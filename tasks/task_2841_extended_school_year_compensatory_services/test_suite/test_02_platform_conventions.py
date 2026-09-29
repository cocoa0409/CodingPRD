"""Platform-wide conventions: system fields, defaults, pagination, and the
authentication / role / not-found layers that sit in front of every endpoint.
"""

import pytest

from test_helpers import (
    NON_EXISTENT_UUID,
    ApiErrorId,
    assert_pagination_meta,
    assert_provider,
    assert_student,
    factories,
    fixtures,
    is_iso8601_timestamp,
    is_valid_uuid,
    make_case_manager_headers,
    make_compliance_officer_headers,
    make_program_coordinator_headers,
    make_sped_director_headers,
    validate_error,
    validate_paginated,
    validate_success,
)

CM = make_case_manager_headers()
PC = make_program_coordinator_headers()
DIR = make_sped_director_headers()
CO = make_compliance_officer_headers()

CLOCK = "2027-06-01T00:00:00Z"
ZERO_ID = NON_EXISTENT_UUID


class TestStudentRecord:
    """Registration inputs, derived defaults, and an unchanged read-back."""

    def test_registration_returns_201_with_every_derived_field_at_its_default(self, api):
        """A fresh student echoes its inputs and reports all six derived values at zero/false.

        The PRD says of the derived block: "At registration `esy_eligibility_status`
        reads `NOT_DETERMINED` — the other possible values being `ELIGIBLE`,
        `INELIGIBLE` and `PENDING_DATA` — and it is written by exactly one event in
        the whole system: the finalization of an eligibility determination." and
        "Alongside it, four minute totals and two flags start at zero or false and
        are maintained by full recomputation as described in §2.11." The version
        counter's opening value is fixed too: "`version` is an integer that starts at
        1 when the resource is created and increases by exactly 1 on every mutation
        of that resource, whether the mutation was requested directly or produced as
        a side effect of an operation against some other resource." Creation status
        is fixed by "Newly created resources are returned with HTTP 201."

        Design: Corner/entities/student_creation_populates_defaults_and_system_fields
        """
        fixtures.set_clock(api, CLOCK)

        student = validate_success(
            api.create_student(
                factories.student_payload(
                    student_number="S-2841-001",
                    first_name="Ada",
                    last_name="Reyes",
                    grade_band="MS_6_8",
                    primary_disability="AUTISM",
                    iep_weekly_minutes_total=250,
                    home_school_code="MS-014",
                    transportation_required=True,
                ),
                CM,
            ),
            201,
        )

        assert_student(student)
        assert student["student_number"] == "S-2841-001"
        assert student["grade_band"] == "MS_6_8"
        assert student["primary_disability"] == "AUTISM"
        assert student["iep_weekly_minutes_total"] == 250
        assert student["transportation_required"] is True
        assert student["esy_eligibility_status"] == "NOT_DETERMINED"
        assert student["pending_award_minutes"] == 0
        assert student["outstanding_owed_minutes"] == 0
        assert student["delivered_makeup_minutes_total"] == 0
        assert student["esy_service_alert"] is False
        assert student["stay_put_active"] is False
        assert student["version"] == 1

    def test_reading_a_student_returns_the_stored_row_without_bumping_version(self, api):
        """A read is not a mutation: the row comes back identical, at the same version.

        The read is available to staff: "A single student read returns all six derived
        values alongside the registered inputs, and it is available to every staff
        role and — restricted to their own child — to a `ParentGuardian`." Because a
        read changes nothing, the version counter must not move: "`version` is an
        integer that starts at 1 when the resource is created and increases by
        exactly 1 on every mutation of that resource, whether the mutation was
        requested directly or produced as a side effect of an operation against some
        other resource."

        Design: Corner/entities/student_retrieval_returns_the_stored_row_unchanged
        """
        fixtures.set_clock(api, CLOCK)
        created = fixtures.register_student(api, student_number="S-2841-001")

        fetched = validate_success(api.get_student(created["id"], CO))

        assert fetched["id"] == created["id"]
        assert fetched["student_number"] == "S-2841-001"
        assert fetched["home_school_code"] == "MS-014"
        assert fetched["iep_weekly_minutes_total"] == 250
        assert fetched["version"] == created["version"]
        assert fetched["updated_at"] == created["updated_at"]

    def test_unknown_student_path_id_returns_the_student_not_found_error(self, api):
        """An id that resolves to nothing is a 404 carrying the error envelope.

        Path resolution is check 5 of the ordered validation sequence: "Every
        identifier in the request path resolves, checked left to right — otherwise
        the matching not-found code from §2.6. Applies to every endpoint carrying a
        path parameter." The failure shape is fixed by "The `meta` object for error
        responses contains only `api_request_id` and `api_request_timestamp`."

        Design: Corner/entities/student_path_id_unknown_returns_student_not_found
        """
        fixtures.set_clock(api, CLOCK)

        response = api.get_student(ZERO_ID, CM)

        validate_error(response, ApiErrorId.STUDENT_NOT_FOUND.value, 404)
        assert response.json()["response_type"] == "error"


class TestDeclaredDefaultsAndTypeConstraints:
    """Omitted optionals versus malformed inputs."""

    def test_omitted_optional_arrays_and_flags_take_their_declared_defaults(self, api):
        """A program without `blackout_dates` and a student without the transport flag.

        For the program the PRD says: "An optional `blackout_dates` array names
        planned non-instructional dates inside the session window, such as a holiday
        or a staff-development day; each entry must be an `YYYY-MM-DD` date falling
        within the session window, and when the array is omitted it is stored
        empty." and of the other array: "`cancelled_dates` is not a client input. It
        starts empty and is appended to only by the day-cancellation operation of
        §3.6, at which point both derived counts are re-derived." With both arrays
        empty the derivation is pure calendar arithmetic: "Walk the inclusive range
        of dates from `session_start_date` through `session_end_date`; keep a date
        when its weekday name appears in `instructional_weekdays`, when it does not
        appear in `blackout_dates`, and when it does not appear in `cancelled_dates`."
        For the student: "An optional `transportation_required` flag records whether
        the IEP marks transportation as a related service; when omitted it is stored
        as false."

        Design: Corner/entities/program_and_student_omitted_optional_inputs_take_declared_defaults
        """
        fixtures.set_clock(api, CLOCK)

        program = validate_success(
            api.create_program(
                factories.program_payload(
                    name="Summer ESY 2027 No Blackouts",
                    blackout_dates=factories.OMIT,
                ),
                PC,
            ),
            201,
        )
        student = validate_success(
            api.create_student(
                factories.student_payload(
                    student_number="S-2841-002",
                    first_name="Ben",
                    last_name="Okafor",
                    primary_disability="SPECIFIC_LEARNING_DISABILITY",
                    transportation_required=factories.OMIT,
                ),
                CM,
            ),
            201,
        )

        assert program["blackout_dates"] == []
        assert program["cancelled_dates"] == []
        # MON-THU across 2027-06-14..2027-07-23 with nothing removed: 6 ISO weeks
        # of 4 instructional days each.
        assert program["instructional_days_count"] == 24
        assert program["instructional_week_count"] == 6
        assert program["status"] == "PLANNING"
        assert student["transportation_required"] is False

    def test_out_of_enum_out_of_range_and_reversed_dates_are_all_invalid_requests(
        self, api
    ):
        """Three structurally unsound bodies, one error id.

        Check 7 of the ordered sequence covers all three: "The request body is
        structurally sound: all required inputs present, every enum value inside its
        declared set, integers non-negative, dates written as `YYYY-MM-DD`, times
        written as `HH:MM` on a 24-hour clock, any end value strictly after its
        matching start value, and delivered minutes never exceeding the scheduled or
        planned minutes they settle — otherwise `ERR_INVALID_REQUEST`. Applies to
        every write endpoint." The declared domains are "the `grade_band` that will
        later pick the summer staffing ratio (one of `PRE_K`, `K_5`, `MS_6_8`,
        `HS_9_12`)", "the `iep_weekly_minutes_total` carrying the school-year IEP's
        whole weekly special-education minute figure (required, between 1 and 3000)"
        and "a `session_start_date` and a `session_end_date` written as `YYYY-MM-DD`
        with the end never earlier than the start, both inclusive".

        Design: Corner/entities/student_and_program_type_constraint_violations_rejected
        """
        fixtures.set_clock(api, CLOCK)

        bad_enum = api.create_student(
            factories.student_payload(
                student_number="S-2841-090", grade_band="GRADE_7"
            ),
            CM,
        )
        validate_error(bad_enum, ApiErrorId.INVALID_REQUEST.value, 422)

        below_range = api.create_student(
            factories.student_payload(
                student_number="S-2841-091", iep_weekly_minutes_total=0
            ),
            CM,
        )
        validate_error(below_range, ApiErrorId.INVALID_REQUEST.value, 422)

        reversed_window = api.create_program(
            factories.program_payload(
                name="Backwards Session",
                session_start_date="2027-07-23",
                session_end_date="2027-06-14",
                instructional_weekdays=["MON"],
                blackout_dates=factories.OMIT,
            ),
            PC,
        )
        validate_error(reversed_window, ApiErrorId.INVALID_REQUEST.value, 422)

    def test_program_creation_without_instructional_weekdays_is_rejected(self, api):
        """The weekday list is required, so omitting it fails the structural check.

        The input is declared mandatory: "`instructional_weekdays` lists between one
        and five distinct weekday names drawn from `MON`, `TUE`, `WED`, `THU` and
        `FRI` — a four-day summer week is normal — and `daily_minutes_cap` fixes,
        between 1 and 480, the most service minutes any single student may be
        scheduled to receive on one instructional day." Check 7 supplies the code:
        "The request body is structurally sound: all required inputs present, every
        enum value inside its declared set, integers non-negative, dates written as
        `YYYY-MM-DD`, times written as `HH:MM` on a 24-hour clock, any end value
        strictly after its matching start value, and delivered minutes never
        exceeding the scheduled or planned minutes they settle — otherwise
        `ERR_INVALID_REQUEST`. Applies to every write endpoint."

        Design: Corner/entities/program_creation_missing_required_instructional_weekdays_rejected
        """
        fixtures.set_clock(api, CLOCK)

        response = api.create_program(
            factories.program_payload(instructional_weekdays=factories.OMIT), PC
        )

        validate_error(response, ApiErrorId.INVALID_REQUEST.value, 422)


class TestListPagination:
    """`limit` / `offset` behaviour and the transportation-run natural order."""

    def test_transportation_run_list_pages_in_service_date_order(self, api):
        """Two pages of a three-run list, each reporting resolved paging metadata.

        The PRD fixes the parameter semantics: "Every list endpoint accepts two
        optional query parameters. `limit` controls page size: it defaults to 10 when
        omitted, may be no smaller than 1, and may be no larger than 100. `offset`
        controls the starting position: it defaults to 0 when omitted and may be no
        smaller than 0." It fixes what `meta` reports: "For paginated responses the
        `meta` object carries `limit` and `offset` as they were resolved for that
        request, `total_count` giving the number of records matching the request's
        filters before pagination is applied, and `has_more` — true exactly when
        records matching the filters remain beyond the current page." It also fixes
        this list's order: "transportation runs are ordered by `service_date`
        ascending, then `window_start_time` ascending, then `created_at` ascending".

        Design: Corner/entities/transportation_run_listing_paginates_with_limit_and_offset
        """
        fixtures.set_clock(api, CLOCK)
        program = fixtures.create_program(api)
        for route_code, service_date in (
            ("R1", "2027-06-14"),
            ("R2", "2027-06-15"),
            ("R3", "2027-06-16"),
        ):
            fixtures.schedule_run(
                api,
                program["id"],
                route_code=route_code,
                service_date=service_date,
                window_start_time="07:00",
                window_end_time="07:45",
                vehicle_capacity_seats=12,
            )

        first_page, first_meta = validate_paginated(
            api.list_program_transportation_runs(
                program["id"], PC, {"limit": 2, "offset": 0}
            )
        )
        second_page, second_meta = validate_paginated(
            api.list_program_transportation_runs(
                program["id"], PC, {"limit": 2, "offset": 2}
            )
        )

        assert len(first_page) == 2
        assert_pagination_meta(first_meta, 3, True, 2, 0)
        assert [row["service_date"] for row in first_page] == [
            "2027-06-14",
            "2027-06-15",
        ]

        assert len(second_page) == 1
        assert_pagination_meta(second_meta, 3, False, 2, 2)
        assert second_page[0]["service_date"] == "2027-06-16"
        assert second_page[0]["route_code"] == "R3"

    @pytest.mark.parametrize(
        "params",
        [
            {"limit": 0},
            {"limit": 101},
            {"offset": -1},
        ],
    )
    def test_pagination_arguments_outside_their_declared_ranges_are_rejected(
        self, api, params
    ):
        """A zero page size, an oversized page size, and a negative offset all fail.

        The bounds are declared: "A `limit` outside the range 1 through 100 inclusive,
        or a negative `offset`, or either parameter supplied as something other than
        an integer, is rejected with `ERR_INVALID_PAGINATION` (HTTP 422)." Check 8 of
        the ordered validation sequence puts the test on every list endpoint:
        "`limit` and `offset` are within their declared ranges — otherwise
        `ERR_INVALID_PAGINATION`. Applies to every list endpoint."

        Design: Corner/errors/list_endpoints_with_out_of_range_pagination_rejected
        """
        fixtures.set_clock(api, CLOCK)

        rejected = api.list_service_logs(CM, params)

        validate_error(rejected, ApiErrorId.INVALID_PAGINATION.value, 422)

    def test_a_list_at_the_maximum_page_size_returns_an_empty_page(self, api):
        """The upper bound of the declared range is itself accepted.

        The range is inclusive at both ends: "A `limit` outside the range 1 through
        100 inclusive, or a negative `offset`, or either parameter supplied as
        something other than an integer, is rejected with `ERR_INVALID_PAGINATION`
        (HTTP 422)." An empty result set still reports its paging figures: "For
        paginated responses the `meta` object carries `limit` and `offset` as they
        were resolved for that request, `total_count` giving the number of records
        matching the request's filters before pagination is applied, and `has_more` —
        true exactly when records matching the filters remain beyond the current
        page."

        Design: Corner/errors/list_endpoints_with_out_of_range_pagination_rejected
        """
        fixtures.set_clock(api, CLOCK)

        rows, meta = validate_paginated(
            api.list_service_logs(CM, {"limit": 100, "offset": 0})
        )

        assert rows == []
        assert_pagination_meta(meta, 0, False, 100, 0)


class TestNotFoundResolution:
    """Path identifiers and body identifiers resolve before anything else runs."""

    @pytest.mark.parametrize(
        "call_name, expected_error",
        [
            ("determination", ApiErrorId.DETERMINATION_NOT_FOUND),
            ("program", ApiErrorId.PROGRAM_NOT_FOUND),
            ("provider", ApiErrorId.PROVIDER_NOT_FOUND),
            ("commitment", ApiErrorId.COMMITMENT_NOT_FOUND),
            ("assignment", ApiErrorId.ASSIGNMENT_NOT_FOUND),
            ("service_log", ApiErrorId.SERVICE_LOG_NOT_FOUND),
            ("award", ApiErrorId.AWARD_NOT_FOUND),
            ("makeup_session", ApiErrorId.MAKEUP_SESSION_NOT_FOUND),
            ("fund_allocation", ApiErrorId.FUND_ALLOCATION_NOT_FOUND),
            ("due_process_record", ApiErrorId.DUE_PROCESS_RECORD_NOT_FOUND),
        ],
    )
    def test_each_unresolvable_path_id_returns_its_own_not_found_code(
        self, api, call_name, expected_error
    ):
        """Ten distinct path parameters, ten distinct 404 codes.

        The catalogue is exhaustive and per-parameter: "The remaining path-level
        not-found codes are `ERR_DETERMINATION_NOT_FOUND` for `determination_id`,
        `ERR_PROGRAM_NOT_FOUND` for `program_id`, `ERR_PROVIDER_NOT_FOUND` for
        `provider_id`, `ERR_COMMITMENT_NOT_FOUND` for `commitment_id`,
        `ERR_ASSIGNMENT_NOT_FOUND` for `assignment_id`,
        `ERR_SERVICE_LOG_NOT_FOUND` for `log_id`, `ERR_AWARD_NOT_FOUND` for
        `award_id`, `ERR_MAKEUP_SESSION_NOT_FOUND` for `session_id`,
        `ERR_FUND_ALLOCATION_NOT_FOUND` for `allocation_id`, and
        `ERR_DUE_PROCESS_RECORD_NOT_FOUND` for `record_id`. All ten answer HTTP 404."
        Resolution runs as check 5, before body structure or state: "Every identifier
        in the request path resolves, checked left to right — otherwise the matching
        not-found code from §2.6. Applies to every endpoint carrying a path
        parameter."

        Design: Corner/errors/unknown_path_ids_return_the_entity_specific_not_found_error
        """
        fixtures.set_clock(api, CLOCK)

        calls = {
            "determination": lambda: api.get_determination(ZERO_ID, CM),
            "program": lambda: api.get_program(ZERO_ID, PC),
            "provider": lambda: api.get_provider(ZERO_ID, PC),
            "commitment": lambda: api.get_commitment(ZERO_ID, PC),
            "assignment": lambda: api.release_provider_assignment(
                ZERO_ID, {"release_reason": "STAFF_REASSIGNED"}, PC
            ),
            "service_log": lambda: api.get_service_log(ZERO_ID, CM),
            "award": lambda: api.get_award(ZERO_ID, CM),
            "makeup_session": lambda: api.get_makeup_session(ZERO_ID, CM),
            "fund_allocation": lambda: api.patch_fund_allocation(
                ZERO_ID, {"status": "FROZEN"}, DIR
            ),
            "due_process_record": lambda: api.patch_due_process_record(
                ZERO_ID, {"status": "RESOLVED"}, CO
            ),
        }

        validate_error(calls[call_name](), expected_error.value, 404)

    def test_unresolvable_body_identifiers_beat_the_domain_gates_behind_them(self, api):
        """A dangling `student_id`, then a dangling `transportation_run_id`.

        Body resolution is its own check, using the same catalogue: "Identifiers
        supplied in a request **body** are resolved the same way and with the same
        codes, once the path has resolved cleanly. A body carrying `student_id`,
        `program_id`, `source_program_id`, `provider_id`, `commitment_id`, `award_id`,
        `transportation_run_id` or `supersedes_session_id` that points at nothing
        yields the matching not-found code for the referenced kind of record —
        `ERR_PROGRAM_NOT_FOUND` covers both `program_id` and `source_program_id`,
        `ERR_RUN_NOT_FOUND` covers `transportation_run_id`, and
        `ERR_MAKEUP_SESSION_NOT_FOUND` covers `supersedes_session_id`." It runs as
        check 6, ahead of the eligibility gate of check 9: "Every identifier in the
        request body resolves — otherwise the matching not-found code. Applies to
        every write endpoint carrying an identifier in its body." The masked gate is
        real: "A student whose eligibility reads `NOT_DETERMINED`, `INELIGIBLE` or
        `PENDING_DATA` cannot be committed, and the attempt is refused with
        `ERR_STUDENT_NOT_ESY_ELIGIBLE`."

        Design: Corner/errors/unknown_body_foreign_keys_return_the_referenced_entity_not_found
        """
        fixtures.set_clock(api, CLOCK)
        program = fixtures.create_program(api)
        not_determined = fixtures.register_student(api, student_number="S-2841-070")

        missing_student = api.create_commitment(
            factories.commitment_payload(program["id"], ZERO_ID), CM
        )
        validate_error(missing_student, ApiErrorId.STUDENT_NOT_FOUND.value, 404)

        missing_run = api.create_commitment(
            factories.commitment_payload(
                program["id"], not_determined["id"], transportation_run_id=ZERO_ID
            ),
            CM,
        )
        validate_error(missing_run, ApiErrorId.RUN_NOT_FOUND.value, 404)

        rows, meta = validate_paginated(
            api.list_commitments(CM, {"program_id": program["id"]})
        )
        assert rows == []
        assert meta["total_count"] == 0

    def test_commitment_creation_against_an_unknown_program_is_a_404(self, api):
        """The program reference is resolved before the student's eligibility is read.

        Body identifiers resolve at check 6: "Every identifier in the request body
        resolves — otherwise the matching not-found code. Applies to every write
        endpoint carrying an identifier in its body." The gate it masks fires only
        later, at check 9: "Two hard gates guard creation: the named program must be
        in `PLANNING`, and the named student's `esy_eligibility_status` must read
        `ELIGIBLE`." A missing `program_id` therefore answers
        `ERR_PROGRAM_NOT_FOUND`, because "`ERR_PROGRAM_NOT_FOUND` covers both
        `program_id` and `source_program_id`".

        Design: Corner/entities/commitment_creation_with_unknown_program_id_returns_404
        """
        fixtures.set_clock(api, CLOCK)
        not_determined = fixtures.register_student(api, student_number="S-2841-071")

        response = api.create_commitment(
            factories.commitment_payload(ZERO_ID, not_determined["id"]), CM
        )

        validate_error(response, ApiErrorId.PROGRAM_NOT_FOUND.value, 404)


class TestAuthenticationAndRoleGates:
    """Checks 1 and 2 sit in front of every endpoint, including reads."""

    def test_absent_or_empty_identity_headers_are_unauthenticated_before_anything_else(
        self, api
    ):
        """A missing header pair, an empty id, and an empty role are all 401.

        The rule covers every endpoint: "Every request to this API — including reads
        and including the test-driving clock endpoint — must carry two headers:
        `X-User-ID`, identifying the acting user, and `X-User-Role`, naming the role
        that user is acting in. If either header is absent or present but empty, the
        request is rejected with `ERR_UNAUTHENTICATED` (HTTP 401). No endpoint is
        anonymous." It is check 1 of the ordered sequence, so it masks the structural
        check on a malformed body: "Both `X-User-ID` and `X-User-Role` are present and
        non-empty — otherwise `ERR_UNAUTHENTICATED`. Applies to every endpoint."

        Design: Corner/errors/requests_with_missing_x_user_headers_return_unauthenticated
        """
        fixtures.set_clock(api, CLOCK)
        malformed = {"student_number": "S-2841-009", "grade_band": "GRADE_7"}

        no_headers = api.post_without_headers("/esy/students", malformed)
        validate_error(no_headers, ApiErrorId.UNAUTHENTICATED.value, 401)

        empty_user_id = api.request(
            "POST",
            "/esy/students",
            factories.student_payload(student_number="S-2841-009"),
            {"X-User-ID": "", "X-User-Role": "CaseManager"},
        )
        validate_error(empty_user_id, ApiErrorId.UNAUTHENTICATED.value, 401)

        empty_role = api.request(
            "POST",
            "/esy/students",
            factories.student_payload(student_number="S-2841-009"),
            {"X-User-ID": "cm-001", "X-User-Role": ""},
        )
        validate_error(empty_role, ApiErrorId.UNAUTHENTICATED.value, 401)

    def test_every_role_may_perform_the_write_that_belongs_to_it(self, api):
        """Five creates, five different owning roles, five 201s.

        The gate is an allow-list per endpoint, not a blanket deny: "If `X-User-Role`
        holds any string outside this set of six, or holds a valid role that is not
        among the roles authorized for the endpoint being addressed, the request is
        rejected with `ERR_ROLE_NOT_PERMITTED` (HTTP 403). The authoritative
        role-to-endpoint mapping is the table in §4." Ownership of each write is
        declared with the operation: "A `CaseManager` registers each student the
        district might serve over the summer."; "A `ProgramCoordinator` registers each
        provider with a `full_name` of 1 to 60 characters, a credentialed `role_type`
        (`SPED_TEACHER`, `SLP`, `OT`, `PT`, `COUNSELOR` or `PARAEDUCATOR`), a
        `credential_expires_on` date naming the last day the credential is valid
        inclusive, a `rate_cents_per_minute` between 1 and 2000 giving the fully
        loaded cost of a service minute, and a `max_weekly_minutes` between 1 and
        3000 fixing the contractual weekly service-minute ceiling."; "Separately, a
        `SpedDirector` authorizes the money."; and "A `ComplianceOfficer` files each
        record against a `student_id`, giving the `record_type`, the `filed_on` date
        the filing was received, and an `allegation_summary` of 1 to 500 characters
        narrating the allegation or, for a mediated settlement, the terms agreed."
        Filing one of the protective record types reaches back into the student:
        "Filing recomputes the student's `stay_put_active` and increments the
        student's `version`."

        Design: Corner/rbac/each_role_can_perform_its_own_exclusive_operations
        """
        fixtures.set_clock(api, CLOCK)

        student = validate_success(
            api.create_student(
                factories.student_payload(student_number="S-2841-001"), CM
            ),
            201,
        )
        program = validate_success(
            api.create_program(factories.program_payload(), PC), 201
        )
        provider = validate_success(
            api.create_provider(factories.provider_payload(), PC), 201
        )
        allocation = validate_success(
            api.create_fund_allocation(
                factories.fund_allocation_payload(program["id"]), DIR
            ),
            201,
        )
        record = validate_success(
            api.create_due_process_record(
                factories.due_process_record_payload(student["id"], "COMPLAINT"), CO
            ),
            201,
        )

        assert student["esy_eligibility_status"] == "NOT_DETERMINED"
        assert student["version"] == 1
        assert program["status"] == "PLANNING"
        # MON-THU over 2027-06-14..2027-07-23 less two blackout dates.
        assert program["instructional_days_count"] == 22
        assert provider["status"] == "ACTIVE"
        assert provider["assigned_weekly_minutes"] == 0
        assert allocation["status"] == "OPEN"
        assert allocation["available_cents"] == 25000000
        assert record["status"] == "OPEN"
        assert fixtures.refresh_student(api, student["id"])["stay_put_active"] is True

    def test_a_case_manager_cannot_authorize_a_budget_code(self, api):
        """The same allocation payload is refused for a case manager, accepted for a director.

        Budget authorization belongs to one role: "Separately, a `SpedDirector`
        authorizes the money." Anyone else addressing that endpoint fails check 2:
        "If `X-User-Role` holds any string outside this set of six, or holds a valid
        role that is not among the roles authorized for the endpoint being addressed,
        the request is rejected with `ERR_ROLE_NOT_PERMITTED` (HTTP 403). The
        authoritative role-to-endpoint mapping is the table in §4." A refused create
        persists nothing, and the accepted one opens with its ceiling untouched: "An
        allocation's `encumbered_amount_cents`, `expended_amount_cents` and
        `compensatory_expended_cents` all start at zero, and `available_cents` is
        derived as described in §2.9." with "At all times, and after every posting or
        reversal, an allocation's `available_cents` equals its
        `authorized_amount_cents` less its `encumbered_amount_cents` less its
        `expended_amount_cents`."

        Design: Corner/rbac/case_manager_cannot_create_a_fund_allocation
        """
        fixtures.set_clock(api, CLOCK)
        program = fixtures.create_program(api)
        payload = factories.fund_allocation_payload(program["id"])

        refused = api.create_fund_allocation(payload, CM)
        validate_error(refused, ApiErrorId.ROLE_NOT_PERMITTED.value, 403)

        _, meta = validate_paginated(
            api.list_program_fund_allocations(program["id"], DIR)
        )
        assert meta["total_count"] == 0

        allocation = validate_success(api.create_fund_allocation(payload, DIR), 201)
        assert allocation["available_cents"] == 25000000


class TestSystemFieldsAndInitialStates:
    """The four common properties, and the state each create endpoint stamps."""

    def test_provider_registration_stamps_the_common_properties(self, api):
        """A new provider carries a UUID id, matching timestamps from the logical clock, version 1.

        The four common properties are universal: "`id` is a server-minted UUID; it
        carries no type prefix and clients never supply it."; "`created_at` is the ISO
        8601 UTC instant the resource was created, rendered with exactly three
        fractional-second digits (for example `2026-08-01T00:00:00.000Z`).";
        "`updated_at` is the ISO 8601 UTC instant of the resource's most recent
        mutation, in the same format; at creation it equals `created_at`."; and
        "`version` is an integer that starts at 1 when the resource is created and
        increases by exactly 1 on every mutation of that resource, whether the
        mutation was requested directly or produced as a side effect of an operation
        against some other resource." The instant comes from the logical clock, never
        the host: "The server must never fall back to real system time, not at startup
        and not between requests." The provider's own opening values are declared: "A
        provider's `status` starts at `ACTIVE` and may later read `ON_LEAVE` or
        `INACTIVE`; a coordinator may update `status`, `credential_expires_on` or
        `max_weekly_minutes` at any time, each field independently optional on the
        update." and "The derived `assigned_weekly_minutes` starts at zero and always
        equals the sum of `covered_weekly_minutes` across that provider's `ACTIVE`
        assignments."

        Design: Corner/entities/provider_creation_stamps_system_fields_and_initial_version
        """
        fixtures.set_clock(api, CLOCK)

        provider = validate_success(
            api.create_provider(
                factories.provider_payload(
                    full_name="Nina Torres",
                    role_type="SPED_TEACHER",
                    credential_expires_on="2028-06-30",
                    rate_cents_per_minute=150,
                    max_weekly_minutes=1200,
                ),
                PC,
            ),
            201,
        )

        assert_provider(provider)
        assert is_valid_uuid(provider["id"])
        assert is_iso8601_timestamp(provider["created_at"])
        # The clock was pinned to 2027-06-01T00:00:00Z; §2.4 renders instants with
        # three fractional digits, so compare on the second-precision prefix.
        assert provider["created_at"].startswith("2027-06-01T00:00:00")
        assert provider["updated_at"] == provider["created_at"]
        assert provider["version"] == 1
        assert provider["status"] == "ACTIVE"
        assert provider["assigned_weekly_minutes"] == 0
        assert provider["rate_cents_per_minute"] == 150
        assert provider["max_weekly_minutes"] == 1200

    def test_six_create_endpoints_stamp_their_own_declared_initial_state(self, api):
        """None of the six accepts a status input; each opens where the PRD says it opens.

        Each initial state is declared with its entity. A determination: "A
        `CaseManager` opens a determination in `DRAFT` for one `student_id` and one
        `school_year` written as `YYYY-YYYY` (for example `2026-2027`), choosing an
        `analysis_variant` of either `PROBE_BASED` or `TEAM_JUDGMENT` and attaching
        the evidence itself as `skill_probes`." A program: "A `ProgramCoordinator`
        creates each session as a program in `PLANNING`, giving it a `name` of 1 to 80
        characters (typically something like "Summer 2027 ESY - Elementary"), the
        `school_year` it belongs to in `YYYY-YYYY` form, a `session_start_date` and a
        `session_end_date` written as `YYYY-MM-DD` with the end never earlier than the
        start, both inclusive." An allocation: "Allocations cycle. A director may move
        one `OPEN → FROZEN`, which removes it from the waterfall's candidate filter,
        and back `FROZEN → OPEN`, which returns it; either direction increments the
        allocation's `version`." with "An allocation's `encumbered_amount_cents`,
        `expended_amount_cents` and `compensatory_expended_cents` all start at zero,
        and `available_cents` is derived as described in §2.9." A run: "A run's own
        `status` starts at `SCHEDULED` and has exactly one exit." A commitment:
        "Commitments follow a six-state lifecycle beginning at `PLANNED`." with "A
        commitment's own ledger fields, `delivered_minutes` and
        `compensable_owed_minutes`, both start at zero and are maintained by full
        recomputation from that commitment's service logs, as §3.6 describes." A
        due-process record: "Each record's `status` starts at `OPEN`, and its own
        `stay_put_active` flag reads true exactly when its `status` is `OPEN` and its
        `record_type` is `COMPLAINT` or `DUE_PROCESS_HEARING`." And the flag it raises
        on the student: "It reads true exactly when at least one due-process record
        naming this student has `status` `OPEN` and a `record_type` of either
        `COMPLAINT` or `DUE_PROCESS_HEARING`".

        Design: Corner/state_machines/newly_created_rows_start_in_declared_initial_states
        """
        fixtures.set_clock(api, CLOCK)
        student = fixtures.register_student(api, student_number="S-2841-001")

        determination = validate_success(
            api.create_determination(
                factories.determination_payload(student["id"]), CM
            ),
            201,
        )
        assert determination["status"] == "DRAFT"

        eligible = fixtures.make_eligible_student(api, student_overrides={
            "student_number": "S-2841-002"
        })
        eligible_student = eligible["student"]

        program = validate_success(
            api.create_program(factories.program_payload(), PC), 201
        )
        allocation = validate_success(
            api.create_fund_allocation(
                factories.fund_allocation_payload(program["id"]), DIR
            ),
            201,
        )
        run = validate_success(
            api.create_transportation_run(
                factories.transportation_run_payload(
                    program["id"], route_code="R1", vehicle_capacity_seats=12
                ),
                PC,
            ),
            201,
        )
        commitment = validate_success(
            api.create_commitment(
                factories.commitment_payload(program["id"], eligible_student["id"]), CM
            ),
            201,
        )
        record = validate_success(
            api.create_due_process_record(
                factories.due_process_record_payload(
                    eligible_student["id"], "COMPLAINT"
                ),
                CO,
            ),
            201,
        )

        assert program["status"] == "PLANNING"
        assert allocation["status"] == "OPEN"
        assert allocation["available_cents"] == 25000000
        assert run["status"] == "SCHEDULED"
        assert run["seats_committed"] == 0
        assert commitment["status"] == "PLANNED"
        assert commitment["delivered_minutes"] == 0
        assert commitment["compensable_owed_minutes"] == 0
        assert record["status"] == "OPEN"
        assert record["resolution_note"] is None
        assert record["resolved_at"] is None
        assert (
            fixtures.refresh_student(api, eligible_student["id"])["stay_put_active"]
            is True
        )
