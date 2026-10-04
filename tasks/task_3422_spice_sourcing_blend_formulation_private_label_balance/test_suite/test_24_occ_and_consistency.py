"""Optimistic concurrency on line scheduling and immediate read-after-write."""
import pytest
from test_helpers import (
    api_client, validate_success, validate_error, ApiErrorId, TEST_USERS,
    setup_accepted_lots, create_active_formula, create_committed_blend_run,
    create_line, create_supplier, create_received_lot, post_test, get_lot,
    production_run_payload,
)


class TestOptimisticConcurrency:
    def test_occ_stale_line_version_rejected_then_fresh_succeeds(self, api):
        """PRD §2.7: "The scheduling request must carry
        `expected_line_version` — a non-optional input field holding the
        `version` of the target production line as the client last observed
        it. If the line's current `version` does not equal
        `expected_line_version` at the moment the request is evaluated, the
        schedule is rejected with `ERR_STALE_VERSION` (HTTP 412)". PRD §2.7:
        "A successful scheduling increments the line's `version` by 1, so
        every scheduling invalidates previously observed versions."

        Version 1 at creation; the first schedule succeeds; replaying the
        stale version is rejected; re-reading (version 2) lets the identical
        payload succeed; two successful schedules land the version on 3.

        Design: Corner/cross_cutting_complexity_layers/occ_stale_line_version_rejected_then_fresh_succeeds
        """
        supplier, lots = setup_accepted_lots(costs=(100, 100, 100))
        formula = create_active_formula("OCC-1")
        br = create_committed_blend_run(formula["id"], "COST_MIN", 10)
        line = create_line(name="Line-OCC")
        v1 = line["version"]
        assert v1 == 1
        ps = TEST_USERS["production_scheduler_headers"]
        resp = api_client.create_production_run(
            production_run_payload(line["id"], formula["id"], br["id"], 10,
                                   "2026-09-24T08:00:00Z",
                                   "2026-09-24T10:00:00Z", v1), ps)
        validate_success(resp, 201)
        resp = api_client.create_production_run(
            production_run_payload(line["id"], formula["id"], br["id"], 10,
                                   "2026-09-24T10:00:00Z",
                                   "2026-09-24T12:00:00Z", v1), ps)
        validate_error(resp, ApiErrorId.ERR_STALE_VERSION)
        assert resp.status_code == 412
        v2 = validate_success(api_client.get_line(line["id"], ps), 200)["version"]
        assert v2 == v1 + 1
        resp = api_client.create_production_run(
            production_run_payload(line["id"], formula["id"], br["id"], 10,
                                   "2026-09-24T10:00:00Z",
                                   "2026-09-24T12:00:00Z", v2), ps)
        validate_success(resp, 201)
        v3 = validate_success(api_client.get_line(line["id"], ps), 200)["version"]
        assert v3 == v2 + 1


class TestImmediateConsistency:
    def test_immediate_read_after_write_consistency(self, api):
        """PRD §2.11: "the system is immediately consistent with no
        eventual-convergence window." PRD §2.4: "an integer `version` that the
        server increments by exactly 1 on every mutation of the resource; the
        current value is always returned in the resource representation."
        PRD §3.2: "The very first test recorded on a `RECEIVED` lot moves it
        to `IN_TEST`."

        A created lot reads back identically on the very next GET; the
        test-post mutation is visible (status IN_TEST, version bumped by
        exactly 1) on the immediately following read.

        Design: Corner/consistency_model/immediate_read_after_write_consistency
        """
        supplier = create_supplier()
        lot = create_received_lot(supplier["id"], spice_code="CINNAMON",
                                  origin_region="Galle", quantity_kg=25,
                                  flavor_intensity_units=65.0,
                                  moisture_pct=9.0, cost_per_kg_cents=400)
        read1 = validate_success(api_client.get_lot(
            lot["id"], TEST_USERS["supply_planner_headers"]), 200)
        assert read1["quantity_kg"] == pytest.approx(25.0)
        assert read1["status"] == "RECEIVED"
        assert read1["version"] == 1
        post_test(lot["id"], "MICRO", 1000)
        read2 = validate_success(api_client.get_lot(
            lot["id"], TEST_USERS["supply_planner_headers"]), 200)
        assert read2["status"] == "IN_TEST"
        assert read2["version"] == read1["version"] + 1
