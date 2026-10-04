"""Authentication, authorization, and peer-role exclusivity."""
from test_helpers import (
    NO_AUTH_HEADERS,
    TEST_USERS,
    ApiErrorId,
    create_allocation_run_payload,
    create_capacity_pool_payload,
    create_part_payload,
    make_customer,
    make_customer_headers,
    make_order,
    make_part,
    validate_error,
    validate_success,
)

ADMIN = TEST_USERS["platform_admin_headers"]
CHANNEL = TEST_USERS["channel_manager_headers"]
QUALITY = TEST_USERS["quality_engineer_headers"]


class TestRbacAndAuth:
    def test_missing_auth_headers_unauthenticated(self, api):
        """PRD §2.1: "A request missing either header, or carrying a role outside
        this set, is rejected with `ERR_UNAUTHENTICATED` (HTTP 401)."

        Design: Corner/validations/missing_auth_headers_unauthenticated
        """
        res = api.list_orders(NO_AUTH_HEADERS)
        validate_error(res, ApiErrorId.ERR_UNAUTHENTICATED)
        assert res.status_code == 401

    def test_customer_role_cannot_create_part(self, api):
        """PRD §2.1: "A request whose role is recognized but not permitted on the
        target endpoint is rejected with `ERR_UNAUTHORIZED` (HTTP 403)."
        PRD §4: POST /parts is authorized for SupplyPlanner only.

        Design: Corner/validations/customer_role_cannot_create_part
        """
        cust = make_customer(name="RBAC Probe", tier="STANDARD",
                             channel="DIRECT_FIELD", credit_limit_cents=1_000_000)
        res = api.create_part(
            create_part_payload(
                part_number="RBAC1", description="Forbidden",
                package_family="SOIC", process_technology="CMOS_180NM",
            ),
            make_customer_headers(cust["id"]),
        )
        validate_error(res, ApiErrorId.ERR_UNAUTHORIZED)
        assert res.status_code == 403

    def test_customer_cannot_read_other_customers_order(self, api):
        """PRD §2.1: "When `X-User-Role` is `Customer`, `X-User-ID` is the `id` of
        the acting `Customer` entity: ownership checks on any resource that
        references a customer — an order's `customer_id`, a lifetime buy's
        `customer_id`, or the customer record itself — compare that foreign key to
        `X-User-ID`, and a mismatch is rejected with `ERR_UNAUTHORIZED` (HTTP 403)."

        Design: Corner/validations/customer_cannot_read_other_customers_order
        """
        part = make_part(part_number="UA741CN")
        cust_a = make_customer(name="Owner A", credit_limit_cents=1_000_000)
        cust_b = make_customer(name="Snooper B", credit_limit_cents=1_000_000)
        order = make_order(cust_a["id"], [{"part_id": part["id"], "quantity": 1}])

        res = api.get_order(order["id"], make_customer_headers(cust_b["id"]))
        validate_error(res, ApiErrorId.ERR_UNAUTHORIZED)
        assert res.status_code == 403

        own = validate_success(
            api.get_order(order["id"], make_customer_headers(cust_a["id"])), 200
        )
        assert own["id"] == order["id"]

    def test_role_exclusive_operations_denied_to_other_roles(self, api):
        """PRD §2.1: "A request whose role is recognized but not permitted on the
        target endpoint is rejected with `ERR_UNAUTHORIZED` (HTTP 403)."
        PRD §2.1: "`PlatformAdmin` operates the benchmark harness: it alone drives
        the logical clock, and it may read every resource."
        PRD §4: POST /capacity-pools is authorized for SupplyPlanner only;
        POST /allocation-runs is authorized for SupplyPlanner only.

        Design: Corner/rbac/role_exclusive_operations_denied_to_other_roles
        """
        r1 = api.create_part(
            create_part_payload(
                part_number="RBAC2", description="Admin attempt",
                package_family="SOIC", process_technology="CMOS_180NM",
            ),
            ADMIN,
        )
        validate_error(r1, ApiErrorId.ERR_UNAUTHORIZED)
        assert r1.status_code == 403

        r2 = api.create_capacity_pool(
            create_capacity_pool_payload(site_name="RBAC-FAB", total_units=100),
            QUALITY,
        )
        validate_error(r2, ApiErrorId.ERR_UNAUTHORIZED)
        assert r2.status_code == 403

        r3 = api.create_allocation_run(
            create_allocation_run_payload("2026-W46"), CHANNEL
        )
        validate_error(r3, ApiErrorId.ERR_UNAUTHORIZED)
        assert r3.status_code == 403
