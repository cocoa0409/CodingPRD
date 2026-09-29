"""Two requests that break two rules at once, and the rung that must answer."""

from test_helpers import (
    ADMIN,
    CELLAR,
    DESTINATION_DISTRIBUTION,
    DESTINATION_TAPROOM,
    ERR_ORDER_NOT_ALLOCATED,
    ERR_SANITATION_BELOW_STANDARD,
    KEG_SIZE_HALF_BBL,
    KEG_TAPPED,
    LICENSE_SELF_DISTRIBUTION,
    ORDER_SUBMITTED,
    PACKAGE_HALF_BBL_KEG,
    TAPROOM,
    USER_TAPROOM_1,
    assert_bbl,
    assert_oz,
    growler_payload,
    validate_error,
    validate_paginated,
    validate_success,
)
from test_helpers.fixtures import (
    bootstrap_brewery,
    create_completed_run,
    create_conditioning_batch,
    create_distribution_ready_beer,
    create_exempt_beer,
    create_license,
    create_tank,
    create_tapped_keg,
    set_license_carry_in,
    submit_order,
)


class TestShipmentReportsStateBeforeFiscal:
    def _submitted_order_over_the_cap(self, api):
        bootstrap_brewery(
            api, home_state_code="OR", ttb_brewers_notice_number="BR-OR-4417"
        )
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
        set_license_carry_in(api, license_row["id"], 1200.000)
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
        create_completed_run(
            api,
            batch["id"],
            package_type=PACKAGE_HALF_BBL_KEG,
            destination=DESTINATION_DISTRIBUTION,
            units_planned=10,
            run_code="R-DIST-1",
        )
        order = submit_order(
            api,
            beer["id"],
            license_row["id"],
            bbl_requested=5.00,
            ship_to_state_code="ID",
            distance_miles=120,
            requested_ship_utc="2026-08-15T15:00:00Z",
            order_code="SO-4002",
        )
        return license_row, order

    def test_an_unallocated_shipment_over_the_ceiling_answers_the_transition_error(self, api):
        """Rung 9 answers before rung 28, so the 409 wins over the fiscal 422.

        PRD §2.8: "When a single request violates more than one rule, the answer
        the client receives is fully determined: the system evaluates checks in
        the fixed order below and reports the **first** violation it finds,
        stopping there."

        Design: Difficulty/priority_pair_validation_conflict/ship_unallocated_order_over_the_annual_cap_reports_state_before_fiscal
        """
        _, order = self._submitted_order_over_the_cap(api)

        validate_error(
            api.ship_order(order["id"], ADMIN), ERR_ORDER_NOT_ALLOCATED, 409
        )

    def test_the_refused_shipment_moves_no_state_and_books_no_barrels(self, api):
        """The order stays SUBMITTED and barrels_shipped_ytd holds at 1200.000.

        PRD §2.8: "`ERR_ORDER_NOT_ALLOCATED` specifically for a shipment
        attempted on an order whose `state` is not `ALLOCATED`."

        Design: Difficulty/priority_pair_validation_conflict/ship_unallocated_order_over_the_annual_cap_reports_state_before_fiscal
        """
        license_row, order = self._submitted_order_over_the_cap(api)

        validate_error(api.ship_order(order["id"], ADMIN), ERR_ORDER_NOT_ALLOCATED)

        unchanged = validate_success(api.get_distribution_order(order["id"], ADMIN))
        assert unchanged["state"] == ORDER_SUBMITTED
        assert unchanged["shipped_at_utc"] is None
        assert_bbl(
            validate_success(api.get_state_license(license_row["id"], ADMIN))[
                "barrels_shipped_ytd"
            ],
            1200.000,
            "barrels_shipped_ytd",
        )


class TestGrowlerReportsSafetyBeforeDuties:
    def _tapped_keg(self, api):
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
        return create_tapped_keg(api, run["id"], KEG_SIZE_HALF_BBL, keg_serial="KEG-0001")

    def test_an_understrength_self_attested_growler_answers_the_sanitation_error(self, api):
        """90 ppm plus self-attestation reports the public-health failure, not the SoD one.

        PRD §2.8: "**Segregation of duties** — `ERR_SEGREGATION_OF_DUTIES` (409)
        when an appointment's approver equals its proposer, when an excise
        return's filer equals its preparer, or when a growler or crowler fill's
        `attested_by_user_id` equals the pouring user."

        Design: Difficulty/priority_pair_validation_conflict/understrength_sanitizer_with_self_attested_growler_reports_safety_before_duties
        """
        keg = self._tapped_keg(api)

        validate_error(
            api.create_taproom_pour(
                growler_payload(
                    keg["id"],
                    USER_TAPROOM_1,
                    sanitizer_ppm=90,
                    contact_time_seconds=90,
                    price_cents=2200,
                ),
                TAPROOM,
            ),
            ERR_SANITATION_BELOW_STANDARD,
            422,
        )

    def test_the_failing_verdict_leaves_no_pour_row_and_no_beer_off_the_keg(self, api):
        """A rejected fill persists nothing: the keg meter never moves.

        PRD §2.8: "**Sanitation standard** — `ERR_SANITATION_BELOW_STANDARD`
        (422) when the sanitation verdict computes to a failure. This guards
        growler and crowler fills, keg washes, and tank clean-in-place cycles. A
        failing verdict is never persisted."

        Design: Difficulty/priority_pair_validation_conflict/understrength_sanitizer_with_self_attested_growler_reports_safety_before_duties
        """
        keg = self._tapped_keg(api)

        validate_error(
            api.create_taproom_pour(
                growler_payload(
                    keg["id"],
                    USER_TAPROOM_1,
                    sanitizer_ppm=90,
                    contact_time_seconds=90,
                    price_cents=2200,
                ),
                TAPROOM,
            ),
            ERR_SANITATION_BELOW_STANDARD,
        )

        pours, meta = validate_paginated(
            api.list_taproom_pours(TAPROOM, {"keg_asset_id": keg["id"]})
        )
        assert pours == []
        assert meta["total_count"] == 0
        stored = validate_success(api.get_keg_asset(keg["id"], CELLAR))
        assert_oz(stored["poured_volume_oz"], 0.00, "poured_volume_oz")
        assert_oz(stored["remaining_volume_oz"], 1984.00, "remaining_volume_oz")
        assert stored["state"] == KEG_TAPPED
