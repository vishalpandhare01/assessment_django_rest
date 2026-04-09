from rest_framework.views import exception_handler
from rest_framework.response import Response
from rest_framework import status
import logging

logger = logging.getLogger(__name__)


def custom_exception_handler(exc, context):
    """
    Custom exception handler for API responses.
    
    Provides consistent error formatting across all endpoints.
    """
    # Call the default exception handler
    response = exception_handler(exc, context)
    
    if response is not None:
        # DRF managed exception
        return response
    
    # Unhandled exceptions
    logger.error(f"Unhandled exception: {exc}", exc_info=True)
    
    return Response(
        {
            'error': 'Internal server error',
            'detail': str(exc)
        },
        status=status.HTTP_500_INTERNAL_SERVER_ERROR
    )
