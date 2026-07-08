import os
import sys
import unittest
from datetime import date

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, PROJECT_ROOT)

from src.amap_client import (
    CollectionState,
    build_fallback_snapshot,
    _make_poi_id,
    write_collection_summary,
)


class TestAmapClient(unittest.TestCase):

    def test_fallback_snapshot_generates_rows(self):
        sample_path = os.path.join(PROJECT_ROOT, "data", "sample_poi.csv")
        rows = build_fallback_snapshot(sample_path, date(2026, 7, 11))
        self.assertTrue(len(rows) >= 24)
        for row in rows:
            self.assertIn("snapshot_date", row)
            self.assertIn("poi_id", row)
            self.assertIn("name", row)
            self.assertIn("district_id", row)

    def test_fallback_source_is_sample(self):
        sample_path = os.path.join(PROJECT_ROOT, "data", "sample_poi.csv")
        rows = build_fallback_snapshot(sample_path, date(2026, 7, 11))
        for row in rows:
            self.assertEqual(row["source"], "sample")

    def test_api_key_not_leaked(self):
        from datetime import date
        sample_path = os.path.join(PROJECT_ROOT, "data", "sample_poi.csv")
        rows = build_fallback_snapshot(sample_path, date(2026, 7, 11))
        content = str(rows)
        for row in rows:
            for val in row.values():
                self.assertNotIn("AMAP_API_KEY", str(val))
        api_key = os.environ.get("AMAP_API_KEY", "")
        if api_key:
            self.assertNotIn(api_key, content)

    def test_make_poi_id_consistent(self):
        id1 = _make_poi_id("咖啡A", "Addr1", "d1")
        id2 = _make_poi_id("咖啡A", "Addr1", "d1")
        self.assertEqual(id1, id2)
        id3 = _make_poi_id("咖啡B", "Addr1", "d1")
        self.assertNotEqual(id1, id3)


class TestCollectionState(unittest.TestCase):

    def test_budget_blocks_when_exceeded(self):
        state = CollectionState(daily_max=2, per_district_max=2, api_key_present=True)
        self.assertTrue(state.can_request("d1"))
        state.record_api_call("d1")
        self.assertTrue(state.can_request("d1"))
        state.record_api_call("d1")
        self.assertFalse(state.can_request("d1"))

    def test_budget_blocks_at_daily_max(self):
        state = CollectionState(daily_max=1, per_district_max=10, api_key_present=True)
        self.assertTrue(state.can_request("d1"))
        state.record_api_call("d1")
        self.assertFalse(state.can_request("d2"))

    def test_no_key_cannot_request(self):
        state = CollectionState(daily_max=30, api_key_present=False)
        self.assertFalse(state.can_request("d1"))

    def test_skipped_query_recorded(self):
        state = CollectionState(daily_max=1, api_key_present=True)
        state.record_api_call("d1")
        state.record_skipped("d1", "街区1", "咖啡", "coffee", "预算不足")
        self.assertEqual(state.skipped_queries, 1)
        self.assertEqual(len(state.skipped_tasks), 1)

    def test_cache_hit_recorded(self):
        state = CollectionState(api_key_present=True)
        state.record_cache_hit()
        self.assertEqual(state.cache_hits, 1)

    def test_planned_queries(self):
        state = CollectionState()
        p = state.planned_queries(3, 5)
        self.assertEqual(p, 15)


class TestCollectionSummary(unittest.TestCase):

    def test_summary_generated(self):
        import tempfile
        import csv
        state = CollectionState(api_key_present=False)
        state.fallback_used = True
        state.poi_count = 26
        summaries = [
            {
                "run_date": "2026-07-11",
                "district_id": "d1",
                "district_name": "街区1",
                "planned_queries": 0,
                "api_requests_used": 0,
                "cache_hits": 0,
                "skipped_queries": 0,
                "fallback_used": "yes",
                "poi_count": 26,
                "notes": "sample fallback",
            }
        ]
        with tempfile.TemporaryDirectory() as tmpdir:
            path = os.path.join(tmpdir, "summary.csv")
            write_collection_summary(
                state, path,
                snapshot_date=date(2026, 7, 8),
                weekend_date=date(2026, 7, 11),
                district_summaries=summaries,
            )
            self.assertTrue(os.path.isfile(path))
            with open(path) as f:
                rows = list(csv.DictReader(f))
            self.assertEqual(len(rows), 2)
            self.assertEqual(rows[-1]["district_name"], "合计")
            self.assertIn("snapshot_date", rows[0])
            self.assertIn("weekend_date", rows[0])
            self.assertEqual(rows[0]["snapshot_date"], "2026-07-08")
            self.assertEqual(rows[0]["weekend_date"], "2026-07-11")


class TestCategoriesConfig(unittest.TestCase):

    def test_query_keywords_and_semantic_keywords(self):
        import yaml
        path = os.path.join(PROJECT_ROOT, "config", "categories.yaml")
        with open(path, encoding="utf-8") as f:
            config = yaml.safe_load(f)
        for cat in config["categories"]:
            self.assertIn("query_keywords", cat,
                          f"{cat['category_id']} missing query_keywords")
            self.assertIn("semantic_keywords", cat,
                          f"{cat['category_id']} missing semantic_keywords")
            self.assertTrue(len(cat["query_keywords"]) > 0,
                            f"{cat['category_id']} has empty query_keywords")
            self.assertTrue(len(cat["semantic_keywords"]) > 0,
                            f"{cat['category_id']} has empty semantic_keywords")


if __name__ == "__main__":
    unittest.main()
