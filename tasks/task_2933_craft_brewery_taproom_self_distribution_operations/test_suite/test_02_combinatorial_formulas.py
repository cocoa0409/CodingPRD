"""Pinned step order in the landed cost, and ounce aggregation before barrel rounding."""

from test_helpers import (
    ADMIN,
    BASIS_METERED_POUR,
    CELLAR,
    DESTINATION_TAPROOM,
    KEG_SIZE_HALF_BBL,
    LICENSE_WHOLESALER_ONLY,
    ORDER_CHANNEL_WHOLESALER,
    ORDER_SUBMITTED,
    PACKAGE_HALF_BBL_KEG,
    SANITATION_PASS,
    SCOPE_ALL_BRANDS,
    TAPROOM,
    USER_TAPROOM_1,
    USER_TAPROOM_2,
    assert_bbl,
    assert_cents,
    assert_oz,
    excise_report_payload,
    growler_payload,
    order_payload,
    validate_success,
)
from test_helpers.fixtures import (
    bootstrap_brewery,
    create_active_appointment,
    create_completed_run,
    create_conditioning_batch,
    create_distribution_ready_beer,
    create_license,
    create_tank,
    create_tapped_keg,
    set_clock,
)


class TestLandedCostPinnedStepOrder:
    """§3.7 step order: tier from the rounded product, discount rounded on its own,
    franchise fee on the discounted subtotal."""

    def _wholesaler_scenario(self, api):
        bootstrap_brewery(api, home_state_code="OR")
        beer = create_distribution_ready_beer(
            api, name="Ridgeline IPA", abv_pct=6.8, price_per_bbl_cents=42000
        )
        license_row = create_license(
            api,
            "WA",
            LICENSE_WHOLESALER_ONLY,
            annual_barrel_cap=0.00,
            franchise_state=True,
            effective_from_utc="2026-01-01T00:00:00Z",
            expires_at_utc="2027-01-01T00:00:00Z",
            termination_notice_days=90,
        )
        appointment = create_active_appointment(
            api, license_row["id"], distributor_name="Evergreen Beverage Co"
        )
        return beer, license_row, appointment

    def test_franchise_fee_is_levied_on_the_discounted_subtotal_not_the_raw_freight(self, api):
        """A 5.00 bbl WHOLESALER order costs 228660 cents, never 228750.

        PRD §3.7: "On the `WHOLESALER` channel only, `franchise_fee_cents` is 3
        percent of the subtotal — where the subtotal is `product_cents` plus the
        **discounted** `freight_cents` of step 4, not the raw freight — rounded
        to whole cents."

        Design: Difficulty/combinatorial_formula/landed_cost_pinned_evaluation_order_discount_before_franchise_fee
        """
        beer, license_row, appointment = self._wholesaler_scenario(api)

        order = validate_success(
            api.create_distribution_order(
                order_payload(
                    beer["id"],
                    license_row["id"],
                    bbl_requested=5.00,
                    ship_to_state_code="WA",
                    distance_miles=300,
                    requested_ship_utc="2026-08-15T15:00:00Z",
                    order_code="SO-3001",
                ),
                ADMIN,
            ),
            201,
        )

        assert order["channel"] == ORDER_CHANNEL_WHOLESALER
        assert order["appointment_id"] == appointment["id"]
        assert order["state"] == ORDER_SUBMITTED
        assert_cents(order["product_cents"], 210000, "product_cents")
        assert_cents(order["freight_cents"], 12000, "freight_cents")
        assert_cents(order["franchise_fee_cents"], 6660, "franchise_fee_cents")
        assert_cents(order["landed_cost_cents"], 228660, "landed_cost_cents")
        assert order["franchise_fee_cents"] != 6750, (
            "6750 is the fee taken on the un-discounted 225000 subtotal"
        )
        assert order["landed_cost_cents"] != 228750, (
            "228750 is the total produced by the wrong step order"
        )

    def test_the_discount_tier_is_chosen_from_the_rounded_product_value(self, api):
        """A product value of 210000 cents takes the 20 percent freight tier.

        PRD §3.7: "The freight discount percentage is chosen from the
        **rounded** `product_cents` of step 1, never from the un-rounded
        product. A `product_cents` of at least 400,000 cents (four thousand
        dollars) earns 30 percent; failing that, at least 200,000 cents earns 20
        percent; failing that, at least 100,000 cents earns 10 percent; below
        that the discount is nothing."

        Design: Difficulty/combinatorial_formula/landed_cost_pinned_evaluation_order_discount_before_franchise_fee
        """
        beer, license_row, appointment = self._wholesaler_scenario(api)

        order = validate_success(
            api.create_distribution_order(
                order_payload(
                    beer["id"],
                    license_row["id"],
                    bbl_requested=5.00,
                    ship_to_state_code="WA",
                    distance_miles=300,
                    requested_ship_utc="2026-08-15T15:00:00Z",
                    order_code="SO-3002",
                ),
                ADMIN,
            ),
            201,
        )
        appointment_row = validate_success(
            api.get_distributor_appointment(appointment["id"], ADMIN)
        )

        # Raw freight is 300 * 30 + 5.00 * 1200 = 15000 cents; the 20 percent
        # tier removes 3000 of it.
        assert_cents(order["freight_cents"], 12000, "freight_cents")
        assert order["freight_cents"] != 15000, "the discount was never applied"
        assert order["freight_cents"] != 13500, "a 10 percent tier was chosen"
        assert appointment_row["brand_scope"] == SCOPE_ALL_BRANDS


class TestOunceAggregationBeforeBarrelRounding:
    def _four_growlers(self, api):
        bootstrap_brewery(api)
        beer = validate_success(
            api.create_beer(
                {
                    "name": "Ridgeline IPA",
                    "style": "West Coast IPA",
                    "abv_pct": 6.8,
                    "price_per_bbl_cents": 42000,
                    "requires_formula": False,
                },
                ADMIN,
            ),
            201,
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
        keg = create_tapped_keg(api, run["id"], KEG_SIZE_HALF_BBL, keg_serial="KEG-0001")
        pours = []
        for _ in range(4):
            pours.append(
                validate_success(
                    api.create_taproom_pour(
                        growler_payload(
                            keg["id"],
                            USER_TAPROOM_2,
                            sanitizer_ppm=200,
                            contact_time_seconds=90,
                            price_cents=2200,
                        ),
                        TAPROOM,
                    ),
                    201,
                )
            )
        set_clock(api, "2026-09-01T00:00:00Z")
        return keg, pours

    def test_each_growler_is_logged_at_its_full_sixty_four_ounces(self, api):
        """Four 64 oz fills draw 256.00 oz off the keg and each verdict is PASS.

        PRD §3.5: "A `SAMPLE_4OZ` pour is 4 ounces, a `HALF_PINT_8OZ` is 8, a
        `PINT_16OZ` is 16, a `CROWLER_32OZ` is 32 and a `GROWLER_64OZ` is 64,
        and the chosen figure is stored as the pour's `volume_oz`."

        Design: Difficulty/combinatorial_formula/taproom_ounce_aggregation_before_barrel_rounding_cascades_into_tax
        """
        keg, pours = self._four_growlers(api)

        for pour in pours:
            assert_oz(pour["volume_oz"], 64, "volume_oz")
            assert pour["sanitation_verdict"] == SANITATION_PASS
            assert pour["poured_by_user_id"] == USER_TAPROOM_1

        stored = validate_success(api.get_keg_asset(keg["id"], CELLAR))
        assert_oz(stored["poured_volume_oz"], 256.00, "poured_volume_oz")
        assert_oz(stored["remaining_volume_oz"], 1728.00, "remaining_volume_oz")

    def test_ounces_are_summed_before_the_single_conversion_to_barrels(self, api):
        """256 oz converts once to 0.065 bbl, cascading to 23 / 36 / 59 cents.

        PRD §3.8: "Under a `taproom_basis` of `METERED_POUR`, the brewery is
        taxed only on what it actually served. `taproom_bbl` is the sum of
        `volume_oz` over every taproom pour whose `poured_at_utc` falls inside
        the window, regardless of `container_type` — a four-ounce sample counts
        for exactly its four ounces and a growler for its sixty-four — divided
        by the 3,968 fluid ounces in a barrel, rounded half up to three decimal
        places."

        Design: Difficulty/combinatorial_formula/taproom_ounce_aggregation_before_barrel_rounding_cascades_into_tax
        """
        self._four_growlers(api)

        report = validate_success(
            api.create_excise_report(
                excise_report_payload(
                    period_start_utc="2026-08-01T00:00:00Z",
                    period_end_utc="2026-09-01T00:00:00Z",
                    taproom_basis=BASIS_METERED_POUR,
                ),
                ADMIN,
            ),
            201,
        )

        assert_bbl(report["taproom_bbl"], 0.065, "taproom_bbl")
        assert_bbl(report["total_taxable_bbl"], 0.065, "total_taxable_bbl")
        assert_cents(report["federal_tax_cents"], 23, "federal_tax_cents")
        assert_cents(report["state_tax_cents"], 36, "state_tax_cents")
        assert_cents(report["total_tax_due_cents"], 59, "total_tax_due_cents")
        assert report["taproom_bbl"] != 0.064, (
            "0.064 is the figure produced by rounding each growler on its own"
        )
