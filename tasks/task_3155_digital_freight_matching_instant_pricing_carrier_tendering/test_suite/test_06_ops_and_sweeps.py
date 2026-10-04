"""The periodic operations sweep and its three clock-driven transitions."""
from test_helpers import (
    api_client as api,
    make_carrier_headers,
    make_platform_admin_headers,
    make_shipper_headers,
    read_carrier,
    read_facility,
    read_load,
    run_sweep,
    set_clock,
    setup_board,
    setup_sweep_scenario,
    shift,
)


def _posted(board, window, **overrides):
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
        "pickup_window_start": window[0],
        "pickup_window_end": window[1],
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


class TestSweepReporting:
    """One sweep call reports each swept collection separately."""

    def test_one_sweep_reports_appointments_loads_and_carriers_separately(self):
        """PRD section 3.10: "it walks in-progress appointments first and scheduled
        appointments second, then posted loads, then verified carriers, marking
        overdue appointments `MISSED`, returning uncovered loads with no live quote
        inside the coverage horizon to `UNCOVERED`, and suspending carriers whose
        insurance has lapsed — reporting the ids it swept in each of the three
        categories along with the instant it processed them."

        Design: Corner/endpoints/sweep_reports_the_three_swept_collections_separately
        """
        board = setup_sweep_scenario()
        booked = board["booked_load"]
        abandoned = board["abandoned_load"]

        set_clock("2026-10-11T00:00:00Z")
        swept = run_sweep()

        assert len(swept["swept_appointment_ids"]) == 1
        assert len(swept["uncovered_load_ids"]) == 1
        assert swept["suspended_carrier_ids"] == [board["carrier_id"]]
        assert swept["processed_at"]

        appointment = api.list_load_appointments(
            booked["id"], make_shipper_headers(board["shipper_id"])).json()["data"][0]
        assert appointment["status"] == "MISSED"
        assert read_load(board["shipper_id"], abandoned["id"])["status"] == "UNCOVERED"
        carrier = read_carrier(board["carrier_id"])
        assert carrier["status"] == "SUSPENDED"
        assert carrier["suspension_reason"] == "INSURANCE_EXPIRED"

    def test_a_repeat_sweep_finds_nothing_left_to_do(self):
        """PRD section 3.10: "Every clock-relative condition in this document — quote expiry, insurance lapse, payout due dates, the missed-appointment grace, the coverage horizon, the repost deadline — is evaluated against that logical clock, and advancing it re-evaluates all of them at once. The periodic operations sweep is the batch form of the same idea: it walks in-progress appointments first and scheduled appointments second, then posted loads, then verified carriers, marking overdue appointments `MISSED`, returning uncovered loads with no live quote inside the coverage horizon to `UNCOVERED`, and suspending carriers whose insurance has lapsed — reporting the ids it swept in each of the three categories along with the instant it processed them."

        Design: Corner/endpoints/sweep_reports_the_three_swept_collections_separately
        """
        setup_sweep_scenario()
        set_clock("2026-10-11T00:00:00Z")
        run_sweep()
        again = run_sweep()
        assert again["swept_appointment_ids"] == []
        assert again["uncovered_load_ids"] == []
        assert again["suspended_carrier_ids"] == []


class TestOverdueAppointmentGrace:
    """The missed-appointment comparison is strict."""

    def test_a_slot_at_exactly_the_grace_boundary_is_not_yet_missed(self):
        """PRD section 3.5: "The comparison is strict: a slot sitting at exactly
        `window_end` plus sixty minutes is not yet missed."

        Design: Difficulty/transitive_cascade/appointment_slot_expiry_walks_slot_to_load_to_carrier_and_rolls_back_on_restore
        """
        board = setup_board(units=1)
        set_clock("2026-10-05T00:00:00Z")
        load, quote = _posted(board, ("2026-10-05T08:00:00Z", "2026-10-05T12:00:00Z"))
        created = api.create_booking(
            {
                "load_id": load["id"],
                "carrier_id": board["carrier_id"],
                "rate_quote_id": quote["id"],
                "equipment_id": board["equipment"][0]["id"],
                "expected_load_version": load["version"],
            },
            make_carrier_headers(board["carrier_id"]),
        )
        assert created.status_code == 201, created.text

        set_clock("2026-10-05T13:00:00Z")
        swept = run_sweep()
        assert swept["swept_appointment_ids"] == []
        appointment = api.list_load_appointments(
            load["id"], make_shipper_headers(board["shipper_id"])).json()["data"][0]
        assert appointment["status"] == "SCHEDULED"

    def test_one_minute_past_the_grace_boundary_misses_the_slot(self):
        """PRD section 3.5: "any slot still `SCHEDULED` at that point is marked
        `MISSED` and releases its dock by lowering `docks_committed_today`."

        Design: Difficulty/transitive_cascade/appointment_slot_expiry_walks_slot_to_load_to_carrier_and_rolls_back_on_restore
        """
        board = setup_board(units=1)
        set_clock("2026-10-05T00:00:00Z")
        load, quote = _posted(board, ("2026-10-05T08:00:00Z", "2026-10-05T12:00:00Z"))
        api.create_booking(
            {
                "load_id": load["id"],
                "carrier_id": board["carrier_id"],
                "rate_quote_id": quote["id"],
                "equipment_id": board["equipment"][0]["id"],
                "expected_load_version": load["version"],
            },
            make_carrier_headers(board["carrier_id"]),
        )

        set_clock("2026-10-05T13:01:00Z")
        swept = run_sweep()
        assert len(swept["swept_appointment_ids"]) == 1
        assert read_facility(board["origin_facility_id"])["docks_committed_today"] == 0


class TestUncoveredSweepBoundary:
    """The coverage-horizon comparison is inclusive."""

    def test_a_load_exactly_at_the_horizon_with_no_live_quote_is_swept(self):
        """PRD section 3.4: "The comparison is inclusive at the boundary: a load
        sitting exactly twenty-four hours out with no live quote is swept."

        Design: Corner/cross_cutting_complexity_layers/sweep_expires_the_quote_and_moves_the_posted_load_to_uncovered
        """
        board = setup_board(units=1)
        set_clock("2026-09-20T00:00:00Z")
        load, _ = _posted(board, ("2026-10-05T08:00:00Z", "2026-10-05T12:00:00Z"))
        set_clock(shift("2026-10-05T08:00:00Z", hours=-24))
        run_sweep()
        assert read_load(board["shipper_id"], load["id"])["status"] == "UNCOVERED"


class TestInsuranceExpirySweep:
    """A lapsed certificate suspends on any clock advance."""

    def test_a_certificate_expiring_exactly_at_the_clock_instant_suspends(self):
        """PRD section 3.10: "The comparison is inclusive — a certificate expiring
        at exactly the clock instant suspends."

        Design: Corner/errors/insurance_just_expired_returns_insurance_expired_at_the_instant
        """
        board = setup_board(units=1)
        carrier_id = board["carrier_id"]
        assert read_carrier(carrier_id)["status"] == "VERIFIED"

        set_clock("2027-06-01T00:00:00Z")
        swept = run_sweep()
        assert carrier_id in swept["suspended_carrier_ids"]
        carrier = read_carrier(carrier_id)
        assert carrier["status"] == "SUSPENDED"
        assert carrier["suspension_reason"] == "INSURANCE_EXPIRED"

    def test_an_already_suspended_carrier_is_not_swept_again(self):
        """PRD section 3.10: "Once suspended, a carrier is not swept again by the
        same rule."

        Design: Corner/errors/insurance_just_expired_returns_insurance_expired_at_the_instant
        """
        setup_board(units=1)
        set_clock("2027-06-01T00:00:00Z")
        run_sweep()
        again = run_sweep()
        assert again["suspended_carrier_ids"] == []