"""
Named action endpoints and the reads taken straight after them.

Each action here publishes side effects on records other than the one named in
the path, and every one of those records is read back in the same test to prove
the write landed everywhere at once.
"""

from test_helpers import fixtures as fx
from test_helpers import get_success_data, validate_paginated, validate_success
from test_helpers.assertions import (
    assert_2dp,
    assert_3dp,
    assert_6dp,
    assert_instant_equals,
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
    SCALE_OPERATOR,
)


def _scheduled_train(api):
    """SH-1: 100 railcars of 2659.00 gallons off a T-301 holding 400000.00."""
    plant = fx.commission_plant(
        api, base_grind_cap_bushels=120000, coverage_floor_bushels=5000
    )
    fx.advance_clock(api, "2026-09-04T06:00:00Z")
    tank = fx.commission_tank(
        api, "T-301", "DENATURED_E100", 1000000.00, opening_gallons=400000.00
    )
    track = fx.commission_track(api, track_code="TRK-A", spot_capacity=110)
    shipment = fx.schedule_shipment(
        api,
        track["id"],
        tank["id"],
        track["version"],
        shipment_code="SH-1",
        railcar_count=100,
        gallons_per_railcar=2659.00,
        window_start="2026-09-04T06:00:00Z",
        window_end="2026-09-04T18:00:00Z",
        price_cents_per_gallon=181.50,
    )
    return {"plant": plant, "tank": tank, "track": track, "shipment": shipment}


class TestTheThreeShipmentActionsEachPublishTheirOwnEffects:
    """Load, document, invoice: two axes advancing under three separate calls."""

    def test_loading_draws_the_planned_gallons_without_touching_the_billing_axis(self, api):
        """265900.00 leaves the tank while the paperwork stays at PENDING_BOL.

        PRD 3.6: "A scheduled shipment lands with `planned_gallons` computed as
        `railcar_count` multiplied by `gallons_per_railcar` (two decimals), its
        `loading_status` at `SCHEDULED` and its `billing_status` at `PENDING_BOL`."

        PRD 3.6: "On success `loaded_gallons` is set equal to `planned_gallons`,
        `loaded_at` records the logical clock, the source tank is debited by the
        loaded gallons and that tank's `version` increments."

        Design: Corner/endpoints/load_then_bol_then_invoice_prices_the_gallons_actually_drawn
        """
        scenario = _scheduled_train(api)
        assert_2dp(scenario["shipment"]["planned_gallons"], 265900.00, "planned_gallons")
        assert_null(scenario["shipment"]["invoice_amount_cents"], "invoice_amount_cents")

        loaded = validate_success(
            api.load_shipment(scenario["shipment"]["id"], LOGISTICS_COORDINATOR), 200
        )
        assert_2dp(loaded["loaded_gallons"], 265900.00, "loaded_gallons")
        assert loaded["loading_status"] == "LOADED", loaded["loading_status"]
        assert loaded["billing_status"] == "PENDING_BOL", loaded["billing_status"]

        tank = get_success_data(api.get_tank(scenario["tank"]["id"], PROCESS_OPERATOR))
        assert_2dp(tank["current_gallons"], 134100.00, "current_gallons")
        assert_2dp(tank["available_gallons"], 865900.00, "available_gallons")

    def test_documenting_then_invoicing_prices_the_gallons_actually_drawn(self, api):
        """The bill of lading is stamped at the clock and the invoice is 48260850 cents.

        PRD 3.6: "The coordinator supplies the `bol_number`, which is stored
        alongside `bol_issued_at`, and the billing dimension moves `PENDING_BOL →
        BOL_ISSUED`."

        PRD 3.6: "`invoice_amount_cents` is computed as `loaded_gallons` multiplied
        by `price_cents_per_gallon`, rounded half up to a whole number of cents,
        and `invoiced_at` is recorded."

        PRD 3.6: "A new track opens with `committed_railcars` at 0, that figure
        being the sum of `railcar_count` over shipments on the track whose
        `loading_status` is `SCHEDULED`, `BLOCKED` or `LOADED` — cancelled
        shipments release their railcars entirely."

        Design: Corner/endpoints/load_then_bol_then_invoice_prices_the_gallons_actually_drawn
        """
        scenario = _scheduled_train(api)
        get_success_data(api.load_shipment(scenario["shipment"]["id"], LOGISTICS_COORDINATOR))

        documented = validate_success(
            api.issue_bill_of_lading(
                scenario["shipment"]["id"], {"bol_number": "BOL-77001"}, LOGISTICS_COORDINATOR
            ),
            200,
        )
        assert documented["billing_status"] == "BOL_ISSUED", documented["billing_status"]
        assert documented["bol_number"] == "BOL-77001", documented["bol_number"]
        assert_instant_equals(
            documented["bol_issued_at"], "2026-09-04T06:00:00Z", "bol_issued_at"
        )

        invoiced = validate_success(
            api.invoice_shipment(scenario["shipment"]["id"], LOGISTICS_COORDINATOR), 200
        )
        assert invoiced["billing_status"] == "INVOICED", invoiced["billing_status"]
        assert invoiced["invoice_amount_cents"] == 48260850, invoiced["invoice_amount_cents"]
        assert invoiced["loading_status"] == "LOADED", invoiced["loading_status"]

        track = get_success_data(api.get_track(scenario["track"]["id"], LOGISTICS_COORDINATOR))
        assert track["committed_railcars"] == 100, track["committed_railcars"]


def _scheduled_on_spec_blend(api):
    """BL-1: 2565.00 neat and 60.00 denaturant gallons into an empty T-301."""
    plant = fx.commission_plant(
        api, base_grind_cap_bushels=120000, coverage_floor_bushels=5000
    )
    fx.advance_clock(api, "2026-09-04T06:00:00Z")
    farm = fx.standard_tank_farm(
        api, neat_opening=500000.00, denaturant_opening=500000.00
    )
    blend = fx.schedule_blend(
        api,
        farm["neat"]["id"],
        farm["denaturant"]["id"],
        farm["e100"]["id"],
        farm["e100"]["version"],
        blend_code="BL-1",
        neat_gallons=2565.00,
        denaturant_gallons=60.00,
        window_start="2026-09-04T06:00:00Z",
        window_end="2026-09-04T10:00:00Z",
    )
    return {"plant": plant, "farm": farm, "blend": blend}


class TestBlendExecutionMovesAllThreeBalances:
    """One call debits two tanks and credits a third in the same transaction."""

    def test_scheduling_reserves_the_window_and_computes_nothing_yet(self, api):
        """The destination is empty, the output is null and occupancy runs to noon.

        PRD 3.5: "`opening_gallons`, the volume already in the tank at
        commissioning, defaults to 0 and must be at least zero and no greater than
        the capacity; and `settling_buffer_minutes`, defaulting to 120, a
        non-negative whole number of minutes appended to the end of every blend
        window on this tank before its occupancy interval is compared with other
        reservations."

        PRD 3.5: "The blend's `occupancy_end` is computed as `window_end` plus the
        destination tank's `settling_buffer_minutes`, and the reserved interval
        runs from `window_start` through `occupancy_end` as a **closed** interval
        on both ends."

        Design: Corner/endpoints/blend_execute_debits_two_source_tanks_and_credits_the_destination
        """
        scenario = _scheduled_on_spec_blend(api)

        assert_2dp(scenario["farm"]["e100"]["current_gallons"], 0.00, "current_gallons")
        assert scenario["blend"]["status"] == "SCHEDULED", scenario["blend"]["status"]
        assert_null(scenario["blend"]["output_gallons"], "output_gallons")
        assert_instant_equals(
            scenario["blend"]["occupancy_end"], "2026-09-04T12:00:00Z", "occupancy_end"
        )

    def test_execution_debits_both_sources_and_credits_the_destination(self, api):
        """497435.00, 499940.00 and 2625.00 after a single execute call.

        PRD 3.5: "On success the blend moves `SCHEDULED → EXECUTED`, `executed_at`
        is recorded, the two sources are debited and the destination credited, and
        all three tanks have their `version` incremented alongside the blend's
        own."

        PRD 3.5: "`available_gallons` is `capacity_gallons` less `current_gallons`,
        floored at 0.00, and both figures carry two decimals."

        Design: Corner/endpoints/blend_execute_debits_two_source_tanks_and_credits_the_destination
        """
        scenario = _scheduled_on_spec_blend(api)

        executed = validate_success(
            api.execute_blend(scenario["blend"]["id"], PROCESS_OPERATOR), 200
        )
        assert executed["status"] == "EXECUTED", executed["status"]
        assert_2dp(executed["output_gallons"], 2625.00, "output_gallons")
        assert_6dp(executed["denaturant_pct"], 0.022857, "denaturant_pct")
        assert_instant_equals(
            executed["executed_at"], "2026-09-04T06:00:00Z", "executed_at"
        )

        neat = get_success_data(api.get_tank(scenario["farm"]["neat"]["id"], PROCESS_OPERATOR))
        assert_2dp(neat["current_gallons"], 497435.00, "current_gallons")
        denaturant = get_success_data(
            api.get_tank(scenario["farm"]["denaturant"]["id"], PROCESS_OPERATOR)
        )
        assert_2dp(denaturant["current_gallons"], 499940.00, "current_gallons")
        e100 = get_success_data(api.get_tank(scenario["farm"]["e100"]["id"], PROCESS_OPERATOR))
        assert_2dp(e100["current_gallons"], 2625.00, "current_gallons")
        assert_2dp(e100["available_gallons"], 997375.00, "available_gallons")


def _two_conditions_with_their_own_readings(api):
    """
    PC-1 carries two air readings and PC-2 a single water reading, all posted
    under their own paths with the clock at 2026-09-04T12:00:00Z.
    """
    plant = fx.commission_plant(
        api, base_grind_cap_bushels=120000, coverage_floor_bushels=5000
    )
    fx.advance_clock(api, "2026-09-04T12:00:00Z")
    air = fx.register_condition(
        api,
        condition_code="PC-1",
        permit_type="AIR_EMISSIONS",
        parameter_name="VOC",
        limit_value=15.000,
        unit="lb/hr",
        averaging_period_hours=24,
        severity="MINOR",
    )
    water = fx.register_condition(
        api,
        condition_code="PC-2",
        permit_type="WATER_DISCHARGE",
        parameter_name="TSS",
        limit_value=30.000,
        unit="mg/L",
        averaging_period_hours=24,
        severity="MINOR",
    )

    first = validate_success(
        api.create_permit_reading(
            air["id"],
            {
                "measured_at": "2026-09-04T06:00:00Z",
                "value": 12.400,
                "sample_reference": "LAB-A1",
            },
            PROCESS_OPERATOR,
        ),
        201,
    )
    second = validate_success(
        api.create_permit_reading(
            air["id"], {"measured_at": "2026-09-04T11:00:00Z", "value": 13.000}, PROCESS_OPERATOR
        ),
        201,
    )
    third = validate_success(
        api.create_permit_reading(
            water["id"],
            {"measured_at": "2026-09-04T09:00:00Z", "value": 5.000},
            COMPLIANCE_OFFICER,
        ),
        201,
    )
    return {
        "plant": plant,
        "air": air,
        "water": water,
        "first": first,
        "second": second,
        "third": third,
    }


class TestPermitReadingsBelongToThePathCondition:
    """Two registers of readings that never bleed into one another."""

    def test_the_condition_reference_comes_from_the_path_and_the_reference_defaults(self, api):
        """Each reading points at the condition it was posted under, sample reference optional.

        PRD 3.9: "A condition opens at `status` `COMPLIANT` with
        `readings_in_window` at 0, `rolling_average_value` null and
        `exceedance_count` at 0."

        PRD 3.9: "each carrying the `measured_at` instant the sample was taken, the
        `value` observed (not negative, three decimals) and an optional
        `sample_reference` naming the laboratory record, defaulting to null. A
        reading is an immutable observation rather than a managed resource: it
        carries only its own `id` and `created_at`, has no version and is never
        updated or deleted. The condition's own `condition_id` is taken from the
        path."

        Design: Corner/endpoints/permit_readings_are_scoped_to_the_condition_in_the_path
        """
        scenario = _two_conditions_with_their_own_readings(api)

        assert scenario["air"]["readings_in_window"] == 0, scenario["air"]["readings_in_window"]
        assert_null(scenario["air"]["rolling_average_value"], "rolling_average_value")
        assert scenario["air"]["exceedance_count"] == 0, scenario["air"]["exceedance_count"]

        assert scenario["first"]["condition_id"] == scenario["air"]["id"], (
            scenario["first"]["condition_id"]
        )
        assert scenario["third"]["condition_id"] == scenario["water"]["id"], (
            scenario["third"]["condition_id"]
        )
        assert_null(scenario["second"]["sample_reference"], "sample_reference")

    def test_each_condition_averages_only_its_own_readings(self, api):
        """12.700 over two air readings and 5.000 over one water reading.

        PRD 3.9: "`readings_in_window` is the count of readings inside, and
        `rolling_average_value` is the sum of their values divided by that count,
        rounded half up to three decimals — or null when the window is empty, which
        is not the same as zero."

        PRD 3.9: "Readings are listed under their condition ordered by
        `measured_at` ascending and then `created_at` ascending."

        Design: Corner/endpoints/permit_readings_are_scoped_to_the_condition_in_the_path
        """
        scenario = _two_conditions_with_their_own_readings(api)

        air = get_success_data(
            api.get_permit_condition(scenario["air"]["id"], COMPLIANCE_OFFICER)
        )
        assert_3dp(air["rolling_average_value"], 12.700, "rolling_average_value")
        assert air["readings_in_window"] == 2, air["readings_in_window"]
        assert air["status"] == "COMPLIANT", air["status"]

        water = get_success_data(
            api.get_permit_condition(scenario["water"]["id"], COMPLIANCE_OFFICER)
        )
        assert_3dp(water["rolling_average_value"], 5.000, "rolling_average_value")
        assert water["readings_in_window"] == 1, water["readings_in_window"]

        air_rows, _ = validate_paginated(
            api.list_permit_readings(scenario["air"]["id"], COMPLIANCE_OFFICER)
        )
        assert len(air_rows) == 2, f"PC-1 owns two readings, got {air_rows!r}"
        water_rows, _ = validate_paginated(
            api.list_permit_readings(scenario["water"]["id"], COMPLIANCE_OFFICER)
        )
        assert len(water_rows) == 1, f"PC-2 owns one reading, got {water_rows!r}"


def _graded_load_awaiting_settlement(api):
    """TK-0001 graded on the basis grades against a 200000.00 bushel PRICED contract."""
    plant = fx.commission_plant(
        api, base_grind_cap_bushels=120000, coverage_floor_bushels=5000
    )
    contract = fx.priced_contract(
        api, 458.0, supplier_name="Cedar Ridge Elevator", bushels_contracted=200000.00
    )
    graded = fx.graded_load(
        api,
        contract["id"],
        delivery_overrides={"ticket_number": "TK-0001"},
        grade_overrides={
            "moisture_pct": 15.00,
            "test_weight_lb_per_bu": 54.0,
            "foreign_material_pct": 3.00,
            "damaged_kernels_pct": 5.00,
            "aflatoxin_ppb": 3,
        },
    )
    return {"plant": plant, "contract": contract, "graded": graded}


class TestSettlementIsVisibleImmediately:
    """The settle response and the reads that follow it agree to the cent."""

    def test_the_settle_response_already_carries_the_bushels_and_the_money(self, api):
        """940.00 dry bushels at 440.00 cents settle at 413600 in the same response.

        PRD 3.3: "`net_price_cents_per_bushel` is the contract gross price less that
        total discount, with a floor of 0.00 so a load can never carry a negative
        price; and at settlement `settlement_amount_cents` is `net_dry_bushels`
        multiplied by `net_price_cents_per_bushel`, rounded half up to a whole
        number of cents."

        PRD 3.2: "the contract's **gross price** — the futures leg plus the basis,
        in cents per bushel — becomes available to the settlement arithmetic of
        §3.3."

        Design: Corner/consistency_model/settlement_aggregates_are_visible_in_the_same_response
        """
        scenario = _graded_load_awaiting_settlement(api)
        assert scenario["graded"]["grading_status"] == "GRADED", (
            scenario["graded"]["grading_status"]
        )
        assert scenario["contract"]["pricing_status"] == "PRICED", (
            scenario["contract"]["pricing_status"]
        )

        settled = validate_success(
            api.settle_delivery(scenario["graded"]["id"], GRAIN_ACCOUNTANT), 200
        )
        assert settled["grading_status"] == "SETTLED", settled["grading_status"]
        assert_2dp(settled["net_dry_bushels"], 940.00, "net_dry_bushels")
        assert_2dp(settled["net_price_cents_per_bushel"], 440.00, "net_price_cents_per_bushel")
        assert settled["settlement_amount_cents"] == 413600, settled["settlement_amount_cents"]

    def test_the_contract_and_the_plant_agree_on_the_very_next_read(self, api):
        """Coverage, inventory and posture are all current without a second write.

        PRD 2.10: "`corn_inventory_bushels`, `ddgs_inventory_tons`,
        `corn_oil_inventory_lbs`, `open_contract_coverage_bushels`,
        `rolling_yield_gal_per_bushel`, `rin_generated_count`,
        `rin_separated_count` and `rin_retired_count` are each defined as a sum
        over primary records in a named state, and after any action that changes
        those records the aggregate is recomputed from scratch."

        PRD 3.3: "The delivered bushels are then added to the plant's
        `corn_inventory_bushels`. Finally `open_contract_coverage_bushels` is
        re-derived, then `procurement_posture`, then `daily_grind_cap_bushels`."

        Design: Corner/consistency_model/settlement_aggregates_are_visible_in_the_same_response
        """
        scenario = _graded_load_awaiting_settlement(api)
        assert_2dp(scenario["plant"]["corn_inventory_bushels"], 0.00, "corn_inventory_bushels")
        assert_2dp(
            scenario["plant"]["open_contract_coverage_bushels"],
            0.00,
            "open_contract_coverage_bushels",
        )
        assert scenario["plant"]["procurement_posture"] == "SHORT", (
            scenario["plant"]["procurement_posture"]
        )

        get_success_data(api.settle_delivery(scenario["graded"]["id"], GRAIN_ACCOUNTANT))

        contract = get_success_data(
            api.get_contract(scenario["contract"]["id"], GRAIN_ACCOUNTANT)
        )
        assert_2dp(contract["bushels_delivered"], 940.00, "bushels_delivered")
        assert contract["status"] == "PARTIALLY_FILLED", contract["status"]

        plant = get_success_data(api.get_plant(scenario["plant"]["id"], GRAIN_ACCOUNTANT))
        assert_2dp(plant["corn_inventory_bushels"], 940.00, "corn_inventory_bushels")
        assert_2dp(
            plant["open_contract_coverage_bushels"], 199060.00, "open_contract_coverage_bushels"
        )
        assert_plant_posture(plant, "OPEN", "ADEQUATE")
