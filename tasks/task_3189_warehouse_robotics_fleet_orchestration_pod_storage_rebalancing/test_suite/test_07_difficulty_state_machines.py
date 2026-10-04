"""Queue A (difficulty) translations: non-linear state machines.

Covers rule_id non_linear_state_machine:
- drive_unit_cyclic_active_charging_maintenance_active (2 tests)
- floor_exception_branching_fork_join (2 tests)
"""
import pytest

from test_helpers import (
    api_client,
    get_success_data,
    validate_success,
    set_clock,
    create_zone,
    create_drive_unit,
    create_charger,
    create_charging_session_payload,
    create_maintenance_window_payload,
    create_floor_exception_payload,
    setup_triaged_human_exception,
    create_and_grant_permit,
    create_human_entry_permit_payload,
    get_zone,
    get_drive_unit,
    TEST_USERS,
)

ADMIN = TEST_USERS["fleet_admin_headers"]
FLOW = TEST_USERS["flow_controller_headers"]
SUPERVISOR = TEST_USERS["floor_supervisor_headers"]
SAFETY = TEST_USERS["safety_officer_headers"]
TECH = TEST_USERS["maintenance_tech_headers"]


def _setup_charge_then_maintenance():
    """DU1 goes ACTIVE -> CHARGING -> ACTIVE (one charge cycle), then a
    CORRECTIVE window [09:00, 09:30) is scheduled and activated by the clock
    (ACTIVE -> MAINTENANCE)."""
    set_clock("2026-09-01T08:00:00Z")
    zone = create_zone(zone_code="Z1", grid_x=0, grid_y=0, width=10, height=10,
                       max_human_occupancy=2)
    charger = create_charger(zone["id"], slot_count=1)
    du = create_drive_unit(zone["id"], unit_code="DU1")
    session = get_success_data(
        api_client.create_charging_session(
            create_charging_session_payload(charger["id"], du["id"]), FLOW
        )
    )
    set_clock("2026-09-01T09:00:00Z")
    get_success_data(api_client.close_charging_session(session["id"], FLOW))
    window = get_success_data(
        api_client.create_maintenance_window(
            create_maintenance_window_payload(
                du["id"],
                starts_at="2026-09-01T09:00:00Z",
                ends_at="2026-09-01T09:30:00Z",
                kind="CORRECTIVE",
            ),
            TECH,
        )
    )
    set_clock("2026-09-01T09:15:00Z")
    return zone, charger, du, session, window


def test_drive_unit_cycles_back_to_active_through_charging_and_maintenance(api):
    """PRD §3.5: "Closing transitions the session `OPEN` → `CLOSED` ... returns
    the unit `CHARGING` → `ACTIVE`."
    PRD §3.5: "Completing an `ACTIVE` window transitions it to `COMPLETE`,
    returns the unit `MAINTENANCE` → `ACTIVE`, and increments the unit's
    `version`."

    Design: Difficulty/non_linear_state_machine/drive_unit_cyclic_active_charging_maintenance_active
    """
    _zone, _charger, du, _session, window = _setup_charge_then_maintenance()
    unit_mid = get_drive_unit(du["id"])
    assert unit_mid["status"] == "MAINTENANCE", (
        f"window activation must pull the unit into MAINTENANCE, got {unit_mid['status']}"
    )
    get_success_data(api_client.complete_maintenance_window(window["id"], TECH))
    unit_after = get_drive_unit(du["id"])
    assert unit_after["status"] == "ACTIVE", (
        "the unit must complete the cycle ACTIVE -> CHARGING -> ACTIVE -> "
        f"MAINTENANCE -> ACTIVE; ended at {unit_after['status']}"
    )


def test_maintenance_window_completes_with_unit(api):
    """PRD §3.5: "Completing an `ACTIVE` window transitions it to `COMPLETE`,
    returns the unit `MAINTENANCE` → `ACTIVE`, and increments the unit's
    `version`."

    Design: Difficulty/non_linear_state_machine/drive_unit_cyclic_active_charging_maintenance_active
    """
    _zone, _charger, du, _session, window = _setup_charge_then_maintenance()
    completed = get_success_data(
        api_client.complete_maintenance_window(window["id"], TECH)
    )
    assert completed["status"] == "COMPLETE", (
        f"window must reach COMPLETE, got {completed['status']}"
    )
    unit_after = get_drive_unit(du["id"])
    assert unit_after["status"] == "ACTIVE"


def _setup_two_exceptions():
    """One zone (occupancy 1) with one ACTIVE unit; EX1 BLOCKED_PATH triaged
    ROBOT; EX2 DROPPED_ITEM triaged HUMAN with a granted-then-released permit.
    Clock ends at 09:00."""
    set_clock("2026-09-01T08:00:00Z")
    zone = create_zone(zone_code="Z1", grid_x=0, grid_y=0, width=10, height=10,
                       max_human_occupancy=1)
    du = create_drive_unit(zone["id"], unit_code="DU1")
    ex1 = get_success_data(
        api_client.create_floor_exception(
            create_floor_exception_payload(zone["id"], kind="BLOCKED_PATH"),
            SUPERVISOR,
        )
    )
    ex2 = get_success_data(
        api_client.create_floor_exception(
            create_floor_exception_payload(zone["id"], kind="DROPPED_ITEM"),
            SUPERVISOR,
        )
    )
    get_success_data(api_client.triage_floor_exception(ex1["id"], "ROBOT", SUPERVISOR))
    get_success_data(api_client.triage_floor_exception(ex2["id"], "HUMAN", SUPERVISOR))
    permit = get_success_data(
        api_client.create_human_entry_permit(
            create_human_entry_permit_payload(
                zone["id"], ex2["id"],
                starts_at="2026-09-01T08:30:00Z",
                ends_at="2026-09-01T09:00:00Z",
            ),
            SUPERVISOR,
        )
    )
    get_success_data(api_client.grant_human_entry_permit(permit["id"], SAFETY))
    set_clock("2026-09-01T09:00:00Z")
    get_success_data(api_client.release_human_entry_permit(permit["id"], SAFETY))
    return zone, du, ex1, ex2, permit


def test_floor_exception_both_branches_resolve(api):
    """PRD §3.6: "Robotic resolution of a `TRIAGED_ROBOT` exception takes
    `corrective_outcome` `RESTORE` and requires that no `ACTIVE` human-entry
    permit covers the zone."
    PRD §3.6: "With every permit authorizing the exception `RELEASED`, a
    `FloorSupervisor` resolves the `TRIAGED_HUMAN` exception with
    `corrective_outcome` `RESTORE` or `MAINTENANCE`."

    Design: Difficulty/non_linear_state_machine/floor_exception_branching_fork_join
    """
    _zone, _du, ex1, ex2, _permit = _setup_two_exceptions()
    r1 = get_success_data(
        api_client.resolve_floor_exception(ex1["id"], "RESTORE", SUPERVISOR)
    )
    assert r1["status"] == "RESOLVED"
    r2 = get_success_data(
        api_client.resolve_floor_exception(ex2["id"], "RESTORE", SUPERVISOR)
    )
    assert r2["status"] == "RESOLVED"


def test_floor_exception_join_restores_zone_and_units(api):
    """PRD §3.6: "Resolution moves the exception to the terminal `RESOLVED`
    state, restores the zone's `posture` to `OPEN`, returns parked units in
    the zone `PARKED` → `ACTIVE`."

    Design: Difficulty/non_linear_state_machine/floor_exception_branching_fork_join
    """
    zone, du, ex1, ex2, _permit = _setup_two_exceptions()
    get_success_data(api_client.resolve_floor_exception(ex1["id"], "RESTORE", SUPERVISOR))
    get_success_data(api_client.resolve_floor_exception(ex2["id"], "RESTORE", SUPERVISOR))
    zone_after = get_zone(zone["id"])
    assert zone_after["posture"] == "OPEN", (
        f"after both branches resolve the zone must return to OPEN, got {zone_after['posture']}"
    )
    unit_after = get_drive_unit(du["id"])
    assert unit_after["status"] == "ACTIVE", (
        f"parked unit must return to ACTIVE once the floor restores, got {unit_after['status']}"
    )
