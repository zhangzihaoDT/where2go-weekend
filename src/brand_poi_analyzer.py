#!/usr/bin/env python3
"""
Brand POI Analyzer — offline analysis of brand POI scan results.

Analyzes brand distribution, POI kind structure, district coverage,
spatial overlap (nearest neighbor via Haversine), and data quality flags.

Usage:
  python3 src/brand_poi_analyzer.py --date 2026-07-08
  python3 src/brand_poi_analyzer.py --city 上海 --date 2026-07-08
   python3 src/brand_poi_analyzer.py --input data/brand_stores/上海_brand_poi_2026-07-08.csv
"""

import argparse
import csv
import json
import math
import os
import sys
import statistics
from collections import defaultdict
from datetime import date

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, PROJECT_ROOT)

from src.poi_classifier import classify_poi_kind, classify_store_location_type

REQUIRED_COLUMNS = [
    "brand_id", "brand_name", "name", "district",
    "lng_gcj02", "lat_gcj02", "poi_kind", "source_query", "address",
]

FRONTEND_KINDS = {"experience_store", "user_center", "mall_store"}
AFTER_SALES_KINDS = {"service_center"}
DELIVERY_KINDS = {"delivery_center"}
CORE_TOUCHPOINT_KINDS = {
    "experience_store", "user_center", "mall_store",
    "service_center", "delivery_center",
}

NON_AUTO_TRIGGERS = ["手机", "授权服务中心", "智能生活馆", "华为手机", "维修手机", "数码"]
NON_AUTO_EXCEPTIONS = ["鸿蒙智行", "问界", "AITO", "智己", "蔚来", "汽车"]
CLOSED_TRIGGERS = ["暂停营业"]
ENTITY_TRIGGERS = ["销售有限公司", "公司"]
PARKING_ENTRANCE_TRIGGERS = ["停车场", "出入口", "入口", "出口"]

BRANDS_OF_INTEREST = ["智己", "蔚来", "鸿蒙智行"]

from src.poi_classifier import CAR_BRAND_CLUES, MALL_CLUES, SERVICE_KEYWORDS, USER_KEYWORDS, ENERGY_TRIGGERS


def haversine_km(lng1, lat1, lng2, lat2):
    R = 6371.0
    dlat = math.radians(lat2 - lat1)
    dlng = math.radians(lng2 - lng1)
    a = math.sin(dlat / 2) ** 2 + math.cos(math.radians(lat1)) * math.cos(math.radians(lat2)) * math.sin(dlng / 2) ** 2
    c = 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))
    return R * c


def parse_args(argv=None):
    parser = argparse.ArgumentParser(description="品牌 POI 分析")
    parser.add_argument("--city", default="上海", help="城市")
    parser.add_argument("--date", dest="date_str", help="日期 YYYY-MM-DD")
    parser.add_argument("--input", help="输入 CSV 路径")
    parser.add_argument("--output-dir", default="data/brand_stores", help="输出目录")
    parser.add_argument("--report-dir", default="reports", help="报告目录")
    parser.add_argument("--top-n", type=int, default=20, help="需复核 POI 最多展示条数")
    return parser.parse_args(argv)


def resolve_paths(args):
    project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    city = args.city
    date_str = args.date_str or date.today().isoformat()

    input_path = args.input
    if not input_path:
        input_path = os.path.join(
            project_root, "data", "brand_poi", f"{city}_brand_poi_{date_str}.csv"
        )

    output_dir = args.output_dir
    if not os.path.isabs(output_dir):
        output_dir = os.path.join(project_root, output_dir)
    report_dir = args.report_dir
    if not os.path.isabs(report_dir):
        report_dir = os.path.join(project_root, report_dir)

    enriched_path = os.path.join(output_dir, f"{city}_brand_poi_{date_str}_enriched.csv")
    summary_path = os.path.join(output_dir, f"{city}_brand_poi_{date_str}_summary.json")
    report_path = os.path.join(report_dir, f"{date_str}_{city}_brand_poi_analysis.md")

    return {
        "project_root": project_root,
        "city": city,
        "date_str": date_str,
        "input_path": input_path,
        "enriched_path": enriched_path,
        "summary_path": summary_path,
        "report_path": report_path,
    }


def read_csv(path):
    with open(path, encoding="utf-8-sig") as f:
        reader = csv.DictReader(f)
        rows = list(reader)
    return rows


def check_required_columns(rows):
    if not rows:
        return
    actual_cols = set(rows[0].keys())
    missing = [c for c in REQUIRED_COLUMNS if c not in actual_cols]
    if missing:
        print(f"[ERROR] missing required columns: {', '.join(missing)}", file=sys.stderr)
        sys.exit(1)


def safe_float(val, default=0.0):
    if val is None or val == "":
        return default
    try:
        return float(val)
    except (ValueError, TypeError):
        return default


def safe_str(val):
    return (val or "").strip()


def re_classify_poi_kind(row):
    """Re-classify poi_kind from a row dict, delegating to shared classify_poi_kind."""
    return classify_poi_kind(
        name=safe_str(row.get("name", "")),
        poi_type=safe_str(row.get("type", "")),
        address=safe_str(row.get("address", "")),
        source_query=safe_str(row.get("source_query", "")),
    )


def needs_review_check(row):
    reasons = []
    name = safe_str(row.get("name", ""))
    addr = safe_str(row.get("address", ""))
    typ = safe_str(row.get("type", ""))
    text = f"{name} {addr} {typ}"

    has_non_auto = any(t in text for t in NON_AUTO_TRIGGERS)
    has_exception = any(t in text for t in NON_AUTO_EXCEPTIONS)
    if has_non_auto and not has_exception:
        reasons.append("suspected_non_auto_store")

    has_energy = any(t in text for t in ENERGY_TRIGGERS)
    if has_energy:
        reasons.append("suspected_energy_site")

    poi_kind = safe_str(row.get("poi_kind", ""))
    if poi_kind == "other":
        reasons.append("poi_kind_other")

    if any(t in name for t in CLOSED_TRIGGERS):
        reasons.append("possibly_closed")

    if any(t in name for t in ENTITY_TRIGGERS):
        reasons.append("possible_dealer_entity_or_office")

    if any(t in name or t in addr for t in PARKING_ENTRANCE_TRIGGERS):
        reasons.append("parking_or_entrance")

    if reasons:
        return True, "|".join(reasons)
    return False, ""


def is_frontend_store(row):
    return safe_str(row.get("poi_kind", "")) in FRONTEND_KINDS


def is_after_sales(row):
    return safe_str(row.get("poi_kind", "")) in AFTER_SALES_KINDS


def is_delivery(row):
    return safe_str(row.get("poi_kind", "")) in DELIVERY_KINDS


def is_core_touchpoint(row):
    return safe_str(row.get("poi_kind", "")) in CORE_TOUCHPOINT_KINDS


def enrich_rows(rows):
    for row in rows:
        name = safe_str(row.get("name", ""))
        address = safe_str(row.get("address", ""))
        typ = safe_str(row.get("type", ""))
        row["poi_kind"] = re_classify_poi_kind(row)
        row["store_location_type"] = classify_store_location_type(name, address, typ)
        row["is_frontend_store"] = str(is_frontend_store(row)).lower()
        row["is_after_sales"] = str(is_after_sales(row)).lower()
        row["is_delivery"] = str(is_delivery(row)).lower()
        row["is_core_touchpoint"] = str(is_core_touchpoint(row)).lower()
        nr, reason = needs_review_check(row)
        row["needs_review"] = str(nr).lower()
        row["review_reason"] = reason
    return rows


def compute_aggregates(rows):
    brand_counts = defaultdict(int)
    brand_district_counts = defaultdict(lambda: defaultdict(int))
    district_counts = defaultdict(int)
    poi_kind_counts = defaultdict(int)
    brand_kind_matrix = defaultdict(lambda: defaultdict(int))
    brand_location_matrix = defaultdict(lambda: defaultdict(int))

    for row in rows:
        bname = safe_str(row.get("brand_name", ""))
        kind = safe_str(row.get("poi_kind", ""))
        district = safe_str(row.get("district", ""))
        loc = safe_str(row.get("store_location_type", ""))
        brand_counts[bname] += 1
        if district:
            brand_district_counts[bname][district] += 1
            district_counts[district] += 1
        poi_kind_counts[kind] += 1
        brand_kind_matrix[bname][kind] += 1
        if loc:
            brand_location_matrix[bname][loc] += 1

    return brand_counts, brand_district_counts, district_counts, poi_kind_counts, brand_kind_matrix, brand_location_matrix


def add_stat_fields(rows, brand_counts, brand_district_counts, district_counts):
    district_brand_counts = defaultdict(lambda: defaultdict(int))
    for row in rows:
        bname = safe_str(row.get("brand_name", ""))
        district = safe_str(row.get("district", ""))
        if district:
            district_brand_counts[district][bname] += 1

    district_brand_rank = {}
    for d, bc in district_brand_counts.items():
        sorted_bc = sorted(bc.items(), key=lambda x: -x[1])
        rank_map = {}
        for i, (b, _) in enumerate(sorted_bc):
            rank_map[b] = i + 1
        district_brand_rank[d] = rank_map

    for row in rows:
        bname = safe_str(row.get("brand_name", ""))
        district = safe_str(row.get("district", ""))
        row["brand_poi_count"] = str(brand_counts.get(bname, 0))
        row["brand_district_poi_count"] = str(brand_district_counts.get(bname, {}).get(district, 0))
        row["district_total_poi_count"] = str(district_counts.get(district, 0))
        dt = district_counts.get(district, 0)
        bd = brand_district_counts.get(bname, {}).get(district, 0)
        share = round(bd / dt, 4) if dt > 0 else 0.0
        row["brand_district_share"] = str(share)
        rank = district_brand_rank.get(district, {}).get(bname, 0)
        row["district_brand_rank"] = str(rank)

    return rows


def build_summary(rows, paths, brand_counts, brand_district_counts,
                  district_counts, poi_kind_counts, brand_kind_matrix,
                  brand_location_matrix=None):
    city = paths["city"]
    date_str = paths["date_str"]

    review_count = 0
    review_reasons = defaultdict(int)
    for row in rows:
        if row.get("needs_review") == "true":
            review_count += 1
            for r in row.get("review_reason", "").split("|"):
                if r:
                    review_reasons[r] += 1

    total_poi = len(rows)

    brand_counts_filtered = {}
    for b in BRANDS_OF_INTEREST:
        brand_counts_filtered[b] = brand_counts.get(b, 0)

    district_summary = []
    for d in sorted(district_counts.keys()):
        bc = {}
        for b in BRANDS_OF_INTEREST:
            bc[b] = brand_district_counts.get(b, {}).get(d, 0)
        district_summary.append({
            "district": d,
            "total_poi": district_counts[d],
            **bc,
        })

    district_brand_matrix = {}
    for b in BRANDS_OF_INTEREST:
        district_brand_matrix[b] = dict(brand_district_counts.get(b, {}))

    brand_kind_matrix_clean = {}
    for b in BRANDS_OF_INTEREST:
        brand_kind_matrix_clean[b] = dict(brand_kind_matrix.get(b, {}))

    brand_location_matrix_clean = {}
    if brand_location_matrix:
        for b in BRANDS_OF_INTEREST:
            brand_location_matrix_clean[b] = dict(brand_location_matrix.get(b, {}))

    summary = {
        "city": city,
        "date": date_str,
        "input_path": paths["input_path"],
        "total_poi": total_poi,
        "brand_counts": brand_counts_filtered,
        "poi_kind_counts": dict(poi_kind_counts),
        "brand_kind_matrix": brand_kind_matrix_clean,
        "brand_location_matrix": brand_location_matrix_clean,
        "district_brand_matrix": district_brand_matrix,
        "district_summary": district_summary,
        "review_summary": {
            "needs_review_count": review_count,
            "needs_review_share": round(review_count / total_poi, 4) if total_poi > 0 else 0.0,
            "reasons": dict(review_reasons),
        },
    }

    brand_names = [safe_str(r.get("brand_name", "")) for r in rows]
    present_brands = sorted(set(bn for bn in brand_names if bn in BRANDS_OF_INTEREST))

    pairs = []
    for i, b1 in enumerate(present_brands):
        for b2 in present_brands[i + 1:]:
            pairs.append((b1, b2))

    if pairs:
        nearest = compute_nearest_neighbor(rows, pairs)
        summary["nearest_neighbor"] = {
            "enabled": True,
            "pairs": nearest,
        }
    else:
        summary["nearest_neighbor"] = {
            "enabled": False,
            "pairs": [],
        }

    return summary


def compute_nearest_neighbor(rows, pairs):
    brand_pois = defaultdict(list)
    for row in rows:
        bn = safe_str(row.get("brand_name", ""))
        lng = safe_float(row.get("lng_gcj02"))
        lat = safe_float(row.get("lat_gcj02"))
        if bn and (lng != 0.0 or lat != 0.0):
            brand_pois[bn].append((lng, lat))

    results = []
    for b1, b2 in pairs:
        pts1 = brand_pois.get(b1, [])
        pts2 = brand_pois.get(b2, [])
        if not pts1 or not pts2:
            continue

        nearest_dists = []
        for lng1, lat1 in pts1:
            min_dist = min(haversine_km(lng1, lat1, lng2, lat2) for lng2, lat2 in pts2)
            nearest_dists.append(min_dist)

        median_dist = statistics.median(nearest_dists)
        mean_dist = statistics.mean(nearest_dists)
        within_0_5k = sum(1 for d in nearest_dists if d <= 0.5)
        within_1k = sum(1 for d in nearest_dists if d <= 1.0)
        within_3k = sum(1 for d in nearest_dists if d <= 3.0)
        n = len(nearest_dists)

        results.append({
            "pair": f"{b1} vs {b2}",
            "from_brand": b1,
            "to_brand": b2,
            "from_count": n,
            "median_nearest_km": round(median_dist, 4),
            "mean_nearest_km": round(mean_dist, 4),
            "within_0_5km_count": within_0_5k,
            "within_1km_count": within_1k,
            "within_3km_count": within_3k,
            "within_0_5km_share": round(within_0_5k / n, 4) if n > 0 else 0.0,
            "within_1km_share": round(within_1k / n, 4) if n > 0 else 0.0,
            "within_3km_share": round(within_3k / n, 4) if n > 0 else 0.0,
        })

    return results


def write_enriched_csv(rows, path):
    if not rows:
        fieldnames = REQUIRED_COLUMNS + [
            "is_frontend_store", "is_after_sales", "is_delivery", "is_core_touchpoint",
            "needs_review", "review_reason", "brand_poi_count",
            "brand_district_poi_count", "district_total_poi_count",
            "brand_district_share", "district_brand_rank",
            "store_location_type",
        ]
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w", encoding="utf-8", newline="") as f:
            writer = csv.DictWriter(f, fieldnames=fieldnames)
            writer.writeheader()
        return

    fieldnames = list(rows[0].keys())
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)


def write_summary_json(summary, path):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(summary, f, ensure_ascii=False, indent=2)


def write_markdown_report(rows, summary, paths, top_n):
    os.makedirs(os.path.dirname(paths["report_path"]), exist_ok=True)
    city = paths["city"]
    date_str = paths["date_str"]
    input_path = paths["input_path"]

    brand_counts = summary["brand_counts"]
    total_poi = summary["total_poi"]
    review_count = summary["review_summary"]["needs_review_count"]
    review_share = summary["review_summary"]["needs_review_share"]
    review_reasons = summary["review_summary"]["reasons"]

    brand_names_present = [b for b in BRANDS_OF_INTEREST if brand_counts.get(b, 0) > 0]
    brands_present_count = len(brand_names_present)

    districts = set()
    for row in rows:
        d = safe_str(row.get("district", ""))
        if d:
            districts.add(d)
    district_count = len(districts)

    lines = []
    lines.append(f"# {city}三品牌门店 POI 对比观察")
    lines.append("")
    lines.append(f"生成日期：{date_str}")
    lines.append(f"城市：{city}")
    lines.append(f"数据来源：高德 POI place_text")
    lines.append(f"输入文件：{input_path}")
    lines.append("")
    lines.append("## 1. 数据说明")
    lines.append("")
    lines.append("本报告基于高德 POI 搜索结果生成，用于观察品牌门店空间分布与渠道形态，不等同于品牌官方门店清单。")
    lines.append("")
    lines.append("## 2. 总体概览")
    lines.append("")
    lines.append("| 指标 | 数值 |")
    lines.append("|---|---:|")
    lines.append(f"| 总 POI 数 | {total_poi} |")
    lines.append(f"| 品牌数 | {brands_present_count} |")
    lines.append(f"| 覆盖区县数 | {district_count} |")
    lines.append(f"| 需要人工复核 POI 数 | {review_count} |")
    lines.append(f"| 人工复核占比 | {review_share:.2%} |")
    lines.append("")

    lines.append("## 3. 品牌门店数量")
    lines.append("")
    lines.append("| 品牌 | POI 数 | 覆盖区县数 | 前端触点数 | 售后服务数 | 交付中心数 | 需复核数 |")
    lines.append("|---|---:|---:|---:|---:|---:|---:|")
    for b in BRANDS_OF_INTEREST:
        bc = brand_counts.get(b, 0)
        b_districts = set()
        f_count = 0
        a_count = 0
        d_count = 0
        r_count = 0
        for row in rows:
            if safe_str(row.get("brand_name", "")) == b:
                d2 = safe_str(row.get("district", ""))
                if d2:
                    b_districts.add(d2)
                if row.get("is_frontend_store") == "true":
                    f_count += 1
                if row.get("is_after_sales") == "true":
                    a_count += 1
                if row.get("is_delivery") == "true":
                    d_count += 1
                if row.get("needs_review") == "true":
                    r_count += 1
        lines.append(f"| {b} | {bc} | {len(b_districts)} | {f_count} | {a_count} | {d_count} | {r_count} |")
    lines.append("")

    lines.append("## 4. 门店类型结构")
    lines.append("")
    all_kinds = ["experience_store", "user_center", "service_center", "delivery_center", "mall_store", "other"]
    header = "| 品牌 | " + " | ".join(all_kinds) + " |"
    sep = "|" + "---|" * (len(all_kinds) + 1)
    lines.append(header)
    lines.append(sep)
    for b in BRANDS_OF_INTEREST:
        vals = []
        for k in all_kinds:
            vals.append(str(summary["brand_kind_matrix"].get(b, {}).get(k, 0)))
        lines.append(f"| {b} | " + " | ".join(vals) + " |")
    lines.append("")

    insight_lines = []
    front_max_brand = max(BRANDS_OF_INTEREST, key=lambda b: summary["brand_kind_matrix"].get(b, {}).get("experience_store", 0))
    insight_lines.append(f"- **{front_max_brand}** 前端触点（experience_store）最多。")

    service_max_brand = max(BRANDS_OF_INTEREST, key=lambda b: summary["brand_kind_matrix"].get(b, {}).get("service_center", 0))
    insight_lines.append(f"- **{service_max_brand}** 服务中心（service_center）最多。")

    uc_ratios = {}
    for b in BRANDS_OF_INTEREST:
        total = brand_counts.get(b, 0) or 1
        uc = summary["brand_kind_matrix"].get(b, {}).get("user_center", 0)
        uc_ratios[b] = uc / total
    uc_max_brand = max(BRANDS_OF_INTEREST, key=lambda b: uc_ratios[b])
    insight_lines.append(f"- **{uc_max_brand}** user_center 占比最高。")

    other_ratios = {}
    for b in BRANDS_OF_INTEREST:
        total = brand_counts.get(b, 0) or 1
        ok = summary["brand_kind_matrix"].get(b, {}).get("other", 0)
        other_ratios[b] = ok / total
    other_max_brand = max(BRANDS_OF_INTEREST, key=lambda b: other_ratios[b])
    insight_lines.append(f"- **{other_max_brand}** other 占比最高，需要复核。")

    lines.append("\n".join(insight_lines))
    lines.append("")

    store_location_labels = {
        "mall": "商场", "road_address_store": "道路地址型门店", "auto_park": "汽车园区",
        "industrial_or_service_site": "工业/服务场地", "office_or_entity": "办公/企业实体",
        "unknown": "未知",
    }
    store_location_footnote = (
        "> road_address_store 表示未识别为商场、汽车园区、工业/服务场地或办公实体的"
        "普通道路地址型门店。"
    )
    blm = summary.get("brand_location_matrix", {})
    has_location_data = any(blm.get(b, {}) for b in BRANDS_OF_INTEREST)
    if has_location_data:
        lines.append("## 5. 空间区位类型")
        lines.append("")
        loc_types = ["mall", "road_address_store", "auto_park", "industrial_or_service_site", "office_or_entity", "unknown"]
        loc_header = "| 品牌 | " + " | ".join(store_location_labels.get(t, t) for t in loc_types) + " |"
        loc_sep = "|" + "---|" * (len(loc_types) + 1)
        lines.append(loc_header)
        lines.append(loc_sep)
        for b in BRANDS_OF_INTEREST:
            vals = [str(blm.get(b, {}).get(t, 0)) for t in loc_types]
            lines.append(f"| {b} | " + " | ".join(vals) + " |")
        lines.append("")
        lines.append(store_location_footnote)
        lines.append("")

        insight_loc = []
        for b in BRANDS_OF_INTEREST:
            bm_loc = blm.get(b, {})
            total = sum(bm_loc.values()) or 1
            mall_share = bm_loc.get("mall", 0) / total
            road_share = bm_loc.get("road_address_store", 0) / total
            parts = []
            if mall_share > 0.3:
                parts.append(f"商场占比 {mall_share:.0%}")
            if road_share > 0.3:
                parts.append(f"道路地址型门店占比 {road_share:.0%}")
            if parts:
                insight_loc.append(f"- **{b}**：{'，'.join(parts)}")
        if insight_loc:
            lines.append("\n".join(insight_loc))
            lines.append("")

    lines.append("## 6. 区县覆盖对比")
    lines.append("")
    ds_rows = summary.get("district_summary", [])
    lines.append("| 区县 | " + " | ".join(BRANDS_OF_INTEREST) + " | 合计 | 覆盖品牌数 | 主导品牌 |")
    lines.append("|---|" + "---|" * len(BRANDS_OF_INTEREST) + "---:|---:|---|")
    for ds in sorted(ds_rows, key=lambda x: -x["total_poi"]):
        d = ds["district"]
        vals = [str(ds.get(b, 0)) for b in BRANDS_OF_INTEREST]
        total = ds["total_poi"]
        covered = sum(1 for b in BRANDS_OF_INTEREST if ds.get(b, 0) > 0)
        dominant = ""
        max_c = 0
        for b in BRANDS_OF_INTEREST:
            if ds.get(b, 0) > max_c:
                max_c = ds[b]
                dominant = b
        lines.append(f"| {d} | " + " | ".join(vals) + f" | {total} | {covered} | {dominant} |")
    lines.append("")

    all_districts_covered = [d for d in ds_rows if sum(1 for b in BRANDS_OF_INTEREST if d.get(b, 0) > 0) == 3]
    if all_districts_covered:
        covered_names = ", ".join(sorted(d["district"] for d in all_districts_covered))
        lines.append(f"- **三品牌共同覆盖区县**：{covered_names}")
    else:
        lines.append("- **三品牌共同覆盖区县**：无")

    single_brand_districts = []
    for d in ds_rows:
        for b in BRANDS_OF_INTEREST:
            if d.get(b, 0) > 0 and sum(1 for b2 in BRANDS_OF_INTEREST if d.get(b2, 0) > 0) == 1:
                single_brand_districts.append(f"{d['district']}（{b}）")
    if single_brand_districts:
        lines.append(f"- **单品牌优势区**：{'、'.join(single_brand_districts)}")

    top5_districts = sorted(ds_rows, key=lambda x: -x["total_poi"])[:5]
    top5_names = [f"{d['district']}（{d['total_poi']}）" for d in top5_districts]
    lines.append(f"- **POI 密度最高区县 TOP5**：{'、'.join(top5_names)}")
    lines.append("")

    lines.append("## 7. 空间重叠观察")
    lines.append("")
    nn = summary.get("nearest_neighbor", {})
    nn_pairs = nn.get("pairs", [])
    if nn_pairs:
        lines.append("| 对比 | 中位最近距离 km | 平均最近距离 km | 500m 内数量 | 1km 内数量 | 3km 内数量 | 500m 占比 | 1km 占比 | 3km 占比 |")
        lines.append("|---|---:|---:|---:|---:|---:|---:|---:|---:|")
        for p in nn_pairs:
            lines.append(
                f"| {p['pair']} | {p['median_nearest_km']} | {p['mean_nearest_km']} | "
                f"{p['within_0_5km_count']} | {p['within_1km_count']} | {p['within_3km_count']} | "
                f"{p['within_0_5km_share']:.1%} | {p['within_1km_share']:.1%} | {p['within_3km_share']:.1%} |"
            )
        lines.append("")

        if len(nn_pairs) >= 1:
            max_overlap = max(nn_pairs, key=lambda p: p["within_0_5km_share"])
            lines.append(f"- **空间重叠最高**：{max_overlap['pair']}（500m 内占比 {max_overlap['within_0_5km_share']:.1%}）")

        close_pairs = [p for p in nn_pairs if p["median_nearest_km"] < 1.0]
        if close_pairs:
            for p in close_pairs:
                lines.append(f"- **{p['pair']}** 中位最近距离仅 {p['median_nearest_km']}km，存在明显贴身布局。")
        lines.append("")
    else:
        lines.append("品牌数据不足以进行最近邻分析。")
        lines.append("")

    lines.append("## 8. 疑似需复核 POI")
    lines.append("")
    review_rows = [r for r in rows if r.get("needs_review") == "true"]
    if review_rows:
        lines.append(f"| 品牌 | 名称 | 类型 | 区县 | 地址 | 原因 |")
        lines.append("|---|---|---|---|---|---|")
        for r in review_rows[:top_n]:
            lines.append(
                f"| {safe_str(r.get('brand_name', ''))} | {safe_str(r.get('name', ''))} | "
                f"{safe_str(r.get('poi_kind', ''))} | {safe_str(r.get('district', ''))} | "
                f"{safe_str(r.get('address', ''))} | {r.get('review_reason', '')} |"
            )
        if len(review_rows) > top_n:
            lines.append(f"| ... | （共 {len(review_rows)} 条，仅展示前 {top_n} 条） | | | | |")
    else:
        lines.append("无需要人工复核的 POI。")
    lines.append("")

    lines.append("## 9. 初步渠道策略观察")
    lines.append("")
    for b in BRANDS_OF_INTEREST:
        lines.append(f"### {b}")
        lines.append("")
        bc = brand_counts.get(b, 0)
        lines.append(f"共 {bc} 个 POI。")
        bm = summary["brand_kind_matrix"].get(b, {})
        if bm.get("experience_store", 0) > 0:
            lines.append(f"- 体验中心（experience_store）：{bm.get('experience_store', 0)} 个")
        if bm.get("service_center", 0) > 0:
            lines.append(f"- 服务中心（service_center）：{bm.get('service_center', 0)} 个")
        if bm.get("delivery_center", 0) > 0:
            lines.append(f"- 交付中心（delivery_center）：{bm.get('delivery_center', 0)} 个")
        if bm.get("user_center", 0) > 0:
            lines.append(f"- 用户中心（user_center）：{bm.get('user_center', 0)} 个")
        if bm.get("mall_store", 0) > 0:
            lines.append(f"- 商场店（mall_store）：{bm.get('mall_store', 0)} 个")
        if b == "智己":
            lines.append("关注：")
            lines.append("- 体验中心、服务中心、交付中心")
            lines.append("- 是否形成体验、交付、售后闭环")
        elif b == "蔚来":
            lines.append("关注：")
            lines.append("- 体验 / 空间类触点")
            lines.append("- 服务中心")
            lines.append("- 是否在核心区县更密集")
        elif b == "鸿蒙智行":
            lines.append("关注：")
            lines.append("- user_center")
            lines.append("- experience_store")
            lines.append("- 是否体现用户中心体系，而非传统单一汽车门店体系")
        lines.append("")

    lines.append("## 10. 下一步建议")
    lines.append("")
    lines.append("- 引入官方门店清单进行校准")
    lines.append("- 增加商圈 / 城市功能区标签")
    lines.append("- 增加品牌间覆盖重叠地图层")
    lines.append("- 将本分析接入 HTML 地图侧栏")
    lines.append("")

    report_content = "\n".join(lines)
    with open(paths["report_path"], "w", encoding="utf-8") as f:
        f.write(report_content)

    return report_content


def print_header(city, date_str, input_path):
    print("=== 品牌 POI 分析 ===")
    print(f"城市: {city}")
    print(f"日期: {date_str}")
    print(f"输入: {input_path}")
    print()


def print_summary(rows, brand_counts, district_count, review_count):
    from collections import Counter
    brand_names_present = [b for b in BRANDS_OF_INTEREST if brand_counts.get(b, 0) > 0]
    print(f"[读取] POI 数: {len(rows)}")
    print(f"[分析] 品牌数: {len(brand_names_present)}")
    print(f"[分析] 覆盖区县数: {district_count}")
    print(f"[分析] 需复核 POI: {review_count}")
    locs = Counter(r.get("store_location_type", "") for r in rows)
    if locs:
        loc_parts = [f"{k}: {v}" for k, v in sorted(locs.items()) if k]
        print(f"[分析] 空间区位: {' | '.join(loc_parts)}")
    print()


def print_outputs(enriched_path, summary_path, report_path):
    print(f"[输出] Enriched CSV: {enriched_path}")
    print(f"[输出] Summary JSON: {summary_path}")
    print(f"[输出] Report: {report_path}")
    print()


def run_analyzer(rows, city, date_str, top_n=20):
    """
    Analyze POI rows.
    Returns {enriched_rows, summary, report_md}.
    Does NOT write files — caller decides where to persist.
    """
    from collections import defaultdict as _dd
    enriched = enrich_rows(rows) if rows else []
    if enriched:
        brand_counts, brand_district_counts, district_counts, poi_kind_counts, brand_kind_matrix, brand_location_matrix = compute_aggregates(enriched)
        enriched = add_stat_fields(enriched, brand_counts, brand_district_counts, district_counts)
    else:
        brand_counts = {b: 0 for b in BRANDS_OF_INTEREST}
        brand_district_counts = _dd(lambda: _dd(int))
        district_counts = _dd(int)
        poi_kind_counts = _dd(int)
        brand_kind_matrix = _dd(lambda: _dd(int))
        brand_location_matrix = _dd(lambda: _dd(int))

    summary = build_summary(enriched, {
        "city": city, "date_str": date_str, "input_path": "",
    }, brand_counts, brand_district_counts, district_counts,
                             poi_kind_counts, brand_kind_matrix,
                             brand_location_matrix=brand_location_matrix)

    import tempfile
    _tmp_report = os.path.join(tempfile.mkdtemp(), "report.md")
    report_md = write_markdown_report(enriched, summary, {
        "report_path": _tmp_report, "city": city, "date_str": date_str,
        "input_path": "",
    }, top_n)

    return {
        "enriched_rows": enriched,
        "summary": summary,
        "report_md": report_md,
    }


def main():
    args = parse_args()
    paths = resolve_paths(args)
    top_n = args.top_n

    print_header(paths["city"], paths["date_str"], paths["input_path"])

    if not os.path.exists(paths["input_path"]):
        print(f"[ERROR] 输入文件不存在: {paths['input_path']}", file=sys.stderr)
        sys.exit(1)

    rows = read_csv(paths["input_path"])
    check_required_columns(rows)

    result = run_analyzer(rows=rows, city=paths["city"], date_str=paths["date_str"], top_n=top_n)

    write_enriched_csv(result["enriched_rows"], paths["enriched_path"])
    write_summary_json(result["summary"], paths["summary_path"])
    with open(paths["report_path"], "w", encoding="utf-8") as f:
        f.write(result["report_md"])

    print(f"[输出] Enriched CSV: {paths['enriched_path']}")
    print(f"[输出] Summary JSON: {paths['summary_path']}")
    print(f"[输出] Report: {paths['report_path']}")
    print("✅ 品牌 POI 分析完成")


if __name__ == "__main__":
    main()
