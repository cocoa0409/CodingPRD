"""Queue B — entity creation, retrieval, listing and input constraints."""
import pytest

from test_helpers import (
    api_client, validate_success, validate_error, validate_paginated,
    get_success_data, create_fund, create_open_protocol, create_facility,
    create_referral, screen_referral, arrive_referral, set_clock,
    TEST_USERS, ApiErrorId, NON_EXISTENT_UUID,
    current_protocol_version,
)


class TestReferralCreation:

    def test_creation_derives_the_eligibility_alias_and_age(self, logical_clock):
        """PRD §3.2: "The submission computes the `eligibility_alias` — the
        child's name lowercased with runs of whitespace collapsed to a single
        hyphen — which becomes the stable screening identity that guards against
        the same child being admitted twice."

        Design: Corner/entities/entity_create_referral_returns_computed_alias_and_age
        """
        fund = create_fund()
        protocol = create_open_protocol(fund["id"])

        res = api_client.create_referral(
            {"protocol_id": protocol["id"], "child_name": "Ava  Reyes",
             "child_date_of_birth": "2015-04-01T00:00:00Z", "disease_group": "ALL",
             "disease_stage": "NEWLY_DIAGNOSED", "household_state_code": "TN",
             "traveling_family_member_count": 3, "expected_treatment_days": 245,
             "is_immunosuppressed": True, "insurance_coverage_cents": 4_000_000},
            TEST_USERS["intake_coordinator_headers"],
        )
        referral = validate_success(res, 201)
        assert referral["child_name"] == "Ava  Reyes"
        assert referral["eligibility_alias"] == "ava-reyes"
        assert referral["computed_age_years"] == 11
        assert referral["status"] == "SUBMITTED"
        assert referral["applied_tier"] == "PENDING"
        assert referral["version"] == 1
        assert referral["screening_fee_cents"] == 0
        assert isinstance(referral["id"], str) and referral["id"]
        assert referral["created_at"] and referral["updated_at"]


class TestProtocolRetrieval:

    def test_declared_fields_and_derived_bands_round_trip(self, logical_clock):
        """PRD §2.5: "`age_tier` is `PAEDIATRIC` when the protocol's
        `age_max_years` is below 12, `ADOLESCENT` when `age_min_years` is 12 or
        above, and `MIXED` when the band spans that boundary."
        PRD §2.5: "`mental_capacity_floor` is the larger of the protocol's
        `age_min_years` and 7"

        Design: Corner/entities/entity_get_protocol_round_trips_declared_fields
        """
        fund = create_fund()
        protocol = get_success_data(api_client.create_protocol(
            {"fund_id": fund["id"], "protocol_code": "ALL-INT-001", "disease_group": "ALL",
             "age_min_years": 5, "age_max_years": 17, "required_stage": "NEWLY_DIAGNOSED",
             "protocol_budget_cents": 10_000_000, "capacity": 8},
            TEST_USERS["protocol_coordinator_headers"]))

        read_back = validate_success(api_client.get_protocol(
            protocol["id"], TEST_USERS["any_headers"]), 200)
        assert read_back["protocol_code"] == "ALL-INT-001"
        assert read_back["disease_group"] == "ALL"
        assert read_back["age_min_years"] == 5
        assert read_back["age_max_years"] == 17
        assert read_back["required_stage"] == "NEWLY_DIAGNOSED"
        assert read_back["capacity"] == 8
        assert read_back["enrolled_count"] == 0
        assert read_back["protocol_budget_cents"] == 10_000_000
        assert read_back["reserved_cents"] == 0
        assert read_back["available_cents"] == 10_000_000
        assert read_back["age_tier"] == "MIXED"
        assert read_back["mental_capacity_floor"] == 7


class TestHousingAssignmentListing:

    def test_pagination_counts_the_whole_filtered_set(self, logical_clock):
        """PRD §2.3: "`limit` caps how many items are returned and defaults to
        10; its minimum accepted value is 1 and its maximum is 100. `offset` is
        the number of items to skip and defaults to 0."

        Design: Corner/entities/entity_list_housing_assignments_paginates_with_total_count
        """
        fund = create_fund()
        protocol = create_open_protocol(fund["id"])
        create_facility(facility_code="ONC-01", total_beds=6, buffer_beds=0)
        referral = create_referral(protocol["id"], is_immunosuppressed=True)
        screened = validate_success(api_client.screen_referral(
            referral["id"], {"expected_protocol_version": current_protocol_version(protocol["id"])},
            TEST_USERS["intake_coordinator_headers"]), 200)
        arrived = arrive_referral(referral["id"], screened["version"])
        enrollment_id = arrived["enrollment_id"]

        for start, end in (("2026-09-01", "2026-09-05"), ("2026-09-06", "2026-09-10"),
                           ("2026-09-11", "2026-09-15")):
            validate_success(api_client.create_assignment(
                {"enrollment_id": enrollment_id, "start_at": f"{start}T00:00:00Z",
                 "end_at": f"{end}T00:00:00Z", "buffer_window_days": 1},
                TEST_USERS["housing_coordinator_headers"]), 201)

        first_page, meta_first = validate_paginated(api_client.list_assignments(
            TEST_USERS["any_headers"], params={"enrollment_id": enrollment_id,
                                               "limit": 2, "offset": 0}))
        assert len(first_page) == 2
        assert meta_first["total_count"] == 3
        assert meta_first["has_more"] is True

        second_page, meta_second = validate_paginated(api_client.list_assignments(
            TEST_USERS["any_headers"], params={"enrollment_id": enrollment_id,
                                               "limit": 2, "offset": 2}))
        assert len(second_page) == 1
        assert meta_second["total_count"] == 3
        assert meta_second["has_more"] is False

    def test_default_page_returns_every_row(self, logical_clock):
        """PRD §2.3: "No list endpoint in this program is unpaginated — every
        collection response carries `limit`, `offset`, `total_count`, and
        `has_more` in the `meta` object"

        Design: Corner/entities/entity_list_housing_assignments_paginates_with_total_count
        """
        fund = create_fund()
        protocol = create_open_protocol(fund["id"])
        create_facility(facility_code="ONC-01", total_beds=6, buffer_beds=0)
        referral = create_referral(protocol["id"], is_immunosuppressed=True)
        screened = validate_success(api_client.screen_referral(
            referral["id"], {"expected_protocol_version": current_protocol_version(protocol["id"])},
            TEST_USERS["intake_coordinator_headers"]), 200)
        arrived = arrive_referral(referral["id"], screened["version"])
        enrollment_id = arrived["enrollment_id"]

        for start, end in (("2026-09-01", "2026-09-05"), ("2026-09-06", "2026-09-10"),
                           ("2026-09-11", "2026-09-15")):
            validate_success(api_client.create_assignment(
                {"enrollment_id": enrollment_id, "start_at": f"{start}T00:00:00Z",
                 "end_at": f"{end}T00:00:00Z", "buffer_window_days": 1},
                TEST_USERS["housing_coordinator_headers"]), 201)

        data, meta = validate_paginated(api_client.list_assignments(TEST_USERS["any_headers"]))
        assert len(data) == 3
        assert meta["limit"] == 10
        assert meta["offset"] == 0
        assert all(row["status"] == "SCHEDULED" for row in data)


class TestEntitySpecificNotFound:

    def test_unknown_referral_id_reports_the_entity_specific_code(self, logical_clock):
        """PRD §2.9: "Where the scaffold declares an entity-specific not-found
        code the server returns it in place of the generic one —
        `ERR_REFERRAL_NOT_FOUND`"
        PRD §2.9: "a read that names a protocol and then a hold beneath it must
        fail on the protocol first"

        Design: Corner/entities/entity_get_referral_with_unknown_id_returns_referral_not_found
        """
        res = api_client.get_referral(NON_EXISTENT_UUID, TEST_USERS["any_headers"])
        validate_error(res, ApiErrorId.ERR_REFERRAL_NOT_FOUND)
        assert res.status_code == 404
        body = res.json()
        assert body["response_type"] == "error"
        assert body["data"]["error_id"] and body["data"]["message"]


class TestRequiredAndDefaultFields:

    def test_protocol_without_capacity_is_rejected(self, logical_clock):
        """PRD §3.1: "A `ProtocolCoordinator` creates a clinical protocol by
        naming the fund that will carry it, a `protocol_code` unique across the
        whole program, the `disease_group` it treats, the inclusive age band
        through `age_min_years` and `age_max_years`, the `required_stage` a
        referral must carry to be screen-eligible, a `protocol_budget_cents`, and
        a `capacity`."

        Design: Corner/entities/entity_create_protocol_without_capacity_returns_invalid_request
        """
        fund = create_fund()
        res = api_client.create_protocol(
            {"fund_id": fund["id"], "protocol_code": "ALL-NOCAP", "disease_group": "ALL",
             "age_min_years": 5, "age_max_years": 17, "required_stage": "NEWLY_DIAGNOSED",
             "protocol_budget_cents": 10_000_000},
            TEST_USERS["protocol_coordinator_headers"])
        error = validate_error(res, ApiErrorId.ERR_INVALID_REQUEST)
        assert error["error_id"] != ApiErrorId.ERR_DUPLICATE_ENTITY
        assert error["error_id"] != ApiErrorId.ERR_FUND_NOT_FOUND

        data, meta = validate_paginated(api_client.list_protocols(
            TEST_USERS["any_headers"], params={"fund_id": fund["id"]}))
        assert meta["total_count"] == 0

    def test_fund_defaults_omitted_donation_fields_to_zero(self, logical_clock):
        """PRD §2.4: "The campaign records what was raised in
        `fundraising_raised_cents` and what arrived as a federal grant in
        `federal_grant_cents`, both in integer cents."
        PRD §2.4: "recording a later donation through the fund's donation
        capability changes the totals a subsequent read reports"

        Design: Corner/entities/entity_create_fund_defaults_optional_donations_to_zero
        """
        res = api_client.create_fund(
            {"fund_code": "SJ-EMPTY", "fiscal_year": 2026, "research_allocation_pct": 0.5},
            TEST_USERS["platform_admin_headers"])
        fund = validate_success(res, 201)
        assert fund["fundraising_raised_cents"] == 0
        assert fund["federal_grant_cents"] == 0
        assert fund["research_balance_cents"] == 0
        assert fund["patient_support_balance_cents"] == 0


class TestFacilityInputHandling:

    def test_system_owned_status_is_not_accepted_from_input(self, logical_clock):
        """PRD §2.6: "A facility's `status` is `OPEN`, `SUSPENDED`, or `CLOSED`,
        and only an `OPEN` residence is offered to the selector."

        Design: Corner/entities/entity_create_facility_extra_field_status_is_ignored_input
        """
        res = api_client.create_facility(
            {"facility_code": "ONC-99", "name": "Campus Residence", "tier": "ON_CAMPUS",
             "total_beds": 4, "buffer_beds": 0, "status": "CLOSED", "version": 99},
            TEST_USERS["housing_coordinator_headers"])
        facility = validate_success(res, 201)
        assert facility["status"] == "OPEN"
        assert facility["version"] == 1
        assert facility["is_on_campus"] is True
        assert facility["is_partner_site"] is False

    def test_out_of_enum_tier_is_rejected(self, logical_clock):
        """PRD §2.6: "The tier is one of `ON_CAMPUS`, `PARTNER_CLASS_A`,
        `PARTNER_CLASS_B`, or `PARTNER_CLASS_C`."

        Design: Corner/entities/entity_create_facility_with_out_of_enum_tier_returns_invalid_request
        """
        res = api_client.create_facility(
            {"facility_code": "BAD-01", "name": "Nowhere", "tier": "HOTEL_SUITE",
             "total_beds": 4, "buffer_beds": 0},
            TEST_USERS["housing_coordinator_headers"])
        validate_error(res, ApiErrorId.ERR_INVALID_REQUEST)

        data, meta = validate_paginated(api_client.list_facilities(TEST_USERS["any_headers"]))
        assert meta["total_count"] == 0


class TestDeclaredUniqueness:

    def test_duplicate_protocol_code_is_rejected(self, logical_clock):
        """PRD §2.13: "Declared uniqueness follows: `protocol_code` is unique
        across the program, as are `facility_code` and `clinic_code`; A collision
        reports `ERR_DUPLICATE_ENTITY` (HTTP 409)."

        Design: Corner/entities/entity_create_second_protocol_with_same_code_returns_duplicate_entity
        """
        fund = create_fund()
        first = get_success_data(api_client.create_protocol(
            {"fund_id": fund["id"], "protocol_code": "ALL-INT-001", "disease_group": "ALL",
             "age_min_years": 5, "age_max_years": 17, "required_stage": "NEWLY_DIAGNOSED",
             "protocol_budget_cents": 10_000_000, "capacity": 8},
            TEST_USERS["protocol_coordinator_headers"]))

        res = api_client.create_protocol(
            {"fund_id": fund["id"], "protocol_code": "ALL-INT-001", "disease_group": "ALL",
             "age_min_years": 1, "age_max_years": 4, "required_stage": "RELAPSED",
             "protocol_budget_cents": 2_000_000, "capacity": 3},
            TEST_USERS["protocol_coordinator_headers"])
        error = validate_error(res, ApiErrorId.ERR_DUPLICATE_ENTITY)
        assert error["error_id"] != ApiErrorId.ERR_INVALID_REQUEST

        data, meta = validate_paginated(api_client.list_protocols(
            TEST_USERS["any_headers"], params={"fund_id": fund["id"]}))
        assert meta["total_count"] == 1
        assert data[0]["protocol_code"] == "ALL-INT-001"


class TestBodyForeignKeyValidation:

    def test_unknown_enrollment_id_reports_enrollment_not_found(self, logical_clock):
        """PRD §2.9: "Foreign keys supplied in a request body are validated next,
        in the order the endpoint's input list declares them, and a missing body
        foreign key yields the generic `ERR_NOT_FOUND` rather than an
        entity-specific code."

        Design: Corner/entities/entity_pledge_body_fk_fails_before_state_check
        """
        fund = create_fund()
        protocol = create_open_protocol(fund["id"])
        create_facility(facility_code="ONC-01", total_beds=4, buffer_beds=0)
        referral = create_referral(protocol["id"], is_immunosuppressed=True)
        screened = validate_success(api_client.screen_referral(
            referral["id"], {"expected_protocol_version": current_protocol_version(protocol["id"])},
            TEST_USERS["intake_coordinator_headers"]), 200)
        arrived = arrive_referral(referral["id"], screened["version"])

        res = api_client.create_pledge(
            {"enrollment_id": NON_EXISTENT_UUID, "patient_support_budget_cents": 400_000},
            TEST_USERS["patient_support_officer_headers"])
        error = validate_error(res, ApiErrorId.ERR_ENROLLMENT_NOT_FOUND)

        data, meta = validate_paginated(api_client.list_pledges(
            TEST_USERS["any_headers"], params={"enrollment_id": arrived["enrollment_id"]}))
        assert meta["total_count"] == 0