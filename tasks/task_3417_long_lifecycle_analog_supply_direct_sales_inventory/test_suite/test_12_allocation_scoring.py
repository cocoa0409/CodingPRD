"""Allocation scoring: created_at tie-break and tier changes between runs."""
from test_helpers import (
    TEST_USERS,
    get_order_lines,
    make_allocation_run,
    make_customer,
    make_order,
    make_stocked_priced_part,
    record_receipt,
    set_clock,
    submit_order,
    validate_success,
)

PLANNER = TEST_USERS["supply_planner_headers"]
CHANNEL = TEST_USERS["channel_manager_headers"]


class TestAllocationScoring:
    def test_allocation_tie_break_uses_order_created_at(self, api):
        """PRD §3.6: "The part's eligible lines are ordered by priority score
        descending, then by their order's `created_at` ascending, then by the line's
        own `created_at` ascending; lines belonging to the same order — identical
        timestamps at both levels — are processed in their position in that order's
        `lines` array."
        PRD §2.5: "Because the clock is fixed unless explicitly advanced, two
        resources created without an intervening clock set share an identical
        `created_at`; workflows that break ties on creation time depend on this
        property."

        Design: Corner/calculations/allocation_tie_break_uses_order_created_at
        """
        part, _ = make_stocked_priced_part(
            "TLV2371IDBVR", on_hand=10, unit_price_cents=100,
            demand_rate=40, buffer_multiple=1.5,
            package_family="SOT23", process_technology="CMOS_180NM",
        )
        cust1 = make_customer(name="Early Bird", tier="STANDARD",
                              channel="DIRECT_FIELD", credit_limit_cents=1_000_000)
        cust2 = make_customer(name="Late Comer", tier="STANDARD",
                              channel="DIRECT_FIELD", credit_limit_cents=1_000_000)
        o1 = make_order(cust1["id"], [{"part_id": part["id"], "quantity": 10}])
        set_clock("2026-09-02T00:00:00Z")  # separate the orders' created_at
        o2 = make_order(cust2["id"], [{"part_id": part["id"], "quantity": 10}])
        assert submit_order(o1["id"], cust1["id"])["status"] == "BACKORDERED"
        assert submit_order(o2["id"], cust2["id"])["status"] == "BACKORDERED"
        line1 = get_order_lines(o1["id"])[0]
        line2 = get_order_lines(o2["id"])[0]

        run = make_allocation_run("2026-W43")
        validate_success(api.publish_allocation_run(run["id"], PLANNER), 200)

        l1 = validate_success(api.get_order_line(line1["id"], PLANNER), 200)
        assert l1["awarded_units"] == 10
        assert l1["allocation_rank"] == 1
        assert l1["allocation_priority_score"] == 40
        l2 = validate_success(api.get_order_line(line2["id"], PLANNER), 200)
        assert l2["awarded_units"] == 0
        assert l2["allocation_rank"] == 2
        assert l2["allocation_priority_score"] == 40

        assert validate_success(api.get_order(o1["id"], PLANNER), 200)["status"] == "ALLOCATED"
        assert validate_success(api.get_order(o2["id"], PLANNER), 200)["status"] == "BACKORDERED"

    def test_customer_tier_change_affects_future_allocation_scores(self, api):
        """PRD §3.2: "The `ChannelManager` may later change `tier`, `channel`,
        `credit_limit_cents`, or `discount_pct`; each such change increments the
        customer's `version` by one, and allocation runs created afterwards score the
        customer's lines with the new tier."
        PRD §3.6: "Each eligible line's priority score is the sum of its customer's
        tier weight — 100 for `STRATEGIC`, 70 for `KEY`, 40 for `STANDARD`, 10 for
        `SMALL` — plus a design-win priority bonus of 25 when the customer holds a
        design win on the line's part whose status is `ACTIVE` and whose `at_risk`
        is false; without such a win the bonus is zero."

        Design: Corner/endpoints/customer_tier_change_affects_future_allocation_scores
        """
        part, pool = make_stocked_priced_part(
            "TLV272IDR", on_hand=0, unit_price_cents=100,
            demand_rate=40, buffer_multiple=1.5,
            package_family="SOIC", process_technology="CMOS_180NM",
        )
        cust = make_customer(name="Rising Star", tier="STANDARD",
                             channel="DIRECT_FIELD", credit_limit_cents=1_000_000)
        order = make_order(cust["id"], [{"part_id": part["id"], "quantity": 10}])
        assert submit_order(order["id"], cust["id"])["status"] == "BACKORDERED"
        line = get_order_lines(order["id"])[0]

        run1 = make_allocation_run("2026-W44")
        validate_success(api.publish_allocation_run(run1["id"], PLANNER), 200)
        mid = validate_success(api.get_order_line(line["id"], PLANNER), 200)
        assert mid["awarded_units"] == 0, "zero available units at run 1"
        assert mid["allocation_priority_score"] == 40  # STANDARD at run-1 creation
        assert mid["allocation_run_id"] == run1["id"]

        patched = validate_success(
            api.patch_customer(cust["id"], {"tier": "STRATEGIC"}, CHANNEL), 200
        )
        assert patched["tier"] == "STRATEGIC"

        record_receipt(part["id"], pool["id"], 10)
        run2 = make_allocation_run("2026-W45")
        validate_success(api.publish_allocation_run(run2["id"], PLANNER), 200)

        final = validate_success(api.get_order_line(line["id"], PLANNER), 200)
        assert final["awarded_units"] == 10
        assert final["allocation_priority_score"] == 100  # rescored with new tier
        assert final["allocation_run_id"] == run2["id"]
        assert validate_success(api.get_order(order["id"], PLANNER), 200)["status"] == "ALLOCATED"
