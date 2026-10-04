"""Reciprocal switching petitions and interchange slot capacity (PRD §3.8)."""
from test_helpers import (
    ApiErrorId,
    NON_EXISTENT_ID,
    SHIPPER_GAL,
    SHIPPER_OTH,
    api_client,
    create_petition_payload,
    escalate,
    file_petition,
    file_service_complaint,
    get_petition_data,
    grant_petition,
    make_shipper_headers,
    register_carrier,
    set_clock,
    setup_escalated_service_complaint,
    validate_error,
    validate_paginated,
    validate_success,
)
from test_helpers import TEST_USERS

BOARD = TEST_USERS["board_adjudicator_headers"]
WINDOW = {"service_start_date": "2026-10-01", "service_end_date": "2026-12-01"}


class TestPetitionGrantGates:
    def test_petition_grant_gated_on_escalated_evidence(self):
        """PRD §3.8: "The evidence complaint must be in `ESCALATED` status at
        decide time — existence was validated at creation, but eligibility is
        re-validated now, and a complaint that was resolved in the meantime
        fails with `ERR_PETITION_EVIDENCE_NOT_ESCALATED` (HTTP 409)."

        Design: Difficulty/cross_entity_state_dependency/petition_grant_gated_on_escalated_evidence
        """
        carrier = register_carrier(
            carrier_code="CSXT", legal_name="Crescent South Extension Transport",
            carrier_class="I", base_route_miles=2100)
        sc = file_service_complaint(carrier["id"])  # stays OPEN
        petition = file_petition(
            SHIPPER_GAL, carrier["id"], sc["id"], facility_distance_miles=12)

        resp = api_client.decide_petition(
            petition["id"], {"outcome": "GRANTED"}, BOARD)
        validate_error(resp, ApiErrorId.ERR_PETITION_EVIDENCE_NOT_ESCALATED)
        assert (get_petition_data(carrier["id"], petition["id"])["status"]
                == "FILED")

        escalate(sc["id"], directive="Directing CSXT to restore service within 72 hours")
        granted = grant_petition(petition["id"])
        assert granted["status"] == "GRANTED"

    def test_referential_mismatch_beats_temporal_staleness(self):
        """PRD §3.8: "Grant is gated by four further checks, evaluated in the
        precedence order of §2.6 — carrier alignment first, then evidence
        freshness, then escalation, then capacity:"
        PRD §3.8: "The evidence service complaint's carrier must be the
        petition's `incumbent_carrier_id`, failing which
        `ERR_SERVICE_COMPLAINT_CARRIER_MISMATCH` (HTTP 422)."

        Design: Difficulty/priority_pair_validation_conflict/referential_mismatch_beats_temporal_staleness
        """
        set_clock("2026-09-01T00:00:00Z")
        incumbent = register_carrier(
            carrier_code="CSXT", legal_name="Crescent South Extension Transport",
            carrier_class="I", base_route_miles=2100)
        other = register_carrier(
            carrier_code="BNRZ", legal_name="Big Northern Railroad",
            carrier_class="I", base_route_miles=800)
        # Evidence complaint against the OTHER carrier, created 2026-09-01.
        sc = file_service_complaint(other["id"], territory_code="LAKES")
        # 91 days later the petition names CSXT as incumbent citing that SC.
        set_clock("2026-12-01T00:00:00Z")
        petition = file_petition(
            SHIPPER_GAL, incumbent["id"], sc["id"], facility_distance_miles=12,
            service_start_date="2027-01-01", service_end_date="2027-03-01")

        resp = api_client.decide_petition(
            petition["id"], {"outcome": "GRANTED"}, BOARD)
        # Carrier mismatch (priority 13) beats the 91 > 84 day staleness (14).
        validate_error(resp, ApiErrorId.ERR_SERVICE_COMPLAINT_CARRIER_MISMATCH)
        assert (get_petition_data(incumbent["id"], petition["id"])["status"]
                == "FILED")

    def test_stale_evidence_window_rejected(self):
        """PRD §3.8: "The evidence complaint must have been created no more
        than 84 days before the petition — that is, the difference between the
        petition's `created_at` and the evidence complaint's `created_at` may
        not exceed 84 days. An older complaint fails with
        `ERR_SERVICE_FAILURE_WINDOW_EXPIRED` (HTTP 422); a difference of
        exactly 84 days is still within the window."

        Design: Corner/errors/stale_evidence_window_rejected
        """
        set_clock("2026-09-01T00:00:00Z")
        carrier = register_carrier(
            carrier_code="CSXT", legal_name="Crescent South Extension Transport",
            carrier_class="I", base_route_miles=2100)
        sc, _eso = setup_escalated_service_complaint(carrier["id"])

        # Exactly 84 days after the complaint's creation: still fresh.
        set_clock("2026-11-24T00:00:00Z")
        p_fresh = file_petition(
            "shp-s2", carrier["id"], sc["id"],
            service_start_date="2027-01-01", service_end_date="2027-03-01")
        # 85 days after: stale.
        set_clock("2026-11-25T00:00:00Z")
        p_stale = file_petition(
            "shp-s1", carrier["id"], sc["id"],
            service_start_date="2027-01-01", service_end_date="2027-03-01")

        resp = api_client.decide_petition(
            p_stale["id"], {"outcome": "GRANTED"}, BOARD)
        validate_error(resp, ApiErrorId.ERR_SERVICE_FAILURE_WINDOW_EXPIRED)
        assert (get_petition_data(carrier["id"], p_stale["id"])["status"]
                == "FILED")

        granted = grant_petition(p_fresh["id"])
        assert granted["status"] == "GRANTED"


class TestInterchangeCapacity:
    def test_interchange_slots_half_open_adjacency(self):
        """PRD §3.8: "Each interchange accommodates at most four overlapping
        granted switching windows."
        PRD §3.8: "the number of already-`GRANTED` petitions whose windows
        overlap the requested window under half-open semantics — the window
        runs from `service_start_date` inclusive to `service_end_date`
        exclusive, so two windows that merely touch, one ending on the day
        another begins, do not overlap — must be fewer than 4."

        Design: Difficulty/resource_temporal_overlap/interchange_slots_half_open_adjacency
        """
        carrier = register_carrier(
            carrier_code="CSXT", legal_name="Crescent South Extension Transport",
            carrier_class="I", base_route_miles=2100)
        sc, _eso = setup_escalated_service_complaint(carrier["id"])
        petitions = [
            file_petition(f"shp-s{i}", carrier["id"], sc["id"],
                          facility_distance_miles=7 + i, **WINDOW)
            for i in range(1, 6)
        ]
        p_adjacent = file_petition(
            "shp-s6", carrier["id"], sc["id"], facility_distance_miles=12,
            service_start_date="2026-12-01", service_end_date="2027-02-01")
        for p in petitions[:4]:
            assert grant_petition(p["id"])["status"] == "GRANTED"

        # Fifth overlapping grant would exceed the four-slot capacity.
        resp = api_client.decide_petition(
            petitions[4]["id"], {"outcome": "GRANTED"}, BOARD)
        validate_error(resp, ApiErrorId.ERR_INTERCHANGE_CAPACITY_EXCEEDED)
        assert (get_petition_data(carrier["id"], petitions[4]["id"])["status"]
                == "FILED")

        # Adjacency consumes no overlapping slot under half-open semantics.
        granted = grant_petition(p_adjacent["id"])
        assert granted["status"] == "GRANTED"

    def test_interchange_slot_conservation_grant_terminate(self):
        """PRD §3.8: "A successful grant moves the petition to `GRANTED` and
        consumes one switching slot on the `interchange_code` for the
        requested window."
        PRD §3.8: "the Board may terminate a granted petition — one in any
        other state rejects termination with `ERR_PETITION_NOT_GRANTED`
        (HTTP 409) — moving it to `TERMINATED`, a terminal state, and
        releasing the consumed slot as the compensating action for the grant."

        Design: Difficulty/compensating_invariant/interchange_slot_conservation_grant_terminate
        """
        carrier = register_carrier(
            carrier_code="CSXT", legal_name="Crescent South Extension Transport",
            carrier_class="I", base_route_miles=2100)
        sc, _eso = setup_escalated_service_complaint(carrier["id"])
        petitions = [
            file_petition(f"shp-s{i}", carrier["id"], sc["id"],
                          facility_distance_miles=7 + i, **WINDOW)
            for i in range(1, 6)
        ]
        for p in petitions[:4]:
            grant_petition(p["id"])
        resp = api_client.decide_petition(
            petitions[4]["id"], {"outcome": "GRANTED"}, BOARD)
        validate_error(resp, ApiErrorId.ERR_INTERCHANGE_CAPACITY_EXCEEDED)

        terminated = validate_success(api_client.terminate_petition(
            petitions[1]["id"], {}, BOARD))
        assert terminated["status"] == "TERMINATED"

        granted = grant_petition(petitions[4]["id"])
        assert granted["status"] == "GRANTED"
        _data, meta = validate_paginated(api_client.list_carrier_petitions(
            carrier["id"], BOARD, params={"status": "GRANTED"}))
        assert meta["total_count"] == 4


class TestPetitionCreationGuards:
    def test_facility_distance_boundary_30_ok_31_rejected(self):
        """PRD §3.8: "the facility must lie within 30 miles of the
        interchange, a greater `facility_distance_miles` being rejected with
        `ERR_FACILITY_BEYOND_INTERCHANGE_DISTANCE` (HTTP 422)" at creation.

        Design: Corner/validations/facility_distance_boundary_30_ok_31_rejected
        """
        carrier = register_carrier(
            carrier_code="CSXT", legal_name="Crescent South Extension Transport",
            carrier_class="I", base_route_miles=2100)
        sc = file_service_complaint(carrier["id"])
        at_limit = file_petition(
            SHIPPER_GAL, carrier["id"], sc["id"], facility_distance_miles=30)
        assert at_limit["status"] == "FILED"

        resp = api_client.create_petition(
            create_petition_payload(
                shipper_id=SHIPPER_OTH, incumbent_carrier_id=carrier["id"],
                evidence_service_complaint_id=sc["id"],
                facility_distance_miles=31),
            make_shipper_headers(SHIPPER_OTH))
        validate_error(resp, ApiErrorId.ERR_FACILITY_BEYOND_INTERCHANGE_DISTANCE)

    def test_petition_window_end_not_after_start_rejected(self):
        """PRD §3.8: "the window must be non-empty, a `service_end_date` not
        strictly later than `service_start_date` being `ERR_INVALID_REQUEST`
        (HTTP 400)."

        Design: Corner/validations/petition_window_end_not_after_start_rejected
        """
        carrier = register_carrier(
            carrier_code="CSXT", legal_name="Crescent South Extension Transport",
            carrier_class="I", base_route_miles=2100)
        sc = file_service_complaint(carrier["id"])
        resp = api_client.create_petition(
            create_petition_payload(
                shipper_id=SHIPPER_GAL, incumbent_carrier_id=carrier["id"],
                evidence_service_complaint_id=sc["id"],
                service_start_date="2026-10-01", service_end_date="2026-10-01"),
            make_shipper_headers(SHIPPER_GAL))
        validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST)

    def test_duplicate_active_petition_rejected(self):
        """PRD §3.8: "at most one non-terminal petition — one in `FILED` or
        `GRANTED` status — may exist for the same `shipper_id` and
        `interchange_code`, a duplicate being rejected with
        `ERR_DUPLICATE_ACTIVE_PETITION` (HTTP 409)."

        Design: Corner/validations/duplicate_active_petition_rejected
        """
        carrier = register_carrier(
            carrier_code="CSXT", legal_name="Crescent South Extension Transport",
            carrier_class="I", base_route_miles=2100)
        sc = file_service_complaint(carrier["id"])
        p1 = file_petition(SHIPPER_GAL, carrier["id"], sc["id"])
        assert p1["status"] == "FILED"

        resp = api_client.create_petition(
            create_petition_payload(
                shipper_id=SHIPPER_GAL, incumbent_carrier_id=carrier["id"],
                evidence_service_complaint_id=sc["id"],
                facility_distance_miles=15,
                service_start_date="2027-01-01", service_end_date="2027-03-01"),
            make_shipper_headers(SHIPPER_GAL))
        validate_error(resp, ApiErrorId.ERR_DUPLICATE_ACTIVE_PETITION)

        denied = validate_success(api_client.decide_petition(
            p1["id"], {"outcome": "DENIED"}, BOARD))
        assert denied["status"] == "DENIED"
        p2 = file_petition(
            SHIPPER_GAL, carrier["id"], sc["id"], facility_distance_miles=15,
            service_start_date="2027-01-01", service_end_date="2027-03-01")
        assert p2["status"] == "FILED"

    def test_petition_terminate_not_found_returns_404(self):
        """PRD §2.6: "a missing petition `ERR_PETITION_NOT_FOUND`" (HTTP 404,
        path existence check)."

        Design: Corner/entities/petition_terminate_not_found_returns_404
        """
        resp = api_client.terminate_petition(NON_EXISTENT_ID, {}, BOARD)
        validate_error(resp, ApiErrorId.ERR_PETITION_NOT_FOUND)
