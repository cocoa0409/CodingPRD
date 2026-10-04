"""Experience submission rules: half-open overlap, validation precedence,
supervisor liveness, reassignment window, return/resubmit conservation
(PRD §2.6, §2.7, §3.1, §3.3)."""
from test_helpers import (
    ApiErrorId, FULL_CREDIT_PCT, TEST_USERS, create_active_supervisor,
    create_candidate, create_draft_report, create_jurisdiction,
    create_submitted_report, create_verified_report,
    make_candidate_headers, make_supervisor_headers, set_clock,
    submit_report, validate_error, validate_success, verify_report,
)

J1 = "J1"
NCARB = TEST_USERS["ncarb_admin_headers"]


def _registry(api):
    create_jurisdiction(code=J1)
    candidate = create_candidate(home_jurisdiction_code=J1)
    supervisor = create_active_supervisor(jurisdiction_code=J1)
    return candidate, supervisor


def _ncarb(api):
    return NCARB


class TestWorkPeriodHalfOpenOverlap:
    def test_adjacent_periods_do_not_overlap(self, api):
        """PRD §3.3: "it requires the half-open work period to avoid
        overlapping any `SUBMITTED` or `VERIFIED` report of the same candidate
        — mere adjacency, where one period's end equals another's start, is
        allowed — with overlaps rejected as `ERR_WORK_PERIOD_OVERLAP`".
        PRD §2.7: "Calendar periods are half-open intervals: a work period
        covers the span from `work_period_start` up to but not including
        `work_period_end`".

        Design: Difficulty/resource_temporal_overlap/work_period_half_open_adjacency
        """
        candidate, supervisor = _registry(api)
        create_submitted_report(
            candidate, supervisor, "PROJECT_PLANNING_DESIGN", 40,
            "2026-01-05", "2026-03-02",
        )
        adjacent = create_draft_report(
            candidate, supervisor, "PROJECT_PLANNING_DESIGN", 40,
            "2026-03-02", "2026-05-01",
        )
        data = submit_report(candidate, adjacent["id"])
        assert data["status"] == "SUBMITTED", (
            "[2026-01-05, 2026-03-02) and [2026-03-02, 2026-05-01) only touch"
        )

    def test_overlapping_period_rejected(self, api):
        """PRD §3.3: "it requires the half-open work period to avoid
        overlapping any `SUBMITTED` or `VERIFIED` report of the same candidate
        — mere adjacency, where one period's end equals another's start, is
        allowed — with overlaps rejected as `ERR_WORK_PERIOD_OVERLAP`".

        Design: Difficulty/resource_temporal_overlap/work_period_half_open_adjacency
        """
        candidate, supervisor = _registry(api)
        ch = make_candidate_headers(candidate["id"])
        create_submitted_report(
            candidate, supervisor, "PROJECT_PLANNING_DESIGN", 40,
            "2026-01-05", "2026-03-02",
        )
        create_submitted_report(
            candidate, supervisor, "PROJECT_PLANNING_DESIGN", 40,
            "2026-03-02", "2026-05-01",
        )
        intruder = create_draft_report(
            candidate, supervisor, "PROJECT_PLANNING_DESIGN", 40,
            "2026-04-15", "2026-06-01",
        )
        validate_error(
            api.submit_experience_report(intruder["id"], ch),
            ApiErrorId.ERR_WORK_PERIOD_OVERLAP,
        )
        after = validate_success(api.get_experience_report(intruder["id"], ch))
        assert after["status"] == "DRAFT", "rejection leaves the report DRAFT"


class TestSubmitValidationPrecedence:
    def test_supervisor_not_active_beats_overlap(self, api):
        """PRD §2.6: "When several checks could reject the same request, the
        first failure in a fixed evaluation order wins, and only that
        failure's error is returned."
        PRD §2.6 tier 6: "**Business referential integrity.** Assignment-level
        checks: `ERR_SUPERVISOR_NOT_ACTIVE` (HTTP 422),
        `ERR_SUPERVISOR_MISMATCH` (HTTP 403), and
        `ERR_SUPPLEMENTAL_NOT_REQUIRED` (HTTP 422)."
        PRD §2.6 tier 8: "**Request shape and business constraints.** Required
        fields, enum membership, numeric ranges, and conditional-field
        presence are swept last as `ERR_INVALID_REQUEST` (HTTP 400), alongside
        the dedicated constraint codes `ERR_WORK_PERIOD_INVALID` (HTTP 422),
        `ERR_HOURS_OUT_OF_RANGE` (HTTP 422), `ERR_WORK_PERIOD_OVERLAP` (HTTP
        409), `ERR_EXAM_DAY_CONFLICT` (HTTP 409), `ERR_JURISDICTION_CODE_EXISTS`
        (HTTP 409), `ERR_TRANSMITTAL_DUPLICATE` (HTTP 409), and
        `ERR_CE_HOURS_INSUFFICIENT` (HTTP 422)."

        Design: Difficulty/priority_pair_validation_conflict/submit_conflict_referential_beats_constraint
        """
        candidate, supervisor = _registry(api)
        ncarb = _ncarb(api)
        create_submitted_report(
            candidate, supervisor, "PROJECT_MANAGEMENT", 40,
            "2026-01-05", "2026-02-02",
        )
        updated = validate_success(api.update_supervisor(
            supervisor["id"],
            {"expected_supervisor_version": supervisor["version"],
             "license_status": "INACTIVE"},
            ncarb,
        ))
        assert updated["license_status"] == "INACTIVE"
        overlapping = create_draft_report(
            candidate, supervisor, "PROJECT_MANAGEMENT", 40,
            "2026-01-20", "2026-02-20",
        )
        # Both the tier-6 referential rule (supervisor INACTIVE) and the
        # tier-8 constraint (overlap with the SUBMITTED report) fail; the
        # referential error must win.
        validate_error(
            api.submit_experience_report(
                overlapping["id"], make_candidate_headers(candidate["id"]),
            ),
            ApiErrorId.ERR_SUPERVISOR_NOT_ACTIVE,
        )
        after = validate_success(api.get_experience_report(
            overlapping["id"], make_candidate_headers(candidate["id"]),
        ))
        assert after["status"] == "DRAFT"

    def test_overlap_error_fires_in_isolation(self, api):
        """PRD §3.3: "it requires the half-open work period to avoid
        overlapping any `SUBMITTED` or `VERIFIED` report of the same candidate
        — mere adjacency, where one period's end equals another's start, is
        allowed — with overlaps rejected as `ERR_WORK_PERIOD_OVERLAP`".

        Design: Difficulty/priority_pair_validation_conflict/submit_conflict_referential_beats_constraint
        """
        candidate, supervisor = _registry(api)
        create_submitted_report(
            candidate, supervisor, "PROJECT_MANAGEMENT", 40,
            "2026-01-05", "2026-02-02",
        )
        overlapping = create_draft_report(
            candidate, supervisor, "PROJECT_MANAGEMENT", 40,
            "2026-01-20", "2026-02-20",
        )
        # Supervisor ACTIVE, so only the overlap constraint can fail.
        validate_error(
            api.submit_experience_report(
                overlapping["id"], make_candidate_headers(candidate["id"]),
            ),
            ApiErrorId.ERR_WORK_PERIOD_OVERLAP,
        )


class TestVerifyRequiresSupervisorActive:
    def _submitted_with_inactive_supervisor(self, api):
        candidate, supervisor = _registry(api)
        ncarb = _ncarb(api)
        report = create_submitted_report(
            candidate, supervisor, "PROJECT_MANAGEMENT", 40,
            "2026-01-05", "2026-02-02",
        )
        updated = validate_success(api.update_supervisor(
            supervisor["id"],
            {"expected_supervisor_version": supervisor["version"],
             "license_status": "INACTIVE"},
            ncarb,
        ))
        return candidate, supervisor, report, updated, ncarb

    def test_verify_blocked_while_supervisor_inactive(self, api):
        """PRD §3.1: "A supervisor's `license_status` starts at `ACTIVE` and
        may be flipped to `INACTIVE` (and back) by council staff through the
        concurrency-guarded supervisor update; only `ACTIVE` supervisors can
        participate in submission or verification, as §3.3 details."
        PRD §3.3: "the supervisor must still hold `license_status` `ACTIVE` at
        verify time, failing which the rejection is
        `ERR_SUPERVISOR_NOT_ACTIVE`".

        Design: Difficulty/cross_entity_state_dependency/verify_requires_supervisor_active
        """
        candidate, supervisor, report, _u, _n = (
            self._submitted_with_inactive_supervisor(api)
        )
        validate_error(
            api.verify_experience_report(
                report["id"], make_supervisor_headers(supervisor["id"]),
            ),
            ApiErrorId.ERR_SUPERVISOR_NOT_ACTIVE,
        )
        after = validate_success(api.get_experience_report(
            report["id"], make_supervisor_headers(supervisor["id"]),
        ))
        assert after["status"] == "SUBMITTED", "blocked verify changes nothing"

    def test_verify_unblocked_after_supervisor_reactivated(self, api):
        """PRD §3.1: "A supervisor's `license_status` starts at `ACTIVE` and
        may be flipped to `INACTIVE` (and back) by council staff through the
        concurrency-guarded supervisor update; only `ACTIVE` supervisors can
        participate in submission or verification, as §3.3 details."
        PRD §3.3: "A successful verification moves the report to its terminal
        `VERIFIED` state and stamps `credited_hours`".

        Design: Difficulty/cross_entity_state_dependency/verify_requires_supervisor_active
        """
        candidate, supervisor, report, updated, ncarb = (
            self._submitted_with_inactive_supervisor(api)
        )
        validate_error(
            api.verify_experience_report(
                report["id"], make_supervisor_headers(supervisor["id"]),
            ),
            ApiErrorId.ERR_SUPERVISOR_NOT_ACTIVE,
        )
        reactivated = validate_success(api.update_supervisor(
            supervisor["id"],
            {"expected_supervisor_version": updated["version"],
             "license_status": "ACTIVE"},
            ncarb,
        ))
        assert reactivated["license_status"] == "ACTIVE"
        data = verify_report(supervisor, report["id"])
        assert data["status"] == "VERIFIED"
        assert data["credited_hours"] == 40


class TestReturnResubmitConservation:
    def _setup_verified_plus_submitted(self, api):
        candidate, supervisor = _registry(api)
        verified = create_verified_report(
            candidate, supervisor, "PROJECT_PLANNING_DESIGN", 40,
            "2026-01-05", "2026-02-02",
        )
        submitted = create_submitted_report(
            candidate, supervisor, "PROJECT_MANAGEMENT", 40,
            "2026-02-02", "2026-03-02",
        )
        return candidate, supervisor, verified, submitted

    def _total(self, api, candidate):
        summary = validate_success(api.get_candidate_summary(
            candidate["id"], make_candidate_headers(candidate["id"]),
        ))
        return summary["total_credited_hours"]

    def test_return_leaves_verified_total_unchanged(self, api):
        """PRD §3.3: "A supervisor may instead return a `SUBMITTED` report
        with a `return_reason`; the report moves to `RETURNED`, the reason is
        recorded, and candidate totals are unaffected because `SUBMITTED`
        reports contribute nothing."
        PRD §3.3: "Only `VERIFIED` reports contribute; `DRAFT`, `SUBMITTED`,
        and `RETURNED` reports each contribute exactly zero."

        Design: Difficulty/compensating_invariant/report_return_resubmit_credit_conservation
        """
        candidate, supervisor, _v, submitted = (
            self._setup_verified_plus_submitted(api)
        )
        assert self._total(api, candidate) == 40
        returned = validate_success(api.return_experience_report(
            submitted["id"], {"return_reason": "fix dates"},
            make_supervisor_headers(supervisor["id"]),
        ))
        assert returned["status"] == "RETURNED"
        assert returned["return_reason"] == "fix dates"
        assert self._total(api, candidate) == 40, (
            "RETURN changed nothing countable"
        )

    def test_resubmit_after_return_preserves_total_and_restamps(self, api):
        """PRD §3.3: "Resubmitting a `RETURNED` report re-applies every
        submission check, restamps `submitted_at` to the current instant,
        re-locks `credit_pct` against the new submission date, and clears
        `return_reason`."
        PRD §3.3: "Only `VERIFIED` reports contribute; `DRAFT`, `SUBMITTED`,
        and `RETURNED` reports each contribute exactly zero."

        Design: Difficulty/compensating_invariant/report_return_resubmit_credit_conservation
        """
        candidate, supervisor, _v, submitted = (
            self._setup_verified_plus_submitted(api)
        )
        validate_success(api.return_experience_report(
            submitted["id"], {"return_reason": "fix dates"},
            make_supervisor_headers(supervisor["id"]),
        ))
        resubmitted = submit_report(candidate, submitted["id"])
        assert resubmitted["status"] == "SUBMITTED"
        assert resubmitted["credit_pct"] == FULL_CREDIT_PCT, (
            "restamped at the same clock, inside the 8-month window"
        )
        assert resubmitted["return_reason"] is None
        assert self._total(api, candidate) == 40, (
            "total still sums VERIFIED reports only"
        )


class TestReassignWindow:
    def test_reassign_window_45_day_boundary(self, api):
        """PRD §3.3: "the candidate may reassign an unanswered `SUBMITTED`
        report to a new supervisor, but only after a waiting period: the
        current date must be on or after the day forty-five days after the
        report's submitted date."
        PRD §3.3: "attempting the reassignment before the forty-five-day
        window has opened, or naming the same or an inactive supervisor, is
        rejected with `ERR_REASSIGN_WINDOW_NOT_OPEN`. Reassignment replaces
        `supervisor_id` but preserves both `submitted_at` and the locked
        `credit_pct` — the credit tier survives the handoff untouched."

        Design: Corner/validations/reassign_window_45_day_boundary
        """
        candidate, supervisor = _registry(api)
        second = create_active_supervisor(jurisdiction_code=J1)
        ch = make_candidate_headers(candidate["id"])
        # Submitted at the default clock date 2026-09-01, locking 100%.
        report = create_submitted_report(
            candidate, supervisor, "PRACTICE_MANAGEMENT", 40,
            "2026-01-05", "2026-02-02",
        )
        assert report["credit_pct"] == FULL_CREDIT_PCT
        # 2026-09-01 + 44 days == 2026-10-15: window not yet open.
        set_clock("2026-10-15T00:00:00Z")
        validate_error(
            api.reassign_experience_report(
                report["id"], {"new_supervisor_id": second["id"]}, ch,
            ),
            ApiErrorId.ERR_REASSIGN_WINDOW_NOT_OPEN,
        )
        # 2026-09-01 + 45 days == 2026-10-16: boundary inclusive, opens.
        set_clock("2026-10-16T00:00:00Z")
        data = validate_success(api.reassign_experience_report(
            report["id"], {"new_supervisor_id": second["id"]}, ch,
        ))
        assert data["supervisor_id"] == second["id"]
        assert data["status"] == "SUBMITTED", "self-loop transition"
        assert data["submitted_at"] == report["submitted_at"], (
            "submitted_at preserved"
        )
        assert data["credit_pct"] == FULL_CREDIT_PCT, (
            "locked tier survives reassignment"
        )
