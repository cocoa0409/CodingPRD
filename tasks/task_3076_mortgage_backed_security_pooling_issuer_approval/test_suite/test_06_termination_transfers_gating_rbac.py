"""Pool termination boundaries, cross-entity state gating, validation
ordering, default/transfer extinguishment cascades, RBAC, auth, and
pagination envelope."""
from test_helpers import (
    NON_EXISTENT_UUID,
    TEST_USERS,
    accept_report,
    create_pool_payload,
    get_issuer,
    get_payment_for_report,
    get_pool,
    get_success_data,
    make_document_custodian_headers,
    make_issuer_officer_headers,
    reject_report,
    set_clock,
    setup_approved_issuer,
    setup_draft_pool_with_loans,
    setup_issuer_with_engagement,
    setup_live_pool,
    setup_live_pool_with_accepted_report,
    submit_report,
    get_auto_report,
    validate_error,
    validate_paginated,
    validate_success,
)
from test_helpers.api_errors import ApiErrorId
from test_helpers.factories import create_application_payload
from test_helpers.test_users import make_applicant_officer_headers


class TestPoolTerminationBoundary:
    def test_terminate_blocked_until_aggregate_principal_zero(self, api):
        """PRD §3.3: "termination requires the pool in `LIVE` (else
        `ERR_POOL_INVALID_STATE`), every loan paid off so that
        `aggregate_principal_cents` is exactly zero (else
        `ERR_POOL_NOT_FULLY_PAID`), and no investor report for the pool
        sitting in `DRAFT` or `SUBMITTED` (else `ERR_UNRESOLVED_RECORDS_EXIST`)."

        Design: Difficulty/boundary_precision_check/terminate_zero_principal_boundary
        """
        set_clock("2026-09-03T00:00:00Z")
        issuer, custodian, pool, loans = setup_live_pool(
            "officer-b2",
            [dict(principal_balance_cents=60000000, note_rate_bps=800, government_insurance="FHA"),
             dict(principal_balance_cents=60000000, note_rate_bps=800, government_insurance="VA")],
        )
        headers = make_issuer_officer_headers(issuer["id"])
        report = get_auto_report(pool["id"])
        submit_report(issuer["id"], report["id"])
        reject_report(report["id"])
        get_success_data(api.set_loan_delinquency_status(loans[0]["id"], "PAID_OFF", headers))
        # One loan still outstanding: aggregate 60000000 > 0.
        resp = api.terminate_pool(pool["id"], headers)
        validate_error(resp, ApiErrorId.ERR_POOL_NOT_FULLY_PAID)
        assert get_pool(pool["id"])["status"] == "LIVE"

    def test_terminate_succeeds_at_exactly_zero_principal(self, api):
        """PRD §3.3: "termination requires the pool in `LIVE` (else
        `ERR_POOL_INVALID_STATE`), every loan paid off so that
        `aggregate_principal_cents` is exactly zero (else
        `ERR_POOL_NOT_FULLY_PAID`), and no investor report for the pool
        sitting in `DRAFT` or `SUBMITTED` (else `ERR_UNRESOLVED_RECORDS_EXIST`)."
        PRD §3.7: "when the denominator is zero the rate is zero."

        Design: Difficulty/boundary_precision_check/terminate_zero_principal_boundary
        """
        set_clock("2026-09-03T00:00:00Z")
        issuer, custodian, pool, loans = setup_live_pool(
            "officer-b2z",
            [dict(principal_balance_cents=60000000, note_rate_bps=800, government_insurance="FHA"),
             dict(principal_balance_cents=60000000, note_rate_bps=800, government_insurance="VA")],
        )
        headers = make_issuer_officer_headers(issuer["id"])
        report = get_auto_report(pool["id"])
        submit_report(issuer["id"], report["id"])
        reject_report(report["id"])
        get_success_data(api.set_loan_delinquency_status(loans[0]["id"], "PAID_OFF", headers))
        get_success_data(api.set_loan_delinquency_status(loans[1]["id"], "PAID_OFF", headers))
        pool_mid = get_pool(pool["id"])
        assert pool_mid["aggregate_principal_cents"] == 0
        assert pool_mid["delinquency_rate_bps"] == 0
        terminated = validate_success(api.terminate_pool(pool["id"], headers))
        assert terminated["status"] == "TERMINATED"


class TestCrossEntityGating:
    def test_assemble_blocked_when_issuer_defaulted(self, api):
        """PRD §3.3: "the issuer must be `ACTIVE` (else
        `ERR_ISSUER_NOT_ACTIVE`)"

        Design: Difficulty/cross_entity_state_dependency/pool_assemble_gated_by_issuer_status
        """
        set_clock("2026-09-03T00:00:00Z")
        issuer, custodian, pool, _loans = setup_draft_pool_with_loans(
            "officer-g1", [120000000])
        validate_success(api.default_issuer(
            issuer["id"], TEST_USERS["agency_reviewer_headers"]))
        assert get_issuer(issuer["id"])["status"] == "DEFAULTED"
        resp = api.assemble_pool(pool["id"], make_issuer_officer_headers(issuer["id"]))
        validate_error(resp, ApiErrorId.ERR_ISSUER_NOT_ACTIVE)
        assert get_pool(pool["id"])["status"] == "DRAFT"

    def test_assemble_succeeds_while_issuer_active(self, api):
        """PRD §3.3: "the issuer must be `ACTIVE` (else
        `ERR_ISSUER_NOT_ACTIVE`)"

        Design: Difficulty/cross_entity_state_dependency/pool_assemble_gated_by_issuer_status
        """
        set_clock("2026-09-03T00:00:00Z")
        issuer, custodian, pool, _loans = setup_draft_pool_with_loans(
            "officer-g1b", [120000000])
        assert get_issuer(issuer["id"])["status"] == "ACTIVE"
        assembled = validate_success(api.assemble_pool(
            pool["id"], make_issuer_officer_headers(issuer["id"])))
        assert assembled["status"] == "ASSEMBLED"

    def _setup_transfer_pending_pool_with_draft_report(self, api, officer_id):
        """LIVE pool + DRAFT report for 2026-10, then default + transfer
        initiation parking the pool in TRANSFER_PENDING."""
        set_clock("2026-09-03T00:00:00Z")
        issuer, custodian, pool, _loans = setup_live_pool(
            officer_id, [120000000])
        headers = make_issuer_officer_headers(issuer["id"])
        # Accept the auto-created 2026-09 report so only the manual DRAFT remains.
        auto_report = get_auto_report(pool["id"])
        submit_report(issuer["id"], auto_report["id"])
        accept_report(auto_report["id"])
        report = get_success_data(api.create_investor_report(
            {"pool_id": pool["id"], "period_month": "2026-10",
             "collection_rate_bps": 10000, "expected_pool_version": pool["version"]},
            headers))
        assert report["status"] == "DRAFT"
        successor = setup_approved_issuer(
            f"{officer_id}-succ", liquid_assets_cents=900000000)
        validate_success(api.default_issuer(
            issuer["id"], TEST_USERS["agency_reviewer_headers"]))
        defaulted_version = get_issuer(issuer["id"])["version"]
        transfer = validate_success(api.create_portfolio_transfer(
            {"defaulted_issuer_id": issuer["id"],
             "successor_issuer_id": successor["id"],
             "expected_defaulted_issuer_version": defaulted_version},
            TEST_USERS["agency_reviewer_headers"]), expected_status=201)
        assert get_pool(pool["id"])["status"] == "TRANSFER_PENDING"
        return issuer, successor, pool, report, transfer

    def test_report_submit_blocked_when_pool_transfer_pending(self, api):
        """PRD §3.5: "Submission requires that the report's pool is in
        `CERTIFIED` or `LIVE` and belongs to the acting issuer (else
        `ERR_NOT_RESOURCE_OWNER`), that the report is in `DRAFT` (else
        `ERR_REPORT_INVALID_STATE`)"
        PRD §2.7: "(5) state-machine legality of the requested transition,
        where each resource family reports its own invalid-state error (for
        example `ERR_POOL_INVALID_STATE` for pools, `ERR_ACCOUNT_INVALID_STATE`
        for custodial accounts, and `ERR_REPORT_INVALID_STATE` for reports)"

        Design: Difficulty/cross_entity_state_dependency/report_submit_gated_by_pool_status
        """
        issuer, successor, pool, report, transfer = (
            self._setup_transfer_pending_pool_with_draft_report(api, "officer-g2"))
        resp = api.submit_report(report["id"], make_issuer_officer_headers(issuer["id"]))
        validate_error(resp, ApiErrorId.ERR_POOL_INVALID_STATE)
        reread = get_success_data(api.get_investor_report(
            report["id"], TEST_USERS["platform_admin_headers"]))
        assert reread["status"] == "DRAFT"

    def test_pool_enters_transfer_pending_on_transfer_initiation(self, api):
        """PRD §3.8: "Initiation increments the defaulted issuer's `version`
        and parks every one of its `LIVE` pools into `TRANSFER_PENDING`,
        suspending their custodial exposure pending the successor's answer."

        Design: Difficulty/cross_entity_state_dependency/report_submit_gated_by_pool_status
        """
        issuer, successor, pool, report, transfer = (
            self._setup_transfer_pending_pool_with_draft_report(api, "officer-g2b"))
        assert transfer["status"] == "INITIATED"
        assert transfer["defaulted_issuer_id"] == issuer["id"]
        assert transfer["successor_issuer_id"] == successor["id"]
        assert get_pool(pool["id"])["status"] == "TRANSFER_PENDING"


class TestValidationOrdering:
    def test_activate_draft_pool_reports_state_error(self, api):
        """PRD §3.3: "Activation moves a pool from `CERTIFIED` to `LIVE`; an
        attempt from any other state fails with `ERR_POOL_INVALID_STATE`"
        PRD §2.7: "state-machine legality of the requested transition"
        precedes "safety and compliance gates such as application thresholds,
        segregation of duties, successor capitalization, and pool composition".

        Design: Difficulty/priority_pair_validation_conflict/state_vs_business_safety_on_pool_assemble
        """
        set_clock("2026-09-03T00:00:00Z")
        issuer, custodian, pool, _loans = setup_draft_pool_with_loans(
            "officer-p1", [1200000])
        resp = api.activate_pool(pool["id"], make_issuer_officer_headers(issuer["id"]))
        validate_error(resp, ApiErrorId.ERR_POOL_INVALID_STATE)

    def test_under_minimum_draft_pool_reports_business_gate(self, api):
        """PRD §3.3: "the pool's `aggregate_principal_cents` must be at least
        one hundred million cents, a one-million-dollar minimum pool balance
        (else `ERR_POOL_BELOW_MINIMUM_PRINCIPAL`)."
        PRD §2.7: "state-machine legality of the requested transition"
        precedes "safety and compliance gates such as application thresholds,
        segregation of duties, successor capitalization, and pool composition".

        Design: Difficulty/priority_pair_validation_conflict/state_vs_business_safety_on_pool_assemble
        """
        set_clock("2026-09-03T00:00:00Z")
        issuer, custodian, pool, _loans = setup_draft_pool_with_loans(
            "officer-p1b", [50000000])
        # Pool is DRAFT (state precondition passes) but aggregate 50000000 <
        # 100000000: the business gate fires.
        resp = api.assemble_pool(pool["id"], make_issuer_officer_headers(issuer["id"]))
        validate_error(resp, ApiErrorId.ERR_POOL_BELOW_MINIMUM_PRINCIPAL)

    def _setup_two_issuers_with_live_pool(self, api):
        set_clock("2026-09-03T00:00:00Z")
        issuer_a, custodian, pool, _loans = setup_live_pool(
            "officer-ownA", [120000000])
        issuer_b = setup_approved_issuer("officer-ownB")
        return issuer_a, issuer_b, pool

    def test_wrong_owner_report_create_reports_ownership_error(self, api):
        """PRD §2.1: "a pool's `issuer_id`, an engagement's `issuer_id`, an
        advance's `issuer_id`, a custodial account's `issuer_id`, or the
        issuer that owns a loan's, report's, payment's, or plan's pool —
        compare that foreign-key field to `X-User-ID`, and a mismatch is
        rejected with `ERR_NOT_RESOURCE_OWNER`."

        Design: Difficulty/priority_pair_validation_conflict/auth_vs_business_referential_on_report_create
        """
        issuer_a, issuer_b, pool = self._setup_two_issuers_with_live_pool(api)
        resp = api.create_investor_report(
            {"pool_id": pool["id"], "period_month": "2026-10",
             "collection_rate_bps": 10000, "expected_pool_version": pool["version"]},
            make_issuer_officer_headers(issuer_b["id"]))
        validate_error(resp, ApiErrorId.ERR_NOT_RESOURCE_OWNER)

    def test_wrong_owner_duplicate_period_still_reports_ownership_error(self, api):
        """PRD §2.7: "the server reports the earliest failing check in a fixed
        priority order" — "(4) ownership, for `IssuerOfficer` write
        operations" precedes "(8) referential business rules such as insurer
        eligibility, note-rate bands, account-type uniqueness, report-period
        uniqueness, engagement-window disjointness, and engagement coverage".

        Design: Difficulty/priority_pair_validation_conflict/auth_vs_business_referential_on_report_create
        """
        issuer_a, issuer_b, pool = self._setup_two_issuers_with_live_pool(api)
        # The 2026-09 auto report already exists for this pool: a duplicate
        # period AND an ownership violation — ownership must surface.
        reports_before = get_success_data(api.list_investor_reports(
            TEST_USERS["platform_admin_headers"], params={"pool_id": pool["id"]}))
        resp = api.create_investor_report(
            {"pool_id": pool["id"], "period_month": "2026-09",
             "collection_rate_bps": 10000, "expected_pool_version": pool["version"]},
            make_issuer_officer_headers(issuer_b["id"]))
        validate_error(resp, ApiErrorId.ERR_NOT_RESOURCE_OWNER)
        reports_after = get_success_data(api.list_investor_reports(
            TEST_USERS["platform_admin_headers"], params={"pool_id": pool["id"]}))
        assert len(reports_after) == len(reports_before)


class TestTransferAcceptCascade:
    def _setup_defaulted_issuer_with_advance(self, api):
        """Defaulted issuer D with a LIVE pool settled via a 750000-cent OPEN
        advance, and ACTIVE successor S; transfer INITIATED."""
        set_clock("2026-09-10T00:00:00Z")
        issuer_d, custodian, pool, _loans, report, payment = (
            setup_live_pool_with_accepted_report(
                "officer-doom", [120000000], pool_overrides={"note_rate_bps": 750},
                liquid_assets_cents=500000000))
        assert payment["amount_cents"] == 750000
        settled = validate_success(api.settle_payment(
            payment["id"], make_issuer_officer_headers(issuer_d["id"])))
        assert settled["status"] == "ADVANCED"
        issuer_s = setup_approved_issuer(
            "officer-knight", liquid_assets_cents=500000000)
        validate_success(api.default_issuer(
            issuer_d["id"], TEST_USERS["agency_reviewer_headers"]))
        defaulted_version = get_issuer(issuer_d["id"])["version"]
        transfer = validate_success(api.create_portfolio_transfer(
            {"defaulted_issuer_id": issuer_d["id"],
             "successor_issuer_id": issuer_s["id"],
             "expected_defaulted_issuer_version": defaulted_version},
            TEST_USERS["agency_reviewer_headers"]), expected_status=201)
        assert get_pool(pool["id"])["status"] == "TRANSFER_PENDING"
        return issuer_d, issuer_s, pool, transfer

    def test_accept_moves_pool_and_advances_to_successor(self, api):
        """PRD §3.8: "An accepted transfer moves to `COMPLETED` and executes
        the full cascade: every `TRANSFER_PENDING` pool returns to `LIVE` with
        its `issuer_id` reassigned to the successor; every `OPEN` advance of
        the defaulted issuer is reassigned to the successor with no change to
        the global open-advance total; the defaulted issuer moves to
        `EXTINGUISHED` and its frozen custodial accounts close `FROZEN` to
        `CLOSED`"

        Design: Corner/cross_cutting_layers/portfolio_transfer_accept_moves_pools_and_advances
        """
        issuer_d, issuer_s, pool, transfer = (
            self._setup_defaulted_issuer_with_advance(api))
        completed = validate_success(api.accept_transfer(
            transfer["id"], TEST_USERS["agency_reviewer_headers"]))
        assert completed["status"] == "COMPLETED"
        pool_after = get_pool(pool["id"])
        assert pool_after["status"] == "LIVE"
        assert pool_after["issuer_id"] == issuer_s["id"]
        issuer_d_after = get_issuer(issuer_d["id"])
        assert issuer_d_after["status"] == "EXTINGUISHED"
        assert issuer_d_after["advance_obligation_cents"] == 0

    def test_accept_conserves_global_open_advance_total(self, api):
        """PRD §2.10: "a transfer acceptance moves open advances from the
        defaulted issuer to the successor with zero change to the global
        open-advance total"

        Design: Corner/cross_cutting_layers/portfolio_transfer_accept_moves_pools_and_advances
        """
        issuer_d, issuer_s, pool, transfer = (
            self._setup_defaulted_issuer_with_advance(api))
        validate_success(api.accept_transfer(
            transfer["id"], TEST_USERS["agency_reviewer_headers"]))
        issuer_s_after = get_issuer(issuer_s["id"])
        assert issuer_s_after["advance_obligation_cents"] == 750000
        advances_d = get_success_data(api.list_liquidity_advances(
            TEST_USERS["platform_admin_headers"], params={"issuer_id": issuer_d["id"]}))
        advances_s = get_success_data(api.list_liquidity_advances(
            TEST_USERS["platform_admin_headers"], params={"issuer_id": issuer_s["id"]}))
        assert all(a["status"] != "OPEN" for a in advances_d) or advances_d == []
        assert sum(a["amount_cents"] for a in advances_s if a["status"] == "OPEN") == 750000


class TestRbac:
    def test_issuer_officer_cannot_approve_application(self, api):
        """PRD §4 endpoint table: "POST | `/issuer-applications/{id}/approve`
        | Approve application; creates Issuer | AgencyReviewer"
        PRD §2.1: "A request whose role is recognized but not permitted for
        the target endpoint is rejected with `ERR_UNAUTHORIZED_ROLE`."

        Design: Corner/rbac/issuer_officer_cannot_approve_application
        """
        app = get_success_data(api.create_application(
            create_application_payload(
                legal_name="RBAC Lending",
                net_worth_cents=400000000, liquid_assets_cents=5000000,
                origination_experience_months=36, branch_count=1,
                annual_origination_volume_cents=1000000000),
            make_applicant_officer_headers("officer-rbac")))
        get_success_data(api.submit_application(
            app["id"], make_applicant_officer_headers("officer-rbac")))
        get_success_data(api.review_application(
            app["id"], TEST_USERS["agency_reviewer_headers"]))
        resp = api.approve_application(
            app["id"], make_issuer_officer_headers("officer-rbac"))
        validate_error(resp, ApiErrorId.ERR_UNAUTHORIZED_ROLE)
        reread = get_success_data(api.get_application(
            app["id"], TEST_USERS["platform_admin_headers"]))
        assert reread["status"] == "UNDER_REVIEW"

    def test_custodian_cannot_create_pools(self, api):
        """PRD §4 endpoint table: "POST | `/pools` | Create pool in DRAFT
        (OCC-guarded on issuer version) | IssuerOfficer"
        PRD §2.1: "A request whose role is recognized but not permitted for
        the target endpoint is rejected with `ERR_UNAUTHORIZED_ROLE`."

        Design: Corner/rbac/custodian_cannot_create_pools
        """
        set_clock("2026-09-03T00:00:00Z")
        issuer, custodian, _eng = setup_issuer_with_engagement("officer-rb2")
        resp = api.create_pool(
            create_pool_payload(
                issuer["id"], custodian["id"], get_issuer(issuer["id"])["version"]),
            make_document_custodian_headers(custodian["id"]))
        validate_error(resp, ApiErrorId.ERR_UNAUTHORIZED_ROLE)
        pools = get_success_data(api.list_pools(
            TEST_USERS["platform_admin_headers"], params={"issuer_id": issuer["id"]}))
        assert pools == []


class TestAuthentication:
    def test_missing_headers_rejected_unauthenticated(self, api):
        """PRD §2.1: "A request missing either header, or carrying a role
        value the system does not recognize, is rejected with
        `ERR_UNAUTHENTICATED`."

        Design: Corner/errors/unauthenticated_missing_headers
        """
        resp = api.list_issuers(headers={})
        validate_error(resp, ApiErrorId.ERR_UNAUTHENTICATED, expected_status=401)


class TestPagination:
    def test_list_applications_pagination_envelope(self, api):
        """PRD §2.3: "The `limit` parameter caps the number of items returned;
        it defaults to 10, with a minimum of 1 and a maximum of 100. The
        `offset` parameter skips a number of items from the front of the
        result set and defaults to 0."
        PRD §2.3: "List responses carry the pagination fields `limit`,
        `offset`, `total_count`, and `has_more` in the `meta` object of the
        response envelope."

        Design: Corner/entities/list_endpoint_pagination_envelope
        """
        get_success_data(api.create_application(
            create_application_payload(legal_name="Page One Lending"),
            make_applicant_officer_headers("officer-pg1")))
        get_success_data(api.create_application(
            create_application_payload(legal_name="Page Two Lending"),
            make_applicant_officer_headers("officer-pg2")))
        resp = api.list_applications(
            TEST_USERS["platform_admin_headers"], params={"limit": 1, "offset": 0})
        data, meta = validate_paginated(resp)
        assert len(data) == 1
        assert meta["limit"] == 1
        assert meta["offset"] == 0
        assert meta["total_count"] == 2
        assert meta["has_more"] is True
