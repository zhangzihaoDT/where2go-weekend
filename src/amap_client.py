import csv
import hashlib
import json
import os
from datetime import date
from typing import Optional

from dotenv import load_dotenv

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


def search_poi_around(
    query: str,
    center_lng: float,
    center_lat: float,
    radius_m: int = 500,
    offset: int = 20,
) -> list[dict]:
    global _quota_warning_shown
    api_key = get_api_key()
    if not api_key:
        return []

    url = "https://restapi.amap.com/v3/place/around"
    params = {
        "key": api_key,
        "keywords": query,
        "location": f"{center_lng},{center_lat}",
        "radius": radius_m,
        "offset": offset,
        "extensions": "base",
    }
    try:
        data = _amap_get(url, params)
        if data.get("status") == "1":
            return data.get("pois", [])
        info = data.get("info", "")
        infocode = data.get("infocode", "")
        if "INVALID_USER_SIGNATURE" in info or infocode == "10007":
            print(f"      ⚠ 高德 API 签名验证失败，请在 .env 中设置 AMAP_API_SECRET")
        elif infocode == "10021" and not _quota_warning_shown:
            _quota_warning_shown = True
            print(f"      ⚠ 高德 API 日调用配额已用尽，部分查询返回空")
        return []
    except Exception:
        return []


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
               radius_m: int, page: int) -> str:
    raw = f"{source}|{dt.isoformat()}|{district_id}|{keyword}|{radius_m}|{page}"
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
               radius_m: int, page: int) -> Optional[list[dict]]:
    path = _cache_path(_cache_key(source, dt, district_id, keyword, radius_m, page))
    if not os.path.isfile(path):
        return None
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return None


def write_cache(source: str, dt: date, district_id: str, keyword: str,
                radius_m: int, page: int, data: list[dict]):
    path = _cache_path(_cache_key(source, dt, district_id, keyword, radius_m, page))
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


# ── 按预算/缓存的 POI 采集 ──────────────────────────────


FETCH_STATUS_API = "fetched_from_api"
FETCH_STATUS_CACHE = "loaded_from_cache"
FETCH_STATUS_SKIPPED = "skipped_by_budget"


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
) -> tuple[list[dict], str]:
    if not state.can_request(district_id):
        state.record_skipped(
            district_id, district_name, query, cat_id,
            "预算不足" if state.api_requests_used >= state.daily_max else "单街区上限",
        )
        return [], FETCH_STATUS_SKIPPED

    if not state.force:
        cached = read_cache(
            "amap", snapshot_date, district_id, query, radius_m, page
        )
        if cached is not None:
            state.record_cache_hit()
            return cached, FETCH_STATUS_CACHE

    pois = search_poi_around(query, center_lng, center_lat, radius_m)
    state.record_api_call(district_id)
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
                normalized)

    return normalized, FETCH_STATUS_API


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
