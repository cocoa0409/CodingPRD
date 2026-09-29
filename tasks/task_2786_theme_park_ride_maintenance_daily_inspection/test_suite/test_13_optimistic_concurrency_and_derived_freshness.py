"""Stale-parent guards and read-time freshness of every derived field.

The two optimistic-concurrency guards are shown to fire ahead of the domain checks
they protect, and the derivations that depend on the logical clock are walked across
their exact boundaries — with the mutation response itself proving that no second
read is needed for derived state to settle.
"""

import pytest

from test_helpers import (
    ADMIN,
    MANAGER,
    TECHNICIAN,
    api_client,
    assert_attraction,
    assert_component,
    assert_inspection_template,
    assert_instant_equals,
    assert_shop_bay,
    assert_work_order,
    factories,
    fixtures,
    validate_error,
    validate_paginated,
    validate_success,
)

CLOCK_START = "2026-08-01T00:00:00.000Z"
CLOCK_START_DATE = "2026-08-01"


def _template_with_one_line(attraction_id: str, effective_from_date: str) -> dict:
    """A DRAFT revision carrying the single line activation requires."""
    template = fixtures.create_template(
        attraction_id, effective_from_date=effective_from_date
    )
    fixtures.append_line(
        template["id"], 1, severity_class="ADVISORY", description="Revision line"
    )
    return template


def _read_template(template_id: str) -> dict:
    return validate_success(api_client.get_inspection_template(template_id, ADMIN))


def test_a_stale_attraction_version_refuses_activation_until_it_is_re_read():
    """PRD §2.6: "The supplied `expected_attraction_version` or
    `expected_shop_bay_version` equals the current `version` of the named parent row —
    otherwise `ERR_STALE_ATTRACTION_VERSION` or `ERR_STALE_SHOP_BAY_VERSION` (412)."

    Design: Corner/complexity_layers/stale_expected_attraction_version_on_activate_returns_412_then_the_fresh_version_succeeds
    """
    attraction = fixtures.create_attraction(
        name="OCC Attraction Ride",
        park_area="FRONTIER",
        manufacturer="Vekoma",
        model_code="OC-1",
        ride_class="THRILL",
        theoretical_hourly_capacity=800,
        min_operators_required=2,
        parts_budget_cents=1000000,
    )
    stale_version = attraction["version"]
    first = _template_with_one_line(attraction["id"], CLOCK_START_DATE)
    second = _template_with_one_line(attraction["id"], "2026-08-02")

    validate_success(
        api_client.activate_inspection_template(
            first["id"],
            factories.activate_inspection_template_payload(stale_version),
            ADMIN,
        )
    )
    after_first = fixtures.read_attraction(attraction["id"])
    assert_attraction(after_first)
    assert after_first["active_template_id"] == first["id"]
    assert after_first["version"] == stale_version + 1, (
        "activation increments the attraction's version by exactly one"
    )

    validate_error(
        api_client.activate_inspection_template(
            second["id"],
            factories.activate_inspection_template_payload(stale_version),
            ADMIN,
        ),
        "ERR_STALE_ATTRACTION_VERSION",
        412,
    )
    assert _read_template(second["id"])["status"] == "DRAFT"
    assert _read_template(first["id"])["status"] == "ACTIVE"
    unmoved = fixtures.read_attraction(attraction["id"])
    assert unmoved["version"] == stale_version + 1, "the refusal moved no version"
    assert unmoved["active_template_id"] == first["id"]

    fresh_version = unmoved["version"]
    validate_success(
        api_client.activate_inspection_template(
            second["id"],
            factories.activate_inspection_template_payload(fresh_version),
            ADMIN,
        )
    )
    promoted = _read_template(second["id"])
    assert_inspection_template(promoted)
    assert promoted["status"] == "ACTIVE"
    assert _read_template(first["id"])["status"] == "SUPERSEDED", (
        "the previously active revision is retired by the switch"
    )
    final = fixtures.read_attraction(attraction["id"])
    assert final["active_template_id"] == second["id"]
    assert final["version"] == fresh_version + 1, (
        "two successful activations produced exactly two increments"
    )


def test_a_stale_bay_version_is_refused_before_the_capacity_check_is_reached():
    """PRD §3.9: "Three refusals therefore compete on this one operation, and per the
    ladder in §2.6 they resolve in this order: the stale-bay check first with
    `ERR_STALE_SHOP_BAY_VERSION`, then the component-installation check with
    `ERR_COMPONENT_ATTRACTION_MISMATCH`, then the bay-capacity check with
    `ERR_BAY_CAPACITY_CONFLICT`."

    Design: Corner/complexity_layers/stale_expected_shop_bay_version_on_overhaul_create_returns_412_then_the_fresh_version_succeeds
    """
    attraction = fixtures.create_attraction(
        name="OCC Bay Ride",
        park_area="SKYLINE",
        manufacturer="B&M",
        model_code="OB-1",
        ride_class="THRILL",
        theoretical_hourly_capacity=1000,
        min_operators_required=2,
        parts_budget_cents=1000000,
    )
    component = fixtures.create_component(
        attraction["id"],
        name="OCC Gearbox",
        component_type="GEARBOX",
        criticality="ESSENTIAL",
        ndt_interval_cycles=500000,
        ndt_interval_days=3650,
    )
    bay = fixtures.create_shop_bay("Bay OCC", 1)
    stale_version = bay["version"]

    first_order = validate_success(
        api_client.create_overhaul_work_order(
            factories.create_overhaul_work_order_payload(
                attraction["id"],
                component["id"],
                bay["id"],
                stale_version,
                window_start_date="2026-11-01",
                window_end_date="2026-11-05",
            ),
            MANAGER,
        ),
        201,
    )
    assert_work_order(first_order)
    booked_once = fixtures.read_shop_bay(bay["id"])
    assert_shop_bay(booked_once)
    assert booked_once["booked_order_count"] == 1
    assert booked_once["version"] == stale_version + 1

    validate_error(
        api_client.create_overhaul_work_order(
            factories.create_overhaul_work_order_payload(
                attraction["id"],
                component["id"],
                bay["id"],
                stale_version,
                window_start_date="2027-01-10",
                window_end_date="2027-01-15",
            ),
            MANAGER,
        ),
        "ERR_STALE_SHOP_BAY_VERSION",
        412,
    )
    refused = fixtures.read_shop_bay(bay["id"])
    assert refused["booked_order_count"] == 1, "the refused booking reserved no slot"
    assert refused["version"] == stale_version + 1
    _, refusal_meta = validate_paginated(
        api_client.list_overhaul_work_orders(
            MANAGER, params={"shop_bay_id": bay["id"]}
        )
    )
    assert refusal_meta["total_count"] == 1, "no work order row was created"

    fresh_version = refused["version"]
    second_order = validate_success(
        api_client.create_overhaul_work_order(
            factories.create_overhaul_work_order_payload(
                attraction["id"],
                component["id"],
                bay["id"],
                fresh_version,
                window_start_date="2027-01-10",
                window_end_date="2027-01-15",
            ),
            MANAGER,
        ),
        201,
    )
    assert_work_order(second_order)
    assert second_order["status"] == "SCHEDULED"
    booked_twice = fixtures.read_shop_bay(bay["id"])
    assert booked_twice["booked_order_count"] == 2
    assert booked_twice["version"] == fresh_version + 1

    orders, orders_meta = validate_paginated(
        api_client.list_overhaul_work_orders(
            MANAGER, params={"shop_bay_id": bay["id"]}
        )
    )
    assert orders_meta["total_count"] == 2
    assert {row["id"] for row in orders} == {first_order["id"], second_order["id"]}


def test_the_day_interval_flips_the_testing_status_on_its_exact_boundaries():
    """PRD §3.1: "If either overdue condition holds, `ndt_status` is `OVERDUE`;
    otherwise, if either due condition holds, it is `DUE`; otherwise it is `CURRENT`."

    Design: Corner/complexity_layers/ndt_day_interval_threshold_flips_current_due_and_overdue_on_its_exact_boundaries
    """
    attraction = fixtures.create_attraction(
        name="Day Threshold Ride",
        park_area="SKYLINE",
        manufacturer="Intamin",
        model_code="DT-1",
        ride_class="THRILL",
        theoretical_hourly_capacity=1000,
        min_operators_required=2,
        parts_budget_cents=1000000,
    )
    component = fixtures.create_component(
        attraction["id"],
        name="Day Restraint Actuator",
        component_type="RESTRAINT_ACTUATOR",
        criticality="SAFETY_CRITICAL",
        ndt_interval_cycles=500000,
        ndt_interval_days=30,
    )
    tested = fixtures.record_ndt(
        component["id"], ndt_method="MAGNETIC_PARTICLE", result="PASS"
    )
    assert_component(tested)
    assert_instant_equals(tested["last_ndt_at"], CLOCK_START, "last_ndt_at")
    assert tested["last_ndt_method"] == "MAGNETIC_PARTICLE"
    assert tested["last_ndt_cycles"] == 0, "no cycles have been logged on this ride"
    assert tested["ndt_status"] == "CURRENT"
    assert tested["condition_flag"] == "OK"

    walk = (
        ("2026-08-30T00:00:00.000Z", "CURRENT", "29 whole days is one short of the interval"),
        ("2026-08-31T00:00:00.000Z", "DUE", "30 days equals ndt_interval_days"),
        ("2026-09-05T00:00:00.000Z", "DUE", "35 days is one below the grace ceiling"),
        ("2026-09-06T00:00:00.000Z", "OVERDUE", "36 days equals ceil(30 x 1.20)"),
    )
    for instant, expected_status, reason in walk:
        moved = fixtures.set_clock(instant)
        assert_instant_equals(moved["current_utc"], instant, "current_utc")
        observed = validate_success(
            api_client.get_component(component["id"], MANAGER)
        )
        assert observed["ndt_status"] == expected_status, reason

    dragged_down = fixtures.read_attraction(attraction["id"])
    assert dragged_down["operational_posture"] == "DOWN", (
        "an OVERDUE SAFETY_CRITICAL component alone forces the posture to DOWN"
    )


def test_the_mutation_response_already_carries_the_recomputed_posture():
    """PRD §2.11: "Every derived field described in this document is recomputed from its
    current inputs at the moment it is read, not cached from the moment it was
    written."

    Design: Corner/consistency_model/the_mutation_response_already_shows_the_recomputed_posture
    """
    attraction = fixtures.create_attraction(
        name="Immediate Ride",
        park_area="FRONTIER",
        manufacturer="Vekoma",
        model_code="IM-1",
        ride_class="THRILL",
        theoretical_hourly_capacity=800,
        min_operators_required=2,
        parts_budget_cents=1000000,
    )
    component = fixtures.create_component(
        attraction["id"],
        name="Immediate Brake",
        component_type="BRAKE",
        criticality="SAFETY_CRITICAL",
        ndt_interval_cycles=100,
        ndt_interval_days=3650,
    )
    before = fixtures.read_attraction(attraction["id"])

    logged = validate_success(
        api_client.log_cycles(
            attraction["id"],
            factories.log_cycles_payload(CLOCK_START_DATE, 120),
            TECHNICIAN,
        )
    )
    assert_attraction(logged)
    assert logged["cumulative_cycles"] == 120
    assert logged["operational_posture"] == "DOWN", (
        "the response that caused the crossing already reports the new posture"
    )

    crossed = validate_success(api_client.get_component(component["id"], TECHNICIAN))
    assert_component(crossed)
    assert crossed["ndt_status"] == "OVERDUE", "120 cycles is exactly ceil(100 x 1.20)"

    re_read = fixtures.read_attraction(attraction["id"], headers=TECHNICIAN)
    assert re_read["cumulative_cycles"] == logged["cumulative_cycles"]
    assert re_read["operational_posture"] == logged["operational_posture"], (
        "a second read neither lags nor drifts"
    )
    assert re_read["version"] == before["version"] + 1, (
        "the single cycle log advanced the attraction exactly once"
    )
