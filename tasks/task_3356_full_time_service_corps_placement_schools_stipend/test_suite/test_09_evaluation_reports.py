"""Evaluation reporting: the snapshot metrics (eligibility overlap, the
inclusive improvement threshold, the empty-set rule), the submission window,
the data-sharing gate, and the RETURNED -> SUBMITTED revision loop."""

from test_helpers import (
    ApiErrorId,
    factories,
    fixtures,
    get_success_data,
    validate_error,
    validate_paginated,
    validate_success,
)
from test_helpers.test_users import (
    PROGRAM_MANAGER_HEADERS,
    make_school_liaison_headers,
)


def _school_with_report(api, period_start="2026-09-01", period_end="2026-10-31"):
    """Active site, active school with signed data sharing, one DRAFT report."""
    site = fixtures.create_active_site(api)
    school = fixtures.create_active_school(api, site["id"])
    report = fixtures.create_evaluation_report(
        api, school["id"], period_start=period_start, period_end=period_end
    )
    return site, school, report


class TestMetricsSnapshot:
    def test_evaluation_metrics_empty_set_zero_pct(self, api):
        """PRD §3.8: "The headline metric `pct_improved` is one hundred times
        the improved count divided by the eligible count, rounded half up to
        one decimal place — and defined as 0.0 when no students are eligible."

        Design: Corner/calculations/evaluation_metrics_empty_set_zero_pct
        """
        fixtures.set_clock(api)
        _site, _school, report = _school_with_report(api)
        assert report["eligible_student_count"] == 0
        assert report["improved_student_count"] == 0
        assert report["pct_improved"] == 0.0  # the pinned empty-set rule
        assert report["status"] == "DRAFT"

    def test_report_metrics_pct_and_improvement_boundary(self, api):
        """PRD §3.8: "Among the eligible, `improved_student_count` counts
        those with a `current_attendance_pct` on record whose improvement over
        `baseline_attendance_pct` is at least 5.0 percentage points."

        Design: Corner/calculations/report_metrics_pct_and_improvement_boundary
        """
        fixtures.set_clock(api)
        world = fixtures.setup_deployed_world(api)
        member_id = world["member"]["id"]
        school_id = world["school"]["id"]

        # +5.0 points meets the inclusive threshold; +4.9 does not.
        student_a = fixtures.create_student(api, school_id, "SA", baseline_attendance_pct=80.0)
        fixtures.assign_caseload(api, student_a["id"], member_id)
        fixtures.post_metrics(api, student_a["id"], 85.0)
        student_b = fixtures.create_student(api, school_id, "SB", baseline_attendance_pct=80.0)
        fixtures.assign_caseload(api, student_b["id"], member_id)
        fixtures.post_metrics(api, student_b["id"], 84.9)

        report = fixtures.create_evaluation_report(api, school_id)
        assert report["eligible_student_count"] == 2
        assert report["improved_student_count"] == 1
        assert report["pct_improved"] == 50.0  # round_half_up(100 x 1 / 2, 1)

    def test_evaluation_report_metrics_snapshot_at_create(self, api):
        """PRD §3.8: "The report's metrics are snapshotted at creation, while
        the report is still `DRAFT`."

        Design: Corner/endpoints/evaluation_report_metrics_snapshot_at_create
        """
        fixtures.set_clock(api)
        world = fixtures.setup_deployed_world(api)
        school_id = world["school"]["id"]
        student = fixtures.create_student(api, school_id, "SA", baseline_attendance_pct=80.0)
        fixtures.assign_caseload(api, student["id"], world["member"]["id"])
        fixtures.post_metrics(api, student["id"], 85.0)

        report = fixtures.create_evaluation_report(api, school_id)
        assert report["pct_improved"] == 100.0  # 1 eligible, 1 improved

        # A worse attendance figure afterwards does not mutate the snapshot.
        fixtures.post_metrics(api, student["id"], 70.0)
        reports, meta = validate_paginated(
            api.list_school_evaluation_reports(school_id, PROGRAM_MANAGER_HEADERS)
        )
        assert meta["total_count"] == 1
        assert reports[0]["pct_improved"] == 100.0


class TestReportWorkflow:
    def test_report_returned_resubmit_cycle(self, api):
        """PRD §3.8: "Resubmission from `RETURNED` runs the same gates and
        clears the prior `return_reason` to null."
        PRD §3.8: "Review belongs to the district: a `SchoolLiaison` whose
        `X-User-ID` equals the report's school `id` (else
        `ERR_NOT_ENTITY_OWNER`) accepts the report — `SUBMITTED` to
        `ACCEPTED`, which is terminal — or returns it, `SUBMITTED` to
        `RETURNED`, with a `return_reason` required (else
        `ERR_INVALID_REQUEST`) and recorded for the revision loop."

        Design: Corner/state_machines/report_returned_resubmit_cycle"""
        fixtures.set_clock(api)
        _site, school, report = _school_with_report(api)
        # Inside the submission window: period_end + 45 = 2026-12-15.
        fixtures.set_clock(api, "2026-11-15T00:00:00Z")
        get_success_data(
            api.transition_evaluation_report(report["id"], {"to_status": "SUBMITTED"}, PROGRAM_MANAGER_HEADERS)
        )

        returned = validate_success(
            api.transition_evaluation_report(
                report["id"],
                {"to_status": "RETURNED", "return_reason": "missing dosage narrative"},
                make_school_liaison_headers(school["id"]),
            )
        )
        assert returned["status"] == "RETURNED"
        assert returned["return_reason"] == "missing dosage narrative"

        resubmitted = validate_success(
            api.transition_evaluation_report(report["id"], {"to_status": "SUBMITTED"}, PROGRAM_MANAGER_HEADERS)
        )
        assert resubmitted["status"] == "SUBMITTED"
        assert resubmitted["return_reason"] is None

        accepted = validate_success(
            api.transition_evaluation_report(
                report["id"], {"to_status": "ACCEPTED"}, make_school_liaison_headers(school["id"])
            )
        )
        assert accepted["status"] == "ACCEPTED"

    def test_report_returned_requires_reason(self, api):
        """PRD §3.8: "or returns it, `SUBMITTED` to `RETURNED`, with a
        `return_reason` required (else `ERR_INVALID_REQUEST`) and recorded for
        the revision loop."

        Design: Corner/validations/report_returned_requires_reason
        """
        fixtures.set_clock(api)
        _site, school, report = _school_with_report(api)
        fixtures.set_clock(api, "2026-11-15T00:00:00Z")
        get_success_data(
            api.transition_evaluation_report(report["id"], {"to_status": "SUBMITTED"}, PROGRAM_MANAGER_HEADERS)
        )

        blocked = api.transition_evaluation_report(
            report["id"], {"to_status": "RETURNED"}, make_school_liaison_headers(school["id"])
        )
        validate_error(blocked, ApiErrorId.ERR_INVALID_REQUEST.value)

        reports = get_success_data(api.list_school_evaluation_reports(school["id"], PROGRAM_MANAGER_HEADERS))
        assert reports[0]["status"] == "SUBMITTED"

    def test_report_window_45_ok_46_closed(self, api):
        """PRD §3.8: "Submission — `DRAFT` or `RETURNED` to `SUBMITTED`, by a
        `ProgramManager` — is gated twice: the school's `data_sharing_status`
        must be `SIGNED` (else `ERR_DATA_SHARING_NOT_SIGNED`), and the clock
        date must be no more than 45 days past `period_end` (else
        `ERR_REPORT_WINDOW_CLOSED`)."

        Design: Corner/validations/report_window_45_ok_46_closed
        """
        fixtures.set_clock(api)
        _site, _school, report1 = _school_with_report(api)
        report2 = fixtures.create_evaluation_report(api, _school["id"])

        # 2026-12-15 is exactly period_end + 45 days: the boundary is inclusive.
        fixtures.set_clock(api, "2026-12-15T00:00:00Z")
        submitted = validate_success(
            api.transition_evaluation_report(report1["id"], {"to_status": "SUBMITTED"}, PROGRAM_MANAGER_HEADERS)
        )
        assert submitted["status"] == "SUBMITTED"

        fixtures.set_clock(api, "2026-12-16T00:00:00Z")
        blocked = api.transition_evaluation_report(
            report2["id"], {"to_status": "SUBMITTED"}, PROGRAM_MANAGER_HEADERS
        )
        validate_error(blocked, ApiErrorId.ERR_REPORT_WINDOW_CLOSED.value)

    def test_report_submit_blocked_after_data_sharing_expiry(self, api):
        """PRD §3.8: "the school's `data_sharing_status` must be `SIGNED`
        (else `ERR_DATA_SHARING_NOT_SIGNED`)".
        PRD §3.2: "the same transition happens automatically whenever the
        school's data sharing lapses to `EXPIRED` — including from
        `AMENDMENT_REVIEW`, which likewise falls to `SUSPENDED` on expiry."

        Design: Corner/validations/report_submit_blocked_after_data_sharing_expiry
        """
        fixtures.set_clock(api)
        _site, school, report = _school_with_report(api)

        expired = validate_success(
            api.transition_school(
                school["id"], {"to_status": "EXPIRED", "dimension": "DATA_SHARING"},
                make_school_liaison_headers(school["id"]),
            )
        )
        # The expiry force-suspends the ACTIVE agreement.
        assert expired["agreement_status"] == "SUSPENDED"

        # The report was drafted while sharing was signed; the submission gate
        # reads the school's dimension at submission time.
        blocked = api.transition_evaluation_report(
            report["id"], {"to_status": "SUBMITTED"}, PROGRAM_MANAGER_HEADERS
        )
        validate_error(blocked, ApiErrorId.ERR_DATA_SHARING_NOT_SIGNED.value)
