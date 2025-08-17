import json
import logging
import mimetypes
import os
from django.shortcuts import render, get_object_or_404
from django.http import JsonResponse, Http404, HttpResponse, FileResponse
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_http_methods
from django.views.decorators.cache import never_cache
from django.urls import reverse
from django.conf import settings
from django.core.exceptions import PermissionDenied, ValidationError
from django.utils.decorators import method_decorator
from django.views import View
from asgiref.sync import sync_to_async, async_to_sync
from .models import ProcessingJob, SpeakerTrack
from .forms import FileUploadForm, SpeakerLabelForm
from .services_refactored import (
    audio_service, start_processing_job, 
    get_job_status, update_speaker_label
)

logger = logging.getLogger(__name__)


class SecurityMixin:
    """Mixin for common security practices"""
    
    def dispatch(self, request, *args, **kwargs):
        # Add security headers
        response = super().dispatch(request, *args, **kwargs)
        if hasattr(response, '__setitem__'):
            response['X-Content-Type-Options'] = 'nosniff'
            response['X-Frame-Options'] = 'DENY'
        return response


@method_decorator(never_cache, name='dispatch')
class IndexView(SecurityMixin, View):
    """Main upload page with enhanced security"""
    
    def get(self, request):
        form = FileUploadForm()
        return render(request, 'processor/index.html', {
            'form': form,
            'max_file_size_mb': settings.MAX_UPLOAD_SIZE / (1024 * 1024),
            'allowed_formats': ', '.join(settings.ALLOWED_AUDIO_FORMATS),
            'csrf_token': request.META.get('CSRF_COOKIE'),
        })


class FileUploadView(SecurityMixin, View):
    """Handle file upload with comprehensive validation and security"""
    
    def post(self, request):
        try:
            # Rate limiting check (basic implementation)
            client_ip = self._get_client_ip(request)
            if self._is_rate_limited(client_ip):
                return JsonResponse({
                    'success': False,
                    'error': 'Too many requests. Please wait before uploading again.'
                }, status=429)
            
            form = FileUploadForm(request.POST, request.FILES)
            
            if form.is_valid():
                uploaded_file = form.cleaned_data['audio_file']
                
                # Additional security validation
                if not self._validate_file_security(uploaded_file):
                    return JsonResponse({
                        'success': False,
                        'error': 'File failed security validation.'
                    }, status=400)
                
                # Create processing job
                job = async_to_sync(audio_service.create_processing_job)(uploaded_file)
                
                # Start processing in background
                start_processing_job(str(job.job_id))
                
                return JsonResponse({
                    'success': True,
                    'job_id': str(job.job_id),
                    'message': 'File uploaded successfully. Processing started.',
                    'redirect_url': reverse('processor:status', kwargs={'job_id': job.job_id})
                })
            else:
                # Return sanitized form errors
                errors = []
                for field, field_errors in form.errors.items():
                    for error in field_errors:
                        # Sanitize error messages to prevent XSS
                        sanitized_error = str(error)[:200]  # Limit length
                        errors.append(f"{field}: {sanitized_error}")
                
                return JsonResponse({
                    'success': False,
                    'errors': errors
                }, status=400)
        
        except ValidationError as e:
            logger.warning(f"Validation error during upload: {str(e)}")
            return JsonResponse({
                'success': False,
                'error': 'Invalid file or request data.'
            }, status=400)
        except Exception as e:
            logger.error(f"Upload error: {str(e)}")
            return JsonResponse({
                'success': False,
                'error': 'An unexpected error occurred. Please try again.'
            }, status=500)
    
    def _get_client_ip(self, request):
        """Get client IP address safely"""
        x_forwarded_for = request.META.get('HTTP_X_FORWARDED_FOR')
        if x_forwarded_for:
            ip = x_forwarded_for.split(',')[0].strip()
        else:
            ip = request.META.get('REMOTE_ADDR', '')
        return ip
    
    def _is_rate_limited(self, client_ip):
        """Basic rate limiting - in production use Redis/proper rate limiter"""
        # Simple in-memory rate limiting (not suitable for production)
        import time
        from collections import defaultdict
        
        if not hasattr(self, '_rate_limit_cache'):
            self._rate_limit_cache = defaultdict(list)
        
        now = time.time()
        # Allow 3 uploads per minute per IP
        recent_uploads = [t for t in self._rate_limit_cache[client_ip] if now - t < 60]
        
        if len(recent_uploads) >= 3:
            return True
        
        recent_uploads.append(now)
        self._rate_limit_cache[client_ip] = recent_uploads
        return False
    
    def _validate_file_security(self, uploaded_file):
        """Additional security validation for uploaded files"""
        try:
            # Check MIME type
            detected_type = mimetypes.guess_type(uploaded_file.name)[0]
            allowed_mimes = [
                'audio/mpeg', 'audio/wav', 'audio/flac', 
                'audio/mp4', 'audio/aac', 'audio/ogg'
            ]
            
            if detected_type and detected_type not in allowed_mimes:
                logger.warning(f"Rejected file with MIME type: {detected_type}")
                return False
            
            # Check for null bytes (potential path traversal)
            if b'\x00' in uploaded_file.name.encode('utf-8', errors='ignore'):
                logger.warning("Rejected file with null bytes in name")
                return False
            
            # Basic file header validation
            uploaded_file.seek(0)
            header = uploaded_file.read(16)
            uploaded_file.seek(0)
            
            # Check for common audio file signatures
            audio_signatures = [
                b'ID3',  # MP3
                b'RIFF', # WAV
                b'fLaC', # FLAC
                b'OggS', # OGG
            ]
            
            if not any(header.startswith(sig) for sig in audio_signatures):
                logger.warning("File does not have valid audio signature")
                return False
            
            return True
            
        except Exception as e:
            logger.error(f"File security validation error: {str(e)}")
            return False


@method_decorator(never_cache, name='dispatch')
class StatusView(SecurityMixin, View):
    """Processing status page with job ownership validation"""
    
    def get(self, request, job_id):
        try:
            job = get_object_or_404(ProcessingJob, job_id=job_id)
            
            # Optional: Add job ownership validation if needed
            # if not self._can_access_job(request, job):
            #     raise PermissionDenied
            
            return render(request, 'processor/status.html', {
                'job': job,
                'job_id': job_id
            })
        except Exception as e:
            logger.error(f"Status page error: {str(e)}")
            return render(request, 'processor/error.html', {
                'error_message': 'Job not found or an error occurred.'
            })


@method_decorator(never_cache, name='dispatch')
class StatusAPIView(SecurityMixin, View):
    """API endpoint for job status polling with rate limiting"""
    
    def get(self, request, job_id):
        try:
            # Basic rate limiting for status checks
            if self._is_status_rate_limited(request):
                return JsonResponse({
                    'status': 'error',
                    'message': 'Too many status requests'
                }, status=429)
            
            status_info = get_job_status(job_id)
            
            # If job is completed, include redirect URL
            if status_info['status'] == 'completed':
                status_info['redirect_url'] = reverse(
                    'processor:results', kwargs={'job_id': job_id}
                )
            
            return JsonResponse(status_info)
        
        except Exception as e:
            logger.error(f"Status API error: {str(e)}")
            return JsonResponse({
                'status': 'error',
                'step': 'error',
                'progress': 0,
                'message': 'Error retrieving status'
            }, status=500)
    
    def _is_status_rate_limited(self, request):
        """Rate limit status checks - 1 request per second per session"""
        import time
        session_key = request.session.session_key or 'anonymous'
        
        if not hasattr(self, '_status_cache'):
            self._status_cache = {}
        
        now = time.time()
        last_check = self._status_cache.get(session_key, 0)
        
        if now - last_check < 1:  # 1 second rate limit
            return True
        
        self._status_cache[session_key] = now
        return False


class ResultsView(SecurityMixin, View):
    """Results page with job validation and security"""
    
    def get(self, request, job_id):
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


class UpdateSpeakerNameView(SecurityMixin, View):
    """Update speaker label with comprehensive validation"""
    
    def post(self, request, job_id):
        try:
            # Parse JSON data safely
            try:
                data = json.loads(request.body)
            except (json.JSONDecodeError, UnicodeDecodeError):
                return JsonResponse({
                    'success': False,
                    'error': 'Invalid JSON data'
                }, status=400)
            
            speaker_id = data.get('speaker_id', '').strip()
            new_label = data.get('speaker_label', '').strip()
            
            # Validate input lengths
            if len(speaker_id) > 50 or len(new_label) > 100:
                return JsonResponse({
                    'success': False,
                    'error': 'Input too long'
                }, status=400)
            
            # Validate speaker_id format
            if not speaker_id or not speaker_id.replace('_', '').replace('SPEAKER', '').isdigit():
                return JsonResponse({
                    'success': False,
                    'error': 'Invalid speaker ID format'
                }, status=400)
            
            # Validate form
            form = SpeakerLabelForm({
                'speaker_id': speaker_id,
                'speaker_label': new_label
            })
            
            if form.is_valid():
                success = async_to_sync(update_speaker_label)(job_id, speaker_id, new_label)
                
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
                        errors.append(str(error)[:200])  # Sanitize and limit
                
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


class AudioDownloadView(SecurityMixin, View):
    """Secure audio file download with access control"""
    
    def get(self, request, job_id, speaker_id):
        try:
            job = get_object_or_404(ProcessingJob, job_id=job_id)
            speaker_track = get_object_or_404(SpeakerTrack, job=job, speaker_id=speaker_id)
            
            # Validate file exists and is within allowed directory
            file_path = speaker_track.audio_file_path
            if not self._is_safe_path(file_path):
                logger.warning(f"Unsafe file path requested: {file_path}")
                raise Http404("File not found")
            
            if not os.path.exists(file_path):
                raise Http404("Audio file not found")
            
            # Generate secure filename for download
            display_name = self._sanitize_filename(speaker_track.display_name)
            original_name = self._sanitize_filename(job.original_filename)
            filename = f"{display_name}_{original_name}.wav"
            
            # Use FileResponse for efficient file serving
            response = FileResponse(
                open(file_path, 'rb'),
                content_type='audio/wav',
                as_attachment=True,
                filename=filename
            )
            
            # Add security headers
            response['X-Content-Type-Options'] = 'nosniff'
            response['Content-Security-Policy'] = "default-src 'none'"
            
            return response
        
        except Exception as e:
            logger.error(f"Download error: {str(e)}")
            raise Http404("File not found or error occurred")
    
    def _is_safe_path(self, file_path):
        """Validate file path is within allowed directories"""
        try:
            real_path = os.path.realpath(file_path)
            allowed_paths = [
                os.path.realpath(settings.AUDIO_OUTPUT_PATH),
                os.path.realpath(settings.MEDIA_ROOT)
            ]
            
            return any(real_path.startswith(allowed) for allowed in allowed_paths)
        except Exception:
            return False
    
    def _sanitize_filename(self, filename):
        """Sanitize filename for safe download"""
        import re
        if not filename:
            return "audio"
        
        # Remove any potentially dangerous characters
        sanitized = re.sub(r'[^\w\s\-_.]', '', filename)
        sanitized = sanitized.replace(' ', '_')[:50]  # Limit length
        
        return sanitized or "audio"


class AudioServeView(SecurityMixin, View):
    """Secure audio file serving for HTML5 audio player"""
    
    def get(self, request, job_id, speaker_id):
        try:
            job = get_object_or_404(ProcessingJob, job_id=job_id)
            speaker_track = get_object_or_404(SpeakerTrack, job=job, speaker_id=speaker_id)
            
            file_path = speaker_track.audio_file_path
            
            # Validate file path security
            if not self._is_safe_path(file_path):
                logger.warning(f"Unsafe file path requested: {file_path}")
                raise Http404("File not found")
            
            if not os.path.exists(file_path):
                raise Http404("Audio file not found")
            
            # Serve audio file with proper headers
            response = FileResponse(
                open(file_path, 'rb'),
                content_type='audio/wav'
            )
            
            # Add security and caching headers
            response['Accept-Ranges'] = 'bytes'
            response['X-Content-Type-Options'] = 'nosniff'
            response['Cache-Control'] = 'private, max-age=3600'
            
            return response
        
        except Exception as e:
            logger.error(f"Serve audio error: {str(e)}")
            raise Http404("Audio file not found")
    
    def _is_safe_path(self, file_path):
        """Validate file path is within allowed directories"""
        try:
            real_path = os.path.realpath(file_path)
            allowed_paths = [
                os.path.realpath(settings.AUDIO_OUTPUT_PATH),
                os.path.realpath(settings.MEDIA_ROOT)
            ]
            
            return any(real_path.startswith(allowed) for allowed in allowed_paths)
        except Exception:
            return False


# View function mappings for URL patterns
index = IndexView.as_view()
upload_file = csrf_exempt(FileUploadView.as_view())
status = StatusView.as_view()
status_api = StatusAPIView.as_view()
results = ResultsView.as_view()
update_speaker_name = csrf_exempt(UpdateSpeakerNameView.as_view())
download_audio = AudioDownloadView.as_view()
serve_audio = AudioServeView.as_view()
