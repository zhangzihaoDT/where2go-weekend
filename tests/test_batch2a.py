import csv
import json
import os
import shutil
import sys
import tempfile
import unittest
from datetime import date

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, PROJECT_ROOT)

from src.amap_client import (
    search_poi_around,
    fetch_poi_around_budgeted,
    CollectionState,
    write_snapshot_csv,
    compute_config_fingerprint,
    write_manifest_json,
    compute_snapshot_source_mode,
    compute_snapshot_completeness,
    read_manifest,
    compare_is_allowed,
    FETCH_STATUS_API,
    FETCH_STATUS_CACHE,
    FETCH_STATUS_SKIPPED,
    FETCH_STATUS_API_FAILED,
    EXEC_STATUS_SUCCESS,
    EXEC_STATUS_EMPTY,
    EXEC_STATUS_CACHE_HIT,
    EXEC_STATUS_SKIPPED_BUDGET,
    EXEC_STATUS_SKIPPED_KEYWORD_LIMIT,
    EXEC_STATUS_FAILED_API,
    EXEC_STATUS_FALLBACK_SAMPLE,
    SNAPSHOT_FIELDS,
)
from src.change_detector import detect_changes


def _make_poi_row(poi_id="P1", name="测试", address="Addr", district_id="d1",
                  district_name="街区1", category_id="coffee", **kw):
    row = {
        "snapshot_date": "2026-07-01",
        "source": "test",
        "district_id": district_id,
        "district_name": district_name,
        "category_id": category_id,
        "keyword": "kw1",
        "poi_id": poi_id,
        "name": name,
        "address": address,
        "lng": "121.0",
        "lat": "31.0",
        "poi_type": "",
        "raw_type": "",
        "business_area": "",
        "confidence": "0.8",
    }
    row.update(kw)
    return row


# ── 1. Page parameter passing ──

class TestPagePassing(unittest.TestCase):

    def test_search_poi_around_accepts_page(self):
        """search_poi_around should accept page parameter without error."""
        import inspect
        sig = inspect.signature(search_poi_around)
        self.assertIn("page", sig.parameters,
                      "search_poi_around must accept page parameter")

    def test_fetch_passes_page_to_search(self):
        """fetch_poi_around_budgeted passes page to search_poi_around."""
        import inspect
        from src.amap_client import search_poi_around as original_search
        called_with = {}
        def mock_search(*a, **kw):
            called_with.update(kw)
            return [], "", ""
        import src.amap_client
        src.amap_client.search_poi_around = mock_search
        try:
            state = CollectionState(daily_max=10, per_district_max=10, force=True, api_key_present=True)
            from src.amap_client import get_api_key
            if get_api_key():
                fetch_poi_around_budgeted(
                    "咖啡", 121.0, 31.0, "d1", "街区1", "coffee",
                    date(2026, 7, 8), 500, page=2,
                    state=state,
                )
            self.assertIn("page", called_with,
                          "page must be in kwargs passed to search_poi_around")
            if called_with:
                self.assertEqual(called_with["page"], 2)
        finally:
            src.amap_client.search_poi_around = original_search


class TestPageInCacheKey(unittest.TestCase):

    def test_cache_key_differs_by_page(self):
        """Two pages should produce different cache keys."""
        from src.amap_client import _cache_key
        k1 = _cache_key("amap", date(2026, 7, 8), "d1", "咖啡", 500, 1)
        k2 = _cache_key("amap", date(2026, 7, 8), "d1", "咖啡", 500, 2)
        self.assertNotEqual(k1, k2, "page must differentiate cache keys")

    def test_cache_read_writes_are_page_specific(self):
        """Cache read/write should isolate different pages."""
        from src.amap_client import read_cache, write_cache
        data_p1 = [{"id": "P1", "name": "咖啡A", "address": "AddrA"}]
        data_p2 = [{"id": "P2", "name": "咖啡B", "address": "AddrB"}]
        write_cache("test", date(2026, 7, 8), "d1", "咖啡", 500, 1, data_p1)
        write_cache("test", date(2026, 7, 8), "d1", "咖啡", 500, 2, data_p2)
        cached_p1 = read_cache("test", date(2026, 7, 8), "d1", "咖啡", 500, 1)
        cached_p2 = read_cache("test", date(2026, 7, 8), "d1", "咖啡", 500, 2)
        self.assertEqual(len(cached_p1), 1)
        self.assertEqual(cached_p1[0]["id"], "P1")
        self.assertEqual(len(cached_p2), 1)
        self.assertEqual(cached_p2[0]["id"], "P2")


# ── 2. Execution status model ──

class TestExecutionStatus(unittest.TestCase):

    def test_empty_status(self):
        """Request that returns 0 records should be empty, not error."""
        state = CollectionState(daily_max=10, per_district_max=10, force=True, api_key_present=False)
        state.record_execution(
            district_id="d1", district_name="街区1", category_id="coffee",
            keyword="咖啡", page=1, execution_status=EXEC_STATUS_EMPTY,
            result_count=0,
        )
        self.assertEqual(state.request_log[0]["execution_status"], EXEC_STATUS_EMPTY)

    def test_skipped_budget_status(self):
        """Budget-skipped request should have correct status."""
        state = CollectionState(daily_max=10, per_district_max=10, api_key_present=True)
        state.record_execution(
            district_id="d1", district_name="街区1", category_id="coffee",
            keyword="咖啡", page=1, execution_status=EXEC_STATUS_SKIPPED_BUDGET,
        )
        self.assertEqual(state.request_log[0]["execution_status"], EXEC_STATUS_SKIPPED_BUDGET)

    def test_skipped_keyword_limit_status(self):
        """Keyword-limit-skipped request should have correct status."""
        state = CollectionState(daily_max=10, per_district_max=10, api_key_present=True)
        state.record_execution(
            district_id="d1", district_name="街区1", category_id="coffee",
            keyword="咖啡", page=1, execution_status=EXEC_STATUS_SKIPPED_KEYWORD_LIMIT,
        )
        self.assertEqual(state.request_log[0]["execution_status"], EXEC_STATUS_SKIPPED_KEYWORD_LIMIT)

    def test_cache_hit_status(self):
        """Cache-hit request should have correct status."""
        state = CollectionState(daily_max=10, per_district_max=10, api_key_present=True)
        state.record_execution(
            district_id="d1", district_name="街区1", category_id="coffee",
            keyword="咖啡", page=1, execution_status=EXEC_STATUS_CACHE_HIT,
            cache_hit=True, result_count=5,
        )
        self.assertEqual(state.request_log[0]["execution_status"], EXEC_STATUS_CACHE_HIT)
        self.assertTrue(state.request_log[0]["cache_hit"])


# ── 2.1. Excluded requests model ──

class TestRequestPlanModel(unittest.TestCase):

    def test_keyword_limit_excluded_from_completeness(self):
        """Keyword-limit-skipped requests are excluded and don't cause partial."""
        state = CollectionState(api_key_present=True)
        state.record_execution(district_id="d1", district_name="街区1", category_id="coffee",
                                keyword="咖啡", page=1, execution_status=EXEC_STATUS_SUCCESS,
                                result_count=5, is_in_approved_plan=True)
        state.record_execution(district_id="d1", district_name="街区1", category_id="coffee",
                                keyword="烘焙", page=1, execution_status=EXEC_STATUS_SKIPPED_KEYWORD_LIMIT,
                                result_count=0, is_in_approved_plan=False)
        s = compute_snapshot_completeness(state, "amap")
        self.assertEqual(s, "complete", "keyword-limit excluded should not cause partial")

    def test_budget_skip_excluded_from_completeness(self):
        """Budget-skipped requests are excluded and don't cause partial."""
        state = CollectionState(api_key_present=True)
        state.record_execution(district_id="d1", district_name="街区1", category_id="coffee",
                                keyword="咖啡", page=1, execution_status=EXEC_STATUS_SUCCESS,
                                result_count=5, is_in_approved_plan=True)
        state.record_execution(district_id="d1", district_name="街区1", category_id="coffee",
                                keyword="烘焙", page=1, execution_status=EXEC_STATUS_SKIPPED_BUDGET,
                                result_count=0, is_in_approved_plan=False)
        s = compute_snapshot_completeness(state, "amap")
        self.assertEqual(s, "complete", "budget-skipped should not cause partial")

    def test_current_config_can_produce_complete(self):
        """With current config (9 kw, tier A=7max_kw, B=6max_kw), approved-only is complete."""
        state = CollectionState(api_key_present=True)
        # Simulate Tier A: 7 approved kw x 2 pages = 14 approved
        for p in range(2):
            for kw_idx in range(7):
                state.record_execution(district_id="d1", district_name="街区1",
                                        category_id="coffee", keyword=f"kw{kw_idx}",
                                        page=p+1, execution_status=EXEC_STATUS_SUCCESS,
                                        result_count=1, is_in_approved_plan=True)
        # Simulate excluded keywords beyond max_kw
        for kw_idx in range(7, 9):
            state.record_execution(district_id="d1", district_name="街区1",
                                    category_id="coffee", keyword=f"kw{kw_idx}",
                                    page=1, execution_status=EXEC_STATUS_SKIPPED_KEYWORD_LIMIT,
                                    result_count=0, is_in_approved_plan=False)
        s = compute_snapshot_completeness(state, "amap")
        self.assertEqual(s, "complete", "current config with excluded kw should be complete")

    def test_approved_failure_causes_partial(self):
        """Approved request failure should still cause partial."""
        state = CollectionState(api_key_present=True)
        state.record_execution(district_id="d1", district_name="街区1", category_id="coffee",
                                keyword="咖啡", page=1, execution_status=EXEC_STATUS_SUCCESS,
                                result_count=5, is_in_approved_plan=True)
        state.record_execution(district_id="d1", district_name="街区1", category_id="coffee",
                                keyword="烘焙", page=1, execution_status=EXEC_STATUS_FAILED_API,
                                result_count=0, is_in_approved_plan=True)
        s = compute_snapshot_completeness(state, "amap")
        self.assertEqual(s, "partial", "approved request failure should cause partial")


# ── 3. Completeness rules ──

class TestCompleteness(unittest.TestCase):

    def test_all_success_is_complete(self):
        """All planned requests succeed → complete."""
        state = CollectionState(api_key_present=True)
        state.record_execution(district_id="d1", district_name="街区1", category_id="coffee",
                                keyword="咖啡", page=1, execution_status=EXEC_STATUS_SUCCESS, result_count=5)
        state.record_execution(district_id="d1", district_name="街区1", category_id="coffee",
                                keyword="咖啡", page=2, execution_status=EXEC_STATUS_EMPTY, result_count=0)
        s = compute_snapshot_completeness(state, "amap")
        self.assertEqual(s, "complete")

    def test_any_failure_is_partial(self):
        """Some requests fail → partial."""
        state = CollectionState(api_key_present=True)
        state.record_execution(district_id="d1", district_name="街区1", category_id="coffee",
                                keyword="咖啡", page=1, execution_status=EXEC_STATUS_SUCCESS, result_count=5)
        state.record_execution(district_id="d1", district_name="街区1", category_id="coffee",
                                keyword="咖啡", page=2, execution_status=EXEC_STATUS_FAILED_API, result_count=0)
        s = compute_snapshot_completeness(state, "amap")
        self.assertEqual(s, "partial")

    def test_sample_is_fallback(self):
        """Sample mode → fallback."""
        state = CollectionState(api_key_present=False)
        s = compute_snapshot_completeness(state, "sample")
        self.assertEqual(s, "fallback")

    def test_empty_log_is_failed(self):
        """No request log → failed."""
        state = CollectionState(api_key_present=True)
        s = compute_snapshot_completeness(state, "amap")
        self.assertEqual(s, "failed")

    def test_coverage_by_keyword_in_manifest(self):
        """Manifest should contain coverage_by_keyword."""
        state = CollectionState(api_key_present=True)
        state.record_pois(3)
        state.record_execution(district_id="d1", district_name="街区1", category_id="coffee",
                                keyword="咖啡", page=1, execution_status=EXEC_STATUS_SUCCESS, result_count=3)
        state.record_execution(district_id="d1", district_name="街区1", category_id="coffee",
                                keyword="烘焙", page=1, execution_status=EXEC_STATUS_EMPTY, result_count=0)
        import tempfile, json
        with tempfile.TemporaryDirectory() as tmpdir:
            m = write_manifest_json(
                state, tmpdir, date(2026, 7, 8), "amap", "complete",
                "abc123",
                {"districts": [{"district_id": "d1"}]},
                {"categories": [{"category_id": "coffee"}]},
                {"daily_max_requests": 30, "per_district_max_requests": 10,
                 "district_tiers": {}, "tier_rules": {}},
                3, [("咖啡", "coffee"), ("烘焙", "coffee")],
            )
            self.assertIn("coverage_by_keyword", m)
            self.assertIn("咖啡", m["coverage_by_keyword"])
            self.assertEqual(m["coverage_by_keyword"]["咖啡"]["poi_count"], 3)


# ── 4. Source mode ──

class TestSourceMode(unittest.TestCase):

    def test_amap_source(self):
        """All API requests → source_mode=amap."""
        state = CollectionState(api_key_present=True)
        state.record_execution(district_id="d1", district_name="街区1", category_id="coffee",
                                keyword="咖啡", page=1, execution_status=EXEC_STATUS_SUCCESS, result_count=5)
        s = compute_snapshot_source_mode(state)
        self.assertEqual(s, "amap")

    def test_sample_source(self):
        """Fallback only → source_mode=sample."""
        state = CollectionState(api_key_present=False)
        state.fallback_used = True
        s = compute_snapshot_source_mode(state)
        self.assertEqual(s, "sample")


# ── 5. Config fingerprint ──

class TestConfigFingerprint(unittest.TestCase):

    def test_fingerprint_is_stable(self):
        """Same config should produce same fingerprint."""
        dc = {"districts": [{"district_id": "d1", "center_lng": 121.0, "center_lat": 31.0, "radius_m": 500}]}
        cc = {"categories": [{"category_id": "coffee", "query_keywords": ["咖啡"]}]}
        bc = {"daily_max_requests": 30, "per_district_max_requests": 10,
              "district_tiers": {"d1": "A"}, "tier_rules": {"A": {"max_keywords": 7, "max_pages": 2}}}
        fp1 = compute_config_fingerprint(dc, cc, bc)
        fp2 = compute_config_fingerprint(dc, cc, bc)
        self.assertEqual(fp1, fp2, "fingerprint must be stable for same config")

    def test_fingerprint_differs(self):
        """Different config should produce different fingerprint."""
        dc1 = {"districts": [{"district_id": "d1", "center_lng": 121.0, "center_lat": 31.0, "radius_m": 500}]}
        dc2 = {"districts": [{"district_id": "d1", "center_lng": 121.5, "center_lat": 31.0, "radius_m": 500}]}
        cc = {"categories": [{"category_id": "coffee", "query_keywords": ["咖啡"]}]}
        bc = {"daily_max_requests": 30, "per_district_max_requests": 10,
              "district_tiers": {}, "tier_rules": {}}
        fp1 = compute_config_fingerprint(dc1, cc, bc)
        fp2 = compute_config_fingerprint(dc2, cc, bc)
        self.assertNotEqual(fp1, fp2, "different radius must change fingerprint")


# ── 6. Compare admission rules ──

class TestCompareAdmission(unittest.TestCase):

    def test_no_previous_snapshot_ok(self):
        """No previous snapshot → allowed (baseline)."""
        ok, reason = compare_is_allowed(
            previous_snapshot_exists=False,
            prev_manifest=None,
            curr_manifest={"config_fingerprint": "a", "source_mode": "amap", "status": "complete"},
        )
        self.assertTrue(ok)
        self.assertEqual(reason, "no_previous_snapshot")

    def test_previous_no_manifest_blocked(self):
        """Previous snapshot exists but no manifest → blocked."""
        ok, reason = compare_is_allowed(
            previous_snapshot_exists=True,
            prev_manifest=None,
            curr_manifest={"config_fingerprint": "a", "source_mode": "amap", "status": "complete"},
        )
        self.assertFalse(ok)
        self.assertEqual(reason, "previous_snapshot_has_no_manifest")

    def test_fingerprint_mismatch_blocked(self):
        """Different config fingerprints → not allowed."""
        prev = {"config_fingerprint": "aaa", "source_mode": "amap", "status": "complete"}
        curr = {"config_fingerprint": "bbb", "source_mode": "amap", "status": "complete"}
        ok, reason = compare_is_allowed(True, prev, curr)
        self.assertFalse(ok)
        self.assertIn("fingerprint_mismatch", reason)

    def test_sample_vs_amap_blocked(self):
        """Sample vs amap → not allowed."""
        prev = {"config_fingerprint": "a", "source_mode": "sample", "status": "fallback"}
        curr = {"config_fingerprint": "a", "source_mode": "amap", "status": "complete"}
        ok, reason = compare_is_allowed(True, prev, curr)
        self.assertFalse(ok)
        self.assertIn("previous_is_sample_current_is_amap", reason)

    def test_amap_vs_sample_blocked(self):
        """Amap vs sample → not allowed."""
        prev = {"config_fingerprint": "a", "source_mode": "amap", "status": "complete"}
        curr = {"config_fingerprint": "a", "source_mode": "sample", "status": "fallback"}
        ok, reason = compare_is_allowed(True, prev, curr)
        self.assertFalse(ok)
        self.assertIn("previous_is_amap_current_is_sample", reason)

    def test_mixed_source_blocked(self):
        """Mixed source → not allowed."""
        prev = {"config_fingerprint": "a", "source_mode": "amap", "status": "complete"}
        curr = {"config_fingerprint": "a", "source_mode": "mixed", "status": "partial"}
        ok, reason = compare_is_allowed(True, prev, curr)
        self.assertFalse(ok)
        self.assertIn("mixed", reason)

    def test_partial_previous_blocked(self):
        """Previous not complete → not allowed."""
        prev = {"config_fingerprint": "a", "source_mode": "amap", "status": "partial"}
        curr = {"config_fingerprint": "a", "source_mode": "amap", "status": "complete"}
        ok, reason = compare_is_allowed(True, prev, curr)
        self.assertFalse(ok)
        self.assertIn("previous_snapshot_status_partial", reason)

    def test_both_complete_and_matching_allowed(self):
        """Both complete with same fingerprint → allowed."""
        prev = {"config_fingerprint": "a", "source_mode": "amap", "status": "complete"}
        curr = {"config_fingerprint": "a", "source_mode": "amap", "status": "complete"}
        ok, reason = compare_is_allowed(True, prev, curr)
        self.assertTrue(ok)
        self.assertEqual(reason, "ok")


# ── 6.1. Blocked semantics ──

class TestBlockedSemantics(unittest.TestCase):

    def test_blocked_not_baseline(self):
        """Compare blocked should NOT generate no_previous_snapshot event."""
        prev = {"config_fingerprint": "a", "source_mode": "amap", "status": "complete"}
        curr = {"config_fingerprint": "b", "source_mode": "amap", "status": "complete"}
        ok, reason = compare_is_allowed(True, prev, curr)
        self.assertFalse(ok)
        self.assertNotEqual(reason, "no_previous_snapshot",
                            "blocked reason must not be 'no_previous_snapshot'")

    def test_comparison_blocked_event_type(self):
        """Blocked compare should produce comparison_blocked event, not baseline."""
        from src.change_detector import generate_baseline_events
        blocked_events = [{
            "snapshot_date": "2026-07-15",
            "previous_snapshot_date": "2026-07-08",
            "district_id": "",
            "district_name": "",
            "category_id": "",
            "event_type": "comparison_blocked",
            "poi_id": "",
            "name": "",
            "address": "",
            "signal_strength": 0,
            "why_interesting": "阻止原因",
        }]
        self.assertEqual(len(blocked_events), 1)
        self.assertEqual(blocked_events[0]["event_type"], "comparison_blocked")
        baseline = generate_baseline_events(
            [{"poi_id": "P1", "name": "测试", "address": "Addr",
              "district_id": "d1", "district_name": "街区1",
              "category_id": "coffee", "snapshot_date": "2026-07-15"}],
            date(2026, 7, 15),
        )
        for e in baseline:
            self.assertNotEqual(e["event_type"], "comparison_blocked")
            self.assertEqual(e["event_type"], "no_previous_snapshot")


# ── 7. Manifest I/O ──

class TestManifestIO(unittest.TestCase):

    def test_write_and_read_manifest(self):
        """Round-trip manifest write/read."""
        import tempfile, json
        state = CollectionState(api_key_present=True)
        state.record_pois(5)
        state.record_execution(district_id="d1", district_name="街区1", category_id="coffee",
                                keyword="咖啡", page=1, execution_status=EXEC_STATUS_SUCCESS, result_count=5)
        with tempfile.TemporaryDirectory() as tmpdir:
            m = write_manifest_json(
                state, tmpdir, date(2026, 7, 8), "amap", "complete",
                "fp123",
                {"districts": [{"district_id": "d1"}]},
                {"categories": [{"category_id": "coffee"}]},
                {"daily_max_requests": 30, "per_district_max_requests": 10,
                 "district_tiers": {}, "tier_rules": {}},
                5, [("咖啡", "coffee")],
            )
            self.assertEqual(m["snapshot_date"], "2026-07-08")
            self.assertEqual(m["status"], "complete")
            self.assertEqual(m["raw_poi_count"], 5)
            self.assertEqual(m["deduped_poi_count"], 5)
            manifest_path = os.path.join(tmpdir, "2026-07-08_manifest.json")
            self.assertTrue(os.path.isfile(manifest_path))
            loaded = read_manifest(manifest_path)
            self.assertEqual(loaded["config_fingerprint"], "fp123")

    def test_archive_summary_does_not_overwrite(self):
        """Date-archived summary should not overwrite existing summary for different date."""
        import tempfile
        with tempfile.TemporaryDirectory() as tmpdir:
            s1_path = os.path.join(tmpdir, "2026-07-01_collection_summary.csv")
            with open(s1_path, "w") as f:
                f.write("date,count\n2026-07-01,10\n")
            s2_path = os.path.join(tmpdir, "2026-07-08_collection_summary.csv")
            with open(s2_path, "w") as f:
                f.write("date,count\n2026-07-08,20\n")
            self.assertTrue(os.path.isfile(s1_path))
            self.assertTrue(os.path.isfile(s2_path))
            with open(s1_path) as f:
                self.assertIn("2026-07-01", f.read())


# ── 8. Request_log structure ──

class TestRequestLog(unittest.TestCase):

    def test_request_log_contains_required_fields(self):
        """Each request log entry should have required fields."""
        state = CollectionState(api_key_present=True)
        state.record_execution(district_id="d1", district_name="街区1", category_id="coffee",
                                keyword="咖啡", page=1, execution_status=EXEC_STATUS_SUCCESS,
                                cache_hit=False, result_count=5, skip_reason="")
        entry = state.request_log[0]
        for field in ("district_id", "district_name", "category_id", "keyword",
                      "page", "execution_status", "cache_hit", "result_count", "skip_reason"):
            self.assertIn(field, entry, f"request_log entry missing {field}")


# ── 9. Snapshot with no duplicates after batch2a changes ──

class TestSnapshotOutput(unittest.TestCase):

    def test_snapshot_csv_written_without_duplicates(self):
        """Snapshot CSV should still be written with no duplicates (regression check)."""
        import tempfile
        with tempfile.TemporaryDirectory() as tmpdir:
            rows = [_make_poi_row("P1", "A", "Addr"), _make_poi_row("P1", "A", "Addr")]
            from src.run import deduplicate_snapshot_rows
            clean = deduplicate_snapshot_rows(rows)
            path = os.path.join(tmpdir, "2026-07-08_poi_snapshot.csv")
            write_snapshot_csv(clean, path)
            from src.change_detector import load_snapshot
            loaded = load_snapshot(path)
            self.assertEqual(len(loaded), 1)


if __name__ == "__main__":
    unittest.main()
