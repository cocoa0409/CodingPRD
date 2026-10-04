"""Authentication and role-based access control: missing headers, role denials
on exclusive endpoints, and entity-backed CustomerOps ownership."""
from test_helpers import (
    NON_EXISTENT_UUID,
    ApiErrorId,
    TEST_USERS,
    api_client,
    create_certify_payload,
    create_customer,
    create_evaluation,
    create_network_payload,
    create_tank_with_telemetry_delivery,
    make_customer_ops_headers,
    make_quality_analyst_headers,
    record_certificate,
    set_logical_clock,
    create_delivered_delivery,
    validate_error,
    validate_success,
)


def test_unauthenticated_missing_headers(api):
    """PRD section 2.1: "Every request must carry two headers: `X-User-ID`,
    identifying the acting user, and `X-User-Role`, naming one of the nine
    declared roles. A request missing either header, or naming a role the
    system does not recognize, is rejected with `ERR_UNAUTHENTICATED`
    (HTTP 401)."
    PRD section 2.8: "1. Authentication: `X-User-Role` and `X-User-ID` are
    present and valid (`ERR_UNAUTHENTICATED`)."

    Design: Corner/errors/unauthenticated_missing_headers
    """
    set_logical_clock()
    response = api_client.get_customer(NON_EXISTENT_UUID, headers={})
    validate_error(response, ApiErrorId.ERR_UNAUTHENTICATED)
    assert response.status_code == 401, (
        "authentication (tier 1) outranks the 404 existence check (tier 3)"
    )


def test_customer_role_cannot_create_network(api):
    """PRD section 2.1: "When the headers are valid but the role is not
    permitted to call the endpoint, the request is rejected with
    `ERR_UNAUTHORIZED_ROLE` (HTTP 403)."
    PRD section 4: "| POST | `/gas-supply/pipeline-networks` | Create a
    pipeline network | PlatformAdmin |"

    Design: Corner/rbac/customer_role_cannot_create_network
    """
    set_logical_clock()
    customer = create_customer(name="Fabrikam Chips", segment="ELECTRONICS",
                               credit_standing="PRIME")
    response = api_client.create_network(
        create_network_payload(name="Rogue Net", nameplate_capacity_nm3h=1000),
        make_customer_ops_headers(customer["id"]),
    )
    validate_error(response, ApiErrorId.ERR_UNAUTHORIZED_ROLE)


def test_analyst_cannot_certify_role(api):
    """PRD section 2.1: "When the headers are valid but the role is not
    permitted to call the endpoint, the request is rejected with
    `ERR_UNAUTHORIZED_ROLE` (HTTP 403)."
    PRD section 4: "| POST |
    `/gas-supply/quality-certificates/{certificateId}/certify` | Certify or
    fail a recorded analysis; segregated from recording | QualityCertifier |"

    Design: Corner/rbac/analyst_cannot_certify_role
    """
    set_logical_clock()
    customer = create_customer(name="Fabrikam Chips", segment="ELECTRONICS",
                               credit_standing="PRIME")
    _, delivery, certificate = _recorded(customer["id"])
    response = api_client.certify_quality_certificate(
        certificate["id"], create_certify_payload("CERTIFIED"),
        make_quality_analyst_headers("qa-2"),
    )
    validate_error(response, ApiErrorId.ERR_UNAUTHORIZED_ROLE)


def test_customer_accepting_others_evaluation_forbidden(api):
    """PRD section 3.1: "Acceptance is performed by `CustomerOps`, and only
    when the caller's `X-User-ID` equals the evaluation's `customer_id` —
    otherwise the call is rejected with `ERR_UNAUTHORIZED_ROLE`"
    PRD section 2.1: "When `X-User-Role` is `CustomerOps`, `X-User-ID` is the
    `id` of the acting Customer: ownership checks on any resource that
    references a customer compare that customer reference to `X-User-ID`, and a
    mismatch is rejected with `ERR_UNAUTHORIZED_ROLE`."

    Design: Corner/rbac/customer_accepting_others_evaluation_forbidden
    """
    set_logical_clock()
    owner = create_customer(name="Fabrikam Chips", segment="ELECTRONICS",
                            credit_standing="PRIME")
    other = create_customer(name="OtherCo", segment="CHEMICAL")
    evaluation = create_evaluation(owner["id"])
    response = api_client.accept_evaluation(
        evaluation["id"], make_customer_ops_headers(other["id"])
    )
    validate_error(response, ApiErrorId.ERR_UNAUTHORIZED_ROLE)
    evaluations = validate_success(api_client.list_customer_evaluations(
        owner["id"], TEST_USERS["supply_planner_headers"]
    ))
    current = [e for e in evaluations if e["id"] == evaluation["id"]][0]
    assert current["status"] == "EVALUATED", (
        "a forbidden acceptance must leave the evaluation EVALUATED"
    )


def test_telemetry_gateway_cannot_confirm_delivery(api):
    """PRD section 2.1: "When the headers are valid but the role is not
    permitted to call the endpoint, the request is rejected with
    `ERR_UNAUTHORIZED_ROLE` (HTTP 403)."
    PRD section 4: "| POST |
    `/gas-supply/deliveries/{deliveryId}/confirm-delivery` | Confirm physical
    delivery with the delivered quantity | PipelineDispatcher |"

    Design: Corner/rbac/telemetry_gateway_cannot_confirm_delivery
    """
    set_logical_clock()
    customer = create_customer(name="Fabrikam Chips", segment="ELECTRONICS",
                               credit_standing="PRIME")
    _, delivery = create_tank_with_telemetry_delivery(customer["id"])
    response = api_client.confirm_delivery(
        delivery["id"], {"delivered_quantity_liters": 30000},
        TEST_USERS["telemetry_gateway_headers"],
    )
    validate_error(response, ApiErrorId.ERR_UNAUTHORIZED_ROLE)


def _recorded(customer_id):
    """Delivered delivery + RECORDED certificate (analyst qa-1)."""
    tank, delivery = create_delivered_delivery(customer_id)
    certificate = record_certificate(delivery["id"], analyst_user_id="qa-1")
    return tank, delivery, certificate
