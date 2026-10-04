"""Error catalogue: the trigger condition behind each refusal."""
from test_helpers import (
    api_client as api,
    ApiErrorId,
    make_carrier_headers,
    make_claims_adjuster_headers,
    make_compliance_reviewer_headers,
    make_platform_admin_headers,
    make_shipper_headers,
    NON_EXISTENT_UUID,
    iso3,
    read_carrier,
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


class TestExistenceErrors:
    """Not-found errors name the kind of identifier that failed."""

    def test_an_unallocated_path_segment_reports_the_entity_specific_error(self):
        """PRD section 2.6: "Upstream identifiers are also resolved before any request-body identifier, and creation requests validate the parent context before any business rule is evaluated. The not-found errors are specific to the kind of identifier that failed: `ERR_LOAD_NOT_FOUND`, `ERR_SHIPPER_NOT_FOUND`, `ERR_CARRIER_NOT_FOUND`, `ERR_FACILITY_NOT_FOUND`, `ERR_EQUIPMENT_NOT_FOUND`, `ERR_QUOTE_NOT_FOUND`, `ERR_BOOKING_NOT_FOUND`, `ERR_APPOINTMENT_NOT_FOUND`, `ERR_DETENTION_NOT_FOUND`, `ERR_CLAIM_NOT_FOUND`, `ERR_SETTLEMENT_NOT_FOUND`, and `ERR_CONTRACT_NOT_FOUND` each answer 404 Not Found with the id that did not resolve."
        PRD section 2.6: "The not-found errors are specific to the kind of identifier that
        failed: `ERR_LOAD_NOT_FOUND`, `ERR_SHIPPER_NOT_FOUND`,
        `ERR_CARRIER_NOT_FOUND`, `ERR_FACILITY_NOT_FOUND`,
        `ERR_EQUIPMENT_NOT_FOUND`, `ERR_QUOTE_NOT_FOUND`,
        `ERR_BOOKING_NOT_FOUND`, `ERR_APPOINTMENT_NOT_FOUND`,
        `ERR_DETENTION_NOT_FOUND`, `ERR_CLAIM_NOT_FOUND`,
        `ERR_SETTLEMENT_NOT_FOUND`, and `ERR_CONTRACT_NOT_FOUND` each
        answer 404 Not Found with the id that did not resolve."

        Design: Corner/entities/load_get_for_an_unallocated_id_returns_load_not_found
        """
        board = setup_board(units=1)
        set_clock("2026-09-20T00:00:00Z")
        headers = make_shipper_headers(board["shipper_id"])

        response = api.get_load(NON_EXISTENT_UUID, headers)
        assert response.status_code == 404, response.text
        body = response.json()
        assert body["response_type"] == "error"
        assert body["data"]["error_id"] == "ERR_LOAD_NOT_FOUND"
        assert body["data"]["message"]

        malformed = api.get_load("not-a-uuid", headers)
        assert malformed.status_code == 404, malformed.text
        assert malformed.json()["data"]["error_id"] == "ERR_LOAD_NOT_FOUND"

    def test_a_workflow_endpoint_on_an_unknown_load_reports_the_same_error(self):
        """PRD section 2.6: "Upstream identifiers are also resolved before any
        request-body identifier, and creation requests validate the parent context
        before any business rule is evaluated."

        Design: Corner/entities/load_get_for_an_unallocated_id_returns_load_not_found
        """
        board = setup_board(units=1)
        set_clock("2026-09-20T00:00:00Z")
        response = api.post_load(NON_EXISTENT_UUID, make_shipper_headers(board["shipper_id"]))
        assert response.status_code == 404, response.text
        assert response.json()["data"]["error_id"] == "ERR_LOAD_NOT_FOUND"


class TestBreachTolerance:
    """The breach comparison is strictly greater than the tolerance."""

    def test_a_pickup_at_exactly_thirty_minutes_late_is_on_time(self):
        """PRD section 3.6: "if `actual_pickup_at` is still null the load is not in
        breach, otherwise the load is in breach exactly when the elapsed time from
        `pickup_window_end` to `actual_pickup_at` is strictly more than 30 minutes."

        Design: Corner/state_machines/pickup_breach_at_exactly_thirty_minutes_late_is_not_a_breach
        """
        board = setup_board(units=2)
        set_clock("2026-10-05T00:00:00Z")
        window = ("2026-10-05T08:00:00Z", "2026-10-05T12:00:00Z")
        on_edge, edge_quote = _posted(board, window)
        late, late_quote = _posted(board, window)
        _book(board, on_edge, edge_quote, board["equipment"][0]["id"])
        _book(board, late, late_quote, board["equipment"][1]["id"])

        set_clock("2026-10-05T12:00:00Z")
        for load_id in (on_edge["id"], late["id"]):
            api.report_tracking_ping(
                load_id,
                {"carrier_id": board["carrier_id"], "sequence": 1,
                 "reported_status": "EN_ROUTE_PICKUP", "location_code": "9vg81"},
                make_carrier_headers(board["carrier_id"]))

        set_clock("2026-10-05T12:30:00Z")
        on_time = api.report_tracking_ping(
            on_edge["id"],
            {"carrier_id": board["carrier_id"], "sequence": 2,
             "reported_status": "AT_PICKUP", "location_code": "9vg82"},
            make_carrier_headers(board["carrier_id"]))
        assert on_time.status_code == 201, on_time.text

        set_clock("2026-10-05T12:31:00Z")
        breached = api.report_tracking_ping(
            late["id"],
            {"carrier_id": board["carrier_id"], "sequence": 2,
             "reported_status": "AT_PICKUP", "location_code": "9vg82"},
            make_carrier_headers(board["carrier_id"]))
        assert breached.status_code == 201, breached.text

        on_edge_load = read_load(board["shipper_id"], on_edge["id"])
        late_load = read_load(board["shipper_id"], late["id"])
        assert on_edge_load["pickup_breach_flag"] is False
        assert on_edge_load["actual_pickup_at"] == iso3("2026-10-05T12:30:00Z")
        assert late_load["pickup_breach_flag"] is True
        assert late_load["actual_pickup_at"] == iso3("2026-10-05T12:31:00Z")

        carrier = read_carrier(board["carrier_id"])
        assert carrier["operational_risk_score"] == 92.0
        assert carrier["operational_risk_score"] != 84.0

    def test_a_load_with_no_arrival_ping_is_never_in_breach(self):
        """PRD section 3.6: "The first is the breach determination, and it can only be made once the load has actually been picked up: if `actual_pickup_at` is still null the load is not in breach, otherwise the load is in breach exactly when the elapsed time from `pickup_window_end` to `actual_pickup_at` is strictly more than 30 minutes."

        Design: Corner/state_machines/pickup_breach_at_exactly_thirty_minutes_late_is_not_a_breach
        """
        board = setup_board(units=1)
        set_clock("2026-10-05T00:00:00Z")
        load, quote = _posted(board)
        _book(board, load, quote, board["equipment"][0]["id"])
        refreshed = read_load(board["shipper_id"], load["id"])
        assert refreshed["actual_pickup_at"] is None
        assert refreshed["pickup_breach_flag"] is False


class TestWaiveBoundary:
    """A waived event leaves the aggregate, but its closed sibling does not."""

    def test_a_closed_event_still_bills_after_a_sibling_is_waived(self):
        """PRD section 2.9: "The accessorial total itself is the sum of the load's
        detention charges over its `OPEN` and `CLOSED` detention events.  A `WAIVED`
        event contributes nothing, even though the charge it once carried remains
        visible on the row for audit."

        Design: Corner/cross_cutting_complexity_layers/accessorial_total_reconciles_down_when_a_detention_charge_is_waived
        """
        board = setup_board(units=1)
        set_clock("2026-10-05T00:00:00Z")
        window = ("2026-10-05T08:00:00Z", "2026-10-05T12:00:00Z")
        load, quote = _posted(board, window)
        _book(board, load, quote, board["equipment"][0]["id"])

        # Pickup dwell of 250 minutes bills two whole hours; the delivery dwell of
        # 310 minutes bills four.
        set_clock("2026-10-05T07:30:00Z")
        api.report_tracking_ping(
            load["id"],
            {"carrier_id": board["carrier_id"], "sequence": 1,
             "reported_status": "EN_ROUTE_PICKUP", "location_code": "9vg81"},
            make_carrier_headers(board["carrier_id"]))
        set_clock("2026-10-05T08:00:00Z")
        api.report_tracking_ping(
            load["id"],
            {"carrier_id": board["carrier_id"], "sequence": 2,
             "reported_status": "AT_PICKUP", "location_code": "9vg82"},
            make_carrier_headers(board["carrier_id"]))
        set_clock("2026-10-05T12:00:00Z")
        api.report_tracking_ping(
            load["id"],
            {"carrier_id": board["carrier_id"], "sequence": 3,
             "reported_status": "IN_TRANSIT", "location_code": "9vg83",
             "eta_utc": "2026-10-07T16:00:00Z"},
            make_carrier_headers(board["carrier_id"]))
        set_clock("2026-10-06T08:00:00Z")
        api.report_tracking_ping(
            load["id"],
            {"carrier_id": board["carrier_id"], "sequence": 4,
             "reported_status": "AT_DELIVERY", "location_code": "9vg84",
             "eta_utc": "2026-10-07T16:00:00Z"},
            make_carrier_headers(board["carrier_id"]))
        set_clock("2026-10-06T13:10:00Z")
        api.report_tracking_ping(
            load["id"],
            {"carrier_id": board["carrier_id"], "sequence": 5,
             "reported_status": "DELIVERED", "location_code": "9vg85"},
            make_carrier_headers(board["carrier_id"]))

        before = api.list_load_detention_events(
            load["id"], make_shipper_headers(board["shipper_id"])).json()["data"]
        charges = sorted(event["detention_charge_cents"] for event in before)
        assert charges == [15000, 30000], f"unexpected detention charges {charges}"
        load_before = read_load(board["shipper_id"], load["id"])
        assert load_before["accessorial_total_cents"] == 45000

        delivery_event = [event for event in before
                          if event["detention_charge_cents"] == 30000][0]
        waived = api.waive_detention_event(delivery_event["id"], "FACILITY_FAULT",
                                           make_platform_admin_headers())
        assert waived.status_code == 200, waived.text

        after = read_load(board["shipper_id"], load["id"])
        assert after["accessorial_total_cents"] == 15000
        assert after["accessorial_total_cents"] != 0
        assert after["accessorial_total_cents"] != 45000

        waived_row = api.get_detention_event(
            delivery_event["id"], make_platform_admin_headers()).json()["data"]
        assert waived_row["status"] == "WAIVED"
        assert waived_row["detention_charge_cents"] == 0
        survivor = [event for event in before
                    if event["id"] != delivery_event["id"]][0]
        survivor_row = api.get_detention_event(
            survivor["id"], make_platform_admin_headers()).json()["data"]
        assert survivor_row["status"] == "CLOSED"
        assert survivor_row["detention_charge_cents"] == 15000
