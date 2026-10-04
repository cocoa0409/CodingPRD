"""Authentication and role-authorization gates."""
from test_helpers import (
    TEST_USERS,
    ApiErrorId,
    create_location,
    create_offer_payload,
    validate_error,
    validate_success,
)

ADMIN = TEST_USERS["platform_admin_headers"]
MANAGER = TEST_USERS["shift_manager_headers"]
KITCHEN = TEST_USERS["kitchen_staff_headers"]
CARHOP = TEST_USERS["carhop_headers"]


class TestUnauthenticated:
    def test_unauthenticated_request_rejected(self, api):
        """PRD: "A request missing a role header, carrying an undeclared role
        value, or — for entity-backed roles — missing the user identifier is
        rejected with `ERR_UNAUTHENTICATED` (HTTP 401)."

        A read with no auth headers at all fails authentication before any
        role check.

        Design: Corner/validations/unauthenticated_request_rejected
        """
        location = create_location(code="CRN-AUTH1")
        resp = api.get_location(location["id"], headers={"Content-Type": "application/json"})
        validate_error(resp, ApiErrorId.ERR_UNAUTHENTICATED)

    def test_undeclared_role_value_rejected(self, api):
        """PRD: "A request missing a role header, carrying an undeclared role
        value, or — for entity-backed roles — missing the user identifier is
        rejected with `ERR_UNAUTHENTICATED` (HTTP 401)."

        A made-up role value is not one of the five declared roles.

        Design: Corner/validations/unauthenticated_request_rejected
        """
        location = create_location(code="CRN-AUTH2")
        resp = api.get_location(
            location["id"],
            headers={
                "X-User-ID": "intruder-1",
                "X-User-Role": "SuperUser",
                "Content-Type": "application/json",
            },
        )
        validate_error(resp, ApiErrorId.ERR_UNAUTHENTICATED)


class TestForbidden:
    def test_wrong_role_forbidden_on_admin_endpoint(self, api, shift_manager_headers):
        """PRD: "A request whose role is not permitted on the target endpoint
        is rejected with `ERR_FORBIDDEN` (HTTP 403)."

        POST /locations is PlatformAdmin-only; a ShiftManager is forbidden.

        Design: Corner/validations/wrong_role_forbidden_on_admin_endpoint
        """
        resp = api.create_location(
            {
                "code": "X",
                "name": "X",
                "timezone": "America/Chicago",
                "stall_capacity": 1,
            },
            shift_manager_headers,
        )
        validate_error(resp, ApiErrorId.ERR_FORBIDDEN)

    def test_kitchen_staff_forbidden_on_admin_endpoint(self, api, kitchen_staff_headers):
        """PRD: "A request whose role is not permitted on the target endpoint
        is rejected with `ERR_FORBIDDEN` (HTTP 403)."

        KitchenStaff, limited to the preparation pipeline, is equally
        forbidden from creating a location.

        Design: Corner/validations/wrong_role_forbidden_on_admin_endpoint
        """
        resp = api.create_location(
            {
                "code": "Y",
                "name": "Y",
                "timezone": "America/Chicago",
                "stall_capacity": 1,
            },
            kitchen_staff_headers,
        )
        validate_error(resp, ApiErrorId.ERR_FORBIDDEN)


class TestRoleDenials:
    def test_kitchen_staff_cannot_create_offers(self, api, kitchen_staff_headers):
        """PRD §2.1: "`KitchenStaff` advances the preparation pipeline only"

        Creating an offer is a ShiftManager/PlatformAdmin operation;
        KitchenStaff is denied.

        Design: Corner/rbac/kitchen_staff_cannot_create_offers
        """
        location = create_location(code="CRN-RBAC1")
        resp = api.create_offer(
            location["id"],
            create_offer_payload(
                code="O", kind="PROMO", discount_type="PERCENT_OFF_ORDER",
                discount_value=10, window_start_local="00:00", window_end_local="23:59",
            ),
            kitchen_staff_headers,
        )
        validate_error(resp, ApiErrorId.ERR_FORBIDDEN)

    def test_kitchen_staff_cannot_create_offers_even_valid_payload(self, api):
        """PRD §2.1: "`KitchenStaff` advances the preparation pipeline only"

        A fully valid offer payload does not rescue a KitchenStaff caller.

        Design: Corner/rbac/kitchen_staff_cannot_create_offers
        """
        location = create_location(code="CRN-RBAC2")
        resp = api.create_offer(
            location["id"],
            create_offer_payload(
                code="VALID", kind="PROMO", discount_type="FIXED_OFF_CENTS",
                discount_value=100, window_start_local="08:00",
                window_end_local="12:00", app_only=False,
            ),
            KITCHEN,
        )
        validate_error(resp, ApiErrorId.ERR_FORBIDDEN)

    def test_carhop_cannot_settle_tip(self, api, carhop_headers):
        """PRD: "Settlement is a `ShiftManager` close-of-shift ritual."

        Tip settlement is ShiftManager-only; a Carhop is denied before any
        record lookup.

        Design: Corner/rbac/carhop_cannot_settle_tip
        """
        from test_helpers import NON_EXISTENT_UUID

        location = create_location(code="CRN-RBAC3")
        resp = api.settle_tip(location["id"], NON_EXISTENT_UUID, {}, carhop_headers)
        validate_error(resp, ApiErrorId.ERR_FORBIDDEN)

    def test_carhop_cannot_settle_tip_with_adjustment(self, api):
        """PRD: "Settlement is a `ShiftManager` close-of-shift ritual."

        The denial holds even when the request carries a valid adjustment.

        Design: Corner/rbac/carhop_cannot_settle_tip
        """
        from test_helpers import NON_EXISTENT_UUID

        location = create_location(code="CRN-RBAC4")
        resp = api.settle_tip(
            location["id"], NON_EXISTENT_UUID, {"adjusted_tip_cents": 50}, CARHOP
        )
        validate_error(resp, ApiErrorId.ERR_FORBIDDEN)
