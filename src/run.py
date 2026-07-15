#!/usr/bin/env python3
import argparse
import os
import re
import sys
import unicodedata
from collections import defaultdict
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
    FETCH_STATUS_API_FAILED,
    EXEC_STATUS_SUCCESS,
    EXEC_STATUS_EMPTY,
    EXEC_STATUS_CACHE_HIT,
    EXEC_STATUS_SKIPPED_BUDGET,
    EXEC_STATUS_SKIPPED_KEYWORD_LIMIT,
    EXEC_STATUS_FAILED_API,
    write_skipped_csv,
    write_collection_summary,
    compute_config_fingerprint,
    write_manifest_json,
    compute_snapshot_source_mode,
    compute_snapshot_completeness,
    read_manifest,
    compare_is_allowed,
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
from src.map_writer import generate_map
from src.collection_scheduler import (
    build_plan,
    estimate_requests,
    build_second_page_slots,
    EXEC_STATUS_NOT_ATTEMPTED_QUOTA_BLOCKED,
    QPSTimer,
    RequestPlan,
    RequestSlot,
)


COORD_MODES = ("approx_wgs84", "raw_gcj02")
MAP_PROVIDERS = ("amap_js", "leaflet_osm")


def deduplicate_snapshot_rows(rows: list[dict]) -> list[dict]:
    seen = set()
    result = []
    removed = 0
    for row in rows:
        did = row.get("district_id", "")
        cat = row.get("category_id", "")
        pid = row.get("poi_id", "")
        if pid:
            key = (did, cat, pid)
        else:
            name = unicodedata.normalize("NFKC", (row.get("name", "") or "").strip().lower())
            name = re.sub(r"\s+", "", name)
            addr = unicodedata.normalize("NFKC", (row.get("address", "") or "").strip().lower())
            addr = re.sub(r"\s+", "", addr)
            key = (did, cat, name, addr)
        if key in seen:
            removed += 1
            continue
        seen.add(key)
        result.append(row)
    if removed > 0:
        print(f"      去重: 输入 {len(rows)} 条, 输出 {len(result)} 条, 移除 {removed} 条")
    return result


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
    parser.add_argument("--no-map", action="store_true", help="跳过地图生成")
    parser.add_argument(
        "--map-provider", dest="map_provider", default="amap_js",
        choices=MAP_PROVIDERS,
        help=f"地图 provider，默认 amap_js，可选 {MAP_PROVIDERS}",
    )
    parser.add_argument(
        "--coord-mode", dest="coord_mode", default="approx_wgs84",
        choices=COORD_MODES,
        help=f"坐标模式（仅 leaflet_osm 时生效），默认 approx_wgs84，可选 {COORD_MODES}",
    )
    parser.add_argument(
        "--estimate-requests", action="store_true",
        help="估算请求量并退出，不调用 API",
    )
    args = parser.parse_args()

    today = date.today()

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

    if args.map_provider == "amap_js" and args.coord_mode != "approx_wgs84":
        print("⚠  warning: coord_mode is ignored when map_provider=amap_js.", file=sys.stderr)
    print(f"      快照日期: {snapshot_date.isoformat()}, 周末目标: {weekend_date.isoformat()}, "
          f"地图 provider: {args.map_provider}, 坐标模式: {args.coord_mode}")

    districts_path = os.path.join(PROJECT_ROOT, "config", "districts.yaml")
    categories_path = os.path.join(PROJECT_ROOT, "config", "categories.yaml")
    budget_path = os.path.join(PROJECT_ROOT, "config", "query_budget.yaml")
    sample_poi_path = os.path.join(PROJECT_ROOT, "data", "sample_poi.csv")
    snapshot_dir = os.path.join(PROJECT_ROOT, "data", "weekend_district_poi")
    scores_path = os.path.join(PROJECT_ROOT, "data", "district_scores.csv")
    change_scores_path = os.path.join(PROJECT_ROOT, "data", "district_change_scores.csv")
    change_events_path = os.path.join(PROJECT_ROOT, "data", "poi_change_events.csv")
    skipped_path = os.path.join(PROJECT_ROOT, "data", "skipped_queries.csv")
    summary_path = os.path.join(PROJECT_ROOT, "data", "collection_summary.csv")
    reports_dir = os.path.join(PROJECT_ROOT, "reports")
    maps_dir = os.path.join(reports_dir, "maps")

    print("[1/6] 读取街区配置...")
    with open(districts_path, encoding="utf-8") as f:
        district_config = yaml.safe_load(f)
    district_map = {d["district_id"]: d for d in district_config["districts"]}
    print(f"      已加载 {len(district_map)} 个街区配置")

    for did, dcfg in district_map.items():
        tags = dcfg.get("tags", [])
        tag_str = " ".join(tags)
        has_address = bool(dcfg.get("address", "").strip()) if "address" in dcfg else False
        has_source = "coordinate_source" in dcfg
        if "滨江岸线" in tag_str and (not has_address or not has_source):
            print(f"      ⚠ [location-warning] {did} is tagged as riverfront "
                  f"but has no address or coordinate_source.")

    print("[2/6] 采集 POI 快照...")

    with open(budget_path, encoding="utf-8") as f:
        budget_config = yaml.safe_load(f)

    use_real_api = has_api_key()
    state = CollectionState(
        daily_max=budget_config.get("max_requests_per_run") or budget_config.get("daily_max_requests", 30),
        per_district_max=budget_config.get("per_district_max_requests", 10),
        force=args.force,
        api_key_present=use_real_api,
    )
    max_qps = budget_config.get("rate_limit", {}).get("max_qps", 0)
    if max_qps > 0 and use_real_api:
        state.qps_timer = QPSTimer(max_qps=max_qps)

    with open(categories_path, encoding="utf-8") as f:
        cat_config = yaml.safe_load(f)

    keyword_plan = []
    for cat in cat_config["categories"]:
        cat_id = cat["category_id"]
        for kw in cat.get("query_keywords", []):
            keyword_plan.append((kw, cat_id))

    config_fingerprint = compute_config_fingerprint(
        district_config, cat_config, budget_config
    )

    if args.estimate_requests:
        est = estimate_requests(district_config, cat_config, budget_config)
        kw_allowed = est['total_candidates'] - est['keyword_limit_excluded']
        print("=== 请求量估算 ===")
        print(f"  候选请求数:          {est['total_candidates']}")
        print(f"  关键词上限排除:      {est['keyword_limit_excluded']}")
        print(f"  关键词排除后候选:    {kw_allowed}")
        print(f"  基础第一页计划:      {est['first_page_base']}")
        print(f"  动态第二页上限:      {est['second_page_upper']}")
        print(f"  单次运行预算:        {est['max_requests_per_run']}")
        print(f"  预计最少请求数:      {est['estimated_min_requests']}")
        print(f"  预计最多请求数:      {est['estimated_max_requests']}")
        print(f"  分页大小:            {est['page_size']}")
        print(f"  自适应分页:          {est['adaptive_pagination']}")
        print(f"\n  各区域第一页覆盖:")
        for did, cnt in est.get("per_district_first_page", {}).items():
            print(f"    {did}: {cnt} 个关键词")
        return

    snapshot_rows = []
    needs_fallback = False

    if use_real_api:
        print("      检测到 AMAP_API_KEY，使用高德 API 采集")

        plan = build_plan(district_config, cat_config, budget_config)
        kw_allowed = plan.total_candidates - plan.excluded_keyword_limit
        print(f"      候选: {plan.total_candidates} → 排除: {plan.excluded_keyword_limit}(kw) + {plan.excluded_district_budget}(budget) → "
              f"批准: {plan.approved_count}（第一页 {plan.first_page_count}）")

        sch_cfg = budget_config.get("scheduler", {})
        page_size = sch_cfg.get("page_size", 20)
        retry_cfg = budget_config.get("retry_policy", {})

        snapshot_rows = []
        district_summaries = {}
        district_poi_counts: dict[str, int] = {}
        second_page_approved_count = 0
        second_page_not_needed_count = 0
        quota_blocked_count = 0

        for d in district_map.values():
            district_summaries[d["district_id"]] = {
                "run_date": today.isoformat(),
                "snapshot_date": snapshot_date.isoformat(),
                "weekend_date": weekend_date.isoformat(),
                "district_id": d["district_id"],
                "district_name": d["name"],
                "planned_queries": 0,
                "api_requests_used": 0,
                "cache_hits": 0,
                "skipped_queries": 0,
                "fallback_used": "no",
                "poi_count": 0,
                "notes": "",
            }
            district_poi_counts[d["district_id"]] = 0

        # ── Execute first page, breadth-first (round-robin) ──
        for slot_idx, slot in enumerate(plan.approved):
            if state.circuit_breaker_triggered:
                state.record_execution(
                    district_id=slot.district_id,
                    district_name=slot.district_name,
                    category_id=slot.category_id,
                    keyword=slot.keyword,
                    page=slot.page,
                    execution_status=EXEC_STATUS_NOT_ATTEMPTED_QUOTA_BLOCKED,
                    cache_hit=False,
                    result_count=0,
                    skip_reason=f"circuit_breaker: {state.circuit_breaker_infocode}",
                    is_in_approved_plan=True,
                )
                quota_blocked_count += 1
                continue

            dcfg = district_map.get(slot.district_id, {})
            center_lng = dcfg.get("center_lng", 0)
            center_lat = dcfg.get("center_lat", 0)
            radius_m = dcfg.get("radius_m", 500)

            if not state.can_request(slot.district_id):
                continue

            pois, status = fetch_poi_around_budgeted(
                query=slot.keyword,
                center_lng=center_lng,
                center_lat=center_lat,
                district_id=slot.district_id,
                district_name=slot.district_name,
                cat_id=slot.category_id,
                snapshot_date=snapshot_date,
                radius_m=radius_m,
                page=slot.page - 1,
                state=state,
                retry_config=retry_cfg,
            )

            if status == FETCH_STATUS_API:
                exec_status = EXEC_STATUS_SUCCESS if pois else EXEC_STATUS_EMPTY
            elif status == FETCH_STATUS_CACHE:
                exec_status = EXEC_STATUS_CACHE_HIT
            elif status == FETCH_STATUS_SKIPPED:
                exec_status = EXEC_STATUS_SKIPPED_BUDGET
            elif status == FETCH_STATUS_API_FAILED:
                exec_status = EXEC_STATUS_FAILED_API
            else:
                exec_status = status

            state.record_execution(
                district_id=slot.district_id,
                district_name=slot.district_name,
                category_id=slot.category_id,
                keyword=slot.keyword,
                page=slot.page,
                execution_status=exec_status,
                cache_hit=(status == FETCH_STATUS_CACHE),
                result_count=len(pois),
                skip_reason="",
                is_in_approved_plan=True,
            )

            snapshot_rows.extend(pois)
            district_poi_counts[slot.district_id] = district_poi_counts.get(slot.district_id, 0) + len(pois)

        # ── Collect second page candidates AFTER all first pages ──
        second_page_potential = plan.second_page_candidates
        second_page_pool: list[RequestSlot] = []
        for s in plan.approved:
            if not s.is_first_page:
                continue
            if state.circuit_breaker_triggered:
                break
            dcfg = district_map.get(s.district_id, {})
            center_lng = dcfg.get("center_lng", 0)
            center_lat = dcfg.get("center_lat", 0)
            radius_m = dcfg.get("radius_m", 500)

            # Find the first-page execution result for this slot
            fp_execs = [r for r in state.request_log
                        if r["district_id"] == s.district_id
                        and r["keyword"] == s.keyword
                        and r["page"] == s.page
                        and r.get("is_in_approved_plan", True)]
            fp_count = fp_execs[0]["result_count"] if fp_execs else 0
            fp_status = fp_execs[0]["execution_status"] if fp_execs else ""

            if fp_status == EXEC_STATUS_SUCCESS and fp_count > 0:
                sp = build_second_page_slots(
                    plan, s.district_id, s.district_name,
                    s.category_id, s.keyword,
                    fp_count, state.daily_max - state.api_requests_used,
                    page_size, api_count=None,
                )
                second_page_pool.extend(sp)

        # ── Execute second pages round-robin ──
        district_order = [d["district_id"] for d in district_map.values()]
        sp_by_district = defaultdict(list)
        for sp in second_page_pool:
            sp_by_district[sp.district_id].append(sp)
        remaining_dids = [did for did in district_order if sp_by_district.get(did)]
        second_page_candidate_count = len(second_page_pool)
        second_page_approved_count = 0
        second_page_executed_count = 0

        while remaining_dids:
            next_round = []
            for did in remaining_dids:
                if state.circuit_breaker_triggered:
                    quota_blocked_count += len(sp_by_district.get(did, []))
                    continue
                queue = sp_by_district.get(did, [])
                if not queue:
                    continue
                sp_slot = queue.pop(0)
                if not state.can_request(did):
                    continue
                dcfg = district_map.get(did, {})
                clng = dcfg.get("center_lng", 0)
                clat = dcfg.get("center_lat", 0)
                r_m = dcfg.get("radius_m", 500)

                pois2, status2 = fetch_poi_around_budgeted(
                    query=sp_slot.keyword,
                    center_lng=clng, center_lat=clat,
                    district_id=did,
                    district_name=sp_slot.district_name,
                    cat_id=sp_slot.category_id,
                    snapshot_date=snapshot_date,
                    radius_m=r_m,
                    page=sp_slot.page - 1,
                    state=state,
                    retry_config=retry_cfg,
                )
                if status2 == FETCH_STATUS_API:
                    es2 = EXEC_STATUS_SUCCESS if pois2 else EXEC_STATUS_EMPTY
                elif status2 == FETCH_STATUS_CACHE:
                    es2 = EXEC_STATUS_CACHE_HIT
                elif status2 == FETCH_STATUS_API_FAILED:
                    es2 = EXEC_STATUS_FAILED_API
                else:
                    es2 = status2

                state.record_execution(
                    district_id=did, district_name=sp_slot.district_name,
                    category_id=sp_slot.category_id, keyword=sp_slot.keyword,
                    page=sp_slot.page, execution_status=es2,
                    cache_hit=(status2 == FETCH_STATUS_CACHE),
                    result_count=len(pois2), skip_reason="",
                    is_in_approved_plan=True,
                )
                snapshot_rows.extend(pois2)
                district_poi_counts[did] = district_poi_counts.get(did, 0) + len(pois2)
                second_page_approved_count += 1
                second_page_executed_count += 1

                if queue:
                    next_round.append(did)
            remaining_dids = next_round

        # ── Record keyword-limit excluded in request_log for manifest ──
        excluded_kw_count = plan.excluded_keyword_limit
        excluded_budget_count = plan.excluded_district_budget

        # ── Record excluded keyword-limit entries ──
        for d in district_map.values():
            did = d["district_id"]
            tier_key = did
            tier = budget_config.get("district_tiers", {}).get(tier_key, "C")
            rules = budget_config.get("tier_rules", {}).get(tier, {})
            max_kw = rules.get("max_keywords", 999)
            total_kw = len(keyword_plan)
            f1_candidates = min(total_kw, max_kw)
            excluded_from_first = total_kw - f1_candidates
            num_pages = rules.get("max_pages", 1)
            for p in range(num_pages):
                for kw, cat_id in keyword_plan[f1_candidates:]:
                    state.record_execution(
                        district_id=did,
                        district_name=d["name"],
                        category_id=cat_id,
                        keyword=kw,
                        page=p + 1,
                        execution_status=EXEC_STATUS_SKIPPED_KEYWORD_LIMIT,
                        cache_hit=False,
                        result_count=0,
                        skip_reason="超出 tier 关键词上限",
                        is_in_approved_plan=False,
                    )

        # ── Build district summaries ──
        for did, s in district_summaries.items():
            approved_slots = [r for r in state.request_log
                              if r["district_id"] == did and r.get("is_in_approved_plan", True)]
            s["planned_queries"] = len(approved_slots)
            s["api_requests_used"] = sum(1 for r in approved_slots
                                         if r["execution_status"] in (
                                             EXEC_STATUS_SUCCESS, EXEC_STATUS_EMPTY, EXEC_STATUS_FAILED_API))
            s["cache_hits"] = sum(1 for r in approved_slots if r["cache_hit"])
            s["poi_count"] = district_poi_counts.get(did, 0)

        summary_list = list(district_summaries.values())

        if not snapshot_rows:
            print("      高德 API 未返回数据，回退到 sample 数据")
            state.fallback_used = True
            snapshot_rows = build_fallback_snapshot(sample_poi_path, snapshot_date)
            for s in summary_list:
                s["fallback_used"] = "yes (no real data)"

        write_collection_summary(state, summary_path, snapshot_date, weekend_date,
                                 summary_list)
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

    snapshot_rows = deduplicate_snapshot_rows(snapshot_rows)
    snapshot_path = os.path.join(
        snapshot_dir, f"{snapshot_date.isoformat()}_poi_snapshot.csv"
    )
    write_snapshot_csv(snapshot_rows, snapshot_path)
    print(f"      快照已写入 {snapshot_path}（{len(snapshot_rows)} 条）")

    source_mode = compute_snapshot_source_mode(state)
    status = compute_snapshot_completeness(state, source_mode)
    extra_manifest = {
        "scheduler_strategy": "breadth_first",
        "adaptive_pagination": True,
        "page_size": budget_config.get("scheduler", {}).get("page_size", 20),
        "max_qps": budget_config.get("rate_limit", {}).get("max_qps", 0),
        "first_page_request_count": plan.first_page_count if use_real_api else 0,
        "second_page_potential_count": plan.second_page_candidates if use_real_api else 0,
        "second_page_candidate_count": second_page_candidate_count if use_real_api else 0,
        "second_page_approved_count": second_page_approved_count if use_real_api else 0,
        "second_page_executed_count": second_page_executed_count if use_real_api else 0,
        "quota_blocked_request_count": quota_blocked_count if use_real_api else 0,
    }
    manifest = write_manifest_json(
        state, snapshot_dir, snapshot_date, source_mode, status,
        config_fingerprint, district_config, cat_config, budget_config,
        len(snapshot_rows), keyword_plan,
        extra_manifest=extra_manifest,
    )
    print(f"      status={status}, source={source_mode}, fingerprint={config_fingerprint}")
    if status == "partial":
        print(f"      ⚠ Snapshot 采集不完整: {manifest.get('failed_request_count', 0)} 个请求失败")
    elif status == "fallback":
        print(f"      ⚠ Snapshot 使用 sample 数据，不能与真实 API Snapshot 比较")

    archive_summary_list = summary_list if use_real_api else district_summaries
    archive_summary_path = os.path.join(
        snapshot_dir, f"{snapshot_date.isoformat()}_collection_summary.csv"
    )
    write_collection_summary(state, archive_summary_path, snapshot_date, weekend_date,
                             archive_summary_list)
    print(f"      归档 summary 已写入 {archive_summary_path}")

    print("[3/6] 检测历史快照...")
    prev_path, prev_date = find_previous_snapshot(snapshot_dir, snapshot_date)
    if prev_path:
        print(f"      发现历史快照: {prev_date}")
        previous_rows = load_snapshot(prev_path)
        print(f"      历史快照共 {len(previous_rows)} 条 POI")
        previous_rows = deduplicate_snapshot_rows(previous_rows)
        has_history = True
    else:
        print("      无历史快照，当前为第一期基准快照")
        previous_rows = None
        has_history = False

    print("[4/6] 识别变化事件...")
    compare_ok = True
    compare_reason = ""
    if has_history:
        prev_manifest_path = os.path.join(
            snapshot_dir, f"{prev_date.isoformat()}_manifest.json"
        )
        prev_manifest = read_manifest(prev_manifest_path)
        compare_ok, compare_reason = compare_is_allowed(
            has_history, prev_manifest, manifest
        )
        if not compare_ok:
            print(f"      ⚠ 无法进行跨期 Compare: {compare_reason}")

    if has_history and compare_ok:
        change_events = detect_changes(
            snapshot_rows, previous_rows, snapshot_date, prev_date
        )
        print(f"      已识别 {len(change_events)} 个变化事件")
    elif has_history and not compare_ok:
        change_events = [{
            "snapshot_date": snapshot_date.isoformat(),
            "previous_snapshot_date": prev_date.isoformat(),
            "district_id": "",
            "district_name": "",
            "category_id": "",
            "event_type": "comparison_blocked",
            "poi_id": "",
            "name": "",
            "address": "",
            "signal_strength": 0,
            "why_interesting": f"跨期比较被阻止: {compare_reason}",
        }]
        print(f"      ⚠ 跨期比较被阻止: {compare_reason}")
    else:
        change_events = generate_baseline_events(snapshot_rows, snapshot_date)
        print(f"      已生成 {len(change_events)} 条第一期基准事件")
    write_change_events_csv(change_events, change_events_path)
    print(f"      已写入 {change_events_path}")

    print("[5/6] 计算街区变化评分...")
    if has_history and not compare_ok:
        change_scores = []
        print(f"      ⚠ 跳过评分计算（因 compare 被阻止）")
    else:
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

    # Map generation
    map_path = None
    if not args.no_map and snapshot_path and os.path.isfile(snapshot_path):
        try:
            map_filename = f"{weekend_date.isoformat()}_shanghai_weekend_map.html"
            map_path = os.path.join(maps_dir, map_filename)
            generate_map(
                poi_snapshot_path=snapshot_path,
                districts_path=districts_path,
                output_path=map_path,
                snapshot_date=snapshot_date.isoformat(),
                weekend_date=weekend_date.isoformat(),
                provider=args.map_provider,
                coord_mode=args.coord_mode,
            )
            print(f"      地图已生成: {map_path} (provider: {args.map_provider})")
        except Exception as e:
            print(f"      ⚠ 地图生成失败: {e}")
            map_path = None
    elif args.no_map:
        print("      地图已跳过 (--no-map)")
    else:
        print("      地图已跳过 (快照文件不存在)")

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
        map_path=map_path,
        coord_mode=args.coord_mode,
        map_provider=args.map_provider,
    )
    print(f"      报告已生成: {report_path}")

    print("\n✅ 完成！城市变化雷达已更新。")


if __name__ == "__main__":
    main()
