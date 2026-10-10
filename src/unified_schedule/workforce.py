"""Interactive Workforce export: python -m unified_schedule.workforce."""

import argparse
from datetime import date, datetime, timedelta, timezone
import json
import os
from pathlib import Path
import sys
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from dotenv import load_dotenv

from unified_schedule.integrations.workforce import (
    WorkforceError, fetch_week,
)
from unified_schedule.workforce_session import schedule_session


def main() -> int:
    parser = argparse.ArgumentParser(description="Export your own EU Workforce shifts, reusing your saved login.")
    parser.add_argument("--start", type=date.fromisoformat, help="First date to include, YYYY-MM-DD (default: today).")
    parser.add_argument("--weeks", type=int, default=4,
                        help="Maximum calendar weeks to inspect, 1-12; stop at the first empty week (default: 4).")
    parser.add_argument("--output", type=Path, default=Path("data/workforce.json"))
    login_options = parser.add_mutually_exclusive_group()
    login_options.add_argument("--login", action="store_true", help="Log in again and replace the saved session.")
    login_options.add_argument("--non-interactive", action="store_true",
                               help="Reuse a session or configured credentials; never prompt for manual login.")
    args = parser.parse_args()
    if not 1 <= args.weeks <= 12:
        parser.error("--weeks must be between 1 and 12")
    if args.output.suffix.lower() != ".json":
        parser.error("--output must have a .json extension")
    load_dotenv(Path.cwd() / ".env", override=False)
    try:
        from playwright.sync_api import Error as PlaywrightError, sync_playwright
    except ImportError:
        print("Install the project dependencies, then run: python -m playwright install chromium", file=sys.stderr)
        return 1
    try:
        zone_name = os.getenv("APP_TIMEZONE", "Europe/Paris")
        zone = ZoneInfo(zone_name)
        start = args.start or datetime.now(zone).date()
        week_start = start - timedelta(days=start.weekday())
        end_exclusive = week_start + timedelta(weeks=args.weeks)
        weeks_checked = 0
        first_empty_week = None
        shifts = {}
        with sync_playwright() as playwright:
            with schedule_session(
                playwright, zone_name, week_start,
                force_login=args.login, non_interactive=args.non_interactive,
            ) as (context, first_week):
                for index in range(args.weeks):
                    monday = week_start + timedelta(weeks=index)
                    print(f"Reading personal schedule for week {monday.isoformat()}...")
                    weekly_shifts = first_week if index == 0 else fetch_week(context, monday, zone_name)
                    weeks_checked += 1
                    if not weekly_shifts:
                        first_empty_week = monday
                        print(f"No shifts for week {monday.isoformat()}; stopping and saving collected shifts.")
                        break
                    for shift in weekly_shifts:
                        if not start <= shift.start.date() < end_exclusive:
                            continue
                        if shift.schedule_id in shifts and shifts[shift.schedule_id] != shift:
                            raise WorkforceError("Conflicting records for the same schedule ID; export aborted.")
                        shifts[shift.schedule_id] = shift
        ordered = sorted(shifts.values(), key=lambda shift: (shift.start.timestamp(), shift.schedule_id))
        result = {
            "source": "Workforce", "timezone": zone_name,
            "retrieved_at": datetime.now(timezone.utc).isoformat(),
            "start_date": start.isoformat(), "end_date_exclusive": end_exclusive.isoformat(),
            "weeks_requested": args.weeks, "shift_count": len(ordered),
            "weeks_checked": weeks_checked,
            "first_empty_week": first_empty_week.isoformat() if first_empty_week else None,
            "checked_end_date_exclusive": (week_start + timedelta(weeks=weeks_checked)).isoformat(),
            "stop_reason": "empty_week" if first_empty_week else "week_limit",
            "shifts": [shift.to_dict() for shift in ordered],
        }
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(json.dumps(result, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
        print(f"Saved {len(ordered)} personal shifts to {args.output}.")
        return 0
    except ZoneInfoNotFoundError:
        print("Error: APP_TIMEZONE is not a recognized IANA timezone.", file=sys.stderr)
    except WorkforceError as error:
        print(f"Error: {error}", file=sys.stderr)
    except PlaywrightError:
        print("Error: browser or schedule request failed. Check login, connectivity, and Chromium installation.", file=sys.stderr)
        print("Install Chromium with: .\\.venv\\Scripts\\python.exe -m playwright install chromium", file=sys.stderr)
    except OSError:
        print("Error: unable to read or write local session/export files. Check permissions.", file=sys.stderr)
    except (EOFError, KeyboardInterrupt):
        print("Export cancelled; no result was written.", file=sys.stderr)
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
