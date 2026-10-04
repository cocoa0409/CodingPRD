"""Domain-rule validation error claims (queue B, validations section)."""
from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    create_active_licensee,
    create_effective_schedule,
    create_licensee,
    create_ownership_claim_payload,
    create_pool,
    create_report_with_lines,
    create_rate_schedule_payload,
    make_admin_headers,
    make_licensee_headers,
    make_royalty_auditor_headers,
    make_royalty_ops_headers,
    make_statutory_board_headers,
    open_audit_case,
    setup_march_audit_scenario,
    setup_recording_with_claimants,
    setup_standard_paid_scenario,
    submit_and_accept_report,
    validate_error,
    validate_success,
)

ADMIN = make_admin_headers()
OPS = make_royalty_ops_headers()
BOARD = make_statutory_board_headers()


class TestContextHeaders:
    def test_missing_context_headers_rejected(self, api):
        """PRD §2.1: "A request in which either header is missing or empty is
        rejected with `ERR_MISSING_OR_INVALID_CONTEXT_HEADER` (HTTP 400)."

        Design: Corner/validations/missing_context_headers_rejected
        """
        resp = api.list_licensees({})
        validate_error(resp, ApiErrorId.ERR_MISSING_OR_INVALID_CONTEXT_HEADER.value)


class TestSubmitPreconditions:
    def test_submit_without_effective_schedule_rejected(self, api):
        """PRD §2.6: "If no such schedule exists, the submission fails with
        `ERR_NO_EFFECTIVE_RATE_SCHEDULE` (HTTP 409)."

        Design: Corner/validations/submit_without_effective_schedule_rejected
        """
        lic = create_active_licensee(legal_name="NoRate")
        lh = make_licensee_headers(lic["id"])
        report, _ = create_report_with_lines(
            lic["id"],
            [{"isrc": "NM-NR", "track_title": "nr", "artist_name": "nr",
              "performance_count": 10}],
            "2026-01-01T00:00:00Z",
            "2026-01-31T00:00:00Z",
        )
        err = api.submit_usage_report(report["id"], lh)
        validate_error(err, ApiErrorId.ERR_NO_EFFECTIVE_RATE_SCHEDULE.value)

    def test_submit_empty_report_rejected(self, api):
        """PRD §3.4: "Four preconditions are evaluated in order: the report must
        contain at least one play line (otherwise `ERR_REPORT_NO_PLAY_LINES`,
        HTTP 409)"

        Design: Corner/validations/submit_empty_report_rejected
        """
        create_effective_schedule()
        lic = create_active_licensee(legal_name="EmptyCo")
        lh = make_licensee_headers(lic["id"])
        report, _ = create_report_with_lines(
            lic["id"], [], "2026-01-01T00:00:00Z", "2026-01-31T00:00:00Z",
        )
        err = api.submit_usage_report(report["id"], lh)
        validate_error(err, ApiErrorId.ERR_REPORT_NO_PLAY_LINES.value)


class TestTerminationGuards:
    def test_terminate_blocked_by_open_audit(self, api):
        """PRD §3.1: "An `Admin` may terminate a licensee from any of `DRAFT`,
        `ACTIVE`, or `SUSPENDED`, but only when three preconditions all hold: no
        usage report of the licensee is in SUBMITTED status, no distribution
        batch on any report of the licensee is in PLANNED status, and no audit
        case for the licensee is in OPENED or FINDINGS_ISSUED status. If any
        precondition fails, the termination is rejected with
        `ERR_TERMINATION_BLOCKED` (HTTP 409)."

        Design: Corner/validations/terminate_blocked_by_open_audit
        """
        lic = create_active_licensee(legal_name="TBCo")
        open_audit_case(
            lic["id"], auditor_user_id="aud-tb",
            period_start="2026-01-01T00:00:00Z",
            period_end="2026-12-31T00:00:00Z",
        )
        err = api.terminate_licensee(lic["id"], ADMIN)
        validate_error(err, ApiErrorId.ERR_TERMINATION_BLOCKED.value)
        got = validate_success(api.get_licensee(lic["id"], ADMIN))
        assert got["license_status"] == "ACTIVE"


class TestUniquenessGuards:
    def test_duplicate_liability_and_batch_rejected(self, api):
        """PRD §3.5: "Exactly one RoyaltyLiability exists per usage report;
        attempting to compute a second liability for a report that already has
        one is rejected with `ERR_ALREADY_EXISTS` (HTTP 409)."
        PRD §3.6: "exactly one batch exists per report: planning a second batch
        for a report that already has one is rejected with `ERR_ALREADY_EXISTS`."

        Design: Corner/validations/duplicate_liability_and_batch_rejected
        """
        create_effective_schedule()
        lic = create_active_licensee(legal_name="DupCo")
        report, _ = create_report_with_lines(
            lic["id"],
            [{"isrc": "NM-DP", "track_title": "dp", "artist_name": "dp",
              "performance_count": 10000}],
            "2026-01-01T00:00:00Z",
            "2026-01-31T00:00:00Z",
        )
        accepted = submit_and_accept_report(report["id"], lic["id"])
        liability = validate_success(
            api.compute_liability(
                report["id"],
                {"expected_usage_report_version": accepted["version"]},
                OPS,
            ),
            expected_status=201,
        )
        # Future relative to the startup clock default 2026-09-01T00:00:00Z.
        batch = validate_success(
            api.create_distribution_batch(
                report["id"], {"scheduled_for": "2026-10-01T00:00:00Z"}, OPS,
            ),
            expected_status=201,
        )
        report_now = validate_success(api.get_usage_report(report["id"], OPS))
        err1 = api.compute_liability(
            report["id"],
            {"expected_usage_report_version": report_now["version"]},
            OPS,
        )
        validate_error(err1, ApiErrorId.ERR_ALREADY_EXISTS.value)
        err2 = api.create_distribution_batch(
            report["id"], {"scheduled_for": "2026-10-02T00:00:00Z"}, OPS,
        )
        validate_error(err2, ApiErrorId.ERR_ALREADY_EXISTS.value)


class TestAuditGuards:
    def test_audit_close_blocked_until_fully_recovered(self, api):
        """PRD §3.8: "An auditor closes a FINDINGS_ISSUED case only when
        `assessed_underpayment_cents` is zero or has been fully recovered;
        otherwise the close is rejected with `ERR_AUDIT_NOT_SETTLABLE`
        (HTTP 409)."

        Design: Corner/validations/audit_close_blocked_until_fully_recovered
        """
        scenario = setup_march_audit_scenario(legal_name="ClCo")
        audit = scenario["audit"]
        err = api.close_audit_case(audit["id"], make_royalty_auditor_headers(
            "auditor-two"))
        validate_error(err, ApiErrorId.ERR_AUDIT_NOT_SETTLABLE.value)
        got = validate_success(api.get_audit_case(audit["id"],
                                                  make_royalty_auditor_headers(
                                                      "auditor-two")))
        assert got["audit_status"] == "FINDINGS_ISSUED"


class TestCatalogGuards:
    def test_withdraw_recording_blocked_during_open_claim(self, api):
        """PRD §3.7: "Withdrawal moves it `ACTIVE` → `WITHDRAWN`, but a recording
        may not be withdrawn while any ownership claim on it is OPEN or
        UNDER_REVIEW — such a withdrawal is rejected with
        `ERR_RECORDING_IN_DISPUTE` (HTTP 409)."

        Design: Corner/validations/withdraw_recording_blocked_during_open_claim
        """
        env = setup_recording_with_claimants(isrc="ISRC-WD")
        rec = env["recording"]
        validate_success(
            api.create_ownership_claim(
                rec["id"],
                create_ownership_claim_payload(env["ro2"]["id"]),
                TEST_USERS["payee_admin_headers"],
            ),
            expected_status=201,
        )
        err = api.withdraw_recording(rec["id"], ADMIN)
        validate_error(err, ApiErrorId.ERR_RECORDING_IN_DISPUTE.value)
        got = validate_success(api.get_recording(rec["id"], ADMIN))
        assert got["catalog_status"] == "ACTIVE"
