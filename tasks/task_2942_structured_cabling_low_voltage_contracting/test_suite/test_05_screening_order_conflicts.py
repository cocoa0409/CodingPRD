"""Single calls that violate two rules at once, where the screening order decides
which identifier is reported.
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from prd_bench_local_runner.testing import build_user_headers, validate_error

from test_helpers import fixtures as fx
from test_helpers.api_client import ApiClient
from test_helpers.api_errors import (
    ERR_LINK_NOT_RECORDED,
    ERR_MAC_BUDGET_EXCEEDED,
    ERR_PATHWAY_FILL_EXCEEDED,
    ERR_PLENUM_RATING_REQUIRED,
    ERR_ROOM_WINDOW_CONFLICT,
    ERR_SEGREGATION_OF_DUTIES,
)
from test_helpers.assertions import assert_cents, assert_decimal_equals
from test_helpers.factories import link_route_payload
from test_helpers.test_users import DESIGNER_HEADERS, INSTALLER_ID, PM_HEADERS
from test_helpers.types import (
    Application,
    CableCategory,
    IdentifierScheme,
    InstallState,
    JacketRating,
    PathwayType,
    RecordState,
    TicketState,
    TicketType,
    UserRole,
)


def _labelled_but_unrecorded_link(client: ApiClient) -> dict:
    """A TESTED_PASS link whose administration dimension has only reached LABELED."""
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
    fx.terminate_link(client, link["id"])
    fx.label_link(client, link["id"], "TR01-A01")
    fx.file_test(client, link["id"], insertion_loss_db=15.0, length_measured_m=85.63)
    return {"project_id": project["id"], "link_id": link["id"]}


def test_certification_reports_the_missing_record_before_the_duty_conflict(
    client: ApiClient,
) -> None:
    """The record-state rule is screened before segregation of duties.

    One call breaks both: the link is TESTED_PASS but only LABELED, and the acting
    identity is the same person who terminated it. The administration rule is
    screened first, so the missing as-built record is what is reported and the
    duty conflict never surfaces.

    Design: Difficulty/priority_pair_validation_conflict/link_not_recorded_rejects_before_segregation_of_duties
    """
    scenario = _labelled_but_unrecorded_link(client)
    acting = build_user_headers(INSTALLER_ID, UserRole.CERTIFIER)

    response = client.certify_link(scenario["link_id"], acting)
    error = validate_error(response, ERR_LINK_NOT_RECORDED, 409)
    assert error["error_id"] != ERR_SEGREGATION_OF_DUTIES


def test_the_refused_certification_leaves_both_link_dimensions_untouched(
    client: ApiClient,
) -> None:
    """A refusal writes nothing: the link keeps its states and has no certifier.

    Design: Difficulty/priority_pair_validation_conflict/link_not_recorded_rejects_before_segregation_of_duties
    """
    scenario = _labelled_but_unrecorded_link(client)
    acting = build_user_headers(INSTALLER_ID, UserRole.CERTIFIER)
    client.certify_link(scenario["link_id"], acting)

    link = fx.read_link(client, scenario["link_id"])
    assert link["install_state"] == InstallState.TESTED_PASS
    assert link["record_state"] == RecordState.LABELED
    assert link["certifier_user_id"] is None


def _plenum_conduit_scenario(client: ApiClient) -> dict:
    """A riser-jacketed 95.03 sq mm cable and a plenum conduit allowing only 53.00 sq mm."""
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
        category=CableCategory.CAT6,
        jacket_rating=JacketRating.CMR,
        outer_diameter_mm=11.0,
        max_channel_length_m=100.0,
        shielded=False,
        cost_per_meter_cents=120,
        applications=[Application.DATA_HORIZONTAL],
    )
    segment = fx.create_segment(
        client,
        project["id"],
        segment_code="PS-P",
        pathway_type=PathwayType.EMT_CONDUIT,
        usable_area_sq_mm=100.0,
        length_m=12.0,
        bend_count=0,
        in_plenum_space=True,
        shared_with_power=False,
        power_separation_mm=0,
    )
    link = fx.create_link(
        client,
        project["id"],
        room["id"],
        cable["id"],
        identifier="TR01-B01",
        horizontal_length_m=40.00,
        consolidation_point_stub_m=0,
        patch_cord_allowance_m=2.00,
    )
    return {"segment": segment, "link_id": link["id"]}


def test_routing_reports_the_plenum_jacket_before_the_fill_overflow(
    client: ApiClient,
) -> None:
    """The fire-safety rule is screened before the fill arithmetic.

    A riser-jacketed cable is routed into a conduit that runs through the plenum
    cavity, and the same cable also overflows the conduit's 53.00 sq mm allowance.
    Both rejections carry the same status, so only the identifier distinguishes
    them: the jacket rating answers first.

    Design: Difficulty/priority_pair_validation_conflict/plenum_rating_rejects_before_pathway_fill_overflow
    """
    scenario = _plenum_conduit_scenario(client)
    response = client.create_link_route(
        link_route_payload(
            scenario["link_id"], scenario["segment"]["id"], scenario["segment"]["version"]
        ),
        DESIGNER_HEADERS,
    )
    error = validate_error(response, ERR_PLENUM_RATING_REQUIRED, 422)
    assert error["error_id"] != ERR_PATHWAY_FILL_EXCEEDED


def test_the_refused_routing_leaves_the_segment_ledger_and_revision_untouched(
    client: ApiClient,
) -> None:
    """A refused routing consumes no area and does not bump the segment's revision.

    Design: Difficulty/priority_pair_validation_conflict/plenum_rating_rejects_before_pathway_fill_overflow
    """
    scenario = _plenum_conduit_scenario(client)
    original_version = scenario["segment"]["version"]
    client.create_link_route(
        link_route_payload(
            scenario["link_id"], scenario["segment"]["id"], original_version
        ),
        DESIGNER_HEADERS,
    )

    segment = fx.read_segment(client, scenario["segment"]["id"])
    assert segment["occupying_route_count"] == 0
    assert_decimal_equals(segment["fill_area_used_sq_mm"], 0.00)
    assert segment["version"] == original_version


def _crowded_room_and_thin_budget(client: ApiClient) -> dict:
    """An occupied project with a 100000-cent budget and two crews already booked.

    Both booked tickets bill four hours at the plain rate, so 76800 cents of the
    budget is already committed and a third four-hour ticket would overrun it.
    """
    scenario = fx.setup_base_scenario(client, project={"mac_budget_cents": 100000})
    occupied = fx.setup_occupied_project(client, scenario)
    project_id = occupied["project_id"]
    link_id = occupied["link_id"]
    room_id = occupied["room_id"]

    first = fx.create_ticket(
        client,
        project_id,
        link_id,
        room_id,
        ticket_type=TicketType.MOVE,
        requested_window_start="2026-08-14T09:00:00Z",
        requested_window_end="2026-08-14T13:00:00Z",
        labor_hours_estimate=4.0,
        expedite_requested=False,
    )
    second = fx.create_ticket(
        client,
        project_id,
        link_id,
        room_id,
        ticket_type=TicketType.ADD,
        requested_window_start="2026-08-14T09:00:00Z",
        requested_window_end="2026-08-14T13:00:00Z",
        labor_hours_estimate=4.0,
        expedite_requested=False,
    )
    for ticket in (first, second):
        fx.schedule_ticket(
            client,
            ticket["id"],
            scheduled_window_start="2026-08-14T09:00:00Z",
            scheduled_window_end="2026-08-14T13:00:00Z",
        )

    third = fx.create_ticket(
        client,
        project_id,
        link_id,
        room_id,
        ticket_type=TicketType.CHANGE,
        requested_window_start="2026-08-14T10:00:00Z",
        requested_window_end="2026-08-14T14:00:00Z",
        labor_hours_estimate=4.0,
        expedite_requested=False,
    )
    return {"project_id": project_id, "third_id": third["id"]}


def test_scheduling_reports_the_room_conflict_before_the_budget_overrun(
    client: ApiClient,
) -> None:
    """The room capacity check is screened before the money check.

    The third booking would be both the third crew in one room and the call that
    breaks a thin budget. The capacity check runs first, so the crowded room is
    what is reported and the budget is never consulted.

    Design: Difficulty/priority_pair_validation_conflict/room_window_conflict_rejects_before_mac_budget_exhaustion
    """
    scenario = _crowded_room_and_thin_budget(client)
    response = client.schedule_mac_ticket(
        scenario["third_id"],
        {
            "scheduled_window_start": "2026-08-14T10:00:00Z",
            "scheduled_window_end": "2026-08-14T14:00:00Z",
        },
        PM_HEADERS,
    )
    error = validate_error(response, ERR_ROOM_WINDOW_CONFLICT, 409)
    assert error["error_id"] != ERR_MAC_BUDGET_EXCEEDED


def test_the_refused_schedule_leaves_the_ticket_and_the_budget_ledger_untouched(
    client: ApiClient,
) -> None:
    """The refused ticket keeps its submitted state and the ledger keeps its two bookings.

    Design: Difficulty/priority_pair_validation_conflict/room_window_conflict_rejects_before_mac_budget_exhaustion
    """
    scenario = _crowded_room_and_thin_budget(client)
    client.schedule_mac_ticket(
        scenario["third_id"],
        {
            "scheduled_window_start": "2026-08-14T10:00:00Z",
            "scheduled_window_end": "2026-08-14T14:00:00Z",
        },
        PM_HEADERS,
    )

    ticket = fx.read_ticket(client, scenario["third_id"])
    assert ticket["ticket_state"] == TicketState.SUBMITTED
    assert ticket["estimated_billed_cents"] is None
    assert ticket["scheduled_window_start"] is None
    assert ticket["scheduled_window_end"] is None

    project = fx.read_project(client, scenario["project_id"])
    assert_cents(project["consumed_mac_cents"], 76800)
