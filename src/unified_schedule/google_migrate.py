"""Preview or move this application's existing events to source calendars."""

import argparse
import os
from pathlib import Path

from dotenv import load_dotenv
from googleapiclient.errors import HttpError

from unified_schedule.google_preview import event_key
from unified_schedule.google_routing import calendar_targets
from unified_schedule.google_sync import execute_write, error_reason
from unified_schedule.integrations.google_calendar import (
    KEY_PROPERTY, GoogleCalendarError, WRITE_SCOPES, WRITE_TOKEN_PATH,
    calendar_service, get_credentials, list_calendars, list_managed_events,
)
from unified_schedule.storage import list_events


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
        existing = {key: list_managed_events(service, key) for key in targets.values()}
        moves = migration_plan(events, remote, targets, existing)
        print(f"{len(moves)} événements à déplacer (aucun événement personnel concerné).")
        if not args.apply:
            print("Prévisualisation uniquement. Utilisez --apply pour déplacer.")
            return 0
        for item, destination in moves:
            execute_write(service.events().move(calendarId=origin, eventId=item["id"], destination=destination))
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
