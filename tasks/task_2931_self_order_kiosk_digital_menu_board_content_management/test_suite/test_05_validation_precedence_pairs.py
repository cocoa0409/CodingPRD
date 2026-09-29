"""Three pairs of simultaneously violated rules, each resolved by the pinned order."""

import os
import sys
from typing import Any, Dict

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from prd_bench_local_runner.testing import (  # noqa: E402
    validate_error,
    validate_paginated,
    validate_success,
)

from test_helpers import factories as f  # noqa: E402
from test_helpers.api_errors import (  # noqa: E402
    ERR_EFFECTIVE_DATE_IN_PAST,
    ERR_PAYMENT_DEVICE_NON_COMPLIANT,
    ERR_REQUEST_NOT_APPROVED,
    ERR_UPLIFT_CAP_EXCEEDED,
)
from test_helpers.assertions import assert_fields, assert_meta  # noqa: E402
from test_helpers.constants import (  # noqa: E402
    ACTION_APPLY,
    ACTION_APPROVE,
    ACTION_SUBMIT,
    CATEGORY_DESSERT,
    CATEGORY_ENTREE,
    CLOCK_T0,
    DEVICE_CODE_K001,
    HEALTH_ONLINE,
    PAYMENT_UNATTESTED,
    PCR_PENDING_APPROVAL,
    POSTURE_DEGRADED,
    SKU_BURGER,
    SKU_PIE,
    STORE_CODE_S001,
    TENDER_CARD,
    ZONE_A_CODE,
)
from test_helpers.fixtures import World, publish_bundle_with_slot  # noqa: E402
from test_helpers.test_users import (  # noqa: E402
    ADMIN,
    ANALYST,
    APPROVER,
    make_device_agent_headers,
)

BACKDATED_INSTANT = "2026-08-04T00:00:00Z"


def _one_of_two_approvals(api) -> Dict[str, Any]:
    world = World(api)
    world.set_clock(CLOCK_T0)
    zone = world.zone(ZONE_A_CODE)
    cluster = world.cluster("CL_ZONE")
    world.store(cluster["id"], zone["id"], STORE_CODE_S001)
    burger = world.item(SKU_BURGER, category=CATEGORY_ENTREE, base_price_cents=500)
    live_version = world.get_item(burger["id"])["version"]
    request = world.price_change_request(burger["id"], zone["id"], 590, CLOCK_T0, live_version,
                                       ANALYST, justification="Beef cost increase")
    world.pcr_action(request["id"], ACTION_SUBMIT, ANALYST)
    partly = world.pcr_action(request["id"], ACTION_APPROVE, APPROVER)
    return {"world": world, "zone": zone, "burger": burger, "request": partly}


def test_applying_an_unapproved_request_reports_the_approval_state_not_the_count(api):
    """PRD: "Applying a price change to a request that is still `PENDING_APPROVAL` **and** short of its second approval returns `ERR_REQUEST_NOT_APPROVED`, not `ERR_DUAL_APPROVAL_REQUIRED`, because the approval-state specialisation sits at position 12 and the approval-count check at position 35."

    Design: Difficulty/priority_pair_validation_conflict/apply_unapproved_state_beats_dual_approval_shortfall
    """
    scene = _one_of_two_approvals(api)
    request = scene["request"]
    assert_fields(request, state=PCR_PENDING_APPROVAL, required_approvals=2)
    assert len(request["approval_user_ids"]) == 1

    response = api.price_change_request_action(request["id"], f.action_payload(ACTION_APPLY),
                                               ANALYST)
    validate_error(response, ERR_REQUEST_NOT_APPROVED, 409)


def test_the_refused_apply_leaves_no_partial_effect(api):
    """PRD: "The request must be in `APPROVED` — an attempt on any other state is refused with `ERR_REQUEST_NOT_APPROVED` — the logical clock must have reached or passed `effective_from_utc`, otherwise the apply is refused with `ERR_EFFECTIVE_DATE_IN_PAST`, and the item's live `version` must still equal `pinned_menu_item_version`, otherwise the apply is refused with `ERR_STALE_MENU_ITEM_VERSION`."

    Design: Difficulty/priority_pair_validation_conflict/apply_unapproved_state_beats_dual_approval_shortfall
    """
    scene = _one_of_two_approvals(api)

    validate_error(
        api.price_change_request_action(scene["request"]["id"], f.action_payload(ACTION_APPLY),
                                       ANALYST),
        ERR_REQUEST_NOT_APPROVED, 409,
    )

    request = validate_success(
        api.get_price_change_request(scene["request"]["id"], ANALYST), 200
    )
    assert request["state"] == PCR_PENDING_APPROVAL
    assert request["applied_price_cents"] is None

    item = validate_success(api.get_menu_item(scene["burger"]["id"], ADMIN), 200)
    assert item["zone_price_overrides"] == []


def _unattested_kiosk_and_an_unsnapshotted_item(api) -> Dict[str, Any]:
    world = World(api)
    world.set_clock(CLOCK_T0)
    zone = world.zone(ZONE_A_CODE)
    cluster = world.cluster("CL_WEST")
    store = world.store(cluster["id"], zone["id"], STORE_CODE_S001)
    world.item(SKU_BURGER, category=CATEGORY_ENTREE, base_price_cents=500)
    pie = world.item(SKU_PIE, category=CATEGORY_DESSERT, base_price_cents=200,
                     contrast_ratio=5.4)
    bundle = publish_bundle_with_slot(world, cluster["id"], category_codes=[CATEGORY_ENTREE])
    world.availability(store["id"], pie["id"], on_hand_units=40, par_units=20)
    device = world.device(store["id"], DEVICE_CODE_K001)
    world.heartbeat(device["id"])
    device = world.cache_sync(device["id"], bundle["id"])
    return {"world": world, "store": store, "pie": pie, "bundle": bundle, "device": device}


def test_payment_noncompliance_outranks_the_item_outside_the_snapshot(api):
    """PRD: "A card-tendered order captured on an unattested device for an item that is also missing from the pinned snapshot returns `ERR_PAYMENT_DEVICE_NON_COMPLIANT`, not `ERR_ITEM_NOT_IN_PUBLISHED_BUNDLE`."

    Design: Difficulty/priority_pair_validation_conflict/payment_noncompliance_beats_item_outside_published_bundle
    """
    scene = _unattested_kiosk_and_an_unsnapshotted_item(api)
    device, store, pie = scene["device"], scene["store"], scene["pie"]

    assert_fields(device, payment_compliance_state=PAYMENT_UNATTESTED, health_state=HEALTH_ONLINE)
    assert pie["id"] not in scene["bundle"]["snapshot_item_ids"], (
        "the DESSERT item must sit outside a snapshot frozen over ENTREE only"
    )
    assert validate_success(api.get_store(store["id"], ADMIN), 200)["content_posture"] == (
        POSTURE_DEGRADED
    )

    response = api.create_order(
        device["id"],
        f.order_payload([f.line(pie["id"], 1)], tender_kind=TENDER_CARD),
        make_device_agent_headers(device["id"]),
    )
    validate_error(response, ERR_PAYMENT_DEVICE_NON_COMPLIANT, 422)


def test_the_refused_capture_consumes_no_order_number(api):
    """PRD: "`daily_order_seq_counter` is the store's monotonic per-UTC-date order counter, initialised to 0, incremented on every successfully captured order and **never** decremented — a voided order leaves a permanent gap in the day's numbering."

    Design: Difficulty/priority_pair_validation_conflict/payment_noncompliance_beats_item_outside_published_bundle
    """
    scene = _unattested_kiosk_and_an_unsnapshotted_item(api)
    device, store, pie = scene["device"], scene["store"], scene["pie"]

    validate_error(
        api.create_order(device["id"],
                         f.order_payload([f.line(pie["id"], 1)], tender_kind=TENDER_CARD),
                         make_device_agent_headers(device["id"])),
        ERR_PAYMENT_DEVICE_NON_COMPLIANT, 422,
    )

    rows, meta = validate_paginated(api.list_order_handoffs(ADMIN, params={"device_id": device["id"]}))
    assert rows == []
    assert_meta(meta, total_count=0)

    store_after = validate_success(api.get_store(store["id"], ADMIN), 200)
    assert store_after["daily_order_seq_counter"] == 0


def _zone_with_one_store(api) -> Dict[str, Any]:
    world = World(api)
    world.set_clock(CLOCK_T0)
    zone = world.zone(ZONE_A_CODE)
    cluster = world.cluster("CL_ZONE")
    world.store(cluster["id"], zone["id"], STORE_CODE_S001)
    burger = world.item(SKU_BURGER, category=CATEGORY_ENTREE, base_price_cents=500)
    return {"world": world, "zone": zone, "burger": burger}


def test_a_backdated_request_reports_the_effective_date_not_the_cap(api):
    """PRD: "And a price change request that is both backdated and above its zone's uplift cap returns `ERR_EFFECTIVE_DATE_IN_PAST`, not `ERR_UPLIFT_CAP_EXCEEDED`."

    Design: Difficulty/priority_pair_validation_conflict/past_effective_date_beats_uplift_cap_breach
    """
    scene = _zone_with_one_store(api)
    world, burger, zone = scene["world"], scene["burger"], scene["zone"]
    live_version = world.get_item(burger["id"])["version"]

    response = api.create_price_change_request(
        f.price_change_request_payload(burger["id"], zone["id"], 643, BACKDATED_INSTANT,
                                       live_version, justification="Backdated correction"),
        ANALYST,
    )
    validate_error(response, ERR_EFFECTIVE_DATE_IN_PAST, 422)

    rows, meta = validate_paginated(
        api.list_price_change_requests(ANALYST, params={"menu_item_id": burger["id"]})
    )
    assert rows == []
    assert_meta(meta, total_count=0)


def test_the_same_proposal_does_breach_the_zone_cap_once_it_is_not_backdated(api):
    """PRD: "Only then, against that same `uplift_bp`, does the server test the zone's ceiling: an uplift strictly greater than the zone's `max_uplift_bp` is refused with `ERR_UPLIFT_CAP_EXCEEDED`, and the refusal is absolute — a proposal above the cap is never quietly clamped down to it."

    Design: Difficulty/priority_pair_validation_conflict/past_effective_date_beats_uplift_cap_breach
    """
    scene = _zone_with_one_store(api)
    world, burger, zone = scene["world"], scene["burger"], scene["zone"]
    live_version = world.get_item(burger["id"])["version"]

    response = api.create_price_change_request(
        f.price_change_request_payload(burger["id"], zone["id"], 643, CLOCK_T0, live_version,
                                       justification="Above the zone ceiling"),
        ANALYST,
    )
    validate_error(response, ERR_UPLIFT_CAP_EXCEEDED, 422)
