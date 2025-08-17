from django import forms
from django.conf import settings
from django.core.exceptions import ValidationError
import os


class FileUploadForm(forms.Form):
    """Form for audio file upload with validation"""
    
    audio_file = forms.FileField(
        widget=forms.FileInput(attrs={
            'accept': ','.join(settings.ALLOWED_AUDIO_FORMATS),
            'class': 'form-control',
            'id': 'audioFileInput'
        })
    )
    
    def clean_audio_file(self):
        """Validate uploaded audio file with comprehensive security checks"""
        audio_file = self.cleaned_data.get('audio_file')
        
        if not audio_file:
            raise ValidationError("Please select an audio file.")
        
        # Check file size
        if audio_file.size > settings.MAX_UPLOAD_SIZE:
            max_size_mb = settings.MAX_UPLOAD_SIZE / (1024 * 1024)
            raise ValidationError(
                f"File size must be less than {max_size_mb:.1f}MB. "
                f"Your file is {audio_file.size / (1024 * 1024):.1f}MB."
            )
        
        # Check minimum file size (prevent empty or malicious tiny files)
        if audio_file.size < 1024:  # 1KB minimum
            raise ValidationError("File is too small to be a valid audio file.")
        
        # Sanitize filename to prevent path traversal
        import re
        safe_filename = re.sub(r'[^\w\-_\.]', '', audio_file.name)
        if not safe_filename or safe_filename != audio_file.name:
            raise ValidationError(
                "Filename contains invalid characters. Use only letters, numbers, hyphens, underscores, and dots."
            )
        
        # Check file extension
        file_extension = os.path.splitext(audio_file.name)[1].lower()
        if file_extension not in settings.ALLOWED_AUDIO_FORMATS:
            raise ValidationError(
                f"File format not supported. Supported formats: "
                f"{', '.join(settings.ALLOWED_AUDIO_FORMATS)}"
            )
        
        # Validate file content by checking magic numbers/signatures
        audio_file.seek(0)  # Reset file pointer
        header = audio_file.read(16)  # Read first 16 bytes
        audio_file.seek(0)  # Reset again
        
        # Define magic numbers for supported audio formats
        magic_numbers = {
            '.mp3': [b'ID3', b'\xff\xfb', b'\xff\xf3', b'\xff\xf2'],
            '.wav': [b'RIFF'],
            '.flac': [b'fLaC'],
            '.m4a': [b'\x00\x00\x00', b'ftyp'],
            '.aac': [b'\xff\xf1', b'\xff\xf9'],
            '.ogg': [b'OggS']
        }
        
        expected_magic = magic_numbers.get(file_extension, [])
        if expected_magic:
            valid_header = any(header.startswith(magic) for magic in expected_magic)
            if not valid_header:
                raise ValidationError(
                    f"File content does not match the {file_extension} format. "
                    "The file may be corrupted or not a genuine audio file."
                )
        
        # Additional content validation for specific formats
        if file_extension == '.wav' and len(header) >= 12:
            # WAV files should have 'WAVE' at offset 8
            if header[8:12] != b'WAVE':
                raise ValidationError("Invalid WAV file format.")
        
        return audio_file


class SpeakerLabelForm(forms.Form):
    """Form for updating speaker labels"""
    
    speaker_id = forms.CharField(max_length=50)
    speaker_label = forms.CharField(
        max_length=100, 
        required=False,
        widget=forms.TextInput(attrs={
            'class': 'form-control speaker-label-input',
            'placeholder': 'Enter speaker name...'
        })
    )
    
    def clean_speaker_label(self):
        """Clean and validate speaker label"""
        label = self.cleaned_data.get('speaker_label', '').strip()
        
        # Remove any potentially harmful characters
        if label:
            # Allow only alphanumeric, spaces, hyphens, and underscores
            import re
            if not re.match(r'^[a-zA-Z0-9\s\-_]+$', label):
                raise ValidationError(
                    "Speaker label can only contain letters, numbers, spaces, hyphens, and underscores."
                )
        
        return label
