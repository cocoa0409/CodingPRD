"""Bid preparation: project opening, takeoff capture, pricing and the bid total."""
from datetime import datetime

import pytest

from test_helpers import (
    ApiErrorId,
    LOGICAL_CLOCK_START,
    NON_EXISTENT_PROJECT_ID,
    advance_clock,
    create_project,
    setup_priced_item,
    setup_project_with_reopenable_item,
    validate_error,
    validate_success,
)


def _instant(text):
    """Parse an ISO 8601 instant so two spellings of the same moment compare equal."""
    return datetime.fromisoformat(text.replace("Z", "+00:00"))


class TestProjectOpening:
    def test_project_creation_applies_declared_defaults(self, api, estimator_headers):
        """PRD §3.1: "Three further attributes are optional at creation and take
        documented defaults."
        PRD §3.1: "when the caller omits it the value `UNIT_PRICE` is assumed"
        PRD §3.1: "it defaults to 5.0 when omitted and must be a number between
        0.0 and 10.0 inclusive"
        PRD §3.1: "it defaults to 0.0 when omitted and must be a number between
        0.0 and 100.0 inclusive"
        PRD §3.1: "Opening the record sets the project's bid-window-open instant
        to the current logical clock, stamps the sealed-bid dimension to `DRAFT`,
        and stamps the delivery dimension to `PRE_BID`."

        Design: Corner/entities/project_creation_applies_declared_defaults
        """
        advance_clock(LOGICAL_CLOCK_START)
        response = api.create_project(
            {
                "project_code": "CALTRANS-04-1J5701",
                "owner_agency_name": "Caltrans District 4",
                "bid_deadline_at": "2026-12-01T00:00:00Z",
            },
            estimator_headers,
        )
        project = validate_success(response, 201)

        assert project["contract_type"] == "UNIT_PRICE"
        assert project["retention_rate_pct"] == pytest.approx(5.0)
        assert project["advertised_dbe_goal_pct"] == pytest.approx(0.0)
        assert project["bid_status"] == "DRAFT"
        assert project["project_status"] == "PRE_BID"
        assert project["total_bid_cents"] == 0
        assert _instant(project["bid_window_open_at"]) == _instant(LOGICAL_CLOCK_START)

    def test_project_missing_required_field_returns_invalid_request(
        self, api, estimator_headers
    ):
        """PRD §3.1: "A body that omits a mandatory attribute, that carries an
        unknown attribute, or that puts a value outside the declared set into an
        enumerated attribute such as `contract_type` is rejected with
        `ERR_INVALID_REQUEST` (HTTP 400)."
        PRD §2.5: "The second band is request well-formedness: if the body does
        not parse, a required field is absent, an unknown field is present, or an
        enum-valued field holds a member outside its declared set, the request is
        rejected with `ERR_INVALID_REQUEST` (HTTP 400)."

        Design: Corner/entities/project_missing_required_field_returns_invalid_request
        """
        advance_clock(LOGICAL_CLOCK_START)
        response = api.create_project(
            {
                "project_code": "CALTRANS-04-1J5702",
                "bid_deadline_at": "2026-12-01T00:00:00Z",
            },
            estimator_headers,
        )
        error = validate_error(response, ApiErrorId.ERR_INVALID_REQUEST)
        assert error["error_id"] == "ERR_INVALID_REQUEST"
        assert response.status_code == 400

    def test_project_get_unknown_id_returns_project_not_found(
        self, api, estimator_headers
    ):
        """PRD §2.5: "`ERR_PROJECT_NOT_FOUND` (HTTP 404) when a
        `project_id` path or body value resolves to no `Project`"
        PRD §2.2: "All error API responses (4xx status codes) follow this
        standard envelope format"

        Design: Corner/entities/project_get_unknown_id_returns_project_not_found
        """
        advance_clock(LOGICAL_CLOCK_START)
        response = api.get_project(NON_EXISTENT_PROJECT_ID, estimator_headers)
        validate_error(response, ApiErrorId.ERR_PROJECT_NOT_FOUND)
        assert response.status_code == 404
        body = response.json()
        assert body["response_type"] == "error", "an unknown id must not leak an object"

    def test_error_response_envelope_on_validation_failure(self, api, estimator_headers):
        """PRD §2.2: "The `error_id` is a unique, machine-readable string that
        identifies the specific error."
        PRD §2.2: "The `message` provides a human-readable explanation of what
        went wrong."
        PRD §2.2: "The `meta` object for error responses contains only
        `api_request_id` and `api_request_timestamp`."

        Design: Corner/endpoints/error_response_envelope_on_validation_failure
        """
        advance_clock(LOGICAL_CLOCK_START)
        response = api.create_project({"project_code": "CALTRANS-04-1J5716"}, estimator_headers)
        validate_error(response, ApiErrorId.ERR_INVALID_REQUEST)
        body = response.json()

        assert body["response_type"] == "error"
        assert isinstance(body["data"]["error_id"], str) and body["data"]["error_id"]
        assert isinstance(body["data"]["message"], str) and body["data"]["message"].strip()
        assert set(body["meta"].keys()) == {"api_request_id", "api_request_timestamp"}


class TestTakeoff:
    def test_bid_item_creation_initialises_computed_fields_to_zero(
        self, api, estimator_headers
    ):
        """PRD §3.1: "Each new pay item starts its life in `DRAFT` status, which
        marks it as part of the takeoff but outside the bid total."
        PRD §3.2: "Applying the price moves the item from `DRAFT` to `PRICED`,
        stores the freshly computed balanced unit price"
        PRD §2.12: "A `BidItem` response carries its computed
        `balanced_unit_price_cents`, `measured_quantity`, `variance_pct` and
        `renegotiation_required` flag."
        PRD §3.9: "The variance percentage is the item's committed measured
        quantity minus its `estimated_quantity`, divided by its
        `estimated_quantity`, multiplied by 100, and rounded half up to exactly 2
        decimal places."

        Design: Corner/entities/bid_item_creation_initialises_computed_fields_to_zero
        """
        advance_clock(LOGICAL_CLOCK_START)
        project = create_project(project_code="CALTRANS-04-1J5704")
        response = api.create_bid_item(
            project["id"],
            {
                "item_code": "2025-390203",
                "item_description": "Class 2 aggregate base",
                "unit_of_measure": "TON",
                "estimated_quantity": 1000,
            },
            estimator_headers,
        )
        item = validate_success(response, 201)

        assert item["item_status"] == "DRAFT"
        assert item["measured_quantity"] == pytest.approx(0)
        # Nothing has been measured yet, so the committed measured quantity is
        # zero and the variance against the 1,000-unit estimate is -100.0.
        assert item["variance_pct"] == pytest.approx(-100.0)
        assert item["renegotiation_required"] is True
        assert item["balanced_unit_price_cents"] == 0

    def test_bid_item_invalid_unit_of_measure_returns_invalid_request(
        self, api, estimator_headers
    ):
        """PRD §3.1: "The `unit_of_measure` must be one of `LF`, `CY`, `TON`,
        `EA` or `SY`."
        PRD §2.5: "The second band is request well-formedness: if the body does
        not parse, a required field is absent, an unknown field is present, or an
        enum-valued field holds a member outside its declared set, the request is
        rejected with `ERR_INVALID_REQUEST` (HTTP 400)."

        Design: Corner/entities/bid_item_invalid_unit_of_measure_returns_invalid_request
        """
        advance_clock(LOGICAL_CLOCK_START)
        project = create_project(project_code="CALTRANS-04-1J5703")
        response = api.create_bid_item(
            project["id"],
            {
                "item_code": "2025-390201",
                "item_description": "Tack coat",
                "unit_of_measure": "GALLON",
                "estimated_quantity": 500,
            },
            estimator_headers,
        )
        validate_error(response, ApiErrorId.ERR_INVALID_REQUEST)
        assert response.status_code == 400

    def test_bid_item_create_under_unknown_project_returns_project_not_found(
        self, api, estimator_headers
    ):
        """PRD §2.5: "`ERR_PROJECT_NOT_FOUND` (HTTP 404) when a
        `project_id` path or body value resolves to no `Project`"
        PRD §2.7: "The parent is located first; if it does not exist the request
        stops with the parent's own not-found error"

        Design: Corner/entities/bid_item_create_under_unknown_project_returns_project_not_found
        """
        advance_clock(LOGICAL_CLOCK_START)
        response = api.create_bid_item(
            "00000000-0000-4000-8000-0000000000fe",
            {
                "item_code": "2025-390202",
                "item_description": "Class 2 aggregate base",
                "unit_of_measure": "TON",
                "estimated_quantity": 1000,
            },
            estimator_headers,
        )
        validate_error(response, ApiErrorId.ERR_PROJECT_NOT_FOUND)
        assert response.status_code == 404


class TestPricingFloor:
    def test_unit_price_below_crew_cost_floor_returns_rate_below_cost(
        self, api, estimator_headers
    ):
        """PRD §3.2: "The `balanced_unit_price_cents` is that crew-day cost
        divided by the `daily_productivity_units`, rounded half up exactly once,
        at the per-unit quotient, to a whole cent."
        PRD §3.2: "a price that falls below the item's balanced unit price is
        rejected with `ERR_RATE_BELOW_COST` (HTTP 422), because bidding work below
        the crew-productivity cost is treated as a materially unbalanced bid
        rather than a legitimate commercial choice."
        PRD §3.2: "Pricing is only accepted on an item that is still `DRAFT`."

        Design: Corner/errors/unit_price_below_crew_cost_floor_returns_rate_below_cost
        """
        advance_clock(LOGICAL_CLOCK_START)
        project = create_project(project_code="CALTRANS-04-1J5721")
        item = api.create_bid_item(
            project["id"],
            {
                "item_code": "2025-390218",
                "item_description": "Class 2 aggregate base",
                "unit_of_measure": "TON",
                "estimated_quantity": 1000,
            },
            estimator_headers,
        ).json()["data"]

        response = api.price_bid_item(
            project["id"],
            item["id"],
            {
                "bid_unit_price_cents": 1000,
                "crew_day_labor_cents": 1_200_000,
                "crew_day_equipment_cents": 800_000,
                "daily_productivity_units": 1000,
            },
            estimator_headers,
        )
        validate_error(response, ApiErrorId.ERR_RATE_BELOW_COST)
        assert response.status_code == 422

        after = validate_success(api.get_bid_item(item["id"], estimator_headers))
        assert after["item_status"] == "DRAFT"


class TestBidExtension:
    def test_bid_extension_and_unbalanced_score_are_two_variants_over_one_takeoff(
        self, api, estimator_headers
    ):
        """PRD §3.2: "The project's bid extension is computed in a pinned
        evaluation order. The population of included pay items is every item on
        the project whose `item_status` is not `DRAFT`."
        PRD §3.2: "For each included item, the extended amount is the item's
        `bid_unit_price_cents` multiplied by its `estimated_quantity`, rounded
        half up to a whole cent, and rounding is applied here, at the item level,
        and only here."
        PRD §3.2: "When the ratio is at least 1.20 but strictly less than 2.00
        the item sits in the moderately unbalanced band and takes a multiplier of
        1.005."

        Design: Difficulty/dual_variant_calc/bid_extension_dual_variant_open_vs_sealed
        """
        advance_clock(LOGICAL_CLOCK_START)
        project = create_project(project_code="CALTRANS-04-1J5604")
        setup_priced_item(
            project["id"], bid_unit_price_cents=3000, estimated_quantity=1000
        )
        sealed = validate_success(api.seal_bid(project["id"], estimator_headers))

        assert sealed["bid_status"] == "SEALED"
        assert sealed["total_bid_cents"] == 3_000_000
        assert sealed["unbalanced_bid_score"] == 2_010_000
        assert sealed["unbalanced_bid_score"] != sealed["total_bid_cents"]

    def test_bid_extension_includes_carried_quotes_while_scrutiny_score_does_not(
        self, api, estimator_headers
    ):
        """PRD §3.2: "The subcontract subtotal is the exact integer sum of the
        `quoted_amount_cents` of every subcontractor quote on the project whose
        `quote_status` is `CARRIED` or `SELECTED`."
        PRD §3.2: "when the project has at least one carried or selected quote
        the total includes the subcontract subtotal, and when no quote has been
        carried the total equals the items subtotal alone — meaning the identical
        takeoff yields a strictly smaller total in the second case."
        PRD §3.2: "The `unbalanced_bid_score` is computed over every included pay
        item whose `item_status` is not `DRAFT` and whose
        `balanced_unit_price_cents` is strictly greater than zero."

        Design: Difficulty/dual_variant_calc/bid_extension_dual_variant_open_vs_sealed
        """
        advance_clock(LOGICAL_CLOCK_START)
        project = create_project(project_code="CALTRANS-04-1J5604")
        setup_priced_item(
            project["id"], bid_unit_price_cents=3000, estimated_quantity=1000
        )
        before = validate_success(api.get_project(project["id"], estimator_headers))
        assert before["total_bid_cents"] == 3_000_000

        quote = validate_success(
            api.create_quote(
                {
                    "project_id": project["id"],
                    "trade_code": "SWPPP",
                    "contact_name": "Dana Reyes",
                    "quoted_amount_cents": 18_000_000,
                    "quote_window_start": "2026-11-01T00:00:00Z",
                    "quote_window_end": "2026-12-01T00:00:00Z",
                    "unicap_registered": True,
                    "good_faith_effort_basis": "SOLICITED_DBE",
                },
                estimator_headers,
            ),
            201,
        )
        validate_success(api.carry_quote(quote["id"], estimator_headers))
        sealed = validate_success(api.seal_bid(project["id"], estimator_headers))

        assert sealed["total_bid_cents"] == 21_000_000
        assert sealed["unbalanced_bid_score"] == 2_010_000, (
            "the scrutiny score is scoped to pay items, not to the subcontract subtotal"
        )

    def test_bid_extension_excludes_draft_items(self, api, estimator_headers):
        """PRD §3.2: "The population of included pay items is every item on the
        project whose `item_status` is not `DRAFT`."
        PRD §3.2: "The items subtotal is the exact integer sum of those per-item
        extended amounts."

        Design: Corner/calculations/bid_extension_excludes_draft_items
        """
        ctx = setup_project_with_reopenable_item()
        assert ctx["draft_item"]["item_status"] == "DRAFT"
        assert ctx["draft_item"]["bid_unit_price_cents"] == 9000
        assert ctx["project"]["total_bid_cents"] == 2_000_000

    def test_carried_quote_changes_bid_total_and_dbe_credit(self, api, estimator_headers):
        """PRD §3.3: "The denominator is the exact sum of the `quoted_amount_cents`
        of every quote on the project whose `quote_status` is `CARRIED` or
        `SELECTED`, regardless of registration."
        PRD §3.3: "The project's `dbe_participation_pct` is the numerator divided
        by the denominator, multiplied by 100, rounded half up to exactly 2
        decimal places."
        PRD §3.2: "The project's `total_bid_cents` is the items subtotal plus the
        subcontract subtotal."

        Design: Corner/calculations/carried_quote_changes_bid_total_and_dbe_credit
        """
        advance_clock(LOGICAL_CLOCK_START)
        project = create_project(
            project_code="CALTRANS-04-1J5711", advertised_dbe_goal_pct=10.0
        )
        setup_priced_item(
            project["id"], bid_unit_price_cents=2000, estimated_quantity=1000
        )
        quote = validate_success(
            api.create_quote(
                {
                    "project_id": project["id"],
                    "trade_code": "SWPPP",
                    "contact_name": "Dana Reyes",
                    "quoted_amount_cents": 18_000_000,
                    "quote_window_start": "2026-11-01T00:00:00Z",
                    "quote_window_end": "2026-12-01T00:00:00Z",
                    "unicap_registered": True,
                    "good_faith_effort_basis": "SOLICITED_DBE",
                },
                estimator_headers,
            ),
            201,
        )
        carried = validate_success(api.carry_quote(quote["id"], estimator_headers))
        assert carried["quote_status"] == "CARRIED"
        assert carried["dbe_credit_cents"] == 18_000_000

        refreshed = validate_success(api.get_project(project["id"], estimator_headers))
        assert refreshed["total_bid_cents"] == 20_000_000
        assert refreshed["dbe_participation_pct"] == pytest.approx(100.0)


class TestProjectSummary:
    def test_project_summary_read_reconciles_with_stored_project_fields(
        self, api, estimator_headers
    ):
        """PRD §2.12: "Reads that recompute a roll-up before answering refresh
        those computed figures on the returned representation as well"
        PRD §3.2: "When the ratio is at least 0.80 but strictly less than 1.20
        the item sits in the at-cost band and also takes a multiplier of 1.00."
        PRD §3.3: "When the denominator is zero — a project with no carried or
        selected quotes at all — the participation percentage is exactly 0 rather
        than undefined or null."

        Design: Corner/endpoints/project_summary_read_reconciles_with_stored_project_fields
        """
        advance_clock(LOGICAL_CLOCK_START)
        project = create_project(project_code="CALTRANS-04-1J5717")
        setup_priced_item(
            project["id"], bid_unit_price_cents=2000, estimated_quantity=1000
        )
        summary = validate_success(
            api.get_project_summary(project["id"], estimator_headers)
        )
        assert summary["total_bid_cents"] == 2_000_000
        assert summary["unbalanced_bid_score"] == 2_000_000
        assert summary["dbe_participation_pct"] == pytest.approx(0)
        assert summary["retention_balance_cents"] == 0


class TestSuretyRegistry:
    def test_surety_creation_initialises_capacity_split(self, api, platform_admin_headers):
        """PRD §3.6: "Registration initialises the surety's consumed capacity to
        zero and its available capacity to the full aggregate capacity, and
        starts the firm in `ACTIVE` status."
        PRD §2.11: "Because registration initialises the consumed amount to zero
        and the available amount to the aggregate capacity, the sum of the two
        figures always equals the aggregate capacity."

        Design: Corner/entities/surety_creation_initialises_capacity_split
        """
        advance_clock(LOGICAL_CLOCK_START)
        response = api.create_surety(
            {
                "surety_name": "Cascade Indemnity",
                "aggregate_capacity_cents": 250_000_000,
                "single_job_limit_cents": 200_000_000,
            },
            platform_admin_headers,
        )
        surety = validate_success(response, 201)

        assert surety["capacity_consumed_cents"] == 0
        assert surety["available_capacity_cents"] == 250_000_000
        assert surety["surety_status"] == "ACTIVE"
        assert (
            surety["capacity_consumed_cents"] + surety["available_capacity_cents"]
            == surety["aggregate_capacity_cents"]
        )
