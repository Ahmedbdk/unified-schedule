"""Choose a calendar for each integration without silently mixing configurations."""

from unified_schedule.integrations.google_calendar import GoogleCalendarError


def calendar_targets(environment):
    ade = environment.get("GOOGLE_ADE_CALENDAR_ID", "").strip()
    workforce = environment.get("GOOGLE_WORKFORCE_CALENDAR_ID", "").strip()
    if ade or workforce:
        if not ade or not workforce or ade == workforce:
            raise GoogleCalendarError("Configure two distinct GOOGLE_ADE_CALENDAR_ID and GOOGLE_WORKFORCE_CALENDAR_ID values.")
        return {"ade": ade, "workforce": workforce}
    calendar = environment.get("GOOGLE_CALENDAR_ID", "").strip()
    return {"ade": calendar, "workforce": calendar}
