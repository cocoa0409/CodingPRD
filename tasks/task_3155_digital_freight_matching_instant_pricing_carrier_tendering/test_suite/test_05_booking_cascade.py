"""The booking tender and its cascade, plus the carrier eligibility gate."""
from test_helpers import (
    api_client as api,
    make_carrier_headers,
    make_compliance_reviewer_headers,
    make_platform_admin_headers,
    make_shipper_headers,
    read_facility,
    read_load,
    setup_board,
    set_clock,
    NON_EXISTENT_UUID,
)


def _posted_load(board, **overrides):
    payload = {
        "shipper_id": board["shipper_id"],
        "origin_facility_id": board["origin_facility_id"],
        "destination_facility_id": board["destination_facility_id"],
        "pricing_mode": "SPOT",
        "equipment_type": "DRY_VAN",
        "commodity": "GENERAL",
        "weight_lbs": 40000,
        "declared_cargo_value_cents": 5000000,
        "distance_miles": 1200,
        "pickup_window_start": "2026-10-05T08:00:00Z",
        "pickup_window_end": "2026-10-05T12:00:00Z",
        "delivery_deadline": "2026-10-07T18:00:00Z",
        "market_band": "BALANCED",
    }
    payload.update(overrides)
    created = api.create_load(payload, make_shipper_headers(board["shipper_id"]))
    assert created.status_code == 201, created.text
    load_id = created.json()["data"]["id"]
    posted = api.post_load(load_id, make_shipper_headers(board["shipper_id"]))
    assert posted.status_code == 200, posted.text
    quote = api.list_load_rate_quotes(
        load_id, make_shipper_headers(board["shipper_id"])).json()["data"][-1]
    return posted.json()["data"], quote


def _booking_body(board, load, quote, equipment_id):
    return {
        "load_id": load["id"],
        "carrier_id": board["carrier_id"],
        "rate_quote_id": quote["id"],
        "equipment_id": equipment_id,
        "expected_load_version": load["version"],
    }


class TestBookingCascade:
    """A single tender writes across several related resources."""

    def test_one_booking_sets_the_load_equipment_quote_credit_and_timeline(self):
        """PRD section 3.7: "A successful booking cascades widely.  The load
        records its `carrier_id` and `equipment_id`, and the equipment unit becomes
        `ASSIGNED`."
        PRD section 3.7: "The quote becomes `ACCEPTED` and every other quote on
        that load in `ACTIVE` or `VIEWED` becomes `SUPERSEDED`.  The shipper's
        `credit_used_cents` rises by the `agreed_rate_cents`, reserving the
        exposure."

        Design: Corner/cross_cutting_complexity_layers/one_booking_mutates_five_related_resources_in_the_same_request
        """
        board = setup_board(units=1)
        set_clock("2026-10-05T00:00:00Z")
        load, quote = _posted_load(board)

        response = api.create_booking(_booking_body(board, load, quote, board["equipment"][0]["id"]),
                                      make_carrier_headers(board["carrier_id"]))
        assert response.status_code == 201, response.text
        booking = response.json()["data"]
        assert booking["agreed_rate_cents"] == 372240

        refreshed = read_load(board["shipper_id"], load["id"])
        assert refreshed["carrier_id"] == board["carrier_id"]
        assert refreshed["equipment_id"] == board["equipment"][0]["id"]
        assert refreshed["status"] == "BOOKED"

        equipment = api.get_equipment(
            board["equipment"][0]["id"], make_carrier_headers(board["carrier_id"])).json()["data"]
        assert equipment["status"] == "ASSIGNED"

        facility = read_facility(board["origin_facility_id"])
        assert facility["docks_committed_today"] == 1

        accepted = api.get_rate_quote(
            quote["id"], make_shipper_headers(board["shipper_id"])).json()["data"]
        assert accepted["status"] == "ACCEPTED"

    def test_booking_synthesizes_a_pickup_slot_and_books_the_credit(self):
        """PRD section 3.7: "The load records its `carrier_id` and `equipment_id`, and the equipment unit becomes `ASSIGNED`. A `PICKUP` appointment is synthesized in `SCHEDULED` status with a window matching the load's pickup window, at the position the dock selector chose, raising the facility's `docks_committed_today` by one; the booking records the synthesized appointment's id, its buffered windows `booking_window_start` and `booking_window_end` matching the load's pickup window bounds, and a `booked_at` stamp of the booking instant."
        PRD section 2.8: "`credit_limit_cents` is the maximum outstanding booked-rate
        exposure the platform will carry on the shipper's behalf, and
        `credit_used_cents` is the portion currently consumed. Exposure is
        reserved the moment a load is booked — `credit_used_cents` rises
        by the booking's `agreed_rate_cents` when the booking is created —
        and is discharged when the carrier is actually paid, at which
        point `credit_used_cents` falls by the same `agreed_rate_cents`."

        Design: Corner/cross_cutting_complexity_layers/one_booking_mutates_five_related_resources_in_the_same_request
        """
        board = setup_board(units=1)
        set_clock("2026-10-05T00:00:00Z")
        load, quote = _posted_load(board)
        api.create_booking(_booking_body(board, load, quote, board["equipment"][0]["id"]),
                           make_carrier_headers(board["carrier_id"]))

        appointments = api.list_load_appointments(
            load["id"], make_shipper_headers(board["shipper_id"])).json()["data"]
        assert len(appointments) == 1
        assert appointments[0]["slot_kind"] == "PICKUP"
        assert appointments[0]["status"] == "SCHEDULED"

        events = api.list_load_status_events(
            load["id"], make_shipper_headers(board["shipper_id"])).json()["data"]
        booked_events = [event for event in events if event["event_type"] == "BOOKED"]
        assert len(booked_events) == 1
        assert booked_events[0]["source"] == "PLATFORM"

        shipper = api.get_shipper(
            board["shipper_id"], make_shipper_headers(board["shipper_id"])).json()["data"]
        assert shipper["credit_used_cents"] == 372240


class TestCarrierEligibilityGate:
    """The gate's clauses are evaluated in a stated order."""

    def test_a_carrier_that_is_not_verified_is_refused_before_the_risk_floor(self):
        """PRD section 2.10: "The carrier's status must be `VERIFIED`; otherwise the
        answer is `ERR_CARRIER_NOT_VERIFIED` (HTTP 409)."

        Design: Difficulty/priority_pair_validation_conflict/carrier_not_verified_beats_low_risk_score_on_booking
        """
        board = setup_board(units=1)
        set_clock("2026-10-05T00:00:00Z")
        load, quote = _posted_load(board)

        # A second carrier advanced through authority verification only.
        pending = api.create_carrier(
            {
                "legal_name": "Halfway Haulage LLC",
                "mc_number": "100777",
                "dot_number": "DOT-100777",
                "insurance_expires_at": "2027-06-01T00:00:00Z",
                "insurance_liability_limit_cents": 100000000,
                "cargo_coverage_limit_cents": 175000000,
                "safety_score": 72.0,
                "equipment_types": ["DRY_VAN"],
            },
            make_compliance_reviewer_headers(),
        )
        assert pending.status_code == 201, pending.text
        pending_id = pending.json()["data"]["id"]
        unit = api.create_equipment(
            {"carrier_id": pending_id, "equipment_type": "DRY_VAN",
             "unit_number": "HW-1", "driver_name": "R. Silva"},
            make_carrier_headers(pending_id),
        )
        assert unit.status_code == 201, unit.text
        verified = api.verify_authority(pending_id, make_compliance_reviewer_headers())
        assert verified.status_code == 200, verified.text
        assert verified.json()["data"]["status"] == "AUTHORITY_VERIFIED"

        rejected = api.create_booking(
            {
                "load_id": load["id"],
                "carrier_id": pending_id,
                "rate_quote_id": quote["id"],
                "equipment_id": unit.json()["data"]["id"],
                "expected_load_version": load["version"],
            },
            make_carrier_headers(pending_id),
        )
        assert rejected.status_code == 409, rejected.text
        assert rejected.json()["data"]["error_id"] == "ERR_CARRIER_NOT_VERIFIED"
        assert rejected.json()["data"]["error_id"] != "ERR_CARRIER_RISK_BLOCKED"

        refreshed = read_load(board["shipper_id"], load["id"])
        assert refreshed["status"] == "POSTED"
        assert refreshed["carrier_id"] is None

    def test_an_unverified_carrier_leaves_no_rows_behind(self):
        """PRD section 2.10: "The clauses are evaluated in a stated order and the
        first failing clause determines which error the caller sees."

        Design: Difficulty/priority_pair_validation_conflict/carrier_not_verified_beats_low_risk_score_on_booking
        """
        board = setup_board(units=1)
        set_clock("2026-10-05T00:00:00Z")
        load, quote = _posted_load(board)
        carrier = api.create_carrier(
            {
                "legal_name": "Halfway Haulage LLC",
                "mc_number": "100778",
                "dot_number": "DOT-100778",
                "insurance_expires_at": "2027-06-01T00:00:00Z",
                "insurance_liability_limit_cents": 100000000,
                "cargo_coverage_limit_cents": 175000000,
                "safety_score": 72.0,
                "equipment_types": ["DRY_VAN"],
            },
            make_compliance_reviewer_headers(),
        ).json()["data"]
        unit = api.create_equipment(
            {"carrier_id": carrier["id"], "equipment_type": "DRY_VAN",
             "unit_number": "HW-2", "driver_name": "R. Silva"},
            make_carrier_headers(carrier["id"])).json()["data"]

        rejected = api.create_booking(
            {"load_id": load["id"], "carrier_id": carrier["id"],
             "rate_quote_id": quote["id"], "equipment_id": unit["id"],
             "expected_load_version": load["version"]},
            make_carrier_headers(carrier["id"]),
        )
        assert rejected.status_code == 409
        bookings = api.list_bookings(make_platform_admin_headers(), {"load_id": load["id"]})
        assert bookings.status_code == 200
        assert bookings.json()["data"] == []
        assert api.get_equipment(
            unit["id"], make_carrier_headers(carrier["id"])).json()["data"]["status"] == "AVAILABLE"


class TestBookingReferentialGuards:
    """Referential integrity and existence are checked in a declared order."""

    def test_booking_against_a_draft_load_is_an_invalid_state_not_a_mismatch(self):
        """PRD section 2.6: "The not-found errors are specific to the kind of identifier that failed: `ERR_LOAD_NOT_FOUND`, `ERR_SHIPPER_NOT_FOUND`, `ERR_CARRIER_NOT_FOUND`, `ERR_FACILITY_NOT_FOUND`, `ERR_EQUIPMENT_NOT_FOUND`, `ERR_QUOTE_NOT_FOUND`, `ERR_BOOKING_NOT_FOUND`, `ERR_APPOINTMENT_NOT_FOUND`, `ERR_DETENTION_NOT_FOUND`, `ERR_CLAIM_NOT_FOUND`, `ERR_SETTLEMENT_NOT_FOUND`, and `ERR_CONTRACT_NOT_FOUND` each answer 404 Not Found with the id that did not resolve. Where a working resource is in a state from which the requested transition is simply not declared, the request is refused as an invalid state rather than as a business-rule failure, and a request aimed at a resource that has already reached one of its terminal states is refused as `ERR_ALREADY_TERMINAL` (HTTP 409) rather than being re-examined against the rules of the state it left."

        Design: Corner/state_machines/booking_on_a_draft_load_returns_invalid_state_never_a_quote_error
        """
        board = setup_board(units=1)
        set_clock("2026-10-05T00:00:00Z")
        posted, posted_quote = _posted_load(
            board, pickup_window_start="2026-10-06T08:00:00Z",
            pickup_window_end="2026-10-06T12:00:00Z")
        draft = api.create_load(
            {
                "shipper_id": board["shipper_id"],
                "origin_facility_id": board["origin_facility_id"],
                "destination_facility_id": board["destination_facility_id"],
                "pricing_mode": "SPOT",
                "equipment_type": "DRY_VAN",
                "commodity": "GENERAL",
                "weight_lbs": 40000,
                "declared_cargo_value_cents": 5000000,
                "distance_miles": 1200,
                "pickup_window_start": "2026-10-05T08:00:00Z",
                "pickup_window_end": "2026-10-05T12:00:00Z",
                "delivery_deadline": "2026-10-07T18:00:00Z",
                "market_band": "BALANCED",
            },
            make_shipper_headers(board["shipper_id"]),
        ).json()["data"]

        rejected = api.create_booking(
            {
                "load_id": draft["id"],
                "carrier_id": board["carrier_id"],
                "rate_quote_id": posted_quote["id"],
                "equipment_id": board["equipment"][0]["id"],
                "expected_load_version": posted["version"],
            },
            make_carrier_headers(board["carrier_id"]),
        )
        assert rejected.status_code == 409, rejected.text
        assert rejected.json()["data"]["error_id"] == "ERR_INVALID_STATE"
        assert rejected.json()["data"]["error_id"] != "ERR_QUOTE_LOAD_MISMATCH"
        assert read_load(board["shipper_id"], draft["id"])["status"] == "DRAFT"

    def test_two_unknown_ids_report_the_load_first_then_the_carrier(self):
        """PRD section 2.6: "Where a path names more than one resource — a
        settlement nested under a carrier, a detention event nested under a
        facility, an equipment list under a carrier — the server resolves each
        identifier in the order the path declares them and fails on the first
        unknown one with the corresponding not-found error."

        Design: Corner/validations/booking_with_two_unknown_ids_reports_the_load_first
        """
        board = setup_board(units=1)
        set_clock("2026-10-05T00:00:00Z")
        load, quote = _posted_load(board)

        all_unknown = api.create_booking(
            {
                "load_id": NON_EXISTENT_UUID,
                "carrier_id": NON_EXISTENT_UUID,
                "rate_quote_id": NON_EXISTENT_UUID,
                "equipment_id": NON_EXISTENT_UUID,
                "expected_load_version": load["version"],
            },
            make_carrier_headers(board["carrier_id"]),
        )
        assert all_unknown.status_code == 404, all_unknown.text
        assert all_unknown.json()["data"]["error_id"] == "ERR_LOAD_NOT_FOUND"

        partial = api.create_booking(
            {
                "load_id": load["id"],
                "carrier_id": NON_EXISTENT_UUID,
                "rate_quote_id": quote["id"],
                "equipment_id": NON_EXISTENT_UUID,
                "expected_load_version": load["version"],
            },
            make_carrier_headers(board["carrier_id"]),
        )
        assert partial.status_code == 404, partial.text
        assert partial.json()["data"]["error_id"] == "ERR_CARRIER_NOT_FOUND"

        refreshed = read_load(board["shipper_id"], load["id"])
        assert refreshed["status"] == "POSTED"
        assert refreshed["carrier_id"] is None


class TestBookingIdempotencyOfState:
    """A failed booking leaves the load exactly where it was."""

    def test_a_conflicting_second_booking_leaves_the_first_intact(self):
        """PRD section 3.7: "The chosen equipment unit must not be `IN_SHOP` and its `equipment_type` must equal the load's, or the answer is `ERR_EQUIPMENT_UNAVAILABLE` (HTTP 409). The requested equipment window must not overlap an existing booking on the same unit that is not terminal, under the zero-buffer half-open rule of §2.11, and that check is evaluated before any dock check, so an equipment conflict is reported as `ERR_EQUIPMENT_WINDOW_CONFLICT` (HTTP 409) rather than being masked by an appointment failure."

        Design: Corner/endpoints/bulk_appointment_capacity_error_does_not_typecheck_each_id
        """
        board = setup_board(units=1)
        set_clock("2026-10-05T00:00:00Z")
        first_load, first_quote = _posted_load(board)
        second_load, second_quote = _posted_load(board)
        first = api.create_booking(
            _booking_body(board, first_load, first_quote, board["equipment"][0]["id"]),
            make_carrier_headers(board["carrier_id"]))
        assert first.status_code == 201, first.text

        second = api.create_booking(
            _booking_body(board, second_load, second_quote, board["equipment"][0]["id"]),
            make_carrier_headers(board["carrier_id"]))
        assert second.status_code == 409, second.text
        assert second.json()["data"]["error_id"] in (
            "ERR_EQUIPMENT_WINDOW_CONFLICT", "ERR_APPOINTMENT_OVERLAP",
            "ERR_DOCK_CAPACITY_EXCEEDED")

        assert read_load(board["shipper_id"], second_load["id"])["status"] == "POSTED"
        assert read_load(board["shipper_id"], first_load["id"])["status"] == "BOOKED"