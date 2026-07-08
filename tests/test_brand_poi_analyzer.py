import csv
import json
import os
import sys
import tempfile
import unittest
from io import StringIO

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, PROJECT_ROOT)

from src.brand_poi_analyzer import (
    haversine_km,
    is_frontend_store,
    is_after_sales,
    is_delivery,
    is_core_touchpoint,
    needs_review_check,
    re_classify_poi_kind,
    classify_store_location_type,
    enrich_rows,
    compute_aggregates,
    add_stat_fields,
    build_summary,
    compute_nearest_neighbor,
    read_csv,
    check_required_columns,
    parse_args,
    resolve_paths,
    write_enriched_csv,
    write_summary_json,
    write_markdown_report,
    BRANDS_OF_INTEREST,
    REQUIRED_COLUMNS,
)


def make_mock_rows():
    """Return 14 mock POI rows for testing, covering enhanced classification scenarios."""
    return [
        {"brand_id": "im_motors", "brand_name": "智己", "name": "智己汽车体验中心",
         "address": "南京西路", "district": "静安区", "lng_gcj02": "121.45",
         "lat_gcj02": "31.23", "poi_kind": "experience_store", "source_query": "智己汽车",
         "type": "汽车销售", "tel": ""},
        {"brand_id": "im_motors", "brand_name": "智己", "name": "智己服务中心",
         "address": "浦东大道", "district": "浦东新区", "lng_gcj02": "121.55",
         "lat_gcj02": "31.25", "poi_kind": "service_center", "source_query": "智己汽车",
         "type": "汽车维修", "tel": ""},
        {"brand_id": "im_motors", "brand_name": "智己", "name": "智己交付中心",
         "address": "普陀路", "district": "普陀区", "lng_gcj02": "121.40",
         "lat_gcj02": "31.24", "poi_kind": "delivery_center", "source_query": "智己汽车",
         "type": "汽车销售", "tel": ""},
        {"brand_id": "nio", "brand_name": "蔚来", "name": "蔚来中心",
         "address": "南京西路", "district": "静安区", "lng_gcj02": "121.46",
         "lat_gcj02": "31.23", "poi_kind": "experience_store", "source_query": "蔚来",
         "type": "汽车服务", "tel": ""},
        {"brand_id": "nio", "brand_name": "蔚来", "name": "蔚来服务中心",
         "address": "杨树浦路", "district": "杨浦区", "lng_gcj02": "121.52",
         "lat_gcj02": "31.27", "poi_kind": "service_center", "source_query": "蔚来",
         "type": "汽车维修", "tel": ""},
        {"brand_id": "nio", "brand_name": "蔚来", "name": "蔚来交付中心",
         "address": "嘉定工业区", "district": "嘉定区", "lng_gcj02": "121.26",
         "lat_gcj02": "31.38", "poi_kind": "delivery_center", "source_query": "蔚来",
         "type": "汽车销售", "tel": ""},
        {"brand_id": "hms", "brand_name": "鸿蒙智行", "name": "鸿蒙智行用户中心",
         "address": "吴中路", "district": "闵行区", "lng_gcj02": "121.38",
         "lat_gcj02": "31.16", "poi_kind": "user_center", "source_query": "鸿蒙智行",
         "type": "汽车销售", "tel": ""},
        {"brand_id": "hms", "brand_name": "鸿蒙智行", "name": "鸿蒙智行体验中心",
         "address": "中山北路", "district": "普陀区", "lng_gcj02": "121.41",
         "lat_gcj02": "31.25", "poi_kind": "experience_store", "source_query": "鸿蒙智行",
         "type": "汽车销售", "tel": ""},
        {"brand_id": "hms", "brand_name": "鸿蒙智行", "name": "华为智能生活馆",
         "address": "世纪大道", "district": "浦东新区", "lng_gcj02": "121.53",
         "lat_gcj02": "31.23", "poi_kind": "other", "source_query": "鸿蒙智行",
         "type": "手机数码", "tel": ""},
        {"brand_id": "hms", "brand_name": "鸿蒙智行", "name": "鸿蒙智行超充站",
         "address": "龙阳路", "district": "浦东新区", "lng_gcj02": "121.54",
         "lat_gcj02": "31.21", "poi_kind": "other", "source_query": "鸿蒙智行",
         "type": "充电站", "tel": ""},
        {"brand_id": "hms", "brand_name": "鸿蒙智行", "name": "鸿蒙智行汽车·华为(世博源店)",
         "address": "世博大道1368号", "district": "浦东新区", "lng_gcj02": "121.50",
         "lat_gcj02": "31.19", "poi_kind": "other", "source_query": "鸿蒙智行",
         "type": "汽车销售", "tel": ""},
        {"brand_id": "hms", "brand_name": "鸿蒙智行", "name": "AITO官方精品施工中心(华江路问界)",
         "address": "华江路", "district": "嘉定区", "lng_gcj02": "121.33",
         "lat_gcj02": "31.28", "poi_kind": "other", "source_query": "AITO",
         "type": "汽车维修", "tel": ""},
        {"brand_id": "hms", "brand_name": "鸿蒙智行", "name": "上海冠松aito4S店(世纪公园店)",
         "address": "锦绣东路", "district": "浦东新区", "lng_gcj02": "121.55",
         "lat_gcj02": "31.22", "poi_kind": "other", "source_query": "AITO",
         "type": "汽车销售", "tel": ""},
        {"brand_id": "hms", "brand_name": "鸿蒙智行", "name": "重庆问界汽车销售有限公司",
         "address": "九干路", "district": "松江区", "lng_gcj02": "121.30",
         "lat_gcj02": "31.05", "poi_kind": "other", "source_query": "问界",
         "type": "汽车销售", "tel": ""},
    ]


def write_mock_csv(rows, path):
    if not rows:
        with open(path, "w", encoding="utf-8", newline="") as f:
            f.write("brand_id,brand_name,name,district,lng_gcj02,lat_gcj02,poi_kind,source_query,address,type,tel\n")
        return
    fieldnames = list(rows[0].keys())
    with open(path, "w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)


class TestHaversine(unittest.TestCase):

    def test_haversine_known_distance(self):
        # Shanghai People's Square to Lujiazui ~ 2.5km
        d = haversine_km(121.475, 31.230, 121.500, 31.240)
        self.assertAlmostEqual(d, 2.38, delta=0.5)

    def test_haversine_same_point(self):
        d = haversine_km(121.47, 31.23, 121.47, 31.23)
        self.assertEqual(d, 0.0)

    def test_haversine_zero_coords(self):
        d = haversine_km(0, 0, 0, 0)
        self.assertEqual(d, 0.0)


class TestReadCsv(unittest.TestCase):

    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()
        self.csv_path = os.path.join(self.tmpdir, "test.csv")

    def tearDown(self):
        import shutil
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def test_read_csv_returns_rows(self):
        write_mock_csv(make_mock_rows(), self.csv_path)
        rows = read_csv(self.csv_path)
        self.assertEqual(len(rows), 14)

    def test_read_empty_csv(self):
        write_mock_csv([], self.csv_path)
        rows = read_csv(self.csv_path)
        self.assertEqual(len(rows), 0)


class TestRequiredColumns(unittest.TestCase):

    def test_missing_required_columns_raises(self):
        row = {"brand_id": "1", "name": "test"}
        with self.assertRaises(SystemExit):
            check_required_columns([row])

    def test_all_columns_present_passes(self):
        row = {c: "" for c in REQUIRED_COLUMNS}
        check_required_columns([row])

    def test_empty_rows_skips_check(self):
        check_required_columns([])


class TestPoiKindClassification(unittest.TestCase):

    def test_is_frontend_store_experience(self):
        row = {"poi_kind": "experience_store"}
        self.assertTrue(is_frontend_store(row))

    def test_is_frontend_store_user_center(self):
        row = {"poi_kind": "user_center"}
        self.assertTrue(is_frontend_store(row))

    def test_is_frontend_store_mall_store(self):
        row = {"poi_kind": "mall_store"}
        self.assertTrue(is_frontend_store(row))

    def test_is_frontend_store_service_center_false(self):
        row = {"poi_kind": "service_center"}
        self.assertFalse(is_frontend_store(row))

    def test_is_frontend_store_other_false(self):
        row = {"poi_kind": "other"}
        self.assertFalse(is_frontend_store(row))

    def test_is_after_sales_service_center(self):
        row = {"poi_kind": "service_center"}
        self.assertTrue(is_after_sales(row))

    def test_is_after_sales_experience_false(self):
        row = {"poi_kind": "experience_store"}
        self.assertFalse(is_after_sales(row))

    def test_is_delivery_center(self):
        row = {"poi_kind": "delivery_center"}
        self.assertTrue(is_delivery(row))

    def test_is_delivery_other_false(self):
        row = {"poi_kind": "other"}
        self.assertFalse(is_delivery(row))

    def test_is_core_touchpoint(self):
        for kind in ["experience_store", "user_center", "mall_store",
                      "service_center", "delivery_center"]:
            row = {"poi_kind": kind}
            self.assertTrue(is_core_touchpoint(row))

    def test_is_core_touchpoint_other_false(self):
        row = {"poi_kind": "other"}
        self.assertFalse(is_core_touchpoint(row))


class TestClassifyStoreLocationType(unittest.TestCase):

    def test_mall_keywords(self):
        self.assertEqual(classify_store_location_type("某店", "南京路某广场", "汽车"), "mall")
        self.assertEqual(classify_store_location_type("某店(万象城)", "路", "汽车"), "mall")
        self.assertEqual(classify_store_location_type("某店", "世博大道", "购物中心"), "mall")

    def test_auto_park(self):
        self.assertEqual(classify_store_location_type("某店", "汽车城", "汽车"), "auto_park")
        self.assertEqual(classify_store_location_type("某店", "", "汽车产业园"), "auto_park")

    def test_industrial_or_service_site(self):
        self.assertEqual(classify_store_location_type("维修中心", "路", "维修"), "industrial_or_service_site")
        self.assertEqual(classify_store_location_type("某店", "仓库", "汽车"), "industrial_or_service_site")

    def test_office_or_entity(self):
        self.assertEqual(classify_store_location_type("上海某公司", "路", "汽车"), "office_or_entity")
        self.assertEqual(classify_store_location_type("某有限公司", "写字楼", "汽车"), "office_or_entity")

    def test_road_address_store(self):
        self.assertEqual(classify_store_location_type("某店", "南京路100号", "汽车"), "road_address_store")
        self.assertEqual(classify_store_location_type("某店", "淮海西路", "汽车"), "road_address_store")

    def test_unknown(self):
        self.assertEqual(classify_store_location_type("测试", "", ""), "unknown")

    def test_office_priority_over_street(self):
        """office keywords checked before road_address_store, should take priority."""
        self.assertEqual(classify_store_location_type("上海某有限公司", "南京路100号", "汽车"), "office_or_entity")

    def test_enhanced_mall_wanda(self):
        self.assertEqual(classify_store_location_type("蔚来城市展厅(中信泰富万达)", "南京路", "汽车"), "mall")

    def test_enhanced_mall_taihe(self):
        self.assertEqual(classify_store_location_type("蔚来中心(上海兴业太古汇)", "南京西路", "汽车"), "mall")

    def test_enhanced_mall_wanxiangtiandi(self):
        self.assertEqual(classify_store_location_type("蔚来中心(上海苏河湾万象天地)", "路", "汽车"), "mall")

    def test_enhanced_mall_longzhimeng(self):
        self.assertEqual(classify_store_location_type("鸿蒙智行体验中心·上海中山公园龙之梦", "路", "汽车"), "mall")

    def test_enhanced_mall_bfc(self):
        self.assertEqual(classify_store_location_type("鸿蒙智行尊界体验中心·上海BFC外滩金融中心店", "中山东二路", "汽车"), "mall")

    def test_enhanced_mall_airport(self):
        self.assertEqual(classify_store_location_type("蔚来中心(上海虹桥国际机场)", "虹桥路", "汽车"), "mall")

    def test_road_address_store_plain_address(self):
        self.assertEqual(classify_store_location_type("某品牌体验中心", "金沙江路2890号", "汽车"), "road_address_store")


class TestNeedsReview(unittest.TestCase):

    def test_suspected_non_auto_store(self):
        row = {"name": "华为智能生活馆", "address": "南京路", "type": "手机数码",
               "poi_kind": "other"}
        nr, reason = needs_review_check(row)
        self.assertTrue(nr)
        self.assertIn("suspected_non_auto_store", reason)

    def test_non_auto_exception_ignored(self):
        row = {"name": "鸿蒙智行体验中心", "address": "南京路", "type": "汽车销售",
               "poi_kind": "experience_store"}
        nr, reason = needs_review_check(row)
        self.assertFalse(nr)

    def test_suspected_energy_site(self):
        row = {"name": "换电站", "address": "", "type": "能源",
               "poi_kind": "other"}
        nr, reason = needs_review_check(row)
        self.assertTrue(nr)
        self.assertIn("suspected_energy_site", reason)

    def test_poi_kind_other(self):
        row = {"name": "某门店", "address": "路", "type": "其他",
               "poi_kind": "other"}
        nr, reason = needs_review_check(row)
        self.assertTrue(nr)
        self.assertIn("poi_kind_other", reason)

    def test_multiple_reasons_combined(self):
        row = {"name": "华为智能生活馆", "address": "", "type": "手机充电",
               "poi_kind": "other"}
        nr, reason = needs_review_check(row)
        self.assertTrue(nr)
        self.assertIn("|", reason)

    def test_possibly_closed(self):
        row = {"name": "鸿蒙智行汽车·华为(晶耀前滩店)(暂停营业)", "address": "", "type": "汽车",
               "poi_kind": "other"}
        nr, reason = needs_review_check(row)
        self.assertTrue(nr)
        self.assertIn("possibly_closed", reason)

    def test_possible_dealer_entity(self):
        row = {"name": "重庆问界汽车销售有限公司", "address": "", "type": "汽车销售",
               "poi_kind": "other"}
        nr, reason = needs_review_check(row)
        self.assertTrue(nr)
        self.assertIn("possible_dealer_entity_or_office", reason)

    def test_company_triggers_review(self):
        row = {"name": "上海益通智行汽车销售服务有限公司", "address": "", "type": "汽车维修",
               "poi_kind": "service_center"}
        nr, reason = needs_review_check(row)
        self.assertTrue(nr)
        self.assertIn("possible_dealer_entity_or_office", reason)

    def test_parking_triggers_review(self):
        row = {"name": "停车场", "address": "龙阳路", "type": "其他",
               "poi_kind": "other"}
        nr, reason = needs_review_check(row)
        self.assertTrue(nr)
        self.assertIn("parking_or_entrance", reason)

    def test_entrance_triggers_review(self):
        row = {"name": "蔚来交付中心地面停车场(出入口)", "address": "嘉定", "type": "汽车",
               "poi_kind": "delivery_center"}
        nr, reason = needs_review_check(row)
        self.assertTrue(nr)
        self.assertIn("parking_or_entrance", reason)

    def test_no_review_needed(self):
        row = {"name": "智己汽车体验中心", "address": "南京路", "type": "汽车销售",
               "poi_kind": "experience_store"}
        nr, reason = needs_review_check(row)
        self.assertFalse(nr)
        self.assertEqual(reason, "")


class TestReClassifyPoiKind(unittest.TestCase):

    def test_mall_store_car_brand_and_mall(self):
        row = {"name": "鸿蒙智行汽车·华为(世博源店)", "address": "世博大道", "type": "汽车", "source_query": "鸿蒙智行"}
        self.assertEqual(re_classify_poi_kind(row), "mall_store")

    def test_mall_store_jinyao(self):
        row = {"name": "鸿蒙智行汽车·华为(晶耀前滩店)(暂停营业)", "address": "耀体路", "type": "汽车", "source_query": "鸿蒙智行"}
        self.assertEqual(re_classify_poi_kind(row), "mall_store")

    def test_mall_store_rimingguang(self):
        row = {"name": "鸿蒙智行(日月光中心宝山店)", "address": "沪太路", "type": "汽车", "source_query": "鸿蒙智行"}
        self.assertEqual(re_classify_poi_kind(row), "mall_store")

    def test_service_center_construction(self):
        row = {"name": "AITO官方精品施工中心(华江路问界)", "address": "华江路", "type": "汽车", "source_query": "AITO"}
        self.assertEqual(re_classify_poi_kind(row), "service_center")

    def test_user_center_4s(self):
        row = {"name": "上海冠松aito4S店(世纪公园店)", "address": "世纪公园", "type": "汽车", "source_query": "AITO"}
        self.assertEqual(re_classify_poi_kind(row), "user_center")

    def test_other_company_entity(self):
        row = {"name": "重庆问界汽车销售有限公司", "address": "九干路", "type": "汽车", "source_query": "问界"}
        self.assertEqual(re_classify_poi_kind(row), "other")


class TestEnrichRows(unittest.TestCase):

    def test_enrich_rows_adds_fields(self):
        rows = make_mock_rows()
        enriched = enrich_rows(rows)
        self.assertIn("is_frontend_store", enriched[0])
        self.assertIn("needs_review", enriched[0])
        self.assertIn("review_reason", enriched[0])

    def test_enrich_marks_review_rows(self):
        rows = make_mock_rows()
        enriched = enrich_rows(rows)
        self.assertEqual(enriched[8]["needs_review"], "true")
        self.assertIn("suspected_non_auto_store", enriched[8]["review_reason"])
        self.assertEqual(enriched[9]["needs_review"], "true")
        self.assertIn("suspected_energy_site", enriched[9]["review_reason"])
        self.assertEqual(enriched[13]["needs_review"], "true")
        self.assertIn("possible_dealer_entity_or_office", enriched[13]["review_reason"])

    def test_enrich_reclassifies_mall_store(self):
        rows = make_mock_rows()
        enriched = enrich_rows(rows)
        self.assertEqual(enriched[10]["poi_kind"], "mall_store")

    def test_enrich_reclassifies_service_center(self):
        rows = make_mock_rows()
        enriched = enrich_rows(rows)
        self.assertEqual(enriched[11]["poi_kind"], "service_center")

    def test_enrich_reclassifies_user_center(self):
        rows = make_mock_rows()
        enriched = enrich_rows(rows)
        self.assertEqual(enriched[12]["poi_kind"], "user_center")

    def test_enrich_keeps_other_for_company_entity(self):
        rows = make_mock_rows()
        enriched = enrich_rows(rows)
        self.assertEqual(enriched[13]["poi_kind"], "other")

    def test_enrich_adds_store_location_type(self):
        rows = make_mock_rows()
        enriched = enrich_rows(rows)
        self.assertIn("store_location_type", enriched[0])
        # Row 10: 鸿蒙智行汽车·华为(世博源店) at 世博大道 → mall
        self.assertEqual(enriched[10]["store_location_type"], "mall")
        # Row 13: 重庆问界汽车销售有限公司 at 九干路 → office_or_entity
        self.assertEqual(enriched[13]["store_location_type"], "office_or_entity")


class TestAggregates(unittest.TestCase):

    def test_brand_counts(self):
        rows = make_mock_rows()
        brand_counts, _, _, _, _, _ = compute_aggregates(rows)
        self.assertEqual(brand_counts.get("智己", 0), 3)
        self.assertEqual(brand_counts.get("蔚来", 0), 3)
        self.assertEqual(brand_counts.get("鸿蒙智行", 0), 8)

    def test_district_counts(self):
        rows = make_mock_rows()
        _, _, district_counts, _, _, _ = compute_aggregates(rows)
        self.assertGreater(district_counts.get("浦东新区", 0), 0)


class TestStatFields(unittest.TestCase):

    def test_brand_district_share(self):
        rows = make_mock_rows()
        brand_counts, brand_district_counts, district_counts, _, _, _ = compute_aggregates(rows)
        rows = add_stat_fields(rows, brand_counts, brand_district_counts, district_counts)
        for r in rows:
            if r["brand_name"] == "智己" and r["district"] == "静安区":
                share = float(r["brand_district_share"])
                self.assertEqual(share, 0.5)  # 1/2 in Jing'an (智己=1, 蔚来=1, total=2)
                break
        else:
            self.fail("No matching row found")

    def test_district_brand_rank(self):
        rows = make_mock_rows()
        brand_counts, brand_district_counts, district_counts, _, _, _ = compute_aggregates(rows)
        rows = add_stat_fields(rows, brand_counts, brand_district_counts, district_counts)
        for r in rows:
            if r["brand_name"] == "智己" and r["district"] == "静安区":
                rank = int(r["district_brand_rank"])
                # In Jing'an: 智己=1, 蔚来=1 -> both rank 1 (tied, but sorted)
                self.assertEqual(rank, 1)
                break
        else:
            self.fail("No matching row found")


class TestNearestNeighbor(unittest.TestCase):

    def test_nearest_neighbor_reasonable(self):
        rows = make_mock_rows()
        pairs = [("智己", "蔚来")]
        result = compute_nearest_neighbor(rows, pairs)
        self.assertEqual(len(result), 1)
        pair = result[0]
        self.assertEqual(pair["from_brand"], "智己")
        self.assertEqual(pair["to_brand"], "蔚来")
        self.assertGreater(pair["median_nearest_km"], 0)

    def test_nearest_neighbor_returns_expected_keys(self):
        rows = make_mock_rows()
        pairs = [("智己", "鸿蒙智行")]
        result = compute_nearest_neighbor(rows, pairs)
        self.assertEqual(len(result), 1)
        pair = result[0]
        for key in ["pair", "from_brand", "to_brand", "median_nearest_km",
                      "mean_nearest_km", "within_0_5km_count", "within_1km_count",
                      "within_3km_count"]:
            self.assertIn(key, pair)

    def test_nearest_neighbor_empty_skipped(self):
        rows = [{"brand_name": "智己", "lng_gcj02": "121.47", "lat_gcj02": "31.23"}]
        pairs = [("智己", "蔚来")]
        result = compute_nearest_neighbor(rows, pairs)
        self.assertEqual(len(result), 0)


class TestBuildSummary(unittest.TestCase):

    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()
        self.paths = {
            "city": "上海",
            "date_str": "2026-07-08",
            "input_path": "/fake/input.csv",
            "enriched_path": os.path.join(self.tmpdir, "enriched.csv"),
            "summary_path": os.path.join(self.tmpdir, "summary.json"),
            "report_path": os.path.join(self.tmpdir, "report.md"),
        }

    def tearDown(self):
        import shutil
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def test_build_summary_has_expected_keys(self):
        rows = make_mock_rows()
        brand_counts, brand_district_counts, district_counts, poi_kind_counts, brand_kind_matrix, _ = compute_aggregates(rows)
        summary = build_summary(rows, self.paths, brand_counts, brand_district_counts,
                                district_counts, poi_kind_counts, brand_kind_matrix)
        self.assertIn("total_poi", summary)
        self.assertIn("brand_counts", summary)
        self.assertIn("poi_kind_counts", summary)
        self.assertIn("district_summary", summary)
        self.assertIn("review_summary", summary)
        self.assertEqual(summary["total_poi"], 14)

    def test_build_summary_review_counts(self):
        rows = make_mock_rows()
        rows = enrich_rows(rows)
        brand_counts, brand_district_counts, district_counts, poi_kind_counts, brand_kind_matrix, _ = compute_aggregates(rows)
        summary = build_summary(rows, self.paths, brand_counts, brand_district_counts,
                                district_counts, poi_kind_counts, brand_kind_matrix)
        self.assertEqual(summary["review_summary"]["needs_review_count"], 3)


class TestWriteEnrichedCsv(unittest.TestCase):

    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()
        self.path = os.path.join(self.tmpdir, "enriched.csv")

    def tearDown(self):
        import shutil
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def test_write_enriched_csv_creates_file(self):
        rows = make_mock_rows()
        rows = enrich_rows(rows)
        brand_counts, brand_district_counts, district_counts, _, _, _ = compute_aggregates(rows)
        rows = add_stat_fields(rows, brand_counts, brand_district_counts, district_counts)
        write_enriched_csv(rows, self.path)
        self.assertTrue(os.path.exists(self.path))
        with open(self.path, encoding="utf-8") as f:
            reader = csv.DictReader(f)
            written = list(reader)
        self.assertEqual(len(written), 14)
        self.assertIn("is_frontend_store", written[0])


class TestWriteSummaryJson(unittest.TestCase):

    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()
        self.path = os.path.join(self.tmpdir, "summary.json")

    def tearDown(self):
        import shutil
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def test_write_summary_json_contains_chinese(self):
        summary = {"city": "上海", "brand_counts": {"智己": 3}}
        write_summary_json(summary, self.path)
        with open(self.path, encoding="utf-8") as f:
            data = json.load(f)
        self.assertEqual(data["city"], "上海")
        self.assertEqual(data["brand_counts"]["智己"], 3)


class TestWriteMarkdownReport(unittest.TestCase):

    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()
        self.paths = {
            "report_path": os.path.join(self.tmpdir, "report.md"),
            "city": "上海",
            "date_str": "2026-07-08",
            "input_path": "/fake/input.csv",
        }

    def tearDown(self):
        import shutil
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def test_markdown_report_generated(self):
        rows = make_mock_rows()
        rows = enrich_rows(rows)
        brand_counts, brand_district_counts, district_counts, poi_kind_counts, brand_kind_matrix, _ = compute_aggregates(rows)
        rows = add_stat_fields(rows, brand_counts, brand_district_counts, district_counts)
        summary = build_summary(rows, self.paths, brand_counts, brand_district_counts,
                                district_counts, poi_kind_counts, brand_kind_matrix)
        write_markdown_report(rows, summary, self.paths, top_n=20)
        self.assertTrue(os.path.exists(self.paths["report_path"]))
        with open(self.paths["report_path"], encoding="utf-8") as f:
            content = f.read()
        self.assertIn("上海三品牌门店 POI 对比观察", content)
        self.assertIn("总 POI 数", content)


class TestEmptyCsv(unittest.TestCase):

    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()
        self.path = os.path.join(self.tmpdir, "empty.csv")
        with open(self.path, "w", encoding="utf-8", newline="") as f:
            f.write("brand_id,brand_name,name,district,lng_gcj02,lat_gcj02,poi_kind,source_query,address,type,tel\n")

    def tearDown(self):
        import shutil
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def test_empty_csv_does_not_crash(self):
        rows = read_csv(self.path)
        self.assertEqual(len(rows), 0)
        check_required_columns(rows)
        # enrich with empty
        rows = enrich_rows(rows)
        self.assertEqual(len(rows), 0)


class TestParseArgs(unittest.TestCase):

    def test_default_date_resolved(self):
        args = parse_args(["--date", "2026-07-08"])
        self.assertEqual(args.date_str, "2026-07-08")
        self.assertEqual(args.city, "上海")

    def test_custom_city(self):
        args = parse_args(["--city", "北京", "--date", "2026-07-08"])
        self.assertEqual(args.city, "北京")


class TestEndToEnd(unittest.TestCase):

    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()
        self.input_path = os.path.join(self.tmpdir, "input.csv")
        write_mock_csv(make_mock_rows(), self.input_path)

    def tearDown(self):
        import shutil
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def test_full_pipeline(self):
        from src.brand_poi_analyzer import main as analyzer_main
        orig_exit = sys.exit
        sys.exit = lambda code: None
        orig_argv = sys.argv
        sys.argv = ["brand_poi_analyzer.py",
                     "--date", "2026-07-08",
                     "--input", self.input_path,
                     "--output-dir", self.tmpdir,
                     "--report-dir", self.tmpdir]
        try:
            analyzer_main()
        finally:
            sys.exit = orig_exit
            sys.argv = orig_argv

        enriched = os.path.join(self.tmpdir, "上海_brand_poi_2026-07-08_enriched.csv")
        summary = os.path.join(self.tmpdir, "上海_brand_poi_2026-07-08_summary.json")
        report = os.path.join(self.tmpdir, "2026-07-08_上海_brand_poi_analysis.md")

        self.assertTrue(os.path.exists(enriched), f"Missing enriched CSV: {enriched}")
        self.assertTrue(os.path.exists(summary), f"Missing summary JSON: {summary}")
        self.assertTrue(os.path.exists(report), f"Missing report: {report}")

        with open(enriched, encoding="utf-8") as f:
            enriched_rows = list(csv.DictReader(f))
        self.assertGreater(len(enriched_rows), 0)
        self.assertIn("is_frontend_store", enriched_rows[0])
        self.assertIn("brand_district_share", enriched_rows[0])


if __name__ == "__main__":
    unittest.main()
