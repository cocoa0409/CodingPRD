"""The two four-hop cascades: certification driving the roll-up up to warranty
readiness, and condemnation unwinding all of it again.
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from prd_bench_local_runner.testing import get_success_data

from test_helpers import fixtures as fx
from test_helpers.api_client import ApiClient
from test_helpers.assertions import assert_cents, assert_decimal_equals
from test_helpers.test_users import CERTIFIER_ID
from test_helpers.types import (
    Application,
    IdentifierScheme,
    InstallState,
    ManufacturerProgram,
    PathwayState,
    RecordState,
    RegistrationState,
    RouteState,
    TestStandard,
    WarrantyStatus,
)

CONDEMNED_REASON = "Tray crushed by mechanical duct hanger during ceiling close"


def _tested_pass_scenario(client: ApiClient) -> dict:
    """One recorded, cleanly tested link and one DRAFT registration on the project."""
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
    route = fx.route_link(client, link["id"], segment["id"])
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
    return {
        "project_id": project["id"],
        "segment_id": segment["id"],
        "registration_id": registration["id"],
        "link_id": link["id"],
        "route_id": route["id"],
    }


def test_certification_recomputes_the_roll_up_and_flips_warranty_eligibility(
    client: ApiClient,
) -> None:
    """Hops 1 to 3: the sign-off drives the counters and then the eligibility flag.

    Before the call the project reads no certified links, a strict figure of 0.00
    and a NOT_ELIGIBLE warranty. Certifying the one link stamps the certifier on it,
    recomputes the project to a strict and provisional 100.00 with an as-built cost
    of 22705 cents, and only then does warranty_status leave NOT_ELIGIBLE for
    ELIGIBLE.

    Design: Difficulty/transitive_cascade/certify_cascades_to_project_rollup_eligibility_and_registration_ready
    """
    scenario = _tested_pass_scenario(client)
    project_id = scenario["project_id"]

    before = fx.read_project(client, project_id)
    assert before["certified_link_count"] == 0
    assert_decimal_equals(before["completeness_pct_strict"], 0.00)
    assert before["warranty_status"] == WarrantyStatus.NOT_ELIGIBLE

    certified = fx.certify_link(client, scenario["link_id"])
    assert certified["install_state"] == InstallState.CERTIFIED
    assert certified["certifier_user_id"] == CERTIFIER_ID

    after = fx.read_project(client, project_id)
    assert after["total_link_count"] == 1
    assert after["certified_link_count"] == 1
    assert_decimal_equals(after["completeness_pct_strict"], 100.00)
    assert_decimal_equals(after["completeness_pct_provisional"], 100.00)
    assert_cents(after["as_built_cost_cents"], 22705)
    assert after["warranty_status"] == WarrantyStatus.ELIGIBLE


def test_certification_promotes_the_draft_registration_and_pins_the_version(
    client: ApiClient,
) -> None:
    """Hop 4: eligibility promotes the registration and captures the project revision.

    The DRAFT registration is moved to READY by the system, not by a request, and
    its pinned_project_version names the project revision produced by the roll-up
    hop, so the pin matches what the project reports immediately afterwards.

    Design: Difficulty/transitive_cascade/certify_cascades_to_project_rollup_eligibility_and_registration_ready
    """
    scenario = _tested_pass_scenario(client)
    registration_id = scenario["registration_id"]

    draft = fx.read_registration(client, registration_id)
    assert draft["registration_state"] == RegistrationState.DRAFT
    assert draft["pinned_project_version"] is None

    fx.certify_link(client, scenario["link_id"])

    project = fx.read_project(client, scenario["project_id"])
    ready = fx.read_registration(client, registration_id)
    assert ready["registration_state"] == RegistrationState.READY
    assert ready["pinned_project_version"] == project["version"]


def test_condemnation_suspends_the_routing_and_empties_the_fill_ledger(
    client: ApiClient,
) -> None:
    """Hops 1 and 2: the segment closes and gives back exactly what it was carrying.

    Condemning the tray stores the finding and moves it out of SERVICEABLE, and the
    routing that was occupying it is suspended by the system, returning its
    consumed area so the segment reads no occupying routings, no used area and a
    fill ratio of zero.

    Design: Difficulty/transitive_cascade/condemn_cascades_to_route_link_project_and_warranty_revert
    """
    scenario = _tested_pass_scenario(client)
    fx.certify_link(client, scenario["link_id"])

    before = fx.read_segment(client, scenario["segment_id"])
    assert before["occupying_route_count"] == 1
    assert_decimal_equals(before["fill_area_used_sq_mm"], 49.02)

    condemned = fx.condemn_segment(
        client, scenario["segment_id"], condemned_reason=CONDEMNED_REASON
    )
    assert condemned["pathway_state"] == PathwayState.CONDEMNED
    assert condemned["condemned_reason"] == CONDEMNED_REASON
    assert condemned["occupying_route_count"] == 0
    assert_decimal_equals(condemned["fill_area_used_sq_mm"], 0.00)
    assert_decimal_equals(condemned["fill_ratio"], 0.0000, 4)

    route = get_success_data(
        client.get_link_route(scenario["route_id"], fx.DESIGNER_HEADERS)
    )
    assert route["route_state"] == RouteState.SUSPENDED


def test_condemnation_reverts_the_certified_link_and_the_warranty_evidence(
    client: ApiClient,
) -> None:
    """Hops 3 and 4: the link falls back to design and the warranty follows it down.

    The link that lost its only routing is reverted all the way to DESIGNED with its
    record dimension back at UNLABELED and both the installer and the certifier
    cleared, while its test history survives. The project's counters fall to zero,
    warranty_status returns to NOT_ELIGIBLE and the READY registration reverts to
    DRAFT with its pin cleared.

    Design: Difficulty/transitive_cascade/condemn_cascades_to_route_link_project_and_warranty_revert
    """
    scenario = _tested_pass_scenario(client)
    fx.certify_link(client, scenario["link_id"])
    fx.condemn_segment(client, scenario["segment_id"], condemned_reason=CONDEMNED_REASON)

    link = fx.read_link(client, scenario["link_id"])
    assert link["install_state"] == InstallState.DESIGNED
    assert link["record_state"] == RecordState.UNLABELED
    assert link["routed_segment_count"] == 0
    assert link["installer_user_id"] is None
    assert link["certifier_user_id"] is None
    assert link["test_attempt_count"] == 1

    project = fx.read_project(client, scenario["project_id"])
    assert project["total_link_count"] == 1
    assert project["certified_link_count"] == 0
    assert_decimal_equals(project["completeness_pct_strict"], 0.00)
    assert_cents(project["as_built_cost_cents"], 0)
    assert project["warranty_status"] == WarrantyStatus.NOT_ELIGIBLE

    registration = fx.read_registration(client, scenario["registration_id"])
    assert registration["registration_state"] == RegistrationState.DRAFT
    assert registration["pinned_project_version"] is None
