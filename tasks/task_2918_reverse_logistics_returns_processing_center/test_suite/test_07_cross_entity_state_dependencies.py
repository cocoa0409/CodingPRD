"""Transitions that a *different* entity's state alone decides.

Each world below is left perfectly valid on the entity being acted upon; the
only thing standing in the way is the status of a channel, a client or a
sibling return line.
"""

from prd_bench_local_runner.testing import get_success_data, validate_error

from test_helpers import factories as f
from test_helpers import fixtures as fx
from test_helpers.api_errors import ERR_CHANNEL_PAUSED, ERR_CLIENT_SUSPENDED
from test_helpers.assertions import (
    assert_line_states,
    assert_money,
    assert_pct_equals,
    assert_unit_buckets,
    entries_of_type,
    sole_entry_of_type,
)
from test_helpers.constants import (
    CHANNEL_STATUS_ACTIVE,
    CHANNEL_STATUS_PAUSED,
    CLIENT_STATUS_ACTIVE,
    CLIENT_STATUS_SUSPENDED,
    DISPOSITION_LIQUIDATE,
    DO_APPROVED,
    DO_EXECUTED,
    DS_DISPOSITION_ASSIGNED,
    DS_DISPOSITIONED,
    ENTRY_RECOVERY_CREDIT,
    FS_HOLD_PENDING_DISPOSITION,
    FS_RELEASE_PENDING,
    GRADE_C,
    REASON_DEFECTIVE,
    RMA_CLOSED,
    RMA_ISSUED,
    RMA_RECEIVED,
)
from test_helpers.test_users import ADMIN, CLERK, SUPERVISOR


def _approved_order_on_a_channel(api, client_code, channel_code="AUC1"):
    """A graded-C line with an APPROVED liquidation order on an ACTIVE channel."""
    world = fx.graded_scenario(
        api,
        client_kwargs=fx.liquidation_client_kwargs(client_code),
        items=[fx.widget_item_kwargs()],
        lines=[{"authorized_quantity": 1, "reason_code": REASON_DEFECTIVE}],
        condition_grade=GRADE_C,
    )
    world["channel"] = fx.make_channel(api, **fx.auction_channel_kwargs(channel_code))
    assert_line_states(
        world["line"],
        disposition_state=DS_DISPOSITION_ASSIGNED,
        financial_state=FS_HOLD_PENDING_DISPOSITION,
        disposition=DISPOSITION_LIQUIDATE,
    )
    order = fx.propose_order(
        api, world["line"]["id"], channel_id=world["channel"]["id"]
    )
    world["order"] = fx.approve_order(api, order["id"])
    assert world["order"]["status"] == DO_APPROVED
    return world


def _pause(api, channel_id, reason="Marketplace outage"):
    """Pause a channel as a CenterAdmin and return the paused channel."""
    return get_success_data(
        api.pause_channel(channel_id, ADMIN, {"pause_reason": reason})
    )


def test_a_channel_paused_after_approval_still_blocks_the_execution(api):
    """PRD §2.6: "Priority 27 requires the resolved channel's `status` to be
    `ACTIVE` at both proposal and execution; a `PAUSED` channel accepts neither
    new disposition orders nor execution of orders already routed to it, and the
    code is `ERR_CHANNEL_PAUSED`."

    Design: Difficulty/cross_entity_state_dependency/disposition_order_execution_blocked_by_paused_channel
    """
    world = _approved_order_on_a_channel(api, "CLXCHAN")
    paused = _pause(api, world["channel"]["id"])
    assert paused["status"] == CHANNEL_STATUS_PAUSED

    response = api.execute_disposition_order(world["order"]["id"], SUPERVISOR, {})
    validate_error(response, ERR_CHANNEL_PAUSED, 409)

    # The order itself was flawless: nothing about it changed.
    order = fx.read_order(api, world["order"]["id"])
    assert order["status"] == DO_APPROVED
    assert order["executed_at"] is None
    assert order["executed_by_user_id"] is None
    assert_money(order["gross_lot_value_cents"], 0, "gross_lot_value_cents")
    assert_money(order["net_recovery_cents"], 0, "net_recovery_cents")

    line = fx.read_return_line(api, world["line"]["id"])
    assert_line_states(
        line,
        disposition_state=DS_DISPOSITION_ASSIGNED,
        financial_state=FS_HOLD_PENDING_DISPOSITION,
    )
    client = fx.read_client(api, world["client"]["id"])
    assert_money(client["settlement_balance_cents"], 0, "settlement_balance_cents")
    assert fx.list_ledger(api, world["client"]["id"]) == [], (
        "a refused execution may not append a ledger row"
    )


def test_resuming_the_channel_lets_the_identical_execution_through(api):
    """PRD §3.1: "A `CenterAdmin` or `DispositionSupervisor` may pause a
    channel, optionally recording a `pause_reason`, which moves its `status` to
    `PAUSED`, removes it from the selector's candidate set and blocks execution
    of orders already routed to it; resuming returns it to `ACTIVE`."

    Design: Difficulty/cross_entity_state_dependency/disposition_order_execution_blocked_by_paused_channel
    """
    world = _approved_order_on_a_channel(api, "CLXCHAN2")
    _pause(api, world["channel"]["id"])
    validate_error(
        api.execute_disposition_order(world["order"]["id"], SUPERVISOR, {}),
        ERR_CHANNEL_PAUSED,
        409,
    )

    resumed = get_success_data(api.resume_channel(world["channel"]["id"], ADMIN))
    assert resumed["status"] == CHANNEL_STATUS_ACTIVE

    executed = fx.execute_order(api, world["order"]["id"])
    assert executed["status"] == DO_EXECUTED
    assert_money(executed["gross_lot_value_cents"], 7200, "gross_lot_value_cents")
    # 7200 is a small lot, so 0.12 plus the 0.06 surcharge.
    assert_pct_equals(executed["effective_fee_pct"], 0.18, "effective_fee_pct")
    assert_money(executed["channel_fee_cents"], 1296, "channel_fee_cents")
    assert_money(executed["net_recovery_cents"], 5904, "net_recovery_cents")

    line = fx.read_return_line(api, world["line"]["id"])
    assert_line_states(
        line,
        disposition_state=DS_DISPOSITIONED,
        financial_state=FS_RELEASE_PENDING,
    )
    credit = sole_entry_of_type(
        fx.list_ledger(api, world["client"]["id"]), ENTRY_RECOVERY_CREDIT
    )
    assert_money(credit["amount_cents"], 5461, "RECOVERY_CREDIT amount_cents")
    client = fx.read_client(api, world["client"]["id"])
    assert_money(client["settlement_balance_cents"], 5461, "settlement_balance_cents")


def _issued_rma_on_a_suspended_client(api, client_code):
    """An issued authorization whose owning client is then suspended."""
    world = fx.received_scenario(
        api,
        client_kwargs=fx.liquidation_client_kwargs(client_code),
        items=[fx.widget_item_kwargs()],
        lines=[{"authorized_quantity": 1, "reason_code": REASON_DEFECTIVE}],
        scan=False,
    )
    assert world["rma"]["status"] == RMA_ISSUED
    suspended = get_success_data(
        api.suspend_client(
            world["client"]["id"], ADMIN, {"suspension_reason": "Balance review"}
        )
    )
    assert suspended["status"] == CLIENT_STATUS_SUSPENDED
    return world


def test_a_suspended_client_blocks_the_dock_even_on_a_flawless_authorization(api):
    """PRD §2.10: "Suspension halts everything that would increase the center's
    exposure to that retailer: no new return authorizations, no new
    authorization lines, no issuing, no new receipts, no new scanned unit lines,
    no new disposition orders and no refund releases."

    Design: Difficulty/cross_entity_state_dependency/receipt_creation_blocked_by_suspended_client
    """
    world = _issued_rma_on_a_suspended_client(api, "CLXSUSP")

    response = api.create_receipt(
        f.receipt_payload(
            world["rma"]["id"],
            tracking_reference="TRK-17A",
            gross_weight_grams=world["expected_weight_grams"],
        ),
        CLERK,
    )
    validate_error(response, ERR_CLIENT_SUSPENDED, 409)

    # The authorization was never the problem: it is ISSUED and its expiry is a
    # calendar month after the current logical time.
    rma = fx.read_rma(api, world["rma"]["id"])
    assert rma["status"] == RMA_ISSUED
    receipts = get_success_data(
        api.list_receipts(ADMIN, {"rma_id": world["rma"]["id"], "limit": 100})
    )
    assert receipts == [], "the refused scan may not leave a Receipt behind"


def test_reinstating_the_client_admits_the_very_same_carton(api):
    """PRD §2.10: "A `CenterAdmin` may suspend a client explicitly, optionally
    recording a `suspension_reason`, and may later reinstate it to `ACTIVE`."

    Design: Difficulty/cross_entity_state_dependency/receipt_creation_blocked_by_suspended_client
    """
    world = _issued_rma_on_a_suspended_client(api, "CLXSUSP2")
    validate_error(
        api.create_receipt(
            f.receipt_payload(
                world["rma"]["id"],
                tracking_reference="TRK-17A",
                gross_weight_grams=world["expected_weight_grams"],
            ),
            CLERK,
        ),
        ERR_CLIENT_SUSPENDED,
        409,
    )

    reinstated = get_success_data(
        api.reinstate_client(world["client"]["id"], ADMIN)
    )
    assert reinstated["status"] == CLIENT_STATUS_ACTIVE

    receipt = fx.make_receipt(
        api,
        world["rma"]["id"],
        world["expected_weight_grams"],
        tracking_reference="TRK-17B",
    )
    # The 200-gram tare plus one 1200-gram unit.
    assert receipt["expected_weight_grams"] == 1400
    assert receipt["gross_weight_grams"] == 1400
    assert receipt["empty_box_suspected"] is False


def _two_sibling_lines_ready_to_disposition(api, client_code):
    """One authorization with two graded-C lines, each carrying an APPROVED order."""
    world = fx.graded_scenario(
        api,
        client_kwargs=fx.liquidation_client_kwargs(client_code),
        items=[fx.widget_item_kwargs()],
        lines=[
            {"authorized_quantity": 1, "reason_code": REASON_DEFECTIVE},
            {"authorized_quantity": 1, "reason_code": REASON_DEFECTIVE},
        ],
        condition_grade=GRADE_C,
    )
    world["channel"] = fx.make_channel(api, **fx.auction_channel_kwargs("AUC1"))
    world["orders"] = [
        fx.propose_and_approve(api, line["id"], channel_id=world["channel"]["id"])
        for line in world["lines"]
    ]
    return world


def test_one_undispositioned_sibling_holds_the_authorization_open(api):
    """PRD §3.2: "Much later, an authorization in `RECEIVED` becomes `CLOSED`
    when the last of its lines reaches `DISPOSITIONED`: the parent bubbles up to
    closure only after every child is settled, and closing recomputes the
    client's `open_rma_count` and advances the authorization's `version`."

    Design: Difficulty/cross_entity_state_dependency/rma_close_depends_on_every_sibling_return_line_dispositioned
    """
    world = _two_sibling_lines_ready_to_disposition(api, "CLXBUB")
    # One carton covered both authorized units, so the parent is already RECEIVED.
    assert fx.read_rma(api, world["rma"]["id"])["status"] == RMA_RECEIVED

    fx.execute_order(api, world["orders"][0]["id"])

    first = fx.read_return_line(api, world["lines"][0]["id"])
    second = fx.read_return_line(api, world["lines"][1]["id"])
    assert_line_states(first, disposition_state=DS_DISPOSITIONED)
    assert_line_states(second, disposition_state=DS_DISPOSITION_ASSIGNED)

    rma = fx.read_rma(api, world["rma"]["id"])
    assert rma["status"] == RMA_RECEIVED, (
        "one line short of DISPOSITIONED keeps the parent open"
    )

    client = fx.read_client(api, world["client"]["id"])
    assert_money(client["settlement_balance_cents"], 5461, "settlement_balance_cents")
    assert_unit_buckets(client, received=2, in_process=0, reserved=1, dispositioned=1)
    assert client["open_rma_count"] == 1


def test_the_second_disposition_closes_the_parent_authorization(api):
    """PRD §3.2: "Issue stamps `issued_at` from the logical clock, advances the
    authorization's `version` by one, and recomputes the client's
    `open_rma_count`, which counts that client's authorizations in `ISSUED`,
    `PARTIALLY_RECEIVED` or `RECEIVED`."

    Design: Difficulty/cross_entity_state_dependency/rma_close_depends_on_every_sibling_return_line_dispositioned
    """
    world = _two_sibling_lines_ready_to_disposition(api, "CLXBUB2")
    before = fx.read_rma(api, world["rma"]["id"])
    assert before["status"] == RMA_RECEIVED

    fx.execute_order(api, world["orders"][0]["id"])
    fx.execute_order(api, world["orders"][1]["id"])

    rma = fx.read_rma(api, world["rma"]["id"])
    assert rma["status"] == RMA_CLOSED
    assert rma["version"] > before["version"]

    client = fx.read_client(api, world["client"]["id"])
    assert client["open_rma_count"] == 0, (
        "a CLOSED authorization is none of ISSUED, PARTIALLY_RECEIVED or RECEIVED"
    )
    assert_money(client["settlement_balance_cents"], 10922, "settlement_balance_cents")
    assert_unit_buckets(client, received=2, in_process=0, reserved=0, dispositioned=2)

    credits = entries_of_type(
        fx.list_ledger(api, world["client"]["id"]), ENTRY_RECOVERY_CREDIT
    )
    assert len(credits) == 2, "each execution appends its own recovery credit"
    for credit in credits:
        assert_money(credit["amount_cents"], 5461, "RECOVERY_CREDIT amount_cents")
