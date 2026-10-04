"""Corner — calculations: deal P&A reconciliation.

Design: Corner/calculations
"""
from test_helpers import (
    TEST_USERS, acquire_film_with_premiere, get_success_data,
    setup_active_campaign, validate_success,
)

ACCT = TEST_USERS["part_acct_headers"]
DIST = TEST_USERS["dist_exec_headers"]
STRAT = TEST_USERS["awards_strat_headers"]


class TestDealPaShortfallReconciliation:
    def test_deal_pa_shortfall_reconciles_after_each_spend(self, api):
        """PRD §3.7: "`pa_shortfall_cents` is recomputed as the greater of
        zero and the difference between `prints_advertising_commit_cents` and
        the sum of `pa_spent_theatrical_cents` plus `pa_spent_awards_cents`."
        PRD §3.7: "A `DistributionExec` reports theatrical-phase spend
        directly against the deal with a single `amount_cents` payload; the
        deal's `pa_spent_theatrical_cents` accumulates the amount and
        `pa_shortfall_cents` is recomputed by the same formula."
        PRD §3.7: "The parent deal's `pa_spent_awards_cents` is recomputed as
        the sum of `amount_cents` across every campaign tied to the deal".

        Design: Corner/calculations/deal_pa_shortfall_reconciles_after_each_spend
        """
        film, offer, deal, festival, slot = acquire_film_with_premiere(
            offer_overrides={"prints_advertising_commit_cents": 5_000_000},
        )
        campaign = setup_active_campaign(
            film, deal, {"budget_total_cents": 2_000_000},
        )

        deal_1 = validate_success(api.report_theatrical_spend(
            deal["id"], {"amount_cents": 1_000_000}, DIST,
        ))
        # 5,000,000 - 1,000,000 - 0 = 4,000,000
        assert deal_1["pa_shortfall_cents"] == 4_000_000
        assert deal_1["pa_spent_theatrical_cents"] == 1_000_000

        validate_success(api.create_campaign_spend(
            campaign["id"],
            {"category": "PUBLICITY", "amount_cents": 500_000,
             "incurred_at": "2026-10-01T00:00:00Z",
             "target_category": "BEST_PICTURE"},
            STRAT,
        ), expected_status=201)

        deal_2 = get_success_data(api.get_deal(deal["id"], ACCT))
        # 5,000,000 - 1,000,000 - 500,000 = 3,500,000
        assert deal_2["pa_shortfall_cents"] == 3_500_000
        assert deal_2["pa_spent_theatrical_cents"] == 1_000_000
        assert deal_2["pa_spent_awards_cents"] == 500_000
