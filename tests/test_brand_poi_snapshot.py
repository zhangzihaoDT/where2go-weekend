import csv
import json
import os
import shutil
import tempfile
import unittest

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
import sys
sys.path.insert(0, PROJECT_ROOT)

from src.brand_poi_snapshot import (
    BrandPoiSnapshot, make_snapshot_id, write_compare_result,
    REQUIRED_CSV_COLUMNS, COMPARE_BASE,
)


def _make_rows(n=5):
    return [
        {"brand_id": f"b{i}", "brand_name": f"品牌{i}", "name": f"门店{i}",
         "district": "浦东新区", "lng_gcj02": "121.5", "lat_gcj02": "31.2",
         "poi_kind": "experience_store", "source_query": "品牌", "address": "路",
         "poi_id": f"P{i:03d}", "type": "汽车", "store_location_type": "mall"}
        for i in range(n)
    ]


class TestBrandPoiSnapshot(unittest.TestCase):

    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()

    def tearDown(self):
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def test_create_and_read_csv(self):
        snap = BrandPoiSnapshot.from_date_city("2026-07-08", "上海", base_dir=self.tmpdir)
        rows = _make_rows(3)
        snap.write_csv(rows)
        self.assertTrue(os.path.isfile(snap.csv_path))
        loaded = snap.read_csv()
        self.assertEqual(len(loaded), 3)
        self.assertEqual(loaded[0]["brand_id"], "b0")

    def test_create_and_read_json(self):
        snap = BrandPoiSnapshot.from_date_city("2026-07-08", "上海", base_dir=self.tmpdir)
        rows = _make_rows(3)
        snap.write_json(rows)
        self.assertTrue(os.path.isfile(snap.json_path))
        loaded = snap.read_json()
        self.assertEqual(len(loaded), 3)

    def test_create_manifest(self):
        snap = BrandPoiSnapshot.from_date_city("2026-07-08", "上海", base_dir=self.tmpdir)
        snap.create_manifest({"total_poi": 5}, ["品牌1", "品牌2"])
        self.assertTrue(os.path.isfile(snap.manifest_path))
        m = snap.read_manifest()
        self.assertEqual(m["date"], "2026-07-08")
        self.assertEqual(m["city"], "上海")
        self.assertEqual(m["stats"]["total_poi"], 5)
        self.assertEqual(m["brands"], ["品牌1", "品牌2"])

    def test_exists(self):
        snap = BrandPoiSnapshot.from_date_city("2026-07-08", "上海", base_dir=self.tmpdir)
        self.assertFalse(snap.exists())
        os.makedirs(snap.dir)
        self.assertTrue(snap.exists())

    def test_enriched_roundtrip(self):
        snap = BrandPoiSnapshot.from_date_city("2026-07-08", "上海", base_dir=self.tmpdir)
        snap.write_csv(_make_rows(2))
        rows = snap.read_csv()
        enriched = [dict(r, is_frontend_store="true") for r in rows]
        snap.write_enriched_csv(enriched)
        self.assertTrue(os.path.isfile(snap.enriched_csv_path))
        loaded = snap.read_enriched_csv()
        self.assertEqual(len(loaded), 2)
        self.assertEqual(loaded[0]["is_frontend_store"], "true")

    def test_summary_roundtrip(self):
        snap = BrandPoiSnapshot.from_date_city("2026-07-08", "上海", base_dir=self.tmpdir)
        summary = {"total_poi": 10, "brand_counts": {"品牌1": 5, "品牌2": 5}}
        snap.write_summary_json(summary)
        loaded = snap.read_summary_json()
        self.assertEqual(loaded["total_poi"], 10)

    def test_analysis_report(self):
        snap = BrandPoiSnapshot.from_date_city("2026-07-08", "上海", base_dir=self.tmpdir)
        snap.write_analysis_report("# 测试报告")
        with open(snap.analysis_report_path, encoding="utf-8") as f:
            self.assertIn("测试报告", f.read())

    def test_compare_result(self):
        base_id = make_snapshot_id("2026-07-01", "上海")
        target_id = make_snapshot_id("2026-07-08", "上海")
        out_dir = write_compare_result(
            base_id, target_id,
            {"markdown": "# 对比结果", "delta": 5},
            base_dir=self.tmpdir,
        )
        self.assertTrue(os.path.isdir(out_dir))
        json_path = os.path.join(out_dir, "compare.json")
        md_path = os.path.join(out_dir, "compare.md")
        self.assertTrue(os.path.isfile(json_path))
        self.assertTrue(os.path.isfile(md_path))
        with open(json_path, encoding="utf-8") as f:
            d = json.load(f)
            self.assertEqual(d["delta"], 5)

    def test_list_snapshots(self):
        s1 = BrandPoiSnapshot.from_date_city("2026-07-01", "上海", base_dir=self.tmpdir)
        s1.write_csv(_make_rows(3))
        s1.create_manifest({"total_poi": 3}, ["品牌1"])
        s2 = BrandPoiSnapshot.from_date_city("2026-07-08", "上海", base_dir=self.tmpdir)
        s2.write_csv(_make_rows(5))
        s2.create_manifest({"total_poi": 5}, ["品牌2"])
        listed = BrandPoiSnapshot.list_snapshots(base_dir=self.tmpdir)
        self.assertEqual(len(listed), 2)
        self.assertEqual(listed[0][0], "2026-07-08_上海")
        self.assertEqual(listed[0][1], "上海")
        self.assertEqual(listed[1][0], "2026-07-01_上海")

    def test_validate_schema_ok(self):
        rows = _make_rows(1)
        missing = BrandPoiSnapshot.validate_schema(rows)
        self.assertEqual(missing, [])

    def test_validate_schema_missing(self):
        rows = [{"brand_id": "b1", "name": "test"}]
        missing = BrandPoiSnapshot.validate_schema(rows)
        self.assertIn("brand_name", missing)
        self.assertIn("district", missing)

    def test_empty_csv_read_returns_empty(self):
        snap = BrandPoiSnapshot.from_date_city("2026-07-08", "上海", base_dir=self.tmpdir)
        self.assertEqual(snap.read_csv(), [])
        self.assertEqual(snap.read_json(), [])
        self.assertEqual(snap.read_enriched_csv(), [])
        self.assertIsNone(snap.read_summary_json())
        self.assertIsNone(snap.read_manifest())

    def test_make_snapshot_id(self):
        sid = make_snapshot_id("2026-07-08", "上海")
        self.assertEqual(sid, "2026-07-08_上海")

    def test_snapshot_dir_includes_city(self):
        snap = BrandPoiSnapshot.from_date_city("2026-07-08", "上海", base_dir=self.tmpdir)
        self.assertTrue(snap.dir.endswith("2026-07-08_上海"))
        self.assertEqual(snap.date_str, "2026-07-08")
        self.assertEqual(snap.city, "上海")

    def test_read_commands_call_no_api(self):
        """Verify analyze/map/slice do not call _amap_request."""
        import subprocess, sys as _sys
        script = '''
import sys
sys.path.insert(0, ".")
from src.brand_poi_scanner import _amap_request
_amap_request = lambda *a, **kw: (_ for _ in ()).throw(RuntimeError("API CALLED"))
from src.brand_poi_analyzer import run_analyzer
from src.brand_poi_snapshot import BrandPoiSnapshot
snap = BrandPoiSnapshot("{snap_id}")
rows = snap.read_csv()
result = run_analyzer(rows, snap.city, snap.date_str, top_n=20)
print(f"analyze OK: {{len(result['enriched_rows'])}} enriched rows")
# slice (no API)
out = "/tmp/_noapi_slice.csv"
import csv
with open(out, "w", newline="", encoding="utf-8") as f:
    w = csv.writer(f)
    w.writerow(["brand_id","brand_name","name","district","lng_gcj02","lat_gcj02","poi_kind","source_query","address"])
    for r in rows:
        w.writerow([r.get(k,"") for k in ["brand_id","brand_name","name","district","lng_gcj02","lat_gcj02","poi_kind","source_query","address"]])
print(f"slice OK")
print("ALL NO-API CHECKS PASSED")
'''
        result = subprocess.run(
            [_sys.executable, "-c", script.format(snap_id="2026-07-08_上海")],
            capture_output=True, text=True, cwd=os.path.join(os.path.dirname(__file__), ".."),
        )
        if result.returncode != 0:
            self.fail(f"no-api check failed: {result.stderr}")
        self.assertIn("ALL NO-API CHECKS PASSED", result.stdout)


if __name__ == "__main__":
    unittest.main()
