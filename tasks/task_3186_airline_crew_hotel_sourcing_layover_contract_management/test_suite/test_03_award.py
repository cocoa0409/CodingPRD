"""Contract award: budget gate, cascade, required fields, stale-version OCC,
and award-driven contract creation."""
import pytest

from test_helpers import (
    validate_success, validate_error,
    ApiErrorId,
    make_station, make_vendor, make_open_cycle_with_proposal,
    make_negotiation_cycle, award_cycle,
    create_award_payload, create_proposal_payload, make_vendor_rep_headers,
)
from test_helpers.fixtures import ADMIN, SOURCING, CREWOPS


class TestAwardBudgetGate:

    def test_award_over_budget_rejected(self, api):
        """PRD §3.2: "Second, the budget gate: the preliminary contract value — the
        proposal's `current_rate_cents` multiplied by the award's `room_block_size`
        multiplied by the number of whole nights between `start_date` and `end_date`
        (partial days discarded), the integer product rounded half-up to whole cents
        once at the end — must be no more than the cycle's `budget_cap_cents`, or the
        award is rejected with `ERR_BUDGET_EXCEEDED` (HTTP 422)."

        Design: Corner/validations/award_over_budget_rejected
        """
        station = make_station(code="ROW")
        vendor = make_vendor(name="Alien Inn", contact_email="ops@alieninn.example")
        cycle, proposal = make_negotiation_cycle(
            station["id"], vendor, rate_cents=9000, rooms=5,
            budget_cap_cents=100000)
        fresh = validate_success(api.get_rfp_cycle(cycle["id"], SOURCING))
        # 9000 x 5 x 10 nights = 450000 > 100000
        resp = api.award_rfp_cycle(cycle["id"], create_award_payload(
            proposal_id=proposal["id"], room_block_size=5,
            expected_cycle_version=fresh["version"]), SOURCING)
        validate_error(resp, ApiErrorId.ERR_BUDGET_EXCEEDED)
        cycle_after = validate_success(api.get_rfp_cycle(cycle["id"], SOURCING))
        assert cycle_after["status"] == "NEGOTIATION"

    def test_award_at_exact_budget_boundary_succeeds(self, api):
        """PRD §3.2: "Second, the budget gate: the preliminary contract value — the
        proposal's `current_rate_cents` multiplied by the award's `room_block_size`
        multiplied by the number of whole nights between `start_date` and `end_date`
        (partial days discarded), the integer product rounded half-up to whole cents
        once at the end — must be no more than the cycle's `budget_cap_cents`, or the
        award is rejected with `ERR_BUDGET_EXCEEDED` (HTTP 422)."
        PRD §2.8: "Comparison boundaries are inclusive where §3 states them with
        \"at least\" or \"no more than\" phrasing; a value sitting exactly on a
        threshold passes the check."

        Design: Corner/validations/award_over_budget_rejected
        """
        station = make_station(code="ROW")
        vendor = make_vendor(name="Alien Inn", contact_email="ops@alieninn.example")
        # 9000 x 5 x 10 nights = 450000 == budget cap exactly -> passes
        cycle, proposal = make_negotiation_cycle(
            station["id"], vendor, rate_cents=9000, rooms=5,
            budget_cap_cents=450000)
        contract = award_cycle(cycle, proposal, room_block_size=5)
        assert contract["status"] == "DRAFT"


class TestAwardRequiredFields:

    def test_award_requires_all_contract_terms_fields(self, api):
        """PRD §3.2: "From `NEGOTIATION`, the manager awards the cycle by naming a
        `proposal_id` that references a proposal of this cycle whose status is
        `SHORTLISTED`, and supplying the contract terms: `room_block_size` (at least
        1), `start_date`, `end_date` (which must fall after `start_date`),
        `late_cancel_hours` (at least 0), a `quiet_room_standard` of `BASIC`,
        `ENHANCED`, or `PREMIUM`, a `security_requirements` array of security clause
        identifiers (defaulting to an empty array), a `blackout_dates` array of ISO
        8601 dates in `YYYY-MM-DD` form on which the negotiated rate does not apply
        (defaulting to empty), and a `blackout_protection` boolean (defaulting to
        false) declaring whether rooms must still be honored on blackout dates."

        Design: Corner/endpoints/award_requires_all_contract_terms_fields
        """
        station = make_station(code="CWA")
        vendor = make_vendor(name="Rib Mountain Inn",
                             contact_email="ops@ribmountain.example")
        cycle, proposal = make_negotiation_cycle(station["id"], vendor)
        fresh = validate_success(api.get_rfp_cycle(cycle["id"], SOURCING))
        payload = create_award_payload(
            proposal_id=proposal["id"],
            expected_cycle_version=fresh["version"])
        del payload["quiet_room_standard"]
        resp = api.award_rfp_cycle(cycle["id"], payload, SOURCING)
        validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST)
        cycle_after = validate_success(api.get_rfp_cycle(cycle["id"], SOURCING))
        assert cycle_after["status"] == "NEGOTIATION"


class TestAwardStaleVersion:

    def test_award_stale_cycle_version_returns_412(self, api):
        """PRD §2.9: "Awarding an RFP cycle requires the request to carry
        `expected_cycle_version` holding the `version` of the cycle the client last
        observed; if another writer has advanced the cycle's version since that read
        — for example by a counter-offer or an open-negotiation call that rewrote
        proposal rates — the award is rejected with `ERR_STALE_VERSION` (HTTP 412),
        preventing the client from awarding a negotiation state it has not observed."

        Design: Corner/errors/award_stale_cycle_version_returns_412
        """
        station = make_station(code="RAP")
        vendor = make_vendor(name="Black Hills Inn",
                             contact_email="ops@blackhills.example")
        cycle, proposal = make_negotiation_cycle(station["id"], vendor)
        stale = validate_success(api.get_rfp_cycle(cycle["id"], SOURCING))
        # advance the cycle version twice: NEGOTIATION -> EVALUATION -> NEGOTIATION
        validate_success(api.open_negotiation(cycle["id"], SOURCING))
        validate_success(api.open_negotiation(cycle["id"], SOURCING))
        resp = api.award_rfp_cycle(cycle["id"], create_award_payload(
            proposal_id=proposal["id"],
            expected_cycle_version=stale["version"]), SOURCING)
        validate_error(resp, ApiErrorId.ERR_STALE_VERSION)
        cycle_after = validate_success(api.get_rfp_cycle(cycle["id"], SOURCING))
        assert cycle_after["status"] == "NEGOTIATION"

    def test_award_with_fresh_version_succeeds(self, api):
        """PRD §2.9: "Awarding an RFP cycle requires the request to carry
        `expected_cycle_version` holding the `version` of the cycle the client last
        observed; if another writer has advanced the cycle's version since that read
        — for example by a counter-offer or an open-negotiation call that rewrote
        proposal rates — the award is rejected with `ERR_STALE_VERSION` (HTTP 412),
        preventing the client from awarding a negotiation state it has not observed."
        PRD §3.2: "A successful award creates a **Contract** in `DRAFT` with the
        `rfp_cycle_id`, `proposal_id`, `vendor_id`, and `station_id` copied from the
        cycle and the accepted proposal, the `negotiated_rate_cents` taken from the
        proposal's `current_rate_cents`, and the award's terms stamped onto it."

        Design: Corner/errors/award_stale_cycle_version_returns_412
        """
        station = make_station(code="RAP")
        vendor = make_vendor(name="Black Hills Inn",
                             contact_email="ops@blackhills.example")
        cycle, proposal = make_negotiation_cycle(station["id"], vendor)
        contract = award_cycle(cycle, proposal, room_block_size=5)
        assert contract["status"] == "DRAFT"
        assert contract["rfp_cycle_id"] == cycle["id"]
        assert contract["proposal_id"] == proposal["id"]
        assert contract["vendor_id"] == vendor["id"]
        assert contract["station_id"] == station["id"]


class TestAwardCascade:

    def test_award_accepts_winner_rejects_losers(self, api):
        """PRD §3.2: "The awarded proposal moves `SHORTLISTED → ACCEPTED`; every other
        proposal of the cycle still in `SUBMITTED`, `UNDER_REVIEW`, or `SHORTLISTED`
        moves to `REJECTED`; the cycle itself moves `NEGOTIATION → AWARDED`; and all
        affected resources bump their `version`."

        Design: Difficulty/transitive_cascade/award_accepts_winner_rejects_losers_creates_contract
        """
        station = make_station(code="STL")
        vendor_w = make_vendor(name="Arch Hotel",
                               contact_email="ops@archhotel.example")
        vendor_y = make_vendor(name="Riverfront Inn",
                               contact_email="ops@riverfront.example")
        cycle = validate_success(api.create_rfp_cycle(
            {"station_id": station["id"], "title": "STL 2026 crew hotel",
             "response_deadline": "2026-11-10T00:00:00Z", "target_room_count": 10,
             "budget_cap_cents": 1000000}, SOURCING), expected_status=201)
        validate_success(api.open_rfp_cycle(cycle["id"], SOURCING))
        prop_w = validate_success(api.submit_proposal(
            cycle["id"], create_proposal_payload(
                vendor_id=vendor_w["id"], offered_room_count=10,
                offered_rate_cents=10500, quiet_room_commitment=10),
            make_vendor_rep_headers(vendor_w["id"])), expected_status=201)
        prop_y = validate_success(api.submit_proposal(
            cycle["id"], create_proposal_payload(
                vendor_id=vendor_y["id"], offered_room_count=10,
                offered_rate_cents=11000, quiet_room_commitment=10),
            make_vendor_rep_headers(vendor_y["id"])), expected_status=201)
        validate_success(api.close_rfp_cycle(cycle["id"], SOURCING))
        validate_success(api.shortlist_proposal(prop_w["id"], SOURCING))
        validate_success(api.shortlist_proposal(prop_y["id"], SOURCING))
        validate_success(api.open_negotiation(cycle["id"], SOURCING))
        validate_success(api.counter_offer_proposal(
            prop_w["id"], {"new_rate_cents": 9000}, SOURCING))
        contract = award_cycle(cycle, prop_w, room_block_size=10)
        fresh_cycle = validate_success(api.get_rfp_cycle(cycle["id"], SOURCING))
        assert fresh_cycle["status"] == "AWARDED"
        fresh_w = validate_success(api.get_proposal(prop_w["id"], SOURCING))
        fresh_y = validate_success(api.get_proposal(prop_y["id"], SOURCING))
        assert fresh_w["status"] == "ACCEPTED"
        assert fresh_y["status"] == "REJECTED"
        assert contract["status"] == "DRAFT"

    def test_award_contract_uses_counter_offered_rate_and_total_value(self, api):
        """PRD §3.2: "A successful award creates a **Contract** in `DRAFT` with the
        `rfp_cycle_id`, `proposal_id`, `vendor_id`, and `station_id` copied from the
        cycle and the accepted proposal, the `negotiated_rate_cents` taken from the
        proposal's `current_rate_cents`, and the award's terms stamped onto it."
        PRD §3.2: "The contract's `total_contract_value_cents` is computed at
        creation with exactly the same formula as the award's budget gate — rate
        times block times whole nights, rounded half-up once at the end — and this
        stored figure is the system of record for downstream budget reporting."

        Design: Difficulty/transitive_cascade/award_accepts_winner_rejects_losers_creates_contract
        """
        station = make_station(code="STL")
        vendor = make_vendor(name="Arch Hotel",
                             contact_email="ops@archhotel.example")
        cycle, proposal = make_negotiation_cycle(
            station["id"], vendor, rate_cents=10500, rooms=10,
            budget_cap_cents=2_000_000)
        validate_success(api.counter_offer_proposal(
            proposal["id"], {"new_rate_cents": 9000}, SOURCING))
        contract = award_cycle(cycle, proposal, room_block_size=10)
        assert contract["negotiated_rate_cents"] == 9000
        # 9000 x 10 rooms x 10 nights = 900000
        assert contract["total_contract_value_cents"] == 900000


class TestCounterOfferGate:

    def test_counter_offer_outside_negotiation_rejected(self, api):
        """PRD §3.2: "A counter-offer is legal only when the proposal is `SHORTLISTED`
        and its parent cycle is in `NEGOTIATION`; any other combination is rejected
        with `ERR_NOT_NEGOTIABLE` (HTTP 409)."

        Design: Corner/validations/counter_offer_outside_negotiation_rejected
        """
        station = make_station(code="PUB")
        vendor = make_vendor(name="Steel City Inn",
                             contact_email="ops@steelcity.example")
        cycle, proposal = make_open_cycle_with_proposal(station["id"], vendor)
        validate_success(api.close_rfp_cycle(cycle["id"], SOURCING))
        validate_success(api.shortlist_proposal(proposal["id"], SOURCING))
        # cycle is EVALUATION, not NEGOTIATION
        resp = api.counter_offer_proposal(
            proposal["id"], {"new_rate_cents": 8500}, SOURCING)
        validate_error(resp, ApiErrorId.ERR_NOT_NEGOTIABLE)
        fresh = validate_success(api.get_proposal(proposal["id"], SOURCING))
        assert fresh["current_rate_cents"] == 9000


class TestRbacCycles:

    def test_crewops_cannot_open_rfp_cycle(self, api):
        """PRD §2.1: "A request whose role is recognized but not permitted for the
        targeted endpoint is rejected with `ERR_FORBIDDEN` (HTTP 403); this same
        rejection covers entity-backed ownership failures, such as a
        `HotelVendorRep` attempting to withdraw a proposal that belongs to another
        vendor."

        Design: Corner/rbac/crewops_cannot_open_rfp_cycle
        """
        station = make_station(code="MSN")
        cycle = validate_success(api.create_rfp_cycle(
            {"station_id": station["id"], "title": "MSN 2026 crew hotel",
             "response_deadline": "2026-11-10T00:00:00Z", "target_room_count": 5,
             "budget_cap_cents": 1000000}, SOURCING), expected_status=201)
        resp = api.open_rfp_cycle(cycle["id"], CREWOPS)
        validate_error(resp, ApiErrorId.ERR_FORBIDDEN)
        fresh = validate_success(api.get_rfp_cycle(cycle["id"], SOURCING))
        assert fresh["status"] == "DRAFT"
