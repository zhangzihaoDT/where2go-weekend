#!/usr/bin/env python3
"""
Unified CLI for Brand POI workflows.

Commands:
  plan     Dry-run: show request budget without calling API
  scan     API scan → write snapshot
  map      Read snapshot → HTML map + Markdown report (no API)
  analyze  Read snapshot → enriched CSV + summary JSON (no API)
  slice    Read snapshot → filtered CSV (no API)
  compare  Diff two snapshots → delta report (no API)
  run      plan + scan + map + analyze

Usage:
  python3 src/brand_poi.py scan --city 上海 --date 2026-07-08
  python3 src/brand_poi.py analyze --dataset 2026-07-08_上海
  python3 src/brand_poi.py map --dataset 2026-07-08_上海
  python3 src/brand_poi.py slice --dataset 2026-07-08_上海 --by brand:蔚来
  python3 src/brand_poi.py compare --base 2026-07-01_上海 --target 2026-07-08_上海
  python3 src/brand_poi.py run --city 上海 --date 2026-07-08
"""

import argparse
import csv
import os
import sys
from collections import Counter
from datetime import date

import yaml

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, PROJECT_ROOT)

from src.brand_poi_scanner import (
    scan_to_snapshot,
    estimate_requests,
    SCAN_MODES,
    clear_cache,
    set_debug,
    set_debug_cache,
    CSV_FIELDS,
)
from src.brand_poi_map_writer import generate_brand_poi_map, generate_brand_poi_report
from src.brand_poi_analyzer import run_analyzer
from src.brand_poi_snapshot import (
    BrandPoiSnapshot,
    make_snapshot_id,
    parse_snapshot_id,
    write_compare_result,
    SNAPSHOT_BASE,
    COMPARE_BASE,
)


def _load_config() -> dict:
    path = os.path.join(PROJECT_ROOT, "config", "brand_poi_compare.yaml")
    with open(path, encoding="utf-8") as f:
        return yaml.safe_load(f)


def _get_api_key():
    from src.amap_client import get_api_key
    return get_api_key()


# ── Plan ──

def cmd_plan(args):
    config = _load_config()
    scan_mode = args.scan_mode or "text_city_first"
    estimated = estimate_requests(config, scan_mode)
    total_queries = sum(len(b.get("queries", [])) for b in config["brands"])
    budget = args.max_total_requests or config["scan_strategy"]["max_total_requests"]
    print("=== Brand POI Plan ===")
    print(f"  scan_mode:       {scan_mode}")
    print(f"  brands:          {len(config['brands'])}")
    print(f"  queries:         {total_queries}")
    print(f"  estimated_reqs:  <= {estimated}")
    print(f"  budget:          {budget}")
    if estimated > budget:
        print(f"\n  [ABORT] estimated {estimated} > budget {budget}")
        sys.exit(1)


# ── Scan (calls API) ──

def cmd_scan(args):
    config = _load_config()
    city = args.city or "上海"
    date_str = args.date or date.today().isoformat()
    crawl_date = date.fromisoformat(date_str)
    api_key = _get_api_key()

    if args.clear_cache:
        clear_cache()
    if args.debug_api:
        set_debug(True)
    if args.debug_cache:
        set_debug_cache(True)

    scan_mode = args.scan_mode or "text_city_first"

    if not api_key:
        print("[ERROR] AMAP_API_KEY not set")
        sys.exit(1)

    print(f"=== Scan: {city} {date_str} ===")
    rows = scan_to_snapshot(config, crawl_date, api_key=api_key, scan_mode=scan_mode)
    snap_id = make_snapshot_id(date_str, city)
    print(f"  Total POI: {len(rows)}")
    print(f"  Snapshot: {BrandPoiSnapshot(snap_id).dir}")


# ── Map (no API) ──

def cmd_map(args):
    snap = BrandPoiSnapshot(args.dataset)
    if not snap.exists():
        print(f"[ERROR] Snapshot not found: {snap.dir}")
        sys.exit(1)
    rows = snap.read_csv()
    city = snap.city
    crawl_date = date.fromisoformat(snap.date_str)

    map_path = os.path.join(
        PROJECT_ROOT, "reports", "maps",
        f"{snap.snapshot_id}_brand_poi_compare.html",
    )
    report_path = os.path.join(
        PROJECT_ROOT, "reports",
        f"{snap.snapshot_id}_brand_poi_compare.md",
    )

    from dotenv import load_dotenv
    load_dotenv()
    js_key = os.environ.get("AMAP_JS_API_KEY", "").strip()
    sec_code = os.environ.get("AMAP_SECURITY_JS_CODE", "").strip()
    has_js_key = bool(js_key)
    has_sec_code = bool(sec_code)

    generate_brand_poi_map(
        poi_rows=rows, output_path=map_path, crawl_date=crawl_date, city=city,
        api_key_available=True, has_js_key=has_js_key,
        has_sec_code=has_sec_code, js_key=js_key, sec_code=sec_code,
    )
    generate_brand_poi_report(
        poi_rows=rows, output_path=report_path, crawl_date=crawl_date, city=city,
        csv_path=snap.csv_path, json_path=snap.json_path, map_path=map_path,
    )
    print(f"  Map:    {map_path}")
    print(f"  Report: {report_path}")


# ── Analyze (no API) ──

def cmd_analyze(args):
    snap = BrandPoiSnapshot(args.dataset)
    if not snap.exists():
        print(f"[ERROR] Snapshot not found: {snap.dir}")
        sys.exit(1)

    rows = snap.read_csv()
    result = run_analyzer(rows=rows, city=snap.city, date_str=snap.date_str, top_n=args.top_n)
    snap.write_enriched_csv(result["enriched_rows"])
    snap.write_summary_json(result["summary"])
    report_path = os.path.join(PROJECT_ROOT, "reports", f"{snap.snapshot_id}_brand_poi_analysis.md")
    with open(report_path, "w", encoding="utf-8") as f:
        f.write(result["report_md"])
    snap.write_analysis_report(result["report_md"])

    print(f"  Enriched CSV: {snap.enriched_csv_path}")
    print(f"  Summary JSON: {snap.summary_json_path}")
    print(f"  Report:       {report_path}")


# ── Slice (no API) ──

def cmd_slice(args):
    snap = BrandPoiSnapshot(args.dataset)
    if not snap.exists():
        print(f"[ERROR] Snapshot not found: {snap.dir}")
        sys.exit(1)
    rows = snap.read_csv()

    if args.by:
        for clause in args.by:
            if ":" in clause:
                key, val = clause.split(":", 1)
            else:
                print(f"[ERROR] --by expects key:value, got '{clause}'")
                sys.exit(1)
            key_map = {
                "brand": "brand_name", "kind": "poi_kind",
                "district": "district", "loc": "store_location_type",
            }
            col = key_map.get(key, key)
            rows = [r for r in rows if r.get(col) == val]

    out = args.output or os.path.join(snap.dir, f"slice_{snap.snapshot_id}.csv")
    os.makedirs(os.path.dirname(out) or ".", exist_ok=True)
    with open(out, "w", encoding="utf-8", newline="") as f:
        fieldnames = CSV_FIELDS
        w = csv.DictWriter(f, fieldnames=fieldnames)
        w.writeheader()
        for r in rows:
            w.writerow({k: r.get(k, "") for k in fieldnames})
    print(f"  Sliced {len(rows)} rows -> {out}")


# ── Compare (no API) ──

def cmd_compare(args):
    snap_base = BrandPoiSnapshot(args.base)
    snap_target = BrandPoiSnapshot(args.target)
    if not snap_base.exists():
        print(f"[ERROR] Snapshot base not found: {snap_base.dir}")
        sys.exit(1)
    if not snap_target.exists():
        print(f"[ERROR] Snapshot target not found: {snap_target.dir}")
        sys.exit(1)

    rows_a = snap_base.read_csv()
    rows_b = snap_target.read_csv()

    index_a = {}
    for r in rows_a:
        pid = r.get("poi_id", "")
        if pid:
            index_a[pid] = r
    index_b = {}
    for r in rows_b:
        pid = r.get("poi_id", "")
        if pid:
            index_b[pid] = r

    keys_a = set(index_a.keys())
    keys_b = set(index_b.keys())
    new_keys = keys_b - keys_a
    removed_keys = keys_a - keys_b

    def counts(rows):
        return {
            "brand": dict(Counter(r.get("brand_name", "") for r in rows)),
            "kind": dict(Counter(r.get("poi_kind", "") for r in rows)),
            "district": dict(Counter(r.get("district", "") for r in rows)),
        }

    ca = counts(rows_a)
    cb = counts(rows_b)

    new_pois = [index_b[k] for k in sorted(new_keys)]
    removed_pois = [index_a[k] for k in sorted(removed_keys)]

    result = {
        "snapshot_base": args.base,
        "snapshot_target": args.target,
        "total_base": len(rows_a),
        "total_target": len(rows_b),
        "delta_poi": len(rows_b) - len(rows_a),
        "new_count": len(new_pois),
        "removed_count": len(removed_pois),
        "new_pois": [
            {"poi_id": r.get("poi_id"), "name": r.get("name"),
             "brand_name": r.get("brand_name"), "poi_kind": r.get("poi_kind"),
             "district": r.get("district")}
            for r in new_pois[:50]
        ],
        "removed_pois": [
            {"poi_id": r.get("poi_id"), "name": r.get("name"),
             "brand_name": r.get("brand_name"), "poi_kind": r.get("poi_kind"),
             "district": r.get("district")}
            for r in removed_pois[:50]
        ],
        "counts_base": ca,
        "counts_target": cb,
    }

    md = []
    md.append(f"# Brand POI 快照对比\n")
    md.append(f"**Base**: {args.base} (n={len(rows_a)})")
    md.append(f"**Target**: {args.target} (n={len(rows_b)})")
    md.append(f"| 指标 | 数值 |")
    md.append(f"|---|---:|")
    md.append(f"| 新增 POI | {len(new_pois)} |")
    md.append(f"| 消失 POI | {len(removed_pois)} |")
    md.append(f"| 净变化 | {result['delta_poi']:+d} |\n")

    md.append("### 品牌变化\n")
    md.append("| 品牌 | Base | Target | 变化 |")
    md.append("|---|---:|---:|---:|")
    for b in sorted(set(list(ca["brand"].keys()) + list(cb["brand"].keys()))):
        va = ca["brand"].get(b, 0)
        vb = cb["brand"].get(b, 0)
        md.append(f"| {b} | {va} | {vb} | {vb - va:+d} |")

    md.append("\n### 功能类型变化\n")
    md.append("| 类型 | Base | Target | 变化 |")
    md.append("|---|---:|---:|---:|")
    for k in sorted(set(list(ca["kind"].keys()) + list(cb["kind"].keys()))):
        va = ca["kind"].get(k, 0)
        vb = cb["kind"].get(k, 0)
        md.append(f"| {k} | {va} | {vb} | {vb - va:+d} |")

    md.append("\n### 区县变化\n")
    md.append("| 区县 | Base | Target | 变化 |")
    md.append("|---|---:|---:|---:|")
    for d in sorted(set(list(ca["district"].keys()) + list(cb["district"].keys()))):
        va = ca["district"].get(d, 0)
        vb = cb["district"].get(d, 0)
        md.append(f"| {d} | {va} | {vb} | {vb - va:+d} |")

    if new_pois:
        md.append(f"\n### 新增 POI (前 {min(50, len(new_pois))} 条)\n")
        md.append("| POI ID | 名称 | 品牌 | 功能类型 | 区县 |")
        md.append("|---|---|---|---|---|")
        for p in new_pois[:50]:
            md.append(f"| {p.get('poi_id', '')} | {p.get('name', '')} | {p.get('brand_name', '')} | {p.get('poi_kind', '')} | {p.get('district', '')} |")

    if removed_pois:
        md.append(f"\n### 消失 POI (前 {min(50, len(removed_pois))} 条)\n")
        md.append("| POI ID | 名称 | 品牌 | 功能类型 | 区县 |")
        md.append("|---|---|---|---|---|")
        for p in removed_pois[:50]:
            md.append(f"| {p.get('poi_id', '')} | {p.get('name', '')} | {p.get('brand_name', '')} | {p.get('poi_kind', '')} | {p.get('district', '')} |")

    result["markdown"] = "\n".join(md)

    out_dir = write_compare_result(args.base, args.target, result)
    print(f"  Compare written: {out_dir}")


# ── Run (full pipeline) ──

def cmd_run(args):
    config = _load_config()
    city = args.city or "上海"
    date_str = args.date or date.today().isoformat()
    crawl_date = date.fromisoformat(date_str)
    api_key = _get_api_key()
    scan_mode = args.scan_mode or "text_city_first"

    if args.clear_cache:
        clear_cache()
    if args.debug_api:
        set_debug(True)
    if args.debug_cache:
        set_debug_cache(True)

    print(f"=== Brand POI Run: {city} {date_str} ===")

    estimated = estimate_requests(config, scan_mode)
    budget = args.max_total_requests or config["scan_strategy"]["max_total_requests"]
    if estimated > budget:
        print(f"[ABORT] estimated {estimated} > budget {budget}")
        sys.exit(1)

    if not api_key:
        print("[ERROR] AMAP_API_KEY not set")
        sys.exit(1)
    rows = scan_to_snapshot(config, crawl_date, api_key=api_key, scan_mode=scan_mode)
    print(f"  Scan complete: {len(rows)} POIs")

    map_path = os.path.join(PROJECT_ROOT, "reports", "maps",
                            f"{date_str}_{city}_brand_poi_compare.html")
    report_path = os.path.join(PROJECT_ROOT, "reports",
                               f"{date_str}_{city}_brand_poi_compare.md")
    from dotenv import load_dotenv
    load_dotenv()
    js_key = os.environ.get("AMAP_JS_API_KEY", "").strip()
    sec_code = os.environ.get("AMAP_SECURITY_JS_CODE", "").strip()
    generate_brand_poi_map(
        poi_rows=rows, output_path=map_path, crawl_date=crawl_date, city=city,
        api_key_available=bool(api_key), has_js_key=bool(js_key),
        has_sec_code=bool(sec_code), js_key=js_key, sec_code=sec_code,
    )
    snap = BrandPoiSnapshot.from_date_city(date_str, city)
    generate_brand_poi_report(
        poi_rows=rows, output_path=report_path, crawl_date=crawl_date, city=city,
        csv_path=snap.csv_path, json_path=snap.json_path, map_path=map_path,
    )

    result = run_analyzer(rows=rows, city=city, date_str=date_str, top_n=args.top_n)
    snap.write_enriched_csv(result["enriched_rows"])
    snap.write_summary_json(result["summary"])
    report_path = os.path.join(PROJECT_ROOT, "reports", f"{date_str}_{city}_brand_poi_analysis.md")
    with open(report_path, "w", encoding="utf-8") as f:
        f.write(result["report_md"])
    snap.write_analysis_report(result["report_md"])

    print(f"\n✅ Run complete. Snapshot: {snap.dir}")
    print(f"   Map:    {map_path}")
    print(f"   Report: {report_path}")


# ── CLI parser ──

def main():
    parser = argparse.ArgumentParser(description="Brand POI unified CLI")
    sub = parser.add_subparsers(dest="command", required=True)

    p = sub.add_parser("plan", help="Dry-run estimate of API requests")
    p.add_argument("--city", default="上海")
    p.add_argument("--date")
    p.add_argument("--scan-mode", choices=SCAN_MODES)
    p.add_argument("--max-total-requests", type=int)
    p.set_defaults(func=cmd_plan)

    p = sub.add_parser("scan", help="API scan → write snapshot")
    p.add_argument("--city", default="上海")
    p.add_argument("--date", required=True)
    p.add_argument("--scan-mode", choices=SCAN_MODES)
    p.add_argument("--debug-api", action="store_true")
    p.add_argument("--debug-cache", action="store_true")
    p.add_argument("--clear-cache", action="store_true")
    p.set_defaults(func=cmd_scan)

    p = sub.add_parser("map", help="Snapshot → HTML map + MD report (no API)")
    p.add_argument("--dataset", required=True, help="snapshot ID, e.g. 2026-07-08_上海")
    p.set_defaults(func=cmd_map)

    p = sub.add_parser("analyze", help="Snapshot → enriched CSV + summary (no API)")
    p.add_argument("--dataset", required=True)
    p.add_argument("--top-n", type=int, default=20)
    p.set_defaults(func=cmd_analyze)

    p = sub.add_parser("slice", help="Snapshot → filtered CSV (no API)")
    p.add_argument("--dataset", required=True)
    p.add_argument("--by", action="append",
                   help="filter: --by brand:蔚来 --by kind:user_center")
    p.add_argument("--output")
    p.set_defaults(func=cmd_slice)

    p = sub.add_parser("compare", help="Diff two snapshots (no API)")
    p.add_argument("--base", required=True, help="older snapshot ID")
    p.add_argument("--target", required=True, help="newer snapshot ID")
    p.set_defaults(func=cmd_compare)

    p = sub.add_parser("run", help="Full pipeline: plan + scan + map + analyze")
    p.add_argument("--city", default="上海")
    p.add_argument("--date", required=True)
    p.add_argument("--scan-mode", choices=SCAN_MODES)
    p.add_argument("--debug-api", action="store_true")
    p.add_argument("--debug-cache", action="store_true")
    p.add_argument("--clear-cache", action="store_true")
    p.add_argument("--max-total-requests", type=int)
    p.add_argument("--top-n", type=int, default=20)
    p.set_defaults(func=cmd_run)

    args = parser.parse_args()
    args.func(args)


if __name__ == "__main__":
    main()
