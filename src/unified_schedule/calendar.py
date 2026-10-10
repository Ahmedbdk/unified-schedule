"""Import snapshots or inspect the unified SQLite calendar, without network IO."""

import argparse
from collections import Counter
from datetime import date
import json
import os
from pathlib import Path
import sqlite3
import sys
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from dotenv import load_dotenv

from unified_schedule.conflicts import find_conflicts
from unified_schedule.events import EventError, read_snapshot
from unified_schedule.storage import import_events, list_events


def main() -> int:
    parser = argparse.ArgumentParser(description="Store and inspect the unified local calendar.")
    parser.add_argument("--database", type=Path, help="Override DATABASE_PATH from .env.")
    commands = parser.add_subparsers(dest="command", required=True)
    ingest = commands.add_parser("import", help="Import both existing local integration snapshots.")
    ingest.add_argument("--ade", type=Path, default=Path("data/ade.json"))
    ingest.add_argument("--workforce", type=Path, default=Path("data/workforce.json"))
    listing = commands.add_parser("list", help="Display events in local time; optionally export JSON.")
    listing.add_argument("--source", choices=("ade", "workforce"))
    conflicts = commands.add_parser("conflicts", help="Report overlaps between ADE and Workforce events.")
    for command in (listing, conflicts):
        command.add_argument("--from", dest="start", type=date.fromisoformat)
        command.add_argument("--to", dest="end", type=date.fromisoformat, help="Exclusive end date, YYYY-MM-DD.")
        command.add_argument("--limit", type=int, default=20, help="Maximum console rows (default: 20); JSON includes all matches.")
        command.add_argument("--output", type=Path, help="Optional local JSON report destination.")
    args = parser.parse_args()
    if args.command in {"list", "conflicts"}:
        if args.limit < 1:
            parser.error("--limit must be positive")
        if args.output and args.output.suffix.lower() != ".json":
            parser.error("--output must have a .json extension")
    load_dotenv(Path.cwd() / ".env", override=False)
    try:
        database = args.database or Path(os.getenv("DATABASE_PATH", "data/unified_schedule.sqlite3"))
        timezone_name = os.getenv("APP_TIMEZONE", "Europe/Paris")
        zone = ZoneInfo(timezone_name)
        if args.command == "import":
            # Parse both sources before opening the database, so a bad snapshot
            # cannot leave one source partially imported.
            events = read_snapshot(args.ade, "ade") + read_snapshot(args.workforce, "workforce")
            counts = import_events(database, events)
            print(f"Imported {len(events)} events: {counts['created']} created, {counts['updated']} updated, {counts['unchanged']} unchanged.")
            print(f"Database: {database}")
            print("Events absent from these snapshots were retained.")
        elif args.command == "conflicts":
            events = list_events(database, start_date=args.start, end_date=args.end,
                                 timezone_name=timezone_name)
            matches = find_conflicts(events, timezone_name=timezone_name,
                                     start_date=args.start, end_date=args.end)
            print(f"{len(matches)} ADE/Workforce conflicts ({timezone_name}).")
            for conflict in matches[:args.limit]:
                start = conflict.start.astimezone(zone).isoformat()
                end = conflict.end.astimezone(zone).isoformat()
                print(f"{start} -> {end} | {conflict.duration_minutes:g} min overlap")
                print(f"  ADE: {conflict.university.title}")
                print(f"  Workforce: {conflict.work.title}")
            if len(matches) > args.limit:
                print(f"Showing {args.limit} of {len(matches)}; increase --limit or export with --output.")
            if args.output:
                args.output.parent.mkdir(parents=True, exist_ok=True)
                args.output.write_text(json.dumps({
                    "display_timezone": timezone_name, "timestamp_timezone": "UTC",
                    "from_date": args.start.isoformat() if args.start else None,
                    "to_date_exclusive": args.end.isoformat() if args.end else None,
                    "conflict_count": len(matches),
                    "conflicts": [conflict.to_dict() for conflict in matches],
                }, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
                print(f"Saved {len(matches)} conflicts to {args.output}.")
        else:
            events = list_events(database, source=args.source, start_date=args.start,
                                 end_date=args.end, timezone_name=timezone_name)
            print(f"{len(events)} events: {dict(Counter(event.source for event in events))} ({timezone_name})")
            for event in events[:args.limit]:
                start = event.start.isoformat() if event.all_day else event.start.astimezone(zone).isoformat()
                end = event.end.isoformat() if event.all_day else event.end.astimezone(zone).isoformat()
                status = f" [{event.status}]" if event.status else ""
                print(f"{start} -> {end} | {event.source} | {event.title}{status}")
            if len(events) > args.limit:
                print(f"Showing {args.limit} of {len(events)}; increase --limit or export with --output.")
            if args.output:
                args.output.parent.mkdir(parents=True, exist_ok=True)
                args.output.write_text(json.dumps({
                    "display_timezone": timezone_name, "timed_event_timezone": "UTC",
                    "event_count": len(events), "events": [event.to_dict() for event in events],
                }, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
                print(f"Saved {len(events)} events to {args.output}.")
        return 0
    except ZoneInfoNotFoundError:
        print("Error: APP_TIMEZONE is not a recognized IANA timezone.", file=sys.stderr)
    except EventError as error:
        print(f"Error: {error}", file=sys.stderr)
    except OSError:
        print("Error: unable to read snapshots or write local files. Check paths and permissions.", file=sys.stderr)
    except sqlite3.Error:
        print("Error: SQLite operation failed. Check the database file and whether it is locked.", file=sys.stderr)
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
