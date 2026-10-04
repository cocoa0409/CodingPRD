"""Wire contracts and role-based access control (PRD §2.1, §2.2, §2.3, §2.8, §4)."""
from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    create_distributor,
    create_order,
    create_plant,
    create_product,
    create_visit,
    get_order,
    get_success_data,
    make_distributor_rep_headers,
    make_plant_scheduler_headers,
    make_retail_manager_headers,
    propose_account,
    setup_active_distributor,
    setup_approved_account,
    submit_visit,
    validate_error,
    validate_paginated,
    validate_success,
)

ADMIN = TEST_USERS["brand_admin_headers"]


def test_product_create_missing_base_price_rejected(api):
    """PRD §2.8: "required fields are present, types match, enum values fall within
    their declared sets, integer quantities are positive, a window's start precedes
    its end, and a promo's `start_date` is on or before its `end_date`; failure is
    `ERR_VALIDATION`." and PRD §3.2: "A `BrandAdmin` creates a product with a unique
    `code` (else `ERR_DUPLICATE_CODE`), a `name`, a `base_price_cents` list price per
    unit in integer cents that must be positive".

    Omitting the required base_price_cents yields 400 before any existence check.

    Design: Corner/entities/product_create_missing_required_base_price
    """
    resp = api.create_product(
        {"code": "P1", "name": "Item", "shelf_life_opened_hours": 72,
         "shelf_life_unopened_days": 30, "allergen_tags": []},
        ADMIN,
    )
    validate_error(resp, ApiErrorId.ERR_VALIDATION)


def test_products_list_pagination_defaults_and_envelope(api):
    """PRD §2.3: "The `limit` parameter sets the maximum number of items returned; it
    defaults to 10, with a minimum of 1 and a maximum of 100. The `offset` parameter
    sets the number of items skipped and defaults to 0." and "List responses carry
    the pagination fields `limit`, `offset`, `total_count`, and `has_more` inside the
    `meta` object of the response envelope." and PRD §2.2: "The `api_request_id` is a
    server-generated unique identifier for the request that starts with `req_`."

    Design: Corner/entities/products_list_pagination_defaults_and_envelope
    """
    create_product(code="P1", name="Item")
    resp = api.list_products(ADMIN)
    data, meta = validate_paginated(resp)
    assert len(data) == 1
    assert meta["limit"] == 10
    assert meta["offset"] == 0
    assert meta["total_count"] == 1
    assert meta["has_more"] is False
    body = resp.json()
    assert body["response_type"] == "array"
    assert isinstance(meta["api_request_id"], str)
    assert meta["api_request_id"].startswith("req_")


def test_error_envelope_shape_on_validation_failure(api):
    """PRD §2.2: "The `meta` object for error responses contains only
    `api_request_id` and `api_request_timestamp`." and "The `error_id` is a unique,
    machine-readable string that identifies the specific error." and "The `message`
    provides a human-readable explanation of what went wrong."

    Design: Corner/errors/error_envelope_shape_on_validation_failure
    """
    resp = api.create_product({"code": "P1"}, ADMIN)
    validate_error(resp, ApiErrorId.ERR_VALIDATION)
    body = resp.json()
    assert body["response_type"] == "error"
    assert body["data"]["error_id"] == "ERR_VALIDATION"
    assert isinstance(body["data"]["message"], str) and body["data"]["message"]
    assert set(body["meta"].keys()) == {"api_request_id", "api_request_timestamp"}


def test_missing_auth_headers_rejected(api):
    """PRD §2.1: "A request with missing headers, or whose role is not one of these
    declared values, is rejected with `ERR_UNAUTHENTICATED`."

    The request without X-User-Role / X-User-ID fails 401 before any role or shape
    check; the same endpoint with valid headers succeeds (control).

    Design: Corner/validations/missing_auth_headers_rejected
    """
    resp = api.list_products(headers={})
    validate_error(resp, ApiErrorId.ERR_UNAUTHENTICATED)
    data, _meta = validate_paginated(api.list_products(ADMIN))
    assert isinstance(data, list)


def test_distributor_cannot_create_products(api):
    """PRD §2.1: "A request whose role is not listed among the roles authorized for
    the target endpoint is rejected with `ERR_FORBIDDEN`." and PRD §4: "Create a
    product SKU | BrandAdmin".

    Product master data is BrandAdmin-exclusive; a DistributorRep is denied.

    Design: Corner/rbac/distributor_cannot_create_products
    """
    net = setup_active_distributor()
    resp = api.create_product(
        {"code": "P1", "name": "Item", "base_price_cents": 500,
         "shelf_life_opened_hours": 72, "shelf_life_unopened_days": 30,
         "allergen_tags": []},
        make_distributor_rep_headers(net["distributor"]["id"]),
    )
    validate_error(resp, ApiErrorId.ERR_FORBIDDEN)


def test_retail_manager_cannot_allocate_week(api):
    """PRD §2.1: "A request whose role is not listed among the roles authorized for
    the target endpoint is rejected with `ERR_FORBIDDEN`." and PRD §4: "Run the
    weekly allocation waterfall over all `PENDING` orders of a delivery week |
    PlantScheduler".

    Allocation is PlantScheduler-exclusive; a RetailManager is denied.

    Design: Corner/rbac/retail_manager_cannot_allocate_week
    """
    ctx = setup_approved_account()
    resp = api.allocate_week(
        "2026-09-07", make_retail_manager_headers(ctx["account"]["id"]))
    validate_error(resp, ApiErrorId.ERR_FORBIDDEN)


def test_plant_scheduler_cannot_review_account(api):
    """PRD §2.1: "A request whose role is not listed among the roles authorized for
    the target endpoint is rejected with `ERR_FORBIDDEN`." and PRD §4: "Approve or
    reject an `UNDER_REVIEW` account | BrandAdmin".

    Account approval is BrandAdmin-exclusive; the denial changes nothing.

    Design: Corner/rbac/plant_scheduler_cannot_review_account
    """
    net = setup_active_distributor()
    account = propose_account(net["distributor"], net["territory"])
    plant = create_plant(code="PL1", name="Plant 1")
    resp = api.review_account(
        account["id"], "APPROVE", make_plant_scheduler_headers(plant["id"]))
    validate_error(resp, ApiErrorId.ERR_FORBIDDEN)
    current = get_success_data(api.get_account(account["id"], ADMIN))
    assert current["approval_status"] == "UNDER_REVIEW"


def test_foreign_distributor_cannot_cancel_order(api):
    """PRD §2.1: "An entity-backed ownership mismatch on a non-read operation is
    rejected with `ERR_FORBIDDEN`." and PRD §3.3: "Cancellation is performed by the
    owning `DistributorRep` — `X-User-ID` must equal the order's `distributor_id`".

    The rep whose X-User-ID differs from the order's distributor is denied with 403,
    not 404: the resource exists, the ownership check rejects the actor.

    Design: Corner/rbac/foreign_distributor_cannot_cancel_order
    """
    net = setup_active_distributor()
    other = create_distributor(code="D2", name="Dist Two")
    product = create_product(code="P1", name="Item")
    order = create_order(net["distributor"], [(product["id"], 5)])
    resp = api.cancel_order(order["id"], make_distributor_rep_headers(other["id"]))
    validate_error(resp, ApiErrorId.ERR_FORBIDDEN)
    assert get_order(order["id"])["allocation_status"] == "PENDING"


def test_visit_submitter_cannot_review_own_visit(api):
    """PRD §3.6: "Verification is segregated by design: a `SafetyOfficer` — never the
    submitting representative — reviews a `SUBMITTED` visit with a `verdict`." and
    PRD §2.1: "A request whose role is not listed among the roles authorized for the
    target endpoint is rejected with `ERR_FORBIDDEN`."

    The role that submits a visit report can never verify it: the review endpoint is
    SafetyOfficer-exclusive, so the submitter's VERIFY attempt is forbidden.

    Design: Corner/rbac/visit_submitter_cannot_review_own_visit
    """
    ctx = setup_approved_account()
    visit = create_visit(ctx["account"], ctx["distributor"],
                         "2026-09-02T09:00:00Z", "2026-09-02T10:00:00Z")
    visit = submit_visit(visit, ctx["distributor"], score=90)
    assert visit["status"] == "SUBMITTED"
    resp = api.review_service_visit(
        visit["id"], "VERIFY", make_distributor_rep_headers(ctx["distributor"]["id"]))
    validate_error(resp, ApiErrorId.ERR_FORBIDDEN)
    current = validate_success(api.get_service_visit(visit["id"], ADMIN))
    assert current["status"] == "SUBMITTED"
