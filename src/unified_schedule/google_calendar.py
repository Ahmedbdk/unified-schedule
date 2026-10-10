"""Authorize Google, preview changes, and synchronize managed events."""

import argparse
from collections import Counter
from datetime import date, datetime, timedelta
import json
import os
from pathlib import Path
import sqlite3
import sys
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from dotenv import load_dotenv
from google.auth.exceptions import GoogleAuthError
from google_auth_oauthlib.flow import WSGITimeoutError
from googleapiclient.errors import HttpError
from oauthlib.oauth2 import OAuth2Error
from requests.exceptions import RequestException

from unified_schedule.events import EventError
from unified_schedule.google_preview import build_preview
from unified_schedule.google_routing import calendar_targets
from unified_schedule.google_sync import apply_plan, error_reason
from unified_schedule.integrations.google_calendar import (
    GoogleCalendarError, calendar_service, get_credentials, list_calendars, list_managed_events,
    WRITE_SCOPES, WRITE_TOKEN_PATH,
)
from unified_schedule.storage import list_events


def main() -> int:
    parser = argparse.ArgumentParser(description="Google Calendar authorization, preview, and synchronization.")
    commands = parser.add_subparsers(dest="command", required=True)
    auth = commands.add_parser("authorize", help="Authorize read-only access in your browser.")
    auth.add_argument("--login", action="store_true", help="Replace an existing token with fresh read-only authorization.")
    auth.add_argument("--write", action="store_true", help="Authorize event creation and updates for synchronization.")
    commands.add_parser("calendars", help="List calendar IDs and access roles.")
    preview = commands.add_parser("preview", help="Save a proposed synchronization plan; no events are written.")
    preview.add_argument("--offline", action="store_true", help="Build a hypothetical plan against an empty calendar; no Google access.")
    preview.add_argument("--from", dest="start", type=date.fromisoformat, help="First local date (default: today).")
    preview.add_argument("--to", dest="end", type=date.fromisoformat, help="Exclusive last date (default: 90 days after --from).")
    preview.add_argument("--output", type=Path, default=Path("data/google-preview.json"))
    sync = commands.add_parser("sync", help="Create/update managed events in the configured Google calendar.")
    sync.add_argument("--from", dest="start", type=date.fromisoformat)
    sync.add_argument("--to", dest="end", type=date.fromisoformat)
    sync.set_defaults(offline=False, output=Path("data/google-sync.json"))
    args = parser.parse_args()
    if args.command == "preview" and args.output.suffix.lower() != ".json":
        parser.error("--output must have a .json extension")
    load_dotenv(Path.cwd() / ".env", override=False)
    try:
        if args.command == "authorize":
            options = {"scopes": WRITE_SCOPES, "token_path": WRITE_TOKEN_PATH} if args.write else {}
            get_credentials(authorize=True, force=args.login, **options)
            print("Google Calendar authorization saved locally (write access)." if args.write else "Read-only Google Calendar authorization saved locally.")
        elif args.command == "calendars":
            service = calendar_service(get_credentials())
            for calendar in list_calendars(service):
                print(f"{calendar.get('summary', '')} | {calendar['id']} | {calendar.get('accessRole', '')}")
        else:
            timezone_name = os.getenv("APP_TIMEZONE", "Europe/Paris")
            start = args.start or datetime.now(ZoneInfo(timezone_name)).date()
            end = args.end or start + timedelta(days=90)
            database = Path(os.getenv("DATABASE_PATH", "data/unified_schedule.sqlite3"))
            events = list_events(database, start_date=start, end_date=end, timezone_name=timezone_name)
            targets = calendar_targets(os.environ)
            calendar_ids = list(dict.fromkeys(targets.values()))
            batches = []
            if not args.offline:
                if not all(calendar_ids):
                    raise GoogleCalendarError("Set GOOGLE_CALENDAR_ID in .env after running the calendars command.")
                options = {"scopes": WRITE_SCOPES, "token_path": WRITE_TOKEN_PATH} if args.command == "sync" else {}
                service = calendar_service(get_credentials(**options))
                calendars = {calendar["id"]: calendar for calendar in list_calendars(service)}
                if any(calendar_id not in calendars for calendar_id in calendar_ids):
                    raise GoogleCalendarError("Configured calendar ID is not in your accessible calendar list.")
                if any(calendars[calendar_id].get("accessRole") not in {"owner", "writer"} for calendar_id in calendar_ids):
                    raise GoogleCalendarError("Choose a calendar where your account has owner or writer access for future synchronization.")
            # Build every plan before the first write, validating both calendars.
            for calendar_id in calendar_ids:
                selected = [event for event in events if targets[event.source] == calendar_id]
                remote = [] if args.offline else list_managed_events(service, calendar_id)
                plan = build_preview(selected, remote, remote_checked=not args.offline)
                plan["calendar_id"] = calendar_id or None
                batches.append(plan)
            counts = Counter()
            for plan in batches:
                counts.update(plan["counts"])
            result = {"read_only": True, "remote_checked": not args.offline,
                      "counts": dict(counts), "items": [dict(item, calendar_id=plan["calendar_id"]) for plan in batches for item in plan["items"]],
                      "calendars": batches}
            result.update(from_date=start.isoformat(),
                          to_date_exclusive=end.isoformat(), display_timezone=timezone_name)
            if args.command == "sync":
                print(f"Synchronizing {len(events)} local events: {result['counts']}", flush=True)
                applied = Counter()
                for plan in batches:
                    applied.update(apply_plan(service, plan["calendar_id"], plan))
                result["applied_counts"] = dict(applied)
                result["read_only"] = False
                result["note"] = "Synchronization completed. Missing local events do not imply remote deletion."
            args.output.parent.mkdir(parents=True, exist_ok=True)
            args.output.write_text(json.dumps(result, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
            if args.command == "sync":
                print(f"Synchronization complete: {result['applied_counts']}")
            else:
                print(f"{'Offline hypothetical' if args.offline else 'Google read-only'} preview for {len(events)} local events: {result['counts']}")
            print(f"Saved synchronization report to {args.output}." if args.command == "sync" else f"Saved plan to {args.output}. No Google events were changed.")
            if args.offline:
                print("Remote calendar was not checked; create actions assume an empty target.")
        return 0
    except (GoogleCalendarError, EventError) as error:
        print(f"Error: {error}", file=sys.stderr)
    except HttpError as error:
        reason = error_reason(error)
        print(f"Error: Google Calendar API returned HTTP {error.resp.status} ({reason}).", file=sys.stderr)
        if reason in {"rateLimitExceeded", "userRateLimitExceeded", "quotaExceeded", "dailyLimitExceeded"}:
            print("Google quota reached. Wait before retrying sync; previously created events will be recognized.", file=sys.stderr)
        else:
            print("Check Google permissions/API configuration. Some events may already be synchronized.", file=sys.stderr)
    except WSGITimeoutError:
        print("Error: browser authorization timed out; run authorize again and complete the Google prompt.", file=sys.stderr)
    except (GoogleAuthError, RequestException, OAuth2Error):
        print("Error: Google authorization or token refresh failed; retry authorize --login.", file=sys.stderr)
    except ZoneInfoNotFoundError:
        print("Error: APP_TIMEZONE is not a recognized IANA timezone.", file=sys.stderr)
    except (OSError, sqlite3.Error):
        print("Error: unable to access local files/database or connect to Google.", file=sys.stderr)
    except (KeyboardInterrupt, EOFError):
        print("Google authorization cancelled.", file=sys.stderr)
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
