import csv
import hashlib
import json
import os
from datetime import date
from typing import Optional

from dotenv import load_dotenv
from src.collection_scheduler import QPSTimer

load_dotenv()

CACHE_DIR = None

# ── API Key ──────────────────────────────────────────────


def get_api_key() -> Optional[str]:
    key = os.environ.get("AMAP_API_KEY")
    if key:
        return key.strip()
    return None


def get_api_secret() -> Optional[str]:
    secret = os.environ.get("AMAP_API_SECRET")
    if secret:
        return secret.strip()
    return None


def has_api_key() -> bool:
    return bool(get_api_key())


# ── 高德 HTTP ──────────────────────────────────────────


def _sign_params(params: dict, secret: str) -> str:
    sorted_keys = sorted(params.keys())
    raw = "&".join(f"{k}={params[k]}" for k in sorted_keys)
    raw += secret
    return hashlib.md5(raw.encode("utf-8")).hexdigest()


def _amap_get(url: str, params: dict) -> dict:
    import requests
    secret = get_api_secret()
    if secret:
        params["sig"] = _sign_params(params, secret)
    resp = requests.get(url, params=params, timeout=10)
    resp.raise_for_status()
    return resp.json()


_quota_warning_shown = False

# ── Error code classification ──
INFCODE_HARD_STOP = {"10003", "10044", "40000", "40002"}
INFCODE_RETRYABLE = {"10004", "10015", "10016", "10019", "10020", "10021"}
INFCODE_NO_RETRY = {"10001", "10002", "10005", "10007", "10009", "10012", "10041",
                    "20000", "20001", "20002"}


def classify_amap_error(info: str, infocode: str) -> tuple[str, str]:
    if infocode in INFCODE_HARD_STOP:
        return "hard_stop", infocode
    if infocode in INFCODE_RETRYABLE:
        return "retryable", infocode
    if "INVALID_USER_SIGNATURE" in info and not infocode:
        infocode = "10007"
    if infocode in INFCODE_NO_RETRY:
        return "no_retry", infocode
    if info:
        return "unknown", infocode
    return "network_error", ""


def search_poi_around(
    query: str,
    center_lng: float,
    center_lat: float,
    radius_m: int = 500,
    offset: int = 20,
    page: int = 1,
) -> tuple[list[dict], str, str]:
    global _quota_warning_shown
    api_key = get_api_key()
    if not api_key:
        return [], "no_api_key", ""

    url = "https://restapi.amap.com/v3/place/around"
    params = {
        "key": api_key,
        "keywords": query,
        "location": f"{center_lng},{center_lat}",
        "radius": radius_m,
        "offset": offset,
        "page": page,
        "extensions": "base",
    }
    try:
        data = _amap_get(url, params)
        if data.get("status") == "1":
            count = data.get("count", "")
            return data.get("pois", []), "", ""
        info = data.get("info", "")
        infocode = str(data.get("infocode", ""))
        if "INVALID_USER_SIGNATURE" in info and not infocode:
            infocode = "10007"
        if infocode == "10021" and not _quota_warning_shown:
            _quota_warning_shown = True
            print(f"      ⚠ 高德返回 infocode=10021 (日调用量超限)")
        return [], infocode, info
    except Exception as e:
        return [], "network_error", str(e)


# ── POI 工具 ─────────────────────────────────────────────


def _make_poi_id(name: str, address: str, district_id: str) -> str:
    raw = f"{name}|{address}|{district_id}"
    return hashlib.md5(raw.encode("utf-8")).hexdigest()[:12]


def normalize_amap_poi(
    poi: dict,
    district_id: str,
    district_name: str,
    category_id: str,
    keyword: str,
    snapshot_date: date,
) -> dict:
    loc = poi.get("location", "0,0")
    parts = loc.split(",")
    lng = float(parts[0]) if len(parts) > 0 else 0.0
    lat = float(parts[1]) if len(parts) > 1 else 0.0

    poi_id = poi.get("id", "")
    if not poi_id:
        poi_id = _make_poi_id(
            poi.get("name", ""), poi.get("address", ""), district_id
        )

    return {
        "snapshot_date": snapshot_date.isoformat(),
        "source": "amap",
        "district_id": district_id,
        "district_name": district_name,
        "category_id": category_id,
        "keyword": keyword,
        "poi_id": poi_id,
        "name": poi.get("name", ""),
        "address": poi.get("address", ""),
        "lng": lng,
        "lat": lat,
        "poi_type": poi.get("type", ""),
        "raw_type": poi.get("typecode", ""),
        "business_area": poi.get("business_area", ""),
        "confidence": 0.8,
    }


# ── 缓存（使用 snapshot_date） ───────────────────────────


def _set_cache_dir(cache_dir: str):
    global CACHE_DIR
    CACHE_DIR = cache_dir


def _cache_key(source: str, dt: date, district_id: str, keyword: str,
               radius_m: int, page: int, center_lng: float = 0.0,
               center_lat: float = 0.0, page_size: int = 20) -> str:
    raw = (f"ep=v3|mode=around|{source}|{dt.isoformat()}|{district_id}|"
           f"{keyword}|{radius_m}|{page}|lng={center_lng}|lat={center_lat}|ps={page_size}")
    return hashlib.md5(raw.encode("utf-8")).hexdigest()


def _cache_path(cache_key: str) -> str:
    global CACHE_DIR
    if CACHE_DIR is None:
        CACHE_DIR = os.path.join(
            os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
            "data", "cache",
        )
    return os.path.join(CACHE_DIR, f"{cache_key}.json")


def read_cache(source: str, dt: date, district_id: str, keyword: str,
               radius_m: int, page: int, center_lng: float = 0.0,
               center_lat: float = 0.0, page_size: int = 20) -> Optional[list[dict]]:
    path = _cache_path(_cache_key(source, dt, district_id, keyword, radius_m, page,
                                  center_lng, center_lat, page_size))
    if not os.path.isfile(path):
        return None
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return None


def write_cache(source: str, dt: date, district_id: str, keyword: str,
                radius_m: int, page: int, data: list[dict],
                center_lng: float = 0.0, center_lat: float = 0.0,
                page_size: int = 20):
    path = _cache_path(_cache_key(source, dt, district_id, keyword, radius_m, page,
                                  center_lng, center_lat, page_size))
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


# ── 预算与采集状态 ──────────────────────────────────────


class CollectionState:
    def __init__(self, daily_max: int = 30, per_district_max: int = 10,
                 force: bool = False, api_key_present: bool = True):
        self.daily_max = daily_max
        self.per_district_max = per_district_max
        self.force = force
        self.api_key_present = api_key_present

        self.api_requests_used = 0
        self.cache_hits = 0
        self.skipped_queries = 0
        self.fallback_used = False
        self.poi_count = 0

        self.skipped_tasks: list[dict] = []
        self.district_usage: dict[str, int] = {}
        self.request_log: list[dict] = []
        self.circuit_breaker_triggered = False
        self.circuit_breaker_infocode = ""
        self.qps_timer: QPSTimer | None = None

    def can_request(self, district_id: str) -> bool:
        if not self.api_key_present:
            return False
        if self.api_requests_used >= self.daily_max:
            return False
        du = self.district_usage.get(district_id, 0)
        if du >= self.per_district_max:
            return False
        return True

    def record_api_call(self, district_id: str):
        self.api_requests_used += 1
        self.district_usage[district_id] = self.district_usage.get(district_id, 0) + 1

    def record_cache_hit(self):
        self.cache_hits += 1

    def record_skipped(self, district_id: str, district_name: str,
                       keyword: str, cat_id: str, reason: str):
        self.skipped_queries += 1
        self.skipped_tasks.append({
            "district_id": district_id,
            "district_name": district_name,
            "keyword": keyword,
            "category_id": cat_id,
            "reason": reason,
        })

    def record_pois(self, count: int):
        self.poi_count += count

    def planned_queries(self, district_count: int, keywords_per_district: int) -> int:
        return district_count * keywords_per_district

    def record_execution(self, *, district_id: str, district_name: str,
                         category_id: str, keyword: str, page: int,
                         execution_status: str, cache_hit: bool = False,
                         result_count: int = 0, skip_reason: str = "",
                         is_in_approved_plan: bool = True):
        self.request_log.append({
            "district_id": district_id,
            "district_name": district_name,
            "category_id": category_id,
            "keyword": keyword,
            "page": page,
            "execution_status": execution_status,
            "cache_hit": cache_hit,
            "result_count": result_count,
            "skip_reason": skip_reason,
            "is_in_approved_plan": is_in_approved_plan,
        })


# ── 按预算/缓存的 POI 采集 ──────────────────────────────


FETCH_STATUS_API = "fetched_from_api"
FETCH_STATUS_CACHE = "loaded_from_cache"
FETCH_STATUS_SKIPPED = "skipped_by_budget"
FETCH_STATUS_API_FAILED = "api_failed"

EXEC_STATUS_SUCCESS = "success"
EXEC_STATUS_EMPTY = "empty"
EXEC_STATUS_CACHE_HIT = "cache_hit"
EXEC_STATUS_SKIPPED_BUDGET = "skipped_budget"
EXEC_STATUS_SKIPPED_KEYWORD_LIMIT = "skipped_keyword_limit"
EXEC_STATUS_FAILED_API = "failed_api"
EXEC_STATUS_FAILED_NETWORK = "failed_network"
EXEC_STATUS_FALLBACK_SAMPLE = "fallback_sample"


def _compute_retry_delay(attempt: int, initial_backoff: float = 1.0,
                         max_backoff: float = 4.0, jitter: bool = True) -> float:
    import random
    delay = min(initial_backoff * (2 ** (attempt - 1)), max_backoff)
    if jitter:
        delay *= 0.5 + random.random() * 0.5
    return delay


def fetch_poi_around_budgeted(
    query: str,
    center_lng: float,
    center_lat: float,
    district_id: str,
    district_name: str,
    cat_id: str,
    snapshot_date: date,
    radius_m: int,
    page: int,
    state: CollectionState,
    retry_config: dict | None = None,
) -> tuple[list[dict], str]:
    if getattr(state, "circuit_breaker_triggered", False):
        return [], FETCH_STATUS_SKIPPED

    if not state.can_request(district_id):
        state.record_skipped(
            district_id, district_name, query, cat_id,
            "预算不足" if state.api_requests_used >= state.daily_max else "单街区上限",
        )
        return [], FETCH_STATUS_SKIPPED

    if not state.force:
        cached = read_cache(
            "amap", snapshot_date, district_id, query, radius_m, page,
            center_lng=center_lng, center_lat=center_lat, page_size=20,
        )
        if cached is not None:
            state.record_cache_hit()
            return cached, FETCH_STATUS_CACHE

    if state.qps_timer is not None:
        state.qps_timer.wait_if_needed()

    max_retries = (retry_config or {}).get("max_retries", 1)
    initial_backoff = (retry_config or {}).get("initial_backoff_seconds", 1.0)
    max_backoff = (retry_config or {}).get("max_backoff_seconds", 4.0)
    jitter = (retry_config or {}).get("jitter", True)

    last_infocode = ""
    last_info = ""
    attempt = 0

    while attempt <= max_retries:
        if attempt > 0:
            delay = _compute_retry_delay(attempt, initial_backoff, max_backoff, jitter)
            import time
            time.sleep(delay)

        pois, infocode, info = search_poi_around(
            query, center_lng, center_lat, radius_m, page=page,
        )
        state.record_api_call(district_id)
        last_infocode = infocode
        last_info = info

        if not infocode:
            state.record_pois(len(pois))
            normalized = []
            seen = set()
            for poi in pois:
                key = (poi.get("id", ""), poi.get("name", ""), poi.get("address", ""))
                if key in seen:
                    continue
                seen.add(key)
                normalized.append(
                    normalize_amap_poi(poi, district_id, district_name, cat_id,
                                       query, snapshot_date)
                )
            write_cache("amap", snapshot_date, district_id, query, radius_m, page,
                        normalized, center_lng=center_lng, center_lat=center_lat, page_size=20)
            return normalized, FETCH_STATUS_API

        err_category, _ = classify_amap_error(last_info, last_infocode)
        if err_category == "hard_stop":
            state.circuit_breaker_triggered = True
            state.circuit_breaker_infocode = last_infocode
            state.record_pois(0)
            return [], FETCH_STATUS_API_FAILED

        if err_category == "no_retry":
            state.record_pois(0)
            return [], FETCH_STATUS_API_FAILED

        if err_category == "retryable" and attempt >= max_retries:
            state.record_pois(0)
            return [], FETCH_STATUS_API_FAILED

        attempt += 1

    state.record_pois(0)
    return [], FETCH_STATUS_API_FAILED


SNAPSHOT_FIELDS = [
    "snapshot_date", "source", "district_id", "district_name",
    "category_id", "keyword", "poi_id", "name", "address",
    "lng", "lat", "poi_type", "raw_type", "business_area", "confidence",
]


def write_snapshot_csv(rows: list[dict], output_path: str):
    os.makedirs(os.path.dirname(output_path), exist_ok=True)
    with open(output_path, "w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=SNAPSHOT_FIELDS)
        writer.writeheader()
        writer.writerows(rows)


# ── Fallback ─────────────────────────────────────────────


def build_fallback_snapshot(
    sample_path: str,
    snapshot_date: date,
) -> list[dict]:
    rows = []
    with open(sample_path, encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for row in reader:
            poi_id = row.get("poi_id", "")
            if not poi_id:
                poi_id = _make_poi_id(
                    row.get("name", ""), row.get("address", ""),
                    row.get("district_id", "")
                )
            rows.append({
                "snapshot_date": snapshot_date.isoformat(),
                "source": "sample",
                "district_id": row.get("district_id", ""),
                "district_name": row.get("district_name", ""),
                "category_id": row.get("category_id", ""),
                "keyword": row.get("raw_keyword", ""),
                "poi_id": poi_id,
                "name": row.get("name", ""),
                "address": row.get("address", ""),
                "lng": float(row.get("lng", 0)) if row.get("lng") else 0.0,
                "lat": float(row.get("lat", 0)) if row.get("lat") else 0.0,
                "poi_type": "",
                "raw_type": "",
                "business_area": "",
                "confidence": 0.5,
            })
    return rows


# ── 采集摘要 ─────────────────────────────────────────────


COLLECTION_SUMMARY_FIELDS = [
    "run_date", "snapshot_date", "weekend_date",
    "district_id", "district_name",
    "planned_queries", "api_requests_used", "cache_hits",
    "skipped_queries", "fallback_used", "poi_count", "notes",
]


def compute_config_fingerprint(district_config: dict, cat_config: dict,
                               budget_config: dict) -> str:
    import yaml
    max_run = budget_config.get("max_requests_per_run")
    if max_run is None:
        max_run = budget_config.get("daily_max_requests", 30)
    sch = budget_config.get("scheduler", {})
    fingerprint_data = {
        "districts": [
            {
                "id": d["district_id"],
                "lng": d.get("center_lng"),
                "lat": d.get("center_lat"),
                "r": d.get("radius_m"),
            }
            for d in district_config["districts"]
        ],
        "categories": [
            {
                "id": c["category_id"],
                "query_keywords": c.get("query_keywords", []),
            }
            for c in cat_config["categories"]
        ],
        "budget": {
            "daily_max": budget_config.get("daily_max_requests"),
            "per_district_max": budget_config.get("per_district_max_requests"),
            "district_tiers": budget_config.get("district_tiers", {}),
            "tier_rules": budget_config.get("tier_rules", {}),
        },
        "scheduler": {
            "strategy": sch.get("strategy", "breadth_first"),
            "adaptive_pagination": sch.get("adaptive_pagination", True),
            "page_size": sch.get("page_size", 20),
        },
        "query_mode": "around_search",
        "offset": 20,
        "max_requests_per_run": max_run,
    }
    serialized = yaml.dump(fingerprint_data, sort_keys=True)
    return hashlib.md5(serialized.encode("utf-8")).hexdigest()[:16]


def write_manifest_json(state: CollectionState, snapshot_dir: str,
                        snapshot_date: date, source_mode: str,
                        status: str, config_fingerprint: str,
                        district_config: dict, cat_config: dict,
                        budget_config: dict, deduped_count: int,
                        keyword_plan: list,
                        extra_manifest: dict | None = None):
    import json
    total_candidates = len(state.request_log)
    approved = [r for r in state.request_log if r.get("is_in_approved_plan", True)]
    excluded = [r for r in state.request_log if not r.get("is_in_approved_plan", True)]
    approved_count = len(approved)
    excluded_count = len(excluded)
    executed = sum(1 for r in approved if r["execution_status"]
                   not in ("skipped_budget", "skipped_keyword_limit"))
    succeeded = sum(1 for r in approved if r["execution_status"]
                    in ("success", "empty", "cache_hit"))
    empties = sum(1 for r in approved if r["execution_status"] == "empty")
    failed = sum(1 for r in approved if r["execution_status"]
                 in ("failed_api", "failed_network"))
    cache_hits = sum(1 for r in approved if r["cache_hit"])

    excluded_by_reason = {
        "keyword_limit": sum(1 for r in excluded if r["execution_status"]
                             == "skipped_keyword_limit"),
        "district_budget": sum(1 for r in excluded if r["execution_status"]
                                == "skipped_budget"),
        "daily_budget": 0,
    }

    by_district = {}
    for r in state.request_log:
        if not r.get("is_in_approved_plan", True):
            continue
        did = r["district_id"]
        if did not in by_district:
            by_district[did] = {"approved": 0, "success": 0, "empty": 0,
                                "failed": 0, "poi_count": 0}
        by_district[did]["approved"] += 1
        if r["execution_status"] in ("success", "empty", "cache_hit"):
            by_district[did]["success"] += 1
        if r["execution_status"] == "empty":
            by_district[did]["empty"] += 1
        if r["execution_status"] in ("failed_api", "failed_network"):
            by_district[did]["failed"] += 1
        by_district[did]["poi_count"] += r["result_count"]

    by_keyword = {}
    for r in state.request_log:
        if not r.get("is_in_approved_plan", True):
            continue
        kw = r["keyword"]
        if kw not in by_keyword:
            by_keyword[kw] = {"approved": 0, "success": 0, "empty": 0,
                              "failed": 0, "poi_count": 0}
        by_keyword[kw]["approved"] += 1
        if r["execution_status"] in ("success", "empty", "cache_hit"):
            by_keyword[kw]["success"] += 1
        if r["execution_status"] == "empty":
            by_keyword[kw]["empty"] += 1
        if r["execution_status"] in ("failed_api", "failed_network"):
            by_keyword[kw]["failed"] += 1
        by_keyword[kw]["poi_count"] += r["result_count"]

    manifest = {
        "schema_version": 1,
        "snapshot_date": snapshot_date.isoformat(),
        "created_at": date.today().isoformat(),
        "source_mode": source_mode,
        "status": status,
        "config_fingerprint": config_fingerprint,
        "districts": [d["district_id"] for d in district_config["districts"]],
        "categories": [c["category_id"] for c in cat_config["categories"]],
        "keyword_plan": keyword_plan,
        "query_budget": {
            "daily_max_requests": budget_config.get("daily_max_requests"),
            "per_district_max_requests": budget_config.get("per_district_max_requests"),
            "district_tiers": budget_config.get("district_tiers", {}),
            "tier_rules": budget_config.get("tier_rules", {}),
        },
        "candidate_request_count": total_candidates,
        "excluded_request_count": excluded_count,
        "approved_request_count": approved_count,
        "excluded_by_reason": excluded_by_reason,
        "executed_request_count": executed,
        "successful_request_count": succeeded,
        "empty_request_count": empties,
        "failed_request_count": failed,
        "cache_hit_count": cache_hits,
        "raw_poi_count": state.poi_count,
        "deduped_poi_count": deduped_count,
        "coverage_by_district": by_district,
        "coverage_by_keyword": by_keyword,
        "circuit_breaker_triggered": state.circuit_breaker_triggered,
        "circuit_breaker_infocode": state.circuit_breaker_infocode,
    }

    if extra_manifest:
        manifest.update(extra_manifest)

    path = os.path.join(
        snapshot_dir, f"{snapshot_date.isoformat()}_manifest.json"
    )
    with open(path, "w", encoding="utf-8") as f:
        json.dump(manifest, f, ensure_ascii=False, indent=2)
    return manifest


def compute_snapshot_source_mode(state: CollectionState) -> str:
    if not state.request_log:
        return "sample" if state.fallback_used else "unknown"
    has_api = any(
        r["execution_status"] in ("success", "empty", "cache_hit",
                                  "failed_api", "failed_network")
        for r in state.request_log
    )
    has_sample = state.fallback_used
    if has_api and has_sample:
        return "mixed"
    if has_api:
        return "amap"
    return "sample"


def compute_snapshot_completeness(state: CollectionState,
                                  source_mode: str) -> str:
    if source_mode == "sample":
        return "fallback"
    approved = [r for r in state.request_log if r.get("is_in_approved_plan", True)]
    if not approved:
        return "failed"
    has_failure = any(
        r["execution_status"] in ("failed_api", "failed_network")
        for r in approved
    )
    all_accounted = all(
        r["execution_status"] in ("success", "empty", "cache_hit")
        for r in approved
    )
    if all_accounted:
        return "complete"
    if has_failure:
        return "partial"
    return "partial"


def read_manifest(path: str) -> dict | None:
    import json
    if not os.path.isfile(path):
        return None
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return None


def compare_is_allowed(previous_snapshot_exists: bool,
                       prev_manifest: dict | None,
                       curr_manifest: dict | None) -> tuple[bool, str]:
    if not previous_snapshot_exists:
        return True, "no_previous_snapshot"
    if prev_manifest is None:
        return False, "previous_snapshot_has_no_manifest"
    if curr_manifest is None:
        return False, "current_snapshot_has_no_manifest"
    if prev_manifest.get("config_fingerprint") != curr_manifest.get("config_fingerprint"):
        return False, "config_fingerprint_mismatch"
    prev_source = prev_manifest.get("source_mode", "")
    curr_source = curr_manifest.get("source_mode", "")
    if prev_source == "sample" and curr_source == "amap":
        return False, "previous_is_sample_current_is_amap"
    if prev_source == "amap" and curr_source == "sample":
        return False, "previous_is_amap_current_is_sample"
    if prev_source == "mixed" or curr_source == "mixed":
        return False, "mixed_source_not_allowed_for_compare"
    if prev_manifest.get("status") not in ("complete",):
        return False, f"previous_snapshot_status_{prev_manifest.get('status')}"
    if curr_manifest.get("status") not in ("complete",):
        return False, f"current_snapshot_status_{curr_manifest.get('status')}"
    return True, "ok"


def write_skipped_csv(tasks: list[dict], output_path: str):
    if not tasks:
        return
    os.makedirs(os.path.dirname(output_path), exist_ok=True)
    fields = ["district_id", "district_name", "keyword", "category_id", "reason"]
    with open(output_path, "w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fields)
        writer.writeheader()
        writer.writerows(tasks)


def write_collection_summary(
    state: CollectionState,
    output_path: str,
    snapshot_date: date,
    weekend_date: date,
    district_summaries: list[dict],
):
    run_date = date.today()
    os.makedirs(os.path.dirname(output_path), exist_ok=True)
    for s in district_summaries:
        s["run_date"] = run_date.isoformat()
        s["snapshot_date"] = snapshot_date.isoformat()
        s["weekend_date"] = weekend_date.isoformat()
    with open(output_path, "w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=COLLECTION_SUMMARY_FIELDS)
        writer.writeheader()
        writer.writerows(district_summaries)

    total_rows = {
        "run_date": run_date.isoformat(),
        "snapshot_date": snapshot_date.isoformat(),
        "weekend_date": weekend_date.isoformat(),
        "district_id": "__total__",
        "district_name": "合计",
        "planned_queries": sum(r["planned_queries"] for r in district_summaries),
        "api_requests_used": state.api_requests_used,
        "cache_hits": state.cache_hits,
        "skipped_queries": state.skipped_queries,
        "fallback_used": "yes" if state.fallback_used else "no",
        "poi_count": state.poi_count,
        "notes": "",
    }
    with open(output_path, "a", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=COLLECTION_SUMMARY_FIELDS)
        writer.writerow(total_rows)
