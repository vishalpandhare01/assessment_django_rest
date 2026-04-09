from rest_framework import serializers
from django.utils import timezone
from django.core.exceptions import ValidationError as DjangoValidationError
import json
from datetime import datetime
import pytz

from .models import Event, Aggregate, AggregationJob


class EventSerializer(serializers.ModelSerializer):
    """
    Serializer for Event model with comprehensive validation.
    
    Includes:
    - Timestamp UTC enforcement
    - Payload size validation
    - Tenant ID validation
    - Event ID uniqueness validation (idempotency)
    """
    
    class Meta:
        model = Event
        fields = ['event_id', 'tenant_id', 'source', 'event_type', 'timestamp', 'payload', 'created_at']
        read_only_fields = ['created_at']
    
    def validate_event_id(self, value):
        """Ensure event_id is not empty"""
        if not value or not value.strip():
            raise serializers.ValidationError("event_id cannot be empty")
        return value
    
    def validate_tenant_id(self, value):
        """Ensure tenant_id is not empty"""
        if not value or not value.strip():
            raise serializers.ValidationError("tenant_id cannot be empty")
        return value
    
    def validate_timestamp(self, value):
        """
        Ensure timestamp is UTC and valid.
        
        - Rejects future timestamps (optionally, configurable)
        - Ensures UTC timezone
        """
        if value is None:
            raise serializers.ValidationError("timestamp is required")
        
        # Make aware if naive
        if value.tzinfo is None:
            value = timezone.make_aware(value, timezone.utc)
        
        # Ensure UTC timezone
        if value.tzinfo != pytz.UTC and value.tzinfo != timezone.utc:
            value = value.astimezone(timezone.utc)
        
        # Optional: reject future timestamps
        now = timezone.now()
        if value > now:
            raise serializers.ValidationError(
                f"timestamp cannot be in the future (got {value}, now is {now})"
            )
        
        return value
    
    def validate_payload(self, value):
        """
        Validate payload:
        - Must be JSON serializable
        - Size must not exceed limit
        """
        from django.conf import settings
        
        if value is None:
            return {}
        
        try:
            payload_json = json.dumps(value)
            payload_size = len(payload_json.encode('utf-8'))
            max_size = settings.MAX_PAYLOAD_SIZE
            
            if payload_size > max_size:
                raise serializers.ValidationError(
                    f'Payload too large: {payload_size} bytes (max {max_size} bytes)'
                )
        except (TypeError, ValueError) as e:
            raise serializers.ValidationError(f"Payload must be JSON serializable: {str(e)}")
        
        return value
    
    def validate(self, data):
        """
        Cross-field validation:
        - Check for existing event with same (event_id, tenant_id)
        """
        event_id = data.get('event_id')
        tenant_id = data.get('tenant_id')
        
        # Check if this is an update (instance exists)
        if self.instance is None:
            # New event - check for existing
            existing = Event.objects.filter(
                event_id=event_id,
                tenant_id=tenant_id
            ).first()
            
            if existing:
                # Event already exists - this is idempotent behavior
                # Raise a specific error that can be handled
                raise serializers.ValidationError({
                    'non_field_errors': 'Event with this event_id and tenant_id already exists.'
                })
        
        return data
    
    def create(self, validated_data):
        """Create event with idempotency handling"""
        try:
            return Event.objects.create(**validated_data)
        except Exception as e:
            if 'unique constraint' in str(e).lower():
                raise serializers.ValidationError(
                    'Event with this event_id and tenant_id already exists.'
                )
            raise


class BulkEventSerializer(serializers.Serializer):
    """
    Serializer for bulk event ingestion.
    
    Accepts list of events with validation and throughput optimization.
    """
    events = serializers.ListField(
        child=serializers.JSONField(),
        required=True
    )
    
    def validate_events(self, value):
        """Validate event list"""
        from django.conf import settings
        
        if not value:
            raise serializers.ValidationError("events list cannot be empty")
        
        max_events = settings.MAX_BULK_EVENTS
        if len(value) > max_events:
            raise serializers.ValidationError(
                f"Too many events: {len(value)} (max {max_events})"
            )
        
        return value
    
    def validate(self, data):
        """Validate each event in the bulk"""
        events = data.get('events', [])
        validated_events = []
        errors = []
        
        for idx, event_data in enumerate(events):
            try:
                # Ensure it's a dict
                if not isinstance(event_data, dict):
                    errors.append({
                        'index': idx,
                        'error': 'Event must be an object'
                    })
                    continue
                
                # Validate using EventSerializer
                serializer = EventSerializer(data=event_data)
                if serializer.is_valid():
                    validated_events.append(serializer.validated_data)
                else:
                    errors.append({
                        'index': idx,
                        'errors': serializer.errors
                    })
            except Exception as e:
                errors.append({
                    'index': idx,
                    'error': str(e)
                })
        
        if errors and len(errors) == len(events):
            raise serializers.ValidationError({
                'events': 'All events failed validation',
                'details': errors
            })
        
        data['validated_events'] = validated_events
        data['validation_errors'] = errors
        
        return data


class AggregateSerializer(serializers.ModelSerializer):
    """Serializer for Aggregate model"""
    
    class Meta:
        model = Aggregate
        fields = [
            'tenant_id', 'bucket_start', 'bucket_size', 
            'source', 'event_type', 'count', 
            'first_seen', 'last_seen', 'created_at', 'updated_at'
        ]
        read_only_fields = ['created_at', 'updated_at', 'count', 'first_seen', 'last_seen']


class AggregationJobSerializer(serializers.ModelSerializer):
    """Serializer for AggregationJob tracking"""
    
    class Meta:
        model = AggregationJob
        fields = [
            'job_id', 'status', 'tenant_id', 'bucket_size',
            'start_time', 'end_time', 'events_processed',
            'aggregates_created', 'aggregates_updated', 'error_message',
            'created_at', 'updated_at'
        ]
        read_only_fields = [
            'status', 'start_time', 'end_time', 'events_processed',
            'aggregates_created', 'aggregates_updated', 'error_message',
            'created_at', 'updated_at'
        ]
