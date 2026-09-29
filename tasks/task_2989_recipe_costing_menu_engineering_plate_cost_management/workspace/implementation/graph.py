"""Recipe graph walks, price selection, cost roll-up, allergen/nutrition
roll-up and the count-sheet explosion (PRD 3.2, 3.3, 3.8)."""
from core import (
    DAY, REFERENCE_REGION_CODE, WEIGHTED_AVG_WINDOW_DAYS, ceil_div, db,
    floor_div, order_key, rhu, touch,
)
from errors import fail


# ---------------------------------------------------------------------------
# Component access
# ---------------------------------------------------------------------------
def components_of(recipe_id):
    rows = [c for c in db.recipe_components.values() if c["recipe_id"] == recipe_id]
    return sorted(rows, key=lambda c: (c["sequence_no"], c["created_at"], c["_seq"]))


def active_components(recipe_id):
    return [c for c in components_of(recipe_id) if c["status"] == "ACTIVE"]


def active_component_count(recipe_id):
    return len(active_components(recipe_id))


def child_ids(recipe_id):
    return [c["child_recipe_id"] for c in active_components(recipe_id)
            if c["component_type"] == "SUB_RECIPE"]


def reaches(source_id, target_id):
    """True when target_id is reachable from source_id through ACTIVE sub-recipe
    components (source itself counts)."""
    seen = set()
    stack = [source_id]
    while stack:
        current = stack.pop()
        if current == target_id:
            return True
        if current in seen:
            continue
        seen.add(current)
        stack.extend(child_ids(current))
    return False


def parents_of(recipe_id):
    """Recipes holding an ACTIVE SUB_RECIPE component pointing at recipe_id."""
    out = set()
    for component in db.recipe_components.values():
        if (component["status"] == "ACTIVE"
                and component["component_type"] == "SUB_RECIPE"
                and component["child_recipe_id"] == recipe_id):
            out.add(component["recipe_id"])
    return out


def depth_of(recipe_id, seen=None):
    children = child_ids(recipe_id)
    if not children:
        return 0
    best = 0
    for child in children:
        if child not in db.recipes:
            continue
        best = max(best, depth_of(child))
    return 1 + best


def prep_guide_of(recipe_id):
    for guide in db.prep_guides.values():
        if guide["recipe_id"] == recipe_id:
            return guide
    return None


def menu_items_of(recipe_id):
    rows = [m for m in db.menu_items.values() if m["recipe_id"] == recipe_id]
    return sorted(rows, key=order_key)


# ---------------------------------------------------------------------------
# Price selection (PRD 3.2)
# ---------------------------------------------------------------------------
def _published_rows(ingredient_id):
    return [p for p in db.ingredient_prices.values()
            if p["status"] == "PUBLISHED"
            and p["ingredient_id"] == ingredient_id
            and p["region_code"] == REFERENCE_REGION_CODE]


def latest_published(ingredient_id):
    now = db.now()
    candidates = []
    for row in _published_rows(ingredient_id):
        if row["effective_from"] > now:
            continue
        if row["effective_to"] is not None and not now < row["effective_to"]:
            continue
        candidates.append(row)
    if not candidates:
        return None
    candidates.sort(key=lambda r: (r["created_at"], r["_seq"]))
    candidates.sort(key=lambda r: r["effective_from"], reverse=True)
    winner = candidates[0]
    return winner["pack_cost_micros"], winner["pack_base_units_snapshot"]


def weighted_avg_90d(ingredient_id):
    now = db.now()
    window_start = now - WEIGHTED_AVG_WINDOW_DAYS * DAY
    weight_total = 0
    weighted_sum = 0
    for row in _published_rows(ingredient_id):
        start = row["effective_from"]
        if start < window_start:
            start = window_start
        end = row["effective_to"]
        if end is None or end > now:
            end = now
        if end <= start:
            continue
        weight = int((end - start).total_seconds()) // 86400
        if weight <= 0:
            continue
        per_base_unit = rhu(row["pack_cost_micros"] * 1000000,
                            row["pack_base_units_snapshot"])
        weighted_sum += weight * per_base_unit
        weight_total += weight
    if weight_total == 0:
        return latest_published(ingredient_id)
    return rhu(weighted_sum, weight_total), 1000000


def select_unit_cost(ingredient_id, basis):
    if basis == "WEIGHTED_AVG_90D":
        return weighted_avg_90d(ingredient_id)
    return latest_published(ingredient_id)


# ---------------------------------------------------------------------------
# Derived quantities
# ---------------------------------------------------------------------------
def ap_from_ep(ep_quantity, net_yield_bps):
    return ceil_div(ep_quantity * 10000, net_yield_bps)


def net_yield(trim_yield_bps, cook_shrink_bps):
    value = floor_div(trim_yield_bps * (10000 - cook_shrink_bps), 10000)
    return max(1, value)


# ---------------------------------------------------------------------------
# Allergen / nutrition / depth roll-up (PRD 3.3)
# ---------------------------------------------------------------------------
def _batch_nutrition(recipe_id):
    """Returns (allergen_mask, batch_kcal_micros, batch_sodium_mcg)."""
    mask = 0
    kcal = 0
    sodium = 0
    for component in active_components(recipe_id):
        if component["component_type"] == "INGREDIENT":
            ingredient = db.ingredients.get(component["ingredient_id"])
            if ingredient is None:
                continue
            mask |= ingredient["allergen_mask"]
            ap = component["ap_quantity_base_units"]
            kcal += ap * ingredient["kcal_per_base_unit_micros"]
            sodium += ap * ingredient["sodium_mcg_per_base_unit"]
        else:
            child = db.recipes.get(component["child_recipe_id"])
            if child is None:
                continue
            child_mask, child_kcal, child_sodium = _batch_nutrition(child["id"])
            mask |= child_mask
            divisor = child["batch_yield_base_units"]
            ep = component["ep_quantity_base_units"]
            kcal += rhu(ep * child_kcal, divisor)
            sodium += rhu(ep * child_sodium, divisor)
    return mask, kcal, sodium


def nutrition_profile(recipe):
    """The computed read: allergen mask, per-portion figures, depth, count."""
    mask, kcal, sodium = _batch_nutrition(recipe["id"])
    portions = recipe["portions_per_batch"]
    return {
        "allergen_mask": mask,
        "kcal_per_portion_micros": rhu(kcal, portions),
        "sodium_mcg_per_portion": rhu(sodium, portions),
        "depth": depth_of(recipe["id"]),
        "component_count": active_component_count(recipe["id"]),
    }


def apply_profile(recipe, profile=None, keep_allergen=False):
    """Writes the five spec-derived fields onto the recipe row (no version bump)."""
    profile = profile or nutrition_profile(recipe)
    if not keep_allergen:
        recipe["allergen_mask"] = profile["allergen_mask"]
    recipe["kcal_per_portion_micros"] = profile["kcal_per_portion_micros"]
    recipe["sodium_mcg_per_portion"] = profile["sodium_mcg_per_portion"]
    recipe["depth"] = profile["depth"]
    recipe["component_count"] = profile["component_count"]
    return recipe


# ---------------------------------------------------------------------------
# Cost roll-up (PRD 3.2)
# ---------------------------------------------------------------------------
def cost_rollup(recipe, basis):
    components = active_components(recipe["id"])

    # STEP 1 -- children first; never recomputed implicitly.
    for component in components:
        if component["component_type"] != "SUB_RECIPE":
            continue
        child = db.recipes.get(component["child_recipe_id"])
        if child is None or child["cost_state"] != "FRESH" or child["cost_basis"] != basis:
            fail("ERR_COST_STALE",
                 "Sub-recipe component's child recipe is not FRESH on basis %s." % basis)

    # Select every unit cost before writing anything, so a missing price leaves
    # no partial mutation behind.
    selections = {}
    for component in components:
        if component["component_type"] != "INGREDIENT":
            continue
        ingredient_id = component["ingredient_id"]
        if ingredient_id in selections:
            continue
        chosen = select_unit_cost(ingredient_id, basis)
        if chosen is None:
            fail("ERR_NO_PUBLISHED_PRICE",
                 "No published price for ingredient %s in region %s."
                 % (ingredient_id, REFERENCE_REGION_CODE))
        selections[ingredient_id] = chosen

    # STEP 2 -- per component extended cost, rounded individually.
    batch_cost = 0
    for component in components:
        if component["component_type"] == "INGREDIENT":
            ingredient = db.ingredients[component["ingredient_id"]]
            unit_cost, pack_base_units = selections[component["ingredient_id"]]
            ap = ap_from_ep(component["ep_quantity_base_units"],
                            ingredient["net_yield_bps"])
            component["ap_quantity_base_units"] = ap
            component["unit_cost_micros_used"] = unit_cost
            component["pack_base_units_snapshot"] = pack_base_units
            component["extended_cost_micros"] = rhu(ap * unit_cost, pack_base_units)
        else:
            child = db.recipes[component["child_recipe_id"]]
            ep = component["ep_quantity_base_units"]
            component["ap_quantity_base_units"] = ep
            component["unit_cost_micros_used"] = child["batch_cost_micros"]
            component["pack_base_units_snapshot"] = child["batch_yield_base_units"]
            component["extended_cost_micros"] = rhu(
                ep * child["batch_cost_micros"], child["batch_yield_base_units"])
        touch(component)
        batch_cost += component["extended_cost_micros"]

    # STEP 3 -- batch and portion.
    recipe["batch_cost_micros"] = batch_cost
    recipe["portion_cost_micros"] = rhu(batch_cost, recipe["portions_per_batch"])

    # The same call refreshes the allergen / nutrition / depth profile.
    apply_profile(recipe)

    # STEP 4.
    recipe["cost_state"] = "FRESH"
    recipe["cost_basis"] = basis
    recipe["last_rollup_at"] = db.now()
    touch(recipe)
    return recipe


# ---------------------------------------------------------------------------
# Count-sheet explosion (PRD 3.8)
# ---------------------------------------------------------------------------
def ap_per_batch(recipe_id, ingredient_id):
    total = 0
    for component in active_components(recipe_id):
        if component["component_type"] == "INGREDIENT":
            if component["ingredient_id"] == ingredient_id:
                total += component["ap_quantity_base_units"]
        else:
            child = db.recipes.get(component["child_recipe_id"])
            if child is None:
                continue
            child_total = ap_per_batch(child["id"], ingredient_id)
            if child_total:
                total += rhu(component["ep_quantity_base_units"] * child_total,
                             child["batch_yield_base_units"])
    return total


def ap_per_portion_micros(recipe_id, ingredient_id):
    recipe = db.recipes.get(recipe_id)
    if recipe is None:
        return 0
    portions = recipe["portions_per_batch"]
    total = 0
    for component in active_components(recipe_id):
        if component["component_type"] == "INGREDIENT":
            if component["ingredient_id"] == ingredient_id:
                total += rhu(component["ap_quantity_base_units"] * 1000000, portions)
        else:
            child = db.recipes.get(component["child_recipe_id"])
            if child is None:
                continue
            child_total = ap_per_batch(child["id"], ingredient_id)
            if child_total:
                total += rhu(
                    component["ep_quantity_base_units"] * child_total * 1000000,
                    child["batch_yield_base_units"] * portions)
    return total


def mix_lines_of(review_id):
    rows = [m for m in db.mix_lines.values() if m["period_review_id"] == review_id]
    return sorted(rows, key=order_key)


def count_lines_of(review_id):
    rows = [c for c in db.count_lines.values() if c["period_review_id"] == review_id]
    return sorted(rows, key=order_key)


def expected_base_units(review_id, ingredient_id):
    accumulated = 0
    for line in mix_lines_of(review_id):
        item = db.menu_items.get(line["menu_item_id"])
        if item is None:
            continue
        per_portion = ap_per_portion_micros(item["recipe_id"], ingredient_id)
        if per_portion:
            accumulated += line["units_sold"] * per_portion
    return floor_div(accumulated, 1000000)


def consuming_recipe_ids(review_id, ingredient_id):
    """Recipes reachable from the review's mix lines that consume the ingredient."""
    out = []
    for line in mix_lines_of(review_id):
        item = db.menu_items.get(line["menu_item_id"])
        if item is None:
            continue
        for recipe_id in _closure(item["recipe_id"]):
            if recipe_id in out:
                continue
            if _consumes_directly(recipe_id, ingredient_id):
                out.append(recipe_id)
    return out


def _closure(recipe_id):
    ordered = []
    stack = [recipe_id]
    seen = set()
    while stack:
        current = stack.pop(0)
        if current in seen or current not in db.recipes:
            continue
        seen.add(current)
        ordered.append(current)
        stack.extend(child_ids(current))
    return ordered


def _consumes_directly(recipe_id, ingredient_id):
    for component in active_components(recipe_id):
        if (component["component_type"] == "INGREDIENT"
                and component["ingredient_id"] == ingredient_id):
            return True
    return False


def valued_usage(used_base_units, ingredient_id):
    """Count lines are always valued at LATEST_PUBLISHED prices (PRD 3.8)."""
    chosen = latest_published(ingredient_id)
    if chosen is None:
        return 0
    unit_cost, pack_base_units = chosen
    return rhu(used_base_units * unit_cost, pack_base_units)
