"""Difficulty-queue tests: transitive cascade chains."""
import pytest

from test_helpers import (
    COORDINATOR,
    SPECIALIST,
    activate_care_team_for,
    activate_enrollment,
    api_client,
    complete_visit,
    create_member_with_enrollment,
    create_scheduled_visit,
    drive_enrollment_to_consented,
    drive_visit_to_in_progress,
    get_care_team_row,
    get_measurement_for_member,
    get_success_data,
    make_clinician_headers,
    setup_active_enrollment,
    setup_basic_reference,
    unwrap_singleton,
    upsert_and_submit_assessment,
    validate_success,
)


# ---------------------------------------------------------------------------
# Difficulty/transitive_cascade/visit_complete_cascades_to_member_score_and_performance_measurement
# ---------------------------------------------------------------------------

def _setup_in_progress_visit_with_submitted_assessment():
    """ACTIVE enrollment; INITIAL_ASSESSMENT visit in IN_PROGRESS with a
    SUBMITTED assessment carrying the recipe's signal values."""
    ctx = setup_active_enrollment(member_overrides={
        "chronic_condition_codes": ["CHF"],
        "prior_ed_visits_12mo": 2,
        "prior_inpatient_admits_12mo": 1,
    })
    visit = create_scheduled_visit(
        ctx["enrollment"]["id"], visit_type="INITIAL_ASSESSMENT",
        start="2026-09-02T09:00:00Z", end="2026-09-02T10:00:00Z",
    )
    drive_visit_to_in_progress(visit)
    upsert_and_submit_assessment(visit, {
        "medication_reconciliation": {
            "medications_reviewed": 8,
            "discrepancies_found": 2,
            "high_risk_med_changes": 1,
        },
        "safety_evaluation": {
            "fall_risk_score": 4,
            "home_hazard_count": 2,
            "adl_impairment_count": 1,
        },
        "social_needs_screening": {
            "food_insecurity": True,
            "housing_instability": False,
            "transportation_barrier": True,
            "social_isolation_score": 3,
        },
        "pcp_coordination_note": "PCP informed.",
    })
    return ctx, visit


def test_complete_cascades_to_assessment_lock_and_member_score(api):
    """PRD section 3.5: "On success, the visit moves to `COMPLETED` and `actual_end` is stamped with the current logical clock. The assigned clinician's `active_daily_visit_count` decrements by 1. The assessment locks into `LOCKED` status, after which it is immutable. The member's `burden_score_final` is recomputed from the assessment (§3.5 continues below), and the member's `risk_tier` is re-derived from that final score using the same thresholds as the provisional derivation."

    Design: Difficulty/transitive_cascade/visit_complete_cascades_to_member_score_and_performance_measurement
    """
    ctx, visit = _setup_in_progress_visit_with_submitted_assessment()
    completed = validate_success(api.complete_visit(
        visit["id"], make_clinician_headers(visit["clinician_id"])
    ))
    assert completed["status"] == "COMPLETED"
    assert completed["actual_end"] is not None

    assessment_data = validate_success(api.get_assessment(visit["id"], COORDINATOR))
    assessment = unwrap_singleton(assessment_data)
    assert assessment["status"] == "LOCKED"
    assert assessment["pcp_notified"] is True

    member = get_success_data(api.get_member(ctx["member"]["id"], COORDINATOR))
    assert member["burden_score_final"] == 35
    assert member["risk_tier"] == "VERY_HIGH"

    clinician = get_success_data(api.get_clinician(ctx["np"]["id"], COORDINATOR))
    assert clinician["active_daily_visit_count"] == 0


def test_complete_cascades_to_performance_measurement(api):
    """PRD section 3.5: "Finally, the `PerformanceMeasurement` row for the contract, member, and current period has `visits_completed` incremented by 1, `pcp_coordination_rate` recomputed as the fraction of `COMPLETED` visits whose assessment has `pcp_notified` set to `true` (or 0 if no visits have completed), and `composite_score` recomputed per §3.7."
    PRD section 3.7: "The SLA component is `urgent_episodes_sla_met` divided by `urgent_episodes_triggered`, falling back to 1.0 when no urgent episodes have been triggered."

    Design: Difficulty/transitive_cascade/visit_complete_cascades_to_member_score_and_performance_measurement
    """
    ctx, visit = _setup_in_progress_visit_with_submitted_assessment()
    validate_success(api.complete_visit(
        visit["id"], make_clinician_headers(visit["clinician_id"])
    ))
    row = get_measurement_for_member(ctx["member"]["id"])
    assert row["visits_completed"] == 1
    assert row["pcp_coordination_rate"] == pytest.approx(1.0, abs=1e-9)
    assert row["composite_score"] == pytest.approx(1.0, abs=1e-9)


# ---------------------------------------------------------------------------
# Difficulty/transitive_cascade/enrollment_disenroll_cascades_to_visits_and_care_team_and_performance
# ---------------------------------------------------------------------------

def _setup_active_enrollment_with_two_visits():
    ctx = setup_active_enrollment()
    enr_id = ctx["enrollment"]["id"]
    v1 = create_scheduled_visit(
        enr_id, start="2026-09-02T09:00:00Z", end="2026-09-02T10:00:00Z"
    )
    v2 = create_scheduled_visit(
        enr_id, start="2026-09-03T09:00:00Z", end="2026-09-03T10:00:00Z"
    )
    return ctx, v1, v2


def test_disenroll_cancels_scheduled_visits_with_enrollment_ended(api):
    """PRD section 3.7: "When an `ACTIVE` enrollment disenrolls, every `SCHEDULED` visit child of the enrollment cascades to `CANCELLED` with `cancellation_reason` set to `ENROLLMENT_ENDED`, and each cascaded cancellation decrements its assigned clinician's `active_daily_visit_count` by 1."

    Design: Difficulty/transitive_cascade/enrollment_disenroll_cascades_to_visits_and_care_team_and_performance
    """
    ctx, v1, v2 = _setup_active_enrollment_with_two_visits()
    before = get_success_data(api.get_clinician(ctx["np"]["id"], COORDINATOR))
    assert before["active_daily_visit_count"] == 2

    disenrolled = validate_success(api.disenroll(
        ctx["enrollment"]["id"], {"disenrollment_reason": "MEMBER_REQUEST"}, SPECIALIST
    ))
    assert disenrolled["status"] == "DISENROLLED"
    assert disenrolled["is_current"] is False

    for v in (v1, v2):
        after = validate_success(api.get_visit(v["id"], COORDINATOR))
        assert after["status"] == "CANCELLED"
        assert after["cancellation_reason"] == "ENROLLMENT_ENDED"

    clinician = get_success_data(api.get_clinician(ctx["np"]["id"], COORDINATOR))
    assert clinician["active_daily_visit_count"] == 0


def test_disenroll_retires_care_team(api):
    """PRD section 3.7: "The care team for the enrollment cascades to `RETIRED` — this is the only path by which a care team reaches `RETIRED`, and it fires whether the team was `DRAFT`, `ACTIVE`, or `SUSPENDED`."

    Design: Difficulty/transitive_cascade/enrollment_disenroll_cascades_to_visits_and_care_team_and_performance
    """
    ctx, _v1, _v2 = _setup_active_enrollment_with_two_visits()
    validate_success(api.disenroll(
        ctx["enrollment"]["id"], {"disenrollment_reason": "MEMBER_REQUEST"}, SPECIALIST
    ))
    team = get_care_team_row(ctx["enrollment"]["id"])
    assert team["status"] == "RETIRED"
