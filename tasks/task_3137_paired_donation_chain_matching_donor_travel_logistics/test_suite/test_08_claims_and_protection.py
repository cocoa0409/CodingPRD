"""Donor protection claims adjudication and policy tests."""
from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    create_center,
    create_claim_payload,
    create_donor,
    get_success_data,
    make_center_coordinator_headers,
    make_registry_admin_headers,
    reset_clock,
    setup_claim_under_review,
    setup_donor_with_policy,
    validate_error,
    validate_success,
)

ADMIN = TEST_USERS["registry_admin_headers"]


class TestClaimPolicyGate:
    def test_claim_without_policy_forbidden(self, api):
        """PRD §3.9: "Filing requires the donor to have an active protection
        policy; if the donor's `protection_policy_id` is still null
        (pre-nephrectomy) or the policy is not active, the submission is
        rejected with `ERR_NO_PROTECTION_POLICY`."

        Design: Corner/validations/claim_without_policy_forbidden
        """
        reset_clock()
        center = create_center()
        donor = create_donor(center)  # pre-nephrectomy: no policy
        resp = api.create_claim_for_donor(
            donor["id"],
            create_claim_payload(claim_kind="COMPLICATION", requested_amount_cents=100000),
            make_center_coordinator_headers(center["id"]),
        )
        validate_error(resp, ApiErrorId.ERR_NO_PROTECTION_POLICY.value)


class TestSegregationOfDuties:
    def test_segregation_of_duties_error(self, api):
        """PRD §2.9: "The user recorded at submission time as the claim's
        submitter (via a `submitter_user_id` field captured from the request
        header at submit time) may not adjudicate the same claim: an attempt by
        the same `X-User-ID` to approve, partially approve, or deny is rejected
        with `ERR_SEGREGATION_OF_DUTIES` (HTTP 403)."

        Design: Corner/errors/segregation_of_duties_error
        """
        ctx, donor, policy = setup_donor_with_policy()
        # Submit as the donor's center coordinator (the role PRD §2.2 assigns
        # claim submission to); capture that coordinator's X-User-ID.
        submitter_id = ctx["center_a"]["id"]
        coord = make_center_coordinator_headers(submitter_id)
        resp = api.create_claim_for_donor(
            donor["id"],
            create_claim_payload(claim_kind="COMPLICATION", requested_amount_cents=50000),
            coord,
        )
        claim = get_success_data(resp, expected_status=201)
        get_success_data(api.start_claim_review(claim["id"], ADMIN))
        # Same X-User-ID (but RegistryAdmin role, required for adjudication)
        # attempts to approve -> segregation violation.
        resp = api.approve_claim(
            claim["id"], make_registry_admin_headers(submitter_id)
        )
        validate_error(resp, ApiErrorId.ERR_SEGREGATION_OF_DUTIES.value)

    def test_logistics_coordinator_cannot_adjudicate_claim(self, api):
        """PRD §4: "POST | `/nkr/claims/{claim_id}/approve` | Approve a claim
        (full amount) | RegistryAdmin".
        PRD §2.1: "If the role is recognized but is not authorized for the
        endpoint per the access rules below, the server rejects with
        `ERR_UNAUTHORIZED` (HTTP 403)."

        Design: Corner/rbac/logistics_coordinator_cannot_adjudicate_claim
        """
        ctx, donor, policy, claim, adjudicator = setup_claim_under_review()
        resp = api.approve_claim(claim["id"], TEST_USERS["logistics_headers"])
        validate_error(resp, ApiErrorId.ERR_UNAUTHORIZED.value)


class TestClaimLifecycle:
    def test_claim_idempotent_approve_second_call_returns_invalid_state(self, api):
        """PRD §3.9: "**Approve** sets `approved_amount_cents` equal to
        `requested_amount_cents` and debits the matching policy bucket".
        PRD §3.9: "`PAID` and `DENIED` are terminal."
        PRD §5: "`ERR_INVALID_STATE` | 409".

        Design: Corner/state_machines/claim_idempotent_approve_second_call_returns_invalid_state
        """
        ctx, donor, policy, claim, adjudicator = setup_claim_under_review()
        approved = validate_success(api.approve_claim(claim["id"], adjudicator))
        assert approved["claim_state"] == "APPROVED"
        resp = api.approve_claim(claim["id"], adjudicator)
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE.value)

    def test_claim_terminal_state_lockdown_paid(self, api):
        """PRD §3.9: "Payment is the final step: a `RegistryAdmin` pays an
        `APPROVED` or `PARTIALLY_APPROVED` claim, moving it to `PAID`. Bucket
        updates happen at approval time; payment itself does not double-count.
        `PAID` and `DENIED` are terminal."
        PRD §5: "`ERR_INVALID_STATE` | 409".

        Design: Corner/state_machines/claim_terminal_state_lockdown_paid
        """
        ctx, donor, policy, claim, adjudicator = setup_claim_under_review()
        get_success_data(api.approve_claim(claim["id"], adjudicator))
        paid = validate_success(api.pay_claim(claim["id"], adjudicator))
        assert paid["claim_state"] == "PAID"
        resp = api.deny_claim(claim["id"], {"denial_reason": "too late"}, adjudicator)
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE.value)
        after = validate_success(api.get_claim(claim["id"], adjudicator))
        assert after["claim_state"] == "PAID"


class TestClaimBucketInvariant:
    def test_claim_approve_then_deny_reversal_conserves_bucket(self, api):
        """PRD §3.9: "**Deny** moves the claim to `DENIED` and records the
        `denial_reason`."
        PRD §3.9: "**Approve** sets `approved_amount_cents` equal to
        `requested_amount_cents` and debits the matching policy bucket" — a
        denied claim never reaches approval, so the bucket is never debited.
        PRD §3.9: "The policy tracks three paid buckets —
        `complications_paid_cents`, `lost_wages_paid_cents`, and
        `travel_reimbursed_cents` — each incremented as approved claims land in
        the corresponding kind."

        Design: Difficulty/compensating_invariant/claim_approve_then_deny_reversal_conserves_bucket
        """
        ctx, donor, policy, claim, adjudicator = setup_claim_under_review()
        assert policy["complications_paid_cents"] == 0
        denied = validate_success(
            api.deny_claim(claim["id"], {"denial_reason": "insufficient documentation"},
                           adjudicator)
        )
        assert denied["claim_state"] == "DENIED"
        policy_after = validate_success(api.get_policy(policy["id"], adjudicator))
        assert policy_after["complications_paid_cents"] == 0

    def test_claim_deny_does_not_touch_other_buckets(self, api):
        """PRD §3.9: "The policy tracks three paid buckets —
        `complications_paid_cents`, `lost_wages_paid_cents`, and
        `travel_reimbursed_cents` — each incremented as approved claims land in
        the corresponding kind."
        PRD §3.9: "**Deny** moves the claim to `DENIED` and records the
        `denial_reason`."

        Design: Difficulty/compensating_invariant/claim_approve_then_deny_reversal_conserves_bucket
        """
        ctx, donor, policy, claim, adjudicator = setup_claim_under_review()
        get_success_data(
            api.deny_claim(claim["id"], {"denial_reason": "no"}, adjudicator)
        )
        policy_after = validate_success(api.get_policy(policy["id"], adjudicator))
        assert policy_after["complications_paid_cents"] == 0
        assert policy_after["lost_wages_paid_cents"] == 0
        assert policy_after["travel_reimbursed_cents"] == 0
