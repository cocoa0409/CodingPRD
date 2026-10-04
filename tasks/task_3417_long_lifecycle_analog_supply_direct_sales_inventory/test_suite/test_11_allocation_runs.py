"""Allocation runs: priority waterfall, publish cascade, empty-run boundary."""
import pytest

from test_helpers import (
    TEST_USERS,
    ApiErrorId,
    get_inventory_position,
    get_order_lines,
    make_active_design_win,
    make_allocation_run,
    make_customer,
    make_order,
    make_stocked_priced_part,
    record_receipt,
    submit_order,
    validate_error,
    validate_success,
)

PLANNER = TEST_USERS["supply_planner_headers"]


def _shortage_part_with_orders(api, on_hand, orders):
    """One SHORTAGE part (demand 40, buffer 1.5 -> target 1560) plus submitted
    BACKORDERED orders. `orders` is a list of (customer, quantity). Returns
    (part, [(customer, order, line), ...])."""
    part, _ = make_stocked_priced_part(
        "LM317T", on_hand=on_hand, unit_price_cents=100,
        demand_rate=40, buffer_multiple=1.5,
    )
    rows = []
    for cust, qty in orders:
        order = make_order(cust["id"], [{"part_id": part["id"], "quantity": qty}])
        submitted = submit_order(order["id"], cust["id"])
        assert submitted["status"] == "BACKORDERED"
        line = get_order_lines(order["id"])[0]
        assert line["awarded_units"] == 0
        rows.append((cust, order, line))
    return part, rows


class TestAllocationRuns:
    def test_allocation_waterfall_nested_min_priority(self, api):
        """PRD §3.6: "Each eligible line's priority score is the sum of its
        customer's tier weight — 100 for `STRATEGIC`, 70 for `KEY`, 40 for
        `STANDARD`, 10 for `SMALL` — plus a design-win priority bonus of 25 when the
        customer holds a design win on the line's part whose status is `ACTIVE` and
        whose `at_risk` is false; without such a win the bonus is zero."
        PRD §3.6: "Walking the sorted lines, each line receives an award equal to the
        smaller of its remaining quantity and the currently available units, the
        available balance decreases by the award, and an award entry recording
        `order_line_id`, `awarded_units`, `priority_score`, and `rank` is appended —
        `rank` being the line's 1-based position in the part's processing order."

        Design: Difficulty/combinatorial_formula/allocation_waterfall_nested_min_priority
        """
        cust_a = make_customer(name="Strategic Motors", tier="STRATEGIC",
                               channel="DIRECT_FIELD", credit_limit_cents=10_000_000)
        cust_b = make_customer(name="Key Controls", tier="KEY",
                               channel="DIRECT_FIELD", credit_limit_cents=10_000_000)
        cust_c = make_customer(name="Standard Devices", tier="STANDARD",
                               channel="DIRECT_FIELD", credit_limit_cents=10_000_000)
        part, rows = _shortage_part_with_orders(
            api, 100, [(cust_a, 80), (cust_b, 50), (cust_c, 30)]
        )
        make_active_design_win(part, cust_a, title="Rail PSU reference")

        run = make_allocation_run("2026-W40")
        published = validate_success(api.publish_allocation_run(run["id"], PLANNER), 200)
        assert published["status"] == "PUBLISHED"

        (_, ord_a, line_a), (_, ord_b, line_b), (_, ord_c, line_c) = rows
        la = validate_success(api.get_order_line(line_a["id"], PLANNER), 200)
        assert la["awarded_units"] == 80
        assert la["allocation_rank"] == 1
        assert la["allocation_priority_score"] == 125  # STRATEGIC 100 + bonus 25
        lb = validate_success(api.get_order_line(line_b["id"], PLANNER), 200)
        assert lb["awarded_units"] == 20  # min(50, remaining 20) — nested min binds
        assert lb["allocation_rank"] == 2
        assert lb["allocation_priority_score"] == 70
        lc = validate_success(api.get_order_line(line_c["id"], PLANNER), 200)
        assert lc["awarded_units"] == 0, "zero-award entry is still recorded"
        assert lc["allocation_rank"] == 3
        assert lc["allocation_priority_score"] == 40

        assert validate_success(api.get_order(ord_a["id"], PLANNER), 200)["status"] == "ALLOCATED"
        assert validate_success(api.get_order(ord_b["id"], PLANNER), 200)["status"] == "BACKORDERED"
        assert validate_success(api.get_order(ord_c["id"], PLANNER), 200)["status"] == "BACKORDERED"

        pos = get_inventory_position(part["id"])
        assert pos["reserved_units"] == 100
        assert pos["on_hand_units"] == 100

    def test_allocation_run_reports_shortage_part_ids(self, api):
        """PRD §3.6: "`shortage_part_ids` is a reporting field listing the ids of
        parts whose `posture` is `SHORTAGE` at run creation, sorted by `part_number`
        ascending — it describes the shortage landscape and does not limit
        eligibility."
        PRD §3.6: "`awards` is the computed award list: one entry per eligible order
        line, including zero-award entries, frozen until publish."

        Design: Difficulty/combinatorial_formula/allocation_waterfall_nested_min_priority
        """
        cust = make_customer(name="Solo Buyer", tier="STANDARD",
                             channel="DIRECT_FIELD", credit_limit_cents=10_000_000)
        part, rows = _shortage_part_with_orders(api, 0, [(cust, 10)])

        run = make_allocation_run("2026-W41")
        assert run["status"] == "DRAFT"
        assert run["shortage_part_ids"] == [part["id"]]
        assert len(run["awards"]) == 1
        entry = run["awards"][0]
        assert entry["order_line_id"] == rows[0][2]["id"]
        assert entry["awarded_units"] == 0  # available == 0 at run creation
        assert entry["priority_score"] == 40
        assert entry["rank"] == 1

    def test_allocation_publish_cascades_order_part_posture(self, api):
        """PRD §3.6: "For every affected order, the newly awarded units are added to
        the part's `reserved_units`; when every line of an order now has
        `awarded_units` equal to its `quantity`, the order flips from `BACKORDERED`
        to `ALLOCATED` as a side effect."
        PRD §3.1: "Posture is recomputed internally after every mutation of
        `on_hand_units`, `reserved_units`, `demand_rate_units_per_week`,
        `buffer_multiple`, or a linked `ACTIVE` design win's `annual_volume_units`."

        Design: Difficulty/transitive_cascade/allocation_publish_cascades_order_part_posture
        """
        part, pool = make_stocked_priced_part(
            "INA128PA", on_hand=1180, unit_price_cents=100,
            demand_rate=40, buffer_multiple=1.5, pool_total_units=5000,
        )
        cust = make_customer(name="Process Controls SA", tier="STANDARD",
                             channel="DIRECT_FIELD", credit_limit_cents=10_000_000)
        order = make_order(cust["id"], [{"part_id": part["id"], "quantity": 1200}])
        submitted = submit_order(order["id"], cust["id"])
        assert submitted["status"] == "BACKORDERED"
        line = get_order_lines(order["id"])[0]
        assert line["awarded_units"] == 0

        record_receipt(part["id"], pool["id"], 300)
        pre = get_inventory_position(part["id"])
        assert pre["posture"] == "WATCH"
        assert pre["coverage_trailing"] == pytest.approx(0.9487, abs=1e-4)

        run = make_allocation_run("2026-W41")
        validate_success(api.publish_allocation_run(run["id"], PLANNER), 200)

        awarded = validate_success(api.get_order_line(line["id"], PLANNER), 200)
        assert awarded["awarded_units"] == 1200
        assert validate_success(api.get_order(order["id"], PLANNER), 200)["status"] == "ALLOCATED"
        pos = get_inventory_position(part["id"])
        assert pos["reserved_units"] == 1200
        assert pos["coverage_trailing"] == pytest.approx(0.1795, abs=1e-4)
        assert pos["posture"] == "SHORTAGE"

    def test_awards_accumulate_across_runs(self, api):
        """PRD §3.6: "Publishing applies the frozen awards: each awarded line's
        `awarded_units` increases by its awarded amount (awards accumulate across
        submissions and runs), and the line's `allocation_run_id`,
        `allocation_rank`, and `allocation_priority_score` are stamped from the
        applying run."
        PRD §3.6: "when every line of an order now has `awarded_units` equal to its
        `quantity`, the order flips from `BACKORDERED` to `ALLOCATED` as a side
        effect."

        Design: Difficulty/transitive_cascade/allocation_publish_cascades_order_part_posture
        """
        part, pool = make_stocked_priced_part(
            "INA129PA", on_hand=0, unit_price_cents=100,
            demand_rate=40, buffer_multiple=1.5, pool_total_units=5000,
        )
        cust = make_customer(name="Accumulator", tier="STANDARD",
                             channel="DIRECT_FIELD", credit_limit_cents=10_000_000)
        order = make_order(cust["id"], [{"part_id": part["id"], "quantity": 10}])
        assert submit_order(order["id"], cust["id"])["status"] == "BACKORDERED"
        line = get_order_lines(order["id"])[0]

        record_receipt(part["id"], pool["id"], 4)
        run1 = make_allocation_run("2026-W42")
        validate_success(api.publish_allocation_run(run1["id"], PLANNER), 200)
        mid = validate_success(api.get_order_line(line["id"], PLANNER), 200)
        assert mid["awarded_units"] == 4
        assert mid["allocation_run_id"] == run1["id"]
        assert validate_success(api.get_order(order["id"], PLANNER), 200)["status"] == "BACKORDERED"

        record_receipt(part["id"], pool["id"], 6)
        run2 = make_allocation_run("2026-W43")
        validate_success(api.publish_allocation_run(run2["id"], PLANNER), 200)
        final = validate_success(api.get_order_line(line["id"], PLANNER), 200)
        assert final["awarded_units"] == 10  # 4 + 6 accumulated
        assert final["allocation_run_id"] == run2["id"]
        assert validate_success(api.get_order(order["id"], PLANNER), 200)["status"] == "ALLOCATED"
        assert get_inventory_position(part["id"])["reserved_units"] == 10

    def test_allocation_run_with_zero_eligible_lines_publishes_empty(self, api):
        """PRD §3.6: "`awards` is the computed award list: one entry per eligible
        order line, including zero-award entries, frozen until publish."
        PRD §3.6: "Eligibility is broad: every order line whose order is in
        `BACKORDERED` status with a remaining quantity — `quantity` minus
        `awarded_units` — greater than zero is eligible, whatever its part's
        posture; `SHORTAGE` parts are simply where the competition actually binds."

        Design: Difficulty/boundary_precision_check/allocation_run_with_zero_eligible_lines_publishes_empty
        """
        part, _pool = make_stocked_priced_part("UA741CP", on_hand=0)
        run = validate_success(
            api.create_allocation_run({"period_label": "2026-W42"}, PLANNER), 201
        )
        assert run["status"] == "DRAFT"
        assert run["awards"] == []
        assert run["shortage_part_ids"] == []

        published = validate_success(api.publish_allocation_run(run["id"], PLANNER), 200)
        assert published["status"] == "PUBLISHED"
        assert published["awards"] == []
        assert get_inventory_position(part["id"])["reserved_units"] == 0

    def test_republish_published_run_rejected(self, api):
        """PRD §3.6: "Publishing is done by a `SupplyPlanner` and only from `DRAFT` —
        publishing a run in any other state is `ERR_INVALID_STATE`."

        Design: Difficulty/boundary_precision_check/allocation_run_with_zero_eligible_lines_publishes_empty
        """
        run = make_allocation_run("2026-W44")
        validate_success(api.publish_allocation_run(run["id"], PLANNER), 200)
        res = api.publish_allocation_run(run["id"], PLANNER)
        validate_error(res, ApiErrorId.ERR_INVALID_STATE)
