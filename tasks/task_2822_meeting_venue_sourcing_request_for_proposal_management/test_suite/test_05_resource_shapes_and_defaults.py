"""Resource shapes, server-derived fields and the declared defaults.

Every check here reads the persisted body of a resource the API minted: the
audit quartet on a mutable row, the reduced pair on an append-only record, the
seeded money envelope of a meeting event, the computed grid of a submitted bid
and the two collection surfaces (pagination state and equality filters).
"""

from typing import Any, Dict, Tuple

import pytest

from test_helpers import (
    CLOCK_SOURCING_WINDOW,
    NON_EXISTENT_UUID,
    PLANNER_HEADERS,
    PLANNER_USER_ID,
    PROGRAM_ADMIN_HEADERS,
    ApiErrorId,
    api_client,
    make_venue_rep_headers,
    validate_error,
    validate_paginated,
    validate_success,
)
from test_helpers import assertions as domain_assert
from test_helpers import factories, fixtures

# The alternative quoted grid of the design: a GROSS rate carrying a ten per
# cent travel-agency commission, 400 offered nights at one comp per forty, a
# third-tier audiovisual estimate and a concession offer above the eight per
# cent cap.
GROSS_RATE_GRID: Dict[str, Any] = {
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
    "force_majeure_scope": "STANDARD",
    "rebooking_credit_pct": 0.40,
}


def _create_canonical_event(**overrides: Any):
    """Open the canonical user-conference sourcing file and hand back the response."""
    fixtures.set_clock(CLOCK_SOURCING_WINDOW)
    payload = factories.event_payload(event_code="EVT-2822-A", **overrides)
    return api_client.create_event(payload, PLANNER_HEADERS)


def _register_three_venues() -> Tuple[Dict[str, Any], Dict[str, Any], Dict[str, Any]]:
    """Two TIER_1 venues and one TIER_2 venue in the supplier master."""
    fixtures.set_clock(CLOCK_SOURCING_WINDOW)
    first = fixtures.create_venue()
    second = fixtures.create_second_venue()
    third = fixtures.create_venue(
        name="Lakeview Training Centre",
        city="Warsaw",
        country="PL",
        destination_tier="TIER_2",
        guest_rooms_total=200,
        largest_space_sqft=6000,
    )
    return first, second, third


def _submitted_gross_bid() -> Dict[str, Any]:
    """An issued round whose single invited venue answers with the GROSS grid."""
    world = fixtures.build_issued_round()
    response = api_client.submit_proposal(
        world["proposal_id"],
        factories.proposal_submission_payload(**GROSS_RATE_GRID),
        make_venue_rep_headers(world["venue_id"]),
    )
    world["submit_response"] = response
    world["proposal"] = validate_success(response, 200)
    return world


def _conditional_venue_candidate() -> Dict[str, Any]:
    """A locked requirement plus a first candidate entry for a CONDITIONAL venue."""
    fixtures.set_clock(CLOCK_SOURCING_WINDOW)
    fixtures.create_benchmark()
    venue = fixtures.create_venue(preferred_supplier_status="CONDITIONAL")
    event = fixtures.create_event(event_code="EVT-2822-A")
    fixtures.lock_event(event["id"])
    response = api_client.create_shortlist_entry(
        event["id"],
        factories.shortlist_entry_payload(venue["id"], rank_seq=1, inspection_required=False),
        PLANNER_HEADERS,
    )
    return {"event": event, "venue": venue, "response": response}


class TestMeetingEventCreation:
    """The declared field set of a freshly opened meeting event."""

    def test_created_event_echoes_the_requirement_and_derives_the_night_span(self):
        """Opening a sourcing file echoes every submitted requirement field and
        derives the room-block night count from the date pair.

        From that pair the server computes `nights_span`, the number of whole days from `start_date` to `end_date`, which is the room-block night count the deposit and capacity arithmetic later divides by.
        Design: Corner/entities/create_meeting_event_returns_all_declared_fields
        """
        response = _create_canonical_event()
        event = validate_success(response, 201)
        domain_assert.assert_envelope(response, "object")

        domain_assert.assert_fields_equal(
            event,
            {
                "event_code": "EVT-2822-A",
                "name": "Global User Conference 2027",
                "program_type": "USER_CONFERENCE",
                "start_date": "2027-03-15",
                "end_date": "2027-03-18",
                "peak_attendees": 200,
                "requested_room_nights": 600,
                "largest_meeting_space_sqft": 12000,
                "preferred_program_only": False,
            },
        )
        domain_assert.assert_calendar_date(event["start_date"], "start_date")
        domain_assert.assert_calendar_date(event["end_date"], "end_date")
        domain_assert.assert_integer(event["nights_span"], 3, "nights_span")
        domain_assert.assert_versioned_entity(event, 1)

    def test_created_event_starts_in_draft_with_its_budget_fully_unspent(self):
        """The status, the owning planner and the whole money envelope are
        seeded by the server, not by the caller.

        The new event's `status` is `DRAFT`, `sourcing_owner_user_id` is set to the calling planner's `X-User-ID`, `budget_remaining_usd` equals `budget_ceiling_usd`, and `committed_spend_usd` and `cancellation_liability_usd` are both `0.00`.
        Design: Corner/entities/create_meeting_event_returns_all_declared_fields
        """
        event = validate_success(_create_canonical_event(), 201)

        assert event["status"] == "DRAFT"
        assert event["sourcing_owner_user_id"] == PLANNER_USER_ID
        domain_assert.assert_money_field(event, "budget_ceiling_usd", 500000.00)
        domain_assert.assert_money_field(event, "budget_remaining_usd", 500000.00)
        domain_assert.assert_money_field(event, "committed_spend_usd", 0.00)
        domain_assert.assert_money_field(event, "cancellation_liability_usd", 0.00)
        domain_assert.assert_budget_envelope(event)

    def test_created_event_has_no_live_bid_no_award_and_no_closeout_figures(self):
        """The rollup surface exists from the first instant and is empty.

        `shortlisted_venue_count` is 0, while `best_total_cost_usd`, `awarded_proposal_id` and `savings_recognized_usd` are all null — there is no live bid, no award and no closeout report yet.
        Design: Corner/entities/create_meeting_event_returns_all_declared_fields
        """
        event = validate_success(_create_canonical_event(), 201)

        domain_assert.assert_integer(
            event["shortlisted_venue_count"], 0, "shortlisted_venue_count"
        )
        domain_assert.assert_nulls(
            event,
            ["best_total_cost_usd", "awarded_proposal_id", "savings_recognized_usd"],
        )


class TestVenueMasterRow:
    """Reading back a registered venue."""

    def test_venue_read_returns_the_stored_registration_row(self):
        """A read of the supplier master returns exactly the registered
        identity fields together with the audit quartet.

        A `ProgramAdmin` builds the supplier master by registering each venue with its `name`, its `city`, its `country` as an ISO 3166-1 alpha-2 code, and its `destination_tier` — one of `TIER_1`, `TIER_2` or `TIER_3`, the axis along which the programme benchmarks rates.
        Design: Corner/entities/get_venue_by_id_returns_stored_row
        """
        fixtures.set_clock(CLOCK_SOURCING_WINDOW)
        created = fixtures.create_venue()

        response = api_client.get_venue(created["id"], PLANNER_HEADERS)
        venue = validate_success(response, 200)
        domain_assert.assert_envelope(response, "object")

        assert venue["id"] == created["id"]
        domain_assert.assert_fields_equal(
            venue,
            {
                "name": "Harborline Grand",
                "city": "Lisbon",
                "country": "PT",
                "destination_tier": "TIER_1",
                "guest_rooms_total": 420,
                "largest_space_sqft": 14000,
                "preferred_supplier_status": "PREFERRED",
            },
        )
        domain_assert.assert_versioned_entity(venue, 1)

    def test_venue_read_shows_an_untraded_supplier_with_empty_rollups(self):
        """No review and no executed contract yet, so every derived venue
        figure is null or zero.

        A freshly registered venue has `performance_score` null, `performance_score_simple_mean` null, `performance_review_count` at 0 and `blocked_room_nights` at 0.
        Design: Corner/entities/get_venue_by_id_returns_stored_row
        """
        fixtures.set_clock(CLOCK_SOURCING_WINDOW)
        created = fixtures.create_venue()

        venue = validate_success(api_client.get_venue(created["id"], PLANNER_HEADERS), 200)

        domain_assert.assert_nulls(
            venue, ["performance_score", "performance_score_simple_mean"]
        )
        domain_assert.assert_integer(
            venue["performance_review_count"], 0, "performance_review_count"
        )
        domain_assert.assert_room_night_inventory(venue, 0)


class TestVenueCollectionSurface:
    """Pagination state and equality filters on the venue collection."""

    def test_venue_pages_report_the_full_filtered_size_and_whether_more_remain(self):
        """Two pages of size two over three venues: the first page still has
        items beyond it, the second does not, and both report the same total.

        List responses carry the pagination state in the envelope's `meta` object as `limit`, `offset`, `total_count` and `has_more`, where `total_count` is the size of the full filtered result set and `has_more` indicates whether any items remain beyond the returned page.
        Design: Corner/entities/list_venues_paginated_with_total_count_and_has_more
        """
        _register_three_venues()

        first_page, first_meta = validate_paginated(
            api_client.list_venues(PLANNER_HEADERS, {"limit": 2, "offset": 0})
        )
        assert len(first_page) == 2
        domain_assert.assert_pagination_meta(
            first_meta, limit=2, offset=0, total_count=3, has_more=True
        )

        second_page, second_meta = validate_paginated(
            api_client.list_venues(PLANNER_HEADERS, {"limit": 2, "offset": 2})
        )
        assert len(second_page) == 1
        domain_assert.assert_pagination_meta(
            second_meta, limit=2, offset=2, total_count=3, has_more=False
        )

        paged_ids = [row["id"] for row in first_page] + [row["id"] for row in second_page]
        assert len(set(paged_ids)) == 3

    def test_tier_filter_narrows_the_total_count_and_keeps_the_default_page_size(self):
        """Filtering by destination tier shrinks the reported total to the size
        of the filtered set while the page size falls back to its default.

        `limit` caps the number of items returned; it defaults to 10 when omitted, may not be smaller than 1 and may not be larger than 100.
        Design: Corner/entities/list_venues_paginated_with_total_count_and_has_more
        """
        first, second, third = _register_three_venues()

        rows, meta = validate_paginated(
            api_client.list_venues(PLANNER_HEADERS, {"destination_tier": "TIER_1"})
        )

        assert len(rows) == 2
        domain_assert.assert_pagination_meta(
            meta, limit=10, offset=0, total_count=2, has_more=False
        )
        assert {row["id"] for row in rows} == {first["id"], second["id"]}
        assert third["id"] not in {row["id"] for row in rows}
        assert all(row["destination_tier"] == "TIER_1" for row in rows)


class TestVenuePreferredStatusDefault:
    """The optional programme-status field and its declared default."""

    def test_registering_without_a_preferred_status_stores_none(self):
        """Omitting the optional programme field registers the venue outside
        the preferred programme rather than rejecting the request.

        Registration may optionally set the venue's `preferred_supplier_status`, one of `PREFERRED`, `CONDITIONAL`, `NONE` or `SUSPENDED`; when the field is omitted the venue is registered as `NONE`.
        Design: Corner/entities/create_venue_omitting_preferred_supplier_status_applies_default_none
        """
        fixtures.set_clock(CLOCK_SOURCING_WINDOW)
        payload = factories.venue_payload(
            name="Quiet Harbour Inn",
            city="Faro",
            country="PT",
            destination_tier="TIER_3",
            guest_rooms_total=90,
            largest_space_sqft=2500,
        )
        payload.pop("preferred_supplier_status")

        response = api_client.create_venue(payload, PROGRAM_ADMIN_HEADERS)
        venue = validate_success(response, 201)

        assert venue["preferred_supplier_status"] == "NONE"
        domain_assert.assert_fields_equal(
            venue,
            {
                "name": "Quiet Harbour Inn",
                "city": "Faro",
                "country": "PT",
                "destination_tier": "TIER_3",
                "guest_rooms_total": 90,
                "largest_space_sqft": 2500,
            },
        )
        domain_assert.assert_versioned_entity(venue, 1)
        domain_assert.assert_integer(
            venue["performance_review_count"], 0, "performance_review_count"
        )
        domain_assert.assert_room_night_inventory(venue, 0)

    def test_defaulted_venue_is_discoverable_through_the_status_filter(self):
        """The stored default is a real value the collection filter matches on.

        Venues may be narrowed by `destination_tier`, by `city` and by `preferred_supplier_status`.
        Design: Corner/entities/create_venue_omitting_preferred_supplier_status_applies_default_none
        """
        fixtures.set_clock(CLOCK_SOURCING_WINDOW)
        payload = factories.venue_payload(name="Quiet Harbour Inn", destination_tier="TIER_3")
        payload.pop("preferred_supplier_status")
        created = validate_success(
            api_client.create_venue(payload, PROGRAM_ADMIN_HEADERS), 201
        )
        fixtures.create_venue()

        rows, meta = validate_paginated(
            api_client.list_venues(PLANNER_HEADERS, {"preferred_supplier_status": "NONE"})
        )

        domain_assert.assert_ids(rows, [created["id"]])
        assert meta["total_count"] == 1


class TestUnknownIdentifierReads:
    """A path identifier that resolves to nothing."""

    def test_reading_an_event_that_does_not_exist_reports_the_event_not_found(self):
        """A syntactically valid identifier that names no meeting event is a
        404 for the event resource type, and nothing is created by the attempt.

        Identifiers embedded in a path are resolved strictly left to right, and the first segment that fails to resolve determines the error: the request is rejected immediately with the 404 that belongs to that segment's resource type, without attempting to resolve anything to its right and without running any business rule.
        Design: Corner/entities/get_event_with_unknown_id_returns_event_not_found
        """
        fixtures.set_clock(CLOCK_SOURCING_WINDOW)

        response = api_client.get_event(NON_EXISTENT_UUID, PLANNER_HEADERS)
        error = validate_error(response, ApiErrorId.EVENT_NOT_FOUND, 404)
        assert error["message"]

        rows, meta = validate_paginated(api_client.list_events(PLANNER_HEADERS))
        assert rows == []
        assert meta["total_count"] == 0


class TestEventRequestShape:
    """Shape checks that run before any business rule on event creation."""

    def test_event_without_its_budget_ceiling_is_an_invalid_request(self):
        """A missing required money field is a shape failure, so no row is
        written at all.

        Request bodies are checked for shape before any business rule runs: every required field must be present and of its declared type, every enum-typed field must carry a declared member, every money field must be non-negative and carry at most two decimal places, and every percentage field must fall inside its declared range.
        Design: Corner/entities/create_event_missing_budget_ceiling_returns_invalid_request
        """
        fixtures.set_clock(CLOCK_SOURCING_WINDOW)
        payload = factories.event_payload(event_code="EVT-2822-A")
        payload.pop("budget_ceiling_usd")

        response = api_client.create_event(payload, PLANNER_HEADERS)
        validate_error(response, ApiErrorId.INVALID_REQUEST, 400)

        _, meta = validate_paginated(api_client.list_events(PLANNER_HEADERS))
        assert meta["total_count"] == 0

    def test_event_with_an_undeclared_program_type_is_an_invalid_request(self):
        """An enum-typed field carrying a value outside its declared members is
        rejected by the same shape band.

        Request bodies are checked for shape before any business rule runs: every required field must be present and of its declared type, every enum-typed field must carry a declared member, every money field must be non-negative and carry at most two decimal places, and every percentage field must fall inside its declared range.
        Design: Corner/entities/create_event_missing_budget_ceiling_returns_invalid_request
        """
        fixtures.set_clock(CLOCK_SOURCING_WINDOW)
        payload = factories.event_payload(event_code="EVT-2822-A", program_type="OFFSITE")

        response = api_client.create_event(payload, PLANNER_HEADERS)
        validate_error(response, ApiErrorId.INVALID_REQUEST, 400)

        _, meta = validate_paginated(api_client.list_events(PLANNER_HEADERS))
        assert meta["total_count"] == 0

    @pytest.mark.parametrize(
        "start_date,end_date",
        [
            pytest.param("2027-03-18", "2027-03-15", id="inverted"),
            pytest.param("2027-03-15", "2027-03-15", id="equal"),
        ],
    )
    def test_event_whose_departure_does_not_follow_arrival_is_an_invalid_date_range(
        self, start_date, end_date
    ):
        """A zero-night or negative-night room block cannot open a sourcing
        file, and it is reported as a date-range failure rather than a shape one.

        Both dates are `YYYY-MM-DD` strings interpreted in UTC, and `end_date` must be strictly after `start_date` — an equal or inverted pair is rejected with `ERR_INVALID_DATE_RANGE`.
        Design: Corner/entities/create_event_with_end_date_before_start_date_returns_invalid_date_range
        """
        fixtures.set_clock(CLOCK_SOURCING_WINDOW)
        payload = factories.event_payload(
            event_code="EVT-2822-A", start_date=start_date, end_date=end_date
        )

        response = api_client.create_event(payload, PLANNER_HEADERS)
        validate_error(response, ApiErrorId.INVALID_DATE_RANGE, 422)

        _, meta = validate_paginated(api_client.list_events(PLANNER_HEADERS))
        assert meta["total_count"] == 0


class TestShortlistEntryParentResolution:
    """Both ends of the junction row must resolve before it is written."""

    def test_entry_under_an_unknown_event_reports_the_event_not_found(self):
        """The path segment resolves first, so an unknown event masks whatever
        the body carries.

        Identifiers embedded in a path are resolved strictly left to right, and the first segment that fails to resolve determines the error: the request is rejected immediately with the 404 that belongs to that segment's resource type, without attempting to resolve anything to its right and without running any business rule.
        Design: Corner/entities/shortlist_entry_requires_existing_parent_event_and_venue
        """
        fixtures.set_clock(CLOCK_SOURCING_WINDOW)
        fixtures.create_benchmark()
        venue = fixtures.create_venue()

        response = api_client.create_shortlist_entry(
            NON_EXISTENT_UUID,
            factories.shortlist_entry_payload(venue["id"], rank_seq=1),
            PLANNER_HEADERS,
        )
        validate_error(response, ApiErrorId.EVENT_NOT_FOUND, 404)

        _, meta = validate_paginated(api_client.list_shortlist_entries(PLANNER_HEADERS))
        assert meta["total_count"] == 0

    def test_entry_naming_an_unknown_venue_reports_the_venue_not_found(self):
        """With the parent event resolved, the body's foreign key is resolved
        next and its own 404 is returned.

        A `venue_id` that names no venue when adding a shortlist entry yields `ERR_VENUE_NOT_FOUND`; a `previous_rfp_id` that names no solicitation round when drafting a round yields `ERR_RFP_NOT_FOUND`; a `proposal_id` that names no bid when awarding yields `ERR_PROPOSAL_NOT_FOUND`; a `counter_id` that names no negotiation counter when revising a bid yields `ERR_COUNTER_NOT_FOUND`; and an `event_id` that names no meeting event when capturing a performance review yields `ERR_EVENT_NOT_FOUND`.
        Design: Corner/entities/shortlist_entry_requires_existing_parent_event_and_venue
        """
        fixtures.set_clock(CLOCK_SOURCING_WINDOW)
        fixtures.create_benchmark()
        fixtures.create_venue()
        event = fixtures.create_event(event_code="EVT-2822-A")
        fixtures.lock_event(event["id"])

        response = api_client.create_shortlist_entry(
            event["id"],
            factories.shortlist_entry_payload(NON_EXISTENT_UUID, rank_seq=1),
            PLANNER_HEADERS,
        )
        validate_error(response, ApiErrorId.VENUE_NOT_FOUND, 404)

        _, meta = validate_paginated(api_client.list_shortlist_entries(PLANNER_HEADERS))
        assert meta["total_count"] == 0

    def test_entry_is_written_once_both_the_event_and_the_venue_resolve(self):
        """The same request body succeeds when both ends of the link exist.

        The planner adds a candidate by naming a `venue_id` and an explicit `rank_seq`, the planner-assigned shortlist ordering in which 1 is the highest preference; `rank_seq` must be at least 1 and must be unused within the event.
        Design: Corner/entities/shortlist_entry_requires_existing_parent_event_and_venue
        """
        fixtures.set_clock(CLOCK_SOURCING_WINDOW)
        fixtures.create_benchmark()
        venue = fixtures.create_venue()
        event = fixtures.create_event(event_code="EVT-2822-A")
        fixtures.lock_event(event["id"])

        response = api_client.create_shortlist_entry(
            event["id"],
            factories.shortlist_entry_payload(venue["id"], rank_seq=1),
            PLANNER_HEADERS,
        )
        entry = validate_success(response, 201)

        domain_assert.assert_fields_equal(
            entry,
            {"event_id": event["id"], "venue_id": venue["id"], "rank_seq": 1},
        )
        domain_assert.assert_versioned_entity(entry, 1)

        rows, meta = validate_paginated(api_client.list_shortlist_entries(PLANNER_HEADERS))
        assert meta["total_count"] == 1
        domain_assert.assert_ids(rows, [entry["id"]])


class TestSubmittedBidComputedGrid:
    """Everything the server derives from a commissionable quoted grid."""

    def test_gross_quote_is_converted_to_a_net_daily_rate(self):
        """A commissionable rate is reduced by its commission before any other
        arithmetic reads it.

        When `rate_type` is `GROSS`, it is `room_rate_usd` multiplied by one minus `commission_pct`, rounded half up to two decimals.
        Design: Corner/entities/proposal_computed_fields_derived_from_gross_rate_and_commission
        """
        world = _submitted_gross_bid()
        bid = world["proposal"]

        assert bid["status"] == "SUBMITTED"
        domain_assert.assert_money_field(bid, "room_rate_usd", 275.00)
        assert bid["rate_type"] == "GROSS"
        domain_assert.assert_money_field(bid, "net_adr_usd", 247.50)

    def test_comp_rooms_are_floored_and_deducted_from_the_offered_nights(self):
        """One free night per forty offered nights, never a fractional room.

        `comp_room_nights` is 0 when `comp_room_ratio` is 0; otherwise it is `room_nights_offered` divided by `comp_room_ratio`, rounded **down** to a whole night.
        Design: Corner/entities/proposal_computed_fields_derived_from_gross_rate_and_commission
        """
        bid = _submitted_gross_bid()["proposal"]

        domain_assert.assert_integer(bid["room_nights_offered"], 400, "room_nights_offered")
        domain_assert.assert_integer(bid["comp_room_nights"], 10, "comp_room_nights")
        domain_assert.assert_integer(bid["paid_room_nights"], 390, "paid_room_nights")

    def test_contracted_total_nets_the_capped_concession_off_the_gross_figure(self):
        """The stored contracted total prices the paid nights, the fixed spend
        and the layered charges, then relieves only the capped concession.

        The variant's total is the gross figure, less `concession_applied_usd`, plus the attrition damages term, rounded half up to two decimals.
        Design: Corner/entities/proposal_computed_fields_derived_from_gross_rate_and_commission
        """
        bid = _submitted_gross_bid()["proposal"]

        domain_assert.assert_money_field(bid, "total_cost_contracted_usd", 290551.07)
        domain_assert.assert_two_decimals(
            bid["total_cost_contracted_usd"], "total_cost_contracted_usd"
        )

    def test_net_rate_below_benchmark_earns_a_negative_variance_and_compliance(self):
        """The signed four-decimal variance against the programme benchmark
        drives the compliance verdict for a preferred supplier.

        With the benchmark in hand, `benchmark_variance_pct` is the signed fraction by which the bid's `net_adr_usd` exceeds the benchmark's `benchmark_adr_usd`: the difference between `net_adr_usd` and `benchmark_adr_usd`, divided by `benchmark_adr_usd`, rounded half up to **four** decimal places.
        Design: Corner/entities/proposal_computed_fields_derived_from_gross_rate_and_commission
        """
        bid = _submitted_gross_bid()["proposal"]

        domain_assert.assert_variance_pct(bid["benchmark_variance_pct"], -0.0481)
        assert bid["compliance_status"] == "COMPLIANT"

    def test_submission_stamps_the_clock_and_leaves_the_evaluation_fields_empty(self):
        """Submitting is not evaluating: the modeled figures stay empty and no
        evaluation snapshot exists yet.

        Before any evaluation exists, both `total_cost_modeled_usd` and `last_evaluation_basis` are null.
        Design: Corner/entities/proposal_computed_fields_derived_from_gross_rate_and_commission
        """
        world = _submitted_gross_bid()
        bid = world["proposal"]

        domain_assert.assert_nulls(bid, ["total_cost_modeled_usd", "last_evaluation_basis"])
        assert bid["submitted_at"] == CLOCK_SOURCING_WINDOW
        domain_assert.assert_iso_instant(bid["submitted_at"], "submitted_at")

        _, evaluations_meta = validate_paginated(
            api_client.list_bid_evaluations(world["proposal_id"], PLANNER_HEADERS)
        )
        assert evaluations_meta["total_count"] == 0

    def test_submission_lifts_the_round_counter_and_the_event_best_total(self):
        """The live bid becomes the round's only answer and the event's cheapest
        total, carried across unrounded.

        Otherwise it is the `total_cost_contracted_usd` of the live bid with the smallest `total_cost_contracted_usd`, with ties broken in favour of the bid with the earlier `created_at` and never by comparing `id` values; the stored two-decimal value is carried across unchanged with no further rounding.
        Design: Corner/entities/proposal_computed_fields_derived_from_gross_rate_and_commission
        """
        world = _submitted_gross_bid()

        rfp = fixtures.read_rfp(world["rfp_id"])
        domain_assert.assert_integer(rfp["invited_count"], 1, "invited_count")
        domain_assert.assert_integer(rfp["submitted_count"], 1, "submitted_count")

        event = fixtures.read_event(world["event_id"])
        domain_assert.assert_money_field(event, "best_total_cost_usd", 290551.07)


class TestShortlistEntryServerDerivedFields:
    """The candidate row the server fills in on the planner's behalf."""

    def test_new_candidate_lands_in_candidate_with_no_elimination_and_no_visit(self):
        """The planner supplies only the link and the rank; the status, the
        elimination reason and the visit counter are the server's.

        The new entry lands in `CANDIDATE` with `elimination_reason` null and `inspection_count` at 0, and it captures a snapshot that is never re-derived.
        Design: Corner/entities/system_fields_on_shortlist_entry_are_server_derived
        """
        world = _conditional_venue_candidate()
        entry = validate_success(world["response"], 201)

        assert entry["status"] == "CANDIDATE"
        domain_assert.assert_nulls(entry, ["elimination_reason"])
        domain_assert.assert_integer(entry["inspection_count"], 0, "inspection_count")
        domain_assert.assert_fields_equal(
            entry,
            {
                "event_id": world["event"]["id"],
                "venue_id": world["venue"]["id"],
                "rank_seq": 1,
                "inspection_required": False,
            },
        )
        domain_assert.assert_versioned_entity(entry, 1)

    def test_conditional_supplier_is_snapshotted_as_in_program(self):
        """A conditionally preferred venue counts as inside the programme at
        the moment it is shortlisted.

        `program_status_at_shortlist` is set to `IN_PROGRAM` when the venue's `preferred_supplier_status` at that moment is `PREFERRED` or `CONDITIONAL`, and to `OUT_OF_PROGRAM` when it is anything else.
        Design: Corner/entities/system_fields_on_shortlist_entry_are_server_derived
        """
        world = _conditional_venue_candidate()
        entry = validate_success(world["response"], 201)

        assert world["venue"]["preferred_supplier_status"] == "CONDITIONAL"
        assert entry["program_status_at_shortlist"] == "IN_PROGRAM"

    def test_candidate_does_not_yet_count_towards_the_shortlisted_total(self):
        """An entry still in `CANDIDATE` is outside the event's shortlist count.

        That count is maintained as the number of the event's entries whose `status` is one of `SHORTLISTED`, `INSPECTION_SCHEDULED`, `INSPECTED`, `RFP_ISSUED` or `AWARDED` — entries still in `CANDIDATE` and entries already `ELIMINATED` are excluded.
        Design: Corner/entities/system_fields_on_shortlist_entry_are_server_derived
        """
        world = _conditional_venue_candidate()
        entry = validate_success(world["response"], 201)

        assert entry["status"] == "CANDIDATE"
        event = fixtures.read_event(world["event"]["id"])
        domain_assert.assert_integer(
            event["shortlisted_venue_count"], 0, "shortlisted_venue_count"
        )


class TestRateBenchmarkAppendOnlyShape:
    """The reduced audit surface of a published benchmark."""

    def test_published_benchmark_carries_no_updated_at_and_no_version(self):
        """A benchmark is an append-only record: it is stamped once and never
        revised, so it exposes no mutation timestamp and no version counter.

        Two resource types are append-only records and deliberately carry a reduced set: a published **rate benchmark** and a **bid evaluation** snapshot both expose only `id` and `created_at`.
        Design: Corner/entities/rate_benchmark_is_immutable_with_no_version_field
        """
        fixtures.set_clock(CLOCK_SOURCING_WINDOW)
        created = fixtures.create_benchmark()

        response = api_client.get_rate_benchmark(created["id"], PLANNER_HEADERS)
        benchmark = validate_success(response, 200)

        domain_assert.assert_append_only_entity(benchmark)
        domain_assert.assert_fields_equal(
            benchmark, {"destination_tier": "TIER_1", "program_type": "USER_CONFERENCE"}
        )
        domain_assert.assert_money_field(benchmark, "benchmark_adr_usd", 260.00)
        assert benchmark["benchmark_service_charge_pct"] == pytest.approx(0.24, abs=0.0001)
        assert benchmark["benchmark_tax_pct"] == pytest.approx(0.156, abs=0.0001)

    def test_published_benchmark_is_the_single_row_for_its_tier(self):
        """The immutable row is discoverable through the benchmark collection
        exactly once for the tier it was published against.

        Rate benchmarks may be narrowed by `destination_tier` and by `program_type`.
        Design: Corner/entities/rate_benchmark_is_immutable_with_no_version_field
        """
        fixtures.set_clock(CLOCK_SOURCING_WINDOW)
        created = fixtures.create_benchmark()

        rows, meta = validate_paginated(
            api_client.list_rate_benchmarks(
                PLANNER_HEADERS,
                {"destination_tier": "TIER_1", "program_type": "USER_CONFERENCE"},
            )
        )

        domain_assert.assert_ids(rows, [created["id"]])
        assert meta["total_count"] == 1
        domain_assert.assert_append_only_entity(rows[0])


def _junction_grid() -> Dict[str, Any]:
    """Two locked events and two venues, wired into four shortlist entries."""
    fixtures.set_clock(CLOCK_SOURCING_WINDOW)
    fixtures.create_benchmark()
    venue_a = fixtures.create_venue()
    venue_b = fixtures.create_second_venue()
    event_a = fixtures.create_event(event_code="EVT-2822-A")
    event_b = fixtures.create_event(
        event_code="EVT-2822-B",
        name="EMEA Sales Training 2027",
        program_type="TRAINING",
        start_date="2027-05-10",
        end_date="2027-05-12",
        peak_attendees=80,
        requested_room_nights=160,
        largest_meeting_space_sqft=5200,
        budget_ceiling_usd=180000.00,
    )
    fixtures.lock_event(event_a["id"])
    fixtures.lock_event(event_b["id"])
    return {
        "venue_a": venue_a,
        "venue_b": venue_b,
        "event_a": event_a,
        "event_b": event_b,
        "entry_a1": fixtures.add_entry(event_a["id"], venue_a["id"], rank_seq=1),
        "entry_a2": fixtures.add_entry(event_a["id"], venue_b["id"], rank_seq=2),
        "entry_b1": fixtures.add_entry(event_b["id"], venue_a["id"], rank_seq=1),
        "entry_b2": fixtures.add_entry(event_b["id"], venue_b["id"], rank_seq=2),
    }


class TestShortlistJunctionTopology:
    """The shortlist collection as a many-to-many join of events and venues."""

    def test_one_venue_is_a_candidate_on_two_independent_events_at_once(self):
        """The same venue is linked to two different events through two
        independent junction rows, each with its own rank and its own version.

        This system is a graph, not a tree: a venue and a meeting event are peers joined both through shortlist entries and through solicitation rounds and bids, a solicitation round points back at the closed round it supersedes, and a contract references a meeting event, a bid and a venue at once.
        Design: Corner/entities/graph_topology_junction_entity_links_many_events_to_many_venues
        """
        grid = _junction_grid()

        all_rows, all_meta = validate_paginated(
            api_client.list_shortlist_entries(PLANNER_HEADERS)
        )
        assert all_meta["total_count"] == 4
        assert len({row["id"] for row in all_rows}) == 4

        rows, meta = validate_paginated(
            api_client.list_shortlist_entries(
                PLANNER_HEADERS, {"venue_id": grid["venue_a"]["id"]}
            )
        )
        assert meta["total_count"] == 2
        assert {row["venue_id"] for row in rows} == {grid["venue_a"]["id"]}
        assert {row["event_id"] for row in rows} == {
            grid["event_a"]["id"],
            grid["event_b"]["id"],
        }
        assert {row["id"] for row in rows} == {
            grid["entry_a1"]["id"],
            grid["entry_b1"]["id"],
        }

    def test_one_event_holds_two_venues_at_distinct_ranks(self):
        """Narrowing by the parent event returns that event's own two rows and
        no row belonging to the other event.

        Shortlist entries may be narrowed by `event_id`, by `venue_id` and by `status`.
        Design: Corner/entities/graph_topology_junction_entity_links_many_events_to_many_venues
        """
        grid = _junction_grid()

        rows, meta = validate_paginated(
            api_client.list_shortlist_entries(
                PLANNER_HEADERS, {"event_id": grid["event_a"]["id"]}
            )
        )
        assert meta["total_count"] == 2
        assert {row["event_id"] for row in rows} == {grid["event_a"]["id"]}
        assert {row["venue_id"] for row in rows} == {
            grid["venue_a"]["id"],
            grid["venue_b"]["id"],
        }
        assert sorted(row["rank_seq"] for row in rows) == [1, 2]

        candidate_rows, candidate_meta = validate_paginated(
            api_client.list_shortlist_entries(
                PLANNER_HEADERS,
                {"event_id": grid["event_a"]["id"], "status": "CANDIDATE"},
            )
        )
        assert candidate_meta["total_count"] == 2
        assert all(row["status"] == "CANDIDATE" for row in candidate_rows)
