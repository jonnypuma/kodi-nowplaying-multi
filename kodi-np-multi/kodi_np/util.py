"""Small shared helpers."""
from __future__ import annotations

import json
import time
from html import escape

from kodi_np import config as _c


def build_cast_html(cast_list, limit=8):
    """Render a cast strip with names immediately; thumbs lazy-load via data-thumb.

    Kodi/NFO scrapers often list the same actor more than once with alternate
    role strings (e.g. "Adam / He-Man" and "Adam Glenn / He-Man"). Deduplicate
    by actor name and keep the richer role / thumbnail.
    """
    if not isinstance(cast_list, list) or not cast_list:
        return ""
    members = []
    by_name = {}
    for entry in cast_list:
        if not isinstance(entry, dict):
            continue
        name = (entry.get("name") or "").strip()
        if not name:
            continue
        thumb = entry.get("thumbnail") or ""
        if isinstance(thumb, str) and (
            "DefaultActor" in thumb or "DefaultImage" in thumb or not thumb.strip()
        ):
            thumb = ""
        role = (entry.get("role") or "").strip()
        key = name.casefold()
        existing = by_name.get(key)
        if existing is not None:
            if len(role) > len(existing["role"]):
                existing["role"] = role
            if thumb and not existing["thumbnail"]:
                existing["thumbnail"] = thumb
            continue
        member = {"name": name, "role": role, "thumbnail": thumb}
        by_name[key] = member
        members.append(member)
        if len(members) >= limit:
            break
    if not members:
        return ""

    cards = []
    for member in members:
        name = escape(member["name"])
        role = escape(member["role"])
        thumb_attr = escape(member["thumbnail"], quote=True) if member["thumbnail"] else ""
        role_html = f'<span class="cast-role">{role}</span>' if role else ""
        cards.append(
            '<div class="cast-card">'
            f'<div class="cast-avatar" data-thumb="{thumb_attr}" aria-hidden="true"></div>'
            f'<div class="cast-name">{name}</div>'
            f"{role_html}"
            "</div>"
        )
    payload = escape(json.dumps(members), quote=True)
    return (
        '<div class="cast-strip" id="cast-strip" data-cast="' + payload + '">'
        '<div class="cast-heading">Cast</div>'
        '<div class="cast-row">' + "".join(cards) + "</div>"
        "</div>"
    )


def build_meta_labeled_line(label: str, value: str) -> str:
    """One labeled metadata row, e.g. YEAR: 2026."""
    if not value:
        return ""
    safe_label = escape(str(label), quote=True)
    safe_value = escape(str(value), quote=True)
    return (
        f'<div class="meta-labeled-line">'
        f'<span class="meta-label">{safe_label}:</span> '
        f'<span class="meta-labeled-value">{safe_value}</span>'
        f"</div>"
    )


def build_meta_labeled_lines(*lines: str) -> str:
    """Stack labeled metadata rows vertically."""
    items = [line for line in lines if line]
    if not items:
        return ""
    return f'<div class="meta-labeled-lines">{"".join(items)}</div>'


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
