"""Authentication and authorization: missing headers, role denials on
credentialing and triage, and entity-backed ownership on volunteer records."""
from test_helpers import (
    AVAILABILITY_WINDOW,
    ApiErrorId,
    add_certification,
    get_certification,
    get_work_order,
    intake_work_order,
    make_partner_liaison_headers,
    make_volunteer_headers,
    register_partner,
    register_volunteer,
    set_clock,
    setup_assessed_incident,
    validate_error,
    validate_success,
)


def test_missing_auth_headers_rejected(api):
    """PRD §2.1: "Each request must include `X-User-ID` to identify the acting user and `X-User-Role` to specify their operational capacity. A request in which either header is missing or malformed is rejected with `ERR_UNAUTHENTICATED` (HTTP 401)."

    Design: Corner/errors/volunteer_create_missing_auth_header
    """
    resp = api.create_volunteer(
        {
            "full_name": "No Headers",
            "email": "nh@x.org",
            "home_region": "TX-GULF",
            "skills": ["DEBRIS"],
        },
        {},
    )
    validate_error(resp, ApiErrorId.ERR_UNAUTHENTICATED)


def test_volunteer_cannot_verify_certification(api, safety_officer_headers):
    """PRD §2.1: "Access to specific operations is restricted by role; an attempt to perform an action outside the acting role's granted set, or one that fails an entity-backed ownership check, is rejected with `ERR_UNAUTHORIZED` (HTTP 403)."
    PRD §2.1: "A `SafetyOfficer` is the credentialing and wellness authority: vets volunteers and manages readiness transitions, verifies, rejects, revokes, and renews certifications, clears safety holds, and resolves wellness checks." (certification transitions are the SafetyOfficer's alone; the Volunteer role is not listed for PATCH /vdr/certifications/{id}.)

    Design: Corner/rbac/volunteer_cannot_verify_own_certification
    """
    set_clock()
    volunteer = register_volunteer(
        full_name="Self Cert", email="self@x.org", skills=["CHAINSAW"],
        availability_windows=[],
    )
    cert = add_certification(volunteer["id"], kind="CHAINSAW")
    resp = api.patch_certification(
        cert["id"], {"status": "VERIFIED"}, make_volunteer_headers(volunteer["id"])
    )
    validate_error(resp, ApiErrorId.ERR_UNAUTHORIZED)
    after = get_certification(cert["id"])
    assert after["status"] == "PENDING_VERIFICATION"


def test_partner_liaison_cannot_triage_work_order(api):
    """PRD §2.1: "an attempt to perform an action outside the acting role's granted set, or one that fails an entity-backed ownership check, is rejected with `ERR_UNAUTHORIZED` (HTTP 403)."
    PRD §3.6: "Triage is the `IntakeCoordinator`'s OCC-guarded judgment: the request must carry `expected_work_order_version` matching the work order's current `version`, and a stale version is rejected with `ERR_STALE_VERSION` (HTTP 412) because a superseding triage has already landed." (triage is granted to the IntakeCoordinator, not to PartnerLiaison.)

    Design: Corner/rbac/partner_liaison_cannot_triage
    """
    set_clock()
    partner = register_partner(
        name="County EM", kind="EMERGENCY_MANAGEMENT", contact_email="em@county.gov",
    )
    incident = setup_assessed_incident(severity=3, affected_households=40, name="Storm A")
    liaison = make_partner_liaison_headers(partner["id"])
    work_order = intake_work_order(
        incident["id"], headers=liaison,
        requester_name="Referred Owner", hazard_kind="MUCK_OUT",
        vulnerable_resident=True, municipality_sourced=True,
        source_partner_id=partner["id"],
    )
    resp = api.triage_work_order(
        work_order["id"],
        {"expected_work_order_version": work_order["version"]},
        liaison,
    )
    validate_error(resp, ApiErrorId.ERR_UNAUTHORIZED)
    after = get_work_order(work_order["id"])
    assert after["status"] == "INTAKE"


def test_volunteer_cannot_patch_other_volunteer_availability(api, system_admin_headers):
    """PRD §2.1: "When `X-User-Role` is `Volunteer`, `X-User-ID` is the `id` of the acting `Volunteer`; ownership checks on any resource that references a volunteer — a deployment offer, a volunteer record's `availability_windows`, a training enrollment — compare the resource's volunteer foreign-key field to `X-User-ID`, and a mismatch is rejected with `ERR_UNAUTHORIZED`."

    Design: Corner/rbac/volunteer_cannot_patch_other_volunteer_availability
    """
    set_clock()
    v1 = register_volunteer(
        full_name="Ada Voss", email="ada@x.org", skills=["DEBRIS"], availability_windows=[],
    )
    v2 = register_volunteer(
        full_name="Bo Karr", email="bo@x.org", skills=["DEBRIS"], availability_windows=[],
    )
    resp = api.patch_volunteer(
        v2["id"],
        {"availability_windows": [dict(AVAILABILITY_WINDOW)]},
        make_volunteer_headers(v1["id"]),
    )
    validate_error(resp, ApiErrorId.ERR_UNAUTHORIZED)
    after = validate_success(api.get_volunteer(v2["id"], system_admin_headers), 200)
    assert after["availability_windows"] == []
