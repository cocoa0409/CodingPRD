"""Rolling-clock validity, expiry sweep boundary, score confidentiality, and
supplemental exam rules (PRD §2.8, §3.4, §3.5)."""
from test_helpers import (
    ApiErrorId, TEST_USERS, authorize_exams, create_candidate,
    create_jurisdiction, make_candidate_headers, pass_division,
    schedule_division, set_clock, validate_error, validate_paginated,
    validate_success, run_expiry_sweep,
)

J1 = "J1"
NCARB = TEST_USERS["ncarb_admin_headers"]

# Item-level examination content must never appear (PRD §2.8).
_FORBIDDEN_CONTENT_KEYS = {
    "questions", "answers", "items", "item_level", "subscores",
    "content", "exam_content", "breakdown", "responses", "item_bank",
}


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


class TestRollingClockWindowMembership:
    def _setup_two_passes(self, api):
        """CE passed 2026-10-01 (expires 2031-10-01); PA passed 2027-10-01
        (expires 2032-10-01); clock then advanced to 2031-10-15."""
        candidate, divisions = _authorized_candidate(api)
        pass_division(candidate, divisions["CE"]["id"], "2026-10-01")
        pass_division(candidate, divisions["PA"]["id"], "2027-10-01")
        set_clock("2031-10-15T00:00:00Z")
        return candidate, divisions

    def test_earliest_pass_lapses_while_later_pass_survives(self, api):
        """PRD §3.4: "Each pass remains valid until the current date reaches
        its own `expires_at`, sixty calendar months after that pass's date; on
        the boundary day itself the pass is already expired, because expiry
        triggers when the current date is on or after `expires_at`. The expiry
        sweep moves every such `PASSED` row to `EXPIRED`. Because validity is
        judged per division against its own pass date, the earliest pass
        anchors the effective window: once the oldest pass crosses its
        sixty-month boundary, that division lapses even though later passes
        remain valid until their own anniversaries."

        Design: Difficulty/combinatorial_formula/rolling_clock_window_membership
        """
        candidate, _d = self._setup_two_passes(api)
        sweep = run_expiry_sweep()
        assert sweep["expired_divisions"] == 1, "only the 2026-10-01 pass lapsed"
        ce = _division(api, candidate, "CE")
        pa = _division(api, candidate, "PA")
        assert ce["status"] == "EXPIRED"
        assert pa["status"] == "PASSED"
        assert pa["expires_at"] == "2032-10-01", (
            "survives past its sibling's lapse on its own anniversary"
        )

    def test_expired_division_can_be_scheduled_again(self, api):
        """PRD §3.4: "An `EXPIRED` division is not a dead end: it may be
        scheduled again exactly as an `ELIGIBLE` one can."
        PRD §3.4: "When a lapse leaves the candidate with fewer than six valid
        passes, `exam_status` falls back from `ALL_PASSED` to `AUTHORIZED` and
        `certificate_eligible` is recomputed — a lapse can undo a completed
        examination set."

        Design: Difficulty/combinatorial_formula/rolling_clock_window_membership
        """
        candidate, divisions = self._setup_two_passes(api)
        run_expiry_sweep()
        data = schedule_division(candidate, divisions["CE"]["id"], "2031-11-01")
        assert data["status"] == "SCHEDULED", "EXPIRED -> SCHEDULED is legal"
        assert data["scheduled_date"] == "2031-11-01"
        summary = validate_success(api.get_candidate_summary(
            candidate["id"], make_candidate_headers(candidate["id"]),
        ))
        assert summary["exam_status"] == "AUTHORIZED", (
            "only 2 of 6 divisions ever held passes"
        )
        assert summary["certificate_eligible"] is False


class TestRollingClockExpiryBoundary:
    def _setup_single_pass(self, api):
        """PCM passed with sitting 2026-10-01; expires_at 2031-10-01."""
        candidate, divisions = _authorized_candidate(api)
        pass_division(candidate, divisions["PCM"]["id"], "2026-10-01")
        return candidate, divisions

    def test_day_before_expiry_pass_survives(self, api):
        """PRD §3.4: "Each pass remains valid until the current date reaches
        its own `expires_at`, sixty calendar months after that pass's date; on
        the boundary day itself the pass is already expired, because expiry
        triggers when the current date is on or after `expires_at`."

        Design: Difficulty/boundary_precision_check/rolling_clock_expiry_boundary_day
        """
        candidate, _d = self._setup_single_pass(api)
        set_clock("2031-09-30T00:00:00Z")
        sweep = run_expiry_sweep()
        assert sweep["expired_divisions"] == 0, (
            "expires_at - 1 day keeps the pass valid"
        )
        pcm = _division(api, candidate, "PCM")
        assert pcm["status"] == "PASSED"

    def test_boundary_day_pass_expires(self, api):
        """PRD §3.4: "Each pass remains valid until the current date reaches
        its own `expires_at`, sixty calendar months after that pass's date; on
        the boundary day itself the pass is already expired, because expiry
        triggers when the current date is on or after `expires_at`. The expiry
        sweep moves every such `PASSED` row to `EXPIRED`."

        Design: Difficulty/boundary_precision_check/rolling_clock_expiry_boundary_day
        """
        candidate, _d = self._setup_single_pass(api)
        set_clock("2031-09-30T00:00:00Z")
        assert run_expiry_sweep()["expired_divisions"] == 0
        set_clock("2031-10-01T00:00:00Z")
        sweep = run_expiry_sweep()
        assert sweep["expired_divisions"] == 1, (
            "current date == expires_at is inclusive: the pass is expired"
        )
        pcm = _division(api, candidate, "PCM")
        assert pcm["status"] == "EXPIRED"


class TestScoreConfidentiality:
    def test_score_report_confidentiality_shape(self, api):
        """PRD §2.8: "Examination outcomes are exposed only as a `result` of
        `PASS` or `FAIL` plus a `scaled_score` integer between 0 and 100
        inclusive. Item-level examination content — questions, answers,
        subscores, and any finer breakdown — is confidential and is never
        returned by any read endpoint."

        Design: Corner/endpoints/score_report_confidentiality_shape
        """
        candidate, divisions = _authorized_candidate(api)
        schedule_division(candidate, divisions["PCM"]["id"], "2026-10-01")
        set_clock("2026-10-01T00:00:00Z")
        data = validate_success(api.report_exam_score(
            divisions["PCM"]["id"],
            {"result": "PASS", "scaled_score": 75},
            NCARB,
        ))
        assert data["result"] == "PASS"
        assert data["scaled_score"] == 75
        leaked = _FORBIDDEN_CONTENT_KEYS & {k.lower() for k in data.keys()}
        assert not leaked, f"item-level content keys leaked: {leaked}"
        row = _division(api, candidate, "PCM")
        leaked = _FORBIDDEN_CONTENT_KEYS & {k.lower() for k in row.keys()}
        assert not leaked, f"read endpoint leaks item-level keys: {leaked}"


class TestSupplementalExams:
    def test_supplemental_retake_90_day_boundary(self, api):
        """PRD §3.5: "a new registration's `exam_date` must fall at least
        ninety days after the previous `FAILED` sitting, and an earlier date
        is rejected with `ERR_SUPPLEMENTAL_RETAKE_WAIT`."

        Design: Corner/validations/supplemental_retake_90_day_boundary
        """
        create_jurisdiction(code="JX", requires_supplemental_exam=True)
        candidate = create_candidate(home_jurisdiction_code="JX")
        ch = make_candidate_headers(candidate["id"])
        set_clock("2026-09-15T00:00:00Z")
        first = validate_success(api.create_supplemental_exam(
            candidate["id"],
            {"jurisdiction_code": "JX", "exam_date": "2026-10-01"},
            ch,
        ), expected_status=201)
        assert first["status"] == "REGISTERED"
        set_clock("2026-10-01T00:00:00Z")
        failed = validate_success(api.report_supplemental_result(
            first["id"], {"result": "FAIL"},
            TEST_USERS["board_admin_headers"],
        ))
        assert failed["status"] == "FAILED"
        # 2026-10-01 + 89 days == 2026-12-29: too early.
        validate_error(
            api.create_supplemental_exam(
                candidate["id"],
                {"jurisdiction_code": "JX", "exam_date": "2026-12-29"},
                ch,
            ),
            ApiErrorId.ERR_SUPPLEMENTAL_RETAKE_WAIT,
        )
        # 2026-10-01 + 90 days == 2026-12-30: boundary inclusive.
        retake = validate_success(api.create_supplemental_exam(
            candidate["id"],
            {"jurisdiction_code": "JX", "exam_date": "2026-12-30"},
            ch,
        ), expected_status=201)
        assert retake["status"] == "REGISTERED"
        assert retake["exam_date"] == "2026-12-30"

    def test_supplemental_registration_for_non_requiring_jurisdiction_rejected(self, api):
        """PRD §3.5: "A candidate may register for a board's supplemental exam
        only when that jurisdiction's `requires_supplemental_exam` flag is
        true; registering against a board that requires none is rejected with
        `ERR_SUPPLEMENTAL_NOT_REQUIRED`."

        Design: Corner/state_machines/supplemental_registration_for_non_requiring_jurisdiction_rejected
        """
        create_jurisdiction(code=J1)
        candidate = create_candidate(home_jurisdiction_code=J1)
        ch = make_candidate_headers(candidate["id"])
        validate_error(
            api.create_supplemental_exam(
                candidate["id"],
                {"jurisdiction_code": "J1", "exam_date": "2026-10-15"},
                ch,
            ),
            ApiErrorId.ERR_SUPPLEMENTAL_NOT_REQUIRED,
        )
        rows, meta = validate_paginated(
            api.list_supplemental_exams(candidate["id"], ch)
        )
        assert rows == [], "no SupplementalExam row created"
        assert meta["total_count"] == 0
