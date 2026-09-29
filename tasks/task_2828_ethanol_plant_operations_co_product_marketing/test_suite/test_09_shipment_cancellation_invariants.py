"""
Cancellation as a compensating action, checked through the invariants it protects.

Cancelling a loaded train must restore the source tank to precisely its pre-load
balance and hand back its railcars, and must revert a credit separation without
ever disturbing the count of credits the plant has generated.
"""

from test_helpers import fixtures as fx
from test_helpers import get_success_data, validate_error, validate_paginated, validate_success
from test_helpers.api_errors import ApiErrorId
from test_helpers.assertions import assert_2dp, assert_instant_equals, assert_null
from test_helpers.test_users import (
    COMPLIANCE_OFFICER,
    LOGISTICS_COORDINATOR,
    PLANT_MANAGER,
    PROCESS_OPERATOR,
)

_CANCEL = {"cancellation_reason": "Buyer cancelled the train"}


def _loaded_train_off_a_full_tank(api):
    """UT-C001 has drawn 265900.00 gallons out of a tank that opened with 400000.00."""
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
    shipment = fx.loaded_shipment(
        api, track["id"], tank["id"], track["version"],
        shipment_code="UT-C001", destination_terminal="Chicago Rail Terminal",
        railcar_count=100, gallons_per_railcar=2659.00,
        window_start="2026-09-05T06:00:00Z", window_end="2026-09-05T12:00:00Z",
        price_cents_per_gallon=181.50,
    )
    return {"tank": tank, "track": track, "shipment": shipment}


def _train_carrying_a_separated_credit_batch(api):
    """UT-D001 railed 2625.00 gallons under BOL-D001, separating a 2616-credit batch."""
    plant = fx.commission_plant(
        api,
        base_grind_cap_bushels=120000,
        coverage_floor_bushels=5000,
        baseline_ci_g_per_mj=60.0,
        rin_generation_enabled=True,
    )
    fx.advance_clock(api, "2026-09-01T00:00:00Z")
    neat = fx.commission_tank(api, "T-101", "ETHANOL_200_PROOF", 1000000.00, opening_gallons=0.00)
    denaturant = fx.commission_tank(api, "T-201", "DENATURANT", 600000.00, opening_gallons=500000.00)
    e100 = fx.commission_tank(
        api, "T-301", "DENATURED_E100", 1000000.00,
        opening_gallons=0.00, settling_buffer_minutes=120,
    )
    contract = fx.priced_contract(api, 458.0, supplier_name="Cedar Ridge Elevator")
    fx.settled_load(api, contract["id"])

    fx.advance_clock(api, "2026-09-03T00:00:00Z")
    fx.completed_batch(
        api, neat["id"], batch_code="FB-8001",
        corn_bushels_charged=900.00, charge_test_weight_lb_per_bu=54.0,
    )

    fx.advance_clock(api, "2026-09-04T06:00:00Z")
    e100_now = get_success_data(api.get_tank(e100["id"], PROCESS_OPERATOR))
    fx.executed_blend(
        api, neat["id"], denaturant["id"], e100["id"], e100_now["version"],
        blend_code="BL-1", neat_gallons=2565.00, denaturant_gallons=60.00,
        window_start="2026-09-04T08:00:00Z", window_end="2026-09-04T12:00:00Z",
    )

    track = fx.commission_track(api, loading_rate_cars_per_hour=20.0, is_active=True)
    fx.advance_clock(api, "2026-09-05T05:00:00Z")
    shipment = fx.documented_shipment(
        api, track["id"], e100["id"], track["version"], bol_number="BOL-D001",
        shipment_code="UT-D001", destination_terminal="Chicago Rail Terminal",
        railcar_count=1, gallons_per_railcar=2625.00,
        window_start="2026-09-05T06:00:00Z", window_end="2026-09-05T12:00:00Z",
        price_cents_per_gallon=181.50,
    )
    rows, _meta = validate_paginated(
        api.list_rin_batches(COMPLIANCE_OFFICER, {"separated_shipment_id": shipment["id"]})
    )
    return {
        "plant": plant,
        "e100": e100,
        "track": track,
        "shipment": shipment,
        "credit": rows[0],
    }


class TestCancellationRestoresTheTankBalance:
    """The denatured-gallons invariant across a load and its compensation."""

    def test_cancelling_a_loaded_train_returns_every_gallon_and_every_railcar(self, api):
        """The tank goes back to exactly 400000.00 and the track back to zero commitment.

        PRD 3.6: "Where the shipment had reached `LOADED`, its `loaded_gallons`
        are credited back to the source tank, `loaded_gallons` is set back to null
        and the tank's `version` increments — which restores the tank to precisely
        its pre-load balance, the plant-wide denatured-gallons invariant this
        compensation exists to protect."

        Design: Difficulty/compensating_invariant/shipment_cancel_restores_total_denatured_gallons_invariant
        """
        scenario = _loaded_train_off_a_full_tank(api)
        assert_2dp(scenario["shipment"]["loaded_gallons"], 265900.00, "loaded_gallons")
        drawn_down = get_success_data(api.get_tank(scenario["tank"]["id"], PROCESS_OPERATOR))
        assert_2dp(drawn_down["current_gallons"], 134100.00, "current_gallons")

        cancelled = validate_success(
            api.cancel_shipment(scenario["shipment"]["id"], _CANCEL, LOGISTICS_COORDINATOR), 200
        )
        assert cancelled["loading_status"] == "CANCELLED", cancelled["loading_status"]
        assert cancelled["billing_status"] == "VOIDED", cancelled["billing_status"]
        assert_null(cancelled["loaded_gallons"], "loaded_gallons")
        assert_instant_equals(cancelled["cancelled_at"], "2026-09-05T05:00:00Z", "cancelled_at")

        tank = get_success_data(api.get_tank(scenario["tank"]["id"], PROCESS_OPERATOR))
        assert_2dp(tank["current_gallons"], 400000.00, "current_gallons")
        assert_2dp(tank["available_gallons"], 600000.00, "available_gallons")
        track = get_success_data(api.get_track(scenario["track"]["id"], LOGISTICS_COORDINATOR))
        assert track["committed_railcars"] == 0, track["committed_railcars"]

    def test_a_second_cancellation_is_refused_rather_than_crediting_twice(self, api):
        """The invariant survives a retry because a cancelled train accepts nothing.

        PRD 3.6: "The loading dimension must be `SCHEDULED`, `BLOCKED` or
        `LOADED`, otherwise `ERR_INVALID_SHIPMENT_LOADING_STATE`; and the billing
        dimension must not be `INVOICED`, otherwise
        `ERR_SHIPMENT_ALREADY_INVOICED` — which is refused even though the loading
        dimension would still allow it."

        Design: Difficulty/compensating_invariant/shipment_cancel_restores_total_denatured_gallons_invariant
        """
        scenario = _loaded_train_off_a_full_tank(api)
        get_success_data(
            api.cancel_shipment(scenario["shipment"]["id"], _CANCEL, LOGISTICS_COORDINATOR)
        )

        validate_error(
            api.cancel_shipment(scenario["shipment"]["id"], _CANCEL, LOGISTICS_COORDINATOR),
            ApiErrorId.INVALID_SHIPMENT_LOADING_STATE,
            409,
        )

        tank = get_success_data(api.get_tank(scenario["tank"]["id"], PROCESS_OPERATOR))
        assert_2dp(tank["current_gallons"], 400000.00, "current_gallons")
        track = get_success_data(api.get_track(scenario["track"]["id"], LOGISTICS_COORDINATOR))
        assert track["committed_railcars"] == 0, track["committed_railcars"]


class TestCancellationPreservesGeneratedCredits:
    """Separation is reverted; generation is not."""

    def test_cancelling_reverts_the_separation_but_not_the_generation(self, api):
        """The credit batch returns to GENERATED while rin_generated_count stays at 2616.

        PRD 3.8: "Every credit batch whose `separated_shipment_id` is the
        cancelled shipment and whose status is still `SEPARATED` returns to
        `GENERATED` with both `separated_shipment_id` and `separated_at` cleared,
        which lowers the plant's `rin_separated_count` while leaving
        `rin_generated_count` untouched."

        Design: Difficulty/compensating_invariant/shipment_cancel_preserves_rin_generated_count_invariant
        """
        scenario = _train_carrying_a_separated_credit_batch(api)
        assert scenario["credit"]["status"] == "SEPARATED", scenario["credit"]["status"]
        assert scenario["credit"]["rin_count"] == 2616, scenario["credit"]["rin_count"]

        cancelled = validate_success(
            api.cancel_shipment(scenario["shipment"]["id"], _CANCEL, LOGISTICS_COORDINATOR), 200
        )
        assert cancelled["billing_status"] == "VOIDED", cancelled["billing_status"]
        assert cancelled["loading_status"] == "CANCELLED", cancelled["loading_status"]

        credit = get_success_data(api.get_rin_batch(scenario["credit"]["id"], COMPLIANCE_OFFICER))
        assert credit["status"] == "GENERATED", credit["status"]
        assert_null(credit["separated_shipment_id"], "separated_shipment_id")
        assert_null(credit["separated_at"], "separated_at")

        plant = get_success_data(api.get_plant(scenario["plant"]["id"], PLANT_MANAGER))
        assert plant["rin_separated_count"] == 0, plant["rin_separated_count"]
        assert plant["rin_generated_count"] == 2616, plant["rin_generated_count"]

        tank = get_success_data(api.get_tank(scenario["e100"]["id"], PROCESS_OPERATOR))
        assert_2dp(tank["current_gallons"], 2625.00, "current_gallons")
        track = get_success_data(api.get_track(scenario["track"]["id"], LOGISTICS_COORDINATOR))
        assert track["committed_railcars"] == 0, track["committed_railcars"]

    def test_the_reverted_credits_can_separate_onto_a_later_train(self, api):
        """Back at GENERATED the batch is a candidate again for the next bill of lading.

        PRD 3.8: "Each separated batch records `separated_shipment_id` pointing at
        the shipment and `separated_at`, and moves to `SEPARATED`."

        Design: Difficulty/compensating_invariant/shipment_cancel_preserves_rin_generated_count_invariant
        """
        scenario = _train_carrying_a_separated_credit_batch(api)
        get_success_data(
            api.cancel_shipment(scenario["shipment"]["id"], _CANCEL, LOGISTICS_COORDINATOR)
        )

        track_now = get_success_data(api.get_track(scenario["track"]["id"], LOGISTICS_COORDINATOR))
        replacement = fx.documented_shipment(
            api, scenario["track"]["id"], scenario["e100"]["id"], track_now["version"],
            bol_number="BOL-D002",
            shipment_code="UT-D002", destination_terminal="Chicago Rail Terminal",
            railcar_count=1, gallons_per_railcar=2625.00,
            window_start="2026-09-05T14:00:00Z", window_end="2026-09-05T18:00:00Z",
            price_cents_per_gallon=181.50,
        )

        credit = get_success_data(api.get_rin_batch(scenario["credit"]["id"], COMPLIANCE_OFFICER))
        assert credit["status"] == "SEPARATED", credit["status"]
        assert credit["separated_shipment_id"] == replacement["id"], credit["separated_shipment_id"]

        plant = get_success_data(api.get_plant(scenario["plant"]["id"], PLANT_MANAGER))
        assert plant["rin_separated_count"] == 2616, plant["rin_separated_count"]
        assert plant["rin_generated_count"] == 2616, plant["rin_generated_count"]
