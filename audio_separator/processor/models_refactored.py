import uuid
import os
from django.db import models
from django.utils import timezone
from django.core.validators import MinValueValidator, MaxValueValidator
from django.core.exceptions import ValidationError
from django.conf import settings


def validate_audio_file_path(value):
    """Validate that file path is within allowed directories"""
    if not value:
        return
    
    try:
        real_path = os.path.realpath(value)
        allowed_paths = [
            os.path.realpath(settings.AUDIO_UPLOAD_PATH),
            os.path.realpath(settings.AUDIO_OUTPUT_PATH),
            os.path.realpath(settings.MEDIA_ROOT)
        ]
        
        if not any(real_path.startswith(allowed) for allowed in allowed_paths):
            raise ValidationError("File path is not within allowed directories.")
        
        # Additional security: check for path traversal attempts
        if '..' in value or value.startswith('/'):
            raise ValidationError("Invalid file path detected.")
            
    except Exception:
        raise ValidationError("Invalid file path.")


def validate_filename(value):
    """Validate filename for security"""
    if not value:
        return
    
    # Check for dangerous characters
    dangerous_chars = ['..', '/', '\\', ':', '*', '?', '"', '<', '>', '|', '\x00']
    if any(char in value for char in dangerous_chars):
        raise ValidationError("Filename contains invalid characters.")
    
    # Check length
    if len(value) > 255:
        raise ValidationError("Filename is too long.")


class ProcessingJob(models.Model):
    """Enhanced model to track audio processing jobs with better validation"""
    
    STATUS_CHOICES = [
        ('pending', 'Pending'),
        ('processing', 'Processing'),
        ('completed', 'Completed'),
        ('failed', 'Failed'),
    ]
    
    STEP_CHOICES = [
        ('uploaded', 'File Uploaded'),
        ('converting', 'Converting Audio Format'),
        ('transcribing', 'Transcribing with WhisperX'),
        ('separating', 'Separating Speakers'),
        ('finalizing', 'Finalizing Output'),
        ('completed', 'Processing Complete'),
    ]
    
    # Job identification with proper constraints
    job_id = models.UUIDField(
        default=uuid.uuid4, 
        unique=True, 
        editable=False,
        db_index=True,
        help_text="Unique identifier for this processing job"
    )
    
    # File information with validation
    original_filename = models.CharField(
        max_length=255,
        validators=[validate_filename],
        help_text="Original name of the uploaded file"
    )
    
    uploaded_file_path = models.CharField(
        max_length=500,
        validators=[validate_audio_file_path],
        help_text="Path to the uploaded audio file"
    )
    
    file_size = models.BigIntegerField(
        validators=[
            MinValueValidator(1024),  # Minimum 1KB
            MaxValueValidator(settings.MAX_UPLOAD_SIZE)
        ],
        help_text="Size of the uploaded file in bytes"
    )
    
    # Processing status with constraints
    status = models.CharField(
        max_length=20, 
        choices=STATUS_CHOICES, 
        default='pending',
        db_index=True
    )
    
    current_step = models.CharField(
        max_length=20, 
        choices=STEP_CHOICES, 
        default='uploaded'
    )
    
    progress_percentage = models.IntegerField(
        default=0,
        validators=[MinValueValidator(0), MaxValueValidator(100)],
        help_text="Processing progress from 0 to 100"
    )
    
    # Results with validation
    speaker_count = models.IntegerField(
        null=True, 
        blank=True,
        validators=[MinValueValidator(0), MaxValueValidator(50)],
        help_text="Number of speakers identified"
    )
    
    output_directory = models.CharField(
        max_length=500,
        null=True, 
        blank=True,
        validators=[validate_audio_file_path],
        help_text="Directory containing output files"
    )
    
    # Error handling with length limit
    error_message = models.TextField(
        null=True, 
        blank=True,
        max_length=1000,
        help_text="Error message if processing failed"
    )
    
    # Timestamps with proper indexing
    created_at = models.DateTimeField(
        default=timezone.now,
        db_index=True,
        help_text="When the job was created"
    )
    
    started_at = models.DateTimeField(
        null=True, 
        blank=True,
        help_text="When processing started"
    )
    
    completed_at = models.DateTimeField(
        null=True, 
        blank=True,
        help_text="When processing completed"
    )
    
    # Additional security and tracking fields
    client_ip = models.GenericIPAddressField(
        null=True,
        blank=True,
        help_text="IP address of the client who submitted the job"
    )
    
    user_agent = models.CharField(
        max_length=500,
        null=True,
        blank=True,
        help_text="User agent string from the client"
    )
    
    class Meta:
        ordering = ['-created_at']
        indexes = [
            models.Index(fields=['status', 'created_at']),
            models.Index(fields=['job_id']),
            models.Index(fields=['-created_at']),
        ]
        
        # Add constraints for data integrity
        constraints = [
            models.CheckConstraint(
                check=models.Q(progress_percentage__gte=0) & models.Q(progress_percentage__lte=100),
                name='valid_progress_percentage'
            ),
            models.CheckConstraint(
                check=models.Q(file_size__gte=1024),
                name='minimum_file_size'
            ),
        ]
    
    def __str__(self):
        return f"Job {self.job_id} - {self.original_filename} ({self.status})"
    
    def clean(self):
        """Model-level validation"""
        super().clean()
        
        # Validate status transitions
        if self.pk:  # Only for existing objects
            try:
                old_instance = ProcessingJob.objects.get(pk=self.pk)
                if not self._is_valid_status_transition(old_instance.status, self.status):
                    raise ValidationError(
                        f"Invalid status transition from {old_instance.status} to {self.status}"
                    )
            except ProcessingJob.DoesNotExist:
                pass
        
        # Validate file path security
        if self.uploaded_file_path:
            validate_audio_file_path(self.uploaded_file_path)
        
        if self.output_directory:
            validate_audio_file_path(self.output_directory)
    
    def _is_valid_status_transition(self, old_status, new_status):
        """Validate status transitions"""
        valid_transitions = {
            'pending': ['processing', 'failed'],
            'processing': ['completed', 'failed'],
            'completed': [],  # Terminal state
            'failed': ['processing'],  # Allow retry
        }
        
        return new_status in valid_transitions.get(old_status, [])
    
    @property
    def duration(self):
        """Calculate processing duration safely"""
        if self.started_at and self.completed_at:
            return self.completed_at - self.started_at
        elif self.started_at:
            return timezone.now() - self.started_at
        return None
    
    @property
    def is_processing(self):
        """Check if job is currently processing"""
        return self.status == 'processing'
    
    @property
    def is_completed(self):
        """Check if job completed successfully"""
        return self.status == 'completed'
    
    @property
    def is_failed(self):
        """Check if job failed"""
        return self.status == 'failed'
    
    def get_absolute_url(self):
        """Get URL for this job's results"""
        from django.urls import reverse
        if self.is_completed:
            return reverse('processor:results', kwargs={'job_id': self.job_id})
        else:
            return reverse('processor:status', kwargs={'job_id': self.job_id})
    
    def mark_as_failed(self, error_message):
        """Mark job as failed with error message"""
        self.status = 'failed'
        self.error_message = error_message[:1000]  # Truncate long messages
        self.completed_at = timezone.now()
        self.save(update_fields=['status', 'error_message', 'completed_at'])
    
    def mark_as_completed(self):
        """Mark job as completed"""
        self.status = 'completed'
        self.progress_percentage = 100
        self.completed_at = timezone.now()
        self.save(update_fields=['status', 'progress_percentage', 'completed_at'])


def validate_speaker_id(value):
    """Validate speaker ID format"""
    import re
    if not re.match(r'^SPEAKER_\d{2}$', value):
        raise ValidationError("Speaker ID must be in format SPEAKER_XX where XX are digits.")


def validate_speaker_label(value):
    """Validate speaker label content"""
    if not value:
        return
    
    import re
    if not re.match(r'^[a-zA-Z0-9\s\-_\.]+$', value):
        raise ValidationError(
            "Speaker label can only contain letters, numbers, spaces, "
            "hyphens, underscores, and dots."
        )


class SpeakerTrack(models.Model):
    """Enhanced model to store individual speaker tracks with validation"""
    
    job = models.ForeignKey(
        ProcessingJob, 
        on_delete=models.CASCADE, 
        related_name='speaker_tracks',
        help_text="The processing job this track belongs to"
    )
    
    speaker_id = models.CharField(
        max_length=50,
        validators=[validate_speaker_id],
        help_text="Identifier for the speaker (e.g., SPEAKER_00)"
    )
    
    speaker_label = models.CharField(
        max_length=100, 
        blank=True,
        validators=[validate_speaker_label],
        help_text="User-friendly label for the speaker"
    )
    
    audio_file_path = models.CharField(
        max_length=500,
        validators=[validate_audio_file_path],
        help_text="Path to the separated audio file"
    )
    
    duration_seconds = models.FloatField(
        null=True, 
        blank=True,
        validators=[MinValueValidator(0.0)],
        help_text="Duration of the audio track in seconds"
    )
    
    word_count = models.IntegerField(
        null=True, 
        blank=True,
        validators=[MinValueValidator(0)],
        help_text="Number of words spoken by this speaker"
    )
    
    # Additional metadata
    created_at = models.DateTimeField(
        default=timezone.now,
        help_text="When this track was created"
    )
    
    file_size = models.BigIntegerField(
        null=True,
        blank=True,
        validators=[MinValueValidator(0)],
        help_text="Size of the audio file in bytes"
    )
    
    class Meta:
        unique_together = ['job', 'speaker_id']
        ordering = ['speaker_id']
        indexes = [
            models.Index(fields=['job', 'speaker_id']),
            models.Index(fields=['job', '-created_at']),
        ]
        
        constraints = [
            models.CheckConstraint(
                check=models.Q(duration_seconds__isnull=True) | models.Q(duration_seconds__gte=0),
                name='valid_duration'
            ),
            models.CheckConstraint(
                check=models.Q(word_count__isnull=True) | models.Q(word_count__gte=0),
                name='valid_word_count'
            ),
        ]
    
    def __str__(self):
        label = self.speaker_label or self.speaker_id
        return f"{self.job.job_id} - {label}"
    
    def clean(self):
        """Model-level validation"""
        super().clean()
        
        # Validate audio file path
        if self.audio_file_path:
            validate_audio_file_path(self.audio_file_path)
            
            # Check if file exists (optional, might be expensive)
            if hasattr(settings, 'VALIDATE_FILE_EXISTS') and settings.VALIDATE_FILE_EXISTS:
                if not os.path.exists(self.audio_file_path):
                    raise ValidationError("Audio file does not exist at specified path.")
    
    @property
    def display_name(self):
        """Get display name for speaker with fallback"""
        return self.speaker_label.strip() if self.speaker_label else self.speaker_id
    
    @property
    def formatted_duration(self):
        """Get formatted duration string"""
        if self.duration_seconds is None:
            return "Unknown"
        
        minutes = int(self.duration_seconds // 60)
        seconds = int(self.duration_seconds % 60)
        return f"{minutes}:{seconds:02d}"
    
    @property
    def file_exists(self):
        """Check if the audio file exists"""
        return os.path.exists(self.audio_file_path) if self.audio_file_path else False
    
    def get_download_url(self):
        """Get download URL for this track"""
        from django.urls import reverse
        return reverse('processor:download_audio', kwargs={
            'job_id': self.job.job_id,
            'speaker_id': self.speaker_id
        })
    
    def get_serve_url(self):
        """Get serving URL for HTML5 audio player"""
        from django.urls import reverse
        return reverse('processor:serve_audio', kwargs={
            'job_id': self.job.job_id,
            'speaker_id': self.speaker_id
        })
    
    def update_file_size(self):
        """Update file size from actual file"""
        if self.audio_file_path and os.path.exists(self.audio_file_path):
            try:
                self.file_size = os.path.getsize(self.audio_file_path)
                self.save(update_fields=['file_size'])
            except OSError:
                pass  # File might be temporarily unavailable


class ProcessingStats(models.Model):
    """Model to track processing statistics and metrics"""
    
    date = models.DateField(
        default=timezone.now,
        unique=True,
        help_text="Date for these statistics"
    )
    
    jobs_created = models.IntegerField(
        default=0,
        validators=[MinValueValidator(0)],
        help_text="Number of jobs created on this date"
    )
    
    jobs_completed = models.IntegerField(
        default=0,
        validators=[MinValueValidator(0)],
        help_text="Number of jobs completed on this date"
    )
    
    jobs_failed = models.IntegerField(
        default=0,
        validators=[MinValueValidator(0)],
        help_text="Number of jobs that failed on this date"
    )
    
    total_processing_time = models.DurationField(
        null=True,
        blank=True,
        help_text="Total processing time for completed jobs"
    )
    
    total_file_size = models.BigIntegerField(
        default=0,
        validators=[MinValueValidator(0)],
        help_text="Total size of files processed in bytes"
    )
    
    average_speakers_per_job = models.FloatField(
        null=True,
        blank=True,
        validators=[MinValueValidator(0.0)],
        help_text="Average number of speakers identified per job"
    )
    
    class Meta:
        ordering = ['-date']
        indexes = [
            models.Index(fields=['-date']),
        ]
    
    def __str__(self):
        return f"Stats for {self.date}"
    
    @classmethod
    def update_daily_stats(cls, date=None):
        """Update statistics for a given date"""
        if date is None:
            date = timezone.now().date()
        
        # Get or create stats object
        stats, created = cls.objects.get_or_create(date=date)
        
        # Calculate statistics for the date
        jobs_on_date = ProcessingJob.objects.filter(created_at__date=date)
        
        stats.jobs_created = jobs_on_date.count()
        stats.jobs_completed = jobs_on_date.filter(status='completed').count()
        stats.jobs_failed = jobs_on_date.filter(status='failed').count()
        
        # Calculate total processing time
        completed_jobs = jobs_on_date.filter(
            status='completed',
            started_at__isnull=False,
            completed_at__isnull=False
        )
        
        if completed_jobs.exists():
            from django.db.models import Sum, Avg
            total_time = sum(
                (job.completed_at - job.started_at).total_seconds()
                for job in completed_jobs
            )
            stats.total_processing_time = timezone.timedelta(seconds=total_time)
            
            # Calculate average speakers per job
            avg_speakers = completed_jobs.aggregate(
                avg=Avg('speaker_count')
            )['avg']
            stats.average_speakers_per_job = avg_speakers
        
        # Calculate total file size
        stats.total_file_size = jobs_on_date.aggregate(
            total=Sum('file_size')
        )['total'] or 0
        
        stats.save()
        return stats
