"""Derived quantities: fill allowances, insertion-loss budgets, ledgers and roll-ups.

Every figure asserted here is recomputed from the formula and the constants the PRD
fixes: the tiered fill allowance with its bend derate and 25 percent floor, the
per-cable separation requirement, the two-place insertion-loss budget, the priced
population of the as-built roll-up, the moves-adds-changes budget ledger, the room
power ledger, the pathway depth walk, the warranty coverage floor, the identifier
pattern selected by the project's scheme, and the two completeness variants.
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from decimal import Decimal
from typing import Any, Dict

from prd_bench_local_runner.testing import (
    validate_error,
    validate_paginated,
    validate_success,
)

from test_helpers import fixtures as fx
from test_helpers.api_client import ApiClient
from test_helpers.api_errors import (
    ERR_IDENTIFIER_FORMAT_INVALID,
    ERR_MAC_BUDGET_EXCEEDED,
    ERR_PATHWAY_CYCLE,
    ERR_POWER_CAPACITY_EXCEEDED,
    ERR_POWER_SEPARATION_INSUFFICIENT,
)
from test_helpers.assertions import (
    assert_cents,
    assert_completeness,
    assert_decimal_equals,
    assert_fill_ledger,
    assert_rack_ru_identity,
    assert_room_power_identity,
)
from test_helpers.factories import (
    link_payload,
    link_route_payload,
    rack_unit_assignment_payload,
    reparent_payload,
    schedule_payload,
)
from test_helpers.test_users import CERTIFIER_HEADERS, DESIGNER_HEADERS, PM_HEADERS
from test_helpers.types import (
    Application,
    CableCategory,
    GroundingStatus,
    IdentifierScheme,
    InstallState,
    JacketRating,
    ManufacturerProgram,
    PathwayType,
    RecordState,
    RegistrationState,
    RouteState,
    TestOutcome,
    TestStandard,
    TicketState,
    TicketType,
    WarrantyStatus,
)


def _assert_at_most_two_places(value: Any, label: str) -> None:
    """A reported decimal quantity carries no more than two decimal places."""
    assert value is not None, f"{label} must be reported, got None"
    exponent = Decimal(str(value)).normalize().as_tuple().exponent
    assert isinstance(exponent, int) and exponent >= -2, (
        f"{label} must be reported to two decimal places, got {value}"
    )


def _cat6a_cmp(client: ApiClient, **overrides: Any) -> Dict[str, Any]:
    """The plenum-rated CAT6A of 7.9 mm outside diameter: 49.02 sq mm of cross section."""
    payload: Dict[str, Any] = dict(
        category=CableCategory.CAT6A,
        jacket_rating=JacketRating.CMP,
        outer_diameter_mm=7.9,
        max_channel_length_m=100.0,
        shielded=False,
        cost_per_meter_cents=150,
        applications=[Application.DATA_HORIZONTAL],
    )
    payload.update(overrides)
    return fx.create_cable_type(client, **payload)


def _riverside_project(client: ApiClient, **overrides: Any) -> Dict[str, Any]:
    payload: Dict[str, Any] = dict(
        name="Riverside Tower Cabling",
        site_code="RVT1",
        plenum_ceiling=True,
        identifier_scheme=IdentifierScheme.TIA_606_CLASS_1,
    )
    payload.update(overrides)
    return fx.create_project(client, **payload)


def _riverside_scenario(client: ApiClient, **project_overrides: Any) -> Dict[str, Any]:
    """Project RVT1: a bonded room TR01, the CAT6A catalogue row, tray PS-A and a
    confirmed ceiling milestone — enough to route, pull and terminate a link."""
    project = _riverside_project(client, **project_overrides)
    room = fx.create_room(
        client,
        project["id"],
        room_code="TR01",
        floor=3,
        branch_circuit_amps=20,
        ups_capacity_va=3000,
    )
    room = fx.verify_grounding(
        client,
        room["id"],
        tgb_installed=True,
        bonding_conductor_awg=6,
        ground_resistance_milliohms=5000,
    )
    cable = _cat6a_cmp(client)
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
    coordination = fx.create_coordination(client, project["id"])
    fx.confirm_coordination(client, coordination["id"], confirmed_date="2026-08-05")
    assert room["grounding_status"] == GroundingStatus.COMPLIANT
    return {
        "project": project,
        "project_id": project["id"],
        "room": room,
        "room_id": room["id"],
        "cable": cable,
        "cable_type_id": cable["id"],
        "segment": segment,
        "segment_id": segment["id"],
        "coordination": coordination,
    }


def _design_link(
    client: ApiClient,
    scenario: Dict[str, Any],
    identifier: str,
    horizontal_length_m: float,
    patch_cord_allowance_m: float = 2.00,
) -> Dict[str, Any]:
    return fx.create_link(
        client,
        scenario["project_id"],
        scenario["room_id"],
        scenario["cable_type_id"],
        identifier=identifier,
        application=Application.DATA_HORIZONTAL,
        horizontal_length_m=horizontal_length_m,
        consolidation_point_stub_m=0,
        patch_cord_allowance_m=patch_cord_allowance_m,
    )


def _terminated_link(
    client: ApiClient,
    scenario: Dict[str, Any],
    identifier: str,
    horizontal_length_m: float,
) -> Dict[str, Any]:
    """A link routed through tray PS-A, pulled and terminated in the bonded room."""
    link = _design_link(client, scenario, identifier, horizontal_length_m)
    fx.route_link(client, link["id"], scenario["segment_id"])
    fx.pull_link(client, link["id"])
    return fx.terminate_link(client, link["id"])


def _certified_link(
    client: ApiClient,
    scenario: Dict[str, Any],
    identifier: str,
    horizontal_length_m: float,
    insertion_loss_db: float = 15.00,
) -> Dict[str, Any]:
    """A terminated link taken all the way through labelling, recording and sign-off."""
    link = _terminated_link(client, scenario, identifier, horizontal_length_m)
    fx.label_link(client, link["id"], identifier)
    fx.record_link(client, link["id"], drawing_sheet_ref="E-501")
    fx.file_test(
        client,
        link["id"],
        test_standard=TestStandard.PERMANENT_LINK,
        tester_model="DSX-8000",
        insertion_loss_db=insertion_loss_db,
        next_margin_db=3.20,
        return_loss_margin_db=2.10,
        length_measured_m=horizontal_length_m,
    )
    return fx.certify_link(client, link["id"])


def _three_segment_chain(client: ApiClient) -> Dict[str, Any]:
    """A tray feeding a six-bend conduit feeding a twenty-bend conduit, plus one link.

    The three segments differ only in pathway_type and bend_count, so a single link
    routed along the chain exercises three different arms of the allowance rule.
    """
    project = _riverside_project(client)
    room = fx.create_room(
        client,
        project["id"],
        room_code="TR01",
        floor=3,
        branch_circuit_amps=20,
        ups_capacity_va=3000,
    )
    cable = _cat6a_cmp(client)
    tray = fx.create_segment(
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
    six_bend = fx.create_segment(
        client,
        project["id"],
        segment_code="PS-B",
        pathway_type=PathwayType.EMT_CONDUIT,
        usable_area_sq_mm=573.0,
        length_m=12.0,
        bend_count=6,
        in_plenum_space=False,
        shared_with_power=False,
        power_separation_mm=0,
        upstream_segment_id=tray["id"],
    )
    twenty_bend = fx.create_segment(
        client,
        project["id"],
        segment_code="PS-C",
        pathway_type=PathwayType.EMT_CONDUIT,
        usable_area_sq_mm=573.0,
        length_m=9.0,
        bend_count=20,
        in_plenum_space=False,
        shared_with_power=False,
        power_separation_mm=0,
        upstream_segment_id=six_bend["id"],
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
        "cable": cable,
        "tray": tray,
        "six_bend": six_bend,
        "twenty_bend": twenty_bend,
        "link": link,
    }


def test_tray_bend_derate_and_the_floor_give_three_different_allowances(
    client: ApiClient,
) -> None:
    """An empty tray allows 50 percent, a six-bend conduit 45 and a twenty-bend one 25.

    A freshly designed segment reports the allowance for one more cable than it
    carries, which on an empty segment is the single-cable figure. The tray takes 50
    percent whatever the count; the conduit starts from 53 percent and loses 2 points
    for every bend past the second, giving 45 at six bends; at twenty bends the raw
    arithmetic gives 17, and the floor lifts it to 25.

    Design: Corner/calculations/tray_percentage_bend_derate_and_the_minimum_fill_floor_are_all_applied
    """
    chain = _three_segment_chain(client)
    assert_decimal_equals(chain["cable"]["cross_section_area_sq_mm"], 49.02)

    assert chain["tray"]["allowed_fill_pct"] == 50
    assert chain["six_bend"]["allowed_fill_pct"] == 45
    assert chain["twenty_bend"]["allowed_fill_pct"] == 25

    for segment in ("tray", "six_bend", "twenty_bend"):
        row = chain[segment]
        assert row["occupying_route_count"] == 0
        assert_decimal_equals(row["fill_area_used_sq_mm"], 0.00)
        assert_decimal_equals(row["fill_ratio"], 0.0000, 4)


def test_one_cable_along_the_chain_fills_every_segment_and_numbers_the_depths(
    client: ApiClient,
) -> None:
    """Routing one 49.02 sq mm cable through all three segments admits it everywhere.

    The twenty-bend conduit admits the cable on its 25 percent floor — 143.25 sq mm of
    allowed area against 49.02 used — so all three routings are created and the link
    reports three routed segments. Each segment carries exactly the one cable's area,
    the ratio is the used area over the usable area at four places, and the depths run
    0, 1 and 2 down the parent chain. Each conduit now carries a cable, so the
    allowance it reports is the two-cable figure of 31 percent less its bend derate,
    which the floor lifts back to 25.

    Design: Corner/calculations/tray_percentage_bend_derate_and_the_minimum_fill_floor_are_all_applied
    """
    chain = _three_segment_chain(client)
    link_id = chain["link"]["id"]
    for index, key in enumerate(("tray", "six_bend", "twenty_bend"), start=1):
        route = fx.route_link(client, link_id, chain[key]["id"], sequence_index=index)
        assert route["route_state"] == RouteState.OCCUPYING
        assert_decimal_equals(route["consumed_area_sq_mm"], 49.02)

    assert fx.read_link(client, link_id)["routed_segment_count"] == 3

    tray = fx.read_segment(client, chain["tray"]["id"])
    assert tray["occupying_route_count"] == 1
    assert_decimal_equals(tray["fill_area_used_sq_mm"], 49.02)
    assert_decimal_equals(tray["fill_ratio"], 0.0025, 4)
    assert tray["allowed_fill_pct"] == 50
    assert tray["pathway_depth"] == 0
    assert_fill_ledger(tray)

    six_bend = fx.read_segment(client, chain["six_bend"]["id"])
    assert six_bend["occupying_route_count"] == 1
    assert_decimal_equals(six_bend["fill_area_used_sq_mm"], 49.02)
    assert_decimal_equals(six_bend["fill_ratio"], 0.0855, 4)
    assert six_bend["allowed_fill_pct"] == 25
    assert six_bend["pathway_depth"] == 1
    assert_fill_ledger(six_bend)

    twenty_bend = fx.read_segment(client, chain["twenty_bend"]["id"])
    assert twenty_bend["occupying_route_count"] == 1
    assert_decimal_equals(twenty_bend["fill_area_used_sq_mm"], 49.02)
    assert twenty_bend["allowed_fill_pct"] == 25
    assert twenty_bend["pathway_depth"] == 2
    assert_fill_ledger(twenty_bend)


def _shared_conduit(client: ApiClient) -> Dict[str, Any]:
    """One straight EMT conduit of 573.0 sq mm carrying two candidate links."""
    project = _riverside_project(client)
    room = fx.create_room(
        client,
        project["id"],
        room_code="TR01",
        floor=3,
        branch_circuit_amps=20,
        ups_capacity_va=3000,
    )
    cable = _cat6a_cmp(client)
    segment = fx.create_segment(
        client,
        project["id"],
        segment_code="PS-A",
        pathway_type=PathwayType.EMT_CONDUIT,
        usable_area_sq_mm=573.0,
        length_m=40.0,
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
        application=Application.DATA_HORIZONTAL,
        horizontal_length_m=40.00,
        consolidation_point_stub_m=0,
        patch_cord_allowance_m=2.00,
    )
    second = fx.create_link(
        client,
        project["id"],
        room["id"],
        cable["id"],
        identifier="TR01-A02",
        application=Application.DATA_HORIZONTAL,
        horizontal_length_m=41.00,
        consolidation_point_stub_m=0,
        patch_cord_allowance_m=2.00,
    )
    return {
        "project_id": project["id"],
        "segment_id": segment["id"],
        "first_id": first["id"],
        "second_id": second["id"],
    }


def test_withdrawing_the_second_route_returns_the_conduit_to_one_cable(
    client: ApiClient,
) -> None:
    """The fill ledger and the tier both come back exactly to where they were.

    An empty conduit reports the single-cable allowance of 53 percent; with one cable
    in it the reported allowance is the two-cable figure of 31, and with two cables the
    three-or-more figure of 40. Withdrawing the second routing gives back exactly its
    49.02 sq mm, drops the count to one and puts the reported allowance back to 31, so
    the compensating write leaves the conduit as the first cable found it.

    Design: Corner/calculations/withdrawn_routes_leave_the_fill_input_set_and_the_tier_returns_to_one_cable
    """
    scenario = _shared_conduit(client)
    segment_id = scenario["segment_id"]
    assert fx.read_segment(client, segment_id)["allowed_fill_pct"] == 53

    fx.route_link(client, scenario["first_id"], segment_id)
    after_first = fx.read_segment(client, segment_id)
    assert after_first["occupying_route_count"] == 1
    assert after_first["allowed_fill_pct"] == 31
    assert_decimal_equals(after_first["fill_area_used_sq_mm"], 49.02)
    assert_decimal_equals(after_first["fill_ratio"], 0.0855, 4)

    second_route = fx.route_link(client, scenario["second_id"], segment_id)
    after_second = fx.read_segment(client, segment_id)
    assert after_second["occupying_route_count"] == 2
    assert after_second["allowed_fill_pct"] == 40
    assert_decimal_equals(after_second["fill_area_used_sq_mm"], 98.04)
    assert_decimal_equals(after_second["fill_ratio"], 0.1711, 4)

    fx.withdraw_route(client, second_route["id"], segment_id)
    after_withdrawal = fx.read_segment(client, segment_id)
    assert after_withdrawal["occupying_route_count"] == 1
    assert after_withdrawal["allowed_fill_pct"] == 31
    assert_decimal_equals(after_withdrawal["fill_area_used_sq_mm"], 49.02)
    assert_decimal_equals(after_withdrawal["fill_ratio"], 0.0855, 4)
    assert_fill_ledger(after_withdrawal)


def test_a_withdrawn_routing_is_retained_but_leaves_the_occupying_input_set(
    client: ApiClient,
) -> None:
    """The WITHDRAWN row keeps its snapshot while contributing nothing to the fill.

    Withdrawal is not a deletion: the routing is still readable, still carries the
    49.02 sq mm it consumed, and its owning link's routed_segment_count has fallen back
    to zero. Filtering the conduit's routings on OCCUPYING returns only the surviving
    one, which is exactly the input set the fill sums walk.

    Design: Corner/calculations/withdrawn_routes_leave_the_fill_input_set_and_the_tier_returns_to_one_cable
    """
    scenario = _shared_conduit(client)
    segment_id = scenario["segment_id"]
    fx.route_link(client, scenario["first_id"], segment_id)
    second_route = fx.route_link(client, scenario["second_id"], segment_id)
    fx.withdraw_route(client, second_route["id"], segment_id)

    withdrawn = validate_success(client.get_link_route(second_route["id"], DESIGNER_HEADERS))
    assert withdrawn["route_state"] == RouteState.WITHDRAWN
    assert_decimal_equals(withdrawn["consumed_area_sq_mm"], 49.02)

    occupying, meta = validate_paginated(
        client.list_link_routes(
            DESIGNER_HEADERS,
            params={
                "pathway_segment_id": segment_id,
                "route_state": RouteState.OCCUPYING.value,
            },
        )
    )
    assert meta["total_count"] == 1
    assert len(occupying) == 1
    assert occupying[0]["link_id"] == scenario["first_id"]

    assert fx.read_link(client, scenario["second_id"])["routed_segment_count"] == 0
    assert fx.read_link(client, scenario["first_id"])["routed_segment_count"] == 1


def _power_sharing_conduit(client: ApiClient) -> Dict[str, Any]:
    """A conduit sharing its space with power at exactly 25 mm of clear separation.

    Three cable types sit against that one segment: shielded copper, unshielded copper
    and single-mode fibre, each with its own link, so the requirement can be read off
    the cable rather than off the pathway.
    """
    project = _riverside_project(client)
    room = fx.create_room(
        client,
        project["id"],
        room_code="TR01",
        floor=3,
        branch_circuit_amps=20,
        ups_capacity_va=3000,
    )
    shielded = _cat6a_cmp(
        client, outer_diameter_mm=8.5, shielded=True, cost_per_meter_cents=210
    )
    unshielded = _cat6a_cmp(client)
    fibre = fx.create_cable_type(
        client,
        category=CableCategory.OS2_SMF,
        jacket_rating=JacketRating.CMP,
        outer_diameter_mm=2.0,
        max_channel_length_m=300.0,
        shielded=False,
        cost_per_meter_cents=90,
        applications=[Application.BACKBONE],
    )
    segment = fx.create_segment(
        client,
        project["id"],
        segment_code="PS-P",
        pathway_type=PathwayType.EMT_CONDUIT,
        usable_area_sq_mm=573.0,
        length_m=30.0,
        bend_count=0,
        in_plenum_space=False,
        shared_with_power=True,
        power_separation_mm=25,
    )
    shielded_link = fx.create_link(
        client,
        project["id"],
        room["id"],
        shielded["id"],
        identifier="TR01-A01",
        application=Application.DATA_HORIZONTAL,
        horizontal_length_m=30.00,
        consolidation_point_stub_m=0,
        patch_cord_allowance_m=2.00,
    )
    unshielded_link = fx.create_link(
        client,
        project["id"],
        room["id"],
        unshielded["id"],
        identifier="TR01-A02",
        application=Application.DATA_HORIZONTAL,
        horizontal_length_m=30.00,
        consolidation_point_stub_m=0,
        patch_cord_allowance_m=2.00,
    )
    fibre_link = fx.create_link(
        client,
        project["id"],
        room["id"],
        fibre["id"],
        identifier="TR01-B01",
        application=Application.BACKBONE,
        horizontal_length_m=30.00,
        consolidation_point_stub_m=0,
        patch_cord_allowance_m=2.00,
    )
    return {
        "segment_id": segment["id"],
        "shielded": shielded,
        "unshielded": unshielded,
        "fibre": fibre,
        "shielded_link_id": shielded_link["id"],
        "unshielded_link_id": unshielded_link["id"],
        "fibre_link_id": fibre_link["id"],
    }


def test_the_screen_earns_the_shielded_cable_a_place_the_unshielded_one_is_denied(
    client: ApiClient,
) -> None:
    """At 25 mm of clearance the screened cable is admitted and the unscreened refused.

    A shielded copper cable needs 25 millimetres from unshielded power conductors, and
    separation exactly equal to the requirement is admitted, so the 8.5 mm cable takes
    its 56.75 sq mm place in the conduit. The unshielded cable of the same category
    needs 50 millimetres and is refused; the refusal consumes no area and leaves its
    link unrouted, which shows the requirement is read from the cable and not from the
    pathway the two would have shared.

    Design: Corner/calculations/separation_requirement_switches_with_the_shield_and_admits_exact_equality
    """
    scenario = _power_sharing_conduit(client)
    segment_id = scenario["segment_id"]
    assert_decimal_equals(scenario["shielded"]["cross_section_area_sq_mm"], 56.75)

    admitted = fx.route_link(client, scenario["shielded_link_id"], segment_id)
    assert admitted["route_state"] == RouteState.OCCUPYING
    assert_decimal_equals(admitted["consumed_area_sq_mm"], 56.75)

    refused = client.create_link_route(
        link_route_payload(
            scenario["unshielded_link_id"],
            segment_id,
            fx.segment_version(client, segment_id),
            sequence_index=1,
        ),
        DESIGNER_HEADERS,
    )
    validate_error(refused, ERR_POWER_SEPARATION_INSUFFICIENT, 422)

    segment = fx.read_segment(client, segment_id)
    assert segment["occupying_route_count"] == 1
    assert_decimal_equals(segment["fill_area_used_sq_mm"], 56.75)

    unrouted = fx.read_link(client, scenario["unshielded_link_id"])
    assert unrouted["routed_segment_count"] == 0
    assert unrouted["install_state"] == InstallState.DESIGNED


def test_fibre_needs_no_separation_at_all_and_joins_the_shielded_cable(
    client: ApiClient,
) -> None:
    """Single-mode fibre carries no induced current, so it requires zero clearance.

    The 2.0 mm fibre takes 3.14 sq mm of the conduit alongside the shielded copper,
    bringing the used area to 59.89 sq mm and the fill ratio to 0.1045. With two cables
    in the conduit the allowance reported for the next one is the three-or-more figure
    of 40 percent, and the run is nowhere near it.

    Design: Corner/calculations/separation_requirement_switches_with_the_shield_and_admits_exact_equality
    """
    scenario = _power_sharing_conduit(client)
    segment_id = scenario["segment_id"]
    assert_decimal_equals(scenario["fibre"]["cross_section_area_sq_mm"], 3.14)

    fx.route_link(client, scenario["shielded_link_id"], segment_id)
    fibre_route = fx.route_link(client, scenario["fibre_link_id"], segment_id)
    assert fibre_route["route_state"] == RouteState.OCCUPYING
    assert_decimal_equals(fibre_route["consumed_area_sq_mm"], 3.14)

    segment = fx.read_segment(client, segment_id)
    assert segment["occupying_route_count"] == 2
    assert_decimal_equals(segment["fill_area_used_sq_mm"], 59.89)
    assert_decimal_equals(segment["fill_ratio"], 0.1045, 4)
    assert segment["allowed_fill_pct"] == 40
    assert_fill_ledger(segment)

    assert fx.read_link(client, scenario["fibre_link_id"])["routed_segment_count"] == 1


def test_both_length_variants_carry_their_own_two_place_insertion_loss_budget(
    client: ApiClient,
) -> None:
    """The permanent link is budgeted at 16.67 dB and the channel at 17.13 dB.

    The budget is 0.40 dB of fixed connector allowance plus 0.19 dB for every metre of
    the graded length, and the graded length is chosen by the standard the tester was
    configured for. Grading the 85.63-metre permanent link gives a raw 16.6697 that is
    rounded half up to 16.67, and grading the 88.03-metre channel gives a raw 17.1257
    that is rounded to 17.13; a 16.60 dB measurement sits inside both, so the same
    physical cable passes twice.

    Design: Corner/calculations/insertion_loss_budget_is_rounded_to_two_places_on_each_graded_length
    """
    scenario = _riverside_scenario(client)
    link = _terminated_link(client, scenario, "TR01-A01", 85.63)
    assert_decimal_equals(link["permanent_link_length_m"], 85.63)
    assert_decimal_equals(link["channel_length_m"], 88.03)

    permanent = fx.file_test(
        client,
        link["id"],
        test_standard=TestStandard.PERMANENT_LINK,
        tester_model="DSX-8000",
        insertion_loss_db=16.60,
        next_margin_db=3.25,
        return_loss_margin_db=2.10,
        length_measured_m=85.60,
    )
    assert_decimal_equals(permanent["insertion_loss_budget_db"], 16.67)
    _assert_at_most_two_places(
        permanent["insertion_loss_budget_db"], "permanent-link insertion_loss_budget_db"
    )
    assert_decimal_equals(permanent["worst_margin_db"], 2.10)
    assert permanent["outcome"] == TestOutcome.PASS
    assert permanent["failure_reason"] is None

    channel = fx.file_test(
        client,
        link["id"],
        test_standard=TestStandard.CHANNEL,
        tester_model="DSX-8000",
        insertion_loss_db=16.60,
        next_margin_db=3.25,
        return_loss_margin_db=2.10,
        length_measured_m=88.00,
    )
    assert_decimal_equals(channel["insertion_loss_budget_db"], 17.13)
    _assert_at_most_two_places(
        channel["insertion_loss_budget_db"], "channel insertion_loss_budget_db"
    )
    assert_decimal_equals(channel["worst_margin_db"], 2.10)
    assert channel["outcome"] == TestOutcome.PASS

    graded = fx.read_link(client, link["id"])
    assert graded["test_attempt_count"] == 2
    assert graded["latest_test_outcome"] == TestOutcome.PASS


def test_a_margin_just_inside_the_accuracy_band_grades_pass_asterisk(
    client: ApiClient,
) -> None:
    """A worst margin of 0.49 dB is marginal while 0.50 dB is a clean pass.

    The field tester's own accuracy band is a strict upper bound, so a margin the tester
    cannot distinguish from the limit line grades PASS_ASTERISK with no failure reason,
    and a margin sitting exactly on the band grades PASS. Both results move the link to
    TESTED_PASS, so the only field that separates the marginal result from the clean one
    is the outcome the link reports as its latest.

    Design: Corner/calculations/worst_margin_inside_the_tester_accuracy_band_grades_pass_asterisk
    """
    scenario = _riverside_scenario(client)
    link = _terminated_link(client, scenario, "TR01-A01", 85.63)

    marginal = fx.file_test(
        client,
        link["id"],
        test_standard=TestStandard.PERMANENT_LINK,
        tester_model="DSX-8000",
        insertion_loss_db=16.00,
        next_margin_db=0.49,
        return_loss_margin_db=2.10,
        length_measured_m=85.60,
    )
    assert_decimal_equals(marginal["worst_margin_db"], 0.49)
    assert marginal["outcome"] == TestOutcome.PASS_ASTERISK
    assert marginal["failure_reason"] is None

    after_marginal = fx.read_link(client, link["id"])
    assert after_marginal["install_state"] == InstallState.TESTED_PASS
    assert after_marginal["latest_test_outcome"] == TestOutcome.PASS_ASTERISK

    clean = fx.file_test(
        client,
        link["id"],
        test_standard=TestStandard.PERMANENT_LINK,
        tester_model="DSX-8000",
        insertion_loss_db=16.00,
        next_margin_db=0.50,
        return_loss_margin_db=2.10,
        length_measured_m=85.60,
    )
    assert_decimal_equals(clean["worst_margin_db"], 0.50)
    assert clean["outcome"] == TestOutcome.PASS

    after_clean = fx.read_link(client, link["id"])
    assert after_clean["install_state"] == InstallState.TESTED_PASS
    assert after_clean["latest_test_outcome"] == TestOutcome.PASS
    assert after_clean["test_attempt_count"] == 2


def _priced_population(client: ApiClient) -> Dict[str, Any]:
    """One terminated link and one routed-but-unbuilt link in the same project."""
    scenario = _riverside_scenario(client)
    first = _terminated_link(client, scenario, "TR01-A01", 85.63)
    second = _design_link(client, scenario, "TR01-A02", 40.00)
    fx.route_link(client, second["id"], scenario["segment_id"])
    return {
        "project_id": scenario["project_id"],
        "first": first,
        "second": second,
    }


def _as_built_cost(client: ApiClient, project_id: str) -> int:
    summary = validate_success(client.get_certification_summary(project_id, PM_HEADERS))
    return summary["as_built_cost_cents"]


def test_a_designed_or_pulled_link_is_priced_nowhere(client: ApiClient) -> None:
    """Pulling cable into the tray does not yet add a cent to the as-built total.

    The priced population opens at termination, so while the second link is DESIGNED and
    again once it is PULLED the project reads the first link's 22705 cents and nothing
    more. The second link nonetheless carries its own stamped material cost of 6360
    cents from design time, which is what makes the exclusion a population rule rather
    than a missing figure.

    Design: Corner/calculations/as_built_cost_excludes_designed_and_pulled_links_and_admits_terminated_ones
    """
    scenario = _priced_population(client)
    project_id = scenario["project_id"]
    second_id = scenario["second"]["id"]

    assert_cents(_as_built_cost(client, project_id), 22705)
    assert fx.read_link(client, second_id)["install_state"] == InstallState.DESIGNED

    fx.pull_link(client, second_id)
    assert fx.read_link(client, second_id)["install_state"] == InstallState.PULLED
    assert_cents(_as_built_cost(client, project_id), 22705)

    assert_cents(scenario["first"]["material_cost_cents"], 13205)
    assert_cents(scenario["second"]["material_cost_cents"], 6360)


def test_terminating_the_second_link_admits_it_to_the_priced_population(
    client: ApiClient,
) -> None:
    """Termination alone lifts the project total from 22705 to 38565 cents.

    A channel length of 42.40 metres at 150 cents per metre is 6360 cents of material,
    and every terminated link carries 9500 cents of labour for its two landed ends, so
    the second link contributes 15860 the moment it is terminated. Nothing else about
    the row changes, and the stored project figure agrees with the computed summary.

    Design: Corner/calculations/as_built_cost_excludes_designed_and_pulled_links_and_admits_terminated_ones
    """
    scenario = _priced_population(client)
    project_id = scenario["project_id"]
    second_id = scenario["second"]["id"]
    fx.pull_link(client, second_id)

    terminated = fx.terminate_link(client, second_id)
    assert terminated["install_state"] == InstallState.TERMINATED
    assert_decimal_equals(terminated["channel_length_m"], 42.40)
    assert_cents(terminated["material_cost_cents"], 6360)
    assert_cents(_as_built_cost(client, project_id), 38565)

    project = fx.read_project(client, project_id)
    assert_cents(project["as_built_cost_cents"], 38565)
    assert project["total_link_count"] == 2
    assert project["certified_link_count"] == 0


def _occupied_riverside(client: ApiClient, mac_budget_cents: int = 19200) -> Dict[str, Any]:
    """A handed-over project with one certified link and a budget of exactly two hours."""
    scenario = _riverside_scenario(client, mac_budget_cents=mac_budget_cents)
    link = _certified_link(client, scenario, "TR01-A01", 85.63)
    fx.release_coordination(client, scenario["coordination"]["id"])
    fx.declare_occupancy(client, scenario["project_id"])
    return {
        "project_id": scenario["project_id"],
        "room_id": scenario["room_id"],
        "link_id": link["id"],
    }


def _one_hour_ticket(
    client: ApiClient, context: Dict[str, Any], start: str, end: str
) -> Dict[str, Any]:
    """A one-hour MOVE ticket with no expedite, which bills a flat 9600 cents."""
    return fx.create_ticket(
        client,
        context["project_id"],
        context["link_id"],
        context["room_id"],
        ticket_type=TicketType.MOVE,
        requested_window_start=start,
        requested_window_end=end,
        labor_hours_estimate=1.0,
        expedite_requested=False,
    )


def test_rejected_and_submitted_tickets_contribute_nothing_to_the_ledger(
    client: ApiClient,
) -> None:
    """Only scheduled work sits in the ledger; a rejection and a fresh request do not.

    One hour of crew time at 96 dollars an hour is a subtotal of 9600 cents, and a
    subtotal under the first volume threshold earns no discount, so scheduling the first
    ticket commits exactly 9600 cents. Rejecting the second ticket is the disjoint branch
    out of SUBMITTED: it leaves the billing field null and the ledger untouched, and a
    third ticket still awaiting a window is equally invisible to the ledger.

    Design: Corner/calculations/mac_budget_ledger_ignores_rejected_and_submitted_tickets_and_admits_equality
    """
    context = _occupied_riverside(client)
    project_id = context["project_id"]

    first = _one_hour_ticket(client, context, "2026-08-10T09:00:00Z", "2026-08-10T10:00:00Z")
    scheduled = fx.schedule_ticket(
        client,
        first["id"],
        scheduled_window_start="2026-08-10T09:00:00Z",
        scheduled_window_end="2026-08-10T10:00:00Z",
    )
    assert scheduled["ticket_state"] == TicketState.SCHEDULED
    assert_cents(scheduled["estimated_billed_cents"], 9600)
    assert_cents(fx.read_project(client, project_id)["consumed_mac_cents"], 9600)

    second = _one_hour_ticket(client, context, "2026-08-11T09:00:00Z", "2026-08-11T10:00:00Z")
    rejected = fx.reject_ticket(client, second["id"])
    assert rejected["ticket_state"] == TicketState.REJECTED
    assert rejected["estimated_billed_cents"] is None
    assert_cents(fx.read_project(client, project_id)["consumed_mac_cents"], 9600)

    third = _one_hour_ticket(client, context, "2026-08-10T12:00:00Z", "2026-08-10T13:00:00Z")
    assert third["ticket_state"] == TicketState.SUBMITTED
    assert third["estimated_billed_cents"] is None
    assert_cents(fx.read_project(client, project_id)["consumed_mac_cents"], 9600)

    summary = validate_success(client.get_certification_summary(project_id, PM_HEADERS))
    assert_cents(summary["consumed_mac_cents"], 9600)


def test_the_budget_admits_the_ticket_that_lands_exactly_on_it_and_refuses_the_next(
    client: ApiClient,
) -> None:
    """Two hours of work exhaust a 19200-cent budget, and the third hour is refused.

    Landing exactly on the budget is admitted, so the second scheduling takes the ledger
    to precisely the 19200 cents the project was given. The next ticket would take it to
    28800 and is refused with a payment-required answer that leaves the ticket SUBMITTED
    with neither a window nor an estimate, so the ledger still reads the two hours that
    were actually committed.

    Design: Corner/calculations/mac_budget_ledger_ignores_rejected_and_submitted_tickets_and_admits_equality
    """
    context = _occupied_riverside(client)
    project_id = context["project_id"]
    assert_cents(fx.read_project(client, project_id)["mac_budget_cents"], 19200)

    first = _one_hour_ticket(client, context, "2026-08-10T09:00:00Z", "2026-08-10T10:00:00Z")
    fx.schedule_ticket(
        client,
        first["id"],
        scheduled_window_start="2026-08-10T09:00:00Z",
        scheduled_window_end="2026-08-10T10:00:00Z",
    )
    second = _one_hour_ticket(client, context, "2026-08-10T12:00:00Z", "2026-08-10T13:00:00Z")
    fx.schedule_ticket(
        client,
        second["id"],
        scheduled_window_start="2026-08-10T12:00:00Z",
        scheduled_window_end="2026-08-10T13:00:00Z",
    )
    assert_cents(fx.read_project(client, project_id)["consumed_mac_cents"], 19200)

    third = _one_hour_ticket(client, context, "2026-08-10T15:00:00Z", "2026-08-10T16:00:00Z")
    refused = client.schedule_mac_ticket(
        third["id"],
        schedule_payload(
            scheduled_window_start="2026-08-10T15:00:00Z",
            scheduled_window_end="2026-08-10T16:00:00Z",
        ),
        PM_HEADERS,
    )
    validate_error(refused, ERR_MAC_BUDGET_EXCEEDED, 402)

    stalled = fx.read_ticket(client, third["id"])
    assert stalled["ticket_state"] == TicketState.SUBMITTED
    assert stalled["estimated_billed_cents"] is None
    assert stalled["scheduled_window_start"] is None

    summary = validate_success(client.get_certification_summary(project_id, PM_HEADERS))
    assert_cents(summary["consumed_mac_cents"], 19200)


def _two_rack_room(client: ApiClient) -> Dict[str, Any]:
    """Room TR01 on a 3000 VA uninterruptible supply, holding racks A and B."""
    project = _riverside_project(client)
    room = fx.create_room(
        client,
        project["id"],
        room_code="TR01",
        floor=3,
        branch_circuit_amps=20,
        ups_capacity_va=3000,
    )
    rack_a = fx.create_rack(client, room["id"], rack_code="A", total_ru=42)
    rack_b = fx.create_rack(client, room["id"], rack_code="B", total_ru=42)
    return {
        "room_id": room["id"],
        "rack_a_id": rack_a["id"],
        "rack_b_id": rack_b["id"],
    }


def test_the_room_ledger_sums_two_racks_and_admits_the_last_available_volt_ampere(
    client: ApiClient,
) -> None:
    """1200 VA in one rack and 1500 in another leave exactly 300 VA of headroom.

    The room's load is recomputed from its racks rather than from the placements, so a
    core switch in rack A and a supply head end in rack B together read 2700 VA against
    the 3000 VA supply. A 300 VA distribution unit is then admitted at exactly zero
    headroom, because equality with the room's capacity is allowed, and both rack ledgers
    reconcile against their own occupancy.

    Design: Corner/calculations/room_power_ledger_sums_across_two_racks_and_admits_exact_capacity
    """
    racks = _two_rack_room(client)
    fx.place_equipment(
        client,
        racks["rack_a_id"],
        equipment_label="Core switch",
        start_ru=1,
        end_ru=4,
        power_va=1200,
    )
    fx.place_equipment(
        client,
        racks["rack_b_id"],
        equipment_label="UPS head end",
        start_ru=1,
        end_ru=2,
        power_va=1500,
    )

    room = fx.read_room(client, racks["room_id"])
    assert room["power_load_va"] == 2700
    assert room["power_headroom_va"] == 300
    assert_room_power_identity(room)

    fitting = fx.place_equipment(
        client,
        racks["rack_b_id"],
        equipment_label="Fitting PDU",
        start_ru=3,
        end_ru=4,
        power_va=300,
    )
    assert fitting["span_ru"] == 2

    rack_a = fx.read_rack(client, racks["rack_a_id"])
    rack_b = fx.read_rack(client, racks["rack_b_id"])
    assert rack_a["power_draw_va"] == 1200
    assert rack_b["power_draw_va"] == 1800
    assert rack_b["occupied_ru"] == 4
    assert_rack_ru_identity(rack_a)
    assert_rack_ru_identity(rack_b)

    filled = fx.read_room(client, racks["room_id"])
    assert filled["power_load_va"] == 3000
    assert filled["power_headroom_va"] == 0
    assert_room_power_identity(filled)


def test_one_volt_ampere_too_many_is_refused_and_consumes_nothing(
    client: ApiClient,
) -> None:
    """A 301 VA unit against 300 VA of headroom is refused and moves no ledger.

    The power check reaches out of the rack and into the room, so the excess is measured
    against the room's load and not against the rack's own draw. The refusal leaves the
    rack's occupancy, its draw and its revision counter exactly where they were, and the
    room still reads its 2700 VA with 300 VA to spare.

    Design: Corner/calculations/room_power_ledger_sums_across_two_racks_and_admits_exact_capacity
    """
    racks = _two_rack_room(client)
    rack_b_id = racks["rack_b_id"]
    fx.place_equipment(
        client,
        racks["rack_a_id"],
        equipment_label="Core switch",
        start_ru=1,
        end_ru=4,
        power_va=1200,
    )
    fx.place_equipment(
        client,
        rack_b_id,
        equipment_label="UPS head end",
        start_ru=1,
        end_ru=2,
        power_va=1500,
    )
    pinned_version = fx.rack_version(client, rack_b_id)

    refused = client.create_rack_unit_assignment(
        rack_unit_assignment_payload(
            rack_b_id,
            pinned_version,
            equipment_label="Overflowing PDU",
            start_ru=3,
            end_ru=4,
            power_va=301,
        ),
        DESIGNER_HEADERS,
    )
    validate_error(refused, ERR_POWER_CAPACITY_EXCEEDED, 422)

    rack_b = fx.read_rack(client, rack_b_id)
    assert rack_b["occupied_ru"] == 2
    assert rack_b["power_draw_va"] == 1500
    assert rack_b["version"] == pinned_version
    assert_rack_ru_identity(rack_b)

    room = fx.read_room(client, racks["room_id"])
    assert room["power_load_va"] == 2700
    assert room["power_headroom_va"] == 300
    assert_room_power_identity(room)


def _two_pathway_chains(client: ApiClient) -> Dict[str, Any]:
    """Chain PS-A to PS-B to PS-C, and a second chain PS-Z to PS-W beside it."""
    project = _riverside_project(client)
    project_id = project["id"]
    seg_a = fx.create_segment(
        client,
        project_id,
        segment_code="PS-A",
        pathway_type=PathwayType.CABLE_TRAY,
        usable_area_sq_mm=20000.0,
        length_m=40.0,
        bend_count=0,
    )
    seg_b = fx.create_segment(
        client,
        project_id,
        segment_code="PS-B",
        pathway_type=PathwayType.EMT_CONDUIT,
        usable_area_sq_mm=573.0,
        length_m=12.0,
        bend_count=0,
        upstream_segment_id=seg_a["id"],
    )
    seg_c = fx.create_segment(
        client,
        project_id,
        segment_code="PS-C",
        pathway_type=PathwayType.INNERDUCT,
        usable_area_sq_mm=180.0,
        length_m=6.0,
        bend_count=0,
        upstream_segment_id=seg_b["id"],
    )
    seg_z = fx.create_segment(
        client,
        project_id,
        segment_code="PS-Z",
        pathway_type=PathwayType.CABLE_TRAY,
        usable_area_sq_mm=20000.0,
        length_m=30.0,
        bend_count=0,
    )
    seg_w = fx.create_segment(
        client,
        project_id,
        segment_code="PS-W",
        pathway_type=PathwayType.EMT_CONDUIT,
        usable_area_sq_mm=573.0,
        length_m=8.0,
        bend_count=0,
        upstream_segment_id=seg_z["id"],
    )
    assert seg_a["pathway_depth"] == 0
    assert seg_b["pathway_depth"] == 1
    assert seg_c["pathway_depth"] == 2
    assert seg_z["pathway_depth"] == 0
    assert seg_w["pathway_depth"] == 1
    return {
        "seg_a": seg_a,
        "seg_b": seg_b,
        "seg_c": seg_c,
        "seg_z": seg_z,
        "seg_w": seg_w,
    }


def test_re_pointing_a_segment_at_its_own_descendant_is_refused(
    client: ApiClient,
) -> None:
    """Feeding PS-B from PS-C would close the chain back on itself, so it is refused.

    The check walks upstream from the proposed parent: starting at PS-C the walk reaches
    PS-B, which is the segment being moved, so the move would make a run feed itself and
    is refused. Nothing about the graph moves — PS-B keeps its parent, its depth and its
    revision counter, and its descendant keeps the depth it had.

    Design: Corner/calculations/pathway_depth_is_recomputed_for_descendants_and_a_cycle_is_refused
    """
    chains = _two_pathway_chains(client)
    seg_b = chains["seg_b"]
    pinned_version = seg_b["version"]

    refused = client.reparent_pathway_segment(
        seg_b["id"],
        reparent_payload(chains["seg_c"]["id"], pinned_version),
        DESIGNER_HEADERS,
    )
    validate_error(refused, ERR_PATHWAY_CYCLE, 422)

    unmoved = fx.read_segment(client, seg_b["id"])
    assert unmoved["upstream_segment_id"] == chains["seg_a"]["id"]
    assert unmoved["pathway_depth"] == 1
    assert unmoved["version"] == pinned_version
    assert fx.read_segment(client, chains["seg_c"]["id"])["pathway_depth"] == 2


def test_a_legal_re_point_renumbers_the_descendant_that_nobody_touched(
    client: ApiClient,
) -> None:
    """Moving PS-B under PS-W pushes PS-B to depth 2 and drags PS-C to depth 3.

    Depth is derived from the parent chain, not stored independently, so re-pointing a
    segment renumbers every segment whose chain runs through it. PS-W sits at depth 1, so
    the moved conduit lands at 2 and its innerduct child at 3 although no request named
    it. The other chain and the original root are undisturbed.

    Design: Corner/calculations/pathway_depth_is_recomputed_for_descendants_and_a_cycle_is_refused
    """
    chains = _two_pathway_chains(client)
    moved = fx.reparent_segment(
        client, chains["seg_b"]["id"], chains["seg_w"]["id"]
    )
    assert moved["upstream_segment_id"] == chains["seg_w"]["id"]
    assert moved["pathway_depth"] == 2

    assert fx.read_segment(client, chains["seg_c"]["id"])["pathway_depth"] == 3
    assert fx.read_segment(client, chains["seg_a"]["id"])["pathway_depth"] == 0
    assert fx.read_segment(client, chains["seg_z"]["id"])["pathway_depth"] == 0
    assert fx.read_segment(client, chains["seg_w"]["id"])["pathway_depth"] == 1


def _reworked_link(
    client: ApiClient,
    scenario: Dict[str, Any],
    identifier: str,
    horizontal_length_m: float,
    losses: Any,
) -> Dict[str, Any]:
    """A terminated, labelled and recorded link tested three times: one fail, two passes."""
    link = _terminated_link(client, scenario, identifier, horizontal_length_m)
    fx.label_link(client, link["id"], identifier)
    fx.record_link(client, link["id"], drawing_sheet_ref="E-501")
    for insertion_loss_db, next_margin_db, return_loss_margin_db in losses:
        fx.file_test(
            client,
            link["id"],
            test_standard=TestStandard.PERMANENT_LINK,
            tester_model="DSX-8000",
            insertion_loss_db=insertion_loss_db,
            next_margin_db=next_margin_db,
            return_loss_margin_db=return_loss_margin_db,
            length_measured_m=horizontal_length_m,
        )
    return fx.read_link(client, link["id"])


def test_two_rework_links_take_a_fifteen_year_programme_down_to_the_floor(
    client: ApiClient,
) -> None:
    """A standard fifteen-year term less two five-year penalties is held up at ten.

    Every link tested three or more times costs five years of warranty term, and both
    links here were tested once beyond the limit line and twice cleanly, so the raw
    arithmetic gives fifteen less ten, which is five. The ten-year floor is applied after
    the penalty rather than blended into it, so the term frozen onto the submission is ten
    years against two certified links.

    Design: Corner/calculations/warranty_coverage_floor_applies_after_the_rework_penalty
    """
    scenario = _riverside_scenario(client)
    project_id = scenario["project_id"]
    first = _reworked_link(
        client,
        scenario,
        "TR01-A01",
        85.63,
        [(20.00, 3.20, 2.10), (15.00, 3.20, 2.10), (14.80, 3.40, 2.20)],
    )
    assert first["test_attempt_count"] == 3
    fx.certify_link(client, first["id"])

    second = _reworked_link(
        client,
        scenario,
        "TR01-A02",
        40.00,
        [(12.00, 3.20, 2.10), (7.50, 3.20, 2.10), (7.40, 3.30, 2.20)],
    )
    assert second["test_attempt_count"] == 3

    registration = fx.create_registration(
        client, project_id, manufacturer_program=ManufacturerProgram.STANDARD_15Y
    )
    assert registration["registration_state"] == RegistrationState.DRAFT
    assert registration["coverage_years"] is None

    fx.certify_link(client, second["id"])
    assert fx.read_link(client, first["id"])["install_state"] == InstallState.CERTIFIED
    assert fx.read_link(client, second["id"])["install_state"] == InstallState.CERTIFIED
    assert (
        fx.read_registration(client, registration["id"])["registration_state"]
        == RegistrationState.READY
    )

    submitted = fx.submit_registration(client, registration["id"], project_id)
    assert submitted["registration_state"] == RegistrationState.SUBMITTED
    assert submitted["submitted_certified_link_count"] == 2
    assert submitted["coverage_years"] == 10

    project = fx.read_project(client, project_id)
    assert_decimal_equals(project["completeness_pct_strict"], 100.00)
    assert project["warranty_status"] == WarrantyStatus.SUBMITTED


def _two_scheme_projects(client: ApiClient) -> Dict[str, Any]:
    """Two projects on the two labelling schemes, each with a room coded TR01."""
    class_1 = _riverside_project(client)
    room_1 = fx.create_room(client, class_1["id"], room_code="TR01", floor=3)
    class_2 = _riverside_project(
        client,
        name="Riverside Annex Cabling",
        site_code="RVT2",
        plenum_ceiling=False,
        identifier_scheme=IdentifierScheme.TIA_606_CLASS_2,
    )
    room_2 = fx.create_room(client, class_2["id"], room_code="TR01", floor=3)
    cable = _cat6a_cmp(client)
    return {
        "class_1_project_id": class_1["id"],
        "class_1_room_id": room_1["id"],
        "class_2_project_id": class_2["id"],
        "class_2_room_id": room_2["id"],
        "cable_type_id": cable["id"],
    }


def _link_attempt(
    client: ApiClient, scheme: Dict[str, Any], which: str, identifier: str
) -> Any:
    """Attempt a 40-metre link under one of the two projects, returning the raw response."""
    return client.create_link(
        link_payload(
            scheme[f"{which}_project_id"],
            scheme[f"{which}_room_id"],
            scheme["cable_type_id"],
            identifier=identifier,
            application=Application.DATA_HORIZONTAL,
            horizontal_length_m=40.00,
            consolidation_point_stub_m=0,
            patch_cord_allowance_m=2.00,
        ),
        DESIGNER_HEADERS,
    )


def test_the_class_one_scheme_takes_the_room_and_rack_form_only(
    client: ApiClient,
) -> None:
    """TR01-A01 is a valid Class 1 identifier; the prefixed and lower-case forms are not.

    The pattern is selected by the owning project's scheme and matched over the whole
    string, so the floor-and-space prefix a Class 2 job would demand is surplus here and
    is refused. The match is case-sensitive as well as anchored, so the same identifier
    typed in lower case is refused too, even though it reads identically to a technician.

    Design: Corner/calculations/identifier_pattern_is_selected_by_the_owning_projects_scheme
    """
    scheme = _two_scheme_projects(client)
    accepted = validate_success(_link_attempt(client, scheme, "class_1", "TR01-A01"), 201)
    assert accepted["identifier"] == "TR01-A01"

    validate_error(
        _link_attempt(client, scheme, "class_1", "03A-TR01-A01"),
        ERR_IDENTIFIER_FORMAT_INVALID,
        422,
    )
    validate_error(
        _link_attempt(client, scheme, "class_1", "tr01-a01"),
        ERR_IDENTIFIER_FORMAT_INVALID,
        422,
    )


def test_the_class_two_scheme_demands_the_floor_and_space_prefix(
    client: ApiClient,
) -> None:
    """The two projects swap verdicts on the very same two identifier strings.

    A Class 2 job labels its links with a two-digit floor and a space letter in front of
    the room code, so 03A-TR01-A01 is accepted there and the bare TR01-A01 that the Class
    1 job requires is refused. Each project ends up holding exactly one link, which is the
    one its own scheme admitted.

    Design: Corner/calculations/identifier_pattern_is_selected_by_the_owning_projects_scheme
    """
    scheme = _two_scheme_projects(client)
    accepted = validate_success(
        _link_attempt(client, scheme, "class_2", "03A-TR01-A01"), 201
    )
    assert accepted["identifier"] == "03A-TR01-A01"

    validate_error(
        _link_attempt(client, scheme, "class_2", "TR01-A01"),
        ERR_IDENTIFIER_FORMAT_INVALID,
        422,
    )
    validate_success(_link_attempt(client, scheme, "class_1", "TR01-A01"), 201)

    for key in ("class_1_project_id", "class_2_project_id"):
        rows, meta = validate_paginated(
            client.list_links(DESIGNER_HEADERS, params={"project_id": scheme[key]})
        )
        assert meta["total_count"] == 1
        assert len(rows) == 1


def test_the_strict_and_provisional_figures_diverge_over_the_same_three_links(
    client: ApiClient,
) -> None:
    """One certified, one tested and one designed link read 33.33 strict and 66.67 provisional.

    Both percentages are taken over every link of the project whatever its state, so the
    designed drop dilutes both denominators. The strict numerator counts only the
    certified link and the provisional one also counts the link that passed its test but
    was never labelled, which is why the same three rows report two different figures.
    Only the strict figure governs warranty eligibility, and the designed link is priced
    nowhere: the as-built total is the two terminated links alone.

    Design: Corner/calculations/certification_rollup_strict_and_provisional_variants_diverge_on_the_same_links
    """
    scenario = _riverside_scenario(client)
    project_id = scenario["project_id"]
    _certified_link(client, scenario, "TR01-A01", 85.63)

    tested = _terminated_link(client, scenario, "TR01-A02", 40.00)
    fx.file_test(
        client,
        tested["id"],
        test_standard=TestStandard.PERMANENT_LINK,
        tester_model="DSX-8000",
        insertion_loss_db=7.50,
        next_margin_db=3.20,
        return_loss_margin_db=2.10,
        length_measured_m=40.00,
    )
    _design_link(client, scenario, "TR01-A03", 30.00)

    summary = validate_success(
        client.get_certification_summary(project_id, CERTIFIER_HEADERS)
    )
    assert summary["total_link_count"] == 3
    assert summary["certified_link_count"] == 1
    assert summary["failed_link_count"] == 0
    assert_decimal_equals(summary["completeness_pct_strict"], 33.33)
    assert_decimal_equals(summary["completeness_pct_provisional"], 66.67)
    assert summary["warranty_status"] == WarrantyStatus.NOT_ELIGIBLE
    assert_cents(summary["as_built_cost_cents"], 38565)

    assert_completeness(fx.read_project(client, project_id), 33.33, 66.67)

    unlabelled = fx.read_link(client, tested["id"])
    assert unlabelled["install_state"] == InstallState.TESTED_PASS
    assert unlabelled["record_state"] == RecordState.UNLABELED
