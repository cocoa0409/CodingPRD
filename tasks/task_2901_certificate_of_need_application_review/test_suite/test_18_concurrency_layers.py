"""Optimistic concurrency on the three versioned writes, and the fiscal boundary walk."""

from test_helpers import (
    api_client,
    get_success_data,
    validate_error,
    validate_paginated,
)
from test_helpers.api_errors import ApiErrorId
from test_helpers.constants import (
    EXPECTED_CEILING_CENTS,
    SCORE_ONE_SHEET,
    SHEET_REV_1,
    SHEET_REV_2,
)
from test_helpers.factories import progress_report_payload, score_sheet_payload
from test_helpers.fixtures import (
    ADMIN,
    OFFICER,
    file_progress_report,
    file_score_sheet,
    refresh_applicant,
    refresh_application,
    refresh_certificate,
    refresh_health_service_area,
    seed_comparative_review,
    seed_issued_certificate,
)
from test_helpers.test_users import (
    REVIEWER_USER_ID_1,
    make_applicant_headers,
    make_review_analyst_headers,
)

SCORE_AFTER_REVISION = 79.25
FIRST_PERIOD = "2026-12-31"
SECOND_PERIOD = "2027-03-31"
THIRD_PERIOD = "2027-06-30"
NEW_LIMIT_CENTS = 1200000000
NEW_MILESTONE_DATE = "2027-12-31"


class TestScoreSheetVersionGuard:
    def test_a_revision_replayed_against_the_pre_first_sheet_version_is_refused(self):
        """No state precondition blocks the revision, so only the version guard can.

        PRD §2.7: "In each case the client must send back the `version` it last
        observed on the **parent** record; if the parent's current `version` differs,
        the write is refused rather than applied on top of a view the client never
        saw."
        PRD §2.7: "A score-sheet submission must carry
        `expected_application_version` matching the target application's current
        `version`."
        PRD §2.7: "A reviewer may legitimately file a revised sheet that supersedes
        their own previous `ACTIVE` sheet, so a second sequential submission is not
        blocked by any state precondition; the stale-version check is what stops a
        revision computed against an outdated `comparative_score` or
        `score_sheet_count` from landing."
        PRD §2.7: "A mismatch is rejected with `ERR_STALE_APPLICATION_VERSION` (HTTP
        412)."
        PRD §3.7: "Every submission — first or revised — recomputes the parent
        application's `comparative_score` and `score_sheet_count` and increases the
        application's `version` by 1."

        Design: Corner/cross_cutting_complexity_layers/occ_score_sheet_revision_against_a_stale_application_version_returns_412
        """
        world = seed_comparative_review()
        stale_version = world["application"]["version"]
        first_sheet = file_score_sheet(
            world["application"],
            SHEET_REV_1,
            REVIEWER_USER_ID_1,
            expected_version=stale_version,
        )
        after_first = refresh_application(world["application"]["id"])
        fresh_version = after_first["version"]
        assert fresh_version == stale_version + 1
        assert after_first["comparative_score"] == SCORE_ONE_SHEET
        assert after_first["score_sheet_count"] == 1

        revision = score_sheet_payload(
            after_first["id"], stale_version, SHEET_REV_2
        )
        response = api_client.create_score_sheet(
            revision, make_review_analyst_headers(REVIEWER_USER_ID_1)
        )

        validate_error(response, ApiErrorId.ERR_STALE_APPLICATION_VERSION, 412)
        unchanged = refresh_application(after_first["id"])
        assert unchanged["version"] == fresh_version
        assert unchanged["comparative_score"] == SCORE_ONE_SHEET
        assert unchanged["score_sheet_count"] == 1
        sheets, meta = validate_paginated(
            api_client.list_score_sheets(after_first["id"], ADMIN)
        )
        assert meta["total_count"] == 1
        assert sheets[0]["id"] == first_sheet["id"]
        assert sheets[0]["status"] == "ACTIVE"

        revision["expected_application_version"] = fresh_version
        accepted = get_success_data(
            api_client.create_score_sheet(
                revision, make_review_analyst_headers(REVIEWER_USER_ID_1)
            ),
            201,
        )

        assert accepted["status"] == "ACTIVE"
        rescored = refresh_application(after_first["id"])
        assert rescored["comparative_score"] == SCORE_AFTER_REVISION
        assert rescored["score_sheet_count"] == 1
        assert rescored["version"] == fresh_version + 1
        surviving, meta = validate_paginated(
            api_client.list_score_sheets(after_first["id"], ADMIN)
        )
        assert meta["total_count"] == 2
        by_id = {sheet["id"]: sheet["status"] for sheet in surviving}
        assert by_id[first_sheet["id"]] == "SUPERSEDED"
        assert by_id[accepted["id"]] == "ACTIVE"


class TestProgressReportVersionGuard:
    def test_a_period_correction_replayed_against_the_pre_report_version_is_refused(self):
        """The supersession is legitimate, so the stale view is the only defect.

        PRD §2.7: "A progress-report filing must carry
        `expected_certificate_version` matching the target certificate's current
        `version`."
        PRD §2.7: "Because a corrected report for an already-reported
        `period_end_date` legitimately supersedes the earlier report, no state
        precondition can exclude the write; the stale-version check is what stops a
        filer from superseding a report while holding an outdated view of the
        certificate's expenditure posture."
        PRD §2.7: "A mismatch is rejected with `ERR_STALE_CERTIFICATE_VERSION` (HTTP
        412)."
        PRD §3.8: "When an accepted report already exists for the same
        `certificate_id` and the same `period_end_date`, that earlier report's
        `status` is set to `SUPERSEDED`, so exactly one `ACCEPTED` report per period
        survives; `ACCEPTED` and `SUPERSEDED` are the only two values the field
        takes."
        PRD §3.8: "From that set, `cumulative_expenditure_cash_cents` is the sum of
        `disbursed_cents` across the contributing reports, and
        `cumulative_expenditure_accrual_cents` is the sum of `disbursed_cents` plus
        `obligated_cents` across the same reports."

        Design: Corner/cross_cutting_complexity_layers/occ_progress_report_supersession_against_a_stale_certificate_version_returns_412
        """
        world = seed_issued_certificate()
        certificate = world["certificate"]
        stale_version = certificate["version"]
        first_report = file_progress_report(
            certificate,
            world["applicant"],
            expected_version=stale_version,
            period_end_date=FIRST_PERIOD,
            disbursed_cents=200000000,
            obligated_cents=50000000,
            physical_completion_pct=12.00,
        )
        after_first = refresh_certificate(certificate["id"])
        fresh_version = after_first["version"]
        assert fresh_version == stale_version + 1
        assert after_first["cumulative_expenditure_cash_cents"] == 200000000
        assert after_first["latest_completion_pct"] == 12.00

        correction = progress_report_payload(
            certificate["id"],
            stale_version,
            period_end_date=FIRST_PERIOD,
            disbursed_cents=260000000,
            obligated_cents=40000000,
            physical_completion_pct=15.00,
        )
        response = api_client.create_progress_report(
            correction, make_applicant_headers(world["applicant"]["id"])
        )

        validate_error(response, ApiErrorId.ERR_STALE_CERTIFICATE_VERSION, 412)
        reports, meta = validate_paginated(
            api_client.list_progress_reports(certificate["id"], OFFICER)
        )
        assert meta["total_count"] == 1
        assert reports[0]["id"] == first_report["id"]
        assert reports[0]["status"] == "ACCEPTED"
        unchanged = refresh_certificate(certificate["id"])
        assert unchanged["version"] == fresh_version
        assert unchanged["cumulative_expenditure_cash_cents"] == 200000000
        assert unchanged["latest_completion_pct"] == 12.00

        correction["expected_certificate_version"] = fresh_version
        accepted = get_success_data(
            api_client.create_progress_report(
                correction, make_applicant_headers(world["applicant"]["id"])
            ),
            201,
        )

        assert accepted["status"] == "ACCEPTED"
        superseding, meta = validate_paginated(
            api_client.list_progress_reports(certificate["id"], OFFICER)
        )
        assert meta["total_count"] == 2
        by_id = {report["id"]: report["status"] for report in superseding}
        assert by_id[first_report["id"]] == "SUPERSEDED"
        assert by_id[accepted["id"]] == "ACCEPTED"
        recomputed = refresh_certificate(certificate["id"])
        assert recomputed["cumulative_expenditure_cash_cents"] == 260000000
        assert recomputed["cumulative_expenditure_accrual_cents"] == 300000000
        assert recomputed["latest_completion_pct"] == 15.00


class TestCertificateModificationVersionGuard:
    def test_a_reissue_computed_before_the_report_landed_is_refused(self):
        """The applicant's report moved the certificate under the officer's feet.

        PRD §2.7: "A certificate modification must carry
        `expected_certificate_version` matching the addressed certificate's current
        `version`."
        PRD §2.7: "The reissue legitimately supersedes the prior certificate row, so
        nothing in the state machine excludes a second reissue; the stale-version
        check is what stops a modification whose limit or bed delta was computed
        against an outdated cumulative expenditure or `authorized_bed_count`."
        PRD §3.8: "A successor certificate row is then created with
        `superseded_certificate_id` pointing at the addressed row,
        `extension_days_granted_total` carried forward unchanged, and its
        `lifecycle_status` taken from the addressed row's
        `lifecycle_status_before_suspension` when that row was `SUSPENDED` — so a
        suspension cured by a limit amendment reappears as `ISSUED` or `IMPLEMENTED`
        exactly as it stood before the breach, with the successor's own
        `lifecycle_status_before_suspension` reset to null — and otherwise taken from
        the addressed row's own `lifecycle_status`."
        PRD §3.8: "On the planning area, `capital_authorization_committed_cents` is
        debited by the old `approved_expenditure_limit_cents` and then credited with
        the new one."
        PRD §2.3: "Certificates may be filtered by `application_id`,
        `superseded_certificate_id` and `lifecycle_status`."

        Design: Corner/cross_cutting_complexity_layers/occ_certificate_reissue_against_a_stale_certificate_version_returns_412
        """
        world = seed_issued_certificate()
        certificate = world["certificate"]
        stale_version = certificate["version"]
        file_progress_report(
            certificate,
            world["applicant"],
            expected_version=stale_version,
            period_end_date=FIRST_PERIOD,
            disbursed_cents=200000000,
            obligated_cents=0,
            physical_completion_pct=10.00,
        )
        after_report = refresh_certificate(certificate["id"])
        fresh_version = after_report["version"]
        assert fresh_version == stale_version + 1

        modification = {
            "expected_certificate_version": stale_version,
            "new_approved_expenditure_limit_cents": NEW_LIMIT_CENTS,
            "new_implementation_milestone_date": NEW_MILESTONE_DATE,
        }
        response = api_client.modify_certificate(
            certificate["id"], modification, OFFICER
        )

        validate_error(response, ApiErrorId.ERR_STALE_CERTIFICATE_VERSION, 412)
        unchanged = refresh_certificate(certificate["id"])
        assert unchanged["lifecycle_status"] == "ISSUED"
        assert unchanged["expenditure_status"] == "WITHIN_LIMIT"
        assert unchanged["version"] == fresh_version
        assert unchanged["approved_expenditure_limit_cents"] == 1000000000
        _, meta = validate_paginated(
            api_client.list_certificates(
                OFFICER, params={"superseded_certificate_id": certificate["id"]}
            )
        )
        assert meta["total_count"] == 0
        assert (
            refresh_health_service_area(world["hsa"]["id"])[
                "capital_authorization_committed_cents"
            ]
            == 1000000000
        )

        modification["expected_certificate_version"] = fresh_version
        successor = get_success_data(
            api_client.modify_certificate(certificate["id"], modification, OFFICER),
            201,
        )

        assert successor["superseded_certificate_id"] == certificate["id"]
        assert successor["lifecycle_status"] == "ISSUED"
        assert successor["lifecycle_status_before_suspension"] is None
        assert successor["approved_expenditure_limit_cents"] == NEW_LIMIT_CENTS
        assert successor["implementation_milestone_date"] == NEW_MILESTONE_DATE
        assert successor["authorized_bed_count"] == 12
        assert successor["extension_days_granted_total"] == 0
        assert successor["expenditure_status"] == "WITHIN_LIMIT"
        assert refresh_certificate(certificate["id"])["lifecycle_status"] == "SUPERSEDED"
        _, meta = validate_paginated(
            api_client.list_certificates(
                OFFICER, params={"superseded_certificate_id": certificate["id"]}
            )
        )
        assert meta["total_count"] == 1
        assert (
            refresh_health_service_area(world["hsa"]["id"])[
                "capital_authorization_committed_cents"
            ]
            == NEW_LIMIT_CENTS
        )


class TestExpenditureCeilingBoundaryWalk:
    def test_three_periods_walk_the_limit_the_ceiling_and_one_cent_beyond(self):
        """Exactly at the limit and exactly at the ceiling are both tolerated.

        PRD §3.8: "Separately, `expenditure_ceiling_cents` is the certificate's
        `approved_expenditure_limit_cents` multiplied by 1.05 — a five percent
        overrun tolerance band — rounded half up to a whole cent."
        PRD §3.8: "The **governing** figure is `cumulative_expenditure_accrual_cents`
        when the certificate's `expenditure_basis` is `ACCRUAL` and
        `cumulative_expenditure_cash_cents` when it is `CASH`."
        PRD §3.8: "The money axis is then set from a three-way comparison:
        `expenditure_status` becomes `WITHIN_LIMIT` when the governing figure is less
        than or equal to `approved_expenditure_limit_cents`;
        `OVER_LIMIT_PENDING_AMENDMENT` when it exceeds the limit but is still less
        than or equal to `expenditure_ceiling_cents`; and `LIMIT_BREACHED` when it
        exceeds the ceiling."
        PRD §3.8: "Each of those writes increases the certificate's `version` by 1
        and leaves `lifecycle_status` untouched."
        PRD §3.8: "When instead the money axis reaches `LIMIT_BREACHED` and the
        certificate's `lifecycle_status` is `ISSUED` or `IMPLEMENTED`, that breached
        value is itself the cause of a lifecycle suspension:
        `lifecycle_status_before_suspension` is set to whatever the lifecycle status
        currently is, `lifecycle_status` becomes `SUSPENDED`, the certificate's
        `version` increases by 1, and the applicant's `compliance_strike_count`
        increases by 1 — which in turn is what can flip that applicant's `standing`
        to `RESTRICTED` at 2 strikes or `BARRED` at 4."
        PRD §3.8: "And `latest_completion_pct` is taken as the
        `physical_completion_pct` of the contributing report with the greatest
        `period_end_date`, with the greatest `created_at` breaking a tie between two
        reports covering the same period end."

        Design: Corner/cross_cutting_complexity_layers/expenditure_ceiling_boundary_walks_within_limit_then_pending_amendment_then_breach
        """
        world = seed_issued_certificate()
        certificate = world["certificate"]
        applicant = world["applicant"]
        assert certificate["approved_expenditure_limit_cents"] == 1000000000
        assert certificate["expenditure_basis"] == "CASH"
        assert certificate["expenditure_ceiling_cents"] == EXPECTED_CEILING_CENTS

        file_progress_report(
            certificate,
            applicant,
            period_end_date=FIRST_PERIOD,
            disbursed_cents=1000000000,
            obligated_cents=0,
            physical_completion_pct=20.00,
        )
        at_limit = refresh_certificate(certificate["id"])
        assert at_limit["cumulative_expenditure_cash_cents"] == 1000000000
        assert at_limit["expenditure_status"] == "WITHIN_LIMIT"
        assert at_limit["lifecycle_status"] == "ISSUED"
        assert at_limit["lifecycle_status_before_suspension"] is None

        file_progress_report(
            at_limit,
            applicant,
            period_end_date=SECOND_PERIOD,
            disbursed_cents=50000000,
            obligated_cents=0,
            physical_completion_pct=30.00,
        )
        at_ceiling = refresh_certificate(certificate["id"])
        assert at_ceiling["cumulative_expenditure_cash_cents"] == EXPECTED_CEILING_CENTS
        assert at_ceiling["expenditure_status"] == "OVER_LIMIT_PENDING_AMENDMENT"
        assert at_ceiling["lifecycle_status"] == "ISSUED"
        assert at_ceiling["lifecycle_status_before_suspension"] is None

        breaching = file_progress_report(
            at_ceiling,
            applicant,
            period_end_date=THIRD_PERIOD,
            disbursed_cents=1,
            obligated_cents=0,
            physical_completion_pct=40.00,
        )

        assert breaching["status"] == "ACCEPTED"
        breached = refresh_certificate(certificate["id"])
        assert breached["cumulative_expenditure_cash_cents"] == 1050000001
        assert breached["expenditure_status"] == "LIMIT_BREACHED"
        assert breached["lifecycle_status"] == "SUSPENDED"
        assert breached["lifecycle_status_before_suspension"] == "ISSUED"
        assert breached["latest_completion_pct"] == 40.00
        struck = refresh_applicant(applicant["id"])
        assert struck["compliance_strike_count"] == 1
        assert struck["standing"] == "GOOD"
