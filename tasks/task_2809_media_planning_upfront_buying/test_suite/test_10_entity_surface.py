"""Corner coverage of the entity surface: creation envelopes, server-minted
system fields, declared defaults, computed allocation figures, append-only
records, listing pagination, required-field and closed-enum rejections, and the
per-entity not-found identifiers.
"""

from test_helpers import (
    BUYER_HEADERS,
    BUYER_USER_ID,
    CLOCK_STARTUP_INPUT,
    CONTROLLER_HEADERS,
    PLANNER_HEADERS,
    ApiErrorId,
    assert_append_only_shape,
    assert_cents,
    assert_common_fields,
    assert_envelope_meta,
    assert_impressions,
    assert_instant_equals,
    assert_instant_field,
    assert_pagination_meta,
    assert_pct2,
    assert_pct4,
    factories as fa,
    get_success_data,
    is_valid_uuid,
    make_advertiser_client_headers,
    make_seller_rep_headers,
    validate_error,
    validate_paginated,
    validate_success,
)

#: A syntactically valid identifier that names no row of any collection.
UNKNOWN_ID = "00000000-0000-0000-0000-000000000000"

#: The Q4 linear objective every allocation and rights scenario is planned on.
Q4_CAMPAIGN = {
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

#: The whole-plan prime linear share of that budget.
PRIME_LINEAR_ALLOCATION = {
    "channel": "LINEAR_TV",
    "allocation_pct": 100.00,
    "planned_cpm_cents": 2000,
    "planned_market": "UPFRONT",
    "primary_daypart": "PRIME",
}

#: The seller's prime linear avail sitting inside that flight.
HARBOR_NIGHTLY_AVAIL = {
    "market": "UPFRONT",
    "fiscal_quarter": "2026Q4",
    "daypart": "PRIME",
    "program": "Harbor Nightly",
    "platform": "LINEAR",
    "window_start": "2026-11-01T00:00:00Z",
    "window_end": "2026-12-31T23:59:59Z",
    "total_impressions": 10_000_000,
    "forecast_cpm_cents": 2200,
}


# ==========================================================================
# Setup helpers — each builds its own world through the public endpoints
# ==========================================================================
def _register_cascadia(api):
    """The BEVERAGE brand every planning scenario is bought for."""
    return get_success_data(
        api.create_advertiser(
            fa.advertiser_payload(
                name="Cascadia Beverage",
                category_code="BEVERAGE",
                credit_limit_cents=500_000_000,
                payment_terms_days=30,
                sequential_liability_enabled=True,
            ),
            CONTROLLER_HEADERS,
        )
    )


def _register_harbor(api):
    """The seller carrying linear, connected television and digital."""
    return get_success_data(
        api.create_seller(
            fa.seller_payload(
                name="Harbor Broadcasting",
                platform_types=["LINEAR", "CTV", "DIGITAL"],
                make_good_capacity_impressions=50_000_000,
            ),
            CONTROLLER_HEADERS,
        )
    )


def _open_q4_campaign(api, advertiser_id, **overrides):
    """Open the Q4 linear campaign for the named advertiser."""
    spec = dict(Q4_CAMPAIGN)
    spec.update(overrides)
    return get_success_data(
        api.create_campaign(fa.campaign_payload(advertiser_id, **spec), PLANNER_HEADERS)
    )


def _add_prime_allocation(api, campaign_id):
    """Allocate the whole budget to prime linear television bought upfront."""
    return get_success_data(
        api.create_channel_allocation(
            fa.channel_allocation_payload(campaign_id, **PRIME_LINEAR_ALLOCATION),
            PLANNER_HEADERS,
        )
    )


def _campaign_with_allocation(api):
    """An advertiser, a DRAFT campaign and its single prime linear allocation."""
    advertiser = _register_cascadia(api)
    campaign = _open_q4_campaign(api, advertiser["id"])
    allocation = _add_prime_allocation(api, campaign["id"])
    return {
        "advertiser_id": advertiser["id"],
        "campaign_id": campaign["id"],
        "allocation_id": allocation["id"],
    }


def _allocated_plan(api):
    """The campaign, the allocation just created on it and the campaign re-read."""
    advertiser = _register_cascadia(api)
    campaign = _open_q4_campaign(api, advertiser["id"])
    response = api.create_channel_allocation(
        fa.channel_allocation_payload(campaign["id"], **PRIME_LINEAR_ALLOCATION),
        PLANNER_HEADERS,
    )
    allocation = validate_success(response, 201)
    return {
        "advertiser_id": advertiser["id"],
        "campaign_id": campaign["id"],
        "allocation": allocation,
        "campaign": get_success_data(api.get_campaign(campaign["id"], PLANNER_HEADERS)),
    }


def _defaults_world(api):
    """Every optional input omitted on an advertiser, an avail and a negotiation."""
    advertiser = get_success_data(
        api.create_advertiser(
            fa.advertiser_payload(
                name="Default Terms Co",
                category_code="TELECOM",
                credit_limit_cents=100_000_000,
            ),
            CONTROLLER_HEADERS,
        )
    )
    seller = _register_harbor(api)
    seller_headers = make_seller_rep_headers(seller["id"])
    campaign = _open_q4_campaign(api, advertiser["id"])
    allocation = _add_prime_allocation(api, campaign["id"])
    forecast = get_success_data(
        api.create_inventory_forecast(
            fa.inventory_forecast_payload(seller["id"], **HARBOR_NIGHTLY_AVAIL),
            seller_headers,
        )
    )
    return {
        "advertiser_id": advertiser["id"],
        "seller_id": seller["id"],
        "campaign_id": campaign["id"],
        "allocation_id": allocation["id"],
        "forecast_id": forecast["id"],
    }


def _open_default_negotiation(api, world):
    """Open the negotiation with guarantee, remedy and option ceiling omitted."""
    return api.create_negotiation(
        fa.negotiation_payload(
            world["campaign_id"],
            world["seller_id"],
            world["allocation_id"],
            market="UPFRONT",
            channel="LINEAR_TV",
            requested_impressions=1_000_000,
            opening_cpm_cents=2000,
        ),
        BUYER_HEADERS,
    )


def _accepted_buy_world(api):
    """The base fixture through acceptance: a PENDING_PLACEMENT buy of 1,000,000
    impressions at 2200 cents, with the clock still at its startup instant.
    """
    advertiser = _register_cascadia(api)
    seller = _register_harbor(api)
    seller_headers = make_seller_rep_headers(seller["id"])
    campaign = _open_q4_campaign(api, advertiser["id"])
    allocation = _add_prime_allocation(api, campaign["id"])
    get_success_data(api.submit_plan(campaign["id"], None, PLANNER_HEADERS))
    get_success_data(
        api.approve_plan(
            campaign["id"], None, make_advertiser_client_headers(advertiser["id"])
        )
    )
    forecast = get_success_data(
        api.create_inventory_forecast(
            fa.inventory_forecast_payload(
                seller["id"], exclusivity_mode="SHARED", **HARBOR_NIGHTLY_AVAIL
            ),
            seller_headers,
        )
    )
    get_success_data(
        api.publish_inventory_forecast(forecast["id"], None, seller_headers)
    )
    negotiation = get_success_data(
        api.create_negotiation(
            fa.negotiation_payload(
                campaign["id"],
                seller["id"],
                allocation["id"],
                market="UPFRONT",
                channel="LINEAR_TV",
                requested_impressions=1_000_000,
                opening_cpm_cents=2000,
                guarantee_pct=100,
                make_good_provision="MAKE_GOOD_UNITS",
                option_pct_ceiling=25,
            ),
            BUYER_HEADERS,
        )
    )
    get_success_data(
        api.counter_negotiation(
            negotiation["id"],
            fa.counter_payload(
                negotiation["version"],
                counter_cpm_cents=2200,
                counter_impressions=1_000_000,
            ),
            seller_headers,
        )
    )
    buy = get_success_data(api.accept_negotiation(negotiation["id"], None, BUYER_HEADERS))
    return {
        "advertiser_id": advertiser["id"],
        "seller_id": seller["id"],
        "campaign_id": campaign["id"],
        "allocation_id": allocation["id"],
        "forecast_id": forecast["id"],
        "negotiation_id": negotiation["id"],
        "buy_id": buy["id"],
        "buy": buy,
    }


# ==========================================================================
# Advertiser creation
# ==========================================================================
class TestAdvertiserCreationEnvelope:
    """The registration response is a §2.2 envelope around the stored brand."""

    def test_registration_answers_201_with_the_created_advertiser_in_data(self, api):
        """Registering Northwind Retail answers 201 with an object envelope whose
        meta carries a prefixed request id and whose data echoes the declared terms.

        PRD: "Endpoints that bring a new resource into existence answer with HTTP
        201 and the created resource in `data`; every other successful call answers
        with HTTP 200 and the affected resource in `data`."

        Design: Corner/entities/advertiser_creation_returns_envelope_and_declared_fields
        """
        response = api.create_advertiser(
            fa.advertiser_payload(
                name="Northwind Retail",
                category_code="RETAIL",
                credit_limit_cents=250_000_000,
                payment_terms_days=45,
                sequential_liability_enabled=False,
            ),
            CONTROLLER_HEADERS,
        )
        advertiser = validate_success(response, 201)
        body = response.json()
        assert body["response_type"] == "object"
        assert_envelope_meta(body)
        assert advertiser["name"] == "Northwind Retail"
        assert advertiser["category_code"] == "RETAIL"
        assert_cents(advertiser, "credit_limit_cents", 250_000_000)
        assert advertiser["payment_terms_days"] == 45
        assert advertiser["sequential_liability_enabled"] is False

    def test_a_fresh_advertiser_starts_active_with_no_receivable(self, api):
        """The credit posture, the lateness counter and the receivable are minted by
        the server at their opening values rather than echoed from the request.

        PRD: "A freshly registered advertiser starts with `credit_status` set to
        `ACTIVE`, `late_payment_count` at 0 and `outstanding_receivable_cents` at 0."

        Design: Corner/entities/advertiser_creation_returns_envelope_and_declared_fields
        """
        advertiser = validate_success(
            api.create_advertiser(
                fa.advertiser_payload(
                    name="Northwind Retail",
                    category_code="RETAIL",
                    credit_limit_cents=250_000_000,
                    payment_terms_days=45,
                    sequential_liability_enabled=False,
                ),
                CONTROLLER_HEADERS,
            ),
            201,
        )
        assert advertiser["credit_status"] == "ACTIVE"
        assert advertiser["late_payment_count"] == 0
        assert_cents(advertiser, "outstanding_receivable_cents", 0)
        assert_common_fields(advertiser, 1)
        assert is_valid_uuid(advertiser["id"])
        assert_instant_equals(
            advertiser["updated_at"], advertiser["created_at"], "updated_at"
        )


# ==========================================================================
# Campaign retrieval
# ==========================================================================
class TestCampaignRetrieval:
    """A fresh campaign reads back its objective and its initialised rollups."""

    def test_read_returns_the_stored_objective_and_the_opening_axes(self, api):
        """The campaign read carries back every objective input and opens on DRAFT,
        UNFUNDED and WITHIN_PLAN with nothing funded.

        PRD: "A newly created campaign starts at `plan_status` `DRAFT`,
        `funding_status` `UNFUNDED` and `plan_posture` `WITHIN_PLAN`, with
        `funded_cents` at 0."

        Design: Corner/entities/campaign_retrieval_returns_the_stored_plan_objective
        """
        advertiser = _register_cascadia(api)
        created = _open_q4_campaign(api, advertiser["id"])
        campaign = validate_success(api.get_campaign(created["id"], PLANNER_HEADERS))
        assert campaign["advertiser_id"] == advertiser["id"]
        assert campaign["target_demo"] == "A25-54"
        assert campaign["universe_thousands"] == 120_000
        assert_pct2(campaign, "reach_goal_pct", 60.0)
        assert_pct2(campaign, "frequency_goal", 4.0)
        assert_cents(campaign, "total_budget_cents", 10_000_000)
        assert campaign["fiscal_quarter"] == "2026Q4"
        assert campaign["plan_status"] == "DRAFT"
        assert campaign["funding_status"] == "UNFUNDED"
        assert campaign["plan_posture"] == "WITHIN_PLAN"
        assert_cents(campaign, "funded_cents", 0)
        assert campaign["version"] == 1

    def test_read_returns_initialised_rollups_not_nulls(self, api):
        """With no allocations the two headroom figures both read the whole budget
        while the allocated, committed and projected rollups read zero.

        PRD: "Both of its headroom figures — `unallocated_budget_cents` and
        `uncommitted_budget_cents` — are initialised to the full
        `total_budget_cents`, since nothing has been allocated and nothing has been
        committed."

        Design: Corner/entities/campaign_retrieval_returns_the_stored_plan_objective
        """
        advertiser = _register_cascadia(api)
        created = _open_q4_campaign(api, advertiser["id"])
        campaign = validate_success(api.get_campaign(created["id"], PLANNER_HEADERS))
        assert_cents(campaign, "unallocated_budget_cents", 10_000_000)
        assert_cents(campaign, "uncommitted_budget_cents", 10_000_000)
        assert_cents(campaign, "allocated_budget_cents", 0)
        assert_cents(campaign, "committed_gross_cents", 0)
        assert_impressions(campaign, "planned_impressions_total", 0)
        assert_pct2(campaign, "planned_grp_total", 0.00)


# ==========================================================================
# Campaign listing
# ==========================================================================
class TestCampaignListingPagination:
    """total_count reports the matched population, not the returned page."""

    def test_two_pages_split_three_campaigns_and_flip_has_more(self, api):
        """With three campaigns stored, limit=2 returns two rows with total_count 3
        and has_more true while offset=2 returns the last row with has_more false.

        PRD: "List responses carry `limit`, `offset`, `total_count` and `has_more`
        inside `meta`, where `total_count` is the number of records matching the
        request's filters before the window is applied and `has_more` is true exactly
        when records remain beyond the returned window."

        Design: Corner/entities/campaign_listing_paginates_with_total_count_and_has_more
        """
        advertiser = _register_cascadia(api)
        first = _open_q4_campaign(api, advertiser["id"])
        second = _open_q4_campaign(
            api,
            advertiser["id"],
            name="Q1 Scatter Base",
            target_demo="A18-49",
            universe_thousands=100_000,
            reach_goal_pct=40.0,
            frequency_goal=3.0,
            total_budget_cents=20_000_000,
            flight_start="2027-01-01T00:00:00Z",
            flight_end="2027-03-31T23:59:59Z",
            fiscal_quarter="2027Q1",
        )
        third = _open_q4_campaign(
            api,
            advertiser["id"],
            name="Q2 Digital Base",
            target_demo="A18-49",
            universe_thousands=100_000,
            reach_goal_pct=35.0,
            frequency_goal=3.0,
            total_budget_cents=30_000_000,
            flight_start="2027-04-01T00:00:00Z",
            flight_end="2027-06-30T23:59:59Z",
            fiscal_quarter="2027Q2",
        )

        page_one = api.list_campaigns(PLANNER_HEADERS, params={"limit": 2, "offset": 0})
        rows_one, meta_one = validate_paginated(page_one)
        assert page_one.json()["response_type"] == "array"
        assert len(rows_one) == 2
        assert_pagination_meta(
            meta_one,
            expected_total=3,
            expected_limit=2,
            expected_offset=0,
            expected_has_more=True,
        )

        page_two = api.list_campaigns(PLANNER_HEADERS, params={"limit": 2, "offset": 2})
        rows_two, meta_two = validate_paginated(page_two)
        assert len(rows_two) == 1
        assert_pagination_meta(
            meta_two,
            expected_total=3,
            expected_limit=2,
            expected_offset=2,
            expected_has_more=False,
        )

        seen = [row["id"] for row in rows_one] + [row["id"] for row in rows_two]
        assert len(seen) == len(set(seen))
        assert set(seen) == {first["id"], second["id"], third["id"]}


# ==========================================================================
# Not found and rejected writes
# ==========================================================================
class TestBuyReadWithUnknownId:
    """The buy collection answers its own not-found identifier."""

    def test_unknown_buy_id_returns_buy_not_found(self, api):
        """A well-formed identifier that resolves to no buy answers 404
        ERR_BUY_NOT_FOUND rather than a generic 404 or an empty 200.

        PRD: "When a path carries an identifier, that identifier is resolved before
        any body field is examined, and the rejection names the entity whose
        identifier failed: `ERR_ADVERTISER_NOT_FOUND`, `ERR_CAMPAIGN_NOT_FOUND`,
        `ERR_ALLOCATION_NOT_FOUND`, `ERR_SELLER_NOT_FOUND`,
        `ERR_FORECAST_NOT_FOUND`, `ERR_NEGOTIATION_NOT_FOUND`,
        `ERR_BUY_NOT_FOUND`, `ERR_BUY_UNIT_NOT_FOUND`, `ERR_REPORT_NOT_FOUND`,
        `ERR_MAKE_GOOD_NOT_FOUND`, `ERR_RIGHTS_EXERCISE_NOT_FOUND`,
        `ERR_RECONCILIATION_RUN_NOT_FOUND` or `ERR_INVOICE_NOT_FOUND`, each carrying
        HTTP 404."

        Design: Corner/entities/buy_read_with_an_unknown_id_returns_buy_not_found
        """
        response = api.get_buy(UNKNOWN_ID, BUYER_HEADERS)
        validate_error(response, ApiErrorId.BUY_NOT_FOUND, 404)
        body = response.json()
        assert body["response_type"] == "error"
        assert isinstance(body["data"]["message"], str)
        assert body["data"]["message"] != ""


class TestCampaignCreationWithoutTargetDemo:
    """A missing required input is a body-shape rejection, not a stored null."""

    def test_omitting_target_demo_is_rejected_and_stores_nothing(self, api):
        """A campaign create carrying every field but `target_demo` answers 400
        ERR_INVALID_REQUEST and leaves the campaign collection empty.

        PRD: "Applies to every write endpoint: every required input must be present,
        every enum value must fall inside its declared value set, monetary and
        impression amounts must be integers greater than zero, percentages must lie
        between 0.00 and 100.00 inclusive, a window's start must fall strictly before
        its end, and timestamps must be ISO 8601 UTC instants."

        Design: Corner/entities/campaign_creation_without_target_demo_is_rejected
        """
        advertiser = _register_cascadia(api)
        payload = fa.campaign_payload(advertiser["id"], **Q4_CAMPAIGN)
        payload["name"] = "No Demo"
        del payload["target_demo"]

        validate_error(
            api.create_campaign(payload, PLANNER_HEADERS),
            ApiErrorId.INVALID_REQUEST,
            400,
        )
        _, meta = validate_paginated(api.list_campaigns(PLANNER_HEADERS))
        assert meta["total_count"] == 0


class TestForecastWithUndeclaredPlatform:
    """`platform` is a closed enum, so SATELLITE never reaches storage."""

    def test_satellite_platform_is_rejected_before_any_avail_is_written(self, api):
        """Filing an avail on SATELLITE answers 400 ERR_INVALID_REQUEST and the
        seller's forecast list stays empty.

        PRD: "A value outside the declared set is a body-shape violation and is
        rejected with `ERR_INVALID_REQUEST`."

        Design: Corner/entities/forecast_creation_with_an_undeclared_platform_is_rejected
        """
        seller = _register_harbor(api)
        seller_headers = make_seller_rep_headers(seller["id"])
        payload = fa.inventory_forecast_payload(
            seller["id"], **{**HARBOR_NIGHTLY_AVAIL, "platform": "SATELLITE"}
        )

        validate_error(
            api.create_inventory_forecast(payload, seller_headers),
            ApiErrorId.INVALID_REQUEST,
            400,
        )
        _, meta = validate_paginated(
            api.list_inventory_forecasts(
                seller_headers, params={"seller_id": seller["id"]}
            )
        )
        assert meta["total_count"] == 0


class TestNegotiationWithUnknownSeller:
    """Body foreign keys resolve in the endpoint's declared input order."""

    def test_a_good_campaign_with_a_bad_seller_returns_seller_not_found(self, api):
        """A negotiation naming a resolvable campaign but an unresolvable seller
        answers 404 ERR_SELLER_NOT_FOUND and stores nothing.

        PRD: "A campaign create that names a non-existent advertiser therefore fails
        with `ERR_ADVERTISER_NOT_FOUND`, and a negotiation create naming a good
        campaign but a bad seller fails with `ERR_SELLER_NOT_FOUND`."

        Design: Corner/entities/negotiation_creation_with_an_unknown_seller_returns_seller_not_found
        """
        world = _campaign_with_allocation(api)
        payload = fa.negotiation_payload(
            world["campaign_id"],
            UNKNOWN_ID,
            world["allocation_id"],
            market="UPFRONT",
            channel="LINEAR_TV",
            requested_impressions=1_000_000,
            opening_cpm_cents=2000,
        )

        validate_error(
            api.create_negotiation(payload, BUYER_HEADERS),
            ApiErrorId.SELLER_NOT_FOUND,
            404,
        )
        _, meta = validate_paginated(
            api.list_negotiations(
                BUYER_HEADERS, params={"campaign_id": world["campaign_id"]}
            )
        )
        assert meta["total_count"] == 0


# ==========================================================================
# Declared defaults on optional inputs
# ==========================================================================
class TestDeclaredDefaults:
    """Omitting an optional input yields its declared default, never null or 0."""

    def test_advertiser_payment_terms_default_to_thirty_days(self, api):
        """An advertiser registered without payment terms carries 30 net days.

        PRD: "`payment_terms_days` is the net-days figure added to the logical clock
        at invoice issue to derive the invoice's due date; it must be an integer from
        0 through 120 inclusive and defaults to 30 when omitted."

        Design: Corner/entities/defaults_apply_when_optional_inputs_are_omitted
        """
        advertiser = validate_success(
            api.create_advertiser(
                fa.advertiser_payload(
                    name="Default Terms Co",
                    category_code="TELECOM",
                    credit_limit_cents=100_000_000,
                ),
                CONTROLLER_HEADERS,
            ),
            201,
        )
        assert advertiser["payment_terms_days"] == 30

    def test_advertiser_sequential_liability_defaults_to_enabled(self, api):
        """An advertiser registered without the flag is bound by sequential liability.

        PRD: "`sequential_liability_enabled` is a boolean that defaults to true, and
        when it is true the agency's remittance to a seller is capped by the pro-rata
        share of client cash actually received, as described in §3.9."

        Design: Corner/entities/defaults_apply_when_optional_inputs_are_omitted
        """
        advertiser = validate_success(
            api.create_advertiser(
                fa.advertiser_payload(
                    name="Default Terms Co",
                    category_code="TELECOM",
                    credit_limit_cents=100_000_000,
                ),
                CONTROLLER_HEADERS,
            ),
            201,
        )
        assert advertiser["sequential_liability_enabled"] is True

    def test_avail_exclusivity_defaults_to_shared(self, api):
        """An avail filed without an exclusivity mode is SHARED.

        PRD: "Optionally it declares an `exclusivity_mode`, which defaults to
        `SHARED`."

        Design: Corner/entities/defaults_apply_when_optional_inputs_are_omitted
        """
        seller = _register_harbor(api)
        forecast = validate_success(
            api.create_inventory_forecast(
                fa.inventory_forecast_payload(seller["id"], **HARBOR_NIGHTLY_AVAIL),
                make_seller_rep_headers(seller["id"]),
            ),
            201,
        )
        assert forecast["exclusivity_mode"] == "SHARED"

    def test_negotiation_guarantee_defaults_to_a_hundred_percent(self, api):
        """A negotiation opened without a guarantee share guarantees the whole
        audience on the campaign's target demo.

        PRD: "`guarantee_pct` is the share of impressions the seller guarantees on
        the campaign's target demo and defaults to 100 — a value greater than 0 and
        at most 100 with at most two decimal places."

        Design: Corner/entities/defaults_apply_when_optional_inputs_are_omitted
        """
        world = _defaults_world(api)
        negotiation = validate_success(_open_default_negotiation(api, world), 201)
        assert_pct2(negotiation, "guarantee_pct", 100)

    def test_negotiation_remedy_defaults_to_make_good_units(self, api):
        """A negotiation opened without a remedy carries the replacement-inventory
        provision rather than a null one.

        PRD: "`make_good_provision` is the remedy the parties agree for
        under-delivery and defaults to `MAKE_GOOD_UNITS`."

        Design: Corner/entities/defaults_apply_when_optional_inputs_are_omitted
        """
        world = _defaults_world(api)
        negotiation = validate_success(_open_default_negotiation(api, world), 201)
        assert negotiation["make_good_provision"] == "MAKE_GOOD_UNITS"

    def test_negotiation_option_ceiling_defaults_to_twenty_five_percent(self, api):
        """A negotiation opened without an option ceiling admits a quarter of the
        guarantee in later option roll-ups.

        PRD: "`option_pct_ceiling` is the maximum percentage of guaranteed
        impressions the agency may later add by exercising its option right; it
        defaults to 25, must be at least 0 and at most 100, and carries at most two
        decimal places."

        Design: Corner/entities/defaults_apply_when_optional_inputs_are_omitted
        """
        world = _defaults_world(api)
        negotiation = validate_success(_open_default_negotiation(api, world), 201)
        assert_pct2(negotiation, "option_pct_ceiling", 25)


# ==========================================================================
# Seller system fields
# ==========================================================================
class TestSellerSystemFields:
    """Nothing the seller endpoint accepts sets the exposure or audit fields."""

    def test_a_new_seller_starts_with_no_make_good_exposure(self, api):
        """Registration echoes the declared platforms and capacity while both
        make-good exposure rollups open at zero.

        PRD: "A new seller's exposure counters both start at 0."

        Design: Corner/entities/seller_system_fields_are_server_minted
        """
        seller = validate_success(
            api.create_seller(
                fa.seller_payload(
                    name="Harbor Broadcasting",
                    platform_types=["LINEAR", "CTV", "DIGITAL"],
                    make_good_capacity_impressions=50_000_000,
                ),
                CONTROLLER_HEADERS,
            ),
            201,
        )
        assert seller["name"] == "Harbor Broadcasting"
        assert seller["platform_types"] == ["LINEAR", "CTV", "DIGITAL"]
        assert_impressions(seller, "make_good_capacity_impressions", 50_000_000)
        assert_impressions(seller, "open_make_good_impressions", 0)
        assert_impressions(seller, "scheduled_make_good_impressions", 0)

    def test_seller_identity_and_version_are_server_minted(self, api):
        """The seller is minted with a bare UUID, a version of 1 and an update
        instant equal to its creation instant.

        PRD: "Most resources additionally carry `updated_at`, refreshed on every
        mutation of the resource, and `version`, an integer that starts at 1 on
        creation and increments by exactly 1 on every mutation of that resource."

        Design: Corner/entities/seller_system_fields_are_server_minted
        """
        response = api.create_seller(
            fa.seller_payload(
                name="Harbor Broadcasting",
                platform_types=["LINEAR", "CTV", "DIGITAL"],
                make_good_capacity_impressions=50_000_000,
            ),
            CONTROLLER_HEADERS,
        )
        seller = validate_success(response, 201)
        assert response.json()["response_type"] == "object"
        assert_common_fields(seller, 1)
        assert is_valid_uuid(seller["id"])
        assert_instant_equals(seller["updated_at"], seller["created_at"], "updated_at")


# ==========================================================================
# Channel allocation computed fields
# ==========================================================================
class TestChannelAllocationComputedFields:
    """A single 100% prime linear allocation of a 10,000,000 cent budget at a
    2000 cent planned CPM: every derived figure follows from the budget, the
    market and daypart multipliers and the band.
    """

    def test_allocated_cents_floors_the_budget_share(self, api):
        """The whole budget is allocated because the allocation takes 100% of it.

        PRD: "The allocation's own `allocated_cents` is the campaign's
        `total_budget_cents` multiplied by its `allocation_pct`, divided by 100, and
        then floored to a whole number of cents — never rounded up, because the
        agency will not allocate a cent it does not have."

        Design: Corner/entities/channel_allocation_computed_fields_derive_from_budget_and_band
        """
        world = _allocated_plan(api)
        assert_cents(world["allocation"], "allocated_cents", 10_000_000)

    def test_effective_cpm_applies_the_market_and_daypart_multipliers(self, api):
        """Prime bought upfront lifts the 2000 cent planned CPM to 2400 cents, which
        sits inside the band and is therefore left alone by both clamps.

        PRD: "The stored `effective_planned_cpm_cents` is the raw product rounded
        half up to a whole cent, raised to the band floor if it sits below it, then
        lowered to the band ceiling if it sits above it — that is, the ceiling has
        the final word when the two clamps disagree."

        Design: Corner/entities/channel_allocation_computed_fields_derive_from_budget_and_band
        """
        world = _allocated_plan(api)
        assert_cents(world["allocation"], "effective_planned_cpm_cents", 2400)

    def test_planned_impressions_floor_the_budget_divided_by_the_effective_cpm(
        self, api
    ):
        """10,000,000 cents at 2400 cents per thousand buys 4,166,666 impressions,
        the two-thirds remainder being dropped rather than rounded.

        PRD: "The allocation's `planned_impressions` is its `allocated_cents` divided
        by `effective_planned_cpm_cents`, multiplied by 1000, and floored to a whole
        impression."

        Design: Corner/entities/channel_allocation_computed_fields_derive_from_budget_and_band
        """
        world = _allocated_plan(api)
        assert_impressions(world["allocation"], "planned_impressions", 4_166_666)

    def test_planned_grp_expresses_those_impressions_against_the_universe(self, api):
        """4,166,666 impressions against a 120,000 thousand universe is 3.47 gross
        rating points once rounded half up to two places.

        PRD: "Its `planned_grp` expresses that in gross rating points: it is
        `planned_impressions` divided by the campaign's universe expressed in people
        — that is, `universe_thousands` multiplied by 1000 — then multiplied by 100
        and rounded half up to two decimal places."

        Design: Corner/entities/channel_allocation_computed_fields_derive_from_budget_and_band
        """
        world = _allocated_plan(api)
        assert_pct2(world["allocation"], "planned_grp", 3.47)

    def test_planned_frequency_divides_the_grp_by_the_reach_goal(self, api):
        """3.47 rating points against a 60% reach goal is a planned frequency of
        0.06 exposures.

        PRD: "Its `planned_frequency` is `planned_grp` divided by the campaign's
        `reach_goal_pct`, rounded half up to two decimal places."

        Design: Corner/entities/channel_allocation_computed_fields_derive_from_budget_and_band
        """
        world = _allocated_plan(api)
        assert_pct2(world["allocation"], "planned_frequency", 0.06)

    def test_the_campaign_rollups_sum_the_draft_allocation(self, api):
        """The campaign's audience rollups pick the DRAFT allocation up unchanged,
        and the mutation advances the campaign to version 2.

        PRD: "At campaign level, `planned_impressions_total` is the sum of
        `planned_impressions` over allocations whose `status` is `DRAFT` or `LOCKED`,
        and `planned_grp_total` is the sum of `planned_grp` over those same
        allocations rounded half up to two decimal places."

        Design: Corner/entities/channel_allocation_computed_fields_derive_from_budget_and_band
        """
        world = _allocated_plan(api)
        campaign = world["campaign"]
        assert_impressions(campaign, "planned_impressions_total", 4_166_666)
        assert_pct2(campaign, "planned_grp_total", 3.47)
        assert_cents(campaign, "allocated_budget_cents", 10_000_000)
        assert_cents(campaign, "unallocated_budget_cents", 0)
        assert_common_fields(campaign, 2)

    def test_a_brand_new_allocation_opens_draft_and_within_plan(self, api):
        """Nothing is committed or delivered on a freshly created allocation, so it
        opens in DRAFT within plan with its committed figure at zero.

        PRD: "A new allocation is created with `status` `DRAFT` and `posture`
        `WITHIN_PLAN`."

        Design: Corner/entities/channel_allocation_computed_fields_derive_from_budget_and_band
        """
        world = _allocated_plan(api)
        allocation = world["allocation"]
        assert allocation["status"] == "DRAFT"
        assert allocation["posture"] == "WITHIN_PLAN"
        assert_cents(allocation, "committed_cents", 0)
        assert_common_fields(allocation, 1)


def _exercised_option_roll(api):
    """Roll a tenth of the guarantee onto the accepted buy and read it back."""
    world = _accepted_buy_world(api)
    response = api.create_rights_exercise(
        fa.option_roll_payload(world["buy_id"], requested_pct=10.00), BUYER_HEADERS
    )
    world["response"] = response
    world["exercise"] = validate_success(response, 201)
    return world


# ==========================================================================
# Rights exercise immutability
# ==========================================================================
class TestRightsExerciseIsAppendOnly:
    """A 10% option roll on a 1,000,000 impression buy at 2200 cents: the record
    itself is a narrow append-only row, and every mutable consequence lands on
    the buy.
    """

    def test_the_record_carries_neither_version_nor_update_instant(self, api):
        """The stored exercise exposes an identifier and a creation instant only, and
        reading it back returns exactly what the create answered.

        PRD: "Both `updated_at` and `version` are absent from those two resource
        types entirely."

        Design: Corner/entities/rights_exercise_row_is_immutable_and_carries_no_version
        """
        world = _exercised_option_roll(api)
        exercise = world["exercise"]
        assert world["response"].json()["response_type"] == "object"
        assert_append_only_shape(exercise)
        assert is_valid_uuid(exercise["id"])
        assert "version" not in exercise
        assert "updated_at" not in exercise
        reread = validate_success(
            api.get_rights_exercise(exercise["id"], CONTROLLER_HEADERS)
        )
        assert reread == exercise

    def test_the_roll_magnitude_floors_a_tenth_of_the_guarantee(self, api):
        """Ten percent of the 1,000,000 impression guarantee standing before the
        exercise is a delta of 100,000 impressions.

        PRD: "Its magnitude is the buy's `guaranteed_impressions` immediately before
        the exercise multiplied by `requested_pct` and divided by 100, floored to a
        whole impression as §2.5 requires."

        Design: Corner/entities/rights_exercise_row_is_immutable_and_carries_no_version
        """
        world = _exercised_option_roll(api)
        assert_impressions(world["exercise"], "delta_impressions", 100_000)

    def test_the_applied_ceiling_is_copied_from_the_buys_option_ceiling(self, api):
        """The record stamps the 25 percent option ceiling the negotiation agreed.

        PRD: "For an `OPTION_ROLL` the ceiling is simply the buy's own
        `option_pct_ceiling`, copied from the negotiation."

        Design: Corner/entities/rights_exercise_row_is_immutable_and_carries_no_version
        """
        world = _exercised_option_roll(api)
        assert_pct2(world["exercise"], "applied_ceiling_pct", 25)

    def test_an_option_roll_cancels_no_lines(self, api):
        """No buy unit is released by a roll-up, so the cancelled line count is zero.

        PRD: "`cancelled_unit_count` records how many lines were cancelled — it is
        always 0 for an `OPTION_ROLL`."

        Design: Corner/entities/rights_exercise_row_is_immutable_and_carries_no_version
        """
        world = _exercised_option_roll(api)
        assert world["exercise"]["cancelled_unit_count"] == 0

    def test_the_buy_cost_stack_is_recomputed_on_the_new_guarantee(self, api):
        """The buy now guarantees 1,100,000 impressions at 2200 cents, and the whole
        stack is rebuilt on the 2,420,000 cent net at the top commission tier.

        PRD: "The buy's `guaranteed_impressions` is then adjusted by that signed
        amount and its entire cost stack is recomputed from scratch with the
        commission tier re-selected on the new pre-commission net:
        `net_media_cost_cents`, `commission_rate`, `agency_commission_cents` and
        `gross_cost_cents` are all rewritten by the three-tier arithmetic of §3.5."

        Design: Corner/entities/rights_exercise_row_is_immutable_and_carries_no_version
        """
        world = _exercised_option_roll(api)
        buy = validate_success(api.get_buy(world["buy_id"], BUYER_HEADERS))
        assert_impressions(buy, "guaranteed_impressions", 1_100_000)
        assert_cents(buy, "net_media_cost_cents", 2_420_000)
        assert_pct4(buy, "commission_rate", 0.0700)
        assert_cents(buy, "agency_commission_cents", 169_400)
        assert_cents(buy, "gross_cost_cents", 2_589_400)

    def test_the_recorded_gross_delta_is_the_signed_difference(self, api):
        """The gross moves from 2,354,000 to 2,589,400 cents, so the record keeps a
        delta of 235,400 cents.

        PRD: "The exercise records `delta_gross_cents`, the signed difference between
        the buy's `gross_cost_cents` after the recomputation and its value before it
        — a large option roll can therefore cross a tier boundary downward and
        produce a proportionally smaller commission increase than the impression
        increase would suggest."

        Design: Corner/entities/rights_exercise_row_is_immutable_and_carries_no_version
        """
        world = _exercised_option_roll(api)
        assert_cents(world["buy"], "gross_cost_cents", 2_354_000)
        assert_cents(world["exercise"], "delta_gross_cents", 235_400)

    def test_the_record_stamps_the_clock_and_the_acting_buyer(self, api):
        """The exercise is stamped at the startup instant of the logical clock and
        attributed to the buyer who exercised the right.

        PRD: "The record also stamps `exercised_at` from the logical clock and
        `exercised_by_user_id` from the acting `X-User-ID`, and it is never modified
        afterwards; as noted in §2.4, a rights exercise carries neither `updated_at`
        nor `version`."

        Design: Corner/entities/rights_exercise_row_is_immutable_and_carries_no_version
        """
        world = _exercised_option_roll(api)
        assert_instant_field(world["exercise"], "exercised_at", CLOCK_STARTUP_INPUT)
        assert world["exercise"]["exercised_by_user_id"] == BUYER_USER_ID

    def test_the_buy_accumulates_the_exercised_option_share(self, api):
        """The buy's option cumulative moves from 0 to the 10.00 percent just
        exercised, which is what a later roll is tested against.

        PRD: "In either case the test is cumulative: `requested_pct` plus the
        matching cumulative already exercised must be no greater than the ceiling,
        where the matching cumulative is `option_pct_cumulative` (the sum of
        `requested_pct` over this buy's `OPTION_ROLL` exercises) for an option and
        `cancelled_pct_cumulative` (the sum over its `CANCELLATION` exercises) for a
        cancellation."

        Design: Corner/entities/rights_exercise_row_is_immutable_and_carries_no_version
        """
        world = _exercised_option_roll(api)
        buy = validate_success(api.get_buy(world["buy_id"], BUYER_HEADERS))
        assert_pct2(buy, "option_pct_cumulative", 10.00)


def _empty_reconciliation_run(api):
    """Run aggregate dedup over a DRAFT campaign that has no delivery at all."""
    advertiser = _register_cascadia(api)
    campaign = _open_q4_campaign(api, advertiser["id"])
    response = api.create_reconciliation_run(
        fa.aggregate_dedup_payload(campaign["id"], aggregate_duplication_pct=10.00),
        PLANNER_HEADERS,
    )
    return {
        "campaign_id": campaign["id"],
        "response": response,
        "run": validate_success(response, 201),
    }


# ==========================================================================
# Reconciliation run immutability
# ==========================================================================
class TestReconciliationRunIsAppendOnly:
    """A run over a campaign with no buys and no reports is still a stored row."""

    def test_the_run_carries_neither_version_nor_update_instant(self, api):
        """The stored run exposes an identifier and a creation instant only, and
        reading it back returns exactly what the create answered.

        PRD: "Both `updated_at` and `version` are absent from those two resource
        types entirely."

        Design: Corner/entities/reconciliation_run_row_is_immutable_and_carries_no_version
        """
        world = _empty_reconciliation_run(api)
        run = world["run"]
        assert_append_only_shape(run)
        assert is_valid_uuid(run["id"])
        assert "version" not in run
        assert "updated_at" not in run
        reread = validate_success(
            api.get_reconciliation_run(run["id"], CONTROLLER_HEADERS)
        )
        assert reread == run

    def test_a_run_with_no_reports_short_circuits_to_completed_no_data(self, api):
        """With nothing to reconcile the run is stored as COMPLETED_NO_DATA and every
        reach and frequency output reads zero rather than null.

        PRD: "When `included_report_count` is 0 the run short-circuits: its `status`
        is `COMPLETED_NO_DATA`, every reach output — each group entry,
        `gross_reach_pct_total` and `unduplicated_reach_pct` — reads 0.0000, and
        `implied_frequency` reads 0.00."

        Design: Corner/entities/reconciliation_run_row_is_immutable_and_carries_no_version
        """
        run = _empty_reconciliation_run(api)["run"]
        assert run["included_report_count"] == 0
        assert run["status"] == "COMPLETED_NO_DATA"
        assert_pct4(run, "gross_reach_pct_total", 0.0000)
        assert_pct4(run, "unduplicated_reach_pct", 0.0000)
        assert_pct2(run, "implied_frequency", 0.00)
        assert run["group_reach_pct"] == {}

    def test_the_run_stamps_the_logical_clock(self, api):
        """The run is computed at the startup instant of the logical clock.

        PRD: "A run is an immutable record: as noted in §2.4 it carries `id` and
        `created_at` but neither `updated_at` nor `version`, and it stamps
        `computed_at` from the logical clock."

        Design: Corner/entities/reconciliation_run_row_is_immutable_and_carries_no_version
        """
        run = _empty_reconciliation_run(api)["run"]
        assert_instant_field(run, "computed_at", CLOCK_STARTUP_INPUT)
