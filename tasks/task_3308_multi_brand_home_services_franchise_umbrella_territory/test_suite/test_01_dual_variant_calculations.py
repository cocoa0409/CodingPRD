"""Dual-variant calculations: referral fee basis and royalty accrual basis."""
from test_helpers import (
    TEST_USERS,
    accept_referral,
    complete_referral,
    create_referral,
    create_statement,
    get_agreement,
    issue_statement,
    preview_statement,
    settle_referral,
    setup_two_brand_pair,
    validate_success,
)

ADMIN = TEST_USERS["franchise_admin_headers"]


class TestReferralFeeBrandPairVariant:
    def test_tiered_brand_pair_rate_replaces_the_referrals_own_rate(self, api):
        """PRD §3.5: "Under the tiered basis, which applies when the receiving
        brand's `cross_brand_fee_table` carries a key equal to the originating
        brand's `brand_code`, the fee is the settled job value multiplied by the
        rate the table gives for that key, rounded half up to a whole cent, and
        the recorded variant is `TIERED_BRAND_PAIR`."
        PRD §3.5: "The tiered table's rate replaces the referral's own rate
        entirely rather than modifying it: a referral created with a
        `referral_fee_rate` of 0.10 but receiving a brand with a table entry for
        its originator settles at the table's rate."

        Design: Difficulty/dual_variant_calc/referral_fee_brand_pair_variant_divergence
        """
        ctx = setup_two_brand_pair()
        referral = create_referral(
            ctx["agt_a1"]["id"], ctx["agt_a2"]["id"], ctx["fr_ms"]["id"],
        )
        accept_referral(referral["id"], ctx["fr_il"]["id"])
        complete_referral(referral["id"], ctx["fr_il"]["id"], 120000)

        settled = settle_referral(referral["id"], ctx["agt_a1"]["id"])

        assert settled["status"] == "SETTLED"
        assert settled["fee_variant"] == "TIERED_BRAND_PAIR"
        assert settled["referral_fee_cents"] == 18000, (
            f"the IL table's rate for MS (0.15) must price the fee at 18000, "
            f"got {settled['referral_fee_cents']}"
        )
        assert settled["referral_fee_cents"] != 12000, (
            "the referral's own referral_fee_rate of 0.10 must not be used once "
            "the receiving brand's table carries a key for the originating brand"
        )

    def test_settlement_posts_opposite_totals_to_both_agreements(self, api):
        """PRD §3.5: "On success the referral's `settled_clock_iso` is stamped,
        its status becomes `SETTLED`, and the fee is posted to both sides at
        once: the originating agreement's `cumulative_referral_net_cents` is
        increased by the fee and the receiving agreement's is decreased by the
        same fee, so that across the pair the two figures remain exactly
        opposite."

        Design: Difficulty/dual_variant_calc/referral_fee_brand_pair_variant_divergence
        """
        ctx = setup_two_brand_pair()
        referral = create_referral(
            ctx["agt_a1"]["id"], ctx["agt_a2"]["id"], ctx["fr_ms"]["id"],
        )
        accept_referral(referral["id"], ctx["fr_il"]["id"])
        complete_referral(referral["id"], ctx["fr_il"]["id"], 120000)
        settle_referral(referral["id"], ctx["agt_a1"]["id"])

        originator = get_agreement(ctx["agt_a1"]["id"])
        receiver = get_agreement(ctx["agt_a2"]["id"])

        assert originator["cumulative_referral_net_cents"] == 18000, (
            f"the originating agreement must be increased by the fee, got "
            f"{originator['cumulative_referral_net_cents']}"
        )
        assert receiver["cumulative_referral_net_cents"] == -18000, (
            f"the receiving agreement must be decreased by the fee, got "
            f"{receiver['cumulative_referral_net_cents']}"
        )
        assert (originator["cumulative_referral_net_cents"]
                + receiver["cumulative_referral_net_cents"]) == 0


class TestRoyaltyAccrualProvisionalVsFinal:
    def _draft_statement_with_settled_referral(self):
        ctx = setup_two_brand_pair(
            ms_agreement={"royalty_rate_override": 0.06},
        )
        referral = create_referral(
            ctx["agt_a1"]["id"], ctx["agt_a2"]["id"], ctx["fr_ms"]["id"],
        )
        accept_referral(referral["id"], ctx["fr_il"]["id"])
        complete_referral(referral["id"], ctx["fr_il"]["id"], 120000)
        settle_referral(referral["id"], ctx["agt_a1"]["id"])
        statement = create_statement(
            ctx["agt_a1"]["id"],
            period_start="2026-09-01T00:00:00Z",
            period_end="2026-10-01T00:00:00Z",
            gross_revenue_cents=1000000,
        )
        return ctx, statement

    def test_preview_reports_draft_proportional_without_any_netting(self, api):
        """PRD §3.10: "In the draft reading the royalty figure is the royalty
        component floored at zero, the `referral_offset_cents` is zero, and the
        `net_remittance_cents` is the royalty figure plus the fund figure, so
        the draft view carries no cross-brand netting at all."

        Design: Difficulty/dual_variant_calc/royalty_accrual_provisional_vs_final_divergence
        """
        ctx, statement = self._draft_statement_with_settled_referral()

        resp = api.preview_statement(statement["id"], ADMIN)
        preview = validate_success(resp, 200)

        assert preview["accrual_variant"] == "DRAFT_PROPORTIONAL"
        assert preview["royalty_cents"] == 60000, (
            f"1000000 * the effective royalty rate 0.06 must be 60000, got "
            f"{preview['royalty_cents']}"
        )
        assert preview["ad_fund_cents"] == 10000
        assert preview["referral_offset_cents"] == 0
        assert preview["net_remittance_cents"] == 70000, (
            f"the draft view must carry no netting, got {preview['net_remittance_cents']}"
        )

    def test_issue_switches_to_final_netted_and_applies_the_settled_offset(self, api):
        """PRD §3.10: "The `net_remittance_cents` is the royalty figure plus the
        fund figure minus the referral offset — and, unlike the draft reading,
        floored at zero after the subtraction, so a period whose offsets exceed
        the royalty and fund accruals remits nothing rather than a negative
        amount."
        PRD §3.10: "The statement's `accrual_variant` becomes `FINAL_NETTED`,
        its `issued_clock_iso` is stamped with the logical clock, and the
        agreement's `cumulative_royalty_cents` is increased by the royalty
        figure."

        Design: Difficulty/dual_variant_calc/royalty_accrual_provisional_vs_final_divergence
        """
        ctx, statement = self._draft_statement_with_settled_referral()

        preview = preview_statement(statement["id"])
        issued = issue_statement(statement["id"])

        assert issued["accrual_variant"] == "FINAL_NETTED"
        assert issued["royalty_cents"] == 60000
        assert issued["ad_fund_cents"] == 10000
        assert issued["referral_offset_cents"] == 18000, (
            f"the settled referral originating at A1 must enter the period's "
            f"offset as +18000, got {issued['referral_offset_cents']}"
        )
        assert issued["net_remittance_cents"] == 52000, (
            f"60000 + 10000 - 18000 must be 52000, got {issued['net_remittance_cents']}"
        )
        assert preview["net_remittance_cents"] - issued["net_remittance_cents"] == 18000, (
            "the two variants must differ by exactly the settled offset"
        )

    def test_issue_posts_the_royalty_figure_to_the_agreement_ledger(self, api):
        """PRD §3.10: "the agreement's `cumulative_royalty_cents` is increased
        by the royalty figure" — the ledger moves by the royalty component
        alone, never by the net remittance.

        Design: Difficulty/dual_variant_calc/royalty_accrual_provisional_vs_final_divergence
        """
        ctx, statement = self._draft_statement_with_settled_referral()
        issue_statement(statement["id"])

        agreement = get_agreement(ctx["agt_a1"]["id"])
        assert agreement["cumulative_royalty_cents"] == 60000, (
            f"the agreement's cumulative_royalty_cents must move by the royalty "
            f"figure 60000, got {agreement['cumulative_royalty_cents']}"
        )