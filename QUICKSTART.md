# Project Structure & Quick Start

## Directory Layout

```
d:/assisment/
├── manage.py                      # Django management script
├── requirements.txt               # Python dependencies
├── pytest.ini                     # Pytest configuration
├── db.sqlite3                     # Development database
│
├── README.md                      # Main documentation
├── PERFORMANCE.md                 # Performance optimization guide
├── examples.py                    # Practical usage examples
│
├── config/                        # Django project settings
│   ├── __init__.py
│   ├── settings.py               # Main configuration (INSTALLED_APPS, DRF settings, etc.)
│   ├── urls.py                   # Root URL routing
│   ├── asgi.py                   # ASGI application
│   └── wsgi.py                   # WSGI application
│
├── apps/                          # Application modules
│   ├── __init__.py
│   ├── utils.py                  # Shared utilities
│   │
│   └── eventapp/                 # Main event tracking app
│       ├── __init__.py
│       ├── models.py             # Event, Aggregate, AggregationJob models
│       ├── views.py              # API viewsets and views
│       ├── serializers.py        # Input/output serializers with validation
│       ├── urls.py               # App-specific URL routing
│       ├── admin.py              # Django admin configuration
│       ├── apps.py               # App configuration
│       ├── tests.py              # Comprehensive test suite
│       ├── middleware.py         # Rate limiting middleware
│       ├── exception_handlers.py # Custom exception handling
│       │
│       ├── management/           # Django management commands
│       │   ├── __init__.py
│       │   └── commands/
│       │       ├── __init__.py
│       │       └── aggregate_events.py  # Background aggregation command
│       │
│       └── migrations/           # Database migrations
│           └── __init__.py
```

## Core Components

### Models (models.py)
- **Event**: Individual event records with idempotent constraints
- **Aggregate**: Pre-computed time-bucketed aggregates
- **AggregationJob**: Tracking for background jobs

### Serializers (serializers.py)
- **EventSerializer**: Single event validation
- **BulkEventSerializer**: Bulk event validation with error collection
- **AggregateSerializer**: Aggregate response serialization

### Views (views.py)
- **EventViewSet**: POST/GET events, idempotency handling
- **MetricsViewSet**: Aggregated metrics queries
- **HealthCheckView**: Liveness endpoint
- **ReadinessCheckView**: Readiness endpoint

### Middleware (middleware.py)
- **RateLimitMiddleware**: Tenant-based rate limiting

### Management Commands (aggregate_events.py)
- Background aggregation with incremental processing
- Idempotent execution for safe reruns

### Tests (tests.py)
- Model tests, serializer tests, API integration tests
- Concurrency and race condition tests
- Edge case and time window tests

## Quick Start

### 1. Setup Environment
```bash
cd d:/assisment

# Create virtual environment (if not exists)
python -m venv .venv
.venv\Scripts\activate  # Windows
# source .venv/bin/activate  # Linux/Mac

# Install dependencies
pip install -r requirements.txt
```

### 2. Initialize Database
```bash
# Create migrations
python manage.py makemigrations apps.eventapp

# Apply migrations
python manage.py migrate

# Create superuser for admin
python manage.py createsuperuser
```

### 3. Run Development Server
```bash
python manage.py runserver

# Server will run at: http://localhost:8000
# Admin panel: http://localhost:8000/admin/
```

### 4. Health Check
```bash
# Test API is working
curl http://localhost:8000/api/health
# Expected: {"status":"ok"}
```

### 5. Run Tests
```bash
# Run all tests
pytest

# With coverage
pytest --cov=apps/eventapp

# Specific test file
pytest apps/eventapp/tests.py -v
```

### 6. Run Background Aggregation
```bash
# In a separate terminal (with .venv activated)
python manage.py aggregate_events --hours=1
```

## API Quick Reference

### Single Event
```bash
curl -X POST http://localhost:8000/api/events/ \
  -H "Content-Type: application/json" \
  -d '{
    "event_id": "evt-123",
    "tenant_id": "tenant-1",
    "source": "web",
    "event_type": "click",
    "timestamp": "2024-01-01T12:00:00Z",
    "payload": {"page": "/"}
  }'
```

### Bulk Events
```bash
curl -X POST http://localhost:8000/api/events/bulk/ \
  -H "Content-Type: application/json" \
  -d '{
    "events": [
      {"event_id": "evt-1", "tenant_id": "tenant-1", ...},
      {"event_id": "evt-2", "tenant_id": "tenant-1", ...}
    ]
  }'
```

### List Events
```bash
curl "http://localhost:8000/api/events/?tenant_id=tenant-1&source=web"
```

### Get Metrics
```bash
curl "http://localhost:8000/api/metrics/?tenant_id=tenant-1&bucket_size=minute"
```

## Configuration

### Environment Variables (optional)
Create `.env` file in project root:
```
SECRET_KEY=your-secret-key
DEBUG=True
ALLOWED_HOSTS=localhost,127.0.0.1
DATABASE_URL=sqlite:///db.sqlite3
```

### Key Settings (config/settings.py)
- `MAX_BULK_EVENTS`: 5000 (max events per bulk request)
- `MAX_PAYLOAD_SIZE`: 1048576 (1 MB max payload)
- `MAX_REQUESTS_PER_HOUR_PER_TENANT`: 100000 (rate limit)
- `AGGREGATION_BATCH_SIZE`: 1000 (background job batch)

## Development Workflow

### Making Code Changes
1. Edit files in `apps/eventapp/`
2. Server auto-reloads on save
3. Check `/api/health` to verify

### Database Changes
1. Modify model in `models.py`
2. Create migration: `python manage.py makemigrations`
3. Apply migration: `python manage.py migrate`

### Running Tests
```bash
# After making changes
pytest

# Run specific tests
pytest apps/eventapp/tests.py::EventModelTests::test_event_idempotency

# Watch mode (requires watch plugin)
ptw apps/eventapp/tests.py
```

## Debugging

### Django Shell
```bash
python manage.py shell

# Example commands
>>> from apps.eventapp.models import Event
>>> Event.objects.count()
>>> Event.objects.filter(tenant_id='tenant-1')
>>> from apps.eventapp.models import Aggregate
>>> Aggregate.objects.first()
```

### Query Debugging
```python
# In shell or test
from django.db import connection
from django.test.utils import CaptureQueriesContext

with CaptureQueriesContext(connection) as context:
    events = Event.objects.filter(tenant_id='tenant-1')
    
for query in context:
    print(query['sql'])
    print(f"Time: {query['time']}ms")
```

### Log Statements
```python
import logging
logger = logging.getLogger(__name__)

logger.info("Event created: event_id=%s", event.event_id)
logger.warning("Rate limit exceeded for tenant: %s", tenant_id)
logger.error("Aggregation failed", exc_info=True)
```

## Troubleshooting

### ModuleNotFoundError
```
Solution: Activate virtual environment
source .venv/bin/activate  # Linux/Mac
.venv\Scripts\activate     # Windows
```

### Database locked (SQLite)
```
Solution: Delete db.sqlite3 and remigrate
rm db.sqlite3
python manage.py migrate
```

### Port 8000 already in use
```
Solution: Use different port
python manage.py runserver 8001
```

### Import errors in tests
```
Solution: Install test dependencies
pip install pytest pytest-django
```

## Production Deployment

### Using Gunicorn
```bash
pip install gunicorn
gunicorn config.wsgi:application --bind 0.0.0.0:8000 --workers 4
```

### Environment Setup
```bash
export SECRET_KEY='your-production-secret'
export DEBUG=False
export ALLOWED_HOSTS='yourdomain.com'
export DATABASE_URL='postgresql://user:pass@host/db'
```

### Background Tasks with Cron
```bash
# /etc/crontab
*/5 * * * * cd /path/to/project && python manage.py aggregate_events --hours=1
```

## Resources

- [Django Documentation](https://docs.djangoproject.com/)
- [Django REST Framework](https://www.django-rest-framework.org/)
- [Pytest Documentation](https://docs.pytest.org/)
- [Database Indexing](https://wiki.postgresql.org/wiki/Performance_Optimization)

## Support

For issues or questions:
1. Check [README.md](./README.md) for full documentation
2. Review [PERFORMANCE.md](./PERFORMANCE.md) for optimization insights
3. Run `python examples.py` for API usage examples
4. Check application logs in console/files

---

**Last Updated**: 2024-01-01  
**Version**: 1.0.0
