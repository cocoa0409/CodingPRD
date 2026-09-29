"""Every link of the execute cascade is visible in the first read that follows it."""

from prd_bench_local_runner.testing import validate_paginated

from test_helpers import fixtures as fx
from test_helpers.assertions import (
    assert_instant_equals,
    assert_line_states,
    assert_money,
    expected_recovery_credit,
)
from test_helpers.constants import (
    CHANNEL_TYPE_BULK_LIQUIDATOR,
    CLOCK_STARTUP_INSTANT,
    DO_EXECUTED,
    DS_DISPOSITIONED,
    FS_RELEASE_PENDING,
    GRADE_C,
    GRADE_D,
    REASON_DEFECTIVE,
    RMA_CLOSED,
    USER_SUPERVISOR_2,
)
from test_helpers.test_users import ADMIN, SUPERVISOR, SUPERVISOR_2

LOT_WINDOW_START = "2026-08-03T08:00:00Z"
LOT_WINDOW_END = "2026-08-03T12:00:00Z"


def test_the_whole_execute_cascade_is_readable_without_a_second_call(api):
    """PRD §3.6: "Link one moves the line from `DISPOSITION_ASSIGNED` to
    `DISPOSITIONED` and replaces its `recovery_value_cents` wholesale with the
    order's `net_recovery_cents` — the final variant of the recovery estimate, which
    for the same line is normally a different number from the provisional estimate,
    and the gap between the two is exactly what the audit report calls recovery
    variance."

    Design: Corner/consistency_model/corner_cm_execute_cascade_is_visible_immediately_in_every_read
    """
    channel = fx.make_channel(api, **fx.auction_channel_kwargs(
        channel_code="BL-CC5", name="Bulk Liquidators",
        channel_type=CHANNEL_TYPE_BULK_LIQUIDATOR,
        accepted_grades=[GRADE_C, GRADE_D], min_lot_value_cents=1000))
    world = fx.graded_scenario(
        api,
        client_kwargs=fx.liquidation_client_kwargs("CC5", name="Ccl Five"),
        items=[fx.widget_item_kwargs()],
        lines=[{"authorized_quantity": 1, "reason_code": REASON_DEFECTIVE}],
        condition_grade=GRADE_C,
        tracking_reference="TRK-CC5",
    )
    client_id = world["client"]["id"]
    line_id = world["line"]["id"]
    rma_id = world["rma"]["id"]
    order = fx.propose_and_approve(
        api,
        line_id,
        channel_id=channel["id"],
        window_start_at=LOT_WINDOW_START,
        window_end_at=LOT_WINDOW_END,
        approver=SUPERVISOR,
    )

    # The execute response is itself already stamped, not queued.
    executed = fx.execute_order(api, order["id"], headers=SUPERVISOR_2)
    assert executed["status"] == DO_EXECUTED
    assert executed["executed_by_user_id"] == USER_SUPERVISOR_2
    assert_instant_equals(
        executed["executed_at"], CLOCK_STARTUP_INSTANT, "executed_at is the clock"
    )

    line = fx.read_return_line(api, line_id)
    assert_line_states(
        line,
        disposition_state=DS_DISPOSITIONED,
        financial_state=FS_RELEASE_PENDING,
    )
    assert_money(line["recovery_value_cents"], 5904, "the realized net replaced it")

    rma = fx.read_rma(api, rma_id)
    assert rma["status"] == RMA_CLOSED, (
        "the authorization's only line reached DISPOSITIONED in the same request"
    )

    entries, ledger_meta = validate_paginated(
        api.list_shrink_ledger_entries(ADMIN, {"client_id": client_id, "limit": 10})
    )
    assert ledger_meta["total_count"] == 1
    assert_money(
        entries[0]["amount_cents"],
        expected_recovery_credit(5904),
        "one recovery credit net of the handling share",
    )

    client = fx.read_client(api, client_id)
    assert client["units_dispositioned"] == 1
    assert client["units_reserved_for_disposition"] == 0
    assert client["units_in_process"] == 0
    assert_money(client["settlement_balance_cents"], 5461, "booked immediately")

    # Nothing settles late: the same four reads repeat identically.
    assert fx.read_return_line(api, line_id) == line
    assert fx.read_rma(api, rma_id) == rma
    assert fx.list_ledger(api, client_id) == entries
    assert fx.read_client(api, client_id) == client

    audit = fx.read_audit(api, client_id)
    assert audit["unit_conservation_ok"] is True
    assert audit["money_conservation_ok"] is True
