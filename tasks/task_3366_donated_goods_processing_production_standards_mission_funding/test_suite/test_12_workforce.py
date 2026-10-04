"""Workforce contracts: attestation segregation and gates, review cycles, the
missed-milestone sweep, and the compliance posture bands."""
from test_helpers import (
    TEST_USERS,
    ApiErrorId,
    api_client,
    attest_milestone,
    create_contract,
    create_org,
    get_milestone,
    get_org,
    list_contract_milestones,
    make_compliance_officer_headers,
    milestone_payload,
    review_action,
    validate_error,
    validate_paginated,
    validate_success,
)

ADMIN = TEST_USERS["platform_admin_headers"]


def _get_contract(org_id, contract_id) -> dict:
    rows, _meta = validate_paginated(
        api_client.list_workforce_contracts(org_id, ADMIN))
    match = [r for r in rows if r["id"] == contract_id]
    assert match, f"contract {contract_id} not found"
    return match[0]


def _setup_contract(milestones, headcount=50, name="Org W"):
    org = create_org(name)
    contract = create_contract(org["id"], milestones,
                               enrolled_headcount=headcount)
    return org, contract


TWO_FUTURE_MILESTONES = [
    milestone_payload(description="M1", target_date="2026-12-01T00:00:00Z",
                      min_headcount=40, payout_cents=50000),
    milestone_payload(description="M2", target_date="2026-12-01T00:00:00Z",
                      min_headcount=40, payout_cents=30000),
]


class TestAttestationGates:
    def test_milestone_attest_twice_returns_invalid_state(self, api):
        """PRD 3.8: "The milestone must be `PENDING` and — a cross-entity gate
        — its contract must be `ACTIVE`: attestation is frozen while the
        contract is `UNDER_REVIEW` or `CLOSED`, and any such attempt draws
        `ERR_INVALID_STATE`."
        PRD 3.8: "A successful attestation moves the milestone to `ATTESTED`,
        stamps the attester into `attested_by_user_id`, and credits the
        `payout_cents` twice in parallel — once onto the contract's
        `attested_payout_cents` and once onto the organization's
        `contract_revenue_cents`, the separate ledger of §2.8 that never
        mingles with retail margin."

        Design: Corner/state_machines/milestone_attest_twice_returns_invalid_state
        """
        org, contract = _setup_contract(TWO_FUTURE_MILESTONES, name="Org AT")
        m1, _m2 = list_contract_milestones(contract["id"])
        attested = attest_milestone(m1["id"], officer_id="co-2")
        assert attested["status"] == "ATTESTED"
        resp = api_client.attest_milestone(
            m1["id"], make_compliance_officer_headers("co-3"))
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE)
        assert get_org(org["id"])["contract_revenue_cents"] == 50000, (
            "credited exactly once")
        assert _get_contract(org["id"], contract["id"])["status"] == "ACTIVE"

    def test_contract_creator_cannot_attest_own_milestone(self, api):
        """PRD 3.8: "Duties are segregated here as well: the attester's
        `X-User-ID` must differ from the contract's `created_by_user_id`, else
        `ERR_SEGREGATION_OF_DUTIES`."

        Design: Corner/validations/contract_creator_cannot_attest_own_milestone
        """
        org, contract = _setup_contract(
            [milestone_payload(description="M1",
                               target_date="2026-12-01T00:00:00Z",
                               min_headcount=40, payout_cents=5000)],
            name="Org SoD2")
        m1 = list_contract_milestones(contract["id"])[0]
        # The ContractManager's user id presented under the ComplianceOfficer role.
        resp = api_client.attest_milestone(
            m1["id"], make_compliance_officer_headers("cm-1"))
        validate_error(resp, ApiErrorId.ERR_SEGREGATION_OF_DUTIES)
        assert get_milestone(m1["id"])["status"] == "PENDING"
        assert get_org(org["id"])["contract_revenue_cents"] == 0

    def test_headcount_shortfall_blocks_attestation(self, api):
        """PRD 3.8: "Finally the contract's `enrolled_headcount` must be at
        least the milestone's `min_headcount`; a shortfall is rejected with
        `ERR_HEADCOUNT_SHORTFALL`."

        Design: Corner/validations/headcount_shortfall_blocks_attestation
        """
        org, contract = _setup_contract(
            [milestone_payload(description="M1",
                               target_date="2026-12-01T00:00:00Z",
                               min_headcount=40, payout_cents=5000)],
            headcount=10, name="Org HC")
        m1 = list_contract_milestones(contract["id"])[0]
        resp = api_client.attest_milestone(
            m1["id"], make_compliance_officer_headers("co-2"))
        validate_error(resp, ApiErrorId.ERR_HEADCOUNT_SHORTFALL)
        assert get_milestone(m1["id"])["status"] == "PENDING"
        assert get_org(org["id"])["contract_revenue_cents"] == 0


class TestReviewCycle:
    def test_review_open_twice_returns_invalid_state(self, api):
        """PRD 3.8: "Opening a review takes an `ACTIVE` contract to
        `UNDER_REVIEW`, freezing milestone attestation for the duration."
        PRD 2.10: "State-machine preconditions for the requested transition:
        `ERR_INVALID_STATE` (HTTP 409)."

        Design: Corner/state_machines/review_open_twice_returns_invalid_state
        """
        org, contract = _setup_contract(
            [milestone_payload(description="M1",
                               target_date="2026-12-01T00:00:00Z",
                               min_headcount=10, payout_cents=25000)],
            headcount=20, name="Org RO")
        review_action(contract["id"], "OPEN", officer_id="co-1")
        resp = api_client.create_review(
            contract["id"], "OPEN", make_compliance_officer_headers("co-1"))
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE)
        assert _get_contract(org["id"], contract["id"])["status"] == "UNDER_REVIEW"

    def test_review_close_sweeps_only_overdue_milestones(self, api):
        """PRD 3.8: "Closing a review takes an `UNDER_REVIEW` contract back to
        `ACTIVE` and sweeps: every still-`PENDING` milestone whose
        `target_date` has already passed relative to the logical clock is set
        to `MISSED`, the contract's `missed_count` is recomputed, and its
        `compliance_posture` is re-derived."
        PRD 3.8: "Otherwise, if the missed count multiplied by four is strictly
        greater than the total milestone count, the posture is `BREACH` —
        strictly greater, so a contract exactly one quarter missed stays in the
        middle band."

        Design: Corner/calculations/compliance_posture_exactly_quarter_missed_stays_at_risk
        """
        milestones = [
            milestone_payload(description="M1", target_date="2026-08-01T00:00:00Z",
                              min_headcount=10, payout_cents=10000),
            milestone_payload(description="M2", target_date="2026-12-01T00:00:00Z",
                              min_headcount=10, payout_cents=10000),
            milestone_payload(description="M3", target_date="2026-12-01T00:00:00Z",
                              min_headcount=10, payout_cents=10000),
            milestone_payload(description="M4", target_date="2026-12-01T00:00:00Z",
                              min_headcount=10, payout_cents=10000),
        ]
        org, contract = _setup_contract(milestones, name="Org CP")
        review_action(contract["id"], "OPEN", officer_id="co-1")
        review_action(contract["id"], "CLOSE", officer_id="co-1")
        by_desc = {m["description"]: m["status"]
                   for m in list_contract_milestones(contract["id"])}
        assert by_desc["M1"] == "MISSED", "target 2026-08-01 < clock 2026-09-01"
        assert by_desc["M2"] == "PENDING"
        assert by_desc["M3"] == "PENDING"
        assert by_desc["M4"] == "PENDING"
        after = _get_contract(org["id"], contract["id"])
        assert after["missed_count"] == 1
        assert after["compliance_posture"] == "AT_RISK", (
            "1*4 > 4 is false: exactly a quarter missed is not BREACH")
        assert after["status"] == "ACTIVE"


class TestAttestBlockedDuringReview:
    def _setup_single_milestone_contract(self):
        org, contract = _setup_contract(
            [milestone_payload(description="M1",
                               target_date="2026-12-01T00:00:00Z",
                               min_headcount=40, payout_cents=50000)],
            headcount=50, name="Org Rev")
        m1 = list_contract_milestones(contract["id"])[0]
        return org, contract, m1

    def test_attestation_frozen_while_under_review(self, api):
        """PRD 3.8: "The milestone must be `PENDING` and — a cross-entity gate
        — its contract must be `ACTIVE`: attestation is frozen while the
        contract is `UNDER_REVIEW` or `CLOSED`, and any such attempt draws
        `ERR_INVALID_STATE`."
        PRD 3.8: "Opening a review takes an `ACTIVE` contract to
        `UNDER_REVIEW`, freezing milestone attestation for the duration."

        Design: Difficulty/cross_entity_state_dependency/milestone_attest_blocked_during_review
        """
        org, contract, m1 = self._setup_single_milestone_contract()
        review_action(contract["id"], "OPEN", officer_id="co-1")
        resp = api_client.attest_milestone(
            m1["id"], make_compliance_officer_headers("co-2"))
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE)
        assert get_milestone(m1["id"])["status"] == "PENDING"
        assert get_org(org["id"])["contract_revenue_cents"] == 0

    def test_attestation_resumes_after_review_close(self, api):
        """PRD 3.8: "Closing a review takes an `UNDER_REVIEW` contract back to
        `ACTIVE` and sweeps: every still-`PENDING` milestone whose
        `target_date` has already passed relative to the logical clock is set
        to `MISSED`, the contract's `missed_count` is recomputed, and its
        `compliance_posture` is re-derived."
        PRD 3.8: "If the attested milestone was the contract's last `PENDING`
        one, the contract automatically transitions to `CLOSED`, locking it
        against any further reviews or attestations."

        Design: Difficulty/cross_entity_state_dependency/milestone_attest_blocked_during_review
        """
        org, contract, m1 = self._setup_single_milestone_contract()
        review_action(contract["id"], "OPEN", officer_id="co-1")
        reopened = review_action(contract["id"], "CLOSE", officer_id="co-1")
        assert reopened["status"] == "ACTIVE", (
            "no overdue milestone: target 2026-12-01 is after the clock")
        attested = attest_milestone(m1["id"], officer_id="co-2")
        assert attested["status"] == "ATTESTED"
        after = _get_contract(org["id"], contract["id"])
        assert after["attested_payout_cents"] == 50000
        org_after = get_org(org["id"])
        assert org_after["contract_revenue_cents"] == 50000
        assert org_after["retail_margin_pool_cents"] == 0, "separate ledger"
        assert after["status"] == "CLOSED", "last PENDING milestone attested"


class TestReviewCycleConservesLedger:
    def _setup_one_attested_one_pending(self):
        org, contract = _setup_contract(TWO_FUTURE_MILESTONES, name="Org Led")
        m1, m2 = list_contract_milestones(contract["id"])
        attest_milestone(m1["id"], officer_id="co-2")
        review_action(contract["id"], "OPEN", officer_id="co-1")
        review_action(contract["id"], "CLOSE", officer_id="co-1")
        return org, contract, m1, m2

    def test_review_cycle_leaves_attested_ledgers_untouched(self, api):
        """PRD 3.8: "Closing a review takes an `UNDER_REVIEW` contract back to
        `ACTIVE` and sweeps: every still-`PENDING` milestone whose
        `target_date` has already passed relative to the logical clock is set
        to `MISSED`, the contract's `missed_count` is recomputed, and its
        `compliance_posture` is re-derived."
        PRD 2.8: "The second ledger, `contract_revenue_cents`, starts at zero
        and is credited only by attested government-contract milestone payouts."

        Design: Difficulty/compensating_invariant/review_cycle_conserves_attested_ledger
        """
        org, contract, _m1, _m2 = self._setup_one_attested_one_pending()
        after = _get_contract(org["id"], contract["id"])
        assert after["attested_payout_cents"] == 50000, "unchanged by the cycle"
        assert get_org(org["id"])["contract_revenue_cents"] == 50000

    def test_review_cycle_preserves_milestone_states_and_reopens(self, api):
        """PRD 3.8: "Milestones reach `MISSED` only through the review-close
        sweep, never through a direct write; `PENDING` milestones simply wait,
        against their `target_date`, for attestation or the broom."
        PRD 3.8: "Closing a review takes an `UNDER_REVIEW` contract back to
        `ACTIVE` and sweeps: every still-`PENDING` milestone whose
        `target_date` has already passed relative to the logical clock is set
        to `MISSED`, the contract's `missed_count` is recomputed, and its
        `compliance_posture` is re-derived."

        Design: Difficulty/compensating_invariant/review_cycle_conserves_attested_ledger
        """
        org, contract, m1, m2 = self._setup_one_attested_one_pending()
        assert get_milestone(m1["id"])["status"] == "ATTESTED"
        assert get_milestone(m2["id"])["status"] == "PENDING", (
            "target 2026-12-01 is after the clock: no sweep")
        after = _get_contract(org["id"], contract["id"])
        assert after["status"] == "ACTIVE", "M2 still PENDING: no auto-close"
        assert after["missed_count"] == 0
