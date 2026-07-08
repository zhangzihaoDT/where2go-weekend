import os
import sys
import unittest
import tempfile
from datetime import date

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, PROJECT_ROOT)

from src.brand_poi_map_writer import (
    generate_brand_poi_map,
    generate_brand_poi_report,
)


SAMPLE_POI = [
    {
        "brand_id": "im_motors",
        "brand_name": "智己",
        "poi_id": "B001",
        "name": "智己体验中心",
        "address": "南京西路",
        "province": "上海市",
        "city": "上海市",
        "district": "静安区",
        "lng_gcj02": 121.47,
        "lat_gcj02": 31.23,
        "type": "汽车",
        "typecode": "050000",
        "tel": "",
        "source_query": "智己汽车",
        "matched_keywords": "智己",
        "poi_kind": "experience_store",
        "crawl_date": "2026-07-08",
    },
    {
        "brand_id": "nio",
        "brand_name": "蔚来",
        "poi_id": "B002",
        "name": "蔚来中心",
        "address": "淮海路",
        "province": "上海市",
        "city": "上海市",
        "district": "黄浦区",
        "lng_gcj02": 121.48,
        "lat_gcj02": 31.22,
        "type": "汽车",
        "typecode": "050000",
        "tel": "",
        "source_query": "蔚来",
        "matched_keywords": "蔚来",
        "poi_kind": "experience_store",
        "crawl_date": "2026-07-08",
    },
    {
        "brand_id": "harmony_auto",
        "brand_name": "鸿蒙智行",
        "poi_id": "B003",
        "name": "鸿蒙智行用户中心",
        "address": "浦东新区",
        "province": "上海市",
        "city": "上海市",
        "district": "浦东新区",
        "lng_gcj02": 121.55,
        "lat_gcj02": 31.25,
        "type": "汽车",
        "typecode": "050000",
        "tel": "",
        "source_query": "鸿蒙智行",
        "matched_keywords": "鸿蒙智行",
        "poi_kind": "delivery_center",
        "crawl_date": "2026-07-08",
    },
]


class TestBrandPoiMapWriter(unittest.TestCase):

    def test_generate_map_html(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            out = os.path.join(tmpdir, "map.html")
            generate_brand_poi_map(
                poi_rows=SAMPLE_POI,
                output_path=out,
                crawl_date=date(2026, 7, 8),
                city="上海",
                api_key_available=True,
                has_js_key=True,
                has_sec_code=True,
                js_key="test_key",
                sec_code="test_code",
            )
            self.assertTrue(os.path.isfile(out))
            with open(out, encoding="utf-8") as f:
                content = f.read()
            self.assertIn("AMap.Map", content)
            self.assertIn("智己", content)
            self.assertIn("蔚来", content)
            self.assertIn("鸿蒙智行", content)
            self.assertIn("GCJ-02", content)
            self.assertIn("AMapSecurityConfig", content)
            self.assertIn("test_key", content)

    def test_generate_map_no_key(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            out = os.path.join(tmpdir, "map.html")
            generate_brand_poi_map(
                poi_rows=[],
                output_path=out,
                crawl_date=date(2026, 7, 8),
                city="上海",
                api_key_available=False,
                has_js_key=False,
                has_sec_code=False,
            )
            self.assertTrue(os.path.isfile(out))
            with open(out, encoding="utf-8") as f:
                content = f.read()
            self.assertIn("AMap.Map", content)
            self.assertIn("缺少 AMAP_API_KEY", content)
            self.assertIn("NO_KEY", content)

    def test_generate_map_no_js_key(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            out = os.path.join(tmpdir, "map.html")
            generate_brand_poi_map(
                poi_rows=SAMPLE_POI,
                output_path=out,
                crawl_date=date(2026, 7, 8),
                city="上海",
                api_key_available=True,
                has_js_key=False,
                has_sec_code=False,
            )
            with open(out, encoding="utf-8") as f:
                content = f.read()
            self.assertIn("缺少 AMAP_JS_API_KEY", content)

    def test_generate_map_has_brand_names(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            out = os.path.join(tmpdir, "map.html")
            generate_brand_poi_map(
                poi_rows=SAMPLE_POI,
                output_path=out,
                crawl_date=date(2026, 7, 8),
                city="上海",
                api_key_available=True,
                has_js_key=True,
                has_sec_code=True,
                js_key="k",
                sec_code="s",
            )
            with open(out, encoding="utf-8") as f:
                content = f.read()
            self.assertIn("im_motors", content)
            self.assertIn("nio", content)
            self.assertIn("harmony_auto", content)

    def test_generate_report(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            out = os.path.join(tmpdir, "report.md")
            generate_brand_poi_report(
                poi_rows=SAMPLE_POI,
                output_path=out,
                crawl_date=date(2026, 7, 8),
                city="上海",
                csv_path="/tmp/test.csv",
                json_path="/tmp/test.json",
                map_path="/tmp/map.html",
            )
            self.assertTrue(os.path.isfile(out))
            with open(out, encoding="utf-8") as f:
                content = f.read()
            self.assertIn("数据概览", content)
            self.assertIn("区县分布", content)
            self.assertIn("智己", content)
            self.assertIn("蔚来", content)
            self.assertIn("鸿蒙智行", content)
            self.assertIn("静安区", content)
            self.assertIn("黄浦区", content)


if __name__ == "__main__":
    unittest.main()
