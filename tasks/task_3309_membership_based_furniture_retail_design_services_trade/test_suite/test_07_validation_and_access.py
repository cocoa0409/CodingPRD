"""Validation rules, response envelope/pagination, and role-based access control."""
from test_helpers import (
    validate_success,
    validate_error,
    validate_paginated,
    get_success_data,
    ApiErrorId,
    TEST_USERS,
    make_member_headers,
    setup_gallery,
    setup_member,
    setup_product,
    setup_trade_account,
    verify_trade_account,
    setup_delivered_stock_order,
    setup_requested_return,
    create_retail_quote,
    create_member_quote,
    add_line,
    confirm_order,
    schedule_appointment,
    create_product_payload,
    create_gallery_payload,
    create_delivery_appointment_payload,
    set_clock,
)

ADMIN = TEST_USERS["platform_admin_headers"]
ASSOCIATE = TEST_USERS["gallery_associate_headers"]
ANON = TEST_USERS["anonymous_headers"]
HUB = TEST_USERS["hub_operator_headers"]
PLANNER = TEST_USERS["production_planner_headers"]


class TestProductValidation:

    def test_product_created_discontinued_via_input(self, api):
        """PRD §3.3: "A product's `status` defaults to `ACTIVE` but may be created directly as `DISCONTINUED`; only `ACTIVE` products may be added to orders."
        PRD §3.3: "Products also carry a computed `promo_active` flag, false at creation, which becomes true while a released source book promotes the product."

        Design: Corner/entities/product_created_discontinued_via_input
        """
        product = validate_success(
            api.create_product(
                create_product_payload(
                    sku="DIS-01", name="Old", list_price_cents=1000,
                    line_kind="STOCK", status="DISCONTINUED",
                ),
                ADMIN,
            ),
            expected_status=201,
        )
        assert product["status"] == "DISCONTINUED"
        assert product["promo_active"] is False

    def test_product_create_client_version_input_ignored(self, api):
        """PRD §2.4: "`version` (integer): starts at 1 on creation and increments by exactly 1 on every mutation."

        Design: Corner/entities/product_create_client_version_input_ignored
        """
        payload = create_product_payload(
            sku="SYS-01", name="Sys", list_price_cents=1000, line_kind="STOCK"
        )
        payload["version"] = 99
        product = validate_success(api.create_product(payload, ADMIN), expected_status=201)
        assert product["version"] == 1

    def test_product_create_missing_required_price_rejected(self, api):
        """PRD §2.10: "7. **Constraint business rules** — uniqueness of emails and SKUs, the single-active-appointment rule, the stock-only return rule, and malformed input (`ERR_DUPLICATE_EMAIL`, `ERR_APPOINTMENT_EXISTS`, `ERR_CUSTOM_NON_RETURNABLE`, `ERR_INVALID_REQUEST`, `ERR_INVALID_ENUM`)."
        PRD §3.3: "Each product is created with a unique `sku` — a duplicate SKU is rejected with `ERR_DUPLICATE_EMAIL` (HTTP 409), the shared uniqueness-violation code — along with a `name`, a `list_price_cents` per unit, and a `line_kind` of `STOCK` or `CUSTOM`"

        Design: Corner/entities/product_create_missing_required_price_rejected
        """
        payload = {"sku": "BAD-01", "name": "Bad", "line_kind": "STOCK"}
        resp = api.create_product(payload, ADMIN)
        validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST.value)

    def test_invalid_line_kind_enum_rejected(self, api):
        """PRD §2.10: "7. **Constraint business rules** — uniqueness of emails and SKUs, the single-active-appointment rule, the stock-only return rule, and malformed input (`ERR_DUPLICATE_EMAIL`, `ERR_APPOINTMENT_EXISTS`, `ERR_CUSTOM_NON_RETURNABLE`, `ERR_INVALID_REQUEST`, `ERR_INVALID_ENUM`)."
        PRD §3.3: "a `line_kind` of `STOCK` or `CUSTOM`"

        Design: Corner/validations/invalid_line_kind_enum_rejected
        """
        payload = create_product_payload(
            sku="V13-01", name="V13", list_price_cents=1000, line_kind="BOGUS"
        )
        resp = api.create_product(payload, ADMIN)
        validate_error(resp, ApiErrorId.ERR_INVALID_ENUM.value)


class TestErrorEnvelope:

    def test_error_envelope_shape_on_not_found(self, api):
        """PRD §2.2: "All error API responses (4xx status codes) follow this standard error envelope format" with "response_type": "error" and data carrying error_id plus message; "The `message` provides a human-readable explanation of what went wrong."
        PRD §2.9: "`ERR_NOT_FOUND` covers any remaining generic case. All not-found errors carry HTTP 404."

        Design: Corner/endpoints/error_envelope_shape_on_not_found
        """
        resp = api.get_product("8a3e1c0b-2f4d-4a91-9c8b-12e7b6a0f1d2", ADMIN)
        assert resp.status_code == 404
        body = resp.json()
        assert body["response_type"] == "error"
        assert body["data"]["error_id"] == "ERR_PRODUCT_NOT_FOUND"
        assert isinstance(body["data"]["message"], str)
        assert len(body["data"]["message"].strip()) > 0


class TestListPagination:

    def test_orders_list_pagination_defaults(self, api):
        """PRD §2.3: "`limit` sets the maximum number of items returned; it defaults to 10, with a minimum of 1 and a maximum of 100. `offset` sets the number of items skipped and defaults to 0."
        PRD §2.3: "List responses carry `limit`, `offset`, `total_count`, and `has_more` in the `meta` object of the response envelope, in addition to the standard request metadata fields."

        Design: Corner/endpoints/orders_list_pagination_defaults
        """
        gallery = setup_gallery(name="Gallery E1")
        create_retail_quote(gallery["id"])

        resp = api.list_orders(ADMIN)
        data, meta = validate_paginated(resp)
        assert meta["limit"] == 10
        assert meta["offset"] == 0
        assert meta["total_count"] == 1
        assert meta["has_more"] is False
        assert len(data) == 1


class TestOwnershipRules:

    def test_member_cannot_read_other_member(self, api):
        """PRD §2.1: "When `X-User-Role` is `Member`, `X-User-ID` is the `id` of the acting `Member`; ownership checks on any resource that references a `Member` — an order's `member_id`, a consultation's `member_id`, or the member attached to the order underlying a return — compare that field to `X-User-ID`."
        PRD §2.1: "A request whose role is not authorized for the target endpoint, or whose identity fails an ownership check, is rejected with `ERR_FORBIDDEN` (HTTP 403)."

        Design: Corner/validations/member_cannot_read_other_member
        """
        member_a = setup_member(email="v1a@x.com", full_name="V A")
        member_b = setup_member(email="v1b@x.com", full_name="V B")

        resp = api.get_member(member_b["id"], make_member_headers(member_a["id"]))
        validate_error(resp, ApiErrorId.ERR_FORBIDDEN.value)

    def test_member_can_read_itself(self, api):
        """PRD §2.1: "When `X-User-Role` is `Member`, `X-User-ID` is the `id` of the acting `Member`; ownership checks on any resource that references a `Member` — an order's `member_id`, a consultation's `member_id`, or the member attached to the order underlying a return — compare that field to `X-User-ID`."
        PRD §4: "GET | `/members/{id}` | Read a member (a `Member` may read only itself) | Member, GalleryAssociate, PlatformAdmin"

        Design: Corner/validations/member_cannot_read_other_member
        """
        member = setup_member(email="v1c@x.com", full_name="V C")
        data = validate_success(
            api.get_member(member["id"], make_member_headers(member["id"]))
        )
        assert data["id"] == member["id"]


class TestRoleDenials:

    def test_anonymous_cannot_create_gallery(self, api):
        """PRD §2.1: "When `X-User-Role` is `Anonymous`, the caller is an unauthenticated-enrollment principal (the role header is present but no entity exists yet); this role may only enroll members, apply for trade accounts, and read products."
        PRD §2.1: "A request whose role is not authorized for the target endpoint, or whose identity fails an ownership check, is rejected with `ERR_FORBIDDEN` (HTTP 403)."

        Design: Corner/validations/anonymous_cannot_create_gallery
        """
        resp = api.create_gallery(
            create_gallery_payload(name="X", region="WEST",
                                   daily_route_minutes_capacity=480),
            ANON,
        )
        validate_error(resp, ApiErrorId.ERR_FORBIDDEN.value)

    def test_member_cannot_verify_trade_account(self, api):
        """PRD §3.2: "A `TradeReviewer` then renders a credential decision by supplying a `decision` of exactly `APPROVE` or `REJECT`."
        PRD §4: "POST | `/trade-accounts/{id}/verify` | Credential decision: `APPROVE` requires `tier`; `REJECT` is terminal | TradeReviewer"

        Design: Corner/rbac/member_cannot_verify_trade_account
        """
        account = setup_trade_account(email="r1@x.com", business_name="R1")
        member = setup_member(email="r2@x.com", full_name="R Two")

        resp = api.verify_trade_account(
            account["id"],
            {"decision": "APPROVE", "tier": "TIER_1"},
            make_member_headers(member["id"]),
        )
        validate_error(resp, ApiErrorId.ERR_FORBIDDEN.value)

    def test_production_planner_cannot_confirm_order(self, api):
        """PRD §2.1: "When `X-User-Role` is `ProductionPlanner`, the caller schedules custom upholstery production."
        PRD §4: "POST | `/orders/{id}/confirm` | Confirm a quote: final settlement re-price; exact deposit payment required when custom lines exist; zero-custom orders go straight to `READY_FOR_DELIVERY` | Member, TradeDesigner, GalleryAssociate"

        Design: Corner/rbac/production_planner_cannot_confirm_order
        """
        gallery = setup_gallery(name="Gallery R3")
        product = setup_product(list_price_cents=10000, line_kind="STOCK")
        order = create_retail_quote(gallery["id"])
        add_line(order["id"], product["id"], qty=1)

        resp = api.confirm_order(order["id"], {}, PLANNER)
        validate_error(resp, ApiErrorId.ERR_FORBIDDEN.value)

    def test_huboperator_cannot_settle_return(self, api):
        """PRD §3.8: "Settlement belongs to the `GalleryAssociate`, who supplies a `decision`."
        PRD §4: "POST | `/returns/{id}/settle` | Settle: `APPROVE` computes the per-line-rounded restocking fee and refund; `REJECT` requires a reason and refunds zero | GalleryAssociate"

        Design: Corner/rbac/huboperator_cannot_settle_return
        """
        setup = setup_requested_return(list_price_cents=10000)

        resp = api.settle_return(
            setup["return"]["id"], {"decision": "APPROVE"}, HUB
        )
        validate_error(resp, ApiErrorId.ERR_FORBIDDEN.value)


class TestLineValidation:

    def test_premium_fabric_on_stock_product_rejected(self, api):
        """PRD §3.4: "The premium fabric option is meaningful only for custom upholstery: specifying `PREMIUM` on a `STOCK` product — or otherwise mismatching the fabric option to the product kind — is rejected with `ERR_PRODUCT_KIND_MISMATCH` (HTTP 422)"

        Design: Corner/validations/premium_fabric_on_stock_product_rejected
        """
        gallery = setup_gallery(name="Gallery V4")
        product = setup_product(list_price_cents=10000, line_kind="STOCK")
        order = create_retail_quote(gallery["id"])

        resp = api.add_order_line(
            order["id"],
            {"product_id": product["id"], "qty": 1, "fabric_tier": "PREMIUM"},
            ASSOCIATE,
        )
        validate_error(resp, ApiErrorId.ERR_PRODUCT_KIND_MISMATCH.value)

    def test_line_add_after_quote_expiry_rejected(self, api):
        """PRD §3.4: "the clock must be at or before `quote_expires_at` (otherwise `ERR_QUOTE_EXPIRED`, HTTP 422)"
        PRD §3.4: "The new order enters in `QUOTE` with `quote_expires_at` set to 14 days after its creation time"

        Design: Corner/validations/line_add_after_quote_expiry_rejected
        """
        gallery = setup_gallery(name="Gallery V12")
        product = setup_product(list_price_cents=10000, line_kind="STOCK")
        order = create_retail_quote(gallery["id"])
        assert order["quote_expires_at"] == "2026-09-15T00:00:00.000Z"
        set_clock("2026-09-16T00:00:00Z")

        resp = api.add_order_line(
            order["id"], {"product_id": product["id"], "qty": 1}, ASSOCIATE
        )
        validate_error(resp, ApiErrorId.ERR_QUOTE_EXPIRED.value)


class TestAppointmentConstraints:

    def test_second_active_appointment_for_order_rejected(self, api):
        """PRD §3.7: "the order must not already have an appointment in `SCHEDULED` or `OUT_FOR_DELIVERY` — one active appointment per order; a second is rejected with `ERR_APPOINTMENT_EXISTS` (HTTP 409)."

        Design: Corner/validations/second_active_appointment_for_order_rejected
        """
        gallery = setup_gallery(name="Gallery V6")
        product = setup_product(list_price_cents=10000, line_kind="STOCK")
        order = create_retail_quote(gallery["id"])
        add_line(order["id"], product["id"], qty=1)
        confirm_order(order["id"])
        schedule_appointment(order["id"], gallery["id"], delivery_date="2026-09-05")

        resp = api.create_delivery_appointment(
            create_delivery_appointment_payload(
                order["id"], gallery["id"], delivery_date="2026-09-06"
            ),
            ASSOCIATE,
        )
        validate_error(resp, ApiErrorId.ERR_APPOINTMENT_EXISTS.value)
