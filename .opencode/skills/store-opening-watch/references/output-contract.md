# Output Contract：输出契约

> 何时读取：需要写入结构化结果或生成变化监控报告时。

---

## 1. 输出目录约定

按照 `data/brand_stores/` 下的目录结构写入（详见 `workflow.md`）：

```text
registry/     # 门店主表和别名表
compares/     # 两期比对结果
events/       # 确认事件和待处理候选
```

---

## 2. compare.json

保存机器可读的完整比对结果：

```json
{
  "baseline_date": "2026-07-12",
  "current_date": "2026-07-19",
  "scope": {
    "brands": ["Nike", "Adidas"],
    "cities": ["上海", "苏州"]
  },
  "quality_status": "usable",
  "counts": {
    "baseline_records": 421,
    "current_records": 425,
    "new_store_candidates": 3,
    "possible_closed_stores": 1,
    "possible_duplicates": 4
  },
  "events": []
}
```

---

## 3. candidates.csv

至少包含：

```text
event_id, priority, event_type, brand_name, canonical_name
city, district, mall_name, baseline_match, first_seen_date
confidence, needs_search, needs_review, reason
```

---

## 4. compare.md

必须使用以下结构：

```markdown
# 门店变化监控

## 1. 本期结论
## 2. 确认开业
## 3. 新增待确认
## 4. 迁址、改名与楼层变化
## 5. 疑似关闭
## 6. 数据质量与重复 POI
## 7. 待人工复核
```

### 报告中必须明确区分：

- 已确认开业
- 本期首次观测
- 疑似新增
- 疑似关店
- 纯数据变化

---

## 5. 数据质量状态

详见 `workflow.md` 第 6 节。每次运行必须给出 `usable` / `usable_with_warnings` / `unusable` 三者之一。

---

## 6. 最终汇报格式

完成任务后，以简洁清单汇报：

```markdown
## 运行结果

- 基准快照：...
- 当前快照：...
- 数据质量：usable / usable_with_warnings / unusable
- 原始 POI：...
- 去重后门店实体：...
- 确认开业：...
- 新增待确认：...
- 疑似关闭：...
- 改名/迁址/楼层变化：...
- 重复 POI：...
- 待人工复核：...

## 输出文件

- registry/...
- compares/...
- events/...

## 关键提醒

- 明确说明哪些结论来自结构化比对
- 明确说明哪些结论有外部证据
- 明确说明哪些仍是待确认候选
```
