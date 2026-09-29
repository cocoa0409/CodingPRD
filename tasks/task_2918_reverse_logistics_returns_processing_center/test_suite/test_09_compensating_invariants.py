"""Compensations that must leave the invariants exactly where they started.

Cancelling a reservation and reversing a released refund are the two undo paths
in the system. Neither is allowed to mint or destroy a unit, and neither is
allowed to leave a cent of drift behind.
"""

from prd_bench_local_runner.testing import get_success_data, validate_success

from test_helpers import factories as f
from test_helpers import fixtures as fx
from test_helpers.assertions import (
    assert_conservation_flags,
    assert_line_states,
    assert_money,
    assert_pct_equals,
    assert_unit_buckets,
    plus_hours,
    sole_entry_of_type,
)
from test_helpers.constants import (
    CLOCK_STARTUP_INSTANT,
    DISPOSITION_LIQUIDATE,
    DO_CANCELLED,
    DO_EXECUTED,
    DO_PROPOSED,
    DS_DISPOSITION_ASSIGNED,
    DS_DISPOSITIONED,
    ENTRY_RECOVERY_CREDIT,
    ENTRY_REFUND_DEBIT,
    ENTRY_REVERSAL,
    FS_CLAWED_BACK,
    FS_REFUNDED,
    FS_RELEASE_PENDING,
    GRADE_C,
    REASON_DEFECTIVE,
)
from test_helpers.test_users import ANALYST, SUPERVISOR

REVERSAL_MEMO = "Chargeback won by the center"


def _two_unit_world(api, client_code):
    """One graded-C line of quantity two, and an auction channel to route it to."""
    world = fx.graded_scenario(
        api,
        client_kwargs=fx.liquidation_client_kwargs(
            client_code, name="Unit Conservation Client"
        ),
        items=[fx.widget_item_kwargs()],
        lines=[{"authorized_quantity": 2, "reason_code": REASON_DEFECTIVE}],
        condition_grade=GRADE_C,
    )
    assert world["expected_weight_grams"] == 2600
    world["channel"] = fx.make_channel(api, **fx.auction_channel_kwargs("AUC1"))
    # Two units at the per-unit provisional estimate of 7200.
    assert_money(world["line"]["recovery_value_cents"], 14400, "recovery_value_cents")
    assert_line_states(world["line"], disposition=DISPOSITION_LIQUIDATE)
    return world


def test_reserving_units_for_an_order_only_moves_them_between_buckets(api):
    """PRD §3.8: "`units_reserved_for_disposition` sums the `quantity` of that
    client's disposition orders in `PROPOSED` or `APPROVED` only; `EXECUTED` and
    `CANCELLED` orders are excluded because execution moves those units into the
    dispositioned bucket and cancellation returns them to work in process."

    Design: Difficulty/compensating_invariant/unit_conservation_survives_disposition_order_cancel
    """
    world = _two_unit_world(api, "CLUNIT")

    before = fx.read_audit(api, world["client"]["id"])
    assert_unit_buckets(before, received=2, in_process=2, reserved=0, dispositioned=0)
    assert_conservation_flags(before)

    order = fx.propose_order(api, world["line"]["id"], channel_id=world["channel"]["id"])
    assert order["status"] == DO_PROPOSED
    assert order["quantity"] == 2
    assert_money(order["unit_price_cents"], 7200, "frozen unit_price_cents")

    after = fx.read_audit(api, world["client"]["id"])
    assert_unit_buckets(after, received=2, in_process=0, reserved=2, dispositioned=0)
    assert_conservation_flags(after)
    assert after["units_received"] == before["units_received"], (
        "a reservation neither mints nor destroys a physical unit"
    )


def test_the_in_flight_order_is_visible_only_to_the_projection(api):
    """PRD §3.8: "It is the booked `settlement_balance_cents`, plus the ledger
    amount every `PROPOSED` or `APPROVED` disposition order of that client
    *would* append if it executed at its frozen `unit_price_cents`, minus the
    `net_refund_cents` of every refund whose line is still in
    `RELEASE_PENDING`."

    Design: Difficulty/compensating_invariant/unit_conservation_survives_disposition_order_cancel
    """
    world = _two_unit_world(api, "CLUNIT2")
    fx.propose_order(api, world["line"]["id"], channel_id=world["channel"]["id"])

    report = fx.read_audit(api, world["client"]["id"])
    assert_money(report["settlement_balance_cents"], 0, "booked balance")
    # Projected gross 14400, less the 0.18 clamped fee of 2592, less the 7.5
    # percent handling share of 886 on the resulting 11808.
    assert_money(
        report["projected_settlement_balance_cents"], 10922, "projected balance"
    )
    assert fx.list_ledger(api, world["client"]["id"]) == [], (
        "a proposed order appends nothing to the ledger"
    )
    assert_money(report["recovery_credit_cents"], 0, "recovery_credit_cents")
    assert_conservation_flags(report)


def test_cancelling_the_order_restores_the_exact_bucket_distribution(api):
    """PRD §3.8: "After every single request, `units_received` must equal the sum
    of the other three buckets exactly."

    Design: Difficulty/compensating_invariant/unit_conservation_survives_disposition_order_cancel
    """
    world = _two_unit_world(api, "CLUNIT3")
    order = fx.propose_order(api, world["line"]["id"], channel_id=world["channel"]["id"])

    cancelled = get_success_data(
        api.cancel_disposition_order(
            order["id"],
            f.cancel_payload("Buyer withdrew from the lot"),
            SUPERVISOR,
        )
    )
    assert cancelled["status"] == DO_CANCELLED

    report = fx.read_audit(api, world["client"]["id"])
    assert_unit_buckets(report, received=2, in_process=2, reserved=0, dispositioned=0)
    assert_conservation_flags(report)
    assert_money(report["settlement_balance_cents"], 0, "booked balance")
    assert_money(
        report["projected_settlement_balance_cents"], 0, "projected balance"
    )
    assert fx.list_ledger(api, world["client"]["id"]) == [], (
        "the compensation may leave no ledger residue"
    )

    # The line is orderable again, which is what makes the undo complete.
    line = fx.read_return_line(api, world["line"]["id"])
    assert_line_states(line, disposition_state=DS_DISPOSITION_ASSIGNED)
    replacement = fx.propose_order(
        api, line["id"], channel_id=world["channel"]["id"]
    )
    assert replacement["status"] == DO_PROPOSED
    assert replacement["quantity"] == 2


def _executed_world(api, client_code):
    """One executed liquidation whose lot landed exactly on the mid-lot floor.

    The clock is then moved 72 hours past startup, which clears the client's
    48-hour refund hold without touching the authorization's expiry.
    """
    world = fx.graded_scenario(
        api,
        client_kwargs=fx.liquidation_client_kwargs(
            client_code, name="Money Conservation Client"
        ),
        items=[fx.widget_item_kwargs()],
        lines=[{"authorized_quantity": 1, "reason_code": REASON_DEFECTIVE}],
        condition_grade=GRADE_C,
    )
    world["channel"] = fx.make_channel(api, **fx.auction_channel_kwargs("AUC1"))
    order = fx.propose_and_approve(
        api, world["line"]["id"], channel_id=world["channel"]["id"]
    )
    executed = fx.execute_order(api, order["id"], realized_unit_price_cents=25000)
    assert executed["status"] == DO_EXECUTED
    # A gross lot of exactly 25000 is a mid lot, so no surcharge applies.
    assert_money(executed["gross_lot_value_cents"], 25000, "gross_lot_value_cents")
    assert_pct_equals(executed["effective_fee_pct"], 0.12, "effective_fee_pct")
    assert_money(executed["channel_fee_cents"], 3000, "channel_fee_cents")
    assert_money(executed["net_recovery_cents"], 22000, "net_recovery_cents")
    world["order"] = executed
    world["pre_release_balance_cents"] = 20350

    client = fx.read_client(api, world["client"]["id"])
    assert_money(
        client["settlement_balance_cents"], 20350, "settlement_balance_cents"
    )
    fx.set_clock(api, plus_hours(CLOCK_STARTUP_INSTANT, 72))
    return world


def test_the_release_debit_is_the_negation_of_the_stored_net_refund(api):
    """PRD §3.8: "A `REFUND_DEBIT` carries the negative of the refund's
    `net_refund_cents`, a `REVERSAL` the positive of the same figure, a
    `REFURB_COST` the negative of a work order's `total_cost_cents`, and a
    `RECEIPT_VARIANCE` the negative of an authorization line's unreceived
    shortfall multiplied by the item's `declared_value_cents`."

    Design: Difficulty/compensating_invariant/settlement_balance_conservation_survives_refund_reversal
    """
    world = _executed_world(api, "CLMONEY")
    line = fx.read_return_line(api, world["line"]["id"])
    assert_line_states(
        line,
        disposition_state=DS_DISPOSITIONED,
        financial_state=FS_RELEASE_PENDING,
    )

    released = validate_success(api.release_refund(line["id"], ANALYST), 200)
    assert_line_states(released, financial_state=FS_REFUNDED)

    refund = fx.refund_release_for_line(api, line["id"])
    assert_money(refund["net_refund_cents"], 18000, "net_refund_cents")

    debit = sole_entry_of_type(
        fx.list_ledger(api, world["client"]["id"]), ENTRY_REFUND_DEBIT
    )
    assert_money(debit["amount_cents"], -18000, "REFUND_DEBIT amount_cents")

    report = fx.read_audit(api, world["client"]["id"])
    assert_money(report["settlement_balance_cents"], 2350, "settlement_balance_cents")
    assert_money(report["recovery_credit_cents"], 20350, "recovery_credit_cents")
    assert_money(report["refund_debit_cents"], -18000, "refund_debit_cents")
    assert_money(report["reversal_cents"], 0, "reversal_cents")
    assert_conservation_flags(report)


def test_the_reversal_returns_the_balance_to_precisely_its_pre_release_value(api):
    """PRD §3.7: "The reversal entry exactly offsets the earlier `REFUND_DEBIT`
    entry, so the client's recomputed `settlement_balance_cents` returns to
    precisely its pre-release value; and when that recomputed balance climbs back
    to or above the negation of `max_refund_exposure_cents`, a `SUSPENDED` client
    returns to `ACTIVE` in the same request."

    Design: Difficulty/compensating_invariant/settlement_balance_conservation_survives_refund_reversal
    """
    world = _executed_world(api, "CLMONEY2")
    line_id = world["line"]["id"]
    validate_success(api.release_refund(line_id, ANALYST), 200)

    reversed_line = validate_success(
        api.reverse_refund(
            line_id, f.reverse_refund_payload(REVERSAL_MEMO), ANALYST
        ),
        200,
    )
    assert_line_states(reversed_line, financial_state=FS_CLAWED_BACK)
    # Reversing the money never rewinds the physical dimension.
    assert_line_states(reversed_line, disposition_state=DS_DISPOSITIONED)
    assert fx.refund_release_for_line(api, line_id)["reversed_at"] is not None

    entries = fx.list_ledger(api, world["client"]["id"])
    reversal = sole_entry_of_type(entries, ENTRY_REVERSAL)
    assert_money(reversal["amount_cents"], 18000, "REVERSAL amount_cents")
    assert REVERSAL_MEMO in reversal["memo"]
    assert len(entries) == 3, "the compensation is an append, never an edit"
    assert_money(
        sole_entry_of_type(entries, ENTRY_RECOVERY_CREDIT)["amount_cents"],
        20350,
        "RECOVERY_CREDIT amount_cents",
    )

    report = fx.read_audit(api, world["client"]["id"])
    assert_money(
        report["settlement_balance_cents"],
        world["pre_release_balance_cents"],
        "settlement_balance_cents",
    )
    assert_money(report["reversal_cents"], 18000, "reversal_cents")
    assert_money(report["refund_debit_cents"], -18000, "refund_debit_cents")
    assert_conservation_flags(report)
