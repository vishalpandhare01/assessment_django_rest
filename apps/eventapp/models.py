import uuid
import json
from django.db import models
from django.contrib.postgres.fields import ArrayField
from django.utils import timezone
from datetime import datetime, timedelta


class Event(models.Model):
    """
    Event model stores individual events from tenants.
    
    Ensures idempotency through:
    - Unique constraint on (event_id, tenant_id)
    - Database-level enforcement prevents duplicates
    """
    SOURCE_CHOICES = [
        ('web', 'Web'),
        ('mobile', 'Mobile'),
        ('device', 'Device'),
    ]
    
    EVENT_TYPE_CHOICES = [
        ('click', 'Click'),
        ('view', 'View'),
        ('error', 'Error'),
        ('custom', 'Custom'),
    ]
    
    # Primary fields
    event_id = models.CharField(max_length=255, db_index=True)
    tenant_id = models.CharField(max_length=255, db_index=True)
    source = models.CharField(
        max_length=50,
        choices=SOURCE_CHOICES,
        db_index=True,
    )
    event_type = models.CharField(
        max_length=50,
        choices=EVENT_TYPE_CHOICES,
        db_index=True,
    )
    
    # Timestamp (UTC, enforced by model)
    timestamp = models.DateTimeField(auto_now_add=True,db_index=True)
    created_at = models.DateTimeField(auto_now_add=True, db_index=True)
    
    # Payload as JSON
    payload = models.JSONField(default=dict)
    
    class Meta:
        # Ensure idempotency: no duplicate event_ids per tenant
        unique_together = ('event_id', 'tenant_id')
        
        # Composite index for common queries
        indexes = [
            models.Index(fields=['tenant_id', 'timestamp']),
            models.Index(fields=['tenant_id', 'source', 'event_type', 'timestamp']),
            models.Index(fields=['tenant_id', 'created_at']),
        ]
        
        verbose_name = 'Event'
        verbose_name_plural = 'Events'
    
    def __str__(self):
        return f"{self.event_id} - {self.tenant_id}"
    
    def clean(self):
        """Validate event before saving"""
        from django.core.exceptions import ValidationError
        
        # Ensure timestamp is in UTC
        if self.timestamp and self.timestamp.tzinfo is None:
            self.timestamp = timezone.make_aware(self.timestamp)
        
        # Payload size validation
        from django.conf import settings
        payload_size = len(json.dumps(self.payload).encode('utf-8'))
        max_size = settings.MAX_PAYLOAD_SIZE
        if payload_size > max_size:
            raise ValidationError(
                f'Payload too large: {payload_size} bytes (max {max_size})'
            )


class Aggregate(models.Model):
    """
    Aggregate model stores pre-computed event counts at minute/hour level.
    
    Used for efficient time-series queries without naive in-memory aggregation.
    Designed to be incremental and idempotent.
    """
    BUCKET_SIZE_CHOICES = [
        ('minute', 'Minute'),
        ('hour', 'Hour'),
    ]
    
    tenant_id = models.CharField(max_length=255, db_index=True)
    bucket_start = models.DateTimeField(db_index=True)
    bucket_size = models.CharField(
        max_length=10,
        choices=BUCKET_SIZE_CHOICES,
        default='minute',
    )
    
    # Optional dimensions
    source = models.CharField(
        max_length=50,
        null=True,
        blank=True,
        db_index=True,
    )
    event_type = models.CharField(
        max_length=50,
        null=True,
        blank=True,
        db_index=True,
    )
    
    # Aggregated data
    count = models.PositiveBigIntegerField(default=0)
    first_seen = models.DateTimeField(null=True, blank=True)
    last_seen = models.DateTimeField(null=True, blank=True)
    
    # Timestamps
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True, db_index=True)
    
    class Meta:
        # Ensure idempotency: unique aggregate per bucket
        unique_together = ('tenant_id', 'bucket_start', 'bucket_size', 'source', 'event_type')
        
        # Composite indexes for efficient querying
        indexes = [
            models.Index(fields=['tenant_id', 'bucket_start', 'bucket_size']),
            models.Index(fields=['tenant_id', 'bucket_size', 'source', 'event_type']),
            models.Index(fields=['bucket_start', 'bucket_size']),
        ]
        
        verbose_name = 'Aggregate'
        verbose_name_plural = 'Aggregates'
    
    def __str__(self):
        return f"{self.tenant_id} - {self.bucket_start} ({self.bucket_size})"
    
    @staticmethod
    def get_bucket_start(timestamp, bucket_size='minute'):
        """
        Calculate the bucket start for a given timestamp.
        
        Args:
            timestamp: datetime object
            bucket_size: 'minute' or 'hour'
        
        Returns:
            datetime object representing bucket start
        """
        if bucket_size == 'minute':
            return timestamp.replace(second=0, microsecond=0)
        elif bucket_size == 'hour':
            return timestamp.replace(minute=0, second=0, microsecond=0)
        else:
            raise ValueError(f"Invalid bucket_size: {bucket_size}")
    
    @classmethod
    def create_or_update_from_event(cls, event, bucket_size='minute'):
        """
        Update aggregate based on event. Idempotent operation.
        
        Args:
            event: Event instance
            bucket_size: 'minute' or 'hour'
        """
        bucket_start = cls.get_bucket_start(event.timestamp, bucket_size)
        
        aggregate, created = cls.objects.update_or_create(
            tenant_id=event.tenant_id,
            bucket_start=bucket_start,
            bucket_size=bucket_size,
            source=event.source,
            event_type=event.event_type,
            defaults={
                'count': models.F('count') + 1,
                'first_seen': bucket_start,
                'last_seen': event.timestamp,
            }
        )
        
        # Refresh to get actual values (F expressions not evaluated)
        aggregate.refresh_from_db()
        return aggregate


class AggregationJob(models.Model):
    """
    Track background aggregation jobs for idempotency and monitoring.
    """
    STATUS_CHOICES = [
        ('pending', 'Pending'),
        ('running', 'Running'),
        ('completed', 'Completed'),
        ('failed', 'Failed'),
    ]
    
    job_id = models.CharField(max_length=255, unique=True, db_index=True)
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='pending')
    tenant_id = models.CharField(max_length=255, null=True, blank=True, db_index=True)
    bucket_size = models.CharField(max_length=10, default='minute')
    
    start_time = models.DateTimeField(null=True, blank=True)
    end_time = models.DateTimeField(null=True, blank=True)
    
    events_processed = models.PositiveBigIntegerField(default=0)
    aggregates_created = models.PositiveBigIntegerField(default=0)
    aggregates_updated = models.PositiveBigIntegerField(default=0)
    
    error_message = models.TextField(null=True, blank=True)
    
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    
    class Meta:
        verbose_name = 'Aggregation Job'
        verbose_name_plural = 'Aggregation Jobs'
        indexes = [
            models.Index(fields=['status', 'created_at']),
            models.Index(fields=['tenant_id', 'status']),
        ]
    
    def __str__(self):
        return f"{self.job_id} - {self.status}"
