"""State-machine boundaries, resource shape, and the OCC and credit guards."""
from test_helpers import (
    api_client as api,
    make_carrier_headers,
    make_platform_admin_headers,
    make_shipper_headers,
    NON_EXISTENT_UUID,
    read_load,
    set_clock,
    setup_board,
    setup_two_quotes_on_one_load,
)


def _raw_load(board, window=("2026-10-05T08:00:00Z", "2026-10-05T12:00:00Z"), **overrides):
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
    return payload


class TestRegistrationShape:
    """A fresh resource comes back with its system-managed fields populated."""

    def test_a_new_shipper_comes_back_active_with_zeroed_ledgers(self):
        """PRD section 2.8: "A freshly registered shipper starts `ACTIVE` with
        `credit_used_cents`, `load_credits_committed`, and `breached_pickup_count`
        all at zero, an empty `blocked_carrier_ids` list, and `last_repriced_lane`
        null until a quote on one of its lanes is first repriced."

        Design: Corner/entities/shipper_create_returns_every_declared_field_and_starts_active
        """
        set_clock("2026-09-20T00:00:00Z")
        response = api.create_shipper(
            {"name": "Gulf Fabricators LLC", "billing_state_code": "TX",
             "payment_terms_days": 30, "quick_pay_discount_pct": 0.03,
             "credit_limit_cents": 20000000, "load_credit_limit": 10},
            make_platform_admin_headers())
        assert response.status_code == 201, response.text
        body = response.json()
        assert body["response_type"] == "object"
        shipper = body["data"]

        assert shipper["status"] == "ACTIVE"
        assert shipper["version"] == 1
        assert shipper["credit_used_cents"] == 0
        assert shipper["credit_limit_cents"] == 20000000
        assert shipper["credit_available_cents"] == 20000000
        assert shipper["load_credits_committed"] == 0
        assert shipper["load_credits_available"] == 10
        assert shipper["breached_pickup_count"] == 0
        assert shipper["blocked_carrier_ids"] == []
        assert shipper["last_repriced_lane"] is None
        assert shipper["payment_terms_days"] == 30

    def test_a_facility_stores_its_two_documented_defaults(self):
        """PRD section 3.5: "Facilities are registered with a `dock_capacity`, a
        `state_code`, a `default_appointment_minutes` that defaults to 60, a
        `free_dwell_minutes` that defaults to 120, and a
        `detention_rate_per_hour_cents`."

        Design: Corner/entities/facility_create_applies_its_two_field_defaults
        """
        set_clock("2026-09-20T00:00:00Z")
        response = api.create_facility(
            {"name": "Gulf Fabricators Houston", "state_code": "TX",
             "dock_capacity": 3, "detention_rate_per_hour_cents": 7500},
            make_platform_admin_headers())
        assert response.status_code == 201, response.text
        facility = response.json()["data"]
        assert facility["default_appointment_minutes"] == 60
        assert facility["free_dwell_minutes"] == 120
        assert facility["docks_committed_today"] == 0
        assert facility["status"] == "ACTIVE"
        assert facility["default_appointment_minutes"] != 0
        assert facility["free_dwell_minutes"] != 0


class TestClosedEnums:
    """Enums are closed sets, rejected before any downstream work."""

    def test_an_unknown_market_band_is_a_malformed_request(self):
        """PRD section 3.2: "a `weight_lbs` below 1, a malformed body, an unknown
        enum member, or a missing required field is refused with
        `ERR_INVALID_REQUEST` (HTTP 400)."

        Design: Corner/entities/load_create_with_an_out_of_enum_market_band_returns_invalid_request
        """
        board = setup_board(units=1)
        set_clock("2026-09-20T00:00:00Z")
        rejected = api.create_load(
            _raw_load(board, market_band="HOT"), make_shipper_headers(board["shipper_id"]))
        assert rejected.status_code == 400, rejected.text
        assert rejected.json()["data"]["error_id"] == "ERR_INVALID_REQUEST"

        loads = api.list_loads(make_shipper_headers(board["shipper_id"]),
                               {"shipper_id": board["shipper_id"]})
        assert loads.json()["data"] == []
        shipper = api.get_shipper(
            board["shipper_id"], make_shipper_headers(board["shipper_id"])).json()["data"]
        assert shipper["load_credits_committed"] == 0


class TestAppendOnlyRecords:
    """Tracking pings and status events carry no mutable bookkeeping fields."""

    def test_a_ping_reports_its_own_progression_and_carries_no_version(self):
        """PRD section 3.6: "`recorded_at` is stamped at receipt and `status_rank`
        is computed from the reported status."

        Design: Corner/entities/tracking_ping_is_created_with_only_the_fields_the_endpoint_declares
        """
        board = setup_board(units=1)
        set_clock("2026-10-05T00:00:00Z")
        load = _booked(board)
        first = api.report_tracking_ping(
            load["id"],
            {"carrier_id": board["carrier_id"], "sequence": 1,
             "reported_status": "EN_ROUTE_PICKUP", "location_code": "9vg81"},
            make_carrier_headers(board["carrier_id"]))
        assert first.status_code == 201, first.text

        second = api.report_tracking_ping(
            load["id"],
            {"carrier_id": board["carrier_id"], "sequence": 2,
             "reported_status": "AT_PICKUP", "location_code": "9vg82"},
            make_carrier_headers(board["carrier_id"]))
        assert second.status_code == 201, second.text
        body = second.json()
        assert body["response_type"] == "object"
        ping = body["data"]
        assert ping["sequence"] == 2
        assert ping["status_rank"] == 2
        assert ping["reported_status"] == "AT_PICKUP"
        assert "id" in ping and "created_at" in ping
        assert "updated_at" not in ping, "an append-only ping has no updated_at"
        assert "version" not in ping, "an append-only ping has no version"
        assert ping["recorded_at"] is not None

        refreshed = read_load(board["shipper_id"], load["id"])
        assert refreshed["tracking_status_rank"] == 2

    def test_a_shipper_authored_note_is_stamped_with_its_portal_source(self):
        """PRD section 3.6: "the server derives `source` from the acting role,
        stamping `SHIPPER_PORTAL` when a shipper authors the note and `DRIVER_APP`
        when a carrier does."

        Design: Corner/entities/status_event_append_stamps_its_source_from_the_acting_role
        """
        board = setup_board(units=1)
        set_clock("2026-10-05T00:00:00Z")
        load = _booked(board)
        appended = api.append_status_event(
            {"load_id": load["id"], "event_type": "EXCEPTION",
             "note": "Customer requested a call-ahead"},
            make_shipper_headers(board["shipper_id"]))
        assert appended.status_code == 201, appended.text
        event = appended.json()["data"]
        assert event["source"] == "SHIPPER_PORTAL"
        assert event["source"] is not None
        assert event["occurred_at"] is not None

        events = api.list_load_status_events(
            load["id"], make_shipper_headers(board["shipper_id"])).json()["data"]
        appended_events = [event for event in events if event["event_type"] == "EXCEPTION"]
        assert len(appended_events) == 1
        assert {event["event_type"] for event in events} >= {"BOOKED", "EXCEPTION"}
        assert appended_events[0]["source"] == "SHIPPER_PORTAL"


class TestResponseEnvelope:
    """The success and error envelopes are shaped differently."""

    def test_success_meta_carries_a_request_id_and_timestamp(self):
        """PRD section 2.2: "The `api_request_id` is a server-generated unique
        identifier for the request that starts with `req_`."

        Design: Corner/entities/envelope_success_meta_carries_request_id_and_timestamp
        """
        set_clock("2026-09-20T00:00:00Z")
        first = api.create_shipper(
            {"name": "Gulf Fabricators LLC", "billing_state_code": "TX",
             "payment_terms_days": 30, "quick_pay_discount_pct": 0.03,
             "credit_limit_cents": 20000000, "load_credit_limit": 10},
            make_platform_admin_headers())
        assert first.status_code == 201
        body = first.json()
        assert body["response_type"] == "object"
        assert body["response_type"] != "array"
        assert isinstance(body["meta"]["api_request_id"], str)
        assert body["meta"]["api_request_id"].startswith("req_")
        assert isinstance(body["meta"]["api_request_timestamp"], str)
        assert body["meta"]["api_request_timestamp"]

        second = api.create_shipper(
            {"name": "Second Freight Buyer", "billing_state_code": "CA",
             "payment_terms_days": 15, "quick_pay_discount_pct": 0.02,
             "credit_limit_cents": 5000000, "load_credit_limit": 3},
            make_platform_admin_headers())
        assert second.status_code == 201
        assert second.json()["meta"]["api_request_id"] != body["meta"]["api_request_id"]

    def test_an_error_body_carries_only_the_error_identifier_and_message(self):
        """PRD section 2.2: "The `meta` object for error responses contains only
        `api_request_id` and `api_request_timestamp`."
        PRD section 2.2: "The `error_id` is a unique, machine-readable string that
        identifies the specific error."

        Design: Corner/entities/envelope_error_body_carries_error_id_and_message_and_no_data_payload
        """
        board = setup_board(units=1)
        set_clock("2026-09-20T00:00:00Z")
        response = api.get_load(NON_EXISTENT_UUID, make_shipper_headers(board["shipper_id"]))
        assert response.status_code == 404, response.text
        body = response.json()
        assert body["response_type"] == "error"
        assert body["data"]["error_id"] == "ERR_LOAD_NOT_FOUND"
        assert isinstance(body["data"]["message"], str)
        assert body["data"]["message"]
        assert "status" not in body["data"]
        assert "carrier_id" not in body["data"]
        assert body["meta"]["api_request_id"]
        assert body["meta"]["api_request_timestamp"]


class TestPostingCreditGuard:
    """The posting-credit guard trips at the limit, not above it."""

    def test_the_third_post_at_a_limit_of_two_is_refused(self):
        """PRD section 2.8: "Posting a load when the committed count already equals
        the limit is refused with `ERR_LOAD_CREDIT_EXHAUSTED` (HTTP 409)."

        Design: Corner/cross_cutting_complexity_layers/posting_a_third_load_is_refused_at_exactly_the_load_credit_limit
        """
        board = setup_board(units=1, shipper_overrides={"load_credit_limit": 2})
        set_clock("2026-09-20T00:00:00Z")
        headers = make_shipper_headers(board["shipper_id"])
        loads = []
        for index in range(3):
            created = api.create_load(
                _raw_load(board, window=(f"2026-10-{5 + index:02d}T08:00:00Z",
                                         f"2026-10-{5 + index:02d}T12:00:00Z")),
                headers)
            assert created.status_code == 201, created.text
            loads.append(created.json()["data"]["id"])
        for load_id in loads[:2]:
            assert api.post_load(load_id, headers).status_code == 200

        shipper = api.get_shipper(board["shipper_id"], headers).json()["data"]
        assert shipper["load_credits_committed"] == 2
        assert shipper["load_credits_available"] == 0

        refused = api.post_load(loads[2], headers)
        assert refused.status_code == 409, refused.text
        assert refused.json()["data"]["error_id"] == "ERR_LOAD_CREDIT_EXHAUSTED"

    def test_cancelling_a_posted_load_frees_exactly_one_credit(self):
        """PRD section 2.8: "The credit is released only when the load is cancelled
        or voided."

        Design: Corner/cross_cutting_complexity_layers/posting_a_third_load_is_refused_at_exactly_the_load_credit_limit
        """
        board = setup_board(units=1, shipper_overrides={"load_credit_limit": 2})
        set_clock("2026-09-20T00:00:00Z")
        headers = make_shipper_headers(board["shipper_id"])
        loads = []
        for index in range(3):
            created = api.create_load(
                _raw_load(board, window=(f"2026-10-{5 + index:02d}T08:00:00Z",
                                         f"2026-10-{5 + index:02d}T12:00:00Z")),
                headers)
            loads.append(created.json()["data"]["id"])
        for load_id in loads[:2]:
            api.post_load(load_id, headers)

        cancelled = api.cancel_load(loads[0], headers)
        assert cancelled.status_code == 200, cancelled.text
        assert cancelled.json()["data"]["status"] == "CANCELLED"
        shipper = api.get_shipper(board["shipper_id"], headers).json()["data"]
        assert shipper["load_credits_available"] == 1

        posted = api.post_load(loads[2], headers)
        assert posted.status_code == 200, posted.text
        assert posted.json()["data"]["status"] == "POSTED"


class TestOptimisticConcurrency:
    """A stale expected version is refused before any pricing work."""

    def test_a_reprice_invalidates_a_previously_observed_load_version(self):
        """PRD section 2.7: "Each guarded write must carry an expected-version field naming the parent it is guarded against, and that field is required, not optional. Creating a booking must carry `expected_load_version`, the booking client's last-observed `version` of the target load."
        PRD section 2.7: "If the load's version has advanced since the client read it —
        because the shipper cancelled the load, or because another carrier
        booked it first — the create is refused with `ERR_STALE_VERSION`
        (HTTP 412)."

        Design: Corner/cross_cutting_complexity_layers/booking_is_rejected_when_the_load_version_went_stale_after_a_reprice
        """
        board = setup_two_quotes_on_one_load()
        load = board["load"]
        stale_version = load["version"]
        quote = board["active_quote"]

        repriced = api.reprice_load(load["id"], "TIGHT", make_platform_admin_headers())
        assert repriced.status_code == 200, repriced.text
        assert repriced.json()["data"]["version"] != stale_version

        refused = api.create_booking(
            {"load_id": load["id"], "carrier_id": board["carrier_id"],
             "rate_quote_id": quote["id"], "equipment_id": board["equipment"][0]["id"],
             "expected_load_version": stale_version},
            make_carrier_headers(board["carrier_id"]))
        assert refused.status_code == 412, refused.text
        assert refused.json()["data"]["error_id"] == "ERR_STALE_VERSION"

    def test_the_current_version_still_books_after_the_reprice(self):
        """PRD section 2.7: "A claim approval or a detention close legitimately re-strikes the settlement's deduction and accessorial lines in place, so a stale expected version must never be able to pay the pre-recompute amount; the payout is refused with `ERR_STALE_VERSION` (HTTP 412). These four are the only guarded writes."

        Design: Corner/cross_cutting_complexity_layers/booking_is_rejected_when_the_load_version_went_stale_after_a_reprice
        """
        board = setup_two_quotes_on_one_load()
        load = board["load"]
        quote = board["active_quote"]
        repriced = api.reprice_load(load["id"], "TIGHT", make_platform_admin_headers())
        assert repriced.status_code == 200, repriced.text

        accepted = api.create_booking(
            {"load_id": load["id"], "carrier_id": board["carrier_id"],
             "rate_quote_id": quote["id"], "equipment_id": board["equipment"][0]["id"],
             "expected_load_version": repriced.json()["data"]["version"]},
            make_carrier_headers(board["carrier_id"]))
        assert accepted.status_code == 201, accepted.text

        refreshed = read_load(board["shipper_id"], load["id"])
        assert refreshed["status"] == "BOOKED"
        assert refreshed["carrier_id"] == board["carrier_id"]


def _booked(board):
    created = api.create_load(
        _raw_load(board), make_shipper_headers(board["shipper_id"]))
    assert created.status_code == 201, created.text
    load_id = created.json()["data"]["id"]
    posted = api.post_load(load_id, make_shipper_headers(board["shipper_id"]))
    assert posted.status_code == 200, posted.text
    quote = api.list_load_rate_quotes(
        load_id, make_shipper_headers(board["shipper_id"])).json()["data"][-1]
    booked = api.create_booking(
        {"load_id": load_id, "carrier_id": board["carrier_id"],
         "rate_quote_id": quote["id"], "equipment_id": board["equipment"][0]["id"],
         "expected_load_version": posted.json()["data"]["version"]},
        make_carrier_headers(board["carrier_id"]))
    assert booked.status_code == 201, booked.text
    return read_load(board["shipper_id"], load_id)