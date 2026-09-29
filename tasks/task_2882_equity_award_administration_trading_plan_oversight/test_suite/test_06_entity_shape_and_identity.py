"""Entity shape, identity, defaults and foreign-key resolution.

Every test builds its own world from an empty database through the endpoints the
PRD declares, and asserts the field-level contract of the entity under test:
which fields the server mints, which optional inputs carry a defined default,
which computed fields ignore client input, and which foreign key is resolved
before the body is read.
"""

from test_helpers import (
    ADMIN,
    AUDITOR,
    COMPLIANCE,
    UNKNOWN_UUID,
    ApiErrorId,
    api_client,
    assert_equity_plan,
    assert_immutable_row_fields,
    assert_mobility_assignment,
    assert_participant,
    assert_reserve_conservation,
    assert_reserve_posture,
    assert_vesting_tranche,
    create_cycle,
    create_participant,
    create_plan,
    set_clock,
    validate_error,
    validate_paginated,
    validate_success,
)


class TestEquityPlanShape:
    def test_plan_creation_returns_every_declared_field_with_a_derived_ledger(self):
        """PRD §3.1: "A freshly registered plan is `ACTIVE` at `version` 1 with `freeze_reason` null, and all five of its accumulators start at zero: `shares_committed_cumulative`, `shares_returned_cumulative`, `fiscal_year_gross_granted_shares`, `fiscal_year_returned_shares`, and `evergreen_topup_last_shares`. Both reported rates, `gross_burn_rate_bps` and `net_burn_rate_bps`, likewise start at 0."

        PRD §3.1: "`available_reserve_shares` equals the `total_authorized_shares` minus `shares_committed_cumulative` plus `shares_returned_cumulative`."

        PRD §3.1: "From the same three integers the system derives `reserve_posture`, which is `OPEN` when the available reserve multiplied by 10000 is greater than or equal to `low_reserve_threshold_bps` multiplied by `total_authorized_shares`, and `RESTRICTED` otherwise."

        PRD §4: "A `POST` that brings a brand-new resource into existence returns HTTP 201 with the created resource in `data`: registering an equity plan, delegating an approval authority, enrolling a participant, recording a mobility assignment, drafting a grant, appending a vesting tranche, opening a performance cycle, vesting a tranche, scheduling a trading window, filing a preclearance request, and adopting a trading plan."

        Design: Corner/entities/equity_plan_creation_returns_all_declared_fields
        """
        set_clock("2026-01-05T09:00:00Z")

        payload = {
            "name": "Corner Plan Alpha",
            "total_authorized_shares": 1000000,
            "common_shares_outstanding": 1000000,
            "fiscal_year_start_date": "2026-01-01",
            "current_fiscal_year_label": "FY2026",
            "evergreen_pct_bps": 200,
            "evergreen_cap_shares": 50000,
            "burn_rate_limit_bps": 800,
            "fungible_ratio_full_value_bps": 15000,
            "low_reserve_threshold_bps": 2500,
            "next_earnings_release_at": "2026-02-10T21:00:00Z",
        }
        response = api_client.create_equity_plan(payload, ADMIN)
        plan = validate_success(response, 201)

        assert response.json()["response_type"] == "object", (
            "a single created resource is returned with response_type object"
        )
        assert_equity_plan(plan)

        assert plan["name"] == "Corner Plan Alpha", "the supplied name is stored verbatim"
        assert plan["total_authorized_shares"] == 1000000, "the authorised pool is stored"
        assert plan["common_shares_outstanding"] == 1000000, (
            "the burn-rate denominator is stored"
        )
        assert plan["fungible_ratio_full_value_bps"] == 15000, (
            "the fungible ratio is stored as supplied"
        )
        assert plan["low_reserve_threshold_bps"] == 2500, (
            "the reserve floor is stored as supplied"
        )
        assert plan["status"] == "ACTIVE", "a freshly registered plan is ACTIVE"
        assert plan["freeze_reason"] is None, "a freshly registered plan has no freeze_reason"
        assert plan["shares_committed_cumulative"] == 0, "accumulators start at zero"
        assert plan["shares_returned_cumulative"] == 0, "accumulators start at zero"
        assert plan["fiscal_year_gross_granted_shares"] == 0, "accumulators start at zero"
        assert plan["fiscal_year_returned_shares"] == 0, "accumulators start at zero"
        assert plan["evergreen_topup_last_shares"] == 0, "accumulators start at zero"
        assert plan["gross_burn_rate_bps"] == 0, "both reported rates start at 0"
        assert plan["net_burn_rate_bps"] == 0, "both reported rates start at 0"
        assert plan["available_reserve_shares"] == 1000000, (
            "available reserve is 1000000 - 0 + 0 at registration"
        )
        assert plan["reserve_posture"] == "OPEN", (
            "1000000 * 10000 >= 2500 * 1000000, so the posture is OPEN"
        )
        assert_reserve_posture(plan)
        assert_reserve_conservation(plan)
        assert plan["version"] == 1, "a freshly registered plan sits at version 1"
        assert plan["id"], "the plan carries a server-minted id"
        assert plan["created_at"], "the plan carries created_at"
        assert plan["updated_at"], "the plan carries updated_at"

    def test_plan_read_returns_the_stored_row_and_the_declared_defaults(self):
        """PRD §3.1: "Seven further inputs are optional and each has a defined default: `current_fiscal_year_label` labels the fiscal year the accumulators belong to and defaults to `FY2026`; `evergreen_pct_bps` expresses the evergreen provision in basis points of common shares outstanding and defaults to 0, with an accepted range of 0 through 10000 inclusive; `evergreen_cap_shares` is a hard ceiling in shares on any single evergreen top-up, defaults to 0, and may not be negative; `burn_rate_limit_bps` is the maximum permitted fiscal-year gross burn rate in basis points, defaults to 10000 (which is the value that disables the gate entirely, since no issuer can grant more than its whole share count), and must lie between 1 and 10000 inclusive; `fungible_ratio_full_value_bps` is the fungible share ratio charged against the reserve for full-value awards, defaults to 10000 — one share charged per share — and may never be set below 10000; `low_reserve_threshold_bps` is the reserve floor expressed in basis points of the authorised pool, defaults to 0, and ranges from 0 through 10000 inclusive; and `next_earnings_release_at` records the ISO 8601 UTC instant of the next scheduled earnings release, defaulting to null, and is read later by the cooling-off calculation of §3.9."

        PRD §3.1: "Plans may be listed with optional `status` and `reserve_posture` filters, and read individually with their live reserve and burn-rate fields; the single-plan read is what a client uses to obtain the `version` it will later quote in `expected_plan_version`."

        Design: Corner/entities/equity_plan_retrieval_matches_stored_row
        """
        set_clock("2026-01-05T09:00:00Z")
        created = create_plan(
            name="Corner Plan Bravo",
            total_authorized_shares=400000,
            common_shares_outstanding=2000000,
            fiscal_year_start_date="2026-01-01",
        )

        response = api_client.get_equity_plan(created["id"], AUDITOR)
        plan = validate_success(response)

        assert plan["id"] == created["id"], "the read resolves the addressed plan"
        assert plan["name"] == "Corner Plan Bravo", "the read serialises the stored name"
        assert plan["total_authorized_shares"] == 400000, (
            "the read serialises the stored authorised pool"
        )
        assert plan["available_reserve_shares"] == 400000, (
            "the live reserve is 400000 - 0 + 0"
        )
        assert plan["current_fiscal_year_label"] == "FY2026", (
            "current_fiscal_year_label defaults to FY2026"
        )
        assert plan["evergreen_pct_bps"] == 0, "evergreen_pct_bps defaults to 0"
        assert plan["evergreen_cap_shares"] == 0, "evergreen_cap_shares defaults to 0"
        assert plan["burn_rate_limit_bps"] == 10000, "burn_rate_limit_bps defaults to 10000"
        assert plan["fungible_ratio_full_value_bps"] == 10000, (
            "fungible_ratio_full_value_bps defaults to 10000"
        )
        assert plan["low_reserve_threshold_bps"] == 0, (
            "low_reserve_threshold_bps defaults to 0"
        )
        assert plan["next_earnings_release_at"] is None, (
            "next_earnings_release_at defaults to null"
        )
        assert plan["reserve_posture"] == "OPEN", (
            "with a 0 basis point floor the posture is OPEN"
        )
        assert plan["version"] == 1, "an unmutated plan is still at version 1"


class TestListingAndLookup:
    def test_participant_listing_reports_filtered_total_and_has_more(self):
        """PRD §2.3: "List responses carry `limit`, `offset`, `total_count`, and `has_more` inside `meta`. `total_count` is the number of rows matching the filters before the page window is applied, and `has_more` is true when rows remain beyond the current window."

        Design: Corner/entities/participants_listing_paginates_with_total_count
        """
        set_clock("2026-01-05T09:00:00Z")
        create_participant(
            full_name="Pia One", employee_number="E-C-01", home_country_code="US",
            home_state_code="CA", hire_date="2020-01-06", birth_date="1988-05-02",
        )
        create_participant(
            full_name="Pia Two", employee_number="E-C-02", home_country_code="US",
            home_state_code="NY", hire_date="2021-01-06", birth_date="1990-06-03",
        )
        validate_success(
            api_client.create_participant(
                {
                    "full_name": "Pia Three",
                    "employee_number": "E-C-03",
                    "home_country_code": "IE",
                    "hire_date": "2022-01-06",
                    "birth_date": "1992-07-04",
                },
                ADMIN,
            ),
            201,
        )

        first_response = api_client.list_participants(
            COMPLIANCE, params={"limit": 2, "offset": 0}
        )
        first_rows, first_meta = validate_paginated(first_response)
        assert first_response.json()["response_type"] == "array", (
            "a list of resources is returned with response_type array"
        )
        assert len(first_rows) == 2, "the first page holds the requested two rows"
        assert first_meta["total_count"] == 3, (
            "total_count counts the three matching rows, not the page"
        )
        assert first_meta["has_more"] is True, "one row remains beyond the first window"
        assert first_meta["limit"] == 2, "the requested limit is echoed"
        assert first_meta["offset"] == 0, "the requested offset is echoed"

        second_rows, second_meta = validate_paginated(
            api_client.list_participants(COMPLIANCE, params={"limit": 2, "offset": 2})
        )
        assert len(second_rows) == 1, "the second page holds the remaining row"
        assert second_meta["total_count"] == 3, (
            "total_count is unaffected by the page window"
        )
        assert second_meta["has_more"] is False, "no rows remain beyond the second window"
        assert second_meta["offset"] == 2, "the requested offset is echoed"

        numbers = sorted(
            row["employee_number"] for row in list(first_rows) + list(second_rows)
        )
        assert numbers == ["E-C-01", "E-C-02", "E-C-03"], (
            f"the two pages together hold every row exactly once, got {numbers}"
        )

    def test_unknown_grant_id_returns_the_entity_specific_not_found_code(self):
        """PRD §2.7: "Path and body existence failures resolve to an entity-specific identifier rather than a single generic code: `ERR_PLAN_NOT_FOUND`, `ERR_AUTHORITY_NOT_FOUND`, `ERR_PARTICIPANT_NOT_FOUND`, `ERR_ASSIGNMENT_NOT_FOUND`, `ERR_GRANT_NOT_FOUND`, `ERR_TRANCHE_NOT_FOUND`, `ERR_CYCLE_NOT_FOUND`, `ERR_VESTING_EVENT_NOT_FOUND`, `ERR_TAX_ALLOCATION_NOT_FOUND`, `ERR_WINDOW_NOT_FOUND`, `ERR_PRECLEARANCE_NOT_FOUND`, `ERR_TRADING_PLAN_NOT_FOUND`, and `ERR_REPORT_NOT_FOUND`. All of them carry HTTP 404."

        Design: Corner/entities/grant_not_found_returns_404
        """
        set_clock("2026-01-05T09:00:00Z")

        response = api_client.get_grant(UNKNOWN_UUID, ADMIN)

        assert response.status_code == 404, "a not-found failure carries HTTP 404"
        validate_error(response, ApiErrorId.ERR_GRANT_NOT_FOUND)
        body = response.json()
        assert body["response_type"] == "error", "a failure is enveloped as an error"
        assert isinstance(body["data"]["message"], str) and body["data"]["message"], (
            "the error carries a non-empty message"
        )

    def test_grant_without_target_shares_is_refused_and_stores_nothing(self):
        """PRD §2.6: "Request shape — every required field present, of the declared JSON type, inside its declared numeric or length range, and a member of its enumeration when the field is an enum — yielding `ERR_INVALID_REQUEST` (HTTP 400). A missing required field, a wrong JSON type, a zero or negative share count where a positive integer is declared, a string outside its length bounds, an unknown enum member, a malformed ISO-8601 date or instant, and a start-after-end date pair inside one payload all land here. Unknown extra fields are ignored rather than rejected."

        Design: Corner/entities/grant_missing_required_target_shares_rejected
        """
        set_clock("2026-01-05T09:00:00Z")
        plan = create_plan(
            name="Corner Plan Charlie", total_authorized_shares=1000000,
            common_shares_outstanding=1000000, fiscal_year_start_date="2026-01-01",
        )
        participant = create_participant(
            full_name="Rob Required", employee_number="E-C-10",
            home_country_code="US", home_state_code="CA",
            hire_date="2020-01-06", birth_date="1987-02-02",
        )

        response = api_client.create_grant(
            {
                "plan_id": plan["id"],
                "participant_id": participant["id"],
                "award_type": "RSU",
            },
            ADMIN,
        )

        assert response.status_code == 400, "a request-shape failure carries HTTP 400"
        validate_error(response, ApiErrorId.ERR_INVALID_REQUEST)

        rows, meta = validate_paginated(
            api_client.list_grants(ADMIN, params={"plan_id": plan["id"]})
        )
        assert meta["total_count"] == 0, "the refused draft was never stored"
        assert rows == [], "the refused draft was never stored"

    def test_grant_with_unknown_award_type_is_refused_and_stores_nothing(self):
        """PRD §3.4: "A `PlanAdministrator` drafts one against a `plan_id` and for a `participant_id`, declaring the `award_type` — `RSU`, `PSU`, `ISO`, or `NSO` — and the `target_shares` at target performance, which must be at least 1."

        PRD §2.6: "Request shape — every required field present, of the declared JSON type, inside its declared numeric or length range, and a member of its enumeration when the field is an enum — yielding `ERR_INVALID_REQUEST` (HTTP 400). A missing required field, a wrong JSON type, a zero or negative share count where a positive integer is declared, a string outside its length bounds, an unknown enum member, a malformed ISO-8601 date or instant, and a start-after-end date pair inside one payload all land here. Unknown extra fields are ignored rather than rejected."

        Design: Corner/entities/grant_invalid_award_type_enum_rejected
        """
        set_clock("2026-01-05T09:00:00Z")
        plan = create_plan(
            name="Corner Plan Echo", total_authorized_shares=1000000,
            common_shares_outstanding=1000000, fiscal_year_start_date="2026-01-01",
        )
        participant = create_participant(
            full_name="Enid Enum", employee_number="E-C-40",
            home_country_code="US", home_state_code="CA",
            hire_date="2020-01-06", birth_date="1986-03-03",
        )

        response = api_client.create_grant(
            {
                "plan_id": plan["id"],
                "participant_id": participant["id"],
                "award_type": "WARRANT",
                "target_shares": 100,
            },
            ADMIN,
        )

        assert response.status_code == 400, "an unknown enum member carries HTTP 400"
        validate_error(response, ApiErrorId.ERR_INVALID_REQUEST)

        rows, meta = validate_paginated(api_client.list_grants(ADMIN))
        assert meta["total_count"] == 0, "no grant row exists after the refusal"
        assert rows == [], "no grant row exists after the refusal"


class TestDefaultsAndServerOwnedFields:
    def test_participant_defaults_distinguish_a_default_from_an_absent_optional(self):
        """PRD §3.3: "Two inputs are optional: `home_state_code` names the home state or province and is null outside the United States, and `insider_status` classifies the recipient as `NON_INSIDER`, `DESIGNATED_INSIDER`, or `SECTION_16_OFFICER`, defaulting to `NON_INSIDER`. A new participant is `ACTIVE` at `version` 1 with `termination_date`, `termination_reason`, and `ptep_expiry_date` all null."

        Design: Corner/entities/participant_insider_status_defaults_to_non_insider
        """
        set_clock("2026-01-05T09:00:00Z")

        response = api_client.create_participant(
            {
                "full_name": "Dee Fault",
                "employee_number": "E-C-20",
                "home_country_code": "IE",
                "hire_date": "2019-04-01",
                "birth_date": "1984-08-09",
            },
            ADMIN,
        )
        participant = validate_success(response, 201)

        assert_participant(participant)
        assert participant["insider_status"] == "NON_INSIDER", (
            "insider_status defaults to NON_INSIDER when omitted"
        )
        assert participant["home_state_code"] is None, (
            "an omitted optional home_state_code stays null outside the United States"
        )
        assert participant["employment_status"] == "ACTIVE", "a new participant is ACTIVE"
        assert participant["termination_date"] is None, "termination_date starts null"
        assert participant["termination_reason"] is None, "termination_reason starts null"
        assert participant["ptep_expiry_date"] is None, "ptep_expiry_date starts null"
        assert participant["version"] == 1, "a new participant sits at version 1"

    def test_plan_ignores_client_supplied_values_for_the_derived_ledger_fields(self):
        """PRD §3.1: "`available_reserve_shares` equals the `total_authorized_shares` minus `shares_committed_cumulative` plus `shares_returned_cumulative`."

        PRD §3.1: "From the same three integers the system derives `reserve_posture`, which is `OPEN` when the available reserve multiplied by 10000 is greater than or equal to `low_reserve_threshold_bps` multiplied by `total_authorized_shares`, and `RESTRICTED` otherwise."

        PRD §3.1: "Both reported rates, `gross_burn_rate_bps` and `net_burn_rate_bps`, likewise start at 0."

        PRD §2.6: "Request shape — every required field present, of the declared JSON type, inside its declared numeric or length range, and a member of its enumeration when the field is an enum — yielding `ERR_INVALID_REQUEST` (HTTP 400). A missing required field, a wrong JSON type, a zero or negative share count where a positive integer is declared, a string outside its length bounds, an unknown enum member, a malformed ISO-8601 date or instant, and a start-after-end date pair inside one payload all land here. Unknown extra fields are ignored rather than rejected."

        Design: Corner/entities/plan_computed_reserve_fields_input_ignored
        """
        set_clock("2026-01-05T09:00:00Z")

        plan = validate_success(
            api_client.create_equity_plan(
                {
                    "name": "Corner Plan Delta",
                    "total_authorized_shares": 750000,
                    "common_shares_outstanding": 1000000,
                    "fiscal_year_start_date": "2026-01-01",
                    "low_reserve_threshold_bps": 9000,
                    "available_reserve_shares": 1,
                    "shares_committed_cumulative": 999999,
                    "reserve_posture": "RESTRICTED",
                    "gross_burn_rate_bps": 4321,
                },
                ADMIN,
            ),
            201,
        )

        assert plan["available_reserve_shares"] == 750000, (
            "the derived reserve is 750000 - 0 + 0, not the posted 1"
        )
        assert plan["shares_committed_cumulative"] == 0, (
            "the accumulator starts at zero, not at the posted 999999"
        )
        assert plan["gross_burn_rate_bps"] == 0, (
            "the reported gross rate starts at 0, not at the posted 4321"
        )
        assert plan["reserve_posture"] == "OPEN", (
            "750000 * 10000 >= 9000 * 750000, so the derived posture is OPEN"
        )
        assert_reserve_posture(plan)

        reread = validate_success(api_client.get_equity_plan(plan["id"], ADMIN))
        assert reread["available_reserve_shares"] == 750000, (
            "the stored row carries the derived reserve"
        )
        assert reread["shares_committed_cumulative"] == 0, (
            "the stored row carries the zeroed accumulator"
        )
        assert reread["gross_burn_rate_bps"] == 0, "the stored row carries a 0 gross rate"
        assert reread["reserve_posture"] == "OPEN", "the stored row carries the OPEN posture"

    def test_participant_id_version_and_status_are_server_minted(self):
        """PRD §2.4: "Every stored row is addressed by an `id` that is a server-minted UUID carrying no type prefix; clients never supply it."

        PRD §3.3: "A new participant is `ACTIVE` at `version` 1 with `termination_date`, `termination_reason`, and `ptep_expiry_date` all null."

        PRD §3.3: "Against a reference date — the logical clock date while the participant is `ACTIVE`, or the frozen `termination_date` once they are `TERMINATED` — the system derives `age_years` as the number of whole completed years from `birth_date` to that reference date, and `service_years` as the number of whole completed years from `hire_date` to it."

        PRD §3.3: ""Whole completed years" means the count of anniversaries falling on or before the reference date, and an anniversary landing exactly on the reference date counts."

        Design: Corner/entities/participant_system_fields_generated_input_ignored
        """
        set_clock("2026-01-05T09:00:00Z")

        participant = validate_success(
            api_client.create_participant(
                {
                    "full_name": "Sy Stem",
                    "employee_number": "E-C-30",
                    "home_country_code": "US",
                    "home_state_code": "WA",
                    "hire_date": "2018-09-03",
                    "birth_date": "1980-01-15",
                    "id": UNKNOWN_UUID,
                    "version": 77,
                    "employment_status": "TERMINATED",
                    "termination_date": "2020-01-01",
                    "age_years": 9,
                },
                ADMIN,
            ),
            201,
        )

        assert participant["id"] != UNKNOWN_UUID, (
            "the row is addressed by a server-minted id, not the posted one"
        )
        assert participant["version"] == 1, "version starts at 1, not at the posted 77"
        assert participant["employment_status"] == "ACTIVE", (
            "a new participant is ACTIVE, not the posted TERMINATED"
        )
        assert participant["termination_date"] is None, (
            "termination_date starts null, not at the posted date"
        )
        assert participant["age_years"] == 45, (
            "birth 1980-01-15 against the clock date 2026-01-05 is 45 whole completed years"
        )

        response = api_client.get_participant(UNKNOWN_UUID, ADMIN)
        assert response.status_code == 404, "the posted id addresses no row"
        validate_error(response, ApiErrorId.ERR_PARTICIPANT_NOT_FOUND)


class TestConstraintsAndParentResolution:
    def test_trading_window_with_close_at_before_open_at_is_a_request_shape_failure(self):
        """PRD §3.9: "A window names the `plan_id` whose calendar it belongs to, a `quarter_label` identifying the fiscal quarter it follows — such as `Q3-FY2026`, and unique among the windows of that plan — an `open_at` instant at which it opens and a `close_at` instant strictly after it at which it closes, and an optional `aggregate_share_cap` limiting the cumulative precleared shares compliance may approve inside it, which must be at least 1 when supplied and means "uncapped" when omitted."

        PRD §2.6: "Request shape — every required field present, of the declared JSON type, inside its declared numeric or length range, and a member of its enumeration when the field is an enum — yielding `ERR_INVALID_REQUEST` (HTTP 400). A missing required field, a wrong JSON type, a zero or negative share count where a positive integer is declared, a string outside its length bounds, an unknown enum member, a malformed ISO-8601 date or instant, and a start-after-end date pair inside one payload all land here. Unknown extra fields are ignored rather than rejected."

        Design: Corner/entities/trading_window_inverted_close_at_rejected
        """
        set_clock("2026-01-05T09:00:00Z")
        plan = create_plan(
            name="Corner Plan Foxtrot", total_authorized_shares=1000000,
            common_shares_outstanding=1000000, fiscal_year_start_date="2026-01-01",
        )

        response = api_client.create_trading_window(
            {
                "plan_id": plan["id"],
                "quarter_label": "FY2026-Q1",
                "open_at": "2026-03-31T00:00:00Z",
                "close_at": "2026-01-05T00:00:00Z",
            },
            COMPLIANCE,
        )

        assert response.status_code == 400, (
            "an inverted instant pair inside one payload is a request-shape failure"
        )
        validate_error(response, ApiErrorId.ERR_INVALID_REQUEST)

        rows, meta = validate_paginated(
            api_client.list_plan_trading_windows(plan["id"], COMPLIANCE)
        )
        assert meta["total_count"] == 0, "the refused window was never scheduled"
        assert rows == [], "the refused window was never scheduled"

    def test_mobility_assignment_row_carries_no_version_and_no_updated_at(self):
        """PRD §2.4: "Two entities are immutable by construction and therefore carry only `id` and `created_at`: a `MobilityAssignment`, once recorded, is never updated, and a `TaxAllocation` row is created by an allocation run and deleted by a reversal but never edited in place. Neither of them has an `updated_at` field and neither of them has a `version` field; there is no update endpoint for either."

        PRD §3.2: "Each carries the `participant_id` it belongs to, a `jurisdiction_code` between 2 and 8 characters — keys such as `US-CA`, `US-NY`, `GB`, or `IE` — a `tax_rate_bps` giving that jurisdiction's combined supplemental withholding rate in basis points between 0 and 10000 inclusive, a `start_date` that is the first day of the period, a `workdays` count of days physically worked in that jurisdiction during the period which may be zero but never negative, and an optional `end_date` which is the last day of the period and may not precede `start_date`."

        Design: Corner/entities/mobility_assignment_is_immutable_with_no_version_field
        """
        set_clock("2026-01-05T09:00:00Z")
        participant = create_participant(
            full_name="Immo Table", employee_number="E-C-50",
            home_country_code="US", home_state_code="CA",
            hire_date="2019-01-07", birth_date="1983-11-11",
        )
        created = validate_success(
            api_client.create_mobility_assignment(
                {
                    "participant_id": participant["id"],
                    "jurisdiction_code": "US-CA",
                    "tax_rate_bps": 4000,
                    "start_date": "2026-01-06",
                    "end_date": "2026-06-30",
                    "workdays": 250,
                },
                ADMIN,
            ),
            201,
        )
        assert_immutable_row_fields(created, "MobilityAssignment")

        assignment = validate_success(
            api_client.get_mobility_assignment(created["id"], AUDITOR)
        )

        assert assignment["id"] == created["id"], "the read resolves the recorded period"
        assert assignment["participant_id"] == participant["id"], (
            "the period names the participant it belongs to"
        )
        assert assignment["jurisdiction_code"] == "US-CA", "the jurisdiction key is stored"
        assert assignment["workdays"] == 250, "the workday count is stored"
        assert assignment["tax_rate_bps"] == 4000, "the withholding rate is stored"
        assert assignment["start_date"] == "2026-01-06", "the first day of the period is stored"
        assert assignment["end_date"] == "2026-06-30", "the last day of the period is stored"
        assert "version" not in assignment, (
            "an immutable row carries no version field"
        )
        assert "updated_at" not in assignment, (
            "an immutable row carries no updated_at field"
        )
        assert_mobility_assignment(assignment)

    def test_tranche_under_unknown_grant_resolves_the_path_before_the_body(self):
        """PRD §2.7: "Paths are resolved outermost segment first. A reserve adjustment addressed at a plan resolves the plan before anything else; a request for a settlement's tax allocations resolves the settlement before listing its rows; a request appending a tranche to a grant resolves the grant before reading the body."

        PRD §2.7: "Path and body existence failures resolve to an entity-specific identifier rather than a single generic code: `ERR_PLAN_NOT_FOUND`, `ERR_AUTHORITY_NOT_FOUND`, `ERR_PARTICIPANT_NOT_FOUND`, `ERR_ASSIGNMENT_NOT_FOUND`, `ERR_GRANT_NOT_FOUND`, `ERR_TRANCHE_NOT_FOUND`, `ERR_CYCLE_NOT_FOUND`, `ERR_VESTING_EVENT_NOT_FOUND`, `ERR_TAX_ALLOCATION_NOT_FOUND`, `ERR_WINDOW_NOT_FOUND`, `ERR_PRECLEARANCE_NOT_FOUND`, `ERR_TRADING_PLAN_NOT_FOUND`, and `ERR_REPORT_NOT_FOUND`. All of them carry HTTP 404."

        Design: Corner/entities/vesting_tranche_requires_existing_grant_parent_not_found
        """
        set_clock("2026-01-05T09:00:00Z")

        response = api_client.create_vesting_tranche(
            UNKNOWN_UUID,
            {
                "tranche_index": 1,
                "vest_type": "TIME",
                "scheduled_vest_date": "2027-01-05",
                "target_shares": 100,
            },
            ADMIN,
        )

        assert response.status_code == 404, "the unknown path parent carries HTTP 404"
        validate_error(response, ApiErrorId.ERR_GRANT_NOT_FOUND)

        rows, meta = validate_paginated(api_client.list_vesting_tranches(ADMIN))
        assert meta["total_count"] == 0, "the refused tranche was never stored"
        assert rows == [], "the refused tranche was never stored"

    def test_tranche_body_foreign_key_to_the_performance_cycle_is_resolved(self):
        """PRD §2.6: "Existence of every foreign key supplied in the request body, yielding the same family of not-found errors. Body-level references are checked in the order the endpoint declares them: creating a grant checks `plan_id` and then `participant_id`; appending a tranche checks `performance_cycle_id`; creating a preclearance request checks `participant_id` and then `window_id`. Creating a delegation checks `plan_id`; creating a mobility assignment checks `participant_id`; creating a performance cycle checks `plan_id`; creating a trading window checks `plan_id`; adopting a trading plan checks `participant_id`."

        PRD §3.4: "A `PERFORMANCE` tranche must supply `performance_cycle_id`, and its `shares` sit at 0 until the cycle is certified — which is why an uncertified performance tranche commits nothing against the reserve."

        PRD §3.4: "Every new tranche is `UNVESTED` with `acceleration_reason` null and `vested_at` null."

        PRD §3.4: "Tranches are listable with optional `grant_id`, `performance_cycle_id`, and `status` filters, and readable individually."

        Design: Corner/entities/tranche_performance_cycle_fk_cross_reference_validated
        """
        set_clock("2026-01-05T09:00:00Z")
        plan = create_plan(
            name="Corner Plan Golf", total_authorized_shares=1000000,
            common_shares_outstanding=1000000, fiscal_year_start_date="2026-01-01",
        )
        participant = create_participant(
            full_name="Fran Key", employee_number="E-C-60",
            home_country_code="US", home_state_code="CA",
            hire_date="2020-01-06", birth_date="1985-05-05",
        )
        cycle = create_cycle(
            plan["id"], metric_code="TSR-2026", target_value=200,
            certification_due_date="2027-02-15",
        )
        grant = validate_success(
            api_client.create_grant(
                {
                    "plan_id": plan["id"],
                    "participant_id": participant["id"],
                    "award_type": "PSU",
                    "target_shares": 1000,
                },
                ADMIN,
            ),
            201,
        )

        unknown_cycle_response = api_client.create_vesting_tranche(
            grant["id"],
            {
                "tranche_index": 1,
                "vest_type": "PERFORMANCE",
                "scheduled_vest_date": "2027-03-01",
                "target_shares": 1000,
                "performance_cycle_id": UNKNOWN_UUID,
            },
            ADMIN,
        )
        assert unknown_cycle_response.status_code == 404, (
            "an unknown body foreign key carries HTTP 404"
        )
        validate_error(unknown_cycle_response, ApiErrorId.ERR_CYCLE_NOT_FOUND)

        tranche = validate_success(
            api_client.create_vesting_tranche(
                grant["id"],
                {
                    "tranche_index": 1,
                    "vest_type": "PERFORMANCE",
                    "scheduled_vest_date": "2027-03-01",
                    "target_shares": 1000,
                    "performance_cycle_id": cycle["id"],
                },
                ADMIN,
            ),
            201,
        )
        assert_vesting_tranche(tranche)
        assert tranche["performance_cycle_id"] == cycle["id"], (
            "the resolved cycle association is stored"
        )
        assert tranche["status"] == "UNVESTED", "every new tranche is UNVESTED"
        assert tranche["acceleration_reason"] is None, (
            "every new tranche has acceleration_reason null"
        )
        assert tranche["vested_at"] is None, "every new tranche has vested_at null"
        assert tranche["shares"] == 0, (
            "a performance tranche carries 0 shares until its cycle is certified"
        )

        rows, meta = validate_paginated(
            api_client.list_vesting_tranches(
                ADMIN, params={"performance_cycle_id": cycle["id"]}
            )
        )
        assert meta["total_count"] == 1, (
            "exactly one tranche is bound to the certified-later cycle"
        )
        assert [row["id"] for row in rows] == [tranche["id"]], (
            "the cycle filter returns the stored tranche"
        )
