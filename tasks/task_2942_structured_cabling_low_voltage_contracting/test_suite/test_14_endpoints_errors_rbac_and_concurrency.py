"""Endpoint surfaces, the error catalogue, role screening and optimistic concurrency.

The whole surface of an endpoint family is exercised here — creation, single read
and filtered paging — together with the family-specific 404 codes, the two
identity screens of §2.1, the segregation-of-duties bar on certification, and the
three stale-version refusals of §2.7 with their compensating resubmissions.
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from prd_bench_local_runner.testing import (
    validate_error,
    validate_paginated,
    validate_success,
)

from test_helpers import factories as f
from test_helpers import fixtures as fx
from test_helpers.api_client import ApiClient
from test_helpers.api_errors import (
    ERR_CABLE_TYPE_NOT_FOUND,
    ERR_COORDINATION_NOT_FOUND,
    ERR_INVALID_LINK_STATE,
    ERR_INVALID_PROJECT_STATE,
    ERR_INVALID_RECORD_STATE,
    ERR_INVALID_TICKET_STATE,
    ERR_LINK_NOT_FOUND,
    ERR_MAC_TICKET_NOT_FOUND,
    ERR_MARGINAL_TEST_NOT_CERTIFIABLE,
    ERR_PATHWAY_SEGMENT_NOT_FOUND,
    ERR_PROJECT_NOT_FOUND,
    ERR_RACK_ASSIGNMENT_NOT_FOUND,
    ERR_RACK_NOT_FOUND,
    ERR_ROUTE_NOT_FOUND,
    ERR_SEGREGATION_OF_DUTIES,
    ERR_STALE_PATHWAY_VERSION,
    ERR_STALE_PROJECT_VERSION,
    ERR_STALE_RACK_VERSION,
    ERR_TEST_RESULT_NOT_FOUND,
    ERR_TRADE_NOT_COORDINATED,
    ERR_UNAUTHENTICATED,
    ERR_UNAUTHORIZED,
    ERR_WARRANTY_NOT_ELIGIBLE,
    ERR_WARRANTY_PIN_STALE,
    ERR_WARRANTY_REGISTRATION_NOT_FOUND,
)
from test_helpers.assertions import (
    assert_cents,
    assert_decimal_equals,
    assert_fill_ledger,
    assert_immutable_fields,
    assert_rack_ru_identity,
    assert_room_power_identity,
    assert_version_is,
)
from test_helpers.test_users import (
    CERTIFIER_HEADERS,
    CERTIFIER_ID,
    CLIENT_HEADERS,
    DESIGNER_HEADERS,
    EMPTY_ROLE_HEADERS,
    EMPTY_USER_ID_HEADERS,
    INSTALLER_HEADERS,
    INSTALLER_ID,
    MANUFACTURER_HEADERS,
    MISSING_ROLE_HEADERS,
    NO_AUTH_HEADERS,
    PM_HEADERS,
    TESTER_HEADERS,
    TEST_TECHNICIAN_ID,
    UNKNOWN_ROLE_HEADERS,
    headers_for,
)
from test_helpers.types import (
    Application,
    AssignmentState,
    CableCategory,
    GroundingStatus,
    IdentifierScheme,
    InstallState,
    JacketRating,
    ManufacturerProgram,
    Milestone,
    OccupancyStatus,
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
    UserRole,
    WarrantyProgram,
    WarrantyStatus,
)


CLEAN_PASS_TEST = {
    "test_standard": TestStandard.PERMANENT_LINK,
    "tester_model": "FLX-500",
    "insertion_loss_db": 6.00,
    "next_margin_db": 5.00,
    "return_loss_margin_db": 4.00,
    "length_measured_m": 40.00,
}

# A 7.9 mm CAT6A occupies pi * 3.95^2 = 49.02 sq mm of a pathway.
CAT6A_AREA_SQ_MM = 49.02


def _project(client: ApiClient, **overrides) -> dict:
    """The Riverside Tower job, labelling to TIA-606 Class 1 under a plenum ceiling."""
    return fx.create_project(
        client,
        name="Riverside Tower Cabling",
        site_code="RVT1",
        plenum_ceiling=True,
        identifier_scheme=IdentifierScheme.TIA_606_CLASS_1,
        **overrides,
    )


def _room(client: ApiClient, project_id: str) -> dict:
    return fx.create_room(
        client,
        project_id,
        room_code="TR01",
        floor=3,
        branch_circuit_amps=20,
        ups_capacity_va=3000,
    )


def _bond(client: ApiClient, room_id: str) -> dict:
    """A compliant bonding measurement: busbar present, #6 AWG, exactly 5000 milliohms."""
    return fx.verify_grounding(
        client,
        room_id,
        tgb_installed=True,
        bonding_conductor_awg=6,
        ground_resistance_milliohms=5000,
    )


def _cable(client: ApiClient) -> dict:
    """A plenum-rated 7.9 mm CAT6A approved for horizontal data only."""
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


def _tray(client: ApiClient, project_id: str) -> dict:
    """Tray PS-A: 20000 sq mm of usable area running through the plenum cavity."""
    return fx.create_segment(
        client,
        project_id,
        segment_code="PS-A",
        pathway_type=PathwayType.CABLE_TRAY,
        usable_area_sq_mm=20000.0,
        length_m=40.0,
        bend_count=0,
        in_plenum_space=True,
    )


def _link(client: ApiClient, site: dict, identifier: str = "TR01-A01") -> dict:
    """A 40.00 m horizontal drop with a 2.00 m cord allowance and no consolidation stub."""
    return fx.create_link(
        client,
        site["project_id"],
        site["room_id"],
        site["cable_type_id"],
        identifier=identifier,
        application=Application.DATA_HORIZONTAL,
        horizontal_length_m=40.00,
        consolidation_point_stub_m=0,
        patch_cord_allowance_m=2.00,
    )


def _site(client: ApiClient, bonded: bool = True, **project_overrides) -> dict:
    """Project RVT1 with room TR01, the CAT6A catalogue entry, tray PS-A and a
    confirmed CEILING / PATHWAY_ROUGH_IN milestone."""
    project = _project(client, **project_overrides)
    room = _room(client, project["id"])
    if bonded:
        _bond(client, room["id"])
    cable = _cable(client)
    segment = _tray(client, project["id"])
    coordination = fx.create_coordination(
        client,
        project["id"],
        trade=Trade.CEILING,
        milestone=Milestone.PATHWAY_ROUGH_IN,
    )
    fx.confirm_coordination(client, coordination["id"], confirmed_date="2026-08-05")
    return {
        "project": project,
        "project_id": project["id"],
        "room_id": room["id"],
        "cable_type_id": cable["id"],
        "segment_id": segment["id"],
        "coordination_id": coordination["id"],
    }


def _recorded_link(client: ApiClient, site: dict, identifier: str = "TR01-A01") -> dict:
    """A link routed through PS-A, pulled, terminated, labelled and filed on E-501."""
    link = _link(client, site, identifier=identifier)
    fx.route_link(client, link["id"], site["segment_id"], sequence_index=1)
    fx.pull_link(client, link["id"])
    fx.terminate_link(client, link["id"])
    fx.label_link(client, link["id"], identifier)
    return fx.record_link(client, link["id"], drawing_sheet_ref="E-501")


def _tested_link(client: ApiClient, site: dict, identifier: str = "TR01-A01") -> dict:
    """A recorded link carrying one clean permanent-link PASS."""
    link = _recorded_link(client, site, identifier=identifier)
    fx.file_test(client, link["id"], **CLEAN_PASS_TEST)
    return fx.read_link(client, link["id"])


# ─── endpoints ───────────────────────────────────────────────────────────────


def test_cable_type_catalogue_reads_back_exactly_what_was_created(
    client: ApiClient,
) -> None:
    """Three catalogue entries are registered and then read back one at a time and by
    category. A cable type is written once and never edited, so it exposes only its
    identity and creation stamp, and the category filter must page over the two CAT6A
    rows while reporting the pre-pagination count and leaving the fibre row out.

    Design: Corner/endpoints/cable_type_crud_reads_back_exactly_what_was_created
    """
    ct1 = validate_success(
        client.create_cable_type(
            f.cable_type_payload(
                category=CableCategory.CAT6A,
                jacket_rating=JacketRating.CMP,
                outer_diameter_mm=7.9,
                max_channel_length_m=100.0,
                shielded=False,
                cost_per_meter_cents=150,
                applications=[Application.DATA_HORIZONTAL],
            ),
            DESIGNER_HEADERS,
        ),
        201,
    )
    ct2 = validate_success(
        client.create_cable_type(
            f.cable_type_payload(
                category=CableCategory.CAT6A,
                jacket_rating=JacketRating.CMR,
                outer_diameter_mm=8.5,
                max_channel_length_m=100.0,
                shielded=True,
                cost_per_meter_cents=210,
                applications=[Application.DATA_HORIZONTAL, Application.WAP],
            ),
            DESIGNER_HEADERS,
        ),
        201,
    )
    ct3 = validate_success(
        client.create_cable_type(
            f.cable_type_payload(
                category=CableCategory.OM4_MMF,
                jacket_rating=JacketRating.CMP,
                outer_diameter_mm=2.0,
                max_channel_length_m=550.0,
                shielded=False,
                cost_per_meter_cents=320,
                applications=[Application.BACKBONE],
            ),
            DESIGNER_HEADERS,
        ),
        201,
    )

    single = validate_success(client.get_cable_type(ct2["id"], DESIGNER_HEADERS), 200)
    assert single["id"] == ct2["id"]
    assert single["category"] == CableCategory.CAT6A
    assert single["jacket_rating"] == JacketRating.CMR
    assert_decimal_equals(single["outer_diameter_mm"], 8.5)
    assert single["shielded"] is True
    assert_cents(single["cost_per_meter_cents"], 210)
    assert single["applications"] == [
        Application.DATA_HORIZONTAL,
        Application.WAP,
    ]
    assert_decimal_equals(single["cross_section_area_sq_mm"], 56.75)
    assert_immutable_fields(single)

    first_page, first_meta = validate_paginated(
        client.list_cable_types(
            DESIGNER_HEADERS,
            params={"category": CableCategory.CAT6A, "limit": 1, "offset": 0},
        )
    )
    assert first_meta["total_count"] == 2
    assert first_meta["has_more"] is True
    assert first_meta["limit"] == 1
    assert first_meta["offset"] == 0
    assert [row["id"] for row in first_page] == [ct1["id"]]

    second_page, second_meta = validate_paginated(
        client.list_cable_types(
            DESIGNER_HEADERS,
            params={"category": CableCategory.CAT6A, "limit": 1, "offset": 1},
        )
    )
    assert second_meta["total_count"] == 2
    assert second_meta["has_more"] is False
    assert second_meta["offset"] == 1
    assert [row["id"] for row in second_page] == [ct2["id"]]

    paged_ids = [row["id"] for row in first_page + second_page]
    assert ct3["id"] not in paged_ids
    for row in first_page + second_page:
        assert row["category"] == CableCategory.CAT6A
        assert "version" not in row
        assert "updated_at" not in row


def test_routing_a_link_needs_both_named_ends_to_exist(client: ApiClient) -> None:
    """A routing joins one link to one pathway segment, and each end is resolved on its
    own. Breaking the link end and then the segment end yields two different 404 codes,
    and once both ends are real the association is written and the tray's fill ledger
    moves exactly once — neither refusal may have touched it.

    Design: Corner/endpoints/the_route_link_endpoint_needs_both_ends_to_exist
    """
    project = _project(client)
    room = _room(client, project["id"])
    cable = _cable(client)
    segment = _tray(client, project["id"])
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
    segment_v1 = segment["version"]

    validate_error(
        client.create_link_route(
            f.link_route_payload(
                "00000000-0000-4000-8000-00000000dead", segment["id"], segment_v1
            ),
            DESIGNER_HEADERS,
        ),
        ERR_LINK_NOT_FOUND,
        404,
    )
    validate_error(
        client.create_link_route(
            f.link_route_payload(
                link["id"], "00000000-0000-4000-8000-00000000beef", segment_v1
            ),
            DESIGNER_HEADERS,
        ),
        ERR_PATHWAY_SEGMENT_NOT_FOUND,
        404,
    )

    route = validate_success(
        client.create_link_route(
            f.link_route_payload(link["id"], segment["id"], segment_v1),
            DESIGNER_HEADERS,
        ),
        201,
    )
    assert route["link_id"] == link["id"]
    assert route["pathway_segment_id"] == segment["id"]
    assert route["sequence_index"] == 1
    assert route["route_state"] == RouteState.OCCUPYING

    after = fx.read_segment(client, segment["id"])
    assert after["occupying_route_count"] == 1
    assert_version_is(after, 2, "pathway segment")
    assert_decimal_equals(after["fill_area_used_sq_mm"], CAT6A_AREA_SQ_MM)


def test_energizing_a_room_demands_a_released_electrical_milestone(
    client: ApiClient,
) -> None:
    """Switching on rack power waits for the electrical contractor to have actually
    released the panel: a merely confirmed POWER_ENERGIZE milestone is not enough, so
    the same payload-free call is refused twice and admitted only after the release.
    The room's power ledger is empty throughout, so nothing but the milestone moved.

    Design: Corner/endpoints/energizing_a_room_enforces_its_electrical_milestone
    """
    project = _project(client)
    room = _room(client, project["id"])
    grounded = _bond(client, room["id"])
    assert grounded["grounding_status"] == GroundingStatus.COMPLIANT
    assert grounded["room_state"] == RoomState.GROUNDED

    coordination = fx.create_coordination(
        client,
        project["id"],
        trade=Trade.ELECTRICAL,
        milestone=Milestone.POWER_ENERGIZE,
    )

    validate_error(
        client.energize_room(room["id"], PM_HEADERS), ERR_TRADE_NOT_COORDINATED, 409
    )

    fx.confirm_coordination(client, coordination["id"], confirmed_date="2026-08-14")
    validate_error(
        client.energize_room(room["id"], PM_HEADERS), ERR_TRADE_NOT_COORDINATED, 409
    )

    still_grounded = fx.read_room(client, room["id"])
    assert still_grounded["room_state"] == RoomState.GROUNDED
    assert still_grounded["power_load_va"] == 0
    assert still_grounded["ups_capacity_va"] == 3000
    assert_room_power_identity(still_grounded)

    fx.release_coordination(client, coordination["id"])
    energized = validate_success(client.energize_room(room["id"], PM_HEADERS), 200)
    assert energized["room_state"] == RoomState.ENERGIZED
    assert energized["power_load_va"] == 0
    assert energized["ups_capacity_va"] == 3000
    assert_room_power_identity(energized)


def test_the_certification_report_recomputes_the_graded_figures_of_the_latest_test(
    client: ApiClient,
) -> None:
    """The per-link report is assembled from the link's latest measurement, so the graded
    length of a permanent-link test, the insertion-loss budget it implies and the worst of
    the two margins are identical either side of the sign-off. Only the certifier's
    identity appears between the two reads, and the owner's representative may read both.

    Design: Corner/endpoints/the_certification_report_recomputes_the_graded_figures_of_the_latest_test
    """
    site = _site(client)
    link = _tested_link(client, site)

    before = validate_success(
        client.get_certification_report(link["id"], CLIENT_HEADERS), 200
    )
    assert before["link_id"] == link["id"]
    assert before["identifier"] == "TR01-A01"
    assert before["install_state"] == InstallState.TESTED_PASS
    assert before["record_state"] == RecordState.RECORDED
    assert before["test_attempt_count"] == 1
    assert before["latest_test_outcome"] == TestOutcome.PASS
    assert before["latest_test_standard"] == TestStandard.PERMANENT_LINK
    assert_decimal_equals(before["graded_length_m"], 40.00)
    assert_decimal_equals(before["insertion_loss_budget_db"], 8.00)
    assert_decimal_equals(before["worst_margin_db"], 4.00)
    assert before["failure_reason"] is None
    assert before["certifier_user_id"] is None
    assert "version" not in before

    certified = validate_success(
        client.certify_link(link["id"], CERTIFIER_HEADERS), 200
    )
    assert certified["install_state"] == InstallState.CERTIFIED

    after = validate_success(
        client.get_certification_report(link["id"], CLIENT_HEADERS), 200
    )
    assert after["install_state"] == InstallState.CERTIFIED
    assert after["certifier_user_id"] == CERTIFIER_ID
    assert after["latest_test_standard"] == TestStandard.PERMANENT_LINK
    assert_decimal_equals(after["graded_length_m"], 40.00)
    assert_decimal_equals(after["insertion_loss_budget_db"], 8.00)
    assert_decimal_equals(after["worst_margin_db"], 4.00)
    assert after["test_attempt_count"] == 1
    assert "version" not in after


def test_warranty_submission_and_decision_follow_eligibility_and_the_pin(
    client: ApiClient,
) -> None:
    """Two registrations of the same job are promoted together by the certification that
    makes the project eligible, but only one of them can be submitted: the first
    submission takes the job out of ELIGIBLE, so the second is refused on eligibility even
    though its own state and version are current. Declaring occupancy afterwards moves the
    project past the pin the manufacturer was asked to decide on, which blocks a
    registration decision while a rejection — which carries no pin — still lands.

    Design: Corner/endpoints/warranty_submission_and_decision_are_conditional_on_eligibility_and_the_pin
    """
    site = _site(client, warranty_program=WarrantyProgram.EXTENDED_25Y)
    link = _tested_link(client, site)

    reg_a = fx.create_registration(
        client, site["project_id"], manufacturer_program=ManufacturerProgram.EXTENDED_25Y
    )
    reg_b = fx.create_registration(
        client, site["project_id"], manufacturer_program=ManufacturerProgram.EXTENDED_25Y
    )
    assert reg_a["registration_state"] == RegistrationState.DRAFT
    assert reg_b["registration_state"] == RegistrationState.DRAFT

    fx.certify_link(client, link["id"])

    project = fx.read_project(client, site["project_id"])
    pv1 = project["version"]
    assert project["warranty_status"] == WarrantyStatus.ELIGIBLE
    for registration_id in (reg_a["id"], reg_b["id"]):
        ready = fx.read_registration(client, registration_id)
        assert ready["registration_state"] == RegistrationState.READY
        assert ready["pinned_project_version"] == pv1

    submitted = validate_success(
        client.submit_warranty_registration(
            reg_a["id"], f.warranty_submit_payload(pv1), PM_HEADERS
        ),
        200,
    )
    assert submitted["registration_state"] == RegistrationState.SUBMITTED
    assert submitted["submitted_certified_link_count"] == 1
    assert submitted["coverage_years"] == 25

    pv2 = fx.project_version(client, site["project_id"])
    validate_error(
        client.submit_warranty_registration(
            reg_b["id"], f.warranty_submit_payload(pv2), PM_HEADERS
        ),
        ERR_WARRANTY_NOT_ELIGIBLE,
        409,
    )

    fx.release_coordination(client, site["coordination_id"])
    occupied = validate_success(
        client.declare_occupancy(site["project_id"], f.occupancy_payload(), PM_HEADERS),
        200,
    )
    assert occupied["occupancy_status"] == OccupancyStatus.OCCUPIED
    assert occupied["version"] > submitted["pinned_project_version"]

    validate_error(
        client.decide_warranty_registration(
            reg_a["id"],
            f.warranty_register_decision_payload(registration_number="CM-2026-0001"),
            MANUFACTURER_HEADERS,
        ),
        ERR_WARRANTY_PIN_STALE,
        409,
    )
    assert (
        fx.read_registration(client, reg_a["id"])["registration_state"]
        == RegistrationState.SUBMITTED
    )

    rejected = validate_success(
        client.decide_warranty_registration(
            reg_a["id"],
            f.warranty_reject_decision_payload(
                rejection_reason="Photo package incomplete"
            ),
            MANUFACTURER_HEADERS,
        ),
        200,
    )
    assert rejected["registration_state"] == RegistrationState.REJECTED
    assert rejected["rejection_reason"] == "Photo package incomplete"

    reopened = validate_success(
        client.reopen_warranty_registration(reg_a["id"], PM_HEADERS), 200
    )
    assert reopened["registration_state"] == RegistrationState.DRAFT
    assert reopened["pinned_project_version"] is None
    assert reopened["coverage_years"] is None
    assert (
        fx.read_project(client, site["project_id"])["warranty_status"]
        == WarrantyStatus.ELIGIBLE
    )


# ─── errors ──────────────────────────────────────────────────────────────────

_ABSENT_PROJECT = "00000000-0000-4000-8000-000000000001"
_ABSENT_RACK = "00000000-0000-4000-8000-000000000002"
_ABSENT_ASSIGNMENT = "00000000-0000-4000-8000-000000000003"
_ABSENT_CABLE_TYPE = "00000000-0000-4000-8000-000000000004"
_ABSENT_ROUTE = "00000000-0000-4000-8000-000000000005"
_ABSENT_TEST_RESULT = "00000000-0000-4000-8000-000000000006"
_ABSENT_REGISTRATION = "00000000-0000-4000-8000-000000000007"
_ABSENT_TICKET = "00000000-0000-4000-8000-000000000008"
_ABSENT_COORDINATION = "00000000-0000-4000-8000-000000000009"
_ABSENT_CATALOGUE_ENTRY = "00000000-0000-4000-8000-00000000000a"


def test_every_resource_family_reports_its_own_not_found_code(
    client: ApiClient,
) -> None:
    """A well-formed identifier that names nothing is answered by the code belonging to
    the family that was addressed, so a project, a rack, an elevation placement, a
    catalogue entry, a routing, a test result, a warranty registration, a
    moves-adds-changes ticket and a trade coordination each report their own miss rather
    than one shared code. The same discrimination applies to an identifier carried in a
    request body: naming an absent catalogue entry when designing a link is the catalogue
    entry's miss, and no link is created.

    Design: Corner/errors/every_resource_family_reports_its_own_not_found_code
    """
    validate_error(
        client.get_project(_ABSENT_PROJECT, PM_HEADERS), ERR_PROJECT_NOT_FOUND, 404
    )
    validate_error(
        client.get_rack(_ABSENT_RACK, PM_HEADERS), ERR_RACK_NOT_FOUND, 404
    )
    validate_error(
        client.get_rack_unit_assignment(_ABSENT_ASSIGNMENT, PM_HEADERS),
        ERR_RACK_ASSIGNMENT_NOT_FOUND,
        404,
    )
    validate_error(
        client.get_cable_type(_ABSENT_CABLE_TYPE, PM_HEADERS),
        ERR_CABLE_TYPE_NOT_FOUND,
        404,
    )
    validate_error(
        client.get_link_route(_ABSENT_ROUTE, PM_HEADERS), ERR_ROUTE_NOT_FOUND, 404
    )
    validate_error(
        client.get_test_result(_ABSENT_TEST_RESULT, PM_HEADERS),
        ERR_TEST_RESULT_NOT_FOUND,
        404,
    )
    validate_error(
        client.get_warranty_registration(_ABSENT_REGISTRATION, PM_HEADERS),
        ERR_WARRANTY_REGISTRATION_NOT_FOUND,
        404,
    )
    validate_error(
        client.get_mac_ticket(_ABSENT_TICKET, PM_HEADERS), ERR_MAC_TICKET_NOT_FOUND, 404
    )
    validate_error(
        client.get_trade_coordination(_ABSENT_COORDINATION, PM_HEADERS),
        ERR_COORDINATION_NOT_FOUND,
        404,
    )

    site = _site(client)
    validate_error(
        client.create_link(
            f.link_payload(
                site["project_id"],
                site["room_id"],
                _ABSENT_CATALOGUE_ENTRY,
                identifier="TR01-A01",
                application=Application.DATA_HORIZONTAL,
                horizontal_length_m=40.00,
                consolidation_point_stub_m=0,
                patch_cord_allowance_m=2.00,
            ),
            DESIGNER_HEADERS,
        ),
        ERR_CABLE_TYPE_NOT_FOUND,
        404,
    )
    assert fx.read_project(client, site["project_id"])["total_link_count"] == 0


def test_recording_a_link_before_it_is_labelled_reports_the_record_dimension_error(
    client: ApiClient,
) -> None:
    """A link carries two independent state dimensions, and a refusal names the dimension
    that actually blocks the call. Filing the as-built sheet for a drop that has never
    been labelled is refused on the record dimension, while applying the label to that
    same drop — whose record dimension is perfectly ready for it — is refused on the
    installation dimension, because no cable has been landed yet.

    Design: Corner/errors/recording_a_link_before_it_is_labelled_reports_the_record_dimension_error
    """
    site = _site(client)
    link = _link(client, site)
    assert link["install_state"] == InstallState.DESIGNED
    assert link["record_state"] == RecordState.UNLABELED
    assert link["drawing_sheet_ref"] is None
    assert link["applied_identifier"] is None

    validate_error(
        client.record_link(link["id"], f.record_payload(), DESIGNER_HEADERS),
        ERR_INVALID_RECORD_STATE,
        409,
    )
    validate_error(
        client.label_link(
            link["id"], f.label_payload("TR01-A01"), INSTALLER_HEADERS
        ),
        ERR_INVALID_LINK_STATE,
        409,
    )

    unchanged = fx.read_link(client, link["id"])
    assert unchanged["install_state"] == InstallState.DESIGNED
    assert unchanged["record_state"] == RecordState.UNLABELED
    assert unchanged["drawing_sheet_ref"] is None
    assert unchanged["applied_identifier"] is None
    assert_version_is(unchanged, link["version"], "link")


def test_a_marginal_pass_moves_the_link_but_cannot_be_certified(
    client: ApiClient,
) -> None:
    """A crosstalk margin of three tenths of a decibel sits inside the field tester's own
    accuracy band, so the drop is advanced as tested but the certifier is turned away with
    the marginal code rather than a generic state refusal. A clean retest of the same drop
    replaces the marginal evidence and the identical signature is then accepted, while both
    tester visits remain on file as separate immutable results.

    Design: Corner/errors/a_marginal_pass_moves_the_link_but_cannot_be_certified
    """
    site = _site(client)
    link = _recorded_link(client, site)

    marginal = fx.file_test(
        client,
        link["id"],
        test_standard=TestStandard.PERMANENT_LINK,
        tester_model="FLX-500",
        insertion_loss_db=6.00,
        next_margin_db=0.30,
        return_loss_margin_db=2.00,
        length_measured_m=40.00,
    )
    assert marginal["outcome"] == TestOutcome.PASS_ASTERISK
    assert marginal["failure_reason"] is None
    assert_decimal_equals(marginal["worst_margin_db"], 0.30)
    assert_decimal_equals(marginal["insertion_loss_budget_db"], 8.00)

    tested = fx.read_link(client, link["id"])
    assert tested["install_state"] == InstallState.TESTED_PASS
    assert tested["latest_test_outcome"] == TestOutcome.PASS_ASTERISK
    assert tested["test_attempt_count"] == 1

    validate_error(
        client.certify_link(link["id"], CERTIFIER_HEADERS),
        ERR_MARGINAL_TEST_NOT_CERTIFIABLE,
        409,
    )
    barred = fx.read_link(client, link["id"])
    assert barred["install_state"] == InstallState.TESTED_PASS
    assert barred["certifier_user_id"] is None

    clean = fx.file_test(
        client,
        link["id"],
        test_standard=TestStandard.PERMANENT_LINK,
        tester_model="FLX-500",
        insertion_loss_db=6.00,
        next_margin_db=4.00,
        return_loss_margin_db=4.00,
        length_measured_m=40.00,
    )
    assert clean["outcome"] == TestOutcome.PASS

    retested = fx.read_link(client, link["id"])
    assert retested["latest_test_outcome"] == TestOutcome.PASS
    assert retested["test_attempt_count"] == 2

    certified = validate_success(
        client.certify_link(link["id"], CERTIFIER_HEADERS), 200
    )
    assert certified["install_state"] == InstallState.CERTIFIED
    assert certified["certifier_user_id"] == CERTIFIER_ID

    rows, meta = validate_paginated(
        client.list_test_results(TESTER_HEADERS, params={"link_id": link["id"]})
    )
    assert meta["total_count"] == 2
    assert [row["outcome"] for row in rows] == [
        TestOutcome.PASS_ASTERISK,
        TestOutcome.PASS,
    ]


def test_terminal_states_lock_the_project_and_the_ticket(client: ApiClient) -> None:
    """Handover happens once: an owner who declares occupancy on a building already handed
    over is refused on the project's own state, and the job is left exactly as it was.
    A rejected moves-adds-changes ticket is equally final — it can be neither rejected a
    second time nor pulled back into scheduling — and because rejection never touched the
    budget ledger the job's consumed spend is still nil.

    Design: Corner/errors/terminal_states_lock_the_project_and_the_ticket
    """
    site = _site(client)
    link = _tested_link(client, site)
    fx.certify_link(client, link["id"])
    fx.release_coordination(client, site["coordination_id"])

    occupied = validate_success(
        client.declare_occupancy(site["project_id"], f.occupancy_payload(), PM_HEADERS),
        200,
    )
    assert occupied["occupancy_status"] == OccupancyStatus.OCCUPIED

    validate_error(
        client.declare_occupancy(site["project_id"], f.occupancy_payload(), PM_HEADERS),
        ERR_INVALID_PROJECT_STATE,
        409,
    )
    still_occupied = fx.read_project(client, site["project_id"])
    assert still_occupied["occupancy_status"] == OccupancyStatus.OCCUPIED
    assert_version_is(still_occupied, occupied["version"], "project")

    ticket = fx.create_ticket(
        client,
        site["project_id"],
        link["id"],
        site["room_id"],
        ticket_type=TicketType.MOVE,
        labor_hours_estimate=2.0,
        expedite_requested=False,
    )
    assert ticket["ticket_state"] == TicketState.SUBMITTED

    rejected = validate_success(
        client.reject_mac_ticket(ticket["id"], PM_HEADERS), 200
    )
    assert rejected["ticket_state"] == TicketState.REJECTED
    assert rejected["estimated_billed_cents"] is None
    assert_version_is(rejected, 2, "ticket")

    validate_error(
        client.reject_mac_ticket(ticket["id"], PM_HEADERS),
        ERR_INVALID_TICKET_STATE,
        409,
    )
    validate_error(
        client.schedule_mac_ticket(ticket["id"], f.schedule_payload(), PM_HEADERS),
        ERR_INVALID_TICKET_STATE,
        409,
    )

    locked = fx.read_ticket(client, ticket["id"])
    assert locked["ticket_state"] == TicketState.REJECTED
    assert locked["scheduled_window_start"] is None
    assert locked["scheduled_window_end"] is None
    assert_version_is(locked, 2, "ticket")
    assert_cents(fx.read_project(client, site["project_id"])["consumed_mac_cents"], 0)


# ─── rbac ────────────────────────────────────────────────────────────────────


def test_peer_roles_cannot_reach_each_others_exclusive_operations(
    client: ApiClient,
) -> None:
    """The trades on a cabling job hold disjoint authority: the installer does not lay out
    the design, the design engineer does not pull cable, the certifier does not run the
    field tester and the test technician does not sign the certificate. Each of those four
    crossings is turned away on authority alone, while the one operation the standard
    genuinely shares — filing the as-built sheet — is open to the owner's manager as well
    as to the design engineer.

    Design: Corner/rbac/peer_roles_cannot_reach_each_others_exclusive_operations
    """
    site = _site(client)

    validate_error(
        client.create_link(
            f.link_payload(
                site["project_id"],
                site["room_id"],
                site["cable_type_id"],
                identifier="TR01-A01",
                application=Application.DATA_HORIZONTAL,
                horizontal_length_m=40.00,
                consolidation_point_stub_m=0,
                patch_cord_allowance_m=2.00,
            ),
            INSTALLER_HEADERS,
        ),
        ERR_UNAUTHORIZED,
        403,
    )

    link = _link(client, site)
    fx.route_link(client, link["id"], site["segment_id"], sequence_index=1)

    validate_error(
        client.pull_link(link["id"], DESIGNER_HEADERS), ERR_UNAUTHORIZED, 403
    )
    fx.pull_link(client, link["id"])
    fx.terminate_link(client, link["id"])

    validate_error(
        client.create_test_result(
            f.test_result_payload(link["id"], **CLEAN_PASS_TEST), CERTIFIER_HEADERS
        ),
        ERR_UNAUTHORIZED,
        403,
    )
    fx.file_test(client, link["id"], **CLEAN_PASS_TEST)
    fx.label_link(client, link["id"], "TR01-A01")

    validate_error(
        client.certify_link(link["id"], TESTER_HEADERS), ERR_UNAUTHORIZED, 403
    )

    recorded = validate_success(
        client.record_link(link["id"], f.record_payload(drawing_sheet_ref="E-501"), PM_HEADERS),
        200,
    )
    assert recorded["record_state"] == RecordState.RECORDED
    assert recorded["drawing_sheet_ref"] == "E-501"

    _, meta = validate_paginated(
        client.list_links(PM_HEADERS, params={"project_id": site["project_id"]})
    )
    assert meta["total_count"] == 1


def test_an_unauthenticated_request_cannot_reach_the_role_check(
    client: ApiClient,
) -> None:
    """Identity is settled before authority is weighed, so a caller who supplies no
    identity, a blank identity or a role nobody on the job holds is refused as
    unauthenticated rather than as unauthorized — even when opening a project, which only
    the manager may do. The same screen also runs ahead of existence, so a nameless
    request for a project that does not exist is answered on identity and not as a miss.

    Design: Corner/rbac/an_unauthenticated_request_cannot_reach_the_role_check
    """
    for headers in (
        NO_AUTH_HEADERS,
        MISSING_ROLE_HEADERS,
        EMPTY_ROLE_HEADERS,
        EMPTY_USER_ID_HEADERS,
        UNKNOWN_ROLE_HEADERS,
    ):
        validate_error(
            client.create_project(
                f.project_payload(
                    name="Riverside Tower Cabling",
                    plenum_ceiling=True,
                    identifier_scheme=IdentifierScheme.TIA_606_CLASS_1,
                ),
                headers,
            ),
            ERR_UNAUTHENTICATED,
            401,
        )

    validate_error(
        client.get_project(_ABSENT_PROJECT, NO_AUTH_HEADERS), ERR_UNAUTHENTICATED, 401
    )

    project = validate_success(
        client.create_project(
            f.project_payload(
                name="Riverside Tower Cabling",
                site_code="RVT1",
                plenum_ceiling=True,
                identifier_scheme=IdentifierScheme.TIA_606_CLASS_1,
            ),
            PM_HEADERS,
        ),
        201,
    )
    assert project["site_code"] == "RVT1"

    _, meta = validate_paginated(client.list_projects(PM_HEADERS))
    assert meta["total_count"] == 1


def test_certification_is_barred_to_the_installer_and_to_the_tester(
    client: ApiClient,
) -> None:
    """Holding the certifier's role is not enough: the signature must come from someone who
    neither punched down the drop nor ran the tester on it. Both coincidences are refused on
    segregation of duties with the drop left unsigned, and only a third person completes the
    certification and carries the job to a full strict completeness.

    Design: Corner/rbac/certification_is_barred_to_the_installer_and_to_the_tester
    """
    site = _site(client)
    link = _tested_link(client, site)
    assert link["installer_user_id"] == INSTALLER_ID

    for impostor in (INSTALLER_ID, TEST_TECHNICIAN_ID):
        validate_error(
            client.certify_link(
                link["id"], headers_for(UserRole.CERTIFIER, user_id=impostor)
            ),
            ERR_SEGREGATION_OF_DUTIES,
            403,
        )
        barred = fx.read_link(client, link["id"])
        assert barred["install_state"] == InstallState.TESTED_PASS
        assert barred["certifier_user_id"] is None

    certified = validate_success(
        client.certify_link(
            link["id"], headers_for(UserRole.CERTIFIER, user_id=CERTIFIER_ID)
        ),
        200,
    )
    assert certified["install_state"] == InstallState.CERTIFIED
    assert certified["certifier_user_id"] == CERTIFIER_ID

    project = fx.read_project(client, site["project_id"])
    assert project["certified_link_count"] == 1
    assert_decimal_equals(project["completeness_pct_strict"], 100.00)


# ─── cross_cutting_complexity_layers ─────────────────────────────────────────


def test_a_stale_segment_version_blocks_the_second_route(client: ApiClient) -> None:
    """Two drops are laid out against the same tray from the same drawing revision. The
    first routing consumes tray area and moves the tray on, so the second engineer is
    working from a revision that no longer describes the fill, and the routing is refused
    on the version rather than silently double-counting. The tray is untouched by the
    refusal, and re-reading it before resubmitting admits the identical routing.

    Design: Corner/cross_cutting_complexity_layers/a_stale_segment_version_blocks_the_second_route
    """
    site = _site(client)
    first = _link(client, site, identifier="TR01-A01")
    second = _link(client, site, identifier="TR01-A02")

    observed = fx.read_segment(client, site["segment_id"])
    assert_version_is(observed, 1, "segment")
    assert observed["occupying_route_count"] == 0

    route = validate_success(
        client.create_link_route(
            f.link_route_payload(
                first["id"], site["segment_id"], observed["version"], sequence_index=1
            ),
            DESIGNER_HEADERS,
        ),
        201,
    )
    assert route["route_state"] == RouteState.OCCUPYING
    assert_decimal_equals(route["consumed_area_sq_mm"], CAT6A_AREA_SQ_MM)

    validate_error(
        client.create_link_route(
            f.link_route_payload(
                second["id"], site["segment_id"], observed["version"], sequence_index=1
            ),
            DESIGNER_HEADERS,
        ),
        ERR_STALE_PATHWAY_VERSION,
        412,
    )

    untouched = fx.read_segment(client, site["segment_id"])
    assert_version_is(untouched, 2, "segment")
    assert untouched["occupying_route_count"] == 1
    assert_decimal_equals(untouched["fill_area_used_sq_mm"], CAT6A_AREA_SQ_MM)
    assert fx.read_link(client, second["id"])["routed_segment_count"] == 0

    admitted = validate_success(
        client.create_link_route(
            f.link_route_payload(
                second["id"], site["segment_id"], untouched["version"], sequence_index=1
            ),
            DESIGNER_HEADERS,
        ),
        201,
    )
    assert admitted["route_state"] == RouteState.OCCUPYING

    reconciled = fx.read_segment(client, site["segment_id"])
    assert_version_is(reconciled, 3, "segment")
    assert reconciled["occupying_route_count"] == 2
    assert_decimal_equals(reconciled["fill_area_used_sq_mm"], 2 * CAT6A_AREA_SQ_MM)
    assert_fill_ledger(reconciled)


def test_a_stale_rack_version_blocks_the_second_assignment(client: ApiClient) -> None:
    """An elevation drawing is marked up twice from one printed copy. The first placement
    consumes rack units and room power, so the second placement — which does not even
    overlap the first, and which the room has ample power for — is still refused on the
    revision it was drawn against. Neither the rack ledger nor the room's power ledger
    moves on the refusal, and the placement lands once the current revision is quoted.

    Design: Corner/cross_cutting_complexity_layers/a_stale_rack_version_blocks_the_second_assignment
    """
    site = _site(client)
    rack = fx.create_rack(client, site["room_id"], rack_code="A", total_ru=42)
    assert_version_is(rack, 1, "rack")
    assert rack["occupied_ru"] == 0
    assert rack["available_ru"] == 42

    placed = validate_success(
        client.create_rack_unit_assignment(
            f.rack_unit_assignment_payload(
                rack["id"],
                rack["version"],
                equipment_label="Core switch",
                start_ru=40,
                end_ru=42,
                power_va=1200,
            ),
            DESIGNER_HEADERS,
        ),
        201,
    )
    assert placed["assignment_state"] == AssignmentState.ACTIVE
    assert placed["span_ru"] == 3

    validate_error(
        client.create_rack_unit_assignment(
            f.rack_unit_assignment_payload(
                rack["id"],
                rack["version"],
                equipment_label="Patch panel",
                start_ru=36,
                end_ru=37,
                power_va=1200,
            ),
            DESIGNER_HEADERS,
        ),
        ERR_STALE_RACK_VERSION,
        412,
    )

    untouched = fx.read_rack(client, rack["id"])
    assert_version_is(untouched, 2, "rack")
    assert untouched["occupied_ru"] == 3
    assert untouched["power_draw_va"] == 1200
    assert_rack_ru_identity(untouched)
    room = fx.read_room(client, site["room_id"])
    assert room["power_load_va"] == 1200
    assert_room_power_identity(room)

    second = validate_success(
        client.create_rack_unit_assignment(
            f.rack_unit_assignment_payload(
                rack["id"],
                untouched["version"],
                equipment_label="Patch panel",
                start_ru=36,
                end_ru=37,
                power_va=1200,
            ),
            DESIGNER_HEADERS,
        ),
        201,
    )
    assert second["span_ru"] == 2

    reconciled = fx.read_rack(client, rack["id"])
    assert_version_is(reconciled, 3, "rack")
    assert reconciled["occupied_ru"] == 5
    assert reconciled["available_ru"] == 37
    assert reconciled["power_draw_va"] == 2400
    assert_rack_ru_identity(reconciled)
    settled = fx.read_room(client, site["room_id"])
    assert settled["power_load_va"] == 2400
    assert_room_power_identity(settled)


def test_a_stale_project_version_blocks_the_warranty_submission(
    client: ApiClient,
) -> None:
    """The manager watches the job, sees the last drop signed off, and submits the
    registration quoting the project revision noted before that signature. Certification
    moved the job on, so the evidence the submission would freeze no longer matches the
    view it was built on and it is refused on the revision. The registration keeps its
    promoted state with no evidence frozen, and quoting the current revision submits it.

    Design: Corner/cross_cutting_complexity_layers/a_stale_project_version_blocks_the_warranty_submission
    """
    site = _site(client)
    link = _tested_link(client, site)
    registration = fx.create_registration(
        client,
        site["project_id"],
        manufacturer_program=ManufacturerProgram.STANDARD_15Y,
    )
    assert registration["registration_state"] == RegistrationState.DRAFT

    observed_version = fx.project_version(client, site["project_id"])
    fx.certify_link(client, link["id"])

    promoted = fx.read_registration(client, registration["id"])
    assert promoted["registration_state"] == RegistrationState.READY
    assert promoted["pinned_project_version"] > observed_version

    validate_error(
        client.submit_warranty_registration(
            registration["id"], f.warranty_submit_payload(observed_version), PM_HEADERS
        ),
        ERR_STALE_PROJECT_VERSION,
        412,
    )

    untouched = fx.read_registration(client, registration["id"])
    assert untouched["registration_state"] == RegistrationState.READY
    assert untouched["coverage_years"] is None
    assert untouched["submitted_certified_link_count"] is None

    submitted = validate_success(
        client.submit_warranty_registration(
            registration["id"],
            f.warranty_submit_payload(fx.project_version(client, site["project_id"])),
            PM_HEADERS,
        ),
        200,
    )
    assert submitted["registration_state"] == RegistrationState.SUBMITTED
    assert submitted["submitted_certified_link_count"] == 1
    assert submitted["coverage_years"] == 15
    assert (
        fx.read_project(client, site["project_id"])["warranty_status"]
        == WarrantyStatus.SUBMITTED
    )


# ─── consistency_model ───────────────────────────────────────────────────────


def test_a_write_response_already_carries_every_derived_field_it_moved(
    client: ApiClient,
) -> None:
    """Laying one drop into a conduit moves figures on three resources at once: the routing
    snapshots the area it consumed, the conduit's fill ledger grows and the drop counts one
    more pathway. The response to the write already reports the routing's own derived
    figures, and reads taken straight afterwards on the conduit and the drop show the moved
    ledgers rather than the values they held a moment earlier, twice over.

    Design: Corner/consistency_model/a_write_response_already_carries_every_derived_field_it_moved
    """
    site = _site(client)
    conduit = fx.create_segment(
        client,
        site["project_id"],
        segment_code="PS-N",
        pathway_type=PathwayType.EMT_CONDUIT,
        usable_area_sq_mm=573.0,
        length_m=30.0,
        bend_count=0,
        in_plenum_space=False,
    )
    link = _link(client, site)

    written = validate_success(
        client.create_link_route(
            f.link_route_payload(
                link["id"], conduit["id"], conduit["version"], sequence_index=1
            ),
            DESIGNER_HEADERS,
        ),
        201,
    )
    assert written["route_state"] == RouteState.OCCUPYING
    assert written["sequence_index"] == 1
    assert_decimal_equals(written["consumed_area_sq_mm"], CAT6A_AREA_SQ_MM)
    assert_version_is(written, 1, "routing")

    fetched = validate_success(
        client.get_link_route(written["id"], DESIGNER_HEADERS), 200
    )
    assert fetched["route_state"] == written["route_state"]
    assert fetched["sequence_index"] == written["sequence_index"]
    assert_decimal_equals(fetched["consumed_area_sq_mm"], CAT6A_AREA_SQ_MM)

    first_read = fx.read_segment(client, conduit["id"])
    assert first_read["occupying_route_count"] == 1
    assert_decimal_equals(first_read["fill_area_used_sq_mm"], CAT6A_AREA_SQ_MM)
    assert_decimal_equals(first_read["fill_ratio"], 0.0855, 4)
    assert_version_is(first_read, 2, "segment")
    assert_fill_ledger(first_read)

    routed = fx.read_link(client, link["id"])
    assert routed["routed_segment_count"] == 1
    assert routed["install_state"] == InstallState.DESIGNED

    second_read = fx.read_segment(client, conduit["id"])
    assert second_read["occupying_route_count"] == first_read["occupying_route_count"]
    assert second_read["version"] == first_read["version"]
    assert_decimal_equals(
        second_read["fill_area_used_sq_mm"], first_read["fill_area_used_sq_mm"]
    )
    assert_decimal_equals(second_read["fill_ratio"], first_read["fill_ratio"], 4)
    assert second_read["allowed_fill_pct"] == first_read["allowed_fill_pct"]
