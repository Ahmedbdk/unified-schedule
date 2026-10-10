import unittest

from unified_schedule.google_routing import calendar_targets
from unified_schedule.google_migrate import migration_plan, repair_plan
from unified_schedule.google_preview import event_payload, event_key
from unified_schedule.integrations.google_calendar import GoogleCalendarError
from test_google_calendar import example


class RoutingTests(unittest.TestCase):
    def test_moved_event_markers_can_be_restored_without_creating_events(self):
        event = example()
        row = {**event_payload(event), "id": "us" + event_key(event)}
        row.pop("extendedProperties")
        repairs = repair_plan([event], [row, {"id": "personal"}])
        self.assertEqual(len(repairs), 1)
        self.assertEqual(repairs[0][1]["extendedProperties"], event_payload(event)["extendedProperties"])
        self.assertIn("colorId", repairs[0][1])
        row["summary"] = "Unexpected"
        with self.assertRaises(GoogleCalendarError):
            repair_plan([event], [row])

    def test_split_and_legacy(self):
        self.assertEqual(calendar_targets({"GOOGLE_CALENDAR_ID": "old"}), {"ade": "old", "workforce": "old"})
        targets = calendar_targets({"GOOGLE_ADE_CALENDAR_ID": "school", "GOOGLE_WORKFORCE_CALENDAR_ID": "work"})
        self.assertEqual(targets, {"ade": "school", "workforce": "work"})

    def test_partial_configuration_rejected(self):
        with self.assertRaises(GoogleCalendarError):
            calendar_targets({"GOOGLE_ADE_CALENDAR_ID": "school"})

    def test_migration_routes_known_events_and_rejects_destination_duplicates(self):
        event = example()
        remote = {**event_payload(event), "id": "example"}
        targets = {"ade": "school", "workforce": "work"}
        self.assertEqual(migration_plan([event], [remote], targets, {"school": [], "work": []})[0][1], "school")
        with self.assertRaises(GoogleCalendarError):
            migration_plan([event], [remote], targets, {"school": [remote], "work": []})
        with self.assertRaises(GoogleCalendarError):
            migration_plan([], [remote], targets, {"school": [], "work": []})
