"""Inclusive thresholds, count gates at exactly one, and both attainment clamps."""

from test_helpers import (
    ApiErrorId,
    AttainmentStatus,
    CandidateStatus,
    CycleStatus,
    InterviewStatus,
    ObjectiveStatus,
    add_candidate,
    add_indicator,
    add_internal_party,
    add_interview,
    advance_to,
    assert_close,
    build_scenario,
    complete_interview,
    create_cycle,
    make_indicator_sufficient,
    score_candidate,
    validate_error,
    validate_success,
)
from test_helpers import constants as C
from test_helpers import factories as F


def _two_candidate_cycle(api):
    """Two identically evidenced indicators differing only in capacity score."""
    cycle = create_cycle(api)
    advance_to(api, cycle["id"], CycleStatus.DATA_COLLECTION)
    ids = []
    for name in ("Adult depression prevalence", "Adult anxiety prevalence"):
        indicator = add_indicator(api, cycle["id"], name=name)
        make_indicator_sufficient(
            api, indicator["id"], overall_value=12.0, high_value=14.0, low_value=10.0
        )
        ids.append(indicator["id"])
    facilitator = add_internal_party(api)["id"]
    advance_to(api, cycle["id"], CycleStatus.INPUT_GATHERING)
    interview = add_interview(api, cycle["id"], facilitator)
    complete_interview(api, interview["id"], rating=4, attendee_count=10)
    advance_to(api, cycle["id"], CycleStatus.PRIORITIZATION)
    candidates = []
    for indicator_id, capacity in ((ids[0], 70), (ids[1], 69.96)):
        candidate = add_candidate(
            api, cycle["id"], indicator_id, hospital_capacity_score=capacity
        )
        candidates.append(score_candidate(api, candidate["id"])["id"])
    return cycle, candidates


def test_a_composite_of_exactly_sixty_is_selectable(api):
    """PRD §3.4: "Finally it requires `composite_score` to be at least 60.00 — a
    score of exactly 60.00 passes — and rejects anything lower with
    `ERR_PRIORITY_SCORE_BELOW_THRESHOLD`."

    Design: Difficulty/boundary_precision_check/candidate_select_at_exactly_sixty_composite_is_allowed
    """
    cycle, candidates = _two_candidate_cycle(api)

    on_threshold = validate_success(api.get_candidate(candidates[0]))
    assert_close(on_threshold["severity_input"], 50.00, "severity_input")
    assert_close(on_threshold["disparity_points"], 40.00, "disparity_points")
    assert_close(on_threshold["community_concern_index"], 80.00, "community_concern_index")
    # 0.25 * (50.00 + 40.00 + 80.00 + 70) = 60.00 exactly.
    assert_close(on_threshold["composite_score"], 60.00, "composite_score")

    selected = validate_success(
        api.select_candidate(
            candidates[0], "Composite sits exactly on the statutory selection threshold"
        )
    )
    assert selected["status"] == CandidateStatus.SELECTED
    assert validate_success(api.get_cycle(cycle["id"]))["selected_priority_count"] == 1


def test_a_composite_one_hundredth_below_the_threshold_is_refused(api):
    """PRD §2.9: "a single rounding is applied to a weighted sum rather than to
    each of its terms, and a ceiling or floor clamp is applied *after* rounding
    rather than before."

    Design: Difficulty/boundary_precision_check/candidate_select_at_exactly_sixty_composite_is_allowed
    """
    _cycle, candidates = _two_candidate_cycle(api)

    below = validate_success(api.get_candidate(candidates[1]))
    # 0.25 * (50.00 + 40.00 + 80.00 + 69.96) = 59.99.
    assert_close(below["composite_score"], 59.99, "composite_score")

    validate_error(
        api.select_candidate(candidates[1], "Attempted selection one hundredth below"),
        ApiErrorId.PRIORITY_SCORE_BELOW_THRESHOLD,
    )
    after = validate_success(api.get_candidate(candidates[1]))
    assert after["status"] == CandidateStatus.SCORED
    assert after["selection_rationale"] is None


def test_neither_a_scheduled_nor_a_cancelled_session_counts_as_community_input(api):
    """PRD §3.1: "Leaving `INPUT_GATHERING` requires `completed_interview_count`
    to be at least 1, so that no prioritization happens without community voice;
    the failure is `ERR_NO_COMMUNITY_INPUT`."

    Design: Difficulty/boundary_precision_check/advance_to_prioritization_with_zero_completed_interviews_rejected
    """
    sc = build_scenario(api, stage="INPUT_GATHERING")
    second = add_interview(
        api,
        sc.cycle_id,
        sc.facilitator_party_id,
        organization_name="Northside Resident Coalition",
        starts_at="2026-04-07T14:00:00Z",
        ends_at="2026-04-07T15:00:00Z",
    )
    assert sc.cycle()["completed_interview_count"] == 0

    validate_error(
        api.advance_cycle(sc.cycle_id, CycleStatus.PRIORITIZATION),
        ApiErrorId.NO_COMMUNITY_INPUT,
    )
    assert sc.cycle()["status"] == CycleStatus.INPUT_GATHERING

    cancelled = validate_success(
        api.cancel_interview(second["id"], "Organization withdrew before the session")
    )
    assert cancelled["status"] == InterviewStatus.CANCELLED

    # A cancelled session is not community input.
    validate_error(
        api.advance_cycle(sc.cycle_id, CycleStatus.PRIORITIZATION),
        ApiErrorId.NO_COMMUNITY_INPUT,
    )


def test_exactly_one_completed_session_satisfies_the_gate_and_closes_the_window(api):
    """PRD §3.1: "Reaching `PRIORITIZATION` closes the interview scheduling
    window: from that point on, scheduling a *new* session on the cycle is
    rejected with `ERR_INPUT_WINDOW_CLOSED`, while completing or cancelling a
    session that was already `SCHEDULED` remains permitted."

    Design: Difficulty/boundary_precision_check/advance_to_prioritization_with_zero_completed_interviews_rejected
    """
    sc = build_scenario(api, stage="INPUT_GATHERING")

    completed = complete_interview(api, sc.interview_id)
    assert completed["status"] == InterviewStatus.COMPLETED
    assert sc.cycle()["completed_interview_count"] == 1

    advanced = validate_success(api.advance_cycle(sc.cycle_id, CycleStatus.PRIORITIZATION))
    assert advanced["status"] == CycleStatus.PRIORITIZATION

    validate_error(
        api.create_interview(
            F.interview_payload(
                sc.cycle_id,
                sc.facilitator_party_id,
                organization_name="Northside Resident Coalition",
                starts_at="2026-04-08T14:00:00Z",
                ends_at="2026-04-08T15:00:00Z",
            )
        ),
        ApiErrorId.INPUT_WINDOW_CLOSED,
    )


def test_attainment_of_exactly_one_hundred_is_met_and_one_unit_short_is_partial(api):
    """PRD §3.8: "The derived `attainment_status` then reads off three inclusive
    bands: `MET` when `attainment_pct` is at least 100.00, `PARTIAL` when it is at
    least 50.00 but below 100.00, and `NOT_MET` when it is below 50.00. Exactly
    100.00 is `MET` and exactly 50.00 is `PARTIAL`."

    Design: Difficulty/boundary_precision_check/objective_attainment_exactly_100_marks_met_and_clamps_both_ends
    """
    sc = build_scenario(api, stage="ADOPTED")
    assert sc.objective()["attainment_status"] == AttainmentStatus.PENDING

    near = validate_success(
        api.report_progress(sc.objective_id, F.report_progress_payload(2399, "2027-05-01"))
    )
    # (2399 - 1200) / 1200 * 100 = 99.9166... -> 99.92.
    assert_close(near["attainment_pct"], 99.92, "attainment_pct")
    assert near["attainment_status"] == AttainmentStatus.PARTIAL

    exact = validate_success(
        api.report_progress(sc.objective_id, F.report_progress_payload(2400, "2027-05-15"))
    )
    assert_close(exact["attainment_pct"], 100.00, "attainment_pct")
    assert exact["attainment_status"] == AttainmentStatus.MET
    assert exact["status"] == ObjectiveStatus.ACTIVE


def test_attainment_clamps_at_both_ends_after_rounding(api):
    """PRD §3.8: "that raw figure is rounded half up to two decimal places, and
    the rounded figure is then clamped into the range from 0.00 to 150.00 — the
    clamp is applied after the rounding, never before, and 150.00 is the highest
    `attainment_pct` the system will record no matter how far the measure
    over-shot."

    Design: Difficulty/boundary_precision_check/objective_attainment_exactly_100_marks_met_and_clamps_both_ends
    """
    sc = build_scenario(api, stage="ADOPTED")

    over = validate_success(
        api.report_progress(sc.objective_id, F.report_progress_payload(3900, "2027-06-01"))
    )
    # Raw 225.00 clamped to the ceiling.
    assert_close(over["attainment_pct"], C.ATTAINMENT_CEILING, "attainment_pct")
    assert over["attainment_status"] == AttainmentStatus.MET

    under = validate_success(
        api.report_progress(sc.objective_id, F.report_progress_payload(1199, "2027-06-15"))
    )
    # Raw -0.08 clamped at zero; never reported as a negative percentage.
    assert_close(under["attainment_pct"], C.ATTAINMENT_FLOOR, "attainment_pct")
    assert under["attainment_status"] == AttainmentStatus.NOT_MET

    objective = sc.objective()
    assert objective["status"] == ObjectiveStatus.ACTIVE
    assert_close(objective["baseline_value"], C.OBJECTIVE_BASELINE_VALUE, "baseline_value")
    assert_close(objective["actual_value"], 1199, "actual_value")
    assert objective["as_of_date"] == "2027-06-15"
