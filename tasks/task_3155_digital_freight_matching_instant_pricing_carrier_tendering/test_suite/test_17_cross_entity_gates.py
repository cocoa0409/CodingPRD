"""Cross-entity gates: a resource's own state is not the whole precondition."""
from test_helpers import (
    api_client as api,
    make_carrier_headers,
    make_platform_admin_headers,
    make_shipper_headers,
    read_load,
    set_clock,
    setup_board,
    shift,
)


def _posted(board, window=("2026-10-05T08:00:00Z", "2026-10-05T12:00:00Z"), **overrides):
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


def _ping(board, load_id, sequence, reported_status, eta=None):
    payload = {"carrier_id": board["carrier_id"], "sequence": sequence,
               "reported_status": reported_status, "location_code": f"9vg8{sequence}"}
    if eta is not None:
        payload["eta_utc"] = eta
    response = api.report_tracking_ping(load_id, payload,
                                        make_carrier_headers(board["carrier_id"]))
    assert response.status_code == 201, response.text
    return response.json()["data"]


class TestQuoteViewabilityGate:
    """A quote's viewability turns on its load's live state."""

    def test_a_quote_whose_load_has_left_the_board_is_not_viewable(self):
        """PRD section 3.2: "and the quote's load must still be `POSTED`, or the
        open is refused with `ERR_QUOTE_NOT_VIEWABLE` (HTTP 409)."

        Design: Difficulty/cross_entity_state_dependency/instrumented_quote_refuses_expiry_once_its_load_has_left_posted
        """
        board = setup_board(units=2)
        set_clock("2026-10-05T00:00:00Z")
        load_one, quote_one = _posted(board, ("2026-10-05T08:00:00Z", "2026-10-05T12:00:00Z"))
        load_two, quote_two = _posted(board, ("2026-10-06T08:00:00Z", "2026-10-06T12:00:00Z"))
        _book(board, load_two, quote_two, board["equipment"][1]["id"])
        assert read_load(board["shipper_id"], load_two["id"])["status"] == "BOOKED"

        blocked = api.view_rate_quote(quote_two["id"], make_carrier_headers(board["carrier_id"]))
        assert blocked.status_code == 409, blocked.text
        assert blocked.json()["data"]["error_id"] == "ERR_QUOTE_NOT_VIEWABLE"

        accepted = api.get_rate_quote(
            quote_two["id"], make_shipper_headers(board["shipper_id"])).json()["data"]
        assert accepted["status"] == "ACCEPTED"
        assert accepted["status"] != "VIEWED"

    def test_the_sibling_loads_quote_is_still_viewable(self):
        """PRD section 3.2: "Re-opening a quote the carrier has already seen is
        idempotent — the carrier's id is already present, the status stays
        `VIEWED`, and the act is recorded without complaint."

        Design: Difficulty/cross_entity_state_dependency/instrumented_quote_refuses_expiry_once_its_load_has_left_posted
        """
        board = setup_board(units=2)
        set_clock("2026-10-05T00:00:00Z")
        load_one, quote_one = _posted(board, ("2026-10-05T08:00:00Z", "2026-10-05T12:00:00Z"))
        load_two, quote_two = _posted(board, ("2026-10-06T08:00:00Z", "2026-10-06T12:00:00Z"))
        _book(board, load_two, quote_two, board["equipment"][1]["id"])

        opened = api.view_rate_quote(quote_one["id"], make_carrier_headers(board["carrier_id"]))
        assert opened.status_code == 200, (
            f"load one is still POSTED, so its quote is viewable, got {opened.text}")
        assert opened.json()["data"]["status"] == "VIEWED"
        assert board["carrier_id"] in opened.json()["data"]["viewed_carrier_ids"]
        assert read_load(board["shipper_id"], load_one["id"])["status"] == "POSTED"


class TestWaiveWindowGate:
    """A detention event's own state is not the whole story."""

    def test_a_reason_outside_the_closed_set_is_refused(self):
        """PRD section 3.10: "An operator may waive a detention event only when the
        supplied `reason_code` is one of `FACILITY_FAULT`, `FORCE_MAJEURE`, or
        `GOODWILL`; any other code is refused with `ERR_WAIVE_REASON_REQUIRED` (HTTP
        409)."

        Design: Difficulty/cross_entity_state_dependency/detention_waive_requires_a_delivered_or_invoiced_load
        """
        board = _fresh_waivable_event()
        open_event = _open_detention(board)
        refused = api.waive_detention_event(open_event["id"], "INCORRECT_CHARGE",
                                            make_platform_admin_headers())
        assert refused.status_code == 409, refused.text
        assert refused.json()["data"]["error_id"] == "ERR_WAIVE_REASON_REQUIRED"

        unchanged = api.get_detention_event(
            open_event["id"], make_platform_admin_headers()).json()["data"]
        assert unchanged["status"] == "CLOSED"
        assert unchanged["detention_charge_cents"] == 30000

    def test_waiving_drops_only_the_waived_events_charge(self):
        """PRD section 3.10: "The load's `accessorial_total_cents` is the sum over
        its `OPEN` and `CLOSED` events only, so a waived event contributes exactly
        nothing — even though the pre-waive charge remains visible on the row for
        audit."

        Design: Difficulty/cross_entity_state_dependency/detention_waive_requires_a_delivered_or_invoiced_load
        """
        board = _fresh_waivable_event()
        open_event = _open_detention(board)
        before = read_load(board["shipper_id"], board["load"]["id"])
        assert before["accessorial_total_cents"] == 45000

        set_clock("2026-10-28T00:00:00Z")
        waived = api.waive_detention_event(open_event["id"], "FACILITY_FAULT",
                                           make_platform_admin_headers())
        assert waived.status_code == 200, waived.text
        assert waived.json()["data"]["status"] == "WAIVED"
        assert waived.json()["data"]["detention_charge_cents"] == 0

        after = read_load(board["shipper_id"], board["load"]["id"])
        assert after["accessorial_total_cents"] == 15000, (
            "the closed pickup event still bills 15,000 cents")
        assert after["accessorial_total_cents"] != 0

        pickup_events = api.list_load_detention_events(
            board["load"]["id"], make_shipper_headers(board["shipper_id"])).json()["data"]
        closed = [event for event in pickup_events if event["status"] == "CLOSED"]
        assert len(closed) == 1
        assert closed[0]["detention_charge_cents"] == 15000


def _fresh_waivable_event():
    """A delivered load whose pickup dwell bills 15,000 cents, plus a delivery
    detention event the operator can waive.

    The delivery leg dwells 330 minutes so its event bills 30,000 cents; the
    pickup event is closed when the driver departed and keeps its 15,000-cent
    charge, which is the sibling the waive must leave untouched.
    """
    board = setup_board(units=1)
    set_clock("2026-10-05T00:00:00Z")
    window = ("2026-10-05T08:00:00Z", "2026-10-05T12:00:00Z")
    load, quote = _posted(board, window)
    _book(board, load, quote, board["equipment"][0]["id"])

    set_clock("2026-10-05T07:30:00Z")
    _ping(board, load["id"], 1, "EN_ROUTE_PICKUP")
    set_clock("2026-10-05T08:00:00Z")
    _ping(board, load["id"], 2, "AT_PICKUP")
    set_clock("2026-10-05T11:05:00Z")
    _ping(board, load["id"], 3, "IN_TRANSIT", eta="2026-10-07T16:00:00Z")
    set_clock("2026-10-06T08:00:00Z")
    _ping(board, load["id"], 4, "AT_DELIVERY", eta="2026-10-07T16:00:00Z")
    set_clock("2026-10-06T13:30:00Z")
    _ping(board, load["id"], 5, "DELIVERED")
    board["load"] = read_load(board["shipper_id"], load["id"])
    return board


def _open_detention(board):
    events = api.list_load_detention_events(
        board["load"]["id"], make_shipper_headers(board["shipper_id"])).json()["data"]
    assert len(events) == 2, f"expected the pickup and delivery events, got {events}"
    # The delivery event is the later one and still bills its own charge.
    return events[-1]


class TestQuickPayTierCounting:
    """The tier count covers settlements already paid strictly before the instant."""

    def test_two_settlements_paid_at_the_same_instant_share_a_tier(self):
        """PRD section 3.9: "Quick pay costs the carrier a tiered discount, and the tier is chosen from history rather than from the amount. The server counts the carrier's settlements already in `PAID` status whose `paid_at` falls strictly before the payout instant — the settlement being paid is not counted among them — and selects a discount rate from that count alone: zero through four prior paid settlements earn a rate of three hundredths, five through nineteen earn two and a half hundredths, twenty through forty-nine earn two hundredths, and fifty or more earn one and a half hundredths."

        Design: Difficulty/compensating_invariant/quick_pay_election_is_not_part_of_the_gross_and_reverses_cleanly
        """
        board = setup_board(units=2)
        set_clock("2026-10-05T00:00:00Z")
        first = _deliver_and_invoice(board, ("2026-10-05T08:00:00Z", "2026-10-05T12:00:00Z"),
                                     board["equipment"][0]["id"])
        second = _deliver_and_invoice(board, ("2026-10-06T08:00:00Z", "2026-10-06T12:00:00Z"),
                                      board["equipment"][1]["id"])
        # QUICK_PAY must beat the due instant, so the payout instant is chosen
        # inside the 30-day terms window for both settlements.
        payout_instant = "2026-10-20T00:00:00Z"
        set_clock(payout_instant)

        paid_first = _quick_pay(first)
        # The tier counts settlements whose paid_at falls strictly before the
        # payout instant, so the second payout is taken one second later: both
        # then sit in the same 0.0300 tier.
        set_clock("2026-10-20T00:00:01Z")
        paid_second = _quick_pay(second)

        for paid in (paid_first, paid_second):
            gross = paid["gross_payable_cents"]
            assert paid["settlement_status"] == "PAID"
            assert paid["quick_pay_discount_cents"] == int(gross * 0.0300 + 0.5), (
                "with no strictly-earlier paid settlement both pay at the 0.0300 tier")
            assert paid["net_payable_cents"] == gross - paid["quick_pay_discount_cents"]

        booking = api.get_booking(
            first["booking"]["id"], make_carrier_headers(board["carrier_id"])).json()["data"]
        assert booking["quick_pay_elected"] is True
        assert booking["quick_pay_discount_cents"] == paid_first["quick_pay_discount_cents"]


def _deliver_and_invoice(board, window, equipment_id):
    load, quote = _posted(board, window)
    booking = _book(board, load, quote, equipment_id)
    set_clock(window[0])
    _ping(board, load["id"], 1, "EN_ROUTE_PICKUP")
    set_clock(shift(window[0], minutes=10))
    _ping(board, load["id"], 2, "AT_PICKUP")
    set_clock(shift(window[0], minutes=40))
    _ping(board, load["id"], 3, "IN_TRANSIT", eta="2026-10-07T16:00:00Z")
    set_clock(shift(window[0], hours=20))
    _ping(board, load["id"], 4, "AT_DELIVERY", eta="2026-10-07T16:00:00Z")
    set_clock(shift(window[0], hours=21))
    _ping(board, load["id"], 5, "DELIVERED")

    invoiced = api.invoice_booking(booking["id"], make_shipper_headers(board["shipper_id"]))
    assert invoiced.status_code == 200, invoiced.text
    settlements = api.list_load_settlements(
        load["id"], make_platform_admin_headers()).json()["data"]
    return {"load": load, "quote": quote, "booking": booking, "settlement": settlements[0]}


def _quick_pay(entry):
    settlement = api.get_settlement(
        entry["settlement"]["id"], make_platform_admin_headers()).json()["data"]
    paid = api.payout_settlement(
        settlement["id"],
        {"payout_mode": "QUICK_PAY", "expected_settlement_version": settlement["version"]},
        make_platform_admin_headers())
    assert paid.status_code == 200, paid.text
    return paid.json()["data"]