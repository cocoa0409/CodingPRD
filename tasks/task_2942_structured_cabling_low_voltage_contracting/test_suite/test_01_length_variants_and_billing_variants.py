"""Two-variant computations that diverge on the same row.

The same physical cable is graded twice — once as a permanent link, once as a
channel — and the same ticket is priced twice, once from the estimate and once
from the actual hours.
"""
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from prd_bench_local_runner.testing import validate_success

from test_helpers import fixtures as fx
from test_helpers.api_client import ApiClient
from test_helpers.assertions import assert_cents, assert_decimal_equals
from test_helpers.factories import test_result_payload as build_test_result
from test_helpers.test_users import TESTER_HEADERS
from test_helpers.types import (
    Application,
    CoordinationState,
    FailureReason,
    IdentifierScheme,
    InstallState,
    TestOutcome,
    TestStandard,
    TicketState,
)


def _grading_scenario(client: ApiClient) -> dict:
    """A terminated CAT6A link measuring 84.00 m horizontal with 14.00 m of cords."""
    project = fx.create_project(
        client,
        name="Riverside Tower Cabling",
        site_code="RVT1",
        plenum_ceiling=True,
        identifier_scheme=IdentifierScheme.TIA_606_CLASS_1,
        warranty_program="STANDARD_15Y",
        mac_budget_cents=500000,
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
        outer_diameter_mm=7.9,
        max_channel_length_m=100.0,
        cost_per_meter_cents=150,
        applications=[Application.DATA_HORIZONTAL, Application.WAP],
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
    fx.coordination_in_state(client, project["id"], CoordinationState.CONFIRMED)
    link_response = client.create_link(
        {
            "project_id": project["id"],
            "telecom_room_id": room["id"],
            "cable_type_id": cable["id"],
            "identifier": "TR01-A01",
            "application": Application.DATA_HORIZONTAL,
            "horizontal_length_m": 84.00,
            "consolidation_point_stub_m": 0,
            "patch_cord_allowance_m": 14.00,
        },
        fx.DESIGNER_HEADERS,
    )
    link = validate_success(link_response, 201)
    fx.route_link(client, link["id"], segment["id"])
    fx.pull_link(client, link["id"])
    fx.terminate_link(client, link["id"])
    return {"project": project, "room": room, "cable": cable, "link": link}


def test_one_link_stores_both_length_variants_from_the_same_measurements(
    client: ApiClient,
) -> None:
    """The permanent-link figure excludes the cords the channel figure derates.

    Horizontal 84.00 metres with no consolidation-point stub gives a
    permanent_link_length_m of 84.00, and adding 14.00 metres of cord allowance
    multiplied by the 1.2 derate factor gives a channel_length_m of 100.80. Both
    figures sit on the same row.

    Design: Difficulty/dual_variant_calc/permanent_link_versus_channel_length_grading_on_one_link
    """
    scenario = _grading_scenario(client)
    link = scenario["link"]

    assert_decimal_equals(link["permanent_link_length_m"], 84.00)
    assert_decimal_equals(link["channel_length_m"], 100.80)


def test_the_permanent_link_variant_passes_while_the_channel_variant_fails(
    client: ApiClient,
) -> None:
    """The same run passes one standard and fails the other on length alone.

    A PERMANENT_LINK test grades 84.00 metres against the 90.00-metre limit and
    reaches a clean PASS on an insertion-loss budget of 16.36 decibels, while a
    CHANNEL test grades 100.80 metres against the 100.00-metre limit and fails at
    the first verdict test with LENGTH_LIMIT on a budget of 19.55 decibels. The
    later FAIL is what the link's latest outcome reports.

    Design: Difficulty/dual_variant_calc/permanent_link_versus_channel_length_grading_on_one_link
    """
    scenario = _grading_scenario(client)
    link_id = scenario["link"]["id"]

    permanent = validate_success(
        client.create_test_result(
            build_test_result(
                link_id,
                test_standard=TestStandard.PERMANENT_LINK,
                tester_model="DSX-8000",
                insertion_loss_db=15.0,
                next_margin_db=3.2,
                return_loss_margin_db=2.1,
                length_measured_m=84.00,
            ),
            TESTER_HEADERS,
        ),
        201,
    )
    assert permanent["outcome"] == TestOutcome.PASS
    assert permanent["failure_reason"] is None
    assert_decimal_equals(permanent["insertion_loss_budget_db"], 16.36)

    channel = validate_success(
        client.create_test_result(
            build_test_result(
                link_id,
                test_standard=TestStandard.CHANNEL,
                tester_model="DSX-8000",
                insertion_loss_db=15.0,
                next_margin_db=3.2,
                return_loss_margin_db=2.1,
                length_measured_m=100.80,
            ),
            TESTER_HEADERS,
        ),
        201,
    )
    assert channel["outcome"] == TestOutcome.FAIL
    assert channel["failure_reason"] == FailureReason.LENGTH_LIMIT
    assert_decimal_equals(channel["insertion_loss_budget_db"], 19.55)

    link = fx.read_link(client, link_id)
    assert link["install_state"] == InstallState.TESTED_FAIL
    assert link["test_attempt_count"] == 2
    assert link["latest_test_outcome"] == TestOutcome.FAIL

    project = fx.read_project(client, scenario["project"]["id"])
    assert project["failed_link_count"] == 1
    assert_decimal_equals(project["completeness_pct_provisional"], 0.00)


def _occupied_project_with_ticket(client: ApiClient) -> dict:
    """An occupied project carrying one submitted 6.0-hour expedited MOVE ticket."""
    project = fx.create_project(
        client,
        name="Riverside Tower Cabling",
        site_code="RVT1",
        plenum_ceiling=True,
        identifier_scheme=IdentifierScheme.TIA_606_CLASS_1,
        warranty_program="STANDARD_15Y",
        mac_budget_cents=500000,
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
        applications=[Application.DATA_HORIZONTAL, Application.WAP],
    )
    segment = fx.create_segment(
        client, project["id"], segment_code="PS-A", usable_area_sq_mm=20000.0, length_m=40.0
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
    fx.release_coordination(client, coordination["id"])
    fx.declare_occupancy(client, project["id"])
    ticket = fx.create_ticket(
        client,
        project["id"],
        link["id"],
        room["id"],
        ticket_type="MOVE",
        requested_window_start="2026-08-10T09:00:00Z",
        requested_window_end="2026-08-10T12:00:00Z",
        labor_hours_estimate=6.0,
        expedite_requested=True,
    )
    return {"project": project, "room": room, "link": link, "ticket": ticket}


def test_the_estimate_run_and_the_final_run_bill_the_same_ticket_differently(
    client: ApiClient,
) -> None:
    """Six estimated hours and four actual hours land in different discount tiers.

    Scheduling runs the billing sequence over labor_hours_estimate 6.0: a subtotal
    of 57600 cents earns the 5 percent tier, and the expedite fee is taken on the
    post-discount base, billing 62928 cents. Completion re-runs the same sequence
    over actual_labor_hours 4.0: a subtotal of 38400 cents sits below the first
    threshold, earns nothing, and bills 44160 cents. Both figures are stamped on
    the one row.

    Design: Difficulty/dual_variant_calc/mac_billing_estimate_versus_final_hours
    """
    scenario = _occupied_project_with_ticket(client)
    ticket_id = scenario["ticket"]["id"]

    scheduled = fx.schedule_ticket(
        client,
        ticket_id,
        scheduled_window_start="2026-08-10T09:00:00Z",
        scheduled_window_end="2026-08-10T12:00:00Z",
    )
    assert_cents(scheduled["estimated_billed_cents"], 62928)
    assert scheduled["ticket_state"] == TicketState.SCHEDULED

    fx.set_clock(client, "2026-08-10T09:30:00Z")
    fx.start_ticket(client, ticket_id)
    completed = fx.complete_ticket(client, ticket_id, actual_labor_hours=4.0)
    assert_cents(completed["final_billed_cents"], 44160)
    assert_decimal_equals(completed["actual_labor_hours"], 4.0, 1)
    assert completed["ticket_state"] == TicketState.COMPLETED

    ticket = fx.read_ticket(client, ticket_id)
    assert_cents(ticket["estimated_billed_cents"], 62928)
    assert_cents(ticket["final_billed_cents"], 44160)


def test_the_project_ledger_moves_from_the_estimate_to_the_final_figure(
    client: ApiClient,
) -> None:
    """The reconciled ledger reads the estimate while scheduled and the final once completed.

    A SCHEDULED or IN_PROGRESS ticket contributes its estimate to
    consumed_mac_cents; a COMPLETED one contributes its final figure instead, so the
    ledger falls from 62928 to 44160 cents when the crew finishes early.

    Design: Difficulty/dual_variant_calc/mac_billing_estimate_versus_final_hours
    """
    scenario = _occupied_project_with_ticket(client)
    project_id = scenario["project"]["id"]
    ticket_id = scenario["ticket"]["id"]

    assert_cents(fx.read_project(client, project_id)["consumed_mac_cents"], 0)

    fx.schedule_ticket(
        client,
        ticket_id,
        scheduled_window_start="2026-08-10T09:00:00Z",
        scheduled_window_end="2026-08-10T12:00:00Z",
    )
    assert_cents(fx.read_project(client, project_id)["consumed_mac_cents"], 62928)

    fx.set_clock(client, "2026-08-10T09:30:00Z")
    fx.start_ticket(client, ticket_id)
    assert_cents(fx.read_project(client, project_id)["consumed_mac_cents"], 62928)

    fx.complete_ticket(client, ticket_id, actual_labor_hours=4.0)
    assert_cents(fx.read_project(client, project_id)["consumed_mac_cents"], 44160)
