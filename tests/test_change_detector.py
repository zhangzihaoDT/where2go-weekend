import os
import sys
import unittest
from datetime import date
from copy import deepcopy

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, PROJECT_ROOT)

from src.change_detector import (
    detect_changes,
    generate_baseline_events,
    find_previous_snapshot,
)


def _make_poi_row(poi_id, name, address, district_id, district_name,
                   category_id="coffee"):
    return {
        "poi_id": poi_id,
        "name": name,
        "address": address,
        "district_id": district_id,
        "district_name": district_name,
        "category_id": category_id,
        "snapshot_date": "2026-07-11",
    }


class TestChangeDetector(unittest.TestCase):

    def test_identifies_new_poi(self):
        """detect_changes should identify new POIs."""
        current = [
            _make_poi_row("A1", "咖啡A", "Addr1", "d1", "街区1", "coffee"),
            _make_poi_row("A2", "咖啡B", "Addr2", "d1", "街区1", "coffee"),
        ]
        previous = [
            _make_poi_row("A1", "咖啡A", "Addr1", "d1", "街区1", "coffee"),
        ]
        events = detect_changes(current, previous, date(2026, 7, 11), date(2026, 7, 4))
        new_pois = [e for e in events if e["event_type"] == "new_poi"]
        self.assertEqual(len(new_pois), 1)
        self.assertEqual(new_pois[0]["poi_id"], "A2")

    def test_identifies_disappeared_poi(self):
        """detect_changes should identify disappeared POIs."""
        current = [
            _make_poi_row("A1", "咖啡A", "Addr1", "d1", "街区1", "coffee"),
        ]
        previous = [
            _make_poi_row("A1", "咖啡A", "Addr1", "d1", "街区1", "coffee"),
            _make_poi_row("A2", "咖啡B", "Addr2", "d1", "街区1", "coffee"),
        ]
        events = detect_changes(current, previous, date(2026, 7, 11), date(2026, 7, 4))
        disappeared = [e for e in events if e["event_type"] == "disappeared_poi"]
        self.assertEqual(len(disappeared), 1)
        self.assertEqual(disappeared[0]["poi_id"], "A2")

    def test_no_previous_snapshot(self):
        """generate_baseline_events should produce no_previous_snapshot events."""
        current = [
            _make_poi_row("A1", "咖啡A", "Addr1", "d1", "街区1", "coffee"),
        ]
        events = generate_baseline_events(current, date(2026, 7, 11))
        self.assertTrue(len(events) > 0)
        for e in events:
            self.assertEqual(e["event_type"], "no_previous_snapshot")

    def test_category_growth(self):
        """detect_changes should identify category_growth."""
        current = [
            _make_poi_row("A1", "咖啡A", "Addr1", "d1", "街区1", "coffee"),
            _make_poi_row("A2", "咖啡B", "Addr2", "d1", "街区1", "coffee"),
        ]
        previous = [
            _make_poi_row("A1", "咖啡A", "Addr1", "d1", "街区1", "coffee"),
        ]
        events = detect_changes(current, previous, date(2026, 7, 11), date(2026, 7, 4))
        growth = [e for e in events if e["event_type"] == "category_growth"]
        self.assertTrue(len(growth) >= 1)
        for e in growth:
            self.assertEqual(e["category_id"], "coffee")
            self.assertIn("growth", e["event_type"])

    def test_category_decline(self):
        """detect_changes should identify category_decline."""
        current = [
            _make_poi_row("A1", "咖啡A", "Addr1", "d1", "街区1", "coffee"),
        ]
        previous = [
            _make_poi_row("A1", "咖啡A", "Addr1", "d1", "街区1", "coffee"),
            _make_poi_row("A2", "咖啡B", "Addr2", "d1", "街区1", "coffee"),
        ]
        events = detect_changes(current, previous, date(2026, 7, 11), date(2026, 7, 4))
        decline = [e for e in events if e["event_type"] == "category_decline"]
        self.assertTrue(len(decline) >= 1)

    def test_find_previous_snapshot_none(self):
        """find_previous_snapshot returns None when no snapshots exist."""
        import tempfile
        with tempfile.TemporaryDirectory() as tmpdir:
            path, d = find_previous_snapshot(tmpdir, date(2026, 7, 11))
            self.assertIsNone(path)
            self.assertIsNone(d)


if __name__ == "__main__":
    unittest.main()
