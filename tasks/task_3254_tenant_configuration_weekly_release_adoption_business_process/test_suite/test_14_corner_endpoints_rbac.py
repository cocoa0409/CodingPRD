"""Corner queue B: endpoints (envelope/pagination, computed reads), errors, RBAC."""
from test_helpers import (
    api_client,
    get_success_data,
    validate_error,
    validate_paginated,
    admin_of,
    make_approver_headers,
    dev_headers,
    op_headers,
    ApiErrorId,
    create_definition,
    create_tenant,
)


def test_list_tenants_envelope_and_pagination(api):
    """PRD §2.2: "The `api_request_id` is a server-generated unique identifier
    for the request that starts with `req_`." and "The `response_type` is
    either "object" for a single resource or "array" for a list of resources."
    PRD §2.3: "All list endpoints accept the query parameters `limit` and
    `offset`. `limit` defaults to 10, with a minimum accepted value of 1 and a
    maximum of 100. `offset` defaults to 0. List responses order results by
    `created_at` ascending. The `meta` object of a list response carries four
    pagination fields: `limit`, `offset`, `total_count`, and `has_more`."

    Design: Corner/endpoints/response_envelope_and_pagination
    """
    for name in ("T-P1", "T-P2", "T-P3"):
        create_tenant(name, kind="PRODUCTION" if name != "T-P3" else "SANDBOX")

    data, meta = validate_paginated(api_client.list_tenants(op_headers()))
    assert meta["limit"] == 10, "default limit is 10"
    assert meta["offset"] == 0
    assert meta["total_count"] == 3
    assert meta["has_more"] is False

    body = api_client.list_tenants(op_headers()).json()
    assert body["response_type"] == "array"
    assert body["meta"]["api_request_id"].startswith("req_")

    data, meta = validate_paginated(
        api_client.list_tenants(op_headers(), params={"limit": 2})
    )
    assert len(data) == 2 and meta["has_more"] is True

    data, meta = validate_paginated(
        api_client.list_tenants(op_headers(), params={"limit": 2, "offset": 2})
    )
    assert len(data) == 1 and meta["has_more"] is False

    resp = api_client.list_tenants(op_headers(), params={"limit": 101})
    validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST)


def test_adoption_health_fresh_tenant(api):
    """PRD §3.7: "The adoption health score is a computed read per tenant,
    exposed as `score`, `enrolled_count`, `deferred_count`, and `late_count`.
    It starts from a base of 100". A tenant with no adoptions subtracts
    nothing.

    Design: Corner/endpoints/adoption_health_computed_read
    """
    tenant = create_tenant("T-EP2")
    health = get_success_data(
        api_client.get_adoption_health(tenant["id"], admin_of(tenant))
    )
    assert health["score"] == 100
    assert health["enrolled_count"] == 0
    assert health["deferred_count"] == 0
    assert health["late_count"] == 0


def test_tenant_admin_cannot_create_release_train(api):
    """PRD §2.1: "A request whose role is recognized but not permitted for the
    target endpoint is rejected with `ERR_UNAUTHORIZED` (HTTP 403)."
    PRD §4: POST /release-trains is authorized for PlatformOperator only.

    Design: Corner/errors/unauthorized_role_denied
    """
    tenant = create_tenant("T-ER2")
    resp = api_client.create_release_train(
        {"release_label": "X", "release_kind": "WEEKLY_SERVICE",
         "mandatory_date": "2026-10-01T00:00:00Z"},
        admin_of(tenant),
    )
    validate_error(resp, ApiErrorId.ERR_UNAUTHORIZED)


def test_approver_cannot_administer_definitions(api):
    """PRD §2.1: "A request whose role is recognized but not permitted for the
    target endpoint is rejected with `ERR_UNAUTHORIZED` (HTTP 403)."
    PRD §4: POST .../business-process-definitions/{id}/activate is authorized
    for TenantAdministrator only.

    Design: Corner/rbac/approver_cannot_administer_definitions
    """
    tenant = create_tenant("T-RB1")
    admin = admin_of(tenant)
    definition = create_definition(tenant["id"], admin, transaction_type="HIRE",
                                   name="Flow")

    resp = api_client.activate_definition(
        tenant["id"], definition["id"],
        {"expected_definition_version": definition["version"]},
        make_approver_headers("approver-1"),
    )
    validate_error(resp, ApiErrorId.ERR_UNAUTHORIZED)


def test_integration_developer_cannot_touch_business_process(api):
    """PRD §2.1: "A request whose role is recognized but not permitted for the
    target endpoint is rejected with `ERR_UNAUTHORIZED` (HTTP 403)."
    PRD §4: POST /tenants/{tid}/business-process-definitions is authorized for
    TenantAdministrator and ImplementationPartner only.

    Design: Corner/rbac/integration_developer_cannot_touch_business_process
    """
    tenant = create_tenant("T-RB2")
    resp = api_client.create_definition(
        tenant["id"],
        {"transaction_type": "HIRE", "definition_name": "Flow"},
        dev_headers(),
    )
    validate_error(resp, ApiErrorId.ERR_UNAUTHORIZED)
