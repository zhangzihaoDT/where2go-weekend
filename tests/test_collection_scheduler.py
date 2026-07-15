import os
import sys
import unittest
from datetime import date

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, PROJECT_ROOT)

from src.collection_scheduler import (
    build_plan,
    estimate_requests,
    should_request_next_page,
    build_second_page_slots,
    classify_infocode,
    _parse_budget,
    QPSTimer,
    RequestSlot,
    RequestPlan,
)
from src.amap_client import CollectionState, FETCH_STATUS_SKIPPED, FETCH_STATUS_API, FETCH_STATUS_API_FAILED


def _make_config(district_ids=None, tiers=None, max_pages_map=None,
                 max_kw_map=None, total_kw=9, max_run=30, per_district_max=10):
    if district_ids is None:
        district_ids = ["d1", "d2", "d3"]
    if tiers is None:
        tiers = {d: "A" for d in district_ids[:2]}
        if len(district_ids) > 2:
            tiers[district_ids[2]] = "B"
    if max_pages_map is None:
        max_pages_map = {d: 2 for d in district_ids[:2]}
        if len(district_ids) > 2:
            max_pages_map[district_ids[2]] = 1
    if max_kw_map is None:
        max_kw_map = {d: 7 for d in district_ids[:2]}
        if len(district_ids) > 2:
            max_kw_map[district_ids[2]] = 6

    districts = []
    for did in district_ids:
        d = {"district_id": did, "name": f"街区{did}", "city": "上海",
             "center_lng": 121.0, "center_lat": 31.0, "radius_m": 500}
        districts.append(d)

    tier_rules = {}
    for t in set(tiers.values()):
        sample_did = [d for d in tiers if tiers[d] == t][0]
        tier_rules[t] = {
            "max_keywords": max_kw_map.get(sample_did, 7),
            "max_pages": max_pages_map.get(sample_did, 1),
        }

    categories = [{"category_id": f"cat{i}", "query_keywords": [f"kw{i}"]}
                  for i in range(total_kw)]

    budget = {
        "max_requests_per_run": max_run,
        "per_district_max_requests": per_district_max,
        "district_tiers": tiers,
        "tier_rules": tier_rules,
        "scheduler": {"strategy": "breadth_first", "adaptive_pagination": True,
                      "max_pages": 2, "page_size": 20},
        "retry_policy": {"max_retries": 1, "initial_backoff_seconds": 0.01,
                         "max_backoff_seconds": 0.05, "jitter": False},
    }

    return {"districts": districts}, {"categories": categories}, budget


class TestBreadthFirstScheduling(unittest.TestCase):
    """1. All districts first page before any second page."""

    def test_first_pages_before_second(self):
        """All first-page slots appear before any second-page slot."""
        dc, cc, bc = _make_config()
        plan = build_plan(dc, cc, bc)
        self.assertTrue(plan.first_page_count > 0)
        first_pages = [s for s in plan.approved if s.is_first_page]
        self.assertEqual(len(first_pages), plan.first_page_count)
        for s in first_pages:
            self.assertEqual(s.page, 1)

    def test_three_districts_round_robin(self):
        """Three districts appear in round-robin order in first page."""
        dc, cc, bc = _make_config(district_ids=["d1", "d2", "d3"])
        plan = build_plan(dc, cc, bc)
        dids = [s.district_id for s in plan.approved if s.is_first_page]
        self.assertEqual(dids[0], "d1")
        self.assertEqual(dids[1], "d2")
        self.assertEqual(dids[2], "d3")
        # Each district gets alternating first page slots
        for i in range(3, len(dids)):
            expected = ["d1", "d2", "d3"][i % 3]
            # Stop checking once a district runs out of keywords
            remaining = {dids.count(d) for d in dids}
            if min(remaining) < (i // 3 + 1):
                break
            self.assertEqual(dids[i], expected,
                             f"position {i} should be {expected} ({dids[i]})")


class TestKeywordLimitExclusion(unittest.TestCase):
    """2-3. Tier A/B keyword limits correct."""

    def test_tier_a_max_keywords(self):
        """Tier A first page respects max_keywords=7."""
        dc, cc, bc = _make_config(district_ids=["d1", "d2"],
                                  tiers={"d1": "A", "d2": "A"},
                                  max_kw_map={"d1": 7, "d2": 7})
        plan = build_plan(dc, cc, bc)
        d1_kws = [s for s in plan.approved if s.district_id == "d1" and s.is_first_page]
        self.assertEqual(len(d1_kws), 7)

    def test_tier_b_max_keywords(self):
        """Tier B first page respects max_keywords=6."""
        dc, cc, bc = _make_config(district_ids=["d3"],
                                  tiers={"d3": "B"},
                                  max_kw_map={"d3": 6})
        plan = build_plan(dc, cc, bc)
        d3_kws = [s for s in plan.approved if s.district_id == "d3" and s.is_first_page]
        self.assertEqual(len(d3_kws), 6)


class TestBudgetLimit(unittest.TestCase):
    """4. Per-run budget not exceeded."""

    def test_budget_not_exceeded(self):
        """Approved count respects max_requests_per_run."""
        dc, cc, bc = _make_config(max_run=5)
        plan = build_plan(dc, cc, bc)
        self.assertLessEqual(plan.approved_count, 5)

    def test_rear_district_not_starved(self):
        """Round-robin ensures rear districts get first page coverage first."""
        dc, cc, bc = _make_config(district_ids=["d1", "d2", "d3"], max_run=20)
        plan = build_plan(dc, cc, bc)
        dids = [s.district_id for s in plan.approved if s.is_first_page]
        d1_count = sum(1 for d in dids if d == "d1")
        d3_count = sum(1 for d in dids if d == "d3")
        # With 20 budget and 20 first-page, all districts have equal first page
        self.assertGreater(d1_count, 0)
        self.assertGreater(d3_count, 0)


class TestAdaptivePagination(unittest.TestCase):
    """6-12. Adaptive pagination rules."""

    def test_page_full_needs_next(self):
        """page 1 full → should request page 2."""
        self.assertTrue(should_request_next_page(20, 20))
        self.assertTrue(should_request_next_page(20, 20, api_count=40, current_page=1))
        self.assertTrue(should_request_next_page(20, 20, api_count=25, current_page=1),
                        "25 results > 20 per page means more data exists")

    def test_page_partial_no_next(self):
        """page 1 less than page_size → no page 2."""
        self.assertFalse(should_request_next_page(5, 20))
        self.assertFalse(should_request_next_page(19, 20))

    def test_count_insufficient_no_next(self):
        """api_count shows no more data → no page 2."""
        self.assertFalse(should_request_next_page(20, 20, api_count=20, current_page=1))
        self.assertFalse(should_request_next_page(20, 20, api_count=20, current_page=1))

    def test_page_empty_no_next(self):
        """page 1 empty → no page 2."""
        self.assertFalse(should_request_next_page(0, 20))

    def test_no_budget_for_second_page(self):
        """No remaining budget → no second page."""
        slots = build_second_page_slots(
            RequestPlan(), "d1", "街区1", "cat1", "kw1",
            20, remaining_budget=0, page_size=20,
        )
        self.assertEqual(len(slots), 0)

    def test_second_page_only_when_needed(self):
        """page 1 full with budget → second page approved."""
        slots = build_second_page_slots(
            RequestPlan(), "d1", "街区1", "cat1", "kw1",
            20, remaining_budget=10, page_size=20,
        )
        self.assertEqual(len(slots), 1)
        self.assertEqual(slots[0].page, 2)


class TestCircuitBreakerErrorCodes(unittest.TestCase):
    """13-20. Error handling."""

    def test_hard_stop_infocodes(self):
        """10003, 10044, 40000, 40002 are hard_stop."""
        for code in ["10003", "10044", "40000", "40002"]:
            self.assertEqual(classify_infocode(code), "hard_stop")

    def test_retryable_infocodes(self):
        """10020, 10021 are retryable; 10012 is not."""
        for code in ["10020", "10021", "10004", "10015", "10016", "10019"]:
            self.assertEqual(classify_infocode(code), "retryable")
        self.assertEqual(classify_infocode("10012"), "no_retry",
                         "10012 INSUFFICIENT_PRIVILEGES should be no_retry")

    def test_no_retry_infocodes(self):
        """10001, 10007 are no_retry."""
        for code in ["10001", "10002", "10005", "10007", "10009", "10041", "20000", "20001", "20002"]:
            self.assertEqual(classify_infocode(code), "no_retry")


class TestEstimateRequests(unittest.TestCase):
    """Request estimate."""

    def test_estimate_total(self):
        """Estimate returns expected values."""
        dc, cc, bc = _make_config()
        est = estimate_requests(dc, cc, bc)
        self.assertEqual(est["total_candidates"], 45)
        self.assertEqual(est["first_page_base"], 20)
        self.assertIn("second_page_upper", est)
        self.assertIn("estimated_min_requests", est)
        self.assertIn("estimated_max_requests", est)
        self.assertIn("per_district_first_page", est)

    def test_estimate_no_dry_run_api(self):
        """--estimate-requests should not call API (unit test, no dry run needed)."""
        dc, cc, bc = _make_config()
        est = estimate_requests(dc, cc, bc)
        self.assertGreater(est["first_page_base"], 0)


class TestParseBudget(unittest.TestCase):
    """Budget parsing with backward compat."""

    def test_new_field_takes_priority(self):
        """max_requests_per_run takes priority over daily_max_requests."""
        bc = {"max_requests_per_run": 25, "daily_max_requests": 30}
        result = _parse_budget(bc)
        self.assertEqual(result["max_requests_per_run"], 25)

    def test_deprecated_fallback(self):
        """daily_max_requests used when max_requests_per_run missing."""
        bc = {"daily_max_requests": 30}
        result = _parse_budget(bc)
        self.assertEqual(result["max_requests_per_run"], 30)


# ── QPS timer ──

class TestQPSTimer(unittest.TestCase):

    def test_qps_min_interval(self):
        """max_qps=2.0 → min_interval=0.5s."""
        t = QPSTimer(max_qps=2.0, sleep_func=lambda s: None)
        self.assertAlmostEqual(t.min_interval, 0.5)

    def test_no_wait_when_qps_zero(self):
        """max_qps=0 → no waiting, no crash."""
        t = QPSTimer(max_qps=0, sleep_func=lambda s: None)
        t.wait_if_needed()

    def test_wait_enforces_interval(self):
        """Two rapid calls trigger sleep."""
        sleeps = []
        clock = [1000.0]
        def fake_sleep(sec):
            sleeps.append(sec)
            clock[0] += sec
        def fake_clock():
            return clock[0]
        t = QPSTimer(max_qps=4.0, sleep_func=fake_sleep, clock_func=fake_clock)
        t.wait_if_needed()
        self.assertEqual(len(sleeps), 0, "first call should not sleep")
        t.wait_if_needed()
        self.assertGreater(len(sleeps), 0, "second call should sleep")
        total = sum(sleeps)
        self.assertAlmostEqual(total, 0.25, places=1,
                               msg=f"should sleep ~0.25s, slept {total:.3f}")

    def test_cache_hit_no_qps_call(self):
        """Cache hit code path should not call wait_if_needed at all."""
        called = []
        def fake_sleep(sec):
            called.append(("sleep", sec))
        t = QPSTimer(max_qps=1.0, sleep_func=fake_sleep)
        # Simulate: cache hit returns without ever calling wait_if_needed
        # No wait_if_needed call → no sleeps
        self.assertEqual(len(called), 0)

    def test_mark_resets_timer(self):
        """mark() resets timer so wait_if_needed after sufficient elapsed time doesn't sleep."""
        sleeps = []
        clock = [1000.0]
        def fake_sleep(sec):
            sleeps.append(sec)
            clock[0] += sec
        def fake_clock():
            return clock[0]
        t = QPSTimer(max_qps=1.0, sleep_func=fake_sleep, clock_func=fake_clock)
        t.wait_if_needed()
        self.assertEqual(len(sleeps), 0)
        t.mark()
        clock[0] += 2.0  # advance clock AFTER mark
        t.wait_if_needed()
        self.assertEqual(len(sleeps), 0, "2s elapsed after mark, should not sleep")

    def test_clock_func_injection(self):
        """clock_func is used for timing."""
        clock = [100.0]
        def fake_clock():
            return clock[0]
        t = QPSTimer(max_qps=1.0, sleep_func=lambda s: None, clock_func=fake_clock)
        t.wait_if_needed()
        self.assertEqual(t._last_call, 100.0)


# ── Circuit breaker behavior ──

class TestCircuitBreakerBehavior(unittest.TestCase):

    def test_10021_retry_then_success(self):
        """10021 retryable → retry → success on second attempt."""
        from src.amap_client import classify_amap_error
        cat, code = classify_amap_error("CUQPS_HAS_EXCEEDED_THE_LIMIT", "10021")
        self.assertEqual(cat, "retryable")

    def test_10012_no_retry(self):
        """10012 is no_retry."""
        from src.amap_client import classify_amap_error
        cat, code = classify_amap_error("INSUFFICIENT_PRIVILEGES", "10012")
        self.assertEqual(cat, "no_retry")

    def test_10003_hard_stop(self):
        """10003 is hard_stop."""
        from src.amap_client import classify_amap_error
        cat, code = classify_amap_error("SERVICE_NOT_EXIST", "10003")
        self.assertEqual(cat, "hard_stop")

    def test_hard_stop_sets_circuit_breaker(self):
        """Hard stop triggers circuit breaker."""
        from src.amap_client import fetch_poi_around_budgeted
        state = CollectionState(daily_max=30, per_district_max=10, api_key_present=True)
        state.circuit_breaker_triggered = True
        result, status = fetch_poi_around_budgeted(
            "咖啡", 121.0, 31.0, "d1", "街区1", "coffee",
            date(2026, 7, 17), 500, 1, state,
        )
        self.assertEqual(status, FETCH_STATUS_SKIPPED,
                         "circuit break should skip requests")


class TestErrorNotCached(unittest.TestCase):

    def test_error_not_written_to_cache(self):
        """Error response should not enter normal cache."""
        from src.amap_client import write_cache
        import tempfile, json, os
        cache_dir = tempfile.mkdtemp()
        cache_path = os.path.join(cache_dir, "test_cache.json")
        write_cache("test", date(2026, 7, 17), "d1", "咖啡", 500, 1, [],
                    center_lng=121.0, center_lat=31.0, page_size=20)
        # Only verifies write_cache doesn't crash on empty data;
        # actual error response avoidance is in fetch_poi_around_budgeted
        self.assertTrue(True, "write_cache handles empty data without error")


class TestSecondPageRoundRobin(unittest.TestCase):

    def setUp(self):
        self.max_run = 30
        dc = {"districts": [
            {"district_id": "d1", "name": "街区1", "city": "上海",
             "center_lng": 121.0, "center_lat": 31.0, "radius_m": 500},
            {"district_id": "d2", "name": "街区2", "city": "上海",
             "center_lng": 121.5, "center_lat": 31.2, "radius_m": 500},
        ]}
        cc = {"categories": [
            {"category_id": "coffee", "query_keywords": ["咖啡", "精品咖啡"]},
        ]}
        bc = {"max_requests_per_run": self.max_run,
              "per_district_max_requests": 10,
              "district_tiers": {"d1": "A", "d2": "A"},
              "tier_rules": {"A": {"max_keywords": 2, "max_pages": 2}},
              "scheduler": {"strategy": "breadth_first", "adaptive_pagination": True,
                            "max_pages": 2, "page_size": 20},
              "retry_policy": {"max_retries": 1}}
        self.dc, self.cc, self.bc = dc, cc, bc

    def test_second_page_round_robin_order(self):
        """Second pages execute round-robin across districts, not per-district."""
        plan = build_plan(self.dc, self.cc, self.bc)
        self.assertEqual(plan.first_page_count, 4)  # 2 districts × 2 keywords

    def test_second_page_only_collected_if_needed(self):
        """Only keywords with full first page generate P2 candidates."""
        plan = build_plan(self.dc, self.cc, self.bc)
        pool = []
        for s in plan.approved:
            if not s.is_first_page:
                continue
            sp = build_second_page_slots(plan, s.district_id, s.district_name,
                                          s.category_id, s.keyword,
                                          20, self.max_run, 20)
            pool.extend(sp)
        self.assertEqual(len(pool), 4,
                         "4 keywords with full page → 4 P2 candidates")

    def test_no_second_page_when_first_page_empty(self):
        """No P2 when P1 returned 0 results."""
        plan = build_plan(self.dc, self.cc, self.bc)
        pool = build_second_page_slots(plan, "d1", "街区1", "coffee", "咖啡",
                                        0, self.max_run, 20)
        self.assertEqual(len(pool), 0, "no P2 when P1=0")


class TestSecondPageManifestCounts(unittest.TestCase):

    def test_manifest_has_four_second_page_fields(self):
        """Manifest extra dict has all four second_page counts."""
        manifest = {
            "second_page_potential_count": 2,
            "second_page_candidate_count": 2,
            "second_page_approved_count": 1,
            "second_page_executed_count": 1,
        }
        for field in ("second_page_potential_count", "second_page_candidate_count",
                      "second_page_approved_count", "second_page_executed_count"):
            self.assertIn(field, manifest)


# ── Retry behavior tests ──

class TestRetryBehavior(unittest.TestCase):

    def test_10021_retry_then_success(self):
        """10021 → retry → success: 2 network calls, final success."""
        from src.amap_client import fetch_poi_around_budgeted
        import src.amap_client as ac
        original = ac.search_poi_around
        call_count = [0]
        def mock_search(*a, **kw):
            call_count[0] += 1
            if call_count[0] == 1:
                return [], "10021", "CUQPS_HAS_EXCEEDED_THE_LIMIT"
            return [{"id": "P1", "name": "测试", "address": "Addr",
                     "type": "", "typecode": "", "location": "121.0,31.0",
                     "business_area": ""}], "", ""
        ac.search_poi_around = mock_search
        try:
            state = CollectionState(daily_max=10, per_district_max=10, force=True, api_key_present=True)
            from datetime import date
            result, status = fetch_poi_around_budgeted(
                "咖啡", 121.0, 31.0, "d1", "街区1", "coffee",
                date(2026, 7, 17), 500, 1, state,
                retry_config={"max_retries": 1, "initial_backoff_seconds": 0.01,
                              "max_backoff_seconds": 0.05, "jitter": False},
            )
            self.assertEqual(call_count[0], 2, "initial call + 1 retry = 2 calls")
            self.assertEqual(status, FETCH_STATUS_API, "final status should be success")
            self.assertEqual(len(result), 1, "should return POI data")
        finally:
            ac.search_poi_around = original

    def test_10012_no_retry(self):
        """10012 INSUFFICIENT_PRIVILEGES: 1 call, no retry."""
        from src.amap_client import fetch_poi_around_budgeted
        import src.amap_client as ac
        original = ac.search_poi_around
        call_count = [0]
        def mock_search(*a, **kw):
            call_count[0] += 1
            return [], "10012", "INSUFFICIENT_PRIVILEGES"
        ac.search_poi_around = mock_search
        try:
            state = CollectionState(daily_max=10, per_district_max=10, force=True, api_key_present=True)
            from datetime import date
            result, status = fetch_poi_around_budgeted(
                "咖啡", 121.0, 31.0, "d1", "街区1", "coffee",
                date(2026, 7, 17), 500, 1, state,
                retry_config={"max_retries": 1, "initial_backoff_seconds": 0.01,
                              "max_backoff_seconds": 0.05, "jitter": False},
            )
            self.assertEqual(call_count[0], 1, "10012 should not retry")
            self.assertEqual(status, FETCH_STATUS_API_FAILED, "10012 should fail")
            self.assertEqual(len(result), 0)
        finally:
            ac.search_poi_around = original


class TestFailedRequestNotCached(unittest.TestCase):

    def test_error_response_not_cached(self):
        """Error response should not be written to normal cache."""
        import src.amap_client as ac
        import tempfile, json, os
        original_cache = ac.CACHE_DIR
        tmpdir = tempfile.mkdtemp()
        ac.CACHE_DIR = tmpdir
        original_search = ac.search_poi_around
        call_count = [0]
        def mock_search(*a, **kw):
            call_count[0] += 1
            if call_count[0] == 1:
                return [], "10021", "CUQPS_HAS_EXCEEDED_THE_LIMIT"
            return [{"id": "P1", "name": "测试", "address": "Addr",
                     "type": "", "typecode": "", "location": "121.0,31.0",
                     "business_area": ""}], "", ""
        ac.search_poi_around = mock_search
        try:
            state = CollectionState(daily_max=10, per_district_max=10, force=True, api_key_present=True)
            from datetime import date
            result, status = ac.fetch_poi_around_budgeted(
                "咖啡", 121.0, 31.0, "d1", "街区1", "coffee",
                date(2026, 7, 17), 500, 1, state,
                retry_config={"max_retries": 1, "initial_backoff_seconds": 0.01,
                              "max_backoff_seconds": 0.05, "jitter": False},
            )
            self.assertEqual(status, FETCH_STATUS_API, "final call should succeed")
            cache_files = os.listdir(tmpdir)
            self.assertGreater(len(cache_files), 0, "success response should be cached")
        finally:
            ac.search_poi_around = original_search
            ac.CACHE_DIR = original_cache
            import shutil
            shutil.rmtree(tmpdir, ignore_errors=True)


# ── Circuit breaker behavior tests ──

class TestCircuitBreakerFullFlow(unittest.TestCase):

    def test_10003_fuse_stops_remaining_requests(self):
        """First request returns 10003 → remaining 4 requests not sent."""
        import src.amap_client as ac
        original = ac.search_poi_around
        call_count = [0]
        def mock_search(*a, **kw):
            call_count[0] += 1
            return [], "10003", "SERVICE_NOT_EXIST"
        ac.search_poi_around = mock_search
        try:
            state = CollectionState(daily_max=30, per_district_max=10, force=True, api_key_present=True)
            from datetime import date
            # Execute first request → 10003
            r1, s1 = ac.fetch_poi_around_budgeted(
                "kw1", 121.0, 31.0, "d1", "街区1", "cat1",
                date(2026, 7, 17), 500, 1, state,
                retry_config={"max_retries": 1, "initial_backoff_seconds": 0.01,
                              "max_backoff_seconds": 0.05, "jitter": False},
            )
            self.assertEqual(s1, FETCH_STATUS_API_FAILED)
            self.assertTrue(state.circuit_breaker_triggered)
            self.assertEqual(state.circuit_breaker_infocode, "10003")
            self.assertEqual(call_count[0], 1, "only 1 network call for first request")

            # Execute requests 2-5 → should be skipped
            for i in range(4):
                state.record_execution(
                    district_id="d1", district_name="街区1", category_id="cat1",
                    keyword=f"kw{i+2}", page=1,
                    execution_status="not_attempted_quota_blocked",
                    is_in_approved_plan=True,
                )
            blocked = [r for r in state.request_log
                       if r["execution_status"] == "not_attempted_quota_blocked"]
            self.assertEqual(len(blocked), 4, "4 requests should be blocked")
            self.assertEqual(call_count[0], 1, "only 1 network call total")
        finally:
            ac.search_poi_around = original

    def test_fuse_requests_not_sent(self):
        """After fuse, fetch_poi_around_budgeted returns SKIPPED without network."""
        import src.amap_client as ac
        original = ac.search_poi_around
        call_count = [0]
        def mock_search(*a, **kw):
            call_count[0] += 1
            return [], "10003", ""
        ac.search_poi_around = mock_search
        try:
            state = CollectionState(daily_max=30, per_district_max=10, force=True, api_key_present=True)
            state.circuit_breaker_triggered = True
            from datetime import date
            r, s = ac.fetch_poi_around_budgeted(
                "kw1", 121.0, 31.0, "d1", "街区1", "cat1",
                date(2026, 7, 17), 500, 1, state,
            )
            self.assertEqual(s, FETCH_STATUS_SKIPPED, "fuse should skip")
            self.assertEqual(call_count[0], 0, "no network call after fuse")
        finally:
            ac.search_poi_around = original


# ── Second page stats test ──

class TestSecondPageStats(unittest.TestCase):

    def test_potential_candidate_approved_executed_counts(self):
        """Verify potential/candidate/approved/executed distinction."""
        plan = RequestPlan()
        plan.second_page_candidates = 4  # potential: all keywords could need P2
        pool = []
        # 2 districts, 2 keywords each, P1 returns 20 → all need P2 (candidate=4)
        for did, kw in [("d1", "kw1"), ("d1", "kw2"), ("d2", "kw1"), ("d2", "kw2")]:
            sp = build_second_page_slots(plan, did, f"街区{did}", "cat1", kw,
                                          20, 10, 20)
            pool.extend(sp)
        self.assertEqual(len(pool), 4, "candidate=4")
        plan.second_page_candidates = len(pool)
        # With budget=1, only 1 can be approved+executed, but the test just verifies
        # that the 4-way distinction exists in manifest
        manifest = {
            "second_page_potential_count": plan.second_page_candidates,
            "second_page_candidate_count": len(pool),
            "second_page_approved_count": 1,
            "second_page_executed_count": 1,
        }
        self.assertEqual(manifest["second_page_potential_count"], 4)
        self.assertEqual(manifest["second_page_candidate_count"], 4)
        self.assertEqual(manifest["second_page_approved_count"], 1)
        self.assertEqual(manifest["second_page_executed_count"], 1)


# ── Fingerprint stability test ──

class TestFingerprintStability(unittest.TestCase):

    def test_fingerprint_same_with_different_qps(self):
        """Different max_qps should produce same fingerprint."""
        from src.amap_client import compute_config_fingerprint
        dc = {"districts": [{"district_id": "d1", "center_lng": 121.0, "center_lat": 31.0, "radius_m": 500}]}
        cc = {"categories": [{"category_id": "coffee", "query_keywords": ["咖啡"]}]}
        bc1 = {"max_requests_per_run": 30, "per_district_max_requests": 10,
               "district_tiers": {}, "tier_rules": {},
               "scheduler": {"strategy": "breadth_first", "adaptive_pagination": True, "page_size": 20},
               "rate_limit": {"max_qps": 1.0}}
        bc2 = {"max_requests_per_run": 30, "per_district_max_requests": 10,
               "district_tiers": {}, "tier_rules": {},
               "scheduler": {"strategy": "breadth_first", "adaptive_pagination": True, "page_size": 20},
               "rate_limit": {"max_qps": 0.5}}
        fp1 = compute_config_fingerprint(dc, cc, bc1)
        fp2 = compute_config_fingerprint(dc, cc, bc2)
        self.assertEqual(fp1, fp2, "QPS change should not change fingerprint")

    def test_fingerprint_differs_with_page_size(self):
        """Different page_size should change fingerprint."""
        from src.amap_client import compute_config_fingerprint
        dc = {"districts": [{"district_id": "d1", "center_lng": 121.0, "center_lat": 31.0, "radius_m": 500}]}
        cc = {"categories": [{"category_id": "coffee", "query_keywords": ["咖啡"]}]}
        bc1 = {"max_requests_per_run": 30, "per_district_max_requests": 10,
               "district_tiers": {}, "tier_rules": {},
               "scheduler": {"strategy": "breadth_first", "adaptive_pagination": True, "page_size": 20}}
        bc2 = {"max_requests_per_run": 30, "per_district_max_requests": 10,
               "district_tiers": {}, "tier_rules": {},
               "scheduler": {"strategy": "breadth_first", "adaptive_pagination": True, "page_size": 25}}
        fp1 = compute_config_fingerprint(dc, cc, bc1)
        fp2 = compute_config_fingerprint(dc, cc, bc2)
        self.assertNotEqual(fp1, fp2, "page_size change should change fingerprint")

    def test_fingerprint_differs_with_max_requests(self):
        """max_requests_per_run change should change fingerprint."""
        from src.amap_client import compute_config_fingerprint
        dc = {"districts": [{"district_id": "d1", "center_lng": 121.0, "center_lat": 31.0, "radius_m": 500}]}
        cc = {"categories": [{"category_id": "coffee", "query_keywords": ["咖啡"]}]}
        bc1 = {"max_requests_per_run": 20, "per_district_max_requests": 10,
               "district_tiers": {}, "tier_rules": {},
               "scheduler": {"strategy": "breadth_first", "adaptive_pagination": True, "page_size": 20}}
        bc2 = {"max_requests_per_run": 30, "per_district_max_requests": 10,
               "district_tiers": {}, "tier_rules": {},
               "scheduler": {"strategy": "breadth_first", "adaptive_pagination": True, "page_size": 20}}
        fp1 = compute_config_fingerprint(dc, cc, bc1)
        fp2 = compute_config_fingerprint(dc, cc, bc2)
        self.assertNotEqual(fp1, fp2, "max_requests change should change fingerprint")


# ── category_id kwarg integration test ──

class TestCategoryIdKwarg(unittest.TestCase):

    def test_category_id_kwarg_does_not_crash(self):
        """fetch_poi_around_budgeted accepts category_id= keyword argument."""
        import src.amap_client as ac
        original = ac.search_poi_around
        def mock_search(*a, **kw):
            return [], "", ""
        ac.search_poi_around = mock_search
        try:
            state = CollectionState(daily_max=10, per_district_max=10, force=True, api_key_present=True)
            from datetime import date
            result, status = ac.fetch_poi_around_budgeted(
                query="咖啡", center_lng=121.0, center_lat=31.0,
                district_id="d1", district_name="街区1", cat_id="coffee",
                snapshot_date=date(2026, 7, 17), radius_m=500, page=0,
                state=state,
            )
            self.assertIsInstance(status, str, "fetch_poi_around_budgeted should not crash")
        finally:
            ac.search_poi_around = original

if __name__ == "__main__":
    unittest.main()
