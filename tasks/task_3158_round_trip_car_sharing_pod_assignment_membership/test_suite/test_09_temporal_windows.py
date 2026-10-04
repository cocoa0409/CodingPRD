"""Half-open interval semantics for reservations and maintenance windows."""
from test_helpers import (
    OPERATOR,
    api_client,
    setup_confirmed_reservation,
    validate_success,
)


def test_maintenance_window_containing_a_live_reservation_is_refused():
    """PRD §3.12: "the requested half-open window must not overlap any existing maintenance
    order for the same vehicle whose status is `SCHEDULED`, `BLOCKED` or `IN_PROGRESS`, nor
    any reservation of that vehicle whose status is `CONFIRMED`, `IN_USE` or `OVERDUE`. A
    collision is refused with `ERR_MAINTENANCE_WINDOW_CONFLICT` (HTTP 409)"
    PRD §2.7: "a maintenance window whose `scheduled_end` exactly equals another window's
    `scheduled_start` does not collide with it"

    Design: Difficulty/resource_temporal_overlap/maintenance_window_contains_semantics_against_live_reservation
    """
    setup = setup_confirmed_reservation(
        pod_name="Campus Maint",
        start_at="2026-09-13T11:00:00Z",
        end_at="2026-09-13T12:00:00Z",
        reserved_hours=1,
    )

    refused = api_client.create_maintenance_order(
        {
            "vehicle_id": setup["vehicle"]["id"],
            "reason": "CONTAINMENT_PROBE",
            "blocking": True,
            "scheduled_start": "2026-09-13T10:00:00Z",
            "scheduled_end": "2026-09-13T13:00:00Z",
        },
        OPERATOR,
    )

    assert refused.status_code == 409, (
        f"A window fully containing a live reservation is a collision, got {refused.status_code}"
    )
    assert refused.json()["data"]["error_id"] == "ERR_MAINTENANCE_WINDOW_CONFLICT", (
        f"Got {refused.json()['data']['error_id']}"
    )
    reservation = validate_success(
        api_client.get_reservation(setup["reservation"]["id"], OPERATOR), 200
    )
    assert reservation["status"] == "CONFIRMED", (
        f"The refused maintenance order leaves the reservation untouched, got "
        f"{reservation['status']}"
    )
    orders = validate_success(
        api_client.list_vehicle_maintenance_orders(setup["vehicle"]["id"], OPERATOR), 200
    )
    assert orders == [], (
        f"A refused order creates no maintenance row, got {[o['reason'] for o in orders]}"
    )


def test_live_reservation_window_is_refused_as_a_maintenance_collision_boundary():
    """PRD §3.12: "the requested half-open window must not overlap any existing maintenance
    order for the same vehicle whose status is `SCHEDULED`, `BLOCKED` or `IN_PROGRESS`, nor
    any reservation of that vehicle whose status is `CONFIRMED`, `IN_USE` or `OVERDUE`."
    PRD §2.7: "A window written as `[from, to)` includes its lower bound and excludes its upper
    bound."

    Design: Difficulty/resource_temporal_overlap/maintenance_window_contains_semantics_against_live_reservation
    """
    setup = setup_confirmed_reservation(
        pod_name="Campus Maint Boundary",
        start_at="2026-09-13T11:00:00Z",
        end_at="2026-09-13T12:00:00Z",
        reserved_hours=1,
    )

    refused = api_client.create_maintenance_order(
        {
            "vehicle_id": setup["vehicle"]["id"],
            "reason": "TYRE_ROTATION",
            "blocking": False,
            "scheduled_start": "2026-09-13T11:30:00Z",
            "scheduled_end": "2026-09-13T11:45:00Z",
        },
        OPERATOR,
    )

    assert refused.status_code == 409, (
        f"A window strictly inside a live reservation collides, got {refused.status_code}"
    )
    assert refused.json()["data"]["error_id"] == "ERR_MAINTENANCE_WINDOW_CONFLICT", (
        f"Got {refused.json()['data']['error_id']}"
    )
    orders = validate_success(
        api_client.list_vehicle_maintenance_orders(setup["vehicle"]["id"], OPERATOR), 200
    )
    assert orders == [], f"A refused order creates no row, got {[o['reason'] for o in orders]}"


def test_maintenance_order_adjacent_to_a_live_window_is_accepted():
    """PRD §3.12: "an adjacent window whose `scheduled_end` exactly equals the other window's
    `scheduled_start` does not collide."
    PRD §3.12: "on success the vehicle's `use_status` is set to `MAINTENANCE`, the order's pod
    derived values are recomputed, the vehicle's `version` increments and the order's `version`
    increments."

    Design: Difficulty/resource_temporal_overlap/maintenance_window_contains_semantics_against_live_reservation
    """
    setup = setup_confirmed_reservation(
        pod_name="Campus Maint Adjacent",
        start_at="2026-09-13T11:00:00Z",
        end_at="2026-09-13T12:00:00Z",
        reserved_hours=1,
    )

    accepted = validate_success(
        api_client.create_maintenance_order(
            {
                "vehicle_id": setup["vehicle"]["id"],
                "reason": "TYRE_ROTATION",
                "blocking": True,
                "scheduled_start": "2026-09-13T12:00:00Z",
                "scheduled_end": "2026-09-13T14:00:00Z",
            },
            OPERATOR,
        ),
        201,
    )

    assert accepted["status"] == "BLOCKED", (
        f"A blocking order moves straight into BLOCKED, got {accepted['status']}"
    )
    assert accepted["pod_id"] == setup["pod"]["id"], (
        f"The order's pod is read from the vehicle, got {accepted['pod_id']}"
    )
    vehicle = validate_success(api_client.get_vehicle(setup["vehicle"]["id"], OPERATOR), 200)
    assert vehicle["use_status"] == "MAINTENANCE", (
        f"A blocking order takes the vehicle with it, got {vehicle['use_status']}"
    )