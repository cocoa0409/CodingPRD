"""Standing up a plan and enrolling the employee-owner census."""
from test_helpers import (
    PAGINATION_DEFAULT_LIMIT,
    PLAN_DEFAULT_ANNUAL_ADDITIONS_LIMIT_CENTS,
    PLAN_DEFAULT_ANNUAL_COMPENSATION_LIMIT_CENTS,
    PLAN_DEFAULT_DIVERSIFICATION_MIN_AGE,
    PLAN_DEFAULT_DIVERSIFICATION_MIN_YEARS,
    PLAN_DEFAULT_NORMAL_RETIREMENT_AGE,
    TEST_USERS,
    ApiErrorId,
    assert_esop_plan,
    assert_participant,
    create_participant,
    create_participant_payload,
    create_plan,
    create_plan_payload,
    is_valid_uuid,
    set_clock,
    validate_error,
    validate_paginated,
    validate_success,
)

SPONSOR = TEST_USERS["sponsor_headers"]
TRUSTEE = TEST_USERS["trustee_headers"]
ADMIN = TEST_USERS["admin_headers"]
UNKNOWN_UUID = "8a3e1c0b-2f4d-4a91-9c8b-12e7b6a0f1d2"


class TestPlanCreation:
    def test_create_plan_returns_201_with_all_counters_zeroed(self, api):
        """PRD 3.1: "A newly created plan opens in `OPEN` posture at `version` 1 with
        `repurchase_posture` `FUNDED` and `forfeiture_posture` `CLEAR`, and with every share
        and cash counter — `total_plan_shares`, `suspense_shares`, `unallocated_released_shares`,
        `unallocated_forfeiture_shares`, `reacquired_shares`, `allocated_shares_total`,
        `current_share_price_cents`, `open_valuation_count`, `draft_run_count`,
        `repurchase_reserve_cents`, `committed_repurchase_cents`,
        `cumulative_repurchase_funding_cents` and `cumulative_repurchase_settled_cents` —
        sitting at 0."
        PRD 4: "Endpoints that bring a brand-new resource into existence answer with HTTP 201
        Created; every other successful call, including every state action, every read and
        every list, answers with HTTP 200 OK."

        Design: Corner/entities/create_plan_returns_201_with_all_counters_zeroed
        """
        set_clock("2026-03-02T00:00:00Z", SPONSOR)
        payload = create_plan_payload(plan_name="Corner Plan", sponsor_name="Corner Corp")
        resp = api.create_plan(payload, SPONSOR)
        plan = validate_success(resp, 201)

        assert_esop_plan(plan)
        assert plan["plan_status"] == "OPEN", "a plan is created OPEN"
        assert plan["version"] == 1, "a newly created plan sits at version 1"
        for counter in (
            "total_plan_shares", "suspense_shares", "unallocated_released_shares",
            "unallocated_forfeiture_shares", "reacquired_shares", "allocated_shares_total",
            "current_share_price_cents", "open_valuation_count", "draft_run_count",
            "repurchase_reserve_cents", "committed_repurchase_cents",
            "cumulative_repurchase_funding_cents", "cumulative_repurchase_settled_cents",
        ):
            assert plan[counter] == 0, f"{counter} must sit at 0 on a new plan, got {plan[counter]}"
        assert plan["repurchase_posture"] == "FUNDED"
        assert plan["forfeiture_posture"] == "CLEAR"
        assert plan["frozen_reason"] is None, "frozen_reason stays null outside FROZEN"

        body = resp.json()
        assert body["response_type"] == "object"
        assert body["meta"]["api_request_id"].startswith("req_"), (
            "api_request_id is a server-generated identifier that starts with req_"
        )
        assert isinstance(body["meta"]["api_request_timestamp"], str)

    def test_plan_optional_fields_apply_declared_defaults(self, api):
        """PRD 3.1: "`sweep_mode` chooses between `STRICT_ORDER` and `BEST_FIT` for the
        repurchase queue and defaults to `STRICT_ORDER`."
        PRD 3.1: "`annual_compensation_limit_cents` is the Section 401(a)(17) compensation cap
        and defaults to 34,500,000 cents — that is, 345,000 dollars of pensionable pay;
        `annual_additions_limit_cents` is the Section 415(c) ceiling on what one account may
        receive in one plan year and defaults to 6,900,000 cents, or 69,000 dollars of
        allocated share value."
        PRD 3.1: "`normal_retirement_age` defaults to 65 and must fall between 40 and 99
        inclusive; `diversification_min_age` defaults to 55 with the same 40-to-99 range;
        `diversification_min_years` defaults to 10 and must be at least 1.
        `repurchase_reserve_floor_cents` defaults to 0, `forfeiture_sweep_threshold_shares`
        defaults to 0, and neither may be negative."

        Design: Corner/entities/plan_optional_fields_apply_declared_defaults
        """
        set_clock("2026-03-02T00:00:00Z", SPONSOR)
        payload = create_plan_payload(
            plan_name="Default Plan", sponsor_name="Corner Corp",
            vesting_schedule="CLIFF_3YR", service_measurement_method="PLAN_YEAR_END_MEASURE",
            forfeiture_policy="REDUCE_CONTRIBUTION", distribution_policy="LUMP_SUM",
        )
        plan = validate_success(api.create_plan(payload, SPONSOR), 201)

        assert plan["annual_compensation_limit_cents"] == PLAN_DEFAULT_ANNUAL_COMPENSATION_LIMIT_CENTS
        assert plan["annual_additions_limit_cents"] == PLAN_DEFAULT_ANNUAL_ADDITIONS_LIMIT_CENTS
        assert plan["sweep_mode"] == "STRICT_ORDER"
        assert plan["normal_retirement_age"] == PLAN_DEFAULT_NORMAL_RETIREMENT_AGE
        assert plan["diversification_min_age"] == PLAN_DEFAULT_DIVERSIFICATION_MIN_AGE
        assert plan["diversification_min_years"] == PLAN_DEFAULT_DIVERSIFICATION_MIN_YEARS
        assert plan["repurchase_reserve_floor_cents"] == 0
        assert plan["forfeiture_sweep_threshold_shares"] == 0

    def test_create_plan_missing_required_field_returns_invalid_request(self, api):
        """PRD 2.12: "Request shape — every required input field present, every field of the
        declared type, every enum field carrying a declared member, every integer field inside
        its declared range, every date field parsing as YYYY-MM-DD, `effective_to_date`
        strictly after `effective_from_date`, `limit` within 1 through 100 and `offset` not
        negative; otherwise `ERR_INVALID_REQUEST` (400)."
        PRD 3.1: "Four policy selections are mandatory at creation because every downstream
        calculation branches on them."

        Design: Corner/entities/create_plan_missing_required_field_returns_invalid_request
        """
        set_clock("2026-03-02T00:00:00Z", SPONSOR)
        payload = create_plan_payload(plan_name="Broken Plan", sponsor_name="Corner Corp")
        del payload["distribution_policy"]

        resp = api.create_plan(payload, SPONSOR)
        validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST)
        assert resp.json()["response_type"] == "error"

    def test_create_plan_invalid_enum_member_rejected(self, api):
        """PRD 3.1: "`vesting_schedule` is either `CLIFF_3YR` or `GRADED_6YR` and selects the
        table that converts service into a vested percentage."
        PRD 2.12: "Request shape — every required input field present, every field of the
        declared type, every enum field carrying a declared member, every integer field inside
        its declared range, every date field parsing as YYYY-MM-DD, `effective_to_date`
        strictly after `effective_from_date`, `limit` within 1 through 100 and `offset` not
        negative; otherwise `ERR_INVALID_REQUEST` (400)."

        Design: Corner/entities/create_plan_invalid_enum_member_rejected
        """
        set_clock("2026-03-02T00:00:00Z", SPONSOR)
        payload = create_plan_payload(
            plan_name="Enum Plan", sponsor_name="Corner Corp",
            vesting_schedule="CLIFF_5YR", distribution_policy="LUMP_SUM",
        )
        validate_error(api.create_plan(payload, SPONSOR), ApiErrorId.ERR_INVALID_REQUEST)

    def test_get_plan_with_unknown_id_returns_not_found(self, api):
        """PRD 2.11: "Each has its own not-found code, all of them HTTP 404:
        `ERR_PLAN_NOT_FOUND`, `ERR_PARTICIPANT_NOT_FOUND`, `ERR_VALUATION_NOT_FOUND`,
        `ERR_LOAN_NOT_FOUND`, `ERR_LOAN_PAYMENT_NOT_FOUND`, `ERR_RUN_NOT_FOUND`,
        `ERR_ALLOCATION_NOT_FOUND`, `ERR_FORFEITURE_NOT_FOUND`, `ERR_ELECTION_NOT_FOUND`,
        `ERR_INSTALLMENT_NOT_FOUND`, `ERR_EXERCISE_NOT_FOUND` and `ERR_STATEMENT_NOT_FOUND`."

        Design: Corner/entities/get_plan_with_unknown_id_returns_not_found
        """
        set_clock("2026-03-02T00:00:00Z", SPONSOR)
        validate_error(api.get_plan(UNKNOWN_UUID, TRUSTEE), ApiErrorId.ERR_PLAN_NOT_FOUND)


class TestCensusEnrolment:
    def test_participant_computed_and_system_fields_ignore_client_input(self, api):
        """PRD 3.1: "Every participant begins `ACTIVE`, with `termination_date` and
        `termination_reason` null, with `years_of_service`, `vested_percentage`,
        `allocated_shares`, `vested_shares`, `distributed_shares_cumulative`,
        `tendered_shares_cumulative` and `diversified_shares_cumulative` all at 0, and with
        `put_window_open_date`, `put_window_close_date` and `last_put_window_close_date` all
        null."
        PRD 3.1: "Consider an owner born on 1968-05-20 and hired on 2010-08-15 under the
        default age and service minimums: birth year plus 55 is 2023, hire year plus 10 is
        2020, and the later of the two, 2023, is the anchor."
        PRD 2.4: "Identifiers are UUIDs with no type prefix of any kind, they are assigned by
        the server, and a client-supplied identifier in a creation payload is ignored."

        Design: Corner/entities/participant_computed_and_system_fields_ignore_client_input
        """
        set_clock("2026-03-02T00:00:00Z", SPONSOR)
        plan = create_plan(plan_name="Census Plan", sponsor_name="Corner Corp")
        payload = create_participant_payload(
            plan["id"], employee_number="E-900", date_of_birth="1968-05-20",
            hire_date="2010-08-15", eligible_compensation_cents=30_000_000,
        )
        participant = validate_success(api.create_participant(payload, SPONSOR), 201)

        assert_participant(participant)
        assert participant["status"] == "ACTIVE"
        for counter in (
            "allocated_shares", "vested_shares", "vested_percentage", "years_of_service",
            "distributed_shares_cumulative", "tendered_shares_cumulative",
            "diversified_shares_cumulative",
        ):
            assert participant[counter] == 0, f"{counter} starts at 0"
        assert participant["termination_date"] is None
        assert participant["termination_reason"] is None
        assert participant["put_window_open_date"] is None
        assert participant["put_window_close_date"] is None
        assert participant["last_put_window_close_date"] is None
        assert participant["diversification_first_eligible_plan_year"] == 2023, (
            "the anchor is the later of birth year plus 55 and hire year plus 10"
        )
        assert participant["diversification_eligible"] is True, (
            "plan year 2026 falls inside the six-year span 2023 through 2028"
        )
        assert is_valid_uuid(participant["id"]) and "_" not in participant["id"], (
            "identifiers are UUIDs with no type prefix of any kind"
        )
        assert participant["version"] == 1

    def test_participant_annual_hours_default_applied(self, api):
        """PRD 3.1: "Two payroll facts are optional at enrolment:
        `eligible_compensation_cents`, the participant's plan-year eligible compensation,
        which defaults to 0 and may not be negative, and `annual_hours`, the hours credited
        for the plan year, which defaults to 2000 and may not be negative."

        Design: Corner/entities/participant_annual_hours_default_applied
        """
        set_clock("2026-03-02T00:00:00Z", SPONSOR)
        plan = create_plan(plan_name="Hours Plan", sponsor_name="Corner Corp")
        payload = {
            "plan_id": plan["id"], "employee_number": "E-901",
            "date_of_birth": "1990-01-01", "hire_date": "2020-01-01",
        }
        participant = validate_success(api.create_participant(payload, SPONSOR), 201)

        assert participant["annual_hours"] == 2000
        assert participant["eligible_compensation_cents"] == 0

    def test_create_participant_with_unknown_plan_id_returns_plan_not_found(self, api):
        """PRD 2.11: "A `plan_id` that matches no plan yields `ERR_PLAN_NOT_FOUND`; a
        `participant_id` that matches no participant yields `ERR_PARTICIPANT_NOT_FOUND`; a
        `valuation_id`, or a `supersedes_valuation_id`, that matches no valuation yields
        `ERR_VALUATION_NOT_FOUND`; a `loan_id` that matches no loan yields
        `ERR_LOAN_NOT_FOUND`; and a `distribution_election_id` that matches no election yields
        `ERR_ELECTION_NOT_FOUND`."
        PRD 2.11: "Body-level foreign-key existence is checked on participant creation,
        valuation submission, loan creation, loan payment recording, allocation run creation,
        distribution election creation and put option exercise creation."

        Design: Corner/entities/create_participant_with_unknown_plan_id_returns_plan_not_found
        """
        set_clock("2026-03-02T00:00:00Z", SPONSOR)
        payload = create_participant_payload(
            UNKNOWN_UUID, employee_number="E-902", date_of_birth="1990-01-01",
            hire_date="2020-01-01",
        )
        del payload["eligible_compensation_cents"]
        validate_error(api.create_participant(payload, SPONSOR), ApiErrorId.ERR_PLAN_NOT_FOUND)

    def test_list_participants_paginates_and_filters_by_plan(self, api):
        """PRD 2.3: "List responses report `limit`, `offset`, `total_count` and `has_more`
        inside `meta`, where `total_count` counts every row matching the filters before the
        page window is applied and `has_more` is true whenever rows remain beyond the current
        window."
        PRD 2.3: "Filters are additive and all optional. Participant lists accept
        `plan_id` and `status`."

        Design: Corner/entities/list_participants_paginates_and_filters_by_plan
        """
        set_clock("2026-03-02T00:00:00Z", SPONSOR)
        plan_a = create_plan(plan_name="List Plan A", sponsor_name="Corner Corp")
        plan_b = create_plan(plan_name="List Plan B", sponsor_name="Corner Corp")
        ids_a = [
            create_participant(plan_a["id"], employee_number="E-001",
                               eligible_compensation_cents=40_000_000)["id"],
            create_participant(plan_a["id"], employee_number="E-002",
                               date_of_birth="1982-09-23", hire_date="2016-06-01",
                               eligible_compensation_cents=20_000_000)["id"],
            create_participant(plan_a["id"], employee_number="E-003",
                               date_of_birth="1990-02-14", hire_date="2019-03-15",
                               eligible_compensation_cents=10_000_000)["id"],
        ]
        id_b = create_participant(plan_b["id"], employee_number="E-010",
                                  date_of_birth="1985-01-01", hire_date="2018-01-01",
                                  eligible_compensation_cents=5_000_000)["id"]

        rows, meta = validate_paginated(
            api.list_participants(ADMIN, params={"plan_id": plan_a["id"], "limit": 2, "offset": 0})
        )
        assert len(rows) == 2, "the page window caps the returned rows at limit"
        assert meta["total_count"] == 3, "total_count counts every row matching the filters"
        assert meta["limit"] == 2 and meta["offset"] == 0
        assert meta["has_more"] is True, "rows remain beyond the current window"
        returned = [r["id"] for r in rows]
        assert all(r in ids_a for r in returned), "only plan A participants match the filter"
        assert id_b not in returned, "plan B's participant never appears under a plan A filter"

        rows_b, meta_b = validate_paginated(
            api.list_participants(ADMIN, params={"plan_id": plan_b["id"]})
        )
        assert len(rows_b) == 1 and meta_b["total_count"] == 1
        assert meta_b["has_more"] is False

    def test_duplicate_employee_number_within_plan_rejected(self, api):
        """PRD 3.1: "The payroll identifier must be unique within the plan; a second enrolment
        reusing an identifier already held by another participant of the same plan is refused
        with `ERR_DUPLICATE_EMPLOYEE_NUMBER`."

        Design: Corner/entities/duplicate_employee_number_within_plan_rejected
        """
        set_clock("2026-03-02T00:00:00Z", SPONSOR)
        plan_a = create_plan(plan_name="Dup Plan A", sponsor_name="Corner Corp")
        plan_b = create_plan(plan_name="Dup Plan B", sponsor_name="Corner Corp")
        create_participant(plan_a["id"], employee_number="E-001",
                           eligible_compensation_cents=40_000_000)

        dup = create_participant_payload(
            plan_a["id"], employee_number="E-001", date_of_birth="1991-11-11",
            hire_date="2021-01-01", eligible_compensation_cents=1_000_000,
        )
        validate_error(api.create_participant(dup, SPONSOR),
                       ApiErrorId.ERR_DUPLICATE_EMPLOYEE_NUMBER)
        _rows, meta = validate_paginated(
            api.list_participants(ADMIN, params={"plan_id": plan_a["id"]})
        )
        assert meta["total_count"] == 1, "the refused enrolment persists nothing"

        other_plan = create_participant_payload(
            plan_b["id"], employee_number="E-001", date_of_birth="1991-11-11",
            hire_date="2021-01-01", eligible_compensation_cents=1_000_000,
        )
        created = validate_success(api.create_participant(other_plan, SPONSOR), 201)
        assert created["employee_number"] == "E-001", (
            "uniqueness is scoped to the plan, so another plan may reuse the identifier"
        )

    def test_patch_participant_updates_only_payroll_facts(self, api):
        """PRD 3.1: "Payroll facts change during a year, so the sponsor may update
        `eligible_compensation_cents` and `annual_hours` on an existing participant — either
        one, or both, or neither — for as long as the plan remains `OPEN`."
        PRD 2.4: "Most resources additionally carry `updated_at`, in the same ISO 8601 UTC
        format with three fractional digits, and `version`, an integer that starts at 1 on
        creation and increments by exactly 1 on every mutation of that resource."

        Design: Corner/entities/patch_participant_updates_only_payroll_facts
        """
        set_clock("2026-03-02T00:00:00Z", SPONSOR)
        plan = create_plan(plan_name="Patch Plan", sponsor_name="Corner Corp")
        participant = create_participant(plan["id"], employee_number="E-777",
                                         eligible_compensation_cents=10_000_000)

        updated = validate_success(
            api.update_participant(participant["id"], {"eligible_compensation_cents": 41_000_000},
                                   SPONSOR)
        )
        assert updated["eligible_compensation_cents"] == 41_000_000
        assert updated["annual_hours"] == 2000, "annual_hours is untouched by this patch"
        assert updated["employee_number"] == "E-777"
        assert updated["hire_date"] == "2015-01-05"
        assert updated["status"] == "ACTIVE"
        assert updated["version"] == 2, "version increments by exactly 1 on every mutation"
        assert updated["updated_at"] >= updated["created_at"]

    def test_default_pagination_window_is_ten_from_zero(self, api):
        """PRD 2.3: "Every collection-returning endpoint is paginated by the same two query
        parameters. `limit` defaults to 10 when omitted, must be at least 1, and may not
        exceed 100. `offset` defaults to 0 and may not be negative."

        Design: Corner/entities/list_participants_paginates_and_filters_by_plan
        """
        set_clock("2026-03-02T00:00:00Z", SPONSOR)
        plan = create_plan(plan_name="Window Plan", sponsor_name="Corner Corp")
        create_participant(plan["id"], employee_number="E-001")

        _rows, meta = validate_paginated(
            api.list_participants(ADMIN, params={"plan_id": plan["id"]})
        )
        assert meta["limit"] == PAGINATION_DEFAULT_LIMIT, "limit defaults to 10 when omitted"
        assert meta["offset"] == 0, "offset defaults to 0"
