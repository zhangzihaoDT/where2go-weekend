import csv
import os
import shutil
import sys
import tempfile
import unittest
from datetime import date

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, PROJECT_ROOT)

from src.run import deduplicate_snapshot_rows
from src.amap_client import SNAPSHOT_FIELDS, write_snapshot_csv
from src.change_detector import (
    detect_changes,
    find_previous_snapshot,
    load_snapshot,
)


def _make_row(snapshot_date: str, poi_id: str, name: str, address: str,
              district_id: str = "d1", district_name: str = "街区1",
              category_id: str = "coffee", keyword: str = "kw1",
              source: str = "test", lng: str = "121.0", lat: str = "31.0",
              **kw) -> dict:
    row = {
        "snapshot_date": snapshot_date,
        "source": source,
        "district_id": district_id,
        "district_name": district_name,
        "category_id": category_id,
        "keyword": keyword,
        "poi_id": poi_id,
        "name": name,
        "address": address,
        "lng": lng,
        "lat": lat,
        "poi_type": "",
        "raw_type": "",
        "business_area": "",
        "confidence": "0.8",
    }
    row.update(kw)
    return row


def _same_event_key(e: dict) -> tuple:
    return (e.get("event_type", ""), e.get("poi_id", ""),
            e.get("district_id", ""), e.get("category_id", ""))


class TestSnapshotPathAndHistory(unittest.TestCase):
    """Test 1: 路径与历史发现"""

    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()
        self.snapshot_dir = self.tmpdir

    def tearDown(self):
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def test_snapshot_dir_is_weekend_district_poi(self):
        """Snapshot 写入路径指向 weekend_district_poi 而非 poi_snapshots."""
        from src.run import main as run_main
        import inspect
        source = inspect.getsource(run_main)
        self.assertIn("weekend_district_poi", source,
                      "run.py 应使用 data/weekend_district_poi")
        self.assertNotIn("data/poi_snapshots", source,
                         "run.py 不应再引用 data/poi_snapshots")

    def test_b_can_find_a(self):
        """B 期运行能够自动找到 A 期."""
        rows_a = [_make_row("2026-07-01", "POI-A", "咖啡A", "AddrA")]
        write_snapshot_csv(rows_a, os.path.join(self.snapshot_dir, "2026-07-01_poi_snapshot.csv"))
        prev_path, prev_date = find_previous_snapshot(self.snapshot_dir, date(2026, 7, 8))
        self.assertIsNotNone(prev_path, "B 期应找到 A 期")
        self.assertEqual(prev_date, date(2026, 7, 1))

    def test_current_date_not_found_as_previous(self):
        """当前期 Snapshot 不应被误选为 previous."""
        write_snapshot_csv(
            [_make_row("2026-07-08", "POI-A", "咖啡A", "AddrA")],
            os.path.join(self.snapshot_dir, "2026-07-08_poi_snapshot.csv"),
        )
        prev_path, prev_date = find_previous_snapshot(self.snapshot_dir, date(2026, 7, 8))
        self.assertIsNone(prev_path, "当期不应被识别为历史快照")

    def test_find_most_recent_previous(self):
        """多个历史 Snapshot 时选最近的."""
        write_snapshot_csv(
            [_make_row("2026-07-01", "POI-A", "A", "A")],
            os.path.join(self.snapshot_dir, "2026-07-01_poi_snapshot.csv"),
        )
        write_snapshot_csv(
            [_make_row("2026-07-04", "POI-B", "B", "B")],
            os.path.join(self.snapshot_dir, "2026-07-04_poi_snapshot.csv"),
        )
        prev_path, prev_date = find_previous_snapshot(self.snapshot_dir, date(2026, 7, 8))
        self.assertEqual(prev_date, date(2026, 7, 4), "应选择最近的 previous")

    def test_no_access_to_old_path(self):
        """find_previous_snapshot 不应访问 data/poi_snapshots."""
        old_path = os.path.join(PROJECT_ROOT, "data", "poi_snapshots")
        prev_path, _ = find_previous_snapshot(old_path, date(2026, 7, 8))
        self.assertIsNone(prev_path, "data/poi_snapshots 不存在或不应被访问")


class TestDedupRules(unittest.TestCase):
    """Tests 2-4: 去重规则"""

    def test_cross_keyword_dedup(self):
        """同一 (district_id, category_id, poi_id) 跨关键词只保留一条."""
        rows = [
            _make_row("2026-07-01", "POI-A", "咖啡A", "AddrA", keyword="kw1"),
            _make_row("2026-07-01", "POI-A", "咖啡A", "AddrA", keyword="kw2"),
            _make_row("2026-07-01", "POI-B", "咖啡B", "AddrB", keyword="kw1"),
        ]
        deduped = deduplicate_snapshot_rows(rows)
        self.assertEqual(len(deduped), 2)
        pids = [r["poi_id"] for r in deduped]
        self.assertCountEqual(pids, ["POI-A", "POI-B"])

    def test_cross_district_preserved(self):
        """同一 poi_id 在不同街区时保留两条."""
        rows = [
            _make_row("2026-07-01", "POI-A", "咖啡A", "AddrA", district_id="d1", district_name="街区1"),
            _make_row("2026-07-01", "POI-A", "咖啡A", "AddrA", district_id="d2", district_name="街区2"),
        ]
        deduped = deduplicate_snapshot_rows(rows)
        self.assertEqual(len(deduped), 2)

    def test_cross_category_preserved(self):
        """同一 poi_id 在同一街区不同类别时保留两条."""
        rows = [
            _make_row("2026-07-01", "POI-A", "咖啡A", "AddrA", category_id="coffee"),
            _make_row("2026-07-01", "POI-A", "咖啡A", "AddrA", category_id="food_light"),
        ]
        deduped = deduplicate_snapshot_rows(rows)
        self.assertEqual(len(deduped), 2)

    def test_dedup_order_preserved(self):
        """去重保留首次出现顺序."""
        rows = [
            _make_row("2026-07-01", "POI-B", "咖啡B", "AddrB"),
            _make_row("2026-07-01", "POI-A", "咖啡A", "AddrA"),
            _make_row("2026-07-01", "POI-A", "咖啡A", "AddrA", keyword="kw2"),
        ]
        deduped = deduplicate_snapshot_rows(rows)
        self.assertEqual(len(deduped), 2)
        self.assertEqual(deduped[0]["poi_id"], "POI-B")
        self.assertEqual(deduped[1]["poi_id"], "POI-A")

    def test_dedup_empty_poi_id_fallback(self):
        """poi_id 为空时 fallback 到标准化后的名称+地址."""
        rows = [
            _make_row("2026-07-01", "", " Ｃａｆé Ａ ", " Ａｄｄｒ １ "),
            _make_row("2026-07-01", "", "café a", "addr 1"),
        ]
        deduped = deduplicate_snapshot_rows(rows)
        self.assertEqual(len(deduped), 1, "NFKC 标准化后应识别为同一行")


class TestHistoricalDirtyData(unittest.TestCase):
    """Test 5: 历史脏数据处理"""

    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()
        self.snapshot_dir = self.tmpdir

    def tearDown(self):
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def test_dirty_previous_does_not_produce_duplicate_events(self):
        """历史快照含重复行，去重后 Compare 不产生重复消失事件."""
        rows_a = [
            _make_row("2026-07-01", "POI-A", "咖啡A", "AddrA"),
            _make_row("2026-07-01", "POI-A", "咖啡A", "AddrA", keyword="kw2"),
            _make_row("2026-07-01", "POI-B", "咖啡B", "AddrB"),
            _make_row("2026-07-01", "POI-B", "咖啡B", "AddrB", keyword="kw2"),
        ]
        rows_b = [
            _make_row("2026-07-08", "POI-A", "咖啡A", "AddrA"),
            _make_row("2026-07-08", "POI-A", "咖啡A", "AddrA", keyword="kw2"),
            _make_row("2026-07-08", "POI-C", "咖啡C", "AddrC"),
            _make_row("2026-07-08", "POI-C", "咖啡C", "AddrC", keyword="kw2"),
        ]
        a_path = os.path.join(self.snapshot_dir, "2026-07-01_poi_snapshot.csv")
        b_path = os.path.join(self.snapshot_dir, "2026-07-08_poi_snapshot.csv")
        write_snapshot_csv(rows_a, a_path)
        write_snapshot_csv(rows_b, b_path)

        raw_prev = load_snapshot(a_path)
        raw_curr = load_snapshot(b_path)
        self.assertEqual(len(raw_prev), 4, "原始 A 应有 4 行（含重复）")

        clean_prev = deduplicate_snapshot_rows(raw_prev)
        clean_curr = deduplicate_snapshot_rows(raw_curr)
        self.assertEqual(len(clean_prev), 2, "去重后 A 应有 2 条唯一 POI")
        self.assertEqual(len(clean_curr), 2, "去重后 B 应有 2 条唯一 POI")

        events = detect_changes(clean_curr, clean_prev, date(2026, 7, 8), date(2026, 7, 1))
        new_events = [e for e in events if e["event_type"] == "new_poi"]
        disappeared_events = [e for e in events if e["event_type"] == "disappeared_poi"]

        self.assertEqual(len(new_events), 1, "应准确产生 1 条新增")
        self.assertEqual(new_events[0]["poi_id"], "POI-C")
        self.assertEqual(len(disappeared_events), 1, "应准确产生 1 条消失")
        self.assertEqual(disappeared_events[0]["poi_id"], "POI-B")

        event_keys = [_same_event_key(e) for e in events
                      if e["event_type"] in ("new_poi", "disappeared_poi")]
        self.assertEqual(len(event_keys), len(set(event_keys)),
                         "变化事件中不应有重复键")


class TestAtoBChangeDetection(unittest.TestCase):
    """Tests 6: A→B 变化检测"""

    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()
        self.snapshot_dir = self.tmpdir

    def tearDown(self):
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def test_a_to_b_change_detection(self):
        """A→B fixture 准确产生 1 条新增和 1 条消失."""
        rows_a = [
            _make_row("2026-07-01", "POI-A", "咖啡A", "AddrA"),
            _make_row("2026-07-01", "POI-B", "咖啡B", "AddrB"),
        ]
        rows_b = [
            _make_row("2026-07-08", "POI-A", "咖啡A", "AddrA"),
            _make_row("2026-07-08", "POI-C", "咖啡C", "AddrC"),
        ]
        clean_a = deduplicate_snapshot_rows(rows_a)
        clean_b = deduplicate_snapshot_rows(rows_b)

        events = detect_changes(clean_b, clean_a, date(2026, 7, 8), date(2026, 7, 1))
        new_events = [e for e in events if e["event_type"] == "new_poi"]
        disappeared_events = [e for e in events if e["event_type"] == "disappeared_poi"]

        self.assertEqual(len(new_events), 1)
        self.assertEqual(new_events[0]["poi_id"], "POI-C")
        self.assertEqual(len(disappeared_events), 1)
        self.assertEqual(disappeared_events[0]["poi_id"], "POI-B")

        change_events = [e for e in events if e["event_type"]
                         in ("category_growth", "category_decline")]
        self.assertEqual(len(change_events), 0,
                         "品类数量不变时不应产生类目变化事件")

    def test_snapshot_no_duplicate_rows(self):
        """写入 Snapshot CSV 后读取，不应有完全重复行."""
        rows = [
            _make_row("2026-07-01", "POI-A", "咖啡A", "AddrA"),
            _make_row("2026-07-01", "POI-A", "咖啡A", "AddrA", keyword="kw2"),
            _make_row("2026-07-01", "POI-B", "咖啡B", "AddrB"),
        ]
        clean = deduplicate_snapshot_rows(rows)
        path = os.path.join(self.snapshot_dir, "2026-07-01_poi_snapshot.csv")
        write_snapshot_csv(clean, path)

        loaded = load_snapshot(path)
        self.assertEqual(len(loaded), 2, "写入后的 Snapshot 不应含重复行")
        dedup_keys = [(r["district_id"], r["category_id"], r["poi_id"])
                      for r in loaded]
        self.assertEqual(len(dedup_keys), len(set(dedup_keys)))

    def test_change_events_no_duplicate_keys(self):
        """变化事件中 (event_type, poi_id, district_id) 不重复."""
        rows_a = [
            _make_row("2026-07-01", "POI-A", "咖啡A", "AddrA"),
            _make_row("2026-07-01", "POI-B", "咖啡B", "AddrB"),
        ]
        rows_b = [
            _make_row("2026-07-08", "POI-A", "咖啡A", "AddrA"),
            _make_row("2026-07-08", "POI-C", "咖啡C", "AddrC"),
        ]
        clean_a = deduplicate_snapshot_rows(rows_a)
        clean_b = deduplicate_snapshot_rows(rows_b)
        events = detect_changes(clean_b, clean_a, date(2026, 7, 8), date(2026, 7, 1))

        poi_event_keys = [(_same_event_key(e)) for e in events
                          if e["event_type"] in ("new_poi", "disappeared_poi")]
        self.assertEqual(len(poi_event_keys), len(set(poi_event_key for poi_event_key in poi_event_keys)),
                         "变化事件中不应有重复的 (type, poi_id, district, category)")

    def test_read_previous_not_modified(self):
        """去重不修改源 CSV 文件."""
        rows_a = [
            _make_row("2026-07-01", "POI-A", "咖啡A", "AddrA"),
            _make_row("2026-07-01", "POI-A", "咖啡A", "AddrA", keyword="kw2"),
            _make_row("2026-07-01", "POI-B", "咖啡B", "AddrB"),
        ]
        path = os.path.join(self.snapshot_dir, "2026-07-01_poi_snapshot.csv")
        write_snapshot_csv(rows_a, path)

        raw = load_snapshot(path)
        self.assertEqual(len(raw), 3, "源 CSV 应保持 3 行")
        clean = deduplicate_snapshot_rows(raw)
        self.assertEqual(len(clean), 2, "内存去重后 2 行")
        reloaded = load_snapshot(path)
        self.assertEqual(len(reloaded), 3, "源文件应未被修改")


class TestCompareOffline(unittest.TestCase):
    """Test 7: Compare 不调用外部 API"""

    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()

    def tearDown(self):
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def test_compare_no_api_call(self):
        """两期 Snapshot 的读取、去重和变化计算不调用外部 API."""
        rows_a = [
            _make_row("2026-07-01", "POI-A", "咖啡A", "AddrA"),
            _make_row("2026-07-01", "POI-B", "咖啡B", "AddrB"),
        ]
        rows_b = [
            _make_row("2026-07-08", "POI-A", "咖啡A", "AddrA"),
            _make_row("2026-07-08", "POI-C", "咖啡C", "AddrC"),
        ]

        clean_a = deduplicate_snapshot_rows(rows_a)
        clean_b = deduplicate_snapshot_rows(rows_b)
        self.assertEqual(len(clean_a), 2)
        self.assertEqual(len(clean_b), 2)

        events = detect_changes(clean_b, clean_a, date(2026, 7, 8), date(2026, 7, 1))
        new_events = [e for e in events if e["event_type"] == "new_poi"]
        disappeared_events = [e for e in events if e["event_type"] == "disappeared_poi"]

        self.assertEqual(len(new_events), 1, "Compare 结果应含 1 条新增")
        self.assertEqual(len(disappeared_events), 1, "Compare 结果应含 1 条消失")
        self.assertEqual(new_events[0]["poi_id"], "POI-C")
        self.assertEqual(disappeared_events[0]["poi_id"], "POI-B")


if __name__ == "__main__":
    unittest.main()
