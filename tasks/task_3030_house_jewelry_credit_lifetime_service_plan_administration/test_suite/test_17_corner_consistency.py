"""Consistency-model claims: every hop of a write is visible in the next read."""

from test_helpers import (
    ASSOCIATE,
    LOGICAL_CLOCK_START,
    api_client,
    get_success_data,
    reset_clock,
    setup_approved_customer,
    setup_diamond,
    setup_purchase,
    setup_store,
    validate_success,
)


def test_immediate_consistency_every_completion_side_effect_is_visible_in_one_read(
        api, sales_associate_headers):
    """PRD §3.5: "The ticket's `purchase_status` becomes `COMPLETED` and its `completed_at` is stamped."
    PRD §3.5: "Every stone attached to the ticket takes the customer as `owner_customer_id` and returns to `IN_CASE`."

    Design: Corner/consistency_model/immediate_consistency_every_completion_side_effect_is_visible_in_one_read
    """
    customer, store, purchase, diamond = _purchase_ready_to_complete()
    completed = validate_success(
        api.complete_purchase(purchase["id"], sales_associate_headers), 200)

    assert completed["purchase_status"] == "COMPLETED"
    assert completed["completed_at"] == "2026-09-01T00:00:00.000Z", (
        "the completion instant is the logical clock, read back with no lag"
    )
    stone = get_success_data(api.get_diamond(diamond["id"], sales_associate_headers))
    assert stone["owner_customer_id"] == customer["id"]
    assert stone["custody_status"] == "IN_CASE"


def test_the_customers_lifetime_total_reflects_the_write_in_the_same_read(
        api, sales_associate_headers):
    """PRD §2.10: "`lifetime_purchase_cents` is the sum of `base_price_cents` over the customer's purchases that have reached `COMPLETED` or `TRADE_UP_APPLIED`."
    PRD §2.12: "Nested and computed collections are re-derived rather than stored"

    Design: Corner/consistency_model/immediate_consistency_every_completion_side_effect_is_visible_in_one_read
    """
    customer, store, purchase, diamond = _purchase_ready_to_complete()
    validate_success(api.complete_purchase(purchase["id"], sales_associate_headers), 200)

    refreshed = get_success_data(api.get_customer(customer["id"], sales_associate_headers))
    assert refreshed["lifetime_purchase_cents"] == 900_100, "no observable lag"


def test_a_purchase_without_a_bundle_opens_no_registration(
        api, sales_associate_headers, store_manager_headers):
    """PRD §3.5: "When the origin ticket carries a live lifetime registration, that registration becomes `TERMINATED` and exactly one fresh registration for the new stone starts at `PENDING_INSPECTION`; when the origin carries no registration, none is created."
    PRD §2.16: "`open_inspection_count` counts the store's registrations whose `coverage_status` is `PENDING_INSPECTION` or `REMINDER_ISSUED`, and is recomputed on every registration transition."

    Design: Corner/consistency_model/immediate_consistency_every_completion_side_effect_is_visible_in_one_read
    """
    customer, store, purchase, diamond = _purchase_ready_to_complete()
    validate_success(api.complete_purchase(purchase["id"], sales_associate_headers), 200)

    store_after = get_success_data(api.get_store(store["id"], sales_associate_headers))
    assert store_after["open_inspection_count"] == 0, (
        "the purchase carried no bundle and no origin, so no registration was opened"
    )
    registrations = validate_success(api.list_purchase_registrations(
        purchase["id"], store_manager_headers), 200)
    assert registrations == []


def test_the_stone_ownership_transfer_survives_a_second_independent_read(
        api, sales_associate_headers):
    """PRD §3.4: "Its `owner_customer_id` is set when the owning purchase completes, and its `custody_status` tracks physical control"
    PRD §2.12: "`id` is a unique, server-minted identifier formatted as a UUID with no type prefix and no enclosing braces."

    Design: Corner/consistency_model/immediate_consistency_every_completion_side_effect_is_visible_in_one_read
    """
    customer, store, purchase, diamond = _purchase_ready_to_complete()
    validate_success(api.complete_purchase(purchase["id"], sales_associate_headers), 200)

    first = get_success_data(api.get_diamond(diamond["id"], sales_associate_headers))
    second = get_success_data(api.get_diamond(diamond["id"], sales_associate_headers))
    assert first["owner_customer_id"] == second["owner_customer_id"] == customer["id"]
    listed = validate_success(api.list_customer_diamonds(
        customer["id"], sales_associate_headers), 200)
    assert [d["id"] for d in listed] == [diamond["id"]], (
        "the ownership filter sees the same row the direct read does"
    )


def test_the_ticket_totals_read_back_consistently_right_after_completion(
        api, sales_associate_headers):
    """PRD §2.8: "The amount actually due at the counter is `net_amount_cents`, computed as `base_price_cents` minus the credited `trade_up_credit_cents`, floored at 0."
    PRD §3.2: "its `protection_fee_cents` is the attached bundle's `lifetime_plan_fee_cents` when a bundle was taken and 0 otherwise."

    Design: Corner/consistency_model/immediate_consistency_every_completion_side_effect_is_visible_in_one_read
    """
    customer, store, purchase, diamond = _purchase_ready_to_complete()
    validate_success(api.complete_purchase(purchase["id"], sales_associate_headers), 200)

    ticket = get_success_data(api.get_purchase(purchase["id"], sales_associate_headers))
    assert ticket["purchase_status"] == "COMPLETED"
    assert ticket["protection_fee_cents"] == 0, "no bundle was attached"
    assert ticket["net_amount_cents"] == ticket["base_price_cents"] - ticket["trade_up_credit_cents"]


def _purchase_ready_to_complete():
    """Store ACTIVE with an approved line covering a 900,100 ticket on a stone."""
    reset_clock(LOGICAL_CLOCK_START)
    from test_helpers import setup_regulation, setup_registry_row
    store = setup_store()
    setup_regulation()
    setup_registry_row(registry_key="TX", credit_tier="TIER_3", base_limit_cents=2_000_000,
                       min_down_payment_pct=0.10, min_ticket_cents=200_000)
    customer, store, _ = setup_approved_customer(
        store=store, requested_limit_cents=1_000_000,
        requested_purchase_amount_cents=900_100, down_payment_cents=90_010)
    diamond = setup_diamond(stone_code="ST-0001")
    purchase = setup_purchase(customer, store, base_price_cents=900_100, diamond=diamond)
    return customer, store, purchase, diamond