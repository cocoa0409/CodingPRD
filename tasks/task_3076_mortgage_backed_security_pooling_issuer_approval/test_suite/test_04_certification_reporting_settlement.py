"""Certification workflow, pool activation, investor reporting, settlement,
and the pass-through payment calculation."""
from test_helpers import (
    TEST_DEFAULTS,
    TEST_USERS,
    assert_custodial_reconciliation,
    certify_pool,
    create_account,
    get_account,
    get_auto_report,
    get_issuer,
    get_payment_for_report,
    get_pool,
    get_success_data,
    list_payments_for_report,
    list_reports_for_pool,
    make_agency_reviewer_headers,
    make_document_custodian_headers,
    make_issuer_officer_headers,
    post_transaction,
    set_clock,
    setup_draft_pool_with_loans,
    setup_live_pool,
    setup_live_pool_with_accepted_report,
    setup_pool_with_open_breach,
    submit_report,
    accept_report,
    validate_error,
    validate_success,
)
from test_helpers.api_errors import ApiErrorId


class TestCertification:
    def test_exception_keeps_pool_assembled_then_certified_completes(self, api):
        """PRD §3.3: "When the `decision` is `EXCEPTION`, the certification is
        recorded, the flagged loans are stored, and the pool stays in
        `ASSEMBLED` — a retry loop in which the custodian re-certifies until a
        clean certification lands."

        Design: Corner/endpoints/certify_with_exception_keeps_pool_assembled
        """
        set_clock()
        issuer, custodian, pool, loans = setup_draft_pool_with_loans(
            "officer-exc", [120000000])
        get_success_data(api.assemble_pool(pool["id"], make_issuer_officer_headers(issuer["id"])))
        cert1 = validate_success(api.create_certification(
            pool["id"],
            {"decision": "EXCEPTION", "exception_loan_ids": [loans[0]["id"]]},
            make_document_custodian_headers(custodian["id"])), expected_status=201)
        assert cert1["decision"] == "EXCEPTION"
        assert cert1["exception_loan_ids"] == [loans[0]["id"]]
        assert get_pool(pool["id"])["status"] == "ASSEMBLED"
        certify_pool(custodian["id"], pool["id"])
        assert get_pool(pool["id"])["status"] == "CERTIFIED"
        certs = get_success_data(api.list_certifications(
            pool["id"], TEST_USERS["platform_admin_headers"]))
        assert len(certs) == 2
        assert {c["decision"] for c in certs} == {"EXCEPTION", "CERTIFIED"}


class TestActivationSideEffect:
    def test_activate_creates_draft_report_for_current_month(self, api):
        """PRD §3.3: "Activation has a notable side effect: it creates the
        pool's first investor report, a `DRAFT` report for the current clock
        month with a full-collection assumption (a collection rate of ten
        thousand basis points), with its scheduled, actual, and advance
        figures computed at creation exactly as any monthly report's would
        be."
        PRD §3.5: "the loan's scheduled monthly interest is computed as its
        `principal_balance_cents` multiplied by the pool's `note_rate_bps`,
        divided by ten thousand, divided by twelve months, and floored to
        integer cents — and these per-loan floored amounts are then summed."

        Design: Corner/state_machines/pool_activate_side_effect_creates_draft_report
        """
        set_clock("2026-09-03T00:00:00Z")
        issuer, custodian, pool, _loans = setup_live_pool("officer-se", [120000000])
        assert pool["status"] == "LIVE"
        reports = list_reports_for_pool(pool["id"])
        assert len(reports) == 1
        report = reports[0]
        assert report["period_month"] == "2026-09"
        assert report["status"] == "DRAFT"
        # floor(120000000 * 700 / 10000 / 12) = 700000; full collection -> actual == scheduled.
        assert report["scheduled_payment_cents"] == 700000
        assert report["actual_collected_cents"] == 700000
        assert report["advance_required_cents"] == 0


class TestPassThroughPaymentRounding:
    def test_scheduled_variant_rounds_per_loan_first(self, api):
        """PRD §3.5: "The evaluation order is pinned: each loan's interest is
        rounded first, then summed; summing first and rounding once is a
        different, wrong algorithm."

        Design: Difficulty/dual_variant_calc/pass_through_scheduled_vs_actual_collection
        """
        set_clock("2026-09-05T00:00:00Z")
        issuer, custodian, pool, _loans = setup_live_pool(
            "officer-canyon",
            [dict(principal_balance_cents=1000000000, note_rate_bps=780, government_insurance="VA"),
             dict(principal_balance_cents=1000100000, note_rate_bps=780, government_insurance="VA")],
            pool_overrides={"note_rate_bps": 680},
        )
        report = get_success_data(api.create_investor_report(
            {"pool_id": pool["id"], "period_month": "2026-10",
             "collection_rate_bps": 8000, "expected_pool_version": pool["version"]},
            make_issuer_officer_headers(issuer["id"])))
        # floor(1000000000*680/10000/12) + floor(1000100000*680/10000/12) = 5666666 + 5667233
        assert report["scheduled_payment_cents"] == 11333899

    def test_actual_variant_floors_once_after_scaling_unrounded_aggregate(self, api):
        """PRD §3.5: "the unrounded aggregate ratio — the sum over the same
        loans of each principal balance multiplied by the pool note rate,
        divided by ten thousand and by twelve — is scaled by the month's
        `collection_rate_bps` out of ten thousand and floored exactly once.
        The actual variant therefore differs from the scheduled variant by
        both the collection rate and the rounding order; it is not a per-loan
        rounding of actuals."
        PRD §3.5: "The `advance_required_cents` is the difference between the
        scheduled and actual figures."

        Design: Difficulty/dual_variant_calc/pass_through_scheduled_vs_actual_collection
        """
        set_clock("2026-09-05T00:00:00Z")
        issuer, custodian, pool, _loans = setup_live_pool(
            "officer-canyon2",
            [dict(principal_balance_cents=1000000000, note_rate_bps=780, government_insurance="VA"),
             dict(principal_balance_cents=1000100000, note_rate_bps=780, government_insurance="VA")],
            pool_overrides={"note_rate_bps": 680},
        )
        report = get_success_data(api.create_investor_report(
            {"pool_id": pool["id"], "period_month": "2026-10",
             "collection_rate_bps": 8000, "expected_pool_version": pool["version"]},
            make_issuer_officer_headers(issuer["id"])))
        # floor((2000100000*680/10000/12) * 8000/10000) = floor(11333900.0 * 0.8) = 9067120
        assert report["actual_collected_cents"] == 9067120
        assert report["advance_required_cents"] == 11333899 - 9067120
        # 9067120 != floor(11333899 * 0.8) == 9067119: the rounding order matters.
        assert report["actual_collected_cents"] != (11333899 * 8000) // 10000


class TestPassThroughRoundingOrder:
    def test_per_loan_round_first_proves_evaluation_order(self, api):
        """PRD §3.5: "The evaluation order is pinned: each loan's interest is
        rounded first, then summed; summing first and rounding once is a
        different, wrong algorithm."

        Design: Difficulty/combinatorial_formula/pass_through_payment_rounding_order_pinned
        """
        set_clock("2026-09-05T00:00:00Z")
        issuer, custodian, pool, _loans = setup_live_pool(
            "officer-ro1",
            [dict(principal_balance_cents=1000000000, note_rate_bps=780, government_insurance="VA"),
             dict(principal_balance_cents=1000100000, note_rate_bps=780, government_insurance="VA")],
            pool_overrides={"note_rate_bps": 680},
        )
        report = get_success_data(api.create_investor_report(
            {"pool_id": pool["id"], "period_month": "2026-10",
             "collection_rate_bps": 8000, "expected_pool_version": pool["version"]},
            make_issuer_officer_headers(issuer["id"])))
        # Per-loan first: floor(1000000000*680/10000/12) + floor(1000100000*680/10000/12)
        #               = 5666666 + 5667233 = 11333899.
        # Aggregate-first (wrong): floor((2000100000*680/10000/12)) = 11333900 —
        # a different figure, so the pinned evaluation order is observable here.
        assert report["scheduled_payment_cents"] == 5666666 + 5667233

    def test_actual_variant_disproves_scale_the_rounded_scheduled_order(self, api):
        """PRD §3.5: "the unrounded aggregate ratio — the sum over the same
        loans of each principal balance multiplied by the pool note rate,
        divided by ten thousand and by twelve — is scaled by the month's
        `collection_rate_bps` out of ten thousand and floored exactly once.
        The actual variant therefore differs from the scheduled variant by
        both the collection rate and the rounding order; it is not a per-loan
        rounding of actuals."

        Design: Difficulty/combinatorial_formula/pass_through_payment_rounding_order_pinned
        """
        set_clock("2026-09-05T00:00:00Z")
        issuer, custodian, pool, _loans = setup_live_pool(
            "officer-ro2",
            [dict(principal_balance_cents=1000000000, note_rate_bps=780, government_insurance="VA"),
             dict(principal_balance_cents=1000100000, note_rate_bps=780, government_insurance="VA")],
            pool_overrides={"note_rate_bps": 680},
        )
        report = get_success_data(api.create_investor_report(
            {"pool_id": pool["id"], "period_month": "2026-10",
             "collection_rate_bps": 8000, "expected_pool_version": pool["version"]},
            make_issuer_officer_headers(issuer["id"])))
        # Aggregate-then-floor: floor((2000100000*680/10000/12) * 8000/10000)
        #                     = floor(11333900.0 * 0.8) = 9067120.
        # Scaling the rounded scheduled figure would give floor(11333899*0.8) = 9067119.
        assert report["actual_collected_cents"] == 9067120
        assert report["actual_collected_cents"] != 9067119


class TestReportPeriodGranule:
    def test_same_month_rejected_adjacent_month_accepted(self, api):
        """PRD §3.5: "no other report already exists for the same pool and
        `period_month` (else `ERR_DUPLICATE_REPORT_PERIOD`)."

        Design: Difficulty/resource_temporal_overlap/report_period_duplicate_month_collision
        """
        set_clock("2026-09-03T00:00:00Z")
        issuer, custodian, pool, _loans = setup_live_pool("officer-gran", [120000000])
        headers = make_issuer_officer_headers(issuer["id"])
        # Activation auto-created the 2026-09 report; a same-month duplicate is rejected.
        resp = api.create_investor_report(
            {"pool_id": pool["id"], "period_month": "2026-09",
             "collection_rate_bps": 10000, "expected_pool_version": pool["version"]},
            headers)
        validate_error(resp, ApiErrorId.ERR_DUPLICATE_REPORT_PERIOD)
        # The immediately adjacent month is accepted.
        report2 = validate_success(api.create_investor_report(
            {"pool_id": pool["id"], "period_month": "2026-10",
             "collection_rate_bps": 10000, "expected_pool_version": pool["version"]},
            headers), expected_status=201)
        assert report2["period_month"] == "2026-10"
        assert report2["status"] == "DRAFT"

    def test_duplicate_period_creates_no_additional_report(self, api):
        """PRD §3.5: "no other report already exists for the same pool and
        `period_month` (else `ERR_DUPLICATE_REPORT_PERIOD`)."

        Design: Difficulty/resource_temporal_overlap/report_period_duplicate_month_collision
        """
        set_clock("2026-09-03T00:00:00Z")
        issuer, custodian, pool, _loans = setup_live_pool("officer-gran2", [120000000])
        headers = make_issuer_officer_headers(issuer["id"])
        reports_before = list_reports_for_pool(pool["id"])
        assert len(reports_before) == 1
        resp = api.create_investor_report(
            {"pool_id": pool["id"], "period_month": "2026-09",
             "collection_rate_bps": 10000, "expected_pool_version": pool["version"]},
            headers)
        validate_error(resp, ApiErrorId.ERR_DUPLICATE_REPORT_PERIOD)
        reports_after = list_reports_for_pool(pool["id"])
        assert len(reports_after) == 1


class TestReportAccept:
    def test_accept_generates_payment_obligation(self, api):
        """PRD §3.5: "Acceptance lands it in terminal `ACCEPTED` and creates
        the month's pass-through payment: a payment whose `report_id` points
        to the accepted report, whose `amount_cents` equals the report's
        `scheduled_payment_cents` — the full scheduled amount, owed
        regardless of borrower delinquency — whose `funding_source` is null
        until settled, and whose status begins at `DUE`."

        Design: Corner/endpoints/report_accept_generates_payment_obligation
        """
        set_clock("2026-09-03T00:00:00Z")
        issuer, custodian, pool, _loans = setup_live_pool("officer-ob", [120000000])
        report = get_auto_report(pool["id"])
        assert report["scheduled_payment_cents"] == 700000
        submit_report(issuer["id"], report["id"])
        accepted = validate_success(api.accept_report(
            report["id"], make_agency_reviewer_headers("reviewer-1")))
        assert accepted["status"] == "ACCEPTED"
        payments = list_payments_for_report(report["id"])
        assert len(payments) == 1
        payment = payments[0]
        assert payment["amount_cents"] == 700000
        assert payment["status"] == "DUE"
        assert payment["funding_source"] is None


class TestCustodialSettle:
    def test_custodial_settle_drains_interest_first(self, api):
        """PRD §3.6: "That disbursement draws from the interest bucket first —
        up to the full `interest_balance_cents` — and only then from the
        principal bucket for whatever remains; the interest-before-principal
        order is pinned."
        PRD §2.10: "for each custodial account, the `balance_cents` always
        equals the sum of deposit amounts minus the sum of disbursement
        amounts over all of the account's transactions, and always equals the
        sum of the account's two component balances — `principal_balance_cents`
        plus `interest_balance_cents` for a principal-and-interest account"

        Design: Difficulty/compensating_invariant/custodial_ledger_deposit_settle_reconciliation
        """
        set_clock("2026-09-10T00:00:00Z")
        issuer, custodian, pool, _loans = setup_live_pool(
            "officer-led", [120000000], pool_overrides={"note_rate_bps": 750})
        account = create_account(issuer["id"], "P_AND_I")
        post_transaction(issuer["id"], account["id"], "INTEREST", 1000000)
        report = get_auto_report(pool["id"])
        # payment = floor(120000000 * 750 / 10000 / 12) = 750000
        assert report["scheduled_payment_cents"] == 750000
        submit_report(issuer["id"], report["id"])
        accept_report(report["id"])
        payment = get_payment_for_report(report["id"])
        settled = validate_success(api.settle_payment(
            payment["id"], make_issuer_officer_headers(issuer["id"])))
        assert settled["status"] == "PAID"
        assert settled["funding_source"] == "CUSTODIAL"
        account_after = get_account(account["id"])
        assert account_after["balance_cents"] == 250000
        assert account_after["interest_balance_cents"] == 250000
        assert account_after["principal_balance_cents"] == 0
        assert_custodial_reconciliation(account_after)

    def test_custodial_settle_creates_no_advance(self, api):
        """PRD §3.6: "If the issuer's `P_AND_I` account is `ACTIVE` and its
        combined principal plus interest balances cover the payment's
        `amount_cents`, the settle succeeds through the custodial path"
        PRD §2.10: "a settle-as-advance raises it and the matching
        reimbursement lowers it by the same amount" — a custodial settle never
        creates an advance at all.

        Design: Difficulty/compensating_invariant/custodial_ledger_deposit_settle_reconciliation
        """
        set_clock("2026-09-10T00:00:00Z")
        issuer, custodian, pool, _loans = setup_live_pool(
            "officer-led2", [120000000], pool_overrides={"note_rate_bps": 750})
        account = create_account(issuer["id"], "P_AND_I")
        post_transaction(issuer["id"], account["id"], "INTEREST", 1000000)
        report = get_auto_report(pool["id"])
        submit_report(issuer["id"], report["id"])
        accept_report(report["id"])
        payment = get_payment_for_report(report["id"])
        validate_success(api.settle_payment(
            payment["id"], make_issuer_officer_headers(issuer["id"])))
        advances = get_success_data(api.list_liquidity_advances(
            TEST_USERS["platform_admin_headers"], params={"issuer_id": issuer["id"]}))
        assert advances == []


class TestAdvanceRoundtrip:
    def test_settle_as_advance_then_reimburse_restores_obligation(self, api):
        """PRD §2.10: "the sum of `amount_cents` over all advances in `OPEN`
        status across all issuers changes only through sanctioned pairs — a
        settle-as-advance raises it and the matching reimbursement lowers it
        by the same amount"
        PRD §3.6: "a liquidity advance is created for the pool's issuer in
        `OPEN` status with an `amount_cents` equal to the payment amount"

        Design: Difficulty/compensating_invariant/advance_obligation_settle_reimburse_roundtrip
        """
        set_clock("2026-09-10T00:00:00Z")
        issuer, custodian, pool, _loans, report, payment = (
            setup_live_pool_with_accepted_report(
                "officer-inv", [120000000], pool_overrides={"note_rate_bps": 750},
                liquid_assets_cents=500000000))
        # payment = floor(120000000 * 750 / 10000 / 12) = 750000
        assert payment["amount_cents"] == 750000
        assert get_issuer(issuer["id"])["advance_obligation_cents"] == 0
        headers = make_issuer_officer_headers(issuer["id"])
        settled = validate_success(api.settle_payment(payment["id"], headers))
        assert settled["status"] == "ADVANCED"
        issuer_mid = get_issuer(issuer["id"])
        assert issuer_mid["advance_obligation_cents"] == 750000
        advances = get_success_data(api.list_liquidity_advances(
            TEST_USERS["platform_admin_headers"], params={"issuer_id": issuer["id"]}))
        assert len(advances) == 1
        advance = advances[0]
        assert advance["status"] == "OPEN"
        assert advance["amount_cents"] == 750000
        assert advance["payment_id"] == payment["id"]
        reimbursed = validate_success(api.reimburse_advance(advance["id"], headers))
        assert reimbursed["status"] == "REIMBURSED"
        assert get_issuer(issuer["id"])["advance_obligation_cents"] == 0

    def test_advance_roundtrip_returns_global_total_to_zero(self, api):
        """PRD §2.10: "the sum of `amount_cents` over all advances in `OPEN`
        status across all issuers changes only through sanctioned pairs — a
        settle-as-advance raises it and the matching reimbursement lowers it
        by the same amount"

        Design: Difficulty/compensating_invariant/advance_obligation_settle_reimburse_roundtrip
        """
        set_clock("2026-09-10T00:00:00Z")
        issuer, custodian, pool, _loans, report, payment = (
            setup_live_pool_with_accepted_report(
                "officer-inv2", [120000000], pool_overrides={"note_rate_bps": 750},
                liquid_assets_cents=500000000))
        headers = make_issuer_officer_headers(issuer["id"])
        validate_success(api.settle_payment(payment["id"], headers))
        advance = get_success_data(api.list_liquidity_advances(
            TEST_USERS["platform_admin_headers"], params={"issuer_id": issuer["id"]}))[0]
        # Global open-advance total: exactly this issuer's 750000.
        open_total_mid = get_issuer(issuer["id"])["advance_obligation_cents"]
        assert open_total_mid == 750000
        validate_success(api.reimburse_advance(advance["id"], headers))
        # Round trip restores the pre-settle total of exactly zero.
        assert get_issuer(issuer["id"])["advance_obligation_cents"] == 0
