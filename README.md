# where2go-weekend / 周末去哪儿

> 用数据、AI 和一点点常识，研究复杂的城市空间。

## 项目是什么

**where2go-weekend 不是大众点评替代品，也不是探店榜单。**

它关注的是城市变化本身：哪些街区正在出现新的空间，哪些业态开始聚集，哪些地方正在从普通通勤/办公空间转变为周末生活目的地。

给定街区的 POI（兴趣点）数据，项目自动生成日期级 POI 快照，对比历史快照识别变化事件，输出街区变化指数和 Markdown 城市变化雷达报告。

## 为什么先做上海周末探索

上海是中国城市更新最密集、业态最丰富、独立商业生态最活跃的城市之一。

我们选择从上海开始，是因为：

- POI 密度高，数据价值大
- 城市微更新（小型园区、复合空间）趋势明显
- 本地周末消费场景丰富

## 对比传统推荐平台

| 维度 | 大众点评 | where2go-weekend |
|------|---------|-----------------|
| 核心关注 | 高分、热门、确定性消费决策 | 变化、新鲜度、低拥挤潜力、城市观察价值 |
| 数据驱动 | 用户评分 + 评论 | POI 快照对比 + 变化事件识别 |
| 输出形式 | 榜单 / 推荐 | 变化信号 / 观察路线 / 城市选题 |
| 适合人群 | 消费者决策 | 城市研究者、内容创作者、好奇居民 |

## 快速开始

```bash
# 1. 进入项目
cd where2go-weekend

# 2. 安装依赖
pip3 install pyyaml requests python-dotenv

# 3. 复制环境变量文件
cp .env.example .env
# 编辑 .env，至少填入 AMAP_API_KEY

# 4. 运行
python3 src/run.py --weekend-date 2026-07-11 --snapshot-date 2026-07-08
```

如果未设置 `AMAP_API_KEY`，项目使用 `data/sample_poi.csv` 运行，无需任何外部服务。

## 环境变量

| 变量 | 用途 | 必需 |
|------|------|------|
| `AMAP_API_KEY` | Python POI 采集（Web Service API） | 采集真实 POI 时需要 |
| `AMAP_API_SECRET` | 高德 Web Service 签名密钥 | 仅开启签名验证时需要 |
| `AMAP_JS_API_KEY` | HTML 地图展示（JS API） | 地图加载时需要 |
| `AMAP_SECURITY_JS_CODE` | 高德 JS API 2.0 安全密钥 | 部分 key 配置需要 |

注意：静态 HTML 中暴露 JS API key 只适合本地 MVP。公开发布时需要重新设计 key 管理方式。

## 输出文件

| 文件 | 说明 |
|------|------|
| `data/poi_snapshots/{date}_poi_snapshot.csv` | 日期级 POI 快照 |
| `data/poi_change_events.csv` | 变化事件列表 |
| `data/district_change_scores.csv` | 街区变化指数 |
| `reports/{weekend}_shanghai_weekend.md` | 城市变化雷达报告 |
| `reports/maps/{weekend}_shanghai_weekend_map.html` | 地图预览 |

## 项目结构

```
where2go-weekend/
├── README.md
├── .env.example
├── .gitignore
├── config/
│   ├── districts.yaml
│   ├── categories.yaml
│   └── query_budget.yaml
├── data/
│   ├── sample_poi.csv
│   ├── poi_snapshots/
│   └── ...
├── reports/
│   ├── maps/
│   └── .gitkeep
├── tests/
│   ├── test_amap_client.py
│   ├── test_change_detector.py
│   ├── test_change_score.py
│   ├── test_geocode.py
│   ├── test_map_writer.py
│   └── test_report_writer.py
└── src/
    ├── run.py
    ├── amap_client.py
    ├── change_detector.py
    ├── geocode_districts.py
    ├── map_writer.py
    ├── report_writer.py
    └── scorer.py
```

## 变化指数公式

```
change_score =
  freshness_score * 0.35
  + category_change_score * 0.25
  + low_crowding_potential * 0.20
  + route_potential_score * 0.20
```

- **freshness_score** — 新出现的品类占比
- **category_change_score** — 类目增长/减少的活跃度
- **low_crowding_potential** — 街区低拥挤潜力（网红街区默认偏低）
- **route_potential_score** — 业态多样性 + 新增 POI 带来的路线价值

## 地图可视化

v0.3.2 起，每次运行自动生成静态 HTML 地图。

### 地图 provider

| provider | 底图 | 坐标 | 用途 |
|----------|------|------|------|
| `amap_js`（默认） | 高德 JS API | GCJ-02，不转换 | POI 点位 QA，减少坐标偏差 |
| `leaflet_osm` | Leaflet + OpenStreetMap | 可选 WGS84 转换 | 开放地图风格，可选输出 |

### 坐标模式（仅 leaflet_osm）

| 模式 | 说明 |
|------|------|
| `approx_wgs84`（默认） | GCJ-02 → WGS84 近似转换，用于 OSM 展示 |
| `raw_gcj02` | GCJ-02 直接叠加到 OSM，可能存在偏移 |

### 为什么默认使用高德 JS API

高德 POI 原始坐标为 GCJ-02。Leaflet + OSM 使用 WGS84 底图，即使做近似转换，在街区尺度下仍可能出现可感知偏移。默认使用高德 JS API 可以减少坐标转换风险，确保地图预览与数据采集在同一坐标体系下闭环。

### 命令行示例

```bash
# 默认：高德 JS API 地图
python3 src/run.py --weekend-date 2026-07-11 --snapshot-date 2026-07-08

# Leaflet + OSM 地图（WGS84 转换）
python3 src/run.py --weekend-date 2026-07-11 --map-provider leaflet_osm --coord-mode approx_wgs84

# Leaflet + OSM 原始 GCJ-02
python3 src/run.py --weekend-date 2026-07-11 --map-provider leaflet_osm --coord-mode raw_gcj02

# 跳过地图
python3 src/run.py --weekend-date 2026-07-11 --no-map
```

## CLI 参数

```bash
python3 src/run.py --weekend-date <YYYY-MM-DD> [options]

Required:
  --weekend-date    目标周末日期

Data:
  --snapshot-date   POI 快照日期（默认今天）
  --force           忽略缓存，重新请求 API
  --date            [已弃用] 请使用 --weekend-date

Map:
  --map-provider    amap_js（默认）| leaflet_osm
  --coord-mode      approx_wgs84（默认）| raw_gcj02（仅 leaflet_osm 生效）
  --no-map          跳过地图生成
```

## 运行测试

```bash
python3 -m unittest discover tests -v
```

## 依赖

- Python 3.10+
- PyYAML
- requests
- python-dotenv

## Roadmap

- **v0.1** ✓ sample POI + 街区评分 + Markdown 报告
- **v0.2** ✓ 高德 API + POI 快照 + 变化事件识别 + 城市变化雷达
- **v0.3** ✓ query budget + cache + geocode 校准 + 日期语义拆分
- **v0.3.1** ✓ 日期语义拆分（snapshot_date / weekend_date）+ 智慧坊坐标校准
- **v0.3.2** ✓ Leaflet + OSM 地图可视化（GCJ-02→WGS84）
- **v0.3.2.1** ✓ 默认地图 provider 切换为高德 JS API + Leaflet 可选保留
- **v0.4** 加入内容提及数据（小红书、公众号）
- **v0.5** 生成地图路线与个人偏好推荐
