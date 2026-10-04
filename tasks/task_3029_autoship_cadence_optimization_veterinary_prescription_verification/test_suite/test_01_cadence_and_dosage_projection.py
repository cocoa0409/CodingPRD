"""Dosage, consumption-cycle and cadence-projection behaviour."""
from test_helpers import TEST_USERS, api_client, get_success_data, make_customer_headers
from test_helpers.fixtures import (
    create_pet,
    create_plan,
    create_product,
    add_item,
    set_clock,
    setup_calibrated_item,
    read_item,
    read_plan,
)


def test_equivalent_duration_uses_the_tiered_pipeline(api):
    """PRD §2.5: "Finally the cycle length is clamped into the range from 14 to 84
    days inclusive: values below 14 become 14, values above 84 become 84, and the
    clamped value is the equivalent lifecycle day count recorded on the item."
    PRD §3.2: "The larger of the two contributions is taken, floored at one unit
    per day, and the pack's `pack_size_units` is divided by that rate and rounded
    down to a whole number of days."

    Design: Difficulty/dual_variant_calc/recalc_after_weight_change_redraws_consumption_cadence
    """
    pet, plan, product, item = setup_calibrated_item()

    assert item["unit_lifecycle_equivalent_days"] == 30, (
        "a 40 kg dog on a 30-unit pack dosed at 0.035 mg/kg yields one unit per day "
        "and therefore a 30-day cycle under the tiered pipeline"
    )
    assert item["unit_lifecycle_equivalent_days"] != 4, (
        "the whole-day band reading would yield 4 and must not be the value recorded"
    )


def test_cadence_prompt_state_reads_aligned_inside_the_window(api):
    """PRD §3.2: "the item reads `UNDER_CONSUMPTION` when the equivalent duration
    exceeds the chosen cadence by more than 3 days, `OVER_CONSUMPTION` when the
    chosen cadence exceeds the equivalent duration by more than 3 days, and
    `ALIGNED` in every other case."
    PRD §3.1: "Adding an item recomputes the plan's `autoship_item_count` and its
    `next_order_due_date`, and computes the item's `unit_lifecycle_equivalent_days`
    and `cadence_prompt_state`."

    Design: Difficulty/dual_variant_calc/recalc_after_weight_change_redraws_consumption_cadence
    """
    pet, plan, product, item = setup_calibrated_item(cadence_days=28)

    assert item["cadence_days"] == 28
    assert item["default_quantity"] == 1
    assert item["cadence_prompt_state"] == "ALIGNED", (
        "30 minus 28 is 2, which does not exceed the 3-day window"
    )
    plan_after = read_plan(plan, pet)
    assert plan_after["next_order_due_date"] == "2026-09-01T00:00:00.000Z"
    assert plan_after["autoship_item_count"] == 1


def test_daily_dosage_applies_the_species_multiplier_once(api):
    """PRD §2.5: "The multiplication is carried out in full and the final product
    alone is rounded half up to exactly two decimal places; no intermediate term
    is rounded."
    PRD §3.2: "the factor is 1.0 for a `CAT` and 1.2 for a `DOG`, `HORSE` or `BIRD`."

    Design: Difficulty/dual_variant_calc/dosage_projection_diverges_by_species_multiplier
    """
    set_clock()
    product = create_product(sku="DSG-CAT1", product_name="Dosage calibration chew",
                             medication_scope="OTC", cold_pack_required=False,
                             unit_dose_mg_per_kg=0.035, pack_size_units=30,
                             unit_price_cents=1200)
    pet = create_pet(pet_name="Bella", species="CAT", breed="Siamese",
                     weight_kg=40.0, owner_state="TX")
    plan = create_plan(pet)
    item = add_item(plan, pet, product, cadence_days=28, default_quantity=1)

    # dosage = round_half_up(0.035 * 40.0 * 1.0, 2) = 1.40 for a CAT,
    # whereas the same weight for a DOG reads round_half_up(0.035 * 40.0 * 1.2, 2) = 1.68.
    assert item["default_quantity"] == 1
    assert item["cadence_days"] == 28
    assert item["dosage_mg_per_day"] == 1.40, (
        "a CAT carries the 1.0 species multiplier, not the 1.2 used for other species"
    )


def test_consumption_projection_ignores_the_species_multiplier(api):
    """PRD §2.5: "The pet's weight is first floored at a sentinel minimum of 2.5
    kilograms, so a lighter pet is treated as weighing 2.5."
    PRD §2.5: "That sentinel weight is then rounded up to the next whole kilogram."

    Design: Difficulty/dual_variant_calc/dosage_projection_diverges_by_species_multiplier
    """
    set_clock()
    product = create_product(sku="DSG-D40", product_name="Dosage calibration chew",
                             medication_scope="OTC", cold_pack_required=False,
                             unit_dose_mg_per_kg=0.035, pack_size_units=30,
                             unit_price_cents=1200)
    dog = create_pet(pet_name="Rex", species="DOG", breed="Labrador",
                     weight_kg=40.0, owner_state="TX")
    cat = create_pet(pet_name="Miso", species="CAT", breed="Siamese",
                     weight_kg=40.0, owner_state="TX")
    dog_plan = create_plan(dog)
    cat_plan = create_plan(cat)
    dog_item = add_item(dog_plan, dog, product, cadence_days=28, default_quantity=1)
    cat_item = add_item(cat_plan, cat, product, cadence_days=28, default_quantity=1)

    assert dog_item["unit_lifecycle_equivalent_days"] == 30
    assert cat_item["unit_lifecycle_equivalent_days"] == 30, (
        "the consumption cycle reads only the weight and the pack size, so both "
        "species agree here while their dosages differ"
    )
    assert dog_item["dosage_mg_per_day"] == 1.68
    assert cat_item["dosage_mg_per_day"] == 1.40, (
        "the same weight and product diverge on the species multiplier alone"
    )


def test_band_reading_differs_from_the_pinned_pipeline(api):
    """PRD §2.5: "The raw cycle length is the product's pack size in units divided
    by that units-per-day figure, rounded down to a whole number."

    Design: Corner/calculations/band_variant_and_base_variant_disagree_on_equivalent_duration
    """
    pet, plan, product, item = setup_calibrated_item(cadence_days=28)

    assert item["unit_lifecycle_equivalent_days"] == 30
    assert item["cadence_prompt_state"] == "ALIGNED"
    item_after = read_item(plan, pet, item)
    assert item_after["unit_lifecycle_equivalent_days"] == 30, (
        "the value is recomputed on read rather than cached"
    )
    assert item["unit_lifecycle_equivalent_days"] != 4, (
        "the whole-day band reading yields 4 for the same weight and pack size"
    )


def test_cadence_prompt_flips_once_the_chosen_cadence_drifts(api):
    """PRD §3.2: "the item reads `UNDER_CONSUMPTION` when the equivalent duration
    exceeds the chosen cadence by more than 3 days, `OVER_CONSUMPTION` when the
    chosen cadence exceeds the equivalent duration by more than 3 days"
    PRD §3.2: "A successful change increments the item's `version`, advances
    `autoship_item_next_due_date` from the new cadence, and recomputes the item's
    `cadence_prompt_state` together with the plan's `next_order_due_date`."

    Design: Corner/cross_cutting_complexity_layers/cadence_prompt_fires_once_the_plan_due_date_passes_the_threshold
    """
    set_clock()
    product = create_product(sku="THR-01", product_name="Threshold pack",
                             medication_scope="OTC", cold_pack_required=False,
                             unit_dose_mg_per_kg=0.02, pack_size_units=10,
                             unit_price_cents=1100)
    pet = create_pet(pet_name="Sagebrush", species="DOG", breed="Airedale",
                     weight_kg=24.0, owner_state="CA")
    plan = create_plan(pet)
    item = add_item(plan, pet, product, cadence_days=14)
    equivalent = item["unit_lifecycle_equivalent_days"]
    assert item["cadence_prompt_state"] == "ALIGNED"

    version = read_item(plan, pet, item)["version"]
    changed = get_success_data(api_client.change_cadence(
        plan["id"], item["id"],
        {"expected_item_version": version, "cadence_days": 21},
        make_customer_headers(pet["id"])), 200)

    assert changed["cadence_days"] == 21
    assert 21 - equivalent > 3
    assert changed["cadence_prompt_state"] == "OVER_CONSUMPTION", (
        "the chosen cadence now exceeds the equivalent duration by more than 3 days"
    )
    plan_after = read_plan(plan, pet)
    assert isinstance(plan_after["cadence_prompt_due_days_delta"], int)
    assert plan_after["cadence_prompt_due_date"] is not None