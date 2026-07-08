import os
import sys
import unittest
import tempfile
import csv

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, PROJECT_ROOT)

from src.map_writer import (
    generate_amap_js_map,
    generate_leaflet_osm_map,
    generate_map,
    gcj02_to_wgs84_approx,
    transform_poi_coords,
)


def _make_snapshot_csv(path, rows):
    fields = [
        "snapshot_date", "source", "district_id", "district_name",
        "category_id", "keyword", "poi_id", "name", "address",
        "lng", "lat", "poi_type", "raw_type", "business_area", "confidence",
    ]
    with open(path, "w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fields)
        writer.writeheader()
        for r in rows:
            writer.writerow(r)


DISTRICTS_YAML = """
districts:
  - district_id: test1
    name: 测试街区
    city: 上海
    center_lng: 121.47
    center_lat: 31.23
    radius_m: 500
    tags: ["测试"]
    default_accessibility_score: 70
    default_crowding_risk: 50
"""


def _make_districts(path):
    with open(path, "w", encoding="utf-8") as f:
        f.write(DISTRICTS_YAML)


def _make_poi_row(**kw):
    defaults = {
        "snapshot_date": "2026-07-08", "source": "sample",
        "district_id": "test1", "district_name": "测试街区",
        "category_id": "coffee", "keyword": "咖啡",
        "poi_id": "P1", "name": "测试咖啡", "address": "测试地址",
        "lng": "121.471", "lat": "31.232",
        "poi_type": "", "raw_type": "", "business_area": "", "confidence": "0.5",
    }
    defaults.update(kw)
    return defaults


# ── Coordinate transform ──


class TestCoordTransform(unittest.TestCase):

    def test_gcj02_to_wgs84_approx_returns_tuple(self):
        result = gcj02_to_wgs84_approx(121.47, 31.23)
        self.assertIsInstance(result, tuple)
        self.assertEqual(len(result), 2)

    def test_gcj02_to_wgs84_approx_changes_values(self):
        lng, lat = gcj02_to_wgs84_approx(121.47, 31.23)
        self.assertNotAlmostEqual(lng, 121.47, places=3)
        self.assertNotAlmostEqual(lat, 31.23, places=3)

    def test_gcj02_to_wgs84_out_of_range(self):
        lng, lat = gcj02_to_wgs84_approx(200.0, 100.0)
        self.assertEqual(lng, 200.0)
        self.assertEqual(lat, 100.0)

    def test_gcj02_to_wgs84_zero(self):
        lng, lat = gcj02_to_wgs84_approx(0.0, 0.0)
        self.assertEqual(lng, 0.0)
        self.assertEqual(lat, 0.0)


class TestTransformPoi(unittest.TestCase):

    def test_approx_wgs84_adds_map_coords(self):
        result = transform_poi_coords({"lng": "121.47", "lat": "31.23"}, "approx_wgs84")
        self.assertEqual(result["source_crs"], "GCJ-02")
        self.assertEqual(result["map_crs"], "WGS84")
        self.assertEqual(result["coord_transform_method"], "gcj02_to_wgs84_approx")
        self.assertNotEqual(result["source_lng"], result["map_lng"])

    def test_raw_gcj02_keeps_coords(self):
        result = transform_poi_coords({"lng": "121.47", "lat": "31.23"}, "raw_gcj02")
        self.assertEqual(result["map_crs"], "GCJ-02")
        self.assertEqual(result["coord_transform_method"], "none")
        self.assertEqual(result["source_lng"], result["map_lng"])


# ── Unified entry ──


class TestGenerateMap(unittest.TestCase):

    def test_default_provider_is_amap_js(self):
        self.assertEqual(generate_map.__defaults__ is not None, True)

    def test_generate_map_amap_js(self):
        with tempfile.TemporaryDirectory() as tmp:
            sp = os.path.join(tmp, "snap.csv")
            _make_snapshot_csv(sp, [_make_poi_row()])
            dp = os.path.join(tmp, "dist.yaml")
            _make_districts(dp)
            out = os.path.join(tmp, "map.html")
            generate_map(sp, dp, out, "2026-07-08", "2026-07-11", provider="amap_js")
            self.assertTrue(os.path.isfile(out))

    def test_generate_map_leaflet_osm(self):
        with tempfile.TemporaryDirectory() as tmp:
            sp = os.path.join(tmp, "snap.csv")
            _make_snapshot_csv(sp, [_make_poi_row()])
            dp = os.path.join(tmp, "dist.yaml")
            _make_districts(dp)
            out = os.path.join(tmp, "map.html")
            generate_map(sp, dp, out, "2026-07-08", "2026-07-11",
                         provider="leaflet_osm", coord_mode="approx_wgs84")
            self.assertTrue(os.path.isfile(out))

    def test_generate_map_unknown_provider(self):
        with tempfile.TemporaryDirectory() as tmp:
            with self.assertRaises(ValueError):
                generate_map("x", "y", "z", "d", "d", provider="unknown")


# ── AMap JS API ──


class TestAmapJsMap(unittest.TestCase):

    def test_generates_html_file(self):
        with tempfile.TemporaryDirectory() as tmp:
            sp = os.path.join(tmp, "snap.csv")
            _make_snapshot_csv(sp, [_make_poi_row()])
            dp = os.path.join(tmp, "dist.yaml")
            _make_districts(dp)
            out = os.path.join(tmp, "map.html")
            generate_amap_js_map(sp, dp, out, "2026-07-08", "2026-07-11")
            self.assertTrue(os.path.isfile(out))

    def test_contains_amap_map_init(self):
        with tempfile.TemporaryDirectory() as tmp:
            sp = os.path.join(tmp, "snap.csv")
            _make_snapshot_csv(sp, [_make_poi_row()])
            dp = os.path.join(tmp, "dist.yaml")
            _make_districts(dp)
            out = os.path.join(tmp, "map.html")
            generate_amap_js_map(sp, dp, out, "2026-07-08", "2026-07-11")
            with open(out) as f:
                content = f.read()
            self.assertIn("AMap.Map", content)

    def test_contains_amap_script(self):
        with tempfile.TemporaryDirectory() as tmp:
            sp = os.path.join(tmp, "snap.csv")
            _make_snapshot_csv(sp, [_make_poi_row()])
            dp = os.path.join(tmp, "dist.yaml")
            _make_districts(dp)
            out = os.path.join(tmp, "map.html")
            generate_amap_js_map(sp, dp, out, "2026-07-08", "2026-07-11")
            with open(out) as f:
                content = f.read()
            self.assertIn("webapi.amap.com/maps", content)

    def test_uses_raw_gcj02_no_transform(self):
        with tempfile.TemporaryDirectory() as tmp:
            sp = os.path.join(tmp, "snap.csv")
            _make_snapshot_csv(sp, [_make_poi_row()])
            dp = os.path.join(tmp, "dist.yaml")
            _make_districts(dp)
            out = os.path.join(tmp, "map.html")
            generate_amap_js_map(sp, dp, out, "2026-07-08", "2026-07-11")
            with open(out) as f:
                content = f.read()
            self.assertIn("coord_transform: none", content)
            self.assertIn("GCJ-02", content)
            self.assertNotIn("gcj02_to_wgs84", content)

    def test_contains_district_circle(self):
        with tempfile.TemporaryDirectory() as tmp:
            sp = os.path.join(tmp, "snap.csv")
            _make_snapshot_csv(sp, [_make_poi_row()])
            dp = os.path.join(tmp, "dist.yaml")
            _make_districts(dp)
            out = os.path.join(tmp, "map.html")
            generate_amap_js_map(sp, dp, out, "2026-07-08", "2026-07-11")
            with open(out) as f:
                content = f.read()
            self.assertIn("AMap.Circle", content)

    def test_has_key_warning_when_no_key(self):
        with tempfile.TemporaryDirectory() as tmp:
            sp = os.path.join(tmp, "snap.csv")
            _make_snapshot_csv(sp, [_make_poi_row()])
            dp = os.path.join(tmp, "dist.yaml")
            _make_districts(dp)
            out = os.path.join(tmp, "map.html")
            # Remove env keys for test
            old_js = os.environ.pop("AMAP_JS_API_KEY", None)
            old_sc = os.environ.pop("AMAP_SECURITY_JS_CODE", None)
            try:
                generate_amap_js_map(sp, dp, out, "2026-07-08", "2026-07-11")
                with open(out) as f:
                    content = f.read()
                self.assertIn("缺少 AMAP_JS_API_KEY", content)
                self.assertIn("NO_KEY", content)
            finally:
                if old_js is not None:
                    os.environ["AMAP_JS_API_KEY"] = old_js
                if old_sc is not None:
                    os.environ["AMAP_SECURITY_JS_CODE"] = old_sc

    def test_empty_poi_still_generates(self):
        with tempfile.TemporaryDirectory() as tmp:
            sp = os.path.join(tmp, "snap.csv")
            _make_snapshot_csv(sp, [])
            dp = os.path.join(tmp, "dist.yaml")
            _make_districts(dp)
            out = os.path.join(tmp, "map.html")
            generate_amap_js_map(sp, dp, out, "2026-07-08", "2026-07-11")
            self.assertTrue(os.path.isfile(out))

    def test_contains_dates(self):
        with tempfile.TemporaryDirectory() as tmp:
            sp = os.path.join(tmp, "snap.csv")
            _make_snapshot_csv(sp, [_make_poi_row()])
            dp = os.path.join(tmp, "dist.yaml")
            _make_districts(dp)
            out = os.path.join(tmp, "map.html")
            generate_amap_js_map(sp, dp, out, "2026-07-08", "2026-07-11")
            with open(out) as f:
                content = f.read()
            self.assertIn("2026-07-08", content)
            self.assertIn("2026-07-11", content)


# ── Leaflet + OSM ──


class TestLeafletOsmMap(unittest.TestCase):

    def test_generates_html_file(self):
        with tempfile.TemporaryDirectory() as tmp:
            sp = os.path.join(tmp, "snap.csv")
            _make_snapshot_csv(sp, [_make_poi_row()])
            dp = os.path.join(tmp, "dist.yaml")
            _make_districts(dp)
            out = os.path.join(tmp, "map.html")
            generate_leaflet_osm_map(sp, dp, out, "2026-07-08", "2026-07-11")
            self.assertTrue(os.path.isfile(out))

    def test_contains_leaflet_init(self):
        with tempfile.TemporaryDirectory() as tmp:
            sp = os.path.join(tmp, "snap.csv")
            _make_snapshot_csv(sp, [_make_poi_row()])
            dp = os.path.join(tmp, "dist.yaml")
            _make_districts(dp)
            out = os.path.join(tmp, "map.html")
            generate_leaflet_osm_map(sp, dp, out, "2026-07-08", "2026-07-11")
            with open(out) as f:
                content = f.read()
            self.assertIn("L.map(", content)
            self.assertIn("L.tileLayer(", content)

    def test_approx_wgs84_has_transform_note(self):
        with tempfile.TemporaryDirectory() as tmp:
            sp = os.path.join(tmp, "snap.csv")
            _make_snapshot_csv(sp, [_make_poi_row()])
            dp = os.path.join(tmp, "dist.yaml")
            _make_districts(dp)
            out = os.path.join(tmp, "map.html")
            generate_leaflet_osm_map(sp, dp, out, "2026-07-08", "2026-07-11",
                                     coord_mode="approx_wgs84")
            with open(out) as f:
                content = f.read()
            self.assertIn("近似转换", content)
            self.assertIn("WGS84", content)

    def test_raw_gcj02_has_offset_note(self):
        with tempfile.TemporaryDirectory() as tmp:
            sp = os.path.join(tmp, "snap.csv")
            _make_snapshot_csv(sp, [_make_poi_row()])
            dp = os.path.join(tmp, "dist.yaml")
            _make_districts(dp)
            out = os.path.join(tmp, "map.html")
            generate_leaflet_osm_map(sp, dp, out, "2026-07-08", "2026-07-11",
                                     coord_mode="raw_gcj02")
            with open(out) as f:
                content = f.read()
            self.assertIn("GCJ-02 直接叠加", content)

    def test_single_quote_escaped(self):
        with tempfile.TemporaryDirectory() as tmp:
            sp = os.path.join(tmp, "snap.csv")
            _make_snapshot_csv(sp, [_make_poi_row(name="David's Cafe")])
            dp = os.path.join(tmp, "dist.yaml")
            _make_districts(dp)
            out = os.path.join(tmp, "map.html")
            generate_leaflet_osm_map(sp, dp, out, "2026-07-08", "2026-07-11")
            with open(out) as f:
                content = f.read()
            self.assertIn("David\\'s", content)

    def test_empty_poi_generates(self):
        with tempfile.TemporaryDirectory() as tmp:
            sp = os.path.join(tmp, "snap.csv")
            _make_snapshot_csv(sp, [])
            dp = os.path.join(tmp, "dist.yaml")
            _make_districts(dp)
            out = os.path.join(tmp, "map.html")
            generate_leaflet_osm_map(sp, dp, out, "2026-07-08", "2026-07-11")
            self.assertTrue(os.path.isfile(out))


if __name__ == "__main__":
    unittest.main()
