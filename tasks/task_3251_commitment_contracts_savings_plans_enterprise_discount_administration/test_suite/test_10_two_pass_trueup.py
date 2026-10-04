"""Tests for the pinned two-pass marketplace weighting in the shortfall true-up."""
from test_helpers import (
    validate_success,
    api_client,
    make_admin_headers,
    create_org,
    create_active_agreement,
    create_linked_account,
    ingest_usage,
    generate_invoice,
    period_close,
    set_clock,
    get_agreement,
)

ADMIN = make_admin_headers()


class TestTwoPassMarketplaceWeighting:
    """Tier selection at pass 1 decides the marketplace weight of pass 2."""

    def _setup(self):
        org = create_org(name="Tp Org", max_hourly_commitment_cents=100000,
                         capacity_quota_units=100)
        agr = create_active_agreement(
            org["id"],
            tiers=[{"service_family": "COMPUTE", "threshold_cents": 0, "rate": 0.10},
                   {"service_family": "COMPUTE", "threshold_cents": 400000, "rate": 0.25}],
            committed_spend_cents=1000000,
            term_start="2026-09-01T00:00:00Z", term_end="2026-10-01T00:00:00Z",
        )
        acct = create_linked_account(org["id"], name="a1", external_ref="e1")
        ingest_usage(acct["id"], usage_hour_start="2026-09-01T00:00:00Z",
                     list_price_cents=300000)
        ingest_usage(acct["id"], usage_hour_start="2026-09-01T01:00:00Z",
                     list_price_cents=200000, is_marketplace=True)
        generate_invoice(org["id"], period_index=0)
        set_clock("2026-10-01T00:00:00Z")
        period_close(org["id"])
        return org, agr, acct

    def test_pass1_boundary_qualifies_top_tier(self, api):
        """PRD section 3.8: "Pass 1 computes consumed spend as the sum of
        `list_price_cents` over eligible non-marketplace usage in the agreement's
        covered families across the term, plus half of the marketplace
        `list_price_cents` — the base marketplace weight is one half, and each
        marketplace record's weighted contribution is truncated down to integer
        cents before summation. Tier selection then finds the highest discount
        tier anywhere on the agreement whose `threshold_cents` is at or below the
        pass-1 consumed value, again with the inclusive boundary."

        Design: Difficulty/combinatorial_formula_two_pass/trueup_two_pass_marketplace_weight_top_tier_double_counts
        """
        _, agr, _ = self._setup()
        resp = api.assess_trueup({"agreement_id": agr["id"]}, ADMIN)
        data = validate_success(resp, expected_status=201)
        # pass 1: 300000 + floor(200000 * 0.5) = 400000 == top threshold (>=
        # qualifies) -> pass 2 weight 1.0 -> consumed_2 = 500000
        assert data["amount_cents"] == 500000, (
            f"shortfall = 1000000 - 500000 = 500000, got {data['amount_cents']}"
        )

    def test_single_pass_interpretation_would_overstate_shortfall(self, api):
        """PRD section 3.8: "Pass 2 re-weights marketplace: if the selected tier
        is the agreement's highest-threshold tier, marketplace usage counts at
        full weight; otherwise it stays at the base half weight. The shortfall is
        the amount by which `committed_spend_cents` exceeds the pass-2 consumed
        value, floored at zero."
        PRD section 3.6: "Generation also advances the agreement's
        `consumed_commitment_cents` by the period's eligible spend, using the
        pass-1 marketplace weighting of §3.8."

        Design: Difficulty/combinatorial_formula_two_pass/trueup_two_pass_marketplace_weight_top_tier_double_counts
        """
        _, agr, _ = self._setup()
        # running consumed uses the pass-1 weight: 300000 + 100000 = 400000
        agr_after = get_agreement(agr["id"])
        assert agr_after["consumed_commitment_cents"] == 400000
        resp = api.assess_trueup({"agreement_id": agr["id"]}, ADMIN)
        data = validate_success(resp, expected_status=201)
        assert data["type"] == "SHORTFALL"
        assert data["amount_cents"] != 600000, (
            "a single-pass half-weight interpretation would give 1000000 - 400000 "
            "= 600000; the pinned two-pass order gives 500000"
        )
        assert data["amount_cents"] == 500000
