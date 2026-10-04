"""Authentication, authorization, and ownership enforcement (PRD §2.1, §2.6)."""
from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    create_delivery_year_payload,
    create_offer_payload,
    get_success_data,
    make_resource_owner_headers,
    create_owner,
    create_resource,
    create_and_approve_resource,
    create_and_open_run,
    submit_offer,
    setup_delivery_year_with_forecast,
    setup_forecast_locked_year,
    set_clock,
    validate_error,
)

ADMIN = TEST_USERS["market_admin_headers"]
OPS = TEST_USERS["settlement_ops_headers"]


class TestAuthentication:
    def test_missing_auth_headers_rejected(self, api):
        """PRD §2.1: "A request missing either header, presenting an empty
        `X-User-ID`, or naming a role outside this set is rejected with
        `ERR_UNAUTHENTICATED` (HTTP 401)."

        Design: Corner/rbac/missing_auth_headers_returns_unauthenticated
        """
        set_clock()
        resp = api.list_delivery_years(headers={})
        validate_error(resp, ApiErrorId.ERR_UNAUTHENTICATED, expected_status=401)


class TestRoleDenials:
    def test_resource_owner_cannot_lock_forecast(self, api):
        """PRD §2.1: "A request whose role is not permitted to invoke the
        target endpoint is rejected with `ERR_FORBIDDEN` (HTTP 403)."
        PRD §4: POST /capacity-market/delivery-years/{id}/lock-forecast is
        authorized for MarketAdmin only.

        Design: Corner/rbac/resource_owner_cannot_lock_forecast
        """
        dy, zone, forecast = setup_delivery_year_with_forecast()
        owner = create_owner()
        resp = api.lock_forecast(dy["id"], make_resource_owner_headers(owner["id"]))
        validate_error(resp, ApiErrorId.ERR_FORBIDDEN, expected_status=403)
        dy_after = get_success_data(api.get_delivery_year(dy["id"], ADMIN))
        assert dy_after["status"] == "DRAFT"

    def test_settlement_ops_cannot_create_delivery_year(self, api):
        """PRD §2.1: "`SettlementOps` settles and closes delivery years and
        otherwise reads." PRD §4: POST /capacity-market/delivery-years is
        authorized for MarketAdmin only.

        Design: Corner/rbac/settlement_ops_cannot_create_delivery_year
        """
        set_clock()
        resp = api.create_delivery_year(create_delivery_year_payload(), OPS)
        validate_error(resp, ApiErrorId.ERR_FORBIDDEN, expected_status=403)

    def test_market_admin_cannot_submit_offer(self, api):
        """PRD §2.1: "`ResourceOwner` is the market-participant role: it
        registers and retires its own resources, and submits accreditations,
        offers, withdrawals, replacement transactions, and measurement reports
        for resources it owns." PRD §4: POST /capacity-market/offers is
        authorized for ResourceOwner only.

        Design: Corner/rbac/market_admin_cannot_submit_offer
        """
        dy, zone, forecast = setup_forecast_locked_year()
        owner = create_owner()
        resource, _ = create_and_approve_resource(owner["id"], zone["id"], dy["id"])
        run = create_and_open_run(dy["id"])
        payload = create_offer_payload(resource["id"], run["id"],
                                       offer_mw=10.0, offer_price_per_mw_day=70.0)
        resp = api.create_offer(payload, ADMIN)
        validate_error(resp, ApiErrorId.ERR_FORBIDDEN, expected_status=403)


class TestOwnershipEnforcement:
    def test_foreign_owner_cannot_withdraw_offer(self, api):
        """PRD §2.6: "Ownership — for owner-scoped mutations, the acting
        `ResourceOwner` must own the resource, offer, or commitment being
        mutated; failure yields `ERR_OWNERSHIP_VIOLATION`."

        Design: Corner/rbac/ownership_violation_foreign_owner_cannot_withdraw
        """
        dy, zone, forecast = setup_forecast_locked_year()
        o1 = create_owner(legal_name="Alpha GenCo", contact_email="alpha@x.com")
        o2 = create_owner(legal_name="Beta GenCo", contact_email="beta@x.com")
        resource, _ = create_and_approve_resource(o1["id"], zone["id"], dy["id"])
        run = create_and_open_run(dy["id"])
        offer = submit_offer(resource["id"], o1["id"], run["id"],
                             offer_mw=10.0, offer_price_per_mw_day=70.0)
        run_now = get_success_data(api.get_auction_run(run["id"], ADMIN))
        resp = api.withdraw_offer(
            offer["id"], run_now["version"], make_resource_owner_headers(o2["id"]),
        )
        validate_error(resp, ApiErrorId.ERR_OWNERSHIP_VIOLATION, expected_status=403)
        offer_after = get_success_data(api.get_offer(offer["id"], ADMIN))
        assert offer_after["status"] == "SUBMITTED"
