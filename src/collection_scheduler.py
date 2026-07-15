"""
Collection scheduler for where2go-weekend.

Implements breadth-first, adaptive-pagination, circuit-breaker collection.
"""
import math
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import date
from typing import Optional


EXEC_STATUS_SUCCESS = "success"
EXEC_STATUS_EMPTY = "empty"
EXEC_STATUS_CACHE_HIT = "cache_hit"
EXEC_STATUS_SKIPPED_BUDGET = "skipped_budget"
EXEC_STATUS_SKIPPED_KEYWORD_LIMIT = "skipped_keyword_limit"
EXEC_STATUS_FAILED_API = "failed_api"
EXEC_STATUS_FAILED_NETWORK = "failed_network"
EXEC_STATUS_NOT_ATTEMPTED_QUOTA_BLOCKED = "not_attempted_quota_blocked"


@dataclass
class RequestSlot:
    district_id: str
    district_name: str
    category_id: str
    keyword: str
    page: int
    priority: int = 0
    is_first_page: bool = True
    is_in_approved_plan: bool = True


@dataclass
class RequestPlan:
    approved: list[RequestSlot] = field(default_factory=list)
    excluded_keyword_limit: int = 0
    excluded_district_budget: int = 0
    first_page_count: int = 0
    second_page_candidates: int = 0
    total_candidates: int = 0

    @property
    def approved_count(self) -> int:
        return len(self.approved)


def estimate_requests(district_config: dict, cat_config: dict,
                      budget_config: dict) -> dict:
    districts = district_config.get("districts", [])
    keyword_plan = []
    for cat in cat_config.get("categories", []):
        for kw in cat.get("query_keywords", []):
            keyword_plan.append((kw, cat["category_id"]))
    total_kw = len(keyword_plan)

    budgets = _parse_budget(budget_config)
    max_run = budgets.get("max_requests_per_run", 999)
    page_size = budgets.get("page_size", 20)
    adaptive = budgets.get("adaptive_pagination", True)

    first_page_total = 0
    second_page_upper = 0
    per_district_first = {}
    total_raw_candidates = 0
    total_approved_max = 0

    for d in districts:
        did = d["district_id"]
        tier_key = did
        tier = budget_config.get("district_tiers", {}).get(tier_key, "C")
        rules = budget_config.get("tier_rules", {}).get(tier, {})
        max_kw = min(rules.get("max_keywords", 999), total_kw)
        tier_pages = rules.get("max_pages", budgets.get("max_pages", 1))
        first_count = max_kw
        first_page_total += first_count
        per_district_first[did] = first_count
        total_raw_candidates += total_kw * tier_pages
        total_approved_max += max_kw * tier_pages
        if tier_pages > 1 and adaptive:
            second_page_upper += max_kw

    keyword_limit_excluded = total_raw_candidates - total_approved_max

    return {
        "total_candidates": total_raw_candidates,
        "keyword_limit_excluded": keyword_limit_excluded,
        "first_page_base": first_page_total,
        "second_page_upper": second_page_upper if adaptive else 0,
        "max_requests_per_run": max_run,
        "estimated_min_requests": first_page_total,
        "estimated_max_requests": min(first_page_total + second_page_upper, max_run),
        "per_district_first_page": per_district_first,
        "page_size": page_size,
        "adaptive_pagination": adaptive,
    }


def build_plan(district_config: dict, cat_config: dict,
               budget_config: dict) -> RequestPlan:
    districts = district_config.get("districts", [])
    keyword_plan = []
    for cat in cat_config.get("categories", []):
        for kw in cat.get("query_keywords", []):
            keyword_plan.append((kw, cat["category_id"]))

    total_kw = len(keyword_plan)
    budgets = _parse_budget(budget_config)
    max_pages = budgets.get("max_pages", 1)
    max_run = budgets.get("max_requests_per_run", 999)
    adaptive = budgets.get("adaptive_pagination", True)

    # Step 1: collect first-page kw per district (respecting max_keywords + keyword order)
    district_first_pages: dict[str, list[tuple[str, str]]] = {}
    for d in districts:
        did = d["district_id"]
        tier_key = did
        tier = budget_config.get("district_tiers", {}).get(tier_key, "C")
        rules = budget_config.get("tier_rules", {}).get(tier, {})
        max_kw = min(rules.get("max_keywords", 999), total_kw)
        district_first_pages[did] = keyword_plan[:max_kw]

    total_candidates = 0
    excluded_keyword_limit = 0
    for d in districts:
        did = d["district_id"]
        tier_key = did
        tier = budget_config.get("district_tiers", {}).get(tier_key, "C")
        rules = budget_config.get("tier_rules", {}).get(tier, {})
        mk = rules.get("max_keywords", 999)
        tier_pages = rules.get("max_pages", budgets.get("max_pages", 1))
        total_candidates += total_kw * tier_pages
        excluded_keyword_limit += (total_kw - min(total_kw, mk)) * tier_pages

    # Step 2: round-robin first pages
    first_page_slots: list[RequestSlot] = []
    district_kw_queue = {d["district_id"]: list(district_first_pages[d["district_id"]])
                         for d in districts}

    district_order = [d["district_id"] for d in districts]
    remaining = list(district_order)
    while remaining:
        next_round = []
        for did in remaining:
            queue = district_kw_queue[did]
            if not queue:
                continue
            kw, cat_id = queue.pop(0)
            first_page_slots.append(RequestSlot(
                district_id=did,
                district_name="",
                category_id=cat_id,
                keyword=kw,
                page=1,
                is_first_page=True,
            ))
            next_round.append(did)
        remaining = next_round

    first_page_count = len(first_page_slots)

    # Step 3: fill district_name
    district_name_map = {d["district_id"]: d.get("name", d["district_id"])
                         for d in districts}
    for slot in first_page_slots:
        slot.district_name = district_name_map.get(slot.district_id, "")

    # Step 4: build approved list (first page only; second page added at execution time)
    approved = list(first_page_slots)
    # Apply per-run budget: trim to max_run
    if len(approved) > max_run:
        approved = approved[:max_run]

    excluded_district_budget = 0
    # Count how many would have been excluded by district budget
    district_usage = defaultdict(int)
    for slot in approved:
        district_usage[slot.district_id] += 1
    for d in districts:
        did = d["district_id"]
        per_district_max = budgets.get("per_district_max_requests", 10)
        if district_usage[did] > per_district_max:
            excluded_district_budget += district_usage[did] - per_district_max

    return RequestPlan(
        approved=approved,
        excluded_keyword_limit=excluded_keyword_limit,
        excluded_district_budget=excluded_district_budget,
        first_page_count=first_page_count,
        second_page_candidates=sum(
            len(district_first_pages[d["district_id"]])
            for d in districts
        ) if adaptive else 0,
        total_candidates=total_candidates,
    )


def should_request_next_page(num_results: int, page_size: int,
                              api_count: Optional[int] = None,
                              current_page: int = 1) -> bool:
    if api_count is not None:
        return api_count > page_size * current_page
    return num_results == page_size


def build_second_page_slots(plan: RequestPlan, district_id: str, district_name: str,
                            category_id: str, keyword: str,
                            first_page_count: int, remaining_budget: int,
                            page_size: int, api_count: Optional[int] = None) -> list[RequestSlot]:
    if remaining_budget <= 0:
        return []
    if not should_request_next_page(first_page_count, page_size, api_count):
        return []
    return [RequestSlot(
        district_id=district_id,
        district_name=district_name,
        category_id=category_id,
        keyword=keyword,
        page=2,
        is_first_page=False,
    )]


_INFCODE_HARD_STOP = {"10003", "10044", "40000", "40002"}
_INFCODE_RETRYABLE = {"10004", "10015", "10016", "10019", "10020", "10021"}
_INFCODE_NO_RETRY = {"10001", "10002", "10005", "10007", "10009", "10012", "10041",
                     "20000", "20001", "20002"}


def classify_infocode(infocode: str) -> str:
    if infocode in _INFCODE_HARD_STOP:
        return "hard_stop"
    if infocode in _INFCODE_RETRYABLE:
        return "retryable"
    return "no_retry"


class QPSTimer:
    def __init__(self, max_qps: float = 1.0, sleep_func=None, clock_func=None):
        self.max_qps = max_qps
        self._last_call = 0.0
        import time
        self._sleep = sleep_func if sleep_func is not None else time.sleep
        self._time_func = clock_func if clock_func is not None else time.monotonic

    @property
    def min_interval(self) -> float:
        if self.max_qps <= 0:
            return 0.0
        return 1.0 / self.max_qps

    def wait_if_needed(self):
        interval = self.min_interval
        if interval <= 0:
            return
        now = self._time_func()
        elapsed = now - self._last_call
        if elapsed < interval:
            self._sleep(interval - elapsed)
        self._last_call = self._time_func()

    def mark(self):
        self._last_call = self._time_func()


def compute_retry_delay(attempt: int, initial_backoff: float = 1.0,
                        max_backoff: float = 4.0, jitter: bool = True) -> float:
    import random
    delay = min(initial_backoff * (2 ** (attempt - 1)), max_backoff)
    if jitter:
        delay *= 0.5 + random.random() * 0.5
    return delay


def _parse_budget(budget_config: dict) -> dict:
    max_run = budget_config.get("max_requests_per_run")
    if max_run is None:
        max_run = budget_config.get("daily_max_requests", 30)
    per_district = budget_config.get("per_district_max_requests", 10)
    max_pages = budget_config.get("max_pages_default", 1)
    sch = budget_config.get("scheduler", {})
    strategy = sch.get("strategy", "breadth_first")
    adaptive = sch.get("adaptive_pagination", True)
    page_size = sch.get("page_size", 20)
    retry_policy = budget_config.get("retry_policy", {})
    return {
        "max_requests_per_run": max_run,
        "per_district_max_requests": per_district,
        "max_pages": max_pages,
        "strategy": strategy,
        "adaptive_pagination": adaptive,
        "page_size": page_size,
        "retry_policy": retry_policy,
    }
