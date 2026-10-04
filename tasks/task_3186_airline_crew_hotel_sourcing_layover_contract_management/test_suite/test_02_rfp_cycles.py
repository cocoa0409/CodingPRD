"""RFP cycle lifecycle: states, negotiation loop, deadline gate, OCC, award."""
import pytest

from test_helpers import (
    validate_success, validate_error, validate_paginated,
    ApiErrorId,
    make_station, make_vendor, make_open_cycle_with_proposal,
    make_negotiation_cycle, award_cycle,
    create_rfp_cycle_payload, create_proposal_payload, create_award_payload,
    make_vendor_rep_headers,
)
from test_helpers.fixtures import ADMIN, SOURCING, CREWOPS


class TestCycleStates:

    def test_rfp_cycle_initial_state_draft(self, api):
        """PRD §3.2: "A new cycle is born in `DRAFT`."
        PRD §3.2: "moving the cycle `EVALUATION → NEGOTIATION` and incrementing the
        cycle's `negotiation_round` by 1 (the round counter starts at 0)."

        Design: Corner/state_machines/rfp_cycle_initial_state_draft
        """
        station = make_station(code="GJT")
        resp = api.create_rfp_cycle(create_rfp_cycle_payload(
            station_id=station["id"], title="GJT 2026 crew hotel"), SOURCING)
        data = validate_success(resp, expected_status=201)
        assert data["status"] == "DRAFT"
        assert data["negotiation_round"] == 0

    def test_open_negotiation_from_draft_rejected(self, api):
        """PRD §3.2: "From `EVALUATION`, the manager may open negotiation — but only
        if at least one proposal of the cycle is `SHORTLISTED` — moving the cycle
        `EVALUATION → NEGOTIATION` and incrementing the cycle's `negotiation_round`
        by 1 (the round counter starts at 0)."
        PRD §2.10: "then state-machine legality (the requested transition exists from
        the target resource's current state, `ERR_INVALID_STATE`)".

        Design: Corner/state_machines/open_negotiation_from_draft_rejected
        """
        station = make_station(code="GJT")
        cycle = validate_success(api.create_rfp_cycle(
            create_rfp_cycle_payload(station_id=station["id"]), SOURCING),
            expected_status=201)
        resp = api.open_negotiation(cycle["id"], SOURCING)
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE)
        fresh = validate_success(api.get_rfp_cycle(cycle["id"], SOURCING))
        assert fresh["status"] == "DRAFT"

    def test_terminal_cycle_rejects_further_transitions(self, api):
        """PRD §3.2: "Cancellation is the escape hatch: from any non-terminal cycle
        state (`DRAFT`, `OPEN`, `EVALUATION`, or `NEGOTIATION`), cancelling the cycle
        moves it to `CANCELLED` and cascades every proposal still in `SUBMITTED`,
        `UNDER_REVIEW`, or `SHORTLISTED` to `REJECTED`. Both `AWARDED` and
        `CANCELLED` are terminal."

        Design: Corner/state_machines/terminal_cycle_rejects_further_transitions
        """
        station = make_station(code="GJT")
        cycle = validate_success(api.create_rfp_cycle(
            create_rfp_cycle_payload(station_id=station["id"]), SOURCING),
            expected_status=201)
        validate_success(api.cancel_rfp_cycle(cycle["id"], SOURCING))
        resp = api.open_rfp_cycle(cycle["id"], SOURCING)
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE)
        fresh = validate_success(api.get_rfp_cycle(cycle["id"], SOURCING))
        assert fresh["status"] == "CANCELLED"

    def test_cycle_cancel_cascades_proposals_to_rejected(self, api):
        """PRD §3.2: "Cancellation is the escape hatch: from any non-terminal cycle
        state (`DRAFT`, `OPEN`, `EVALUATION`, or `NEGOTIATION`), cancelling the cycle
        moves it to `CANCELLED` and cascades every proposal still in `SUBMITTED`,
        `UNDER_REVIEW`, or `SHORTLISTED` to `REJECTED`. Both `AWARDED` and
        `CANCELLED` are terminal."

        Design: Corner/state_machines/cycle_cancel_cascades_proposals_to_rejected
        """
        station = make_station(code="FCA")
        vendor = make_vendor(name="Glacier Lodge",
                             contact_email="ops@glacierlodge.example")
        cycle, proposal = make_open_cycle_with_proposal(station["id"], vendor)
        validate_success(api.cancel_rfp_cycle(cycle["id"], SOURCING))
        fresh_cycle = validate_success(api.get_rfp_cycle(cycle["id"], SOURCING))
        assert fresh_cycle["status"] == "CANCELLED"
        fresh_prop = validate_success(api.get_proposal(proposal["id"], SOURCING))
        assert fresh_prop["status"] == "REJECTED"


class TestNegotiationLoop:

    def test_negotiation_round_counts_forward_entries(self, api):
        """PRD §3.2: "The same open-negotiation action, invoked while the cycle is
        already in `NEGOTIATION`, returns it `NEGOTIATION → EVALUATION` when no
        counter-offer advances the round; the return direction does not increment
        `negotiation_round`."

        Design: Difficulty/non_linear_state_machine/rfp_cycle_evaluation_negotiation_cycle
        """
        station = make_station(code="PHX")
        vendor = make_vendor(name="Desert Inn",
                             contact_email="ops@desertinn.example")
        cycle, proposal = make_negotiation_cycle(
            station["id"], vendor, rate_cents=11000, rooms=8)
        assert cycle["status"] == "NEGOTIATION"
        assert cycle["negotiation_round"] == 1
        # return branch: NEGOTIATION -> EVALUATION without incrementing the round
        back = validate_success(api.open_negotiation(cycle["id"], SOURCING))
        assert back["status"] == "EVALUATION"
        assert back["negotiation_round"] == 1
        # second forward entry
        fwd = validate_success(api.open_negotiation(cycle["id"], SOURCING))
        assert fwd["status"] == "NEGOTIATION"
        assert fwd["negotiation_round"] == 2

    def test_counter_offer_rewrites_current_rate(self, api):
        """PRD §3.2: "During negotiation, the manager rewrites a shortlisted
        proposal's economics with a counter-offer carrying a `new_rate_cents`; the
        proposal's `current_rate_cents` is set to that value and its `version`
        increments."

        Design: Difficulty/non_linear_state_machine/rfp_cycle_evaluation_negotiation_cycle
        """
        station = make_station(code="PHX")
        vendor = make_vendor(name="Desert Inn",
                             contact_email="ops@desertinn.example")
        cycle, proposal = make_negotiation_cycle(
            station["id"], vendor, rate_cents=11000, rooms=8)
        validate_success(api.counter_offer_proposal(
            proposal["id"], {"new_rate_cents": 10000}, SOURCING))
        fresh = validate_success(api.get_proposal(proposal["id"], SOURCING))
        assert fresh["current_rate_cents"] == 10000
        assert fresh["offered_rate_cents"] == 11000


class TestProposalDeadline:

    def test_proposal_after_deadline_rejected(self, api):
        """PRD §3.3: "Timing is enforced at submission: if the logical clock has
        already passed the cycle's `response_deadline`, the submission is rejected
        with `ERR_DEADLINE_PASSED` (HTTP 422)."

        Design: Corner/validations/proposal_after_deadline_rejected
        """
        station = make_station(code="CPR")
        vendor = make_vendor(name="Platte River Inn",
                             contact_email="ops@platteriver.example")
        # The startup logical clock is 2026-11-01; use a deadline just after it so
        # the cycle can open, then advance the clock past the deadline.
        cycle = validate_success(api.create_rfp_cycle(create_rfp_cycle_payload(
            station_id=station["id"], response_deadline="2026-11-05T00:00:00Z"),
            SOURCING), expected_status=201)
        validate_success(api.open_rfp_cycle(cycle["id"], SOURCING))
        api.set_clock("2026-11-06T00:00:00Z", ADMIN)
        resp = api.submit_proposal(cycle["id"], create_proposal_payload(
            vendor_id=vendor["id"]), make_vendor_rep_headers(vendor["id"]))
        validate_error(resp, ApiErrorId.ERR_DEADLINE_PASSED)

    def test_state_gate_beats_temporal_deadline_on_proposal_submit(self, api):
        """PRD §2.10: "Every request passes through a fixed gauntlet of checks,
        evaluated in this order: authentication first (missing or undeclared role
        header, `ERR_UNAUTHENTICATED`), then authorization (role not permitted for
        the endpoint, or an entity-backed ownership check failure such as a vendor
        representative withdrawing another vendor's proposal, `ERR_FORBIDDEN`), then
        existence (every identifier in the path and every foreign-key identifier in
        the body resolves to an existing entity, validated left-to-right,
        `ERR_NOT_FOUND`), then state-machine legality (the requested transition
        exists from the target resource's current state, `ERR_INVALID_STATE`), then
        the business and safety rules attached to the specific endpoint in the
        priority order §3 narrates, and finally request shape (required fields
        present, enum values valid, datetime ranges ordered with the end after the
        start, `ERR_INVALID_REQUEST`)."
        PRD §3.3: "A `HotelVendorRep` participates by submitting a proposal to an
        `OPEN` cycle."

        Design: Difficulty/priority_pair_validation_conflict/state_gate_beats_temporal_deadline_on_proposal_submit
        """
        station = make_station(code="ICT")
        vendor = make_vendor(name="Keeper Hotel",
                             contact_email="ops@keeperhotel.example")
        cycle = validate_success(api.create_rfp_cycle(create_rfp_cycle_payload(
            station_id=station["id"], response_deadline="2026-11-05T00:00:00Z"),
            SOURCING), expected_status=201)
        validate_success(api.open_rfp_cycle(cycle["id"], SOURCING))
        validate_success(api.close_rfp_cycle(cycle["id"], SOURCING))
        # advance the clock past the deadline: both conditions now hold
        api.set_clock("2026-11-06T00:00:00Z", ADMIN)
        resp = api.submit_proposal(cycle["id"], create_proposal_payload(
            vendor_id=vendor["id"]), make_vendor_rep_headers(vendor["id"]))
        # state-machine legality outranks the temporal business rule
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE)
        data, meta = validate_paginated(api.list_proposals(
            SOURCING, params={"rfp_cycle_id": cycle["id"]}))
        assert len(data) == 0

    def test_proposal_submission_before_deadline_accepted(self, api):
        """PRD §3.3: "Timing is enforced at submission: if the logical clock has
        already passed the cycle's `response_deadline`, the submission is rejected
        with `ERR_DEADLINE_PASSED` (HTTP 422)."
        PRD §3.3: "A `HotelVendorRep` participates by submitting a proposal to an
        `OPEN` cycle."

        Design: Difficulty/priority_pair_validation_conflict/state_gate_beats_temporal_deadline_on_proposal_submit
        """
        station = make_station(code="ICT")
        vendor = make_vendor(name="Keeper Hotel",
                             contact_email="ops@keeperhotel.example")
        cycle = validate_success(api.create_rfp_cycle(create_rfp_cycle_payload(
            station_id=station["id"], response_deadline="2026-11-05T00:00:00Z"),
            SOURCING), expected_status=201)
        validate_success(api.open_rfp_cycle(cycle["id"], SOURCING))
        # cycle OPEN and the deadline still in the future -> submission succeeds
        data = validate_success(api.submit_proposal(
            cycle["id"], create_proposal_payload(vendor_id=vendor["id"]),
            make_vendor_rep_headers(vendor["id"])), expected_status=201)
        assert data["status"] == "SUBMITTED"


class TestProposalListing:

    def test_get_proposals_filtered_by_cycle_reverse_fk(self, api):
        """PRD §3.3: "The proposal list supports reverse lookups by `rfp_cycle_id?`,
        `vendor_id?`, and `status?`."

        Design: Corner/endpoints/get_proposals_filtered_by_cycle_reverse_fk
        """
        station = make_station(code="SAF")
        vendor = make_vendor(name="Adobe Inn", contact_email="ops@adobeinn.example")
        cycle, proposal = make_open_cycle_with_proposal(station["id"], vendor)
        data, meta = validate_paginated(api.list_proposals(
            SOURCING, params={"rfp_cycle_id": cycle["id"]}))
        assert len(data) == 1
        assert data[0]["id"] == proposal["id"]


class TestImmediateConsistency:

    def test_immediate_consistency_mutation_visible_in_response(self, api):
        """PRD §2.2: "Unless otherwise noted, operations that create or modify a
        resource will return the created or updated resource object in the data
        field."
        PRD §3.2: "Opening the cycle moves it `DRAFT → OPEN`; this is allowed only
        while the cycle's `response_deadline` is still in the future relative to the
        logical clock."

        Design: Corner/consistency_model/immediate_consistency_mutation_visible_in_response
        """
        station = make_station(code="BFF")
        cycle = validate_success(api.create_rfp_cycle(
            create_rfp_cycle_payload(station_id=station["id"]), SOURCING),
            expected_status=201)
        resp = api.open_rfp_cycle(cycle["id"], SOURCING)
        data = validate_success(resp)
        assert data["status"] == "OPEN"
