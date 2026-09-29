"""One entity's own state is legal; a second entity's state is what refuses the call."""

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
    ERR_BUNDLE_NOT_PUBLISHED,
    ERR_STORE_CONTENT_FROZEN,
)
from test_helpers.assertions import (  # noqa: E402
    assert_audit_action_present,
    assert_fields,
    assert_meta,
)
from test_helpers.constants import (  # noqa: E402
    ACTOR_SYSTEM,
    BUNDLE_DRAFT,
    BUNDLE_VALIDATED,
    CACHE_FRESH,
    CACHE_MISSING,
    CATEGORY_ENTREE,
    CLOCK_T0,
    DEVICE_CODE_K001,
    HEALTH_ONLINE,
    HEALTH_QUARANTINED,
    POSTURE_FROZEN,
    POSTURE_OPEN,
    SKU_BURGER,
    STORE_CODE_S001,
    SUBJECT_STORE,
    AUDIT_STORE_CONTENT_FROZEN,
    TENDER_CARD,
    ZONE_A_CODE,
)
from test_helpers.fixtures import World, publish_bundle_with_slot  # noqa: E402
from test_helpers.test_users import ADMIN, make_device_agent_headers  # noqa: E402

CLOCK_SEVENTEEN_MINUTES_LATER = "2026-08-05T17:17:00Z"


def _draft_bundle_and_a_healthy_kiosk(api) -> Dict[str, Any]:
    world = World(api)
    world.set_clock(CLOCK_T0)
    zone = world.zone(ZONE_A_CODE)
    cluster = world.cluster("CL_WEST")
    store = world.store(cluster["id"], zone["id"], STORE_CODE_S001)
    world.item(SKU_BURGER, category=CATEGORY_ENTREE, base_price_cents=500)
    bundle = world.bundle(cluster["id"])
    bundle = world.slot(bundle["id"], bundle["version"], category_codes=[CATEGORY_ENTREE])
    device = world.device(store["id"], DEVICE_CODE_K001)
    world.attest(device["id"])
    device = world.heartbeat(device["id"])
    return {"world": world, "store": store, "bundle": bundle, "device": device}


def test_an_unpublished_bundle_refuses_the_cache_pull_from_a_healthy_device(api):
    """PRD: "The named bundle must be `PUBLISHED` and its cluster must lie on the device's store's cluster inheritance chain; a bundle that is not published, or whose cluster is off that chain, is refused with `ERR_BUNDLE_NOT_PUBLISHED`."

    Design: Difficulty/cross_entity_state_dependency/device_cache_sync_gated_by_content_bundle_state
    """
    scene = _draft_bundle_and_a_healthy_kiosk(api)
    bundle, device = scene["bundle"], scene["device"]

    assert bundle["state"] == BUNDLE_DRAFT
    assert_fields(device, health_state=HEALTH_ONLINE, cache_state=CACHE_MISSING)

    response = api.cache_sync(device["id"], f.cache_sync_payload(bundle["id"]),
                              make_device_agent_headers(device["id"]))
    validate_error(response, ERR_BUNDLE_NOT_PUBLISHED, 409)


def test_validated_is_not_published_but_publishing_opens_the_cache(api):
    """PRD: "A successful pull stores `cached_bundle_id` and `cached_bundle_version`, sets the content dimension to `FRESH` — or straight to `STALE` when the bundle's `stale_flag` is already true — and re-derives the owning store's `content_posture`."

    Design: Difficulty/cross_entity_state_dependency/device_cache_sync_gated_by_content_bundle_state
    """
    scene = _draft_bundle_and_a_healthy_kiosk(api)
    world, bundle, device, store = (scene["world"], scene["bundle"], scene["device"],
                                    scene["store"])
    assert world.get_store(store["id"])["content_posture"] == POSTURE_FROZEN, (
        "a chain with no published bundle is frozen"
    )

    world.audit_pass(bundle["id"])
    validated = world.validate(bundle["id"])
    assert validated["state"] == BUNDLE_VALIDATED

    validate_error(
        api.cache_sync(device["id"], f.cache_sync_payload(bundle["id"]),
                       make_device_agent_headers(device["id"])),
        ERR_BUNDLE_NOT_PUBLISHED, 409,
    )

    published = world.publish(bundle["id"])
    synced = validate_success(
        api.cache_sync(device["id"], f.cache_sync_payload(bundle["id"]),
                       make_device_agent_headers(device["id"])),
        200,
    )
    assert_fields(synced, cache_state=CACHE_FRESH, cached_bundle_id=bundle["id"],
                  cached_bundle_version=published["bundle_version"])
    assert world.get_store(store["id"])["content_posture"] == POSTURE_OPEN


def _store_frozen_by_its_only_quarantined_kiosk(api) -> Dict[str, Any]:
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
    posture_open = world.get_store(store["id"])["content_posture"]
    clock = world.set_clock(CLOCK_SEVENTEEN_MINUTES_LATER)
    return {"world": world, "store": store, "burger": burger, "device": device,
            "posture_open": posture_open, "clock": clock}


def test_a_frozen_store_outranks_the_quarantined_device_that_froze_it(api):
    """PRD: "The posture is `FROZEN` when the store's cluster inheritance chain resolves no content bundle in the `PUBLISHED` state, or when the store has at least one `KIOSK` device and every one of its `KIOSK` devices has a `health_state` of `OFFLINE` or `QUARANTINED`."

    Design: Difficulty/cross_entity_state_dependency/order_creation_gated_by_store_posture_frozen_by_quarantine
    """
    scene = _store_frozen_by_its_only_quarantined_kiosk(api)
    world, store, burger, device = (scene["world"], scene["store"], scene["burger"],
                                    scene["device"])

    assert scene["posture_open"] == POSTURE_OPEN
    assert scene["clock"]["devices_rescored"] == 1

    rescored = world.get_device(device["id"])
    assert_fields(rescored, consecutive_missed_heartbeats=3, rolling_health_score=55,
                  worst_case_health_score=40, health_state=HEALTH_QUARANTINED)
    assert world.get_store(store["id"])["content_posture"] == POSTURE_FROZEN

    response = api.create_order(
        device["id"], f.order_payload([f.line(burger["id"], 1)], tender_kind=TENDER_CARD),
        make_device_agent_headers(device["id"]),
    )
    validate_error(response, ERR_STORE_CONTENT_FROZEN, 409)


def test_the_freeze_is_audited_by_the_system_and_costs_no_order_number(api):
    """PRD: "A store whose posture is `FROZEN` refuses every kiosk order with `ERR_STORE_CONTENT_FROZEN`, and the transition into `FROZEN` is recorded on the audit trail with subject kind `STORE` and action `STORE_CONTENT_FROZEN` attributed to the system."

    Design: Difficulty/cross_entity_state_dependency/order_creation_gated_by_store_posture_frozen_by_quarantine
    """
    scene = _store_frozen_by_its_only_quarantined_kiosk(api)
    world, store, burger, device = (scene["world"], scene["store"], scene["burger"],
                                    scene["device"])

    validate_error(
        api.create_order(device["id"],
                         f.order_payload([f.line(burger["id"], 1)], tender_kind=TENDER_CARD),
                         make_device_agent_headers(device["id"])),
        ERR_STORE_CONTENT_FROZEN, 409,
    )

    rows = world.audit(subject_kind=SUBJECT_STORE, subject_id=store["id"])
    # PRD 2.9: every transition *into* FROZEN is recorded.  This store crosses that
    # boundary twice: once when its first KIOSK is registered OFFLINE, and once when
    # the clock quarantines that same kiosk.  Both are attributed to the system.
    frozen = assert_audit_action_present(rows, AUDIT_STORE_CONTENT_FROZEN, count=2)
    assert [row["actor_role"] for row in frozen] == [ACTOR_SYSTEM, ACTOR_SYSTEM]

    handoffs, meta = validate_paginated(
        api.list_order_handoffs(ADMIN, params={"device_id": device["id"]})
    )
    assert handoffs == []
    assert_meta(meta, total_count=0)
    assert world.get_store(store["id"])["daily_order_seq_counter"] == 0
