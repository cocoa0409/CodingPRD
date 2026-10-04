"""RBAC and request-validation refusals: role exclusivity, org-ownership
gating, and malformed request bodies.
"""
import pytest

from test_helpers import (
    api_client, COORDINATOR,
    validate_success, validate_error, get_success_data,
    ApiErrorId,
    set_clock, create_network, create_org,
    setup_routed_referral, get_referral,
    make_case_worker_headers, make_org_admin_headers, make_funder_admin_headers,
)


def test_orgadmin_cannot_create_organizations():
    """PRD §2.1: "A request whose role is not permitted for the target endpoint
    is rejected with `ERR_UNAUTHORIZED_ROLE` (HTTP 403)."
    PRD §4: the `POST /care-network/organizations` row of the endpoint
    inventory authorizes only `NetworkCoordinator`.

    Design: Corner/rbac/orgadmin_cannot_create_organizations
    """
    set_clock()
    create_network()
    receiver = create_org("Receiver R", "CBO", "EIN-R", activate=False)
    validate_error(api_client.create_organization(
        {"name": "Rogue Org", "org_type": "CBO", "ein": "EIN-X"},
        make_org_admin_headers(receiver["id"])),
        ApiErrorId.ERR_UNAUTHORIZED_ROLE, expected_status=403)


def test_funderadmin_cannot_accept_referral():
    """PRD §2.1: "A request whose role is not permitted for the target endpoint
    is rejected with `ERR_UNAUTHORIZED_ROLE` (HTTP 403)."
    PRD §4: the `POST /care-network/referrals/{id}/accept` row of the endpoint
    inventory authorizes only `OrgAdmin`.

    Design: Corner/rbac/funderadmin_cannot_accept_referral
    """
    ctx, referral = setup_routed_referral(with_funder=True)
    validate_error(api_client.accept_referral(
        referral["id"], make_funder_admin_headers(ctx["funder_id"])),
        ApiErrorId.ERR_UNAUTHORIZED_ROLE, expected_status=403)
    assert get_referral(referral["id"])["status"] == "ROUTED"


def test_wrong_receiver_org_accept_returns_forbidden_org():
    """PRD §3.5: "Accepting moves `ROUTED` → `ACCEPTED` and requires the
    caller's organization to be the current `receiver_org_id` (else
    `ERR_FORBIDDEN_ORG`)".
    PRD §2.1: "Org-ownership checks — for example, a receiver-only action
    requiring the caller's organization to equal the referral's
    `receiver_org_id` — compare the org-id prefix of `X-User-ID`; a mismatch is
    rejected with `ERR_FORBIDDEN_ORG` (HTTP 403)."

    Design: Corner/rbac/wrong_receiver_org_accept_returns_forbidden_org
    """
    ctx, referral = setup_routed_referral()
    # A second ACTIVE CBO that is NOT the referral's receiver.
    other = create_org("Receiver R2", "CBO", "EIN-R2")

    validate_error(api_client.accept_referral(
        referral["id"], make_org_admin_headers(other["id"])),
        ApiErrorId.ERR_FORBIDDEN_ORG, expected_status=403)
    assert get_referral(referral["id"])["status"] == "ROUTED"


def test_org_registration_missing_ein_returns_invalid_request():
    """PRD §2.6: "then request well-formedness — a request with a missing
    required field, an invalid enum value, an unknown field, or a foreign-key
    target that does not exist is rejected with `ERR_INVALID_REQUEST` (HTTP
    400)".
    PRD §3.2: "A `NetworkCoordinator` registers each participant organization
    with a legal `name`, an `org_type` of `CBO`, `CLINIC`, or `FUNDER`, and a
    tax identifier `ein` that is unique across the network."

    Design: Corner/validations/org_registration_missing_ein_returns_invalid_request
    """
    set_clock()
    validate_error(api_client.create_organization(
        {"name": "Receiver R", "org_type": "CBO"}, COORDINATOR),
        ApiErrorId.ERR_INVALID_REQUEST, expected_status=400)


def test_invalid_gender_enum_returns_invalid_request():
    """PRD §2.6: "then request well-formedness — a request with a missing
    required field, an invalid enum value, an unknown field, or a foreign-key
    target that does not exist is rejected with `ERR_INVALID_REQUEST` (HTTP
    400)".
    PRD §3.5: "A `CaseWorker` registers a `Client` with a `full_name`, a
    `date_of_birth` (an ISO `YYYY-MM-DD` date used for age evaluation at
    referral time), a residential `zip_code`, and a `gender` of `FEMALE`,
    `MALE`, `NONBINARY`, or `UNDISCLOSED`."

    Design: Corner/validations/invalid_gender_enum_returns_invalid_request
    """
    set_clock()
    sender = create_org("Sender S", "CLINIC", "EIN-S", activate=False)
    validate_error(api_client.create_client(
        {"full_name": "K", "date_of_birth": "1990-01-01", "zip_code": "94110",
         "gender": "ALIEN"},
        make_case_worker_headers(sender["id"])),
        ApiErrorId.ERR_INVALID_REQUEST, expected_status=400)
