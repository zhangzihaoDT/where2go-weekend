# where2go-weekend 项目状态

> 该文件是动态项目状态记录，不是永久规范。
> 重大版本、架构或测试状态发生变化后更新。
> Agent 在询问当前进度、下一步或验收状态时应读取本文件。
> 项目规则以 AGENTS.md 为准，当前事实以代码和测试为准。
> AGENTS.md 与 STATUS.md 冲突时，规则以 AGENTS.md 为准，事实以代码和测试为准。

## 验证信息

- 最后验证：2026-07-15
- 验证提交：`13ba3a2`
- 验证命令：`python3 -m unittest discover tests -v`
- 验证结果：310 tests passed
- 工作区状态：clean

---

## 当前阶段

项目处于 OpenCode 基础设施建设和核心数据管道稳定化阶段。已完成跑通完整采集-快照-分析-报告流水线，正在建设门店变化监控 SOP 和项目级可复用规范。

未进入消费级产品或小程序开发阶段。

---

## 当前 OpenCode 架构

| 层级 | 文件 | 用途 |
|---|---|---|
| 全局 instructions | `~/.config/opencode/SOUL.md` | 工作人格指令 |
| 全局自动加载 | `~/.config/opencode/AGENTS.md` | 视觉规范 + Context7 步骤 |
| 全局 MCP | `opencode.jsonc` → Context7 | 文档检索 |
| 项目宪法 | `<root>/AGENTS.md` | 项目硬约束 |
| 项目状态 | `<root>/STATUS.md` | 动态项目状态 |
| Skill | `.opencode/skills/brand-map-pipeline/` | 品牌 POI 采集与可视化 |
| Skill | `.opencode/skills/store-opening-watch/` | 门店变化监控 |

---

## 已完成能力

### 采集与快照

- `src/run.py`：街区 POI 采集 → 快照 → 变化检测 → 评分 → 报告 → 地图的完整流水线
- `src/collection_scheduler.py`：广度优先调度、自适应分页、电路熔断、QPS 控制
- `src/brand_poi_scanner.py`：品牌 POI 扫描（text / around / grid 三种模式）
- `src/brand_poi_snapshot.py`：品牌快照管理（CSV + JSON + manifest）
- 快照写入 `data/weekend_district_poi/{date}_poi_snapshot.csv`，附带 manifest 和归档 summary
- 品牌快照写入 `data/brand_stores/snapshots/{date}_{city}/`
- 缓存机制：API 响应缓存至 `data/cache/`，cache key 含中心坐标和 page_size
- sample POI 回退（`data/sample_poi.csv`）

### 变化检测

- `src/change_detector.py`：POI 快照变化检测（新增 / 消失 / 类型变化）
- `src/brand_poi_compare.py`：品牌 POI 两期比较
- 比较结果写入 `data/brand_stores/compares/` 独立目录
- 事件输出：`data/poi_change_events.csv`

### 分析与评分

- `src/poi_classifier.py`：POI 类型分类（店型、空间区位）
- `src/scorer.py`：街区变化指数计算（freshness / category change / low crowding / route potential）
- 评分输出 `data/district_scores.csv`、`data/district_change_scores.csv`

### 地图

- 支持高德 JS API（amap_js，默认）和 Leaflet + OSM（leaflet_osm）两种 provider
- 支持 GCJ-02 直接使用和近似 WGS84 转换
- 地图 HTML 输出至 `reports/maps/`

### 报告

- `src/report_writer.py`：Markdown 报告（城市变化雷达）
- 报告输出至 `reports/{date}_shanghai_weekend.md`

### 门店变化监控

- store-opening-watch Skill 已完成渐进式结构重构（入口 SKILL.md + 6 个 references + 4 个 examples）
- 门店 registry 已在 `data/brand_stores/registry/` 建立初始基线
- 比较候选已产出（`data/brand_stores/compares/`、`data/brand_stores/events/`）

### CLI 能力

```
python3 src/run.py --weekend-date YYYY-MM-DD [options]
  --snapshot-date      POI 快照日期（默认今天）
  --force              忽略缓存，重新请求 API
  --no-map             跳过地图生成
  --map-provider       amap_js（默认）| leaflet_osm
  --coord-mode         approx_wgs84（默认）| raw_gcj02（仅 leaflet_osm）
  --estimate-requests  估算请求量并退出，不调用 API
```

```
python3 src/brand_poi_compare.py [options]
  --city, --date, --scan-mode, --smoke-query, --clear-cache
```

### 测试

310 项测试全部通过（`python3 -m unittest discover tests -v`）。

测试覆盖模块：
- `test_amap_client.py`
- `test_batch2a.py`
- `test_brand_poi_analyzer.py`
- `test_brand_poi_map_writer.py`
- `test_brand_poi_scanner.py`
- `test_brand_poi_snapshot.py`
- `test_change_detector.py`
- `test_change_score.py`
- `test_collection_scheduler.py`
- `test_district_config.py`
- `test_geocode.py`
- `test_map_writer.py`
- `test_report_writer.py`
- `test_run_compare_e2e.py`

---

## 当前风险

| 风险 | 说明 |
|---|---|
| 历史 Snapshot 无 manifest | 2026-07-08/11/12 三期无 manifest，无法与正式 baseline Compare |
| 仅一期正式 baseline | 2026-07-15 是首期含 manifest 的 complete Snapshot，尚未执行过真实同口径 Compare |
| 关键词命中率有限 | 11 个关键词中有 5 个（美术馆/买手店/联合办公/共享空间/工作室）在当前采样圆内零返回 |
| 采样点单一 | 每个区域仅一个固定圆心，杨浦滨江为带状区域但使用圆形采样 |
| 实体匹配仍是精确三字段 | `poi_id\|name\|address`，名称后缀变化导致假新增 |
| 产品层未完成 | 当前仍是数据管道和 CLI，没有面向消费者的界面 |

---

## 下一阶段

1. **等待下一期真实同口径采集** — 配置已冻结，下一期 run 将自动触发 Compare（两期 fingerprint 一致，source=amap，status=complete）
2. **执行真实跨期 Compare 验证** — 验证变化事件质量，确认新增/消失/类目变化可追溯
3. **字段级变化检测** — 在现有匹配基础上增加 name/address/coord 变化输出
4. **协调空间采样模型** — 优化杨浦滨江等带状区域的采样点设计
