"""Parts ordering: the off-season incentive's pinned per-line rounding, the
commitment ledger's debit/compensation pair, and the line-quantity boundary
(PRD §3.3).
"""
from test_helpers import (
    ApiErrorId,
    advance_clock,
    cancel_order,
    create_order_for,
    create_part_for,
    get_success_data,
    make_distributor_manager_headers,
    setup_program,
    submit_order,
    validate_error,
    validate_success,
)

OFF_SEASON_JANUARY = "2027-01-15T00:00:00Z"


def _setup_program_with_part(unit_cost_cents=12000, **part_overrides):
    ctx = setup_program()
    part = create_part_for(ctx["model"], unit_cost_cents=unit_cost_cents, **part_overrides)
    ctx["part"] = part
    return ctx


def _setup_two_25005_parts():
    ctx = setup_program()
    p3 = create_part_for(ctx["model"], sku="P3-BLADE", name="Rotary blade set",
                         unit_cost_cents=25005, min_stock_qty=2)
    p4 = create_part_for(ctx["model"], sku="P4-HOSE", name="Hydraulic hose kit",
                         unit_cost_cents=25005, min_stock_qty=2)
    ctx["p3"] = p3
    ctx["p4"] = p4
    return ctx


def test_per_line_rounding_discount_sum(api):
    """PRD §3.3: "Rounding is pinned per line: each line's discount is that
    line's `qty` times `unit_cost_cents` times the tier percentage, rounded
    half-up to integer cents, and `discount_cents` is the sum of those per-line
    discounts — summing the raw discounts first and rounding once would produce
    different cents and is not the rule."

    Design: Difficulty/combinatorial_formula/incentive_discount_per_line_rounding
    """
    ctx = _setup_two_25005_parts()
    advance_clock(OFF_SEASON_JANUARY)
    order = create_order_for(
        ctx["distributor"],
        [{"part_id": ctx["p3"]["id"], "qty": 1}, {"part_id": ctx["p4"]["id"], "qty": 1}],
    )
    submitted = submit_order(order)
    # Per line: round_half_up(25005 x 0.07) = 1750; 1750 + 1750 = 3500.
    # The forbidden sum-then-round order would give round_half_up(3500.7) = 3501.
    assert submitted["discount_tier_pct"] == 0.07
    assert submitted["discount_cents"] == 3500, (
        f"pinned per-line rounding gives 3500 (not 3501); got {submitted['discount_cents']}"
    )


def test_submission_sets_totals_and_flags(api):
    """PRD §3.3: "`total_cents` is then `subtotal_cents` minus
    `discount_cents`; `off_season_applied` is set true and `discount_tier_pct`
    records the tier percentage applied."
    PRD §3.3: "a subtotal of at least 200,000 cents earns 12 percent; otherwise
    a subtotal of at least 50,000 cents earns 7 percent; otherwise 3 percent."

    Design: Difficulty/combinatorial_formula/incentive_discount_per_line_rounding
    """
    ctx = _setup_two_25005_parts()
    advance_clock(OFF_SEASON_JANUARY)
    order = create_order_for(
        ctx["distributor"],
        [{"part_id": ctx["p3"]["id"], "qty": 1}, {"part_id": ctx["p4"]["id"], "qty": 1}],
    )
    submitted = submit_order(order)
    assert submitted["subtotal_cents"] == 50010
    assert submitted["off_season_applied"] is True
    assert submitted["discount_cents"] == 3500
    assert submitted["total_cents"] == 46510, (
        f"total = 50010 - 3500 = 46510; got {submitted['total_cents']}"
    )


def test_incentive_tier_boundary_at_exact_threshold(api):
    """PRD §3.3: "a subtotal of at least 200,000 cents earns 12 percent;
    otherwise a subtotal of at least 50,000 cents earns 7 percent; otherwise
    3 percent."
    PRD §3.3: "The incentive applies only when the order is `STOCK` and the
    logical clock's month is November, December, January, or February."

    Design: Corner/calculations/incentive_tier_boundary_at_exact_threshold
    """
    ctx = _setup_program_with_part(unit_cost_cents=25000, sku="P5-FILTER",
                                   name="Filter kit", min_stock_qty=2)
    advance_clock(OFF_SEASON_JANUARY)
    order = create_order_for(ctx["distributor"], [{"part_id": ctx["part"]["id"], "qty": 2}])
    submitted = submit_order(order)
    assert submitted["subtotal_cents"] == 50000
    assert submitted["discount_tier_pct"] == 0.07, (
        f"subtotal exactly 50000 meets the inclusive 7% tier; got {submitted['discount_tier_pct']}"
    )
    assert submitted["discount_cents"] == 3500
    assert submitted["total_cents"] == 46500


def test_incentive_not_applied_in_season(api):
    """PRD §3.3: "When the incentive does not apply — a `CUSTOMER` order, or a
    submit outside the four off-season months — `off_season_applied` stays
    false and both `discount_tier_pct` and `discount_cents` stay 0."

    Design: Corner/calculations/incentive_not_applied_in_season
    """
    # Default logical clock is 2026-09-01T00:00:00Z — September, in-season.
    ctx = _setup_program_with_part(unit_cost_cents=25000, sku="P5-FILTER",
                                   name="Filter kit", min_stock_qty=2)
    order = create_order_for(ctx["distributor"], [{"part_id": ctx["part"]["id"], "qty": 2}])
    submitted = submit_order(order)
    assert submitted["off_season_applied"] is False
    assert submitted["discount_cents"] == 0
    assert submitted["total_cents"] == 50000


def test_order_cancel_voids_discount_and_releases_commitment(api, corporate_admin_headers):
    """PRD §3.3: "Cancelling out of `SUBMITTED` — also a `DistributorManager`
    act — compensates the ledger: `committed_parts_cents` decreases by
    `total_cents`, and the order's `discount_cents` is voided along with the
    order."

    Design: Corner/state_machines/order_cancel_voids_discount_and_releases_commitment
    """
    ctx = _setup_two_25005_parts()
    advance_clock(OFF_SEASON_JANUARY)
    order = create_order_for(
        ctx["distributor"],
        [{"part_id": ctx["p3"]["id"], "qty": 1}, {"part_id": ctx["p4"]["id"], "qty": 1}],
    )
    submitted = submit_order(order)
    assert submitted["total_cents"] == 46510
    after_submit = validate_success(
        api.get_distributor(ctx["distributor"]["id"], corporate_admin_headers)
    )
    assert after_submit["committed_parts_cents"] == 46510

    cancelled = cancel_order(submitted)
    assert cancelled["status"] == "CANCELLED"
    after_cancel = validate_success(
        api.get_distributor(ctx["distributor"]["id"], corporate_admin_headers)
    )
    assert after_cancel["committed_parts_cents"] == 0, (
        f"cancelling must release exactly the discounted total 46510; "
        f"committed is {after_cancel['committed_parts_cents']}"
    )


def test_submit_debits_commitment(api, corporate_admin_headers):
    """PRD §3.3: "Either way, submission debits the distributor's commitment
    ledger: `committed_parts_cents` increases by the order's `total_cents`,
    reflecting the value of in-flight orders in `SUBMITTED`, `ALLOCATED`, or
    `SHIPPED`."

    Design: Difficulty/compensating_invariant/order_submit_cancel_conserves_commitment
    """
    ctx = _setup_program_with_part()
    order = create_order_for(ctx["distributor"], [{"part_id": ctx["part"]["id"], "qty": 100}])
    submitted = submit_order(order)
    # September (in-season): no incentive; total == subtotal == 100 x 12000.
    assert submitted["total_cents"] == 1200000
    distributor = validate_success(
        api.get_distributor(ctx["distributor"]["id"], corporate_admin_headers)
    )
    assert distributor["committed_parts_cents"] == 1200000, (
        f"submit must debit exactly total_cents; got {distributor['committed_parts_cents']}"
    )


def test_cancel_releases_commitment(api, corporate_admin_headers):
    """PRD §3.3: "Cancelling out of `SUBMITTED` — also a `DistributorManager`
    act — compensates the ledger: `committed_parts_cents` decreases by
    `total_cents`, and the order's `discount_cents` is voided along with the
    order."

    Design: Difficulty/compensating_invariant/order_submit_cancel_conserves_commitment
    """
    ctx = _setup_program_with_part()
    order = create_order_for(ctx["distributor"], [{"part_id": ctx["part"]["id"], "qty": 100}])
    submitted = submit_order(order)
    cancelled = cancel_order(submitted)
    assert cancelled["status"] == "CANCELLED"
    assert cancelled["total_cents"] == 1200000
    distributor = validate_success(
        api.get_distributor(ctx["distributor"]["id"], corporate_admin_headers)
    )
    assert distributor["committed_parts_cents"] == 0, (
        f"the submit + cancel pair must conserve the pre-action commitment; "
        f"got {distributor['committed_parts_cents']}"
    )


def test_zero_qty_line_rejected(api):
    """PRD §3.3: "Order shape is enforced at creation and re-checked at
    submission: an order with zero lines is rejected with `ERR_EMPTY_ORDER`
    (HTTP 422), and any line whose `qty` is below 1 is rejected with
    `ERR_ZERO_QUANTITY_LINE` (HTTP 422)."

    Design: Difficulty/boundary_precision_check/zero_qty_line_rejected_one_is_accepted
    """
    ctx = _setup_program_with_part()
    resp = api.create_parts_order(
        {"order_type": "STOCK", "lines": [{"part_id": ctx["part"]["id"], "qty": 0}]},
        make_distributor_manager_headers(ctx["distributor"]["id"]),
    )
    validate_error(resp, ApiErrorId.ERR_ZERO_QUANTITY_LINE.value)


def test_qty_one_accepted(api):
    """PRD §3.3: "any line whose `qty` is below 1 is rejected with
    `ERR_ZERO_QUANTITY_LINE` (HTTP 422)"
    PRD §3.3: "At creation the system already computes `subtotal_cents` — the
    sum over lines of each line's `qty` multiplied by its part's
    `unit_cost_cents` — and `ordered_units`, the sum of `qty` across lines"

    Design: Difficulty/boundary_precision_check/zero_qty_line_rejected_one_is_accepted
    """
    ctx = _setup_program_with_part()
    order = validate_success(
        api.create_parts_order(
            {"order_type": "STOCK", "lines": [{"part_id": ctx["part"]["id"], "qty": 1}]},
            make_distributor_manager_headers(ctx["distributor"]["id"]),
        ),
        201,
    )
    assert order["ordered_units"] == 1, (
        f"qty 1 is the first legal value; ordered_units must be 1, got {order['ordered_units']}"
    )
    assert order["status"] == "DRAFT"
