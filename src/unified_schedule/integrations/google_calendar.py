"""Read-only Google Calendar access using desktop OAuth authorization."""

import json
import os
from pathlib import Path
from tempfile import NamedTemporaryFile

from google.auth.exceptions import RefreshError
from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import build


SCOPES = [
    "https://www.googleapis.com/auth/calendar.events.readonly",
    "https://www.googleapis.com/auth/calendar.calendarlist.readonly",
]
WRITE_SCOPES = ["https://www.googleapis.com/auth/calendar.events", SCOPES[1]]
WRITE_TOKEN_PATH = Path("secrets/google-write-token.json")
CLIENT_PATH = Path("secrets/google-client.json")
TOKEN_PATH = Path("secrets/google-token.json")
APP_PROPERTY = "unified_schedule_app"
KEY_PROPERTY = "unified_schedule_key"
APP_NAME = "unified-schedule"


class GoogleCalendarError(ValueError):
    """Google authorization or preview cannot safely proceed."""


def _save_token(credentials, path: Path):
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = None
    try:
        with NamedTemporaryFile(mode="w", encoding="utf-8", dir=path.parent,
                                prefix="google-token-", suffix=".tmp", delete=False) as stream:
            temporary = Path(stream.name)
            os.chmod(temporary, 0o600)
            stream.write(credentials.to_json())
        temporary.replace(path)
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)


def get_credentials(*, authorize=False, force=False,
                    client_path=CLIENT_PATH, token_path=TOKEN_PATH, scopes=None):
    scopes = SCOPES if scopes is None else scopes
    credentials = None
    if token_path.is_file() and not force:
        try:
            data = json.loads(token_path.read_text(encoding="utf-8"))
            if set(data.get("scopes", [])) != set(scopes):
                raise GoogleCalendarError("Saved Google permissions differ. Run authorize --login for read-only access.")
            credentials = Credentials.from_authorized_user_info(data)
        except (ValueError, TypeError, AttributeError):
            raise GoogleCalendarError("Invalid Google token file. Run authorize --login to replace it.") from None
        if credentials.expired and credentials.refresh_token:
            try:
                credentials.refresh(Request())
                _save_token(credentials, token_path)
            except RefreshError:
                credentials = None
    if credentials and credentials.valid:
        return credentials
    if not authorize:
        raise GoogleCalendarError("Google authorization is required. Run: python -m unified_schedule.google_calendar authorize")
    if not client_path.is_file():
        raise GoogleCalendarError("Download a Desktop app OAuth client JSON to secrets/google-client.json; see README.")
    try:
        client = json.loads(client_path.read_text(encoding="utf-8"))
        if not isinstance(client.get("installed"), dict):
            raise GoogleCalendarError("Google OAuth credentials must use the Desktop app client type.")
        flow = InstalledAppFlow.from_client_config(client, scopes)
    except (ValueError, TypeError, AttributeError):
        raise GoogleCalendarError("Invalid Desktop app OAuth client file.") from None
    credentials = flow.run_local_server(
        port=0, authorization_prompt_message="Authorize Google Calendar access in the browser.",
        success_message="Authorization complete. You can close this window.", timeout_seconds=180,
    )
    _save_token(credentials, token_path)
    return credentials


def calendar_service(credentials):
    return build("calendar", "v3", credentials=credentials, cache_discovery=False)


def list_calendars(service) -> list[dict]:
    result, page_token = [], None
    while True:
        response = service.calendarList().list(pageToken=page_token).execute()
        result.extend(response.get("items", []))
        page_token = response.get("nextPageToken")
        if not page_token:
            return result


def list_managed_events(service, calendar_id: str) -> list[dict]:
    """Read only this app's tagged events; follow every page, including moved events."""
    result, page_token = [], None
    while True:
        response = service.events().list(
            calendarId=calendar_id, privateExtendedProperty=[f"{APP_PROPERTY}={APP_NAME}"],
            showDeleted=False, singleEvents=False, maxResults=2500, pageToken=page_token,
        ).execute()
        result.extend(response.get("items", []))
        page_token = response.get("nextPageToken")
        if not page_token:
            return result
