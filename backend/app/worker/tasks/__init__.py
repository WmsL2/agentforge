"""Background tasks."""

from app.worker.tasks.smoke import echo_task

__all__ = ["echo_task"]
