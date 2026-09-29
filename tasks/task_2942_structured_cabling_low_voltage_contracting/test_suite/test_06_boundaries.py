"""Threshold-equality and empty-set boundaries: the exact limit is admitted, one
unit of the declared precision beyond it is not.
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from prd_bench_local_runner.testing import validate_error, validate_success

from test_helpers import fixtures as fx
from test_helpers.api_client import ApiClient
from test_helpers.api_errors import ERR_LINK_LENGTH_EXCEEDED
from test_helpers.assertions import assert_cents, assert_decimal_equals
from test_helpers.factories import grounding_payload
from test_helpers.test_users import INSTALLER_HEADERS, INSTALLER_ID, PM_HEADERS
from test_helpers.types import (
    Application,
    GroundingStatus,
    IdentifierScheme,
    InstallState,
    RoomState,
    WarrantyStatus,
)


def _two_links_astride_the_distance_limit(client: ApiClient) -> dict:
    """One link measuring exactly 90.00 m of permanent link and one measuring 90.01 m."""
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
        in_plenum_space=True,
    )
    coordination = fx.create_coordination(client, project["id"])
    fx.confirm_coordination(client, coordination["id"])

    at_limit = fx.create_link(
        client,
        project["id"],
        room["id"],
        cable["id"],
        identifier="TR01-A01",
        horizontal_length_m=90.00,
        consolidation_point_stub_m=0,
        patch_cord_allowance_m=2.00,
    )
    fx.route_link(client, at_limit["id"], segment["id"])
    over_limit = fx.create_link(
        client,
        project["id"],
        room["id"],
        cable["id"],
        identifier="TR01-A02",
        horizontal_length_m=90.01,
        consolidation_point_stub_m=0,
        patch_cord_allowance_m=2.00,
    )
    fx.route_link(client, over_limit["id"], segment["id"])
    return {"at_limit_id": at_limit["id"], "over_limit_id": over_limit["id"]}


def test_a_link_measuring_exactly_ninety_metres_is_pulled(client: ApiClient) -> None:
    """The distance limit rejects on strictly greater, so the exact limit is admitted.

    Both length variants are stored: the permanent link reads 90.00 and the channel
    reads 92.40, and the pull succeeds and advances the install dimension.

    Design: Difficulty/boundary_precision_check/permanent_link_at_ninety_metres_admits_and_ninety_point_zero_one_rejects
    """
    scenario = _two_links_astride_the_distance_limit(client)

    before = fx.read_link(client, scenario["at_limit_id"])
    assert_decimal_equals(before["permanent_link_length_m"], 90.00)
    assert_decimal_equals(before["channel_length_m"], 92.40)

    pulled = validate_success(
        client.pull_link(scenario["at_limit_id"], INSTALLER_HEADERS), 200
    )
    assert pulled["install_state"] == InstallState.PULLED


def test_a_link_one_hundredth_of_a_metre_over_the_limit_is_refused(
    client: ApiClient,
) -> None:
    """90.01 metres is one unit of the declared precision past the limit and is rejected.

    Design: Difficulty/boundary_precision_check/permanent_link_at_ninety_metres_admits_and_ninety_point_zero_one_rejects
    """
    scenario = _two_links_astride_the_distance_limit(client)

    before = fx.read_link(client, scenario["over_limit_id"])
    assert_decimal_equals(before["permanent_link_length_m"], 90.01)
    assert_decimal_equals(before["channel_length_m"], 92.41)

    response = client.pull_link(scenario["over_limit_id"], INSTALLER_HEADERS)
    validate_error(response, ERR_LINK_LENGTH_EXCEEDED, 422)

    after = fx.read_link(client, scenario["over_limit_id"])
    assert after["install_state"] == InstallState.DESIGNED
    assert after["installer_user_id"] is None


def test_the_two_links_differ_only_in_the_hundredth_of_a_metre(client: ApiClient) -> None:
    """The same call on the same catalogue entry and pathway diverges on 0.01 metre alone.

    Design: Difficulty/boundary_precision_check/permanent_link_at_ninety_metres_admits_and_ninety_point_zero_one_rejects
    """
    scenario = _two_links_astride_the_distance_limit(client)
    validate_success(client.pull_link(scenario["at_limit_id"], INSTALLER_HEADERS), 200)
    validate_error(
        client.pull_link(scenario["over_limit_id"], INSTALLER_HEADERS),
        ERR_LINK_LENGTH_EXCEEDED,
        422,
    )

    admitted = fx.read_link(client, scenario["at_limit_id"])
    refused = fx.read_link(client, scenario["over_limit_id"])
    assert admitted["install_state"] == InstallState.PULLED
    assert refused["install_state"] == InstallState.DESIGNED
    assert admitted["cable_type_id"] == refused["cable_type_id"]
    assert_decimal_equals(admitted["patch_cord_allowance_m"], 2.00)
    assert_decimal_equals(refused["patch_cord_allowance_m"], 2.00)


def test_a_project_with_no_links_reports_a_zero_summary(client: ApiClient) -> None:
    """The empty set is a legitimate reading, not a vacuous pass and not a failure.

    A freshly opened project has no links at all, so every derived figure of the
    certification summary reads zero rather than a vacuously complete 100.00.

    Design: Difficulty/boundary_precision_check/zero_link_project_certification_summary_is_the_empty_set_boundary
    """
    project = fx.create_project(
        client,
        name="Riverside Tower Cabling",
        site_code="RVT1",
        plenum_ceiling=True,
        identifier_scheme=IdentifierScheme.TIA_606_CLASS_1,
    )

    summary = validate_success(
        client.get_certification_summary(project["id"], PM_HEADERS), 200
    )
    assert summary["total_link_count"] == 0
    assert summary["certified_link_count"] == 0
    assert_decimal_equals(summary["completeness_pct_strict"], 0.00)
    assert_decimal_equals(summary["completeness_pct_provisional"], 0.00)


def test_the_empty_summary_also_reports_no_money_and_no_warranty(
    client: ApiClient,
) -> None:
    """Both money ledgers read zero and the job is not yet warrantable.

    Design: Difficulty/boundary_precision_check/zero_link_project_certification_summary_is_the_empty_set_boundary
    """
    project = fx.create_project(
        client,
        name="Riverside Tower Cabling",
        site_code="RVT1",
        plenum_ceiling=True,
        identifier_scheme=IdentifierScheme.TIA_606_CLASS_1,
    )

    summary = validate_success(
        client.get_certification_summary(project["id"], PM_HEADERS), 200
    )
    assert_cents(summary["as_built_cost_cents"], 0)
    assert_cents(summary["consumed_mac_cents"], 0)
    assert summary["warranty_status"] == WarrantyStatus.NOT_ELIGIBLE
    assert summary["failed_link_count"] == 0


def _unverified_room(client: ApiClient) -> dict:
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


def test_exactly_five_thousand_milliohms_bonds_the_room(client: ApiClient) -> None:
    """The resistance comparison is inclusive, so the exact ceiling still bonds the room.

    Design: Difficulty/boundary_precision_check/grounding_resistance_at_five_thousand_milliohms_is_the_inclusive_boundary
    """
    scenario = _unverified_room(client)
    assert scenario["room"]["room_state"] == RoomState.ROUGH_IN
    assert scenario["room"]["grounding_status"] == GroundingStatus.UNVERIFIED

    graded = validate_success(
        client.verify_grounding(
            scenario["room"]["id"],
            grounding_payload(ground_resistance_milliohms=5000),
            PM_HEADERS,
        ),
        200,
    )
    assert graded["grounding_status"] == GroundingStatus.COMPLIANT
    assert graded["room_state"] == RoomState.GROUNDED
    assert_decimal_equals(graded["ground_resistance_milliohms"], 5000.00)


def test_one_hundredth_of_a_milliohm_over_the_ceiling_demotes_the_room(
    client: ApiClient,
) -> None:
    """A failing reading is filed as evidence and cycles a bonded room back to rough-in.

    Design: Difficulty/boundary_precision_check/grounding_resistance_at_five_thousand_milliohms_is_the_inclusive_boundary
    """
    scenario = _unverified_room(client)
    original_version = scenario["room"]["version"]
    fx.verify_grounding(client, scenario["room"]["id"], ground_resistance_milliohms=5000)

    graded = validate_success(
        client.verify_grounding(
            scenario["room"]["id"],
            grounding_payload(ground_resistance_milliohms=5000.01),
            PM_HEADERS,
        ),
        200,
    )
    assert graded["grounding_status"] == GroundingStatus.NON_COMPLIANT
    assert graded["room_state"] == RoomState.ROUGH_IN
    assert_decimal_equals(graded["ground_resistance_milliohms"], 5000.01)

    after = fx.read_room(client, scenario["room"]["id"])
    assert after["version"] == original_version + 2
