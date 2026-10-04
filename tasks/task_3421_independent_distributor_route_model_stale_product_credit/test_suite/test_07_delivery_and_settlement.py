"""Delivery charges, shortage credits, the credit-limit gate, immediate
consistency, and the weekly settlement statement.

Covers PRD §3.4 (per-line rounding, shortage proration, credit gate, ledger
moves, settlement reconciliation) and §2.9 (ledger events).
Instances:
Difficulty/combinatorial_formula/delivery_charge_per_line_then_sum_rounding_order,
Corner/calculations/shortage_credit_prorated_per_line,
Corner/state_machines/record_delivery_before_day_close_rejected,
Corner/validations/record_delivery_over_credit_limit_returns_fiscal_error,
Corner/consistency_model/delivery_charge_visible_immediately_in_same_sequence,
Corner/calculations/settlement_week_fields_and_reconciliation.
"""
from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    api_client,
    assert_settlement_statement,
    claim_item,
    close_production_day,
    get_distributor,
    issue_credit,
    list_orders,
    make_distributor_headers,
    order_line,
    reconcile_order,
    record_delivery,
    record_delivery_payload,
    set_clock,
    setup_active_cash_agreement,
    setup_approved_claim,
    setup_confirmed_order,
    setup_delivered_order,
    validate_error,
    validate_success,
)

_CREDIT = TEST_USERS["credit_analyst_headers"]


def _find_order(distributor_id: str, order_id: str) -> dict:
    matches = [o for o in list_orders(distributor_id) if o["id"] == order_id]
    assert len(matches) == 1, f"order {order_id} not found"
    return matches[0]


def test_delivery_charge_per_line_then_sum(api):
    """PRD §3.4: "The rounding order is pinned — round each line first, then
    sum. With catalog prices of 319 and 157 cents, a `discount_pct` of 0.20,
    and quantities of 3 and 3, per-line rounding then summing yields
    766 + 377 = 1143 cents; summing the raw amounts before rounding would yield
    1142, and is forbidden."

    Design: Difficulty/combinatorial_formula/delivery_charge_per_line_then_sum_rounding_order
    """
    ctx = setup_active_cash_agreement()
    day, order = setup_confirmed_order(
        ctx, "2026-09-04", [order_line("RYE-09", 3), order_line("BAG-06", 3)]
    )
    set_clock("2026-09-04T08:00:00Z")
    close_production_day(day["id"])
    delivered = record_delivery(
        order, [order_line("RYE-09", 3), order_line("BAG-06", 3)]
    )
    assert delivered["status"] == "DELIVERED"
    assert delivered["total_charge_cents"] == 1143, (
        "round_half_up(3*319*0.8)=766 plus round_half_up(3*157*0.8)=377"
    )
    assert delivered["total_charge_cents"] != 1142, (
        "sum-then-round is the forbidden order"
    )
    assert delivered["units_total"] == 6


def test_delivery_charge_posts_to_trade_ledger(api):
    """PRD §2.9: "Exactly three events move it: recording a delivery adds the
    order's computed charge; reconciling a delivered order subtracts the
    verified shortage credit; issuing an approved stale credit subtracts the
    issued amount."
    PRD §3.4: "The rounding order is pinned — round each line first, then sum."

    Design: Difficulty/combinatorial_formula/delivery_charge_per_line_then_sum_rounding_order
    """
    ctx = setup_active_cash_agreement()
    day, order = setup_confirmed_order(
        ctx, "2026-09-04", [order_line("RYE-09", 3), order_line("BAG-06", 3)]
    )
    set_clock("2026-09-04T08:00:00Z")
    close_production_day(day["id"])
    record_delivery(order, [order_line("RYE-09", 3), order_line("BAG-06", 3)])
    distributor = get_distributor(ctx["distributor"]["id"])
    assert distributor["trade_balance_cents"] == 1143, (
        "the per-line-then-sum charge is what lands on the ledger"
    )


def test_shortage_credit_prorated_per_line(api):
    """PRD §3.4: "For every line where the verified quantity falls short of the
    delivered quantity, a line shortage credit is that line's charge — as
    computed at delivery — multiplied by the shortfall and divided by the
    delivered quantity, rounded half-up to whole cents; `shortage_credit_cents`
    is the sum of those per-line credits. The credit is subtracted from the
    trade ledger, the distributor's `version` advances, and the order becomes
    `RECONCILED`."

    Design: Corner/calculations/shortage_credit_prorated_per_line
    """
    ctx = setup_active_cash_agreement()
    _, order = setup_delivered_order(
        ctx, "2026-09-04", [order_line("WHT-24", 10), order_line("BUN-12", 5)]
    )
    assert order["total_charge_cents"] == 3520
    reconciled = reconcile_order(
        order, [order_line("WHT-24", 8), order_line("BUN-12", 5)]
    )
    assert reconciled["status"] == "RECONCILED"
    assert reconciled["shortage_credit_cents"] == 512, (
        "WHT-24 line charge 2560 prorated by shortfall 2 of 10: "
        "round_half_up(2560 * 2 / 10)"
    )
    distributor = get_distributor(ctx["distributor"]["id"])
    assert distributor["trade_balance_cents"] == 3008, "3520 - 512"


def test_record_delivery_before_day_close_rejected(api):
    """PRD §3.4: "Recording delivery against a day that is not yet closed is
    rejected with `ERR_PRODUCTION_DAY_LOCKED`, since production has not been
    finalized, and the distributor's agreement must be `ACTIVE` at this point
    (`ERR_AGREEMENT_NOT_ACTIVE`)."

    Design: Corner/state_machines/record_delivery_before_day_close_rejected
    """
    ctx = setup_active_cash_agreement()
    day, order = setup_confirmed_order(
        ctx, "2026-09-04", [order_line("WHT-24", 5)]
    )
    assert day["status"] == "PLANNING"
    set_clock("2026-09-04T08:00:00Z")
    resp = api_client.record_delivery(
        order["id"],
        record_delivery_payload([order_line("WHT-24", 5)]),
        make_distributor_headers(ctx["distributor"]["id"]),
    )
    validate_error(resp, ApiErrorId.ERR_PRODUCTION_DAY_LOCKED)
    current = _find_order(ctx["distributor"]["id"], order["id"])
    assert current["status"] == "CONFIRMED"
    assert get_distributor(ctx["distributor"]["id"])["trade_balance_cents"] == 0


def test_record_delivery_over_credit_limit_returns_fiscal_error(api):
    """PRD §3.4: "Before the charge posts, the credit gate runs: the
    distributor's `trade_balance_cents` plus the new charge may not exceed
    `credit_limit_cents` — landing exactly at the limit is allowed — or the
    delivery is rejected with `ERR_CREDIT_LIMIT_EXCEEDED`."

    Design: Corner/validations/record_delivery_over_credit_limit_returns_fiscal_error
    """
    ctx = setup_active_cash_agreement(credit_limit_cents=3000)
    day, order = setup_confirmed_order(
        ctx, "2026-09-04", [order_line("WHT-24", 10), order_line("BUN-12", 5)]
    )
    set_clock("2026-09-04T08:00:00Z")
    close_production_day(day["id"])
    resp = api_client.record_delivery(
        order["id"],
        record_delivery_payload(
            [order_line("WHT-24", 10), order_line("BUN-12", 5)]
        ),
        make_distributor_headers(ctx["distributor"]["id"]),
    )
    validate_error(resp, ApiErrorId.ERR_CREDIT_LIMIT_EXCEEDED)
    current = _find_order(ctx["distributor"]["id"], order["id"])
    assert current["status"] == "CONFIRMED"
    assert current["total_charge_cents"] is None
    distributor = get_distributor(ctx["distributor"]["id"])
    assert distributor["trade_balance_cents"] == 0, "0 + 3520 > 3000 rejected"


def test_delivery_charge_visible_immediately_in_same_sequence(api):
    """PRD §3.4: "On success the order becomes `DELIVERED`, the charge is added
    to the trade ledger, and the distributor's `version` and `account_standing`
    are refreshed."

    Design: Corner/consistency_model/delivery_charge_visible_immediately_in_same_sequence
    """
    ctx = setup_active_cash_agreement()
    day, order = setup_confirmed_order(
        ctx, "2026-09-04", [order_line("WHT-24", 10), order_line("BUN-12", 5)]
    )
    set_clock("2026-09-04T08:00:00Z")
    close_production_day(day["id"])
    resp = api_client.record_delivery(
        order["id"],
        record_delivery_payload(
            [order_line("WHT-24", 10), order_line("BUN-12", 5)]
        ),
        make_distributor_headers(ctx["distributor"]["id"]),
    )
    delivered = validate_success(resp)
    assert delivered["total_charge_cents"] == 3520
    distributor = get_distributor(ctx["distributor"]["id"])
    assert distributor["trade_balance_cents"] == 3520, (
        "the very next read already shows the posted charge"
    )


def test_settlement_week_fields_and_reconciliation(api):
    """PRD §3.4: "The statement reports `gross_charges_cents`, the sum of
    `total_charge_cents` over the distributor's `DELIVERED` or `RECONCILED`
    orders whose recorded delivery date falls inside the week;
    `stale_credits_issued_cents`, the credits issued on claims submitted inside
    the week; and `net_trade_cents`, the gross charges minus those issued stale
    credits."
    PRD §3.4: "`ledger_view_cents` is the running `trade_balance_cents`, while
    `document_view_cents` rebuilds the position from documents — every
    delivered or reconciled order's charge, minus every reconciled order's
    shortage credit, minus every issued stale credit. The `reconciles` flag is
    true exactly when the two views agree, and the response also carries
    `trade_balance_cents` itself."

    Design: Corner/calculations/settlement_week_fields_and_reconciliation
    """
    ctx = setup_active_cash_agreement()
    _, _, claim = setup_approved_claim(
        ctx,
        "2026-09-07",
        [order_line("WHT-24", 5), order_line("BUN-12", 10)],
        [claim_item("BUN-12", "2026-09-07", 2, "2026-09-11")],
        file_clock="2026-09-11T09:00:00Z",
    )
    issued = issue_credit(claim["id"])
    assert issued["issued_credit_cents"] == 288

    resp = api_client.get_settlement(
        ctx["distributor"]["id"], _CREDIT, params={"week": "2026-W37"}
    )
    data = validate_success(resp)
    assert_settlement_statement(data)
    assert data["week"] == "2026-W37"
    assert data["gross_charges_cents"] == 3200
    assert data["stale_credits_issued_cents"] == 288
    assert data["net_trade_cents"] == 2912
    assert data["stale_cap_cents"] == 320
    assert data["stale_cap_used_cents"] == 288
    assert data["trade_balance_cents"] == 2912
    assert data["ledger_view_cents"] == 2912
    assert data["document_view_cents"] == 2912
    assert data["reconciles"] is True
