"""Difficulty queue: boundary precision — the 250bp qualification reject-rate
gate and the 110% transfer capacity gate, each exercised exactly at and one
integer step beyond the threshold.
"""
from test_helpers import (
    TEST_USERS,
    ApiErrorId,
    api_client,
    create_brand,
    create_item,
    create_plant,
    create_product_transfer_payload,
    get_transfer,
    record_run,
    setup_transfer_planned,
    validate_created,
    validate_error,
)

SCP = TEST_USERS["supply_chain_planner_headers"]


class TestQualificationRejectRateBoundary:
    def test_reject_rate_exactly_250bp_passes(self):
        """PRD §3.4: "Every run's `result` is computed by a hard quality gate:
        the run `PASS`es if and only if `units_rejected` multiplied by 10,000
        is less than or equal to `units_produced` multiplied by 250 — a reject
        rate of at most 250 basis points, evaluated as a pure integer
        comparison with no rounding, where a reject rate of exactly 250 basis
        points passes."

        Design: Difficulty/boundary_precision_check/qualification_reject_rate_exactly_250bp
        """
        _, _, target_plant, _, transfer = setup_transfer_planned()
        # 250 * 10000 <= 10000 * 250 -> boundary is inclusive.
        run = record_run(transfer["id"], target_plant["id"],
                         run_date="2026-09-02T00:00:00Z",
                         units_produced=10000, units_rejected=250)
        assert run["result"] == "PASS", (
            f"exactly 250bp must PASS (integer <=), got {run['result']}"
        )
        assert get_transfer(transfer["id"])["consecutive_pass_count"] == 1

    def test_reject_rate_251bp_fails_and_resets_counter(self):
        """PRD §3.4: "the run `PASS`es if and only if `units_rejected`
        multiplied by 10,000 is less than or equal to `units_produced`
        multiplied by 250 — a reject rate of at most 250 basis points,
        evaluated as a pure integer comparison with no rounding, where a reject
        rate of exactly 250 basis points passes. Any other outcome is a
        `FAIL`."
        PRD §3.4: "Each `PASS` increments the transfer's
        `consecutive_pass_count` by 1; each `FAIL` resets it to 0 — there is no
        failure ceiling and no cancel transition, so a string of failures
        simply keeps the transfer in `QUALIFYING`."

        Design: Difficulty/boundary_precision_check/qualification_reject_rate_exactly_250bp
        """
        _, _, target_plant, _, transfer = setup_transfer_planned()
        run_pass = record_run(transfer["id"], target_plant["id"],
                              run_date="2026-09-02T00:00:00Z",
                              units_produced=10000, units_rejected=250)
        assert run_pass["result"] == "PASS"
        # 251 * 10000 > 10000 * 250 -> one integer step beyond the boundary.
        run_fail = record_run(transfer["id"], target_plant["id"],
                              run_date="2026-09-03T00:00:00Z",
                              units_produced=10000, units_rejected=251)
        assert run_fail["result"] == "FAIL", (
            f"251bp must FAIL (one step beyond 250bp), got {run_fail['result']}"
        )
        after = get_transfer(transfer["id"])
        assert after["consecutive_pass_count"] == 0, (
            "PASS then FAIL must net a reset counter of 0"
        )
        assert after["transfer_status"] == "QUALIFYING"


class TestTransferCapacityBoundary:
    def _setup_loaded_target(self):
        """Target plant (capacity 10000) already committed to 9000 quarterly
        units by item X (annual 36000); source plant (capacity 1000000)."""
        brand = create_brand()
        target = create_plant(quarterly_capacity_units=10000)
        source = create_plant(quarterly_capacity_units=1000000)
        item_x = create_item(brand["id"], target["id"], annual_units=36000,
                             unit_net_revenue_cents=2000, unit_cost_cents=1700,
                             units_on_hand=0)
        return brand, source, target, item_x

    def test_exactly_110pct_projected_utilization_allowed(self):
        """PRD §3.4: "The comparison is pure integer cross-multiplication —
        projected times 100 must be less than or equal to capacity times 110 —
        with no floating-point rounding; a projected utilization of exactly
        110.00 percent is allowed and 110.01 percent is rejected with
        `ERR_PLANT_OVER_CAPACITY` (HTTP 422)."

        Design: Difficulty/boundary_precision_check/transfer_capacity_exactly_110pct_allowed
        """
        brand, source, target, _ = self._setup_loaded_target()
        # Incoming quarterly = round_half_up(8000/4) = 2000; projected 11000;
        # 11000 * 100 == 10000 * 110 -> exactly 110.00% -> allowed.
        item_y = create_item(brand["id"], source["id"], annual_units=8000,
                             unit_net_revenue_cents=2000, unit_cost_cents=1700,
                             units_on_hand=0)
        resp = api_client.create_product_transfer(
            create_product_transfer_payload(item_y["id"], source["id"], target["id"]),
            SCP,
        )
        transfer = validate_created(resp)
        assert transfer["transfer_status"] == "PLANNED"
        assert transfer["consecutive_pass_count"] == 0

    def test_110_01pct_projected_utilization_rejected(self):
        """PRD §3.4: "a projected utilization of exactly 110.00 percent is
        allowed and 110.01 percent is rejected with `ERR_PLANT_OVER_CAPACITY`
        (HTTP 422)."

        Design: Difficulty/boundary_precision_check/transfer_capacity_exactly_110pct_allowed
        """
        brand, source, target, _ = self._setup_loaded_target()
        # Incoming quarterly = round_half_up(8004/4) = 2001; projected 11001;
        # 11001 * 100 > 10000 * 110 -> 110.01% -> rejected.
        item_z = create_item(brand["id"], source["id"], annual_units=8004,
                             unit_net_revenue_cents=2000, unit_cost_cents=1700,
                             units_on_hand=0)
        resp = api_client.create_product_transfer(
            create_product_transfer_payload(item_z["id"], source["id"], target["id"]),
            SCP,
        )
        validate_error(resp, ApiErrorId.ERR_PLANT_OVER_CAPACITY)
