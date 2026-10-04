"""Per-line discount arithmetic, protection guards and cold-pack reservation sizing."""
import math

from test_helpers import TEST_USERS, api_client, get_success_data
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
    ship_order_ok,
)


def test_line_discounts_are_rounded_per_line_before_summing(api):
    """PRD §3.4: "the line's `line_autoship_discount_cents` is that base multiplied
    by the rate and rounded half up to a whole cent."
    PRD §3.4: "The order's `autoship_discount_cents` is the sum of the per-line
    discounts, and the order-level product is never rounded directly."
    PRD §2.6: "where a derived amount is a sum of per-line components, each
    component is rounded half up individually before the components are added — the
    total is never obtained by rounding an order-level product directly."

    Design: Difficulty/combinatorial_formula/discount_rounding_order_changes_the_order_total
    """
    set_clock()
    kibble = create_product(sku="BLD-A1", product_name="Foundation kibble",
                            medication_scope="OTC", cold_pack_required=False,
                            unit_dose_mg_per_kg=0.02, pack_size_units=20,
                            unit_price_cents=1005)
    chew = create_product(sku="BLD-B2", product_name="Joint chew",
                          medication_scope="OTC", cold_pack_required=False,
                          unit_dose_mg_per_kg=0.01, pack_size_units=10,
                          unit_price_cents=1005)
    pet = create_pet(pet_name="Otto", species="DOG", breed="Beagle",
                     weight_kg=20.0, owner_state="CA")
    plan = create_plan(pet)
    add_item(plan, pet, kibble, cadence_days=28)
    add_item(plan, pet, chew, cadence_days=28)
    compose_ok(plan, pet)  # first order; the next one takes the recurring rate

    # The first composition advanced both 28-day items from 2026-09-01 to
    # 2026-09-29, so advancing the logical clock to that date makes both due.
    set_clock("2026-09-29T00:00:00Z")
    order = compose_ok(plan, pet)
    lines = order_lines(order)
    assert len(lines) == 2, "both items are due and must be bundled into one order"

    per_line_sum = sum(line["line_autoship_discount_cents"] for line in lines)
    order_level_rounding = math.floor(2010 * 0.10 + 0.5)

    assert order["merchandise_subtotal_cents"] == 2010
    assert order["autoship_discount_cents"] == per_line_sum, (
        "the order discount must be the sum of the rounded per-line discounts"
    )
    assert order["autoship_discount_cents"] != order_level_rounding, (
        f"rounding once on the 2010 subtotal would give {order_level_rounding}"
    )
    assert order["order_total_cents"] == 2010 - order["autoship_discount_cents"]
    assert order["order_total_components_sum"] == order["order_total_cents"]


def test_recurring_bundle_takes_the_ten_percent_rate(api):
    """PRD §3.4: "The discount rate is 35 percent when the plan has no prior composed
    order and 10 percent for every order thereafter."
    PRD §3.4: "The order's `order_kind` is `FIRST` only when it is the plan's first
    successfully composed order and `RECURRING` for every later one"

    Design: Difficulty/combinatorial_formula/discount_rounding_order_changes_the_order_total
    """
    set_clock()
    kibble = create_product(sku="BLD-A1", product_name="Foundation kibble",
                            medication_scope="OTC", cold_pack_required=False,
                            unit_dose_mg_per_kg=0.02, pack_size_units=20,
                            unit_price_cents=1550)
    chew = create_product(sku="BLD-B2", product_name="Joint chew",
                          medication_scope="OTC", cold_pack_required=False,
                          unit_dose_mg_per_kg=0.01, pack_size_units=10,
                          unit_price_cents=656)
    pet = create_pet(pet_name="Otto", species="DOG", breed="Beagle",
                     weight_kg=20.0, owner_state="CA")
    plan = create_plan(pet)
    add_item(plan, pet, kibble, cadence_days=28)
    first_order = compose_ok(plan, pet)
    add_item(plan, pet, chew, cadence_days=28)

    # The first composition advanced the 28-day item to 2026-09-29, and the
    # newly added item is due immediately, so both bundle on the same date.
    set_clock("2026-09-29T00:00:00Z")
    order = compose_ok(plan, pet)
    assert first_order["order_kind"] == "FIRST"
    assert order["order_kind"] == "RECURRING"

    line_a = next(l for l in order_lines(order) if l["line_item_subtotal_cents"] == 1550)
    assert line_a["line_autoship_discount_cents"] == 155, (
        "1550 cents at the recurring 10 percent rate rounds half up to 155"
    )


def test_protection_guard_prices_the_line_and_the_cold_pack_ladder_reserves(api):
    """PRD §3.4: "the guard amount is that protected price multiplied by one plus
    five percent and rounded half up to a whole cent, the item's `protection_state`
    reads `PROTECTED` while its current `unit_price_cents` is at or below the guard
    and `REPRICED` once it is above, and the line's `line_unit_price_cents` is the
    smaller of the item's current unit price and the guard"
    PRD §3.5: "The whole sum is rounded up to a whole number of units and becomes
    the shipment's `cold_pack_units`, written also onto the reservation"

    Design: Difficulty/combinatorial_formula/battery_capacity_ladder_and_guard_price_interact
    """
    set_clock()
    site = create_site(site_code="SAC1", site_state="CA", licensed_states=["CA", "NV"],
                       cold_pack_capacity_units=411, csr_registered=True)
    product = create_product(sku="BLD-C3", product_name="Insulin analogue",
                             medication_scope="OTC", cold_pack_required=True,
                             unit_dose_mg_per_kg=0.02, pack_size_units=10,
                             unit_price_cents=319)
    pet = create_pet(pet_name="Nova", species="CAT", breed="Siamese",
                     weight_kg=18.0, owner_state="CA")
    plan = create_plan(pet)
    item = add_item(plan, pet, product, cadence_days=28, default_quantity=2)
    compose_ok(plan, pet)  # locks price_protected_unit_price_cents at 319

    api_client.change_product_price(product["id"], {"unit_price_cents": 599},
                                    TEST_USERS["compliance_officer_headers"])
    set_clock("2026-10-28T00:00:00Z")
    order = compose_ok(plan, pet)
    line = order_lines(order)[0]

    guard = math.floor(319 * 1.05 + 0.5)
    assert guard == 335, "the guard over a protected price of 319 is 335 cents"
    assert line["line_unit_price_cents"] == guard, (
        "a list price raised to 599 is charged at the guard rather than in full"
    )
    assert line["line_item_subtotal_cents"] == guard * 2
    item_after = read_item(plan, pet, item)
    assert item_after["protection_state"] == "REPRICED"
    assert item_after["price_protected_unit_price_cents"] == 319, (
        "the protected price is written once and never rewritten"
    )

    shipment = create_shipment(order)
    expected_units = math.ceil(24.0 + 1.5 * 21.0 + 0.0 + (2 - 1) / 4.0)
    assert expected_units == 56
    ship_order_ok(order)
    shipment_after = get_success_data(api_client.get_shipment(
        shipment["id"], TEST_USERS["pharmacy_technician_headers"]))
    assert shipment_after["cold_pack_required"] is True
    assert shipment_after["cold_pack_units"] == expected_units
    assert shipment_after["cold_pack_units"] < 411
    assert read_site(site)["cold_pack_committed_units"] == expected_units


def test_cold_pack_ladder_scales_with_the_sites_existing_load(api):
    """PRD §3.5: "it adds the site's currently committed load multiplied by that
    same 21-degree difference divided by 100 cooling-burden hours per degree"

    Design: Difficulty/combinatorial_formula/battery_capacity_ladder_and_guard_price_interact
    """
    bundle = None
    set_clock()
    site = create_site(site_code="SAC1", site_state="CA", licensed_states=["CA", "NV"],
                       cold_pack_capacity_units=411, csr_registered=True)
    first_product = create_product(sku="BLD-C4", product_name="Insulin analogue",
                                   medication_scope="OTC", cold_pack_required=True,
                                   unit_dose_mg_per_kg=0.02, pack_size_units=10,
                                   unit_price_cents=319)

    # First order: quantity 2, site load 0 -> 56 units committed.
    pet_a = create_pet(pet_name="Nova", species="CAT", breed="Siamese",
                       weight_kg=18.0, owner_state="CA")
    plan_a = create_plan(pet_a)
    add_item(plan_a, pet_a, first_product, cadence_days=28, default_quantity=2)
    order_a = compose_ok(plan_a, pet_a)
    create_shipment(order_a)
    ship_order_ok(order_a)
    assert read_site(site)["cold_pack_committed_units"] == 56

    # Second order: same basket, but the site already carries 56 committed units,
    # so the cooling-burden term adds 56 * 21 / 100 = 11.76 hours.
    pet_b = create_pet(pet_name="Orbit", species="CAT", breed="Siamese",
                       weight_kg=18.0, owner_state="CA")
    plan_b = create_plan(pet_b)
    add_item(plan_b, pet_b, first_product, cadence_days=28, default_quantity=2)
    order_b = compose_ok(plan_b, pet_b)
    shipment_b = create_shipment(order_b)
    ship_order_ok(order_b)
    shipment_b_after = get_success_data(api_client.get_shipment(
        shipment_b["id"], TEST_USERS["pharmacy_technician_headers"]))

    expected = math.ceil(24.0 + 1.5 * 21.0 + 56 * 21.0 / 100.0 + (2 - 1) / 4.0)
    assert expected == 68
    assert shipment_b_after["cold_pack_units"] == expected, (
        "the ladder reads the site load observed before this shipment is packed"
    )
    assert read_site(site)["cold_pack_committed_units"] == 56 + expected


def test_first_order_discount_uses_the_fixed_rate(api):
    """PRD §3.4: "The discount rate is 35 percent when the plan has no prior composed
    order and 10 percent for every order thereafter."
    PRD §3.4: "The order's `order_kind` is `FIRST` only when it is the plan's first
    successfully composed order"

    Design: Corner/calculations/first_order_discount_uses_the_fixed_rate_and_per_line_rounding
    """
    set_clock()
    product = create_product(sku="CAL-12", product_name="First order pack",
                             medication_scope="OTC", cold_pack_required=False,
                             unit_dose_mg_per_kg=0.02, pack_size_units=10,
                             unit_price_cents=1001)
    pet = create_pet(pet_name="Fennel", species="DOG", breed="Schipperke",
                     weight_kg=7.0, owner_state="CA")
    plan = create_plan(pet)
    add_item(plan, pet, product, cadence_days=28)

    order = compose_ok(plan, pet)
    assert order["order_kind"] == "FIRST"
    assert order["merchandise_subtotal_cents"] == 1001
    assert order["autoship_discount_cents"] == 350, (
        "1001 cents at the 35 percent first-order rate rounds half up to 350"
    )
    assert order["cold_pack_fee_cents"] == 0
    assert order["expedited_shipping_fee_cents"] == 0
    assert order["order_total_cents"] == 651


def test_ordinary_order_carries_neither_the_cold_pack_nor_the_expedited_fee(api):
    """PRD §2.6: "The cold-pack fee is exactly 599 cents when at least one line in the
    order is cold-pack-required and exactly 0 otherwise; this is written to
    `cold_pack_fee_cents`. The expedited-shipping fee, written to
    `expedited_shipping_fee_cents`, is exactly 990 cents when at least one line
    carries a prescription whose drug schedule is `CII` or `CIII`, and exactly 0
    otherwise."
    PRD §3.4: "the expedited fee is 990 cents when any line carries a `CII` or `CIII`
    prescription; both are exactly 0 otherwise."

    Design: Corner/validations/shipping_a_single_controlled_prescription_carries_the_expedited_fee
    """
    set_clock()
    product = create_product(sku="VAL-02", product_name="Ordinary pack",
                             medication_scope="OTC", cold_pack_required=False,
                             unit_dose_mg_per_kg=0.02, pack_size_units=10,
                             unit_price_cents=1200)
    pet = create_pet(pet_name="Anise", species="CAT", breed="Manx",
                     weight_kg=4.0, owner_state="CA")
    plan = create_plan(pet)
    add_item(plan, pet, product, cadence_days=28)

    order = compose_ok(plan, pet)

    assert order["expedited_shipping_fee_cents"] == 0, (
        "no line carries a CII or CIII prescription"
    )
    assert order["cold_pack_fee_cents"] == 0, "no line is cold-pack-required"
    assert order["merchandise_subtotal_cents"] == 1200
    assert order["autoship_discount_cents"] == 420
    assert order["order_total_cents"] == 780


def test_controlled_prescription_line_carries_the_expedited_fee(api):
    """PRD §2.6: "The expedited-shipping fee, written to `expedited_shipping_fee_cents`,
    is exactly 990 cents when at least one line carries a prescription whose drug
    schedule is `CII` or `CIII`, and exactly 0 otherwise."
    PRD §2.6: "The derived total and the component sum are kept equal by recomputing
    the component sum from the same four terms whenever any of them changes."

    Design: Corner/validations/shipping_a_single_controlled_prescription_carries_the_expedited_fee
    """
    from test_helpers.fixtures import setup_verified_prescription_item
    bundle = setup_verified_prescription_item(
        product_overrides=dict(sku="VAL-02C", product_name="Controlled pack",
                              medication_scope="PRESCRIPTION",
                              unit_dose_mg_per_kg=0.02, pack_size_units=10,
                              unit_price_cents=2000),
        prescription_overrides=dict(drug_schedule="CII", authorized_qty_total=60,
                                    refills_authorized=0))
    assert bundle["rx"]["rx_status"] == "VERIFIED"

    order = compose_ok(bundle["plan"], bundle["pet"])

    assert order["expedited_shipping_fee_cents"] == 990, (
        "the order carries a CII prescription line"
    )
    assert order["cold_pack_fee_cents"] == 0
    assert order["merchandise_subtotal_cents"] == 2000
    assert order["order_total_cents"] == 2000 - order["autoship_discount_cents"] + 990
    assert order["order_total_cents"] == order["order_total_components_sum"]