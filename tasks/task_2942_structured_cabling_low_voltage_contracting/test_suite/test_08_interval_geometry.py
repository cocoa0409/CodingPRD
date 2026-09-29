"""Two different interval geometries: closed integer rack units at capacity one, and
half-open buffered time windows at aggregate capacity two.
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
from test_helpers.api_errors import ERR_RACK_RU_CONFLICT, ERR_ROOM_WINDOW_CONFLICT
from test_helpers.assertions import (
    assert_cents,
    assert_rack_ru_identity,
    assert_room_power_identity,
)
from test_helpers.factories import rack_unit_assignment_payload
from test_helpers.test_users import DESIGNER_HEADERS, PM_HEADERS
from test_helpers.types import (
    AssignmentState,
    IdentifierScheme,
    TicketState,
    TicketType,
)


def _rack_with_the_lowest_four_units_taken(client: ApiClient) -> dict:
    """A 42-unit rack whose closed interval [1, 4] is already active."""
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
    fx.place_equipment(
        client,
        rack["id"],
        equipment_label="Core switch",
        start_ru=1,
        end_ru=4,
        power_va=1200,
    )
    return {"room_id": room["id"], "rack_id": rack["id"]}


def test_a_candidate_sharing_one_rack_unit_endpoint_is_refused(client: ApiClient) -> None:
    """Rack-unit intervals are closed, so unit 4 belongs to the placement holding [1, 4].

    Design: Difficulty/resource_temporal_overlap/rack_unit_intervals_are_closed_with_unit_capacity_one
    """
    scenario = _rack_with_the_lowest_four_units_taken(client)
    before = fx.read_rack(client, scenario["rack_id"])
    assert before["occupied_ru"] == 4
    assert before["available_ru"] == 38
    assert before["power_draw_va"] == 1200

    response = client.create_rack_unit_assignment(
        rack_unit_assignment_payload(
            scenario["rack_id"],
            before["version"],
            equipment_label="Patch panel P1",
            start_ru=4,
            end_ru=6,
            power_va=0,
        ),
        DESIGNER_HEADERS,
    )
    validate_error(response, ERR_RACK_RU_CONFLICT, 409)

    _, meta = validate_paginated(
        client.list_rack_unit_assignments(
            DESIGNER_HEADERS, params={"rack_id": scenario["rack_id"]}
        )
    )
    assert meta["total_count"] == 1


def test_a_candidate_starting_one_unit_higher_is_admitted_with_no_gap(
    client: ApiClient,
) -> None:
    """Touching endpoints without a shared unit is a zero gap, and zero gaps are legal.

    Design: Difficulty/resource_temporal_overlap/rack_unit_intervals_are_closed_with_unit_capacity_one
    """
    scenario = _rack_with_the_lowest_four_units_taken(client)
    before = fx.read_rack(client, scenario["rack_id"])

    placed = validate_success(
        client.create_rack_unit_assignment(
            rack_unit_assignment_payload(
                scenario["rack_id"],
                before["version"],
                equipment_label="Patch panel P1",
                start_ru=5,
                end_ru=8,
                power_va=300,
            ),
            DESIGNER_HEADERS,
        ),
        201,
    )
    assert placed["span_ru"] == 4
    assert placed["assignment_state"] == AssignmentState.ACTIVE

    rack = fx.read_rack(client, scenario["rack_id"])
    assert rack["occupied_ru"] == 8
    assert rack["available_ru"] == 34
    assert rack["power_draw_va"] == 1500
    assert_rack_ru_identity(rack)

    room = fx.read_room(client, scenario["room_id"])
    assert room["power_load_va"] == 1500
    assert room["power_headroom_va"] == 1500
    assert_room_power_identity(room)


def _room_with_one_booked_hour(client: ApiClient) -> dict:
    """An occupied job whose room holds one 09:00-10:00 booking and three open requests.

    W1 begins exactly thirty minutes after W0 ends, W2 sits inside W1, and W3 overlaps
    both of them.
    """
    scenario = fx.setup_base_scenario(client, project={"mac_budget_cents": 500000})
    occupied = fx.setup_occupied_project(
        client,
        scenario,
        identifier="TR01-A01",
        horizontal_length_m=85.63,
        consolidation_point_stub_m=0,
        patch_cord_allowance_m=2.00,
    )
    project_id = occupied["project_id"]
    link_id = occupied["link_id"]
    room_id = occupied["room_id"]

    def request(start: str, end: str) -> str:
        ticket = fx.create_ticket(
            client,
            project_id,
            link_id,
            room_id,
            ticket_type=TicketType.CHANGE,
            requested_window_start=start,
            requested_window_end=end,
            labor_hours_estimate=1.0,
            expedite_requested=False,
        )
        return ticket["id"]

    w0 = request("2026-08-14T09:00:00Z", "2026-08-14T10:00:00Z")
    fx.schedule_ticket(
        client,
        w0,
        scheduled_window_start="2026-08-14T09:00:00Z",
        scheduled_window_end="2026-08-14T10:00:00Z",
    )
    return {
        "project_id": project_id,
        "w1": request("2026-08-14T10:30:00Z", "2026-08-14T11:30:00Z"),
        "w2": request("2026-08-14T10:45:00Z", "2026-08-14T11:15:00Z"),
        "w3": request("2026-08-14T11:00:00Z", "2026-08-14T11:20:00Z"),
    }


def _schedule(client: ApiClient, ticket_id: str, start: str, end: str):
    return client.schedule_mac_ticket(
        ticket_id,
        {"scheduled_window_start": start, "scheduled_window_end": end},
        PM_HEADERS,
    )


def test_an_exact_thirty_minute_changeover_gap_is_admitted(client: ApiClient) -> None:
    """The buffered candidate touches the standing booking without overlapping it.

    Design: Difficulty/resource_temporal_overlap/room_change_windows_are_half_open_with_a_thirty_minute_buffer
    """
    scenario = _room_with_one_booked_hour(client)

    scheduled = validate_success(
        _schedule(
            client, scenario["w1"], "2026-08-14T10:30:00Z", "2026-08-14T11:30:00Z"
        ),
        200,
    )
    assert scheduled["ticket_state"] == TicketState.SCHEDULED
    assert_cents(scheduled["estimated_billed_cents"], 9600)


def test_a_second_overlapping_window_is_admitted_because_the_room_holds_two_crews(
    client: ApiClient,
) -> None:
    """One occupying window overlapping the candidate is legal; the room hosts two crews.

    Design: Difficulty/resource_temporal_overlap/room_change_windows_are_half_open_with_a_thirty_minute_buffer
    """
    scenario = _room_with_one_booked_hour(client)
    validate_success(
        _schedule(
            client, scenario["w1"], "2026-08-14T10:30:00Z", "2026-08-14T11:30:00Z"
        ),
        200,
    )

    scheduled = validate_success(
        _schedule(
            client, scenario["w2"], "2026-08-14T10:45:00Z", "2026-08-14T11:15:00Z"
        ),
        200,
    )
    assert scheduled["ticket_state"] == TicketState.SCHEDULED
    assert_cents(scheduled["estimated_billed_cents"], 9600)


def test_the_third_overlapping_window_is_refused_and_commits_nothing(
    client: ApiClient,
) -> None:
    """Two overlaps are legal and the third is not, and the refusal touches no ledger.

    Design: Difficulty/resource_temporal_overlap/room_change_windows_are_half_open_with_a_thirty_minute_buffer
    """
    scenario = _room_with_one_booked_hour(client)
    validate_success(
        _schedule(
            client, scenario["w1"], "2026-08-14T10:30:00Z", "2026-08-14T11:30:00Z"
        ),
        200,
    )
    validate_success(
        _schedule(
            client, scenario["w2"], "2026-08-14T10:45:00Z", "2026-08-14T11:15:00Z"
        ),
        200,
    )

    response = _schedule(
        client, scenario["w3"], "2026-08-14T11:00:00Z", "2026-08-14T11:20:00Z"
    )
    validate_error(response, ERR_ROOM_WINDOW_CONFLICT, 409)

    refused = fx.read_ticket(client, scenario["w3"])
    assert refused["ticket_state"] == TicketState.SUBMITTED
    assert refused["scheduled_window_start"] is None
    assert refused["estimated_billed_cents"] is None

    project = fx.read_project(client, scenario["project_id"])
    assert_cents(project["consumed_mac_cents"], 28800)
