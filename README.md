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

## v0.2 新功能

- **日期级 POI 快照** — 每次运行生成 `data/poi_snapshots/{date}_poi_snapshot.csv`
- **高德 API 集成** — 通过 `.env` 配置 `AMAP_API_KEY`，自动采集真实数据
- **变化事件识别** — 对比历史快照，识别 `new_poi` / `disappeared_poi` / `category_growth` / `category_decline`
- **街区变化指数** — 基于变化事件、新鲜度、低拥挤潜力、路线潜力的综合评分
- **城市变化雷达报告** — 聚焦变化信号，而非推荐榜单

## 快速开始

```bash
# 1. 进入项目
cd where2go-weekend

# 2. 安装依赖
pip3 install pyyaml requests python-dotenv

# 3. 复制环境变量文件（可选，用于高德 API）
cp .env.example .env
# 编辑 .env，填入 AMAP_API_KEY

# 4. 运行
python3 src/run.py --date 2026-07-11
```

如果未设置 `AMAP_API_KEY`，项目使用 `data/sample_poi.csv` 运行，无需任何外部服务。

## 输出文件

| 文件 | 说明 |
|------|------|
| `data/poi_snapshots/{date}_poi_snapshot.csv` | 日期级 POI 快照 |
| `data/poi_change_events.csv` | 变化事件列表 |
| `data/district_scores.csv` | 传统街区评分（v0.1 保留） |
| `data/district_change_scores.csv` | 街区变化指数 |
| `reports/YYYY-MM-DD_shanghai_weekend.md` | 城市变化雷达报告 |

## v0.2 项目结构

```
where2go-weekend/
├── README.md
├── .env.example
├── .gitignore
├── config/
│   ├── districts.yaml       # 街区配置
│   └── categories.yaml      # POI 类别配置
├── data/
│   ├── sample_poi.csv       # 示例 POI 数据
│   ├── poi_snapshots/       # 日期级 POI 快照
│   ├── district_scores.csv  # 传统评分
│   ├── district_change_scores.csv  # 变化指数
│   └── poi_change_events.csv       # 变化事件
├── reports/                 # 报告输出目录
├── tests/
│   ├── test_amap_client.py
│   ├── test_change_detector.py
│   ├── test_change_score.py
│   └── test_report_writer.py
└── src/
    ├── run.py               # 主入口
    ├── amap_client.py       # 高德 API + 快照生成
    ├── change_detector.py   # 变化事件识别
    ├── scorer.py            # 评分逻辑
    └── report_writer.py     # 报告生成
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
- **v0.3** 每周快照，识别新增 / 消失 POI，积累变化趋势
- **v0.4** 加入内容提及数据（小红书、公众号）
- **v0.5** 生成地图路线与个人偏好推荐
