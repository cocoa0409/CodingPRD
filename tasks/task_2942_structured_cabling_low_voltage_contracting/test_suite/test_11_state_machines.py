"""Declared lifecycles: the edges that exist, the edges that do not, and what a
refused transition leaves untouched.

Each test drives one resource along its declared transitions through the public
endpoints and then aims a trigger the state machine does not declare, checking
both the refusal code and that no ledger, stamp or revision counter moved.
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
    ERR_INVALID_ASSIGNMENT_STATE,
    ERR_INVALID_COORDINATION_STATE,
    ERR_INVALID_LINK_STATE,
    ERR_INVALID_ROOM_STATE,
    ERR_INVALID_ROUTE_STATE,
    ERR_INVALID_WARRANTY_STATE,
    ERR_LINK_NOT_TESTED,
    ERR_SEGMENT_CONDEMNED,
    ERR_TRADE_NOT_COORDINATED,
)
from test_helpers.assertions import (
    assert_decimal_equals,
    assert_rack_ru_identity,
    assert_room_power_identity,
)
from test_helpers.factories import (
    condemn_payload,
    confirm_payload,
    link_route_payload,
    release_payload,
    warranty_register_decision_payload,
    warranty_registration_payload,
    warranty_submit_payload,
    withdraw_payload,
)
from test_helpers.test_users import (
    CERTIFIER_HEADERS,
    DESIGNER_HEADERS,
    INSTALLER_HEADERS,
    MANUFACTURER_HEADERS,
    PM_HEADERS,
)
from test_helpers.types import (
    Application,
    AssignmentState,
    CoordinationState,
    GroundingStatus,
    IdentifierScheme,
    InstallState,
    ManufacturerProgram,
    Milestone,
    PathwayState,
    RecordState,
    RegistrationState,
    RoomState,
    RouteState,
    TestStandard,
    Trade,
    WarrantyStatus,
)


RIVERSIDE = {
    "name": "Riverside Tower Cabling",
    "site_code": "RVT1",
    "plenum_ceiling": True,
    "identifier_scheme": IdentifierScheme.TIA_606_CLASS_1,
}


def _riverside_project(client: ApiClient) -> dict:
    """The Riverside Tower job, labelled to the TIA-606 Class 1 scheme."""
    return fx.create_project(client, **RIVERSIDE)


def _riverside_room(client: ApiClient, project_id: str) -> dict:
    return fx.create_room(
        client,
        project_id,
        room_code="TR01",
        floor=3,
        branch_circuit_amps=20,
        ups_capacity_va=3000,
    )


def _horizontal_cable(client: ApiClient) -> dict:
    """A plenum-rated CAT6A approved only for horizontal data service."""
    return fx.create_cable_type(
        client,
        outer_diameter_mm=7.9,
        max_channel_length_m=100.0,
        cost_per_meter_cents=150,
        applications=[Application.DATA_HORIZONTAL],
    )


def _tray_segment(client: ApiClient, project_id: str) -> dict:
    return fx.create_segment(
        client,
        project_id,
        segment_code="PS-A",
        usable_area_sq_mm=20000.0,
        length_m=40.0,
        bend_count=0,
        in_plenum_space=True,
        shared_with_power=False,
        power_separation_mm=0,
    )


def _certified_project_with_a_ready_registration(client: ApiClient) -> dict:
    """One certified link, so the job is warranty-eligible and its registration READY.

    The registration is opened while the project is still uncertified, so the
    DRAFT to READY promotion happens as a consequence of the certification
    rather than as a client request.
    """
    project = _riverside_project(client)
    room = _riverside_room(client, project["id"])
    fx.verify_grounding(client, room["id"], ground_resistance_milliohms=5000)
    cable = _horizontal_cable(client)
    segment = _tray_segment(client, project["id"])
    coordination = fx.create_coordination(client, project["id"])
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
        horizontal_length_m=85.63,
        consolidation_point_stub_m=0,
        patch_cord_allowance_m=2.00,
    )
    fx.route_link(client, link["id"], segment["id"])
    fx.pull_link(client, link["id"])
    fx.terminate_link(client, link["id"])
    fx.label_link(client, link["id"], "TR01-A01")
    fx.record_link(client, link["id"], drawing_sheet_ref="E-501")
    fx.file_test(
        client,
        link["id"],
        test_standard=TestStandard.PERMANENT_LINK,
        tester_model="DSX-8000",
        insertion_loss_db=15.0,
        next_margin_db=3.2,
        return_loss_margin_db=2.1,
        length_measured_m=85.63,
    )
    fx.certify_link(client, link["id"])
    return {
        "project_id": project["id"],
        "room_id": room["id"],
        "segment_id": segment["id"],
        "link_id": link["id"],
        "registration_id": registration["id"],
    }


def test_submitting_a_ready_registration_freezes_the_evidence_and_repins_the_project(
    client: ApiClient,
) -> None:
    """Submission is the one client-driven edge out of READY, and it freezes the file.

    The certified population is stamped once and never moves again, the fifteen-year
    standard term survives intact because no link needed three test attempts, and the
    project's own warranty status follows the registration to SUBMITTED.

    Design: Corner/state_machines/warranty_submit_moves_ready_to_submitted_and_pins_the_project_version
    """
    scenario = _certified_project_with_a_ready_registration(client)
    project_version_at_submit = fx.project_version(client, scenario["project_id"])

    before = fx.read_registration(client, scenario["registration_id"])
    assert before["registration_state"] == RegistrationState.READY
    assert before["pinned_project_version"] == project_version_at_submit

    submitted = validate_success(
        client.submit_warranty_registration(
            scenario["registration_id"],
            warranty_submit_payload(project_version_at_submit),
            PM_HEADERS,
        ),
        200,
    )
    assert submitted["registration_state"] == RegistrationState.SUBMITTED
    assert submitted["submitted_certified_link_count"] == 1
    assert submitted["coverage_years"] == 15

    project = fx.read_project(client, scenario["project_id"])
    assert project["warranty_status"] == WarrantyStatus.SUBMITTED
    assert project["version"] == project_version_at_submit + 1

    after = fx.read_registration(client, scenario["registration_id"])
    assert after["pinned_project_version"] == project["version"]


def test_a_register_decision_stamps_the_manufacturer_number_on_the_registration(
    client: ApiClient,
) -> None:
    """The manufacturer's desk closes the file in one call.

    A REGISTER decision moves the registration out of SUBMITTED, stores the number
    the programme issued verbatim, leaves the rejection reason empty and the frozen
    coverage term alone, and carries the project's warranty status with it.

    Design: Corner/state_machines/warranty_decision_register_stamps_the_registration_number
    """
    scenario = _certified_project_with_a_ready_registration(client)
    fx.submit_registration(
        client, scenario["registration_id"], scenario["project_id"]
    )

    decided = validate_success(
        client.decide_warranty_registration(
            scenario["registration_id"],
            warranty_register_decision_payload(registration_number="MFR-2026-0042"),
            MANUFACTURER_HEADERS,
        ),
        200,
    )
    assert decided["registration_state"] == RegistrationState.REGISTERED
    assert decided["registration_number"] == "MFR-2026-0042"
    assert decided["rejection_reason"] is None
    assert decided["coverage_years"] == 15

    project = fx.read_project(client, scenario["project_id"])
    assert project["warranty_status"] == WarrantyStatus.REGISTERED

    _, meta = validate_paginated(
        client.list_warranty_registrations(
            PM_HEADERS,
            params={
                "project_id": scenario["project_id"],
                "registration_state": RegistrationState.REGISTERED.value,
            },
        )
    )
    assert meta["total_count"] == 1


def test_certifying_a_recorded_link_that_was_never_tested_is_refused(
    client: ApiClient,
) -> None:
    """The paperwork can be complete while the measurement is missing.

    The link is terminated and its as-built sheet is filed, so the administration
    dimension has nothing outstanding, but no field tester has ever been on it. The
    certifier is turned away on the installation dimension alone and the project's
    certified population stays empty.

    Design: Corner/state_machines/certify_a_recorded_but_untested_link_returns_link_not_tested
    """
    project = _riverside_project(client)
    room = _riverside_room(client, project["id"])
    fx.verify_grounding(client, room["id"], ground_resistance_milliohms=5000)
    cable = _horizontal_cable(client)
    segment = _tray_segment(client, project["id"])
    coordination = fx.create_coordination(client, project["id"])
    fx.confirm_coordination(client, coordination["id"], confirmed_date="2026-08-05")
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
    fx.terminate_link(client, link["id"])
    fx.label_link(client, link["id"], "TR01-A01")
    recorded = fx.record_link(client, link["id"], drawing_sheet_ref="E-501")
    assert recorded["record_state"] == RecordState.RECORDED
    assert recorded["test_attempt_count"] == 0

    validate_error(
        client.certify_link(link["id"], CERTIFIER_HEADERS), ERR_LINK_NOT_TESTED, 409
    )

    unchanged = fx.read_link(client, link["id"])
    assert unchanged["install_state"] == InstallState.TERMINATED
    assert unchanged["record_state"] == RecordState.RECORDED
    assert unchanged["certifier_user_id"] is None

    still = fx.read_project(client, project["id"])
    assert still["certified_link_count"] == 0
    assert still["warranty_status"] == WarrantyStatus.NOT_ELIGIBLE


def test_withdrawing_an_already_withdrawn_route_is_refused_and_credits_no_area(
    client: ApiClient,
) -> None:
    """A withdrawal is the compensation of a routing, and it happens exactly once.

    The tray gave its area back on the first withdrawal; a second withdrawal is not a
    declared edge out of WITHDRAWN, so it is refused and the segment's fill ledger,
    occupancy count and revision counter all stand still.

    Design: Corner/state_machines/withdraw_an_already_withdrawn_route_returns_invalid_route_state
    """
    project = _riverside_project(client)
    room = _riverside_room(client, project["id"])
    cable = _horizontal_cable(client)
    segment = _tray_segment(client, project["id"])
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
    route = fx.route_link(client, link["id"], segment["id"])
    fx.withdraw_route(client, route["id"], segment["id"])
    version_after_withdrawal = fx.segment_version(client, segment["id"])

    validate_error(
        client.withdraw_link_route(
            route["id"], withdraw_payload(version_after_withdrawal), DESIGNER_HEADERS
        ),
        ERR_INVALID_ROUTE_STATE,
        409,
    )

    unchanged = validate_success(
        client.get_link_route(route["id"], DESIGNER_HEADERS), 200
    )
    assert unchanged["route_state"] == RouteState.WITHDRAWN
    assert_decimal_equals(unchanged["consumed_area_sq_mm"], 49.02)

    tray = fx.read_segment(client, segment["id"])
    assert_decimal_equals(tray["fill_area_used_sq_mm"], 0.00)
    assert tray["occupying_route_count"] == 0
    assert tray["version"] == version_after_withdrawal


def test_terminating_a_link_that_was_never_pulled_reports_the_state_refusal(
    client: ApiClient,
) -> None:
    """Termination is only declared from a pulled or a failed link.

    The cable here is designed and has a path reserved for it but has never been
    pulled, and its room has no bonding measurement on file either. The crew is
    turned away on the link's own state rather than on the room's grounding, and no
    installer identity is recorded against the link.

    Design: Corner/state_machines/terminate_a_designed_link_returns_invalid_link_state
    """
    project = _riverside_project(client)
    room = _riverside_room(client, project["id"])
    cable = _horizontal_cable(client)
    segment = _tray_segment(client, project["id"])
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
    fx.route_link(client, link["id"], segment["id"])
    assert fx.read_room(client, room["id"])["grounding_status"] == (
        GroundingStatus.UNVERIFIED
    )

    validate_error(
        client.terminate_link(link["id"], INSTALLER_HEADERS),
        ERR_INVALID_LINK_STATE,
        409,
    )

    unchanged = fx.read_link(client, link["id"])
    assert unchanged["install_state"] == InstallState.DESIGNED
    assert unchanged["installer_user_id"] is None


def test_a_new_warranty_registration_opens_in_draft_with_nothing_pinned(
    client: ApiClient,
) -> None:
    """Opening a registration files an intention, not evidence.

    The job has no links at all, so nothing about the extended programme's coverage,
    the manufacturer's number or the certified population can be known yet, and every
    one of those fields is empty on the fresh record.

    Design: Corner/state_machines/new_warranty_registration_starts_in_draft_with_no_pinned_version
    """
    project = _riverside_project(client)

    created = validate_success(
        client.create_warranty_registration(
            warranty_registration_payload(
                project["id"], manufacturer_program=ManufacturerProgram.EXTENDED_25Y
            ),
            PM_HEADERS,
        ),
        201,
    )
    assert created["registration_state"] == RegistrationState.DRAFT
    assert created["pinned_project_version"] is None
    assert created["coverage_years"] is None
    assert created["registration_number"] is None
    assert created["rejection_reason"] is None
    assert created["submitted_certified_link_count"] is None
    assert created["version"] == 1

    unchanged = fx.read_project(client, project["id"])
    assert unchanged["warranty_status"] == WarrantyStatus.NOT_ELIGIBLE


def test_submitting_a_draft_registration_reports_the_state_refusal_first(
    client: ApiClient,
) -> None:
    """A registration is promoted to READY by the work, never by a submission attempt.

    The project has no links, so it is neither eligible nor promotable, and the
    supplied project revision is perfectly current. The refusal names the
    registration's own state rather than the eligibility shortfall, and the record
    stays at its opening revision.

    Design: Corner/state_machines/submit_a_draft_registration_returns_invalid_warranty_state
    """
    project = _riverside_project(client)
    registration = fx.create_registration(
        client, project["id"], manufacturer_program=ManufacturerProgram.STANDARD_15Y
    )

    validate_error(
        client.submit_warranty_registration(
            registration["id"],
            warranty_submit_payload(project["version"]),
            PM_HEADERS,
        ),
        ERR_INVALID_WARRANTY_STATE,
        409,
    )

    unchanged = fx.read_registration(client, registration["id"])
    assert unchanged["registration_state"] == RegistrationState.DRAFT
    assert unchanged["version"] == 1


def test_a_condemned_segment_takes_neither_a_second_condemnation_nor_a_new_route(
    client: ApiClient,
) -> None:
    """Once a tray is condemned the drawing is closed against it for good.

    Neither a second inspection finding nor a designer looking for somewhere to put a
    cable can move the segment, the original finding stands unedited, and the segment
    carries no routings at all.

    Design: Corner/state_machines/condemned_segment_refuses_a_new_route_and_a_second_condemn
    """
    project = _riverside_project(client)
    room = _riverside_room(client, project["id"])
    cable = _horizontal_cable(client)
    segment = _tray_segment(client, project["id"])
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
    fx.condemn_segment(
        client, segment["id"], condemned_reason="Tray removed during mechanical rework"
    )
    version_after_condemnation = fx.segment_version(client, segment["id"])

    validate_error(
        client.condemn_pathway_segment(
            segment["id"], condemn_payload(condemned_reason="Second attempt"), PM_HEADERS
        ),
        ERR_SEGMENT_CONDEMNED,
        409,
    )
    validate_error(
        client.create_link_route(
            link_route_payload(
                link["id"], segment["id"], version_after_condemnation, sequence_index=1
            ),
            DESIGNER_HEADERS,
        ),
        ERR_SEGMENT_CONDEMNED,
        409,
    )

    unchanged = fx.read_segment(client, segment["id"])
    assert unchanged["pathway_state"] == PathwayState.CONDEMNED
    assert unchanged["condemned_reason"] == "Tray removed during mechanical rework"
    assert unchanged["occupying_route_count"] == 0
    assert unchanged["version"] == version_after_condemnation

    _, meta = validate_paginated(
        client.list_link_routes(
            DESIGNER_HEADERS, params={"pathway_segment_id": segment["id"]}
        )
    )
    assert meta["total_count"] == 0


def test_confirming_an_already_confirmed_milestone_keeps_the_first_committed_date(
    client: ApiClient,
) -> None:
    """The other trade commits to a date once, and a later date does not overwrite it.

    A second confirmation is not a declared edge out of CONFIRMED, so the ceiling
    milestone keeps the date it was originally committed to and the refused call
    leaves the coordination's revision counter where the first confirmation left it.

    Design: Corner/state_machines/confirming_an_already_confirmed_coordination_returns_invalid_coordination_state
    """
    project = _riverside_project(client)
    coordination = fx.create_coordination(
        client, project["id"], trade=Trade.CEILING, milestone=Milestone.PATHWAY_ROUGH_IN
    )
    confirmed = fx.confirm_coordination(
        client, coordination["id"], confirmed_date="2026-08-05"
    )
    assert confirmed["coordination_state"] == CoordinationState.CONFIRMED

    validate_error(
        client.confirm_trade_coordination(
            coordination["id"],
            confirm_payload(confirmed_date="2026-08-09"),
            PM_HEADERS,
        ),
        ERR_INVALID_COORDINATION_STATE,
        409,
    )

    unchanged = validate_success(
        client.get_trade_coordination(coordination["id"], PM_HEADERS), 200
    )
    assert unchanged["coordination_state"] == CoordinationState.CONFIRMED
    assert unchanged["confirmed_date"] == "2026-08-05"
    assert unchanged["version"] == 2


def test_releasing_an_already_released_placement_credits_the_ledgers_only_once(
    client: ApiClient,
) -> None:
    """Equipment comes off the elevation once, and the ledgers are credited once.

    The rack units and the volt-amperes were given back on the first release; the
    second release is refused on the placement's own state, the reason recorded when
    the switch actually came out is preserved, and neither the rack's occupancy nor
    the room's power load can be credited a second time.

    Design: Corner/state_machines/releasing_an_already_released_assignment_returns_invalid_assignment_state
    """
    project = _riverside_project(client)
    room = _riverside_room(client, project["id"])
    rack = fx.create_rack(client, room["id"], rack_code="A", total_ru=42)
    placement = fx.place_equipment(
        client,
        rack["id"],
        equipment_label="Core switch",
        start_ru=1,
        end_ru=4,
        power_va=1200,
    )
    fx.release_equipment(
        client, placement["id"], rack["id"], released_reason="Switch relocated"
    )
    version_after_release = fx.rack_version(client, rack["id"])

    validate_error(
        client.release_rack_unit_assignment(
            placement["id"],
            release_payload(version_after_release, released_reason="Second attempt"),
            DESIGNER_HEADERS,
        ),
        ERR_INVALID_ASSIGNMENT_STATE,
        409,
    )

    unchanged = validate_success(
        client.get_rack_unit_assignment(placement["id"], DESIGNER_HEADERS), 200
    )
    assert unchanged["assignment_state"] == AssignmentState.RELEASED
    assert unchanged["released_reason"] == "Switch relocated"

    elevation = fx.read_rack(client, rack["id"])
    assert elevation["occupied_ru"] == 0
    assert elevation["available_ru"] == 42
    assert elevation["power_draw_va"] == 0
    assert elevation["version"] == version_after_release
    assert_rack_ru_identity(elevation)

    space = fx.read_room(client, room["id"])
    assert space["power_load_va"] == 0
    assert space["power_headroom_va"] == 3000
    assert_room_power_identity(space)


def test_energizing_a_room_twice_is_refused_on_the_second_attempt(
    client: ApiClient,
) -> None:
    """Switching on the rack power distribution is a one-way door.

    With the bonding proved compliant and the electrical trade's energize milestone
    released, the first attempt takes the room to its terminal state; the second is
    refused, and the room carries no load because nothing has been placed on a rack.

    Design: Corner/state_machines/energize_an_energized_room_returns_invalid_room_state
    """
    project = _riverside_project(client)
    room = _riverside_room(client, project["id"])
    fx.verify_grounding(client, room["id"], ground_resistance_milliohms=5000)
    fx.coordination_in_state(
        client,
        project["id"],
        CoordinationState.RELEASED,
        trade=Trade.ELECTRICAL,
        milestone=Milestone.POWER_ENERGIZE,
    )

    energized = validate_success(client.energize_room(room["id"], PM_HEADERS), 200)
    assert energized["room_state"] == RoomState.ENERGIZED
    assert energized["grounding_status"] == GroundingStatus.COMPLIANT

    validate_error(
        client.energize_room(room["id"], PM_HEADERS), ERR_INVALID_ROOM_STATE, 409
    )

    unchanged = fx.read_room(client, room["id"])
    assert unchanged["room_state"] == RoomState.ENERGIZED
    assert unchanged["power_load_va"] == 0
    assert unchanged["power_headroom_va"] == 3000
    assert_room_power_identity(unchanged)


def test_blocking_the_ceiling_milestone_reblocks_the_pulls_that_have_not_happened(
    client: ApiClient,
) -> None:
    """A blocked ceiling grid stops the next pull without undoing the last one.

    The cable already in the tray is untouched by the block, while the cable still
    waiting is refused on the trade sequence. Clearing the block returns the milestone
    to a bare request rather than to a confirmation, so the pull stays shut until the
    ceiling trade commits to a fresh date.

    Design: Corner/state_machines/blocking_the_ceiling_milestone_reblocks_further_pulls
    """
    project = _riverside_project(client)
    room = _riverside_room(client, project["id"])
    cable = _horizontal_cable(client)
    segment = _tray_segment(client, project["id"])
    coordination = fx.create_coordination(
        client, project["id"], trade=Trade.CEILING, milestone=Milestone.PATHWAY_ROUGH_IN
    )
    fx.confirm_coordination(client, coordination["id"], confirmed_date="2026-08-05")

    first = fx.create_link(
        client,
        project["id"],
        room["id"],
        cable["id"],
        identifier="TR01-A01",
        horizontal_length_m=40.00,
        consolidation_point_stub_m=0,
        patch_cord_allowance_m=2.00,
    )
    fx.route_link(client, first["id"], segment["id"])
    fx.pull_link(client, first["id"])

    second = fx.create_link(
        client,
        project["id"],
        room["id"],
        cable["id"],
        identifier="TR01-A02",
        horizontal_length_m=41.00,
        consolidation_point_stub_m=0,
        patch_cord_allowance_m=2.00,
    )
    fx.route_link(client, second["id"], segment["id"])

    blocked = fx.block_coordination(
        client,
        coordination["id"],
        block_reason="Ceiling grid closed ahead of schedule",
    )
    assert blocked["coordination_state"] == CoordinationState.BLOCKED
    assert blocked["block_reason"] == "Ceiling grid closed ahead of schedule"

    validate_error(
        client.pull_link(second["id"], INSTALLER_HEADERS),
        ERR_TRADE_NOT_COORDINATED,
        409,
    )
    assert fx.read_link(client, first["id"])["install_state"] == InstallState.PULLED

    unblocked = fx.unblock_coordination(client, coordination["id"])
    assert unblocked["coordination_state"] == CoordinationState.REQUESTED
    assert unblocked["block_reason"] is None
    assert unblocked["confirmed_date"] is None

    validate_error(
        client.pull_link(second["id"], INSTALLER_HEADERS),
        ERR_TRADE_NOT_COORDINATED,
        409,
    )

    reconfirmed = fx.confirm_coordination(
        client, coordination["id"], confirmed_date="2026-08-12"
    )
    assert reconfirmed["coordination_state"] == CoordinationState.CONFIRMED
    assert reconfirmed["confirmed_date"] == "2026-08-12"

    pulled = validate_success(
        client.pull_link(second["id"], INSTALLER_HEADERS), 200
    )
    assert pulled["install_state"] == InstallState.PULLED
    assert fx.read_link(client, first["id"])["install_state"] == InstallState.PULLED
