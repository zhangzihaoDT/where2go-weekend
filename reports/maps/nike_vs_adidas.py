"""
Nike vs Adidas city-wide store comparison — supports single or dual city.

Usage:
  python3 reports/maps/nike_vs_adidas.py --city 上海
  python3 reports/maps/nike_vs_adidas.py --city 苏州
  python3 reports/maps/nike_vs_adidas.py --cities 上海 苏州   # combined HTML
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
SVG_DIR = PROJECT_ROOT / "assets" / "brand_logo"
SNAPSHOT_DIR = PROJECT_ROOT / "data" / "brand_stores" / "snapshots"


def _extract_mall(name):
    m = re.search(r'\((.+?)\)', name)
    if m:
        return re.sub(r'(店|\s*)$', '', m.group(1), flags=re.I).strip()
    return ''

sys.path.insert(0, str(PROJECT_ROOT))

load_dotenv()
AMAP_API_KEY = (os.environ.get("AMAP_API_KEY") or "").strip()
AMAP_API_SECRET = (os.environ.get("AMAP_API_SECRET") or "").strip()
AMAP_JS_KEY = (os.environ.get("AMAP_JS_API_KEY") or "").strip()
AMAP_SEC_CODE = (os.environ.get("AMAP_SECURITY_JS_CODE") or "").strip()

BRANDS = [
    {"id": "nike",   "name": "Nike",   "keywords": ["耐克", "Nike"],         "color": "#DD1E2C", "logo_svg": (SVG_DIR / "nike.svg").read_text(encoding="utf-8")},
    {"id": "adidas", "name": "Adidas", "keywords": ["阿迪达斯", "adidas"],     "color": "#0077C8", "logo_svg": (SVG_DIR / "adidas.svg").read_text(encoding="utf-8")},
]

CITY_CENTERS = {
    "上海": (121.47, 31.23),
    "苏州": (120.58, 31.30),
}

MAX_PAGES = 20
PAGE_OFFSET = 25
SLEEP = 0.5


def _sign_params(params: dict, secret: str) -> str:
    sorted_keys = sorted(params.keys())
    raw = "&".join(f"{k}={params[k]}" for k in sorted_keys)
    raw += secret
    return hashlib.md5(raw.encode("utf-8")).hexdigest()


def amap_text_search(keyword: str, city: str, page: int = 1) -> list[dict]:
    url = "https://restapi.amap.com/v3/place/text"
    params = {
        "key": AMAP_API_KEY, "keywords": keyword, "city": city,
        "citylimit": "true", "offset": PAGE_OFFSET, "page": page,
        "extensions": "base",
    }
    if AMAP_API_SECRET:
        params["sig"] = _sign_params(params, AMAP_API_SECRET)
    data = requests.get(url, params=params, timeout=10).json()
    if data.get("status") == "1":
        return data.get("pois", [])
    return []


def scan_brand_citywide(brand: dict, city: str) -> list[dict]:
    seen_ids = set()
    results = []

    for kw in brand["keywords"]:
        for page in range(1, MAX_PAGES + 1):
            pois = amap_text_search(kw, city, page)
            if not pois:
                break
            for p in pois:
                poi_id = p.get("id", "")
                if poi_id and poi_id in seen_ids:
                    continue
                if poi_id:
                    seen_ids.add(poi_id)

                loc = p.get("location", "").split(",")
                if len(loc) != 2:
                    continue
                try:
                    plng, plat = float(loc[0]), float(loc[1])
                except ValueError:
                    continue

                # filter noise (非 Nike 实体但名中含"耐克")
                if brand['id'] == 'nike':
                    name_check = p.get("name", "")
                    is_noise = any(_np in name_check and 'Nike' not in name_check and 'NIKE' not in name_check for _np in NIKE_NOISE_PREFIX)
                    if is_noise:
                        continue

                results.append({
                    "name": p.get("name", ""),
                    "address": p.get("address", ""),
                    "district": p.get("adname", ""),
                    "city": city,
                    "lon": plng,
                    "lat": plat,
                    "brand_id": brand["id"],
                    "brand_name": brand["name"],
                    "color": brand["color"],
                    "logo_svg": brand["logo_svg"],
                    "tel": p.get("tel", "") if isinstance(p.get("tel"), str) else "",
                })
            time.sleep(SLEEP)
    return results


def generate_html(all_markers: list[dict], cities: list[str]) -> str:
    markers_json = json.dumps(all_markers, ensure_ascii=True)
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

    city = cities[0] if len(cities) == 1 else "沪苏"
    default_center = CITY_CENTERS.get(cities[0], (121.47, 31.23))

    # stats per city
    city_stats = {}
    for c in cities:
        c_nike = sum(1 for m in all_markers if m["city"] == c and m["brand_id"] == "nike")
        c_adi = sum(1 for m in all_markers if m["city"] == c and m["brand_id"] == "adidas")
        city_stats[c] = (c_nike, c_adi)

    return f"""<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>Nike vs Adidas 门店对比 — {' · '.join(cities)}</title>
<style>
  body {{ margin:0; padding:0; font-family:-apple-system,'Helvetica Neue','PingFang SC',sans-serif; }}
  #map {{ width:100%; height:75vh; }}
  .panel {{
    max-width:100%; margin:8px 16px; display:flex; flex-wrap:wrap; gap:12px;
  }}
  .legend {{
    background:#fff; padding:10px 14px; border-radius:8px;
    box-shadow:0 2px 8px rgba(0,0,0,0.12); font-size:13px; line-height:1.8;
    flex:1; min-width:160px;
  }}
  .legend h4 {{ margin:0 0 4px 0; font-size:13px; color:#1F2D3D; }}
  .filter-bar {{
    background:#fff; padding:8px 14px; border-radius:8px;
    box-shadow:0 2px 8px rgba(0,0,0,0.12); font-size:13px;
    display:flex; flex-wrap:wrap; gap:8px 16px; align-items:center;
  }}
  .filter-bar label {{ cursor:pointer; display:inline-flex; align-items:center; gap:4px; }}
  .filter-bar input {{ margin:0; }}
  .store-list {{
    background:#fff; padding:10px 14px; border-radius:8px;
    box-shadow:0 2px 8px rgba(0,0,0,0.12); font-size:13px; line-height:1.7;
    flex:2; min-width:260px; max-height:180px; overflow-y:auto;
  }}
  .store-list h4 {{ margin:0 0 4px 0; font-size:13px; color:#1F2D3D; }}
  .store-item {{ display:flex; align-items:center; gap:6px; padding:1px 0; }}
  .store-dot {{ width:8px;height:8px;border-radius:50%;flex-shrink:0; }}
  .city-tag {{
    font-size:10px; padding:1px 5px; border-radius:3px; color:#fff; flex-shrink:0;
  }}
  .logo-marker {{
    border-radius:50%; overflow:hidden;
    border:1px solid rgba(255,255,255,0.6); box-shadow:0 1px 4px rgba(0,0,0,0.12);
    display:flex; align-items:center; justify-content:center;
    cursor:pointer; transition:transform 0.15s, width 0.1s, height 0.1s;
    opacity:0.75;
  }}
  .logo-marker:hover {{ opacity:1; }}
  .logo-marker:hover {{ transform:scale(1.2); }}
  .logo-marker svg {{ display:block; }}
</style>
</head>
<body>
<div id="map"></div>
<div class="panel">
  <div class="filter-bar">
    <b>城市：</b>
    {"".join(f'<label><input type="checkbox" class="city-filter" data-city="{c}" checked> {c}</label>' for c in cities)}
    &nbsp;&nbsp;<b>品牌：</b>
    {"".join(f'<label><input type="checkbox" class="brand-filter" data-brand="{b["id"]}" checked> <span style="display:inline-block;width:8px;height:8px;border-radius:50%;background:{b["color"]}"></span> {b["name"]}</label>' for b in BRANDS)}
  </div>
</div>
<div class="panel">
  <div class="legend">
    <h4>统计</h4>
    {"".join(f'<div>{c} — Nike {n} / Adidas {a}</div>' for c, (n, a) in city_stats.items())}
    <div style="margin-top:4px;font-size:11px;color:#999;">总计: {len(all_markers)} 家门店</div>
  </div>
  <div class="store-list">
    <h4>门店列表</h4>
    <div id="storeList">
    {"".join(
        f'    <div class="store-item" data-city="{m["city"]}" data-brand="{m["brand_id"]}">'
        f'<span class="city-tag" style="background:{CITY_CENTERS.get(m["city"], ("#999",))[1] if False else "#999"}">{m["city"]}</span>'
        f'<span class="store-dot" style="background:{m["color"]}"></span>'
        f'<b>{m["brand_name"]}</b> — {m["name"]}'
        f'<span style="color:#999;font-size:11px;margin-left:auto;">{m.get("district", "")}</span>'
        f'</div>'
        for m in sorted(all_markers, key=lambda x: (x["city"], x["brand_id"], x.get("district", "")))
    )}
    </div>
  </div>
</div>

{sec_config}
<script src="{src_url}"></script>
<script>
var map = new AMap.Map('map', {{
  center: [{default_center[0]}, {default_center[1]}],
  zoom: {11 if len(cities) == 1 else 10},
  mapStyle: 'amap://styles/grey',
  features: ['bg', 'road'],
  viewMode: '2D',
  pitch: 0, rotation: 0,
  rotateEnable: false, pitchEnable: false,
  doubleClickZoom: false,
}});

var brandColors = {brand_colors_json};
var markers = {markers_json};
var infoWin = new AMap.InfoWindow({{offset: new AMap.Pixel(0, -30)}});
var markerWraps = [];

/* city color mapping */
var cityColors = {json.dumps({c: "#999" for c in cities}, ensure_ascii=True)};

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
      '城市: ' + d.city + '<br>' +
      '地址: ' + (d.address || '—') + '<br>' +
      '区: ' + (d.district || '') + '<br>' +
      (d.tel ? '电话: ' + d.tel + '<br>' : '') +
      '坐标: GCJ-02'
    );
    infoWin.open(map, e.target.getPosition());
  }});

  markerWraps.push({{ wrap: wrap, marker: marker }});
  marker._city = m.city;
  marker._brand = m.brand_id;
}});

/* zoom-responsive marker sizing */
function resizeMarkers() {{
  var z = map.getZoom();
  var size, svgSize, borderW;
  if (z <= 8) {{ size = 10; svgSize = 7; borderW = 1; }}
  else if (z <= 10) {{ size = 14; svgSize = 9; borderW = 1; }}
  else if (z <= 12) {{ size = 18; svgSize = 12; borderW = 1.5; }}
  else if (z <= 14) {{ size = 24; svgSize = 16; borderW = 2; }}
  else {{ size = 30; svgSize = 20; borderW = 2; }}
  markerWraps.forEach(function(item) {{
    item.wrap.style.width = size + 'px';
    item.wrap.style.height = size + 'px';
    item.wrap.style.borderWidth = borderW + 'px';
    var svg = item.wrap.querySelector('svg');
    if (svg) {{ svg.style.width = svgSize + 'px'; svg.style.height = svgSize + 'px'; }}
  }});
}}
map.on('zoomend', resizeMarkers);
resizeMarkers();

map.setFitView(null, false, [50,50,50,50]);

/* ── Filter logic ── */
function applyFilters() {{
  var activeCities = {{}};
  document.querySelectorAll('.city-filter').forEach(function(cb) {{
    activeCities[cb.dataset.city] = cb.checked;
  }});
  var activeBrands = {{}};
  document.querySelectorAll('.brand-filter').forEach(function(cb) {{
    activeBrands[cb.dataset.brand] = cb.checked;
  }});

  markerWraps.forEach(function(item) {{
    var d = item.marker.getExtData();
    var visible = activeCities[d.city] !== false && activeBrands[d.brand_id] !== false;
    item.marker.setMap(visible ? map : null);
  }});

  /* update store list */
  document.querySelectorAll('#storeList .store-item').forEach(function(el) {{
    var show = activeCities[el.dataset.city] !== false && activeBrands[el.dataset.brand] !== false;
    el.style.display = show ? '' : 'none';
  }});
}}

document.querySelectorAll('.city-filter, .brand-filter').forEach(function(cb) {{
  cb.addEventListener('change', applyFilters);
}});
</script>
</body>
</html>"""


def save_snapshot(markers: list[dict], cities: list[str]) -> Path:
    suffix = "_".join(cities)
    snap_dir = SNAPSHOT_DIR / f"{suffix}_nike_adidas"
    snap_dir.mkdir(parents=True, exist_ok=True)
    path = snap_dir / "poi_data.json"
    path.write_text(json.dumps(markers, ensure_ascii=False), encoding="utf-8")
    print(f"  Snapshot saved → {path} ({len(markers)} POIs)")
    return path


def load_snapshot(cities: list[str]) -> list[dict] | None:
    suffix = "_".join(cities)
    path = SNAPSHOT_DIR / f"{suffix}_nike_adidas" / "poi_data.json"
    if path.exists():
        return json.loads(path.read_text(encoding="utf-8"))
    return None


BRAND_HOTLINES_NIKE = ['4008806453', '4008801515', '4008807985', '4006668800']

NIKE_NOISE_PREFIX = ['施耐克', '耐克森', '博耐克', '狄耐克', '金耐克']


def _is_nike_noise(r: dict) -> bool:
    if r['brand_id'] != 'nike':
        return False
    name = r.get('name', '')
    for p in NIKE_NOISE_PREFIX:
        if p in name:
            if 'Nike' not in name and 'NIKE' not in name:
                return True
    return False

def _haversine(lon1, lat1, lon2, lat2):
    R = 6371000
    dlon = math.radians(lon2 - lon1)
    dlat = math.radians(lat2 - lat1)
    a = math.sin(dlat/2)**2 + math.cos(math.radians(lat1)) * math.cos(math.radians(lat2)) * math.sin(dlon/2)**2
    return R * 2 * math.asin(math.sqrt(a))


def _eff_tel(t):
    t = re.sub(r'[-\s]', '', t or '')
    if not t or any(h in t for h in BRAND_HOTLINES_NIKE):
        return ''
    return t


def _type_conflict(na, nb):
    kws = ['kids', 'originals', 'outlet', 'factory', 'mega', '旗舰', '儿童', 'neo']
    na_low = na.lower()
    nb_low = nb.lower()
    return any((kw in na_low) != (kw in nb_low) for kw in kws)


def dedup_markers(markers: list[dict]) -> list[dict]:
    # pre-filter noise
    markers = [m for m in markers if not _is_nike_noise(m)]

    used = set()
    merged = []
    for i, a in enumerate(markers):
        if i in used:
            continue
        cluster = [i]
        used.add(i)
        for j, b in enumerate(markers):
            if j in used:
                continue
            if a['brand_id'] != b['brand_id']:
                continue
            nm_a = re.sub(r'\s+', '', a['name'])
            nm_b = re.sub(r'\s+', '', b['name'])
            name_match = nm_a == nm_b
            ta, tb = _eff_tel(a.get('tel', '')), _eff_tel(b.get('tel', ''))
            tel_match = bool(ta) and ta == tb
            d = _haversine(a['lon'], a['lat'], b['lon'], b['lat'])
            mall_a = _extract_mall(a['name'])
            mall_b = _extract_mall(b['name'])
            mall_match = bool(mall_a) and mall_a == mall_b
            if (name_match and tel_match and d <= 30 and not _type_conflict(nm_a, nm_b)) or \
               (name_match and mall_match and d <= 30 and not _type_conflict(nm_a, nm_b)):
                cluster.append(j)
                used.add(j)
        merged.append(markers[i])
    return merged


def main():
    parser = argparse.ArgumentParser(description="Nike vs Adidas city-wide store comparison")
    parser.add_argument("--out", default="", help="output HTML path")
    parser.add_argument("--city", default="", help="single city to scan")
    parser.add_argument("--cities", nargs="+", default=[], help="multiple cities (combined)")
    parser.add_argument("--from-snapshot", action="store_true", help="load from saved snapshot, skip API")
    args = parser.parse_args()

    cities = args.cities or ([args.city] if args.city else ["上海"])

    if args.from_snapshot:
        all_markers = load_snapshot(cities)
        if all_markers is None:
            print(f"[ERROR] No snapshot found for {'_'.join(cities)}")
            sys.exit(1)
        print(f"Loaded {len(all_markers)} POIs from snapshot")
    else:
        if not AMAP_API_KEY:
            print("[ERROR] AMAP_API_KEY not set in .env")
            sys.exit(1)

        all_markers = []
        for city in cities:
            for brand in BRANDS:
                print(f"Scanning {brand['name']} @ {city}...", end=" ", flush=True)
                stores = scan_brand_citywide(brand, city)
                print(f"{len(stores)} stores")
                all_markers.extend(stores)

        if not all_markers:
            print("[ERROR] No stores found")
            sys.exit(1)

        save_snapshot(all_markers, cities)

    # default output path
    suffix = "_".join(cities)
    out_path = Path(args.out or PROJECT_ROOT / "reports" / "maps" / f"nike_vs_adidas_{suffix}.html")

    all_markers = dedup_markers(all_markers)
    print(f"  After dedup: {len(all_markers)} entities")
    html = generate_html(all_markers, cities)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(html, encoding="utf-8")
    print(f"\nMap saved → {out_path}")
    print(f"Total: {len(all_markers)} stores across {len(cities)} city/cities")


if __name__ == "__main__":
    main()
