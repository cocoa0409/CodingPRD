"""Skimming claims: filing gates (amount, window, case ownership), the
investigation/adjudication role and SoD gates, provisional and final credits,
purse freeze/unfreeze, and the retailer-integrity cascade."""
from test_helpers import (
    ApiErrorId,
    CSR_USER_A,
    CSR_USER_B,
    TEST_USERS,
    make_cardholder_headers,
    make_cardholder_services_headers,
    make_retailer_system_headers,
    validate_error,
    validate_success,
)
from test_helpers import assertions as A
from test_helpers import factories as f
from test_helpers import fixtures as fx

ADMIN = TEST_USERS["state_admin_headers"]


def _two_cases_with_b_purchase(api):
    """Contract/retailer + cases A (card, no txns) and B (active card, one
    500-cent purchase on 2026-09-02). Returns (ctx, card_a, txn_b)."""
    ctx = fx.setup_active_contract(api)
    fx.add_retailer(api, ctx)
    fx.add_case(api, ctx, case_identifier="0000000000")
    fx.add_case(api, ctx, case_identifier="0000000001", key="case_b")
    fx.fund_case(api, ctx)  # 30000 FOOD for both cases
    card_a = fx.issue_card(api, ctx.case["id"])
    card_b = fx.issue_card(api, ctx.case_b["id"])
    fx.set_clock(api, "2026-09-02T12:00:00Z")  # both cards mailed (issued 09-01)
    fx.activate_card(api, card_b["id"], ctx.case_b["id"])
    txn_b = fx.place_purchase(api, ctx.retailer["id"], card_b["id"],
                              items=[f.purchase_item(unit_price_cents=500)])
    return ctx, card_a, txn_b


class TestClaimFilingGates:
    def test_claim_amount_exceeds_referenced_total(self, api):
        """PRD §3.8: "The `claimed_amount_cents` must not exceed the sum of the
        referenced transactions' `total_cents`, else
        `ERR_CLAIM_AMOUNT_EXCEEDS_REFERENCED`."

        Design: Corner/validations/claim_amount_exceeds_referenced_total
        """
        ctx = fx.setup_pos_ready(api)
        txn = fx.place_purchases(api, ctx, [{"unit_price_cents": 500}])[0]
        resp = api.file_claim(
            f.claim_payload(ctx.case["id"], ctx.card["id"], [txn["id"]], 600,
                            incident_description="over-claim", freeze_purse=False),
            make_cardholder_headers(ctx.case["id"]),
        )
        validate_error(resp, ApiErrorId.ERR_CLAIM_AMOUNT_EXCEEDS_REFERENCED)

    def test_claim_mismatch_alone_returns_case_mismatch(self, api):
        """PRD §3.8: "Every referenced transaction must exist
        (`ERR_REFERENCE_NOT_FOUND`), must belong to the filing case
        (`ERR_CLAIM_TXN_CASE_MISMATCH`), and must be recent: each referenced
        transaction's `created_at` must lie within the contract's
        `claim_window_days` (60 days by default) of the current clock, else the
        filing is rejected with `ERR_CLAIM_WINDOW_EXPIRED`."

        Design: Corner/validations/claim_mismatch_alone_returns_case_mismatch
        """
        ctx, card_a, txn_b = _two_cases_with_b_purchase(api)
        # Same-day filing: only the case-ownership check can fail.
        resp = api.file_claim(
            f.claim_payload(ctx.case["id"], card_a["id"], [txn_b["id"]], 500,
                            incident_description="not my txn", freeze_purse=False),
            make_cardholder_headers(ctx.case["id"]),
        )
        validate_error(resp, ApiErrorId.ERR_CLAIM_TXN_CASE_MISMATCH)

    def test_claim_window_expired_beats_txn_case_mismatch(self, api):
        """PRD §2.8: "Incoming requests are validated against an ordered
        pipeline, and when several checks would fail at once, the earliest check
        in this order determines the error returned."
        PRD §2.8: "21. Temporal windows: `ERR_VOID_WINDOW_EXPIRED`,
        `ERR_CLAIM_WINDOW_EXPIRED`, `ERR_DISPUTE_WINDOW_EXPIRED`, and
        `ERR_POSTING_MONTH_INVALID`."
        PRD §2.8: "22. Cross-reference rules: `ERR_CLAIM_TXN_CASE_MISMATCH` and
        `ERR_DUPLICATE_POSTING_RUN`."

        Design: Difficulty/priority_pair_validation_conflict/claim_window_expired_beats_txn_case_mismatch
        """
        ctx, card_a, txn_b = _two_cases_with_b_purchase(api)
        # 2026-11-15: the referenced transaction is ~73 days old (window 60)
        # AND belongs to case B — the temporal check (21) fires first.
        fx.set_clock(api, "2026-11-15T00:00:00Z")
        resp = api.file_claim(
            f.claim_payload(ctx.case["id"], card_a["id"], [txn_b["id"]], 500,
                            incident_description="not mine but old",
                            freeze_purse=False),
            make_cardholder_headers(ctx.case["id"]),
        )
        validate_error(resp, ApiErrorId.ERR_CLAIM_WINDOW_EXPIRED)

    def test_claim_window_expired_for_own_old_transaction(self, api):
        """PRD §3.8: "Every referenced transaction must exist
        (`ERR_REFERENCE_NOT_FOUND`), must belong to the filing case
        (`ERR_CLAIM_TXN_CASE_MISMATCH`), and must be recent: each referenced
        transaction's `created_at` must lie within the contract's
        `claim_window_days` (60 days by default) of the current clock, else the
        filing is rejected with `ERR_CLAIM_WINDOW_EXPIRED`."

        Design: Difficulty/priority_pair_validation_conflict/claim_window_expired_beats_txn_case_mismatch
        """
        ctx = fx.setup_pos_ready(api)
        txn = fx.place_purchases(api, ctx, [{"unit_price_cents": 500}])[0]
        # The case's own transaction, but ~73 days old: the temporal rule alone.
        fx.set_clock(api, "2026-11-15T00:00:00Z")
        resp = api.file_claim(
            f.claim_payload(ctx.case["id"], ctx.card["id"], [txn["id"]], 500,
                            incident_description="my txn, too old",
                            freeze_purse=False),
            make_cardholder_headers(ctx.case["id"]),
        )
        validate_error(resp, ApiErrorId.ERR_CLAIM_WINDOW_EXPIRED)


class TestClaimLifecycleGates:
    def test_adjudicate_claim_before_investigation_rejected(self, api):
        """PRD §3.8: "Adjudication belongs to `StateAdmin` alone and proceeds
        from `UNDER_INVESTIGATION`."
        PRD §2.8: "7. Generic transition legality: the target resource is in a
        from-state the requested transition allows, else `ERR_INVALID_STATE`;
        terminal resources reject all further transitions this way."

        Design: Corner/state_machines/adjudicate_claim_before_investigation_rejected
        """
        ctx = fx.setup_purchase_and_claim(api)  # claim FILED
        resp = api.set_claim_status(
            ctx.claim["id"],
            f.claim_status_payload("SUBSTANTIATED", substantiated_amount_cents=500),
            ADMIN,
        )
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE)

    def test_csr_cannot_adjudicate_claim(self, api):
        """PRD §3.8: "Adjudication belongs to `StateAdmin` alone and proceeds
        from `UNDER_INVESTIGATION`."
        PRD §2.1: "A request whose role is not among the roles authorized for
        the endpoint is rejected with `ERR_FORBIDDEN`."

        Design: Corner/rbac/csr_cannot_adjudicate_claim
        """
        ctx = fx.setup_purchase_and_claim(api)
        fx.investigate_claim(api, ctx.claim["id"])  # UNDER_INVESTIGATION
        resp = api.set_claim_status(
            ctx.claim["id"],
            f.claim_status_payload("SUBSTANTIATED", substantiated_amount_cents=500),
            make_cardholder_services_headers(CSR_USER_A),
        )
        validate_error(resp, ApiErrorId.ERR_FORBIDDEN)

    def test_filer_csr_cannot_investigate_same_claim(self, api):
        """PRD §3.8: "Segregation of duties applies at exactly this step: when
        the claim's `filed_by_role` is `CardholderServices`, the acting
        representative's `X-User-ID` must differ from the claim's
        `filed_by_user_id`, and a filer attempting to move their own claim into
        investigation is rejected with `ERR_SOD_VIOLATION`."

        Design: Corner/rbac/filer_csr_cannot_investigate_same_claim
        """
        ctx = fx.setup_purchase_and_claim(api, filer="csr",
                                          csr_user_id=CSR_USER_A)
        # The filer csr-a is blocked from investigating their own claim.
        resp = api.set_claim_status(
            ctx.claim["id"], f.claim_status_payload("UNDER_INVESTIGATION"),
            make_cardholder_services_headers(CSR_USER_A),
        )
        validate_error(resp, ApiErrorId.ERR_SOD_VIOLATION)
        # A different CSR may investigate.
        resp2 = api.set_claim_status(
            ctx.claim["id"], f.claim_status_payload("UNDER_INVESTIGATION"),
            make_cardholder_services_headers(CSR_USER_B),
        )
        data = validate_success(resp2, 200)
        assert data["investigation_status"] == "UNDER_INVESTIGATION"


class TestClaimCredits:
    def test_claim_parallel_investigation_and_credit_dimensions(self, api):
        """PRD §3.8: "If the claim is still under investigation when the current
        clock reaches or passes `investigated_at` plus the contract's
        `provisional_credit_delay_days` (10 days by default) — an inclusive
        boundary — the provisional-credit sweep (step 5 of the clock pipeline)
        auto-issues credit: a `PROVISIONAL_CREDIT` of the smaller of
        `claimed_amount_cents` and the contract's `provisional_credit_cap_cents`
        (50000 cents by default) posts to the claim's target purse,
        `provisional_credit_cents` and `provisional_credited_at` are set, and
        `credit_status` moves from `NONE` to `PROVISIONAL`."
        PRD §3.8: "The target purse is chosen deterministically from the
        referenced transactions: the system sums their `food_charge_cents` and
        their `cash_charge_cents`, and the target is the case's cash purse when
        the cash sum is at least the food sum, otherwise the case's food purse."
        PRD §3.8: "when the provisional exceeds the final, a
        `CLAIM_REVERSAL_DEBIT` of the difference posts"

        Design: Difficulty/non_linear_state_machine/claim_parallel_investigation_and_credit_dimensions
        """
        ctx = fx.setup_pos_ready(
            api, program_types=("FOOD", "CASH"),
            allotments={"FOOD": 30000, "CASH": 40000},
            item_entries=[
                f.item_entry(),
                f.item_entry(upc=f.DEFAULTS["NON_FOOD_UPC"], food_eligible=False),
            ])
        txn = fx.place_purchase(
            api, ctx.retailer["id"], ctx.card["id"],
            items=[f.purchase_item(unit_price_cents=30000),
                   f.purchase_item(upc=f.DEFAULTS["NON_FOOD_UPC"],
                                   unit_price_cents=30000)])
        assert txn["food_charge_cents"] == 30000 and txn["cash_charge_cents"] == 30000
        fx.set_clock(api, "2026-09-02T13:00:00Z")
        claim = fx.file_claim_on(api, ctx, txn, 60000, freeze_purse=True,
                                 incident_description="skimmed at pump")
        fx.set_clock(api, "2026-09-05T12:00:00Z")
        fx.investigate_claim(api, claim["id"])  # investigated_at 2026-09-05T12:00Z

        # One second before investigated_at + 10 days: no provisional credit.
        fx.set_clock(api, "2026-09-15T11:59:59Z")
        pre = fx.list_case_claims(api, ctx.case["id"])[0]
        assert pre["investigation_status"] == "UNDER_INVESTIGATION"
        assert pre["credit_status"] == "NONE"

        # At the inclusive boundary the credit dimension moves independently.
        fx.set_clock(api, "2026-09-15T12:00:00Z")
        mid = fx.list_case_claims(api, ctx.case["id"])[0]
        assert mid["investigation_status"] == "UNDER_INVESTIGATION"
        assert mid["credit_status"] == "PROVISIONAL"
        assert mid["provisional_credit_cents"] == 50000  # min(60000, cap 50000)
        # cash_sum 30000 >= food_sum 30000 -> target is the CASH purse:
        # 40000 - 30000 + 50000 = 60000.
        cash = fx.get_purse(api, ctx.purses["CASH"]["id"])
        A.assert_purse_balances(cash, ledger_balance_cents=60000)

        # Adjudication below the provisional posts the negative delta.
        result = fx.adjudicate_claim(api, claim["id"], to="SUBSTANTIATED",
                                     substantiated_amount_cents=45000)
        assert result["investigation_status"] == "SUBSTANTIATED"
        assert result["credit_status"] == "FINAL"
        cash = fx.get_purse(api, ctx.purses["CASH"]["id"])
        A.assert_purse_balances(cash, ledger_balance_cents=55000)  # -5000 reversal

    def test_adjudication_before_provisional_posts_full_final_credit(self, api):
        """PRD §3.8: "The system then settles the delta against any provisional
        credit already on the target purse: when the final credit exceeds the
        provisional, a `CLAIM_CREDIT` of the difference posts; when the
        provisional exceeds the final, a `CLAIM_REVERSAL_DEBIT` of the
        difference posts; when they are equal, no entry posts; and when no
        provisional exists, the full final credit posts as a `CLAIM_CREDIT`."
        PRD §3.8: "The claim's `credit_status` becomes `FINAL`."

        Design: Difficulty/non_linear_state_machine/claim_parallel_investigation_and_credit_dimensions
        """
        ctx = fx.setup_purchase_and_claim(api, purchase_price_cents=500,
                                          freeze_purse=False)
        fx.investigate_claim(api, ctx.claim["id"])
        # Adjudicate long before the 10-day provisional-credit delay elapses.
        result = fx.adjudicate_claim(api, ctx.claim["id"], to="SUBSTANTIATED",
                                     substantiated_amount_cents=500)
        assert result["credit_status"] == "FINAL"
        assert result["provisional_credit_cents"] == 0
        # Target is the FOOD purse (food_sum 500 > cash_sum 0):
        # 30000 - 500 + 500 = 30000 restored.
        food = fx.get_purse(api, ctx.purses["FOOD"]["id"])
        A.assert_purse_balances(food, ledger_balance_cents=30000)
        credits = fx.list_ledger(api, food["id"], entry_type="CLAIM_CREDIT")
        assert [e["amount_cents"] for e in credits] == [500]

    def test_unsubstantiated_claim_reverses_provisional_credit(self, api):
        """PRD §3.8: "A finding of `UNSUBSTANTIATED` posts nothing when no
        provisional credit exists — `credit_status` simply stays `NONE` — and
        posts a `PROVISIONAL_REVERSAL_DEBIT` of the full
        `provisional_credit_cents` with `credit_status` moving to `REVERSED`
        when one does."
        PRD §3.8: "Either decision stamps `decided_by_user_id` and `decided_at`,
        and every purse the claim froze flips from `FROZEN` back to `OPEN`,
        provided the purse's case is not `CLOSED`."
        PRD §3.8: "A `FROZEN` purse rejects purchase, withdrawal, and fee debits
        with `ERR_PURSE_FROZEN`, while credits — posting, void, provisional, and
        claim credits — and expunge and expiry debits still apply to it."

        Design: Corner/cross_cutting_layers/unsubstantiated_claim_reverses_provisional_credit
        """
        ctx = fx.setup_purchase_and_claim(api, purchase_price_cents=300,
                                          freeze_purse=True)
        fx.set_clock(api, "2026-09-02T12:30:00Z")
        fx.investigate_claim(api, ctx.claim["id"])  # investigated_at 12:30
        # At investigated_at + 10 days (inclusive): provisional credit 300.
        fx.set_clock(api, "2026-09-12T12:30:00Z")
        food_id = ctx.purses["FOOD"]["id"]
        purse = fx.get_purse(api, food_id)
        # Credits still apply to the FROZEN purse: 30000 - 300 + 300 = 30000.
        A.assert_purse_balances(purse, ledger_balance_cents=30000)
        assert purse["purse_status"] == "FROZEN"
        claim = fx.list_case_claims(api, ctx.case["id"])[0]
        assert claim["credit_status"] == "PROVISIONAL"
        assert claim["provisional_credit_cents"] == 300

        result = fx.adjudicate_claim(api, claim["id"], to="UNSUBSTANTIATED")
        assert result["investigation_status"] == "UNSUBSTANTIATED"
        assert result["credit_status"] == "REVERSED"
        purse = fx.get_purse(api, food_id)
        # The reversal restores exactly the pre-claim 29700.
        A.assert_purse_balances(purse, ledger_balance_cents=29700)
        assert purse["purse_status"] == "OPEN"
        reversals = fx.list_ledger(api, food_id,
                                   entry_type="PROVISIONAL_REVERSAL_DEBIT")
        assert [e["amount_cents"] for e in reversals] == [300]


class TestClaimCascades:
    @staticmethod
    def _substantiated_round(api, ctx):
        """One round of: 100-cent purchase -> cardholder claim (no freeze) ->
        CSR investigation -> StateAdmin substantiation at 100."""
        txn = fx.place_purchases(api, ctx, [{"unit_price_cents": 100}])[0]
        claim = fx.file_claim_on(api, ctx, txn, 100, freeze_purse=False,
                                 incident_description="skim round")
        fx.investigate_claim(api, claim["id"])
        fx.adjudicate_claim(api, claim["id"], to="SUBSTANTIATED",
                            substantiated_amount_cents=100)

    def test_third_substantiated_claim_suspends_retailer(self, api):
        """PRD §3.8: "Substantiation also feeds the retailer-integrity cascade:
        for each distinct retailer among the referenced transactions, the
        retailer's `skimming_incident_count` increases by 1, and any retailer
        whose count reaches the contract's `skimming_suspend_threshold` (3
        lifetime incidents by default) flips automatically from `APPROVED` to
        `SUSPENDED`, with the consequences of Section 3.2."
        PRD §3.2: "A `SUSPENDED` retailer rejects new authorizations and
        item-file uploads with `ERR_RETAILER_NOT_ACTIVE`, while its existing
        transactions and settlement batches are unaffected."

        Design: Difficulty/transitive_cascade/substantiated_claim_retailer_threshold_suspension_chain
        """
        ctx = fx.setup_pos_ready(api)  # default threshold 3
        for _ in range(3):
            self._substantiated_round(api, ctx)
        retailer = fx.get_retailer(api, ctx.retailer["id"])
        assert retailer["skimming_incident_count"] == 3
        assert retailer["retailer_status"] == "SUSPENDED"
        # The cascade's consequence: new authorizations are refused.
        resp = api.create_authorization(
            ctx.retailer["id"],
            f.purchase_payload(ctx.card["id"],
                               items=[f.purchase_item(unit_price_cents=100)]),
            make_retailer_system_headers(ctx.retailer["id"]),
        )
        validate_error(resp, ApiErrorId.ERR_RETAILER_NOT_ACTIVE)

    def test_two_substantiated_claims_leave_retailer_approved(self, api):
        """PRD §3.8: "Substantiation also feeds the retailer-integrity cascade:
        for each distinct retailer among the referenced transactions, the
        retailer's `skimming_incident_count` increases by 1, and any retailer
        whose count reaches the contract's `skimming_suspend_threshold` (3
        lifetime incidents by default) flips automatically from `APPROVED` to
        `SUSPENDED`, with the consequences of Section 3.2."

        Design: Difficulty/transitive_cascade/substantiated_claim_retailer_threshold_suspension_chain
        """
        ctx = fx.setup_pos_ready(api)
        for _ in range(2):  # one below the threshold of 3
            self._substantiated_round(api, ctx)
        retailer = fx.get_retailer(api, ctx.retailer["id"])
        assert retailer["skimming_incident_count"] == 2
        assert retailer["retailer_status"] == "APPROVED"
        txn = fx.place_purchases(api, ctx, [{"unit_price_cents": 100}])[0]
        assert txn["total_cents"] == 100

    def test_frozen_purse_beats_insufficient_funds(self, api):
        """PRD §2.8: "A state rejection always beats a fiscal one: a debit that
        would hit a `FROZEN` purse surfaces `ERR_PURSE_FROZEN` even when that
        purse also lacks funds."
        PRD §3.8: "A `FROZEN` purse rejects purchase, withdrawal, and fee debits
        with `ERR_PURSE_FROZEN`, while credits — posting, void, provisional, and
        claim credits — and expunge and expiry debits still apply to it."

        Design: Difficulty/priority_pair_validation_conflict/frozen_purse_beats_insufficient_funds
        """
        ctx = fx.setup_pos_ready(api, program_types=("FOOD", "CASH"),
                                 allotments={"FOOD": 2000, "CASH": 20000})
        txn = fx.place_purchases(api, ctx, [{"unit_price_cents": 100}])[0]
        fx.file_claim_on(api, ctx, txn, 100, freeze_purse=True,
                         incident_description="freeze me")
        # The food purse is FROZEN and its 1900 spendable is below the 2500
        # charge: both rules are violated; the state error wins.
        resp = api.create_authorization(
            ctx.retailer["id"],
            f.purchase_payload(ctx.card["id"],
                               items=[f.purchase_item(unit_price_cents=2500)]),
            make_retailer_system_headers(ctx.retailer["id"]),
        )
        validate_error(resp, ApiErrorId.ERR_PURSE_FROZEN)
        purse = fx.get_purse(api, ctx.purses["FOOD"]["id"])
        assert purse["purse_status"] == "FROZEN"
        A.assert_purse_balances(purse, spendable_balance_cents=1900)

    def test_frozen_purse_rejects_even_sufficient_purchase(self, api):
        """PRD §3.8: "A `FROZEN` purse rejects purchase, withdrawal, and fee
        debits with `ERR_PURSE_FROZEN`, while credits — posting, void,
        provisional, and claim credits — and expunge and expiry debits still
        apply to it."
        PRD §3.8: "When `freeze_purse` is true, every purse the referenced
        transactions charged flips from `OPEN` to `FROZEN` at filing."

        Design: Difficulty/priority_pair_validation_conflict/frozen_purse_beats_insufficient_funds
        """
        ctx = fx.setup_pos_ready(api)  # FOOD purse at 30000
        txn = fx.place_purchases(api, ctx, [{"unit_price_cents": 100}])[0]
        fx.file_claim_on(api, ctx, txn, 100, freeze_purse=True)
        # Funds are ample (29900 spendable vs 100 charge); the freeze alone
        # rejects the debit.
        resp = api.create_authorization(
            ctx.retailer["id"],
            f.purchase_payload(ctx.card["id"],
                               items=[f.purchase_item(unit_price_cents=100)]),
            make_retailer_system_headers(ctx.retailer["id"]),
        )
        validate_error(resp, ApiErrorId.ERR_PURSE_FROZEN)
        purse = fx.get_purse(api, ctx.purses["FOOD"]["id"])
        assert purse["purse_status"] == "FROZEN"
        A.assert_purse_balances(purse, spendable_balance_cents=29900)

    def test_case_close_with_open_claim_rejected(self, api):
        """PRD §2.8: "And on case closure, the open-claims check (step 17) fires
        before the zero-balance check (step 23), so a case with both problems
        reports `ERR_CASE_HAS_OPEN_CLAIMS`."
        PRD §3.10: "Two preconditions apply, in the pipeline order of Section
        2.8: first, no skimming claim of the case may be in `FILED` or
        `UNDER_INVESTIGATION`, else `ERR_CASE_HAS_OPEN_CLAIMS`; second, every
        purse of the case must have a `ledger_balance_cents` of zero, else
        `ERR_CASE_BALANCE_NONZERO`"

        Design: Corner/validations/case_close_with_open_claim_rejected
        """
        ctx = fx.setup_purchase_and_claim(api)  # FILED claim; purse nonzero too
        version = fx.get_case(api, ctx.case["id"])["version"]
        resp = api.set_case_status(
            ctx.case["id"],
            f.case_status_payload("CLOSED", expected_case_account_version=version),
            ADMIN,
        )
        validate_error(resp, ApiErrorId.ERR_CASE_HAS_OPEN_CLAIMS)
