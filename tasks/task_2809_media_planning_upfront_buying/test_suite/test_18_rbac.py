"""Role-based access control across the upfront buying surface.

The file walks the authorisation ladder in the order the requirement fixes it:
authentication of the declared headers, then role authorisation for the
operation, then resource ownership for the two entity-backed roles, and finally
the identity-level segregation of duties that guards a seller remittance.
"""

from test_helpers import (
    BUYER_HEADERS,
    BUYER_USER_ID,
    CONTROLLER_ALT_HEADERS,
    CONTROLLER_ALT_USER_ID,
    CONTROLLER_HEADERS,
    MEASUREMENT_HEADERS,
    NO_AUTH_HEADERS,
    NO_ROLE_HEADERS,
    PLANNER_HEADERS,
    UNDECLARED_ROLE_HEADERS,
    ApiErrorId,
    BuyStatus,
    DedupMethod,
    ForecastStatus,
    InvoiceSellerStatus,
    MeasurementBasis,
    PlanPosture,
    ReportStatus,
    RunStatus,
    SettlementStatus,
    StewardshipStatus,
    UserRole,
    assert_allocation_posture,
    assert_buy_axes,
    assert_campaign_axes,
    assert_cents,
    assert_invoice_axes,
    assert_pct4,
    factories as fa,
    fixtures as fx,
    get_success_data,
    make_controller_headers,
    make_seller_rep_headers,
    validate_error,
    validate_paginated,
    validate_success,
)

#: Headers naming a recognised role but carrying no acting user identifier at
#: all.  ``test_helpers`` offers an empty-identifier variant; this one omits the
#: header outright, which is the case the requirement's first ladder rung names.
_ROLE_WITHOUT_USER_HEADERS = {
    "X-User-Role": UserRole.AGENCY_CONTROLLER.value,
    "Content-Type": "application/json",
}

#: The brand and the seller every scenario below is transacted between.
_ADVERTISER = {
    "name": "Cascadia Beverage",
    "category_code": "BEVERAGE",
    "credit_limit_cents": 500_000_000,
    "payment_terms_days": 30,
    "sequential_liability_enabled": True,
}

_SELLER = {
    "name": "Harbor Broadcasting",
    "platform_types": ["LINEAR", "CTV", "DIGITAL"],
    "make_good_capacity_impressions": 50_000_000,
}

_SECOND_SELLER = {
    "name": "Summit Cable",
    "platform_types": ["CTV"],
    "make_good_capacity_impressions": 20_000_000,
}

#: A single-channel plan whose whole ten-million-cent budget runs in prime linear.
_CAMPAIGN = {
    "name": "Q4 Linear Base",
    "target_demo": "A25-54",
    "universe_thousands": 120_000,
    "reach_goal_pct": 60.0,
    "frequency_goal": 4.0,
    "total_budget_cents": 10_000_000,
    "flight_start": "2026-11-01T00:00:00Z",
    "flight_end": "2026-12-31T23:59:59Z",
    "fiscal_quarter": "2026Q4",
}

_ALLOCATION = {
    "channel": "LINEAR_TV",
    "allocation_pct": 100.00,
    "planned_cpm_cents": 2000,
    "planned_market": "UPFRONT",
    "primary_daypart": "PRIME",
}

_AVAIL = {
    "market": "UPFRONT",
    "fiscal_quarter": "2026Q4",
    "daypart": "PRIME",
    "program": "Harbor Nightly",
    "platform": "LINEAR",
    "window_start": "2026-11-01T00:00:00Z",
    "window_end": "2026-12-31T23:59:59Z",
    "total_impressions": 10_000_000,
    "forecast_cpm_cents": 2200,
    "exclusivity_mode": "SHARED",
}

_NEGOTIATION = {
    "market": "UPFRONT",
    "channel": "LINEAR_TV",
    "requested_impressions": 1_000_000,
    "opening_cpm_cents": 2000,
    "guarantee_pct": 100,
    "make_good_provision": "MAKE_GOOD_UNITS",
    "option_pct_ceiling": 25,
}

_UNIT = {
    "daypart": "PRIME",
    "program": "Harbor Nightly",
    "platform": "LINEAR",
    "units": 1,
    "unit_rate_cents": 2_200_000,
    "projected_impressions": 1_000_000,
    "air_window_start": "2026-11-02T00:00:00Z",
    "air_window_end": "2026-11-30T23:59:59Z",
    "exclusive": False,
}


def _advertiser_and_campaign(api):
    """A registered brand with one drafted campaign against it."""
    advertiser = fx.register_advertiser(api, **_ADVERTISER)
    campaign = fx.open_campaign(api, advertiser["id"], **_CAMPAIGN)
    return {
        "advertiser_id": advertiser["id"],
        "campaign_id": campaign["id"],
    }


def _approved_plan(api):
    """The whole-budget linear plan, approved by the brand and so locked."""
    world = _advertiser_and_campaign(api)
    seller = fx.register_seller(api, **_SELLER)
    allocation = fx.add_allocation(api, world["campaign_id"], **_ALLOCATION)
    fx.submit_plan(api, world["campaign_id"])
    fx.approve_plan(api, world["campaign_id"], world["advertiser_id"])
    world["seller_id"] = seller["id"]
    world["allocation_id"] = allocation["id"]
    return world


def _covered_buy(api):
    """A buy at PENDING_PLACEMENT whose single line covers the whole guarantee.

    The seller owns the only avail behind the line, the plan is approved and the
    campaign version the buyer last read is captured, so the buy is one placement
    call away from committing its budget.
    """
    world = _approved_plan(api)
    avail = fx.file_avail(api, world["seller_id"], **_AVAIL)
    fx.publish_avail(api, avail["id"], world["seller_id"])
    negotiation = fx.open_negotiation(
        api,
        world["campaign_id"],
        world["seller_id"],
        world["allocation_id"],
        **_NEGOTIATION,
    )
    fx.counter(
        api,
        negotiation["id"],
        world["seller_id"],
        counter_cpm_cents=2200,
        counter_impressions=1_000_000,
    )
    buy = fx.accept_negotiation(api, negotiation["id"])
    unit = fx.add_unit(api, buy["id"], avail["id"], **_UNIT)
    campaign = get_success_data(api.get_campaign(world["campaign_id"], BUYER_HEADERS))
    world.update(
        {
            "forecast_id": avail["id"],
            "negotiation_id": negotiation["id"],
            "buy_id": buy["id"],
            "unit_id": unit["id"],
            "campaign_version": campaign["version"],
        }
    )
    return world


def _placed_buy(api):
    """The same buy, placed by ``buyer-01`` and so committing the campaign."""
    world = _covered_buy(api)
    fx.place_buy(api, world["buy_id"], world["campaign_id"])
    return world


def _two_sellers_with_a_draft_avail(api):
    """Two registered sellers, with the first holding one unpublished avail."""
    owner = fx.register_seller(api, **_SELLER)
    stranger = fx.register_seller(api, **_SECOND_SELLER)
    avail = fx.file_avail(api, owner["id"], **_AVAIL)
    return {
        "owner_id": owner["id"],
        "stranger_id": stranger["id"],
        "forecast_id": avail["id"],
    }


class TestUnauthenticatedRequests:
    """The first rung of the ladder: the headers themselves."""

    def test_a_missing_or_unrecognised_role_header_is_rejected_before_anything_else(
        self, api
    ):
        """A write with no role, a write with a role but no acting user, a write
        naming a role outside the declared six and a read with neither header are
        all answered 401 ERR_UNAUTHENTICATED, and no advertiser is created.

        PRD: "If either header is absent, or if `X-User-Role` is not exactly one
        of the six recognised role names, the request is rejected with
        `ERR_UNAUTHENTICATED` (HTTP 401)."

        Design: Corner/rbac/a_request_without_a_declared_role_header_is_unauthenticated_and_rejected
        """
        payload = fa.advertiser_payload(**_ADVERTISER)

        no_role = api.create_advertiser(payload, NO_ROLE_HEADERS)
        validate_error(no_role, ApiErrorId.UNAUTHENTICATED, 401)

        no_user = api.create_advertiser(payload, _ROLE_WITHOUT_USER_HEADERS)
        validate_error(no_user, ApiErrorId.UNAUTHENTICATED, 401)

        undeclared_role = api.create_advertiser(payload, UNDECLARED_ROLE_HEADERS)
        validate_error(undeclared_role, ApiErrorId.UNAUTHENTICATED, 401)

        unauthenticated_read = api.list_advertisers(NO_AUTH_HEADERS)
        validate_error(unauthenticated_read, ApiErrorId.UNAUTHENTICATED, 401)

        for response in (no_role, no_user, undeclared_role, unauthenticated_read):
            assert response.json()["response_type"] == "error", (
                "a rejected request must answer with the error envelope"
            )

        rows, meta = validate_paginated(api.list_advertisers(CONTROLLER_HEADERS))
        assert meta["total_count"] == 0, (
            "a request that never reached a handler must not have created a row"
        )
        assert rows == []


class TestPlacementIsReservedToTheAgencyBuyer:
    """Placement is an AgencyBuyer exclusive, even for the owning seller."""

    def test_the_seller_behind_every_unit_still_cannot_place_the_buy(self, api):
        """A SellerRep owning the only avail behind the buy is refused placement
        with 403 ERR_ROLE_NOT_PERMITTED, the buy stays PENDING_PLACEMENT with no
        placing user recorded, the campaign and its allocation are untouched, and
        the buyer's identical call then places the buy.

        PRD: "Where the Authorized Role(s) column reads "Any authenticated role",
        all six roles of §2.1 may call the endpoint, subject to the ownership
        checks described there; where it names specific roles, any other role is
        refused with `ERR_ROLE_NOT_PERMITTED`."

        Design: Corner/rbac/a_seller_rep_cannot_place_a_buy_reserved_to_the_agency_buyer
        """
        world = _covered_buy(api)
        campaign_version = world["campaign_version"]
        assert campaign_version == 4, (
            "creation, the allocation, submission and approval are four mutations"
        )
        placement = fa.place_payload(campaign_version)

        refused = api.place_buy(
            world["buy_id"], placement, make_seller_rep_headers(world["seller_id"])
        )
        validate_error(refused, ApiErrorId.ROLE_NOT_PERMITTED, 403)

        buy = validate_success(api.get_buy(world["buy_id"], BUYER_HEADERS))
        assert_buy_axes(buy, buy_status=BuyStatus.PENDING_PLACEMENT.value)
        assert buy["placed_by_user_id"] is None, (
            "a refused placement records no placing user"
        )

        campaign = validate_success(
            api.get_campaign(world["campaign_id"], BUYER_HEADERS)
        )
        assert campaign["version"] == 4, "the refusal mutated nothing"
        assert_cents(campaign, "committed_gross_cents", 0)
        assert_cents(campaign, "uncommitted_budget_cents", 10_000_000)
        assert_campaign_axes(campaign, plan_posture=PlanPosture.WITHIN_PLAN.value)

        allocation = validate_success(
            api.get_channel_allocation(world["allocation_id"], BUYER_HEADERS)
        )
        assert_cents(allocation, "committed_cents", 0)
        assert_allocation_posture(allocation, posture="WITHIN_PLAN")

        placed = validate_success(
            api.place_buy(world["buy_id"], placement, BUYER_HEADERS)
        )
        assert_buy_axes(placed, buy_status=BuyStatus.PLACED.value)
        assert placed["placed_by_user_id"] == BUYER_USER_ID


class TestAvailPublicationIsOwnedBySeller:
    """Ownership sits below role authorisation and reports its own identifier."""

    def test_a_second_sellers_rep_cannot_publish_the_avail_it_does_not_own(self, api):
        """A SellerRep carrying the right role but another seller's identifier is
        refused with 403 ERR_NOT_RESOURCE_OWNER, the avail stays DRAFT at version
        1, and the owning seller's identical call then publishes it at version 2.

        PRD: "In practice that means a `SellerRep` may only file or publish an
        avail whose `seller_id` is its own, only counter a negotiation whose
        `seller_id` is its own, only settle the airing of a unit whose avail
        belongs to it, only file a delivery report for a buy whose seller is it,
        and only offer a make-good on a buy whose seller is it."

        Design: Corner/rbac/a_foreign_seller_rep_cannot_publish_another_sellers_avail
        """
        world = _two_sellers_with_a_draft_avail(api)

        refused = api.publish_inventory_forecast(
            world["forecast_id"], None, make_seller_rep_headers(world["stranger_id"])
        )
        validate_error(refused, ApiErrorId.NOT_RESOURCE_OWNER, 403)

        avail = validate_success(
            api.get_inventory_forecast(world["forecast_id"], BUYER_HEADERS)
        )
        assert avail["status"] == ForecastStatus.DRAFT.value
        assert avail["version"] == 1, "a refused publication mutates nothing"

        published = validate_success(
            api.publish_inventory_forecast(
                world["forecast_id"], None, make_seller_rep_headers(world["owner_id"])
            )
        )
        assert published["status"] == ForecastStatus.PUBLISHED.value
        assert published["version"] == 2

    def test_a_non_seller_role_is_refused_one_rung_higher_than_the_owner_check(
        self, api
    ):
        """An AgencyController publishing the same DRAFT avail is refused with
        ERR_ROLE_NOT_PERMITTED, a different identifier from the ownership failure
        an entity-backed role earns.

        PRD: "Where the Authorized Role(s) column reads "Any authenticated role",
        all six roles of §2.1 may call the endpoint, subject to the ownership
        checks described there; where it names specific roles, any other role is
        refused with `ERR_ROLE_NOT_PERMITTED`."

        Design: Corner/rbac/a_foreign_seller_rep_cannot_publish_another_sellers_avail
        """
        world = _two_sellers_with_a_draft_avail(api)

        refused = api.publish_inventory_forecast(
            world["forecast_id"], None, CONTROLLER_HEADERS
        )
        validate_error(refused, ApiErrorId.ROLE_NOT_PERMITTED, 403)
        assert (
            ApiErrorId.ROLE_NOT_PERMITTED != ApiErrorId.NOT_RESOURCE_OWNER
        ), "the role failure and the ownership failure are distinct identifiers"

        avail = validate_success(
            api.get_inventory_forecast(world["forecast_id"], BUYER_HEADERS)
        )
        assert avail["status"] == ForecastStatus.DRAFT.value
        assert avail["version"] == 1


class TestReconciliationIsSharedByPlannerAndController:
    """The one mutation two agency roles share, and the role it excludes."""

    def test_both_the_planner_and_the_controller_can_open_a_run(self, api):
        """Planner and controller each create their own run against the same
        campaign, both completing with no data because no delivery was accepted,
        and the campaign then lists exactly two distinct runs.

        PRD: "A **Reconciliation Run** does that, and either an `AgencyPlanner`
        or an `AgencyController` may start one."

        Design: Corner/rbac/reconciliation_is_shared_by_planner_and_controller_and_closed_to_the_buyer
        """
        world = _advertiser_and_campaign(api)
        payload = fa.aggregate_dedup_payload(
            world["campaign_id"], aggregate_duplication_pct=10.00
        )

        planner_run = validate_success(
            api.create_reconciliation_run(payload, PLANNER_HEADERS), 201
        )
        assert planner_run["status"] == RunStatus.COMPLETED_NO_DATA.value
        assert planner_run["dedup_method"] == DedupMethod.AGGREGATE_DEDUP.value

        controller_run = validate_success(
            api.create_reconciliation_run(payload, CONTROLLER_HEADERS), 201
        )
        assert controller_run["status"] == RunStatus.COMPLETED_NO_DATA.value

        rows, meta = validate_paginated(
            api.list_reconciliation_runs(
                PLANNER_HEADERS, params={"campaign_id": world["campaign_id"]}
            )
        )
        assert meta["total_count"] == 2, "each role's run is its own immutable row"
        assert {row["id"] for row in rows} == {planner_run["id"], controller_run["id"]}
        assert planner_run["id"] != controller_run["id"]

    def test_the_agency_buyer_is_closed_out_of_reconciliation(self, api):
        """The AgencyBuyer, who may steward delivery and accept reports, is
        refused the run with 403 ERR_ROLE_NOT_PERMITTED and leaves no row behind.

        PRD: "Where the Authorized Role(s) column reads "Any authenticated role",
        all six roles of §2.1 may call the endpoint, subject to the ownership
        checks described there; where it names specific roles, any other role is
        refused with `ERR_ROLE_NOT_PERMITTED`."

        Design: Corner/rbac/reconciliation_is_shared_by_planner_and_controller_and_closed_to_the_buyer
        """
        world = _advertiser_and_campaign(api)
        payload = fa.aggregate_dedup_payload(
            world["campaign_id"], aggregate_duplication_pct=10.00
        )

        refused = api.create_reconciliation_run(payload, BUYER_HEADERS)
        validate_error(refused, ApiErrorId.ROLE_NOT_PERMITTED, 403)

        _, meta = validate_paginated(
            api.list_reconciliation_runs(
                PLANNER_HEADERS, params={"campaign_id": world["campaign_id"]}
            )
        )
        assert meta["total_count"] == 0


def _vendor_filed_report(api):
    """A placed buy carrying one SUBMITTED report filed by the measurement vendor.

    The clock is moved past the reported period first, because no one reports the
    future; the filing response itself is kept so the test can prove the shared
    operation is open to the vendor.
    """
    world = _placed_buy(api)
    fx.move_clock(api, "2027-01-01T00:00:00Z")
    world["filing"] = api.create_delivery_report(
        fa.delivery_report_payload(
            world["buy_id"],
            1_000_000,
            990_000,
            period_start="2026-11-01T00:00:00Z",
            period_end="2026-12-31T23:59:59Z",
            measurement_basis=MeasurementBasis.LINEAR_C3.value,
        ),
        MEASUREMENT_HEADERS,
    )
    return world


class TestFilingDeliveryDoesNotCarryAcceptance:
    """Filing is shared with the vendor; blessing the numbers is not."""

    def test_the_measurement_vendor_cannot_accept_the_report_it_filed(self, api):
        """The vendor's filing is accepted at 201 but its acceptance is refused
        with 403 ERR_ROLE_NOT_PERMITTED, leaving the report SUBMITTED, the buy
        PLACED and NOT_STARTED with a final index of 0.0000, until the buyer
        accepts it.

        PRD: "Accepting a report is an `AgencyBuyer` action and moves it
        `SUBMITTED → ACCEPTED`."

        Design: Corner/rbac/a_measurement_provider_cannot_accept_the_delivery_it_filed
        """
        world = _vendor_filed_report(api)
        report = validate_success(world["filing"], 201)
        assert report["status"] == ReportStatus.SUBMITTED.value

        refused = api.accept_delivery_report(report["id"], None, MEASUREMENT_HEADERS)
        validate_error(refused, ApiErrorId.ROLE_NOT_PERMITTED, 403)

        unchanged = validate_success(
            api.get_delivery_report(report["id"], BUYER_HEADERS)
        )
        assert unchanged["status"] == ReportStatus.SUBMITTED.value

        buy = validate_success(api.get_buy(world["buy_id"], BUYER_HEADERS))
        assert_buy_axes(
            buy,
            buy_status=BuyStatus.PLACED.value,
            stewardship_status=StewardshipStatus.NOT_STARTED.value,
        )
        assert_pct4(buy, "final_delivery_index", 0.0000)

        accepted = validate_success(
            api.accept_delivery_report(report["id"], None, BUYER_HEADERS)
        )
        assert accepted["status"] == ReportStatus.ACCEPTED.value


def _client_paid_invoice(api):
    """A buy placed by ``buyer-01``, aired, invoiced and paid in full.

    The single line bills 2,200,000 cents of net media and 154,000 cents of
    commission at the top tier, so the client settles 2,354,000 cents and the
    seller payable the remittance draws on is 2,200,000 cents.
    """
    world = _placed_buy(api)
    fx.move_clock(api, "2026-12-01T00:00:00Z")
    fx.settle_aired(api, world["unit_id"], world["seller_id"], 1_000_000)
    fx.fund_campaign(api, world["campaign_id"], world["advertiser_id"], 2_354_000)
    invoice = fx.draft_invoice(
        api,
        world["buy_id"],
        billing_period_start="2026-11-01T00:00:00Z",
        billing_period_end="2026-11-30T23:59:59Z",
    )
    fx.issue_invoice(api, invoice["id"])
    fx.pay_invoice(api, invoice["id"], world["advertiser_id"], 2_354_000)
    world["invoice_id"] = invoice["id"]
    return world


class TestRemittanceIsSegregatedFromPlacement:
    """The remittance check compares identities, not roles."""

    def test_a_controller_acting_as_the_placing_buyer_cannot_remit(self, api):
        """A controller whose acting identifier equals the buy's
        placed_by_user_id is refused with 403 ERR_SEGREGATION_OF_DUTIES even
        though the amount sits inside the 2,200,000-cent sequential-liability
        cap, while a second controller releases the identical amount and is
        recorded as the approver.

        PRD: "The remitting `X-User-ID` must differ from the buy's
        `placed_by_user_id`, or the release is refused with
        `ERR_SEGREGATION_OF_DUTIES` — the buyer who committed the money may not
        be the controller who pays it out."

        Design: Corner/rbac/a_controller_reusing_the_placing_buyers_user_id_cannot_remit_to_the_seller
        """
        world = _client_paid_invoice(api)
        release = fa.remittance_payload(2_200_000)

        refused = api.remit_seller(
            world["invoice_id"], release, make_controller_headers(BUYER_USER_ID)
        )
        validate_error(refused, ApiErrorId.SEGREGATION_OF_DUTIES, 403)

        invoice = validate_success(
            api.get_invoice(world["invoice_id"], CONTROLLER_HEADERS)
        )
        assert_cents(invoice, "seller_remitted_cents", 0)
        assert_invoice_axes(
            invoice, seller_status=InvoiceSellerStatus.UNREMITTED.value
        )
        assert invoice.get("approver_user_id") is None, (
            "a refused release records no approver"
        )
        assert_cents(invoice, "max_remittable_cents", 2_200_000)

        buy = validate_success(api.get_buy(world["buy_id"], BUYER_HEADERS))
        assert_buy_axes(buy, settlement_status=SettlementStatus.CLIENT_PAID.value)

        remitted = validate_success(
            api.remit_seller(world["invoice_id"], release, CONTROLLER_ALT_HEADERS)
        )
        assert_cents(remitted, "seller_remitted_cents", 2_200_000)
        assert_invoice_axes(
            remitted, seller_status=InvoiceSellerStatus.REMITTED.value
        )
        assert remitted["approver_user_id"] == CONTROLLER_ALT_USER_ID

        settled = validate_success(api.get_buy(world["buy_id"], BUYER_HEADERS))
        assert_buy_axes(
            settled,
            buy_status=BuyStatus.PLACED.value,
            settlement_status=SettlementStatus.REMITTED.value,
        )
