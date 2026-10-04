"""Response-envelope claims and role-based access denials
(PRD §2.1, §2.2, §4)."""
from test_helpers import (
    ADMIN,
    SUPPORT,
    ApiErrorId,
    api_client,
    assert_plan_line,
    create_coupon_payload,
    create_customer,
    create_product_payload,
    get_success_data,
    list_plan_lines,
    make_customer_headers,
    set_clock,
    setup_customer_with_plan,
    setup_reported_claim,
    validate_error,
    validate_paginated,
)

GHOST_ID = "8a3e1c0b-2f4d-4a91-9c8b-12e7b6a0f1d2"


class TestListEnvelope:
    def test_list_endpoint_uses_array_envelope_with_pagination_fields(self):
        """PRD §2.2: "The `response_type` is either "object" for a single
        resource or "array" for a list of resources."
        PRD §2.2: "Pagination-related fields in `meta` (`limit`, `offset`,
        `total_count`, `has_more`) are included for list endpoints."

        Design: Corner/endpoints/list_endpoint_uses_array_envelope_with_pagination_fields
        """
        customer, product, placement, subs, plan = setup_customer_with_plan()
        headers = make_customer_headers(customer["id"])
        resp = api_client.list_plan_lines_global(
            headers, params={"subscription_id": subs[0]["id"]})
        assert resp.status_code == 200
        body = resp.json()
        assert body["response_type"] == "array"
        assert body["meta"]["api_request_id"]
        assert body["meta"]["api_request_timestamp"]
        data, meta = validate_paginated(resp)
        assert len(data) == 1
        assert meta["total_count"] == 1
        assert meta["has_more"] is False
        assert_plan_line(data[0])


class TestRbacDenials:
    def test_customer_cannot_create_product(self):
        """PRD §4: the endpoint table lists `POST /sns/products` as
        authorized for PlatformAdmin only.
        PRD §2.1: "A request whose role is authenticated but not listed among
        the endpoint's permitted roles is rejected with `ERR_FORBIDDEN` (HTTP
        403)."

        Design: Corner/rbac/customer_cannot_create_product
        """
        set_clock()
        customer = create_customer()
        resp = api_client.create_product(
            create_product_payload(), make_customer_headers(customer["id"]))
        validate_error(resp, ApiErrorId.ERR_FORBIDDEN)

    def test_customer_cannot_review_damage_claim(self):
        """PRD §3.11: "Review belongs to a `SupportAgent` and takes a
        `decision` of `APPROVE_REFUND`, `APPROVE_RESHIP`, or `REJECT`".
        PRD §2.1: "A request whose role is authenticated but not listed among
        the endpoint's permitted roles is rejected with `ERR_FORBIDDEN` (HTTP
        403)."

        Design: Corner/rbac/customer_cannot_review_damage_claim
        """
        customer, product, placement, subs, plan, line, claim = (
            setup_reported_claim())
        resp = api_client.review_damage_claim(
            claim["id"], {"decision": "APPROVE_REFUND"},
            make_customer_headers(customer["id"]))
        validate_error(resp, ApiErrorId.ERR_FORBIDDEN)
        claim_after = get_success_data(
            api_client.get_damage_claim(claim["id"], SUPPORT))
        assert claim_after["claim_status"] == "REPORTED"

    def test_support_agent_cannot_create_coupon(self):
        """PRD §4: the endpoint table lists `POST /sns/coupons` as authorized
        for PlatformAdmin only.
        PRD §2.1: "A request whose role is authenticated but not listed among
        the endpoint's permitted roles is rejected with `ERR_FORBIDDEN` (HTTP
        403)."

        Design: Corner/rbac/support_agent_cannot_create_coupon
        """
        set_clock()
        resp = api_client.create_coupon(create_coupon_payload("NOPE"), SUPPORT)
        validate_error(resp, ApiErrorId.ERR_FORBIDDEN)

    def test_customer_cannot_lock_another_customers_plan(self):
        """PRD §2.1: "When `X-User-Role` is `Customer`, `X-User-ID` is the
        `id` of the acting `Customer` entity; ownership checks on any
        customer-scoped resource (subscription, delivery plan, plan line,
        damage claim, retention offer, notification) compare the resource's
        owning-customer chain to `X-User-ID`, and a mismatch is rejected with
        `ERR_OWNERSHIP_MISMATCH` (HTTP 403)."

        Design: Corner/rbac/customer_cannot_lock_another_customers_plan
        """
        customer_a, product, placement, subs, plan = setup_customer_with_plan()
        customer_b = create_customer()
        resp = api_client.lock_plan(
            plan["id"], make_customer_headers(customer_b["id"]))
        validate_error(resp, ApiErrorId.ERR_OWNERSHIP_MISMATCH)
        from test_helpers import get_plan
        assert get_plan(plan["id"])["plan_status"] == "OPEN"

    def test_request_missing_auth_headers_returns_401(self):
        """PRD §2.1: "A request missing either header, or carrying an
        unrecognized role, is rejected with `ERR_UNAUTHENTICATED` (HTTP 401)."

        Design: Corner/rbac/request_missing_auth_headers_returns_401
        """
        set_clock()
        resp = api_client.get_product(GHOST_ID, None)
        validate_error(resp, ApiErrorId.ERR_UNAUTHENTICATED)
