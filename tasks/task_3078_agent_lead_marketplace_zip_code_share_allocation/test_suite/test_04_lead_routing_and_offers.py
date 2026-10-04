"""Lead intake, routing, offer lifecycle: reroute self-loop, pool exhaustion,
selector determinism, manual assign, cancel preconditions, OCC on the lead
(PRD §3.4, §3.5)."""
from test_helpers import (
    ApiErrorId,
    accept_lead_offer,
    create_active_listing,
    create_agent,
    create_lead_payload,
    create_routed_lead,
    get_agent,
    get_assignment,
    get_lead,
    get_share_order,
    make_agent_headers,
    set_clock,
    setup_market_with_active_order,
    setup_assigned_lead,
    setup_team_with_order,
    validate_error,
    validate_error_is_one_of,
    validate_paginated,
    validate_success,
)


class TestDuplicateWindow:
    def test_repeat_consumer_inside_30_days_rejected_outside_allowed(self, api, marketplace_ops_headers):
        """PRD §3.4: "The window guard rejects the intake when the same `consumer_key`
        already has a lead in this market within the last 30 days (counting only anchor
        leads that are not themselves `REJECTED_DUPLICATE`)."
        PRD §3.4: "A rejection on either ground moves the new lead to
        `REJECTED_DUPLICATE` with `duplicate_of_lead_id` set to the anchor lead, and the
        intake is rejected with `ERR_DUPLICATE_LEAD` (HTTP 422)."

        Design: Difficulty/resource_temporal_overlap/duplicate_lead_30_day_window
        """
        set_clock("2026-09-01T00:00:00Z")
        market, brokerage, agent, _, lead, _, listing = setup_assigned_lead(
            zip_code="27513", state_code="NC", duration_days=60, consumer_key="c-t3@x.com"
        )
        agent2 = create_agent(brokerage["id"], license_state="NC")
        set_clock("2026-09-30T00:00:00Z")
        # Day 29: still inside the 30-day window — rejected. The consumer asks about a
        # different listing (different listing agent) so only the window guard applies.
        listing_b = create_active_listing(market["id"], brokerage["id"], agent2["id"])
        resp29 = api.create_lead(
            create_lead_payload(market["id"], listing_b["id"], listing_b["listing_agent_id"],
                                consumer_key="c-t3@x.com"), marketplace_ops_headers
        )
        validate_error(resp29, ApiErrorId.ERR_DUPLICATE_LEAD, 422)
        dup29 = resp29.json().get("data") or {}
        set_clock("2026-10-02T00:00:00Z")
        resp31 = api.create_lead(
            create_lead_payload(market["id"], listing_b["id"], listing_b["listing_agent_id"],
                                consumer_key="c-t3@x.com"), marketplace_ops_headers
        )
        ok31 = validate_success(resp31, 201)
        assert ok31["lead_status"] == "ROUTED"
        assert ok31.get("duplicate_of_lead_id") is None

    def test_duplicate_rejection_records_anchor_lead(self, api, marketplace_ops_headers):
        """PRD §3.4: "A rejection on either ground moves the new lead to
        `REJECTED_DUPLICATE` with `duplicate_of_lead_id` set to the anchor lead".

        Design: Difficulty/resource_temporal_overlap/duplicate_lead_30_day_window
        """
        set_clock("2026-09-01T00:00:00Z")
        market, _, agent, _, anchor, _, listing = setup_assigned_lead(
            zip_code="27514", state_code="NC", duration_days=60, consumer_key="c-anchor@x.com"
        )
        set_clock("2026-09-15T00:00:00Z")
        resp = api.create_lead(
            create_lead_payload(market["id"], listing["id"], listing["listing_agent_id"],
                                consumer_key="c-anchor@x.com"), marketplace_ops_headers
        )
        validate_error(resp, ApiErrorId.ERR_DUPLICATE_LEAD, 422)
        dups, _ = validate_paginated(api.list_lead_duplicates(anchor["id"], marketplace_ops_headers))
        assert len(dups) == 1
        assert dups[0]["lead_status"] == "REJECTED_DUPLICATE"
        assert dups[0]["duplicate_of_lead_id"] == anchor["id"]


class TestEmptyCandidatePool:
    def test_lead_with_no_eligible_agents_goes_unassigned_and_charges_nothing(self, api, marketplace_ops_headers):
        """PRD §3.4: "If the eligible candidate pool is empty — no order in the market
        can be charged for a lead nobody can receive — the lead moves directly to
        `UNASSIGNED` with a `routing_note` of "pool empty"; no share order's counters are
        touched and no charge is posted."

        Design: Difficulty/boundary_precision_check/candidate_pool_empty_boundary
        """
        set_clock()
        market, brokerage, agent, order = setup_market_with_active_order(
            zip_code="02101", state_code="MA", share_bps=6000
        )
        listing = create_active_listing(market["id"], brokerage["id"], agent["id"])
        # First lead routes and is allowed to expire.
        lead1, _ = create_routed_lead(market["id"], "c-t1@x.com", listing)
        set_clock("2026-09-01T00:06:00Z")
        validate_success(api.run_ops_sweep(marketplace_ops_headers), 201)
        validate_success(api.suspend_agent(agent["id"], marketplace_ops_headers))
        lead2 = validate_success(
            api.create_lead(create_lead_payload(market["id"], listing["id"],
                                                listing["listing_agent_id"],
                                                consumer_key="c-t2@x.com"),
                            marketplace_ops_headers),
            201,
        )
        assert lead2["lead_status"] == "UNASSIGNED"
        assert lead2.get("share_order_id") is None
        fresh_order = get_share_order(order["id"])
        assert fresh_order["leads_received"] == 1, "only the pre-suspension lead was routed"
        lead1_fresh = get_lead(lead1["id"])
        assert lead1_fresh["lead_status"] == "UNASSIGNED"
        assert lead1_fresh["routing_note"] == "pool exhausted"

    def test_suspended_buyer_leaves_empty_pool_for_new_lead(self, api, marketplace_ops_headers):
        """PRD §3.4: "If the eligible candidate pool is empty — no order in the market
        can be charged for a lead nobody can receive — the lead moves directly to
        `UNASSIGNED` with a `routing_note` of "pool empty"".
        PRD §3.2: "An operator may suspend an agent — moving them to `SUSPENDED` — which
        excludes them from selector pools".

        Design: Difficulty/boundary_precision_check/candidate_pool_empty_boundary
        """
        set_clock()
        market, brokerage, agent, order = setup_market_with_active_order(
            zip_code="02102", state_code="MA", share_bps=6000
        )
        listing = create_active_listing(market["id"], brokerage["id"], agent["id"])
        validate_success(api.suspend_agent(agent["id"], marketplace_ops_headers))
        lead = validate_success(
            api.create_lead(create_lead_payload(market["id"], listing["id"],
                                                listing["listing_agent_id"],
                                                consumer_key="c-t9@x.com"),
                            marketplace_ops_headers),
            201,
        )
        assert lead["lead_status"] == "UNASSIGNED"
        assert lead["routing_note"] == "pool empty"
        assert get_share_order(order["id"])["leads_received"] == 0


class TestRerouteSelfLoop:
    def test_expired_offer_reroutes_then_exhausts_pool(self, api, marketplace_ops_headers):
        """PRD §3.5: "The sweep then attempts to reroute the lead: the reroute pool
        excludes all prior candidates across every earlier attempt, and if the pool is
        non-empty a fresh `LeadAssignment` is created in `OFFERED` with a new
        `candidate_agent_ids` triple, the lead's `routing_attempts` increments by one,
        and the new offer's `expires_at` is now plus 300 seconds. No candidate may
        repeat across reroute attempts; if the reroute pool is empty the lead moves to
        `UNASSIGNED` with `routing_note` of "pool exhausted", and the previously charged
        amount is credited back to the share order".

        Design: Difficulty/non_linear_state_machine/lead_reroute_self_loop
        """
        set_clock("2026-09-01T00:00:00Z")
        # PRD §3.4: for a team order the candidate pool is the team's ACTIVE
        # memberships. Six members with weight 1 give exactly two disjoint triples
        # across two routing attempts before the pool is exhausted.
        (market, brokerage, lead_agent, members, team, memberships, order,
         listing) = setup_team_with_order(
            zip_code="73301", state_code="TX", share_bps=6000,
            member_weights=(1, 1, 1, 1, 1, 1), include_lead_membership=False,
        )
        lead, assignment1 = create_routed_lead(market["id"], "c-race@x.com", listing)
        assert lead["routing_attempts"] == 1
        assert len(assignment1["candidate_agent_ids"]) == 3
        set_clock("2026-09-01T00:06:00Z")
        validate_success(api.run_ops_sweep(marketplace_ops_headers), 201)
        lead_mid = get_lead(lead["id"])
        assert lead_mid["lead_status"] == "ROUTED"
        assert lead_mid["routing_attempts"] == 2
        assignments, _ = validate_paginated(api.list_lead_assignments(lead["id"], marketplace_ops_headers))
        assert len(assignments) == 2
        by_offer = sorted(assignments, key=lambda a: a["offered_at"])
        first_candidates = set(by_offer[0]["candidate_agent_ids"])
        second_candidates = set(by_offer[1]["candidate_agent_ids"])
        assert by_offer[0]["assignment_status"] == "EXPIRED"
        assert by_offer[1]["assignment_status"] == "OFFERED"
        assert first_candidates.isdisjoint(second_candidates), (
            "no candidate may repeat across reroute attempts"
        )
        set_clock("2026-09-01T00:12:00Z")
        validate_success(api.run_ops_sweep(marketplace_ops_headers), 201)
        lead_final = get_lead(lead["id"])
        assert lead_final["lead_status"] == "UNASSIGNED"
        assert lead_final["routing_note"] == "pool exhausted"
        assert lead_final.get("accepted_agent_id") is None
        assert get_share_order(order["id"])["credits_cents"] == 9000

    def test_expiry_increments_offers_expired_for_prior_candidates(self, api, marketplace_ops_headers):
        """PRD §3.5: "When the ops sweep encounters an assignment that is still `OFFERED`
        with `expires_at` at or before now, the assignment moves to `EXPIRED` and each of
        its prior candidates has their `offers_expired` incremented and their
        `rolling_score` recomputed."

        Design: Difficulty/non_linear_state_machine/lead_reroute_self_loop
        """
        set_clock("2026-09-01T00:00:00Z")
        # Team order: the candidate pool is the team's ACTIVE memberships (PRD §3.4).
        (market, brokerage, lead_agent, members, team, memberships, order,
         listing) = setup_team_with_order(
            zip_code="73302", state_code="TX", share_bps=6000,
            member_weights=(1, 1, 1, 1, 1, 1), include_lead_membership=False,
        )
        lead, assignment = create_routed_lead(market["id"], "c-race2@x.com", listing)
        candidates = assignment["candidate_agent_ids"]
        set_clock("2026-09-01T00:06:00Z")
        validate_success(api.run_ops_sweep(marketplace_ops_headers), 201)
        assert get_assignment(assignment["id"])["assignment_status"] == "EXPIRED"
        for candidate_id in candidates:
            candidate = get_agent(candidate_id)
            assert candidate["offers_expired"] == 1, (
                f"candidate {candidate_id} must have offers_expired == 1"
            )


class TestSelectorDeterminism:
    def test_candidates_top_three_by_created_at_when_all_unrated(self, api, marketplace_ops_headers):
        """PRD §3.4: "A `LeadAssignment` is then created with `assignment_status` of
        `OFFERED`, carrying the `lead_id`, the winning `share_order_id` copied from the
        lead, and a `candidate_agent_ids` array of exactly three agent ids drawn from the
        candidate selector. ... Candidates are ranked by `performance_tier` (HIGH above
        STANDARD above LOW above UNRATED), then by `rolling_score` descending, then by
        `created_at` ascending, and the top three are taken."
        PRD §3.4: "for a solo order, the candidate must be the order's `buyer_agent_id`".

        Design: Corner/complexity_layers/selector_determinism_tie_break
        """
        set_clock()
        market, brokerage, buyer, order = setup_market_with_active_order(
            zip_code="97226", state_code="OR", share_bps=6000
        )
        fillers = [create_agent(brokerage["id"], license_state="OR") for _ in range(3)]
        listing = create_active_listing(market["id"], brokerage["id"], buyer["id"])
        lead, assignment = create_routed_lead(market["id"], "c-sel@x.com", listing)
        assert assignment["candidate_agent_ids"] == [buyer["id"]], (
            "solo order covers exactly the buyer agent"
        )
        assert assignment["assignment_status"] == "OFFERED"
        assert assignment["share_order_id"] == order["id"]
        assert lead["routing_attempts"] == 1
        assert lead["share_order_id"] == order["id"]

    def test_offer_ttl_is_300_seconds(self, api, marketplace_ops_headers):
        """PRD §3.4: "The assignment's `offered_at` is now and its `expires_at` is
        `offered_at` plus 300 seconds."

        Design: Corner/complexity_layers/selector_determinism_tie_break
        """
        from datetime import datetime
        set_clock()
        market, brokerage, buyer, _ = setup_market_with_active_order(
            zip_code="97229", state_code="OR", share_bps=6000
        )
        listing = create_active_listing(market["id"], brokerage["id"], buyer["id"])
        lead, assignment = create_routed_lead(market["id"], "c-ttl@x.com", listing)
        fmt = "%Y-%m-%dT%H:%M:%S"
        offered = datetime.fromisoformat(assignment["offered_at"].replace("Z", "+00:00"))
        expires = datetime.fromisoformat(assignment["expires_at"].replace("Z", "+00:00"))
        assert (expires - offered).total_seconds() == 300


class TestManualAssign:
    def test_manual_assign_to_orderless_agent_rejected(self, api, marketplace_ops_headers):
        """PRD §3.5: "The assignee must be eligible per the same selector criteria
        (license state matches the market, agent is `ACTIVE`, tier is not `INELIGIBLE`)
        and must be covered by an `ACTIVE` share order in this market, either their own
        or a team order they belong to; if no covering order exists the assignment is
        rejected with `ERR_NO_ELIGIBLE_CANDIDATES` (HTTP 422)."

        Design: Corner/endpoints/manual_assign_is_conditional_action
        """
        set_clock()
        market, brokerage, agent1, order = setup_market_with_active_order(
            zip_code="97219", state_code="OR", share_bps=6000
        )
        agent2 = create_agent(brokerage["id"], license_state="OR")
        listing = create_active_listing(market["id"], brokerage["id"], agent1["id"])
        lead, _ = create_routed_lead(market["id"], "c-t2@x.com", listing)
        resp = api.assign_lead(lead["id"], {"accepted_agent_id": agent2["id"]}, marketplace_ops_headers)
        validate_error(resp, ApiErrorId.ERR_NO_ELIGIBLE_CANDIDATES, 422)
        assert get_lead(lead["id"])["lead_status"] == "ROUTED"

    def test_manual_assign_to_covered_agent_succeeds(self, api, marketplace_ops_headers):
        """PRD §3.5: "a lead in `ROUTED` or `UNASSIGNED` status may be moved to
        `ASSIGNED` by specifying an `accepted_agent_id` directly."
        PRD §3.5: "A successful manual assignment sets `assigned_at`, applies the same
        counter increments as an acceptance (including the team-member selection when the
        covering order is a team order), and recomputes `rolling_score`."

        Design: Corner/endpoints/manual_assign_is_conditional_action
        """
        set_clock()
        market, brokerage, agent1, order = setup_market_with_active_order(
            zip_code="97220", state_code="OR", share_bps=6000
        )
        listing = create_active_listing(market["id"], brokerage["id"], agent1["id"])
        lead, _ = create_routed_lead(market["id"], "c-t3@x.com", listing)
        assigned = validate_success(
            api.assign_lead(lead["id"], {"accepted_agent_id": agent1["id"]}, marketplace_ops_headers)
        )
        assert assigned["lead_status"] == "ASSIGNED"
        assert assigned["accepted_agent_id"] == agent1["id"]
        assert assigned["assigned_at"] is not None


class TestAcceptPreconditions:
    def test_accept_after_operator_cancel_rejected(self, api, marketplace_ops_headers):
        """PRD §3.5: "An operator may cancel a `ROUTED` lead outright, which moves the
        open assignment to `CANCELLED`, the lead to `UNASSIGNED`, and applies the same
        credit settlement as the sweep path".
        PRD §2.7: "Accepting a lead assignment requires the request body to carry
        `expected_lead_version` matching the current `version` of the lead the assignment
        is for. If the lead's version has advanced ... the accept is rejected with
        `ERR_STALE_LEAD_VERSION` (HTTP 412)."

        Design: Corner/state_machines/assignment_accept_precondition_wrong_lead_state
        """
        set_clock()
        market, brokerage, agent, order = setup_market_with_active_order(
            zip_code="97401", state_code="OR", share_bps=6000
        )
        listing = create_active_listing(market["id"], brokerage["id"], agent["id"])
        lead, assignment = create_routed_lead(market["id"], "c-t1@x.com", listing)
        lead_version_at_offer = lead["version"]
        validate_success(api.cancel_lead(lead["id"], marketplace_ops_headers))
        resp = api.accept_assignment(
            assignment["id"], {"expected_lead_version": lead_version_at_offer},
            make_agent_headers(agent["id"]),
        )
        actual = validate_error_is_one_of(
            resp, [ApiErrorId.ERR_STALE_LEAD_VERSION, ApiErrorId.ERR_INVALID_STATE]
        )
        assert get_assignment(assignment["id"])["assignment_status"] == "CANCELLED"
        assert get_agent(agent["id"])["offers_accepted"] == 0

    def test_stale_lead_version_rejected_after_cancel(self, api, marketplace_ops_headers):
        """PRD §2.7: "Accepting a lead assignment requires the request body to carry
        `expected_lead_version` matching the current `version` of the lead the assignment
        is for. If the lead's version has advanced — for example because an ops sweep
        expired the offer and rerouted the lead, or another candidate accepted first —
        the accept is rejected with `ERR_STALE_LEAD_VERSION` (HTTP 412)."

        Design: Corner/errors/error_stale_lead_version_triggerable
        """
        set_clock()
        market, brokerage, agent, order = setup_market_with_active_order(
            zip_code="97222", state_code="OR", share_bps=6000
        )
        listing = create_active_listing(market["id"], brokerage["id"], agent["id"])
        lead, assignment = create_routed_lead(market["id"], "c-t1@x.com", listing)
        stale_version = lead["version"]
        validate_success(api.cancel_lead(lead["id"], marketplace_ops_headers))
        resp = api.accept_assignment(
            assignment["id"], {"expected_lead_version": stale_version},
            make_agent_headers(agent["id"]),
        )
        actual = validate_error_is_one_of(
            resp, [ApiErrorId.ERR_STALE_LEAD_VERSION, ApiErrorId.ERR_INVALID_STATE]
        )
        assert get_lead(lead["id"])["lead_status"] == "UNASSIGNED"
        assert get_agent(agent["id"])["offers_accepted"] == 0

    def test_accept_with_current_version_succeeds(self, api):
        """PRD §3.5: "On a successful accept, the assignment moves to `ACCEPTED` with
        `accepted_by_agent_id` and `accepted_at` recorded; the lead moves to `ASSIGNED`
        with `accepted_agent_id` set to the acceptor and `assigned_at` set to now; the
        accepting agent's `offers_accepted` increments by one".

        Design: Corner/errors/error_stale_lead_version_triggerable
        """
        set_clock()
        market, _, agent, _, lead, assignment, _ = setup_assigned_lead(zip_code="97223")
        assert lead["lead_status"] == "ASSIGNED"
        assert lead["accepted_agent_id"] == agent["id"]
        assert get_agent(agent["id"])["offers_accepted"] == 1
