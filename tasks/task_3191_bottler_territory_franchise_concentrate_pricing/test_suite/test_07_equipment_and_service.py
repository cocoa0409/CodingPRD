"""Cold-drink equipment: placement interval semantics, service windows, budget."""
import pytest

from test_helpers import (
    api_client,
    TEST_USERS,
    ApiErrorId,
    validate_error,
    validate_success,
    get_success_data,
    validate_paginated,
    seed_active_agreement,
    create_customer,
    create_equipment,
    place_equipment,
    create_service_window,
    ops_headers,
)

PA = TEST_USERS["platform_admin_headers"]
FT = TEST_USERS["field_technician_headers"]


def test_service_windows_half_open_adjacency_allowed(api):
    """PRD §3.5: "Windows sharing the same `technician_label` must not overlap;
    because the interval is half-open, adjacency — one window ending exactly
    when another begins — is allowed. An overlap on the same label is rejected
    with `ERR_SERVICE_WINDOW_OVERLAP` (HTTP 409)."
    PRD §3.5: "On success, the window is created, its `cost_cents` is added
    into the agreement's `service_spent_cents`, and the first window against a
    `PLACED` unit moves that unit to `UNDER_SERVICE`."

    Design: Difficulty/resource_temporal_overlap/service_windows_half_open_adjacency_allowed
    """
    env = seed_active_agreement()
    cust = create_customer(env)
    eq = create_equipment(env)
    place_equipment(env, eq["id"], cust["id"])
    create_service_window(
        eq["id"], technician_label="T-7",
        window_start="2026-10-01T10:00:00Z", window_end="2026-10-01T11:00:00Z",
        cost_cents=100,
    )
    # adjacent: starts exactly when the previous ends -> allowed
    r = api_client.create_service_window(
        eq["id"],
        {"technician_label": "T-7", "window_start": "2026-10-01T11:00:00Z",
         "window_end": "2026-10-01T12:00:00Z", "cost_cents": 100},
        FT,
    )
    assert r.status_code == 201, f"adjacent half-open window must be allowed: {r.text}"
    # overlapping the 11:00-12:00 window -> rejected
    r = api_client.create_service_window(
        eq["id"],
        {"technician_label": "T-7", "window_start": "2026-10-01T11:59:00Z",
         "window_end": "2026-10-01T13:00:00Z", "cost_cents": 100},
        FT,
    )
    validate_error(r, ApiErrorId.ERR_SERVICE_WINDOW_OVERLAP.value)
    assert r.status_code == 409
    agreement = get_success_data(api_client.get_agreement(env["agreement"]["id"], PA))
    assert agreement["service_spent_cents"] == 200, "only accepted windows charge the budget"


def test_service_windows_overlap_rejected_on_same_label(api):
    """PRD §3.5: "Windows sharing the same `technician_label` must not overlap;
    because the interval is half-open, adjacency — one window ending exactly
    when another begins — is allowed. An overlap on the same label is rejected
    with `ERR_SERVICE_WINDOW_OVERLAP` (HTTP 409)."

    Design: Difficulty/resource_temporal_overlap/service_windows_half_open_adjacency_allowed
    """
    env = seed_active_agreement()
    cust = create_customer(env)
    eq = create_equipment(env)
    place_equipment(env, eq["id"], cust["id"])
    create_service_window(
        eq["id"], technician_label="T-7",
        window_start="2026-10-01T10:00:00Z", window_end="2026-10-01T11:00:00Z",
        cost_cents=100,
    )
    r = api_client.create_service_window(
        eq["id"],
        {"technician_label": "T-7", "window_start": "2026-10-01T10:30:00Z",
         "window_end": "2026-10-01T11:30:00Z", "cost_cents": 100},
        FT,
    )
    validate_error(r, ApiErrorId.ERR_SERVICE_WINDOW_OVERLAP.value)
    agreement = get_success_data(api_client.get_agreement(env["agreement"]["id"], PA))
    assert agreement["service_spent_cents"] == 100


def test_equipment_placement_closed_interval_touching_dates_conflict(api):
    """PRD §3.5: "The placement interval must not overlap any other placement
    in the same unit's history — and because placement intervals are closed,
    adjacency counts as overlap: a prior placement ending on exactly the date
    the new one begins is still a conflict, rejected with
    `ERR_EQUIPMENT_PLACEMENT_OVERLAP` (HTTP 409)."
    PRD §3.5: "Successful placement stamps `customer_id`, `placed_from`, and
    `placed_until`, moves the unit to `PLACED`, and increments its `version`."

    Design: Difficulty/resource_temporal_overlap/equipment_placement_closed_interval_touching_dates_conflict
    """
    env = seed_active_agreement()
    c1 = create_customer(env, name="QuickMart 12")
    c2 = create_customer(env, name="QuickMart 13")
    eq = create_equipment(env)
    place_equipment(env, eq["id"], c1["id"], placed_from="2026-09-15", placed_until="2026-09-30")
    r = api_client.uninstall_equipment(eq["id"], ops_headers(env))
    assert r.status_code == 200
    r = api_client.place_equipment(
        eq["id"],
        {"customer_id": c2["id"], "placed_from": "2026-09-30", "placed_until": "2026-10-31"},
        ops_headers(env),
    )
    validate_error(r, ApiErrorId.ERR_EQUIPMENT_PLACEMENT_OVERLAP.value)
    assert r.status_code == 409
    r = api_client.place_equipment(
        eq["id"],
        {"customer_id": c2["id"], "placed_from": "2026-10-01", "placed_until": "2026-10-31"},
        ops_headers(env),
    )
    assert r.status_code == 200, "non-touching placement must be accepted"
    eq_after = get_success_data(api_client.get_equipment(eq["id"], PA))
    assert eq_after["status"] == "PLACED"
    assert eq_after["customer_id"] == c2["id"]


def test_equipment_placement_non_touching_after_uninstall_succeeds(api):
    """PRD §3.5: "The placement interval must not overlap any other placement
    in the same unit's history — and because placement intervals are closed,
    adjacency counts as overlap: a prior placement ending on exactly the date
    the new one begins is still a conflict, rejected with
    `ERR_EQUIPMENT_PLACEMENT_OVERLAP` (HTTP 409)."

    Design: Difficulty/resource_temporal_overlap/equipment_placement_closed_interval_touching_dates_conflict
    """
    env = seed_active_agreement()
    c1 = create_customer(env, name="QuickMart 12")
    eq = create_equipment(env)
    place_equipment(env, eq["id"], c1["id"], placed_from="2026-09-15", placed_until="2026-09-30")
    r = api_client.uninstall_equipment(eq["id"], ops_headers(env))
    assert r.status_code == 200
    r = api_client.place_equipment(
        eq["id"],
        {"customer_id": c1["id"], "placed_from": "2026-10-01", "placed_until": "2026-10-31"},
        ops_headers(env),
    )
    assert r.status_code == 200
    eq_after = get_success_data(api_client.get_equipment(eq["id"], PA))
    assert eq_after["placed_from"] == "2026-10-01"
    assert eq_after["placed_until"] == "2026-10-31"


def test_equipment_place_twice_rejected(api):
    """PRD §3.5: "Placement requires the unit to be `IN_WAREHOUSE` (otherwise
    `ERR_EQUIPMENT_NOT_IN_WAREHOUSE`, HTTP 409) and the target customer to be
    `ACTIVE`."

    Design: Corner/state_machines/equipment_place_twice_rejected
    """
    env = seed_active_agreement()
    cust = create_customer(env)
    eq = create_equipment(env)
    place_equipment(env, eq["id"], cust["id"], placed_from="2026-09-15", placed_until="2026-12-31")
    r = api_client.place_equipment(
        eq["id"],
        {"customer_id": cust["id"], "placed_from": "2026-10-01", "placed_until": "2026-11-30"},
        ops_headers(env),
    )
    validate_error(r, ApiErrorId.ERR_EQUIPMENT_NOT_IN_WAREHOUSE.value)
    assert r.status_code == 409
    eq_after = get_success_data(api_client.get_equipment(eq["id"], PA))
    assert eq_after["placed_from"] == "2026-09-15", "original placement must be untouched"


def test_equipment_place_then_uninstall_conserves_pool_counts(api):
    """PRD §2.9: "Cold-drink equipment obeys a conservation invariant:
    placement and uninstallation are paired operations. Placing a unit
    transitions it from `IN_WAREHOUSE` to `PLACED` and stamps the placement
    site and dates; uninstalling returns a `PLACED` unit to `IN_WAREHOUSE` and
    clears the placement fields."
    PRD §3.5: "**Uninstall** returns a `PLACED` unit to `IN_WAREHOUSE` and
    clears those three placement fields."

    Design: Difficulty/compensating_invariant/equipment_place_then_uninstall_conserves_pool_counts
    """
    env = seed_active_agreement()
    cust = create_customer(env)
    eq = create_equipment(env)
    assert eq["status"] == "IN_WAREHOUSE"
    place_equipment(env, eq["id"], cust["id"])
    r = api_client.uninstall_equipment(eq["id"], ops_headers(env))
    assert r.status_code == 200
    eq_after = get_success_data(api_client.get_equipment(eq["id"], PA))
    assert eq_after["status"] == "IN_WAREHOUSE"
    assert eq_after["customer_id"] is None
    assert eq_after["placed_from"] is None
    assert eq_after["placed_until"] is None


def test_equipment_pool_counts_invariant_across_place_uninstall(api):
    """PRD §2.9: "Cold-drink equipment obeys a conservation invariant:
    placement and uninstallation are paired operations. Placing a unit
    transitions it from `IN_WAREHOUSE` to `PLACED` and stamps the placement
    site and dates; uninstalling returns a `PLACED` unit to `IN_WAREHOUSE` and
    clears the placement fields. Nothing else may move a unit between the
    warehouse and the field, and a unit that is not `IN_WAREHOUSE` cannot be
    placed (rejected with `ERR_EQUIPMENT_NOT_IN_WAREHOUSE`, HTTP 409)."

    Design: Difficulty/compensating_invariant/equipment_place_then_uninstall_conserves_pool_counts
    """
    env = seed_active_agreement()
    cust = create_customer(env)
    eq = create_equipment(env)
    place_equipment(env, eq["id"], cust["id"])
    placed_eq = get_success_data(api_client.get_equipment(eq["id"], PA))
    assert placed_eq["status"] == "PLACED"
    assert placed_eq["customer_id"] == cust["id"]
    assert placed_eq["placed_from"] == "2026-09-15"
    assert placed_eq["placed_until"] == "2026-12-31"
    r = api_client.uninstall_equipment(eq["id"], ops_headers(env))
    assert r.status_code == 200
    data, meta = validate_paginated(
        api_client.list_equipment(PA, params={"agreement_id": env["agreement"]["id"]})
    )
    assert meta["total_count"] == 1, "the pool still holds exactly the one unit"
    assert data[0]["status"] == "IN_WAREHOUSE"
    assert data[0]["customer_id"] is None
