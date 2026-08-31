"""Sequencing construction windows around an occupied parcel."""
from test_helpers import (
    ApiErrorId, validate_success, validate_error, validate_paginated,
    assert_construction_phase,
    setup_permitted_project, setup_scheduled_phase, setup_started_phase,
    add_phase, schedule_phase, register_inspector, book_inspection,
    prepare_submittal, file_submittal, read_project,
    PROJECT_MANAGER,
)


def test_multi_day_shutoff_on_an_occupied_parcel_is_refused(api):
    """PRD §3.7: "The **habitability rule** comes first: when the parcel's `occupied` flag is
    true and the phase's `disruption_class` is `UTILITY_SHUTOFF`, the requested window may
    span no more than a single calendar day counting both endpoints, meaning
    `window_start_date` and `window_end_date` must be the same date; a longer shutoff on an
    occupied parcel is rejected with `ERR_OCCUPIED_HABITABILITY_VIOLATION` (HTTP 409)."
    PRD §3.7: "Two conflict checks then guard the booking, in this order."

    Design: Difficulty/priority_pair_validation_conflict/safety_beats_temporal_on_phase_schedule
    """
    ctx = setup_permitted_project(api, pathway="STATUTORY_MINISTERIAL", occupied_parcel=True)
    setup_scheduled_phase(api, ctx, "2026-09-01", "2026-09-05")
    shutoff = add_phase(api, ctx["project"]["id"], phase_code="UTILITY_TIE_IN",
                        disruption_class="UTILITY_SHUTOFF", sequence_index=3)

    error = validate_error(
        api.schedule_construction_phase(
            shutoff["id"],
            {"window_start_date": "2026-09-03", "window_end_date": "2026-09-06"},
            PROJECT_MANAGER),
        ApiErrorId.ERR_OCCUPIED_HABITABILITY_VIOLATION)

    assert error["error_id"] != ApiErrorId.ERR_PHASE_WINDOW_CONFLICT.value, (
        "the habitability rule is evaluated before the property window rule")


def test_habitability_rejection_leaves_both_phases_where_they_were(api):
    """PRD §3.7: "Booking a phase's disruption window stamps `window_start_date` and
    `window_end_date` and moves the phase to `SCHEDULED`."
    PRD §3.7: "Phases are created in `PLANNED` with `window_start_date`, `window_end_date`,
    `started_on_date`, and `completed_on_date` all null."

    Design: Difficulty/priority_pair_validation_conflict/safety_beats_temporal_on_phase_schedule
    """
    ctx = setup_permitted_project(api, pathway="STATUTORY_MINISTERIAL", occupied_parcel=True)
    foundation = setup_scheduled_phase(api, ctx, "2026-09-01", "2026-09-05")
    shutoff = add_phase(api, ctx["project"]["id"], phase_code="UTILITY_TIE_IN",
                        disruption_class="UTILITY_SHUTOFF", sequence_index=3)

    validate_error(
        api.schedule_construction_phase(
            shutoff["id"],
            {"window_start_date": "2026-09-03", "window_end_date": "2026-09-06"},
            PROJECT_MANAGER),
        ApiErrorId.ERR_OCCUPIED_HABITABILITY_VIOLATION)

    unchanged = validate_success(api.get_construction_phase(shutoff["id"], PROJECT_MANAGER))
    assert_construction_phase(unchanged)
    assert unchanged["status"] == "PLANNED"
    assert unchanged["window_start_date"] is None
    assert unchanged["window_end_date"] is None

    incumbent = validate_success(api.get_construction_phase(foundation["id"], PROJECT_MANAGER))
    assert incumbent["status"] == "SCHEDULED"


def test_window_inside_the_habitability_buffer_collides(api):
    """PRD §3.7: "The **property window rule** comes second and applies to every phase
    regardless of disruption class. Windows are closed intervals as described in §2.10, and
    the buffer is 2 calendar days when the parcel's `occupied` flag is true and 0 days
    otherwise."
    PRD §3.7: "The booking is rejected with `ERR_PHASE_WINDOW_CONFLICT` (HTTP 409) when any
    *other* construction phase belonging to a project on the same parcel is in `SCHEDULED` or
    `IN_PROGRESS` and its window, widened by the buffer on both sides, still overlaps the
    requested one — concretely, when the requested `window_start_date` is on or before that
    phase's `window_end_date` advanced by the buffer, and that phase's `window_start_date` is
    on or before the requested `window_end_date` advanced by the buffer."

    Design: Difficulty/resource_temporal_overlap/phase_window_closed_interval_with_habitability_buffer
    """
    ctx = setup_permitted_project(api, pathway="STATUTORY_MINISTERIAL", occupied_parcel=True)
    setup_scheduled_phase(api, ctx, "2026-09-01", "2026-09-05")
    framing = add_phase(api, ctx["project"]["id"], phase_code="FRAMING",
                        disruption_class="INVASIVE", sequence_index=1)

    validate_error(
        api.schedule_construction_phase(
            framing["id"],
            {"window_start_date": "2026-09-07", "window_end_date": "2026-09-09"},
            PROJECT_MANAGER),
        ApiErrorId.ERR_PHASE_WINDOW_CONFLICT)

    still_planned = validate_success(api.get_construction_phase(framing["id"], PROJECT_MANAGER))
    assert still_planned["status"] == "PLANNED"


def test_window_clear_of_the_habitability_buffer_is_accepted(api):
    """PRD §2.10: "On an occupied parcel a further habitability buffer of 2 calendar days is
    added on each side before the comparison is made, so two windows on an occupied parcel
    must be separated by more than two clear days to coexist."
    PRD §3.7: "Booking a phase's disruption window stamps `window_start_date` and
    `window_end_date` and moves the phase to `SCHEDULED`."

    Design: Difficulty/resource_temporal_overlap/phase_window_closed_interval_with_habitability_buffer
    """
    ctx = setup_permitted_project(api, pathway="STATUTORY_MINISTERIAL", occupied_parcel=True)
    foundation = setup_scheduled_phase(api, ctx, "2026-09-01", "2026-09-05")
    framing = add_phase(api, ctx["project"]["id"], phase_code="FRAMING",
                        disruption_class="INVASIVE", sequence_index=1)
    validate_error(
        api.schedule_construction_phase(
            framing["id"],
            {"window_start_date": "2026-09-07", "window_end_date": "2026-09-09"},
            PROJECT_MANAGER),
        ApiErrorId.ERR_PHASE_WINDOW_CONFLICT)

    booked = validate_success(api.schedule_construction_phase(
        framing["id"],
        {"window_start_date": "2026-09-08", "window_end_date": "2026-09-10"},
        PROJECT_MANAGER))

    assert booked["status"] == "SCHEDULED"
    assert booked["window_start_date"] == "2026-09-08"
    assert booked["window_end_date"] == "2026-09-10"

    incumbent = validate_success(api.get_construction_phase(foundation["id"], PROJECT_MANAGER))
    assert incumbent["window_end_date"] == "2026-09-05"


def test_phase_start_is_blocked_by_a_revision_package_under_plan_check(api):
    """PRD §3.7: "The project's most recently created permit submittal — newest by
    `created_at` — must be `APPROVED`, or the answer is `ERR_PERMIT_NOT_APPROVED`; this is the
    same freshness rule that governs energizing a utility, and it means a permit revision
    filed mid-build stops new phase starts until it clears."

    Design: Difficulty/cross_entity_state_dependency/phase_start_requires_approved_permit
    """
    ctx = setup_permitted_project(api)
    phase = setup_scheduled_phase(api, ctx, "2026-09-01", "2026-09-05")
    revision = prepare_submittal(api, ctx["project"]["id"], design_sheet_count=3)
    file_submittal(api, revision["id"])

    validate_error(api.start_construction_phase(phase["id"], PROJECT_MANAGER),
                   ApiErrorId.ERR_PERMIT_NOT_APPROVED)


def test_permit_blocked_start_leaves_the_phase_scheduled(api):
    """PRD §3.7: "Starting work moves a phase `SCHEDULED → IN_PROGRESS` and stamps
    `started_on_date` from the logical clock."
    PRD §3.4: "On success the project also moves onto its permitting axis: from
    `FEASIBILITY_CLEARED` to `PERMITTING`, or from `PERMITTED` back to `PERMITTING`, or from
    `UNDER_CONSTRUCTION` back to `PERMITTING`, in each case raising the project's `version` by
    1 alongside the submittal's own."

    Design: Difficulty/cross_entity_state_dependency/phase_start_requires_approved_permit
    """
    ctx = setup_permitted_project(api)
    phase = setup_scheduled_phase(api, ctx, "2026-09-01", "2026-09-05")
    revision = prepare_submittal(api, ctx["project"]["id"], design_sheet_count=3)
    file_submittal(api, revision["id"])

    validate_error(api.start_construction_phase(phase["id"], PROJECT_MANAGER),
                   ApiErrorId.ERR_PERMIT_NOT_APPROVED)

    unchanged = validate_success(api.get_construction_phase(phase["id"], PROJECT_MANAGER))
    assert unchanged["status"] == "SCHEDULED"
    assert unchanged["started_on_date"] is None

    original = validate_success(api.get_permit_submittal(ctx["submittal"]["id"], PROJECT_MANAGER))
    assert original["status"] == "APPROVED"
    newest = validate_success(api.get_permit_submittal(revision["id"], PROJECT_MANAGER))
    assert newest["status"] == "UNDER_PLAN_CHECK"
    assert read_project(api, ctx["project"]["id"])["status"] == "PERMITTING"


def test_phase_start_with_an_unfinished_predecessor_is_rejected(api):
    """PRD §3.7: "And if the phase names a `depends_on_phase_id`, that predecessor must have
    reached `COMPLETE`, or the answer is `ERR_PHASE_DEPENDENCY_INCOMPLETE` (HTTP 409); a phase
    with a null `depends_on_phase_id` skips this check entirely."
    PRD §3.7: "Phase listings may be narrowed by `adu_project_id`, by `depends_on_phase_id`,
    and by `status`."

    Design: Corner/state_machines/phase_start_with_incomplete_dependency_returns_phase_dependency_incomplete
    """
    ctx = setup_permitted_project(api)
    foundation = setup_scheduled_phase(api, ctx, "2026-09-01", "2026-09-05")
    framing = add_phase(api, ctx["project"]["id"], phase_code="FRAMING",
                        disruption_class="INVASIVE", sequence_index=1,
                        depends_on_phase_id=foundation["id"])
    schedule_phase(api, framing["id"], "2026-09-06", "2026-09-08")

    validate_error(api.start_construction_phase(framing["id"], PROJECT_MANAGER),
                   ApiErrorId.ERR_PHASE_DEPENDENCY_INCOMPLETE)

    assert validate_success(
        api.get_construction_phase(framing["id"], PROJECT_MANAGER))["status"] == "SCHEDULED"
    assert validate_success(
        api.get_construction_phase(foundation["id"], PROJECT_MANAGER))["status"] == "SCHEDULED"
    assert read_project(api, ctx["project"]["id"])["status"] == "PERMITTED"

    rows, meta = validate_paginated(api.list_construction_phases(
        PROJECT_MANAGER, {"depends_on_phase_id": foundation["id"]}))
    assert meta["total_count"] == 1
    assert rows[0]["id"] == framing["id"]


def test_phase_cannot_close_while_an_inspection_is_still_open(api):
    """PRD §3.7: "Closing out a phase moves it `IN_PROGRESS → COMPLETE` and stamps
    `completed_on_date`. It is refused while any inspection appointment on that phase is still
    in `SCHEDULED` or `PARTIAL`, with `ERR_OPEN_INSPECTIONS_REMAIN` (HTTP 409) — a partial
    inspection is an open inspection, and the builder must either finish it or cancel it
    before the phase can close."
    PRD §3.7: "The first phase to start on a project also advances the project itself, moving
    `status` from `PERMITTED` to `UNDER_CONSTRUCTION`; on later starts the project's status is
    already `UNDER_CONSTRUCTION` and is left alone."

    Design: Corner/state_machines/complete_phase_with_open_inspection_returns_open_inspections_remain
    """
    ctx = setup_permitted_project(api)
    inspector = register_inspector(api, ctx["jurisdiction"]["id"])
    phase = setup_started_phase(api, ctx, "2026-09-01", "2026-09-05")
    assert phase["status"] == "IN_PROGRESS"
    assert phase["started_on_date"] == "2026-08-01"
    appointment = book_inspection(api, phase["id"], inspector["id"])

    validate_error(api.complete_construction_phase(phase["id"], PROJECT_MANAGER),
                   ApiErrorId.ERR_OPEN_INSPECTIONS_REMAIN)

    unchanged = validate_success(api.get_construction_phase(phase["id"], PROJECT_MANAGER))
    assert unchanged["status"] == "IN_PROGRESS"
    assert unchanged["completed_on_date"] is None
    assert validate_success(api.get_inspection_appointment(
        appointment["id"], PROJECT_MANAGER))["status"] == "SCHEDULED"
    assert read_project(api, ctx["project"]["id"])["status"] == "UNDER_CONSTRUCTION"
