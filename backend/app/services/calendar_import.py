"""Calendar ICS metadata import helpers."""

from __future__ import annotations

import re
from datetime import UTC, datetime
from typing import Any

from fastapi import HTTPException, status

_PROP_RE = re.compile(r"^([A-Z]+)(?:;[^:]*)?:(.*)$")


def _unescape(value: str) -> str:
    return (
        value.replace("\\n", "\n")
        .replace("\\,", ",")
        .replace("\\;", ";")
        .replace("\\\\", "\\")
        .strip()
    )


def _parse_ics_datetime(raw: str) -> datetime | None:
    value = raw.strip()
    for fmt in ("%Y%m%dT%H%M%SZ", "%Y%m%dT%H%M%S", "%Y%m%d"):
        try:
            parsed = datetime.strptime(value, fmt)
            if fmt.endswith("Z") or value.endswith("Z"):
                return parsed.replace(tzinfo=UTC)
            return parsed.replace(tzinfo=UTC)
        except ValueError:
            continue
    return None


def parse_ics_event(ics_text: str) -> dict[str, Any]:
    """Extract SUMMARY/DTSTART/DESCRIPTION/LOCATION/UID from the first VEVENT."""
    text = ics_text.replace("\r\n", "\n").replace("\r", "\n")
    # Unfold folded lines (RFC 5545).
    text = re.sub(r"\n[ \t]", "", text)
    if "BEGIN:VEVENT" not in text.upper():
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={
                "error": {
                    "code": "validation_error",
                    "message": "ICS payload must contain a VEVENT.",
                }
            },
        )

    in_event = False
    fields: dict[str, str] = {}
    for line in text.split("\n"):
        upper = line.upper()
        if upper.startswith("BEGIN:VEVENT"):
            in_event = True
            continue
        if upper.startswith("END:VEVENT"):
            break
        if not in_event:
            continue
        match = _PROP_RE.match(line)
        if not match:
            continue
        key, value = match.group(1).upper(), _unescape(match.group(2))
        if key in {"SUMMARY", "DESCRIPTION", "LOCATION", "UID", "DTSTART"} and key not in fields:
            fields[key] = value

    title = fields.get("SUMMARY")
    if not title:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={
                "error": {
                    "code": "validation_error",
                    "message": "VEVENT is missing SUMMARY.",
                }
            },
        )

    occurred_at = _parse_ics_datetime(fields["DTSTART"]) if "DTSTART" in fields else None
    return {
        "title": title[:200],
        "description": fields.get("DESCRIPTION"),
        "location": fields.get("LOCATION", "")[:500] or None,
        "calendar_event_uid": fields.get("UID", "")[:255] or None,
        "calendar_provider": "ics",
        "occurred_at": occurred_at,
    }
