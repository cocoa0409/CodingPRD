"""Multi-hop cascades: a hospitalization hold and an upheld reduction appeal.

Both flows start with one write and end several rows away, and the PRD insists
the chain runs to its end - a cascade that stops after the first hop is a defect.
"""

from prd_bench_local_runner.testing import validate_success

from test_helpers import factories as f
from test_helpers import fixtures as fx
from test_helpers.assertions import assert_hours, assert_ratio
from test_helpers.test_users import CASE_MANAGER, SCHEDULER
from test_helpers.types import (
    AssignmentCancelReason,
    AssignmentStatus,
    AuthorizationStatus,
    CaseStatus,
    DisputeOutcome,
    DisputeStatus,
    DisputeType,
    HoldReason,
    IncidentStatus,
    PatientStatus,
    ShiftCancelReason,
    StaffingStatus,
)


def _two_assigned_future_shifts(api):
    """960 committed minutes: two 8-hour shifts later in the same ISO week."""
    base = fx.setup_baseline(api)
    shift1 = fx.publish_shift(
        api, base.case_id, "2026-08-05T08:00:00Z", "2026-08-05T16:00:00Z"
    )
    assignment1 = fx.assign_nurse(api, shift1["id"], base.nurse_id)
    shift2 = fx.publish_shift(
        api, base.case_id, "2026-08-06T08:00:00Z", "2026-08-06T16:00:00Z"
    )
    assignment2 = fx.assign_nurse(api, shift2["id"], base.nurse_id)
    return base, (shift1, shift2), (assignment1, assignment2)


def test_hospitalization_report_hospitalizes_the_patient_and_holds_the_case(api):
    """A HOSPITALIZATION report records `triggered_case_hold` true, sets the
    patient to HOSPITALIZED, and drives the case ACTIVE -> ON_HOLD with
    `hold_reason` HOSPITALIZATION and `hold_incident_report_id` pointing at the
    report - hops zero through two of the chain.

    Design: Difficulty/transitive_cascade/hospitalization_incident_cascades_four_hops_to_nurse_minutes
    """
    base, _shifts, _assignments = _two_assigned_future_shifts(api)

    incident = fx.file_incident(api, base.case_id, "2026-08-03T05:00:00Z")

    assert incident["status"] == IncidentStatus.OPEN.value, incident
    assert incident["triggered_case_hold"] is True, incident

    patient = validate_success(api.get_patient(base.patient_id, CASE_MANAGER))
    assert patient["status"] == PatientStatus.HOSPITALIZED.value, patient

    case = fx.refresh_case(api, base.case_id)
    assert case["status"] == CaseStatus.ON_HOLD.value, case
    assert case["hold_reason"] == HoldReason.HOSPITALIZATION.value, case
    assert case["hold_incident_report_id"] == incident["id"], case


def test_the_hold_cancels_both_future_shifts_and_their_active_assignments(api):
    """Because the case entered ON_HOLD, every shift of the case starting at or
    after the clock becomes CANCELLED with `cancel_reason` CASE_HOLD, and each
    such shift's ACTIVE assignment is cancelled with the matching reason.

    Design: Difficulty/transitive_cascade/hospitalization_incident_cascades_four_hops_to_nurse_minutes
    """
    base, shifts, assignments = _two_assigned_future_shifts(api)

    fx.file_incident(api, base.case_id, "2026-08-03T05:00:00Z")

    for shift in shifts:
        reread = fx.refresh_shift(api, shift["id"])
        assert reread["staffing_status"] == StaffingStatus.CANCELLED.value, reread
        assert reread["cancel_reason"] == ShiftCancelReason.CASE_HOLD.value, reread

    for assignment in assignments:
        reread = validate_success(api.get_assignment(assignment["id"], SCHEDULER))
        assert reread["status"] == AssignmentStatus.CANCELLED.value, reread
        assert reread["cancel_reason"] == AssignmentCancelReason.CASE_HOLD.value, reread


def test_the_cascade_reaches_the_nurse_authorization_and_case_aggregates(api):
    """The final hop re-derives the aggregates the cancellations invalidated: the
    nurse's `scheduled_minutes_this_week` falls 960 -> 0, the authorization's
    `hours_committed_this_week` falls 16.00 -> 0.00 with 40.00 remaining, and the
    case's `unfilled_shift_count` is 0 with `fill_rate` exactly 1.0000 because no
    forward non-cancelled shift is left.

    Design: Difficulty/transitive_cascade/hospitalization_incident_cascades_four_hops_to_nurse_minutes
    """
    base, _shifts, _assignments = _two_assigned_future_shifts(api)

    assert fx.refresh_nurse(api, base.nurse_id)["scheduled_minutes_this_week"] == 960
    assert_hours(fx.refresh_authorization(api, base), "hours_committed_this_week", 16.00)

    fx.file_incident(api, base.case_id, "2026-08-03T05:00:00Z")

    assert fx.refresh_nurse(api, base.nurse_id)["scheduled_minutes_this_week"] == 0
    authorization = fx.refresh_authorization(api, base)
    assert_hours(authorization, "hours_committed_this_week", 0.00)
    assert_hours(authorization, "hours_remaining_this_week", 40.00)

    case = fx.refresh_case(api, base.case_id)
    assert case["unfilled_shift_count"] == 0, case
    assert_ratio(case, "fill_rate", 1.0000)


def _reduction_appeal_under_review(api):
    """1920 committed minutes across four 8-hour shifts, a noticed reduction to
    24 h/wk, and a REDUCTION_APPEAL taken under review."""
    base = fx.setup_baseline(api)
    shifts = []
    assignments = []
    for day in ("03", "04", "05", "06"):
        shift = fx.publish_shift(
            api, base.case_id, f"2026-08-{day}T08:00:00Z", f"2026-08-{day}T16:00:00Z"
        )
        shifts.append(shift)
        assignments.append(fx.assign_nurse(api, shift["id"], base.nurse_id))

    validate_success(
        api.reduce_authorization(
            base.authorization_id,
            f.reduce_payload(24.00, "utilization review lowered the ordered hours"),
            base.payer_headers,
        )
    )
    dispute = validate_success(
        api.create_dispute(
            f.dispute_payload(
                base.authorization_id,
                40.00,
                dispute_type=DisputeType.REDUCTION_APPEAL.value,
                reason="the child still needs continuous vent support",
            ),
            CASE_MANAGER,
        ),
        201,
    )
    validate_success(api.review_dispute(dispute["id"], base.payer_headers))
    return base, shifts, assignments, dispute


def test_upholding_a_reduction_appeal_lowers_the_grant_and_clears_the_notice(api):
    """UPHELD is terminal for the dispute with `decided_hours_per_week` null, and
    it sets `approved_hours_per_week` to the stored `noticed_hours_per_week`,
    clears `noticed_hours_per_week` and `reduction_effective_at`, and moves the
    authorization UNDER_APPEAL -> REDUCED.

    Design: Difficulty/transitive_cascade/reduction_appeal_upheld_trims_one_shift_in_waterfall_order
    """
    base, _shifts, _assignments, dispute = _reduction_appeal_under_review(api)

    decided = validate_success(
        api.decide_dispute(
            dispute["id"],
            f.decide_dispute_payload(
                DisputeOutcome.UPHELD.value,
                decision_note="reduction stands after clinical review",
            ),
            base.payer_headers,
        )
    )

    assert decided["status"] == DisputeStatus.UPHELD.value, decided
    assert decided["decided_hours_per_week"] is None, decided

    authorization = fx.refresh_authorization(api, base)
    assert authorization["status"] == AuthorizationStatus.REDUCED.value, authorization
    assert_hours(authorization, "approved_hours_per_week", 24.00)
    assert authorization["noticed_hours_per_week"] is None, authorization
    assert authorization["reduction_effective_at"] is None, authorization


def test_the_trim_waterfall_cancels_only_the_latest_starting_assigned_shift(api):
    """With 1920 committed minutes against the new 1440-minute target the loop
    cancels the candidate with the greatest `start_at` - the 2026-08-06 shift -
    with `cancel_reason` AUTH_REDUCTION, then re-evaluates, finds the week at the
    target and stops, leaving the three earlier shifts ASSIGNED.

    Design: Difficulty/transitive_cascade/reduction_appeal_upheld_trims_one_shift_in_waterfall_order
    """
    base, shifts, assignments, dispute = _reduction_appeal_under_review(api)

    validate_success(
        api.decide_dispute(
            dispute["id"],
            f.decide_dispute_payload(DisputeOutcome.UPHELD.value),
            base.payer_headers,
        )
    )

    victim = fx.refresh_shift(api, shifts[3]["id"])
    assert victim["staffing_status"] == StaffingStatus.CANCELLED.value, victim
    assert victim["cancel_reason"] == ShiftCancelReason.AUTH_REDUCTION.value, victim

    for shift in shifts[:3]:
        survivor = fx.refresh_shift(api, shift["id"])
        assert survivor["staffing_status"] == StaffingStatus.ASSIGNED.value, survivor

    cancelled = validate_success(api.get_assignment(assignments[3]["id"], SCHEDULER))
    assert cancelled["status"] == AssignmentStatus.CANCELLED.value, cancelled
    assert cancelled["cancel_reason"] == AssignmentCancelReason.AUTH_REDUCTION.value, cancelled

    kept = validate_success(api.get_assignment(assignments[0]["id"], SCHEDULER))
    assert kept["status"] == AssignmentStatus.ACTIVE.value, kept


def test_the_trim_leaves_every_aggregate_exactly_on_the_new_target(api):
    """After the cascade the nurse holds 1440 scheduled minutes, the authorization
    reports 24.00 committed and 0.00 remaining hours, and the cancelled shift
    leaves both sides of the fill rate, which stays 1.0000 with no unfilled shift.

    Design: Difficulty/transitive_cascade/reduction_appeal_upheld_trims_one_shift_in_waterfall_order
    """
    base, _shifts, _assignments, dispute = _reduction_appeal_under_review(api)

    validate_success(
        api.decide_dispute(
            dispute["id"],
            f.decide_dispute_payload(DisputeOutcome.UPHELD.value),
            base.payer_headers,
        )
    )

    assert fx.refresh_nurse(api, base.nurse_id)["scheduled_minutes_this_week"] == 1440
    authorization = fx.refresh_authorization(api, base)
    assert_hours(authorization, "hours_committed_this_week", 24.00)
    assert_hours(authorization, "hours_remaining_this_week", 0.00)

    case = fx.refresh_case(api, base.case_id)
    assert case["unfilled_shift_count"] == 0, case
    assert_ratio(case, "fill_rate", 1.0000)
