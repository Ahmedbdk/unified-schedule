"""Small ADE inspection command; no synchronization or database writes."""

import argparse
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import sys
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from dotenv import load_dotenv

from unified_schedule.integrations.ade import (
    ADEError, event_fingerprint, fetch_calendar, parse_calendar,
)


def main() -> int:
    parser = argparse.ArgumentParser(description="Download and inspect the ADE timetable.")
    parser.add_argument("--input", type=Path, help="Parse a saved ICS file without network access.")
    parser.add_argument("--output", type=Path, default=Path("data/ade.json"),
                        help="Local JSON destination (default: data/ade.json).")
    parser.add_argument("--check-updates", action="store_true",
                        help="Download twice and compare bytes and actual event fields.")
    args = parser.parse_args()
    if args.output.suffix.lower() != ".json":
        parser.error("--output must have a .json extension")
    if args.input and args.check_updates:
        parser.error("--check-updates requires live downloads, not --input")
    load_dotenv(Path.cwd() / ".env", override=False)
    try:
        zone_name = os.getenv("APP_TIMEZONE", "Europe/Paris")
        ZoneInfo(zone_name)
        download = None
        comparison = None
        if args.input:
            content = args.input.read_bytes()
        else:
            url = os.getenv("ADE_ICS_URL", "").strip()
            if not url:
                raise ADEError("Set ADE_ICS_URL in your local .env before downloading.")
            download = fetch_calendar(url)
            content = download.content
        events = parse_calendar(content, zone_name)
        if args.check_updates:
            second = fetch_calendar(url)
            second_events = parse_calendar(second.content, zone_name)
            comparison = {
                "bytes_changed": download.sha256 != second.sha256,
                "events_changed": event_fingerprint(events) != event_fingerprint(second_events),
                "first_headers": download.headers,
                "second_headers": second.headers,
                "first_sha256": download.sha256,
                "second_sha256": second.sha256,
                "note": "Two snapshots cannot prove future freshness; recheck after a known timetable change.",
            }
            download, content, events = second, second.content, second_events
        document = {
            "source": "ADE", "timezone": zone_name,
            "retrieved_at": datetime.now(timezone.utc).isoformat() if download else None,
            "event_count": len(events), "event_fingerprint": event_fingerprint(events),
            "headers": download.headers if download else {},
            "comparison": comparison, "events": [event.to_dict() for event in events],
        }
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(json.dumps(document, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
        if download:
            args.output.with_suffix(".ics").write_bytes(content)
        print(f"Parsed {len(events)} ADE events ({zone_name}).")
        if events:
            print(f"Start date range: {events[0].start.isoformat()} to {events[-1].start.isoformat()}")
        print(f"Saved local results to {args.output}.")
        if comparison:
            print(f"Raw bytes changed: {comparison['bytes_changed']}")
            print(f"Timetable fields changed: {comparison['events_changed']}")
            print(comparison["note"])
        return 0
    except ZoneInfoNotFoundError:
        print("Error: APP_TIMEZONE is not a recognized IANA timezone.", file=sys.stderr)
    except (ADEError, OSError) as error:
        print(f"Error: {error}", file=sys.stderr)
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
