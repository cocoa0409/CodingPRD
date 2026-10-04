"""Household enrollment: creation defaults, secondary member, schema and
existence errors, and the pinned logical-clock startup reading."""
from test_helpers import (
    api_client, validate_success, validate_error, validate_paginated,
    NON_EXISTENT_UUID, ApiErrorId, TEST_USERS,
    create_household_payload, set_clock,
    assert_household, assert_member, assert_membership_term,
)

MSA = TEST_USERS["member_services_headers"]


class TestHouseholdEnrollment:
    def test_minimal_creation_defaults_and_computed_fields(self, api):
        """PRD §3.1: "it may also carry `auto_renew_enabled` (defaulting to
        `false` when omitted)". PRD §3.1: "Annual base dues are 1,600 cents
        (sixteen dollars) per year." PRD §3.1: "Multi-year terms earn a
        discount of 0% for one year, 10% for three years, or 20% for five
        years". PRD §3.2: "A household's `status` is a derived value, never
        stored as a mutable field: it is `ACTIVE` when at least one of the
        household's membership terms is itself `ACTIVE` and covers the current
        clock date".

        Design: Corner/entities/household_create_defaults_and_computed_fields
        """
        set_clock()
        payload = create_household_payload(
            state_code="TX", term_years=1, primary_full_name="Ada Adams",
            primary_date_of_birth="1970-01-15")
        resp = api.create_household(payload, MSA)
        household = validate_success(resp, expected_status=201)
        assert_household(household)
        assert household["status"] == "ACTIVE"
        assert household["version"] == 1
        assert household["auto_renew_enabled"] is False
        assert household["secondary_member_id"] is None
        assert household["lifetime_collected_cents"] == 1600
        assert household["lifetime_refunded_cents"] == 0
        assert household["primary_member_id"]

        terms, _ = validate_paginated(
            api.list_household_terms(household["id"], MSA))
        assert len(terms) == 1
        assert_membership_term(terms[0])
        assert terms[0]["paid_cents"] == 1600
        assert terms[0]["is_renewal"] is False
        assert terms[0]["status"] == "ACTIVE"

        members, _ = validate_paginated(
            api.list_household_members(household["id"], MSA))
        assert len(members) == 1
        assert_member(members[0])
        assert members[0]["role_in_household"] == "PRIMARY"
        # Born 1970-01-15, clock 2026-09-01: 56 whole years.
        assert members[0]["age_years"] == 56

    def test_secondary_member_added_at_zero_price(self, api):
        """PRD §3.1: "A secondary member adds 0 cents: household pricing
        covers up to two members at no additional charge." PRD §3.1: "The
        created member records carry `full_name`, `date_of_birth`, and
        `benefit_marketing_opt_out` taken from the correspondingly prefixed
        payload fields, a `role_in_household` of `PRIMARY` or `SECONDARY`
        derived from which creation slot each occupies".

        Design: Corner/entities/household_create_with_secondary_member
        """
        set_clock()
        payload = create_household_payload(
            state_code="VT", term_years=3, primary_full_name="Ben Bell",
            primary_date_of_birth="1968-03-20",
            secondary_full_name="Cora Bell",
            secondary_date_of_birth="1971-09-12",
            secondary_benefit_marketing_opt_out=True)
        resp = api.create_household(payload, MSA)
        household = validate_success(resp, expected_status=201)
        assert household["secondary_member_id"] is not None

        members, _ = validate_paginated(
            api.list_household_members(household["id"], MSA))
        assert len(members) == 2
        roles = sorted(m["role_in_household"] for m in members)
        assert roles == ["PRIMARY", "SECONDARY"]
        secondary = next(m for m in members if m["role_in_household"] == "SECONDARY")
        assert secondary["benefit_marketing_opt_out"] is True

        terms, _ = validate_paginated(
            api.list_household_terms(household["id"], MSA))
        assert len(terms) == 1
        assert terms[0]["paid_cents"] == 4320

    def test_missing_required_term_years_is_schema_error(self, api):
        """PRD §2.8 rung 5: "Required fields are present, enum values are
        valid, dates parse, ranges are not inverted (`effective_to` strictly
        after `effective_from`, `end_time` strictly after `start_time`,
        `max_cpm_cents` at least `min_cpm_cents`, campaign `end_date` on or
        after `start_date`), conditional fields hold (`state_code` present
        exactly when a campaign's `level` is `STATE`,
        `secondary_date_of_birth` present exactly when `secondary_full_name`
        is supplied), and no unknown `audience_spec` keys appear; otherwise
        `ERR_INVALID_REQUEST` (HTTP 400)." PRD §3.1: "The payload carries the
        household's `state_code`, the desired `term_years`, and the primary
        applicant's `primary_full_name` and `primary_date_of_birth`".

        Design: Corner/entities/household_create_missing_required_term_years
        """
        set_clock()
        payload = {
            "state_code": "TX",
            "primary_full_name": "Dee Daws",
            "primary_date_of_birth": "1970-06-06",
        }
        resp = api.create_household(payload, MSA)
        validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST)

    def test_unsupported_term_years_returns_domain_error(self, api):
        """PRD §3.1: "The term length itself must be exactly 1, 3, or 5 years
        — any other `term_years` value is rejected with
        `ERR_INVALID_TERM_YEARS` (HTTP 422)."

        Design: Corner/entities/invalid_term_years_returns_domain_error
        """
        set_clock()
        payload = create_household_payload(
            state_code="TX", term_years=2, primary_full_name="Ed Edds",
            primary_date_of_birth="1970-06-06")
        resp = api.create_household(payload, MSA)
        validate_error(resp, ApiErrorId.ERR_INVALID_TERM_YEARS)

    def test_get_unknown_household_returns_not_found(self, api):
        """PRD §2.8 rung 6: "Path identifiers exist, validated left to right,
        followed by body-supplied foreign keys (`member_id`,
        `license_agreement_id`, `sponsor_entity_id`, `from_entity_id`,
        `to_entity_id`); otherwise `ERR_NOT_FOUND` (HTTP 404)." PRD §2.2: "The `meta`
        object for error responses contains only `api_request_id` and
        `api_request_timestamp`."

        Design: Corner/entities/household_get_unknown_id_returns_not_found
        """
        set_clock()
        resp = api.get_household(NON_EXISTENT_UUID, MSA)
        error = validate_error(resp, ApiErrorId.ERR_NOT_FOUND)
        assert "message" in error
        assert resp.status_code == 404
        body = resp.json()
        assert body["response_type"] == "error"
        assert "api_request_id" in body["meta"]
        assert "api_request_timestamp" in body["meta"]

    def test_clock_default_startup_date_pinned(self, api):
        """PRD §2.4: "At server startup, before any operator intervention, the
        clock reads exactly `2026-09-01T00:00:00Z`, and the server must not
        fall back to wall-clock time under any circumstances." PRD §3.1: "The
        initial term starts `ACTIVE` with `is_renewal` false, its
        `start_date` set to the clock date at purchase, its `end_date` set to
        the start date advanced by `term_years` years, and its `purchased_at`
        stamped from the logical clock."

        Design: Corner/endpoints/clock_default_startup_date
        """
        # Deliberately NO set_clock call: the server just started.
        payload = create_household_payload(
            state_code="SD", term_years=1, primary_full_name="Zoe Zinn",
            primary_date_of_birth="1970-10-10")
        resp = api.create_household(payload, MSA)
        household = validate_success(resp, expected_status=201)
        terms, _ = validate_paginated(
            api.list_household_terms(household["id"], MSA))
        assert len(terms) == 1
        assert terms[0]["start_date"] == "2026-09-01"
        assert terms[0]["purchased_at"] == "2026-09-01T00:00:00Z"
