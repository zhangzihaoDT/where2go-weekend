"""
Scan Huaihai Road area via AMap around-search for sport brand stores,
plot results on an AMap JS API map with brand logo markers.

Usage:
  python3 src/manual_map.py
  python3 src/manual_map.py --out path.html
"""

import argparse
import hashlib
import json
import math
import os
import re
import sys
import time
from pathlib import Path

import requests
from dotenv import load_dotenv

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
DEFAULT_OUT = PROJECT_ROOT / "reports" / "maps" / "huaihai_brands_map.html"
SVG_DIR = PROJECT_ROOT / "assets" / "brand_logo"
SNAPSHOT_DIR = PROJECT_ROOT / "data" / "brand_stores" / "snapshots"

sys.path.insert(0, str(PROJECT_ROOT))

load_dotenv()
AMAP_API_KEY = (os.environ.get("AMAP_API_KEY") or "").strip()
AMAP_API_SECRET = (os.environ.get("AMAP_API_SECRET") or "").strip()
AMAP_JS_KEY = (os.environ.get("AMAP_JS_API_KEY") or "").strip()
AMAP_SEC_CODE = (os.environ.get("AMAP_SECURITY_JS_CODE") or "").strip()


def read_brand_logo_svg(brand_id: str) -> str:
    path = SVG_DIR / f"{brand_id}.svg"
    if path.exists():
        return path.read_text(encoding="utf-8")
    return ""


BRANDS = [
    {"id": "nike",        "name": "Nike",        "keywords": ["耐克", "Nike"],         "color": "#DD1E2C",   "logo_svg": read_brand_logo_svg("nike")},
    {"id": "adidas",      "name": "Adidas",      "keywords": ["阿迪达斯", "adidas"],     "color": "#0077C8",   "logo_svg": read_brand_logo_svg("adidas")},
    {"id": "puma",        "name": "Puma",        "keywords": ["彪马", "Puma"],          "color": "#000000",   "logo_svg": read_brand_logo_svg("puma")},
    {"id": "newbalance",  "name": "New Balance", "keywords": ["新百伦", "New Balance"], "color": "#CF5A32",   "logo_svg": read_brand_logo_svg("newbalance")},
    {"id": "underarmour", "name": "Under Armour","keywords": ["安德玛", "Under Armour"],"color": "#D6A13A",   "logo_svg": read_brand_logo_svg("underarmour")},
    {"id": "fila",        "name": "FILA",        "keywords": ["斐乐", "FILA"],          "color": "#E73C3C",   "logo_svg": read_brand_logo_svg("fila")},
    {"id": "lining",      "name": "李宁",        "keywords": ["李宁", "Li-Ning"],       "color": "#C8102E",   "logo_svg": read_brand_logo_svg("lining")},
    {"id": "anta",        "name": "安踏",        "keywords": ["安踏", "ANTA"],          "color": "#C41E3A",   "logo_svg": read_brand_logo_svg("anta")},
]


def _sign_params(params: dict, secret: str) -> str:
    sorted_keys = sorted(params.keys())
    raw = "&".join(f"{k}={params[k]}" for k in sorted_keys)
    raw += secret
    return hashlib.md5(raw.encode("utf-8")).hexdigest()


def amap_text_search(keyword: str, city: str = "上海", offset: int = 5) -> list[dict]:
    url = "https://restapi.amap.com/v3/place/text"
    params = {"key": AMAP_API_KEY, "keywords": keyword, "city": city, "offset": offset, "extensions": "base"}
    if AMAP_API_SECRET:
        params["sig"] = _sign_params(params, AMAP_API_SECRET)
    data = requests.get(url, params=params, timeout=10).json()
    if data.get("status") == "1":
        return data.get("pois", [])
    return []


def amap_around_search(keyword: str, location: str, radius: int = 500, offset: int = 20) -> list[dict]:
    url = "https://restapi.amap.com/v3/place/around"
    params = {
        "key": AMAP_API_KEY, "keywords": keyword, "location": location,
        "radius": radius, "offset": offset, "extensions": "base",
    }
    if AMAP_API_SECRET:
        params["sig"] = _sign_params(params, AMAP_API_SECRET)
    data = requests.get(url, params=params, timeout=10).json()
    if data.get("status") == "1":
        return data.get("pois", [])
    return []


def find_station_coords(station_name: str) -> tuple[float, float] | None:
    pois = amap_text_search(station_name)
    if pois:
        loc = pois[0].get("location", "")
        parts = loc.split(",")
        if len(parts) == 2:
            return float(parts[0]), float(parts[1])
    return None


def scan_brands_around_multi(centers: list[tuple[str, float, float]], radius: int = 500) -> list[dict]:
    global_seen = set()
    results = []

    for brand in BRANDS:
        brand_seen = set()
        for kw in brand["keywords"]:
            for _station_name, lng, lat in centers:
                location = f"{lng},{lat}"
                pois = amap_around_search(kw, location, radius)
                for p in pois:
                    poi_id = p.get("id", "")
                    poi_name = p.get("name", "")
                    loc = p.get("location", "").split(",")
                    if len(loc) != 2:
                        continue
                    try:
                        plng, plat = float(loc[0]), float(loc[1])
                    except ValueError:
                        continue

                    dedup_key = poi_id or f"{plng:.5f}_{plat:.5f}"
                    if dedup_key in brand_seen or dedup_key in global_seen:
                        continue
                    brand_seen.add(dedup_key)
                    global_seen.add(dedup_key)

                    dist_float = 0.0
                    raw_dist = p.get("distance", "0")
                    try:
                        dist_float = float(raw_dist)
                    except ValueError:
                        pass

                    results.append({
                        "name": poi_name,
                        "address": p.get("address", ""),
                        "lon": plng,
                    "lat": plat,
                    "brand_id": brand["id"],
                    "brand_name": brand["name"],
                    "color": brand["color"],
                    "logo_svg": brand["logo_svg"],
                    "distance_m": int(dist_float),
                    "tel": p.get("tel", "") if isinstance(p.get("tel"), str) else "",
                })
            time.sleep(0.3)
    return results


def generate_html(markers: list[dict], centers: list[tuple[str, float, float]], radius: int = 200) -> str:
    markers_json = json.dumps(markers, ensure_ascii=True)
    brand_colors = {b["id"]: b["color"] for b in BRANDS}
    brand_colors_json = json.dumps(brand_colors, ensure_ascii=True)

    sec_config = (
        f'<script>window._AMapSecurityConfig = {{securityJsCode: "{AMAP_SEC_CODE}"}};</script>'
        if AMAP_SEC_CODE else ""
    )
    src_url = (
        f"https://webapi.amap.com/maps?v=2.0&key={AMAP_JS_KEY}"
        if AMAP_JS_KEY else "https://webapi.amap.com/maps?v=2.0&key=NO_KEY"
    )

    active_ids = {m["brand_id"] for m in markers}
    center_lon = sum(c[1] for c in centers) / len(centers)
    center_lat = sum(c[2] for c in centers) / len(centers)

    return f"""<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>淮海中路运动品牌门店</title>
<style>
  body {{ margin:0; padding:0; font-family:-apple-system,'Helvetica Neue','PingFang SC',sans-serif; }}
  #map {{ width:100%; height:80vh; }}
  .panel {{
    max-width:100%; margin:8px 16px; display:flex; flex-wrap:wrap; gap:12px;
  }}
  .legend {{
    background:#fff; padding:10px 14px; border-radius:8px;
    box-shadow:0 2px 8px rgba(0,0,0,0.12); font-size:13px; line-height:1.8;
    flex:1; min-width:160px;
  }}
  .legend h4 {{ margin:0 0 4px 0; font-size:13px; color:#1F2D3D; }}
  .legend i {{ display:inline-block; width:10px;height:10px;border-radius:50%;margin-right:6px;vertical-align:middle; }}
  .store-list {{
    background:#fff; padding:10px 14px; border-radius:8px;
    box-shadow:0 2px 8px rgba(0,0,0,0.12); font-size:13px; line-height:1.7;
    flex:2; min-width:260px; max-height:200px; overflow-y:auto;
  }}
  .store-list h4 {{ margin:0 0 4px 0; font-size:13px; color:#1F2D3D; }}
  .store-item {{ display:flex; align-items:center; gap:6px; padding:2px 0; }}
  .store-dot {{ width:8px;height:8px;border-radius:50%;flex-shrink:0; }}
  .logo-marker {{
    width:32px; height:32px; border-radius:50%; overflow:hidden;
    border:2px solid #fff; box-shadow:0 2px 6px rgba(0,0,0,0.25);
    background:#fff; display:flex; align-items:center; justify-content:center;
    cursor:pointer; transition:transform 0.15s;
  }}
  .logo-marker:hover {{ transform:scale(1.15); }}
  .logo-marker svg {{ width:22px; height:22px; display:block; }}
</style>
</head>
<body>
<div id="map"></div>
<div class="panel">
  <div class="legend">
    <h4>品牌</h4>
    {"".join(f'    <div><i style="background:{b["color"]}"></i>{b["name"]}</div>' for b in BRANDS if b["id"] in active_ids)}
    <div style="margin-top:6px;font-size:11px;color:#999;">
      扫描中心：{" / ".join(n for n, _, _ in centers)}<br>
      半径：{radius}m
    </div>
  </div>
  <div class="store-list">
    <h4>门店列表</h4>
    {"".join(
        f'    <div class="store-item">'
        f'<span class="store-dot" style="background:{m["color"]}"></span>'
        f'<b>{m["brand_name"]}</b> — {m["name"]}'
        f'<span style="color:#999;font-size:11px;margin-left:auto;">{m["distance_m"]}m</span>'
        f'</div>'
        for m in sorted(markers, key=lambda x: (x["brand_id"], x["distance_m"]))
    )}
  </div>
</div>

{sec_config}
<script src="{src_url}"></script>
<script>
var map = new AMap.Map('map', {{
  center: [{center_lon}, {center_lat}],
  zoom: 16,
  mapStyle: 'amap://styles/grey',
  features: ['bg', 'road'],
  viewMode: '2D',
  pitch: 0,
  rotation: 0,
  rotateEnable: false,
  pitchEnable: false,
  doubleClickZoom: false,
}});

/* radius circles + station markers */
var centerData = {json.dumps([{"name": c[0], "lng": c[1], "lat": c[2]} for c in centers], ensure_ascii=True)};
centerData.forEach(function(c) {{
  var circle = new AMap.Circle({{
    center: new AMap.LngLat(c.lng, c.lat),
    radius: {radius},
    strokeColor: '#174A7C', strokeWeight: 3,
    strokeOpacity: 1, strokeStyle: 'dashed', strokeDasharray: [8, 8],
    fillColor: '#DDEFF8', fillOpacity: 0.3,
    zIndex: 10,
  }});
  map.add(circle);
  new AMap.Marker({{
    map: map,
    position: [c.lng, c.lat],
    content: '<div style="background:#174A7C;color:#fff;padding:3px 10px;border-radius:999px;font-size:12px;white-space:nowrap;box-shadow:0 2px 6px rgba(0,0,0,0.2);">🚇 ' + c.name + '</div>',
    anchor: 'bottom-center',
    zIndex: 50,
  }});
}});

/* brand color map */
var brandColors = {brand_colors_json};

/* markers */
var markers = {markers_json};
var infoWin = new AMap.InfoWindow({{offset: new AMap.Pixel(0, -36)}});

markers.forEach(function(m) {{
  var wrap = document.createElement('div');
  wrap.className = 'logo-marker';
  wrap.style.background = brandColors[m.brand_id] || '#6B7280';
  wrap.innerHTML = m.logo_svg;

  var marker = new AMap.Marker({{
    map: map,
    position: [m.lon, m.lat],
    content: wrap,
    anchor: 'center',
    zIndex: 30,
    extData: m,
  }});

  marker.on('click', function(e) {{
    var d = e.target.getExtData();
    infoWin.setContent(
      '<div style="font-size:14px;line-height:1.7;max-width:260px;">' +
      '<b style="color:' + (brandColors[d.brand_id] || '#333') + '">' + d.brand_name + '</b><br>' +
      '<b>' + d.name + '</b><br>' +
      '地址: ' + (d.address || '—') + '<br>' +
      (d.tel ? '电话: ' + d.tel + '<br>' : '') +
      '距离: 约' + d.distance_m + 'm<br>' +
      '坐标: GCJ-02 (高德)'
    );
    infoWin.open(map, e.target.getPosition());
  }});
}});

map.setFitView(null, false, [60,60,60,60]);
</script>
</body>
</html>"""


STATIONS = [
    ("淮海中路站(13号线)", "淮海中路站(13号线)"),
    ("陕西南路站", "陕西南路站(1/10/12号线)"),
]


def _haversine(lon1, lat1, lon2, lat2):
    R = 6371000
    dlon = math.radians(lon2 - lon1)
    dlat = math.radians(lat2 - lat1)
    a = math.sin(dlat/2)**2 + math.cos(math.radians(lat1)) * math.cos(math.radians(lat2)) * math.sin(dlon/2)**2
    return R * 2 * math.asin(math.sqrt(a))


def _effective_tel(t):
    t = re.sub(r'[-\s]', '', t or '')
    BRAND_HOTLINES = ['4008806453', '4008801515', '4008807985', '4006668800']
    if not t or any(h in t for h in BRAND_HOTLINES):
        return ''
    return t


def _has_type_conflict(na, nb):
    kws = ['kids', 'originals', 'outlet', 'factory', 'mega', '旗舰', '儿童']
    na_low = na.lower()
    nb_low = nb.lower()
    return any((kw in na_low) != (kw in nb_low) for kw in kws)


def dedup_markers(markers: list[dict]) -> list[dict]:
    used = set()
    merged = []
    for i, a in enumerate(markers):
        if i in used: continue
        cluster = [i]; used.add(i)
        for j, b in enumerate(markers):
            if j in used: continue
            if a['brand_id'] != b['brand_id']: continue
            name_match = re.sub(r'\s+', '', a['name']) == re.sub(r'\s+', '', b['name'])
            tel_a, tel_b = _effective_tel(a.get('tel','')), _effective_tel(b.get('tel',''))
            tel_match = bool(tel_a) and tel_a == tel_b
            dist = _haversine(a['lon'], a['lat'], b['lon'], b['lat'])
            mall_a = re.search(r'\((.+?)\)', a['name'])
            mall_b = re.search(r'\((.+?)\)', b['name'])
            mall_a = re.sub(r'(店|\s*)$', '', mall_a.group(1), flags=re.I).strip() if mall_a else ''
            mall_b = re.sub(r'(店|\s*)$', '', mall_b.group(1), flags=re.I).strip() if mall_b else ''
            mall_match = bool(mall_a) and mall_a == mall_b
            if (name_match and tel_match and dist <= 30 and not _has_type_conflict(a['name'], b['name'])) or \
               (name_match and mall_match and dist <= 30 and not _has_type_conflict(a['name'], b['name'])):
                cluster.append(j); used.add(j)
        merged.append(markers[i])
    return merged


def save_snapshot(markers: list[dict]) -> Path:
    snap_dir = SNAPSHOT_DIR / "huaihai_350m"
    snap_dir.mkdir(parents=True, exist_ok=True)
    path = snap_dir / "poi_data.json"
    path.write_text(json.dumps(markers, ensure_ascii=False), encoding="utf-8")
    print(f"  Snapshot → {path} ({len(markers)} POIs)")
    return path


def load_snapshot() -> list[dict] | None:
    path = SNAPSHOT_DIR / "huaihai_350m" / "poi_data.json"
    if path.exists():
        return json.loads(path.read_text(encoding="utf-8"))
    return None


def main():
    parser = argparse.ArgumentParser(description="Scan & map sport brands around Huaihai Rd stations")
    parser.add_argument("--out", default=str(DEFAULT_OUT), help="output HTML path")
    parser.add_argument("--radius", type=int, default=200, help="scan radius in meters")
    parser.add_argument("--from-snapshot", action="store_true", help="load data from snapshot, skip API")
    args = parser.parse_args()

    if args.from_snapshot:
        results = load_snapshot()
        if results is None:
            print("[ERROR] No snapshot found")
            sys.exit(1)
        print(f"Loaded {len(results)} POIs from snapshot")
        centers = []
        # centers not needed for data, only for HTML — use defaults
    else:
        if not AMAP_API_KEY:
            print("[ERROR] AMAP_API_KEY not set in .env")
            sys.exit(1)

        centers = []
        for search_name, display_name in STATIONS:
            print(f"Locating {search_name}...", end=" ")
            coords = find_station_coords(search_name)
            if not coords:
                print("✗ not found")
                continue
            centers.append((display_name, coords[0], coords[1]))
            print(f"✓ ({coords[0]:.5f}, {coords[1]:.5f})")

        if not centers:
            print("[ERROR] No stations found")
            sys.exit(1)

        print(f"\nScanning brands within {args.radius}m ...")
        results = scan_brands_around_multi(centers, args.radius)

        summary = {}
        for r in results:
            summary.setdefault(r["brand_id"], []).append(r["name"])
        for b in BRANDS:
            stores = summary.get(b["id"], [])
            print(f"  {b['name']}: {len(stores)} store(s)")
            for s in stores:
                print(f"    - {s}")

        if not results:
            print("[ERROR] No stores found")
            sys.exit(1)

        save_snapshot(results)

    # For from-snapshot mode, use known station coordinates (no API)
    if args.from_snapshot:
        centers = [
            ("淮海中路站(13号线)", 121.46436, 31.22006),
            ("陕西南路站(1/10/12号线)", 121.45874, 31.21515),
        ]

    results = dedup_markers(results)
    html = generate_html(results, centers, radius=args.radius)
    out_path = Path(args.out)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(html, encoding="utf-8")
    print(f"\nMap saved → {out_path}")


if __name__ == "__main__":
    main()
