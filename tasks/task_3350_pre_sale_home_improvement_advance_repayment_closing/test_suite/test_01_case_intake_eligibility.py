"""Case intake, reference data, and eligibility underwriting."""
from test_helpers import (
    NON_EXISTENT_UUID,
    TEST_USERS,
    api_client,
    assert_agent,
    assert_concierge_case,
    assert_vendor,
    create_case_payload,
    create_vendor_payload,
    make_agent,
    make_listing_agent_headers,
    reset_clock,
    set_clock,
    create_case,
    get_case,
    approve_eligibility,
    validate_error,
    validate_paginated,
    validate_success,
)
from test_helpers import ApiErrorId as ERR


class TestReferenceData:
    def test_agent_create_and_get_round_trip(self, api):
        """PRD §3.1: "A `PlatformAdmin` registers each listing agent with a
        `display_name`, a state real-estate `license_number`, and a `brokerage`."

        Design: Corner/endpoints/agent_create_and_get_round_trip
        """
        reset_clock()
        resp = api_client.create_agent(
            {"display_name": "Agent A", "license_number": "LIC-001",
             "brokerage": "Brokerage X"},
            TEST_USERS["platform_admin_headers"],
        )
        created = validate_success(resp, expected_status=201)
        assert_agent(created)
        fetched = validate_success(api_client.get_agent(created["id"], TEST_USERS["any_headers"]))
        assert fetched["display_name"] == "Agent A"
        assert fetched["license_number"] == "LIC-001"

    def test_vendor_create_returns_computed_quality_fields_at_default(self, api):
        """PRD §3.1: "A newly created vendor starts with a spotless record: its
        `quality_score_bp` is initialized to 10000 and its `on_time_streak` to 0."

        Design: Corner/entities/vendor_create_returns_computed_quality_fields_at_default
        """
        reset_clock()
        resp = api_client.create_vendor(
            create_vendor_payload(legal_name="Vendor V", trade="PAINT"),
            TEST_USERS["platform_admin_headers"],
        )
        vendor = validate_success(resp, expected_status=201)
        assert_vendor(vendor)
        assert vendor["quality_score_bp"] == 10000
        assert vendor["on_time_streak"] == 0

    def test_vendor_create_with_invalid_trade_enum_returns_invalid_request(self, api):
        """PRD §2.8: "a structurally malformed request body, a negative or zero
        amount where a positive one is required, or an unrecognized enum value is
        rejected with `ERR_INVALID_REQUEST` (HTTP 400)."

        Design: Corner/entities/vendor_create_with_invalid_trade_enum_returns_invalid_request
        """
        reset_clock()
        resp = api_client.create_vendor(
            create_vendor_payload(legal_name="Vendor V", trade="ROOFING"),
            TEST_USERS["platform_admin_headers"],
        )
        validate_error(resp, ERR.ERR_INVALID_REQUEST)


class TestCaseCreation:
    def test_case_create_returns_declared_fields_and_starts_eligibility_review(self, api):
        """PRD §3.2: "A new case enters `ELIGIBILITY_REVIEW`, and the system derives
        its `upfront_payment_track` from the contribution: a
        `homeowner_contribution_cents` greater than zero places the case on the
        `CONTRIBUTION` track, while a zero contribution places it on the `NO_UPFRONT`
        track."
        PRD §3.2: "when omitted, the case begins with no approved or disbursed
        advances, so the running total is zero."

        Design: Corner/entities/concierge_case_create_returns_every_declared_field_and_starts_eligibility_review
        """
        reset_clock()
        agent = make_agent()
        resp = api_client.create_case(
            create_case_payload(), make_listing_agent_headers(agent["id"])
        )
        case = validate_success(resp, expected_status=201)
        assert_concierge_case(case)
        assert case["status"] == "ELIGIBILITY_REVIEW"
        assert case["advance_total_cents"] == 0
        assert case["posture"] == "OPEN"

    def test_case_create_omitting_optionals_uses_declared_defaults(self, api):
        """PRD §3.2: "The create payload may optionally carry
        `homeowner_contribution_cents`, an upfront homeowner co-pay that defaults
        to 0, and `listing_window_days`, the number of days from first listing to
        the no-sale penalty trigger, which defaults to 180."
        PRD §3.2: "a zero contribution places it on the `NO_UPFRONT` track."

        Design: Corner/entities/concierge_case_create_omitting_listing_window_days_defaults_to_180
        """
        reset_clock()
        agent = make_agent()
        case = create_case(agent)
        fetched = get_case(case["id"])
        assert fetched["listing_window_days"] == 180
        assert fetched["homeowner_contribution_cents"] == 0
        assert fetched["upfront_payment_track"] == "NO_UPFRONT"

    def test_case_get_with_unknown_id_returns_not_found(self, api):
        """PRD §2.4: "A failure at any point — a missing parent, a missing child,
        or a child that belongs to a different parent — is rejected with
        `ERR_NOT_FOUND` (HTTP 404)."

        Design: Corner/entities/concierge_case_get_with_unknown_id_returns_not_found
        """
        reset_clock()
        resp = api_client.get_case(NON_EXISTENT_UUID, TEST_USERS["any_headers"])
        validate_error(resp, ERR.ERR_NOT_FOUND)

    def test_cases_list_paginates_and_reports_total_count_and_has_more(self, api):
        """PRD §2.3: "For list endpoints, the `meta` object of the success envelope
        carries the pagination fields `limit`, `offset`, `total_count`, and
        `has_more`."

        Design: Corner/entities/concierge_cases_list_paginates_and_reports_total_count_and_has_more
        """
        reset_clock()
        agent = make_agent()
        headers = make_listing_agent_headers(agent["id"])
        for address in ("123 Main St", "456 Oak Ave", "789 Pine Ln"):
            api_client.create_case(create_case_payload(address_line=address), headers)
        data, meta = validate_paginated(
            api_client.list_cases(TEST_USERS["any_headers"], params={"limit": 2, "offset": 0})
        )
        assert len(data) == 2, f"expected 2 rows, got {len(data)}"
        assert meta["total_count"] == 3
        assert meta["has_more"] is True
        data2, meta2 = validate_paginated(
            api_client.list_cases(TEST_USERS["any_headers"], params={"limit": 2, "offset": 2})
        )
        assert len(data2) == 1, f"expected 1 row, got {len(data2)}"
        assert meta2["total_count"] == 3
        assert meta2["has_more"] is False


class TestEligibility:
    def test_eligibility_approve_transitions_case_to_scope_planning(self, api):
        """PRD §3.2: "On approval the case advances from `ELIGIBILITY_REVIEW` to
        `SCOPE_PLANNING` and its `advance_limit_cents` is computed: the hard cap on
        total program advances is the `expected_sale_proceeds_cents` multiplied by
        0.15, floored down to a whole cent"

        Design: Corner/state_machines/eligibility_approve_transitions_case_to_scope_planning
        """
        reset_clock()
        agent = make_agent()
        case = create_case(agent)
        resp = api_client.approve_eligibility(
            case["id"], TEST_USERS["program_underwriter_headers"]
        )
        validate_success(resp)
        fetched = get_case(case["id"])
        assert fetched["status"] == "SCOPE_PLANNING"
        assert fetched["advance_limit_cents"] == 15_000_000

    def test_eligibility_reject_transitions_case_to_cancelled(self, api):
        """PRD §3.2: "A `ProgramUnderwriter` may instead reject eligibility, which
        moves the case from `ELIGIBILITY_REVIEW` directly to `CANCELLED` with no
        further effect."

        Design: Corner/state_machines/eligibility_reject_transitions_case_to_cancelled
        """
        reset_clock()
        agent = make_agent()
        case = create_case(agent)
        resp = api_client.reject_eligibility(
            case["id"], TEST_USERS["program_underwriter_headers"]
        )
        validate_success(resp)
        assert get_case(case["id"])["status"] == "CANCELLED"

    def test_eligibility_approve_with_insufficient_equity_returns_eligibility_failed(self, api):
        """PRD §3.2: "the `expected_sale_proceeds_cents` exceeds the
        `estimated_property_value_cents` multiplied by 1.10, the program's minimum
        equity ratio"
        PRD §3.2: "If any of these fails, the approval is rejected with
        `ERR_ELIGIBILITY_FAILED` (HTTP 409)."

        Design: Corner/validations/eligibility_approve_with_insufficient_equity_returns_eligibility_failed
        """
        reset_clock()
        agent = make_agent()
        case = create_case(
            agent,
            estimated_property_value_cents=80_000_000,
            expected_sale_proceeds_cents=81_000_000,
        )
        resp = api_client.approve_eligibility(
            case["id"], TEST_USERS["program_underwriter_headers"]
        )
        validate_error(resp, ERR.ERR_ELIGIBILITY_FAILED)

    def test_advance_limit_calculation_uses_floor_and_fifteen_percent(self, api):
        """PRD §3.2: "the hard cap on total program advances is the
        `expected_sale_proceeds_cents` multiplied by 0.15, floored down to a whole
        cent"

        Design: Corner/calculations/advance_limit_calculation_uses_floor_and_fifteen_percent
        """
        reset_clock()
        agent = make_agent()
        case = create_case(agent, expected_sale_proceeds_cents=100_000_001)
        approve_eligibility(case["id"])
        fetched = get_case(case["id"])
        # floor(100000001 * 0.15) = floor(15000000.15) = 15000000
        assert fetched["advance_limit_cents"] == 15_000_000


class TestAdvanceLimitMinOfTwoConstraints:
    """Both branches of the advance-limit formula, with and without a homeowner
    contribution, on otherwise identical cases."""

    def test_advance_limit_without_contribution_uses_rate_cap(self, api):
        """PRD §3.2: "the hard cap on total program advances is the
        `expected_sale_proceeds_cents` multiplied by 0.15, floored down to a whole
        cent — and if the `homeowner_contribution_cents` is greater than zero, the
        cap is additionally clamped to no more than the
        `expected_sale_proceeds_cents` minus the `estimated_property_value_cents`,
        taking the smaller of the two figures."

        Design: Difficulty/combinatorial_formula/advance_limit_min_of_two_constraints
        """
        reset_clock()
        agent = make_agent()
        case = create_case(agent, homeowner_contribution_cents=0)
        approve_eligibility(case["id"])
        fetched = get_case(case["id"])
        # floor(100000000 * 0.15) = 15000000
        assert fetched["advance_limit_cents"] == 15_000_000

    def test_advance_limit_with_contribution_takes_smaller_of_two_figures(self, api):
        """PRD §3.2: "if the `homeowner_contribution_cents` is greater than zero,
        the cap is additionally clamped to no more than the
        `expected_sale_proceeds_cents` minus the `estimated_property_value_cents`,
        taking the smaller of the two figures."

        Design: Difficulty/combinatorial_formula/advance_limit_min_of_two_constraints
        """
        reset_clock()
        agent = make_agent()
        case = create_case(agent, homeowner_contribution_cents=1_000_000)
        approve_eligibility(case["id"])
        fetched = get_case(case["id"])
        # min(floor(100000000*0.15), 100000000-80000000) = min(15000000, 20000000)
        assert fetched["advance_limit_cents"] == 15_000_000
        assert fetched["upfront_payment_track"] == "CONTRIBUTION"


class TestAuthAndRoles:
    def test_missing_auth_headers_returns_400(self, api):
        """PRD §2.1: "A request in which either header is missing or malformed is
        rejected with `ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER` (HTTP 400)."

        Design: Corner/validations/missing_auth_headers_returns_400
        """
        reset_clock()
        resp = api_client.get_case(NON_EXISTENT_UUID, headers={})
        validate_error(resp, ERR.ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER)

    def test_homeowner_cannot_create_case(self, api):
        """PRD §2.1: "A request whose role is well-formed but not authorized for
        the target endpoint is rejected with `ERR_FORBIDDEN_FOR_ROLE` (HTTP 403)."

        Design: Corner/validations/role_not_permitted_returns_403
        """
        reset_clock()
        resp = api_client.create_case(
            create_case_payload(), TEST_USERS["homeowner_headers"]
        )
        validate_error(resp, ERR.ERR_FORBIDDEN_FOR_ROLE)

    def test_listing_agent_cannot_approve_eligibility(self, api):
        """PRD §2.1: "A request whose role is well-formed but not authorized for
        the target endpoint is rejected with `ERR_FORBIDDEN_FOR_ROLE` (HTTP 403)."
        PRD §3.2: "Eligibility is decided by a `ProgramUnderwriter`."

        Design: Corner/roles/listing_agent_cannot_approve_eligibility
        """
        reset_clock()
        agent = make_agent()
        case = create_case(agent)
        resp = api_client.approve_eligibility(
            case["id"], make_listing_agent_headers(agent["id"])
        )
        validate_error(resp, ERR.ERR_FORBIDDEN_FOR_ROLE)

    def test_program_underwriter_cannot_create_case(self, api):
        """PRD §2.1: "A request whose role is well-formed but not authorized for
        the target endpoint is rejected with `ERR_FORBIDDEN_FOR_ROLE` (HTTP 403)."
        PRD §3.2: "A `ListingAgent` opens a `ConciergeCase` by submitting the
        property's `address_line`"

        Design: Corner/roles/program_underwriter_cannot_create_case
        """
        reset_clock()
        resp = api_client.create_case(
            create_case_payload(), TEST_USERS["program_underwriter_headers"]
        )
        validate_error(resp, ERR.ERR_FORBIDDEN_FOR_ROLE)
