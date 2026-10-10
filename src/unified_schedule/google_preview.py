"""Build an event synchronization plan without applying any changes."""

from collections import Counter
from datetime import datetime, timezone
from hashlib import sha256
import re

from unified_schedule.events import Event
from unified_schedule.google_colors import event_color
from unified_schedule.integrations.google_calendar import (
    APP_NAME, APP_PROPERTY, KEY_PROPERTY, GoogleCalendarError,
)


def event_key(event: Event) -> str:
    return sha256(f"{event.source}\0{event.source_id}".encode()).hexdigest()


def event_payload(event: Event) -> dict:
    description = event.description
    if event.source == "ade":
        description = re.sub(
            r"(?:\r?\n)?\(Exporté le:\d{2}/\d{2}/\d{4} \d{2}:\d{2}\)\s*\Z", "", description,
        )
    date_key = "date" if event.all_day else "dateTime"
    payload = {
        "summary": event.title, "location": event.location, "description": description,
        "start": {date_key: event.start.isoformat()}, "end": {date_key: event.end.isoformat()},
        "status": "tentative" if event.status.upper() == "TENTATIVE" else "confirmed",
        "extendedProperties": {"private": {APP_PROPERTY: APP_NAME, KEY_PROPERTY: event_key(event)}},
    }
    color = event_color(event)
    if color is not None:
        payload["colorId"] = color
    return payload


def _canonical_time(value: dict) -> tuple[str, str]:
    if "date" in value:
        return "date", value["date"]
    try:
        instant = datetime.fromisoformat(value["dateTime"])
        if instant.utcoffset() is None:
            raise ValueError("Missing timezone offset")
        return "dateTime", instant.astimezone(timezone.utc).isoformat()
    except (ValueError, TypeError, KeyError):
        raise GoogleCalendarError("A managed Google event has an invalid timestamp.") from None


def _same_event(remote: dict, payload: dict) -> bool:
    return (
        all(remote.get(key, "") == payload[key] for key in ("summary", "description", "location"))
        and remote.get("status", "confirmed") == payload["status"]
        and ("colorId" not in payload or str(remote.get("colorId", "")) == payload["colorId"])
        and _canonical_time(remote.get("start", {})) == _canonical_time(payload["start"])
        and _canonical_time(remote.get("end", {})) == _canonical_time(payload["end"])
    )


def build_preview(events: list[Event], remote_events: list[dict], *, remote_checked: bool) -> dict:
    managed = {}
    for remote in remote_events:
        properties = remote.get("extendedProperties", {}).get("private", {})
        if properties.get(APP_PROPERTY) != APP_NAME:
            continue
        key = properties.get(KEY_PROPERTY)
        if not key or not remote.get("id") or key in managed or remote.get("recurrence"):
            raise GoogleCalendarError("Managed Google events have missing/duplicate identities or unsupported recurrence.")
        managed[key] = remote
    items = []
    for event in events:
        remote = managed.get(event_key(event))
        item = {"uid": f"{event.source}:{event.source_id}", "title": event.title,
                "google_event_id": remote.get("id") if remote else None}
        if event.status.strip().upper() == "CANCELLED":
            item.update(action="cancel" if remote and remote.get("status") != "cancelled" else "skip",
                        reason="source_cancelled")
        elif not event.all_day and event.start == event.end:
            item.update(action="skip", reason="zero_duration_not_supported_by_google")
        else:
            payload = event_payload(event)
            action = "create" if remote is None else "unchanged" if _same_event(remote, payload) else "update"
            item.update(action=action, payload=payload)
        items.append(item)
    return {
        "read_only": True, "remote_checked": remote_checked,
        "counts": dict(Counter(item["action"] for item in items)), "items": items,
        "note": "Preview only. No Google events were changed. Missing local events do not imply remote deletion.",
    }
