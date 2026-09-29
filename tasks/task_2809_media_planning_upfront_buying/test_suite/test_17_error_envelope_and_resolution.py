"""Error-surface coverage for the Media Planning & Upfront Buying API.

The file pins the per-entity not-found family standing behind every collection
read, the order in which a create resolves the foreign keys carried in its body,
and the single error envelope that each rejection category must serialise.
"""

from test_helpers import (
    BUYER_HEADERS,
    CONTROLLER_HEADERS,
    NON_EXISTENT_UUID,
    NOT_FOUND_BY_COLLECTION,
    PLANNER_HEADERS,
    ApiErrorId,
    assert_envelope_meta,
    factories as fa,
    get_success_data,
    make_seller_rep_headers,
    validate_error,
    validate_paginated,
)


def _read_every_collection_with_an_unknown_id(api):
    """Read all thirteen collections at the same well-formed but unknown id."""
    return {
        collection: api.get_path(
            f"/{collection}/{NON_EXISTENT_UUID}", CONTROLLER_HEADERS
        )
        for collection in NOT_FOUND_BY_COLLECTION
    }


class TestEveryCollectionAnswersWithItsOwnNotFound:
    """The not-found family is per entity, never a single generic identifier."""

    def test_each_collection_read_names_the_entity_whose_id_failed(self, api):
        """Reading each of the thirteen collections at one unknown identifier
        answers 404 with that collection's own not-found identifier.

        PRD: "When a path carries an identifier, that identifier is resolved
        before any body field is examined, and the rejection names the entity
        whose identifier failed: `ERR_ADVERTISER_NOT_FOUND`,
        `ERR_CAMPAIGN_NOT_FOUND`, `ERR_ALLOCATION_NOT_FOUND`,
        `ERR_SELLER_NOT_FOUND`, `ERR_FORECAST_NOT_FOUND`,
        `ERR_NEGOTIATION_NOT_FOUND`, `ERR_BUY_NOT_FOUND`,
        `ERR_BUY_UNIT_NOT_FOUND`, `ERR_REPORT_NOT_FOUND`,
        `ERR_MAKE_GOOD_NOT_FOUND`, `ERR_RIGHTS_EXERCISE_NOT_FOUND`,
        `ERR_RECONCILIATION_RUN_NOT_FOUND` or `ERR_INVOICE_NOT_FOUND`, each
        carrying HTTP 404."

        Design: Corner/errors/every_unknown_path_id_returns_its_own_entity_not_found_error
        """
        responses = _read_every_collection_with_an_unknown_id(api)

        assert len(responses) == 13, "the design sweeps thirteen collections"
        for collection, response in responses.items():
            validate_error(response, NOT_FOUND_BY_COLLECTION[collection], 404)

    def test_the_thirteen_not_found_identifiers_are_pairwise_distinct(self, api):
        """The same unknown identifier read against thirteen collections yields
        thirteen different error identifiers rather than one collapsed family.

        PRD: "When a path carries an identifier, that identifier is resolved
        before any body field is examined, and the rejection names the entity
        whose identifier failed: `ERR_ADVERTISER_NOT_FOUND`,
        `ERR_CAMPAIGN_NOT_FOUND`, `ERR_ALLOCATION_NOT_FOUND`,
        `ERR_SELLER_NOT_FOUND`, `ERR_FORECAST_NOT_FOUND`,
        `ERR_NEGOTIATION_NOT_FOUND`, `ERR_BUY_NOT_FOUND`,
        `ERR_BUY_UNIT_NOT_FOUND`, `ERR_REPORT_NOT_FOUND`,
        `ERR_MAKE_GOOD_NOT_FOUND`, `ERR_RIGHTS_EXERCISE_NOT_FOUND`,
        `ERR_RECONCILIATION_RUN_NOT_FOUND` or `ERR_INVOICE_NOT_FOUND`, each
        carrying HTTP 404."

        Design: Corner/errors/every_unknown_path_id_returns_its_own_entity_not_found_error
        """
        responses = _read_every_collection_with_an_unknown_id(api)

        observed = []
        for collection, response in responses.items():
            assert response.status_code == 404, (
                f"the {collection} read must answer 404, "
                f"got {response.status_code}"
            )
            body = response.json()
            assert body["response_type"] == "error", (
                f"the {collection} read must answer response_type 'error', "
                f"got {body['response_type']!r}"
            )
            observed.append(body["data"]["error_id"])

        assert len(observed) == 13, "thirteen reads produce thirteen identifiers"
        assert len(set(observed)) == 13, (
            f"the thirteen not-found identifiers must be pairwise distinct, got "
            f"{sorted(observed)}"
        )
        assert set(observed) == set(NOT_FOUND_BY_COLLECTION.values()), (
            "each collection must answer with its own catalogued identifier"
        )


class TestBodyForeignKeysResolveInDeclaredOrder:
    """A create with several bad references reports the first declared field."""

    def test_negotiation_create_with_three_unknown_references_reports_the_campaign(
        self, api
    ):
        """Opening a negotiation whose campaign, seller and allocation are all
        unknown reports the campaign — the first declared body field — at 404,
        with a single-identifier payload and no negotiation row created.

        PRD: "Foreign keys supplied in a request body are resolved next, in the
        order the body fields are declared for that operation, and they draw from
        the same per-entity family of not-found errors."

        Design: Corner/errors/unknown_body_foreign_keys_are_resolved_in_declared_input_order_and_not_found
        """
        response = api.create_negotiation(
            fa.negotiation_payload(
                NON_EXISTENT_UUID, NON_EXISTENT_UUID, NON_EXISTENT_UUID
            ),
            BUYER_HEADERS,
        )

        validate_error(response, ApiErrorId.CAMPAIGN_NOT_FOUND, 404)
        body = response.json()
        assert set(body["data"]) == {"error_id", "message"}, (
            f"an error payload carries exactly error_id and message, got "
            f"{sorted(body['data'])}"
        )

        _, meta = validate_paginated(api.list_negotiations(CONTROLLER_HEADERS))
        assert meta["total_count"] == 0, (
            f"a rejected create leaves no negotiation behind, got "
            f"{meta['total_count']}"
        )

    def test_campaign_create_with_an_unknown_advertiser_reports_the_advertiser(
        self, api
    ):
        """Opening a campaign against an unknown advertiser reports
        ERR_ADVERTISER_NOT_FOUND at 404 and creates no campaign.

        PRD: "A campaign create that names a non-existent advertiser therefore
        fails with `ERR_ADVERTISER_NOT_FOUND`, and a negotiation create naming a
        good campaign but a bad seller fails with `ERR_SELLER_NOT_FOUND`."

        Design: Corner/errors/unknown_body_foreign_keys_are_resolved_in_declared_input_order_and_not_found
        """
        response = api.create_campaign(
            fa.campaign_payload(NON_EXISTENT_UUID), PLANNER_HEADERS
        )

        validate_error(response, ApiErrorId.ADVERTISER_NOT_FOUND, 404)
        body = response.json()
        assert set(body["data"]) == {"error_id", "message"}, (
            f"an error payload carries exactly error_id and message, got "
            f"{sorted(body['data'])}"
        )

        _, meta = validate_paginated(api.list_campaigns(CONTROLLER_HEADERS))
        assert meta["total_count"] == 0, (
            f"a rejected create leaves no campaign behind, got "
            f"{meta['total_count']}"
        )


def _four_rejections(api):
    """Stage one rejection per rule category — shape, existence, state, constraint.

    The world is an advertiser, a seller, a campaign carrying a single hundred
    percent linear allocation, and a published avail.  The four returned
    responses are the request-shape rejection, the existence rejection, the
    state rejection and the business-constraint rejection, in that order.
    """
    advertiser = get_success_data(
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
    seller = get_success_data(
        api.create_seller(
            fa.seller_payload(
                name="Harbor Broadcasting",
                platform_types=["LINEAR", "CTV", "DIGITAL"],
                make_good_capacity_impressions=50_000_000,
            ),
            CONTROLLER_HEADERS,
        )
    )
    campaign = get_success_data(
        api.create_campaign(
            fa.campaign_payload(
                advertiser["id"],
                name="Q4 Linear Base",
                target_demo="A25-54",
                universe_thousands=120_000,
                reach_goal_pct=60.00,
                frequency_goal=4.00,
                total_budget_cents=10_000_000,
                flight_start="2026-11-01T00:00:00Z",
                flight_end="2026-12-31T23:59:59Z",
                fiscal_quarter="2026Q4",
            ),
            PLANNER_HEADERS,
        )
    )
    get_success_data(
        api.create_channel_allocation(
            fa.channel_allocation_payload(
                campaign["id"],
                channel="LINEAR_TV",
                allocation_pct=100.00,
                planned_cpm_cents=2000,
                planned_market="UPFRONT",
                primary_daypart="PRIME",
            ),
            PLANNER_HEADERS,
        )
    )
    seller_headers = make_seller_rep_headers(seller["id"])
    avail = get_success_data(
        api.create_inventory_forecast(
            fa.inventory_forecast_payload(
                seller["id"],
                market="UPFRONT",
                fiscal_quarter="2026Q4",
                daypart="PRIME",
                program="Harbor Nightly",
                platform="LINEAR",
                window_start="2026-11-01T00:00:00Z",
                window_end="2026-12-31T23:59:59Z",
                total_impressions=10_000_000,
                forecast_cpm_cents=2200,
                exclusivity_mode="SHARED",
            ),
            seller_headers,
        )
    )
    get_success_data(api.publish_inventory_forecast(avail["id"], None, seller_headers))

    shape = api.create_advertiser(
        fa.advertiser_payload(credit_limit_cents=-5), CONTROLLER_HEADERS
    )
    existence = api.get_invoice(NON_EXISTENT_UUID, CONTROLLER_HEADERS)
    state = api.publish_inventory_forecast(avail["id"], None, seller_headers)
    constraint = api.create_channel_allocation(
        fa.channel_allocation_payload(
            campaign["id"],
            channel="CTV",
            allocation_pct=0.01,
            planned_cpm_cents=2000,
            planned_market="UPFRONT",
            primary_daypart="PRIME",
        ),
        PLANNER_HEADERS,
    )
    return [shape, existence, state, constraint]


class TestOneEnvelopeForEveryRejectionCategory:
    """Shape, existence, state and constraint rejections serialise alike."""

    def test_the_four_categories_answer_their_catalogued_status_and_identifier(
        self, api
    ):
        """A negative credit limit, an unknown invoice, a second publication and a
        hundred-and-one percent allocation split answer 400, 404, 409 and 422 with
        ERR_INVALID_REQUEST, ERR_INVOICE_NOT_FOUND,
        ERR_FORECAST_NOT_IN_EXPECTED_STATE and ERR_ALLOCATION_PCT_SUM_INVALID.

        PRD: "Every rejection returns the error envelope of §2.2 with the
        `error_id` set to one of the identifiers below and the HTTP status shown
        beside it."

        Design: Corner/errors/the_error_envelope_is_identical_whichever_rule_rejects_the_request
        """
        responses = _four_rejections(api)

        assert [response.status_code for response in responses] == [400, 404, 409, 422]

        expected = [
            (ApiErrorId.INVALID_REQUEST, 400),
            (ApiErrorId.INVOICE_NOT_FOUND, 404),
            (ApiErrorId.FORECAST_NOT_IN_EXPECTED_STATE, 409),
            (ApiErrorId.ALLOCATION_PCT_SUM_INVALID, 422),
        ]
        for response, (error_id, status) in zip(responses, expected):
            validate_error(response, error_id, status)

    def test_all_four_rejections_carry_the_identical_error_envelope(self, api):
        """Each of the four rejections answers response_type "error", a request id
        and request timestamp in meta, and a data object holding exactly the two
        keys error_id and message.

        PRD: "The `meta` object for error responses contains only
        `api_request_id` and `api_request_timestamp`."

        Design: Corner/errors/the_error_envelope_is_identical_whichever_rule_rejects_the_request
        """
        responses = _four_rejections(api)

        assert len(responses) == 4, "the design stages four rule categories"
        for response in responses:
            body = response.json()
            assert body["response_type"] == "error", (
                f"a {response.status_code} rejection must answer response_type "
                f"'error', got {body['response_type']!r}"
            )
            assert_envelope_meta(body)
            meta = body["meta"]
            assert meta["api_request_id"], (
                f"a {response.status_code} rejection must carry a non-empty "
                f"meta.api_request_id"
            )
            assert meta["api_request_timestamp"], (
                f"a {response.status_code} rejection must carry a non-empty "
                f"meta.api_request_timestamp"
            )
            assert set(body["data"]) == {"error_id", "message"}, (
                f"a {response.status_code} rejection must carry exactly error_id "
                f"and message, got {sorted(body['data'])}"
            )
            assert isinstance(body["data"]["error_id"], str)
            assert body["data"]["message"].strip(), (
                f"a {response.status_code} rejection must carry a human-readable "
                f"message"
            )
