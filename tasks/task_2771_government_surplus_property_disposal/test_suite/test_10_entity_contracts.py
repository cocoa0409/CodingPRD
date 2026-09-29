"""Field-level record contracts for the Government Surplus Property Disposal API.

Identity and audit stamps, enum domains on write, nullability, the immutability of
the two append-only audit rows, uniqueness and range constraints, derived
valuation fields and the turn-in roll-up counters.
"""

import pytest

from test_helpers import (
    ASSESSOR_USER_ID,
    CLOCK_EPOCH,
    TECHNICIAN_USER_ID,
    ApiErrorId,
    assert_agency,
    assert_clearance_certificate,
    assert_condition_assessment,
    assert_sale_venue,
    assert_surplus_asset,
    assert_timestamp_format,
    assert_turn_in,
    create_asset_payload,
    create_draft_turn_in,
    create_screening_request_payload,
    is_valid_uuid,
    make_agency_officer_headers,
    make_clearance_technician_headers,
    make_disposal_officer_headers,
    make_program_admin_headers,
    make_surplus_assessor_headers,
    open_screening_cycle,
    read_asset,
    read_cycle,
    read_turn_in,
    register_state_agency,
    set_clock,
    setup_assessed_asset,
    setup_assessed_assets,
    submit_turn_in,
    validate_error,
    validate_paginated,
    validate_success,
)

# Syntactically valid identifiers that deliberately name no persisted row.
UNRESOLVABLE_ID = "00000000-0000-4000-8000-000000000000"
SECOND_UNRESOLVABLE_ID = "00000000-0000-4000-8000-000000000001"

ADMIN = make_program_admin_headers()
OFFICER = make_disposal_officer_headers()
ASSESSOR = make_surplus_assessor_headers()
TECHNICIAN = make_clearance_technician_headers()


def _response_type(response) -> str:
    return response.json()["response_type"]


class TestAgencyRecordContracts:
    """POST /agencies, GET /agencies/{id} and GET /agencies."""

    def test_agency_create_applies_declared_defaults(self, api):
        """PRD 3.1: "Registration may optionally carry a `federal_donee_status`,
        which is one of `NONE`, `CERTIFIED` or `SUSPENDED` and defaults to `NONE`
        when omitted, together with a `donee_certification_expires_on` calendar
        date."
        PRD 3.1: "Where `federal_donee_status` is submitted as `CERTIFIED`, the
        expiry date is mandatory and its absence is rejected with
        `ERR_CONDITIONAL_FIELD_REQUIRED`; where the donee status is `NONE`, the
        expiry date is null."
        PRD 3.1: "A freshly registered organisation starts with `status` `ACTIVE`,
        a `proceeds_account_balance_cents` of 0 — a figure that never goes below
        zero — and a `posted_distribution_count` of 0."
        PRD 2.5: "Every resource in this system carries an `id`: a server-minted
        UUID string with no type prefix and no embedded meaning."
        PRD 2.5: "Most resources additionally carry an `updated_at` — an ISO 8601
        UTC timestamp refreshed on every mutation of the row — and a `version`, an
        integer that starts at 1 on insert and increments by exactly 1 on every
        mutation of that row, including mutations the server performs on its own
        initiative as part of a cascade and including recomputation of derived
        fields."

        Design: Corner/entities/entity_agency_create_applies_declared_defaults
        """
        set_clock(CLOCK_EPOCH)

        response = api.create_agency(
            {
                "name": "State Department of Transportation",
                "agency_code": "DOT-01",
                "agency_type": "STATE_AGENCY",
            },
            ADMIN,
        )

        data = validate_success(response, 201)
        assert _response_type(response) == "object", (
            "a single created resource is returned under response_type 'object'"
        )
        assert_agency(data)
        assert data["status"] == "ACTIVE", (
            f"a freshly registered organisation starts ACTIVE, got {data['status']}"
        )
        assert data["federal_donee_status"] == "NONE", (
            "federal_donee_status defaults to NONE when omitted, got "
            f"{data['federal_donee_status']}"
        )
        assert data["donee_certification_expires_on"] is None, (
            "the expiry date is null where the donee status is NONE, got "
            f"{data['donee_certification_expires_on']!r}"
        )
        assert data["proceeds_account_balance_cents"] == 0, (
            "a new organisation opens with a zero proceeds ledger balance, got "
            f"{data['proceeds_account_balance_cents']}"
        )
        assert data["posted_distribution_count"] == 0, (
            f"posted_distribution_count starts at 0, got {data['posted_distribution_count']}"
        )
        assert data["version"] == 1, (
            f"version starts at 1 on insert, got {data['version']}"
        )
        assert is_valid_uuid(data["id"]), (
            f"id must be a bare UUID with no type prefix, got {data['id']!r}"
        )
        assert_timestamp_format(data["created_at"])
        assert data["created_at"] == data["updated_at"], (
            "an unmutated row's updated_at still holds the insert instant; got "
            f"created_at {data['created_at']} vs updated_at {data['updated_at']}"
        )

    def test_agency_get_returns_stored_row_without_mutating_it(self, api):
        """PRD 3.1: "An **organisation** — a state agency, a city or county, or an
        eligible nonprofit — is registered with a legal `name` of 1 to 160
        characters, a short operator-facing `agency_code` of 1 to 24 characters,
        and an `agency_type` of `STATE_AGENCY`, `LOCAL_GOVERNMENT` or
        `ELIGIBLE_NONPROFIT`."
        PRD 2.5: "Most resources additionally carry an `updated_at` — an ISO 8601
        UTC timestamp refreshed on every mutation of the row — and a `version`, an
        integer that starts at 1 on insert and increments by exactly 1 on every
        mutation of that row, including mutations the server performs on its own
        initiative as part of a cascade and including recomputation of derived
        fields."

        Design: Corner/entities/entity_agency_get_returns_stored_row
        """
        set_clock(CLOCK_EPOCH)
        created = validate_success(
            api.create_agency(
                {
                    "name": "Hill Country Food Relief",
                    "agency_code": "NPO-13",
                    "agency_type": "ELIGIBLE_NONPROFIT",
                    "federal_donee_status": "CERTIFIED",
                    "donee_certification_expires_on": "2027-06-30",
                },
                ADMIN,
            ),
            201,
        )

        response = api.get_agency(created["id"], OFFICER)

        data = validate_success(response, 200)
        assert _response_type(response) == "object"
        assert_agency(data)
        assert data["id"] == created["id"]
        assert data["name"] == "Hill Country Food Relief", (
            f"the stored legal name must be returned verbatim, got {data['name']!r}"
        )
        assert data["agency_code"] == "NPO-13", (
            f"the stored agency_code must be returned verbatim, got {data['agency_code']!r}"
        )
        assert data["agency_type"] == "ELIGIBLE_NONPROFIT", (
            f"agency_type must round-trip, got {data['agency_type']!r}"
        )
        assert data["federal_donee_status"] == "CERTIFIED", (
            f"federal_donee_status must round-trip, got {data['federal_donee_status']!r}"
        )
        assert data["donee_certification_expires_on"] == "2027-06-30", (
            "the mandatory expiry date for a CERTIFIED donee must round-trip, got "
            f"{data['donee_certification_expires_on']!r}"
        )
        assert data["version"] == 1, (
            "version increments only on a mutation, and a read is not one; got "
            f"{data['version']}"
        )

    def test_agency_list_reports_filtered_total_and_pagination_window(self, api):
        """PRD 2.3: "List responses populate four pagination fields inside the
        envelope's `meta` object: `limit`, `offset`, `total_count` and `has_more`.
        `total_count` is the number of rows matching the filters before the window
        is applied, and `has_more` is true when rows remain beyond the returned
        window."
        PRD 2.3: "`limit` caps the number of rows returned; it defaults to 10 when
        omitted, its minimum accepted value is 1 and its maximum is 100."
        PRD 2.3: "Unless a specific endpoint states otherwise, list results are
        ordered by `created_at` ascending."
        PRD 3.1: "Organisation listings may be narrowed by `agency_type`, by
        `status` or by `federal_donee_status`."

        Design: Corner/entities/entity_agency_list_pagination_envelope_fields
        """
        # Distinct created_at stamps so the ascending order is total.
        set_clock(CLOCK_EPOCH)
        first = validate_success(
            api.create_agency(
                {
                    "name": "State Department of Transportation",
                    "agency_code": "DOT-01",
                    "agency_type": "STATE_AGENCY",
                },
                ADMIN,
            ),
            201,
        )
        set_clock("2026-08-01T00:00:01Z")
        second = validate_success(
            api.create_agency(
                {
                    "name": "State Parks Division",
                    "agency_code": "PARKS-02",
                    "agency_type": "STATE_AGENCY",
                },
                ADMIN,
            ),
            201,
        )
        set_clock("2026-08-01T00:00:02Z")
        third = validate_success(
            api.create_agency(
                {
                    "name": "City of Cedar Park",
                    "agency_code": "CITY-77",
                    "agency_type": "LOCAL_GOVERNMENT",
                },
                ADMIN,
            ),
            201,
        )

        page_one_response = api.list_agencies(ADMIN, params={"limit": 2, "offset": 0})
        page_one, meta_one = validate_paginated(page_one_response)
        assert _response_type(page_one_response) == "array"
        assert len(page_one) == 2, f"limit 2 caps the window at 2 rows, got {len(page_one)}"
        assert meta_one["limit"] == 2, f"meta.limit echoes the request, got {meta_one['limit']}"
        assert meta_one["offset"] == 0, f"meta.offset echoes the request, got {meta_one['offset']}"
        assert meta_one["total_count"] == 3, (
            f"total_count counts the whole unfiltered set, got {meta_one['total_count']}"
        )
        assert meta_one["has_more"] is True, "rows remain beyond the first window"
        assert [row["id"] for row in page_one] == [first["id"], second["id"]], (
            "rows are ordered by created_at ascending"
        )

        page_two, meta_two = validate_paginated(
            api.list_agencies(ADMIN, params={"limit": 2, "offset": 2})
        )
        assert len(page_two) == 1, f"only one row remains past offset 2, got {len(page_two)}"
        assert meta_two["offset"] == 2
        assert meta_two["total_count"] == 3, (
            f"total_count is window-independent, got {meta_two['total_count']}"
        )
        assert meta_two["has_more"] is False, "no rows remain beyond the second window"
        assert page_two[0]["id"] == third["id"]
        assert not (
            {row["id"] for row in page_one} & {row["id"] for row in page_two}
        ), "offset paging over an unmutated set must not repeat a row"

        filtered, meta_filtered = validate_paginated(
            api.list_agencies(ADMIN, params={"agency_type": "STATE_AGENCY"})
        )
        assert meta_filtered["total_count"] == 2, (
            "total_count reflects the agency_type filter, got "
            f"{meta_filtered['total_count']}"
        )
        assert meta_filtered["has_more"] is False
        assert meta_filtered["limit"] == 10, (
            f"limit defaults to 10 when omitted, got {meta_filtered['limit']}"
        )
        assert {row["id"] for row in filtered} == {first["id"], second["id"]}

    def test_agency_get_unknown_id_returns_agency_not_found(self, api):
        """PRD 2.11: "Each entity has its own not-found code:
        `ERR_AGENCY_NOT_FOUND`, `ERR_TURN_IN_NOT_FOUND`, `ERR_ASSET_NOT_FOUND`,
        `ERR_SCREENING_CYCLE_NOT_FOUND`, `ERR_SCREENING_REQUEST_NOT_FOUND`,
        `ERR_TRANSFER_ORDER_NOT_FOUND`, `ERR_VENUE_NOT_FOUND`,
        `ERR_AUCTION_LOT_NOT_FOUND`, `ERR_BIDDER_NOT_FOUND`,
        `ERR_SALE_INVOICE_NOT_FOUND` and `ERR_DISTRIBUTION_NOT_FOUND`, all
        answering with HTTP 404."
        PRD 2.12: "Every identifier in the path resolves, left to right —
        otherwise the matching 404 code from §2.11."

        Design: Corner/entities/entity_agency_get_unknown_id_not_found
        """
        set_clock(CLOCK_EPOCH)

        response = api.get_agency(UNRESOLVABLE_ID, ADMIN)

        error = validate_error(response, ApiErrorId.ERR_AGENCY_NOT_FOUND)
        assert _response_type(response) == "error"
        assert error["message"].strip(), "the error envelope carries a human-readable message"

        _, meta = validate_paginated(api.list_agencies(ADMIN))
        assert meta["total_count"] == 0, (
            f"the not-found probe created nothing, got total_count {meta['total_count']}"
        )


class TestTurnInRecordContracts:
    """POST /turn-ins field constraints and the fields the server sets itself."""

    @pytest.mark.parametrize("case", ["omitted", "empty_string"])
    def test_turn_in_rejects_missing_custody_location(self, api, case):
        """PRD 3.2: "The opening payload names the `turning_in_agency_id` of the
        organisation giving up custody, a `custody_location` of 1 to 120
        characters naming the yard or warehouse where the property physically
        sits, and optional free-text `remarks`."
        PRD 2.12: "Request shape: every required input present, non-null and of
        the declared JSON type, and every string-length and numeric-range
        constraint satisfied — otherwise `ERR_INVALID_REQUEST` (400)."

        Design: Corner/entities/entity_turn_in_missing_required_custody_location_rejected
        """
        set_clock(CLOCK_EPOCH)
        agency = register_state_agency()
        officer_headers = make_agency_officer_headers(agency["id"])

        payload = {"turning_in_agency_id": agency["id"]}
        if case == "empty_string":
            payload["custody_location"] = ""

        response = api.create_turn_in(payload, officer_headers)

        validate_error(response, ApiErrorId.ERR_INVALID_REQUEST)
        assert _response_type(response) == "error"

        _, meta = validate_paginated(
            api.list_turn_ins(ADMIN, params={"turning_in_agency_id": agency["id"]})
        )
        assert meta["total_count"] == 0, (
            "a rejected opening payload must persist nothing, got total_count "
            f"{meta['total_count']}"
        )

    def test_turn_in_accepts_custody_location_within_length_bounds(self, api):
        """PRD 3.2: "The opening payload names the `turning_in_agency_id` of the
        organisation giving up custody, a `custody_location` of 1 to 120
        characters naming the yard or warehouse where the property physically
        sits, and optional free-text `remarks`."
        PRD 3.2: "Turn-in listings may be narrowed by `turning_in_agency_id` or by
        `status`."

        Design: Corner/entities/entity_turn_in_missing_required_custody_location_rejected
        """
        set_clock(CLOCK_EPOCH)
        agency = register_state_agency()
        officer_headers = make_agency_officer_headers(agency["id"])

        response = api.create_turn_in(
            {"turning_in_agency_id": agency["id"], "custody_location": "Austin Yard 4"},
            officer_headers,
        )

        data = validate_success(response, 201)
        assert_turn_in(data)
        assert data["custody_location"] == "Austin Yard 4", (
            f"custody_location must round-trip verbatim, got {data['custody_location']!r}"
        )
        assert data["turning_in_agency_id"] == agency["id"]

        rows, meta = validate_paginated(
            api.list_turn_ins(ADMIN, params={"turning_in_agency_id": agency["id"]})
        )
        assert meta["total_count"] == 1, (
            f"exactly one turn-in was opened, got total_count {meta['total_count']}"
        )
        assert rows[0]["id"] == data["id"]

    def test_turn_in_create_sets_system_and_computed_fields(self, api):
        """PRD 3.2: "The turn-in opens in `status` `DRAFT` with `asset_count` and
        `appraised_total_cents` both 0 and with `submitted_at`, `reviewed_at` and
        `rejection_reason` all null."
        PRD 2.5: "Every resource in this system carries an `id`: a server-minted
        UUID string with no type prefix and no embedded meaning."
        PRD 2.5: "Most resources additionally carry an `updated_at` — an ISO 8601
        UTC timestamp refreshed on every mutation of the row — and a `version`, an
        integer that starts at 1 on insert and increments by exactly 1 on every
        mutation of that row, including mutations the server performs on its own
        initiative as part of a cascade and including recomputation of derived
        fields."

        Design: Corner/entities/entity_turn_in_system_and_computed_fields_on_create
        """
        set_clock(CLOCK_EPOCH)
        agency = register_state_agency()
        officer_headers = make_agency_officer_headers(agency["id"])

        response = api.create_turn_in(
            {
                "turning_in_agency_id": agency["id"],
                "custody_location": "Round Rock Warehouse B",
                "remarks": "End of fiscal year clear-out",
            },
            officer_headers,
        )

        created = validate_success(response, 201)
        assert_turn_in(created)
        assert created["status"] == "DRAFT", (
            f"a turn-in opens in DRAFT, got {created['status']}"
        )
        assert created["asset_count"] == 0, (
            f"asset_count opens at 0, got {created['asset_count']}"
        )
        assert created["appraised_total_cents"] == 0, (
            f"appraised_total_cents opens at 0, got {created['appraised_total_cents']}"
        )
        assert created["submitted_at"] is None, (
            f"submitted_at opens null, got {created['submitted_at']!r}"
        )
        assert created["reviewed_at"] is None, (
            f"reviewed_at opens null, got {created['reviewed_at']!r}"
        )
        assert created["rejection_reason"] is None, (
            f"rejection_reason opens null, got {created['rejection_reason']!r}"
        )
        assert created["version"] == 1, (
            f"version starts at 1 on insert, got {created['version']}"
        )
        assert is_valid_uuid(created["id"]), (
            f"id must be a bare UUID, got {created['id']!r}"
        )
        assert_timestamp_format(created["created_at"])
        assert created["created_at"] == created["updated_at"], (
            "an unmutated turn-in has updated_at equal to created_at; got "
            f"{created['created_at']} vs {created['updated_at']}"
        )

        fetched = read_turn_in(created["id"], agency["id"])
        assert fetched == created, (
            "the stored turn-in must read back identically to the creation response"
        )


class TestSurplusAssetRecordContracts:
    """POST /assets: flags, enum domains, derived valuation fields and the
    acyclic component graph."""

    def test_asset_optional_flags_set_the_clearance_axis(self, api):
        """PRD 3.2: "`clearance_status` begins at `REQUIRED_PENDING` when either
        `is_data_bearing` or `is_restricted` is true, and at `NOT_REQUIRED` when
        both are false — in the latter case the release gate stands open from birth
        and no certificate may ever be filed against the item."
        PRD 3.2: "`disposition_status` begins at `INTAKE` in every case."
        PRD 3.2: "`is_restricted` marks a controlled or restricted article that
        needs demilitarisation before it can leave; it also defaults to false, and
        when it is true a `demil_code` of `A`, `B`, `C`, `D` or `Q` is mandatory —
        its absence is rejected with `ERR_CONDITIONAL_FIELD_REQUIRED`, and for an
        unrestricted item the `demil_code` is null."
        PRD 3.2: "`asset_count` is the number of assets whose `turn_in_id` is this
        turn-in, counted across every `disposition_status` value without
        exception."

        Design: Corner/entities/entity_asset_creation_with_optional_flags_sets_clearance_axis
        """
        set_clock(CLOCK_EPOCH)
        agency = register_state_agency()
        officer_headers = make_agency_officer_headers(agency["id"])
        turn_in = create_draft_turn_in(agency["id"])

        restricted = validate_success(
            api.create_asset(
                {
                    "turn_in_id": turn_in["id"],
                    "category": "RESTRICTED_MILITARY",
                    "description": "Armoured personnel carrier hull",
                    "acquisition_cost_cents": 870401,
                    "acquisition_date": "2016-04-11",
                    "is_restricted": True,
                    "demil_code": "B",
                },
                officer_headers,
            ),
            201,
        )
        assert_surplus_asset(restricted)
        assert restricted["clearance_status"] == "REQUIRED_PENDING", (
            "a restricted article needs clearance before release, got "
            f"{restricted['clearance_status']}"
        )
        assert restricted["is_restricted"] is True
        assert restricted["is_data_bearing"] is False, (
            "is_data_bearing defaults to false, got "
            f"{restricted['is_data_bearing']!r}"
        )
        assert restricted["demil_code"] == "B", (
            f"the supplied demil_code must round-trip, got {restricted['demil_code']!r}"
        )
        assert restricted["disposition_status"] == "INTAKE", (
            f"disposition_status begins at INTAKE in every case, got "
            f"{restricted['disposition_status']}"
        )
        assert restricted["condition_code"] is None, (
            "condition_code stays null until the first assessment exists, got "
            f"{restricted['condition_code']!r}"
        )
        assert restricted["fair_market_value_cents"] is None, (
            "fair_market_value_cents stays null until the first assessment exists, "
            f"got {restricted['fair_market_value_cents']!r}"
        )

        plain = validate_success(
            api.create_asset(
                {
                    "turn_in_id": turn_in["id"],
                    "category": "FURNITURE",
                    "description": "Four-drawer lateral file cabinets, lot of six",
                    "acquisition_cost_cents": 104500,
                    "acquisition_date": "2024-05-20",
                },
                officer_headers,
            ),
            201,
        )
        assert_surplus_asset(plain)
        assert plain["clearance_status"] == "NOT_REQUIRED", (
            "neither flag is set, so the release gate stands open from birth; got "
            f"{plain['clearance_status']}"
        )
        assert plain["is_data_bearing"] is False
        assert plain["is_restricted"] is False
        assert plain["demil_code"] is None, (
            f"an unrestricted item's demil_code is null, got {plain['demil_code']!r}"
        )
        assert plain["disposition_status"] == "INTAKE"

        parent = read_turn_in(turn_in["id"], agency["id"])
        assert parent["asset_count"] == 2, (
            "the parent turn-in's asset_count is recomputed on each creation, got "
            f"{parent['asset_count']}"
        )

    def test_asset_condition_and_value_are_computed_from_the_assessment(self, api):
        """PRD 3.3: "Take the number of whole days between the asset's
        `acquisition_date` and the logical clock's current date, divide by 365 and
        discard any remainder to obtain the number of full elapsed years."
        PRD 3.3: "The age factor is one minus ten hundredths for each of those full
        years, but never less than twenty hundredths — an item held twelve years
        and an item held twenty years are both floored at the same twenty
        hundredths of original value."
        PRD 3.3: "The **condition factor** is read from the governing assessment's
        `condition_code` against a fixed schedule: `C1` retains the full original
        value at one, `C2` retains eighty-five hundredths, `C3` seventy hundredths,
        `C4` fifty hundredths, `C5` thirty hundredths, `C6` fifteen hundredths, and
        `C7` five hundredths."
        PRD 3.3: "The **functional factor** is one when the governing assessment's
        `functional` flag is true, and sixty hundredths when it is false."
        PRD 3.3: "Multiply `acquisition_cost_cents` by the condition factor, the
        age factor and the functional factor, and round that single product half up
        to whole cents."
        PRD 3.3: "The result is stored as `fair_market_value_cents`, and the
        governing assessment's `condition_code` is copied onto the asset's own
        `condition_code`."
        PRD 3.3: "The first assessment on an asset drives `disposition_status` from
        `INTAKE` to `ASSESSED`."
        PRD 3.3: "Either way the parent turn-in's `appraised_total_cents` is
        recomputed and the asset's `version` increments by 1."

        Design: Corner/entities/entity_asset_computed_condition_and_value_fields
        """
        set_clock(CLOCK_EPOCH)
        agency = register_state_agency()
        officer_headers = make_agency_officer_headers(agency["id"])
        turn_in = create_draft_turn_in(agency["id"])
        asset = validate_success(
            api.create_asset(
                {
                    "turn_in_id": turn_in["id"],
                    "category": "FURNITURE",
                    "description": "Executive conference table",
                    "acquisition_cost_cents": 1000000,
                    "acquisition_date": "2005-01-01",
                },
                officer_headers,
            ),
            201,
        )
        assert asset["fair_market_value_cents"] is None
        submit_turn_in(agency["id"], turn_in["id"])

        assessment = validate_success(
            api.create_condition_assessment(
                asset["id"],
                {
                    "condition_code": "C1",
                    "functional": True,
                    "repair_cost_estimate_cents": 0,
                    "assessed_on": "2026-07-31",
                    "expected_asset_version": asset["version"],
                },
                ASSESSOR,
            ),
            201,
        )
        assert_condition_assessment(assessment)

        appraised = read_asset(asset["id"])
        assert_surplus_asset(appraised)
        assert appraised["condition_code"] == "C1", (
            "the governing assessment's condition_code is copied onto the asset, got "
            f"{appraised['condition_code']!r}"
        )
        assert appraised["fair_market_value_cents"] == 200000, (
            "an item held 21 full years floors at the twenty-hundredths age factor, "
            f"so 1000000 * 1.00 * 0.20 * 1.00 is 200000; got "
            f"{appraised['fair_market_value_cents']}"
        )
        assert appraised["disposition_status"] == "ASSESSED", (
            "the first assessment drives INTAKE to ASSESSED, got "
            f"{appraised['disposition_status']}"
        )
        assert appraised["version"] == 2, (
            f"the asset's version increments by 1, got {appraised['version']}"
        )

        parent = read_turn_in(turn_in["id"], agency["id"])
        assert parent["appraised_total_cents"] == 200000, (
            "the parent turn-in's appraised_total_cents is recomputed, got "
            f"{parent['appraised_total_cents']}"
        )
        assert parent["asset_count"] == 1, (
            f"asset_count counts every disposition_status, got {parent['asset_count']}"
        )

    def test_asset_category_outside_the_declared_enum_is_rejected(self, api):
        """PRD 3.2: "An item is described by a `category` — one of `VEHICLE`,
        `IT_EQUIPMENT`, `FURNITURE`, `HEAVY_EQUIPMENT` or `RESTRICTED_MILITARY` —
        a `description` of 1 to 200 characters, an `acquisition_cost_cents` that
        must be strictly greater than zero, and an `acquisition_date` giving the
        calendar date on which the turning-in agency originally acquired it."
        PRD 2.12: "Every enum-typed input carries a value from that enum's declared
        set — otherwise `ERR_INVALID_ENUM_VALUE` (422)."

        Design: Corner/entities/entity_asset_invalid_category_enum_rejected
        """
        set_clock(CLOCK_EPOCH)
        agency = register_state_agency()
        officer_headers = make_agency_officer_headers(agency["id"])
        turn_in = create_draft_turn_in(agency["id"])

        response = api.create_asset(
            {
                "turn_in_id": turn_in["id"],
                "category": "OFFICE_SUPPLIES",
                "description": "Boxes of assorted stationery",
                "acquisition_cost_cents": 45000,
                "acquisition_date": "2023-02-14",
            },
            officer_headers,
        )

        validate_error(response, ApiErrorId.ERR_INVALID_ENUM_VALUE)
        assert read_turn_in(turn_in["id"], agency["id"])["asset_count"] == 0, (
            "a rejected asset creation must not touch the parent's asset_count"
        )

    def test_asset_non_positive_acquisition_cost_is_rejected(self, api):
        """PRD 3.2: "An item is described by a `category` — one of `VEHICLE`,
        `IT_EQUIPMENT`, `FURNITURE`, `HEAVY_EQUIPMENT` or `RESTRICTED_MILITARY` —
        a `description` of 1 to 200 characters, an `acquisition_cost_cents` that
        must be strictly greater than zero, and an `acquisition_date` giving the
        calendar date on which the turning-in agency originally acquired it."
        PRD 2.12: "Request shape: every required input present, non-null and of the
        declared JSON type, and every string-length and numeric-range constraint
        satisfied — otherwise `ERR_INVALID_REQUEST` (400)."

        Design: Corner/entities/entity_asset_invalid_category_enum_rejected
        """
        set_clock(CLOCK_EPOCH)
        agency = register_state_agency()
        officer_headers = make_agency_officer_headers(agency["id"])
        turn_in = create_draft_turn_in(agency["id"])

        response = api.create_asset(
            {
                "turn_in_id": turn_in["id"],
                "category": "FURNITURE",
                "description": "Fully depreciated stacking chairs",
                "acquisition_cost_cents": 0,
                "acquisition_date": "2023-02-14",
            },
            officer_headers,
        )

        validate_error(response, ApiErrorId.ERR_INVALID_REQUEST)
        assert read_turn_in(turn_in["id"], agency["id"])["asset_count"] == 0, (
            "a rejected asset creation must not touch the parent's asset_count"
        )

    def test_asset_component_link_must_stay_inside_the_same_turn_in(self, api):
        """PRD 3.2: "The referenced asset must sit on the same `turn_in_id`, must
        not be the item being created, and must not be one of that item's own
        ancestors: the component graph must stay acyclic. Any of those three
        violations is rejected with `ERR_ASSET_COMPONENT_CYCLE` (HTTP 422)."
        PRD 3.2: "Asset listings may be narrowed by `turn_in_id`, by
        `component_of_asset_id`, by `category`, by `disposition_status` or by
        `clearance_status`."

        Design: Corner/entities/entity_asset_component_of_self_rejected
        """
        set_clock(CLOCK_EPOCH)
        agency = register_state_agency()
        officer_headers = make_agency_officer_headers(agency["id"])
        turn_in_a = create_draft_turn_in(agency["id"], custody_location="Austin Yard 4")
        turn_in_b = create_draft_turn_in(agency["id"], custody_location="Bastrop Annex")

        parent_asset = validate_success(
            api.create_asset(
                {
                    "turn_in_id": turn_in_a["id"],
                    "category": "HEAVY_EQUIPMENT",
                    "description": "Nine-ton vibratory road roller",
                    "acquisition_cost_cents": 870401,
                    "acquisition_date": "2016-04-11",
                },
                officer_headers,
            ),
            201,
        )

        cross_turn_in = api.create_asset(
            {
                "turn_in_id": turn_in_b["id"],
                "category": "HEAVY_EQUIPMENT",
                "description": "Roller drum scraper assembly",
                "acquisition_cost_cents": 41000,
                "acquisition_date": "2016-04-11",
                "component_of_asset_id": parent_asset["id"],
            },
            officer_headers,
        )
        validate_error(cross_turn_in, ApiErrorId.ERR_ASSET_COMPONENT_CYCLE)

        same_turn_in = validate_success(
            api.create_asset(
                {
                    "turn_in_id": turn_in_a["id"],
                    "category": "HEAVY_EQUIPMENT",
                    "description": "Roller drum scraper assembly",
                    "acquisition_cost_cents": 41000,
                    "acquisition_date": "2016-04-11",
                    "component_of_asset_id": parent_asset["id"],
                },
                officer_headers,
            ),
            201,
        )
        assert_surplus_asset(same_turn_in)
        assert same_turn_in["component_of_asset_id"] == parent_asset["id"], (
            "a component link inside the same turn-in must be stored, got "
            f"{same_turn_in['component_of_asset_id']!r}"
        )

        children, meta = validate_paginated(
            api.list_assets(
                OFFICER, params={"component_of_asset_id": parent_asset["id"]}
            )
        )
        assert meta["total_count"] == 1, (
            "only the accepted component hangs off the parent, got total_count "
            f"{meta['total_count']}"
        )
        assert children[0]["id"] == same_turn_in["id"]

        assert read_turn_in(turn_in_b["id"], agency["id"])["asset_count"] == 0, (
            "the rejected cross-turn-in component persisted nothing on the other "
            "turn-in"
        )


class TestAppendOnlyAuditRecords:
    """ConditionAssessment and ClearanceCertificate are written once and never
    modified, and carry no updated_at and no version."""

    def test_condition_assessment_row_is_an_immutable_audit_record(self, api):
        """PRD 2.5: "A `ConditionAssessment` has an `id` and a `created_at` and
        nothing else of the system set: it has no `updated_at` and no `version`."
        PRD 2.5: "Both are written once and never modified — with the single
        exception of the `superseded` flag on a `ConditionAssessment`, which the
        valuation selector maintains and which does not create an `updated_at` or a
        `version` on that row."
        PRD 3.3: "Every later assessment is a self-transition, `ASSESSED` to
        `ASSESSED`, and it is a genuine rewrite of the valuation rather than an
        append: the assessment that had been governing acquires `superseded` equal
        to true, and the asset's `condition_code` and `fair_market_value_cents` are
        recomputed from the new governing assessment."
        PRD 3.3: "Every other candidate carries `superseded` equal to true, and the
        governing one carries `superseded` equal to false."
        PRD 3.3: "Assessments for an asset are listed with the governing assessment
        first, ordered by `assessed_on` descending and then by `created_at`
        descending."

        Design: Corner/entities/entity_condition_assessment_is_immutable_audit_row
        """
        set_clock(CLOCK_EPOCH)
        agency = register_state_agency()
        officer_headers = make_agency_officer_headers(agency["id"])
        turn_in = create_draft_turn_in(agency["id"])
        asset = validate_success(
            api.create_asset(
                {
                    "turn_in_id": turn_in["id"],
                    "category": "FURNITURE",
                    "description": "Modular workstation cluster",
                    "acquisition_cost_cents": 1000000,
                    "acquisition_date": "2026-01-10",
                },
                officer_headers,
            ),
            201,
        )
        submit_turn_in(agency["id"], turn_in["id"])

        first = validate_success(
            api.create_condition_assessment(
                asset["id"],
                {
                    "condition_code": "C5",
                    "functional": True,
                    "repair_cost_estimate_cents": 0,
                    "assessed_on": "2026-07-20",
                    "expected_asset_version": asset["version"],
                },
                ASSESSOR,
            ),
            201,
        )
        assert_condition_assessment(first)
        assert first["superseded"] is False, (
            "the only candidate governs, so it is not superseded"
        )
        assert first["assessor_user_id"] == ASSESSOR_USER_ID, (
            "assessor_user_id is stamped from the caller's X-User-ID, got "
            f"{first['assessor_user_id']!r}"
        )
        assert "version" not in first, (
            "a ConditionAssessment carries no version field"
        )
        assert "updated_at" not in first, (
            "a ConditionAssessment carries no updated_at field"
        )
        after_first = read_asset(asset["id"])
        assert after_first["fair_market_value_cents"] == 300000, (
            "1000000 at the C5 thirty-hundredths factor is 300000; got "
            f"{after_first['fair_market_value_cents']}"
        )

        second = validate_success(
            api.create_condition_assessment(
                asset["id"],
                {
                    "condition_code": "C2",
                    "functional": True,
                    "repair_cost_estimate_cents": 0,
                    "assessed_on": "2026-07-28",
                    "expected_asset_version": after_first["version"],
                },
                ASSESSOR,
            ),
            201,
        )
        assert_condition_assessment(second)
        assert second["id"] != first["id"], (
            "a re-assessment appends a new audit row rather than rewriting the old one"
        )
        assert second["superseded"] is False, (
            "the newly governing assessment carries superseded false"
        )
        assert "version" not in second and "updated_at" not in second, (
            "neither system field appears on a ConditionAssessment"
        )

        rows, meta = validate_paginated(
            api.list_condition_assessments(asset["id"], ASSESSOR)
        )
        assert meta["total_count"] == 2, (
            f"both assessment rows survive, got total_count {meta['total_count']}"
        )
        assert rows[0]["id"] == second["id"], (
            "assessments are listed governing-first, by assessed_on descending"
        )
        assert rows[1]["id"] == first["id"]
        stored_first = rows[1]
        assert stored_first["superseded"] is True, (
            "the previously governing assessment acquires superseded true, got "
            f"{stored_first['superseded']!r}"
        )
        assert stored_first["condition_code"] == "C5", (
            "the superseded row keeps its own condition_code, got "
            f"{stored_first['condition_code']!r}"
        )
        assert stored_first["assessed_on"] == "2026-07-20", (
            f"the superseded row keeps its assessed_on, got {stored_first['assessed_on']!r}"
        )
        assert stored_first["created_at"] == first["created_at"], (
            "maintaining superseded must not restamp created_at; got "
            f"{stored_first['created_at']} vs {first['created_at']}"
        )
        assert "version" not in stored_first and "updated_at" not in stored_first, (
            "maintaining superseded creates neither an updated_at nor a version"
        )

        revalued = read_asset(asset["id"])
        assert revalued["condition_code"] == "C2", (
            "the asset's condition_code is recomputed from the new governing "
            f"assessment, got {revalued['condition_code']!r}"
        )
        assert revalued["fair_market_value_cents"] == 850000, (
            "1000000 at the C2 eighty-five-hundredths factor is 850000; got "
            f"{revalued['fair_market_value_cents']}"
        )
        assert revalued["version"] == 3, (
            f"each assessment increments the asset's version by 1, got {revalued['version']}"
        )

    def test_clearance_certificate_row_is_an_immutable_audit_record(self, api):
        """PRD 2.5: "A `ClearanceCertificate` likewise has an `id` and a
        `created_at`, with no `updated_at` and no `version`."
        PRD 3.8: "The certificate stores the `asset_id` it addresses and stamps
        `technician_user_id` from the technician's `X-User-ID`."
        PRD 3.8: "A certificate with `serials_verified` false is persisted for audit
        and moves the asset to `BLOCKED`, whether it arrives at `REQUIRED_PENDING`
        or at `CLEARED` — a clearance that has already been granted can be revoked
        by a later failed verification, though only while the asset has not yet
        reached `RELEASED`."
        PRD 3.8: "From `BLOCKED`, a verified certificate that completes the required
        set moves the asset back to `CLEARED`."
        PRD 3.8: "Each accepted certificate re-evaluates the clearance axis and
        leaves `disposition_status` entirely untouched, incrementing the asset's
        `version` by 1 either way."
        PRD 3.8: "Certificates against an asset may be listed narrowed by
        `cert_type`."

        Design: Corner/entities/entity_clearance_certificate_is_immutable_audit_row
        """
        set_clock(CLOCK_EPOCH)
        agency = register_state_agency()
        officer_headers = make_agency_officer_headers(agency["id"])
        turn_in = create_draft_turn_in(agency["id"])
        asset = validate_success(
            api.create_asset(
                {
                    "turn_in_id": turn_in["id"],
                    "category": "IT_EQUIPMENT",
                    "description": "Rack-mounted database server, dual socket",
                    "acquisition_cost_cents": 1449920,
                    "acquisition_date": "2023-11-02",
                    "is_data_bearing": True,
                },
                officer_headers,
            ),
            201,
        )
        assert asset["clearance_status"] == "REQUIRED_PENDING"
        submit_turn_in(agency["id"], turn_in["id"])
        validate_success(
            api.create_condition_assessment(
                asset["id"],
                {
                    "condition_code": "C2",
                    "functional": True,
                    "repair_cost_estimate_cents": 0,
                    "assessed_on": "2026-07-28",
                    "expected_asset_version": asset["version"],
                },
                ASSESSOR,
            ),
            201,
        )

        failed = validate_success(
            api.create_clearance_certificate(
                asset["id"],
                {
                    "cert_type": "DATA_SANITIZATION",
                    "method": "NIST_CLEAR",
                    "serials_verified": False,
                    "certified_on": "2026-07-30",
                },
                TECHNICIAN,
            ),
            201,
        )
        assert_clearance_certificate(failed)
        assert failed["asset_id"] == asset["id"], (
            f"the certificate stores the asset it addresses, got {failed['asset_id']!r}"
        )
        assert failed["technician_user_id"] == TECHNICIAN_USER_ID, (
            "technician_user_id is stamped from the technician's X-User-ID, got "
            f"{failed['technician_user_id']!r}"
        )
        assert failed["serials_verified"] is False
        assert "version" not in failed and "updated_at" not in failed, (
            "a ClearanceCertificate carries neither a version nor an updated_at"
        )
        blocked = read_asset(asset["id"])
        assert blocked["clearance_status"] == "BLOCKED", (
            "an unverified certificate is persisted for audit and blocks the asset, "
            f"got {blocked['clearance_status']}"
        )
        assert blocked["disposition_status"] == "ASSESSED", (
            "the clearance axis leaves disposition_status entirely untouched, got "
            f"{blocked['disposition_status']}"
        )
        assert blocked["version"] == 3, (
            f"each accepted certificate increments version by 1, got {blocked['version']}"
        )

        verified = validate_success(
            api.create_clearance_certificate(
                asset["id"],
                {
                    "cert_type": "DATA_SANITIZATION",
                    "method": "NIST_PURGE",
                    "serials_verified": True,
                    "certified_on": "2026-08-01",
                },
                TECHNICIAN,
            ),
            201,
        )
        assert_clearance_certificate(verified)
        assert verified["id"] != failed["id"], (
            "a later certificate appends a new audit row rather than rewriting the "
            "earlier one"
        )
        assert "version" not in verified and "updated_at" not in verified

        cleared = read_asset(asset["id"])
        assert cleared["clearance_status"] == "CLEARED", (
            "from BLOCKED, a verified certificate completing the required set "
            f"restores CLEARED, got {cleared['clearance_status']}"
        )
        assert cleared["disposition_status"] == "ASSESSED", (
            "disposition_status is still untouched, got "
            f"{cleared['disposition_status']}"
        )
        assert cleared["version"] == 4, (
            f"the second certificate increments version again, got {cleared['version']}"
        )

        rows, meta = validate_paginated(
            api.list_clearance_certificates(
                asset["id"], TECHNICIAN, params={"cert_type": "DATA_SANITIZATION"}
            )
        )
        assert meta["total_count"] == 2, (
            "the failed certificate is retained for audit alongside the verified "
            f"one, got total_count {meta['total_count']}"
        )
        by_id = {row["id"]: row for row in rows}
        assert set(by_id) == {failed["id"], verified["id"]}
        stored_failed = by_id[failed["id"]]
        assert stored_failed["serials_verified"] is False, (
            "the failed certificate is never rewritten, got "
            f"{stored_failed['serials_verified']!r}"
        )
        assert stored_failed["method"] == "NIST_CLEAR", (
            f"the failed certificate keeps its method, got {stored_failed['method']!r}"
        )
        assert stored_failed["created_at"] == failed["created_at"], (
            "the stored certificate keeps its original created_at; got "
            f"{stored_failed['created_at']} vs {failed['created_at']}"
        )
        for row in rows:
            assert "version" not in row and "updated_at" not in row, (
                "no ClearanceCertificate row carries a version or an updated_at"
            )


class TestBodyForeignKeyResolution:
    """Foreign keys carried in the request body resolve in field-declaration
    order, each with its own not-found code."""

    def test_asset_creation_with_unknown_turn_in_reports_turn_in_not_found(self, api):
        """PRD 2.11: "Once every path identifier resolves, foreign keys carried in
        the request body are resolved next, in the order in which the fields are
        declared on the entity being created. The same not-found codes apply.
        Body-level foreign key resolution is performed by turn-in creation, asset
        creation, screening-cycle creation, screening-request filing, transfer-order
        issuance, auction-lot creation, bid placement and proceeds-distribution
        creation."
        PRD 2.11: "Each entity has its own not-found code: `ERR_AGENCY_NOT_FOUND`,
        `ERR_TURN_IN_NOT_FOUND`, `ERR_ASSET_NOT_FOUND`,
        `ERR_SCREENING_CYCLE_NOT_FOUND`, `ERR_SCREENING_REQUEST_NOT_FOUND`,
        `ERR_TRANSFER_ORDER_NOT_FOUND`, `ERR_VENUE_NOT_FOUND`,
        `ERR_AUCTION_LOT_NOT_FOUND`, `ERR_BIDDER_NOT_FOUND`,
        `ERR_SALE_INVOICE_NOT_FOUND` and `ERR_DISTRIBUTION_NOT_FOUND`, all answering
        with HTTP 404."

        Design: Corner/entities/entity_asset_unknown_turn_in_fk_not_found
        """
        set_clock(CLOCK_EPOCH)
        register_state_agency()

        response = api.create_asset(
            {
                "turn_in_id": UNRESOLVABLE_ID,
                "category": "FURNITURE",
                "description": "Four-drawer lateral file cabinets, lot of six",
                "acquisition_cost_cents": 104500,
                "acquisition_date": "2024-05-20",
            },
            ADMIN,
        )

        validate_error(response, ApiErrorId.ERR_TURN_IN_NOT_FOUND)
        assert _response_type(response) == "error"

        _, meta = validate_paginated(api.list_assets(OFFICER))
        assert meta["total_count"] == 0, (
            "an unresolvable body foreign key must persist nothing, got total_count "
            f"{meta['total_count']}"
        )

    def test_screening_request_resolves_cycle_before_requesting_agency(self, api):
        """PRD 2.11: "Once every path identifier resolves, foreign keys carried in
        the request body are resolved next, in the order in which the fields are
        declared on the entity being created."
        PRD 2.12: "Every foreign key in the request body resolves, in entity
        field-declaration order — otherwise the matching 404 code."
        PRD 3.4: "The filing names the `screening_cycle_id` it competes in and the
        `requesting_agency_id` asking for the property, and describes the claim with
        an `intended_use` of 1 to 200 characters, a `justification` of 1 to 500
        characters, and the `needed_by_date` by which the organisation needs the
        property."

        Design: Corner/entities/entity_screening_request_body_fk_validation_order_not_found
        """
        scenario = setup_assessed_asset(kind="vehicle", clock=CLOCK_EPOCH)
        cycle = open_screening_cycle(scenario["asset"]["id"])

        # Both body foreign keys unresolvable: the cycle is declared first, so the
        # cycle's not-found code is the one reported.
        both_missing = api.create_screening_request(
            create_screening_request_payload(UNRESOLVABLE_ID, SECOND_UNRESOLVABLE_ID),
            ADMIN,
        )
        validate_error(both_missing, ApiErrorId.ERR_SCREENING_CYCLE_NOT_FOUND)

        # With the cycle resolving, the second declared foreign key is reached.
        agency_missing = api.create_screening_request(
            create_screening_request_payload(cycle["id"], SECOND_UNRESOLVABLE_ID),
            ADMIN,
        )
        validate_error(agency_missing, ApiErrorId.ERR_AGENCY_NOT_FOUND)

        _, meta = validate_paginated(
            api.list_screening_requests(OFFICER, params={"screening_cycle_id": cycle["id"]})
        )
        assert meta["total_count"] == 0, (
            "neither rejected filing may persist, got total_count "
            f"{meta['total_count']}"
        )
        assert read_cycle(cycle["id"])["open_request_count"] == 0, (
            "a rejected filing must not touch the cycle's open_request_count"
        )


class TestAssetListingContracts:
    """GET /assets: declared filters combined with the pagination window."""

    def test_asset_listing_filters_and_windows_independently(self, api):
        """PRD 3.2: "Asset listings may be narrowed by `turn_in_id`, by
        `component_of_asset_id`, by `category`, by `disposition_status` or by
        `clearance_status`."
        PRD 2.3: "List responses populate four pagination fields inside the
        envelope's `meta` object: `limit`, `offset`, `total_count` and `has_more`.
        `total_count` is the number of rows matching the filters before the window
        is applied, and `has_more` is true when rows remain beyond the returned
        window."
        PRD 3.3: "The first assessment on an asset drives `disposition_status` from
        `INTAKE` to `ASSESSED`."

        Design: Corner/entities/entity_asset_list_filter_and_pagination
        """
        appraisal = {
            "condition_code": "C1",
            "functional": True,
            "repair_cost_estimate_cents": 0,
            "assessed_on": "2026-07-31",
        }
        scenario = setup_assessed_assets(
            [
                {
                    "kind": "furniture",
                    "overrides": {"description": "Workstation cluster 1"},
                    "assessment": appraisal,
                },
                {
                    "kind": "furniture",
                    "overrides": {"description": "Workstation cluster 2"},
                    "assessment": appraisal,
                },
                {
                    "kind": "furniture",
                    "overrides": {"description": "Workstation cluster 3"},
                    "assessment": None,
                },
            ],
            clock=CLOCK_EPOCH,
            accept=False,
        )
        turn_in_id = scenario["turn_in"]["id"]
        assets = scenario["assets"]
        assessed_ids = {assets[0]["id"], assets[1]["id"]}
        unappraised_id = assets[2]["id"]

        all_rows, all_meta = validate_paginated(
            api.list_assets(OFFICER, params={"turn_in_id": turn_in_id})
        )
        assert all_meta["total_count"] == 3, (
            f"all three items sit on the turn-in, got {all_meta['total_count']}"
        )
        assert all_meta["has_more"] is False
        assert {row["id"] for row in all_rows} == assessed_ids | {unappraised_id}

        assessed_rows, assessed_meta = validate_paginated(
            api.list_assets(
                OFFICER,
                params={"turn_in_id": turn_in_id, "disposition_status": "ASSESSED"},
            )
        )
        assert assessed_meta["total_count"] == 2, (
            "only the two appraised items reached ASSESSED, got "
            f"{assessed_meta['total_count']}"
        )
        assert {row["id"] for row in assessed_rows} == assessed_ids
        assert unappraised_id not in {row["id"] for row in assessed_rows}, (
            "the unappraised item is still at INTAKE and must be filtered out"
        )

        intake_rows, intake_meta = validate_paginated(
            api.list_assets(
                OFFICER,
                params={"turn_in_id": turn_in_id, "disposition_status": "INTAKE"},
            )
        )
        assert intake_meta["total_count"] == 1, (
            f"exactly one item is still at INTAKE, got {intake_meta['total_count']}"
        )
        assert intake_rows[0]["id"] == unappraised_id

        page_one, page_one_meta = validate_paginated(
            api.list_assets(
                OFFICER, params={"turn_in_id": turn_in_id, "limit": 2, "offset": 0}
            )
        )
        assert len(page_one) == 2, f"the window is capped at 2 rows, got {len(page_one)}"
        assert page_one_meta["total_count"] == 3, (
            "total_count counts the filter matches before the window, got "
            f"{page_one_meta['total_count']}"
        )
        assert page_one_meta["has_more"] is True, "a third row remains beyond the window"

        page_two, page_two_meta = validate_paginated(
            api.list_assets(
                OFFICER, params={"turn_in_id": turn_in_id, "limit": 2, "offset": 2}
            )
        )
        assert len(page_two) == 1, f"one row remains past offset 2, got {len(page_two)}"
        assert page_two_meta["offset"] == 2
        assert page_two_meta["total_count"] == 3
        assert page_two_meta["has_more"] is False
        assert not (
            {row["id"] for row in page_one} & {row["id"] for row in page_two}
        ), "the two windows must not overlap"
        assert {row["id"] for row in page_one} | {row["id"] for row in page_two} == (
            assessed_ids | {unappraised_id}
        ), "the two windows together must cover every matching row exactly once"

        category_rows, category_meta = validate_paginated(
            api.list_assets(
                OFFICER, params={"turn_in_id": turn_in_id, "category": "VEHICLE"}
            )
        )
        assert category_meta["total_count"] == 0, (
            "no VEHICLE was turned in, got total_count "
            f"{category_meta['total_count']}"
        )
        assert category_rows == [], "an empty match returns an empty data array"

    @pytest.mark.parametrize(
        "params",
        [
            {"limit": 0},
            {"limit": 101},
            {"offset": -1},
        ],
        ids=["limit_below_minimum", "limit_above_maximum", "negative_offset"],
    )
    def test_asset_listing_rejects_out_of_range_pagination(self, api, params):
        """PRD 2.3: "`limit` caps the number of rows returned; it defaults to 10
        when omitted, its minimum accepted value is 1 and its maximum is 100."
        PRD 2.3: "A `limit` outside the range 1 through 100 inclusive, or a negative
        `offset`, or a non-integer value for either, is rejected with
        `ERR_INVALID_PAGINATION` (HTTP 400)."

        Design: Corner/entities/entity_asset_list_filter_and_pagination
        """
        set_clock(CLOCK_EPOCH)
        agency = register_state_agency()
        officer_headers = make_agency_officer_headers(agency["id"])
        turn_in = create_draft_turn_in(agency["id"])
        validate_success(
            api.create_asset(create_asset_payload(turn_in["id"]), officer_headers), 201
        )

        query = {"turn_in_id": turn_in["id"]}
        query.update(params)

        response = api.list_assets(OFFICER, params=query)

        validate_error(response, ApiErrorId.ERR_INVALID_PAGINATION)


class TestSaleVenueRecordContracts:
    """POST /venues: the three commercial parameters and their bounds."""

    @pytest.mark.parametrize(
        "field, value",
        [
            ("concurrent_lot_capacity", 0),
            ("buyer_premium_pct", 0.31),
            ("sales_tax_pct", 0.16),
        ],
        ids=["capacity_below_one", "premium_above_maximum", "tax_above_maximum"],
    )
    def test_venue_rate_and_capacity_bounds_are_enforced(self, api, field, value):
        """PRD 3.1: "`concurrent_lot_capacity` is the maximum number of lots whose
        sale windows may overlap at the venue at any instant and must be at least
        1."
        PRD 3.1: "`buyer_premium_pct` is the premium charged to the winning buyer on
        top of the hammer price, expressed as a decimal fraction between 0 and 0.30
        inclusive."
        PRD 3.1: "`sales_tax_pct` is the tax rate applied to hammer price plus
        premium, expressed as a decimal fraction between 0 and 0.15 inclusive."
        PRD 2.12: "Request shape: every required input present, non-null and of the
        declared JSON type, and every string-length and numeric-range constraint
        satisfied — otherwise `ERR_INVALID_REQUEST` (400)."

        Design: Corner/entities/entity_venue_rate_bounds_rejected
        """
        set_clock(CLOCK_EPOCH)
        payload = {
            "name": "Austin Surplus Yard",
            "venue_code": "AUS-01",
            "concurrent_lot_capacity": 2,
            "buyer_premium_pct": 0.105,
            "sales_tax_pct": 0.0635,
        }
        payload[field] = value

        response = api.create_venue(payload, ADMIN)

        validate_error(response, ApiErrorId.ERR_INVALID_REQUEST)

        _, meta = validate_paginated(api.list_venues(ADMIN))
        assert meta["total_count"] == 0, (
            "an out-of-range commercial parameter must persist no venue, got "
            f"total_count {meta['total_count']}"
        )

    def test_venue_accepts_the_inclusive_upper_bounds(self, api):
        """PRD 3.1: "`concurrent_lot_capacity` is the maximum number of lots whose
        sale windows may overlap at the venue at any instant and must be at least
        1."
        PRD 3.1: "`buyer_premium_pct` is the premium charged to the winning buyer on
        top of the hammer price, expressed as a decimal fraction between 0 and 0.30
        inclusive."
        PRD 3.1: "`sales_tax_pct` is the tax rate applied to hammer price plus
        premium, expressed as a decimal fraction between 0 and 0.15 inclusive."
        PRD 3.1: "A new venue opens with `status` `ACTIVE` and an `active_lot_count`
        of 0."

        Design: Corner/entities/entity_venue_rate_bounds_rejected
        """
        set_clock(CLOCK_EPOCH)

        response = api.create_venue(
            {
                "name": "Austin Surplus Yard",
                "venue_code": "AUS-01",
                "concurrent_lot_capacity": 1,
                "buyer_premium_pct": 0.30,
                "sales_tax_pct": 0.15,
            },
            ADMIN,
        )

        data = validate_success(response, 201)
        assert_sale_venue(data)
        assert data["concurrent_lot_capacity"] == 1, (
            "a capacity of exactly 1 is the accepted minimum, got "
            f"{data['concurrent_lot_capacity']}"
        )
        assert float(data["buyer_premium_pct"]) == 0.30, (
            f"0.30 is inclusive on the premium bound, got {data['buyer_premium_pct']!r}"
        )
        assert float(data["sales_tax_pct"]) == 0.15, (
            f"0.15 is inclusive on the tax bound, got {data['sales_tax_pct']!r}"
        )
        assert data["status"] == "ACTIVE", (
            f"a new venue opens ACTIVE, got {data['status']}"
        )
        assert data["active_lot_count"] == 0, (
            f"a new venue opens with an active_lot_count of 0, got {data['active_lot_count']}"
        )
        assert data["version"] == 1, (
            f"version starts at 1 on insert, got {data['version']}"
        )
