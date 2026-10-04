"""Accounts: creation defaults, existence, enum validation, terminal CLOSED,
the credit-line boundary, trailing-spend derivation, and read consistency.
"""

from test_helpers import (
    ACCOUNT_MANAGER,
    ApiErrorId,
    CREDIT_LIMIT_CENTS,
    NON_EXISTENT_UUID,
    account_payload,
    api_client,
    assert_account,
    close_account,
    create_account,
    create_catalog_item,
    create_shipped_order,
    get_account,
    is_valid_uuid,
    order_line,
    plus_days,
    CLOCK_START_UTC,
    set_clock,
    ship_order_total,
    validate_error,
    validate_success,
)


def test_account_create_applies_defaults(api):
    """PRD section 3.1: "An account is created in `ACTIVE` status." and
    "`priority_class`, one of `STANDARD`, `PRIORITY`, or `CRITICAL`, defaults
    to `STANDARD`" and "`controlled_substance_license` defaults to `false`".
    PRD section 2.8: "`outstanding_balance_cents`, which starts at 0 when the
    account is created."
    PRD section 2.5: "`id` (string): a server-minted UUID with no type prefix."

    Design: Corner/entities/account_create_applies_defaults
    """
    response = api_client.create_account(
        {"name": "Defaults Lab", "segment": "ACADEMIC", "territory_code": "CA-NORTH"},
        headers=ACCOUNT_MANAGER,
    )
    data = validate_success(response, 201)
    assert_account(data)
    assert data["status"] == "ACTIVE"
    assert data["credit_status"] == "GOOD"
    assert data["outstanding_balance_cents"] == 0
    assert data["priority_class"] == "STANDARD"
    assert data["controlled_substance_license"] is False
    assert isinstance(data["version"], int) and data["version"] >= 1
    assert is_valid_uuid(data["id"])


def test_account_not_found_returns_404(api):
    """PRD section 2.9: "Unknown path identifiers and unknown body references
    are rejected before any state or business rule runs: a request naming a
    nonexistent identifier always fails with the corresponding not-found error
    — `ERR_ACCOUNT_NOT_FOUND` ... by resource".

    Design: Corner/entities/account_not_found_returns_404
    """
    response = api_client.get_account(NON_EXISTENT_UUID, headers=ACCOUNT_MANAGER)
    validate_error(response, ApiErrorId.ERR_ACCOUNT_NOT_FOUND)


def test_account_invalid_enum_segment_invalid_request(api):
    """PRD section 2.9: "malformed requests — a missing required field, a
    malformed value, a value outside a field's declared enumeration, or an
    empty order-lines array — yield `ERR_INVALID_REQUEST`."
    PRD section 3.1: "a `segment` of `ACADEMIC`, `PHARMA`, `CLINICAL`, or
    `INDUSTRIAL`".

    Design: Corner/validations/account_invalid_enum_segment_invalid_request
    """
    response = api_client.create_account(
        account_payload(segment="PHARMA-X"), headers=ACCOUNT_MANAGER
    )
    validate_error(response, ApiErrorId.ERR_INVALID_REQUEST)


def test_closed_account_cannot_reopen_invalid_state(api):
    """PRD section 3.1: "an account in either `ACTIVE` or `SUSPENDED` can be
    closed to the terminal `CLOSED` state" and "any attempt to change the
    status of a `CLOSED` account is rejected with `ERR_INVALID_STATE`."

    Design: Corner/state_machines/closed_account_cannot_reopen_invalid_state
    """
    account = create_account(name="Closing Lab", segment="ACADEMIC")
    close_account(account)
    response = api_client.update_account(
        account["id"], {"status": "ACTIVE"}, headers=ACCOUNT_MANAGER
    )
    validate_error(response, ApiErrorId.ERR_INVALID_STATE)
    fresh = get_account(account)
    assert fresh["status"] == "CLOSED", "CLOSED is terminal; status must not move"


def test_immediate_read_after_create_shows_computed(api):
    """PRD section 2.2: "operations that create or modify a resource will
    return the created or updated resource object in the data field" and
    PRD section 3.1: "An account is created in `ACTIVE` status."  The create
    response already carries the computed fields and a same-instant GET
    returns the identical representation.

    Design: Corner/consistency_model/immediate_read_after_create_shows_computed
    """
    response = api_client.create_account(
        account_payload(
            name="Immediate Lab", segment="ACADEMIC", priority_class="PRIORITY"
        ),
        headers=ACCOUNT_MANAGER,
    )
    created = validate_success(response, 201)
    assert created["status"] == "ACTIVE"
    assert created["credit_status"] == "GOOD"
    assert created["outstanding_balance_cents"] == 0
    reread = validate_success(
        api_client.get_account(created["id"], headers=ACCOUNT_MANAGER), 200
    )
    assert reread["version"] == created["version"], "no lag between create and read"
    assert reread["status"] == created["status"] == "ACTIVE"
    assert reread["credit_status"] == created["credit_status"] == "GOOD"


def test_credit_hold_boundary_strictly_greater(api):
    """PRD section 2.8: "When the balance after the posting is strictly
    greater than 2000000 cents, the account's `credit_status` becomes `HOLD`;
    otherwise it is `GOOD`. The boundary is strict: a balance of exactly
    2000000 cents keeps the account in `GOOD` standing."

    Design: Corner/calculations/credit_hold_boundary_strictly_greater
    """
    account = create_account(name="Edge Credit Lab")
    _, at_limit = ship_order_total(account, CREDIT_LIMIT_CENTS)
    assert at_limit["outstanding_balance_cents"] == CREDIT_LIMIT_CENTS
    assert at_limit["credit_status"] == "GOOD", (
        "balance exactly at the credit line stays GOOD (strictly-greater rule)"
    )

    penny = create_catalog_item(base_price_cents=1, stock_on_hand=5)
    create_shipped_order(account, [order_line(penny["sku"], 1)])
    over = get_account(account)
    assert over["outstanding_balance_cents"] == CREDIT_LIMIT_CENTS + 1
    assert over["credit_status"] == "HOLD", "one cent over the line flips to HOLD"


def test_trailing_spend_derived_after_delivery(api):
    """PRD section 3.1: "`trailing_spend_cents`, is the sum of `total_cents`
    over the account's orders in `DELIVERED` status whose `delivered_at` is at
    or after the instant 365 days before the current logical time; orders in
    `DRAFT`, `BACKORDERED`, `ALLOCATED`, `SHIPPED`, or `CANCELLED` never count
    toward it."

    Design: Corner/cross_cutting_layers/trailing_spend_derived_after_delivery
    """
    account = create_account(name="Derived Lab")
    item = create_catalog_item(base_price_cents=10000, stock_on_hand=5)
    shipped = create_shipped_order(account, [order_line(item["sku"], 1)])

    before = get_account(account)
    assert before["trailing_spend_cents"] == 0, "SHIPPED orders never count"

    set_clock(plus_days(CLOCK_START_UTC, 3))
    after = get_account(account)
    assert after["trailing_spend_cents"] == 10000, (
        "the swept DELIVERED order's frozen total joins trailing spend"
    )
