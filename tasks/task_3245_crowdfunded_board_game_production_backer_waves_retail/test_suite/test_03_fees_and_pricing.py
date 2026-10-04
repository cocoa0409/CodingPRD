"""Pledge pricing, campaign fee reconciliation, and charge/refund flows."""
from test_helpers import (
    TEST_USERS,
    ApiErrorId,
    charge_pledge,
    create_pledge,
    get_campaign,
    refund_pledge,
    set_clock,
    setup_closed_success_campaign,
    setup_live_campaign,
    validate_error,
    validate_success,
)

OWNER = TEST_USERS["campaign_owner_headers"]
ADMIN = TEST_USERS["platform_admin_headers"]

LATE_LEVEL = [
    {
        "name": "L",
        "price_cents": 995,
        "contents": ["b"],
        "quantity_cap": None,
        "late_pledge_premium_pct": 0.10,
        "status": "OPEN",
    }
]
LATE_ADDONS = [
    {"sku": "X", "price_cents": 435, "per_backer_cap": 5, "status": "OPEN"}
]


class TestPledgePricing:
    def test_pledge_total_per_line_rounding_then_sum(self, api):
        """PRD §3.3: "A pledge's `pledge_total_cents` is computed line by
        line, each line rounded half-up to integer cents before any
        summation."
        PRD §3.3: "Summing first and rounding once is explicitly wrong."
        PRD §3.3: "The level line is the level's `price_cents` multiplied by
        one plus the `late_pledge_premium_pct` when `is_late_pledge` is true
        ... Each add-on line is the catalog entry's `price_cents` multiplied
        by the line's `quantity`, multiplied by the same premium factor,
        rounded half-up, taken in array order."
        PRD §3.3: "The optional `is_late_pledge` flag defaults to false and
        may only be true when pledging after `closes_at` against a campaign
        in `CLOSED_SUCCESS`."

        Level 995c at premium 0.10: round_half_up(995*1.10)=1095.
        Add-on 435c x1: round_half_up(435*1.10)=479. Total = 1574.

        Design: Difficulty/combinatorial_formula/pledge_total_per_line_rounding_then_sum
        """
        campaign = setup_closed_success_campaign(
            goal_cents=1, pledge_levels=LATE_LEVEL, add_on_catalog=LATE_ADDONS
        )
        pledge = create_pledge(
            campaign["id"],
            backer_user_id="b9",
            backer_email="b9@x",
            is_late_pledge=True,
            add_on_lines=[{"sku": "X", "quantity": 1}],
        )
        assert pledge["pledge_total_cents"] == 1574, (
            f"per-line rounding: expected 1574, got {pledge['pledge_total_cents']}"
        )

    def test_pledge_total_per_line_rounding_with_quantity(self, api):
        """PRD §3.3: "Each add-on line is the catalog entry's `price_cents`
        multiplied by the line's `quantity`, multiplied by the same premium
        factor, rounded half-up, taken in array order. The pledge total is
        the level line plus the sum of the add-on lines."

        Late pledge: level line round_half_up(995*1.10)=1095; add-on line
        round_half_up(435*2*1.10)=957; total 2052.

        Design: Difficulty/combinatorial_formula/pledge_total_per_line_rounding_then_sum
        """
        campaign = setup_closed_success_campaign(
            goal_cents=1, pledge_levels=LATE_LEVEL, add_on_catalog=LATE_ADDONS
        )
        pledge = create_pledge(
            campaign["id"],
            backer_user_id="b9",
            backer_email="b9@x",
            is_late_pledge=True,
            add_on_lines=[{"sku": "X", "quantity": 2}],
        )
        assert pledge["pledge_total_cents"] == 2052


class TestCampaignFeeEvaluationOrder:
    def test_campaign_net_payable_evaluation_order(self, api):
        """PRD §2.9: "first `gross_charged_cents` is recomputed from charged
        pledges; then `platform_fee_cents` is computed from the gross (never
        from the net); then `payment_fee_cents` from the charged pledges;
        then `customs_duty_paid_cents` from duty-paid shipments; and finally
        `net_payable_cents` is the gross minus the platform fee, minus the
        payment fee, minus customs duty paid."
        PRD §2.9 implies the tiered average-rate platform fee; at
        gross=2,000,000c the tier-2 rate of 0.06 applies (fee 120,000c) and
        the per-pledge payment fee is round(2,000,000*0.029)+30 = 58,030c,
        so net = 1,821,970c.

        Design: Difficulty/combinatorial_formula/campaign_net_payable_evaluation_order
        """
        campaign = setup_live_campaign(
            pledge_levels=[
                {
                    "name": "Big",
                    "price_cents": 2_000_000,
                    "contents": ["d"],
                    "quantity_cap": None,
                    "late_pledge_premium_pct": 0.0,
                    "status": "OPEN",
                }
            ],
        )
        pledge = create_pledge(
            campaign["id"],
            backer_user_id="b1",
            backer_email="b1@x",
            pledge_level_name="Big",
        )
        charge_pledge(pledge["id"])
        data = get_campaign(campaign["id"])
        assert data["gross_charged_cents"] == 2_000_000
        assert data["platform_fee_cents"] == 120_000
        assert data["payment_fee_cents"] == 58_030
        assert data["net_payable_cents"] == 1_821_970

    def test_platform_fee_tier_boundary_average_rate(self, api):
        """PRD §2.9: "`platform_fee_cents` is computed from the gross (never
        from the net)". The average-rate tier rule selects a single rate from
        the whole gross: a gross of exactly 1,000,000c lands in the second
        tier (rate 0.06 → fee 60,000c), while a gross one cent below uses the
        first tier (rate 0.08 → fee 80,000c).

        Design: Corner/calculations/platform_fee_tier_boundary_average_rate
        """
        # Campaign A: single 1,000,000c pledge (== tier-2 threshold).
        campaign_a = setup_live_campaign(
            goal_cents=1,
            pledge_levels=[
                {
                    "name": "L",
                    "price_cents": 1_000_000,
                    "contents": ["b"],
                    "quantity_cap": None,
                    "late_pledge_premium_pct": 0.0,
                    "status": "OPEN",
                }
            ],
        )
        pledge_a = create_pledge(
            campaign_a["id"], backer_user_id="ba", backer_email="ba@x"
        )
        charge_pledge(pledge_a["id"])
        # Campaign B: single 999,999c pledge (just below threshold).
        campaign_b = setup_live_campaign(
            goal_cents=1,
            pledge_levels=[
                {
                    "name": "L",
                    "price_cents": 999_999,
                    "contents": ["b"],
                    "quantity_cap": None,
                    "late_pledge_premium_pct": 0.0,
                    "status": "OPEN",
                }
            ],
        )
        pledge_b = create_pledge(
            campaign_b["id"], backer_user_id="bb", backer_email="bb@x"
        )
        charge_pledge(pledge_b["id"])
        assert get_campaign(campaign_a["id"])["platform_fee_cents"] == 60_000
        assert get_campaign(campaign_b["id"])["platform_fee_cents"] == 80_000


    def test_net_payable_reconciles_after_refund(self, api):
        """PRD §2.9: "finally `net_payable_cents` is the gross minus the
        platform fee, minus the payment fee, minus customs duty paid."
        PRD §3.3: "The refund subtracts the pledge's total from
        `gross_charged_cents`, decrements `total_backers_charged`, recomputes
        fees and net payable".

        One 2,000,000c pledge charged then refunded: every aggregate returns
        to zero under the pinned evaluation order.

        Design: Difficulty/combinatorial_formula/campaign_net_payable_evaluation_order
        """
        campaign = setup_live_campaign(
            pledge_levels=[
                {
                    "name": "Big",
                    "price_cents": 2_000_000,
                    "contents": ["d"],
                    "quantity_cap": None,
                    "late_pledge_premium_pct": 0.0,
                    "status": "OPEN",
                }
            ],
        )
        pledge = create_pledge(
            campaign["id"],
            backer_user_id="b1",
            backer_email="b1@x",
            pledge_level_name="Big",
        )
        charge_pledge(pledge["id"])
        refund_pledge(pledge["id"])
        data = get_campaign(campaign["id"])
        assert data["gross_charged_cents"] == 0
        assert data["platform_fee_cents"] == 0
        assert data["payment_fee_cents"] == 0
        assert data["net_payable_cents"] == 0
        assert data["total_backers_charged"] == 0


class TestChargeOutcomes:
    def test_charge_failed_contributes_zero_to_gross(self, api):
        """PRD §3.3: "When the same action carries `payment_outcome`
        `FAILED`, the pledge instead moves `PENDING → CHARGE_FAILED` with no
        campaign effect".
        PRD §2.9: "`gross_charged_cents`, the sum of `pledge_total_cents`
        over pledges whose `charge_status` is `CHARGED`".

        Design: Corner/calculations/charge_failed_contributes_zero_to_gross
        """
        campaign = setup_live_campaign()
        pledge = create_pledge(
            campaign["id"], backer_user_id="b1", backer_email="b1@x"
        )
        charge_pledge(pledge["id"], payment_outcome="FAILED")
        resp = api.get_pledge(pledge["id"], ADMIN)
        assert validate_success(resp)["charge_status"] == "CHARGE_FAILED"
        data = get_campaign(campaign["id"])
        assert data["gross_charged_cents"] == 0
        assert data["total_backers_charged"] == 0

    def test_charge_immediately_visible_on_campaign(self, api):
        """PRD §3.3: "A successful charge adds the pledge's total to
        `gross_charged_cents`, increments `total_backers_charged`, recomputes
        both fees and the net payable, increments the campaign's `version`".

        Design: Corner/consistency_model/charge_immediately_visible_on_campaign
        """
        campaign = setup_live_campaign()
        pledge = create_pledge(
            campaign["id"], backer_user_id="b1", backer_email="b1@x"
        )
        resp = api.transition_pledge(pledge["id"], {"action": "charge"}, OWNER)
        assert validate_success(resp)["charge_status"] == "CHARGED"
        data = get_campaign(campaign["id"])
        assert data["gross_charged_cents"] == 5000
        assert data["total_backers_charged"] == 1

    def test_state_priority_beats_level_capacity(self, api):
        """PRD §2.5: "Earlier checks mask later ones: a request failing an
        earlier check is rejected with that check's error even if it would
        also fail a later check." Item 5 is the target resource's from-state
        (`ERR_INVALID_STATE`); item 12 is pledge-level capacity
        (`ERR_LEVEL_CAPACITY_EXCEEDED`).
        PRD §3.3: "Charging requires the pledge to be `PENDING` (otherwise
        `ERR_INVALID_STATE`)".

        Design: Corner/validations/state_priority_beats_level_capacity
        """
        campaign = setup_live_campaign(
            goal_cents=1,
            pledge_levels=[
                {
                    "name": "L",
                    "price_cents": 5000,
                    "contents": ["b"],
                    "quantity_cap": 2,
                    "late_pledge_premium_pct": 0.0,
                    "status": "OPEN",
                }
            ],
        )
        p1 = create_pledge(campaign["id"], backer_user_id="b1", backer_email="b1@x")
        charge_pledge(p1["id"])
        p2 = create_pledge(campaign["id"], backer_user_id="b2", backer_email="b2@x")
        charge_pledge(p2["id"])
        # Level is now at cap AND p1 is already CHARGED; state must win.
        resp = api.transition_pledge(p1["id"], {"action": "charge"}, OWNER)
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE)
