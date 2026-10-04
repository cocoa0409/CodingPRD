"""RBAC allow/deny, authentication ordering, ownership checks, not-found."""
from test_helpers import (
    ADMIN,
    CLA,
    ET,
    NON_EXISTENT_UUID,
    RM,
    ApiErrorId,
    api_client,
    create_region_payload,
    get_success_data,
    make_dealer_principal_headers,
    place_order,
    setup_base,
    setup_dealer,
    setup_onboarded_dealer,
    setup_region,
    validate_error,
    validate_success,
)


class TestAuthentication:
    def test_missing_role_header_is_unauthenticated_even_for_missing_resource(self, api):
        """PRD section 2.1: "A request missing either header, or presenting
        an `X-User-Role` value that is not one of the declared role names, is
        rejected with `ERR_UNAUTHENTICATED` (HTTP 401)."
        PRD section 2.5: "The order is: (1) authentication — the
        `X-User-Role` header is present and names a declared role, and
        `X-User-ID` is present for entity-backed roles, else
        `ERR_UNAUTHENTICATED` ... (3) path existence — path-referenced
        resources exist, validated left-to-right along the URL hierarchy,
        else `ERR_NOT_FOUND`".

        Design: Corner/validations/authenticate_before_any_business_check
        """
        resp = api._request(
            "GET", f"/dealer-network/dealers/{NON_EXISTENT_UUID}",
            headers={"Content-Type": "application/json"},
        )
        validate_error(resp, ApiErrorId.ERR_UNAUTHENTICATED, expected_status=401)

    def test_undeclared_role_is_unauthenticated(self, api):
        """PRD section 2.1: "A request missing either header, or presenting
        an `X-User-Role` value that is not one of the declared role names, is
        rejected with `ERR_UNAUTHENTICATED` (HTTP 401)."

        Design: Corner/validations/authenticate_before_any_business_check
        """
        resp = api._request(
            "GET", "/dealer-network/regions",
            headers={
                "X-User-ID": "intruder-1",
                "X-User-Role": "SuperUser",
                "Content-Type": "application/json",
            },
        )
        validate_error(resp, ApiErrorId.ERR_UNAUTHENTICATED, expected_status=401)


class TestNotFound:
    def test_get_nonexistent_dealer_returns_not_found(self, api):
        """PRD section 2.5: "(3) path existence — path-referenced resources
        exist, validated left-to-right along the URL hierarchy, else
        `ERR_NOT_FOUND`".

        Design: Corner/entities/get_nonexistent_dealer_returns_not_found
        """
        resp = api.get_dealer(NON_EXISTENT_UUID, RM)
        validate_error(resp, ApiErrorId.ERR_NOT_FOUND, expected_status=404)


class TestRbacDenials:
    def test_region_manager_cannot_suspend_dealer(self, api):
        """PRD section 2.1: "A request whose role is not listed as authorized
        for the target endpoint, or that fails an entity-backed ownership
        check, is rejected with `ERR_UNAUTHORIZED` (HTTP 403)."
        PRD section 4: "POST /dealer-network/dealers/{id}/suspend | Suspend
        an active dealer | ChannelDirector".

        Design: Corner/roles/region_manager_cannot_suspend_dealer
        """
        ctx = setup_onboarded_dealer()
        resp = api.suspend_dealer(ctx["dealer"]["id"], RM)
        validate_error(resp, ApiErrorId.ERR_UNAUTHORIZED, expected_status=403)

    def test_color_lab_admin_cannot_create_region(self, api):
        """PRD section 2.1: "A request whose role is not listed as authorized
        for the target endpoint, or that fails an entity-backed ownership
        check, is rejected with `ERR_UNAUTHORIZED` (HTTP 403)."
        PRD section 4: "POST /dealer-network/regions | Create a region |
        PlatformAdmin".

        Design: Corner/roles/color_lab_admin_cannot_create_region
        """
        resp = api.create_region(create_region_payload(), CLA)
        validate_error(resp, ApiErrorId.ERR_UNAUTHORIZED, expected_status=403)

    def test_equipment_tech_cannot_approve_order(self, api):
        """PRD section 2.1: "A request whose role is not listed as authorized
        for the target endpoint, or that fails an entity-backed ownership
        check, is rejected with `ERR_UNAUTHORIZED` (HTTP 403)."
        PRD section 4: "POST /dealer-network/orders/{id}/approve | Approve a
        submitted order | RegionManager".

        Design: Corner/roles/equipment_tech_cannot_approve_order
        """
        ctx = setup_base()
        dealer = setup_dealer(ctx["region"]["id"])
        get_success_data(api.begin_onboarding(dealer["id"], RM))
        order = place_order(dealer["id"], ctx["line"]["id"], units=40)
        resp = api.approve_order(order["id"], ET)
        validate_error(resp, ApiErrorId.ERR_UNAUTHORIZED, expected_status=403)

    def test_dealer_principal_cannot_order_for_other_dealer(self, api):
        """PRD section 3.5: "Dealer orders are placed by a `DealerPrincipal`
        acting on their own dealership — the `dealer_id` in the request must
        equal the caller's `X-User-ID`."
        PRD section 2.1: "When `X-User-Role` is `DealerPrincipal`,
        `X-User-ID` is the `id` of the acting `Dealer`; ownership checks on
        any resource that references a `Dealer` compare the resource's dealer
        foreign-key field to `X-User-ID`."

        Design: Corner/validations/dealer_principal_cannot_order_for_other_dealer
        """
        ctx = setup_base()
        dealer1 = setup_dealer(ctx["region"]["id"])
        get_success_data(api.begin_onboarding(dealer1["id"], RM))
        dealer2 = setup_dealer(
            ctx["region"]["id"], legal_name="Second Paint Co",
            latitude=43.0, longitude=-72.0,
        )
        get_success_data(api.begin_onboarding(dealer2["id"], RM))
        resp = api.create_order(
            {
                "dealer_id": dealer2["id"],
                "product_line_id": ctx["line"]["id"],
                "units": 40,
                "purpose": "INITIAL_STOCK",
            },
            make_dealer_principal_headers(dealer1["id"]),
        )
        validate_error(resp, ApiErrorId.ERR_UNAUTHORIZED, expected_status=403)


class TestRbacAllow:
    def test_dealer_principal_can_read_own_dealer(self, api):
        """PRD section 4: "GET /dealer-network/dealers/{id} | Get a dealer
        (computed posture, share, co-op balances) | PlatformAdmin,
        RegionManager, ChannelDirector, ColorLabAdmin, EquipmentTech,
        DealerPrincipal".
        PRD section 2.1: "When `X-User-Role` is `DealerPrincipal`,
        `X-User-ID` is the `id` of the acting `Dealer`".

        Design: Corner/roles/dealer_principal_read_access_shared
        """
        ctx = setup_base()
        dealer = setup_dealer(ctx["region"]["id"])
        get_success_data(api.begin_onboarding(dealer["id"], RM))
        read = validate_success(
            api.get_dealer(dealer["id"], make_dealer_principal_headers(dealer["id"]))
        )
        assert read["legal_name"] == "Beacon Paint Co"
