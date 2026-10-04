"""Exact numeric and interval boundaries."""
import math

from test_helpers import TEST_USERS, api_client, validate_error, get_success_data
from test_helpers.fixtures import (
    add_item,
    compose,
    compose_ok,
    create_pet,
    create_plan,
    create_product,
    create_shipment,
    create_site,
    order_lines,
    plan_version,
    read_item,
    read_plan,
    read_site,
    set_clock,
    ship_order,
    ship_order_ok,
)


def test_protection_boundary_is_inclusive_at_the_rounded_guard(api):
    """PRD §2.6: "an item is `PROTECTED` while its current unit price is less than
    or equal to that guard and `REPRICED` once the current price exceeds it."
    PRD §3.4: "the line's `line_unit_price_cents` is the smaller of the item's
    current unit price and the guard — so a list price raised past the guard is
    charged at the guard rather than in full."

    Design: Difficulty/boundary_precision_check/protection_guard_boundary_is_inclusive_at_the_rounded_guard
    """
    set_clock()
    product = create_product(sku="BND-F1", product_name="Boundary guard pack",
                             medication_scope="OTC", cold_pack_required=False,
                             unit_dose_mg_per_kg=0.02, pack_size_units=10,
                             unit_price_cents=1610)
    pet = create_pet(pet_name="Remy", species="CAT", breed="Abyssinian",
                     weight_kg=14.0, owner_state="CA")
    plan = create_plan(pet)
    item = add_item(plan, pet, product, cadence_days=28)
    compose_ok(plan, pet)

    guard = math.floor(1610 * 1.05 + 0.5)
    assert guard == 1691, "the guard over a protected price of 1610 is exactly 1691"
    api_client.change_product_price(product["id"], {"unit_price_cents": guard},
                                    TEST_USERS["compliance_officer_headers"])
    set_clock("2026-10-29T00:00:00Z")

    order = compose_ok(plan, pet)
    line = order_lines(order)[0]
    assert line["line_unit_price_cents"] == guard, (
        "a price equal to the guard is still protected, so the comparison is inclusive"
    )
    assert read_item(plan, pet, item)["protection_state"] == "PROTECTED"


def test_raising_the_list_price_one_cent_past_the_guard_reprices(api):
    """PRD §2.6: "an item is `PROTECTED` while its current unit price is less than
    or equal to that guard and `REPRICED` once the current price exceeds it."
    PRD §3.1: "A list price is changed by supplying a replacement `unit_price_cents`,
    which overwrites the stored price and forces every autoship item scheduling that
    product to recompute both its `unit_price_cents` and its `protection_state`."

    Design: Difficulty/boundary_precision_check/protection_guard_boundary_is_inclusive_at_the_rounded_guard
    """
    set_clock()
    product = create_product(sku="BND-F1", product_name="Boundary guard pack",
                             medication_scope="OTC", cold_pack_required=False,
                             unit_dose_mg_per_kg=0.02, pack_size_units=10,
                             unit_price_cents=1610)
    pet = create_pet(pet_name="Remy", species="CAT", breed="Abyssinian",
                     weight_kg=14.0, owner_state="CA")
    plan = create_plan(pet)
    item = add_item(plan, pet, product, cadence_days=28)
    compose_ok(plan, pet)

    api_client.change_product_price(product["id"], {"unit_price_cents": 1692},
                                    TEST_USERS["compliance_officer_headers"])
    set_clock("2026-10-29T00:00:00Z")

    order = compose_ok(plan, pet)
    line = order_lines(order)[0]
    item_after = read_item(plan, pet, item)
    assert item_after["unit_price_cents"] == 1692
    assert item_after["protection_state"] == "REPRICED", (
        "one cent past the 1691 guard flips the state"
    )
    assert line["line_unit_price_cents"] == 1691, (
        "the line is still charged at the guard, never at the raised list price"
    )
    assert line["line_unit_price_cents"] != 1692


def test_empty_due_set_still_composes_a_zero_line_order(api):
    """PRD §3.4: "A request is accepted even when nothing at all is due, in which
    case an order is still created and its `bundle_line_count` is 0."

    Design: Difficulty/boundary_precision_check/empty_due_set_composes_a_zero_line_order
    """
    set_clock()
    kibble = create_product(sku="BND-G1", product_name="Empty set kibble",
                            medication_scope="OTC", cold_pack_required=False,
                            unit_dose_mg_per_kg=0.02, pack_size_units=10,
                            unit_price_cents=800)
    chew = create_product(sku="BND-G2", product_name="Empty set chew",
                          medication_scope="OTC", cold_pack_required=False,
                          unit_dose_mg_per_kg=0.02, pack_size_units=10,
                          unit_price_cents=900)
    pet = create_pet(pet_name="Wren", species="DOG", breed="Whippet",
                     weight_kg=14.0, owner_state="CA")
    plan = create_plan(pet)
    item_g1 = add_item(plan, pet, kibble, cadence_days=28)
    item_g2 = add_item(plan, pet, chew, cadence_days=14)
    compose_ok(plan, pet)

    due_g1 = read_item(plan, pet, item_g1)["autoship_item_next_due_date"]
    due_g2 = read_item(plan, pet, item_g2)["autoship_item_next_due_date"]

    resp = compose(plan, pet)
    assert resp.status_code == 201, "the empty due set is a legal outcome"
    empty_order = resp.json()["data"]

    assert empty_order["bundle_line_count"] == 0
    assert empty_order["merchandise_subtotal_cents"] == 0
    assert empty_order["autoship_discount_cents"] == 0
    assert empty_order["order_total_cents"] == 0
    assert order_lines(empty_order) == []

    assert read_item(plan, pet, item_g1)["autoship_item_next_due_date"] == due_g1
    assert read_item(plan, pet, item_g2)["autoship_item_next_due_date"] == due_g2, (
        "no item was due, so no cadence advance may fire"
    )


def test_empty_due_set_order_is_legal_rather_than_a_constraint_violation(api):
    """PRD §3.4: "The composed order records the `autoship_plan_id` it was composed
    from, so that the plan's order history is reachable from it."
    PRD §3.4: "its `bundle_line_count` is 0"

    Design: Difficulty/boundary_precision_check/empty_due_set_composes_a_zero_line_order
    """
    set_clock()
    product = create_product(sku="BND-G1", product_name="Empty set kibble",
                             medication_scope="OTC", cold_pack_required=False,
                             unit_dose_mg_per_kg=0.02, pack_size_units=10,
                             unit_price_cents=800)
    pet = create_pet(pet_name="Wren", species="DOG", breed="Whippet",
                     weight_kg=14.0, owner_state="CA")
    plan = create_plan(pet)
    add_item(plan, pet, product, cadence_days=28)
    first = compose_ok(plan, pet)
    assert first["bundle_line_count"] == 1

    second = compose_ok(plan, pet)
    assert second["order_kind"] == "RECURRING"
    assert second["bundle_line_count"] == 0
    orders = get_success_data(api_client.list_plan_orders(
        plan["id"], TEST_USERS["customer_service_headers"]))
    assert len(orders) == 2, "both compositions produced a durable order row"


def test_cadence_window_ending_at_the_blackout_start_is_permitted(api):
    """PRD §3.2: "this cadence window is tested exactly as it stands, with no buffer,
    so a window that ends exactly on the blackout start date is permitted and only a
    window that ends a day later conflicts."

    Design: Difficulty/resource_temporal_overlap/cadence_window_boundary_moves_with_one_day_of_blackout_start
    """
    set_clock("2026-09-02T00:00:00Z")
    product = create_product(sku="OVL-I1", product_name="Overlap chews",
                             medication_scope="OTC", cold_pack_required=False,
                             unit_dose_mg_per_kg=0.02, pack_size_units=10,
                             unit_price_cents=1200)
    pet = create_pet(pet_name="Nix", species="CAT", breed="Burmese",
                     weight_kg=4.0, owner_state="CA")
    plan = create_plan(pet, blackout_start_date="2026-09-30T00:00:00Z",
                       blackout_end_date="2026-10-06T00:00:00Z")
    item = add_item(plan, pet, product, cadence_days=14)

    version = read_item(plan, pet, item)["version"]
    resp = api_client.change_cadence(plan["id"], item["id"],
                                    {"expected_item_version": version, "cadence_days": 28},
                                    TEST_USERS["customer_service_headers"])
    assert resp.status_code == 200, (
        "a 28-day window from 2026-09-02 ends exactly on the blackout start and is accepted"
    )
    assert read_item(plan, pet, item)["cadence_days"] == 28


def test_cadence_window_ending_one_day_past_adjacency_conflicts(api):
    """PRD §3.2: "it conflicts with the plan's blackout interval when the window's
    start falls strictly before the blackout end date and the blackout start date
    falls strictly before the window's end. ... A conflict is reported as
    `ERR_CADENCE_WINDOW_OVERLAP` with HTTP 409."

    Design: Difficulty/resource_temporal_overlap/cadence_window_boundary_moves_with_one_day_of_blackout_start
    """
    set_clock("2026-09-02T00:00:00Z")
    product = create_product(sku="OVL-I1", product_name="Overlap chews",
                             medication_scope="OTC", cold_pack_required=False,
                             unit_dose_mg_per_kg=0.02, pack_size_units=10,
                             unit_price_cents=1200)
    pet = create_pet(pet_name="Odette", species="CAT", breed="Birman",
                     weight_kg=4.1, owner_state="CA")
    plan = create_plan(pet, blackout_start_date="2026-09-29T00:00:00Z",
                       blackout_end_date="2026-10-06T00:00:00Z")
    item = add_item(plan, pet, product, cadence_days=14)

    version = read_item(plan, pet, item)["version"]
    resp = api_client.change_cadence(plan["id"], item["id"],
                                    {"expected_item_version": version, "cadence_days": 28},
                                    TEST_USERS["customer_service_headers"])
    validate_error(resp, "ERR_CADENCE_WINDOW_OVERLAP")
    assert resp.status_code == 409

    item_after = read_item(plan, pet, item)
    assert item_after["cadence_days"] == 14, "the refused attempt wrote nothing"
    assert item_after["version"] == version


def test_buffered_transit_window_conflicts_where_the_cadence_window_does_not(api):
    """PRD §3.5: "For a temperature-sensitive shipment, the window is extended by one
    day at its end before the overlap test, and it conflicts when the extended
    interval intersects the plan's blackout interval ... Because of that buffer, a
    transit window ending exactly on the blackout start date still conflicts and the
    request is refused with `ERR_TEMPERATURE_CHAIN_RISK` and HTTP 422"
    PRD §2.11: "the transit window acquires a one-day buffer at its end before it is
    compared with a blackout interval, while the cadence window compared against the
    same blackout interval acquires no buffer."

    Design: Difficulty/resource_temporal_overlap/transit_buffer_makes_the_adjacent_interval_conflict
    """
    set_clock()
    site = create_site(site_code="FRE7", site_state="CA", licensed_states=["CA"],
                       cold_pack_capacity_units=300, csr_registered=True)
    product = create_product(sku="OVL-I2", product_name="Overlap cold pack",
                             medication_scope="OTC", cold_pack_required=True,
                             unit_dose_mg_per_kg=0.02, pack_size_units=10,
                             unit_price_cents=1100)
    pet = create_pet(pet_name="Odi", species="CAT", breed="Persian",
                     weight_kg=4.2, owner_state="CA")
    plan = create_plan(pet, blackout_start_date="2026-09-30T00:00:00Z",
                       blackout_end_date="2026-10-06T00:00:00Z")
    add_item(plan, pet, product, cadence_days=28)
    set_clock("2026-09-29T00:00:00Z")

    order = compose_ok(plan, pet)
    shipment = create_shipment(order)
    resp = ship_order(order)

    validate_error(resp, "ERR_TEMPERATURE_CHAIN_RISK")
    assert resp.status_code == 422
    shipment_after = get_success_data(api_client.get_shipment(
        shipment["id"], TEST_USERS["pharmacy_technician_headers"]))
    assert shipment_after["shipment_status"] == "PENDING"
    assert read_site(site)["cold_pack_committed_units"] == 0


def test_unbuffered_transit_window_would_have_cleared_the_blackout(api):
    """PRD §2.11: "The shipment transit window and the plan blackout interval are
    likewise half-open, but the transit window acquires a one-day buffer at its end
    before it is compared with a blackout interval"
    PRD §3.5: "`transit_window_start_date` is the dispatch instant and
    `transit_window_end_date` is that instant advanced by 2 days, with the window
    treated as half-open so the start is included and the end is not."

    Design: Difficulty/resource_temporal_overlap/transit_buffer_makes_the_adjacent_interval_conflict
    """
    set_clock()
    site = create_site(site_code="FRE7", site_state="CA", licensed_states=["CA"],
                       cold_pack_capacity_units=300, csr_registered=True)
    product = create_product(sku="OVL-I2", product_name="Overlap cold pack",
                             medication_scope="OTC", cold_pack_required=True,
                             unit_dose_mg_per_kg=0.02, pack_size_units=10,
                             unit_price_cents=1100)
    pet = create_pet(pet_name="Odi", species="CAT", breed="Persian",
                     weight_kg=4.2, owner_state="CA")
    plan = create_plan(pet, blackout_start_date="2026-09-30T00:00:00Z",
                       blackout_end_date="2026-10-06T00:00:00Z")
    add_item(plan, pet, product, cadence_days=28)

    # A blackout-free plan carrying the identical cold-pack basket dispatches and
    # stamps a two-day window, which is the interval the buffered rule extends.
    set_clock("2026-09-29T00:00:00Z")
    clear_pet = create_pet(pet_name="Clear", species="CAT", breed="Persian",
                           weight_kg=4.2, owner_state="CA")
    clear_plan = create_plan(clear_pet)
    add_item(clear_plan, clear_pet, product, cadence_days=28)
    clear_order = compose_ok(clear_plan, clear_pet)
    create_shipment(clear_order)
    ship_order_ok(clear_order)

    shipment = get_success_data(api_client.list_order_shipments(
        clear_order["id"], TEST_USERS["pharmacy_technician_headers"]))[0]
    assert shipment["shipment_status"] == "DISPATCHED"
    assert shipment["transit_window_start_date"] == "2026-09-29T00:00:00.000Z"
    assert shipment["transit_window_end_date"] == "2026-10-01T00:00:00.000Z", (
        "the unbuffered window ends on 2026-10-01, inside the blackout only after "
        "the one-day buffer is appended"
    )