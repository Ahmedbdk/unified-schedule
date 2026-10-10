"""Choose a calendar for each integration without silently mixing configurations."""

from unified_schedule.integrations.google_calendar import GoogleCalendarError
from unified_schedule.google_colors import ade_category

CATEGORY_VARIABLES = {"ai": "GOOGLE_ADE_IA_CALENDAR_ID", "data": "GOOGLE_ADE_DATA_CALENDAR_ID",
                      "common": "GOOGLE_ADE_COMMON_CALENDAR_ID", "english": "GOOGLE_ADE_ENGLISH_CALENDAR_ID",
                      "exam": "GOOGLE_ADE_EXAMS_CALENDAR_ID", "holiday": "GOOGLE_ADE_HOLIDAYS_CALENDAR_ID"}


def event_destination(event, targets):
    key = "ade:" + ade_category(event) if event.source == "ade" and "ade:ai" in targets else event.source
    return targets[key]


def calendar_targets(environment):
    ade = environment.get("GOOGLE_ADE_CALENDAR_ID", "").strip()
    workforce = environment.get("GOOGLE_WORKFORCE_CALENDAR_ID", "").strip()
    categories = {"ade:" + category: environment.get(variable, "").strip() for category, variable in CATEGORY_VARIABLES.items()}
    if any(categories.values()):
        values = [*categories.values(), workforce]
        if not all(values) or len(set(values)) != 7:
            raise GoogleCalendarError("Configure all six distinct ADE category calendars and the Workforce calendar.")
        return {**categories, "workforce": workforce}
    if ade or workforce:
        if not ade or not workforce or ade == workforce:
            raise GoogleCalendarError("Configure two distinct GOOGLE_ADE_CALENDAR_ID and GOOGLE_WORKFORCE_CALENDAR_ID values.")
        return {"ade": ade, "workforce": workforce}
    calendar = environment.get("GOOGLE_CALENDAR_ID", "").strip()
    return {"ade": calendar, "workforce": calendar}
