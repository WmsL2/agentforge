# How to: Add a Background Task

## Overview

Background tasks run asynchronously outside the request-response cycle. Your project uses **celery** as the task queue.

Workflow runs use the stable `agentforge.workflow.execute` task. Producers send
only a string `run_id`; the worker reconstructs its own database, Tool Platform,
MCP, Agent Runtime, observer, and workflow-engine dependencies for each task.
PostgreSQL claim/lease fencing remains the execution authority, so broker
delivery or redelivery alone never grants permission to execute a run.

## Step-by-Step

### 1. Create the task
```python
# app/worker/tasks/notifications.py
from app.worker.celery_app import celery_app


@celery_app.task(name="send_notification")
def send_notification(user_id: str, message: str) -> dict:
    """Send a notification to a user."""
    # Your logic here — email, push notification, etc.
    print(f"Sending to {user_id}: {message}")
    return {"status": "sent", "user_id": user_id}
```

### 2. Call it from your API

```python
# In any route or service:
from app.worker.tasks.notifications import send_notification

# Fire and forget
send_notification.delay("user_123", "Your order is ready!")

# Or with options
send_notification.apply_async(
    args=["user_123", "Your order is ready!"],
    countdown=60,  # Delay 60 seconds
)
```

### 3. Add scheduling (optional)
In `celery_app.py`, add to `beat_schedule`:
```python
celery_app.conf.beat_schedule["daily-digest"] = {
    "task": "send_notification",
    "schedule": crontab(hour=9, minute=0),  # Daily at 9 AM
    "args": ["broadcast", "Daily digest"],
}
```

### 4. Run the worker

```bash
make celery-worker    # Start worker
make celery-beat      # Start scheduler (for cron jobs)
make celery-flower    # Start monitoring UI (optional)
```

On Windows, run workflow workers with Celery's solo pool:

```bash
uv run celery -A app.worker.celery_app:celery_app worker --pool=solo
```

Tasks are acknowledged late and rejected on worker loss. A redelivery while a
previous lease is still valid can therefore return `not_claimed`; expired-lease
recovery depends on the separate recovery scanner rather than blind task retry.
