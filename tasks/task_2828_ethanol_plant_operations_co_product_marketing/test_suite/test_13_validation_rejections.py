"""
Field, uniqueness, temporal and cross-entity validations and the rows they spare.

Each rejection here is checked twice over: the error identifier and status the
PRD names, and the state of the records the refused call must have left exactly
as it found them.
"""

from test_helpers import fixtures as fx
from test_helpers import get_success_data, validate_error, validate_paginated, validate_success
from test_helpers.api_errors import ApiErrorId
from test_helpers.assertions import (
    assert_2dp,
    assert_3dp,
    assert_6dp,
    assert_instant_equals,
    assert_null,
    assert_plant_posture,
)
from test_helpers.test_users import (
    GRAIN_ACCOUNTANT,
    GRAIN_BUYER,
    LOGISTICS_COORDINATOR,
    PLANT_MANAGER,
    PROCESS_OPERATOR,
    RISK_MANAGER,
    SCALE_OPERATOR,
)

_BASIS_GRADE = {
    "moisture_pct": 15.00,
    "test_weight_lb_per_bu": 54.0,
    "foreign_material_pct": 3.00,
    "damaged_kernels_pct": 5.00,
    "aflatoxin_ppb": 3,
}


class TestBusinessCodesAreGlobalNaturalKeys:
    """A reused tank code is refused whatever else the payload says."""

    def test_a_second_tank_reusing_the_code_is_refused_and_the_original_stands(self, api):
        """T-101 cannot be re-keyed as a smaller denaturant tank.

        PRD 3.5: "A `ProcessOperator` commissions a tank with a globally unique
        `tank_code` such as T-101, a `product_type` that is one of
        `ETHANOL_200_PROOF`, `DENATURANT` or `DENATURED_E100`, and a positive
        working `capacity_gallons` carried to two decimals."

        PRD 2.9: "**Uniqueness** — `ERR_PLANT_ALREADY_EXISTS` for a second plant,
        then `ERR_DUPLICATE_CODE` for a reused business code."

        Design: Corner/validations/duplicate_tank_code_rejected
        """
        fx.commission_plant(api, base_grind_cap_bushels=120000, coverage_floor_bushels=5000)
        original = fx.commission_tank(api, "T-101", "ETHANOL_200_PROOF", 1000000.00)

        validate_error(
            api.create_tank(
                {
                    "tank_code": "T-101",
                    "product_type": "DENATURANT",
                    "capacity_gallons": 250000.00,
                },
                PROCESS_OPERATOR,
            ),
            ApiErrorId.DUPLICATE_CODE,
            409,
        )

        stored = get_success_data(api.get_tank(original["id"], PROCESS_OPERATOR))
        assert stored["product_type"] == "ETHANOL_200_PROOF", stored["product_type"]
        assert_2dp(stored["capacity_gallons"], 1000000.00, "capacity_gallons")


class TestTheFacilityIsASingleton:
    """One plant, and the second registration cannot displace it."""

    def test_a_second_registration_is_refused_and_the_first_plant_is_untouched(self, api):
        """A differently named plant of another size still collides.

        PRD 3.1: "Exactly one plant may exist; a second registration attempt is
        refused with `ERR_PLANT_ALREADY_EXISTS`, and any plant-level read or write
        attempted before the plant exists is refused with `ERR_PLANT_NOT_FOUND`."

        Design: Corner/validations/second_plant_creation_rejected
        """
        plant = fx.commission_plant(
            api, base_grind_cap_bushels=120000, coverage_floor_bushels=5000
        )

        validate_error(
            api.create_plant(
                {"name": "Second Plant", "nameplate_capacity_gallons": 60000000},
                PLANT_MANAGER,
            ),
            ApiErrorId.PLANT_ALREADY_EXISTS,
            409,
        )

        stored = get_success_data(api.get_plant(plant["id"], PLANT_MANAGER))
        assert stored["name"] == "Prairie Gold Ethanol", stored["name"]
        assert stored["version"] == 1, stored["version"]


class TestRollWaitsForLoadsInFlight:
    """A single ungraded ticket freezes the remainder and blocks the roll."""

    def test_a_pending_grade_load_blocks_the_roll_and_no_successor_appears(self, api):
        """The parent is OPEN with room to roll, but its child is still in flight.

        PRD 3.2: "And no delivery against it may still be in flight: if any of its
        deliveries has a `grading_status` of `PENDING_GRADE` or `GRADED`, the roll
        is refused with `ERR_CONTRACT_HAS_OPEN_DELIVERIES`, because those loads
        must be settled or rejected before the remainder is known with certainty."

        PRD 3.2: "Contracts are discoverable through a filtered list that accepts
        `status`, `delivery_month`, `pricing_status` and `rolled_from_contract_id`,
        the last of which is what makes the self-referential roll chain navigable
        in both directions."

        Design: Corner/validations/roll_with_a_pending_grade_load_rejected
        """
        fx.commission_plant(api, base_grind_cap_bushels=120000, coverage_floor_bushels=5000)
        contract = fx.priced_contract(
            api, 458.0, supplier_name="Cedar Ridge Elevator", bushels_contracted=200000.00
        )
        delivery = fx.book_delivery(api, contract["id"], ticket_number="TK-0001")

        validate_error(
            api.roll_contract(
                contract["id"],
                {"delivery_month": "2026-11", "roll_basis_adjustment_cents": 4.0},
                GRAIN_BUYER,
            ),
            ApiErrorId.CONTRACT_HAS_OPEN_DELIVERIES,
            422,
        )

        stored = get_success_data(api.get_contract(contract["id"], GRAIN_BUYER))
        assert stored["status"] == "OPEN", stored["status"]

        successors, meta = validate_paginated(
            api.list_contracts(GRAIN_BUYER, {"rolled_from_contract_id": contract["id"]})
        )
        assert successors == [], f"no successor may exist, got {successors!r}"
        assert meta["total_count"] == 0, meta["total_count"]

        load = get_success_data(api.get_delivery(delivery["id"], SCALE_OPERATOR))
        assert load["grading_status"] == "PENDING_GRADE", load["grading_status"]


class TestTheClockIsStrictlyForwardOnly:
    """Re-posting the instant in force is itself a regression."""

    def test_neither_the_equal_nor_the_earlier_instant_moves_the_clock(self, api):
        """Both posts are refused and a later creation still stamps the old instant.

        PRD 2.4: "An operator in any of the eight roles may advance it by supplying
        a `current_utc` instant; the new instant must be strictly later than the
        instant currently in force, and re-posting the instant already in force is
        itself a regression and is rejected with `ERR_CLOCK_REGRESSION`."

        PRD 2.4: "Every rolling window, every quote expiry, every occupancy
        comparison and every system-recorded instant in this specification reads
        that logical clock."

        Design: Corner/validations/clock_reposted_at_the_same_instant_rejected
        """
        fx.commission_plant(api, base_grind_cap_bushels=120000, coverage_floor_bushels=5000)
        fx.advance_clock(api, "2026-09-05T00:00:00Z")

        validate_error(
            api.set_clock("2026-09-05T00:00:00Z", PLANT_MANAGER),
            ApiErrorId.CLOCK_REGRESSION,
            422,
        )
        validate_error(
            api.set_clock("2026-09-04T23:59:59Z", PLANT_MANAGER),
            ApiErrorId.CLOCK_REGRESSION,
            422,
        )

        tank = fx.commission_tank(api, "T-101", "ETHANOL_200_PROOF", 1000000.00)
        assert_instant_equals(tank["created_at"], "2026-09-05T00:00:00Z", "created_at")


class TestQuoteExpiryIsInclusive:
    """A response landing exactly on the expiry instant is still in time."""

    def test_declining_on_the_expiry_instant_is_accepted_and_prices_nothing(self, api):
        """The clock sits on 2026-09-10T00:00:00Z and the decline still lands.

        PRD 3.7: "The logical clock must be at or before `quote_expires_at` — the
        bound is **inclusive**, so a response landing on the expiry instant to the
        second is still in time, while one instant later is refused with
        `ERR_QUOTE_EXPIRED`. A `DECLINE` moves the sale to `DECLINED`, records
        `responded_at` and leaves every money field null forever; nothing is ever
        computed for a declined quote."

        Design: Corner/validations/quote_response_exactly_at_the_expiry_instant_is_accepted
        """
        fx.commission_plant(api, base_grind_cap_bushels=120000, coverage_floor_bushels=5000)
        fx.advance_clock(api, "2026-09-03T00:00:00Z")
        sale = fx.quote_flat_sale(
            api,
            sale_code="SL-1",
            buyer_name="Midwest Feeders",
            product="DDGS_DRY",
            quantity=5.000,
            quoted_price=210.00,
            quote_expires_at="2026-09-10T00:00:00Z",
        )
        fx.advance_clock(api, "2026-09-10T00:00:00Z")

        responded = validate_success(
            api.respond_to_sale(sale["id"], {"decision": "DECLINE"}, GRAIN_BUYER), 200
        )
        assert responded["status"] == "DECLINED", responded["status"]
        assert_instant_equals(
            responded["responded_at"], "2026-09-10T00:00:00Z", "responded_at"
        )

        stored = get_success_data(api.get_sale(sale["id"], GRAIN_BUYER))
        assert_null(stored["settlement_price"], "settlement_price")


def _blend_below_the_band(api):
    """
    A full tank farm with BL-1 scheduled for 2565.00 neat and only 30.00
    denaturant gallons, a fraction of 0.011561 that the execution gate refuses.
    """
    plant = fx.commission_plant(
        api, base_grind_cap_bushels=120000, coverage_floor_bushels=5000
    )
    farm = fx.standard_tank_farm(
        api, neat_opening=500000.00, denaturant_opening=500000.00, e100_opening=0.00
    )
    blend = fx.schedule_blend(
        api,
        farm["neat"]["id"],
        farm["denaturant"]["id"],
        farm["e100"]["id"],
        farm["e100"]["version"],
        blend_code="BL-1",
        neat_gallons=2565.00,
        denaturant_gallons=30.00,
        window_start="2026-09-04T06:00:00Z",
        window_end="2026-09-04T10:00:00Z",
    )
    return {"plant": plant, "farm": farm, "blend": blend}


class TestDenaturantBandIsCheckedAtExecution:
    """Scheduling a thin blend is legal; moving the liquid is not."""

    def test_an_off_spec_ratio_schedules_cleanly_then_fails_and_moves_no_liquid(self, api):
        """30.00 over 2595.00 is 0.011561, below the 0.019800 floor.

        PRD 3.5: "`output_gallons` is `neat_gallons` plus `denaturant_gallons`,
        rounded half up to two decimals, and `denaturant_pct` is
        `denaturant_gallons` divided by `output_gallons`, rounded half up to six
        decimals. The finished-product band runs from 0.019800 to 0.029800
        **inclusive on both bounds**, so a blend sitting exactly on either edge is
        on spec; anything outside is refused with `ERR_DENATURANT_SPEC_VIOLATION`
        and no liquid moves."

        Design: Corner/validations/blend_below_the_denaturant_band_rejected_at_execution
        """
        scenario = _blend_below_the_band(api)
        assert scenario["blend"]["status"] == "SCHEDULED", scenario["blend"]["status"]

        validate_error(
            api.execute_blend(scenario["blend"]["id"], PROCESS_OPERATOR),
            ApiErrorId.DENATURANT_SPEC_VIOLATION,
            422,
        )

        blend = get_success_data(api.get_blend(scenario["blend"]["id"], PROCESS_OPERATOR))
        assert blend["status"] == "SCHEDULED", blend["status"]
        assert_null(blend["executed_at"], "executed_at")

        neat = get_success_data(api.get_tank(scenario["farm"]["neat"]["id"], PROCESS_OPERATOR))
        assert_2dp(neat["current_gallons"], 500000.00, "current_gallons")
        e100 = get_success_data(api.get_tank(scenario["farm"]["e100"]["id"], PROCESS_OPERATOR))
        assert_2dp(e100["current_gallons"], 0.00, "current_gallons")

    def test_the_same_volumes_with_sixty_denaturant_gallons_execute(self, api):
        """Only the ratio was at fault: 60.00 over 2625.00 is 0.022857 and on spec.

        PRD 3.5: "On success the blend moves `SCHEDULED → EXECUTED`, `executed_at`
        is recorded, the two sources are debited and the destination credited, and
        all three tanks have their `version` incremented alongside the blend's
        own."

        Design: Corner/validations/blend_below_the_denaturant_band_rejected_at_execution
        """
        scenario = _blend_below_the_band(api)
        destination = get_success_data(
            api.get_tank(scenario["farm"]["e100"]["id"], PROCESS_OPERATOR)
        )

        executed = fx.executed_blend(
            api,
            scenario["farm"]["neat"]["id"],
            scenario["farm"]["denaturant"]["id"],
            destination["id"],
            destination["version"],
            blend_code="BL-2",
            neat_gallons=2565.00,
            denaturant_gallons=60.00,
            window_start="2026-09-04T12:01:00Z",
            window_end="2026-09-04T16:00:00Z",
        )

        assert executed["status"] == "EXECUTED", executed["status"]
        assert_2dp(executed["output_gallons"], 2625.00, "output_gallons")
        assert_6dp(executed["denaturant_pct"], 0.022857, "denaturant_pct")

        neat = get_success_data(api.get_tank(scenario["farm"]["neat"]["id"], PROCESS_OPERATOR))
        assert_2dp(neat["current_gallons"], 497435.00, "current_gallons")
        e100 = get_success_data(api.get_tank(destination["id"], PROCESS_OPERATOR))
        assert_2dp(e100["current_gallons"], 2625.00, "current_gallons")


class TestEachTankReferenceIsTypeCheckedByItsRole:
    """A neat tank cannot stand in for the finished-product destination."""

    def test_a_neat_destination_is_refused_and_its_version_is_not_bumped(self, api):
        """T-102 exists, is in service and has room, but it is the wrong product.

        PRD 3.5: "Each referenced tank's `product_type` must match its role —
        `ETHANOL_200_PROOF` for the neat source, `DENATURANT` for the denaturant
        source, `DENATURED_E100` for the destination — and any mismatch is refused
        with `ERR_TANK_PRODUCT_TYPE_MISMATCH`."

        PRD 3.5: "A successful schedule lands the blend at `SCHEDULED` and
        increments the destination tank's `version`."

        Design: Corner/validations/blend_into_a_tank_of_the_wrong_product_type_rejected
        """
        fx.commission_plant(api, base_grind_cap_bushels=120000, coverage_floor_bushels=5000)
        neat = fx.commission_tank(
            api, "T-101", "ETHANOL_200_PROOF", 1000000.00, opening_gallons=500000.00
        )
        second_neat = fx.commission_tank(
            api, "T-102", "ETHANOL_200_PROOF", 1000000.00, opening_gallons=0.00
        )
        denaturant = fx.commission_tank(
            api, "T-201", "DENATURANT", 1000000.00, opening_gallons=500000.00
        )

        validate_error(
            api.create_blend(
                {
                    "blend_code": "BL-1",
                    "neat_source_tank_id": neat["id"],
                    "denaturant_source_tank_id": denaturant["id"],
                    "destination_tank_id": second_neat["id"],
                    "expected_destination_tank_version": second_neat["version"],
                    "neat_gallons": 2565.00,
                    "denaturant_gallons": 60.00,
                    "window_start": "2026-09-04T06:00:00Z",
                    "window_end": "2026-09-04T10:00:00Z",
                },
                PROCESS_OPERATOR,
            ),
            ApiErrorId.TANK_PRODUCT_TYPE_MISMATCH,
            422,
        )

        rows, meta = validate_paginated(
            api.list_tank_blends(second_neat["id"], PROCESS_OPERATOR)
        )
        assert rows == [], f"no blend may have been scheduled, got {rows!r}"
        assert meta["total_count"] == 0, meta["total_count"]

        stored = get_success_data(api.get_tank(second_neat["id"], PROCESS_OPERATOR))
        assert stored["version"] == 1, stored["version"]


def _plant_with_one_settled_load(api):
    """940.00 settled bushels against a 200000.00 bushel contract, and T-101 idle."""
    plant = fx.commission_plant(
        api, base_grind_cap_bushels=120000, coverage_floor_bushels=5000
    )
    tank = fx.commission_tank(api, "T-101", "ETHANOL_200_PROOF", 1000000.00)
    contract = fx.priced_contract(
        api, 458.0, supplier_name="Cedar Ridge Elevator", bushels_contracted=200000.00
    )
    delivery = fx.settled_load(
        api,
        contract["id"],
        delivery_overrides={"ticket_number": "TK-0001"},
        grade_overrides=dict(_BASIS_GRADE),
    )
    return {"plant": plant, "tank": tank, "contract": contract, "delivery": delivery}


class TestChargeIsGatedOnSettledInventoryNotTheContractBook:
    """A 200000 bushel contract does not feed a fermenter; settled corn does."""

    def test_a_thousand_bushel_charge_against_nine_hundred_and_forty_is_refused(self, api):
        """The bin holds 940.00 bushels and the cap of 120000 is nowhere near binding.

        PRD 3.4: "And last, the plant's `corn_inventory_bushels` must be at least
        the bushels being charged, otherwise `ERR_INSUFFICIENT_CORN_INVENTORY`."

        PRD 2.8: "With the default base cap of 120,000 bushels a day, an open and
        adequately covered plant may grind 120,000"

        Design: Corner/validations/charge_over_the_corn_inventory_rejected
        """
        scenario = _plant_with_one_settled_load(api)
        assert_2dp(scenario["delivery"]["net_dry_bushels"], 940.00, "net_dry_bushels")

        plant = get_success_data(api.get_plant(scenario["plant"]["id"], PLANT_MANAGER))
        assert_2dp(plant["corn_inventory_bushels"], 940.00, "corn_inventory_bushels")
        assert_plant_posture(plant, "OPEN", "ADEQUATE", 120000)

        validate_error(
            api.create_batch(
                {
                    "batch_code": "FB-1",
                    "corn_bushels_charged": 1000.00,
                    "charge_test_weight_lb_per_bu": 54.0,
                    "destination_tank_id": scenario["tank"]["id"],
                },
                PROCESS_OPERATOR,
            ),
            ApiErrorId.INSUFFICIENT_CORN_INVENTORY,
            422,
        )

    def test_charging_exactly_the_bushels_on_hand_is_accepted_and_empties_the_bin(self, api):
        """940.00 is the whole bin, and the inclusive gate lets it through.

        PRD 3.4: "The charged bushels are subtracted from `corn_inventory_bushels`
        immediately, and they are **never returned**: charged corn is consumed the
        moment it is ground, and no later outcome, dump included, restores it."

        Design: Corner/validations/charge_over_the_corn_inventory_rejected
        """
        scenario = _plant_with_one_settled_load(api)

        batch = fx.charge_batch(
            api,
            scenario["tank"]["id"],
            batch_code="FB-1",
            corn_bushels_charged=940.00,
            charge_test_weight_lb_per_bu=54.0,
        )
        assert batch["status"] == "CHARGED", batch["status"]
        assert_2dp(batch["corn_bushels_charged"], 940.00, "corn_bushels_charged")

        plant = get_success_data(api.get_plant(scenario["plant"]["id"], PLANT_MANAGER))
        assert_2dp(plant["corn_inventory_bushels"], 0.00, "corn_inventory_bushels")


class TestHedgeCloseNeverClamps:
    """Twelve lots against ten open is a refusal, not a ten-lot fill."""

    def test_an_oversized_close_is_refused_and_leaves_the_position_whole(self, api):
        """Nothing is realized, nothing is closed and the position stays OPEN.

        PRD 3.9: "The position must be `OPEN` or `PARTIALLY_CLOSED`, otherwise
        `ERR_INVALID_POSITION_STATE`, and `contracts_to_close` must be at least 1
        and at most `contracts_open`, otherwise
        `ERR_CLOSE_EXCEEDS_OPEN_CONTRACTS`."

        PRD 3.9: "opens the position at `status` `OPEN` with `contracts_closed` at
        0, `contracts_open` equal to `contracts`, both `realized_pnl_cents` and
        `unrealized_pnl_cents` at 0, and `opened_at` recorded."

        Design: Corner/validations/hedge_close_over_the_open_contracts_rejected
        """
        fx.commission_plant(api, base_grind_cap_bushels=120000, coverage_floor_bushels=5000)
        position = fx.open_hedge(
            api,
            position_code="HP-1",
            commodity="ETHANOL",
            direction="SHORT",
            contracts=10,
            entry_price=182.00,
            contract_month="2026-10",
        )
        assert position["unrealized_pnl_cents"] == 0, position["unrealized_pnl_cents"]

        validate_error(
            api.close_hedge_position(
                position["id"], {"contracts_to_close": 12, "exit_price": 176.50}, RISK_MANAGER
            ),
            ApiErrorId.CLOSE_EXCEEDS_OPEN_CONTRACTS,
            422,
        )

        stored = get_success_data(api.get_hedge_position(position["id"], RISK_MANAGER))
        assert stored["status"] == "OPEN", stored["status"]
        assert stored["contracts_open"] == 10, stored["contracts_open"]
        assert stored["contracts_closed"] == 0, stored["contracts_closed"]
        assert stored["realized_pnl_cents"] == 0, stored["realized_pnl_cents"]


class TestInactiveTrackRefusesEvenOneRailcar:
    """The flag gates scheduling on its own, with 110 spots standing empty."""

    def test_a_single_railcar_on_a_deactivated_track_is_refused(self, api):
        """is_active false overrides the true default and blocks the schedule.

        PRD 3.6: "Two optional inputs follow: `loading_rate_cars_per_hour`, a
        positive one-decimal figure defaulting to 4.0 that is purely informational
        and gates nothing, and `is_active`, defaulting to true, which when false
        makes the track refuse new shipments."

        PRD 3.6: "After capacity, the track's `is_active` flag is checked, and an
        inactive track refuses the schedule with `ERR_TRACK_INACTIVE`."

        Design: Corner/validations/shipment_on_an_inactive_track_rejected
        """
        fx.commission_plant(api, base_grind_cap_bushels=120000, coverage_floor_bushels=5000)
        tank = fx.commission_tank(
            api, "T-301", "DENATURED_E100", 1000000.00, opening_gallons=400000.00
        )
        track = fx.commission_track(api, track_code="TRK-B", spot_capacity=110, is_active=False)
        assert track["is_active"] is False, track["is_active"]

        validate_error(
            api.create_shipment(
                {
                    "shipment_code": "SH-1",
                    "track_id": track["id"],
                    "expected_track_version": track["version"],
                    "source_tank_id": tank["id"],
                    "destination_terminal": "Chicago Terminal",
                    "railcar_count": 1,
                    "gallons_per_railcar": 2659.00,
                    "window_start": "2026-09-04T06:00:00Z",
                    "window_end": "2026-09-04T18:00:00Z",
                    "price_cents_per_gallon": 181.50,
                },
                LOGISTICS_COORDINATOR,
            ),
            ApiErrorId.TRACK_INACTIVE,
            422,
        )

        stored = get_success_data(api.get_track(track["id"], LOGISTICS_COORDINATOR))
        assert stored["committed_railcars"] == 0, stored["committed_railcars"]
        assert stored["version"] == 1, stored["version"]

        rows, meta = validate_paginated(api.list_shipments(LOGISTICS_COORDINATOR))
        assert rows == [], f"no shipment may exist, got {rows!r}"
        assert meta["total_count"] == 0, meta["total_count"]


def _accepted_sale_with_an_empty_shed(api):
    """SL-1 accepted for 5.000 tons of dry distillers grains the plant does not have."""
    plant = fx.commission_plant(
        api, base_grind_cap_bushels=120000, coverage_floor_bushels=5000
    )
    fx.advance_clock(api, "2026-09-03T00:00:00Z")
    sale = fx.quote_flat_sale(
        api,
        sale_code="SL-1",
        buyer_name="Midwest Feeders",
        product="DDGS_DRY",
        quantity=5.000,
        quoted_price=210.00,
        quote_expires_at="2026-09-30T00:00:00Z",
    )
    accepted = fx.accept_sale(api, sale["id"])
    return {"plant": plant, "sale": sale, "accepted": accepted}


class TestCoProductShipmentNeedsRealInventory:
    """A flat quote prices without marks, but shipping needs tons on the floor."""

    def test_acceptance_builds_the_invoice_from_the_flat_quote_alone(self, api):
        """1050.00 subtotal, no rebate tier and a 105000 cent invoice.

        PRD 3.7: "For a `FLAT` sale the `settlement_price` is simply the stored
        `quoted_price` and both `collar_floor` and `collar_ceiling` remain null."

        PRD 3.7: "`subtotal_usd` is the `quantity` multiplied by the
        `settlement_price`, divided by that unit divisor, rounded half up to two
        decimals."

        PRD 3.7: "The rate is 0.0150 when `subtotal_usd` is at least 50000.00;
        failing that, 0.0075 when it is at least 20000.00; otherwise 0.0000."

        Design: Corner/validations/co_product_shipment_over_the_inventory_rejected
        """
        scenario = _accepted_sale_with_an_empty_shed(api)
        accepted = scenario["accepted"]

        assert accepted["status"] == "ACCEPTED", accepted["status"]
        assert_2dp(accepted["settlement_price"], 210.00, "settlement_price")
        assert_2dp(accepted["subtotal_usd"], 1050.00, "subtotal_usd")
        assert_2dp(accepted["volume_rebate_usd"], 0.00, "volume_rebate_usd")
        assert accepted["invoice_amount_cents"] == 105000, accepted["invoice_amount_cents"]

    def test_shipping_against_an_empty_shed_is_refused_and_the_sale_stays_accepted(self, api):
        """Zero tons on hand refuses a 5.000 ton shipment and moves no status.

        PRD 3.7: "For either grade of distillers grains the plant's
        `ddgs_inventory_tons` must be at least the `quantity`; for corn oil the
        plant's `corn_oil_inventory_lbs` must be at least the `quantity`. A short
        cupboard is refused with `ERR_INSUFFICIENT_COPRODUCT_INVENTORY`."

        Design: Corner/validations/co_product_shipment_over_the_inventory_rejected
        """
        scenario = _accepted_sale_with_an_empty_shed(api)

        validate_error(
            api.ship_sale(scenario["sale"]["id"], LOGISTICS_COORDINATOR),
            ApiErrorId.INSUFFICIENT_COPRODUCT_INVENTORY,
            422,
        )

        stored = get_success_data(api.get_sale(scenario["sale"]["id"], GRAIN_BUYER))
        assert stored["status"] == "ACCEPTED", stored["status"]
        assert_null(stored["shipped_at"], "shipped_at")

        plant = get_success_data(api.get_plant(scenario["plant"]["id"], PLANT_MANAGER))
        assert_3dp(plant["ddgs_inventory_tons"], 0.000, "ddgs_inventory_tons")


def _contract_filled_by_its_first_load(api):
    """C-1 is written for exactly 940.00 bushels, which one default ticket fills."""
    plant = fx.commission_plant(
        api, base_grind_cap_bushels=120000, coverage_floor_bushels=5000
    )
    contract = fx.priced_contract(
        api, 458.0, supplier_name="Cedar Ridge Elevator", bushels_contracted=940.00
    )
    delivery = fx.settled_load(
        api,
        contract["id"],
        delivery_overrides={"ticket_number": "TK-0001"},
        grade_overrides=dict(_BASIS_GRADE),
    )
    return {"plant": plant, "contract": contract, "delivery": delivery}


class TestFilledContractRefusesFurtherLoads:
    """The specific fully-delivered refusal, not the generic invalid state."""

    def test_a_second_ticket_is_refused_as_fully_delivered(self, api):
        """940.00 delivered against 940.00 contracted closes the contract to loads.

        PRD 3.3: "a contract whose fill `status` is `ROLLED` accepts no further
        loads and is refused with `ERR_INVALID_CONTRACT_STATE`, because its
        remainder now lives on its successor; and a contract whose settled bushels
        already meet or exceed `bushels_contracted` is refused with the more
        specific `ERR_CONTRACT_FULLY_DELIVERED`."

        Design: Corner/validations/delivery_booked_against_a_filled_contract_rejected
        """
        scenario = _contract_filled_by_its_first_load(api)
        assert scenario["delivery"]["grading_status"] == "SETTLED", (
            scenario["delivery"]["grading_status"]
        )

        contract = get_success_data(api.get_contract(scenario["contract"]["id"], GRAIN_BUYER))
        assert contract["status"] == "FILLED", contract["status"]
        assert_2dp(contract["bushels_delivered"], 940.00, "bushels_delivered")

        validate_error(
            api.create_delivery(
                scenario["contract"]["id"],
                {
                    "ticket_number": "TK-0002",
                    "gross_weight_lbs": 78640,
                    "tare_weight_lbs": 26000.00,
                },
                SCALE_OPERATOR,
            ),
            ApiErrorId.CONTRACT_FULLY_DELIVERED,
            422,
        )

        rows, meta = validate_paginated(
            api.list_contract_deliveries(scenario["contract"]["id"], SCALE_OPERATOR)
        )
        assert len(rows) == 1, f"only the first ticket may exist, got {rows!r}"
        assert meta["total_count"] == 1, meta["total_count"]

    def test_the_filled_contract_drops_out_of_coverage_entirely(self, api):
        """Filling the book leaves coverage at zero and procurement SHORT.

        PRD 3.2: "Contracts at `FILLED` or `ROLLED` are excluded from the input set
        **entirely** — not counted as zero, but dropped — which is why a roll can
        leave a non-zero remainder on the source row that no longer counts
        anywhere, the successor carrying it instead."

        PRD 2.8: "`procurement_posture` is `ADEQUATE` when
        `open_contract_coverage_bushels` is greater than or equal to
        `coverage_floor_bushels`, and `SHORT` otherwise"

        Design: Corner/validations/delivery_booked_against_a_filled_contract_rejected
        """
        scenario = _contract_filled_by_its_first_load(api)

        plant = get_success_data(api.get_plant(scenario["plant"]["id"], PLANT_MANAGER))
        assert_2dp(plant["open_contract_coverage_bushels"], 0.00, "open_contract_coverage_bushels")
        assert_plant_posture(plant, "OPEN", "SHORT")
