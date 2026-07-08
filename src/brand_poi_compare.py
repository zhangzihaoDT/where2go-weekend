#!/usr/bin/env python3
"""
Legacy CLI entry — delegates to unified brand_poi.py run.

Usage:
  python3 src/brand_poi_compare.py --date 2026-07-08
  python3 src/brand_poi_compare.py --smoke-query 蔚来中心 --debug-api --no-cache
  python3 src/brand_poi_compare.py --date 2026-07-08 --clear-cache
  python3 src/brand_poi_compare.py --date 2026-07-08 --dry-run-plan
"""

import os
import sys
from datetime import date

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, PROJECT_ROOT)

from src.brand_poi_scanner import SCAN_MODES, smoke_query, clear_cache, set_debug, set_debug_cache
from src.amap_client import get_api_key


def main():
    import argparse
    parser = argparse.ArgumentParser(description="品牌 POI 对比观察")
    parser.add_argument("--city", default="上海")
    parser.add_argument("--date", dest="date_str")
    parser.add_argument("--scan-mode", default="text_city_first", choices=SCAN_MODES)
    parser.add_argument("--max-total-requests", type=int, default=None)
    parser.add_argument("--dry-run-plan", action="store_true")
    parser.add_argument("--debug-api", action="store_true")
    parser.add_argument("--debug-cache", action="store_true")
    parser.add_argument("--smoke-query", help="只执行一次 API 查询用于诊断")
    parser.add_argument("--no-cache", action="store_true")
    parser.add_argument("--clear-cache", action="store_true")
    args = parser.parse_args()

    # ── Smoke query mode (standalone, not delegated) ──
    if args.smoke_query:
        api_key = get_api_key()
        if not api_key:
            print("⚠  未设置 AMAP_API_KEY，无法执行查询。")
            sys.exit(1)
        import yaml
        config_path = os.path.join(PROJECT_ROOT, "config", "brand_poi_compare.yaml")
        with open(config_path, encoding="utf-8") as f:
            config = yaml.safe_load(f)
        print(f"=== API Smoke Test ===")
        smoke_query(config, api_key, args.smoke_query, args.city,
                     debug=args.debug_api, no_cache=args.no_cache)
        return

    # ── Delegate to unified CLI run ──
    from src.brand_poi import main as unified_main
    import sys as _sys
    _sys.argv = ["brand_poi.py", "run",
                  "--city", args.city,
                  "--date", args.date_str or date.today().isoformat(),
                  "--scan-mode", args.scan_mode]
    if args.debug_api:
        _sys.argv.append("--debug-api")
    if args.debug_cache:
        _sys.argv.append("--debug-cache")
    if args.clear_cache:
        _sys.argv.append("--clear-cache")
    if args.max_total_requests:
        _sys.argv.extend(["--max-total-requests", str(args.max_total_requests)])
    if args.dry_run_plan:
        # 'brand_poi.py plan' uses same args as 'run' minus date requirement
        _sys.argv[1] = "plan"
    unified_main()


if __name__ == "__main__":
    main()
