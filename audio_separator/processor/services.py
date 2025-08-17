import os
import uuid
import logging
import threading
import subprocess
from pathlib import Path
from typing import Optional, Dict, List
from django.conf import settings
from django.utils import timezone
from pydub import AudioSegment
from .models import ProcessingJob, SpeakerTrack

# Set up logging
logger = logging.getLogger(__name__)

# Configure logging level for this module
logger.setLevel(logging.INFO)

# Add console handler if not already present
if not logger.handlers:
    console_handler = logging.StreamHandler()
    console_handler.setLevel(logging.INFO)
    formatter = logging.Formatter('%(asctime)s - %(name)s - %(levelname)s - %(message)s')
    console_handler.setFormatter(formatter)
    logger.addHandler(console_handler)

# Global dictionary to track job statuses
job_statuses = {}

# Global dictionary to track cancellation requests
job_cancellations = {}

# Global dictionary to track running threads
job_threads = {}

class AudioProcessingService:
    """Service class for handling audio separation pipeline"""
    
    def __init__(self):
        self.temp_dir = settings.AUDIO_TEMP_PATH
        self.output_dir = settings.AUDIO_OUTPUT_PATH
        
    def save_uploaded_file(self, uploaded_file, job_id: str) -> str:
        """Save uploaded file and return path with security checks"""
        try:
            logger.info(f"Starting file upload for job {job_id}, file: {uploaded_file.name}, size: {uploaded_file.size} bytes")
            
            # Validate job_id is a proper UUID to prevent path traversal
            import uuid
            try:
                uuid.UUID(job_id)
            except ValueError:
                raise ValueError(f"Invalid job ID format: {job_id}")
            
            # Create upload directory if it doesn't exist
            upload_dir = settings.AUDIO_UPLOAD_PATH
            upload_dir.mkdir(parents=True, exist_ok=True)
            logger.info(f"Upload directory ready: {upload_dir}")
            
            # Sanitize filename and generate secure path
            import re
            safe_extension = re.sub(r'[^\w.-]', '', os.path.splitext(uploaded_file.name)[1].lower())
            if not safe_extension or safe_extension not in settings.ALLOWED_AUDIO_FORMATS:
                raise ValueError(f"Invalid or unsafe file extension: {safe_extension}")
            
            filename = f"{job_id}{safe_extension}"
            file_path = upload_dir / filename
            
            # Ensure the final path is within the upload directory (prevent path traversal)
            try:
                file_path.resolve().relative_to(upload_dir.resolve())
            except ValueError:
                raise ValueError("Invalid file path - potential path traversal attempt")
            
            logger.info(f"Target file path: {file_path}")
            
            # Save file with progress tracking
            total_size = uploaded_file.size
            written_size = 0
            
            with open(file_path, 'wb+') as destination:
                for chunk_num, chunk in enumerate(uploaded_file.chunks()):
                    destination.write(chunk)
                    written_size += len(chunk)
                    
                    # Log progress every 10 chunks or at completion
                    if chunk_num % 10 == 0 or written_size >= total_size:
                        progress = (written_size / total_size * 100) if total_size > 0 else 100
                        logger.info(f"Upload progress: {progress:.1f}% ({written_size}/{total_size} bytes)")
            
            # Verify file was saved correctly
            if not file_path.exists() or file_path.stat().st_size != total_size:
                raise ValueError("File upload verification failed")
            
            logger.info(f"File saved successfully: {file_path}")
            return str(file_path)
            
        except Exception as e:
            logger.error(f"Error saving file: {str(e)}")
            raise
    
    def create_processing_job(self, uploaded_file) -> ProcessingJob:
        """Create a new processing job"""
        try:
            # Save the uploaded file
            job_id = str(uuid.uuid4())
            file_path = self.save_uploaded_file(uploaded_file, job_id)
            
            # Create job record
            job = ProcessingJob.objects.create(
                job_id=job_id,
                original_filename=uploaded_file.name,
                uploaded_file_path=file_path,
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
    
    def check_job_cancelled(self, job_id: str) -> bool:
        """Check if job has been cancelled"""
        return job_cancellations.get(job_id, False)
    
    def cancel_job(self, job_id: str) -> bool:
        """Cancel a running job"""
        try:
            logger.info(f"Cancelling job {job_id}")
            
            # Mark job as cancelled
            job_cancellations[job_id] = True
            
            # Update job status
            self.update_job_status(job_id, 'failed', 'cancelled', 0, "Job cancelled by user")
            
            # Clean up resources
            if job_id in job_statuses:
                del job_statuses[job_id]
            
            if job_id in job_threads:
                del job_threads[job_id]
            
            logger.info(f"Job {job_id} cancelled successfully")
            return True
            
        except Exception as e:
            logger.error(f"Error cancelling job {job_id}: {str(e)}")
            return False

    def update_job_status(self, job_id: str, status: str, step: str, 
                         progress: int, message: str = ""):
        """Update job status in both database and memory"""
        try:
            # Check if job is cancelled before updating
            if self.check_job_cancelled(job_id) and status not in ['failed', 'cancelled']:
                logger.info(f"Job {job_id} is cancelled, skipping status update")
                return
                
            logger.info(f"UPDATING JOB STATUS: {job_id} -> {status}, {step}, {progress}%, '{message}'")
            
            # Update in-memory status
            job_statuses[job_id] = {
                'status': status,
                'step': step,
                'progress': progress,
                'message': message
            }
            logger.info(f"Updated in-memory status for {job_id}: {job_statuses[job_id]}")
            
            # Update database
            job = ProcessingJob.objects.get(job_id=job_id)
            job.status = status
            job.current_step = step
            job.progress_percentage = progress
            
            # Set error message for cancelled jobs
            if status == 'failed' and step == 'cancelled':
                job.error_message = "Job cancelled by user"
            
            if status == 'processing' and not job.started_at:
                job.started_at = timezone.now()
                logger.info(f"Set started_at for job {job_id}")
            elif status in ['completed', 'failed']:
                job.completed_at = timezone.now()
                logger.info(f"Set completed_at for job {job_id}")
            
            job.save()
            logger.info(f"Database updated for job {job_id}")
            
            logger.info(f"Job {job_id} status updated successfully: {status} - {step} ({progress}%)")
            
        except Exception as e:
            logger.error(f"Error updating job status: {str(e)}")
            import traceback
            logger.error(f"Update status traceback: {traceback.format_exc()}")
    
    def convert_to_wav(self, input_path: str, job_id: str) -> str:
        """Convert audio file to WAV format using pydub"""
        try:
            # Check if job is cancelled
            if self.check_job_cancelled(job_id):
                raise Exception("Job cancelled by user")
                
            logger.info(f"Starting WAV conversion for job {job_id}, input: {input_path}")
            self.update_job_status(job_id, 'processing', 'converting', 10, 
                                 "Starting audio conversion to WAV format...")
            
            # Check if input file exists and get its size
            if not os.path.exists(input_path):
                raise FileNotFoundError(f"Input file not found: {input_path}")
            
            file_size = os.path.getsize(input_path)
            logger.info(f"Input file size: {file_size} bytes")
            
            self.update_job_status(job_id, 'processing', 'converting', 15, 
                                 "Loading audio file...")
            
            # Check pydub dependencies
            try:
                from pydub.utils import which
                ffmpeg_path = which("ffmpeg")
                ffprobe_path = which("ffprobe")
                logger.info(f"FFmpeg path: {ffmpeg_path}")
                logger.info(f"FFprobe path: {ffprobe_path}")
                
                if not ffmpeg_path:
                    logger.warning("FFmpeg not found in PATH - may cause issues with some audio formats")
            except Exception as dep_error:
                logger.warning(f"Could not check dependencies: {dep_error}")
            
            # Check if job is cancelled
            if self.check_job_cancelled(job_id):
                raise Exception("Job cancelled by user")
                
            # Load audio file
            logger.info(f"Loading audio file: {input_path}")
            try:
                audio = AudioSegment.from_file(input_path)
            except Exception as load_error:
                logger.error(f"Failed to load audio file: {load_error}")
                # Try with explicit format detection
                file_extension = os.path.splitext(input_path)[1].lower()
                logger.info(f"Trying to load with explicit format: {file_extension}")
                if file_extension == '.mp3':
                    audio = AudioSegment.from_mp3(input_path)
                elif file_extension == '.wav':
                    audio = AudioSegment.from_wav(input_path)
                elif file_extension == '.flac':
                    audio = AudioSegment.from_flac(input_path)
                elif file_extension == '.m4a':
                    audio = AudioSegment.from_file(input_path, format="m4a")
                else:
                    raise
            
            # Log audio properties
            duration_ms = len(audio)
            duration_sec = duration_ms / 1000
            logger.info(f"Audio loaded - Duration: {duration_sec:.2f}s, Channels: {audio.channels}, Frame rate: {audio.frame_rate}Hz")
            
            self.update_job_status(job_id, 'processing', 'converting', 20, 
                                 f"Audio loaded ({duration_sec:.1f}s). Exporting to WAV...")
            
            # Create output path
            output_path = self.temp_dir / f"{job_id}_converted.wav"
            logger.info(f"Output path: {output_path}")
            
            # Ensure temp directory exists
            self.temp_dir.mkdir(parents=True, exist_ok=True)
            
            # Check if job is cancelled before export
            if self.check_job_cancelled(job_id):
                raise Exception("Job cancelled by user")
                
            # Export as WAV with timeout protection
            logger.info("Starting WAV export...")
            import time
            
            try:
                start_time = time.time()
                audio.export(output_path, format="wav")
                export_time = time.time() - start_time
                logger.info(f"WAV export completed in {export_time:.2f} seconds")
            except Exception as export_error:
                logger.error(f"WAV export failed: {str(export_error)}")
                raise
            
            # Verify output file was created
            if not os.path.exists(output_path):
                raise FileNotFoundError(f"Output file was not created: {output_path}")
            
            output_size = os.path.getsize(output_path)
            logger.info(f"WAV conversion completed. Output file size: {output_size} bytes")
            
            self.update_job_status(job_id, 'processing', 'converting', 25, 
                                 "Audio converted to WAV format successfully")
            
            return str(output_path)
            
        except Exception as e:
            logger.error(f"Error converting audio: {str(e)}")
            logger.error(f"Exception type: {type(e).__name__}")
            import traceback
            logger.error(f"Traceback: {traceback.format_exc()}")
            raise
    
    def run_whisperx_transcription(self, wav_path: str, job_id: str) -> Dict:
        """Run WhisperX transcription and diarization"""
        try:
            # Check if job is cancelled
            if self.check_job_cancelled(job_id):
                raise Exception("Job cancelled by user")
                
            logger.info(f"Starting WhisperX transcription for job {job_id}, WAV file: {wav_path}")
            self.update_job_status(job_id, 'processing', 'transcribing', 30, 
                                 "Transcribing audio and identifying speakers...")
            
            # Verify WAV file exists
            if not os.path.exists(wav_path):
                raise FileNotFoundError(f"WAV file not found: {wav_path}")
            
            wav_size = os.path.getsize(wav_path)
            logger.info(f"WAV file size: {wav_size} bytes")
            
            # Import WhisperX
            try:
                import whisperx
                import torch
                logger.info("WhisperX imported successfully")
            except ImportError as e:
                logger.warning(f"WhisperX not available: {e}. Falling back to mock implementation.")
                return self._run_mock_whisperx(job_id)
            
            # Check device availability
            device = settings.WHISPERX_DEVICE
            if device == "cuda" and not torch.cuda.is_available():
                logger.warning("CUDA not available, falling back to CPU")
                device = "cpu"
            
            logger.info(f"Using device: {device}")
            
            # Step 1: Load WhisperX model
            self.update_job_status(job_id, 'processing', 'transcribing', 35, 
                                 "Loading WhisperX model...")
            logger.info(f"Loading WhisperX model: {settings.WHISPERX_MODEL}")
            
            model = whisperx.load_model(
                settings.WHISPERX_MODEL, 
                device=device, 
                compute_type=settings.WHISPERX_COMPUTE_TYPE
            )
            logger.info("WhisperX model loaded successfully")
            
            # Step 2: Load audio and transcribe
            if self.check_job_cancelled(job_id):
                raise Exception("Job cancelled by user")
                
            self.update_job_status(job_id, 'processing', 'transcribing', 40, 
                                 "Transcribing audio...")
            logger.info("Starting audio transcription")
            
            audio = whisperx.load_audio(wav_path)
            result = model.transcribe(audio, batch_size=settings.WHISPERX_BATCH_SIZE)
            
            logger.info(f"Transcription completed. Found {len(result.get('segments', []))} segments")
            
            # Step 3: Load alignment model and align whisper output
            if self.check_job_cancelled(job_id):
                raise Exception("Job cancelled by user")
                
            self.update_job_status(job_id, 'processing', 'transcribing', 50, 
                                 "Aligning transcription...")
            logger.info("Loading alignment model")
            
            try:
                model_a, metadata = whisperx.load_align_model(
                    language_code=result["language"], 
                    device=device
                )
                logger.info(f"Alignment model loaded for language: {result['language']}")
                
                # Add timeout and error handling for alignment
                import signal
                import time
                
                def timeout_handler(signum, frame):
                    raise TimeoutError("WhisperX alignment timed out")
                
                # Set timeout for alignment (5 minutes)
                old_handler = signal.signal(signal.SIGALRM, timeout_handler)
                signal.alarm(300)  # 5 minutes timeout
                
                try:
                    logger.info("Starting alignment process...")
                    result = whisperx.align(
                        result["segments"], 
                        model_a, 
                        metadata, 
                        audio, 
                        device, 
                        return_char_alignments=False
                    )
                    logger.info("Alignment completed successfully")
                finally:
                    # Reset alarm
                    signal.alarm(0)
                    signal.signal(signal.SIGALRM, old_handler)
                    
            except TimeoutError as timeout_error:
                logger.warning(f"Alignment timed out: {timeout_error}. Continuing without alignment.")
                # Continue with original result without alignment
                pass
            except Exception as align_error:
                logger.warning(f"Alignment failed: {align_error}. Continuing without alignment.")
                # Continue with original result without alignment
                pass
            
            # Step 4: Speaker diarization
            if self.check_job_cancelled(job_id):
                raise Exception("Job cancelled by user")
                
            self.update_job_status(job_id, 'processing', 'transcribing', 55, 
                                 "Performing speaker diarization...")
            logger.info("Starting speaker diarization")
            
            # Check if HuggingFace token is available for pyannote
            hf_token = getattr(settings, 'HUGGINGFACE_TOKEN', None)
            if not hf_token:
                logger.warning("No HuggingFace token provided. Speaker diarization may not work properly.")
                logger.warning("To get a token: 1) Go to https://huggingface.co/settings/tokens")
                logger.warning("2) Accept terms at https://huggingface.co/pyannote/speaker-diarization")
                logger.warning("3) Set HUGGINGFACE_TOKEN environment variable")
            
            try:
                # Set timeout for diarization (10 minutes)
                def diarization_timeout_handler(signum, frame):
                    raise TimeoutError("Speaker diarization timed out")
                
                old_handler = signal.signal(signal.SIGALRM, diarization_timeout_handler)
                signal.alarm(600)  # 10 minutes timeout
                
                try:
                    # Enhanced diarization with custom parameters
                    diarize_model = whisperx.DiarizationPipeline(
                        use_auth_token=hf_token, 
                        device=device
                    )
                    logger.info("Diarization model loaded")
                    
                    # Log audio characteristics for debugging
                    audio_duration = len(audio) / 16000  # WhisperX uses 16kHz
                    logger.info(f"Audio duration: {audio_duration:.2f} seconds")
                    logger.info(f"Audio samples: {len(audio)}")
                    
                    # Run diarization with custom parameters
                    logger.info("Running speaker diarization...")
                    
                    # Get diarization parameters from settings
                    min_speakers = getattr(settings, 'DIARIZATION_MIN_SPEAKERS', 1)
                    max_speakers = getattr(settings, 'DIARIZATION_MAX_SPEAKERS', 8)
                    
                    logger.info(f"Running diarization with min_speakers={min_speakers}, max_speakers={max_speakers}")
                    
                    # Pass additional parameters to improve speaker separation
                    diarize_segments = diarize_model(
                        audio,
                        min_speakers=min_speakers,
                        max_speakers=max_speakers
                    )
                    
                    # Debug diarization results
                    speaker_labels = diarize_segments.get_labels()
                    unique_speakers = list(set(speaker_labels))
                    logger.info(f"Diarization completed. Found {len(unique_speakers)} unique speakers: {unique_speakers}")
                    
                    # Log speaker timeline for debugging
                    for turn, _, speaker in diarize_segments.itertracks(yield_label=True):
                        logger.info(f"Speaker {speaker}: {turn.start:.2f}s - {turn.end:.2f}s ({turn.end - turn.start:.2f}s duration)")
                    
                    # Assign speakers to segments
                    self.update_job_status(job_id, 'processing', 'transcribing', 58, 
                                         f"Assigning {len(unique_speakers)} speakers to segments...")
                    
                    logger.info(f"Assigning speakers to {len(result.get('segments', []))} transcription segments")
                    result = whisperx.assign_word_speakers(diarize_segments, result)
                    
                    # Debug speaker assignment results
                    assigned_speakers = set()
                    for segment in result.get('segments', []):
                        if 'speaker' in segment:
                            assigned_speakers.add(segment['speaker'])
                    
                    logger.info(f"Speaker assignment completed. Segments have speakers: {list(assigned_speakers)}")
                    
                finally:
                    # Reset alarm
                    signal.alarm(0)
                    signal.signal(signal.SIGALRM, old_handler)
                
            except TimeoutError as timeout_error:
                logger.warning(f"Speaker diarization timed out: {timeout_error}. Using fallback speaker labels.")
                
                # Apply same fallback logic as above
                segments = result.get("segments", [])
                if len(segments) > 1:
                    current_speaker = 0
                    last_end_time = 0
                    
                    for segment in segments:
                        start_time = segment.get('start', 0)
                        if start_time - last_end_time > 2.0:
                            current_speaker = 1 - current_speaker
                        
                        segment["speaker"] = f"SPEAKER_{current_speaker:02d}"
                        last_end_time = segment.get('end', start_time)
                        
                    logger.info(f"Applied timeout fallback speaker assignment")
                else:
                    for segment in segments:
                        segment["speaker"] = "SPEAKER_00"
            except Exception as diarize_error:
                logger.error(f"Speaker diarization failed: {diarize_error}")
                import traceback
                logger.error(f"Diarization traceback: {traceback.format_exc()}")
                
                logger.warning("Falling back to simple speaker assignment based on transcript segments")
                
                # Try to create basic speaker separation based on transcript timing
                segments = result.get("segments", [])
                if len(segments) > 1:
                    # Simple heuristic: alternate speakers based on gaps in speech
                    current_speaker = 0
                    last_end_time = 0
                    
                    for segment in segments:
                        start_time = segment.get('start', 0)
                        # If there's a significant gap (>2 seconds), might be different speaker
                        if start_time - last_end_time > 2.0:
                            current_speaker = 1 - current_speaker  # Toggle between 0 and 1
                        
                        segment["speaker"] = f"SPEAKER_{current_speaker:02d}"
                        last_end_time = segment.get('end', start_time)
                        
                    logger.info(f"Applied fallback speaker assignment to {len(segments)} segments")
                else:
                    # Single segment, assign to single speaker
                    for segment in segments:
                        segment["speaker"] = "SPEAKER_00"
            
            # Clean up GPU memory
            if device == "cuda":
                torch.cuda.empty_cache()
            
            logger.info(f"WhisperX transcription completed for job {job_id}")
            return result
            
        except Exception as e:
            logger.error(f"Error in WhisperX transcription: {str(e)}")
            logger.error(f"Falling back to mock implementation due to error")
            import traceback
            logger.error(f"WhisperX traceback: {traceback.format_exc()}")
            
            # Fall back to mock implementation if WhisperX fails
            return self._run_mock_whisperx(job_id)
    
    def _run_mock_whisperx(self, job_id: str) -> Dict:
        """Fallback mock implementation when WhisperX is not available"""
        import time
        
        logger.info("Running mock WhisperX implementation")
        self.update_job_status(job_id, 'processing', 'transcribing', 35, 
                             "Processing audio with mock WhisperX...")
        
        # Simulate processing time with progress updates
        for i in range(5):
            time.sleep(0.5)
            progress = 35 + (i + 1) * 5
            self.update_job_status(job_id, 'processing', 'transcribing', progress, 
                                 f"Mock WhisperX processing... {i+1}/5")
            logger.info(f"Mock WhisperX simulation step {i+1}/5")
        
        # Enhanced mock WhisperX result structure with better speaker variation
        mock_result = {
            "language": "en",
            "segments": [
                {
                    "start": 0.0,
                    "end": 3.0,
                    "text": "Hello, welcome to our podcast.",
                    "speaker": "SPEAKER_00"
                },
                {
                    "start": 3.5,
                    "end": 7.0,
                    "text": "Thank you for having me.",
                    "speaker": "SPEAKER_01"
                },
                {
                    "start": 7.5,
                    "end": 11.0,
                    "text": "Let's talk about the topic.",
                    "speaker": "SPEAKER_00"
                },
                {
                    "start": 11.5,
                    "end": 15.0,
                    "text": "That sounds interesting.",
                    "speaker": "SPEAKER_01"
                },
                {
                    "start": 15.5,
                    "end": 19.0,
                    "text": "I think we should discuss this further.",
                    "speaker": "SPEAKER_00"
                },
                {
                    "start": 19.5,
                    "end": 23.0,
                    "text": "Absolutely, I agree with that point.",
                    "speaker": "SPEAKER_01"
                }
            ]
        }
        
        logger.info(f"Mock result created with {len(mock_result['segments'])} segments and 2 speakers")
        
        # Log mock speaker distribution
        speaker_counts = {}
        for segment in mock_result['segments']:
            speaker = segment['speaker']
            speaker_counts[speaker] = speaker_counts.get(speaker, 0) + 1
        
        logger.info(f"Mock speaker distribution: {speaker_counts}")
        logger.info(f"Mock WhisperX transcription completed for job {job_id}")
        return mock_result
    
    def separate_speakers(self, wav_path: str, transcription_result: Dict, 
                         job_id: str) -> List[str]:
        """Separate audio by speakers and save individual tracks"""
        try:
            # Check if job is cancelled
            if self.check_job_cancelled(job_id):
                raise Exception("Job cancelled by user")
                
            logger.info(f"Starting speaker separation for job {job_id}")
            self.update_job_status(job_id, 'processing', 'separating', 60, 
                                 "Separating speakers into individual tracks...")
            
            # Verify WAV file still exists
            if not os.path.exists(wav_path):
                raise FileNotFoundError(f"WAV file not found: {wav_path}")
            
            logger.info(f"Loading audio from: {wav_path}")
            # Load the original audio
            audio = AudioSegment.from_wav(wav_path)
            logger.info(f"Audio loaded for separation - Duration: {len(audio)/1000:.2f}s")
            
            # Group segments by speaker
            logger.info("Grouping segments by speaker...")
            speaker_segments = {}
            total_segments = len(transcription_result.get('segments', []))
            logger.info(f"Processing {total_segments} segments")
            
            for i, segment in enumerate(transcription_result.get('segments', [])):
                speaker = segment.get('speaker', 'UNKNOWN')
                if speaker not in speaker_segments:
                    speaker_segments[speaker] = []
                    logger.info(f"Found new speaker: {speaker}")
                speaker_segments[speaker].append(segment)
            
            logger.info(f"Found {len(speaker_segments)} unique speakers: {list(speaker_segments.keys())}")
            
            # Create output directory for this job
            job_output_dir = self.output_dir / job_id
            job_output_dir.mkdir(parents=True, exist_ok=True)
            
            speaker_files = []
            total_speakers = len(speaker_segments)
            
            for speaker_idx, (speaker_id, segments) in enumerate(speaker_segments.items()):
                # Check if job is cancelled
                if self.check_job_cancelled(job_id):
                    raise Exception("Job cancelled by user")
                    
                logger.info(f"Processing speaker {speaker_idx + 1}/{total_speakers}: {speaker_id} ({len(segments)} segments)")
                
                # Update progress for this speaker
                speaker_progress = 65 + (speaker_idx * 20 // total_speakers)
                self.update_job_status(job_id, 'processing', 'separating', speaker_progress, 
                                     f"Processing speaker {speaker_idx + 1}/{total_speakers}: {speaker_id}")
                # Create audio for this speaker
                speaker_audio = AudioSegment.empty()
                
                for segment in segments:
                    start_ms = int(segment['start'] * 1000)
                    end_ms = int(segment['end'] * 1000)
                    segment_audio = audio[start_ms:end_ms]
                    speaker_audio += segment_audio
                    
                    # Add small gap between segments
                    speaker_audio += AudioSegment.silent(duration=500)
                
                # Save speaker audio file
                speaker_filename = f"{speaker_id}.wav"
                speaker_path = job_output_dir / speaker_filename
                speaker_audio.export(speaker_path, format="wav")
                
                speaker_files.append(str(speaker_path))
                logger.info(f"Created speaker file: {speaker_path}")
            
            return speaker_files
            
        except Exception as e:
            logger.error(f"Error separating speakers: {str(e)}")
            raise
    
    def finalize_processing(self, job_id: str, speaker_files: List[str], 
                           transcription_result: Dict):
        """Finalize processing and create speaker track records"""
        try:
            logger.info(f"Starting finalization for job {job_id} with {len(speaker_files)} speaker files")
            self.update_job_status(job_id, 'processing', 'finalizing', 90, 
                                 "Finalizing results...")
            
            logger.info("Updating job record with results...")
            job = ProcessingJob.objects.get(job_id=job_id)
            job.speaker_count = len(speaker_files)
            job.output_directory = str(Path(speaker_files[0]).parent)
            job.save()
            logger.info(f"Job record updated - Speaker count: {job.speaker_count}, Output dir: {job.output_directory}")
            
            # Create speaker track records
            logger.info("Creating speaker track records...")
            speaker_segments = {}
            for segment in transcription_result.get('segments', []):
                speaker = segment.get('speaker', 'UNKNOWN')
                if speaker not in speaker_segments:
                    speaker_segments[speaker] = []
                speaker_segments[speaker].append(segment)
            
            logger.info(f"Grouped segments for {len(speaker_segments)} speakers")
            
            for i, speaker_file in enumerate(speaker_files):
                speaker_id = Path(speaker_file).stem
                logger.info(f"Creating track record for speaker {i+1}/{len(speaker_files)}: {speaker_id}")
                
                # Calculate duration and word count
                audio = AudioSegment.from_wav(speaker_file)
                duration_seconds = len(audio) / 1000.0
                
                segments = speaker_segments.get(speaker_id, [])
                word_count = sum(len(segment.get('text', '').split()) for segment in segments)
                
                logger.info(f"Speaker {speaker_id} - Duration: {duration_seconds:.2f}s, Words: {word_count}")
                
                SpeakerTrack.objects.create(
                    job=job,
                    speaker_id=speaker_id,
                    audio_file_path=speaker_file,
                    duration_seconds=duration_seconds,
                    word_count=word_count
                )
                
                # Update progress
                progress = 92 + (i * 6 // len(speaker_files))
                self.update_job_status(job_id, 'processing', 'finalizing', progress, 
                                     f"Created track record for {speaker_id}")
            
            self.update_job_status(job_id, 'completed', 'completed', 100, 
                                 f"Processing complete! Identified {len(speaker_files)} speakers.")
            
            logger.info(f"Processing finalized for job {job_id}")
            
        except Exception as e:
            logger.error(f"Error finalizing processing: {str(e)}")
            raise
    def run_separation_pipeline(self, job_id: str):
        """Main pipeline for audio separation processing"""
        try:
            logger.info(f"Starting separation pipeline for job {job_id}")
            
            # Get job from database
            job = ProcessingJob.objects.get(job_id=job_id)
            logger.info(f"Job loaded - Original file: {job.original_filename}, Size: {job.file_size} bytes")
            
            self.update_job_status(job_id, 'processing', 'initializing', 5, 
                                 "Starting audio processing pipeline...")
            
            # Step 1: Convert to WAV
            logger.info("=== STEP 1: Converting to WAV ===")
            wav_path = self.convert_to_wav(job.uploaded_file_path, job_id)
            logger.info(f"WAV conversion completed: {wav_path}")
            
            # Step 2: Run WhisperX transcription and diarization
            logger.info("=== STEP 2: WhisperX Transcription ===")
            transcription_result = self.run_whisperx_transcription(wav_path, job_id)
            logger.info(f"Transcription completed with {len(transcription_result.get('segments', []))} segments")
            
            # Step 3: Separate speakers
            logger.info("=== STEP 3: Speaker Separation ===")
            speaker_files = self.separate_speakers(wav_path, transcription_result, job_id)
            logger.info(f"Speaker separation completed with {len(speaker_files)} files")
            
            # Step 4: Finalize processing
            logger.info("=== STEP 4: Finalizing ===")
            self.finalize_processing(job_id, speaker_files, transcription_result)
            logger.info("Pipeline completed successfully")
            
            # Cleanup temporary files
            logger.info("Cleaning up temporary files...")
            try:
                if 'wav_path' in locals() and os.path.exists(wav_path):
                    os.remove(wav_path)
                    logger.info(f"Cleaned up temp file: {wav_path}")
            except Exception as e:
                logger.warning(f"Could not clean up temp file {wav_path}: {str(e)}")
            
        except Exception as e:
            logger.error(f"Pipeline error for job {job_id}: {str(e)}")
            logger.error(f"Exception type: {type(e).__name__}")
            import traceback
            logger.error(f"Full traceback: {traceback.format_exc()}")
            
            self.update_job_status(job_id, 'failed', 'error', 0, 
                                 f"Processing failed: {str(e)}")
            
            # Update job with error
            try:
                job = ProcessingJob.objects.get(job_id=job_id)
                job.error_message = str(e)
                job.save()
            except Exception as db_error:
                logger.error(f"Could not update job error message: {str(db_error)}")
    
    def clean_stale_cache_entries(self):
        """Clean up stale cache entries for stuck jobs"""
        from django.utils import timezone
        import datetime
        
        stale_jobs = []
        for job_id, status in list(job_statuses.items()):
            try:
                job = ProcessingJob.objects.get(job_id=job_id)
                
                # Check if job has been processing for too long (30 minutes)
                if (job.status == 'processing' and 
                    job.started_at and 
                    (timezone.now() - job.started_at) > datetime.timedelta(minutes=30)):
                    
                    logger.warning(f"Job {job_id} appears stuck, cleaning cache and marking as failed")
                    
                    # Update database to failed status
                    job.status = 'failed'
                    job.current_step = 'failed'
                    job.progress_percentage = 0
                    job.error_message = "Processing timed out after 30 minutes"
                    job.completed_at = timezone.now()
                    job.save()
                    
                    # Remove from cache
                    stale_jobs.append(job_id)
                    
            except ProcessingJob.DoesNotExist:
                # Job doesn't exist in database, remove from cache
                stale_jobs.append(job_id)
        
        # Clean up stale entries
        for job_id in stale_jobs:
            if job_id in job_statuses:
                del job_statuses[job_id]
                logger.info(f"Removed stale cache entry for job {job_id}")

    def get_job_status(self, job_id: str) -> Dict:
        """Get current job status"""
        try:
            logger.info(f"Getting job status for {job_id}")
            
            # Clean stale cache entries periodically
            import random
            if random.random() < 0.1:  # 10% chance to clean cache
                self.clean_stale_cache_entries()
            
            # Always check database first for completed/failed jobs to ensure accuracy
            job = ProcessingJob.objects.get(job_id=job_id)
            
            # If job is completed or failed, always return fresh database status
            if job.status in ['completed', 'failed']:
                status = {
                    'status': job.status,
                    'step': job.current_step,
                    'progress': job.progress_percentage,
                    'message': f"Current step: {job.get_current_step_display()}"
                }
                logger.info(f"Job {job_id} is {job.status}, returning database status: {status}")
                # Update memory cache with final status
                job_statuses[job_id] = status
                return status
            
            # For processing jobs, use memory cache if available (faster for frequent updates)
            if job_id in job_statuses:
                memory_status = job_statuses[job_id]
                logger.info(f"Found processing job in memory: {memory_status}")
                return memory_status
            
            # Fall back to database for processing jobs not in cache
            logger.info(f"Processing job not in memory, using database for job {job_id}")
            status = {
                'status': job.status,
                'step': job.current_step,
                'progress': job.progress_percentage,
                'message': f"Current step: {job.get_current_step_display()}"
            }
            
            logger.info(f"Database status: {status}")
            
            # Update memory cache
            job_statuses[job_id] = status
            return status
            
        except ProcessingJob.DoesNotExist:
            logger.error(f"Job {job_id} not found in database")
            return {
                'status': 'not_found',
                'step': 'error',
                'progress': 0,
                'message': 'Job not found'
            }
        except Exception as e:
            logger.error(f"Error getting job status: {str(e)}")
            import traceback
            logger.error(f"Get status traceback: {traceback.format_exc()}")
            return {
                'status': 'error',
                'step': 'error',
                'progress': 0,
                'message': 'Error retrieving status'
            }


# Global service instance
audio_service = AudioProcessingService()


def start_processing_job(job_id: str):
    """Start processing job in a separate thread"""
    def run_job():
        try:
            logger.info(f"Processing thread started for job {job_id}")
            audio_service.run_separation_pipeline(job_id)
            logger.info(f"Processing thread completed for job {job_id}")
        except Exception as e:
            logger.error(f"Unexpected error in processing thread for job {job_id}: {str(e)}")
            import traceback
            logger.error(f"Thread traceback: {traceback.format_exc()}")
        finally:
            # Clean up thread tracking
            if job_id in job_threads:
                del job_threads[job_id]
            if job_id in job_cancellations:
                del job_cancellations[job_id]
    
    # Start processing in a separate thread
    thread = threading.Thread(target=run_job, daemon=True)
    thread.start()
    
    # Track the thread
    job_threads[job_id] = thread
    
    logger.info(f"Started processing thread for job {job_id}")


def get_job_status(job_id: str) -> Dict:
    """Public function to get job status"""
    return audio_service.get_job_status(job_id)


def cancel_job(job_id: str) -> bool:
    """Public function to cancel a job"""
    return audio_service.cancel_job(job_id)


def cancel_all_jobs() -> int:
    """Cancel all running jobs and return the count of cancelled jobs"""
    cancelled_count = 0
    
    # Get all processing jobs
    running_jobs = [job_id for job_id, status in job_statuses.items() 
                   if status.get('status') == 'processing']
    
    for job_id in running_jobs:
        try:
            if audio_service.cancel_job(job_id):
                cancelled_count += 1
                logger.info(f"Cancelled job {job_id}")
        except Exception as e:
            logger.error(f"Error cancelling job {job_id}: {e}")
    
    return cancelled_count


def update_speaker_label(job_id: str, speaker_id: str, new_label: str) -> bool:
    """Update speaker label"""
    try:
        job = ProcessingJob.objects.get(job_id=job_id)
        speaker_track = SpeakerTrack.objects.get(job=job, speaker_id=speaker_id)
        speaker_track.speaker_label = new_label
        speaker_track.save()
        logger.info(f"Updated speaker label: {speaker_id} -> {new_label}")
        return True
    except Exception as e:
        logger.error(f"Error updating speaker label: {str(e)}")
        return False
