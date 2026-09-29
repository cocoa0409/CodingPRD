"""Route-commitment window arithmetic and the compensating inverses of the ledger.

Two families of rules are pinned here. First, the two reservations a commitment
takes out: the driver's occupied interval, which runs from the planned departure
through the modelled return plus the store's reset buffer and is closed at both
ends, and the store's hot-bag reservation window, which runs from the planned
departure inclusive to the modelled return exclusive. Each is pinned by a pair of
locks placed on either side of the same boundary instant, so the open end and the
closed end are told apart rather than assumed. Second, the operations the
specification defines as exact compensating inverses — voiding a safe drop,
releasing a stop, and clawing back a chargeable stop line — together with the
part of each inverse that is deliberately not symmetric: an ordinal is never
reused, and a clawback moves the accrual by exactly one stop's line.
"""

import pytest

from prd_bench_local_runner.testing import (
    validate_error,
    validate_paginated,
    validate_success,
)

from test_helpers import api_client
from test_helpers.api_errors import ApiErrorId
from test_helpers import assertions as a
from test_helpers import factories as f
from test_helpers import fixtures as fx
from test_helpers.constants import CAR_COST_MODEL, NOON_CLOCK, TEST_ZONE_MODEL
from test_helpers.test_users import DISPATCHER_HEADERS, make_manager_headers

# The store policy the scenarios below depend on arithmetically: four bag slots,
# a six-minute curbside allowance at each door and a ten-minute recovery buffer
# appended to the driver's occupied interval.
STORE_POLICY = {
    "hot_bag_count": 4,
    "max_stacked_stops": 3,
    "handoff_minutes_per_stop": 6,
    "dispatch_reset_buffer_minutes": 10,
    "cash_limit_cents": 5000,
}

MINUTES_PER_MILE = TEST_ZONE_MODEL["minutes_per_mile"]
HANDOFF_MINUTES = STORE_POLICY["handoff_minutes_per_stop"]
RESET_BUFFER_MINUTES = STORE_POLICY["dispatch_reset_buffer_minutes"]

# Both shared addresses used below sit 3.00 grid miles from the store origin.
STOP_MILES = 3.00
EVENING_DEPART_AT = "2026-08-05T18:00:00Z"


def _ledger_lines(store_id, driver_id):
    """Every ledger line of one driver, read by the owning store's manager."""
    data, _meta = validate_paginated(
        api_client.list_reimbursement_lines(
            make_manager_headers(store_id), {"driver_id": driver_id, "limit": 100}
        )
    )
    return data


def test_second_route_of_the_same_driver_at_the_closed_interval_end_is_refused():
    """A lock whose departure lands exactly on the prior route's return plus the reset buffer is refused.

    PRD: "The driver's occupied interval for this route — from `planned_depart_at` through `expected_return_at` plus the store's `dispatch_reset_buffer_minutes`, closed at both ends — must not intersect the same interval of any other route of the **same driver** whose status is `LOCKED` or `EN_ROUTE`, or the commitment is refused with `ERR_DRIVER_WINDOW_CONFLICT`."
    Design: Difficulty/resource_temporal_overlap/driver_occupation_interval_is_closed_so_touching_at_1834_conflicts
    """
    world = fx.setup_locked_route(
        ("A",),
        planned_depart_at=EVENING_DEPART_AT,
        hot_bag_slots=[1],
        store_overrides=dict(STORE_POLICY),
    )
    store_id = world["store"]["id"]
    driver_id = world["driver"]["id"]

    first = fx.read_dispatch(world["dispatch"]["id"])
    # One 3.00-mile stop: nine minutes out, six at the door, nine home again.
    assert first["route_minutes"] == a.expected_route_minutes(
        [STOP_MILES], MINUTES_PER_MILE, HANDOFF_MINUTES
    )
    assert first["route_minutes"] == 24
    a.assert_iso_millis(first["expected_return_at"], "expected_return_at")
    assert a.parse_instant(first["expected_return_at"]) == a.parse_instant(
        "2026-08-05T18:24:00Z"
    )

    # The closed upper end of the occupied interval, read off the committed route.
    boundary = a.instant_plus(first["expected_return_at"], minutes=RESET_BUFFER_MINUTES)
    assert boundary == "2026-08-05T18:34:00Z"

    second_address = fx.add_address(store_id, "A2")
    second_order = fx.add_ready_order(store_id, second_address["id"])
    second = fx.open_dispatch(driver_id, boundary)
    fx.stack_stop(second["id"], second_order["id"], 1)

    validate_error(
        api_client.lock_dispatch(second["id"], DISPATCHER_HEADERS),
        ApiErrorId.ERR_DRIVER_WINDOW_CONFLICT.value,
    )

    refused = fx.read_dispatch(second["id"])
    assert refused["status"] == "STACKED"
    assert refused["route_minutes"] is None
    assert refused["expected_return_at"] is None
    assert refused["resolved_cost_model_id"] is None
    assert refused["estimated_reimbursement_cents"] is None
    assert refused["committed_hot_bag_slots"] == 1
    assert fx.read_dispatch(first["id"])["status"] == "LOCKED"


def test_second_route_of_the_same_driver_one_minute_past_the_buffer_commits():
    """A lock one whole minute past the reset buffer clears the occupied interval and prices normally.

    PRD: "Back-to-back routes for the same driver must therefore leave the reset buffer plus at least one whole minute between them."
    Design: Difficulty/resource_temporal_overlap/driver_occupation_interval_is_closed_so_touching_at_1834_conflicts
    """
    world = fx.setup_locked_route(
        ("A",),
        planned_depart_at=EVENING_DEPART_AT,
        hot_bag_slots=[1],
        store_overrides=dict(STORE_POLICY),
    )
    store_id = world["store"]["id"]
    driver_id = world["driver"]["id"]

    first = fx.read_dispatch(world["dispatch"]["id"])
    assert first["route_minutes"] == 24
    boundary = a.instant_plus(first["expected_return_at"], minutes=RESET_BUFFER_MINUTES)
    just_clear = a.instant_plus(boundary, minutes=1)
    assert just_clear == "2026-08-05T18:35:00Z"

    second_address = fx.add_address(store_id, "A2")
    second_order = fx.add_ready_order(store_id, second_address["id"])
    second = fx.open_dispatch(driver_id, just_clear)
    fx.stack_stop(second["id"], second_order["id"], 1)

    committed = validate_success(
        api_client.lock_dispatch(second["id"], DISPATCHER_HEADERS), 200
    )
    assert committed["status"] == "LOCKED"
    assert committed["route_minutes"] == 24
    a.assert_iso_millis(committed["expected_return_at"], "expected_return_at")
    assert a.parse_instant(committed["expected_return_at"]) == a.parse_instant(
        "2026-08-05T18:59:00Z"
    )
    assert committed["resolved_cost_model_id"] == world["cost_model"]["id"]
    assert committed["estimated_reimbursement_cents"] == a.expected_reimbursement_from_model(
        [STOP_MILES], CAR_COST_MODEL
    )
    assert committed["estimated_reimbursement_cents"] == 336

    # The earlier commitment is untouched by the later one.
    unchanged = fx.read_dispatch(first["id"])
    assert unchanged["status"] == "LOCKED"
    assert unchanged["version"] == first["version"]
    assert a.parse_instant(unchanged["expected_return_at"]) == a.parse_instant(
        "2026-08-05T18:24:00Z"
    )


def test_releasing_the_earlier_commitment_frees_the_driver_interval_at_the_boundary():
    """Un-committing the first route clears every computed field and lets the touching lock through.

    PRD: "Releasing a commitment reverses all of it: a `Dispatcher` may move a route `LOCKED → STACKED`, which returns `route_minutes`, `expected_return_at`, `resolved_cost_model_id` and `estimated_reimbursement_cents` all to null and frees both the driver's occupied interval and the store's bag reservation, so that stops can be added or removed and the route committed again."
    Design: Difficulty/resource_temporal_overlap/driver_occupation_interval_is_closed_so_touching_at_1834_conflicts
    """
    world = fx.setup_locked_route(
        ("A",),
        planned_depart_at=EVENING_DEPART_AT,
        hot_bag_slots=[1],
        store_overrides=dict(STORE_POLICY),
    )
    store_id = world["store"]["id"]
    driver_id = world["driver"]["id"]
    first = fx.read_dispatch(world["dispatch"]["id"])

    second_address = fx.add_address(store_id, "A2")
    second_order = fx.add_ready_order(store_id, second_address["id"])
    second = fx.open_dispatch(driver_id, "2026-08-05T18:34:00Z")
    fx.stack_stop(second["id"], second_order["id"], 1)

    released = validate_success(
        api_client.unlock_dispatch(first["id"], DISPATCHER_HEADERS), 200
    )
    assert released["status"] == "STACKED"
    assert released["route_minutes"] is None
    assert released["expected_return_at"] is None
    assert released["resolved_cost_model_id"] is None
    assert released["estimated_reimbursement_cents"] is None
    assert released["committed_hot_bag_slots"] == 1

    now_free = validate_success(
        api_client.lock_dispatch(second["id"], DISPATCHER_HEADERS), 200
    )
    assert now_free["status"] == "LOCKED"
    assert now_free["route_minutes"] == 24
    assert a.parse_instant(now_free["expected_return_at"]) == a.parse_instant(
        "2026-08-05T18:58:00Z"
    )


def _bag_pool_world():
    """A committed two-stop evening route holding all four bag slots, plus a second
    qualified driver of the same store who has no route yet."""
    world = fx.setup_locked_route(
        ("A", "A2"),
        planned_depart_at=EVENING_DEPART_AT,
        hot_bag_slots=[2, 2],
        store_overrides=dict(STORE_POLICY),
    )
    store_id = world["store"]["id"]
    world["second_driver"] = fx.add_qualified_driver(
        store_id, full_name="Bo Reyes", license_number="DL-1002"
    )
    committed = fx.read_dispatch(world["dispatch"]["id"])
    assert committed["committed_hot_bag_slots"] == 4
    assert committed["route_minutes"] == a.expected_route_minutes(
        [STOP_MILES, STOP_MILES], MINUTES_PER_MILE, HANDOFF_MINUTES
    )
    assert committed["route_minutes"] == 39
    assert a.parse_instant(committed["expected_return_at"]) == a.parse_instant(
        "2026-08-05T18:39:00Z"
    )
    assert committed["estimated_reimbursement_cents"] == 651
    world["dispatch"] = committed
    return world


def test_a_second_driver_whose_bag_window_overlaps_exhausts_the_pool():
    """A route whose reservation window overlaps a committed one cannot draw a fifth bag slot.

    PRD: "The store's bag pool must accommodate the route: taking every route of the same store whose status is `LOCKED` or `EN_ROUTE` and whose half-open reservation window from `planned_depart_at` inclusive to `expected_return_at` exclusive intersects this route's window, the sum of their `committed_hot_bag_slots` plus this route's own `committed_hot_bag_slots` must not exceed the store's `hot_bag_count`, or the commitment is refused with `ERR_HOT_BAG_CAPACITY_EXCEEDED`."
    Design: Difficulty/resource_temporal_overlap/hot_bag_pool_window_is_half_open_so_1830_overlaps_but_1839_does_not
    """
    world = _bag_pool_world()
    store_id = world["store"]["id"]
    first = world["dispatch"]

    third_order = fx.add_ready_order(store_id, world["addresses"]["A"]["id"])
    inside = fx.open_dispatch(world["second_driver"]["id"], "2026-08-05T18:30:00Z")
    fx.stack_stop(inside["id"], third_order["id"], 1)

    validate_error(
        api_client.lock_dispatch(inside["id"], DISPATCHER_HEADERS),
        ApiErrorId.ERR_HOT_BAG_CAPACITY_EXCEEDED.value,
    )

    refused = fx.read_dispatch(inside["id"])
    assert refused["status"] == "STACKED"
    assert refused["committed_hot_bag_slots"] == 1
    assert refused["route_minutes"] is None
    assert refused["expected_return_at"] is None
    assert refused["estimated_reimbursement_cents"] is None

    untouched = fx.read_dispatch(first["id"])
    assert untouched["status"] == "LOCKED"
    assert untouched["committed_hot_bag_slots"] == 4
    assert untouched["version"] == first["version"]


def test_a_second_driver_departing_at_the_exclusive_end_shares_no_bags():
    """A route departing exactly when a committed route is modelled home draws from a free pool.

    PRD: "Two routes whose windows merely touch share no bags."
    Design: Difficulty/resource_temporal_overlap/hot_bag_pool_window_is_half_open_so_1830_overlaps_but_1839_does_not
    """
    world = _bag_pool_world()
    store_id = world["store"]["id"]
    first = world["dispatch"]

    touching_at = a.format_instant(a.parse_instant(first["expected_return_at"]))
    assert touching_at == "2026-08-05T18:39:00Z"

    third_order = fx.add_ready_order(store_id, world["addresses"]["A"]["id"])
    abutting = fx.open_dispatch(world["second_driver"]["id"], touching_at)
    fx.stack_stop(abutting["id"], third_order["id"], 1)

    committed = validate_success(
        api_client.lock_dispatch(abutting["id"], DISPATCHER_HEADERS), 200
    )
    assert committed["status"] == "LOCKED"
    assert committed["committed_hot_bag_slots"] == 1
    assert committed["route_minutes"] == 24
    assert a.parse_instant(committed["expected_return_at"]) == a.parse_instant(
        "2026-08-05T19:03:00Z"
    )
    assert committed["estimated_reimbursement_cents"] == 336
    assert fx.read_dispatch(first["id"])["committed_hot_bag_slots"] == 4


def test_releasing_the_committed_route_returns_every_bag_slot_to_the_pool():
    """Un-committing the four-slot route frees the reservation so the overlapping route commits.

    PRD: "Releasing a commitment reverses all of it: a `Dispatcher` may move a route `LOCKED → STACKED`, which returns `route_minutes`, `expected_return_at`, `resolved_cost_model_id` and `estimated_reimbursement_cents` all to null and frees both the driver's occupied interval and the store's bag reservation, so that stops can be added or removed and the route committed again."
    Design: Difficulty/resource_temporal_overlap/hot_bag_pool_window_is_half_open_so_1830_overlaps_but_1839_does_not
    """
    world = _bag_pool_world()
    store_id = world["store"]["id"]
    first = world["dispatch"]

    third_order = fx.add_ready_order(store_id, world["addresses"]["A"]["id"])
    inside = fx.open_dispatch(world["second_driver"]["id"], "2026-08-05T18:30:00Z")
    fx.stack_stop(inside["id"], third_order["id"], 1)

    released = validate_success(
        api_client.unlock_dispatch(first["id"], DISPATCHER_HEADERS), 200
    )
    assert released["status"] == "STACKED"
    assert released["route_minutes"] is None
    assert released["expected_return_at"] is None
    assert released["resolved_cost_model_id"] is None
    assert released["estimated_reimbursement_cents"] is None
    # The slots stay counted on the route itself; what the release frees is the
    # store-level reservation the commitment took out.
    assert released["committed_hot_bag_slots"] == 4

    committed = validate_success(
        api_client.lock_dispatch(inside["id"], DISPATCHER_HEADERS), 200
    )
    assert committed["status"] == "LOCKED"
    assert committed["committed_hot_bag_slots"] == 1
    assert committed["route_minutes"] == 24
    assert a.parse_instant(committed["expected_return_at"]) == a.parse_instant(
        "2026-08-05T18:54:00Z"
    )


def _cash_collected_world():
    """One cash order handed over at the door, so the whole take sits on the driver."""
    world = fx.setup_departed_route(
        ("A",),
        planned_depart_at="2026-08-05T12:05:00Z",
        hot_bag_slots=[1],
        order_overrides={"payment_method": "CASH"},
        clock=NOON_CLOCK,
        store_overrides=dict(STORE_POLICY),
    )
    driver_id = world["driver"]["id"]
    order = world["orders"][0]
    stop = world["stops"][0]
    assert order["payment_method"] == "CASH"
    assert order["total_charge_cents"] == 2900

    fx.set_clock("2026-08-05T12:36:00Z")
    fx.arrive_at_door(world["dispatch"]["id"], stop["id"], driver_id, 3.40, 2900)
    world["order"] = fx.read_order(order["id"])
    world["stop"] = fx.read_stop(stop["id"])
    return world


def test_voiding_a_safe_drop_restores_the_cash_conservation_identity():
    """The drop and its void leave every cash figure exactly where the door handoff left it.

    PRD: "A successful void stamps `voided_at` from the logical clock, records the `voided_reason`, and is the exact compensating inverse of the drop: the driver's `cash_on_hand_cents` rises by `amount_cents`, the store's `safe_deposit_total_cents` falls by the same figure, and both the driver's `version` and the store's `version` increment by 1."
    Design: Difficulty/compensating_invariant/safe_drop_void_restores_the_cash_conservation_identity
    """
    world = _cash_collected_world()
    store_id = world["store"]["id"]
    driver_id = world["driver"]["id"]

    before = fx.read_cash_reconciliation(store_id)
    a.assert_cash_conservation(before)
    assert before["cash_collected_total_cents"] == 2900
    assert before["safe_deposit_total_cents"] == 0
    assert before["driver_cash_on_hand_total_cents"] == 2900
    assert before["reconciled"] is True

    drop = fx.record_safe_drop(driver_id, 2900, envelope_number="ENV-0001")
    assert drop["status"] == "RECORDED"
    in_the_safe = fx.read_cash_reconciliation(store_id)
    a.assert_cash_conservation(in_the_safe)
    assert in_the_safe["cash_collected_total_cents"] == 2900
    assert in_the_safe["safe_deposit_total_cents"] == 2900
    assert in_the_safe["driver_cash_on_hand_total_cents"] == 0
    assert in_the_safe["reconciled"] is True

    driver_after_drop = fx.read_driver(driver_id)
    store_after_drop = fx.read_store(store_id)

    voided = validate_success(
        api_client.void_safe_drop(
            drop["id"],
            f.void_safe_drop_payload(voided_reason="Envelope mis-scanned at the safe"),
            make_manager_headers(store_id),
        ),
        200,
    )
    a.assert_safe_drop(voided)
    assert voided["status"] == "VOIDED"
    assert voided["voided_reason"] == "Envelope mis-scanned at the safe"
    assert voided["amount_cents"] == 2900
    a.assert_iso_millis(voided["voided_at"], "voided_at")
    assert a.parse_instant(voided["voided_at"]) == a.parse_instant("2026-08-05T12:36:00Z")

    after = fx.read_cash_reconciliation(store_id)
    a.assert_cash_conservation(after)
    assert after["cash_collected_total_cents"] == before["cash_collected_total_cents"]
    assert after["safe_deposit_total_cents"] == before["safe_deposit_total_cents"]
    assert after["driver_cash_on_hand_total_cents"] == before["driver_cash_on_hand_total_cents"]
    assert after["reconciled"] is True

    driver_after_void = fx.read_driver(driver_id)
    store_after_void = fx.read_store(store_id)
    assert driver_after_void["cash_on_hand_cents"] == 2900
    assert driver_after_void["cash_posture"] == "CLEAR"
    assert driver_after_void["version"] == driver_after_drop["version"] + 1
    assert store_after_void["safe_deposit_total_cents"] == 0
    assert store_after_void["cash_collected_total_cents"] == 2900
    assert store_after_void["version"] == store_after_drop["version"] + 1

    # The money the customer handed over at the door is not what moved.
    assert fx.read_stop(world["stop"]["id"])["cash_collected_cents"] == 2900
    assert fx.read_order(world["order"]["id"])["cash_collected_cents"] == 2900


def test_a_voided_drop_is_terminal_so_the_driver_is_credited_only_once():
    """The void is not repeatable: a second attempt is refused and no cash figure moves again.

    PRD: "Voiding requires a `voided_reason` and advances the drop `RECORDED → VOIDED`, its only transition and its terminal state; voiding a drop that is already `VOIDED` is refused with `ERR_INVALID_SAFE_DROP_STATE`."
    Design: Difficulty/compensating_invariant/safe_drop_void_restores_the_cash_conservation_identity
    """
    world = _cash_collected_world()
    store_id = world["store"]["id"]
    driver_id = world["driver"]["id"]

    drop = fx.record_safe_drop(driver_id, 2900, envelope_number="ENV-0001")
    once = fx.void_safe_drop(
        drop["id"], store_id, voided_reason="Envelope mis-scanned at the safe"
    )
    assert once["status"] == "VOIDED"

    credited_once = fx.read_cash_reconciliation(store_id)
    a.assert_cash_conservation(credited_once)
    assert credited_once["driver_cash_on_hand_total_cents"] == 2900
    driver_once = fx.read_driver(driver_id)

    validate_error(
        api_client.void_safe_drop(
            drop["id"],
            f.void_safe_drop_payload(voided_reason="Second attempt on the same envelope"),
            make_manager_headers(store_id),
        ),
        ApiErrorId.ERR_INVALID_SAFE_DROP_STATE.value,
    )

    unchanged = validate_success(
        api_client.get_safe_drop(drop["id"], make_manager_headers(store_id)), 200
    )
    assert unchanged["status"] == "VOIDED"
    assert unchanged["voided_reason"] == "Envelope mis-scanned at the safe"
    assert unchanged["version"] == once["version"]
    assert a.parse_instant(unchanged["voided_at"]) == a.parse_instant(once["voided_at"])

    after = fx.read_cash_reconciliation(store_id)
    a.assert_cash_conservation(after)
    assert after["cash_collected_total_cents"] == 2900
    assert after["safe_deposit_total_cents"] == 0
    assert after["driver_cash_on_hand_total_cents"] == 2900
    assert fx.read_driver(driver_id)["version"] == driver_once["version"]


def test_releasing_a_stop_and_re_stacking_the_order_restores_every_route_total():
    """Release and re-insertion return the route's slot count, stop count and the store's queue to their prior values.

    PRD: "The stop's status becomes `RELEASED`, its order reverts `ASSIGNED → READY`, and the route's `committed_hot_bag_slots` and `stop_count` both fall back to their pre-insertion values — the hot-bag pool must return to exactly the total it had before, which is why released stops stop being counted."
    Design: Difficulty/compensating_invariant/stop_release_restores_hot_bag_slots_without_reusing_the_ordinal
    """
    world = fx.setup_stacked_route(
        ("A", "A2"), hot_bag_slots=[2, 1], store_overrides=dict(STORE_POLICY)
    )
    store_id = world["store"]["id"]
    dispatch_id = world["dispatch"]["id"]
    first_stop, second_stop = world["stops"]
    first_order, second_order = world["orders"]

    before = fx.read_dispatch(dispatch_id)
    assert before["status"] == "STACKED"
    assert before["stop_count"] == 2
    assert before["committed_hot_bag_slots"] == 3
    assert fx.read_store(store_id)["unassigned_order_count"] == 0

    parent = validate_success(
        api_client.delete_dispatch_stop(dispatch_id, first_stop["id"], DISPATCHER_HEADERS), 200
    )
    assert parent["id"] == dispatch_id
    assert parent["status"] == "STACKED"
    assert parent["stop_count"] == 1
    assert parent["committed_hot_bag_slots"] == 1
    assert fx.read_stop(first_stop["id"])["status"] == "RELEASED"
    assert fx.read_order(first_order["id"])["fulfillment_status"] == "READY"
    assert fx.read_order(second_order["id"])["fulfillment_status"] == "ASSIGNED"
    assert fx.read_store(store_id)["unassigned_order_count"] == 1

    fx.stack_stop(dispatch_id, first_order["id"], 2)

    after = fx.read_dispatch(dispatch_id)
    assert after["status"] == before["status"]
    assert after["stop_count"] == before["stop_count"]
    assert after["committed_hot_bag_slots"] == before["committed_hot_bag_slots"]
    assert after["stop_count"] == 2
    assert after["committed_hot_bag_slots"] == 3
    assert fx.read_order(first_order["id"])["fulfillment_status"] == "ASSIGNED"
    assert fx.read_store(store_id)["unassigned_order_count"] == 0
    assert fx.read_stop(second_stop["id"])["status"] == "PENDING"


def test_a_released_stops_ordinal_is_never_reused_by_the_next_insertion():
    """Slots come back but the ordinal does not: the next insertion mints a fresh higher sequence.

    PRD: "Existing stops are never renumbered and a released stop's ordinal is never reused, so the insertion that follows a release receives a fresh higher number and a route's live stops may carry non-contiguous ordinals."
    Design: Difficulty/compensating_invariant/stop_release_restores_hot_bag_slots_without_reusing_the_ordinal
    """
    world = fx.setup_stacked_route(
        ("A", "A2"), hot_bag_slots=[2, 1], store_overrides=dict(STORE_POLICY)
    )
    dispatch_id = world["dispatch"]["id"]
    first_stop, second_stop = world["stops"]
    first_order = world["orders"][0]
    assert first_stop["sequence"] == 1
    assert second_stop["sequence"] == 2

    validate_success(
        api_client.delete_dispatch_stop(dispatch_id, first_stop["id"], DISPATCHER_HEADERS), 200
    )
    released = fx.read_stop(first_stop["id"])
    assert released["status"] == "RELEASED"
    assert released["sequence"] == 1
    # The survivor keeps the ordinal it was minted with.
    assert fx.read_stop(second_stop["id"])["sequence"] == 2

    fresh = fx.stack_stop(dispatch_id, first_order["id"], 2)
    assert fresh["sequence"] == 3
    assert fresh["status"] == "PENDING"
    assert fresh["id"] != first_stop["id"]
    assert fx.read_dispatch(dispatch_id)["committed_hot_bag_slots"] == 3

    # The live stops of the route now carry non-contiguous ordinals, in ascending order.
    walked = fx.list_route_stops(dispatch_id)
    live = [stop["sequence"] for stop in walked if stop["status"] == "PENDING"]
    assert live == [2, 3]


def test_releasing_every_stop_empties_the_route_and_blocks_the_commitment():
    """A fully unwound route holds nothing and therefore cannot be committed.

    PRD: "And the route must carry at least one counted stop, or the commitment is refused with `ERR_DISPATCH_HAS_NO_STOPS` — an empty route has no schedule to resolve, no last stop to drive home from, and nothing to reimburse."
    Design: Difficulty/compensating_invariant/stop_release_restores_hot_bag_slots_without_reusing_the_ordinal
    """
    world = fx.setup_stacked_route(
        ("A", "A2"), hot_bag_slots=[2, 1], store_overrides=dict(STORE_POLICY)
    )
    store_id = world["store"]["id"]
    dispatch_id = world["dispatch"]["id"]
    first_stop, second_stop = world["stops"]

    fx.unstack_stop(dispatch_id, first_stop["id"])
    emptied = validate_success(
        api_client.delete_dispatch_stop(dispatch_id, second_stop["id"], DISPATCHER_HEADERS), 200
    )
    assert emptied["status"] == "DRAFT"
    assert emptied["stop_count"] == 0
    assert emptied["committed_hot_bag_slots"] == 0
    assert fx.read_store(store_id)["unassigned_order_count"] == 2

    validate_error(
        api_client.lock_dispatch(dispatch_id, DISPATCHER_HEADERS),
        ApiErrorId.ERR_DISPATCH_HAS_NO_STOPS.value,
    )

    still_empty = fx.read_dispatch(dispatch_id)
    assert still_empty["status"] == "DRAFT"
    assert still_empty["stop_count"] == 0
    assert still_empty["committed_hot_bag_slots"] == 0
    assert still_empty["route_minutes"] is None
    assert still_empty["expected_return_at"] is None
    assert still_empty["resolved_cost_model_id"] is None
    assert still_empty["estimated_reimbursement_cents"] is None
    assert still_empty["version"] == emptied["version"]


def _settled_pair_world():
    """A two-stop card route settled on odometer readings of 3.40 and 2.80 miles,
    so the ledger holds one accrued actual-basis line per stop."""
    world = fx.setup_departed_route(
        ("A", "A2"),
        planned_depart_at="2026-08-05T12:05:00Z",
        hot_bag_slots=[1, 1],
        clock=NOON_CLOCK,
        store_overrides=dict(STORE_POLICY),
    )
    store_id = world["store"]["id"]
    driver_id = world["driver"]["id"]
    dispatch_id = world["dispatch"]["id"]
    first_stop, second_stop = world["stops"]

    fx.set_clock("2026-08-05T12:36:00Z")
    fx.arrive_at_door(dispatch_id, first_stop["id"], driver_id, 3.40, 0)
    fx.arrive_at_door(dispatch_id, second_stop["id"], driver_id, 2.80, 0)
    fx.check_in_route(dispatch_id, driver_id)

    settled = fx.settle_route(dispatch_id, store_id)
    assert settled["status"] == "SETTLED"
    assert settled["estimated_reimbursement_cents"] == 651
    assert settled["actual_reimbursement_cents"] == 659
    assert settled["reimbursement_variance_cents"] == 8
    assert a.expected_stops_from_model([3.40, 2.80], CAR_COST_MODEL) == [361, 298]
    assert fx.read_driver(driver_id)["reimbursement_accrued_cents"] == 659

    world["dispatch"] = settled
    world["orders"] = [fx.read_order(order["id"]) for order in world["orders"]]
    world["stops"] = fx.list_route_stops(dispatch_id)
    return world


def test_a_chargeable_approval_claws_back_exactly_the_settled_stop_line():
    """The clawback line negates the one stop's actual amount, not the customer's credit.

    PRD: "When `driver_chargeable` is true the approval additionally writes a ledger line with `line_type` `CLAWBACK`, `basis` `NONE`, `status` `ACCRUED`, `sequence_snapshot` 0, and an `amount_cents` equal to the negation of the `ACTUAL_STOP` line amount recorded for this order; the complaint's `clawback_cents` records the absolute value of that amount, and because the new line is accrued and negative, the driver's `reimbursement_accrued_cents` re-derives downward by that same figure while the driver's `version` increments by 1."
    Design: Difficulty/compensating_invariant/driver_chargeable_complaint_clawback_reduces_accrual_by_exactly_the_stop_line
    """
    world = _settled_pair_world()
    store_id = world["store"]["id"]
    driver_id = world["driver"]["id"]
    first_order = world["orders"][0]

    complaint = fx.log_complaint(
        first_order["id"],
        "QUALITY",
        description="Pizza arrived cold and the box was crushed",
    )
    proposed = fx.propose_remedy(complaint["id"])
    assert proposed["status"] == "REMEDY_PROPOSED"
    assert proposed["remedy_basis"] == "QUALITY_HALF"
    assert proposed["proposed_remedy_cents"] == 1100
    assert proposed["clawback_cents"] == 0

    driver_before = fx.read_driver(driver_id)
    assert driver_before["reimbursement_accrued_cents"] == 659

    issued = validate_success(
        api_client.resolve_complaint(
            complaint["id"],
            f.resolve_complaint_payload("APPROVE", driver_chargeable=True),
            make_manager_headers(store_id),
        ),
        200,
    )
    a.assert_complaint(issued)
    assert issued["status"] == "REMEDY_ISSUED"
    assert issued["driver_chargeable"] is True
    assert issued["clawback_cents"] == 361
    assert issued["proposed_remedy_cents"] == 1100
    a.assert_iso_millis(issued["resolved_at"], "resolved_at")

    clawbacks = [
        line for line in _ledger_lines(store_id, driver_id) if line["line_type"] == "CLAWBACK"
    ]
    assert len(clawbacks) == 1
    line = clawbacks[0]
    a.assert_reimbursement_line(line)
    assert line["amount_cents"] == -361
    assert line["basis"] == "NONE"
    assert line["status"] == "ACCRUED"
    assert line["sequence_snapshot"] == 0
    assert line["order_id"] == first_order["id"]
    assert line["dispatch_id"] == world["dispatch"]["id"]

    driver_after = fx.read_driver(driver_id)
    assert driver_after["reimbursement_accrued_cents"] == 659 - 361
    assert driver_after["reimbursement_accrued_cents"] == 298
    assert driver_after["version"] == driver_before["version"] + 1


def test_the_clawback_leaves_the_settled_lines_and_the_other_stop_alone():
    """The accrual after a clawback is still the sum of the accrued lines and nothing else.

    PRD: "What a driver is actually owed on the next payroll run — the driver's `reimbursement_accrued_cents` — is the sum of `amount_cents` across every ledger line of that driver whose `status` is `ACCRUED`, and nothing else."
    Design: Difficulty/compensating_invariant/driver_chargeable_complaint_clawback_reduces_accrual_by_exactly_the_stop_line
    """
    world = _settled_pair_world()
    store_id = world["store"]["id"]
    driver_id = world["driver"]["id"]
    first_order, second_order = world["orders"]

    before = {
        line["id"]: line
        for line in _ledger_lines(store_id, driver_id)
        if line["line_type"] == "ACTUAL_STOP"
    }
    assert len(before) == 2

    complaint = fx.log_complaint(
        first_order["id"],
        "QUALITY",
        description="Pizza arrived cold and the box was crushed",
    )
    fx.propose_remedy(complaint["id"])
    fx.resolve_complaint(complaint["id"], "APPROVE", store_id, driver_chargeable=True)

    lines = _ledger_lines(store_id, driver_id)
    actual = {line["id"]: line for line in lines if line["line_type"] == "ACTUAL_STOP"}
    assert set(actual) == set(before)
    for line_id, line in actual.items():
        # The ledger is append-only: the settled lines are not edited by the clawback.
        assert line["amount_cents"] == before[line_id]["amount_cents"]
        assert line["status"] == "ACCRUED"
        assert line["basis"] == "ACTUAL"
        assert line["version"] == before[line_id]["version"]

    by_sequence = {line["sequence_snapshot"]: line["amount_cents"] for line in actual.values()}
    assert by_sequence == {1: 361, 2: 298}

    provisional = [line for line in lines if line["line_type"] == "PROVISIONAL_STOP"]
    assert len(provisional) == 2
    assert all(line["status"] == "SUPERSEDED" for line in provisional)

    accrued_total = sum(line["amount_cents"] for line in lines if line["status"] == "ACCRUED")
    assert accrued_total == 361 + 298 - 361
    assert accrued_total == 298
    assert fx.read_driver(driver_id)["reimbursement_accrued_cents"] == accrued_total

    # The remedy is the customer's money and never enters the driver's accrual.
    adjusted = fx.read_order(first_order["id"])
    assert adjusted["settlement_status"] == "ADJUSTED"
    assert adjusted["remedy_issued_cents"] == 1100
    untouched = fx.read_order(second_order["id"])
    assert untouched["settlement_status"] == "CLOSED_SETTLED"
    assert untouched["remedy_issued_cents"] == 0
