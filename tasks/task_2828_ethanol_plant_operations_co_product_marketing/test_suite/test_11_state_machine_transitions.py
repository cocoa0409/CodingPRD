"""
Initial states, admitted transitions, terminal lock-downs and their cascades.

Each test drives one row to the edge of its declared state machine and then
checks both the row that moved and the rows the move was allowed to touch.
"""

from test_helpers import fixtures as fx
from test_helpers import get_success_data, validate_error, validate_paginated, validate_success
from test_helpers.api_errors import ApiErrorId
from test_helpers.assertions import (
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
    USER_SCALE_OPERATOR,
)


def _plant_and_contract(api, clock="2026-09-01T00:00:00Z"):
    plant = fx.commission_plant(
        api, base_grind_cap_bushels=120000, coverage_floor_bushels=5000
    )
    if clock is not None:
        fx.advance_clock(api, clock)
    contract = fx.open_contract(
        api, supplier_name="Cedar Ridge Elevator", delivery_month="2026-10",
        bushels_contracted=200000.00, basis_cents_per_bushel=-18.0,
    )
    return {"plant": plant, "contract": contract}


class TestCornContractStateDimensions:
    """The fill dimension and the pricing dimension move independently."""

    def test_a_new_contract_occupies_the_initial_state_of_both_dimensions(self, api):
        """Opening a contract also lifts the plant's coverage in the same breath.

        PRD 3.2: "Because the contract's unfilled remainder immediately joins the
        plant's coverage set, opening a contract re-derives
        `open_contract_coverage_bushels`, then `procurement_posture`, then
        `daily_grind_cap_bushels` — which is how a single large purchase can lift
        the plant out of `SHORT` and restore a quarter of its grind capacity."

        Design: Corner/state_machines/contract_starts_in_open_and_unpriced
        """
        plant = fx.commission_plant(
            api, base_grind_cap_bushels=120000, coverage_floor_bushels=5000
        )
        fx.advance_clock(api, "2026-09-01T00:00:00Z")

        contract = validate_success(
            api.create_contract(
                {
                    "supplier_name": "Cedar Ridge Elevator",
                    "delivery_month": "2026-10",
                    "bushels_contracted": 200000.00,
                    "basis_cents_per_bushel": -18.0,
                },
                GRAIN_BUYER,
            ),
            201,
        )

        assert contract["status"] == "OPEN", contract["status"]
        assert contract["pricing_status"] == "UNPRICED", contract["pricing_status"]
        assert_2dp(contract["bushels_delivered"], 0.00, "bushels_delivered")
        assert_null(contract["priced_at"], "priced_at")

        after = get_success_data(api.get_plant(plant["id"], PLANT_MANAGER))
        assert_2dp(
            after["open_contract_coverage_bushels"], 200000.00, "open_contract_coverage_bushels"
        )
        assert_plant_posture(after, procurement_posture="ADEQUATE", daily_grind_cap_bushels=120000)

    def test_fixing_the_futures_leg_moves_only_the_pricing_dimension(self, api):
        """The fill dimension stays OPEN while the pricing dimension advances once.

        PRD 3.2: "On success the futures price is stored, `pricing_status` moves
        `UNPRICED → PRICED`, `priced_at` records the logical clock instant, and the
        contract's **gross price** — the futures leg plus the basis, in cents per
        bushel — becomes available to the settlement arithmetic of §3.3."

        Design: Corner/state_machines/contract_price_moves_pricing_status_to_priced_and_stamps_priced_at
        """
        scenario = _plant_and_contract(api, clock=None)
        fx.advance_clock(api, "2026-09-02T00:00:00Z")

        priced = validate_success(
            api.price_contract(
                scenario["contract"]["id"], {"futures_price_cents_per_bushel": 458.0}, GRAIN_BUYER
            ),
            200,
        )

        assert priced["pricing_status"] == "PRICED", priced["pricing_status"]
        assert priced["status"] == "OPEN", priced["status"]
        assert priced["futures_price_cents_per_bushel"] == 458.0, priced[
            "futures_price_cents_per_bushel"
        ]
        assert_instant_equals(priced["priced_at"], "2026-09-02T00:00:00Z", "priced_at")
        assert priced["version"] == 2, priced["version"]

    def test_pricing_is_one_shot_and_the_replay_never_overwrites_the_stored_price(self, api):
        """A second price call gets the specific already-priced code, not the generic one.

        PRD 3.2: "and its pricing dimension must still be `UNPRICED`; a second
        attempt on an already-priced contract is refused with
        `ERR_CONTRACT_ALREADY_PRICED`."

        Design: Corner/state_machines/contract_second_price_call_rejected_as_already_priced
        """
        scenario = _plant_and_contract(api, clock=None)
        get_success_data(
            api.price_contract(
                scenario["contract"]["id"], {"futures_price_cents_per_bushel": 458.0}, GRAIN_BUYER
            )
        )

        validate_error(
            api.price_contract(
                scenario["contract"]["id"], {"futures_price_cents_per_bushel": 470.0}, GRAIN_BUYER
            ),
            ApiErrorId.CONTRACT_ALREADY_PRICED,
            409,
        )

        after = get_success_data(api.get_contract(scenario["contract"]["id"], GRAIN_BUYER))
        assert after["futures_price_cents_per_bushel"] == 458.0, after[
            "futures_price_cents_per_bushel"
        ]
        assert after["version"] == 2, after["version"]


def _pending_load_on_a_priced_contract(api):
    """TK-0001 booked and awaiting a grade against a PRICED contract."""
    plant = fx.commission_plant(
        api, base_grind_cap_bushels=120000, coverage_floor_bushels=5000
    )
    contract = fx.priced_contract(api, 458.0, supplier_name="Cedar Ridge Elevator")
    delivery = fx.book_delivery(api, contract["id"], ticket_number="TK-0001")
    return {"plant": plant, "contract": contract, "delivery": delivery}


class TestGradingAutoRejection:
    """A rejection is a successful grade, not a failed request."""

    def test_aflatoxin_over_the_limit_rejects_the_load_on_a_two_hundred_response(self, api):
        """Twenty-five parts per billion rejects the load and prices nothing.

        PRD 3.3: "A load whose `aflatoxin_ppb` exceeds 20 parts per billion, or
        whose `moisture_pct` exceeds 20.00 percent, is auto-rejected:
        `grading_status` moves `PENDING_GRADE → REJECTED`, `rejection_reason` is
        set, and `net_price_cents_per_bushel` and `settlement_amount_cents` are
        left null because a rejected load is never priced and contributes nothing
        to `bushels_delivered`."

        PRD 3.3: "Crucially, auto-rejection is a **successful** response, not an
        error: the load was legitimately graded and the grade happens to be a
        rejection."

        Design: Corner/state_machines/grade_auto_rejects_the_load_when_aflatoxin_is_over_the_limit
        """
        scenario = _pending_load_on_a_priced_contract(api)

        graded = validate_success(
            api.grade_delivery(
                scenario["delivery"]["id"],
                {
                    "moisture_pct": 22.00,
                    "test_weight_lb_per_bu": 54.0,
                    "foreign_material_pct": 3.00,
                    "damaged_kernels_pct": 5.00,
                    "aflatoxin_ppb": 25,
                },
                SCALE_OPERATOR,
            ),
            200,
        )

        assert graded["grading_status"] == "REJECTED", graded["grading_status"]
        assert_null(graded["net_price_cents_per_bushel"], "net_price_cents_per_bushel")
        assert_null(graded["settlement_amount_cents"], "settlement_amount_cents")
        assert graded["graded_by_user_id"] == USER_SCALE_OPERATOR, graded["graded_by_user_id"]

        contract = get_success_data(api.get_contract(scenario["contract"]["id"], GRAIN_BUYER))
        assert_2dp(contract["bushels_delivered"], 0.00, "bushels_delivered")
        plant = get_success_data(api.get_plant(scenario["plant"]["id"], PLANT_MANAGER))
        assert_2dp(plant["corn_inventory_bushels"], 0.00, "corn_inventory_bushels")

    def test_the_aflatoxin_reason_wins_over_the_moisture_reason_on_a_load_failing_both(self, api):
        """Both limits are breached, and the aflatoxin test is the one evaluated first.

        PRD 3.3: "The aflatoxin test is evaluated **first**, so a load breaching
        both limits reports `AFLATOXIN_OVER_LIMIT` rather than
        `MOISTURE_OVER_LIMIT`."

        Design: Corner/state_machines/grade_auto_rejects_the_load_when_aflatoxin_is_over_the_limit
        """
        scenario = _pending_load_on_a_priced_contract(api)

        graded = get_success_data(
            api.grade_delivery(
                scenario["delivery"]["id"],
                {
                    "moisture_pct": 22.00,
                    "test_weight_lb_per_bu": 54.0,
                    "foreign_material_pct": 3.00,
                    "damaged_kernels_pct": 5.00,
                    "aflatoxin_ppb": 25,
                },
                SCALE_OPERATOR,
            )
        )

        assert graded["rejection_reason"] == "AFLATOXIN_OVER_LIMIT", graded["rejection_reason"]
        assert graded["rejection_reason"] != "MOISTURE_OVER_LIMIT"


class TestRejectedDeliveryIsTerminal:
    """A rejected load accepts neither a settlement nor a second grade."""

    def test_settling_a_rejected_load_is_refused_and_no_corn_arrives(self, api):
        """REJECTED is terminal on the grading dimension, so settlement is locked out.

        PRD 3.3: "Grading is the load's single moment of quality truth, and it is
        also where the discount schedule is computed. A `ScaleOperator` — which
        must still be a load at `PENDING_GRADE`, since a `REJECTED` or already
        `SETTLED` load accepts neither grading nor settlement and both are refused
        with `ERR_INVALID_DELIVERY_STATE` — records five readings"

        Design: Corner/state_machines/settle_on_a_rejected_delivery_is_locked_out
        """
        scenario = _pending_load_on_a_priced_contract(api)
        rejected = get_success_data(
            api.grade_delivery(
                scenario["delivery"]["id"],
                {
                    "moisture_pct": 15.00,
                    "test_weight_lb_per_bu": 54.0,
                    "foreign_material_pct": 3.00,
                    "damaged_kernels_pct": 5.00,
                    "aflatoxin_ppb": 25,
                },
                SCALE_OPERATOR,
            )
        )
        assert rejected["grading_status"] == "REJECTED", rejected["grading_status"]

        validate_error(
            api.settle_delivery(scenario["delivery"]["id"], GRAIN_ACCOUNTANT),
            ApiErrorId.INVALID_DELIVERY_STATE,
            409,
        )

        after = get_success_data(api.get_delivery(scenario["delivery"]["id"], GRAIN_ACCOUNTANT))
        assert after["grading_status"] == "REJECTED", after["grading_status"]
        assert_null(after["settled_at"], "settled_at")
        plant = get_success_data(api.get_plant(scenario["plant"]["id"], PLANT_MANAGER))
        assert_2dp(plant["corn_inventory_bushels"], 0.00, "corn_inventory_bushels")


def _charged_batch(api, clock="2026-09-01T00:00:00Z"):
    """940.00 settled bushels on hand, T-101 empty, FB-1 charged with 900.00."""
    plant = fx.commission_plant(
        api, base_grind_cap_bushels=120000, coverage_floor_bushels=5000
    )
    if clock is not None:
        fx.advance_clock(api, clock)
    tank = fx.commission_tank(
        api, "T-101", "ETHANOL_200_PROOF", 1000000.00, opening_gallons=0.00
    )
    contract = fx.priced_contract(api, 458.0, supplier_name="Cedar Ridge Elevator")
    fx.settled_load(api, contract["id"], {"ticket_number": "TK-0001"})
    batch = fx.charge_batch(
        api,
        tank["id"],
        batch_code="FB-1",
        corn_bushels_charged=900.00,
        charge_test_weight_lb_per_bu=54.0,
    )
    return {"plant": plant, "tank": tank, "contract": contract, "batch": batch}


class TestDumpForfeitsTheCharge:
    """CHARGED to DUMPED writes the corn off without producing anything."""

    def test_dumping_a_charged_batch_records_the_reason_and_produces_no_product(self, api):
        """The batch reaches the terminal dumped state and the tank stays empty.

        PRD 3.4: "The operator supplies a free-text `dump_reason`; the batch moves
        to `DUMPED`, `dumped_at` and the reason are recorded, and the outcome is
        deliberately unforgiving: the charged corn stays consumed and
        `corn_inventory_bushels` is not restored, no ethanol, no distillers
        grains, no corn oil and no renewable credits are created."

        Design: Corner/state_machines/dump_from_charged_forfeits_the_corn_without_producing_ethanol
        """
        scenario = _charged_batch(api)

        dumped = validate_success(
            api.dump_batch(
                scenario["batch"]["id"],
                {"dump_reason": "Stuck fermentation after chiller failure"},
                PROCESS_OPERATOR,
            ),
            200,
        )

        assert dumped["status"] == "DUMPED", dumped["status"]
        assert_instant_equals(dumped["dumped_at"], "2026-09-01T00:00:00Z", "dumped_at")
        assert dumped["dump_reason"] == "Stuck fermentation after chiller failure", (
            dumped["dump_reason"]
        )

        tank = get_success_data(api.get_tank(scenario["tank"]["id"], PROCESS_OPERATOR))
        assert_2dp(tank["current_gallons"], 0.00, "current_gallons")
        assert_2dp(tank["available_gallons"], 1000000.00, "available_gallons")

    def test_the_forfeited_charge_stays_consumed_and_mints_no_credits(self, api):
        """Inventory keeps subtracting a dumped batch's charge, so 40.00 bushels remain.

        PRD 3.4: "`corn_inventory_bushels` is the sum of `net_dry_bushels` over
        deliveries whose `grading_status` is `SETTLED`, less the sum of
        `corn_bushels_charged` over batches whose `status` is any of `CHARGED`,
        `FERMENTING`, `HEALTH_WATCH`, `DISTILLING`, `COMPLETED` or `DUMPED` —
        every state a batch can occupy, dumped included."

        PRD 3.7: "A dumped batch mints nothing at all."

        Design: Corner/state_machines/dump_from_charged_forfeits_the_corn_without_producing_ethanol
        """
        scenario = _charged_batch(api)
        get_success_data(
            api.dump_batch(
                scenario["batch"]["id"],
                {"dump_reason": "Stuck fermentation after chiller failure"},
                PROCESS_OPERATOR,
            )
        )

        plant = get_success_data(api.get_plant(scenario["plant"]["id"], PLANT_MANAGER))
        assert_2dp(plant["corn_inventory_bushels"], 40.00, "corn_inventory_bushels")
        assert_3dp(plant["ddgs_inventory_tons"], 0.000, "ddgs_inventory_tons")
        assert_2dp(plant["corn_oil_inventory_lbs"], 0.00, "corn_oil_inventory_lbs")
        assert plant["rin_generated_count"] == 0, plant["rin_generated_count"]

        rows, meta = validate_paginated(api.list_rin_batches(PLANT_MANAGER))
        assert rows == [], f"a dumped batch must mint no credit batch, got {rows!r}"
        assert meta["total_count"] == 0, meta["total_count"]


class TestCompletionRequiresDistillation:
    """COMPLETED is reachable only from DISTILLING."""

    def test_completing_a_fermenting_batch_is_refused_and_moves_no_product(self, api):
        """Skipping the still is an invalid transition, not a shortcut.

        PRD 3.4: "Completing the batch moves it `DISTILLING → COMPLETED` and is
        where physical product appears. It requires the batch to be `DISTILLING`,
        the destination tank to be `IN_SERVICE`, and that tank's
        `available_gallons` to be at least the ethanol volume about to land"

        PRD 3.4: "Appending a reading to a `COMPLETED` or `DUMPED` batch is
        refused with `ERR_INVALID_BATCH_STATE`, as is any action a batch's current
        state does not admit."

        Design: Corner/state_machines/complete_before_distill_rejected_as_invalid_batch_state
        """
        scenario = _charged_batch(api, clock=None)
        fx.append_health_reading(
            api,
            scenario["batch"]["id"],
            hours_elapsed=12.0,
            lactic_acid_ppm=400,
            acetic_acid_ppm=150,
            temperature_c=32.0,
        )
        fermenting = get_success_data(api.get_batch(scenario["batch"]["id"], PROCESS_OPERATOR))
        assert fermenting["status"] == "FERMENTING", fermenting["status"]

        validate_error(
            api.complete_batch(scenario["batch"]["id"], PROCESS_OPERATOR),
            ApiErrorId.INVALID_BATCH_STATE,
            409,
        )

        after = get_success_data(api.get_batch(scenario["batch"]["id"], PROCESS_OPERATOR))
        assert after["status"] == "FERMENTING", after["status"]
        assert_null(after["completed_at"], "completed_at")

        tank = get_success_data(api.get_tank(scenario["tank"]["id"], PROCESS_OPERATOR))
        assert_2dp(tank["current_gallons"], 0.00, "current_gallons")
        rows, _ = validate_paginated(api.list_rin_batches(PLANT_MANAGER))
        assert rows == [], f"no credit batch may exist before completion, got {rows!r}"


class TestTankHoldForksOnReason:
    """The hold reason picks the target state, and one release endpoint undoes both."""

    def test_a_mechanical_hold_sends_the_tank_out_of_service_and_release_brings_it_back(self, api):
        """Hold then release walks the tank IN_SERVICE to OUT_OF_SERVICE and back.

        PRD 3.5: "A **`MECHANICAL`** hold is an equipment event. `service_status`
        moves `IN_SERVICE → OUT_OF_SERVICE`."

        PRD 3.5: "`hold_reason` and `held_at` are cleared, `service_status`
        returns to `IN_SERVICE` from either state"

        Design: Corner/state_machines/mechanical_hold_takes_the_tank_out_of_service_and_release_restores_it
        """
        fx.commission_plant(api, base_grind_cap_bushels=120000, coverage_floor_bushels=5000)
        tank = fx.commission_tank(
            api, "T-101", "ETHANOL_200_PROOF", 1000000.00, opening_gallons=0.00
        )
        fx.advance_clock(api, "2026-09-03T00:00:00Z", PROCESS_OPERATOR)

        held = validate_success(
            api.hold_tank(tank["id"], {"hold_reason": "MECHANICAL"}, PROCESS_OPERATOR), 200
        )
        assert held["service_status"] == "OUT_OF_SERVICE", held["service_status"]
        assert held["hold_reason"] == "MECHANICAL", held["hold_reason"]
        assert_instant_equals(held["held_at"], "2026-09-03T00:00:00Z", "held_at")
        assert held["version"] == 2, held["version"]

        released = validate_success(api.release_tank(tank["id"], PROCESS_OPERATOR), 200)
        assert released["service_status"] == "IN_SERVICE", released["service_status"]
        assert_null(released["hold_reason"], "hold_reason")
        assert_null(released["held_at"], "held_at")
        assert released["version"] == 3, released["version"]

    def test_a_mechanical_hold_leaves_the_compliance_posture_open(self, api):
        """A broken pump is not a permit violation, so the posture never moves.

        PRD 3.5: "Deliberately, a mechanical hold does **not** change
        `compliance_posture` at all: a broken pump is not a permit violation."

        Design: Corner/state_machines/mechanical_hold_takes_the_tank_out_of_service_and_release_restores_it
        """
        plant = fx.commission_plant(
            api, base_grind_cap_bushels=120000, coverage_floor_bushels=5000
        )
        tank = fx.commission_tank(
            api, "T-101", "ETHANOL_200_PROOF", 1000000.00, opening_gallons=0.00
        )
        fx.advance_clock(api, "2026-09-03T00:00:00Z", PROCESS_OPERATOR)
        assert_plant_posture(
            get_success_data(api.get_plant(plant["id"], PLANT_MANAGER)),
            compliance_posture="OPEN",
        )

        fx.hold_tank(api, tank["id"], "MECHANICAL")
        assert_plant_posture(
            get_success_data(api.get_plant(plant["id"], PLANT_MANAGER)),
            compliance_posture="OPEN",
        )

        fx.release_tank(api, tank["id"])
        assert_plant_posture(
            get_success_data(api.get_plant(plant["id"], PLANT_MANAGER)),
            compliance_posture="OPEN",
        )


def _scheduled_train_on_a_finished_tank(api):
    """SH-1 scheduled for 100 railcars out of T-301, which opens with 400000.00."""
    plant = fx.commission_plant(
        api, base_grind_cap_bushels=120000, coverage_floor_bushels=5000
    )
    fx.advance_clock(api, "2026-09-03T00:00:00Z")
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


class TestOffSpecHoldBlocksAndReleaseReschedules:
    """A quality hold pauses the train without giving back its railcars."""

    def test_the_off_spec_hold_blocks_the_train_and_keeps_its_railcars_committed(self, api):
        """SCHEDULED becomes BLOCKED, the paperwork stands still and the spots stay taken.

        PRD 3.5: "Every shipment whose source is this tank and whose
        `loading_status` is `SCHEDULED` moves `SCHEDULED → BLOCKED`, and each
        blocked shipment's `railcar_count` **remains** inside its track's
        `committed_railcars`, because the window is still reserved and the train
        is merely paused. The shipment's `billing_status` is untouched."

        Design: Corner/state_machines/off_spec_hold_blocks_the_shipment_and_release_reschedules_it
        """
        scenario = _scheduled_train_on_a_finished_tank(api)
        assert_2dp(scenario["shipment"]["planned_gallons"], 265900.00, "planned_gallons")

        held = get_success_data(
            api.hold_tank(scenario["tank"]["id"], {"hold_reason": "OFF_SPEC"}, PROCESS_OPERATOR)
        )
        assert held["service_status"] == "ON_HOLD", held["service_status"]

        shipment = get_success_data(
            api.get_shipment(scenario["shipment"]["id"], LOGISTICS_COORDINATOR)
        )
        assert shipment["loading_status"] == "BLOCKED", shipment["loading_status"]
        assert shipment["billing_status"] == "PENDING_BOL", shipment["billing_status"]

        track = get_success_data(api.get_track(scenario["track"]["id"], LOGISTICS_COORDINATOR))
        assert track["committed_railcars"] == 100, track["committed_railcars"]

    def test_the_off_spec_hold_restricts_the_plant_and_the_release_reschedules_the_train(self, api):
        """An off-spec hold is a compliance event, and releasing it reverses both effects.

        PRD 2.8: "each off-spec tank hold raises it to at least `RESTRICTED`"

        PRD 3.5: "every shipment on this source tank whose `loading_status` is
        `BLOCKED` moves `BLOCKED → SCHEDULED` with its own `version` incremented,
        and `compliance_posture` and `daily_grind_cap_bushels` are re-derived."

        Design: Corner/state_machines/off_spec_hold_blocks_the_shipment_and_release_reschedules_it
        """
        scenario = _scheduled_train_on_a_finished_tank(api)
        fx.hold_tank(api, scenario["tank"]["id"], "OFF_SPEC")

        assert_plant_posture(
            get_success_data(api.get_plant(scenario["plant"]["id"], PLANT_MANAGER)),
            compliance_posture="RESTRICTED",
        )

        released = fx.release_tank(api, scenario["tank"]["id"])
        assert released["service_status"] == "IN_SERVICE", released["service_status"]

        shipment = get_success_data(
            api.get_shipment(scenario["shipment"]["id"], LOGISTICS_COORDINATOR)
        )
        assert shipment["loading_status"] == "SCHEDULED", shipment["loading_status"]
        assert_plant_posture(
            get_success_data(api.get_plant(scenario["plant"]["id"], PLANT_MANAGER)),
            compliance_posture="OPEN",
        )


def _scheduled_blend_on_three_tanks(api):
    """BL-1 scheduled out of T-101 and T-201 into an empty T-301."""
    plant = fx.commission_plant(
        api, base_grind_cap_bushels=120000, coverage_floor_bushels=5000
    )
    fx.advance_clock(api, "2026-09-03T00:00:00Z")
    neat = fx.commission_tank(
        api, "T-101", "ETHANOL_200_PROOF", 1000000.00, opening_gallons=500000.00
    )
    denaturant = fx.commission_tank(
        api, "T-201", "DENATURANT", 1000000.00, opening_gallons=500000.00
    )
    destination = fx.commission_tank(
        api, "T-301", "DENATURED_E100", 1000000.00, opening_gallons=0.00
    )
    blend = fx.schedule_blend(
        api,
        neat["id"],
        denaturant["id"],
        destination["id"],
        destination["version"],
        blend_code="BL-1",
        neat_gallons=2565.00,
        denaturant_gallons=60.00,
        window_start="2026-09-04T06:00:00Z",
        window_end="2026-09-04T10:00:00Z",
    )
    assert blend["status"] == "SCHEDULED", blend["status"]
    return {
        "plant": plant,
        "neat": neat,
        "denaturant": denaturant,
        "destination": destination,
        "blend": blend,
    }


class TestMechanicalHoldCancelsScheduledBlends:
    """The cascade fires from any of the blend's three tank roles."""

    def test_holding_the_neat_source_cancels_the_blend_and_moves_no_liquid(self, api):
        """The blend is cancelled where it stood, so all three balances are untouched.

        PRD 3.5: "Every blend whose `status` is `SCHEDULED` and which references
        this tank in **any** of its three roles — as `neat_source_tank_id`, as
        `denaturant_source_tank_id` or as `destination_tank_id` — moves `SCHEDULED
        → CANCELLED`, recording `cancelled_at`, moving no liquid and changing no
        tank balance"

        Design: Corner/state_machines/mechanical_hold_cancels_the_scheduled_blend
        """
        scenario = _scheduled_blend_on_three_tanks(api)

        held = get_success_data(
            api.hold_tank(scenario["neat"]["id"], {"hold_reason": "MECHANICAL"}, PROCESS_OPERATOR)
        )
        assert held["service_status"] == "OUT_OF_SERVICE", held["service_status"]

        blend = get_success_data(api.get_blend(scenario["blend"]["id"], PROCESS_OPERATOR))
        assert blend["status"] == "CANCELLED", blend["status"]
        assert_instant_equals(blend["cancelled_at"], "2026-09-03T00:00:00Z", "cancelled_at")
        assert_null(blend["output_gallons"], "output_gallons")
        assert_null(blend["denaturant_pct"], "denaturant_pct")

        for key, expected in (
            ("neat", 500000.00),
            ("denaturant", 500000.00),
            ("destination", 0.00),
        ):
            tank = get_success_data(api.get_tank(scenario[key]["id"], PROCESS_OPERATOR))
            assert_2dp(tank["current_gallons"], expected, f"{key} current_gallons")

    def test_the_cancelled_blend_can_no_longer_be_executed(self, api):
        """CANCELLED is terminal, so the pump-over is refused on state alone.

        PRD 3.5: "Executing a blend requires the blend to be `SCHEDULED` — an
        `EXECUTED` or `CANCELLED` blend is refused with `ERR_INVALID_BLEND_STATE`
        — and takes no request body."

        Design: Corner/state_machines/mechanical_hold_cancels_the_scheduled_blend
        """
        scenario = _scheduled_blend_on_three_tanks(api)
        fx.hold_tank(api, scenario["neat"]["id"], "MECHANICAL")

        validate_error(
            api.execute_blend(scenario["blend"]["id"], PROCESS_OPERATOR),
            ApiErrorId.INVALID_BLEND_STATE,
            409,
        )

        blend = get_success_data(api.get_blend(scenario["blend"]["id"], PROCESS_OPERATOR))
        assert blend["status"] == "CANCELLED", blend["status"]
        assert_null(blend["executed_at"], "executed_at")


def _declined_quote(api):
    """SL-1, a FLAT quote for 5.000 tons of dry distillers grains, declined."""
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
        quote_expires_at="2026-09-10T00:00:00Z",
    )
    declined = get_success_data(api.respond_to_sale(sale["id"], {"decision": "DECLINE"}, GRAIN_BUYER))
    assert declined["status"] == "DECLINED", declined["status"]
    assert_instant_equals(declined["responded_at"], "2026-09-03T00:00:00Z", "responded_at")
    return {"plant": plant, "sale": declined}


class TestDeclinedSaleIsTerminal:
    """A declined quote is dead, and nothing is ever computed for it."""

    def test_shipping_a_declined_quote_is_refused_and_relieves_no_inventory(self, api):
        """The shipping gate reads the sale's state before it reads the cupboard.

        PRD 3.7: "Shipping an accepted sale is what actually relieves the plant's
        co-product inventory, and it is a `LogisticsCoordinator`'s action rather
        than the buyer's. The sale must be `ACCEPTED`, otherwise
        `ERR_INVALID_SALE_STATE`."

        PRD 3.7: "A `DECLINE` moves the sale to `DECLINED`, records `responded_at`
        and leaves every money field null forever; nothing is ever computed for a
        declined quote."

        Design: Corner/state_machines/declined_sale_cannot_be_shipped
        """
        scenario = _declined_quote(api)

        validate_error(
            api.ship_sale(scenario["sale"]["id"], LOGISTICS_COORDINATOR),
            ApiErrorId.INVALID_SALE_STATE,
            409,
        )

        sale = get_success_data(api.get_sale(scenario["sale"]["id"], GRAIN_BUYER))
        assert sale["status"] == "DECLINED", sale["status"]
        assert_null(sale["shipped_at"], "shipped_at")
        assert_null(sale["settlement_price"], "settlement_price")
        assert_null(sale["invoice_amount_cents"], "invoice_amount_cents")

        plant = get_success_data(api.get_plant(scenario["plant"]["id"], PLANT_MANAGER))
        assert_3dp(plant["ddgs_inventory_tons"], 0.000, "ddgs_inventory_tons")

    def test_a_second_response_to_a_declined_quote_is_refused(self, api):
        """The buyer cannot change their mind, because responding requires QUOTED.

        PRD 3.7: "Responding to a quote carries a single `decision` of either
        `ACCEPT` or `DECLINE`, and the sale must still be at `QUOTED`, otherwise
        `ERR_INVALID_SALE_STATE`."

        Design: Corner/state_machines/declined_sale_cannot_be_shipped
        """
        scenario = _declined_quote(api)

        validate_error(
            api.respond_to_sale(scenario["sale"]["id"], {"decision": "ACCEPT"}, GRAIN_BUYER),
            ApiErrorId.INVALID_SALE_STATE,
            409,
        )

        sale = get_success_data(api.get_sale(scenario["sale"]["id"], GRAIN_BUYER))
        assert sale["status"] == "DECLINED", sale["status"]
        assert_null(sale["settlement_price"], "settlement_price")
        assert_null(sale["invoice_amount_cents"], "invoice_amount_cents")


class TestResolveDeviationRequiresAnExceedance:
    """There is nothing to sign off on a condition that never breached."""

    def test_resolving_a_compliant_condition_is_refused_and_stores_no_note(self, api):
        """A fresh condition opens compliant with an empty window and no deviation.

        PRD 3.9: "A condition opens at `status` `COMPLIANT` with
        `readings_in_window` at 0, `rolling_average_value` null and
        `exceedance_count` at 0."

        PRD 3.9: "The condition must actually be in `EXCEEDANCE`, otherwise
        `ERR_CONDITION_NOT_IN_EXCEEDANCE`, and the current `rolling_average_value`
        must be not null and at or below `limit_value`, so an officer cannot sign
        off a deviation while the plant is still over the line."

        Design: Corner/state_machines/resolve_deviation_on_a_compliant_condition_rejected
        """
        plant = fx.commission_plant(
            api, base_grind_cap_bushels=120000, coverage_floor_bushels=5000
        )
        condition = fx.register_condition(
            api,
            condition_code="VOC-1",
            permit_type="AIR_EMISSIONS",
            parameter_name="VOC",
            limit_value=12.500,
            unit="lb/hr",
            averaging_period_hours=24,
            severity="MINOR",
        )
        assert condition["status"] == "COMPLIANT", condition["status"]
        assert_null(condition["rolling_average_value"], "rolling_average_value")
        assert condition["readings_in_window"] == 0, condition["readings_in_window"]
        assert condition["exceedance_count"] == 0, condition["exceedance_count"]

        validate_error(
            api.resolve_deviation(
                condition["id"], {"resolution_note": "Scrubber tuned"}, COMPLIANCE_OFFICER
            ),
            ApiErrorId.CONDITION_NOT_IN_EXCEEDANCE,
            409,
        )

        after = get_success_data(api.get_permit_condition(condition["id"], COMPLIANCE_OFFICER))
        assert after["status"] == "COMPLIANT", after["status"]
        assert_null(after["resolution_note"], "resolution_note")
        assert after["version"] == 1, after["version"]
        assert_plant_posture(
            get_success_data(api.get_plant(plant["id"], PLANT_MANAGER)),
            compliance_posture="OPEN",
        )


def _short_ethanol_position(api):
    """HP-1: ten ethanol lots sold at 182.00 against a posted mark of 178.00."""
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
    position = fx.open_hedge(
        api,
        position_code="HP-1",
        commodity="ETHANOL",
        direction="SHORT",
        contract_month="2026-10",
        contracts=10,
        entry_price=182.00,
    )
    return {"plant": plant, "position": position}


class TestHedgePositionCloseWalk:
    """Realized accumulates while unrealized shrinks with the open lots."""

    def test_a_new_short_stamps_the_ethanol_unit_size_and_opens_flat(self, api):
        """Ten lots of 29000 gallons open with both profit-and-loss figures at zero.

        PRD 3.9: "The system stamps the contract `unit_size` from the commodity —
        5000 bushels for corn, 29000 gallons for ethanol, 10000 million British
        thermal units for natural gas — and opens the position at `status` `OPEN`
        with `contracts_closed` at 0, `contracts_open` equal to `contracts`, both
        `realized_pnl_cents` and `unrealized_pnl_cents` at 0, and `opened_at`
        recorded."

        Design: Corner/state_machines/hedge_partial_close_then_full_close_walks_the_position_to_closed
        """
        position = _short_ethanol_position(api)["position"]

        assert position["unit_size"] == 29000, position["unit_size"]
        assert position["status"] == "OPEN", position["status"]
        assert position["contracts_open"] == 10, position["contracts_open"]
        assert position["contracts_closed"] == 0, position["contracts_closed"]
        assert_integer_cents(position["realized_pnl_cents"], "realized_pnl_cents")
        assert position["realized_pnl_cents"] == 0, position["realized_pnl_cents"]
        assert position["unrealized_pnl_cents"] == 0, position["unrealized_pnl_cents"]
        assert_not_null(position["opened_at"], "opened_at")

    def test_closing_five_of_ten_lots_realizes_half_and_reprices_the_remainder(self, api):
        """The short banks 797500 cents and still carries 580000 unrealized on five lots.

        PRD 3.9: "The realized slice from a close is that sign multiplied by the
        difference of `exit_price` less `entry_price`, multiplied by the
        `unit_size` and by the `contracts_to_close`, rounded half up to a whole
        number of cents, and it **accumulates into** `realized_pnl_cents` rather
        than replacing it"

        PRD 3.9: "Closing strictly fewer contracts than are open moves the
        position to `PARTIALLY_CLOSED` — from `OPEN` on the first partial close
        and from `PARTIALLY_CLOSED` to itself on each subsequent one."

        Design: Corner/state_machines/hedge_partial_close_then_full_close_walks_the_position_to_closed
        """
        scenario = _short_ethanol_position(api)

        closed = validate_success(
            api.close_hedge_position(
                scenario["position"]["id"],
                {"contracts_to_close": 5, "exit_price": 176.50},
                RISK_MANAGER,
            ),
            200,
        )

        assert closed["status"] == "PARTIALLY_CLOSED", closed["status"]
        assert closed["realized_pnl_cents"] == 797500, closed["realized_pnl_cents"]
        assert closed["unrealized_pnl_cents"] == 580000, closed["unrealized_pnl_cents"]
        assert closed["contracts_open"] == 5, closed["contracts_open"]
        assert closed["contracts_closed"] == 5, closed["contracts_closed"]
        assert_null(closed["closed_at"], "closed_at")

    def test_closing_the_last_five_lots_closes_the_position_and_zeroes_the_unrealized(self, api):
        """Realized reaches 1595000 as the sum of both slices and unrealized is forced to zero.

        PRD 3.9: "Closing exactly the number open moves it to `CLOSED`, which is
        terminal, sets `contracts_open` to 0, records `closed_at` and forces
        `unrealized_pnl_cents` to 0."

        Design: Corner/state_machines/hedge_partial_close_then_full_close_walks_the_position_to_closed
        """
        scenario = _short_ethanol_position(api)
        fx.close_hedge(api, scenario["position"]["id"], 5, 176.50)

        closed = validate_success(
            api.close_hedge_position(
                scenario["position"]["id"],
                {"contracts_to_close": 5, "exit_price": 176.50},
                RISK_MANAGER,
            ),
            200,
        )

        assert closed["status"] == "CLOSED", closed["status"]
        assert closed["realized_pnl_cents"] == 1595000, closed["realized_pnl_cents"]
        assert closed["unrealized_pnl_cents"] == 0, closed["unrealized_pnl_cents"]
        assert closed["contracts_open"] == 0, closed["contracts_open"]
        assert closed["contracts_closed"] == 10, closed["contracts_closed"]
        assert_not_null(closed["closed_at"], "closed_at")

    def test_a_third_close_on_a_closed_position_is_refused(self, api):
        """CLOSED is terminal, so there is no lot left to sell and no state to leave.

        PRD 3.9: "The position must be `OPEN` or `PARTIALLY_CLOSED`, otherwise
        `ERR_INVALID_POSITION_STATE`, and `contracts_to_close` must be at least 1
        and at most `contracts_open`, otherwise
        `ERR_CLOSE_EXCEEDS_OPEN_CONTRACTS`."

        Design: Corner/state_machines/hedge_partial_close_then_full_close_walks_the_position_to_closed
        """
        scenario = _short_ethanol_position(api)
        fx.close_hedge(api, scenario["position"]["id"], 5, 176.50)
        fx.close_hedge(api, scenario["position"]["id"], 5, 176.50)

        validate_error(
            api.close_hedge_position(
                scenario["position"]["id"],
                {"contracts_to_close": 1, "exit_price": 176.50},
                RISK_MANAGER,
            ),
            ApiErrorId.INVALID_POSITION_STATE,
            409,
        )

        after = get_success_data(
            api.get_hedge_position(scenario["position"]["id"], RISK_MANAGER)
        )
        assert after["status"] == "CLOSED", after["status"]
        assert after["contracts_closed"] == 10, after["contracts_closed"]
        assert after["realized_pnl_cents"] == 1595000, after["realized_pnl_cents"]
