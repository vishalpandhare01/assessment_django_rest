import logging
import asyncio
import uuid
from datetime import datetime, timedelta

from django.shortcuts import render
from django.db import transaction, IntegrityError
from django.utils import timezone
from django.core.paginator import Paginator
from django.db.models import Q, Count, Max, Min, F
from django.conf import settings
from django.http import JsonResponse
from django.views import View

from rest_framework import viewsets, status, permissions, pagination
from rest_framework.decorators import api_view, action
from rest_framework.response import Response
from rest_framework.exceptions import ValidationError

from .models import Event, Aggregate, AggregationJob
from .serializers import (
    EventSerializer, 
    BulkEventSerializer, 
    AggregateSerializer,
    AggregationJobSerializer
)

logger = logging.getLogger(__name__)


class HealthCheckView(View):
    """Basic liveness check - always responds"""
    
    def get(self, request):
        return JsonResponse({'status': 'ok'}, status=200)


class ReadinessCheckView(View):
    """Readiness check including database connectivity"""
    
    def get(self, request):
        try:
            # Try a simple database query
            Event.objects.exists()
            Aggregate.objects.exists()
            
            return JsonResponse(
                {'status': 'ready', 'database': 'connected'},
                status=200
            )
        except Exception as e:
            logger.error(f"Readiness check failed: {e}")
            return JsonResponse(
                {'status': 'not_ready', 'database': 'disconnected', 'error': str(e)},
                status=503
            )


class EventViewSet(viewsets.ModelViewSet):
    """
    ViewSet for Event management.
    
    Endpoints:
    - POST /events - Create single event (idempotent)
    - GET /events - List events (filtered, paginated)
    - POST /events/bulk - Bulk create events
    """
    queryset = Event.objects.all()
    serializer_class = EventSerializer
    permission_classes = [permissions.AllowAny]
    pagination_class = pagination.PageNumberPagination
    
    def get_queryset(self):
        """
        Filter events by tenant and optional dimensions.
        
        Query parameters:
        - tenant_id (required)
        - source (optional)
        - event_type (optional)
        - from (ISO datetime)
        - to (ISO datetime)
        """
        queryset = Event.objects.all()
        
        # Mandatory: tenant_id
        tenant_id = self.request.query_params.get('tenant_id')
        if not tenant_id:
            raise ValidationError({'tenant_id': 'tenant_id is required'})
        
        queryset = queryset.filter(tenant_id=tenant_id)
        
        # Optional filters
        source = self.request.query_params.get('source')
        if source:
            queryset = queryset.filter(source=source)
        
        event_type = self.request.query_params.get('event_type')
        if event_type:
            queryset = queryset.filter(event_type=event_type)
        
        # Time window
        from_dt = self.request.query_params.get('from')
        to_dt = self.request.query_params.get('to')
        
        if from_dt:
            try:
                from_dt = timezone.datetime.fromisoformat(from_dt)
                if from_dt.tzinfo is None:
                    from_dt = timezone.make_aware(from_dt)
                queryset = queryset.filter(timestamp__gte=from_dt)
            except (ValueError, AttributeError) as e:
                logger.warning(f"Invalid 'from' parameter: {from_dt}")
        
        if to_dt:
            try:
                to_dt = timezone.datetime.fromisoformat(to_dt)
                if to_dt.tzinfo is None:
                    to_dt = timezone.make_aware(to_dt)
                queryset = queryset.filter(timestamp__lte=to_dt)
            except (ValueError, AttributeError) as e:
                logger.warning(f"Invalid 'to' parameter: {to_dt}")
        
        # Stable sorting
        queryset = queryset.order_by('-timestamp', '-created_at', 'event_id')
        
        return queryset
    
    def create(self, request, *args, **kwargs):
        """
        Create a single event with idempotency.
        
        If event_id + tenant_id already exists, returns 200 with existing event.
        Otherwise creates new event.
        """
        serializer = self.get_serializer(data=request.data)
        
        try:
            serializer.is_valid(raise_exception=True)
        except ValidationError as e:
            # Check if it's an idempotency issue
            if 'already exists' in str(e):
                # Return existing event
                event_id = request.data.get('event_id')
                tenant_id = request.data.get('tenant_id')
                try:
                    existing_event = Event.objects.get(
                        event_id=event_id,
                        tenant_id=tenant_id
                    )
                    return Response(
                        EventSerializer(existing_event).data,
                        status=status.HTTP_200_OK
                    )
                except Event.DoesNotExist:
                    pass
            
            raise
        
        self.perform_create(serializer)
        headers = self.get_success_headers(serializer.data)
        return Response(
            serializer.data,
            status=status.HTTP_201_CREATED,
            headers=headers
        )
    
    @action(detail=False, methods=['post'])
    def bulk(self, request):
        """
        Bulk create events (up to 5000).
        
        Request body:
        {
            "events": [
                {"event_id": "...", "tenant_id": "...", ...},
                ...
            ]
        }
        
        Response:
        {
            "created": 4999,
            "duplicates": 1,
            "failed": 0,
            "errors": []
        }
        """
        serializer = BulkEventSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        
        validated_events = serializer.validated_data.get('validated_events', [])
        validation_errors = serializer.validated_data.get('validation_errors', [])
        
        created_count = 0
        duplicate_count = 0
        failed_count = len(validation_errors)
        errors = validation_errors
        
        # Batch create with error handling
        try:
            # Use bulk_create for throughput, but need to handle IntegrityError
            for event_data in validated_events:
                try:
                    with transaction.atomic():
                        Event.objects.create(**event_data)
                        created_count += 1
                except IntegrityError:
                    # Duplicate event_id + tenant_id
                    duplicate_count += 1
                    logger.debug(
                        f"Duplicate event: {event_data.get('event_id')} "
                        f"for tenant {event_data.get('tenant_id')}"
                    )
                except Exception as e:
                    failed_count += 1
                    errors.append({
                        'event_id': event_data.get('event_id'),
                        'error': str(e)
                    })
                    logger.error(f"Failed to create event: {e}")
        except Exception as e:
            logger.error(f"Bulk create failed: {e}")
            return Response(
                {
                    'error': 'Bulk create failed',
                    'detail': str(e)
                },
                status=status.HTTP_500_INTERNAL_SERVER_ERROR
            )
        
        return Response({
            'created': created_count,
            'duplicates': duplicate_count,
            'failed': failed_count,
            'errors': errors
        }, status=status.HTTP_202_ACCEPTED)


class MetricsViewSet(viewsets.ViewSet):
    """
    ViewSet for retrieving aggregated metrics.
    
    GET /metrics
    
    Query parameters:
    - tenant_id (required)
    - bucket_size (minute|hour, default: minute)
    - source (optional)
    - event_type (optional)
    - from (ISO datetime)
    - to (ISO datetime)
    """
    permission_classes = [permissions.AllowAny]
    
    def list(self, request):
        """
        Get aggregated metrics for a tenant.
        
        Uses pre-computed aggregates for efficient querying.
        """
        # Mandatory: tenant_id
        tenant_id = request.query_params.get('tenant_id')
        if not tenant_id:
            raise ValidationError({'tenant_id': 'tenant_id is required'})
        
        # Optional parameters
        bucket_size = request.query_params.get('bucket_size', 'minute')
        if bucket_size not in ['minute', 'hour']:
            raise ValidationError({'bucket_size': 'Must be "minute" or "hour"'})
        
        source = request.query_params.get('source')
        event_type = request.query_params.get('event_type')
        
        # Time window
        from_dt = request.query_params.get('from')
        to_dt = request.query_params.get('to')
        
        queryset = Aggregate.objects.filter(
            tenant_id=tenant_id,
            bucket_size=bucket_size
        )
        
        # Apply dimension filters
        if source:
            queryset = queryset.filter(source=source)
        else:
            queryset = queryset.filter(source__isnull=True)
        
        if event_type:
            queryset = queryset.filter(event_type=event_type)
        else:
            queryset = queryset.filter(event_type__isnull=True)
        
        # Apply time window
        if from_dt:
            try:
                from_dt = timezone.datetime.fromisoformat(from_dt)
                if from_dt.tzinfo is None:
                    from_dt = timezone.make_aware(from_dt)
                queryset = queryset.filter(bucket_start__gte=from_dt)
            except (ValueError, AttributeError):
                logger.warning(f"Invalid 'from' parameter: {from_dt}")
        
        if to_dt:
            try:
                to_dt = timezone.datetime.fromisoformat(to_dt)
                if to_dt.tzinfo is None:
                    to_dt = timezone.make_aware(to_dt)
                queryset = queryset.filter(bucket_start__lte=to_dt)
            except (ValueError, AttributeError):
                logger.warning(f"Invalid 'to' parameter: {to_dt}")
        
        # Order by bucket_start
        queryset = queryset.order_by('bucket_start')
        
        # Serialize and return
        serializer = AggregateSerializer(queryset, many=True)
        
        return Response({
            'tenant_id': tenant_id,
            'bucket_size': bucket_size,
            'dimensions': {
                'source': source,
                'event_type': event_type,
            },
            'time_window': {
                'from': from_dt.isoformat() if from_dt else None,
                'to': to_dt.isoformat() if to_dt else None,
            },
            'metrics': serializer.data
        })
