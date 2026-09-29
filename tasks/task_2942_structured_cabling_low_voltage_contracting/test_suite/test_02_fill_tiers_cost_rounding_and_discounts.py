"""Formulas whose inputs interact: the fill tier table, the as-built rounding
order, and the volume tier keyed on the subtotal.
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from prd_bench_local_runner.testing import validate_error, validate_success

from test_helpers import fixtures as fx
from test_helpers.api_client import ApiClient
from test_helpers.api_errors import ERR_PATHWAY_FILL_EXCEEDED
from test_helpers.assertions import (
    assert_cents,
    assert_decimal_equals,
    assert_instant_equals,
)
from test_helpers.factories import link_route_payload
from test_helpers.test_users import DESIGNER_HEADERS
from test_helpers.types import (
    Application,
    CableCategory,
    IdentifierScheme,
    InstallState,
    JacketRating,
    PathwayType,
    RouteState,
    TicketState,
)


def _conduit_scenario(client: ApiClient) -> dict:
    """An EMT conduit of 573.0 sq mm and two designed CAT6 links of 95.03 sq mm each."""
    project = fx.create_project(
        client,
        name="Bluewater Fitout",
        site_code="BLD2",
        plenum_ceiling=False,
        identifier_scheme=IdentifierScheme.TIA_606_CLASS_1,
    )
    room = fx.create_room(
        client,
        project["id"],
        room_code="TR01",
        floor=2,
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
        cost_per_meter_cents=150,
        applications=[Application.DATA_HORIZONTAL],
    )
    segment = fx.create_segment(
        client,
        project["id"],
        segment_code="PS-C",
        pathway_type=PathwayType.EMT_CONDUIT,
        usable_area_sq_mm=573.0,
        length_m=18.0,
        bend_count=0,
        in_plenum_space=False,
        shared_with_power=False,
        power_separation_mm=0,
    )
    first = fx.create_link(
        client,
        project["id"],
        room["id"],
        cable["id"],
        identifier="TR01-A01",
        horizontal_length_m=50.00,
    )
    second = fx.create_link(
        client,
        project["id"],
        room["id"],
        cable["id"],
        identifier="TR01-A02",
        horizontal_length_m=50.00,
    )
    return {
        "project": project,
        "cable": cable,
        "segment": segment,
        "first": first,
        "second": second,
    }


def test_a_single_cable_is_admitted_at_the_fifty_three_percent_allowance(
    client: ApiClient,
) -> None:
    """One 95.03 sq mm cable fits a 573.0 sq mm conduit at the single-cable tier.

    An empty conduit reports the allowance for one more cable than it carries,
    which is the 53 percent single-cable tier. Admitting the cable snapshots
    95.03 sq mm onto the routing, raises fill_area_used_sq_mm to 95.03 and gives a
    fill_ratio of 0.1658 at four decimal places.

    Design: Difficulty/combinatorial_formula/conduit_fill_tier_table_is_non_monotonic_at_the_second_cable
    """
    scenario = _conduit_scenario(client)
    assert scenario["segment"]["allowed_fill_pct"] == 53
    assert_decimal_equals(scenario["cable"]["cross_section_area_sq_mm"], 95.03)

    route = fx.route_link(client, scenario["first"]["id"], scenario["segment"]["id"])
    assert_decimal_equals(route["consumed_area_sq_mm"], 95.03)
    assert route["route_state"] == RouteState.OCCUPYING

    segment = fx.read_segment(client, scenario["segment"]["id"])
    assert segment["occupying_route_count"] == 1
    assert_decimal_equals(segment["fill_area_used_sq_mm"], 95.03)
    assert_decimal_equals(segment["fill_ratio"], 0.1658, 4)


def test_the_second_cable_is_refused_because_the_two_cable_allowance_is_lower(
    client: ApiClient,
) -> None:
    """The tier table falls at two cables, so a cable that would fit at 40 percent is refused.

    The evaluation counts the candidate, so a second cable is priced at the
    two-cable tier of 31 percent: the allowed area is 177.63 sq mm against a used
    area of 190.06 sq mm, and the routing is refused. A monotone reading that
    applied the 40 percent three-or-more tier would compute 229.20 sq mm and admit
    it. Nothing about the conduit or the second link moves.

    Design: Difficulty/combinatorial_formula/conduit_fill_tier_table_is_non_monotonic_at_the_second_cable
    """
    scenario = _conduit_scenario(client)
    segment_id = scenario["segment"]["id"]
    fx.route_link(client, scenario["first"]["id"], segment_id)

    response = client.create_link_route(
        link_route_payload(
            scenario["second"]["id"],
            segment_id,
            fx.segment_version(client, segment_id),
            sequence_index=1,
        ),
        DESIGNER_HEADERS,
    )
    validate_error(response, ERR_PATHWAY_FILL_EXCEEDED, 422)

    segment = fx.read_segment(client, segment_id)
    assert segment["occupying_route_count"] == 1
    assert_decimal_equals(segment["fill_area_used_sq_mm"], 95.03)
    assert_decimal_equals(segment["fill_ratio"], 0.1658, 4)

    second = fx.read_link(client, scenario["second"]["id"])
    assert second["routed_segment_count"] == 0
    assert second["install_state"] == InstallState.DESIGNED


def _two_link_project(client: ApiClient) -> dict:
    """Two links of channel length 88.03 metres on a 150 cents-per-metre cable, both pulled."""
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
    links = []
    for identifier in ("TR01-A01", "TR01-A02"):
        link = fx.create_link(
            client,
            project["id"],
            room["id"],
            cable["id"],
            identifier=identifier,
            horizontal_length_m=85.63,
            consolidation_point_stub_m=0,
            patch_cord_allowance_m=2.00,
        )
        fx.route_link(client, link["id"], segment["id"])
        links.append(link)
    for link in links:
        fx.pull_link(client, link["id"])
    return {"project": project, "links": links}


def test_each_link_is_priced_and_rounded_on_its_own_channel_length(
    client: ApiClient,
) -> None:
    """A raw 13204.5-cent figure rounds half up to 13205 cents on every link.

    Horizontal 85.63 metres with 2.00 metres of cord allowance gives a
    channel_length_m of 88.03 on both links; at 150 cents per metre the material
    cost is rounded half up to whole cents on each link individually.

    Design: Difficulty/combinatorial_formula/as_built_cost_is_rounded_per_link_then_summed
    """
    scenario = _two_link_project(client)
    for link in scenario["links"]:
        assert_decimal_equals(link["channel_length_m"], 88.03)
        assert_cents(link["material_cost_cents"], 13205)
        stored = fx.read_link(client, link["id"])
        assert_cents(stored["material_cost_cents"], 13205)


def test_the_as_built_roll_up_sums_the_already_rounded_per_link_figures(
    client: ApiClient,
) -> None:
    """Rounding per link then summing gives 45410 cents, not 45409.

    Once both links are terminated they join the priced population. Each
    contributes its own rounded 13205 cents of material plus 9500 cents of
    termination labour, so the roll-up reads 45410 cents. Summing the raw material
    products first and rounding once would report 45409.

    Design: Difficulty/combinatorial_formula/as_built_cost_is_rounded_per_link_then_summed
    """
    scenario = _two_link_project(client)
    project_id = scenario["project"]["id"]
    for link in scenario["links"]:
        fx.terminate_link(client, link["id"])

    summary = validate_success(client.get_certification_summary(project_id, fx.PM_HEADERS))
    assert_cents(summary["as_built_cost_cents"], 45410)
    assert summary["total_link_count"] == 2
    assert summary["certified_link_count"] == 0
    assert_decimal_equals(summary["completeness_pct_strict"], 0.00)

    project = fx.read_project(client, project_id)
    assert_cents(project["as_built_cost_cents"], 45410)


def _occupied_project_with_five_hour_ticket(client: ApiClient) -> dict:
    """An occupied project carrying a submitted 5.0-hour expedited MOVE ticket."""
    project = fx.create_project(
        client,
        name="Riverside Tower Cabling",
        site_code="RVT1",
        plenum_ceiling=True,
        identifier_scheme=IdentifierScheme.TIA_606_CLASS_1,
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
    fx.record_link(client, link["id"], drawing_sheet_ref="E-501")
    fx.file_test(client, link["id"], insertion_loss_db=15.0, length_measured_m=85.63)
    fx.certify_link(client, link["id"])
    fx.release_coordination(client, coordination["id"])
    fx.declare_occupancy(client, project["id"])
    ticket = fx.create_ticket(
        client,
        project["id"],
        link["id"],
        room["id"],
        ticket_type="MOVE",
        requested_window_start="2026-08-12T08:00:00Z",
        requested_window_end="2026-08-12T13:00:00Z",
        labor_hours_estimate=5.0,
        expedite_requested=True,
    )
    return {"project": project, "ticket": ticket}


def test_the_volume_tier_is_selected_from_the_subtotal_not_the_billed_total(
    client: ApiClient,
) -> None:
    """Five expedited hours bill 55200 cents, because 48000 is below the first threshold.

    The tier is chosen at the third step from the subtotal of 48000 cents, which
    sits below 50000, so the discount is nil and the expedite fee of 15 percent is
    taken on the full subtotal. Reading the tier off the 55200-cent amount the
    client pays would wrongly grant 5 percent and bill 52440.

    Design: Difficulty/combinatorial_formula/mac_discount_tier_is_keyed_on_subtotal_not_billed_total
    """
    scenario = _occupied_project_with_five_hour_ticket(client)
    scheduled = fx.schedule_ticket(
        client,
        scenario["ticket"]["id"],
        scheduled_window_start="2026-08-12T08:00:00Z",
        scheduled_window_end="2026-08-12T13:00:00Z",
    )
    assert_cents(scheduled["estimated_billed_cents"], 55200)


def test_scheduling_commits_the_estimate_to_the_ledger_and_leaves_the_final_null(
    client: ApiClient,
) -> None:
    """Scheduling stamps the window and the estimate only; no final figure yet exists.

    The ticket moves to SCHEDULED with both window instants stored, the project's
    consumed_mac_cents grows by the 55200-cent estimate, and final_billed_cents
    stays null until the ticket is completed.

    Design: Difficulty/combinatorial_formula/mac_discount_tier_is_keyed_on_subtotal_not_billed_total
    """
    scenario = _occupied_project_with_five_hour_ticket(client)
    ticket_id = scenario["ticket"]["id"]
    scheduled = fx.schedule_ticket(
        client,
        ticket_id,
        scheduled_window_start="2026-08-12T08:00:00Z",
        scheduled_window_end="2026-08-12T13:00:00Z",
    )
    assert scheduled["ticket_state"] == TicketState.SCHEDULED
    assert_instant_equals(scheduled["scheduled_window_start"], "2026-08-12T08:00:00Z")
    assert_instant_equals(scheduled["scheduled_window_end"], "2026-08-12T13:00:00Z")

    project = fx.read_project(client, scenario["project"]["id"])
    assert_cents(project["consumed_mac_cents"], 55200)

    ticket = fx.read_ticket(client, ticket_id)
    assert ticket["final_billed_cents"] is None
