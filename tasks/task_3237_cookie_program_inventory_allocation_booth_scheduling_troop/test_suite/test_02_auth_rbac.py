"""Authentication and role-authorization coverage."""
from test_helpers import (
    ApiErrorId,
    NON_EXISTENT_UUID,
    add_product,
    create_order_with_lines,
    create_season,
    create_troop,
    make_council_admin_headers,
    make_troop_leader_headers,
    open_season,
    set_clock,
    validate_error,
    validate_success,
)


class TestAuthentication:
    def test_auth_missing_role_header_rejected(self, api):
        """PRD §2.1: "A request missing either header, or carrying a role value
        outside the declared set, is rejected with `ERR_UNAUTHENTICATED` (HTTP
        401)."

        Design: Corner/validations/auth_missing_role_header_rejected
        """
        resp = api.list_seasons(headers={"Content-Type": "application/json"})
        validate_error(resp, ApiErrorId.ERR_UNAUTHENTICATED, 401)

    def test_priority_auth_beats_not_found(self, api):
        """PRD §2.10: "Authentication (`ERR_UNAUTHENTICATED`) runs first, then
        role authorization (`ERR_UNAUTHORIZED`), then left-to-right path
        existence (`ERR_NOT_FOUND`)"."

        Design: Corner/validations/priority_auth_beats_not_found
        """
        resp = api.get_season(
            NON_EXISTENT_UUID, headers={"Content-Type": "application/json"}
        )
        validate_error(resp, ApiErrorId.ERR_UNAUTHENTICATED, 401)


class TestRoleAuthorization:
    def test_troop_leader_cannot_confirm_order(self, api):
        """PRD §2.1: "Certain operations are reserved for `CouncilAdmin` alone:
        season lifecycle transitions, catalog and site administration,
        purchase-order management, order confirmation and rejection, transfer
        completion, booth slot creation, lottery draws and manual approvals,
        refunds, forfeitures and dispute resolution, recall activation, and the
        test clock." PRD §2.1: "A request whose authenticated role is not
        permitted for the target endpoint is rejected with `ERR_UNAUTHORIZED`
        (HTTP 403)."

        Design: Corner/rbac/troop_leader_cannot_confirm_order
        """
        admin = make_council_admin_headers()
        season = create_season(admin=admin)
        product = add_product(season["id"], admin=admin)
        open_season(season["id"], admin=admin)
        troop = create_troop(admin=admin)
        leader = make_troop_leader_headers(troop["id"])
        set_clock("2027-01-10T00:00:00Z", admin=admin)
        order = create_order_with_lines(
            season["id"], troop, [(product["id"], 80)], leader=leader
        )
        validate_success(api.submit_order(season["id"], order["id"], leader))
        resp = api.confirm_order(season["id"], order["id"], leader)
        validate_error(resp, ApiErrorId.ERR_UNAUTHORIZED, 403)

    def test_troop_leader_cannot_touch_other_troops_order(self, api):
        """PRD §2.1: "A troop leader who attempts to act on a resource owned by
        a different troop is rejected with `ERR_FORBIDDEN_OWNERSHIP` (HTTP
        403)."

        Design: Corner/rbac/troop_leader_cannot_touch_other_troops_order
        """
        admin = make_council_admin_headers()
        season = create_season(admin=admin)
        product = add_product(season["id"], admin=admin)
        open_season(season["id"], admin=admin)
        troop1 = create_troop(admin=admin)
        troop2 = create_troop(admin=admin)
        leader1 = make_troop_leader_headers(troop1["id"])
        leader2 = make_troop_leader_headers(troop2["id"])
        set_clock("2027-01-10T00:00:00Z", admin=admin)
        order = create_order_with_lines(
            season["id"], troop1, [(product["id"], 10)], leader=leader1
        )
        resp = api.submit_order(season["id"], order["id"], leader2)
        validate_error(resp, ApiErrorId.ERR_FORBIDDEN_OWNERSHIP, 403)
        from test_helpers import get_order

        unchanged = get_order(order["id"], admin=admin)
        assert unchanged["status"] == "DRAFT"
