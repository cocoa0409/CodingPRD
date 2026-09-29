"""Cross-entity state dependencies, temporal windows and conserved quantities.

Three related themes are covered. First, requests whose legality is decided by
the state of a *different* row than the one being mutated - a counter refused
because its parent solicitation round closed, an inspection refused because its
parent shortlist entry was never committed. Second, the two interval semantics
the inspection endpoint uses: a half-open buffered occupation interval on the
venue, and a fully-closed blackout interval on the meeting's own dates. Third,
the two quantities the model conserves - the venue's integer room-night
inventory and the meeting's money envelope - observed across a compensating
action that must undo exactly what its forward move added.
"""

import pytest

from test_helpers import (
    ApiErrorId,
    PLANNER_HEADERS,
    api_client,
    assertions as domain_assert,
    factories,
    fixtures,
    validate_error,
    validate_paginated,
    validate_success,
)

# --------------------------------------------------------------------------
# Module-private state builders
# --------------------------------------------------------------------------

# A second meeting whose dates sit well clear of the first one's, used whenever
# two entries must share a single venue as a bookable resource.
_SECOND_MEETING = {
    "name": "Field Enablement Summit 2027",
    "program_type": "TRAINING",
    "start_date": "2027-06-14",
    "end_date": "2027-06-17",
    "peak_attendees": 90,
    "requested_room_nights": 270,
    "largest_meeting_space_sqft": 5200,
    "budget_ceiling_usd": 300000.00,
    "preferred_program_only": False,
}

# The competing supplier's grid: a GROSS rate carrying commission, no resort fee
# and a lighter concession, which prices well under the first bid.
_CASCADE_GRID = {
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

_FIRST_INSPECTION_WINDOW = {
    "window_start": "2026-09-10T09:00:00.000Z",
    "window_end": "2026-09-10T13:00:00.000Z",
    "travel_buffer_minutes": 90,
}


def _plan_inspection_response(entry_id, **overrides):
    """Attempt to plan an inspection and hand back the raw response."""
    return api_client.create_site_inspection(
        factories.site_inspection_payload(entry_id, **overrides), PLANNER_HEADERS
    )


def _plan_inspection_response_without_buffer(entry_id, **overrides):
    """Attempt to plan an inspection with the buffer field left out entirely."""
    payload = factories.site_inspection_payload(entry_id, **overrides)
    payload.pop("travel_buffer_minutes")
    return api_client.create_site_inspection(payload, PLANNER_HEADERS)


def _counter_response(proposal_id, **overrides):
    """Attempt a counter at the bid's current version, returning the response."""
    payload = factories.counter_payload(fixtures.proposal_version(proposal_id), **overrides)
    return api_client.create_counter(proposal_id, payload, PLANNER_HEADERS)


def _add_second_meeting_entry(venue_id):
    """Lock a second meeting and commit the same venue to its solicitation."""
    event = fixtures.create_event(**_SECOND_MEETING)
    fixtures.lock_event(event["id"])
    entry = fixtures.add_entry(event["id"], venue_id, rank_seq=1, inspection_required=False)
    entry = fixtures.promote_entry(entry["id"])
    return {
        "event": event,
        "event_id": event["id"],
        "entry": entry,
        "entry_id": entry["id"],
    }


def _build_shared_venue_occupation_world():
    """One venue committed to two meetings, with the first inspection on file.

    The first inspection runs 09:00 to 13:00 with a ninety-minute buffer, so the
    venue is occupied up to but not including 14:30.
    """
    world = fixtures.build_sourcing_world()
    world["second"] = _add_second_meeting_entry(world["venue_id"])
    world["inspection_a"] = fixtures.plan_inspection(
        world["entry_id"], **_FIRST_INSPECTION_WINDOW
    )
    return world


def _build_paid_deposit_world():
    """An executed contract with installment 1 settled and the clock 151 days out.

    The deposit schedule is generated, the first installment is paid in full on
    its due date, and the clock is then moved to an instant that falls inside the
    ninety-one-day band of the negotiated cancellation schedule.
    """
    world = fixtures.build_deposit_scheduled_contract()
    installments = sorted(world["installments"], key=lambda row: row["installment_seq"])
    world["installments"] = installments
    fixtures.set_clock("2026-09-16T10:00:00.000Z")
    fixtures.pay_installment(
        installments[0]["id"], 44081.37, payment_reference="WIRE-2822-001"
    )
    fixtures.set_clock("2026-10-15T00:00:00.000Z")
    return world


def _build_superseded_award_world():
    """A meeting awarded on round 1, with a live round-2 bid ready to replace it.

    Round 1 invites only the first venue; the competing venue is committed after
    that round closes and is invited on round 2, which is chained to round 1.
    Both bids are priced on the contracted basis, the round-1 bid is awarded and
    its contract is routed, so two approval steps sit ``PENDING``.
    """
    world = fixtures.build_submitted_bid()
    fixtures.close_rfp(world["rfp_id"])

    venue_b = fixtures.create_second_venue()
    entry_b = fixtures.add_entry(world["event_id"], venue_b["id"], rank_seq=2)
    entry_b = fixtures.promote_entry(entry_b["id"])
    rfp_2 = fixtures.create_rfp(
        world["event_id"], round_number=2, previous_rfp_id=world["rfp_id"]
    )
    rfp_2 = fixtures.issue_rfp(rfp_2["id"])
    proposal_b = fixtures.find_invited_proposal(rfp_2["id"], venue_b["id"])
    fixtures.submit_bid(proposal_b["id"], venue_b["id"], **_CASCADE_GRID)
    fixtures.close_rfp(rfp_2["id"])

    fixtures.evaluate_bid(world["proposal_id"])
    fixtures.evaluate_bid(proposal_b["id"])

    contract_1 = fixtures.award_bid(world["event_id"], world["proposal_id"])
    contract_1 = fixtures.route_contract(contract_1["id"])
    world.update(
        {
            "venue_b": venue_b,
            "venue_b_id": venue_b["id"],
            "entry_b": entry_b,
            "entry_b_id": entry_b["id"],
            "rfp_2": rfp_2,
            "rfp_2_id": rfp_2["id"],
            "proposal_b": proposal_b,
            "proposal_b_id": proposal_b["id"],
            "contract_1": contract_1,
            "contract_1_id": contract_1["id"],
            "steps_1": fixtures.approval_steps(contract_1["id"]),
        }
    )
    return world


class TestCounterRequiresOpenSolicitationRound:
    """A counter's legality is decided by the parent round, not by the bid."""

    _CONCESSION_COUNTER = {
        "term_category": "CONCESSION",
        "proposed_numeric_value": 30000.00,
        "planner_note": "Raise the concession credit to 30000.00.",
    }

    def test_counter_raised_on_an_open_round_carries_the_first_round_seq(self):
        """The counter raised while the round was open is the bid's first.

        PRD: "A successful counter is created with HTTP 201 in `resolution` `OPEN`, with `resolved_at` null, with `initiated_by_user_id` set to the calling planner's `X-User-ID`, and with `round_seq` set to the bid's `negotiation_round_count` plus 1, giving a 1-based sequence in creation order within the bid."

        Design: Difficulty/cross_entity_state_dependency/counter_requires_parent_rfp_still_issued
        """
        world = fixtures.build_negotiation_cycle(loops=1)

        domain_assert.assert_integer(world["counters"][0]["round_seq"], 1, "round seq")

    def test_accepted_revision_resolves_the_counter(self):
        """The venue's acceptance closes the counter it answered.

        PRD: "On success the referenced counter's `resolution` becomes `ACCEPTED` when `accepted` is `true` and `DECLINED_BY_VENUE` when it is `false`, and its `resolved_at` is stamped from the logical clock."

        Design: Difficulty/cross_entity_state_dependency/counter_requires_parent_rfp_still_issued
        """
        world = fixtures.build_negotiation_cycle(loops=1)

        rows, _meta = validate_paginated(
            api_client.list_negotiation_counters(world["proposal_id"], PLANNER_HEADERS)
        )
        assert [row["resolution"] for row in rows] == ["ACCEPTED"]

    def test_accepted_revision_reprices_the_bid_on_the_revised_rate(self):
        """The revised rate is re-priced through the contracted-basis model.

        PRD: "The contracted-basis cost model is then re-run over the revised terms, refreshing `net_adr_usd`, `comp_room_nights`, `paid_room_nights` and `total_cost_contracted_usd`, and the benchmark rules are re-run, refreshing `benchmark_variance_pct` and `compliance_status`."

        Design: Difficulty/cross_entity_state_dependency/counter_requires_parent_rfp_still_issued
        """
        world = fixtures.build_negotiation_cycle(loops=1)

        bid = fixtures.read_proposal(world["proposal_id"])
        domain_assert.assert_money(bid["room_rate_usd"], 235.00, "revised room rate")
        domain_assert.assert_money(
            bid["total_cost_contracted_usd"], 436722.27, "revised contracted total"
        )

    def test_closing_the_round_stamps_it_closed_from_the_logical_clock(self):
        """Closing the round is the only state change the trigger depends on.

        PRD: "`closed_at` is stamped from the logical clock, the round moves `ISSUED → CLOSED`, and every bid of that round still sitting in `INVITED` moves `INVITED → EXPIRED` — a venue that never answered is expired rather than declined, and expiry mutates nothing else."

        Design: Difficulty/cross_entity_state_dependency/counter_requires_parent_rfp_still_issued
        """
        world = fixtures.build_negotiation_cycle(loops=1)

        closed = fixtures.close_rfp(world["rfp_id"])

        assert closed["status"] == "CLOSED"
        assert closed["closed_at"] == "2026-08-05T09:00:00.000Z"

    def test_closing_the_round_moves_the_meeting_into_bid_review(self):
        """The parent meeting follows the round into review.

        PRD: "The parent event moves `SOURCING → BID_REVIEW`, its `best_total_cost_usd` is recomputed, and its `version` advances by 1."

        Design: Difficulty/cross_entity_state_dependency/counter_requires_parent_rfp_still_issued
        """
        world = fixtures.build_negotiation_cycle(loops=1)

        fixtures.close_rfp(world["rfp_id"])

        assert fixtures.read_event(world["event_id"])["status"] == "BID_REVIEW"

    def test_counter_on_a_closed_round_is_refused(self):
        """Once the parent round is closed no further negotiation may be opened.

        PRD: "Beyond the state check the bid's parent solicitation round must still be in `ISSUED`, otherwise `ERR_RFP_NOT_OPEN` — a planner cannot open new negotiation on a closed round."

        Design: Difficulty/cross_entity_state_dependency/counter_requires_parent_rfp_still_issued
        """
        world = fixtures.build_negotiation_cycle(loops=1)
        fixtures.close_rfp(world["rfp_id"])

        response = _counter_response(world["proposal_id"], **self._CONCESSION_COUNTER)

        validate_error(response, ApiErrorId.RFP_NOT_OPEN.value, 409)

    def test_closed_round_refusal_is_not_a_complaint_about_the_bid_state(self):
        """The bid itself is still in a state counters are raised from.

        PRD: "A `SourcingManager` raises a counter against a bid that is `UNDER_REVIEW`, naming the `term_category` being countered — one of `RATE`, `CONCESSION`, `ATTRITION`, `CANCELLATION`, `FORCE_MAJEURE` or `REBOOKING_CREDIT` — together with the target value."

        Design: Difficulty/cross_entity_state_dependency/counter_requires_parent_rfp_still_issued
        """
        world = fixtures.build_negotiation_cycle(loops=1)
        fixtures.close_rfp(world["rfp_id"])
        assert fixtures.read_proposal(world["proposal_id"])["status"] == "UNDER_REVIEW"

        response = _counter_response(world["proposal_id"], **self._CONCESSION_COUNTER)

        assert response.json()["data"]["error_id"] != ApiErrorId.PROPOSAL_STATE_INVALID.value

    def test_refused_counter_leaves_the_bid_and_its_audit_trail_untouched(self):
        """None of a counter's bid effects fire when the counter is refused.

        PRD: "The bid then moves `UNDER_REVIEW → COUNTERED`, its `negotiation_round_count` increases by 1, and its `version` advances by 1."

        Design: Difficulty/cross_entity_state_dependency/counter_requires_parent_rfp_still_issued
        """
        world = fixtures.build_negotiation_cycle(loops=1)
        fixtures.close_rfp(world["rfp_id"])
        before = fixtures.read_proposal(world["proposal_id"])

        _counter_response(world["proposal_id"], **self._CONCESSION_COUNTER)

        after = fixtures.read_proposal(world["proposal_id"])
        assert after["status"] == "UNDER_REVIEW"
        domain_assert.assert_integer(
            after["negotiation_round_count"], 1, "negotiation round count"
        )
        assert after["version"] == before["version"]
        rows, _meta = validate_paginated(
            api_client.list_negotiation_counters(world["proposal_id"], PLANNER_HEADERS)
        )
        assert len(rows) == 1


class TestSiteInspectionRequiresCommittedEntry:
    """An inspection's legality is decided by the parent entry's own status."""

    def test_candidate_entry_cannot_be_inspected(self):
        """A venue still only a candidate may not be visited.

        PRD: "The referenced entry must be exactly in `SHORTLISTED` — an entry still in `CANDIDATE`, already in `INSPECTION_SCHEDULED`, already `INSPECTED`, already `RFP_ISSUED`, `AWARDED` or `ELIMINATED` is rejected with `ERR_SHORTLIST_ENTRY_NOT_SHORTLISTED`."

        Design: Difficulty/cross_entity_state_dependency/site_inspection_requires_shortlisted_entry_not_candidate
        """
        world = fixtures.build_sourcing_world(promote=False)

        response = _plan_inspection_response(world["entry_id"], **_FIRST_INSPECTION_WINDOW)

        validate_error(response, ApiErrorId.SHORTLIST_ENTRY_NOT_SHORTLISTED.value, 409)

    def test_refused_plan_leaves_the_candidate_entry_untouched(self):
        """The refused plan neither advances the entry nor records an inspection.

        PRD: "A successful plan creates the inspection in `PLANNED` with `findings_score` null and `cancel_reason` null, moves the parent entry `SHORTLISTED → INSPECTION_SCHEDULED`, increases that entry's `inspection_count` by 1 and advances the entry's `version` by 1."

        Design: Difficulty/cross_entity_state_dependency/site_inspection_requires_shortlisted_entry_not_candidate
        """
        world = fixtures.build_sourcing_world(promote=False)

        _plan_inspection_response(world["entry_id"], **_FIRST_INSPECTION_WINDOW)

        entry = fixtures.read_entry(world["entry_id"])
        assert entry["status"] == "CANDIDATE"
        domain_assert.assert_integer(entry["inspection_count"], 0, "inspection count")
        rows, _meta = validate_paginated(
            api_client.list_site_inspections(
                PLANNER_HEADERS, {"shortlist_entry_id": world["entry_id"]}
            )
        )
        assert rows == []

    def test_committing_the_entry_raises_the_shortlisted_venue_count(self):
        """Promotion is what changes on the entry between the two attempts.

        PRD: "On success the parent event's `shortlisted_venue_count` increases by 1 and the event's `version` advances by 1."

        Design: Difficulty/cross_entity_state_dependency/site_inspection_requires_shortlisted_entry_not_candidate
        """
        world = fixtures.build_sourcing_world(promote=False)

        entry = fixtures.promote_entry(world["entry_id"])

        assert entry["status"] == "SHORTLISTED"
        event = fixtures.read_event(world["event_id"])
        domain_assert.assert_integer(
            event["shortlisted_venue_count"], 1, "shortlisted venue count"
        )

    def test_committed_entry_accepts_the_identical_inspection_body(self):
        """The same body is admitted once the entry alone has been committed.

        PRD: "From those inputs the server derives `occupied_until` as `window_end` advanced by `travel_buffer_minutes`, and treats the half-open interval from `window_start` up to but not including `occupied_until` as the venue's buffered occupation interval."

        Design: Difficulty/cross_entity_state_dependency/site_inspection_requires_shortlisted_entry_not_candidate
        """
        world = fixtures.build_sourcing_world(promote=False)
        _plan_inspection_response(world["entry_id"], **_FIRST_INSPECTION_WINDOW)
        fixtures.promote_entry(world["entry_id"])

        response = _plan_inspection_response(world["entry_id"], **_FIRST_INSPECTION_WINDOW)

        inspection = validate_success(response, 201)
        assert inspection["status"] == "PLANNED"
        domain_assert.assert_integer(
            inspection["travel_buffer_minutes"], 90, "travel buffer minutes"
        )
        assert inspection["occupied_until"] == "2026-09-10T14:30:00.000Z"

    def test_inspection_copies_the_venue_from_the_parent_entry(self):
        """The admitted inspection points at the entry's venue.

        PRD: "The inspection also copies `venue_id` from the parent shortlist entry at creation and never re-derives it, so a later change on the entry cannot move an inspection to a different venue."

        Design: Difficulty/cross_entity_state_dependency/site_inspection_requires_shortlisted_entry_not_candidate
        """
        world = fixtures.build_sourcing_world(promote=False)
        fixtures.promote_entry(world["entry_id"])

        inspection = fixtures.plan_inspection(world["entry_id"], **_FIRST_INSPECTION_WINDOW)

        assert inspection["venue_id"] == world["venue_id"]

    def test_successful_plan_schedules_the_committed_entry(self):
        """The admitted plan advances the entry and its inspection count.

        PRD: "A successful plan creates the inspection in `PLANNED` with `findings_score` null and `cancel_reason` null, moves the parent entry `SHORTLISTED → INSPECTION_SCHEDULED`, increases that entry's `inspection_count` by 1 and advances the entry's `version` by 1."

        Design: Difficulty/cross_entity_state_dependency/site_inspection_requires_shortlisted_entry_not_candidate
        """
        world = fixtures.build_sourcing_world(promote=False)
        fixtures.promote_entry(world["entry_id"])

        fixtures.plan_inspection(world["entry_id"], **_FIRST_INSPECTION_WINDOW)

        entry = fixtures.read_entry(world["entry_id"])
        assert entry["status"] == "INSPECTION_SCHEDULED"
        domain_assert.assert_integer(entry["inspection_count"], 1, "inspection count")

    def test_scheduling_an_inspection_does_not_change_the_shortlisted_count(self):
        """A scheduled entry still counts once towards the committed venues.

        PRD: "That count is maintained as the number of the event's entries whose `status` is one of `SHORTLISTED`, `INSPECTION_SCHEDULED`, `INSPECTED`, `RFP_ISSUED` or `AWARDED` — entries still in `CANDIDATE` and entries already `ELIMINATED` are excluded."

        Design: Difficulty/cross_entity_state_dependency/site_inspection_requires_shortlisted_entry_not_candidate
        """
        world = fixtures.build_sourcing_world(promote=False)
        fixtures.promote_entry(world["entry_id"])

        fixtures.plan_inspection(world["entry_id"], **_FIRST_INSPECTION_WINDOW)

        event = fixtures.read_event(world["event_id"])
        domain_assert.assert_integer(
            event["shortlisted_venue_count"], 1, "shortlisted venue count"
        )


class TestVenueOccupationHalfOpenBoundary:
    """The venue's buffered occupation interval is closed below and open above."""

    _COLLIDING_WINDOW = {
        "window_start": "2026-09-10T14:29:00.000Z",
        "window_end": "2026-09-10T18:29:00.000Z",
        "travel_buffer_minutes": 90,
    }
    _ABUTTING_WINDOW = {
        "window_start": "2026-09-10T14:30:00.000Z",
        "window_end": "2026-09-10T18:30:00.000Z",
        "travel_buffer_minutes": 0,
    }

    def test_first_inspection_occupies_the_venue_to_its_buffered_bound(self):
        """The first inspection's buffer sets the bound the second one must clear.

        PRD: "From those inputs the server derives `occupied_until` as `window_end` advanced by `travel_buffer_minutes`, and treats the half-open interval from `window_start` up to but not including `occupied_until` as the venue's buffered occupation interval."

        Design: Difficulty/resource_temporal_overlap/venue_inspection_buffered_half_open_interval_boundary
        """
        world = _build_shared_venue_occupation_world()

        assert world["inspection_a"]["occupied_until"] == "2026-09-10T14:30:00.000Z"

    def test_window_starting_one_minute_inside_the_buffer_conflicts(self):
        """A start one minute short of the bound intersects the occupied interval.

        PRD: "And two temporal exclusions hold: the inspection window must not intersect the parent meeting event's own fully-closed date interval, which runs from the event's `start_date` at `00:00:00.000Z` through its `end_date` at `23:59:59.999Z` inclusive — an intersection is rejected with `ERR_INSPECTION_WINDOW_OVERLAPS_EVENT`, because a site visit cannot be scheduled while the meeting itself is in the building — and the new buffered occupation interval must not intersect the buffered occupation interval of any other inspection on the same `venue_id` whose `status` is `PLANNED` or `COMPLETED`, an intersection being rejected with `ERR_INSPECTION_WINDOW_CONFLICT`."

        Design: Difficulty/resource_temporal_overlap/venue_inspection_buffered_half_open_interval_boundary
        """
        world = _build_shared_venue_occupation_world()

        response = _plan_inspection_response(
            world["second"]["entry_id"], **self._COLLIDING_WINDOW
        )

        validate_error(response, ApiErrorId.INSPECTION_WINDOW_CONFLICT.value, 409)

    def test_refused_conflict_leaves_the_second_entry_untouched(self):
        """The conflicting request records nothing against the second entry.

        PRD: "A successful plan creates the inspection in `PLANNED` with `findings_score` null and `cancel_reason` null, moves the parent entry `SHORTLISTED → INSPECTION_SCHEDULED`, increases that entry's `inspection_count` by 1 and advances the entry's `version` by 1."

        Design: Difficulty/resource_temporal_overlap/venue_inspection_buffered_half_open_interval_boundary
        """
        world = _build_shared_venue_occupation_world()

        _plan_inspection_response(world["second"]["entry_id"], **self._COLLIDING_WINDOW)

        entry = fixtures.read_entry(world["second"]["entry_id"])
        assert entry["status"] == "SHORTLISTED"
        domain_assert.assert_integer(entry["inspection_count"], 0, "inspection count")

    def test_window_starting_exactly_on_the_buffered_bound_is_admitted(self):
        """Abutting the occupied interval is permitted because the top is open.

        PRD: "Because both intervals are half-open at the top, an inspection whose `window_start` falls exactly on another inspection's `occupied_until` does not conflict; abutting is permitted, overlapping is not."

        Design: Difficulty/resource_temporal_overlap/venue_inspection_buffered_half_open_interval_boundary
        """
        world = _build_shared_venue_occupation_world()
        _plan_inspection_response(world["second"]["entry_id"], **self._COLLIDING_WINDOW)

        response = _plan_inspection_response(
            world["second"]["entry_id"], **self._ABUTTING_WINDOW
        )

        inspection = validate_success(response, 201)
        assert inspection["status"] == "PLANNED"
        assert inspection["venue_id"] == world["venue_id"]

    def test_zero_buffer_leaves_the_occupation_bound_at_the_window_end(self):
        """A zero-minute buffer occupies the venue only to the window's end.

        PRD: "From those inputs the server derives `occupied_until` as `window_end` advanced by `travel_buffer_minutes`, and treats the half-open interval from `window_start` up to but not including `occupied_until` as the venue's buffered occupation interval."

        Design: Difficulty/resource_temporal_overlap/venue_inspection_buffered_half_open_interval_boundary
        """
        world = _build_shared_venue_occupation_world()

        inspection = fixtures.plan_inspection(
            world["second"]["entry_id"], **self._ABUTTING_WINDOW
        )

        domain_assert.assert_integer(
            inspection["travel_buffer_minutes"], 0, "travel buffer minutes"
        )
        assert inspection["occupied_until"] == "2026-09-10T18:30:00.000Z"

    def test_abutting_plan_leaves_the_earlier_inspection_unchanged(self):
        """The earlier inspection keeps its own state and occupation bound.

        PRD: "Because both intervals are half-open at the top, an inspection whose `window_start` falls exactly on another inspection's `occupied_until` does not conflict; abutting is permitted, overlapping is not."

        Design: Difficulty/resource_temporal_overlap/venue_inspection_buffered_half_open_interval_boundary
        """
        world = _build_shared_venue_occupation_world()

        fixtures.plan_inspection(world["second"]["entry_id"], **self._ABUTTING_WINDOW)

        earlier = fixtures.read_inspection(world["inspection_a"]["id"])
        assert earlier["status"] == "PLANNED"
        assert earlier["occupied_until"] == "2026-09-10T14:30:00.000Z"

    def test_abutting_plan_schedules_the_second_entry(self):
        """The admitted plan advances the second meeting's entry.

        PRD: "The `inspection_count` field is maintained as the number of inspections on the entry whose `status` is `PLANNED` or `COMPLETED`."

        Design: Difficulty/resource_temporal_overlap/venue_inspection_buffered_half_open_interval_boundary
        """
        world = _build_shared_venue_occupation_world()

        fixtures.plan_inspection(world["second"]["entry_id"], **self._ABUTTING_WINDOW)

        entry = fixtures.read_entry(world["second"]["entry_id"])
        assert entry["status"] == "INSPECTION_SCHEDULED"
        domain_assert.assert_integer(entry["inspection_count"], 1, "inspection count")

    def test_the_shared_venue_now_carries_two_abutting_inspections(self):
        """Both inspections live on the one venue whose time they occupy.

        PRD: "The inspection also copies `venue_id` from the parent shortlist entry at creation and never re-derives it, so a later change on the entry cannot move an inspection to a different venue."

        Design: Difficulty/resource_temporal_overlap/venue_inspection_buffered_half_open_interval_boundary
        """
        world = _build_shared_venue_occupation_world()
        second = fixtures.plan_inspection(
            world["second"]["entry_id"], **self._ABUTTING_WINDOW
        )

        rows, _meta = validate_paginated(
            api_client.list_site_inspections(
                PLANNER_HEADERS, {"venue_id": world["venue_id"], "limit": 100}
            )
        )

        assert len(rows) == 2
        assert {row["id"] for row in rows} == {world["inspection_a"]["id"], second["id"]}


class TestInspectionWindowVersusMeetingBlackout:
    """The meeting's own blackout interval is closed at both ends."""

    _CLOSING_INSTANT_WINDOW = {
        "window_start": "2027-03-18T23:59:59.999Z",
        "window_end": "2027-03-19T04:00:00.000Z",
    }
    _JUST_AFTER_WINDOW = {
        "window_start": "2027-03-19T00:00:00.000Z",
        "window_end": "2027-03-19T04:00:00.000Z",
    }

    def test_window_starting_on_the_meetings_closing_instant_is_refused(self):
        """The final millisecond of the closing day is inside the blackout.

        PRD: "And two temporal exclusions hold: the inspection window must not intersect the parent meeting event's own fully-closed date interval, which runs from the event's `start_date` at `00:00:00.000Z` through its `end_date` at `23:59:59.999Z` inclusive — an intersection is rejected with `ERR_INSPECTION_WINDOW_OVERLAPS_EVENT`, because a site visit cannot be scheduled while the meeting itself is in the building — and the new buffered occupation interval must not intersect the buffered occupation interval of any other inspection on the same `venue_id` whose `status` is `PLANNED` or `COMPLETED`, an intersection being rejected with `ERR_INSPECTION_WINDOW_CONFLICT`."

        Design: Difficulty/resource_temporal_overlap/inspection_window_versus_event_fully_closed_day_interval
        """
        world = fixtures.build_sourcing_world()

        response = _plan_inspection_response_without_buffer(
            world["entry_id"], **self._CLOSING_INSTANT_WINDOW
        )

        validate_error(response, ApiErrorId.INSPECTION_WINDOW_OVERLAPS_EVENT.value, 422)

    def test_refused_blackout_plan_leaves_the_entry_untouched(self):
        """The refused plan records nothing against the entry.

        PRD: "A successful plan creates the inspection in `PLANNED` with `findings_score` null and `cancel_reason` null, moves the parent entry `SHORTLISTED → INSPECTION_SCHEDULED`, increases that entry's `inspection_count` by 1 and advances the entry's `version` by 1."

        Design: Difficulty/resource_temporal_overlap/inspection_window_versus_event_fully_closed_day_interval
        """
        world = fixtures.build_sourcing_world()

        _plan_inspection_response_without_buffer(
            world["entry_id"], **self._CLOSING_INSTANT_WINDOW
        )

        entry = fixtures.read_entry(world["entry_id"])
        assert entry["status"] == "SHORTLISTED"
        domain_assert.assert_integer(entry["inspection_count"], 0, "inspection count")
        rows, _meta = validate_paginated(
            api_client.list_site_inspections(
                PLANNER_HEADERS, {"shortlist_entry_id": world["entry_id"]}
            )
        )
        assert rows == []

    def test_window_one_millisecond_past_the_blackout_is_admitted(self):
        """Midnight on the day after the meeting closes is outside the blackout.

        PRD: "And two temporal exclusions hold: the inspection window must not intersect the parent meeting event's own fully-closed date interval, which runs from the event's `start_date` at `00:00:00.000Z` through its `end_date` at `23:59:59.999Z` inclusive — an intersection is rejected with `ERR_INSPECTION_WINDOW_OVERLAPS_EVENT`, because a site visit cannot be scheduled while the meeting itself is in the building — and the new buffered occupation interval must not intersect the buffered occupation interval of any other inspection on the same `venue_id` whose `status` is `PLANNED` or `COMPLETED`, an intersection being rejected with `ERR_INSPECTION_WINDOW_CONFLICT`."

        Design: Difficulty/resource_temporal_overlap/inspection_window_versus_event_fully_closed_day_interval
        """
        world = fixtures.build_sourcing_world()
        _plan_inspection_response_without_buffer(
            world["entry_id"], **self._CLOSING_INSTANT_WINDOW
        )

        response = _plan_inspection_response_without_buffer(
            world["entry_id"], **self._JUST_AFTER_WINDOW
        )

        inspection = validate_success(response, 201)
        assert inspection["status"] == "PLANNED"

    def test_omitted_travel_buffer_defaults_to_ninety_minutes(self):
        """Leaving the buffer out applies the declared default.

        PRD: "The optional `travel_buffer_minutes` field is the number of minutes of travel buffer appended after `window_end` to form the venue's occupation interval; it defaults to 90 minutes — an hour and a half — when omitted, and must be at least 0 and at most 720 minutes, that is, no more than twelve hours."

        Design: Difficulty/resource_temporal_overlap/inspection_window_versus_event_fully_closed_day_interval
        """
        world = fixtures.build_sourcing_world()

        response = _plan_inspection_response_without_buffer(
            world["entry_id"], **self._JUST_AFTER_WINDOW
        )

        inspection = validate_success(response, 201)
        domain_assert.assert_integer(
            inspection["travel_buffer_minutes"], 90, "travel buffer minutes"
        )

    def test_admitted_window_carries_its_default_buffered_occupation_bound(self):
        """The default buffer pushes the occupation bound ninety minutes on.

        PRD: "From those inputs the server derives `occupied_until` as `window_end` advanced by `travel_buffer_minutes`, and treats the half-open interval from `window_start` up to but not including `occupied_until` as the venue's buffered occupation interval."

        Design: Difficulty/resource_temporal_overlap/inspection_window_versus_event_fully_closed_day_interval
        """
        world = fixtures.build_sourcing_world()

        response = _plan_inspection_response_without_buffer(
            world["entry_id"], **self._JUST_AFTER_WINDOW
        )

        inspection = validate_success(response, 201)
        assert inspection["occupied_until"] == "2027-03-19T05:30:00.000Z"

    def test_admitted_blackout_clear_plan_schedules_the_entry(self):
        """The admitted plan advances the entry it was raised against.

        PRD: "A successful plan creates the inspection in `PLANNED` with `findings_score` null and `cancel_reason` null, moves the parent entry `SHORTLISTED → INSPECTION_SCHEDULED`, increases that entry's `inspection_count` by 1 and advances the entry's `version` by 1."

        Design: Difficulty/resource_temporal_overlap/inspection_window_versus_event_fully_closed_day_interval
        """
        world = fixtures.build_sourcing_world()

        _plan_inspection_response_without_buffer(
            world["entry_id"], **self._JUST_AFTER_WINDOW
        )

        entry = fixtures.read_entry(world["entry_id"])
        assert entry["status"] == "INSPECTION_SCHEDULED"
        domain_assert.assert_integer(entry["inspection_count"], 1, "inspection count")


class TestTerminationRestoresRoomNightInventory:
    """Termination subtracts exactly the nights and money execution committed."""

    def test_termination_returns_the_venue_room_night_inventory_to_zero(self):
        """The 587 nights execution blocked are given back exactly once.

        PRD: "The venue's `blocked_room_nights` decreases by the contract's `contracted_paid_room_nights`, restoring the room-night identity of section 2.10."

        Design: Difficulty/compensating_invariant/termination_restores_integer_room_night_inventory
        """
        world = _build_paid_deposit_world()
        domain_assert.assert_room_night_inventory(fixtures.read_venue(world["venue_id"]), 587)

        fixtures.terminate_contract(world["contract_id"])

        domain_assert.assert_room_night_inventory(fixtures.read_venue(world["venue_id"]), 0)

    def test_termination_preserves_the_contracted_night_snapshot(self):
        """The frozen block on the contract is not rewritten by the unwind.

        PRD: "The contract's `contracted_room_rate_usd` is the bid's `net_adr_usd`; its `contracted_paid_room_nights` is the bid's `paid_room_nights`; its `contracted_room_revenue_usd` is `contracted_room_rate_usd` multiplied by `contracted_paid_room_nights`, rounded to 2 decimal places."

        Design: Difficulty/compensating_invariant/termination_restores_integer_room_night_inventory
        """
        world = _build_paid_deposit_world()

        contract = fixtures.terminate_contract(world["contract_id"])

        domain_assert.assert_integer(
            contract["contracted_paid_room_nights"], 587, "contracted paid room nights"
        )
        domain_assert.assert_money(
            contract["contracted_room_revenue_usd"], 146163.00, "contracted room revenue"
        )

    def test_termination_stamps_the_contract_terminated(self):
        """The contract leaves execution for its terminated state.

        PRD: "`terminated_at` is stamped from the logical clock and the contract moves `signature_state` `EXECUTED → TERMINATED`."

        Design: Difficulty/compensating_invariant/termination_restores_integer_room_night_inventory
        """
        world = _build_paid_deposit_world()

        contract = fixtures.terminate_contract(world["contract_id"])

        assert contract["signature_state"] == "TERMINATED"
        assert contract["terminated_at"] == "2026-10-15T00:00:00.000Z"

    def test_cancellation_fee_is_the_room_revenue_at_the_selected_tier(self):
        """One hundred and fifty-one days out selects the ninety-one-day tier.

        PRD: "Then `cancellation_fee_usd` is the contract's `contracted_room_revenue_usd` multiplied by that tier's `fee_pct`, rounded to 2 decimal places."

        Design: Difficulty/compensating_invariant/termination_restores_integer_room_night_inventory
        """
        world = _build_paid_deposit_world()

        contract = fixtures.terminate_contract(world["contract_id"])

        domain_assert.assert_money(
            contract["cancellation_fee_usd"], 73081.50, "cancellation fee"
        )

    def test_rebooking_credit_is_a_share_of_the_fee_charged(self):
        """The credit is taken from the fee, not from the contract value.

        PRD: "Finally `rebooking_credit_usd` is `cancellation_fee_usd` multiplied by the contract's `rebooking_credit_pct`, rounded to 2 decimal places — the credit is a share of the fee charged, not of the contract value."

        Design: Difficulty/compensating_invariant/termination_restores_integer_room_night_inventory
        """
        world = _build_paid_deposit_world()

        contract = fixtures.terminate_contract(world["contract_id"])

        domain_assert.assert_money(
            contract["rebooking_credit_usd"], 43848.90, "rebooking credit"
        )

    def test_termination_cancels_only_the_still_scheduled_installments(self):
        """The settled installment survives; the outstanding balance clears.

        PRD: "Every deposit installment on the contract whose `status` is `SCHEDULED` moves to `CANCELLED`, and the contract's `deposit_outstanding_usd` becomes `0.00`; installments already `PAID` are left untouched, so `deposit_paid_usd` does not change."

        Design: Difficulty/compensating_invariant/termination_restores_integer_room_night_inventory
        """
        world = _build_paid_deposit_world()

        contract = fixtures.terminate_contract(world["contract_id"])

        rows = sorted(
            fixtures.deposit_installments(world["contract_id"]),
            key=lambda row: row["installment_seq"],
        )
        assert [row["status"] for row in rows] == ["PAID", "CANCELLED", "CANCELLED"]
        domain_assert.assert_money(rows[0]["paid_amount_usd"], 44081.37, "installment 1 paid")
        domain_assert.assert_money(contract["deposit_paid_usd"], 44081.37, "deposit paid")
        domain_assert.assert_money(
            contract["deposit_outstanding_usd"], 0.00, "deposit outstanding"
        )

    def test_termination_moves_the_commitment_into_cancellation_liability(self):
        """Committed money becomes liability, and the envelope still closes.

        PRD: "The event's `committed_spend_usd` returns to `0.00`, its `cancellation_liability_usd` increases by the `cancellation_fee_usd`, its `budget_remaining_usd` is recomputed so the money identity of section 2.10 still holds, and the event moves `CONTRACTED → CANCELLED`."

        Design: Difficulty/compensating_invariant/termination_restores_integer_room_night_inventory
        """
        world = _build_paid_deposit_world()

        fixtures.terminate_contract(world["contract_id"])

        event = fixtures.read_event(world["event_id"])
        assert event["status"] == "CANCELLED"
        domain_assert.assert_money(event["committed_spend_usd"], 0.00, "committed spend")
        domain_assert.assert_money(
            event["cancellation_liability_usd"], 73081.50, "cancellation liability"
        )
        domain_assert.assert_money(
            event["budget_remaining_usd"], 426918.50, "budget remaining"
        )
        domain_assert.assert_budget_envelope(event)

    def test_termination_does_not_un_award_the_shortlist_entry(self):
        """The winning entry keeps the terminal state execution gave it.

        PRD: "The awarded shortlist entry moves `RFP_ISSUED → AWARDED`, which is its second terminal state alongside `ELIMINATED`."

        Design: Difficulty/compensating_invariant/termination_restores_integer_room_night_inventory
        """
        world = _build_paid_deposit_world()

        fixtures.terminate_contract(world["contract_id"])

        assert fixtures.read_entry(world["entry_id"])["status"] == "AWARDED"


class TestAwardSupersedeConservesTheMoneyEnvelope:
    """Replacing an award voids the first contract without double-counting money."""

    def test_superseded_contract_reaches_its_terminal_states(self):
        """The replaced contract is cancelled on both parallel dimensions.

        PRD: "Its contract moves to `approval_state` `CANCELLED` and `signature_state` `VOIDED`, which are the terminal states on the two dimensions."

        Design: Difficulty/compensating_invariant/award_supersede_conserves_the_money_envelope
        """
        world = _build_superseded_award_world()

        fixtures.award_bid(world["event_id"], world["proposal_b_id"])

        superseded = fixtures.read_contract(world["contract_1_id"])
        assert superseded["approval_state"] == "CANCELLED"
        assert superseded["signature_state"] == "VOIDED"

    def test_superseded_contract_preserves_its_frozen_total(self):
        """The voided snapshot keeps the terms it was struck on.

        PRD: "Every commercial term the parties agreed on is frozen onto the contract at award time, so that later revision of the bid — which is impossible once it is `AWARDED`, but which the model nevertheless guards against — could not disturb what was signed."

        Design: Difficulty/compensating_invariant/award_supersede_conserves_the_money_envelope
        """
        world = _build_superseded_award_world()

        fixtures.award_bid(world["event_id"], world["proposal_b_id"])

        superseded = fixtures.read_contract(world["contract_1_id"])
        domain_assert.assert_money(
            superseded["contracted_total_usd"], 432170.27, "superseded contracted total"
        )

    def test_supersede_skips_the_pending_approval_steps(self):
        """Every control step still awaiting a decision is skipped.

        PRD: "Every approval step on that superseded contract whose `decision` is still `PENDING` moves to `SKIPPED`, and every deposit installment on it whose `status` is `SCHEDULED` moves to `CANCELLED`."

        Design: Difficulty/compensating_invariant/award_supersede_conserves_the_money_envelope
        """
        world = _build_superseded_award_world()
        assert [step["decision"] for step in world["steps_1"]] == ["PENDING", "PENDING"]

        fixtures.award_bid(world["event_id"], world["proposal_b_id"])

        steps = sorted(
            fixtures.approval_steps(world["contract_1_id"]), key=lambda s: s["step_seq"]
        )
        assert [step["decision"] for step in steps] == ["SKIPPED", "SKIPPED"]

    def test_supersede_rejects_the_previously_awarded_bid(self):
        """The replaced bid loses its award and the replacement takes it.

        PRD: "The previously awarded bid moves from `AWARDED` to `REJECTED`."

        Design: Difficulty/compensating_invariant/award_supersede_conserves_the_money_envelope
        """
        world = _build_superseded_award_world()

        fixtures.award_bid(world["event_id"], world["proposal_b_id"])

        assert fixtures.read_proposal(world["proposal_id"])["status"] == "REJECTED"
        assert fixtures.read_proposal(world["proposal_b_id"])["status"] == "AWARDED"

    def test_replacement_contract_prices_the_middle_rebate_tier(self):
        """A pre-rebate total inside the middle band earns the 0.020 rebate.

        PRD: "The rebate percentage is then chosen from that pre-rebate figure: a `pre_rebate_total_usd` below `150000.00` earns `volume_rebate_pct` of `0.000`; a `pre_rebate_total_usd` at or above `150000.00` but below `400000.00` earns `0.020`; and a `pre_rebate_total_usd` at or above `400000.00` earns `0.035`."

        Design: Difficulty/compensating_invariant/award_supersede_conserves_the_money_envelope
        """
        world = _build_superseded_award_world()

        replacement = fixtures.award_bid(world["event_id"], world["proposal_b_id"])

        domain_assert.assert_money(
            replacement["pre_rebate_total_usd"], 290551.07, "pre-rebate total"
        )
        assert replacement["volume_rebate_pct"] == pytest.approx(0.020, abs=0.00005)
        domain_assert.assert_money(
            replacement["volume_rebate_usd"], 5811.02, "volume rebate"
        )
        domain_assert.assert_money(
            replacement["contracted_total_usd"], 284740.05, "contracted total"
        )

    def test_replacement_contract_starts_unrouted_and_unsigned(self):
        """The new contract begins on both dimensions from scratch.

        PRD: "A new contract begins with `approval_state` `PENDING_ROUTING` and `signature_state` `UNSIGNED` — the two parallel dimensions described below — and with its money and signature fields empty: `deposit_total_usd` null, `deposit_paid_usd` `0.00`, `deposit_outstanding_usd` null, `approval_step_count` `0`, and `planner_signatory_name`, `venue_signatory_name`, `executed_at`, `terminated_at`, `cancellation_fee_usd`, `rebooking_credit_usd` and `termination_reason` all null."

        Design: Difficulty/compensating_invariant/award_supersede_conserves_the_money_envelope
        """
        world = _build_superseded_award_world()

        replacement = fixtures.award_bid(world["event_id"], world["proposal_b_id"])

        assert replacement["approval_state"] == "PENDING_ROUTING"
        assert replacement["signature_state"] == "UNSIGNED"

    def test_committed_spend_repoints_at_the_replacement_contract(self):
        """The meeting commits the new total instead of accumulating both.

        PRD: "The event's `awarded_proposal_id` and `committed_spend_usd` then re-point at the new contract rather than accumulating both, so the money identity continues to hold across the supersede."

        Design: Difficulty/compensating_invariant/award_supersede_conserves_the_money_envelope
        """
        world = _build_superseded_award_world()

        fixtures.award_bid(world["event_id"], world["proposal_b_id"])

        event = fixtures.read_event(world["event_id"])
        assert event["status"] == "AWARDED"
        assert event["awarded_proposal_id"] == world["proposal_b_id"]
        domain_assert.assert_money(
            event["committed_spend_usd"], 284740.05, "committed spend"
        )

    def test_money_envelope_closes_across_the_supersede(self):
        """The three-way split still sums to the ceiling to the cent.

        PRD: "At every observable instant, and for every meeting event, the sum of `budget_remaining_usd`, `committed_spend_usd` and `cancellation_liability_usd` equals `budget_ceiling_usd` exactly."

        Design: Difficulty/compensating_invariant/award_supersede_conserves_the_money_envelope
        """
        world = _build_superseded_award_world()

        fixtures.award_bid(world["event_id"], world["proposal_b_id"])

        event = fixtures.read_event(world["event_id"])
        domain_assert.assert_money(
            event["budget_remaining_usd"], 215259.95, "budget remaining"
        )
        domain_assert.assert_money(
            event["cancellation_liability_usd"], 0.00, "cancellation liability"
        )
        domain_assert.assert_budget_envelope(event)

    def test_supersede_leaves_exactly_one_live_contract_for_the_meeting(self):
        """Both contracts remain on file but only the replacement is live.

        PRD: "A superseded contract can never be routed, signed, countersigned or executed again; `CANCELLED` and `VOIDED` are dead ends."

        Design: Difficulty/compensating_invariant/award_supersede_conserves_the_money_envelope
        """
        world = _build_superseded_award_world()
        replacement = fixtures.award_bid(world["event_id"], world["proposal_b_id"])

        rows, _meta = validate_paginated(
            api_client.list_contracts(
                PLANNER_HEADERS, {"event_id": world["event_id"], "limit": 100}
            )
        )

        assert len(rows) == 2
        live = [row for row in rows if row["approval_state"] != "CANCELLED"]
        assert [row["id"] for row in live] == [replacement["id"]]

    def test_supersede_neither_eliminates_the_earlier_entry_nor_blocks_rooms(self):
        """The round-1 entry keeps its own status and no nights are blocked.

        PRD: "Entries whose bids were untouched at level 2 keep their own status."

        Design: Difficulty/compensating_invariant/award_supersede_conserves_the_money_envelope
        """
        world = _build_superseded_award_world()

        fixtures.award_bid(world["event_id"], world["proposal_b_id"])

        assert fixtures.read_entry(world["entry_id"])["status"] == "RFP_ISSUED"
        domain_assert.assert_room_night_inventory(fixtures.read_venue(world["venue_id"]), 0)
        domain_assert.assert_room_night_inventory(
            fixtures.read_venue(world["venue_b_id"]), 0
        )
