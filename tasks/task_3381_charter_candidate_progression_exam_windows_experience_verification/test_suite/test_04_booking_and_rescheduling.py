"""Booking and rescheduling rules: the pinned retake-eligibility chain,
per-center-date seat accounting, list pagination, window retargeting, the
reschedule fee card, and optimistic concurrency on reschedule."""
from test_helpers import (
    ApiErrorId,
    PROGRAM_FEE_CENTS,
    book_appointment,
    book_checkin_score,
    compute_reschedule_fee_cents,
    create_appointment_payload,
    create_candidate,
    create_enrolled_enrollment,
    create_exam_level,
    create_exam_window,
    create_test_center,
    get_appointment,
    get_candidate,
    get_enrollment_of_candidate,
    list_appointments,
    list_exam_attempts,
    make_candidate_headers,
    reschedule_appointment_payload,
    set_logical_clock,
    setup_bookable_context,
    validate_error,
    validate_paginated,
    validate_success,
)

CLOCK = "2027-01-05T00:00:00Z"

# LEVEL_II window shape (canonical, non-overlapping with the LEVEL_I default).
LEVEL_II_WINDOW = {
    "window_opens_at": "2027-05-03T00:00:00Z",
    "window_closes_at": "2027-05-17T00:00:00Z",
    "scheduling_deadline_at": "2027-04-19T00:00:00Z",
    "reschedule_deadline_at": "2027-04-26T00:00:00Z",
    "early_fee_deadline_at": "2027-03-31T00:00:00Z",
}

# Two later LEVEL_I windows: WN opens exactly when the default window closes
# (legal adjacency for creation, too soon for a retaker); WL opens strictly
# after it. Deadlines respect PRD §3.2: scheduling_deadline_at no later than
# the opening, early_fee_deadline_at no later than the scheduling deadline,
# reschedule_deadline_at no later than the close.
LATER_WINDOW_N = {
    "window_opens_at": "2027-03-15T00:00:00Z",
    "window_closes_at": "2027-03-29T00:00:00Z",
    "scheduling_deadline_at": "2027-03-15T00:00:00Z",
    "reschedule_deadline_at": "2027-03-25T00:00:00Z",
    "early_fee_deadline_at": "2027-03-10T00:00:00Z",
}
LATER_WINDOW_L = {
    "window_opens_at": "2027-03-29T00:00:00Z",
    "window_closes_at": "2027-04-12T00:00:00Z",
    "scheduling_deadline_at": "2027-03-29T00:00:00Z",
    "reschedule_deadline_at": "2027-04-05T00:00:00Z",
    "early_fee_deadline_at": "2027-03-20T00:00:00Z",
}


def _enrolled_candidate(email, full_name, date_of_birth, gov_id_number):
    candidate = create_candidate(
        email=email,
        full_name=full_name,
        date_of_birth=date_of_birth,
        gov_id_number=gov_id_number,
    )
    enrollment = create_enrolled_enrollment(candidate["id"])
    return candidate, enrollment


def _mini_context(candidate, enrollment, window, center):
    return {
        "candidate": candidate,
        "enrollment": enrollment,
        "window": window,
        "center": center,
        "candidate_headers": make_candidate_headers(candidate["id"]),
    }


class TestBookingRules:
    def test_booking_level_ii_without_prerequisite_rejected(self, api):
        """PRD §3.3: "Third, the target level's predecessor in the enum ordering
        — if it has one — must appear in the passed set, else
        `ERR_PREREQUISITE_LEVEL_NOT_PASSED`."

        Design: Corner/state_machines/c_booking_level_ii_without_prerequisite_rejected
        """
        context = setup_bookable_context()
        level_ii = create_exam_level(level_code="LEVEL_II", mps_scaled_score=720)
        window_ii = create_exam_window(level_ii["id"], **LEVEL_II_WINDOW)
        resp = api.create_appointment(
            create_appointment_payload(
                context["enrollment"]["id"],
                window_ii["id"],
                context["center"]["id"],
                exam_date="2027-05-05",
            ),
            context["candidate_headers"],
        )
        validate_error(resp, ApiErrorId.ERR_PREREQUISITE_LEVEL_NOT_PASSED)
        assert resp.status_code == 422
        assert (
            list_appointments(
                params={"program_enrollment_id": context["enrollment"]["id"]}
            )
            == []
        )
        enrollment = get_enrollment_of_candidate(context["candidate"]["id"])
        assert enrollment["outstanding_balance_cents"] == 0

    def test_double_booking_same_level_rejected(self, api):
        """PRD §3.3: "A candidate may hold only one active appointment per level
        — active meaning `SCHEDULED` or `CHECKED_IN` — and a second active
        booking for the same level is rejected with `ERR_DOUBLE_BOOKING_LEVEL`."

        Design: Corner/errors/c_double_booking_same_level_rejected
        """
        context = setup_bookable_context()
        book_appointment(context, exam_date="2027-03-03", pay_fee=False)
        resp = api.create_appointment(
            create_appointment_payload(
                context["enrollment"]["id"],
                context["window"]["id"],
                context["center"]["id"],
                exam_date="2027-03-04",
            ),
            context["candidate_headers"],
        )
        validate_error(resp, ApiErrorId.ERR_DOUBLE_BOOKING_LEVEL)
        assert resp.status_code == 409
        rows = list_appointments(
            params={"program_enrollment_id": context["enrollment"]["id"]}
        )
        assert len(rows) == 1

    def test_booking_after_scheduling_deadline_rejected(self, api):
        """PRD §3.3: "The enrollment must be `ENROLLED`
        (`ERR_ENROLLMENT_NOT_ENROLLED`); the window must be `OPEN`
        (`ERR_WINDOW_NOT_OPEN`); the logical clock must be no later than the
        window's `scheduling_deadline_at` (`ERR_WINDOW_SCHEDULING_CLOSED`)."

        Design: Corner/errors/c_booking_after_scheduling_deadline_rejected
        """
        context = setup_bookable_context()
        set_logical_clock("2027-02-21T00:00:00Z")
        resp = api.create_appointment(
            create_appointment_payload(
                context["enrollment"]["id"],
                context["window"]["id"],
                context["center"]["id"],
                exam_date="2027-03-03",
            ),
            context["candidate_headers"],
        )
        validate_error(resp, ApiErrorId.ERR_WINDOW_SCHEDULING_CLOSED)
        assert resp.status_code == 422
        assert (
            list_appointments(
                params={"program_enrollment_id": context["enrollment"]["id"]}
            )
            == []
        )

    def test_retake_into_not_strictly_later_window_rejected(self, api):
        """PRD §3.3: "Fifth, if the candidate has a most-recent failed attempt
        at the target level — latest by creation among attempts with result
        `FAIL` and validity `VALID` or `REINSTATED` — the target window's
        opening must lie strictly after that failed attempt's window closed,
        else `ERR_RETAKE_WINDOW_TOO_SOON`."

        Design: Corner/errors/c_retake_into_not_strictly_later_window_rejected
        """
        context = setup_bookable_context()
        window_n = create_exam_window(context["level"]["id"], **LATER_WINDOW_N)
        window_l = create_exam_window(context["level"]["id"], **LATER_WINDOW_L)
        # Score exactly at the default window's close: the retake booking below
        # must occur no later than WN's scheduling deadline, which PRD §3.2
        # caps at WN's opening (== the failed attempt's window close).
        book_checkin_score(
            context["candidate"],
            context["enrollment"],
            context["window"],
            context["center"],
            exam_date="2027-03-03",
            scaled_score=600,
            score_clock="2027-03-15T00:00:00Z",
        )
        resp = api.create_appointment(
            create_appointment_payload(
                context["enrollment"]["id"],
                window_n["id"],
                context["center"]["id"],
                exam_date="2027-03-20",
            ),
            context["candidate_headers"],
        )
        validate_error(resp, ApiErrorId.ERR_RETAKE_WINDOW_TOO_SOON)
        assert resp.status_code == 422
        enrollment = get_enrollment_of_candidate(context["candidate"]["id"])
        assert enrollment["outstanding_balance_cents"] == 0
        ok = api.create_appointment(
            create_appointment_payload(
                context["enrollment"]["id"],
                window_l["id"],
                context["center"]["id"],
                exam_date="2027-04-01",
            ),
            context["candidate_headers"],
        )
        data = validate_success(ok, 201)
        assert data["fee_tier"] == "EARLY"

    def test_level_already_passed_rejected(self, api):
        """PRD §3.3: "Second, if the target level is already in that set, the
        booking is rejected with `ERR_LEVEL_ALREADY_PASSED`."

        Design: Corner/errors/c_level_already_passed_rejected
        """
        context = setup_bookable_context()
        window_later = create_exam_window(
            context["level"]["id"],
            window_opens_at="2027-04-01T00:00:00Z",
            window_closes_at="2027-04-15T00:00:00Z",
            scheduling_deadline_at="2027-03-20T00:00:00Z",
            reschedule_deadline_at="2027-03-25T00:00:00Z",
            early_fee_deadline_at="2027-02-28T00:00:00Z",
        )
        book_checkin_score(
            context["candidate"],
            context["enrollment"],
            context["window"],
            context["center"],
            exam_date="2027-03-03",
            scaled_score=context["level"]["mps_scaled_score"],
            score_clock="2027-03-16T00:00:00Z",
        )
        resp = api.create_appointment(
            create_appointment_payload(
                context["enrollment"]["id"],
                window_later["id"],
                context["center"]["id"],
                exam_date="2027-04-02",
            ),
            context["candidate_headers"],
        )
        validate_error(resp, ApiErrorId.ERR_LEVEL_ALREADY_PASSED)
        assert resp.status_code == 422
        candidate = get_candidate(context["candidate"]["id"])
        assert candidate["highest_level_passed_code"] == "LEVEL_I"

    def test_attempt_cap_counts_only_target_level_valid_attempts(self, api):
        """PRD §3.3: "Fourth, the count of the candidate's attempts at the
        target level with validity `VALID` or `REINSTATED` must be smaller than
        the level's `max_attempts` — invalidated attempts do not count — else
        `ERR_MAX_ATTEMPTS_REACHED`."

        Design: Corner/calculations/c_attempt_cap_counts_only_target_level_valid_attempts
        """
        context = setup_bookable_context(level_overrides={"max_attempts": 1})
        window_l = create_exam_window(context["level"]["id"], **LATER_WINDOW_L)
        book_checkin_score(
            context["candidate"],
            context["enrollment"],
            context["window"],
            context["center"],
            exam_date="2027-03-03",
            scaled_score=600,
            score_clock="2027-03-16T00:00:00Z",
        )
        resp = api.create_appointment(
            create_appointment_payload(
                context["enrollment"]["id"],
                window_l["id"],
                context["center"]["id"],
                exam_date="2027-04-01",
            ),
            context["candidate_headers"],
        )
        validate_error(resp, ApiErrorId.ERR_MAX_ATTEMPTS_REACHED)
        assert resp.status_code == 422
        attempts = list_exam_attempts(
            params={"candidate_id": context["candidate"]["id"]}
        )
        assert len(attempts) == 1
        assert attempts[0]["result"] == "FAIL"
        enrollment = get_enrollment_of_candidate(context["candidate"]["id"])
        assert enrollment["lifetime_charges_cents"] == PROGRAM_FEE_CENTS + 94000


class TestAppointmentListing:
    def test_appointments_list_paginates_filters_and_counts(self, api, program_admin_headers):
        """PRD §2.3: "The `limit` parameter caps the number of items returned:
        it defaults to 10, accepts a minimum of 1 and a maximum of 100. The
        `offset` parameter skips a number of items from the start of the result
        set and defaults to 0."
        PRD §2.3: "Paginated list responses carry four pagination fields in the
        `meta` object of the envelope: `limit`, `offset`, `total_count`, and
        `has_more`."
        PRD §3.3: "The candidate's `candidate_id` is denormalized onto the
        appointment so that the appointments listing can be filtered by
        `candidate_id` — alongside `program_enrollment_id`, `exam_window_id`,
        `test_center_id`, `booking_status` and `status` filters"

        Design: Corner/entities/c_appointments_list_paginates_filters_and_counts
        """
        set_logical_clock(CLOCK)
        level = create_exam_level()
        window = create_exam_window(level["id"])
        center = create_test_center(daily_seat_capacity=5)
        specs = [
            ("a.cand@example.com", "A Candidate", "1995-04-12", "GOV-A-1001", "2027-03-03"),
            ("b.cand@example.com", "B Candidate", "1993-09-30", "GOV-B-1002", "2027-03-04"),
            ("c.cand@example.com", "C Candidate", "1990-01-20", "GOV-C-1003", "2027-03-05"),
        ]
        for email, full_name, dob, gov_id, exam_date in specs:
            candidate, enrollment = _enrolled_candidate(email, full_name, dob, gov_id)
            book_appointment(
                _mini_context(candidate, enrollment, window, center),
                exam_date=exam_date,
                calculator_model="HP_12C" if exam_date == "2027-03-04" else "TI_BA_II_PLUS",
            )
        first, meta_first = validate_paginated(
            api.list_appointments(
                program_admin_headers,
                params={"test_center_id": center["id"], "limit": 2, "offset": 0},
            )
        )
        assert len(first) == 2
        assert meta_first["total_count"] == 3
        assert meta_first["has_more"] is True
        last, meta_last = validate_paginated(
            api.list_appointments(
                program_admin_headers,
                params={"test_center_id": center["id"], "limit": 2, "offset": 2},
            )
        )
        assert len(last) == 1
        assert meta_last["total_count"] == 3
        assert meta_last["has_more"] is False
        filtered, _ = validate_paginated(
            api.list_appointments(
                program_admin_headers,
                params={"test_center_id": center["id"], "booking_status": "SCHEDULED"},
            )
        )
        assert len(filtered) == 3
        by_window, meta_window = validate_paginated(
            api.list_appointments(
                program_admin_headers, params={"exam_window_id": window["id"]}
            )
        )
        assert len(by_window) == 3
        assert meta_window["limit"] == 10
        assert meta_window["offset"] == 0


class TestRescheduling:
    def test_reschedule_window_level_mismatch_rejected(self, api):
        """PRD §3.4: "When the window does change, four further checks bind the
        retarget: the target window must be `OPEN` (`ERR_WINDOW_NOT_OPEN`), it
        must belong to the same level (`ERR_WINDOW_LEVEL_MISMATCH`), the clock
        must be no later than the target's `scheduling_deadline_at`
        (`ERR_WINDOW_SCHEDULING_CLOSED`), and the retake gap of §3.3 is
        re-checked against the new window (`ERR_RETAKE_WINDOW_TOO_SOON`)."

        Design: Corner/errors/c_reschedule_window_level_mismatch_rejected
        """
        context = setup_bookable_context()
        level_ii = create_exam_level(level_code="LEVEL_II", mps_scaled_score=720)
        window_ii = create_exam_window(level_ii["id"], **LEVEL_II_WINDOW)
        appointment = book_appointment(context, pay_fee=False)
        resp = api.reschedule_appointment(
            appointment["id"],
            reschedule_appointment_payload(
                appointment["version"],
                exam_window_id=window_ii["id"],
                exam_date="2027-05-05",
            ),
            context["candidate_headers"],
        )
        validate_error(resp, ApiErrorId.ERR_WINDOW_LEVEL_MISMATCH)
        assert resp.status_code == 422
        after = get_appointment(appointment["id"])
        assert after["exam_window_id"] == context["window"]["id"]
        assert after["reschedule_count"] == 0

    def test_reschedule_fee_day14_is_not_late(self, api):
        """PRD §3.4: "The fee starts at a base of 25,000 cents. If the notice
        period is shorter than 14 days, a late surcharge of 25,000 cents is
        added."

        Design: Corner/calculations/c_reschedule_fee_day14_is_not_late
        """
        assert compute_reschedule_fee_cents(14, 0) == 25000
        context = setup_bookable_context()
        appointment = book_appointment(context, exam_date="2027-03-14")
        set_logical_clock("2027-02-28T00:00:00Z")
        resp = api.reschedule_appointment(
            appointment["id"],
            reschedule_appointment_payload(
                appointment["version"], exam_date="2027-03-13"
            ),
            context["candidate_headers"],
        )
        data = validate_success(resp, 200)
        assert data["reschedule_fees_total_cents"] == 25000
        assert data["reschedule_count"] == 1

    def test_occ_reschedule_stale_version_returns_412(self, api):
        """PRD §2.7: "Rescheduling an appointment requires
        `expected_appointment_version`, carrying the caller's last observed
        `version` of that appointment. If the appointment's current `version` no
        longer matches — because a prior reschedule, a cancellation, or a
        check-in side effect has advanced it since the caller's read — the
        request is rejected as stale with `ERR_STALE_VERSION` (HTTP 412); the
        supersede must not proceed on an unobserved state."

        Design: Corner/cross_cutting_layers/c_occ_reschedule_stale_version_returns_412
        """
        context = setup_bookable_context()
        appointment = book_appointment(context, exam_date="2027-03-03")
        first = api.reschedule_appointment(
            appointment["id"],
            reschedule_appointment_payload(
                appointment["version"], exam_date="2027-03-12"
            ),
            context["candidate_headers"],
        )
        first_data = validate_success(first, 200)
        assert first_data["version"] == 2
        assert first_data["reschedule_fees_total_cents"] == 25000
        stale = api.reschedule_appointment(
            appointment["id"],
            reschedule_appointment_payload(
                appointment["version"], exam_date="2027-03-13"
            ),
            context["candidate_headers"],
        )
        validate_error(stale, ApiErrorId.ERR_STALE_VERSION)
        assert stale.status_code == 412
        after = get_appointment(appointment["id"])
        assert after["version"] == 2
        assert after["exam_date"] == "2027-03-12"
        assert after["reschedule_count"] == 1
