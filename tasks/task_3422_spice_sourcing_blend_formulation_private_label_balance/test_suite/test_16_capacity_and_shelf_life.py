"""Boundary thresholds: surge-week pool switch and the 75% shelf-life gate."""
from test_helpers import (
    api_client, validate_success, validate_error, ApiErrorId, TEST_USERS,
    setup_accepted_lots, create_active_formula, create_committed_blend_run,
    create_line, schedule_run, complete_run, batch_for_run, set_clock,
    reservation_payload,
)


class TestSurgePoolBoundary:
    def test_surge_pool_multiplier_week43_vs_week44(self, api):
        """PRD §3.5: "the surge multiplier is 1.25 for ISO weeks 44 through 52
        inclusive — the holiday demand spike — and 1.0 for every other week,
        with ISO weeks counted Monday-start under ISO-8601." PRD §3.8: "If
        honoring the reservation would push any intersected week's pool below
        zero, the create is rejected with `ERR_RESERVATION_OVER_COMMIT` (HTTP
        409)".

        A 6000 kg reservation fails against week 43's 1000*5 = 5000 kg pool
        and succeeds against week 44's floor(1000*5*1.25) = 6250 kg pool — the
        multiplier switches exactly at ISO week 44.

        Design: Corner/calculations/surge_pool_multiplier_week43_vs_week44
        """
        line = create_line(name="Line-43")
        resp = api_client.create_reservation(
            reservation_payload(line["id"], "2026-10-19T00:00:00Z",
                                "2026-10-26T00:00:00Z", 6000),
            TEST_USERS["production_scheduler_headers"])
        validate_error(resp, ApiErrorId.ERR_RESERVATION_OVER_COMMIT)
        resp = api_client.create_reservation(
            reservation_payload(line["id"], "2026-10-26T00:00:00Z",
                                "2026-11-02T00:00:00Z", 6000),
            TEST_USERS["production_scheduler_headers"])
        validate_success(resp, 201)


def _setup_two_batches():
    supplier, lots = setup_accepted_lots(costs=(100, 100, 100))
    formula = create_active_formula("DAT-1")
    br1 = create_committed_blend_run(formula["id"], "COST_MIN", 10)
    br2 = create_committed_blend_run(formula["id"], "COST_MIN", 10)
    line = create_line(name="Line-DT")
    r1 = schedule_run(line["id"], formula["id"], br1["id"], 10,
                      "2026-09-07T08:00:00Z", "2026-09-07T10:00:00Z")
    complete_run(r1["id"])
    b1 = batch_for_run(r1["id"])
    r2 = schedule_run(line["id"], formula["id"], br2["id"], 10,
                      "2026-09-07T10:00:00Z", "2026-09-07T12:00:00Z")
    complete_run(r2["id"])
    b2 = batch_for_run(r2["id"])
    return b1, b2


class TestShelfLifeShipBoundary:
    def test_shelf_life_ship_at_exactly_75pct_passes(self, api):
        """PRD §3.6: "The shelf-life computation floors the exact duration
        from the logical clock to `best_by_date` to whole days, divides by the
        540-day shelf life, and expresses the result as a percentage; a batch
        with exactly 405 days remaining sits exactly at 75.0 percent and
        passes — at-threshold passes." PRD §2.5: "At server start, before any
        clock-setting call, the logical clock reads exactly
        2026-09-01T00:00:00Z".

        Both batches are produced at the clock default (best_by +540 days).
        At 2027-01-14 exactly 405 days remain: ship passes. At 2027-01-15 only
        404 days remain (74.81%): ERR_SHELF_LIFE_INSUFFICIENT.

        Design: Corner/calculations/shelf_life_ship_at_exactly_75pct_passes
        """
        b1, b2 = _setup_two_batches()
        assert b1["produced_at"].startswith("2026-09-01")
        assert b1["best_by_date"].startswith("2028-02-23")
        current = set_clock("2027-01-14T00:00:00Z")
        assert current.startswith("2027-01-14")
        resp = api_client.ship_batch(b1["id"],
                                     TEST_USERS["supply_planner_headers"])
        shipped = validate_success(resp, 200)
        assert shipped["commercial_status"] == "SHIPPED"
        set_clock("2027-01-15T00:00:00Z")
        resp = api_client.ship_batch(b2["id"],
                                     TEST_USERS["supply_planner_headers"])
        validate_error(resp, ApiErrorId.ERR_SHELF_LIFE_INSUFFICIENT)
