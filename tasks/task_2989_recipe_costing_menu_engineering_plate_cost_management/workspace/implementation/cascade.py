"""Invalidation cascades (PRD 2.6, 3.2, 3.3, 3.6, 3.9).

Invalidation always happens in the request that causes it, propagates upward
through the recipe graph, and stops at nodes that were already STALE.
"""
from core import db, touch
from graph import active_components, menu_items_of, parents_of, prep_guide_of


def flip_recipe_stale(recipe):
    if recipe["cost_state"] != "FRESH":
        return False
    recipe["cost_state"] = "STALE"
    touch(recipe)
    return True


def propagate_upward(seed_recipe_ids):
    """Flips FRESH ancestors of the given (already stale) recipes.

    Returns the ancestors that actually changed, in discovery order.
    """
    flipped = []
    queue = list(seed_recipe_ids)
    while queue:
        current = queue.pop(0)
        for parent_id in sorted(parents_of(current)):
            parent = db.recipes.get(parent_id)
            if parent is None:
                continue
            if flip_recipe_stale(parent):
                flipped.append(parent_id)
                queue.append(parent_id)
    return flipped


def revert_costed_campaigns(menu_item_id):
    """The COSTED -> PLANNED reverse edge (PRD 3.9)."""
    reverted = 0
    for campaign in db.lto_campaigns.values():
        if campaign["menu_item_id"] != menu_item_id or campaign["status"] != "COSTED":
            continue
        campaign["status"] = "PLANNED"
        campaign["promo_plate_cost_cents"] = 0
        campaign["promo_food_cost_bps"] = 0
        campaign["forecast_contribution_cents"] = 0
        touch(campaign)
        reverted += 1
    return reverted


def stale_menu_item(item, source_recipe=None):
    """Flips one menu item's plate cost stale. Returns True when it changed.

    When source_recipe is given the item also re-copies that recipe's allergen
    mask and sodium figure, which is what a specification change order does to
    the menu items of the recipe it changed.
    """
    was_fresh = item["plate_cost_state"] == "FRESH"
    if source_recipe is None and not was_fresh:
        return False
    if source_recipe is not None:
        item["allergen_mask"] = source_recipe["allergen_mask"]
        item["sodium_mcg_per_portion"] = source_recipe["sodium_mcg_per_portion"]
    item["plate_cost_state"] = "STALE"
    item["margin_class"] = "UNCLASSIFIED"
    touch(item)
    revert_costed_campaigns(item["id"])
    return was_fresh


def stale_menu_items_of(recipe_ids, source_recipe=None):
    """Returns the number of menu items whose plate_cost_state flipped."""
    flipped = 0
    for recipe_id in recipe_ids:
        source = source_recipe if (source_recipe is not None
                                   and source_recipe["id"] == recipe_id) else None
        for item in menu_items_of(recipe_id):
            if stale_menu_item(item, source):
                flipped += 1
    return flipped


def mark_prep_guide_out_of_date(recipe_id):
    guide = prep_guide_of(recipe_id)
    if guide is None:
        return False
    guide["sync_state"] = "OUT_OF_DATE"
    touch(guide)
    return True


def _ingredients_consumed_by(recipe_id):
    return set(component["ingredient_id"]
               for component in active_components(recipe_id)
               if component["component_type"] == "INGREDIENT")


def mark_count_lines_out_of_date(recipe_id):
    """Count lines of non-CLOSED reviews on an ingredient this recipe consumes."""
    ingredient_ids = _ingredients_consumed_by(recipe_id)
    touched = 0
    for line in db.count_lines.values():
        review = db.period_reviews.get(line["period_review_id"])
        if review is None or review["status"] == "CLOSED":
            continue
        if line["ingredient_id"] not in ingredient_ids:
            continue
        line["sync_state"] = "OUT_OF_DATE"
        touch(line)
        touched += 1
    return touched
