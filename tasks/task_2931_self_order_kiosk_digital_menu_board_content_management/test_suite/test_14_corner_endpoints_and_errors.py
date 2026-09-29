"""Endpoint surfaces and three error identifiers reached from their own gates."""

import os
import sys
from typing import Any, Dict

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from prd_bench_local_runner.testing import (  # noqa: E402
    NON_EXISTENT_UUID,
    validate_error,
    validate_paginated,
    validate_success,
)

from test_helpers import factories as f  # noqa: E402
from test_helpers.api_errors import (  # noqa: E402
    ERR_ITEM_EIGHTY_SIXED,
    ERR_OFFLINE_CACHE_CAPACITY_EXCEEDED,
    ERR_REFERENCED_ENTITY_NOT_FOUND,
    ERR_UPSELL_RULE_NOT_ELIGIBLE,
)
from test_helpers.assertions import (  # noqa: E402
    assert_envelope,
    assert_fields,
    assert_instant_equals,
    assert_meta,
    assert_money,
    assert_order_totals,
    ids_of,
)
from test_helpers.constants import (  # noqa: E402
    ACTION_RESTORE,
    AVAIL_AVAILABLE,
    AVAIL_UNAVAILABLE,
    BURGER_BASE_CENTS,
    BURGER_ZONE_A_CENTS,
    CACHE_FRESH,
    CATEGORY_ENTREE,
    CATEGORY_SIDE,
    CLOCK_T0,
    DEVICE_CODE_K001,
    EIGHTY_SIX_AUTO,
    EIGHTY_SIX_NONE,
    FRIES_BASE_CENTS,
    FRIES_ZONE_A_CENTS,
    HANDOFF_CACHED_OFFLINE,
    HANDOFF_QUEUED,
    HEALTH_DEGRADED,
    LISTING_EIGHTY_SIXED,
    LISTING_LISTED,
    PAYMENT_AUTHORIZED,
    POSTURE_DEGRADED,
    POSTURE_OPEN,
    REASON_INVENTORY_DEPLETED,
    RULE_ACTIVE,
    RULE_KIND_COMBO,
    SKU_BURGER,
    SKU_FRIES,
    STORE_CODE_S001,
    SUPPLY_DEPLETED,
    TENDER_CARD,
    ZONE_A_CODE,
)
from test_helpers.fixtures import World, publish_bundle_with_slot  # noqa: E402
from test_helpers.test_users import (  # noqa: E402
    ADMIN,
    CONTENT_MANAGER,
    make_device_agent_headers,
    make_store_operator_headers,
)

SKU_ENTREE_1 = "SKU-E1"
SKU_ENTREE_2 = "SKU-E2"
SKU_ENTREE_3 = "SKU-E3"
SKU_SIDE_1 = "SKU-F1"
AUTO_86_UNTIL = "2026-08-05T19:00:00Z"
EIGHTY_SIX_UNTIL = "2026-08-05T21:00:00Z"


def _kiosk_stack(api, capacity: int = 2, with_fries: bool = False,
                 attest: bool = True) -> Dict[str, Any]:
    """One store with a published ENTREE bundle and one healthy attested kiosk."""
    world = World(api)
    world.set_clock(CLOCK_T0)
    zone = world.zone(ZONE_A_CODE)
    cluster = world.cluster("CL_WEST")
    store = world.store(cluster["id"], zone["id"], STORE_CODE_S001)
    burger = world.item(SKU_BURGER, category=CATEGORY_ENTREE,
                        base_price_cents=BURGER_BASE_CENTS)
    categories = [CATEGORY_ENTREE]
    fries = None
    fries_row = None
    if with_fries:
        fries = world.item(SKU_FRIES, category=CATEGORY_SIDE,
                           base_price_cents=FRIES_BASE_CENTS, contrast_ratio=6.2)
        categories.append(CATEGORY_SIDE)
    burger_row = world.availability(store["id"], burger["id"], on_hand_units=40, par_units=20)
    if fries is not None:
        fries_row = world.availability(store["id"], fries["id"], on_hand_units=40, par_units=20)
    bundle = publish_bundle_with_slot(world, cluster["id"], category_codes=categories)
    device = world.device(store["id"], DEVICE_CODE_K001, offline_cache_capacity=capacity)
    if attest:
        world.attest(device["id"])
    world.heartbeat(device["id"])
    device = world.cache_sync(device["id"], bundle["id"])
    return {
        "world": world,
        "zone": zone,
        "cluster": cluster,
        "store": store,
        "burger": burger,
        "fries": fries,
        "burger_row": burger_row,
        "fries_row": fries_row,
        "bundle": bundle,
        "device": device,
    }


def test_the_category_filter_is_applied_before_the_pagination_window(api):
    """PRD: "Every endpoint that returns a collection is paginated through two query parameters."

    Design: Corner/endpoints/menu_item_list_endpoint_combines_a_filter_with_limit_and_offset
    """
    world = World(api)
    world.set_clock(CLOCK_T0)
    entree_1 = world.item(SKU_ENTREE_1, category=CATEGORY_ENTREE, base_price_cents=500)
    entree_2 = world.item(SKU_ENTREE_2, category=CATEGORY_ENTREE, base_price_cents=540)
    world.item(SKU_SIDE_1, category=CATEGORY_SIDE, base_price_cents=310, contrast_ratio=6.2)
    entree_3 = world.item(SKU_ENTREE_3, category=CATEGORY_ENTREE, base_price_cents=480,
                          contrast_ratio=7.4)

    page_one, meta_one = validate_paginated(
        api.list_menu_items(CONTENT_MANAGER,
                            params={"category": CATEGORY_ENTREE, "limit": 2, "offset": 0})
    )
    assert ids_of(page_one) == [entree_1["id"], entree_2["id"]]
    assert_meta(meta_one, total_count=3, limit=2, offset=0, has_more=True)

    page_two, meta_two = validate_paginated(
        api.list_menu_items(CONTENT_MANAGER,
                            params={"category": CATEGORY_ENTREE, "limit": 2, "offset": 2})
    )
    assert ids_of(page_two) == [entree_3["id"]]
    assert_meta(meta_two, total_count=3, offset=2, has_more=False)

    windowed = [row["sku"] for row in page_one + page_two]
    assert SKU_SIDE_1 not in windowed, (
        "the category filter is applied before the window, so total_count is 3 and not 4"
    )

    everything, meta_all = validate_paginated(api.list_menu_items(CONTENT_MANAGER))
    assert_meta(meta_all, total_count=4)
    assert len(everything) == 4


def test_a_sync_to_zero_auto_eighty_sixes_and_a_restore_only_relists(api):
    """PRD: "`listing_state` is set to `EIGHTY_SIXED`, `eighty_six_state` to `AUTO_86`, `eighty_six_reason` to the token `INVENTORY_DEPLETED`, and `eighty_six_until_utc` to two hours after the logical clock; `availability_state` becomes `UNAVAILABLE`."

    Design: Corner/endpoints/availability_actions_endpoint_auto_eighty_sixes_a_depleted_sync
    """
    world = World(api)
    world.set_clock(CLOCK_T0)
    zone = world.zone(ZONE_A_CODE)
    cluster = world.cluster("CL_WEST")
    store = world.store(cluster["id"], zone["id"], STORE_CODE_S001)
    burger = world.item(SKU_BURGER, category=CATEGORY_ENTREE,
                        base_price_cents=BURGER_BASE_CENTS)
    operator = make_store_operator_headers(store["id"])
    row = validate_success(
        api.create_item_availability(store["id"],
                                     f.availability_payload(burger["id"], on_hand_units=40,
                                                            par_units=20),
                                     operator),
        201,
    )
    assert row["availability_state"] == AVAIL_AVAILABLE

    depleted = validate_success(
        api.item_availability_action(row["id"], f.sync_on_hand_payload(0, 0), operator), 200
    )
    assert_fields(depleted, supply_state=SUPPLY_DEPLETED, listing_state=LISTING_EIGHTY_SIXED,
                  eighty_six_state=EIGHTY_SIX_AUTO,
                  eighty_six_reason=REASON_INVENTORY_DEPLETED,
                  availability_state=AVAIL_UNAVAILABLE, available_units=0)
    assert_instant_equals(depleted["eighty_six_until_utc"], AUTO_86_UNTIL, "eighty_six_until_utc")
    assert_instant_equals(depleted["last_sync_utc"], CLOCK_T0, "last_sync_utc")
    assert world.get_item(burger["id"])["chainwide_availability_state"] == AVAIL_UNAVAILABLE

    restored = validate_success(
        api.item_availability_action(row["id"], f.action_payload(ACTION_RESTORE), operator), 200
    )
    assert_fields(restored, listing_state=LISTING_LISTED, eighty_six_state=EIGHTY_SIX_NONE,
                  supply_state=SUPPLY_DEPLETED, availability_state=AVAIL_UNAVAILABLE)
    assert restored["eighty_six_until_utc"] is None
    assert restored["eighty_six_reason"] is None
    assert world.get_item(burger["id"])["chainwide_availability_state"] == AVAIL_UNAVAILABLE


def test_reading_a_store_re_derives_its_posture_without_writing_to_it(api):
    """PRD: "It is one of `OPEN`, `DEGRADED` or `FROZEN` and is recomputed from the store's devices and its cluster chain whenever the store is read and after every device registration, heartbeat, cache synchronisation or payment attestation, every bundle publication or rollback, every price cascade and every clock movement."

    Design: Corner/endpoints/store_read_recomputes_content_posture_without_any_write
    """
    scene = _kiosk_stack(api)
    store, device = scene["store"], scene["device"]
    assert device["cache_state"] == CACHE_FRESH

    response = api.get_store(store["id"], make_store_operator_headers(store["id"]))
    assert_envelope(response, "object")
    healthy = validate_success(response, 200)
    assert_fields(healthy, id=store["id"], content_posture=POSTURE_OPEN, open_order_count=0)

    degraded_device = validate_success(
        api.send_heartbeat(device["id"], f.heartbeat_payload(network_ok=False),
                           make_device_agent_headers(device["id"])),
        200,
    )
    assert_fields(degraded_device, rolling_health_score=75, health_state=HEALTH_DEGRADED)

    after = validate_success(
        api.get_store(store["id"], make_store_operator_headers(store["id"])), 200)
    assert_fields(after, id=store["id"], content_posture=POSTURE_DEGRADED)


def test_an_offline_order_is_released_only_by_a_sync_carrying_the_flush_flag(api):
    """PRD: "With `flush_offline_orders` true, every order this device is holding offline is released to the kitchen as described in §3.9 and `offline_order_count` is recomputed."

    Design: Corner/endpoints/offline_order_flush_happens_only_when_the_flag_is_set
    """
    scene = _kiosk_stack(api)
    device, store, bundle = scene["device"], scene["store"], scene["bundle"]
    agent = make_device_agent_headers(device["id"])
    operator = make_store_operator_headers(store["id"])

    order = validate_success(
        api.create_order(device["id"],
                         f.order_payload([f.line(scene["burger"]["id"], 1)],
                                         tender_kind=TENDER_CARD, created_offline=True),
                         agent),
        201,
    )
    assert_fields(order, handoff_state=HANDOFF_CACHED_OFFLINE,
                  payment_state=PAYMENT_AUTHORIZED, order_number="S001-0001")

    unflushed = validate_success(
        api.cache_sync(device["id"], f.cache_sync_payload(bundle["id"]), agent), 200)
    assert unflushed["offline_order_count"] == 1
    still_cached = validate_success(api.get_order_handoff(order["id"], operator), 200)
    assert still_cached["handoff_state"] == HANDOFF_CACHED_OFFLINE

    flushed_device = validate_success(
        api.cache_sync(device["id"], f.cache_sync_payload(bundle["id"], flush_offline_orders=True),
                       agent),
        200,
    )
    assert flushed_device["offline_order_count"] == 0
    released = validate_success(api.get_order_handoff(order["id"], operator), 200)
    assert_fields(released, handoff_state=HANDOFF_QUEUED, payment_state=PAYMENT_AUTHORIZED)

    row = validate_success(api.get_item_availability(scene["burger_row"]["id"], operator), 200)
    assert row["reserved_units"] == 1, "the flush is not a second reservation"


def test_an_upsell_rule_needs_both_of_its_menu_items_to_resolve(api):
    """PRD: "Body reference existence — every foreign key in the body resolves → `ERR_REFERENCED_ENTITY_NOT_FOUND` (404). Applies to every creating endpoint that carries foreign keys."

    Design: Corner/endpoints/upsell_rule_link_requires_both_referenced_menu_items_to_exist
    """
    world = World(api)
    world.set_clock(CLOCK_T0)
    cluster = world.cluster("CL_WEST")
    burger = world.item(SKU_BURGER, category=CATEGORY_ENTREE,
                        base_price_cents=BURGER_BASE_CENTS)
    fries = world.item(SKU_FRIES, category=CATEGORY_SIDE, base_price_cents=FRIES_BASE_CENTS,
                       contrast_ratio=6.2)

    validate_error(
        api.create_upsell_rule(
            f.upsell_rule_payload(cluster["id"], burger["id"], NON_EXISTENT_UUID,
                                  rule_kind=RULE_KIND_COMBO, min_cart_subtotal_cents=0,
                                  suggestion_slot=1, max_prompt_seconds=20),
            CONTENT_MANAGER),
        ERR_REFERENCED_ENTITY_NOT_FOUND, 404,
    )

    rule = validate_success(
        api.create_upsell_rule(
            f.upsell_rule_payload(cluster["id"], burger["id"], fries["id"],
                                  rule_kind=RULE_KIND_COMBO, min_cart_subtotal_cents=0,
                                  suggestion_slot=1, max_prompt_seconds=20),
            CONTENT_MANAGER),
        201,
    )
    assert rule["state"] == RULE_ACTIVE

    for params in ({"suggested_item_id": fries["id"]}, {"trigger_item_id": burger["id"]},
                   {"cluster_id": cluster["id"]}):
        rows, meta = validate_paginated(api.list_upsell_rules(CONTENT_MANAGER, params=params))
        assert ids_of(rows) == [rule["id"]], f"the link is navigable by {params}"
        assert_meta(meta, total_count=1)


def test_the_offline_cache_capacity_bounds_only_the_offline_backlog(api):
    """PRD: "A device already holding as many cached-offline orders as its `offline_cache_capacity` permits may not capture another offline order and is refused with `ERR_OFFLINE_CACHE_CAPACITY_EXCEEDED`."

    Design: Corner/errors/offline_capacity_bounds_the_offline_order_backlog
    """
    scene = _kiosk_stack(api, capacity=1)
    device, store, burger = scene["device"], scene["store"], scene["burger"]
    agent = make_device_agent_headers(device["id"])
    assert device["offline_cache_capacity"] == 1

    first = validate_success(
        api.create_order(device["id"],
                         f.order_payload([f.line(burger["id"], 1)], tender_kind=TENDER_CARD,
                                         created_offline=True),
                         agent),
        201,
    )
    assert first["handoff_state"] == HANDOFF_CACHED_OFFLINE
    assert scene["world"].get_device(device["id"])["offline_order_count"] == 1

    validate_error(
        api.create_order(device["id"],
                         f.order_payload([f.line(burger["id"], 1)], tender_kind=TENDER_CARD,
                                         created_offline=True),
                         agent),
        ERR_OFFLINE_CACHE_CAPACITY_EXCEEDED, 409,
    )

    online = validate_success(
        api.create_order(device["id"],
                         f.order_payload([f.line(burger["id"], 1)], tender_kind=TENDER_CARD),
                         agent),
        201,
    )
    assert_fields(online, handoff_state=HANDOFF_QUEUED, order_number="S001-0002")

    assert scene["world"].get_store(store["id"])["daily_order_seq_counter"] == 2, (
        "the refused capture consumed no order number"
    )
    rows, meta = validate_paginated(api.list_order_handoffs(ADMIN, params={"device_id": device["id"]}))
    assert_meta(meta, total_count=2)
    assert first["id"] in ids_of(rows)


def test_an_accepted_rule_whose_suggested_item_is_absent_is_not_eligible(api):
    """PRD: "Every entry of `accepted_upsell_rule_ids` must be an `ACTIVE` rule of the store's cluster chain whose `trigger_item_id` **and** whose `suggested_item_id` are both in the cart — the guest having accepted it, the suggested item is expected to be there — or the capture is refused with `ERR_UPSELL_RULE_NOT_ELIGIBLE`."

    Design: Corner/errors/accepted_upsell_rule_must_match_the_cart_contents
    """
    scene = _kiosk_stack(api, with_fries=True)
    world, device, store = scene["world"], scene["device"], scene["store"]
    burger, fries = scene["burger"], scene["fries"]
    rule = world.upsell_rule(scene["cluster"]["id"], burger["id"], fries["id"],
                             rule_kind=RULE_KIND_COMBO, min_cart_subtotal_cents=0,
                             suggestion_slot=1, max_prompt_seconds=20)
    agent = make_device_agent_headers(device["id"])

    validate_error(
        api.create_order(device["id"],
                         f.order_payload([f.line(burger["id"], 1)], tender_kind=TENDER_CARD,
                                         accepted_upsell_rule_ids=[rule["id"]]),
                         agent),
        ERR_UPSELL_RULE_NOT_ELIGIBLE, 422,
    )
    assert world.get_store(store["id"])["daily_order_seq_counter"] == 0

    accepted = validate_success(
        api.create_order(device["id"],
                         f.order_payload([f.line(burger["id"], 1), f.line(fries["id"], 1)],
                                         tender_kind=TENDER_CARD,
                                         accepted_upsell_rule_ids=[rule["id"]]),
                         agent),
        201,
    )
    assert_order_totals(accepted, subtotal_cents=BURGER_ZONE_A_CENTS + FRIES_ZONE_A_CENTS,
                        discount_cents=0, tax_cents=79, total_cents=987)
    assert_fields(accepted, order_number="S001-0001")
    assert accepted["accepted_upsell_rule_ids"] == [rule["id"]]


def test_an_eighty_sixed_line_is_refused_until_the_row_is_restored(api):
    """PRD: "And no ordered line's availability row at the capturing store may be `UNAVAILABLE`, or the capture is refused with `ERR_ITEM_EIGHTY_SIXED`."

    Design: Corner/errors/ordering_an_eighty_sixed_line_is_refused
    """
    scene = _kiosk_stack(api)
    device, store, burger, row = scene["device"], scene["store"], scene["burger"], scene["burger_row"]
    operator = make_store_operator_headers(store["id"])
    agent = make_device_agent_headers(device["id"])

    pulled = validate_success(
        api.item_availability_action(
            row["id"], f.eighty_six_payload(EIGHTY_SIX_UNTIL, eighty_six_reason="Grill down"),
            operator),
        200,
    )
    assert pulled["availability_state"] == AVAIL_UNAVAILABLE
    assert burger["id"] in scene["bundle"]["snapshot_item_ids"], (
        "the item is still in the published snapshot, so the 86 gate is the one that fires"
    )

    validate_error(
        api.create_order(device["id"],
                         f.order_payload([f.line(burger["id"], 1)], tender_kind=TENDER_CARD),
                         agent),
        ERR_ITEM_EIGHTY_SIXED, 409,
    )

    restored = validate_success(
        api.item_availability_action(row["id"], f.action_payload(ACTION_RESTORE), operator), 200)
    assert restored["availability_state"] == AVAIL_AVAILABLE

    retried = validate_success(
        api.create_order(device["id"],
                         f.order_payload([f.line(burger["id"], 1)], tender_kind=TENDER_CARD),
                         agent),
        201,
    )
    assert_fields(retried, order_number="S001-0001", handoff_state=HANDOFF_QUEUED)
    assert_money(retried["total_cents"], 608, "total_cents")
