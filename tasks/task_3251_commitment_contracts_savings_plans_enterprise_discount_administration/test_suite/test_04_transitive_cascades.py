"""Tests for transitive cascades: agreement termination and invoice finalize."""
from test_helpers import (
    validate_success,
    api_client,
    make_admin_headers,
    make_platform_headers,
    create_org,
    create_active_agreement,
    create_linked_account,
    create_plan,
    create_grant,
    set_clock,
    generate_invoice,
    ingest_usage,
    setup_draft_invoice,
    get_agreement,
    get_credit_grant,
    assert_credit_conservation,
)

ADMIN = make_admin_headers()
PLATFORM = make_platform_headers()


class TestAgreementTerminateCascade:
    """Depth-3 cascade: agreement -> plans -> true-up charges -> accrual."""

    def _setup(self):
        org = create_org(name="Cas Org", max_hourly_commitment_cents=100000,
                         capacity_quota_units=100)
        agr = create_active_agreement(
            org["id"],
            tiers=[{"service_family": "COMPUTE", "threshold_cents": 0, "rate": 0.10}],
            committed_spend_cents=1000000,
        )
        p1 = create_plan(
            org["id"], agr["id"], type="SAVINGS_PLAN", instance_family="COMPUTE",
            units=0, hourly_commitment_cents=100, plan_discount_rate=0.30,
            term_start="2026-09-01T00:00:00Z", term_end="2026-09-03T00:00:00Z",
        )
        p2 = create_plan(
            org["id"], agr["id"], type="SAVINGS_PLAN", instance_family="COMPUTE",
            units=0, hourly_commitment_cents=100, plan_discount_rate=0.30,
            term_start="2026-09-01T00:00:00Z", term_end="2026-09-04T00:00:00Z",
        )
        set_clock("2026-09-02T12:00:00Z")
        return org, agr, p1, p2

    def test_terminate_cascades_plans_and_spawns_early_termination_charges(self, api):
        """PRD section 3.11: "First, every commitment plan scoped to the agreement
        that is still `ACTIVE` moves to `TERMINATED`. Second, each plan terminated
        in the first step spawns an `EARLY_TERMINATION` true-up charge in
        `ASSESSED` status, with `plan_id` set and the penalty amount computed per
        the early-termination rule of §3.4."

        Design: Difficulty/transitive_cascade/agreement_terminate_cascades_plans_then_trueups_then_accrual
        """
        org, agr, p1, p2 = self._setup()
        validate_success(api.terminate_agreement(agr["id"], ADMIN))

        for plan in (p1, p2):
            refreshed = validate_success(api.get_commitment_plan(plan["id"], ADMIN))
            assert refreshed["status"] == "TERMINATED"

        t1 = api.list_trueup_charges(ADMIN, params={"plan_id": p1["id"]}).json()["data"]
        t2 = api.list_trueup_charges(ADMIN, params={"plan_id": p2["id"]}).json()["data"]
        assert len(t1) == 1 and len(t2) == 1
        assert t1[0]["type"] == "EARLY_TERMINATION"
        assert t1[0]["status"] == "ASSESSED"
        assert t1[0]["amount_cents"] == 600, (
            f"0.5 * 100 * 12 remaining hours = 600, got {t1[0]['amount_cents']}"
        )
        assert t2[0]["amount_cents"] == 1800, (
            f"0.5 * 100 * 36 remaining hours = 1800, got {t2[0]['amount_cents']}"
        )

    def test_cascade_recomputes_agreement_accrued_trueup(self, api):
        """PRD section 3.11: "Third, the agreement's `accrued_trueup_cents` is
        recomputed over the now-larger set of non-waived charges."
        PRD section 3.4: "The penalty amount is half of the remaining hourly
        commitment over the remaining hours: take the whole hours between the
        logical clock and the plan's `term_end` (zero if the clock has already
        passed `term_end`), multiply by `hourly_commitment_cents`, multiply by one
        half, and round half-up to integer cents."

        Design: Difficulty/transitive_cascade/agreement_terminate_cascades_plans_then_trueups_then_accrual
        """
        org, agr, p1, p2 = self._setup()
        data = validate_success(api.terminate_agreement(agr["id"], ADMIN))
        assert data["accrued_trueup_cents"] == 2400, (
            f"600 + 1800 = 2400, got {data['accrued_trueup_cents']}"
        )
        refreshed = get_agreement(agr["id"])
        assert refreshed["accrued_trueup_cents"] == 2400


class TestInvoiceFinalizeCreditCascade:
    """Depth-3 cascade: finalize -> credit debits -> exhaustion -> org pool."""

    def _setup(self):
        org = create_org(name="Cr Org", max_hourly_commitment_cents=100000,
                         capacity_quota_units=100)
        acct = create_linked_account(org["id"], name="acct-1", external_ref="ext-1")
        g1 = create_grant(org["id"], amount_cents=2000,
                          expires_at="2026-10-01T00:00:00Z")
        g2 = create_grant(org["id"], amount_cents=1500,
                          expires_at="2026-09-15T00:00:00Z")
        g3 = create_grant(org["id"], amount_cents=4000,
                          expires_at="2026-10-01T00:00:00Z")
        inv = setup_draft_invoice(org["id"], acct["id"], 5000)
        return org, acct, inv, g1, g2, g3

    def test_finalize_debits_grants_in_expiry_order(self, api):
        """PRD section 3.7: "Grants are walked in `expires_at` ascending order
        with ties broken by `created_at` ascending, each debited by the smaller of
        its `remaining_cents` and the outstanding pool, until the pool is
        exhausted."

        Design: Difficulty/transitive_cascade/invoice_finalize_cascades_credit_debits_exhaustion_and_org_pool
        """
        org, _, inv, g1, g2, g3 = self._setup()
        data = validate_success(api.finalize_invoice(inv["id"], ADMIN))
        assert data["total_credit_applied_cents"] == 5000

        g2_after = get_credit_grant(g2["id"])
        g1_after = get_credit_grant(g1["id"])
        g3_after = get_credit_grant(g3["id"])
        assert g2_after["status"] == "EXHAUSTED"
        assert g2_after["consumed_cents"] == 1500
        assert g1_after["status"] == "EXHAUSTED"
        assert g1_after["consumed_cents"] == 2000
        assert g3_after["status"] == "DEPLETING"
        assert g3_after["consumed_cents"] == 1500
        assert g3_after["remaining_cents"] == 2500

    def test_finalize_recomputes_org_unapplied_credit_pool(self, api):
        """PRD section 3.7: "The debit happens at finalize, not at generation:
        when a `DRAFT` invoice is finalized, the cascade debits each grant in that
        order; a grant debited down to exactly zero remaining moves to `EXHAUSTED`
        (whether from `ISSUED` or `DEPLETING`), a partially debited `ISSUED` grant
        moves to `DEPLETING`, and every such transition recomputes
        `unapplied_credit_cents`."

        Design: Difficulty/transitive_cascade/invoice_finalize_cascades_credit_debits_exhaustion_and_org_pool
        """
        org, _, inv, g1, g2, g3 = self._setup()
        validate_success(api.finalize_invoice(inv["id"], ADMIN))
        org_after = validate_success(api.get_billing_org(org["id"], ADMIN))
        assert org_after["unapplied_credit_cents"] == 2500, (
            f"only g3 retains 2500 of unapplied credit, "
            f"got {org_after['unapplied_credit_cents']}"
        )
        for g in (g1, g2, g3):
            assert_credit_conservation(get_credit_grant(g["id"]))
