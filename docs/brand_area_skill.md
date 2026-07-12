# 街区品牌门店地图 — 经验 Skill

对应脚本示例：`reports/maps/huaihai_brands_map.py`

## 整体流程

```
定义品牌列表 + SVG Logo
       ↓
定位地铁站坐标 (AMap Text Search)
       ↓
围绕站点扫描品牌门店 (AMap Around Search)
       ↓
去重、整理结果
       ↓
生成 AMap JS API HTML 地图
```

---

## 1. Brand Logo 获取

**数据源**: [Simple Icons](https://simpleicons.org)

**CDN 格式**: `https://cdn.simpleicons.org/{brand}/{color_hex}`

```bash
curl -s -o assets/brand_logo/nike.svg "https://cdn.simpleicons.org/nike/FFFFFF"
```

**本地路径**: `assets/brand_logo/{brand}.svg`（白色 fill，配合品牌色背景）

**脚本中读取**:
```python
SVG_DIR = PROJECT_ROOT / "assets" / "brand_logo"

def read_brand_logo_svg(brand_id: str) -> str:
    path = SVG_DIR / f"{brand_id}.svg"
    return path.read_text(encoding="utf-8")
```

SVG 直接通过 `innerHTML` 嵌入 Marker，零外部请求。

---

## 2. 高德 POI 搜索

### Text Search（定位站点）

```
GET https://restapi.amap.com/v3/place/text
  ?key={key}
  &keywords=淮海中路站(13号线)
  &city=上海
  &offset=5
```

返回 `pois[0].location` → `"lng,lat"`。

### Around Search（扫描门店）

```
GET https://restapi.amap.com/v3/place/around
  ?key={key}
  &keywords=耐克
  &location=121.46436,31.22006
  &radius=350
  &offset=20
```

注意：

- 每个品牌用中英文两个关键词分别搜索，结果合并去重
- 跨关键词去重通过 `poi_id` 或坐标 `{lng:.5f}_{lat:.5f}`
- 跨站点去重通过全局 `global_seen` set
- 每次请求后 `time.sleep(0.3)` 避免 QPS 超限
- 需要 `_sign_params()` 当有 `AMAP_API_SECRET`

---

## 3. AMap JS API 地图配置

### 底图样式（视觉降噪）

```javascript
var map = new AMap.Map('map', {
  mapStyle: 'amap://styles/grey',   // 灰底低饱和
  features: ['bg', 'road'],          // 只保留背景+道路
  viewMode: '2D',
  pitch: 0, rotation: 0,
  rotateEnable: false, pitchEnable: false,
  doubleClickZoom: false,
});
```

### AMap.Circle（扫描圈）

```javascript
var circle = new AMap.Circle({
  center: new AMap.LngLat(lng, lat),  // 必须用 LngLat，不能用数组
  radius: 350,
  strokeColor: '#174A7C', strokeWeight: 3,
  strokeOpacity: 1, strokeStyle: 'dashed', strokeDasharray: [8, 8],
  fillColor: '#DDEFF8', fillOpacity: 0.3,
  zIndex: 10,
});
map.add(circle);  // 必须用 map.add()，不能传 map: map
```

关键踩坑：

| 项目 | ❌ 错误 | ✅ 正确 |
|---|---|---|
| 添加方式 | `new AMap.Circle({map: map, ...})` | `map.add(circle)` |
| center | `[121.46, 31.22]` | `new AMap.LngLat(121.46, 31.22)` |
| 虚线 | `strokeStyle: 'dashed'`（支持） | 需同时设置 `strokeDasharray` |

### Marker 品牌 Logo

```javascript
var wrap = document.createElement('div');
wrap.className = 'logo-marker';
wrap.style.background = brandColors[m.brand_id];
wrap.innerHTML = m.logo_svg;  // 内联 SVG
// ...
var marker = new AMap.Marker({
  map: map,
  position: [m.lon, m.lat],
  content: wrap,
  zIndex: 30,
});
```

### 信息窗体

```javascript
var infoWin = new AMap.InfoWindow({offset: new AMap.Pixel(0, -36)});
marker.on('click', function(e) {
  var d = e.target.getExtData();
  infoWin.setContent('<div>...</div>');
  infoWin.open(map, e.target.getPosition());
});
```

---

## 4. 多站点覆盖

支持多个地铁站作为扫描圆心：

```python
STATIONS = [
    "淮海中路站(13号线)",
    "陕西南路站",
]
```

每个站独立画 Circle + 站标 Marker。结果全局去重，图例只显示有门店的品牌。

---

## 5. 图例动态过滤

图例只列出有门店的品牌。通过 `active_ids` 过滤：

```python
active_ids = {m["brand_id"] for m in markers}
# 在模板中过滤 BRANDS
"".join(... for b in BRANDS if b["id"] in active_ids)
```

---

## 6. Zoom-Responsive Marker 缩放

Marker 尺寸随地图缩放级别自适应，避免小比例尺下点过于密集：

```javascript
function resizeMarkers() {
  var z = map.getZoom();
  var size, svgSize, borderW;
  if (z <= 8)      { size = 10; svgSize = 7;  borderW = 1; }
  else if (z <= 10) { size = 14; svgSize = 9;  borderW = 1; }
  else if (z <= 12) { size = 18; svgSize = 12; borderW = 1.5; }
  else if (z <= 14) { size = 24; svgSize = 16; borderW = 2; }
  else              { size = 30; svgSize = 20; borderW = 2; }
  markerWraps.forEach(function(item) {
    item.wrap.style.width = size + 'px';
    item.wrap.style.height = size + 'px';
    item.wrap.style.borderWidth = borderW + 'px';
  });
}
map.on('zoomend', resizeMarkers);
resizeMarkers();
```

CSS 中去掉固定宽高，由 JS 控制：

```css
.logo-marker {
  border-radius: 50%; overflow: hidden;
  border: 1px solid rgba(255,255,255,0.6);
  box-shadow: 0 1px 4px rgba(0,0,0,0.12);
  display: flex; align-items: center; justify-content: center;
  cursor: pointer; opacity: 0.75;
}
.logo-marker:hover { opacity: 1; }
```

---

## 7. 数据快照（先扫再画）

所有地图脚本必须遵循 **两阶段分离** 原则：

### 阶段一：扫描（API 调用）

```python
# 扫描 → 保存快照
results = scan_brands(...)
save_snapshot(results)   # → data/brand_stores/snapshots/{name}/poi_data.json
```

### 阶段二：可视化（零 API）

```bash
# 从快照加载 → 生成 HTML
python3 reports/maps/nike_vs_adidas.py --cities 上海 苏州 --from-snapshot
```

快照目录：
```
data/brand_stores/snapshots/
├── huaihai_350m/poi_data.json
└── 上海_苏州_nike_adidas/poi_data.json
```

---

## 8. 门店去重规则

### 高置信度身份覆盖

当地址/楼层冲突时，满足以下 **全部** 条件可自动合并：

1. `brand_id` 相同
2. 标准化门店名称相同
3. 有效联系电话相同（非 400 热线/空值）
4. 坐标 ≤ 30 米
5. 无店型冲突（Kids/Originals/Outlet/Mega/旗舰店等）

### 信号优先级

```
独立电话一致 > 名称一致 > 铺位号一致 > 商场一致 > 地址文本 > 坐标
```

### 噪音过滤

搜索关键词（如"耐克"）可能匹配到非目标实体，需在扫描阶段和去重阶段双重过滤：

```python
NOISE_PREFIX = ['施耐克', '耐克森', '博耐克', '狄耐克', '金耐克']

def _is_nike_noise(r: dict) -> bool:
    if r['brand_id'] != 'nike':
        return False
    name = r.get('name', '')
    for p in NOISE_PREFIX:
        if p in name and 'Nike' not in name and 'NIKE' not in name:
            return True
    return False
```

常见误匹配场景：其他品牌名包含"耐克"字样（施耐克=施耐德、耐克森=Nexans 电缆、博耐克=木业板材、狄耐克=暖通设备、金耐克=辅料）。

### 身份与地址解耦

```json
{
  "entity_match": "confirmed_same_store",
  "entity_confidence": "high",
  "address_status": "conflicting",
  "address_confidence": "low",
  "needs_address_review": true
}
```

---

## 9. SKILL 流程集成

完整流程遵循 `.opencode/skills/store-opening-watch/SKILL.md`：

```
快照 → 输入检查 → 字段标准化 → 去重 → Registry → Baseline → 候选输出
```

产出目录：
```
data/brand_stores/
├── snapshots/     ← 原始 POI 快照
├── registry/      ← 门店实体表
├── compares/      ← Baseline 元数据 + 报告
└── events/        ← 待复核候选
```

---

## 10. 交互筛选器

城市/品牌筛选必须遍历 `markerWraps`（AMap.Marker 实例数组），而非数据数组：

```javascript
markerWraps.forEach(function(item) {
  var d = item.marker.getExtData();
  var visible = activeCities[d.city] && activeBrands[d.brand_id];
  item.marker.setMap(visible ? map : null);
});
```

---

## 11. 相关文件

| 文件 | 用途 |
|---|---|
| `reports/maps/{area}_brands_map.py` | 扫描+生成脚本 |
| `assets/brand_logo/*.svg` | 品牌 SVG logo |
| `reports/maps/{area}_brands_map.html` | 生成的地图 |
| `config/brand_poi_compare.yaml` | 品牌 POI 扫描配置 |
| `.env` | AMAP_API_KEY / AMAP_JS_API_KEY / AMAP_SECURITY_JS_CODE |

## 拓展到新街区

1. 复制 `reports/maps/huaihai_brands_map.py` 为新脚本
2. 修改 `STATIONS` 列表为目标地铁站
3. 调整 `--radius` 覆盖范围
4. 如需新增品牌，下载 SVG 到 `assets/brand_logo/` 并加到 `BRANDS` 列表
5. 运行 `python3 reports/maps/{new_area}_brands_map.py --radius 350`
