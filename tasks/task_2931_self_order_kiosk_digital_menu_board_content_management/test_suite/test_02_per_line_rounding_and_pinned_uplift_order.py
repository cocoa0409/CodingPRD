"""Per-line discount rounding, and the pinned order in which an uplift is derived."""

import os
import sys
from typing import Any, Dict

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from prd_bench_local_runner.testing import validate_success  # noqa: E402

from test_helpers import factories as f  # noqa: E402
from test_helpers.assertions import (  # noqa: E402
    assert_fields,
    assert_money,
    assert_order_totals,
    assert_priced_line,
    override_for_zone,
)
from test_helpers.constants import (  # noqa: E402
    ACTION_APPLY,
    ACTION_APPROVE,
    ACTION_SUBMIT,
    CAMPAIGN_ACTIVE,
    CATEGORY_ENTREE,
    CATEGORY_SIDE,
    CLOCK_T0,
    DEVICE_CODE_K001,
    DISCOUNT_PERCENT_OFF,
    PCR_APPLIED,
    PCR_DRAFT,
    SKU_BURGER,
    SKU_FRIES,
    STACKING_GROUP_BASE,
    STORE_CODE_S001,
    TENDER_CARD,
    ZONE_A_CODE,
)
from test_helpers.fixtures import World, publish_bundle_with_slot  # noqa: E402
from test_helpers.test_users import (  # noqa: E402
    ADMIN,
    ANALYST,
    APPROVER,
    APPROVER_2,
    CONTENT_MANAGER,
    make_device_agent_headers,
)

WINDOW_START = "2026-08-05T00:00:00Z"
WINDOW_END = "2026-08-31T23:59:59Z"


def _campaign_scenario(api) -> Dict[str, Any]:
    world = World(api)
    world.set_clock(CLOCK_T0)
    zone = world.zone(ZONE_A_CODE)
    cluster = world.cluster("CL_WEST")
    store = world.store(cluster["id"], zone["id"], STORE_CODE_S001)
    burger = world.item(SKU_BURGER, category=CATEGORY_ENTREE, base_price_cents=500)
    fries = world.item(SKU_FRIES, category=CATEGORY_SIDE, base_price_cents=310)
    bundle = publish_bundle_with_slot(world, cluster["id"],
                                     category_codes=[CATEGORY_ENTREE, CATEGORY_SIDE])
    world.availability(store["id"], burger["id"], on_hand_units=40, par_units=20)
    world.availability(store["id"], fries["id"], on_hand_units=40, par_units=12)
    device = world.device(store["id"], DEVICE_CODE_K001)
    world.attest(device["id"])
    world.heartbeat(device["id"])
    device = world.cache_sync(device["id"], bundle["id"])
    campaign = world.campaign("SUMMER15", cluster["id"], WINDOW_START, WINDOW_END,
                             discount_kind=DISCOUNT_PERCENT_OFF, discount_value=1500,
                             stacking_group=STACKING_GROUP_BASE, priority_rank=10)
    campaign = world.schedule_campaign(campaign["id"])
    return {"world": world, "zone": zone, "cluster": cluster, "store": store,
            "burger": burger, "fries": fries, "bundle": bundle, "device": device,
            "campaign": campaign}


def test_each_line_discount_is_rounded_before_the_discounts_are_summed(api):
    """PRD: "`discount_cents` is the sum of the **already-rounded** `line_discount_cents` across those lines — the rounding happens once per line and the sum is taken afterwards, so an implementation that sums the unrounded line discounts and rounds the total once will report a different figure and is wrong."

    Design: Difficulty/combinatorial_formula/per_line_rounded_campaign_discount_mode_b
    """
    scene = _campaign_scenario(api)
    burger, fries, device = scene["burger"], scene["fries"], scene["device"]

    response = api.create_order(
        device["id"],
        f.order_payload([f.line(burger["id"], 4), f.line(fries["id"], 4)],
                        tender_kind=TENDER_CARD),
        make_device_agent_headers(device["id"]),
    )
    order = validate_success(response, 201)

    assert_priced_line(order["priced_lines"][0], burger["id"], 4, 559, 2236, 335)
    assert_priced_line(order["priced_lines"][1], fries["id"], 4, 349, 1396, 209)
    assert_money(order["discount_cents"], 544, "discount_cents")
    assert order["discount_cents"] != 545, (
        "545 is the figure produced by rounding the summed discount once"
    )


def test_the_selected_campaign_drives_the_order_totals(api):
    """PRD: "`tax_cents` is the net amount — `subtotal_cents` minus `discount_cents` — multiplied by the store's price zone `tax_rate_bp` and divided by 10000, rounded half up."

    Design: Difficulty/combinatorial_formula/per_line_rounded_campaign_discount_mode_b
    """
    scene = _campaign_scenario(api)
    burger, fries, device = scene["burger"], scene["fries"], scene["device"]

    assert scene["campaign"]["state"] == CAMPAIGN_ACTIVE, (
        "a scheduled version whose window contains the clock reads ACTIVE"
    )

    response = api.create_order(
        device["id"],
        f.order_payload([f.line(burger["id"], 4), f.line(fries["id"], 4)],
                        tender_kind=TENDER_CARD),
        make_device_agent_headers(device["id"]),
    )
    order = validate_success(response, 201)

    assert order["applied_campaign_version_id"] == scene["campaign"]["id"]
    assert_order_totals(order, subtotal_cents=3632, discount_cents=544,
                        tax_cents=270, total_cents=3358)


def _uplift_scenario(api) -> Dict[str, Any]:
    world = World(api)
    world.set_clock(CLOCK_T0)
    zone = world.zone(ZONE_A_CODE)
    cluster = world.cluster("CL_WEST")
    store = world.store(cluster["id"], zone["id"], STORE_CODE_S001)
    burger = world.item(SKU_BURGER, category=CATEGORY_ENTREE, base_price_cents=500)
    return {"world": world, "zone": zone, "cluster": cluster, "store": store, "burger": burger}


def test_uplift_is_derived_once_from_the_raw_proposal(api):
    """PRD: "Because the uplift is taken from the raw proposal, the psychological rounding that will later be applied at apply time never influences the tier or the cap; deriving the uplift from the rounded price instead would reject proposals that this specification accepts."

    Design: Difficulty/combinatorial_formula/uplift_tier_pinned_evaluation_order_mode_c
    """
    scene = _uplift_scenario(api)
    world, burger, zone = scene["world"], scene["burger"], scene["zone"]

    live_version = world.get_item(burger["id"])["version"]
    response = api.create_price_change_request(
        f.price_change_request_payload(burger["id"], zone["id"], 642, CLOCK_T0, live_version,
                                       justification="Premium bun upgrade"),
        ANALYST,
    )
    request = validate_success(response, 201)

    assert_money(request["baseline_price_cents"], 559, "baseline_price_cents")
    assert_fields(request, uplift_bp=1485, required_approvals=2, state=PCR_DRAFT)


def test_the_apply_time_rounding_never_feeds_back_into_the_uplift(api):
    """PRD: "`applied_price_cents` is set to the raw `proposed_price_cents` after the request's price zone `psychological_rounding` has been applied to it."

    Design: Difficulty/combinatorial_formula/uplift_tier_pinned_evaluation_order_mode_c
    """
    scene = _uplift_scenario(api)
    world, burger, zone = scene["world"], scene["burger"], scene["zone"]

    live_version = world.get_item(burger["id"])["version"]
    request = world.price_change_request(burger["id"], zone["id"], 642, CLOCK_T0, live_version,
                                        ANALYST, justification="Premium bun upgrade")
    world.pcr_action(request["id"], ACTION_SUBMIT, ANALYST)
    world.pcr_action(request["id"], ACTION_APPROVE, APPROVER)
    world.pcr_action(request["id"], ACTION_APPROVE, APPROVER_2)

    applied = validate_success(
        api.price_change_request_action(request["id"], f.action_payload(ACTION_APPLY), ANALYST), 200
    )

    assert_fields(applied, state=PCR_APPLIED, uplift_bp=1485)
    assert_money(applied["applied_price_cents"], 649, "applied_price_cents")

    item = validate_success(api.get_menu_item(burger["id"], ADMIN), 200)
    entry = override_for_zone(item, zone["id"])
    assert entry is not None and len(item["zone_price_overrides"]) == 1
    assert_money(entry["price_cents"], 649, "override price_cents")
    assert_money(item["zone_override_total_cents"], 649, "zone_override_total_cents")
