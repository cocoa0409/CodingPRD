"""Entity shapes, server-minted fields, declared defaults and the collection reads.

Every resource of the contracting model is created through its declared endpoint
and then read back — one row at a time and through the filtered collection reads
that stand in for the absent nested URLs — so that the stored shape, the computed
figures and the pagination envelope are all pinned against the contract.
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from prd_bench_local_runner.testing import (
    is_valid_uuid,
    validate_error,
    validate_paginated,
    validate_success,
)

from test_helpers import fixtures as fx
from test_helpers.api_client import ApiClient
from test_helpers.api_errors import (
    ERR_INVALID_REQUEST,
    ERR_LINK_NOT_FOUND,
    ERR_OCCUPANCY_READINESS_NOT_MET,
    ERR_TELECOM_ROOM_NOT_FOUND,
)
from test_helpers.assertions import (
    assert_array_response,
    assert_cents,
    assert_common_fields,
    assert_created_at_ascending,
    assert_decimal_equals,
    assert_envelope_meta,
    assert_fill_ledger,
    assert_immutable_fields,
    assert_instant_equals,
    assert_instant_field,
    assert_object_response,
    assert_rack_ru_identity,
    assert_room_power_identity,
)
from test_helpers.constants import (
    CLOCK_EPOCH,
    DEFAULT_MAC_BUDGET_CENTS,
    TRAY_FILL_PCT,
)
from test_helpers.test_users import (
    DESIGNER_HEADERS,
    PM_HEADERS,
    TEST_TECHNICIAN_ID,
    TESTER_HEADERS,
)
from test_helpers.types import (
    Application,
    AssignmentState,
    CableCategory,
    CoordinationState,
    GroundingStatus,
    IdentifierScheme,
    InstallState,
    JacketRating,
    ManufacturerProgram,
    Milestone,
    OccupancyStatus,
    PathwayState,
    PathwayType,
    RecordState,
    RegistrationState,
    RoomState,
    RouteState,
    TestOutcome,
    TestStandard,
    TicketState,
    TicketType,
    Trade,
    WarrantyProgram,
    WarrantyStatus,
)

# The four inputs a project cannot be opened without (§3.1).
_PROJECT_PAYLOAD = {
    "name": "Riverside Tower Cabling",
    "site_code": "RVT1",
    "plenum_ceiling": True,
    "identifier_scheme": IdentifierScheme.TIA_606_CLASS_1,
}


def _open_project(client: ApiClient, **overrides) -> dict:
    """Open the Riverside Tower job through the declared create endpoint."""
    return fx.create_project(client, **{**_PROJECT_PAYLOAD, **overrides})


def _plenum_cat6a(client: ApiClient) -> dict:
    """The 7.9 mm plenum-rated CAT6A the horizontal runs are built from."""
    return fx.create_cable_type(
        client,
        category=CableCategory.CAT6A,
        jacket_rating=JacketRating.CMP,
        outer_diameter_mm=7.9,
        max_channel_length_m=100.0,
        shielded=False,
        cost_per_meter_cents=150,
        applications=[Application.DATA_HORIZONTAL],
    )


def test_opening_a_project_returns_every_field_with_the_roll_ups_at_zero(
    client: ApiClient,
) -> None:
    """A job opened with only its four mandatory inputs comes back complete.

    The name, site code, plenum declaration and identifier class are echoed as the
    manager submitted them, the optional warranty programme and moves-adds-changes
    budget fall to their declared defaults, and every derived figure — link counts,
    both completeness percentages, the as-built cost and the ticket ledger — is
    reported at zero rather than being left out of the body.

    Design: Corner/entities/create_project_with_required_fields_returns_full_entity
    """
    response = client.create_project(dict(_PROJECT_PAYLOAD), PM_HEADERS)
    project = validate_success(response, 201)

    assert project["name"] == "Riverside Tower Cabling"
    assert project["site_code"] == "RVT1"
    assert project["plenum_ceiling"] is True
    assert project["identifier_scheme"] == IdentifierScheme.TIA_606_CLASS_1
    assert project["warranty_program"] == WarrantyProgram.STANDARD_15Y
    assert_cents(project["mac_budget_cents"], DEFAULT_MAC_BUDGET_CENTS)

    assert project["occupancy_status"] == OccupancyStatus.PRE_OCCUPANCY
    assert project["warranty_status"] == WarrantyStatus.NOT_ELIGIBLE
    assert project["total_link_count"] == 0
    assert project["certified_link_count"] == 0
    assert project["failed_link_count"] == 0
    assert_cents(project["as_built_cost_cents"], 0)
    assert_cents(project["consumed_mac_cents"], 0)
    assert_decimal_equals(project["completeness_pct_strict"], 0.00)
    assert_decimal_equals(project["completeness_pct_provisional"], 0.00)

    assert_common_fields(project, expected_version=1)
    assert_object_response(response)
    assert_envelope_meta(response)


def test_reading_a_cable_type_echoes_the_catalogue_row_and_its_cross_section(
    client: ApiClient,
) -> None:
    """The catalogue detail read gives back exactly what was registered.

    A 7.9 mm plenum-rated CAT6A consumes 49.02 square millimetres of pathway, the
    area of a circle drawn on its outside diameter, and that derived figure is
    carried on the row alongside the approved application list and the installed
    cost per metre.

    Design: Corner/entities/get_cable_type_returns_the_stored_row
    """
    cable = _plenum_cat6a(client)

    response = client.get_cable_type(cable["id"], DESIGNER_HEADERS)
    row = validate_success(response, 200)

    assert row["id"] == cable["id"]
    assert row["category"] == CableCategory.CAT6A
    assert row["jacket_rating"] == JacketRating.CMP
    assert_decimal_equals(row["outer_diameter_mm"], 7.9)
    assert_decimal_equals(row["cross_section_area_sq_mm"], 49.02)
    assert_cents(row["cost_per_meter_cents"], 150)
    assert row["applications"] == [Application.DATA_HORIZONTAL]
    assert row["shielded"] is False
    assert_object_response(response)


def test_listing_links_by_project_pages_the_collection_with_its_counters(
    client: ApiClient,
) -> None:
    """Three designed drops read back over two pages of two.

    The first page carries two of the three rows with more still to come, the
    second carries the remaining row and closes the collection, and both pages
    report the same total for the project filter they were given.

    Design: Corner/entities/list_links_filtered_by_project_returns_paginated_envelope
    """
    project = _open_project(client)
    room = fx.create_room(
        client,
        project["id"],
        room_code="TR01",
        floor=3,
        branch_circuit_amps=20,
        ups_capacity_va=3000,
    )
    cable = _plenum_cat6a(client)
    for identifier, length in (
        ("TR01-A01", 40.00),
        ("TR01-A02", 41.00),
        ("TR01-A03", 42.00),
    ):
        fx.create_link(
            client,
            project["id"],
            room["id"],
            cable["id"],
            identifier=identifier,
            application=Application.DATA_HORIZONTAL,
            horizontal_length_m=length,
        )

    first = client.list_links(
        DESIGNER_HEADERS, params={"project_id": project["id"], "limit": 2, "offset": 0}
    )
    page_one, meta_one = validate_paginated(first)
    assert_array_response(first)
    assert meta_one["total_count"] == 3
    assert meta_one["limit"] == 2
    assert meta_one["offset"] == 0
    assert meta_one["has_more"] is True
    assert len(page_one) == 2

    second = client.list_links(
        DESIGNER_HEADERS, params={"project_id": project["id"], "limit": 2, "offset": 2}
    )
    page_two, meta_two = validate_paginated(second)
    assert meta_two["total_count"] == 3
    assert meta_two["limit"] == 2
    assert meta_two["offset"] == 2
    assert meta_two["has_more"] is False
    assert len(page_two) == 1

    rows = page_one + page_two
    assert_created_at_ascending(rows)
    for row in rows:
        assert row["project_id"] == project["id"]
        assert row["install_state"] == InstallState.DESIGNED


def test_the_design_side_collections_answer_their_foreign_key_filters(
    client: ApiClient,
) -> None:
    """Nothing is nested, so each design-side collection is walked by its own filter.

    Projects are found by site code, rooms by their project, racks by their room,
    elevation placements by rack and state, and tray segments by project and
    pathway type. Each listed row already carries its ledgers — the room's power
    load and headroom, the rack's occupied and available units, the segment's fill
    and allowance — rather than only an identifier to chase.

    Design: Corner/entities/the_design_side_collections_answer_their_reverse_reachability_reads
    """
    project = _open_project(client)
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
        equipment_label="48-port patch panel",
        start_ru=40,
        end_ru=42,
        power_va=1200,
    )
    segment = fx.create_segment(
        client,
        project["id"],
        segment_code="PS-A",
        pathway_type=PathwayType.CABLE_TRAY,
        usable_area_sq_mm=20000.0,
        length_m=40.0,
        bend_count=0,
        in_plenum_space=True,
        shared_with_power=False,
        power_separation_mm=0,
    )

    projects_response = client.list_projects(
        PM_HEADERS, params={"site_code": "RVT1", "limit": 10, "offset": 0}
    )
    project_rows, project_meta = validate_paginated(projects_response)
    assert_array_response(projects_response)
    assert project_meta["total_count"] == 1
    assert project_meta["has_more"] is False
    assert len(project_rows) == 1
    assert project_rows[0]["id"] == project["id"]
    assert project_rows[0]["site_code"] == "RVT1"
    assert project_rows[0]["occupancy_status"] == OccupancyStatus.PRE_OCCUPANCY
    assert project_rows[0]["total_link_count"] == 0

    rooms_response = client.list_telecom_rooms(
        PM_HEADERS, params={"project_id": project["id"], "limit": 10, "offset": 0}
    )
    room_rows, room_meta = validate_paginated(rooms_response)
    assert_array_response(rooms_response)
    assert room_meta["total_count"] == 1
    assert room_meta["has_more"] is False
    assert len(room_rows) == 1
    room_detail = validate_success(client.get_telecom_room(room["id"], PM_HEADERS), 200)
    for view in (room_rows[0], room_detail):
        assert view["id"] == room["id"]
        assert view["power_load_va"] == 1200
        assert view["power_headroom_va"] == 1800
        assert view["room_state"] == RoomState.ROUGH_IN
        assert view["grounding_status"] == GroundingStatus.UNVERIFIED
        assert_room_power_identity(view)

    racks_response = client.list_racks(
        PM_HEADERS, params={"telecom_room_id": room["id"], "limit": 10, "offset": 0}
    )
    rack_rows, rack_meta = validate_paginated(racks_response)
    assert_array_response(racks_response)
    assert rack_meta["total_count"] == 1
    assert rack_meta["has_more"] is False
    assert len(rack_rows) == 1
    assert rack_rows[0]["id"] == rack["id"]
    assert rack_rows[0]["total_ru"] == 42
    assert rack_rows[0]["occupied_ru"] == 3
    assert rack_rows[0]["available_ru"] == 39
    assert rack_rows[0]["power_draw_va"] == 1200
    assert_rack_ru_identity(rack_rows[0])

    assignments_response = client.list_rack_unit_assignments(
        PM_HEADERS,
        params={
            "rack_id": rack["id"],
            "assignment_state": AssignmentState.ACTIVE,
            "limit": 10,
            "offset": 0,
        },
    )
    assignment_rows, assignment_meta = validate_paginated(assignments_response)
    assert_array_response(assignments_response)
    assert assignment_meta["total_count"] == 1
    assert assignment_meta["has_more"] is False
    assert len(assignment_rows) == 1
    assert assignment_rows[0]["id"] == assignment["id"]
    assert assignment_rows[0]["span_ru"] == 3
    assert assignment_rows[0]["assignment_state"] == AssignmentState.ACTIVE
    assert assignment_rows[0]["released_reason"] is None

    segments_response = client.list_pathway_segments(
        PM_HEADERS,
        params={
            "project_id": project["id"],
            "pathway_type": PathwayType.CABLE_TRAY,
            "limit": 10,
            "offset": 0,
        },
    )
    segment_rows, segment_meta = validate_paginated(segments_response)
    assert_array_response(segments_response)
    assert segment_meta["total_count"] == 1
    assert segment_meta["has_more"] is False
    assert len(segment_rows) == 1
    assert segment_rows[0]["id"] == segment["id"]
    assert segment_rows[0]["pathway_depth"] == 0
    assert segment_rows[0]["occupying_route_count"] == 0
    assert_decimal_equals(segment_rows[0]["fill_area_used_sq_mm"], 0.00)
    assert segment_rows[0]["allowed_fill_pct"] == TRAY_FILL_PCT
    assert segment_rows[0]["pathway_state"] == PathwayState.SERVICEABLE


def _handed_over_job_with_one_certified_link(client: ApiClient) -> dict:
    """One drop taken the whole way from design to certification, then handed over.

    The single link is routed through a plenum tray, pulled, terminated, labelled,
    filed on a drawing sheet, tested clean and signed off; the ceiling milestone is
    released, the space is declared occupied and the owner raises one ticket.
    """
    project = _open_project(client)
    room = fx.create_room(
        client,
        project["id"],
        room_code="TR01",
        floor=3,
        branch_circuit_amps=20,
        ups_capacity_va=3000,
    )
    fx.verify_grounding(
        client,
        room["id"],
        tgb_installed=True,
        bonding_conductor_awg=6,
        ground_resistance_milliohms=5000,
    )
    cable = _plenum_cat6a(client)
    segment = fx.create_segment(
        client,
        project["id"],
        segment_code="PS-A",
        pathway_type=PathwayType.CABLE_TRAY,
        usable_area_sq_mm=20000.0,
        length_m=40.0,
        bend_count=0,
        in_plenum_space=True,
        shared_with_power=False,
        power_separation_mm=0,
    )
    coordination = fx.create_coordination(
        client,
        project["id"],
        trade=Trade.CEILING,
        milestone=Milestone.PATHWAY_ROUGH_IN,
    )
    fx.confirm_coordination(client, coordination["id"], confirmed_date="2026-08-05")
    registration = fx.create_registration(
        client, project["id"], manufacturer_program=ManufacturerProgram.STANDARD_15Y
    )
    link = fx.create_link(
        client,
        project["id"],
        room["id"],
        cable["id"],
        identifier="TR01-A01",
        application=Application.DATA_HORIZONTAL,
        horizontal_length_m=40.00,
        consolidation_point_stub_m=0,
        patch_cord_allowance_m=2.00,
    )
    route = fx.route_link(client, link["id"], segment["id"], sequence_index=1)
    fx.pull_link(client, link["id"])
    fx.terminate_link(client, link["id"])
    fx.label_link(client, link["id"], "TR01-A01")
    fx.record_link(client, link["id"], drawing_sheet_ref="E-501")
    fx.file_test(
        client,
        link["id"],
        test_standard=TestStandard.PERMANENT_LINK,
        tester_model="DSX-8000",
        insertion_loss_db=6.0,
        next_margin_db=3.2,
        return_loss_margin_db=2.1,
        length_measured_m=40.00,
    )
    fx.certify_link(client, link["id"])
    fx.release_coordination(client, coordination["id"])
    fx.declare_occupancy(client, project["id"])
    ticket = fx.create_ticket(
        client,
        project["id"],
        link["id"],
        room["id"],
        ticket_type=TicketType.ADD,
        requested_window_start="2026-09-01T09:00:00Z",
        requested_window_end="2026-09-01T11:00:00Z",
        labor_hours_estimate=1.0,
    )
    return {
        "project_id": project["id"],
        "room_id": room["id"],
        "link_id": link["id"],
        "route_id": route["id"],
        "registration_id": registration["id"],
        "coordination_id": coordination["id"],
        "ticket_id": ticket["id"],
    }


def test_the_downstream_collections_list_the_rows_the_certification_chain_left(
    client: ApiClient,
) -> None:
    """Every artefact of the finished chain is reachable from the key it declares.

    The routing still occupies its tray with the snapshotted cable area, the field
    test stands as a clean pass on an immutable row, the warranty registration has
    been promoted to ready by full certification, the owner's ticket sits newly
    submitted, and the ceiling milestone keeps the date the other trade committed
    to even after release.

    Design: Corner/entities/the_downstream_collections_are_reachable_after_the_link_is_certified
    """
    job = _handed_over_job_with_one_certified_link(client)
    page = {"limit": 10, "offset": 0}

    routes_response = client.list_link_routes(
        PM_HEADERS,
        params={"link_id": job["link_id"], "route_state": RouteState.OCCUPYING, **page},
    )
    route_rows, route_meta = validate_paginated(routes_response)
    assert_array_response(routes_response)
    assert route_meta["total_count"] == 1
    assert route_meta["limit"] == 10
    assert route_meta["offset"] == 0
    assert route_meta["has_more"] is False
    assert len(route_rows) == 1
    assert route_rows[0]["id"] == job["route_id"]
    assert route_rows[0]["sequence_index"] == 1
    assert_decimal_equals(route_rows[0]["consumed_area_sq_mm"], 49.02)
    assert route_rows[0]["route_state"] == RouteState.OCCUPYING

    tests_response = client.list_test_results(
        PM_HEADERS, params={"link_id": job["link_id"], **page}
    )
    test_rows, test_meta = validate_paginated(tests_response)
    assert_array_response(tests_response)
    assert test_meta["total_count"] == 1
    assert test_meta["has_more"] is False
    assert len(test_rows) == 1
    assert test_rows[0]["link_id"] == job["link_id"]
    assert test_rows[0]["outcome"] == TestOutcome.PASS
    assert_decimal_equals(test_rows[0]["worst_margin_db"], 2.10)
    assert_immutable_fields(test_rows[0])

    registrations_response = client.list_warranty_registrations(
        PM_HEADERS, params={"project_id": job["project_id"], **page}
    )
    registration_rows, registration_meta = validate_paginated(registrations_response)
    assert_array_response(registrations_response)
    assert registration_meta["total_count"] == 1
    assert registration_meta["has_more"] is False
    assert len(registration_rows) == 1
    assert registration_rows[0]["id"] == job["registration_id"]
    assert registration_rows[0]["manufacturer_program"] == ManufacturerProgram.STANDARD_15Y
    assert registration_rows[0]["registration_state"] == RegistrationState.READY

    tickets_response = client.list_mac_tickets(
        PM_HEADERS,
        params={
            "project_id": job["project_id"],
            "ticket_state": TicketState.SUBMITTED,
            **page,
        },
    )
    ticket_rows, ticket_meta = validate_paginated(tickets_response)
    assert_array_response(tickets_response)
    assert ticket_meta["total_count"] == 1
    assert ticket_meta["has_more"] is False
    assert len(ticket_rows) == 1
    assert ticket_rows[0]["id"] == job["ticket_id"]
    assert ticket_rows[0]["ticket_type"] == TicketType.ADD
    assert ticket_rows[0]["ticket_state"] == TicketState.SUBMITTED
    assert ticket_rows[0]["rework_count"] == 0

    coordinations_response = client.list_trade_coordinations(
        PM_HEADERS,
        params={"project_id": job["project_id"], "trade": Trade.CEILING, **page},
    )
    coordination_rows, coordination_meta = validate_paginated(coordinations_response)
    assert_array_response(coordinations_response)
    assert coordination_meta["total_count"] == 1
    assert coordination_meta["has_more"] is False
    assert len(coordination_rows) == 1
    assert coordination_rows[0]["id"] == job["coordination_id"]
    assert coordination_rows[0]["milestone"] == Milestone.PATHWAY_ROUGH_IN
    assert coordination_rows[0]["coordination_state"] == CoordinationState.RELEASED
    assert coordination_rows[0]["confirmed_date"] == "2026-08-05"


# A well-formed identifier that matches no row anywhere in the store.
_UNKNOWN_UUID = "11111111-1111-4111-8111-111111111111"


def test_reading_a_link_that_does_not_exist_reports_the_link_not_found_code(
    client: ApiClient,
) -> None:
    """An identifier that resolves to no drop is an error, not an empty success.

    The detail read names the kind of record that could not be found, so a caller
    chasing a stale identifier learns it was a link rather than receiving a hollow
    body it might mistake for a real one.

    Design: Corner/entities/get_link_with_unknown_id_returns_link_not_found
    """
    response = client.get_link(_UNKNOWN_UUID, DESIGNER_HEADERS)

    error = validate_error(response, ERR_LINK_NOT_FOUND, 404)
    assert error["message"].strip() != ""
    assert response.json()["response_type"] == "error"
    assert_envelope_meta(response)


def test_designing_a_link_without_a_cable_type_is_refused_before_any_lookup(
    client: ApiClient,
) -> None:
    """A drop cannot be designed without naming the cable it is built from.

    The selected catalogue entry is a required input with no default, so a payload
    that leaves it out is rejected on shape alone and no link row is written for
    the project.

    Design: Corner/entities/create_link_without_cable_type_id_returns_invalid_request
    """
    project = _open_project(client)
    room = fx.create_room(
        client,
        project["id"],
        room_code="TR01",
        floor=3,
        branch_circuit_amps=20,
        ups_capacity_va=3000,
    )

    response = client.create_link(
        {
            "project_id": project["id"],
            "telecom_room_id": room["id"],
            "identifier": "TR01-A01",
            "application": Application.DATA_HORIZONTAL,
            "horizontal_length_m": 40.00,
        },
        DESIGNER_HEADERS,
    )
    validate_error(response, ERR_INVALID_REQUEST, 400)

    _, meta = validate_paginated(
        client.list_links(DESIGNER_HEADERS, params={"project_id": project["id"]})
    )
    assert meta["total_count"] == 0


def test_a_pathway_segment_created_without_its_optional_flags_takes_the_defaults(
    client: ApiClient,
) -> None:
    """A J-hook run drawn with only its geometry starts in the benign environment.

    No bends, not in a plenum cavity, not sharing space with power conductors and
    therefore no clearance to declare; the run opens serviceable and completely
    empty, at the root of its own pathway tree.

    Design: Corner/entities/create_pathway_segment_omitting_optional_flags_applies_defaults
    """
    project = _open_project(client)

    response = client.create_pathway_segment(
        {
            "project_id": project["id"],
            "segment_code": "PS-D",
            "pathway_type": PathwayType.J_HOOK,
            "usable_area_sq_mm": 5000.0,
            "length_m": 15.0,
        },
        DESIGNER_HEADERS,
    )
    segment = validate_success(response, 201)

    assert segment["bend_count"] == 0
    assert segment["in_plenum_space"] is False
    assert segment["shared_with_power"] is False
    assert segment["power_separation_mm"] == 0

    assert segment["pathway_state"] == PathwayState.SERVICEABLE
    assert_decimal_equals(segment["fill_area_used_sq_mm"], 0.00)
    assert segment["occupying_route_count"] == 0
    assert_decimal_equals(segment["fill_ratio"], 0.0000, 4)
    assert_fill_ledger(segment)

    assert segment["upstream_segment_id"] is None
    assert segment["pathway_depth"] == 0
    assert_common_fields(segment, expected_version=1)


def test_both_link_length_variants_are_computed_and_never_accepted_as_input(
    client: ApiClient,
) -> None:
    """The same physical drop is measured two ways, and the server does both sums.

    Forty metres of horizontal run plus a two-and-a-half-metre consolidation-point
    stub is a 42.50 metre permanent link; adding three metres of patch cord at the
    derated rate on top of that already-rounded figure gives a 46.10 metre channel.
    Neither figure is something a designer may assert for themselves.

    Design: Corner/entities/link_length_variants_are_computed_and_not_client_supplied
    """
    project = _open_project(client)
    room = fx.create_room(
        client,
        project["id"],
        room_code="TR01",
        floor=3,
        branch_circuit_amps=20,
        ups_capacity_va=3000,
    )
    cable = _plenum_cat6a(client)
    base = {
        "project_id": project["id"],
        "telecom_room_id": room["id"],
        "cable_type_id": cable["id"],
        "application": Application.DATA_HORIZONTAL,
        "horizontal_length_m": 40.00,
        "consolidation_point_stub_m": 2.50,
        "patch_cord_allowance_m": 3.00,
    }

    response = client.create_link({**base, "identifier": "TR01-A01"}, DESIGNER_HEADERS)
    link = validate_success(response, 201)

    assert_decimal_equals(link["permanent_link_length_m"], 42.50)
    assert_decimal_equals(link["channel_length_m"], 46.10)
    assert link["install_state"] == InstallState.DESIGNED
    assert link["record_state"] == RecordState.UNLABELED
    assert link["routed_segment_count"] == 0
    assert link["test_attempt_count"] == 0
    assert link["latest_test_outcome"] is None
    assert link["certifier_user_id"] is None

    refused = client.create_link(
        {**base, "identifier": "TR01-A02", "permanent_link_length_m": 42.50},
        DESIGNER_HEADERS,
    )
    validate_error(refused, ERR_INVALID_REQUEST, 400)

    _, meta = validate_paginated(
        client.list_links(DESIGNER_HEADERS, params={"project_id": project["id"]})
    )
    assert meta["total_count"] == 1


def test_the_project_identity_and_stamps_are_minted_by_the_server(
    client: ApiClient,
) -> None:
    """Identity, stamps and the revision counter belong to the server alone.

    A newly opened job carries a bare identifier with no type prefix, a revision
    counter starting at one, and creation and update stamps that both read the
    site's logical clock. A declaration of occupancy the job is nowhere near ready
    for is refused, and because a refused write changes nothing, the counter and
    the update stamp are exactly where they were.

    Design: Corner/entities/project_system_fields_are_server_minted
    """
    response = client.create_project(dict(_PROJECT_PAYLOAD), PM_HEADERS)
    project = validate_success(response, 201)

    assert is_valid_uuid(project["id"])
    assert len(project["id"].split("-")[0]) == 8
    assert project["version"] == 1
    assert_instant_field(project["created_at"], "created_at")
    assert_instant_field(project["updated_at"], "updated_at")
    assert_instant_equals(project["created_at"], CLOCK_EPOCH, "created_at")
    assert_instant_equals(project["updated_at"], project["created_at"], "updated_at")

    refused = client.declare_occupancy(
        project["id"], {"occupancy_status": OccupancyStatus.OCCUPIED}, PM_HEADERS
    )
    validate_error(refused, ERR_OCCUPANCY_READINESS_NOT_MET, 409)

    reread = fx.read_project(client, project["id"])
    assert reread["version"] == 1
    assert_instant_equals(reread["updated_at"], project["updated_at"], "updated_at")
    assert reread["occupancy_status"] == OccupancyStatus.PRE_OCCUPANCY
    assert_decimal_equals(reread["completeness_pct_strict"], 0.00)


def test_a_site_code_that_breaks_its_pattern_opens_no_project(
    client: ApiClient,
) -> None:
    """The owner's site code is matched exactly, without folding or trimming.

    Two to four capitals followed by one or two digits is the whole of the domain,
    so a lowercase code carrying three digits is refused outright and the job is
    never opened.

    Design: Corner/entities/create_project_with_malformed_site_code_returns_invalid_request
    """
    response = client.create_project(
        {**_PROJECT_PAYLOAD, "site_code": "rvt123"}, PM_HEADERS
    )
    validate_error(response, ERR_INVALID_REQUEST, 400)

    _, meta = validate_paginated(client.list_projects(PM_HEADERS))
    assert meta["total_count"] == 0


def test_a_cable_category_outside_the_catalogue_domain_registers_nothing(
    client: ApiClient,
) -> None:
    """The catalogue admits only the six cable categories the contract names.

    A category outside that closed set is a malformed request rather than a new kind
    of cable, and the catalogue stays empty.

    Design: Corner/entities/create_cable_type_with_unknown_category_returns_invalid_request
    """
    response = client.create_cable_type(
        {
            "category": "CAT7",
            "jacket_rating": JacketRating.CMP,
            "outer_diameter_mm": 7.9,
            "max_channel_length_m": 100.0,
            "shielded": False,
            "cost_per_meter_cents": 150,
            "applications": [Application.DATA_HORIZONTAL],
        },
        DESIGNER_HEADERS,
    )
    validate_error(response, ERR_INVALID_REQUEST, 400)

    _, meta = validate_paginated(client.list_cable_types(DESIGNER_HEADERS))
    assert meta["total_count"] == 0


def test_a_rack_drawn_against_a_room_that_does_not_exist_is_refused(
    client: ApiClient,
) -> None:
    """A rack hangs off a telecom room, so that room must resolve first.

    A body key naming no room at all fails the existence check and reports the room
    as the missing kind, leaving the elevation collection for that identifier empty.

    Design: Corner/entities/create_rack_under_unknown_room_returns_telecom_room_not_found
    """
    _open_project(client)

    response = client.create_rack(
        {"telecom_room_id": _UNKNOWN_UUID, "rack_code": "A", "total_ru": 42},
        DESIGNER_HEADERS,
    )
    validate_error(response, ERR_TELECOM_ROOM_NOT_FOUND, 404)

    _, meta = validate_paginated(
        client.list_racks(DESIGNER_HEADERS, params={"telecom_room_id": _UNKNOWN_UUID})
    )
    assert meta["total_count"] == 0


def test_one_link_occupies_two_segments_through_the_routing_junction(
    client: ApiClient,
) -> None:
    """A drop crossing two trays is held by two routings, one per tray.

    The chain is walked downstream a parent-child hop at a time, each routing
    snapshots the same cable area into the tray it enters, and the junction answers
    from both ends: the link counts two routed segments while each tray counts the
    one cable it carries.

    Design: Corner/entities/one_link_occupies_two_pathway_segments_through_the_junction_entity
    """
    project = _open_project(client)
    room = fx.create_room(
        client,
        project["id"],
        room_code="TR01",
        floor=3,
        branch_circuit_amps=20,
        ups_capacity_va=3000,
    )
    cable = _plenum_cat6a(client)
    upstream = fx.create_segment(
        client,
        project["id"],
        segment_code="PS-A",
        pathway_type=PathwayType.CABLE_TRAY,
        usable_area_sq_mm=20000.0,
        length_m=40.0,
        bend_count=0,
        in_plenum_space=True,
        shared_with_power=False,
        power_separation_mm=0,
    )
    downstream = fx.create_segment(
        client,
        project["id"],
        segment_code="PS-B",
        pathway_type=PathwayType.CABLE_TRAY,
        usable_area_sq_mm=18000.0,
        length_m=25.0,
        bend_count=0,
        in_plenum_space=True,
        shared_with_power=False,
        power_separation_mm=0,
        upstream_segment_id=upstream["id"],
    )
    link = fx.create_link(
        client,
        project["id"],
        room["id"],
        cable["id"],
        identifier="TR01-A01",
        application=Application.DATA_HORIZONTAL,
        horizontal_length_m=60.00,
        consolidation_point_stub_m=0,
        patch_cord_allowance_m=2.00,
    )

    first_response = client.create_link_route(
        {
            "link_id": link["id"],
            "pathway_segment_id": upstream["id"],
            "sequence_index": 1,
            "expected_segment_version": fx.segment_version(client, upstream["id"]),
        },
        DESIGNER_HEADERS,
    )
    first_route = validate_success(first_response, 201)
    second_response = client.create_link_route(
        {
            "link_id": link["id"],
            "pathway_segment_id": downstream["id"],
            "sequence_index": 2,
            "expected_segment_version": fx.segment_version(client, downstream["id"]),
        },
        DESIGNER_HEADERS,
    )
    second_route = validate_success(second_response, 201)

    for route in (first_route, second_route):
        assert route["route_state"] == RouteState.OCCUPYING
        assert_decimal_equals(route["consumed_area_sq_mm"], 49.02)
    assert first_route["sequence_index"] == 1
    assert second_route["sequence_index"] == 2

    assert fx.read_link(client, link["id"])["routed_segment_count"] == 2

    by_link, by_link_meta = validate_paginated(
        client.list_link_routes(DESIGNER_HEADERS, params={"link_id": link["id"]})
    )
    assert by_link_meta["total_count"] == 2
    assert sorted(row["sequence_index"] for row in by_link) == [1, 2]

    _, by_segment_meta = validate_paginated(
        client.list_link_routes(
            DESIGNER_HEADERS, params={"pathway_segment_id": downstream["id"]}
        )
    )
    assert by_segment_meta["total_count"] == 1

    upstream_row = fx.read_segment(client, upstream["id"])
    assert upstream_row["occupying_route_count"] == 1
    assert_decimal_equals(upstream_row["fill_area_used_sq_mm"], 49.02)
    assert_fill_ledger(upstream_row)


def test_a_recorded_test_result_carries_no_revision_counter_or_update_stamp(
    client: ApiClient,
) -> None:
    """A field measurement is filed once and never edited.

    The tester's row exposes only its identity and the moment it was written, with
    no revision counter and no update stamp, and the detail read agrees: the
    operator who ran the tester, the verdict and the measured length come back
    exactly as filed. A retest is a new row, never a correction of this one.

    Design: Corner/entities/test_result_rows_carry_no_version_and_have_no_update_endpoint
    """
    project = _open_project(client)
    room = fx.create_room(
        client,
        project["id"],
        room_code="TR01",
        floor=3,
        branch_circuit_amps=20,
        ups_capacity_va=3000,
    )
    fx.verify_grounding(
        client,
        room["id"],
        tgb_installed=True,
        bonding_conductor_awg=6,
        ground_resistance_milliohms=5000,
    )
    cable = _plenum_cat6a(client)
    segment = fx.create_segment(
        client,
        project["id"],
        segment_code="PS-A",
        pathway_type=PathwayType.CABLE_TRAY,
        usable_area_sq_mm=20000.0,
        length_m=40.0,
        bend_count=0,
        in_plenum_space=True,
        shared_with_power=False,
        power_separation_mm=0,
    )
    coordination = fx.create_coordination(
        client,
        project["id"],
        trade=Trade.CEILING,
        milestone=Milestone.PATHWAY_ROUGH_IN,
    )
    fx.confirm_coordination(client, coordination["id"], confirmed_date="2026-08-05")
    link = fx.create_link(
        client,
        project["id"],
        room["id"],
        cable["id"],
        identifier="TR01-A01",
        application=Application.DATA_HORIZONTAL,
        horizontal_length_m=85.63,
        consolidation_point_stub_m=0,
        patch_cord_allowance_m=2.00,
    )
    fx.route_link(client, link["id"], segment["id"], sequence_index=1)
    fx.pull_link(client, link["id"])
    fx.terminate_link(client, link["id"])

    create_response = client.create_test_result(
        {
            "link_id": link["id"],
            "test_standard": TestStandard.PERMANENT_LINK,
            "tester_model": "DSX-8000",
            "insertion_loss_db": 15.0,
            "next_margin_db": 3.2,
            "return_loss_margin_db": 2.1,
            "length_measured_m": 85.63,
        },
        TESTER_HEADERS,
    )
    result = validate_success(create_response, 201)
    assert_immutable_fields(result)
    assert_instant_field(result["created_at"], "created_at")

    detail = validate_success(client.get_test_result(result["id"], TESTER_HEADERS), 200)
    assert detail["id"] == result["id"]
    assert detail["link_id"] == link["id"]
    assert detail["tester_user_id"] == TEST_TECHNICIAN_ID
    assert detail["outcome"] == TestOutcome.PASS
    assert_decimal_equals(detail["length_measured_m"], 85.63)
    assert_immutable_fields(detail)
