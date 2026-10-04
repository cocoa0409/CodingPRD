"""Appeals: window boundary, one-shot cap, segregation of duties, outcomes."""
from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    create_escalated_claim,
    deny_escalated_claim,
    file_appeal,
    file_claim,
    make_adjuster_headers,
    make_policyholder_headers,
    pay_premium,
    set_clock,
    setup_bound_policy,
    setup_denied_claim_with_appeal,
    setup_state_fee,
    create_cause_and_cohort,
    create_policyholder,
    create_quote,
    create_application,
    bind_policy,
    validate_error,
    validate_paginated,
    validate_success,
    list_ledger_entries,
)

ADMIN = TEST_USERS["platform_admin_headers"]
UNDERWRITER = TEST_USERS["underwriting_admin_headers"]
FINANCE = TEST_USERS["finance_ops_headers"]
ADJ_1 = TEST_USERS["adjuster_1_headers"]
ADJ_2 = TEST_USERS["adjuster_2_headers"]


class TestAppealWindow:
    def _fl_denied_claims(self, api):
        """Two FL policyholders, each with a claim denied at 2026-03-01T10:00:00Z."""
        set_clock("2026-02-20T00:00:00Z")
        cause, cohort = create_cause_and_cohort(2026)
        setup_state_fee(state_code="FL")
        out = []
        for email in ("p@x.com", "q@x.com"):
            ph = create_policyholder(state_code="FL", email=email)
            quote = create_quote(ph["id"], 500000, 100000)
            app = create_application(ph["id"], quote["id"])
            policy = bind_policy(ph["id"], quote["id"], app["id"])
            pay_premium(policy["id"], 100000)
            claim = create_escalated_claim(ph["id"], policy["id"], 50000)
            out.append((ph, policy, claim))
        set_clock("2026-03-01T10:00:00Z")
        for ph, policy, claim in out:
            deny_escalated_claim(claim["id"], claim["version"], "COVERAGE")
        return out

    def test_appeal_exactly_at_deadline_allowed(self, api):
        """PRD §3.9: "requires the current logical clock to be at or before the claim's appeal_deadline: a request landing exactly at the deadline instant is allowed, while one second past it fails with ERR_APPEAL_WINDOW_CLOSED."

        Design: Difficulty/boundary_precision_check/appeal_window_exactly_at_deadline_vs_one_second_after
        """
        (ph_p, _, claim_p), _ = self._fl_denied_claims(api)
        set_clock("2026-03-31T10:00:00Z")
        appeal = validate_success(
            api.create_appeal(claim_p["id"], {"statement": "at deadline"},
                              make_policyholder_headers(ph_p["id"])),
            expected_status=201,
        )
        assert appeal["status"] == "PENDING"
        claim_after = validate_success(api.get_claim(claim_p["id"], ADJ_1))
        assert claim_after["status"] == "APPEALED"
        assert claim_after["appeal_count"] == 1

    def test_appeal_one_second_after_deadline_rejected(self, api):
        """PRD §3.9: "requires the current logical clock to be at or before the claim's appeal_deadline: a request landing exactly at the deadline instant is allowed, while one second past it fails with ERR_APPEAL_WINDOW_CLOSED."

        Design: Difficulty/boundary_precision_check/appeal_window_exactly_at_deadline_vs_one_second_after
        """
        _, (ph_q, _, claim_q) = self._fl_denied_claims(api)
        set_clock("2026-03-31T10:00:01Z")
        resp = api.create_appeal(
            claim_q["id"], {"statement": "one second late"},
            make_policyholder_headers(ph_q["id"]),
        )
        validate_error(resp, ApiErrorId.ERR_APPEAL_WINDOW_CLOSED)
        claim_after = validate_success(api.get_claim(claim_q["id"], ADJ_1))
        assert claim_after["status"] == "DENIED"
        assert claim_after["appeal_count"] == 0

    def test_late_appeal_rejected_and_deadline_stamped(self, api):
        """PRD §3.8: "an appeal_deadline is stamped at exactly 30 days after the denial instant".
        PRD §3.9: "a request landing exactly at the deadline instant is allowed, while one second past it fails with ERR_APPEAL_WINDOW_CLOSED."

        Design: Difficulty/resource_temporal_overlap/appeal_window_overlap_with_giveback_close_blocks_late_appeal
        """
        set_clock("2026-02-20T00:00:00Z")
        create_cause_and_cohort(2026)
        setup_state_fee(state_code="WY")
        ph = create_policyholder(state_code="WY", email="wy@x.com")
        quote = create_quote(ph["id"], 500000, 100000)
        app = create_application(ph["id"], quote["id"])
        policy = bind_policy(ph["id"], quote["id"], app["id"])
        pay_premium(policy["id"], 100000)
        claim = create_escalated_claim(ph["id"], policy["id"], 50000)
        set_clock("2026-03-01T00:00:00Z")
        deny_escalated_claim(claim["id"], claim["version"], "COVERAGE")
        claim_after = validate_success(api.get_claim(claim["id"], ADJ_1))
        assert claim_after["appeal_deadline"] == "2026-03-31T00:00:00.000Z"
        set_clock("2026-04-15T00:00:00Z")
        resp = api.create_appeal(
            claim["id"], {"statement": "late"}, make_policyholder_headers(ph["id"])
        )
        validate_error(resp, ApiErrorId.ERR_APPEAL_WINDOW_CLOSED)
        claim_final = validate_success(api.get_claim(claim["id"], ADJ_1))
        assert claim_final["status"] == "DENIED"
        assert claim_final["appeal_count"] == 0

    def test_appeal_on_paid_claim_rejected_by_state_guard(self, api):
        """PRD §3.9: "Filing requires the claim to be DENIED (otherwise ERR_INVALID_STATE)".

        Design: Difficulty/priority_pair_validation_conflict/appeal_state_check_beats_window_check_on_paid_claim
        """
        ctx = setup_bound_policy(state_code="AZ", premium_cents=100000)
        pay_premium(ctx["policy"]["id"], 100000)
        claim = file_claim(ctx["policyholder"]["id"], ctx["policy"]["id"], 100000, 0.10)
        assert claim["status"] == "PAID"
        resp = api.create_appeal(
            claim["id"], {"statement": "i want more money"},
            make_policyholder_headers(ctx["policyholder"]["id"]),
        )
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE)
        claim_after = validate_success(api.get_claim(claim["id"], ADJ_1))
        assert claim_after["status"] == "PAID"
        assert claim_after["appeal_count"] == 0


    def test_appeal_deadline_stamped_30_days_after_denial(self, api):
        """PRD §3.8: "an appeal_deadline is stamped at exactly 30 days after the denial instant".

        Design: Difficulty/resource_temporal_overlap/appeal_window_overlap_with_giveback_close_blocks_late_appeal
        """
        set_clock("2026-02-20T00:00:00Z")
        create_cause_and_cohort(2026)
        setup_state_fee(state_code="WY")
        ph = create_policyholder(state_code="WY", email="wy@x.com")
        quote = create_quote(ph["id"], 500000, 100000)
        app = create_application(ph["id"], quote["id"])
        policy = bind_policy(ph["id"], quote["id"], app["id"])
        pay_premium(policy["id"], 100000)
        claim = create_escalated_claim(ph["id"], policy["id"], 50000)
        set_clock("2026-03-01T00:00:00Z")
        deny_escalated_claim(claim["id"], claim["version"], "COVERAGE")
        claim_after = validate_success(api.get_claim(claim["id"], ADJ_1))
        assert claim_after["appeal_deadline"] == "2026-03-31T00:00:00.000Z"
        assert claim_after["status"] == "DENIED"

    def test_appeal_on_paid_claim_creates_no_appeal_record(self, api):
        """PRD §3.9: "Filing requires the claim to be DENIED (otherwise ERR_INVALID_STATE)" — a rejected filing creates no appeal row.
        PRD §3.9: "A successful filing creates an Appeal in PENDING, moves the claim from DENIED to APPEALED, and increments appeal_count by one" — a rejected filing therefore leaves the appeals list empty.

        Design: Difficulty/priority_pair_validation_conflict/appeal_state_check_beats_window_check_on_paid_claim
        """
        ctx = setup_bound_policy(state_code="AZ", premium_cents=100000)
        pay_premium(ctx["policy"]["id"], 100000)
        claim = file_claim(ctx["policyholder"]["id"], ctx["policy"]["id"], 100000, 0.10)
        assert claim["status"] == "PAID"
        resp = api.create_appeal(
            claim["id"], {"statement": "i want more money"},
            make_policyholder_headers(ctx["policyholder"]["id"]),
        )
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE)
        appeals, _ = validate_paginated(
            api.list_claim_appeals(claim["id"], ADJ_1)
        )
        assert appeals == []


class TestAppealCap:
    def test_second_appeal_rejected_by_limit(self, api):
        """PRD §3.9: "requires the appeal count to still be below the cap of one — a second appeal is rejected with ERR_APPEAL_LIMIT_REACHED".

        Design: Corner/validations/second_appeal_rejected_by_limit
        """
        ctx = setup_denied_claim_with_appeal(denial_reason="COVERAGE")
        appeal = ctx["appeal"]
        validate_success(
            api.uphold_appeal(appeal["id"], {"review_note": "denial stands"}, ADJ_2)
        )
        resp = api.create_appeal(
            ctx["claim"]["id"], {"statement": "second try"},
            make_policyholder_headers(ctx["policyholder"]["id"]),
        )
        validate_error(resp, ApiErrorId.ERR_APPEAL_LIMIT_REACHED)
        claim_after = validate_success(api.get_claim(ctx["claim"]["id"], ADJ_1))
        assert claim_after["appeal_count"] == 1
        assert claim_after["status"] == "DENIED"


class TestSegregationOfDuties:
    def test_same_adjuster_cannot_review_own_denial(self, api):
        """PRD §3.9: "Review is performed by a ClaimsAdjuster, never by the adjuster who issued the original denial: when the reviewer's X-User-ID equals the claim's recorded denied_by_adjuster_id, the review is rejected with ERR_SEGREGATION_OF_DUTIES."

        Design: Corner/validations/segregation_of_duties_same_adjuster_cannot_review_own_denial
        """
        ctx = setup_denied_claim_with_appeal(denial_reason="COVERAGE")
        resp = api.uphold_appeal(
            ctx["appeal"]["id"], {"review_note": "i deny again"}, ADJ_1
        )
        validate_error(resp, ApiErrorId.ERR_SEGREGATION_OF_DUTIES)
        appeal_after = validate_success(api.get_appeal(ctx["appeal"]["id"], ADJ_2))
        assert appeal_after["status"] == "PENDING"
        claim_after = validate_success(api.get_claim(ctx["claim"]["id"], ADJ_1))
        assert claim_after["denied_by_adjuster_id"] == "adj-1"


class TestAppealOutcomes:
    def test_uphold_returns_claim_to_denied_terminal(self, api):
        """PRD §3.9: "Upholding the denial moves the appeal to UPHELD and returns the claim to DENIED, its terminal state."

        Design: Corner/state_machines/appeal_uphold_returns_claim_to_denied_terminal
        """
        ctx = setup_denied_claim_with_appeal(denial_reason="FRAUD")
        upheld = validate_success(
            api.uphold_appeal(
                ctx["appeal"]["id"], {"review_note": "evidence confirmed"}, ADJ_2
            )
        )
        assert upheld["status"] == "UPHELD"
        claim_after = validate_success(api.get_claim(ctx["claim"]["id"], ADJ_1))
        assert claim_after["status"] == "DENIED"
        assert claim_after["denial_reason"] == "FRAUD"
        from test_helpers import get_policyholder
        ph_after = get_policyholder(ctx["policyholder"]["id"])
        assert ph_after["fraud_strike_count"] == 1

    def test_overturn_pays_and_clears_denial_reason(self, api):
        """PRD §3.9: "Overturning requires a payout_cents input greater than zero; it moves the appeal to OVERTURNED, pays the claim — creating the payment, appending the ledger entry, and recomputing the cohort aggregates exactly as an escalation approval does — and clears the claim's denial_reason back to null as the claim reaches PAID."

        Design: Difficulty/non_linear_state_machine/claim_denied_appealed_paid_cycle_on_claim_entity
        """
        set_clock("2026-03-01T00:00:00Z")
        create_cause_and_cohort(2026)
        setup_state_fee(state_code="OR")
        ph = create_policyholder(state_code="OR", email="or@x.com")
        quote = create_quote(ph["id"], 500000, 100000)
        app = create_application(ph["id"], quote["id"])
        policy = bind_policy(ph["id"], quote["id"], app["id"])
        pay_premium(policy["id"], 100000)
        claim = create_escalated_claim(ph["id"], policy["id"], 80000)
        deny_escalated_claim(claim["id"], claim["version"], "COVERAGE")
        appeal = file_appeal(ph["id"], claim["id"], "the damage is covered under section 4")
        overturned = validate_success(
            api.overturn_appeal(
                appeal["id"],
                {"payout_cents": 65000, "review_note": "coverage confirmed on review"},
                ADJ_2,
            )
        )
        assert overturned["status"] == "OVERTURNED"
        claim_after = validate_success(api.get_claim(claim["id"], ADJ_1))
        assert claim_after["status"] == "PAID"
        assert claim_after["payout_cents"] == 65000
        assert claim_after["denial_reason"] is None
        assert claim_after["appeal_count"] == 1

    def test_overturn_creates_payment_and_ledger_entry(self, api):
        """PRD §3.9: "it moves the appeal to OVERTURNED, pays the claim — creating the payment, appending the ledger entry, and recomputing the cohort aggregates exactly as an escalation approval does".

        Design: Difficulty/non_linear_state_machine/claim_denied_appealed_paid_cycle_on_claim_entity
        """
        ctx = setup_denied_claim_with_appeal(denial_reason="COVERAGE", claimed_amount_cents=80000)
        overturned = validate_success(
            api.overturn_appeal(
                ctx["appeal"]["id"],
                {"payout_cents": 65000, "review_note": "coverage confirmed"},
                ADJ_2,
            )
        )
        assert overturned["status"] == "OVERTURNED"
        payments, _ = validate_paginated(
            api.list_claim_payments(
                ctx["claim"]["id"], make_policyholder_headers(ctx["policyholder"]["id"])
            )
        )
        assert len(payments) == 1
        assert payments[0]["amount_cents"] == 65000
        payout_entries = [
            e for e in list_ledger_entries(ctx["policy"]["id"]) if e["kind"] == "CLAIM_PAYOUT"
        ]
        assert len(payout_entries) == 1
        assert payout_entries[0]["amount_cents"] == 65000
