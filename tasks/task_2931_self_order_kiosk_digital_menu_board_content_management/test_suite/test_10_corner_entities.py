"""Entity-level corners: envelopes, defaults, derived fields, keys and the graph."""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from prd_bench_local_runner.testing import (  # noqa: E402
    NON_EXISTENT_UUID,
    is_valid_uuid,
    validate_error,
    validate_paginated,
    validate_success,
)

from test_helpers import factories as f  # noqa: E402
from test_helpers.api_errors import (  # noqa: E402
    ERR_INVALID_REQUEST,
    ERR_REFERENCED_ENTITY_NOT_FOUND,
    ERR_RESOURCE_NOT_FOUND,
    ERR_UPSELL_CYCLE_DETECTED,
)
from test_helpers.assertions import (  # noqa: E402
    assert_audit_row_shape,
    assert_common_fields,
    assert_envelope,
    assert_fields,
    assert_instant_equals,
    assert_meta,
    ids_of,
)
from test_helpers.constants import (  # noqa: E402
    AUDIT_ITEM_EIGHTY_SIXED,
    AVAIL_AVAILABLE,
    BUNDLE_DRAFT,
    CATEGORY_DESSERT,
    CATEGORY_ENTREE,
    CATEGORY_SIDE,
    CACHE_MISSING,
    CLOCK_T0,
    DEFAULT_CURRENCY,
    DEVICE_CODE_B001,
    DEVICE_MENU_BOARD,
    EIGHTY_SIX_NONE,
    HEALTH_OFFLINE,
    LISTING_LISTED,
    PAYMENT_NOT_APPLICABLE,
    POSTURE_FROZEN,
    ROLE_STORE_OPERATOR,
    ROUNDING_NINE_ENDING,
    ROUNDING_NONE,
    RULE_ACTIVE,
    RULE_KIND_COMBO,
    SKU_BURGER,
    SKU_FRIES,
    SKU_PIE,
    STORE_CODE_S001,
    SUBJECT_ITEM_AVAILABILITY,
    SUPPLY_IN_STOCK,
    TIER_STANDARD,
    ZONE_A_CODE,
    ZONE_A_MAX_UPLIFT_BP,
    ZONE_A_MULTIPLIER_BP,
    ZONE_A_TAX_BP,
    ZONE_B_CODE,
    ZONE_B_MAX_UPLIFT_BP,
    ZONE_B_MULTIPLIER_BP,
    ZONE_B_TAX_BP,
)
from test_helpers.fixtures import World  # noqa: E402
from test_helpers.test_users import (  # noqa: E402
    ADMIN,
    COMPLIANCE,
    CONTENT_MANAGER,
    make_store_operator_headers,
)

EIGHTY_SIX_UNTIL = "2026-08-05T21:00:00Z"


def test_creating_a_price_zone_returns_the_envelope_and_every_declared_field(api):
    """PRD: "A `PlatformAdmin` registers a price zone with a `zone_code` — a human-readable local zone code of 1 to 16 characters that must be unique chain-wide and is compared case-sensitively — and a `currency_code`, the ISO-4217 currency of every price in the zone, given as exactly three uppercase letters and defaulting to `USD` when omitted."

    Design: Corner/entities/create_price_zone_returns_201_with_envelope_and_all_declared_fields
    """
    world = World(api)
    world.set_clock(CLOCK_T0)

    response = api.create_price_zone(
        f.price_zone_payload(ZONE_A_CODE, currency_code=DEFAULT_CURRENCY,
                             price_multiplier_bp=ZONE_A_MULTIPLIER_BP,
                             psychological_rounding=ROUNDING_NINE_ENDING,
                             tax_rate_bp=ZONE_A_TAX_BP, max_uplift_bp=ZONE_A_MAX_UPLIFT_BP),
        ADMIN,
    )
    assert_envelope(response, "object")
    zone = validate_success(response, 201)

    assert_common_fields(zone, expect_version=1)
    assert_fields(zone, zone_code=ZONE_A_CODE, currency_code=DEFAULT_CURRENCY,
                  price_multiplier_bp=ZONE_A_MULTIPLIER_BP,
                  psychological_rounding=ROUNDING_NINE_ENDING,
                  tax_rate_bp=ZONE_A_TAX_BP, max_uplift_bp=ZONE_A_MAX_UPLIFT_BP)
    assert_instant_equals(zone["created_at"], CLOCK_T0, "created_at")
    assert_instant_equals(zone["updated_at"], CLOCK_T0, "updated_at")


def test_reading_a_price_zone_returns_the_stored_row_untouched(api):
    """PRD: "`version` — an integer that starts at 1 on creation and increments by exactly 1 on every mutation of the row."

    Design: Corner/entities/get_price_zone_by_id_returns_the_stored_row_unchanged
    """
    world = World(api)
    world.set_clock(CLOCK_T0)
    created = world.zone(ZONE_B_CODE, price_multiplier_bp=ZONE_B_MULTIPLIER_BP,
                         psychological_rounding=ROUNDING_NONE, tax_rate_bp=ZONE_B_TAX_BP,
                         max_uplift_bp=ZONE_B_MAX_UPLIFT_BP)

    fetched = validate_success(api.get_price_zone(created["id"], CONTENT_MANAGER), 200)

    assert_fields(fetched, id=created["id"], version=1,
                  price_multiplier_bp=ZONE_B_MULTIPLIER_BP,
                  psychological_rounding=ROUNDING_NONE, tax_rate_bp=ZONE_B_TAX_BP,
                  max_uplift_bp=ZONE_B_MAX_UPLIFT_BP)
    assert_instant_equals(fetched["updated_at"], created["updated_at"], "updated_at")


def test_the_menu_item_collection_paginates_and_filters(api):
    """PRD: "List responses carry `limit`, `offset`, `total_count` and `has_more` inside the `meta` object of the envelope described above."

    Design: Corner/entities/list_menu_items_paginates_with_total_count_and_has_more
    """
    world = World(api)
    world.set_clock(CLOCK_T0)
    burger = world.item(SKU_BURGER, category=CATEGORY_ENTREE, base_price_cents=500)
    fries = world.item(SKU_FRIES, category=CATEGORY_SIDE, base_price_cents=310,
                       contrast_ratio=6.2)
    pie = world.item(SKU_PIE, category=CATEGORY_DESSERT, base_price_cents=200,
                     contrast_ratio=5.4)

    page_one, meta_one = validate_paginated(
        api.list_menu_items(CONTENT_MANAGER, params={"limit": 2, "offset": 0})
    )
    assert len(page_one) == 2
    assert_meta(meta_one, total_count=3, limit=2, offset=0, has_more=True)

    page_two, meta_two = validate_paginated(
        api.list_menu_items(CONTENT_MANAGER, params={"limit": 2, "offset": 2})
    )
    assert len(page_two) == 1
    assert page_two[0]["sku"] == SKU_PIE
    assert_meta(meta_two, total_count=3, limit=2, offset=2, has_more=False)

    assert ids_of(page_one) + ids_of(page_two) == [burger["id"], fries["id"], pie["id"]]

    sides, meta_sides = validate_paginated(
        api.list_menu_items(CONTENT_MANAGER, params={"category": CATEGORY_SIDE})
    )
    assert ids_of(sides) == [fries["id"]]
    assert_meta(meta_sides, total_count=1)


def test_an_unknown_path_identifier_is_a_resource_not_found(api):
    """PRD: "Where a path does carry identifiers, they are resolved **left to right**, and the first identifier that does not resolve to an existing row terminates the request with `ERR_RESOURCE_NOT_FOUND` (HTTP 404)."

    Design: Corner/entities/get_device_with_unknown_id_returns_resource_not_found
    """
    world = World(api)
    world.set_clock(CLOCK_T0)

    response = api.get_device(NON_EXISTENT_UUID, ADMIN)
    assert_envelope(response, "error")
    validate_error(response, ERR_RESOURCE_NOT_FOUND, 404)

    body = response.json()
    assert isinstance(body["data"]["message"], str) and body["data"]["message"]
    assert set(body["data"]) == {"error_id", "message"}, (
        f"an error body echoes no entity fields: {body['data']!r}"
    )


def test_a_store_without_a_price_zone_is_a_malformed_request(api):
    """PRD: "A store is created with a `store_code` of 1 to 12 characters, unique chain-wide, which becomes the prefix of every kitchen order number the store ever prints; a `cluster_id` naming the content cluster whose published bundle drives its boards and kiosks; a `price_zone_id` naming its local price zone; a `timezone_offset_minutes`, the fixed offset from UTC used to convert the logical clock into the store-local minute of day for daypart resolution, which must be at least -720 and at most 840; and an `accessibility_certified_until_utc`, the instant through which the store's kiosk accessibility certification remains valid, inclusive."

    Design: Corner/entities/create_store_missing_price_zone_id_returns_invalid_request
    """
    world = World(api)
    world.set_clock(CLOCK_T0)
    zone = world.zone(ZONE_A_CODE)
    cluster = world.cluster("CL_WEST")

    payload = f.store_payload(cluster["id"], zone["id"], STORE_CODE_S001)
    payload.pop("price_zone_id")
    validate_error(api.create_store(payload, ADMIN), ERR_INVALID_REQUEST, 400)

    rows, meta = validate_paginated(
        api.list_stores(ADMIN, params={"cluster_id": cluster["id"]})
    )
    assert rows == []
    assert_meta(meta, total_count=0)


def test_a_menu_board_takes_every_declared_default(api):
    """PRD: "A new device starts with all four hardware flags — `printer_ok`, `touch_ok`, `screen_reader_ok` and `network_ok` — false, `last_heartbeat_utc` null, `consecutive_missed_heartbeats` at 0, `offline_order_count` at 0, `cached_bundle_id` null with `cached_bundle_version` at 0, `attestation_expiry_utc` null, `p2pe_certified` false, its health dimension `OFFLINE` and its content dimension `MISSING`."

    Design: Corner/entities/register_device_applies_declared_defaults_for_omitted_and_system_fields
    """
    world = World(api)
    world.set_clock(CLOCK_T0)
    zone = world.zone(ZONE_A_CODE)
    cluster = world.cluster("CL_WEST")
    store = world.store(cluster["id"], zone["id"], STORE_CODE_S001)

    payload = f.device_payload(store["id"], DEVICE_CODE_B001, DEVICE_MENU_BOARD,
                               offline_cache_capacity=0)
    assert "pin_pad_firmware_version" not in payload
    board = validate_success(api.register_device(payload, ADMIN), 201)

    assert_fields(board, cache_state=CACHE_MISSING, health_state=HEALTH_OFFLINE,
                  payment_compliance_state=PAYMENT_NOT_APPLICABLE,
                  cached_bundle_version=0, consecutive_missed_heartbeats=0,
                  offline_order_count=0, printer_ok=False, touch_ok=False,
                  screen_reader_ok=False, network_ok=False, p2pe_certified=False)
    assert board["pin_pad_firmware_version"] is None
    assert board["cached_bundle_id"] is None
    assert board["last_heartbeat_utc"] is None
    assert board["attestation_expiry_utc"] is None
    assert world.get_store(store["id"])["content_posture"] == POSTURE_FROZEN


def test_an_availability_row_derives_its_sellable_count_and_bands(api):
    """PRD: "- `available_units` is `on_hand_units` minus `reserved_units`, floored at 0 so it is never negative."

    Design: Corner/entities/create_availability_computes_available_units_and_supply_state
    """
    world = World(api)
    world.set_clock(CLOCK_T0)
    zone = world.zone(ZONE_A_CODE)
    cluster = world.cluster("CL_WEST")
    store = world.store(cluster["id"], zone["id"], STORE_CODE_S001)
    burger = world.item(SKU_BURGER, category=CATEGORY_ENTREE, base_price_cents=500)

    row = validate_success(
        api.create_item_availability(
            store["id"],
            f.availability_payload(burger["id"], on_hand_units=30, par_units=20,
                                   reserved_units=6),
            make_store_operator_headers(store["id"])),
        201,
    )

    assert_fields(row, available_units=24, supply_state=SUPPLY_IN_STOCK,
                  availability_state=AVAIL_AVAILABLE, listing_state=LISTING_LISTED,
                  eighty_six_state=EIGHTY_SIX_NONE)
    assert_instant_equals(row["last_sync_utc"], CLOCK_T0, "last_sync_utc")
    assert world.get_item(burger["id"])["chainwide_availability_state"] == AVAIL_AVAILABLE


def test_a_new_cluster_is_stamped_by_the_server_and_by_the_logical_clock(api):
    """PRD: "`chain_depth` counts the clusters on the inheritance chain including the cluster itself, so a root cluster has a chain depth of 1 and a cluster whose parent is a root has 2; the deepest legal chain is five clusters."

    Design: Corner/entities/create_store_cluster_stamps_system_id_created_at_and_version
    """
    world = World(api)
    world.set_clock(CLOCK_T0)

    cluster = validate_success(
        api.create_store_cluster(f.store_cluster_payload("CL_NATIONAL", tier=TIER_STANDARD),
                                 CONTENT_MANAGER),
        201,
    )

    assert_common_fields(cluster, expect_version=1)
    assert is_valid_uuid(cluster["id"])
    assert_instant_equals(cluster["created_at"], CLOCK_T0, "created_at")
    assert_instant_equals(cluster["updated_at"], CLOCK_T0, "updated_at")
    assert cluster["parent_cluster_id"] is None
    assert_fields(cluster, chain_depth=1, published_bundle_version=0)

    fetched = validate_success(api.get_store_cluster(cluster["id"], CONTENT_MANAGER), 200)
    assert fetched["id"] == cluster["id"]


def test_a_minute_of_day_of_1440_is_outside_the_declared_range(api):
    """PRD: "Minute-of-day values are integers in the range 0 to 1439 inclusive; a value outside that range is a malformed request."

    Design: Corner/entities/daypart_slot_with_end_minute_1440_returns_invalid_request
    """
    world = World(api)
    world.set_clock(CLOCK_T0)
    cluster = world.cluster("CL_WEST")
    bundle = world.bundle(cluster["id"], effective_from_utc="2026-08-05T00:00:00Z")

    def late_slot(end_minute: int):
        return f.daypart_slot_payload(bundle["version"], daypart_code="LATE",
                                      start_minute_of_day=1320, end_minute_of_day=end_minute,
                                      layout_code="LATE_GRID", buffer_minutes=10,
                                      category_codes=[CATEGORY_ENTREE])

    validate_error(api.append_daypart_slot(bundle["id"], late_slot(1440), CONTENT_MANAGER),
                   ERR_INVALID_REQUEST, 400)

    unchanged = world.get_bundle(bundle["id"])
    assert unchanged["daypart_slots"] == []
    assert unchanged["version"] == bundle["version"]
    assert unchanged["state"] == BUNDLE_DRAFT

    accepted = validate_success(
        api.append_daypart_slot(bundle["id"], late_slot(1439), CONTENT_MANAGER),
        200,
    )
    assert len(accepted["daypart_slots"]) == 1
    assert accepted["daypart_slots"][0]["end_minute_of_day"] == 1439


def test_audit_rows_grow_only_and_carry_no_version(api):
    """PRD: "An audit row carries only `id` and `created_at`: it has neither `updated_at` nor `version`, because it is written once and never touched again."

    Design: Corner/entities/audit_events_are_append_only_and_carry_no_version_field
    """
    world = World(api)
    world.set_clock(CLOCK_T0)
    zone = world.zone(ZONE_A_CODE)
    cluster = world.cluster("CL_WEST")
    store = world.store(cluster["id"], zone["id"], STORE_CODE_S001)
    burger = world.item(SKU_BURGER, category=CATEGORY_ENTREE, base_price_cents=500)
    row = world.availability(store["id"], burger["id"], on_hand_units=40, par_units=20)
    validate_success(
        api.item_availability_action(
            row["id"], f.eighty_six_payload(EIGHTY_SIX_UNTIL, eighty_six_reason="Grill down"),
            make_store_operator_headers(store["id"])),
        200,
    )

    rows, meta = validate_paginated(
        api.list_audit_events(COMPLIANCE, params={"subject_kind": SUBJECT_ITEM_AVAILABILITY,
                                                  "subject_id": row["id"]})
    )
    assert meta["total_count"] >= 1
    first = rows[0]
    assert_fields(first, action=AUDIT_ITEM_EIGHTY_SIXED, actor_role=ROLE_STORE_OPERATOR,
                  sequence_no=1, subject_kind=SUBJECT_ITEM_AVAILABILITY, subject_id=row["id"])
    assert [r["sequence_no"] for r in rows] == sorted(r["sequence_no"] for r in rows)
    for audit_row in rows:
        assert_audit_row_shape(audit_row)
        assert audit_row["actor_user_id"], "every row names its actor"
    assert_instant_equals(first["at_utc"], CLOCK_T0, "at_utc")


def test_an_unresolvable_body_foreign_key_is_a_referenced_entity_not_found(api):
    """PRD: "Identifiers arriving in a request **body** are a separate concern: a foreign key that does not resolve is rejected with `ERR_REFERENCED_ENTITY_NOT_FOUND` (HTTP 404), and this covers `price_zone_id`, `cluster_id`, `parent_cluster_id`, `store_id`, `menu_item_id`, `trigger_item_id`, `suggested_item_id`, `cached_bundle_id`, `applied_campaign_version_id`, the `menu_item_id` of every ordered line and every entry of `accepted_upsell_rule_ids`."

    Design: Corner/entities/create_store_with_unknown_cluster_id_returns_referenced_entity_not_found
    """
    world = World(api)
    world.set_clock(CLOCK_T0)
    zone = world.zone(ZONE_A_CODE)

    response = api.create_store(
        f.store_payload(NON_EXISTENT_UUID, zone["id"], STORE_CODE_S001), ADMIN
    )
    validate_error(response, ERR_REFERENCED_ENTITY_NOT_FOUND, 404)

    rows, meta = validate_paginated(api.list_stores(ADMIN))
    assert rows == []
    assert_meta(meta, total_count=0)


def test_a_suggestion_edge_closing_a_cycle_is_rejected(api):
    """PRD: "Within one cluster the suggestion edges from trigger to suggested item must remain **acyclic**, and a rule may not point an item at itself; a rule that would close a cycle in its cluster's active suggestion graph, or whose trigger and suggested items are the same, is refused with `ERR_UPSELL_CYCLE_DETECTED`."

    Design: Corner/entities/upsell_rule_closing_a_suggestion_cycle_is_rejected
    """
    world = World(api)
    world.set_clock(CLOCK_T0)
    cluster = world.cluster("CL_WEST")
    burger = world.item(SKU_BURGER, category=CATEGORY_ENTREE, base_price_cents=500)
    fries = world.item(SKU_FRIES, category=CATEGORY_SIDE, base_price_cents=310,
                       contrast_ratio=6.2)
    pie = world.item(SKU_PIE, category=CATEGORY_DESSERT, base_price_cents=200,
                     contrast_ratio=5.4)

    rule_ab = validate_success(
        api.create_upsell_rule(
            f.upsell_rule_payload(cluster["id"], burger["id"], fries["id"],
                                  rule_kind=RULE_KIND_COMBO, min_cart_subtotal_cents=0,
                                  suggestion_slot=1, max_prompt_seconds=8),
            CONTENT_MANAGER),
        201,
    )
    assert rule_ab["state"] == RULE_ACTIVE
    rule_bc = validate_success(
        api.create_upsell_rule(
            f.upsell_rule_payload(cluster["id"], fries["id"], pie["id"],
                                  rule_kind=RULE_KIND_COMBO, min_cart_subtotal_cents=0,
                                  suggestion_slot=2, max_prompt_seconds=8),
            CONTENT_MANAGER),
        201,
    )

    closing = api.create_upsell_rule(
        f.upsell_rule_payload(cluster["id"], pie["id"], burger["id"],
                              rule_kind=RULE_KIND_COMBO, min_cart_subtotal_cents=0,
                              suggestion_slot=3, max_prompt_seconds=8),
        CONTENT_MANAGER,
    )
    validate_error(closing, ERR_UPSELL_CYCLE_DETECTED, 422)

    rows, meta = validate_paginated(
        api.list_upsell_rules(CONTENT_MANAGER, params={"cluster_id": cluster["id"]})
    )
    assert ids_of(rows) == [rule_ab["id"], rule_bc["id"]]
    assert_meta(meta, total_count=2)
