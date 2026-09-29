"""Two prices for one item at one instant, and two health scores on one device row."""

import os
import sys
from typing import Any, Dict

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from prd_bench_local_runner.testing import validate_success  # noqa: E402

from test_helpers import factories as f  # noqa: E402
from test_helpers.assertions import (  # noqa: E402
    assert_fields,
    assert_money,
    assert_order_totals,
    assert_priced_line,
    override_for_zone,
    projection_item,
    snapshot_price,
)
from test_helpers.constants import (  # noqa: E402
    ACTION_APPLY,
    ACTION_APPROVE,
    ACTION_SUBMIT,
    CATEGORY_ENTREE,
    CATEGORY_SIDE,
    CLOCK_T0,
    DEVICE_CODE_K001,
    HEALTH_ONLINE,
    HEALTH_QUARANTINED,
    PCR_APPLIED,
    SKU_BURGER,
    SKU_FRIES,
    STORE_CODE_S001,
    TENDER_CARD,
    ZONE_A_CODE,
)
from test_helpers.fixtures import World, publish_bundle_with_slot  # noqa: E402
from test_helpers.test_users import (  # noqa: E402
    ADMIN,
    ANALYST,
    APPROVER,
    APPROVER_2,
    make_device_agent_headers,
    make_store_operator_headers,
)

BURGER_BOARD_CENTS = 559
BURGER_OVERRIDE_CENTS = 599


def _applied_override_scenario(api) -> Dict[str, Any]:
    """Publish a bundle at board price 559, then apply an override of 599 to the live item."""
    world = World(api)
    world.set_clock(CLOCK_T0)
    zone = world.zone(ZONE_A_CODE)
    cluster = world.cluster("CL_WEST")
    store = world.store(cluster["id"], zone["id"], STORE_CODE_S001)
    burger = world.item(SKU_BURGER, category=CATEGORY_ENTREE, base_price_cents=500)
    fries = world.item(SKU_FRIES, category=CATEGORY_SIDE, base_price_cents=310)
    bundle = publish_bundle_with_slot(world, cluster["id"],
                                     category_codes=[CATEGORY_ENTREE, CATEGORY_SIDE])
    world.availability(store["id"], burger["id"])
    device = world.device(store["id"], DEVICE_CODE_K001)
    world.attest(device["id"])
    world.heartbeat(device["id"])
    device = world.cache_sync(device["id"], bundle["id"])

    live_version = world.get_item(burger["id"])["version"]
    pcr = world.price_change_request(burger["id"], zone["id"], 590, CLOCK_T0, live_version,
                                    ANALYST, justification="Beef cost increase Q3")
    world.pcr_action(pcr["id"], ACTION_SUBMIT, ANALYST)
    world.pcr_action(pcr["id"], ACTION_APPROVE, APPROVER, comment="First approval")
    world.pcr_action(pcr["id"], ACTION_APPROVE, APPROVER_2, comment="Second approval")
    applied = world.pcr_action(pcr["id"], ACTION_APPLY, ANALYST)
    return {
        "world": world,
        "zone": zone,
        "cluster": cluster,
        "store": store,
        "burger": burger,
        "fries": fries,
        "bundle": bundle,
        "device": device,
        "pcr": applied,
    }


def test_board_display_price_is_read_from_the_frozen_snapshot(api):
    """PRD: "The **board display price** — the price a menu board renders and the projection returns — is read back out of that frozen snapshot, so a price change applied after publication does **not** move it."

    Design: Difficulty/dual_variant_calc/board_snapshot_price_versus_kiosk_charge_price
    """
    scene = _applied_override_scenario(api)
    store, burger, device = scene["store"], scene["burger"], scene["device"]

    response = api.get_menu_projection(store["id"], make_store_operator_headers(store["id"]),
                                       params=f.projection_params(device_id=device["id"]))
    projection = validate_success(response, 200)

    entry = projection_item(projection, burger["id"])
    assert entry is not None, f"burger missing from the projection: {projection.get('items')}"
    assert_money(entry.get("price_cents"), BURGER_BOARD_CENTS, "board display price")
    assert projection["stale_prices"] is True, (
        "the projection must warn that kiosks will charge something else"
    )

    bundle = validate_success(api.get_content_bundle(scene["bundle"]["id"], ADMIN), 200)
    assert snapshot_price(bundle, burger["id"], scene["zone"]["id"]) == BURGER_BOARD_CENTS


def test_kiosk_charge_price_is_recomputed_from_live_item_data(api):
    """PRD: "The **kiosk charge price** — the unit price of an order line — is recomputed from live item data at the moment the order is captured, so it diverges from the board display price for exactly those items whose zone price changed after the device's cached bundle was published."

    Design: Difficulty/dual_variant_calc/board_snapshot_price_versus_kiosk_charge_price
    """
    scene = _applied_override_scenario(api)
    burger, device = scene["burger"], scene["device"]

    assert scene["pcr"]["state"] == PCR_APPLIED
    item = validate_success(api.get_menu_item(burger["id"], ADMIN), 200)
    entry = override_for_zone(item, scene["zone"]["id"])
    assert entry is not None, "the applied request must have written a zone override"
    assert_money(entry["price_cents"], BURGER_OVERRIDE_CENTS, "override price_cents")

    response = api.create_order(
        device["id"],
        f.order_payload([f.line(burger["id"], 1)], tender_kind=TENDER_CARD),
        make_device_agent_headers(device["id"]),
    )
    order = validate_success(response, 201)

    assert_priced_line(order["priced_lines"][0], burger["id"], 1,
                       unit_price_cents=BURGER_OVERRIDE_CENTS,
                       gross_line_cents=BURGER_OVERRIDE_CENTS, line_discount_cents=0)
    assert_order_totals(order, subtotal_cents=599, discount_cents=0, tax_cents=52, total_cents=651)
    assert order["priced_lines"][0]["unit_price_cents"] - BURGER_BOARD_CENTS == 40, (
        "the two variants must differ for the same item at the same instant"
    )


def _one_heartbeat_with_a_failed_printer(api) -> Dict[str, Any]:
    world = World(api)
    world.set_clock(CLOCK_T0)
    zone = world.zone(ZONE_A_CODE)
    cluster = world.cluster("CL_WEST")
    store = world.store(cluster["id"], zone["id"], STORE_CODE_S001)
    device = world.device(store["id"], DEVICE_CODE_K001)
    world.heartbeat(device["id"], printer_ok=False)
    return {"world": world, "store": store, "device": device}


def test_rolling_and_worst_case_scores_disagree_on_one_device_row(api):
    """PRD: "`worst_case_health_score` is computed from the same base and the same data but charges **two additional** hypothetical misses, again with the 60-point penalty cap and the floor at 0."

    Design: Difficulty/dual_variant_calc/rolling_versus_worst_case_device_health_score
    """
    scene = _one_heartbeat_with_a_failed_printer(api)

    device = validate_success(api.get_device(scene["device"]["id"], ADMIN), 200)

    assert_fields(device,
                  consecutive_missed_heartbeats=0,
                  rolling_health_score=80,
                  worst_case_health_score=50)


def test_the_rolling_score_bands_the_device_and_quarantine_is_withheld(api):
    """PRD: "Otherwise, a device whose missed count has reached 3 **and** whose `worst_case_health_score` is below 50 is `QUARANTINED`."

    Design: Difficulty/dual_variant_calc/rolling_versus_worst_case_device_health_score
    """
    scene = _one_heartbeat_with_a_failed_printer(api)

    device = validate_success(api.get_device(scene["device"]["id"], ADMIN), 200)

    assert device["health_state"] == HEALTH_ONLINE, (
        f"rolling 80 must band the kiosk ONLINE, got {device['health_state']!r}"
    )
    assert device["health_state"] != HEALTH_QUARANTINED
    assert device["consecutive_missed_heartbeats"] == 0
    assert device["worst_case_health_score"] == 50, (
        "the worst-case measure is consulted for quarantine only"
    )
