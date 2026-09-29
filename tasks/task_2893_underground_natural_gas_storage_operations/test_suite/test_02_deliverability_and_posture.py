"""Deliverability recomputation, the two curve evaluation methods and the
ordered posture ladder that gates commercial availability."""

from prd_bench_local_runner.testing import validate_paginated

from test_helpers import factories as F
from test_helpers.api_errors import (
    ERR_FIELD_FROZEN,
    ERR_INTERRUPTIBLE_RESTRICTED,
)
from test_helpers.assertions import (
    assert_error_envelope,
    assert_field_derived_block,
    assert_ok,
    assert_volume,
)
from test_helpers.constants import (
    DELIVERABILITY_TIER_FLOOR,
    DIRECTION_INJECTION,
    EMERGENCY_CONTAINED,
    INTEGRITY_MIT_CURRENT,
    INTEGRITY_MIT_FAILED,
    LEDGER_CURTAILMENT_CREDIT,
    MIT_OUTCOME_FAIL,
    NOMINATION_CONFIRMED,
    NOMINATION_SUBMITTED,
    POSTURE_FROZEN,
    POSTURE_OPEN,
    POSTURE_RESTRICTED,
    REMEDIATION_OPEN,
    SERVICE_CLASS_INTERRUPTIBLE,
    SHUT_IN_REASON_MIT_FAILURE,
    TIER_1,
    TIER_2,
    TIER_3,
    WELL_IN_SERVICE,
    WELL_SHUT_IN,
    WELL_TYPE_OBSERVATION,
)
from test_helpers.fixtures import (
    add_sibling_contract,
    advance_emergency,
    build_std_world,
    confirm_nomination,
    create_field,
    create_std_field,
    create_well,
    fail_mit_on_well,
    file_and_submit_nomination,
    freeze_field_by_emergency,
    ledger_entries,
    read_contract,
    read_field,
    read_nomination,
    read_well,
    record_mit,
    schedule_mit,
    set_clock,
)
from test_helpers.test_users import (
    FIELD_OPERATOR,
    INTEGRITY_ENGINEER,
    SCHEDULING_COORDINATOR,
)


def _std_field_with_one_well(api, **overrides):
    """A standard reservoir plus a single wellbore rated far above every curve
    value, so the mechanical cap never binds and the curve is observed alone."""
    field = create_std_field(api, **overrides)
    create_well(api, field["id"], well_name="AUR-1", rated_rate_dth_per_day=600000)
    return read_field(api, field["id"], SCHEDULING_COORDINATOR)


class TestDeliverabilityMethodVariants:
    """Two reservoirs of byte-identical geometry evaluated under the two
    published methods."""

    def test_interpolated_method_reads_the_bracketed_rate_pair(self, api):
        """A reservoir sitting at 37.50 percent — halfway between the 25 and 50
        curve points — publishes the interpolated pair 225000 withdrawal and
        300000 injection.

        PRD §2.7: "Each rate is then the low point's rate plus the fraction
        multiplied by the difference between the high point's rate and the low
        point's rate, rounded half up to a whole dekatherm per day."

        Design: Difficulty/dual_variant_calc/deliverability_curve_interpolated_vs_tier_floor_on_identical_field_state
        """
        field = _std_field_with_one_well(
            api, name="Aurora Dome A", field_code="F-AUR-A"
        )
        assert_field_derived_block(
            field,
            working_gas=3000000.000,
            inventory_pct=37.50,
            pressure=1325,
            tier=TIER_2,
            withdrawal_rate=225000,
            injection_rate=300000,
            wells_in_service=1,
            posture=POSTURE_OPEN,
        )
        assert_volume(field["max_working_gas_dth"], 8000000.000, "max_working_gas_dth")

    def test_tier_floor_method_reads_the_step_function_floor_pair(self, api):
        """The same reservoir state under the floor method takes both rates from
        the 25 percent point and publishes 150000 withdrawal / 350000 injection.

        PRD §2.7: "The curve behaves as a step function with floor semantics:
        each rate is taken exactly from the highest curve point whose
        `inventory_pct` is less than or equal to the field's `inventory_pct`."

        Design: Difficulty/dual_variant_calc/deliverability_curve_interpolated_vs_tier_floor_on_identical_field_state
        """
        field = _std_field_with_one_well(
            api,
            name="Aurora Dome B",
            field_code="F-AUR-B",
            deliverability_method=DELIVERABILITY_TIER_FLOOR,
        )
        assert field["deliverability_method"] == DELIVERABILITY_TIER_FLOOR
        assert_field_derived_block(
            field,
            inventory_pct=37.50,
            pressure=1325,
            tier=TIER_2,
            withdrawal_rate=150000,
            injection_rate=350000,
            wells_in_service=1,
            posture=POSTURE_OPEN,
        )

    def test_the_two_methods_diverge_on_byte_identical_reservoir_state(self, api):
        """Inventory, pressure and tier are identical on both reservoirs while the
        published rates differ by 75000 Dth on withdrawal and by 50000 Dth the
        other way on injection.

        PRD §2.7: "For the same field state this method is strictly more
        conservative on withdrawal and strictly more generous on injection than
        interpolation, so the two methods legitimately publish different integers
        for byte-identical input."

        Design: Difficulty/dual_variant_calc/deliverability_curve_interpolated_vs_tier_floor_on_identical_field_state
        """
        interpolated = _std_field_with_one_well(
            api, name="Aurora Dome A", field_code="F-AUR-A"
        )
        floored = _std_field_with_one_well(
            api,
            name="Aurora Dome B",
            field_code="F-AUR-B",
            deliverability_method=DELIVERABILITY_TIER_FLOOR,
        )
        for shared in ("inventory_pct", "current_pressure_psig", "deliverability_tier",
                       "max_working_gas_dth", "wells_in_service_count", "field_posture"):
            assert interpolated[shared] == floored[shared], (
                f"{shared} must be identical on byte-identical input: "
                f"{interpolated[shared]} vs {floored[shared]}"
            )
        assert (
            interpolated["max_withdrawal_rate_dth_per_day"]
            - floored["max_withdrawal_rate_dth_per_day"]
            == 75000
        )
        assert (
            floored["max_injection_rate_dth_per_day"]
            - interpolated["max_injection_rate_dth_per_day"]
            == 50000
        )


def _mini_field_with_one_well(api, well_name, **overrides):
    """An F_MINI reservoir plus one wellbore rated 600000, so the two-point curve
    is the only thing that can bind either rate."""
    field = create_field(api, **overrides)
    create_well(api, field["id"], well_name=well_name, rated_rate_dth_per_day=600000)
    return read_field(api, field["id"], SCHEDULING_COORDINATOR)


class TestCurveEvaluationGeometry:
    """What the curve is evaluated at, and what it returns at and between knots."""

    def test_tier_floors_are_read_from_the_two_decimal_inventory_pct(self, api):
        """Three reservoirs holding 124950, 125000 and 125050 Dth land on 24.99,
        25.00 and 25.01 percent and therefore on TIER_1, TIER_2 and TIER_2 — the
        band floor is inclusive — while all three round to the same 1150 psig.

        PRD §2.7: "`deliverability_tier` is a band label read from
        `inventory_pct`: `TIER_1` below 25 percent, `TIER_2` from 25 up to but not
        including 50 percent, `TIER_3` from 50 up to but not including 75 percent,
        and `TIER_4` at 75 percent or above."

        Design: Corner/calculations/deliverability_tier_floors_compared_against_the_two_decimal_inventory_pct
        """
        below = _mini_field_with_one_well(
            api, "BELOW-1", name="Cavern Below", field_code="F-BELOW",
            opening_working_gas_dth=124950,
        )
        at = _mini_field_with_one_well(
            api, "AT-1", name="Cavern At", field_code="F-AT",
            opening_working_gas_dth=125000,
        )
        above = _mini_field_with_one_well(
            api, "ABOVE-1", name="Cavern Above", field_code="F-ABOVE",
            opening_working_gas_dth=125050,
        )
        assert_field_derived_block(
            below, inventory_pct=24.99, pressure=1150, tier=TIER_1,
            withdrawal_rate=74970, injection_rate=225030,
            wells_in_service=1, posture=POSTURE_OPEN,
        )
        assert_field_derived_block(
            at, inventory_pct=25.00, pressure=1150, tier=TIER_2,
            withdrawal_rate=75000, injection_rate=225000,
            wells_in_service=1, posture=POSTURE_OPEN,
        )
        assert_field_derived_block(
            above, inventory_pct=25.01, pressure=1150, tier=TIER_2,
            withdrawal_rate=75030, injection_rate=224970,
            wells_in_service=1, posture=POSTURE_OPEN,
        )

    def test_curve_is_read_verbatim_on_a_knot_and_interpolated_between_knots(self, api):
        """A reservoir resting exactly on the 50 percent curve point reports that
        point's rates untouched, while one resting halfway between the 25 and 50
        points reports the genuinely interpolated pair.

        PRD §2.7: "When the low and high points are the same point — because the
        field's inventory sits exactly on a curve point — the rate is that point's
        rate with no interpolation."

        Design: Corner/calculations/curve_evaluation_at_an_exact_knot_point_and_between_two_knots
        """
        on_knot = _std_field_with_one_well(
            api, name="Aurora Knot", field_code="F-K1",
            opening_working_gas_dth=4000000,
        )
        between = _std_field_with_one_well(
            api, name="Aurora Between", field_code="F-K2",
            opening_working_gas_dth=3000000,
        )
        assert_field_derived_block(
            on_knot, inventory_pct=50.00, pressure=1500, tier=TIER_3,
            withdrawal_rate=300000, injection_rate=250000,
            wells_in_service=1, posture=POSTURE_OPEN,
        )
        assert_field_derived_block(
            between, inventory_pct=37.50, pressure=1325, tier=TIER_2,
            withdrawal_rate=225000, injection_rate=300000,
            wells_in_service=1, posture=POSTURE_OPEN,
        )
        for field in (on_knot, between):
            assert_volume(field["max_working_gas_dth"], 8000000.000, "max_working_gas_dth")

    def test_curve_lookup_uses_the_rounded_percentage_not_the_raw_ratio(self, api):
        """A reservoir holding 166667 of 500000 Dth is evaluated at 33.33 percent,
        which yields 200010 Dth/day of injection rather than the 200000 an
        unrounded ratio would produce, while the pressure keeps the raw fraction.

        PRD §2.7: "`inventory_pct` is the working gas inventory divided by
        `max_working_gas_dth`, multiplied by one hundred, rounded half up to 2
        decimal places."

        Design: Corner/calculations/curve_lookup_uses_the_rounded_pct_not_the_raw_inventory_ratio
        """
        field = _mini_field_with_one_well(
            api, "PREC-1", name="Cavern Precision", field_code="F-PREC",
            opening_working_gas_dth=166667,
        )
        assert_field_derived_block(
            field,
            working_gas=166667.000,
            inventory_pct=33.33,
            pressure=1267,
            tier=TIER_2,
            withdrawal_rate=99990,
            injection_rate=200010,
            wells_in_service=1,
            posture=POSTURE_OPEN,
        )


class TestWellCapacityFiltering:
    """Which wellbores are allowed to contribute mechanical capacity."""

    def test_observation_and_shut_in_wellbores_contribute_no_capacity(self, api):
        """A 600000 Dth/day observation wellbore and a 600000 Dth/day shut-in
        wellbore add nothing, so the single 100000 Dth/day wellbore caps both rates
        below the curve until the shut-in wellbore returns to service.

        PRD §2.7: "`wells_in_service_count` is the number of wellbores on this
        field whose `well_type` is `INJECTION_WITHDRAWAL` and whose
        `operational_state` is `IN_SERVICE`."

        Design: Corner/calculations/deliverability_ignores_observation_and_out_of_service_wells
        """
        field = create_field(api)
        create_well(api, field["id"], well_name="MINI-A", rated_rate_dth_per_day=100000)
        create_well(
            api, field["id"], well_name="MINI-B",
            well_type=WELL_TYPE_OBSERVATION, rated_rate_dth_per_day=600000,
        )
        shut_in = create_well(
            api, field["id"], well_name="MINI-C",
            rated_rate_dth_per_day=600000, initial_operational_state=WELL_SHUT_IN,
        )
        before = read_field(api, field["id"], SCHEDULING_COORDINATOR)
        assert_field_derived_block(
            before, inventory_pct=50.00, pressure=1500, tier=TIER_3,
            withdrawal_rate=100000, injection_rate=100000,
            wells_in_service=1, posture=POSTURE_OPEN,
        )

        returned = assert_ok(
            api.change_well_service(
                shut_in["id"], F.service_change_payload(WELL_IN_SERVICE), FIELD_OPERATOR
            )
        )
        assert returned["operational_state"] == WELL_IN_SERVICE
        assert returned["service_change_count"] == 1

        after = read_field(api, field["id"], SCHEDULING_COORDINATOR)
        assert_field_derived_block(
            after, inventory_pct=50.00, pressure=1500, tier=TIER_3,
            withdrawal_rate=150000, injection_rate=150000,
            wells_in_service=2, posture=POSTURE_OPEN,
        )

        rows, meta = validate_paginated(
            api.list_wells(
                SCHEDULING_COORDINATOR,
                {
                    "storage_field_id": field["id"],
                    "integrity_state": INTEGRITY_MIT_CURRENT,
                    "limit": 100,
                },
            )
        )
        assert meta["total_count"] == 3, (
            "every wellbore stays integrity-tracked regardless of type or service state"
        )
        assert len(rows) == 3


class TestPostureLadder:
    """The ordered chain of posture clauses, and the first one that holds."""

    def test_the_first_matching_posture_clause_decides_the_answer(self, api):
        """Three reservoirs match three different clauses of the same chain: a
        one-wellbore field whose only wellbore fails is FROZEN by clause 1 even
        though clause 3 also holds, a two-wellbore field with the same failure is
        only RESTRICTED, and a healthy field above its pressure ceiling is
        RESTRICTED by clause 4.

        PRD §2.6: "The derivation is evaluated as an ordered chain of clauses, and
        the **first** clause that holds decides the answer."

        Design: Corner/calculations/field_posture_takes_the_first_matching_clause_not_the_worst_one
        """
        lone = create_field(api, name="Cavern One", field_code="F-ONE")
        lone_well = create_well(api, lone["id"], well_name="ONE-1")
        pair = create_field(api, name="Cavern Two", field_code="F-TWO")
        pair_failing = create_well(api, pair["id"], well_name="TWO-1")
        pair_healthy = create_well(api, pair["id"], well_name="TWO-2")
        # base 2938 + 0.70 * 60 = 2980 psig, above the 2850 posture ceiling that
        # ninety-five percent of the 3000 psig maximum yields.
        pressed = create_field(
            api, name="Cavern Press", field_code="F-PRESS",
            base_pressure_psig=2938, pressure_span_psig=60, max_pressure_psig=3000,
            opening_working_gas_dth=350000,
        )
        pressed_well = create_well(api, pressed["id"], well_name="PRESS-1")

        first = schedule_mit(api, lone_well["id"])
        second = schedule_mit(api, pair_failing["id"])
        set_clock(api, "2026-08-02T07:00:00Z")
        record_mit(api, first["id"], MIT_OUTCOME_FAIL, 400)
        record_mit(api, second["id"], MIT_OUTCOME_FAIL, 400)

        assert_field_derived_block(
            read_field(api, lone["id"]),
            wells_in_service=0, withdrawal_rate=0, injection_rate=0,
            posture=POSTURE_FROZEN,
        )
        assert_field_derived_block(
            read_field(api, pair["id"]),
            wells_in_service=1, withdrawal_rate=150000, injection_rate=150000,
            posture=POSTURE_RESTRICTED,
        )
        assert_field_derived_block(
            read_field(api, pressed["id"]),
            inventory_pct=70.00, pressure=2980, tier=TIER_3,
            withdrawal_rate=210000, injection_rate=90000,
            wells_in_service=1, posture=POSTURE_RESTRICTED,
        )

        for well_id in (lone_well["id"], pair_failing["id"]):
            failed = read_well(api, well_id)
            assert failed["operational_state"] == WELL_SHUT_IN
            assert failed["shut_in_reason"] == SHUT_IN_REASON_MIT_FAILURE
            assert failed["integrity_state"] == INTEGRITY_MIT_FAILED
        for well_id in (pair_healthy["id"], pressed_well["id"]):
            untouched = read_well(api, well_id)
            assert untouched["operational_state"] == WELL_IN_SERVICE
            assert untouched["integrity_state"] == INTEGRITY_MIT_CURRENT

        _, meta = validate_paginated(
            api.list_remediation_programs(
                INTEGRITY_ENGINEER, {"status": REMEDIATION_OPEN, "limit": 100}
            )
        )
        assert meta["total_count"] == 2, "one remediation program per failed wellbore"


def _world_with_submitted_injection(api, volume_dth, gas_day, **world_kwargs):
    """A standard reservoir carrying one submitted-but-unallocated injection, so
    no sweep has anything to withdraw when the posture later changes."""
    world = build_std_world(api, well_names=["AUR-1"], **world_kwargs)
    nomination = file_and_submit_nomination(
        api,
        world.contract_id,
        world.shipper_id,
        gas_day=gas_day,
        direction=DIRECTION_INJECTION,
        nominated_volume_dth=volume_dth,
    )
    return world, nomination


class TestEmergencyDrivenPostureGate:
    """A nomination's fate decided by the status of an emergency event two
    entities away."""

    def test_confirm_is_refused_while_the_event_stands_responding(self, api):
        """With a serious leak responding on the reservoir, the posture is FROZEN
        even though a healthy wellbore is still in service, and the allocation is
        refused without touching the nomination.

        PRD §2.6: "While a field is `FROZEN`, no nomination on it may be confirmed,
        no gas movement ticket on it may be confirmed, no contract written against
        it may be activated, and no compressor run may be booked on it; each of
        those attempts is rejected with `ERR_FIELD_FROZEN` (HTTP 422)."

        Design: Difficulty/cross_entity_state_dependency/nomination_confirm_gated_on_field_posture_driven_by_an_emergency_event
        """
        world, nomination = _world_with_submitted_injection(api, 90000, "2026-08-05")
        freeze_field_by_emergency(api, world.field_id, well_id=world.well_id)

        assert_field_derived_block(
            read_field(api, world.field_id),
            wells_in_service=1, injection_rate=300000, posture=POSTURE_FROZEN,
        )
        assert_error_envelope(
            api.confirm_nomination(nomination["id"], SCHEDULING_COORDINATOR),
            ERR_FIELD_FROZEN,
        )

        refused = read_nomination(api, nomination["id"])
        assert refused["status"] == NOMINATION_SUBMITTED
        assert refused["confirmed_volume_dth"] == 0
        assert refused["curtailed_volume_dth"] == 0
        assert read_contract(api, world.contract_id)["scheduled_injection_dth"] == 0

    def test_the_identical_confirm_succeeds_once_the_event_is_contained(self, api):
        """Containment re-derives the posture from scratch, and the very same
        confirm then allocates the whole 90000 Dth request with nothing else about
        the nomination, contract, shipper or wellbore having moved.

        PRD §3.8: "In both cases `contained_at` is stamped from the logical clock
        and the reservoir's posture is recomputed from scratch — which is how a
        field leaves `FROZEN` once no event on it is responding or evacuating, and
        how it lands in `RESTRICTED` rather than `OPEN` if a wellbore on it is
        still `MIT_FAILED` or if its pressure still sits above the posture
        ceiling."

        Design: Difficulty/cross_entity_state_dependency/nomination_confirm_gated_on_field_posture_driven_by_an_emergency_event
        """
        world, nomination = _world_with_submitted_injection(api, 90000, "2026-08-05")
        responding = freeze_field_by_emergency(
            api, world.field_id, well_id=world.well_id
        )

        contained = advance_emergency(api, responding["id"], EMERGENCY_CONTAINED)
        assert contained["status"] == EMERGENCY_CONTAINED
        assert contained["contained_at"] is not None
        assert_field_derived_block(
            read_field(api, world.field_id), posture=POSTURE_OPEN, wells_in_service=1
        )

        confirmed = confirm_nomination(api, nomination["id"])
        assert confirmed["status"] == NOMINATION_CONFIRMED
        assert confirmed["confirmed_volume_dth"] == 90000
        assert confirmed["curtailed_volume_dth"] == 0
        assert read_contract(api, world.contract_id)["scheduled_injection_dth"] == 90000
        assert not [
            e for e in ledger_entries(api, world.contract_id)
            if e["entry_type"] == LEDGER_CURTAILMENT_CREDIT
        ], "nothing was ever confirmed before the freeze, so nothing was credited"


def _restricted_world_with_two_service_classes(api):
    """Two wellbores of 300000 Dth/day each, a firm and an interruptible contract
    on the same reservoir and gas day, and one failed integrity test that takes
    the reservoir to RESTRICTED without moving its injection ceiling."""
    world = build_std_world(
        api,
        well_names=["AUR-1", "AUR-2"],
        well_rate_dth_per_day=300000,
        contract_overrides={"contract_code": "CF-FIRM"},
    )
    interruptible = add_sibling_contract(
        api, world, contract_code="CI-INTR", service_class=SERVICE_CLASS_INTERRUPTIBLE
    )
    firm_nomination = file_and_submit_nomination(
        api, world.contract_id, world.shipper_id,
        gas_day="2026-08-20", direction=DIRECTION_INJECTION, nominated_volume_dth=90000,
    )
    interruptible_nomination = file_and_submit_nomination(
        api, interruptible["id"], world.shipper_id,
        gas_day="2026-08-20", direction=DIRECTION_INJECTION, nominated_volume_dth=60000,
    )
    fail_mit_on_well(
        api,
        world.wells[0]["id"],
        scheduled_start_at="2026-08-10T00:00:00Z",
        scheduled_end_at="2026-08-10T06:00:00Z",
        record_at="2026-08-10T12:00:00Z",
        result_pressure_psig=1200,
    )
    return world, interruptible, firm_nomination, interruptible_nomination


class TestIntegrityDrivenInterruptibleGate:
    """One wellbore's integrity state deciding two nominations differently."""

    def test_interruptible_confirm_is_refused_while_a_sibling_wellbore_has_failed(self, api):
        """A failed integrity test on one wellbore takes the reservoir to
        RESTRICTED, and the interruptible allocation is refused with its own code
        even though the reservoir's injection ceiling never moved.

        PRD §2.6: "While a field is `RESTRICTED`, firm service continues
        unaffected, but a nomination whose contract carries `service_class` of
        `INTERRUPTIBLE` may not be confirmed and the attempt is rejected with
        `ERR_INTERRUPTIBLE_RESTRICTED` (HTTP 422)."

        Design: Difficulty/cross_entity_state_dependency/interruptible_confirm_gated_on_a_sibling_wells_integrity_state_while_firm_proceeds
        """
        world, interruptible, _, interruptible_nomination = (
            _restricted_world_with_two_service_classes(api)
        )
        assert_field_derived_block(
            read_field(api, world.field_id),
            wells_in_service=1, injection_rate=300000, posture=POSTURE_RESTRICTED,
        )
        assert read_well(api, world.wells[0]["id"])["integrity_state"] == INTEGRITY_MIT_FAILED
        assert read_well(api, world.wells[1]["id"])["integrity_state"] == INTEGRITY_MIT_CURRENT

        assert_error_envelope(
            api.confirm_nomination(interruptible_nomination["id"], SCHEDULING_COORDINATOR),
            ERR_INTERRUPTIBLE_RESTRICTED,
        )
        refused = read_nomination(api, interruptible_nomination["id"])
        assert refused["status"] == NOMINATION_SUBMITTED
        assert refused["confirmed_volume_dth"] == 0
        assert read_contract(api, interruptible["id"])["scheduled_injection_dth"] == 0
        assert not [
            e for e in ledger_entries(api, interruptible["id"])
            if e["entry_type"] == LEDGER_CURTAILMENT_CREDIT
        ], "nothing stood confirmed when the integrity test failed"

    def test_firm_confirm_proceeds_on_the_same_restricted_reservoir(self, api):
        """The firm nomination on the very same reservoir and gas day allocates its
        whole 90000 Dth against the unchanged 300000 Dth/day injection ceiling.

        PRD §3.5: "For a `FIRM` contract, the headroom is the field ceiling less
        the firm sum less the interruptible sum."

        Design: Difficulty/cross_entity_state_dependency/interruptible_confirm_gated_on_a_sibling_wells_integrity_state_while_firm_proceeds
        """
        world, _, firm_nomination, _ = _restricted_world_with_two_service_classes(api)
        assert read_field(api, world.field_id)["field_posture"] == POSTURE_RESTRICTED

        confirmed = confirm_nomination(api, firm_nomination["id"])
        assert confirmed["status"] == NOMINATION_CONFIRMED
        assert confirmed["confirmed_volume_dth"] == 90000
        assert confirmed["curtailed_volume_dth"] == 0
        assert read_contract(api, world.contract_id)["scheduled_injection_dth"] == 90000
        assert not [
            e for e in ledger_entries(api, world.contract_id)
            if e["entry_type"] == LEDGER_CURTAILMENT_CREDIT
        ], "a fully confirmed firm nomination writes no curtailment credit"
