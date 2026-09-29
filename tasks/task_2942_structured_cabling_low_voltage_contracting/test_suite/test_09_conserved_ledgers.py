"""Compensating pairs: each write and its undo must return the conserved ledger to the
exact figure it held beforehand.
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from test_helpers import fixtures as fx
from test_helpers.api_client import ApiClient
from test_helpers.assertions import (
    assert_decimal_equals,
    assert_fill_ledger,
    assert_rack_ru_identity,
    assert_room_power_identity,
)
from test_helpers.types import (
    Application,
    AssignmentState,
    IdentifierScheme,
    InstallState,
    RouteState,
)

RELEASE_REASON = "Switch relocated to TR02 during the MAC window"


def _routed_tray(client: ApiClient) -> dict:
    """A 20000 sq mm tray carrying exactly one 49.02 sq mm cable."""
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
        bend_count=0,
        in_plenum_space=True,
    )
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
    route = fx.route_link(client, link["id"], segment["id"])
    return {
        "segment_id": segment["id"],
        "link_id": link["id"],
        "route": route,
        "route_id": route["id"],
    }


def test_the_routing_charges_the_tray_exactly_the_cable_cross_section(
    client: ApiClient,
) -> None:
    """The route's own snapshot and the segment's ledger agree on 49.02 sq mm.

    Design: Difficulty/compensating_invariant/route_withdraw_returns_exactly_the_pathway_area_it_consumed
    """
    scenario = _routed_tray(client)
    assert_decimal_equals(scenario["route"]["consumed_area_sq_mm"], 49.02)

    segment = fx.read_segment(client, scenario["segment_id"])
    assert_decimal_equals(segment["fill_area_used_sq_mm"], 49.02)
    assert segment["occupying_route_count"] == 1
    assert segment["allowed_fill_pct"] == 50
    assert_decimal_equals(segment["fill_ratio"], 0.0025, 4)
    assert_fill_ledger(segment)


def test_withdrawing_the_routing_gives_back_exactly_that_area(client: ApiClient) -> None:
    """The undo restores the pre-route figures exactly, with no rounding drift left over.

    Design: Difficulty/compensating_invariant/route_withdraw_returns_exactly_the_pathway_area_it_consumed
    """
    scenario = _routed_tray(client)

    withdrawn = fx.withdraw_route(
        client, scenario["route_id"], scenario["segment_id"]
    )
    assert withdrawn["route_state"] == RouteState.WITHDRAWN
    assert_decimal_equals(withdrawn["consumed_area_sq_mm"], 49.02)

    segment = fx.read_segment(client, scenario["segment_id"])
    assert_decimal_equals(segment["fill_area_used_sq_mm"], 0.00)
    assert segment["occupying_route_count"] == 0
    assert segment["allowed_fill_pct"] == 50
    assert_decimal_equals(segment["fill_ratio"], 0.0000, 4)

    link = fx.read_link(client, scenario["link_id"])
    assert link["routed_segment_count"] == 0
    assert link["install_state"] == InstallState.DESIGNED


def _rack_with_a_core_switch(client: ApiClient) -> dict:
    """A 42-unit rack in a 3000 VA room holding one 1200 VA placement over [1, 4]."""
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
    rack = fx.create_rack(client, room["id"], rack_code="A", total_ru=42)
    assignment = fx.place_equipment(
        client,
        rack["id"],
        equipment_label="Core switch",
        start_ru=1,
        end_ru=4,
        power_va=1200,
    )
    return {
        "room_id": room["id"],
        "rack_id": rack["id"],
        "assignment_id": assignment["id"],
    }


def test_the_placement_draws_volt_amperes_two_hops_up_the_chain(
    client: ApiClient,
) -> None:
    """The rack aggregates the placement and the room aggregates the rack.

    Design: Difficulty/compensating_invariant/assignment_release_returns_exactly_the_room_volt_amperes_it_drew
    """
    scenario = _rack_with_a_core_switch(client)

    rack = fx.read_rack(client, scenario["rack_id"])
    assert rack["occupied_ru"] == 4
    assert rack["available_ru"] == 38
    assert rack["power_draw_va"] == 1200
    assert_rack_ru_identity(rack)

    room = fx.read_room(client, scenario["room_id"])
    assert room["power_load_va"] == 1200
    assert room["power_headroom_va"] == 1800
    assert_room_power_identity(room)


def test_releasing_the_placement_returns_exactly_the_units_and_the_volt_amperes(
    client: ApiClient,
) -> None:
    """Both ledgers come back to their pre-placement figures and the room identity holds.

    Design: Difficulty/compensating_invariant/assignment_release_returns_exactly_the_room_volt_amperes_it_drew
    """
    scenario = _rack_with_a_core_switch(client)

    released = fx.release_equipment(
        client,
        scenario["assignment_id"],
        scenario["rack_id"],
        released_reason=RELEASE_REASON,
    )
    assert released["assignment_state"] == AssignmentState.RELEASED
    assert released["span_ru"] == 4
    assert released["released_reason"] == RELEASE_REASON

    rack = fx.read_rack(client, scenario["rack_id"])
    assert rack["occupied_ru"] == 0
    assert rack["available_ru"] == 42
    assert rack["power_draw_va"] == 0
    assert_rack_ru_identity(rack)

    room = fx.read_room(client, scenario["room_id"])
    assert room["power_load_va"] == 0
    assert room["power_headroom_va"] == 3000
    assert_room_power_identity(room)
