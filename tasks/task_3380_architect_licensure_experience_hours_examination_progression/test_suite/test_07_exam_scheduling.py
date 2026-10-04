"""Examination scheduling: date floor, attempt window, day conflicts, retake
loop, state legality and validation precedence (PRD §2.6, §3.4)."""
from test_helpers import (
    ApiErrorId, TEST_USERS, authorize_exams, create_candidate,
    create_jurisdiction, fail_division, make_candidate_headers, pass_division,
    report_score, schedule_division, set_clock, validate_error,
    validate_paginated,
)

NCARB = TEST_USERS["ncarb_admin_headers"]

J1 = "J1"


def _authorized_candidate(api):
    create_jurisdiction(code=J1)
    candidate = create_candidate(home_jurisdiction_code=J1)
    auth = authorize_exams(candidate, jurisdiction_code=J1)
    return candidate, auth["divisions"]


def _division(api, candidate, code):
    ch = make_candidate_headers(candidate["id"])
    rows, _meta = validate_paginated(
        api.list_exam_progress(candidate["id"], ch, params={"division_code": code})
    )
    assert len(rows) == 1
    return rows[0]


class TestScheduleDateFloor:
    def test_schedule_date_in_past_rejected(self, api):
        """PRD §3.4: "From `ELIGIBLE`, the requested date must fall on or
        after the current date (earlier dates are rejected with
        `ERR_SCHEDULE_DATE_PAST`)".

        Design: Corner/validations/schedule_date_in_past_rejected
        """
        candidate, divisions = _authorized_candidate(api)
        set_clock("2026-09-15T00:00:00Z")
        ch = make_candidate_headers(candidate["id"])
        validate_error(
            api.schedule_exam_division(
                divisions["PCM"]["id"], {"scheduled_date": "2026-09-14"}, ch,
            ),
            ApiErrorId.ERR_SCHEDULE_DATE_PAST,
        )
        data = schedule_division(candidate, divisions["PCM"]["id"], "2026-09-15")
        assert data["status"] == "SCHEDULED", "today itself is allowed"
        assert data["scheduled_date"] == "2026-09-15"


class TestExamDayConflict:
    def test_same_calendar_day_conflicts(self, api):
        """PRD §3.4: "no other `SCHEDULED` division nor any `REGISTERED`
        supplemental exam of the same candidate may already occupy that
        calendar day, which is rejected as `ERR_EXAM_DAY_CONFLICT`".

        Design: Difficulty/resource_temporal_overlap/exam_day_closed_interval_conflict
        """
        candidate, divisions = _authorized_candidate(api)
        set_clock("2026-09-15T00:00:00Z")
        ch = make_candidate_headers(candidate["id"])
        schedule_division(candidate, divisions["PCM"]["id"], "2026-10-05")
        validate_error(
            api.schedule_exam_division(
                divisions["PA"]["id"], {"scheduled_date": "2026-10-05"}, ch,
            ),
            ApiErrorId.ERR_EXAM_DAY_CONFLICT,
        )
        pa = _division(api, candidate, "PA")
        assert pa["status"] == "ELIGIBLE", "rejection leaves PA unscheduled"

    def test_next_calendar_day_is_free(self, api):
        """PRD §3.4: "no other `SCHEDULED` division nor any `REGISTERED`
        supplemental exam of the same candidate may already occupy that
        calendar day, which is rejected as `ERR_EXAM_DAY_CONFLICT`".

        Design: Difficulty/resource_temporal_overlap/exam_day_closed_interval_conflict
        """
        candidate, divisions = _authorized_candidate(api)
        set_clock("2026-09-15T00:00:00Z")
        ch = make_candidate_headers(candidate["id"])
        schedule_division(candidate, divisions["PCM"]["id"], "2026-10-05")
        validate_error(
            api.schedule_exam_division(
                divisions["PA"]["id"], {"scheduled_date": "2026-10-05"}, ch,
            ),
            ApiErrorId.ERR_EXAM_DAY_CONFLICT,
        )
        data = schedule_division(candidate, divisions["PA"]["id"], "2026-10-06")
        assert data["status"] == "SCHEDULED"
        assert data["scheduled_date"] == "2026-10-06"


class TestStateBeatsTemporal:
    def test_already_scheduled_beats_retake_wait(self, api):
        """PRD §2.6: "When several checks could reject the same request, the
        first failure in a fixed evaluation order wins, and only that
        failure's error is returned."
        PRD §2.6 tier 4: "Dedicated state rejections at this tier include
        `ERR_DIVISION_ALREADY_PASSED`, `ERR_DIVISION_ALREADY_SCHEDULED`,
        `ERR_CERTIFICATE_EXISTS`, `ERR_EVALUATION_ALREADY_OPEN`, and
        `ERR_CERTIFICATE_NOT_ACTIVE` (all HTTP 409), as well as the
        optimistic-concurrency rejection `ERR_STALE_VERSION` (HTTP 412)."
        PRD §2.6 tier 7: "**Temporal rules.** Every deadline and window rule
        of §3: `ERR_EXPERIENCE_TOO_OLD`, `ERR_RETAKE_WAIT_NOT_ELAPSED`,
        `ERR_ATTEMPT_LIMIT_EXCEEDED`, `ERR_SCHEDULE_DATE_PAST`,
        `ERR_REASSIGN_WINDOW_NOT_OPEN`, `ERR_SUPPLEMENTAL_RETAKE_WAIT`,
        `ERR_RENEWAL_WINDOW_NOT_OPEN`, `ERR_REINSTATEMENT_WINDOW_CLOSED`, and
        `ERR_CE_ENTRY_INVALID` (all HTTP 422)."

        Design: Difficulty/priority_pair_validation_conflict/schedule_conflict_state_beats_temporal
        """
        candidate, divisions = _authorized_candidate(api)
        set_clock("2026-09-15T00:00:00Z")
        fail_division(candidate, divisions["PCM"]["id"], "2026-10-01")
        # Exactly last_failed_at + 60 days: permitted (boundary inclusive).
        schedule_division(candidate, divisions["PCM"]["id"], "2026-11-30")
        ch = make_candidate_headers(candidate["id"])
        # 2026-11-15 would violate the retake wait — but the division is
        # already SCHEDULED, and the state tier must win.
        validate_error(
            api.schedule_exam_division(
                divisions["PCM"]["id"], {"scheduled_date": "2026-11-15"}, ch,
            ),
            ApiErrorId.ERR_DIVISION_ALREADY_SCHEDULED,
        )
        pcm = _division(api, candidate, "PCM")
        assert pcm["status"] == "SCHEDULED"
        assert pcm["scheduled_date"] == "2026-11-30", (
            "original sitting untouched by the rejected request"
        )

    def test_retake_wait_fires_in_isolation(self, api):
        """PRD §3.4: "From `FAILED`, all of those checks apply plus the retake
        waiting period: the new sitting must fall at least sixty days after
        `last_failed_at`, with a sitting exactly sixty days later permitted;
        earlier requests are rejected with `ERR_RETAKE_WAIT_NOT_ELAPSED`."

        Design: Difficulty/priority_pair_validation_conflict/schedule_conflict_state_beats_temporal
        """
        candidate, divisions = _authorized_candidate(api)
        set_clock("2026-09-15T00:00:00Z")
        fail_division(candidate, divisions["PA"]["id"], "2026-10-01")
        ch = make_candidate_headers(candidate["id"])
        # From FAILED, 59 days after the failure: only the temporal rule
        # can fail here.
        validate_error(
            api.schedule_exam_division(
                divisions["PA"]["id"], {"scheduled_date": "2026-11-29"}, ch,
            ),
            ApiErrorId.ERR_RETAKE_WAIT_NOT_ELAPSED,
        )
        pa = _division(api, candidate, "PA")
        assert pa["status"] == "FAILED"
        assert pa["scheduled_date"] is None


class TestScoringStateLegality:
    def test_score_report_from_eligible_rejected(self, api):
        """PRD §3.4: "Score reporting belongs to `NcarbAdministrator` staff
        and applies to a `SCHEDULED` division whose sitting date has arrived —
        the current date must be on or after the `scheduled_date`."
        PRD §2.6: "The target resource's current state must permit the
        attempted transition; any trigger attempted from a state that does not
        list it is rejected with the generic `ERR_INVALID_STATE` (HTTP 409)."

        Design: Corner/state_machines/score_report_from_eligible_rejected
        """
        candidate, divisions = _authorized_candidate(api)
        validate_error(
            api.report_exam_score(
                divisions["PCM"]["id"],
                {"result": "PASS", "scaled_score": 75},
                NCARB,
            ),
            ApiErrorId.ERR_INVALID_STATE,
        )
        pcm = _division(api, candidate, "PCM")
        assert pcm["status"] == "ELIGIBLE"
        assert pcm["attempt_count"] == 0
        assert pcm["attempt_dates"] == []

    def test_schedule_passed_division_rejected(self, api):
        """PRD §3.4: "Attempting to schedule a division already `PASSED` is
        rejected with `ERR_DIVISION_ALREADY_PASSED`, and one already
        `SCHEDULED` with `ERR_DIVISION_ALREADY_SCHEDULED`."
        PRD §3.4: "A `PASS` increments `attempt_count` by one, appends the
        sitting date to `attempt_dates`, records the sitting date as
        `passed_at`, sets `expires_at` to the day sixty calendar months after
        the pass, stores the result and score, and clears `scheduled_date` to
        null."

        Design: Corner/state_machines/schedule_passed_division_rejected
        """
        candidate, divisions = _authorized_candidate(api)
        set_clock("2026-09-15T00:00:00Z")
        pass_division(candidate, divisions["PCM"]["id"], "2026-10-01")
        ch = make_candidate_headers(candidate["id"])
        validate_error(
            api.schedule_exam_division(
                divisions["PCM"]["id"], {"scheduled_date": "2026-11-01"}, ch,
            ),
            ApiErrorId.ERR_DIVISION_ALREADY_PASSED,
        )
        pcm = _division(api, candidate, "PCM")
        assert pcm["status"] == "PASSED"
        assert pcm["passed_at"] == "2026-10-01"
        assert pcm["expires_at"] == "2031-10-01", "passed_at + 60 months"


class TestFailRetakeCycle:
    def test_retake_at_exactly_60_days_permitted(self, api):
        """PRD §3.4: "From `FAILED`, all of those checks apply plus the retake
        waiting period: the new sitting must fall at least sixty days after
        `last_failed_at`, with a sitting exactly sixty days later permitted;
        earlier requests are rejected with `ERR_RETAKE_WAIT_NOT_ELAPSED`."

        Design: Difficulty/non_linear_state_machine/exam_division_fail_retake_cycle
        """
        candidate, divisions = _authorized_candidate(api)
        set_clock("2026-09-15T00:00:00Z")
        pcm = divisions["PCM"]["id"]
        fail_division(candidate, pcm, "2026-10-01")
        # 2026-10-01 + 60 days == 2026-11-30 (boundary inclusive).
        first = schedule_division(candidate, pcm, "2026-11-30")
        assert first["status"] == "SCHEDULED"
        assert first["scheduled_date"] == "2026-11-30"
        set_clock("2026-11-30T00:00:00Z")
        report_score(pcm, "FAIL", 58)
        # 2026-11-30 + 60 days == 2027-01-29.
        second = schedule_division(candidate, pcm, "2027-01-29")
        assert second["status"] == "SCHEDULED"
        assert second["scheduled_date"] == "2027-01-29"

    def test_two_retake_loops_converge_to_passed(self, api):
        """PRD §3.4: "A `PASS` increments `attempt_count` by one, appends the
        sitting date to `attempt_dates`, records the sitting date as
        `passed_at`, sets `expires_at` to the day sixty calendar months after
        the pass, stores the result and score, and clears `scheduled_date` to
        null."
        PRD §3.4: "A `FAIL` likewise increments `attempt_count` by one and
        appends the sitting date, records the sitting date as
        `last_failed_at`, stores the result and score, and clears
        `scheduled_date`."

        Design: Difficulty/non_linear_state_machine/exam_division_fail_retake_cycle
        """
        candidate, divisions = _authorized_candidate(api)
        set_clock("2026-09-15T00:00:00Z")
        pcm = divisions["PCM"]["id"]
        fail_division(candidate, pcm, "2026-10-01", scaled_score=55)
        fail_division(candidate, pcm, "2026-11-30", scaled_score=58)
        pass_division(candidate, pcm, "2027-01-29", scaled_score=80)
        row = _division(api, candidate, "PCM")
        assert row["status"] == "PASSED", (
            "ELIGIBLE -> SCHEDULED -> FAILED -> SCHEDULED -> FAILED -> "
            "SCHEDULED -> PASSED"
        )
        assert row["attempt_count"] == 3
        assert row["attempt_dates"] == ["2026-10-01", "2026-11-30", "2027-01-29"]
        assert row["passed_at"] == "2027-01-29"
        assert row["expires_at"] == "2032-01-29", "passed_at + 60 months"
        assert row["last_failed_at"] == "2026-11-30", "failure kept as history"
        assert row["result"] == "PASS"
        assert row["scaled_score"] == 80
        assert row["scheduled_date"] is None


class TestAttemptWindowBoundary:
    def test_attempt_window_365_day_boundary(self, api):
        """PRD §3.4: "the attempt window must have room, meaning fewer than
        three prior scored attempts on that division bear dates strictly more
        recent than the day three hundred sixty-five days before the requested
        sitting — an attempt exactly 365 days earlier no longer counts against
        the window, and a third recent attempt makes the request fail with
        `ERR_ATTEMPT_LIMIT_EXCEEDED`"; the sitting itself is otherwise legal.

        Design: Corner/calculations/attempt_window_365_day_boundary
        """
        candidate, divisions = _authorized_candidate(api)
        set_clock("2026-09-15T00:00:00Z")
        pcm = divisions["PCM"]["id"]
        fail_division(candidate, pcm, "2026-10-01", scaled_score=55)
        fail_division(candidate, pcm, "2026-12-01", scaled_score=56)
        fail_division(candidate, pcm, "2027-01-30", scaled_score=57)
        ch = make_candidate_headers(candidate["id"])
        # 2027-09-30: cutoff 2026-09-30; all three attempts (2026-10-01,
        # 2026-12-01, 2027-01-30) are strictly more recent — blocked.
        validate_error(
            api.schedule_exam_division(pcm, {"scheduled_date": "2027-09-30"}, ch),
            ApiErrorId.ERR_ATTEMPT_LIMIT_EXCEEDED,
        )
        # 2027-10-01: cutoff 2026-10-01; the attempt exactly 365 days earlier
        # no longer counts, leaving two — allowed.
        data = schedule_division(candidate, pcm, "2027-10-01")
        assert data["status"] == "SCHEDULED"
        assert data["scheduled_date"] == "2027-10-01"
