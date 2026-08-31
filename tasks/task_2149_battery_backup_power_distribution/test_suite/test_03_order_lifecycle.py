"""Order lifecycle: submission gates, cancellation unwinds and ledger conservation."""
import pytest

from test_helpers import (
    validate_error, ApiErrorId, api_client, TEST_USERS,
    create_warehouse, create_account, create_battery_model, create_order, add_line,
    submit_order, allocate_order, cancel_order, read_order, read_order_line,
    read_account, read_lot, receive_lot, setup_base_env, setup_account_in_credit_hold,
)

REP = TEST_USERS["sales_rep_headers"]
OPERATOR = TEST_USERS["warehouse_operator_headers"]


# --------------------------------------------------------------------------
# Submission gates
# --------------------------------------------------------------------------

def _order_at_its_credit_ceiling():
    """One submitted order whose total exactly consumes the account's credit limit."""
    warehouse = create_warehouse(code="TX-DAL", state_code="TX", hazmat_endorsement=True,
                                 storm_reserve_pct=0.0, dock_capacity_kg_per_window=100000.0)
    account = create_account(name="Lone Star Backup", account_tier="STANDARD",
                             state_code="TX", credit_limit_cents=118080,
                             storm_priority_rank=9)
    model = create_battery_model("IB-AGM-95")
    order = create_order(account["id"], warehouse["id"], requested_ship_date="2026-08-11")
    add_line(order["id"], model["id"], 4, core_expected_count=0)
    submitted = submit_order(order["id"])
    return {"account": account, "order": submitted, "warehouse": warehouse, "model": model}


def test_resubmitting_a_submitted_order_reports_the_state_failure(api):
    """PRD §2.6: "Checks are evaluated in a fixed order and the **first** one
    that fails decides the response; no later check can mask an earlier one, and
    no earlier check is skipped because a later one looks more specific."
    PRD §3.3: "Four gates guard it, and because the rejection ladder is strict
    they are reported in this relative order: the order must stand in `DRAFT`,
    and any other fulfilment status is `ERR_INVALID_STATE`; the buying account's
    `status` must be `ACTIVE`, and an account sitting in `CREDIT_HOLD` yields
    `ERR_ACCOUNT_NOT_ACTIVE` (HTTP 409); the order must carry at least one line,
    and an empty order yields `ERR_ORDER_HAS_NO_LINES` (HTTP 422); and the
    priced order must fit inside the account's credit headroom."

    Design: Difficulty/priority_pair_validation_conflict/order_state_outranks_credit_limit_on_resubmit
    """
    ctx = _order_at_its_credit_ceiling()
    assert ctx["order"]["total_cents"] == 118080

    resp = api.submit_order(ctx["order"]["id"], REP)
    error = validate_error(resp, ApiErrorId.ERR_INVALID_STATE.value)
    assert error["error_id"] != ApiErrorId.ERR_CREDIT_LIMIT_EXCEEDED.value, \
        "The state rung outranks the fiscal rung"


def test_rejected_resubmission_leaves_the_receivable_untouched(api):
    """PRD §3.3: "That last check is evaluated against the freshly computed
    total: the order's `total_cents` plus the account's `open_receivable_cents`
    minus the account's `warranty_credit_cents` must be no greater than the
    account's `credit_limit_cents`, and a breach is refused with
    `ERR_CREDIT_LIMIT_EXCEEDED` (HTTP 402)."
    PRD §3.3: "It then books the money: the account's `open_receivable_cents`
    increases by the order's `total_cents`."

    Design: Difficulty/priority_pair_validation_conflict/order_state_outranks_credit_limit_on_resubmit
    """
    ctx = _order_at_its_credit_ceiling()
    assert read_account(ctx["account"]["id"])["open_receivable_cents"] == 118080

    api.submit_order(ctx["order"]["id"], REP)

    account = read_account(ctx["account"]["id"])
    assert account["open_receivable_cents"] == 118080, \
        f"A refused submit books nothing, got {account['open_receivable_cents']}"
    assert read_order(ctx["order"]["id"])["fulfillment_status"] == "SUBMITTED"


def _draft_order_with_no_lines():
    warehouse = create_warehouse(code="TX-DAL", state_code="TX", hazmat_endorsement=True,
                                 storm_reserve_pct=0.0, dock_capacity_kg_per_window=100000.0)
    account = create_account(name="Empty Cart Co", account_tier="STANDARD",
                             state_code="TX", credit_limit_cents=100000000,
                             storm_priority_rank=9)
    order = create_order(account["id"], warehouse["id"], requested_ship_date="2026-08-15")
    return {"warehouse": warehouse, "account": account, "order": order}


def test_submitting_a_lineless_order_is_refused(api):
    """PRD §3.3: "the order must carry at least one line, and an empty order
    yields `ERR_ORDER_HAS_NO_LINES` (HTTP 422)"
    PRD §3.3: "Each successful line increments the order's `line_count`; the
    order's money fields remain zero until submission."

    Design: Difficulty/boundary_precision_check/submit_rejects_order_holding_zero_lines
    """
    ctx = _draft_order_with_no_lines()
    assert ctx["order"]["line_count"] == 0

    resp = api.submit_order(ctx["order"]["id"], REP)
    validate_error(resp, ApiErrorId.ERR_ORDER_HAS_NO_LINES.value)


def test_lineless_order_keeps_both_state_dimensions_and_every_money_field(api):
    """PRD §3.3: "A new order opens with `fulfillment_status` at `DRAFT` and
    `credit_status` at `PENDING`, and every money field at zero."
    PRD §3.3: "A successful submission advances `fulfillment_status` from
    `DRAFT` to `SUBMITTED` and, on the independent credit dimension, advances
    `credit_status` from `PENDING` to `CLEARED`."

    Design: Difficulty/boundary_precision_check/submit_rejects_order_holding_zero_lines
    """
    ctx = _draft_order_with_no_lines()
    api.submit_order(ctx["order"]["id"], REP)

    order = read_order(ctx["order"]["id"])
    assert order["fulfillment_status"] == "DRAFT"
    assert order["credit_status"] == "PENDING"
    assert order["subtotal_cents"] == 0
    assert order["total_cents"] == 0
    assert read_account(ctx["account"]["id"])["open_receivable_cents"] == 0


def test_submit_is_refused_while_the_buying_account_sits_in_credit_hold(api):
    """PRD §3.3: "the buying account's `status` must be `ACTIVE`, and an account
    sitting in `CREDIT_HOLD` yields `ERR_ACCOUNT_NOT_ACTIVE` (HTTP 409)"
    PRD §3.5: "**Hop four** reacts to that increase: if the account's
    core-deposit liability now stands at or above 500000 cents — five thousand
    dollars of outstanding core obligation — and the account's `status` is
    `ACTIVE`, the account moves to `CREDIT_HOLD`."

    Design: Difficulty/cross_entity_state_dependency/order_submit_requires_account_status_active
    """
    env = setup_account_in_credit_hold()
    account = read_account(env["account"]["id"])
    assert account["status"] == "CREDIT_HOLD"
    assert account["core_deposit_balance_cents"] == 600000

    order_c = create_order(env["account"]["id"], env["warehouse"]["id"],
                           requested_ship_date="2026-09-01")
    add_line(order_c["id"], env["model"]["id"], 1, core_expected_count=0)

    resp = api.submit_order(order_c["id"], REP)
    validate_error(resp, ApiErrorId.ERR_ACCOUNT_NOT_ACTIVE.value)


def test_order_refused_for_credit_hold_is_left_completely_unpriced(api):
    """PRD §3.1: "A new account opens with `status` set to `ACTIVE` — the only
    other posture is `CREDIT_HOLD`, and only `ACTIVE` permits order submission —
    and with all four of its ledger fields at zero: `open_receivable_cents`,
    `core_deposit_balance_cents`, `warranty_credit_cents` and
    `lifetime_lead_recovered_kg`, the last of which is a cumulative lead mass
    carried to three decimals."

    Design: Difficulty/cross_entity_state_dependency/order_submit_requires_account_status_active
    """
    env = setup_account_in_credit_hold()
    order_c = create_order(env["account"]["id"], env["warehouse"]["id"],
                           requested_ship_date="2026-09-01")
    add_line(order_c["id"], env["model"]["id"], 1, core_expected_count=0)

    api.submit_order(order_c["id"], REP)

    order = read_order(order_c["id"])
    assert order["fulfillment_status"] == "DRAFT"
    assert order["credit_status"] == "PENDING"
    assert order["total_cents"] == 0


# --------------------------------------------------------------------------
# Compensating invariants
# --------------------------------------------------------------------------

def _allocated_twelve_unit_order():
    env = setup_base_env(
        "IB-31-FLD",
        account_overrides={"name": "Delta Fleet", "storm_priority_rank": 5},
        lot_overrides={"manufactured_on": "2026-06-01", "quantity_on_hand": 40},
        with_carrier=False,
    )
    order = create_order(env["account"]["id"], env["warehouse"]["id"],
                         requested_ship_date="2026-08-10")
    line = add_line(order["id"], env["model"]["id"], 12, core_expected_count=0)
    order = submit_order(order["id"])
    order = allocate_order(order["id"])
    env["order"] = order
    env["line"] = line
    return env


def test_allocation_reserves_units_without_moving_the_units_on_hand():
    """PRD §3.4: "A successful allocation writes `allocation_priority_score`
    onto the order, advances `fulfillment_status` from `SUBMITTED` to
    `ALLOCATED`, and for each line writes the chosen lot into
    `allocated_lot_id`, sets `allocated_quantity` equal to the line's
    `quantity`, and increments that lot's `quantity_reserved` by the same
    amount, with `quantity_available` re-derived."
    PRD §3.4: "Note carefully that `quantity_on_hand` does **not** move at
    allocation; the units are still physically in the building and only a
    reservation has been placed."

    Design: Difficulty/compensating_invariant/allocate_then_cancel_conserves_reserved_unit_count
    """
    env = _allocated_twelve_unit_order()
    assert env["order"]["total_cents"] == 260290

    lot = read_lot(env["lot"]["id"])
    assert lot["quantity_reserved"] == 12, f"Expected 12 reserved, got {lot['quantity_reserved']}"
    assert lot["quantity_available"] == 28, f"Expected 28 available, got {lot['quantity_available']}"
    assert lot["quantity_on_hand"] == 40, f"Expected 40 on hand, got {lot['quantity_on_hand']}"


def test_cancelling_an_allocated_order_returns_every_reserved_unit():
    """PRD §3.3: "From `ALLOCATED`, the receivable is reversed the same way; in
    addition, for every line carrying a non-null `allocated_lot_id` the platform
    decrements that lot's `quantity_reserved` by the line's `allocated_quantity`
    and then clears `allocated_lot_id` and resets `allocated_quantity` to 0"
    PRD §3.3: "What it unwinds depends on how far the order had travelled, and
    in all three cases it drives `credit_status` to `CLOSED`."

    Design: Difficulty/compensating_invariant/allocate_then_cancel_conserves_reserved_unit_count
    """
    env = _allocated_twelve_unit_order()
    cancel_order(env["order"]["id"], "Customer deferred the retrofit to next quarter.")

    lot = read_lot(env["lot"]["id"])
    assert lot["quantity_reserved"] == 0, f"Expected 0 reserved, got {lot['quantity_reserved']}"
    assert lot["quantity_available"] == 40, f"Expected 40 available, got {lot['quantity_available']}"
    assert lot["quantity_on_hand"] == 40, "quantity_on_hand is untouched by cancellation"

    line = read_order_line(env["line"]["id"])
    assert line["allocated_lot_id"] is None
    assert line["allocated_quantity"] == 0

    order = read_order(env["order"]["id"])
    assert order["fulfillment_status"] == "CANCELLED"
    assert order["credit_status"] == "CLOSED"


def _submitted_four_unit_order():
    warehouse = create_warehouse(code="TX-DAL", state_code="TX", hazmat_endorsement=True,
                                 storm_reserve_pct=0.0, dock_capacity_kg_per_window=100000.0)
    account = create_account(name="Lone Star Backup", account_tier="STANDARD",
                             state_code="TX", credit_limit_cents=100000000,
                             storm_priority_rank=9)
    model = create_battery_model("IB-AGM-95")
    order = create_order(account["id"], warehouse["id"], requested_ship_date="2026-08-11")
    add_line(order["id"], model["id"], 4, core_expected_count=0)
    return {"warehouse": warehouse, "account": account, "model": model, "order": order}


def test_submission_books_the_order_total_onto_the_account_receivable():
    """PRD §3.3: "It then books the money: the account's
    `open_receivable_cents` increases by the order's `total_cents`. Nothing else
    moves — no stock is reserved and no storm pool is drawn at submission."

    Design: Difficulty/compensating_invariant/submit_then_cancel_conserves_account_open_receivable
    """
    ctx = _submitted_four_unit_order()
    assert read_account(ctx["account"]["id"])["open_receivable_cents"] == 0

    submitted = submit_order(ctx["order"]["id"])
    assert submitted["total_cents"] == 118080
    assert submitted["subtotal_cents"] == 104000

    account = read_account(ctx["account"]["id"])
    assert account["open_receivable_cents"] == 118080, \
        f"Expected the whole total booked, got {account['open_receivable_cents']}"


def test_cancelling_a_submitted_order_credits_back_exactly_what_it_booked():
    """PRD §3.3: "From `SUBMITTED`, the account's `open_receivable_cents` is
    reduced by the order's `total_cents`, and any service contract attached to
    that order standing in `ATTACHED` or `ACTIVE` moves to `CANCELLED`."

    Design: Difficulty/compensating_invariant/submit_then_cancel_conserves_account_open_receivable
    """
    ctx = _submitted_four_unit_order()
    submitted = submit_order(ctx["order"]["id"])

    cancel_order(submitted["id"], "Duplicate purchase order raised by the branch.")

    account = read_account(ctx["account"]["id"])
    assert account["open_receivable_cents"] == 0, \
        f"The reversal must land exactly on 0, got {account['open_receivable_cents']}"

    order = read_order(submitted["id"])
    assert order["fulfillment_status"] == "CANCELLED"
    assert order["credit_status"] == "CLOSED"
    assert order["total_cents"] == 118080, "The frozen total survives cancellation"


# --------------------------------------------------------------------------
# Order and line body validation
# --------------------------------------------------------------------------

def _orders_for_account(api, account_id):
    from test_helpers import validate_paginated
    data, meta = validate_paginated(api.list_orders(REP, params={"account_id": account_id}))
    return data, meta


def test_order_without_a_warehouse_id_is_rejected(api):
    """PRD §3.3: "Opening one names the buying `account_id`, the `warehouse_id`
    whose lots may satisfy it, and a `requested_ship_date` as an ISO 8601
    calendar date."
    PRD §2.6: "The request body being well formed — every required field
    present, every value of its declared type, every enum value a declared
    member — otherwise `ERR_INVALID_REQUEST`."

    Design: Corner/entities/create_order_missing_warehouse_id_returns_invalid_request
    """
    account = create_account(name="Delta Fleet", account_tier="STANDARD", state_code="TX",
                             credit_limit_cents=100000000, storm_priority_rank=5)

    resp = api.create_order({"account_id": account["id"],
                             "requested_ship_date": "2026-08-10"}, REP)
    validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST.value)

    data, meta = _orders_for_account(api, account["id"])
    assert meta["total_count"] == 0 and data == [], "No order row is created"


def test_order_naming_an_unknown_warehouse_reports_the_not_found_code(api):
    """PRD §2.10: "The same codes serve foreign keys carried in a request body,
    but they are evaluated one rung lower on the ladder, after body
    well-formedness. The body foreign keys that are resolved this way are those
    on order creation, order line creation, lot receiving, lot scrapping,
    shipment packing, core-return creation, warranty-claim creation,
    warranty-claim settlement, service-contract creation, service-contract
    attachment, manifest creation, manifest core-return attachment, and model
    discontinuation."
    PRD §2.10: "Each resource type has its own not-found code —
    `ERR_ACCOUNT_NOT_FOUND`, `ERR_BATTERY_MODEL_NOT_FOUND`,
    `ERR_WAREHOUSE_NOT_FOUND`, `ERR_CARRIER_NOT_FOUND`,
    `ERR_INVENTORY_LOT_NOT_FOUND`, `ERR_ORDER_NOT_FOUND`,
    `ERR_ORDER_LINE_NOT_FOUND`, `ERR_SHIPMENT_NOT_FOUND`,
    `ERR_CORE_RETURN_NOT_FOUND`, `ERR_WARRANTY_CLAIM_NOT_FOUND`,
    `ERR_SERVICE_CONTRACT_NOT_FOUND`, `ERR_STORM_EVENT_NOT_FOUND` and
    `ERR_DISPOSAL_MANIFEST_NOT_FOUND` — all returning HTTP 404."

    Design: Corner/entities/create_order_with_unknown_warehouse_id_returns_warehouse_not_found
    """
    account = create_account(name="Delta Fleet", account_tier="STANDARD", state_code="TX",
                             credit_limit_cents=100000000, storm_priority_rank=5)

    resp = api.create_order({
        "account_id": account["id"],
        "warehouse_id": "0f0e0d0c-0b0a-4908-8706-050403020100",
        "requested_ship_date": "2026-08-10",
    }, REP)
    validate_error(resp, ApiErrorId.ERR_WAREHOUSE_NOT_FOUND.value)


def test_line_promising_more_cores_than_units_is_rejected(api):
    """PRD §3.3: "A line may also declare `core_expected_count`, the number of
    units for which the buyer promises to hand back a core; it defaults to 0,
    may not be negative, and may not exceed the line's `quantity`."
    PRD §3.3: "Each successful line increments the order's `line_count`; the
    order's money fields remain zero until submission."

    Design: Corner/entities/order_line_core_expected_above_quantity_returns_invalid_request
    """
    warehouse = create_warehouse(code="TX-DAL", state_code="TX", hazmat_endorsement=True,
                                 storm_reserve_pct=0.0, dock_capacity_kg_per_window=100000.0)
    account = create_account(name="Delta Fleet", account_tier="STANDARD", state_code="TX",
                             credit_limit_cents=100000000, storm_priority_rank=5)
    model = create_battery_model("IB-AGM-95")
    order = create_order(account["id"], warehouse["id"], requested_ship_date="2026-08-10")

    resp = api.create_order_line(order["id"], {
        "battery_model_id": model["id"], "quantity": 5, "core_expected_count": 6,
    }, REP)
    validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST.value)

    assert read_order(order["id"])["line_count"] == 0


def test_cancelling_a_delivered_order_is_refused(api):
    """PRD §3.3: "An order that has reached `SHIPPED` or `DELIVERED` can no
    longer be cancelled, and neither can one already `CANCELLED`."
    PRD §3.3: "Cancellation is available from `DRAFT`, from `SUBMITTED` and from
    `ALLOCATED`, to a sales representative, an administrator or the buying
    customer, and it always records a free-text `cancellation_reason`."

    Design: Corner/state_machines/cancel_delivered_order_returns_invalid_state
    """
    from test_helpers import setup_delivered_order
    env = setup_delivered_order(
        quantity=2, core_expected_count=0, model_preset="IB-AGM-95",
        lot_overrides={"manufactured_on": "2026-06-01", "quantity_on_hand": 30},
        order_overrides={"requested_ship_date": "2026-08-05"},
    )
    assert env["order"]["fulfillment_status"] == "DELIVERED"

    resp = api.cancel_order(env["order"]["id"], {
        "cancellation_reason": "Buyer changed their mind after the truck left."
    }, REP)
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE.value)

    order = read_order(env["order"]["id"])
    assert order["fulfillment_status"] == "DELIVERED"
    assert order["credit_status"] == "CLOSED"

    lot = read_lot(env["lot"]["id"])
    assert lot["quantity_on_hand"] == 28
    assert lot["quantity_reserved"] == 0


def test_cancelling_an_allocated_order_voids_its_open_shipment():
    """PRD §3.3: "any shipment on the order standing in `PACKED` or `CERTIFIED`
    moves to `VOIDED`, releasing both its carrier window and its dock-capacity
    contribution; and any attached or active service contract moves to
    `CANCELLED`."
    PRD §3.3: "From `ALLOCATED`, the receivable is reversed the same way; in
    addition, for every line carrying a non-null `allocated_lot_id` the platform
    decrements that lot's `quantity_reserved` by the line's `allocated_quantity`
    and then clears `allocated_lot_id` and resets `allocated_quantity` to 0"

    Design: Corner/state_machines/cancel_allocated_order_voids_the_open_shipment
    """
    from test_helpers import setup_packed_shipment, read_shipment
    env = setup_packed_shipment(
        quantity=2, core_expected_count=0, model_preset="IB-AGM-95",
        lot_overrides={"manufactured_on": "2026-06-01", "quantity_on_hand": 30},
        order_overrides={"requested_ship_date": "2026-08-05"},
    )
    assert read_order(env["order"]["id"])["total_cents"] == 59678

    cancel_order(env["order"]["id"], "Site retrofit cancelled by the customer.")

    order = read_order(env["order"]["id"])
    assert order["fulfillment_status"] == "CANCELLED"
    assert order["credit_status"] == "CLOSED"
    assert read_shipment(env["shipment"]["id"])["status"] == "VOIDED"

    lot = read_lot(env["lot"]["id"])
    assert lot["quantity_reserved"] == 0
    assert lot["quantity_on_hand"] == 30
    assert read_order_line(env["line"]["id"])["allocated_lot_id"] is None
    assert read_account(env["account"]["id"])["open_receivable_cents"] == 0


def test_submitting_beyond_the_credit_limit_is_refused(api):
    """PRD §3.3: "That last check is evaluated against the freshly computed
    total: the order's `total_cents` plus the account's `open_receivable_cents`
    minus the account's `warranty_credit_cents` must be no greater than the
    account's `credit_limit_cents`, and a breach is refused with
    `ERR_CREDIT_LIMIT_EXCEEDED` (HTTP 402)."
    PRD §3.3: "Accumulated warranty credit therefore functions as headroom, not
    as cash."

    Design: Corner/validations/submit_beyond_the_credit_limit_returns_payment_required
    """
    warehouse = create_warehouse(code="TX-DAL", state_code="TX", hazmat_endorsement=True,
                                 storm_reserve_pct=0.0, dock_capacity_kg_per_window=100000.0)
    account = create_account(name="Lone Star Backup", account_tier="STANDARD",
                             state_code="TX", credit_limit_cents=100000,
                             storm_priority_rank=9)
    model = create_battery_model("IB-AGM-95")
    order = create_order(account["id"], warehouse["id"], requested_ship_date="2026-08-11")
    add_line(order["id"], model["id"], 4, core_expected_count=0)

    resp = api.submit_order(order["id"], REP)
    validate_error(resp, ApiErrorId.ERR_CREDIT_LIMIT_EXCEEDED.value)

    stored = read_order(order["id"])
    assert stored["fulfillment_status"] == "DRAFT"
    assert stored["credit_status"] == "PENDING"
    assert stored["total_cents"] == 0
    assert read_account(account["id"])["open_receivable_cents"] == 0


def test_line_naming_a_discontinued_model_is_refused(api):
    """PRD §3.1: "Once a model is `DISCONTINUED`, a new order line naming it is
    refused with `ERR_MODEL_DISCONTINUED` (HTTP 422); a warranty settlement
    against it, however, falls through to the successor rather than failing."
    PRD §3.3: "A line naming a model whose `status` is `DISCONTINUED` is refused
    with `ERR_MODEL_DISCONTINUED`."

    Design: Corner/validations/order_line_naming_a_discontinued_model_is_refused
    """
    from test_helpers import discontinue_battery_model
    warehouse = create_warehouse(code="TX-DAL", state_code="TX", hazmat_endorsement=True,
                                 storm_reserve_pct=0.0, dock_capacity_kg_per_window=100000.0)
    account = create_account(name="Delta Fleet", account_tier="STANDARD", state_code="TX",
                             credit_limit_cents=100000000, storm_priority_rank=5)
    retired = create_battery_model("IB-31-FLD")
    successor = create_battery_model("IB-AGM-95")
    stopped = discontinue_battery_model(retired["id"], successor["id"])
    assert stopped["status"] == "DISCONTINUED"

    order = create_order(account["id"], warehouse["id"], requested_ship_date="2026-08-10")
    resp = api.create_order_line(order["id"], {
        "battery_model_id": retired["id"], "quantity": 3, "core_expected_count": 0,
    }, REP)
    validate_error(resp, ApiErrorId.ERR_MODEL_DISCONTINUED.value)
    assert read_order(order["id"])["line_count"] == 0
