"""Session scheduling: publish gate, room turnaround buffer, lock window."""
from test_helpers import (
    ApiErrorId,
    NON_EXISTENT_UUID,
    TEST_USERS,
    add_staff,
    api_client,
    complete_audit,
    create_authorized_center,
    create_center,
    create_published_session,
    create_session,
    create_session_payload,
    get_center,
    get_session,
    publish_session,
    schedule_audit,
    validate_error,
    validate_paginated,
    validate_success,
)
from test_helpers import make_center_manager_headers


def test_publish_rejected_while_center_applied(api):
    """PRD §3.2: "Publication requires the owning center's
    `authorization_status` to be `AUTHORIZED`; attempting it while the center
    is `APPLIED` or `SUSPENDED` is rejected with `ERR_CENTER_NOT_AUTHORIZED`."

    Design: Difficulty/cross_entity_state_dependency/session_publish_requires_center_authorized
    """
    center = create_center(name="Center XD", facility_seat_capacity=20)
    manager = add_staff(center["id"], "Mgr XD", "CENTER_MANAGER", "ADVANCED")
    session = create_session(center["id"], total_seats=5)
    resp = api.publish_session(
        session["id"], make_center_manager_headers(manager["id"])
    )
    validate_error(resp, ApiErrorId.ERR_CENTER_NOT_AUTHORIZED)
    assert get_session(session["id"])["status"] == "DRAFT"


def test_publish_succeeds_after_center_authorized(api, auditor_headers):
    """PRD §3.2: "Publication requires the owning center's
    `authorization_status` to be `AUTHORIZED`; attempting it while the center
    is `APPLIED` or `SUSPENDED` is rejected with `ERR_CENTER_NOT_AUTHORIZED`."
    PRD §3.1: "A `PASSED` audit moves an `APPLIED` center to `AUTHORIZED`"

    Design: Difficulty/cross_entity_state_dependency/session_publish_requires_center_authorized
    """
    center = create_center(name="Center XD2", facility_seat_capacity=20)
    manager = add_staff(center["id"], "Mgr XD2", "CENTER_MANAGER", "ADVANCED")
    session = create_session(center["id"], total_seats=5)
    audit = schedule_audit(center["id"])
    validate_success(
        api.complete_audit(audit["id"],
                           {"facility_findings": 1, "staffing_findings": 1,
                            "equipment_findings": 2, "high_severity_findings": 0},
                           auditor_headers),
        200,
    )
    assert get_center(center["id"])["authorization_status"] == "AUTHORIZED"
    published = validate_success(
        api.publish_session(session["id"], make_center_manager_headers(manager["id"])),
        200,
    )
    assert published["status"] == "PUBLISHED"


def test_session_room_turnaround_30_min_gap_rejected(api, program_admin_headers):
    """PRD §3.2: "a new session must leave a gap of at least 60 minutes to
    every existing non-`CANCELLED` session sharing the same center,
    `test_date`, and `room_label`, counting the new session's own start-to-end
    interval against each existing one. A tighter gap rejects the create with
    `ERR_SESSION_OVERLAP`."

    Design: Difficulty/resource_temporal_overlap/session_room_turnaround_buffer
    """
    center = create_authorized_center(name="Center BF", facility_seat_capacity=40)
    create_session(center["id"], test_date="2026-10-10", start_time="08:00",
                   end_time="12:00", room_label="R1", total_seats=10)
    resp = api.create_session(
        center["id"],
        create_session_payload(test_date="2026-10-10", start_time="12:30",
                               end_time="14:00", room_label="R1", total_seats=10),
        program_admin_headers,
    )
    validate_error(resp, ApiErrorId.ERR_SESSION_OVERLAP)


def test_session_room_turnaround_60_min_gap_and_other_room_allowed(
    api, program_admin_headers
):
    """PRD §3.2: "a new session must leave a gap of at least 60 minutes to
    every existing non-`CANCELLED` session sharing the same center,
    `test_date`, and `room_label`, counting the new session's own start-to-end
    interval against each existing one. A tighter gap rejects the create with
    `ERR_SESSION_OVERLAP`."

    Design: Difficulty/resource_temporal_overlap/session_room_turnaround_buffer
    """
    center = create_authorized_center(name="Center BF2", facility_seat_capacity=40)
    create_session(center["id"], test_date="2026-10-10", start_time="08:00",
                   end_time="12:00", room_label="R1", total_seats=10)
    # Exactly 60 minutes after the existing session's end: accepted (>= boundary).
    resp = api.create_session(
        center["id"],
        create_session_payload(test_date="2026-10-10", start_time="13:00",
                               end_time="15:00", room_label="R1", total_seats=10),
        program_admin_headers,
    )
    session2 = validate_success(resp, 201)
    assert session2["room_label"] == "R1"
    # The buffer is per-room: a different room on the same date is free.
    resp = api.create_session(
        center["id"],
        create_session_payload(test_date="2026-10-10", start_time="08:30",
                               end_time="11:00", room_label="R2", total_seats=10),
        program_admin_headers,
    )
    session3 = validate_success(resp, 201)
    assert session3["room_label"] == "R2"


def test_lock_before_test_date_rejected(api):
    """PRD §3.2: "publication-to-lock moves `PUBLISHED` to `LOCKED` and
    requires the current logical-clock UTC date to equal the session's
    `test_date` exactly, failing with `ERR_LOCK_WINDOW_NOT_OPEN` on any other
    day."
    PRD §2.5: "Before any administrative set operation, the clock reads exactly
    `2026-09-01T00:00:00Z`."

    Design: Corner/validations/lock_before_test_date_rejected
    """
    center = create_authorized_center(name="Center LW", facility_seat_capacity=20)
    manager = add_staff(center["id"], "Mgr LW", "CENTER_MANAGER", "ADVANCED")
    session = create_published_session(center["id"], manager["id"],
                                       test_date="2026-10-10")
    # The clock is never set: it still reads 2026-09-01, not the test date.
    resp = api.lock_session(session["id"], make_center_manager_headers(manager["id"]))
    validate_error(resp, ApiErrorId.ERR_LOCK_WINDOW_NOT_OPEN)
    assert get_session(session["id"])["status"] == "PUBLISHED"


def test_default_clock_lock_on_matching_date(api):
    """PRD §2.5: "Before any administrative set operation, the clock reads
    exactly `2026-09-01T00:00:00Z`."
    PRD §3.2: "publication-to-lock moves `PUBLISHED` to `LOCKED` and requires
    the current logical-clock UTC date to equal the session's `test_date`
    exactly, failing with `ERR_LOCK_WINDOW_NOT_OPEN` on any other day."

    Design: Corner/cross_cutting_complexity_layers/default_clock_2026_09_01_lock_works
    """
    center = create_authorized_center(name="Center DF", facility_seat_capacity=20)
    manager = add_staff(center["id"], "Mgr DF", "CENTER_MANAGER", "ADVANCED")
    session = create_published_session(center["id"], manager["id"],
                                       test_date="2026-09-01")
    # No clock call is ever made: the default clock date equals the test date.
    locked = validate_success(
        api.lock_session(session["id"], make_center_manager_headers(manager["id"])),
        200,
    )
    assert locked["status"] == "LOCKED"


def test_pagination_defaults_empty_sessions_list(api, program_admin_headers):
    """PRD §2.3: "The `limit` parameter caps the number of items returned: it
    defaults to 10 when omitted, and any supplied value must be at least 1 and
    at most 100. The `offset` parameter controls how many items are skipped
    and defaults to 0."
    PRD §2.3: "List responses carry four pagination fields in the `meta`
    object of the envelope: `limit`, `offset`, `total_count`, and `has_more`."

    Design: Corner/endpoints/pagination_defaults_empty_sessions_list
    """
    center = create_center(name="Center PG", facility_seat_capacity=10,
                           equipment_list=[])
    data, meta = validate_paginated(
        api.list_sessions(center["id"], program_admin_headers)
    )
    assert data == []
    assert meta["total_count"] == 0
    assert meta["has_more"] is False
    assert meta["limit"] == 10
    assert meta["offset"] == 0


def test_session_get_not_found_returns_404(api, program_admin_headers):
    """PRD §2.6: "Path-template resources are validated left to right — center
    first, then session, audit, or staff, then registration, score record,
    review case, or report. The first id that does not exist fails the request
    with `ERR_NOT_FOUND` (HTTP 404)."

    Design: Corner/entities/session_get_not_found_returns_404
    """
    resp = api.get_session(NON_EXISTENT_UUID, program_admin_headers)
    validate_error(resp, ApiErrorId.ERR_NOT_FOUND)
