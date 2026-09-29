"""Optimistic concurrency on the two versioned writes, and read-your-write consistency.

The award and the term counter are the only two writes that carry an expected
version, so this module drives both refusal-then-retry cycles, walks the event
version ladder one write at a time, pins the inclusive volume-rebate tier
minimum that reads the pre-rebate total, and checks that a countersignature's
own response body already carries the executed join and its whole cascade.
"""

import pytest

from test_helpers import (
    PLANNER_HEADERS,
    PLANNER_USER_ID,
    ApiErrorId,
    api_client,
    factories,
    fixtures,
    validate_error,
    validate_paginated,
    validate_success,
)
from test_helpers import assertions as domain_assert

SOURCING_CLOCK = "2026-08-05T09:00:00.000Z"

# The two three-night requirements of the rebate-boundary pair. They differ only
# in their code, name and dates; every commercial input is identical.
_EVENT_P = {
    "event_code": "EVT-2822-P",
    "name": "Rebate Boundary Programme P",
    "start_date": "2027-04-12",
    "end_date": "2027-04-15",
    "peak_attendees": 180,
    "requested_room_nights": 500,
    "largest_meeting_space_sqft": 9000,
    "budget_ceiling_usd": 200000.00,
}
_EVENT_Q = dict(
    _EVENT_P,
    event_code="EVT-2822-Q",
    name="Rebate Boundary Programme Q",
    start_date="2027-05-17",
    end_date="2027-05-20",
)

# One flat bid grid quoted on both requirements: a 200.00 NET rate over 500
# offered nights with no comp rooms, no resort fee, no audiovisual and no
# concession, so only the F&B minimum separates the two totals.
_FLAT_GRID = {
    "room_rate_usd": 200.00,
    "rate_type": "NET",
    "commission_pct": 0.00,
    "room_nights_offered": 500,
    "comp_room_ratio": 0,
    "resort_fee_usd_per_night": 0.00,
    "service_charge_pct": 0.20,
    "tax_pct": 0.10,
    "av_estimate_usd": 0.00,
    "concession_credit_usd": 0.00,
    "attrition_allowance_pct": 0.20,
    "force_majeure_scope": "STANDARD",
    "rebooking_credit_pct": 0.50,
}


def _priced_round_on_venue(venue_id, event_overrides, fnb_minimum_usd):
    """Run one requirement from creation to a priced bid on an existing venue.

    The benchmark and the venue are registered once by the caller, because the
    tier-and-programme pairing of a published benchmark is unique.
    """
    event = fixtures.create_event(**event_overrides)
    fixtures.lock_event(event["id"])
    entry = fixtures.add_entry(event["id"], venue_id, rank_seq=1)
    fixtures.promote_entry(entry["id"])
    rfp = fixtures.create_rfp(event["id"])
    fixtures.issue_rfp(rfp["id"])
    proposal = fixtures.find_invited_proposal(rfp["id"], venue_id)
    fixtures.submit_bid(
        proposal["id"], venue_id, fnb_minimum_usd=fnb_minimum_usd, **_FLAT_GRID
    )
    fixtures.close_rfp(rfp["id"])
    fixtures.evaluate_bid(proposal["id"])
    return {
        "event_id": event["id"],
        "entry_id": entry["id"],
        "rfp_id": rfp["id"],
        "proposal_id": proposal["id"],
    }


def _awarded_rebate_boundary_pair():
    """Two awards whose pre-rebate totals sit one cent apart on the tier minimum."""
    fixtures.set_clock(SOURCING_CLOCK)
    fixtures.create_benchmark()
    venue = fixtures.create_venue()
    at_the_minimum = _priced_round_on_venue(venue["id"], _EVENT_P, 13636.37)
    one_cent_below = _priced_round_on_venue(venue["id"], _EVENT_Q, 13636.36)
    contract_at_minimum = fixtures.award_bid(
        at_the_minimum["event_id"], at_the_minimum["proposal_id"]
    )
    contract_below = fixtures.award_bid(
        one_cent_below["event_id"], one_cent_below["proposal_id"]
    )
    return {
        "venue_id": venue["id"],
        "at_the_minimum": at_the_minimum,
        "one_cent_below": one_cent_below,
        "contract_at_minimum": contract_at_minimum,
        "contract_below": contract_below,
    }


class TestStaleEventVersionOnAward:
    """The award is one of the two writes that carry a caller-supplied version."""

    def test_an_award_carrying_a_superseded_event_version_is_refused(self):
        """A view one version behind the event is refused and leaves no trace.

        "If that value does not equal the event's current `version`, the award is rejected with `ERR_STALE_EVENT_VERSION` (HTTP 412)."

        Design: Corner/cross_cutting_complexity_layers/award_with_a_stale_expected_event_version_is_refused_then_retried
        """
        world = fixtures.build_evaluated_bid(close_round=True)
        event_version = fixtures.event_version(world["event_id"])

        response = api_client.award_event(
            world["event_id"],
            factories.award_payload(
                world["proposal_id"],
                event_version - 1,
                award_note="Stale read of the event.",
            ),
            PLANNER_HEADERS,
        )
        validate_error(response, ApiErrorId.STALE_EVENT_VERSION.value, 412)

        contracts, meta = validate_paginated(
            api_client.list_contracts(
                PLANNER_HEADERS, {"event_id": world["event_id"]}
            )
        )
        assert contracts == [], "the refused award must not mint a contract"
        domain_assert.assert_integer(meta["total_count"], 0, "total_count")

        event = fixtures.read_event(world["event_id"])
        domain_assert.assert_fields_equal(
            event, {"status": "BID_REVIEW", "version": event_version}
        )
        domain_assert.assert_nulls(event, ["awarded_proposal_id"])
        domain_assert.assert_fields_equal(
            fixtures.read_proposal(world["proposal_id"]), {"status": "UNDER_REVIEW"}
        )

    def test_the_retry_with_the_current_version_mints_the_contract(self):
        """The same body carrying the live version is accepted at HTTP 201.

        "A new contract begins with `approval_state` `PENDING_ROUTING` and `signature_state` `UNSIGNED` — the two parallel dimensions described below — and with its money and signature fields empty: `deposit_total_usd` null, `deposit_paid_usd` `0.00`, `deposit_outstanding_usd` null, `approval_step_count` `0`, and `planner_signatory_name`, `venue_signatory_name`, `executed_at`, `terminated_at`, `cancellation_fee_usd`, `rebooking_credit_usd` and `termination_reason` all null."

        Design: Corner/cross_cutting_complexity_layers/award_with_a_stale_expected_event_version_is_refused_then_retried
        """
        world = fixtures.build_evaluated_bid(close_round=True)
        event_version = fixtures.event_version(world["event_id"])
        stale = api_client.award_event(
            world["event_id"],
            factories.award_payload(
                world["proposal_id"],
                event_version - 1,
                award_note="Stale read of the event.",
            ),
            PLANNER_HEADERS,
        )
        validate_error(stale, ApiErrorId.STALE_EVENT_VERSION.value, 412)

        contract = validate_success(
            api_client.award_event(
                world["event_id"],
                factories.award_payload(world["proposal_id"], event_version),
                PLANNER_HEADERS,
            ),
            201,
        )
        domain_assert.assert_fields_equal(
            contract,
            {
                "approval_state": "PENDING_ROUTING",
                "signature_state": "UNSIGNED",
                "approval_step_count": 0,
            },
        )
        domain_assert.assert_money_field(contract, "contracted_total_usd", 432170.27)

    def test_the_accepted_award_moves_the_event_and_the_winning_bid(self):
        """The event's rollups and the bid's status settle in the award request itself.

        "The event moves to `AWARDED`, its `awarded_proposal_id` is set to the winning bid, its `committed_spend_usd` is set to the contract's `contracted_total_usd`, its `budget_remaining_usd` is recomputed from the money identity in section 2.10, and its `version` advances by 1."

        Design: Corner/cross_cutting_complexity_layers/award_with_a_stale_expected_event_version_is_refused_then_retried
        """
        world = fixtures.build_evaluated_bid(close_round=True)
        event_version = fixtures.event_version(world["event_id"])
        validate_error(
            api_client.award_event(
                world["event_id"],
                factories.award_payload(
                    world["proposal_id"], event_version - 1
                ),
                PLANNER_HEADERS,
            ),
            ApiErrorId.STALE_EVENT_VERSION.value,
            412,
        )
        validate_success(
            api_client.award_event(
                world["event_id"],
                factories.award_payload(world["proposal_id"], event_version),
                PLANNER_HEADERS,
            ),
            201,
        )

        event = fixtures.read_event(world["event_id"])
        domain_assert.assert_fields_equal(
            event,
            {
                "status": "AWARDED",
                "awarded_proposal_id": world["proposal_id"],
                "version": event_version + 1,
            },
        )
        domain_assert.assert_money_field(event, "committed_spend_usd", 432170.27)
        domain_assert.assert_budget_envelope(event)
        domain_assert.assert_fields_equal(
            fixtures.read_proposal(world["proposal_id"]), {"status": "AWARDED"}
        )


class TestStaleProposalVersionOnCounter:
    """The term counter is the other write that carries a caller-supplied version."""

    def test_a_counter_carrying_a_superseded_bid_version_is_refused(self):
        """A view one version behind the bid is refused and opens no negotiation.

        "If that value does not equal the bid's current `version`, the counter is rejected with `ERR_STALE_PROPOSAL_VERSION` (HTTP 412)."

        Design: Corner/cross_cutting_complexity_layers/counter_with_a_stale_expected_proposal_version_is_refused_then_retried
        """
        world = fixtures.build_evaluated_bid()
        bid_version = fixtures.proposal_version(world["proposal_id"])

        response = api_client.create_counter(
            world["proposal_id"],
            factories.counter_payload(
                bid_version - 1,
                "RATE",
                proposed_numeric_value=239.00,
                planner_note="Stale read of the proposal.",
            ),
            PLANNER_HEADERS,
        )
        validate_error(response, ApiErrorId.STALE_PROPOSAL_VERSION.value, 412)

        counters, meta = validate_paginated(
            api_client.list_negotiation_counters(world["proposal_id"], PLANNER_HEADERS)
        )
        assert counters == [], "the refused counter must not be recorded"
        domain_assert.assert_integer(meta["total_count"], 0, "total_count")

        proposal = fixtures.read_proposal(world["proposal_id"])
        domain_assert.assert_fields_equal(
            proposal,
            {
                "status": "UNDER_REVIEW",
                "negotiation_round_count": 0,
                "version": bid_version,
            },
        )

    def test_the_retry_with_the_current_version_opens_round_one(self):
        """The retried counter is created as the bid's first open negotiation round.

        "A successful counter is created with HTTP 201 in `resolution` `OPEN`, with `resolved_at` null, with `initiated_by_user_id` set to the calling planner's `X-User-ID`, and with `round_seq` set to the bid's `negotiation_round_count` plus 1, giving a 1-based sequence in creation order within the bid."

        Design: Corner/cross_cutting_complexity_layers/counter_with_a_stale_expected_proposal_version_is_refused_then_retried
        """
        world = fixtures.build_evaluated_bid()
        bid_version = fixtures.proposal_version(world["proposal_id"])
        validate_error(
            api_client.create_counter(
                world["proposal_id"],
                factories.counter_payload(
                    bid_version - 1, "RATE", proposed_numeric_value=239.00
                ),
                PLANNER_HEADERS,
            ),
            ApiErrorId.STALE_PROPOSAL_VERSION.value,
            412,
        )

        counter = validate_success(
            api_client.create_counter(
                world["proposal_id"],
                factories.counter_payload(
                    bid_version,
                    "RATE",
                    proposed_numeric_value=239.00,
                    planner_note="Please hold the rate at 239.00.",
                ),
                PLANNER_HEADERS,
            ),
            201,
        )
        domain_assert.assert_fields_equal(
            counter,
            {
                "round_seq": 1,
                "term_category": "RATE",
                "resolution": "OPEN",
                "initiated_by_user_id": PLANNER_USER_ID,
            },
        )
        domain_assert.assert_money(
            counter["proposed_numeric_value"], 239.00, "proposed_numeric_value"
        )
        domain_assert.assert_nulls(counter, ["resolved_at"])

    def test_the_accepted_counter_advances_the_bid_by_exactly_one_round(self):
        """The bid's own negotiation counters move once, in the counter's request.

        "The bid then moves `UNDER_REVIEW → COUNTERED`, its `negotiation_round_count` increases by 1, and its `version` advances by 1."

        Design: Corner/cross_cutting_complexity_layers/counter_with_a_stale_expected_proposal_version_is_refused_then_retried
        """
        world = fixtures.build_evaluated_bid()
        bid_version = fixtures.proposal_version(world["proposal_id"])
        validate_error(
            api_client.create_counter(
                world["proposal_id"],
                factories.counter_payload(
                    bid_version - 1, "RATE", proposed_numeric_value=239.00
                ),
                PLANNER_HEADERS,
            ),
            ApiErrorId.STALE_PROPOSAL_VERSION.value,
            412,
        )
        validate_success(
            api_client.create_counter(
                world["proposal_id"],
                factories.counter_payload(
                    bid_version, "RATE", proposed_numeric_value=239.00
                ),
                PLANNER_HEADERS,
            ),
            201,
        )

        proposal = fixtures.read_proposal(world["proposal_id"])
        domain_assert.assert_fields_equal(
            proposal,
            {
                "status": "COUNTERED",
                "negotiation_round_count": 1,
                "version": bid_version + 1,
            },
        )


class TestEventVersionLadder:
    """The version a write returns is exactly what the next read observes."""

    def test_each_write_advances_the_event_version_by_exactly_one(self):
        """Creation, locking, an entry and its promotion walk the event 1 -> 4.

        "`version` is an integer that starts at 1 on creation and increases by exactly 1 on every mutation of that row."

        Design: Corner/cross_cutting_complexity_layers/event_version_increments_once_per_write_and_is_visible_on_read
        """
        fixtures.set_clock(SOURCING_CLOCK)
        fixtures.create_benchmark()
        venue = fixtures.create_venue()

        created = fixtures.create_event()
        domain_assert.assert_versioned_entity(created, 1)
        domain_assert.assert_fields_equal(created, {"status": "DRAFT"})
        domain_assert.assert_integer(
            fixtures.read_event(created["id"])["version"], 1, "version on read"
        )

        locked = fixtures.lock_event(created["id"])
        domain_assert.assert_fields_equal(
            locked, {"status": "REQUIREMENTS_LOCKED", "version": 2}
        )
        domain_assert.assert_integer(
            fixtures.read_event(created["id"])["version"], 2, "version on read"
        )

        entry = fixtures.add_entry(created["id"], venue["id"])
        after_entry = fixtures.read_event(created["id"])
        domain_assert.assert_fields_equal(
            after_entry, {"version": 3, "shortlisted_venue_count": 0}
        )

        fixtures.promote_entry(entry["id"])
        after_promotion = fixtures.read_event(created["id"])
        domain_assert.assert_fields_equal(
            after_promotion, {"version": 4, "shortlisted_venue_count": 1}
        )
        domain_assert.assert_versioned_entity(after_promotion, 4)

    def test_the_promoted_entry_carries_the_snapshot_taken_at_shortlisting(self):
        """The entry's programme snapshot is captured from the venue's live standing.

        "`program_status_at_shortlist` is set to `IN_PROGRAM` when the venue's `preferred_supplier_status` at that moment is `PREFERRED` or `CONDITIONAL`, and to `OUT_OF_PROGRAM` when it is anything else."

        Design: Corner/cross_cutting_complexity_layers/event_version_increments_once_per_write_and_is_visible_on_read
        """
        fixtures.set_clock(SOURCING_CLOCK)
        fixtures.create_benchmark()
        venue = fixtures.create_venue()
        domain_assert.assert_fields_equal(
            venue, {"preferred_supplier_status": "PREFERRED"}
        )
        event = fixtures.create_event()
        fixtures.lock_event(event["id"])
        entry = fixtures.add_entry(event["id"], venue["id"])
        fixtures.promote_entry(entry["id"])

        reread = fixtures.read_entry(entry["id"])
        domain_assert.assert_fields_equal(
            reread,
            {"status": "SHORTLISTED", "program_status_at_shortlist": "IN_PROGRAM"},
        )


class TestVolumeRebateTierBoundary:
    """One cent of F&B decides which rebate tier an award lands in."""

    def test_the_two_flat_bids_price_one_cent_apart(self):
        """Identical grids differing only in the F&B minimum straddle 150000.00.

        "The contracted-basis output is written to the bid's `total_cost_contracted_usd` on every submission and on every revision, and that figure — never the actualized one — is the only total the budget ceiling is tested against and the only total the volume-rebate tier reads."

        Design: Corner/cross_cutting_complexity_layers/volume_rebate_tier_opens_at_exactly_150000_pre_rebate_total
        """
        pair = _awarded_rebate_boundary_pair()
        at_minimum = fixtures.read_proposal(pair["at_the_minimum"]["proposal_id"])
        below = fixtures.read_proposal(pair["one_cent_below"]["proposal_id"])

        domain_assert.assert_money_field(
            at_minimum, "total_cost_contracted_usd", 150000.00
        )
        domain_assert.assert_money_field(below, "total_cost_contracted_usd", 149999.99)
        for bid in (at_minimum, below):
            domain_assert.assert_money_field(bid, "net_adr_usd", 200.00)
            domain_assert.assert_integer(
                bid["paid_room_nights"], 500, "paid_room_nights"
            )
            domain_assert.assert_variance_pct(bid["benchmark_variance_pct"], -0.2308)
            domain_assert.assert_fields_equal(bid, {"compliance_status": "COMPLIANT"})

    def test_the_inclusive_tier_minimum_splits_the_two_awards(self):
        """The dearer bid earns the 0.020 tier and ends up the cheaper contract.

        "The tier minimums are inclusive, so a pre-rebate total of exactly `150000.00` earns `0.020` and a pre-rebate total of exactly `400000.00` earns `0.035`."

        Design: Corner/cross_cutting_complexity_layers/volume_rebate_tier_opens_at_exactly_150000_pre_rebate_total
        """
        pair = _awarded_rebate_boundary_pair()
        rebated = pair["contract_at_minimum"]
        unrebated = pair["contract_below"]

        domain_assert.assert_money_field(rebated, "pre_rebate_total_usd", 150000.00)
        assert rebated["volume_rebate_pct"] == pytest.approx(0.0200, abs=1e-6)
        domain_assert.assert_money_field(rebated, "volume_rebate_usd", 3000.00)
        domain_assert.assert_money_field(rebated, "contracted_total_usd", 147000.00)

        domain_assert.assert_money_field(unrebated, "pre_rebate_total_usd", 149999.99)
        assert unrebated["volume_rebate_pct"] == pytest.approx(0.0000, abs=1e-6)
        domain_assert.assert_money_field(unrebated, "volume_rebate_usd", 0.00)
        domain_assert.assert_money_field(unrebated, "contracted_total_usd", 149999.99)

        domain_assert.assert_money(
            unrebated["contracted_total_usd"] - rebated["contracted_total_usd"],
            2999.99,
            "the cent of F&B costs this much",
        )

        for contract in (rebated, unrebated):
            domain_assert.assert_money_field(
                contract, "contracted_room_revenue_usd", 100000.00
            )
            domain_assert.assert_integer(
                contract["contracted_paid_room_nights"],
                500,
                "contracted_paid_room_nights",
            )
            domain_assert.assert_integer(
                contract["peak_rooms_per_night"], 167, "peak_rooms_per_night"
            )

    def test_the_rebate_leaves_more_budget_on_the_dearer_bid(self):
        """Each event commits its own contract's post-rebate total, not the bid's.

        "Awarding adds the new contract's `contracted_total_usd` to `committed_spend_usd`."

        Design: Corner/cross_cutting_complexity_layers/volume_rebate_tier_opens_at_exactly_150000_pre_rebate_total
        """
        pair = _awarded_rebate_boundary_pair()
        rebated_event = fixtures.read_event(pair["at_the_minimum"]["event_id"])
        unrebated_event = fixtures.read_event(pair["one_cent_below"]["event_id"])

        domain_assert.assert_money_field(
            rebated_event, "committed_spend_usd", 147000.00
        )
        domain_assert.assert_money_field(
            rebated_event, "budget_remaining_usd", 53000.00
        )
        domain_assert.assert_money_field(
            unrebated_event, "committed_spend_usd", 149999.99
        )
        domain_assert.assert_money_field(
            unrebated_event, "budget_remaining_usd", 50000.01
        )
        domain_assert.assert_budget_envelope(rebated_event)
        domain_assert.assert_budget_envelope(unrebated_event)


class TestCountersignatureConsistency:
    """The request that completes the join already returns the joined state."""

    def test_the_countersign_response_itself_carries_the_executed_join(
        self, executed_contract
    ):
        """Both dimensions and the execution stamp are in the countersign body.

        "On success the contract moves `PLANNER_SIGNED → COUNTERSIGNED`, and if `approval_state` is already `APPROVED` the contract immediately joins to `EXECUTED` in the same request."

        Design: Corner/consistency_model/countersignature_response_already_shows_the_executed_join_and_its_cascade
        """
        countersign_body = executed_contract["contract"]
        domain_assert.assert_fields_equal(
            countersign_body,
            {
                "signature_state": "EXECUTED",
                "approval_state": "APPROVED",
                "venue_signatory_name": "Rui Costa",
                "executed_at": SOURCING_CLOCK,
            },
        )

        reread = fixtures.read_contract(executed_contract["contract_id"])
        domain_assert.assert_fields_equal(
            reread,
            {
                "signature_state": countersign_body["signature_state"],
                "executed_at": countersign_body["executed_at"],
                "version": countersign_body["version"],
            },
        )

    def test_the_whole_cascade_is_visible_on_the_first_read_of_every_row(
        self, executed_contract
    ):
        """One read each of the event, the entry and the venue observes the join.

        "Every rollup field is correct the instant the mutating request returns, and each touched row independently refreshes its `updated_at` and advances its `version`."

        Design: Corner/consistency_model/countersignature_response_already_shows_the_executed_join_and_its_cascade
        """
        event = fixtures.read_event(executed_contract["event_id"])
        domain_assert.assert_fields_equal(
            event,
            {
                "status": "CONTRACTED",
                "awarded_proposal_id": executed_contract["proposal_id"],
            },
        )
        domain_assert.assert_money_field(event, "committed_spend_usd", 432170.27)
        domain_assert.assert_money_field(event, "cancellation_liability_usd", 0.00)
        domain_assert.assert_budget_envelope(event)

        entry = fixtures.read_entry(executed_contract["entry_id"])
        domain_assert.assert_fields_equal(entry, {"status": "AWARDED"})

        venue = fixtures.read_venue(executed_contract["venue_id"])
        domain_assert.assert_room_night_inventory(venue, 587)
