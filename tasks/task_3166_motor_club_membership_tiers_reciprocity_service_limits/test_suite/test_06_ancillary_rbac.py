"""Ancillary sales and refunds, RBAC denials, SoD, auth, clock default,
pagination envelope, and part-stock restock (PRD §2.1-2.4, §2.8, §3.7, §3.9)."""
from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    accept_dispatch,
    arrive_dispatch,
    create_ancillary_product,
    create_ancillary_sale,
    create_and_dispatch_call,
    create_club,
    create_club_payload,
    create_membership,
    create_part_stock,
    create_provider,
    create_settlement_period,
    create_service_call,
    create_tier,
    dispatch_call,
    get_membership,
    get_success_data,
    make_agent_headers,
    make_federation_finance_headers,
    make_settlement_clerk_headers,
    set_clock,
    setup_dispatchable_scenario,
    setup_foreign_call_scenario,
    setup_membership_scenario,
    unique_email,
    validate_error,
    validate_paginated,
    validate_success,
)


class TestAncillaryRefundInvariant:
    def test_sale_then_refund_restores_credit_and_version(self, api, member_services_rep_headers):
        """PRD §3.9: "The compensating invariant is exact: a sale followed by
        its refund leaves `account_credit_cents` unchanged, and the membership's
        `version` returns to its pre-sale value plus two — one bump per event."

        Design: Difficulty/compensating_invariant/ancillary_sale_refund_credit_invariant
        """
        base = setup_membership_scenario("CLASSIC", with_primary=False)
        m = base["membership"]
        credit0 = m["account_credit_cents"]
        version0 = m["version"]
        product = create_ancillary_product()
        sale = create_ancillary_sale(m["id"], product["id"], agent_headers=make_agent_headers("agent-1"))
        validate_success(api.refund_ancillary_sale(sale["id"], make_agent_headers("agent-1")))
        final = get_membership(m["id"])
        assert final["account_credit_cents"] == credit0
        assert final["version"] == version0 + 2

    def test_commission_rounded_half_up_and_sale_refunded(self, api, member_services_rep_headers):
        """PRD §3.9: "computes the agent's `commission_cents` as the price times
        `commission_bps` divided by ten thousand and rounded half-up" and "A
        successful refund moves the sale from `ACTIVE` to terminal `REFUNDED`".

        Design: Difficulty/compensating_invariant/ancillary_sale_refund_credit_invariant
        """
        base = setup_membership_scenario("CLASSIC", with_primary=False)
        product = create_ancillary_product(price_cents=12000, commission_bps=1000)
        sale = create_ancillary_sale(base["membership"]["id"], product["id"],
                                     agent_headers=make_agent_headers("agent-1"))
        assert sale["commission_cents"] == 1200
        resp = api.refund_ancillary_sale(sale["id"], make_agent_headers("agent-1"))
        assert validate_success(resp)["status"] == "REFUNDED"


class TestAncillaryRefundWindow:
    def test_refund_window_30_day_boundary(self, api):
        """PRD §3.9: "a sale may be refunded only within thirty days of its
        creation, with the window inclusive at exactly thirty days — later
        attempts return `ERR_REFUND_WINDOW_EXPIRED`."

        Design: Corner/validations/ancillary_refund_window_30_day_boundary
        """
        base = setup_membership_scenario("CLASSIC", with_primary=False)
        product = create_ancillary_product(product_type="TRAVEL_AGENCY", name="Travel Desk",
                                           price_cents=5000, commission_bps=800)
        agent = make_agent_headers("agent-1")
        s1 = create_ancillary_sale(base["membership"]["id"], product["id"], agent_headers=agent)
        s2 = create_ancillary_sale(base["membership"]["id"], product["id"], agent_headers=agent)
        set_clock("2026-10-01T00:00:00Z")
        ok = api.refund_ancillary_sale(s1["id"], agent)
        assert validate_success(ok)["status"] == "REFUNDED"
        set_clock("2026-10-01T00:00:01Z")
        late = api.refund_ancillary_sale(s2["id"], agent)
        validate_error(late, ApiErrorId.ERR_REFUND_WINDOW_EXPIRED, expected_status=422)


class TestAncillaryTierGate:
    def test_premier_gated_product_and_retired_product_rejected(self, api):
        """PRD §3.9: "Purchase gating is threefold and any failure returns
        `ERR_PRODUCT_TIER_GATE`: the membership must be `ACTIVE` or
        `REINSTATED`, the membership's tier `rank` must be at least the
        product's `min_tier_code` rank, and the product must be `ACTIVE`."

        Design: Corner/validations/ancillary_tier_gate_and_retired_product
        """
        base = setup_membership_scenario("CLASSIC", with_primary=False, tiers=["CLASSIC", "PREMIER"])
        m = base["membership"]
        premier_product = create_ancillary_product(
            product_type="INSURANCE_AGENCY", name="Premier Insurance", price_cents=20000,
            min_tier_code="PREMIER", commission_bps=1500,
        )
        retired_product = create_ancillary_product(
            product_type="TRAVEL_AGENCY", name="Old Travel", price_cents=4000,
            min_tier_code="CLASSIC", commission_bps=500,
        )
        validate_success(api.update_ancillary_product(retired_product["id"], {"status": "RETIRED"},
                                                      TEST_USERS["club_admin_headers"]))
        agent = make_agent_headers("agent-1")
        gated = api.create_ancillary_sale({"membership_id": m["id"], "product_id": premier_product["id"]}, agent)
        validate_error(gated, ApiErrorId.ERR_PRODUCT_TIER_GATE, expected_status=422)
        retired = api.create_ancillary_sale({"membership_id": m["id"], "product_id": retired_product["id"]}, agent)
        validate_error(retired, ApiErrorId.ERR_PRODUCT_TIER_GATE, expected_status=422)
        sales, _meta = validate_paginated(api.list_ancillary_sales(agent, params={"membership_id": m["id"]}))
        assert sales == []


class TestRbacDenials:
    def test_agent_cannot_create_club(self, api, agent_headers):
        """PRD §2.1: "A request whose role is recognized but not permitted for
        the targeted endpoint is rejected with `ERR_UNAUTHORIZED` (HTTP 403)."
        PRD §4: POST /motor-club/clubs is authorized for ClubAdmin only.

        Design: Corner/rbac/agent_cannot_create_club
        """
        resp = api.create_club(create_club_payload(), agent_headers)
        validate_error(resp, ApiErrorId.ERR_UNAUTHORIZED, expected_status=403)

    def test_dispatcher_cannot_upgrade_membership(self, api, dispatcher_headers, member_services_rep_headers):
        """PRD §2.1: "A request whose role is recognized but not permitted for
        the targeted endpoint is rejected with `ERR_UNAUTHORIZED` (HTTP 403)."
        PRD §4: POST /motor-club/memberships/{membershipId}/upgrade is
        authorized for MemberServicesRep only.

        Design: Corner/rbac/dispatcher_cannot_upgrade_membership
        """
        base = setup_membership_scenario("CLASSIC", with_primary=False, tiers=["CLASSIC", "PLUS"])
        m = base["membership"]
        resp = api.upgrade_membership(
            m["id"], {"target_tier_code": "PLUS", "expected_membership_version": m["version"]},
            dispatcher_headers,
        )
        validate_error(resp, ApiErrorId.ERR_UNAUTHORIZED, expected_status=403)
        after = get_membership(m["id"])
        assert after["tier_code"] == "CLASSIC"
        assert after["version"] == m["version"]

    def test_providerops_cannot_dispatch_call(self, api, provider_ops_headers, dispatcher_headers):
        """PRD §3.6: "Dispatching a `REQUESTED` call is the `Dispatcher`'s
        exclusive act". PRD §2.1: "A request whose role is recognized but not
        permitted for the targeted endpoint is rejected with `ERR_UNAUTHORIZED`
        (HTTP 403)."

        Design: Corner/rbac/providerops_cannot_dispatch_call
        """
        base = setup_dispatchable_scenario("CLASSIC")
        call = create_service_call(
            base["membership"]["id"], base["primary"]["id"],
            breakdown_location_state="CA", requested_tow_miles=5,
        )
        resp = api.dispatch_service_call(
            call["id"], {"expected_service_call_version": call["version"]}, provider_ops_headers,
        )
        validate_error(resp, ApiErrorId.ERR_UNAUTHORIZED, expected_status=403)
        after = get_success_data(api.get_service_call(call["id"], dispatcher_headers))
        assert after["status"] == "REQUESTED"
        assert after["version"] == call["version"]

    def test_memberservicesrep_cannot_complete_dispatch(self, api, member_services_rep_headers, dispatcher_headers):
        """PRD §2.1: "A request whose role is recognized but not permitted for
        the targeted endpoint is rejected with `ERR_UNAUTHORIZED` (HTTP 403)."
        PRD §4: POST /motor-club/dispatches/{dispatchId}/complete is authorized
        for ProviderOps only.

        Design: Corner/rbac/memberservicesrep_cannot_complete_dispatch
        """
        base = setup_dispatchable_scenario("CLASSIC")
        pair = create_and_dispatch_call(
            base["membership"]["id"], base["primary"]["id"],
            breakdown_location_state="CA", requested_tow_miles=5,
        )
        accept_dispatch(pair["dispatch"]["id"], en_route=True)
        arrive_dispatch(pair["dispatch"]["id"])
        resp = api.complete_dispatch(pair["dispatch"]["id"], {"actual_tow_miles": 5},
                                     member_services_rep_headers)
        validate_error(resp, ApiErrorId.ERR_UNAUTHORIZED, expected_status=403)
        after = get_success_data(api.get_dispatch(pair["dispatch"]["id"], dispatcher_headers))
        assert after["status"] == "ARRIVED"

    def test_settlementclerk_cannot_assess_period(self, api):
        """PRD §2.1: "A request whose role is recognized but not permitted for
        the targeted endpoint is rejected with `ERR_UNAUTHORIZED` (HTTP 403)."
        PRD §4: POST /motor-club/settlement-periods/{periodId}/assess is
        authorized for FederationFinance only.

        Design: Corner/rbac/settlementclerk_cannot_assess_period
        """
        scenario = setup_foreign_call_scenario()
        period = create_settlement_period(scenario["servicing_club"]["id"])
        set_clock("2026-10-01T00:00:00Z")
        clerk1 = make_settlement_clerk_headers("clerk-1")
        validate_success(api.close_settlement_period(period["id"], clerk1))
        resp = api.assess_settlement_period(period["id"], clerk1)
        validate_error(resp, ApiErrorId.ERR_UNAUTHORIZED, expected_status=403)
        after = get_success_data(api.get_settlement_period(period["id"], clerk1))
        assert after["status"] == "CLOSED"


class TestSegregationOfDuties:
    def test_closer_cannot_assess_own_period(self, api):
        """PRD §3.8: "Segregation of duties is hard: the assessing officer's
        `X-User-ID` must differ from the `closed_by` recorded at close, else
        `ERR_SOD_CONFLICT`."

        Design: Corner/rbac/segregation_of_duties_closer_cannot_assess
        """
        scenario = setup_foreign_call_scenario()
        period = create_settlement_period(scenario["servicing_club"]["id"])
        set_clock("2026-10-01T00:00:00Z")
        validate_success(api.close_settlement_period(period["id"], make_settlement_clerk_headers("clerk-1")))
        conflict = api.assess_settlement_period(period["id"], make_federation_finance_headers("clerk-1"))
        validate_error(conflict, ApiErrorId.ERR_SOD_CONFLICT, expected_status=422)
        ok = api.assess_settlement_period(period["id"], make_federation_finance_headers("fin-9"))
        assert validate_success(ok)["status"] == "ASSESSED"


class TestAuthentication:
    def test_missing_auth_headers_rejected(self, api):
        """PRD §2.1: "A request missing either header, or presenting a role the
        system does not recognize, is rejected with `ERR_UNAUTHENTICATED`
        (HTTP 401)."

        Design: Corner/rbac/missing_auth_headers_rejected
        """
        resp = api.list_clubs(headers={})
        validate_error(resp, ApiErrorId.ERR_UNAUTHENTICATED, expected_status=401)


class TestClockDefault:
    def test_default_clock_stamps_term_dates(self, api, member_services_rep_headers):
        """PRD §2.4: "At server startup the clock reads exactly
        `2026-09-01T00:00:00Z`". PRD §3.2: "`enrolled_at` and `term_start_date`
        are stamped at the logical now, and `term_end_date` is set exactly 365
        days later".

        Design: Corner/endpoints/clock_default_and_sweep_determinism
        """
        club = create_club()
        create_tier("CLASSIC")
        resp = api.create_membership(
            {"home_club_id": club["id"], "primary_member_name": "Pat Primary",
             "primary_member_email": unique_email(), "tier_code": "CLASSIC"},
            member_services_rep_headers,
        )
        m = validate_success(resp, expected_status=201)
        assert m["term_start_date"] == "2026-09-01T00:00:00.000Z"
        assert m["term_end_date"] == "2027-09-01T00:00:00.000Z"


class TestMembershipPagination:
    def test_pagination_envelope_and_status_filter(self, api, member_services_rep_headers):
        """PRD §2.3: "The `meta` object of a list response carries exactly the
        pagination fields `limit`, `offset`, `total_count`, and `has_more`."
        PRD §4: GET /motor-club/memberships is "filterable by status, home
        club".

        Design: Corner/endpoints/memberships_list_pagination_envelope
        """
        base = setup_membership_scenario("CLASSIC", with_primary=False)
        m1 = base["membership"]
        create_membership(base["club"]["id"], "CLASSIC")
        create_membership(base["club"]["id"], "CLASSIC")
        validate_success(api.cancel_membership(m1["id"], member_services_rep_headers))
        page1, meta1 = validate_paginated(
            api.list_memberships(member_services_rep_headers, params={"limit": 2, "offset": 0})
        )
        assert len(page1) == 2
        assert meta1["total_count"] == 3
        assert meta1["has_more"] is True
        page2, meta2 = validate_paginated(
            api.list_memberships(member_services_rep_headers, params={"limit": 2, "offset": 2})
        )
        assert len(page2) == 1
        assert meta2["has_more"] is False
        cancelled, meta3 = validate_paginated(
            api.list_memberships(member_services_rep_headers, params={"status": "CANCELLED"})
        )
        assert len(cancelled) == 1
        assert cancelled[0]["id"] == m1["id"]


class TestPartStockRestock:
    def test_restock_adds_to_existing_quantity(self, api, provider_ops_headers, club_admin_headers):
        """PRD §3.7: "a restock adds its `add_quantity` to `quantity_on_hand`."

        Design: Corner/endpoints/restock_adds_to_existing_quantity
        """
        club = create_club()
        provider = create_provider(club["id"], name="NCA Fleet 1", capabilities=["BATTERY"],
                                   max_concurrent_dispatches=1)
        stock = create_part_stock(provider["id"], part_sku="BAT-G24", part_kind="BATTERY", quantity_on_hand=3)
        resp = api.restock_part_stock(stock["id"], {"add_quantity": 5}, provider_ops_headers)
        assert validate_success(resp)["quantity_on_hand"] == 8
