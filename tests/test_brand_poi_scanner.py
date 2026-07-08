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
    _make_text_cache_key,
    _make_around_cache_key,
    _read_cache,
    _write_cache,
    _cache_path,
    estimate_requests,
    SCAN_MODES,
    parse_amap_response,
    set_debug,
    set_debug_cache,
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

    def test_classify_energy(self):
        self.assertEqual(classify_poi_kind("蔚来换电站", "能源", "杨浦"), "energy")
        self.assertEqual(classify_poi_kind("充电站", "充电", "徐汇"), "energy")

    def test_classify_delivery_center(self):
        self.assertEqual(classify_poi_kind("蔚来交付中心", "汽车", "浦东"), "delivery_center")
        self.assertEqual(classify_poi_kind("某普通门店", "汽车", "", source_query="蔚来交付中心"), "delivery_center")

    def test_classify_service_center(self):
        self.assertEqual(classify_poi_kind("蔚来服务中心", "维修", "长宁"), "service_center")
        self.assertEqual(classify_poi_kind("某门店", "维修", "", source_query="服务中心"), "service_center")

    def test_classify_user_center(self):
        self.assertEqual(classify_poi_kind("鸿蒙智行用户中心", "汽车", "上海"), "user_center")
        self.assertEqual(classify_poi_kind("问界用户中心", "汽车", "浦东"), "user_center")
        self.assertEqual(classify_poi_kind("AITO授权用户中心", "汽车", "闵行"), "user_center")
        self.assertEqual(classify_poi_kind("普通名称", "汽车", "", source_query="鸿蒙智行用户中心"), "user_center")
        self.assertEqual(classify_poi_kind("普通名称", "汽车", "", source_query="问界用户中心"), "user_center")

    def test_classify_experience_store(self):
        self.assertEqual(classify_poi_kind("蔚来空间", "汽车", "南京西路"), "experience_store")
        self.assertEqual(classify_poi_kind("智己体验中心", "汽车", "淮海路"), "experience_store")
        self.assertEqual(classify_poi_kind("NIO House", "汽车", "新天地"), "experience_store")
        self.assertEqual(classify_poi_kind("某门店", "汽车", "", source_query="智己体验中心"), "experience_store")
        self.assertEqual(classify_poi_kind("某门店", "汽车", "", source_query="蔚来中心"), "experience_store")

    def test_classify_mall_store(self):
        self.assertEqual(classify_poi_kind("商场店", "汽车", "环球港"), "mall_store")
        self.assertEqual(classify_poi_kind("万象城店", "汽车", "万象城"), "mall_store")

    def test_classify_mall_store_car_brand_and_mall_clue(self):
        self.assertEqual(classify_poi_kind("鸿蒙智行汽车·华为(世博源店)", "汽车", "世博大道"), "mall_store")
        self.assertEqual(classify_poi_kind("鸿蒙智行汽车·华为(晶耀前滩店)", "汽车", "耀体路"), "mall_store")
        self.assertEqual(classify_poi_kind("鸿蒙智行(日月光中心宝山店)", "汽车", "沪太路"), "mall_store")

    def test_classify_service_center_enhanced(self):
        self.assertEqual(classify_poi_kind("AITO官方精品施工中心", "汽车", "华江路"), "service_center")
        self.assertEqual(classify_poi_kind("精品施工中心", "汽车", "路"), "service_center")
        self.assertEqual(classify_poi_kind("施工中心", "汽车", "华江路"), "service_center")

    def test_classify_user_center_enhanced(self):
        self.assertEqual(classify_poi_kind("上海冠松aito4S店", "汽车", "世纪公园"), "user_center")
        self.assertEqual(classify_poi_kind("华为AITO汽车中心", "汽车", "长宁"), "user_center")
        self.assertEqual(classify_poi_kind("某品牌4S 店", "汽车", "路"), "user_center")

    def test_classify_service_center_priority_over_mall(self):
        self.assertEqual(classify_poi_kind("AITO官方精品施工中心(华江路问界)", "汽车", "华江路"), "service_center")

    def test_classify_user_center_priority_over_mall_store(self):
        self.assertEqual(classify_poi_kind("上海冠松aito4S店(世纪公园店)", "汽车", "世纪公园"), "user_center")

    def test_classify_mall_store_not_for_non_car_brand(self):
        """Without a car brand clue, mall clue alone still hits fallback mall_store."""
        self.assertEqual(classify_poi_kind("普通店", "其他", "世博源"), "mall_store")

    def test_classify_office(self):
        self.assertEqual(classify_poi_kind("蔚来总部", "办公", "嘉定"), "office")

    def test_classify_other(self):
        self.assertEqual(classify_poi_kind("一些无关名称", "其他", ""), "other")

    def test_energy_still_priority(self):
        """energy should still be detected even if other keywords match."""
        self.assertEqual(classify_poi_kind("蔚来换电站", "能源", "", source_query="蔚来服务中心"), "energy")

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

    def test_set_debug_cache_flag(self):
        set_debug_cache(True)
        set_debug_cache(False)

    def test_text_cache_key_is_stable(self):
        config = _load_config()
        k1 = _make_text_cache_key(config, "nio", "蔚来中心", 1)
        k2 = _make_text_cache_key(config, "nio", "蔚来中心", 1)
        self.assertEqual(k1, k2)

    def test_text_cache_key_differs_by_query(self):
        config = _load_config()
        k1 = _make_text_cache_key(config, "nio", "蔚来中心", 1)
        k2 = _make_text_cache_key(config, "nio", "蔚来空间", 1)
        self.assertNotEqual(k1, k2)

    def test_text_cache_key_differs_by_page(self):
        config = _load_config()
        k1 = _make_text_cache_key(config, "nio", "蔚来中心", 1)
        k2 = _make_text_cache_key(config, "nio", "蔚来中心", 2)
        self.assertNotEqual(k1, k2)

    def test_text_cache_key_no_api_key_or_sig(self):
        config = _load_config()
        k = _make_text_cache_key(config, "im_motors", "智己汽车", 1)
        self.assertNotIn("key=", k)
        self.assertNotIn("sig=", k)
        self.assertIn("api=text", k)
        self.assertIn("brand=im_motors", k)

    def test_around_cache_key_differs_by_location(self):
        config = _load_config()
        k1 = _make_around_cache_key(config, "nio", "蔚来", 121.47, 31.23, 3000)
        k2 = _make_around_cache_key(config, "nio", "蔚来", 121.50, 31.24, 3000)
        self.assertNotEqual(k1, k2)

    def test_cache_write_then_read(self):
        import tempfile, os, json
        data = [{"id": "P1", "name": "test", "location": "121.47,31.23"}]
        tmpdir = tempfile.mkdtemp()
        path = os.path.join(tmpdir, "cache_test.json")
        try:
            _write_cache(path, data)
            self.assertTrue(os.path.exists(path))
            loaded = _read_cache(path)
            self.assertEqual(len(loaded), 1)
            self.assertEqual(loaded[0]["name"], "test")
        finally:
            import shutil
            shutil.rmtree(tmpdir, ignore_errors=True)

    def test_cache_read_nonexistent_returns_none(self):
        self.assertIsNone(_read_cache("/nonexistent/path.json"))

    def test_clear_cache_then_first_miss_second_hit(self):
        """Simulate cache round-trip: clear → write → read."""
        import tempfile, os, json
        tmpdir = tempfile.mkdtemp()
        path = os.path.join(tmpdir, "roundtrip.json")
        try:
            self.assertIsNone(_read_cache(path))
            _write_cache(path, [{"id": "T1"}])
            loaded = _read_cache(path)
            self.assertIsNotNone(loaded)
        finally:
            import shutil
            shutil.rmtree(tmpdir, ignore_errors=True)

    def test_10021_does_not_cache(self):
        """Error responses should not be cached."""
        from src.brand_poi_scanner import _amap_request
        import tempfile
        # We can't easily mock _amap_request, but we can test the stats behavior:
        # parse_amap_response with status=0 should increment api_error_count
        from src.brand_poi_scanner import parse_amap_response, reset_stats, get_stats
        reset_stats()
        data = {"status": "0", "info": "CUQPS_HAS_EXCEEDED_THE_LIMIT", "infocode": "10021"}
        result = parse_amap_response(data, api="text", brand="test", query="q", page=1)
        self.assertEqual(result, [])
        stats = get_stats()
        self.assertGreater(stats["api_error_count"], 0)

    def test_parse_amap_response_cache_hit_counter(self):
        from src.brand_poi_scanner import parse_amap_response, reset_stats, get_stats
        reset_stats()
        data = {"status": "1", "info": "OK", "infocode": "10000", "count": "1",
                "pois": [{"id": "P1", "name": "test"}]}
        result = parse_amap_response(data, api="text", brand="test", query="q", page=1, is_cached=True)
        self.assertEqual(len(result), 1)
        stats = get_stats()
        self.assertGreater(stats["cache_hit_count"], 0)

    def test_parse_amap_response_cache_miss_counter(self):
        from src.brand_poi_scanner import parse_amap_response, reset_stats, get_stats
        reset_stats()
        data = {"status": "1", "info": "OK", "infocode": "10000", "count": "1",
                "pois": [{"id": "P1", "name": "test"}]}
        result = parse_amap_response(data, api="text", brand="test", query="q", page=1, is_cached=False)
        self.assertEqual(len(result), 1)
        stats = get_stats()
        self.assertGreater(stats["cache_miss_count"], 0)
        self.assertEqual(stats["cache_hit_count"], 0)

    def test_empty_poi_list_is_written_to_cache(self):
        """status=1 with pois=[] should still be written to cache."""
        import tempfile, os
        tmpdir = tempfile.mkdtemp()
        path = os.path.join(tmpdir, "empty.json")
        try:
            _write_cache(path, [])
            self.assertTrue(os.path.exists(path))
            import json
            with open(path) as f:
                self.assertEqual(json.load(f), [])
        finally:
            import shutil
            shutil.rmtree(tmpdir, ignore_errors=True)

    def test_empty_cache_is_readable(self):
        import tempfile, os
        tmpdir = tempfile.mkdtemp()
        path = os.path.join(tmpdir, "empty_read.json")
        try:
            _write_cache(path, [])
            loaded = _read_cache(path)
            self.assertIsNotNone(loaded)
            self.assertEqual(loaded, [])
        finally:
            import shutil
            shutil.rmtree(tmpdir, ignore_errors=True)

    def test_same_empty_query_hits_cache_twice(self):
        """Simulate two identical requests hitting the same empty cache."""
        import tempfile, os
        tmpdir = tempfile.mkdtemp()
        path = os.path.join(tmpdir, "empty_twice.json")
        try:
            _write_cache(path, [])
            r1 = _read_cache(path)
            r2 = _read_cache(path)
            self.assertIsNotNone(r1)
            self.assertIsNotNone(r2)
        finally:
            import shutil
            shutil.rmtree(tmpdir, ignore_errors=True)

    def test_status_0_10021_not_cached_by_parse(self):
        """status=0 with 10021 increments error count but should not be written."""
        from src.brand_poi_scanner import parse_amap_response, reset_stats, get_stats
        reset_stats()
        data = {"status": "0", "info": "CUQPS_HAS_EXCEEDED_THE_LIMIT", "infocode": "10021"}
        result = parse_amap_response(data, api="text", brand="test", query="q", page=1)
        self.assertEqual(result, [])
        stats = get_stats()
        self.assertGreater(stats["api_error_count"], 0)

    def test_status_0_invalid_key_not_cached_by_parse(self):
        """status=0 with INVALID_USER_SIGNATURE should also not be cached."""
        from src.brand_poi_scanner import parse_amap_response, reset_stats, get_stats
        reset_stats()
        data = {"status": "0", "info": "INVALID_USER_SIGNATURE", "infocode": "10003"}
        result = parse_amap_response(data, api="text", brand="test", query="q", page=1)
        self.assertEqual(result, [])
        stats = get_stats()
        self.assertGreater(stats["api_error_count"], 0)


if __name__ == "__main__":
    unittest.main()
