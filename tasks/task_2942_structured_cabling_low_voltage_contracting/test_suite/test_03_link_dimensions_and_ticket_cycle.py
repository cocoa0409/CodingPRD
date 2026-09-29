"""State machines that are not a single line: two parallel dimensions on one link,
and a genuine cycle on a moves-adds-changes ticket.
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from test_helpers import fixtures as fx
from test_helpers.api_client import ApiClient
from test_helpers.assertions import assert_cents, assert_instant_equals
from test_helpers.test_users import CERTIFIER_ID, INSTALLER_ID
from test_helpers.types import (
    Application,
    IdentifierScheme,
    InstallState,
    RecordState,
    TestOutcome,
    TestStandard,
    TicketState,
)


def _terminated_link_scenario(client: ApiClient) -> dict:
    """A link terminated by the installer, whose administration dimension is untouched."""
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
    terminated = fx.terminate_link(client, link["id"])
    return {
        "project": project,
        "room": room,
        "coordination": coordination,
        "link": terminated,
        "link_id": link["id"],
    }


def test_the_record_dimension_walks_forward_while_the_install_dimension_holds(
    client: ApiClient,
) -> None:
    """Labelling and filing move record_state without disturbing install_state.

    A terminated link starts UNLABELED. Applying the label moves record_state to
    LABELED and stores applied_identifier; filing the as-built sheet moves it to
    RECORDED. Through both steps install_state stays TERMINATED, because the two
    dimensions advance on separate tracks.

    Design: Difficulty/non_linear_state_machine/link_install_and_record_dimensions_advance_independently
    """
    scenario = _terminated_link_scenario(client)
    link_id = scenario["link_id"]
    assert scenario["link"]["install_state"] == InstallState.TERMINATED
    assert scenario["link"]["record_state"] == RecordState.UNLABELED

    labelled = fx.label_link(client, link_id, "TR01-A01")
    assert labelled["record_state"] == RecordState.LABELED
    assert labelled["applied_identifier"] == "TR01-A01"
    assert labelled["install_state"] == InstallState.TERMINATED

    recorded = fx.record_link(client, link_id, drawing_sheet_ref="E-501")
    assert recorded["record_state"] == RecordState.RECORDED
    assert recorded["drawing_sheet_ref"] == "E-501"
    assert recorded["install_state"] == InstallState.TERMINATED


def test_the_install_dimension_walks_forward_while_the_record_dimension_holds(
    client: ApiClient,
) -> None:
    """Testing and certifying move install_state while record_state stays RECORDED.

    Once the administration dimension has reached RECORDED, a clean test moves
    install_state to TESTED_PASS and certification moves it to CERTIFIED, stamping
    certifier_user_id. record_state never moves off RECORDED, and the installer
    recorded at termination survives untouched.

    Design: Difficulty/non_linear_state_machine/link_install_and_record_dimensions_advance_independently
    """
    scenario = _terminated_link_scenario(client)
    link_id = scenario["link_id"]
    fx.label_link(client, link_id, "TR01-A01")
    fx.record_link(client, link_id, drawing_sheet_ref="E-501")

    result = fx.file_test(
        client,
        link_id,
        test_standard=TestStandard.PERMANENT_LINK,
        tester_model="DSX-8000",
        insertion_loss_db=15.0,
        next_margin_db=3.2,
        return_loss_margin_db=2.1,
        length_measured_m=85.63,
    )
    assert result["outcome"] == TestOutcome.PASS
    tested = fx.read_link(client, link_id)
    assert tested["install_state"] == InstallState.TESTED_PASS
    assert tested["record_state"] == RecordState.RECORDED

    certified = fx.certify_link(client, link_id)
    assert certified["install_state"] == InstallState.CERTIFIED
    assert certified["record_state"] == RecordState.RECORDED
    assert certified["certifier_user_id"] == CERTIFIER_ID

    link = fx.read_link(client, link_id)
    assert link["installer_user_id"] == INSTALLER_ID
    assert link["test_attempt_count"] == 1


def _occupied_project_with_six_hour_ticket(client: ApiClient) -> dict:
    """An occupied project carrying a submitted 6.0-hour ticket with no expedite."""
    scenario = _terminated_link_scenario(client)
    link_id = scenario["link_id"]
    fx.label_link(client, link_id, "TR01-A01")
    fx.record_link(client, link_id, drawing_sheet_ref="E-501")
    fx.file_test(client, link_id, insertion_loss_db=15.0, length_measured_m=85.63)
    fx.certify_link(client, link_id)
    fx.release_coordination(client, scenario["coordination"]["id"])
    fx.declare_occupancy(client, scenario["project"]["id"])
    ticket = fx.create_ticket(
        client,
        scenario["project"]["id"],
        link_id,
        scenario["room"]["id"],
        ticket_type="MOVE",
        requested_window_start="2026-08-14T09:00:00Z",
        requested_window_end="2026-08-14T15:00:00Z",
        labor_hours_estimate=6.0,
        expedite_requested=False,
    )
    scenario["ticket"] = ticket
    scenario["ticket_id"] = ticket["id"]
    return scenario


def test_rework_returns_an_in_progress_ticket_to_submitted_and_unwinds_the_ledger(
    client: ApiClient,
) -> None:
    """The cycle closes back onto SUBMITTED, clearing the windows and the commitment.

    Scheduling commits an estimate of 54720 cents and the crew starts inside the
    window. Reworking the ticket sends it back to SUBMITTED, nulls both window
    instants and the estimate, raises rework_count to 1, and reduces the project's
    consumed_mac_cents by exactly the amount scheduling had committed.

    Design: Difficulty/non_linear_state_machine/mac_ticket_rework_cycle_returns_to_submitted
    """
    scenario = _occupied_project_with_six_hour_ticket(client)
    ticket_id = scenario["ticket_id"]
    project_id = scenario["project"]["id"]

    scheduled = fx.schedule_ticket(
        client,
        ticket_id,
        scheduled_window_start="2026-08-14T09:00:00Z",
        scheduled_window_end="2026-08-14T15:00:00Z",
    )
    assert scheduled["ticket_state"] == TicketState.SCHEDULED
    assert_cents(scheduled["estimated_billed_cents"], 54720)
    assert scheduled["rework_count"] == 0

    fx.set_clock(client, "2026-08-14T10:00:00Z")
    started = fx.start_ticket(client, ticket_id)
    assert started["ticket_state"] == TicketState.IN_PROGRESS

    reworked = fx.rework_ticket(client, ticket_id)
    assert reworked["ticket_state"] == TicketState.SUBMITTED
    assert reworked["rework_count"] == 1
    assert reworked["estimated_billed_cents"] is None
    assert reworked["scheduled_window_start"] is None
    assert reworked["scheduled_window_end"] is None

    assert_cents(fx.read_project(client, project_id)["consumed_mac_cents"], 0)


def test_a_reworked_ticket_can_be_scheduled_again_and_recommits_the_estimate(
    client: ApiClient,
) -> None:
    """The loop may be walked again; rework_count records how many times it has been.

    A second schedule on the reworked ticket stamps the new window, re-runs the
    same estimate of 54720 cents from the unchanged labor_hours_estimate, and
    re-commits it to the project ledger while rework_count stays at 1.

    Design: Difficulty/non_linear_state_machine/mac_ticket_rework_cycle_returns_to_submitted
    """
    scenario = _occupied_project_with_six_hour_ticket(client)
    ticket_id = scenario["ticket_id"]
    project_id = scenario["project"]["id"]

    fx.schedule_ticket(
        client,
        ticket_id,
        scheduled_window_start="2026-08-14T09:00:00Z",
        scheduled_window_end="2026-08-14T15:00:00Z",
    )
    fx.set_clock(client, "2026-08-14T10:00:00Z")
    fx.start_ticket(client, ticket_id)
    fx.rework_ticket(client, ticket_id)

    rescheduled = fx.schedule_ticket(
        client,
        ticket_id,
        scheduled_window_start="2026-08-17T09:00:00Z",
        scheduled_window_end="2026-08-17T15:00:00Z",
    )
    assert rescheduled["ticket_state"] == TicketState.SCHEDULED
    assert_cents(rescheduled["estimated_billed_cents"], 54720)
    assert rescheduled["rework_count"] == 1
    assert_instant_equals(
        rescheduled["scheduled_window_start"], "2026-08-17T09:00:00Z"
    )

    assert_cents(fx.read_project(client, project_id)["consumed_mac_cents"], 54720)
