"""Input-validation corners on the intake half of the pipeline.

Request shape and numeric-range bounds, enum values against pagination bounds,
the conditionally required fields of asset creation and organisation
registration, future-date refusal, the two registry collation rules, the
same-turn-in component restriction, body foreign-key resolution order, and the
ordering between organisation suspension and tier priority.
"""

import pytest

from test_helpers import (
    ADMIN,
    ApiErrorId,
    api_client,
    assess_asset,
    create_agency_payload,
    create_asset_payload,
    create_bidder_payload,
    create_clearance_certificate_payload,
    create_condition_assessment_payload,
    create_draft_turn_in,
    create_screening_request_payload,
    create_venue_payload,
    create_vehicle_asset_payload,
    make_agency_officer_headers,
    make_clearance_technician_headers,
    make_surplus_assessor_headers,
    read_agency,
    read_asset,
    read_bidder,
    read_turn_in,
    register_agency,
    register_bidder,
    register_state_agency,
    register_venue,
    set_clock,
    submit_turn_in,
    validate_error,
    validate_paginated,
    validate_success,
)

# An identifier that matches no row of any entity.
MISSING_ID = "00000000-0000-4000-8000-000000000000"


def _draft_turn_in_with_agency(custody_location="Austin Yard 4"):
    """One ACTIVE state organisation holding one DRAFT turn-in."""
    set_clock()
    agency = register_state_agency()
    turn_in = create_draft_turn_in(agency["id"], custody_location=custody_location)
    return agency, turn_in


class TestRequestShapeAndNumericRanges:
    """The request-shape rule covers absent fields and out-of-range numbers."""

    def test_absent_field_and_out_of_range_numbers_are_all_invalid_request(self):
        """An absent required input and every violated numeric bound answer the
        same request-shape code, and the corrected payload then succeeds.

        PRD: "Request shape: every required input present, non-null and of the
        declared JSON type, and every string-length and numeric-range constraint
        satisfied — otherwise `ERR_INVALID_REQUEST` (400)."
        PRD: "An **organisation** — a state agency, a city or county, or an
        eligible nonprofit — is registered with a legal `name` of 1 to 160
        characters, a short operator-facing `agency_code` of 1 to 24 characters,
        and an `agency_type` of `STATE_AGENCY`, `LOCAL_GOVERNMENT` or
        `ELIGIBLE_NONPROFIT`."
        PRD: "`concurrent_lot_capacity` is the maximum number of lots whose sale
        windows may overlap at the venue at any instant and must be at least 1."
        PRD: "`buyer_premium_pct` is the premium charged to the winning buyer on
        top of the hammer price, expressed as a decimal fraction between 0 and
        0.30 inclusive."
        PRD: "An item is described by a `category` — one of `VEHICLE`,
        `IT_EQUIPMENT`, `FURNITURE`, `HEAVY_EQUIPMENT` or `RESTRICTED_MILITARY`
        — a `description` of 1 to 200 characters, an `acquisition_cost_cents`
        that must be strictly greater than zero, and an `acquisition_date`
        giving the calendar date on which the turning-in agency originally
        acquired it."

        Design: Corner/validations/val_required_field_and_numeric_range_rejected
        """
        agency, turn_in = _draft_turn_in_with_agency()
        officer = make_agency_officer_headers(agency["id"])

        no_code = api_client.create_agency(
            {"name": "Texas Facilities Commission", "agency_type": "STATE_AGENCY"},
            ADMIN,
        )
        validate_error(no_code, ApiErrorId.ERR_INVALID_REQUEST)

        premium_too_high = api_client.create_venue(
            create_venue_payload(
                name="Dallas Auction Yard", venue_code="DAL-01",
                concurrent_lot_capacity=2, buyer_premium_pct=1.5,
                sales_tax_pct=0.0635,
            ),
            ADMIN,
        )
        validate_error(premium_too_high, ApiErrorId.ERR_INVALID_REQUEST)

        capacity_zero = api_client.create_venue(
            create_venue_payload(
                name="Dallas Auction Yard", venue_code="DAL-01",
                concurrent_lot_capacity=0, buyer_premium_pct=0.105,
                sales_tax_pct=0.0635,
            ),
            ADMIN,
        )
        validate_error(capacity_zero, ApiErrorId.ERR_INVALID_REQUEST)

        zero_cost = api_client.create_asset(
            create_asset_payload(
                turn_in["id"], description="Guest chair set",
                acquisition_cost_cents=0, acquisition_date="2026-01-10",
            ),
            officer,
        )
        validate_error(zero_cost, ApiErrorId.ERR_INVALID_REQUEST)

        accepted = api_client.create_asset(
            create_asset_payload(
                turn_in["id"], description="Guest chair set",
                acquisition_cost_cents=104500, acquisition_date="2026-01-10",
            ),
            officer,
        )
        asset = validate_success(accepted, 201)
        assert asset["acquisition_cost_cents"] == 104500, (
            "the corrected create must persist the supplied whole-cent cost"
        )

        _, agency_meta = validate_paginated(api_client.list_agencies(ADMIN))
        assert agency_meta["total_count"] == 1, (
            "the refused organisation must not have been persisted"
        )
        _, venue_meta = validate_paginated(api_client.list_venues(ADMIN))
        assert venue_meta["total_count"] == 0, (
            "neither refused venue may leave a row behind"
        )
        assert read_turn_in(turn_in["id"])["asset_count"] == 1, (
            "asset_count must count only the one accepted asset"
        )


class TestEnumValueBeforePaginationBounds:
    """Enum validation is ranked ahead of the pagination-bound check."""

    def test_unknown_enum_filter_outranks_out_of_range_limit(self):
        """One list request carrying both an unknown enum filter and an
        out-of-range limit answers with the enum code, because the enum rule is
        listed ahead of the pagination rule.

        PRD: "Every enum-typed input carries a value from that enum's declared
        set — otherwise `ERR_INVALID_ENUM_VALUE` (422)."
        PRD: "`limit` and `offset` within their permitted ranges on list
        endpoints — otherwise `ERR_INVALID_PAGINATION` (400)."
        PRD: "When several rules could reject the same request, the **first**
        rule violated in the order below determines the response, and no later
        rule is evaluated."

        Design: Corner/validations/val_enum_value_outranks_pagination_bounds
        """
        set_clock()
        register_state_agency()

        both_faults = api_client.list_assets(
            ADMIN, {"disposition_status": "SCRAPPED", "limit": 0}
        )
        validate_error(both_faults, ApiErrorId.ERR_INVALID_ENUM_VALUE)

    @pytest.mark.parametrize(
        "params",
        [
            {"disposition_status": "ASSESSED", "limit": 0},
            {"disposition_status": "ASSESSED", "limit": 101},
            {"disposition_status": "ASSESSED", "limit": 20, "offset": -1},
        ],
        ids=["limit_below_minimum", "limit_above_maximum", "negative_offset"],
    )
    def test_pagination_bounds_are_enforced_with_a_valid_filter(self, params):
        """With a legal enum filter the out-of-range window parameters surface
        the pagination code on their own.

        PRD: "`limit` caps the number of rows returned; it defaults to 10 when
        omitted, its minimum accepted value is 1 and its maximum is 100."
        PRD: "A `limit` outside the range 1 through 100 inclusive, or a negative
        `offset`, or a non-integer value for either, is rejected with
        `ERR_INVALID_PAGINATION` (HTTP 400)."

        Design: Corner/validations/val_enum_value_outranks_pagination_bounds
        """
        set_clock()
        register_state_agency()

        resp = api_client.list_assets(ADMIN, params)
        validate_error(resp, ApiErrorId.ERR_INVALID_PAGINATION)

    def test_unknown_action_enum_rejected_and_upper_pagination_bound_accepted(self):
        """An unknown enum on a write action changes nothing, and a limit of
        exactly 100 sits inside the accepted range.

        PRD: "Every enum-typed input carries a value from that enum's declared
        set — otherwise `ERR_INVALID_ENUM_VALUE` (422)."
        PRD: "`limit` caps the number of rows returned; it defaults to 10 when
        omitted, its minimum accepted value is 1 and its maximum is 100."
        PRD: "A freshly registered organisation starts with `status` `ACTIVE`, a
        `proceeds_account_balance_cents` of 0 — a figure that never goes below
        zero — and a `posted_distribution_count` of 0."

        Design: Corner/validations/val_enum_value_outranks_pagination_bounds
        """
        set_clock()
        agency = register_state_agency()

        bad_status = api_client.set_agency_status(agency["id"], "ARCHIVED", ADMIN)
        validate_error(bad_status, ApiErrorId.ERR_INVALID_ENUM_VALUE)
        assert read_agency(agency["id"])["status"] == "ACTIVE", (
            "a refused status action must leave the organisation ACTIVE"
        )

        rows, meta = validate_paginated(
            api_client.list_assets(
                ADMIN, {"disposition_status": "ASSESSED", "limit": 100, "offset": 0}
            )
        )
        assert rows == [], "no asset exists yet, so the window must be empty"
        assert meta["total_count"] == 0, "total_count must be 0"
        assert meta["limit"] == 100, "a limit of 100 is inside the inclusive bound"
        assert meta["offset"] == 0, "offset must echo the requested 0"


class TestConditionallyRequiredFields:
    """The conditional-field rule guards asset creation and registration."""

    def test_vehicle_triple_is_not_satisfied_piecemeal(self):
        """A VEHICLE needs all three documentary fields at once: none, one and
        two of them are each refused, only the full triple is accepted, and a
        FURNITURE item in the same turn-in needs none of them.

        PRD: "Vehicles carry their own documentary triple: when `category` is
        `VEHICLE`, the `vin`, the `odometer_reading` and the `title_number` are
        all mandatory, and any of the three missing is
        `ERR_CONDITIONAL_FIELD_REQUIRED`."
        PRD: "For non-vehicles all three are null."
        PRD: "`asset_count` is the number of assets whose `turn_in_id` is this
        turn-in, counted across every `disposition_status` value without
        exception."

        Design: Corner/validations/val_vehicle_conditional_fields_required_then_satisfied
        """
        agency, turn_in = _draft_turn_in_with_agency("Austin Fleet Pool")
        officer = make_agency_officer_headers(agency["id"])
        base = {
            "turn_in_id": turn_in["id"],
            "category": "VEHICLE",
            "description": "2016 half-ton pickup",
            "acquisition_cost_cents": 2800000,
            "acquisition_date": "2016-04-11",
        }

        for extra in (
            {},
            {"vin": "1FTEW1E45JKE12345"},
            {"vin": "1FTEW1E45JKE12345", "odometer_reading": 148320},
        ):
            resp = api_client.create_asset({**base, **extra}, officer)
            validate_error(resp, ApiErrorId.ERR_CONDITIONAL_FIELD_REQUIRED)

        vehicle = validate_success(
            api_client.create_asset(
                {
                    **base,
                    "vin": "1FTEW1E45JKE12345",
                    "odometer_reading": 148320,
                    "title_number": "TX-77410992",
                },
                officer,
            ),
            201,
        )
        assert vehicle["vin"] == "1FTEW1E45JKE12345", "vin must persist as supplied"
        assert vehicle["odometer_reading"] == 148320, "odometer_reading must persist"
        assert vehicle["title_number"] == "TX-77410992", "title_number must persist"
        assert vehicle["clearance_status"] == "NOT_REQUIRED", (
            "a plain vehicle is neither data-bearing nor restricted, so no "
            "release gate opens at intake"
        )

        furniture = validate_success(
            api_client.create_asset(
                create_asset_payload(
                    turn_in["id"], description="Dispatch desk",
                    acquisition_cost_cents=104500, acquisition_date="2024-05-20",
                ),
                officer,
            ),
            201,
        )
        assert furniture["vin"] is None, (
            "the documentary triple is required only for VEHICLE items"
        )
        assert read_turn_in(turn_in["id"])["asset_count"] == 2, (
            "the three refused attempts must have persisted nothing"
        )

    def test_restricted_federal_and_donee_flags_each_demand_their_partner_field(self):
        """The same conditional-field code guards three flag-driven pairs across
        asset creation and organisation registration, and the accepted federal
        item shows the derived use-period end date.

        PRD: "`is_restricted` marks a controlled or restricted article that
        needs demilitarisation before it can leave; it also defaults to false,
        and when it is true a `demil_code` of `A`, `B`, `C`, `D` or `Q` is
        mandatory — its absence is rejected with
        `ERR_CONDITIONAL_FIELD_REQUIRED`, and for an unrestricted item the
        `demil_code` is null."
        PRD: "`federal_source` marks an item that the turning-in agency itself
        received as federal surplus donation and which therefore carries a use
        period; it defaults to false, and when it is true a
        `federal_use_period_start_on` date is mandatory, again under
        `ERR_CONDITIONAL_FIELD_REQUIRED`."
        PRD: "Where `federal_donee_status` is submitted as `CERTIFIED`, the
        expiry date is mandatory and its absence is rejected with
        `ERR_CONDITIONAL_FIELD_REQUIRED`; where the donee status is `NONE`, the
        expiry date is null."
        PRD: "Its `federal_use_period_end_on` is computed at creation by adding
        a category-dependent number of calendar months to
        `federal_use_period_start_on`: eighteen months for a `VEHICLE`, a
        `HEAVY_EQUIPMENT` item or a `RESTRICTED_MILITARY` article, and twelve
        months for `IT_EQUIPMENT` or `FURNITURE`."

        Design: Corner/validations/val_restricted_federal_and_donee_conditional_fields_required
        """
        agency, turn_in = _draft_turn_in_with_agency("Camp Swift Storage")
        officer = make_agency_officer_headers(agency["id"])
        restricted = {
            "turn_in_id": turn_in["id"],
            "category": "RESTRICTED_MILITARY",
            "description": "Armored door kit",
            "acquisition_cost_cents": 900000,
            "acquisition_date": "2019-06-01",
            "is_restricted": True,
        }
        federal = {
            "turn_in_id": turn_in["id"],
            "category": "IT_EQUIPMENT",
            "description": "Donated server rack",
            "acquisition_cost_cents": 700000,
            "acquisition_date": "2025-03-31",
            "federal_source": True,
        }
        donee = create_agency_payload(
            name="Hill Country Youth Services", agency_code="NPO-04",
            agency_type="ELIGIBLE_NONPROFIT", federal_donee_status="CERTIFIED",
        )

        validate_error(
            api_client.create_asset(restricted, officer),
            ApiErrorId.ERR_CONDITIONAL_FIELD_REQUIRED,
        )
        validate_error(
            api_client.create_asset(federal, officer),
            ApiErrorId.ERR_CONDITIONAL_FIELD_REQUIRED,
        )
        validate_error(
            api_client.create_agency(donee, ADMIN),
            ApiErrorId.ERR_CONDITIONAL_FIELD_REQUIRED,
        )

        restricted_row = validate_success(
            api_client.create_asset({**restricted, "demil_code": "C"}, officer), 201
        )
        assert restricted_row["demil_code"] == "C", "demil_code must persist"
        assert restricted_row["clearance_status"] == "REQUIRED_PENDING", (
            "the restricted flag opens the clearance axis at creation"
        )

        federal_row = validate_success(
            api_client.create_asset(
                {**federal, "federal_use_period_start_on": "2025-03-31"}, officer
            ),
            201,
        )
        assert federal_row["federal_use_period_start_on"] == "2025-03-31", (
            "the supplied use-period start date must persist"
        )
        assert federal_row["federal_use_period_end_on"] == "2026-03-31", (
            "IT_EQUIPMENT carries a twelve-month federal use period"
        )
        assert federal_row["clearance_status"] == "NOT_REQUIRED", (
            "federal sourcing alone does not open the clearance axis"
        )

        nonprofit = validate_success(
            api_client.create_agency(
                {**donee, "donee_certification_expires_on": "2027-05-31"}, ADMIN
            ),
            201,
        )
        assert nonprofit["federal_donee_status"] == "CERTIFIED", (
            "the submitted donee status must persist"
        )
        assert nonprofit["donee_certification_expires_on"] == "2027-05-31", (
            "the mandatory expiry date must persist"
        )
        assert nonprofit["status"] == "ACTIVE", (
            "a freshly registered organisation starts ACTIVE"
        )

        _, agency_meta = validate_paginated(api_client.list_agencies(ADMIN))
        assert agency_meta["total_count"] == 2, (
            "the refused registration must not have been persisted"
        )
        assert read_turn_in(turn_in["id"])["asset_count"] == 2, (
            "the two refused asset creates must have persisted nothing"
        )


class TestFutureDatesRefused:
    """Three date inputs are compared against the logical clock's date."""

    def test_dates_equal_to_the_clock_date_pass_and_the_next_day_fails(self):
        """acquisition_date, assessed_on and certified_on are each accepted at
        the clock's own date and each refused one day later; the refused
        assessment does not consume the asset's version.

        PRD: "That date may not be later than the logical clock's date; a future
        acquisition date is rejected with `ERR_FUTURE_DATE`."
        PRD: "An `assessed_on` later than the logical clock date is rejected
        with `ERR_FUTURE_DATE`."
        PRD: "The `certified_on` date may not be in the future relative to the
        logical clock, refused with `ERR_FUTURE_DATE`."

        Design: Corner/validations/val_future_dates_on_asset_assessment_and_certificate_rejected
        """
        agency, turn_in = _draft_turn_in_with_agency()
        officer = make_agency_officer_headers(agency["id"])
        laptop = {
            "turn_in_id": turn_in["id"],
            "category": "IT_EQUIPMENT",
            "description": "Laptop cart",
            "acquisition_cost_cents": 300000,
            "is_data_bearing": True,
        }

        validate_error(
            api_client.create_asset(
                {**laptop, "acquisition_date": "2026-08-02"}, officer
            ),
            ApiErrorId.ERR_FUTURE_DATE,
        )
        asset = validate_success(
            api_client.create_asset(
                {**laptop, "acquisition_date": "2026-08-01"}, officer
            ),
            201,
        )
        submit_turn_in(agency["id"], turn_in["id"])

        future_assessment = api_client.create_condition_assessment(
            asset["id"],
            create_condition_assessment_payload(
                asset["version"], condition_code="C3", functional=True,
                repair_cost_estimate_cents=0, assessed_on="2026-08-02",
            ),
            make_surplus_assessor_headers(),
        )
        validate_error(future_assessment, ApiErrorId.ERR_FUTURE_DATE)
        assess_asset(
            asset["id"], asset["version"], condition_code="C3", functional=True,
            repair_cost_estimate_cents=0, assessed_on="2026-08-01",
        )

        future_certificate = api_client.create_clearance_certificate(
            asset["id"],
            create_clearance_certificate_payload(certified_on="2026-08-02"),
            make_clearance_technician_headers(),
        )
        validate_error(future_certificate, ApiErrorId.ERR_FUTURE_DATE)
        certificate = validate_success(
            api_client.create_clearance_certificate(
                asset["id"],
                create_clearance_certificate_payload(certified_on="2026-08-01"),
                make_clearance_technician_headers(),
            ),
            201,
        )

        stored = read_asset(asset["id"])
        assert stored["condition_code"] == "C3", (
            "the accepted assessment must govern the valuation"
        )
        assert stored["fair_market_value_cents"] == 210000, (
            "300000 cents at condition factor 0.70 with no depreciation and no "
            "repair deduction values the item at 210000 cents"
        )
        assert stored["version"] == 3, (
            "only the two accepted writes may increment the asset's version: the "
            "assessment takes it from 1 to 2 and the accepted certificate takes it "
            "to 3, while neither refused future-dated attempt counts; got "
            f"{stored['version']}"
        )
        assert stored["clearance_status"] == "CLEARED", (
            "a verified sanitisation certificate completes the required set"
        )
        rows, meta = validate_paginated(
            api_client.list_clearance_certificates(asset["id"], ADMIN)
        )
        assert meta["total_count"] == 1, "the refused certificate persisted nothing"
        assert rows[0]["id"] == certificate["id"], (
            "the single stored certificate must be the accepted one"
        )


class TestRegistryUniquenessCollation:
    """agency_code compares case-sensitively; bidder email does not."""

    def test_duplicate_codes_report_their_own_errors_under_the_declared_collation(self):
        """A repeated agency_code, a repeated venue_code and an email differing
        only in case each report their own conflict code, while a lowercase
        agency_code is a distinct key and is accepted.

        PRD: "The `agency_code` must be unique across every organisation on
        file, compared case-sensitively and exactly, and a collision is rejected
        with `ERR_DUPLICATE_AGENCY_CODE`."
        PRD: "A **sale venue** is registered with a display `name` of 1 to 120
        characters and a `venue_code` of 1 to 24 characters that must be unique
        across all venues; a duplicate is rejected with
        `ERR_DUPLICATE_VENUE_CODE`."
        PRD: "A **bidder** registers with a `legal_name` of 1 to 160 characters,
        an `email` that must be unique across all bidders when compared
        case-insensitively — a collision is refused with
        `ERR_DUPLICATE_BIDDER_EMAIL` — and a `bidder_type` of `INDIVIDUAL` or
        `BUSINESS`."

        Design: Corner/validations/val_duplicate_code_checks_respect_declared_case_rules
        """
        set_clock()
        register_state_agency()
        register_venue(name="Austin Auction Yard", venue_code="AUS-01")
        incumbent = register_bidder(
            status="PENDING", legal_name="Cedar Ridge Salvage LLC",
            email="bids@cedarridge.example", bidder_type="BUSINESS",
        )

        validate_error(
            api_client.create_agency(
                create_agency_payload(
                    name="Different Department, Same Code", agency_code="DOT-01",
                    agency_type="LOCAL_GOVERNMENT",
                ),
                ADMIN,
            ),
            ApiErrorId.ERR_DUPLICATE_AGENCY_CODE,
        )
        lowercase = register_agency(
            name="Lowercase Code Department", agency_code="dot-01",
            agency_type="LOCAL_GOVERNMENT",
        )
        assert lowercase["agency_code"] == "dot-01", (
            "an exact case-sensitive comparison makes the lowercase code a "
            "different key"
        )

        validate_error(
            api_client.create_venue(
                create_venue_payload(
                    name="Austin Overflow Yard", venue_code="AUS-01",
                    concurrent_lot_capacity=1, buyer_premium_pct=0.10,
                    sales_tax_pct=0.06,
                ),
                ADMIN,
            ),
            ApiErrorId.ERR_DUPLICATE_VENUE_CODE,
        )
        validate_error(
            api_client.create_bidder(
                create_bidder_payload(
                    legal_name="Cedar Ridge Salvage LLC (second registration)",
                    email="BIDS@Cedarridge.EXAMPLE", bidder_type="INDIVIDUAL",
                ),
                ADMIN,
            ),
            ApiErrorId.ERR_DUPLICATE_BIDDER_EMAIL,
        )

        _, agencies = validate_paginated(api_client.list_agencies(ADMIN))
        assert agencies["total_count"] == 2, "only the distinct codes persisted"
        _, venues = validate_paginated(api_client.list_venues(ADMIN))
        assert venues["total_count"] == 1, "the duplicate venue persisted nothing"
        _, bidders = validate_paginated(api_client.list_bidders(ADMIN))
        assert bidders["total_count"] == 1, "the duplicate email persisted nothing"

        stored = read_bidder(incumbent["id"])
        assert stored["status"] == "PENDING", (
            "the refused registration must leave the incumbent untouched"
        )
        assert stored["deposit_paid_cents"] == 0, (
            "a freshly registered bidder holds no deposit"
        )


class TestComponentParentMustShareTurnIn:
    """A component's parent has to sit on the same turn-in."""

    def test_parent_on_another_turn_in_is_refused_while_the_same_turn_in_is_accepted(self):
        """Naming a parent that exists but belongs to a different turn-in is a
        component violation rather than a not-found, and the identical payload
        against a parent on the same turn-in is accepted.

        PRD: "The referenced asset must sit on the same `turn_in_id`, must not be
        the item being created, and must not be one of that item's own
        ancestors: the component graph must stay acyclic."
        PRD: "Any of those three violations is rejected with
        `ERR_ASSET_COMPONENT_CYCLE` (HTTP 422)."
        PRD: "`clearance_status` begins at `REQUIRED_PENDING` when either
        `is_data_bearing` or `is_restricted` is true, and at `NOT_REQUIRED` when
        both are false — in the latter case the release gate stands open from
        birth and no certificate may ever be filed against the item."

        Design: Corner/validations/val_component_parent_must_share_turn_in
        """
        agency, turn_in_a = _draft_turn_in_with_agency("Austin Fleet Pool")
        officer = make_agency_officer_headers(agency["id"])
        turn_in_b = create_draft_turn_in(agency["id"], custody_location="Austin Yard 4")
        parent = validate_success(
            api_client.create_asset(
                create_vehicle_asset_payload(turn_in_a["id"]), officer
            ),
            201,
        )
        component = {
            "category": "IT_EQUIPMENT",
            "description": "Telematics unit installed in the pickup",
            "acquisition_cost_cents": 90000,
            "acquisition_date": "2016-04-11",
            "is_data_bearing": True,
            "component_of_asset_id": parent["id"],
        }

        validate_error(
            api_client.create_asset(
                {**component, "turn_in_id": turn_in_b["id"]}, officer
            ),
            ApiErrorId.ERR_ASSET_COMPONENT_CYCLE,
        )
        child = validate_success(
            api_client.create_asset(
                {**component, "turn_in_id": turn_in_a["id"]}, officer
            ),
            201,
        )
        assert child["component_of_asset_id"] == parent["id"], (
            "the accepted component must record its parent"
        )
        assert child["clearance_status"] == "REQUIRED_PENDING", (
            "the data-bearing component carries its own release gate"
        )
        assert read_asset(parent["id"])["clearance_status"] == "NOT_REQUIRED", (
            "the parent does not inherit the component's release gate"
        )
        assert read_turn_in(turn_in_a["id"])["asset_count"] == 2, (
            "both accepted assets belong to the first turn-in"
        )
        assert read_turn_in(turn_in_b["id"])["asset_count"] == 0, (
            "the refused create must have persisted nothing"
        )
        _, meta = validate_paginated(
            api_client.list_assets(ADMIN, {"component_of_asset_id": parent["id"]})
        )
        assert meta["total_count"] == 1, "exactly one component names that parent"


class TestBodyForeignKeyResolution:
    """Body foreign keys resolve in entity field-declaration order."""

    def test_unknown_body_reference_and_conditional_gap_each_report_their_own_code(self):
        """An unknown turn-in reference answers the turn-in not-found code, the
        VEHICLE conditional gap answers the conditional-field code, and a payload
        carrying both answers the conditional-field code because that rule is
        listed ahead of body reference resolution.

        PRD: "Conditionally required fields present — otherwise
        `ERR_CONDITIONAL_FIELD_REQUIRED` (422)."
        PRD: "Every foreign key in the request body resolves, in entity
        field-declaration order — otherwise the matching 404 code."
        PRD: "When several rules could reject the same request, the **first**
        rule violated in the order below determines the response, and no later
        rule is evaluated."

        Design: Corner/validations/val_body_fk_not_found_outranks_conditional_field_check
        """
        agency, turn_in = _draft_turn_in_with_agency("Austin Fleet Pool")
        officer = make_agency_officer_headers(agency["id"])

        unknown_turn_in = api_client.create_asset(
            create_asset_payload(MISSING_ID), officer
        )
        validate_error(unknown_turn_in, ApiErrorId.ERR_TURN_IN_NOT_FOUND)

        vehicle_gap = {
            "turn_in_id": turn_in["id"],
            "category": "VEHICLE",
            "description": "2016 half-ton pickup",
            "acquisition_cost_cents": 2800000,
            "acquisition_date": "2016-04-11",
        }
        validate_error(
            api_client.create_asset(vehicle_gap, officer),
            ApiErrorId.ERR_CONDITIONAL_FIELD_REQUIRED,
        )
        validate_error(
            api_client.create_asset(
                {**vehicle_gap, "turn_in_id": MISSING_ID}, officer
            ),
            ApiErrorId.ERR_CONDITIONAL_FIELD_REQUIRED,
        )

        two_unknown_ids = api_client.create_screening_request(
            create_screening_request_payload(
                MISSING_ID, MISSING_ID, intended_use="Office refit",
                justification="Existing furniture is at end of life.",
            ),
            ADMIN,
        )
        validate_error(two_unknown_ids, ApiErrorId.ERR_SCREENING_CYCLE_NOT_FOUND)

        assert read_turn_in(turn_in["id"])["asset_count"] == 0, (
            "no refused asset create may be persisted"
        )
        _, meta = validate_paginated(api_client.list_screening_requests(ADMIN))
        assert meta["total_count"] == 0, (
            "the refused screening request must have persisted nothing"
        )
