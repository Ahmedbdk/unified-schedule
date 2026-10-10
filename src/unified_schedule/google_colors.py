"""Simple ADE category rules and Google event palette identifiers."""

import re
import unicodedata
from datetime import datetime, time, timedelta
from zoneinfo import ZoneInfo


def normalized(text):
    return "".join(character for character in unicodedata.normalize("NFKD", text.upper())
                   if not unicodedata.combining(character))


def ade_category(event):
    title = normalized(event.title)
    if re.search(r"\b(EXAMEN\w*|SOUTENANCE\w*)\b", title):
        return "exam"
    if re.search(r"\b(FERIE\w*|VACANCES|INTERRUPTION PEDAGOGIQUE)\b", title):
        return "holiday"
    if re.search(r"\b(ANGLAIS|LV1)\b", title):
        return "english"
    if re.search(r"\bPARCOURS\s*(?:1|IA)\b", title):
        return "ai"
    if re.search(r"\bPARCOURS\s*(?:2|DATA SCIENCE)\b", title):
        return "data"
    # Descriptions may contain multiple groups. Only infer a track when there
    # is one unambiguous track and the title does not name a common FISE group.
    description = normalized(event.description)
    if not re.search(r"\bFISE\w*\b", title):
        ai = bool(re.search(r"\bPARCOURS\s*(?:1|IA)\b", description))
        data = bool(re.search(r"\bPARCOURS\s*(?:2|DATA SCIENCE)\b", description))
        if ai != data:
            return "ai" if ai else "data"
    return "common"


COLORS = {"ai": "10", "data": "5", "english": "3", "common": "9",
          "exam": "11", "holiday": "8"}


WORKFORCE_COLORS = {"close": "11", "preclose": "6", "lunch": "5", "normal": "7"}


def workforce_category(event):
    if event.all_day:
        return "normal"
    zone = ZoneInfo("Europe/Paris")
    start, end = event.start.astimezone(zone), event.end.astimezone(zone)
    end_time = end.time()
    if time(23) <= end_time <= time(23, 30):
        return "close"
    if time(22) <= end_time <= time(22, 30):
        return "preclose"
    day = start.date()
    while day <= end.date():
        lunch_start = datetime.combine(day, time(11), zone)
        lunch_end = datetime.combine(day, time(14), zone)
        if start < lunch_end and end > lunch_start:
            return "lunch"
        day += timedelta(days=1)
    return "normal"


def event_color(event):
    return COLORS[ade_category(event)] if event.source == "ade" else WORKFORCE_COLORS[workforce_category(event)]
