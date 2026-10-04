"""Role-based access control: authentication failure, and each role denied an
operation outside its authorized list.
"""
from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    api_client,
    create_certify_payload,
    create_chapter,
    create_donation_offer_payload,
    create_fulfillment_plan_payload,
    create_referral,
    create_referral_payload,
    create_volunteer_payload,
    get_fulfillment_plan,
    get_referral,
    get_wish,
    get_wish_version,
    make_volunteer_headers,
    set_clock,
    setup_determined_wish,
    setup_planning_wish,
    submit_plan,
    validate_error,
)

REFERRAL_SOURCE = TEST_USERS["referral_source_headers"]
WISH_COORDINATOR = TEST_USERS["wish_coordinator_headers"]
IN_KIND_OFFICER = TEST_USERS["in_kind_officer_headers"]


def test_referral_create_missing_auth_header_unauthenticated():
    """PRD section 2.1: "A request missing either header, or presenting a role
    outside the declared set, is rejected with `ERR_UNAUTHENTICATED`
    (HTTP 401)."

    Design: Corner/rbac/referral_create_missing_auth_header_unauthenticated
    """
    resp = api_client.create_referral(create_referral_payload(), {})
    validate_error(resp, ApiErrorId.ERR_UNAUTHENTICATED)


def test_referral_source_cannot_create_donation_offers():
    """PRD section 2.1: "When the role is declared but is not on the target
    endpoint's authorized list, the request is rejected with
    `ERR_FORBIDDEN_ROLE` (HTTP 403)."
    PRD section 4: POST /wish-grant/donation-offers is authorized for
    InKindOfficer only.

    Design: Corner/rbac/referral_source_cannot_create_donation_offers
    """
    resp = api_client.create_donation_offer(create_donation_offer_payload(),
                                            REFERRAL_SOURCE)
    validate_error(resp, ApiErrorId.ERR_FORBIDDEN_ROLE)


def test_volunteer_cannot_approve_plan():
    """PRD section 2.1: "When the role is declared but is not on the target
    endpoint's authorized list, the request is rejected with
    `ERR_FORBIDDEN_ROLE` (HTTP 403)."
    PRD section 4: POST /wish-grant/fulfillment-plans/{id}/approve is
    authorized for ChapterDirector and NationalDirector only — never for the
    entity-backed Volunteer, even one on the wish's team.

    Design: Corner/rbac/volunteer_cannot_approve_plan
    """
    ctx = setup_planning_wish(wish_type="RECEIVE_ITEM", cash_cost_cents=100000)
    submit_plan(ctx["plan"]["id"])
    resp = api_client.approve_plan(ctx["plan"]["id"],
                                   make_volunteer_headers(ctx["lead"]["id"]))
    validate_error(resp, ApiErrorId.ERR_FORBIDDEN_ROLE)
    assert get_fulfillment_plan(ctx["plan"]["id"])["status"] == "PENDING_APPROVAL"


def test_inkind_officer_cannot_manage_volunteers():
    """PRD section 2.1: "When the role is declared but is not on the target
    endpoint's authorized list, the request is rejected with
    `ERR_FORBIDDEN_ROLE` (HTTP 403)."
    PRD section 4: POST /wish-grant/volunteers is authorized for
    WishCoordinator only.

    Design: Corner/rbac/inkind_officer_cannot_manage_volunteers
    """
    chapter = create_chapter()
    resp = api_client.create_volunteer(
        create_volunteer_payload(chapter["id"]), IN_KIND_OFFICER)
    validate_error(resp, ApiErrorId.ERR_FORBIDDEN_ROLE)


def test_wish_coordinator_cannot_certify_referral():
    """PRD section 2.1: "When the role is declared but is not on the target
    endpoint's authorized list, the request is rejected with
    `ERR_FORBIDDEN_ROLE` (HTTP 403)."
    PRD section 4: POST /wish-grant/referrals/{id}/certify is authorized for
    MedicalProvider only.

    Design: Corner/rbac/wish_coordinator_cannot_certify_referral
    """
    set_clock()
    create_chapter(territory_zip_prefixes=["900"])
    referral = create_referral()
    resp = api_client.certify_referral(
        referral["id"], create_certify_payload("ONCOLOGY"), WISH_COORDINATOR)
    validate_error(resp, ApiErrorId.ERR_FORBIDDEN_ROLE)
    assert get_referral(referral["id"])["status"] == "PENDING_CERTIFICATION"


def test_national_director_cannot_create_plans():
    """PRD section 2.1: "When the role is declared but is not on the target
    endpoint's authorized list, the request is rejected with
    `ERR_FORBIDDEN_ROLE` (HTTP 403)."
    PRD section 4: POST /wish-grant/fulfillment-plans is authorized for
    WishCoordinator and ChapterDirector only.

    Design: Corner/rbac/national_director_cannot_create_plans
    """
    ctx = setup_determined_wish()
    wish = ctx["wish"]
    version = get_wish_version(wish["id"])
    resp = api_client.create_fulfillment_plan(
        create_fulfillment_plan_payload(wish["id"], version, 100000),
        TEST_USERS["national_director_headers"])
    validate_error(resp, ApiErrorId.ERR_FORBIDDEN_ROLE)
    after = get_wish(wish["id"])
    assert after["status"] == "DETERMINED"
    assert after["version"] == version, "the rejected creation must not advance Wish.version"
