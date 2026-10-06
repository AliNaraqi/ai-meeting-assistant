"""RQ task entrypoints."""

from __future__ import annotations

from app.services.pipeline import run_full_process_job


def process_meeting_job(job_id: str) -> None:
    run_full_process_job(job_id)
