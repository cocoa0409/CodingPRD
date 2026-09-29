"""Calculation corners: campaign selection, health scoring, rounding, discounts, inheritance."""

import os
import sys
from typing import Any, Dict

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from prd_bench_local_runner.testing import validate_paginated, validate_success  # noqa: E402

from test_helpers import factories as f  # noqa: E402
from test_helpers.assertions import (  # noqa: E402
    assert_audit_action_present,
    assert_audit_money,
    assert_fields,
    assert_money,
    assert_order_totals,
    assert_priced_line,
    override_for_zone,
    snapshot_price,
)
from test_helpers.constants import (  # noqa: E402
    ACTION_APPLY,
    ACTION_APPROVE,
    ACTION_SUBMIT,
    ACTION_WITHDRAW,
    AUDIT_PRICE_OVERRIDE_APPLIED,
    BURGER_BASE_CENTS,
    BURGER_ZONE_A_CENTS,
    CAMPAIGN_ACTIVE,
    CAMPAIGN_EXPIRED,
    CAMPAIGN_SCHEDULED,
    CAMPAIGN_WITHDRAWN,
    CATEGORY_ENTREE,
    CATEGORY_SIDE,
    CLOCK_T0,
    DEVICE_CODE_B001,
    DEVICE_CODE_K001,
    DEVICE_CODE_K002,
    DEVICE_MENU_BOARD,
    DINNER_CODE,
    DINNER_END,
    DINNER_START,
    DISCOUNT_AMOUNT_OFF,
    DISCOUNT_PERCENT_OFF,
    FRIES_BASE_CENTS,
    FRIES_ZONE_A_CENTS,
    HEALTH_DEGRADED,
    HEALTH_ONLINE,
    HEALTH_QUARANTINED,
    LUNCH_CODE,
    LUNCH_END,
    LUNCH_START,
    PAYMENT_NOT_APPLICABLE,
    PCR_APPLIED,
    PCR_APPROVED,
    PHASE_ACTIVE,
    PHASE_FALLBACK,
    ROUNDING_NONE,
    RULE_ACTIVE,
    RULE_KIND_COMBO,
    RULE_KIND_UPSELL,
    SKU_BURGER,
    SKU_COLA,
    SKU_FRIES,
    SKU_PIE,
    STACKING_GROUP_BASE,
    STACKING_GROUP_LOYALTY,
    STATIC_FALLBACK,
    STORE_CODE_S001,
    STORE_CODE_S002,
    SUBJECT_MENU_ITEM,
    TIER_STANDARD,
    TENDER_CARD,
    ZONE_A_CODE,
    ZONE_B_CODE,
    ZONE_B_MAX_UPLIFT_BP,
    ZONE_B_MULTIPLIER_BP,
    ZONE_B_TAX_BP,
)
from test_helpers.fixtures import (  # noqa: E402
    World,
    build_catalogue,
    publish_bundle_with_slot,
)
from test_helpers.test_users import (  # noqa: E402
    ANALYST,
    APPROVER,
    CONTENT_MANAGER,
    make_device_agent_headers,
    make_store_operator_headers,
)

WINDOW_START_AUGUST = "2026-08-01T00:00:00Z"
WINDOW_END_AUGUST = "2026-08-31T00:00:00Z"
WINDOW_START_SEPTEMBER = "2026-09-01T00:00:00Z"
WINDOW_END_SEPTEMBER = "2026-09-10T00:00:00Z"
WEEKEND_START = "2026-08-10T00:00:00Z"
WEEKEND_END = "2026-08-12T00:00:00Z"
ONE_SECOND_AFTER_WEEKEND = "2026-08-12T00:00:01Z"
STORE_LOCAL_NOON = 720


def _store_on_published_content(api) -> Dict[str, Any]:
    """One store in ZONE_A whose cluster has a published ENTREE bundle."""
    world = World(api)
    world.set_clock(CLOCK_T0)
    zone = world.zone(ZONE_A_CODE)
    cluster = world.cluster("CL_WEST")
    store = world.store(cluster["id"], zone["id"], STORE_CODE_S001,
                        timezone_offset_minutes=-300)
    burger = world.item(SKU_BURGER, category=CATEGORY_ENTREE,
                        base_price_cents=BURGER_BASE_CENTS)
    bundle = publish_bundle_with_slot(world, cluster["id"], category_codes=[CATEGORY_ENTREE])
    return {"world": world, "zone": zone, "cluster": cluster, "store": store,
            "burger": burger, "bundle": bundle}


def _projection(api, store_id: str, **params: Any) -> Dict[str, Any]:
    return validate_success(
        api.get_menu_projection(store_id, make_store_operator_headers(store_id),
                                params=f.projection_params(**params) or None),
        200,
    )


def test_the_lowest_priority_rank_wins_across_stacking_groups(api):
    """PRD: "When several qualify, exactly one wins, chosen by `priority_rank` ascending, then by `discount_value` descending, then by creation ascending — stacking is forbidden, and the winner's identifier is stored on the order as `applied_campaign_version_id`."

    Design: Corner/calculations/campaign_selection_picks_the_lowest_priority_rank_across_stacking_groups
    """
    scene = _store_on_published_content(api)
    world, cluster, store = scene["world"], scene["cluster"], scene["store"]

    loyalty = world.campaign("LOYALTY", cluster["id"], WINDOW_START_AUGUST, WINDOW_END_AUGUST,
                             discount_kind=DISCOUNT_PERCENT_OFF, discount_value=1500,
                             stacking_group=STACKING_GROUP_LOYALTY, priority_rank=30)
    loyalty = world.schedule_campaign(loyalty["id"])
    spring = world.campaign("SPRING5", cluster["id"], WINDOW_START_AUGUST, WINDOW_END_AUGUST,
                            discount_kind=DISCOUNT_PERCENT_OFF, discount_value=500,
                            stacking_group=STACKING_GROUP_BASE, priority_rank=10)
    spring = world.schedule_campaign(spring["id"])

    assert_fields(loyalty, state=CAMPAIGN_ACTIVE, pinned_bundle_version=1)
    assert spring["state"] == CAMPAIGN_ACTIVE

    projection = _projection(api, store["id"])
    assert_fields(projection, local_minute_of_day=STORE_LOCAL_NOON, phase=PHASE_ACTIVE)
    assert projection["selected_campaign_version_id"] == spring["id"], (
        "rank 10 outranks rank 30 before the larger discount or the earlier creation is consulted"
    )


def test_only_active_versions_enter_the_candidate_set(api):
    """PRD: "Versions in `DRAFT`, `SCHEDULED`, `EXPIRED`, `WITHDRAWN` or `SUPERSEDED` are excluded even when their window contains the clock."

    Design: Corner/calculations/campaign_selection_excludes_scheduled_and_withdrawn_versions
    """
    scene = _store_on_published_content(api)
    world, cluster, store = scene["world"], scene["cluster"], scene["store"]

    future = world.campaign("FUTURE10", cluster["id"], WINDOW_START_SEPTEMBER,
                            WINDOW_END_SEPTEMBER, discount_kind=DISCOUNT_PERCENT_OFF,
                            discount_value=1000, stacking_group=STACKING_GROUP_BASE,
                            priority_rank=10)
    future = world.schedule_campaign(future["id"])
    assert future["state"] == CAMPAIGN_SCHEDULED, (
        "SCHEDULE does not activate a window that has not opened"
    )

    now_sale = world.campaign("NOWSALE", cluster["id"], WINDOW_START_AUGUST, WINDOW_END_AUGUST,
                              discount_kind=DISCOUNT_PERCENT_OFF, discount_value=800,
                              stacking_group=STACKING_GROUP_LOYALTY, priority_rank=20)
    now_sale = world.schedule_campaign(now_sale["id"])
    assert now_sale["state"] == CAMPAIGN_ACTIVE
    withdrawn = validate_success(
        api.campaign_version_action(now_sale["id"], f.action_payload(ACTION_WITHDRAW),
                                    CONTENT_MANAGER), 200)
    assert withdrawn["state"] == CAMPAIGN_WITHDRAWN

    projection = _projection(api, store["id"])
    assert projection["selected_campaign_version_id"] is None, (
        "the scheduled version is out of window and the withdrawn one is filtered by state"
    )

    rows, _ = validate_paginated(
        api.list_campaign_versions(CONTENT_MANAGER, params={"state": CAMPAIGN_ACTIVE})
    )
    assert rows == []


def test_the_health_weights_and_the_penalty_cap_are_applied_as_declared(api):
    """PRD: "`rolling_health_score` is the base minus 15 points for each miss, where the total penalty is capped at 60 points and the result is floored at 0."

    Design: Corner/calculations/device_health_weights_and_penalty_cap_are_applied_as_declared
    """
    world = World(api)
    world.set_clock(CLOCK_T0)
    zone = world.zone(ZONE_A_CODE)
    cluster = world.cluster("CL_WEST")
    store = world.store(cluster["id"], zone["id"], STORE_CODE_S001,
                        timezone_offset_minutes=-300)
    device = world.device(store["id"], DEVICE_CODE_K001, offline_cache_capacity=2)

    scored = world.heartbeat(device["id"], printer_ok=False)
    assert_fields(scored, rolling_health_score=80, worst_case_health_score=50,
                  health_state=HEALTH_ONLINE)

    advanced = world.set_clock("2026-08-05T17:20:00Z")
    assert advanced["devices_rescored"] == 1

    rescored = world.get_device(device["id"])
    assert_fields(rescored, consecutive_missed_heartbeats=4, rolling_health_score=20,
                  worst_case_health_score=20, health_state=HEALTH_QUARANTINED)


def test_each_zone_rounds_the_snapshot_by_its_own_pinned_rule(api):
    """PRD: "The second step applies the zone's `psychological_rounding` to the basis — **and it applies in both branches, an override included**."

    Design: Corner/calculations/publish_snapshot_rounds_each_zone_by_its_own_pinned_rule
    """
    world = World(api)
    world.set_clock(CLOCK_T0)
    zone_a = world.zone(ZONE_A_CODE)
    zone_b = world.zone(ZONE_B_CODE, price_multiplier_bp=ZONE_B_MULTIPLIER_BP,
                        psychological_rounding=ROUNDING_NONE, tax_rate_bp=ZONE_B_TAX_BP,
                        max_uplift_bp=ZONE_B_MAX_UPLIFT_BP)
    cluster = world.cluster("CL_WEST")
    world.store(cluster["id"], zone_a["id"], STORE_CODE_S001, timezone_offset_minutes=-300)
    world.store(cluster["id"], zone_b["id"], STORE_CODE_S002, timezone_offset_minutes=-300)
    burger = world.item(SKU_BURGER, category=CATEGORY_ENTREE,
                        base_price_cents=BURGER_BASE_CENTS)
    fries = world.item(SKU_FRIES, category=CATEGORY_SIDE, base_price_cents=FRIES_BASE_CENTS,
                       contrast_ratio=6.2)

    published = publish_bundle_with_slot(world, cluster["id"],
                                         category_codes=[CATEGORY_ENTREE, CATEGORY_SIDE])

    assert len(published["price_snapshot"]) == 4, (
        f"two snapshot items across two store zones: {published['price_snapshot']!r}"
    )
    assert_money(snapshot_price(published, burger["id"], zone_a["id"]), 559, "burger in ZONE_A")
    assert_money(snapshot_price(published, fries["id"], zone_a["id"]), 349, "fries in ZONE_A")
    assert_money(snapshot_price(published, burger["id"], zone_b["id"]), 600, "burger in ZONE_B")
    assert_money(snapshot_price(published, fries["id"], zone_b["id"]), 372, "fries in ZONE_B")
    assert published["price_snapshot_checksum"] == published["live_price_checksum"]
    assert published["stale_flag"] is False


def test_an_applied_override_is_still_rounded_but_never_re_multiplied(api):
    """PRD: "If the item carries a `zone_price_overrides` entry for that zone, the basis is that entry's `price_cents`."

    Design: Corner/calculations/applied_override_price_still_takes_the_nine_ending_branch
    """
    world = World(api)
    world.set_clock(CLOCK_T0)
    zone = world.zone(ZONE_A_CODE)
    cluster = world.cluster("CL_ZONE")
    world.store(cluster["id"], zone["id"], STORE_CODE_S001, timezone_offset_minutes=-300)
    burger = world.item(SKU_BURGER, category=CATEGORY_ENTREE,
                        base_price_cents=BURGER_BASE_CENTS)
    assert burger["zone_override_total_cents"] == 0

    live_version = world.get_item(burger["id"])["version"]
    request = world.price_change_request(burger["id"], zone["id"], 580, CLOCK_T0, live_version,
                                        ANALYST, justification="Beef cost")
    assert_money(request["baseline_price_cents"], BURGER_ZONE_A_CENTS, "baseline_price_cents")
    assert_fields(request, uplift_bp=376, required_approvals=1)

    world.pcr_action(request["id"], ACTION_SUBMIT, ANALYST)
    approved = world.pcr_action(request["id"], ACTION_APPROVE, APPROVER, comment="Approved")
    assert approved["state"] == PCR_APPROVED

    applied = validate_success(
        api.price_change_request_action(request["id"], f.action_payload(ACTION_APPLY), ANALYST),
        200,
    )
    assert applied["state"] == PCR_APPLIED
    assert_money(applied["applied_price_cents"], 589, "applied_price_cents")

    item = world.get_item(burger["id"])
    entry = override_for_zone(item, zone["id"])
    assert entry is not None, f"no ZONE_A override on the item: {item['zone_price_overrides']!r}"
    assert_money(entry["price_cents"], 589, "zone_price_overrides price_cents")
    assert_money(item["zone_override_total_cents"], 589, "zone_override_total_cents")

    rows = world.audit(subject_kind=SUBJECT_MENU_ITEM, subject_id=burger["id"],
                       action=AUDIT_PRICE_OVERRIDE_APPLIED)
    assert_audit_money(assert_audit_action_present(rows, AUDIT_PRICE_OVERRIDE_APPLIED)[0],
                       BURGER_ZONE_A_CENTS, 589)


def test_a_cash_discount_is_capped_at_the_line_and_zeroes_the_tax(api):
    """PRD: "and the smaller of the campaign's `discount_value` multiplied by the line's `qty` and the gross line amount when the kind is `AMOUNT_OFF` — a per-unit cash discount is capped at the line it discounts and can never push a line negative."

    Design: Corner/calculations/amount_off_discount_is_capped_at_the_line_and_zeroes_the_tax
    """
    world = World(api)
    world.set_clock(CLOCK_T0)
    zone = world.zone(ZONE_A_CODE)
    cluster = world.cluster("CL_WEST")
    store = world.store(cluster["id"], zone["id"], STORE_CODE_S001,
                        timezone_offset_minutes=-300)
    fries = world.item(SKU_FRIES, category=CATEGORY_SIDE, base_price_cents=FRIES_BASE_CENTS,
                       contrast_ratio=6.2)
    row = world.availability(store["id"], fries["id"], on_hand_units=40, par_units=20)
    bundle = publish_bundle_with_slot(world, cluster["id"], category_codes=[CATEGORY_SIDE])

    campaign = world.campaign("BIGCUT", cluster["id"], WINDOW_START_AUGUST, WINDOW_END_AUGUST,
                              discount_kind=DISCOUNT_AMOUNT_OFF, discount_value=1000,
                              stacking_group=STACKING_GROUP_BASE, priority_rank=10)
    campaign = world.schedule_campaign(campaign["id"])
    assert campaign["state"] == CAMPAIGN_ACTIVE

    device = world.device(store["id"], DEVICE_CODE_K001, offline_cache_capacity=2)
    world.attest(device["id"])
    world.heartbeat(device["id"])
    device = world.cache_sync(device["id"], bundle["id"])
    assert device["cached_bundle_version"] == 1

    order = validate_success(
        api.create_order(device["id"],
                         f.order_payload([f.line(fries["id"], 1)], tender_kind=TENDER_CARD),
                         make_device_agent_headers(device["id"])),
        201,
    )

    assert_order_totals(order, FRIES_ZONE_A_CENTS, FRIES_ZONE_A_CENTS, 0, 0)
    assert_fields(order, order_number="S001-0001", daypart_code=LUNCH_CODE,
                  applied_campaign_version_id=campaign["id"])
    assert_priced_line(order["priced_lines"][0], fries["id"], 1, FRIES_ZONE_A_CENTS,
                       FRIES_ZONE_A_CENTS, FRIES_ZONE_A_CENTS)

    reserved = validate_success(
        api.get_item_availability(row["id"], make_store_operator_headers(store["id"])), 200)
    assert_fields(reserved, reserved_units=1, available_units=39)


def test_a_child_slot_shadows_the_ancestor_slot_of_the_same_daypart_code(api):
    """PRD: "A nearer cluster's slot therefore **shadows** an ancestor's slot bearing the same daypart code, while an ancestor's slot with a code the child never declared is additive."

    Design: Corner/calculations/child_cluster_slot_shadows_the_ancestor_slot_of_the_same_daypart_code
    """
    world = World(api)
    world.set_clock(CLOCK_T0)
    zone = world.zone(ZONE_A_CODE)
    national = world.cluster("CL_NATL", tier=TIER_STANDARD)
    west = world.cluster("CL_WEST", parent_cluster_id=national["id"], tier=TIER_STANDARD)
    assert west["chain_depth"] == 2, "a cluster whose parent is a root has a chain depth of 2"
    store = world.store(west["id"], zone["id"], STORE_CODE_S001, timezone_offset_minutes=-300)
    world.item(SKU_BURGER, category=CATEGORY_ENTREE, base_price_cents=BURGER_BASE_CENTS)

    national_bundle = world.bundle(national["id"])
    national_bundle = world.slot(national_bundle["id"], national_bundle["version"],
                                 daypart_code=LUNCH_CODE, start_minute_of_day=LUNCH_START,
                                 end_minute_of_day=LUNCH_END, layout_code="NATL_LUNCH",
                                 category_codes=[CATEGORY_ENTREE])
    national_bundle = world.slot(national_bundle["id"], national_bundle["version"],
                                 daypart_code=DINNER_CODE, start_minute_of_day=DINNER_START,
                                 end_minute_of_day=DINNER_END, layout_code="NATL_DINNER",
                                 category_codes=[CATEGORY_ENTREE])
    world.audit_pass(national_bundle["id"])
    world.validate(national_bundle["id"])
    assert world.publish(national_bundle["id"])["bundle_version"] == 1

    west_bundle = world.bundle(west["id"])
    west_bundle = world.slot(west_bundle["id"], west_bundle["version"], daypart_code=LUNCH_CODE,
                             start_minute_of_day=690, end_minute_of_day=900,
                             layout_code="WEST_LUNCH", category_codes=[CATEGORY_ENTREE])
    world.audit_pass(west_bundle["id"])
    world.validate(west_bundle["id"])
    assert world.publish(west_bundle["id"])["bundle_version"] == 1, (
        "each cluster keeps its own bundle_version counter"
    )

    at_noon = _projection(api, store["id"])
    assert_fields(at_noon, local_minute_of_day=STORE_LOCAL_NOON, daypart_code=LUNCH_CODE,
                  layout_code="WEST_LUNCH", phase=PHASE_ACTIVE)

    at_920 = _projection(api, store["id"], at_minute_of_day=920)
    assert at_920["daypart_code"] is None, (
        "the shadowed ancestor LUNCH slot never entered the candidate set"
    )
    assert_fields(at_920, layout_code=STATIC_FALLBACK, phase=PHASE_FALLBACK)

    at_1000 = _projection(api, store["id"], at_minute_of_day=1000)
    assert_fields(at_1000, daypart_code=DINNER_CODE, layout_code="NATL_DINNER",
                  phase=PHASE_ACTIVE, resolved_bundle_version=1)


def test_a_menu_board_is_awarded_the_printer_and_touch_components(api):
    """PRD: "A menu board is awarded the printer's 20 points and the touch panel's 30 points **unconditionally**, because it has neither; a kiosk earns each of them only when the corresponding flag is true."

    Design: Corner/calculations/menu_board_kind_is_awarded_the_printer_and_touch_components_unconditionally
    """
    world = World(api)
    world.set_clock(CLOCK_T0)
    zone = world.zone(ZONE_A_CODE)
    cluster = world.cluster("CL_WEST")
    store = world.store(cluster["id"], zone["id"], STORE_CODE_S001,
                        timezone_offset_minutes=-300)

    board = world.device(store["id"], DEVICE_CODE_B001, device_kind=DEVICE_MENU_BOARD,
                         offline_cache_capacity=1)
    assert board["payment_compliance_state"] == PAYMENT_NOT_APPLICABLE
    kiosk = world.device(store["id"], DEVICE_CODE_K002, offline_cache_capacity=2)

    board_scored = world.heartbeat(board["id"], printer_ok=False, touch_ok=False)
    assert_fields(board_scored, rolling_health_score=100, worst_case_health_score=70,
                  health_state=HEALTH_ONLINE)

    kiosk_scored = world.heartbeat(kiosk["id"], printer_ok=False, touch_ok=False)
    assert_fields(kiosk_scored, rolling_health_score=50, worst_case_health_score=20,
                  health_state=HEALTH_DEGRADED)
    assert kiosk_scored["health_state"] != HEALTH_QUARANTINED, (
        "a missed count of 0 is below the quarantine floor whatever the worst case says"
    )


def test_a_screen_reader_device_tightens_the_suggestion_cap_to_two(api):
    """PRD: "Finally the list is capped: a device reporting a working screen-reader subsystem receives at most 2 suggestions, and any other device receives at most 3."

    Design: Corner/calculations/screen_reader_device_tightens_the_upsell_suggestion_cap_to_two
    """
    world = World(api)
    world.set_clock(CLOCK_T0)
    zone = world.zone(ZONE_A_CODE)
    cluster = world.cluster("CL_WEST")
    store = world.store(cluster["id"], zone["id"], STORE_CODE_S001,
                        timezone_offset_minutes=-300)
    items = build_catalogue(world)
    burger, fries, pie, cola = (items[SKU_BURGER], items[SKU_FRIES], items[SKU_PIE],
                                items[SKU_COLA])
    for suggested in (fries, pie, cola):
        world.availability(store["id"], suggested["id"], on_hand_units=40, par_units=20)
    publish_bundle_with_slot(world, cluster["id"])

    first = world.upsell_rule(cluster["id"], burger["id"], fries["id"], suggestion_slot=1,
                              rule_kind=RULE_KIND_COMBO, max_prompt_seconds=20)
    assert first["state"] == RULE_ACTIVE
    second = world.upsell_rule(cluster["id"], burger["id"], pie["id"], suggestion_slot=2,
                               rule_kind=RULE_KIND_UPSELL, max_prompt_seconds=20)
    third = world.upsell_rule(cluster["id"], burger["id"], cola["id"], suggestion_slot=3,
                              rule_kind=RULE_KIND_UPSELL, max_prompt_seconds=20)

    device = world.device(store["id"], DEVICE_CODE_K001, offline_cache_capacity=2)
    heartbeat = world.heartbeat(device["id"])
    assert heartbeat["screen_reader_ok"] is True

    without_device = _projection(api, store["id"], cart_item_ids=[burger["id"]])
    assert without_device["suggested_upsell_rule_ids"] == [first["id"], second["id"],
                                                          third["id"]]

    with_device = _projection(api, store["id"], cart_item_ids=[burger["id"]],
                              device_id=device["id"])
    assert with_device["suggested_upsell_rule_ids"] == [first["id"], second["id"]], (
        "the third slot is truncated by the accessibility cap, not reordered"
    )


def test_a_campaign_survives_its_closing_instant_and_expires_one_second_later(api):
    """PRD: "An `ACTIVE` version moves to the terminal `EXPIRED` state only once the clock advances **strictly** past `window_end_utc` — at exactly `window_end_utc` the version is still active and still discounts orders — recording `CAMPAIGN_EXPIRED`."

    Design: Corner/calculations/campaign_activates_at_window_start_and_survives_the_closing_instant
    """
    scene = _store_on_published_content(api)
    world, cluster = scene["world"], scene["cluster"]

    campaign = world.campaign("WEEKEND", cluster["id"], WEEKEND_START, WEEKEND_END,
                              discount_kind=DISCOUNT_PERCENT_OFF, discount_value=500,
                              stacking_group=STACKING_GROUP_BASE, priority_rank=10)
    campaign = world.schedule_campaign(campaign["id"])
    assert campaign["state"] == CAMPAIGN_SCHEDULED

    def state_now() -> str:
        return validate_success(api.get_campaign_version(campaign["id"], CONTENT_MANAGER),
                                200)["state"]

    opened = world.set_clock(WEEKEND_START)
    assert opened["campaign_versions_advanced"] == 1
    assert state_now() == CAMPAIGN_ACTIVE, "the window is closed on the left"

    at_close = world.set_clock(WEEKEND_END)
    assert at_close["campaign_versions_advanced"] == 0
    assert state_now() == CAMPAIGN_ACTIVE, "the closing instant still discounts orders"

    after_close = world.set_clock(ONE_SECOND_AFTER_WEEKEND)
    assert after_close["campaign_versions_advanced"] == 1
    assert state_now() == CAMPAIGN_EXPIRED
