"""
State machines that are cyclic or multi-dimensional rather than linear.

A fermenter can loop HEALTH_WATCH → FERMENTING → HEALTH_WATCH twice before its
intervention budget is spent, and a unit train runs a physical dimension and a
paperwork dimension on the same row, where the paperwork dimension is what
forbids cancellation.
"""

from test_helpers import fixtures as fx
from test_helpers import get_success_data, validate_error, validate_success
from test_helpers.api_errors import ApiErrorId
from test_helpers.assertions import assert_2dp, assert_null
from test_helpers.test_users import (
    LOGISTICS_COORDINATOR,
    PLANT_MANAGER,
    PROCESS_OPERATOR,
)

_SICK_READING = {
    "lactic_acid_ppm": 1237,
    "acetic_acid_ppm": 552,
    "temperature_c": 36.9,
}


def _batch_with_both_interventions_spent(api):
    """
    FB-3001 driven onto health watch three times, dosed after the first two, so
    its intervention budget of two is exhausted and the index sits at 41.89.
    """
    plant = fx.commission_plant(
        api,
        base_grind_cap_bushels=120000,
        coverage_floor_bushels=5000,
        baseline_ci_g_per_mj=60.0,
        rin_generation_enabled=True,
    )
    fx.advance_clock(api, "2026-09-01T00:00:00Z")
    tank = fx.commission_tank(api, "T-101", "ETHANOL_200_PROOF", 1000000.00, opening_gallons=0.00)
    contract = fx.priced_contract(api, 458.0, supplier_name="Cedar Ridge Elevator")
    fx.settled_load(api, contract["id"])
    batch = fx.charge_batch(
        api,
        tank["id"],
        batch_code="FB-3001",
        corn_bushels_charged=900.00,
        charge_test_weight_lb_per_bu=54.0,
    )

    states = []
    for hours in (12, 24, 36):
        reading = get_success_data(
            api.create_health_reading(
                batch["id"], dict(_SICK_READING, hours_elapsed=hours), PROCESS_OPERATOR
            )
        )
        assert reading is not None
        after_reading = get_success_data(api.get_batch(batch["id"], PROCESS_OPERATOR))
        states.append(after_reading["status"])
        if hours < 36:
            dosed = get_success_data(
                api.intervene_batch(
                    batch["id"], {"intervention_note": "Dosed with antimicrobial"}, PROCESS_OPERATOR
                )
            )
            states.append(dosed["status"])
    return {"plant": plant, "batch": batch, "states": states}


def _invoiced_train(api):
    """UT-7001: 100 railcars of 2659.00 gallons loaded, documented and invoiced."""
    fx.commission_plant(
        api,
        base_grind_cap_bushels=120000,
        coverage_floor_bushels=5000,
        baseline_ci_g_per_mj=60.0,
        rin_generation_enabled=True,
    )
    fx.advance_clock(api, "2026-09-05T05:00:00Z")
    tank = fx.commission_tank(
        api, "T-301", "DENATURED_E100", 1000000.00,
        opening_gallons=400000.00, settling_buffer_minutes=120,
    )
    track = fx.commission_track(api, loading_rate_cars_per_hour=20.0, is_active=True)
    shipment = fx.invoiced_shipment(
        api,
        track["id"],
        tank["id"],
        track["version"],
        bol_number="BOL-7001",
        shipment_code="UT-7001",
        railcar_count=100,
        gallons_per_railcar=2659.00,
        window_start="2026-09-05T06:00:00Z",
        window_end="2026-09-05T12:00:00Z",
        price_cents_per_gallon=181.50,
    )
    return {"tank": tank, "track": track, "shipment": shipment}


class TestFermentationInterventionCycle:
    """Two dosing cycles, then a spent budget."""

    def test_each_dose_returns_the_batch_to_fermenting_and_the_next_reading_sends_it_back(self, api):
        """The batch loops health watch and fermenting twice under identical readings.

        PRD 3.4: "A `ProcessOperator` doses the batch, recording a free-text
        `intervention_note`, and the batch moves `HEALTH_WATCH → FERMENTING`."

        Design: Difficulty/non_linear_state_machine/fermentation_health_watch_intervention_cycle_third_intervention_blocked
        """
        scenario = _batch_with_both_interventions_spent(api)

        assert scenario["states"] == [
            "HEALTH_WATCH",
            "FERMENTING",
            "HEALTH_WATCH",
            "FERMENTING",
            "HEALTH_WATCH",
        ], scenario["states"]

        batch = get_success_data(api.get_batch(scenario["batch"]["id"], PROCESS_OPERATOR))
        assert batch["intervention_count"] == 2, batch["intervention_count"]
        assert_2dp(batch["fermentation_health_index"], 41.89, "fermentation_health_index")

    def test_a_third_dose_is_refused_and_leaves_the_batch_stranded_on_health_watch(self, api):
        """With both doses spent the batch can only be dumped, never dosed again.

        PRD 3.4: "At most two interventions are permitted per batch; a third is
        refused with `ERR_INTERVENTION_LIMIT_REACHED`, which means a batch that
        keeps degrading after two doses can only be dumped."

        Design: Difficulty/non_linear_state_machine/fermentation_health_watch_intervention_cycle_third_intervention_blocked
        """
        scenario = _batch_with_both_interventions_spent(api)

        validate_error(
            api.intervene_batch(
                scenario["batch"]["id"],
                {"intervention_note": "Third dose attempt"},
                PROCESS_OPERATOR,
            ),
            ApiErrorId.INTERVENTION_LIMIT_REACHED,
            422,
        )

        batch = get_success_data(api.get_batch(scenario["batch"]["id"], PROCESS_OPERATOR))
        assert batch["status"] == "HEALTH_WATCH", batch["status"]
        assert batch["intervention_count"] == 2, batch["intervention_count"]
        assert_2dp(batch["fermentation_health_index"], 41.89, "fermentation_health_index")

        plant = get_success_data(api.get_plant(scenario["plant"]["id"], PLANT_MANAGER))
        assert_2dp(plant["corn_inventory_bushels"], 40.00, "corn_inventory_bushels")


class TestShipmentBillingDimensionBlocksCancellation:
    """The paperwork dimension refuses a cancellation the physical dimension allows."""

    def test_invoicing_prices_the_loaded_gallons_and_leaves_the_train_loaded(self, api):
        """The two dimensions advance independently: LOADED physically, INVOICED on paper.

        PRD 3.6: "`invoice_amount_cents` is computed as `loaded_gallons`
        multiplied by `price_cents_per_gallon`, rounded half up to a whole number
        of cents, and `invoiced_at` is recorded."

        Design: Difficulty/non_linear_state_machine/shipment_billing_dimension_blocks_cancel_after_invoice_while_loading_dimension_unchanged
        """
        scenario = _invoiced_train(api)
        shipment = scenario["shipment"]

        assert shipment["loading_status"] == "LOADED", shipment["loading_status"]
        assert shipment["billing_status"] == "INVOICED", shipment["billing_status"]
        assert_2dp(shipment["loaded_gallons"], 265900.00, "loaded_gallons")
        assert shipment["invoice_amount_cents"] == 48260850, shipment["invoice_amount_cents"]
        assert shipment["invoiced_at"] is not None, "invoiced_at must be recorded"

    def test_cancelling_an_invoiced_train_is_refused_and_reverses_nothing(self, api):
        """Invoicing is the point of no return, so no compensating reversal fires.

        PRD 3.6: "The loading dimension must be `SCHEDULED`, `BLOCKED` or
        `LOADED`, otherwise `ERR_INVALID_SHIPMENT_LOADING_STATE`; and the billing
        dimension must not be `INVOICED`, otherwise
        `ERR_SHIPMENT_ALREADY_INVOICED` — which is refused even though the
        loading dimension would still allow it."

        Design: Difficulty/non_linear_state_machine/shipment_billing_dimension_blocks_cancel_after_invoice_while_loading_dimension_unchanged
        """
        scenario = _invoiced_train(api)

        validate_error(
            api.cancel_shipment(
                scenario["shipment"]["id"],
                {"cancellation_reason": "Buyer cancelled the train"},
                LOGISTICS_COORDINATOR,
            ),
            ApiErrorId.SHIPMENT_ALREADY_INVOICED,
            409,
        )

        shipment = validate_success(
            api.get_shipment(scenario["shipment"]["id"], LOGISTICS_COORDINATOR), 200
        )
        assert shipment["loading_status"] == "LOADED", shipment["loading_status"]
        assert shipment["billing_status"] == "INVOICED", shipment["billing_status"]
        assert_null(shipment["cancelled_at"], "cancelled_at")
        assert_2dp(shipment["loaded_gallons"], 265900.00, "loaded_gallons")

        tank = get_success_data(api.get_tank(scenario["tank"]["id"], PROCESS_OPERATOR))
        assert_2dp(tank["current_gallons"], 134100.00, "current_gallons")
        track = get_success_data(api.get_track(scenario["track"]["id"], LOGISTICS_COORDINATOR))
        assert track["committed_railcars"] == 100, track["committed_railcars"]
