#!/usr/bin/env python3
import argparse
import os
import sys
import warnings
from datetime import date

import yaml

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, PROJECT_ROOT)

from src.amap_client import (
    CollectionState,
    has_api_key,
    build_fallback_snapshot,
    write_snapshot_csv,
    fetch_poi_around_budgeted,
    FETCH_STATUS_API,
    FETCH_STATUS_CACHE,
    FETCH_STATUS_SKIPPED,
    write_skipped_csv,
    write_collection_summary,
)
from src.change_detector import (
    load_snapshot,
    find_previous_snapshot,
    detect_changes,
    generate_baseline_events,
    write_change_events_csv,
)
from src.scorer import (
    load_district_config,
    compute_change_scores,
    write_change_scores_csv,
    write_scores_csv,
    score_districts,
)
from src.report_writer import generate_report


def main():
    parser = argparse.ArgumentParser(description="where2go-weekend: 城市变化雷达")
    parser.add_argument(
        "--weekend-date", dest="weekend_date_str",
        help="目标周末日期，格式 YYYY-MM-DD",
    )
    parser.add_argument(
        "--snapshot-date", dest="snapshot_date_str",
        help="POI 快照采集日期，默认今天，格式 YYYY-MM-DD",
    )
    parser.add_argument(
        "--date", dest="date_deprecated",
        help="[已弃用] 请使用 --weekend-date",
    )
    parser.add_argument("--force", action="store_true", help="忽略缓存，重新请求 API")
    args = parser.parse_args()

    today = date.today()

    # Deprecated --date handling
    if args.date_deprecated:
        if args.weekend_date_str:
            parser.error("不能同时使用 --date 和 --weekend-date。请只使用 --weekend-date。")
        print("⚠  warning: `--date` is deprecated. Please use `--weekend-date`. "
              "Snapshot date defaults to today.", file=sys.stderr)
        weekend_date = date.fromisoformat(args.date_deprecated)
    elif args.weekend_date_str:
        weekend_date = date.fromisoformat(args.weekend_date_str)
    else:
        parser.error("请指定 --weekend-date (或已弃用的 --date)")

    if args.snapshot_date_str:
        snapshot_date = date.fromisoformat(args.snapshot_date_str)
    else:
        snapshot_date = today

    print(f"      快照日期: {snapshot_date.isoformat()}, 周末目标: {weekend_date.isoformat()}")

    districts_path = os.path.join(PROJECT_ROOT, "config", "districts.yaml")
    categories_path = os.path.join(PROJECT_ROOT, "config", "categories.yaml")
    budget_path = os.path.join(PROJECT_ROOT, "config", "query_budget.yaml")
    sample_poi_path = os.path.join(PROJECT_ROOT, "data", "sample_poi.csv")
    snapshot_dir = os.path.join(PROJECT_ROOT, "data", "poi_snapshots")
    scores_path = os.path.join(PROJECT_ROOT, "data", "district_scores.csv")
    change_scores_path = os.path.join(PROJECT_ROOT, "data", "district_change_scores.csv")
    change_events_path = os.path.join(PROJECT_ROOT, "data", "poi_change_events.csv")
    skipped_path = os.path.join(PROJECT_ROOT, "data", "skipped_queries.csv")
    summary_path = os.path.join(PROJECT_ROOT, "data", "collection_summary.csv")
    reports_dir = os.path.join(PROJECT_ROOT, "reports")

    print("[1/6] 读取街区配置...")
    with open(districts_path, encoding="utf-8") as f:
        district_config = yaml.safe_load(f)
    district_map = {d["district_id"]: d for d in district_config["districts"]}
    print(f"      已加载 {len(district_map)} 个街区配置")

    print("[2/6] 采集 POI 快照...")

    with open(budget_path, encoding="utf-8") as f:
        budget_config = yaml.safe_load(f)

    use_real_api = has_api_key()
    state = CollectionState(
        daily_max=budget_config.get("daily_max_requests", 30),
        per_district_max=budget_config.get("per_district_max_requests", 10),
        force=args.force,
        api_key_present=use_real_api,
    )

    with open(categories_path, encoding="utf-8") as f:
        cat_config = yaml.safe_load(f)

    keyword_plan = []
    for cat in cat_config["categories"]:
        cat_id = cat["category_id"]
        for kw in cat.get("query_keywords", []):
            keyword_plan.append((kw, cat_id))

    snapshot_rows = []
    needs_fallback = False

    if use_real_api:
        print("      检测到 AMAP_API_KEY，使用高德 API 采集")
        district_summaries = []

        for did, dcfg in district_map.items():
            tier_key = did
            tier = budget_config.get("district_tiers", {}).get(tier_key, "C")
            tier_rules = budget_config.get("tier_rules", {})
            max_kw = tier_rules.get(tier, {}).get("max_keywords", 999)
            max_pages = tier_rules.get(tier, {}).get("max_pages", 1)

            district_planned = 0
            district_api = 0
            district_cache = 0
            district_skipped = 0

            # Track keyword skip for tier limits
            for kw, cat_id in keyword_plan:
                pass
            # Reserve slots for tier limit calculation
            kw_index = 0
            page_district_pois = []

            for page in range(max_pages):
                kw_index = 0
                for kw, cat_id in keyword_plan:
                    if kw_index >= max_kw:
                        state.record_skipped(
                            did, dcfg["name"], kw, cat_id,
                            "超出 tier 关键词上限"
                        )
                        district_skipped += 1
                        continue
                    kw_index += 1
                    district_planned += 1

                    pois, status = fetch_poi_around_budgeted(
                        query=kw,
                        center_lng=dcfg["center_lng"],
                        center_lat=dcfg["center_lat"],
                        district_id=did,
                        district_name=dcfg["name"],
                        cat_id=cat_id,
                        snapshot_date=snapshot_date,
                        radius_m=dcfg.get("radius_m", 500),
                        page=page,
                        state=state,
                    )

                    if status == FETCH_STATUS_API:
                        district_api += 1
                    elif status == FETCH_STATUS_CACHE:
                        district_cache += 1
                    elif status == FETCH_STATUS_SKIPPED:
                        district_skipped += 1

                    page_district_pois.extend(pois)

            snapshot_rows.extend(page_district_pois)

            if not page_district_pois and max_pages > 0:
                needs_fallback = True

            district_summaries.append({
                "run_date": today.isoformat(),
                "snapshot_date": snapshot_date.isoformat(),
                "weekend_date": weekend_date.isoformat(),
                "district_id": did,
                "district_name": dcfg["name"],
                "planned_queries": district_planned,
                "api_requests_used": district_api,
                "cache_hits": district_cache,
                "skipped_queries": district_skipped,
                "fallback_used": "no",
                "poi_count": len(page_district_pois),
                "notes": "",
            })

        if needs_fallback or not snapshot_rows:
            if not snapshot_rows:
                print("      高德 API 未返回数据，回退到 sample 数据")
                state.fallback_used = True
                snapshot_rows = build_fallback_snapshot(sample_poi_path, snapshot_date)
            for s in district_summaries:
                if s["poi_count"] == 0:
                    s["fallback_used"] = "yes (no real data)"

        write_collection_summary(state, summary_path, snapshot_date, weekend_date,
                                 district_summaries)
        print(f"      API 请求: {state.api_requests_used}, "
              f"缓存命中: {state.cache_hits}, "
              f"跳过: {state.skipped_queries}")
    else:
        print("      未设置 AMAP_API_KEY，使用 sample POI 数据")
        state.fallback_used = True
        snapshot_rows = build_fallback_snapshot(sample_poi_path, snapshot_date)

        district_summaries = []
        for did, dcfg in district_map.items():
            cnt = sum(1 for r in snapshot_rows if r["district_id"] == did)
            district_summaries.append({
                "run_date": today.isoformat(),
                "snapshot_date": snapshot_date.isoformat(),
                "weekend_date": weekend_date.isoformat(),
                "district_id": did,
                "district_name": dcfg["name"],
                "planned_queries": 0,
                "api_requests_used": 0,
                "cache_hits": 0,
                "skipped_queries": 0,
                "fallback_used": "yes",
                "poi_count": cnt,
                "notes": "sample fallback",
            })
        write_collection_summary(state, summary_path, snapshot_date, weekend_date,
                                 district_summaries)

    if state.skipped_tasks:
        write_skipped_csv(state.skipped_tasks, skipped_path)
        print(f"      ⚠ 部分查询被跳过，详情: {skipped_path}")

    snapshot_path = os.path.join(
        snapshot_dir, f"{snapshot_date.isoformat()}_poi_snapshot.csv"
    )
    write_snapshot_csv(snapshot_rows, snapshot_path)
    print(f"      快照已写入 {snapshot_path}（{len(snapshot_rows)} 条）")

    print("[3/6] 检测历史快照...")
    prev_path, prev_date = find_previous_snapshot(snapshot_dir, snapshot_date)
    if prev_path:
        print(f"      发现历史快照: {prev_date}")
        previous_rows = load_snapshot(prev_path)
        print(f"      历史快照共 {len(previous_rows)} 条 POI")
        has_history = True
    else:
        print("      无历史快照，当前为第一期基准快照")
        previous_rows = None
        has_history = False

    print("[4/6] 识别变化事件...")
    if has_history:
        change_events = detect_changes(
            snapshot_rows, previous_rows, snapshot_date, prev_date
        )
    else:
        change_events = generate_baseline_events(snapshot_rows, snapshot_date)
    write_change_events_csv(change_events, change_events_path)
    print(f"      已识别 {len(change_events)} 个变化事件")
    print(f"      已写入 {change_events_path}")

    print("[5/6] 计算街区变化评分...")
    change_scores = compute_change_scores(
        current_rows=snapshot_rows,
        previous_rows=previous_rows,
        change_events=change_events,
        district_config=district_map,
        score_date=snapshot_date,
        target_weekend_date=weekend_date,
    )
    write_change_scores_csv(change_scores, change_scores_path)
    print(f"      变化评分已写入 {change_scores_path}")

    weekend_scores = score_districts(snapshot_rows, district_map)
    write_scores_csv(weekend_scores, scores_path)

    print("[6/6] 生成城市变化雷达报告...")
    report_path = generate_report(
        change_scores=change_scores,
        change_events=change_events,
        snapshot_rows=snapshot_rows,
        output_dir=reports_dir,
        snapshot_date=snapshot_date,
        weekend_date=weekend_date,
        has_previous_snapshot=has_history,
        collection_state=state,
    )
    print(f"      报告已生成: {report_path}")

    print("\n✅ 完成！城市变化雷达已更新。")


if __name__ == "__main__":
    main()
