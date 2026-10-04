"""Corner/rbac + Corner/errors + Corner/consistency_model."""
from test_helpers import (
    api_client, validate_success, validate_error, create_account,
    create_rate_card_payload, setup_police_verified_claim,
    make_contractor_manager_headers, make_jobsite_supervisor_headers,
    make_fleet_admin_headers, make_claims_adjuster_headers,
    create_jobsite, setup_agreement_with_assets, NON_EXISTENT_UUID, TEST_USERS,
)

ADMIN = TEST_USERS["fleet_admin_headers"]


def test_supervisor_cannot_create_rate_card_returns_forbidden(api):
    """PRD §2.1: "A request whose role is recognized but not permitted for the
    target endpoint is rejected with `ERR_FORBIDDEN` (HTTP 403)."
    PRD §4: "POST /fleet/rate-cards | Create a rate card; closed-interval
    overlap within a category is rejected | FleetAdmin"

    Design: Corner/rbac/supervisor_cannot_create_rate_card_returns_forbidden
    """
    js = make_jobsite_supervisor_headers("some-account-id")
    r = api_client.create_rate_card(create_rate_card_payload(code="RC-RB1"), js)
    validate_error(r, "ERR_FORBIDDEN")


def test_contractor_manager_cannot_decide_theft_claim_returns_forbidden(api):
    """PRD §2.1: "A request whose role is recognized but not permitted for the
    target endpoint is rejected with `ERR_FORBIDDEN` (HTTP 403)."
    PRD §4: "POST /fleet/theft-claims/{id}/decide | Approve or deny a
    POLICE_VERIFIED claim; decider must differ from verifier | ClaimsAdjuster"

    Design: Corner/rbac/contractor_manager_cannot_decide_theft_claim_returns_forbidden
    """
    env = setup_police_verified_claim(
        verifier="admin-rb2", filed_at="2026-09-01T06:00:00Z")
    cm = make_contractor_manager_headers(env["account_id"])
    r = api_client.decide_theft_claim(env["claim"]["id"], "APPROVE", cm)
    validate_error(r, "ERR_FORBIDDEN")


def test_missing_role_header_returns_unauthenticated(api):
    """PRD §2.1: "A request missing either header, or presenting a role string
    the platform does not recognize, is rejected with `ERR_UNAUTHENTICATED`
    (HTTP 401)."

    Design: Corner/errors/missing_role_header_returns_unauthenticated
    """
    account = create_account(credit_limit_cents=1000)
    r = api_client.get_account(account["id"], headers={"X-User-ID": "nobody"})
    validate_error(r, "ERR_UNAUTHENTICATED", expected_status=401)


def test_nonexistent_asset_returns_not_found(api):
    """PRD §2.9: "each id must exist, and each child must belong to the
    embedding parent named to its left. A violation anywhere in the chain is
    reported as `ERR_NOT_FOUND` (HTTP 404)."

    Design: Corner/errors/nonexistent_asset_returns_not_found
    """
    r = api_client.get_asset(NON_EXISTENT_UUID, ADMIN)
    validate_error(r, "ERR_NOT_FOUND")


def test_cross_account_jobsite_deploy_returns_not_found(api):
    """PRD §2.9: "References that cross account boundaries are deliberately
    hidden the same way — for example, deploying an asset to a jobsite owned by
    a different account yields `ERR_NOT_FOUND`, not an authorization error, so
    the existence of other tenants' resources is never disclosed."

    Design: Corner/errors/cross_account_jobsite_deploy_returns_not_found
    """
    env = setup_agreement_with_assets(n_assets=1)
    account_b = create_account()
    site_b = create_jobsite(account_b["id"], capacity_assets=5)
    r = api_client.deploy_asset(env["asset_ids"][0], site_b["id"], env["js"])
    validate_error(r, "ERR_NOT_FOUND")


def test_theft_decide_by_verifier_returns_duty_segregation(api):
    """PRD §3.7: "the deciding adjuster's `X-User-ID` must differ from the
    claim's `verified_by`; the verifier deciding their own claim is rejected
    with `ERR_DUTY_SEGREGATION`."

    Design: Corner/errors/theft_decide_by_verifier_returns_duty_segregation
    """
    env = setup_police_verified_claim(
        verifier="ops-shared", filed_at="2026-09-01T06:00:00Z")
    r = api_client.decide_theft_claim(
        env["claim"]["id"], "APPROVE", make_claims_adjuster_headers("ops-shared"))
    validate_error(r, "ERR_DUTY_SEGREGATION")
    r = api_client.decide_theft_claim(
        env["claim"]["id"], "APPROVE", make_claims_adjuster_headers("adj-other"))
    claim = validate_success(r)
    assert claim["status"] == "APPROVED"


def test_error_envelope_shape_on_failure(api):
    """PRD §2.2: "The `meta` object for error responses contains only
    `api_request_id` and `api_request_timestamp`."
    PRD §2.2: "The `data` field contains the resource object or an array of
    resource objects."

    Design: Corner/consistency_model/error_envelope_shape_on_failure
    """
    account = create_account(credit_limit_cents=1000)
    r = api_client.get_account(account["id"], headers={"X-User-ID": "nobody"})
    err = validate_error(r, "ERR_UNAUTHENTICATED", expected_status=401)
    assert isinstance(err["message"], str) and len(err["message"].strip()) > 0
    body = r.json()
    assert body["response_type"] == "error"
    assert "api_request_id" in body["meta"]
    assert "api_request_timestamp" in body["meta"]
    r = api_client.get_account(account["id"], ADMIN)
    data = validate_success(r)
    assert data["id"] == account["id"]
