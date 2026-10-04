"""Corner queue B — state machines: initial states, preconditions, terminal locks."""
from test_helpers import (
    ApiErrorId,
    CREDIT_OFFICER,
    MANAGER,
    add_inventory,
    advance_claim,
    advance_product_order,
    api_client,
    approve_claim,
    book_payment,
    cancel_payment,
    collect_payment,
    confirm_order,
    create_certified_franchisee,
    create_delivered_order,
    create_order,
    create_product,
    create_product_order,
    create_route,
    deliver_order,
    file_application,
    file_claim,
    get_account,
    get_franchisee,
    get_order,
    get_product_order,
    get_route,
    list_positions,
    list_warranty_claims,
    order_line,
    requested_line,
    set_clock,
    setup_account,
    setup_product_with_stock,
    setup_shop_and_technician,
    setup_storefront,
    validate_error,
    validate_success,
)


def test_new_route_starts_on_all_three_axes_at_once(api):
    """PRD §3.1: "A new route starts at `route_status` `DRAFT`, at
    `territory_development_status` `UNASSIGNED`, and at `resale_status` `NONE`, and its
    `schedule_anchor_utc` is computed on creation."
    PRD §2.12: "it is the most recent
    occurrence of the route's visit weekday at `08:00:00Z` that falls strictly before the logical clock."

    Design: Corner/state_machines/state_route_created_draft_with_territory_unassigned
    """
    set_clock("2026-09-07T00:00:00Z")
    franchisee = create_certified_franchisee()
    route = create_route(franchisee, route_code="R1", visit_weekday=1)
    assert route["route_status"] == "DRAFT"
    assert route["territory_development_status"] == "UNASSIGNED"
    assert route["resale_status"] == "NONE"
    assert route["in_force_from_week"] is None
    assert route["in_force_to_week"] is None
    assert route["schedule_anchor_utc"] == "2026-08-31T08:00:00Z"


def test_certification_below_the_threshold_is_refused(api):
    """PRD §2.10: "A certification request whose points are below the threshold is
    refused with `ERR_CERTIFICATION_POINTS_SHORT` and HTTP status 422 rather than silently enrolling the
    franchisee."
    PRD §2.10: "the boundary is inclusive on the
    high side, so exactly 40 points certifies and 39 points does not."

    Design: Corner/state_machines/state_franchisee_certify_below_threshold_rejected
    """
    franchisee = create_certified_franchisee(training_points=10)
    enrolled = get_franchisee(franchisee["id"], franchisee["owner_headers"])
    assert enrolled["training_status"] == "ENROLLED"

    response = api_client.advance_training(
        franchisee["id"], {"action": "CERTIFY", "training_points": 39},
        franchisee["owner_headers"])
    validate_error(response, ApiErrorId.ERR_CERTIFICATION_POINTS_SHORT, 422)

    fetched = get_franchisee(franchisee["id"], franchisee["owner_headers"])
    assert fetched["training_status"] == "ENROLLED"
    assert fetched["certified_on"] is None
    assert fetched["can_resell_territory"] is False


def test_cancelled_payment_cannot_be_collected(api):
    """PRD §3.5: "a
    collection attempted against a payment that is not booked is refused with `ERR_PAYMENT_NOT_BOOKED` at
    HTTP status 409."
    PRD §3.5: "The three terminal states of this machine are `COLLECTED`, `REVERSED` and `CANCELLED`, and
    `MISSED` is deliberately not among them — a missed booking can still collect."

    Design: Corner/state_machines/state_payment_collect_from_terminal_state_rejected
    """
    set_clock("2026-09-07T00:00:00Z")
    store = setup_storefront()
    people = setup_shop_and_technician(store)
    account = setup_account(store["franchisee"], people["shop"], people["technician"],
                            requested_limit_cents=400_000)
    payment = book_payment(store["franchisee"], account, "2026-09-07T00:00:00Z")
    cancelled = validate_success(cancel_payment(account, payment))
    assert cancelled["payment_status"] == "CANCELLED"

    validate_error(collect_payment(store["franchisee"], account, payment),
                   ApiErrorId.ERR_PAYMENT_NOT_BOOKED, 409)
    assert get_account(account["id"])["principal_balance_cents"] == 0
    assert get_account(account["id"])["last_payment_week_start"] is None


def test_delivered_order_cannot_be_cancelled(api):
    """PRD §3.4: "Cancellation is allowed from `DRAFT` or `CONFIRMED` and releases the
    reservation"
    PRD §2.6: "A resource whose current state has no
    transition for the requested trigger is rejected with `ERR_INVALID_STATE` and HTTP status 409, before
    any business rule is consulted."

    Design: Corner/state_machines/state_sales_order_cancel_from_delivered_rejected
    """
    set_clock("2026-09-07T00:00:00Z")
    store = setup_storefront(mix_plan="POWER_TOOLS")
    people = setup_shop_and_technician(store)
    product = setup_product_with_stock(store, on_hand=10)
    account = setup_account(store["franchisee"], people["shop"], people["technician"],
                            requested_limit_cents=50_000)
    order = create_delivered_order(store["franchisee"], store["route"],
                                   people["technician"], account, [order_line(product, 3)],
                                   mix_profile="DIAGNOSTIC_WEIGHTED")
    assert get_order(order["id"])["order_status"] == "DELIVERED"

    cancel = api_client.advance_sales_order(order["id"], {"action": "CANCEL"},
                                            store["franchisee"]["rep_headers"])
    validate_error(cancel, ApiErrorId.ERR_INVALID_STATE, 409)

    assert get_order(order["id"])["order_status"] == "DELIVERED"
    assert get_account(account["id"])["principal_balance_cents"] == 45338


def test_approved_claim_is_locked_until_reopened(api):
    """PRD §3.8: "a decision requested against a claim that is already `APPROVED` or `REJECTED`
    is refused with `ERR_CLAIM_ALREADY_TERMINAL` at HTTP status 409"
    PRD §3.8: "An approval may be reopened, moving `APPROVED` back to `SUBMITTED`, clearing
    `resolved_iso_week` to null, removing the principal that was previously allocated from the target
    account exactly as it was written"

    Design: Corner/state_machines/state_warranty_claim_is_terminal_after_approval
    """
    set_clock("2026-09-07T00:00:00Z")
    store = setup_storefront(mix_plan="DIAGNOSTIC_WEIGHTED")
    people = setup_shop_and_technician(store)
    product = setup_product_with_stock(store, on_hand=10)
    account = setup_account(store["franchisee"], people["shop"], people["technician"],
                            requested_limit_cents=50_000)
    order = create_delivered_order(store["franchisee"], store["route"],
                                   people["technician"], account, [order_line(product, 2)],
                                   mix_profile="DIAGNOSTIC_WEIGHTED")
    claim = validate_success(file_claim(store["franchisee"], order, "idem-lockdown-1",
                                        apply_to_account_id=account["id"]), 201)
    set_clock("2027-09-13T00:00:00Z")
    approved = approve_claim(store["franchisee"], order, claim)
    assert approved["claim_status"] == "APPROVED"
    assert approved["principal_allocated_cents"] == 4800

    again = advance_claim(store["franchisee"], order, claim, "APPROVE")
    validate_error(again, ApiErrorId.ERR_CLAIM_ALREADY_TERMINAL, 409)

    reopened = validate_success(advance_claim(store["franchisee"], order, claim,
                                              "REOPEN"))
    assert reopened["claim_status"] == "SUBMITTED"
    assert reopened["principal_allocated_cents"] == 0


def test_receiving_a_replenishment_order_posts_stock(api):
    """PRD §3.6: "each ordered line's inventory position has
    its `on_hand_qty` increased by the ordered quantity, and a position is created for the route when the
    route holds none for that product yet."
    PRD §3.6: "Shipping requires that every share pledge under the order be in `BOUND` or `RELEASED` status"

    Design: Corner/state_machines/state_product_order_receive_posts_stock_and_creates_position
    """
    set_clock("2026-09-07T00:00:00Z")
    store = setup_storefront()
    product = create_product(sku="P1", category="DIAGNOSTICS", unit_cost_cents=30000,
                             retail_price_cents=39000)
    order = create_product_order(store["franchisee"], store["route"],
                                 [requested_line(product["id"], 2)], ceiling=60000)
    assert order["ordered_cost_cents"] == 60000
    assert order["is_fully_covered"] is True

    submitted = validate_success(advance_product_order(store["franchisee"], order,
                                                       "SUBMIT"))
    assert submitted["product_order_status"] == "SUBMITTED"
    shipped = validate_success(advance_product_order(store["franchisee"], order,
                                                     "SHIP"))
    assert shipped["product_order_status"] == "SHIPPED"

    version = get_product_order(order["id"], store["franchisee"]["owner_headers"])["version"]
    received = validate_success(advance_product_order(store["franchisee"], order,
                                                      "RECEIVE", version))
    assert received["product_order_status"] == "RECEIVED"

    rows = list_positions(store["franchisee"], store["route"]["id"], product["id"])
    assert len(rows) == 1
    assert rows[0]["on_hand_qty"] == 2
    assert rows[0]["reserved_qty"] == 0
    assert rows[0]["remaining_qty"] == 2
    assert get_route(store["route"]["id"])["inventory_at_risk_cents"] == 0


def test_refiling_with_the_same_idempotency_key_replays_the_claim(api):
    """PRD §3.8: "filing a claim whose `idempotency_key` already exists on the same order replays the
    existing claim and sets `is_idempotent_replay` to true rather than creating a duplicate, so a retried
    filing is safe."
    PRD §3.8: "And no non-terminal claim may already stand
    against the same order and the same line: a second filing there is refused with
    `ERR_WARRANTY_ALREADY_CLAIMED` at HTTP status 409."

    Design: Corner/state_machines/state_warranty_claim_refile_with_same_idempotency_key_replays
    """
    set_clock("2026-09-07T00:00:00Z")
    store = setup_storefront()
    people = setup_shop_and_technician(store)
    product = setup_product_with_stock(store, on_hand=10)
    account = setup_account(store["franchisee"], people["shop"], people["technician"],
                            requested_limit_cents=50_000)
    order = create_delivered_order(store["franchisee"], store["route"],
                                   people["technician"], account, [order_line(product, 2)])

    first = validate_success(file_claim(store["franchisee"], order, "idem-replay-1",
                                        apply_to_account_id=account["id"]), 201)
    assert first["is_idempotent_replay"] is False

    replay = validate_success(file_claim(store["franchisee"], order, "idem-replay-1",
                                         apply_to_account_id=account["id"]), 201)
    assert replay["id"] == first["id"]
    assert replay["is_idempotent_replay"] is True

    claims = list_warranty_claims(store["franchisee"], {"order_id": order["id"]})
    assert len(claims) == 1

    duplicate = file_claim(store["franchisee"], order, "idem-replay-2",
                           apply_to_account_id=account["id"])
    validate_error(duplicate, ApiErrorId.ERR_WARRANTY_ALREADY_CLAIMED, 409)


def test_minting_requires_an_approved_application(api):
    """PRD §3.5: "The mint requires that the
    parent application's `application_status` be `APPROVED`, failing which it is refused with
    `ERR_APPLICATION_NOT_APPROVED` at HTTP status 409"

    Design: Corner/state_machines/state_credit_account_mint_requires_approved_application
    """
    set_clock("2026-09-07T00:00:00Z")
    store = setup_storefront()
    people = setup_shop_and_technician(store)
    application = file_application(store["franchisee"], people["shop"],
                                   people["technician"], requested_limit_cents=400_000)
    assert application["application_status"] == "SUBMITTED"

    response = api_client.mint_credit_account(
        application["id"],
        {"expected_application_version": application["version"]}, CREDIT_OFFICER)
    validate_error(response, ApiErrorId.ERR_APPLICATION_NOT_APPROVED, 409)

    accounts = validate_success(api_client.list_credit_accounts(
        CREDIT_OFFICER, {"technician_id": people["technician"]["id"]}))
    assert accounts == []
