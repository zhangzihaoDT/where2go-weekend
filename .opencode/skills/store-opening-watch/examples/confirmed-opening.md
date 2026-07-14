# 案例：确认开业 — Nike 上海西岸梦中心店

> 展示从新增 POI 到确认开业的完整链路。

---

## 输入观测

**当前快照**中出现此前从未观测到的 POI：

| 字段 | 值 |
|---|---|
| 名称 | 耐克Nike(上海西岸梦中心店) |
| 品牌 | Nike |
| 地址 | 上海市徐汇区云锦路 688 号西岸梦中心 L1 层 |
| 城市 | 上海 |
| 坐标 | 121.456, 31.145 |
| 电话 | 021-XXXXXXX |

**历史记录**：baseline 快照（2 周前）中该地址/商场无 Nike 门店。

## 变化候选

```text
event_type: new_store_candidate
first_seen_date: 本期快照日期
opening_date_exact: null
```

## 搜索证据

使用以下精确查询：

1. `Nike 西岸梦中心 开业`
2. `耐克 西岸梦中心 正式开业`
3. `上海西岸梦中心 Nike 新店`
4. `site:nike.com 西岸梦中心`

**搜索结果**：

- Nike 官方微信公众号于 2026-07-05 发布推文"Nike 上海西岸梦中心店正式开业"
- 西岸梦中心官方公众号同步确认
- 多家本地媒体报道开业活动（含日期和照片）

## 判断过程

| 条件 | 结果 |
|---|---|
| 品牌官方公告明确给出开业日期 | ✓ 2026-07-05 |
| 商场官方公告明确给出开业日期 | ✓ |
| 正式新闻报道有明确时间地点 | ✓ |
| 综合置信度 | **高** |

## 最终状态

```text
event_type: confirmed_opening
confidence: high
opening_date_exact: 2026-07-05
opening_date_type: exact
evidence_count: 3
```

## 为什么不是其他状态

| 其他状态 | 排除原因 |
|---|---|
| `new_store_candidate` | 已有充分外部证据升级 |
| `new_poi_candidate` | 无既有门店实体可匹配，是新门店 |
| `newly_observed_store` | 证据充分，可以确认开业 |
