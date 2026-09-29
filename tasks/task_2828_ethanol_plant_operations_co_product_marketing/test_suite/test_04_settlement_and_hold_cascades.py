"""
Cascades that reach three or more entities from a single call.

Settling one small load fills its contract, drops that contract out of the
coverage set, flips the procurement posture and cuts the grind cap; a mechanical
tank hold cancels a blend and a train and gives the train's railcars back to a
shared track.
"""

from test_helpers import fixtures as fx
from test_helpers import get_success_data, validate_success
from test_helpers.assertions import assert_2dp, assert_not_null, assert_null, assert_plant_posture
from test_helpers.test_users import (
    GRAIN_ACCOUNTANT,
    GRAIN_BUYER,
    LOGISTICS_COORDINATOR,
    PLANT_MANAGER,
    PROCESS_OPERATOR,
)


def _load_that_will_fill_its_contract(api):
    """
    A plant covered to 200440.00 bushels by two contracts, one of which is a
    940.00-bushel contract carrying a single graded 940.00-bushel load.
    """
    plant = fx.commission_plant(
        api,
        base_grind_cap_bushels=120000,
        coverage_floor_bushels=200000,
        baseline_ci_g_per_mj=60.0,
        rin_generation_enabled=True,
    )
    fx.advance_clock(api, "2026-09-01T00:00:00Z")
    big = fx.open_contract(
        api,
        supplier_name="Prairie Grain Terminal",
        delivery_month="2026-11",
        bushels_contracted=199500.00,
        basis_cents_per_bushel=-14.0,
    )
    small = fx.priced_contract(
        api,
        458.0,
        supplier_name="Cedar Ridge Elevator",
        delivery_month="2026-10",
        bushels_contracted=940.00,
        basis_cents_per_bushel=-18.0,
    )
    graded = fx.graded_load(
        api,
        small["id"],
        {"ticket_number": "TK-0940", "gross_weight_lbs": 78640, "tare_weight_lbs": 26000.00},
        {"aflatoxin_ppb": 2},
    )
    return {"plant": plant, "big": big, "small": small, "delivery": graded}


def _tank_farm_with_a_scheduled_blend_and_train(api):
    """
    T-301 is the destination of a scheduled blend and the source of a scheduled
    100-railcar train, so a hold on it has two dependents to destroy.
    """
    plant = fx.commission_plant(
        api,
        base_grind_cap_bushels=120000,
        coverage_floor_bushels=5000,
        baseline_ci_g_per_mj=60.0,
        rin_generation_enabled=True,
    )
    fx.advance_clock(api, "2026-09-01T00:00:00Z")
    neat = fx.commission_tank(api, "T-101", "ETHANOL_200_PROOF", 1000000.00, opening_gallons=300000.00)
    denaturant = fx.commission_tank(api, "T-201", "DENATURANT", 600000.00, opening_gallons=500000.00)
    e100 = fx.commission_tank(
        api, "T-301", "DENATURED_E100", 1000000.00,
        opening_gallons=400000.00, settling_buffer_minutes=120,
    )
    blend = fx.schedule_blend(
        api, neat["id"], denaturant["id"], e100["id"], e100["version"],
        blend_code="BL-7001", neat_gallons=100000.00, denaturant_gallons=2100.00,
        window_start="2026-09-04T08:00:00Z", window_end="2026-09-04T12:00:00Z",
    )
    track = fx.commission_track(api, loading_rate_cars_per_hour=20.0, is_active=True)
    shipment = fx.schedule_shipment(
        api, track["id"], e100["id"], track["version"],
        shipment_code="UT-7002", destination_terminal="Chicago Rail Terminal",
        railcar_count=100, gallons_per_railcar=2659.00,
        window_start="2026-09-05T06:00:00Z", window_end="2026-09-05T12:00:00Z",
        price_cents_per_gallon=181.50,
    )
    return {
        "plant": plant,
        "e100": e100,
        "blend": blend,
        "track": track,
        "shipment": shipment,
    }


class TestSettlementShrinksTheProductionCeiling:
    """One 940.00-bushel settlement fills a contract and costs the plant a quarter of its grind."""

    def test_settling_the_load_fills_the_contract_it_was_booked_against(self, api):
        """The load settles at the full gross price and completes its 940.00-bushel contract.

        PRD 3.3: "The contract's `bushels_delivered` is recomputed as the sum of
        `net_dry_bushels` over its own `SETTLED` deliveries — `REJECTED` and
        `GRADED` loads never count — and the contract's fill dimension advances
        accordingly: to `PARTIALLY_FILLED` when delivered bushels are now
        strictly greater than zero but still strictly less than
        `bushels_contracted`, and to `FILLED` when delivered bushels reach or
        exceed `bushels_contracted`; a contract already at `PARTIALLY_FILLED`
        advances to `FILLED` under the same condition."

        Design: Difficulty/transitive_cascade/settle_delivery_fills_contract_shrinks_coverage_flips_procurement_posture_and_grind_cap
        """
        scenario = _load_that_will_fill_its_contract(api)

        before = fx.read_plant(api, scenario["plant"]["id"])
        assert_2dp(before["open_contract_coverage_bushels"], 200440.00, "open_contract_coverage_bushels")
        assert_plant_posture(
            before, procurement_posture="ADEQUATE", daily_grind_cap_bushels=120000
        )

        settled = validate_success(
            api.settle_delivery(scenario["delivery"]["id"], GRAIN_ACCOUNTANT), 200
        )
        assert settled["grading_status"] == "SETTLED", settled["grading_status"]
        assert_2dp(settled["net_dry_bushels"], 940.00, "net_dry_bushels")
        assert_2dp(settled["net_price_cents_per_bushel"], 440.00, "net_price_cents_per_bushel")
        assert settled["settlement_amount_cents"] == 413600, settled["settlement_amount_cents"]

        contract = get_success_data(api.get_contract(scenario["small"]["id"], GRAIN_BUYER))
        assert contract["status"] == "FILLED", contract["status"]
        assert_2dp(contract["bushels_delivered"], 940.00, "bushels_delivered")

    def test_the_filled_contract_drops_out_of_coverage_and_cuts_the_grind_cap(self, api):
        """Coverage falls to 199500.00, procurement flips SHORT and the cap drops to 90000.

        PRD 3.3: "The chain has a counter-intuitive consequence worth
        internalising: because a `FILLED` contract drops out of the coverage set
        entirely, settling a small load that happens to complete a contract can
        **lower** total coverage below `coverage_floor_bushels`, flip
        `procurement_posture` from `ADEQUATE` to `SHORT`, and cut the plant's
        daily grind cap by a quarter — a settlement that shrinks the plant's
        production ceiling."

        Design: Difficulty/transitive_cascade/settle_delivery_fills_contract_shrinks_coverage_flips_procurement_posture_and_grind_cap
        """
        scenario = _load_that_will_fill_its_contract(api)
        fx.settle_delivery(api, scenario["delivery"]["id"])

        plant = fx.read_plant(api, scenario["plant"]["id"])
        assert_2dp(plant["open_contract_coverage_bushels"], 199500.00, "open_contract_coverage_bushels")
        assert_plant_posture(
            plant,
            compliance_posture="OPEN",
            procurement_posture="SHORT",
            daily_grind_cap_bushels=90000,
        )
        assert_2dp(plant["corn_inventory_bushels"], 940.00, "corn_inventory_bushels")

        big = get_success_data(api.get_contract(scenario["big"]["id"], GRAIN_BUYER))
        assert big["status"] == "OPEN", big["status"]


class TestMechanicalHoldCascade:
    """A broken pump destroys a blend and a train, and gives railcars back to the track."""

    def test_a_mechanical_hold_cancels_the_blend_and_the_train_and_frees_the_railcars(self, api):
        """One hold reaches a blend, a shipment and a shared track without touching the posture.

        PRD 3.5: "Every shipment whose source is this tank and whose
        `loading_status` is `SCHEDULED` moves `SCHEDULED → CANCELLED` with its
        `billing_status` forced to `VOIDED`, and that cancellation **drops** its
        `railcar_count` out of the track's `committed_railcars`, freeing
        aggregate spot capacity for a later shipment and incrementing the track's
        `version`."

        Design: Difficulty/transitive_cascade/mechanical_tank_hold_cancels_shipment_which_releases_track_railcars
        """
        scenario = _tank_farm_with_a_scheduled_blend_and_train(api)
        before_track = get_success_data(
            api.get_track(scenario["track"]["id"], LOGISTICS_COORDINATOR)
        )
        assert before_track["committed_railcars"] == 100, before_track["committed_railcars"]
        before_plant = fx.read_plant(api, scenario["plant"]["id"])

        held = fx.hold_tank(api, scenario["e100"]["id"], "MECHANICAL")
        assert held["service_status"] == "OUT_OF_SERVICE", held["service_status"]
        assert held["hold_reason"] == "MECHANICAL", held["hold_reason"]
        assert_2dp(held["current_gallons"], 400000.00, "current_gallons")

        blend = get_success_data(api.get_blend(scenario["blend"]["id"], PROCESS_OPERATOR))
        assert blend["status"] == "CANCELLED", blend["status"]
        assert_not_null(blend["cancelled_at"], "cancelled_at")

        shipment = get_success_data(
            api.get_shipment(scenario["shipment"]["id"], LOGISTICS_COORDINATOR)
        )
        assert shipment["loading_status"] == "CANCELLED", shipment["loading_status"]
        assert shipment["billing_status"] == "VOIDED", shipment["billing_status"]

        track = get_success_data(api.get_track(scenario["track"]["id"], LOGISTICS_COORDINATOR))
        assert track["committed_railcars"] == 0, track["committed_railcars"]

        plant = get_success_data(api.get_plant(scenario["plant"]["id"], PLANT_MANAGER))
        assert_plant_posture(plant, compliance_posture="OPEN")
        assert plant["daily_grind_cap_bushels"] == before_plant["daily_grind_cap_bushels"], (
            "a mechanical hold is not a permit violation and must not move the grind cap"
        )

    def test_releasing_the_tank_never_resurrects_what_the_hold_destroyed(self, api):
        """The tank comes back into service, but the blend and the train stay cancelled.

        PRD 3.5: "What release does **not** do is undo a mechanical hold's
        destruction: blends and shipments that were cancelled stay `CANCELLED`,
        their windows and railcars stay freed, and nothing is re-reserved."

        Design: Difficulty/transitive_cascade/mechanical_tank_hold_cancels_shipment_which_releases_track_railcars
        """
        scenario = _tank_farm_with_a_scheduled_blend_and_train(api)
        fx.hold_tank(api, scenario["e100"]["id"], "MECHANICAL")

        released = fx.release_tank(api, scenario["e100"]["id"])
        assert released["service_status"] == "IN_SERVICE", released["service_status"]
        assert_null(released["hold_reason"], "hold_reason")

        blend = get_success_data(api.get_blend(scenario["blend"]["id"], PROCESS_OPERATOR))
        assert blend["status"] == "CANCELLED", blend["status"]
        shipment = get_success_data(
            api.get_shipment(scenario["shipment"]["id"], LOGISTICS_COORDINATOR)
        )
        assert shipment["loading_status"] == "CANCELLED", shipment["loading_status"]
        track = get_success_data(api.get_track(scenario["track"]["id"], LOGISTICS_COORDINATOR))
        assert track["committed_railcars"] == 0, track["committed_railcars"]
