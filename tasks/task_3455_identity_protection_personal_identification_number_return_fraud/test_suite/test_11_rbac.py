"""Authentication and role-authorization tests: missing headers, role
denials, and entity-backed ownership scoping.

PRD section 2.1 (with the endpoint role tables of section 4).
"""
from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    create_active_config,
    create_filter_model_config_payload,
    create_return_payload,
    create_taxpayer,
    file_return,
    get_return,
    make_taxpayer_headers,
    set_clock,
    setup_held_return,
    validate_error,
    validate_success,
)

ADMIN = TEST_USERS["system_admin_headers"]
ANALYST = TEST_USERS["fraud_analyst_headers"]
AGENT = TEST_USERS["verification_agent_headers"]


def test_list_returns_missing_auth_headers(api):
    """PRD section 2.1: "Every request must carry two HTTP headers:
    `X-User-ID`, identifying the acting user, and `X-User-Role`, naming their
    operational capacity. A request with either header missing or empty is
    rejected with `ERR_UNAUTHENTICATED` (HTTP 401)."

    Design: Corner/validations/list_returns_missing_auth_headers
    """
    resp = api.list_tax_returns(None)
    validate_error(resp, ApiErrorId.ERR_UNAUTHENTICATED)


def test_analyst_cannot_activate_config(api):
    """PRD section 2.1: "Each endpoint declares the roles permitted to call
    it (see §4); a caller whose role is not in an endpoint's role list is
    rejected with `ERR_UNAUTHORIZED` (HTTP 403)."
    PRD section 4: the `POST /identity-protection/filter-model-configs/{id}/activate`
    row authorizes SystemAdmin only.

    Design: Corner/rbac/analyst_cannot_activate_config
    """
    cfg = validate_success(
        api.create_filter_model_config(
            create_filter_model_config_payload(model_version="MV-RBAC"), ADMIN
        ),
        201,
    )
    assert cfg["status"] == "DRAFT"

    resp = api.activate_filter_model_config(cfg["id"], ANALYST)
    validate_error(resp, ApiErrorId.ERR_UNAUTHORIZED)

    reread = validate_success(api.get_filter_model_config(cfg["id"], ADMIN), 200)
    assert reread["status"] == "DRAFT"


def test_taxpayer_cannot_read_others_return(api):
    """PRD section 2.1: "When `X-User-Role` is `Taxpayer`, `X-User-ID` is the
    `id` of the acting `Taxpayer` record; ownership checks on any resource
    that references a taxpayer — returns, reports, pins, verification cases,
    advocate cases, appointments, holds, disbursements, and claims — compare
    the resource's taxpayer foreign key to `X-User-ID`, and acting on another
    taxpayer's resource is rejected with `ERR_UNAUTHORIZED` (HTTP 403)."

    Design: Corner/rbac/taxpayer_cannot_read_others_return
    """
    create_active_config(model_version="MV-OWN")
    owner = create_taxpayer()
    stranger = create_taxpayer()
    rtn = file_return(owner["id"], claimed_refund_cents=1000,
                      bank_product="NONE")

    resp = api.get_tax_return(rtn["id"], make_taxpayer_headers(stranger["id"]))
    validate_error(resp, ApiErrorId.ERR_UNAUTHORIZED)


def test_verification_agent_cannot_confirm_fraud(api):
    """PRD section 2.1: "Each endpoint declares the roles permitted to call
    it (see §4); a caller whose role is not in an endpoint's role list is
    rejected with `ERR_UNAUTHORIZED` (HTTP 403)."
    PRD section 4: the `POST
    /identity-protection/tax-returns/{id}/confirm-fraud` row authorizes
    FraudAnalyst only.

    Design: Corner/rbac/verification_agent_cannot_confirm_fraud
    """
    set_clock("2027-02-01T00:00:00Z")
    _taxpayer, rtn, _hold = setup_held_return()

    resp = api.confirm_fraud(rtn["id"], AGENT)
    validate_error(resp, ApiErrorId.ERR_UNAUTHORIZED)
    assert get_return(rtn["id"])["status"] == "FILTER_HELD"
