"""Stale pulls, credits, and disputes: tier boundaries, dual-variant
provisional-vs-final divergence, deadline rejection, parallel dimensions,
dispute threshold cascade, and the dispute/resolve conservation invariant."""
from test_helpers import (
    TEST_USERS,
    ApiErrorId,
    get_success_data,
    validate_error,
    validate_success,
)
from test_helpers.fixtures import (
    add_route_stop,
    create_completed_batch,
    create_dispatched_route,
    create_door,
    create_route,
    create_stale_pull,
    deliver_stop_fully,
    setup_delivered_shipment,
    setup_hub_with_line,
    stage_shipment,
)
from test_helpers.test_users import make_door_manager_headers as dmh

NA = TEST_USERS["network_admin_headers"]
HM = TEST_USERS["hub_manager_headers"]
RP = TEST_USERS["route_planner_headers"]
RD = TEST_USERS["route_driver_headers"]


# ---------------------------------------------------------------------------
# Corner/calculations/stale_credit_tier_boundaries
# ---------------------------------------------------------------------------

def test_stale_credit_tier_boundaries(api):
    """PRD §3.6: "The base value is `pulled_dozens` multiplied by 1200 cents
    per dozen. The tier rate depends on the pull size: pulls of at least 24
    dozen use a rate of 0.80; pulls of at least 6 dozen but fewer than 24 use
    0.65; anything smaller uses 0.50. The raw credit is the base multiplied
    by the applicable rate, and the rounding order is pinned — the credit is
    rounded once, half-up, to integer cents, per credit and never per dozen."

    Design: Corner/calculations/stale_credit_tier_boundaries
    """
    env = setup_delivered_shipment(
        network_code="NCB", region="RCB", planned_dozens=100, dozens_shipped=60,
        line_overrides={"rated_dozens_per_hour": 200, "service_interval_hours": 300},
    )
    nid, did, sid = env["network"]["id"], env["door"]["id"], env["shipment"]["id"]

    sc5 = create_stale_pull(nid, did, sid, 5)
    assert sc5["provisional_credit_cents"] == 3000, (
        f"5 dozen at TIER0 0.50: 5*1200*0.5 == 3000, got {sc5['provisional_credit_cents']}"
    )

    sc6 = create_stale_pull(nid, did, sid, 6)
    assert sc6["provisional_credit_cents"] == 4680, (
        f"6 dozen at TIER1 0.65: 6*1200*0.65 == 4680, got {sc6['provisional_credit_cents']}"
    )

    sc24 = create_stale_pull(nid, did, sid, 24)
    assert sc24["provisional_credit_cents"] == 23040, (
        f"24 dozen at TIER2 0.80: 24*1200*0.80 == 23040, got {sc24['provisional_credit_cents']}"
    )


# ---------------------------------------------------------------------------
# Difficulty/dual_variant_calc/stale_credit_provisional_vs_final_diverge_on_late_stop
# ---------------------------------------------------------------------------

def _setup_late_delivered_with_pull(api):
    """Late-delivered stop (arrival after window_end, late-arrival-eligible)
    with a 10-dozen stale pull created at 12:00. Returns the env dict."""
    network, hub, line = setup_hub_with_line(network_code="N1", hub_code="H1", region="R1")
    door = create_door(
        network["id"], door_kind="SPOKE", ownership="FRANCHISE", region="R1", hub_id=hub["id"]
    )
    batch = create_completed_batch(
        network["id"], hub["id"], line["id"], planned_dozens=100, produced_dozens=100
    )
    route, stop, shipment = create_dispatched_route(
        network["id"], hub["id"], door["id"], batch["id"], dozens_shipped=40,
        window_start="2026-09-01T08:00:00Z", window_end="2026-09-01T10:00:00Z",
    )
    # Arrive AFTER window_end (10:30) — late-arrival-eligible per recipe.
    deliver_stop_fully(
        network["id"], hub["id"], route["id"], stop["id"],
        [(shipment["id"], 40)], arrive_at="2026-09-01T10:30:00Z",
    )
    credit = create_stale_pull(network["id"], door["id"], shipment["id"], 10)
    return {
        "network": network, "hub": hub, "line": line, "door": door,
        "batch": batch, "route": route, "stop": stop, "shipment": shipment,
        "credit": credit,
    }


def test_stale_credit_provisional_value_at_pull_time(api):
    """PRD §3.6: "The base value is `pulled_dozens` multiplied by 1200 cents
    per dozen ... pulls of at least 6 dozen but fewer than 24 use 0.65 ... the
    credit is rounded once, half-up, to integer cents" and "The provisional
    variant, computed at pull time, uses the pulled dozens as reported".

    Design: Difficulty/dual_variant_calc/stale_credit_provisional_vs_final_diverge_on_late_stop
    """
    env = _setup_late_delivered_with_pull(api)
    credit = env["credit"]
    assert credit["credit_state"] == "PROVISIONAL"
    assert credit["provisional_credit_cents"] == 7800, (
        f"10 dozen at TIER1 0.65: 10*1200*0.65 == 7800, got {credit['provisional_credit_cents']}"
    )
    assert credit.get("final_credit_cents") is None, (
        "PRD §3.6: `final_credit_cents` stays unset until finalization"
    )


def test_stale_credit_final_variant_applies_late_penalty_at_reconcile(api):
    """PRD §3.6: "The final variant, computed at route reconciliation or
    dispute resolution, ignores `freshness_override` entirely but applies a
    late-delivery penalty: if the stop arrived after its `window_end`, the
    credit is multiplied by 0.9 before the same single rounding step."
    PRD §3.5: "every stale credit in `PROVISIONAL` tied to the route's
    shipments is recomputed under the final variant of the credit calculation
    and transitions `PROVISIONAL` → `FINALIZED`; each affected door's
    `credit_balance_cents` is adjusted by the per-credit delta between
    `final_credit_cents` and `provisional_credit_cents`".

    Design: Difficulty/dual_variant_calc/stale_credit_provisional_vs_final_diverge_on_late_stop
    """
    env = _setup_late_delivered_with_pull(api)
    nid, did = env["network"]["id"], env["door"]["id"]
    hub, route, credit = env["hub"], env["route"], env["credit"]

    door_before = validate_success(api.get_door(nid, did, NA))
    assert door_before["credit_balance_cents"] == 7800

    resp = api.reconcile_route(nid, hub["id"], route["id"], RP)
    validate_success(resp)

    credit_after = validate_success(
        api.get_stale_credit(nid, did, credit["id"], dmh(did))
    )
    assert credit_after["credit_state"] == "FINALIZED"
    assert credit_after["final_credit_cents"] == 7020, (
        f"final variant: 7800 * 0.9 == 7020, got {credit_after['final_credit_cents']}"
    )

    door_after = validate_success(api.get_door(nid, did, NA))
    assert door_after["credit_balance_cents"] == 7020, (
        f"delta adjustment: 7800 + (7020 - 7800) == 7020, got {door_after['credit_balance_cents']}"
    )


# ---------------------------------------------------------------------------
# Corner/validations/stale_pull_after_deadline_rejected
# ---------------------------------------------------------------------------

def test_stale_pull_after_deadline_rejected(api):
    """PRD §3.6: "the same-day pull regime gives doors until 23:59 local time
    on the batch's `production_date` to report stale product ... a pull
    attempted after 23:59 on the production date is rejected with
    `ERR_FRESHNESS_VIOLATION` (HTTP 422)."

    Design: Corner/validations/stale_pull_after_deadline_rejected
    """
    env = setup_delivered_shipment(
        network_code="NSD", region="RSD", planned_dozens=40, dozens_shipped=20,
    )
    get_success_data(api.set_clock("2026-09-02T01:00:00Z", NA))

    resp = api.create_stale_credit(
        env["network"]["id"], env["door"]["id"],
        {"shipment_id": env["shipment"]["id"], "pulled_dozens": 3},
        dmh(env["door"]["id"]),
    )
    validate_error(resp, ApiErrorId.ERR_FRESHNESS_VIOLATION)


# ---------------------------------------------------------------------------
# Difficulty/non_linear_state_machine/shipment_parallel_dimensions_delivery_and_credit
# ---------------------------------------------------------------------------

def test_shipment_parallel_dimensions_partial_delivery_and_dispute(api):
    """PRD §3.5: "Every shipment lives on two independent state dimensions.
    The first, `delivery_status`, runs `STAGED` → `IN_TRANSIT` → one of
    `DELIVERED`, `PARTIAL`, or `FAILED`. The second, `credit_status`, runs
    `NONE` → `PENDING_PULL` → one of `CREDITED` or `DISPUTED` ... The two
    dimensions evolve independently on the same entity."

    Design: Difficulty/non_linear_state_machine/shipment_parallel_dimensions_delivery_and_credit
    """
    env = setup_delivered_shipment(
        network_code="N6", region="R6", planned_dozens=40, dozens_shipped=40,
        dozens_delivered=30, line_overrides={"service_interval_hours": 300},
    )
    nid, did, sid = env["network"]["id"], env["door"]["id"], env["shipment"]["id"]

    shipment_mid = validate_success(api.get_shipment(nid, sid, RP))
    assert shipment_mid["delivery_status"] == "PARTIAL", "30 of 40 delivered -> PARTIAL"
    assert shipment_mid["credit_status"] == "NONE"

    credit = create_stale_pull(nid, did, sid, 6)
    resp = api.dispute_stale_credit(nid, did, credit["id"], dmh(did))
    disputed = validate_success(resp)
    assert disputed["credit_state"] == "DISPUTED"

    shipment_after = validate_success(api.get_shipment(nid, sid, RP))
    assert shipment_after["delivery_status"] == "PARTIAL", (
        "the delivery axis is already terminal PARTIAL and unaffected by the dispute"
    )
    assert shipment_after["credit_status"] == "DISPUTED"


def test_shipment_partial_delivery_increments_door_dispute_count(api):
    """PRD §3.6: "A `DoorManager` may dispute a credit only while it is
    `PROVISIONAL` and only within 48 hours of the pull time; the credit moves
    to `DISPUTED`, the door's `open_dispute_count` increments".

    Design: Difficulty/non_linear_state_machine/shipment_parallel_dimensions_delivery_and_credit
    """
    env = setup_delivered_shipment(
        network_code="N6B", region="R6", planned_dozens=40, dozens_shipped=40,
        dozens_delivered=30, line_overrides={"service_interval_hours": 300},
    )
    nid, did, sid = env["network"]["id"], env["door"]["id"], env["shipment"]["id"]

    credit = create_stale_pull(nid, did, sid, 6)
    validate_success(api.dispute_stale_credit(nid, did, credit["id"], dmh(did)))

    door_after = validate_success(api.get_door(nid, did, NA))
    assert door_after["open_dispute_count"] == 1


# ---------------------------------------------------------------------------
# Difficulty/transitive_cascade/dispute_threshold_suspends_door_then_halts_allocation
# ---------------------------------------------------------------------------

def _setup_three_credits_two_disputed(api):
    """Three delivered shipments, three stale pulls, two already disputed.
    Returns env dict with the third credit still PROVISIONAL."""
    network, hub, line = setup_hub_with_line(network_code="N8", hub_code="H8", region="R8")
    door = create_door(
        network["id"], door_kind="SPOKE", ownership="FRANCHISE", region="R8", hub_id=hub["id"]
    )
    batch = create_completed_batch(
        network["id"], hub["id"], line["id"], planned_dozens=60, produced_dozens=60
    )
    route = create_route(network["id"], hub["id"], route_code="RT8")
    stop = add_route_stop(network["id"], hub["id"], route["id"], door["id"])
    shipments = [
        stage_shipment(network["id"], hub["id"], route["id"], stop["id"], batch["id"], 20)
        for _ in range(3)
    ]
    get_success_data(api.lock_route(network["id"], hub["id"], route["id"], RP))
    get_success_data(api.dispatch_route(network["id"], hub["id"], route["id"], RP))
    deliver_stop_fully(
        network["id"], hub["id"], route["id"], stop["id"],
        [(s["id"], 20) for s in shipments],
    )
    credits = [
        create_stale_pull(network["id"], door["id"], s["id"], 4) for s in shipments
    ]
    for credit in credits[:2]:
        get_success_data(api.dispute_stale_credit(network["id"], door["id"], credit["id"], dmh(door["id"])))
    return {
        "network": network, "hub": hub, "line": line, "door": door,
        "batch": batch, "route": route, "stop": stop,
        "shipments": shipments, "credits": credits,
    }


def test_dispute_threshold_suspends_door(api):
    """PRD §3.6: "the credit moves to `DISPUTED`, the door's
    `open_dispute_count` increments, and if that count reaches three the door
    is automatically suspended".

    Design: Difficulty/transitive_cascade/dispute_threshold_suspends_door_then_halts_allocation
    """
    env = _setup_three_credits_two_disputed(api)
    nid, did = env["network"]["id"], env["door"]["id"]

    door_mid = validate_success(api.get_door(nid, did, NA))
    assert door_mid["open_dispute_count"] == 2
    assert door_mid["door_status"] == "ACTIVE", (
        "the conditional cascade must not fire before the threshold crossing"
    )

    third = env["credits"][2]
    validate_success(api.dispute_stale_credit(nid, did, third["id"], dmh(did)))

    door_after = validate_success(api.get_door(nid, did, NA))
    assert door_after["open_dispute_count"] == 3
    assert door_after["door_status"] == "SUSPENDED", (
        "crossing the >= 3 threshold flips the door to SUSPENDED"
    )


def test_dispute_threshold_second_dispute_leaves_door_active(api):
    """PRD §3.6: "if that count reaches three the door is automatically
    suspended" — at count two the door must still be `ACTIVE`.

    Design: Difficulty/transitive_cascade/dispute_threshold_suspends_door_then_halts_allocation
    """
    env = _setup_three_credits_two_disputed(api)
    nid, did = env["network"]["id"], env["door"]["id"]

    door_mid = validate_success(api.get_door(nid, did, NA))
    assert door_mid["open_dispute_count"] == 2
    assert door_mid["door_status"] == "ACTIVE"


# ---------------------------------------------------------------------------
# Difficulty/compensating_invariant/dispute_then_resolve_conserves_door_credit_balance
# ---------------------------------------------------------------------------

def test_dispute_then_resolve_conserves_credit_balance(api):
    """PRD §3.6: "A `NetworkAdmin` resolves a disputed credit by supplying a
    `resolution_credit_cents` amount: the credit's `final_credit_cents` is
    set to that amount, the door's `credit_balance_cents` is adjusted to the
    final figure, the dispute count decrements".

    Design: Difficulty/compensating_invariant/dispute_then_resolve_conserves_door_credit_balance
    """
    env = setup_delivered_shipment(
        network_code="N18", region="R18", planned_dozens=40, dozens_shipped=20,
    )
    nid, did, sid = env["network"]["id"], env["door"]["id"], env["shipment"]["id"]

    credit = create_stale_pull(nid, did, sid, 5)
    assert credit["provisional_credit_cents"] == 3000  # 5*1200*0.50
    validate_success(api.dispute_stale_credit(nid, did, credit["id"], dmh(did)))

    door_mid = validate_success(api.get_door(nid, did, NA))
    assert door_mid["open_dispute_count"] == 1

    resp = api.resolve_stale_credit(nid, did, credit["id"], {"resolution_credit_cents": 2500}, NA)
    resolved = validate_success(resp)
    assert resolved["credit_state"] == "RESOLVED"
    assert resolved["final_credit_cents"] == 2500

    door_after = validate_success(api.get_door(nid, did, NA))
    assert door_after["open_dispute_count"] == 0, "dispute +1, resolve -1: conserved counter"
    assert door_after["credit_balance_cents"] == 2500, (
        "resolution adjusts the balance to the final figure exactly once "
        "(provisional 3000 adjusted by delta -500), it does not add a second credit"
    )


def test_dispute_then_resolve_marks_credit_resolved(api):
    """PRD §3.6: "A `NetworkAdmin` resolves a disputed credit by supplying a
    `resolution_credit_cents` amount: the credit's `final_credit_cents` is
    set to that amount ... `FINALIZED` and `RESOLVED` are terminal for the
    credit."

    Design: Difficulty/compensating_invariant/dispute_then_resolve_conserves_door_credit_balance
    """
    env = setup_delivered_shipment(
        network_code="N18B", region="R18", planned_dozens=40, dozens_shipped=20,
    )
    nid, did, sid = env["network"]["id"], env["door"]["id"], env["shipment"]["id"]

    credit = create_stale_pull(nid, did, sid, 5)
    validate_success(api.dispute_stale_credit(nid, did, credit["id"], dmh(did)))

    resp = api.resolve_stale_credit(nid, did, credit["id"], {"resolution_credit_cents": 2500}, NA)
    resolved = validate_success(resp)
    assert resolved["credit_state"] == "RESOLVED"
    assert resolved["final_credit_cents"] == 2500

    fetched = validate_success(api.get_stale_credit(nid, did, credit["id"], dmh(did)))
    assert fetched["credit_state"] == "RESOLVED"
    assert fetched["final_credit_cents"] == 2500
