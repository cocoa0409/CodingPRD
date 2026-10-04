"""Difficulty probe — resource_temporal_overlap: half-open interval semantics
on same-level exam windows (adjacency legal, strict-inside collides) and the
closed-interval-plus-buffer blackout rule on test centers."""
from test_helpers import (
    ApiErrorId,
    book_appointment,
    create_appointment_payload,
    create_candidate,
    create_enrolled_enrollment,
    create_exam_level,
    create_exam_window,
    create_exam_window_payload,
    create_test_center,
    list_appointments,
    list_exam_windows,
    make_candidate_headers,
    set_logical_clock,
    validate_error,
    validate_success,
)

CLOCK = "2027-01-05T00:00:00Z"

ADJACENT_WINDOW = {
    "window_opens_at": "2027-03-15T00:00:00Z",
    "window_closes_at": "2027-03-29T00:00:00Z",
    "scheduling_deadline_at": "2027-03-01T00:00:00Z",
    "reschedule_deadline_at": "2027-03-10T00:00:00Z",
    "early_fee_deadline_at": "2027-02-20T00:00:00Z",
}
OVERLAPPING_WINDOW = {
    "window_opens_at": "2027-03-14T12:00:00Z",
    "window_closes_at": "2027-03-28T00:00:00Z",
    "scheduling_deadline_at": "2027-03-01T00:00:00Z",
    "reschedule_deadline_at": "2027-03-10T00:00:00Z",
    "early_fee_deadline_at": "2027-02-20T00:00:00Z",
}

BLACKOUT = [
    {
        "blackout_start_date": "2027-03-05",
        "blackout_end_date": "2027-03-07",
        "reason": "HVAC maintenance",
    }
]


def _blackout_setup():
    """Two ENROLLED candidates and a capacity-2 center closed 2027-03-05
    through 2027-03-07 (inclusive, plus a one-day buffer each side)."""
    set_logical_clock(CLOCK)
    cand_a = create_candidate()
    enr_a = create_enrolled_enrollment(cand_a["id"])
    cand_b = create_candidate(
        email="b.cand@example.com",
        full_name="B Candidate",
        date_of_birth="1993-09-30",
        gov_id_number="GOV-B-1002",
    )
    enr_b = create_enrolled_enrollment(cand_b["id"])
    level = create_exam_level()
    window = create_exam_window(level["id"])
    center = create_test_center(
        name="Blackout Center", daily_seat_capacity=2, blackout_windows=BLACKOUT
    )
    ctx_a = {
        "candidate": cand_a,
        "enrollment": enr_a,
        "window": window,
        "center": center,
        "candidate_headers": make_candidate_headers(cand_a["id"]),
    }
    ctx_b = {
        "candidate": cand_b,
        "enrollment": enr_b,
        "window": window,
        "center": center,
        "candidate_headers": make_candidate_headers(cand_b["id"]),
    }
    return ctx_a, ctx_b, center


class TestWindowOverlap:
    def test_adjacent_window_allowed(self, api, program_admin_headers):
        """PRD §2.9: "Exam windows are **half-open** intervals: a window covers
        every instant from its `window_opens_at` (inclusive) up to but not
        including its `window_closes_at`. Two windows of the same level whose
        boundaries merely touch do not overlap."

        Design: Difficulty/resource_temporal_overlap/same_level_window_half_open_overlap
        """
        set_logical_clock(CLOCK)
        level = create_exam_level()
        create_exam_window(level["id"])
        resp = api.create_exam_window(
            create_exam_window_payload(level["id"], **ADJACENT_WINDOW),
            program_admin_headers,
        )
        data = validate_success(resp, 201)
        assert data["status"] == "OPEN"
        rows = list_exam_windows(params={"exam_level_id": level["id"]})
        assert len(rows) == 2

    def test_overlapping_window_rejected(self, api, program_admin_headers):
        """PRD §3.2: "Two windows of the same level may not overlap under the
        half-open convention — adjacent windows whose boundaries merely touch
        are allowed — and a conflicting creation is rejected with
        `ERR_WINDOW_OVERLAP`."

        Design: Difficulty/resource_temporal_overlap/same_level_window_half_open_overlap
        """
        set_logical_clock(CLOCK)
        level = create_exam_level()
        create_exam_window(level["id"])
        create_exam_window(level["id"], **ADJACENT_WINDOW)
        resp = api.create_exam_window(
            create_exam_window_payload(level["id"], **OVERLAPPING_WINDOW),
            program_admin_headers,
        )
        validate_error(resp, ApiErrorId.ERR_WINDOW_OVERLAP)
        assert resp.status_code == 409
        rows = list_exam_windows(params={"exam_level_id": level["id"]})
        assert len(rows) == 2


class TestCenterBlackout:
    def test_blackout_buffer_day_rejected(self, api):
        """PRD §3.2: "Each blackout entry carries a `blackout_start_date`, a
        `blackout_end_date`, and a `reason`; both dates are ISO dates and
        **both bounds are inclusive**, and a one-day buffer on each side of the
        closed range also blocks bookings. Any attempt to seat a candidate at
        that center on a blocked date is rejected with
        `ERR_CENTER_BLACKOUT_CONFLICT`."

        Design: Difficulty/resource_temporal_overlap/center_blackout_closed_interval_with_buffer
        """
        ctx_a, _ctx_b, _center = _blackout_setup()
        blocked = api.create_appointment(
            create_appointment_payload(
                ctx_a["enrollment"]["id"],
                ctx_a["window"]["id"],
                ctx_a["center"]["id"],
                exam_date="2027-03-04",
            ),
            ctx_a["candidate_headers"],
        )
        validate_error(blocked, ApiErrorId.ERR_CENTER_BLACKOUT_CONFLICT)
        assert blocked.status_code == 409
        clear = book_appointment(ctx_a, exam_date="2027-03-03")
        assert clear["booking_status"] == "SCHEDULED"

    def test_blackout_outer_edge_books(self, api):
        """PRD §3.2: "Each blackout entry carries a `blackout_start_date`, a
        `blackout_end_date`, and a `reason`; both dates are ISO dates and
        **both bounds are inclusive**, and a one-day buffer on each side of the
        closed range also blocks bookings."

        Design: Difficulty/resource_temporal_overlap/center_blackout_closed_interval_with_buffer
        """
        ctx_a, ctx_b, center = _blackout_setup()
        book_appointment(ctx_a, exam_date="2027-03-03")
        book_appointment(ctx_b, exam_date="2027-03-09", calculator_model="HP_12C")
        rows = list_appointments(params={"test_center_id": center["id"]})
        assert sorted(row["exam_date"] for row in rows) == ["2027-03-03", "2027-03-09"]
