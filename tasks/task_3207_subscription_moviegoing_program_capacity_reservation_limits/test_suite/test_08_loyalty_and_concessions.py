"""Loyalty points, concession discounts, and pinned evaluation order."""
from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    create_active_member,
    create_confirmed_reservation,
    create_published_plan,
    create_theater_with_auditorium,
    enroll_member,
    get_success_data,
    make_member_headers,
    record_concession_purchase,
    set_clock,
    setup_theater_with_on_sale_showtime,
    validate_paginated,
    validate_success,
)

ADMIN = TEST_USERS["program_admin_headers"]
SERVICES = TEST_USERS["member_services_headers"]
STAFF = TEST_USERS["theater_staff_headers"]


class TestConcessionDiscountRounding:

    def _premier_member(self, api, email):
        set_clock()
        plan = create_published_plan(
            tier="PREMIER", monthly_fee_cents=2999, weekly_reservation_quota=3,
            max_rollover_credits=2, premium_format_allowed=True,
            max_future_reservations=6, loyalty_points_multiplier_pct=150,
            concession_discount_pct=15)
        theater, _aud = create_theater_with_auditorium()
        member = create_active_member(email=email, full_name=email)
        enroll_member(member["id"], plan["id"])
        return member, theater

    def test_concession_discount_floor_then_subtract_then_points(self, api):
        """PRD §3.9: "The rounding order is pinned: floor the discount first,
        then subtract — never floor the charged amount. For a 999-cent list
        price at a 15 percent tier, the discount is the floor of 149.85, which
        is 149 cents, and the charge is 850 cents."

        Design: Difficulty/combinatorial_formula/concession_discount_floor_then_subtract_then_points
        """
        member, theater = self._premier_member(api, "m4@x.com")
        purchase = record_concession_purchase(member, theater["id"], 999)
        assert purchase["discount_cents"] == 149, (
            f"floor(999*15/100) = 149, got {purchase['discount_cents']}")
        assert purchase["charged_cents"] == 850
        # floor(850/100)*20 = 160 base; floor(160*150/100) = 240
        assert purchase["points_earned"] == 240, (
            f"expected 240 points, got {purchase['points_earned']}")

    def test_concession_discount_posts_to_loyalty_balance(self, api):
        """PRD §3.9: "The member's `loyalty_points_balance` is recomputed from
        the ledger after every append."
        PRD §3.9: "The rounding order is pinned: floor the discount first, then
        subtract — never floor the charged amount."

        Design: Difficulty/combinatorial_formula/concession_discount_floor_then_subtract_then_points
        """
        member, theater = self._premier_member(api, "m4b@x.com")
        record_concession_purchase(member, theater["id"], 999)
        m = get_success_data(api.get_member(member["id"], SERVICES))
        assert m["loyalty_points_balance"] == 240


class TestLoyaltyEvaluationOrder:

    def _plus_member(self, api, email):
        set_clock()
        plan = create_published_plan(
            tier="PLUS", monthly_fee_cents=2499, weekly_reservation_quota=3,
            max_rollover_credits=2, premium_format_allowed=True,
            max_future_reservations=5, loyalty_points_multiplier_pct=125,
            concession_discount_pct=10)
        theater, _aud = create_theater_with_auditorium()
        member = create_active_member(email=email, full_name=email)
        enroll_member(member["id"], plan["id"])
        return member, theater

    def test_loyalty_earn_pinned_evaluation_order(self, api):
        """PRD §3.9: "The evaluation order is pinned: compute `charged_cents`
        first, derive base points from it, then apply the tier multiplier, then
        floor once."
        PRD §3.9: "A concession purchase earns base points equal to the
        whole-dollar portion of `charged_cents` — the charged amount divided by
        one hundred and rounded down — multiplied by 20 points per dollar
        (`POINTS_PER_DOLLAR`)"

        Design: Difficulty/combinatorial_formula/loyalty_earn_pinned_evaluation_order_charged_then_base_then_multiplier
        """
        member, theater = self._plus_member(api, "m5@x.com")
        purchase = record_concession_purchase(member, theater["id"], 1000)
        assert purchase["discount_cents"] == 100
        assert purchase["charged_cents"] == 900
        # floor(900/100)*20 = 180 base; floor(180*125/100) = 225
        assert purchase["points_earned"] == 225, (
            f"expected 225 (multiplier on discounted base), got {purchase['points_earned']}")

    def test_loyalty_earn_appends_earn_concession_entry(self, api):
        """PRD §3.9: "Each earning appends a `LoyaltyLedgerEntry` of `kind`
        `EARN_CONCESSION` or `EARN_ADMISSION` carrying the signed `points`
        delta and the `source_id` of the originating purchase or reservation"

        Design: Difficulty/combinatorial_formula/loyalty_earn_pinned_evaluation_order_charged_then_base_then_multiplier
        """
        member, theater = self._plus_member(api, "m5b@x.com")
        purchase = record_concession_purchase(member, theater["id"], 1000)
        rows, meta = validate_paginated(
            api.list_member_loyalty_ledger(member["id"], SERVICES))
        assert meta["total_count"] == 1
        entry = rows[0]
        assert entry["kind"] == "EARN_CONCESSION"
        assert entry["points"] == 225
        assert entry["source_id"] == purchase["id"]
