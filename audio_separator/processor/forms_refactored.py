import os
import re
from django import forms
from django.conf import settings
from django.core.exceptions import ValidationError
from django.core.validators import RegexValidator
from django.utils.html import escape


class FileUploadForm(forms.Form):
    """Enhanced form for audio file upload with comprehensive validation"""
    
    audio_file = forms.FileField(
        widget=forms.FileInput(attrs={
            'accept': ','.join(settings.ALLOWED_AUDIO_FORMATS),
            'class': 'form-control',
            'id': 'audioFileInput',
            'aria-describedby': 'fileHelpText'
        }),
        help_text=f"Supported formats: {', '.join(settings.ALLOWED_AUDIO_FORMATS)}. "
                  f"Maximum size: {settings.MAX_UPLOAD_SIZE // (1024 * 1024)}MB."
    )
    
    def clean_audio_file(self):
        """Comprehensive validation for uploaded audio file"""
        audio_file = self.cleaned_data.get('audio_file')
        
        if not audio_file:
            raise ValidationError("Please select an audio file.")
        
        # Validate file size
        if audio_file.size > settings.MAX_UPLOAD_SIZE:
            max_size_mb = settings.MAX_UPLOAD_SIZE / (1024 * 1024)
            raise ValidationError(
                f"File size must be less than {max_size_mb:.1f}MB. "
                f"Your file is {audio_file.size / (1024 * 1024):.1f}MB."
            )
        
        # Validate minimum file size (prevent empty files)
        if audio_file.size < 1024:  # 1KB minimum
            raise ValidationError("The uploaded file is too small to be a valid audio file.")
        
        # Validate filename
        self._validate_filename(audio_file.name)
        
        # Validate file extension
        file_extension = os.path.splitext(audio_file.name)[1].lower()
        if file_extension not in settings.ALLOWED_AUDIO_FORMATS:
            raise ValidationError(
                f"File format '{file_extension}' not supported. "
                f"Supported formats: {', '.join(settings.ALLOWED_AUDIO_FORMATS)}"
            )
        
        # Validate file content (basic header check)
        self._validate_file_content(audio_file)
        
        return audio_file
    
    def _validate_filename(self, filename):
        """Validate filename for security and compatibility"""
        if not filename:
            raise ValidationError("Invalid filename.")
        
        # Check for dangerous characters
        dangerous_chars = ['..', '/', '\\', ':', '*', '?', '"', '<', '>', '|', '\x00']
        if any(char in filename for char in dangerous_chars):
            raise ValidationError(
                "Filename contains invalid characters. Please rename your file."
            )
        
        # Check filename length
        if len(filename) > 255:
            raise ValidationError("Filename is too long. Maximum 255 characters allowed.")
        
        # Check for hidden files or system files
        if filename.startswith('.') or filename.startswith('~'):
            raise ValidationError("Hidden or system files are not allowed.")
        
        # Validate filename pattern (letters, numbers, spaces, hyphens, underscores, dots)
        if not re.match(r'^[a-zA-Z0-9\s\-_\.]+$', filename):
            raise ValidationError(
                "Filename can only contain letters, numbers, spaces, hyphens, underscores, and dots."
            )
    
    def _validate_file_content(self, audio_file):
        """Validate file content by checking headers"""
        try:
            # Read first 16 bytes to check file signature
            audio_file.seek(0)
            header = audio_file.read(16)
            audio_file.seek(0)  # Reset file pointer
            
            # Define audio file signatures
            audio_signatures = {
                b'ID3': 'MP3',
                b'RIFF': 'WAV/AVI',
                b'fLaC': 'FLAC',
                b'OggS': 'OGG',
                b'\x00\x00\x00\x20ftypM4A': 'M4A',
                b'\x00\x00\x00\x18ftypmp42': 'MP4',
                b'\xff\xfb': 'MP3 (no ID3)',
                b'\xff\xf3': 'MP3 (no ID3)',
                b'\xff\xf2': 'MP3 (no ID3)',
            }
            
            # Check if file starts with any known audio signature
            for signature, format_name in audio_signatures.items():
                if header.startswith(signature):
                    return  # Valid audio file
            
            # Special case for WAV files
            if header.startswith(b'RIFF') and b'WAVE' in header:
                return  # Valid WAV file
            
            # If no signature matches, reject the file
            raise ValidationError(
                "File does not appear to be a valid audio file. "
                "Please ensure you're uploading a genuine audio file."
            )
            
        except Exception as e:
            if isinstance(e, ValidationError):
                raise
            raise ValidationError("Unable to validate file content. Please try again.")


class SpeakerLabelForm(forms.Form):
    """Enhanced form for updating speaker labels with validation"""
    
    # Validator for speaker ID format
    speaker_id_validator = RegexValidator(
        regex=r'^SPEAKER_\d{2}$',
        message='Speaker ID must be in format SPEAKER_XX where XX are digits.'
    )
    
    speaker_id = forms.CharField(
        max_length=50,
        validators=[speaker_id_validator],
        widget=forms.HiddenInput()
    )
    
    speaker_label = forms.CharField(
        max_length=100, 
        required=False,
        widget=forms.TextInput(attrs={
            'class': 'form-control speaker-label-input',
            'placeholder': 'Enter speaker name...',
            'maxlength': '100',
            'pattern': r'^[a-zA-Z0-9\s\-_\.]*$',
            'title': 'Speaker name can only contain letters, numbers, spaces, hyphens, underscores, and dots.'
        }),
        help_text="Leave empty to use default name. Maximum 100 characters."
    )
    
    def clean_speaker_id(self):
        """Validate and sanitize speaker ID"""
        speaker_id = self.cleaned_data.get('speaker_id', '').strip()
        
        if not speaker_id:
            raise ValidationError("Speaker ID is required.")
        
        # Additional validation beyond the regex
        if not speaker_id.startswith('SPEAKER_'):
            raise ValidationError("Invalid speaker ID format.")
        
        # Extract and validate the number part
        try:
            number_part = speaker_id.replace('SPEAKER_', '')
            if not number_part.isdigit() or len(number_part) != 2:
                raise ValidationError("Speaker ID must end with exactly 2 digits.")
        except Exception:
            raise ValidationError("Invalid speaker ID format.")
        
        return speaker_id
    
    def clean_speaker_label(self):
        """Validate and sanitize speaker label"""
        label = self.cleaned_data.get('speaker_label', '').strip()
        
        # Allow empty labels (will use default)
        if not label:
            return ''
        
        # Validate length
        if len(label) > 100:
            raise ValidationError("Speaker name must be 100 characters or less.")
        
        # Validate minimum length if provided
        if len(label) < 2:
            raise ValidationError("Speaker name must be at least 2 characters long.")
        
        # Sanitize and validate characters
        if not re.match(r'^[a-zA-Z0-9\s\-_\.]+$', label):
            raise ValidationError(
                "Speaker name can only contain letters, numbers, spaces, "
                "hyphens, underscores, and dots."
            )
        
        # Check for inappropriate content (basic filter)
        inappropriate_words = ['admin', 'root', 'system', 'null', 'undefined']
        if label.lower() in inappropriate_words:
            raise ValidationError("This speaker name is not allowed.")
        
        # Escape HTML to prevent XSS
        label = escape(label)
        
        # Remove multiple consecutive spaces
        label = re.sub(r'\s+', ' ', label).strip()
        
        return label
    
    def clean(self):
        """Cross-field validation"""
        cleaned_data = super().clean()
        speaker_id = cleaned_data.get('speaker_id')
        speaker_label = cleaned_data.get('speaker_label')
        
        # If label is provided, ensure it's different from speaker_id
        if speaker_label and speaker_label == speaker_id:
            raise ValidationError(
                "Speaker name cannot be the same as the speaker ID."
            )
        
        return cleaned_data


class JobSearchForm(forms.Form):
    """Form for searching jobs (for potential admin interface)"""
    
    job_id = forms.UUIDField(
        required=False,
        widget=forms.TextInput(attrs={
            'class': 'form-control',
            'placeholder': 'Enter job ID...'
        })
    )
    
    status = forms.ChoiceField(
        choices=[('', 'All')] + [
            ('pending', 'Pending'),
            ('processing', 'Processing'),
            ('completed', 'Completed'),
            ('failed', 'Failed'),
        ],
        required=False,
        widget=forms.Select(attrs={'class': 'form-control'})
    )
    
    original_filename = forms.CharField(
        max_length=255,
        required=False,
        widget=forms.TextInput(attrs={
            'class': 'form-control',
            'placeholder': 'Search by filename...'
        })
    )
    
    def clean_original_filename(self):
        """Sanitize filename search"""
        filename = self.cleaned_data.get('original_filename', '').strip()
        
        if filename:
            # Remove potentially dangerous characters for search
            filename = re.sub(r'[^\w\s\-_\.]', '', filename)
            filename = filename[:255]  # Limit length
        
        return filename


class BulkDeleteForm(forms.Form):
    """Form for bulk deletion of old jobs (admin use)"""
    
    confirm_deletion = forms.BooleanField(
        required=True,
        widget=forms.CheckboxInput(attrs={
            'class': 'form-check-input'
        }),
        label="I confirm that I want to delete the selected jobs and all associated files."
    )
    
    job_ids = forms.CharField(
        widget=forms.HiddenInput(),
        help_text="Comma-separated list of job IDs to delete"
    )
    
    def clean_job_ids(self):
        """Validate job IDs for bulk deletion"""
        job_ids_str = self.cleaned_data.get('job_ids', '').strip()
        
        if not job_ids_str:
            raise ValidationError("No jobs selected for deletion.")
        
        try:
            job_ids = [uuid.strip() for uuid in job_ids_str.split(',')]
            
            # Validate each UUID
            from uuid import UUID
            validated_ids = []
            for job_id in job_ids:
                try:
                    UUID(job_id)  # This will raise ValueError if invalid
                    validated_ids.append(job_id)
                except ValueError:
                    raise ValidationError(f"Invalid job ID format: {job_id}")
            
            # Limit number of jobs that can be deleted at once
            if len(validated_ids) > 50:
                raise ValidationError("Cannot delete more than 50 jobs at once.")
            
            return validated_ids
            
        except Exception as e:
            if isinstance(e, ValidationError):
                raise
            raise ValidationError("Invalid job IDs format.")
