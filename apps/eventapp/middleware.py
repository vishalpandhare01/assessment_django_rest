from django.utils.deprecation import MiddlewareMixin
from django.http import JsonResponse
from django.core.cache import cache
from django.conf import settings
from rest_framework import status
import logging

logger = logging.getLogger(__name__)


class RateLimitMiddleware(MiddlewareMixin):
    """
    Rate limiting middleware for tenant-based API requests.
    
    Uses Django's cache to track request counts per tenant.
    Configuration in settings: MAX_REQUESTS_PER_HOUR_PER_TENANT
    """
    
    def process_request(self, request):
        """
        Check rate limits before processing request.
        
        Rate limit is per tenant_id extracted from request.
        """
        # Skip rate limiting for health checks
        if request.path.startswith('/health') or request.path.startswith('/ready'):
            return None
        
        # Extract tenant_id from request
        tenant_id = self._get_tenant_id(request)
        
        if not tenant_id:
            # If no tenant_id, allow but log
            logger.warning(f"Request without tenant_id: {request.path}")
            return None
        
        # Check rate limit
        cache_key = f"rate_limit:{tenant_id}:hour"
        current_count = cache.get(cache_key, 0)
        max_requests = settings.MAX_REQUESTS_PER_HOUR_PER_TENANT
        
        if current_count >= max_requests:
            logger.warning(
                f"Rate limit exceeded for tenant {tenant_id}: "
                f"{current_count}/{max_requests}"
            )
            return JsonResponse(
                {
                    'error': 'Rate limit exceeded',
                    'detail': f'Maximum {max_requests} requests per hour allowed'
                },
                status=status.HTTP_429_TOO_MANY_REQUESTS
            )
        
        # Increment counter
        cache.set(cache_key, current_count + 1, 3600)  # 1 hour expiry
        
        return None
    
    def _get_tenant_id(self, request):
        """
        Extract tenant_id from request.
        
        Priority:
        1. Query parameter: ?tenant_id=...
        2. Header: X-Tenant-ID
        3. Request body (for POST/PUT): tenant_id field
        """
        # Query parameter
        tenant_id = request.GET.get('tenant_id')
        if tenant_id:
            return tenant_id
        
        # Header
        tenant_id = request.META.get('HTTP_X_TENANT_ID')
        if tenant_id:
            return tenant_id
        
        # Request body
        if request.method in ['POST', 'PUT', 'PATCH']:
            try:
                import json
                if request.body:
                    data = json.loads(request.body)
                    if isinstance(data, dict):
                        return data.get('tenant_id')
                    elif isinstance(data, list) and data:
                        # For bulk requests
                        return data[0].get('tenant_id') if isinstance(data[0], dict) else None
            except (json.JSONDecodeError, AttributeError):
                pass
        
        return None
