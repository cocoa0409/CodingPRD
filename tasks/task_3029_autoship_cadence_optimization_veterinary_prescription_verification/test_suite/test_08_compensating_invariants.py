"""Conserved quantities: cold-pack capacity and settlement arithmetic."""
from test_helpers import (
    TEST_USERS,
    api_client,
    get_success_data,
    make_customer_headers,
)
from test_helpers.fixtures import (
    add_item,
    cancel_order,
    compose_ok,
    create_pet,
    create_plan,
    create_product,
    create_shipment,
    decide_review,
    read_item,
    read_order,
    read_plan,
    read_site,
    set_clock,
    setup_cold_pack_capacity_plan,
    ship_order_ok,
)


def test_cold_pack_commit_matches_the_computed_reservation(api):
    """PRD §3.5: "the commit step moves its `reservation_status` from `HELD` to
    `CONSUMED` and folds the shipment's units into the site's committed load"
    PRD §3.5: "The site's `cold_pack_committed_units` is by invariant the sum of the
    `units` on its held reservations only"

    Design: Difficulty/compensating_invariant/cold_pack_release_restores_the_sites_committed_load
    """
    bundle = setup_cold_pack_capacity_plan()
    site = bundle["site"]
    order = compose_ok(bundle["plan"], bundle["pet"])
    shipment = create_shipment(order)

    assert read_site(site)["cold_pack_committed_units"] == 0, (
        "the site holds no committed load before the pack step"
    )

    ship_order_ok(order)
    shipment_after = get_success_data(api_client.get_shipment(
        shipment["id"], TEST_USERS["pharmacy_technician_headers"]))
    committed = read_site(site)["cold_pack_committed_units"]
    assert committed == shipment_after["cold_pack_units"], (
        "the committed load equals the shipment's reserved units"
    )
    assert committed > 0


def test_cancelling_the_order_restores_the_sites_committed_load(api):
    """PRD §3.6: "The order moves to the terminal `CANCELED`, its shipment is
    cancelled, and any held or committed cold-pack reservation at the origin site is
    released."
    PRD §3.5: "the release step moves it from `HELD` to `RELEASED` and removes them."

    Design: Difficulty/compensating_invariant/cold_pack_release_restores_the_sites_committed_load
    """
    bundle = setup_cold_pack_capacity_plan()
    site = bundle["site"]
    pet = bundle["pet"]
    order = compose_ok(bundle["plan"], pet)
    create_shipment(order)
    ship_order_ok(order)
    committed_after_ship = read_site(site)["cold_pack_committed_units"]
    assert committed_after_ship > 0

    get_success_data(cancel_order(order, "CUSTOMER_REQUEST", as_pet=pet), 200)

    released = read_site(site)["cold_pack_committed_units"]
    assert released == 0, (
        "the compensating action returns the site to its exact pre-ship value"
    )
    assert released == 0 and committed_after_ship > 0, "capacity was conserved exactly"


def test_released_cold_pack_reservation_is_terminal(api):
    """PRD §3.5: "the release step moves it from `HELD` to `RELEASED` and removes
    them."
    PRD §3.6: "its shipment is cancelled, and any held or committed cold-pack
    reservation at the origin site is released."

    Design: Difficulty/compensating_invariant/cold_pack_release_restores_the_sites_committed_load
    """
    bundle = setup_cold_pack_capacity_plan()
    site = bundle["site"]
    pet = bundle["pet"]
    order = compose_ok(bundle["plan"], pet)
    shipment = create_shipment(order)
    ship_order_ok(order)
    get_success_data(cancel_order(order, "CUSTOMER_REQUEST", as_pet=pet), 200)

    reservations = get_success_data(api_client.list_shipment_reservations(
        shipment["id"], TEST_USERS["pharmacy_technician_headers"]))
    assert reservations, "the shipment carried at least one cold-pack reservation"
    assert all(r["reservation_status"] == "RELEASED" for r in reservations)
    assert read_site(site)["cold_pack_committed_units"] == 0


def test_release_lets_the_site_be_closed_again(api):
    """PRD §3.5: "Closing a site is permitted only from `ACTIVE` and only while its
    `cold_pack_committed_units` is exactly zero, so capacity already promised to
    in-flight work is never stranded"
    PRD §3.5: "the site's `cold_pack_committed_units` is by invariant the sum of the
    `units` on its held reservations only"

    Design: Difficulty/compensating_invariant/cold_pack_release_restores_the_sites_committed_load
    """
    bundle = setup_cold_pack_capacity_plan()
    site = bundle["site"]
    pet = bundle["pet"]
    order = compose_ok(bundle["plan"], pet)
    create_shipment(order)
    ship_order_ok(order)
    get_success_data(cancel_order(order, "CUSTOMER_REQUEST", as_pet=pet), 200)

    get_success_data(api_client.close_site(site["id"],
                                          TEST_USERS["compliance_officer_headers"]), 200)
    assert read_site(site)["site_status"] == "CLOSED"


def test_settlement_net_reconciles_against_the_plan_refunds(api):
    """PRD §3.6: "An order's `settlement_net_cents` is its `order_total_cents` minus
    its `refunded_amount_cents`."
    PRD §3.6: "the plan's `released_refunds_cents` accumulates each order's
    `refunded_amount_cents` while the plan's `transaction_adjustments_cents`
    accumulates each order's `settlement_net_cents`"

    Design: Difficulty/compensating_invariant/settlement_net_reversal_leaves_the_plans_released_refunds_exact
    """
    bundle = setup_cold_pack_capacity_plan(
        product_overrides=dict(sku="CMP-J2", product_name="Invariant settlement pack",
                               cold_pack_required=True, unit_price_cents=1193))
    pet = bundle["pet"]
    plan = bundle["plan"]

    canceled_order = compose_ok(plan, pet)
    get_success_data(cancel_order(canceled_order, "CUSTOMER_REQUEST", as_pet=pet), 200)
    set_clock("2026-10-01T00:00:00Z")
    delivered_order = compose_ok(plan, pet)
    create_shipment(delivered_order)
    ship_order_ok(delivered_order)
    get_success_data(api_client.deliver_order(
        delivered_order["id"], TEST_USERS["pharmacy_technician_headers"]), 200)

    pet_after = get_success_data(api_client.report_passing(
        pet["id"], {"refund_destination": "WALLET"}, make_customer_headers(pet["id"])))
    review_id = pet_after["compassionate_review_id"]
    assert decide_review(review_id, "APPROVED", "cs-ray").status_code == 200

    cancelled = read_order(canceled_order, as_pet=pet)
    delivered = read_order(delivered_order, as_pet=pet)
    plan_after = read_plan(plan, pet)

    assert cancelled["refunded_amount_cents"] == 1193
    assert cancelled["settlement_net_cents"] == (
        cancelled["order_total_cents"] - cancelled["refunded_amount_cents"]
    )
    assert delivered["refunded_amount_cents"] == 0, "a delivered order contributes no refund"
    assert plan_after["released_refunds_cents"] == cancelled["refunded_amount_cents"]
    assert plan_after["transaction_adjustments_cents"] == (
        cancelled["settlement_net_cents"] + delivered["settlement_net_cents"]
    )


def test_cadence_changes_leave_the_plan_due_date_recomputed(api):
    """PRD §3.2: "A successful change increments the item's `version`, advances
    `autoship_item_next_due_date` from the new cadence, and recomputes the item's
    `cadence_prompt_state` together with the plan's `next_order_due_date`."
    PRD §3.1: "`next_order_due_date`, which considers only the remaining `ACTIVE`
    items"

    Design: Corner/validations/settling_a_deadline_boundary_cadence_does_not_move_the_plan_due_date
    """
    set_clock("2026-09-02T00:00:00Z")
    pack_a = create_product(sku="VAL-03A", product_name="Temporal pack A",
                            medication_scope="OTC", cold_pack_required=False,
                            unit_dose_mg_per_kg=0.02, pack_size_units=10,
                            unit_price_cents=1000)
    pack_b = create_product(sku="VAL-03B", product_name="Temporal pack B",
                            medication_scope="OTC", cold_pack_required=False,
                            unit_dose_mg_per_kg=0.02, pack_size_units=10,
                            unit_price_cents=1100)
    pet = create_pet(pet_name="Quince", species="DOG", breed="Elkhound",
                     weight_kg=20.0, owner_state="CA")
    plan = create_plan(pet, blackout_start_date="2026-10-10T00:00:00Z",
                       blackout_end_date="2026-10-20T00:00:00Z")
    item_a = add_item(plan, pet, pack_a, cadence_days=28)
    add_item(plan, pet, pack_b, cadence_days=42)

    version = read_item(plan, pet, item_a)["version"]
    changed = get_success_data(api_client.change_cadence(
        plan["id"], item_a["id"],
        {"expected_item_version": version, "cadence_days": 14},
        make_customer_headers(pet["id"])), 200)

    assert changed["cadence_days"] == 14
    assert read_item(plan, pet, item_a)["autoship_item_next_due_date"] == "2026-09-16T00:00:00.000Z"
    plan_after = read_plan(plan, pet)
    assert plan_after["next_order_due_date"] == "2026-09-02T00:00:00.000Z", (
        "the due date is recomputed from the earliest remaining item"
    )
    assert plan_after["autoship_item_count"] == 2