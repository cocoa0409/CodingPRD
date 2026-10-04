"""Multi-hop cascades: the insurance unwind and the missed-appointment chain."""
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


def _book(board, load, quote, equipment_id):
    response = api.create_booking(
        {"load_id": load["id"], "carrier_id": board["carrier_id"],
         "rate_quote_id": quote["id"], "equipment_id": equipment_id,
         "expected_load_version": load["version"]},
        make_carrier_headers(board["carrier_id"]))
    assert response.status_code == 201, response.text
    return response.json()["data"]


def _ping(board, load_id, sequence, reported_status):
    response = api.report_tracking_ping(
        load_id,
        {"carrier_id": board["carrier_id"], "sequence": sequence,
         "reported_status": reported_status, "location_code": f"9vg8{sequence}"},
        make_carrier_headers(board["carrier_id"]))
    assert response.status_code == 201, response.text
    return response.json()["data"]


class TestInsuranceSuspensionCascade:
    """One lapsed certificate walks carrier to booking to equipment to load."""

    def test_the_four_hop_unwind_fires_from_a_single_sweep(self):
        """PRD section 3.10: "Every booking of that carrier in
        `PENDING_APPOINTMENT` or `IN_TRANSIT` status becomes `CANCELLED`; each such
        booking's equipment unit returns to `AVAILABLE`; and each such booking's
        load returns to `UNCOVERED` so the shipper may repost it."

        Design: Difficulty/transitive_cascade/insurance_suspension_walks_carrier_to_booking_to_equipment_to_load_to_quote
        """
        board = setup_board(units=1,
                            carrier_overrides={"insurance_expires_at": "2026-10-10T00:00:00Z"})
        set_clock("2026-10-05T00:00:00Z")
        load, quote = _posted(board, ("2026-10-05T08:00:00Z", "2026-10-05T12:00:00Z"))
        booking = _book(board, load, quote, board["equipment"][0]["id"])

        set_clock("2026-10-11T00:00:00Z")
        swept = run_sweep()
        assert board["carrier_id"] in swept["suspended_carrier_ids"]

        carrier = read_carrier(board["carrier_id"])
        assert carrier["status"] == "SUSPENDED"
        assert carrier["suspension_reason"] == "INSURANCE_EXPIRED"

        cancelled = api.get_booking(
            booking["id"], make_carrier_headers(board["carrier_id"])).json()["data"]
        assert cancelled["status"] == "CANCELLED"

        equipment = api.get_equipment(
            board["equipment"][0]["id"], make_carrier_headers(board["carrier_id"])).json()["data"]
        assert equipment["status"] == "AVAILABLE"

        unwound = read_load(board["shipper_id"], load["id"])
        assert unwound["status"] == "UNCOVERED"
        assert unwound["carrier_id"] is None

    def test_a_suspended_carrier_can_no_longer_be_tendered(self):
        """PRD section 2.10: "The carrier's status must be `VERIFIED`; otherwise the
        answer is `ERR_CARRIER_NOT_VERIFIED` (HTTP 409)."

        Design: Difficulty/transitive_cascade/insurance_suspension_walks_carrier_to_booking_to_equipment_to_load_to_quote
        """
        board = setup_board(units=1,
                            carrier_overrides={"insurance_expires_at": "2026-10-10T00:00:00Z"})
        set_clock("2026-10-05T00:00:00Z")
        first, quote = _posted(board, ("2026-10-05T08:00:00Z", "2026-10-05T12:00:00Z"))
        _book(board, first, quote, board["equipment"][0]["id"])

        set_clock("2026-10-11T00:00:00Z")
        run_sweep()
        assert read_carrier(board["carrier_id"])["status"] == "SUSPENDED"

        spare, spare_quote = _posted(board, ("2026-10-20T08:00:00Z", "2026-10-20T12:00:00Z"))
        rejected = api.create_booking(
            {"load_id": spare["id"], "carrier_id": board["carrier_id"],
             "rate_quote_id": spare_quote["id"], "equipment_id": board["equipment"][0]["id"],
             "expected_load_version": spare["version"]},
            make_carrier_headers(board["carrier_id"]))
        assert rejected.status_code == 409, rejected.text
        assert rejected.json()["data"]["error_id"] == "ERR_CARRIER_NOT_VERIFIED"


class TestMissedAppointmentCascade:
    """A missed slot writes the load's breach flag and re-scores the carrier."""

    def test_the_slot_to_load_to_carrier_chain_fires_once(self):
        """PRD section 3.6: "otherwise the load is in breach exactly when the
        elapsed time from `pickup_window_end` to `actual_pickup_at` is strictly more
        than 30 minutes."
        PRD section 3.6: "A missed appointment on a load that never saw an `AT_PICKUP` ping
        therefore adds nothing to that shipper's count, because no flag
        was ever written to attribute it to. The breach also recomputes
        the carrier's `operational_risk_score` with the
        eight-point-per-breached-load deduction of §2.10, applied once per
        breached load."

        Design: Difficulty/transitive_cascade/appointment_slot_expiry_walks_slot_to_load_to_carrier_and_rolls_back_on_restore
        """
        board = setup_board(units=2)
        set_clock("2026-10-05T00:00:00Z")
        window_a = ("2026-10-05T08:00:00Z", "2026-10-05T12:00:00Z")
        window_b = ("2026-10-05T08:00:00Z", "2026-10-05T12:00:00Z")
        load_a, quote_a = _posted(board, window_a)
        load_b, quote_b = _posted(board, window_b)
        _book(board, load_a, quote_a, board["equipment"][0]["id"])
        _book(board, load_b, quote_b, board["equipment"][1]["id"])

        # Load A arrives, very late, but the appointment is never completed.
        set_clock("2026-10-05T13:00:00Z")
        _ping(board, load_a["id"], 1, "EN_ROUTE_PICKUP")
        _ping(board, load_a["id"], 2, "AT_PICKUP")
        # Load B never reports at all, so it can never be in breach.

        set_clock("2026-10-05T15:00:00Z")
        swept = run_sweep()
        assert len(swept["swept_appointment_ids"]) == 2

        slots_a = api.list_load_appointments(
            load_a["id"], make_shipper_headers(board["shipper_id"])).json()["data"]
        slots_b = api.list_load_appointments(
            load_b["id"], make_shipper_headers(board["shipper_id"])).json()["data"]
        assert all(slot["status"] == "MISSED" for slot in slots_a + slots_b)

        refreshed_a = read_load(board["shipper_id"], load_a["id"])
        assert refreshed_a["pickup_breach_flag"] is True
        refreshed_b = read_load(board["shipper_id"], load_b["id"])
        assert refreshed_b["pickup_breach_flag"] is False

        carrier = read_carrier(board["carrier_id"])
        assert carrier["operational_risk_score"] == 92.0
        assert carrier["operational_risk_score"] != 84.0

    def test_a_second_sweep_does_not_double_count_the_breach(self):
        """PRD section 3.6: "A missed appointment on a load that never saw an `AT_PICKUP` ping therefore adds nothing to that shipper's count, because no flag was ever written to attribute it to. The breach also recomputes the carrier's `operational_risk_score` with the eight-point-per-breached-load deduction of §2.10, applied once per breached load."

        Design: Difficulty/transitive_cascade/appointment_slot_expiry_walks_slot_to_load_to_carrier_and_rolls_back_on_restore
        """
        board = setup_board(units=1)
        set_clock("2026-10-05T00:00:00Z")
        load, quote = _posted(board, ("2026-10-05T08:00:00Z", "2026-10-05T12:00:00Z"))
        _book(board, load, quote, board["equipment"][0]["id"])
        set_clock("2026-10-05T13:00:00Z")
        _ping(board, load["id"], 1, "EN_ROUTE_PICKUP")
        _ping(board, load["id"], 2, "AT_PICKUP")
        set_clock("2026-10-05T15:00:00Z")
        run_sweep()
        assert read_carrier(board["carrier_id"])["operational_risk_score"] == 92.0

        run_sweep()
        assert read_carrier(board["carrier_id"])["operational_risk_score"] == 92.0

    def test_a_slot_restored_before_the_sweep_never_breaches(self):
        """PRD section 3.5: "A slot can be restored only while the same capacity
        guard still passes."

        Design: Difficulty/transitive_cascade/appointment_slot_expiry_walks_slot_to_load_to_carrier_and_rolls_back_on_restore
        """
        board = setup_board(units=1)
        set_clock("2026-10-05T00:00:00Z")
        cancelled_load, cancelled_quote = _posted(
            board, ("2026-10-05T08:00:00Z", "2026-10-05T10:00:00Z"), distance_miles=1000)
        restored_load, restored_quote = _posted(
            board, ("2026-10-06T08:00:00Z", "2026-10-06T10:00:00Z"), distance_miles=900)
        _book(board, cancelled_load, cancelled_quote, board["equipment"][0]["id"])
        _book(board, restored_load, restored_quote, board["equipment"][0]["id"])

        slot = api.list_load_appointments(
            cancelled_load["id"], make_shipper_headers(board["shipper_id"])).json()["data"][0]
        api.cancel_appointment(slot["id"], make_carrier_headers(board["carrier_id"]))
        restored = api.restore_appointment(slot["id"], make_carrier_headers(board["carrier_id"]))
        assert restored.status_code == 200, restored.text
        assert restored.json()["data"]["status"] == "SCHEDULED"

        refreshed = read_load(board["shipper_id"], cancelled_load["id"])
        assert refreshed["pickup_breach_flag"] is False, (
            "a slot that never saw an arrival ping can never be in breach")
        assert read_carrier(board["carrier_id"])["operational_risk_score"] == 100.0


class TestBulkCapacityFailure:
    """A capacity failure is reported before any identifier shape check."""

    def test_a_full_facility_reports_capacity_not_a_booking_conflict(self):
        """PRD section 2.11: "That count rises when a slot is created in `SCHEDULED` or `IN_PROGRESS` status and falls when a slot is cancelled, missed, or otherwise leaves that pair of states. A slot cannot be placed when the committed count has already reached the capacity — the guard trips at equality, not only above it — and the attempt is refused with `ERR_DOCK_CAPACITY_EXCEEDED` (HTTP 409)."

        Design: Corner/endpoints/bulk_appointment_capacity_error_does_not_typecheck_each_id
        """
        board = setup_board(units=2, origin_overrides={"dock_capacity": 1})
        set_clock("2026-10-05T00:00:00Z")
        first, first_quote = _posted(board, ("2026-10-05T08:00:00Z", "2026-10-05T09:00:00Z"))
        second, second_quote = _posted(board, ("2026-10-05T08:00:00Z", "2026-10-05T09:00:00Z"))

        accepted = api.create_booking(
            {"load_id": first["id"], "carrier_id": board["carrier_id"],
             "rate_quote_id": first_quote["id"], "equipment_id": board["equipment"][0]["id"],
             "expected_load_version": first["version"]},
            make_carrier_headers(board["carrier_id"]))
        assert accepted.status_code == 201, accepted.text

        rejected = api.create_booking(
            {"load_id": second["id"], "carrier_id": board["carrier_id"],
             "rate_quote_id": second_quote["id"], "equipment_id": board["equipment"][1]["id"],
             "expected_load_version": second["version"]},
            make_carrier_headers(board["carrier_id"]))
        assert rejected.status_code == 409, rejected.text
        assert rejected.json()["data"]["error_id"] == "ERR_DOCK_CAPACITY_EXCEEDED"

        facility = read_facility(board["origin_facility_id"])
        assert facility["docks_committed_today"] == 1
        assert facility["dock_capacity"] == 1
        assert read_load(board["shipper_id"], second["id"])["status"] == "POSTED"