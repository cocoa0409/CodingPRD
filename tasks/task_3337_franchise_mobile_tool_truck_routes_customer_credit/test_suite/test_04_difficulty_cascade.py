"""Difficulty queue A — transitive_cascade: each hop caused by the previous write."""
from test_helpers import (
    MANAGER,
    ApiErrorId,
    api_client,
    book_payment,
    collect_payment,
    create_delivered_order,
    get_account,
    get_franchisee,
    get_shop,
    get_technician,
    list_charges,
    order_line,
    set_clock,
    setup_account,
    setup_product_with_stock,
    setup_shop_and_technician,
    setup_storefront,
    validate_error,
    validate_success,
)


def test_collection_cascade_reaches_franchisee_aggregate(api):
    """PRD §3.5: "When a
    charge's `collection_applied_cents` reaches its `charge_amount_cents` the charge flips to `CLOSED` and
    its `charge_resolved_iso_week` is stamped with the payment's `effective_iso_week`."
    PRD §3.5: "After allocation the account's
    `principal_balance_cents`, `accrued_finance_charge_cents`, `current_balance_cents`,
    `credit_available_cents` and `last_payment_week_start` are all recomputed, along with the technician's
    `revolving_used_cents` and the franchisee's `outstanding_credit_cents` and `recourse_exposure_cents`."

    Design: Difficulty/transitive_cascade/transitive_collection_cascade_five_hops
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
    assert account["id"]  # the delivered order wrote 45338 cents of principal
    payment = book_payment(store["franchisee"], account, "2026-09-07T00:00:00Z")

    set_clock("2026-09-14T00:00:00Z")
    charged = get_account(account["id"])
    assert charged["accrued_finance_charge_cents"] == 136

    collected = validate_success(collect_payment(store["franchisee"], account,
                                                 payment))
    assert collected["charge_applied_cents"] == 136

    charges = list_charges(account["id"])
    assert len(charges) == 1
    assert charges[0]["charge_status"] == "CLOSED"
    assert charges[0]["collection_applied_cents"] == 136
    assert charges[0]["charge_resolved_iso_week"] == "2026-09-14T00:00:00Z"

    account_after = get_account(account["id"])
    assert account_after["accrued_finance_charge_cents"] == 0
    assert account_after["principal_balance_cents"] == 25474
    assert account_after["current_balance_cents"] == 25474

    assert get_technician(people["technician"]["id"])["revolving_used_cents"] == 25474
    assert get_franchisee(store["franchisee"]["id"])["outstanding_credit_cents"] == 25474

    again = api_client.advance_payment(account["id"], payment["id"],
                                       {"action": "COLLECT"},
                                       store["franchisee"]["rep_headers"])
    validate_error(again, ApiErrorId.ERR_PAYMENT_NOT_BOOKED)


def test_trade_exit_cascade_suspends_account_and_contracts_aggregates(api):
    """PRD §3.2: "suspends money: every credit account of that technician whose `account_status` is `ACTIVE` moves to
    `SUSPENDED`. Accounts already `DELINQUENT`, `CHARGED_OFF` or `CLOSED` are not disturbed."
    PRD §3.2: "The exit
    captures `last_known_shop_name` from the current shop's `shop_name`, clears `current_shop_location_id`
    to null and clears `home_route_id` to null, refreshes the source shop's `active_technician_count`"

    Design: Difficulty/transitive_cascade/transitive_trade_exit_cascade_four_hops
    """
    set_clock("2026-09-07T00:00:00Z")
    store = setup_storefront(mix_plan="POWER_TOOLS")
    people = setup_shop_and_technician(store)
    product = setup_product_with_stock(store, on_hand=10)
    account = setup_account(store["franchisee"], people["shop"], people["technician"],
                            requested_limit_cents=50_000)
    create_delivered_order(store["franchisee"], store["route"], people["technician"],
                           account, [order_line(product, 3)],
                           mix_profile="DIAGNOSTIC_WEIGHTED")

    exited = validate_success(api_client.advance_technician_status(
        people["technician"]["id"], {"action": "EXIT_TRADE"}, MANAGER))
    assert exited["technician_status"] == "TRADE_EXITED"
    assert exited["current_shop_location_id"] is None
    assert exited["home_route_id"] is None
    assert exited["last_known_shop_name"] == "Northside Diesel"

    assert get_account(account["id"])["account_status"] == "SUSPENDED"

    technician = get_technician(people["technician"]["id"])
    assert technician["revolving_used_cents"] == 0
    assert technician["revolving_available_cents"] == 100000

    assert get_franchisee(store["franchisee"]["id"])["outstanding_credit_cents"] == 0
    assert get_shop(people["shop"]["id"])["active_technician_count"] == 0
