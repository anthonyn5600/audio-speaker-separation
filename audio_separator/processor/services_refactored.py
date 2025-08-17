import os
import uuid
import logging
import asyncio
from pathlib import Path
from typing import Optional, Dict, List, Any
from django.conf import settings
from django.utils import timezone
from django.db import transaction
from asgiref.sync import sync_to_async, async_to_sync
from pydub import AudioSegment
from .models import ProcessingJob, SpeakerTrack

# Set up logging
logger = logging.getLogger(__name__)

# Global dictionary to track job statuses (in production, use Redis/Celery)
job_statuses = {}

class AudioProcessingService:
    """Service class for handling audio separation pipeline with async safety"""
    
    def __init__(self):
        self.temp_dir = settings.AUDIO_TEMP_PATH
        self.output_dir = settings.AUDIO_OUTPUT_PATH
        self._ensure_directories()
    
    def _ensure_directories(self):
        """Ensure all required directories exist"""
        for path in [self.temp_dir, self.output_dir, settings.AUDIO_UPLOAD_PATH]:
            path.mkdir(parents=True, exist_ok=True)
    
    @sync_to_async
    def save_uploaded_file(self, uploaded_file, job_id: str) -> str:
        """Save uploaded file and return path - thread-safe"""
        try:
            # Generate secure filename to prevent path traversal
            file_extension = os.path.splitext(uploaded_file.name)[1].lower()
            if file_extension not in settings.ALLOWED_AUDIO_FORMATS:
                raise ValueError(f"Invalid file extension: {file_extension}")
            
            # Create secure filename
            filename = f"{job_id}{file_extension}"
            file_path = settings.AUDIO_UPLOAD_PATH / filename
            
            # Ensure we're writing within allowed directory
            if not str(file_path).startswith(str(settings.AUDIO_UPLOAD_PATH)):
                raise ValueError("Invalid file path detected")
            
            # Save file with size validation
            total_size = 0
            with open(file_path, 'wb+') as destination:
                for chunk in uploaded_file.chunks():
                    total_size += len(chunk)
                    if total_size > settings.MAX_UPLOAD_SIZE:
                        destination.close()
                        os.remove(file_path)
                        raise ValueError("File too large")
                    destination.write(chunk)
            
            logger.info(f"File saved securely: {file_path}")
            return str(file_path)
            
        except Exception as e:
            logger.error(f"Error saving file: {str(e)}")
            raise
    
    @sync_to_async
    def create_processing_job(self, uploaded_file) -> ProcessingJob:
        """Create a new processing job with database transaction"""
        try:
            job_id = str(uuid.uuid4())
            
            with transaction.atomic():
                # Save the uploaded file
                file_path = sync_to_async(self.save_uploaded_file)(uploaded_file, job_id)
                
                # Create job record
                job = ProcessingJob.objects.create(
                    job_id=job_id,
                    original_filename=uploaded_file.name[:255],  # Prevent overflow
                    uploaded_file_path=str(file_path),
                    file_size=uploaded_file.size,
                    status='pending'
                )
            
            # Initialize job status
            job_statuses[job_id] = {
                'status': 'pending',
                'step': 'uploaded',
                'progress': 0,
                'message': 'File uploaded successfully'
            }
            
            logger.info(f"Created processing job: {job_id}")
            return job
            
        except Exception as e:
            logger.error(f"Error creating job: {str(e)}")
            raise
    
    async def update_job_status(self, job_id: str, status: str, step: str, 
                               progress: int, message: str = ""):
        """Update job status with async database operations"""
        try:
            # Update in-memory status
            job_statuses[job_id] = {
                'status': status,
                'step': step,
                'progress': progress,
                'message': message
            }
            
            # Update database asynchronously
            @sync_to_async
            def update_db():
                try:
                    with transaction.atomic():
                        job = ProcessingJob.objects.select_for_update().get(job_id=job_id)
                        job.status = status
                        job.current_step = step
                        job.progress_percentage = progress
                        
                        if status == 'processing' and not job.started_at:
                            job.started_at = timezone.now()
                        elif status in ['completed', 'failed']:
                            job.completed_at = timezone.now()
                        
                        job.save()
                except Exception as e:
                    logger.error(f"Database update failed: {str(e)}")
            
            await update_db()
            logger.info(f"Job {job_id} status updated: {status} - {step} ({progress}%)")
            
        except Exception as e:
            logger.error(f"Error updating job status: {str(e)}")
    
    async def convert_to_wav(self, input_path: str, job_id: str) -> str:
        """Convert audio file to WAV format using async file operations"""
        try:
            await self.update_job_status(job_id, 'processing', 'converting', 10, 
                                       "Converting audio to WAV format...")
            
            # Use async file operations
            @sync_to_async
            def convert_file():
                audio = AudioSegment.from_file(input_path)
                output_path = self.temp_dir / f"{job_id}_converted.wav"
                audio.export(output_path, format="wav")
                return str(output_path)
            
            output_path = await convert_file()
            logger.info(f"Audio converted to WAV: {output_path}")
            return output_path
            
        except Exception as e:
            logger.error(f"Error converting audio: {str(e)}")
            raise
    async def finalize_processing(self, job_id: str, speaker_files: List[str], 
                                 transcription_result: Dict[str, Any]):
        """Finalize processing with async database operations"""
        try:
            await self.update_job_status(job_id, 'processing', 'finalizing', 90, 
                                       "Finalizing results...")
            
            @sync_to_async
            def update_database():
                with transaction.atomic():
                    job = ProcessingJob.objects.select_for_update().get(job_id=job_id)
                    job.speaker_count = len(speaker_files)
                    if speaker_files:
                        job.output_directory = str(Path(speaker_files[0]).parent)
                    job.save()
                    
                    # Create speaker track records
                    speaker_segments = {}
                    for segment in transcription_result.get('segments', []):
                        speaker = segment.get('speaker', 'UNKNOWN')
                        if speaker not in speaker_segments:
                            speaker_segments[speaker] = []
                        speaker_segments[speaker].append(segment)
                    
                    # Create SpeakerTrack objects
                    tracks_to_create = []
                    for speaker_file in speaker_files:
                        speaker_id = Path(speaker_file).stem
                        
                        # Calculate audio duration safely
                        try:
                            audio = AudioSegment.from_wav(speaker_file)
                            duration_seconds = len(audio) / 1000.0
                        except Exception as e:
                            logger.warning(f"Could not calculate duration for {speaker_file}: {e}")
                            duration_seconds = 0.0
                        
                        # Calculate word count
                        segments = speaker_segments.get(speaker_id, [])
                        word_count = sum(
                            len(segment.get('text', '').split()) 
                            for segment in segments
                        )
                        
                        tracks_to_create.append(SpeakerTrack(
                            job=job,
                            speaker_id=speaker_id,
                            audio_file_path=speaker_file,
                            duration_seconds=duration_seconds,
                            word_count=word_count
                        ))
                    
                    # Bulk create for better performance
                    SpeakerTrack.objects.bulk_create(tracks_to_create)
            
            await update_database()
            
            await self.update_job_status(job_id, 'completed', 'completed', 100, 
                                       f"Processing complete! Identified {len(speaker_files)} speakers.")
            
            logger.info(f"Processing finalized for job {job_id}")
            
        except Exception as e:
            logger.error(f"Error finalizing processing: {str(e)}")
            raise
    
    async def run_separation_pipeline(self, job_id: str):
        """Main async pipeline for audio separation processing"""
        try:
            # Get job from database
            @sync_to_async
            def get_job():
                return ProcessingJob.objects.get(job_id=job_id)
            
            job = await get_job()
            
            await self.update_job_status(job_id, 'processing', 'converting', 5, 
                                       "Starting audio processing...")
            
            # Step 1: Convert to WAV
            wav_path = await self.convert_to_wav(job.uploaded_file_path, job_id)
            
            # Step 2: Run WhisperX transcription and diarization
            transcription_result = await self.run_whisperx_transcription(wav_path, job_id)
            
            # Step 3: Separate speakers
            speaker_files = await self.separate_speakers(wav_path, transcription_result, job_id)
            
            # Step 4: Finalize processing
            await self.finalize_processing(job_id, speaker_files, transcription_result)
            
            # Cleanup temporary files
            await self._cleanup_temp_files(wav_path)
            
        except Exception as e:
            logger.error(f"Pipeline error for job {job_id}: {str(e)}")
            await self.update_job_status(job_id, 'failed', 'error', 0, 
                                       f"Processing failed: {str(e)}")
            
            # Update job with error in database
            @sync_to_async
            def update_error():
                try:
                    job = ProcessingJob.objects.get(job_id=job_id)
                    job.error_message = str(e)[:500]  # Truncate long error messages
                    job.save()
                except Exception as db_error:
                    logger.error(f"Could not update job error message: {str(db_error)}")
            
            await update_error()
    
    async def _cleanup_temp_files(self, *file_paths):
        """Safely cleanup temporary files"""
        @sync_to_async
        def cleanup():
            for file_path in file_paths:
                try:
                    if file_path and os.path.exists(file_path):
                        os.remove(file_path)
                        logger.info(f"Cleaned up temp file: {file_path}")
                except Exception as e:
                    logger.warning(f"Could not clean up temp file {file_path}: {str(e)}")
        
        await cleanup()
    
    async def get_job_status(self, job_id: str) -> Dict[str, Any]:
        """Get current job status with async database fallback"""
        try:
            # Try to get from memory first (faster)
            if job_id in job_statuses:
                return job_statuses[job_id]
            
            # Fall back to database
            @sync_to_async
            def get_from_db():
                try:
                    job = ProcessingJob.objects.get(job_id=job_id)
                    return {
                        'status': job.status,
                        'step': job.current_step,
                        'progress': job.progress_percentage,
                        'message': f"Current step: {job.get_current_step_display()}"
                    }
                except ProcessingJob.DoesNotExist:
                    return {
                        'status': 'not_found',
                        'step': 'error',
                        'progress': 0,
                        'message': 'Job not found'
                    }
            
            status = await get_from_db()
            
            # Update memory cache
            job_statuses[job_id] = status
            return status
            
        except Exception as e:
            logger.error(f"Error getting job status: {str(e)}")
            return {
                'status': 'error',
                'step': 'error',
                'progress': 0,
                'message': 'Error retrieving status'
            }


# Global service instance
audio_service = AudioProcessingService()


async def start_processing_job_async(job_id: str):
    """Start processing job asynchronously"""
    try:
        await audio_service.run_separation_pipeline(job_id)
    except Exception as e:
        logger.error(f"Unexpected error in async processing: {str(e)}")


def start_processing_job(job_id: str):
    """Start processing job - wrapper for backwards compatibility"""
    # Use asyncio to run the async function
    try:
        asyncio.create_task(start_processing_job_async(job_id))
        logger.info(f"Started async processing for job {job_id}")
    except Exception as e:
        # Fallback to thread-based processing for compatibility
        import threading
        def run_sync_job():
            try:
                async_to_sync(audio_service.run_separation_pipeline)(job_id)
            except Exception as thread_error:
                logger.error(f"Thread-based processing failed: {str(thread_error)}")
        
        thread = threading.Thread(target=run_sync_job, daemon=True)
        thread.start()
        logger.info(f"Started thread-based processing for job {job_id}")


async def get_job_status_async(job_id: str) -> Dict[str, Any]:
    """Async function to get job status"""
    return await audio_service.get_job_status(job_id)


def get_job_status(job_id: str) -> Dict[str, Any]:
    """Sync wrapper for getting job status"""
    try:
        return async_to_sync(get_job_status_async)(job_id)
    except Exception as e:
        logger.error(f"Error in sync get_job_status: {str(e)}")
        return {
            'status': 'error',
            'step': 'error',
            'progress': 0,
            'message': 'Error retrieving status'
        }


@sync_to_async
def update_speaker_label(job_id: str, speaker_id: str, new_label: str) -> bool:
    """Update speaker label with database transaction"""
    try:
        with transaction.atomic():
            job = ProcessingJob.objects.select_for_update().get(job_id=job_id)
            speaker_track = SpeakerTrack.objects.select_for_update().get(
                job=job, speaker_id=speaker_id
            )
            
            # Sanitize label input
            sanitized_label = new_label.strip()[:100]  # Prevent overflow
            speaker_track.speaker_label = sanitized_label
            speaker_track.save()
            
        logger.info(f"Updated speaker label: {speaker_id} -> {sanitized_label}")
        return True
    except Exception as e:
        logger.error(f"Error updating speaker label: {str(e)}")
        return False
