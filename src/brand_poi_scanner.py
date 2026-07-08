"""
Brand POI scanner for where2go-weekend.
"""

import csv
import hashlib
import json
import math
import os
import shutil
import time
from datetime import date
from typing import Optional

import yaml


PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SCAN_MODES = ("text_city_first", "text_city_only", "around_fallback", "grid_around")

# Module-level flags
_debug_api = False
_error_cache = False
_stats = {
    "api_success_count": 0,
    "api_error_count": 0,
    "qps_limited_count": 0,
    "cache_hit_count": 0,
    "cache_miss_count": 0,
}


def set_debug(val: bool = True):
    global _debug_api
    _debug_api = val


def set_error_cache(val: bool = True):
    global _error_cache
    _error_cache = val


def reset_stats():
    global _stats
    _stats = {k: 0 for k in _stats}


def get_stats() -> dict:
    return dict(_stats)


def _load_config() -> dict:
    path = os.path.join(PROJECT_ROOT, "config", "brand_poi_compare.yaml")
    with open(path, encoding="utf-8") as f:
        return yaml.safe_load(f)


# ── Cache management ──


def clear_cache():
    cache_dir = os.path.join(PROJECT_ROOT, "data", "cache", "amap_brand_poi_raw")
    if os.path.isdir(cache_dir):
        shutil.rmtree(cache_dir)
        os.makedirs(cache_dir, exist_ok=True)
        print(f"  [cache] cleared {cache_dir}")


def estimate_requests(config: dict, scan_mode: str) -> int:
    brands = config["brands"]
    total_queries = sum(len(b.get("queries", [])) for b in brands)
    max_pages = config["scan_area"]["max_pages"]
    if scan_mode in ("text_city_first", "text_city_only"):
        return total_queries * max_pages
    elif scan_mode == "around_fallback":
        points = config.get("fallback_scan_points", [])
        return total_queries * len(points) * max_pages
    else:
        bbox = config["scan_area"]["grid_bbox"]
        step_km = config["scan_area"].get("grid_step_km", 4)
        lat_step = step_km / 111.0
        lng_step = step_km / (111.0 * math.cos(math.radians((bbox["min_lat"] + bbox["max_lat"]) / 2)))
        n_lat = int((bbox["max_lat"] - bbox["min_lat"]) / lat_step) + 1
        n_lng = int((bbox["max_lng"] - bbox["min_lng"]) / lng_step) + 1
        return total_queries * n_lat * n_lng * max_pages


# ── Bbox grid ──


def generate_scan_points(config: dict) -> list[dict]:
    bbox = config["scan_area"]["grid_bbox"]
    step_km = config["scan_area"].get("grid_step_km", 4)
    radius_m = config["scan_area"].get("grid_radius_m", 3500)
    min_lng, min_lat = bbox["min_lng"], bbox["min_lat"]
    max_lng, max_lat = bbox["max_lng"], bbox["max_lat"]
    lat_step = step_km / 111.0
    lng_step = step_km / (111.0 * math.cos(math.radians((min_lat + max_lat) / 2)))
    points = []
    lat = min_lat
    while lat <= max_lat:
        lng = min_lng
        while lng <= max_lng:
            points.append({"lng": round(lng, 4), "lat": round(lat, 4), "radius_m": radius_m})
            lng += lng_step
        lat += lat_step
    return points


# ── POI classification ──


def _safe_str(val) -> str:
    if isinstance(val, list):
        return " ".join(str(v) for v in val)
    return str(val) if val is not None else ""


def classify_poi_kind(
    name: str, poi_type: str, address: str,
    source_query: str = "",
    brand_id: str = "",
) -> str:
    text = _safe_str(name) + " " + _safe_str(poi_type) + " " + _safe_str(address)
    sq = _safe_str(source_query)
    combined = text + " " + sq

    # 1. energy first
    if any(k in text for k in ("换电", "充电", "超充", "能源", "power")):
        return "energy"

    # 2. delivery_center
    if "交付" in text or "交付" in sq:
        return "delivery_center"

    # 3. service_center
    if any(k in combined for k in ("服务中心", "售后", "维修")):
        return "service_center"

    # 4. user_center
    if any(k in combined for k in ("用户中心", "授权用户中心", "问界用户中心", "AITO授权用户中心")):
        return "user_center"

    # 5. experience_store
    if any(k in combined for k in ("体验中心", "体验店", "蔚来空间", "蔚来中心", "智己汽车", "NIO House", "NIO Space")):
        return "experience_store"

    # 6. mall_store
    mall_keywords = ("商场", "广场", "mall", "Mall", "购物中心", "百联", "龙湖",
                     "万象城", "合生汇", "前滩太古里", "环球港")
    if any(k in text for k in mall_keywords):
        return "mall_store"

    if any(k in text for k in ("总部", "办公", "office")):
        return "office"
    return "other"


# ── Normalize ──


def _normalize(text: str) -> str:
    import re
    return re.sub(r"\s+", "", (text or "").strip())


def _make_dedup_key(row: dict) -> str:
    poi_id = row.get("poi_id", "")
    if poi_id:
        return f"{row['brand_id']}|{poi_id}"
    name = _normalize(row.get("name", ""))
    addr = _normalize(row.get("address", ""))
    lng = round(float(row.get("lng_gcj02", 0)), 5)
    lat = round(float(row.get("lat_gcj02", 0)), 5)
    return f"{row['brand_id']}|{name}|{addr}|{lng}|{lat}"


def normalize_amap_poi(poi: dict, brand: dict, query: str, scan_point: dict,
                       crawl_date: date) -> dict:
    loc_raw = poi.get("location", "")
    if not loc_raw:
        lng, lat = 0.0, 0.0
    else:
        loc = loc_raw.split(",")
        try:
            lng = float(loc[0]) if len(loc) > 0 else 0.0
            lat = float(loc[1]) if len(loc) > 1 else 0.0
        except (ValueError, TypeError):
            lng, lat = 0.0, 0.0
    poi_id = poi.get("id", "")
    matched = []
    poi_name = poi.get("name", "")
    poi_type_val = poi.get("type", "")
    if isinstance(poi_type_val, list):
        poi_type_val = "|".join(poi_type_val)
    for kw in brand.get("include_keywords", []):
        if kw in (poi_name + poi_type_val):
            matched.append(kw)

    # Safely stringify list fields
    def _s(v):
        if isinstance(v, list):
            return "|".join(str(x) for x in v)
        return str(v) if v is not None else ""

    return {
        "brand_id": brand["brand_id"],
        "brand_name": brand["display_name"],
        "poi_id": poi_id,
        "name": _s(poi.get("name")),
        "address": _s(poi.get("address")),
        "province": _s(poi.get("pname")),
        "city": _s(poi.get("cityname")),
        "district": _s(poi.get("adname")),
        "adcode": _s(poi.get("adcode")),
        "lng_gcj02": lng,
        "lat_gcj02": lat,
        "type": _s(poi.get("type")),
        "typecode": _s(poi.get("typecode")),
        "tel": _s(poi.get("tel")),
        "source_query": query,
        "matched_keywords": "|".join(matched),
        "poi_kind": classify_poi_kind(poi_name, poi.get("type", ""), poi.get("address", ""),
                                       source_query=query, brand_id=brand["brand_id"]),
        "raw_distance": poi.get("distance", ""),
        "scan_center_lng": scan_point["lng"],
        "scan_center_lat": scan_point["lat"],
        "scan_radius_m": scan_point["radius_m"],
        "source": "amap_place_text",
        "crawl_date": crawl_date.isoformat(),
    }


# ── API response parser ──


def parse_amap_response(
    data: dict,
    *,
    api: str,
    brand: str,
    query: str,
    page: int,
    cache_path: Optional[str] = None,
    is_cached: bool = False,
) -> list[dict]:
    status = data.get("status")
    info = data.get("info", "")
    infocode = data.get("infocode", "")
    count = data.get("count", "?")
    pois = data.get("pois")

    if is_cached:
        _stats["cache_hit_count"] += 1
    else:
        _stats["cache_miss_count"] += 1

    if status != "1":
        _stats["api_error_count"] += 1
        print(f"    [AMAP ERROR] query={query} api={api} status={status} info={info} infocode={infocode}")
        return []

    if not isinstance(pois, list):
        print(f"    [AMAP WARN] query={query} api={api} pois is not a list: {type(pois)}")
        return []

    prefix = "    [cache] " if is_cached else "    "
    print(f"{prefix}status=1 info=OK count={count} pois={len(pois)}")
    return pois


# ── API call ──


QUOTA_BACKOFF = [2, 5, 10]


def _amap_request(url: str, params: dict, config: dict) -> Optional[dict]:
    import requests
    from src.amap_client import get_api_secret, _sign_params
    secret = get_api_secret()
    if secret:
        sig = _sign_params(params, secret)
        params["sig"] = sig
    retry = config["amap"]["retry"]
    base_sleep = config["amap"]["sleep_seconds"]
    timeout = config["amap"].get("timeout_seconds", 10)
    for attempt in range(retry):
        try:
            resp = requests.get(url, params=params, timeout=timeout)
            data = resp.json()
            if data.get("infocode") == "10021":
                _stats["qps_limited_count"] += 1
                wait = QUOTA_BACKOFF[attempt] if attempt < len(QUOTA_BACKOFF) else 10
                if _debug_api:
                    print(f"    [rate-limit] attempt {attempt+1}/{retry}, waiting {wait}s...")
                if attempt < retry - 1:
                    time.sleep(wait)
                    continue
                return None
            _stats["api_success_count"] += 1
            return data
        except Exception as e:
            _stats["api_error_count"] += 1
            if _debug_api:
                print(f"    [debug] request failed attempt {attempt+1}: {e}")
            if attempt < retry - 1:
                time.sleep(base_sleep)
    return None


# ── Cache helpers ──


def _cache_path(config: dict, cache_key: str) -> str:
    cache_dir = os.path.join(PROJECT_ROOT, config["amap"]["cache_dir"])
    h = hashlib.md5(cache_key.encode("utf-8")).hexdigest()
    return os.path.join(cache_dir, f"{h}.json")


def _read_cache(cache_path: str) -> Optional[list]:
    if not os.path.isfile(cache_path):
        return None
    try:
        with open(cache_path, encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return None


def _write_cache(cache_path: str, data: list):
    if _error_cache and not data:
        return
    os.makedirs(os.path.dirname(cache_path), exist_ok=True)
    with open(cache_path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False)


# ── Smoke query ──


def smoke_query(
    config: dict, api_key: str, query: str, city: str, debug: bool = False, no_cache: bool = False,
):
    set_debug(debug)
    base_url = config["amap"]["text_api_base"]
    offset = config["scan_area"]["offset"]

    city_variants = [city, city + "市", "310000"]
    seen = set()

    for cv in city_variants:
        print(f"\n  [smoke] city={cv}")
        for page in [1, 2]:
            params = {
                "key": api_key,
                "keywords": query,
                "city": cv,
                "citylimit": "true",
                "offset": offset,
                "page": page,
                "extensions": "all",
                "output": "json",
            }
            cache_key = f"smoke|{query}|{cv}|page{page}"
            cpath = _cache_path(config, cache_key) if not no_cache else None

            if not no_cache and cpath:
                cached = _read_cache(cpath)
                if cached is not None:
                    print(f"    [cache] loaded {len(cached)} items, skipping API")
                    for item in cached:
                        pid = item.get("id", "") + item.get("name", "")
                        if pid not in seen:
                            seen.add(pid)
                            print(f"      {item.get('name','?')} | {item.get('address','')} | {item.get('location','')}")
                    continue

            result = _amap_request(base_url, params, config)
            if result is None:
                print(f"    [smoke] request failed (no response)")
                continue

            show_key = api_key[:6] if debug else None
            pois = parse_amap_response(
                result, api="text", brand="", query=query, page=page,
                cache_path=cpath, show_key_prefix=show_key,
            )
            if pois:
                for item in pois[:5]:
                    pid = item.get("id", "") + item.get("name", "")
                    if pid not in seen:
                        seen.add(pid)
                        loc = item.get("location", "")
                        print(f"      {item.get('name','?')} | {item.get('address','')} | {loc}")
            if not no_cache and cpath and result.get("status") == "1" and isinstance(result.get("pois"), list):
                _write_cache(cpath, result["pois"])

            if result.get("status") != "1":
                break

        # If this city variant returned POIs, don't try next
        if any(result.get("status") == "1" and result.get("pois") for _ in [1]):
            pass  # need a more reliable check — we break if last call had pois
        # Actually just check if we printed any POI above
        if seen:
            break


# ── Scan by text ──


def _scan_text(
    config: dict, brand: dict, query: str, crawl_date: date,
    api_key: str, seen_keys: set, all_rows: list,
    max_pages: int, source_label: str,
):
    base_url = config["amap"]["text_api_base"]
    cache_prefix = f"text|{brand['brand_id']}|{query}"
    scan_point = {"lng": 0, "lat": 0, "radius_m": 0}

    for page in range(1, max_pages + 1):
        cache_key = f"{cache_prefix}|page{page}"
        cpath = _cache_path(config, cache_key)
        cached = _read_cache(cpath) if config["amap"]["cache_enabled"] else None

        if cached is not None:
            _stats["cache_hit_count"] += 1
            print(f"    [cache] status=ok pois={len(cached)} ({brand['display_name']} / {query} / page {page})")
            for item in cached:
                row = normalize_amap_poi(item, brand, query, scan_point, crawl_date)
                dk = _make_dedup_key(row)
                if dk not in seen_keys:
                    seen_keys.add(dk)
                    all_rows.append(row)
            continue

        params = {
            "key": api_key,
            "keywords": query,
            "city": config["city"],
            "citylimit": "true",
            "offset": config["scan_area"]["offset"],
            "page": page,
            "extensions": config["amap"]["extensions"],
            "output": "json",
        }

        result = _amap_request(base_url, params, config)
        if result is None:
            print(f"    [AMAP ERROR] query={query} api=text — no response after retries")
            return

        pois = parse_amap_response(
            result, api="text", brand=brand["display_name"], query=query, page=page,
            cache_path=cpath,
        )
        if not pois:
            return

        page_items = []
        for item in pois:
            row = normalize_amap_poi(item, brand, query, scan_point, crawl_date)
            dk = _make_dedup_key(row)
            if dk not in seen_keys:
                seen_keys.add(dk)
                all_rows.append(row)
            page_items.append(item)

        if page_items and config["amap"]["cache_enabled"]:
            _write_cache(cpath, page_items)

        time.sleep(config["amap"]["sleep_seconds"])


# ── Scan by around ──


def _scan_around(
    config: dict, brand: dict, query: str, crawl_date: date,
    api_key: str, seen_keys: set, all_rows: list,
    scan_points: list[dict], max_pages: int, source_label: str,
):
    base_url = config["amap"]["around_api_base"]

    for sp in scan_points:
        sp_radius = sp.get("radius_m", 3500)
        # Ensure sp has radius_m for downstream normalize_amap_poi
        sp["radius_m"] = sp_radius
        cache_key = f"around|{brand['brand_id']}|{query}|{sp['lng']}|{sp['lat']}|{sp_radius}"
        cpath = _cache_path(config, cache_key)
        cached = _read_cache(cpath) if config["amap"]["cache_enabled"] else None

        if cached is not None:
            sp["radius_m"] = sp.get("radius_m", 3500)
            _stats["cache_hit_count"] += 1
            print(f"    [cache] status=ok pois={len(cached)} ({brand['display_name']} / {query} / {sp.get('name','?')})")
            for item in cached:
                row = normalize_amap_poi(item, brand, query, sp, crawl_date)
                dk = _make_dedup_key(row)
                if dk not in seen_keys:
                    seen_keys.add(dk)
                    all_rows.append(row)
            continue

        params = {
            "key": api_key,
            "keywords": query,
            "location": f"{sp['lng']},{sp['lat']}",
            "radius": sp_radius,
            "offset": config["scan_area"]["offset"],
            "page": 1,
            "extensions": config["amap"]["extensions"],
            "output": "json",
        }
        if config["amap"]["city_limit"]:
            params["city"] = config["city"]
            params["citylimit"] = "true"

        page_items = []
        for page in range(1, max_pages + 1):
            params["page"] = page
            result = _amap_request(base_url, params, config)
            if result is None:
                break
            show_key = api_key[:6] if _debug_api else None
            pois = parse_amap_response(
                result, api="around", brand=brand["display_name"], query=query, page=page,
                cache_path=cpath, show_key_prefix=show_key,
            )
            if not pois:
                break
            for item in pois:
                row = normalize_amap_poi(item, brand, query, sp, crawl_date)
                dk = _make_dedup_key(row)
                if dk not in seen_keys:
                    seen_keys.add(dk)
                    all_rows.append(row)
                page_items.append(item)
            time.sleep(config["amap"]["sleep_seconds"])

        if page_items and config["amap"]["cache_enabled"]:
            _write_cache(cpath, page_items)
        time.sleep(config["amap"]["sleep_seconds"])


# ── Main scan ──


def scan_brand_pois(
    config: dict,
    crawl_date: date,
    api_key: Optional[str] = None,
    scan_mode: str = "text_city_first",
) -> list[dict]:
    all_rows = []
    seen_keys = set()
    max_pages = config["scan_area"]["max_pages"]

    for brand in config["brands"]:
        brand_id = brand["brand_id"]
        print(f"\n  === {brand['display_name']} ===")

        if scan_mode in ("text_city_first", "text_city_only"):
            for query in brand.get("queries", []):
                if not api_key:
                    break
                _scan_text(config, brand, query, crawl_date, api_key,
                           seen_keys, all_rows, max_pages, "Text Search")

        brand_count = sum(1 for r in all_rows if r["brand_id"] == brand_id)
        print(f"  [品牌完成] {brand['display_name']} raw={brand_count}")

        if scan_mode == "text_city_first":
            fallback_min = config["scan_strategy"]["fallback_min_brand_poi_count"]
            fallback_enabled = config["scan_strategy"]["enable_around_fallback"]
            if fallback_enabled and brand_count < fallback_min:
                fb_points = config.get("fallback_scan_points", [])
                print(f"  [Fallback Around] {brand['display_name']} only got {brand_count}, "
                      f"fallback with {len(fb_points)} points")
                for query in brand.get("queries", []):
                    if not api_key:
                        break
                    _scan_around(config, brand, query, crawl_date, api_key,
                                 seen_keys, all_rows, fb_points, 1,
                                 "Fallback Around")

        if scan_mode == "around_fallback":
            fb_points = config.get("fallback_scan_points", [])
            for query in brand.get("queries", []):
                if not api_key:
                    break
                _scan_around(config, brand, query, crawl_date, api_key,
                             seen_keys, all_rows, fb_points, max_pages,
                             "Around")

        if scan_mode == "grid_around":
            grid_points = generate_scan_points(config)
            for query in brand.get("queries", []):
                if not api_key:
                    break
                _scan_around(config, brand, query, crawl_date, api_key,
                             seen_keys, all_rows, grid_points, max_pages,
                             "Grid Around")

    filtered = []
    for row in all_rows:
        brand_conf = None
        for b in config["brands"]:
            if b["brand_id"] == row["brand_id"]:
                brand_conf = b
                break
        if not brand_conf:
            filtered.append(row)
            continue
        row_type = row.get("type", "")
        if isinstance(row_type, list):
            row_type = "|".join(row_type)
        text = _safe_str(row["name"]) + " " + _safe_str(row_type) + " " + _safe_str(row.get("address", ""))
        excluded = False
        for ek in brand_conf.get("exclude_keywords", []):
            if ek in text:
                excluded = True
                break
        if excluded:
            continue
        if row["poi_kind"] == "energy":
            continue
        filtered.append(row)

    s = _stats
    print(f"\n  总计: raw={len(all_rows)} → 去重+过滤: {len(filtered)}")
    print(f"  API 请求成功: {s['api_success_count']}, 错误: {s['api_error_count']}, "
          f"限流: {s['qps_limited_count']}, 缓存命中: {s['cache_hit_count']}, "
          f"缓存未命中: {s['cache_miss_count']}")
    if s['qps_limited_count'] > 0:
        print(f"  ⚠  本次结果可能不完整（{s['qps_limited_count']} 次请求被限流），"
              f"建议稍后不带 --clear-cache 重新运行以补齐。")
    reset_stats()
    return filtered


# ── CSV / JSON output ──


CSV_FIELDS = [
    "brand_id", "brand_name", "poi_id", "name", "address",
    "province", "city", "district", "adcode",
    "lng_gcj02", "lat_gcj02", "type", "typecode", "tel",
    "source_query", "matched_keywords", "poi_kind",
    "raw_distance", "scan_center_lng", "scan_center_lat", "scan_radius_m",
    "source", "crawl_date",
]


def write_csv(rows: list[dict], output_path: str):
    os.makedirs(os.path.dirname(output_path), exist_ok=True)
    with open(output_path, "w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=CSV_FIELDS)
        w.writeheader()
        for r in rows:
            w.writerow({k: r.get(k, "") for k in CSV_FIELDS})


def write_json(rows: list[dict], output_path: str):
    os.makedirs(os.path.dirname(output_path), exist_ok=True)
    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(rows, f, ensure_ascii=False, indent=2)
