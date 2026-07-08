#!/usr/bin/env python3
"""
CLI entry for brand POI compare.

Usage:
  python3 src/brand_poi_compare.py --date 2026-07-08
  python3 src/brand_poi_compare.py --smoke-query 蔚来中心 --debug-api --no-cache
  python3 src/brand_poi_compare.py --date 2026-07-08 --clear-cache
  python3 src/brand_poi_compare.py --date 2026-07-08 --dry-run-plan
"""

import argparse
import os
import sys
from datetime import date

import yaml

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, PROJECT_ROOT)

from src.amap_client import get_api_key
from src.brand_poi_scanner import (
    scan_brand_pois,
    estimate_requests,
    SCAN_MODES,
    smoke_query,
    clear_cache,
    set_debug,
    write_csv,
    write_json,
)
from src.brand_poi_map_writer import (
    generate_brand_poi_map,
    generate_brand_poi_report,
)


def main():
    parser = argparse.ArgumentParser(description="品牌 POI 对比观察")
    parser.add_argument("--city", default="上海", help="城市")
    parser.add_argument("--date", dest="date_str", help="扫描日期 YYYY-MM-DD")
    parser.add_argument("--brands", default="智己,蔚来,鸿蒙智行", help="品牌列表")
    parser.add_argument("--map-provider", default="amap_js", choices=["amap_js"])
    parser.add_argument("--scan-mode", default="text_city_first", choices=SCAN_MODES)
    parser.add_argument("--max-total-requests", type=int, default=None)
    parser.add_argument("--dry-run-plan", action="store_true")
    parser.add_argument("--debug-api", action="store_true", help="打印详细 API 调试日志")
    parser.add_argument("--smoke-query", help="只执行一次 API 查询用于诊断，不生成地图")
    parser.add_argument("--no-cache", action="store_true", help="不使用缓存")
    parser.add_argument("--clear-cache", action="store_true", help="清空缓存后执行")
    args = parser.parse_args()

    # ── Smoke query mode ──
    if args.smoke_query:
        api_key = get_api_key()
        if not api_key:
            print("⚠  未设置 AMAP_API_KEY，无法执行查询。")
            sys.exit(1)
        config_path = os.path.join(PROJECT_ROOT, "config", "brand_poi_compare.yaml")
        with open(config_path, encoding="utf-8") as f:
            config = yaml.safe_load(f)
        print(f"=== API Smoke Test ===")
        print(f"query: {args.smoke_query}")
        print(f"city: {args.city}")
        print(f"debug: {args.debug_api}")
        print(f"no_cache: {args.no_cache}")
        smoke_query(config, api_key, args.smoke_query, args.city,
                     debug=args.debug_api, no_cache=args.no_cache)
        return

    # ── Normal scan mode ──
    if not args.date_str:
        parser.error("--date is required for scan mode (use --smoke-query for API test)")

    crawl_date = date.fromisoformat(args.date_str)
    city = args.city
    api_key = get_api_key()

    if args.clear_cache:
        clear_cache()
    if args.debug_api:
        set_debug(True)
    if args.no_cache:
        # Disable cache by not loading cached data
        pass

    config_path = os.path.join(PROJECT_ROOT, "config", "brand_poi_compare.yaml")
    with open(config_path, encoding="utf-8") as f:
        config = yaml.safe_load(f)

    total_queries = sum(len(b.get("queries", [])) for b in config["brands"])
    estimated = estimate_requests(config, args.scan_mode)
    budget = args.max_total_requests or config["scan_strategy"]["max_total_requests"]

    print(f"=== 品牌 POI 对比观察 ===")
    print(f"scan_mode: {args.scan_mode}")
    print(f"brands: {len(config['brands'])}")
    print(f"queries: {total_queries}")
    print(f"estimated_requests: <= {estimated}")
    if args.scan_mode in ("around_fallback", "grid_around"):
        fb = config.get("fallback_scan_points", [])
        print(f"fallback_scan_points: {len(fb)}")
    print(f"max_total_requests: {budget}")
    print(f"debug_api: {args.debug_api}")

    if estimated > budget:
        print(f"\n[中止] 预计请求数 {estimated}，超过 max_total_requests={budget}。")
        print(f"请使用 --scan-mode text_city_first，或显式提高 --max-total-requests。")
        sys.exit(1)

    if args.dry_run_plan:
        print(f"\n[dry-run] 仅打印计划，未发起任何请求。")
        return

    csv_path = os.path.join(PROJECT_ROOT, "data", "brand_poi",
                            f"{city}_brand_poi_{crawl_date.isoformat()}.csv")
    json_path = os.path.join(PROJECT_ROOT, "data", "brand_poi",
                             f"{city}_brand_poi_{crawl_date.isoformat()}.json")
    map_path = os.path.join(PROJECT_ROOT, "reports", "maps",
                            f"{crawl_date.isoformat()}_{city}_brand_poi_compare.html")
    report_path = os.path.join(PROJECT_ROOT, "reports",
                               f"{crawl_date.isoformat()}_{city}_brand_poi_compare.md")

    if api_key:
        print(f"\n[扫描] 使用高德 API (key: {api_key[:6]}...)")
        poi_rows = scan_brand_pois(config, crawl_date, api_key=api_key,
                                    scan_mode=args.scan_mode)
    else:
        print("\n⚠  未设置 AMAP_API_KEY，无法执行真实 POI 扫描。")
        poi_rows = []

    print(f"\n[输出] CSV: {csv_path}")
    write_csv(poi_rows, csv_path)
    print(f"       JSON: {json_path}")
    write_json(poi_rows, json_path)

    from dotenv import load_dotenv
    load_dotenv()
    js_key = os.environ.get("AMAP_JS_API_KEY", "").strip()
    sec_code = os.environ.get("AMAP_SECURITY_JS_CODE", "").strip()
    has_js_key = bool(js_key)
    has_sec_code = bool(sec_code)

    print(f"\n[地图] provider: {args.map_provider}")
    print(f"       JS API key: {'✅' if has_js_key else '❌'}")
    generate_brand_poi_map(
        poi_rows=poi_rows,
        output_path=map_path,
        crawl_date=crawl_date,
        city=city,
        api_key_available=bool(api_key),
        has_js_key=has_js_key,
        has_sec_code=has_sec_code,
        js_key=js_key,
        sec_code=sec_code,
    )
    print(f"       地图: {map_path}")

    print(f"\n[报告] {report_path}")
    generate_brand_poi_report(
        poi_rows=poi_rows,
        output_path=report_path,
        crawl_date=crawl_date,
        city=city,
        csv_path=csv_path,
        json_path=json_path,
        map_path=map_path,
    )

    print(f"\n✅ 品牌 POI 对比观察完成。")
    print(f"   CSV: {csv_path}")
    print(f"   JSON: {json_path}")
    print(f"   地图: {map_path}")
    print(f"   报告: {report_path}")


if __name__ == "__main__":
    main()
