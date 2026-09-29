"""Immunotherapy dose sizing across the escalation schedule, the vial millilitre ledger, and the reaction cascade that reaches the whole chart."""

from prd_bench_local_runner.testing import validate_error

from test_helpers import ApiErrorId
from test_helpers import assertions as check
from test_helpers import constants as C
from test_helpers import factories as F
from test_helpers import fixtures as SETUP
from test_helpers import test_users as USERS


def _patient_climbed_to_maintenance_step_seven(api):
    """Six cleared build-up doses, leaving the chart at pre-rollback step 7.

    The doses draw 0.05, 0.10, 0.20, 0.30, 0.40 and 0.50 mL from the 5.00 mL
    build-up vial, each administered on the half hour and discharged thirty
    minutes later, so the last draw is stamped 11:30 and the chart lands on
    step 7 at noon.
    """
    base = SETUP.immunotherapy_ready_patient(
        api,
        plan_code="IMM-2999",
        patient_mrn=C.mrn(10041),
        policy_overrides={
            "payer_name": "Immuno Mutual",
            "observation_floor_minutes": 20,
        },
        patient_overrides={
            "full_name": "Climbing Patient",
            "epinephrine_on_file": True,
        },
    )
    stamps = ("09:00", "09:30", "10:00", "10:30", "11:00", "11:30", "12:00")
    doses = []
    for index in range(6):
        SETUP.set_clock(api, "2026-08-01T{0}:00Z".format(stamps[index]))
        dose = SETUP.administer_dose(api, base["vial"]["id"])
        doses.append(dose)
        SETUP.set_clock(api, "2026-08-01T{0}:00Z".format(stamps[index + 1]))
        SETUP.clear_dose(api, dose["id"])
    base["doses"] = doses
    return base


def test_maintenance_band_from_step_seven_admits_a_yellow_vial_drawing_a_build_up_volume(api):
    """PRD 3.5: "Deciding the band on the pre-rollback step and the volume on the
    post-rollback step is not a stylistic choice; evaluating both on the same step gives
    the wrong answer whenever a rollback crosses the seam between step 6 and step 7."

    Design: Difficulty/combinatorial_formula/dose_dilution_band_from_pre_rollback_step
    """
    base = _patient_climbed_to_maintenance_step_seven(api)

    # The chart sits on the first maintenance step with the last draw at 11:30.
    chart = SETUP.read_patient(api, base["patient"]["id"])
    check.assert_patient(
        chart,
        immunotherapy_escalation_step=7,
        immunotherapy_status=C.IMMUNO_STATUS_MAINTENANCE,
        risk_score=5,
    )
    check.assert_instant_equals(chart["last_dose_administered_at"], "2026-08-01T11:30:00Z")

    # A maintenance-strength vial is compounded for the returning patient.
    yellow = SETUP.verified_vial(
        api,
        base["patient"],
        base["lot"]["id"],
        dilution_code=C.DILUTION_YELLOW,
    )
    check.assert_immunotherapy_vial(
        yellow,
        dilution_code=C.REQUIRED_DILUTION_MAINTENANCE,
        status=C.VIAL_LABEL_VERIFIED,
        label_text=C.make_label_text(
            C.mrn(10041), C.DILUTION_YELLOW, yellow["expires_at"]
        ),
    )

    # The patient returns twenty-eight whole days after that last draw.
    SETUP.set_clock(api, "2026-08-29T11:30:00Z")
    dose = SETUP.administer_dose(api, yellow["id"])

    # The band came from step 7, the volume from step 4 after the three-step rollback.
    check.assert_immunotherapy_dose(
        dose,
        status=C.DOSE_ADMINISTERED,
        escalation_step_at_dose=4,
        gap_days_at_dose=C.ROLLBACK_GAP_DAYS_MAINTENANCE,
        observation_required_minutes=C.OBSERVATION_BASE_DOSE,
        reaction_grade=0,
        observation_cleared_at=None,
    )
    check.assert_volume_ml(dose["volume_ml"], 0.30)

    drawn = SETUP.read_vial(api, yellow["id"])
    check.assert_immunotherapy_vial(drawn, status=C.VIAL_IN_USE)
    check.assert_volume_ml(drawn["volume_ml_remaining"], 4.70)
    check.assert_volume_ml(drawn["volume_ml_dispensed_total"], 0.30)
    check.assert_volume_ml(drawn["volume_ml_wasted"], 0.00)


def test_build_up_vial_is_refused_for_a_chart_whose_pre_rollback_step_is_seven(api):
    """PRD 3.5: "The vial's `dilution_code` must equal the required dilution derived from
    the pre-rollback step, or it is refused with `ERR_DILUTION_MISMATCH`."

    Design: Difficulty/combinatorial_formula/dose_dilution_band_from_pre_rollback_step
    """
    base = _patient_climbed_to_maintenance_step_seven(api)

    # A build-up-strength vial is compounded for the same maintenance patient.
    blue = SETUP.verified_vial(
        api,
        base["patient"],
        base["lot"]["id"],
        dilution_code=C.DILUTION_BLUE,
    )

    # The same twenty-eight-day gap that rolls the volume back to step 4 applies,
    # but the band is still read from step 7 and demands the maintenance strength.
    SETUP.set_clock(api, "2026-08-29T11:30:00Z")
    response = api.create_immunotherapy_dose(
        F.immunotherapy_dose_payload(blue["id"]), USERS.NURSE_1
    )
    validate_error(response, ApiErrorId.DILUTION_MISMATCH.value)

    # No volume moved out of the refused vial.
    untouched = SETUP.read_vial(api, blue["id"])
    check.assert_immunotherapy_vial(untouched, status=C.VIAL_LABEL_VERIFIED)
    check.assert_volume_ml(untouched["volume_ml_remaining"], 5.00)
    check.assert_volume_ml(untouched["volume_ml_dispensed_total"], 0.00)
    check.assert_volume_ml(untouched["volume_ml_wasted"], 0.00)


def test_superseded_build_up_vial_closes_its_ledger_at_the_maintenance_switch(api):
    """PRD 3.5: "Compounding also **supersedes**: if that patient already holds a vial in
    status `LABEL_VERIFIED` or `IN_USE`, that older vial is moved to `DISCARDED` with
    `discard_reason` `SUPERSEDED`, its `volume_ml_remaining` is moved into
    `volume_ml_wasted` and its `volume_ml_remaining` is set to 0.00, leaving the ledger
    identity of §2.10 intact."

    Design: Difficulty/combinatorial_formula/dose_dilution_band_from_pre_rollback_step
    """
    base = _patient_climbed_to_maintenance_step_seven(api)

    # The six cleared doses account for every millilitre the build-up vial dispensed.
    drawn = SETUP.read_vial(api, base["vial"]["id"])
    check.assert_immunotherapy_vial(drawn, status=C.VIAL_IN_USE, discard_reason=None)
    check.assert_volume_ml(drawn["volume_ml_dispensed_total"], 1.55)
    check.assert_volume_ml(drawn["volume_ml_remaining"], 3.45)
    cleared = [SETUP.read_dose(api, dose["id"]) for dose in base["doses"]]
    check.assert_dose_volumes_sum_to_dispensed(cleared, drawn)

    # Compounding the maintenance vial retires the build-up vial in the same call.
    SETUP.verified_vial(
        api,
        base["patient"],
        base["lot"]["id"],
        dilution_code=C.DILUTION_YELLOW,
    )

    superseded = SETUP.read_vial(api, base["vial"]["id"])
    check.assert_immunotherapy_vial(
        superseded,
        status=C.VIAL_DISCARDED,
        discard_reason=C.DISCARD_REASON_SUPERSEDED,
    )
    check.assert_volume_ml(superseded["volume_ml_remaining"], 0.00)
    check.assert_volume_ml(superseded["volume_ml_wasted"], 3.45)
    check.assert_volume_ml(superseded["volume_ml_dispensed_total"], 1.55)


def _vial_with_a_cleared_dose_and_a_fresh_draw(api):
    """A 5.00 mL vial that has cleared 0.05 mL and just drawn 0.10 mL more.

    The first dose is administered at 09:00 and discharged at 09:30, which lifts
    the chart to step 2; the second dose is drawn at 09:30 and is still inside
    its observation window.
    """
    base = SETUP.immunotherapy_ready_patient(
        api,
        plan_code="LEDG-2999",
        patient_mrn=C.mrn(10171),
        policy_overrides={
            "payer_name": "Ledger Mutual",
            "observation_floor_minutes": 20,
        },
        patient_overrides={
            "full_name": "Ledger Patient",
            "epinephrine_on_file": True,
        },
    )
    SETUP.set_clock(api, "2026-08-01T09:00:00Z")
    first = SETUP.administer_dose(api, base["vial"]["id"])
    SETUP.set_clock(api, "2026-08-01T09:30:00Z")
    SETUP.clear_dose(api, first["id"])
    second = SETUP.administer_dose(api, base["vial"]["id"])
    base["first_dose"] = first
    base["second_dose"] = second
    return base


def test_voiding_a_dose_returns_its_millilitres_and_leaves_no_residue(api):
    """PRD 3.5: "The void moves the dose `ADMINISTERED → VOIDED`, returns its `volume_ml`
    to the vial's `volume_ml_remaining` and subtracts the same figure from the vial's
    `volume_ml_dispensed_total`, so the ledger closes with no residue at all."

    Design: Difficulty/compensating_invariant/vial_millilitre_ledger_conserved_across_dose_void
    """
    base = _vial_with_a_cleared_dose_and_a_fresh_draw(api)
    vial_id = base["vial"]["id"]
    check.assert_volume_ml(base["first_dose"]["volume_ml"], 0.05)
    check.assert_volume_ml(base["second_dose"]["volume_ml"], 0.10)

    # Two draws have left the vial fifteen hundredths of a millilitre lighter.
    before = SETUP.read_vial(api, vial_id)
    check.assert_immunotherapy_vial(before, status=C.VIAL_IN_USE)
    check.assert_volume_ml(before["volume_ml_initial"], C.VIAL_DEFAULT_VOLUME_ML)
    check.assert_volume_ml(before["volume_ml_remaining"], 4.85)
    check.assert_volume_ml(before["volume_ml_dispensed_total"], 0.15)
    check.assert_volume_ml(before["volume_ml_wasted"], 0.00)

    # Ten minutes after the draw the nurse voids it as drawn in error.
    SETUP.set_clock(api, "2026-08-01T09:40:00Z")
    voided = SETUP.void_dose(
        api, base["second_dose"]["id"], C.VOID_REASON_DRAWN_IN_ERROR
    )
    check.assert_immunotherapy_dose(
        voided, status=C.DOSE_VOIDED, observation_cleared_at=None
    )
    check.assert_volume_ml(voided["volume_ml"], 0.10)

    # The vial is back exactly where the first cleared dose left it.
    after = SETUP.read_vial(api, vial_id)
    check.assert_immunotherapy_vial(after, status=C.VIAL_IN_USE)
    check.assert_volume_ml(after["volume_ml_remaining"], 4.95)
    check.assert_volume_ml(after["volume_ml_dispensed_total"], 0.05)
    check.assert_volume_ml(after["volume_ml_wasted"], 0.00)
    check.assert_dose_volumes_sum_to_dispensed(
        [SETUP.read_dose(api, base["first_dose"]["id"]), voided], after
    )


def test_void_rewinds_the_gap_clock_without_moving_the_escalation_step(api):
    """PRD 3.5: "The patient's `immunotherapy_escalation_step` is deliberately **left
    untouched** — a void neither advances the schedule nor rolls it back, and because a
    `VOIDED` dose never contributes to `last_dose_administered_at`, it also does not reset
    the gap clock."

    Design: Difficulty/compensating_invariant/vial_millilitre_ledger_conserved_across_dose_void
    """
    base = _vial_with_a_cleared_dose_and_a_fresh_draw(api)
    vial_id = base["vial"]["id"]

    SETUP.set_clock(api, "2026-08-01T09:40:00Z")
    voided = SETUP.void_dose(
        api, base["second_dose"]["id"], C.VOID_REASON_DRAWN_IN_ERROR
    )

    # The chart still stands on step 2, with the gap clock back on the cleared dose.
    chart = SETUP.read_patient(api, base["patient"]["id"])
    check.assert_patient(
        chart,
        immunotherapy_escalation_step=2,
        immunotherapy_status=C.IMMUNO_STATUS_BUILD_UP,
    )
    check.assert_instant_equals(
        chart["last_dose_administered_at"], "2026-08-01T09:00:00Z"
    )

    # The re-draw therefore repeats step 2 at the same volume, with no gap accrued.
    replacement = SETUP.administer_dose(api, vial_id)
    check.assert_immunotherapy_dose(
        replacement,
        status=C.DOSE_ADMINISTERED,
        escalation_step_at_dose=2,
        gap_days_at_dose=0,
        observation_required_minutes=C.OBSERVATION_BASE_DOSE,
    )
    check.assert_volume_ml(replacement["volume_ml"], 0.10)

    # The voided draw is excluded from the ledger, so the totals match the two live doses.
    final = SETUP.read_vial(api, vial_id)
    check.assert_volume_ml(final["volume_ml_remaining"], 4.85)
    check.assert_volume_ml(final["volume_ml_dispensed_total"], 0.15)
    check.assert_volume_ml(final["volume_ml_wasted"], 0.00)
    check.assert_dose_volumes_sum_to_dispensed(
        [
            SETUP.read_dose(api, base["first_dose"]["id"]),
            SETUP.read_dose(api, voided["id"]),
            replacement,
        ],
        final,
    )


def test_void_sixteen_minutes_after_the_draw_is_refused_and_the_ledger_stands(api):
    """PRD 3.5: "The dose must still be `ADMINISTERED` with `observation_cleared_at` null,
    and no more than fifteen minutes may have elapsed since `administered_at`, or the void
    is refused with `ERR_VOID_WINDOW_CLOSED`."

    Design: Difficulty/compensating_invariant/vial_millilitre_ledger_conserved_across_dose_void
    """
    base = _vial_with_a_cleared_dose_and_a_fresh_draw(api)
    vial_id = base["vial"]["id"]

    # Sixteen minutes after the draw the compensating action is no longer available.
    SETUP.set_clock(api, "2026-08-01T09:46:00Z")
    response = api.void_immunotherapy_dose(
        base["second_dose"]["id"],
        F.dose_void_payload(void_reason=C.VOID_REASON_DRAWN_IN_ERROR),
        USERS.NURSE_1,
    )
    validate_error(response, ApiErrorId.VOID_WINDOW_CLOSED.value)

    # The refused void moved no millilitre in either direction.
    still = SETUP.read_vial(api, vial_id)
    check.assert_immunotherapy_vial(still, status=C.VIAL_IN_USE)
    check.assert_volume_ml(still["volume_ml_remaining"], 4.85)
    check.assert_volume_ml(still["volume_ml_dispensed_total"], 0.15)
    check.assert_volume_ml(still["volume_ml_wasted"], 0.00)

    held = SETUP.read_dose(api, base["second_dose"]["id"])
    check.assert_immunotherapy_dose(held, status=C.DOSE_ADMINISTERED)


def _third_dose_under_observation_with_downstream_rows(api):
    """A dose still under observation, plus the rows a tier change reaches.

    One prior systemic reaction with epinephrine on file puts the chart at 20
    points. An intradermal panel is left waiting in ORDERED and an endoscopy
    sits on the calendar for the fifth, so both are in place before any
    reaction is recorded. Two cleared doses lift the chart to step 3 and the
    third draw, stamped 10:00, is the one that will react.
    """
    base = SETUP.immunotherapy_ready_patient(
        api,
        plan_code="REACT-2999",
        patient_mrn=C.mrn(10071),
        policy_overrides={
            "payer_name": "Reaction Mutual",
            "observation_floor_minutes": 20,
        },
        patient_overrides={
            "full_name": "Cascade Patient",
            "date_of_birth": "1988-06-20",
            "epinephrine_on_file": True,
            "prior_systemic_reaction_count": 1,
        },
    )
    patient_id = base["patient"]["id"]
    check.assert_patient(
        base["patient"],
        risk_score=20,
        risk_score_variant=C.RISK_VARIANT_PROVISIONAL,
        supervision_tier=C.SUPERVISION_TIER_STANDARD,
    )

    base["order"] = SETUP.create_order(
        api,
        patient_id,
        panel_code=C.PANEL_MOLD_12,
        method=C.METHOD_INTRADERMAL,
    )
    scope = SETUP.register_scope(api, serial=C.scope_serial(1))
    base["scope"] = scope
    base["booking"] = SETUP.create_booking(
        api,
        patient_id,
        "2026-08-05T09:00:00Z",
        "2026-08-05T10:00:00Z",
        physician_user_id=C.USER_ENT_1,
        procedure_type=C.PROCEDURE_DIAGNOSTIC_ENDOSCOPY,
        venue=C.VENUE_IN_OFFICE_SUITE,
        headers=USERS.ENT_1,
        endoscope_asset_id=scope["id"],
    )

    stamps = ("09:00", "09:30", "10:00")
    doses = []
    for index in range(2):
        SETUP.set_clock(api, "2026-08-01T{0}:00Z".format(stamps[index]))
        dose = SETUP.administer_dose(api, base["vial"]["id"])
        doses.append(dose)
        SETUP.set_clock(api, "2026-08-01T{0}:00Z".format(stamps[index + 1]))
        SETUP.clear_dose(api, dose["id"])
    third = SETUP.administer_dose(api, base["vial"]["id"])
    doses.append(third)
    base["doses"] = doses
    base["held_dose"] = third
    return base


def test_grade_three_reaction_holds_the_dose_and_rolls_the_chart_back_two_steps(api):
    """PRD 3.4: "Hop two, caused by hop one, does three things to the patient:
    `immunotherapy_escalation_step` is rolled back to the dose's own
    `escalation_step_at_dose` less two, floored at 1; `immunotherapy_status` is set to
    `HELD`; and `risk_score_variant` is set to `POST_REACTION` with `risk_score`
    recomputed under that variant."

    Design: Difficulty/transitive_cascade/reaction_event_four_hop_cascade
    """
    base = _third_dose_under_observation_with_downstream_rows(api)
    check.assert_immunotherapy_dose(
        base["held_dose"], escalation_step_at_dose=3, status=C.DOSE_ADMINISTERED
    )

    # Ten minutes into observation the patient reacts at grade three.
    SETUP.set_clock(api, "2026-08-01T10:10:00Z")
    event = SETUP.record_reaction(
        api,
        3,
        10,
        dose_id=base["held_dose"]["id"],
        local_wheal_mm=22.0,
        epinephrine_given=True,
    )

    # The event is append-only evidence stamped from the clock.
    check.assert_reaction_event(
        event,
        systemic_grade=3,
        onset_minutes=10,
        epinephrine_given=True,
        allergy_test_order_id=None,
        immunotherapy_dose_id=base["held_dose"]["id"],
        recorded_by_user_id=C.USER_NURSE_1,
    )
    check.assert_instant_equals(event["occurred_at"], "2026-08-01T10:10:00Z")

    # Hop one holds the dose; hop two rewrites the chart's posture and score.
    held = SETUP.read_dose(api, base["held_dose"]["id"])
    check.assert_immunotherapy_dose(
        held,
        status=C.DOSE_REACTION_HELD,
        reaction_grade=3,
        escalation_step_at_dose=3,
        observation_cleared_at=None,
    )

    chart = SETUP.read_patient(api, base["patient"]["id"])
    check.assert_patient(
        chart,
        immunotherapy_escalation_step=1,
        immunotherapy_status=C.IMMUNO_STATUS_HELD,
        risk_score_variant=C.RISK_VARIANT_POST_REACTION,
        risk_score=80,
    )


def test_the_new_score_escalates_supervision_and_re_sizes_the_waiting_panel(api):
    """PRD 3.4: "Hop three fires only if hop two's new score reached 60 or more: the
    patient's `supervision_tier` becomes `PHYSICIAN_PRESENT`, and every allergy test order
    of that patient still sitting in status `ORDERED` has its
    `observation_required_minutes` re-derived — which, under the new `PHYSICIAN_PRESENT`
    tier, raises each of them to at least 90 minutes."

    Design: Difficulty/transitive_cascade/reaction_event_four_hop_cascade
    """
    base = _third_dose_under_observation_with_downstream_rows(api)

    # The waiting intradermal panel is sized at its own forty-minute base.
    check.assert_allergy_test_order(
        base["order"],
        status=C.ORDER_ORDERED,
        method=C.METHOD_INTRADERMAL,
        observation_required_minutes=C.OBSERVATION_BASE_INTRADERMAL,
    )

    SETUP.set_clock(api, "2026-08-01T10:10:00Z")
    SETUP.record_reaction(
        api,
        3,
        10,
        dose_id=base["held_dose"]["id"],
        local_wheal_mm=22.0,
        epinephrine_given=True,
    )

    # Eighty points carries the chart over the sixty-point supervision threshold.
    chart = SETUP.read_patient(api, base["patient"]["id"])
    check.assert_patient(
        chart,
        risk_score=80,
        supervision_tier=C.SUPERVISION_TIER_PHYSICIAN_PRESENT,
    )

    # The untouched panel is re-sized without leaving ORDERED.
    resized = SETUP.read_order(api, base["order"]["id"])
    check.assert_allergy_test_order(
        resized,
        status=C.ORDER_ORDERED,
        administered_at=None,
        observation_required_minutes=C.OBSERVATION_FLOOR_PHYSICIAN_PRESENT,
    )


def test_supervision_escalation_reaches_the_patients_vial_and_scheduled_booking(api):
    """PRD 3.4: "Hop four fires only because hop three changed the tier, and it reaches
    across two more aggregates: every extract vial of that patient in status
    `LABEL_VERIFIED` or `IN_USE` has `requires_supervised_administration` set to true, and
    every procedure booking of that patient in status `SCHEDULED` has
    `requires_physician_presence` set to true."

    Design: Difficulty/transitive_cascade/reaction_event_four_hop_cascade
    """
    base = _third_dose_under_observation_with_downstream_rows(api)

    # Neither downstream row demands a physician before the reaction.
    check.assert_immunotherapy_vial(
        SETUP.read_vial(api, base["vial"]["id"]),
        status=C.VIAL_IN_USE,
        requires_supervised_administration=False,
    )
    check.assert_procedure_booking(
        base["booking"],
        status=C.BOOKING_SCHEDULED,
        requires_physician_presence=False,
        attending_physician_user_id=None,
    )

    SETUP.set_clock(api, "2026-08-01T10:10:00Z")
    SETUP.record_reaction(
        api,
        3,
        10,
        dose_id=base["held_dose"]["id"],
        local_wheal_mm=22.0,
        epinephrine_given=True,
    )

    # The vial in use may no longer be drawn from unsupervised.
    check.assert_immunotherapy_vial(
        SETUP.read_vial(api, base["vial"]["id"]),
        status=C.VIAL_IN_USE,
        requires_supervised_administration=True,
    )

    # The endoscopy four days out acquires the presence requirement in place.
    check.assert_procedure_booking(
        SETUP.read_booking(api, base["booking"]["id"]),
        status=C.BOOKING_SCHEDULED,
        requires_physician_presence=True,
        physician_user_id=C.USER_ENT_1,
        attending_physician_user_id=None,
    )

    # The two doses already discharged are outside the cascade's reach.
    for dose in base["doses"][:2]:
        check.assert_immunotherapy_dose(
            SETUP.read_dose(api, dose["id"]), status=C.DOSE_CLEARED, reaction_grade=0
        )
