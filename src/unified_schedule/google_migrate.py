"""Preview or move this application's existing events to source calendars."""

import argparse
import os
from pathlib import Path

from dotenv import load_dotenv
from googleapiclient.errors import HttpError

from unified_schedule.google_preview import event_key, event_payload, _canonical_time
from unified_schedule.google_routing import calendar_targets
from unified_schedule.google_sync import execute_write, error_reason
from unified_schedule.integrations.google_calendar import (
    KEY_PROPERTY, GoogleCalendarError, WRITE_SCOPES, WRITE_TOKEN_PATH,
    calendar_service, get_credentials, list_calendars, list_managed_events,
)
from unified_schedule.storage import list_events


def repair_plan(events, rows):
    expected = {"us" + event_key(event): event for event in events}
    repairs = []
    for row in rows:
        event = expected.get(row.get("id"))
        if event is None:
            continue
        if row.get("extendedProperties", {}).get("private", {}).get(KEY_PROPERTY) == event_key(event):
            continue
        payload = event_payload(event)
        if row.get("summary") != event.title or any(
            _canonical_time(row.get(field, {})) != _canonical_time(payload[field]) for field in ("start", "end")
        ):
            raise GoogleCalendarError("A destination event cannot be safely recognized for marker restoration.")
        body = {"extendedProperties": payload["extendedProperties"]}
        if "colorId" in payload:
            body["colorId"] = payload["colorId"]
        repairs.append((row["id"], body))
    return repairs


def destination_events(service, calendar):
    rows, page = [], None
    while True:
        response = service.events().list(calendarId=calendar, maxResults=2500, showDeleted=False, pageToken=page).execute()
        rows.extend(response.get("items", []))
        page = response.get("nextPageToken")
        if not page:
            return rows


def migration_plan(events, remote, destinations, existing):
    identities = {event_key(event): event.source for event in events}
    moves = []
    seen = set()
    for item in remote:
        key = item.get("extendedProperties", {}).get("private", {}).get(KEY_PROPERTY)
        if key not in identities:
            raise GoogleCalendarError("A managed event cannot be matched to the local database. No moves applied.")
        if key in seen:
            raise GoogleCalendarError("Duplicate managed identity in the original calendar.")
        seen.add(key)
        destination = destinations[identities[key]]
        if any(entry.get("extendedProperties", {}).get("private", {}).get(KEY_PROPERTY) == key for entry in existing[destination]):
            raise GoogleCalendarError("An event already exists in both calendars. Resolve the duplicate before migration.")
        if item.get("eventType", "default") != "default" or item.get("recurrence"):
            raise GoogleCalendarError("Unsupported managed event type for migration.")
        moves.append((item, destination))
    return moves


def main():
    parser = argparse.ArgumentParser(description="Déplacer les événements gérés vers EILCO et Domino's.")
    parser.add_argument("--apply", action="store_true", help="Effectuer les déplacements (sinon prévisualisation).")
    args = parser.parse_args()
    load_dotenv(Path.cwd() / ".env")
    try:
        targets = calendar_targets(os.environ)
        origin = os.getenv("GOOGLE_CALENDAR_ID", "").strip()
        if not origin or len(set(targets.values())) != 2 or origin in targets.values():
            raise GoogleCalendarError("Keep GOOGLE_CALENDAR_ID as the original calendar and configure two distinct destination calendars.")
        service = calendar_service(get_credentials(scopes=WRITE_SCOPES, token_path=WRITE_TOKEN_PATH))
        calendars = {item["id"]: item for item in list_calendars(service)}
        if any(calendars.get(key, {}).get("accessRole") != "owner" for key in [origin, *targets.values()]):
            raise GoogleCalendarError("You must own the original calendar and both destinations.")
        events = list_events(Path(os.getenv("DATABASE_PATH", "data/unified_schedule.sqlite3")))
        remote = list_managed_events(service, origin)
        existing = {key: destination_events(service, key) for key in targets.values()}
        repairs = [(calendar, event_id, body) for source, calendar in targets.items()
                   for event_id, body in repair_plan([event for event in events if event.source == source], existing[calendar])]
        moves = migration_plan(events, remote, targets, existing)
        print(f"{len(moves)} événements à déplacer (aucun événement personnel concerné).")
        print(f"{len(repairs)} marqueurs de migration à rétablir.")
        if not args.apply:
            print("Prévisualisation uniquement. Utilisez --apply pour déplacer.")
            return 0
        for calendar, event_id, body in repairs:
            execute_write(service.events().patch(calendarId=calendar, eventId=event_id, body=body))
            print("Marqueur de migration rétabli.", flush=True)
        for item, destination in moves:
            moved = execute_write(service.events().move(calendarId=origin, eventId=item["id"], destination=destination))
            execute_write(service.events().patch(calendarId=destination, eventId=moved["id"],
                                                body={"extendedProperties": item["extendedProperties"]}))
            print(f"Déplacé vers {calendars[destination].get('summary', destination)}", flush=True)
        print("Migration terminée. Relancez sync pour vérifier les agendas cibles.")
        return 0
    except HttpError as error:
        print(f"Google HTTP {error.resp.status} ({error_reason(error)}). Migration potentiellement partielle ; relancez pour reprendre.")
    except (GoogleCalendarError, OSError) as error:
        print(f"Erreur : {error}")
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
