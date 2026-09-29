"""Allergy panel billing arithmetic, observation sizing and the safety-before-temporal precedence on panel administration."""

from prd_bench_local_runner.testing import validate_error

from test_helpers import ApiErrorId
from test_helpers import assertions as check
from test_helpers import constants as C
from test_helpers import fixtures as SETUP
from test_helpers import test_users as USERS


def _billing_plan_with_patient(api):
    """A plan paying eight tenths of each unit, and one adult chart under it.

    The patient has no prior reactions and carries epinephrine, so the chart
    opens at a risk score of 5 and neither the epinephrine gate nor the
    elevated-risk observation floor is in play.
    """
    return SETUP.policy_with_patient(
        api,
        plan_code="BILL-2999",
        patient_mrn=C.mrn(10031),
        policy_overrides={
            "payer_name": "Billing Mutual",
            "covered_pct_bps": 8000,
            "observation_floor_minutes": 20,
        },
        patient_overrides={
            "full_name": "Billing Patient",
            "date_of_birth": "1988-06-20",
            "epinephrine_on_file": True,
            "prior_systemic_reaction_count": 0,
        },
    )


def test_env36_skin_prick_bills_the_rounded_per_unit_gross_times_thirty_six_units(api):
    """PRD 3.3: "An `ENV_36` panel by `SKIN_PRICK` under a plan covering 8000 basis
    points takes the 0.8500 tier, giving a per-unit gross of 1509 cents, 36 billed
    units, a `practice_charge_cents` of 54324, a per-unit patient share of 302 cents
    and a `patient_responsibility_cents` of 10872."

    Design: Difficulty/combinatorial_formula/allergy_billing_per_unit_rounding_order
    """
    base = _billing_plan_with_patient(api)

    # The panel is pricked at nine in the morning on the large-tier antigen count.
    SETUP.set_clock(api, "2026-08-01T09:00:00Z")
    order = SETUP.administered_order(
        api,
        base["patient"]["id"],
        panel_code=C.PANEL_ENV_36,
        method=C.METHOD_SKIN_PRICK,
    )
    check.assert_allergy_test_order(
        order,
        status=C.ORDER_ADMINISTERED,
        antigen_count=36,
        observation_required_minutes=C.OBSERVATION_BASE_SKIN_PRICK,
    )

    # Half an hour later the observation window has elapsed and the reader bills.
    SETUP.set_clock(api, "2026-08-01T09:30:00Z")
    billed = SETUP.record_reading(api, order["id"], 12, max_wheal_mm=8.0)
    check.assert_allergy_test_order(
        billed,
        status=C.ORDER_READ,
        antigen_count=36,
        billed_units=36,
        practice_charge_cents=54324,
        patient_responsibility_cents=10872,
    )

    # Rounding the extended amount instead of the per-unit amount would have
    # published 54315 and 10863 -- nine cents light on each figure.
    assert billed["practice_charge_cents"] != 54315
    assert billed["patient_responsibility_cents"] != 10863


def test_serum_arm_of_the_same_panel_bills_nine_batched_units(api):
    """PRD 3.3: "The same panel by `SERUM_IGE` under the same plan yields 9 billed
    units, a `practice_charge_cents` of 25326 and a `patient_responsibility_cents` of
    5067."

    Design: Difficulty/combinatorial_formula/allergy_billing_per_unit_rounding_order
    """
    base = _billing_plan_with_patient(api)

    # The same thirty-six-antigen panel is opened on the skin arm.
    order = SETUP.create_order(
        api,
        base["patient"]["id"],
        panel_code=C.PANEL_ENV_36,
        method=C.METHOD_SKIN_PRICK,
    )

    # The conversion rewrites the method and batches the antigens four at a time.
    converted = SETUP.convert_order_to_serum(api, order["id"])
    check.assert_allergy_test_order(
        converted,
        status=C.ORDER_SERUM_PENDING,
        method=C.METHOD_SERUM_IGE,
        billed_units=9,
        observation_required_minutes=C.OBSERVATION_MINUTES_SERUM,
        administered_at=None,
    )

    # The serum arm carries no observation wait, so the reading is admissible at once.
    billed = SETUP.record_reading(api, order["id"], 12)
    check.assert_allergy_test_order(
        billed,
        status=C.ORDER_READ,
        method=C.METHOD_SERUM_IGE,
        billed_units=9,
        practice_charge_cents=25326,
        patient_responsibility_cents=5067,
    )


def test_reaching_read_refreshes_the_sensitization_count_and_the_risk_score(api):
    """PRD 3.3: "The chart's `sensitized_antigen_count` is recomputed as the sum of
    `positive_antigen_count` across all of that patient's orders in status `READ`,
    capped at 20; the `risk_score` is recomputed under the patient's current
    `risk_score_variant`; and `supervision_tier` is re-derived from the new score."

    Design: Difficulty/combinatorial_formula/allergy_billing_per_unit_rounding_order
    """
    base = _billing_plan_with_patient(api)
    check.assert_patient(
        base["patient"],
        sensitized_antigen_count=0,
        risk_score=5,
        risk_score_variant=C.RISK_VARIANT_PROVISIONAL,
        supervision_tier=C.SUPERVISION_TIER_STANDARD,
    )

    # Twelve of the thirty-six antigens read positive on the skin arm.
    SETUP.set_clock(api, "2026-08-01T09:00:00Z")
    order = SETUP.administered_order(
        api,
        base["patient"]["id"],
        panel_code=C.PANEL_ENV_36,
        method=C.METHOD_SKIN_PRICK,
    )
    SETUP.set_clock(api, "2026-08-01T09:30:00Z")
    SETUP.record_reading(api, order["id"], 12, max_wheal_mm=8.0)

    # The chart carries the twelve sensitizations straight into the score.
    chart = SETUP.read_patient(api, base["patient"]["id"])
    check.assert_patient(
        chart,
        sensitized_antigen_count=12,
        risk_score=17,
        risk_score_variant=C.RISK_VARIANT_PROVISIONAL,
        supervision_tier=C.SUPERVISION_TIER_STANDARD,
    )


def _boundary_plan_with_patient(api, mrn_serial):
    """A plan with a 20-minute floor, and one adult chart with two prior reactions.

    Two prior reactions and epinephrine on file put the chart at 35 points, so
    the sensitizations a first panel discovers decide which side of the
    45-point observation threshold the chart lands on.
    """
    return SETUP.policy_with_patient(
        api,
        plan_code="BND-2999",
        patient_mrn=C.mrn(mrn_serial),
        policy_overrides={
            "payer_name": "Boundary Health",
            "covered_pct_bps": 8000,
            "observation_floor_minutes": 20,
        },
        patient_overrides={
            "full_name": "Boundary Patient",
            "date_of_birth": "1974-05-02",
            "epinephrine_on_file": True,
            "prior_systemic_reaction_count": 2,
        },
    )


def test_risk_score_of_exactly_forty_five_lifts_the_observation_window_to_sixty(api):
    """PRD 3.2: "If the patient's `risk_score` is 45 or higher, raise the candidate to
    at least 60 minutes."

    Design: Difficulty/boundary_precision_check/risk_score_threshold_45_boundary_on_administer
    """
    base = _boundary_plan_with_patient(api, 10111)
    patient_id = base["patient"]["id"]
    check.assert_patient(
        base["patient"],
        sensitized_antigen_count=0,
        risk_score=35,
        supervision_tier=C.SUPERVISION_TIER_STANDARD,
    )

    # The first panel is pricked while the chart still sits below the threshold.
    first = SETUP.administered_order(api, patient_id, panel_code=C.PANEL_MOLD_12)
    check.assert_allergy_test_order(
        first,
        status=C.ORDER_ADMINISTERED,
        antigen_count=12,
        observation_required_minutes=C.OBSERVATION_BASE_SKIN_PRICK,
    )

    # Ten of the twelve antigens read positive half an hour later.
    SETUP.set_clock(api, "2026-08-01T00:30:00Z")
    billed = SETUP.record_reading(api, first["id"], 10, max_wheal_mm=7.5)
    check.assert_allergy_test_order(
        billed,
        status=C.ORDER_READ,
        billed_units=12,
        practice_charge_cents=21300,
        patient_responsibility_cents=4260,
    )

    # Thirty-five points plus ten sensitizations land the chart exactly on 45.
    chart = SETUP.read_patient(api, patient_id)
    check.assert_patient(
        chart,
        sensitized_antigen_count=10,
        risk_score=C.RISK_SAFETY_THRESHOLD,
        supervision_tier=C.SUPERVISION_TIER_STANDARD,
    )

    # A second prick on the same chart is now held for the elevated-risk window.
    second = SETUP.administered_order(api, patient_id, panel_code=C.PANEL_MOLD_12)
    check.assert_allergy_test_order(
        second,
        status=C.ORDER_ADMINISTERED,
        observation_required_minutes=C.OBSERVATION_FLOOR_ELEVATED_RISK,
    )


def test_risk_score_of_forty_four_leaves_the_skin_prick_base_of_thirty(api):
    """PRD 3.2: "A `SKIN_PRICK` order for a patient scoring 44 under a plan whose floor
    is 20 therefore requires 30 minutes; the same order for a patient scoring exactly 45
    requires 60; an `INTRADERMAL` order for a low-risk patient under a plan whose floor
    is 45 requires 45, because the plan floor dominates the 40-minute base; and a serum
    conversion for a `PHYSICIAN_PRESENT` patient scoring 100 under a plan whose floor is
    120 still requires 0."

    Design: Difficulty/boundary_precision_check/risk_score_threshold_45_boundary_on_administer
    """
    base = _boundary_plan_with_patient(api, 10112)
    patient_id = base["patient"]["id"]

    # The control chart is worked up exactly like the boundary chart.
    first = SETUP.administered_order(api, patient_id, panel_code=C.PANEL_MOLD_12)
    check.assert_allergy_test_order(
        first,
        status=C.ORDER_ADMINISTERED,
        observation_required_minutes=C.OBSERVATION_BASE_SKIN_PRICK,
    )

    # Nine positives instead of ten leave the chart one point short of the threshold.
    SETUP.set_clock(api, "2026-08-01T00:30:00Z")
    billed = SETUP.record_reading(api, first["id"], 9, max_wheal_mm=7.5)
    check.assert_allergy_test_order(billed, status=C.ORDER_READ, billed_units=12)

    chart = SETUP.read_patient(api, patient_id)
    check.assert_patient(
        chart,
        sensitized_antigen_count=9,
        risk_score=44,
        supervision_tier=C.SUPERVISION_TIER_STANDARD,
    )

    # At 44 points the prick keeps its own thirty-minute base.
    second = SETUP.administered_order(api, patient_id, panel_code=C.PANEL_MOLD_12)
    check.assert_allergy_test_order(
        second,
        status=C.ORDER_ADMINISTERED,
        observation_required_minutes=C.OBSERVATION_BASE_SKIN_PRICK,
    )


def _gate_conflict_setup(api):
    """A chart that fails the epinephrine gate and the washout gate at once.

    Two prior reactions with no epinephrine on file score 45, and an
    antihistamine taken twelve hours before the opening clock leaves sixty of
    the seventy-two washout hours still to run.
    """
    base = SETUP.policy_with_patient(
        api,
        plan_code="SAFE-2999",
        patient_mrn=C.mrn(10101),
        policy_overrides={
            "payer_name": "Safety Mutual",
            "observation_floor_minutes": 20,
        },
        patient_overrides={
            "full_name": "Gate Patient",
            "date_of_birth": "1976-02-09",
            "epinephrine_on_file": False,
            "prior_systemic_reaction_count": 2,
            "antihistamine_last_dose_at": "2026-07-31T12:00:00Z",
        },
    )
    check.assert_patient(
        base["patient"],
        risk_score=C.RISK_SAFETY_THRESHOLD,
        epinephrine_on_file=False,
        risk_score_variant=C.RISK_VARIANT_PROVISIONAL,
        supervision_tier=C.SUPERVISION_TIER_STANDARD,
    )
    base["order"] = SETUP.create_order(
        api,
        base["patient"]["id"],
        panel_code=C.PANEL_MOLD_12,
        method=C.METHOD_SKIN_PRICK,
    )
    return base


def test_missing_epinephrine_outranks_the_incomplete_antihistamine_washout(api):
    """PRD 2.8: "**Second**, on panel administration, a safety failure beats a temporal
    failure: if the patient's `risk_score` is at least 45 with `epinephrine_on_file` false
    while the seventy-two-hour antihistamine washout is simultaneously incomplete, the
    response is `ERR_EPINEPHRINE_NOT_ON_FILE` from rung 10, not `ERR_WASHOUT_NOT_COMPLETE`
    from rung 11."

    Design: Difficulty/priority_pair_validation_conflict/epinephrine_safety_beats_washout_temporal_on_administer
    """
    base = _gate_conflict_setup(api)

    # Both gates are violated by the same request; the safety gate answers first.
    response = api.administer_allergy_test_order(base["order"]["id"], USERS.NURSE_1)
    validate_error(response, ApiErrorId.EPINEPHRINE_NOT_ON_FILE.value)

    # The refusal left the order exactly where it stood.
    untouched = SETUP.read_order(api, base["order"]["id"])
    check.assert_allergy_test_order(
        untouched,
        status=C.ORDER_ORDERED,
        administered_at=None,
        administered_by_user_id=None,
    )


def test_curing_the_epinephrine_gate_surfaces_the_washout_rejection(api):
    """PRD 3.2: "And the antihistamine washout must be complete: if
    `antihistamine_last_dose_at` is null the gate is satisfied outright, and otherwise at
    least seventy-two hours must have elapsed between that instant and the current clock,
    or the administration is refused with `ERR_WASHOUT_NOT_COMPLETE`."

    Design: Difficulty/priority_pair_validation_conflict/epinephrine_safety_beats_washout_temporal_on_administer
    """
    base = _gate_conflict_setup(api)

    # A rescue prescription is filed, which drops the chart back below 45 points.
    amended = SETUP.patch_patient(api, base["patient"]["id"], epinephrine_on_file=True)
    check.assert_patient(
        amended,
        epinephrine_on_file=True,
        risk_score=35,
        supervision_tier=C.SUPERVISION_TIER_STANDARD,
    )

    # With the safety rung satisfied, the temporal rung is the one that answers.
    response = api.administer_allergy_test_order(base["order"]["id"], USERS.NURSE_1)
    validate_error(response, ApiErrorId.WASHOUT_NOT_COMPLETE.value)

    untouched = SETUP.read_order(api, base["order"]["id"])
    check.assert_allergy_test_order(
        untouched, status=C.ORDER_ORDERED, administered_at=None
    )


def test_completed_washout_after_the_epinephrine_cure_admits_the_panel(api):
    """PRD 3.2: "On success the order moves `ORDERED → ADMINISTERED`, `administered_at` is
    stamped from the logical clock, `administered_by_user_id` is stamped from the acting
    identifier, and `observation_required_minutes` is re-derived from the order's own
    method."

    Design: Difficulty/priority_pair_validation_conflict/epinephrine_safety_beats_washout_temporal_on_administer
    """
    base = _gate_conflict_setup(api)

    # The rescue prescription is filed and the appointment is moved out.
    SETUP.patch_patient(api, base["patient"]["id"], epinephrine_on_file=True)
    SETUP.set_clock(api, "2026-08-03T13:00:00Z")

    # Seventy-three hours have now elapsed since the antihistamine dose.
    administered = SETUP.administer_order(api, base["order"]["id"])
    check.assert_allergy_test_order(
        administered,
        status=C.ORDER_ADMINISTERED,
        administered_by_user_id=C.USER_NURSE_1,
        observation_required_minutes=C.OBSERVATION_BASE_SKIN_PRICK,
    )
    check.assert_instant_equals(administered["administered_at"], "2026-08-03T13:00:00Z")
