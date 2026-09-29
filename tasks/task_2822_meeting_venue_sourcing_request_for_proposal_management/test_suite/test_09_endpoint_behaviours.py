"""Endpoint behaviours of the Meeting Venue Sourcing & RFP Management API.

Each test drives one documented endpoint through the state its rule needs and
checks the response the PRD specifies for that call.
"""

import pytest

from test_helpers import (
    CLOCK_SOURCING_WINDOW,
    PLANNER_HEADERS,
    PROGRAM_ADMIN_HEADERS,
    ApiErrorId,
    api_client,
    assert_fields_equal,
    assert_integer,
    assert_iso_instant,
    assert_money,
    assert_money_field,
    assert_nulls,
    assert_pagination_meta,
    assert_variance_pct,
    validate_error,
    validate_paginated,
    validate_success,
)
from test_helpers import assertions as domain_assert  # noqa: F401
from test_helpers import factories, fixtures

# ---------------------------------------------------------------------------
# Module-private state builders
#
# Three bidding venues on one requirement is wider than the shared builders
# reach, so the chain is assembled here from the documented endpoints.
# ---------------------------------------------------------------------------

THIRD_VENUE = {
    "name": "Cordova Palace Hotel",
    "city": "Lisbon",
    "country": "PT",
    "destination_tier": "TIER_1",
    "guest_rooms_total": 300,
    "largest_space_sqft": 13000,
    "preferred_supplier_status": "PREFERRED",
}

# Cascade Bay quotes a GROSS rate over a smaller block with a tighter attrition
# allowance, which is what makes its two cost variants diverge.
CASCADE_BAY_GRID = {
    "room_rate_usd": 275.00,
    "rate_type": "GROSS",
    "commission_pct": 0.10,
    "room_nights_offered": 400,
    "comp_room_ratio": 40,
    "resort_fee_usd_per_night": 0.00,
    "service_charge_pct": 0.22,
    "tax_pct": 0.145,
    "av_estimate_usd": 30000.00,
    "fnb_minimum_usd": 90000.00,
    "concession_credit_usd": 12000.00,
    "attrition_allowance_pct": 0.05,
    "rebooking_credit_pct": 0.40,
}

CORDOVA_GRID = {
    "room_rate_usd": 200.00,
    "rate_type": "NET",
    "commission_pct": 0.00,
    "room_nights_offered": 100,
    "comp_room_ratio": 0,
    "resort_fee_usd_per_night": 0.00,
    "service_charge_pct": 0.20,
    "tax_pct": 0.10,
    "av_estimate_usd": 0.00,
    "fnb_minimum_usd": 0.00,
    "concession_credit_usd": 0.00,
    "attrition_allowance_pct": 0.20,
    "rebooking_credit_pct": 0.50,
}


def build_three_bidder_round():
    """Publish the benchmark, register three venues, lock the requirement and
    issue round 1 so that three invited bids exist."""
    fixtures.set_clock(CLOCK_SOURCING_WINDOW)
    benchmark = fixtures.create_benchmark()
    venue_a = fixtures.create_venue()
    venue_b = fixtures.create_second_venue()
    venue_c = fixtures.create_venue(**THIRD_VENUE)
    event = fixtures.create_event()
    fixtures.lock_event(event["id"])
    entry_a = fixtures.promote_entry(
        fixtures.add_entry(event["id"], venue_a["id"], rank_seq=1)["id"]
    )
    entry_b = fixtures.promote_entry(
        fixtures.add_entry(event["id"], venue_b["id"], rank_seq=2)["id"]
    )
    entry_c = fixtures.promote_entry(
        fixtures.add_entry(event["id"], venue_c["id"], rank_seq=3)["id"]
    )
    rfp = fixtures.issue_rfp(fixtures.create_rfp(event["id"])["id"])
    return {
        "benchmark_id": benchmark["id"],
        "event_id": event["id"],
        "venue_a_id": venue_a["id"],
        "venue_b_id": venue_b["id"],
        "venue_c_id": venue_c["id"],
        "entry_a_id": entry_a["id"],
        "entry_b_id": entry_b["id"],
        "entry_c_id": entry_c["id"],
        "rfp_id": rfp["id"],
        "proposal_a_id": fixtures.find_invited_proposal(rfp["id"], venue_a["id"])["id"],
        "proposal_b_id": fixtures.find_invited_proposal(rfp["id"], venue_b["id"])["id"],
        "proposal_c_id": fixtures.find_invited_proposal(rfp["id"], venue_c["id"])["id"],
    }


@pytest.fixture
def cost_comparison_world():
    """Three invited venues: two live submissions and one that was withdrawn."""
    world = build_three_bidder_round()
    fixtures.submit_bid(world["proposal_a_id"], world["venue_a_id"])
    fixtures.submit_bid(world["proposal_b_id"], world["venue_b_id"], **CASCADE_BAY_GRID)
    fixtures.submit_bid(world["proposal_c_id"], world["venue_c_id"], **CORDOVA_GRID)
    fixtures.withdraw_bid(world["proposal_c_id"], world["venue_c_id"])
    return world


class TestEventCostComparison:
    """GET /sourcing/events/{event_id}/cost-comparison."""

    def test_comparison_covers_the_live_bids_only_in_contracted_total_order(
        self, cost_comparison_world
    ):
        """Alongside the snapshots, the planner can read a side-by-side comparison of the event's live bids.

        The event cost-comparison collection is ordered by contracted-basis total ascending, with ties broken by the bid's `created_at` ascending.

        Design: Corner/endpoints/cost_comparison_recomputes_both_variants_for_live_bids_only
        """
        world = cost_comparison_world
        response = api_client.get_cost_comparison(world["event_id"], PLANNER_HEADERS)
        domain_assert.assert_envelope(response, "array")
        rows, meta = validate_paginated(response)

        assert len(rows) == 2
        assert meta["total_count"] == 2
        assert [row["proposal_id"] for row in rows] == [
            world["proposal_b_id"],
            world["proposal_a_id"],
        ]
        assert world["proposal_c_id"] not in [row["proposal_id"] for row in rows]
        assert_fields_equal(
            rows[0],
            {
                "venue_id": world["venue_b_id"],
                "venue_name": "Cascade Bay Resort",
                "status": "SUBMITTED",
                "compliance_status": "COMPLIANT",
                "within_budget": True,
            },
        )
        assert_fields_equal(
            rows[1],
            {
                "venue_id": world["venue_a_id"],
                "venue_name": "Harborline Grand",
                "status": "SUBMITTED",
                "compliance_status": "COMPLIANT",
                "within_budget": True,
            },
        )

    def test_comparison_reports_both_variants_and_their_delta_for_each_row(
        self, cost_comparison_world
    ):
        """Each comparison row reports the bid's `proposal_id` and `venue_id`, the `venue_name` of the bidding venue, the bid's current `status`, its `total_cost_contracted_usd`, its `total_cost_actualized_usd` — the actualized-basis total for the same bid — the `variant_delta_usd` obtained by subtracting the actualized total from the contracted total, the bid's `benchmark_variance_pct`, its `compliance_status`, and a boolean `within_budget` that is true exactly when the bid's `total_cost_contracted_usd` is at most the event's `budget_ceiling_usd`.

        Design: Corner/endpoints/cost_comparison_recomputes_both_variants_for_live_bids_only
        """
        world = cost_comparison_world
        rows, _ = validate_paginated(
            api_client.get_cost_comparison(world["event_id"], PLANNER_HEADERS)
        )
        by_proposal = {row["proposal_id"]: row for row in rows}

        cascade = by_proposal[world["proposal_b_id"]]
        assert_money_field(cascade, "total_cost_contracted_usd", 290551.07)
        assert_money_field(cascade, "total_cost_actualized_usd", 280706.17)
        assert_money_field(cascade, "variant_delta_usd", 9844.90)
        assert_variance_pct(cascade["benchmark_variance_pct"], -0.0481)

        harborline = by_proposal[world["proposal_a_id"]]
        assert_money_field(harborline, "total_cost_contracted_usd", 447844.84)
        assert_money_field(harborline, "total_cost_actualized_usd", 422797.82)
        assert_money_field(harborline, "variant_delta_usd", 25047.02)
        assert_variance_pct(harborline["benchmark_variance_pct"], -0.0423)

    def test_comparison_is_a_pure_read_that_appends_no_snapshot(
        self, cost_comparison_world
    ):
        """This comparison recomputes both variants of the cost model on the fly and writes no snapshot rows; it is a pure read that leaves the bid's `total_cost_modeled_usd` and `last_evaluation_basis` alone.

        Design: Corner/endpoints/cost_comparison_recomputes_both_variants_for_live_bids_only
        """
        world = cost_comparison_world
        validate_success(
            api_client.get_cost_comparison(world["event_id"], PLANNER_HEADERS), 200
        )

        snapshots, meta = validate_paginated(
            api_client.list_bid_evaluations(world["proposal_a_id"], PLANNER_HEADERS)
        )
        assert snapshots == []
        assert meta["total_count"] == 0
        assert_nulls(
            fixtures.read_proposal(world["proposal_a_id"]),
            ["total_cost_modeled_usd", "last_evaluation_basis"],
        )


@pytest.fixture
def candidate_world():
    """A locked requirement carrying one un-promoted candidate for a PREFERRED venue."""
    return fixtures.build_sourcing_world(promote=False)


class TestPreferredStandingPatch:
    """PATCH /sourcing/venues/{venue_id}/preferred-status."""

    def test_suspension_writes_the_new_standing_and_advances_the_venue_version(
        self, candidate_world
    ):
        """A `ProgramAdmin` may promote a venue to `PREFERRED`, put it on `CONDITIONAL`, drop it to `NONE` or suspend it outright, and the move writes the new `preferred_supplier_status` and advances the venue's `version` by 1.

        Design: Corner/endpoints/preferred_status_patch_updates_the_master_without_rewriting_snapshots
        """
        response = api_client.update_venue_preferred_status(
            candidate_world["venue_id"],
            factories.preferred_status_payload("SUSPENDED"),
            PROGRAM_ADMIN_HEADERS,
        )
        venue = validate_success(response, 200)

        assert_fields_equal(
            venue,
            {
                "preferred_supplier_status": "SUSPENDED",
                "version": 2,
                "guest_rooms_total": 420,
                "largest_space_sqft": 14000,
                "blocked_room_nights": 0,
            },
        )
        assert_iso_instant(venue["updated_at"], "updated_at")

    def test_suspension_leaves_an_existing_entry_s_programme_snapshot_alone(
        self, candidate_world
    ):
        """Shortlist entries that already exist are **not** rewritten: each entry's `program_status_at_shortlist` snapshot keeps the value it captured at entry creation, so suspending a venue does not retroactively push its existing entries out of programme.

        Design: Corner/endpoints/preferred_status_patch_updates_the_master_without_rewriting_snapshots
        """
        fixtures.set_preferred_status(candidate_world["venue_id"], "SUSPENDED")

        entry = fixtures.read_entry(candidate_world["entry_id"])
        assert entry["program_status_at_shortlist"] == "IN_PROGRAM"

    def test_promoting_an_entry_whose_venue_was_suspended_is_refused(
        self, candidate_world
    ):
        """It requires the entry to be in `CANDIDATE`, and any other status is rejected with `ERR_SHORTLIST_ENTRY_STATE_INVALID`; it requires the parent event to be in `REQUIREMENTS_LOCKED`, `SOURCING` or `BID_REVIEW`; it re-checks that the venue's `preferred_supplier_status` is not `SUSPENDED`, rejecting with `ERR_VENUE_SUSPENDED` if it has been suspended since the entry was added; and when the event's `preferred_program_only` is `true` it requires the entry's `program_status_at_shortlist` to be `IN_PROGRAM`, rejecting with `ERR_PREFERRED_PROGRAM_REQUIRED` otherwise.

        Design: Corner/endpoints/preferred_status_patch_updates_the_master_without_rewriting_snapshots
        """
        fixtures.set_preferred_status(candidate_world["venue_id"], "SUSPENDED")

        response = api_client.shortlist_entry(
            candidate_world["entry_id"], PLANNER_HEADERS
        )
        validate_error(response, ApiErrorId.VENUE_SUSPENDED.value)

        assert fixtures.read_entry(candidate_world["entry_id"])["status"] == "CANDIDATE"
        assert (
            fixtures.read_event(candidate_world["event_id"])["shortlisted_venue_count"]
            == 0
        )

    def test_venue_collection_narrows_to_the_suspended_standing(self, candidate_world):
        """Venues may be narrowed by `destination_tier`, by `city` and by `preferred_supplier_status`.

        Design: Corner/endpoints/preferred_status_patch_updates_the_master_without_rewriting_snapshots
        """
        fixtures.set_preferred_status(candidate_world["venue_id"], "SUSPENDED")

        rows, meta = validate_paginated(
            api_client.list_venues(
                PLANNER_HEADERS, {"preferred_supplier_status": "SUSPENDED"}
            )
        )
        assert len(rows) == 1
        assert meta["total_count"] == 1
        assert rows[0]["id"] == candidate_world["venue_id"]


@pytest.fixture
def completed_event_world():
    """A closed-out event: its contract executed, its actuals filed, and a second
    registered venue that never won anything."""
    world = fixtures.build_executed_contract()
    world["venue_b"] = fixtures.create_second_venue()
    world["venue_b_id"] = world["venue_b"]["id"]
    fixtures.set_clock("2027-03-19T00:00:00.000Z")
    world["report"] = fixtures.file_post_event_report(
        world["event_id"],
        actual_room_nights=400,
        actual_fnb_usd=132000.00,
        actual_av_usd=19500.00,
    )
    return world


class TestSupplierPerformanceReviews:
    """POST /sourcing/venues/{venue_id}/performance-reviews."""

    def test_event_sourced_review_of_the_awarded_venue_is_scored_and_rolled_up(
        self, completed_event_world
    ):
        """Each review's `composite_score` is `0.35` times `service_score` plus `0.25` times `value_score` plus `0.20` times `av_quality_score` plus `0.20` times `responsiveness_score`, rounded to 2 decimal places.

        The `reviewer_user_id` is recorded from the caller's `X-User-ID`.

        Design: Corner/endpoints/performance_review_event_source_requires_this_venue_s_completed_event
        """
        world = completed_event_world
        response = api_client.create_performance_review(
            world["venue_id"],
            factories.performance_review_payload(
                review_source="EVENT", event_id=world["event_id"]
            ),
            PLANNER_HEADERS,
        )
        review = validate_success(response, 201)

        assert_money(review["composite_score"], 4.80, "composite_score")
        assert_fields_equal(
            review,
            {
                "review_source": "EVENT",
                "event_id": world["event_id"],
                "reviewer_user_id": "planner-anita",
            },
        )

        venue = fixtures.read_venue(world["venue_id"])
        assert_money(venue["performance_score"], 4.80, "performance_score")
        assert_money(
            venue["performance_score_simple_mean"], 4.80, "performance_score_simple_mean"
        )
        assert_integer(venue["performance_review_count"], 1, "performance_review_count")

    def test_external_review_carrying_an_event_id_is_refused(
        self, completed_event_world
    ):
        """The two sources have mirror-image requirements: `review_source` of `EVENT` requires `event_id` to name an event whose `status` is `COMPLETED` and whose awarded contract's `venue_id` equals the venue being reviewed, while `review_source` of `EXTERNAL` requires `event_id` to be absent.

        Either requirement failing yields `ERR_REVIEW_EVENT_INVALID`.

        Design: Corner/endpoints/performance_review_event_source_requires_this_venue_s_completed_event
        """
        world = completed_event_world
        response = api_client.create_performance_review(
            world["venue_id"],
            factories.performance_review_payload(
                review_source="EXTERNAL", event_id=world["event_id"]
            ),
            PLANNER_HEADERS,
        )
        validate_error(response, ApiErrorId.REVIEW_EVENT_INVALID.value)

    def test_event_sourced_review_without_an_event_id_is_refused(
        self, completed_event_world
    ):
        """The two sources have mirror-image requirements: `review_source` of `EVENT` requires `event_id` to name an event whose `status` is `COMPLETED` and whose awarded contract's `venue_id` equals the venue being reviewed, while `review_source` of `EXTERNAL` requires `event_id` to be absent.

        Either requirement failing yields `ERR_REVIEW_EVENT_INVALID`.

        Design: Corner/endpoints/performance_review_event_source_requires_this_venue_s_completed_event
        """
        world = completed_event_world
        response = api_client.create_performance_review(
            world["venue_id"],
            factories.performance_review_payload(review_source="EVENT"),
            PLANNER_HEADERS,
        )
        validate_error(response, ApiErrorId.REVIEW_EVENT_INVALID.value)

    def test_event_sourced_review_of_a_venue_that_did_not_win_is_refused(
        self, completed_event_world
    ):
        """The two sources have mirror-image requirements: `review_source` of `EVENT` requires `event_id` to name an event whose `status` is `COMPLETED` and whose awarded contract's `venue_id` equals the venue being reviewed, while `review_source` of `EXTERNAL` requires `event_id` to be absent.

        Both are null when the venue has zero reviews.

        Design: Corner/endpoints/performance_review_event_source_requires_this_venue_s_completed_event
        """
        world = completed_event_world
        response = api_client.create_performance_review(
            world["venue_b_id"],
            factories.performance_review_payload(
                review_source="EVENT", event_id=world["event_id"]
            ),
            PLANNER_HEADERS,
        )
        validate_error(response, ApiErrorId.REVIEW_EVENT_INVALID.value)

        venue_b = fixtures.read_venue(world["venue_b_id"])
        assert_integer(venue_b["performance_review_count"], 0, "performance_review_count")
        assert_nulls(venue_b, ["performance_score", "performance_score_simple_mean"])

    def test_review_collection_narrows_to_one_venue(self, completed_event_world):
        """Supplier performance reviews may be narrowed by `venue_id`, by `event_id` and by `review_source`.

        Design: Corner/endpoints/performance_review_event_source_requires_this_venue_s_completed_event
        """
        world = completed_event_world
        review = validate_success(
            api_client.create_performance_review(
                world["venue_id"],
                factories.performance_review_payload(
                    review_source="EVENT", event_id=world["event_id"]
                ),
                PLANNER_HEADERS,
            ),
            201,
        )

        rows, meta = validate_paginated(
            api_client.list_performance_reviews(
                PLANNER_HEADERS, {"venue_id": world["venue_id"]}
            )
        )
        assert len(rows) == 1
        assert meta["total_count"] == 1
        assert rows[0]["id"] == review["id"]


@pytest.fixture
def bid_collection_world():
    """One issued round holding three bids in three different statuses."""
    world = build_three_bidder_round()
    fixtures.submit_bid(world["proposal_a_id"], world["venue_a_id"])
    fixtures.submit_bid(world["proposal_b_id"], world["venue_b_id"], **CASCADE_BAY_GRID)
    fixtures.evaluate_bid(world["proposal_b_id"], "CONTRACTED_BASIS")
    return world


class TestBidCollectionFiltersAndPagination:
    """GET /sourcing/proposals."""

    def test_round_filter_returns_every_minted_bid_on_the_default_page(
        self, bid_collection_world
    ):
        """List responses carry the pagination state in the envelope's `meta` object as `limit`, `offset`, `total_count` and `has_more`, where `total_count` is the size of the full filtered result set and `has_more` indicates whether any items remain beyond the returned page.

        One bid is created in `INVITED` for each eligible entry, processed in ascending `rank_seq` order so the highest-preference venue's bid is created first, each copying `venue_id` from its source entry; `invited_count` is set to the number of bids created.

        Design: Corner/endpoints/proposal_list_filters_and_pagination_interact
        """
        world = bid_collection_world
        rows, meta = validate_paginated(
            api_client.list_proposals(PLANNER_HEADERS, {"rfp_id": world["rfp_id"]})
        )

        assert len(rows) == 3
        assert_pagination_meta(meta, limit=10, offset=0, total_count=3, has_more=False)
        assert [row["id"] for row in rows] == [
            world["proposal_a_id"],
            world["proposal_b_id"],
            world["proposal_c_id"],
        ]

    def test_status_filter_narrows_the_round_to_the_untouched_submission(
        self, bid_collection_world
    ):
        """Bids may be narrowed by `rfp_id`, by `venue_id` and by `status`, and this bid collection is the only discovery channel for the `INVITED` bids minted when a solicitation is issued.

        In all three cases a new snapshot row is appended and earlier rows are left exactly as written, the bid's `total_cost_modeled_usd` and `last_evaluation_basis` are overwritten from the newest row, and the bid's `version` advances by 1.

        Design: Corner/endpoints/proposal_list_filters_and_pagination_interact
        """
        world = bid_collection_world
        rows, meta = validate_paginated(
            api_client.list_proposals(
                PLANNER_HEADERS, {"rfp_id": world["rfp_id"], "status": "SUBMITTED"}
            )
        )

        assert len(rows) == 1
        assert rows[0]["id"] == world["proposal_a_id"]
        assert_pagination_meta(meta, limit=10, offset=0, total_count=1, has_more=False)

        evaluated = fixtures.read_proposal(world["proposal_b_id"])
        assert_fields_equal(
            evaluated,
            {"status": "UNDER_REVIEW", "last_evaluation_basis": "CONTRACTED_BASIS"},
        )

    def test_offset_past_the_first_page_returns_only_the_tail(
        self, bid_collection_world
    ):
        """`offset` is the number of items to skip before the first returned item; it defaults to 0 and may not be negative.

        Design: Corner/endpoints/proposal_list_filters_and_pagination_interact
        """
        world = bid_collection_world
        rows, meta = validate_paginated(
            api_client.list_proposals(
                PLANNER_HEADERS, {"rfp_id": world["rfp_id"], "limit": 2, "offset": 2}
            )
        )

        assert len(rows) == 1
        assert rows[0]["id"] == world["proposal_c_id"]
        assert_pagination_meta(meta, limit=2, offset=2, total_count=3, has_more=False)

    def test_limit_below_one_is_rejected(self, bid_collection_world):
        """A `limit` outside the range 1 through 100 inclusive, or a negative `offset`, is rejected with `ERR_INVALID_PAGINATION` (HTTP 400).

        Design: Corner/endpoints/proposal_list_filters_and_pagination_interact
        """
        world = bid_collection_world
        response = api_client.list_proposals(
            PLANNER_HEADERS, {"rfp_id": world["rfp_id"], "limit": 0}
        )
        validate_error(response, ApiErrorId.INVALID_PAGINATION.value)

    def test_venue_filter_surfaces_the_invited_bid_that_never_answered(
        self, bid_collection_world
    ):
        """Bids may be narrowed by `rfp_id`, by `venue_id` and by `status`, and this bid collection is the only discovery channel for the `INVITED` bids minted when a solicitation is issued.

        The bid's `total_cost_contracted_usd` is **not** touched by evaluation; it changes only on submission and revision.

        Design: Corner/endpoints/proposal_list_filters_and_pagination_interact
        """
        world = bid_collection_world
        rows, meta = validate_paginated(
            api_client.list_proposals(PLANNER_HEADERS, {"venue_id": world["venue_c_id"]})
        )

        assert len(rows) == 1
        assert meta["total_count"] == 1
        assert rows[0]["id"] == world["proposal_c_id"]
        assert rows[0]["status"] == "INVITED"
        assert_nulls(rows[0], ["total_cost_contracted_usd"])
