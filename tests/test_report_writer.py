import os
import sys
import unittest
from datetime import date
import tempfile

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, PROJECT_ROOT)

from src.report_writer import generate_report
from src.amap_client import CollectionState


class TestReportWriter(unittest.TestCase):

    def setUp(self):
        self.change_scores = [
            {
                "score_date": "2026-07-11",
                "district_id": "d1",
                "district_name": "智慧坊",
                "new_poi_count": 0,
                "disappeared_poi_count": 0,
                "category_growth_count": 0,
                "category_decline_count": 0,
                "freshness_score": 50,
                "category_change_score": 0,
                "low_crowding_potential": 75,
                "route_potential_score": 80,
                "change_score": 48,
                "score_explanation": "智慧坊 为首期基准快照",
            },
            {
                "score_date": "2026-07-11",
                "district_id": "d2",
                "district_name": "定西路",
                "new_poi_count": 0,
                "disappeared_poi_count": 0,
                "category_growth_count": 0,
                "category_decline_count": 0,
                "freshness_score": 50,
                "category_change_score": 0,
                "low_crowding_potential": 70,
                "route_potential_score": 80,
                "change_score": 48,
                "score_explanation": "定西路 为首期基准快照",
            },
        ]
        self.change_events = [
            {
                "snapshot_date": "2026-07-08",
                "previous_snapshot_date": "",
                "district_id": "d1",
                "district_name": "智慧坊",
                "category_id": "coffee",
                "event_type": "no_previous_snapshot",
                "poi_id": "A1",
                "name": "咖啡A",
                "address": "Addr",
                "signal_strength": 0,
                "why_interesting": "首期基准",
            }
        ]
        self.snapshot_rows = [
            {"source": "sample", "poi_id": "A1", "name": "咖啡A",
             "district_id": "d1", "district_name": "智慧坊",
             "category_id": "coffee"},
        ]
        self.state = CollectionState(api_key_present=False)
        self.state.fallback_used = True

    def test_title_contains_city_radar(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            path = generate_report(
                self.change_scores, self.change_events, self.snapshot_rows,
                tmpdir, snapshot_date=date(2026, 7, 8),
                weekend_date=date(2026, 7, 11),
                has_previous_snapshot=False,
                collection_state=self.state,
            )
            with open(path, encoding="utf-8") as f:
                content = f.read()
            self.assertIn("城市变化雷达", content)

    def test_contains_seven_sections(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            path = generate_report(
                self.change_scores, self.change_events, self.snapshot_rows,
                tmpdir, snapshot_date=date(2026, 7, 8),
                weekend_date=date(2026, 7, 11),
                has_previous_snapshot=False,
                collection_state=self.state,
            )
            with open(path, encoding="utf-8") as f:
                content = f.read()
            sections = [
                "本周城市变化信号",
                "街区变化指数",
                "新出现的空间",
                "为什么这个变化值得去看",
                "三条周末观察路线",
                "一个城市观察选题",
                "数据采集说明",
            ]
            for s in sections:
                with self.subTest(section=s):
                    self.assertIn(s, content)

    def test_contains_keywords(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            path = generate_report(
                self.change_scores, self.change_events, self.snapshot_rows,
                tmpdir, snapshot_date=date(2026, 7, 8),
                weekend_date=date(2026, 7, 11),
                has_previous_snapshot=False,
                collection_state=self.state,
            )
            with open(path, encoding="utf-8") as f:
                content = f.read()
            keywords = ["变化", "新出现", "观察路线"]
            for kw in keywords:
                with self.subTest(keyword=kw):
                    self.assertIn(kw, content)

    def test_not_top_list_oriented(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            path = generate_report(
                self.change_scores, self.change_events, self.snapshot_rows,
                tmpdir, snapshot_date=date(2026, 7, 8),
                weekend_date=date(2026, 7, 11),
                has_previous_snapshot=False,
                collection_state=self.state,
            )
            with open(path, encoding="utf-8") as f:
                content = f.read()
            top_phrases = ["TOP", "TOP榜单", "最好玩", "最好吃"]
            for phrase in top_phrases:
                with self.subTest(phrase=phrase):
                    self.assertNotIn(phrase, content)

    def test_has_collection_section(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            path = generate_report(
                self.change_scores, self.change_events, self.snapshot_rows,
                tmpdir, snapshot_date=date(2026, 7, 8),
                weekend_date=date(2026, 7, 11),
                has_previous_snapshot=False,
                collection_state=self.state,
            )
            with open(path, encoding="utf-8") as f:
                content = f.read()
            self.assertIn("数据采集说明", content)
            self.assertIn("API 请求数", content)
            self.assertIn("缓存命中数", content)

    def test_mentions_both_dates(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            path = generate_report(
                self.change_scores, self.change_events, self.snapshot_rows,
                tmpdir, snapshot_date=date(2026, 7, 8),
                weekend_date=date(2026, 7, 11),
                has_previous_snapshot=False,
                collection_state=self.state,
            )
            with open(path, encoding="utf-8") as f:
                content = f.read()
            self.assertIn("2026-07-08", content)
            self.assertIn("2026-07-11", content)

    def test_report_filename_uses_weekend_date(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            path = generate_report(
                self.change_scores, self.change_events, self.snapshot_rows,
                tmpdir, snapshot_date=date(2026, 7, 8),
                weekend_date=date(2026, 7, 11),
                has_previous_snapshot=False,
                collection_state=self.state,
            )
            self.assertIn("2026-07-11", os.path.basename(path))
            self.assertNotIn("2026-07-08", os.path.basename(path))

    def test_route_sections_have_observation_questions(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            path = generate_report(
                self.change_scores, self.change_events, self.snapshot_rows,
                tmpdir, snapshot_date=date(2026, 7, 8),
                weekend_date=date(2026, 7, 11),
                has_previous_snapshot=False,
                collection_state=self.state,
            )
            with open(path, encoding="utf-8") as f:
                content = f.read()
            self.assertIn("观察问题", content)
            self.assertIn("适合人群", content)


if __name__ == "__main__":
    unittest.main()
