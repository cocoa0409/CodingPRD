"""Single calls whose effects run four levels deep.

Suspending an agreement voids its proposals, requeues their requests and
re-derives three conserved counters.  Failing a final assessment pends a
removal, holds the remaining calendar and re-prices the supervisor's caseload.
Each cascade is asserted hop by hop, including the hops that must *not* fire.
"""
from test_helpers import (
    ASSESSMENT_SCORER,
    PROGRAM_ADMIN,
    assert_agreement_ledger,
    assert_caseload,
    assert_placement_dimensions,
    assert_ratio_equals,
    assert_stipend,
    factories as f,
    open_assessment,
    read_agreement,
    read_assessment,
    read_cycle,
    read_placement,
    read_request,
    read_supervisor,
    read_teacher,
    schedule_cycle,
    set_clock,
    setup_observed_placement,
    setup_proposed_placement,
    submit_assessment,
    validate_success,
)

FOURTH_CYCLE = (4, "FORMATIVE", "2026-11-30T00:00:00Z", "2026-12-05T00:00:00Z")
FAILING_SCORES = {
    "task_planning": 4.0,
    "task_instruction": 3.5,
    "task_assessment": 3.0,
    "task_professionalism": 2.5,
}


def _assessment_on_its_final_attempt(api):
    """An observed placement whose assessment has been returned once and resubmitted."""
    scenario = setup_observed_placement(api)
    scenario.cycles.append(schedule_cycle(api, scenario.placement_id, *FOURTH_CYCLE))
    scenario.assessment = open_assessment(api, scenario.placement_id)
    set_clock(api, "2026-11-18T09:00:00Z")
    submit_assessment(api, scenario.assessment_id, scenario.candidate_id)
    validate_success(api.score_assessment(
        scenario.assessment_id,
        f.assessment_return_payload(
            returned_feedback="Assessment-of-learning evidence is thin."),
        ASSESSMENT_SCORER))
    set_clock(api, "2026-11-20T09:00:00Z")
    scenario.assessment = submit_assessment(api, scenario.assessment_id,
                                            scenario.candidate_id,
                                            artifact_reference="portfolio-v2")
    return scenario


def test_suspension_voids_the_proposal_and_requeues_its_request(api):
    """One suspension reaches the placement and the request behind it.

    PRD §3.3: "Second, because the agreement has left `ACTIVE`, every placement
    it backs whose `placement_status` is `PROPOSED` moves `PROPOSED → VOIDED`
    with `voided_reason` set to `AGREEMENT_SUSPENDED` ... Third, because those
    placements have died, each one's placement request moves `ROUTED →
    SUBMITTED` and gains the voided placement's `cooperating_teacher_id` in its
    `excluded_cooperating_teacher_ids`".

    Design: Difficulty/transitive_cascade/agreement_suspension_cascades_void_requeue_and_ledger_rederivation
    """
    scenario = setup_proposed_placement(api)

    suspended = validate_success(api.suspend_agreement(
        scenario.agreement_id,
        f.suspend_payload(
            suspension_reason="State compliance hold on the district's sites."),
        PROGRAM_ADMIN))
    assert suspended["status"] == "SUSPENDED"

    voided = read_placement(api, scenario.placement_id)
    assert voided["placement_status"] == "VOIDED"
    assert voided["voided_reason"] == "AGREEMENT_SUSPENDED"

    requeued = read_request(api, scenario.request_id)
    assert requeued["status"] == "SUBMITTED"
    assert requeued["excluded_cooperating_teacher_ids"] == [scenario.teacher_id]


def test_suspension_gives_back_every_seat_headcount_and_caseload_point(api):
    """The three conserved counters return to their pre-routing values.

    PRD §3.3: "Fourth, because the voided placements no longer count anywhere,
    the agreement's `seats_reserved` falls by one per voided placement, each
    affected teacher's `active_placement_count` falls, each affected
    supervisor's `caseload_points` falls by the points that placement was
    contributing, and `capacity_posture` is re-derived from the resulting
    `seats_committed`."

    Design: Difficulty/transitive_cascade/agreement_suspension_cascades_void_requeue_and_ledger_rederivation
    """
    scenario = setup_proposed_placement(api)
    assert_agreement_ledger(read_agreement(api, scenario.agreement_id),
                            seats_reserved=1, seats_committed=0,
                            stipend_committed_cents=0)

    validate_success(api.suspend_agreement(
        scenario.agreement_id, f.suspend_payload(), PROGRAM_ADMIN))

    assert_agreement_ledger(read_agreement(api, scenario.agreement_id),
                            seats_reserved=0, seats_committed=0,
                            stipend_committed_cents=0,
                            capacity_posture="OPEN")
    assert read_teacher(api, scenario.teacher_id)["active_placement_count"] == 0
    supervisor = read_supervisor(api, scenario.supervisor_id)
    assert_caseload(supervisor, 0)
    assert supervisor["accepting_new_placements"] is True
    assert_placement_dimensions(read_placement(api, scenario.placement_id),
                                "VOIDED", "NOT_ACCRUED")


def test_a_sub_cut_score_on_the_final_attempt_pends_a_system_removal(api):
    """69 points on attempt two fails the assessment and files the removal.

    PRD §3.8: "Drop the last dimension to 2.5 and the total is 24 plus 25 plus
    12 plus 8, or 69." ... "Second, because the assessment failed, the owning
    placement moves `ACTIVE → REMOVAL_PENDING` with `removal_reason` set to
    `ASSESSMENT_FAILURE`, `removal_requested_by_role` set to the literal
    `"system"` and `removal_requested_by_user_id` left null".

    Design: Difficulty/transitive_cascade/assessment_failure_cascades_removal_pending_cycle_hold_and_caseload
    """
    scenario = _assessment_on_its_final_attempt(api)

    failed = validate_success(api.score_assessment(
        scenario.assessment_id, f.assessment_score_payload(**FAILING_SCORES),
        ASSESSMENT_SCORER))

    assert failed["total_score"] == 69
    assert failed["status"] == "FAILED", "a sub-cut score on attempt 2 cannot return"
    assert failed["attempt_no"] == 2

    placement = read_placement(api, scenario.placement_id)
    assert placement["placement_status"] == "REMOVAL_PENDING"
    assert placement["removal_reason"] == "ASSESSMENT_FAILURE"
    assert placement["removal_requested_by_role"] == "system"
    assert placement["removal_requested_by_user_id"] is None


def test_the_failure_cascade_holds_the_calendar_and_reprices_the_caseload(api):
    """The scheduled cycle goes on hold, the ratio rises and the money stands still.

    PRD §3.8: "Third, because the placement entered `REMOVAL_PENDING`, every one
    of its cycles still `SCHEDULED` moves to `CANCELLED_HOLD` and
    `observation_compliance_ratio` is re-derived over the cycles that survive.
    Fourth, because the placement's stage changed, its `supervisor_points` is
    re-scored at the `REMOVAL_PENDING` base of 3 points plus the same distance
    surcharge".

    Design: Difficulty/transitive_cascade/assessment_failure_cascades_removal_pending_cycle_hold_and_caseload
    """
    scenario = _assessment_on_its_final_attempt(api)
    assert_ratio_equals(
        read_placement(api, scenario.placement_id)["observation_compliance_ratio"],
        0.75)

    validate_success(api.score_assessment(
        scenario.assessment_id, f.assessment_score_payload(**FAILING_SCORES),
        ASSESSMENT_SCORER))

    assert read_cycle(api, scenario.cycles[3]["id"])["status"] == "CANCELLED_HOLD"
    for index in (0, 1, 2):
        assert read_cycle(api, scenario.cycles[index]["id"])["status"] == (
            "COMPLETED"), "an already-completed cycle is left exactly as it is"

    placement = read_placement(api, scenario.placement_id)
    assert_ratio_equals(placement["observation_compliance_ratio"], 1.0)
    assert_caseload(read_supervisor(api, scenario.supervisor_id), 4)
    assert_placement_dimensions(placement, "REMOVAL_PENDING", "ACCRUED")
    assert_stipend(placement, variant="PROVISIONAL", gross_cents=181468)
    assert read_assessment(api, scenario.assessment_id)["status"] == "FAILED"
