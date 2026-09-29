"""
Pinned arithmetic: step ladders, shrink factors, waterfalls and greedy walks.

Every figure asserted here is re-derived from the constants and the rounding
rules the PRD fixes, so an implementation that reorders two steps or rounds at
the wrong moment lands on a visibly different number.
"""

from test_helpers import fixtures as fx
from test_helpers import get_success_data, validate_error, validate_paginated, validate_success
from test_helpers.api_errors import ApiErrorId
from test_helpers.assertions import (
    assert_1dp,
    assert_2dp,
    assert_3dp,
    assert_instant_equals,
    assert_integer_cents,
    assert_not_null,
    assert_null,
    assert_plant_posture,
)
from test_helpers.test_users import (
    COMPLIANCE_OFFICER,
    GRAIN_ACCOUNTANT,
    GRAIN_BUYER,
    LOGISTICS_COORDINATOR,
    PLANT_MANAGER,
    PROCESS_OPERATOR,
    RISK_MANAGER,
    SCALE_OPERATOR,
)

_BIG_GRADE = {
    "moisture_pct": 16.50,
    "test_weight_lb_per_bu": 53.2,
    "foreign_material_pct": 3.40,
    "damaged_kernels_pct": 6.00,
    "aflatoxin_ppb": 8,
}


def _big_load_graded(api):
    """A 5,500,000 lb load off a 300,000 lb tare, graded on every discount ladder."""
    plant = fx.commission_plant(
        api, base_grind_cap_bushels=120000, coverage_floor_bushels=5000
    )
    contract = fx.priced_contract(api, 458.0, supplier_name="Cedar Ridge Elevator")
    delivery = fx.book_delivery(
        api, contract["id"], ticket_number="TK-BIG",
        gross_weight_lbs=5500000, tare_weight_lbs=300000.00,
    )
    graded = fx.grade_delivery(api, delivery["id"], **_BIG_GRADE)
    return {"plant": plant, "contract": contract, "delivery": graded}


class TestSettlementStacksEveryDiscountLadder:
    """All four ladders and the moisture shrink on one load."""

    def test_the_four_discount_components_are_rounded_independently_before_they_are_added(self, api):
        """Twelve, two eighty, six and eight cents come off a 92857.14 bushel load.

        PRD 3.3: "Each component — `moisture_discount_cents`,
        `test_weight_discount_cents`, `foreign_material_discount_cents` and
        `damage_discount_cents` — is its own step count multiplied by its own rate,
        **rounded half up to two decimals independently**, before any of them are
        added together."

        PRD 3.3: "the net wet weight is the gross weight less the tare weight, and
        `gross_wet_bushels` is that net weight divided by 56.0 pounds per bushel,
        rounded half up to two decimals. **Second**, the load is shrunk to the 15.0
        percent moisture dry basis: the shrink factor is 100 less the recorded
        moisture percentage, divided by 100 less 15.0, and `net_dry_bushels` is
        `gross_wet_bushels` multiplied by that factor, rounded half up to two
        decimals."

        Design: Corner/calculations/settlement_stacks_all_four_discount_components_on_a_unit_train_load
        """
        graded = _big_load_graded(api)["delivery"]

        assert_2dp(graded["gross_wet_bushels"], 92857.14, "gross_wet_bushels")
        assert_2dp(graded["net_dry_bushels"], 91218.48, "net_dry_bushels")
        assert_2dp(graded["moisture_discount_cents"], 12.00, "moisture_discount_cents")
        assert_2dp(graded["test_weight_discount_cents"], 2.80, "test_weight_discount_cents")
        assert_2dp(
            graded["foreign_material_discount_cents"], 6.00, "foreign_material_discount_cents"
        )
        assert_2dp(graded["damage_discount_cents"], 8.00, "damage_discount_cents")
        assert_2dp(graded["discount_cents_per_bushel"], 28.80, "discount_cents_per_bushel")

    def test_settlement_prices_the_dry_bushels_at_the_discounted_price(self, api):
        """91218.48 dry bushels at 411.20 cents settle at 37509039 cents.

        PRD 3.3: "`net_price_cents_per_bushel` is the contract gross price less
        that total discount, with a floor of 0.00 so a load can never carry a
        negative price; and at settlement `settlement_amount_cents` is
        `net_dry_bushels` multiplied by `net_price_cents_per_bushel`, rounded half
        up to a whole number of cents."

        PRD 3.3: "The contract's `bushels_delivered` is recomputed as the sum of
        `net_dry_bushels` over its own `SETTLED` deliveries — `REJECTED` and
        `GRADED` loads never count — and the contract's fill dimension advances
        accordingly: to `PARTIALLY_FILLED` when delivered bushels are now strictly
        greater than zero but still strictly less than `bushels_contracted`"

        Design: Corner/calculations/settlement_stacks_all_four_discount_components_on_a_unit_train_load
        """
        scenario = _big_load_graded(api)

        settled = validate_success(
            api.settle_delivery(scenario["delivery"]["id"], GRAIN_ACCOUNTANT), 200
        )

        assert_2dp(settled["net_price_cents_per_bushel"], 411.20, "net_price_cents_per_bushel")
        assert_integer_cents(settled["settlement_amount_cents"], "settlement_amount_cents")
        assert settled["settlement_amount_cents"] == 37509039, settled["settlement_amount_cents"]

        contract = get_success_data(api.get_contract(scenario["contract"]["id"], GRAIN_BUYER))
        assert_2dp(contract["bushels_delivered"], 91218.48, "bushels_delivered")
        assert contract["status"] == "PARTIALLY_FILLED", contract["status"]
        plant = get_success_data(api.get_plant(scenario["plant"]["id"], PLANT_MANAGER))
        assert_2dp(plant["corn_inventory_bushels"], 91218.48, "corn_inventory_bushels")


def _two_booked_loads(api):
    """TK-A and TK-B, identical 78640/26000 lb tickets on one PRICED contract."""
    plant = fx.commission_plant(
        api, base_grind_cap_bushels=120000, coverage_floor_bushels=5000
    )
    contract = fx.priced_contract(api, 458.0, supplier_name="Cedar Ridge Elevator")
    first = fx.book_delivery(
        api, contract["id"], ticket_number="TK-A",
        gross_weight_lbs=78640, tare_weight_lbs=26000.00,
    )
    second = fx.book_delivery(
        api, contract["id"], ticket_number="TK-B",
        gross_weight_lbs=78640, tare_weight_lbs=26000.00,
    )
    return {"plant": plant, "contract": contract, "first": first, "second": second}


def _grade_at_moisture(api, delivery_id, moisture_pct):
    return fx.grade_delivery(
        api,
        delivery_id,
        moisture_pct=moisture_pct,
        test_weight_lb_per_bu=54.0,
        foreign_material_pct=3.00,
        damaged_kernels_pct=5.00,
        aflatoxin_ppb=4,
    )


class TestMoistureStepCountIsCeiled:
    """One extra hundredth of a percent buys a whole second step."""

    def test_moisture_of_exactly_fifteen_and_a_half_is_a_single_whole_step(self, api):
        """Fifty hundredths over the basis divide into exactly one step of 4.00 cents.

        PRD 3.3: "**Moisture steps**: take the moisture hundredths less 1,500 (that
        is, the excess over 15.00 percent), treat any negative result as zero,
        divide by 50 — one step per half a percentage point — and round the quotient
        **up** to the next whole step. Each step costs 4.0 cents per bushel."

        Design: Corner/calculations/moisture_discount_ceils_at_the_half_percent_step_boundary
        """
        scenario = _two_booked_loads(api)

        graded = _grade_at_moisture(api, scenario["first"]["id"], 15.50)
        assert_2dp(graded["gross_wet_bushels"], 940.00, "gross_wet_bushels")
        assert_2dp(graded["net_dry_bushels"], 934.47, "net_dry_bushels")
        assert_2dp(graded["moisture_discount_cents"], 4.00, "moisture_discount_cents")
        assert_2dp(graded["net_price_cents_per_bushel"], 436.00, "net_price_cents_per_bushel")

        settled = get_success_data(api.settle_delivery(graded["id"], GRAIN_ACCOUNTANT))
        assert settled["settlement_amount_cents"] == 407429, settled["settlement_amount_cents"]

    def test_one_extra_hundredth_of_moisture_rolls_into_a_second_whole_step(self, api):
        """15.51 percent costs 8.00 cents and 3785 cents on an otherwise identical load.

        PRD 3.3: "**Moisture steps**: take the moisture hundredths less 1,500 (that
        is, the excess over 15.00 percent), treat any negative result as zero,
        divide by 50 — one step per half a percentage point — and round the quotient
        **up** to the next whole step. Each step costs 4.0 cents per bushel."

        PRD 3.3: "The delivered bushels are then added to the plant's
        `corn_inventory_bushels`."

        Design: Corner/calculations/moisture_discount_ceils_at_the_half_percent_step_boundary
        """
        scenario = _two_booked_loads(api)

        wet = _grade_at_moisture(api, scenario["first"]["id"], 15.50)
        dry_step = _grade_at_moisture(api, scenario["second"]["id"], 15.51)

        assert_2dp(dry_step["gross_wet_bushels"], 940.00, "gross_wet_bushels")
        assert_2dp(dry_step["net_dry_bushels"], 934.36, "net_dry_bushels")
        assert_2dp(dry_step["moisture_discount_cents"], 8.00, "moisture_discount_cents")
        assert_2dp(dry_step["net_price_cents_per_bushel"], 432.00, "net_price_cents_per_bushel")

        first_amount = get_success_data(
            api.settle_delivery(wet["id"], GRAIN_ACCOUNTANT)
        )["settlement_amount_cents"]
        second_amount = get_success_data(
            api.settle_delivery(dry_step["id"], GRAIN_ACCOUNTANT)
        )["settlement_amount_cents"]

        assert first_amount == 407429, first_amount
        assert second_amount == 403644, second_amount
        assert first_amount - second_amount == 3785, first_amount - second_amount

        plant = get_success_data(api.get_plant(scenario["plant"]["id"], PLANT_MANAGER))
        assert_2dp(plant["corn_inventory_bushels"], 1868.83, "corn_inventory_bushels")


def _fermenting_batch_on_high_test_weight_corn(api):
    """1500.00 settled bushels, FB-1 charged with 900.00 at 56.0 lb/bu and fermenting."""
    plant = fx.commission_plant(
        api, base_grind_cap_bushels=120000, coverage_floor_bushels=5000
    )
    tank = fx.commission_tank(
        api, "T-101", "ETHANOL_200_PROOF", 1000000.00, opening_gallons=0.00
    )
    contract = fx.priced_contract(api, 458.0, supplier_name="Cedar Ridge Elevator")
    settled = fx.settled_load(
        api,
        contract["id"],
        {"ticket_number": "TK-0001", "gross_weight_lbs": 110000, "tare_weight_lbs": 26000.00},
    )
    batch = fx.charge_batch(
        api,
        tank["id"],
        batch_code="FB-1",
        corn_bushels_charged=900.00,
        charge_test_weight_lb_per_bu=56.0,
    )
    reading = fx.append_health_reading(
        api,
        batch["id"],
        hours_elapsed=12.0,
        lactic_acid_ppm=400,
        acetic_acid_ppm=150,
        temperature_c=32.0,
    )
    return {
        "plant": plant,
        "tank": tank,
        "contract": contract,
        "settled": settled,
        "batch": batch,
        "reading": reading,
    }


class TestRollingYieldCountsOnlyCompletedBatches:
    """A batch under way is outside the input set of the plant's rolling yield."""

    def test_a_distilling_batch_freezes_its_yield_but_leaves_the_plant_on_the_default(self, api):
        """The 56.0 lb charge earns a 0.030 bonus, yet the plant still reports 2.850.

        PRD 3.4: "First, `starch_bonus_gal_per_bushel`: convert
        `charge_test_weight_lb_per_bu` into whole tenths of a pound by multiplying
        by 10 and rounding half up to a whole number, take the excess of that
        figure over 540 tenths (the 54.0 pound-per-bushel basis) treating any
        negative result as zero, multiply by 0.0015 gallons per tenth, round half
        up to three decimals, and cap the result at 0.090 gallons per bushel."

        PRD 3.4: "`rolling_yield_gal_per_bushel` is then re-derived across all
        completed batches as the sum of `ethanol_gallons_produced` divided by the
        sum of `corn_bushels_charged` over batches whose `status` is `COMPLETED`,
        rounded half up to three decimals, falling back to 2.850 when no completed
        batch exists."

        Design: Corner/calculations/rolling_yield_counts_only_completed_batches
        """
        scenario = _fermenting_batch_on_high_test_weight_corn(api)
        assert scenario["settled"]["settlement_amount_cents"] == 660000, scenario["settled"][
            "settlement_amount_cents"
        ]
        assert_2dp(scenario["reading"]["reading_score"], 100.00, "reading_score")

        distilling = validate_success(
            api.distill_batch(scenario["batch"]["id"], PROCESS_OPERATOR), 200
        )
        assert distilling["status"] == "DISTILLING", distilling["status"]
        assert_3dp(distilling["starch_bonus_gal_per_bushel"], 0.030, "starch_bonus_gal_per_bushel")
        assert_3dp(
            distilling["effective_yield_gal_per_bushel"], 2.880, "effective_yield_gal_per_bushel"
        )

        plant = get_success_data(api.get_plant(scenario["plant"]["id"], PLANT_MANAGER))
        assert_3dp(plant["rolling_yield_gal_per_bushel"], 2.850, "rolling_yield_gal_per_bushel")

    def test_completion_publishes_the_ratio_the_co_products_and_the_credits(self, api):
        """2592.00 gallons over 900.00 bushels is exactly 2.880 once the batch completes.

        PRD 3.4: "`ethanol_gallons_produced` is `corn_bushels_charged` multiplied by
        `effective_yield_gal_per_bushel`, rounded half up to two decimals;
        `ddgs_tons_produced` is `corn_bushels_charged` multiplied by 17.0 pounds of
        distillers grains per bushel, divided by 2,000 pounds per short ton, rounded
        half up to three decimals; and `corn_oil_lbs_produced` is
        `corn_bushels_charged` multiplied by 0.600 pounds of corn oil per bushel,
        rounded half up to two decimals."

        PRD 3.7: "`rin_eligible_gallons` is the batch's `ethanol_gallons_produced`
        multiplied by a denaturant gross-up of 1.02 and by a D6 equivalence value of
        1.0, rounded half up to two decimals. The tradeable count, `rin_count`, is
        then the **floor** of that eligible-gallons figure and never a rounding"

        Design: Corner/calculations/rolling_yield_counts_only_completed_batches
        """
        scenario = _fermenting_batch_on_high_test_weight_corn(api)
        get_success_data(api.distill_batch(scenario["batch"]["id"], PROCESS_OPERATOR))

        completed = validate_success(
            api.complete_batch(scenario["batch"]["id"], PROCESS_OPERATOR), 200
        )
        assert completed["status"] == "COMPLETED", completed["status"]
        assert_2dp(completed["ethanol_gallons_produced"], 2592.00, "ethanol_gallons_produced")
        assert_3dp(completed["ddgs_tons_produced"], 7.650, "ddgs_tons_produced")
        assert_2dp(completed["corn_oil_lbs_produced"], 540.00, "corn_oil_lbs_produced")

        plant = get_success_data(api.get_plant(scenario["plant"]["id"], PLANT_MANAGER))
        assert_3dp(plant["rolling_yield_gal_per_bushel"], 2.880, "rolling_yield_gal_per_bushel")
        assert_3dp(plant["ddgs_inventory_tons"], 7.650, "ddgs_inventory_tons")
        assert_2dp(plant["corn_oil_inventory_lbs"], 540.00, "corn_oil_inventory_lbs")

        tank = get_success_data(api.get_tank(scenario["tank"]["id"], PROCESS_OPERATOR))
        assert_2dp(tank["current_gallons"], 2592.00, "current_gallons")

        rows, _ = validate_paginated(
            api.list_rin_batches(PLANT_MANAGER, {"fermentation_batch_id": scenario["batch"]["id"]})
        )
        assert len(rows) == 1, f"exactly one credit batch is minted, got {rows!r}"
        assert_2dp(rows[0]["rin_eligible_gallons"], 2643.84, "rin_eligible_gallons")
        assert rows[0]["rin_count"] == 2643, rows[0]["rin_count"]


class TestHedgeUnitSizesArePerCommodity:
    """The contract multiplier is chosen by commodity, never shared."""

    def test_corn_stamps_five_thousand_and_natural_gas_ten_thousand(self, api):
        """Twenty long corn lots ten cents offside lose exactly 1000000 cents.

        PRD 3.9: "The system stamps the contract `unit_size` from the commodity —
        5000 bushels for corn, 29000 gallons for ethanol, 10000 million British
        thermal units for natural gas"

        PRD 3.9: "otherwise the same sign multiplied by the difference of the
        current mark less `entry_price`, multiplied by the `unit_size` and by
        `contracts_open`, rounded half up to a whole number of cents."

        PRD 3.1: "A posting also re-prices the futures book: every hedge position
        whose `status` is `OPEN` or `PARTIALLY_CLOSED` has its
        `unrealized_pnl_cents` re-derived against the new mark for its commodity
        and its own `version` incremented, while positions already `CLOSED` are
        left untouched."

        Design: Corner/calculations/hedge_unit_sizes_are_applied_per_commodity
        """
        plant = fx.commission_plant(
            api, base_grind_cap_bushels=120000, coverage_floor_bushels=5000
        )
        fx.post_marks(
            api,
            plant["id"],
            RISK_MANAGER,
            marks_effective_month="2026-10",
            mark_corn_cents_per_bushel=440.00,
            mark_ethanol_cents_per_gallon=178.00,
            mark_natgas_cents_per_mmbtu=320.00,
            mark_soybean_meal_usd_per_ton=330.00,
            mark_sbo_cents_per_lb=48.00,
        )

        corn = fx.open_hedge(
            api,
            position_code="HP-CORN",
            commodity="CORN",
            direction="LONG",
            contract_month="2026-10",
            contracts=20,
            entry_price=450.00,
        )
        natgas = fx.open_hedge(
            api,
            position_code="HP-NG",
            commodity="NATGAS",
            direction="SHORT",
            contract_month="2026-10",
            contracts=3,
            entry_price=330.00,
        )

        assert corn["unit_size"] == 5000, corn["unit_size"]
        assert natgas["unit_size"] == 10000, natgas["unit_size"]
        assert corn["realized_pnl_cents"] == 0, corn["realized_pnl_cents"]
        assert corn["contracts_open"] == 20, corn["contracts_open"]
        assert natgas["status"] == "OPEN", natgas["status"]
        assert natgas["contracts_closed"] == 0, natgas["contracts_closed"]

        fx.post_marks(
            api,
            plant["id"],
            RISK_MANAGER,
            marks_effective_month="2026-10",
            mark_corn_cents_per_bushel=440.00,
            mark_ethanol_cents_per_gallon=178.00,
            mark_natgas_cents_per_mmbtu=320.00,
            mark_soybean_meal_usd_per_ton=330.00,
            mark_sbo_cents_per_lb=48.00,
        )

        repriced_corn = get_success_data(api.get_hedge_position(corn["id"], RISK_MANAGER))
        repriced_natgas = get_success_data(api.get_hedge_position(natgas["id"], RISK_MANAGER))
        assert repriced_corn["unrealized_pnl_cents"] == -1000000, repriced_corn[
            "unrealized_pnl_cents"
        ]
        assert repriced_natgas["unrealized_pnl_cents"] == 300000, repriced_natgas[
            "unrealized_pnl_cents"
        ]


def _two_credit_batches_and_a_small_train(api):
    """2616 and 290 credits against a train that has loaded only 500.00 gallons."""
    plant = fx.commission_plant(
        api, base_grind_cap_bushels=120000, coverage_floor_bushels=5000
    )
    fx.advance_clock(api, "2026-09-01T00:00:00Z")
    neat = fx.commission_tank(
        api, "T-101", "ETHANOL_200_PROOF", 1000000.00, opening_gallons=0.00
    )
    finished = fx.commission_tank(
        api, "T-301", "DENATURED_E100", 1000000.00, opening_gallons=1000.00
    )
    contract = fx.priced_contract(api, 458.0, supplier_name="Cedar Ridge Elevator")
    fx.settled_load(
        api,
        contract["id"],
        {"ticket_number": "TK-0001", "gross_weight_lbs": 110000, "tare_weight_lbs": 26000.00},
    )
    first = fx.completed_batch(
        api, neat["id"], None,
        batch_code="FB-1", corn_bushels_charged=900.00, charge_test_weight_lb_per_bu=54.0,
    )
    second = fx.completed_batch(
        api, neat["id"], None,
        batch_code="FB-2", corn_bushels_charged=100.00, charge_test_weight_lb_per_bu=54.0,
    )
    track = fx.commission_track(api, track_code="TRK-A", spot_capacity=110)
    shipment = fx.loaded_shipment(
        api,
        track["id"],
        finished["id"],
        track["version"],
        shipment_code="SH-1",
        railcar_count=1,
        gallons_per_railcar=500.00,
        window_start="2026-09-04T06:00:00Z",
        window_end="2026-09-04T10:00:00Z",
        price_cents_per_gallon=181.50,
    )
    assert_2dp(shipment["loaded_gallons"], 500.00, "loaded_gallons")
    return {
        "plant": plant,
        "first": first,
        "second": second,
        "shipment": shipment,
    }


class TestRinSeparationStopsAtTheFirstMisfit:
    """The greedy walk halts rather than skipping ahead to a smaller row."""

    def test_the_bill_of_lading_issues_while_neither_credit_batch_separates(self, api):
        """A 500 gallon allowance cannot fit 2616 credits, so the walk never advances.

        PRD 3.8: "The system walks that ordered list accumulating a running total,
        and separates a candidate only while the running total plus that
        candidate's `rin_count` remains at or below the allowance. **At the first
        candidate that does not fit, the walk stops.** It does not skip that
        candidate and keep scanning for a smaller one that would fit — a credit
        batch is never split, and no later batch is examined once an earlier one
        has been passed over."

        Design: Corner/calculations/rin_separation_stops_at_the_first_row_that_does_not_fit
        """
        scenario = _two_credit_batches_and_a_small_train(api)

        documented = validate_success(
            api.issue_bill_of_lading(
                scenario["shipment"]["id"], {"bol_number": "BOL-0001"}, LOGISTICS_COORDINATOR
            ),
            200,
        )
        assert documented["billing_status"] == "BOL_ISSUED", documented["billing_status"]
        assert documented["bol_number"] == "BOL-0001", documented["bol_number"]

        for key, eligible, count in (
            ("first", 2616.30, 2616),
            ("second", 290.70, 290),
        ):
            rows, _ = validate_paginated(
                api.list_rin_batches(
                    PLANT_MANAGER, {"fermentation_batch_id": scenario[key]["id"]}
                )
            )
            assert len(rows) == 1, f"{key}: expected one credit batch, got {rows!r}"
            assert_2dp(rows[0]["rin_eligible_gallons"], eligible, "rin_eligible_gallons")
            assert rows[0]["rin_count"] == count, rows[0]["rin_count"]
            assert rows[0]["status"] == "GENERATED", rows[0]["status"]
            assert_null(rows[0]["separated_shipment_id"], "separated_shipment_id")

    def test_the_plant_counts_every_generated_credit_and_none_separated(self, api):
        """2906 credits exist, the separated tally stays zero and both rows are D6 for 2026.

        PRD 3.8: "`rin_generated_count` sums `rin_count` across `GENERATED`,
        `SEPARATED` and `RETIRED` batches; `rin_separated_count` sums across
        `SEPARATED` and `RETIRED`; and `rin_retired_count` sums across `RETIRED`
        alone."

        PRD 3.8: "the system mints exactly one `RinBatch` row recording the
        `fermentation_batch_id` it came from, a `d_code` that is always 6 because
        corn starch ethanol is a D6 renewable fuel, and a `rin_year` taken as the
        UTC calendar year of the generating batch's `completed_at`."

        Design: Corner/calculations/rin_separation_stops_at_the_first_row_that_does_not_fit
        """
        scenario = _two_credit_batches_and_a_small_train(api)
        get_success_data(
            api.issue_bill_of_lading(
                scenario["shipment"]["id"], {"bol_number": "BOL-0001"}, LOGISTICS_COORDINATOR
            )
        )

        plant = get_success_data(api.get_plant(scenario["plant"]["id"], PLANT_MANAGER))
        assert plant["rin_generated_count"] == 2906, plant["rin_generated_count"]
        assert plant["rin_separated_count"] == 0, plant["rin_separated_count"]

        separated, meta = validate_paginated(
            api.list_rin_batches(PLANT_MANAGER, {"status": "SEPARATED"})
        )
        assert separated == [], f"nothing may have separated, got {separated!r}"
        assert meta["total_count"] == 0, meta["total_count"]

        everything, _ = validate_paginated(api.list_rin_batches(PLANT_MANAGER))
        assert len(everything) == 2, f"two credit batches were minted, got {everything!r}"
        for row in everything:
            assert row["d_code"] == 6, row["d_code"]
            assert row["rin_year"] == 2026, row["rin_year"]


def _condition_with_three_readings(api):
    """
    VOC-1 with a 24 hour window, the clock at 2026-09-05T00:00:00Z and three
    readings: two inside the window and one sitting exactly on its excluded
    start boundary.
    """
    plant = fx.commission_plant(api)
    fx.advance_clock(api, "2026-09-05T00:00:00Z")
    condition = fx.register_condition(
        api,
        condition_code="VOC-1",
        parameter_name="VOC",
        limit_value=12.500,
        averaging_period_hours=24,
        severity="MINOR",
    )

    reading_ids = []
    for measured_at, value, reference in (
        ("2026-09-04T12:00:00Z", 13.000, "R-1"),
        ("2026-09-04T18:00:00Z", 12.400, "R-2"),
        ("2026-09-04T00:00:00Z", 2.000, "R-3"),
    ):
        appended = validate_success(
            api.create_permit_reading(
                condition["id"],
                {
                    "measured_at": measured_at,
                    "value": value,
                    "sample_reference": reference,
                },
                PROCESS_OPERATOR,
            ),
            201,
        )
        reading_ids.append(appended["id"])

    return {"plant": plant, "condition": condition, "reading_ids": reading_ids}


class TestPermitWindowExcludesItsStartInstant:
    """A 24 hour window that admits 12.700 and refuses to be diluted to 9.133."""

    def test_the_boundary_reading_is_stored_but_left_out_of_the_average(self, api):
        """Three rows exist, two are in the window and the average is 12.700.

        PRD 3.9: "The window is then **start-exclusive and end-inclusive**: a
        reading whose `measured_at` falls strictly after the start and at or
        before the clock is inside; a reading whose `measured_at` equals the
        start instant exactly is **outside**. `readings_in_window` is the count
        of readings inside, and `rolling_average_value` is the sum of their
        values divided by that count, rounded half up to three decimals — or
        null when the window is empty, which is not the same as zero."

        PRD 3.9: "Readings of 13.000 and 12.400 inside it average 12.700 and
        breach the limit. A third reading of 2.000 measured exactly at
        2026-09-04T00:00:00Z sits on the excluded start boundary and is left out;
        wrongly admitting it would give 9.133 and mask the breach entirely."

        Design: Corner/calculations/permit_rolling_average_excludes_the_reading_at_the_window_start
        """
        scenario = _condition_with_three_readings(api)

        condition = get_success_data(
            api.get_permit_condition(scenario["condition"]["id"], COMPLIANCE_OFFICER)
        )
        assert condition["readings_in_window"] == 2, condition["readings_in_window"]
        assert_3dp(condition["rolling_average_value"], 12.700, "rolling_average_value")

        rows, _ = validate_paginated(
            api.list_permit_readings(scenario["condition"]["id"], COMPLIANCE_OFFICER)
        )
        assert len(rows) == 3, f"every appended reading is kept, got {rows!r}"
        stored_ids = {row["id"] for row in rows}
        assert stored_ids == set(scenario["reading_ids"]), stored_ids

    def test_the_breach_is_one_episode_and_the_plant_drops_to_ninety_percent(self, api):
        """Two more appends after the crossing leave the episode count at one.

        PRD 3.9: "Crossing into `EXCEEDANCE` from `COMPLIANT` increments
        `exceedance_count`, records `last_exceedance_at`, and re-derives both the
        plant's `compliance_posture` and its grind cap by the worst-of rule of
        §2.8, which is how a `CRITICAL` water-discharge breach halts corn
        grinding entirely."

        PRD 3.9: "Further readings recompute the average and leave the status at
        `EXCEEDANCE` — and crucially they do **not** increment `exceedance_count`
        a second time, since the count records episodes rather than samples."

        PRD 2.8: "each permit condition in exceedance raises the posture to at
        least `RESTRICTED` when its `severity` is `MINOR`"

        Design: Corner/calculations/permit_rolling_average_excludes_the_reading_at_the_window_start
        """
        scenario = _condition_with_three_readings(api)

        condition = get_success_data(
            api.get_permit_condition(scenario["condition"]["id"], COMPLIANCE_OFFICER)
        )
        assert condition["status"] == "EXCEEDANCE", condition["status"]
        assert condition["exceedance_count"] == 1, condition["exceedance_count"]
        assert_instant_equals(
            condition["last_exceedance_at"], "2026-09-05T00:00:00Z", "last_exceedance_at"
        )

        plant = get_success_data(api.get_plant(scenario["plant"]["id"], PLANT_MANAGER))
        assert_plant_posture(plant, "RESTRICTED", "SHORT")
        assert plant["daily_grind_cap_bushels"] == 81000, plant["daily_grind_cap_bushels"]


def _four_projects_three_certified(api):
    """
    CP-1 (FULL, verified 8.0), CP-2 (PROVISIONAL, stacked on CP-1, verified 6.0)
    and CP-3 (FULL, verified 5.0) certified in that order, with CP-4 (FULL)
    submitted and awaiting review.
    """
    plant = fx.commission_plant(api)
    first = fx.certified_project(
        api,
        8.0,
        project_code="CP-1",
        project_name="Fermenter CO2 capture",
        project_type="CARBON_CAPTURE",
        claimed_reduction_g_per_mj=9.0,
        certification_tier="FULL",
    )
    second = fx.certified_project(
        api,
        6.0,
        project_code="CP-2",
        project_name="CHP retrofit phase two",
        project_type="COMBINED_HEAT_POWER",
        claimed_reduction_g_per_mj=7.0,
        certification_tier="PROVISIONAL",
        predecessor_project_id=first["id"],
    )
    third = fx.certified_project(
        api,
        5.0,
        project_code="CP-3",
        project_name="Corn oil extraction upgrade",
        project_type="CORN_OIL_EXTRACTION",
        claimed_reduction_g_per_mj=5.0,
        certification_tier="FULL",
    )
    fourth = fx.submitted_project(
        api,
        project_code="CP-4",
        project_name="Low till feedstock program",
        project_type="LOW_TILL_FEEDSTOCK",
        claimed_reduction_g_per_mj=3.0,
        certification_tier="FULL",
    )
    return {
        "plant": plant,
        "first": first,
        "second": second,
        "third": third,
        "fourth": fourth,
    }


class TestCarbonWaterfallTruncatesAndZeroes:
    """A 12.0 allowance spent 8.000, 2.100, 1.900, 0.000 in certification order."""

    def test_the_straddling_project_takes_the_headroom_and_the_last_takes_nothing(self, api):
        """Certifying CP-4 re-runs the whole waterfall and credits it 0.000.

        PRD 3.8: "For each project in that order, take a tier factor of 1.00 for
        `FULL` and 0.70 for `PROVISIONAL`, and a stacking factor of 0.50 where
        `predecessor_project_id` is set and 1.00 where it is null."

        PRD 3.8: "The project's `credited_reduction_g_per_mj` is the **lesser** of
        that raw figure and the remaining allowance, and the allowance is then
        reduced by the credited amount, rounded half up to three decimals."

        PRD 3.8: "The project straddling the cap is truncated to whatever
        allowance is left, and **every project after it is credited exactly
        0.000** — order, not merit, decides who is cut."

        Design: Corner/calculations/ci_waterfall_truncates_the_straddling_project_and_zeroes_the_rest
        """
        scenario = _four_projects_three_certified(api)

        reviewed = get_success_data(
            api.review_carbon_project(
                scenario["fourth"]["id"],
                {"determination": "CERTIFY", "verified_reduction_g_per_mj": 3.0},
                PLANT_MANAGER,
            )
        )
        assert reviewed["verification_status"] == "CERTIFIED", reviewed["verification_status"]
        assert_1dp(reviewed["verified_reduction_g_per_mj"], 3.0, "verified_reduction_g_per_mj")
        assert_3dp(reviewed["credited_reduction_g_per_mj"], 0.000, "credited_reduction_g_per_mj")

        for key, credited in (
            ("first", 8.000),
            ("second", 2.100),
            ("third", 1.900),
        ):
            row = get_success_data(
                api.get_carbon_project(scenario[key]["id"], COMPLIANCE_OFFICER)
            )
            assert_3dp(row["credited_reduction_g_per_mj"], credited, "credited_reduction_g_per_mj")
            assert row["verification_status"] == "CERTIFIED", row["verification_status"]
            assert_not_null(row["certified_at"], "certified_at")

    def test_the_plant_score_and_the_lcfs_credit_follow_the_verified_figures(self, api):
        """12.000 credited grams take the score to 48.000 and the credit to 2587.943.

        PRD 3.8: "`ci_score_g_per_mj` is the plant's `baseline_ci_g_per_mj` less
        the total credited reduction, rounded half up to three decimals, and then
        floored at zero so the score is never negative."

        PRD 3.8: "`lcfs_credit_tonnes_per_million_gal` takes the shortfall of the
        score beneath a benchmark of 79.75 grams per megajoule — that shortfall
        floored at zero — multiplies it by an energy density of 81.51 megajoules
        per gallon and by one million gallons, converts grams to tonnes by
        dividing by one million, and rounds half up to three decimals."

        PRD 3.8: "Only verified reductions ever enter the waterfall; a claimed
        reduction that was never verified contributes nothing."

        PRD 3.8: "A project opens at `verification_status` `DRAFT` with
        `revision_count` at 0."

        Design: Corner/calculations/ci_waterfall_truncates_the_straddling_project_and_zeroes_the_rest
        """
        scenario = _four_projects_three_certified(api)
        get_success_data(
            api.review_carbon_project(
                scenario["fourth"]["id"],
                {"determination": "CERTIFY", "verified_reduction_g_per_mj": 3.0},
                PLANT_MANAGER,
            )
        )

        plant = get_success_data(api.get_plant(scenario["plant"]["id"], PLANT_MANAGER))
        assert_3dp(plant["ci_score_g_per_mj"], 48.000, "ci_score_g_per_mj")
        assert_3dp(
            plant["lcfs_credit_tonnes_per_million_gal"],
            2587.943,
            "lcfs_credit_tonnes_per_million_gal",
        )

        first = get_success_data(
            api.get_carbon_project(scenario["first"]["id"], COMPLIANCE_OFFICER)
        )
        assert_1dp(first["claimed_reduction_g_per_mj"], 9.0, "claimed_reduction_g_per_mj")
        assert_3dp(first["credited_reduction_g_per_mj"], 8.000, "credited_reduction_g_per_mj")

        second = get_success_data(
            api.get_carbon_project(scenario["second"]["id"], COMPLIANCE_OFFICER)
        )
        assert second["revision_count"] == 0, second["revision_count"]


def _curtailed_and_short_plant(api):
    """
    A default plant (base cap 120000, coverage floor 200000) carrying only
    150000.00 contracted bushels and one MAJOR permit exceedance, so both
    multipliers bite at once.
    """
    plant = fx.commission_plant(api)
    fx.advance_clock(api, "2026-09-05T00:00:00Z")
    tank = fx.commission_tank(api, "T-101", "ETHANOL_200_PROOF", 1000000.00)
    contract = fx.open_contract(api, bushels_contracted=150000.00)
    condition = fx.register_condition(
        api,
        condition_code="NOX-1",
        parameter_name="NOx",
        limit_value=12.500,
        averaging_period_hours=24,
        severity="MAJOR",
    )
    fx.append_permit_reading(api, condition["id"], "2026-09-04T20:00:00Z", 13.000)
    return {
        "plant": plant,
        "tank": tank,
        "contract": contract,
        "condition": condition,
    }


class TestGrindCapMultipliesBothPostures:
    """0.60 for curtailment and 0.75 for short coverage, floored once at the end."""

    def test_the_cap_falls_to_fifty_four_thousand_rather_than_either_leg_alone(self, api):
        """A curtailed and short plant grinds 54000, not 72000 and not 90000.

        PRD 2.8: "The compliance multiplier is 1.00 when the compliance posture is
        `OPEN`, 0.90 when it is `RESTRICTED`, 0.60 when it is `CURTAILED` and 0.00
        when it is `SUSPENDED`. The procurement multiplier is 1.00 when the
        procurement posture is `ADEQUATE` and 0.75 when it is `SHORT`. The base
        cap is multiplied by both multipliers **in a single expression** and the
        product is then floored to a whole number of bushels — never rounded, and
        never floored after each multiplier separately."

        PRD 3.1: "Under the default floor that makes the opening
        `daily_grind_cap_bushels` three quarters of the base cap floored to whole
        bushels — 90,000 with the default base."

        PRD 2.8: "each permit condition in exceedance raises the posture to at
        least `RESTRICTED` when its `severity` is `MINOR`, at least `CURTAILED`
        when its severity is `MAJOR`, and `SUSPENDED` when its severity is
        `CRITICAL`"

        Design: Corner/calculations/grind_cap_applies_both_multipliers_under_curtailment
        """
        scenario = _curtailed_and_short_plant(api)
        assert scenario["plant"]["daily_grind_cap_bushels"] == 90000, (
            scenario["plant"]["daily_grind_cap_bushels"]
        )

        plant = get_success_data(api.get_plant(scenario["plant"]["id"], PLANT_MANAGER))
        assert_plant_posture(plant, "CURTAILED", "SHORT", 54000)

        condition = get_success_data(
            api.get_permit_condition(scenario["condition"]["id"], COMPLIANCE_OFFICER)
        )
        assert condition["status"] == "EXCEEDANCE", condition["status"]
        assert_3dp(condition["rolling_average_value"], 13.000, "rolling_average_value")

    def test_a_sixty_thousand_bushel_charge_hits_the_cap_gate_before_the_empty_bin(self, api):
        """The cap gate fires at priority 40, ahead of the plant's empty corn bin.

        PRD 3.4: "The charge may not exceed the plant's current
        `daily_grind_cap_bushels` — the cap already scaled by both postures —
        otherwise `ERR_GRIND_CAP_EXCEEDED`. The destination tank's `product_type`
        must be `ETHANOL_200_PROOF`, otherwise `ERR_TANK_PRODUCT_TYPE_MISMATCH`.
        And last, the plant's `corn_inventory_bushels` must be at least the
        bushels being charged, otherwise `ERR_INSUFFICIENT_CORN_INVENTORY`."

        Design: Corner/calculations/grind_cap_applies_both_multipliers_under_curtailment
        """
        scenario = _curtailed_and_short_plant(api)

        validate_error(
            api.create_batch(
                {
                    "batch_code": "FB-1",
                    "corn_bushels_charged": 60000.00,
                    "charge_test_weight_lb_per_bu": 54.0,
                    "destination_tank_id": scenario["tank"]["id"],
                },
                PROCESS_OPERATOR,
            ),
            ApiErrorId.GRIND_CAP_EXCEEDED,
            422,
        )

        rows, meta = validate_paginated(
            api.list_tank_batches(scenario["tank"]["id"], PROCESS_OPERATOR)
        )
        assert rows == [], f"no batch may have been charged, got {rows!r}"
        assert meta["total_count"] == 0, meta["total_count"]


def _index_quote_then_a_higher_mark(api):
    """
    SL-1 quotes 750.000 tons of dry distillers grains at 92 percent of a 330.00
    soybean meal mark, sending a bogus 999.00 quoted_price, and the mark then
    moves up to 362.50 before the buyer answers.
    """
    plant = fx.commission_plant(api)
    fx.advance_clock(api, "2026-09-03T00:00:00Z")
    fx.post_marks(api, plant["id"], RISK_MANAGER, mark_soybean_meal_usd_per_ton=330.00)
    sale = fx.quote_index_sale(
        api,
        sale_code="SL-1",
        buyer_name="Midwest Feeders",
        product="DDGS_DRY",
        quantity=750.000,
        quoted_price=999.00,
        index_pct=0.9200,
        freight_rate_per_unit=3.2500,
        quote_expires_at="2026-09-30T00:00:00Z",
    )
    fx.post_marks(api, plant["id"], RISK_MANAGER, mark_soybean_meal_usd_per_ton=362.50)
    return {"plant": plant, "sale": sale}


class TestIndexQuoteIsStruckFromTheMark:
    """303.60 at quote time, and a ceiling of 326.37 that a 333.50 restrike cannot pass."""

    def test_the_client_supplied_price_is_discarded_in_favour_of_the_reference_mark(self, api):
        """The stored quote is 330.00 times 0.9200, and the mark used is stamped.

        PRD 3.7: "An `INDEX` sale requires `index_pct` — a multiplier between 0.10
        and 2.00 inclusive carried to four decimals — and **ignores any
        `quoted_price` the caller supplies**, because for an index sale the quoted
        price is struck by the system at quote time from the plant's published
        marks."

        PRD 3.7: "Which mark an index sale reads depends on the product: both
        grades of distillers grains price off `mark_soybean_meal_usd_per_ton`,
        while corn oil prices off `mark_sbo_cents_per_lb`. At quote time the
        system multiplies that reference mark by `index_pct`, rounds half up to
        two decimals and stores the result as `quoted_price`, while also stamping
        the mark it used into `quote_reference_mark` so the later restrike can be
        audited."

        Design: Corner/calculations/index_quote_is_struck_from_the_reference_mark_not_the_client_price
        """
        scenario = _index_quote_then_a_higher_mark(api)
        sale = scenario["sale"]

        assert_2dp(sale["quoted_price"], 303.60, "quoted_price")
        assert_2dp(sale["quote_reference_mark"], 330.00, "quote_reference_mark")
        assert sale["status"] == "QUOTED", sale["status"]

        stored = get_success_data(api.get_sale(sale["id"], GRAIN_BUYER))
        assert_2dp(stored["quoted_price"], 303.60, "quoted_price")
        assert_2dp(stored["quote_reference_mark"], 330.00, "quote_reference_mark")

    def test_the_restrike_is_clamped_by_a_collar_anchored_on_the_original_quote(self, api):
        """333.50 against a 326.37 ceiling settles at the ceiling, quote untouched.

        PRD 3.7: "For an `INDEX` sale the system restrikes the price against the
        mark **as it stands at acceptance**: multiply the current reference mark by
        `index_pct` and round half up to two decimals. That restruck figure is
        then clamped into a symmetric band of seven and a half percent computed
        **from the original `quoted_price`, never from the restruck price** —
        `collar_floor` is `quoted_price` multiplied by 0.925 rounded half up to
        two decimals, and `collar_ceiling` is `quoted_price` multiplied by 1.075
        rounded half up to two decimals. If the restruck price falls below the
        floor the settlement price becomes the floor; if it rises above the ceiling
        the settlement price becomes the ceiling; otherwise the settlement price is
        the restruck price itself."

        Design: Corner/calculations/index_quote_is_struck_from_the_reference_mark_not_the_client_price
        """
        scenario = _index_quote_then_a_higher_mark(api)

        accepted = validate_success(
            api.respond_to_sale(scenario["sale"]["id"], {"decision": "ACCEPT"}, GRAIN_BUYER),
            200,
        )

        assert accepted["status"] == "ACCEPTED", accepted["status"]
        assert_2dp(accepted["collar_floor"], 280.83, "collar_floor")
        assert_2dp(accepted["collar_ceiling"], 326.37, "collar_ceiling")
        assert_2dp(accepted["settlement_price"], 326.37, "settlement_price")
        assert_2dp(accepted["quoted_price"], 303.60, "quoted_price")

        stored = get_success_data(api.get_sale(scenario["sale"]["id"], GRAIN_BUYER))
        assert_2dp(stored["quoted_price"], 303.60, "quoted_price")
        assert_2dp(stored["settlement_price"], 326.37, "settlement_price")
