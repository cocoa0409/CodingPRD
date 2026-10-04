"""Ticket sales: family-pack rounding order (divide per-seat first, then multiply)."""
from test_helpers import (
    TEST_USERS,
    api_client,
    create_ticket_scale,
    setup_confirmed_engagement,
    validate_success,
)

BOM = TEST_USERS["box_office_manager_headers"]


class TestFamilyPackPricing:
    def test_family_pack_rounding_divide_then_multiply(self):
        """PRD §3.8: "For an order of N seats against a tier with
        `is_family_pack` true, the bundle size is 4 seats: the order yields a
        whole-bundle count of N divided by 4 rounded down, plus a remainder of
        loose seats. Each loose seat is priced at the bundle `base_price_cents`
        divided by 4 and rounded half-up to integer cents — the per-seat
        division rounds first — and the order total is the whole-bundle count
        times the bundle price plus the loose-seat count times the per-seat
        price. This divide-then-multiply order is deliberate: it is not
        equivalent to multiplying N by the bundle price and dividing by 4
        afterward, and for odd N the two orders disagree."

        Design: Difficulty/combinatorial_formula/family_pack_per_seat_division_rounding_order
        """
        ctx = setup_confirmed_engagement()
        scale = create_ticket_scale(
            ctx,
            tier_label="FAMILY4",
            base_price_cents=9999,
            seats_allocated=100,
            tier_rank=2,
            on_sale_at="2026-09-01T00:00:00Z",
            is_family_pack=True,
            is_group_sales_only=True,
            min_group_size=4,
        )
        resp = api_client.create_ticket_sale(
            ctx["tour"]["id"], ctx["engagement"]["id"],
            {"ticket_scale_id": scale["id"], "quantity": 7}, BOM,
        )
        sale = validate_success(resp, expected_status=201)
        # 1 bundle at 9999 + 3 loose at round_half_up(9999/4)=2500 each = 17499.
        assert sale["total_cents"] == 17499
        assert sale["total_cents"] != 17498

    def test_family_pack_exact_bundles_have_no_loose_seat_component(self):
        """PRD §3.8: "the order yields a whole-bundle count of N divided by 4
        rounded down, plus a remainder of loose seats. Each loose seat is priced
        at the bundle `base_price_cents` divided by 4 and rounded half-up to
        integer cents — the per-seat division rounds first — and the order total
        is the whole-bundle count times the bundle price plus the loose-seat
        count times the per-seat price."

        Design: Difficulty/combinatorial_formula/family_pack_per_seat_division_rounding_order
        """
        ctx = setup_confirmed_engagement()
        scale = create_ticket_scale(
            ctx,
            tier_label="FAMILY4",
            base_price_cents=9999,
            seats_allocated=100,
            tier_rank=2,
            on_sale_at="2026-09-01T00:00:00Z",
            is_family_pack=True,
            is_group_sales_only=True,
            min_group_size=4,
        )
        resp = api_client.create_ticket_sale(
            ctx["tour"]["id"], ctx["engagement"]["id"],
            {"ticket_scale_id": scale["id"], "quantity": 8}, BOM,
        )
        sale = validate_success(resp, expected_status=201)
        # Exactly 2 bundles, no loose seats.
        assert sale["total_cents"] == 2 * 9999
