"""Apply a freshly fetched synchronization plan to the selected calendar."""

from collections import Counter
import json
import random
import time

from googleapiclient.errors import HttpError

from unified_schedule.integrations.google_calendar import GoogleCalendarError


def recover_existing(service, calendar_id, payload):
    from unified_schedule.google_preview import _canonical_time, _same_event
    from unified_schedule.integrations.google_calendar import APP_PROPERTY, APP_NAME, KEY_PROPERTY
    existing = service.events().get(calendarId=calendar_id, eventId=payload["id"]).execute()
    if existing.get("status") == "cancelled":
        raise GoogleCalendarError("Existing ID is cancelled or moved. Verify GOOGLE_ADE_CALENDAR_ID and GOOGLE_WORKFORCE_CALENDAR_ID; do not use the original calendar after migration.")
    expected = payload["extendedProperties"]["private"]
    properties = existing.get("extendedProperties", {}).get("private", {})
    tagged = properties.get(APP_PROPERTY) == APP_NAME and properties.get(KEY_PROPERTY) == expected[KEY_PROPERTY]
    same_content = existing.get("summary") == payload["summary"] and all(
        _canonical_time(existing.get(field, {})) == _canonical_time(payload[field]) for field in ("start", "end")
    )
    if existing.get("id") != payload["id"] or existing.get("recurrence") or existing.get("eventType", "default") != "default" or not (tagged or same_content):
        raise GoogleCalendarError("Existing ID cannot be safely matched. No duplicate was created.")
    if tagged and _same_event(existing, payload):
        return "unchanged"
    body = {key: value for key, value in payload.items() if key != "id"}
    execute_write(service.events().patch(calendarId=calendar_id, eventId=payload["id"], body=body))
    return "update"


def error_reason(error):
    """Return only a known error code, never the potentially private response."""
    known = {"rateLimitExceeded", "userRateLimitExceeded", "quotaExceeded",
             "forbidden", "forbiddenForNonOrganizer", "insufficientPermissions",
             "accessNotConfigured", "dailyLimitExceeded", "duplicate", "backendError"}
    try:
        entries = json.loads(error.content).get("error", {}).get("errors", [])
        return next((entry.get("reason") for entry in entries if entry.get("reason") in known), "unknown")
    except (ValueError, TypeError, AttributeError):
        return "unknown"


def execute_write(request):
    for attempt in range(6):
        try:
            return request.execute()
        except HttpError as error:
            retryable = error.resp.status in {429, 500, 502, 503, 504} or (
                error.resp.status == 403 and error_reason(error) in {"rateLimitExceeded", "userRateLimitExceeded"})
            if not retryable or attempt == 5:
                raise
            delay = 2 ** attempt + random.random()
            print(f"Google temporarily limited the request; retrying in {delay:.1f}s...", flush=True)
            time.sleep(delay)


def apply_plan(service, calendar_id: str, plan: dict) -> dict:
    if not plan.get("remote_checked"):
        raise GoogleCalendarError("Cannot synchronize an offline plan.")
    counts = Counter()
    for item in plan["items"]:
        action = item["action"]
        if action == "create":
            # Hex hashes satisfy Google's base32hex ID constraints. A retry after
            # an interrupted response cannot create a second event with this ID.
            payload = {**item["payload"]}
            key = payload["extendedProperties"]["private"]["unified_schedule_key"]
            payload["id"] = "us" + key
            try:
                execute_write(service.events().insert(calendarId=calendar_id, body=payload))
            except HttpError as error:
                if error.resp.status != 409 or error_reason(error) != "duplicate":
                    raise
                action = recover_existing(service, calendar_id, payload)
        elif action in {"update", "cancel"}:
            payload = item["payload"] if action == "update" else {"status": "cancelled"}
            execute_write(service.events().patch(calendarId=calendar_id, eventId=item["google_event_id"], body=payload))
        elif action not in {"unchanged", "skip"}:
            raise GoogleCalendarError("Unknown synchronization action.")
        counts[action] += 1
        if action in {"create", "update", "cancel"}:
            print(f"{action}: {item['title']}", flush=True)
            time.sleep(0.5)
    return dict(counts)
