"""Corner queue B — consistency model: derived state is correct on the next read."""
from test_helpers import (
    CREDIT_OFFICER,
    advance_claim,
    api_client,
    approve_claim,
    confirm_order,
    create_delivered_order,
    create_order,
    deliver_order,
    file_claim,
    get_account,
    get_franchisee,
    get_order,
    get_shop,
    get_technician,
    list_warranty_claims,
    order_line,
    set_clock,
    setup_account,
    setup_product_with_stock,
    setup_shop_and_technician,
    setup_storefront,
    update_shop,
    validate_success,
)


def test_delivery_updates_every_derived_field_immediately(api):
    """PRD §2.5: "When the service recomputes a derived attribute — a
    route's `inventory_at_risk_cents`, a franchisee's `outstanding_credit_cents`, an account's
    `current_balance_cents`, an order's `gross_total_cents` — it bumps the owning row's `updated_at` and
    increments its `version` exactly as if a client had written the row directly."
    PRD §3.4: "the target credit account's `principal_balance_cents` is increased by
    `financed_principal_cents` with `current_balance_cents`, `credit_available_cents`,
    `revolving_used_cents` and the franchisee's `outstanding_credit_cents` all recomputed after it."

    Design: Corner/consistency model/consistency_account_balance_visible_in_same_response_as_delivery
    """
    set_clock("2026-09-07T00:00:00Z")
    store = setup_storefront(mix_plan="POWER_TOOLS")
    people = setup_shop_and_technician(store)
    product = setup_product_with_stock(store, on_hand=10)
    account = setup_account(store["franchisee"], people["shop"], people["technician"],
                            requested_limit_cents=50_000)
    order = create_order(store["franchisee"], store["route"], people["technician"], account,
                         [order_line(product, 3)], mix_profile="DIAGNOSTIC_WEIGHTED")
    confirm_order(store["franchisee"], order, order["version"])

    delivered = deliver_order(store["franchisee"], order)
    assert delivered["financed_principal_cents"] == 45338

    account_read = get_account(account["id"])
    assert account_read["principal_balance_cents"] == 45338
    assert account_read["credit_available_cents"] == 4662
    assert get_technician(people["technician"]["id"])["revolving_used_cents"] == 45338
    assert get_franchisee(store["franchisee"]["id"])["outstanding_credit_cents"] == 45338


def test_reopening_a_claim_restores_the_principal_it_allocated(api):
    """PRD §3.8: "An approval may be reopened, moving `APPROVED` back to `SUBMITTED`, clearing
    `resolved_iso_week` to null, removing the principal that was previously allocated from the target
    account exactly as it was written, and recomputing the parent order's `financed_principal_cents`."
    PRD §3.8: "the allocation equals the claim's `replacement_charge_cents` and it is written onto the named account as new
    principal, increasing that account's `principal_balance_cents` by the allocated amount."

    Design: Corner/consistency model/consistency_warranty_reopen_restores_principal_before_next_read
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
    claim = validate_success(file_claim(store["franchisee"], order, "idem-consistency-1",
                                        apply_to_account_id=account["id"]), 201)

    # The order sold 12 months before the claim is resolved, so the charge is priced.
    set_clock("2027-09-13T00:00:00Z")
    approved = approve_claim(store["franchisee"], order, claim)
    assert approved["principal_allocated_cents"] == 4800
    assert get_account(account["id"])["principal_balance_cents"] == 50138

    reopened = validate_success(advance_claim(store["franchisee"], order, claim,
                                              "REOPEN"))
    assert reopened["claim_status"] == "SUBMITTED"
    assert reopened["principal_allocated_cents"] == 0
    assert get_account(account["id"])["principal_balance_cents"] == 45338, (
        "the allocation is removed exactly as it was written")
    assert get_order(order["id"])["financed_principal_cents"] == 45338


def test_account_technician_and_franchisee_aggregates_agree_in_one_pass(api):
    """PRD §2.10: "`outstanding_credit_cents` sums `current_balance_cents` over those same `ACTIVE` and `DELINQUENT`
    accounts"
    PRD §2.13: "A technician's
    `revolving_used_cents` sums `current_balance_cents` over the technician's accounts whose `account_kind`
    is `REVOLVING` and whose `account_status` is `ACTIVE` or `DELINQUENT`"

    Design: Corner/consistency model/consistency_cross_entity_reference_cascades_to_technician_and_franchisee
    """
    set_clock("2026-09-07T00:00:00Z")
    store = setup_storefront(mix_plan="POWER_TOOLS")
    people = setup_shop_and_technician(store)
    product = setup_product_with_stock(store, on_hand=10)
    account = setup_account(store["franchisee"], people["shop"], people["technician"],
                            requested_limit_cents=45_338)
    create_delivered_order(store["franchisee"], store["route"], people["technician"],
                           account, [order_line(product, 3)],
                           mix_profile="DIAGNOSTIC_WEIGHTED")

    set_clock("2026-09-14T00:00:00Z")
    account_read = get_account(account["id"])
    assert account_read["current_balance_cents"] == 45474
    assert account_read["accrued_finance_charge_cents"] == 136

    technician = get_technician(people["technician"]["id"])
    assert technician["revolving_used_cents"] == 45474
    assert technician["revolving_available_cents"] == 100000 - 45474

    franchisee = get_franchisee(store["franchisee"]["id"])
    assert franchisee["credit_ceiling_cents"] == 45338
    assert franchisee["outstanding_credit_cents"] == 45474


def test_deactivating_a_shop_removes_it_from_the_active_roster(api):
    """PRD §3.2: "A shop's `shop_name`, `street_line` and `shop_status` may be
    revised by the owning `FranchiseOwner`, and each such revision also refreshes the franchisee's
    fallback pointer."
    PRD §3.2: "A shop's `active_technician_count` is derived: it counts the technicians whose
    `technician_status` is `ACTIVE` and whose `current_shop_location_id` is that shop."

    Design: Corner/consistency model/consistency_soft_delete_shop_state_filters_technician_roster
    """
    set_clock("2026-09-07T00:00:00Z")
    store = setup_storefront()
    people = setup_shop_and_technician(store)

    active_rows = validate_success(api_client.list_shops(
        store["franchisee"]["owner_headers"], {"shop_status": "ACTIVE"}))
    assert len(active_rows) == 1
    assert active_rows[0]["id"] == people["shop"]["id"]
    assert active_rows[0]["active_technician_count"] == 1

    updated = validate_success(update_shop(store["franchisee"], people["shop"],
                                           shop_status="INACTIVE"))
    assert updated["shop_status"] == "INACTIVE"

    after = validate_success(api_client.list_shops(
        store["franchisee"]["owner_headers"], {"shop_status": "ACTIVE"}))
    assert after == []

    still_there = get_shop(people["shop"]["id"], store["franchisee"]["owner_headers"])
    assert still_there["shop_status"] == "INACTIVE"
    assert get_technician(people["technician"]["id"])["technician_status"] == "ACTIVE"
