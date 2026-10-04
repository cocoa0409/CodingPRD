"""Gates on booking an interview slot: agreement state and supervisor overlap."""
from test_helpers import (
    ApiErrorId,
    advance_student_to_internship,
    assert_interview_round,
    create_cohort,
    create_enrolled_student,
    create_partner,
    draft_agreement,
    interview_payload,
    placement_payload,
    schedule_interview_for,
    setup_two_matched_placements,
    staff_headers,
    validate_error,
    validate_success,
)

SLOT = "2026-09-20T15:00:00Z"
INSIDE_EXISTING_ROUND = "2026-09-20T15:30:00Z"
ADJACENT_SLOT = "2026-09-20T15:45:00Z"


def _draft_agreement_placement(api):
    """A MATCHED placement whose sponsoring agreement is still DRAFT."""
    partner = create_partner()
    cohort = create_cohort()
    student = create_enrolled_student(cohort["id"])
    advance_student_to_internship(student["id"])
    agreement = draft_agreement(partner["id"])
    placement = validate_success(
        api.create_placement(
            placement_payload(agreement["id"], student["id"]), staff_headers()
        ),
        201,
    )
    return partner, agreement, placement


def test_interview_scheduling_requires_an_active_agreement(api):
    """PRD §2.5: "The parent aggregate must be in the state the transition requires —
    an `ACTIVE` agreement for interview scheduling and offers, an `ACTIVE` or
    `FULFILLED` agreement for offer acceptance, a `PLANNED` or `ACTIVE` cohort for
    enrollment, and a placement at `ACCEPTED` or `ACTIVE` for an internship-phase
    stipend statement. Otherwise `ERR_PARENT_STATE_CONFLICT` (409)."
    PRD §3.4: "The sponsoring agreement must be `ACTIVE`, and `scheduled_for` must
    fall inside that agreement's window, from its `start_date` through its `end_date`
    inclusive."

    Design: Difficulty/cross_entity_state_dependency/interview_scheduling_requires_active_agreement
    """
    partner, agreement, placement = _draft_agreement_placement(api)
    assert agreement["status"] == "DRAFT", agreement["status"]

    response = api.schedule_interview(
        placement["id"], interview_payload(scheduled_for=SLOT), staff_headers()
    )

    validate_error(response, ApiErrorId.ERR_PARENT_STATE_CONFLICT)


def test_interview_scheduling_succeeds_once_the_agreement_is_activated(api):
    """PRD §3.4: "The sponsoring agreement must be `ACTIVE`, and `scheduled_for` must
    fall inside that agreement's window, from its `start_date` through its `end_date`
    inclusive."
    PRD §3.4: "A successful scheduling creates an interview round whose `outcome`
    starts at `PENDING`, whose `round_number` is the placement's current
    `interview_attempt` plus 1, and whose `feedback` is empty"

    Design: Difficulty/cross_entity_state_dependency/interview_scheduling_requires_active_agreement
    """
    partner, agreement, placement = _draft_agreement_placement(api)

    activated = validate_success(
        api.activate_agreement(
            agreement["id"], {"expected_partner_version": partner["version"]}, staff_headers()
        ),
        200,
    )
    assert activated["status"] == "ACTIVE", activated["status"]

    round_data = validate_success(
        api.schedule_interview(
            placement["id"], interview_payload(scheduled_for=SLOT), staff_headers()
        ),
        201,
    )
    assert round_data["round_number"] == 1, round_data["round_number"]
    assert round_data["outcome"] == "PENDING", round_data["outcome"]
    assert_interview_round(round_data)

    placement_now = validate_success(api.get_placement(placement["id"], staff_headers()), 200)
    assert placement_now["state"] == "INTERVIEW_SCHEDULED", placement_now["state"]


def test_overlapping_supervisor_slot_is_refused(api):
    """PRD §3.4: "two rounds conflict when the intervals running from each round's
    `scheduled_for` for its `duration_minutes` share any instant, regardless of which
    placement they belong to"

    Design: Difficulty/resource_temporal_overlap/supervisor_interview_slot_half_open_overlap
    """
    scenario = setup_two_matched_placements()
    schedule_interview_for(scenario.placement["id"], scheduled_for=SLOT, duration_minutes=45)

    response = api.schedule_interview(
        scenario.placement_two["id"],
        interview_payload(scheduled_for=INSIDE_EXISTING_ROUND, duration_minutes=30),
        staff_headers(),
    )

    validate_error(response, ApiErrorId.ERR_INTERVIEW_SLOT_CONFLICT)


def test_adjacent_slot_starting_at_the_previous_rounds_end_is_accepted(api):
    """PRD §3.4: "two rounds conflict when the intervals running from each round's
    `scheduled_for` for its `duration_minutes` share any instant, regardless of which
    placement they belong to"

    The 15:00 round runs until 15:45, so a slot starting at 15:45 shares no instant
    with it and is accepted.

    Design: Difficulty/resource_temporal_overlap/supervisor_interview_slot_half_open_overlap
    """
    scenario = setup_two_matched_placements()
    schedule_interview_for(scenario.placement["id"], scheduled_for=SLOT, duration_minutes=45)

    round_data = validate_success(
        api.schedule_interview(
            scenario.placement_two["id"],
            interview_payload(scheduled_for=ADJACENT_SLOT, duration_minutes=30),
            staff_headers(),
        ),
        201,
    )
    assert round_data["scheduled_for"] is not None, round_data
    assert round_data["supervisor_name"] == "Dana Whitfield", round_data["supervisor_name"]
    assert_interview_round(round_data)

    first_placement_rounds = validate_success(
        api.list_interviews(scenario.placement["id"], staff_headers()), 200
    )
    second_placement_rounds = validate_success(
        api.list_interviews(scenario.placement_two["id"], staff_headers()), 200
    )
    assert len(first_placement_rounds) == 1, len(first_placement_rounds)
    assert len(second_placement_rounds) == 1, len(second_placement_rounds)
    supervisors = {
        item["supervisor_name"]
        for item in list(first_placement_rounds) + list(second_placement_rounds)
    }
    assert supervisors == {"Dana Whitfield"}, supervisors

    placement_two = validate_success(
        api.get_placement(scenario.placement_two["id"], staff_headers()), 200
    )
    assert placement_two["state"] == "INTERVIEW_SCHEDULED", placement_two["state"]
