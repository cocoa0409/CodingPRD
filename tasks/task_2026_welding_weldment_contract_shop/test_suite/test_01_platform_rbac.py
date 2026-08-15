"""Platform rules: shop onboarding defaults, addressing, header auth, RBAC,
and pagination."""
import pytest

from test_helpers import (
    NON_EXISTENT_UUID,
    ApiErrorId,
    TEST_USERS,
    assert_welder,
    build_user_headers,
    create_and_approve_pqr,
    create_pqr,
    create_shop,
    create_welder,
    create_wps,
    get_success_data,
    make_welder_headers,
    validate_error,
    validate_paginated,
    validate_success,
)

ADMIN = TEST_USERS["shop_admin_headers"]
QC_MANAGER = TEST_USERS["qc_manager_headers"]


class TestShopOnboarding:
    def test_shop_creation_applies_repair_rate_limit_default(self, api):
        """PRD §3.1: "A `ShopAdmin` onboards a new contract shop by supplying
        its legal `shop_name`, the `aws_d1_1_revision` the shop is
        contractually bound to (for example, `D1.1:2025`), and optionally a
        `repair_rate_limit_pct` — the shop-wide contractual ceiling on repair
        work, expressed as a whole percent and defaulting to 5 when omitted."

        Design: Corner/entities/shop_creation_applies_repair_rate_limit_default
        """
        resp = api.create_shop(
            {"shop_name": "Default Limit Shop",
             "aws_d1_1_revision": "D1.1:2025"},
            ADMIN)
        shop = validate_success(resp, 201)
        assert shop["repair_rate_limit_pct"] == 5, (
            f"Omitted repair_rate_limit_pct must default to 5, "
            f"got {shop['repair_rate_limit_pct']}")

        fetched = validate_success(api.get_shop(shop["id"], ADMIN), 200)
        assert fetched["repair_rate_limit_pct"] == 5
        assert fetched["current_utc"] is not None

    def test_shop_creation_uses_explicit_repair_rate_limit(self, api):
        """PRD §3.1: "A `ShopAdmin` onboards a new contract shop by supplying
        its legal `shop_name`, the `aws_d1_1_revision` the shop is
        contractually bound to (for example, `D1.1:2025`), and optionally a
        `repair_rate_limit_pct` — the shop-wide contractual ceiling on repair
        work, expressed as a whole percent and defaulting to 5 when omitted."

        Design: Corner/entities/shop_creation_uses_explicit_repair_rate_limit
        """
        resp = api.create_shop(
            {"shop_name": "Explicit Limit Shop",
             "aws_d1_1_revision": "D1.1:2025",
             "repair_rate_limit_pct": 12},
            ADMIN)
        shop = validate_success(resp, 201)
        assert shop["repair_rate_limit_pct"] == 12, (
            f"Explicit repair_rate_limit_pct must be honored, "
            f"got {shop['repair_rate_limit_pct']}")

        fetched = validate_success(api.get_shop(shop["id"], ADMIN), 200)
        assert fetched["repair_rate_limit_pct"] == 12

    def test_shop_not_found_returns_404(self, api):
        """PRD §2.10: "the request is rejected with `ERR_NOT_FOUND` (HTTP 404)
        at the first identifier in the chain that does not resolve, and deeper
        identifiers are never consulted."

        Design: Corner/entities/shop_not_found_returns_404
        """
        resp = api.get_shop(NON_EXISTENT_UUID, ADMIN)
        validate_error(resp, ApiErrorId.ERR_NOT_FOUND)


class TestWelderEnrollment:
    def test_welder_creation_persists_fields(self, api):
        """PRD §3.2: "A welder's `status` begins at `ACTIVE`; the full
        vocabulary is `ACTIVE`, `SUSPENDED`, and `TERMINATED`."

        Design: Corner/entities/welder_creation_persists_fields
        """
        shop = create_shop(shop_name="Welder Shop")
        resp = api.create_welder(
            shop["id"], {"stencil": "W-X", "full_name": "Welder X"}, ADMIN)
        welder = validate_success(resp, 201)
        assert_welder(welder)
        assert welder["status"] == "ACTIVE", (
            f"A welder is born ACTIVE, got {welder['status']}")
        assert welder["stencil"] == "W-X"
        assert welder["full_name"] == "Welder X"
        assert welder["shop_id"] == shop["id"]


class TestHeaderAuth:
    def test_missing_user_role_header_returns_400(self, api):
        """PRD §2.1: "A request missing either header, or carrying a malformed
        value, is rejected with `ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER`
        (HTTP 400)."

        Design: Corner/validations/missing_user_role_header_returns_400
        """
        shop = create_shop(shop_name="Header Shop")

        # Missing X-User-Role entirely.
        resp_no_role = api.get_shop(
            shop["id"],
            {"X-User-ID": "test-reader-1", "Content-Type": "application/json"})
        validate_error(
            resp_no_role,
            ApiErrorId.ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER)

        # Missing X-User-ID entirely.
        resp_no_id = api.get_shop(
            shop["id"],
            {"X-User-Role": "ShopAdmin", "Content-Type": "application/json"})
        validate_error(
            resp_no_id,
            ApiErrorId.ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER)


class TestRbacDenials:
    def test_welder_cannot_approve_pqr(self, api):
        """PRD §2.1: "A request whose role is not authorized for the target
        operation is rejected with `ERR_INSUFFICIENT_PERMISSIONS` (HTTP 403)."
        PRD §2.1: "`QCManager` is the quality-control manager. It alone
        creates and dispositions PQRs and WPS revisions (approve and reject)"

        Design: Corner/validations/welder_cannot_approve_pqr
        """
        shop = create_shop(shop_name="RBAC PQR Shop")
        welder = create_welder(shop["id"], stencil="W-V2",
                               full_name="Welder V2")
        pqr = create_pqr(shop["id"], pqr_number="PQR-V2")

        resp = api.approve_pqr(shop["id"], pqr["id"],
                               make_welder_headers(welder["id"]))
        validate_error(resp, ApiErrorId.ERR_INSUFFICIENT_PERMISSIONS)

    def test_cwi_cannot_manage_ovens(self, api):
        """PRD §2.1: "A request whose role is not authorized for the target
        operation is rejected with `ERR_INSUFFICIENT_PERMISSIONS` (HTTP 403)."
        PRD §2.1: "`MaterialController` owns ovens, consumable lots, and
        consumable issues — including returns, rebakes, and taking ovens
        offline or bringing them online."

        Design: Corner/rbac/cwi_cannot_manage_ovens
        """
        shop = create_shop(shop_name="RBAC Oven Shop")
        resp = api.create_oven(
            shop["id"],
            {"oven_code": "OV-R2", "holding_temp_c": 150,
             "capacity_electrodes_kg": 500},
            TEST_USERS["cwi_headers"])
        validate_error(resp, ApiErrorId.ERR_INSUFFICIENT_PERMISSIONS)

    def test_shipping_clerk_cannot_approve_wps(self, api):
        """PRD §2.1: "A request whose role is not authorized for the target
        operation is rejected with `ERR_INSUFFICIENT_PERMISSIONS` (HTTP 403)."
        PRD §2.1: "`QCManager` is the quality-control manager. It alone
        creates and dispositions PQRs and WPS revisions (approve and reject)"

        Design: Corner/rbac/shipping_clerk_cannot_approve_wps
        """
        shop = create_shop(shop_name="RBAC WPS Shop")
        pqr = create_and_approve_pqr(shop["id"], pqr_number="PQR-R1")
        wps = create_wps(shop["id"], pqr["id"], wps_number="WPS-R1")

        resp = api.approve_wps(
            shop["id"], wps["id"],
            {"expected_wps_version": wps["version"]},
            TEST_USERS["shipping_clerk_headers"])
        validate_error(resp, ApiErrorId.ERR_INSUFFICIENT_PERMISSIONS)


class TestPagination:
    def test_list_pagination_default_limit_10(self, api):
        """PRD §2.3: "The `limit` parameter sets the maximum number of items
        returned: it defaults to 10 when omitted, accepts a minimum of 1, and
        is capped at a maximum of 100."
        PRD §2.3: "The `meta` object of a list response carries the pagination
        fields `limit`, `offset`, `total_count`, and `has_more`."

        Design: Corner/endpoints/list_pagination_default_limit_10
        """
        shop = create_shop(shop_name="Pagination Shop")
        for i in range(1, 13):
            create_welder(shop["id"], stencil=f"WE{i:02d}",
                          full_name=f"Welder {i}")

        data, meta = validate_paginated(
            api.list_welders(shop["id"], ADMIN))
        assert len(data) == 10, (
            f"Default page size is 10, got {len(data)}")
        assert meta["limit"] == 10
        assert meta["offset"] == 0
        assert meta["total_count"] == 12
        assert meta["has_more"] is True

        # PRD §2.3: "The `offset` parameter sets how many items to skip and
        # defaults to 0."
        data2, meta2 = validate_paginated(
            api.list_welders(shop["id"], ADMIN,
                             params={"limit": 10, "offset": 10}))
        assert len(data2) == 2
        assert meta2["total_count"] == 12
        assert meta2["has_more"] is False
