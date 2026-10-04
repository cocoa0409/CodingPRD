"""Authentication, role membership and the agency-of-record ownership gate."""
from test_helpers import (
    api_client,
    create_agency,
    create_zone,
    make_agency_producer_headers,
    setup_reviewed_appraisal_property,
    setup_submitted_enrollment,
    validate_error,
    validate_success,
)

NON_EXISTENT_ID = "00000000-0000-4000-8000-000000000000"


def test_an_absent_role_header_is_refused_before_any_lookup(api):
    """PRD 2.1: "A request missing either header, or naming a role the platform does
    not recognize, is refused with `ERR_UNAUTHENTICATED`"
    PRD 2.11: "Authentication is evaluated first (priority 1), then role membership
    (priority 2), then left-to-right resolution of path identifiers (priority 3)."

    Design: Corner/errors/unrecognized_role_is_refused_before_any_resource_lookup
    """
    res = api_client.get_property(NON_EXISTENT_ID, {})
    validate_error(res, "ERR_UNAUTHENTICATED", expected_status=401)


def test_the_authentication_gate_precedes_the_not_found_gate(
        api, anonymous_headers, underwriter_headers):
    """PRD 2.1: "A request missing either header, or naming a role the platform does
    not recognize, is refused with `ERR_UNAUTHENTICATED`"

    Design: Corner/errors/unrecognized_role_is_refused_before_any_resource_lookup
    """
    res = api_client.get_property(NON_EXISTENT_ID, anonymous_headers)
    validate_error(res, "ERR_UNAUTHENTICATED", expected_status=401)

    # A recognized role reading a resolvable resource succeeds.
    zone = create_zone(zone_code="ZAUTH")
    validate_success(api_client.get_risk_zone(zone["id"], underwriter_headers), 200)


def test_an_unallocated_agency_id_resolves_as_not_found(api, underwriter_headers):
    """PRD 2.5: "the server resolves those identifiers strictly left to right and
    rejects the request with `ERR_NOT_FOUND` at the first one that does not correspond
    to a stored record."

    Design: Corner/entities/agency_get_with_unknown_id_returns_not_found
    """
    res = api_client.get_agency(NON_EXISTENT_ID, underwriter_headers)
    validate_error(res, "ERR_NOT_FOUND", expected_status=404)
    body = res.json()
    assert body["response_type"] == "error"
    assert isinstance(body["data"]["message"], str) and body["data"]["message"]
    assert body["meta"]["api_request_id"]


def test_a_recognized_role_outside_the_endpoint_roles_is_forbidden(
        api, underwriter_headers):
    """PRD 2.1: "a request whose role is not among the roles the target operation
    admits is refused with `ERR_FORBIDDEN`."
    PRD 2.1: "Note that an unrecognized role is a 401 while a recognized-but-unlisted
    role is a 403 — the two gates are distinct."

    Design: Corner/rbac/agency_producer_cannot_reach_the_underwriting_write_surface
    """
    zone, agency, prop, enroll = setup_submitted_enrollment(
        zone_code="ZRBAC", agency_code="AGRBAC")
    res = api_client.approve_enrollment(enroll["id"],
                                        make_agency_producer_headers(agency["id"]))
    validate_error(res, "ERR_FORBIDDEN", expected_status=403)


def test_the_producer_role_is_refused_every_underwriter_exclusive_write(
        api, underwriter_headers):
    """PRD 2.1: "The `Underwriter` is the binding authority — posture derivation,
    appraisal approval and provision, enrollment approval and attachment, mitigation
    imposition and waiver, non-renewal issuance and vendor dispatch all sit with this
    role."

    Design: Corner/rbac/agency_producer_cannot_reach_the_underwriting_write_surface
    """
    zone, agency, prop, enroll = setup_submitted_enrollment(
        zone_code="ZRBAC2", agency_code="AGRBAC2")
    producer = make_agency_producer_headers(agency["id"])

    forbidden = [
        api_client.approve_enrollment(enroll["id"], producer),
        api_client.posture_eval(prop["id"], prop["version"], producer),
        api_client.poll_vendors(zone["id"], producer),
    ]
    for res in forbidden:
        validate_error(res, "ERR_FORBIDDEN", expected_status=403)

    # The same producer can still read the enrollment.
    validate_success(api_client.get_enrollment(enroll["id"], producer), 200)


def test_a_risk_consultant_cannot_approve_an_appraisal(
        api, underwriter_headers, risk_consultant_headers):
    """PRD 2.1: "The `RiskConsultant` performs the complimentary on-site visit and
    verifies completed mitigation work."

    Design: Corner/rbac/risk_consultant_cannot_impose_a_compliance_decision
    """
    zone, agency, prop, appr = setup_reviewed_appraisal_property(
        zone_code="ZRCON", agency_code="AGRCON")
    res = api_client.approve_appraisal(appr["id"], risk_consultant_headers)
    validate_error(res, "ERR_FORBIDDEN", expected_status=403)


def test_a_risk_consultant_can_impose_and_verify_but_not_waive(
        api, underwriter_headers, risk_consultant_headers):
    """PRD 3.3: "An underwriter or a risk consultant imposes one by naming the
    `requirement_code`"
    PRD 3.3: "A requirement may be waived by an underwriter on a supplied `reason`,
    which sets it to `WAIVED`"

    Design: Corner/rbac/risk_consultant_cannot_impose_a_compliance_decision
    """
    zone, agency, prop, appr = setup_reviewed_appraisal_property(
        zone_code="ZRCON2", agency_code="AGRCON2")

    imposed = validate_success(api_client.create_mitigation_requirement(
        prop["id"],
        {"requirement_code": "DEFENSIBLE_SPACE", "band_awarded": "CLEARED",
         "source": "RISK_CONSULTANT", "due_on": "2026-12-01T00:00:00Z"},
        risk_consultant_headers), 201)
    verified = validate_success(api_client.verify_mitigation_requirement(
        imposed["id"], "CLEARED", risk_consultant_headers, verification_count=0), 200)
    assert verified["status"] == "VERIFIED"

    refused = api_client.waive_mitigation_requirement(
        imposed["id"], "consultant opinion", risk_consultant_headers)
    validate_error(refused, "ERR_FORBIDDEN", expected_status=403)


def test_the_adjuster_and_the_underwriter_hold_disjoint_surfaces(
        api, underwriter_headers, claims_adjuster_headers):
    """PRD 2.1: "The `ClaimsAdjuster` handles first-party losses."
    PRD 2.1: "The `Underwriter` is the binding authority"

    Design: Corner/rbac/claims_adjuster_cannot_underwrite_and_underwriter_cannot_adjust
    """
    zone, agency, prop, enroll = setup_submitted_enrollment(
        zone_code="ZPEER", agency_code="AGPEER")

    adjuster_attempt = api_client.approve_enrollment(enroll["id"], claims_adjuster_headers)
    validate_error(adjuster_attempt, "ERR_FORBIDDEN", expected_status=403)

    underwriter_attempt = api_client.create_claim(
        enroll["id"],
        {"cause_of_loss": "WIND", "loss_date": "2026-09-20T00:00:00Z",
         "reported_indemnity_cents": 100_000_000},
        underwriter_headers)
    validate_error(underwriter_attempt, "ERR_FORBIDDEN", expected_status=403)

    # The adjuster can still read the enrollment.
    validate_success(api_client.get_enrollment(enroll["id"], claims_adjuster_headers), 200)


def test_the_platform_operator_alone_owns_reference_configuration(
        api, underwriter_headers, platform_admin_headers):
    """PRD 2.1: "The `PlatformAdmin` owns reference configuration and the logical
    clock."

    Design: Corner/errors/unrecognized_role_is_refused_before_any_resource_lookup
    """
    res = api_client.create_risk_zone({
        "zone_code": "ZADMIN", "state_code": "CA",
        "wildland_urban_interface_band": "OUTSIDE_WUI",
        "sustained_wind_mph": 20, "mitigation_band_multiplier": 1.0,
        "mitigated_loss_multiplier": 1.0,
        "exposure_band": "STANDARD"}, underwriter_headers)
    validate_error(res, "ERR_FORBIDDEN", expected_status=403)

    validate_success(api_client.create_risk_zone({
        "zone_code": "ZADMIN", "state_code": "CA",
        "wildland_urban_interface_band": "OUTSIDE_WUI",
        "sustained_wind_mph": 20, "mitigation_band_multiplier": 1.0,
        "mitigated_loss_multiplier": 1.0, "exposure_band": "STANDARD"},
        platform_admin_headers), 201)


def test_a_non_writing_regulatory_role_can_read_but_not_write(
        api, underwriter_headers, compliance_reporter_headers):
    """PRD 2.1: "The `ComplianceReporter` is a non-writing regulatory audience"

    Design: Corner/rbac/agency_producer_cannot_reach_the_underwriting_write_surface
    """
    zone, agency, prop, enroll = setup_submitted_enrollment(
        zone_code="ZCOMP", agency_code="AGCOMP")

    validate_success(api_client.get_enrollment(enroll["id"], compliance_reporter_headers), 200)
    validate_success(api_client.get_property(prop["id"], compliance_reporter_headers), 200)
    validate_success(api_client.get_risk_zone(zone["id"], compliance_reporter_headers), 200)
    # PRD 4's endpoint table admits ComplianceReporter to the wildfire-dispatch
    # reads, so the non-writing audience can reach the loss surfaces too.
    validate_success(api_client.list_property_dispatches(
        prop["id"], compliance_reporter_headers), 200)

    res = api_client.approve_enrollment(enroll["id"], compliance_reporter_headers)
    validate_error(res, "ERR_FORBIDDEN", expected_status=403)


def test_extra_payload_fields_do_not_steer_server_managed_state(
        api, underwriter_headers, platform_admin_headers):
    """PRD 2.6: "`version` is a system-managed integer that increments with each
    modification"
    PRD 2.2: "Unless otherwise noted, operations that create or modify a resource will
    return the created or updated resource object in the data field."

    Design: Corner/entities/property_create_omitting_grid_risk_block_defaults_to_ungrouped
    """
    zone = create_zone(zone_code="ZMASS")
    agency = create_agency(agency_code="AGMASS")

    prop = validate_success(api_client.create_property({
        "risk_zone_id": zone["id"], "agency_id": agency["id"],
        "address_line": "7 Corner Rd", "status": "APPROVED",
        "version": 99, "base_posture": "UNDERWRITABLE"}, underwriter_headers), 201)
    # A create cannot dictate its own gate or counter.
    assert prop["base_posture"] == "PENDING_APPRAISAL"
    assert prop["posture"] == "WRITE_FROZEN"
    assert isinstance(prop["version"], int)