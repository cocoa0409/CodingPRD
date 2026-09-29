"""Compensations restore the conserved quantity exactly, and only that quantity."""

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
    assert_money,
    assert_order_totals,
    override_for_zone,
    projection_item,
)
from test_helpers.constants import (  # noqa: E402
    ACTION_APPLY,
    ACTION_APPROVE,
    ACTION_SUBMIT,
    ACTION_VOID,
    AUDIT_ORDER_VOIDED,
    AUDIT_PRICE_OVERRIDE_APPLIED,
    AUDIT_PRICE_OVERRIDE_ROLLED_BACK,
    ACTION_ROLLBACK,
    AVAIL_AVAILABLE,
    BURGER_ZONE_A_CENTS,
    CACHE_FRESH,
    CATEGORY_ENTREE,
    CLOCK_T0,
    DEVICE_CODE_K001,
    HANDOFF_VOIDED,
    PAYMENT_VOIDED,
    PCR_ROLLED_BACK,
    POSTURE_OPEN,
    SKU_BURGER,
    STORE_CODE_S001,
    SUBJECT_MENU_ITEM,
    SUBJECT_ORDER_HANDOFF,
    SUPPLY_IN_STOCK,
    TENDER_CARD,
    TENDER_CASH,
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

APPLIED_OVERRIDE_CENTS = 599


def _applied_then_rollbackable(api) -> Dict[str, Any]:
    world = World(api)
    world.set_clock(CLOCK_T0)
    zone = world.zone(ZONE_A_CODE)
    cluster = world.cluster("CL_WEST")
    store = world.store(cluster["id"], zone["id"], STORE_CODE_S001)
    burger = world.item(SKU_BURGER, category=CATEGORY_ENTREE, base_price_cents=500)
    bundle = publish_bundle_with_slot(world, cluster["id"], category_codes=[CATEGORY_ENTREE])
    world.availability(store["id"], burger["id"], on_hand_units=40, par_units=20)
    device = world.device(store["id"], DEVICE_CODE_K001)
    world.attest(device["id"])
    world.heartbeat(device["id"])
    device = world.cache_sync(device["id"], bundle["id"])

    total_before = world.get_item(burger["id"])["zone_override_total_cents"]
    request = world.price_change_request(burger["id"], zone["id"], 590, CLOCK_T0,
                                        world.get_item(burger["id"])["version"], ANALYST,
                                        justification="Beef cost increase")
    world.pcr_action(request["id"], ACTION_SUBMIT, ANALYST)
    world.pcr_action(request["id"], ACTION_APPROVE, APPROVER)
    world.pcr_action(request["id"], ACTION_APPROVE, APPROVER_2)
    applied = world.pcr_action(request["id"], ACTION_APPLY, ANALYST)
    item_applied = world.get_item(burger["id"])
    return {"world": world, "zone": zone, "store": store, "burger": burger, "bundle": bundle,
            "device": device, "request": applied, "total_before": total_before,
            "item_applied": item_applied}


def test_rolling_back_returns_the_override_total_to_exactly_its_prior_value(api):
    """PRD: "Because `zone_override_total_cents` is the sum of live overrides, a rolled-back price is verifiable: the item's override total returns to exactly the value it held before the apply."

    Design: Difficulty/compensating_invariant/price_rollback_restores_zone_override_total_and_cache_freshness
    """
    scene = _applied_then_rollbackable(api)
    world, burger, zone = scene["world"], scene["burger"], scene["zone"]

    assert_money(scene["total_before"], 0, "zone_override_total_cents before the apply")
    assert_money(scene["item_applied"]["zone_override_total_cents"], APPLIED_OVERRIDE_CENTS,
                 "zone_override_total_cents after the apply")

    rolled = world.pcr_action(scene["request"]["id"], ACTION_ROLLBACK, APPROVER)
    assert rolled["state"] == PCR_ROLLED_BACK
    assert_money(rolled["applied_price_cents"], APPLIED_OVERRIDE_CENTS,
                 "applied_price_cents retained for the audit trail")

    item = world.get_item(burger["id"])
    assert_money(item["zone_override_total_cents"], 0, "zone_override_total_cents after rollback")
    assert item["zone_price_overrides"] == []
    assert override_for_zone(item, zone["id"]) is None
    assert item["version"] == scene["item_applied"]["version"] + 1, (
        "compensation advances the version, it never rewinds it"
    )


def test_rolling_back_refreshes_the_cascade_without_erasing_the_audit_trail(api):
    """PRD: "It then walks the same cascade in reverse: every `PUBLISHED` bundle the forward apply touched recomputes its live price checksum and its drift marker, which returns to false when no other drift remains; every device caching such a bundle recomputes its content dimension, returning to `FRESH` when the bundle is published, undrifted and version-matched; and every affected store re-derives its `content_posture`."

    Design: Difficulty/compensating_invariant/price_rollback_restores_zone_override_total_and_cache_freshness
    """
    scene = _applied_then_rollbackable(api)
    world, burger, store = scene["world"], scene["burger"], scene["store"]

    world.pcr_action(scene["request"]["id"], ACTION_ROLLBACK, APPROVER)

    assert world.get_bundle(scene["bundle"]["id"])["stale_flag"] is False
    assert world.get_device(scene["device"]["id"])["cache_state"] == CACHE_FRESH
    assert world.get_store(store["id"])["content_posture"] == POSTURE_OPEN

    projection = validate_success(
        api.get_menu_projection(store["id"], CONTENT_MANAGER), 200
    )
    assert projection["stale_prices"] is False
    assert_money(projection_item(projection, burger["id"])["price_cents"],
                 BURGER_ZONE_A_CENTS, "board display price after the rollback")

    rows = world.audit(subject_kind=SUBJECT_MENU_ITEM, subject_id=burger["id"])
    forward = assert_audit_action_present(rows, AUDIT_PRICE_OVERRIDE_APPLIED)
    assert_audit_money(forward[0], BURGER_ZONE_A_CENTS, APPLIED_OVERRIDE_CENTS)
    back = assert_audit_action_present(rows, AUDIT_PRICE_OVERRIDE_ROLLED_BACK)
    assert_audit_money(back[0], APPLIED_OVERRIDE_CENTS, BURGER_ZONE_A_CENTS)


def _captured_card_order_for_four(api) -> Dict[str, Any]:
    world = World(api)
    world.set_clock(CLOCK_T0)
    zone = world.zone(ZONE_A_CODE)
    cluster = world.cluster("CL_WEST")
    store = world.store(cluster["id"], zone["id"], STORE_CODE_S001)
    burger = world.item(SKU_BURGER, category=CATEGORY_ENTREE, base_price_cents=500)
    bundle = publish_bundle_with_slot(world, cluster["id"], category_codes=[CATEGORY_ENTREE])
    row = world.availability(store["id"], burger["id"], on_hand_units=40, par_units=20)
    device = world.device(store["id"], DEVICE_CODE_K001)
    world.attest(device["id"])
    world.heartbeat(device["id"])
    device = world.cache_sync(device["id"], bundle["id"])

    store_before = world.get_store(store["id"])
    order = world.order(device["id"], [f.line(burger["id"], 4)], tender_kind=TENDER_CARD)
    row_during = validate_success(api.get_item_availability(row["id"], ADMIN), 200)
    return {"world": world, "store": store, "burger": burger, "device": device, "row": row,
            "order": order, "store_before": store_before, "row_during": row_during}


def test_voiding_releases_every_reserved_unit_exactly(api):
    """PRD: "Every priced line's `qty` is released from its availability row's `reserved_units`, and `available_units`, `supply_state` and `availability_state` are re-derived so that the row returns to **exactly** the values it held before the order was captured."

    Design: Difficulty/compensating_invariant/order_void_conserves_reserved_units_but_retires_the_order_number
    """
    scene = _captured_card_order_for_four(api)
    order, row = scene["order"], scene["row"]

    assert scene["store_before"]["daily_order_seq_counter"] == 0
    assert order["order_number"] == "S001-0001"
    assert_order_totals(order, subtotal_cents=2236, discount_cents=0, tax_cents=196,
                        total_cents=2432)
    assert_fields(row, reserved_units=0, available_units=40)
    assert_fields(scene["row_during"], reserved_units=4, available_units=36)

    voided = validate_success(
        api.order_handoff_action(order["id"],
                                 f.action_payload(ACTION_VOID,
                                                  void_reason="Guest abandoned the order"),
                                 make_store_operator_headers(scene["store"]["id"])),
        200,
    )
    assert_fields(voided, handoff_state=HANDOFF_VOIDED, payment_state=PAYMENT_VOIDED)

    restored = validate_success(api.get_item_availability(row["id"], ADMIN), 200)
    assert_fields(restored, reserved_units=0, available_units=40,
                  supply_state=SUPPLY_IN_STOCK, availability_state=AVAIL_AVAILABLE)


def test_voiding_retires_the_order_number_and_keeps_the_money_on_the_ticket(api):
    """PRD: "One quantity is deliberately **not** compensated: the store's `daily_order_seq_counter` is never decremented, so the voided order's number is permanently retired and the day's numbering carries a visible gap."

    Design: Difficulty/compensating_invariant/order_void_conserves_reserved_units_but_retires_the_order_number
    """
    scene = _captured_card_order_for_four(api)
    world, order, store, device = (scene["world"], scene["order"], scene["store"],
                                   scene["device"])

    validate_success(
        api.order_handoff_action(order["id"],
                                 f.action_payload(ACTION_VOID,
                                                  void_reason="Guest abandoned the order"),
                                 make_store_operator_headers(store["id"])),
        200,
    )

    nxt = world.order(device["id"], [f.line(scene["burger"]["id"], 1)], tender_kind=TENDER_CASH)
    assert nxt["order_number"] == "S001-0002", "S001-0001 is permanently retired"
    assert world.get_store(store["id"])["open_order_count"] == 1

    voided = validate_success(api.get_order_handoff(order["id"], ADMIN), 200)
    assert_money(voided["total_cents"], 2432, "the voided ticket keeps its money")

    rows = world.audit(subject_kind=SUBJECT_ORDER_HANDOFF, subject_id=order["id"])
    found = assert_audit_action_present(rows, AUDIT_ORDER_VOIDED)
    assert_audit_money(found[0], 2432, 0)
