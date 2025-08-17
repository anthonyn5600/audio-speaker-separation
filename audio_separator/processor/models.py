from django.db import models
import uuid
from django.utils import timezone


class ProcessingJob(models.Model):
    """Model to track audio processing jobs"""
    
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
    
    # Job identification
    job_id = models.UUIDField(default=uuid.uuid4, unique=True, editable=False)
    
    # File information
    original_filename = models.CharField(max_length=255)
    uploaded_file_path = models.FilePathField()
    file_size = models.BigIntegerField()
    
    # Processing status
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='pending')
    current_step = models.CharField(max_length=20, choices=STEP_CHOICES, default='uploaded')
    progress_percentage = models.IntegerField(default=0)
    
    # Results
    speaker_count = models.IntegerField(null=True, blank=True)
    output_directory = models.FilePathField(null=True, blank=True)
    
    # Error handling
    error_message = models.TextField(null=True, blank=True)
    
    # Timestamps
    created_at = models.DateTimeField(default=timezone.now)
    started_at = models.DateTimeField(null=True, blank=True)
    completed_at = models.DateTimeField(null=True, blank=True)
    
    class Meta:
        ordering = ['-created_at']
    
    def __str__(self):
        return f"Job {self.job_id} - {self.original_filename} ({self.status})"
    
    @property
    def duration(self):
        """Calculate processing duration"""
        if self.started_at and self.completed_at:
            return self.completed_at - self.started_at
        elif self.started_at:
            return timezone.now() - self.started_at
        return None


class SpeakerTrack(models.Model):
    """Model to store individual speaker tracks"""
    
    job = models.ForeignKey(ProcessingJob, on_delete=models.CASCADE, related_name='speaker_tracks')
    speaker_id = models.CharField(max_length=50)  # e.g., "SPEAKER_00"
    speaker_label = models.CharField(max_length=100, blank=True)  # User-editable label
    audio_file_path = models.FilePathField()
    duration_seconds = models.FloatField(null=True, blank=True)
    word_count = models.IntegerField(null=True, blank=True)
    
    class Meta:
        unique_together = ['job', 'speaker_id']
        ordering = ['speaker_id']
    
    def __str__(self):
        label = self.speaker_label or self.speaker_id
        return f"{self.job.job_id} - {label}"
    
    @property
    def display_name(self):
        """Get display name for speaker"""
        return self.speaker_label if self.speaker_label else self.speaker_id
