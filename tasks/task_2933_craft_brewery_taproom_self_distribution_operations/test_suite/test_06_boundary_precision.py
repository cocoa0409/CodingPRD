"""Inclusive and strict boundaries: the annual cap, and the shrinkage tolerance."""

from test_helpers import (
    ADMIN,
    CELLAR,
    CONTAINER_PINT_16OZ,
    DESTINATION_DISTRIBUTION,
    DESTINATION_TAPROOM,
    KEG_EMPTY_DIRTY,
    KEG_SIZE_HALF_BBL,
    LICENSE_SELF_DISTRIBUTION,
    ORDER_CHANNEL_SELF_DISTRIBUTED,
    ORDER_SHIPPED,
    PACKAGE_HALF_BBL_KEG,
    RECON_RECONCILED,
    TAPROOM,
    assert_bbl,
    assert_cents,
    assert_instant_equals,
    assert_oz,
    keg_return_payload,
    pour_payload,
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
    create_tapped_keg,
    set_clock,
    set_license_carry_in,
)

SHIP_INSTANT = "2026-08-15T15:00:00Z"


class TestSelfDistributionCapExactHit:
    def _order_with_exactly_five_barrels_of_headroom(self, api):
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
        set_license_carry_in(api, license_row["id"], 995.000)
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
            bbl_requested=5.00,
            ship_to_state_code="ID",
            distance_miles=120,
            requested_ship_utc=SHIP_INSTANT,
            order_code="SO-4003",
        )
        set_clock(api, SHIP_INSTANT)
        return license_row, run, order

    def test_landing_exactly_on_the_annual_cap_is_permitted(self, api):
        """995.000 shipped plus 5.000 more reaches 1000.000 and the shipment stands.

        PRD §3.7: "It requires the brewery's `notice_status` and the licence's
        `status` to be `ACTIVE`, and on the `SELF_DISTRIBUTED` channel it enforces
        the annual ceiling: the licence's `barrels_shipped_ytd` plus this order's
        `allocated_bbl` must be **at most** the licence's `annual_barrel_cap`. The
        comparison is inclusive, so landing exactly on the cap is permitted and
        the very next barrel is not; a breach is refused with
        `ERR_SELF_DISTRIBUTION_CAP_EXCEEDED`."

        Design: Difficulty/boundary_precision_check/self_distribution_annual_cap_exact_hit_is_permitted
        """
        license_row, _, order = self._order_with_exactly_five_barrels_of_headroom(api)

        shipped = validate_success(api.ship_order(order["id"], ADMIN))

        assert shipped["state"] == ORDER_SHIPPED
        assert shipped["channel"] == ORDER_CHANNEL_SELF_DISTRIBUTED
        assert_cents(shipped["franchise_fee_cents"], 0, "franchise_fee_cents")
        assert_instant_equals(shipped["shipped_at_utc"], SHIP_INSTANT, "shipped_at_utc")
        assert_bbl(
            validate_success(api.get_state_license(license_row["id"], ADMIN))[
                "barrels_shipped_ytd"
            ],
            1000.000,
            "barrels_shipped_ytd",
        )

    def test_the_shipment_moves_the_barrels_from_allocated_to_shipped(self, api):
        """The run's ledger reads 5.000 removed, 5.000 shipped, nothing available.

        PRD §3.7: "Each cited run moves that line's barrels from `allocated_bbl`
        to `shipped_bbl`, leaving `available_bbl` **unchanged**, since those
        barrels were already spoken for."

        Design: Difficulty/boundary_precision_check/self_distribution_annual_cap_exact_hit_is_permitted
        """
        _, run, order = self._order_with_exactly_five_barrels_of_headroom(api)

        validate_success(api.ship_order(order["id"], ADMIN))

        stored = validate_success(api.get_packaging_run(run["id"], CELLAR))
        assert_bbl(stored["shipped_bbl"], 5.000, "shipped_bbl")
        assert_bbl(stored["allocated_bbl"], 0.000, "allocated_bbl")
        assert_bbl(stored["available_bbl"], 0.000, "available_bbl")
        assert_bbl(stored["bbl_removed"], 5.000, "bbl_removed")


class TestShrinkageToleranceExactHit:
    def _two_kegs_each_four_pints_down(self, api):
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
        kegs = []
        for serial in ("KEG-0001", "KEG-0002"):
            keg = create_tapped_keg(
                api, run["id"], KEG_SIZE_HALF_BBL, keg_serial=serial
            )
            for _ in range(4):
                validate_success(
                    api.create_taproom_pour(
                        pour_payload(keg["id"], CONTAINER_PINT_16OZ, price_cents=800),
                        TAPROOM,
                    ),
                    201,
                )
            kegs.append(keg)
        return run, kegs

    def test_a_variance_of_exactly_the_tolerance_is_not_flagged(self, api):
        """-39.68 oz sits on the 2 percent line and 0.01 gal further does not.

        PRD §3.4: "The keg is flagged when the variance is large in either
        direction: the tolerance is two percent of `filled_volume_oz`, rounded
        half up to two decimal places, and `shrinkage_flagged` becomes true when
        the absolute value of `depletion_variance_oz` is **strictly greater** than
        that tolerance."

        Design: Difficulty/boundary_precision_check/keg_shrinkage_tolerance_exact_hit_is_not_flagged
        """
        _, kegs = self._two_kegs_each_four_pints_down(api)

        on_the_line = validate_success(
            api.move_keg_asset(kegs[0]["id"], keg_return_payload(14.69), TAPROOM)
        )
        over_the_line = validate_success(
            api.move_keg_asset(kegs[1]["id"], keg_return_payload(14.68), TAPROOM)
        )

        assert_oz(on_the_line["returned_volume_oz"], 1880.32, "returned_volume_oz")
        assert_oz(on_the_line["depletion_variance_oz"], -39.68, "depletion_variance_oz")
        assert on_the_line["shrinkage_flagged"] is False
        assert_oz(over_the_line["returned_volume_oz"], 1879.04, "returned_volume_oz")
        assert_oz(over_the_line["depletion_variance_oz"], -40.96, "depletion_variance_oz")
        assert over_the_line["shrinkage_flagged"] is True
        for keg_id in (kegs[0]["id"], kegs[1]["id"]):
            stored = validate_success(api.get_keg_asset(keg_id, CELLAR))
            assert stored["state"] == KEG_EMPTY_DIRTY
            assert stored["cycle_count"] == 1

    def test_the_unflagged_keg_still_contributes_to_the_run_roll_up(self, api):
        """The reconciled run sums both variances to -80.64 oz.

        PRD §3.4: "The third hop follows from the second: when that count reaches
        zero and the run's `kegs_filled_count` is at least 1, the run's
        `reconciliation_state` moves `OPEN → RECONCILED` and its
        `keg_shrinkage_oz` is written as the sum of `depletion_variance_oz` over
        every keg asset still linked to the run — including the kegs whose own
        variance sat comfortably inside tolerance — rounded half up to two
        decimal places."

        Design: Difficulty/boundary_precision_check/keg_shrinkage_tolerance_exact_hit_is_not_flagged
        """
        run, kegs = self._two_kegs_each_four_pints_down(api)

        validate_success(api.move_keg_asset(kegs[0]["id"], keg_return_payload(14.69), TAPROOM))
        validate_success(api.move_keg_asset(kegs[1]["id"], keg_return_payload(14.68), TAPROOM))

        reconciled = validate_success(api.get_packaging_run(run["id"], CELLAR))
        assert_oz(reconciled["keg_shrinkage_oz"], -80.64, "keg_shrinkage_oz")
        assert reconciled["reconciliation_state"] == RECON_RECONCILED
        assert reconciled["kegs_outstanding_count"] == 0
