"""Resource temporal overlap: interval semantics on a facility timeline and a person.

Covers the cutover plan's half-open windows and the staffing roster's per-person
capacity.
"""

import pytest

from test_helpers import (
    api_client,
    validate_success,
    validate_error,
    ApiErrorId,
    get_success_data,
    setup_program_and_facility,
    setup_credentialed_staff,
    create_cutover_task,
    create_cutover_task_payload,
    create_staffing_shift_payload,
    validate_paginated,
    CUTOVER,
    COMMAND_CENTER,
    ANALYST,
)


# ===========================================================================
# r8_cutover_task_interval_overlap_on_resource
# ===========================================================================

def test_a_cutover_step_encroaching_on_the_prior_step_is_refused(api, cutover_headers):
    """PRD §3.9: "A new step's window must leave the standard handoff buffer of
    30 minutes clear after the preceding step and must not overlap the step that
    follows it; a window that violates either rule is refused with
    `ERR_TEMPORAL_OVERLAP` (HTTP 409)."
    PRD §3.9: "its planned window as a `planned_start_utc` that is inclusive and
    a `planned_end_utc` that is exclusive".

    A step starting at 22:45 while the previous step runs until 23:00 overlaps it
    and is refused.

    Design: Difficulty/resource_temporal_overlap/r8_cutover_task_interval_overlap_on_resource
    """
    prog, fac = setup_program_and_facility()
    create_cutover_task(fac["id"], task_class="DOWNTIME_PREP", sequence_index=1,
                        planned_start_utc="2026-11-30T22:00:00Z",
                        planned_end_utc="2026-11-30T23:00:00Z")

    refused = api.create_cutover_task(
        fac["id"],
        create_cutover_task_payload(
            task_class="ORDER_RECONCILIATION", sequence_index=2,
            planned_start_utc="2026-11-30T22:45:00Z",
            planned_end_utc="2026-11-30T23:30:00Z",
        ),
        cutover_headers,
    )
    validate_error(refused, ApiErrorId.ERR_TEMPORAL_OVERLAP, expected_status=409)


def test_an_adjacent_cutover_step_is_admitted_with_its_derived_duration(api, cutover_headers):
    """PRD §3.9: "The server derives `duration_minutes` as the interval between
    those two instants expressed in minutes."
    PRD §3.9: "a window that violates either rule is refused with
    `ERR_TEMPORAL_OVERLAP` (HTTP 409)."

    A step starting exactly as the previous one ends is adjacent rather than
    overlapping, so it is admitted with a thirty-minute derived duration.

    Design: Difficulty/resource_temporal_overlap/r8_cutover_task_interval_overlap_on_resource
    """
    prog, fac = setup_program_and_facility()
    create_cutover_task(fac["id"], task_class="DOWNTIME_PREP", sequence_index=1,
                        planned_start_utc="2026-11-30T22:00:00Z",
                        planned_end_utc="2026-11-30T23:00:00Z")

    adjacent = validate_success(api.create_cutover_task(
        fac["id"],
        create_cutover_task_payload(
            task_class="ORDER_RECONCILIATION", sequence_index=2,
            planned_start_utc="2026-11-30T23:00:00Z",
            planned_end_utc="2026-11-30T23:30:00Z",
        ),
        cutover_headers,
    ), 201)
    assert adjacent["duration_minutes"] == pytest.approx(30.0, abs=0.01)

    rows, _ = validate_paginated(api.list_facility_cutover_tasks(fac["id"], cutover_headers))
    assert len(rows) == 2, "the refused overlap was never persisted"


# ===========================================================================
# r8_staffing_shift_overlap_on_assigned_person
# ===========================================================================

def test_a_second_shift_overlapping_the_first_is_refused_for_the_same_staffer(api, command_center_headers):
    """PRD §3.10: "A shift may not overlap another shift of the same staff
    member, and two `AT_THE_ELBOW` shifts at the same facility may not overlap
    either; exact adjacency, where one shift ends precisely as the next begins,
    is permitted. A violation of either rule is refused with `ERR_SHIFT_OVERLAP`
    (HTTP 409)."
    PRD §3.10: "A shift begins in `SCHEDULED`".

    The second window starts at 11:00 while the first still runs until 12:00.

    Design: Difficulty/resource_temporal_overlap/r8_staffing_shift_overlap_on_assigned_person
    """
    ctx = setup_credentialed_staff()
    get_success_data(api_client.create_shift(
        create_staffing_shift_payload(
            ctx["staff"]["id"], ctx["fac"]["id"], support_role="AT_THE_ELBOW",
            start_utc="2026-09-03T06:00:00Z", end_utc="2026-09-03T12:00:00Z",
        ),
        command_center_headers,
    ))

    refused = api.create_shift(
        create_staffing_shift_payload(
            ctx["staff"]["id"], ctx["fac"]["id"], support_role="AT_THE_ELBOW",
            start_utc="2026-09-03T11:00:00Z", end_utc="2026-09-03T17:00:00Z",
        ),
        command_center_headers,
    )
    validate_error(refused, ApiErrorId.ERR_SHIFT_OVERLAP, expected_status=409)


def test_a_back_to_back_shift_for_the_same_staffer_is_admitted(api, command_center_headers):
    """PRD §3.10: "exact adjacency, where one shift ends precisely as the next
    begins, is permitted. A violation of either rule is refused with
    `ERR_SHIFT_OVERLAP` (HTTP 409)."
    PRD §3.10: "The server stamps `handoff_buffer_minutes` at 30."

    Design: Difficulty/resource_temporal_overlap/r8_staffing_shift_overlap_on_assigned_person
    """
    ctx = setup_credentialed_staff()
    get_success_data(api_client.create_shift(
        create_staffing_shift_payload(
            ctx["staff"]["id"], ctx["fac"]["id"], support_role="AT_THE_ELBOW",
            start_utc="2026-09-03T06:00:00Z", end_utc="2026-09-03T12:00:00Z",
        ),
        command_center_headers,
    ))

    adjacent = validate_success(api.create_shift(
        create_staffing_shift_payload(
            ctx["staff"]["id"], ctx["fac"]["id"], support_role="AT_THE_ELBOW",
            start_utc="2026-09-03T12:00:00Z", end_utc="2026-09-03T18:00:00Z",
        ),
        command_center_headers,
    ), 201)
    assert adjacent["status"] == "SCHEDULED"

    rows, meta = validate_paginated(
        api.list_staffing_shifts(command_center_headers, params={"staff_id": ctx["staff"]["id"]})
    )
    assert len(rows) == 2
    assert meta["total_count"] == 2