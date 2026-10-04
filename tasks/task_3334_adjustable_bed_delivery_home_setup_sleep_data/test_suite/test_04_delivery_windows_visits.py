"""Delivery windows and visits: capacity, waitlist, reschedule, completion."""
from test_helpers import (
    ApiErrorId,
    create_delivery_visit,
    create_delivery_window,
    register_device,
    set_clock,
    setup_confirmed_order,
    setup_delivered_order,
    setup_scheduled_visit,
    validate_error,
    validate_success,
)
from test_helpers.fixtures import ADMIN, SALES, TECH
from test_helpers import pair_device, verify_visit


def test_window_capacity_equality_admitted_overflow_rejected(api):
    """PRD §3.5: "Capacity is then checked: a window accepts the visit when
    `reserved_slots` plus `slot_need` is no greater than `capacity_slots`,
    with equality allowed. When capacity suffices the visit lands in
    `SCHEDULED` and the window's `reserved_slots` increases by `slot_need`;
    the first `SCHEDULED` visit on an order moves the order from `CONFIRMED`
    to `FULFILLING`. When capacity is insufficient and `allow_waitlist` is not
    set, the request fails with `ERR_WINDOW_CAPACITY_EXCEEDED`."

    Design: Difficulty/boundary_precision_check/window_capacity_equality_admitted_overflow_rejected
    """
    set_clock()
    store, customer, fa, order_a = setup_confirmed_order(email="a@x.com")
    order_b = None
    from test_helpers import create_order
    from test_helpers.fixtures import SALES as _S
    order_b = create_order(customer["id"], fa["id"], [{"sku": "MAT-1", "qty": 1}])
    validate_success(api.confirm_order(order_b["id"],
                                       {"payment_method": "PAY_IN_FULL"}, _S))
    order_c = create_order(customer["id"], fa["id"], [{"sku": "MAT-1", "qty": 1}])
    validate_success(api.confirm_order(order_c["id"],
                                       {"payment_method": "PAY_IN_FULL"}, _S))
    window = create_delivery_window(store["id"], capacity_slots=4)
    visit_a = create_delivery_visit(order_a["id"], window["id"])
    assert visit_a["status"] == "SCHEDULED"

    # equality: reserved 2 + need 2 == capacity 4
    visit_b = create_delivery_visit(order_b["id"], window["id"])
    assert visit_b["status"] == "SCHEDULED"
    win = validate_success(api.get_delivery_window(window["id"], ADMIN))
    assert win["reserved_slots"] == 4

    # overflow: reserved 4 + need 2 > 4
    resp = api.create_delivery_visit(
        {"order_id": order_c["id"], "delivery_window_id": window["id"]}, SALES)
    validate_error(resp, ApiErrorId.ERR_WINDOW_CAPACITY_EXCEEDED)


def test_removal_visit_rejected_on_aggregate_slots_not_geometry(api):
    """PRD §3.5: "A `SalesAssociate` schedules a visit against an `order_id`
    and a `delivery_window_id`, optionally flagging `remove_old_mattress`
    (defaulting to false, and adding 1 slot when true), recording
    `room_prep_notes`, and optionally setting `allow_waitlist`. The visit's
    `slot_need` is computed as 2 plus 1 when `remove_old_mattress` is true."

    Design: Difficulty/resource_temporal_overlap/window_slot_capacity_aggregate_semantics_no_geometry
    """
    set_clock()
    store, customer, fa, order_a = setup_confirmed_order(email="a2@x.com")
    from test_helpers import create_order
    order_b = create_order(customer["id"], fa["id"], [{"sku": "MAT-1", "qty": 1}])
    validate_success(api.confirm_order(order_b["id"],
                                       {"payment_method": "PAY_IN_FULL"}, SALES))
    window = create_delivery_window(store["id"], capacity_slots=4)
    create_delivery_visit(order_a["id"], window["id"])

    resp = api.create_delivery_visit(
        {"order_id": order_b["id"], "delivery_window_id": window["id"],
         "remove_old_mattress": True}, SALES)
    validate_error(resp, ApiErrorId.ERR_WINDOW_CAPACITY_EXCEEDED)
    win = validate_success(api.get_delivery_window(window["id"], ADMIN))
    assert win["reserved_slots"] == 2, (
        f"reserved_slots must remain 2 after rejection, got "
        f"{win['reserved_slots']}")


def test_team_window_overlap_rejected_adjacency_allowed(api):
    """PRD §3.5: "Two windows belonging to the same `(store_id, team_id)` pair
    must not overlap; because the interval is half-open, an existing window
    whose `window_end` equals the new window's `window_start` is adjacency,
    not overlap, and is allowed. A violating window is rejected with
    `ERR_WINDOW_TEAM_OVERLAP`."

    Design: Difficulty/resource_temporal_overlap/team_window_half_open_overlap_adjacency_allowed
    """
    set_clock()
    store, customer, fa, order = setup_confirmed_order(email="a3@x.com")
    create_delivery_window(store["id"], team_id="T1",
                           window_start="2026-09-02T08:00:00Z",
                           window_end="2026-09-02T12:00:00Z",
                           capacity_slots=4)
    # Overlapping same-team window: 11:00-15:00 intersects [08:00, 12:00).
    resp = api.create_delivery_window(
        {"store_id": store["id"], "team_id": "T1",
         "window_start": "2026-09-02T11:00:00Z",
         "window_end": "2026-09-02T15:00:00Z", "capacity_slots": 4}, ADMIN)
    validate_error(resp, ApiErrorId.ERR_WINDOW_TEAM_OVERLAP)

    # Adjacent same-team window: starts exactly at existing window_end.
    resp = api.create_delivery_window(
        {"store_id": store["id"], "team_id": "T1",
         "window_start": "2026-09-02T12:00:00Z",
         "window_end": "2026-09-02T16:00:00Z", "capacity_slots": 4}, ADMIN)
    validate_success(resp, expected_status=201)

    # Same interval, different team: allowed.
    resp = api.create_delivery_window(
        {"store_id": store["id"], "team_id": "T2",
         "window_start": "2026-09-02T08:00:00Z",
         "window_end": "2026-09-02T12:00:00Z", "capacity_slots": 4}, ADMIN)
    validate_success(resp, expected_status=201)


def test_window_slots_schedule_then_cancel_conserves_capacity(api):
    """PRD §3.4: "First, every non-terminal `DeliveryVisit` for the order —
    any visit in `SCHEDULED`, `WAITLISTED`, or `FAILED_SETUP` — transitions to
    `CANCELLED`. Second, each `SCHEDULED` visit so cancelled releases its
    `slot_need` back to its `DeliveryWindow`, decrementing the window's
    `reserved_slots`." and PRD §3.5: "The invariant across all operations is
    that for every window, `reserved_slots` equals the sum of `slot_need` over
    its `SCHEDULED` visits, and the freed-capacity arithmetic is exact."

    Design: Difficulty/compensating_invariant/window_slots_schedule_then_cancel_conserves_capacity
    """
    set_clock()
    store, customer, fa, order = setup_confirmed_order(email="a4@x.com")
    window = create_delivery_window(store["id"], capacity_slots=6)
    visit = create_delivery_visit(order["id"], window["id"],
                                  remove_old_mattress=True)
    win = validate_success(api.get_delivery_window(window["id"], ADMIN))
    assert win["reserved_slots"] == 3, (
        f"removal visit consumes 2 base + 1 removal = 3, got "
        f"{win['reserved_slots']}")

    from test_helpers import make_customer_headers
    validate_success(api.cancel_order(
        order["id"], make_customer_headers(customer["id"])))
    win = validate_success(api.get_delivery_window(window["id"], ADMIN))
    assert win["reserved_slots"] == 0, (
        f"schedule + cancel must conserve capacity exactly, got "
        f"{win['reserved_slots']}")
    v = validate_success(api.get_delivery_visit(visit["id"], ADMIN))
    assert v["status"] == "CANCELLED"


def test_failed_setup_visit_reschedule_cycle_returns_to_scheduled(api):
    """PRD §3.5: "Rescheduling moves a `SCHEDULED` or `FAILED_SETUP` visit to
    a new window. The caller supplies `expected_visit_version`, a
    `new_delivery_window_id`, and optionally `allow_waitlist`." and "On
    success the visit releases its `slot_need` on the old window (which
    triggers waitlist promotion there), consumes `slot_need` on the new window
    and stays `SCHEDULED` — or, if the new window is full and `allow_waitlist`
    was set, moves to `WAITLISTED` against the new window — and increments its
    `version` by 1. The `FAILED_SETUP → SCHEDULED` leg and the
    `SCHEDULED → SCHEDULED` leg share this mechanics; the failed-setup cycle
    is repeatable."

    Design: Corner/state_machines/failed_setup_visit_reschedule_cycle_returns_to_scheduled
    """
    ctx = setup_scheduled_visit(email="u@x.com", window_capacity=4)
    store, order, visit = ctx["store"], ctx["order"], ctx["visit"]
    window2 = create_delivery_window(
        store["id"], window_start="2026-09-03T08:00:00Z",
        window_end="2026-09-03T12:00:00Z", capacity_slots=4)
    validate_success(api.complete_visit(visit["id"], {
        "outcome": "FAILED_SETUP",
        "setup_checklist": {"base_assembled": False, "chambers_connected": False,
                            "remote_configured": False,
                            "connectivity_verified": False}}, TECH))
    failed = validate_success(api.get_delivery_visit(visit["id"], ADMIN))
    assert failed["status"] == "FAILED_SETUP"
    version = failed["version"]

    resp = api.reschedule_visit(visit["id"], {
        "expected_visit_version": version,
        "new_delivery_window_id": window2["id"]}, SALES)
    rescheduled = validate_success(resp)
    assert rescheduled["status"] == "SCHEDULED"
    assert rescheduled["delivery_window_id"] == window2["id"]
    assert rescheduled["version"] == version + 1, (
        f"reschedule increments version by 1: {version} -> "
        f"{rescheduled['version']}")
    win1 = validate_success(api.get_delivery_window(ctx["window"]["id"], ADMIN))
    win2 = validate_success(api.get_delivery_window(window2["id"], ADMIN))
    assert win1["reserved_slots"] == 0
    assert win2["reserved_slots"] == 2


def test_complete_verified_visit_rejects_second_complete(api):
    """PRD §3.5: "Completing a `VERIFIED` or `CANCELLED` visit is rejected
    with `ERR_VISIT_ALREADY_COMPLETED`."

    Design: Corner/state_machines/complete_visit_from_terminal_verified_returns_invalid_state
    """
    ctx = setup_delivered_order(email="t@x.com", serial_number="SN-T1")
    order, visit = ctx["order"], ctx["visit"]
    trial_verified_at = order["trial_verified_at"]
    resp = api.complete_visit(visit["id"], {
        "outcome": "VERIFIED",
        "setup_checklist": {"base_assembled": True, "chambers_connected": True,
                            "remote_configured": True,
                            "connectivity_verified": True}}, TECH)
    validate_error(resp, ApiErrorId.ERR_VISIT_ALREADY_COMPLETED)
    v = validate_success(api.get_delivery_visit(visit["id"], ADMIN))
    assert v["status"] == "VERIFIED"
    o = validate_success(api.get_order(order["id"], ADMIN))
    assert o["trial_verified_at"] == trial_verified_at, (
        "no duplicate side effects: trial_verified_at unchanged")


def test_device_unpair_repair_cycle_recomputes_connectivity(api):
    """PRD §3.6: "Pairing is cyclic. A `DeliveryTechnician` drives a device to
    `PAIRED` by submitting `target_status` equal to `PAIRED` and optionally
    `connectivity_verified`; pairing is refused when the parent order is
    `CANCELLED` or `RETURNED`, surfacing as `ERR_INVALID_STATE`. When the pair
    action carried `connectivity_verified` true, the device's `connectivity`
    becomes `ONLINE`; otherwise it stays `OFFLINE`. Driving a device back to
    `UNPAIRED` always sets `connectivity` to `OFFLINE`. Re-pairing is
    allowed."

    Design: Corner/state_machines/device_unpair_repair_cycle_and_connectivity_recompute
    """
    store, customer, fa, order = setup_confirmed_order(email="w@x.com")
    device = register_device(order["id"], kind="BASE", serial_number="SN-W1")

    d = pair_device(device["id"], connectivity_verified=False)
    assert d["pairing_status"] == "PAIRED"
    assert d["connectivity"] == "OFFLINE"

    resp = api.pair_device(device["id"], {"target_status": "UNPAIRED"}, TECH)
    d = validate_success(resp)
    assert d["pairing_status"] == "UNPAIRED"
    assert d["connectivity"] == "OFFLINE"

    d = pair_device(device["id"], connectivity_verified=True)
    assert d["pairing_status"] == "PAIRED"
    assert d["connectivity"] == "ONLINE"


def test_visit_verification_gated_by_base_device_pairing(api):
    """PRD §3.5: "With `outcome` equal to `VERIFIED`, all four flags must be
    true — any false flag is rejected with `ERR_SETUP_CHECKLIST_INCOMPLETE` —
    and every `Device` of `kind` `BASE` registered under the order must have
    `pairing_status` equal to `PAIRED`, else the request fails with
    `ERR_DEVICE_NOT_PAIRED`. A verified completion moves the order from
    `FULFILLING` to `DELIVERED` and stamps `trial_verified_at` with the
    logical clock, starting the 100-night trial."

    Design: Difficulty/cross_entity_state_dependency/visit_verification_gated_by_base_device_pairing
    """
    ctx = setup_scheduled_visit(email="a5@x.com")
    order, visit = ctx["order"], ctx["visit"]
    device = register_device(order["id"], kind="BASE", serial_number="SN-A1")
    checklist = {"base_assembled": True, "chambers_connected": True,
                 "remote_configured": True, "connectivity_verified": True}

    resp = api.complete_visit(
        visit["id"], {"outcome": "VERIFIED", "setup_checklist": checklist},
        TECH)
    validate_error(resp, ApiErrorId.ERR_DEVICE_NOT_PAIRED)
    v = validate_success(api.get_delivery_visit(visit["id"], ADMIN))
    assert v["status"] == "SCHEDULED"

    pair_device(device["id"])
    v = validate_success(api.complete_visit(
        visit["id"], {"outcome": "VERIFIED", "setup_checklist": checklist},
        TECH))
    assert v["status"] == "VERIFIED"
    o = validate_success(api.get_order(order["id"], ADMIN))
    assert o["order_status"] == "DELIVERED"
    assert o["trial_verified_at"], "trial_verified_at must be stamped"
