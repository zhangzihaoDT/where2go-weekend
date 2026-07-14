# Evidence Levels：证据分级与事件判断

> 何时读取：需要判断现有证据是否足以确认开业或关店事件时。

---

## 1. 证据分级

### 高置信度

满足任意一项：

- 品牌官方公告明确给出开业日期
- 商场官方公告明确给出开业日期
- 品牌官方门店页从筹备状态变为营业状态，并有明确时间证据
- 官方活动海报或正式新闻稿明确写明试营业或开业日期

### 中置信度

满足多项交叉证据：

- 地图新增且有独立联系电话
- 商场招商、媒体报道或店员招聘信息指向近期营业
- 多个用户内容在相近日期提及"刚开""试营业"
- 官方门店列表新增，但没有明确开业日期

### 低置信度

仅有：

- 单一地图 POI
- 无来源的聚合页面
- 无法核验的用户评论
- 只有门店名称，没有营业状态或日期

低置信度证据不能确认开业。

---

## 2. 日期口径

同时维护以下字段：

```text
first_seen_date
opening_date_exact
opening_date_lower_bound
opening_date_upper_bound
opening_date_type
```

### 找到明确日期

```text
opening_date_exact = 官方明确日期
opening_date_type = exact
```

### 没有明确日期，但前后快照可界定

例如 7 月 12 日不存在、7 月 19 日已营业：

```text
opening_date_lower_bound = 2026-07-12
opening_date_upper_bound = 2026-07-19
opening_date_type = interval
```

### 只有首次观测

```text
first_seen_date = 当前快照日期
opening_date_exact = null
opening_date_type = unknown
```

不得用 `first_seen_date` 填充 `opening_date_exact`。

---

## 3. 事件确认规则

只有达到以下要求，才能将事件升级为 `confirmed_opening`：

```text
存在高置信度证据
或
至少两个相互独立的中置信度证据，且时间和地址一致
```

确认结果必须包含：

```text
event_id, store_key, brand_name, canonical_name
city, district, mall_name, event_type
first_seen_date, opening_date_exact
opening_date_lower_bound, opening_date_upper_bound
confidence, evidence_count, evidence_summary
source_urls, review_status
```

无法确认时保留：

```text
newly_observed_store
unresolved_candidate
```

不要为了让报告完整而猜测日期。
