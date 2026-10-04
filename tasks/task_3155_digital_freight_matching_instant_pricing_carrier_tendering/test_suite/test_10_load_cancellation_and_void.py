"""Load cancellation, in-transit unwind and void compensation."""
from test_helpers import (
    api_client as api,
    assert_settlement_reverses,
    make_carrier_headers,
    make_platform_admin_headers,
    make_shipper_headers,
    read_carrier,
    read_load,
    read_settlement,
    set_clock,
    setup_board,
    setup_invoiced_load,
    setup_paid_load,
    shift,
    list_load_settlements,
)


def _posted_load(board, window=None, **overrides):
    window = window or ("2026-10-05T08:00:00Z", "2026-10-05T12:00:00Z")
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


def _credit(board):
    return api.get_shipper(board["shipper_id"],
                           make_shipper_headers(board["shipper_id"])).json()["data"]


class TestCreditConservation:
    """The shipper's exposure is conserved across booking, cancel and void."""

    def test_a_void_returns_credit_used_to_its_pre_booking_reading(self):
        """PRD section 2.8: "`credit_limit_cents` is the maximum outstanding booked-rate exposure the platform will carry on the shipper's behalf, and `credit_used_cents` is the portion currently consumed. Exposure is reserved the moment a load is booked — `credit_used_cents` rises by the booking's `agreed_rate_cents` when the booking is created — and is discharged when the carrier is actually paid, at which point `credit_used_cents` falls by the same `agreed_rate_cents`."

        Design: Difficulty/compensating_invariant/load_cancel_debits_and_void_credits_the_same_booking_price_back
        """
        board = setup_board(units=1)
        set_clock("2026-10-05T00:00:00Z")
        shipper_before = _credit(board)
        assert shipper_before["credit_used_cents"] == 0

        load, quote = _posted_load(board)
        booking = _book(board, load, quote, board["equipment"][0]["id"])
        after_booking = _credit(board)
        assert after_booking["credit_used_cents"] == booking["agreed_rate_cents"]
        assert after_booking["credit_used_cents"] > 0

        cancelled = api.cancel_load(load["id"], make_shipper_headers(board["shipper_id"]))
        assert cancelled.status_code == 200, cancelled.text
        assert cancelled.json()["data"]["status"] == "CANCELLED"
        after_cancel = _credit(board)
        assert after_cancel["credit_used_cents"] == shipper_before["credit_used_cents"]

    def test_cancelling_a_booked_load_releases_the_unit_and_the_slot(self):
        """PRD section 3.10: "Cancelling a `BOOKED` load does the same plus more:
        the equipment unit returns to `AVAILABLE`, the synthesized `PICKUP`
        appointment becomes `CANCELLED`, the shipper's `credit_used_cents` falls by
        the booking's `agreed_rate_cents`, and the booking itself becomes
        `CANCELLED`."

        Design: Difficulty/compensating_invariant/load_cancel_debits_and_void_credits_the_same_booking_price_back
        """
        board = setup_board(units=1)
        set_clock("2026-10-05T00:00:00Z")
        load, quote = _posted_load(board)
        booking = _book(board, load, quote, board["equipment"][0]["id"])

        cancelled = api.cancel_load(load["id"], make_shipper_headers(board["shipper_id"]))
        assert cancelled.status_code == 200, cancelled.text

        equipment = api.get_equipment(
            board["equipment"][0]["id"], make_carrier_headers(board["carrier_id"])).json()["data"]
        assert equipment["status"] == "AVAILABLE"

        appointment = api.list_load_appointments(
            load["id"], make_shipper_headers(board["shipper_id"])).json()["data"][0]
        assert appointment["status"] == "CANCELLED"

        refreshed = api.get_booking(
            booking["id"], make_carrier_headers(board["carrier_id"])).json()["data"]
        assert refreshed["status"] == "CANCELLED"

        shipper = _credit(board)
        assert shipper["load_credits_committed"] == 0

    def test_a_cancel_after_movement_is_refused(self):
        """PRD section 3.7: "Cancelling a `BOOKED` load before it moves is the
        shipper's prerogative and requires that no tracking ping has yet been
        recorded for it — once the driver has reported anything, the cancel is
        refused with `ERR_INVALID_STATE` (HTTP 409)."

        Design: Corner/state_machines/paid_load_rejects_cancel_with_already_terminal_but_leaves_void_open
        """
        board = setup_board(units=1)
        set_clock("2026-10-05T00:00:00Z")
        load, quote = _posted_load(board)
        _book(board, load, quote, board["equipment"][0]["id"])
        api.report_tracking_ping(
            load["id"],
            {"carrier_id": board["carrier_id"], "sequence": 1,
             "reported_status": "EN_ROUTE_PICKUP", "location_code": "9vg81"},
            make_carrier_headers(board["carrier_id"]))

        refused = api.cancel_load(load["id"], make_shipper_headers(board["shipper_id"]))
        assert refused.status_code == 409, refused.text
        assert refused.json()["data"]["error_id"] == "ERR_INVALID_STATE"


class TestTerminalLockdown:
    """PAID is terminal for cancel; only void leaves it."""

    def test_a_paid_load_rejects_the_cancel_endpoint(self):
        """PRD section 2.6: "a request aimed at a resource that has already reached
        one of its terminal states is refused as `ERR_ALREADY_TERMINAL` (HTTP 409)
        rather than being re-examined against the rules of the state it left."

        Design: Corner/state_machines/paid_load_rejects_cancel_with_already_terminal_but_leaves_void_open
        """
        board = setup_paid_load()
        assert board["load"]["status"] == "PAID"

        refused = api.cancel_load(board["load"]["id"],
                                  make_shipper_headers(board["shipper_id"]))
        assert refused.status_code == 409, refused.text
        assert refused.json()["data"]["error_id"] == "ERR_ALREADY_TERMINAL"
        assert read_load(board["shipper_id"], board["load"]["id"])["status"] == "PAID"

    def test_the_void_path_still_leaves_a_paid_load(self):
        """PRD section 3.10: "Voiding a load whose settlement is already `PAID`
        works the same way: the paid row becomes `REVERSED`, the compensating row
        is written against it with the same exact negations, the shipper's
        `load_credits_committed` falls by one, and the load becomes `VOIDED`."

        Design: Corner/state_machines/paid_load_rejects_cancel_with_already_terminal_but_leaves_void_open
        """
        board = setup_paid_load()
        voided = api.void_load(board["load"]["id"], "void-paid-3155",
                               make_platform_admin_headers())
        assert voided.status_code == 200, voided.text
        assert voided.json()["data"]["status"] == "VOIDED"

        rows = list_load_settlements(board["load"]["id"])
        assert len(rows) == 2
        forward = [row for row in rows if row["reversal_of_settlement_id"] is None][0]
        reversal = [row for row in rows if row["reversal_of_settlement_id"] is not None][0]
        assert_settlement_reverses(forward, reversal)

        shipper = _credit(board)
        assert shipper["load_credits_committed"] == 0


class TestInTransitUnwind:
    """An operator can unwind an in-transit booking while it is unpaid."""

    def test_cancelling_in_transit_returns_the_load_to_the_board(self):
        """PRD section 3.10: "Cancelling an `IN_TRANSIT` booking is permitted while its settlement is not `PAID` — once the carrier has been paid the attempt is refused with `ERR_SETTLEMENT_ALREADY_PAID` (HTTP 409). The cancellation sets the booking to `CANCELLED`, returns the equipment unit to `AVAILABLE`, releases the shipper's credit by the agreed rate, and puts the load back on the board as `UNCOVERED` — and here is the subtlety: the load's posting credit stays committed, because the load is still holding a slot even though it is back to being uncovered."

        Design: Difficulty/transitive_cascade/insurance_suspension_walks_carrier_to_booking_to_equipment_to_load_to_quote
        """
        board = setup_board(units=1)
        set_clock("2026-10-05T00:00:00Z")
        load, quote = _posted_load(board)
        booking = _book(board, load, quote, board["equipment"][0]["id"])
        set_clock("2026-10-05T08:00:00Z")
        api.report_tracking_ping(
            load["id"],
            {"carrier_id": board["carrier_id"], "sequence": 1,
             "reported_status": "EN_ROUTE_PICKUP", "location_code": "9vg81"},
            make_carrier_headers(board["carrier_id"]))
        api.report_tracking_ping(
            load["id"],
            {"carrier_id": board["carrier_id"], "sequence": 2,
             "reported_status": "AT_PICKUP", "location_code": "9vg82"},
            make_carrier_headers(board["carrier_id"]))
        moved = api.report_tracking_ping(
            load["id"],
            {"carrier_id": board["carrier_id"], "sequence": 3,
             "reported_status": "IN_TRANSIT", "location_code": "9vg83",
             "eta_utc": "2026-10-07T16:00:00Z"},
            make_carrier_headers(board["carrier_id"]))
        assert moved.status_code == 201, moved.text

        unwound = api.cancel_booking_in_transit(booking["id"], "CARRIER_FAILURE",
                                                make_platform_admin_headers())
        assert unwound.status_code == 200, unwound.text
        assert unwound.json()["data"]["status"] == "CANCELLED"

        assert read_load(board["shipper_id"], load["id"])["status"] == "UNCOVERED"
        equipment = api.get_equipment(
            board["equipment"][0]["id"], make_carrier_headers(board["carrier_id"])).json()["data"]
        assert equipment["status"] == "AVAILABLE"
        shipper = _credit(board)
        assert shipper["credit_used_cents"] == 0
        assert shipper["load_credits_committed"] == 1

    def test_a_paid_settlement_blocks_the_in_transit_cancel(self):
        """PRD section 3.10: "Cancelling an `IN_TRANSIT` booking is permitted while
        its settlement is not `PAID` — once the carrier has been paid the attempt is
        refused with `ERR_SETTLEMENT_ALREADY_PAID` (HTTP 409)."

        Design: Difficulty/compensating_invariant/quick_pay_election_is_not_part_of_the_gross_and_reverses_cleanly
        """
        board = setup_paid_load()
        refused = api.cancel_booking_in_transit(board["booking"]["id"], "OPS_ERROR",
                                                make_platform_admin_headers())
        assert refused.status_code == 409, refused.text
        assert refused.json()["data"]["error_id"] == "ERR_SETTLEMENT_ALREADY_PAID"


class TestVoidIdempotency:
    """A repeated void key returns the stored outcome."""

    def test_a_replayed_void_adds_no_second_compensating_row(self):
        """PRD section 3.10: "A void requires a `retry_idempotency_key`, and a
        repeated call carrying a key already used on that load returns the stored
        void rather than voiding twice."

        Design: Corner/cross_cutting_complexity_layers/void_with_a_repeated_retry_key_returns_the_first_outcome_and_adds_no_second_compensation
        """
        board = setup_invoiced_load()
        load_id = board["load"]["id"]
        forward_id = board["settlement"]["id"]

        first = api.void_load(load_id, "void-load-3155-a", make_platform_admin_headers())
        assert first.status_code == 200, first.text
        assert first.json()["data"]["status"] == "VOIDED"

        second = api.void_load(load_id, "void-load-3155-a", make_platform_admin_headers())
        assert second.status_code == 200, second.text

        rows = list_load_settlements(load_id)
        assert len(rows) == 2, "a replayed void must not synthesize a third row"
        forward = read_settlement(forward_id)
        assert forward["settlement_status"] == "REVERSED"
        reversal = [row for row in rows if row["reversal_of_settlement_id"] == forward_id][0]
        assert reversal["settlement_status"] == "ACCRUED"
        assert_settlement_reverses(forward, reversal)

        shipper = _credit(board)
        assert shipper["load_credits_committed"] == 0, (
            "the void releases the posting credit exactly once")

    def test_a_void_negates_every_settlement_line_exactly(self):
        """PRD section 3.10: "The compensating row negates that row's line haul,
        accessorial line, claims deduction, quick-pay discount, gross payable, and
        net payable exactly, figure for figure."

        Design: Difficulty/compensating_invariant/load_cancel_debits_and_void_credits_the_same_booking_price_back
        """
        board = setup_invoiced_load()
        api.void_load(board["load"]["id"], "void-negation-3155",
                      make_platform_admin_headers())
        rows = list_load_settlements(board["load"]["id"])
        forward = [row for row in rows if row["reversal_of_settlement_id"] is None][0]
        reversal = [row for row in rows if row["reversal_of_settlement_id"] == forward["id"]][0]
        assert_settlement_reverses(forward, reversal)