"""Small shared helpers."""
from __future__ import annotations

import time
from html import escape

from kodi_np import config as _c

def prune_load_jobs(force_id=None):
    """Remove finished/stale load jobs and optionally drop a specific job id."""
    now = time.time()
    with _c.load_lock:
        if force_id is not None:
            _c.load_jobs.pop(force_id, None)

        expired = []
        for job_id, job in _c.load_jobs.items():
            updated = job.get("updated_at") or job.get("created_at") or 0
            status = job.get("status")
            age = now - updated
            if status in ("done", "error", "consumed") and age >= _c.LOAD_JOB_TTL_SECONDS:
                expired.append(job_id)
            elif age >= _c.LOAD_JOB_STALE_SECONDS:
                expired.append(job_id)
        for job_id in expired:
            _c.load_jobs.pop(job_id, None)

        # Hard cap: drop oldest finished jobs first, then oldest overall
        if len(_c.load_jobs) > _c.LOAD_JOB_MAX:
            ordered = sorted(
                _c.load_jobs.items(),
                key=lambda item: (
                    0 if item[1].get("status") in ("done", "error", "consumed") else 1,
                    item[1].get("updated_at") or item[1].get("created_at") or 0,
                ),
            )
            overflow = len(_c.load_jobs) - _c.LOAD_JOB_MAX
            for job_id, _ in ordered[:overflow]:
                _c.load_jobs.pop(job_id, None)

def html_escape(value):
    return escape(str(value), quote=True) if value is not None else ""
