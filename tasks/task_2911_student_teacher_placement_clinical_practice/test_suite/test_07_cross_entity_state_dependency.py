"""A row that is perfectly actionable, blocked by the row it hangs from.

A `PROPOSED` placement under an active in-window agreement with a `READY`
candidate is refused because its cooperating teacher's mentor training lapsed.
An `OPEN` assessment inside its window and above the compliance floor is refused
because the placement it belongs to has left `ACTIVE`.  Each pair is asserted
from both sides: the blocking state on the dependency, and the untouched state
on the row that was refused.
"""
from test_helpers import (
    ASSESSMENT_WINDOW_CLOSES,
    DEFAULT_CYCLE_PLAN,
    ERR_PLACEMENT_STATE_INVALID,
    ERR_TEACHER_TRAINING_EXPIRED,
    PLACEMENT_COORDINATOR,
    SUBMISSION_CLOCK,
    assert_agreement_ledger,
    assert_caseload,
    assert_date_equals,
    assert_instant_equals,
    assert_placement_dimensions,
    assert_ratio_equals,
    complete_cycle,
    factories as f,
    open_assessment,
    read_agreement,
    read_assessment,
    read_cycle,
    read_placement,
    read_supervisor,
    read_teacher,
    set_clock,
    setup_active_placement,
    setup_proposed_placement,
    setup_scheduled_cycles,
    validate_error,
    validate_success,
)

# Training completed 2024-11-15 is valid for 730 days, so it lapses on
# 2026-11-15 and the clock is moved one day past that.
LAPSED_TRAINING_ON = "2024-11-15"
TRAINING_EXPIRES_ON = "2026-11-15"
LAPSED_TRAINING_CLOCK = "2026-11-16T00:00:00Z"


def _proposal_under_a_lapsed_mentor(api):
    """A routed proposal whose teacher's training fell behind the clock."""
    scenario = setup_proposed_placement(
        api, training_completed_on=LAPSED_TRAINING_ON)
    set_clock(api, LAPSED_TRAINING_CLOCK)
    return scenario


def _assessment_whose_placement_left_active(api):
    """An OPEN assessment on a placement that a removal case has pended."""
    scenario = setup_active_placement(api)
    setup_scheduled_cycles(api, scenario)
    for index in (0, 1):
        complete_cycle(api, scenario.cycles[index]["id"], scenario.supervisor_id,
                       DEFAULT_CYCLE_PLAN[index][4], DEFAULT_CYCLE_PLAN[index][5])
    scenario.assessment = open_assessment(api, scenario.placement_id)
    set_clock(api, SUBMISSION_CLOCK)
    return scenario


def test_the_lapsed_mentor_training_blocks_a_flawless_confirmation(api):
    """The teacher's lazy transition is what refuses the placement's own call.

    PRD §3.6: "The cooperating teacher's training is examined next: a
    `QUALIFIED` teacher whose `training_expires_on` has fallen behind the clock
    is lazily moved to `TRAINING_EXPIRED` and the confirmation is refused with
    `ERR_TEACHER_TRAINING_EXPIRED`."  PRD §3.4: "the system computes
    `training_expires_on` as that date plus 730 days — two years of validity."

    Design: Difficulty/cross_entity_state_dependency/placement_confirmation_gated_on_cooperating_teacher_training_state
    """
    scenario = _proposal_under_a_lapsed_mentor(api)

    validate_error(api.confirm_placement(scenario.placement_id,
                                         PLACEMENT_COORDINATOR),
                   ERR_TEACHER_TRAINING_EXPIRED, 409)

    teacher = read_teacher(api, scenario.teacher_id)
    assert teacher["qualification_status"] == "TRAINING_EXPIRED"
    assert_date_equals(teacher["training_expires_on"], TRAINING_EXPIRES_ON,
                       "training_expires_on")


def test_the_dependent_placement_is_left_exactly_where_it_was(api):
    """The refused confirmation moves no seat, no headcount and no point.

    PRD §3.6: "the placement moves `PROPOSED → ACTIVE` and, in the very same
    request, its money dimension moves `NOT_ACCRUED → ACCRUED` ... One seat
    moves out of the agreement's `seats_reserved` and into `seats_committed`".
    PRD §3.4: "The stage base is 1 point while the placement is `PROPOSED`, 2
    points while it is `ACTIVE`".

    Design: Difficulty/cross_entity_state_dependency/placement_confirmation_gated_on_cooperating_teacher_training_state
    """
    scenario = _proposal_under_a_lapsed_mentor(api)

    validate_error(api.confirm_placement(scenario.placement_id,
                                         PLACEMENT_COORDINATOR),
                   ERR_TEACHER_TRAINING_EXPIRED, 409)

    assert_placement_dimensions(read_placement(api, scenario.placement_id),
                                "PROPOSED", "NOT_ACCRUED")
    assert_agreement_ledger(read_agreement(api, scenario.agreement_id),
                            seats_reserved=1, seats_committed=0,
                            stipend_committed_cents=0)
    assert_caseload(read_supervisor(api, scenario.supervisor_id), 2)


def test_a_pended_placement_blocks_its_own_assessment_submission(api):
    """The candidate's submission is refused and consumes no attempt.

    PRD §3.8: "the owning placement must be `ACTIVE`, otherwise
    `ERR_PLACEMENT_STATE_INVALID` ... A successful submission moves the
    assessment `OPEN → SUBMITTED` on the first pass ... raises `attempt_no` by
    one — from 0 to 1 — and records `artifact_reference` and `submitted_at`."

    Design: Difficulty/cross_entity_state_dependency/assessment_submission_gated_on_owning_placement_clinical_state
    """
    scenario = _assessment_whose_placement_left_active(api)
    validate_success(api.request_removal(
        scenario.placement_id,
        f.removal_request_payload(
            removal_narrative="Unsafe supervision incident reported by the site."),
        PLACEMENT_COORDINATOR))

    validate_error(api.submit_assessment(scenario.assessment_id,
                                         f.assessment_submit_payload(),
                                         scenario.candidate_headers),
                   ERR_PLACEMENT_STATE_INVALID, 409)

    refused = read_assessment(api, scenario.assessment_id)
    assert refused["status"] == "OPEN"
    assert refused["attempt_no"] == 0
    assert refused["submitted_at"] is None
    assert read_placement(api, scenario.placement_id)["placement_status"] == (
        "REMOVAL_PENDING")


def test_the_compliance_floor_was_never_the_reason_for_the_refusal(api):
    """0.6667 clears the 0.5 submission gate before and after the removal.

    PRD §3.8: "the placement's `observation_compliance_ratio` must be at least
    0.5 at that moment, otherwise `ERR_OBSERVATION_COMPLIANCE_LOW`".  PRD §3.7:
    "`CANCELLED_HOLD` cycles are excluded from **both** the numerator and the
    counted set entirely. The denominator is the larger of 3 and the size of the
    counted set ... Three counted with two completed give 0.6667."

    Design: Difficulty/cross_entity_state_dependency/assessment_submission_gated_on_owning_placement_clinical_state
    """
    scenario = _assessment_whose_placement_left_active(api)
    assert_ratio_equals(
        read_placement(api, scenario.placement_id)["observation_compliance_ratio"],
        0.6667)

    validate_success(api.request_removal(
        scenario.placement_id, f.removal_request_payload(),
        PLACEMENT_COORDINATOR))

    assert_ratio_equals(
        read_placement(api, scenario.placement_id)["observation_compliance_ratio"],
        0.6667)
    assert read_cycle(api, scenario.cycles[2]["id"])["status"] == "CANCELLED_HOLD"
    validate_error(api.submit_assessment(scenario.assessment_id,
                                         f.assessment_submit_payload(),
                                         scenario.candidate_headers),
                   ERR_PLACEMENT_STATE_INVALID, 409)
    assert_instant_equals(
        read_assessment(api, scenario.assessment_id)["window_closes_at"],
        ASSESSMENT_WINDOW_CLOSES, "window_closes_at")
