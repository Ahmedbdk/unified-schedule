"""Keep Workforce browser authentication locally in the ignored .auth folder."""

from contextlib import contextmanager
import json
import os
from pathlib import Path
from tempfile import NamedTemporaryFile
from urllib.parse import urlsplit

from unified_schedule.integrations.workforce import (
    BASE_URL, WorkforceError, WorkforceSessionExpired, fetch_week, personal_week,
)


SESSION_PATH = Path("playwright/.auth/workforce.json")


def _load_state(path: Path) -> dict | None:
    if not path.exists():
        return None
    try:
        state = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(state, dict) or not isinstance(state.get("cookies"), list) or not isinstance(state.get("origins"), list):
            raise ValueError("Invalid storage state")
        return state
    except (ValueError, UnicodeError):
        print("Saved Workforce session is invalid; a fresh login is needed.")
        return None


def _save_state(context, path: Path) -> None:
    """Replace state atomically; never print its cookies or other contents."""
    state = context.storage_state(indexed_db=True)
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = None
    try:
        with NamedTemporaryFile(mode="w", encoding="utf-8", dir=path.parent,
                                prefix="workforce-", suffix=".tmp", delete=False) as stream:
            temporary = Path(stream.name)
            os.chmod(temporary, 0o600)
            json.dump(state, stream)
        temporary.replace(path)
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)


@contextmanager
def schedule_session(playwright, zone_name, week_start, *, force_login=False,
                     non_interactive=False, session_path=SESSION_PATH):
    """Yield an authenticated context and its already-fetched first week.

    Reuse runs headlessly. Interactive fresh login keeps the browser visible
    so verification can be completed in the same session;
    parsing errors and access-denied responses propagate without a login loop.
    """
    state = None if force_login else _load_state(session_path)
    if state is not None:
        browser = playwright.chromium.launch(headless=True)
        try:
            context = browser.new_context(timezone_id=zone_name, storage_state=state)
            try:
                first_week = fetch_week(context, week_start, zone_name)
            except WorkforceSessionExpired:
                print("Saved Workforce session has expired; a fresh login is needed.")
            else:
                print("Reusing saved Workforce session.")
                yield context, first_week
                _save_state(context, session_path)
                return
        finally:
            browser.close()
    email = os.getenv("WORKFORCE_EMAIL", "").strip()
    password = os.getenv("WORKFORCE_PASSWORD", "")
    if bool(email) != bool(password):
        raise WorkforceError("Set both WORKFORCE_EMAIL and WORKFORCE_PASSWORD, or leave both blank.")
    if email and password:
        from playwright.sync_api import TimeoutError as LoginTimeout
        print("Attempting automatic Workforce login.")
        browser = playwright.chromium.launch(headless=non_interactive)
        try:
            context = browser.new_context(timezone_id=zone_name)
            page = context.new_page()
            page.goto(BASE_URL + "/mobile_app/login", wait_until="domcontentloaded")
            login_url = urlsplit(page.url)
            if login_url.scheme != "https" or login_url.netloc != "eu.workforce.com":
                raise WorkforceError("Unexpected login host; credentials were not submitted.")
            try:
                page.get_by_placeholder("Email", exact=True).fill(email)
                password_input = page.get_by_placeholder("Password", exact=True)
                password_input.fill(password)
                password_input.press("Enter")
                page.wait_for_url(
                    lambda url: urlsplit(url).netloc == "eu.workforce.com"
                    and urlsplit(url).path not in {"/login", "/mobile_app/login"},
                    wait_until="domcontentloaded", timeout=30_000,
                )
                first_week = fetch_week(context, week_start, zone_name)
            except (LoginTimeout, WorkforceSessionExpired):
                if non_interactive:
                    raise WorkforceSessionExpired(
                        "Login needs verification or corrected credentials. Run without --non-interactive to complete it."
                    ) from None
                print("Complete the email code, SSO, or other login step in this browser, then open Liste and select Mine.")
                input("When your own schedule is visible, press Enter here: ")
                if urlsplit(page.url).netloc != "eu.workforce.com":
                    raise WorkforceError("The browser is not on EU Workforce.")
                frame = page.locator("turbo-frame#schedules")
                frame.wait_for(state="attached", timeout=30_000)
                personal_week(frame.get_attribute("src") or "")
                first_week = fetch_week(context, week_start, zone_name)
            _save_state(context, session_path)
            print("Workforce login verified; session saved locally.")
            yield context, first_week
            _save_state(context, session_path)
            return
        finally:
            browser.close()
    if non_interactive:
        raise WorkforceSessionExpired("No usable session. Configure automatic login or run without --non-interactive to log in manually.")
    browser = playwright.chromium.launch(headless=False)
    try:
        context = browser.new_context(timezone_id=zone_name)
        page = context.new_page()
        page.goto(BASE_URL + "/mobile_app/login", wait_until="domcontentloaded")
        print("Log in in the browser, open Liste, and select Mine.")
        print("Your verified session will be saved locally for reuse.")
        input("When your own schedule is visible, press Enter here: ")
        if urlsplit(page.url).netloc != "eu.workforce.com":
            raise WorkforceError("The browser is not on EU Workforce.")
        frame = page.locator("turbo-frame#schedules")
        frame.wait_for(state="attached", timeout=30_000)
        personal_week(frame.get_attribute("src") or "")
        first_week = fetch_week(context, week_start, zone_name)
        # Save once login is verified, even if a later week has a layout error.
        _save_state(context, session_path)
        print(f"Saved Workforce session to {session_path} (excluded from Git).")
        yield context, first_week
        _save_state(context, session_path)
    finally:
        browser.close()
