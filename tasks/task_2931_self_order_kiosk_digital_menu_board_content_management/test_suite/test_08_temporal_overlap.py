"""Half-open daypart intervals may touch; closed campaign windows may not."""

import os
import sys
from typing import Any, Dict

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from prd_bench_local_runner.testing import validate_error, validate_success  # noqa: E402

from test_helpers import factories as f  # noqa: E402
from test_helpers.api_errors import (  # noqa: E402
    ERR_CAMPAIGN_WINDOW_CONFLICT,
    ERR_DAYPART_SLOT_OVERLAP,
)
from test_helpers.assertions import assert_fields  # noqa: E402
from test_helpers.constants import (  # noqa: E402
    ACTION_SCHEDULE,
    BUNDLE_DRAFT,
    CAMPAIGN_DRAFT,
    CAMPAIGN_SCHEDULED,
    CATEGORY_ENTREE,
    CATEGORY_SIDE,
    CLOCK_T0,
    DINNER_CODE,
    DINNER_END,
    DINNER_LAYOUT,
    DINNER_START,
    DISCOUNT_AMOUNT_OFF,
    DISCOUNT_PERCENT_OFF,
    LUNCH_CODE,
    SKU_BURGER,
    STACKING_GROUP_BASE,
    STACKING_GROUP_LOYALTY,
    STORE_CODE_S001,
    ZONE_A_CODE,
)
from test_helpers.fixtures import World, publish_bundle_with_slot  # noqa: E402
from test_helpers.test_users import CONTENT_MANAGER  # noqa: E402

SUMMER_START = "2026-08-10T00:00:00Z"
SHARED_INSTANT = "2026-08-20T00:00:00Z"
AUTUMN_END = "2026-08-25T00:00:00Z"
AUTUMN_START_MOVED = "2026-08-20T00:01:00Z"


def _draft_bundle_with_a_lunch_slot(api) -> Dict[str, Any]:
    world = World(api)
    world.set_clock(CLOCK_T0)
    zone = world.zone(ZONE_A_CODE)
    cluster = world.cluster("CL_WEST")
    world.store(cluster["id"], zone["id"], STORE_CODE_S001)
    world.item(SKU_BURGER, category=CATEGORY_ENTREE, base_price_cents=500)
    bundle = world.bundle(cluster["id"])
    bundle = world.slot(bundle["id"], bundle["version"], category_codes=[CATEGORY_ENTREE])
    return {"world": world, "bundle": bundle}


def _append_dinner(api, bundle: Dict[str, Any]):
    return api.append_daypart_slot(
        bundle["id"],
        f.daypart_slot_payload(bundle["version"], daypart_code=DINNER_CODE,
                              start_minute_of_day=DINNER_START, end_minute_of_day=DINNER_END,
                              layout_code=DINNER_LAYOUT, buffer_minutes=20,
                              category_codes=[CATEGORY_ENTREE]),
        CONTENT_MANAGER,
    )


def test_a_slot_starting_exactly_where_another_ends_is_accepted(api):
    """PRD: "The interval is half-open, so a slot running from 600 to 900 covers minute 899 but not minute 900, and two slots of the same bundle must not overlap; an overlapping interval, or one whose start is not strictly below its end, is refused with `ERR_DAYPART_SLOT_OVERLAP`."

    Design: Difficulty/resource_temporal_overlap/daypart_slot_half_open_adjacency_allowed_but_straddle_rejected
    """
    scene = _draft_bundle_with_a_lunch_slot(api)
    bundle = scene["bundle"]

    response = _append_dinner(api, bundle)
    assert response.status_code in (200, 201), (
        f"touching at minute 960 is legal, got HTTP {response.status_code}: {response.text}"
    )
    after = validate_success(response, response.status_code)

    assert after["version"] == bundle["version"] + 1
    assert [slot["daypart_code"] for slot in after["daypart_slots"]] == [LUNCH_CODE, DINNER_CODE]


def test_a_slot_straddling_two_neighbours_is_refused_without_bumping_the_version(api):
    """PRD: "Daypart geometry — a new slot's half-open interval does not overlap an existing slot of the same bundle and its start is strictly below its end → `ERR_DAYPART_SLOT_OVERLAP` (409)."

    Design: Difficulty/resource_temporal_overlap/daypart_slot_half_open_adjacency_allowed_but_straddle_rejected
    """
    scene = _draft_bundle_with_a_lunch_slot(api)
    world = scene["world"]
    response = _append_dinner(api, scene["bundle"])
    after_dinner_version = validate_success(response, response.status_code)["version"]

    straddle = api.append_daypart_slot(
        scene["bundle"]["id"],
        f.daypart_slot_payload(after_dinner_version, daypart_code="SNACK",
                               start_minute_of_day=900, end_minute_of_day=1000,
                               layout_code="SNACK_GRID", buffer_minutes=10,
                               category_codes=[CATEGORY_SIDE]),
        CONTENT_MANAGER,
    )
    validate_error(straddle, ERR_DAYPART_SLOT_OVERLAP, 409)

    final = world.get_bundle(scene["bundle"]["id"])
    assert final["version"] == after_dinner_version, "the rejected append must not bump the version"
    assert [slot["daypart_code"] for slot in final["daypart_slots"]] == [LUNCH_CODE, DINNER_CODE]
    assert final["state"] == BUNDLE_DRAFT


def _cluster_with_a_scheduled_summer_campaign(api) -> Dict[str, Any]:
    world = World(api)
    world.set_clock(CLOCK_T0)
    zone = world.zone(ZONE_A_CODE)
    cluster = world.cluster("CL_WEST")
    world.store(cluster["id"], zone["id"], STORE_CODE_S001)
    world.item(SKU_BURGER, category=CATEGORY_ENTREE, base_price_cents=500)
    publish_bundle_with_slot(world, cluster["id"], category_codes=[CATEGORY_ENTREE])

    summer = world.campaign("SUMMER15", cluster["id"], SUMMER_START, SHARED_INSTANT,
                            discount_kind=DISCOUNT_PERCENT_OFF, discount_value=1500,
                            stacking_group=STACKING_GROUP_BASE, priority_rank=10)
    summer = world.schedule_campaign(summer["id"])
    autumn = world.campaign("AUTUMN10", cluster["id"], SHARED_INSTANT, AUTUMN_END,
                            discount_kind=DISCOUNT_PERCENT_OFF, discount_value=1000,
                            stacking_group=STACKING_GROUP_BASE, priority_rank=20)
    return {"world": world, "cluster": cluster, "summer": summer, "autumn": autumn}


def test_two_closed_windows_sharing_one_instant_conflict(api):
    """PRD: "And no other version of the same cluster and the same `stacking_group` whose state is `SCHEDULED` or `ACTIVE` may have a closed window that intersects this one, because at most **one** version per cluster and stacking group may occupy any single instant; an intersection is refused with `ERR_CAMPAIGN_WINDOW_CONFLICT`."

    Design: Difficulty/resource_temporal_overlap/campaign_windows_closed_intervals_conflict_on_shared_endpoint
    """
    scene = _cluster_with_a_scheduled_summer_campaign(api)
    summer, autumn = scene["summer"], scene["autumn"]

    assert_fields(summer, state=CAMPAIGN_SCHEDULED, pinned_bundle_version=1)

    response = api.campaign_version_action(autumn["id"], f.action_payload(ACTION_SCHEDULE),
                                           CONTENT_MANAGER)
    validate_error(response, ERR_CAMPAIGN_WINDOW_CONFLICT, 409)

    assert validate_success(api.get_campaign_version(autumn["id"], CONTENT_MANAGER),
                            200)["state"] == CAMPAIGN_DRAFT
    assert validate_success(api.get_campaign_version(summer["id"], CONTENT_MANAGER),
                            200)["state"] == CAMPAIGN_SCHEDULED


def test_the_conflict_is_scoped_to_the_stacking_group_and_to_a_shared_instant(api):
    """PRD: "Campaign stacking — scheduling a version whose closed window intersects that of another scheduled or active version in the same stacking group of the same cluster → `ERR_CAMPAIGN_WINDOW_CONFLICT` (409)."

    Design: Difficulty/resource_temporal_overlap/campaign_windows_closed_intervals_conflict_on_shared_endpoint
    """
    scene = _cluster_with_a_scheduled_summer_campaign(api)
    world, cluster = scene["world"], scene["cluster"]

    validate_error(
        api.campaign_version_action(scene["autumn"]["id"], f.action_payload(ACTION_SCHEDULE),
                                    CONTENT_MANAGER),
        ERR_CAMPAIGN_WINDOW_CONFLICT, 409,
    )

    loyalty = world.campaign("LOYALTY5", cluster["id"], SHARED_INSTANT, AUTUMN_END,
                             discount_kind=DISCOUNT_AMOUNT_OFF, discount_value=100,
                             stacking_group=STACKING_GROUP_LOYALTY, priority_rank=30)
    loyalty = validate_success(
        api.campaign_version_action(loyalty["id"], f.action_payload(ACTION_SCHEDULE),
                                    CONTENT_MANAGER), 200)
    assert loyalty["state"] == CAMPAIGN_SCHEDULED, (
        "an identical window in another stacking group does not intersect"
    )

    autumn_v2 = world.campaign("AUTUMN10", cluster["id"], AUTUMN_START_MOVED, AUTUMN_END,
                               version_no=2, discount_kind=DISCOUNT_PERCENT_OFF,
                               discount_value=1000, stacking_group=STACKING_GROUP_BASE,
                               priority_rank=20)
    autumn_v2 = validate_success(
        api.campaign_version_action(autumn_v2["id"], f.action_payload(ACTION_SCHEDULE),
                                    CONTENT_MANAGER), 200)
    assert autumn_v2["state"] == CAMPAIGN_SCHEDULED, (
        "moving the start one minute later removes the only shared instant"
    )
