"""Validation corners: uniqueness scopes, aggregate depth, conditional and cascading rules."""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from prd_bench_local_runner.testing import (  # noqa: E402
    validate_error,
    validate_paginated,
    validate_success,
)

from test_helpers import factories as f  # noqa: E402
from test_helpers.api_errors import (  # noqa: E402
    ERR_ACCESSIBILITY_AUDIT_REQUIRED,
    ERR_CAMPAIGN_WINDOW_EXPIRED,
    ERR_CLUSTER_CHAIN_INVALID,
    ERR_DEVICE_KIND_NOT_SUPPORTED,
    ERR_DUPLICATE_AVAILABILITY,
    ERR_DUPLICATE_NATURAL_KEY,
    ERR_SCREEN_READER_TEXT_MISSING,
    ERR_STORE_ACCESSIBILITY_LAPSED,
)
from test_helpers.assertions import assert_fields, assert_meta, ids_of  # noqa: E402
from test_helpers.constants import (  # noqa: E402
    ACCESSIBILITY_CONTRAST_FAIL,
    ACCESSIBILITY_READY,
    ACTION_PUBLISH,
    ACTION_VALIDATE,
    AUDIT_STATE_PASSED,
    AUDIT_STATE_PENDING,
    AVAIL_AVAILABLE,
    BUNDLE_DRAFT,
    BUNDLE_PUBLISHED,
    BUNDLE_VALIDATED,
    BURGER_BASE_CENTS,
    CACHE_FRESH,
    CACHE_MISSING,
    CATEGORY_ENTREE,
    CATEGORY_SIDE,
    CLOCK_T0,
    DEVICE_CODE_B001,
    DEVICE_CODE_K001,
    DEVICE_CODE_K002,
    DEVICE_KIOSK,
    DEVICE_MENU_BOARD,
    FRIES_BASE_CENTS,
    HEALTH_ONLINE,
    PAYMENT_COMPLIANT,
    PAYMENT_NOT_APPLICABLE,
    POSTURE_OPEN,
    SKU_BURGER,
    SKU_FRIES,
    STORE_CODE_S001,
    STORE_CODE_S002,
    SUPPLY_IN_STOCK,
    TIER_STANDARD,
    ZONE_A_CODE,
)
from test_helpers.fixtures import World, publish_bundle_with_slot  # noqa: E402
from test_helpers.test_users import (  # noqa: E402
    ADMIN,
    COMPLIANCE,
    CONTENT_MANAGER,
    make_device_agent_headers,
    make_store_operator_headers,
)

LAPSED_CERTIFICATE = "2026-08-01T00:00:00Z"
INVERTED_START = "2026-09-10T00:00:00Z"
INVERTED_END = "2026-09-01T00:00:00Z"
PAST_START = "2026-07-01T00:00:00Z"
PAST_END = "2026-08-01T00:00:00Z"


def test_two_uniqueness_rules_report_two_different_error_ids(api):
    """PRD: "At most one row may exist for a given store and item pair; a second attempt is refused with `ERR_DUPLICATE_AVAILABILITY`."

    Design: Corner/validations/declared_natural_keys_reject_a_second_row_with_the_same_key
    """
    world = World(api)
    world.set_clock(CLOCK_T0)
    zone = world.zone(ZONE_A_CODE)
    cluster = world.cluster("CL_WEST")
    store = world.store(cluster["id"], zone["id"], STORE_CODE_S001,
                        timezone_offset_minutes=-300)
    burger = world.item(SKU_BURGER, category=CATEGORY_ENTREE,
                        base_price_cents=BURGER_BASE_CENTS)
    row = world.availability(store["id"], burger["id"], on_hand_units=40, par_units=20)
    operator = make_store_operator_headers(store["id"])

    duplicate_store = api.create_store(
        f.store_payload(cluster["id"], zone["id"], STORE_CODE_S001, timezone_offset_minutes=0),
        ADMIN,
    )
    validate_error(duplicate_store, ERR_DUPLICATE_NATURAL_KEY, 409)

    duplicate_row = api.create_item_availability(
        store["id"], f.availability_payload(burger["id"], on_hand_units=5, par_units=20),
        operator,
    )
    validate_error(duplicate_row, ERR_DUPLICATE_AVAILABILITY, 409)

    stores, meta = validate_paginated(api.list_stores(ADMIN, params={"cluster_id": cluster["id"]}))
    assert ids_of(stores) == [store["id"]]
    assert_meta(meta, total_count=1)
    assert validate_success(api.get_item_availability(row["id"], operator),
                            200)["on_hand_units"] == 40


def test_the_uniqueness_scopes_admit_a_different_key(api):
    """PRD: "A store is created with a `store_code` of 1 to 12 characters, unique chain-wide, which becomes the prefix of every kitchen order number the store ever prints; a `cluster_id` naming the content cluster whose published bundle drives its boards and kiosks; a `price_zone_id` naming its local price zone; a `timezone_offset_minutes`, the fixed offset from UTC used to convert the logical clock into the store-local minute of day for daypart resolution, which must be at least -720 and at most 840; and an `accessibility_certified_until_utc`, the instant through which the store's kiosk accessibility certification remains valid, inclusive."

    Design: Corner/validations/distinct_keys_satisfy_the_same_uniqueness_rules_and_are_accepted
    """
    world = World(api)
    world.set_clock(CLOCK_T0)
    zone = world.zone(ZONE_A_CODE)
    cluster = world.cluster("CL_WEST")
    first_store = world.store(cluster["id"], zone["id"], STORE_CODE_S001,
                              timezone_offset_minutes=-300)
    burger = world.item(SKU_BURGER, category=CATEGORY_ENTREE,
                        base_price_cents=BURGER_BASE_CENTS)
    fries = world.item(SKU_FRIES, category=CATEGORY_SIDE, base_price_cents=FRIES_BASE_CENTS,
                       contrast_ratio=6.2)
    world.availability(first_store["id"], burger["id"], on_hand_units=40, par_units=20)
    publish_bundle_with_slot(world, cluster["id"],
                             category_codes=[CATEGORY_ENTREE, CATEGORY_SIDE])

    second_store = validate_success(
        api.create_store(f.store_payload(cluster["id"], zone["id"], STORE_CODE_S002,
                                         timezone_offset_minutes=-300), ADMIN),
        201,
    )
    assert second_store["id"] != first_store["id"]
    assert second_store["content_posture"] == POSTURE_OPEN, (
        "a store with no devices reads OPEN as soon as its chain resolves a published bundle"
    )

    second_row = validate_success(
        api.create_item_availability(
            first_store["id"],
            f.availability_payload(fries["id"], on_hand_units=12, par_units=20),
            make_store_operator_headers(first_store["id"])),
        201,
    )
    assert_fields(second_row, availability_state=AVAIL_AVAILABLE, supply_state=SUPPLY_IN_STOCK,
                  available_units=12)

    rows, meta = validate_paginated(
        api.list_item_availabilities(ADMIN, params={"store_id": first_store["id"]})
    )
    assert_meta(meta, total_count=2)
    assert second_row["id"] in ids_of(rows)


def test_a_sixth_cluster_on_the_chain_is_refused(api):
    """PRD: "A chain may hold at most five clusters including the cluster itself, and it may never revisit a cluster it has already visited; an attempt to attach a parent that would close a cycle or push the chain beyond five clusters is rejected with `ERR_CLUSTER_CHAIN_INVALID` (HTTP 422)."

    Design: Corner/validations/cluster_chain_deeper_than_the_declared_maximum_is_rejected
    """
    world = World(api)
    world.set_clock(CLOCK_T0)

    root = world.cluster("CL0", tier=TIER_STANDARD)
    assert root["chain_depth"] == 1, "a root cluster has a chain depth of 1"

    chain = [root]
    for index in range(1, 5):
        child = world.cluster(f"CL{index}", parent_cluster_id=chain[-1]["id"],
                              tier=TIER_STANDARD)
        assert child["chain_depth"] == index + 1
        chain.append(child)
    deepest = chain[-1]
    assert deepest["chain_depth"] == 5, "five clusters is exactly the deepest legal chain"

    refused = api.create_store_cluster(
        f.store_cluster_payload("CL5", parent_cluster_id=deepest["id"], tier=TIER_STANDARD),
        ADMIN,
    )
    validate_error(refused, ERR_CLUSTER_CHAIN_INVALID, 422)

    rows, meta = validate_paginated(
        api.list_store_clusters(ADMIN, params={"parent_cluster_id": deepest["id"]})
    )
    assert rows == [], "the rejected cluster was not partially created"
    assert_meta(meta, total_count=0)


def test_the_pin_pad_rule_is_conditional_on_the_device_kind(api):
    """PRD: "An attestation submitted for a menu board is refused with `ERR_DEVICE_KIND_NOT_SUPPORTED`; a menu board's payment dimension is `NOT_APPLICABLE` from registration and never moves."

    Design: Corner/validations/pin_pad_firmware_is_required_only_for_kiosk_devices
    """
    world = World(api)
    world.set_clock(CLOCK_T0)
    zone = world.zone(ZONE_A_CODE)
    cluster = world.cluster("CL_WEST")
    store = world.store(cluster["id"], zone["id"], STORE_CODE_S001,
                        timezone_offset_minutes=-300)

    board_payload = f.device_payload(store["id"], DEVICE_CODE_B001, DEVICE_MENU_BOARD,
                                     offline_cache_capacity=1)
    assert "pin_pad_firmware_version" not in board_payload
    board = validate_success(api.register_device(board_payload, ADMIN), 201)
    assert board["payment_compliance_state"] == PAYMENT_NOT_APPLICABLE
    kiosk = world.device(store["id"], DEVICE_CODE_K001, offline_cache_capacity=2)

    bare_kiosk = f.device_payload(store["id"], DEVICE_CODE_K002, DEVICE_KIOSK,
                                  offline_cache_capacity=2,
                                  pin_pad_firmware_version=None)
    assert "pin_pad_firmware_version" not in bare_kiosk
    validate_error(api.register_device(bare_kiosk, ADMIN), ERR_DEVICE_KIND_NOT_SUPPORTED, 422)

    validate_error(
        api.payment_attestation(board["id"], f.attestation_payload(), COMPLIANCE),
        ERR_DEVICE_KIND_NOT_SUPPORTED, 422,
    )

    attested = validate_success(
        api.payment_attestation(kiosk["id"], f.attestation_payload(), COMPLIANCE), 200)
    assert attested["payment_compliance_state"] == PAYMENT_COMPLIANT, (
        "the identical payload succeeds on a kiosk, so the payload is not what was rejected"
    )


def test_a_lapsed_certificate_stops_the_kiosk_but_not_the_board(api):
    """PRD: "For a kiosk, the owning store's `accessibility_certified_until_utc` must be at or after the logical clock, otherwise the pull is refused with `ERR_STORE_ACCESSIBILITY_LAPSED` — a store whose kiosk accessibility certification has lapsed may not receive new content."

    Design: Corner/validations/lapsed_store_certificate_blocks_only_the_kiosk_cache_sync
    """
    world = World(api)
    world.set_clock(CLOCK_T0)
    zone = world.zone(ZONE_A_CODE)
    cluster = world.cluster("CL_WEST")
    store = world.store(cluster["id"], zone["id"], STORE_CODE_S001,
                        timezone_offset_minutes=-300,
                        accessibility_certified_until_utc=LAPSED_CERTIFICATE)
    world.item(SKU_BURGER, category=CATEGORY_ENTREE, base_price_cents=BURGER_BASE_CENTS)
    bundle = publish_bundle_with_slot(world, cluster["id"], category_codes=[CATEGORY_ENTREE])
    assert bundle["state"] == BUNDLE_PUBLISHED

    kiosk = world.device(store["id"], DEVICE_CODE_K001, offline_cache_capacity=2)
    assert world.heartbeat(kiosk["id"])["health_state"] == HEALTH_ONLINE
    board = world.device(store["id"], DEVICE_CODE_B001, device_kind=DEVICE_MENU_BOARD,
                         offline_cache_capacity=1)
    world.heartbeat(board["id"])

    refused = api.cache_sync(kiosk["id"], f.cache_sync_payload(bundle["id"]),
                             make_device_agent_headers(kiosk["id"]))
    validate_error(refused, ERR_STORE_ACCESSIBILITY_LAPSED, 422)

    unchanged = world.get_device(kiosk["id"])
    assert unchanged["cache_state"] == CACHE_MISSING
    assert unchanged["cached_bundle_id"] is None

    synced = world.cache_sync(board["id"], bundle["id"])
    assert_fields(synced, cache_state=CACHE_FRESH, cached_bundle_version=1)


def test_a_window_that_ends_before_it_starts_is_refused_at_creation(api):
    """PRD: "A draft whose `window_end_utc` is at or before its `window_start_utc` is refused with `ERR_CAMPAIGN_WINDOW_EXPIRED`, as is one whose `window_end_utc` is at or before the logical clock."

    Design: Corner/validations/campaign_window_ending_before_it_starts_is_rejected_at_creation
    """
    world = World(api)
    world.set_clock(CLOCK_T0)
    cluster = world.cluster("CL_WEST")

    inverted = api.create_campaign_version(
        f.campaign_version_payload("BACKWARDS", cluster["id"], INVERTED_START, INVERTED_END,
                                   discount_value=500, priority_rank=10),
        CONTENT_MANAGER,
    )
    validate_error(inverted, ERR_CAMPAIGN_WINDOW_EXPIRED, 422)

    already_over = api.create_campaign_version(
        f.campaign_version_payload("STALE", cluster["id"], PAST_START, PAST_END,
                                   discount_value=500, priority_rank=10),
        CONTENT_MANAGER,
    )
    validate_error(already_over, ERR_CAMPAIGN_WINDOW_EXPIRED, 422)

    rows, meta = validate_paginated(
        api.list_campaign_versions(CONTENT_MANAGER, params={"cluster_id": cluster["id"]})
    )
    assert rows == []
    assert_meta(meta, total_count=0)


def test_the_publish_gate_and_the_audit_gate_unblock_in_order(api):
    """PRD: "The bundle must be in `VALIDATED` — any other state is an invalid transition — and its `accessibility_audit_state` must be `PASSED`, otherwise the publication is refused with `ERR_ACCESSIBILITY_AUDIT_REQUIRED`."

    Design: Corner/validations/publish_gate_requires_the_audit_which_requires_ready_accessibility_copy
    """
    world = World(api)
    world.set_clock(CLOCK_T0)
    zone = world.zone(ZONE_A_CODE)
    cluster = world.cluster("CL_WEST")
    world.store(cluster["id"], zone["id"], STORE_CODE_S001, timezone_offset_minutes=-300)
    burger = world.item(SKU_BURGER, category=CATEGORY_ENTREE,
                        base_price_cents=BURGER_BASE_CENTS, contrast_ratio=3.0)
    assert burger["accessibility_state"] == ACCESSIBILITY_CONTRAST_FAIL

    bundle = world.bundle(cluster["id"])
    bundle = world.slot(bundle["id"], bundle["version"], category_codes=[CATEGORY_ENTREE])
    assert bundle["snapshot_item_ids"] == [burger["id"]]
    assert bundle["accessibility_audit_state"] == AUDIT_STATE_PENDING

    validate_error(
        api.content_bundle_action(bundle["id"], f.action_payload(ACTION_VALIDATE),
                                  CONTENT_MANAGER),
        ERR_SCREEN_READER_TEXT_MISSING, 422,
    )
    validate_error(
        api.content_bundle_action(bundle["id"], f.audit_action_payload(), COMPLIANCE),
        ERR_SCREEN_READER_TEXT_MISSING, 422,
    )
    assert world.get_bundle(bundle["id"])["state"] == BUNDLE_DRAFT

    fixed = world.accessibility_copy(burger["id"], world.get_item(burger["id"])["version"],
                                     "Classic burger with lettuce and tomato", 7.1)
    assert fixed["accessibility_state"] == ACCESSIBILITY_READY
    assert fixed["version"] == burger["version"] + 1

    validated = world.validate(bundle["id"])
    assert_fields(validated, state=BUNDLE_VALIDATED,
                  accessibility_audit_state=AUDIT_STATE_PENDING)

    validate_error(
        api.content_bundle_action(bundle["id"], f.action_payload(ACTION_PUBLISH),
                                  CONTENT_MANAGER),
        ERR_ACCESSIBILITY_AUDIT_REQUIRED, 422,
    )

    audited = world.audit_pass(bundle["id"])
    assert_fields(audited, accessibility_audit_state=AUDIT_STATE_PASSED,
                  state=BUNDLE_VALIDATED)

    published = world.publish(bundle["id"])
    assert_fields(published, state=BUNDLE_PUBLISHED, bundle_version=1)
