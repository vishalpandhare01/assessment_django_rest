from django.urls import path, include
from rest_framework.routers import DefaultRouter
from .views import (
    EventViewSet,
    MetricsViewSet,
    HealthCheckView,
    ReadinessCheckView
)

app_name = 'eventapp'

# Create router for viewsets
router = DefaultRouter()
router.register(r'events', EventViewSet, basename='event')
router.register(r'metrics', MetricsViewSet, basename='metrics')

urlpatterns = [
    # Health checks
    path('health', HealthCheckView.as_view(), name='health'),
    path('ready', ReadinessCheckView.as_view(), name='ready'),
    
    # API routes
    path('', include(router.urls)),
]
