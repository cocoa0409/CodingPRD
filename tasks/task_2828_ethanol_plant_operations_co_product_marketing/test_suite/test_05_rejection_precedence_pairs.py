"""
Requests that break two rules at once, where only one error may be reported.

Both scenarios below are deliberately doubly-invalid: the ladder of section 2.9
decides which failure is reported, and the loser must never appear.
"""

from test_helpers import fixtures as fx
from test_helpers import get_success_data, validate_error
from test_helpers.api_errors import ApiErrorId
from test_helpers.assertions import assert_2dp, assert_3dp, assert_null, assert_plant_posture
from test_helpers.test_users import (
    COMPLIANCE_OFFICER,
    LOGISTICS_COORDINATOR,
    PLANT_MANAGER,
    PROCESS_OPERATOR,
)


def _health_watch_batch_with_a_held_tank(api):
    """FB-4001 stuck on health watch, whose destination tank is also off spec."""
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
        batch_code="FB-4001",
        corn_bushels_charged=900.00,
        charge_test_weight_lb_per_bu=54.0,
    )
    fx.append_health_reading(
        api, batch["id"], hours_elapsed=12, lactic_acid_ppm=1237,
        acetic_acid_ppm=552, temperature_c=36.9,
    )
    fx.hold_tank(api, tank["id"], "OFF_SPEC")
    return {"plant": plant, "tank": tank, "batch": batch}


def _suspended_plant_with_an_oversized_train(api):
    """
    UT-8001 plans to draw 265900.00 gallons from a tank holding 100000.00, while
    a CRITICAL air exceedance has suspended the plant outright.
    """
    plant = fx.commission_plant(
        api,
        base_grind_cap_bushels=120000,
        coverage_floor_bushels=5000,
        baseline_ci_g_per_mj=60.0,
        rin_generation_enabled=True,
    )
    fx.advance_clock(api, "2026-09-05T05:00:00Z")
    tank = fx.commission_tank(
        api, "T-301", "DENATURED_E100", 1000000.00,
        opening_gallons=100000.00, settling_buffer_minutes=120,
    )
    track = fx.commission_track(api, loading_rate_cars_per_hour=20.0, is_active=True)
    shipment = fx.schedule_shipment(
        api, track["id"], tank["id"], track["version"],
        shipment_code="UT-8001", destination_terminal="Chicago Rail Terminal",
        railcar_count=100, gallons_per_railcar=2659.00,
        window_start="2026-09-05T06:00:00Z", window_end="2026-09-05T12:00:00Z",
        price_cents_per_gallon=181.50,
    )
    condition = fx.register_condition(
        api,
        condition_code="PC-AIR-1",
        permit_type="AIR_EMISSIONS",
        parameter_name="VOC",
        limit_value=12.500,
        unit="lb/hr",
        averaging_period_hours=24,
        severity="CRITICAL",
    )
    fx.append_permit_reading(
        api, condition["id"], "2026-09-05T04:00:00Z", 13.000, sample_reference="CEMS-0001"
    )
    return {"plant": plant, "tank": tank, "shipment": shipment, "condition": condition}


class TestDistillStatePrecedesTankService:
    """A distil call that breaks both the state tier and the safety tier."""

    def test_the_batch_state_error_wins_over_the_held_tank(self, api):
        """State preconditions are checked before safety gates, so the 409 is reported.

        PRD 2.9: "When a batch is asked to distil while it is not `FERMENTING`
        **and** its destination tank is out of service, the state check wins and
        the response is `ERR_INVALID_BATCH_STATE`, not `ERR_TANK_NOT_IN_SERVICE`."

        Design: Difficulty/priority_pair_validation_conflict/distill_state_error_precedes_tank_service_safety_error
        """
        scenario = _health_watch_batch_with_a_held_tank(api)

        response = api.distill_batch(scenario["batch"]["id"], PROCESS_OPERATOR)
        validate_error(response, ApiErrorId.INVALID_BATCH_STATE, 409)
        assert response.json()["data"]["error_id"] != ApiErrorId.TANK_NOT_IN_SERVICE, (
            "the safety tier must never be reached while the state tier already fails"
        )

    def test_the_refused_distillation_freezes_no_yield_and_leaves_both_rows_alone(self, api):
        """Nothing is written: the batch keeps its state and the tank keeps its hold.

        PRD 3.4: "Sending the batch to the still moves it `FERMENTING →
        DISTILLING` and takes no request body."

        Design: Difficulty/priority_pair_validation_conflict/distill_state_error_precedes_tank_service_safety_error
        """
        scenario = _health_watch_batch_with_a_held_tank(api)
        validate_error(
            api.distill_batch(scenario["batch"]["id"], PROCESS_OPERATOR),
            ApiErrorId.INVALID_BATCH_STATE,
            409,
        )

        batch = get_success_data(api.get_batch(scenario["batch"]["id"], PROCESS_OPERATOR))
        assert batch["status"] == "HEALTH_WATCH", batch["status"]
        assert_null(batch["distillation_started_at"], "distillation_started_at")
        assert_null(batch["effective_yield_gal_per_bushel"], "effective_yield_gal_per_bushel")

        tank = get_success_data(api.get_tank(scenario["tank"]["id"], PROCESS_OPERATOR))
        assert tank["service_status"] == "ON_HOLD", tank["service_status"]
        assert tank["hold_reason"] == "OFF_SPEC", tank["hold_reason"]

        plant = get_success_data(api.get_plant(scenario["plant"]["id"], PLANT_MANAGER))
        assert_plant_posture(
            plant, compliance_posture="RESTRICTED", daily_grind_cap_bushels=108000
        )


class TestLoadSafetyPrecedesTankVolume:
    """A load call that breaks both the safety tier and the fiscal tier."""

    def test_the_suspension_wins_over_the_empty_tank(self, api):
        """The safety gate fires first, so the fiscal volume check is never reached.

        PRD 2.9: "When a train is asked to load while the plant is `SUSPENDED`
        **and** the source tank holds less liquid than the shipment plans to
        draw, the safety gate wins and the response is `ERR_PLANT_SUSPENDED`, not
        `ERR_INSUFFICIENT_TANK_VOLUME`."

        Design: Difficulty/priority_pair_validation_conflict/shipment_posture_safety_error_precedes_tank_volume_fiscal_error
        """
        scenario = _suspended_plant_with_an_oversized_train(api)

        response = api.load_shipment(scenario["shipment"]["id"], LOGISTICS_COORDINATOR)
        validate_error(response, ApiErrorId.PLANT_SUSPENDED, 422)
        assert response.json()["data"]["error_id"] != ApiErrorId.INSUFFICIENT_TANK_VOLUME, (
            "the fiscal tier is evaluated last and must not win here"
        )

    def test_the_critical_exceedance_suspends_the_plant_and_the_train_stays_scheduled(self, api):
        """One CRITICAL reading zeroes the grind cap and the refused load moves no liquid.

        PRD 2.8: "Starting from `OPEN`, each permit condition in exceedance
        raises the posture to at least `RESTRICTED` when its `severity` is
        `MINOR`, at least `CURTAILED` when its severity is `MAJOR`, and
        `SUSPENDED` when its severity is `CRITICAL`; each off-spec tank hold
        raises it to at least `RESTRICTED`."

        Design: Difficulty/priority_pair_validation_conflict/shipment_posture_safety_error_precedes_tank_volume_fiscal_error
        """
        scenario = _suspended_plant_with_an_oversized_train(api)
        validate_error(
            api.load_shipment(scenario["shipment"]["id"], LOGISTICS_COORDINATOR),
            ApiErrorId.PLANT_SUSPENDED,
            422,
        )

        condition = get_success_data(
            api.get_permit_condition(scenario["condition"]["id"], COMPLIANCE_OFFICER)
        )
        assert condition["status"] == "EXCEEDANCE", condition["status"]
        assert_3dp(condition["rolling_average_value"], 13.000, "rolling_average_value")
        assert condition["readings_in_window"] == 1, condition["readings_in_window"]
        assert condition["exceedance_count"] == 1, condition["exceedance_count"]

        plant = get_success_data(api.get_plant(scenario["plant"]["id"], PLANT_MANAGER))
        assert_plant_posture(
            plant, compliance_posture="SUSPENDED", daily_grind_cap_bushels=0
        )

        shipment = get_success_data(
            api.get_shipment(scenario["shipment"]["id"], LOGISTICS_COORDINATOR)
        )
        assert shipment["loading_status"] == "SCHEDULED", shipment["loading_status"]
        assert_null(shipment["loaded_gallons"], "loaded_gallons")

        tank = get_success_data(api.get_tank(scenario["tank"]["id"], PROCESS_OPERATOR))
        assert_2dp(tank["current_gallons"], 100000.00, "current_gallons")
