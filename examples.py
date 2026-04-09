#!/usr/bin/env python
"""
Practical usage examples for the Event Tracking System API.

Run as: python examples.py
"""

import requests
import json
from datetime import datetime, timedelta
import uuid

BASE_URL = "http://localhost:8000/api"

# ============================================================================
# Example 1: Health Checks
# ============================================================================

def example_health_checks():
    """Verify API is running"""
    print("\n=== Health Checks ===")
    
    # Liveness check
    response = requests.get(f"{BASE_URL}/health")
    print(f"Health: {response.json()}")
    
    # Readiness check
    response = requests.get(f"{BASE_URL}/ready")
    print(f"Ready: {response.json()}")


# ============================================================================
# Example 2: Single Event Ingestion
# ============================================================================

def example_single_event():
    """Create a single event"""
    print("\n=== Single Event Ingestion ===")
    
    event = {
        "event_id": str(uuid.uuid4()),
        "tenant_id": "company-1",
        "source": "web",
        "event_type": "click",
        "timestamp": datetime.utcnow().isoformat() + "Z",
        "payload": {
            "page": "/dashboard",
            "button": "export",
            "success": True
        }
    }
    
    response = requests.post(f"{BASE_URL}/events/", json=event)
    print(f"Status: {response.status_code}")
    print(f"Response: {json.dumps(response.json(), indent=2)}")
    
    # Idempotent test: submit same event again
    print("\nSubmitting duplicate event (idempotent)...")
    response = requests.post(f"{BASE_URL}/events/", json=event)
    print(f"Status: {response.status_code} (should be 200)")
    print(f"Response: {json.dumps(response.json(), indent=2)}")


# ============================================================================
# Example 3: Bulk Event Ingestion
# ============================================================================

def example_bulk_events():
    """Create multiple events in one request"""
    print("\n=== Bulk Event Ingestion ===")
    
    events = []
    for i in range(100):
        events.append({
            "event_id": f"bulk-event-{i}-{uuid.uuid4()}",
            "tenant_id": "company-2",
            "source": "mobile" if i % 2 == 0 else "web",
            "event_type": "view" if i % 3 == 0 else "click",
            "timestamp": (datetime.utcnow() - timedelta(minutes=i)).isoformat() + "Z",
            "payload": {
                "session_id": f"session-{i}",
                "interaction_id": i
            }
        })
    
    bulk_data = {"events": events}
    
    response = requests.post(f"{BASE_URL}/events/bulk/", json=bulk_data)
    print(f"Status: {response.status_code}")
    print(f"Response: {json.dumps(response.json(), indent=2)}")


# ============================================================================
# Example 4: List Events with Filters
# ============================================================================

def example_list_events():
    """Retrieve events with various filters"""
    print("\n=== List Events ===")
    
    # Basic query
    print("\n1. All events for a tenant:")
    params = {"tenant_id": "company-1"}
    response = requests.get(f"{BASE_URL}/events/", params=params)
    print(f"Total events: {response.json()['count']}")
    print(f"First event: {json.dumps(response.json()['results'][0] if response.json()['results'] else {}, indent=2)}")
    
    # With source filter
    print("\n2. Events filtered by source:")
    params = {"tenant_id": "company-1", "source": "web"}
    response = requests.get(f"{BASE_URL}/events/", params=params)
    print(f"Web events: {response.json()['count']}")
    
    # With time range
    print("\n3. Events within time range:")
    now = datetime.utcnow()
    from_time = (now - timedelta(hours=1)).isoformat() + "Z"
    to_time = now.isoformat() + "Z"
    params = {
        "tenant_id": "company-1",
        "from": from_time,
        "to": to_time
    }
    response = requests.get(f"{BASE_URL}/events/", params=params)
    print(f"Events in last hour: {response.json()['count']}")
    
    # Pagination
    print("\n4. Pagination (page 2):")
    params = {"tenant_id": "company-1", "page": 2}
    response = requests.get(f"{BASE_URL}/events/", params=params)
    print(f"Page 2 results: {response.json()['count']}")


# ============================================================================
# Example 5: Metrics/Aggregation Query
# ============================================================================

def example_metrics():
    """Query aggregated metrics"""
    print("\n=== Metrics Query ===")
    
    # Basic metrics
    print("\n1. Minute-level metrics for a tenant:")
    params = {
        "tenant_id": "company-1",
        "bucket_size": "minute"
    }
    response = requests.get(f"{BASE_URL}/metrics/", params=params)
    data = response.json()
    print(f"Metrics buckets: {len(data['metrics'])}")
    if data['metrics']:
        print(f"First bucket: {json.dumps(data['metrics'][0], indent=2)}")
    
    # Metrics by source
    print("\n2. Metrics filtered by source:")
    params = {
        "tenant_id": "company-1",
        "bucket_size": "minute",
        "source": "web"
    }
    response = requests.get(f"{BASE_URL}/metrics/", params=params)
    data = response.json()
    print(f"Web metrics: {len(data['metrics'])} buckets")
    
    # Hour-level metrics
    print("\n3. Hour-level metrics:")
    params = {
        "tenant_id": "company-1",
        "bucket_size": "hour"
    }
    response = requests.get(f"{BASE_URL}/metrics/", params=params)
    data = response.json()
    print(f"Hour metrics: {len(data['metrics'])} buckets")


# ============================================================================
# Example 6: Rate Limiting
# ============================================================================

def example_rate_limiting():
    """Test rate limiting behavior"""
    print("\n=== Rate Limiting ===")
    
    # Send many requests to same tenant
    print(f"Sending 10 requests from same tenant...")
    for i in range(10):
        event = {
            "event_id": str(uuid.uuid4()),
            "tenant_id": "rate-limit-test",
            "source": "web",
            "event_type": "click",
            "timestamp": datetime.utcnow().isoformat() + "Z",
            "payload": {"request": i}
        }
        response = requests.post(f"{BASE_URL}/events/", json=event)
        print(f"  Request {i+1}: Status {response.status_code}")


# ============================================================================
# Example 7: Error Handling
# ============================================================================

def example_error_handling():
    """Demonstrate error handling"""
    print("\n=== Error Handling ===")
    
    # Missing tenant_id
    print("1. Missing tenant_id on events list:")
    response = requests.get(f"{BASE_URL}/events/")
    print(f"  Status: {response.status_code}")
    print(f"  Error: {response.json()}")
    
    # Empty event_id
    print("\n2. Empty event_id:")
    event = {
        "event_id": "",
        "tenant_id": "company-1",
        "source": "web",
        "event_type": "click",
        "timestamp": datetime.utcnow().isoformat() + "Z",
        "payload": {}
    }
    response = requests.post(f"{BASE_URL}/events/", json=event)
    print(f"  Status: {response.status_code}")
    print(f"  Errors: {response.json()}")
    
    # Future timestamp
    print("\n3. Future timestamp:")
    event = {
        "event_id": str(uuid.uuid4()),
        "tenant_id": "company-1",
        "source": "web",
        "event_type": "click",
        "timestamp": (datetime.utcnow() + timedelta(hours=1)).isoformat() + "Z",
        "payload": {}
    }
    response = requests.post(f"{BASE_URL}/events/", json=event)
    print(f"  Status: {response.status_code}")
    print(f"  Errors: {response.json()}")


# ============================================================================
# Example 8: Background Aggregation
# ============================================================================

def example_aggregation_command():
    """Run background aggregation"""
    print("\n=== Background Aggregation ===")
    
    print("""
To run background aggregation, use:

1. Aggregate all events from last hour:
   python manage.py aggregate_events --hours=1

2. Aggregate specific tenant:
   python manage.py aggregate_events --tenant_id=company-1 --hours=24

3. Hour-level aggregation:
   python manage.py aggregate_events --bucket_size=hour --hours=24

4. View aggregation jobs:
   python manage.py shell
   >>> from apps.eventapp.models import AggregationJob
   >>> jobs = AggregationJob.objects.all().order_by('-created_at')
   >>> for job in jobs:
   ...     print(f"{job.job_id}: {job.status}")
    """)


# ============================================================================
# Example 9: Concurrency Test
# ============================================================================

def example_concurrent_requests():
    """Test concurrent requests"""
    print("\n=== Concurrent Requests ===")
    
    import concurrent.futures
    
    def create_event(i):
        event = {
            "event_id": f"concurrent-{i}-{uuid.uuid4()}",
            "tenant_id": "concurrent-test",
            "source": "web",
            "event_type": "click",
            "timestamp": datetime.utcnow().isoformat() + "Z",
            "payload": {"index": i}
        }
        try:
            response = requests.post(f"{BASE_URL}/events/", json=event, timeout=5)
            return (i, response.status_code)
        except Exception as e:
            return (i, f"Error: {e}")
    
    print("Sending 50 concurrent requests...")
    with concurrent.futures.ThreadPoolExecutor(max_workers=10) as executor:
        results = list(executor.map(create_event, range(50)))
    
    success = sum(1 for _, status in results if status == 201)
    print(f"Success: {success}/50")
    print(f"Failures: {50 - success}")


# ============================================================================
# Main
# ============================================================================

if __name__ == "__main__":
    print("=" * 70)
    print("Event Tracking System - API Examples")
    print("=" * 70)
    
    try:
        # Run examples
        example_health_checks()
        example_single_event()
        example_bulk_events()
        example_list_events()
        example_metrics()
        example_rate_limiting()
        example_error_handling()
        example_aggregation_command()
        example_concurrent_requests()
        
    except Exception as e:
        print(f"\n❌ Error: {e}")
        print("Make sure the server is running: python manage.py runserver")
    
    print("\n" + "=" * 70)
    print("Examples completed!")
    print("=" * 70)
