"""Delinquency cascades, breach lifecycle, liquidity ratios, and issuer
recovery."""
from test_helpers import (
    TEST_USERS,
    create_account,
    create_corrective_action_plan_payload,
    create_pool_payload,
    get_account,
    get_issuer,
    get_pool,
    get_success_data,
    make_agency_reviewer_headers,
    make_document_custodian_headers,
    make_issuer_officer_headers,
    set_clock,
    setup_approved_issuer,
    setup_draft_pool_with_loans,
    setup_live_pool,
    setup_live_pool_with_accepted_report,
    setup_pool_with_open_breach,
    submit_report,
    accept_report,
    get_auto_report,
    get_payment_for_report,
    validate_error,
    validate_success,
)
from test_helpers.api_errors import ApiErrorId


def _list_breaches(api, pool_id):
    return get_success_data(api.list_delinquency_breaches(
        TEST_USERS["platform_admin_headers"], params={"pool_id": pool_id}))


class TestDelinquencyCascade:
    def test_delinquent_set_entry_breaches_threshold_and_watches_issuer(self, api):
        """PRD §3.7: "The numerator is the total `principal_balance_cents` of
        the pool's loans in `DELINQ_60`, `DELINQ_90_PLUS`, or `FORECLOSURE`"
        PRD §3.7: "When the recomputed rate is at least five hundred basis
        points — five percent of aggregate principal, with exactly five
        hundred breaching — and no breach for the pool is currently `OPEN` or
        `MITIGATING`, the system creates a delinquency breach in `OPEN` status
        recording the owning `issuer_id`, the `pool_id`, and the current rate
        as `delinquency_rate_bps_at_breach`; if the issuer is `ACTIVE` it
        simultaneously moves to `WATCH`"

        Design: Difficulty/transitive_cascade/loan_delinquency_breach_issuer_watch_cascade
        """
        set_clock("2026-09-03T00:00:00Z")
        issuer, custodian, pool, loans = setup_live_pool(
            "officer-c1",
            [dict(principal_balance_cents=40000000, note_rate_bps=800, government_insurance="FHA"),
             dict(principal_balance_cents=80000000, note_rate_bps=820, government_insurance="VA")],
        )
        headers = make_issuer_officer_headers(issuer["id"])
        loan_b = loans[1]
        get_success_data(api.set_loan_delinquency_status(loan_b["id"], "DELINQ_30", headers))
        get_success_data(api.set_loan_delinquency_status(loan_b["id"], "DELINQ_60", headers))
        pool_after = get_pool(pool["id"])
        # round_half_up(80000000 * 10000 / 120000000) = 6667
        assert pool_after["delinquency_rate_bps"] == 6667
        breaches = _list_breaches(api, pool["id"])
        assert len(breaches) == 1
        assert breaches[0]["status"] == "OPEN"
        assert breaches[0]["delinquency_rate_bps_at_breach"] == 6667
        assert get_issuer(issuer["id"])["status"] == "WATCH"

    def test_delinq_30_creates_no_breach(self, api):
        """PRD §3.7: "`DELINQ_30` is never counted in the delinquent set"

        Design: Difficulty/transitive_cascade/loan_delinquency_breach_issuer_watch_cascade
        """
        set_clock("2026-09-03T00:00:00Z")
        issuer, custodian, pool, loans = setup_live_pool(
            "officer-c1b",
            [dict(principal_balance_cents=40000000, note_rate_bps=800, government_insurance="FHA"),
             dict(principal_balance_cents=80000000, note_rate_bps=820, government_insurance="VA")],
        )
        headers = make_issuer_officer_headers(issuer["id"])
        get_success_data(api.set_loan_delinquency_status(loans[1]["id"], "DELINQ_30", headers))
        assert _list_breaches(api, pool["id"]) == []
        assert get_pool(pool["id"])["delinquency_rate_bps"] == 0
        assert get_issuer(issuer["id"])["status"] == "ACTIVE"


class TestDelinquencyBoundary:
    def test_exactly_five_hundred_bps_breaches(self, api):
        """PRD §3.7: "When the recomputed rate is at least five hundred basis
        points — five percent of aggregate principal, with exactly five
        hundred breaching — and no breach for the pool is currently `OPEN` or
        `MITIGATING`, the system creates a delinquency breach in `OPEN` status"

        Design: Difficulty/boundary_precision_check/delinquency_threshold_exactly_500_breaches
        """
        set_clock("2026-09-03T00:00:00Z")
        # Delinquent principal exactly 5% of the 100000000-cent aggregate:
        # round_half_up(5000000 * 10000 / 100000000) = 500.
        issuer, custodian, pool, loans = setup_live_pool(
            "officer-b1",
            [dict(principal_balance_cents=5000000, note_rate_bps=800, government_insurance="FHA"),
             dict(principal_balance_cents=95000000, note_rate_bps=800, government_insurance="VA")],
        )
        headers = make_issuer_officer_headers(issuer["id"])
        get_success_data(api.set_loan_delinquency_status(loans[0]["id"], "DELINQ_30", headers))
        get_success_data(api.set_loan_delinquency_status(loans[0]["id"], "DELINQ_60", headers))
        assert get_pool(pool["id"])["delinquency_rate_bps"] == 500
        breaches = _list_breaches(api, pool["id"])
        assert len(breaches) == 1
        assert breaches[0]["status"] == "OPEN"
        assert get_issuer(issuer["id"])["status"] == "WATCH"

    def test_delinq_30_alone_stays_below_threshold(self, api):
        """PRD §3.7: "`DELINQ_30` is never counted in the delinquent set"

        Design: Difficulty/boundary_precision_check/delinquency_threshold_exactly_500_breaches
        """
        set_clock("2026-09-03T00:00:00Z")
        issuer, custodian, pool, loans = setup_live_pool(
            "officer-b1z",
            [dict(principal_balance_cents=100000000, note_rate_bps=800, government_insurance="FHA"),
             dict(principal_balance_cents=100000000, note_rate_bps=800, government_insurance="VA")],
        )
        headers = make_issuer_officer_headers(issuer["id"])
        get_success_data(api.set_loan_delinquency_status(loans[0]["id"], "DELINQ_30", headers))
        assert get_pool(pool["id"])["delinquency_rate_bps"] == 0
        assert _list_breaches(api, pool["id"]) == []


class TestPaidOffExitsBothSides:
    def test_payoff_removes_loan_from_numerator_and_denominator(self, api):
        """PRD §3.7: "the denominator is the pool's `aggregate_principal_cents`,
        the total over loans not `PAID_OFF`. `DELINQ_30` is never counted in
        the delinquent set, and a paid-off loan leaves both numerator and
        denominator."

        Design: Corner/calculations/delinquency_rate_paid_off_exits_both_sides
        """
        set_clock("2026-09-03T00:00:00Z")
        issuer, custodian, pool, loan_a, loan_b, breach = setup_pool_with_open_breach(
            "officer-eb", 100000000, 100000000)
        assert get_pool(pool["id"])["delinquency_rate_bps"] == 5000
        headers = make_issuer_officer_headers(issuer["id"])
        get_success_data(api.set_loan_delinquency_status(loan_a["id"], "PAID_OFF", headers))
        pool_after = get_pool(pool["id"])
        assert pool_after["aggregate_principal_cents"] == 100000000
        assert pool_after["delinquency_rate_bps"] == 0

    def test_payoff_never_auto_closes_breach(self, api):
        """PRD §3.7: "Closing a breach is never automatic: even when the rate
        later falls back below threshold, the breach stays open until an
        `AgencyReviewer` closes it, and the issuer stays at `WATCH` until
        closure."

        Design: Corner/calculations/delinquency_rate_paid_off_exits_both_sides
        """
        set_clock("2026-09-03T00:00:00Z")
        issuer, custodian, pool, loan_a, loan_b, breach = setup_pool_with_open_breach(
            "officer-eb2", 100000000, 100000000)
        headers = make_issuer_officer_headers(issuer["id"])
        get_success_data(api.set_loan_delinquency_status(loan_a["id"], "PAID_OFF", headers))
        after = get_success_data(api.get_delinquency_breach(
            breach["id"], TEST_USERS["platform_admin_headers"]))
        assert after["status"] == "OPEN"


class TestTerminalLoanLockdown:
    def test_paid_off_loan_rejects_further_transitions(self, api):
        """PRD §3.7: "Any other pairing — a skipped rung, a move out of
        `FORECLOSURE`, or any move out of `PAID_OFF` — is rejected with
        `ERR_LOAN_INVALID_STATE`"

        Design: Corner/state_machines/loan_terminal_paid_off_lockdown
        """
        set_clock("2026-09-03T00:00:00Z")
        issuer, custodian, pool, loans = setup_draft_pool_with_loans(
            "officer-tl", [120000000])
        headers = make_issuer_officer_headers(issuer["id"])
        get_success_data(api.set_loan_delinquency_status(loans[0]["id"], "PAID_OFF", headers))
        resp = api.set_loan_delinquency_status(loans[0]["id"], "DELINQ_30", headers)
        validate_error(resp, ApiErrorId.ERR_LOAN_INVALID_STATE)
        loan_after = get_success_data(api.get_loan(loans[0]["id"], TEST_USERS["platform_admin_headers"]))
        assert loan_after["status"] == "PAID_OFF"
        assert get_pool(pool["id"])["aggregate_principal_cents"] == 0


class TestBreachLifecycle:
    def test_watch_active_recovery_cycle_via_cap_and_close(self, api):
        """PRD §3.7: "Acceptance moves the plan to `ACCEPTED` and the breach
        from `OPEN` to `MITIGATING`, and re-evaluates the issuer"
        PRD §3.7: "Closing a breach is never automatic: even when the rate
        later falls back below threshold, the breach stays open until an
        `AgencyReviewer` closes it, and the issuer stays at `WATCH` until
        closure."

        Design: Difficulty/non_linear_state_machine/issuer_watch_active_recovery_cycle
        """
        set_clock("2026-09-03T00:00:00Z")
        issuer, custodian, pool, loans = setup_live_pool(
            "officer-cw",
            [dict(principal_balance_cents=40000000, note_rate_bps=800, government_insurance="FHA"),
             dict(principal_balance_cents=80000000, note_rate_bps=820, government_insurance="VA")],
        )
        headers = make_issuer_officer_headers(issuer["id"])
        reviewer = make_agency_reviewer_headers("reviewer-1")
        loan_b = loans[1]
        get_success_data(api.set_loan_delinquency_status(loan_b["id"], "DELINQ_30", headers))
        get_success_data(api.set_loan_delinquency_status(loan_b["id"], "DELINQ_60", headers))
        breach = _list_breaches(api, pool["id"])[0]
        assert get_issuer(issuer["id"])["status"] == "WATCH"
        # Corrective action plan accepted: breach OPEN -> MITIGATING, issuer stays WATCH.
        plan = validate_success(api.create_corrective_action_plan(
            create_corrective_action_plan_payload(breach["id"]), headers), expected_status=201)
        validate_success(api.accept_plan(plan["id"], reviewer))
        breach_mid = get_success_data(api.get_delinquency_breach(
            breach["id"], TEST_USERS["platform_admin_headers"]))
        assert breach_mid["status"] == "MITIGATING"
        assert get_issuer(issuer["id"])["status"] == "WATCH"
        # Cure the loan: rate recomputes to 0 but the breach is NOT auto-closed.
        get_success_data(api.set_loan_delinquency_status(loan_b["id"], "CURRENT", headers))
        assert get_pool(pool["id"])["delinquency_rate_bps"] == 0
        breach_cured = get_success_data(api.get_delinquency_breach(
            breach["id"], TEST_USERS["platform_admin_headers"]))
        assert breach_cured["status"] == "MITIGATING"
        # Agency close completes the cycle: issuer returns to ACTIVE.
        closed = validate_success(api.close_breach(breach["id"], reviewer))
        assert closed["status"] == "CLOSED"
        assert get_issuer(issuer["id"])["status"] == "ACTIVE"

    def test_issuer_stays_watch_until_agency_closes_breach(self, api):
        """PRD §3.7: "Closing a breach is never automatic: even when the rate
        later falls back below threshold, the breach stays open until an
        `AgencyReviewer` closes it, and the issuer stays at `WATCH` until
        closure."

        Design: Difficulty/non_linear_state_machine/issuer_watch_active_recovery_cycle
        """
        set_clock("2026-09-03T00:00:00Z")
        issuer, custodian, pool, loan_a, loan_b, breach = setup_pool_with_open_breach(
            "officer-cw2", 40000000, 80000000)
        headers = make_issuer_officer_headers(issuer["id"])
        reviewer = make_agency_reviewer_headers("reviewer-1")
        assert get_issuer(issuer["id"])["status"] == "WATCH"
        # Cure the loan without any plan or close: rate falls to 0.
        get_success_data(api.set_loan_delinquency_status(loan_a["id"], "CURRENT", headers))
        assert get_pool(pool["id"])["delinquency_rate_bps"] == 0
        # Breach remains OPEN and the issuer remains WATCH — no auto-closure.
        after = get_success_data(api.get_delinquency_breach(
            breach["id"], TEST_USERS["platform_admin_headers"]))
        assert after["status"] == "OPEN"
        assert get_issuer(issuer["id"])["status"] == "WATCH"
        # The agency close completes the cycle.
        closed = validate_success(api.close_breach(breach["id"], reviewer))
        assert closed["status"] == "CLOSED"
        assert get_issuer(issuer["id"])["status"] == "ACTIVE"

    def test_breach_close_rejected_while_still_breaching(self, api):
        """PRD §3.7: "requires the breaching pool's current
        `delinquency_rate_bps` to be back below the five-hundred-basis-point
        threshold (else `ERR_BREACH_STILL_BREACHING`)"

        Design: Corner/calculations/pool_threshold_evaluation_constants_applied
        """
        set_clock("2026-09-03T00:00:00Z")
        issuer, custodian, pool, loan_a, loan_b, breach = setup_pool_with_open_breach(
            "officer-k", 100000000, 100000000)
        assert get_pool(pool["id"])["delinquency_rate_bps"] == 5000
        resp = api.close_breach(breach["id"], make_agency_reviewer_headers("reviewer-1"))
        validate_error(resp, ApiErrorId.ERR_BREACH_STILL_BREACHING)
        after = get_success_data(api.get_delinquency_breach(
            breach["id"], TEST_USERS["platform_admin_headers"]))
        assert after["status"] == "OPEN"
        assert get_issuer(issuer["id"])["status"] == "WATCH"


class TestLiquidityRatios:
    def _setup_advanced_issuer(self, api, officer_id, liquid_assets_cents=100000,
                               unused_credit_lines_cents=0):
        """Issuer whose 2812500-cent payment settles as an ADVANCE.

        Pool note 750; single loan 450000000 cents at note 850 bps.
        payment = floor(450000000 * 750 / 10000 / 12) = 2812500.
        The issuer has no P_AND_I account, so the settle routes to ADVANCE.
        """
        set_clock("2026-09-10T00:00:00Z")
        issuer, custodian, pool, _loans = setup_live_pool(
            officer_id,
            [dict(principal_balance_cents=450000000, note_rate_bps=850, government_insurance="FHA")],
            pool_overrides={"note_rate_bps": 750},
            liquid_assets_cents=9000000,
        )
        # Patch financials to the target liquidity posture.
        issuer_now = get_issuer(issuer["id"])
        get_success_data(api.patch_issuer_financials(
            issuer["id"],
            {"expected_issuer_version": issuer_now["version"],
             "liquid_assets_cents": liquid_assets_cents,
             "unused_credit_lines_cents": unused_credit_lines_cents},
            make_issuer_officer_headers(issuer["id"])))
        report = get_auto_report(pool["id"])
        assert report["scheduled_payment_cents"] == 2812500
        submit_report(issuer["id"], report["id"])
        accept_report(report["id"])
        payment = get_payment_for_report(report["id"])
        settled = validate_success(api.settle_payment(
            payment["id"], make_issuer_officer_headers(issuer["id"])))
        return issuer, payment, settled

    def test_excluding_and_including_ratios_differ_by_credit_numerator(self, api):
        """PRD §3.6: "The `liquidity_ratio_excluding_credit_bps` divides the
        issuer's `liquid_assets_cents` alone by the obligation, scaled to
        basis points. The `liquidity_ratio_including_credit_bps` adds the
        issuer's `unused_credit_lines_cents` to the numerator against the same
        denominator — the two ratios differ for an identical obligation purely
        because the numerators differ."

        Design: Difficulty/dual_variant_calc/liquidity_ratio_excluding_vs_including_credit
        """
        issuer, payment, settled = self._setup_advanced_issuer(
            api, "officer-meridian", liquid_assets_cents=100000,
            unused_credit_lines_cents=10000)
        assert settled["status"] == "ADVANCED"
        assert settled["funding_source"] == "ADVANCE"
        issuer_after = get_issuer(issuer["id"])
        assert issuer_after["advance_obligation_cents"] == 2812500
        # floor(100000 * 10000 / 2812500) = 355
        assert issuer_after["liquidity_ratio_excluding_credit_bps"] == 355
        # floor(110000 * 10000 / 2812500) = 391
        assert issuer_after["liquidity_ratio_including_credit_bps"] == 391
        # The including ratio is strictly larger purely because its numerator
        # adds the unused credit lines; flooring each side means the gap need
        # not equal the floored credit-line term exactly.
        assert (
            issuer_after["liquidity_ratio_including_credit_bps"]
            > issuer_after["liquidity_ratio_excluding_credit_bps"]
        )

    def test_ratios_above_hard_floor_leave_issuer_active(self, api):
        """PRD §3.6: "If the excluding ratio is not null and falls strictly
        below three hundred basis points — a three-percent hard floor — an
        issuer in `ACTIVE` or `WATCH` moves to `SUSPENDED`, and its custodial
        accounts freeze `ACTIVE` to `FROZEN`. A ratio of exactly three hundred
        does not suspend."

        Design: Difficulty/dual_variant_calc/liquidity_ratio_excluding_vs_including_credit
        """
        issuer, payment, settled = self._setup_advanced_issuer(
            api, "officer-meridian2", liquid_assets_cents=100000,
            unused_credit_lines_cents=10000)
        issuer_after = get_issuer(issuer["id"])
        assert issuer_after["liquidity_ratio_excluding_credit_bps"] == 355
        assert issuer_after["status"] == "ACTIVE"


class TestAdvanceReimburseCascade:
    def _setup_suspended_issuer(self, api, officer_id):
        """Issuer driven to SUSPENDED by a 3750000-cent advance.

        Loan 600000000 cents, pool note 750 -> payment
        floor(600000000 * 750 / 10000 / 12) = 3750000. Liquid assets 100000
        cents -> ratio floor(100000 * 10000 / 3750000) = 266 < 300.
        """
        set_clock("2026-09-10T00:00:00Z")
        issuer, custodian, pool, _loans = setup_live_pool(
            officer_id,
            [dict(principal_balance_cents=600000000, note_rate_bps=850, government_insurance="FHA")],
            pool_overrides={"note_rate_bps": 750},
            liquid_assets_cents=100000,
        )
        account = create_account(issuer["id"], "P_AND_I")
        report = get_auto_report(pool["id"])
        assert report["scheduled_payment_cents"] == 3750000
        submit_report(issuer["id"], report["id"])
        accept_report(report["id"])
        payment = get_payment_for_report(report["id"])
        settled = validate_success(api.settle_payment(
            payment["id"], make_issuer_officer_headers(issuer["id"])))
        assert settled["status"] == "ADVANCED"
        advances = get_success_data(api.list_liquidity_advances(
            TEST_USERS["platform_admin_headers"], params={"issuer_id": issuer["id"]}))
        assert len(advances) == 1
        return issuer, account, payment, advances[0]

    def test_reimburse_unsuspends_issuer_and_thaws_accounts(self, api):
        """PRD §3.6: "when a reimbursement or financial update restores the
        excluding ratio to at least three hundred, a suspended issuer with no
        open or mitigating breach returns to `ACTIVE` and its accounts thaw
        `FROZEN` to `ACTIVE`"
        PRD §3.6: "Two ratios are computed against that obligation, both
        floored to integer basis points and both null whenever the obligation
        is zero."

        Design: Difficulty/transitive_cascade/advance_reimburse_ratio_issuer_unsuspend_cascade
        """
        issuer, account, payment, advance = self._setup_suspended_issuer(
            api, "officer-c2")
        issuer_mid = get_issuer(issuer["id"])
        assert issuer_mid["status"] == "SUSPENDED"
        # floor(100000 * 10000 / 3750000) = 266
        assert issuer_mid["liquidity_ratio_excluding_credit_bps"] == 266
        assert get_account(account["id"])["status"] == "FROZEN"
        reimbursed = validate_success(api.reimburse_advance(
            advance["id"], make_issuer_officer_headers(issuer["id"])))
        assert reimbursed["status"] == "REIMBURSED"
        issuer_after = get_issuer(issuer["id"])
        assert issuer_after["advance_obligation_cents"] == 0
        assert issuer_after["status"] == "ACTIVE"
        assert issuer_after["liquidity_ratio_excluding_credit_bps"] is None
        assert issuer_after["liquidity_ratio_including_credit_bps"] is None
        assert get_account(account["id"])["status"] == "ACTIVE"

    def test_suspension_freezes_accounts_and_settle_uses_advance_path(self, api):
        """PRD §3.6: "If the excluding ratio is not null and falls strictly
        below three hundred basis points — a three-percent hard floor — an
        issuer in `ACTIVE` or `WATCH` moves to `SUSPENDED`, and its custodial
        accounts freeze `ACTIVE` to `FROZEN`."
        PRD §3.6: "While `SUSPENDED`, pool assembly and activation, engagement
        creation, and custodial deposits and disbursements are blocked, but
        pass-through settlement continues — necessarily down the advance path,
        since the accounts are frozen."

        Design: Difficulty/transitive_cascade/advance_reimburse_ratio_issuer_unsuspend_cascade
        """
        issuer, account, payment, advance = self._setup_suspended_issuer(
            api, "officer-c2b")
        issuer_mid = get_issuer(issuer["id"])
        assert issuer_mid["status"] == "SUSPENDED"
        assert issuer_mid["advance_obligation_cents"] == 3750000
        assert get_account(account["id"])["status"] == "FROZEN"
        assert advance["status"] == "OPEN"
        assert advance["amount_cents"] == 3750000
        assert advance["payment_id"] == payment["id"]
