"""Authentication, role authorisation, ownership, segregation of duties and OCC."""

import pytest

from test_helpers import (
    ApiErrorId,
    NO_AUTH_HEADERS,
    TEST_USERS,
    build_user_headers,
    create_agreement,
    create_land_manager,
    create_land_manager_from,
    create_permit,
    make_land_manager_headers,
    make_volunteer_headers,
    minimal_land_manager_payload,
    party_version,
    read_agreement,
    read_party,
    read_permit,
    read_shift,
    read_volunteer,
    setup_approved_plan,
    setup_party_with_sawyer,
    setup_registry,
    setup_verified_sawyer_hours,
    submit_agreement,
    validate_error,
    validate_success,
)

COORD = TEST_USERS["coordinator_headers"]
GRANTS = TEST_USERS["grants_admin_headers"]


def test_a_request_without_auth_headers_is_rejected_before_anything_else(api):
    """PRD 2.1: "Every request to the API must carry two headers: `X-User-ID`, identifying the acting principal, and `X-User-Role`, naming the role that principal is acting under. If either header is absent, or if `X-User-Role` is not one of the six declared role names, the request is rejected with `ERR_UNAUTHENTICATED` (HTTP 401)."
    PRD 2.7: "Authentication — both headers present, role among the six declared names (`ERR_UNAUTHENTICATED`)."

    Design: Corner/rbac/unauthenticated_request_missing_header_returns_401
    """
    manager = create_land_manager()

    response = api.get_land_manager(manager["id"], NO_AUTH_HEADERS)
    validate_error(response, ApiErrorId.ERR_UNAUTHENTICATED.value, 401)

    authorised = api.get_land_manager(manager["id"], COORD)
    assert authorised.status_code == 200
    validate_success(authorised)


def test_a_volunteer_may_not_review_an_adoption_agreement(api):
    """PRD 2.1: "If the headers are well-formed but the named role is not among the roles authorised for the endpoint being called (see the endpoint table in section 4), the request is rejected with `ERR_FORBIDDEN_ROLE` (HTTP 403)."
    PRD 2.1: "A `StewardshipCoordinator` is stewardship-organisation staff who reviews adoptions and plans, triages and disposes of condition reports, approves requisitions and verifies volunteer hours."
    PRD 3.2: "Review is a `StewardshipCoordinator` decision carrying a `decision` value and, where the decision is a return, a `reason`."

    Design: Corner/rbac/volunteer_cannot_review_an_adoption_agreement
    """
    world = setup_registry()
    agreement = create_agreement(world["seg_id"], world["lead_id"])
    submitted = submit_agreement(agreement["id"], world["lead_id"])
    assert submitted["status"] == "SUBMITTED"

    response = api.review_adoption_agreement(
        agreement["id"], {"decision": "APPROVE"}, make_volunteer_headers(world["gen_id"])
    )
    validate_error(response, ApiErrorId.ERR_FORBIDDEN_ROLE.value, 403)

    stored = read_agreement(agreement["id"])
    assert stored["status"] == "SUBMITTED"
    assert stored["reviewed_by_user_id"] is None


def test_a_crew_leader_may_not_read_the_grant_match_figures(api):
    """PRD 3.7: "**The grant match** is a read-only computed view over a plan, available to a `StewardshipCoordinator` or a `GrantsAdministrator`, and it persists nothing."
    PRD 2.1: "If the headers are well-formed but the named role is not among the roles authorised for the endpoint being called (see the endpoint table in section 4), the request is rejected with `ERR_FORBIDDEN_ROLE` (HTTP 403)."

    Design: Corner/rbac/crew_leader_cannot_read_the_grant_match_figures
    """
    world = setup_approved_plan()

    refused = api.get_grant_match(
        world["plan_id"], world["lead_headers"], params={"variant": "CERTIFIED"}
    )
    validate_error(refused, ApiErrorId.ERR_FORBIDDEN_ROLE.value, 403)

    allowed = api.get_grant_match(
        world["plan_id"], GRANTS, params={"variant": "CERTIFIED"}
    )
    assert allowed.status_code == 200
    figures = validate_success(allowed)
    assert float(figures["grant_match_total_usd"]) == pytest.approx(0.00, abs=0.001)


def test_an_officer_of_another_agency_may_not_decide_this_permit(api):
    """PRD 2.1: "When `X-User-Role` is `LandManagerOfficer`, `X-User-ID` is the `id` of the acting `LandManager`; issuing or denying a permit, revoking a permit, activating an agreement and terminating a suspended agreement all compare `X-User-ID` against the `land_manager_id` that governs the resource in question."
    PRD 2.1: "Any of those ownership comparisons that fails yields `ERR_NOT_RESOURCE_OWNER` (HTTP 403)."
    PRD 3.5: "The decision belongs to a `LandManagerOfficer` whose `X-User-ID` equals the permit's `land_manager_id`, and it carries a `decision` value."

    Design: Corner/rbac/officer_of_another_agency_cannot_issue_this_permit
    """
    world = setup_approved_plan()
    other_agency = create_land_manager_from(minimal_land_manager_payload())
    permit = create_permit(
        world["plan_id"],
        world["seg_id"],
        world["lead_id"],
        requested_work_types=["TREAD_WORK"],
    )
    assert permit["land_manager_id"] == world["lm_id"]

    issue_payload = {
        "decision": "ISSUE",
        "allowed_work_types": ["TREAD_WORK"],
        "max_party_size": 10,
    }
    refused = api.decide_work_permit(
        permit["id"], issue_payload, make_land_manager_headers(other_agency["id"])
    )
    validate_error(refused, ApiErrorId.ERR_NOT_RESOURCE_OWNER.value, 403)

    issued = validate_success(
        api.decide_work_permit(permit["id"], issue_payload, world["lm_headers"])
    )
    assert issued["status"] == "ISSUED"
    assert read_permit(permit["id"])["issued_by_user_id"] == world["lm_id"]


def test_only_a_grants_administrator_who_did_not_verify_may_certify_the_hours(api):
    """PRD 3.7: "Certification is the `GrantsAdministrator`'s act and moves the shift `HOURS_VERIFIED → HOURS_CERTIFIED`."
    PRD 3.7: "It is refused with `ERR_SEGREGATION_OF_DUTIES` when the acting `X-User-ID` equals the `hours_verified_by_user_id` already on the shift — the person who certifies hours may never be the person who verified them."
    PRD 2.7: "Role authorisation — the acting role appears in the endpoint's authorised list (`ERR_FORBIDDEN_ROLE`)."
    PRD 2.7: "Segregation of duties (`ERR_SEGREGATION_OF_DUTIES`), applying to shift certification and incident closure."

    Design: Corner/rbac/coordinator_cannot_certify_hours_that_only_grants_admin_may_certify
    """
    world = setup_verified_sawyer_hours()
    assert world["shift_saw"]["hours_verified_by_user_id"] == "coord-1"

    wrong_role = api.certify_shift_hours(world["shift_saw_id"], COORD)
    validate_error(wrong_role, ApiErrorId.ERR_FORBIDDEN_ROLE.value, 403)

    same_person = api.certify_shift_hours(
        world["shift_saw_id"], build_user_headers("coord-1", "GrantsAdministrator")
    )
    validate_error(same_person, ApiErrorId.ERR_SEGREGATION_OF_DUTIES.value, 403)

    certified = validate_success(api.certify_shift_hours(world["shift_saw_id"], GRANTS))
    assert certified["status"] == "HOURS_CERTIFIED"
    assert certified["hours_certified_by_user_id"] == "grants-1"
    assert float(read_volunteer(world["saw_id"])["certified_hours"]) == 6.50


def test_a_stale_work_party_version_rejects_the_next_registration(api):
    """PRD 2.8: "Registering a volunteer onto a work party's roster requires a non-optional `expected_work_party_version` field in the request, carrying the client's last observed `version` of that work party. If it does not equal the work party's current `version`, the registration is rejected with `ERR_STALE_WORK_PARTY_VERSION` and HTTP status 412."
    PRD 2.8: "Every roster mutation advances the work party's `version` — registration, withdrawal, cascade withdrawal, briefing, and any readiness recompute — so a client that registered once and then reuses its original version number is by definition stale."

    Design: Corner/cross_cutting_complexity_layers/stale_work_party_version_rejects_registration
    """
    world = setup_party_with_sawyer()
    stale_version = world["party_version_after_briefing"]

    stale = api.register_shift(
        world["party_id"],
        {
            "volunteer_id": world["gen_id"],
            "expected_work_party_version": stale_version,
            "role_on_crew": "CREW_MEMBER",
        },
        world["lead_headers"],
    )
    validate_error(stale, ApiErrorId.ERR_STALE_WORK_PARTY_VERSION.value, 412)
    assert read_party(world["party_id"])["registered_count"] == 1

    retry = validate_success(
        api.register_shift(
            world["party_id"],
            {
                "volunteer_id": world["gen_id"],
                "expected_work_party_version": party_version(world["party_id"]),
                "role_on_crew": "CREW_MEMBER",
            },
            world["lead_headers"],
        ),
        201,
    )
    assert read_shift(retry["id"])["status"] == "REGISTERED"
    assert read_party(world["party_id"])["registered_count"] == 2
