"""Error-catalog breadth: each documented code is reachable through the one condition
that produces it, with its own HTTP status and with no partial write left behind."""

from typing import Any, Dict

from test_helpers import factories as f
from test_helpers import get_success_data, validate_error, validate_paginated
from test_helpers.api_errors import ApiErrorId
from test_helpers.assertions import (
    assert_grant_money_balanced,
    assert_instant_equals,
    assert_lot_units_conserved,
)
from test_helpers.constants import (
    AssessmentBasis,
    AssessmentStatus,
    CertificationLevel,
    DeviceType,
    GrantStatus,
    InstallationStatus,
    IssuedChannel,
    LotStatus,
    PlacementLocation,
    PlanStatus,
    ReimbursementBasis,
    ReportDecision,
    ReportStatus,
    VoidedReason,
    ZoneKind,
)
from test_helpers.fixtures import (
    activate_grant,
    arrive,
    book_visit,
    compile_report,
    complete_visit,
    create_active_grant,
    create_assessed_zone,
    create_crew,
    create_escape_plan,
    create_grant,
    create_household,
    create_partner,
    create_published_route,
    create_zone,
    decide_report,
    defer_visit,
    deliver_education,
    funded_arrived_visit,
    pin_clock,
    read_escape_plan,
    read_grant,
    read_household,
    read_installation,
    read_lot,
    read_report,
    read_zone,
    record_fire_incident,
    reserve_installation,
    submit_report,
    verify_installation,
)
from test_helpers.test_users import (
    ADMIN,
    ANALYST,
    COORDINATOR,
    GRANT_OFFICER_SUBMIT_ID,
    OFFICER,
    make_crr_technician_headers,
    make_grant_officer_headers,
    make_partner_liaison_headers,
)

# Ten syntactically valid identifiers that name nothing at all.
MISSING = {
    "zone": "00000000-0000-4000-8000-000000000001",
    "household": "00000000-0000-4000-8000-000000000002",
    "route": "00000000-0000-4000-8000-000000000003",
    "lot": "00000000-0000-4000-8000-000000000004",
    "installation": "00000000-0000-4000-8000-000000000005",
    "grant": "00000000-0000-4000-8000-000000000006",
    "plan": "00000000-0000-4000-8000-000000000007",
    "report": "00000000-0000-4000-8000-000000000008",
    "partner": "00000000-0000-4000-8000-000000000009",
    "crew": "00000000-0000-4000-8000-00000000000a",
}


def test_01_every_existence_error_names_its_own_entity(api):
    """Eight unknown path ids and two unknown body references each answer with the code
    for their own entity, never a single generic not-found.

    PRD: "Existence of every identifier in the URL path, validated strictly left to
    right, with HTTP 404 and the code naming the first missing level:
    `ERR_ZONE_NOT_FOUND`, `ERR_HOUSEHOLD_NOT_FOUND`, `ERR_ROUTE_NOT_FOUND`,
    `ERR_VISIT_NOT_FOUND`, `ERR_LOT_NOT_FOUND`, `ERR_INSTALLATION_NOT_FOUND`,
    `ERR_GRANT_NOT_FOUND`, `ERR_REPORT_NOT_FOUND` or `ERR_PLAN_NOT_FOUND`."

    Design: Corner/errors/every_existence_error_in_the_catalog_is_reachable_returns_not_found
    """
    pin_clock(api)
    zone = create_assessed_zone(api)

    validate_error(api.get_zone(MISSING["zone"], ADMIN), ApiErrorId.ZONE_NOT_FOUND, 404)
    validate_error(
        api.get_household(MISSING["household"], ADMIN),
        ApiErrorId.HOUSEHOLD_NOT_FOUND,
        404,
    )
    validate_error(api.get_route(MISSING["route"], ADMIN), ApiErrorId.ROUTE_NOT_FOUND, 404)
    validate_error(
        api.get_device_lot(MISSING["lot"], ADMIN), ApiErrorId.LOT_NOT_FOUND, 404
    )
    validate_error(
        api.get_installation(MISSING["installation"], ADMIN),
        ApiErrorId.INSTALLATION_NOT_FOUND,
        404,
    )
    validate_error(
        api.get_grant(MISSING["grant"], ADMIN), ApiErrorId.GRANT_NOT_FOUND, 404
    )
    validate_error(
        api.get_escape_plan(MISSING["plan"], ADMIN), ApiErrorId.PLAN_NOT_FOUND, 404
    )
    validate_error(
        api.get_grant_report(MISSING["report"], ADMIN), ApiErrorId.REPORT_NOT_FOUND, 404
    )

    # The two body-borne references sit at priority 5, not at priority 3.
    validate_error(
        api.create_grant(
            f.grant_payload(MISSING["partner"], grant_code="G-ORPHAN"), OFFICER
        ),
        ApiErrorId.PARTNER_NOT_FOUND,
        404,
    )
    validate_error(
        api.create_route(f.route_payload(zone["id"], MISSING["crew"]), COORDINATOR),
        ApiErrorId.CREW_NOT_FOUND,
        404,
    )

    _, grants = validate_paginated(api.list_grants(OFFICER))
    assert grants["total_count"] == 0
    _, routes = validate_paginated(api.list_routes(COORDINATOR))
    assert routes["total_count"] == 0
    assert read_zone(api, zone["id"])["assessment_status"] == AssessmentStatus.ASSESSED


def test_02_a_district_zone_cannot_be_assessed_directly(api):
    """Nesting a child flips the parent to DISTRICT, and the district's own version
    guard passes, so only the state gate can produce the refusal.

    PRD: "The run is only permitted on a zone whose `zone_kind` is `LEAF`; districts
    derive their score by rollup and a direct request is rejected with
    `ERR_ZONE_NOT_ASSESSABLE`."

    Design: Corner/errors/assessment_on_a_district_zone_returns_zone_not_assessable
    """
    pin_clock(api)
    parent = create_zone(
        api,
        zone_code="Z-DIST-1",
        name="Birchwood District",
        occupied_units=4000,
        structure_fire_count_5yr=20,
        fire_injury_count_5yr=3,
        pre_1980_unit_pct=30.0,
        senior_household_pct=15.0,
        under5_household_pct=6.0,
        disability_household_pct=3.0,
        assumed_alarm_absence_pct=40.0,
        daily_visit_cap=20,
    )
    child = create_zone(api, parent_zone_id=parent["id"])

    district = read_zone(api, parent["id"])
    assert district["zone_kind"] == ZoneKind.DISTRICT

    validate_error(
        api.create_assessment(
            district["id"],
            f.assessment_payload(district["version"], basis=AssessmentBasis.PROVISIONAL),
            ANALYST,
        ),
        ApiErrorId.ZONE_NOT_ASSESSABLE,
        409,
    )

    after = read_zone(api, parent["id"])
    assert after["zone_kind"] == ZoneKind.DISTRICT
    assert after["assessment_status"] == AssessmentStatus.UNASSESSED
    assert after["current_assessment_id"] is None
    _, meta = validate_paginated(api.list_assessments(parent["id"], ANALYST))
    assert meta["total_count"] == 0
    assert read_zone(api, child["id"])["zone_kind"] == ZoneKind.LEAF


def test_03_activating_an_active_grant_is_refused_and_does_not_bump_the_version(api):
    """Activation is not idempotent: the retry is a 409 and the OCC counter must not
    move a second time.

    PRD: "Activation moves it `DRAFT -> ACTIVE` and is the gate that lets lots be
    received and funds be reserved against it; activating a grant that is not in
    `DRAFT` is rejected with `ERR_GRANT_NOT_DRAFT`."

    Design: Corner/errors/activating_an_already_active_grant_returns_grant_not_draft
    """
    pin_clock(api)
    partner = create_partner(api, contact_email="grants@firesafe.example")
    grant = create_grant(api, partner["id"])
    activated = activate_grant(api, grant["id"])
    assert activated["status"] == GrantStatus.ACTIVE
    assert activated["version"] == 2

    validate_error(
        api.activate_grant(grant["id"], OFFICER), ApiErrorId.GRANT_NOT_DRAFT, 409
    )

    stored = read_grant(api, grant["id"])
    assert stored["status"] == GrantStatus.ACTIVE
    assert stored["version"] == 2
    assert stored["available_cents"] == 500000


def _draft_report_of_an_empty_period(api) -> Dict[str, Any]:
    """An ACTIVE grant with no stock and no installations, plus one DRAFT report over
    a closed August period, compiled by the compiling officer."""
    pin_clock(api, "2026-09-05T00:00:00Z")
    partner = create_partner(api, contact_email="grants@firesafe.example")
    grant = create_active_grant(api, partner["id"])
    report = compile_report(api, grant["id"])
    return {"partner": partner, "grant": grant, "report": report}


def test_04_a_decision_on_a_draft_report_is_refused_even_for_its_own_partner(api):
    """The liaison is the report's rightful partner, so ownership passes and the only
    gate left to reject is the state gate.

    PRD: "Only a `PartnerLiaison` whose `X-User-ID` equals the grant's `partner_id`
    may decide a report, and only while the report's `status` is `SUBMITTED`; a
    decision on a report in any other status is rejected with
    `ERR_REPORT_NOT_EDITABLE`, and a liaison from the wrong partner is rejected with
    `ERR_PARTNER_NOT_OWNER`."

    Design: Corner/errors/decision_recorded_on_a_draft_report_returns_report_not_editable
    """
    ctx = _draft_report_of_an_empty_period(api)
    report = ctx["report"]
    assert report["status"] == ReportStatus.DRAFT

    error = validate_error(
        api.decide_grant_report(
            report["id"],
            f.decision_payload(
                decision=ReportDecision.ACCEPT, reviewer_note="Looks fine to us"
            ),
            make_partner_liaison_headers(ctx["partner"]["id"]),
        ),
        ApiErrorId.REPORT_NOT_EDITABLE,
        409,
    )
    assert error["error_id"] != ApiErrorId.PARTNER_NOT_OWNER

    stored = read_report(api, report["id"])
    assert stored["status"] == ReportStatus.DRAFT
    assert stored["decided_at"] is None
    assert stored["revision_no"] == 0
    assert read_grant(api, ctx["grant"]["id"])["reported_grant_share_cents"] == 0


def test_05_compiling_an_empty_period_is_legal_but_submitting_it_is_not(api):
    """The DRAFT report over a period with nothing in it exists with every money field
    at 0; the sufficiency gate only bites at submission, and the submitting officer
    differs from the compiler so segregation of duties cannot be the cause.

    PRD: "After a full pre-submit recompute, `installation_count` must be at least 1,
    or the request is rejected with `ERR_NO_REPORTABLE_INSTALLATIONS`."

    Design: Corner/errors/submitting_a_report_with_no_installations_returns_no_reportable_installations
    """
    ctx = _draft_report_of_an_empty_period(api)
    report = ctx["report"]
    assert report["installation_count"] == 0
    assert report["reimbursable_total_cents"] == 0
    assert report["indirect_cents"] == 0
    assert report["total_project_cents"] == 0
    assert report["grant_share_cents"] == 0

    error = validate_error(
        api.submit_grant_report(
            report["id"],
            f.submit_report_payload(attestation_name="Dana Reyes"),
            make_grant_officer_headers(GRANT_OFFICER_SUBMIT_ID),
        ),
        ApiErrorId.NO_REPORTABLE_INSTALLATIONS,
        422,
    )
    assert error["error_id"] != ApiErrorId.SEGREGATION_OF_DUTIES

    stored = read_report(api, report["id"])
    assert stored["status"] == ReportStatus.DRAFT
    assert stored["submitted_by_user_id"] is None
    assert stored["submitted_at"] is None
    assert stored["version"] == 1


def test_06_a_superseded_plan_can_never_be_issued_but_its_replacement_can(api):
    """SUPERSEDED is terminal even though the plan was never issued, while the live
    plan that replaced it issues normally in the same run.

    PRD: "It is valid only from `DRAFT` or from `LAPSED`; an attempt on a plan in
    `ISSUED`, `VERIFIED` or `SUPERSEDED` is rejected with `ERR_PLAN_NOT_REISSUABLE`."

    Design: Corner/errors/issuing_a_superseded_escape_plan_returns_plan_not_reissuable
    """
    pin_clock(api)
    zone = create_assessed_zone(api)
    crew = create_crew(api, crew_code="CREW-B1")
    route = create_published_route(api, zone["id"], crew["id"], planned_slots=4)
    household = create_household(api, zone["id"], address_line="12 Birch Row")
    visit = book_visit(api, household["id"], route["id"])
    arrive(api, visit["id"], crew["id"])
    deliver_education(api, visit["id"], crew["id"], topics_covered=["ESCAPE_ROUTES"])
    defer_visit(api, visit["id"], crew["id"])

    first_version = read_household(api, household["id"])["version"]
    plan_one = create_escape_plan(
        api,
        household["id"],
        first_version,
        secondary_exit_count=1,
        meeting_point_description="Mailbox at the kerb",
    )
    second_version = read_household(api, household["id"])["version"]
    plan_two = create_escape_plan(
        api,
        household["id"],
        second_version,
        secondary_exit_count=2,
        meeting_point_description="Corner of Birch Row and 4th",
    )

    validate_error(
        api.issue_escape_plan(
            plan_one["id"], f.issue_plan_payload(IssuedChannel.IN_PERSON), COORDINATOR
        ),
        ApiErrorId.PLAN_NOT_REISSUABLE,
        409,
    )
    stale = read_escape_plan(api, plan_one["id"])
    assert stale["status"] == PlanStatus.SUPERSEDED
    assert stale["issued_channel"] is None
    assert stale["issued_at"] is None
    assert stale["version"] == plan_one["version"] + 1

    issued = get_success_data(
        api.issue_escape_plan(
            plan_two["id"], f.issue_plan_payload(IssuedChannel.MAIL), COORDINATOR
        )
    )
    assert issued["status"] == PlanStatus.ISSUED
    assert issued["issued_channel"] == IssuedChannel.MAIL
    assert_instant_equals(issued["issued_at"], "2026-08-01T00:00:00Z", "issued_at")
    assert issued["reissue_count"] == 0


SM10_LOT = {
    "sku": "SKU-SM10-A",
    "unit_cost_cents": 1850,
    "received_qty": 60,
    "expiry_date": "2027-06-30",
}


def test_07_a_forbidden_location_and_a_type_mismatch_are_different_refusals(api):
    """KITCHEN is refused for every family at all, while SLEEPING_AREA is a legal
    location that is simply absent from the CO_ALARM row; the legal pairing installs.

    PRD: "`KITCHEN`, `BATHROOM` and `GARAGE` are recognised request values that are
    always refused with `ERR_PLACEMENT_LOCATION_FORBIDDEN` ... a `CO_ALARM` may sit in
    `HALLWAY_OUTSIDE_SLEEPING`, `LIVING_LEVEL` or `BASEMENT_STAIR_TOP` but never inside
    a sleeping area ... Any other pairing is rejected with
    `ERR_PLACEMENT_TYPE_LOCATION_MISMATCH`."

    Design: Corner/errors/forbidden_and_type_mismatched_placements_are_both_rejected
    """
    ctx = funded_arrived_visit(
        api,
        pre_existing_working_smoke_alarms=0,
        lot_overrides=dict(SM10_LOT),
        household_overrides={"address_line": "12 Birch Row"},
    )
    crew_headers = make_crr_technician_headers(ctx["crew"]["id"])
    visit_id = ctx["visit"]["id"]

    validate_error(
        api.create_installation(
            f.installation_payload(
                visit_id,
                device_type=DeviceType.SMOKE_10YR,
                placement_location=PlacementLocation.KITCHEN,
                storey=1,
            ),
            crew_headers,
        ),
        ApiErrorId.PLACEMENT_LOCATION_FORBIDDEN,
        422,
    )
    validate_error(
        api.create_installation(
            f.installation_payload(
                visit_id,
                device_type=DeviceType.CO_ALARM,
                placement_location=PlacementLocation.SLEEPING_AREA,
                storey=1,
            ),
            crew_headers,
        ),
        ApiErrorId.PLACEMENT_TYPE_LOCATION_MISMATCH,
        422,
    )

    accepted = get_success_data(
        api.create_installation(
            f.installation_payload(
                visit_id,
                device_type=DeviceType.SMOKE_10YR,
                placement_location=PlacementLocation.HALLWAY_OUTSIDE_SLEEPING,
                storey=1,
            ),
            crew_headers,
        ),
        201,
    )
    assert accepted["status"] == InstallationStatus.RESERVED
    assert accepted["placement_location"] == PlacementLocation.HALLWAY_OUTSIDE_SLEEPING
    assert accepted["device_lot_id"] == ctx["lot"]["id"]

    _, meta = validate_paginated(api.list_installations(OFFICER, params={"visit_id": visit_id}))
    assert meta["total_count"] == 1

    lot = read_lot(api, ctx["lot"]["id"])
    assert lot["reserved_qty"] == 1
    assert lot["on_hand_qty"] == 60
    grant = read_grant(api, ctx["grant"]["id"])
    assert grant["reserved_cents"] == 1921
    assert grant["available_cents"] == 498079


def test_08_an_explicit_lot_of_the_wrong_family_is_a_referential_refusal(api):
    """Naming the lot bypasses the selector, so the requested family and the lot's
    family can disagree; the placement itself is legal for a CO alarm.

    PRD: "When `device_lot_id` is supplied it is used exactly as given, and its own
    `device_type` must equal the requested `device_type` - a mismatch is rejected with
    `ERR_LOT_TYPE_MISMATCH`."

    Design: Corner/errors/explicit_lot_of_another_device_type_returns_lot_type_mismatch
    """
    ctx = funded_arrived_visit(
        api,
        pre_existing_working_smoke_alarms=0,
        lot_overrides=dict(SM10_LOT),
        household_overrides={"address_line": "12 Birch Row", "fuel_burning_appliance": True},
    )

    validate_error(
        api.create_installation(
            f.installation_payload(
                ctx["visit"]["id"],
                device_type=DeviceType.CO_ALARM,
                placement_location=PlacementLocation.HALLWAY_OUTSIDE_SLEEPING,
                storey=1,
                device_lot_id=ctx["lot"]["id"],
            ),
            make_crr_technician_headers(ctx["crew"]["id"]),
        ),
        ApiErrorId.LOT_TYPE_MISMATCH,
        422,
    )

    _, meta = validate_paginated(
        api.list_installations(OFFICER, params={"visit_id": ctx["visit"]["id"]})
    )
    assert meta["total_count"] == 0
    lot = read_lot(api, ctx["lot"]["id"])
    assert lot["reserved_qty"] == 0
    assert lot["version"] == 1
    grant = read_grant(api, ctx["grant"]["id"])
    assert grant["reserved_cents"] == 0
    assert grant["version"] == 2


def test_09_a_lot_of_an_unfunded_family_cannot_be_received(api):
    """The grant's allowed set is a hard receipt filter, not advisory metadata.

    PRD: "The lot's `device_type` must be a member of its funding grant's
    `allowed_device_types`; a lot of an unfunded family is rejected with
    `ERR_DEVICE_TYPE_NOT_FUNDED`."

    Design: Corner/errors/lot_of_an_unfunded_device_type_returns_device_type_not_funded
    """
    pin_clock(api)
    partner = create_partner(api, contact_email="grants@firesafe.example")
    grant = create_active_grant(api, partner["id"])
    assert grant["allowed_device_types"] == [DeviceType.SMOKE_10YR, DeviceType.CO_ALARM]

    validate_error(
        api.create_device_lot(
            f.device_lot_payload(
                grant["id"],
                sku="SKU-STROBE-A",
                device_type=DeviceType.STROBE_HOH,
                unit_cost_cents=4900,
                received_qty=10,
                expiry_date="2028-06-30",
            ),
            OFFICER,
        ),
        ApiErrorId.DEVICE_TYPE_NOT_FUNDED,
        422,
    )

    _, meta = validate_paginated(
        api.list_device_lots(OFFICER, params={"funding_grant_id": grant["id"]})
    )
    assert meta["total_count"] == 0
    stored = read_grant(api, grant["id"])
    assert stored["status"] == GrantStatus.ACTIVE
    assert stored["version"] == 2


def test_10_the_grant_period_is_tested_against_the_clock_not_the_service_date(api):
    """The visit was surveyed inside the period, but the reservation happens a week
    after it ended and the grant is still ACTIVE, so only the temporal rule can reject.

    PRD: "Whether the lot was named or selected, the funding grant must be `ACTIVE`
    (`ERR_GRANT_NOT_ACTIVE`), the logical clock's date must lie within the grant's
    inclusive period (`ERR_OUTSIDE_GRANT_PERIOD`)..."

    Design: Corner/errors/installation_after_the_grant_period_ends_returns_outside_grant_period
    """
    ctx = funded_arrived_visit(
        api,
        pre_existing_working_smoke_alarms=0,
        grant_overrides={
            "grant_code": "G-SHORT-1",
            "period_end_date": "2026-08-31",
            "allowed_device_types": [DeviceType.SMOKE_10YR],
            "unit_rate_cents_by_type": {DeviceType.SMOKE_10YR: 2195},
        },
        lot_overrides=dict(SM10_LOT),
        household_overrides={"address_line": "12 Birch Row"},
    )
    pin_clock(api, "2026-09-05T00:00:00Z")

    validate_error(
        api.create_installation(
            f.installation_payload(
                ctx["visit"]["id"],
                device_type=DeviceType.SMOKE_10YR,
                placement_location=PlacementLocation.HALLWAY_OUTSIDE_SLEEPING,
                storey=1,
                device_lot_id=ctx["lot"]["id"],
            ),
            make_crr_technician_headers(ctx["crew"]["id"]),
        ),
        ApiErrorId.OUTSIDE_GRANT_PERIOD,
        422,
    )

    grant = read_grant(api, ctx["grant"]["id"])
    assert grant["status"] == GrantStatus.ACTIVE
    assert grant["reserved_cents"] == 0
    assert grant["available_cents"] == 500000
    assert read_lot(api, ctx["lot"]["id"])["reserved_qty"] == 0
    _, meta = validate_paginated(
        api.list_installations(OFFICER, params={"visit_id": ctx["visit"]["id"]})
    )
    assert meta["total_count"] == 0


SMOKE_ONLY_GRANT = {
    "allowed_device_types": [DeviceType.SMOKE_10YR],
    "unit_rate_cents_by_type": {DeviceType.SMOKE_10YR: 2195},
}


def test_11_availability_is_on_hand_less_reserved_not_on_hand(api):
    """The one-unit lot still reports on_hand_qty 1 after the first reservation, yet the
    second reservation must fail - a reserved unit is held, not consumed.

    PRD: "The explicitly named lot must also have at least one unreserved unit
    available, meaning its `on_hand_qty` less its `reserved_qty` is 1 or more;
    otherwise the request is rejected with `ERR_INSUFFICIENT_DEVICE_STOCK`."

    Design: Corner/errors/second_reservation_from_a_single_unit_lot_returns_insufficient_device_stock
    """
    ctx = funded_arrived_visit(
        api,
        pre_existing_working_smoke_alarms=0,
        grant_overrides=dict(SMOKE_ONLY_GRANT),
        lot_overrides={
            "sku": "SKU-SM10-LAST",
            "unit_cost_cents": 1850,
            "received_qty": 1,
            "expiry_date": "2027-06-30",
        },
        household_overrides={
            "address_line": "12 Birch Row",
            "occupant_count": 3,
            "sleeping_areas_count": 2,
        },
    )
    crew_headers = make_crr_technician_headers(ctx["crew"]["id"])
    first = reserve_installation(
        api,
        ctx["visit"]["id"],
        ctx["crew"]["id"],
        placement_location=PlacementLocation.HALLWAY_OUTSIDE_SLEEPING,
        storey=1,
        device_lot_id=ctx["lot"]["id"],
    )

    validate_error(
        api.create_installation(
            f.installation_payload(
                ctx["visit"]["id"],
                device_type=DeviceType.SMOKE_10YR,
                placement_location=PlacementLocation.SLEEPING_AREA,
                storey=1,
                device_lot_id=ctx["lot"]["id"],
            ),
            crew_headers,
        ),
        ApiErrorId.INSUFFICIENT_DEVICE_STOCK,
        409,
    )

    lot = read_lot(api, ctx["lot"]["id"])
    assert lot["on_hand_qty"] == 1
    assert lot["reserved_qty"] == 1
    assert lot["consumed_qty"] == 0
    assert lot["status"] == LotStatus.AVAILABLE
    assert_lot_units_conserved(lot)
    assert read_installation(api, first["id"])["status"] == InstallationStatus.RESERVED
    _, meta = validate_paginated(
        api.list_installations(OFFICER, params={"visit_id": ctx["visit"]["id"]})
    )
    assert meta["total_count"] == 1
    assert read_grant(api, ctx["grant"]["id"])["reserved_cents"] == 1921


def test_12_a_verified_installation_can_no_longer_be_voided(api):
    """VERIFIED is terminal, so the void that would have worked one step earlier is
    refused and the second crew's verification stamps survive.

    PRD: "...it may be applied only to an installation in `RESERVED` or `INSTALLED`;
    `VERIFIED` and `VOIDED` are both terminal and an attempt on either is rejected with
    `ERR_INSTALLATION_NOT_VOIDABLE`."

    Design: Corner/errors/voiding_a_verified_installation_returns_installation_not_voidable
    """
    ctx = funded_arrived_visit(
        api,
        pre_existing_working_smoke_alarms=1,
        grant_overrides=dict(SMOKE_ONLY_GRANT),
        lot_overrides=dict(SM10_LOT),
        household_overrides={"address_line": "12 Birch Row"},
    )
    verifier = create_crew(api, crew_code="CREW-B2")
    installation = reserve_installation(
        api,
        ctx["visit"]["id"],
        ctx["crew"]["id"],
        placement_location=PlacementLocation.HALLWAY_OUTSIDE_SLEEPING,
        storey=1,
        device_lot_id=ctx["lot"]["id"],
    )
    deliver_education(api, ctx["visit"]["id"], ctx["crew"]["id"])
    complete_visit(
        api, ctx["visit"]["id"], ctx["crew"]["id"], occupant_signature_name="R. Okafor"
    )
    verify_installation(api, installation["id"], verifier["id"])

    validate_error(
        api.void_installation(
            installation["id"], f.void_payload(VoidedReason.DEVICE_DEFECT), OFFICER
        ),
        ApiErrorId.INSTALLATION_NOT_VOIDABLE,
        409,
    )

    stored = read_installation(api, installation["id"])
    assert stored["status"] == InstallationStatus.VERIFIED
    assert stored["verified_by_crew_id"] == verifier["id"]
    assert stored["installed_by_crew_id"] == ctx["crew"]["id"]
    assert_instant_equals(stored["verified_at"], "2026-08-01T00:00:00Z", "verified_at")
    assert stored["voided_at"] is None
    assert stored["voided_reason"] is None

    lot = read_lot(api, ctx["lot"]["id"])
    assert lot["consumed_qty"] == 1
    assert lot["on_hand_qty"] == 59
    grant = read_grant(api, ctx["grant"]["id"])
    assert grant["committed_cents"] == 1921
    assert grant["reserved_cents"] == 0
    assert grant["available_cents"] == 498079
    assert_grant_money_balanced(grant)


def test_13_an_accepted_report_freezes_its_installations_against_voiding(api):
    """The row's own state still admits the void, so the refusal is 422 and comes only
    from the accounting the partner has already signed off.

    PRD: "One guard applies to the `INSTALLED` branch only: if the installation's
    `reimbursable_cents` is already frozen into an `ACCEPTED` grant report - and the
    reportable set of a report covers `INSTALLED` and `VERIFIED` rows alike - the void
    is rejected with `ERR_INSTALLATION_ALREADY_REPORTED`, because reversing it would
    falsify a report the partner has already signed off."

    Design: Corner/errors/voiding_an_installation_frozen_into_an_accepted_report_returns_already_reported
    """
    ctx = funded_arrived_visit(
        api,
        pre_existing_working_smoke_alarms=1,
        grant_overrides=dict(SMOKE_ONLY_GRANT),
        lot_overrides=dict(SM10_LOT),
        household_overrides={"address_line": "12 Birch Row"},
    )
    installation = reserve_installation(
        api,
        ctx["visit"]["id"],
        ctx["crew"]["id"],
        placement_location=PlacementLocation.HALLWAY_OUTSIDE_SLEEPING,
        storey=1,
        device_lot_id=ctx["lot"]["id"],
    )
    deliver_education(api, ctx["visit"]["id"], ctx["crew"]["id"])
    complete_visit(
        api, ctx["visit"]["id"], ctx["crew"]["id"], occupant_signature_name="R. Okafor"
    )
    report = compile_report(api, ctx["grant"]["id"])
    submit_report(api, report["id"], attestation_name="Dana Reyes")
    decided = decide_report(
        api,
        report["id"],
        ctx["partner"]["id"],
        decision=ReportDecision.ACCEPT,
        reviewer_note="Reimbursement approved",
    )

    validate_error(
        api.void_installation(
            installation["id"], f.void_payload(VoidedReason.DATA_ENTRY_ERROR), OFFICER
        ),
        ApiErrorId.INSTALLATION_ALREADY_REPORTED,
        422,
    )

    stored = read_installation(api, installation["id"])
    assert stored["status"] == InstallationStatus.INSTALLED
    assert stored["reimbursable_cents"] == 1921
    assert decided["status"] == ReportStatus.ACCEPTED
    assert decided["installation_count"] == 1
    assert decided["reimbursable_total_cents"] == 1921
    assert decided["indirect_cents"] == 240
    assert decided["total_project_cents"] == 2161
    assert decided["partner_match_required_cents"] == 432
    assert decided["grant_share_cents"] == 1729

    grant = read_grant(api, ctx["grant"]["id"])
    assert grant["reported_grant_share_cents"] == 1729
    assert grant["committed_cents"] == 1921
    assert grant["available_cents"] == 498079
    assert grant["status"] == GrantStatus.ACTIVE
    lot = read_lot(api, ctx["lot"]["id"])
    assert lot["consumed_qty"] == 1
    assert lot["on_hand_qty"] == 59


def test_14_a_share_larger_than_the_direct_cost_can_break_the_authorization(api):
    """Both devices reserve and commit legally under the 5000-cent award, yet a 50%
    indirect rate with no partner match pushes the report's share above it.

    PRD: "And the fiscal ceiling must hold: the report's `grant_share_cents` must be no
    greater than the grant's `authorized_cents` less its `reported_grant_share_cents`,
    or the request is rejected with `ERR_GRANT_SHARE_EXCEEDS_AUTHORIZED`."

    Design: Corner/errors/report_share_above_the_authorized_remainder_returns_grant_share_exceeds_authorized
    """
    ctx = funded_arrived_visit(
        api,
        pre_existing_working_smoke_alarms=0,
        grant_overrides={
            "grant_code": "G-THIN-1",
            "authorized_cents": 5000,
            "allowed_device_types": [DeviceType.SMOKE_10YR],
            "unit_rate_cents_by_type": {DeviceType.SMOKE_10YR: 2195},
            "reimbursement_pct": 100.0,
            "indirect_rate_pct": 50.0,
            "match_pct": 0.0,
        },
        lot_overrides={
            "sku": "SKU-SM10-A",
            "unit_cost_cents": 1850,
            "received_qty": 10,
            "expiry_date": "2027-06-30",
        },
        household_overrides={"address_line": "12 Birch Row"},
    )
    first = reserve_installation(
        api,
        ctx["visit"]["id"],
        ctx["crew"]["id"],
        placement_location=PlacementLocation.HALLWAY_OUTSIDE_SLEEPING,
        storey=1,
        device_lot_id=ctx["lot"]["id"],
    )
    second = reserve_installation(
        api,
        ctx["visit"]["id"],
        ctx["crew"]["id"],
        placement_location=PlacementLocation.SLEEPING_AREA,
        storey=1,
        device_lot_id=ctx["lot"]["id"],
    )
    deliver_education(api, ctx["visit"]["id"], ctx["crew"]["id"])
    complete_visit(
        api, ctx["visit"]["id"], ctx["crew"]["id"], occupant_signature_name="R. Okafor"
    )
    report = compile_report(api, ctx["grant"]["id"])

    validate_error(
        api.submit_grant_report(
            report["id"],
            f.submit_report_payload(attestation_name="Dana Reyes"),
            make_grant_officer_headers(GRANT_OFFICER_SUBMIT_ID),
        ),
        ApiErrorId.GRANT_SHARE_EXCEEDS_AUTHORIZED,
        422,
    )

    for row in (first, second):
        installed = read_installation(api, row["id"])
        assert installed["status"] == InstallationStatus.INSTALLED
        assert installed["reimbursable_cents"] == 2195
    assert report["reimbursable_total_cents"] == 4390
    assert report["indirect_cents"] == 2195
    assert report["total_project_cents"] == 6585
    assert report["partner_match_required_cents"] == 0
    assert report["grant_share_cents"] == 6585

    stored = read_report(api, report["id"])
    assert stored["status"] == ReportStatus.DRAFT
    assert stored["submitted_at"] is None
    assert stored["attestation_name"] is None
    grant = read_grant(api, ctx["grant"]["id"])
    assert grant["committed_cents"] == 4390
    assert grant["available_cents"] == 610
    assert grant["reported_grant_share_cents"] == 0


def test_15_a_validated_score_cannot_be_run_before_any_unit_is_surveyed(api):
    """The validated variant divides by surveyed_units, so it is undefined at zero and
    must not silently fall back to the provisional variant.

    PRD: "Requesting the `VALIDATED` basis additionally requires the zone's
    `surveyed_units` to be at least 1, because the validated alarm gap is measured from
    field data; when no unit has been surveyed the request is rejected with
    `ERR_INSUFFICIENT_FIELD_DATA`."

    Design: Corner/errors/validated_basis_on_an_unsurveyed_zone_returns_insufficient_field_data
    """
    pin_clock(api)
    zone = create_zone(api)
    assert zone["surveyed_units"] == 0

    validate_error(
        api.create_assessment(
            zone["id"],
            f.assessment_payload(
                zone["version"],
                basis=AssessmentBasis.VALIDATED,
                analyst_note="Attempting a field-validated score before any survey",
            ),
            ANALYST,
        ),
        ApiErrorId.INSUFFICIENT_FIELD_DATA,
        422,
    )

    stored = read_zone(api, zone["id"])
    assert stored["assessment_status"] == AssessmentStatus.UNASSESSED
    assert stored["risk_score"] is None
    assert stored["risk_tier"] is None
    assert stored["assessment_basis"] is None
    assert stored["surveyed_units"] == 0
    assert stored["version"] == zone["version"]
    _, meta = validate_paginated(api.list_assessments(zone["id"], ANALYST))
    assert meta["total_count"] == 0


def test_16_three_global_code_scopes_and_one_per_zone_address_scope(api):
    """Crew code, grant code and incident number collide globally, while an address
    collides only inside its own zone - the same street address lands in a second zone.

    PRD: "...code and address uniqueness (`ERR_ZONE_CODE_TAKEN`,
    `ERR_CREW_CODE_TAKEN`, `ERR_GRANT_CODE_TAKEN`, `ERR_INCIDENT_NUMBER_TAKEN`,
    `ERR_DUPLICATE_HOUSEHOLD_ADDRESS`, all 409, on `POST /crr/zones`,
    `POST /crr/crews`, `POST /crr/grants`, `POST /crr/zones/{id}/fire-incidents` and
    `POST /crr/households` respectively)..."

    Design: Corner/errors/all_four_remaining_uniqueness_families_are_rejected
    """
    pin_clock(api)
    birchwood = create_zone(api)
    cedar = create_zone(
        api,
        zone_code="Z-C77",
        name="Cedar Leaf",
        occupied_units=1200,
        structure_fire_count_5yr=4,
        fire_injury_count_5yr=0,
        pre_1980_unit_pct=12.0,
        senior_household_pct=6.0,
        under5_household_pct=3.0,
        disability_household_pct=1.0,
        assumed_alarm_absence_pct=25.0,
        daily_visit_cap=6,
    )
    create_household(api, birchwood["id"], address_line="12 Birch Row")
    crew = create_crew(api, crew_code="CREW-B1")
    partner = create_partner(api, contact_email="grants@firesafe.example")
    grant = create_grant(api, partner["id"], **SMOKE_ONLY_GRANT)
    incident = record_fire_incident(
        api,
        birchwood["id"],
        incident_number="INC-2026-0001",
        occurred_at="2026-07-04T02:10:00Z",
        injuries=1,
    )

    validate_error(
        api.create_crew(
            f.crew_payload(
                crew_code="CREW-B1",
                member_count=3,
                certification_level=CertificationLevel.BASIC,
                max_daily_minutes=300,
            ),
            ADMIN,
        ),
        ApiErrorId.CREW_CODE_TAKEN,
        409,
    )
    validate_error(
        api.create_grant(
            f.grant_payload(
                partner["id"],
                grant_code="G-UNIT-1",
                authorized_cents=100000,
                period_start_date="2027-01-01",
                period_end_date="2027-06-30",
                allowed_device_types=[DeviceType.CO_ALARM],
                unit_rate_cents_by_type={DeviceType.CO_ALARM: 3495},
                reimbursement_basis=ReimbursementBasis.ACTUAL_COST,
                reimbursement_pct=90.0,
                indirect_rate_pct=10.0,
                match_pct=25.0,
            ),
            OFFICER,
        ),
        ApiErrorId.GRANT_CODE_TAKEN,
        409,
    )
    validate_error(
        api.create_fire_incident(
            cedar["id"],
            f.fire_incident_payload(
                incident_number="INC-2026-0001",
                occurred_at="2026-07-09T04:00:00Z",
                working_alarm_present=True,
            ),
            ANALYST,
        ),
        ApiErrorId.INCIDENT_NUMBER_TAKEN,
        409,
    )
    validate_error(
        api.create_household(
            f.household_payload(
                birchwood["id"],
                address_line="12 Birch Row",
                occupant_count=5,
                sleeping_areas_count=3,
                storeys=2,
            ),
            COORDINATOR,
        ),
        ApiErrorId.DUPLICATE_HOUSEHOLD_ADDRESS,
        409,
    )

    control = create_household(
        api,
        cedar["id"],
        address_line="12 Birch Row",
        occupant_count=5,
        sleeping_areas_count=3,
        storeys=2,
    )
    assert control["zone_id"] == cedar["id"]
    assert control["address_line"] == "12 Birch Row"

    _, households = validate_paginated(api.list_households(COORDINATOR))
    assert households["total_count"] == 2
    _, grants = validate_paginated(api.list_grants(OFFICER))
    assert grants["total_count"] == 1
    assert read_grant(api, grant["id"])["status"] == GrantStatus.DRAFT
    _, birch_incidents = validate_paginated(
        api.list_fire_incidents(birchwood["id"], ANALYST)
    )
    assert birch_incidents["total_count"] == 1
    assert incident["incident_number"] == "INC-2026-0001"
    _, cedar_incidents = validate_paginated(api.list_fire_incidents(cedar["id"], ANALYST))
    assert cedar_incidents["total_count"] == 0
    assert crew["certification_level"] == CertificationLevel.ADVANCED
