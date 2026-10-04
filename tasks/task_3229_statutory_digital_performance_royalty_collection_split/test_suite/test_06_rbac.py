"""Role-based access control claims (queue B, rbac section)."""
from test_helpers import (
    ApiErrorId,
    create_active_licensee,
    create_effective_schedule,
    create_pool,
    create_rate_proceeding_payload,
    create_report_with_lines,
    make_admin_headers,
    make_licensee_headers,
    make_matching_agent_headers,
    make_royalty_auditor_headers,
    make_royalty_ops_headers,
    make_statutory_board_headers,
    open_audit_case,
    set_clock,
    setup_standard_paid_scenario,
    validate_error,
    validate_success,
)

ADMIN = make_admin_headers()
OPS = make_royalty_ops_headers()
BOARD = make_statutory_board_headers()
MATCHER = make_matching_agent_headers()


class TestReportReviewRbac:
    def test_licensee_cannot_accept_own_report(self, api):
        """PRD §2.1: "If the named role is not in the endpoint's authorized roles
        list, the request is rejected with `ERR_UNAUTHORIZED` (HTTP 403)."
        PRD §4: "POST /usage-reports/{id}/accept | Accept a submitted report |
        RoyaltyOps"

        Design: Corner/rbac/licensee_cannot_accept_own_report
        """
        create_effective_schedule()
        lic = create_active_licensee(legal_name="RBCo")
        lh = make_licensee_headers(lic["id"])
        report, _ = create_report_with_lines(
            lic["id"],
            [{"isrc": "NM-RB", "track_title": "rb", "artist_name": "rb",
              "performance_count": 10}],
            "2026-01-01T00:00:00Z",
            "2026-01-31T00:00:00Z",
        )
        validate_success(api.submit_usage_report(report["id"], lh))
        err = api.accept_usage_report(report["id"], lh)
        validate_error(err, ApiErrorId.ERR_UNAUTHORIZED.value)
        got = validate_success(api.get_usage_report(report["id"], OPS))
        assert got["report_status"] == "SUBMITTED"

    def test_royaltyops_cannot_run_rate_proceedings(self, api):
        """PRD §2.1: "If the named role is not in the endpoint's authorized roles
        list, the request is rejected with `ERR_UNAUTHORIZED` (HTTP 403)."
        PRD §4: "POST /rate-proceedings | Open a rate proceeding |
        StatutoryBoard"

        Design: Corner/rbac/royaltyops_cannot_run_rate_proceedings
        """
        err = api.create_rate_proceeding(
            create_rate_proceeding_payload(docket_no="DKT-RB"), OPS,
        )
        validate_error(err, ApiErrorId.ERR_UNAUTHORIZED.value)

    def test_admin_cannot_execute_distribution(self, api):
        """PRD §2.1: "If the named role is not in the endpoint's authorized roles
        list, the request is rejected with `ERR_UNAUTHORIZED` (HTTP 403)."
        PRD §4: "POST /distribution-batches/{id}/execute | Execute a planned
        batch (splits, unclaimed accrual, liability settlement) | RoyaltyOps"

        Design: Corner/rbac/admin_cannot_execute_distribution
        """
        scenario = setup_standard_paid_scenario(
            legal_name="ADCo",
            lines=[{"isrc": "NM-AD2", "track_title": "ad2", "artist_name": "ad2",
                    "performance_count": 10}],
        )
        report = scenario["report"]
        create_pool()
        batch = validate_success(
            api.create_distribution_batch(
                report["id"], {"scheduled_for": "2026-10-01T00:00:00Z"}, OPS,
            ),
            expected_status=201,
        )
        # Advance the logical clock to exactly scheduled_for so the batch is due.
        set_clock("2026-10-01T00:00:00Z")
        err = api.execute_distribution_batch(
            batch["id"],
            {"expected_distribution_batch_version": batch["version"]},
            ADMIN,
        )
        validate_error(err, ApiErrorId.ERR_UNAUTHORIZED.value)
        got = validate_success(api.get_distribution_batch(batch["id"], OPS))
        assert got["batch_status"] == "PLANNED"

    def test_matching_agent_cannot_release_pool(self, api):
        """PRD §2.1: "If the named role is not in the endpoint's authorized roles
        list, the request is rejected with `ERR_UNAUTHORIZED` (HTTP 403)."
        PRD §4: "POST /unclaimed-pools/{id}/release | Release an eligible pool
        to verified rights owners pro-rata | RoyaltyOps"

        Design: Corner/rbac/matching_agent_cannot_release_pool
        """
        pool = create_pool()
        err = api.release_pool(pool["id"], MATCHER)
        validate_error(err, ApiErrorId.ERR_UNAUTHORIZED.value)


class TestSegregationOfDuties:
    def test_segregation_of_duties_same_auditor_cannot_issue_findings(self, api):
        """PRD §2.1: "Segregation of duties is enforced on the audit lifecycle:
        the same `X-User-ID` that opened an AuditCase may not issue its
        findings, record a recovery against it, or close it. A violation is
        rejected with `ERR_SEGREGATION_OF_DUTIES` (HTTP 403), and this check
        applies to the issue-findings, record-recovery, and close operations of
        an audit case."
        PRD §3.8: "At least one usage report of the licensee with a period
        overlapping the audit window must be in ACCEPTED or AMENDED status for
        findings to issue."

        Design: Corner/rbac/segregation_of_duties_same_auditor_cannot_issue_findings
        """
        create_effective_schedule()
        lic = create_active_licensee(legal_name="SoDCo")
        report, _ = create_report_with_lines(
            lic["id"],
            [{"isrc": "NM-SD", "track_title": "sd", "artist_name": "sd",
              "performance_count": 10}],
            "2026-03-01T00:00:00Z",
            "2026-03-31T00:00:00Z",
        )
        lh = make_licensee_headers(lic["id"])
        validate_success(api.submit_usage_report(report["id"], lh))
        validate_success(api.accept_usage_report(report["id"], OPS))
        audit = open_audit_case(
            lic["id"], auditor_user_id="auditor-one",
            period_start="2026-03-01T00:00:00Z",
            period_end="2026-03-31T00:00:00Z",
        )
        err = api.issue_audit_findings(
            audit["id"], {"declared_true_performances": 20},
            make_royalty_auditor_headers("auditor-one"),
        )
        validate_error(err, ApiErrorId.ERR_SEGREGATION_OF_DUTIES.value)
        ok = validate_success(
            api.issue_audit_findings(
                audit["id"], {"declared_true_performances": 20},
                make_royalty_auditor_headers("auditor-two"),
            )
        )
        assert ok["audit_status"] == "FINDINGS_ISSUED"
