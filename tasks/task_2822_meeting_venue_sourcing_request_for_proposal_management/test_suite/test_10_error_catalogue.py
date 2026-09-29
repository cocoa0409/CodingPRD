"""The error catalogue of the Meeting Venue Sourcing & RFP Management API.

Every test here drives one documented refusal: the request is built so that
exactly one guard fails, and the response is checked against the error identity
the PRD assigns to that guard.
"""

import pytest

from test_helpers import (
    CLOCK_SOURCING_WINDOW,
    FINANCE_HEADERS,
    NON_EXISTENT_UUID,
    PLANNER_HEADERS,
    PROGRAM_ADMIN_HEADERS,
    ApiErrorId,
    api_client,
    assert_fields_equal,
    assert_integer,
    assert_iso_instant,
    assert_money_field,
    assert_nulls,
    assert_variance_pct,
    make_venue_rep_headers,
    validate_error,
    validate_paginated,
    validate_success,
)
from test_helpers import assertions as domain_assert
from test_helpers import factories, fixtures

# ---------------------------------------------------------------------------
# Module-private payload shapes
# ---------------------------------------------------------------------------

# A TIER_2 venue whose largest space is far below the canonical requirement.
LAKEVIEW_VENUE = {
    "name": "Lakeview Training Centre",
    "city": "Warsaw",
    "country": "PL",
    "destination_tier": "TIER_2",
    "guest_rooms_total": 200,
    "largest_space_sqft": 6000,
    "preferred_supplier_status": "PREFERRED",
}

TRAINING_EVENT = {
    "name": "Regional Trainer Bootcamp 2027",
    "program_type": "TRAINING",
    "start_date": "2027-05-10",
    "end_date": "2027-05-13",
    "peak_attendees": 40,
    "requested_room_nights": 120,
    "largest_meeting_space_sqft": 4500,
    "budget_ceiling_usd": 200000.00,
}

TRAINING_BENCHMARK = {
    "destination_tier": "TIER_2",
    "program_type": "TRAINING",
    "benchmark_adr_usd": 210.00,
    "benchmark_service_charge_pct": 0.22,
    "benchmark_tax_pct": 0.14,
}

TRAINING_GRID = {
    "room_rate_usd": 199.00,
    "rate_type": "NET",
    "commission_pct": 0.00,
    "room_nights_offered": 120,
    "comp_room_ratio": 50,
    "resort_fee_usd_per_night": 0.00,
    "service_charge_pct": 0.22,
    "tax_pct": 0.14,
    "av_estimate_usd": 8000.00,
    "fnb_minimum_usd": 20000.00,
    "concession_credit_usd": 5000.00,
    "attrition_allowance_pct": 0.20,
    "rebooking_credit_pct": 0.50,
}

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

# The twelve addressed resource types, each paired with the not-found code its
# path variable owns.
ADDRESSED_SEGMENTS = [
    ("get_event", ApiErrorId.EVENT_NOT_FOUND),
    ("get_venue", ApiErrorId.VENUE_NOT_FOUND),
    ("get_shortlist_entry", ApiErrorId.SHORTLIST_ENTRY_NOT_FOUND),
    ("get_site_inspection", ApiErrorId.INSPECTION_NOT_FOUND),
    ("get_rfp", ApiErrorId.RFP_NOT_FOUND),
    ("get_proposal", ApiErrorId.PROPOSAL_NOT_FOUND),
    ("get_contract", ApiErrorId.CONTRACT_NOT_FOUND),
    ("get_approval_step", ApiErrorId.APPROVAL_STEP_NOT_FOUND),
    ("get_deposit_installment", ApiErrorId.INSTALLMENT_NOT_FOUND),
    ("get_rate_benchmark", ApiErrorId.BENCHMARK_NOT_FOUND),
    ("get_post_event_report", ApiErrorId.REPORT_NOT_FOUND),
    ("get_performance_review", ApiErrorId.REVIEW_NOT_FOUND),
]


class TestAddressedSegmentNotFoundCodes:
    """Each addressed resource type owns its own 404."""

    @pytest.mark.parametrize(
        "reader_name,error_id",
        ADDRESSED_SEGMENTS,
        ids=[name for name, _ in ADDRESSED_SEGMENTS],
    )
    def test_unknown_identifier_reports_that_segment_s_not_found_code(
        self, reader_name, error_id
    ):
        """Identifiers embedded in a path are resolved strictly left to right, and the first segment that fails to resolve determines the error: the request is rejected immediately with the 404 that belongs to that segment's resource type, without attempting to resolve anything to its right and without running any business rule.

        Design: Corner/errors/every_addressed_path_segment_has_its_own_not_found_code
        """
        fixtures.set_clock(CLOCK_SOURCING_WINDOW)

        response = getattr(api_client, reader_name)(NON_EXISTENT_UUID, PLANNER_HEADERS)
        error = validate_error(response, error_id.value)

        assert response.status_code == 404
        assert response.json()["response_type"] == "error"
        assert error["message"].strip() != ""


@pytest.fixture
def published_benchmark():
    """One published benchmark for the TIER_1 / USER_CONFERENCE pair."""
    fixtures.set_clock(CLOCK_SOURCING_WINDOW)
    return fixtures.create_benchmark()


class TestRateBenchmarkPairUniqueness:
    """POST /sourcing/rate-benchmarks."""

    def test_republishing_the_same_tier_and_programme_pair_is_refused(
        self, published_benchmark
    ):
        """The tier-and-programme pair is unique: publishing a second benchmark for a pair that already has one is rejected with `ERR_BENCHMARK_DUPLICATE`.

        Design: Corner/errors/rate_benchmark_pair_is_unique_but_only_as_a_pair
        """
        response = api_client.create_rate_benchmark(
            factories.rate_benchmark_payload(benchmark_adr_usd=305.00),
            PROGRAM_ADMIN_HEADERS,
        )
        validate_error(response, ApiErrorId.BENCHMARK_DUPLICATE.value)

        original = validate_success(
            api_client.get_rate_benchmark(published_benchmark["id"], PLANNER_HEADERS), 200
        )
        assert_money_field(original, "benchmark_adr_usd", 260.00)

    def test_same_tier_with_a_different_programme_is_a_separate_pair(
        self, published_benchmark
    ):
        """A `ProgramAdmin` publishes one benchmark per pair of `destination_tier` and `program_type`, where `program_type` is one of `BOARD_MEETING`, `SALES_KICKOFF`, `TRAINING`, `USER_CONFERENCE` or `INCENTIVE`.

        Design: Corner/errors/rate_benchmark_pair_is_unique_but_only_as_a_pair
        """
        response = api_client.create_rate_benchmark(
            factories.rate_benchmark_payload(
                program_type="TRAINING", benchmark_adr_usd=225.00
            ),
            PROGRAM_ADMIN_HEADERS,
        )
        validate_success(response, 201)

        rows, meta = validate_paginated(
            api_client.list_rate_benchmarks(PLANNER_HEADERS, {"destination_tier": "TIER_1"})
        )
        assert len(rows) == 2
        assert meta["total_count"] == 2


@pytest.fixture
def shortlist_guard_world():
    """A locked requirement holding one candidate, plus two further venues: one
    large enough to be shortlisted and one that is not."""
    world = fixtures.build_sourcing_world(promote=False)
    world["venue_b"] = fixtures.create_second_venue()
    world["venue_b_id"] = world["venue_b"]["id"]
    world["venue_c"] = fixtures.create_venue(**LAKEVIEW_VENUE)
    world["venue_c_id"] = world["venue_c"]["id"]
    return world


class TestShortlistEntryCreationGuards:
    """POST /sourcing/events/{event_id}/shortlist-entries."""

    def test_repeating_the_same_event_and_venue_pair_is_refused(
        self, shortlist_guard_world
    ):
        """Three guards fire on creation, in the order given in section 2.8: a repeat of the same event-and-venue pair, or a `rank_seq` already taken inside the event, is rejected with `ERR_VENUE_ALREADY_SHORTLISTED`; a venue whose `preferred_supplier_status` is `SUSPENDED` is rejected with `ERR_VENUE_SUSPENDED`; and a venue whose `largest_space_sqft` is smaller than the event's `largest_meeting_space_sqft` is rejected with `ERR_VENUE_SPACE_INSUFFICIENT`.

        Design: Corner/errors/shortlist_entry_creation_guards_pair_uniqueness_rank_and_space
        """
        world = shortlist_guard_world
        response = api_client.create_shortlist_entry(
            world["event_id"],
            factories.shortlist_entry_payload(world["venue_id"], rank_seq=2),
            PLANNER_HEADERS,
        )
        validate_error(response, ApiErrorId.VENUE_ALREADY_SHORTLISTED.value)

    def test_reusing_a_rank_already_taken_inside_the_event_is_refused(
        self, shortlist_guard_world
    ):
        """Three guards fire on creation, in the order given in section 2.8: a repeat of the same event-and-venue pair, or a `rank_seq` already taken inside the event, is rejected with `ERR_VENUE_ALREADY_SHORTLISTED`; a venue whose `preferred_supplier_status` is `SUSPENDED` is rejected with `ERR_VENUE_SUSPENDED`; and a venue whose `largest_space_sqft` is smaller than the event's `largest_meeting_space_sqft` is rejected with `ERR_VENUE_SPACE_INSUFFICIENT`.

        Design: Corner/errors/shortlist_entry_creation_guards_pair_uniqueness_rank_and_space
        """
        world = shortlist_guard_world
        response = api_client.create_shortlist_entry(
            world["event_id"],
            factories.shortlist_entry_payload(world["venue_b_id"], rank_seq=1),
            PLANNER_HEADERS,
        )
        validate_error(response, ApiErrorId.VENUE_ALREADY_SHORTLISTED.value)

    def test_venue_smaller_than_the_required_meeting_space_is_refused(
        self, shortlist_guard_world
    ):
        """Three guards fire on creation, in the order given in section 2.8: a repeat of the same event-and-venue pair, or a `rank_seq` already taken inside the event, is rejected with `ERR_VENUE_ALREADY_SHORTLISTED`; a venue whose `preferred_supplier_status` is `SUSPENDED` is rejected with `ERR_VENUE_SUSPENDED`; and a venue whose `largest_space_sqft` is smaller than the event's `largest_meeting_space_sqft` is rejected with `ERR_VENUE_SPACE_INSUFFICIENT`.

        Design: Corner/errors/shortlist_entry_creation_guards_pair_uniqueness_rank_and_space
        """
        world = shortlist_guard_world
        response = api_client.create_shortlist_entry(
            world["event_id"],
            factories.shortlist_entry_payload(world["venue_c_id"], rank_seq=3),
            PLANNER_HEADERS,
        )
        validate_error(response, ApiErrorId.VENUE_SPACE_INSUFFICIENT.value)

    def test_a_free_rank_for_a_large_enough_venue_is_still_accepted(
        self, shortlist_guard_world
    ):
        """The planner adds a candidate by naming a `venue_id` and an explicit `rank_seq`, the planner-assigned shortlist ordering in which 1 is the highest preference; `rank_seq` must be at least 1 and must be unused within the event.

        Design: Corner/errors/shortlist_entry_creation_guards_pair_uniqueness_rank_and_space
        """
        world = shortlist_guard_world
        for payload in (
            factories.shortlist_entry_payload(world["venue_id"], rank_seq=2),
            factories.shortlist_entry_payload(world["venue_b_id"], rank_seq=1),
            factories.shortlist_entry_payload(world["venue_c_id"], rank_seq=3),
        ):
            assert (
                api_client.create_shortlist_entry(
                    world["event_id"], payload, PLANNER_HEADERS
                ).status_code
                != 201
            )

        rows, meta = validate_paginated(
            api_client.list_shortlist_entries(
                PLANNER_HEADERS, {"event_id": world["event_id"]}
            )
        )
        assert len(rows) == 1
        assert meta["total_count"] == 1

        entry_b = validate_success(
            api_client.create_shortlist_entry(
                world["event_id"],
                factories.shortlist_entry_payload(world["venue_b_id"], rank_seq=2),
                PLANNER_HEADERS,
            ),
            201,
        )
        assert_integer(entry_b["rank_seq"], 2, "rank_seq")

        rows, meta = validate_paginated(
            api_client.list_shortlist_entries(
                PLANNER_HEADERS, {"event_id": world["event_id"]}
            )
        )
        assert len(rows) == 2
        assert meta["total_count"] == 2


@pytest.fixture
def draft_round_world():
    """A shortlisted requirement with round 1 drafted but not yet issued."""
    world = fixtures.build_sourcing_world()
    world["rfp"] = fixtures.create_rfp(world["event_id"])
    world["rfp_id"] = world["rfp"]["id"]
    return world


class TestSolicitationRoundNumbering:
    """POST /sourcing/events/{event_id}/rfps."""

    def test_reusing_a_round_number_on_the_same_event_is_refused(
        self, draft_round_world
    ):
        """A `round_number` already used by another round of the same event is rejected with `ERR_RFP_ROUND_DUPLICATE`.

        Design: Corner/errors/rfp_round_numbering_guards_duplicate_and_previous_round_state
        """
        world = draft_round_world
        response = api_client.create_rfp(
            world["event_id"], factories.rfp_payload(round_number=1), PLANNER_HEADERS
        )
        validate_error(response, ApiErrorId.RFP_ROUND_DUPLICATE.value)

    def test_later_round_without_a_chain_to_its_predecessor_is_refused(
        self, draft_round_world
    ):
        """The chaining rule is strict in both directions: when `round_number` is greater than 1, `previous_rfp_id` must be supplied, must reference a round belonging to the same event, and that referenced round's `status` must be `CLOSED`; when `round_number` is exactly 1, `previous_rfp_id` must be absent.

        Design: Corner/errors/rfp_round_numbering_guards_duplicate_and_previous_round_state
        """
        world = draft_round_world
        response = api_client.create_rfp(
            world["event_id"],
            factories.rfp_payload(
                round_number=2, response_due_at="2026-10-15T17:00:00.000Z"
            ),
            PLANNER_HEADERS,
        )
        validate_error(response, ApiErrorId.PREVIOUS_ROUND_NOT_CLOSED.value)

    def test_later_round_chained_to_a_round_that_is_not_closed_is_refused(
        self, draft_round_world
    ):
        """Any violation of either direction — an omitted chain on a later round, a chain to another event's round, a chain to a round that is not yet `CLOSED`, or a chain supplied on round 1 — is rejected with `ERR_PREVIOUS_ROUND_NOT_CLOSED`.

        Design: Corner/errors/rfp_round_numbering_guards_duplicate_and_previous_round_state
        """
        world = draft_round_world
        response = api_client.create_rfp(
            world["event_id"],
            factories.rfp_payload(
                round_number=2,
                response_due_at="2026-10-15T17:00:00.000Z",
                previous_rfp_id=world["rfp_id"],
            ),
            PLANNER_HEADERS,
        )
        validate_error(response, ApiErrorId.PREVIOUS_ROUND_NOT_CLOSED.value)

        rows, meta = validate_paginated(
            api_client.list_rfps(PLANNER_HEADERS, {"event_id": world["event_id"]})
        )
        assert len(rows) == 1
        assert meta["total_count"] == 1

    def test_later_round_chained_to_the_closed_predecessor_is_accepted(
        self, draft_round_world
    ):
        """A drafted round lands in `DRAFT` with `invited_count` at 0, `submitted_count` at 0, `issued_at` null and `closed_at` null.

        Design: Corner/errors/rfp_round_numbering_guards_duplicate_and_previous_round_state
        """
        world = draft_round_world
        fixtures.issue_rfp(world["rfp_id"])
        closed = fixtures.close_rfp(world["rfp_id"])
        assert closed["status"] == "CLOSED"
        assert fixtures.read_event(world["event_id"])["status"] == "BID_REVIEW"

        round_two = validate_success(
            api_client.create_rfp(
                world["event_id"],
                factories.rfp_payload(
                    round_number=2,
                    response_due_at="2026-10-15T17:00:00.000Z",
                    previous_rfp_id=world["rfp_id"],
                ),
                PLANNER_HEADERS,
            ),
            201,
        )
        assert_fields_equal(
            round_two,
            {
                "round_number": 2,
                "previous_rfp_id": world["rfp_id"],
                "status": "DRAFT",
                "invited_count": 0,
                "submitted_count": 0,
            },
        )


class TestSolicitationRoundStateGuards:
    """POST /sourcing/rfps/{rfp_id}/issue and /close."""

    def test_closing_a_round_before_it_was_issued_is_refused(self, draft_round_world):
        """It requires the round to be in `ISSUED`, rejecting anything else with `ERR_RFP_STATE_INVALID`.

        Design: Corner/errors/rfp_state_invalid_on_close_before_issue_and_on_repeated_triggers
        """
        world = draft_round_world
        response = api_client.close_rfp(world["rfp_id"], PLANNER_HEADERS)
        validate_error(response, ApiErrorId.RFP_STATE_INVALID.value)

        rfp = fixtures.read_rfp(world["rfp_id"])
        assert rfp["status"] == "DRAFT"
        assert_nulls(rfp, ["closed_at"])

    def test_issuing_an_already_issued_round_is_refused(self, draft_round_world):
        """It requires the round to be in `DRAFT` — anything else is `ERR_RFP_STATE_INVALID` — the parent event to be in `REQUIREMENTS_LOCKED` or `BID_REVIEW`, at least one entry of the event to be in `SHORTLISTED`, `INSPECTION_SCHEDULED` or `INSPECTED` (otherwise `ERR_NO_SHORTLISTED_VENUES`, because a solicitation to an empty invitee set is meaningless), every one of those eligible entries flagged `inspection_required` to have reached `INSPECTED` (otherwise `ERR_INSPECTION_INCOMPLETE`), and `response_due_at` to still lie strictly after the current logical clock (otherwise `ERR_RESPONSE_DUE_OUT_OF_RANGE`, since a round drafted days ago may have gone stale).

        Design: Corner/errors/rfp_state_invalid_on_close_before_issue_and_on_repeated_triggers
        """
        world = draft_round_world
        issued = fixtures.issue_rfp(world["rfp_id"])
        assert issued["status"] == "ISSUED"
        assert_integer(issued["invited_count"], 1, "invited_count")

        response = api_client.issue_rfp(world["rfp_id"], PLANNER_HEADERS)
        validate_error(response, ApiErrorId.RFP_STATE_INVALID.value)

        assert_integer(
            fixtures.read_rfp(world["rfp_id"])["invited_count"], 1, "invited_count"
        )
        rows, meta = validate_paginated(
            api_client.list_proposals(PLANNER_HEADERS, {"rfp_id": world["rfp_id"]})
        )
        assert len(rows) == 1
        assert meta["total_count"] == 1

    def test_closing_an_already_closed_round_is_refused(self, draft_round_world):
        """`closed_at` is stamped from the logical clock, the round moves `ISSUED → CLOSED`, and every bid of that round still sitting in `INVITED` moves `INVITED → EXPIRED` — a venue that never answered is expired rather than declined, and expiry mutates nothing else.

        Design: Corner/errors/rfp_state_invalid_on_close_before_issue_and_on_repeated_triggers
        """
        world = draft_round_world
        fixtures.issue_rfp(world["rfp_id"])
        closed = fixtures.close_rfp(world["rfp_id"])
        assert closed["status"] == "CLOSED"
        assert closed["closed_at"] == CLOCK_SOURCING_WINDOW

        response = api_client.close_rfp(world["rfp_id"], PLANNER_HEADERS)
        validate_error(response, ApiErrorId.RFP_STATE_INVALID.value)

        assert fixtures.read_rfp(world["rfp_id"])["closed_at"] == CLOCK_SOURCING_WINDOW


@pytest.fixture
def training_round():
    """A TIER_2 venue invited to a TRAINING requirement, for which no benchmark
    pair has been published."""
    return fixtures.build_issued_round(
        venue_overrides=LAKEVIEW_VENUE, event_overrides=TRAINING_EVENT
    )


class TestBenchmarkPrerequisiteForSubmission:
    """POST /sourcing/proposals/{proposal_id}/submit."""

    def test_submission_without_a_benchmark_for_the_pair_is_refused(
        self, training_round
    ):
        """And a rate benchmark must exist for the pairing of the bidding venue's `destination_tier` with the meeting event's `program_type`, otherwise `ERR_BENCHMARK_NOT_CONFIGURED`.

        Design: Corner/errors/submit_without_a_benchmark_for_the_tier_and_program_pair_is_refused
        """
        world = training_round
        response = api_client.submit_proposal(
            world["proposal_id"],
            factories.proposal_submission_payload(**TRAINING_GRID),
            make_venue_rep_headers(world["venue_id"]),
        )
        validate_error(response, ApiErrorId.BENCHMARK_NOT_CONFIGURED.value)

        proposal = fixtures.read_proposal(world["proposal_id"])
        assert proposal["status"] == "INVITED"
        assert proposal["compliance_status"] == "NOT_EVALUATED"
        assert_nulls(proposal, ["net_adr_usd", "total_cost_contracted_usd"])
        assert_integer(
            fixtures.read_rfp(world["rfp_id"])["submitted_count"], 0, "submitted_count"
        )

    def test_submission_is_accepted_once_the_pair_has_a_benchmark(self, training_round):
        """The server then computes `net_adr_usd`, `comp_room_nights`, `paid_room_nights` and `total_cost_contracted_usd` from the contracted-basis total cost model below, computes `benchmark_variance_pct` and `compliance_status` from the rate-benchmark rules below, increases the parent round's `submitted_count` by 1, recomputes the event's `best_total_cost_usd` and advances the event's `version` by 1.

        Design: Corner/errors/submit_without_a_benchmark_for_the_tier_and_program_pair_is_refused
        """
        world = training_round
        validate_success(
            api_client.create_rate_benchmark(
                factories.rate_benchmark_payload(**TRAINING_BENCHMARK),
                PROGRAM_ADMIN_HEADERS,
            ),
            201,
        )

        response = api_client.submit_proposal(
            world["proposal_id"],
            factories.proposal_submission_payload(**TRAINING_GRID),
            make_venue_rep_headers(world["venue_id"]),
        )
        proposal = validate_success(response, 200)

        assert proposal["status"] == "SUBMITTED"
        assert_integer(proposal["comp_room_nights"], 2, "comp_room_nights")
        assert_integer(proposal["paid_room_nights"], 118, "paid_room_nights")
        assert_money_field(proposal, "net_adr_usd", 199.00)
        assert_money_field(proposal, "total_cost_contracted_usd", 69722.61)
        assert_variance_pct(proposal["benchmark_variance_pct"], -0.0524)
        assert proposal["compliance_status"] == "COMPLIANT"

        event = fixtures.read_event(world["event_id"])
        assert_money_field(event, "best_total_cost_usd", 69722.61)


@pytest.fixture
def inspection_required_world():
    """A shortlisted entry whose venue must be inspected before it may be invited."""
    return fixtures.build_sourcing_world(entry_overrides={"inspection_required": True})


class TestSiteInspectionWindowAndCompletion:
    """POST /sourcing/site-inspections and its complete / cancel triggers."""

    def test_zero_length_window_is_refused_and_creates_nothing(
        self, inspection_required_world
    ):
        """`window_end` must be strictly after `window_start`; an equal or inverted window is rejected with `ERR_INVALID_INSPECTION_WINDOW`.

        Design: Corner/errors/inspection_window_shape_and_completion_state_are_both_guarded
        """
        world = inspection_required_world
        response = api_client.create_site_inspection(
            factories.site_inspection_payload(
                world["entry_id"],
                window_start="2026-09-10T13:00:00.000Z",
                window_end="2026-09-10T13:00:00.000Z",
            ),
            PLANNER_HEADERS,
        )
        validate_error(response, ApiErrorId.INVALID_INSPECTION_WINDOW.value)

        rows, meta = validate_paginated(
            api_client.list_site_inspections(
                PLANNER_HEADERS, {"shortlist_entry_id": world["entry_id"]}
            )
        )
        assert rows == []
        assert meta["total_count"] == 0

    def test_a_forward_window_is_planned_with_its_buffered_occupation_end(
        self, inspection_required_world
    ):
        """From those inputs the server derives `occupied_until` as `window_end` advanced by `travel_buffer_minutes`, and treats the half-open interval from `window_start` up to but not including `occupied_until` as the venue's buffered occupation interval.

        Design: Corner/errors/inspection_window_shape_and_completion_state_are_both_guarded
        """
        world = inspection_required_world
        response = api_client.create_site_inspection(
            factories.site_inspection_payload(world["entry_id"]), PLANNER_HEADERS
        )
        inspection = validate_success(response, 201)

        assert_fields_equal(
            inspection,
            {
                "status": "PLANNED",
                "venue_id": world["venue_id"],
                "travel_buffer_minutes": 90,
                "occupied_until": "2026-09-10T14:30:00.000Z",
            },
        )
        assert_iso_instant(inspection["occupied_until"], "occupied_until")

    def test_completion_before_the_window_has_elapsed_is_refused(
        self, inspection_required_world
    ):
        """It requires the inspection to be in `PLANNED` **and** the current logical clock to be at or after the inspection's `window_end` — a completion attempted while the clock is still short of `window_end` is rejected with `ERR_INSPECTION_STATE_INVALID`, the same code an attempt on an already-completed or already-cancelled inspection receives.

        Design: Corner/errors/inspection_window_shape_and_completion_state_are_both_guarded
        """
        world = inspection_required_world
        inspection = fixtures.plan_inspection(world["entry_id"])

        response = api_client.complete_site_inspection(
            inspection["id"], factories.complete_inspection_payload(), PLANNER_HEADERS
        )
        validate_error(response, ApiErrorId.INSPECTION_STATE_INVALID.value)

        stored = fixtures.read_inspection(inspection["id"])
        assert stored["status"] == "PLANNED"
        assert_nulls(stored, ["findings_score"])

    def test_completing_an_already_completed_inspection_is_refused(
        self, inspection_required_world
    ):
        """The inspection moves `PLANNED → COMPLETED` and the parent entry moves `INSPECTION_SCHEDULED → INSPECTED`, with the entry's `version` advancing by 1.

        Design: Corner/errors/inspection_window_shape_and_completion_state_are_both_guarded
        """
        world = inspection_required_world
        inspection = fixtures.plan_inspection(world["entry_id"])
        fixtures.set_clock("2026-09-10T13:00:00.000Z")

        completed = fixtures.complete_inspection(inspection["id"])
        assert completed["status"] == "COMPLETED"
        assert_integer(completed["findings_score"], 4, "findings_score")
        assert fixtures.read_entry(world["entry_id"])["status"] == "INSPECTED"

        response = api_client.complete_site_inspection(
            inspection["id"],
            factories.complete_inspection_payload(findings_score=5),
            PLANNER_HEADERS,
        )
        validate_error(response, ApiErrorId.INSPECTION_STATE_INVALID.value)

        assert_integer(
            fixtures.read_inspection(inspection["id"])["findings_score"],
            4,
            "findings_score",
        )

    def test_cancelling_a_completed_inspection_is_refused(
        self, inspection_required_world
    ):
        """It requires the inspection to be in `PLANNED`, rejecting anything else with `ERR_INSPECTION_STATE_INVALID`, and the caller supplies `cancel_reason`, which is persisted.

        Design: Corner/errors/inspection_window_shape_and_completion_state_are_both_guarded
        """
        world = inspection_required_world
        inspection = fixtures.plan_inspection(world["entry_id"])
        fixtures.set_clock("2026-09-10T13:00:00.000Z")
        fixtures.complete_inspection(inspection["id"])

        response = api_client.cancel_site_inspection(
            inspection["id"], factories.cancel_inspection_payload(), PLANNER_HEADERS
        )
        validate_error(response, ApiErrorId.INSPECTION_STATE_INVALID.value)

        assert_nulls(fixtures.read_inspection(inspection["id"]), ["cancel_reason"])


@pytest.fixture
def inspection_gated_draft_round():
    """Round 1 drafted against a single shortlisted entry that must be inspected."""
    world = fixtures.build_sourcing_world(entry_overrides={"inspection_required": True})
    world["rfp"] = fixtures.create_rfp(world["event_id"])
    world["rfp_id"] = world["rfp"]["id"]
    return world


class TestIssueBlockedByRequiredInspection:
    """POST /sourcing/rfps/{rfp_id}/issue."""

    def test_issue_is_blocked_while_the_required_inspection_is_unplanned(
        self, inspection_gated_draft_round
    ):
        """Note carefully that the eligible set is defined by the three statuses above and is **not** narrowed by `inspection_required`: an entry flagged as requiring inspection does not quietly drop out of the invitee list, it blocks the entire issue until it has been inspected.

        Design: Corner/errors/rfp_issue_is_blocked_until_every_required_inspection_is_completed
        """
        world = inspection_gated_draft_round
        response = api_client.issue_rfp(world["rfp_id"], PLANNER_HEADERS)
        validate_error(response, ApiErrorId.INSPECTION_INCOMPLETE.value)

        rfp = fixtures.read_rfp(world["rfp_id"])
        assert rfp["status"] == "DRAFT"
        assert_integer(rfp["invited_count"], 0, "invited_count")

    def test_issue_is_still_blocked_while_the_inspection_is_only_planned(
        self, inspection_gated_draft_round
    ):
        """Note carefully that the eligible set is defined by the three statuses above and is **not** narrowed by `inspection_required`: an entry flagged as requiring inspection does not quietly drop out of the invitee list, it blocks the entire issue until it has been inspected.

        Design: Corner/errors/rfp_issue_is_blocked_until_every_required_inspection_is_completed
        """
        world = inspection_gated_draft_round
        fixtures.plan_inspection(
            world["entry_id"],
            window_start="2026-08-06T09:00:00.000Z",
            window_end="2026-08-06T13:00:00.000Z",
        )
        assert fixtures.read_entry(world["entry_id"])["status"] == "INSPECTION_SCHEDULED"

        response = api_client.issue_rfp(world["rfp_id"], PLANNER_HEADERS)
        validate_error(response, ApiErrorId.INSPECTION_INCOMPLETE.value)

        assert fixtures.read_rfp(world["rfp_id"])["status"] == "DRAFT"

    def test_issue_succeeds_once_the_required_inspection_is_completed(
        self, inspection_gated_draft_round
    ):
        """One bid is created in `INVITED` for each eligible entry, processed in ascending `rank_seq` order so the highest-preference venue's bid is created first, each copying `venue_id` from its source entry; `invited_count` is set to the number of bids created.

        Design: Corner/errors/rfp_issue_is_blocked_until_every_required_inspection_is_completed
        """
        world = inspection_gated_draft_round
        inspection = fixtures.plan_inspection(
            world["entry_id"],
            window_start="2026-08-06T09:00:00.000Z",
            window_end="2026-08-06T13:00:00.000Z",
        )
        fixtures.set_clock("2026-08-06T13:00:00.000Z")
        fixtures.complete_inspection(inspection["id"], findings_score=5)
        assert fixtures.read_entry(world["entry_id"])["status"] == "INSPECTED"

        issued = validate_success(
            api_client.issue_rfp(world["rfp_id"], PLANNER_HEADERS), 200
        )
        assert issued["status"] == "ISSUED"
        assert_integer(issued["invited_count"], 1, "invited_count")

        assert fixtures.read_entry(world["entry_id"])["status"] == "RFP_ISSUED"
        assert fixtures.read_event(world["event_id"])["status"] == "SOURCING"

        proposal = fixtures.find_invited_proposal(world["rfp_id"], world["venue_id"])
        assert proposal["status"] == "INVITED"
        assert proposal["venue_id"] == world["venue_id"]


@pytest.fixture
def non_compliant_evaluated_bid():
    """A closed round whose single bid is priced fifteen percent over benchmark."""
    return fixtures.build_evaluated_bid(
        close_round=True, bid_overrides={"room_rate_usd": 299.00}
    )


class TestNonCompliantAwardRefusal:
    """POST /sourcing/events/{event_id}/award."""

    def test_bid_above_the_programme_premium_is_graded_non_compliant(
        self, non_compliant_evaluated_bid
    ):
        """When the venue's `preferred_supplier_status` is `PREFERRED` or `CONDITIONAL`, a variance at or below `0.0000` earns `COMPLIANT`; a variance above `0.0000` but at or below the maximum programme premium of `0.1000` — ten percent over benchmark — earns `COMPLIANT_WITH_VARIANCE`; and a variance above `0.1000` earns `NON_COMPLIANT`.

        Design: Corner/errors/award_of_a_non_compliant_bid_is_refused_even_inside_the_budget
        """
        proposal = fixtures.read_proposal(non_compliant_evaluated_bid["proposal_id"])

        assert_money_field(proposal, "net_adr_usd", 299.00)
        assert_integer(proposal["paid_room_nights"], 587, "paid_room_nights")
        assert_money_field(proposal, "total_cost_contracted_usd", 487568.31)
        assert_variance_pct(proposal["benchmark_variance_pct"], 0.1500)
        assert proposal["compliance_status"] == "NON_COMPLIANT"

    def test_awarding_a_non_compliant_bid_is_refused(self, non_compliant_evaluated_bid):
        """The winning bid's `compliance_status` must not be `NON_COMPLIANT`, otherwise `ERR_RATE_BENCHMARK_NON_COMPLIANT`; `COMPLIANT` and `ABOVE_BENCHMARK` are both awardable.

        Design: Corner/errors/award_of_a_non_compliant_bid_is_refused_even_inside_the_budget
        """
        world = non_compliant_evaluated_bid
        response = api_client.award_event(
            world["event_id"],
            factories.award_payload(
                world["proposal_id"], fixtures.event_version(world["event_id"])
            ),
            PLANNER_HEADERS,
        )
        validate_error(response, ApiErrorId.RATE_BENCHMARK_NON_COMPLIANT.value)

        rows, meta = validate_paginated(
            api_client.list_contracts(PLANNER_HEADERS, {"event_id": world["event_id"]})
        )
        assert rows == []
        assert meta["total_count"] == 0

        event = fixtures.read_event(world["event_id"])
        assert event["status"] == "BID_REVIEW"
        assert_nulls(event, ["awarded_proposal_id"])
        assert_money_field(event, "committed_spend_usd", 0.00)
        domain_assert.assert_budget_envelope(event)

        assert (
            fixtures.read_proposal(world["proposal_id"])["status"] == "UNDER_REVIEW"
        )


@pytest.fixture
def executed_world():
    """An executed contract on the canonical bid, with the event in CONTRACTED."""
    return fixtures.build_executed_contract()


class TestPostEventReportGates:
    """POST /sourcing/events/{event_id}/post-event-report."""

    def test_report_filed_long_before_the_meeting_is_refused(self, executed_world):
        """Five guards apply in ladder order: the event must be in `CONTRACTED`, otherwise `ERR_EVENT_STATE_INVALID`; the current logical clock must be strictly after the event's `end_date` at `23:59:59.999Z`, otherwise `ERR_EVENT_NOT_CONCLUDED`, since actuals cannot be reported while the meeting is still running; no report may already exist for the event, otherwise `ERR_POST_EVENT_REPORT_EXISTS`, and this is the error an event in `COMPLETED` reports as described in section 2.8; a rate benchmark must exist for the venue's `destination_tier` paired with the event's `program_type`, otherwise `ERR_BENCHMARK_NOT_CONFIGURED`, because the savings figures are measured against it; and `actual_room_nights` must be at most the contract's `contracted_paid_room_nights`, otherwise `ERR_ACTUALS_EXCEED_CONTRACT`, since the group cannot consume more paid nights than were contracted.

        Design: Corner/errors/post_event_report_is_gated_on_the_clock_the_actuals_and_uniqueness
        """
        world = executed_world
        response = api_client.create_post_event_report(
            world["event_id"],
            factories.post_event_report_payload(
                actual_room_nights=587, actual_fnb_usd=132000.00, actual_av_usd=19500.00
            ),
            PLANNER_HEADERS,
        )
        validate_error(response, ApiErrorId.EVENT_NOT_CONCLUDED.value)

    def test_report_on_the_last_millisecond_of_the_departure_day_is_refused(
        self, executed_world
    ):
        """Five guards apply in ladder order: the event must be in `CONTRACTED`, otherwise `ERR_EVENT_STATE_INVALID`; the current logical clock must be strictly after the event's `end_date` at `23:59:59.999Z`, otherwise `ERR_EVENT_NOT_CONCLUDED`, since actuals cannot be reported while the meeting is still running; no report may already exist for the event, otherwise `ERR_POST_EVENT_REPORT_EXISTS`, and this is the error an event in `COMPLETED` reports as described in section 2.8; a rate benchmark must exist for the venue's `destination_tier` paired with the event's `program_type`, otherwise `ERR_BENCHMARK_NOT_CONFIGURED`, because the savings figures are measured against it; and `actual_room_nights` must be at most the contract's `contracted_paid_room_nights`, otherwise `ERR_ACTUALS_EXCEED_CONTRACT`, since the group cannot consume more paid nights than were contracted.

        Design: Corner/errors/post_event_report_is_gated_on_the_clock_the_actuals_and_uniqueness
        """
        world = executed_world
        fixtures.set_clock("2027-03-18T23:59:59.999Z")

        response = api_client.create_post_event_report(
            world["event_id"],
            factories.post_event_report_payload(
                actual_room_nights=587, actual_fnb_usd=132000.00, actual_av_usd=19500.00
            ),
            PLANNER_HEADERS,
        )
        validate_error(response, ApiErrorId.EVENT_NOT_CONCLUDED.value)

    def test_actuals_above_the_contracted_paid_nights_are_refused(self, executed_world):
        """Five guards apply in ladder order: the event must be in `CONTRACTED`, otherwise `ERR_EVENT_STATE_INVALID`; the current logical clock must be strictly after the event's `end_date` at `23:59:59.999Z`, otherwise `ERR_EVENT_NOT_CONCLUDED`, since actuals cannot be reported while the meeting is still running; no report may already exist for the event, otherwise `ERR_POST_EVENT_REPORT_EXISTS`, and this is the error an event in `COMPLETED` reports as described in section 2.8; a rate benchmark must exist for the venue's `destination_tier` paired with the event's `program_type`, otherwise `ERR_BENCHMARK_NOT_CONFIGURED`, because the savings figures are measured against it; and `actual_room_nights` must be at most the contract's `contracted_paid_room_nights`, otherwise `ERR_ACTUALS_EXCEED_CONTRACT`, since the group cannot consume more paid nights than were contracted.

        Design: Corner/errors/post_event_report_is_gated_on_the_clock_the_actuals_and_uniqueness
        """
        world = executed_world
        contract = fixtures.read_contract(world["contract_id"])
        assert_integer(
            contract["contracted_paid_room_nights"], 587, "contracted_paid_room_nights"
        )
        assert_money_field(contract, "concession_applied_usd", 11693.04)

        fixtures.set_clock("2027-03-19T00:00:00.000Z")
        response = api_client.create_post_event_report(
            world["event_id"],
            factories.post_event_report_payload(
                actual_room_nights=588, actual_fnb_usd=132000.00, actual_av_usd=19500.00
            ),
            PLANNER_HEADERS,
        )
        validate_error(response, ApiErrorId.ACTUALS_EXCEED_CONTRACT.value)

        rows, meta = validate_paginated(
            api_client.list_post_event_reports(
                PLANNER_HEADERS, {"event_id": world["event_id"]}
            )
        )
        assert rows == []
        assert meta["total_count"] == 0
        assert fixtures.read_event(world["event_id"])["status"] == "CONTRACTED"

    def test_actuals_at_the_contracted_ceiling_close_the_event(self, executed_world):
        """`realized_total_usd` is the sum of `actual_room_cost_usd`, the realized resort fee, `actual_fnb_usd`, `actual_av_usd`, `realized_service_charge_usd`, `realized_tax_usd` and `attrition_charge_usd`, minus the contract's `concession_applied_usd`, rounded to 2 decimal places.

        Filing the report then moves the event `CONTRACTED → COMPLETED`, sets its `savings_recognized_usd` to the report's `savings_vs_budget_usd`, sets its `committed_spend_usd` to `realized_total_usd` with `budget_remaining_usd` recomputed so the money identity still holds against actuals rather than against the contracted estimate, decreases the venue's `blocked_room_nights` by the contract's `contracted_paid_room_nights` since the rooms have now been consumed, and advances the event's `version` by 1.

        Design: Corner/errors/post_event_report_is_gated_on_the_clock_the_actuals_and_uniqueness
        """
        world = executed_world
        fixtures.set_clock("2027-03-19T00:00:00.000Z")

        report = validate_success(
            api_client.create_post_event_report(
                world["event_id"],
                factories.post_event_report_payload(
                    actual_room_nights=587,
                    actual_fnb_usd=132000.00,
                    actual_av_usd=19500.00,
                ),
                PLANNER_HEADERS,
            ),
            201,
        )

        assert report["contract_id"] == world["contract_id"]
        assert_integer(
            report["attrition_allowed_nights"], 469, "attrition_allowed_nights"
        )
        assert_integer(
            report["attrition_shortfall_nights"], 0, "attrition_shortfall_nights"
        )
        assert_money_field(report, "attrition_charge_usd", 0.00)
        assert_money_field(report, "actual_room_cost_usd", 146163.00)
        assert_money_field(report, "realized_service_charge_usd", 71439.12)
        assert_money_field(report, "realized_tax_usd", 59228.23)
        assert_money_field(report, "realized_total_usd", 427203.31)
        assert_money_field(report, "benchmark_room_cost_usd", 152620.00)
        assert_money_field(report, "savings_vs_benchmark_usd", 6457.00)
        assert_money_field(report, "savings_vs_budget_usd", 72796.69)

        event = fixtures.read_event(world["event_id"])
        assert event["status"] == "COMPLETED"
        assert_money_field(event, "savings_recognized_usd", 72796.69)
        assert_money_field(event, "committed_spend_usd", 427203.31)
        assert_money_field(event, "budget_remaining_usd", 72796.69)
        domain_assert.assert_budget_envelope(event)

        domain_assert.assert_room_night_inventory(
            fixtures.read_venue(world["venue_id"]), 0
        )

    def test_a_second_report_for_the_same_event_is_refused(self, executed_world):
        """Five guards apply in ladder order: the event must be in `CONTRACTED`, otherwise `ERR_EVENT_STATE_INVALID`; the current logical clock must be strictly after the event's `end_date` at `23:59:59.999Z`, otherwise `ERR_EVENT_NOT_CONCLUDED`, since actuals cannot be reported while the meeting is still running; no report may already exist for the event, otherwise `ERR_POST_EVENT_REPORT_EXISTS`, and this is the error an event in `COMPLETED` reports as described in section 2.8; a rate benchmark must exist for the venue's `destination_tier` paired with the event's `program_type`, otherwise `ERR_BENCHMARK_NOT_CONFIGURED`, because the savings figures are measured against it; and `actual_room_nights` must be at most the contract's `contracted_paid_room_nights`, otherwise `ERR_ACTUALS_EXCEED_CONTRACT`, since the group cannot consume more paid nights than were contracted.

        Design: Corner/errors/post_event_report_is_gated_on_the_clock_the_actuals_and_uniqueness
        """
        world = executed_world
        fixtures.set_clock("2027-03-19T00:00:00.000Z")
        fixtures.file_post_event_report(
            world["event_id"],
            actual_room_nights=587,
            actual_fnb_usd=132000.00,
            actual_av_usd=19500.00,
        )

        response = api_client.create_post_event_report(
            world["event_id"],
            factories.post_event_report_payload(
                actual_room_nights=587, actual_fnb_usd=132000.00, actual_av_usd=19500.00
            ),
            PLANNER_HEADERS,
        )
        validate_error(response, ApiErrorId.POST_EVENT_REPORT_EXISTS.value)

        rows, meta = validate_paginated(
            api_client.list_post_event_reports(
                PLANNER_HEADERS, {"event_id": world["event_id"]}
            )
        )
        assert len(rows) == 1
        assert meta["total_count"] == 1


@pytest.fixture
def deposit_scheduled_world():
    """An executed contract that already carries its three-installment deposit."""
    return fixtures.build_deposit_scheduled_contract()


class TestExecutedContractRefusals:
    """The triggers an already-executed, already-scheduled contract refuses."""

    def test_a_second_deposit_schedule_on_the_same_contract_is_refused(
        self, deposit_scheduled_world
    ):
        """This is the only place in the system where finance acts alone, and it may happen at most once per contract: the contract's `deposit_total_usd` must still be null, otherwise `ERR_DEPOSIT_ALREADY_SCHEDULED`, and `signature_state` must be `EXECUTED`, otherwise `ERR_CONTRACT_STATE_INVALID`.

        Design: Corner/errors/executed_contract_refuses_a_second_deposit_schedule_and_a_late_termination
        """
        world = deposit_scheduled_world
        response = api_client.generate_deposit_schedule(
            world["contract_id"], FINANCE_HEADERS
        )
        validate_error(response, ApiErrorId.DEPOSIT_ALREADY_SCHEDULED.value)

        rows, meta = validate_paginated(
            api_client.list_deposit_installments(world["contract_id"], FINANCE_HEADERS)
        )
        assert len(rows) == 3
        assert meta["total_count"] == 3

        contract = fixtures.read_contract(world["contract_id"])
        assert_money_field(contract, "contracted_total_usd", 432170.27)
        assert_money_field(contract, "deposit_total_usd", 129651.08)
        assert_money_field(contract, "deposit_outstanding_usd", 129651.08)
        domain_assert.assert_deposit_split_sums(rows, 129651.08)

    def test_signing_an_already_executed_contract_is_refused(
        self, deposit_scheduled_world
    ):
        """Signing requires `signature_state` to be `UNSIGNED`, otherwise `ERR_CONTRACT_STATE_INVALID`, and requires `approval_state` to be neither `REJECTED` nor `CANCELLED`.

        Design: Corner/errors/executed_contract_refuses_a_second_deposit_schedule_and_a_late_termination
        """
        world = deposit_scheduled_world
        response = api_client.sign_contract(
            world["contract_id"],
            factories.sign_payload(planner_signatory_name="Bruno Reis"),
            PLANNER_HEADERS,
        )
        validate_error(response, ApiErrorId.CONTRACT_STATE_INVALID.value)

        contract = fixtures.read_contract(world["contract_id"])
        assert contract["planner_signatory_name"] == "Anita Vale"
        assert contract["signature_state"] == "EXECUTED"

    def test_routing_an_already_approved_contract_is_refused(
        self, deposit_scheduled_world
    ):
        """Routing requires `approval_state` to be `PENDING_ROUTING` — any other value is `ERR_CONTRACT_STATE_INVALID` — and requires `signature_state` to be neither `TERMINATED` nor `VOIDED`, since a voided or terminated contract has nothing left to authorise.

        Design: Corner/errors/executed_contract_refuses_a_second_deposit_schedule_and_a_late_termination
        """
        world = deposit_scheduled_world
        response = api_client.route_approvals(world["contract_id"], PLANNER_HEADERS)
        validate_error(response, ApiErrorId.CONTRACT_STATE_INVALID.value)

        rows, meta = validate_paginated(
            api_client.list_approval_steps(world["contract_id"], PLANNER_HEADERS)
        )
        assert len(rows) == 2
        assert meta["total_count"] == 2

    def test_termination_on_the_arrival_day_is_refused(self, deposit_scheduled_world):
        """Termination requires `signature_state` to be `EXECUTED`, otherwise `ERR_CONTRACT_STATE_INVALID`, and requires the current logical clock to be strictly before the event's `start_date` at `00:00:00.000Z`, otherwise `ERR_TERMINATION_WINDOW_CLOSED`.

        A new contract begins with `approval_state` `PENDING_ROUTING` and `signature_state` `UNSIGNED` — the two parallel dimensions described below — and with its money and signature fields empty: `deposit_total_usd` null, `deposit_paid_usd` `0.00`, `deposit_outstanding_usd` null, `approval_step_count` `0`, and `planner_signatory_name`, `venue_signatory_name`, `executed_at`, `terminated_at`, `cancellation_fee_usd`, `rebooking_credit_usd` and `termination_reason` all null.

        Design: Corner/errors/executed_contract_refuses_a_second_deposit_schedule_and_a_late_termination
        """
        world = deposit_scheduled_world
        fixtures.set_clock("2027-03-15T00:00:00.000Z")

        response = api_client.terminate_contract(
            world["contract_id"], factories.terminate_payload(), PLANNER_HEADERS
        )
        validate_error(response, ApiErrorId.TERMINATION_WINDOW_CLOSED.value)

        contract = fixtures.read_contract(world["contract_id"])
        assert contract["signature_state"] == "EXECUTED"
        assert_nulls(contract, ["terminated_at", "cancellation_fee_usd"])

        domain_assert.assert_room_night_inventory(
            fixtures.read_venue(world["venue_id"]), 587
        )
        assert fixtures.read_event(world["event_id"])["status"] == "CONTRACTED"


@pytest.fixture
def bid_under_review():
    """A submitted bid priced once on the contracted basis, with its round still open."""
    world = fixtures.build_submitted_bid()
    fixtures.evaluate_bid(world["proposal_id"])
    return world


def open_second_counter(world):
    """Resolve one counter, re-price the bid and leave a second counter open."""
    counter_a = fixtures.raise_counter(
        world["proposal_id"],
        term_category="ATTRITION",
        proposed_numeric_value=0.15,
        planner_note="Tighten the attrition allowance to 0.15.",
    )
    fixtures.revise_bid(
        world["proposal_id"],
        world["venue_id"],
        counter_a["id"],
        accepted=True,
        revised_attrition_allowance_pct=0.15,
    )
    fixtures.evaluate_bid(world["proposal_id"])
    counter_b = fixtures.raise_counter(
        world["proposal_id"],
        term_category="CONCESSION",
        proposed_numeric_value=30000.00,
        planner_note="Raise the concession credit to 30000.00.",
    )
    return counter_a, counter_b


class TestRevisionTargetsAnOpenCounter:
    """POST /sourcing/proposals/{proposal_id}/revise."""

    def test_accepting_the_open_counter_rewrites_the_countered_term(
        self, bid_under_review
    ):
        """A successful counter is created with HTTP 201 in `resolution` `OPEN`, with `resolved_at` null, with `initiated_by_user_id` set to the calling planner's `X-User-ID`, and with `round_seq` set to the bid's `negotiation_round_count` plus 1, giving a 1-based sequence in creation order within the bid.

        On success the referenced counter's `resolution` becomes `ACCEPTED` when `accepted` is `true` and `DECLINED_BY_VENUE` when it is `false`, and its `resolved_at` is stamped from the logical clock.

        Design: Corner/errors/revise_targets_only_an_open_counter_that_belongs_to_the_proposal
        """
        world = bid_under_review
        counter_a = validate_success(
            api_client.create_counter(
                world["proposal_id"],
                factories.counter_payload(
                    fixtures.proposal_version(world["proposal_id"]),
                    term_category="ATTRITION",
                    proposed_numeric_value=0.15,
                    planner_note="Tighten the attrition allowance to 0.15.",
                ),
                PLANNER_HEADERS,
            ),
            201,
        )
        assert_integer(counter_a["round_seq"], 1, "round_seq")
        assert counter_a["resolution"] == "OPEN"

        countered = fixtures.read_proposal(world["proposal_id"])
        assert countered["status"] == "COUNTERED"
        assert_integer(
            countered["negotiation_round_count"], 1, "negotiation_round_count"
        )

        revised = validate_success(
            api_client.revise_proposal(
                world["proposal_id"],
                factories.revision_payload(
                    counter_a["id"], True, revised_attrition_allowance_pct=0.15
                ),
                make_venue_rep_headers(world["venue_id"]),
            ),
            200,
        )
        assert revised["status"] == "REVISED"
        assert revised["attrition_allowance_pct"] == 0.15
        assert_money_field(revised, "total_cost_contracted_usd", 447844.84)

        resolved = [
            row
            for row in validate_paginated(
                api_client.list_negotiation_counters(
                    world["proposal_id"], PLANNER_HEADERS
                )
            )[0]
            if row["id"] == counter_a["id"]
        ][0]
        assert resolved["resolution"] == "ACCEPTED"
        assert resolved["resolved_at"] == CLOCK_SOURCING_WINDOW

    def test_revising_against_an_already_resolved_counter_is_refused(
        self, bid_under_review
    ):
        """Revision requires the bid to be in `COUNTERED`, otherwise `ERR_PROPOSAL_STATE_INVALID`, and requires the referenced counter to belong to this same bid and to still be in `OPEN`; a counter belonging to a different bid or already resolved is rejected with `ERR_COUNTER_NOT_OPEN`, while a `counter_id` naming nothing at all yields `ERR_COUNTER_NOT_FOUND`.

        Design: Corner/errors/revise_targets_only_an_open_counter_that_belongs_to_the_proposal
        """
        world = bid_under_review
        counter_a, counter_b = open_second_counter(world)
        assert_integer(counter_b["round_seq"], 2, "round_seq")
        assert counter_b["resolution"] == "OPEN"

        response = api_client.revise_proposal(
            world["proposal_id"],
            factories.revision_payload(counter_a["id"], True),
            make_venue_rep_headers(world["venue_id"]),
        )
        validate_error(response, ApiErrorId.COUNTER_NOT_OPEN.value)

        assert fixtures.read_proposal(world["proposal_id"])["status"] == "COUNTERED"

    def test_revising_against_a_counter_that_does_not_exist_is_refused(
        self, bid_under_review
    ):
        """Revision requires the bid to be in `COUNTERED`, otherwise `ERR_PROPOSAL_STATE_INVALID`, and requires the referenced counter to belong to this same bid and to still be in `OPEN`; a counter belonging to a different bid or already resolved is rejected with `ERR_COUNTER_NOT_OPEN`, while a `counter_id` naming nothing at all yields `ERR_COUNTER_NOT_FOUND`.

        Design: Corner/errors/revise_targets_only_an_open_counter_that_belongs_to_the_proposal
        """
        world = bid_under_review
        _, counter_b = open_second_counter(world)

        response = api_client.revise_proposal(
            world["proposal_id"],
            factories.revision_payload(NON_EXISTENT_UUID, True),
            make_venue_rep_headers(world["venue_id"]),
        )
        validate_error(response, ApiErrorId.COUNTER_NOT_FOUND.value)

        assert fixtures.read_proposal(world["proposal_id"])["status"] == "COUNTERED"
        rows, _ = validate_paginated(
            api_client.list_negotiation_counters(
                world["proposal_id"], PLANNER_HEADERS, {"resolution": "OPEN"}
            )
        )
        assert [row["id"] for row in rows] == [counter_b["id"]]

    def test_declining_the_open_counter_leaves_the_quoted_term_untouched(
        self, bid_under_review
    ):
        """On success the referenced counter's `resolution` becomes `ACCEPTED` when `accepted` is `true` and `DECLINED_BY_VENUE` when it is `false`, and its `resolved_at` is stamped from the logical clock.

        Each supplied revised value overwrites the corresponding quoted term on the bid — a supplied `revised_room_rate_usd` becomes the new `room_rate_usd`, a supplied `revised_fnb_minimum_usd` becomes the new `fnb_minimum_usd`, and so on for each pair — while omitted fields leave their quoted term untouched.

        Design: Corner/errors/revise_targets_only_an_open_counter_that_belongs_to_the_proposal
        """
        world = bid_under_review
        _, counter_b = open_second_counter(world)

        revised = validate_success(
            api_client.revise_proposal(
                world["proposal_id"],
                factories.revision_payload(counter_b["id"], False),
                make_venue_rep_headers(world["venue_id"]),
            ),
            200,
        )
        assert revised["status"] == "REVISED"
        assert_money_field(revised, "concession_credit_usd", 25000.00)
        assert_money_field(revised, "total_cost_contracted_usd", 447844.84)

        rows, _ = validate_paginated(
            api_client.list_negotiation_counters(world["proposal_id"], PLANNER_HEADERS)
        )
        declined = [row for row in rows if row["id"] == counter_b["id"]][0]
        assert declined["resolution"] == "DECLINED_BY_VENUE"
        assert_iso_instant(declined["resolved_at"], "resolved_at")

        still_open, meta = validate_paginated(
            api_client.list_negotiation_counters(
                world["proposal_id"], PLANNER_HEADERS, {"resolution": "OPEN"}
            )
        )
        assert still_open == []
        assert meta["total_count"] == 0


@pytest.fixture
def contracted_event_with_live_round_two_bid():
    """An executed award struck from round 1, with round 2's separate bidder left
    submitted because the award cascade only reaches its own round."""
    fixtures.set_clock(CLOCK_SOURCING_WINDOW)
    fixtures.create_benchmark()
    venue_a = fixtures.create_venue()
    event = fixtures.create_event()
    fixtures.lock_event(event["id"])
    fixtures.promote_entry(
        fixtures.add_entry(event["id"], venue_a["id"], rank_seq=1)["id"]
    )
    rfp_one = fixtures.issue_rfp(fixtures.create_rfp(event["id"])["id"])
    proposal_a = fixtures.find_invited_proposal(rfp_one["id"], venue_a["id"])
    fixtures.submit_bid(proposal_a["id"], venue_a["id"])
    fixtures.close_rfp(rfp_one["id"])

    venue_b = fixtures.create_second_venue()
    entry_b = fixtures.promote_entry(
        fixtures.add_entry(event["id"], venue_b["id"], rank_seq=2)["id"]
    )
    rfp_two = fixtures.issue_rfp(
        fixtures.create_rfp(
            event["id"],
            round_number=2,
            response_due_at="2026-10-15T17:00:00.000Z",
            previous_rfp_id=rfp_one["id"],
        )["id"]
    )
    proposal_b = fixtures.find_invited_proposal(rfp_two["id"], venue_b["id"])
    fixtures.submit_bid(proposal_b["id"], venue_b["id"], **CASCADE_BAY_GRID)
    fixtures.close_rfp(rfp_two["id"])

    fixtures.evaluate_bid(proposal_a["id"])
    contract = fixtures.award_bid(event["id"], proposal_a["id"])
    fixtures.route_contract(contract["id"])
    fixtures.approve_all_steps(contract["id"])
    fixtures.sign_contract(contract["id"])
    fixtures.countersign_contract(contract["id"], venue_a["id"])

    return {
        "event_id": event["id"],
        "venue_a_id": venue_a["id"],
        "venue_b_id": venue_b["id"],
        "entry_b_id": entry_b["id"],
        "proposal_a_id": proposal_a["id"],
        "proposal_b_id": proposal_b["id"],
        "contract_id": contract["id"],
    }


class TestAwardOnAContractedEvent:
    """POST /sourcing/events/{event_id}/award once the event is CONTRACTED."""

    def test_the_surviving_round_two_bid_can_still_be_priced(
        self, contracted_event_with_live_round_two_bid
    ):
        """Every other bid on the same solicitation round whose `status` is `SUBMITTED`, `UNDER_REVIEW`, `COUNTERED` or `REVISED` moves to `REJECTED`.

        Design: Corner/errors/award_on_a_contracted_event_reports_the_already_executed_contract
        """
        world = contracted_event_with_live_round_two_bid
        assert fixtures.read_proposal(world["proposal_b_id"])["status"] == "SUBMITTED"
        assert fixtures.read_entry(world["entry_b_id"])["status"] == "RFP_ISSUED"

        validate_success(
            api_client.evaluate_proposal(
                world["proposal_b_id"],
                factories.evaluate_payload("CONTRACTED_BASIS"),
                PLANNER_HEADERS,
            ),
            201,
        )

        proposal_b = fixtures.read_proposal(world["proposal_b_id"])
        assert proposal_b["status"] == "UNDER_REVIEW"
        assert_money_field(proposal_b, "total_cost_contracted_usd", 290551.07)

    def test_awarding_a_contracted_event_reports_the_executed_contract(
        self, contracted_event_with_live_round_two_bid
    ):
        """An event in any other lifecycle state is rejected with `ERR_EVENT_STATE_INVALID`, and an event already in `CONTRACTED` is rejected with the more specific `ERR_CONTRACT_ALREADY_EXECUTED` as described in section 2.8.

        Design: Corner/errors/award_on_a_contracted_event_reports_the_already_executed_contract
        """
        world = contracted_event_with_live_round_two_bid
        fixtures.evaluate_bid(world["proposal_b_id"])

        response = api_client.award_event(
            world["event_id"],
            factories.award_payload(
                world["proposal_b_id"], fixtures.event_version(world["event_id"])
            ),
            PLANNER_HEADERS,
        )
        validate_error(response, ApiErrorId.CONTRACT_ALREADY_EXECUTED.value)

        rows, meta = validate_paginated(
            api_client.list_contracts(PLANNER_HEADERS, {"event_id": world["event_id"]})
        )
        assert len(rows) == 1
        assert meta["total_count"] == 1
        assert rows[0]["id"] == world["contract_id"]

        event = fixtures.read_event(world["event_id"])
        assert event["status"] == "CONTRACTED"
        assert event["awarded_proposal_id"] == world["proposal_a_id"]
        assert_money_field(event, "committed_spend_usd", 432170.27)

        assert fixtures.read_proposal(world["proposal_b_id"])["status"] == "UNDER_REVIEW"
        domain_assert.assert_room_night_inventory(
            fixtures.read_venue(world["venue_b_id"]), 0
        )
