"""Order submission: the ALLOCATED/BACKORDERED fork and pinned totals math."""
from test_helpers import (
    TEST_USERS,
    get_customer,
    get_inventory_position,
    get_order_lines,
    make_customer,
    make_order,
    make_stocked_priced_part,
    submit_order,
    validate_success,
)

PLANNER = TEST_USERS["supply_planner_headers"]


class TestOrderSubmissionFork:
    def test_order_submit_branching_alloc_vs_backorder(self, api):
        """PRD §3.4: "if every line was fully auto-awarded, the order lands in
        `ALLOCATED`; if at least one line was not fully auto-awarded, the order lands
        in `BACKORDERED`, and the partial auto-awards and reservations made during
        submission persist — a `BACKORDERED` order still holds its reservations and
        still accrues open exposure."
        PRD §3.2: "`open_exposure_cents` is the sum of `total_cents` over the
        customer's orders in `ALLOCATED` or `BACKORDERED` status, plus the sum of
        `ltb_value_cents` over the customer's `APPROVED` lifetime buys."

        Design: Difficulty/non_linear_state_machine/order_submit_branching_alloc_vs_backorder
        """
        normal_part, _ = make_stocked_priced_part(
            "SN74HC00N", on_hand=1000, unit_price_cents=100,
            site_name="DFAB", process_technology="CMOS_180NM",
        )
        shortage_part, _ = make_stocked_priced_part(
            "TPS5430DDAR", on_hand=100, unit_price_cents=100,
            demand_rate=10, buffer_multiple=1.5,
            site_name="DFAB", process_technology="ANALOG_BIPOLAR",
        )
        cust = make_customer(name="Standard Buyer", tier="STANDARD",
                             channel="DIRECT_FIELD", credit_limit_cents=10_000_000)
        o1 = make_order(cust["id"], [{"part_id": normal_part["id"], "quantity": 5}])
        o2 = make_order(cust["id"], [{"part_id": shortage_part["id"], "quantity": 5}])

        s1 = submit_order(o1["id"], cust["id"])
        s2 = submit_order(o2["id"], cust["id"])
        assert s1["status"] == "ALLOCATED"
        assert s2["status"] == "BACKORDERED"

        lines1 = get_order_lines(o1["id"])
        lines2 = get_order_lines(o2["id"])
        assert lines1[0]["awarded_units"] == 5
        assert lines2[0]["awarded_units"] == 0
        assert get_inventory_position(normal_part["id"])["reserved_units"] == 5
        assert get_inventory_position(shortage_part["id"])["reserved_units"] == 0

        exposure = get_customer(cust["id"])["open_exposure_cents"]
        assert exposure == 1000, "exposure accrues on BOTH fork branches (500 + 500)"

    def test_backordered_order_keeps_partial_line_awards_and_exposure(self, api):
        """PRD §3.4: "if every line was fully auto-awarded, the order lands in
        `ALLOCATED`; if at least one line was not fully auto-awarded, the order lands
        in `BACKORDERED`, and the partial auto-awards and reservations made during
        submission persist — a `BACKORDERED` order still holds its reservations and
        still accrues open exposure."
        PRD §3.4: "a line whose part's `posture` is not `SHORTAGE` and whose available
        stock (`on_hand_units` minus `reserved_units`) covers the full `quantity`
        receives `awarded_units` equal to its `quantity`, and the awarded units are
        added to the part's `reserved_units`."

        Design: Difficulty/non_linear_state_machine/order_submit_branching_alloc_vs_backorder
        """
        normal_part, _ = make_stocked_priced_part(
            "SN74HC02N", on_hand=100, unit_price_cents=100,
            site_name="DFAB", process_technology="CMOS_180NM",
        )
        shortage_part, _ = make_stocked_priced_part(
            "TPS5431DDAR", on_hand=50, unit_price_cents=100,
            demand_rate=40, buffer_multiple=1.5,
            site_name="DFAB", process_technology="ANALOG_BIPOLAR",
        )
        cust = make_customer(name="Mixed Buyer", tier="STANDARD",
                             channel="DIRECT_FIELD", credit_limit_cents=10_000_000)
        order = make_order(
            cust["id"],
            [
                {"part_id": normal_part["id"], "quantity": 5},
                {"part_id": shortage_part["id"], "quantity": 5},
            ],
        )
        submitted = submit_order(order["id"], cust["id"])
        assert submitted["status"] == "BACKORDERED"
        assert submitted["total_cents"] == 1000

        lines = sorted(get_order_lines(order["id"]), key=lambda l: l["part_id"])
        by_part = {l["part_id"]: l for l in lines}
        assert by_part[normal_part["id"]]["awarded_units"] == 5
        assert by_part[shortage_part["id"]]["awarded_units"] == 0
        assert get_inventory_position(normal_part["id"])["reserved_units"] == 5
        assert get_inventory_position(shortage_part["id"])["reserved_units"] == 0

        assert get_customer(cust["id"])["open_exposure_cents"] == 1000

    def test_order_totals_per_line_rounding_beats_sum_rounding(self, api):
        """PRD §3.4: "the discount is applied and rounded per line, and only then are
        the rounded line totals summed; summing unrounded amounts and rounding once at
        the end is a different, non-conformant result."

        Design: Difficulty/combinatorial_formula/order_totals_per_line_rounding_beats_sum_rounding
        """
        part, _ = make_stocked_priced_part(
            "TL431ACDR", on_hand=100, unit_price_cents=175
        )
        cust = make_customer(
            name="Key Instrumentation", tier="KEY", channel="DIRECT_FIELD",
            credit_limit_cents=10_000_000, discount_pct=0.10,
        )
        order = make_order(
            cust["id"],
            [
                {"part_id": part["id"], "quantity": 33},
                {"part_id": part["id"], "quantity": 33},
            ],
        )
        submitted = submit_order(order["id"], cust["id"])
        assert submitted["status"] == "ALLOCATED"
        assert submitted["subtotal_cents"] == 10396  # NOT 10395 (sum-then-round)
        assert submitted["service_fee_cents"] == 0
        assert submitted["total_cents"] == 10396

        for line in get_order_lines(order["id"]):
            assert line["line_total_cents"] == 5198  # round_half_up(5197.5)
            assert line["unit_price_cents"] == 175
        assert get_inventory_position(part["id"])["reserved_units"] == 66

    def test_service_fee_zero_at_exact_min_subtotal(self, api):
        """PRD §3.4: "`service_fee_cents` is 500 cents — the small-order fee — when
        the customer's tier is `SMALL` and the order's channel is `DIRECT_ONLINE` and
        `subtotal_cents` is strictly below 10000 cents; in every other case, including
        a subtotal of exactly 10000 cents, the fee is 0."

        Design: Difficulty/combinatorial_formula/order_totals_per_line_rounding_beats_sum_rounding
        """
        part, _ = make_stocked_priced_part(
            "MCP6001-I/P", on_hand=100, unit_price_cents=250
        )
        cust = make_customer(
            name="Boundary Hobbyist", tier="SMALL", channel="DIRECT_ONLINE",
            credit_limit_cents=10_000_000,
        )
        order = make_order(cust["id"], [{"part_id": part["id"], "quantity": 40}])
        submitted = submit_order(order["id"], cust["id"])
        assert submitted["subtotal_cents"] == 10000
        assert submitted["service_fee_cents"] == 0
        assert submitted["total_cents"] == 10000
        assert submitted["status"] == "ALLOCATED"
