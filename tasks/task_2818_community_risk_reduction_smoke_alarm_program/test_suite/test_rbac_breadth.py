"""Role-based access control: operation-scoped denials, authentication ahead of
authorization, the two entity-backed identities and the two segregation-of-duties
operations - each with the control leg that then succeeds on the same row."""

from test_helpers import factories as f
from test_helpers import get_success_data, validate_error, validate_paginated
from test_helpers.api_errors import ApiErrorId
from test_helpers.assertions import assert_instant_equals
from test_helpers.constants import (
    AssessmentStatus,
    InstallStatus,
    InstallationStatus,
    ReportStatus,
    Role,
    RouteStatus,
    VisitStatus,
)
from test_helpers.fixtures import (
    activate_grant,
    arrive,
    book_visit,
    compile_report,
    complete_visit,
    create_assessed_zone,
    create_crew,
    create_grant,
    create_household,
    create_lot,
    create_partner,
    create_published_route,
    create_zone,
    deliver_education,
    pin_clock,
    read_grant,
    read_installation,
    read_report,
    read_route,
    read_visit,
    read_zone,
    reserve_installation,
)
from test_helpers.test_users import (
    ADMIN,
    ANALYST,
    COORDINATOR,
    GRANT_OFFICER_COMPILE_ID,
    NO_AUTH_HEADERS,
    OFFICER,
    headers_for,
    make_crr_technician_headers,
    make_grant_officer_headers,
    make_partner_liaison_headers,
)

# A body that would be accepted verbatim from a RiskAnalyst.
VALID_ZONE_BODY = f.zone_payload()


def test_01_a_coordinator_may_read_zones_but_never_create_one(api):
    """The denial is scoped to the operation, not to the resource: the very same
    coordinator headers list zones successfully in the same test.

    PRD: "If the headers are well-formed but the named role does not appear in the
    authorized-role list for the requested endpoint (SS4), the request is rejected with
    `ERR_ROLE_NOT_PERMITTED` (HTTP 403)."

    Design: Corner/rbac/zone_create_by_a_canvass_coordinator_returns_forbidden
    """
    pin_clock(api)

    validate_error(
        api.create_zone(VALID_ZONE_BODY, COORDINATOR),
        ApiErrorId.ROLE_NOT_PERMITTED,
        403,
    )

    rows, meta = validate_paginated(api.list_zones(COORDINATOR))
    assert meta["total_count"] == 0
    assert rows == []


def test_02_authentication_answers_before_authorization_and_before_the_body(api):
    """A wholly absent header pair and a syntactically fine but undeclared role name are
    the same failure, and neither is downgraded to 403 or 400.

    PRD: "If either header is absent or empty, or if `X-User-Role` is not one of the six
    declared role names, the request is rejected with `ERR_UNAUTHENTICATED` (HTTP 401)."

    Design: Corner/rbac/call_without_role_headers_returns_unauthenticated
    """
    missing = validate_error(
        api.create_zone(VALID_ZONE_BODY, NO_AUTH_HEADERS),
        ApiErrorId.UNAUTHENTICATED,
        401,
    )
    assert missing["error_id"] != ApiErrorId.ROLE_NOT_PERMITTED

    unknown = validate_error(
        api.list_zones(headers_for("FireMarshal", "marshal-1")),
        ApiErrorId.UNAUTHENTICATED,
        401,
    )
    assert unknown["error_id"] != ApiErrorId.ROLE_NOT_PERMITTED

    _, meta = validate_paginated(api.list_zones(ANALYST))
    assert meta["total_count"] == 0


def test_03_a_technician_of_another_crew_cannot_arrive_at_this_visit(api):
    """CREW-B2 is a fully valid ADVANCED crew, and the identical request from the
    route's own crew then succeeds - so the check is per-resource, not per-role.

    PRD: "Concretely, a technician may only arrive at, educate at, complete, or reserve
    a device for a visit whose route names that same crew - a mismatch is rejected with
    `ERR_CREW_NOT_ASSIGNED` (HTTP 403)."

    Design: Corner/rbac/technician_working_another_crews_visit_returns_forbidden
    """
    pin_clock(api)
    zone = create_assessed_zone(api)
    household = create_household(api, zone["id"], address_line="12 Birch Row")
    owner = create_crew(api, crew_code="CREW-B1")
    stranger = create_crew(api, crew_code="CREW-B2")
    route = create_published_route(api, zone["id"], owner["id"], planned_slots=4)
    visit = book_visit(api, household["id"], route["id"])

    validate_error(
        api.arrive_visit(
            visit["id"],
            f.arrive_payload(0, 0),
            make_crr_technician_headers(stranger["id"]),
        ),
        ApiErrorId.CREW_NOT_ASSIGNED,
        403,
    )

    refused = read_visit(api, visit["id"])
    assert refused["install_status"] == InstallStatus.NOT_STARTED
    assert refused["visit_status"] == VisitStatus.SCHEDULED
    assert read_zone(api, zone["id"])["surveyed_units"] == 0

    admitted = arrive(api, visit["id"], owner["id"])
    assert admitted["install_status"] == InstallStatus.SURVEYED
    assert admitted["visit_status"] == VisitStatus.IN_PROGRESS
    assert read_route(api, route["id"])["status"] == RouteStatus.IN_PROGRESS

    # The survey counters are driven by close-out, not by arrival: PRD SS3.6 moves
    # surveyed_units and surveyed_units_without_alarm on the household transition to
    # VISIT_COMPLETED, so they are still 0 here.
    surveyed = read_zone(api, zone["id"])
    assert surveyed["surveyed_units"] == 0
    assert surveyed["surveyed_units_without_alarm"] == 0
    assert surveyed["assessment_status"] == AssessmentStatus.TARGETED


def test_04_ownership_answers_before_the_reports_own_state(api):
    """P1's DRAFT report would also justify a 409, but the liaison belongs to P2, and
    priority 6 runs four steps ahead of the target-state check.

    PRD: "...a liaison may only record a decision on a grant report whose grant belongs
    to that partner, and any other pairing is rejected with `ERR_PARTNER_NOT_OWNER`
    (HTTP 403)."

    Design: Corner/rbac/liaison_deciding_another_partners_report_returns_forbidden
    """
    pin_clock(api, "2026-09-05T00:00:00Z")
    owner = create_partner(api, contact_email="grants@firesafe.example")
    outsider = create_partner(
        api,
        org_name="Metro Utility Co",
        org_type="UTILITY",
        contact_email="safety@metroutility.example",
    )
    grant = create_grant(api, owner["id"])
    activate_grant(api, grant["id"])
    report = compile_report(api, grant["id"])

    error = validate_error(
        api.decide_grant_report(
            report["id"],
            f.decision_payload(),
            make_partner_liaison_headers(outsider["id"]),
        ),
        ApiErrorId.PARTNER_NOT_OWNER,
        403,
    )
    assert error["error_id"] != ApiErrorId.REPORT_NOT_EDITABLE

    stored = read_report(api, report["id"])
    assert stored["status"] == ReportStatus.DRAFT
    assert stored["decided_at"] is None
    assert read_grant(api, grant["id"])["reported_grant_share_cents"] == 0

    # The outsider's read authority is untouched - only the decision is owner-bound.
    validate_paginated(api.list_grant_reports(make_partner_liaison_headers(outsider["id"])))


def test_05_neither_the_installing_crew_nor_the_compiling_officer_may_sign_off(api):
    """Both halves of the separation-of-duties rule refuse at 403, and both control
    legs - a second crew and a second officer - then succeed on the very same rows.

    PRD: "Two operations additionally enforce **segregation of duties**, and both reject
    with `ERR_SEGREGATION_OF_DUTIES` (HTTP 403). Verifying an installation requires that
    the acting crew's `X-User-ID` differ from the installation's `installed_by_crew_id`
    ... Submitting a grant report requires that the submitting officer's `X-User-ID`
    differ from the report's `compiled_by_user_id`."

    Design: Corner/rbac/segregation_of_duties_blocks_self_verify_and_self_submit
    """
    pin_clock(api)
    zone = create_assessed_zone(api)
    household = create_household(api, zone["id"], address_line="12 Birch Row")
    installer = create_crew(api, crew_code="CREW-B1")
    checker = create_crew(api, crew_code="CREW-B2")
    route = create_published_route(api, zone["id"], installer["id"], planned_slots=4)
    visit = book_visit(api, household["id"], route["id"])
    arrive(api, visit["id"], installer["id"], pre_existing_working_smoke_alarms=1)

    partner = create_partner(api, contact_email="grants@firesafe.example")
    grant = create_grant(
        api,
        partner["id"],
        allowed_device_types=["SMOKE_10YR"],
        unit_rate_cents_by_type={"SMOKE_10YR": 2195},
    )
    activate_grant(api, grant["id"])
    lot = create_lot(
        api,
        grant["id"],
        sku="SKU-SM10-A",
        unit_cost_cents=1850,
        received_qty=60,
        expiry_date="2027-06-30",
    )
    installation = reserve_installation(
        api,
        visit["id"],
        installer["id"],
        placement_location="HALLWAY_OUTSIDE_SLEEPING",
        storey=1,
        device_lot_id=lot["id"],
    )
    deliver_education(api, visit["id"], installer["id"])
    complete_visit(api, visit["id"], installer["id"], occupant_signature_name="R. Okafor")
    report = compile_report(api, grant["id"])

    validate_error(
        api.verify_installation(
            installation["id"], make_crr_technician_headers(installer["id"])
        ),
        ApiErrorId.SEGREGATION_OF_DUTIES,
        403,
    )
    validate_error(
        api.submit_grant_report(
            report["id"],
            f.submit_report_payload(attestation_name="Same Officer"),
            make_grant_officer_headers(GRANT_OFFICER_COMPILE_ID),
        ),
        ApiErrorId.SEGREGATION_OF_DUTIES,
        403,
    )
    assert read_installation(api, installation["id"])["status"] == InstallationStatus.INSTALLED
    assert read_report(api, report["id"])["status"] == ReportStatus.DRAFT

    verified = get_success_data(
        api.verify_installation(
            installation["id"], make_crr_technician_headers(checker["id"])
        )
    )
    assert verified["status"] == InstallationStatus.VERIFIED
    assert verified["verified_by_crew_id"] == checker["id"]
    assert verified["installed_by_crew_id"] == installer["id"]

    submitted = get_success_data(
        api.submit_grant_report(
            report["id"],
            f.submit_report_payload(attestation_name="Dana Reyes"),
            make_grant_officer_headers("officer-submit-2"),
        )
    )
    assert submitted["status"] == ReportStatus.SUBMITTED
    assert submitted["submitted_by_user_id"] == "officer-submit-2"
    assert submitted["compiled_by_user_id"] == GRANT_OFFICER_COMPILE_ID
    assert submitted["installation_count"] == 1
    assert submitted["grant_share_cents"] == 1729
    assert_instant_equals(submitted["submitted_at"], "2026-08-01T00:00:00Z", "submitted_at")


def test_06_the_six_roles_are_peers_that_share_reads_and_not_writes(api):
    """One zone read answers for three different roles, while three exclusive writes -
    including one attempted by the broadest reader - are all refused.

    PRD: "| GET | `/crr/zones/{id}` | Retrieves one risk zone... | `ProgramAdmin`,
    `RiskAnalyst`, `CanvassCoordinator`, `CrrTechnician`, `GrantOfficer`,
    `PartnerLiaison` |"

    Design: Corner/rbac/peer_roles_share_reads_but_exclusive_writes_are_rejected
    """
    pin_clock(api)
    zone = create_zone(api)
    partner = create_partner(api, contact_email="grants@firesafe.example")
    canonical = get_success_data(api.get_zone(zone["id"], ANALYST))

    for headers in (
        COORDINATOR,
        OFFICER,
        make_partner_liaison_headers(partner["id"]),
        headers_for(Role.CRR_TECHNICIAN, "00000000-0000-4000-8000-0000000000ff"),
    ):
        assert get_success_data(api.get_zone(zone["id"], headers)) == canonical

    validate_error(
        api.create_grant(
            f.grant_payload(partner["id"], grant_code="G-PEER-1"), COORDINATOR
        ),
        ApiErrorId.ROLE_NOT_PERMITTED,
        403,
    )
    validate_error(
        api.create_household(f.household_payload(zone["id"]), OFFICER),
        ApiErrorId.ROLE_NOT_PERMITTED,
        403,
    )
    validate_error(
        api.create_assessment(
            zone["id"], f.assessment_payload(canonical["version"]), ADMIN
        ),
        ApiErrorId.ROLE_NOT_PERMITTED,
        403,
    )

    _, grants = validate_paginated(api.list_grants(OFFICER))
    assert grants["total_count"] == 0
    _, households = validate_paginated(api.list_households(COORDINATOR))
    assert households["total_count"] == 0

    unchanged = read_zone(api, zone["id"])
    assert unchanged["assessment_status"] == AssessmentStatus.UNASSESSED
    assert unchanged["version"] == canonical["version"]
    assert unchanged["current_assessment_id"] is None
