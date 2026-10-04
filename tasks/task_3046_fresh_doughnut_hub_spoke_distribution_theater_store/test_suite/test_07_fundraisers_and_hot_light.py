"""Fundraiser orders and hot-light windows: tiered marginal pricing, the
approval renegotiation loop, allocation ordering, pickup code enforcement,
ops-run expiry, theater-only windows, freshness gating, demand caps, and
single-lit exclusion."""
from test_helpers import (
    TEST_USERS,
    ApiErrorId,
    get_success_data,
    validate_error,
    validate_paginated,
    validate_success,
)
from test_helpers.fixtures import (
    commit_batch,
    create_batch,
    create_completed_batch,
    create_door,
    create_fundraiser_order,
    create_hot_light_window,
    create_mix_plan,
    create_published_mix_plan,
    create_variety,
    hub_version,
    publish_mix_plan,
    setup_hub_with_line,
    setup_lit_window,
    setup_ready_fundraiser,
    upsert_line,
)
from test_helpers.test_users import make_door_manager_headers as dmh

NA = TEST_USERS["network_admin_headers"]
HM = TEST_USERS["hub_manager_headers"]


# ---------------------------------------------------------------------------
# Difficulty/combinatorial_formula/fundraiser_pricing_marginal_tiers_with_per_line_rounding
# ---------------------------------------------------------------------------

def test_fundraiser_pricing_charity_per_line_rounding(api):
    """PRD §3.7: "The rounding order is pinned and nested: each implied dozen
    line is priced at its tier rate, any organization discount is applied to
    that line, and the line is rounded half-up to integer cents before the
    lines are summed into the quote. The discount is an
    `organization_discount_pct` that defaults to zero; when the organization
    is flagged as a registered licensed charity at approval time, a 0.10
    discount applies per dozen line before rounding."

    Design: Difficulty/combinatorial_formula/fundraiser_pricing_marginal_tiers_with_per_line_rounding
    """
    network, hub, _line = setup_hub_with_line(network_code="N3", hub_code="H3", region="R3",
                                              capacity=1000)
    door = create_door(network["id"], door_kind="THEATER", ownership="COMPANY", region="R3")
    order = create_fundraiser_order(
        network["id"], door["id"],
        organization_name="Licensed Charity Org", requested_dozens=30,
        pickup_at="2026-09-03T10:00:00Z",
    )
    resp = api.approve_fundraiser_order(network["id"], door["id"], order["id"], dmh(door["id"]))
    approved = validate_success(resp)
    assert approved["fundraiser_status"] == "APPROVED"
    # Charity variant, per-line rounding: 25*round(700*0.9) + 5*round(650*0.9)
    # == 25*630 + 5*585 == 18675.
    assert approved["quoted_total_cents"] == 18675, (
        f"expected 18675 (25*630 + 5*585), got {approved['quoted_total_cents']}"
    )


def test_fundraiser_pricing_charity_differs_from_flat_discount(api):
    """PRD §3.7: "Pricing is marginal and tiered by cumulative dozens: the
    first 25 dozen of the order price at 700 cents per dozen, dozens 26
    through 100 price at 650 cents per dozen, and every dozen beyond 100
    prices at 600 cents."

    Design: Difficulty/combinatorial_formula/fundraiser_pricing_marginal_tiers_with_per_line_rounding
    """
    network, hub, _line = setup_hub_with_line(network_code="N3B", hub_code="H3B", region="R3",
                                              capacity=1000)
    door = create_door(network["id"], door_kind="THEATER", ownership="COMPANY", region="R3")
    order = create_fundraiser_order(
        network["id"], door["id"],
        organization_name="Licensed Charity Org", requested_dozens=30,
        pickup_at="2026-09-03T10:00:00Z",
    )
    approved = validate_success(
        api.approve_fundraiser_order(network["id"], door["id"], order["id"], dmh(door["id"]))
    )
    # Marginal tiering: the first 25 dozen stay at tier A, only dozens 26-30
    # price at tier B — a flat 0.9*(25*700+5*650) == 18225 would be wrong.
    assert approved["quoted_total_cents"] == 18675
    assert approved["quoted_total_cents"] != 18225


# ---------------------------------------------------------------------------
# Difficulty/boundary_precision_check/fundraiser_tier_boundary_25_vs_26_dozens
# ---------------------------------------------------------------------------

def test_fundraiser_tier_boundary_25_dozens(api):
    """PRD §3.7: "the first 25 dozen of the order price at 700 cents per
    dozen".

    Design: Difficulty/boundary_precision_check/fundraiser_tier_boundary_25_vs_26_dozens
    """
    network, hub, _line = setup_hub_with_line(network_code="N12", hub_code="H12", region="R12",
                                              capacity=1000)
    door = create_door(network["id"], door_kind="THEATER", ownership="COMPANY", region="R12")
    order = create_fundraiser_order(
        network["id"], door["id"], organization_name="Org A", requested_dozens=25,
        pickup_at="2026-09-03T10:00:00Z",
    )
    approved = validate_success(
        api.approve_fundraiser_order(network["id"], door["id"], order["id"], dmh(door["id"]))
    )
    assert approved["quoted_total_cents"] == 17500  # 25 * 700


def test_fundraiser_tier_boundary_26_dozens(api):
    """PRD §3.7: "dozens 26 through 100 price at 650 cents per dozen" — the
    26th dozen is priced at the marginal tier rate, so a 26-dozen order
    quotes 25*700 + 1*650.

    Design: Difficulty/boundary_precision_check/fundraiser_tier_boundary_25_vs_26_dozens
    """
    network, hub, _line = setup_hub_with_line(network_code="N12B", hub_code="H12B", region="R12",
                                              capacity=1000)
    door = create_door(network["id"], door_kind="THEATER", ownership="COMPANY", region="R12")
    order = create_fundraiser_order(
        network["id"], door["id"], organization_name="Org B", requested_dozens=26,
        pickup_at="2026-09-03T10:00:00Z",
    )
    approved = validate_success(
        api.approve_fundraiser_order(network["id"], door["id"], order["id"], dmh(door["id"]))
    )
    assert approved["quoted_total_cents"] == 18150, (
        f"25*700 + 1*650 == 18150, got {approved['quoted_total_cents']}"
    )


# ---------------------------------------------------------------------------
# Difficulty/non_linear_state_machine/fundraiser_order_approval_cycle_returns_to_submitted
# ---------------------------------------------------------------------------

def test_fundraiser_approval_cycle_returns_to_submitted(api):
    """PRD §3.7: "a `DoorManager` can return an approved order for changes,
    cycling it back to `SUBMITTED` and clearing `quoted_total_cents` to null
    — it is recomputed from current tiers on the next approval, which is the
    intended renegotiation loop."

    Design: Difficulty/non_linear_state_machine/fundraiser_order_approval_cycle_returns_to_submitted
    """
    network, hub, _line = setup_hub_with_line(network_code="N5", hub_code="H5", region="R5",
                                              capacity=1000)
    door = create_door(network["id"], door_kind="THEATER", ownership="COMPANY", region="R5")
    order = create_fundraiser_order(
        network["id"], door["id"], organization_name="Band Boosters", requested_dozens=10,
        pickup_at="2026-09-03T10:00:00Z",
    )
    approved = validate_success(
        api.approve_fundraiser_order(network["id"], door["id"], order["id"], dmh(door["id"]))
    )
    assert approved["quoted_total_cents"] == 7000

    returned = validate_success(
        api.return_fundraiser_order_for_changes(network["id"], door["id"], order["id"], dmh(door["id"]))
    )
    assert returned["fundraiser_status"] == "SUBMITTED"
    assert returned.get("quoted_total_cents") is None

    reapproved = validate_success(
        api.approve_fundraiser_order(network["id"], door["id"], order["id"], dmh(door["id"]))
    )
    assert reapproved["fundraiser_status"] == "APPROVED"
    assert reapproved["quoted_total_cents"] == 7000, (
        "10 dozen at 700 with no discount recomputes to 7000 on the second approval"
    )


def test_fundraiser_approval_cycle_clears_quote(api):
    """PRD §3.7: "cycling it back to `SUBMITTED` and clearing
    `quoted_total_cents` to null".

    Design: Difficulty/non_linear_state_machine/fundraiser_order_approval_cycle_returns_to_submitted
    """
    network, hub, _line = setup_hub_with_line(network_code="N5C", hub_code="H5C", region="R5",
                                              capacity=1000)
    door = create_door(network["id"], door_kind="THEATER", ownership="COMPANY", region="R5")
    order = create_fundraiser_order(
        network["id"], door["id"], organization_name="Band Boosters", requested_dozens=10,
        pickup_at="2026-09-03T10:00:00Z",
    )
    validate_success(
        api.approve_fundraiser_order(network["id"], door["id"], order["id"], dmh(door["id"]))
    )
    returned = validate_success(
        api.return_fundraiser_order_for_changes(network["id"], door["id"], order["id"], dmh(door["id"]))
    )
    assert returned["fundraiser_status"] == "SUBMITTED"
    assert returned.get("quoted_total_cents") is None

    fetched = validate_success(
        api.get_fundraiser_order(network["id"], door["id"], order["id"], dmh(door["id"]))
    )
    assert fetched.get("quoted_total_cents") is None


# ---------------------------------------------------------------------------
# Difficulty/combinatorial_formula/mix_allocation_circular_ordering_waterfall
# ---------------------------------------------------------------------------

def test_mix_allocation_fundraiser_first_waterfall(api):
    """PRD §3.3: "Allocation proceeds in a pinned order — fixed before any
    remainder is computed: first, fundraiser reservations in `READY` or
    `SCHEDULED`, ordered by `pickup_at` ascending ... second, mix plan lines
    of `PUBLISHED` or `LOCKED` plans ... Each bucket in turn takes the
    smaller of its remaining need and the remaining available dozens".

    Design: Difficulty/combinatorial_formula/mix_allocation_circular_ordering_waterfall
    """
    network, hub, line = setup_hub_with_line(
        network_code="N4", hub_code="H4", region="R4", capacity=500,
        line_overrides={"service_interval_hours": 500},
    )
    variety = create_variety(network["id"], variety_code="GLAZED", collection_kind="CORE")
    door = create_door(
        network["id"], door_kind="SPOKE", ownership="FRANCHISE", region="R4", hub_id=hub["id"]
    )
    plan = create_mix_plan(network["id"], door["id"])
    line_rec = upsert_line(network["id"], door["id"], plan["id"], variety["id"], 40)
    publish_mix_plan(network["id"], door["id"], plan["id"])

    order = create_fundraiser_order(
        network["id"], door["id"], organization_name="School PTA", requested_dozens=20,
        pickup_at="2026-09-01T15:00:00Z",
    )
    validate_success(
        api.approve_fundraiser_order(network["id"], door["id"], order["id"], dmh(door["id"]))
    )

    batch = create_batch(network["id"], hub["id"], line["id"], planned_dozens=50)
    validate_success(
        api.commit_batch(
            network["id"], hub["id"], batch["id"],
            {"expected_hub_version": hub_version(network["id"], hub["id"])}, HM,
        )
    )
    order = validate_success(
        api.schedule_fundraiser_order(network["id"], door["id"], order["id"], dmh(door["id"]))
    )
    validate_success(api.start_batch(network["id"], hub["id"], batch["id"], HM))
    completed = validate_success(
        api.complete_batch(network["id"], hub["id"], batch["id"], {"produced_dozens": 50}, HM)
    )
    assert completed["batch_status"] == "COMPLETED", "yield 50/50 == 1.0 >= 0.85"

    # Fundraiser reservation bucket (20) fills first; the mix line gets
    # min(40 need, 50 - 20 available) == 30.
    lines, _meta = validate_paginated(
        api.list_mix_plan_lines(network["id"], door["id"], plan["id"], dmh(door["id"]))
    )
    assert len(lines) == 1
    assert lines[0]["allocated_dozens"] == 30, (
        f"fundraiser-first ordering: line allocation must be 30, got {lines[0]['allocated_dozens']}"
    )
    order_after = validate_success(
        api.get_fundraiser_order(network["id"], door["id"], order["id"], dmh(door["id"]))
    )
    assert order_after["fundraiser_status"] == "SCHEDULED"


def test_mix_allocation_waterfall_leaves_batch_completed(api):
    """PRD §3.3: "If the produced dozens reach at least 0.85 times the planned
    dozens — the minimum yield rate — the batch lands in `COMPLETED`" and
    "the mix allocation waterfall runs for that production date across the
    hub's doors."

    Design: Difficulty/combinatorial_formula/mix_allocation_circular_ordering_waterfall
    """
    network, hub, line = setup_hub_with_line(
        network_code="N4B", hub_code="H4B", region="R4", capacity=500,
        line_overrides={"service_interval_hours": 500},
    )
    variety = create_variety(network["id"], variety_code="GLAZED", collection_kind="CORE")
    door = create_door(
        network["id"], door_kind="SPOKE", ownership="FRANCHISE", region="R4", hub_id=hub["id"]
    )
    plan = create_published_mix_plan(network["id"], door["id"], variety["id"], planned_dozens=40)

    order = create_fundraiser_order(
        network["id"], door["id"], organization_name="School PTA", requested_dozens=20,
        pickup_at="2026-09-01T15:00:00Z",
    )
    validate_success(
        api.approve_fundraiser_order(network["id"], door["id"], order["id"], dmh(door["id"]))
    )
    batch = create_batch(network["id"], hub["id"], line["id"], planned_dozens=50)
    commit_batch(network["id"], hub["id"], batch["id"])
    validate_success(
        api.schedule_fundraiser_order(network["id"], door["id"], order["id"], dmh(door["id"]))
    )
    validate_success(api.start_batch(network["id"], hub["id"], batch["id"], HM))
    completed = validate_success(
        api.complete_batch(network["id"], hub["id"], batch["id"], {"produced_dozens": 50}, HM)
    )
    assert completed["batch_status"] == "COMPLETED"
    # The whole available pool is consumed: fundraiser 20 + line 30 == 50.
    lines, _meta = validate_paginated(
        api.list_mix_plan_lines(network["id"], door["id"], plan["id"], dmh(door["id"]))
    )
    assert lines[0]["allocated_dozens"] == 30


# ---------------------------------------------------------------------------
# Corner/state_machines/fundraiser_fulfill_wrong_pickup_code
# ---------------------------------------------------------------------------

def test_fundraiser_fulfill_wrong_pickup_code(api):
    """PRD §3.7: "Fulfillment is the handshake: the driver of the pickup
    presents the code, the request carries `pickup_code`, a mismatch is
    rejected with `ERR_PICKUP_CODE_MISMATCH` (HTTP 422)".

    Design: Corner/state_machines/fundraiser_fulfill_wrong_pickup_code
    """
    env = setup_ready_fundraiser(network_code="NF", region="RF")
    nid, did, oid = env["network"]["id"], env["door"]["id"], env["order"]["id"]
    get_success_data(api.set_clock("2026-09-01T15:30:00Z", NA))

    resp = api.fulfill_fundraiser_order(nid, did, oid, {"pickup_code": "WRONGCODE"}, dmh(did))
    validate_error(resp, ApiErrorId.ERR_PICKUP_CODE_MISMATCH)

    after = validate_success(api.get_fundraiser_order(nid, did, oid, dmh(did)))
    assert after["fundraiser_status"] == "READY"


# ---------------------------------------------------------------------------
# Corner/state_machines/ready_fundraiser_expires_at_ops_run_past_grace
# ---------------------------------------------------------------------------

def test_ready_fundraiser_expires_at_ops_run_past_grace(api):
    """PRD §3.9: "Each checkpoint ... auto-expires any `READY` fundraiser
    orders whose pickup grace has elapsed".
    PRD §3.7: "Orders still `READY` when the clock passes `pickup_at` plus
    the grace window expire automatically".

    Design: Corner/state_machines/ready_fundraiser_expires_at_ops_run_past_grace
    """
    env = setup_ready_fundraiser(
        network_code="NX9", region="RX9", pickup_at="2026-09-01T10:00:00Z",
        organization_name="Scouts",
    )
    nid, did, oid = env["network"]["id"], env["door"]["id"], env["order"]["id"]
    get_success_data(api.set_clock("2026-09-02T00:00:00Z", NA))

    resp = api.run_ops_run(nid, NA)
    data = validate_success(resp, expected_status=201)
    assert data["expired_order_count"] == 1

    after = validate_success(api.get_fundraiser_order(nid, did, oid, dmh(did)))
    assert after["fundraiser_status"] == "EXPIRED"


# ---------------------------------------------------------------------------
# Corner/state_machines/hot_light_on_non_theater_door_rejected
# ---------------------------------------------------------------------------

def test_hot_light_on_non_theater_door_rejected(api):
    """PRD §3.8: "only `THEATER` doors may have windows — scheduling one
    against any other door kind is a territory violation."
    PRD §5: `ERR_TERRITORY_VIOLATION` (422).

    Design: Corner/state_machines/hot_light_on_non_theater_door_rejected
    """
    network, hub, _line = setup_hub_with_line(network_code="NH", hub_code="HH", region="RH")
    door = create_door(
        network["id"], door_kind="SPOKE", ownership="FRANCHISE", region="RH", hub_id=hub["id"]
    )
    resp = api.create_hot_light_window(
        network["id"], door["id"],
        {"lit_start": "2026-09-01T06:00:00Z", "lit_end": "2026-09-01T08:00:00Z"},
        dmh(door["id"]),
    )
    validate_error(resp, ApiErrorId.ERR_TERRITORY_VIOLATION)


# ---------------------------------------------------------------------------
# Corner/calculations/hot_light_demand_cap_thresholds
# ---------------------------------------------------------------------------

def test_hot_light_demand_cap_low_band(api):
    """PRD §3.8: "when that fresh figure reaches at least 120 dozen the cap
    is 90 minutes, when it reaches at least 30 dozen but fewer than 120 the
    cap is 45 minutes, and below 30 dozen the cap is zero. The granted
    extension is the smaller of the request and the cap".

    Design: Corner/calculations/hot_light_demand_cap_thresholds
    """
    env = setup_lit_window(network_code="NHD", batch_dozens=40, ignite_at="2026-09-01T07:00:00Z")
    nid, did, wid = env["network"]["id"], env["door"]["id"], env["window"]["id"]

    resp = api.extend_hot_light_window(
        nid, did, wid, {"demand_response_extend_minutes": 45}, dmh(did)
    )
    extended = validate_success(resp)
    assert extended["window_status"] == "EXTENDED"
    assert extended["lit_end"] == "2026-09-01T08:45:00Z", (
        f"08:00 + 45 minutes == 08:45, got {extended['lit_end']}"
    )


# ---------------------------------------------------------------------------
# Difficulty/priority_pair_validation_conflict/safety_vs_temporal_on_hot_light_ignite
# ---------------------------------------------------------------------------

def test_hot_light_ignite_without_fresh_batch_rejected(api):
    """PRD §3.8: "Ignition — `SCHEDULED` → `LIT` — happens automatically when
    the clock reaches `lit_start`, or early at the door manager's hand, but
    only when at least one batch completed today at the door's hub still has
    `fresh_until` in the future ... Lighting without a fresh batch behind it
    is rejected with `ERR_FRESHNESS_VIOLATION`."

    Design: Difficulty/priority_pair_validation_conflict/safety_vs_temporal_on_hot_light_ignite
    """
    network, hub, _line = setup_hub_with_line(network_code="N10", hub_code="H10", region="R10")
    door = create_door(network["id"], door_kind="THEATER", ownership="COMPANY", region="R10")
    window = create_hot_light_window(
        network["id"], door["id"],
        lit_start="2026-09-01T06:00:00Z", lit_end="2026-09-01T08:00:00Z",
    )
    get_success_data(api.set_clock("2026-09-01T07:00:00Z", NA))

    resp = api.ignite_hot_light_window(network["id"], door["id"], window["id"], dmh(door["id"]))
    validate_error(resp, ApiErrorId.ERR_FRESHNESS_VIOLATION)

    after = validate_success(
        api.get_hot_light_window(network["id"], door["id"], window["id"], dmh(door["id"]))
    )
    assert after["window_status"] == "SCHEDULED"


def test_hot_light_ignite_without_fresh_batch_leaves_window_scheduled(api):
    """PRD §3.8: "Lighting without a fresh batch behind it is rejected with
    `ERR_FRESHNESS_VIOLATION`" — a rejected ignite must not move the window
    out of `SCHEDULED`.

    Design: Difficulty/priority_pair_validation_conflict/safety_vs_temporal_on_hot_light_ignite
    """
    network, hub, _line = setup_hub_with_line(network_code="N10B", hub_code="H10B", region="R10")
    door = create_door(network["id"], door_kind="THEATER", ownership="COMPANY", region="R10")
    window = create_hot_light_window(
        network["id"], door["id"],
        lit_start="2026-09-01T06:00:00Z", lit_end="2026-09-01T08:00:00Z",
    )
    get_success_data(api.set_clock("2026-09-01T07:00:00Z", NA))

    resp = api.ignite_hot_light_window(network["id"], door["id"], window["id"], dmh(door["id"]))
    validate_error(resp, ApiErrorId.ERR_FRESHNESS_VIOLATION)

    after = validate_success(
        api.get_hot_light_window(network["id"], door["id"], window["id"], dmh(door["id"]))
    )
    assert after["window_status"] == "SCHEDULED"


# ---------------------------------------------------------------------------
# Difficulty/resource_temporal_overlap/hot_light_windows_single_lit_exclusion
# ---------------------------------------------------------------------------

def test_hot_light_second_ignite_rejected_while_first_extended(api):
    """PRD §3.8: "only when no other window for the door is currently `LIT`
    or `EXTENDED`" — igniting a second window while the first is `EXTENDED`
    is rejected even though the windows did not overlap at creation.

    Design: Difficulty/resource_temporal_overlap/hot_light_windows_single_lit_exclusion
    """
    env = setup_lit_window(
        network_code="N16", batch_dozens=200,
        lit_start="2026-09-01T06:00:00Z", lit_end="2026-09-01T09:00:00Z",
        ignite_at="2026-09-01T07:00:00Z",
    )
    nid, did = env["network"]["id"], env["door"]["id"]
    window_a = env["window"]

    # Extend W_a by 90 (fresh stock 200 >= 120 -> cap 90): lit_end 09:00 -> 10:30.
    extended = validate_success(
        api.extend_hot_light_window(
            nid, did, window_a["id"], {"demand_response_extend_minutes": 90}, dmh(did)
        )
    )
    assert extended["window_status"] == "EXTENDED"
    assert extended["lit_end"] == "2026-09-01T10:30:00Z"

    window_b = create_hot_light_window(
        nid, did, lit_start="2026-09-01T10:00:00Z", lit_end="2026-09-01T12:00:00Z"
    )
    get_success_data(api.set_clock("2026-09-01T10:15:00Z", NA))

    resp = api.ignite_hot_light_window(nid, did, window_b["id"], dmh(did))
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE)

    after_b = validate_success(api.get_hot_light_window(nid, did, window_b["id"], dmh(did)))
    assert after_b["window_status"] == "SCHEDULED"


def test_hot_light_extension_moves_lit_end_by_granted_minutes(api):
    """PRD §3.8: "A granted extension moves the window to `EXTENDED` and
    pushes `lit_end` out by the granted minutes."

    Design: Difficulty/resource_temporal_overlap/hot_light_windows_single_lit_exclusion
    """
    env = setup_lit_window(
        network_code="N16B", batch_dozens=200,
        lit_start="2026-09-01T06:00:00Z", lit_end="2026-09-01T09:00:00Z",
        ignite_at="2026-09-01T07:00:00Z",
    )
    nid, did, wid = env["network"]["id"], env["door"]["id"], env["window"]["id"]

    extended = validate_success(
        api.extend_hot_light_window(nid, did, wid, {"demand_response_extend_minutes": 90}, dmh(did))
    )
    assert extended["window_status"] == "EXTENDED"
    assert extended["lit_end"] == "2026-09-01T10:30:00Z"
