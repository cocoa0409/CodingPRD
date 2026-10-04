"""Order submission gates and the frozen pricing snapshot: the controlled
license gate, shipping-class precedence and handling fees, the credit gate,
and the priority ordering between the state, safety, and fiscal gates.
"""

from test_helpers import (
    ApiErrorId,
    api_client,
    assert_order_pricing_invariant,
    create_account,
    create_catalog_item,
    create_order,
    get_order,
    make_lab_procurement_headers,
    order_line,
    push_account_to_credit_hold,
    reactivate_account,
    submit_order,
    suspend_account,
    validate_error,
)


def test_controlled_order_with_license_succeeds(api):
    """PRD section 3.6: "when any line names a `CONTROLLED` item the account's
    `controlled_substance_license` must be true
    (`ERR_CONTROLLED_LICENSE_REQUIRED`)" — a licensed account passes the gate —
    and "A single per-order `handling_fee_cents` follows the class: 0 cents
    for `STANDARD`, 4500 cents for `COLD_CHAIN`, 7500 cents for `HAZARDOUS`,
    and 9500 cents for `CONTROLLED`."

    Design: Corner/entities/controlled_order_with_license_succeeds
    """
    account = create_account(name="Licensed Lab",
                             controlled_substance_license=True)
    item = create_catalog_item(item_class="CONTROLLED", base_price_cents=10000,
                               stock_on_hand=10)
    submitted = submit_order(
        create_order(account, [order_line(item["sku"], 1)]), account
    )
    assert submitted["status"] == "ALLOCATED"
    assert submitted["shipping_class"] == "CONTROLLED"
    assert submitted["handling_fee_cents"] == 9500
    assert submitted["goods_subtotal_cents"] == 10000
    assert submitted["total_cents"] == 19500
    assert_order_pricing_invariant(submitted)


def test_handling_fee_controlled_precedence(api):
    """PRD section 3.6: "The order's `shipping_class` — null until submission —
    becomes the most restrictive `item_class` among its lines under the
    precedence of `CONTROLLED` over `HAZARDOUS` over `COLD_CHAIN` over
    `STANDARD`. A single per-order `handling_fee_cents` follows the class".

    Design: Corner/calculations/handling_fee_controlled_precedence
    """
    account = create_account(name="Mixed Ship Lab",
                             controlled_substance_license=True)
    cold = create_catalog_item(item_class="COLD_CHAIN", base_price_cents=2000,
                               stock_on_hand=10)
    ctrl = create_catalog_item(item_class="CONTROLLED", base_price_cents=3000,
                               stock_on_hand=10)
    submitted = submit_order(
        create_order(account, [order_line(cold["sku"], 1),
                               order_line(ctrl["sku"], 1)]),
        account,
    )
    assert submitted["shipping_class"] == "CONTROLLED", (
        "CONTROLLED outranks COLD_CHAIN among the order's lines"
    )
    assert submitted["handling_fee_cents"] == 9500, (
        "a single fee by class; the 4500 cold-chain fee does not stack"
    )
    assert submitted["goods_subtotal_cents"] == 5000
    assert submitted["total_cents"] == 14500
    assert_order_pricing_invariant(submitted)


def test_cold_chain_handling_fee_applied(api):
    """PRD section 3.6: "A single per-order `handling_fee_cents` follows the
    class: 0 cents for `STANDARD`, 4500 cents for `COLD_CHAIN`, 7500 cents for
    `HAZARDOUS`, and 9500 cents for `CONTROLLED`."

    Design: Corner/calculations/cold_chain_handling_fee_applied
    """
    account = create_account(name="Cold Lab", segment="CLINICAL")
    item = create_catalog_item(item_class="COLD_CHAIN", base_price_cents=2000,
                               stock_on_hand=10)
    submitted = submit_order(
        create_order(account, [order_line(item["sku"], 2)]), account
    )
    assert submitted["status"] == "ALLOCATED"
    assert submitted["shipping_class"] == "COLD_CHAIN"
    assert submitted["handling_fee_cents"] == 4500
    assert submitted["goods_subtotal_cents"] == 4000
    assert submitted["total_cents"] == 8500
    assert_order_pricing_invariant(submitted)


def test_credit_hold_blocks_submit_returns_402(api):
    """PRD section 2.9: "Credit gate. Order submission against an account in
    `HOLD` standing yields `ERR_CREDIT_HOLD`, and it is evaluated last".

    Design: Corner/validations/credit_hold_blocks_submit_returns_402
    """
    account = create_account(name="Hold Lab")
    push_account_to_credit_hold(account)
    item = create_catalog_item(base_price_cents=100, stock_on_hand=10)
    order = create_order(account, [order_line(item["sku"], 1)])

    response = api_client.submit_order(
        order["id"], headers=make_lab_procurement_headers(account["id"])
    )
    validate_error(response, ApiErrorId.ERR_CREDIT_HOLD)
    fresh = get_order(order)
    assert fresh["status"] == "DRAFT"


def test_state_gate_beats_license_gate_on_submit(api):
    """PRD section 2.9: "4. **State guards.** ... `ERR_ACCOUNT_NOT_ACTIVE`
    where an `ACTIVE` account is required" is evaluated before "6.
    **Controlled-substance license gate.** Order submission containing a
    `CONTROLLED` line without a licensed account yields
    `ERR_CONTROLLED_LICENSE_REQUIRED`." — a submit violating both reports the
    state error.

    Design: Difficulty/priority_pair_validation_conflict/state_beats_safety_on_order_submit
    """
    account = create_account(name="Prio Lab 1", segment="CLINICAL")
    item = create_catalog_item(item_class="CONTROLLED", base_price_cents=5000,
                               stock_on_hand=10)
    order = create_order(account, [order_line(item["sku"], 1)])
    suspend_account(account)

    response = api_client.submit_order(
        order["id"], headers=make_lab_procurement_headers(account["id"])
    )
    validate_error(response, ApiErrorId.ERR_ACCOUNT_NOT_ACTIVE)
    fresh = get_order(order)
    assert fresh["status"] == "DRAFT", "the rejected submit leaves the order DRAFT"


def test_license_gate_surfaces_once_state_gate_passes(api):
    """PRD section 3.6: "the account must be `ACTIVE`
    (`ERR_ACCOUNT_NOT_ACTIVE`); when any line names a `CONTROLLED` item the
    account's `controlled_substance_license` must be true
    (`ERR_CONTROLLED_LICENSE_REQUIRED`)".  With the account reinstated, the
    same CONTROLLED order now reaches the license gate and reports it.

    Design: Difficulty/priority_pair_validation_conflict/state_beats_safety_on_order_submit
    """
    account = create_account(name="Prio Lab 1", segment="CLINICAL")
    item = create_catalog_item(item_class="CONTROLLED", base_price_cents=5000,
                               stock_on_hand=10)
    order = create_order(account, [order_line(item["sku"], 1)])
    suspend_account(account)
    reactivate_account(account)

    response = api_client.submit_order(
        order["id"], headers=make_lab_procurement_headers(account["id"])
    )
    validate_error(response, ApiErrorId.ERR_CONTROLLED_LICENSE_REQUIRED)
    fresh = get_order(order)
    assert fresh["status"] == "DRAFT"


def test_license_gate_beats_credit_gate_on_submit(api):
    """PRD section 2.9: "an order submission that would fail both the license
    gate and the credit gate reports `ERR_CONTROLLED_LICENSE_REQUIRED`, never
    `ERR_CREDIT_HOLD`."

    Design: Difficulty/priority_pair_validation_conflict/safety_beats_fiscal_on_order_submit
    """
    account = create_account(name="Prio Lab 2", segment="CLINICAL")
    push_account_to_credit_hold(account)
    item = create_catalog_item(item_class="CONTROLLED", base_price_cents=5000,
                               stock_on_hand=10)
    order = create_order(account, [order_line(item["sku"], 1)])

    response = api_client.submit_order(
        order["id"], headers=make_lab_procurement_headers(account["id"])
    )
    validate_error(response, ApiErrorId.ERR_CONTROLLED_LICENSE_REQUIRED)


def test_credit_gate_reports_once_license_gate_passes(api):
    """PRD section 3.6: "when any line names a `CONTROLLED` item the account's
    `controlled_substance_license` must be true
    (`ERR_CONTROLLED_LICENSE_REQUIRED`); and the account's `credit_status`
    must be `GOOD` (`ERR_CREDIT_HOLD`)".  A licensed account on HOLD passes
    the license gate, so the fiscal gate reports `ERR_CREDIT_HOLD`.

    Design: Difficulty/priority_pair_validation_conflict/safety_beats_fiscal_on_order_submit
    """
    account = create_account(name="Licensed Hold Lab",
                             controlled_substance_license=True)
    push_account_to_credit_hold(account)
    item = create_catalog_item(item_class="CONTROLLED", base_price_cents=5000,
                               stock_on_hand=10)
    order = create_order(account, [order_line(item["sku"], 1)])

    response = api_client.submit_order(
        order["id"], headers=make_lab_procurement_headers(account["id"])
    )
    validate_error(response, ApiErrorId.ERR_CREDIT_HOLD)
    fresh = get_order(order)
    assert fresh["status"] == "DRAFT"
