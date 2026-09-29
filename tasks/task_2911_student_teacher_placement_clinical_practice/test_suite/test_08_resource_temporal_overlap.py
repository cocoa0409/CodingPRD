"""Two contended calendars with deliberately opposite interval semantics.

A cooperating teacher's terms are closed-closed dates padded by a 14-day
recovery buffer, so a term whose first day is the padded upper bound conflicts.
A placement's observation cycles are half-open instant windows with no buffer at
all, so a window starting exactly where another ends is adjacency, not overlap.
Each test proves the contended resource was the only reason for the answer.
"""
from test_helpers import (
    ERR_CYCLE_WINDOW_CONFLICT,
    ERR_TEACHER_TURNAROUND_CONFLICT,
    PLACEMENT_COORDINATOR,
    SUPERVISION_LEAD,
    assert_date_equals,
    assert_instant_equals,
    assert_placement_dimensions,
    assert_ratio_equals,
    factories as f,
    open_request,
    read_agreement,
    read_cycle,
    read_placement,
    read_teacher,
    route,
    schedule_cycle,
    set_clock,
    setup_active_placement,
    setup_ready_candidate,
    validate_error,
    validate_success,
)

# An 8-week term from 2026-09-01 ends 2026-10-26 and blocks 2026-08-18 through
# 2026-11-09; the next term is asked to start on that exact upper bound.
TWO_SEAT_BENCH = {
    "agreement": {"placement_cap": 2},
    "teacher": {"max_concurrent_candidates": 2},
    "request": {"weeks_scheduled": 8},
}
TOUCHING_TERM = {"term_start_date": "2026-11-09", "weeks_scheduled": 2}

# Cycle 3 is missed and then rescheduled twice: once into cycle 4's window and
# once starting exactly at cycle 4's window_end.
MISSED_CYCLE = (3, "FORMATIVE", "2026-10-01T00:00:00Z", "2026-10-05T00:00:00Z")
SUMMATIVE_CYCLE = (4, "SUMMATIVE", "2026-10-20T00:00:00Z", "2026-10-25T00:00:00Z")
AFTER_THE_MISS_CLOCK = "2026-10-06T00:00:00Z"
OVERLAPPING_WINDOW = ("2026-10-22T00:00:00Z", "2026-10-24T00:00:00Z")
TOUCHING_WINDOW = ("2026-10-25T00:00:00Z", "2026-10-27T00:00:00Z")


def _back_to_back_terms_on_one_mentor(api):
    """One confirmed 8-week term and a second proposal starting on its buffer."""
    scenario = setup_active_placement(api, **TWO_SEAT_BENCH)
    second = setup_ready_candidate(api)
    second.request = open_request(api, second.candidate_id,
                                 preferred_district_id=scenario.district_id,
                                 **TOUCHING_TERM)
    second.placement = route(api, second.request_id)
    return scenario, second


def _missed_cycle_beside_a_summative_one(api):
    """A placement whose formative cycle was missed and whose summative stands."""
    scenario = setup_active_placement(api)
    scenario.cycles.append(schedule_cycle(api, scenario.placement_id,
                                          *MISSED_CYCLE))
    scenario.cycles.append(schedule_cycle(api, scenario.placement_id,
                                          *SUMMATIVE_CYCLE))
    set_clock(api, AFTER_THE_MISS_CLOCK)
    return scenario


def test_routing_tolerates_the_touching_term_that_confirmation_refuses(api):
    """The raw intervals fit; the 14-day padded ones collide on one day.

    PRD §3.5: "no placement of that teacher in `PROPOSED`, `ACTIVE`,
    `REMOVAL_PENDING` or `COMPLETED` overlaps the **raw, unpadded** interval
    from `term_start_date` through `term_end_date`."  PRD §3.6: "an existing
    placement running 2026-09-01 through 2026-10-26 blocks 2026-08-18 through
    2026-11-09, so a new term beginning 2026-11-09 conflicts — touching the
    closed upper bound is a conflict".

    Design: Difficulty/resource_temporal_overlap/teacher_turnaround_buffer_blocks_the_touching_next_term_at_confirmation
    """
    scenario, second = _back_to_back_terms_on_one_mentor(api)
    assert second.placement["cooperating_teacher_id"] == scenario.teacher_id
    assert_date_equals(second.placement["start_date"], "2026-11-09", "start_date")
    assert_date_equals(second.placement["end_date"], "2026-11-22", "end_date")

    validate_error(api.confirm_placement(second.placement_id,
                                         PLACEMENT_COORDINATOR),
                   ERR_TEACHER_TURNAROUND_CONFLICT, 409)

    assert_placement_dimensions(read_placement(api, second.placement_id),
                                "PROPOSED", "NOT_ACCRUED")


def test_neither_the_seat_cap_nor_the_concurrency_limit_was_the_blocker(api):
    """A free seat and a free mentor slot leave the buffer as the only cause.

    PRD §3.6: "Finally the agreement's `seats_committed` must be strictly below
    its `placement_cap`."  PRD §3.4: "`max_concurrent_candidates`, from 1
    through 3 and defaulting to 1, caps how many non-terminal placements the
    teacher may hold at once."

    Design: Difficulty/resource_temporal_overlap/teacher_turnaround_buffer_blocks_the_touching_next_term_at_confirmation
    """
    scenario, second = _back_to_back_terms_on_one_mentor(api)

    validate_error(api.confirm_placement(second.placement_id,
                                         PLACEMENT_COORDINATOR),
                   ERR_TEACHER_TURNAROUND_CONFLICT, 409)

    agreement = read_agreement(api, scenario.agreement_id)
    assert agreement["placement_cap"] == 2
    assert agreement["seats_committed"] == 1
    assert agreement["capacity_posture"] == "OPEN"
    teacher = read_teacher(api, scenario.teacher_id)
    assert teacher["max_concurrent_candidates"] == 2
    assert teacher["active_placement_count"] == 2
    first = read_placement(api, scenario.placement_id)
    assert first["placement_status"] == "ACTIVE"
    assert_date_equals(first["end_date"], "2026-10-26", "end_date")


def test_a_reschedule_into_another_window_is_refused_and_costs_no_allowance(api):
    """[10-22, 10-24) lies inside [10-20, 10-25), so the rescue is refused.

    PRD §3.7: "The new window must start no earlier than the current
    logical-clock instant, must end no later than the owning placement's
    `end_date` taken at 23:59:59Z on that date, and must not overlap any other
    `SCHEDULED` or `COMPLETED` cycle of the same placement; any of those three
    failures is refused with `ERR_CYCLE_WINDOW_CONFLICT`."

    Design: Difficulty/resource_temporal_overlap/observation_cycle_half_open_windows_permit_touching_but_reject_overlap
    """
    scenario = _missed_cycle_beside_a_summative_one(api)
    missed = read_cycle(api, scenario.cycles[0]["id"])
    assert missed["status"] == "MISSED", "the clock passed window_end"
    assert missed["reschedule_count"] == 0

    validate_error(api.reschedule_observation_cycle(
        scenario.cycles[0]["id"],
        f.cycle_reschedule_payload(
            *OVERLAPPING_WINDOW,
            resolution_note="Attempt lands inside the summative window."),
        SUPERVISION_LEAD), ERR_CYCLE_WINDOW_CONFLICT, 409)

    unchanged = read_cycle(api, scenario.cycles[0]["id"])
    assert unchanged["status"] == "MISSED"
    assert_instant_equals(unchanged["window_start"], MISSED_CYCLE[2],
                          "window_start")
    assert unchanged["reschedule_count"] == 0


def test_a_window_starting_at_another_window_end_is_adjacency_not_overlap(api):
    """[10-25, 10-27) abuts [10-20, 10-25) and is perfectly legal.

    PRD §3.7: "Because cycle windows are half-open and carry no buffer, two
    cycles that merely abut — one ending exactly where the next begins — do not
    overlap and are perfectly legal, in deliberate contrast to the closed-closed,
    buffer-padded teacher turnaround intervals of §3.6. A successful reschedule
    replaces both window instants, raises `reschedule_count` by one, records the
    `resolution_note`".

    Design: Difficulty/resource_temporal_overlap/observation_cycle_half_open_windows_permit_touching_but_reject_overlap
    """
    scenario = _missed_cycle_beside_a_summative_one(api)

    rescued = validate_success(api.reschedule_observation_cycle(
        scenario.cycles[0]["id"],
        f.cycle_reschedule_payload(
            *TOUCHING_WINDOW,
            resolution_note="Starts exactly at the summative window_end."),
        SUPERVISION_LEAD))

    assert rescued["status"] == "SCHEDULED"
    assert_instant_equals(rescued["window_start"], TOUCHING_WINDOW[0],
                          "window_start")
    assert_instant_equals(rescued["window_end"], TOUCHING_WINDOW[1],
                          "window_end")
    assert rescued["reschedule_count"] == 1

    summative = read_cycle(api, scenario.cycles[1]["id"])
    assert summative["status"] == "SCHEDULED"
    assert_instant_equals(summative["window_start"], SUMMATIVE_CYCLE[2],
                          "window_start")
    assert_instant_equals(summative["window_end"], SUMMATIVE_CYCLE[3],
                          "window_end")
    assert_ratio_equals(
        read_placement(api, scenario.placement_id)["observation_compliance_ratio"],
        0.0)
