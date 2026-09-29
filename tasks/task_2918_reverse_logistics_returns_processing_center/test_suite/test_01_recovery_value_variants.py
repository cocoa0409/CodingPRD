"""Provisional versus final recovery, and booked versus projected settlement."""

from prd_bench_local_runner.testing import validate_success

from test_helpers import fixtures as fx
from test_helpers.assertions import (
    assert_money,
    assert_pct_equals,
    sole_entry_of_type,
)
from test_helpers.constants import (
    CLIENT_STATUS_ACTIVE,
    DISPOSITION_LIQUIDATE,
    ENTRY_RECOVERY_CREDIT,
    GRADE_C,
    REASON_DEFECTIVE,
)
from test_helpers.test_users import SUPERVISOR


def _liquidation_world(api, client_code, channel_code="AUC1"):
    """A graded-C line on a liquidation client, plus an auction channel."""
    world = fx.graded_scenario(
        api,
        client_kwargs=fx.liquidation_client_kwargs(client_code),
        items=[fx.widget_item_kwargs()],
        lines=[{"authorized_quantity": 1, "reason_code": REASON_DEFECTIVE}],
        condition_grade=GRADE_C,
    )
    world["channel"] = fx.make_channel(
        api, **fx.auction_channel_kwargs(channel_code)
    )
    return world


def test_recovery_value_switches_from_provisional_to_final_on_execution(api):
    """PRD §3.6: "Link one moves the line from `DISPOSITION_ASSIGNED` to
    `DISPOSITIONED` and replaces its `recovery_value_cents` wholesale with the
    order's `net_recovery_cents` — the final variant of the recovery estimate,
    which for the same line is normally a different number from the provisional
    estimate, and the gap between the two is exactly what the audit report
    calls recovery variance."

    Design: Difficulty/dual_variant_calc/recovery_value_provisional_vs_final_on_return_line
    """
    world = _liquidation_world(api, "CLLIQ")
    line = world["line"]

    # The provisional variant: round_half_up(20000 * 0.40 * (1 - 0.10)) * 1.
    assert_money(line["recovery_value_cents"], 7200, "provisional recovery")
    assert line["disposition"] == DISPOSITION_LIQUIDATE

    order = fx.propose_order(
        api,
        line["id"],
        channel_id=world["channel"]["id"],
        disposition=DISPOSITION_LIQUIDATE,
        quantity=1,
    )
    # The provisional variant is what freezes into the order.
    assert_money(order["unit_price_cents"], 7200, "frozen unit_price_cents")

    fx.approve_order(api, order["id"])
    executed = fx.execute_order(api, order["id"], realized_unit_price_cents=12000)

    assert_money(executed["gross_lot_value_cents"], 12000, "gross_lot_value_cents")
    assert_pct_equals(executed["effective_fee_pct"], 0.18, "effective_fee_pct")
    assert_money(executed["channel_fee_cents"], 2160, "channel_fee_cents")
    assert_money(executed["net_recovery_cents"], 9840, "net_recovery_cents")

    final_line = fx.read_return_line(api, line["id"])
    assert_money(final_line["recovery_value_cents"], 9840, "final recovery")
    assert final_line["recovery_value_cents"] != 7200

    credit = sole_entry_of_type(
        fx.list_ledger(api, world["client"]["id"]), ENTRY_RECOVERY_CREDIT
    )
    assert_money(credit["amount_cents"], 9102, "RECOVERY_CREDIT amount_cents")
    client = fx.read_client(api, world["client"]["id"])
    assert_money(client["settlement_balance_cents"], 9102, "settlement_balance_cents")


def test_audit_recovery_variance_is_the_gap_between_the_two_recovery_variants(api):
    """PRD §3.8: "It reports `recovery_variance_cents`, the sum over the
    client's `DISPOSITIONED` lines of the executed order's `net_recovery_cents`
    minus the provisional recovery estimate for that line, where the
    provisional figure is re-derived at report time from the line's current
    `condition_grade` and `reason_code` — so a repackaged line is measured
    against its post-refurbishment grade."

    Design: Difficulty/dual_variant_calc/recovery_value_provisional_vs_final_on_return_line
    """
    world = _liquidation_world(api, "CLLIQV")
    line = world["line"]
    assert_money(line["recovery_value_cents"], 7200, "provisional recovery")

    order = fx.propose_order(
        api,
        line["id"],
        channel_id=world["channel"]["id"],
        disposition=DISPOSITION_LIQUIDATE,
        quantity=1,
    )
    fx.approve_order(api, order["id"])
    fx.execute_order(api, order["id"], realized_unit_price_cents=12000)

    report = fx.read_audit(api, world["client"]["id"])
    # 9840 final less the 7200 the grade and reason still re-derive.
    assert_money(
        report["recovery_variance_cents"], 2640, "recovery_variance_cents"
    )
    assert_money(report["recovery_credit_cents"], 9102, "recovery_credit_cents")
    assert report["money_conservation_ok"] is True


def test_proposed_order_reads_zero_booked_but_a_positive_projected_balance(api):
    """PRD §3.8: "A client with one proposed liquidation order and no ledger
    rows at all therefore reads a booked balance of 0 and a projected balance of
    5461 for one particular set of inputs — the two figures are not
    interchangeable and both are reported."

    Design: Difficulty/dual_variant_calc/client_settlement_booked_vs_projected_balance
    """
    world = _liquidation_world(api, "CLLIQ2")
    order = fx.propose_order(
        api,
        world["line"]["id"],
        channel_id=world["channel"]["id"],
        disposition=DISPOSITION_LIQUIDATE,
        quantity=1,
    )
    assert_money(order["unit_price_cents"], 7200, "frozen unit_price_cents")

    ledger = fx.list_ledger(api, world["client"]["id"])
    assert ledger == [], "nothing has executed, so no ledger row may exist yet"

    report = fx.read_audit(api, world["client"]["id"])
    assert_money(report["settlement_balance_cents"], 0, "booked balance")
    assert_money(
        report["projected_settlement_balance_cents"], 5461, "projected balance"
    )


def test_execution_leaves_the_projection_below_the_booked_balance(api):
    """PRD §3.8: "It is the booked `settlement_balance_cents`, plus the ledger
    amount every `PROPOSED` or `APPROVED` disposition order of that client
    *would* append if it executed at its frozen `unit_price_cents`, minus the
    `net_refund_cents` of every refund whose line is still in
    `RELEASE_PENDING`."

    Design: Difficulty/dual_variant_calc/client_settlement_booked_vs_projected_balance
    """
    world = _liquidation_world(api, "CLPROJ")
    order = fx.propose_order(
        api,
        world["line"]["id"],
        channel_id=world["channel"]["id"],
        disposition=DISPOSITION_LIQUIDATE,
        quantity=1,
    )
    fx.approve_order(api, order["id"])
    fx.execute_order(api, order["id"], realized_unit_price_cents=12000)

    client = fx.read_client(api, world["client"]["id"])
    assert_money(client["settlement_balance_cents"], 9102, "booked balance")
    # No order left in flight, and the refund of 18000 is RELEASE_PENDING.
    assert_money(
        client["projected_settlement_balance_cents"], -8898, "projected balance"
    )
    assert client["status"] == CLIENT_STATUS_ACTIVE

    refund = fx.refund_release_for_line(api, world["line"]["id"])
    assert_money(refund["gross_refund_cents"], 20000, "gross_refund_cents")
    assert_pct_equals(refund["restocking_fee_pct"], 0.10, "restocking_fee_pct")
    assert_money(refund["restocking_fee_cents"], 2000, "restocking_fee_cents")
    assert_money(refund["net_refund_cents"], 18000, "net_refund_cents")


def test_disposition_order_creation_answers_201_with_the_frozen_economics(api):
    """PRD §4: "The single exception is proposing a disposition order, which
    creates a resource and therefore responds `201 Created`."

    Design: Difficulty/dual_variant_calc/client_settlement_booked_vs_projected_balance
    """
    world = _liquidation_world(api, "CLPROP")
    line = world["line"]
    response = api.create_disposition_order(
        {
            "return_line_id": line["id"],
            "expected_return_line_version": line["version"],
            "channel_id": world["channel"]["id"],
            "disposition": DISPOSITION_LIQUIDATE,
            "quantity": 1,
            "channel_window_start_at": "2026-08-02T08:00:00Z",
            "channel_window_end_at": "2026-08-02T12:00:00Z",
        },
        SUPERVISOR,
    )
    order = validate_success(response, 201)
    assert_money(order["unit_price_cents"], 7200, "frozen unit_price_cents")
    assert_money(order["gross_lot_value_cents"], 0, "gross_lot_value_cents")
    assert_money(order["channel_fee_cents"], 0, "channel_fee_cents")
    assert_money(order["net_recovery_cents"], 0, "net_recovery_cents")
    assert order["approved_by_user_id"] is None
    assert order["executed_by_user_id"] is None
    assert order["executed_at"] is None
