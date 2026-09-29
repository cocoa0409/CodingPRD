"""Conditional, cross-entity and priority-ordered validations on write paths.

Each test drives one refusal and, where the contract admits a neighbouring
request, the accepting branch beside it, so that a rule is pinned to the input it
is actually keyed on rather than to the call site.
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
    ERR_APPLICATION_NOT_SUPPORTED,
    ERR_BONDING_NON_COMPLIANT,
    ERR_COORDINATION_CYCLE,
    ERR_CROSS_PROJECT_REFERENCE,
    ERR_DUPLICATE_LINK_IDENTIFIER,
    ERR_IDENTIFIER_FORMAT_INVALID,
    ERR_LABEL_MISMATCH,
    ERR_LINK_NOT_ROUTED,
    ERR_OCCUPANCY_READINESS_NOT_MET,
    ERR_PLENUM_RATING_REQUIRED,
    ERR_POWER_CAPACITY_EXCEEDED,
    ERR_PREDECESSOR_NOT_RELEASED,
    ERR_RACK_CAPACITY_EXCEEDED,
    ERR_ROUTE_SEQUENCE_GAP,
    ERR_TICKET_WINDOW_NOT_OPEN,
    ERR_TRADE_NOT_COORDINATED,
)
from test_helpers.assertions import assert_cents, assert_decimal_equals
from test_helpers.factories import (
    confirm_payload,
    grounding_payload,
    label_payload,
    link_payload,
    link_route_payload,
    occupancy_payload,
    rack_unit_assignment_payload,
    trade_coordination_payload,
)
from test_helpers.test_users import (
    CERTIFIER_HEADERS,
    DESIGNER_HEADERS,
    INSTALLER_HEADERS,
    PM_HEADERS,
)
from test_helpers.types import (
    Application,
    CableCategory,
    CoordinationState,
    GroundingStatus,
    IdentifierScheme,
    InstallState,
    JacketRating,
    Milestone,
    OccupancyStatus,
    PathwayType,
    RecordState,
    RoomState,
    RouteState,
    TicketState,
    TicketType,
    Trade,
)


# ── Plenum rating is keyed on the segment, not the cable ────────────────────
def _riser_cable_and_two_segments(client: ApiClient) -> dict:
    """One riser-jacketed CMR cable, one plenum tray and one ordinary conduit."""
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
        category=CableCategory.CAT6A,
        jacket_rating=JacketRating.CMR,
        outer_diameter_mm=7.9,
        max_channel_length_m=100.0,
        shielded=False,
        cost_per_meter_cents=130,
        applications=[Application.DATA_HORIZONTAL],
    )
    plenum_segment = fx.create_segment(
        client,
        project["id"],
        segment_code="PS-P",
        pathway_type=PathwayType.CABLE_TRAY,
        usable_area_sq_mm=20000.0,
        length_m=40.0,
        bend_count=0,
        in_plenum_space=True,
    )
    open_segment = fx.create_segment(
        client,
        project["id"],
        segment_code="PS-N",
        pathway_type=PathwayType.EMT_CONDUIT,
        usable_area_sq_mm=573.0,
        length_m=20.0,
        bend_count=0,
        in_plenum_space=False,
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
    return {
        "project_id": project["id"],
        "link_id": link["id"],
        "plenum_segment": plenum_segment,
        "open_segment": open_segment,
    }


def test_a_riser_jacket_is_refused_by_the_segment_inside_the_plenum_space(
    client: ApiClient,
) -> None:
    """A CMR jacket may not enter a run that passes through the return air.

    The tray is flagged as sitting inside the plenum cavity, so the riser-rated
    cable is refused outright. The refusal is a complete no-op on the drawing: the
    tray carries no cable, its fill ledger reads zero and its revision counter has
    not moved.

    Design: Corner/validations/plenum_rating_applies_only_to_segments_inside_the_plenum_space
    """
    scenario = _riser_cable_and_two_segments(client)
    segment = scenario["plenum_segment"]

    response = client.create_link_route(
        link_route_payload(scenario["link_id"], segment["id"], segment["version"]),
        DESIGNER_HEADERS,
    )
    validate_error(response, ERR_PLENUM_RATING_REQUIRED, 422)

    after = fx.read_segment(client, segment["id"])
    assert after["occupying_route_count"] == 0
    assert_decimal_equals(after["fill_area_used_sq_mm"], 0.00)
    assert after["version"] == segment["version"]
    assert fx.read_link(client, scenario["link_id"])["routed_segment_count"] == 0


def test_the_same_riser_jacket_is_admitted_outside_the_plenum_space(
    client: ApiClient,
) -> None:
    """The identical cable is legal in a conduit that never sees the return air.

    The rule reads the segment's plenum flag rather than the cable alone, so the
    very cable the plenum tray refused is admitted by the ordinary conduit, and it
    snapshots the 49.02 square millimetres a 7.9 mm cable occupies.

    Design: Corner/validations/plenum_rating_applies_only_to_segments_inside_the_plenum_space
    """
    scenario = _riser_cable_and_two_segments(client)
    plenum = scenario["plenum_segment"]
    client.create_link_route(
        link_route_payload(scenario["link_id"], plenum["id"], plenum["version"]),
        DESIGNER_HEADERS,
    )

    open_segment = scenario["open_segment"]
    response = client.create_link_route(
        link_route_payload(
            scenario["link_id"], open_segment["id"], open_segment["version"]
        ),
        DESIGNER_HEADERS,
    )
    route = validate_success(response, 201)
    assert route["route_state"] == RouteState.OCCUPYING
    assert_decimal_equals(route["consumed_area_sq_mm"], 49.02)
    assert fx.read_link(client, scenario["link_id"])["routed_segment_count"] == 1


# ── The cable's approved application list ───────────────────────────────────
def test_a_camera_drop_needs_a_cable_approved_to_carry_cameras(
    client: ApiClient,
) -> None:
    """The check reads the catalogue entry's approved list, not the enum domain.

    CAMERA is a perfectly legal application, yet a cable approved only for
    horizontal data may not carry it. The same CAMERA link built from a cable whose
    approved list includes CAMERA is designed without complaint, and only that one
    link counts against the project.

    Design: Corner/validations/application_must_be_listed_on_the_selected_cable_type
    """
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
    data_only = fx.create_cable_type(
        client,
        category=CableCategory.CAT6A,
        jacket_rating=JacketRating.CMP,
        outer_diameter_mm=7.9,
        max_channel_length_m=100.0,
        shielded=False,
        cost_per_meter_cents=150,
        applications=[Application.DATA_HORIZONTAL],
    )
    multi_service = fx.create_cable_type(
        client,
        category=CableCategory.CAT6A,
        jacket_rating=JacketRating.CMP,
        outer_diameter_mm=7.9,
        max_channel_length_m=100.0,
        shielded=False,
        cost_per_meter_cents=155,
        applications=[Application.DATA_HORIZONTAL, Application.CAMERA],
    )

    refused = client.create_link(
        link_payload(
            project["id"],
            room["id"],
            data_only["id"],
            identifier="TR01-C01",
            application=Application.CAMERA,
            horizontal_length_m=40.00,
            consolidation_point_stub_m=0,
            patch_cord_allowance_m=2.00,
        ),
        DESIGNER_HEADERS,
    )
    validate_error(refused, ERR_APPLICATION_NOT_SUPPORTED, 422)

    admitted = client.create_link(
        link_payload(
            project["id"],
            room["id"],
            multi_service["id"],
            identifier="TR01-C02",
            application=Application.CAMERA,
            horizontal_length_m=40.00,
            consolidation_point_stub_m=0,
            patch_cord_allowance_m=2.00,
        ),
        DESIGNER_HEADERS,
    )
    link = validate_success(admitted, 201)
    assert link["application"] == Application.CAMERA
    assert link["cable_type_id"] == multi_service["id"]
    assert fx.read_project(client, project["id"])["total_link_count"] == 1


# ── The bonding conductor gate runs before the resistance grading ───────────
def _rough_in_room(client: ApiClient) -> dict:
    """A telecom room in ROUGH_IN whose bonding has never been measured."""
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
    return {"project_id": project["id"], "room": room}


def test_a_thin_bonding_conductor_is_refused_before_any_verdict_is_stored(
    client: ApiClient,
) -> None:
    """A conductor thinner than #6 AWG is a code violation, not a measurement.

    A #8 AWG submission is rejected outright, so the room keeps the UNVERIFIED
    grade it was created with rather than being graded NON_COMPLIANT: an
    implementation that graded the reading first would have stored a verdict. The
    room stays in ROUGH_IN and its revision counter never moves.

    Design: Corner/validations/a_thin_bonding_conductor_is_refused_before_any_measurement_is_stored
    """
    scenario = _rough_in_room(client)
    room = scenario["room"]

    response = client.verify_grounding(
        room["id"],
        grounding_payload(
            tgb_installed=True,
            bonding_conductor_awg=8,
            ground_resistance_milliohms=100.00,
        ),
        PM_HEADERS,
    )
    validate_error(response, ERR_BONDING_NON_COMPLIANT, 422)

    after = fx.read_room(client, room["id"])
    assert after["grounding_status"] == GroundingStatus.UNVERIFIED
    assert after["room_state"] == RoomState.ROUGH_IN
    assert after["version"] == room["version"]


def test_a_number_six_conductor_at_the_resistance_limit_grades_compliant(
    client: ApiClient,
) -> None:
    """The refused submission does not poison the room: a legal one still lands.

    A #6 AWG conductor measuring exactly 5000 milliohms satisfies all three
    conditions, so the room is graded COMPLIANT and advances to GROUNDED, which is
    what unblocks termination. Both measurements are stored as submitted.

    Design: Corner/validations/a_thin_bonding_conductor_is_refused_before_any_measurement_is_stored
    """
    scenario = _rough_in_room(client)
    room_id = scenario["room"]["id"]
    client.verify_grounding(
        room_id,
        grounding_payload(bonding_conductor_awg=8, ground_resistance_milliohms=100.00),
        PM_HEADERS,
    )

    response = client.verify_grounding(
        room_id,
        grounding_payload(
            tgb_installed=True,
            bonding_conductor_awg=6,
            ground_resistance_milliohms=5000,
        ),
        PM_HEADERS,
    )
    graded = validate_success(response, 200)
    assert graded["grounding_status"] == GroundingStatus.COMPLIANT
    assert graded["room_state"] == RoomState.GROUNDED

    after = fx.read_room(client, room_id)
    assert after["bonding_conductor_awg"] == 6
    assert_decimal_equals(after["ground_resistance_milliohms"], 5000)


# ── Cross-project references at two different call sites ────────────────────
def test_cross_project_references_are_refused_on_links_and_on_routes(
    client: ApiClient,
) -> None:
    """Two jobs on one site may not borrow each other's rooms or trays.

    A link that names a room belonging to the neighbouring job, and a routing that
    joins this job's link to that job's tray, are both refused as cross-aggregate
    references. Neither is a missing-row problem: every referenced record exists,
    so the answer is a conflict rather than a not-found, and neither project's
    ledgers move.

    Design: Corner/validations/cross_project_references_are_refused_on_links_and_on_routes
    """
    first = fx.create_project(
        client,
        name="Riverside Tower Cabling",
        site_code="RVT1",
        plenum_ceiling=True,
        identifier_scheme=IdentifierScheme.TIA_606_CLASS_1,
    )
    first_room = fx.create_room(
        client,
        first["id"],
        room_code="TR01",
        floor=3,
        branch_circuit_amps=20,
        ups_capacity_va=3000,
    )
    second = fx.create_project(
        client,
        name="Riverside Annex Cabling",
        site_code="RVT2",
        plenum_ceiling=False,
        identifier_scheme=IdentifierScheme.TIA_606_CLASS_1,
    )
    second_room = fx.create_room(
        client,
        second["id"],
        room_code="TR02",
        floor=4,
        branch_circuit_amps=20,
        ups_capacity_va=3000,
    )
    foreign_segment = fx.create_segment(
        client,
        second["id"],
        segment_code="PS-X",
        pathway_type=PathwayType.CABLE_TRAY,
        usable_area_sq_mm=20000.0,
        length_m=40.0,
        bend_count=0,
    )
    cable = fx.create_cable_type(
        client,
        category=CableCategory.CAT6A,
        jacket_rating=JacketRating.CMP,
        outer_diameter_mm=7.9,
        max_channel_length_m=100.0,
        shielded=False,
        cost_per_meter_cents=150,
        applications=[Application.DATA_HORIZONTAL],
    )
    link = fx.create_link(
        client,
        first["id"],
        first_room["id"],
        cable["id"],
        identifier="TR01-A01",
        horizontal_length_m=40.00,
        consolidation_point_stub_m=0,
        patch_cord_allowance_m=2.00,
    )

    borrowed_room = client.create_link(
        link_payload(
            first["id"],
            second_room["id"],
            cable["id"],
            identifier="TR01-A02",
            horizontal_length_m=40.00,
            consolidation_point_stub_m=0,
            patch_cord_allowance_m=2.00,
        ),
        DESIGNER_HEADERS,
    )
    validate_error(borrowed_room, ERR_CROSS_PROJECT_REFERENCE, 409)

    borrowed_tray = client.create_link_route(
        link_route_payload(
            link["id"], foreign_segment["id"], foreign_segment["version"]
        ),
        DESIGNER_HEADERS,
    )
    validate_error(borrowed_tray, ERR_CROSS_PROJECT_REFERENCE, 409)

    assert fx.read_project(client, first["id"])["total_link_count"] == 1
    assert fx.read_project(client, second["id"])["total_link_count"] == 0
    after = fx.read_segment(client, foreign_segment["id"])
    assert after["occupying_route_count"] == 0
    assert after["version"] == foreign_segment["version"]


# ── Chain continuity and duplicate positions ────────────────────────────────
def test_route_continuity_refuses_an_unrelated_segment_and_a_repeated_position(
    client: ApiClient,
) -> None:
    """A chain is walked one parent-child hop at a time and each position is used once.

    The link already occupies the tray at position 1. A second position landing on
    an unrelated pathway root is refused, because that segment is not fed by the
    segment at the preceding position; the conduit that really is fed by it is
    admitted at the same position; and asking for that position a second time is
    refused as well. The refused root never carries the cable.

    Design: Corner/validations/route_continuity_is_checked_against_the_previous_index_and_forbids_duplicates
    """
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
        category=CableCategory.CAT6A,
        jacket_rating=JacketRating.CMP,
        outer_diameter_mm=7.9,
        max_channel_length_m=100.0,
        shielded=False,
        cost_per_meter_cents=150,
        applications=[Application.DATA_HORIZONTAL],
    )
    head = fx.create_segment(
        client,
        project["id"],
        segment_code="PS-A",
        pathway_type=PathwayType.CABLE_TRAY,
        usable_area_sq_mm=20000.0,
        length_m=40.0,
        bend_count=0,
    )
    child = fx.create_segment(
        client,
        project["id"],
        segment_code="PS-B",
        pathway_type=PathwayType.EMT_CONDUIT,
        usable_area_sq_mm=573.0,
        length_m=12.0,
        bend_count=0,
        upstream_segment_id=head["id"],
    )
    stranger = fx.create_segment(
        client,
        project["id"],
        segment_code="PS-D",
        pathway_type=PathwayType.EMT_CONDUIT,
        usable_area_sq_mm=573.0,
        length_m=9.0,
        bend_count=0,
    )
    link = fx.create_link(
        client,
        project["id"],
        room["id"],
        cable["id"],
        identifier="TR01-A01",
        horizontal_length_m=40.00,
        consolidation_point_stub_m=0,
        patch_cord_allowance_m=2.00,
    )
    fx.route_link(client, link["id"], head["id"], sequence_index=1)

    gap = client.create_link_route(
        link_route_payload(
            link["id"],
            stranger["id"],
            fx.segment_version(client, stranger["id"]),
            sequence_index=2,
        ),
        DESIGNER_HEADERS,
    )
    validate_error(gap, ERR_ROUTE_SEQUENCE_GAP, 422)

    admitted = client.create_link_route(
        link_route_payload(
            link["id"],
            child["id"],
            fx.segment_version(client, child["id"]),
            sequence_index=2,
        ),
        DESIGNER_HEADERS,
    )
    route = validate_success(admitted, 201)
    assert route["sequence_index"] == 2

    duplicate = client.create_link_route(
        link_route_payload(
            link["id"],
            child["id"],
            fx.segment_version(client, child["id"]),
            sequence_index=2,
        ),
        DESIGNER_HEADERS,
    )
    validate_error(duplicate, ERR_ROUTE_SEQUENCE_GAP, 422)

    assert fx.read_link(client, link["id"])["routed_segment_count"] == 2
    assert fx.read_segment(client, stranger["id"])["occupying_route_count"] == 0


# ── The pull reports the missing pathway before the missing milestone ───────
def test_a_pull_reports_the_missing_route_before_the_uncoordinated_trade(
    client: ApiClient,
) -> None:
    """With no pathway and no ceiling milestone, the missing pathway answers first.

    Adding the routing alone flips the answer to the trade milestone, and
    confirming that milestone finally admits the pull. The link sits in DESIGNED
    throughout both refusals, so neither of them advanced the physical work.

    Design: Corner/validations/routing_is_checked_before_the_trade_milestone_on_a_pull
    """
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
        category=CableCategory.CAT6A,
        jacket_rating=JacketRating.CMP,
        outer_diameter_mm=7.9,
        max_channel_length_m=100.0,
        shielded=False,
        cost_per_meter_cents=150,
        applications=[Application.DATA_HORIZONTAL],
    )
    tray = fx.create_segment(
        client,
        project["id"],
        segment_code="PS-A",
        pathway_type=PathwayType.CABLE_TRAY,
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
        horizontal_length_m=40.00,
        consolidation_point_stub_m=0,
        patch_cord_allowance_m=2.00,
    )

    unrouted = client.pull_link(link["id"], INSTALLER_HEADERS)
    validate_error(unrouted, ERR_LINK_NOT_ROUTED, 409)
    assert fx.read_link(client, link["id"])["install_state"] == InstallState.DESIGNED

    fx.route_link(client, link["id"], tray["id"])
    uncoordinated = client.pull_link(link["id"], INSTALLER_HEADERS)
    validate_error(uncoordinated, ERR_TRADE_NOT_COORDINATED, 409)
    assert fx.read_link(client, link["id"])["install_state"] == InstallState.DESIGNED

    coordination = fx.create_coordination(
        client,
        project["id"],
        trade=Trade.CEILING,
        milestone=Milestone.PATHWAY_ROUGH_IN,
    )
    fx.confirm_coordination(client, coordination["id"], confirmed_date="2026-08-05")

    admitted = client.pull_link(link["id"], INSTALLER_HEADERS)
    pulled = validate_success(admitted, 200)
    assert pulled["install_state"] == InstallState.PULLED


# ── Rack height is checked before room power ────────────────────────────────
def _empty_rack(client: ApiClient) -> dict:
    """A 42 RU rack in a room fed by a 3000 VA UPS, with nothing placed yet."""
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
    return {"room_id": room["id"], "rack": rack}


def test_rack_height_answers_before_room_power_on_a_doubly_illegal_placement(
    client: ApiClient,
) -> None:
    """One placement breaks the elevation and the UPS at once; the elevation answers.

    A switch spanning units 40 to 45 overruns a 42 RU rack while also drawing 5000
    VA behind a 3000 VA UPS. The height limit is screened first. Shrinking the
    interval to a legal one leaves only the power fault, which then surfaces. Both
    refusals leave the rack's revision counter where it was.

    Design: Corner/validations/rack_capacity_is_checked_before_room_power_capacity
    """
    scenario = _empty_rack(client)
    rack = scenario["rack"]

    too_tall = client.create_rack_unit_assignment(
        rack_unit_assignment_payload(
            rack["id"],
            rack["version"],
            equipment_label="CORE-SW-1",
            start_ru=40,
            end_ru=45,
            power_va=5000,
        ),
        DESIGNER_HEADERS,
    )
    validate_error(too_tall, ERR_RACK_CAPACITY_EXCEEDED, 422)

    too_hungry = client.create_rack_unit_assignment(
        rack_unit_assignment_payload(
            rack["id"],
            rack["version"],
            equipment_label="CORE-SW-1",
            start_ru=40,
            end_ru=42,
            power_va=5000,
        ),
        DESIGNER_HEADERS,
    )
    validate_error(too_hungry, ERR_POWER_CAPACITY_EXCEEDED, 422)

    after = fx.read_rack(client, rack["id"])
    assert after["version"] == rack["version"]
    assert after["occupied_ru"] == 0
    assert after["power_draw_va"] == 0
    assert fx.read_room(client, scenario["room_id"])["power_load_va"] == 0


def test_the_legal_placement_moves_the_rack_and_room_ledgers_together(
    client: ApiClient,
) -> None:
    """After both refusals the originally observed rack revision is still current.

    A 40-to-42 placement drawing 1200 VA spans three rack units, and the placement
    propagates outwards: the rack reports three units occupied and thirty-nine free
    at revision two, and the room's UPS ledger reads 1200 VA of load against 1800
    VA of headroom.

    Design: Corner/validations/rack_capacity_is_checked_before_room_power_capacity
    """
    scenario = _empty_rack(client)
    rack = scenario["rack"]
    for end_ru, power_va in ((45, 5000), (42, 5000)):
        client.create_rack_unit_assignment(
            rack_unit_assignment_payload(
                rack["id"],
                rack["version"],
                equipment_label="CORE-SW-1",
                start_ru=40,
                end_ru=end_ru,
                power_va=power_va,
            ),
            DESIGNER_HEADERS,
        )

    response = client.create_rack_unit_assignment(
        rack_unit_assignment_payload(
            rack["id"],
            rack["version"],
            equipment_label="CORE-SW-1",
            start_ru=40,
            end_ru=42,
            power_va=1200,
        ),
        DESIGNER_HEADERS,
    )
    placement = validate_success(response, 201)
    assert placement["span_ru"] == 3
    assert placement["power_va"] == 1200

    after = fx.read_rack(client, rack["id"])
    assert after["occupied_ru"] == 3
    assert after["available_ru"] == 39
    assert after["power_draw_va"] == 1200
    assert after["version"] == 2

    room = fx.read_room(client, scenario["room_id"])
    assert room["power_load_va"] == 1200
    assert room["power_headroom_va"] == 1800


# ── Identifier format, then uniqueness within the project ───────────────────
def test_identifier_format_is_screened_before_uniqueness_within_the_project(
    client: ApiClient,
) -> None:
    """The same label string is a collision in one job and perfectly free in another.

    Repeating TR01-A01 inside the job that already carries it is a duplicate, while
    a TR1-A01 that no link carries never reaches the uniqueness test at all because
    it does not match the Class 1 pattern. The identical string is then designed
    without complaint in the neighbouring job, so uniqueness is scoped per project.

    Design: Corner/validations/link_identifier_uniqueness_is_scoped_to_the_project
    """
    first = fx.create_project(
        client,
        name="Riverside Tower Cabling",
        site_code="RVT1",
        plenum_ceiling=True,
        identifier_scheme=IdentifierScheme.TIA_606_CLASS_1,
    )
    first_room = fx.create_room(
        client,
        first["id"],
        room_code="TR01",
        floor=3,
        branch_circuit_amps=20,
        ups_capacity_va=3000,
    )
    second = fx.create_project(
        client,
        name="Riverside Annex Cabling",
        site_code="RVT2",
        plenum_ceiling=False,
        identifier_scheme=IdentifierScheme.TIA_606_CLASS_1,
    )
    second_room = fx.create_room(
        client,
        second["id"],
        room_code="TR02",
        floor=4,
        branch_circuit_amps=20,
        ups_capacity_va=3000,
    )
    cable = fx.create_cable_type(
        client,
        category=CableCategory.CAT6A,
        jacket_rating=JacketRating.CMP,
        outer_diameter_mm=7.9,
        max_channel_length_m=100.0,
        shielded=False,
        cost_per_meter_cents=150,
        applications=[Application.DATA_HORIZONTAL],
    )
    fx.create_link(
        client,
        first["id"],
        first_room["id"],
        cable["id"],
        identifier="TR01-A01",
        horizontal_length_m=40.00,
        consolidation_point_stub_m=0,
        patch_cord_allowance_m=2.00,
    )

    repeat = client.create_link(
        link_payload(
            first["id"],
            first_room["id"],
            cable["id"],
            identifier="TR01-A01",
            horizontal_length_m=41.00,
            consolidation_point_stub_m=0,
            patch_cord_allowance_m=2.00,
        ),
        DESIGNER_HEADERS,
    )
    validate_error(repeat, ERR_DUPLICATE_LINK_IDENTIFIER, 409)

    malformed = client.create_link(
        link_payload(
            first["id"],
            first_room["id"],
            cable["id"],
            identifier="TR1-A01",
            horizontal_length_m=41.00,
            consolidation_point_stub_m=0,
            patch_cord_allowance_m=2.00,
        ),
        DESIGNER_HEADERS,
    )
    validate_error(malformed, ERR_IDENTIFIER_FORMAT_INVALID, 422)

    elsewhere = client.create_link(
        link_payload(
            second["id"],
            second_room["id"],
            cable["id"],
            identifier="TR01-A01",
            horizontal_length_m=41.00,
            consolidation_point_stub_m=0,
            patch_cord_allowance_m=2.00,
        ),
        DESIGNER_HEADERS,
    )
    twin = validate_success(elsewhere, 201)
    assert twin["identifier"] == "TR01-A01"

    assert fx.read_project(client, first["id"])["total_link_count"] == 1
    assert fx.read_project(client, second["id"])["total_link_count"] == 1


# ── The applied label must match the designed identifier exactly ────────────
def _terminated_link_labelled_tr01_a01(client: ApiClient) -> dict:
    """A TERMINATED link whose designed identifier is TR01-A01, not yet labelled."""
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
    fx.verify_grounding(
        client,
        room["id"],
        tgb_installed=True,
        bonding_conductor_awg=6,
        ground_resistance_milliohms=5000,
    )
    cable = fx.create_cable_type(
        client,
        category=CableCategory.CAT6A,
        jacket_rating=JacketRating.CMP,
        outer_diameter_mm=7.9,
        max_channel_length_m=100.0,
        shielded=False,
        cost_per_meter_cents=150,
        applications=[Application.DATA_HORIZONTAL],
    )
    tray = fx.create_segment(
        client,
        project["id"],
        segment_code="PS-A",
        pathway_type=PathwayType.CABLE_TRAY,
        usable_area_sq_mm=20000.0,
        length_m=40.0,
        bend_count=0,
        in_plenum_space=True,
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
        horizontal_length_m=40.00,
        consolidation_point_stub_m=0,
        patch_cord_allowance_m=2.00,
    )
    fx.route_link(client, link["id"], tray["id"])
    fx.pull_link(client, link["id"])
    fx.terminate_link(client, link["id"])
    return {"project_id": project["id"], "link_id": link["id"]}


def test_a_mismatched_applied_label_leaves_the_record_dimension_unlabeled(
    client: ApiClient,
) -> None:
    """A label reading TR01-A02 on a link designed as TR01-A01 is refused.

    Nothing partial is accepted: the administration dimension stays UNLABELED and
    the link carries no applied identifier at all, while the physical work it
    already did remains TERMINATED.

    Design: Corner/validations/the_applied_label_must_match_the_designed_identifier_exactly
    """
    scenario = _terminated_link_labelled_tr01_a01(client)

    response = client.label_link(
        scenario["link_id"], label_payload("TR01-A02"), INSTALLER_HEADERS
    )
    validate_error(response, ERR_LABEL_MISMATCH, 422)

    link = fx.read_link(client, scenario["link_id"])
    assert link["record_state"] == RecordState.UNLABELED
    assert link["applied_identifier"] is None
    assert link["install_state"] == InstallState.TERMINATED


def test_the_exact_applied_label_advances_only_the_record_dimension(
    client: ApiClient,
) -> None:
    """Only the exact designed string moves the administration dimension forward.

    The label the crew actually applied is stored and the record dimension reaches
    LABELED, while the installation dimension stays where it was: the two
    dimensions advance on separate tracks.

    Design: Corner/validations/the_applied_label_must_match_the_designed_identifier_exactly
    """
    scenario = _terminated_link_labelled_tr01_a01(client)
    client.label_link(
        scenario["link_id"], label_payload("TR01-A02"), INSTALLER_HEADERS
    )

    response = client.label_link(
        scenario["link_id"], label_payload("TR01-A01"), INSTALLER_HEADERS
    )
    labelled = validate_success(response, 200)
    assert labelled["record_state"] == RecordState.LABELED
    assert labelled["applied_identifier"] == "TR01-A01"
    assert labelled["install_state"] == InstallState.TERMINATED


# ── Predecessor release, and no repeated pair in a chain ─────────────────────
def _ceiling_then_electrical_chain(client: ApiClient) -> dict:
    """A confirmed ceiling milestone with an electrical milestone chained behind it."""
    project = fx.create_project(
        client,
        name="Riverside Tower Cabling",
        site_code="RVT1",
        plenum_ceiling=True,
        identifier_scheme=IdentifierScheme.TIA_606_CLASS_1,
    )
    ceiling = fx.create_coordination(
        client,
        project["id"],
        trade=Trade.CEILING,
        milestone=Milestone.PATHWAY_ROUGH_IN,
    )
    fx.confirm_coordination(client, ceiling["id"], confirmed_date="2026-08-05")
    electrical = fx.create_coordination(
        client,
        project["id"],
        trade=Trade.ELECTRICAL,
        milestone=Milestone.POWER_ENERGIZE,
        predecessor_coordination_id=ceiling["id"],
    )
    return {
        "project_id": project["id"],
        "ceiling_id": ceiling["id"],
        "electrical_id": electrical["id"],
    }


def test_a_dependent_milestone_waits_for_its_predecessor_to_be_released(
    client: ApiClient,
) -> None:
    """A merely confirmed predecessor is not enough to confirm what depends on it.

    The electrical contractor cannot commit to energizing the panel while the
    ceiling trade has only promised a date; the refusal leaves the dependent
    milestone in REQUESTED with no committed date. Once the ceiling milestone is
    released, the same confirmation lands and stores the date it carried.

    Design: Corner/validations/a_dependent_milestone_waits_for_its_predecessor_and_cannot_repeat_the_pair
    """
    scenario = _ceiling_then_electrical_chain(client)

    early = client.confirm_trade_coordination(
        scenario["electrical_id"], confirm_payload("2026-08-10"), PM_HEADERS
    )
    validate_error(early, ERR_PREDECESSOR_NOT_RELEASED, 409)

    dependent = validate_success(
        client.get_trade_coordination(scenario["electrical_id"], PM_HEADERS), 200
    )
    assert dependent["coordination_state"] == CoordinationState.REQUESTED
    assert dependent["confirmed_date"] is None

    released = validate_success(
        client.release_trade_coordination(scenario["ceiling_id"], PM_HEADERS), 200
    )
    assert released["coordination_state"] == CoordinationState.RELEASED

    retried = client.confirm_trade_coordination(
        scenario["electrical_id"], confirm_payload("2026-08-10"), PM_HEADERS
    )
    confirmed = validate_success(retried, 200)
    assert confirmed["coordination_state"] == CoordinationState.CONFIRMED
    assert confirmed["confirmed_date"] == "2026-08-10"


def test_a_predecessor_chain_may_not_repeat_a_trade_and_milestone_pair(
    client: ApiClient,
) -> None:
    """A milestone may not depend on itself, however indirectly.

    A third coordination repeating the ceiling pathway rough-in already sitting two
    hops up its own predecessor chain is refused, and the project is left with the
    two coordinations it already had, so the refused row was never written.

    Design: Corner/validations/a_dependent_milestone_waits_for_its_predecessor_and_cannot_repeat_the_pair
    """
    scenario = _ceiling_then_electrical_chain(client)
    fx.release_coordination(client, scenario["ceiling_id"])
    fx.confirm_coordination(
        client, scenario["electrical_id"], confirmed_date="2026-08-10"
    )

    response = client.create_trade_coordination(
        trade_coordination_payload(
            scenario["project_id"],
            trade=Trade.CEILING,
            milestone=Milestone.PATHWAY_ROUGH_IN,
            predecessor_coordination_id=scenario["electrical_id"],
        ),
        PM_HEADERS,
    )
    validate_error(response, ERR_COORDINATION_CYCLE, 422)

    rows, meta = validate_paginated(
        client.list_trade_coordinations(
            PM_HEADERS, params={"project_id": scenario["project_id"]}
        )
    )
    assert meta["total_count"] == 2
    assert len(rows) == 2


# ── Occupancy reads the whole project, not the last link touched ─────────────
def _project_with_two_tested_links(client: ApiClient) -> dict:
    """A released ceiling milestone and two links each carrying a clean strict PASS."""
    scenario = fx.setup_base_scenario(client)
    first = fx.setup_tested_pass_link(client, scenario)
    second = fx.setup_tested_pass_link(client, scenario)
    return {
        "project_id": scenario["project_id"],
        "first_link_id": first["link_id"],
        "second_link_id": second["link_id"],
    }


def test_occupancy_waits_for_every_link_of_the_project_to_be_certified(
    client: ApiClient,
) -> None:
    """Handover is judged on the aggregate, not on the link most recently signed off.

    With one of two links certified the job stands at half its links certified, and
    the owner's representative is refused the space even though the ceiling trade has
    already released its milestone and the certified link is faultless on its own.
    Certifying the second link lifts the aggregate and the same declaration lands.

    Design: Corner/validations/occupancy_readiness_is_an_aggregate_over_every_link_of_the_project
    """
    scenario = _project_with_two_tested_links(client)
    fx.certify_link(client, scenario["first_link_id"])

    half = validate_success(
        client.get_certification_summary(scenario["project_id"], PM_HEADERS), 200
    )
    assert half["total_link_count"] == 2
    assert half["certified_link_count"] == 1
    assert_decimal_equals(half["completeness_pct_strict"], 50.00)

    refused = client.declare_occupancy(
        scenario["project_id"], occupancy_payload(), PM_HEADERS
    )
    validate_error(refused, ERR_OCCUPANCY_READINESS_NOT_MET, 409)
    assert (
        fx.read_project(client, scenario["project_id"])["occupancy_status"]
        == OccupancyStatus.PRE_OCCUPANCY
    )

    second = validate_success(
        client.certify_link(scenario["second_link_id"], CERTIFIER_HEADERS), 200
    )
    assert second["install_state"] == InstallState.CERTIFIED

    full = validate_success(
        client.get_certification_summary(scenario["project_id"], PM_HEADERS), 200
    )
    assert full["certified_link_count"] == 2
    assert_decimal_equals(full["completeness_pct_strict"], 100.00)

    accepted = validate_success(
        client.declare_occupancy(scenario["project_id"], occupancy_payload(), PM_HEADERS),
        200,
    )
    assert accepted["occupancy_status"] == OccupancyStatus.OCCUPIED


# ── The scheduled window is closed on the left and open on the right ─────────
def _occupied_project_with_a_scheduled_ticket(
    client: ApiClient, window_start: str, window_end: str
) -> dict:
    """A handed-over project with one crew booked into room TR01 for that window."""
    scenario = fx.setup_occupied_project(client)
    ticket = fx.create_ticket(
        client,
        scenario["project_id"],
        scenario["link_id"],
        scenario["room_id"],
        ticket_type=TicketType.MOVE,
        requested_window_start=window_start,
        requested_window_end=window_end,
        labor_hours_estimate=1.0,
        expedite_requested=False,
    )
    fx.schedule_ticket(
        client,
        ticket["id"],
        scheduled_window_start=window_start,
        scheduled_window_end=window_end,
    )
    return {
        "project_id": scenario["project_id"],
        "link_id": scenario["link_id"],
        "room_id": scenario["room_id"],
        "ticket_id": ticket["id"],
    }


def test_a_crew_may_start_exactly_on_the_scheduled_start_but_not_before_it(
    client: ApiClient,
) -> None:
    """The booked window is closed on its left edge.

    A crew arriving while the site clock still reads the start of August is turned
    away from a September booking and the ticket keeps waiting. Moved to the exact
    instant the window opens, the very same request is admitted, so the start edge
    counts as inside the window.

    Design: Corner/validations/the_scheduled_window_is_half_open_when_a_crew_tries_to_start
    """
    scenario = _occupied_project_with_a_scheduled_ticket(
        client, "2026-09-01T09:00:00Z", "2026-09-01T11:00:00Z"
    )

    early = client.start_mac_ticket(scenario["ticket_id"], INSTALLER_HEADERS)
    validate_error(early, ERR_TICKET_WINDOW_NOT_OPEN, 409)
    assert (
        fx.read_ticket(client, scenario["ticket_id"])["ticket_state"]
        == TicketState.SCHEDULED
    )

    fx.set_clock(client, "2026-09-01T09:00:00Z")
    started = validate_success(
        client.start_mac_ticket(scenario["ticket_id"], INSTALLER_HEADERS), 200
    )
    assert started["ticket_state"] == TicketState.IN_PROGRESS


def test_a_crew_may_not_start_at_the_instant_the_scheduled_window_closes(
    client: ApiClient,
) -> None:
    """The booked window is open on its right edge.

    Two crews share one room for the same two hours, which the room's capacity of two
    admits. One minute before the hour the first crew is let in; at exactly the
    closing instant the second is refused and stays booked. Neither attempt touches
    the money ledger, which still carries only the two one-hour estimates.

    Design: Corner/validations/the_scheduled_window_is_half_open_when_a_crew_tries_to_start
    """
    scenario = _occupied_project_with_a_scheduled_ticket(
        client, "2026-09-02T09:00:00Z", "2026-09-02T11:00:00Z"
    )
    second = fx.create_ticket(
        client,
        scenario["project_id"],
        scenario["link_id"],
        scenario["room_id"],
        ticket_type=TicketType.MOVE,
        requested_window_start="2026-09-02T09:00:00Z",
        requested_window_end="2026-09-02T11:00:00Z",
        labor_hours_estimate=1.0,
        expedite_requested=False,
    )
    fx.schedule_ticket(
        client,
        second["id"],
        scheduled_window_start="2026-09-02T09:00:00Z",
        scheduled_window_end="2026-09-02T11:00:00Z",
    )
    assert_cents(
        fx.read_project(client, scenario["project_id"])["consumed_mac_cents"], 19200
    )

    fx.set_clock(client, "2026-09-02T10:59:00Z")
    inside = validate_success(
        client.start_mac_ticket(scenario["ticket_id"], INSTALLER_HEADERS), 200
    )
    assert inside["ticket_state"] == TicketState.IN_PROGRESS

    fx.set_clock(client, "2026-09-02T11:00:00Z")
    at_the_close = client.start_mac_ticket(second["id"], INSTALLER_HEADERS)
    validate_error(at_the_close, ERR_TICKET_WINDOW_NOT_OPEN, 409)
    assert fx.read_ticket(client, second["id"])["ticket_state"] == TicketState.SCHEDULED
    assert_cents(
        fx.read_project(client, scenario["project_id"])["consumed_mac_cents"], 19200
    )
