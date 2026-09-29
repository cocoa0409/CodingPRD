"""Compensations that must restore an invariant exactly: the run ledger and the batch identity."""

from test_helpers import (
    ADMIN,
    BATCH_CONDITIONING,
    CELLAR,
    DESTINATION_DISTRIBUTION,
    DESTINATION_TAPROOM,
    LICENSE_SELF_DISTRIBUTION,
    ORDER_CANCELLED,
    PACKAGE_HALF_BBL_KEG,
    RUN_COMPLETED,
    RUN_VOIDED,
    TANK_OCCUPIED,
    assert_batch_conserved,
    assert_bbl,
    assert_ledger_conserved,
    cancel_order_payload,
    validate_success,
)
from test_helpers.fixtures import (
    bootstrap_brewery,
    create_allocated_order,
    create_completed_run,
    create_conditioning_batch,
    create_distribution_ready_beer,
    create_exempt_beer,
    create_license,
    create_tank,
)

CANCEL_REASON = "wholesaler rescheduled the delivery window"


class TestOrderCancelRestoresTheRunLedger:
    def _allocated_three_of_five_barrels(self, api):
        bootstrap_brewery(api, home_state_code="OR")
        beer = create_distribution_ready_beer(
            api, name="Ridgeline IPA", abv_pct=6.8, price_per_bbl_cents=42000
        )
        license_row = create_license(
            api,
            "ID",
            LICENSE_SELF_DISTRIBUTION,
            annual_barrel_cap=1000.00,
            franchise_state=False,
            effective_from_utc="2026-01-01T00:00:00Z",
            expires_at_utc="2027-01-01T00:00:00Z",
        )
        tank = create_tank(api, code="FV-01", capacity_bbl=30.00)
        batch = create_conditioning_batch(
            api,
            beer["id"],
            tank["id"],
            actual_yield_bbl=16.000,
            batch_code="B-1001",
            planned_volume_bbl=16.00,
            brew_start_utc="2026-08-01T06:00:00Z",
            brew_end_utc="2026-08-08T06:00:00Z",
        )
        run = create_completed_run(
            api,
            batch["id"],
            package_type=PACKAGE_HALF_BBL_KEG,
            destination=DESTINATION_DISTRIBUTION,
            units_planned=10,
            run_code="R-DIST-1",
        )
        order = create_allocated_order(
            api,
            beer["id"],
            license_row["id"],
            bbl_requested=3.00,
            ship_to_state_code="ID",
            distance_miles=120,
            requested_ship_utc="2026-08-15T15:00:00Z",
            order_code="SO-4005",
        )
        return batch, run, license_row, order

    def test_cancelling_from_allocated_returns_every_reserved_barrel(self, api):
        """The run ledger closes back to 5.000 = 5.000 + 0.000 + 0.000.

        PRD §3.7: "From `ALLOCATED` it is a full compensation: every entry of
        `allocation_lines` is released, so each cited run's `allocated_bbl` falls
        and its `available_bbl` rises by that entry's barrels, leaving the run's
        `bbl_removed` still equal to the sum of its `available_bbl`,
        `allocated_bbl` and `shipped_bbl`; the order's `allocation_lines` becomes
        an empty list and its `allocated_bbl` returns to 0.000."

        Design: Difficulty/compensating_invariant/order_cancel_restores_packaging_run_barrel_conservation
        """
        _, run, license_row, order = self._allocated_three_of_five_barrels(api)
        before = validate_success(api.get_packaging_run(run["id"], CELLAR))
        assert_ledger_conserved(before)
        version_when_allocated = before["version"]

        cancelled = validate_success(
            api.cancel_order(order["id"], cancel_order_payload(CANCEL_REASON), ADMIN)
        )

        assert cancelled["state"] == ORDER_CANCELLED
        assert cancelled["cancel_reason"] == CANCEL_REASON
        assert cancelled["allocation_lines"] == []
        assert_bbl(cancelled["allocated_bbl"], 0.000, "order allocated_bbl")
        released = validate_success(api.get_packaging_run(run["id"], CELLAR))
        assert_bbl(released["available_bbl"], 5.000, "available_bbl")
        assert_bbl(released["allocated_bbl"], 0.000, "allocated_bbl")
        assert_bbl(released["shipped_bbl"], 0.000, "shipped_bbl")
        assert_bbl(released["bbl_removed"], 5.000, "bbl_removed")
        assert_ledger_conserved(released)
        assert released["state"] == RUN_COMPLETED
        assert released["version"] > version_when_allocated
        assert_bbl(
            validate_success(api.get_state_license(license_row["id"], ADMIN))[
                "barrels_shipped_ytd"
            ],
            0.000,
            "barrels_shipped_ytd",
        )

    def test_the_cancel_touches_the_reservation_and_not_the_packaging(self, api):
        """The batch still shows 5.000 packaged against 11.000 remaining.

        PRD §2.9: "`bbl_removed` itself changes only when the run completes
        (rising from zero) or is voided (falling to zero)."

        Design: Difficulty/compensating_invariant/order_cancel_restores_packaging_run_barrel_conservation
        """
        batch, _, _, order = self._allocated_three_of_five_barrels(api)

        validate_success(
            api.cancel_order(order["id"], cancel_order_payload(CANCEL_REASON), ADMIN)
        )

        stored = validate_success(api.get_batch(batch["id"], CELLAR))
        assert_bbl(stored["packaged_bbl"], 5.000, "packaged_bbl")
        assert_bbl(stored["remaining_bbl"], 11.000, "remaining_bbl")
        assert_batch_conserved(stored)


class TestRunVoidRestoresTheBatchIdentity:
    def _batch_with_one_completed_taproom_run(self, api):
        bootstrap_brewery(api)
        beer = create_exempt_beer(
            api, name="Ridgeline IPA", abv_pct=6.8, price_per_bbl_cents=42000
        )
        tank = create_tank(api, code="FV-01", capacity_bbl=30.00)
        batch = create_conditioning_batch(
            api,
            beer["id"],
            tank["id"],
            actual_yield_bbl=16.000,
            batch_code="B-1001",
            planned_volume_bbl=16.00,
            brew_start_utc="2026-08-01T06:00:00Z",
            brew_end_utc="2026-08-08T06:00:00Z",
        )
        run = create_completed_run(
            api,
            batch["id"],
            package_type=PACKAGE_HALF_BBL_KEG,
            destination=DESTINATION_TAPROOM,
            units_planned=10,
            run_code="R-TAP-1",
        )
        return tank, batch, run

    def test_voiding_a_completed_run_credits_the_barrels_back_to_the_batch(self, api):
        """16.000 = 0.000 packaged + 16.000 remaining once the run is voided.

        PRD §3.3: "When the guard passes, the batch's `packaged_bbl` falls by the
        run's `bbl_removed` and its `remaining_bbl` rises by the same amount,
        restoring the batch identity that `actual_yield_bbl` equals `packaged_bbl`
        plus `remaining_bbl`; the run's `bbl_removed` and `available_bbl` are reset
        to 0.000, its `units_produced` is set back to null, and `voided_at_utc` is
        stamped."

        Design: Difficulty/compensating_invariant/run_void_restores_batch_yield_conservation
        """
        tank, batch, run = self._batch_with_one_completed_taproom_run(api)
        version_after_complete = validate_success(api.get_batch(batch["id"], CELLAR))["version"]

        voided = validate_success(api.void_packaging_run(run["id"], CELLAR))

        assert voided["state"] == RUN_VOIDED
        assert_bbl(voided["bbl_removed"], 0.000, "bbl_removed")
        assert_bbl(voided["available_bbl"], 0.000, "available_bbl")
        assert voided["units_produced"] is None
        assert voided["loss_share_bbl"] is None
        assert voided["voided_at_utc"] is not None
        stored = validate_success(api.get_batch(batch["id"], CELLAR))
        assert_bbl(stored["packaged_bbl"], 0.000, "packaged_bbl")
        assert_bbl(stored["remaining_bbl"], 16.000, "remaining_bbl")
        assert_bbl(stored["actual_yield_bbl"], 16.000, "actual_yield_bbl")
        assert_batch_conserved(stored)
        assert stored["version"] > version_after_complete
        assert stored["state"] == BATCH_CONDITIONING
        stored_tank = validate_success(api.get_tank(tank["id"], CELLAR))
        assert stored_tank["status"] == TANK_OCCUPIED
        assert stored_tank["occupying_batch_id"] == batch["id"]

    def test_the_voided_run_leaves_no_phantom_inventory_behind(self, api):
        """Nothing on the void's own ledger survives: every barrel figure is 0.000.

        PRD §2.9: "Underneath all of it sits the **conservation law for packaged
        barrels**. For any packaging run, at every instant, `bbl_removed` equals
        the sum of `available_bbl`, `allocated_bbl` and `shipped_bbl`."

        Design: Difficulty/compensating_invariant/run_void_restores_batch_yield_conservation
        """
        _, _, run = self._batch_with_one_completed_taproom_run(api)

        validate_success(api.void_packaging_run(run["id"], CELLAR))

        stored = validate_success(api.get_packaging_run(run["id"], CELLAR))
        assert_bbl(stored["bbl_removed"], 0.000, "bbl_removed")
        assert_bbl(stored["allocated_bbl"], 0.000, "allocated_bbl")
        assert_bbl(stored["shipped_bbl"], 0.000, "shipped_bbl")
        assert_bbl(stored["available_bbl"], 0.000, "available_bbl")
        assert_ledger_conserved(stored)
