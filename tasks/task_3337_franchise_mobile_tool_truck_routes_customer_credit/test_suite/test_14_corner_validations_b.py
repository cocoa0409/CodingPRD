"""Corner queue B — validations (second half): stock, ceilings, temporal guards."""
from test_helpers import (
    CREDIT_OFFICER,
    MANAGER,
    ApiErrorId,
    add_inventory,
    api_client,
    book_payment,
    confirm_order,
    create_certified_franchisee,
    create_delivered_order,
    create_order,
    create_product,
    create_product_order,
    create_route,
    create_shop,
    create_technician,
    edit_order,
    file_application,
    file_pledge,
    get_account,
    get_order,
    get_route,
    list_pledges,
    list_positions,
    list_product_orders,
    order_line,
    position_for,
    requested_line,
    set_clock,
    setup_account,
    setup_product_with_stock,
    setup_shop_and_technician,
    setup_storefront,
    validate_error,
    validate_success,
)


def test_sales_line_cannot_exceed_remaining_stock(api):
    """PRD §3.4: "When an order is
    advanced past `DRAFT`, every line's quantity must be at most the `remaining_qty` of the matching
    inventory position on the order's route — the quantity on hand less the quantity already reserved."
    PRD §3.4: "A
    line that exceeds it is refused with `ERR_INSUFFICIENT_INVENTORY` and HTTP status 409."

    Design: Corner/validations/validation_sales_line_cannot_exceed_remaining_stock
    """
    set_clock("2026-09-07T00:00:00Z")
    store = setup_storefront()
    people = setup_shop_and_technician(store)
    product = setup_product_with_stock(store, on_hand=2)
    account = setup_account(store["franchisee"], people["shop"], people["technician"],
                            requested_limit_cents=100_000)
    position = position_for(store["franchisee"], store["route"]["id"], product["id"])
    assert position["remaining_qty"] == 2

    # creation is guarded: a 3-unit line against 2 units on hand is refused
    over = api_client.create_sales_order(
        store["route"]["id"],
        {"technician_id": people["technician"]["id"], "credit_account_id": account["id"],
         "mix_profile": "DIAGNOSTIC_WEIGHTED", "lines": [order_line(product, 3)]},
        store["franchisee"]["rep_headers"])
    validate_error(over, ApiErrorId.ERR_INSUFFICIENT_INVENTORY, 409)

    # an order at exactly the remaining quantity is accepted
    order = create_order(store["franchisee"], store["route"], people["technician"], account,
                         [order_line(product, 1), order_line(product, 1)])
    assert order["gross_total_cents"] == 30226

    # line editing is guarded: raising the order back above the stock is refused
    validate_error(edit_order(store["franchisee"], order, [order_line(product, 3)]),
                   ApiErrorId.ERR_INSUFFICIENT_INVENTORY, 409)

    # advancement is guarded: once the stock is reserved, a second order cannot confirm
    second = create_order(store["franchisee"], store["route"], people["technician"], account,
                          [order_line(product, 1), order_line(product, 1)])
    version = get_order(order["id"], store["franchisee"]["rep_headers"])["version"]
    confirmed = validate_success(api_client.advance_sales_order(
        order["id"], {"action": "CONFIRM", "expected_sales_order_version": version},
        store["franchisee"]["rep_headers"]))
    assert confirmed["order_status"] == "CONFIRMED"
    assert position_for(store["franchisee"], store["route"]["id"],
                        product["id"])["remaining_qty"] == 0

    validate_error(api_client.advance_sales_order(
        second["id"], {"action": "CONFIRM", "expected_sales_order_version": second["version"]},
        store["franchisee"]["rep_headers"]), ApiErrorId.ERR_INSUFFICIENT_INVENTORY, 409)


def test_replenishment_request_above_the_ceiling_is_refused(api):
    """PRD §3.6: "An order whose requested cost exceeds the ceiling is refused with
    `ERR_ALLOCATION_CEILING_EXCEEDED` and HTTP status 422."
    PRD §3.9: "A replenishment order whose
    `requested_cost_cents` exceeds `investment_ceiling_cents` is refused with
    `ERR_ALLOCATION_CEILING_EXCEEDED` at HTTP status 422."

    Design: Corner/validations/validation_replenishment_ceiling_exceeded_at_creation
    """
    set_clock("2026-09-07T00:00:00Z")
    store = setup_storefront()
    product = create_product(sku="P1", category="DIAGNOSTICS", unit_cost_cents=30000,
                             retail_price_cents=39000)

    create = api_client.create_product_order(
        store["route"]["id"],
        {"mix_profile": "DIAGNOSTIC_WEIGHTED", "investment_ceiling_cents": 50000,
         "requested_lines": [requested_line(product["id"], 2)]},
        store["franchisee"]["owner_headers"])
    if create.status_code < 300:
        order = validate_success(create, 201)
        submit = api_client.advance_product_order(
            order["id"], {"action": "SUBMIT"}, store["franchisee"]["owner_headers"])
        validate_error(submit, ApiErrorId.ERR_ALLOCATION_CEILING_EXCEEDED, 422)
    else:
        validate_error(create, ApiErrorId.ERR_ALLOCATION_CEILING_EXCEEDED, 422)

    assert list_product_orders(store["franchisee"],
                               {"route_id": store["route"]["id"]}) == []


def test_pledges_are_bounded_by_the_ordered_quantity_and_the_draft_state(api):
    """PRD §3.6: "The
    pledged quantity for a product may not exceed the order's ordered quantity for that product, and a
    pledge that oversubscribes is refused with `ERR_PLEDGE_OVERSUBSCRIBED` and HTTP status 422."
    PRD §3.6: "Filing is permitted only while the
    order is `DRAFT`; a pledge against any other status is refused with `ERR_PRODUCT_ORDER_NOT_DRAFT`."

    Design: Corner/validations/validation_pledge_oversubscription_and_draft_only_rule
    """
    set_clock("2026-09-07T00:00:00Z")
    store = setup_storefront()
    people = setup_shop_and_technician(store)
    product = create_product(sku="P1", category="DIAGNOSTICS", unit_cost_cents=30000,
                             retail_price_cents=39000)
    account = setup_account(store["franchisee"], people["shop"], people["technician"],
                            requested_limit_cents=50_000)
    order = create_product_order(store["franchisee"], store["route"],
                                 [requested_line(product["id"], 2)], ceiling=60000)
    assert order["ordered_cost_cents"] == 60000

    from test_helpers import pledged_line
    oversubscribed = file_pledge(store["franchisee"], order, account,
                                 [pledged_line(product["id"], 3)], order["version"])
    validate_error(oversubscribed, ApiErrorId.ERR_PLEDGE_OVERSUBSCRIBED, 422)

    accepted = validate_success(file_pledge(store["franchisee"], order, account,
                                            [pledged_line(product["id"], 2)],
                                            order["version"]), 201)
    assert accepted["pledge_status"] == "HELD"

    submitted = validate_success(api_client.advance_product_order(
        order["id"], {"action": "SUBMIT"}, store["franchisee"]["owner_headers"]))
    assert submitted["product_order_status"] == "SUBMITTED"

    late = file_pledge(store["franchisee"], order, account,
                       [pledged_line(product["id"], 1)], submitted["version"])
    validate_error(late, ApiErrorId.ERR_PRODUCT_ORDER_NOT_DRAFT, 409)


def test_a_launch_is_planned_once_per_product(api):
    """PRD §3.7: "`SECONDARY` re-plans,
    and it is refused with `ERR_LAUNCH_ALREADY_ALLOCATED` and HTTP status 409 once the product has already
    reached `ALLOCATED` or `LIVE`, so a given product can be planned once per launch run."
    PRD §3.7: "a product flagged `is_new_launch` is
    created `ANNOUNCED` and carries a `launch_iso_week`, while a product that is not a launch product is
    created directly at `LIVE`."

    Design: Corner/validations/validation_second_launch_plan_for_same_product_rejected
    """
    set_clock("2026-09-07T00:00:00Z")
    store = setup_storefront()
    launch_product = create_product(sku="P1", product_name="Launch Wrench",
                                    category="DIAGNOSTICS", unit_cost_cents=30000,
                                    retail_price_cents=39000, is_new_launch=True,
                                    launch_iso_week="2026-09-07T00:00:00Z")
    assert launch_product["launch_status"] == "ANNOUNCED"

    first = validate_success(api_client.plan_launch(
        launch_product["id"], {"total_launch_qty": 10, "run_priority": "PRIMARY"},
        MANAGER))
    assert first[0]["allocated_qty"] == 10
    assert validate_success(api_client.get_product(launch_product["id"],
                                                   CREDIT_OFFICER))["launch_status"] \
        == "ALLOCATED"

    second = api_client.plan_launch(launch_product["id"],
                                    {"total_launch_qty": 10, "run_priority": "SECONDARY"},
                                    MANAGER)
    validate_error(second, ApiErrorId.ERR_LAUNCH_ALREADY_ALLOCATED, 409)

    rows = validate_success(api_client.list_launch_allocations(
        MANAGER, {"product_id": launch_product["id"]}))
    assert len(rows) == 1
    assert rows[0]["allocated_qty"] == 10


def test_payment_week_must_not_precede_the_current_week(api):
    """PRD §2.4: "A payment's
    `expected_week_start` must itself be a Monday `00:00:00Z` and must not precede the logical clock's
    current week; a payment booked with a non-Monday or a past week is rejected with
    `ERR_PAYMENT_WEEK_IN_PAST` and HTTP status 422."

    Design: Corner/validations/validation_payment_expected_week_must_be_current_monday
    """
    store = setup_storefront()
    people = setup_shop_and_technician(store)
    account = setup_account(store["franchisee"], people["shop"], people["technician"],
                            requested_limit_cents=50_000)
    set_clock("2026-09-14T00:00:00Z")

    backdated = api_client.book_payment(
        account["id"], {"amount_cents": 20000, "collection_source": "TRUCK_COLLECTION",
                        "expected_week_start": "2026-09-07T00:00:00Z"},
        store["franchisee"]["rep_headers"])
    validate_error(backdated, ApiErrorId.ERR_PAYMENT_WEEK_IN_PAST, 422)

    rows = validate_success(api_client.list_payments(account["id"],
                                                     CREDIT_OFFICER))
    assert rows == []

    booked = book_payment(store["franchisee"], account, "2026-09-14T00:00:00Z")
    assert booked["payment_status"] == "BOOKED"
    assert booked["expected_week_start"] == "2026-09-14T00:00:00Z"
    assert get_account(account["id"])["next_due_weekday"] == 1


def test_charge_off_is_refused_before_the_anniversary_week(api):
    """PRD §2.14: "A charge-off requested before the account's
    charge-off week has been reached, or a closure requested while the balance is non-zero, is refused
    with `ERR_CHARGE_OFF_NOT_DUE` at HTTP status 422."
    PRD §2.14: "the
    effective charge-off week is that week start plus 26 weeks."

    Design: Corner/validations/validation_charge_off_before_anniversary_rejected
    """
    set_clock("2026-09-07T00:00:00Z")
    store = setup_storefront()
    people = setup_shop_and_technician(store)
    product = setup_product_with_stock(store, category="DIAGNOSTICS", on_hand=10)
    account = setup_account(store["franchisee"], people["shop"], people["technician"],
                            requested_limit_cents=400_000)
    create_delivered_order(store["franchisee"], store["route"], people["technician"],
                           account, [order_line(product, 1)])
    payment = book_payment(store["franchisee"], account, "2026-09-07T00:00:00Z")

    set_clock("2026-09-14T00:00:00Z")
    missed = validate_success(api_client.advance_payment(
        account["id"], payment["id"], {"action": "MISS"}, MANAGER))
    assert missed["payment_status"] == "MISSED"

    delinquent = get_account(account["id"])
    assert delinquent["account_status"] == "DELINQUENT"
    assert delinquent["account_status_changed_at"] == "2026-09-14T00:00:00Z"

    early = api_client.advance_account_status(account["id"], {"action": "CHARGE_OFF"},
                                              CREDIT_OFFICER)
    validate_error(early, ApiErrorId.ERR_CHARGE_OFF_NOT_DUE, 422)
    assert get_account(account["id"])["account_status"] == "DELINQUENT"

    set_clock("2027-03-15T00:00:00Z")
    swept = get_account(account["id"])
    assert swept["account_status"] == "CHARGED_OFF"


def test_requested_limit_above_the_absolute_cap_is_refused(api):
    """PRD §2.9: "A credit application that asks for more than
    `CREDIT_ABSOLUTE_CAP_CENTS` is refused outright with `ERR_CREDIT_REQUEST_ABOVE_CAP` at HTTP status 402,
    before any scoring runs."

    Design: Corner/validations/validation_requested_limit_above_absolute_cap_rejected
    """
    set_clock("2026-09-07T00:00:00Z")
    store = setup_storefront()
    people = setup_shop_and_technician(store)

    refused = api_client.file_credit_application(
        people["shop"]["id"],
        {"technician_id": people["technician"]["id"], "requested_limit_cents": 9_000_000,
         "requested_kind": "REVOLVING", "employment_verified": True, "months_in_trade": 100,
         "prior_delinquency_count": 0, "decision_source": "FRANCHISEE"},
        store["franchisee"]["owner_headers"])
    validate_error(refused, ApiErrorId.ERR_CREDIT_REQUEST_ABOVE_CAP, 402)

    at_cap = file_application(store["franchisee"], people["shop"], people["technician"],
                              requested_limit_cents=500_000)
    assert at_cap["application_status"] == "SUBMITTED"
    assert at_cap["decision_score"] == 100


def test_confirmation_succeeds_when_every_precondition_holds(api):
    """PRD §3.4: "Confirming reserves, delivering writes principal, settling closes, cancelling releases."
    PRD §3.4: "On
    confirmation each line's inventory position has its `reserved_qty` incremented by the line quantity"

    Design: Corner/validations/validation_order_and_pledge_pass_all_checks_when_conditions_hold
    """
    set_clock("2026-09-07T00:00:00Z")
    store = setup_storefront()
    people = setup_shop_and_technician(store)
    product = setup_product_with_stock(store, on_hand=10)
    account = setup_account(store["franchisee"], people["shop"], people["technician"],
                            requested_limit_cents=50_000)
    order = create_order(store["franchisee"], store["route"], people["technician"], account,
                         [order_line(product, 3)])

    confirmed = validate_success(api_client.advance_sales_order(
        order["id"], {"action": "CONFIRM", "expected_sales_order_version": order["version"]},
        store["franchisee"]["rep_headers"]))
    assert confirmed["order_status"] == "CONFIRMED"
    assert confirmed["gross_total_cents"] == 45338

    position = position_for(store["franchisee"], store["route"]["id"], product["id"])
    assert position["reserved_qty"] == 3
    assert position["remaining_qty"] == 7
