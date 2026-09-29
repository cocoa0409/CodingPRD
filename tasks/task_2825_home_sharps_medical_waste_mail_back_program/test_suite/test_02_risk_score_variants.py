"""One non-conformance history read through two different lenses: the decaying
`screening_risk_score` and the unforgiving, lateness-penalising `audit_risk_score`."""

from test_helpers import (
    add_screened_kit_cycle,
    assert_auto_ship_run,
    assert_enrollment,
    assert_patient_risk,
    auto_ship_run_payload,
    get_success_data,
    issue_kit_for,
    read_enrollment,
    read_kit,
    read_patient,
    set_clock,
    setup_screened_shipment,
)


def _run_checkpoint(api, headers, as_of_date):
    return get_success_data(api.create_auto_ship_run(auto_ship_run_payload(as_of_date), headers))


# --------------------------------------------------------------------------
# One 25-point event aged 92 days plus one overdue kit
# --------------------------------------------------------------------------
def _one_overfill_event_and_one_overdue_kit(api):
    """Screen kit 1 non-conforming for OVERFILLED_CONTAINER on 2026-08-01, issue a
    second kit on 2026-08-15 and never acknowledge it, then move the clock to
    2026-11-01 so the event is 92 days old and the second kit is overdue."""
    ctx = setup_screened_shipment(
        api, outcome="NON_CONFORMING", reason_code="OVERFILLED_CONTAINER"
    )
    set_clock(api, "2026-08-15T00:00:00Z")
    ctx["overdue_kit"] = issue_kit_for(api, ctx)
    set_clock(api, "2026-11-01T00:00:00Z")
    return ctx


def test_01_screening_variant_halves_an_event_in_the_ninety_one_to_one_eighty_day_band(api, program_admin_headers):
    """The single OVERFILLED_CONTAINER event weighs 25 and is 92 complete days old,
    so it contributes 12.5, and the one exact total is rounded half up to 13.

    PRD 3.9: "An event aged at most 90 days contributes its full weight; an event aged from 91 through 180 days inclusive contributes half its weight; an event aged more than 180 days contributes nothing."
    PRD 3.9: "The discounted contributions are summed **exactly**, keeping halves intact, and the single total is then rounded half up to a whole number; the result is capped at 100."

    Design: Difficulty/dual_variant_calc/patient_risk_screening_variant_vs_audit_variant_divergence
    """
    ctx = _one_overfill_event_and_one_overdue_kit(api)

    _run_checkpoint(api, program_admin_headers, "2026-11-01")

    patient = read_patient(api, ctx["patient"]["id"])
    assert_patient_risk(patient, screening_risk_score=13)


def test_02_audit_variant_keeps_the_full_weight_and_adds_the_late_kit_penalty(api, program_admin_headers):
    """The audit lens applies no decay, so the same event weighs its full 25, and the
    kit still sitting in ISSUED past its seal deadline adds 10, giving 35.

    PRD 3.9: "Every event contributes its full weight with no age discount at all. Added to that sum is a penalty of 10 points for each **late kit**, where a late kit is one of the patient's kits still in `ISSUED` or `ACTIVE_FILLING` whose `seal_deadline_date` falls strictly before the current logical-clock UTC date."

    Design: Difficulty/dual_variant_calc/patient_risk_screening_variant_vs_audit_variant_divergence
    """
    ctx = _one_overfill_event_and_one_overdue_kit(api)

    _run_checkpoint(api, program_admin_headers, "2026-11-01")

    patient = read_patient(api, ctx["patient"]["id"])
    assert_patient_risk(patient, audit_risk_score=35)


def test_03_the_two_lenses_diverge_by_twenty_two_points_on_identical_rows(api, program_admin_headers):
    """Both readings are stored on the same patient row and differ by 22 points, and
    because only the screening reading can suspend, the patient stays ENROLLED.

    PRD 3.9: "Because the two readings apply different lenses to the same events, they routinely return different integers for the same patient, and only the audit reading can be pushed over the threshold by lateness alone."
    PRD 3.9: "When an auto-ship run finds `audit_risk_score` at 60 or above, the run merely skips that enrollment and never writes the patient's `status` at all."

    Design: Difficulty/dual_variant_calc/patient_risk_screening_variant_vs_audit_variant_divergence
    """
    ctx = _one_overfill_event_and_one_overdue_kit(api)

    _run_checkpoint(api, program_admin_headers, "2026-11-01")

    patient = read_patient(api, ctx["patient"]["id"])
    assert patient["audit_risk_score"] - patient["screening_risk_score"] == 22
    assert_patient_risk(patient, status="ENROLLED")


def test_04_seal_deadline_is_the_issue_date_plus_cadence_plus_fourteen_day_grace(api):
    """The second kit was issued on 2026-08-15 under a 30-day cadence, so its seal
    deadline is 44 days later, which is what makes it late by 2026-11-01.

    PRD 3.4: "Its `seal_deadline_date` is the UTC calendar date of `issued_at` advanced by the enrollment's `cadence_days` plus a 14-day grace period; a kit still unsealed after that date is a late kit for audit purposes."

    Design: Difficulty/dual_variant_calc/patient_risk_screening_variant_vs_audit_variant_divergence
    """
    ctx = _one_overfill_event_and_one_overdue_kit(api)

    kit = read_kit(api, ctx["overdue_kit"]["id"])
    assert kit["status"] == "ISSUED"
    assert kit["seal_deadline_date"] == "2026-09-28"


def test_05_an_unreturned_kit_is_skipped_as_unfilled_rather_than_as_risky(api, program_admin_headers):
    """The enrollment is due and the audit score of 35 is under the threshold, so the
    run reaches the third skip reason: the most recent kit is still in ISSUED.

    PRD 3.9: "Third, **unfilled**: if the enrollment's most recent kit by creation time is still in `ISSUED` or `ACTIVE_FILLING`, `kits_skipped_unfilled` rises by 1 — the household has not yet returned what it already has."

    Design: Difficulty/dual_variant_calc/patient_risk_screening_variant_vs_audit_variant_divergence
    """
    _one_overfill_event_and_one_overdue_kit(api)

    run = _run_checkpoint(api, program_admin_headers, "2026-11-01")

    assert_auto_ship_run(
        run,
        kits_created=0,
        kits_skipped_unfilled=1,
        kits_skipped_risk=0,
    )


# --------------------------------------------------------------------------
# Two odd weights, both half-decayed: sum once, round once
# --------------------------------------------------------------------------
def _two_odd_weight_events_in_the_half_decay_band(api):
    """Screen one LOOSE_SHARPS_IN_BOX event (45) on 2026-08-01 and one
    OVERFILLED_CONTAINER event (25) on 2026-08-02, then move the clock to
    2026-11-01 so the two events are 92 and 91 days old respectively."""
    ctx = setup_screened_shipment(
        api, outcome="NON_CONFORMING", reason_code="LOOSE_SHARPS_IN_BOX"
    )
    set_clock(api, "2026-08-02T00:00:00Z")
    add_screened_kit_cycle(
        api,
        ctx,
        outcome="NON_CONFORMING",
        reason_code="OVERFILLED_CONTAINER",
        scheduled_intake_date="2026-08-11",
    )
    set_clock(api, "2026-11-01T00:00:00Z")
    return ctx


def test_06_two_half_weighted_odd_weights_are_summed_before_the_single_rounding(api, program_admin_headers):
    """22.5 and 12.5 sum exactly to 35.0, which rounds to 35. Rounding each
    contribution first would give 23 + 13 = 36, a full point too high.

    PRD 3.9: "The discounted contributions are summed **exactly**, keeping halves intact, and the single total is then rounded half up to a whole number; the result is capped at 100."
    PRD 3.9: "Rounding each discounted contribution before summing is a different and forbidden order — two half-weighted odd weights differ from the correct answer by a full point."

    Design: Difficulty/combinatorial_formula/risk_score_sum_then_single_round_not_per_term_round
    """
    ctx = _two_odd_weight_events_in_the_half_decay_band(api)

    _run_checkpoint(api, program_admin_headers, "2026-11-01")

    patient = read_patient(api, ctx["patient"]["id"])
    assert patient["screening_risk_score"] == 35
    assert patient["screening_risk_score"] != 36


def test_07_the_audit_lens_reads_the_same_two_events_at_their_full_undecayed_weight(api, program_admin_headers):
    """Neither event is discounted for age and both kits came back, so the audit score
    is the plain sum 45 + 25 with no lateness penalty at all.

    PRD 3.9: "Every event contributes its full weight with no age discount at all."
    PRD 3.9: "Each event contributes a weight determined by its `reason_code`: `LOOSE_SHARPS_IN_BOX` weighs 45, `UNAPPROVED_WASTE_TYPE` weighs 40, `UNSEALED_CONTAINER` weighs 30, `OVERFILLED_CONTAINER` weighs 25, `WEIGHT_EXCEEDS_SPEC` weighs 20 and `MISSING_ABSORBENT` weighs 15."

    Design: Difficulty/combinatorial_formula/risk_score_sum_then_single_round_not_per_term_round
    """
    ctx = _two_odd_weight_events_in_the_half_decay_band(api)

    _run_checkpoint(api, program_admin_headers, "2026-11-01")

    patient = read_patient(api, ctx["patient"]["id"])
    assert_patient_risk(patient, audit_risk_score=70)


def test_08_the_undecayed_seventy_crossed_the_threshold_at_screening_time(api):
    """At the moment of the second screening both events were brand new, so the
    recomputed screening score was 70 and the patient was suspended, which paused the
    enrollment.

    PRD 3.7: "Third, and only when that recomputed score reaches at least 60 while the patient is `ENROLLED`, the patient is suspended, which is itself a multi-hop cascade covered in §3.9."
    PRD 3.9: "The second hop moves every enrollment of that patient whose status is `ACTIVE` to `PAUSED`."

    Design: Difficulty/combinatorial_formula/risk_score_sum_then_single_round_not_per_term_round
    """
    ctx = _two_odd_weight_events_in_the_half_decay_band(api)

    patient = read_patient(api, ctx["patient"]["id"])
    assert patient["status"] == "SUSPENDED"
    assert_enrollment(read_enrollment(api, ctx["enrollment"]["id"]), status="PAUSED")


def test_09_a_paused_enrollment_is_out_of_the_checkpoint_walk_entirely(api, program_admin_headers):
    """The run still refreshes both scores for the suspended patient, but the paused
    enrollment is never inspected, so `enrollments_evaluated` stays at 0 and no skip
    counter moves.

    PRD 3.9: "The run then walks the enrollments whose status is `ACTIVE`, and only those — `DRAFT`, `PENDING_SPONSOR_APPROVAL`, `PAUSED`, `REJECTED` and `TERMINATED` enrollments are out of scope entirely — in ascending order of enrollment creation time."

    Design: Difficulty/combinatorial_formula/risk_score_sum_then_single_round_not_per_term_round
    """
    _two_odd_weight_events_in_the_half_decay_band(api)

    run = _run_checkpoint(api, program_admin_headers, "2026-11-01")

    assert_auto_ship_run(
        run,
        enrollments_evaluated=0,
        kits_created=0,
        kits_skipped_not_due=0,
        kits_skipped_risk=0,
    )
