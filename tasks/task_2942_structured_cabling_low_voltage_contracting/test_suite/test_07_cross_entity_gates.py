"""Transitions gated on a field of a different entity: the identical call is refused
and then admitted with nothing about the acting resource changed in between.
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from prd_bench_local_runner.testing import (
    validate_error,
    validate_paginated,
    validate_success,
)

from test_helpers import fixtures as fx
from test_helpers.api_client import ApiClient
from test_helpers.api_errors import (
    ERR_PROJECT_NOT_OCCUPIED,
    ERR_ROOM_NOT_GROUNDED,
    ERR_TRADE_NOT_COORDINATED,
)
from test_helpers.assertions import assert_decimal_equals
from test_helpers.factories import mac_ticket_payload
from test_helpers.test_users import (
    CLIENT_HEADERS,
    INSTALLER_HEADERS,
    INSTALLER_ID,
    PM_HEADERS,
)
from test_helpers.types import (
    Application,
    CoordinationState,
    GroundingStatus,
    IdentifierScheme,
    InstallState,
    OccupancyStatus,
    RecordState,
    RoomState,
    TicketState,
    TicketType,
)


def _pulled_link_in_an_unbonded_room(client: ApiClient) -> dict:
    """A link pulled through a tray while its telecom room is still unverified."""
    project = fx.create_project(
        client,
        name="Riverside Tower Cabling",
        site_code="RVT1",
        plenum_ceiling=True,
        identifier_scheme=IdentifierScheme.TIA_606_CLASS_1,
    )
    room = fx.create_room(
        client,
        project["id"],
        room_code="TR01",
        floor=3,
        branch_circuit_amps=20,
        ups_capacity_va=3000,
    )
    cable = fx.create_cable_type(
        client,
        outer_diameter_mm=7.9,
        max_channel_length_m=100.0,
        cost_per_meter_cents=150,
        applications=[Application.DATA_HORIZONTAL],
    )
    segment = fx.create_segment(
        client,
        project["id"],
        segment_code="PS-A",
        usable_area_sq_mm=20000.0,
        length_m=40.0,
        in_plenum_space=True,
    )
    coordination = fx.create_coordination(client, project["id"])
    fx.confirm_coordination(client, coordination["id"])
    link = fx.create_link(
        client,
        project["id"],
        room["id"],
        cable["id"],
        identifier="TR01-A01",
        horizontal_length_m=85.63,
        consolidation_point_stub_m=0,
        patch_cord_allowance_m=2.00,
    )
    fx.route_link(client, link["id"], segment["id"])
    fx.pull_link(client, link["id"])
    return {"room_id": room["id"], "link_id": link["id"]}


def test_termination_is_refused_while_the_room_is_not_provably_bonded(
    client: ApiClient,
) -> None:
    """Landing conductors waits on a field of the room, not of the link.

    Design: Difficulty/cross_entity_state_dependency/link_termination_depends_on_telecom_room_grounding_status
    """
    scenario = _pulled_link_in_an_unbonded_room(client)

    response = client.terminate_link(scenario["link_id"], INSTALLER_HEADERS)
    validate_error(response, ERR_ROOM_NOT_GROUNDED, 409)

    link = fx.read_link(client, scenario["link_id"])
    assert link["install_state"] == InstallState.PULLED


def test_bonding_the_room_admits_the_identical_termination_call(
    client: ApiClient,
) -> None:
    """Only the room moved between the two calls, and that is what flipped the outcome.

    Design: Difficulty/cross_entity_state_dependency/link_termination_depends_on_telecom_room_grounding_status
    """
    scenario = _pulled_link_in_an_unbonded_room(client)
    validate_error(
        client.terminate_link(scenario["link_id"], INSTALLER_HEADERS),
        ERR_ROOM_NOT_GROUNDED,
        409,
    )

    room = fx.verify_grounding(
        client, scenario["room_id"], ground_resistance_milliohms=4200.50
    )
    assert room["grounding_status"] == GroundingStatus.COMPLIANT
    assert room["room_state"] == RoomState.GROUNDED

    terminated = validate_success(
        client.terminate_link(scenario["link_id"], INSTALLER_HEADERS), 200
    )
    assert terminated["install_state"] == InstallState.TERMINATED
    assert terminated["record_state"] == RecordState.UNLABELED


def _certified_but_unoccupied_project(client: ApiClient) -> dict:
    """A job whose single link is certified and whose ceiling milestone is released."""
    scenario = fx.setup_base_scenario(client, project={"mac_budget_cents": 500000})
    return fx.setup_certified_link(
        client,
        scenario,
        identifier="TR01-A01",
        horizontal_length_m=85.63,
        consolidation_point_stub_m=0,
        patch_cord_allowance_m=2.00,
    )


def _move_ticket(project_id: str, link_id: str, room_id: str) -> dict:
    return mac_ticket_payload(
        project_id,
        link_id,
        room_id,
        ticket_type=TicketType.MOVE,
        requested_window_start="2026-08-14T09:00:00Z",
        requested_window_end="2026-08-14T15:00:00Z",
        labor_hours_estimate=6.0,
        expedite_requested=False,
    )


def test_ticketing_is_refused_before_the_project_is_handed_over(
    client: ApiClient,
) -> None:
    """Raising a ticket depends on the parent project's occupancy, not on the link.

    Design: Difficulty/cross_entity_state_dependency/mac_ticket_creation_depends_on_project_occupancy_status
    """
    scenario = _certified_but_unoccupied_project(client)
    assert scenario["project"]["occupancy_status"] == OccupancyStatus.PRE_OCCUPANCY

    response = client.create_mac_ticket(
        _move_ticket(scenario["project_id"], scenario["link_id"], scenario["room_id"]),
        CLIENT_HEADERS,
    )
    validate_error(response, ERR_PROJECT_NOT_OCCUPIED, 409)

    _, meta = validate_paginated(
        client.list_mac_tickets(PM_HEADERS, params={"project_id": scenario["project_id"]})
    )
    assert meta["total_count"] == 0


def test_handover_unlocks_the_identical_ticket_creation(client: ApiClient) -> None:
    """The declaration of occupancy is what opens moves-adds-changes ticketing.

    Design: Difficulty/cross_entity_state_dependency/mac_ticket_creation_depends_on_project_occupancy_status
    """
    scenario = _certified_but_unoccupied_project(client)
    validate_error(
        client.create_mac_ticket(
            _move_ticket(
                scenario["project_id"], scenario["link_id"], scenario["room_id"]
            ),
            CLIENT_HEADERS,
        ),
        ERR_PROJECT_NOT_OCCUPIED,
        409,
    )

    occupied = fx.declare_occupancy(client, scenario["project_id"])
    assert occupied["occupancy_status"] == OccupancyStatus.OCCUPIED
    assert_decimal_equals(occupied["completeness_pct_strict"], 100.00)

    ticket = validate_success(
        client.create_mac_ticket(
            _move_ticket(
                scenario["project_id"], scenario["link_id"], scenario["room_id"]
            ),
            CLIENT_HEADERS,
        ),
        201,
    )
    assert ticket["ticket_state"] == TicketState.SUBMITTED
    assert ticket["estimated_billed_cents"] is None

    _, meta = validate_paginated(
        client.list_mac_tickets(PM_HEADERS, params={"project_id": scenario["project_id"]})
    )
    assert meta["total_count"] == 1


def _routed_link_awaiting_the_ceiling_trade(client: ApiClient) -> dict:
    """A routed link whose ceiling milestone has only been requested, never confirmed."""
    project = fx.create_project(
        client,
        name="Riverside Tower Cabling",
        site_code="RVT1",
        plenum_ceiling=True,
        identifier_scheme=IdentifierScheme.TIA_606_CLASS_1,
    )
    room = fx.create_room(
        client,
        project["id"],
        room_code="TR01",
        floor=3,
        branch_circuit_amps=20,
        ups_capacity_va=3000,
    )
    fx.verify_grounding(client, room["id"], ground_resistance_milliohms=5000)
    cable = fx.create_cable_type(
        client,
        outer_diameter_mm=7.9,
        max_channel_length_m=100.0,
        cost_per_meter_cents=150,
        applications=[Application.DATA_HORIZONTAL],
    )
    segment = fx.create_segment(
        client,
        project["id"],
        segment_code="PS-A",
        usable_area_sq_mm=20000.0,
        length_m=40.0,
        in_plenum_space=True,
    )
    coordination = fx.create_coordination(client, project["id"])
    link = fx.create_link(
        client,
        project["id"],
        room["id"],
        cable["id"],
        identifier="TR01-A01",
        horizontal_length_m=85.63,
        consolidation_point_stub_m=0,
        patch_cord_allowance_m=2.00,
    )
    fx.route_link(client, link["id"], segment["id"])
    return {
        "project_id": project["id"],
        "coordination_id": coordination["id"],
        "link_id": link["id"],
    }


def test_the_pull_is_refused_while_the_ceiling_milestone_is_only_requested(
    client: ApiClient,
) -> None:
    """The gate is a sibling coordination row, neither a room field nor a project field.

    Design: Difficulty/cross_entity_state_dependency/link_pull_depends_on_ceiling_trade_coordination_state
    """
    scenario = _routed_link_awaiting_the_ceiling_trade(client)

    response = client.pull_link(scenario["link_id"], INSTALLER_HEADERS)
    validate_error(response, ERR_TRADE_NOT_COORDINATED, 409)

    link = fx.read_link(client, scenario["link_id"])
    assert link["install_state"] == InstallState.DESIGNED
    assert link["installer_user_id"] is None


def test_confirming_the_ceiling_milestone_admits_the_identical_pull(
    client: ApiClient,
) -> None:
    """Confirmation alone flips the outcome, and the pull leaves the coordination alone.

    Design: Difficulty/cross_entity_state_dependency/link_pull_depends_on_ceiling_trade_coordination_state
    """
    scenario = _routed_link_awaiting_the_ceiling_trade(client)
    validate_error(
        client.pull_link(scenario["link_id"], INSTALLER_HEADERS),
        ERR_TRADE_NOT_COORDINATED,
        409,
    )

    confirmed = fx.confirm_coordination(
        client, scenario["coordination_id"], confirmed_date="2026-08-05"
    )
    assert confirmed["coordination_state"] == CoordinationState.CONFIRMED
    assert confirmed["confirmed_date"] == "2026-08-05"

    pulled = validate_success(
        client.pull_link(scenario["link_id"], INSTALLER_HEADERS), 200
    )
    assert pulled["install_state"] == InstallState.PULLED

    rows, _ = validate_paginated(
        client.list_trade_coordinations(
            PM_HEADERS, params={"project_id": scenario["project_id"]}
        )
    )
    assert [row["coordination_state"] for row in rows] == [CoordinationState.CONFIRMED]
