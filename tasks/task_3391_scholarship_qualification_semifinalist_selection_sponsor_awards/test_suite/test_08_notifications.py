"""Notification embargoes, per-student sequencing, and the publicity gap —
PRD §3.9.
"""
from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    accept_award,
    advance_clock,
    list_notifications,
    release_notification,
    setup_matching_run,
    setup_semifinalists_selected,
    validate_error,
    validate_success,
)

PA = TEST_USERS["program_admin_headers"]


def test_notification_embargo_and_sequence_gates(api):
    """PRD §3.9: "Every notification of the same student with a lower
    `sequence_number` must already be `RELEASED`, else
    `ERR_NOTIFICATION_SEQUENCE_VIOLATION` (HTTP 409). The logical clock must
    be at or past the notification's `embargo_until`, else
    `ERR_NOTIFICATION_EMBARGOED` (HTTP 422)."
    
    Design: Corner/validations/notification_embargo_and_sequence_gates
    """
    ctx = setup_matching_run(cycle_overrides={"national_award_slots": 1})
    student_id = ctx["student"]["id"]
    notes = list_notifications(student_id)
    assert [n["sequence_number"] for n in notes] == [1, 2, 3, 4]
    assert all(n["status"] == "EMBARGOED" for n in notes)
    n1, n2 = notes[0], notes[1]

    # Default clock 2026-09-01 is before n1's embargo 2027-09-10.
    resp_embargo = api.release_notification(n1["id"], PA)
    validate_error(resp_embargo, ApiErrorId.ERR_NOTIFICATION_EMBARGOED)

    advance_clock("2028-03-05T00:00:00Z")  # every embargo has now passed
    resp_seq = api.release_notification(n2["id"], PA)  # n1 not yet released
    validate_error(resp_seq, ApiErrorId.ERR_NOTIFICATION_SEQUENCE_VIOLATION)

    assert release_notification(n1["id"])["status"] == "RELEASED"
    assert release_notification(n2["id"])["status"] == "RELEASED"


def _setup_publicity_ready(ctx_api):
    """Cycle through matching with one national award; the award is accepted at
    the default clock (before its 2026-10-01 acceptance deadline, so the clock
    advance past the embargoes cannot sweep it and supersede the notifications
    under test), then the clock moves to 2028-03-02T10:00:00Z and sequences
    1-3 are released."""
    ctx = setup_matching_run(cycle_overrides={"national_award_slots": 1})
    accept_award(ctx["award"]["id"], ctx["student"]["id"])
    advance_clock("2028-03-02T10:00:00Z")
    notes = list_notifications(ctx["student"]["id"])
    for note in notes[:3]:
        release_notification(note["id"])
    return ctx, notes[3]


def test_publicity_gap_rejects_release_inside_two_days(api):
    """PRD §3.9: "And for a `PUBLIC_ANNOUNCEMENT` specifically, the logical clock
    must additionally be at least 2 days past the most recent
    `released_logical_at` among the cycle's `RELEASED` `AWARD_OFFER`
    notifications — the publicity gap — else `ERR_PUBLICITY_WINDOW_TOO_EARLY`
    (HTTP 422)."
    
    Design: Difficulty/resource_temporal_overlap/publicity_gap_minimum_separation
    """
    ctx, n4 = _setup_publicity_ready(api)
    # AWARD_OFFER was released at 2028-03-02T10:00:00Z; the clock is still there.
    resp = api.release_notification(n4["id"], PA)
    validate_error(resp, ApiErrorId.ERR_PUBLICITY_WINDOW_TOO_EARLY)
    notes = list_notifications(ctx["student"]["id"])
    assert notes[3]["status"] == "EMBARGOED"
    assert notes[3]["notice_type"] == "PUBLIC_ANNOUNCEMENT"
    assert notes[3]["sequence_number"] == 4


def test_publicity_gap_release_at_exactly_two_days_succeeds(api):
    """PRD §3.9: the PUBLIC_ANNOUNCEMENT gate requires the clock "at least 2 days
    past the most recent `released_logical_at` among the cycle's `RELEASED`
    `AWARD_OFFER` notifications", and "A successful release stamps
    `released_logical_at` from the logical clock".
    
    Design: Difficulty/resource_temporal_overlap/publicity_gap_minimum_separation
    """
    ctx, n4 = _setup_publicity_ready(api)
    advance_clock("2028-03-04T10:00:00Z")  # offer release + exactly 2 days
    released = validate_success(api.release_notification(n4["id"], PA))
    assert released["status"] == "RELEASED"
    assert released["released_logical_at"] == "2028-03-04T10:00:00Z"
    assert released["notice_type"] == "PUBLIC_ANNOUNCEMENT"
    assert released["sequence_number"] == 4
