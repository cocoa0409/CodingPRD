"""Payload factories — one per resource, input fields only.

Every money and quantity value is emitted as a JSON number (integer cents for
money), never as a string.
"""

from .constants import TEST_DEFAULTS


# --- BakeryDepartment -------------------------------------------------------

def create_department_payload(**overrides) -> dict:
    payload = {
        "name": TEST_DEFAULTS["DEPARTMENT_NAME"],
        "store_number": TEST_DEFAULTS["STORE_NUMBER"],
        "shrink_budget_pct": TEST_DEFAULTS["SHRINK_BUDGET_PCT"],
        "labor_rate_cents_per_minute": TEST_DEFAULTS["LABOR_RATE_CENTS_PER_MINUTE"],
        "freight_surcharge_pct": TEST_DEFAULTS["FREIGHT_SURCHARGE_PCT"],
    }
    payload.update(overrides)
    return payload


def create_second_department_payload(**overrides) -> dict:
    payload = create_department_payload(
        name=TEST_DEFAULTS["SECOND_DEPARTMENT_NAME"],
        store_number=TEST_DEFAULTS["SECOND_STORE_NUMBER"],
    )
    payload.update(overrides)
    return payload


# --- Ingredient -------------------------------------------------------------

def create_ingredient_payload(department_id, **overrides) -> dict:
    payload = {
        "department_id": department_id,
        "name": "Bread Flour",
        "case_pack_units": 45,
        "unit_cost_cents": 10,
        "shelf_life_days": 30,
        "daily_usage_units": 40,
        "reorder_point_units": 120,
        "on_hand_units": 2000,
        "allergen_tags": ["WHEAT"],
    }
    payload.update(overrides)
    return payload


def create_flour_payload(department_id, on_hand_units=2000, **overrides) -> dict:
    """Bread Flour: 45-unit cases at 10 cents a unit, reorder point 120."""
    return create_ingredient_payload(
        department_id, on_hand_units=on_hand_units, **overrides
    )


def create_sugar_payload(department_id, on_hand_units=500, **overrides) -> dict:
    """Baker Sugar: 30-unit cases at 15 cents a unit, reorder point 60."""
    payload = {
        "department_id": department_id,
        "name": "Baker Sugar",
        "case_pack_units": 30,
        "unit_cost_cents": 15,
        "shelf_life_days": 10,
        "daily_usage_units": 20,
        "reorder_point_units": 60,
        "on_hand_units": on_hand_units,
    }
    payload.update(overrides)
    return payload


# --- Product ----------------------------------------------------------------

def create_product_payload(department_id, **overrides) -> dict:
    """A par-baked croissant: 40 units a rack, 20 bake + 15 cool minutes."""
    payload = {
        "department_id": department_id,
        "sku": "PAR-CROIS",
        "name": "Par-baked Croissant",
        "production_method": "PAR_BAKED",
        "units_per_rack": 40,
        "proof_minutes": 0,
        "bake_minutes": 20,
        "cool_minutes": 15,
        "base_labor_minutes_per_rack": 10,
        "setup_labor_minutes": 15,
        "unit_retail_cents": 150,
        "shelf_life_hours": 10,
        "allergen_tags": ["WHEAT"],
    }
    payload.update(overrides)
    return payload


def create_par_baked_product_payload(department_id, **overrides) -> dict:
    return create_product_payload(department_id, **overrides)


def create_scratch_product_payload(department_id, **overrides) -> dict:
    """A scratch dinner roll: 45 proof + 30 bake + 20 cool minutes."""
    payload = {
        "department_id": department_id,
        "sku": "SCR-ROLL",
        "name": "Scratch Dinner Roll",
        "production_method": "SCRATCH",
        "units_per_rack": 25,
        "proof_minutes": 45,
        "bake_minutes": 30,
        "cool_minutes": 20,
        "base_labor_minutes_per_rack": 12,
        "setup_labor_minutes": 20,
        "unit_retail_cents": 199,
        "shelf_life_hours": 12,
        "allergen_tags": ["WHEAT"],
    }
    payload.update(overrides)
    return payload


def create_scratch_milk_product_payload(department_id, **overrides) -> dict:
    """A second scratch product with a different allergen profile (adds MILK)."""
    payload = {
        "department_id": department_id,
        "sku": "SCR-MILK",
        "name": "Scratch Milk Bread",
        "production_method": "SCRATCH",
        "units_per_rack": 20,
        "proof_minutes": 45,
        "bake_minutes": 30,
        "cool_minutes": 20,
        "base_labor_minutes_per_rack": 12,
        "setup_labor_minutes": 20,
        "unit_retail_cents": 250,
        "shelf_life_hours": 12,
        "allergen_tags": ["WHEAT", "MILK"],
    }
    payload.update(overrides)
    return payload


def create_thaw_filler_product_payload(department_id, **overrides) -> dict:
    """A zero-cost thaw-and-serve filler: one unit a rack, no labor at all."""
    payload = {
        "department_id": department_id,
        "sku": "THAW-FIL",
        "name": "Thaw Filler Danish",
        "production_method": "THAW_AND_SERVE",
        "units_per_rack": 1,
        "proof_minutes": 0,
        "bake_minutes": 0,
        "cool_minutes": 0,
        "base_labor_minutes_per_rack": 0,
        "setup_labor_minutes": 0,
        "unit_retail_cents": 100,
        "shelf_life_hours": 24,
    }
    payload.update(overrides)
    return payload


def create_thaw_box_product_payload(department_id, **overrides) -> dict:
    """A thaw-and-serve muffin box that does carry labor: 12 setup + 8 a rack."""
    payload = {
        "department_id": department_id,
        "sku": "THAW-BOX",
        "name": "Thaw Muffin Box",
        "production_method": "THAW_AND_SERVE",
        "units_per_rack": 6,
        "proof_minutes": 0,
        "bake_minutes": 0,
        "cool_minutes": 0,
        "base_labor_minutes_per_rack": 8,
        "setup_labor_minutes": 12,
        "unit_retail_cents": 200,
        "shelf_life_hours": 24,
    }
    payload.update(overrides)
    return payload


def create_cake_base_product_payload(department_id, **overrides) -> dict:
    """An 8-inch cake round flagged as a custom cake base."""
    payload = {
        "department_id": department_id,
        "sku": "CAKE-8",
        "name": "8 inch Cake Round",
        "production_method": "THAW_AND_SERVE",
        "units_per_rack": 1,
        "proof_minutes": 0,
        "bake_minutes": 0,
        "cool_minutes": 0,
        "base_labor_minutes_per_rack": 0,
        "setup_labor_minutes": 0,
        "unit_retail_cents": 1800,
        "shelf_life_hours": 48,
        "is_custom_cake_base": True,
    }
    payload.update(overrides)
    return payload


def create_nut_free_product_payload(department_id, **overrides) -> dict:
    """A gluten-free loaf merchandised with a nut-free claim."""
    payload = {
        "department_id": department_id,
        "sku": "GF-LOAF",
        "name": "Gluten-Free Loaf",
        "production_method": "PAR_BAKED",
        "units_per_rack": 20,
        "proof_minutes": 0,
        "bake_minutes": 25,
        "cool_minutes": 15,
        "base_labor_minutes_per_rack": 10,
        "setup_labor_minutes": 15,
        "unit_retail_cents": 400,
        "shelf_life_hours": 24,
        "allergen_free_claim": True,
    }
    payload.update(overrides)
    return payload


def create_tree_nut_product_payload(department_id, **overrides) -> dict:
    """A walnut bar carrying TREE_NUT: 10 setup + 10 a rack, par-baked."""
    payload = {
        "department_id": department_id,
        "sku": "NUT-BAR",
        "name": "Walnut Bar",
        "production_method": "PAR_BAKED",
        "units_per_rack": 10,
        "proof_minutes": 0,
        "bake_minutes": 20,
        "cool_minutes": 10,
        "base_labor_minutes_per_rack": 10,
        "setup_labor_minutes": 10,
        "unit_retail_cents": 300,
        "shelf_life_hours": 48,
        "allergen_tags": ["WHEAT", "TREE_NUT"],
    }
    payload.update(overrides)
    return payload


def recipe_line(ingredient_id, units_per_rack) -> dict:
    return {"ingredient_id": ingredient_id, "units_per_rack": units_per_rack}


# --- Oven -------------------------------------------------------------------

def create_oven_payload(department_id, **overrides) -> dict:
    """Deck Oven A: two decks, four racks a deck, 20-minute changeover buffer."""
    payload = {
        "department_id": department_id,
        "name": "Deck Oven A",
        "deck_count": 2,
        "rack_capacity_per_deck": 4,
        "changeover_buffer_minutes": 20,
        "allergen_mode": "SHARED",
    }
    payload.update(overrides)
    return payload


def create_unbuffered_oven_payload(department_id, **overrides) -> dict:
    """Deck Oven B: one deck, four racks, no changeover buffer at all."""
    payload = {
        "department_id": department_id,
        "name": "Deck Oven B",
        "deck_count": 1,
        "rack_capacity_per_deck": 4,
        "changeover_buffer_minutes": 0,
        "allergen_mode": "SHARED",
    }
    payload.update(overrides)
    return payload


def create_nut_free_oven_payload(department_id, **overrides) -> dict:
    """Nut-Free Oven: one deck, dedicated to nut-free production."""
    payload = {
        "department_id": department_id,
        "name": "Nut-Free Oven",
        "deck_count": 1,
        "rack_capacity_per_deck": 4,
        "changeover_buffer_minutes": 0,
        "allergen_mode": "NUT_FREE_DEDICATED",
    }
    payload.update(overrides)
    return payload


# --- BakeDay ----------------------------------------------------------------

def create_bake_day_payload(department_id, **overrides) -> dict:
    """A Wednesday bake day (no day-of-week uplift) with a 16-hour oven shift."""
    payload = {
        "department_id": department_id,
        "business_date": TEST_DEFAULTS["BUSINESS_DATE"],
        "labor_budget_minutes": TEST_DEFAULTS["LABOR_BUDGET_MINUTES"],
        "oven_shift_start_utc": TEST_DEFAULTS["OVEN_SHIFT_START_UTC"],
        "oven_shift_end_utc": TEST_DEFAULTS["OVEN_SHIFT_END_UTC"],
    }
    payload.update(overrides)
    return payload


def forecast_line_payload(product_id, daypart="MORNING", forecasted_units=40, **overrides) -> dict:
    payload = {
        "product_id": product_id,
        "daypart": daypart,
        "forecasted_units": forecasted_units,
    }
    payload.update(overrides)
    return payload


def generate_plan_payload(expected_bake_day_version, **overrides) -> dict:
    payload = {"expected_bake_day_version": expected_bake_day_version}
    payload.update(overrides)
    return payload


def close_bake_day_payload(donate_remaining=None, **overrides) -> dict:
    payload = {}
    if donate_remaining is not None:
        payload["donate_remaining"] = donate_remaining
    payload.update(overrides)
    return payload


# --- ProductionRun ----------------------------------------------------------

def create_production_run_payload(
    bake_day_id,
    product_id,
    rack_count=2,
    oven_id=None,
    deck_index=None,
    proof_start_utc=None,
    bake_start_utc=None,
    **overrides,
) -> dict:
    payload = {
        "bake_day_id": bake_day_id,
        "product_id": product_id,
        "rack_count": rack_count,
    }
    if oven_id is not None:
        payload["oven_id"] = oven_id
    if deck_index is not None:
        payload["deck_index"] = deck_index
    if proof_start_utc is not None:
        payload["proof_start_utc"] = proof_start_utc
    if bake_start_utc is not None:
        payload["bake_start_utc"] = bake_start_utc
    payload.update(overrides)
    return payload


def complete_run_payload(actual_units, actual_labor_minutes=None, **overrides) -> dict:
    payload = {"actual_units": actual_units}
    if actual_labor_minutes is not None:
        payload["actual_labor_minutes"] = actual_labor_minutes
    payload.update(overrides)
    return payload


def oven_status_payload(oven_status, status_reason=None, **overrides) -> dict:
    payload = {"oven_status": oven_status}
    if status_reason is not None:
        payload["status_reason"] = status_reason
    payload.update(overrides)
    return payload


# --- WasteRecord ------------------------------------------------------------

def create_waste_record_payload(
    production_run_id, units, disposition_reason="DAMAGED", **overrides
) -> dict:
    payload = {
        "production_run_id": production_run_id,
        "disposition_reason": disposition_reason,
        "units": units,
    }
    payload.update(overrides)
    return payload


def void_waste_record_payload(void_reason="Mis-attested batch", **overrides) -> dict:
    payload = {"void_reason": void_reason}
    payload.update(overrides)
    return payload


# --- PickupSlot -------------------------------------------------------------

def create_pickup_slot_payload(
    bake_day_id,
    slot_start_utc="2026-08-12T14:00:00Z",
    slot_end_utc="2026-08-12T16:00:00Z",
    decorator_capacity_units=10,
    **overrides,
) -> dict:
    payload = {
        "bake_day_id": bake_day_id,
        "slot_start_utc": slot_start_utc,
        "slot_end_utc": slot_end_utc,
        "decorator_capacity_units": decorator_capacity_units,
    }
    payload.update(overrides)
    return payload


# --- CustomCakeOrder --------------------------------------------------------

def create_cake_order_payload(
    bake_day_id,
    pickup_slot_id,
    product_id,
    customer_name="Ada Lovelace",
    decoration_complexity="STANDARD",
    tier_count=2,
    **overrides,
) -> dict:
    payload = {
        "bake_day_id": bake_day_id,
        "pickup_slot_id": pickup_slot_id,
        "product_id": product_id,
        "customer_name": customer_name,
        "decoration_complexity": decoration_complexity,
        "tier_count": tier_count,
    }
    payload.update(overrides)
    return payload


def cake_revision_payload(decoration_complexity, tier_count=None, **overrides) -> dict:
    payload = {"decoration_complexity": decoration_complexity}
    if tier_count is not None:
        payload["tier_count"] = tier_count
    payload.update(overrides)
    return payload


# --- IngredientOrder --------------------------------------------------------

def ingredient_order_line(ingredient_id, required_units) -> dict:
    return {"ingredient_id": ingredient_id, "required_units": required_units}


def create_ingredient_order_payload(
    department_id, expected_department_version, lines, target_bake_day_id=None, **overrides
) -> dict:
    payload = {
        "department_id": department_id,
        "expected_department_version": expected_department_version,
        "lines": lines,
    }
    if target_bake_day_id is not None:
        payload["target_bake_day_id"] = target_bake_day_id
    payload.update(overrides)
    return payload


def received_line(ingredient_id, received_units) -> dict:
    return {"ingredient_id": ingredient_id, "received_units": received_units}


def receive_ingredient_order_payload(received_lines, **overrides) -> dict:
    payload = {"received_lines": received_lines}
    payload.update(overrides)
    return payload


def cancel_ingredient_order_payload(cancel_reason="Supplier out of stock", **overrides) -> dict:
    payload = {"cancel_reason": cancel_reason}
    payload.update(overrides)
    return payload
