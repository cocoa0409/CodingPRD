"""Guard precedence and exact-boundary behaviour for the sourcing API.

Two families of behaviour are exercised here. The first is the fixed global
ordering of the validation ladder: when a single request violates more than one
rule, only the highest-precedence refusal may be observed, and relaxing that
rule must then expose the lower one for an otherwise identical request. The
second is arithmetic that must land exactly on a documented threshold - money to
the cent against a budget ceiling, and integer peak-room capacity against a
venue's guest-room count.
"""

import pytest

from test_helpers import (
    ApiErrorId,
    PLANNER_HEADERS,
    PROGRAM_ADMIN_HEADERS,
    api_client,
    assertions as domain_assert,
    factories,
    fixtures,
    make_venue_rep_headers,
    validate_error,
    validate_paginated,
    validate_success,
)

# --------------------------------------------------------------------------
# Module-private state builders
#
# Every scenario below needs a chain the shared builders do not assemble, so
# each is composed here from the documented endpoints only.
# --------------------------------------------------------------------------

# A TIER_2 / TRAINING programme, so the two sibling bids are priced against a
# 210.00 benchmark ADR rather than the TIER_1 conference default.
_TRAINING_BENCHMARK = {
    "destination_tier": "TIER_2",
    "program_type": "TRAINING",
    "benchmark_adr_usd": 210.00,
    "benchmark_service_charge_pct": 0.22,
    "benchmark_tax_pct": 0.14,
}

_LAKEVIEW_VENUE = {
    "name": "Lakeview Training Centre",
    "city": "Warsaw",
    "country": "PL",
    "destination_tier": "TIER_2",
    "guest_rooms_total": 200,
    "largest_space_sqft": 6000,
    "preferred_supplier_status": "PREFERRED",
}

_VISTULA_VENUE = {
    "name": "Vistula Conference Hotel",
    "city": "Krakow",
    "country": "PL",
    "destination_tier": "TIER_2",
    "guest_rooms_total": 180,
    "largest_space_sqft": 5200,
    "preferred_supplier_status": "PREFERRED",
}

# A three-night training meeting whose ceiling is the cheaper bid's total to the
# cent.
_TRAINING_EVENT = {
    "name": "Regional Trainer Bootcamp 2027",
    "program_type": "TRAINING",
    "start_date": "2027-05-10",
    "end_date": "2027-05-13",
    "peak_attendees": 40,
    "requested_room_nights": 120,
    "largest_meeting_space_sqft": 4500,
    "budget_ceiling_usd": 69722.61,
    "preferred_program_only": False,
}

_AT_CEILING_GRID = {
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

# The identical grid except for one extra cent of food-and-beverage minimum.
_ONE_CENT_OVER_GRID = dict(_AT_CEILING_GRID, fnb_minimum_usd=20000.01)

# A second, date-overlapping meeting at the same venue that needs exactly one
# more peak room.
_OVERLAP_EVENT = {
    "name": "Executive Briefing Overlap 2027",
    "program_type": "USER_CONFERENCE",
    "start_date": "2027-03-16",
    "end_date": "2027-03-19",
    "peak_attendees": 12,
    "requested_room_nights": 3,
    "largest_meeting_space_sqft": 3000,
    "budget_ceiling_usd": 50000.00,
    "preferred_program_only": False,
}

_OVERLAP_GRID = {
    "room_nights_offered": 3,
    "comp_room_ratio": 0,
    "av_estimate_usd": 0.00,
    "fnb_minimum_usd": 0.00,
    "concession_credit_usd": 0.00,
    "rebooking_credit_pct": 0.40,
}


def _build_cent_boundary_world():
    """Two sibling bids on one training meeting, priced one cent apart.

    Both bids are submitted, the round is closed and both are priced on the
    contracted basis, so both sit ``UNDER_REVIEW`` and either could be awarded.
    """
    world = fixtures.build_two_venue_round(
        benchmark_overrides=_TRAINING_BENCHMARK,
        venue_overrides=_LAKEVIEW_VENUE,
        second_venue_overrides=_VISTULA_VENUE,
        event_overrides=_TRAINING_EVENT,
    )
    fixtures.submit_bid(world["proposal_id"], world["venue_id"], **_AT_CEILING_GRID)
    fixtures.submit_bid(world["proposal_b_id"], world["venue_b_id"], **_ONE_CENT_OVER_GRID)
    world["rfp"] = fixtures.close_rfp(world["rfp_id"])
    fixtures.evaluate_bid(world["proposal_id"])
    fixtures.evaluate_bid(world["proposal_b_id"])
    world["proposal"] = fixtures.read_proposal(world["proposal_id"])
    world["proposal_b"] = fixtures.read_proposal(world["proposal_b_id"])
    return world


def _plan_inspection_response(entry_id, **overrides):
    """Attempt to plan an inspection and hand back the raw response."""
    return api_client.create_site_inspection(
        factories.site_inspection_payload(entry_id, **overrides), PLANNER_HEADERS
    )


def _award_response(event_id, proposal_id):
    """Attempt an award at the event's current version, returning the response."""
    payload = factories.award_payload(proposal_id, fixtures.event_version(event_id))
    return api_client.award_event(event_id, payload, PLANNER_HEADERS)


def _award_overlapping_planner_signed_contract(venue_id):
    """Source, award and planner-sign a second meeting at the same venue.

    The second meeting's dates overlap the first one's, its block is three paid
    nights over a three-night span, and its contract stops one countersignature
    short of execution.
    """
    event = fixtures.create_event(**_OVERLAP_EVENT)
    fixtures.lock_event(event["id"])
    entry = fixtures.add_entry(event["id"], venue_id, rank_seq=1, inspection_required=False)
    fixtures.promote_entry(entry["id"])
    rfp = fixtures.create_rfp(event["id"])
    rfp = fixtures.issue_rfp(rfp["id"])
    proposal = fixtures.find_invited_proposal(rfp["id"], venue_id)
    fixtures.submit_bid(proposal["id"], venue_id, **_OVERLAP_GRID)
    fixtures.close_rfp(rfp["id"])
    fixtures.evaluate_bid(proposal["id"])
    contract = fixtures.award_bid(event["id"], proposal["id"])
    contract = fixtures.sign_contract(contract["id"])
    return {
        "event": event,
        "event_id": event["id"],
        "entry_id": entry["id"],
        "proposal_id": proposal["id"],
        "contract": contract,
        "contract_id": contract["id"],
    }


def _build_capacity_boundary_world():
    """A venue whose guest-room count is exactly the first contract's peak need.

    The primary contract is fully approved and planner-signed, and a second
    date-overlapping contract at the same venue is planner-signed too, so the
    capacity guard can be observed at both the equality and the exceeding case.
    """
    world = fixtures.build_routed_contract(venue_overrides={"guest_rooms_total": 196})
    fixtures.approve_all_steps(world["contract_id"])
    world["contract"] = fixtures.sign_contract(world["contract_id"])
    world["overlap"] = _award_overlapping_planner_signed_contract(world["venue_id"])
    return world


class TestAwardGuardPrecedence:
    """The award's lifecycle-state guard outranks its budget-ceiling guard."""

    def test_open_round_award_reports_the_event_state_not_the_budget(self):
        """An award attempted while the round is still open reports the state guard.

        PRD: "An event in any other lifecycle state is rejected with `ERR_EVENT_STATE_INVALID`, and an event already in `CONTRACTED` is rejected with the more specific `ERR_CONTRACT_ALREADY_EXECUTED` as described in section 2.8."

        Design: Difficulty/priority_pair_validation_conflict/award_event_state_beats_budget_ceiling
        """
        world = fixtures.build_evaluated_bid(event_overrides={"budget_ceiling_usd": 400000.00})

        response = _award_response(world["event_id"], world["proposal_id"])

        validate_error(response, ApiErrorId.EVENT_STATE_INVALID.value, 409)

    def test_open_round_award_does_not_report_the_lower_ranked_ceiling_breach(self):
        """The lower-ranked ceiling breach is masked even though it is equally true.

        PRD: "Checks are therefore evaluated in a fixed global order, and the **first** failing check determines the response; no later check may mask an earlier one."

        Design: Difficulty/priority_pair_validation_conflict/award_event_state_beats_budget_ceiling
        """
        world = fixtures.build_evaluated_bid(event_overrides={"budget_ceiling_usd": 400000.00})
        priced = fixtures.read_proposal(world["proposal_id"])
        domain_assert.assert_money(
            priced["total_cost_contracted_usd"], 447844.84, "bid contracted total"
        )

        response = _award_response(world["event_id"], world["proposal_id"])

        body = response.json()
        assert body["data"]["error_id"] != ApiErrorId.BUDGET_CEILING_EXCEEDED.value

    def test_refused_award_leaves_the_event_row_untouched(self):
        """No part of the award's event effects fires when the award is refused.

        PRD: "The event moves to `AWARDED`, its `awarded_proposal_id` is set to the winning bid, its `committed_spend_usd` is set to the contract's `contracted_total_usd`, its `budget_remaining_usd` is recomputed from the money identity in section 2.10, and its `version` advances by 1."

        Design: Difficulty/priority_pair_validation_conflict/award_event_state_beats_budget_ceiling
        """
        world = fixtures.build_evaluated_bid(event_overrides={"budget_ceiling_usd": 400000.00})
        before = fixtures.read_event(world["event_id"])

        _award_response(world["event_id"], world["proposal_id"])

        after = fixtures.read_event(world["event_id"])
        assert after["status"] == "SOURCING"
        assert after["awarded_proposal_id"] is None
        domain_assert.assert_money(after["committed_spend_usd"], 0.00, "committed spend")
        domain_assert.assert_money(after["budget_remaining_usd"], 400000.00, "budget remaining")
        assert after["version"] == before["version"]
        domain_assert.assert_budget_envelope(after)

    def test_refused_award_mints_no_contract(self):
        """A refused award creates no contract row for the meeting.

        PRD: "The response is HTTP 201 and its body is the newly created contract."

        Design: Difficulty/priority_pair_validation_conflict/award_event_state_beats_budget_ceiling
        """
        world = fixtures.build_evaluated_bid(event_overrides={"budget_ceiling_usd": 400000.00})

        _award_response(world["event_id"], world["proposal_id"])

        rows, _meta = validate_paginated(
            api_client.list_contracts(PLANNER_HEADERS, {"event_id": world["event_id"]})
        )
        assert rows == []

    def test_closing_the_round_moves_the_meeting_into_bid_review(self):
        """Closing the round is what satisfies the award's lifecycle-state guard.

        PRD: "The parent event moves `SOURCING → BID_REVIEW`, its `best_total_cost_usd` is recomputed, and its `version` advances by 1."

        Design: Difficulty/priority_pair_validation_conflict/award_event_state_beats_budget_ceiling
        """
        world = fixtures.build_evaluated_bid(event_overrides={"budget_ceiling_usd": 400000.00})
        _award_response(world["event_id"], world["proposal_id"])

        fixtures.close_rfp(world["rfp_id"])

        assert fixtures.read_event(world["event_id"])["status"] == "BID_REVIEW"

    def test_closed_round_award_now_reports_the_budget_ceiling_breach(self):
        """With the state guard satisfied the ceiling guard becomes observable.

        PRD: "Finally the winning bid's `total_cost_contracted_usd` must be at most the event's `budget_ceiling_usd`, otherwise `ERR_BUDGET_CEILING_EXCEEDED`; equality is allowed, so a bid priced at exactly the ceiling is awardable."

        Design: Difficulty/priority_pair_validation_conflict/award_event_state_beats_budget_ceiling
        """
        world = fixtures.build_evaluated_bid(event_overrides={"budget_ceiling_usd": 400000.00})
        _award_response(world["event_id"], world["proposal_id"])
        fixtures.close_rfp(world["rfp_id"])

        response = _award_response(world["event_id"], world["proposal_id"])

        validate_error(response, ApiErrorId.BUDGET_CEILING_EXCEEDED.value, 422)

    def test_both_refusals_leave_the_bid_and_the_money_envelope_intact(self):
        """Neither refusal moves the bid out of review or spends any budget.

        PRD: "At every observable instant, and for every meeting event, the sum of `budget_remaining_usd`, `committed_spend_usd` and `cancellation_liability_usd` equals `budget_ceiling_usd` exactly."

        Design: Difficulty/priority_pair_validation_conflict/award_event_state_beats_budget_ceiling
        """
        world = fixtures.build_evaluated_bid(event_overrides={"budget_ceiling_usd": 400000.00})
        _award_response(world["event_id"], world["proposal_id"])
        fixtures.close_rfp(world["rfp_id"])
        _award_response(world["event_id"], world["proposal_id"])

        assert fixtures.read_proposal(world["proposal_id"])["status"] == "UNDER_REVIEW"
        event = fixtures.read_event(world["event_id"])
        domain_assert.assert_money(event["budget_remaining_usd"], 400000.00, "budget remaining")
        domain_assert.assert_money(event["committed_spend_usd"], 0.00, "committed spend")
        domain_assert.assert_budget_envelope(event)


class TestSiteInspectionGuardPrecedence:
    """The supplier-safety guard outranks the inspection's temporal exclusions."""

    _BLACKOUT_WINDOW = {
        "window_start": "2027-03-16T09:00:00.000Z",
        "window_end": "2027-03-16T13:00:00.000Z",
    }

    def _suspended_world(self):
        world = fixtures.build_sourcing_world()
        fixtures.set_preferred_status(world["venue_id"], "SUSPENDED")
        return world

    def test_suspended_supplier_is_reported_ahead_of_the_meeting_blackout(self):
        """A suspended venue is refused even though the window also hits the meeting.

        PRD: "The venue's `preferred_supplier_status` must not be `SUSPENDED`, otherwise `ERR_VENUE_SUSPENDED`."

        Design: Difficulty/priority_pair_validation_conflict/site_inspection_venue_suspended_beats_event_window_overlap
        """
        world = self._suspended_world()

        response = _plan_inspection_response(world["entry_id"], **self._BLACKOUT_WINDOW)

        validate_error(response, ApiErrorId.VENUE_SUSPENDED.value, 422)

    def test_suspended_supplier_masks_the_lower_ranked_blackout_breach(self):
        """The blackout refusal must not surface while the supplier guard is failing.

        PRD: "Checks are therefore evaluated in a fixed global order, and the **first** failing check determines the response; no later check may mask an earlier one."

        Design: Difficulty/priority_pair_validation_conflict/site_inspection_venue_suspended_beats_event_window_overlap
        """
        world = self._suspended_world()

        response = _plan_inspection_response(world["entry_id"], **self._BLACKOUT_WINDOW)

        body = response.json()
        assert body["data"]["error_id"] != ApiErrorId.INSPECTION_WINDOW_OVERLAPS_EVENT.value

    def test_refused_plan_leaves_the_entry_and_its_inspection_ledger_untouched(self):
        """None of the successful-plan effects fire when the plan is refused.

        PRD: "A successful plan creates the inspection in `PLANNED` with `findings_score` null and `cancel_reason` null, moves the parent entry `SHORTLISTED → INSPECTION_SCHEDULED`, increases that entry's `inspection_count` by 1 and advances the entry's `version` by 1."

        Design: Difficulty/priority_pair_validation_conflict/site_inspection_venue_suspended_beats_event_window_overlap
        """
        world = self._suspended_world()

        _plan_inspection_response(world["entry_id"], **self._BLACKOUT_WINDOW)

        entry = fixtures.read_entry(world["entry_id"])
        assert entry["status"] == "SHORTLISTED"
        domain_assert.assert_integer(entry["inspection_count"], 0, "inspection count")
        rows, _meta = validate_paginated(
            api_client.list_site_inspections(
                PLANNER_HEADERS, {"shortlist_entry_id": world["entry_id"]}
            )
        )
        assert rows == []

    def test_reinstated_supplier_exposes_the_meeting_blackout_for_the_same_window(self):
        """Lifting the suspension surfaces the temporal exclusion for an identical body.

        PRD: "And two temporal exclusions hold: the inspection window must not intersect the parent meeting event's own fully-closed date interval, which runs from the event's `start_date` at `00:00:00.000Z` through its `end_date` at `23:59:59.999Z` inclusive — an intersection is rejected with `ERR_INSPECTION_WINDOW_OVERLAPS_EVENT`, because a site visit cannot be scheduled while the meeting itself is in the building — and the new buffered occupation interval must not intersect the buffered occupation interval of any other inspection on the same `venue_id` whose `status` is `PLANNED` or `COMPLETED`, an intersection being rejected with `ERR_INSPECTION_WINDOW_CONFLICT`."

        Design: Difficulty/priority_pair_validation_conflict/site_inspection_venue_suspended_beats_event_window_overlap
        """
        world = self._suspended_world()
        _plan_inspection_response(world["entry_id"], **self._BLACKOUT_WINDOW)
        fixtures.set_preferred_status(world["venue_id"], "PREFERRED")

        response = _plan_inspection_response(world["entry_id"], **self._BLACKOUT_WINDOW)

        validate_error(response, ApiErrorId.INSPECTION_WINDOW_OVERLAPS_EVENT.value, 422)

    def test_window_clear_of_both_guards_is_planned_with_its_buffered_occupation(self):
        """A window outside the meeting is admitted and carries its buffered end.

        PRD: "From those inputs the server derives `occupied_until` as `window_end` advanced by `travel_buffer_minutes`, and treats the half-open interval from `window_start` up to but not including `occupied_until` as the venue's buffered occupation interval."

        Design: Difficulty/priority_pair_validation_conflict/site_inspection_venue_suspended_beats_event_window_overlap
        """
        world = self._suspended_world()
        _plan_inspection_response(world["entry_id"], **self._BLACKOUT_WINDOW)
        fixtures.set_preferred_status(world["venue_id"], "PREFERRED")
        _plan_inspection_response(world["entry_id"], **self._BLACKOUT_WINDOW)

        response = _plan_inspection_response(
            world["entry_id"],
            window_start="2026-09-10T09:00:00.000Z",
            window_end="2026-09-10T13:00:00.000Z",
            travel_buffer_minutes=90,
        )

        inspection = validate_success(response, 201)
        assert inspection["status"] == "PLANNED"
        assert inspection["occupied_until"] == "2026-09-10T14:30:00.000Z"

    def test_successful_plan_schedules_the_inspection_on_its_entry(self):
        """The admitted plan advances the parent entry and its inspection count.

        PRD: "A successful plan creates the inspection in `PLANNED` with `findings_score` null and `cancel_reason` null, moves the parent entry `SHORTLISTED → INSPECTION_SCHEDULED`, increases that entry's `inspection_count` by 1 and advances the entry's `version` by 1."

        Design: Difficulty/priority_pair_validation_conflict/site_inspection_venue_suspended_beats_event_window_overlap
        """
        world = self._suspended_world()
        fixtures.set_preferred_status(world["venue_id"], "PREFERRED")

        fixtures.plan_inspection(
            world["entry_id"],
            window_start="2026-09-10T09:00:00.000Z",
            window_end="2026-09-10T13:00:00.000Z",
            travel_buffer_minutes=90,
        )

        entry = fixtures.read_entry(world["entry_id"])
        assert entry["status"] == "INSPECTION_SCHEDULED"
        domain_assert.assert_integer(entry["inspection_count"], 1, "inspection count")

    def test_inspection_copies_the_venue_from_its_parent_entry(self):
        """The admitted inspection points at the entry's venue.

        PRD: "The inspection also copies `venue_id` from the parent shortlist entry at creation and never re-derives it, so a later change on the entry cannot move an inspection to a different venue."

        Design: Difficulty/priority_pair_validation_conflict/site_inspection_venue_suspended_beats_event_window_overlap
        """
        world = self._suspended_world()
        fixtures.set_preferred_status(world["venue_id"], "PREFERRED")

        inspection = fixtures.plan_inspection(
            world["entry_id"],
            window_start="2026-09-10T09:00:00.000Z",
            window_end="2026-09-10T13:00:00.000Z",
            travel_buffer_minutes=90,
        )

        assert inspection["venue_id"] == world["venue_id"]


class TestAwardBudgetCeilingToTheCent:
    """The ceiling test is inclusive: equality is awardable, one cent over is not."""

    def test_sibling_bids_are_priced_exactly_one_cent_apart(self):
        """The two contracted-basis totals straddle the ceiling by a single cent.

        PRD: "The contracted-basis output is written to the bid's `total_cost_contracted_usd` on every submission and on every revision, and that figure — never the actualized one — is the only total the budget ceiling is tested against and the only total the volume-rebate tier reads."

        Design: Difficulty/boundary_precision_check/award_budget_ceiling_equality_versus_one_cent_over
        """
        world = _build_cent_boundary_world()

        domain_assert.assert_money(
            world["proposal"]["total_cost_contracted_usd"], 69722.61, "at-ceiling bid total"
        )
        domain_assert.assert_money(
            world["proposal_b"]["total_cost_contracted_usd"], 69722.62, "one-cent-over bid total"
        )

    def test_one_cent_over_the_ceiling_is_refused(self):
        """A bid a single cent above the ceiling cannot be awarded.

        PRD: "Finally the winning bid's `total_cost_contracted_usd` must be at most the event's `budget_ceiling_usd`, otherwise `ERR_BUDGET_CEILING_EXCEEDED`; equality is allowed, so a bid priced at exactly the ceiling is awardable."

        Design: Difficulty/boundary_precision_check/award_budget_ceiling_equality_versus_one_cent_over
        """
        world = _build_cent_boundary_world()

        response = _award_response(world["event_id"], world["proposal_b_id"])

        validate_error(response, ApiErrorId.BUDGET_CEILING_EXCEEDED.value, 422)

    def test_refused_award_leaves_the_meeting_in_bid_review(self):
        """The refused award leaves the meeting unawarded.

        PRD: "The event moves to `AWARDED`, its `awarded_proposal_id` is set to the winning bid, its `committed_spend_usd` is set to the contract's `contracted_total_usd`, its `budget_remaining_usd` is recomputed from the money identity in section 2.10, and its `version` advances by 1."

        Design: Difficulty/boundary_precision_check/award_budget_ceiling_equality_versus_one_cent_over
        """
        world = _build_cent_boundary_world()

        _award_response(world["event_id"], world["proposal_b_id"])

        event = fixtures.read_event(world["event_id"])
        assert event["status"] == "BID_REVIEW"
        assert event["awarded_proposal_id"] is None

    def test_bid_priced_exactly_at_the_ceiling_is_awarded(self):
        """Dead equality with the ceiling is admitted.

        PRD: "Finally the winning bid's `total_cost_contracted_usd` must be at most the event's `budget_ceiling_usd`, otherwise `ERR_BUDGET_CEILING_EXCEEDED`; equality is allowed, so a bid priced at exactly the ceiling is awardable."

        Design: Difficulty/boundary_precision_check/award_budget_ceiling_equality_versus_one_cent_over
        """
        world = _build_cent_boundary_world()
        _award_response(world["event_id"], world["proposal_b_id"])

        response = api_client.award_event(
            world["event_id"],
            factories.award_payload(
                world["proposal_id"], fixtures.event_version(world["event_id"])
            ),
            PLANNER_HEADERS,
        )

        contract = validate_success(response, 201)
        domain_assert.assert_money(
            contract["pre_rebate_total_usd"], 69722.61, "pre-rebate total"
        )

    def test_award_below_the_first_rebate_tier_earns_no_rebate(self):
        """A pre-rebate total under the first tier minimum carries a zero rebate.

        PRD: "The rebate percentage is then chosen from that pre-rebate figure: a `pre_rebate_total_usd` below `150000.00` earns `volume_rebate_pct` of `0.000`; a `pre_rebate_total_usd` at or above `150000.00` but below `400000.00` earns `0.020`; and a `pre_rebate_total_usd` at or above `400000.00` earns `0.035`."

        Design: Difficulty/boundary_precision_check/award_budget_ceiling_equality_versus_one_cent_over
        """
        world = _build_cent_boundary_world()
        _award_response(world["event_id"], world["proposal_b_id"])

        contract = fixtures.award_bid(world["event_id"], world["proposal_id"])

        assert contract["volume_rebate_pct"] == pytest.approx(0.000, abs=0.00005)
        domain_assert.assert_money(contract["volume_rebate_usd"], 0.00, "volume rebate")
        domain_assert.assert_money(
            contract["contracted_total_usd"], 69722.61, "contracted total"
        )

    def test_contract_freezes_the_paid_block_and_its_peak_occupancy(self):
        """The contract carries the bid's paid nights and the rounded-up peak rooms.

        PRD: "A contract's `peak_rooms_per_night` is derived from the contracted block and the meeting's length: it is the contract's `contracted_paid_room_nights` divided by the parent meeting event's `nights_span`, rounded **up** to the next whole room."

        Design: Difficulty/boundary_precision_check/award_budget_ceiling_equality_versus_one_cent_over
        """
        world = _build_cent_boundary_world()

        contract = fixtures.award_bid(world["event_id"], world["proposal_id"])

        domain_assert.assert_integer(
            contract["contracted_paid_room_nights"], 118, "contracted paid room nights"
        )
        domain_assert.assert_integer(
            contract["peak_rooms_per_night"], 40, "peak rooms per night"
        )

    def test_award_at_the_ceiling_leaves_no_budget_remaining(self):
        """Committing exactly the ceiling drains the remaining budget to zero.

        PRD: "At every observable instant, and for every meeting event, the sum of `budget_remaining_usd`, `committed_spend_usd` and `cancellation_liability_usd` equals `budget_ceiling_usd` exactly."

        Design: Difficulty/boundary_precision_check/award_budget_ceiling_equality_versus_one_cent_over
        """
        world = _build_cent_boundary_world()

        fixtures.award_bid(world["event_id"], world["proposal_id"])

        event = fixtures.read_event(world["event_id"])
        domain_assert.assert_money(event["committed_spend_usd"], 69722.61, "committed spend")
        domain_assert.assert_money(event["budget_remaining_usd"], 0.00, "budget remaining")
        domain_assert.assert_budget_envelope(event)

    def test_award_rejects_the_losing_sibling_and_eliminates_its_entry(self):
        """The award closes out the competing bid and its shortlist entry.

        PRD: "For each bid rejected at level 2, that bid's shortlist entry moves to `ELIMINATED` with `elimination_reason` set to `NOT_SELECTED`."

        Design: Difficulty/boundary_precision_check/award_budget_ceiling_equality_versus_one_cent_over
        """
        world = _build_cent_boundary_world()

        fixtures.award_bid(world["event_id"], world["proposal_id"])

        assert fixtures.read_proposal(world["proposal_id"])["status"] == "AWARDED"
        assert fixtures.read_proposal(world["proposal_b_id"])["status"] == "REJECTED"
        entry_b = fixtures.read_entry(world["entry_b_id"])
        assert entry_b["status"] == "ELIMINATED"
        assert entry_b["elimination_reason"] == "NOT_SELECTED"


class TestCountersignRoomBlockCapacityBoundary:
    """The room-block guard admits exact equality and refuses one room more."""

    def test_peak_rooms_per_night_rounds_up_to_the_next_whole_room(self):
        """Five hundred and eighty-seven paid nights over three nights need 196 rooms.

        PRD: "A contract's `peak_rooms_per_night` is derived from the contracted block and the meeting's length: it is the contract's `contracted_paid_room_nights` divided by the parent meeting event's `nights_span`, rounded **up** to the next whole room."

        Design: Difficulty/boundary_precision_check/countersign_room_block_capacity_at_exact_guest_room_count
        """
        world = _build_capacity_boundary_world()

        contract = fixtures.read_contract(world["contract_id"])
        domain_assert.assert_integer(
            contract["contracted_paid_room_nights"], 587, "contracted paid room nights"
        )
        domain_assert.assert_integer(
            contract["peak_rooms_per_night"], 196, "peak rooms per night"
        )

    def test_countersign_at_the_exact_guest_room_count_executes(self):
        """A peak need that lands exactly on the venue's inventory is admitted.

        PRD: "The comparison is inclusive, so a request that lands exactly on `guest_rooms_total` is allowed; only exceeding it is refused."

        Design: Difficulty/boundary_precision_check/countersign_room_block_capacity_at_exact_guest_room_count
        """
        world = _build_capacity_boundary_world()
        venue = validate_success(
            api_client.get_venue(world["venue_id"], PROGRAM_ADMIN_HEADERS), 200
        )
        domain_assert.assert_integer(venue["guest_rooms_total"], 196, "guest rooms total")

        response = api_client.countersign_contract(
            world["contract_id"],
            factories.countersign_payload(),
            make_venue_rep_headers(world["venue_id"]),
        )

        contract = validate_success(response, 200)
        assert contract["signature_state"] == "EXECUTED"
        assert contract["executed_at"] == "2026-08-05T09:00:00.000Z"

    def test_execution_blocks_the_contracted_room_nights_at_the_venue(self):
        """Reaching execution moves the venue's room-night inventory.

        PRD: "The venue's `blocked_room_nights` increases by the contract's `contracted_paid_room_nights`, restoring the room-night identity of section 2.10."

        Design: Difficulty/boundary_precision_check/countersign_room_block_capacity_at_exact_guest_room_count
        """
        world = _build_capacity_boundary_world()

        fixtures.countersign_contract(world["contract_id"], world["venue_id"])

        domain_assert.assert_room_night_inventory(fixtures.read_venue(world["venue_id"]), 587)

    def test_execution_contracts_the_meeting_and_awards_its_entry(self):
        """Execution advances the meeting and its winning shortlist entry.

        PRD: "The awarded shortlist entry moves `RFP_ISSUED → AWARDED`, which is its second terminal state alongside `ELIMINATED`."

        Design: Difficulty/boundary_precision_check/countersign_room_block_capacity_at_exact_guest_room_count
        """
        world = _build_capacity_boundary_world()

        fixtures.countersign_contract(world["contract_id"], world["venue_id"])

        assert fixtures.read_event(world["event_id"])["status"] == "CONTRACTED"
        assert fixtures.read_entry(world["entry_id"])["status"] == "AWARDED"

    def test_overlapping_contract_freezes_a_single_peak_room(self):
        """The date-overlapping meeting needs exactly one more peak room.

        PRD: "A contract's `peak_rooms_per_night` is derived from the contracted block and the meeting's length: it is the contract's `contracted_paid_room_nights` divided by the parent meeting event's `nights_span`, rounded **up** to the next whole room."

        Design: Difficulty/boundary_precision_check/countersign_room_block_capacity_at_exact_guest_room_count
        """
        world = _build_capacity_boundary_world()

        overlap = fixtures.read_contract(world["overlap"]["contract_id"])
        domain_assert.assert_integer(
            overlap["contracted_paid_room_nights"], 3, "contracted paid room nights"
        )
        domain_assert.assert_integer(
            overlap["peak_rooms_per_night"], 1, "peak rooms per night"
        )

    def test_one_room_beyond_the_inventory_is_refused(self):
        """A second overlapping countersignature taking the aggregate to 197 is refused.

        PRD: "The guard collects the venue's other contracts whose `signature_state` is `EXECUTED` and whose meeting event's date range overlaps this event's on a fully-closed basis — that is, the other event's `start_date` is on or before this event's `end_date` and the other event's `end_date` is on or after this event's `start_date` — sums their `peak_rooms_per_night`, adds this contract's `peak_rooms_per_night`, and requires the result to be at most the venue's `guest_rooms_total`."

        Design: Difficulty/boundary_precision_check/countersign_room_block_capacity_at_exact_guest_room_count
        """
        world = _build_capacity_boundary_world()
        fixtures.countersign_contract(world["contract_id"], world["venue_id"])

        response = api_client.countersign_contract(
            world["overlap"]["contract_id"],
            factories.countersign_payload(),
            make_venue_rep_headers(world["venue_id"]),
        )

        validate_error(response, ApiErrorId.VENUE_ROOM_BLOCK_CAPACITY_EXCEEDED.value, 422)

    def test_refused_countersign_leaves_the_second_contract_planner_signed(self):
        """The refused countersignature persists nothing on the second contract.

        PRD: "On success the contract moves `PLANNER_SIGNED → COUNTERSIGNED`, and if `approval_state` is already `APPROVED` the contract immediately joins to `EXECUTED` in the same request."

        Design: Difficulty/boundary_precision_check/countersign_room_block_capacity_at_exact_guest_room_count
        """
        world = _build_capacity_boundary_world()
        fixtures.countersign_contract(world["contract_id"], world["venue_id"])

        api_client.countersign_contract(
            world["overlap"]["contract_id"],
            factories.countersign_payload(),
            make_venue_rep_headers(world["venue_id"]),
        )

        overlap = fixtures.read_contract(world["overlap"]["contract_id"])
        assert overlap["signature_state"] == "PLANNER_SIGNED"
        assert overlap["venue_signatory_name"] is None
        assert fixtures.read_event(world["overlap"]["event_id"])["status"] == "AWARDED"

    def test_refused_countersign_does_not_move_room_night_inventory(self):
        """The capacity guard fires before any inventory increment.

        PRD: "The guard is evaluated before the `blocked_room_nights` increment, never after."

        Design: Difficulty/boundary_precision_check/countersign_room_block_capacity_at_exact_guest_room_count
        """
        world = _build_capacity_boundary_world()
        fixtures.countersign_contract(world["contract_id"], world["venue_id"])

        api_client.countersign_contract(
            world["overlap"]["contract_id"],
            factories.countersign_payload(),
            make_venue_rep_headers(world["venue_id"]),
        )

        domain_assert.assert_room_night_inventory(fixtures.read_venue(world["venue_id"]), 587)
