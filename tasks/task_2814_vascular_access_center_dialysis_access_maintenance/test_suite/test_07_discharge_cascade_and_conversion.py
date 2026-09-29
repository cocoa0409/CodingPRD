"""The discharge cascade, the conversion it fires and the bookings it strands.

One discharge call reaches five entities in a fixed order, and the last two hops fire
only because a plan had been walked out of MATURATION_HOLD and back. The same cascade
retires an access underneath a booking that no call in the chain ever names.
"""

from test_helpers import assertions
from test_helpers import fixtures as fx
from test_helpers import validate_error, validate_paginated, validate_success

CATHETER_PLACED_ON = "2026-05-01"
FISTULA_PLACED_ON = "2026-06-20"
DISCHARGE_CLOCK = "2026-08-01T14:30:00Z"


def _catheter_and_maturing_fistula(api):
    """A catheter in use, a fistula maturing, and two surveillance readings on the fistula."""
    center = fx.seed_center(api)
    catheter = fx.seed_catheter_in_use(
        api, center["patient_id"], placed_on=CATHETER_PLACED_ON
    )
    fistula = fx.seed_access_maturing(
        api, center["patient_id"], access_type="AVF", placed_on=FISTULA_PLACED_ON
    )
    readings = fx.seed_reading_pair(api, fistula["id"], center["facility_id"])
    return center, catheter, fistula, readings


def _plan_walked_through_the_hold_loop(api, center, catheter, fistula):
    """An ACTIVE plan whose readiness was earned only on its second check.

    The first check reports a flow of 599 and fails, which parks the plan in
    MATURATION_HOLD; the second reports exactly 600 and passes, which walks it back to
    ACTIVE. Only an ACTIVE plan whose readiness holds converts later.
    """
    plan = fx.seed_active_plan(api, center["patient_id"], catheter, fistula["id"])
    assert plan["status"] == "ACTIVE"

    failed = fx.file_maturation_check(api, plan["id"], flow_ml_min=599)
    assert failed["status"] == "MATURATION_HOLD"
    assert failed["readiness_met"] is False
    assert failed["readiness_failure_reasons"] == ["FLOW"]
    assert failed["last_flow_ml_min"] == 599

    passed = fx.file_maturation_check(api, plan["id"], flow_ml_min=600)
    assert passed["status"] == "ACTIVE"
    assert passed["readiness_met"] is True
    assert passed["readiness_failure_reasons"] == []
    assert passed["maturation_check_count"] == 2
    assert passed["days_since_placement"] == 42
    return plan, passed


def _maturation_case_in_recovery(api, center, fistula):
    """A fistula-maturation case on the fistula, in recovery and cleared to discharge."""
    referral = fx.seed_referral(
        api,
        fistula["id"],
        center["facility_id"],
        suspected_problem="MATURATION_FAILURE",
        clinical_narrative="fistula slow to mature, needs assisted maturation",
        missed_treatment_count=0,
    )
    triaged = fx.triage(api, referral["id"])
    procedure = fx.book_case(
        api, triaged["id"], center["room_id"], center["operator_id"], triaged["version"],
        "2026-08-01T13:00:00Z", "2026-08-01T14:00:00Z",
        procedure_type="FISTULA_MATURATION_INTERVENTION",
        sedation_level="MODERATE",
        sedation_rn_id=center["nurse_id"],
    )

    bundle = dict(center)
    bundle["procedure_id"] = procedure["id"]
    bundle["referral_id"] = triaged["id"]
    lot = fx.seed_lot(api, "BALLOON", received_quantity=10)
    bundle["lot_id"] = lot["id"]
    bundle["usage_id"] = fx.reserve_units(api, procedure["id"], lot, 1)["id"]

    fx.set_clock(api, fx.CASE_START_CLOCK)
    fx.start_case(api, bundle)
    fx.move_to_recovery(api, bundle, "2026-08-01T14:00:00Z")
    fx.chart_observation(api, bundle, "2026-08-01T14:10:00Z", aldrete_score=8, on_room_air=False)
    fx.chart_observation(api, bundle, "2026-08-01T14:25:00Z", aldrete_score=9, on_room_air=True)
    fx.set_clock(api, DISCHARGE_CLOCK)
    return bundle


def _conversion_ready_discharge(api):
    center, catheter, fistula, _readings = _catheter_and_maturing_fistula(api)
    plan, _checked = _plan_walked_through_the_hold_loop(api, center, catheter, fistula)
    bundle = _maturation_case_in_recovery(api, center, fistula)
    return center, catheter, fistula, plan, bundle


def test_01_the_first_three_hops_consume_complete_and_mature(api):
    """Devices, referral and access all move on the single discharge call.

    The PRD states: "**Hop 1.** The procedure's `discharged_at` is set to the clock, and
    every `RESERVED` device usage on it moves `RESERVED → CONSUMED` with the inventory
    arithmetic of §3.6, taking any emptied lot to `DEPLETED`."

    It also states: "An access in `DYSFUNCTIONAL` returns to `IN_USE`; an access in
    `MATURING` also moves to `IN_USE`, but only when the discharging procedure's
    `procedure_type` is `FISTULA_MATURATION_INTERVENTION`."

    The single maturation intervention carries a weight of one, so the recomputed burden
    score is 1 while every other counter stays at 0.

    Design: Difficulty/transitive_cascade/discharge_five_hop_chain_converts_the_plan_and_retires_the_catheter
    """
    _center, _catheter, fistula, _plan, bundle = _conversion_ready_discharge(api)

    discharged = fx.discharge(api, bundle)
    assert discharged["clinical_status"] == "DISCHARGED"
    assertions.assert_instant_equals(discharged["discharged_at"], DISCHARGE_CLOCK, "discharged_at")

    usage = fx.read_usage(api, bundle["usage_id"])
    assert usage["state"] == "CONSUMED"
    assert usage["wasted_quantity"] == 0
    assertions.assert_instant_equals(usage["consumed_at"], DISCHARGE_CLOCK, "consumed_at")

    lot = fx.read_lot(api, bundle["lot_id"])
    assert lot["quantity_on_hand"] == 9
    assert lot["quantity_reserved"] == 0
    assert lot["status"] == "AVAILABLE"

    referral = fx.read_referral(api, bundle["referral_id"])
    assert referral["status"] == "COMPLETED"
    assertions.assert_instant_equals(referral["completed_at"], DISCHARGE_CLOCK, "completed_at")

    matured = fx.read_access(api, fistula["id"])
    assert matured["status"] == "IN_USE"
    assert matured["maturation_intervention_count"] == 1
    assert matured["angioplasty_count"] == 0
    assert matured["thrombectomy_count"] == 0
    assert matured["catheter_exchange_count"] == 0
    assert matured["intervention_burden_score"] == 1
    assertions.assert_burden_score(matured)


def test_02_the_last_two_hops_convert_the_plan_and_retire_the_catheter(api):
    """Hops 4 and 5 fire off the access transition, not off the request body.

    The PRD states: "**Hop 5, caused by hop 4.** Each newly converted plan's source
    access — the one named by its `from_access_id` — moves to `ABANDONED` with
    `abandoned_at` set to the clock, decrementing the owning patient's `access_count`."

    It also states: "A plan sitting in `MATURATION_HOLD`, or one that is `ACTIVE` with
    `readiness_met` false, does not convert, even when its target access reaches
    `IN_USE`."

    The fistula's `predecessor_access_id` was written by the activation and is not
    rewritten by the cascade, so the lineage survives the conversion untouched.

    Design: Difficulty/transitive_cascade/discharge_five_hop_chain_converts_the_plan_and_retires_the_catheter
    """
    center, catheter, fistula, plan, bundle = _conversion_ready_discharge(api)

    before = fx.read_patient(api, center["patient_id"])
    assert before["access_count"] == 2

    fx.discharge(api, bundle)

    converted = fx.read_plan(api, plan["id"])
    assert converted["status"] == "CONVERTED"
    assertions.assert_instant_equals(converted["converted_at"], DISCHARGE_CLOCK, "converted_at")
    assert converted["readiness_met"] is True
    assert converted["maturation_check_count"] == 2

    retired = fx.read_access(api, catheter["id"])
    assert retired["status"] == "ABANDONED"
    assertions.assert_instant_equals(retired["abandoned_at"], DISCHARGE_CLOCK, "abandoned_at")

    after = fx.read_patient(api, center["patient_id"])
    assert after["access_count"] == 1

    successor = fx.read_access(api, fistula["id"])
    assert successor["predecessor_access_id"] == catheter["id"]
    assert successor["status"] == "IN_USE"


def _standing_catheter_booking_and_a_conversion_about_to_fire(api):
    """A catheter exchange booked for 16:00 while a 13:00 fistula case waits to discharge.

    The catheter carries its own triaged referral, which is what moves it to
    DYSFUNCTIONAL, and a case that no part of the conversion chain names.
    """
    center, catheter, fistula, _readings = _catheter_and_maturing_fistula(api)
    plan, _checked = _plan_walked_through_the_hold_loop(api, center, catheter, fistula)
    bundle = _maturation_case_in_recovery(api, center, fistula)

    fx.reset_clock(api)
    fx.seed_reading(api, catheter["id"], center["facility_id"], "2026-07-30T09:00:00Z")
    catheter_referral = fx.triage(
        api,
        fx.seed_referral(
            api,
            catheter["id"],
            center["facility_id"],
            suspected_problem="CATHETER_DYSFUNCTION",
            clinical_narrative="poor catheter flows",
            missed_treatment_count=0,
        )["id"],
    )
    standing = fx.book_case(
        api, catheter_referral["id"], center["room_id"], center["operator_id"],
        catheter_referral["version"], "2026-08-01T16:00:00Z", "2026-08-01T17:00:00Z",
        procedure_type="CATHETER_EXCHANGE",
        sedation_level="MODERATE",
        sedation_rn_id=center["nurse_id"],
    )
    fx.set_clock(api, DISCHARGE_CLOCK)
    return center, catheter, fistula, plan, bundle, catheter_referral, standing


def test_03_the_cascade_abandons_an_access_a_direct_request_may_not(api):
    """The open-case guard blocks the coordinator and exempts hop 5.

    The PRD states: "A directly requested abandonment is blocked while any procedure on
    the access has a `clinical_status` of `SCHEDULED`, `IN_ROOM` or `RECOVERY`, and is
    refused with `ERR_ACCESS_HAS_OPEN_CASE`. The conversion cascade described in §3.9 is
    deliberately **exempt** from that block: the entire point of a conversion is to
    retire the old access, and any booking still standing on it is intentionally left in
    place so that it fails later, at the moment someone tries to bring the case into the
    room."

    The refused direct request and the successful cascade hop reach the identical row, so
    the asymmetry is a property of the caller and not of the access.

    Design: Difficulty/cross_entity_state_dependency/start_rejects_a_booking_whose_access_the_conversion_cascade_retired
    """
    _center, catheter, fistula, plan, bundle, _referral, standing = (
        _standing_catheter_booking_and_a_conversion_about_to_fire(api)
    )

    refused = api.set_vascular_access_status(
        catheter["id"], {"to_status": "ABANDONED"}, fx.COORDINATOR
    )
    validate_error(refused, "ERR_ACCESS_HAS_OPEN_CASE", 409)

    guarded = fx.read_access(api, catheter["id"])
    assert guarded["status"] == "DYSFUNCTIONAL"
    assert guarded["abandoned_at"] is None

    fx.discharge(api, bundle)

    assert fx.read_plan(api, plan["id"])["status"] == "CONVERTED"
    assert fx.read_access(api, fistula["id"])["status"] == "IN_USE"
    retired = fx.read_access(api, catheter["id"])
    assert retired["status"] == "ABANDONED"
    assertions.assert_instant_equals(retired["abandoned_at"], DISCHARGE_CLOCK, "abandoned_at")

    # Hop 5 retires the access and deliberately leaves the booking standing on it.
    assert fx.read_procedure(api, standing["id"])["clinical_status"] == "SCHEDULED"


def test_04_the_stranded_booking_fails_at_the_door_and_is_left_intact(api):
    """The start is refused by the state of an entity its request never names.

    The PRD states: "The access the case is being performed on must be in `MATURING`,
    `IN_USE` or `DYSFUNCTIONAL`; if it reached `ABANDONED` after the booking was made —
    which is precisely what the conversion cascade of §3.9 arranges — the start is
    refused with `ERR_ACCESS_ABANDONED`."

    The refusal is inert: the case stays SCHEDULED, its referral stays SCHEDULED rather
    than completing, and the abandoned catheter's `catheter_exchange_count` stays 0
    because that counter counts DISCHARGED procedures only.

    Design: Difficulty/cross_entity_state_dependency/start_rejects_a_booking_whose_access_the_conversion_cascade_retired
    """
    center, catheter, _fistula, _plan, bundle, referral, standing = (
        _standing_catheter_booking_and_a_conversion_about_to_fire(api)
    )

    fx.discharge(api, bundle)

    refused = api.start_procedure(standing["id"], center["operator_headers"])
    validate_error(refused, "ERR_ACCESS_ABANDONED", 409)

    unchanged = fx.read_procedure(api, standing["id"])
    assert unchanged["clinical_status"] == "SCHEDULED"
    assert unchanged["discharged_at"] is None
    assert fx.read_referral(api, referral["id"])["status"] == "SCHEDULED"

    retired = fx.read_access(api, catheter["id"])
    assert retired["status"] == "ABANDONED"
    assert retired["catheter_exchange_count"] == 0
    assert fx.read_patient(api, center["patient_id"])["access_count"] == 1


def _plan_aimed_at_an_access_that_is_already_in_use(api):
    """A catheter, a fistula already in use, a second fistula still planned, one draft plan."""
    center = fx.seed_center(api)
    catheter = fx.seed_catheter_in_use(
        api, center["patient_id"], placed_on=CATHETER_PLACED_ON
    )
    in_use_fistula = fx.seed_access_in_use(
        api, center["patient_id"], access_type="AVF", placed_on=FISTULA_PLACED_ON
    )
    planned_fistula = fx.seed_access(
        api,
        center["patient_id"],
        access_type="AVF",
        laterality="RIGHT",
        site="UPPER_ARM",
        placed_on=FISTULA_PLACED_ON,
    )
    assert planned_fistula["status"] == "PLANNED"

    plan_one = fx.seed_draft_plan(
        api, center["patient_id"], catheter, in_use_fistula["id"]
    )
    assert plan_one["status"] == "DRAFT"
    return center, catheter, in_use_fistula, planned_fistula, plan_one


def test_05_activation_is_refused_by_the_target_access_it_merely_references(api):
    """The plan row is flawless; the fistula it points at is not convertible.

    The PRD states: "Its `target_access_id` must be non-null and the target access's
    `status` must be `PLANNED`, `PLACED` or `MATURING`; a target that is already
    `IN_USE`, `DYSFUNCTIONAL` or `ABANDONED` is refused with
    `ERR_TARGET_ACCESS_NOT_CONVERTIBLE`."

    The clinical-indication gate is satisfied and never competes for this request: the
    PRD states "either the source access's `access_type` is `TUNNELED_CATHETER`, or its
    `intervention_burden_score` is at least 4, boundary inclusive", and the source is a
    tunnelled catheter carrying a burden of 0.

    Design: Difficulty/cross_entity_state_dependency/plan_activation_and_supersession_both_hinge_on_the_target_access_state
    """
    _center, catheter, in_use_fistula, _planned, plan_one = (
        _plan_aimed_at_an_access_that_is_already_in_use(api)
    )

    source = fx.read_access(api, catheter["id"])
    assert source["access_type"] == "TUNNELED_CATHETER"
    assert source["intervention_burden_score"] == 0

    refused = api.activate_conversion_plan(plan_one["id"], fx.COORDINATOR)
    validate_error(refused, "ERR_TARGET_ACCESS_NOT_CONVERTIBLE", 409)

    unchanged = fx.read_plan(api, plan_one["id"])
    assert unchanged["status"] == "DRAFT"
    assert unchanged["version"] == plan_one["version"]
    assert unchanged["readiness_met"] is False

    target = fx.read_access(api, in_use_fistula["id"])
    assert target["status"] == "IN_USE"
    assert target["predecessor_access_id"] is None
    assert target["version"] == in_use_fistula["version"]


def test_06_a_replacement_plan_supersedes_the_first_without_naming_it(api):
    """Creating plan two abandons plan one, and the abandonment is terminal.

    The PRD states: "Creation **supersedes**: any existing plan on the same
    `from_access_id` whose `status` is `DRAFT` moves `DRAFT → ABANDONED` in the same
    request."

    It also states: "Activation also writes the target access's
    `predecessor_access_id` to the value of `from_access_id` and increments that target
    access's `version`, so the successor chain is recorded on the access itself and not
    only on the plan."

    Both plans are listed against the same source access in creation order, one abandoned
    and one active, which is the whole supersession recorded in one read.

    Design: Difficulty/cross_entity_state_dependency/plan_activation_and_supersession_both_hinge_on_the_target_access_state
    """
    center, catheter, _in_use_fistula, planned_fistula, plan_one = (
        _plan_aimed_at_an_access_that_is_already_in_use(api)
    )
    validate_error(
        api.activate_conversion_plan(plan_one["id"], fx.COORDINATOR),
        "ERR_TARGET_ACCESS_NOT_CONVERTIBLE",
        409,
    )

    source = fx.read_access(api, catheter["id"])
    plan_two = validate_success(
        api.create_conversion_plan(
            {
                "patient_id": center["patient_id"],
                "from_access_id": catheter["id"],
                "target_access_type": "AVF",
                "target_conversion_date": "2026-09-01",
                "expected_access_version": source["version"],
                "target_access_id": planned_fistula["id"],
            },
            fx.COORDINATOR,
        ),
        201,
    )
    assert plan_two["status"] == "DRAFT"
    assert plan_two["maturation_check_count"] == 0
    assert plan_two["readiness_met"] is False
    assert plan_two["readiness_failure_reasons"] == []

    superseded = fx.read_plan(api, plan_one["id"])
    assert superseded["status"] == "ABANDONED"

    activated = fx.activate_plan(api, plan_two["id"])
    assert activated["status"] == "ACTIVE"

    successor = fx.read_access(api, planned_fistula["id"])
    assert successor["predecessor_access_id"] == catheter["id"]
    assert successor["version"] == planned_fistula["version"] + 1
    assert successor["status"] == "PLANNED"

    revived = api.activate_conversion_plan(plan_one["id"], fx.COORDINATOR)
    validate_error(revived, "ERR_PLAN_STATE_INVALID", 409)
    assert fx.read_plan(api, plan_one["id"])["status"] == "ABANDONED"

    plans, meta = validate_paginated(
        api.list_conversion_plans(fx.ADMIN, {"from_access_id": catheter["id"]})
    )
    assert meta["total_count"] == 2
    assert [plan["id"] for plan in plans] == [plan_one["id"], plan_two["id"]]
    assert [plan["status"] for plan in plans] == ["ABANDONED", "ACTIVE"]
