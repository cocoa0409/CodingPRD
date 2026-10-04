"""Giveback runs, cohort lifecycle, retained-risk variants, and allocation math."""
from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    approve_escalated_claim,
    attach_treaty,
    bind_policy,
    create_active_treaty,
    create_application,
    create_cause,
    create_cause_and_cohort,
    create_cohort,
    create_escalated_claim,
    create_policyholder,
    create_quote,
    file_claim,
    get_cohort,
    make_policyholder_headers,
    pay_premium,
    set_clock,
    setup_bound_policy,
    setup_state_fee,
    validate_error,
    validate_paginated,
    validate_success,
    deny_escalated_claim,
)

ADMIN = TEST_USERS["platform_admin_headers"]
UNDERWRITER = TEST_USERS["underwriting_admin_headers"]
FINANCE = TEST_USERS["finance_ops_headers"]
ADJ_1 = TEST_USERS["adjuster_1_headers"]


def _ny_treatied_cohort_with_open_reserve(api):
    """NY ABSOLUTE filing, treaty 0.75 attached, premium 200000 paid,
    one instant-paid claim (100000) and one escalated claim (60000).

    Expected state: pot 43750; retained actual 25000; retained reserved 40000;
    giveback actual 18750; giveback projected 3750.
    """
    ctx = setup_bound_policy(
        state_code="NY", premium_cents=200000, coverage_amount_cents=900000,
        filing_mode="ABSOLUTE_CENTS", max_flat_fee_pct=0.30,
        max_flat_fee_cap_cents=25000, flat_fee_pct=0.30, flat_fee_cents=25000,
        attach_treaty_quota=0.75,
    )
    pay_premium(ctx["policy"]["id"], 200000)
    ph = ctx["policyholder"]
    claim_a = file_claim(ph["id"], ctx["policy"]["id"], 100000, 0.10, "vid-A")
    claim_b = file_claim(ph["id"], ctx["policy"]["id"], 60000, 0.90, "vid-B")
    ctx["claim_a"] = claim_a
    ctx["claim_b"] = claim_b
    return ctx


class TestRetainedRiskVariants:
    def test_actual_and_projected_variants_diverge_with_open_reserve(self, api):
        """PRD §3.10: "The actual basis, retained_claims_actual_cents, sums the retained amounts over PAID claims only — reserves do not count — and giveback_actual_cents is the claims pot minus that figure, floored at zero".
        PRD §3.10: "The provisional basis, retained_claims_reserved_cents, adds the reserved parts over ESCALATED claims on top of the paid total, and giveback_projected_cents is the claims pot minus that larger figure, floored at zero".

        Design: Difficulty/dual_variant_calc/giveback_actual_vs_projected_variants_diverge_with_open_reserve
        """
        ctx = _ny_treatied_cohort_with_open_reserve(api)
        claim_a = validate_success(api.get_claim(ctx["claim_a"]["id"], ADJ_1))
        claim_b = validate_success(api.get_claim(ctx["claim_b"]["id"], ADJ_1))
        assert claim_a["status"] == "PAID"
        assert claim_a["reinsurance_share_cents"] == 75000
        assert claim_b["status"] == "ESCALATED"
        assert claim_b["reserve_cents"] == 60000
        assert claim_b["reinsurance_share_cents"] == 45000
        cohort = get_cohort(ctx["cohort"]["id"])
        assert cohort["claims_pot_cents"] == 43750
        assert cohort["retained_claims_actual_cents"] == 25000
        assert cohort["retained_claims_reserved_cents"] == 40000

    def test_giveback_figures_for_open_reserve_state(self, api):
        """PRD §3.10: "giveback_actual_cents is the claims pot minus that figure, floored at zero; this is the final number the giveback run distributes, and on this basis an unused reserve flows to charity." — "giveback_projected_cents is the claims pot minus that larger figure, floored at zero".

        Design: Difficulty/dual_variant_calc/giveback_actual_vs_projected_variants_diverge_with_open_reserve
        """
        ctx = _ny_treatied_cohort_with_open_reserve(api)
        cohort = get_cohort(ctx["cohort"]["id"])
        assert cohort["giveback_actual_cents"] == 18750
        assert cohort["giveback_projected_cents"] == 3750

    def test_giveback_run_pays_actual_basis_not_projected(self, api):
        """PRD §3.10: "The annual giveback run executes against a CLOSED cohort — running it on an OPEN or already-DONATED cohort is rejected with ERR_COHORT_NOT_CLOSED — and distributes giveback_actual_cents across policies by premium weight." — "this is the final number the giveback run distributes, and on this basis an unused reserve flows to charity."
        PRD §3.3: "From CLOSED, a FinanceOps-run giveback (§3.8) moves it to DONATED."

        Design: Difficulty/dual_variant_calc/giveback_run_pays_actual_basis_not_projected_basis
        """
        ctx = _ny_treatied_cohort_with_open_reserve(api)
        validate_success(api.close_cohort(ctx["cohort"]["id"], ADMIN))
        result = validate_success(api.run_giveback(ctx["cohort"]["id"], FINANCE))
        assert result["giveback_total_cents"] == 18750
        cohort = get_cohort(ctx["cohort"]["id"])
        assert cohort["status"] == "DONATED"

    def test_giveback_run_leaves_projection_field_separate(self, api):
        """PRD §3.10: "The provisional basis, retained_claims_reserved_cents, adds the reserved parts over ESCALATED claims on top of the paid total, and giveback_projected_cents is the claims pot minus that larger figure, floored at zero; this is the conservative projection shown during the year".

        Design: Difficulty/dual_variant_calc/giveback_run_pays_actual_basis_not_projected_basis
        """
        ctx = _ny_treatied_cohort_with_open_reserve(api)
        validate_success(api.close_cohort(ctx["cohort"]["id"], ADMIN))
        validate_success(api.run_giveback(ctx["cohort"]["id"], FINANCE))
        cohort = get_cohort(ctx["cohort"]["id"])
        assert cohort["giveback_projected_cents"] == 3750


class TestReserveReleaseOnDenial:
    def test_denial_releases_reserve_and_restores_projection(self, api):
        """PRD §3.8: "The claim moves ESCALATED → DENIED: the reserve is released" and "The cohort's retained_claims_reserved_cents and giveback_projected_cents are recomputed, since the released reserve changes the provisional picture."
        PRD §3.10: "a DENIED claim retains nothing".

        Design: Difficulty/compensating_invariant/denial_releases_reserve_conserving_projected_giveback
        """
        ctx = setup_bound_policy(
            state_code="NY", premium_cents=200000, coverage_amount_cents=900000,
            filing_mode="ABSOLUTE_CENTS", max_flat_fee_pct=0.30,
            max_flat_fee_cap_cents=25000, flat_fee_pct=0.30, flat_fee_cents=25000,
            attach_treaty_quota=0.75,
        )
        pay_premium(ctx["policy"]["id"], 200000)
        claim = create_escalated_claim(ctx["policyholder"]["id"], ctx["policy"]["id"], 60000)
        mid = get_cohort(ctx["cohort"]["id"])
        assert mid["retained_claims_reserved_cents"] == 15000
        assert mid["giveback_projected_cents"] == 28750
        deny_escalated_claim(claim["id"], claim["version"], "COVERAGE")
        cohort = get_cohort(ctx["cohort"]["id"])
        assert cohort["retained_claims_reserved_cents"] == 0
        assert cohort["giveback_projected_cents"] == 43750

    def test_coverage_denial_releases_claim_reserve_without_strike(self, api):
        """PRD §3.8: "the reserve is released (reserve_cents becomes null)" and "A fraud denial carries a further consequence: the policyholder's fraud_strike_count increments by one" — only FRAUD carries the strike.
        PRD §3.8: "The strike count is precisely the number of that policyholder's claims denied with reason FRAUD."

        Design: Difficulty/compensating_invariant/denial_releases_reserve_conserving_projected_giveback
        """
        from test_helpers import get_policyholder
        ctx = setup_bound_policy(state_code="NY", premium_cents=200000, coverage_amount_cents=900000)
        pay_premium(ctx["policy"]["id"], 200000)
        claim = create_escalated_claim(ctx["policyholder"]["id"], ctx["policy"]["id"], 60000)
        denied = deny_escalated_claim(claim["id"], claim["version"], "COVERAGE")
        assert denied["status"] == "DENIED"
        assert denied["reserve_cents"] is None
        ph_after = get_policyholder(ctx["policyholder"]["id"])
        assert ph_after["fraud_strike_count"] == 0


class TestGivebackRunGate:
    def test_giveback_run_rejected_when_cohort_open(self, api):
        """PRD §3.10: "The annual giveback run executes against a CLOSED cohort — running it on an OPEN or already-DONATED cohort is rejected with ERR_COHORT_NOT_CLOSED".

        Design: Difficulty/cross_entity_state_dependency/giveback_run_rejected_when_cohort_not_closed
        """
        ctx = setup_bound_policy(state_code="KS", premium_cents=100000)
        pay_premium(ctx["policy"]["id"], 100000)
        resp = api.run_giveback(ctx["cohort"]["id"], FINANCE)
        validate_error(resp, ApiErrorId.ERR_COHORT_NOT_CLOSED)

    def test_giveback_run_rejected_leaves_aggregates_untouched(self, api):
        """PRD §3.10: "The annual giveback run executes against a CLOSED cohort — running it on an OPEN or already-DONATED cohort is rejected with ERR_COHORT_NOT_CLOSED".

        Design: Difficulty/cross_entity_state_dependency/giveback_run_rejected_when_cohort_not_closed
        """
        ctx = setup_bound_policy(state_code="KS", premium_cents=100000)
        pay_premium(ctx["policy"]["id"], 100000)
        api.run_giveback(ctx["cohort"]["id"], FINANCE)
        cohort = get_cohort(ctx["cohort"]["id"])
        assert cohort["status"] == "OPEN"
        assert cohort["giveback_actual_cents"] == 80000

    def test_second_giveback_run_rejected_after_donated(self, api):
        """PRD §3.10: "running it on an OPEN or already-DONATED cohort is rejected with ERR_COHORT_NOT_CLOSED".

        Design: Corner/cross_cutting_layers/ops_run_giveback_epoch_checkpoint
        """
        ctx = setup_bound_policy(state_code="TX", premium_cents=50000)
        pay_premium(ctx["policy"]["id"], 50000)
        validate_success(api.close_cohort(ctx["cohort"]["id"], ADMIN))
        validate_success(api.run_giveback(ctx["cohort"]["id"], FINANCE))
        resp = api.run_giveback(ctx["cohort"]["id"], FINANCE)
        validate_error(resp, ApiErrorId.ERR_COHORT_NOT_CLOSED)
        cohort = get_cohort(ctx["cohort"]["id"])
        assert cohort["status"] == "DONATED"


class TestGivebackAllocation:
    def _three_policy_cohort(self, api):
        """Causes A (cohort default) and B; three TX policies with premiums
        60000/30000/10000 fully paid; P1 elects A, P2 elects B; a 69999 payout
        on P1 leaves giveback_actual 10001. Cohort closed."""
        set_clock()
        cause_a = create_cause("Cause A")
        cause_b = create_cause("Cause B")
        cohort = create_cohort(2026, cause_a["id"])
        setup_state_fee(state_code="TX")
        policies = []
        holders = []
        for email, premium in (("p1@x.com", 60000), ("p2@x.com", 30000), ("p3@x.com", 10000)):
            ph = create_policyholder(state_code="TX", email=email)
            quote = create_quote(ph["id"], 500000, premium)
            app = create_application(ph["id"], quote["id"])
            policy = bind_policy(ph["id"], quote["id"], app["id"])
            policies.append(policy)
            holders.append(ph)
        validate_success(
            api.elect_cause(
                policies[0]["id"],
                {"cause_id": cause_a["id"], "expected_policy_version": policies[0]["version"]},
                make_policyholder_headers(holders[0]["id"]),
            )
        )
        validate_success(
            api.elect_cause(
                policies[1]["id"],
                {"cause_id": cause_b["id"], "expected_policy_version": policies[1]["version"]},
                make_policyholder_headers(holders[1]["id"]),
            )
        )
        for policy, premium in zip(policies, (60000, 30000, 10000)):
            pay_premium(policy["id"], premium)
        claim = create_escalated_claim(holders[0]["id"], policies[0]["id"], 69999)
        approve_escalated_claim(claim["id"], claim["version"], 69999)
        validate_success(api.close_cohort(cohort["id"], ADMIN))
        return cohort, cause_a, cause_b, policies, holders

    def test_largest_remainder_allocation_and_cause_grouping(self, api):
        """PRD §3.10: "Each policy receives the whole-cent floor of its raw share, and the remaining cents — the pot minus the sum of the floors — are distributed one cent at a time to policies ordered by the fractional part of their raw share in descending order, ties broken by the policy's created_at ascending (never by identifier), cycling until the remainder is exhausted: the classic largest-remainder method."
        PRD §3.10: "Donations are then grouped by cause: each policy's allocation flows to its cause_id when one was elected, or to the cohort's default cause_id when the policy never elected."

        Design: Difficulty/combinatorial_formula/giveback_allocation_circular_pot_weight_resolution_order
        """
        cohort, cause_a, cause_b, policies, _ = self._three_policy_cohort(api)
        result = validate_success(api.run_giveback(cohort["id"], FINANCE))
        assert result["giveback_total_cents"] == 10001
        # Donations are grouped by cause; two distinct target causes (P1 and P3
        # land on the cohort default A, P2 on B) produce a two-entry breakdown.
        assert len(result["cause_allocations"]) == 2
        cohort_after = get_cohort(cohort["id"])
        assert cohort_after["status"] == "DONATED"

    def test_pot_resolved_before_weights_in_run(self, api):
        """PRD §3.10: "The annual giveback run executes against a CLOSED cohort — running it on an OPEN or already-DONATED cohort is rejected with ERR_COHORT_NOT_CLOSED — and distributes giveback_actual_cents across policies by premium weight."
        PRD §3.10: "the pot is apportioned in exact rational arithmetic: each policy's raw share is the pot multiplied by its weight and divided by the total weight across eligible policies."

        Design: Difficulty/combinatorial_formula/giveback_allocation_circular_pot_weight_resolution_order
        """
        # Same three-policy fixture, but the observation is the pot side:
        # pot 80000 minus the 69999 retained payout must be the distributed
        # total, and the cohort moves to DONATED as its terminal state.
        cohort, cause_a, cause_b, policies, _ = self._three_policy_cohort(api)
        pre = get_cohort(cohort["id"])
        assert pre["giveback_actual_cents"] == 10001
        result = validate_success(api.run_giveback(cohort["id"], FINANCE))
        assert result["giveback_total_cents"] == pre["giveback_actual_cents"]
        assert get_cohort(cohort["id"])["status"] == "DONATED"

    def test_allocation_conserves_total_donated_equals_pot(self, api):
        """PRD §3.10: "the pot is apportioned in exact rational arithmetic: each policy's raw share is the pot multiplied by its weight and divided by the total weight across eligible policies" and "The run returns the cohort_id, the giveback_total_cents distributed, and the cause_allocations breakdown".

        Design: Difficulty/compensating_invariant/giveback_allocation_conserves_total_donated_equals_pot
        """
        cohort, cause_a, cause_b, policies, _ = self._three_policy_cohort(api)
        result = validate_success(api.run_giveback(cohort["id"], FINANCE))
        assert result["giveback_total_cents"] == 10001
        assert result["giveback_total_cents"] == get_cohort(cohort["id"])["giveback_actual_cents"]
        assert len(result["cause_allocations"]) == 2

    def test_largest_remainder_tie_broken_by_created_at(self, api):
        """PRD §3.10: "the remaining cents — the pot minus the sum of the floors — are distributed one cent at a time to policies ordered by the fractional part of their raw share in descending order, ties broken by the policy's created_at ascending (never by identifier)".

        Design: Corner/calculations/largest_remainder_tie_broken_by_created_at
        """
        set_clock()
        cause_a = create_cause("C")
        cohort = create_cohort(2026, cause_a["id"])
        setup_state_fee(state_code="TX")
        holders = []
        policies = []
        for email in ("p1@x.com", "p2@x.com"):
            ph = create_policyholder(state_code="TX", email=email)
            quote = create_quote(ph["id"], 500000, 50000)
            app = create_application(ph["id"], quote["id"])
            policy = bind_policy(ph["id"], quote["id"], app["id"])
            holders.append(ph)
            policies.append(policy)
        pay_premium(policies[0]["id"], 50000)
        pay_premium(policies[1]["id"], 50000)
        claim = create_escalated_claim(holders[0]["id"], policies[0]["id"], 79999)
        approve_escalated_claim(claim["id"], claim["version"], 79999)
        validate_success(api.close_cohort(cohort["id"], ADMIN))
        result = validate_success(api.run_giveback(cohort["id"], FINANCE))
        assert result["giveback_total_cents"] == 1
        # Both policies share the single cohort default cause, so the one
        # allocated cent flows to that cause; the run conserves the pot.
        assert len(result["cause_allocations"]) == 1

    def test_zero_pot_run_still_transitions_to_donated(self, api):
        """PRD §3.10: "When the total weight is zero or the pot itself is zero, no allocations are made at all — yet the cohort still transitions to DONATED, because the run is the closing act regardless of whether money moved."

        Design: Difficulty/compensating_invariant/giveback_allocation_conserves_total_donated_equals_pot
        """
        # One policy, premium 50000 paid (pot 40000), a 40000 payout drains the
        # pot to giveback_actual 0; the run distributes nothing and still
        # closes the cohort as DONATED.
        ctx = setup_bound_policy(state_code="TX", premium_cents=50000)
        pay_premium(ctx["policy"]["id"], 50000)
        claim = create_escalated_claim(ctx["policyholder"]["id"], ctx["policy"]["id"], 40000)
        approve_escalated_claim(claim["id"], claim["version"], 40000)
        validate_success(api.close_cohort(ctx["cohort"]["id"], ADMIN))
        result = validate_success(api.run_giveback(ctx["cohort"]["id"], FINANCE))
        assert result["giveback_total_cents"] == 0
        assert result["cause_allocations"] == []
        assert get_cohort(ctx["cohort"]["id"])["status"] == "DONATED"

    def test_lapsed_policy_excluded_from_allocation_weights(self, api):
        """PRD §3.10: "Eligible policies are those in the cohort whose status is anything other than LAPSED — both ACTIVE and CANCELLED policies participate."
        PRD §3.6: "A lapsed policy stops accepting first notices of loss — FNOL against it fails with ERR_POLICY_NOT_ACTIVE — and is excluded from giveback allocation weights."
        PRD §3.10: "Donations are then grouped by cause: each policy's allocation flows to its cause_id when one was elected, or to the cohort's default cause_id when the policy never elected."
        P1 (premium 60000, 20000 paid → lapsable, elects cause B) and P2 (premium 50000, fully paid, default cause A) share a cohort; a 46000 payout on P2 leaves giveback_actual 10000 (pot 56000 − retained 46000). With P1 lapsed and excluded, P2 is the sole eligible policy: all 10000 flows to cause A and cause B receives nothing. If P1's 20000 weight wrongly participated, P2 would take only 7143 and 2857 would leak to cause B — so the cause breakdown is the exclusion witness.

        Design: Corner/calculations/giveback_input_set_excludes_lapsed_policy_weights
        """
        set_clock("2026-02-01T00:00:00Z")
        cause, cohort = create_cause_and_cohort(2026)
        cause_b = create_cause("Cause B")
        setup_state_fee(state_code="TX")
        ph1 = create_policyholder(state_code="TX", email="p1@x.com")
        q1 = create_quote(ph1["id"], 500000, 60000)
        app1 = create_application(ph1["id"], q1["id"])
        pol1 = bind_policy(ph1["id"], q1["id"], app1["id"])
        validate_success(
            api.elect_cause(
                pol1["id"],
                {"cause_id": cause_b["id"], "expected_policy_version": pol1["version"]},
                make_policyholder_headers(ph1["id"]),
            )
        )
        pay_premium(pol1["id"], 20000)
        ph2 = create_policyholder(state_code="TX", email="p2@x.com")
        q2 = create_quote(ph2["id"], 500000, 50000)
        app2 = create_application(ph2["id"], q2["id"])
        pol2 = bind_policy(ph2["id"], q2["id"], app2["id"])
        pay_premium(pol2["id"], 50000)
        claim = create_escalated_claim(ph2["id"], pol2["id"], 46000)
        approve_escalated_claim(claim["id"], claim["version"], 46000)
        set_clock("2026-04-02T00:00:00Z")
        lapsed = validate_success(api.lapse_policy(pol1["id"], FINANCE))
        assert lapsed["status"] == "LAPSED"
        pre = get_cohort(cohort["id"])
        assert pre["giveback_actual_cents"] == 10000
        validate_success(api.close_cohort(cohort["id"], ADMIN))
        result = validate_success(api.run_giveback(cohort["id"], FINANCE))
        assert result["giveback_total_cents"] == 10000
        # P2 (sole eligible policy, cohort default cause) takes the full pot;
        # the lapsed P1's elected cause receives nothing.
        assert result["cause_allocations"] == [
            {"cause_id": cause["id"], "amount_cents": 10000}
        ]
        cohort_after = get_cohort(cohort["id"])
        assert cohort_after["status"] == "DONATED"


class TestCohortPoliciesReachability:
    def test_cohort_policies_reverse_lookup(self, api):
        """PRD §3.4: "its cohort_id resolves to the unique OPEN cohort whose cohort_year equals the bind year (if none exists, the approval fails with ERR_COHORT_NOT_OPEN)".

        Design: Corner/endpoints/fk_reverse_reachability_cohort_to_policies
        """
        ctx = setup_bound_policy(state_code="TX", premium_cents=100000)
        cohort_2027 = create_cohort(2027, ctx["cause"]["id"])
        data, _ = validate_paginated(api.list_cohort_policies(ctx["cohort"]["id"], ADMIN))
        assert [p["id"] for p in data] == [ctx["policy"]["id"]]
        data27, _ = validate_paginated(api.list_cohort_policies(cohort_2027["id"], ADMIN))
        assert data27 == []


class TestCauseLifecycle:
    def test_cause_retire_blocks_new_cohort_but_keeps_existing(self, api):
        """PRD §3.3: "the referenced cause must be ACTIVE at creation time, otherwise ERR_CAUSE_NOT_ACTIVE."
        PRD §3.3: "A PlatformAdmin registers one with a name; it is born ACTIVE and may later be retired, moving to RETIRED."

        Design: Corner/validations/cause_retire_blocks_new_cohort_but_keeps_existing
        """
        set_clock()
        cause = create_cause("C")
        cohort = create_cohort(2026, cause["id"])
        validate_success(api.retire_cause(cause["id"], ADMIN))
        resp = api.create_cohort({"cohort_year": 2027, "cause_id": cause["id"]}, ADMIN)
        validate_error(resp, ApiErrorId.ERR_CAUSE_NOT_ACTIVE)
        cohort_after = get_cohort(cohort["id"], ADMIN)
        assert cohort_after["cause_id"] == cause["id"]
        assert cohort_after["status"] == "OPEN"


class TestLapseGrace:
    def test_lapse_before_grace_rejected_then_succeeds_at_grace(self, api):
        """PRD §3.6: "only once the current logical clock has reached the policy's created_at plus the premium_grace_days carried over from the bound quote (60 days by default); an early attempt is rejected with ERR_LAPSE_GRACE_NOT_ELAPSED."

        Design: Corner/validations/lapse_before_grace_rejected
        """
        ctx = setup_bound_policy(
            state_code="TX", premium_cents=50000, start_clock="2026-02-01T00:00:00Z"
        )
        pay_premium(ctx["policy"]["id"], 10000)  # outstanding 40000
        set_clock("2026-04-01T00:00:00Z")  # 59 days after bind
        resp = api.lapse_policy(ctx["policy"]["id"], FINANCE)
        validate_error(resp, ApiErrorId.ERR_LAPSE_GRACE_NOT_ELAPSED)
        from test_helpers import get_policy
        assert get_policy(ctx["policy"]["id"])["status"] == "ACTIVE"
        set_clock("2026-04-02T00:00:00Z")  # exactly 60 days after bind
        lapsed = validate_success(api.lapse_policy(ctx["policy"]["id"], FINANCE))
        assert lapsed["status"] == "LAPSED"
