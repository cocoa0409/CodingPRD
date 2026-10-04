"""Authentication, authorization, ownership, and request-shape gates.

Covers the validation ladder tiers 1-5 of PRD §2.8: unauthenticated requests,
role authorization, entity-backed ownership, reference existence, and required
field / enum shape checks.
"""
from test_helpers import (
    NON_EXISTENT_UUID,
    ApiErrorId,
    create_distributor_active,
    create_distributor_payload,
    create_lease_for,
    create_course_payload,
    create_model_payload,
    create_parts_order_payload,
    make_course_manager_headers,
    make_distributor_manager_headers,
    setup_program,
    setup_submitted_claim,
    validate_error,
    validate_success,
)


def test_missing_auth_header_returns_unauthenticated(api):
    """PRD §2.1: "A request missing either header, or presenting a role the
    system does not declare, is rejected with `ERR_UNAUTHENTICATED` (HTTP 401)."
    PRD §2.8: "This ordering means, for example, that a stale lease version
    surfaces before any territory or fiscal problem on the same request, and
    that an authentication failure masks every other defect."

    Design: Corner/rbac/missing_auth_header_returns_unauthenticated
    """
    resp = api.get_lease(NON_EXISTENT_UUID, {})
    validate_error(resp, ApiErrorId.ERR_UNAUTHENTICATED.value)


def test_distributor_manager_cannot_create_models(api, corporate_admin_headers):
    """PRD §2.1: "Every endpoint lists the roles permitted to call it; a caller
    whose role is not in that list is rejected with `ERR_UNAUTHORIZED`
    (HTTP 403)."
    PRD §4: "| POST | `/turf/models` | Publish an equipment model to the
    catalog | CorporateAdmin |"

    Design: Corner/rbac/distributor_manager_cannot_create_models
    """
    distributor = validate_success(
        api.create_distributor(create_distributor_payload(), corporate_admin_headers),
        201,
    )
    resp = api.create_model(
        create_model_payload(),
        make_distributor_manager_headers(distributor["id"]),
    )
    validate_error(resp, ApiErrorId.ERR_UNAUTHORIZED.value)


def test_course_manager_cannot_adjudicate_claims(api):
    """PRD §2.1: "Every endpoint lists the roles permitted to call it; a caller
    whose role is not in that list is rejected with `ERR_UNAUTHORIZED`
    (HTTP 403)."
    PRD §4: "| POST | `/turf/warranty-claims/{id}/transition` | Adjudicate and
    settle a claim: UNDER_REVIEW, APPROVED, PARTIAL_APPROVED, DENIED, DISPUTED,
    PAID; OCC-guarded via `expected_claim_version` | CorporateAdmin,
    DistributorManager |"

    Design: Corner/rbac/course_manager_cannot_adjudicate_claims
    """
    ctx = setup_submitted_claim()
    claim = ctx["claim"]
    resp = api.transition_warranty_claim(
        claim["id"],
        "UNDER_REVIEW",
        claim["version"],
        make_course_manager_headers(ctx["course"]["id"]),
    )
    validate_error(resp, ApiErrorId.ERR_UNAUTHORIZED.value)


def test_distributor_manager_cannot_transition_foreign_lease(api, corporate_admin_headers):
    """PRD §2.1: "For the three entity-backed roles, an `X-User-ID` that
    resolves to no entity of the backing type, or that does not own the target
    resource, is rejected with `ERR_FORBIDDEN_OWNERSHIP` (HTTP 403)."

    Design: Corner/rbac/distributor_manager_cannot_transition_foreign_lease
    """
    ctx = setup_program()
    lease = create_lease_for(
        ctx["distributor"],
        ctx["course"],
        [{"model_id": ctx["model"]["id"], "qty": 1}],
    )
    other = validate_success(
        api.create_distributor(
            create_distributor_payload(name="Sierra Turf Supply", territory_codes=["AZ"]),
            corporate_admin_headers,
        ),
        201,
    )
    resp = api.transition_lease(
        lease["id"],
        "SPEC_REVIEW",
        lease["version"],
        make_distributor_manager_headers(other["id"]),
    )
    validate_error(resp, ApiErrorId.ERR_FORBIDDEN_OWNERSHIP.value)


def test_distributor_create_missing_name_returns_invalid_request(api, corporate_admin_headers):
    """PRD §2.8: "5. Request shape — required fields present, enum members
    valid, types match; a parts order created or submitted with zero lines
    fails as `ERR_EMPTY_ORDER` (422), a line with a quantity below 1 fails as
    `ERR_ZERO_QUANTITY_LINE` (422), a claim with non-positive `labor_hours` is
    malformed, and other shape failures surface as `ERR_INVALID_REQUEST`
    (400)."

    Design: Corner/entities/distributor_create_missing_name_returns_invalid_request
    """
    payload = create_distributor_payload()
    del payload["name"]
    resp = api.create_distributor(payload, corporate_admin_headers)
    validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST.value)


def test_course_create_invalid_turf_profile_returns_invalid_request(api, corporate_admin_headers):
    """PRD §2.8: "5. Request shape — required fields present, enum members
    valid, types match; a parts order created or submitted with zero lines
    fails as `ERR_EMPTY_ORDER` (422), a line with a quantity below 1 fails as
    `ERR_ZERO_QUANTITY_LINE` (422), a claim with non-positive `labor_hours` is
    malformed, and other shape failures surface as `ERR_INVALID_REQUEST`
    (400)."
    PRD §3.4: "its dominant `turf_profile` (`BENTGRASS`, `BERMUDA`,
    `POA_ANNUA`, or `MIXED`)"

    Design: Corner/entities/course_create_invalid_turf_profile_returns_invalid_request
    """
    distributor = validate_success(
        api.create_distributor(create_distributor_payload(), corporate_admin_headers),
        201,
    )
    payload = create_course_payload(distributor["id"], turf_profile="KIKUYU")
    resp = api.create_course(payload, corporate_admin_headers)
    validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST.value)


def test_lease_get_unknown_id_returns_not_found(api, corporate_admin_headers):
    """PRD §2.8: "The first reference that does not resolve to an existing
    resource rejects the request with `ERR_NOT_FOUND` (HTTP 404), and later
    references are not examined."

    Design: Corner/entities/lease_get_unknown_id_returns_not_found
    """
    resp = api.get_lease(NON_EXISTENT_UUID, corporate_admin_headers)
    validate_error(resp, ApiErrorId.ERR_NOT_FOUND.value)


def test_parts_order_empty_lines_rejected(api):
    """PRD §3.3: "Order shape is enforced at creation and re-checked at
    submission: an order with zero lines is rejected with `ERR_EMPTY_ORDER`
    (HTTP 422), and any line whose `qty` is below 1 is rejected with
    `ERR_ZERO_QUANTITY_LINE` (HTTP 422)."

    Design: Corner/errors/parts_order_empty_lines_rejected
    """
    distributor, _technician = create_distributor_active()
    mgr = make_distributor_manager_headers(distributor["id"])
    resp = api.create_parts_order(create_parts_order_payload([], order_type="STOCK"), mgr)
    validate_error(resp, ApiErrorId.ERR_EMPTY_ORDER.value)
