# Brand POI — 品牌门店 POI 扫描与分析 Skill

## 概述

Brand POI 模块用于对汽车品牌门店进行高德 POI 扫描、分类、分析和对比观察。

覆盖品牌：智己、蔚来、鸿蒙智行（可扩展）。  
城市：上海（可扩展，通过 `--city` 参数）。

---

## 1. Scan / Read 边界

整个模块严格分为两层：

### 采集层（Scan Layer）

| 命令 | 行为 | 调用 API |
|------|------|----------|
| `brand_poi.py scan` | 调用高德 API 扫描品牌 POI，写入 snapshot | **是** |
| `brand_poi.py run` | plan + scan + map + analyze | **是**（scan 阶段） |
| `brand_poi.py plan` | 仅打印请求预算，不发起请求 | 否 |

### 使用层（Read Layer）

| 命令 | 行为 | 调用 API |
|------|------|----------|
| `brand_poi.py analyze` | 读取 snapshot → enriched CSV + summary JSON + 报告 | **否** |
| `brand_poi.py map` | 读取 snapshot → HTML 地图 + MD 报告 | **否** |
| `brand_poi.py slice` | 读取 snapshot → 过滤 CSV | **否** |
| `brand_poi.py compare` | 读取两个 snapshot → delta 报告 | **否** |

**规则**：使用层命令如果检测到 API 调用，直接 fail。这一边界通过 `test_read_commands_call_no_api` 测试保障。

---

## 2. Snapshot 目录结构

```
data/brand_poi/
├── snapshots/
│   └── {date}_{city}/
│       ├── manifest.json      # 元信息：版本、日期、城市、品牌、统计
│       ├── brand_poi.csv      # 原始扫描数据（核心产物）
│       ├── brand_poi.json     # 原始数据 JSON 格式
│       ├── enriched.csv       # （analyze 产出）增强字段
│       ├── summary.json       # （analyze 产出）聚合统计
│       └── analysis.md        # （analyze 产出）分析报告
├── compares/
│   └── {base_id}__vs__{target_id}/
│       ├── compare.json       # delta 数据
│       └── compare.md         # delta 报告
```

`snapshot_id` 格式固定为 `{date}_{city}`，例如 `2026-07-08_上海`。  
跨城市同日期不会冲突。

### manifest.json 结构

```json
{
  "version": 1,
  "date": "2026-07-08",
  "city": "上海",
  "brands": ["智己", "蔚来", "鸿蒙智行"],
  "created_at": "2026-07-08T16:39:23",
  "stats": {
    "total_poi": 208,
    "brand_counts": { "智己": 48, "蔚来": 86, "鸿蒙智行": 74 }
  }
}
```

---

## 3. CLI 命令

### 统一入口：`src/brand_poi.py`

```bash
# 计划
python3 src/brand_poi.py plan --city 上海 --date 2026-07-08

# 扫描（唯一调用 API 的入口之一）
python3 src/brand_poi.py scan --city 上海 --date 2026-07-08

# 全流程（plan + scan + map + analyze）
python3 src/brand_poi.py run --city 上海 --date 2026-07-08

# 分析 snapshot（不调 API）
python3 src/brand_poi.py analyze --dataset 2026-07-08_上海

# 生成地图 + 报告（不调 API）
python3 src/brand_poi.py map --dataset 2026-07-08_上海

# 过滤导出（不调 API）
python3 src/brand_poi.py slice --dataset 2026-07-08_上海 --by brand:蔚来
python3 src/brand_poi.py slice --dataset 2026-07-08_上海 --by kind:user_center
python3 src/brand_poi.py slice --dataset 2026-07-08_上海 --by district:浦东新区

# 对比两个 snapshot（不调 API）
python3 src/brand_poi.py compare \\
  --base 2026-07-01_上海 --target 2026-07-08_上海
```

### 旧入口兼容：`src/brand_poi_compare.py`

```bash
python3 src/brand_poi_compare.py --date 2026-07-08
```

内部转发到 `brand_poi.py run`。

### scan 命令额外参数

| 参数 | 作用 |
|------|------|
| `--clear-cache` | 清空 API 缓存后再扫描 |
| `--debug-cache` | 打印缓存键、缓存路径 |
| `--debug-api` | 打印详细 API 请求日志 |
| `--scan-mode` | 扫描模式：`text_city_first`（默认）/ `around_fallback` / `grid_around` |

---

## 4. 产物说明

### 4.1 brand_poi.csv（扫描，每个 POI 一行）

| 字段 | 说明 |
|------|------|
| `brand_id` / `brand_name` | 品牌标识 / 显示名称 |
| `poi_id` | 高德 POI ID（去重依据） |
| `name` / `address` | POI 名称 / 地址 |
| `district` | 区县 |
| `lng_gcj02` / `lat_gcj02` | GCJ-02 坐标 |
| `poi_kind` | **功能类型**（见下方分类） |
| `store_location_type` | **空间区位类型**（见下方分类） |
| `source_query` | 触发本次匹配的搜索词 |
| `type` / `typecode` | 高德原始类别 |
| `crawl_date` | 扫描日期 |
| `source` | 数据来源（`amap_place_text`） |

### 4.2 poi_kind（功能类型）

```
energy > service_center > delivery_center > user_center > mall_store > experience_store > other
```

| 分类 | 含义 | 识别线索 |
|------|------|----------|
| `energy` | 补能站 | 充电 / 换电 / 超充 / 能源 / power |
| `service_center` | 服务中心 | 服务中心 / 售后 / 维修 / 施工中心 / 精品施工 |
| `delivery_center` | 交付中心 | 交付 |
| `user_center` | 用户中心 | 用户中心 / 授权用户中心 / 汽车中心 / 4S店 |
| `mall_store` | 商场店 | 品牌名 + 商场/广场/万象城/百联等 |
| `experience_store` | 体验中心 | 体验中心 / 体验店 / 蔚来空间 / 蔚来中心 |
| `other` | 其他 | 总部 / 办公 / 未匹配 |

### 4.3 store_location_type（空间区位类型）

```
office_or_entity > auto_park > industrial_or_service_site > mall > road_address_store > unknown
```

| 分类 | 含义 |
|------|------|
| `mall` | 商场/购物中心/商业综合体内 |
| `road_address_store` | 道路地址型门店（未识别为商场/园区/场地的普通地址） |
| `auto_park` | 汽车园区/汽车城 |
| `industrial_or_service_site` | 工业/服务场地（维修车间/仓库/厂房） |
| `office_or_entity` | 办公/企业实体（含"公司"/"有限公司"名称） |
| `unknown` | 无法判断 |

### 4.4 enriched.csv（analyze 增强字段）

| 字段 | 说明 |
|------|------|
| `is_frontend_store` | 是否为前端触点（experience_store / user_center / mall_store） |
| `is_after_sales` | 是否为售后服务（service_center） |
| `is_delivery` | 是否为交付中心（delivery_center） |
| `is_core_touchpoint` | 是否为核心门店触点 |
| `needs_review` | 是否需要人工复核 |
| `review_reason` | 复核原因（`suspected_non_auto_store` / `suspected_energy_site` / `poi_kind_other` / `possibly_closed` / `possible_dealer_entity_or_office` / `parking_or_entrance`，可组合） |
| `brand_poi_count` | 该品牌总 POI 数 |
| `brand_district_poi_count` | 该品牌在该区县 POI 数 |
| `district_total_poi_count` | 该区县三品牌总 POI 数 |
| `brand_district_share` | 品牌在该区县的 POI 占比 |
| `district_brand_rank` | 品牌在该区县的排名 |

### 4.5 summary.json（analyze 聚合）

```json
{
  "total_poi": 208,
  "brand_counts": { "智己": 48, "蔚来": 86, "鸿蒙智行": 74 },
  "poi_kind_counts": { "experience_store": 40, ... },
  "brand_kind_matrix": { "智己": { "experience_store": 28, ... }, ... },
  "brand_location_matrix": { "智己": { "mall": 23, "road_address_store": 11, ... }, ... },
  "district_summary": [ { "district": "浦东新区", "total_poi": 42, "智己": 10, "蔚来": 15, "鸿蒙智行": 17 }, ... ],
  "review_summary": { "needs_review_count": 8, "reasons": { "possible_dealer_entity_or_office": 6, ... } },
  "nearest_neighbor": { "enabled": true, "pairs": [ { "pair": "智己 vs 蔚来", "median_nearest_km": 1.212, ... } ] }
}
```

### 4.6 analysis.md（analyze 报告）

包含 10 个章节：数据说明 → 总体概览 → 品牌数量 → 类型结构 → 空间区位 → 区县覆盖 → 空间重叠 → 需复核 POI → 渠道策略观察 → 下一步建议。

### 4.7 HTML 地图

交互式 AMap JS 地图，支持：
- 按品牌/功能类型/空间区位三面板联动筛选
- 点击标记显示详情
- 筛选计数实时更新

---

## 5. API 调用规则

| 场景 | 是否调用高德 API | 说明 |
|------|-----------------|------|
| `brand_poi.py scan` | ✅ 是 | 调用 `place/text` 和 `place/around` 接口 |
| `brand_poi.py run` | ✅ 是 | scan 阶段调用，map + analyze 不调 |
| `brand_poi.py analyze` | ❌ 否 | 只读已有 snapshot |
| `brand_poi.py map` | ❌ 否 | 只读已有 snapshot |
| `brand_poi.py slice` | ❌ 否 | 只读已有 snapshot；纯文件过滤 |
| `brand_poi.py compare` | ❌ 否 | 读取两个 snapshot 做 delta |
| `brand_poi_compare.py run` | ✅ 是 | 转发到 `brand_poi.py run` |

API 调用限制：
- `max_total_requests`（默认 500）保护预算，超限拒绝执行
- `sleep_seconds: 1.0` 控制 QPS
- 响应结果按语义参数（city / offset / extensions / keywords / page）缓存，后续命中缓存不再请求
- `--clear-cache` 可强制重新请求

---

## 6. Compare 能观察什么

`brand_poi.py compare --base A --target B` 按 `poi_id` 比对两个 snapshot，产出：

### 6.1 新增 POI

B 中出现了 A 中没有的 POI。列表包含 POI ID、名称、品牌、功能类型、区县。

### 6.2 消失 POI

A 中有但 B 中消失的 POI。

### 6.3 品牌数量变化

| 品牌 | Base | Target | 变化 |
|------|------|--------|------|
| 智己 | 48 | 52 | +4 |
| 蔚来 | 86 | 82 | -4 |

### 6.4 功能类型变化

| 类型 | Base | Target | 变化 |
|------|------|--------|------|
| experience_store | 40 | 42 | +2 |
| user_center | 41 | 45 | +4 |

### 6.5 区县变化

| 区县 | Base | Target | 变化 |
|------|------|--------|------|
| 浦东新区 | 42 | 48 | +6 |
| 闵行区 | 39 | 37 | -2 |

### 6.6 产物

```
data/brand_poi/compares/A__vs__B/
├── compare.json    # 结构化 delta 数据
└── compare.md      # Markdown delta 报告
```

---

## 分类规则共享

所有分类逻辑集中在 `src/poi_classifier.py`：

- `classify_poi_kind()` — 功能类型分类
- `classify_store_location_type()` — 空间区位类型分类

Scanner（`brand_poi_scanner.py`）和 Analyzer（`brand_poi_analyzer.py`）都 import 此模块。  
修改分类规则只需改 `poi_classifier.py` 一处。

---

## 关键文件一览

| 文件 | 角色 |
|------|------|
| `src/poi_classifier.py` | 分类引擎（共享规则） |
| `src/brand_poi_scanner.py` | API 扫描 + 缓存 |
| `src/brand_poi_snapshot.py` | Snapshot 目录管理 |
| `src/brand_poi.py` | 统一 CLI |
| `src/brand_poi_analyzer.py` | 离线分析 pipeline |
| `src/brand_poi_map_writer.py` | HTML 地图 + MD 报告生成 |
| `src/brand_poi_compare.py` | 旧入口兼容（转发） |
| `tests/test_brand_poi_analyzer.py` | 分析器测试 |
| `tests/test_brand_poi_scanner.py` | 扫描器测试 |
| `tests/test_brand_poi_snapshot.py` | Snapshot + 无 API 边界测试 |
| `tests/test_brand_poi_map_writer.py` | 地图/报告生成测试 |
| `config/brand_poi_compare.yaml` | 品牌配置、扫描策略、API 参数 |
