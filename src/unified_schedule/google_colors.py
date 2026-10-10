"""Simple ADE category rules and Google event palette identifiers."""

import re
import unicodedata


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


def event_color(event):
    return COLORS[ade_category(event)] if event.source == "ade" else None
