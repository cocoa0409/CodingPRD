"""Lifecycle transitions: the guarded moves and their fan-out.

Each check drives one documented transition of a meeting event, a shortlist
entry, a site inspection, a solicitation round or a bid, and then reads back
both the moved row and every rollup the move is documented to touch, including
the refusals that leave a terminal row exactly where it was.
"""

from typing import Any, Dict

from test_helpers import (
    CLOCK_SOURCING_WINDOW,
    PLANNER_HEADERS,
    ApiErrorId,
    api_client,
    make_venue_rep_headers,
    validate_error,
    validate_paginated,
    validate_success,
)
from test_helpers import assertions as domain_assert
from test_helpers import factories, fixtures

# The clock instant at which the canonical inspection window closes, which is
# the earliest instant a completion may be recorded.
INSPECTION_WINDOW_END = "2026-09-10T13:00:00.000Z"

# The alternative quoted grid: a GROSS rate carrying a ten per cent commission
# over 400 offered nights, which prices out cheaper than the canonical grid.
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

# The two pre-computed contracted totals of the two quoted grids.
CANONICAL_GRID_TOTAL = 447844.84
GROSS_GRID_TOTAL = 290551.07


def _draft_event_world() -> Dict[str, Any]:
    """A published benchmark, a registered venue and an event still in DRAFT."""
    fixtures.set_clock(CLOCK_SOURCING_WINDOW)
    benchmark = fixtures.create_benchmark()
    venue = fixtures.create_venue()
    event = fixtures.create_event(event_code="EVT-2822-A")
    return {
        "benchmark": benchmark,
        "venue": venue,
        "venue_id": venue["id"],
        "event": event,
        "event_id": event["id"],
    }


def _two_venue_draft_round() -> Dict[str, Any]:
    """Two promoted venues on one locked event, with round 1 drafted but not issued."""
    world = fixtures.build_sourcing_world()
    venue_b = fixtures.create_second_venue()
    entry_b = fixtures.add_entry(world["event_id"], venue_b["id"], rank_seq=2)
    entry_b = fixtures.promote_entry(entry_b["id"])
    rfp = fixtures.create_rfp(world["event_id"])
    world.update(
        {
            "venue_b": venue_b,
            "venue_b_id": venue_b["id"],
            "entry_b": entry_b,
            "entry_b_id": entry_b["id"],
            "rfp": rfp,
            "rfp_id": rfp["id"],
        }
    )
    return world


def _planned_inspection_world() -> Dict[str, Any]:
    """A shortlisted entry flagged for inspection, with one visit planned."""
    world = fixtures.build_sourcing_world(entry_overrides={"inspection_required": True})
    inspection = fixtures.plan_inspection(world["entry_id"])
    world.update({"inspection": inspection, "inspection_id": inspection["id"]})
    return world


def _round_with_one_expired_bid() -> Dict[str, Any]:
    """A closed round in which the cheaper venue answered and the other did not.

    The first venue's bid was never submitted, so closing the round expired it.
    """
    world = fixtures.build_two_venue_round()
    world["proposal_b"] = fixtures.submit_bid(
        world["proposal_b_id"], world["venue_b_id"], **GROSS_RATE_GRID
    )
    world["rfp"] = fixtures.close_rfp(world["rfp_id"])
    world["proposal"] = fixtures.read_proposal(world["proposal_id"])
    return world


class TestRequirementLock:
    """The one-way gate out of DRAFT."""

    def test_locking_the_requirement_advances_the_event_out_of_draft(self):
        """The lock is the opening transition of the sourcing file and it
        advances the event's version by one.

        Locking the requirement definition moves the event `DRAFT → REQUIREMENTS_LOCKED` and is the gate that opens shortlisting; before it, no shortlist entry may be created at all.
        Design: Corner/state_machines/lock_requirements_moves_event_from_draft_to_requirements_locked
        """
        world = _draft_event_world()
        assert world["event"]["status"] == "DRAFT"
        assert world["event"]["version"] == 1

        response = api_client.lock_event_requirements(world["event_id"], PLANNER_HEADERS)
        event = validate_success(response, 200)
        domain_assert.assert_envelope(response, "object")

        assert event["status"] == "REQUIREMENTS_LOCKED"
        domain_assert.assert_versioned_entity(event, 2)
        domain_assert.assert_version_advanced(world["event"], event)

    def test_locking_freezes_the_requirement_without_touching_any_figure(self):
        """The requirement fields and the whole money envelope come through the
        lock untouched, so downstream arithmetic may treat them as frozen.

        Locking mutates no child rows whatsoever; its entire effect is that the requirement fields become immutable inputs which every downstream calculation may safely treat as frozen.
        Design: Corner/state_machines/lock_requirements_moves_event_from_draft_to_requirements_locked
        """
        world = _draft_event_world()

        event = validate_success(
            api_client.lock_event_requirements(world["event_id"], PLANNER_HEADERS), 200
        )

        domain_assert.assert_fields_equal(
            event,
            {
                "event_code": "EVT-2822-A",
                "program_type": "USER_CONFERENCE",
                "start_date": "2027-03-15",
                "end_date": "2027-03-18",
                "peak_attendees": 200,
                "requested_room_nights": 600,
                "largest_meeting_space_sqft": 12000,
                "nights_span": 3,
                "shortlisted_venue_count": 0,
            },
        )
        domain_assert.assert_money_field(event, "budget_ceiling_usd", 500000.00)
        domain_assert.assert_money_field(event, "budget_remaining_usd", 500000.00)
        domain_assert.assert_money_field(event, "committed_spend_usd", 0.00)
        domain_assert.assert_money_field(event, "cancellation_liability_usd", 0.00)
        domain_assert.assert_budget_envelope(event)
        domain_assert.assert_nulls(event, ["best_total_cost_usd", "awarded_proposal_id"])

    def test_locking_an_already_locked_requirement_is_refused(self):
        """The lock is not idempotent: a second attempt is a state error and the
        event's version does not move again.

        The transition requires the event to be in `DRAFT` — any other status is rejected with `ERR_EVENT_STATE_INVALID` — and re-asserts that `peak_attendees` is at least 1, that `requested_room_nights` is at least 1 and that `budget_ceiling_usd` is strictly greater than 0.
        Design: Corner/state_machines/lock_requirements_twice_returns_event_state_invalid
        """
        world = _draft_event_world()
        locked = validate_success(
            api_client.lock_event_requirements(world["event_id"], PLANNER_HEADERS), 200
        )
        assert locked["version"] == 2

        response = api_client.lock_event_requirements(world["event_id"], PLANNER_HEADERS)
        validate_error(response, ApiErrorId.EVENT_STATE_INVALID, 409)

        after = fixtures.read_event(world["event_id"])
        assert after["status"] == "REQUIREMENTS_LOCKED"
        domain_assert.assert_versioned_entity(after, 2)


class TestShortlistEntryEventStateGuard:
    """Adding a candidate is gated on the parent event's status."""

    def test_draft_event_refuses_a_shortlist_entry(self):
        """Before the requirement is locked the shortlist is closed, and the
        refusal writes nothing and moves nothing.

        Shortlisting begins once the requirement is locked and stays open while the event is in `REQUIREMENTS_LOCKED`, `SOURCING` or `BID_REVIEW` — those three statuses, and no others, admit a new entry.
        Design: Corner/state_machines/shortlist_entry_creation_is_guarded_by_the_parent_event_state
        """
        world = _draft_event_world()

        response = api_client.create_shortlist_entry(
            world["event_id"],
            factories.shortlist_entry_payload(world["venue_id"], rank_seq=1),
            PLANNER_HEADERS,
        )
        validate_error(response, ApiErrorId.EVENT_STATE_INVALID, 409)

        _, meta = validate_paginated(
            api_client.list_shortlist_entries(
                PLANNER_HEADERS, {"event_id": world["event_id"]}
            )
        )
        assert meta["total_count"] == 0

        after = fixtures.read_event(world["event_id"])
        assert after["status"] == "DRAFT"
        domain_assert.assert_versioned_entity(after, 1)

    def test_locked_event_admits_the_same_shortlist_entry(self):
        """The identical request succeeds once the gate has opened.

        Locking the requirement definition moves the event `DRAFT → REQUIREMENTS_LOCKED` and is the gate that opens shortlisting; before it, no shortlist entry may be created at all.
        Design: Corner/state_machines/shortlist_entry_creation_is_guarded_by_the_parent_event_state
        """
        world = _draft_event_world()
        payload = factories.shortlist_entry_payload(world["venue_id"], rank_seq=1)
        validate_error(
            api_client.create_shortlist_entry(world["event_id"], payload, PLANNER_HEADERS),
            ApiErrorId.EVENT_STATE_INVALID,
            409,
        )

        fixtures.lock_event(world["event_id"])
        response = api_client.create_shortlist_entry(
            world["event_id"], payload, PLANNER_HEADERS
        )
        entry = validate_success(response, 201)

        assert entry["status"] == "CANDIDATE"
        domain_assert.assert_fields_equal(
            entry,
            {"event_id": world["event_id"], "venue_id": world["venue_id"], "rank_seq": 1},
        )
        domain_assert.assert_versioned_entity(entry, 1)

        after = fixtures.read_event(world["event_id"])
        assert after["status"] == "REQUIREMENTS_LOCKED"
        # Creation leaves the event at version 1 and locking advances it to 2;
        # "Creating an entry also advances the parent meeting event's `version`
        # by 1", so the event stands at 3 once the entry has been added.
        domain_assert.assert_versioned_entity(after, 3)


class TestShortlistEntryElimination:
    """ELIMINATED is a one-way exit from the shortlist."""

    def test_eliminating_a_shortlisted_entry_stores_the_reason_and_drops_the_count(self):
        """The entry leaves the live shortlist and the event's shortlist count
        falls with it.

        From `SHORTLISTED`, the entry moves `SHORTLISTED → ELIMINATED` with `elimination_reason` stored, and the parent event's `shortlisted_venue_count` decreases by 1.
        Design: Corner/state_machines/eliminated_shortlist_entry_is_terminal_and_rejects_further_transitions
        """
        world = fixtures.build_sourcing_world()
        assert world["entry"]["status"] == "SHORTLISTED"
        before_event = fixtures.read_event(world["event_id"])
        domain_assert.assert_integer(
            before_event["shortlisted_venue_count"], 1, "shortlisted_venue_count"
        )

        response = api_client.eliminate_shortlist_entry(
            world["entry_id"], factories.eliminate_payload(), PLANNER_HEADERS
        )
        entry = validate_success(response, 200)

        assert entry["status"] == "ELIMINATED"
        assert entry["elimination_reason"] == "Rate above programme benchmark."
        domain_assert.assert_version_advanced(world["entry"], entry)

        after_event = fixtures.read_event(world["event_id"])
        domain_assert.assert_integer(
            after_event["shortlisted_venue_count"], 0, "shortlisted_venue_count"
        )

    def test_eliminating_an_already_eliminated_entry_is_refused(self):
        """A second elimination is a state error, and the stored reason and the
        event's count are both left alone.

        Elimination is permitted from any status other than `AWARDED` and `ELIMINATED`; attempting it on an entry already in one of those two terminal states is rejected with `ERR_SHORTLIST_ENTRY_STATE_INVALID`.
        Design: Corner/state_machines/eliminated_shortlist_entry_is_terminal_and_rejects_further_transitions
        """
        world = fixtures.build_sourcing_world()
        eliminated = fixtures.eliminate_entry(world["entry_id"])
        assert eliminated["status"] == "ELIMINATED"

        response = api_client.eliminate_shortlist_entry(
            world["entry_id"],
            factories.eliminate_payload(elimination_reason="Second attempt."),
            PLANNER_HEADERS,
        )
        validate_error(response, ApiErrorId.SHORTLIST_ENTRY_STATE_INVALID, 409)

        entry = fixtures.read_entry(world["entry_id"])
        assert entry["status"] == "ELIMINATED"
        assert entry["elimination_reason"] == "Rate above programme benchmark."
        assert entry["version"] == eliminated["version"]

        event = fixtures.read_event(world["event_id"])
        domain_assert.assert_integer(
            event["shortlisted_venue_count"], 0, "shortlisted_venue_count"
        )

    def test_an_eliminated_entry_cannot_be_shortlisted_again(self):
        """There is no revival path back onto the live shortlist.

        Both `AWARDED` and `ELIMINATED` are terminal for a shortlist entry: there is no operation that revives an entry out of either.
        Design: Corner/state_machines/eliminated_shortlist_entry_is_terminal_and_rejects_further_transitions
        """
        world = fixtures.build_sourcing_world()
        eliminated = fixtures.eliminate_entry(world["entry_id"])

        response = api_client.shortlist_entry(world["entry_id"], PLANNER_HEADERS)
        validate_error(response, ApiErrorId.SHORTLIST_ENTRY_STATE_INVALID, 409)

        entry = fixtures.read_entry(world["entry_id"])
        assert entry["status"] == "ELIMINATED"
        assert entry["version"] == eliminated["version"]

        event = fixtures.read_event(world["event_id"])
        domain_assert.assert_integer(
            event["shortlisted_venue_count"], 0, "shortlisted_venue_count"
        )


class TestSolicitationRoundDraft:
    """A drafted round has reached nobody yet."""

    def test_drafted_round_starts_in_draft_with_empty_response_counters(self):
        """Drafting only records the terms of the solicitation: both counters
        are zero and neither lifecycle instant is stamped.

        A drafted round lands in `DRAFT` with `invited_count` at 0, `submitted_count` at 0, `issued_at` null and `closed_at` null.
        Design: Corner/state_machines/rfp_starts_in_draft_with_zero_response_counters
        """
        world = fixtures.build_sourcing_world()

        response = api_client.create_rfp(
            world["event_id"], factories.rfp_payload(), PLANNER_HEADERS
        )
        rfp = validate_success(response, 201)

        assert rfp["status"] == "DRAFT"
        domain_assert.assert_integer(rfp["invited_count"], 0, "invited_count")
        domain_assert.assert_integer(rfp["submitted_count"], 0, "submitted_count")
        domain_assert.assert_nulls(rfp, ["issued_at", "closed_at", "previous_rfp_id"])
        domain_assert.assert_fields_equal(
            rfp,
            {
                "event_id": world["event_id"],
                "round_number": 1,
                "response_due_at": "2026-09-30T17:00:00.000Z",
                "standard_response_version": "V2",
            },
        )
        domain_assert.assert_versioned_entity(rfp, 1)

    def test_drafting_a_round_invites_nobody_and_leaves_the_event_locked(self):
        """No bid shell exists before the round is issued, and the event only
        advances on issue.

        Finally the parent event advances: `REQUIREMENTS_LOCKED → SOURCING` when this is round 1, or `BID_REVIEW → SOURCING` when `round_number` is greater than 1, and the event's `version` advances by 1.
        Design: Corner/state_machines/rfp_starts_in_draft_with_zero_response_counters
        """
        world = fixtures.build_sourcing_world()

        rfp = validate_success(
            api_client.create_rfp(world["event_id"], factories.rfp_payload(), PLANNER_HEADERS),
            201,
        )

        assert fixtures.list_round_proposals(rfp["id"]) == []

        event = fixtures.read_event(world["event_id"])
        assert event["status"] == "REQUIREMENTS_LOCKED"
        domain_assert.assert_integer(
            event["shortlisted_venue_count"], 1, "shortlisted_venue_count"
        )
        entry = fixtures.read_entry(world["entry_id"])
        assert entry["status"] == "SHORTLISTED"


class TestSolicitationRoundIssueGuard:
    """A round cannot reach an empty invitee set."""

    def test_issuing_with_every_entry_still_a_candidate_is_refused(self):
        """A candidate that was never committed to the solicitation is not an
        invitee, so the issue is refused and the round stays in DRAFT.

        It requires the round to be in `DRAFT` — anything else is `ERR_RFP_STATE_INVALID` — the parent event to be in `REQUIREMENTS_LOCKED` or `BID_REVIEW`, at least one entry of the event to be in `SHORTLISTED`, `INSPECTION_SCHEDULED` or `INSPECTED` (otherwise `ERR_NO_SHORTLISTED_VENUES`, because a solicitation to an empty invitee set is meaningless), every one of those eligible entries flagged `inspection_required` to have reached `INSPECTED` (otherwise `ERR_INSPECTION_INCOMPLETE`), and `response_due_at` to still lie strictly after the current logical clock (otherwise `ERR_RESPONSE_DUE_OUT_OF_RANGE`, since a round drafted days ago may have gone stale).
        Design: Corner/state_machines/rfp_issue_without_any_shortlisted_entry_returns_no_shortlisted_venues
        """
        world = fixtures.build_sourcing_world(promote=False)
        assert world["entry"]["status"] == "CANDIDATE"
        rfp = fixtures.create_rfp(world["event_id"])

        response = api_client.issue_rfp(rfp["id"], PLANNER_HEADERS)
        validate_error(response, ApiErrorId.NO_SHORTLISTED_VENUES, 422)

        after = fixtures.read_rfp(rfp["id"])
        assert after["status"] == "DRAFT"
        domain_assert.assert_integer(after["invited_count"], 0, "invited_count")
        domain_assert.assert_nulls(after, ["issued_at"])
        assert fixtures.list_round_proposals(rfp["id"]) == []

        event = fixtures.read_event(world["event_id"])
        assert event["status"] == "REQUIREMENTS_LOCKED"

    def test_issuing_succeeds_once_one_candidate_has_been_shortlisted(self):
        """Committing a single candidate is enough to make the invitee set
        non-empty, and exactly one bid shell is minted for it.

        One bid is created in `INVITED` for each eligible entry, processed in ascending `rank_seq` order so the highest-preference venue's bid is created first, each copying `venue_id` from its source entry; `invited_count` is set to the number of bids created.
        Design: Corner/state_machines/rfp_issue_without_any_shortlisted_entry_returns_no_shortlisted_venues
        """
        world = fixtures.build_sourcing_world(promote=False)
        rfp = fixtures.create_rfp(world["event_id"])
        validate_error(
            api_client.issue_rfp(rfp["id"], PLANNER_HEADERS),
            ApiErrorId.NO_SHORTLISTED_VENUES,
            422,
        )

        fixtures.promote_entry(world["entry_id"])
        issued = validate_success(api_client.issue_rfp(rfp["id"], PLANNER_HEADERS), 200)

        assert issued["status"] == "ISSUED"
        domain_assert.assert_integer(issued["invited_count"], 1, "invited_count")

        bids = fixtures.list_round_proposals(rfp["id"])
        assert len(bids) == 1
        assert bids[0]["status"] == "INVITED"
        assert bids[0]["venue_id"] == world["venue_id"]


class TestSolicitationRoundIssueFanOut:
    """Issuing a round is the system's largest documented fan-out."""

    def test_issue_stamps_the_round_and_counts_its_invitees(self):
        """The round moves to ISSUED, is stamped from the logical clock and
        records how many venues were invited.

        On success, `issued_at` is stamped from the logical clock and the round moves `DRAFT → ISSUED`.
        Design: Corner/state_machines/rfp_issue_side_effects_create_invited_proposals_and_flip_entries
        """
        world = _two_venue_draft_round()

        response = api_client.issue_rfp(world["rfp_id"], PLANNER_HEADERS)
        rfp = validate_success(response, 200)

        assert rfp["status"] == "ISSUED"
        assert rfp["issued_at"] == CLOCK_SOURCING_WINDOW
        domain_assert.assert_iso_instant(rfp["issued_at"], "issued_at")
        domain_assert.assert_integer(rfp["invited_count"], 2, "invited_count")
        domain_assert.assert_integer(rfp["submitted_count"], 0, "submitted_count")
        domain_assert.assert_nulls(rfp, ["closed_at"])
        domain_assert.assert_version_advanced(world["rfp"], rfp)

    def test_issue_mints_one_invited_bid_for_each_invitee(self):
        """Every eligible entry receives its own bid shell, carrying the venue
        copied from that entry.

        One bid is created in `INVITED` for each eligible entry, processed in ascending `rank_seq` order so the highest-preference venue's bid is created first, each copying `venue_id` from its source entry; `invited_count` is set to the number of bids created.
        Design: Corner/state_machines/rfp_issue_side_effects_create_invited_proposals_and_flip_entries
        """
        world = _two_venue_draft_round()
        validate_success(api_client.issue_rfp(world["rfp_id"], PLANNER_HEADERS), 200)

        bids = fixtures.list_round_proposals(world["rfp_id"])

        assert len(bids) == 2
        assert all(bid["status"] == "INVITED" for bid in bids)
        assert all(bid["rfp_id"] == world["rfp_id"] for bid in bids)
        assert {bid["venue_id"] for bid in bids} == {
            world["venue_id"],
            world["venue_b_id"],
        }

    def test_issue_flips_every_source_entry_to_rfp_issued(self):
        """Both committed entries advance out of SHORTLISTED and each one's
        version advances by one.

        Each source entry then moves to `RFP_ISSUED` and its `version` advances by 1, and all three eligible source states are admitted: an entry in `SHORTLISTED` moves `SHORTLISTED → RFP_ISSUED`; an entry in `INSPECTED` moves `INSPECTED → RFP_ISSUED`; and an entry in `INSPECTION_SCHEDULED` moves `INSPECTION_SCHEDULED → RFP_ISSUED` only when its `inspection_required` is `false`, which is exactly the case the `ERR_INSPECTION_INCOMPLETE` guard leaves reachable.
        Design: Corner/state_machines/rfp_issue_side_effects_create_invited_proposals_and_flip_entries
        """
        world = _two_venue_draft_round()
        assert world["entry"]["status"] == "SHORTLISTED"
        assert world["entry_b"]["status"] == "SHORTLISTED"

        validate_success(api_client.issue_rfp(world["rfp_id"], PLANNER_HEADERS), 200)

        first = fixtures.read_entry(world["entry_id"])
        second = fixtures.read_entry(world["entry_b_id"])
        assert first["status"] == "RFP_ISSUED"
        assert second["status"] == "RFP_ISSUED"
        domain_assert.assert_version_advanced(world["entry"], first)
        domain_assert.assert_version_advanced(world["entry_b"], second)

    def test_issue_moves_the_event_into_sourcing_with_no_live_bid_yet(self):
        """The parent event advances on round 1 and still has no cheapest total,
        because nobody has answered.

        Finally the parent event advances: `REQUIREMENTS_LOCKED → SOURCING` when this is round 1, or `BID_REVIEW → SOURCING` when `round_number` is greater than 1, and the event's `version` advances by 1.
        Design: Corner/state_machines/rfp_issue_side_effects_create_invited_proposals_and_flip_entries
        """
        world = _two_venue_draft_round()
        before = fixtures.read_event(world["event_id"])
        assert before["status"] == "REQUIREMENTS_LOCKED"

        validate_success(api_client.issue_rfp(world["rfp_id"], PLANNER_HEADERS), 200)

        event = fixtures.read_event(world["event_id"])
        assert event["status"] == "SOURCING"
        domain_assert.assert_nulls(event, ["best_total_cost_usd"])
        domain_assert.assert_integer(
            event["shortlisted_venue_count"], 2, "shortlisted_venue_count"
        )
        domain_assert.assert_version_advanced(before, event)


class TestSolicitationRoundClose:
    """Closing a round settles the silent invitees and nothing else."""

    def test_closing_expires_the_bid_that_never_answered(self):
        """The invitee that stayed silent is expired rather than declined, and
        the round is stamped closed.

        `closed_at` is stamped from the logical clock, the round moves `ISSUED → CLOSED`, and every bid of that round still sitting in `INVITED` moves `INVITED → EXPIRED` — a venue that never answered is expired rather than declined, and expiry mutates nothing else.
        Design: Corner/state_machines/rfp_close_expires_invited_proposals_but_leaves_submitted_ones
        """
        world = fixtures.build_two_venue_round()
        fixtures.submit_bid(world["proposal_id"], world["venue_id"])

        response = api_client.close_rfp(world["rfp_id"], PLANNER_HEADERS)
        rfp = validate_success(response, 200)

        assert rfp["status"] == "CLOSED"
        assert rfp["closed_at"] == CLOCK_SOURCING_WINDOW
        domain_assert.assert_iso_instant(rfp["closed_at"], "closed_at")

        silent = fixtures.read_proposal(world["proposal_b_id"])
        assert silent["status"] == "EXPIRED"

    def test_closing_leaves_the_submitted_bid_and_its_priced_total_intact(self):
        """The venue that answered keeps its status and its contracted total,
        and the round's response counter still reports one live answer.

        `submitted_count` is the number of this round's bids whose `status` is one of `SUBMITTED`, `UNDER_REVIEW`, `COUNTERED`, `REVISED` or `AWARDED`.
        Design: Corner/state_machines/rfp_close_expires_invited_proposals_but_leaves_submitted_ones
        """
        world = fixtures.build_two_venue_round()
        submitted = fixtures.submit_bid(world["proposal_id"], world["venue_id"])
        domain_assert.assert_money_field(
            submitted, "total_cost_contracted_usd", CANONICAL_GRID_TOTAL
        )

        rfp = validate_success(api_client.close_rfp(world["rfp_id"], PLANNER_HEADERS), 200)

        domain_assert.assert_integer(rfp["submitted_count"], 1, "submitted_count")
        domain_assert.assert_integer(rfp["invited_count"], 2, "invited_count")

        live = fixtures.read_proposal(world["proposal_id"])
        assert live["status"] == "SUBMITTED"
        domain_assert.assert_money_field(
            live, "total_cost_contracted_usd", CANONICAL_GRID_TOTAL
        )

    def test_closing_moves_the_event_into_bid_review_without_touching_the_entries(self):
        """The event advances to review with the surviving bid as its cheapest
        total, while the shortlist rows are left exactly where issuing put them.

        The parent event moves `SOURCING → BID_REVIEW`, its `best_total_cost_usd` is recomputed, and its `version` advances by 1.
        Design: Corner/state_machines/rfp_close_expires_invited_proposals_but_leaves_submitted_ones
        """
        world = fixtures.build_two_venue_round()
        fixtures.submit_bid(world["proposal_id"], world["venue_id"])
        before = fixtures.read_event(world["event_id"])
        assert before["status"] == "SOURCING"

        validate_success(api_client.close_rfp(world["rfp_id"], PLANNER_HEADERS), 200)

        event = fixtures.read_event(world["event_id"])
        assert event["status"] == "BID_REVIEW"
        domain_assert.assert_money_field(
            event, "best_total_cost_usd", CANONICAL_GRID_TOTAL
        )
        domain_assert.assert_version_advanced(before, event)

        assert fixtures.read_entry(world["entry_id"])["status"] == "RFP_ISSUED"
        assert fixtures.read_entry(world["entry_b_id"])["status"] == "RFP_ISSUED"


class TestSiteInspectionCancellation:
    """Cancelling a visit must not cost the venue its place on the shortlist."""

    def test_cancelling_a_planned_visit_records_the_reason(self):
        """The visit is cancelled with its reason persisted and no findings.

        It requires the inspection to be in `PLANNED`, rejecting anything else with `ERR_INSPECTION_STATE_INVALID`, and the caller supplies `cancel_reason`, which is persisted.
        Design: Corner/state_machines/site_inspection_cancel_reverts_entry_to_shortlisted_and_releases_window
        """
        world = _planned_inspection_world()
        assert world["inspection"]["status"] == "PLANNED"

        response = api_client.cancel_site_inspection(
            world["inspection_id"], factories.cancel_inspection_payload(), PLANNER_HEADERS
        )
        inspection = validate_success(response, 200)

        assert inspection["status"] == "CANCELLED"
        assert inspection["cancel_reason"] == "Inspector travel restriction."
        domain_assert.assert_nulls(inspection, ["findings_score"])
        domain_assert.assert_version_advanced(world["inspection"], inspection)

    def test_cancelling_the_only_visit_reverts_the_entry_to_shortlisted(self):
        """With the visit counter back at zero the entry returns to the live
        shortlist, ready to be re-planned.

        When that decrement brings `inspection_count` to 0 and the entry is still in `INSPECTION_SCHEDULED`, the entry reverts `INSPECTION_SCHEDULED → SHORTLISTED`, ready to be re-planned; when other planned or completed inspections remain on the entry, the entry's status is left where it is.
        Design: Corner/state_machines/site_inspection_cancel_reverts_entry_to_shortlisted_and_releases_window
        """
        world = _planned_inspection_world()
        scheduled = fixtures.read_entry(world["entry_id"])
        assert scheduled["status"] == "INSPECTION_SCHEDULED"
        domain_assert.assert_integer(scheduled["inspection_count"], 1, "inspection_count")

        validate_success(
            api_client.cancel_site_inspection(
                world["inspection_id"],
                factories.cancel_inspection_payload(),
                PLANNER_HEADERS,
            ),
            200,
        )

        entry = fixtures.read_entry(world["entry_id"])
        assert entry["status"] == "SHORTLISTED"
        domain_assert.assert_integer(entry["inspection_count"], 0, "inspection_count")
        domain_assert.assert_version_advanced(scheduled, entry)

        event = fixtures.read_event(world["event_id"])
        domain_assert.assert_integer(
            event["shortlisted_venue_count"], 1, "shortlisted_venue_count"
        )

    def test_the_released_window_can_be_booked_again_with_identical_timings(self):
        """A cancelled visit holds no occupation interval, so the very same
        window is free for a replacement visit.

        Inspections whose `status` is `CANCELLED` release their interval entirely and never participate in the conflict test.
        Design: Corner/state_machines/site_inspection_cancel_reverts_entry_to_shortlisted_and_releases_window
        """
        world = _planned_inspection_world()
        fixtures.cancel_inspection(world["inspection_id"])

        response = api_client.create_site_inspection(
            factories.site_inspection_payload(world["entry_id"]), PLANNER_HEADERS
        )
        replacement = validate_success(response, 201)

        assert replacement["status"] == "PLANNED"
        assert replacement["id"] != world["inspection_id"]
        domain_assert.assert_fields_equal(
            replacement,
            {
                "shortlist_entry_id": world["entry_id"],
                "window_start": "2026-09-10T09:00:00.000Z",
                "window_end": "2026-09-10T13:00:00.000Z",
            },
        )

        entry = fixtures.read_entry(world["entry_id"])
        assert entry["status"] == "INSPECTION_SCHEDULED"
        domain_assert.assert_integer(entry["inspection_count"], 1, "inspection_count")


class TestSiteInspectionCompletion:
    """A completed visit clears the entry for a solicitation."""

    def test_completing_a_visit_persists_the_inspector_score(self):
        """The findings score is recorded on the inspection and no cancellation
        reason appears.

        The caller supplies `findings_score`, the inspector's score from 1 through 5 inclusive, which is persisted on the inspection.
        Design: Corner/state_machines/inspection_completion_flips_the_shortlist_entry_to_inspected
        """
        world = _planned_inspection_world()
        fixtures.set_clock(INSPECTION_WINDOW_END)

        response = api_client.complete_site_inspection(
            world["inspection_id"],
            factories.complete_inspection_payload(),
            PLANNER_HEADERS,
        )
        inspection = validate_success(response, 200)

        assert inspection["status"] == "COMPLETED"
        domain_assert.assert_integer(inspection["findings_score"], 4, "findings_score")
        domain_assert.assert_nulls(inspection, ["cancel_reason"])
        domain_assert.assert_version_advanced(world["inspection"], inspection)

    def test_completing_a_visit_flips_the_entry_to_inspected(self):
        """The parent entry advances with the visit and its version advances
        with it, while the visit still counts.

        The inspection moves `PLANNED → COMPLETED` and the parent entry moves `INSPECTION_SCHEDULED → INSPECTED`, with the entry's `version` advancing by 1.
        Design: Corner/state_machines/inspection_completion_flips_the_shortlist_entry_to_inspected
        """
        world = _planned_inspection_world()
        scheduled = fixtures.read_entry(world["entry_id"])
        assert scheduled["status"] == "INSPECTION_SCHEDULED"
        fixtures.set_clock(INSPECTION_WINDOW_END)

        validate_success(
            api_client.complete_site_inspection(
                world["inspection_id"],
                factories.complete_inspection_payload(),
                PLANNER_HEADERS,
            ),
            200,
        )

        entry = fixtures.read_entry(world["entry_id"])
        assert entry["status"] == "INSPECTED"
        domain_assert.assert_integer(entry["inspection_count"], 1, "inspection_count")
        domain_assert.assert_version_advanced(scheduled, entry)

    def test_an_inspected_entry_still_counts_towards_the_shortlist(self):
        """Completion does not move the event, and an inspected entry remains
        inside the event's shortlist count.

        That count is maintained as the number of the event's entries whose `status` is one of `SHORTLISTED`, `INSPECTION_SCHEDULED`, `INSPECTED`, `RFP_ISSUED` or `AWARDED` — entries still in `CANDIDATE` and entries already `ELIMINATED` are excluded.
        Design: Corner/state_machines/inspection_completion_flips_the_shortlist_entry_to_inspected
        """
        world = _planned_inspection_world()
        fixtures.set_clock(INSPECTION_WINDOW_END)
        fixtures.complete_inspection(world["inspection_id"])

        event = fixtures.read_event(world["event_id"])
        assert event["status"] == "REQUIREMENTS_LOCKED"
        domain_assert.assert_integer(
            event["shortlisted_venue_count"], 1, "shortlisted_venue_count"
        )


def _two_live_bids() -> Dict[str, Any]:
    """An issued round in which both invited venues have answered.

    The second venue's commissionable grid prices out cheaper, so it holds the
    event's best total until it is withdrawn.
    """
    world = fixtures.build_two_venue_round()
    world["proposal"] = fixtures.submit_bid(world["proposal_id"], world["venue_id"])
    world["proposal_b"] = fixtures.submit_bid(
        world["proposal_b_id"], world["venue_b_id"], **GROSS_RATE_GRID
    )
    return world


class TestBidWithdrawal:
    """Withdrawing a live bid rebases the round and the event."""

    def test_withdrawing_a_live_bid_keeps_its_priced_total_on_the_record(self):
        """The withdrawn bid reaches its terminal status while the figures it
        quoted stay on the row.

        A `VenueRep` acting for the bid's own venue may withdraw from `SUBMITTED`, `UNDER_REVIEW`, `COUNTERED` or `REVISED`, and all four source states behave identically in their primary effect: the bid moves to `WITHDRAWN`, the parent round's `submitted_count` decreases by 1, and the event's `best_total_cost_usd` is recomputed with the event's `version` advancing by 1.
        Design: Corner/state_machines/withdraw_proposal_decrements_rfp_counter_and_rebases_event_best_total
        """
        world = _two_live_bids()
        domain_assert.assert_money_field(
            world["proposal_b"], "total_cost_contracted_usd", GROSS_GRID_TOTAL
        )

        response = api_client.withdraw_proposal(
            world["proposal_b_id"], make_venue_rep_headers(world["venue_b_id"])
        )
        withdrawn = validate_success(response, 200)

        assert withdrawn["status"] == "WITHDRAWN"
        domain_assert.assert_money_field(
            withdrawn, "total_cost_contracted_usd", GROSS_GRID_TOTAL
        )
        domain_assert.assert_money_field(withdrawn, "net_adr_usd", 247.50)

    def test_withdrawing_drops_the_round_response_counter_by_one(self):
        """A withdrawn bid stops counting as a response while the invitation
        count is unaffected.

        It rises by 1 when a venue submits and falls by 1 when a venue withdraws, and bids in `INVITED`, `DECLINED`, `REJECTED`, `WITHDRAWN` or `EXPIRED` are not counted.
        Design: Corner/state_machines/withdraw_proposal_decrements_rfp_counter_and_rebases_event_best_total
        """
        world = _two_live_bids()
        before = fixtures.read_rfp(world["rfp_id"])
        domain_assert.assert_integer(before["submitted_count"], 2, "submitted_count")

        validate_success(
            api_client.withdraw_proposal(
                world["proposal_b_id"], make_venue_rep_headers(world["venue_b_id"])
            ),
            200,
        )

        after = fixtures.read_rfp(world["rfp_id"])
        domain_assert.assert_integer(after["submitted_count"], 1, "submitted_count")
        domain_assert.assert_integer(after["invited_count"], 2, "invited_count")
        assert after["status"] == "ISSUED"

    def test_withdrawing_the_cheapest_bid_rebases_the_event_best_total(self):
        """With the cheapest answer gone the event falls back on the remaining
        live bid's own contracted total, carried across unchanged.

        Otherwise it is the `total_cost_contracted_usd` of the live bid with the smallest `total_cost_contracted_usd`, with ties broken in favour of the bid with the earlier `created_at` and never by comparing `id` values; the stored two-decimal value is carried across unchanged with no further rounding.
        Design: Corner/state_machines/withdraw_proposal_decrements_rfp_counter_and_rebases_event_best_total
        """
        world = _two_live_bids()
        before = fixtures.read_event(world["event_id"])
        domain_assert.assert_money_field(
            before, "best_total_cost_usd", GROSS_GRID_TOTAL
        )

        validate_success(
            api_client.withdraw_proposal(
                world["proposal_b_id"], make_venue_rep_headers(world["venue_b_id"])
            ),
            200,
        )

        event = fixtures.read_event(world["event_id"])
        domain_assert.assert_money_field(
            event, "best_total_cost_usd", CANONICAL_GRID_TOTAL
        )
        assert event["status"] == "SOURCING"
        domain_assert.assert_version_advanced(before, event)

        survivor = fixtures.read_proposal(world["proposal_id"])
        assert survivor["status"] == "SUBMITTED"
        domain_assert.assert_money_field(
            survivor, "total_cost_contracted_usd", CANONICAL_GRID_TOTAL
        )
        assert fixtures.read_entry(world["entry_b_id"])["status"] == "RFP_ISSUED"


class TestExpiredBidIsTerminal:
    """An expired invitation admits no venue action at all."""

    def test_an_expired_bid_cannot_be_submitted(self):
        """The venue that missed the round cannot answer it afterwards.

        The bid must be in `INVITED`, and any other status is rejected with `ERR_PROPOSAL_STATE_INVALID`.
        Design: Corner/state_machines/expired_proposal_rejects_submit_decline_and_withdraw
        """
        world = _round_with_one_expired_bid()
        assert world["proposal"]["status"] == "EXPIRED"

        response = api_client.submit_proposal(
            world["proposal_id"],
            factories.proposal_submission_payload(),
            make_venue_rep_headers(world["venue_id"]),
        )
        validate_error(response, ApiErrorId.PROPOSAL_STATE_INVALID, 409)

        assert fixtures.read_proposal(world["proposal_id"])["status"] == "EXPIRED"

    def test_an_expired_bid_cannot_be_declined(self):
        """Declining is reserved for a live invitation, not an expired one.

        Declining requires the bid to be in `INVITED` and the caller to own the venue, moves the bid `INVITED → DECLINED`, and deliberately leaves the matching shortlist entry untouched so that a later negotiation round may still invite the same venue.
        Design: Corner/state_machines/expired_proposal_rejects_submit_decline_and_withdraw
        """
        world = _round_with_one_expired_bid()

        response = api_client.decline_proposal(
            world["proposal_id"], make_venue_rep_headers(world["venue_id"])
        )
        validate_error(response, ApiErrorId.PROPOSAL_STATE_INVALID, 409)

        assert fixtures.read_proposal(world["proposal_id"])["status"] == "EXPIRED"

    def test_an_expired_bid_cannot_be_withdrawn(self):
        """There is nothing live to withdraw from.

        A bid in any other status — `INVITED`, `DECLINED`, `AWARDED`, `REJECTED`, `WITHDRAWN` or `EXPIRED` — cannot be withdrawn and is rejected with `ERR_PROPOSAL_STATE_INVALID`.
        Design: Corner/state_machines/expired_proposal_rejects_submit_decline_and_withdraw
        """
        world = _round_with_one_expired_bid()

        response = api_client.withdraw_proposal(
            world["proposal_id"], make_venue_rep_headers(world["venue_id"])
        )
        validate_error(response, ApiErrorId.PROPOSAL_STATE_INVALID, 409)

        assert fixtures.read_proposal(world["proposal_id"])["status"] == "EXPIRED"

    def test_three_refused_attempts_leave_every_rollup_untouched(self):
        """None of the three refusals feeds the round counter or the event's
        cheapest total, which still belong to the venue that did answer.

        The five statuses `AWARDED`, `REJECTED`, `DECLINED`, `WITHDRAWN` and `EXPIRED` are terminal for a bid.
        Design: Corner/state_machines/expired_proposal_rejects_submit_decline_and_withdraw
        """
        world = _round_with_one_expired_bid()
        expired_headers = make_venue_rep_headers(world["venue_id"])

        validate_error(
            api_client.submit_proposal(
                world["proposal_id"],
                factories.proposal_submission_payload(),
                expired_headers,
            ),
            ApiErrorId.PROPOSAL_STATE_INVALID,
            409,
        )
        validate_error(
            api_client.decline_proposal(world["proposal_id"], expired_headers),
            ApiErrorId.PROPOSAL_STATE_INVALID,
            409,
        )
        validate_error(
            api_client.withdraw_proposal(world["proposal_id"], expired_headers),
            ApiErrorId.PROPOSAL_STATE_INVALID,
            409,
        )

        rfp = fixtures.read_rfp(world["rfp_id"])
        assert rfp["status"] == "CLOSED"
        domain_assert.assert_integer(rfp["submitted_count"], 1, "submitted_count")
        domain_assert.assert_integer(rfp["invited_count"], 2, "invited_count")

        event = fixtures.read_event(world["event_id"])
        assert event["status"] == "BID_REVIEW"
        domain_assert.assert_money_field(event, "best_total_cost_usd", GROSS_GRID_TOTAL)

        answered = fixtures.read_proposal(world["proposal_b_id"])
        assert answered["status"] == "SUBMITTED"
        domain_assert.assert_money_field(
            answered, "total_cost_contracted_usd", GROSS_GRID_TOTAL
        )
