from dataclasses import replace
from datetime import datetime
import unittest

from unified_schedule.google_colors import ade_category, event_color, workforce_category
from unified_schedule.google_preview import event_payload, build_preview
from test_google_calendar import example


class ColorTests(unittest.TestCase):
    def test_categories_and_precedence(self):
        samples = {"CM PARCOURS 1 - DEEP LEARNING": "ai",
                   "000TP PARCOURS 2 - DATA SCIENCE AVANCEE": "data",
                   "000LV1 SOUTIEN ANGLAIS": "english",
                   "TD1 FISE - API ET SERVICES CLOUD": "common",
                   "EXAMEN S9 - DEEP LEARNING": "exam",
                   "SOUTENANCE AI FISE": "exam",
                   "Interruption pédagogique de Noël": "holiday", "FÉRIÉ": "holiday"}
        for title, category in samples.items():
            with self.subTest(title=title):
                self.assertEqual(ade_category(replace(example(), title=title)), category)

    def test_description_ambiguity_and_common_group(self):
        event = replace(example(), description="ING3 - PARCOURS IA")
        self.assertEqual(ade_category(event), "ai")
        self.assertEqual(ade_category(replace(event, description="PARCOURS IA et PARCOURS DATA SCIENCE")), "common")
        self.assertEqual(ade_category(replace(event, title="TD1 FISE - CLOUD")), "common")

    def test_existing_events_update_color_once_without_identity_changes(self):
        event = example()
        old = {**event_payload(event), "id": "existing"}
        old.pop("colorId")
        plan = build_preview([event], [old], remote_checked=True)
        self.assertEqual(plan["counts"], {"update": 1})
        self.assertEqual(plan["items"][0]["google_event_id"], "existing")
        old["colorId"] = event_color(event)
        self.assertEqual(build_preview([event], [old], remote_checked=True)["counts"], {"unchanged": 1})

    def test_workforce_normal_has_its_own_color(self):
        event = replace(example(), source="workforce")
        self.assertEqual(event_color(event), "7")
        self.assertEqual(event_payload(event)["colorId"], "7")

    def test_workforce_local_hours_boundaries_and_precedence(self):
        cases = [("18:00", "23:00", "close"), ("18:00", "23:30", "close"),
                 ("18:00", "22:59", "normal"), ("18:00", "23:31", "normal"),
                 ("18:00", "22:00", "preclose"), ("18:00", "22:30", "preclose"),
                 ("18:00", "22:31", "normal"), ("11:00", "14:00", "lunch"),
                 ("10:00", "11:00", "normal"), ("14:00", "16:00", "normal"),
                 ("10:00", "12:00", "lunch"), ("12:00", "23:00", "close")]
        for day, offset in (("2026-10-12", "+02:00"), ("2026-12-12", "+01:00")):
            for start, end, category in cases:
                with self.subTest(day=day, start=start, end=end):
                    event = replace(example(), source="workforce", start=datetime.fromisoformat(f"{day}T{start}:00{offset}"),
                                    end=datetime.fromisoformat(f"{day}T{end}:00{offset}"))
                    self.assertEqual(workforce_category(event), category)

    def test_workforce_reclassification_updates_existing_color(self):
        event = replace(example(), source="workforce")
        old = {**event_payload(event), "id": "existing", "colorId": "11"}
        self.assertEqual(build_preview([event], [old], remote_checked=True)["counts"], {"update": 1})
