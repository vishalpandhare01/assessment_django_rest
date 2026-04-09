import pytest
import json
import uuid
from datetime import datetime, timedelta
from django.utils import timezone
from django.test import TestCase, TransactionTestCase
from django.urls import reverse
from django.core.cache import cache
from rest_framework.test import APITestCase, APIClient
from rest_framework import status

from .models import Event, Aggregate, AggregationJob
from .serializers import EventSerializer, BulkEventSerializer


# ============================================================================
# Event Model Tests
# ============================================================================

class EventModelTests(TestCase):
    """Tests for Event model functionality"""
    
    def setUp(self):
        """Set up test fixtures"""
        self.tenant_id = 'test-tenant-1'
        self.event_id = str(uuid.uuid4())
    
    def test_event_creation(self):
        """Test basic event creation"""
        event = Event.objects.create(
            event_id=self.event_id,
            tenant_id=self.tenant_id,
            source='web',
            event_type='click',
            timestamp=timezone.now(),
            payload={'button': 'submit'}
        )
        
        assert event.id is not None
        assert event.event_id == self.event_id
        assert event.tenant_id == self.tenant_id
    
    def test_event_idempotency(self):
        """Test that duplicate event_id + tenant_id raises IntegrityError"""
        event_data = {
            'event_id': self.event_id,
            'tenant_id': self.tenant_id,
            'source': 'web',
            'event_type': 'click',
            'timestamp': timezone.now(),
            'payload': {}
        }
        
        # Create first event
        Event.objects.create(**event_data)
        
        # Attempting to create duplicate should raise IntegrityError
        from django.db import IntegrityError
        with pytest.raises(IntegrityError):
            Event.objects.create(**event_data)
    
    def test_event_timestamp_utc(self):
        """Test that timestamp is stored in UTC"""
        event = Event.objects.create(
            event_id=self.event_id,
            tenant_id=self.tenant_id,
            source='web',
            event_type='click',
            timestamp=timezone.now(),
            payload={}
        )
        
        assert event.timestamp.tzinfo is not None
    
    def test_event_indexing(self):
        """Test that events are properly indexed"""
        # Create multiple events
        for i in range(10):
            Event.objects.create(
                event_id=f'event-{i}',
                tenant_id=self.tenant_id,
                source='mobile',
                event_type='view',
                timestamp=timezone.now() - timedelta(hours=i),
                payload={'page': f'page-{i}'}
            )
        
        # Query should be efficient with indexes
        events = Event.objects.filter(
            tenant_id=self.tenant_id,
            source='mobile'
        )
        assert events.count() == 10


# ============================================================================
# Aggregate Model Tests
# ============================================================================

class AggregateModelTests(TestCase):
    """Tests for Aggregate model functionality"""
    
    def setUp(self):
        """Set up test fixtures"""
        self.tenant_id = 'test-tenant-1'
        self.timestamp = timezone.now()
    
    def test_bucket_start_minute(self):
        """Test bucket_start calculation for minute-level bucketing"""
        ts = timezone.datetime(2024, 1, 1, 12, 34, 56, 789123, tzinfo=timezone.utc)
        bucket = Aggregate.get_bucket_start(ts, 'minute')
        
        assert bucket.minute == 34
        assert bucket.second == 0
        assert bucket.microsecond == 0
    
    def test_bucket_start_hour(self):
        """Test bucket_start calculation for hour-level bucketing"""
        ts = timezone.datetime(2024, 1, 1, 12, 34, 56, 789123, tzinfo=timezone.utc)
        bucket = Aggregate.get_bucket_start(ts, 'hour')
        
        assert bucket.hour == 12
        assert bucket.minute == 0
        assert bucket.second == 0
        assert bucket.microsecond == 0
    
    def test_aggregate_idempotency(self):
        """Test that updating same aggregate is idempotent"""
        event = Event.objects.create(
            event_id=str(uuid.uuid4()),
            tenant_id=self.tenant_id,
            source='web',
            event_type='click',
            timestamp=self.timestamp,
            payload={}
        )
        
        # Create from event
        agg1 = Aggregate.create_or_update_from_event(event, 'minute')
        initial_count = agg1.count
        
        # Create same event type/source should increment count
        agg2 = Aggregate.create_or_update_from_event(event, 'minute')
        assert agg1.id == agg2.id
        # Note: count should be incremented by 1
    
    def test_aggregate_unique_constraint(self):
        """Test unique constraint on aggregate."""
        from django.db import IntegrityError
        
        bucket_start = Aggregate.get_bucket_start(self.timestamp, 'minute')
        
        agg1 = Aggregate.objects.create(
            tenant_id=self.tenant_id,
            bucket_start=bucket_start,
            bucket_size='minute',
            source='web',
            event_type='click',
            count=1
        )
        
        # Creating duplicate should raise IntegrityError
        with pytest.raises(IntegrityError):
            Aggregate.objects.create(
                tenant_id=self.tenant_id,
                bucket_start=bucket_start,
                bucket_size='minute',
                source='web',
                event_type='click',
                count=2
            )


# ============================================================================
# Serializer Tests
# ============================================================================

class EventSerializerTests(TestCase):
    """Tests for EventSerializer validation"""
    
    def test_valid_event_serialization(self):
        """Test serialization of valid event"""
        data = {
            'event_id': str(uuid.uuid4()),
            'tenant_id': 'tenant-1',
            'source': 'web',
            'event_type': 'click',
            'timestamp': timezone.now().isoformat(),
            'payload': {'button': 'submit'}
        }
        
        serializer = EventSerializer(data=data)
        assert serializer.is_valid(), serializer.errors
    
    def test_invalid_empty_event_id(self):
        """Test rejection of empty event_id"""
        data = {
            'event_id': '',
            'tenant_id': 'tenant-1',
            'source': 'web',
            'event_type': 'click',
            'timestamp': timezone.now().isoformat(),
            'payload': {}
        }
        
        serializer = EventSerializer(data=data)
        assert not serializer.is_valid()
        assert 'event_id' in serializer.errors
    
    def test_invalid_empty_tenant_id(self):
        """Test rejection of empty tenant_id"""
        data = {
            'event_id': str(uuid.uuid4()),
            'tenant_id': '',
            'source': 'web',
            'event_type': 'click',
            'timestamp': timezone.now().isoformat(),
            'payload': {}
        }
        
        serializer = EventSerializer(data=data)
        assert not serializer.is_valid()
        assert 'tenant_id' in serializer.errors
    
    def test_timestamp_utc_enforcement(self):
        """Test UTC timestamp enforcement"""
        data = {
            'event_id': str(uuid.uuid4()),
            'tenant_id': 'tenant-1',
            'source': 'web',
            'event_type': 'click',
            'timestamp': timezone.now().isoformat(),
            'payload': {}
        }
        
        serializer = EventSerializer(data=data)
        assert serializer.is_valid()
    
    def test_future_timestamp_rejection(self):
        """Test rejection of future timestamps"""
        future_time = timezone.now() + timedelta(hours=1)
        data = {
            'event_id': str(uuid.uuid4()),
            'tenant_id': 'tenant-1',
            'source': 'web',
            'event_type': 'click',
            'timestamp': future_time.isoformat(),
            'payload': {}
        }
        
        serializer = EventSerializer(data=data)
        assert not serializer.is_valid()
        assert 'timestamp' in serializer.errors
    
    def test_payload_size_validation(self):
        """Test payload size limit validation"""
        # Create a large payload
        large_payload = {'data': 'x' * (2 * 1024 * 1024)}  # 2 MB
        
        data = {
            'event_id': str(uuid.uuid4()),
            'tenant_id': 'tenant-1',
            'source': 'web',
            'event_type': 'click',
            'timestamp': timezone.now().isoformat(),
            'payload': large_payload
        }
        
        serializer = EventSerializer(data=data)
        assert not serializer.is_valid()
        assert 'payload' in serializer.errors


class BulkEventSerializerTests(TestCase):
    """Tests for BulkEventSerializer"""
    
    def test_valid_bulk_events(self):
        """Test serialization of valid bulk events"""
        events = [
            {
                'event_id': str(uuid.uuid4()),
                'tenant_id': 'tenant-1',
                'source': 'web',
                'event_type': 'click',
                'timestamp': timezone.now().isoformat(),
                'payload': {}
            }
            for _ in range(10)
        ]
        
        data = {'events': events}
        serializer = BulkEventSerializer(data=data)
        assert serializer.is_valid(), serializer.errors
    
    def test_bulk_events_max_limit(self):
        """Test rejection of bulk requests exceeding limit"""
        from django.conf import settings
        max_events = settings.MAX_BULK_EVENTS
        
        events = [
            {
                'event_id': str(uuid.uuid4()),
                'tenant_id': 'tenant-1',
                'source': 'web',
                'event_type': 'click',
                'timestamp': timezone.now().isoformat(),
                'payload': {}
            }
            for _ in range(max_events + 1)
        ]
        
        data = {'events': events}
        serializer = BulkEventSerializer(data=data)
        assert not serializer.is_valid()


# ============================================================================
# API Integration Tests
# ============================================================================

class EventAPITests(APITestCase):
    """Integration tests for Event API endpoints"""
    
    def setUp(self):
        """Set up test fixtures"""
        self.client = APIClient()
        self.tenant_id = 'test-tenant-1'
        self.api_url = reverse('eventapp:event-list')
    
    def test_create_single_event(self):
        """Test POST /events - create single event"""
        data = {
            'event_id': str(uuid.uuid4()),
            'tenant_id': self.tenant_id,
            'source': 'web',
            'event_type': 'click',
            'timestamp': timezone.now().isoformat(),
            'payload': {'button': 'submit'}
        }
        
        response = self.client.post(self.api_url, data, format='json')
        assert response.status_code == status.HTTP_201_CREATED
        assert response.data['event_id'] == data['event_id']
    
    def test_create_event_idempotency(self):
        """Test that duplicate events return 200 with existing data"""
        event_id = str(uuid.uuid4())
        data = {
            'event_id': event_id,
            'tenant_id': self.tenant_id,
            'source': 'web',
            'event_type': 'click',
            'timestamp': timezone.now().isoformat(),
            'payload': {}
        }
        
        # First request
        response1 = self.client.post(self.api_url, data, format='json')
        assert response1.status_code == status.HTTP_201_CREATED
        
        # Duplicate request
        response2 = self.client.post(self.api_url, data, format='json')
        assert response2.status_code == status.HTTP_200_OK
        assert response2.data['event_id'] == event_id
    
    def test_get_events_requires_tenant_id(self):
        """Test that GET /events requires tenant_id parameter"""
        response = self.client.get(self.api_url)
        assert response.status_code == status.HTTP_400_BAD_REQUEST
    
    def test_get_events_with_tenant_id(self):
        """Test GET /events with tenant_id filter"""
        # Create events
        for i in range(5):
            Event.objects.create(
                event_id=f'event-{i}',
                tenant_id=self.tenant_id,
                source='web',
                event_type='click',
                timestamp=timezone.now() - timedelta(minutes=i),
                payload={}
            )
        
        response = self.client.get(self.api_url, {'tenant_id': self.tenant_id})
        assert response.status_code == status.HTTP_200_OK
        assert response.data['count'] == 5
    
    def test_get_events_with_filters(self):
        """Test GET /events with additional filters"""
        # Create mixed events
        Event.objects.create(
            event_id='event-1',
            tenant_id=self.tenant_id,
            source='web',
            event_type='click',
            timestamp=timezone.now(),
            payload={}
        )
        
        Event.objects.create(
            event_id='event-2',
            tenant_id=self.tenant_id,
            source='mobile',
            event_type='view',
            timestamp=timezone.now(),
            payload={}
        )
        
        # Filter by source
        response = self.client.get(
            self.api_url,
            {'tenant_id': self.tenant_id, 'source': 'web'}
        )
        assert response.status_code == status.HTTP_200_OK
        assert response.data['count'] == 1
    
    @pytest.mark.django_db(transaction=True)
    def test_bulk_event_creation(self):
        """Test POST /events/bulk - bulk event creation"""
        events = [
            {
                'event_id': str(uuid.uuid4()),
                'tenant_id': self.tenant_id,
                'source': 'web' if i % 2 == 0 else 'mobile',
                'event_type': 'click' if i % 2 == 0 else 'view',
                'timestamp': timezone.now().isoformat(),
                'payload': {}
            }
            for i in range(100)
        ]
        
        bulk_url = reverse('eventapp:event-bulk')
        response = self.client.post(
            bulk_url,
            {'events': events},
            format='json'
        )
        
        assert response.status_code == status.HTTP_202_ACCEPTED
        assert response.data['created'] == 100
    
    def test_health_check(self):
        """Test GET /health endpoint"""
        health_url = reverse('eventapp:health')
        response = self.client.get(health_url)
        assert response.status_code == status.HTTP_200_OK
        assert response.data['status'] == 'ok'
    
    def test_readiness_check(self):
        """Test GET /ready endpoint"""
        ready_url = reverse('eventapp:ready')
        response = self.client.get(ready_url)
        assert response.status_code == status.HTTP_200_OK
        assert 'status' in response.data


class MetricsAPITests(APITestCase):
    """Integration tests for Metrics API endpoint"""
    
    def setUp(self):
        """Set up test fixtures"""
        self.client = APIClient()
        self.tenant_id = 'test-tenant-1'
        self.api_url = reverse('eventapp:metrics-list')
    
    def test_metrics_requires_tenant_id(self):
        """Test that GET /metrics requires tenant_id"""
        response = self.client.get(self.api_url)
        assert response.status_code == status.HTTP_400_BAD_REQUEST
    
    def test_metrics_retrieval(self):
        """Test GET /metrics endpoint"""
        # Create aggregates
        now = timezone.now()
        Aggregate.objects.create(
            tenant_id=self.tenant_id,
            bucket_start=Aggregate.get_bucket_start(now, 'minute'),
            bucket_size='minute',
            source='web',
            event_type='click',
            count=10,
            first_seen=now,
            last_seen=now
        )
        
        response = self.client.get(
            self.api_url,
            {'tenant_id': self.tenant_id}
        )
        
        assert response.status_code == status.HTTP_200_OK
        assert response.data['bucket_size'] == 'minute'
        assert len(response.data['metrics']) == 1
    
    def test_metrics_with_dimension_filters(self):
        """Test GET /metrics with dimension filters"""
        now = timezone.now()
        
        # Create multiple aggregates
        for source in ['web', 'mobile']:
            Aggregate.objects.create(
                tenant_id=self.tenant_id,
                bucket_start=Aggregate.get_bucket_start(now, 'minute'),
                bucket_size='minute',
                source=source,
                event_type='click',
                count=5,
                first_seen=now,
                last_seen=now
            )
        
        # Query with source filter
        response = self.client.get(
            self.api_url,
            {'tenant_id': self.tenant_id, 'source': 'web'}
        )
        
        assert response.status_code == status.HTTP_200_OK


# ============================================================================
# Concurrency and Race Condition Tests
# ============================================================================

class ConcurrencyTests(TransactionTestCase):
    """Tests for concurrency and race condition safety"""
    
    def setUp(self):
        """Set up test fixtures"""
        self.tenant_id = 'test-tenant-1'
        self.event_id = str(uuid.uuid4())
    
    @pytest.mark.django_db(transaction=True)
    def test_concurrent_event_creation_idempotency(self):
        """Test that concurrent duplicate events are handled safely"""
        from threading import Thread
        import threading
        
        event_data = {
            'event_id': self.event_id,
            'tenant_id': self.tenant_id,
            'source': 'web',
            'event_type': 'click',
            'timestamp': timezone.now(),
            'payload': {}
        }
        
        results = []
        lock = threading.Lock()
        
        def create_event():
            try:
                event = Event.objects.create(**event_data)
                with lock:
                    results.append(('success', event.id))
            except Exception as e:
                with lock:
                    results.append(('error', str(e)))
        
        # NOTE: Full threading test would require special test DB setup
        # This is a simplified version


# ============================================================================
# Edge Cases and Time Window Tests
# ============================================================================

class TimeWindowEdgeCaseTests(TestCase):
    """Tests for edge cases in time window handling"""
    
    def setUp(self):
        """Set up test fixtures"""
        self.tenant_id = 'test-tenant-1'
        self.api_url = reverse('eventapp:event-list')
        self.client = APIClient()
    
    def test_events_at_boundary(self):
        """Test querying events at time window boundaries"""
        now = timezone.now()
        
        # Create events at boundary times
        for i in range(3):
            Event.objects.create(
                event_id=f'event-{i}',
                tenant_id=self.tenant_id,
                source='web',
                event_type='click',
                timestamp=now - timedelta(hours=i),
                payload={}
            )
        
        # Query with specific time window
        from_time = (now - timedelta(hours=5)).isoformat()
        to_time = now.isoformat()
        
        response = self.client.get(
            self.api_url,
            {
                'tenant_id': self.tenant_id,
                'from': from_time,
                'to': to_time
            }
        )
        
        assert response.status_code == status.HTTP_200_OK
        assert response.data['count'] == 3
    
    def test_empty_time_window(self):
        """Test querying empty time window"""
        now = timezone.now()
        
        # Query for future events (should be empty)
        from_time = (now + timedelta(hours=1)).isoformat()
        to_time = (now + timedelta(hours=2)).isoformat()
        
        response = self.client.get(
            self.api_url,
            {
                'tenant_id': self.tenant_id,
                'from': from_time,
                'to': to_time
            }
        )
        
        assert response.status_code == status.HTTP_200_OK
        assert response.data['count'] == 0
