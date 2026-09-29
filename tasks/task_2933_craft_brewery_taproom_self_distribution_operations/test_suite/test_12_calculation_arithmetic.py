"""Pinned arithmetic: excise tiers, landed cost, the sanitation band and the waterfall."""

from test_helpers import (
    ADMIN,
    BASIS_METERED_POUR,
    BASIS_WHOLE_KEG_REMOVAL,
    CELLAR,
    COMPLIANCE,
    CONTAINER_PINT_16OZ,
    DESTINATION_DISTRIBUTION,
    DESTINATION_TAPROOM,
    ERR_SANITATION_BELOW_STANDARD,
    KEG_CLEANED,
    KEG_EMPTY_DIRTY,
    KEG_SIZE_HALF_BBL,
    LICENSE_SELF_DISTRIBUTION,
    ORDER_ALLOCATED,
    ORDER_REJECTED,
    PACKAGE_HALF_BBL_KEG,
    RECON_RECONCILED,
    REJECTION_INSUFFICIENT_INVENTORY,
    REPORT_FILED,
    REPORT_SUPERSEDED,
    SANITATION_PASS,
    TAPROOM,
    assert_allocation_lines,
    assert_bbl,
    assert_cents,
    assert_instant_equals,
    assert_oz,
    crowler_payload,
    keg_clean_payload,
    keg_return_payload,
    order_payload,
    pour_payload,
    validate_error,
    validate_paginated,
    validate_success,
)
from test_helpers.constants import CLOCK_DEFAULT_UTC
from test_helpers.fixtures import (
    bootstrap_brewery,
    complete_run,
    create_allocated_order,
    create_completed_run,
    create_conditioning_batch,
    create_distribution_ready_beer,
    create_exempt_beer,
    create_keg,
    create_license,
    create_tank,
    create_tapped_keg,
    draft_report,
    file_report,
    plan_run,
    set_clock,
)
from test_helpers.test_users import USER_TAPROOM_2

AUGUST_START = "2026-08-01T00:00:00Z"
AUGUST_END = "2026-09-01T00:00:00Z"


class TestFederalTierStraddle:
    def test_one_period_is_cut_in_two_by_the_reduced_tier_limit(self, api):
        """1.000 bbl at 350 plus 0.500 bbl at 1600 is 1150 cents, not a flat 525.

        PRD §3.8: "`federal_tax_cents` is then the reduced-tier barrels multiplied
        by 350 cents per barrel, rounded half up to whole cents, **plus** the
        standard-tier barrels multiplied by 1,600 cents per barrel, likewise
        rounded half up to whole cents on its own."

        Design: Corner/calculations/federal_tier_straddle_splits_one_period_across_cbma_and_standard_rates
        """
        bootstrap_brewery(
            api,
            home_state_code="OR",
            carry_in_taproom_bbl=59999.000,
            carry_in_distribution_bbl=0.000,
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
        taproom_run = create_completed_run(
            api,
            batch["id"],
            package_type=PACKAGE_HALF_BBL_KEG,
            destination=DESTINATION_TAPROOM,
            units_planned=10,
            run_code="R-TAP-1",
        )
        create_completed_run(
            api,
            batch["id"],
            package_type=PACKAGE_HALF_BBL_KEG,
            destination=DESTINATION_DISTRIBUTION,
            units_planned=10,
            run_code="R-DIST-1",
        )
        set_clock(api, "2026-08-10T12:00:00Z")
        create_tapped_keg(
            api, taproom_run["id"], KEG_SIZE_HALF_BBL, keg_serial="KEG-0001"
        )
        order = create_allocated_order(
            api,
            beer["id"],
            license_row["id"],
            bbl_requested=1.00,
            ship_to_state_code="ID",
            distance_miles=120,
            requested_ship_utc="2026-08-10T12:00:00Z",
            order_code="SO-6100",
        )
        validate_success(api.ship_order(order["id"], ADMIN))
        set_clock(api, AUGUST_END)

        report = draft_report(
            api,
            period_start_utc=AUGUST_START,
            period_end_utc=AUGUST_END,
            taproom_basis=BASIS_WHOLE_KEG_REMOVAL,
        )

        assert_bbl(report["ytd_bbl_before_period"], 59999.000, "ytd_bbl_before_period")
        assert_bbl(report["taproom_bbl"], 0.500, "taproom_bbl")
        assert_bbl(report["distribution_bbl"], 1.000, "distribution_bbl")
        assert_bbl(report["total_taxable_bbl"], 1.500, "total_taxable_bbl")
        assert_cents(report["federal_tax_cents"], 1150, "federal_tax_cents")
        assert_cents(report["state_tax_cents"], 1413, "state_tax_cents")
        assert_cents(report["total_tax_due_cents"], 2563, "total_tax_due_cents")


class TestAllocationCandidatePool:
    def test_taproom_stock_is_invisible_to_the_allocator(self, api):
        """Five barrels sit in a taproom run, so the pool is empty and the order rejects.

        PRD §3.7: "Runs destined for the taproom are **never** drawn from, however
        much idle stock is sitting there; runs still in `PLANNED` hold no inventory
        yet; and runs in `VOIDED` have an `available_bbl` of 0.000."

        Design: Corner/calculations/allocation_pool_ignores_taproom_runs_and_rejects_for_insufficient_inventory
        """
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
        taproom_run = create_completed_run(
            api,
            batch["id"],
            package_type=PACKAGE_HALF_BBL_KEG,
            destination=DESTINATION_TAPROOM,
            units_planned=10,
            run_code="R-TAP-1",
        )
        run_version_before = taproom_run["version"]
        order = validate_success(
            api.create_distribution_order(
                order_payload(
                    beer["id"],
                    license_row["id"],
                    bbl_requested=1.00,
                    ship_to_state_code="ID",
                    distance_miles=120,
                    requested_ship_utc="2026-08-15T15:00:00Z",
                    order_code="SO-6200",
                ),
                ADMIN,
            ),
            201,
        )

        rejected = validate_success(api.allocate_order(order["id"], ADMIN))

        assert rejected["state"] == ORDER_REJECTED
        assert rejected["rejection_reason"] == REJECTION_INSUFFICIENT_INVENTORY
        assert rejected["allocation_lines"] == []
        assert_bbl(rejected["allocated_bbl"], 0.000, "allocated_bbl")
        stored_run = validate_success(api.get_packaging_run(taproom_run["id"], CELLAR))
        assert_bbl(stored_run["allocated_bbl"], 0.000, "allocated_bbl")
        assert_bbl(stored_run["available_bbl"], 5.000, "available_bbl")
        assert stored_run["version"] == run_version_before


class TestFreightDiscountTierBoundary:
    def test_the_cheaper_order_lands_dearer_because_it_misses_the_tier(self, api):
        """200000 cents takes 20 percent while 199600 takes only 10 percent.

        PRD §3.7: "Tier selection is inclusive at each boundary: a product value of
        exactly 200,000 cents takes the 20 percent tier, while 199,999 cents takes
        the 10 percent tier."

        Design: Corner/calculations/landed_cost_freight_discount_tier_boundary_at_exactly_two_hundred_thousand_cents
        """
        bootstrap_brewery(api, home_state_code="OR")
        beer = create_distribution_ready_beer(
            api, name="Ridgeline IPA", abv_pct=6.8, price_per_bbl_cents=40000
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

        at_the_tier = validate_success(
            api.create_distribution_order(
                order_payload(
                    beer["id"],
                    license_row["id"],
                    bbl_requested=5.00,
                    ship_to_state_code="ID",
                    distance_miles=100,
                    requested_ship_utc="2026-08-15T15:00:00Z",
                    order_code="SO-6301",
                ),
                ADMIN,
            ),
            201,
        )
        below_the_tier = validate_success(
            api.create_distribution_order(
                order_payload(
                    beer["id"],
                    license_row["id"],
                    bbl_requested=4.99,
                    ship_to_state_code="ID",
                    distance_miles=100,
                    requested_ship_utc="2026-08-15T15:00:00Z",
                    order_code="SO-6302",
                ),
                ADMIN,
            ),
            201,
        )

        assert_cents(at_the_tier["product_cents"], 200000, "product_cents")
        assert_cents(at_the_tier["freight_cents"], 7200, "freight_cents")
        assert_cents(at_the_tier["franchise_fee_cents"], 0, "franchise_fee_cents")
        assert_cents(at_the_tier["landed_cost_cents"], 207200, "landed_cost_cents")
        assert_cents(below_the_tier["product_cents"], 199600, "product_cents")
        assert_cents(below_the_tier["freight_cents"], 8089, "freight_cents")
        assert_cents(below_the_tier["landed_cost_cents"], 207689, "landed_cost_cents")
        assert below_the_tier["landed_cost_cents"] > at_the_tier["landed_cost_cents"]


class TestSanitationBandCeiling:
    def _tapped_half_barrel(self, api):
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
        return run, create_tapped_keg(
            api, run["id"], KEG_SIZE_HALF_BBL, keg_serial="KEG-0001"
        )

    def test_four_hundred_parts_per_million_passes_and_four_hundred_one_does_not(
        self, api
    ):
        """The concentration band is closed at the top as well as the bottom.

        PRD §3.5: "The sanitation reading on a growler or crowler is judged by the
        same standard as a tank clean-in-place or a keg wash: the concentration must
        be at least 150 and at most 400 parts per million, both bounds inclusive,
        and the contact time must be at least 60 seconds."

        Design: Corner/calculations/crowler_fill_at_four_hundred_ppm_passes_and_four_hundred_one_fails
        """
        _, keg = self._tapped_half_barrel(api)

        accepted = validate_success(
            api.create_taproom_pour(
                crowler_payload(
                    keg["id"],
                    USER_TAPROOM_2,
                    sanitizer_ppm=400,
                    contact_time_seconds=60,
                    price_cents=1200,
                ),
                TAPROOM,
            ),
            201,
        )
        validate_error(
            api.create_taproom_pour(
                crowler_payload(
                    keg["id"],
                    USER_TAPROOM_2,
                    sanitizer_ppm=401,
                    contact_time_seconds=60,
                    price_cents=1200,
                ),
                TAPROOM,
            ),
            ERR_SANITATION_BELOW_STANDARD,
            422,
        )

        assert accepted["sanitation_verdict"] == SANITATION_PASS
        assert_oz(accepted["volume_oz"], 32, "volume_oz")
        _, meta = validate_paginated(
            api.list_taproom_pours(TAPROOM, {"keg_asset_id": keg["id"]})
        )
        assert meta["total_count"] == 1
        stored = validate_success(api.get_keg_asset(keg["id"], CELLAR))
        assert_oz(stored["poured_volume_oz"], 32.00, "poured_volume_oz")
        assert_oz(stored["remaining_volume_oz"], 1952.00, "remaining_volume_oz")


class TestKegWashContactTime:
    def test_fifty_nine_seconds_aborts_the_wash_and_sixty_completes_it(self, api):
        """The contact-time comparison is inclusive at exactly sixty seconds.

        PRD §3.4: "Anything outside that band aborts the request with
        `ERR_SANITATION_BELOW_STANDARD` and **no wash is recorded** — the keg stays
        `EMPTY_DIRTY` and `last_cleaned_utc` is not moved."

        Design: Corner/calculations/keg_clean_contact_time_at_sixty_seconds_passes_and_fifty_nine_fails
        """
        bootstrap_brewery(api)
        keg = create_keg(api, KEG_SIZE_HALF_BBL, keg_serial="KEG-0001")
        assert keg["state"] == KEG_EMPTY_DIRTY
        assert keg["last_cleaned_utc"] is None

        validate_error(
            api.clean_keg_asset(
                keg["id"], keg_clean_payload(sanitizer_ppm=200, contact_time_seconds=59), CELLAR
            ),
            ERR_SANITATION_BELOW_STANDARD,
            422,
        )
        after_failure = validate_success(api.get_keg_asset(keg["id"], CELLAR))
        cleaned = validate_success(
            api.clean_keg_asset(
                keg["id"], keg_clean_payload(sanitizer_ppm=200, contact_time_seconds=60), CELLAR
            )
        )

        assert after_failure["state"] == KEG_EMPTY_DIRTY
        assert after_failure["last_cleaned_utc"] is None
        assert cleaned["state"] == KEG_CLEANED
        assert_instant_equals(
            cleaned["last_cleaned_utc"], CLOCK_DEFAULT_UTC, "last_cleaned_utc"
        )


class TestZeroVarianceReturn:
    def test_a_keg_returned_full_shows_no_variance_at_all(self, api):
        """15.50 gallons back out of 1984.00 ounces in is a variance of exactly zero.

        PRD §3.4: "The first hop books the volumes on the keg itself:
        `returned_volume_oz` becomes `returned_volume_gal` multiplied by 128, rounded
        half up to two decimal places; `depletion_variance_oz` becomes
        `returned_volume_oz` minus the keg's expected remainder, where the expected
        remainder is `filled_volume_oz` minus `poured_volume_oz` — the same quantity
        the keg reports as `remaining_volume_oz` — again rounded half up to two
        decimal places; and `cycle_count` rises by 1."

        Design: Corner/calculations/keg_returned_full_measure_yields_zero_variance_and_no_flag
        """
        bootstrap_brewery(api)
        beer = create_exempt_beer(api, name="Ridgeline IPA")
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
        keg = create_tapped_keg(
            api, run["id"], KEG_SIZE_HALF_BBL, keg_serial="KEG-0001"
        )

        returned = validate_success(
            api.move_keg_asset(keg["id"], keg_return_payload(15.5), CELLAR)
        )

        assert_oz(returned["returned_volume_oz"], 1984.00, "returned_volume_oz")
        assert_oz(returned["depletion_variance_oz"], 0.00, "depletion_variance_oz")
        assert returned["shrinkage_flagged"] is False
        assert returned["state"] == KEG_EMPTY_DIRTY
        assert returned["cycle_count"] == 1
        stored_run = validate_success(api.get_packaging_run(run["id"], CELLAR))
        assert_oz(stored_run["keg_shrinkage_oz"], 0.00, "keg_shrinkage_oz")
        assert stored_run["kegs_outstanding_count"] == 0
        assert stored_run["reconciliation_state"] == RECON_RECONCILED


class TestWaterfallDrawDownOrder:
    def test_the_older_run_is_drained_before_the_newer_one_is_touched(self, api):
        """Seven barrels take all five of the older run and only two of the newer.

        PRD §3.7: "The pool is then sorted **oldest stock first**: by
        `removed_at_utc` ascending, with `created_at` ascending as the tie-break for
        two runs certified at the same logical instant."

        Design: Corner/calculations/allocation_draws_oldest_removed_stock_first_across_two_runs
        """
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
        set_clock(api, "2026-08-02T00:00:00Z")
        older = plan_run(
            api,
            batch["id"],
            package_type=PACKAGE_HALF_BBL_KEG,
            destination=DESTINATION_DISTRIBUTION,
            units_planned=10,
            run_code="R-DIST-1",
        )
        complete_run(api, older["id"], 10)
        set_clock(api, "2026-08-03T00:00:00Z")
        newer = plan_run(
            api,
            batch["id"],
            package_type=PACKAGE_HALF_BBL_KEG,
            destination=DESTINATION_DISTRIBUTION,
            units_planned=10,
            run_code="R-DIST-2",
        )
        complete_run(api, newer["id"], 10)
        order = validate_success(
            api.create_distribution_order(
                order_payload(
                    beer["id"],
                    license_row["id"],
                    bbl_requested=7.00,
                    ship_to_state_code="ID",
                    distance_miles=120,
                    requested_ship_utc="2026-08-15T15:00:00Z",
                    order_code="SO-6400",
                ),
                ADMIN,
            ),
            201,
        )

        allocated = validate_success(api.allocate_order(order["id"], ADMIN))

        assert allocated["state"] == ORDER_ALLOCATED
        assert_bbl(allocated["allocated_bbl"], 7.000, "allocated_bbl")
        assert_allocation_lines(
            allocated["allocation_lines"], [(older["id"], 5.000), (newer["id"], 2.000)]
        )
        stored_older = validate_success(api.get_packaging_run(older["id"], CELLAR))
        assert_bbl(stored_older["allocated_bbl"], 5.000, "allocated_bbl")
        assert_bbl(stored_older["available_bbl"], 0.000, "available_bbl")
        stored_newer = validate_success(api.get_packaging_run(newer["id"], CELLAR))
        assert_bbl(stored_newer["allocated_bbl"], 2.000, "allocated_bbl")
        assert_bbl(stored_newer["available_bbl"], 3.000, "available_bbl")


class TestAmendingReturn:
    def test_the_amendment_reprices_the_same_period_on_the_other_basis(self, api):
        """0.012 metered barrels become 0.500 whole-keg barrels over identical data.

        PRD §3.8: "Returns in `SUPERSEDED` never contribute, and neither do drafts —
        which has the deliberate consequence that an amending return sees exactly the
        same `ytd_bbl_before_period` its superseded original saw."

        Design: Corner/calculations/amending_return_reprices_the_same_period_under_the_other_basis
        """
        bootstrap_brewery(api)
        beer = create_exempt_beer(api, name="Ridgeline IPA")
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
        keg = create_tapped_keg(
            api, run["id"], KEG_SIZE_HALF_BBL, keg_serial="KEG-0001"
        )
        for _ in range(3):
            validate_success(
                api.create_taproom_pour(
                    pour_payload(keg["id"], CONTAINER_PINT_16OZ, price_cents=800), TAPROOM
                ),
                201,
            )
        set_clock(api, AUGUST_END)
        original = draft_report(
            api,
            period_start_utc=AUGUST_START,
            period_end_utc=AUGUST_END,
            taproom_basis=BASIS_METERED_POUR,
        )
        filed_original = file_report(api, original["id"])
        assert_bbl(filed_original["taproom_bbl"], 0.012, "taproom_bbl")
        assert_cents(filed_original["total_tax_due_cents"], 11, "total_tax_due_cents")

        amendment = draft_report(
            api,
            period_start_utc=AUGUST_START,
            period_end_utc=AUGUST_END,
            taproom_basis=BASIS_WHOLE_KEG_REMOVAL,
            amends_report_id=original["id"],
        )
        filed_amendment = file_report(api, amendment["id"])

        assert_bbl(
            filed_amendment["ytd_bbl_before_period"], 0.000, "ytd_bbl_before_period"
        )
        assert_bbl(filed_amendment["taproom_bbl"], 0.500, "taproom_bbl")
        assert_bbl(filed_amendment["total_taxable_bbl"], 0.500, "total_taxable_bbl")
        assert_cents(filed_amendment["federal_tax_cents"], 175, "federal_tax_cents")
        assert_cents(filed_amendment["state_tax_cents"], 272, "state_tax_cents")
        assert_cents(filed_amendment["total_tax_due_cents"], 447, "total_tax_due_cents")
        assert filed_amendment["state"] == REPORT_FILED
        superseded = validate_success(api.get_excise_report(original["id"], COMPLIANCE))
        assert superseded["state"] == REPORT_SUPERSEDED
        assert_bbl(superseded["taproom_bbl"], 0.012, "taproom_bbl")
        assert_cents(superseded["total_tax_due_cents"], 11, "total_tax_due_cents")
        brewery = validate_success(api.get_brewery(ADMIN))
        assert_bbl(brewery["taproom_bbl_ytd"], 0.500, "taproom_bbl_ytd")
        assert_bbl(brewery["total_bbl_ytd"], 0.500, "total_bbl_ytd")
