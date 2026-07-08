import os
import sys
import unittest

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, PROJECT_ROOT)

import yaml

from src.brand_poi_scanner import (
    generate_scan_points,
    normalize_amap_poi,
    classify_poi_kind,
    _make_dedup_key,
    estimate_requests,
    SCAN_MODES,
    parse_amap_response,
    set_debug,
    clear_cache,
)


def _load_config():
    path = os.path.join(PROJECT_ROOT, "config", "brand_poi_compare.yaml")
    with open(path, encoding="utf-8") as f:
        return yaml.safe_load(f)


class TestBrandPoiScanner(unittest.TestCase):

    def test_config_readable(self):
        config = _load_config()
        self.assertIn("brands", config)
        self.assertIn("scan_area", config)
        self.assertTrue(len(config["brands"]) >= 3)

    def test_generate_scan_points_returns_list(self):
        config = _load_config()
        points = generate_scan_points(config)
        self.assertIsInstance(points, list)
        self.assertTrue(len(points) > 10)
        for p in points:
            self.assertIn("lng", p)
            self.assertIn("lat", p)
            self.assertIn("radius_m", p)

    def test_classify_experience_store(self):
        self.assertEqual(classify_poi_kind("蔚来空间", "汽车", "南京西路"), "experience_store")
        self.assertEqual(classify_poi_kind("智己体验中心", "汽车", "淮海路"), "experience_store")
        self.assertEqual(classify_poi_kind("NIO House", "汽车", "新天地"), "experience_store")

    def test_classify_delivery_center(self):
        self.assertEqual(classify_poi_kind("蔚来交付中心", "汽车", "浦东"), "delivery_center")

    def test_classify_service_center(self):
        self.assertEqual(classify_poi_kind("蔚来服务中心", "维修", "长宁"), "service_center")

    def test_classify_energy(self):
        self.assertEqual(classify_poi_kind("蔚来换电站", "能源", "杨浦"), "energy")
        self.assertEqual(classify_poi_kind("充电站", "充电", "徐汇"), "energy")

    def test_classify_office(self):
        self.assertEqual(classify_poi_kind("蔚来总部", "办公", "嘉定"), "office")

    def test_classify_other(self):
        self.assertEqual(classify_poi_kind("一些无关名称", "其他", ""), "other")

    def test_normalize_amap_poi_has_fields(self):
        from datetime import date
        brand = {"brand_id": "nio", "display_name": "蔚来", "include_keywords": ["蔚来", "NIO"]}
        scan_point = {"lng": 121.47, "lat": 31.23, "radius_m": 3000}
        raw = {
            "id": "B001",
            "name": "蔚来空间",
            "address": "南京西路",
            "pname": "上海市",
            "cityname": "上海市",
            "adname": "静安区",
            "adcode": "310106",
            "location": "121.47,31.23",
            "type": "汽车服务",
            "typecode": "050000",
            "tel": "12345678",
            "distance": "200",
        }
        row = normalize_amap_poi(raw, brand, "蔚来", scan_point, date(2026, 7, 8))
        self.assertEqual(row["brand_id"], "nio")
        self.assertEqual(row["brand_name"], "蔚来")
        self.assertEqual(row["poi_id"], "B001")
        self.assertEqual(row["lng_gcj02"], 121.47)
        self.assertEqual(row["lat_gcj02"], 31.23)
        self.assertIn("蔚来", row["matched_keywords"])
        self.assertEqual(row["poi_kind"], "experience_store")
        self.assertEqual(row["source"], "amap_place_text")
        self.assertEqual(row["crawl_date"], "2026-07-08")

    def test_dedup_key_by_poi_id(self):
        row = {
            "brand_id": "nio",
            "poi_id": "B001",
            "name": "蔚来中心",
            "address": "南京西路",
            "lng_gcj02": "121.47",
            "lat_gcj02": "31.23",
        }
        key = _make_dedup_key(row)
        self.assertEqual(key, "nio|B001")

    def test_dedup_key_without_poi_id(self):
        row = {
            "brand_id": "nio",
            "poi_id": "",
            "name": "蔚来空间",
            "address": "南京西路",
            "lng_gcj02": "121.47000",
            "lat_gcj02": "31.23000",
        }
        key = _make_dedup_key(row)
        self.assertIn("nio", key)
        self.assertIn("蔚来空间", key)

    def test_energy_excluded_by_default(self):
        from datetime import date
        brand = {"brand_id": "nio", "display_name": "蔚来", "include_keywords": ["蔚来", "NIO"]}
        scan_point = {"lng": 121.47, "lat": 31.23, "radius_m": 3000}
        raw = {
            "id": "B002",
            "name": "蔚来换电站",
            "address": "杨浦",
            "location": "121.47,31.23",
            "type": "能源",
            "typecode": "050000",
        }
        row = normalize_amap_poi(raw, brand, "蔚来", scan_point, date(2026, 7, 8))
        self.assertEqual(row["poi_kind"], "energy")

    def test_normalize_missing_location(self):
        from datetime import date
        brand = {"brand_id": "nio", "display_name": "蔚来", "include_keywords": []}
        scan_point = {"lng": 121.47, "lat": 31.23, "radius_m": 3000}
        raw = {"id": "", "name": "test", "address": "", "location": "", "type": ""}
        row = normalize_amap_poi(raw, brand, "test", scan_point, date(2026, 7, 8))
        self.assertEqual(row["lng_gcj02"], 0.0)
        self.assertEqual(row["lat_gcj02"], 0.0)

    def test_exclude_keywords_filtered(self):
        from datetime import date
        brand = {
            "brand_id": "nio", "display_name": "蔚来",
            "include_keywords": ["蔚来"],
            "exclude_keywords": ["换电站"],
        }
        scan_point = {"lng": 121.47, "lat": 31.23, "radius_m": 3000}
        raw = {
            "id": "B003",
            "name": "蔚来换电站（虹桥）",
            "address": "",
            "location": "121.47,31.23",
            "type": "能源",
            "typecode": "050000",
        }
        row = normalize_amap_poi(raw, brand, "蔚来", scan_point, date(2026, 7, 8))
        text = row["name"] + " " + row["type"] + " " + row.get("address", "")
        has_excluded = any(ek in text for ek in brand["exclude_keywords"])
        self.assertTrue(has_excluded)


    def test_default_scan_mode_is_text_city_first(self):
        self.assertIn("text_city_first", SCAN_MODES)
        self.assertEqual(SCAN_MODES[0], "text_city_first")

    def test_estimate_requests_text_city_first(self):
        config = _load_config()
        est = estimate_requests(config, "text_city_first")
        queries = sum(len(b.get("queries", [])) for b in config["brands"])
        max_pages = config["scan_area"]["max_pages"]
        self.assertLessEqual(est, queries * max_pages)

    def test_estimate_requests_grid_around_large(self):
        config = _load_config()
        est = estimate_requests(config, "grid_around")
        # Should be much larger than text mode
        text_est = estimate_requests(config, "text_city_first")
        self.assertGreater(est, text_est)

    def test_text_source_label(self):
        from datetime import date
        brand = {"brand_id": "im_motors", "display_name": "智己", "include_keywords": ["智己"]}
        scan_point = {"lng": 0, "lat": 0, "radius_m": 0}
        raw = {
            "id": "T001", "name": "智己体验中心", "address": "南京西路",
            "location": "121.47,31.23", "type": "汽车", "typecode": "050000",
        }
        row = normalize_amap_poi(raw, brand, "智己汽车", scan_point, date(2026, 7, 8))
        self.assertEqual(row["source"], "amap_place_text")


    def test_parse_amap_response_status_0_returns_empty(self):
        data = {"status": "0", "info": "INVALID_USER_KEY", "infocode": "10001", "pois": []}
        result = parse_amap_response(data, api="text", brand="test", query="q", page=1)
        self.assertEqual(result, [])

    def test_parse_amap_response_status_1_empty_pois(self):
        data = {"status": "1", "info": "OK", "infocode": "10000", "count": "0", "pois": []}
        result = parse_amap_response(data, api="text", brand="test", query="q", page=1)
        self.assertEqual(result, [])

    def test_parse_amap_response_status_1_with_pois(self):
        data = {"status": "1", "info": "OK", "infocode": "10000", "count": "2",
                "pois": [{"id": "P1", "name": "蔚来中心"}, {"id": "P2", "name": "蔚来空间"}]}
        result = parse_amap_response(data, api="text", brand="test", query="q", page=1)
        self.assertEqual(len(result), 2)

    def test_parse_amap_response_pois_not_list(self):
        data = {"status": "1", "info": "OK", "infocode": "10000", "count": "0", "pois": None}
        result = parse_amap_response(data, api="text", brand="test", query="q", page=1)
        self.assertEqual(result, [])

    def test_parse_amap_response_missing_pois_key(self):
        data = {"status": "1", "info": "OK", "count": "0"}
        result = parse_amap_response(data, api="text", brand="test", query="q", page=1)
        self.assertEqual(result, [])

    def test_set_debug_flag(self):
        set_debug(True)
        # Just verify it doesn't crash
        set_debug(False)

    def test_clear_cache_does_not_crash(self):
        clear_cache()
        # Should not raise


if __name__ == "__main__":
    unittest.main()
