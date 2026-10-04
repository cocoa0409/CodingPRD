"""FNOL intake, triage routing, instant pay, escalation, and adjudication OCC."""
from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    approve_escalated_claim,
    create_escalated_claim,
    deny_escalated_claim,
    file_claim,
    get_cohort,
    make_policyholder_headers,
    pay_premium,
    setup_bound_policy,
    validate_error,
    validate_paginated,
    validate_success,
    list_ledger_entries,
    get_cohort,
)

ADMIN = TEST_USERS["platform_admin_headers"]
UNDERWRITER = TEST_USERS["underwriting_admin_headers"]
FINANCE = TEST_USERS["finance_ops_headers"]
ADJ_1 = TEST_USERS["adjuster_1_headers"]


class TestInstantPayBoundaries:
    def test_claimed_amount_exactly_250000_auto_pays(self, api):
        """PRD §3.7: "the claimed_amount_cents is at most 250000 cents — exactly 250000 cents still auto-pays".

        Design: Difficulty/boundary_precision_check/fnol_auto_pay_ceiling_inclusive_250000_vs_escalate_250001
        """
        ctx = setup_bound_policy(state_code="CO", premium_cents=600000, coverage_amount_cents=900000)
        pay_premium(ctx["policy"]["id"], 600000)
        claim = validate_success(
            api.create_claim(
                {
                    "policy_id": ctx["policy"]["id"],
                    "video_statement_ref": "at-limit",
                    "claimed_amount_cents": 250000,
                    "fraud_score": 0.10,
                },
                make_policyholder_headers(ctx["policyholder"]["id"]),
            ),
            expected_status=201,
        )
        assert claim["status"] == "PAID"
        assert claim["payout_cents"] == 250000
        payments, _ = validate_paginated(
            api.list_claim_payments(claim["id"], make_policyholder_headers(ctx["policyholder"]["id"]))
        )
        assert len(payments) == 1

    def test_claimed_amount_250001_escalates(self, api):
        """PRD §3.7: "the claimed_amount_cents is at most 250000 cents — exactly 250000 cents still auto-pays" (the ceiling is inclusive, so 250001 falls outside it).
        PRD §3.7: "Escalation sets an initial reserve_cents equal to the full claimed_amount_cents".

        Design: Difficulty/boundary_precision_check/fnol_auto_pay_ceiling_inclusive_250000_vs_escalate_250001
        """
        ctx = setup_bound_policy(state_code="CO", premium_cents=600000, coverage_amount_cents=900000)
        pay_premium(ctx["policy"]["id"], 600000)
        claim = validate_success(
            api.create_claim(
                {
                    "policy_id": ctx["policy"]["id"],
                    "video_statement_ref": "over-limit",
                    "claimed_amount_cents": 250001,
                    "fraud_score": 0.10,
                },
                make_policyholder_headers(ctx["policyholder"]["id"]),
            ),
            expected_status=201,
        )
        assert claim["status"] == "ESCALATED"
        assert claim["reserve_cents"] == 250001
        payments, _ = validate_paginated(
            api.list_claim_payments(claim["id"], make_policyholder_headers(ctx["policyholder"]["id"]))
        )
        assert payments == []

    def test_fraud_score_029_auto_pays_while_030_escalates(self, api):
        """PRD §3.7: "The claim auto-pays only when the fraud_score is strictly below 0.30 — a score of exactly 0.30 escalates".

        Design: Difficulty/boundary_precision_check/fraud_score_threshold_strict_less_than_030
        """
        ctx = setup_bound_policy(state_code="UT", premium_cents=100000)
        pay_premium(ctx["policy"]["id"], 100000)
        ph = ctx["policyholder"]
        claim_029 = file_claim(ph["id"], ctx["policy"]["id"], 1000, 0.29, "s029")
        claim_030 = file_claim(ph["id"], ctx["policy"]["id"], 1000, 0.30, "s030")
        assert claim_029["status"] == "PAID"
        assert claim_030["status"] == "ESCALATED"
        assert claim_030["reserve_cents"] == 1000

    def test_clean_claim_never_observable_in_fnol_submitted(self, api):
        """PRD §3.7: "The new claim lands in FNOL_SUBMITTED and is triaged in the same request."
        PRD §3.7: "When all three hold, the claim moves FNOL_SUBMITTED → AUTO_APPROVED → PAID within the single request".

        Design: Corner/state_machines/claim_created_in_fnol_then_system_triage_same_request
        """
        ctx = setup_bound_policy(state_code="TX", premium_cents=100000)
        pay_premium(ctx["policy"]["id"], 100000)
        claim = file_claim(ctx["policyholder"]["id"], ctx["policy"]["id"], 1000, 0.10)
        assert claim["status"] == "PAID"


    def test_fraud_score_boundary_compared_as_exact_decimal(self, api):
        """PRD §2.5: "Fraud scores, by contrast, are compared as exact decimals with no rounding".
        PRD §3.7: "The claim auto-pays only when the fraud_score is strictly below 0.30 — a score of exactly 0.30 escalates".

        Design: Difficulty/boundary_precision_check/fraud_score_threshold_strict_less_than_030
        """
        ctx = setup_bound_policy(state_code="UT", premium_cents=100000)
        pay_premium(ctx["policy"]["id"], 100000)
        ph = ctx["policyholder"]
        claim_low = file_claim(ph["id"], ctx["policy"]["id"], 1000, 0.29, "low")
        claim_at = file_claim(ph["id"], ctx["policy"]["id"], 1000, 0.30, "at")
        assert claim_low["status"] == "PAID"
        assert claim_low["payout_cents"] == 1000
        assert claim_at["status"] == "ESCALATED"
        assert claim_at["payout_cents"] is None


class TestFlaggedPolicyEscalates:
    def test_instant_pay_blocked_by_policy_fraud_flag(self, api):
        """PRD §3.7: "The claim auto-pays only when the fraud_score is strictly below 0.30 — a score of exactly 0.30 escalates — and the claimed_amount_cents is at most 250000 cents — exactly 250000 cents still auto-pays — and the policy's fraud_flag is false."
        PRD §3.4: "the policy that results will carry a permanent fraud_flag of true".

        Design: Corner/state_machines/instant_pay_on_flagged_policy_escalates_instead
        """
        ctx = setup_bound_policy(
            state_code="TX",
            premium_cents=100000,
            application_overrides={"checkout_velocity_seconds": 5},
        )
        policy = ctx["policy"]
        assert policy["fraud_flag"] is True
        pay_premium(policy["id"], 100000)
        claim = file_claim(ctx["policyholder"]["id"], policy["id"], 1000, 0.10)
        assert claim["status"] == "ESCALATED"


class TestEscalationSideEffects:
    def test_escalation_sets_reserve_and_drops_projected_giveback(self, api):
        """PRD §3.7: "Escalation sets an initial reserve_cents equal to the full claimed_amount_cents and immediately recomputes the cohort's retained_claims_reserved_cents and giveback_projected_cents, so the provisional projection reflects the open reserve from the first moment."

        Design: Corner/state_machines/escalate_side_effect_sets_reserve_and_projection
        """
        ctx = setup_bound_policy(state_code="TX", premium_cents=100000)
        pay_premium(ctx["policy"]["id"], 100000)
        claim = file_claim(ctx["policyholder"]["id"], ctx["policy"]["id"], 50000, 0.90)
        assert claim["status"] == "ESCALATED"
        assert claim["reserve_cents"] == 50000
        assert claim["reinsurance_share_cents"] == 0
        cohort = get_cohort(ctx["cohort"]["id"])
        assert cohort["giveback_projected_cents"] == 30000
        assert cohort["giveback_actual_cents"] == 80000


class TestInstantPayCascade:
    def test_instant_pay_cascades_payment_ledger_and_cohort(self, api):
        """PRD §3.7: "the claim moves FNOL_SUBMITTED → AUTO_APPROVED → PAID within the single request: payout_cents is set to the full claimed_amount_cents, a ClaimPayment is created in SETTLED status (the only alternative status being VOIDED) recording the gross amount_cents, the reinsurance_share_cents ceded at payment time, and a fee_cents that is always zero — payments never carry a fee, and the field exists so the ledger reconciles by construction."

        Design: Difficulty/transitive_cascade/instant_pay_cascades_claim_payment_ledger_cohort_giveback
        """
        ctx = setup_bound_policy(state_code="ME", premium_cents=100000, attach_treaty_quota=0.75)
        pay_premium(ctx["policy"]["id"], 100000)  # pot 20000
        claim = file_claim(ctx["policyholder"]["id"], ctx["policy"]["id"], 100000, 0.10)
        assert claim["status"] == "PAID"
        assert claim["payout_cents"] == 100000
        assert claim["reinsurance_share_cents"] == 75000
        payments, _ = validate_paginated(
            api.list_claim_payments(claim["id"], make_policyholder_headers(ctx["policyholder"]["id"]))
        )
        assert len(payments) == 1
        assert payments[0]["amount_cents"] == 100000
        assert payments[0]["reinsurance_share_cents"] == 75000
        payout_entries = [e for e in list_ledger_entries(ctx["policy"]["id"])
                          if e["kind"] == "CLAIM_PAYOUT"]
        assert len(payout_entries) == 1 and payout_entries[0]["amount_cents"] == 100000
        cohort = get_cohort(ctx["cohort"]["id"])
        assert cohort["claims_pot_cents"] == 20000
        assert cohort["retained_claims_actual_cents"] == 25000
        assert cohort["giveback_actual_cents"] == 0

    def test_instant_pay_claim_payment_records_zero_fee(self, api):
        """PRD §3.7: "a ClaimPayment is created in SETTLED status (the only alternative status being VOIDED) recording the gross amount_cents, the reinsurance_share_cents ceded at payment time, and a fee_cents that is always zero — payments never carry a fee, and the field exists so the ledger reconciles by construction."

        Design: Difficulty/transitive_cascade/instant_pay_cascades_claim_payment_ledger_cohort_giveback
        """
        ctx = setup_bound_policy(state_code="ME", premium_cents=100000, attach_treaty_quota=0.75)
        pay_premium(ctx["policy"]["id"], 100000)
        claim = file_claim(ctx["policyholder"]["id"], ctx["policy"]["id"], 100000, 0.10)
        payments, _ = validate_paginated(
            api.list_claim_payments(claim["id"], make_policyholder_headers(ctx["policyholder"]["id"]))
        )
        assert len(payments) == 1
        assert payments[0]["status"] == "SETTLED"
        assert payments[0]["fee_cents"] == 0
        assert payments[0]["amount_cents"] == 100000
        assert payments[0]["reinsurance_share_cents"] == 75000

    def test_instant_pay_visible_atomically_in_same_response(self, api):
        """PRD §3.7: "When all three hold, the claim moves FNOL_SUBMITTED → AUTO_APPROVED → PAID within the single request".
        PRD §1 (Introduction): "automated triage that pays clean low-value claims in the same breath that receives them".

        Design: Corner/consistency_model/instant_pay_visible_atomically_in_same_response
        """
        ctx = setup_bound_policy(state_code="TX", premium_cents=100000, attach_treaty_quota=0.75)
        pay_premium(ctx["policy"]["id"], 100000)
        claim = file_claim(ctx["policyholder"]["id"], ctx["policy"]["id"], 1000, 0.10)
        assert claim["status"] == "PAID"
        assert claim["payout_cents"] == 1000
        assert claim["reinsurance_share_cents"] == 750
        cohort = get_cohort(ctx["cohort"]["id"])
        assert cohort["retained_claims_actual_cents"] == 250


class TestFnolOnInactivePolicy:
    def test_fnol_rejected_when_policy_cancelled(self, api):
        """PRD §3.7: "The policy must be ACTIVE, otherwise ERR_POLICY_NOT_ACTIVE."
        PRD §3.6: "A lapsed policy stops accepting first notices of loss — FNOL against it fails with ERR_POLICY_NOT_ACTIVE".

        Design: Difficulty/cross_entity_state_dependency/fnol_rejected_when_policy_not_active
        """
        ctx = setup_bound_policy(state_code="ID", premium_cents=100000)
        pay_premium(ctx["policy"]["id"], 100000)
        validate_success(
            api.cancel_policy(
                ctx["policy"]["id"], make_policyholder_headers(ctx["policyholder"]["id"])
            )
        )
        resp = api.create_claim(
            {
                "policy_id": ctx["policy"]["id"],
                "video_statement_ref": "v",
                "claimed_amount_cents": 1000,
                "fraud_score": 0.10,
            },
            make_policyholder_headers(ctx["policyholder"]["id"]),
        )
        validate_error(resp, ApiErrorId.ERR_POLICY_NOT_ACTIVE)
        claims, meta = validate_paginated(
            api.list_policy_claims(ctx["policy"]["id"], ADJ_1)
        )
        assert claims == []


    def test_fnol_rejection_writes_no_payment_or_ledger_rows(self, api):
        """PRD §3.7: "The policy must be ACTIVE, otherwise ERR_POLICY_NOT_ACTIVE."
        PRD §3.7: "The new claim lands in FNOL_SUBMITTED and is triaged in the same request." — a rejected FNOL never enters triage, so no payment or CLAIM_PAYOUT ledger row can exist.

        Design: Difficulty/cross_entity_state_dependency/fnol_rejected_when_policy_not_active
        """
        ctx = setup_bound_policy(state_code="ID", premium_cents=100000)
        pay_premium(ctx["policy"]["id"], 100000)
        validate_success(
            api.cancel_policy(
                ctx["policy"]["id"], make_policyholder_headers(ctx["policyholder"]["id"])
            )
        )
        resp = api.create_claim(
            {
                "policy_id": ctx["policy"]["id"],
                "video_statement_ref": "v",
                "claimed_amount_cents": 1000,
                "fraud_score": 0.10,
            },
            make_policyholder_headers(ctx["policyholder"]["id"]),
        )
        validate_error(resp, ApiErrorId.ERR_POLICY_NOT_ACTIVE)
        payout_entries = [
            e for e in list_ledger_entries(ctx["policy"]["id"]) if e["kind"] == "CLAIM_PAYOUT"
        ]
        assert payout_entries == []
        cohort = get_cohort(ctx["cohort"]["id"])
        assert cohort["retained_claims_actual_cents"] == 0


class TestAdjudicationOccAndState:
    def test_stale_claim_version_on_deny(self, api):
        """PRD §2.6: "Denying an ESCALATED claim likewise requires expected_claim_version matching the claim's current version." — "if another writer has advanced that entity's version since the client last read it, the request is rejected with ERR_STALE_VERSION (HTTP 412)".

        Design: Corner/errors/stale_claim_version_on_deny
        """
        ctx = setup_bound_policy(state_code="TX", premium_cents=100000)
        pay_premium(ctx["policy"]["id"], 100000)
        claim = create_escalated_claim(ctx["policyholder"]["id"], ctx["policy"]["id"], 50000)
        resp = api.deny_claim(
            claim["id"],
            {"denial_reason": "COVERAGE", "expected_claim_version": claim["version"] - 1},
            ADJ_1,
        )
        validate_error(resp, ApiErrorId.ERR_STALE_VERSION)
        claim_after = validate_success(api.get_claim(claim["id"], ADJ_1))
        assert claim_after["status"] == "ESCALATED"

    def test_second_approve_on_paid_claim_rejected(self, api):
        """PRD §3.8: "acting on a claim that is not ESCALATED is ERR_INVALID_STATE."

        Design: Corner/state_machines/second_approve_on_paid_claim_rejected
        """
        ctx = setup_bound_policy(state_code="TX", premium_cents=500000, coverage_amount_cents=900000)
        pay_premium(ctx["policy"]["id"], 500000)
        claim = create_escalated_claim(ctx["policyholder"]["id"], ctx["policy"]["id"], 50000)
        approved = approve_escalated_claim(claim["id"], claim["version"], 40000)
        resp = api.approve_claim(
            claim["id"],
            {"payout_cents": 40000, "expected_claim_version": approved["version"]},
            ADJ_1,
        )
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE)
        payments, _ = validate_paginated(
            api.list_claim_payments(claim["id"], make_policyholder_headers(ctx["policyholder"]["id"]))
        )
        assert len(payments) == 1

    def test_terminal_paid_claim_rejects_deny(self, api):
        """PRD §3.8: "acting on a claim that is not ESCALATED is ERR_INVALID_STATE."

        Design: Corner/state_machines/terminal_paid_claim_rejects_deny
        """
        ctx = setup_bound_policy(state_code="TX", premium_cents=100000)
        pay_premium(ctx["policy"]["id"], 100000)
        claim = file_claim(ctx["policyholder"]["id"], ctx["policy"]["id"], 1000, 0.10)
        assert claim["status"] == "PAID"
        resp = api.deny_claim(
            claim["id"],
            {"denial_reason": "COVERAGE", "expected_claim_version": claim["version"]},
            ADJ_1,
        )
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE)
        claim_after = validate_success(api.get_claim(claim["id"], ADJ_1))
        assert claim_after["status"] == "PAID"

    def test_invalid_denial_reason_rejected(self, api):
        """PRD §3.8: "Denying requires a denial_reason drawn from FRAUD, COVERAGE, or OTHER — anything else is ERR_INVALID_REQUEST."
        PRD §2.8: "Generic request-shape failures — missing required fields, wrong types, out-of-range values, bad enum members — are rejected with ERR_INVALID_REQUEST (HTTP 400)."

        Design: Corner/entities/invalid_enum_denial_reason_rejected
        """
        ctx = setup_bound_policy(state_code="TX", premium_cents=100000)
        pay_premium(ctx["policy"]["id"], 100000)
        claim = create_escalated_claim(ctx["policyholder"]["id"], ctx["policy"]["id"], 5000)
        resp = api.deny_claim(
            claim["id"],
            {"denial_reason": "SUS", "expected_claim_version": claim["version"]},
            ADJ_1,
        )
        validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST)
        claim_after = validate_success(api.get_claim(claim["id"], ADJ_1))
        assert claim_after["status"] == "ESCALATED"

    def test_missing_video_statement_ref_rejected(self, api):
        """PRD §2.8: "Generic request-shape failures — missing required fields, wrong types, out-of-range values, bad enum members — are rejected with ERR_INVALID_REQUEST (HTTP 400)."

        Design: Corner/validations/missing_required_field_returns_invalid_request
        """
        ctx = setup_bound_policy(state_code="TX", premium_cents=100000)
        pay_premium(ctx["policy"]["id"], 100000)
        resp = api.create_claim(
            {
                "policy_id": ctx["policy"]["id"],
                "claimed_amount_cents": 1000,
                "fraud_score": 0.10,
            },
            make_policyholder_headers(ctx["policyholder"]["id"]),
        )
        validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST)
        claims, _ = validate_paginated(api.list_policy_claims(ctx["policy"]["id"], ADJ_1))
        assert claims == []


class TestClaimPaymentsAppendOnly:
    def test_claim_payment_carries_no_version_or_updated_at(self, api):
        """PRD §2.4: "A ClaimPayment and a PolicyLedgerEntry are append-only records: each carries an id and a created_at, but neither carries updated_at nor version."
        PRD §3.7: "a ClaimPayment is created in SETTLED status (the only alternative status being VOIDED)".

        Design: Corner/entities/claim_payment_has_no_update_endpoint
        """
        ctx = setup_bound_policy(state_code="TX", premium_cents=100000)
        pay_premium(ctx["policy"]["id"], 100000)
        claim = file_claim(ctx["policyholder"]["id"], ctx["policy"]["id"], 1000, 0.10)
        payments, _ = validate_paginated(
            api.list_claim_payments(claim["id"], make_policyholder_headers(ctx["policyholder"]["id"]))
        )
        assert len(payments) == 1
        payment = payments[0]
        assert payment["amount_cents"] == 1000
        assert payment["status"] == "SETTLED"
        assert "version" not in payment
        assert "updated_at" not in payment


class TestClaimsListing:
    def test_claims_list_paginates_with_filters(self, api):
        """PRD §2.3: "limit caps the number of items returned: it defaults to 10 when omitted, with a minimum of 1 and a maximum of 100. offset skips that many items from the front of the result set and defaults to 0." — "The meta object of a list response carries limit, offset, total_count, and has_more."
        PRD §2.3: "claims by policy_id and status (or by status alone when listing a policy's claims)".

        Design: Corner/entities/claims_list_paginates_with_filters
        """
        ctx = setup_bound_policy(state_code="TX", premium_cents=600000, coverage_amount_cents=900000)
        pay_premium(ctx["policy"]["id"], 600000)
        ph = ctx["policyholder"]
        file_claim(ph["id"], ctx["policy"]["id"], 1000, 0.10, "v1")
        file_claim(ph["id"], ctx["policy"]["id"], 2000, 0.10, "v2")
        file_claim(ph["id"], ctx["policy"]["id"], 3000, 0.90, "v3")

        data, meta = validate_paginated(
            api.list_claims(ADJ_1, params={"policy_id": ctx["policy"]["id"], "limit": 2, "offset": 0})
        )
        assert len(data) == 2
        assert meta["total_count"] == 3
        assert meta["has_more"] is True

        data2, meta2 = validate_paginated(
            api.list_claims(ADJ_1, params={"policy_id": ctx["policy"]["id"], "limit": 2, "offset": 2})
        )
        assert len(data2) == 1
        assert meta2["total_count"] == 3
        assert meta2["has_more"] is False

        paid, _ = validate_paginated(
            api.list_claims(ADJ_1, params={"policy_id": ctx["policy"]["id"], "status": "PAID"})
        )
        assert len(paid) == 2
        esc, _ = validate_paginated(
            api.list_claims(ADJ_1, params={"policy_id": ctx["policy"]["id"], "status": "ESCALATED"})
        )
        assert len(esc) == 1
