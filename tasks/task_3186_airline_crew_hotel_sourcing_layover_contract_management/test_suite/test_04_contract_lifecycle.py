"""Contract lifecycle: activation gates, expiry, termination thresholds,
suspension cascade, remediation."""
import pytest

from test_helpers import (
    validate_success, validate_error,
    ApiErrorId,
    make_station, make_union_agreement, make_vendor,
    make_station_and_union, make_active_contract, make_negotiation_cycle,
    award_cycle, make_layover, make_confirmed_booking,
    create_award_payload, create_crew_feedback_payload,
    setup_sourced_station,
)
from test_helpers.fixtures import ADMIN, SOURCING, CREWOPS, AUDITOR


class TestActivationVendorGate:

    def test_contract_activation_gated_by_vendor_status(self, api):
        """PRD §3.4: "Activation moves it `DRAFT → ACTIVE` and re-runs the union
        compliance gate described in §3.2 — quiet-room, blackout-protection, and
        room-standard ladder — plus a vendor gate: the contract's vendor must
        currently be `ACTIVE`, not `SUSPENDED` or `BLACKLISTED`, or activation is
        refused with `ERR_VENDOR_INACTIVE` (HTTP 422)."
        PRD §3.4: "Either way, termination cascades: every room allocation of the
        contract in `HELD` or `CONFIRMED` moves to `CANCELLED`; every layover
        requirement at the contract's station in `CONFIRMED` whose allocation was
        cancelled moves to `SURGED`; and the contract's vendor is moved to
        `SUSPENDED`."

        Design: Difficulty/cross_entity_state_dependency/contract_activation_gated_by_vendor_status
        """
        station, union = make_station_and_union("MCI", station_min_rest=10,
                                                transport=35)
        vendor = make_vendor(name="Heartland Hotels",
                             contact_email="ops@heartland.example")
        # K7: ACTIVE contract
        contract_k7 = make_active_contract(station, vendor, rate_cents=9000,
                                           room_block_size=10)
        # K8: awarded, still DRAFT
        cycle_b, prop_b = make_negotiation_cycle(
            station["id"], vendor, rate_cents=8800, rooms=5,
            budget_cap_cents=1_000_000, title="MCI 2026 crew hotel B")
        contract_k8 = award_cycle(cycle_b, prop_b, room_block_size=5)
        # three low-rated feedback rows on K7, then terminate -> vendor SUSPENDED
        layover = make_layover(station["id"], crew_count=4)
        for rating, category in [(1, "NOISE"), (2, "CLEANLINESS"), (1, "SECURITY")]:
            validate_success(api.create_crew_feedback(
                create_crew_feedback_payload(
                    contract_id=contract_k7["id"],
                    layover_requirement_id=layover["id"],
                    rating=rating, category=category), CREWOPS),
                expected_status=201)
        validate_success(api.terminate_contract(contract_k7["id"], SOURCING))
        vendor_after = validate_success(api.get_hotel_vendor(vendor["id"], SOURCING))
        assert vendor_after["status"] == "SUSPENDED"
        resp = api.activate_contract(contract_k8["id"], SOURCING)
        validate_error(resp, ApiErrorId.ERR_VENDOR_INACTIVE)
        k8_after = validate_success(api.get_contract(contract_k8["id"], SOURCING))
        assert k8_after["status"] == "DRAFT"

    def test_activation_succeeds_when_vendor_active(self, api):
        """PRD §3.4: "Activation moves it `DRAFT → ACTIVE` and re-runs the union
        compliance gate described in §3.2 — quiet-room, blackout-protection, and
        room-standard ladder — plus a vendor gate: the contract's vendor must
        currently be `ACTIVE`, not `SUSPENDED` or `BLACKLISTED`, or activation is
        refused with `ERR_VENDOR_INACTIVE` (HTTP 422)."

        Design: Difficulty/cross_entity_state_dependency/contract_activation_gated_by_vendor_status
        """
        station, union = make_station_and_union("MCI")
        vendor = make_vendor(name="Heartland Hotels",
                             contact_email="ops@heartland.example")
        cycle, proposal = make_negotiation_cycle(station["id"], vendor)
        contract = award_cycle(cycle, proposal)
        resp = api.activate_contract(contract["id"], SOURCING)
        data = validate_success(resp)
        assert data["status"] == "ACTIVE"


class TestContractExpiry:

    def test_contract_expire_lazy_settle_past_end_date(self, api):
        """PRD §3.4: "The first is time: the system evaluates expiry lazily, so any
        read or write touching a contract whose `end_date` the logical clock has
        passed settles it to `EXPIRED` before answering."

        Design: Corner/state_machines/contract_expire_lazy_settle_past_end_date
        """
        station, union, vendor, contract = setup_sourced_station(
            "GRI", end_date="2026-10-11T00:00:00Z")
        assert contract["status"] == "ACTIVE"
        api.set_clock("2026-10-12T00:00:00Z", ADMIN)
        data = validate_success(api.get_contract(contract["id"], SOURCING))
        assert data["status"] == "EXPIRED"


class TestTerminationThreshold:

    def test_terminate_active_without_three_strikes_rejected(self, api):
        """PRD §3.4: "Termination from `ACTIVE` is evidence-gated: the manager may
        terminate only when the contract has accumulated at least 3 crew feedback
        rows with a `rating` of 2 or lower — the three-strike rule — and an attempt
        short of that count is refused with `ERR_TERMINATION_THRESHOLD` (HTTP 422)."

        Design: Corner/validations/terminate_active_without_three_strikes_rejected
        """
        station, union, vendor, contract = setup_sourced_station("GSP")
        layover = make_layover(station["id"])
        for rating, category in [(2, "NOISE"), (1, "CLEANLINESS")]:
            validate_success(api.create_crew_feedback(
                create_crew_feedback_payload(
                    contract_id=contract["id"],
                    layover_requirement_id=layover["id"],
                    rating=rating, category=category), CREWOPS),
                expected_status=201)
        resp = api.terminate_contract(contract["id"], SOURCING)
        validate_error(resp, ApiErrorId.ERR_TERMINATION_THRESHOLD)
        fresh = validate_success(api.get_contract(contract["id"], SOURCING))
        assert fresh["status"] == "ACTIVE"

    def test_termination_cascade_end_to_end(self, api):
        """PRD §3.4: "Either way, termination cascades: every room allocation of the
        contract in `HELD` or `CONFIRMED` moves to `CANCELLED`; every layover
        requirement at the contract's station in `CONFIRMED` whose allocation was
        cancelled moves to `SURGED`; and the contract's vendor is moved to
        `SUSPENDED`."

        Design: Corner/cross_cutting_layers/cascade_side_effects_full_chain_end_to_end
        """
        station, union, vendor, contract = setup_sourced_station(
            "ALS", crew_type="FLIGHT_ATTENDANT", union_min_rest=8,
            station_min_rest=8, transport=20)
        layover, allocation = make_confirmed_booking(
            station, contract, stay_date="2026-10-02T00:00:00Z",
            crew_type="FLIGHT_ATTENDANT", crew_count=3)
        for rating, category in [(1, "NOISE"), (2, "SECURITY"), (1, "CLEANLINESS")]:
            validate_success(api.create_crew_feedback(
                create_crew_feedback_payload(
                    contract_id=contract["id"],
                    layover_requirement_id=layover["id"],
                    crew_type="FLIGHT_ATTENDANT",
                    rating=rating, category=category), CREWOPS),
                expected_status=201)
        validate_success(api.terminate_contract(contract["id"], SOURCING))
        fresh_contract = validate_success(api.get_contract(contract["id"], SOURCING))
        assert fresh_contract["status"] == "TERMINATED"
        fresh_alloc = validate_success(api.get_allocation(allocation["id"], CREWOPS))
        assert fresh_alloc["status"] == "CANCELLED"
        fresh_layover = validate_success(
            api.get_layover_requirement(layover["id"], CREWOPS))
        assert fresh_layover["status"] == "SURGED"
        fresh_vendor = validate_success(api.get_hotel_vendor(vendor["id"], SOURCING))
        assert fresh_vendor["status"] == "SUSPENDED"


class TestSuspensionCascade:

    def test_critical_audit_suspends_contract_releases_allocation_surges_layover(self, api):
        """PRD §3.8: "Opening a `CRITICAL` audit against an `ACTIVE` contract
        immediately suspends the contract (`ACTIVE → SUSPENDED`) and fires the full
        suspension cascade: the contract's `remediation_deadline` is set to the
        logical clock plus 168 hours — one week; every allocation of the contract in
        `HELD` moves to `RELEASED`; every transport trip referencing the contract in
        `SCHEDULED` moves to `CANCELLED`; and every layover at the contract's station
        in `CONFIRMED` whose held allocation was just released moves to `SURGED`."

        Design: Difficulty/transitive_cascade/critical_audit_suspends_contract_releases_allocation_surges_layover
        """
        station, union, vendor, contract = setup_sourced_station(
            "ABQ", station_min_rest=8, transport=25, union_min_rest=8,
            rate_cents=9500, room_block_size=10)
        layover, allocation = make_confirmed_booking(
            station, contract, stay_date="2026-10-05T00:00:00Z", crew_count=3,
            arrival="2026-10-05T18:00:00Z", departure="2026-10-06T09:00:00Z",
            confirm=False)
        trip = validate_success(api.create_transport_trip(
            layover["id"], {"direction": "AIRPORT_TO_HOTEL", "vehicle_capacity": 8},
            CREWOPS), expected_status=201)
        validate_success(api.create_audit({
            "contract_id": contract["id"], "auditor_id": "aud-77",
            "severity": "CRITICAL",
            "findings": "external doors propped open; floor keycard reader disabled",
        }, AUDITOR), expected_status=201)
        fresh_contract = validate_success(api.get_contract(contract["id"], SOURCING))
        assert fresh_contract["status"] == "SUSPENDED"
        assert fresh_contract["remediation_deadline"] is not None
        fresh_alloc = validate_success(api.get_allocation(allocation["id"], CREWOPS))
        assert fresh_alloc["status"] == "RELEASED"
        fresh_layover = validate_success(
            api.get_layover_requirement(layover["id"], CREWOPS))
        assert fresh_layover["status"] == "SURGED"
        fresh_trip = validate_success(api.get_transport_trip(trip["id"], CREWOPS))
        assert fresh_trip["status"] == "CANCELLED"

    def test_distressed_book_legal_after_suspension_cascade(self, api):
        """PRD §3.7: "A layover in `SURGED` — whether it got there by release or by
        the contract cascades of §3.8 — needs rooms beyond the contracted block. Crew
        operations re-houses it with a distressed booking that names a `vendor_id`
        (which must reference a vendor currently `ACTIVE`, or the request is refused
        with `ERR_VENDOR_INACTIVE`) and a `rate_cents`."

        Design: Difficulty/transitive_cascade/critical_audit_suspends_contract_releases_allocation_surges_layover
        """
        station, union, vendor, contract = setup_sourced_station(
            "ABQ", station_min_rest=8, transport=25, union_min_rest=8,
            rate_cents=9500, room_block_size=10)
        layover, allocation = make_confirmed_booking(
            station, contract, stay_date="2026-10-05T00:00:00Z", crew_count=3,
            arrival="2026-10-05T18:00:00Z", departure="2026-10-06T09:00:00Z",
            confirm=False)
        validate_success(api.create_audit({
            "contract_id": contract["id"], "auditor_id": "aud-77",
            "severity": "CRITICAL", "findings": "no night security",
        }, AUDITOR), expected_status=201)
        # the layover is now SURGED, so distressed-book is legal
        distressed = make_vendor(name="Relief Rooms",
                                 contact_email="ops@relief.example")
        resp = api.distressed_book_layover(
            layover["id"], {"vendor_id": distressed["id"], "rate_cents": 12000},
            CREWOPS)
        data = validate_success(resp, expected_status=201)
        assert data["kind"] == "DISTRESSED"
        assert data["status"] == "HELD"


class TestRemediation:

    def test_remediate_blocked_while_critical_audit_open(self, api):
        """PRD §3.8: "A suspended contract can recover: remediation moves it
        `SUSPENDED → ACTIVE`, but only when no audit against the contract remains in
        `OPEN` or `IN_PROGRESS` with severity `CRITICAL`; success clears the
        `remediation_deadline` back to null."

        Design: Corner/state_machines/remediate_blocked_while_critical_audit_open
        """
        station, union, vendor, contract = setup_sourced_station("IDA")
        audit = validate_success(api.create_audit({
            "contract_id": contract["id"], "auditor_id": "aud-3",
            "severity": "CRITICAL", "findings": "no night security",
        }, AUDITOR), expected_status=201)
        resp = api.remediate_contract(contract["id"], SOURCING)
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE)
        validate_success(api.start_audit(audit["id"], AUDITOR))
        validate_success(api.close_audit(audit["id"], {"outcome": "PASS"}, AUDITOR))
        data = validate_success(api.remediate_contract(contract["id"], SOURCING))
        assert data["status"] == "ACTIVE"
        assert data["remediation_deadline"] is None


class TestAuditCloseFail:

    def test_audit_close_fail_terminates_contract(self, api):
        """PRD §3.8: "Closing with a fail outcome terminates the contract outright,
        regardless of whether it stood `ACTIVE` or `SUSPENDED`, and fires the full
        termination cascade of §3.4 — allocations cancelled, their layovers surged,
        vendor suspended."

        Design: Corner/state_machines/audit_close_fail_terminates_contract
        """
        station, union, vendor, contract = setup_sourced_station("HOB")
        audit = validate_success(api.create_audit({
            "contract_id": contract["id"], "auditor_id": "aud-9",
            "severity": "MINOR", "findings": "worn hallway carpet",
        }, AUDITOR), expected_status=201)
        validate_success(api.start_audit(audit["id"], AUDITOR))
        data = validate_success(api.close_audit(
            audit["id"], {"outcome": "FAIL"}, AUDITOR))
        assert data["status"] == "CLOSED_FAIL"
        fresh_contract = validate_success(api.get_contract(contract["id"], SOURCING))
        assert fresh_contract["status"] == "TERMINATED"
        fresh_vendor = validate_success(api.get_hotel_vendor(vendor["id"], SOURCING))
        assert fresh_vendor["status"] == "SUSPENDED"
