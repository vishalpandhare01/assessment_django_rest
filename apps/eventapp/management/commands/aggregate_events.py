import logging
import uuid
from datetime import timedelta

from django.core.management.base import BaseCommand, CommandError
from django.utils import timezone
from django.db import transaction
from django.db.models import Count

from apps.eventapp.models import Event, Aggregate, AggregationJob

logger = logging.getLogger(__name__)


class Command(BaseCommand):
    """
    Django management command to process event aggregation.
    
    Incremental and idempotent background aggregation task.
    
    Usage:
        python manage.py aggregate_events [--tenant_id=<id>] [--bucket_size=minute|hour] [--hours=<n>]
    
    Examples:
        # Aggregate all events from last hour (minute-level bucketing)
        python manage.py aggregate_events --hours=1
        
        # Aggregate specific tenant from last 24 hours (hour-level bucketing)
        python manage.py aggregate_events --tenant_id=tenant1 --bucket_size=hour --hours=24
    """
    
    help = 'Process event aggregation.'
    
    def add_arguments(self, parser):
        parser.add_argument(
            '--tenant_id',
            type=str,
            help='Specific tenant_id to aggregate (if not provided, aggregates all)',
        )
        parser.add_argument(
            '--bucket_size',
            type=str,
            choices=['minute', 'hour'],
            default='minute',
            help='Aggregation bucket size (minute or hour)',
        )
        parser.add_argument(
            '--hours',
            type=int,
            default=1,
            help='Hours back from now to aggregate',
        )
        parser.add_argument(
            '--lookback',
            type=int,
            default=5,
            help='Days back to look for unaggregated events',
        )
    
    def handle(self, *args, **options):
        """Execute aggregation"""
        tenant_id = options.get('tenant_id')
        bucket_size = options.get('bucket_size', 'minute')
        hours_back = options.get('hours', 1)
        lookback_days = options.get('lookback', 5)
        
        # Create job record for tracking
        job = AggregationJob.objects.create(
            job_id=str(uuid.uuid4()),
            status='running',
            tenant_id=tenant_id,
            bucket_size=bucket_size,
            start_time=timezone.now(),
        )
        
        try:
            now = timezone.now()
            lookback_start = now - timedelta(days=lookback_days)
            window_start = now - timedelta(hours=hours_back)
            
            self.stdout.write(
                f"Aggregating events: tenant={tenant_id}, "
                f"bucket_size={bucket_size}, lookback={lookback_days} days"
            )
            
            # Get distinct (tenant_id, source, event_type, bucket) combinations
            # from events not yet aggregated
            events = Event.objects.filter(
                created_at__gte=lookback_start,
                timestamp__gte=window_start
            )
            
            if tenant_id:
                events = events.filter(tenant_id=tenant_id)
            
            # Process events in batches
            batch_size = options.get('batch_size', 1000)
            events_processed = 0
            aggregates_created = 0
            aggregates_updated = 0
            
            # Get unique tenants
            tenants = events.values_list('tenant_id', flat=True).distinct()
            
            for current_tenant_id in tenants:
                tenant_events = events.filter(tenant_id=current_tenant_id)
                
                # Get unique (source, event_type) combinations
                combinations = tenant_events.values('source', 'event_type').distinct()
                
                for combo in combinations:
                    combo_events = tenant_events.filter(**combo)
                    
                    # Process events for this combination
                    for event in combo_events[:batch_size]:
                        try:
                            with transaction.atomic():
                                aggregate, created = Aggregate.objects.update_or_create(
                                    tenant_id=event.tenant_id,
                                    bucket_start=Aggregate.get_bucket_start(event.timestamp, bucket_size),
                                    bucket_size=bucket_size,
                                    source=event.source,
                                    event_type=event.event_type,
                                    defaults={
                                        'count': 1,
                                        'first_seen': event.timestamp,
                                        'last_seen': event.timestamp,
                                    }
                                )
                                
                                if not created:
                                    # Update existing
                                    aggregate.count += 1
                                    aggregate.last_seen = max(
                                        aggregate.last_seen or event.timestamp,
                                        event.timestamp
                                    )
                                    aggregate.save(update_fields=['count', 'last_seen'])
                                    aggregates_updated += 1
                                else:
                                    aggregates_created += 1
                                
                                events_processed += 1
                        except Exception as e:
                            logger.error(f"Error aggregating event {event.event_id}: {e}")
                            continue
            
            # Update job
            job.status = 'completed'
            job.end_time = timezone.now()
            job.events_processed = events_processed
            job.aggregates_created = aggregates_created
            job.aggregates_updated = aggregates_updated
            job.save()
            
            self.stdout.write(
                self.style.SUCCESS(
                    f'Aggregation completed: '
                    f'processed={events_processed}, '
                    f'created={aggregates_created}, '
                    f'updated={aggregates_updated}'
                )
            )
            
        except Exception as e:
            logger.error(f"Aggregation failed: {e}", exc_info=True)
            job.status = 'failed'
            job.error_message = str(e)
            job.end_time = timezone.now()
            job.save()
            
            self.stdout.write(
                self.style.ERROR(f'Aggregation failed: {e}')
            )
            raise CommandError(str(e))
