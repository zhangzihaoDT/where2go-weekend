"""
Map visualization layer for where2go-weekend.

Supports two providers:
- amap_js: AMap JS API (default) — uses GCJ-02 directly
- leaflet_osm: Leaflet + OSM — optional GCJ-02→WGS84 transform
"""

import csv
import math
import os
import warnings

import yaml


# ── Coordinate transform (approximate, visualization only) ──


def _transform_lat(lng: float, lat: float) -> float:
    x = lng - 105.0
    y = lat - 35.0
    ret = -100.0 + 2.0 * x + 3.0 * y + 0.2 * y * y + 0.1 * x * y + 0.2 * math.sqrt(abs(x))
    ret += (20.0 * math.sin(6.0 * x * math.pi) + 20.0 * math.sin(2.0 * x * math.pi)) * 2.0 / 3.0
    ret += (20.0 * math.sin(y * math.pi) + 40.0 * math.sin(y / 3.0 * math.pi)) * 2.0 / 3.0
    ret += (160.0 * math.sin(y / 12.0 * math.pi) + 320.0 * math.sin(y * math.pi / 30.0)) * 2.0 / 3.0
    return ret


def _transform_lng(lng: float, lat: float) -> float:
    x = lng - 105.0
    y = lat - 35.0
    ret = 300.0 + x + 2.0 * y + 0.1 * x * x + 0.1 * x * y + 0.1 * math.sqrt(abs(x))
    ret += (20.0 * math.sin(6.0 * x * math.pi) + 20.0 * math.sin(2.0 * x * math.pi)) * 2.0 / 3.0
    ret += (20.0 * math.sin(x * math.pi) + 40.0 * math.sin(x / 3.0 * math.pi)) * 2.0 / 3.0
    ret += (150.0 * math.sin(x / 12.0 * math.pi) + 300.0 * math.sin(x / 30.0 * math.pi)) * 2.0 / 3.0
    return ret


def _wgs84_to_gcj02(lng: float, lat: float) -> tuple[float, float]:
    """WGS84 to GCJ-02 (approximate)."""
    dlat = _transform_lat(lng - 105.0, lat - 35.0)
    dlng = _transform_lng(lng - 105.0, lat - 35.0)
    radlat = lat / 180.0 * math.pi
    magic = math.sin(radlat)
    magic = 1 - 0.00669342162296594323 * magic * magic
    sqrtmagic = math.sqrt(magic)
    dlat = (dlat * 180.0) / ((6378245.0 / sqrtmagic) * math.cos(radlat) * math.pi)
    dlng = (dlng * 180.0) / (6378245.0 / sqrtmagic * math.cos(radlat) * math.pi)
    return lng + dlng, lat + dlat


def gcj02_to_wgs84_approx(lng: float, lat: float) -> tuple[float, float]:
    """
    Convert GCJ-02 to WGS84 using iterative approximation.

    APPROXIMATE / VISUALIZATION ONLY.
    Not for navigation, surveying, or precision measurement.
    """
    if not (73 <= lng <= 135 and 3 <= lat <= 54):
        warnings.warn(f"Coordinates ({lng}, {lat}) outside reasonable China range, returning as-is")
        return lng, lat
    wgs_lng, wgs_lat = lng, lat
    for _ in range(5):
        gcj_lng, gcj_lat = _wgs84_to_gcj02(wgs_lng, wgs_lat)
        d_lng = gcj_lng - lng
        d_lat = gcj_lat - lat
        wgs_lng -= d_lng
        wgs_lat -= d_lat
    return wgs_lng, wgs_lat


def transform_poi_coords(poi: dict, coord_mode: str) -> dict:
    """Apply coordinate transform to a POI row, returning enriched dict."""
    try:
        source_lng = float(poi.get("lng", 0))
        source_lat = float(poi.get("lat", 0))
    except (ValueError, TypeError):
        source_lng, source_lat = 0.0, 0.0

    result = dict(poi)
    result["source_lng"] = source_lng
    result["source_lat"] = source_lat
    result["source_crs"] = "GCJ-02"

    if coord_mode == "raw_gcj02":
        result["map_lng"] = source_lng
        result["map_lat"] = source_lat
        result["map_crs"] = "GCJ-02"
        result["coord_transform_method"] = "none"
    else:
        if source_lng != 0.0 and source_lat != 0.0:
            map_lng, map_lat = gcj02_to_wgs84_approx(source_lng, source_lat)
        else:
            map_lng, map_lat = source_lng, source_lat
        result["map_lng"] = map_lng
        result["map_lat"] = map_lat
        result["map_crs"] = "WGS84"
        result["coord_transform_method"] = "gcj02_to_wgs84_approx"

    return result


# ── Shared helpers ──


CATEGORY_COLORS = {
    "coffee": "#D4A574",
    "food_light": "#7ECDEB",
    "art_space": "#D79A36",
    "lifestyle": "#174A7C",
    "compound_space": "#7A4A24",
}

CATEGORY_LABELS = {
    "coffee": "咖啡",
    "food_light": "轻食",
    "art_space": "艺术空间",
    "lifestyle": "生活方式",
    "compound_space": "复合空间",
}


def _js_str(s: str) -> str:
    return s.replace("\\", "\\\\").replace("'", "\\'")


# ── Load helpers ──


def _load_snapshot_rows(path: str) -> list[dict]:
    with open(path, encoding="utf-8") as f:
        return list(csv.DictReader(f))


def _load_districts(path: str) -> list[dict]:
    with open(path, encoding="utf-8") as f:
        cfg = yaml.safe_load(f)
    return cfg.get("districts", [])


# ══════════════════════════════════════════════════════════
#  Provider: AMap JS API
# ══════════════════════════════════════════════════════════


# ── AMap style defaults ──

DEFAULT_AMAP_STYLE = "amap://styles/grey"
DEFAULT_AMAP_FEATURES = ("bg", "road")


def _amap_key_status() -> dict:
    """Check AMap JS API key config. Never returns secrets."""
    from dotenv import load_dotenv
    load_dotenv()
    js_key = os.environ.get("AMAP_JS_API_KEY", "").strip()
    sec_code = os.environ.get("AMAP_SECURITY_JS_CODE", "").strip()
    return {
        "has_js_key": bool(js_key),
        "has_sec_code": bool(sec_code),
        "js_key": js_key,
        "sec_code": sec_code,
    }


import json


def _valid_coords(r: dict) -> bool:
    try:
        lng = float(r.get("lng", 0))
        lat = float(r.get("lat", 0))
        return lng != 0 and lat != 0
    except (ValueError, TypeError):
        return False


def generate_amap_js_map(
    poi_snapshot_path: str,
    districts_path: str,
    output_path: str,
    snapshot_date: str,
    weekend_date: str,
    map_style: str = DEFAULT_AMAP_STYLE,
    map_features: tuple[str, ...] = DEFAULT_AMAP_FEATURES,
) -> str:
    """Generate a HTML map using AMap JS API with raw GCJ-02 coordinates."""
    rows = _load_snapshot_rows(poi_snapshot_path)
    districts_raw = _load_districts(districts_path)

    key_info = _amap_key_status()
    has_js_key = key_info["has_js_key"]
    has_sec_code = key_info["has_sec_code"]
    js_key = key_info["js_key"]
    sec_code = key_info["sec_code"]

    center_lng = 121.47
    center_lat = 31.23
    poi_count = len(rows)

    # Prepare JSON-serializable district data
    district_data = []
    for d in districts_raw:
        district_data.append({
            "name": d.get("name", ""),
            "center_lng": d.get("center_lng", 0),
            "center_lat": d.get("center_lat", 0),
            "radius_m": d.get("radius_m", 500),
        })

    # Prepare JSON-serializable POI data with category info
    poi_data = []
    for r in rows:
        if not _valid_coords(r):
            continue
        cat = r.get("category_id", "unknown")
        label = CATEGORY_LABELS.get(cat, cat)
        poi_data.append({
            "lng": float(r.get("lng", 0)),
            "lat": float(r.get("lat", 0)),
            "cat": cat,
            "name": r.get("name", "?"),
            "dname": r.get("district_name", ""),
            "label": label,
            "addr": r.get("address", ""),
            "src": r.get("source", ""),
            "kw": r.get("keyword", ""),
        })

    district_json = json.dumps(district_data, ensure_ascii=False)
    poi_json = json.dumps(poi_data, ensure_ascii=False)
    parts = []

    # ── HTML head ──
    parts.append("""<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>where2go-weekend 城市变化雷达 — 地图预览 (高德)</title>
<style>
  body { margin: 0; padding: 0; font-family: -apple-system, 'Helvetica Neue', sans-serif; }
  #map { width: 100%; height: 80vh; }
  .info-box {
    background: #fff; padding: 12px 16px; border-radius: 8px;
    box-shadow: 0 2px 8px rgba(0,0,0,0.15); font-size: 13px; line-height: 1.6;
  }
  .info-box h3 { margin: 0 0 6px 0; font-size: 14px; }
  .legend { line-height: 1.8; }
  .legend i { width: 14px; height: 14px; display: inline-block; border-radius: 50%; margin-right: 6px; vertical-align: middle; }
  .warning { background:#FFF3CD; border-left:4px solid #D79A36; padding:8px 14px; font-size:13px; margin:0 0 4px 0; }
  /* ── District paper-tag markers ── */
  .district-marker-wrap {
    display: inline-block; width: max-content;
    white-space: nowrap; cursor: pointer;
  }
  .district-marker {
    display: inline-flex; align-items: center; gap: 8px;
    padding: 5px 10px 5px 6px; border-radius: 999px;
    background: #FFF9EF; border: 1px solid #D79A36;
    box-shadow: 0 3px 10px rgba(31,45,61,0.16);
    font-family: -apple-system, BlinkMacSystemFont, "PingFang SC", sans-serif;
    white-space: nowrap;
    width: max-content; min-width: max-content;
  }
  .district-rank {
    width: 20px; height: 20px; border-radius: 999px;
    background: #174A7C; color: #fff;
    font-size: 12px; font-weight: 700;
    display: flex; align-items: center; justify-content: center;
    flex-shrink: 0;
  }
  .district-main {
    display: flex; flex-direction: column;
    min-width: max-content; white-space: nowrap;
  }
  .district-name {
    font-size: 13px; font-weight: 700; color: #1F2D3D;
    line-height: 1.2; white-space: nowrap;
  }
  /* ── POI dot markers ── */
  .poi-marker-wrap { cursor: pointer; }
  .poi-marker-wrap:hover .poi-marker { transform: scale(1.3); }
  .poi-marker {
    width: 16px; height: 16px; border-radius: 999px;
    display: flex; align-items: center; justify-content: center;
    background: rgba(255,249,239,0.92);
    border: 1px solid rgba(31,45,61,0.18);
    box-shadow: 0 2px 6px rgba(31,45,61,0.20);
    transition: transform 0.15s;
  }
  .poi-marker:hover { transform: scale(1.3); }
  .poi-dot { width: 8px; height: 8px; border-radius: 999px; background: #6B7280; }
  .poi-coffee .poi-dot { background: #D4A574; }
  .poi-food_light .poi-dot { background: #7ECDEB; }
  .poi-art_space .poi-dot { background: #D79A36; }
  .poi-lifestyle .poi-dot { background: #174A7C; }
  .poi-compound_space .poi-dot { background: #7A4A24; }
  @media (max-width: 600px) { #map { height: 60vh; } }
</style>
</head>
<body>""")

    # ── Warnings ──
    if not has_js_key:
        parts.append("""<div class="warning">⚠ 缺少 AMAP_JS_API_KEY，地图可能无法加载。请在 .env 中配置 AMAP_JS_API_KEY。</div>""")
    if has_js_key and not has_sec_code:
        parts.append("""<div class="warning">⚠ 缺少 AMAP_SECURITY_JS_CODE。高德 JS API 2.0 在部分 key 配置下需要安全密钥。</div>""")

    # ── Map container + AMap scripts ──
    parts.append('<div id="map"></div>')

    if has_sec_code:
        parts.append(f"""<script>window._AMapSecurityConfig = {{securityJsCode: "{sec_code}"}};</script>""")
    if has_js_key:
        parts.append(f"""<script src="https://webapi.amap.com/maps?v=2.0&key={js_key}"></script>""")
    else:
        # No key — still include script (will fail silently) for testability
        parts.append("""<script src="https://webapi.amap.com/maps?v=2.0&key=NO_KEY"></script>""")

    features_json = json.dumps(list(map_features), ensure_ascii=True)

    parts.append("""<script>
var map = new AMap.Map('map', {
  center: [""" + str(center_lng) + ", " + str(center_lat) + """],
  zoom: 13,
  mapStyle: \"""" + map_style + """\",
  features: """ + features_json + """,
  viewMode: '2D',
  pitch: 0,
  rotation: 0,
  rotateEnable: false,
  pitchEnable: false,
  doubleClickZoom: false,
});
var bounds = [];
var districtMarkers = [];
var poiMarkers = [];

  /* ---------- Helpers ---------- */
  function safeClassName(value) {
    return String(value || 'default').toLowerCase().replace(/[^a-z0-9_-]/g, '_');
  }

  /* ---------- Factory: createHtmlMarker ---------- */
  function createHtmlMarker(opt) {
    var marker = new AMap.Marker({
      map: map,
      position: opt.position,
      content: opt.content,
      anchor: opt.anchor || 'center',
      zIndex: opt.zIndex || 20,
      extData: opt.extData || {},
      cursor: 'pointer',
    });
    return { marker: marker, el: opt.content };
  }

  /* ---------- createDistrictElement ---------- */
  function createDistrictElement(district, index) {
    var wrap = document.createElement('div');
    wrap.className = 'district-marker-wrap';

    var root = document.createElement('div');
    root.className = 'district-marker';

    var rank = document.createElement('div');
    rank.className = 'district-rank';
    rank.textContent = String(index + 1);

    var main = document.createElement('div');
    main.className = 'district-main';

    var nameEl = document.createElement('div');
    nameEl.className = 'district-name';
    nameEl.textContent = district.name || '';

    main.appendChild(nameEl);
    root.appendChild(rank);
    root.appendChild(main);
    wrap.appendChild(root);

    return wrap;
  }

  /* ---------- createPoiElement ---------- */
  function createPoiElement(poi) {
    var cls = 'poi-marker poi-' + safeClassName(poi.cat);

    var wrap = document.createElement('div');
    wrap.className = 'poi-marker-wrap ' + cls;
    wrap.title = poi.name || '';

    var dot = document.createElement('span');
    dot.className = 'poi-dot';

    wrap.appendChild(dot);
    return wrap;
  }

  /* ---------- District circles + paper-tag markers ---------- */
  var districtData = """ + district_json + """;
  districtData.forEach(function(d, i) {
    new AMap.Circle({
      center: [d.center_lng, d.center_lat],
      radius: d.radius_m || 500,
      strokeColor: '#174A7C', strokeWeight: 1.5,
      fillColor: '#DDEFF8', fillOpacity: 0.2,
    }).setMap(map);
    var el = createDistrictElement(d, i);
    var result = createHtmlMarker({
      position: [d.center_lng, d.center_lat],
      content: el,
      zIndex: 50,
      anchor: 'top-center',
      extData: d,
    });
    districtMarkers.push(result.marker);
    bounds.push([d.center_lat, d.center_lng]);
  });

  /* ── Shared InfoWindow ── */
  var _infoWin = new AMap.InfoWindow({offset: new AMap.Pixel(0, -30)});
  function _showPoiInfo(e) {
    var d = e.target.getExtData();
    _infoWin.setContent(
      '<div style=\\"font-size:13px;line-height:1.6;max-width:280px;\\">' +
      '<b>' + d.name + '</b><br>' +
      '街区: ' + d.dname + '<br>' +
      '类目: ' + d.label + '<br>' +
      '地址: ' + d.addr + '<br>' +
      'source: ' + d.src + '<br>' +
      'keyword: ' + d.kw + '<br>' +
      'source_crs: GCJ-02<br>' +
      'coord_transform: none</div>'
    );
    _infoWin.open(map, e.target.getPosition());
  }

  /* ---------- POI dot markers ---------- */
  var poiData = """ + poi_json + """;
  poiData.forEach(function(p) {
    var el = createPoiElement(p);
    var result = createHtmlMarker({
      position: [p.lng, p.lat],
      content: el,
      zIndex: 30,
      extData: p,
    });
    result.marker.on('click', _showPoiInfo);
    poiMarkers.push(result.marker);
    bounds.push([p.lat, p.lng]);
  });

  map.setFitView(null, false, [40, 40, 40, 40]);
</script>""")

    # ── Static legend + info below map ──
    parts.append("""
<div style="max-width:100%;margin:8px 16px;font-family:-apple-system,'Helvetica Neue',sans-serif;">
<div style="display:flex;flex-wrap:wrap;gap:12px 24px;">
  <div class="info-box" style="flex:1;min-width:200px;">
    <h3>图例</h3>
    <div class="legend">""")
    for cat, color in CATEGORY_COLORS.items():
        clabel = CATEGORY_LABELS.get(cat, cat)
        parts.append(f'      <i style="background:{color};width:10px;height:10px;display:inline-block;border-radius:50%;margin-right:6px"></i> {clabel}<br>')
    parts.append(f"""    </div>
  </div>
  <div class="info-box" style="flex:2;min-width:240px;">
    <h3>数据说明</h3>
    快照日期: <b>{snapshot_date}</b><br>
    目标周末: <b>{weekend_date}</b><br>
    POI 数量: <b>{len(poi_data)}</b> | 街区数量: <b>{len(district_data)}</b><br>
    地图 provider: <b>amap_js</b> | 坐标体系: <b>GCJ-02</b><br>
    <hr style="margin:6px 0">
    <div style="font-size:12px;color:#6B7C8F;">
      本地图使用高德 JS API 底图，POI 坐标来自高德 Web Service，坐标体系为 GCJ-02。
      该模式用于验证高德 POI 点位，减少坐标转换偏差。
    </div>
  </div>
</div>
</div>
</body>
</html>""")

    os.makedirs(os.path.dirname(output_path), exist_ok=True)
    html = "\n".join(parts)
    with open(output_path, "w", encoding="utf-8") as f:
        f.write(html)
    return output_path

    os.makedirs(os.path.dirname(output_path), exist_ok=True)
    html = "\n".join(parts)
    with open(output_path, "w", encoding="utf-8") as f:
        f.write(html)
    return output_path


# ══════════════════════════════════════════════════════════
#  Provider: Leaflet + OSM
# ══════════════════════════════════════════════════════════


def generate_leaflet_osm_map(
    poi_snapshot_path: str,
    districts_path: str,
    output_path: str,
    snapshot_date: str,
    weekend_date: str,
    coord_mode: str = "approx_wgs84",
) -> str:
    """Generate a Leaflet + OSM HTML map with optional GCJ-02→WGS84 transform."""
    rows = _load_snapshot_rows(poi_snapshot_path)
    districts = _load_districts(districts_path)
    transformed = [transform_poi_coords(r, coord_mode) for r in rows]

    center_lng = 121.47
    center_lat = 31.23

    parts = []
    parts.append("""<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>where2go-weekend 城市变化雷达 — 地图预览 (Leaflet)</title>
<link rel="stylesheet" href="https://unpkg.com/leaflet@1.9.4/dist/leaflet.css" />
<script src="https://unpkg.com/leaflet@1.9.4/dist/leaflet.js"></script>
<style>
  body { margin: 0; padding: 0; font-family: -apple-system, 'Helvetica Neue', sans-serif; }
  #map { width: 100%; height: 80vh; }
  .info-box {
    background: #fff; padding: 12px 16px; border-radius: 8px;
    box-shadow: 0 2px 8px rgba(0,0,0,0.15); font-size: 13px; line-height: 1.6;
  }
  .info-box h3 { margin: 0 0 6px 0; font-size: 14px; }
  .legend { line-height: 1.8; }
  .legend i { width: 14px; height: 14px; display: inline-block; border-radius: 50%; margin-right: 6px; vertical-align: middle; }
  @media (max-width: 600px) { #map { height: 60vh; } }
</style>
</head>
<body>
<div id="map"></div>
<script>
  var map = L.map('map').setView([""" + f"{center_lat}, {center_lng}" + """], 13);
  L.tileLayer('https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png', {
    attribution: '&copy; OSM',
    maxZoom: 18,
  }).addTo(map);
  var bounds = [];
""")

    for d in districts:
        dlng = d.get("center_lng", 0)
        dlat = d.get("center_lat", 0)
        radius = d.get("radius_m", 500)
        name = _js_str(d.get("name", ""))
        parts.append(f"""
  L.circle([{dlat}, {dlng}], {{
    radius: {radius}, color: '#174A7C', fillColor: '#DDEFF8',
    fillOpacity: 0.2, weight: 1.5,
  }}).addTo(map).bindPopup('<b>{name}</b><br>采样半径: {radius}m');
  L.marker([{dlat}, {dlng}], {{
    icon: L.divIcon({{
      className: 'district-center',
      html: '<div style="background:#174A7C;color:#fff;border-radius:4px;padding:2px 6px;font-size:11px;white-space:nowrap;">{name}</div>',
      iconSize: [0, 0],
    }})
  }}).addTo(map);
  bounds.push([{dlat}, {dlng}]);""")

    for t in transformed:
        try:
            mlng = float(t.get("map_lng", 0))
            mlat = float(t.get("map_lat", 0))
        except (ValueError, TypeError):
            continue
        if mlng == 0 and mlat == 0:
            continue
        cat = t.get("category_id", "unknown")
        color = CATEGORY_COLORS.get(cat, "#999999")
        label = CATEGORY_LABELS.get(cat, cat)
        name = _js_str(t.get("name", "?"))
        dname = _js_str(t.get("district_name", ""))
        addr = _js_str(t.get("address", ""))
        src = _js_str(t.get("source", ""))
        kw = _js_str(t.get("keyword", ""))
        src_crs = _js_str(t.get("source_crs", "GCJ-02"))
        method = _js_str(t.get("coord_transform_method", "none"))
        parts.append(f"""
  L.circleMarker([{mlat}, {mlng}], {{
    radius: 6, fillColor: '{color}', color: '#333', weight: 0.5, fillOpacity: 0.85,
  }}).addTo(map).bindPopup(
    '<b>{name}</b><br>街区: {dname}<br>类目: {label}<br>地址: {addr}<br>' +
    'source: {src}<br>keyword: {kw}<br>source_crs: {src_crs}<br>coord_transform: {method}'
  );
  bounds.push([{mlat}, {mlng}]);""")

    parts.append("""
  var legend = L.control({position: 'bottomleft'});
  legend.onAdd = function(map) {
    var div = L.DomUtil.create('div', 'info-box legend');
    div.innerHTML = '<h3>图例</h3>';""")
    for cat, color in CATEGORY_COLORS.items():
        clabel = CATEGORY_LABELS.get(cat, cat)
        parts.append(f"""    div.innerHTML += '<i style="background:{color}"></i> {clabel}<br>';""")
    parts.append("""    return div;
  };
  legend.addTo(map);""")

    parts.append(f"""
  var info = L.control({{position: 'topright'}});
  info.onAdd = function(map) {{
    var div = L.DomUtil.create('div', 'info-box');
    div.innerHTML = '<h3>数据说明</h3>' +
      '快照日期: <b>{snapshot_date}</b><br>' +
      '目标周末: <b>{weekend_date}</b><br>' +
      'POI 数量: <b>{len(transformed)}</b><br>' +
      '街区数量: <b>{len(districts)}</b><br>' +
      '地图 provider: <b>leaflet_osm</b><br>' +
      '坐标模式: <b>{coord_mode}</b><br>' +
      'source_crs: <b>GCJ-02</b><br>' +
      'map_crs: <b>{"WGS84" if coord_mode == "approx_wgs84" else "GCJ-02"}</b><br>';
      {"div.innerHTML += '<hr style=\\\"margin:6px 0\\\">地图使用 Leaflet + OpenStreetMap 生成。高德 POI 原始坐标为 GCJ-02，本地图使用近似转换后的 WGS84 坐标进行可视化，仅用于数据 QA 和空间预览，不用于导航或精确测绘。<br>';" if coord_mode == "approx_wgs84" else "div.innerHTML += '<hr style=\\\"margin:6px 0\\\">注意：该模式将 GCJ-02 直接叠加到 OSM 底图，可能存在偏移。<br>';"}
    return div;
  }};
  info.addTo(map);""")

    parts.append("""
  if (bounds.length > 0) {
    map.fitBounds(bounds, {padding: [40, 40]});
  }
</script>
</body>
</html>""")

    os.makedirs(os.path.dirname(output_path), exist_ok=True)
    html = "\n".join(parts)
    with open(output_path, "w", encoding="utf-8") as f:
        f.write(html)
    return output_path


# ══════════════════════════════════════════════════════════
#  Unified entry
# ══════════════════════════════════════════════════════════


def generate_map(
    poi_snapshot_path: str,
    districts_path: str,
    output_path: str,
    snapshot_date: str,
    weekend_date: str,
    provider: str = "amap_js",
    coord_mode: str = "approx_wgs84",
    **kwargs,
) -> str:
    """Unified map generation entry point.

    Args:
        provider: 'amap_js' (default) or 'leaflet_osm'
        coord_mode: 'approx_wgs84' (default) or 'raw_gcj02'; only used for leaflet_osm
        **kwargs: forwarded to provider-specific functions
            (map_style, map_features, min_zoom, max_zoom for amap_js)
    """
    if provider == "amap_js":
        return generate_amap_js_map(
            poi_snapshot_path, districts_path, output_path,
            snapshot_date, weekend_date,
            **kwargs,
        )
    elif provider == "leaflet_osm":
        return generate_leaflet_osm_map(
            poi_snapshot_path, districts_path, output_path,
            snapshot_date, weekend_date, coord_mode,
        )
    else:
        raise ValueError(f"Unknown map provider: {provider}")
