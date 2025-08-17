from django.shortcuts import render, get_object_or_404
from django.http import JsonResponse, Http404, HttpResponse
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_http_methods
from django.urls import reverse
from django.conf import settings
import json
import logging
import os
from .models import ProcessingJob, SpeakerTrack
from .forms import FileUploadForm, SpeakerLabelForm
from .services import audio_service, start_processing_job, get_job_status, update_speaker_label, cancel_job

logger = logging.getLogger(__name__)


def index(request):
    """Main upload page"""
    form = FileUploadForm()
    return render(request, 'processor/index.html', {
        'form': form,
        'max_file_size_mb': settings.MAX_UPLOAD_SIZE / (1024 * 1024),
        'allowed_formats': ', '.join(settings.ALLOWED_AUDIO_FORMATS)
    })


@require_http_methods(["POST"])
def upload_file(request):
    """Handle file upload and start processing"""
    try:
        form = FileUploadForm(request.POST, request.FILES)
        
        if form.is_valid():
            uploaded_file = form.cleaned_data['audio_file']
            
            # Create processing job
            job = audio_service.create_processing_job(uploaded_file)
            
            # Start processing in background
            start_processing_job(str(job.job_id))
            
            return JsonResponse({
                'success': True,
                'job_id': str(job.job_id),
                'message': 'File uploaded successfully. Processing started.',
                'redirect_url': reverse('processor:status', kwargs={'job_id': job.job_id})
            })
        else:
            # Return form errors
            errors = []
            for field, field_errors in form.errors.items():
                for error in field_errors:
                    errors.append(f"{field}: {error}")
            
            return JsonResponse({
                'success': False,
                'errors': errors
            }, status=400)
    
    except Exception as e:
        logger.error(f"Upload error: {str(e)}")
        return JsonResponse({
            'success': False,
            'error': 'An unexpected error occurred. Please try again.'
        }, status=500)


def status(request, job_id):
    """Processing status page"""
    try:
        job = get_object_or_404(ProcessingJob, job_id=job_id)
        return render(request, 'processor/status.html', {
            'job': job,
            'job_id': job_id
        })
    except Exception as e:
        logger.error(f"Status page error: {str(e)}")
        return render(request, 'processor/error.html', {
            'error_message': 'Job not found or an error occurred.'
        })


@require_http_methods(["GET"])
def status_api(request, job_id):
    """API endpoint for job status polling"""
    try:
        logger.info(f"Status API called for job {job_id}")
        status_info = get_job_status(job_id)
        logger.info(f"Status API returning: {status_info}")
        
        # If job is completed, include redirect URL
        if status_info['status'] == 'completed':
            status_info['redirect_url'] = reverse('processor:results', kwargs={'job_id': job_id})
        
        return JsonResponse(status_info)
    
    except Exception as e:
        logger.error(f"Status API error: {str(e)}")
        import traceback
        logger.error(f"Status API traceback: {traceback.format_exc()}")
        return JsonResponse({
            'status': 'error',
            'step': 'error',
            'progress': 0,
            'message': 'Error retrieving status'
        }, status=500)


def results(request, job_id):
    """Results page showing separated audio tracks"""
    try:
        job = get_object_or_404(ProcessingJob, job_id=job_id)
        
        if job.status != 'completed':
            return render(request, 'processor/error.html', {
                'error_message': 'Processing not completed yet or failed.'
            })
        
        speaker_tracks = SpeakerTrack.objects.filter(job=job).order_by('speaker_id')
        
        return render(request, 'processor/results.html', {
            'job': job,
            'speaker_tracks': speaker_tracks,
            'form': SpeakerLabelForm()
        })
    
    except Exception as e:
        logger.error(f"Results page error: {str(e)}")
        return render(request, 'processor/error.html', {
            'error_message': 'Error loading results.'
        })


@require_http_methods(["POST"])
def update_speaker_name(request, job_id):
    """Update speaker label via AJAX"""
    try:
        data = json.loads(request.body)
        speaker_id = data.get('speaker_id')
        new_label = data.get('speaker_label', '').strip()
        
        # Validate input
        form = SpeakerLabelForm({
            'speaker_id': speaker_id,
            'speaker_label': new_label
        })
        
        if form.is_valid():
            success = update_speaker_label(job_id, speaker_id, new_label)
            
            if success:
                return JsonResponse({
                    'success': True,
                    'message': 'Speaker name updated successfully'
                })
            else:
                return JsonResponse({
                    'success': False,
                    'error': 'Failed to update speaker name'
                }, status=500)
        else:
            errors = []
            for field, field_errors in form.errors.items():
                for error in field_errors:
                    errors.append(error)
            
            return JsonResponse({
                'success': False,
                'errors': errors
            }, status=400)
    
    except Exception as e:
        logger.error(f"Update speaker name error: {str(e)}")
        return JsonResponse({
            'success': False,
            'error': 'An unexpected error occurred'
        }, status=500)


def download_audio(request, job_id, speaker_id):
    """Download individual speaker audio file"""
    try:
        job = get_object_or_404(ProcessingJob, job_id=job_id)
        speaker_track = get_object_or_404(SpeakerTrack, job=job, speaker_id=speaker_id)
        
        if not os.path.exists(speaker_track.audio_file_path):
            raise Http404("Audio file not found")
        
        # Determine filename for download
        display_name = speaker_track.display_name.replace(' ', '_')
        filename = f"{display_name}_{job.original_filename}"
        
        # Serve file
        with open(speaker_track.audio_file_path, 'rb') as audio_file:
            response = HttpResponse(audio_file.read(), content_type='audio/wav')
            response['Content-Disposition'] = f'attachment; filename="{filename}"'
            return response
    
    except Exception as e:
        logger.error(f"Download error: {str(e)}")
        raise Http404("File not found or error occurred")


@require_http_methods(["POST"])
def cancel_job_view(request, job_id):
    """Cancel a running job"""
    try:
        logger.info(f"Cancel request received for job {job_id}")
        
        # Check if job exists
        job = get_object_or_404(ProcessingJob, job_id=job_id)
        
        # Check if job is in a cancellable state
        if job.status not in ['pending', 'processing']:
            return JsonResponse({
                'success': False,
                'error': f'Job cannot be cancelled. Current status: {job.status}'
            }, status=400)
        
        # Cancel the job
        success = cancel_job(str(job_id))
        
        if success:
            logger.info(f"Job {job_id} cancelled successfully")
            return JsonResponse({
                'success': True,
                'message': 'Job cancelled successfully'
            })
        else:
            logger.error(f"Failed to cancel job {job_id}")
            return JsonResponse({
                'success': False,
                'error': 'Failed to cancel job'
            }, status=500)
    
    except Exception as e:
        logger.error(f"Cancel job error: {str(e)}")
        return JsonResponse({
            'success': False,
            'error': 'An unexpected error occurred'
        }, status=500)


def serve_audio(request, job_id, speaker_id):
    """Serve audio file for HTML5 audio player"""
    try:
        job = get_object_or_404(ProcessingJob, job_id=job_id)
        speaker_track = get_object_or_404(SpeakerTrack, job=job, speaker_id=speaker_id)
        
        if not os.path.exists(speaker_track.audio_file_path):
            raise Http404("Audio file not found")
        
        # Serve audio file
        with open(speaker_track.audio_file_path, 'rb') as audio_file:
            response = HttpResponse(audio_file.read(), content_type='audio/wav')
            response['Accept-Ranges'] = 'bytes'
            return response
    
    except Exception as e:
        logger.error(f"Serve audio error: {str(e)}")
        raise Http404("Audio file not found")
