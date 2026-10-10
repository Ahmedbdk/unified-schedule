from dataclasses import replace
import unittest

from unified_schedule.google_colors import ade_category, event_color
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

    def test_workforce_keeps_calendar_color(self):
        event = replace(example(), source="workforce")
        self.assertIsNone(event_color(event))
        self.assertNotIn("colorId", event_payload(event))
