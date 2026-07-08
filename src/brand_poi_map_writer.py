"""
Brand POI compare map writer.

Generates an AMap JS HTML map and a Markdown report for brand POI comparison.
"""

import csv
import json
import os
from collections import Counter, defaultdict
from datetime import date

import yaml


PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _load_config() -> dict:
    path = os.path.join(PROJECT_ROOT, "config", "brand_poi_compare.yaml")
    with open(path, encoding="utf-8") as f:
        return yaml.safe_load(f)


def _load_poi_csv(path: str) -> list[dict]:
    rows = []
    with open(path, encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for r in reader:
            rows.append(r)
    return rows


def _brand_color_map(config: dict) -> dict:
    return {b["brand_id"]: b["marker_color"] for b in config["brands"]}


def _brand_name_map(config: dict) -> dict:
    return {b["brand_id"]: b["display_name"] for b in config["brands"]}


def _js_str(s: str) -> str:
    return s.replace("\\", "\\\\").replace("'", "\\'").replace("\n", " ")


# ── HTML map ──


def generate_brand_poi_map(
    poi_rows: list[dict],
    output_path: str,
    crawl_date: date,
    city: str,
    api_key_available: bool,
    has_js_key: bool,
    has_sec_code: bool,
    js_key: str = "",
    sec_code: str = "",
):
    config = _load_config()
    color_map = _brand_color_map(config)
    name_map = _brand_name_map(config)

    brands = config["brands"]
    html_parts = []
    center_lng, center_lat = 121.4737, 31.2304

    # ── Group by brand ──
    by_brand = defaultdict(list)
    for r in poi_rows:
        by_brand[r.get("brand_id", "unknown")].append(r)

    poi_json = json.dumps(poi_rows, ensure_ascii=False)

    html_parts.append(f"""<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>{city}品牌门店POI对比观察</title>
<style>
  body {{ margin:0; padding:0; font-family:-apple-system,'Helvetica Neue',sans-serif; }}
  #map {{ width:100%; height:75vh; }}
  .info-box {{
    background:#fff; padding:10px 14px; border-radius:8px;
    box-shadow:0 2px 8px rgba(0,0,0,0.15); font-size:13px; line-height:1.6;
  }}
  .info-box h3 {{ margin:0 0 6px 0; font-size:14px; }}
  .warning {{ background:#FFF3CD; border-left:4px solid #D79A36; padding:8px 14px; font-size:13px; }}
  .filter-bar {{ padding:6px 12px; background:#f8f9fa; border-bottom:1px solid #ddd; font-size:13px; }}
  .filter-bar label {{ margin-right:12px; cursor:pointer; }}
  .filter-bar input {{ margin-right:3px; }}
  .poi-dot {{ width:10px;height:10px;border-radius:999px;display:inline-block;margin-right:4px;vertical-align:middle; }}
  @media (max-width:600px) {{ #map {{ height:60vh; }} }}
</style>
</head>
<body>""")

    if not api_key_available:
        html_parts.append("""<div class="warning">⚠ 缺少 AMAP_API_KEY，未执行真实 POI 扫描。当前展示为空数据骨架。</div>""")
    elif not has_js_key:
        html_parts.append("""<div class="warning">⚠ 缺少 AMAP_JS_API_KEY，地图可能无法加载。请在 .env 中配置 AMAP_JS_API_KEY。</div>""")
    if has_js_key and not has_sec_code:
        html_parts.append("""<div class="warning">⚠ 缺少 AMAP_SECURITY_JS_CODE。高德 JS API 2.0 在部分 key 配置下需要安全密钥。</div>""")

    html_parts.append('<div id="map"></div>')

    if has_sec_code:
        html_parts.append(f"""<script>window._AMapSecurityConfig = {{securityJsCode: "{sec_code}"}};</script>""")
    if has_js_key:
        html_parts.append(f"""<script src="https://webapi.amap.com/maps?v=2.0&key={js_key}"></script>""")
    else:
        html_parts.append("""<script src="https://webapi.amap.com/maps?v=2.0&key=NO_KEY"></script>""")

    html_parts.append(f"""<script>
var map = new AMap.Map('map', {{
  center: [{center_lng}, {center_lat}],
  zoom: 10,
  viewMode: '2D',
}});
var allMarkers = [];
var filterState = {{}};
var poiData = {poi_json};

/* ---------- Brand colors ---------- */
var brandColors = {json.dumps(color_map, ensure_ascii=False)};
var brandNames = {json.dumps(name_map, ensure_ascii=False)};

/* ---------- safeClassName ---------- */
function safeClassName(v) {{
  return String(v || 'default').toLowerCase().replace(/[^a-z0-9_-]/g, '_');
}}

/* ---------- Marker factory ---------- */
function createBrandMarker(poi) {{
  var color = brandColors[poi.brand_id] || '#6B7280';
  var dot = document.createElement('span');
  dot.className = 'poi-dot';
  dot.style.background = color;
  var wrap = document.createElement('div');
  wrap.className = 'poi-marker-wrap';
  wrap.appendChild(dot);

  var marker = new AMap.Marker({{
    map: map,
    position: [parseFloat(poi.lng_gcj02), parseFloat(poi.lat_gcj02)],
    content: wrap,
    anchor: 'center',
    zIndex: 20,
    extData: poi,
    cursor: 'pointer',
  }});
  return marker;
}}

/* ---------- InfoWindow ---------- */
var infoWin = new AMap.InfoWindow({{offset: new AMap.Pixel(0, -30)}});
function showInfo(e) {{
  var d = e.target.getExtData();
  var kindLabel = {{ 'experience_store':'体验中心','delivery_center':'交付中心','service_center':'服务中心','mall_store':'商场店','user_center':'用户中心','energy':'补能','office':'办公','other':'其他' }};
  var locLabel = {{ 'mall':'商场','road_address_store':'道路地址型门店','auto_park':'汽车园区','industrial_or_service_site':'工业/服务场地','office_or_entity':'办公/企业实体','unknown':'未知' }};
  infoWin.setContent(
    '<div style="font-size:13px;line-height:1.6;max-width:260px;">' +
    '<b style="color:' + brandColors[d.brand_id] + '">' + brandNames[d.brand_id] + '</b><br>' +
    '<b>' + d.name + '</b><br>' +
    '功能类型: ' + (kindLabel[d.poi_kind] || d.poi_kind) + '<br>' +
    '空间区位: ' + (locLabel[d.store_location_type] || d.store_location_type || '—') + '<br>' +
    '区县: ' + (d.district || '') + '<br>' +
    '地址: ' + (d.address || '') + '<br>' +
    'source_query: ' + (d.source_query || '') + '<br>' +
    '坐标: GCJ-02'
  );
  infoWin.open(map, e.target.getPosition());
}}

/* ---------- Render markers ---------- */
poiData.forEach(function(p) {{
  var m = createBrandMarker(p);
  m.on('click', showInfo);
  m.setExtData(p);
  if (!filterState[p.brand_id]) filterState[p.brand_id] = true;
  if (!filterState['kind_' + p.poi_kind]) filterState['kind_' + p.poi_kind] = true;
  allMarkers.push({{ marker: m, brand_id: p.brand_id, poi_kind: p.poi_kind, store_location_type: p.store_location_type || '' }});
}});

/* ---------- Fit view ---------- */
if (allMarkers.length > 0) {{
  map.setFitView(allMarkers.map(function(m) {{ return m.marker; }}), false, [40,40,40,40]);
}}
</script>
""")

    # ── Legend + filters below map ──
    html_parts.append("""
<div style="max-width:100%;margin:8px 16px;">
<div style="display:flex;flex-wrap:wrap;gap:12px;">
  <div class="info-box" style="flex:1;min-width:200px;">
    <h3>品牌</h3>""")
    for b in brands:
        bid = b["brand_id"]
        count = len(by_brand.get(bid, []))
        html_parts.append(
            f'    <label><input type="checkbox" class="brand-filter" data-brand="{bid}" checked>'
            f' <span class="poi-dot" style="background:{b["marker_color"]}"></span>'
            f' {b["display_name"]} (<span class="fc" data-ft="brand" data-fv="{bid}">{count}</span>)</label><br>'
        )

    kind_labels = {
        "experience_store": "体验中心",
        "delivery_center": "交付中心",
        "service_center": "服务中心",
        "user_center": "用户中心",
        "mall_store": "商场店",
        "other": "其他",
    }
    html_parts.append("""  </div>
  <div class="info-box" style="flex:1;min-width:180px;">
    <h3>功能类型</h3>""")
    for kid, klabel in kind_labels.items():
        count = sum(1 for r in poi_rows if r.get("poi_kind") == kid)
        html_parts.append(
            f'    <label><input type="checkbox" class="kind-filter" data-kind="{kid}" checked>'
            f' {klabel} (<span class="fc" data-ft="kind" data-fv="{kid}">{count}</span>)</label><br>'
        )
    html_parts.append("""  </div>
  <div class="info-box" style="flex:1;min-width:180px;">
    <h3>空间区位</h3>""")
    loc_labels = {
        "mall": "商场", "road_address_store": "道路地址型门店",
        "auto_park": "汽车园区", "industrial_or_service_site": "工业/服务场地",
        "office_or_entity": "办公/企业实体", "unknown": "未知",
    }
    for lid, ll in loc_labels.items():
        count = sum(1 for r in poi_rows if r.get("store_location_type") == lid)
        html_parts.append(
            f'    <label><input type="checkbox" class="loc-filter" data-loc="{lid}" checked>'
            f' {ll} (<span class="fc" data-ft="loc" data-fv="{lid}">{count}</span>)</label><br>'
        )
    html_parts.append("""  </div>
</div>
<div class="info-box" style="margin-top:8px;">
  <h3>数据说明</h3>
  数据来源：高德地图 POI API<br>
  坐标口径：GCJ-02（不转换）<br>
  扫描范围：上海 bbox 网格扫描<br>
  生成日期：""" + crawl_date.isoformat() + """<br>
  <div style="font-size:12px;color:#6B7C8F;margin-top:4px;">
    该结果用于品牌门店空间分布观察，不能完全等同于品牌官方门店清单。
  </div>
</div>
</div>

<script>
/* ---------- Filter logic + linked counts ---------- */
function applyFilters() {
  var brandChecks = {};
  document.querySelectorAll('.brand-filter').forEach(function(cb) {
    brandChecks[cb.dataset.brand] = cb.checked;
  });
  var kindChecks = {};
  document.querySelectorAll('.kind-filter').forEach(function(cb) {
    kindChecks[cb.dataset.kind] = cb.checked;
  });
  var locChecks = {};
  document.querySelectorAll('.loc-filter').forEach(function(cb) {
    locChecks[cb.dataset.loc] = cb.checked;
  });
  var counts = { brand: {}, kind: {}, loc: {} };
  allMarkers.forEach(function(item) {
    var visible = brandChecks[item.brand_id] !== false
              && kindChecks[item.poi_kind] !== false
              && locChecks[item.store_location_type] !== false;
    if (visible) {
      item.marker.setMap(map);
      counts.brand[item.brand_id] = (counts.brand[item.brand_id] || 0) + 1;
      counts.kind[item.poi_kind] = (counts.kind[item.poi_kind] || 0) + 1;
      counts.loc[item.store_location_type] = (counts.loc[item.store_location_type] || 0) + 1;
    } else {
      item.marker.setMap(null);
    }
  });
  document.querySelectorAll('.fc').forEach(function(el) {
    var ft = el.dataset.ft, fv = el.dataset.fv;
    el.textContent = (counts[ft] && counts[ft][fv]) || 0;
  });
}
document.querySelectorAll('.brand-filter, .kind-filter, .loc-filter').forEach(function(cb) {
  cb.addEventListener('change', applyFilters);
});
</script>
</body>
</html>""")

    os.makedirs(os.path.dirname(output_path), exist_ok=True)
    with open(output_path, "w", encoding="utf-8") as f:
        f.write("".join(html_parts))
    return output_path


# ── Markdown report ──


def generate_brand_poi_report(
    poi_rows: list[dict],
    output_path: str,
    crawl_date: date,
    city: str,
    csv_path: str,
    json_path: str,
    map_path: str,
):
    config = _load_config()
    by_brand = defaultdict(list)
    for r in poi_rows:
        by_brand[r.get("brand_id", "unknown")].append(r)

    kind_order = ["experience_store", "delivery_center", "service_center", "user_center", "mall_store", "other"]
    kind_labels = {
        "experience_store": "体验中心", "delivery_center": "交付中心",
        "service_center": "服务中心", "user_center": "用户中心",
        "mall_store": "商场店", "other": "其他",
    }

    lines = []
    lines.append(f"# {city}品牌门店 POI 对比观察\n")
    lines.append(f"生成日期：{crawl_date.isoformat()}  ")
    lines.append(f"城市：{city}  ")
    brands_list = " / ".join(b["display_name"] for b in config["brands"])
    lines.append(f"品牌：{brands_list}  ")
    lines.append("数据来源：高德地图 POI API  \n")

    lines.append("## 1. 数据概览\n")
    header = "| 品牌 | POI 数 | " + " | ".join(kind_labels[k] for k in kind_order) + " |"
    sep = "|---|---:" + ":|" * len(kind_order)
    lines.append(header)
    lines.append(sep)
    for b in config["brands"]:
        rows = by_brand.get(b["brand_id"], [])
        counts = {k: sum(1 for r in rows if r.get("poi_kind") == k) for k in kind_order}
        vals = " | ".join(str(counts[k]) for k in kind_order)
        lines.append(f"| {b['display_name']} | {len(rows)} | {vals} |")
    lines.append("")

    # ── District breakdown ──
    lines.append("## 2. 区县分布\n")
    lines.append("| 品牌 | 区县 | POI 数 |")
    lines.append("|---|---:|---:|")
    for b in config["brands"]:
        rows = by_brand.get(b["brand_id"], [])
        dist_counter = Counter(r.get("district", "未知") for r in rows)
        for dist, cnt in dist_counter.most_common():
            lines.append(f"| {b['display_name']} | {dist} | {cnt} |")
    lines.append("")

    # ── Location type breakdown ──
    loc_order = ["mall", "road_address_store", "auto_park", "industrial_or_service_site", "office_or_entity", "unknown"]
    loc_labels = {
        "mall": "商场", "road_address_store": "道路地址型门店", "auto_park": "汽车园区",
        "industrial_or_service_site": "工业/服务场地", "office_or_entity": "办公/企业实体",
        "unknown": "未知",
    }
    has_loc_data = any(r.get("store_location_type") for brand_rows in by_brand.values() for r in brand_rows)
    if has_loc_data:
        lines.append("## 3. 空间区位类型\n")
        loc_header = "| 品牌 | " + " | ".join(loc_labels[t] for t in loc_order) + " |"
        loc_sep = "|" + "---|" * (len(loc_order) + 1)
        lines.append(loc_header)
        lines.append(loc_sep)
        for b in config["brands"]:
            rows = by_brand.get(b["brand_id"], [])
            counts = {t: sum(1 for r in rows if r.get("store_location_type") == t) for t in loc_order}
            vals = " | ".join(str(counts[t]) for t in loc_order)
            lines.append(f"| {b['display_name']} | {vals} |")
        lines.append("")

    lines.append(f"## {'4' if has_loc_data else '3'}. 地图文件\n")
    lines.append(f"- {map_path}\n")

    n = 5 if has_loc_data else 4
    lines.append(f"## {n}. 数据文件\n")
    lines.append(f"- CSV: {csv_path}")
    lines.append(f"- JSON: {json_path}\n")

    n = 6 if has_loc_data else 5
    lines.append(f"## {n}. 注意事项\n")
    lines.append("- 本结果来自高德 POI API，不等同于品牌官方门店清单。")
    lines.append("- 鸿蒙智行 POI 可能包含 AITO / 问界 / 用户中心等多种命名体系。")
    lines.append("- 蔚来补能类 POI 默认排除，避免换电站数量干扰门店对比。")

    os.makedirs(os.path.dirname(output_path), exist_ok=True)
    with open(output_path, "w", encoding="utf-8") as f:
        f.write("\n".join(lines))
    return output_path
