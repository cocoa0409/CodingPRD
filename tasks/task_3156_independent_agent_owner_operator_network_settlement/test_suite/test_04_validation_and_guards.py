"""Validation ordering, cross-entity state dependencies, terminal-state
lockdown and the refusals that protect a terminal or already-advanced row."""
from test_helpers import (
    ApiErrorId,
    bco_headers,
    cover_load,
    enroll_agent,
    get_bco,
    get_success_data,
    promote_load,
    register_customer,
    set_logical_clock,
    setup_load_ready_to_cover,
    setup_settlement_awaiting_submit,
    setup_two_loads_one_bco,
    TEST_USERS,
    validate_error,
    validate_paginated,
    validate_success,
)

SETTLEMENT_OPERATOR = TEST_USERS["settlement_operator_headers"]


class TestValidationPriority:
    """Which refusal surfaces when more than one condition fails."""

    def test_award_state_beats_safety_clearance(self, api):
        """PRD §2.10: "When several checks apply to one request, they are
        evaluated in a fixed order. The order matters because it determines which
        error surfaces when more than one condition fails."
        PRD §2.10: "4. Resource state. The target must be in the state the
        operation requires."
        PRD §2.10: "6. Business safety. The capacity owner's derived posture and
        the safety preconditions must hold."

        Design: Difficulty/priority_pair_validation_conflict/award_state_beats_safety_clearance
        """
        state = setup_two_loads_one_bco()
        agent, bco = state["agent"], state["bco"]

        # The BCO takes the first load, so a second award would double-book it.
        validate_success(
            api.accept_load_offer(
                state["offer_a"]["id"], {"accepted_at": "2026-09-01T02:00:00Z"}, bco_headers(bco)
            ), 200
        )
        # … and then declines the second offer, leaving the BCO busy while the
        # second offer is in a terminal state.
        validate_success(
            api.decline_load_offer(
                state["offer_b"]["id"], {"declined_at": "2026-09-01T04:00:00Z"}, bco_headers(bco)
            ), 200
        )

        refused = api.accept_load_offer(
            state["offer_b"]["id"], {"accepted_at": "2026-09-01T05:00:00Z"}, bco_headers(bco)
        )
        validate_error(refused, ApiErrorId.ERR_OFFER_NOT_OPEN, expected_status=409)

    def test_the_state_refusal_is_not_the_busy_refusal(self, api):
        """PRD §2.10: "5. Ownership. Where the role model assigns ownership, the
        caller must own the resource it is acting on."
        PRD §3.5: "Acceptance requires that the load be `POSTED` with
        `board_required` still true (else `ERR_LOAD_NOT_OPEN_FOR_AWARD`); that
        the accepting capacity owner is the offer's own `capacity_owner_id`".

        Design: Difficulty/priority_pair_validation_conflict/award_state_beats_safety_clearance
        """
        state = setup_two_loads_one_bco()
        bco = state["bco"]

        validate_success(
            api.accept_load_offer(
                state["offer_a"]["id"], {"accepted_at": "2026-09-01T02:00:00Z"}, bco_headers(bco)
            ), 200
        )
        api.decline_load_offer(
            state["offer_b"]["id"], {"declined_at": "2026-09-01T04:00:00Z"}, bco_headers(bco)
        )
        refused = api.accept_load_offer(
            state["offer_b"]["id"], {"accepted_at": "2026-09-01T05:00:00Z"}, bco_headers(bco)
        )

        error_id = refused.json()["data"]["error_id"]
        assert error_id == "ERR_OFFER_NOT_OPEN"
        assert error_id != "ERR_CAPACITY_OWNER_BUSY", (
            "the state table is evaluated before the safety table"
        )

        load_b = get_success_data(api.get_load(state["load_b"]["id"], TEST_USERS["network_admin_headers"]))
        assert load_b["status"] == "POSTED"
        open_offers, meta = validate_paginated(
            api.list_load_board_offers(
                state["load_b"]["id"], TEST_USERS["network_admin_headers"], params={"status": "OPEN"}
            )
        )
        assert meta["total_count"] == 0 and open_offers == []


class TestCrossEntityStateDependency:
    """A decision on one aggregate is gated by another aggregate's posture."""

    def test_settlement_submit_blocked_by_frozen_bco_posture(self, api):
        """PRD §3.6: "the capacity owner's posture must not be
        `QUALIFICATION_FROZEN` (else `ERR_CAPACITY_OWNER_QUALIFICATION_FROZEN`)".
        PRD §3.3: "and a `QUALIFICATION_FROZEN` owner may not have a settlement
        submitted against it".

        Design: Difficulty/cross_entity_state_dependency/settlement_submit_blocked_by_frozen_bco_posture
        """
        bundle = setup_settlement_awaiting_submit()
        bco, agent, settlement = bundle["bco"], bundle["agent"], bundle["settlement"]

        frozen = validate_success(
            api.decertify_capacity_owner(
                bco["id"], {"reason_code": "FALSIFIED_DRUG_TEST"},
                TEST_USERS["safety_reviewer_headers"],
            ), 200
        )
        assert frozen["status"] == "DECERTIFIED"
        assert frozen["qualification_posture"] == "QUALIFICATION_FROZEN"

        refused = api.submit_settlement(
            settlement["id"],
            {"expected_network_agent_version": get_success_data(
                api.get_agent(agent["id"], TEST_USERS["network_admin_headers"])
            )["version"]},
            SETTLEMENT_OPERATOR,
        )
        validate_error(refused, ApiErrorId.ERR_CAPACITY_OWNER_QUALIFICATION_FROZEN, expected_status=422)

    def test_the_freeze_blocks_the_submission_without_mutating_the_row(self, api):
        """PRD §3.6: "Submission moves the settlement from `DRAFT` to
        `PENDING_APPROVAL`".
        PRD §3.1: "a held agent may neither promote loads nor have settlements
        paid, and both are refused with `ERR_AGENT_SETTLEMENT_HELD`."

        Design: Difficulty/cross_entity_state_dependency/settlement_submit_blocked_by_frozen_bco_posture
        """
        bundle = setup_settlement_awaiting_submit()
        bco, agent, settlement = bundle["bco"], bundle["agent"], bundle["settlement"]

        api.decertify_capacity_owner(
            bco["id"], {"reason_code": "FALSIFIED_DRUG_TEST"}, TEST_USERS["safety_reviewer_headers"]
        )
        api.submit_settlement(
            settlement["id"],
            {"expected_network_agent_version": get_success_data(
                api.get_agent(agent["id"], TEST_USERS["network_admin_headers"])
            )["version"]},
            SETTLEMENT_OPERATOR,
        )

        settlement_after = get_success_data(
            api.get_settlement(settlement["id"], SETTLEMENT_OPERATOR)
        )
        assert settlement_after["status"] == "DRAFT", "the freeze blocked the submission rather than mutating it"

        agent_after = get_success_data(api.get_agent(agent["id"], TEST_USERS["network_admin_headers"]))
        assert agent_after["settlement_hold"] is False, (
            "the refusal came from the BCO posture rather than from the agent"
        )


class TestTerminalStateLockdown:
    """No transition leaves a terminal state."""

    def test_cancelled_load_has_no_outbound_transition(self, api):
        """PRD §3.4: "the load must still be `POSTED` (else
        `ERR_LOAD_NOT_CANCELLABLE`) and the caller must own it (else
        `ERR_UNAUTHORIZED`)".
        PRD §3.6: "where the load-side preconditions are evaluated, requires the
        load to be `DELIVERED` or `SETTLED` (else `ERR_LOAD_NOT_SETTLEABLE`)".

        Design: Corner/state_machines/cancelled_load_has_no_outbound_transition
        """
        set_logical_clock()
        agent = enroll_agent()
        customer = register_customer(agent)
        load = promote_load(agent, customer["customer_ref"])
        from test_helpers import enroll_capacity_owner, post_offer

        bco = enroll_capacity_owner()
        offer = post_offer(agent, load, bco)

        validate_success(
            api.cancel_load(load["id"], {"reason_code": "SHIPPER_CANCELLED"},
                            _agent_headers(agent)), 200
        )
        cancelled = get_success_data(api.get_load(load["id"], TEST_USERS["network_admin_headers"]))
        assert cancelled["status"] == "CANCELLED"
        offer_after = get_success_data(api.get_load_offer(offer["id"], TEST_USERS["network_admin_headers"]))
        assert offer_after["status"] == "WITHDRAWN"

        recancel = api.cancel_load(load["id"], {"reason_code": "AGAIN"}, _agent_headers(agent))
        validate_error(recancel, ApiErrorId.ERR_LOAD_NOT_CANCELLABLE)

        terminal = api.evaluate_load_settlement(
            load["id"], {"settlement_method": "PROVISIONAL"}, SETTLEMENT_OPERATOR
        )
        validate_error(terminal, ApiErrorId.ERR_LOAD_NOT_SETTLEABLE)

        still = get_success_data(api.get_load(load["id"], TEST_USERS["network_admin_headers"]))
        assert still["status"] == "CANCELLED"

    def test_pod_verification_is_not_idempotent(self, api):
        """PRD §3.6: "the trip must be `DELIVERED` (else
        `ERR_TRIP_NOT_DELIVERED`), and either a missing trip
        `proof_of_delivery_code` or a `pod_verified` that is not true is refused
        with `ERR_POD_MISSING`."

        Design: Corner/state_machines/verify_pod_twice_is_rejected_after_the_first_success
        """
        bundle = setup_settlement_awaiting_submit()
        trip = bundle["trip"]

        trip_now = get_success_data(api.get_trip(trip["id"], TEST_USERS["network_admin_headers"]))
        assert trip_now["status"] == "COMPLETED"
        version_after_first = trip_now["version"]

        second = api.verify_pod(
            trip["id"], {"pod_verified": True}, SETTLEMENT_OPERATOR
        )
        validate_error(second, ApiErrorId.ERR_TRIP_NOT_DELIVERED)

        after = get_success_data(api.get_trip(trip["id"], TEST_USERS["network_admin_headers"]))
        assert after["version"] == version_after_first, "the rejected call wrote nothing"
        assert after["status"] == "COMPLETED"


class TestCoverageGuards:
    """The covering call re-checks posture and unit currency."""

    def test_covering_a_load_needs_a_current_inspection(self, api):
        """PRD §3.5: "the named unit must have an `inspection_status` of
        `CURRENT` (else `ERR_EQUIPMENT_INSPECTION_NOT_CURRENT`) and a status of
        `IN_SERVICE` (else `ERR_EQUIPMENT_NOT_IN_SERVICE`)".
        PRD §3.5: "A deadline at or before the departure instant is refused
        outright with `ERR_INVALID_TRIP_WINDOW`."

        Design: Difficulty/priority_pair_validation_conflict/escrow_fiscal_beats_inspection_constraint
        """
        # The unit's inspection deadline lapses once the clock passes it, and the
        # BCO's escrow also sits below the floor.
        state = setup_load_ready_to_cover(inspection_due_at="2026-09-01T12:00:00Z",
                                          escrow_cents=50000)
        bco, load, unit = state["bco"], state["load"], state["equipment"]

        set_logical_clock("2026-09-02T00:00:00Z")

        unit_now = get_success_data(api.get_equipment(unit["id"], TEST_USERS["network_admin_headers"]))
        assert unit_now["inspection_status"] == "OVERDUE"

        refused = cover_load(
            bco, load, unit,
            departed_at="2026-09-02T01:00:00Z", deadline_at="2026-09-03T01:00:00Z",
            expect_error=True,
        )
        validate_error(refused, ApiErrorId.ERR_EQUIPMENT_INSPECTION_NOT_CURRENT, expected_status=409)
        assert refused.json()["data"]["error_id"] != "ERR_ESCROW_BALANCE_INSUFFICIENT", (
            "the safety table is evaluated before the fiscal table"
        )

        bco_now = get_bco(bco["id"])
        assert bco_now["escrow_balance_cents"] == 50000
        assert bco_now["qualification_posture"] == "QUALIFICATION_RESTRICTED"

        load_after = get_success_data(api.get_load(load["id"], TEST_USERS["network_admin_headers"]))
        assert load_after["status"] == "AWARDED"
        trips, meta = validate_paginated(
            api.list_load_trips(load["id"], TEST_USERS["network_admin_headers"])
        )
        assert meta["total_count"] == 0 and trips == []

    def test_covering_with_a_backwards_window_is_refused(self, api):
        """PRD §3.5: "A deadline at or before the departure instant is refused
        outright with `ERR_INVALID_TRIP_WINDOW`."
        PRD §3.5: "The load must be `AWARDED` (else `ERR_LOAD_NOT_AWARDED`); the
        owner must be `QUALIFIED_CLEAR` (else
        `ERR_CAPACITY_OWNER_NOT_QUALIFIED_CLEAR`)".

        Design: Corner/errors/trip_create_with_deadline_before_departure_returns_invalid_trip_window
        """
        state = setup_load_ready_to_cover()
        bco, load, unit = state["bco"], state["load"], state["equipment"]

        refused = cover_load(
            bco, load, unit,
            departed_at="2026-09-02T03:00:00Z", deadline_at="2026-09-01T03:00:00Z",
            expect_error=True,
        )
        validate_error(refused, ApiErrorId.ERR_INVALID_TRIP_WINDOW, expected_status=400)

        trips, meta = validate_paginated(
            api.list_load_trips(load["id"], TEST_USERS["network_admin_headers"])
        )
        assert meta["total_count"] == 0
        load_after = get_success_data(api.get_load(load["id"], TEST_USERS["network_admin_headers"]))
        assert load_after["status"] == "AWARDED", "the malformed window did not consume the award"


class TestTurnaroundBuffer:
    """The mandatory two-hour turnaround after a delivery."""

    def test_equipment_turnaround_buffer_half_open_window(self, api):
        """PRD §3.5: "with a departure that falls inside the mandatory two-hour
        turnaround buffer after the unit's previous delivery refused as
        `ERR_EQUIPMENT_TURNAROUND_OVERLAP`".

        Design: Difficulty/resource_temporal_overlap/equipment_turnaround_buffer_half_open_window
        """
        bundle = setup_sealed_equipment_with_closed_trip()
        bco, unit, next_load = bundle["bco"], bundle["equipment"], bundle["next_load"]

        refused = cover_load(
            bco, next_load, unit,
            departed_at="2026-09-02T11:59:59Z", deadline_at="2026-09-03T12:00:00Z",
            expect_error=True,
        )
        validate_error(refused, ApiErrorId.ERR_EQUIPMENT_TURNAROUND_OVERLAP, expected_status=409)

        trips, meta = validate_paginated(
            api.list_equipment_trips(unit["id"], TEST_USERS["network_admin_headers"])
        )
        assert meta["total_count"] == 1, "the rejected trip created nothing"

    def test_the_buffer_window_is_half_open_at_its_lower_edge(self, api):
        """PRD §3.5: "no trip referencing that unit may already be
        `DISPATCH_PENDING` or `EN_ROUTE` (else `ERR_EQUIPMENT_ALREADY_ASSIGNED`)".

        Design: Difficulty/resource_temporal_overlap/equipment_turnaround_buffer_half_open_window
        """
        bundle = setup_sealed_equipment_with_closed_trip()
        bco, unit, next_load = bundle["bco"], bundle["equipment"], bundle["next_load"]

        accepted = validate_success(
            cover_load(
                bco, next_load, unit,
                departed_at="2026-09-02T12:00:01Z", deadline_at="2026-09-03T12:00:00Z",
                expect_error=True,
            ), 201
        )
        assert accepted["status"] == "DISPATCH_PENDING"


def setup_sealed_equipment_with_closed_trip():
    """Delegates to the shared fixture helper of the same name."""
    from test_helpers import setup_sealed_equipment_with_closed_trip as _helper
    return _helper()


def _agent_headers(agent):
    from test_helpers import make_freight_agent_headers
    return make_freight_agent_headers(agent["id"])