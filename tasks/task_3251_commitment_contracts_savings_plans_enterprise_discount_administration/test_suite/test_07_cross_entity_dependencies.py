"""Tests for cross-entity state dependencies."""
from test_helpers import (
    validate_error,
    validate_success,
    api_client,
    make_admin_headers,
    create_org,
    create_active_agreement,
    create_linked_account,
    create_plan,
    ingest_usage,
    generate_invoice,
    get_invoice,
    ApiErrorId,
)

ADMIN = make_admin_headers()


class TestFinalizeGatedByAgreementLifecycle:
    """A DRAFT invoice cannot finalize once its agreement is TERMINATED."""

    def _setup(self):
        org = create_org(name="Xe Org", max_hourly_commitment_cents=100000,
                         capacity_quota_units=100)
        agr = create_active_agreement(
            org["id"],
            tiers=[{"service_family": "COMPUTE", "threshold_cents": 0, "rate": 0.10}],
            committed_spend_cents=1000000,
        )
        acct = create_linked_account(org["id"], name="acct-1", external_ref="ext-1")
        ingest_usage(acct["id"], usage_hour_start="2026-09-01T00:00:00Z",
                     list_price_cents=10000)
        inv = generate_invoice(org["id"], period_index=0)
        validate_success(api_client.terminate_agreement(agr["id"], ADMIN))
        return org, agr, acct, inv

    def test_finalize_rejected_when_agreement_terminated(self, api):
        """PRD section 3.7: "Finalization has one cross-entity gate: if the
        invoice's `agreement_id` is non-null, that agreement's lifecycle must be
        `ACTIVE` or `EXPIRED`; finalizing against an agreement in any other
        lifecycle state is rejected with `ERR_AGREEMENT_NOT_ACTIVE`."

        Design: Difficulty/cross_entity_state_dependency/invoice_finalize_gated_by_agreement_lifecycle_state
        """
        _, _, _, inv = self._setup()
        resp = api.finalize_invoice(inv["id"], ADMIN)
        validate_error(resp, ApiErrorId.ERR_AGREEMENT_NOT_ACTIVE)
        assert resp.status_code == 409

    def test_invoice_remains_draft_after_rejected_finalize(self, api):
        """PRD section 3.7: "Finalization has one cross-entity gate: if the
        invoice's `agreement_id` is non-null, that agreement's lifecycle must be
        `ACTIVE` or `EXPIRED`; finalizing against an agreement in any other
        lifecycle state is rejected with `ERR_AGREEMENT_NOT_ACTIVE`."

        Design: Difficulty/cross_entity_state_dependency/invoice_finalize_gated_by_agreement_lifecycle_state
        """
        _, _, _, inv = self._setup()
        validate_error(api.finalize_invoice(inv["id"], ADMIN),
                       ApiErrorId.ERR_AGREEMENT_NOT_ACTIVE)
        assert get_invoice(inv["id"])["status"] == "DRAFT"


class TestPlanTerminationBlockedByDraftInvoice:
    """Plan terminate rejected while any org invoice is DRAFT."""

    def _setup(self):
        org = create_org(name="Xp Org", max_hourly_commitment_cents=100000,
                         capacity_quota_units=100)
        agr = create_active_agreement(
            org["id"],
            tiers=[{"service_family": "COMPUTE", "threshold_cents": 0, "rate": 0.10}],
            committed_spend_cents=1000000,
        )
        plan = create_plan(
            org["id"], agr["id"], type="SAVINGS_PLAN", instance_family="COMPUTE",
            units=0, hourly_commitment_cents=100, plan_discount_rate=0.30,
            term_start="2026-09-01T00:00:00Z", term_end="2026-12-01T00:00:00Z",
        )
        acct = create_linked_account(org["id"], name="acct-1", external_ref="ext-1")
        ingest_usage(acct["id"], usage_hour_start="2026-09-01T00:00:00Z",
                     list_price_cents=5000)
        inv = generate_invoice(org["id"], period_index=0)
        return org, agr, plan, acct, inv

    def test_terminate_rejected_while_draft_invoice_exists(self, api):
        """PRD section 3.4: "An `OrgAdmin` may terminate it early, but only while
        the org has no invoice in `DRAFT` — terminating against an open draft is
        rejected with `ERR_INVOICE_DRAFT_BLOCKS_TERMINATION` (HTTP 409)."

        Design: Difficulty/cross_entity_state_dependency/plan_termination_blocked_by_org_draft_invoice
        """
        _, _, plan, _, inv = self._setup()
        resp = api.terminate_commitment_plan(plan["id"], ADMIN)
        validate_error(resp, ApiErrorId.ERR_INVOICE_DRAFT_BLOCKS_TERMINATION)
        assert resp.status_code == 409

    def test_terminate_succeeds_after_invoice_voided(self, api):
        """PRD section 3.9: "A `DRAFT` invoice may instead be voided, moving it to
        `VOIDED`; voiding releases every usage record billed into it back to
        `INGESTED` with `invoice_id` cleared to null, which makes the period
        billable again."
        PRD section 3.4: "An `OrgAdmin` may terminate it early, but only while
        the org has no invoice in `DRAFT` — terminating against an open draft is
        rejected with `ERR_INVOICE_DRAFT_BLOCKS_TERMINATION` (HTTP 409)."

        Design: Difficulty/cross_entity_state_dependency/plan_termination_blocked_by_org_draft_invoice
        """
        _, _, plan, _, inv = self._setup()
        validate_error(api.terminate_commitment_plan(plan["id"], ADMIN),
                       ApiErrorId.ERR_INVOICE_DRAFT_BLOCKS_TERMINATION)
        validate_success(api.void_invoice(inv["id"], ADMIN))
        data = validate_success(api.terminate_commitment_plan(plan["id"], ADMIN))
        assert data["status"] == "TERMINATED"
