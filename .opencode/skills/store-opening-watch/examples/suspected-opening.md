# 案例：疑似新增 — Nike 上海西岸梦中心店（无外部证据）

> 展示当外部证据不足时，应保留的状态。

---

## 输入观测

**当前快照**中出现此前从未观测到的 POI，数据与 confirmed-opening 案例完全相同。

## 变化候选

```text
event_type: new_store_candidate
first_seen_date: 本期快照日期
opening_date_exact: null
```

## 搜索证据

使用精确查询后未找到有效结果：

1. `Nike 西岸梦中心 开业` → 无有效结果
2. `耐克 西岸梦中心 新店` → 无有效结果
3. `site:nike.com 西岸梦中心` → 未在官方门店列表中找到

## 判断过程

| 条件 | 结果 |
|---|---|
| 品牌官方公告 | ✗ 未找到 |
| 商场官方公告 | ✗ 未找到 |
| 正式新闻报道 | ✗ 未找到 |
| 用户内容提及"刚开" | ✗ 未找到 |
| 综合置信度 | **低** |

## 最终状态

```text
event_type: new_store_candidate
confidence: low
first_seen_date: 本期快照日期
opening_date_exact: null
opening_date_type: unknown
```

保留为 `newly_observed_store`，加入待确认候选列表。

## 为什么不是其他状态

| 其他状态 | 排除原因 |
|---|---|
| `confirmed_opening` | 无高置信度证据，无中置信度交叉 |
| `possible_closed_store` | 这是新增，不是消失 |
| 不记录 | 有 POI 存在，必须记录为候选以便后续追踪 |
