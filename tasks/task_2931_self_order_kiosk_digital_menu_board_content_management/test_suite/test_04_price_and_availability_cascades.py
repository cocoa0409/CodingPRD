"""The two long cascades: a price override reaching a store, and an 86 reaching a cache."""

import os
import sys
from typing import Any, Dict

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from prd_bench_local_runner.testing import validate_success  # noqa: E402

from test_helpers import factories as f  # noqa: E402
from test_helpers.assertions import (  # noqa: E402
    assert_audit_action_present,
    assert_audit_money,
    assert_fields,
    assert_instant_equals,
    assert_money,
    override_for_zone,
)
from test_helpers.constants import (  # noqa: E402
    ACTION_APPLY,
    ACTION_APPROVE,
    ACTION_SUBMIT,
    AUDIT_ITEM_EIGHTY_SIXED,
    AUDIT_PRICE_OVERRIDE_APPLIED,
    AVAIL_AVAILABLE,
    AVAIL_UNAVAILABLE,
    CACHE_FRESH,
    CACHE_STALE,
    CATEGORY_ENTREE,
    CATEGORY_SIDE,
    CLOCK_T0,
    DEVICE_CODE_K001,
    EIGHTY_SIX_MANUAL,
    LISTING_EIGHTY_SIXED,
    PCR_APPLIED,
    POSTURE_DEGRADED,
    POSTURE_OPEN,
    RULE_SUSPENDED,
    SKU_BURGER,
    SKU_FRIES,
    STORE_CODE_S001,
    SUBJECT_ITEM_AVAILABILITY,
    SUBJECT_MENU_ITEM,
    SUPPLY_IN_STOCK,
    SUSPENDED_REASON_UNAVAILABLE,
    ZONE_A_CODE,
)
from test_helpers.fixtures import World, publish_bundle_with_slot  # noqa: E402
from test_helpers.test_users import (  # noqa: E402
    ADMIN,
    ANALYST,
    APPROVER,
    APPROVER_2,
    CONTENT_MANAGER,
    make_store_operator_headers,
)

EIGHTY_SIX_UNTIL = "2026-08-05T21:00:00Z"


def _approved_request_over_a_fresh_cache(api) -> Dict[str, Any]:
    world = World(api)
    world.set_clock(CLOCK_T0)
    zone = world.zone(ZONE_A_CODE)
    cluster = world.cluster("CL_WEST")
    store = world.store(cluster["id"], zone["id"], STORE_CODE_S001)
    burger = world.item(SKU_BURGER, category=CATEGORY_ENTREE, base_price_cents=500)
    bundle = publish_bundle_with_slot(world, cluster["id"], category_codes=[CATEGORY_ENTREE])
    device = world.device(store["id"], DEVICE_CODE_K001)
    world.attest(device["id"])
    world.heartbeat(device["id"])
    device = world.cache_sync(device["id"], bundle["id"])

    live_version = world.get_item(burger["id"])["version"]
    request = world.price_change_request(burger["id"], zone["id"], 590, CLOCK_T0, live_version,
                                       ANALYST, justification="Beef cost increase")
    world.pcr_action(request["id"], ACTION_SUBMIT, ANALYST)
    world.pcr_action(request["id"], ACTION_APPROVE, APPROVER)
    world.pcr_action(request["id"], ACTION_APPROVE, APPROVER_2)
    return {"world": world, "zone": zone, "store": store, "burger": burger,
            "bundle": bundle, "device": device, "request": request}


def test_the_applied_override_drifts_the_published_bundle(api):
    """PRD: "Because the item's price moved, every content bundle that is `PUBLISHED` and whose cluster owns at least one store in that price zone recomputes its live price checksum, raises its drift marker to true, and increments its own `version` by 1."

    Design: Difficulty/transitive_cascade/price_apply_cascade_depth_four_to_store_posture
    """
    scene = _approved_request_over_a_fresh_cache(api)
    world, store, burger = scene["world"], scene["store"], scene["burger"]

    assert world.get_store(store["id"])["content_posture"] == POSTURE_OPEN

    applied = validate_success(
        api.price_change_request_action(scene["request"]["id"], f.action_payload(ACTION_APPLY),
                                       ANALYST),
        200,
    )
    assert_fields(applied, state=PCR_APPLIED)
    assert_money(applied["applied_price_cents"], 599, "applied_price_cents")

    item = validate_success(api.get_menu_item(burger["id"], ADMIN), 200)
    entry = override_for_zone(item, scene["zone"]["id"])
    assert entry is not None and entry["applied_request_id"] == scene["request"]["id"]
    assert_money(entry["price_cents"], 599, "override price_cents")
    assert_money(item["zone_override_total_cents"], 599, "zone_override_total_cents")

    bundle = validate_success(api.get_content_bundle(scene["bundle"]["id"], ADMIN), 200)
    assert bundle["stale_flag"] is True
    assert bundle["live_price_checksum"] != bundle["price_snapshot_checksum"]


def test_the_drift_reaches_the_device_cache_and_then_the_store_posture(api):
    """PRD: "Because those devices changed, every store owning one of them re-derives its `content_posture`, which is what turns an `OPEN` store into a `DEGRADED` one until its devices re-sync."

    Design: Difficulty/transitive_cascade/price_apply_cascade_depth_four_to_store_posture
    """
    scene = _approved_request_over_a_fresh_cache(api)
    store, device = scene["store"], scene["device"]
    assert device["cache_state"] == CACHE_FRESH

    validate_success(
        api.price_change_request_action(scene["request"]["id"], f.action_payload(ACTION_APPLY),
                                       ANALYST),
        200,
    )

    device_after = validate_success(api.get_device(device["id"], ADMIN), 200)
    assert_fields(device_after, cache_state=CACHE_STALE, cached_bundle_id=scene["bundle"]["id"])

    store_after = validate_success(api.get_store(store["id"], ADMIN), 200)
    assert store_after["content_posture"] == POSTURE_DEGRADED

    rows = validate_success(
        api.list_audit_events(ADMIN, params={"subject_kind": SUBJECT_MENU_ITEM, "limit": 100}), 200
    )
    applied_rows = assert_audit_action_present(rows, AUDIT_PRICE_OVERRIDE_APPLIED)
    assert_audit_money(applied_rows[0], before_value_cents=559, after_value_cents=599)


def _manual_eighty_six_scenario(api) -> Dict[str, Any]:
    world = World(api)
    world.set_clock(CLOCK_T0)
    zone = world.zone(ZONE_A_CODE)
    cluster = world.cluster("CL_WEST")
    store = world.store(cluster["id"], zone["id"], STORE_CODE_S001)
    burger = world.item(SKU_BURGER, category=CATEGORY_ENTREE, base_price_cents=500)
    fries = world.item(SKU_FRIES, category=CATEGORY_SIDE, base_price_cents=310)
    bundle = publish_bundle_with_slot(world, cluster["id"],
                                     category_codes=[CATEGORY_ENTREE, CATEGORY_SIDE])
    avail_a = world.availability(store["id"], burger["id"], on_hand_units=40, par_units=20)
    avail_b = world.availability(store["id"], fries["id"], on_hand_units=40, par_units=20)
    rule = world.upsell_rule(cluster["id"], burger["id"], fries["id"])
    device = world.device(store["id"], DEVICE_CODE_K001)
    world.attest(device["id"])
    world.heartbeat(device["id"])
    device = world.cache_sync(device["id"], bundle["id"])
    return {"world": world, "store": store, "burger": burger, "fries": fries,
            "avail_a": avail_a, "avail_b": avail_b, "rule": rule,
            "bundle": bundle, "device": device}


def test_a_manual_eighty_six_suspends_the_rule_that_suggests_the_item(api):
    """PRD: "If that rollup reached `UNAVAILABLE`, every upsell rule whose `suggested_item_id` is this item and whose state is `ACTIVE` moves to `SUSPENDED` with `suspended_reason` set to the token `SUGGESTED_ITEM_UNAVAILABLE`."

    Design: Difficulty/transitive_cascade/manual_eighty_six_cascade_depth_five_to_device_cache
    """
    scene = _manual_eighty_six_scenario(api)
    store, fries = scene["store"], scene["fries"]

    response = api.item_availability_action(
        scene["avail_b"]["id"],
        f.eighty_six_payload(EIGHTY_SIX_UNTIL, eighty_six_reason="Fryer out of service"),
        make_store_operator_headers(store["id"]),
    )
    row = validate_success(response, 200)

    assert_fields(row, listing_state=LISTING_EIGHTY_SIXED, eighty_six_state=EIGHTY_SIX_MANUAL,
                  availability_state=AVAIL_UNAVAILABLE, supply_state=SUPPLY_IN_STOCK)
    assert_instant_equals(row["eighty_six_until_utc"], EIGHTY_SIX_UNTIL, "eighty_six_until_utc")

    item = validate_success(api.get_menu_item(fries["id"], ADMIN), 200)
    assert item["chainwide_availability_state"] == AVAIL_UNAVAILABLE

    rule = validate_success(api.get_upsell_rule(scene["rule"]["id"], CONTENT_MANAGER), 200)
    assert_fields(rule, state=RULE_SUSPENDED, suspended_reason=SUSPENDED_REASON_UNAVAILABLE)


def test_the_suspension_drifts_the_bundle_the_cache_and_the_posture(api):
    """PRD: "`stale_flag` is true whenever `live_price_checksum` differs from `price_snapshot_checksum`, and also whenever an upsell rule of the bundle's cluster has been suspended since publication."

    Design: Difficulty/transitive_cascade/manual_eighty_six_cascade_depth_five_to_device_cache
    """
    scene = _manual_eighty_six_scenario(api)
    store = scene["store"]

    validate_success(
        api.item_availability_action(
            scene["avail_b"]["id"],
            f.eighty_six_payload(EIGHTY_SIX_UNTIL, eighty_six_reason="Fryer out of service"),
            make_store_operator_headers(store["id"]),
        ),
        200,
    )

    bundle = validate_success(api.get_content_bundle(scene["bundle"]["id"], ADMIN), 200)
    assert bundle["stale_flag"] is True

    device = validate_success(api.get_device(scene["device"]["id"], ADMIN), 200)
    assert device["cache_state"] == CACHE_STALE

    store_after = validate_success(api.get_store(store["id"], ADMIN), 200)
    assert store_after["content_posture"] == POSTURE_DEGRADED

    untouched = validate_success(api.get_item_availability(scene["avail_a"]["id"], ADMIN), 200)
    assert untouched["availability_state"] == AVAIL_AVAILABLE

    rows = validate_success(
        api.list_audit_events(ADMIN, params={"subject_kind": SUBJECT_ITEM_AVAILABILITY,
                                            "limit": 100}),
        200,
    )
    assert_audit_action_present(rows, AUDIT_ITEM_EIGHTY_SIXED)
