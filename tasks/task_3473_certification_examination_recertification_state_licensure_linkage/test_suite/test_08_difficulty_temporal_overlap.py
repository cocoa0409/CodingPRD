"""Queue A — resource_temporal_overlap: half-open interval semantics on two
different resources (the candidate's exam-delivery calendar; the VERIFIED
psychomotor credential window).
"""
from test_helpers import (
    ApiErrorId,
    advance_clock,
    api_client,
    create_approved_exam_application,
    create_psychomotor,
    create_psychomotor_payload,
    make_candidate_headers,
    make_state_official_headers,
    schedule_attempt,
    schedule_attempt_payload,
    setup_approved_application,
    setup_candidate_with_verified_completion,
    validate_error,
    validate_success,
    verify_psychomotor,
)


def test_attempt_slot_half_open_overlap(api):
    """PRD §3.4: "A candidate may also hold at most one `SCHEDULED` attempt
    covering any instant: a new window conflicts with an existing scheduled
    window when the existing start is strictly before the new end and the new
    start is strictly before the existing end — a half-open intersection, so
    touching endpoints, the new window beginning exactly when the old one ends
    or ending exactly when the old one begins, do not conflict — and a conflict
    is rejected with `ERR_ATTEMPT_SLOT_OVERLAP`."

    [11:00,13:00) intersects the existing [10:00,12:00) and is rejected; the
    merely-touching [12:00,14:00) is allowed.

    Design: Difficulty/resource_temporal_overlap/attempt_slot_half_open_overlap
    """
    ctx = setup_approved_application()
    candidate_id = ctx["candidate"]["id"]
    second = create_approved_exam_application(
        candidate_id, ctx["level"]["id"], ctx["completion_record"]["id"],
    )
    first_attempt = schedule_attempt(
        candidate_id, ctx["att_id"], "2026-09-02T10:00:00Z", "2026-09-02T12:00:00Z",
    )
    assert first_attempt["status"] == "SCHEDULED"

    resp = api_client.schedule_cognitive_exam_attempt(
        schedule_attempt_payload(
            second["att_id"], "2026-09-02T11:00:00Z", "2026-09-02T13:00:00Z",
        ),
        make_candidate_headers(candidate_id),
    )
    validate_error(resp, ApiErrorId.ERR_ATTEMPT_SLOT_OVERLAP)

    touching = schedule_attempt(
        candidate_id, second["att_id"], "2026-09-02T12:00:00Z", "2026-09-02T14:00:00Z",
    )
    assert touching["status"] == "SCHEDULED", "adjacency at the endpoint is not a conflict"


def test_psychomotor_validity_window_containment(api):
    """PRD §3.5: "Every `VERIFIED` psychomotor record for a candidate and level
    defines a half-open validity window running from the calendar date of its
    `verified_at` up to — but not including — the date twenty-four calendar
    months later. A new submission whose `exam_date` falls inside any such
    window is rejected with `ERR_ACTIVE_VERIFICATION_EXISTS`; an exam date
    exactly on the twenty-four-month boundary lies outside the window and is
    allowed. `SUBMITTED` and `REJECTED` records define no window."

    With the first record verified at 2026-09-05 (window
    [2026-09-05, 2028-09-05)): exam_date 2026-09-08 is inside and rejected;
    exam_date exactly 2028-09-05 is outside and allowed.

    Design: Difficulty/resource_temporal_overlap/psychomotor_validity_window_containment
    """
    ctx = setup_candidate_with_verified_completion()
    candidate_id = ctx["candidate"]["id"]
    level_id = ctx["level"]["id"]
    record_id = ctx["completion_record"]["id"]

    advance_clock("2026-09-03T00:00:00Z")
    first = create_psychomotor(candidate_id, level_id, record_id, exam_date="2026-09-03")
    advance_clock("2026-09-05T00:00:00Z")
    verify_psychomotor(first["id"])  # window opens at the 2026-09-05 decision

    advance_clock("2026-09-10T00:00:00Z")
    resp = api_client.create_psychomotor_verification(
        create_psychomotor_payload(
            candidate_id, level_id, record_id, exam_date="2026-09-08",
        ),
        make_state_official_headers("so-1"),
    )
    validate_error(resp, ApiErrorId.ERR_ACTIVE_VERIFICATION_EXISTS)

    advance_clock("2028-09-05T00:00:00Z")
    boundary = api_client.create_psychomotor_verification(
        create_psychomotor_payload(
            candidate_id, level_id, record_id, exam_date="2028-09-05",
        ),
        make_state_official_headers("so-1"),
    )
    data = validate_success(boundary, 201)
    assert data["status"] == "SUBMITTED", (
        "exam_date exactly on the window's 24-month end lies outside the half-open window"
    )
