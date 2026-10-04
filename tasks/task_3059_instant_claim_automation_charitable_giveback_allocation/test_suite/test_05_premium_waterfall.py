"""Premium payments, the three-way waterfall, ledger shape, and cohort aggregates."""
from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    attach_treaty,
    create_active_treaty,
    create_cause_and_cohort,
    create_policyholder,
    create_quote,
    create_application,
    get_cohort,
    get_policy,
    list_ledger_entries,
    pay_premium,
    set_clock,
    setup_bound_policy,
    setup_state_fee,
    validate_error,
    validate_paginated,
    validate_success,
    bind_policy,
)

ADMIN = TEST_USERS["platform_admin_headers"]
UNDERWRITER = TEST_USERS["underwriting_admin_headers"]
FINANCE = TEST_USERS["finance_ops_headers"]


def _bind(state, premium, coverage=500000, **stack_kwargs):
    ctx = setup_bound_policy(state_code=state, premium_cents=premium,
                             coverage_amount_cents=coverage, **stack_kwargs)
    return ctx


class TestWaterfallVariants:
    def test_absolute_vs_pct_variants_diverge_on_identical_charge(self, api):
        """PRD §3.5: "when the filing's mode is ABSOLUTE_CENTS, the fee is the lesser of the config's flat_fee_cents and the charge — an absolute fee independent of the premium size, so two identically sized charges under different-mode states can yield different fees; when the mode is PCT_OF_PREMIUM, the fee is the charge multiplied by flat_fee_pct, rounded half-up to integer cents".

        Design: Difficulty/dual_variant_calc/fee_split_absolute_vs_pct_variants_diverge_on_identical_charge
        """
        set_clock()
        cause, cohort = create_cause_and_cohort(2026)
        setup_state_fee(
            state_code="TX", filing_mode="ABSOLUTE_CENTS",
            max_flat_fee_pct=0.30, max_flat_fee_cap_cents=25000,
            flat_fee_pct=0.30, flat_fee_cents=25000,
        )
        setup_state_fee(
            state_code="CA", filing_mode="PCT_OF_PREMIUM",
            max_flat_fee_pct=0.25, max_flat_fee_cap_cents=90000,
            flat_fee_pct=0.20, flat_fee_cents=90000,
        )
        ph_tx = create_policyholder(state_code="TX", email="tx@x.com")
        q_tx = create_quote(ph_tx["id"], 500000, 100000)
        app_tx = create_application(ph_tx["id"], q_tx["id"])
        pol_tx = bind_policy(ph_tx["id"], q_tx["id"], app_tx["id"])
        ph_ca = create_policyholder(state_code="CA", email="ca@x.com")
        q_ca = create_quote(ph_ca["id"], 500000, 100000)
        app_ca = create_application(ph_ca["id"], q_ca["id"])
        pol_ca = bind_policy(ph_ca["id"], q_ca["id"], app_ca["id"])

        pay_premium(pol_tx["id"], 100000)
        pay_premium(pol_ca["id"], 100000)

        assert any(
            e["kind"] == "FEE_RETAINED" and e["amount_cents"] == 25000
            for e in list_ledger_entries(pol_tx["id"])
        )
        assert any(
            e["kind"] == "FEE_RETAINED" and e["amount_cents"] == 20000
            for e in list_ledger_entries(pol_ca["id"])
        )
        cohort_after = get_cohort(cohort["id"])
        assert cohort_after["fee_retained_cents"] == 45000
        assert cohort_after["claims_pot_cents"] == 155000
        assert get_policy(pol_tx["id"])["premium_outstanding_cents"] == 0
        assert get_policy(pol_ca["id"])["premium_outstanding_cents"] == 0

    def test_absolute_variant_fee_equals_whole_small_charge(self, api):
        """PRD §3.5: "when the filing's mode is ABSOLUTE_CENTS, the fee is the lesser of the config's flat_fee_cents and the charge".

        Design: Difficulty/combinatorial_formula/fee_split_nested_conditional_min_fee_cap_branch
        """
        set_clock()
        cause, cohort = create_cause_and_cohort(2026)
        setup_state_fee(
            state_code="TX", filing_mode="ABSOLUTE_CENTS",
            max_flat_fee_pct=0.30, max_flat_fee_cap_cents=25000,
            flat_fee_pct=0.30, flat_fee_cents=25000,
        )
        ph_s = create_policyholder(state_code="TX", email="s@x.com")
        q_s = create_quote(ph_s["id"], 50000, 10000)
        app_s = create_application(ph_s["id"], q_s["id"])
        pol_s = bind_policy(ph_s["id"], q_s["id"], app_s["id"])
        pay_premium(pol_s["id"], 10000)
        entries = list_ledger_entries(pol_s["id"])
        fee = [e for e in entries if e["kind"] == "FEE_RETAINED"]
        assert len(fee) == 1 and fee[0]["amount_cents"] == 10000

    def test_absolute_variant_fee_capped_on_large_charge(self, api):
        """PRD §3.5: "when the filing's mode is ABSOLUTE_CENTS, the fee is the lesser of the config's flat_fee_cents and the charge".

        Design: Difficulty/combinatorial_formula/fee_split_nested_conditional_min_fee_cap_branch
        """
        set_clock()
        cause, cohort = create_cause_and_cohort(2026)
        setup_state_fee(
            state_code="TX", filing_mode="ABSOLUTE_CENTS",
            max_flat_fee_pct=0.30, max_flat_fee_cap_cents=25000,
            flat_fee_pct=0.30, flat_fee_cents=25000,
        )
        ph_b = create_policyholder(state_code="TX", email="b@x.com")
        q_b = create_quote(ph_b["id"], 900000, 100000)
        app_b = create_application(ph_b["id"], q_b["id"])
        pol_b = bind_policy(ph_b["id"], q_b["id"], app_b["id"])
        pay_premium(pol_b["id"], 100000)
        entries = list_ledger_entries(pol_b["id"])
        fee = [e for e in entries if e["kind"] == "FEE_RETAINED"]
        assert len(fee) == 1 and fee[0]["amount_cents"] == 25000
        cohort_after = get_cohort(cohort["id"])
        assert cohort_after["claims_pot_cents"] == 75000


    def test_fee_variant_chosen_by_filing_mode_not_config(self, api):
        """PRD §3.2: "Which of the two actually governs is decided by the referenced filing's filing_mode, not by the config."
        PRD §3.5: "when the filing's mode is ABSOLUTE_CENTS, the fee is the lesser of the config's flat_fee_cents and the charge — an absolute fee independent of the premium size".

        Design: Difficulty/dual_variant_calc/fee_split_absolute_vs_pct_variants_diverge_on_identical_charge
        """
        # Same charge size (100000) as the primary variant test, but the
        # observation is the pot side: ABSOLUTE 25000 fee → pot 75000, while
        # PCT 0.20 fee 20000 → pot 80000. Each policy sits in its own state
        # within the same cohort, so the cohort pot is the sum.
        set_clock()
        cause, cohort = create_cause_and_cohort(2026)
        setup_state_fee(
            state_code="TX", filing_mode="ABSOLUTE_CENTS",
            max_flat_fee_pct=0.30, max_flat_fee_cap_cents=25000,
            flat_fee_pct=0.30, flat_fee_cents=25000,
        )
        setup_state_fee(
            state_code="CA", filing_mode="PCT_OF_PREMIUM",
            max_flat_fee_pct=0.25, max_flat_fee_cap_cents=90000,
            flat_fee_pct=0.20, flat_fee_cents=90000,
        )
        pols = []
        for state, email in (("TX", "tx@x.com"), ("CA", "ca@x.com")):
            ph = create_policyholder(state_code=state, email=email)
            q = create_quote(ph["id"], 500000, 100000)
            app = create_application(ph["id"], q["id"])
            pols.append(bind_policy(ph["id"], q["id"], app["id"]))
        for pol in pols:
            pay_premium(pol["id"], 100000)
        cohort_after = get_cohort(cohort["id"])
        assert cohort_after["premium_pool_cents"] == 200000
        assert cohort_after["fee_retained_cents"] == 45000
        assert cohort_after["claims_pot_cents"] == 155000


class TestPerComponentRounding:
    def test_fee_and_cession_rounded_individually_before_subtraction(self, api):
        """PRD §3.5: "Rounding discipline is strict: the fee and the ceded amount are each rounded individually, half-up, to integer cents before any subtraction; the system never sums unrounded components and rounds the total."

        Design: Difficulty/combinatorial_formula/fee_split_per_component_rounding_order_pinned
        """
        ctx = setup_bound_policy(
            state_code="WA", premium_cents=9999, coverage_amount_cents=50000,
            filing_mode="PCT_OF_PREMIUM", max_flat_fee_pct=0.30,
            max_flat_fee_cap_cents=50000, flat_fee_pct=0.25, flat_fee_cents=50000,
            attach_treaty_quota=0.75,
        )
        pol = ctx["policy"]
        pay_premium(pol["id"], 9999)
        entries = list_ledger_entries(pol["id"])
        charge = [e for e in entries if e["kind"] == "PREMIUM_CHARGE"]
        fee = [e for e in entries if e["kind"] == "FEE_RETAINED"]
        ceded = [e for e in entries if e["kind"] == "REINSURANCE_CEDED"]
        assert charge[0]["amount_cents"] == 9999
        assert fee[0]["amount_cents"] == 2500  # round_half_up(9999 * 0.25)
        assert ceded[0]["amount_cents"] == 5624  # round_half_up(7499 * 0.75)
        cohort_after = get_cohort(ctx["cohort"]["id"])
        assert cohort_after["claims_pot_cents"] == 1875
        assert cohort_after["reinsurance_ceded_cents"] == 5624
        assert cohort_after["fee_retained_cents"] == 2500

    def test_charge_conserved_across_two_payments_without_drift(self, api):
        """PRD §3.5: "per-component rounding before subtraction is what makes the premium waterfall and the reinsurance cession reconcile exactly." (§2.5)
        PRD §3.5: "the cohort's premium_pool_cents, fee_retained_cents, reinsurance_ceded_cents, and claims_pot_cents are recomputed from the ledgers of all its policies."

        Design: Difficulty/compensating_invariant/premium_charge_conserves_charge_equals_fee_plus_ceded_plus_pot
        """
        ctx = setup_bound_policy(
            state_code="WA", premium_cents=9999, coverage_amount_cents=50000,
            filing_mode="PCT_OF_PREMIUM", max_flat_fee_pct=0.30,
            max_flat_fee_cap_cents=50000, flat_fee_pct=0.25, flat_fee_cents=50000,
            attach_treaty_quota=0.75,
        )
        pol = ctx["policy"]
        pay_premium(pol["id"], 5000)
        pay_premium(pol["id"], 4999)
        entries = list_ledger_entries(pol["id"])
        charges = [e for e in entries if e["kind"] == "PREMIUM_CHARGE"]
        fees = [e for e in entries if e["kind"] == "FEE_RETAINED"]
        cededs = [e for e in entries if e["kind"] == "REINSURANCE_CEDED"]
        # Payment 1: charge 5000 → fee 1250, ceded round_half_up(3750*0.75)=2813, pot 937.
        # Payment 2: charge 4999 → fee 1250, ceded round_half_up(3749*0.75)=2812, pot 937.
        assert sorted(e["amount_cents"] for e in charges) == [4999, 5000]
        assert sorted(e["amount_cents"] for e in fees) == [1250, 1250]
        assert sorted(e["amount_cents"] for e in cededs) == [2812, 2813]
        for c, f, d in zip([5000, 4999], [1250, 1250], [2813, 2812]):
            assert c == f + d + (c - f - d)  # per-payment conservation by construction
        cohort_after = get_cohort(ctx["cohort"]["id"])
        assert cohort_after["premium_pool_cents"] == 9999
        assert cohort_after["premium_pool_cents"] == (
            cohort_after["fee_retained_cents"]
            + cohort_after["reinsurance_ceded_cents"]
            + cohort_after["claims_pot_cents"]
        )
        assert get_policy(pol["id"])["premium_outstanding_cents"] == 0


    def test_cession_computed_on_post_fee_remainder(self, api):
        """PRD §3.5: "Second, when the policy's cohort has an ACTIVE treaty attached, the ceded amount is the post-fee remainder — the charge minus the fee — multiplied by the treaty's quota_share_pct, rounded half-up to integer cents".

        Design: Difficulty/combinatorial_formula/fee_split_per_component_rounding_order_pinned
        """
        # A round charge (10000) with the same 0.25/0.75 parameters: fee 2500,
        # ceded on the post-fee remainder 7500 -> 5625; ceding on the gross
        # charge instead would have produced 7500.
        ctx = setup_bound_policy(
            state_code="WA", premium_cents=10000, coverage_amount_cents=50000,
            filing_mode="PCT_OF_PREMIUM", max_flat_fee_pct=0.30,
            max_flat_fee_cap_cents=50000, flat_fee_pct=0.25, flat_fee_cents=50000,
            attach_treaty_quota=0.75,
        )
        pol = ctx["policy"]
        pay_premium(pol["id"], 10000)
        entries = list_ledger_entries(pol["id"])
        by_kind = {e["kind"]: e["amount_cents"] for e in entries}
        assert by_kind["FEE_RETAINED"] == 2500
        assert by_kind["REINSURANCE_CEDED"] == 5625
        cohort_after = get_cohort(ctx["cohort"]["id"])
        assert cohort_after["claims_pot_cents"] == 1875


class TestCohortAggregates:
    def test_cohort_get_recomputes_aggregates_from_ledger(self, api):
        """PRD §3.3: "the derived claims_pot_cents, which always equals the premium pool minus the retained fee minus the ceded reinsurance and is kept in sync on every ledger mutation."
        PRD §3.5: "the cohort's premium_pool_cents, fee_retained_cents, reinsurance_ceded_cents, and claims_pot_cents are recomputed from the ledgers of all its policies."

        Design: Corner/entities/cohort_get_recomputes_aggregates_from_ledger
        """
        ctx = _bind("TX", 100000)
        pay_premium(ctx["policy"]["id"], 100000)
        cohort = get_cohort(ctx["cohort"]["id"])
        assert cohort["premium_pool_cents"] == 100000
        assert cohort["fee_retained_cents"] == 20000
        assert cohort["reinsurance_ceded_cents"] == 0
        assert cohort["claims_pot_cents"] == 80000
        assert cohort["giveback_actual_cents"] == 80000
        assert cohort["giveback_projected_cents"] == 80000

    def test_incremental_payments_reconcile_to_same_aggregates(self, api):
        """PRD §3.5: "the cohort's premium_pool_cents, fee_retained_cents, reinsurance_ceded_cents, and claims_pot_cents are recomputed from the ledgers of all its policies."
        PRD §3.5: "the policy's premium_paid_cents advances by the charge, premium_outstanding_cents falls to the annual premium minus the paid-to-date (floored at zero — it equals the full annual premium at bind and never goes negative)".

        Design: Corner/cross_cutting_layers/derived_fields_reconciled_on_every_premium_mutation
        """
        ctx = _bind("TX", 100000)
        pay_premium(ctx["policy"]["id"], 60000)
        pay_premium(ctx["policy"]["id"], 40000)
        cohort = get_cohort(ctx["cohort"]["id"])
        assert cohort["premium_pool_cents"] == 100000
        assert cohort["fee_retained_cents"] == 20000
        assert cohort["claims_pot_cents"] == 80000
        policy = get_policy(ctx["policy"]["id"])
        assert policy["premium_paid_cents"] == 100000
        assert policy["premium_outstanding_cents"] == 0


    def test_per_payment_charge_equals_fee_plus_ceded_plus_pot(self, api):
        """PRD §2.5: "per-component rounding before subtraction is what makes the premium waterfall and the reinsurance cession reconcile exactly."
        PRD §3.5: "Third, whatever remains of the charge after fee and cession is the claims-pot increment."

        Design: Difficulty/compensating_invariant/premium_charge_conserves_charge_equals_fee_plus_ceded_plus_pot
        """
        # First payment of the two-payment scenario, observed on its own:
        # charge 5000 → fee round_half_up(5000*0.25)=1250, ceded
        # round_half_up(3750*0.75)=2813, pot increment 937.
        ctx = setup_bound_policy(
            state_code="WA", premium_cents=9999, coverage_amount_cents=50000,
            filing_mode="PCT_OF_PREMIUM", max_flat_fee_pct=0.30,
            max_flat_fee_cap_cents=50000, flat_fee_pct=0.25, flat_fee_cents=50000,
            attach_treaty_quota=0.75,
        )
        pol = ctx["policy"]
        pay_premium(pol["id"], 5000)
        entries = list_ledger_entries(pol["id"])
        by_kind = {e["kind"]: e["amount_cents"] for e in entries}
        assert by_kind["PREMIUM_CHARGE"] == 5000
        assert by_kind["FEE_RETAINED"] == 1250
        assert by_kind["REINSURANCE_CEDED"] == 2813
        cohort_after = get_cohort(ctx["cohort"]["id"])
        assert cohort_after["claims_pot_cents"] == 937
        assert 5000 == 1250 + 2813 + 937


class TestLedgerShape:
    def test_policy_ledger_lists_three_entries_per_payment(self, api):
        """PRD §3.5: "Each payment appends three entries to the policy's ledger: a PREMIUM_CHARGE entry for the full charge, a FEE_RETAINED entry for the fee, and a REINSURANCE_CEDED entry for the ceded amount."
        PRD §2.3: "policy ledger entries by kind".

        Design: Corner/endpoints/policy_ledger_lists_three_entries_per_payment
        """
        ctx = _bind("TX", 100000, attach_treaty_quota=0.75)
        pay_premium(ctx["policy"]["id"], 100000)
        entries, meta = validate_paginated(
            api.list_policy_ledger(ctx["policy"]["id"], FINANCE)
        )
        assert len(entries) == 3
        by_kind = {e["kind"]: e["amount_cents"] for e in entries}
        assert by_kind["PREMIUM_CHARGE"] == 100000
        assert by_kind["FEE_RETAINED"] == 20000
        assert by_kind["REINSURANCE_CEDED"] == 60000
        filtered, fmeta = validate_paginated(
            api.list_policy_ledger(ctx["policy"]["id"], FINANCE, params={"kind": "FEE_RETAINED"})
        )
        assert len(filtered) == 1 and filtered[0]["amount_cents"] == 20000


class TestPremiumPaymentErrors:
    def test_payment_after_full_payment_rejected(self, api):
        """PRD §3.5: "when premium_outstanding_cents has already reached zero, further payments are rejected with ERR_PREMIUM_ALREADY_PAID."

        Design: Corner/validations/premium_payment_after_full_payment_rejected
        """
        ctx = _bind("TX", 50000)
        pay_premium(ctx["policy"]["id"], 50000)
        resp = api.pay_premium(ctx["policy"]["id"], {"amount_cents": 1}, FINANCE)
        validate_error(resp, ApiErrorId.ERR_PREMIUM_ALREADY_PAID)
        assert get_policy(ctx["policy"]["id"])["premium_paid_cents"] == 50000

    def test_payment_on_cancelled_policy_appends_no_ledger_rows(self, api):
        """PRD §3.5: "The policy must be ACTIVE — operations against a lapsed or cancelled policy are rejected with ERR_POLICY_NOT_ACTIVE".
        PRD §3.5: "Each payment appends three entries to the policy's ledger" — a rejected payment appends none.

        Design: Difficulty/priority_pair_validation_conflict/state_check_beats_fiscal_check_on_second_premium_payment
        """
        from test_helpers import make_policyholder_headers
        ctx = setup_bound_policy(state_code="GA", premium_cents=50000)
        pay_premium(ctx["policy"]["id"], 50000)
        before = list_ledger_entries(ctx["policy"]["id"])
        validate_success(
            api.cancel_policy(
                ctx["policy"]["id"],
                make_policyholder_headers(ctx["policyholder"]["id"]),
            )
        )
        resp = api.pay_premium(ctx["policy"]["id"], {"amount_cents": 1000}, FINANCE)
        validate_error(resp, ApiErrorId.ERR_POLICY_NOT_ACTIVE)
        after = list_ledger_entries(ctx["policy"]["id"])
        assert len(after) == len(before)
        cohort = get_cohort(ctx["cohort"]["id"])
        assert cohort["premium_pool_cents"] == 50000

    def test_payment_on_cancelled_policy_reports_policy_not_active(self, api):
        """PRD §3.5: "The policy must be ACTIVE — operations against a lapsed or cancelled policy are rejected with ERR_POLICY_NOT_ACTIVE — and there must be something left to pay: when premium_outstanding_cents has already reached zero, further payments are rejected with ERR_PREMIUM_ALREADY_PAID."
        PRD §2.8: "the generic state guard (ERR_INVALID_STATE, HTTP 409) follows them, then optimistic-concurrency staleness, then the business rules described throughout §3."
        (Setup uses cancellation rather than lapse: a fully-paid policy has nothing to lapse for, so only the cancel path can hold policy-inactive and fully-paid true at once.)

        Design: Difficulty/priority_pair_validation_conflict/state_check_beats_fiscal_check_on_second_premium_payment
        """
        from test_helpers import make_policyholder_headers
        ctx = setup_bound_policy(state_code="GA", premium_cents=50000)
        pay_premium(ctx["policy"]["id"], 50000)  # outstanding 0
        validate_success(
            api.cancel_policy(
                ctx["policy"]["id"],
                make_policyholder_headers(ctx["policyholder"]["id"]),
            )
        )
        resp = api.pay_premium(ctx["policy"]["id"], {"amount_cents": 1000}, FINANCE)
        validate_error(resp, ApiErrorId.ERR_POLICY_NOT_ACTIVE)
        assert get_policy(ctx["policy"]["id"])["premium_paid_cents"] == 50000
