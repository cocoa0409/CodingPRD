"""Opening the floor: venue, party, tier, grill table and chef creation, plus the
listing envelope and the request-format rules that guard them.
"""
from test_helpers import (
    ApiErrorId,
    api_client,
    get_success_data,
    is_valid_uuid,
    validate_error,
    validate_paginated,
    validate_success,
)
from test_helpers.factories import create_party_payload, create_table_payload
from test_helpers.fixtures import (
    DEFAULT_CLOCK,
    EMPTY_UUID,
    HOST,
    PA,
    FM,
    create_party,
    minimal_floor,
    set_clock,
    setup_floor,
)


class TestVenueCreation:

    def test_venue_create_returns_server_initialised_floor_state(self):
        """PRD §3.1: "A `PlatformAdmin` opens a venue by supplying `venue_name`,
        `city_code` and `ventilation_zone`; `filter_service_threshold_index` may be
        supplied and otherwise defaults to 40. The new `Venue` row starts `ACTIVE`,
        with `occupancy_freeze` false, `hood_filter_life_index` at 0 and `ops_epoch`
        at 0."
        PRD §2.4: "`version` is an integer that starts at its initial value and
        increments by exactly one on every mutation of the row."

        Design: Corner/entities/venue_create_returns_envelope_and_server_initialised_floor_state
        """
        set_clock(DEFAULT_CLOCK)
        response = api_client.create_venue(
            {"venue_name": "Riverside Teppan House", "city_code": "CHI",
             "ventilation_zone": "ZONE_C", "filter_service_threshold_index": 45}, PA)
        data = validate_success(response, expected_status=201)

        assert response.json()["response_type"] == "object"
        assert data["venue_name"] == "Riverside Teppan House"
        assert data["city_code"] == "CHI"
        assert data["ventilation_zone"] == "ZONE_C"
        assert data["filter_service_threshold_index"] == 45
        assert data["status"] == "ACTIVE"
        assert data["occupancy_freeze"] is False
        assert data["hood_filter_life_index"] == 0
        assert data["ops_epoch"] == 0
        assert data["version"] == 1
        assert is_valid_uuid(data["id"])
        assert data["created_at"] and data["updated_at"]
        assert response.json()["meta"]["api_request_id"].startswith("req_")

    def test_venue_create_omitting_the_threshold_defaults_it_to_forty(self):
        """PRD §3.1: "`filter_service_threshold_index` may be supplied and otherwise
        defaults to 40."
        PRD §2.5: "`filter_service_threshold_index`, the index at which the bank must
        be taken out of service; it is supplied when the venue is opened and defaults
        to 40."

        Design: Corner/entities/venue_create_omitting_the_threshold_defaults_it_to_forty
        """
        set_clock(DEFAULT_CLOCK)
        data = get_success_data(api_client.create_venue(
            {"venue_name": "Default Threshold Grill", "city_code": "SEA",
             "ventilation_zone": "ZONE_B"}, PA))

        assert data["filter_service_threshold_index"] == 40
        assert data["filter_service_threshold_index"] is not None
        assert data["hood_filter_life_index"] == 0
        assert data["hood_filter_life_index"] < data["filter_service_threshold_index"]


class TestPartyRetrieval:

    def test_party_get_round_trips_every_declared_field_unchanged(self):
        """PRD §3.2: "A `Host` registers a `Party` with its `venue_id`, the
        `lead_guest_name`, the `contact_phone`, and optionally a `loyalty_tier`. The
        tier is one of `NONE`, `SILVER`, `GOLD` or `PLATINUM` and defaults to `NONE`.
        A new party starts `ACTIVE` with `no_show_count` and `loyalty_credit_cents`
        both at 0."

        Design: Corner/entities/party_get_round_trips_every_declared_field_unchanged
        """
        scenario = minimal_floor()
        party = get_success_data(api_client.create_party(
            {"venue_id": scenario["venue"]["id"], "lead_guest_name": "Rue Calloway",
             "contact_phone": "212-555-0111"}, HOST))
        response = api_client.get_party(party["id"], HOST)
        data = validate_success(response)

        assert response.json()["response_type"] == "object"
        assert data["lead_guest_name"] == "Rue Calloway"
        assert data["contact_phone"] == "212-555-0111"
        assert data["loyalty_tier"] == "NONE"
        assert data["status"] == "ACTIVE"
        assert data["no_show_count"] == 0
        assert data["loyalty_credit_cents"] == 0
        assert data["venue_id"] == scenario["venue"]["id"]

    def test_party_create_with_an_unknown_venue_returns_venue_not_found(self):
        """PRD §2.10: "Every id in the path and every foreign key in the body must
        resolve before any business rule is evaluated. The first unresolvable segment
        determines the error returned, and the sibling returned always corresponds to
        that segment: `ERR_VENUE_NOT_FOUND` ... each carrying HTTP 404."

        Design: Corner/entities/party_create_with_an_unknown_venue_returns_venue_not_found
        """
        set_clock(DEFAULT_CLOCK)
        response = api_client.create_party(create_party_payload(
            "00000000-0000-4000-8000-000000000009"), HOST)
        validate_error(response, ApiErrorId.ERR_VENUE_NOT_FOUND)

        listed = get_success_data(api_client.list_parties(HOST))
        assert listed == []


class TestRequestFormat:

    def test_reservation_create_omitting_scheduled_time_returns_invalid_request(self):
        """PRD §3.2: "Drafting a booking requires a `venue_id`, a `party_id`, a
        `tier_id`, a `party_size`, a `scheduled_time`, and a `payment_mode` drawn from
        `CARD_ONLY`, `CARD_THEN_CREDIT` or `CREDIT_ONLY`."
        PRD §5: "`ERR_INVALID_REQUEST` | 400 Bad Request"

        Design: Corner/entities/reservation_create_omitting_scheduled_time_returns_invalid_request
        """
        scenario = setup_floor(tier_codes=("T4",), tables=(), chefs=())
        party = create_party(scenario, loyalty_tier="GOLD", name="Owen Marsh",
                             phone="212-555-0177")
        response = api_client.create_reservation(
            {"venue_id": scenario["venue"]["id"], "party_id": party["id"],
             "tier_id": scenario["tiers"]["T4"]["id"], "party_size": 4,
             "payment_mode": "CARD_ONLY"}, HOST)
        validate_error(response, ApiErrorId.ERR_INVALID_REQUEST)

        listed = get_success_data(api_client.list_reservations(HOST, {"party_id": party["id"]}))
        assert listed == []

    def test_party_create_with_an_out_of_enum_loyalty_tier_returns_invalid_request(self):
        """PRD §3.2: "The tier is one of `NONE`, `SILVER`, `GOLD` or `PLATINUM` and
        defaults to `NONE`."
        PRD §2.1: "Every request must carry two headers." (the format check runs before
        any business rule)

        Design: Corner/entities/party_create_with_an_out_of_enum_loyalty_tier_returns_invalid_request
        """
        scenario = minimal_floor()
        response = api_client.create_party(
            {"venue_id": scenario["venue"]["id"], "lead_guest_name": "Nia Frost",
             "contact_phone": "212-555-0132", "loyalty_tier": "DIAMOND"}, HOST)
        validate_error(response, ApiErrorId.ERR_INVALID_REQUEST)

        listed = get_success_data(api_client.list_parties(HOST, {"venue_id": scenario["venue"]["id"]}))
        assert listed == []


class TestTierAndTableCreation:

    def test_tier_get_with_an_unknown_id_returns_tier_not_found(self):
        """PRD §2.10: "The first unresolvable segment determines the error returned,
        and the sibling returned always corresponds to that segment:
        `ERR_VENUE_NOT_FOUND`, `ERR_PARTY_NOT_FOUND`, `ERR_TIER_NOT_FOUND` ... each
        carrying HTTP 404."

        Design: Corner/entities/tier_get_with_an_unknown_id_returns_tier_not_found
        """
        set_clock(DEFAULT_CLOCK)
        response = api_client.get_tier(EMPTY_UUID, PA)
        body = validate_error(response, ApiErrorId.ERR_TIER_NOT_FOUND)

        assert body["error_id"] == "ERR_TIER_NOT_FOUND"
        assert isinstance(body["message"], str) and body["message"]

    def test_grill_table_create_ignores_client_supplied_status_and_guest_counter(self):
        """PRD §3.1: "Each `GrillTable` is created with its `venue_id`, the
        `tier_code` it was built to, and its physical `seat_capacity`, and starts
        `AVAILABLE` with `pending_turn` false and `guests_seated` at 0."

        Design: Corner/entities/grill_table_create_ignores_client_supplied_status_and_guest_counter
        """
        scenario = minimal_floor()
        response = api_client.create_table(create_table_payload(
            scenario["venue"]["id"], tier_code="T6", seat_capacity=6), FM)
        data = validate_success(response, expected_status=201)

        assert data["status"] == "AVAILABLE"
        assert data["guests_seated"] == 0
        assert data["pending_turn"] is False
        assert data["maintenance_resume_at"] is None
        assert data["version"] == 1


class TestReservationMoneySlots:

    def test_reservation_get_returns_stored_state_and_never_the_quote_as_the_bill(self):
        """PRD §3.2: "The booking begins in `DRAFT` with `hold_count` at 0, and a
        provisional quote is stamped into `quote_final_cents` immediately. That
        provisional figure is the quote variant of the settlement rule, in which the
        celebration fee term is dropped and the booking is priced as the smaller of
        the tier's capacity-derived ceiling and the party's entitlement."

        Design: Corner/entities/reservation_get_returns_stored_state_and_never_the_quote_as_the_bill
        """
        scenario = setup_floor(tier_codes=("T4",), tables=(), chefs=())
        party = create_party(scenario, loyalty_tier="GOLD", name="Owen Marsh",
                             phone="212-555-0177")
        reservation = get_success_data(api_client.create_reservation(
            {"venue_id": scenario["venue"]["id"], "party_id": party["id"],
             "tier_id": scenario["tiers"]["T4"]["id"], "party_size": 4,
             "scheduled_time": "2026-09-03T19:00:00Z", "payment_mode": "CARD_ONLY",
             "celebration": "NONE"}, HOST))

        data = validate_success(api_client.get_reservation(reservation["id"], HOST))
        assert data["status"] == "DRAFT"
        assert data["hold_count"] == 0
        assert data["quote_final_cents"] == 12800
        assert data["final_bill_cents"] == 0
        assert data["check_cents"] == 0
        assert data["seat_surcharge_cents"] == 0
        assert data["credit_applied_cents"] == 0
        assert data["celebration_fee_cents"] == 0
        assert data["table_id"] is None
        assert data["hold_until"] is None


class TestListing:

    def test_venue_list_paginates_with_total_count_and_has_more(self):
        """PRD §2.3: "The `limit` parameter caps how many items a single page returns;
        it defaults to 10, and its smallest permitted value is 1 while its largest is
        100. The `offset` parameter says how many items to skip from the front of the
        result and defaults to 0."
        PRD §2.3: "Recognised `limit` and `offset` values are echoed, together with
        `total_count` and `has_more`, into the `meta` object of the response envelope
        whenever a list is returned."

        Design: Corner/entities/venue_list_paginates_with_total_count_and_has_more
        """
        set_clock(DEFAULT_CLOCK)
        api_client.create_venue({"venue_name": "Midtown Iron Grill", "city_code": "NYC",
                                 "ventilation_zone": "ZONE_A",
                                 "filter_service_threshold_index": 40}, PA)
        api_client.create_venue({"venue_name": "Lakeview Teppan", "city_code": "CHI",
                                 "ventilation_zone": "ZONE_B"}, PA)
        api_client.create_venue({"venue_name": "Harbour Teppan", "city_code": "SEA",
                                 "ventilation_zone": "ZONE_D"}, PA)

        first, meta = validate_paginated(api_client.list_venues(PA, {"limit": 2, "offset": 0}))
        assert len(first) == 2
        assert meta["total_count"] == 3
        assert meta["has_more"] is True
        assert meta["limit"] == 2
        assert meta["offset"] == 0

        second, meta2 = validate_paginated(api_client.list_venues(PA, {"limit": 2, "offset": 2}))
        assert len(second) == 1
        assert meta2["total_count"] == 3
        assert meta2["has_more"] is False

        by_city, _ = validate_paginated(api_client.list_venues(PA, {"city_code": "CHI"}))
        assert len(by_city) == 1
        assert by_city[0]["venue_name"] == "Lakeview Teppan"

        default_page, default_meta = validate_paginated(api_client.list_venues(PA))
        assert len(default_page) == 3
        assert default_meta["limit"] == 10
        assert default_meta["offset"] == 0