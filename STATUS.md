# where2go-weekend 项目状态

> 该文件是动态项目状态记录，不是永久规范。
> 重大版本、架构或测试状态发生变化后更新。
> Agent 在询问当前进度、下一步或验收状态时应读取本文件。
> 项目规则以 AGENTS.md 为准，当前事实以代码和测试为准。
> AGENTS.md 与 STATUS.md 冲突时，规则以 AGENTS.md 为准，事实以代码和测试为准。

## 验证信息

- 最后验证：2026-07-14
- 验证提交：`b6c4ea934be05d6272d28612ccd06d47c513e0ba`
- 验证命令：`python3 -m unittest discover tests -v`
- 验证结果：215 tests passed
- 工作区状态：存在未提交的文档修改

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
- `src/brand_poi_scanner.py`：品牌 POI 扫描（text / around / grid 三种模式）
- `src/brand_poi_snapshot.py`：品牌快照管理（CSV + JSON + manifest）
- 快照写入 `data/poi_snapshots/{date}_poi_snapshot.csv`
- 品牌快照写入 `data/brand_stores/snapshots/{date}_{city}/`
- 缓存机制：API 响应缓存至 `data/cache/`
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
  --snapshot-date   POI 快照日期（默认今天）
  --force           忽略缓存，重新请求 API
  --no-map          跳过地图生成
  --map-provider    amap_js（默认）| leaflet_osm
  --coord-mode      approx_wgs84（默认）| raw_gcj02（仅 leaflet_osm）
```

```
python3 src/brand_poi_compare.py [options]
  --city, --date, --scan-mode, --smoke-query, --clear-cache
```

### 测试

215 项测试全部通过（`python3 -m unittest discover tests -v`）。

测试覆盖模块：
- `test_amap_client.py`
- `test_brand_poi_analyzer.py`
- `test_brand_poi_map_writer.py`
- `test_brand_poi_scanner.py`
- `test_brand_poi_snapshot.py`
- `test_change_detector.py`
- `test_change_score.py`
- `test_district_config.py`
- `test_geocode.py`
- `test_map_writer.py`
- `test_report_writer.py`

---

## 当前风险

| 风险 | 说明 |
|---|---|
| 高德数据覆盖延迟 | 新开业门店 1-4 周后才出现 POI，关店 POI 长期残留 |
| 假新增 / 假消失 | POI 坐标漂移、楼层变化、数据源更新容易产生误报 |
| 门店实体匹配 | 同一商场多店型并存、地址冲突、名称不标准仍是难点 |
| 证据分级自动化 | 外部证据搜索链路的自动化和缓存尚未完成 |
| 产品层未完成 | 当前仍是数据管道和 CLI，没有面向消费者的界面 |
| Skill 维护 | brand-map-pipeline 仍为单文件 35 行，store-opening-watch 已拆分 |

---

## 下一阶段

1. 项目基础设施完成（AGENTS.md + STATUS.md + SOUL.md 分层到位）
2. store-opening-watch 渐进式拆分已完成，推进产物契约和证据状态统一
3. 街区变化解释层——将变化指数转化为可读的"为什么这个街区值得关注"
4. 用户产品层验证——确定第一版对外输出形态（报告 / 地图 / 小程序）
