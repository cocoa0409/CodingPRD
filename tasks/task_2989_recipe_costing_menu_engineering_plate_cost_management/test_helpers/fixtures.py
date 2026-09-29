"""Composite setup helpers.

Every helper is a *phase*: it reads the version it needs immediately before the
write that consumes it, so two helpers can be chained in any order without the
second one tripping over a version the first one bumped.  Nothing here asserts
business outcomes — setup failures surface as setup failures, and the assertions
live in the tests.

The recurring worlds:

* ``grill_world_*`` — cheddar priced in MW, the PLATE-GRILL plated recipe with a
  single 400-gram cheddar component, and optionally the MI-GRILL-MW menu item.
  Each function stops at a different point of the lifecycle.
* ``cheese_stack_*`` — the two-level graph: the SUB-CHEESE sub-recipe under a
  plated parent, used wherever depth, transitivity or child freshness matter.
"""

from typing import Any, Dict, List, Optional

from prd_bench_local_runner.testing import get_success_data

from . import factories as f
from .api_client import ApiClient
from .constants import CLOCK_EPOCH
from .test_users import (
    APPROVER_USER_ID,
    COST_ANALYST,
    CULINARY_DIRECTOR,
    PLATFORM_ADMIN,
    RECIPE_DEVELOPER,
    SUBMITTER_USER_ID,
    make_culinary_director_headers,
    make_recipe_developer_headers,
    make_unit_manager_headers,
)
from .types import (
    CostBasis,
    LtoDecision,
    PropagationTarget,
    RegionCode,
)

# ─── Tier 1: single-entity creation ───────────────────


def set_clock(api: ApiClient, to_iso8601: str) -> Dict[str, Any]:
    """Move the logical clock forwards to the given instant."""
    return get_success_data(
        api.set_clock(f.clock_payload(to_iso8601), PLATFORM_ADMIN)
    )


def create_unit(api: ApiClient, **overrides: Any) -> Dict[str, Any]:
    return get_success_data(api.create_unit(f.unit_payload(**overrides), PLATFORM_ADMIN))


def create_ingredient(api: ApiClient, **overrides: Any) -> Dict[str, Any]:
    return get_success_data(
        api.create_ingredient(f.ingredient_payload(**overrides), RECIPE_DEVELOPER)
    )


def create_cheddar(api: ApiClient, **overrides: Any) -> Dict[str, Any]:
    return get_success_data(
        api.create_ingredient(f.cheddar_block_payload(**overrides), RECIPE_DEVELOPER)
    )


def create_peanut_oil(api: ApiClient, **overrides: Any) -> Dict[str, Any]:
    return get_success_data(
        api.create_ingredient(f.peanut_oil_payload(**overrides), RECIPE_DEVELOPER)
    )


def retire_ingredient(api: ApiClient, ingredient_id: str) -> Dict[str, Any]:
    return get_success_data(api.retire_ingredient(ingredient_id, CULINARY_DIRECTOR))


def create_recipe(api: ApiClient, **overrides: Any) -> Dict[str, Any]:
    return get_success_data(
        api.create_recipe(f.recipe_payload(**overrides), RECIPE_DEVELOPER)
    )


def create_sub_recipe(api: ApiClient, **overrides: Any) -> Dict[str, Any]:
    return get_success_data(
        api.create_recipe(f.sub_recipe_payload(**overrides), RECIPE_DEVELOPER)
    )


# ─── Tier 1: price feeds ──────────────────────────────


def open_price_feed(api: ApiClient, **overrides: Any) -> Dict[str, Any]:
    return get_success_data(
        api.create_price_feed(f.price_feed_payload(**overrides), COST_ANALYST)
    )


def add_price_line(
    api: ApiClient, price_feed_id: str, ingredient_id: str, **overrides: Any
) -> Dict[str, Any]:
    return get_success_data(
        api.add_price_feed_line(
            price_feed_id, f.price_line_payload(ingredient_id, **overrides), COST_ANALYST
        )
    )


def publish_price_feed(api: ApiClient, price_feed_id: str) -> Dict[str, Any]:
    return get_success_data(api.publish_price_feed(price_feed_id, COST_ANALYST))


def publish_price(
    api: ApiClient,
    ingredient_id: str,
    pack_cost_micros: int,
    effective_from: str = "2026-07-01T00:00:00.000Z",
    effective_to: Optional[str] = None,
    region_code: str = RegionCode.MW,
    feed_date: Optional[str] = None,
    **feed_overrides: Any,
) -> Dict[str, Any]:
    """Open a feed, add one line for the ingredient and publish it.

    Returns the published feed so its cascade counters can be inspected.
    """
    feed = open_price_feed(
        api,
        region_code=region_code,
        feed_date=feed_date or effective_from,
        **feed_overrides,
    )
    line_extras: Dict[str, Any] = {}
    if effective_to is not None:
        line_extras["effective_to"] = effective_to
    add_price_line(
        api,
        feed["id"],
        ingredient_id,
        pack_cost_micros=pack_cost_micros,
        effective_from=effective_from,
        **line_extras,
    )
    return publish_price_feed(api, feed["id"])


def stage_price_feed(
    api: ApiClient,
    ingredient_id: str,
    pack_cost_micros: int,
    effective_from: str,
    effective_to: Optional[str] = None,
    region_code: str = RegionCode.MW,
    feed_date: Optional[str] = None,
    **feed_overrides: Any,
) -> Dict[str, Any]:
    """Open a feed and add one line, but leave it DRAFT for the test to publish."""
    feed = open_price_feed(
        api,
        region_code=region_code,
        feed_date=feed_date or effective_from,
        **feed_overrides,
    )
    line_extras: Dict[str, Any] = {}
    if effective_to is not None:
        line_extras["effective_to"] = effective_to
    add_price_line(
        api,
        feed["id"],
        ingredient_id,
        pack_cost_micros=pack_cost_micros,
        effective_from=effective_from,
        **line_extras,
    )
    return feed


# ─── Tier 2: recipe composition ───────────────────────


def recipe_version(api: ApiClient, recipe_id: str) -> int:
    """Read the recipe's current version, for the guard on the next write."""
    return get_success_data(api.get_recipe(recipe_id, COST_ANALYST))["version"]


def menu_item_version(api: ApiClient, menu_item_id: str) -> int:
    return get_success_data(api.get_menu_item(menu_item_id, COST_ANALYST))["version"]


def add_ingredient_component(
    api: ApiClient,
    recipe_id: str,
    ingredient_id: str,
    ep_quantity_base_units: int = 400,
    sequence_no: int = 1,
    headers: Optional[Dict[str, str]] = None,
    **overrides: Any,
) -> Dict[str, Any]:
    """Add an ingredient component, reading the guard version first."""
    payload = f.ingredient_component_payload(
        ingredient_id,
        recipe_version(api, recipe_id),
        ep_quantity_base_units=ep_quantity_base_units,
        sequence_no=sequence_no,
        **overrides,
    )
    return get_success_data(
        api.add_recipe_component(recipe_id, payload, headers or RECIPE_DEVELOPER)
    )


def add_sub_recipe_component(
    api: ApiClient,
    recipe_id: str,
    child_recipe_id: str,
    ep_quantity_base_units: int = 500,
    sequence_no: int = 1,
    headers: Optional[Dict[str, str]] = None,
    **overrides: Any,
) -> Dict[str, Any]:
    payload = f.sub_recipe_component_payload(
        child_recipe_id,
        recipe_version(api, recipe_id),
        ep_quantity_base_units=ep_quantity_base_units,
        sequence_no=sequence_no,
        **overrides,
    )
    return get_success_data(
        api.add_recipe_component(recipe_id, payload, headers or RECIPE_DEVELOPER)
    )


def remove_component(
    api: ApiClient, recipe_id: str, recipe_component_id: str
) -> Dict[str, Any]:
    return get_success_data(
        api.delete_recipe_component(
            recipe_component_id,
            f.component_delete_params(recipe_version(api, recipe_id)),
            RECIPE_DEVELOPER,
        )
    )


def rollup(
    api: ApiClient, recipe_id: str, basis: str = CostBasis.LATEST_PUBLISHED
) -> Dict[str, Any]:
    return get_success_data(
        api.cost_rollup_recipe(recipe_id, f.rollup_payload(basis=basis), COST_ANALYST)
    )


def submit_recipe_review(
    api: ApiClient, recipe_id: str, user_id: Optional[str] = None
) -> Dict[str, Any]:
    headers = (
        make_recipe_developer_headers(user_id) if user_id else RECIPE_DEVELOPER
    )
    return get_success_data(api.submit_recipe_review(recipe_id, headers))


def activate_recipe(
    api: ApiClient, recipe_id: str, user_id: Optional[str] = None
) -> Dict[str, Any]:
    headers = (
        make_culinary_director_headers(user_id) if user_id else CULINARY_DIRECTOR
    )
    return get_success_data(api.activate_recipe(recipe_id, headers))


def review_and_activate_recipe(api: ApiClient, recipe_id: str) -> Dict[str, Any]:
    """Walk DRAFT -> UNDER_REVIEW -> ACTIVE in two phases."""
    submit_recipe_review(api, recipe_id)
    return activate_recipe(api, recipe_id)


def retire_recipe(api: ApiClient, recipe_id: str) -> Dict[str, Any]:
    return get_success_data(api.retire_recipe(recipe_id, CULINARY_DIRECTOR))


def sole_prep_guide(api: ApiClient, recipe_id: str) -> Dict[str, Any]:
    rows = api.list_prep_guides(recipe_id, None, COST_ANALYST).json()["data"]
    assert len(rows) == 1, f"expected one prep guide, found {len(rows)}"
    return rows[0]


def prep_guide_rows(api: ApiClient, recipe_id: str) -> List[Dict[str, Any]]:
    return api.list_prep_guides(recipe_id, None, COST_ANALYST).json()["data"]


# ─── Tier 2: menu items ───────────────────────────────


def create_menu_item(
    api: ApiClient, recipe_id: str, **overrides: Any
) -> Dict[str, Any]:
    return get_success_data(
        api.create_menu_item(f.menu_item_payload(recipe_id, **overrides), RECIPE_DEVELOPER)
    )


def plate_cost(api: ApiClient, menu_item_id: str) -> Dict[str, Any]:
    return get_success_data(api.plate_cost_menu_item(menu_item_id, COST_ANALYST))


def activate_menu_item(api: ApiClient, menu_item_id: str) -> Dict[str, Any]:
    return get_success_data(api.activate_menu_item(menu_item_id, CULINARY_DIRECTOR))


# ─── Tier 3: the GRILL WORLD lifecycle shortcuts ──────

CHEDDAR_MW_PACK_COST_MICROS = 22_000_000
CHEDDAR_MW_EFFECTIVE_FROM = "2026-07-01T00:00:00.000Z"


def grill_world_priced(api: ApiClient, **ingredient_overrides: Any) -> Dict[str, Any]:
    """Cheddar in the catalogue with one published MW price row."""
    cheddar = create_cheddar(api, **ingredient_overrides)
    feed = publish_price(
        api,
        cheddar["id"],
        CHEDDAR_MW_PACK_COST_MICROS,
        effective_from=CHEDDAR_MW_EFFECTIVE_FROM,
    )
    return {"cheddar": cheddar, "feed": feed}


def grill_world_draft(
    api: ApiClient,
    ep_quantity_base_units: int = 400,
    **recipe_overrides: Any,
) -> Dict[str, Any]:
    """Priced cheddar plus a DRAFT PLATE-GRILL carrying one cheddar component."""
    world = grill_world_priced(api)
    recipe = create_recipe(api, **recipe_overrides)
    component = add_ingredient_component(
        api,
        recipe["id"],
        world["cheddar"]["id"],
        ep_quantity_base_units=ep_quantity_base_units,
    )
    world.update({"recipe": recipe, "component": component})
    return world


def grill_world_costed(
    api: ApiClient,
    ep_quantity_base_units: int = 400,
    basis: str = CostBasis.LATEST_PUBLISHED,
    **recipe_overrides: Any,
) -> Dict[str, Any]:
    """The DRAFT recipe rolled up once, so its cost is FRESH at 3880071 micros."""
    world = grill_world_draft(
        api, ep_quantity_base_units=ep_quantity_base_units, **recipe_overrides
    )
    world["recipe"] = rollup(api, world["recipe"]["id"], basis=basis)
    return world


def grill_world_under_review(
    api: ApiClient, ep_quantity_base_units: int = 400, **recipe_overrides: Any
) -> Dict[str, Any]:
    world = grill_world_costed(
        api, ep_quantity_base_units=ep_quantity_base_units, **recipe_overrides
    )
    world["recipe"] = submit_recipe_review(api, world["recipe"]["id"])
    return world


def grill_world_active_recipe(
    api: ApiClient, ep_quantity_base_units: int = 400, **recipe_overrides: Any
) -> Dict[str, Any]:
    """The recipe ACTIVE with its first prep guide minted."""
    world = grill_world_under_review(
        api, ep_quantity_base_units=ep_quantity_base_units, **recipe_overrides
    )
    world["recipe"] = activate_recipe(api, world["recipe"]["id"])
    return world


def grill_world_draft_item(
    api: ApiClient,
    ep_quantity_base_units: int = 400,
    plate_costed: bool = True,
    recipe_overrides: Optional[Dict[str, Any]] = None,
    **item_overrides: Any,
) -> Dict[str, Any]:
    """The ACTIVE recipe plus a DRAFT MI-GRILL-MW, optionally plate-costed."""
    world = grill_world_active_recipe(
        api,
        ep_quantity_base_units=ep_quantity_base_units,
        **(recipe_overrides or {}),
    )
    item = create_menu_item(api, world["recipe"]["id"], **item_overrides)
    if plate_costed:
        item = plate_cost(api, item["id"])
    world["menu_item"] = item
    return world


def grill_world_active_item(
    api: ApiClient,
    ep_quantity_base_units: int = 400,
    recipe_overrides: Optional[Dict[str, Any]] = None,
    **item_overrides: Any,
) -> Dict[str, Any]:
    """The whole chain: ACTIVE recipe, plate-costed and ACTIVE menu item."""
    world = grill_world_draft_item(
        api,
        ep_quantity_base_units=ep_quantity_base_units,
        plate_costed=True,
        recipe_overrides=recipe_overrides,
        **item_overrides,
    )
    world["menu_item"] = activate_menu_item(api, world["menu_item"]["id"])
    return world


def add_menu_item_to_world(
    api: ApiClient, world: Dict[str, Any], activate: bool = True, **item_overrides: Any
) -> Dict[str, Any]:
    """Hang a second menu item off the world's recipe and cost it."""
    item = create_menu_item(api, world["recipe"]["id"], **item_overrides)
    item = plate_cost(api, item["id"])
    if activate:
        item = activate_menu_item(api, item["id"])
    return item


def restale_and_repair(api: ApiClient, world: Dict[str, Any]) -> Dict[str, Any]:
    """Re-roll the recipe and re-cost the item after a price change."""
    world["recipe"] = rollup(api, world["recipe"]["id"])
    if "menu_item" in world:
        world["menu_item"] = plate_cost(api, world["menu_item"]["id"])
    return world


# ─── Tier 3: the two-level cheese stack ───────────────


def cheese_stack_costed(
    api: ApiClient,
    child_ep: int = 500,
    parent_ep: int = 500,
    parent_overrides: Optional[Dict[str, Any]] = None,
    child_overrides: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """SUB-CHEESE under a plated parent, both rolled up under LATEST_PUBLISHED."""
    priced = grill_world_priced(api)
    child = create_sub_recipe(api, **(child_overrides or {}))
    add_ingredient_component(
        api, child["id"], priced["cheddar"]["id"], ep_quantity_base_units=child_ep
    )
    child = rollup(api, child["id"])

    parent_defaults = {
        "code": "PLATE-CHEESE",
        "name": "Cheese Plate",
        "batch_yield_base_units": 5,
        "portions_per_batch": 5,
    }
    parent_defaults.update(parent_overrides or {})
    parent = create_recipe(api, **parent_defaults)
    parent_component = add_sub_recipe_component(
        api, parent["id"], child["id"], ep_quantity_base_units=parent_ep
    )
    parent = rollup(api, parent["id"])
    return {
        "cheddar": priced["cheddar"],
        "feed": priced["feed"],
        "child": child,
        "parent": parent,
        "parent_component": parent_component,
    }


def cheese_stack_active(
    api: ApiClient,
    child_ep: int = 500,
    parent_ep: int = 500,
    parent_overrides: Optional[Dict[str, Any]] = None,
    child_overrides: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """Both levels of the stack ACTIVE — the child first, as the parent requires."""
    stack = cheese_stack_costed(
        api,
        child_ep=child_ep,
        parent_ep=parent_ep,
        parent_overrides=parent_overrides,
        child_overrides=child_overrides,
    )
    stack["child"] = review_and_activate_recipe(api, stack["child"]["id"])
    stack["parent"] = review_and_activate_recipe(api, stack["parent"]["id"])
    return stack


# ─── Tier 4: period reviews, mix and counts ───────────


def open_review(api: ApiClient, unit_id: str, **overrides: Any) -> Dict[str, Any]:
    return get_success_data(
        api.create_period_review(f.period_review_payload(unit_id, **overrides), COST_ANALYST)
    )


def load_mix_line(
    api: ApiClient, period_review_id: str, menu_item_id: str, **overrides: Any
) -> Dict[str, Any]:
    return get_success_data(
        api.add_mix_line(
            period_review_id, f.mix_line_payload(menu_item_id, **overrides), COST_ANALYST
        )
    )


def record_count_line(
    api: ApiClient,
    period_review_id: str,
    ingredient_id: str,
    unit_id: Optional[str] = None,
    **overrides: Any,
) -> Dict[str, Any]:
    """Record a count line, as the store's own manager when a unit id is given."""
    headers = make_unit_manager_headers(unit_id) if unit_id else COST_ANALYST
    return get_success_data(
        api.add_count_line(
            period_review_id, f.count_line_payload(ingredient_id, **overrides), headers
        )
    )


def classify_review(api: ApiClient, period_review_id: str) -> Dict[str, Any]:
    return get_success_data(api.classify_period_review(period_review_id, COST_ANALYST))


def close_review(api: ApiClient, period_review_id: str) -> Dict[str, Any]:
    return get_success_data(api.close_period_review(period_review_id, COST_ANALYST))


def closed_review_with_one_item(
    api: ApiClient,
    menu_item_id: str,
    ingredient_id: str,
    unit_id: Optional[str] = None,
    review_overrides: Optional[Dict[str, Any]] = None,
    mix_overrides: Optional[Dict[str, Any]] = None,
    count_overrides: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """Walk one review from OPEN to CLOSED in five separate phases."""
    unit = None
    if unit_id is None:
        unit = create_unit(api)
        unit_id = unit["id"]
    review = open_review(api, unit_id, **(review_overrides or {}))
    mix_line = load_mix_line(
        api, review["id"], menu_item_id, **(mix_overrides or {})
    )
    count_line = record_count_line(
        api, review["id"], ingredient_id, **(count_overrides or {})
    )
    review = classify_review(api, review["id"])
    review = close_review(api, review["id"])
    return {
        "unit_id": unit_id,
        "unit": unit,
        "review": review,
        "mix_line": mix_line,
        "count_line": count_line,
    }


def count_line_rows(api: ApiClient, period_review_id: str) -> List[Dict[str, Any]]:
    return api.list_count_lines(period_review_id, None, COST_ANALYST).json()["data"]


def mix_line_rows(api: ApiClient, period_review_id: str) -> List[Dict[str, Any]]:
    return api.list_mix_lines(period_review_id, None, COST_ANALYST).json()["data"]


# ─── Tier 4: price change proposals ───────────────────


def open_proposal(api: ApiClient, menu_item_id: str, **overrides: Any) -> Dict[str, Any]:
    return get_success_data(
        api.create_proposal(f.proposal_payload(menu_item_id, **overrides), RECIPE_DEVELOPER)
    )


def submit_proposal(
    api: ApiClient, proposal_id: str, user_id: str = SUBMITTER_USER_ID
) -> Dict[str, Any]:
    return get_success_data(
        api.submit_proposal(proposal_id, make_recipe_developer_headers(user_id))
    )


def request_revision(
    api: ApiClient,
    proposal_id: str,
    reason: str = "trim the increase",
    user_id: str = APPROVER_USER_ID,
) -> Dict[str, Any]:
    return get_success_data(
        api.request_proposal_revision(
            proposal_id,
            f.revision_payload(reason),
            make_culinary_director_headers(user_id),
        )
    )


def approve_proposal(
    api: ApiClient, proposal_id: str, user_id: str = APPROVER_USER_ID
) -> Dict[str, Any]:
    return get_success_data(
        api.approve_proposal(proposal_id, make_culinary_director_headers(user_id))
    )


def apply_proposal(api: ApiClient, proposal_id: str) -> Dict[str, Any]:
    return get_success_data(api.apply_proposal(proposal_id, COST_ANALYST))


def submitted_proposal(
    api: ApiClient, menu_item_id: str, **overrides: Any
) -> Dict[str, Any]:
    """Open a proposal and submit it, as two phases by two distinct operators."""
    proposal = open_proposal(api, menu_item_id, **overrides)
    return submit_proposal(api, proposal["id"])


def approved_proposal(
    api: ApiClient, menu_item_id: str, **overrides: Any
) -> Dict[str, Any]:
    proposal = submitted_proposal(api, menu_item_id, **overrides)
    return approve_proposal(api, proposal["id"])


# ─── Tier 5: specification change orders ──────────────


def open_qty_change(
    api: ApiClient,
    recipe_id: str,
    target_component_id: str,
    new_ep_quantity_base_units: int = 600,
    user_id: str = SUBMITTER_USER_ID,
    **overrides: Any,
) -> Dict[str, Any]:
    payload = f.component_qty_change_payload(
        recipe_id,
        target_component_id,
        recipe_version(api, recipe_id),
        new_ep_quantity_base_units=new_ep_quantity_base_units,
        **overrides,
    )
    return get_success_data(
        api.create_spec_change_order(payload, make_recipe_developer_headers(user_id))
    )


def submit_change_order(
    api: ApiClient, spec_change_order_id: str, user_id: str = SUBMITTER_USER_ID
) -> Dict[str, Any]:
    return get_success_data(
        api.submit_spec_change_order(
            spec_change_order_id, make_recipe_developer_headers(user_id)
        )
    )


def approve_change_order(
    api: ApiClient, spec_change_order_id: str, user_id: str = APPROVER_USER_ID
) -> Dict[str, Any]:
    return get_success_data(
        api.approve_spec_change_order(
            spec_change_order_id, make_culinary_director_headers(user_id)
        )
    )


def reject_change_order(
    api: ApiClient, spec_change_order_id: str, user_id: str = APPROVER_USER_ID
) -> Dict[str, Any]:
    return get_success_data(
        api.reject_spec_change_order(
            spec_change_order_id, make_culinary_director_headers(user_id)
        )
    )


def propagate_change_order(
    api: ApiClient,
    spec_change_order_id: str,
    target: str = PropagationTarget.PREP_GUIDE,
) -> Dict[str, Any]:
    return get_success_data(
        api.propagate_spec_change_order(
            spec_change_order_id, f.propagate_payload(target), COST_ANALYST
        )
    )


def rollback_change_order(
    api: ApiClient, spec_change_order_id: str, user_id: str = APPROVER_USER_ID
) -> Dict[str, Any]:
    return get_success_data(
        api.rollback_spec_change_order(
            spec_change_order_id, make_culinary_director_headers(user_id)
        )
    )


def approved_qty_change(
    api: ApiClient,
    recipe_id: str,
    target_component_id: str,
    new_ep_quantity_base_units: int = 600,
) -> Dict[str, Any]:
    """Open, submit and approve one quantity change, in three phases."""
    order = open_qty_change(
        api,
        recipe_id,
        target_component_id,
        new_ep_quantity_base_units=new_ep_quantity_base_units,
    )
    submit_change_order(api, order["id"])
    return approve_change_order(api, order["id"])


# ─── Tier 5: limited-time offer campaigns ─────────────


def plan_lto(api: ApiClient, menu_item_id: str, **overrides: Any) -> Dict[str, Any]:
    """Plan a campaign, reading the menu item's version for the guard first."""
    payload = f.lto_campaign_payload(
        menu_item_id, menu_item_version(api, menu_item_id), **overrides
    )
    return get_success_data(api.create_lto_campaign(payload, RECIPE_DEVELOPER))


def cost_lto(api: ApiClient, lto_campaign_id: str) -> Dict[str, Any]:
    return get_success_data(api.cost_lto_campaign(lto_campaign_id, COST_ANALYST))


def launch_lto(api: ApiClient, lto_campaign_id: str) -> Dict[str, Any]:
    return get_success_data(api.launch_lto_campaign(lto_campaign_id, CULINARY_DIRECTOR))


def close_lto_review(
    api: ApiClient,
    lto_campaign_id: str,
    actual_units: int,
    actual_gross_sales_cents: int,
) -> Dict[str, Any]:
    return get_success_data(
        api.close_review_lto_campaign(
            lto_campaign_id,
            f.close_review_payload(actual_units, actual_gross_sales_cents),
            COST_ANALYST,
        )
    )


def decide_lto(
    api: ApiClient, lto_campaign_id: str, decision: str = LtoDecision.RENEW
) -> Dict[str, Any]:
    return get_success_data(
        api.decide_lto_campaign(
            lto_campaign_id, f.decide_payload(decision), CULINARY_DIRECTOR
        )
    )


def costed_lto(api: ApiClient, menu_item_id: str, **overrides: Any) -> Dict[str, Any]:
    campaign = plan_lto(api, menu_item_id, **overrides)
    return cost_lto(api, campaign["id"])


def launched_lto(api: ApiClient, menu_item_id: str, **overrides: Any) -> Dict[str, Any]:
    campaign = costed_lto(api, menu_item_id, **overrides)
    return launch_lto(api, campaign["id"])


EPOCH = CLOCK_EPOCH
