"""Minimal Celery smoke task for infrastructure validation."""

from celery import shared_task


@shared_task(name="agentforge.smoke.echo")
def echo_task(value: str) -> str:
    """Return the input value unchanged."""
    return value
