import os
import sys
import unittest
from datetime import date

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, PROJECT_ROOT)

from src.scorer import compute_change_scores


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
        "source": "sample",
    }


def _make_change_event(etype, did, dname, cat="coffee"):
    return {
        "event_date": "2026-07-11",
        "previous_date": "2026-07-04",
        "district_id": did,
        "district_name": dname,
        "category_id": cat,
        "event_type": etype,
        "poi_id": "",
        "name": "",
        "address": "",
        "signal_strength": 50,
        "why_interesting": "test",
    }


class TestChangeScore(unittest.TestCase):

    def setUp(self):
        self.district_config = {
            "zhihui": {
                "district_id": "zhihui",
                "name": "智慧坊",
                "tags": ["创意园区", "生活方式"],
                "default_accessibility_score": 75,
                "default_crowding_risk": 40,
            },
        }

    def test_score_in_range(self):
        """change_score should be between 0 and 100."""
        current = [
            _make_poi_row("A1", "P1", "A1", "zhihui", "智慧坊", "coffee"),
        ]
        scores = compute_change_scores(
            current, None, [], self.district_config, date(2026, 7, 11)
        )
        for s in scores:
            self.assertGreaterEqual(s["change_score"], 0)
            self.assertLessEqual(s["change_score"], 100)

    def test_first_snapshot_explanation(self):
        """First snapshot should mention '首期' or '基准'."""
        current = [
            _make_poi_row("A1", "P1", "A1", "zhihui", "智慧坊", "coffee"),
        ]
        scores = compute_change_scores(
            current, None, [], self.district_config, date(2026, 7, 11)
        )
        for s in scores:
            self.assertTrue(
                "首期" in s["score_explanation"] or "基准" in s["score_explanation"]
            )

    def test_low_crowding_potential_for_creative_park(self):
        """创意园区 should have higher low_crowding_potential."""
        current = [
            _make_poi_row("A1", "P1", "A1", "zhihui", "智慧坊", "coffee"),
        ]
        scores = compute_change_scores(
            current, None, [], self.district_config, date(2026, 7, 11)
        )
        for s in scores:
            self.assertGreaterEqual(s["low_crowding_potential"], 50)

    def test_hot_district_low_crowding_potential(self):
        """网红街区 should have lower low_crowding_potential."""
        hot_config = {
            "anfu": {
                "district_id": "anfu",
                "name": "安福路",
                "tags": ["网红", "热门商圈"],
                "default_accessibility_score": 90,
                "default_crowding_risk": 85,
            }
        }
        current = [
            _make_poi_row("A1", "P1", "A1", "anfu", "安福路", "coffee"),
            _make_poi_row("A2", "P2", "A2", "anfu", "安福路", "coffee"),
            _make_poi_row("A3", "P3", "A3", "anfu", "安福路", "coffee"),
        ]
        scores = compute_change_scores(
            current, None, [], hot_config, date(2026, 7, 11)
        )
        for s in scores:
            self.assertLessEqual(s["low_crowding_potential"], 40)

    def test_change_score_with_events(self):
        """With new POI events, change_score should reflect changes."""
        current = [
            _make_poi_row("A1", "P1", "A1", "zhihui", "智慧坊", "coffee"),
            _make_poi_row("A2", "P2", "A2", "zhihui", "智慧坊", "coffee"),
        ]
        previous = [
            _make_poi_row("A1", "P1", "A1", "zhihui", "智慧坊", "coffee"),
        ]
        events = [
            _make_change_event("new_poi", "zhihui", "智慧坊", "coffee"),
            _make_change_event("category_growth", "zhihui", "智慧坊", "coffee"),
        ]
        scores = compute_change_scores(
            current, previous, events, self.district_config, date(2026, 7, 11)
        )
        for s in scores:
            self.assertGreater(s["new_poi_count"], 0)
            self.assertGreater(s["change_score"], 0)


if __name__ == "__main__":
    unittest.main()
