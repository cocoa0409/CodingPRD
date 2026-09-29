"""Optimistic concurrency, threshold bands and the immediacy of every derived effect."""

import os
import sys
from typing import Any, Dict

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from prd_bench_local_runner.testing import (  # noqa: E402
    is_iso8601_timestamp,
    validate_error,
    validate_paginated,
    validate_success,
)

from test_helpers import factories as f  # noqa: E402
from test_helpers.api_errors import (  # noqa: E402
    ERR_STALE_CONTENT_BUNDLE_VERSION,
    ERR_STALE_MENU_ITEM_VERSION,
)
from test_helpers.assertions import (  # noqa: E402
    assert_fields,
    assert_instant_equals,
    assert_meta,
    assert_money,
    assert_order_totals,
    assert_priced_line,
)
from test_helpers.constants import (  # noqa: E402
    ACCESSIBILITY_READY,
    ACTION_KITCHEN_ACK,
    AVAIL_AVAILABLE,
    BUNDLE_DRAFT,
    BURGER_BASE_CENTS,
    BURGER_ZONE_A_CENTS,
    CACHE_FRESH,
    CATEGORY_ENTREE,
    CLOCK_T0,
    DEVICE_CODE_K001,
    DINNER_CODE,
    DINNER_END,
    DINNER_LAYOUT,
    DINNER_START,
    HANDOFF_ACCEPTED,
    HANDOFF_QUEUED,
    HEALTH_DEGRADED,
    HEALTH_ONLINE,
    HEALTH_QUARANTINED,
    LUNCH_CODE,
    LUNCH_END,
    LUNCH_LAYOUT,
    LUNCH_START,
    PAYMENT_AUTHORIZED,
    PAYMENT_CAPTURED,
    PAYMENT_COMPLIANT,
    PCR_DRAFT,
    POSTURE_FROZEN,
    POSTURE_OPEN,
    SKU_BURGER,
    STORE_CODE_S001,
    SUPPLY_IN_STOCK,
    TENDER_CARD,
    ZONE_A_CODE,
)
from test_helpers.fixtures import World, publish_bundle_with_slot  # noqa: E402
from test_helpers.test_users import (  # noqa: E402
    ANALYST,
    COMPLIANCE,
    CONTENT_MANAGER,
    make_device_agent_headers,
    make_store_operator_headers,
)

FUTURE_EFFECTIVE = "2026-08-10T00:00:00Z"
CLOCK_PLUS_10 = "2026-08-05T17:10:00Z"
CLOCK_PLUS_15 = "2026-08-05T17:15:00Z"
NEW_SCREEN_READER_TEXT = "Classic burger with lettuce and tomato"


def _store_with_a_healthy_attested_kiosk(api) -> Dict[str, Any]:
    """A published ENTREE bundle, a stocked availability row and one fresh kiosk."""
    world = World(api)
    world.set_clock(CLOCK_T0)
    zone = world.zone(ZONE_A_CODE)
    cluster = world.cluster("CL_WEST")
    store = world.store(cluster["id"], zone["id"], STORE_CODE_S001)
    burger = world.item(SKU_BURGER, category=CATEGORY_ENTREE,
                        base_price_cents=BURGER_BASE_CENTS)
    row = world.availability(store["id"], burger["id"], on_hand_units=40, par_units=20)
    bundle = publish_bundle_with_slot(world, cluster["id"], category_codes=[CATEGORY_ENTREE])
    device = world.device(store["id"], DEVICE_CODE_K001)
    attested = world.attest(device["id"])
    beat = world.heartbeat(device["id"])
    device = world.cache_sync(device["id"], bundle["id"])
    assert attested["payment_compliance_state"] == PAYMENT_COMPLIANT
    assert beat["health_state"] == HEALTH_ONLINE
    return {
        "world": world,
        "store": store,
        "burger": burger,
        "row": row,
        "bundle": bundle,
        "device": device,
    }


def test_a_stale_menu_item_version_blocks_both_guarded_writes(api):
    """PRD: "If the value does not equal the menu item's current `version`, the request is rejected with `ERR_STALE_MENU_ITEM_VERSION` (HTTP 412)."

    Design: Corner/complexity_layers/stale_menu_item_version_blocks_the_price_change_request
    """
    world = World(api)
    world.set_clock(CLOCK_T0)
    zone = world.zone(ZONE_A_CODE)
    cluster = world.cluster("CL_ZONE")
    world.store(cluster["id"], zone["id"], STORE_CODE_S001)
    burger = world.item(SKU_BURGER, category=CATEGORY_ENTREE,
                        base_price_cents=BURGER_BASE_CENTS)
    stale_version = burger["version"]
    assert stale_version == 1

    rewritten = validate_success(
        api.write_accessibility_copy(
            burger["id"],
            f.accessibility_copy_payload(stale_version, NEW_SCREEN_READER_TEXT, 8.4),
            COMPLIANCE),
        200,
    )
    assert_fields(rewritten, version=2, accessibility_state=ACCESSIBILITY_READY)
    live_version = rewritten["version"]

    validate_error(
        api.create_price_change_request(
            f.price_change_request_payload(burger["id"], zone["id"], 569, FUTURE_EFFECTIVE,
                                           stale_version,
                                           justification="Commodity cost increase"),
            ANALYST),
        ERR_STALE_MENU_ITEM_VERSION, 412,
    )
    validate_error(
        api.write_accessibility_copy(
            burger["id"],
            f.accessibility_copy_payload(stale_version, "Should not land", 9.0), COMPLIANCE),
        ERR_STALE_MENU_ITEM_VERSION, 412,
    )

    unchanged = world.get_item(burger["id"])
    assert_fields(unchanged, version=live_version, screen_reader_text=NEW_SCREEN_READER_TEXT)

    accepted = validate_success(
        api.create_price_change_request(
            f.price_change_request_payload(burger["id"], zone["id"], 569, FUTURE_EFFECTIVE,
                                           live_version,
                                           justification="Commodity cost increase"),
            ANALYST),
        201,
    )
    assert_fields(accepted, state=PCR_DRAFT, uplift_bp=179)
    assert_money(accepted["baseline_price_cents"], BURGER_ZONE_A_CENTS, "baseline_price_cents")

    rows, meta = validate_paginated(
        api.list_price_change_requests(ANALYST, params={"menu_item_id": burger["id"]})
    )
    assert len(rows) == 1
    assert_meta(meta, total_count=1)


def test_a_stale_bundle_version_blocks_the_append_before_the_overlap_test(api):
    """PRD: "If the value does not equal the bundle's current `version`, the append is rejected with `ERR_STALE_CONTENT_BUNDLE_VERSION` (HTTP 412)."

    Design: Corner/complexity_layers/stale_content_bundle_version_blocks_the_next_daypart_slot
    """
    world = World(api)
    world.set_clock(CLOCK_T0)
    zone = world.zone(ZONE_A_CODE)
    cluster = world.cluster("CL_WEST")
    world.store(cluster["id"], zone["id"], STORE_CODE_S001)
    bundle = world.bundle(cluster["id"], effective_from_utc="2026-08-05T00:00:00Z")
    assert_fields(bundle, version=1, state=BUNDLE_DRAFT)
    assert bundle["daypart_slots"] == []
    stale_version = bundle["version"]

    after_lunch = validate_success(
        api.append_daypart_slot(
            bundle["id"],
            f.daypart_slot_payload(stale_version, daypart_code=LUNCH_CODE,
                                   start_minute_of_day=LUNCH_START,
                                   end_minute_of_day=LUNCH_END, layout_code=LUNCH_LAYOUT,
                                   buffer_minutes=15, category_codes=[CATEGORY_ENTREE]),
            CONTENT_MANAGER),
        200,
    )
    assert after_lunch["version"] == 2
    live_version = after_lunch["version"]

    def dinner(expected_version: int):
        return f.daypart_slot_payload(expected_version, daypart_code=DINNER_CODE,
                                      start_minute_of_day=DINNER_START,
                                      end_minute_of_day=DINNER_END,
                                      layout_code=DINNER_LAYOUT, buffer_minutes=15,
                                      category_codes=[CATEGORY_ENTREE])

    validate_error(api.append_daypart_slot(bundle["id"], dinner(stale_version), CONTENT_MANAGER),
                   ERR_STALE_CONTENT_BUNDLE_VERSION, 412)
    validate_error(
        api.append_daypart_slot(
            bundle["id"],
            f.daypart_slot_payload(stale_version, daypart_code=LUNCH_CODE,
                                   start_minute_of_day=700, end_minute_of_day=800,
                                   layout_code=LUNCH_LAYOUT, buffer_minutes=15,
                                   category_codes=[CATEGORY_ENTREE]),
            CONTENT_MANAGER),
        ERR_STALE_CONTENT_BUNDLE_VERSION, 412,
    )
    assert len(world.get_bundle(bundle["id"])["daypart_slots"]) == 1, (
        "the two refused appends left the slot list untouched"
    )

    retried = validate_success(
        api.append_daypart_slot(bundle["id"], dinner(live_version), CONTENT_MANAGER), 200)
    assert_fields(retried, version=3, state=BUNDLE_DRAFT)
    assert [slot["daypart_code"] for slot in retried["daypart_slots"]] == [LUNCH_CODE, DINNER_CODE]


def test_quarantine_bites_at_the_third_miss_and_the_next_beat_clears_it(api):
    """PRD: "Otherwise, a device whose missed count has reached 3 **and** whose `worst_case_health_score` is below 50 is `QUARANTINED`."

    Design: Corner/complexity_layers/quarantine_thresholds_bite_at_the_third_miss_and_reset_on_the_next_beat
    """
    scene = _store_with_a_healthy_attested_kiosk(api)
    world, store, device = scene["world"], scene["store"], scene["device"]

    fresh = world.get_device(device["id"])
    assert_fields(fresh, consecutive_missed_heartbeats=0, rolling_health_score=100,
                  health_state=HEALTH_ONLINE, cache_state=CACHE_FRESH)
    assert world.get_store(store["id"])["content_posture"] == POSTURE_OPEN

    world.set_clock(CLOCK_PLUS_10)
    two_missed = world.get_device(device["id"])
    assert_fields(two_missed, consecutive_missed_heartbeats=2, rolling_health_score=70,
                  worst_case_health_score=40, health_state=HEALTH_DEGRADED)

    world.set_clock(CLOCK_PLUS_15)
    three_missed = world.get_device(device["id"])
    assert_fields(three_missed, consecutive_missed_heartbeats=3, rolling_health_score=55,
                  worst_case_health_score=40, health_state=HEALTH_QUARANTINED)
    assert world.get_store(store["id"])["content_posture"] == POSTURE_FROZEN, (
        "a quarantined kiosk freezes the store it serves"
    )

    recovered = validate_success(
        api.send_heartbeat(device["id"], f.heartbeat_payload(),
                           make_device_agent_headers(device["id"])),
        200,
    )
    # PRD 3.8: the worst-case measure always charges two additional hypothetical
    # misses, so a device that has just beaten reads 100 - 2 * 15 = 70.
    assert_fields(recovered, consecutive_missed_heartbeats=0, rolling_health_score=100,
                  worst_case_health_score=70, health_state=HEALTH_ONLINE)
    assert_instant_equals(recovered["last_heartbeat_utc"], CLOCK_PLUS_15, "last_heartbeat_utc")
    assert world.get_store(store["id"])["content_posture"] == POSTURE_OPEN, (
        "the quarantine leaves no residue once the beat arrives"
    )


def test_every_derived_effect_of_a_capture_is_already_in_its_own_response(api):
    """PRD: "A **kitchen acknowledgement**, driven by the `StoreOperator` whose `X-User-ID` equals the store of the capturing device, moves the kitchen dimension `QUEUED_TO_KITCHEN → ACCEPTED` and, in the same request, the payment dimension `AUTHORIZED → CAPTURED`; both dimensions move together here."

    Design: Corner/consistency_model/every_derived_effect_of_an_order_is_already_in_its_own_response
    """
    scene = _store_with_a_healthy_attested_kiosk(api)
    world, store, device, burger = scene["world"], scene["store"], scene["device"], scene["burger"]
    operator = make_store_operator_headers(store["id"])

    order = validate_success(
        api.create_order(device["id"],
                         f.order_payload([f.line(burger["id"], 2)], tender_kind=TENDER_CARD),
                         make_device_agent_headers(device["id"])),
        201,
    )
    assert_order_totals(order, subtotal_cents=2 * BURGER_ZONE_A_CENTS, discount_cents=0,
                        tax_cents=98, total_cents=1216)
    assert_fields(order, order_number="S001-0001", payment_state=PAYMENT_AUTHORIZED,
                  handoff_state=HANDOFF_QUEUED, daypart_code=LUNCH_CODE,
                  pinned_bundle_version=1)
    assert order["receipt_hash"], "the receipt hash is stamped by the capture itself"
    assert is_iso8601_timestamp(order["created_at"])
    assert len(order["priced_lines"]) == 1
    assert_priced_line(order["priced_lines"][0], burger["id"], 2, BURGER_ZONE_A_CENTS,
                       2 * BURGER_ZONE_A_CENTS, 0)

    row = validate_success(api.get_item_availability(scene["row"]["id"], operator), 200)
    assert_fields(row, reserved_units=2, available_units=38, on_hand_units=40,
                  availability_state=AVAIL_AVAILABLE, supply_state=SUPPLY_IN_STOCK)
    assert_fields(world.get_store(store["id"]), open_order_count=1, daily_order_seq_counter=1)

    reread = validate_success(api.get_order_handoff(order["id"], operator), 200)
    assert_fields(reread, order_number="S001-0001", handoff_state=HANDOFF_QUEUED,
                  payment_state=PAYMENT_AUTHORIZED)
    assert_money(reread["total_cents"], 1216, "total_cents")

    acknowledged = validate_success(
        api.order_handoff_action(order["id"], f.action_payload(ACTION_KITCHEN_ACK), operator), 200
    )
    assert_fields(acknowledged, handoff_state=HANDOFF_ACCEPTED, payment_state=PAYMENT_CAPTURED)
    assert world.get_store(store["id"])["open_order_count"] == 1, (
        "queued and accepted orders both count as open"
    )
