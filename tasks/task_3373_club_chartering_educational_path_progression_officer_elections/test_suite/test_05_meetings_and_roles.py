"""Meetings: the overlap window, quorum, role slots and the speech rotation window."""
from test_helpers import (
    ApiErrorId,
    assign_role,
    close_meeting,
    create_assignment,
    create_meeting,
    get_assignment,
    get_club,
    get_meeting,
    get_success_data,
    hold_meeting,
    list_club_meetings,
    release_assignment,
    schedule_meeting,
    setup_club_with_officer,
    setup_club_with_paid_members,
    validate_error,
)

MEETING_A_AT = "2026-09-10T18:30:00Z"
MEETING_B_AT = "2026-09-12T18:30:00Z"
MEETING_C_AT = "2026-09-14T18:30:00Z"
SEVEN_ROLES = [
    "TOASTMASTER",
    "TIMER",
    "AH_COUNTER",
    "GRAMMARIAN",
    "GENERAL_EVALUATOR",
    "EVALUATOR",
    "TABLE_TOPICS_MASTER",
]


def _meeting_with_two_speech_assignments() -> tuple:
    """Club + 3 paid members; Ada holds SPEAKER roles at two meetings inside one window."""
    club, memberships = setup_club_with_paid_members(3, prefix="w")
    officer_ms, ada_ms, grace_ms = memberships[0], memberships[1], memberships[2]
    meeting_a = create_meeting(club["id"], officer_ms["id"], scheduled_at=MEETING_A_AT)
    meeting_b = create_meeting(club["id"], officer_ms["id"], scheduled_at=MEETING_B_AT)
    meeting_c = create_meeting(club["id"], officer_ms["id"], scheduled_at=MEETING_C_AT)
    create_assignment(meeting_a["id"], officer_ms["id"], ada_ms["member_id"], "SPEAKER")
    second = create_assignment(meeting_b["id"], officer_ms["id"], ada_ms["member_id"], "SPEAKER")
    return club, officer_ms, ada_ms, grace_ms, meeting_c, second


def test_candidate_starting_exactly_thirty_minutes_after_is_accepted(api, whq_headers):
    """PRD §3.6: "The buffer runs one way only; a candidate starting exactly 30 minutes
    after an existing meeting ends is accepted."

    Design: Difficulty/boundary_precision_check/meeting_buffer_exactly_thirty_minutes_after_previous_end
    """
    club, membership, member_id = setup_club_with_officer()
    meeting_a = create_meeting(club["id"], membership["id"], scheduled_at=MEETING_A_AT, duration_minutes=90)

    response = schedule_meeting(club["id"], membership["id"], scheduled_at="2026-09-10T20:30:00Z")
    accepted = get_success_data(response, 201)
    assert accepted["status"] == "SCHEDULED"
    assert accepted["id"] != meeting_a["id"]

    meetings = list_club_meetings(club["id"])
    assert len(meetings) == 2, "only meeting A and the accepted candidate may exist"


def test_candidate_starting_twenty_nine_minutes_after_is_refused(api, whq_headers):
    """PRD §3.6: "A second, one-sided rule guards the gap that precedes the candidate: the request is also refused when the candidate starts at or after the end of an existing meeting and less than 30 minutes after it — that is, when the difference between the candidate's start and the existing meeting's end is at least 0 and strictly less than 30 minutes."
    PRD §3.6: "Both refusals carry `ERR_MEETING_OVERLAP`."

    Design: Difficulty/boundary_precision_check/meeting_buffer_exactly_thirty_minutes_after_previous_end
    """
    club, membership, member_id = setup_club_with_officer()
    create_meeting(club["id"], membership["id"], scheduled_at=MEETING_A_AT, duration_minutes=90)

    response = schedule_meeting(club["id"], membership["id"], scheduled_at="2026-09-10T20:29:00Z")
    validate_error(response, ApiErrorId.ERR_MEETING_OVERLAP)
    assert len(list_club_meetings(club["id"])) == 1, "the refused candidate must not be stored"


def test_candidate_intersecting_a_scheduled_meeting_is_refused(api, whq_headers):
    """PRD §3.6: "A candidate meeting is refused when any meeting of the same club in
    status `SCHEDULED` or `HELD` intersects it: the existing meeting starts before the
    candidate's start plus the candidate's `duration_minutes`, and the candidate starts
    before the existing meeting's start plus its own `duration_minutes`."

    Design: Difficulty/resource_temporal_overlap/meeting_interval_intersection_with_one_sided_buffer
    """
    club, membership, member_id = setup_club_with_officer()
    create_meeting(club["id"], membership["id"], scheduled_at=MEETING_A_AT, duration_minutes=90)

    response = schedule_meeting(club["id"], membership["id"], scheduled_at="2026-09-10T19:00:00Z")
    validate_error(response, ApiErrorId.ERR_MEETING_OVERLAP)
    assert len(list_club_meetings(club["id"])) == 1


def test_cancelled_meeting_frees_the_window(api, whq_headers):
    """PRD §3.6: "Cancelled meetings never occupy the window, so a cancelled slot frees
    up completely."

    Design: Difficulty/resource_temporal_overlap/meeting_interval_intersection_with_one_sided_buffer
    """
    club, membership, member_id = setup_club_with_officer()
    meeting_a = create_meeting(club["id"], membership["id"], scheduled_at=MEETING_A_AT, duration_minutes=90)
    assert close_meeting(meeting_a["id"], membership["id"], "CANCELLED").status_code == 200

    accepted = get_success_data(
        schedule_meeting(club["id"], membership["id"], scheduled_at="2026-09-10T19:00:00Z"), 201
    )
    assert accepted["status"] == "SCHEDULED", "the identical candidate must now be accepted"

    live = [m for m in list_club_meetings(club["id"]) if m["status"] != "CANCELLED"]
    assert len(live) == 1, "only one non-cancelled meeting may exist for the club"


def test_third_speech_role_inside_the_rolling_window_is_refused(api, whq_headers):
    """PRD §3.6: "for a candidate `SPEECH` assignment, the window runs from 7 days before the meeting's `scheduled_at` to 7 days after it, inclusive at both ends, and the server counts every role assignment for that member whose `role_class` is `SPEECH` and whose status is `ASSIGNED`, `COMPLETED` or `NO_SHOW` and whose meeting falls inside that window. If that count already stands at 2, the new assignment is refused with `ERR_ROLE_WINDOW_EXCEEDED`; released assignments never occupy the window, so releasing a role genuinely frees the member's slot in the rotation."

    Design: Difficulty/resource_temporal_overlap/speech_role_rolling_window_capacity_and_release_exclusion
    """
    club, officer_ms, ada_ms, grace_ms, meeting_c, _ = _meeting_with_two_speech_assignments()
    create_assignment(meeting_c["id"], officer_ms["id"], grace_ms["member_id"], "TOASTMASTER")

    response = assign_role(meeting_c["id"], officer_ms["id"], ada_ms["member_id"], "SPEAKER")
    validate_error(response, ApiErrorId.ERR_ROLE_WINDOW_EXCEEDED)


def test_released_speech_role_frees_the_rotation_window(api, whq_headers):
    """PRD §3.6: "released assignments never occupy the window, so releasing a role
    genuinely frees the member's slot in the rotation."

    Design: Difficulty/resource_temporal_overlap/speech_role_rolling_window_capacity_and_release_exclusion
    """
    club, officer_ms, ada_ms, grace_ms, meeting_c, second = _meeting_with_two_speech_assignments()
    create_assignment(meeting_c["id"], officer_ms["id"], grace_ms["member_id"], "TOASTMASTER")

    released = get_success_data(
        release_assignment(second["id"], officer_ms["id"], "Member moved out of the area"), 200
    )
    assert released["status"] == "RELEASED"

    accepted = get_success_data(
        assign_role(meeting_c["id"], officer_ms["id"], ada_ms["member_id"], "SPEAKER"), 201
    )
    assert accepted["status"] == "ASSIGNED"
    assert get_meeting(meeting_c["id"])["filled_role_slots"] == 2, (
        "the released assignment frees its slot and the retry takes the other one"
    )


def test_closing_a_held_meeting_again_is_an_invalid_state(api, whq_headers):
    """PRD §3.6: "A meeting closed as `HELD` or `CANCELLED` is terminal and cannot be
    closed again."
    PRD §2.10: "Checks are evaluated in a fixed order, and the first check that fails
    determines the response."

    Design: Difficulty/priority_pair_validation_conflict/invalid_state_beats_quorum_check_on_second_close
    """
    club, membership, member_id = setup_club_with_officer()
    meeting = create_meeting(club["id"], membership["id"], scheduled_at=MEETING_A_AT)
    hold_meeting(meeting["id"], membership["id"], [member_id])

    response = close_meeting(meeting["id"], membership["id"], "HELD", attendance_count=3)
    validate_error(response, ApiErrorId.ERR_INVALID_STATE)


def test_refused_second_close_leaves_the_meeting_held(api, whq_headers):
    """PRD §3.6: "When the quorum is met, `quorum_met` becomes true and `held_at` is
    stamped with the request timestamp."

    Design: Difficulty/priority_pair_validation_conflict/invalid_state_beats_quorum_check_on_second_close
    """
    club, membership, member_id = setup_club_with_officer()
    meeting = create_meeting(club["id"], membership["id"], scheduled_at=MEETING_A_AT)
    hold_meeting(meeting["id"], membership["id"], [member_id])

    close_meeting(meeting["id"], membership["id"], "HELD", attendance_count=3)

    after = get_meeting(meeting["id"])
    assert after["status"] == "HELD"
    assert after["quorum_met"] is True


def test_role_window_check_wins_over_slot_capacity(api, whq_headers):
    """PRD §2.10: "Ninth, a speech role assignment may not push the member past the
    rolling window limit, otherwise `ERR_ROLE_WINDOW_EXCEEDED`."
    PRD §2.10: "Fourteenth, the seven-slot capacity of a meeting is enforced, failing
    with `ERR_ROLE_SLOTS_FULL`."

    Design: Difficulty/priority_pair_validation_conflict/role_window_check_beats_slot_capacity_check
    """
    club, memberships = setup_club_with_paid_members(8, prefix="z")
    officer_ms = memberships[0]
    meeting_a = create_meeting(club["id"], officer_ms["id"], scheduled_at=MEETING_A_AT)
    meeting_b = create_meeting(club["id"], officer_ms["id"], scheduled_at=MEETING_B_AT)
    meeting_c = create_meeting(club["id"], officer_ms["id"], scheduled_at=MEETING_C_AT)
    create_assignment(meeting_a["id"], officer_ms["id"], memberships[0]["member_id"], "SPEAKER")
    create_assignment(meeting_b["id"], officer_ms["id"], memberships[0]["member_id"], "SPEAKER")
    for index, role_code in enumerate(SEVEN_ROLES):
        create_assignment(meeting_c["id"], officer_ms["id"], memberships[index + 1]["member_id"], role_code)
    assert get_meeting(meeting_c["id"])["filled_role_slots"] == 7, "setup: the meeting is full"

    response = assign_role(meeting_c["id"], officer_ms["id"], memberships[0]["member_id"], "SPEAKER")
    validate_error(response, ApiErrorId.ERR_ROLE_WINDOW_EXCEEDED)


def test_refused_window_assignment_leaves_the_slot_count_at_seven(api, whq_headers):
    """PRD §3.6: "A meeting never carries more than 7 assignments in status `ASSIGNED`, `COMPLETED` or `NO_SHOW` — the count that `filled_role_slots` reports — and an eighth is refused with `ERR_ROLE_SLOTS_FULL`."

    Design: Difficulty/priority_pair_validation_conflict/role_window_check_beats_slot_capacity_check
    """
    club, memberships = setup_club_with_paid_members(8, prefix="z")
    officer_ms = memberships[0]
    meeting_a = create_meeting(club["id"], officer_ms["id"], scheduled_at=MEETING_A_AT)
    meeting_b = create_meeting(club["id"], officer_ms["id"], scheduled_at=MEETING_B_AT)
    meeting_c = create_meeting(club["id"], officer_ms["id"], scheduled_at=MEETING_C_AT)
    create_assignment(meeting_a["id"], officer_ms["id"], memberships[0]["member_id"], "SPEAKER")
    create_assignment(meeting_b["id"], officer_ms["id"], memberships[0]["member_id"], "SPEAKER")
    for index, role_code in enumerate(SEVEN_ROLES):
        create_assignment(meeting_c["id"], officer_ms["id"], memberships[index + 1]["member_id"], role_code)

    assign_role(meeting_c["id"], officer_ms["id"], memberships[0]["member_id"], "SPEAKER")

    assert get_meeting(meeting_c["id"])["filled_role_slots"] == 7, (
        "the refused assignment must not occupy a slot"
    )


def test_releasing_a_role_restores_the_filled_slot_count(api, whq_headers):
    """PRD §3.6: "The assignment moves to `RELEASED`, the meeting's
    `filled_role_slots` is recomputed, and the assignment's `version` increments."

    Design: Difficulty/compensating_invariant/role_assignment_release_conserves_filled_slots
    """
    club, memberships = setup_club_with_paid_members(2, prefix="v")
    officer_ms, other_ms = memberships[0], memberships[1]
    meeting = create_meeting(club["id"], officer_ms["id"], scheduled_at=MEETING_A_AT)
    create_assignment(meeting["id"], officer_ms["id"], officer_ms["member_id"], "TIMER")
    assert get_meeting(meeting["id"])["filled_role_slots"] == 1, "before the pair"

    added = create_assignment(meeting["id"], officer_ms["id"], other_ms["member_id"], "GRAMMARIAN")
    assert get_meeting(meeting["id"])["filled_role_slots"] == 2, "after the added assignment"

    release_assignment(added["id"], officer_ms["id"], "Member unavailable")
    assert get_meeting(meeting["id"])["filled_role_slots"] == 1, (
        "the release restores the pre-pair slot count"
    )


def test_released_assignment_stops_counting_toward_slots(api, whq_headers):
    """PRD §2.6: "The assignment moves to `RELEASED`, the meeting's `filled_role_slots` is recomputed, and the assignment's `version` increments.".

    Design: Difficulty/compensating_invariant/role_assignment_release_conserves_filled_slots
    """
    club, memberships = setup_club_with_paid_members(2, prefix="v")
    officer_ms, other_ms = memberships[0], memberships[1]
    meeting = create_meeting(club["id"], officer_ms["id"], scheduled_at=MEETING_A_AT)
    original = create_assignment(meeting["id"], officer_ms["id"], officer_ms["member_id"], "TIMER")
    added = create_assignment(meeting["id"], officer_ms["id"], other_ms["member_id"], "GRAMMARIAN")

    released = get_success_data(
        release_assignment(added["id"], officer_ms["id"], "Member unavailable"), 200
    )
    assert released["status"] == "RELEASED"
    assert get_assignment(original["id"])["status"] == "ASSIGNED", (
        "the untouched assignment still occupies its slot"
    )
    assert get_meeting(meeting["id"])["filled_role_slots"] == 1


def test_new_meeting_starts_scheduled_with_seven_required_slots(api, whq_headers):
    """PRD §3.6: "A newly scheduled meeting is in status `SCHEDULED` with
    `required_role_slots` fixed at 7, `filled_role_slots` 0, `quorum_met` false and
    `held_at` null."

    Design: Corner/state_machines/new_meeting_starts_scheduled_with_seven_required_slots
    """
    club, membership, member_id = setup_club_with_officer()

    meeting = create_meeting(club["id"], membership["id"], scheduled_at=MEETING_A_AT)

    assert meeting["status"] == "SCHEDULED"
    assert meeting["required_role_slots"] == 7
    assert meeting["filled_role_slots"] == 0
    assert meeting["quorum_met"] is False
    assert meeting["held_at"] is None


def test_second_release_of_the_same_assignment_is_refused(api, whq_headers):
    """PRD §3.6: "Releasing an assignment is an officer act that requires the assignment to be `ASSIGNED` and its meeting to still be `SCHEDULED`; the payload carries `released_reason`."
    PRD §3.6: "A `RELEASED` assignment is terminal, and its member is free to take
    another speaking role inside the same window."

    Design: Corner/state_machines/release_of_released_assignment_returns_invalid_state
    """
    club, membership, member_id = setup_club_with_officer()
    meeting = create_meeting(club["id"], membership["id"], scheduled_at=MEETING_A_AT)
    assignment = create_assignment(meeting["id"], membership["id"], member_id, "TIMER")
    first = get_success_data(release_assignment(assignment["id"], membership["id"], "Member unavailable"), 200)
    assert first["status"] == "RELEASED"

    response = release_assignment(assignment["id"], membership["id"], "Second release attempt")
    validate_error(response, ApiErrorId.ERR_INVALID_STATE)
    assert get_meeting(meeting["id"])["filled_role_slots"] == 0


def test_holding_a_meeting_resolves_absent_assignments_as_no_show(api, whq_headers):
    """PRD §3.6: "Every role assignment of that meeting still in status `ASSIGNED` is
    then resolved in the same operation: those whose member appears in
    `attendee_member_ids` become `COMPLETED`, and those whose member does not appear
    become `NO_SHOW`."

    Design: Corner/state_machines/meeting_hold_marks_absent_assignments_no_show
    """
    club, memberships = setup_club_with_paid_members(2, prefix="h")
    officer_ms, grace_ms = memberships[0], memberships[1]
    meeting = create_meeting(club["id"], officer_ms["id"], scheduled_at=MEETING_A_AT)
    ada_assignment = create_assignment(meeting["id"], officer_ms["id"], officer_ms["member_id"], "TIMER")
    grace_assignment = create_assignment(meeting["id"], officer_ms["id"], grace_ms["member_id"], "GRAMMARIAN")

    held = hold_meeting(meeting["id"], officer_ms["id"], [officer_ms["member_id"]])
    assert held["status"] == "HELD" and held["quorum_met"] is True

    assert get_assignment(ada_assignment["id"])["status"] == "COMPLETED", (
        "the listed attendee completes their role"
    )
    absent = get_assignment(grace_assignment["id"])
    assert absent["status"] == "NO_SHOW"
    assert absent["credit_awarded"] is False
    assert get_club(club["id"])["meetings_held_this_cycle"] == 1


def test_second_assignment_for_the_same_member_is_refused(api, whq_headers):
    """PRD §3.6: "A member may hold only one `ASSIGNED` assignment on a given meeting;
    a second one is refused with `ERR_DUPLICATE_ASSIGNMENT`."

    Design: Corner/validations/duplicate_role_assignment_rejected
    """
    club, membership, member_id = setup_club_with_officer()
    meeting = create_meeting(club["id"], membership["id"], scheduled_at=MEETING_A_AT)
    create_assignment(meeting["id"], membership["id"], member_id, "TIMER")

    response = assign_role(meeting["id"], membership["id"], member_id, "GRAMMARIAN")
    validate_error(response, ApiErrorId.ERR_DUPLICATE_ASSIGNMENT)
    assert get_meeting(meeting["id"])["filled_role_slots"] == 1, (
        "the refused assignment must not occupy a second slot"
    )


def test_eighth_assignment_is_refused_when_the_meeting_is_full(api, whq_headers):
    """PRD §3.6: "A meeting never carries more than 7 assignments in status `ASSIGNED`,
    `COMPLETED` or `NO_SHOW` — the count that `filled_role_slots` reports — and an
    eighth is refused with `ERR_ROLE_SLOTS_FULL`."

    Design: Corner/errors/role_slots_full_on_eighth_assignment
    """
    club, memberships = setup_club_with_paid_members(8, prefix="s")
    officer_ms = memberships[0]
    meeting = create_meeting(club["id"], officer_ms["id"], scheduled_at=MEETING_A_AT)
    for index, role_code in enumerate(SEVEN_ROLES):
        create_assignment(meeting["id"], officer_ms["id"], memberships[index]["member_id"], role_code)
    assert get_meeting(meeting["id"])["filled_role_slots"] == 7, "setup: seven slots are taken"

    response = assign_role(meeting["id"], officer_ms["id"], memberships[7]["member_id"], "SPEAKER")
    validate_error(response, ApiErrorId.ERR_ROLE_SLOTS_FULL)
    assert get_meeting(meeting["id"])["filled_role_slots"] == 7


def test_close_with_insufficient_attendance_is_refused(api, whq_headers):
    """PRD §3.6: "Closing as `HELD` requires `attendance_count` of at least 5;
    anything lower is refused with `ERR_QUORUM_NOT_MET`."

    Design: Corner/errors/quorum_not_met_on_low_attendance_close
    """
    club, membership, member_id = setup_club_with_officer()
    meeting = create_meeting(club["id"], membership["id"], scheduled_at=MEETING_A_AT)

    response = close_meeting(
        meeting["id"], membership["id"], "HELD", attendance_count=4, attendee_member_ids=[member_id]
    )
    validate_error(response, ApiErrorId.ERR_QUORUM_NOT_MET)

    after = get_meeting(meeting["id"])
    assert after["status"] == "SCHEDULED"
    assert after["quorum_met"] is False
