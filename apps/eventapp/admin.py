from django.contrib import admin
from .models import Event, Aggregate, AggregationJob


@admin.register(Event)
class EventAdmin(admin.ModelAdmin):
    list_display = ['event_id', 'tenant_id', 'source', 'event_type', 'timestamp', 'created_at']
    list_filter = ['source', 'event_type', 'tenant_id', 'created_at']
    search_fields = ['event_id', 'tenant_id']
    readonly_fields = ['created_at']
    ordering = ['-created_at']


@admin.register(Aggregate)
class AggregateAdmin(admin.ModelAdmin):
    list_display = ['tenant_id', 'bucket_start', 'bucket_size', 'source', 'event_type', 'count']
    list_filter = ['bucket_size', 'source', 'event_type', 'tenant_id']
    search_fields = ['tenant_id']
    readonly_fields = ['created_at', 'updated_at', 'count']
    ordering = ['-bucket_start']


@admin.register(AggregationJob)
class AggregationJobAdmin(admin.ModelAdmin):
    list_display = ['job_id', 'status', 'tenant_id', 'events_processed', 'aggregates_created', 'created_at']
    list_filter = ['status', 'created_at']
    search_fields = ['job_id', 'tenant_id']
    readonly_fields = ['created_at', 'updated_at']
    ordering = ['-created_at']
