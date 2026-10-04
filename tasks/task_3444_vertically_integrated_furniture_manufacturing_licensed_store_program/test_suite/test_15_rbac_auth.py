"""Access control: role denial, entity-backed ownership denial, and missing
authentication headers (PRD §2.1, §2.8, §4)."""
from test_helpers import (
    NON_EXISTENT_UUID,
    ApiErrorId,
    create_active_licensee,
    create_licensee_order,
    create_product_line_payload,
    create_retail_account,
    get_order,
    make_licensee_manager_headers,
    make_wholesale_buyer_headers,
    setup_open_cycle,
    submit_order,
    validate_error,
)


class TestRoleDenial:
    def test_wholesale_buyer_cannot_create_product_line(self, api, platform_admin_headers):
        """PRD §2.1: "Every endpoint restricts which roles may call it (§4 lists the
        authorized roles per endpoint); a caller whose role is not in the endpoint's
        list is rejected with `ERR_FORBIDDEN_ROLE` (HTTP 403)."
        PRD §4: POST /api/product-lines — "Create a product line (starts `CONCEPT`);
        price must be on the ladder" — authorized role: PlatformAdmin.

        Design: Corner/rbac/wholesale_buyer_cannot_create_product_line
        """
        account = create_retail_account(credit_limit_cents=1_000_000)
        resp = api.create_product_line(
            create_product_line_payload(
                name="Forbidden Line",
                category="BEDDING",
                price_point_cents=39900,
                style_code="FB-01",
            ),
            make_wholesale_buyer_headers(account["id"]),
        )
        validate_error(resp, ApiErrorId.ERR_FORBIDDEN_ROLE.value)

    def test_licensee_manager_cannot_run_allocation(self, api, production_planner_headers):
        """PRD §2.1: "a caller whose role is not in the endpoint's list is rejected with
        `ERR_FORBIDDEN_ROLE` (HTTP 403)."
        PRD §4: POST /api/allocation-cycles/{id}/run-allocation — "Run the capacity
        waterfall (`OPEN → ALLOCATED`)" — authorized role: ProductionPlanner.

        Design: Corner/rbac/licensee_manager_cannot_run_allocation
        """
        ctx = setup_open_cycle()
        resp = api.run_allocation(
            ctx["cycle"]["id"],
            make_licensee_manager_headers(ctx["licensee"]["id"]),
        )
        validate_error(resp, ApiErrorId.ERR_FORBIDDEN_ROLE.value)
        from test_helpers import get_cycle

        assert get_cycle(ctx["cycle"]["id"])["status"] == "OPEN"


class TestOwnershipDenial:
    def test_licensee_cannot_cancel_other_licensees_order(self, api, platform_admin_headers):
        """PRD §2.1: "When `X-User-Role` is `LicenseeManager`, `X-User-ID` is the `id`
        of the acting `Licensee`; ownership checks on any resource that references a
        licensee compare the resource's `licensee_id` foreign key to `X-User-ID`. ...
        A mismatch on a buyer-scoped operation is rejected with
        `ERR_NOT_RESOURCE_OWNER` (HTTP 403)."
        PRD §3.5: "Cancellation (action `CANCEL`, with an optional `reason` recorded
        into the order's `cancel_reason`) is open to the buyer owner or a
        `PlatformAdmin`"

        Design: Corner/rbac/licensee_cannot_cancel_other_licensees_order
        """
        ctx = setup_open_cycle()
        prairie = create_active_licensee(business_name="Prairie Furniture Co")
        order = create_licensee_order(
            ctx["licensee"], ctx["cycle"], ctx["line"], quantity=3
        )
        submit_order(order)
        # Prairie's manager is role-allowed to cancel but does not own the order.
        resp = api.transition_order(
            order["id"],
            {"action": "CANCEL", "reason": "not mine but trying"},
            make_licensee_manager_headers(prairie["id"]),
        )
        validate_error(resp, ApiErrorId.ERR_NOT_RESOURCE_OWNER.value)
        fetched = get_order(order["id"])
        assert fetched["allocation_state"] == "RESERVED"
        assert fetched["fulfillment_state"] == "PENDING"


class TestAuthentication:
    def test_missing_auth_headers_returns_unauthenticated(self, api):
        """PRD §2.1: "Every request must carry two headers: `X-User-ID`, identifying
        the acting user, and `X-User-Role`, naming their operational capacity. ... A
        request missing either header, or carrying a role outside this list, is rejected
        with `ERR_UNAUTHENTICATED` (HTTP 401)."
        PRD §2.8: "1. **Authentication.** ... otherwise `ERR_UNAUTHENTICATED` (HTTP
        401)." — stage 1 precedes the existence stage.

        Design: Corner/rbac/missing_auth_headers_returns_unauthenticated
        """
        resp = api.get_licensee(NON_EXISTENT_UUID, None)
        err = validate_error(resp, ApiErrorId.ERR_UNAUTHENTICATED.value)
        assert resp.status_code == 401
        assert err["error_id"] != ApiErrorId.ERR_LICENSEE_NOT_FOUND.value
