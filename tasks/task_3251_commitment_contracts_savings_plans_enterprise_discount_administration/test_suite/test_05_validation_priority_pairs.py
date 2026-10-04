"""Tests for priority-pair validation conflicts (PRD section 2.6 ordering)."""
from test_helpers import (
    validate_error,
    validate_paginated,
    validate_success,
    api_client,
    make_admin_headers,
    make_finance_headers,
    create_org,
    create_active_agreement,
    add_tier,
    get_agreement,
    ApiErrorId,
)

ADMIN = make_admin_headers()
FINANCE = make_finance_headers()


class TestStateGatePrecedesFiscalCeiling:
    """p5 agreement-state gate must win over p9 fiscal ceiling."""

    def test_suspended_agreement_rejects_before_ceiling_checked(self, api):
        """PRD section 2.6: "This ordering is observable: a request that violates
        both a state gate and a fiscal ceiling must surface the state-gate error."
        PRD section 3.4: "The scoped agreement's lifecycle gates first: if the
        agreement is `SUSPENDED` the purchase fails with `ERR_AGREEMENT_SUSPENDED`
        (HTTP 409), and if it is in any other non-`ACTIVE` state (`NEGOTIATION`,
        `EXPIRED`, or `TERMINATED`) it fails with `ERR_AGREEMENT_NOT_ACTIVE`. This
        state check precedes the fiscal checks."

        Design: Difficulty/priority_pair_validation_conflict/plan_purchase_state_gate_precedes_fiscal_ceiling
        """
        org = create_org(name="Pv Org", max_hourly_commitment_cents=50,
                         capacity_quota_units=100)
        agr = create_active_agreement(
            org["id"],
            tiers=[{"service_family": "COMPUTE", "threshold_cents": 0, "rate": 0.10}],
            committed_spend_cents=1000000,
        )
        validate_success(api.suspend_agreement(agr["id"], ADMIN))
        resp = api.create_commitment_plan(
            {
                "org_id": org["id"], "agreement_id": agr["id"],
                "type": "SAVINGS_PLAN", "instance_family": "COMPUTE", "units": 0,
                "hourly_commitment_cents": 100, "plan_discount_rate": 0.30,
                "term_start": "2026-09-01T00:00:00Z",
                "term_end": "2026-10-01T00:00:00Z",
            },
            ADMIN,
        )
        err = validate_error(resp, ApiErrorId.ERR_AGREEMENT_SUSPENDED)
        assert resp.status_code == 409

    def test_rejected_purchase_creates_no_plan(self, api):
        """PRD section 3.4: "Finally, the fiscal ceiling: the sum of
        `hourly_commitment_cents` over the org's `ACTIVE` plans plus the new
        plan's commitment must not exceed `max_hourly_commitment_cents`, else
        `ERR_COMMITMENT_CEILING_EXCEEDED` (HTTP 422)."

        Design: Difficulty/priority_pair_validation_conflict/plan_purchase_state_gate_precedes_fiscal_ceiling
        """
        org = create_org(name="Pv Org", max_hourly_commitment_cents=50,
                         capacity_quota_units=100)
        agr = create_active_agreement(
            org["id"],
            tiers=[{"service_family": "COMPUTE", "threshold_cents": 0, "rate": 0.10}],
            committed_spend_cents=1000000,
        )
        validate_success(api.suspend_agreement(agr["id"], ADMIN))
        resp = api.create_commitment_plan(
            {
                "org_id": org["id"], "agreement_id": agr["id"],
                "type": "SAVINGS_PLAN", "instance_family": "COMPUTE", "units": 0,
                "hourly_commitment_cents": 100, "plan_discount_rate": 0.30,
                "term_start": "2026-09-01T00:00:00Z",
                "term_end": "2026-10-01T00:00:00Z",
            },
            ADMIN,
        )
        err = validate_error(resp, ApiErrorId.ERR_AGREEMENT_SUSPENDED)
        assert err["error_id"] != ApiErrorId.ERR_COMMITMENT_CEILING_EXCEEDED, (
            "hourly 100 > ceiling 50 also violates the fiscal check, but the "
            "state gate (p5) must surface, not the fiscal check (p9)"
        )
        plans, meta = validate_paginated(
            api.list_commitment_plans(ADMIN, params={"org_id": org["id"]})
        )
        assert plans == [], "no CommitmentPlan may be created by the rejected call"


class TestAmendmentTemporalPrecedesReferential:
    """p6 temporal out-of-term must win over p7 family coverage."""

    def _setup(self):
        org = create_org(name="Ov Org", max_hourly_commitment_cents=100000,
                         capacity_quota_units=100)
        agr = create_active_agreement(
            org["id"],
            tiers=[{"service_family": "COMPUTE", "threshold_cents": 0, "rate": 0.10}],
            committed_spend_cents=1000000,
        )
        return org, agr

    def test_out_of_term_window_wins_over_uncovered_family(self, api):
        """PRD section 2.6: "When several checks apply to one request, they are
        evaluated in a fixed priority order, and the first failure determines the
        rejection."
        PRD section 3.3: "The window must lie entirely within the agreement's
        term — an amendment whose window falls outside it is rejected with
        `ERR_AMENDMENT_OUT_OF_TERM`."

        Design: Difficulty/priority_pair_validation_conflict/amendment_temporal_out_of_term_precedes_referential_family_coverage
        """
        _, agr = self._setup()
        version = get_agreement(agr["id"])["version"]
        resp = api.create_pricing_amendment(
            {
                "agreement_id": agr["id"], "service_family": "UNKNOWN_SVC",
                "discount_rate": 0.20,
                "effective_from": "2028-01-01T00:00:00Z",
                "effective_to": "2028-02-01T00:00:00Z",
                "expected_agreement_version": version,
            },
            FINANCE,
        )
        err = validate_error(resp, ApiErrorId.ERR_AMENDMENT_OUT_OF_TERM)
        assert resp.status_code == 422

    def test_out_of_term_error_is_not_family_coverage_error(self, api):
        """PRD section 3.3: "The amendment's service family must also be covered
        by at least one discount tier of the agreement, else
        `ERR_SERVICE_FAMILY_NOT_COVERED`."
        PRD section 2.6: "Only after those three gates does the server examine
        whether the target resource's current state permits the transition
        (`ERR_INVALID_STATE_TRANSITION`, 409), then cross-entity state gates such
        as suspended accounts and non-active agreements (409), then
        temporal-window checks (422), then referential coverage of service
        families (422), then structural constraints such as tier ordering,
        duplicate usage, and capacity quotas (422), and only then fiscal checks
        such as commitment ceilings and settlement amounts (422)."

        Design: Difficulty/priority_pair_validation_conflict/amendment_temporal_out_of_term_precedes_referential_family_coverage
        """
        _, agr = self._setup()
        version = get_agreement(agr["id"])["version"]
        resp = api.create_pricing_amendment(
            {
                "agreement_id": agr["id"], "service_family": "UNKNOWN_SVC",
                "discount_rate": 0.20,
                "effective_from": "2028-01-01T00:00:00Z",
                "effective_to": "2028-02-01T00:00:00Z",
                "expected_agreement_version": version,
            },
            FINANCE,
        )
        err = validate_error(resp, ApiErrorId.ERR_AMENDMENT_OUT_OF_TERM)
        assert err["error_id"] != ApiErrorId.ERR_SERVICE_FAMILY_NOT_COVERED, (
            "UNKNOWN_SVC has no tier (referential violation) but the temporal "
            "check (p6) precedes the referential check (p7)"
        )
