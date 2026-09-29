"""Board reference data and the dealership record: envelopes, declared
defaults, the listing contract, request validity and the two 404 catalogues.
"""
from prd_bench_local_runner.testing import (
    NON_EXISTENT_UUID,
    get_success_data,
    is_iso8601_timestamp,
    is_valid_uuid,
    validate_error,
    validate_paginated,
    validate_success,
)
from test_helpers import factories as f
from test_helpers import fixtures as fx
from test_helpers.api_errors import ApiErrorId
from test_helpers.assertions import (
    assert_append_only_record,
    assert_list_meta,
    assert_versioned_record,
)
from test_helpers.test_users import BOARD_ADMIN, LICENSING_ANALYST, make_dealer_headers


class TestFranchisorRegistration:
    def test_registration_returns_the_envelope_with_every_declared_default(self, api):
        """PRD 3.1: "Registration standing may be supplied as
        `state_registration_status`, which is either `REGISTERED` or `LAPSED` and
        defaults to `REGISTERED` when omitted." PRD 3.1: "`open_dispute_count`,
        the number of that franchisor's warranty rate disputes still in `FILED` or
        `UNDER_REVIEW`, and `active_filing_count`, the number of its franchise
        filings still in `NOTICE_SERVED` or `PROTEST_PENDING`. Both start at 0."
        PRD 2.4 fixes the opening version: "`version`, an integer that starts at 1
        when the record is created and increases by exactly 1 on every mutation of
        that record."

        Design: Corner/entities/manufacturer_creation_returns_envelope_and_defaults
        """
        response = api.create_manufacturer(
            f.manufacturer_payload(legal_name="Aurora Motors NA", line_make="AURORA",
                                   home_office_state="MI",
                                   posted_warranty_labor_rate_cents=6000),
            BOARD_ADMIN)
        manufacturer = validate_success(response, 201)

        body = response.json()
        assert body["response_type"] == "object"
        assert body["meta"]["api_request_id"].startswith("req_")
        assert is_iso8601_timestamp(body["meta"]["api_request_timestamp"])

        assert manufacturer["legal_name"] == "Aurora Motors NA"
        assert manufacturer["line_make"] == "AURORA"
        assert manufacturer["home_office_state"] == "MI"
        assert manufacturer["posted_warranty_labor_rate_cents"] == 6000
        assert manufacturer["state_registration_status"] == "REGISTERED"
        assert manufacturer["open_dispute_count"] == 0
        assert manufacturer["active_filing_count"] == 0
        assert manufacturer["version"] == 1
        assert_versioned_record(manufacturer)

    def test_a_franchisor_without_a_line_make_is_a_malformed_request(self, api):
        """PRD 3.1 makes the line make part of the identity of a registration: "A
        **franchisor** — the manufacturer or distributor of a vehicle line — is
        registered with its `legal_name`, the `line_make` it distributes in the
        state, the `home_office_state` of its head office, and the
        `posted_warranty_labor_rate_cents` it currently posts to its dealers." PRD
        2.10: "**Request validity** — the body parses; every required field is
        present; every enum value is a declared member".

        Design: Corner/entities/manufacturer_missing_required_line_make_rejected
        """
        response = api.create_manufacturer(
            {"legal_name": "Aurora Motors NA", "home_office_state": "MI",
             "posted_warranty_labor_rate_cents": 6000},
            BOARD_ADMIN)
        validate_error(response, ApiErrorId.ERR_INVALID_REQUEST.value, expected_status=400)

        _, meta = validate_paginated(api.list_manufacturers(BOARD_ADMIN))
        assert meta["total_count"] == 0


class TestHearingRoomDefaults:
    def test_the_docket_settings_default_and_may_be_overridden(self, api):
        """PRD 3.1: "`max_hearings_per_day` is the greatest number of protest
        hearings the room may host on one UTC calendar date; it accepts 1 through
        4 and defaults to 2." PRD 3.1: "`buffer_minutes` is the mandatory
        changeover time that must separate two hearings in that room; it accepts 0
        through 240 and defaults to 60." PRD 3.1: "The room also carries
        `booked_hearing_count`, which starts at 0 and is the conserved quantity
        described in §2.11."

        Design: Corner/entities/hearing_room_defaults_applied_when_omitted
        """
        defaulted = get_success_data(api.create_hearing_room(
            {"room_code": "HR-1", "seating_capacity": 60}, BOARD_ADMIN), 201)
        overridden = get_success_data(api.create_hearing_room(
            {"room_code": "HR-2", "seating_capacity": 40,
             "max_hearings_per_day": 3, "buffer_minutes": 30}, BOARD_ADMIN), 201)

        assert defaulted["max_hearings_per_day"] == 2
        assert defaulted["buffer_minutes"] == 60
        assert defaulted["booked_hearing_count"] == 0
        assert overridden["max_hearings_per_day"] == 3
        assert overridden["buffer_minutes"] == 30
        assert overridden["booked_hearing_count"] == 0


class TestDealershipRecord:
    def test_a_fresh_dealership_reads_back_exactly_as_opened(self, api):
        """PRD 3.1: "Every new record begins with `license_status` at
        `PROSPECTIVE`, `franchise_status` at `NONE`, `suspension_reason` at `NONE`,
        `license_effective_on` and `license_expires_on` unset, `disciplinary_points`
        and `restitution_outstanding_cents` and `licensed_salesperson_count` at 0,
        and `approved_warranty_labor_rate_cents` unset until the board approves a
        warranty rate for it."

        Design: Corner/entities/dealer_retrieval_returns_stored_row
        """
        fx.set_clock("2026-09-01T00:00:00Z")
        created = fx.create_dealer(legal_name="Lakeside Aurora", site_x_km=0, site_y_km=0)

        stored = get_success_data(api.get_dealer(created["id"], LICENSING_ANALYST), 200)

        assert stored["id"] == created["id"]
        assert stored["legal_name"] == "Lakeside Aurora"
        assert stored["dealer_type"] == "NEW_MOTOR_VEHICLE"
        assert stored["license_status"] == "PROSPECTIVE"
        assert stored["franchise_status"] == "NONE"
        assert stored["suspension_reason"] == "NONE"
        assert stored["disciplinary_points"] == 0
        assert stored["restitution_outstanding_cents"] == 0
        assert stored["licensed_salesperson_count"] == 0
        assert stored["license_effective_on"] is None
        assert stored["license_expires_on"] is None
        assert stored["approved_warranty_labor_rate_cents"] is None
        assert stored["site_x_km"] == 0
        assert stored["site_y_km"] == 0

    def test_the_server_mints_the_identity_and_the_version(self, api):
        """PRD 2.4: "Every record the service persists carries a server-minted
        `id`, a UUID with no type prefix of any kind, and a `created_at` timestamp
        in ISO 8601 UTC notation with three fractional digits." PRD 2.4: "Most
        records additionally carry `updated_at`, in the same timestamp format, and
        `version`, an integer that starts at 1 when the record is created and
        increases by exactly 1 on every mutation of that record."

        Design: Corner/entities/dealer_system_fields_generated_on_create
        """
        fx.set_clock("2026-09-01T00:00:00Z")

        created = get_success_data(
            api.create_dealer(f.dealer_payload(legal_name="Lakeside Aurora"), BOARD_ADMIN),
            201)

        assert is_valid_uuid(created["id"])
        assert not created["id"].startswith(("dlr", "dealer"))
        assert is_iso8601_timestamp(created["created_at"])
        assert is_iso8601_timestamp(created["updated_at"])
        assert created["version"] == 1
        assert_versioned_record(created)

    def test_an_undeclared_county_tier_is_refused_and_tier_three_is_stored(self, api):
        """PRD 3.1: "its `county_tier`, the population tier of the county
        containing its established place of business, which is one of `TIER_1`,
        `TIER_2` or `TIER_3`." PRD 2.10: "every enum value is a declared member;
        every number lies inside its declared range; every date and datetime is
        ISO-8601". A TIER_4 body is therefore refused with `ERR_INVALID_REQUEST`
        while the declared TIER_3 is accepted.

        Design: Corner/entities/dealer_invalid_enum_county_tier_rejected
        """
        response = api.create_dealer(
            {"legal_name": "Bad Tier Autos", "dealer_type": "NEW_MOTOR_VEHICLE",
             "county_tier": "TIER_4", "site_x_km": 0, "site_y_km": 0},
            BOARD_ADMIN)
        validate_error(response, ApiErrorId.ERR_INVALID_REQUEST.value, expected_status=400)

        accepted = get_success_data(api.create_dealer(
            {"legal_name": "Rural Autos", "dealer_type": "NEW_MOTOR_VEHICLE",
             "county_tier": "TIER_3", "site_x_km": 0, "site_y_km": 0},
            BOARD_ADMIN), 201)
        assert accepted["county_tier"] == "TIER_3"

        rows, meta = validate_paginated(api.list_dealers(BOARD_ADMIN))
        assert meta["total_count"] == 1
        assert rows[0]["id"] == accepted["id"]

    def test_the_listing_pages_the_window_and_filters_by_county_tier(self, api):
        """PRD 2.3: "List results are ordered by `created_at` ascending. The `meta`
        block of a list response carries `limit`, `offset`, `total_count` (the
        number of rows matching the filters before the page window is applied) and
        `has_more` (true when rows remain beyond the current window)." PRD 3.1:
        "Dealerships may be listed with filters on `license_status`,
        `franchise_status`, `county_tier` and `line_make`."

        Design: Corner/entities/dealers_listing_paginates_and_filters_by_county_tier
        """
        fx.set_clock("2026-09-01T00:00:00Z")
        first = fx.create_dealer(legal_name="Lakeside Aurora", county_tier="TIER_2")
        second = fx.create_dealer(legal_name="Harbor Aurora", county_tier="TIER_2",
                                  site_x_km=20)
        tier_one = fx.create_dealer(legal_name="Metro Aurora", county_tier="TIER_1",
                                    site_x_km=40)

        page, meta = validate_paginated(
            api.list_dealers(BOARD_ADMIN, params={"limit": 2, "offset": 0}))
        assert meta["total_count"] == 3
        assert meta["has_more"] is True
        assert len(page) == 2
        assert [row["id"] for row in page] == [first["id"], second["id"]]

        filtered, filtered_meta = validate_paginated(api.list_dealers(
            BOARD_ADMIN, params={"county_tier": "TIER_1", "limit": 10, "offset": 0}))
        assert_list_meta(filtered_meta, total_count=1)
        assert [row["id"] for row in filtered] == [tier_one["id"]]
        assert filtered[0]["county_tier"] == "TIER_1"


class TestNotFoundCatalogue:
    def test_reading_a_dealership_that_was_never_minted_is_a_404(self, api):
        """PRD 2.10: "**Path existence** — every identifier in the path resolves,
        left to right (the 404 catalogue)." The catalogue in §4 maps
        `ERR_DEALER_NOT_FOUND` to HTTP 404, and PRD 2.2 requires the error
        envelope: "The `message` provides a human-readable explanation of what
        went wrong."

        Design: Corner/entities/dealer_detail_read_unknown_id_not_found
        """
        response = api.get_dealer(NON_EXISTENT_UUID, BOARD_ADMIN)
        validate_error(response, ApiErrorId.ERR_DEALER_NOT_FOUND.value, expected_status=404)
        assert response.json()["response_type"] == "error"

    def test_an_application_naming_no_dealership_is_a_404_and_stores_nothing(self, api):
        """PRD 2.10: "**Body foreign-key existence** — every foreign key in the
        body resolves, in the order the operation declares its inputs (the 404
        catalogue)." PRD 3.2: "A licence action opens as a **draft application**
        naming its `dealer_id` and an `application_type` — `INITIAL`, `RENEWAL`,
        `CHANGE_OF_OWNERSHIP` or `RELOCATION`."

        Design: Corner/entities/license_application_unknown_dealer_id_not_found
        """
        fx.set_clock("2026-09-01T00:00:00Z")

        response = api.create_license_application(
            f.license_application_payload(NON_EXISTENT_UUID), BOARD_ADMIN)
        validate_error(response, ApiErrorId.ERR_DEALER_NOT_FOUND.value, expected_status=404)

        _, meta = validate_paginated(api.list_license_applications(BOARD_ADMIN))
        assert meta["total_count"] == 0


class TestMarketStudyIsAppendOnly:
    def test_a_study_carries_no_version_and_the_next_one_appends(self, api):
        """PRD 2.4: "`MarketStudy` and `EvidenceSubmission` rows therefore expose
        only `id` and `created_at`. Both `updated_at` and `version` are absent from
        those two resources entirely, and no operation in this specification
        mutates a row of either kind after it is created." PRD 3.7: "A study is
        never edited, superseded or re-scored once filed." On 3,200 of 40,000
        registrations the actual penetration is 8.00, so a statewide 12.50 shows a
        4.50-point shortfall and comparable shares of 9, 10 and 11 a 2.00-point
        one.

        Design: Corner/entities/market_study_is_immutable_and_carries_no_version
        """
        ctx = fx.setup_filed_additional_point_protest()
        protest, dealer = ctx["protest"], ctx["dealer"]

        statewide = fx.tender_protestant_study(
            protest["id"], dealer["id"],
            total_market_registrations=40000, line_make_registrations=3200,
            statewide_line_make_share_pct=12.50,
            permanency_investment_cents=250000000,
            consumer_access_drive_minutes=22, market_growth_pct=8.00)
        comparable = fx.tender_comparable_study(
            protest["id"], dealer["id"],
            total_market_registrations=40000, line_make_registrations=3200,
            comparable_market_shares_pct=[9.00, 10.00, 11.00],
            permanency_investment_cents=250000000,
            consumer_access_drive_minutes=22, market_growth_pct=8.00)

        assert_append_only_record(statewide)
        assert_append_only_record(comparable)
        assert statewide["actual_penetration_pct"] == 8.00
        assert statewide["expected_penetration_pct"] == 12.50
        assert statewide["shortfall_pts"] == 4.50
        assert comparable["expected_penetration_pct"] == 10.00
        assert comparable["shortfall_pts"] == 2.00
        assert statewide["id"] != comparable["id"]

        rows, meta = validate_paginated(api.list_market_studies(
            protest["id"], make_dealer_headers(dealer["id"]),
            params={"submitted_by_party": "PROTESTANT", "limit": 10, "offset": 0}))
        assert meta["total_count"] == 2
        assert {row["id"] for row in rows} == {statewide["id"], comparable["id"]}
