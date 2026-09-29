"""
Actions whose legality is decided by the state of a different entity.

A settlement reads the parent contract's pricing dimension, a distillation reads
the destination tank's service status, and a credit retirement reads the billing
dimension of the train the credit separated onto.
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
)
from test_helpers.test_users import (
    COMPLIANCE_OFFICER,
    GRAIN_ACCOUNTANT,
    GRAIN_BUYER,
    LOGISTICS_COORDINATOR,
    PLANT_MANAGER,
    PROCESS_OPERATOR,
)


def _graded_load_on_an_unpriced_contract(api):
    """TK-0001 graded at 940.00 net dry bushels against a contract still UNPRICED."""
    plant = fx.commission_plant(
        api,
        base_grind_cap_bushels=120000,
        coverage_floor_bushels=5000,
        baseline_ci_g_per_mj=60.0,
        rin_generation_enabled=True,
    )
    fx.advance_clock(api, "2026-09-01T00:00:00Z")
    contract = fx.open_contract(api, supplier_name="Cedar Ridge Elevator")
    graded = fx.graded_load(api, contract["id"])
    return {"plant": plant, "contract": contract, "delivery": graded}


def _fermenting_batch_with_a_held_destination(api):
    """FB-6001 is perfectly healthy, but T-101 has been taken off spec."""
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
        api, tank["id"], batch_code="FB-6001",
        corn_bushels_charged=900.00, charge_test_weight_lb_per_bu=54.0,
    )
    reading = fx.append_health_reading(api, batch["id"])
    fx.hold_tank(api, tank["id"], "OFF_SPEC")
    fx.advance_clock(api, "2026-09-03T00:00:00Z")
    return {"plant": plant, "tank": tank, "batch": batch, "reading": reading}


def _separated_credit_batch_on_an_uninvoiced_train(api):
    """
    The full chain: 900.00 bushels become 2565.00 gallons and 2616 credits, the
    gallons are denatured to 2625.00 and railed out under BOL-7001, which
    separates the credits onto a train that has not yet been invoiced.
    """
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
    completed = fx.completed_batch(
        api, neat["id"], batch_code="FB-7001",
        corn_bushels_charged=900.00, charge_test_weight_lb_per_bu=54.0,
    )

    fx.advance_clock(api, "2026-09-04T06:00:00Z")
    e100_now = get_success_data(api.get_tank(e100["id"], PROCESS_OPERATOR))
    blend = fx.executed_blend(
        api, neat["id"], denaturant["id"], e100["id"], e100_now["version"],
        blend_code="BL-1", neat_gallons=2565.00, denaturant_gallons=60.00,
        window_start="2026-09-04T08:00:00Z", window_end="2026-09-04T12:00:00Z",
    )

    track = fx.commission_track(api, loading_rate_cars_per_hour=20.0, is_active=True)
    fx.advance_clock(api, "2026-09-05T05:00:00Z")
    shipment = fx.documented_shipment(
        api, track["id"], e100["id"], track["version"], bol_number="BOL-7001",
        shipment_code="UT-7001", destination_terminal="Chicago Rail Terminal",
        railcar_count=1, gallons_per_railcar=2625.00,
        window_start="2026-09-05T06:00:00Z", window_end="2026-09-05T12:00:00Z",
        price_cents_per_gallon=181.50,
    )
    rows, _meta = validate_paginated(
        api.list_rin_batches(COMPLIANCE_OFFICER, {"separated_shipment_id": shipment["id"]})
    )
    return {
        "plant": plant,
        "batch": completed,
        "blend": blend,
        "shipment": shipment,
        "rin_batches": rows,
    }


class TestSettlementNeedsAPricedContract:
    """The delivery is ready, but the money cannot be computed without the futures leg."""

    def test_settling_against_an_unpriced_contract_is_refused(self, api):
        """No settlement figure and no inventory movement while the contract is UNPRICED.

        PRD 3.3: "Three preconditions guard it, in this order: the load's
        `grading_status` must be `GRADED`, otherwise `ERR_INVALID_DELIVERY_STATE`;
        the settling operator's `X-User-ID` must differ from the stored
        `graded_by_user_id`, otherwise `ERR_SEGREGATION_OF_DUTIES`; and the parent
        contract's `pricing_status` must be `PRICED`, otherwise
        `ERR_CONTRACT_NOT_PRICED`, since the futures leg is null while the
        contract is unpriced and the money cannot be computed."

        Design: Difficulty/cross_entity_state_dependency/settle_requires_contract_priced
        """
        scenario = _graded_load_on_an_unpriced_contract(api)

        validate_error(
            api.settle_delivery(scenario["delivery"]["id"], GRAIN_ACCOUNTANT),
            ApiErrorId.CONTRACT_NOT_PRICED,
            422,
        )

        delivery = get_success_data(api.get_delivery(scenario["delivery"]["id"], GRAIN_ACCOUNTANT))
        assert delivery["grading_status"] == "GRADED", delivery["grading_status"]
        assert_null(delivery["settlement_amount_cents"], "settlement_amount_cents")

        plant = get_success_data(api.get_plant(scenario["plant"]["id"], PLANT_MANAGER))
        assert_2dp(plant["corn_inventory_bushels"], 0.00, "corn_inventory_bushels")

    def test_pricing_the_contract_unlocks_the_same_settlement(self, api):
        """Once the futures leg is fixed the identical call settles at 413600 cents.

        PRD 3.3: "On success `grading_status` moves `GRADED → SETTLED`,
        `settlement_amount_cents` is computed, `settled_by_user_id` and
        `settled_at` are recorded, and the deepest cascade in the system fires."

        Design: Difficulty/cross_entity_state_dependency/settle_requires_contract_priced
        """
        scenario = _graded_load_on_an_unpriced_contract(api)
        get_success_data(
            api.price_contract(
                scenario["contract"]["id"], {"futures_price_cents_per_bushel": 458.0}, GRAIN_BUYER
            )
        )

        settled = validate_success(
            api.settle_delivery(scenario["delivery"]["id"], GRAIN_ACCOUNTANT), 200
        )
        assert settled["grading_status"] == "SETTLED", settled["grading_status"]
        assert_2dp(settled["net_price_cents_per_bushel"], 440.00, "net_price_cents_per_bushel")
        assert settled["settlement_amount_cents"] == 413600, settled["settlement_amount_cents"]

        contract = get_success_data(api.get_contract(scenario["contract"]["id"], GRAIN_BUYER))
        assert_2dp(contract["bushels_delivered"], 940.00, "bushels_delivered")
        plant = get_success_data(api.get_plant(scenario["plant"]["id"], PLANT_MANAGER))
        assert_2dp(plant["corn_inventory_bushels"], 940.00, "corn_inventory_bushels")


class TestDistillationNeedsTheDestinationTankInService:
    """A healthy fermenter still cannot run while its receiving tank is off spec."""

    def test_distilling_into_a_held_tank_is_refused(self, api):
        """The batch is FERMENTING, so the tank's service status is the only obstacle.

        PRD 3.4: "It requires that the batch be `FERMENTING` — a batch on health
        watch may not be distilled — that the destination tank be `IN_SERVICE`,
        and that the plant not be `SUSPENDED`."

        Design: Difficulty/cross_entity_state_dependency/distill_requires_destination_tank_in_service
        """
        scenario = _fermenting_batch_with_a_held_destination(api)
        assert_2dp(scenario["reading"]["reading_score"], 100.00, "reading_score")

        validate_error(
            api.distill_batch(scenario["batch"]["id"], PROCESS_OPERATOR),
            ApiErrorId.TANK_NOT_IN_SERVICE,
            422,
        )

        batch = get_success_data(api.get_batch(scenario["batch"]["id"], PROCESS_OPERATOR))
        assert batch["status"] == "FERMENTING", batch["status"]
        assert_null(batch["distillation_started_at"], "distillation_started_at")

    def test_releasing_the_tank_lets_the_same_batch_distil_at_the_base_yield(self, api):
        """With the tank back in service the frozen yield is the unpenalised 2.850.

        PRD 3.4: "Fourth, `effective_yield_gal_per_bushel` is a base yield of
        2.850 gallons per bushel plus the starch bonus less the health penalty
        less the intervention penalty, rounded half up to three decimals and then
        clamped into the range 2.550 through 3.050 gallons per bushel."

        Design: Difficulty/cross_entity_state_dependency/distill_requires_destination_tank_in_service
        """
        scenario = _fermenting_batch_with_a_held_destination(api)
        released = fx.release_tank(api, scenario["tank"]["id"])
        assert released["service_status"] == "IN_SERVICE", released["service_status"]

        distilling = validate_success(
            api.distill_batch(scenario["batch"]["id"], PROCESS_OPERATOR), 200
        )
        assert distilling["status"] == "DISTILLING", distilling["status"]
        assert_3dp(distilling["starch_bonus_gal_per_bushel"], 0.000, "starch_bonus_gal_per_bushel")
        assert_3dp(distilling["health_penalty_gal_per_bushel"], 0.000, "health_penalty_gal_per_bushel")
        assert_3dp(
            distilling["effective_yield_gal_per_bushel"], 2.850, "effective_yield_gal_per_bushel"
        )
        assert_instant_equals(
            distilling["distillation_started_at"], "2026-09-03T00:00:00Z", "distillation_started_at"
        )


class TestRetirementNeedsTheSeparatingTrainInvoiced:
    """A bill of lading separates the credits; only the invoice lets them be surrendered."""

    def test_retiring_credits_off_an_uninvoiced_train_is_refused(self, api):
        """The credits are SEPARATED, but the fuel has not been billed yet.

        PRD 3.8: "The batch must be at `SEPARATED`, otherwise
        `ERR_INVALID_RIN_STATE`, and the shipment that separated it must have
        reached `billing_status` `INVOICED`, otherwise
        `ERR_SHIPMENT_NOT_INVOICED` — credits may only be surrendered against fuel
        that has actually been billed."

        Design: Difficulty/cross_entity_state_dependency/rin_retire_requires_separating_shipment_invoiced
        """
        scenario = _separated_credit_batch_on_an_uninvoiced_train(api)
        assert_2dp(scenario["batch"]["ethanol_gallons_produced"], 2565.00, "ethanol_gallons_produced")
        assert_6dp(scenario["blend"]["denaturant_pct"], 0.022857, "denaturant_pct")
        assert_2dp(scenario["blend"]["output_gallons"], 2625.00, "output_gallons")
        assert_2dp(scenario["shipment"]["loaded_gallons"], 2625.00, "loaded_gallons")

        assert len(scenario["rin_batches"]) == 1, scenario["rin_batches"]
        credit = scenario["rin_batches"][0]
        assert credit["status"] == "SEPARATED", credit["status"]
        assert credit["rin_count"] == 2616, credit["rin_count"]

        validate_error(
            api.retire_rin_batch(
                credit["id"], {"retirement_reference": "RET-2026-Q3-001"}, COMPLIANCE_OFFICER
            ),
            ApiErrorId.SHIPMENT_NOT_INVOICED,
            422,
        )

        unchanged = get_success_data(api.get_rin_batch(credit["id"], COMPLIANCE_OFFICER))
        assert unchanged["status"] == "SEPARATED", unchanged["status"]
        assert_null(unchanged["retired_at"], "retired_at")

        plant = get_success_data(api.get_plant(scenario["plant"]["id"], PLANT_MANAGER))
        assert plant["rin_retired_count"] == 0, plant["rin_retired_count"]
        assert plant["rin_separated_count"] == 2616, plant["rin_separated_count"]

    def test_invoicing_the_train_unlocks_the_retirement(self, api):
        """Once billed, the same 2616 credits retire against the supplied reference.

        PRD 3.8: "The officer supplies a `retirement_reference` which is stored
        alongside `retired_at`."

        Design: Difficulty/cross_entity_state_dependency/rin_retire_requires_separating_shipment_invoiced
        """
        scenario = _separated_credit_batch_on_an_uninvoiced_train(api)
        credit = scenario["rin_batches"][0]

        invoiced = get_success_data(
            api.invoice_shipment(scenario["shipment"]["id"], LOGISTICS_COORDINATOR)
        )
        assert invoiced["billing_status"] == "INVOICED", invoiced["billing_status"]

        retired = validate_success(
            api.retire_rin_batch(
                credit["id"], {"retirement_reference": "RET-2026-Q3-001"}, COMPLIANCE_OFFICER
            ),
            200,
        )
        assert retired["status"] == "RETIRED", retired["status"]
        assert retired["retirement_reference"] == "RET-2026-Q3-001", retired["retirement_reference"]
        assert retired["retired_at"] is not None, "retired_at must be recorded"

        plant = get_success_data(api.get_plant(scenario["plant"]["id"], PLANT_MANAGER))
        assert plant["rin_retired_count"] == 2616, plant["rin_retired_count"]
        assert plant["rin_generated_count"] == 2616, plant["rin_generated_count"]
