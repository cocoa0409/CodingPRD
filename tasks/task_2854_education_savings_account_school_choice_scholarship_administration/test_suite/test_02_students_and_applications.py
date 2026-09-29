"""Student intake, filing applications and the gates that protect creation."""

import pytest

from test_helpers import (
    AWARD_BAND_B_IEP,
    AWARD_BAND_B_IEP_AND_PRIOR_PUBLIC,
    MISSING_ID,
    PA,
    ApiErrorId,
    accept_award,
    assert_instant_equals,
    assert_student,
    create_application,
    create_application_payload,
    create_program_year,
    create_student,
    create_student_payload,
    make_guardian_headers,
    open_window,
    read_application,
    read_program_year,
    record_determination,
    run_awarding,
    set_clock,
    setup_draft_application,
    setup_open_year_and_student,
    setup_submitted_application,
    submit_application,
    validate_error,
    validate_paginated,
    validate_success,
)


class TestStudentIntake:
    """The stored student record and the shape checks at intake."""

    def test_stored_student_record_reads_back_exactly_as_registered(self, api):
        """PRD §3.2: "`category_flags` is a duplicate-free subset of `DISABILITY_IEP`,
        `FOSTER`, `MILITARY`, and `PRIOR_PUBLIC_SCHOOL` and defaults to the empty list,
        and `has_enrolled_sibling` defaults to false and is set true when a sibling
        already holds an accepted award in any programme year."

        Design: Corner/entities/student_retrieval_returns_the_stored_record
        """
        payload = create_student_payload(
            category_flags=["DISABILITY_IEP", "PRIOR_PUBLIC_SCHOOL"]
        )
        created = validate_success(api.create_student(payload, PA), expected_status=201)

        student = validate_success(api.get_student(created["id"], PA))
        assert_student(student)

        assert student["household_id"] == "HH-1", (
            f"household_id should be the stored grouping key, got {student['household_id']!r}"
        )
        assert student["first_name"] == "Ana" and student["last_name"] == "Reyes", (
            f"the name should read back unchanged, got {student!r}"
        )
        assert student["date_of_birth"] == "2014-04-02", (
            f"date_of_birth keeps its YYYY-MM-DD form, got {student['date_of_birth']!r}"
        )
        assert student["residency_state"] == "TX", (
            f"residency_state should read back unchanged, got {student['residency_state']!r}"
        )
        assert student["prior_enrollment"] == "PUBLIC_SCHOOL_FULL_YEAR", (
            f"prior_enrollment should read back unchanged, "
            f"got {student['prior_enrollment']!r}"
        )
        assert student["income_band"] == "BAND_B", (
            f"income_band should read back unchanged, got {student['income_band']!r}"
        )
        assert student["category_flags"] == ["DISABILITY_IEP", "PRIOR_PUBLIC_SCHOOL"], (
            "the submitted flag list should read back with its order preserved, got "
            f"{student['category_flags']!r}"
        )
        assert student["has_enrolled_sibling"] is False, (
            f"has_enrolled_sibling should read back as false, "
            f"got {student['has_enrolled_sibling']!r}"
        )

    def test_missing_required_field_is_a_malformed_request(self, api):
        """PRD §2.8: "Request shape: required fields present, enum values within their
        declared sets, integers non-negative where declared, ISO 8601 instants
        parseable, plain dates in `YYYY-MM-DD` form, `limit` within 1 through 100,
        `offset` at least 0 — `ERR_INVALID_REQUEST`."

        Design: Corner/entities/student_creation_missing_required_field_returns_invalid_request
        """
        payload = create_student_payload(income_band=None)
        assert "income_band" not in payload, "the payload must omit income_band entirely"

        response = api.create_student(payload, PA)
        validate_error(response, ApiErrorId.INVALID_REQUEST.value, 400)

    def test_enum_value_outside_its_declared_set_is_a_malformed_request(self, api):
        """PRD §3.2: "Prior schooling is captured in `prior_enrollment`, which is one of
        `PUBLIC_SCHOOL_FULL_YEAR`, `PUBLIC_SCHOOL_PARTIAL`, `PRIVATE_SCHOOL`,
        `HOMESCHOOL`, or `ENTERING_KINDERGARTEN`."

        Design: Corner/entities/student_invalid_enum_value_returns_invalid_request
        """
        response = api.create_student(
            create_student_payload(prior_enrollment="CHARTER_SCHOOL"), PA
        )
        validate_error(response, ApiErrorId.INVALID_REQUEST.value, 400)


class TestApplicationCreation:
    """Filing an application and the four gates that protect the creation itself."""

    def test_application_naming_a_nonexistent_student_reports_the_student(self, api):
        """PRD §2.8: "The student named by the path or by `student_id` exists —
        `ERR_STUDENT_NOT_FOUND`, on student reads and application creation."

        Design: Corner/entities/application_naming_a_nonexistent_student_returns_student_not_found
        """
        year = create_program_year()
        open_window(year["id"])
        set_clock("2026-09-01T00:00:00Z")

        response = api.create_application(
            create_application_payload(year["id"], MISSING_ID),
            make_guardian_headers(MISSING_ID),
        )
        validate_error(response, ApiErrorId.STUDENT_NOT_FOUND.value, 404)

        rows, meta = validate_paginated(api.list_applications(PA))
        assert meta["total_count"] == 0, (
            f"the refused filing must leave no application behind, got {meta['total_count']}"
        )
        assert rows == [], f"no application row should exist, got {rows!r}"

    def test_second_live_application_for_the_same_year_is_a_duplicate(self, api):
        """PRD §3.2: "The student must not already have a live application for the same
        `program_year_id`, where "live" means any status other than `WITHDRAWN`,
        `DENIED_FINAL`, or `EXPIRED`, or the request fails
        `ERR_DUPLICATE_APPLICATION`."

        Design: Corner/validations/duplicate_application_in_the_same_program_year_returns_conflict
        """
        env = setup_draft_application()

        response = api.create_application(
            create_application_payload(env.program_year_id, env.student_id), env.guardian
        )
        validate_error(response, ApiErrorId.DUPLICATE_APPLICATION.value, 409)

        _, meta = validate_paginated(
            api.list_applications(PA, params={"student_id": env.student_id})
        )
        assert meta["total_count"] == 1, (
            f"the duplicate must not be persisted, got {meta['total_count']} rows"
        )
        year = read_program_year(env.program_year_id)
        assert year["seats_available"] == 2, (
            "a refused filing consumes no seat, got seats_available "
            f"{year['seats_available']}"
        )

    def test_residency_state_mismatch_is_refused_as_unprocessable(self, api):
        """PRD §3.2: "And the student's `residency_state` must equal the programme
        year's `residency_state`, or the request fails `ERR_RESIDENCY_NOT_ELIGIBLE`."

        Design: Corner/validations/residency_state_mismatch_on_application_returns_unprocessable
        """
        year = create_program_year(residency_state="TX")
        open_window(year["id"])
        out_of_state = create_student(
            household_id="HH-9",
            first_name="Noa",
            last_name="Marquez",
            residency_state="NM",
        )
        set_clock("2026-09-01T00:00:00Z")

        response = api.create_application(
            create_application_payload(year["id"], out_of_state["id"]),
            make_guardian_headers(out_of_state["id"]),
        )
        validate_error(response, ApiErrorId.RESIDENCY_NOT_ELIGIBLE.value, 422)

        _, meta = validate_paginated(api.list_applications(PA))
        assert meta["total_count"] == 0, (
            f"the refused filing must leave no application behind, got {meta['total_count']}"
        )


class TestProvisionalAward:
    """The claimed variant the submission stamps."""

    def test_submission_computes_the_provisional_figure_from_the_claims(self, api):
        """PRD §3.2: "A newly created application sits in `DRAFT` with
        `appeal_round_count` at 0, both award figures at 0, and no verified attributes
        yet — `verified_income_band` is null until a determination is recorded, and
        `verified_category_flags` starts as the empty list."

        PRD §3.2: "The two orders genuinely differ: for `BAND_B` with the flags
        `DISABILITY_IEP` and `PRIOR_PUBLIC_SCHOOL`, rounding each component before
        summing yields 978382 cents, whereas summing the percentages first would yield
        978381."

        Design: Corner/entities/application_provisional_award_is_computed_not_client_supplied
        """
        env = setup_open_year_and_student()
        draft = create_application(
            env.program_year_id,
            env.student_id,
            claimed_income_band="BAND_B",
            claimed_category_flags=["DISABILITY_IEP", "PRIOR_PUBLIC_SCHOOL"],
        )

        assert draft["status"] == "DRAFT", (
            f"a newly created application sits in DRAFT, got {draft['status']!r}"
        )
        assert draft["provisional_award_cents"] == 0, (
            "both award figures start at 0 on a newly created application, got "
            f"{draft['provisional_award_cents']}"
        )
        assert draft["annual_award_cents"] == 0, (
            "both award figures start at 0 on a newly created application, got "
            f"{draft['annual_award_cents']}"
        )
        assert draft["appeal_round_count"] == 0, (
            f"appeal_round_count starts at 0, got {draft['appeal_round_count']}"
        )
        assert draft["verified_income_band"] is None, (
            "verified_income_band is null until a determination is recorded, got "
            f"{draft['verified_income_band']!r}"
        )
        assert draft["verified_category_flags"] == [], (
            f"verified_category_flags starts as the empty list, got "
            f"{draft['verified_category_flags']!r}"
        )

        submitted = validate_success(
            api.submit_application(draft["id"], env.guardian)
        )
        assert submitted["status"] == "SUBMITTED", (
            f"submission advances the application DRAFT to SUBMITTED, "
            f"got {submitted['status']!r}"
        )
        assert submitted["provisional_award_cents"] == AWARD_BAND_B_IEP_AND_PRIOR_PUBLIC, (
            "BAND_B with DISABILITY_IEP and PRIOR_PUBLIC_SCHOOL yields 978382 cents "
            f"when each component is rounded before summing, got "
            f"{submitted['provisional_award_cents']}"
        )
        assert isinstance(submitted["provisional_award_cents"], int), (
            "money is transported as a JSON integer, never as a string, got "
            f"{submitted['provisional_award_cents']!r}"
        )
        assert_instant_equals(
            submitted["submitted_at"],
            "2026-09-01T00:00:00Z",
            "application.submitted_at",
        )


class TestApplicationTransitions:
    """The window gate on submission and the invalid transitions around it."""

    def test_submission_after_the_window_closes_is_refused(self, api):
        """PRD §3.2: "and the governing year must be `WINDOW_OPEN` with the logical
        clock at or after `window_open_at` and strictly before `window_close_at`, or it
        is refused with `ERR_APPLICATION_WINDOW_CLOSED`."

        Design: Corner/state_machines/application_submit_after_window_close_returns_window_closed
        """
        env = setup_draft_application()
        set_clock("2026-10-01T00:00:00Z")

        response = api.submit_application(env.application_id, env.guardian)
        validate_error(response, ApiErrorId.APPLICATION_WINDOW_CLOSED.value, 409)

        application = read_application(env.application_id)
        assert application["status"] == "DRAFT", (
            f"the refused submission leaves the application in DRAFT, "
            f"got {application['status']!r}"
        )
        assert application["submitted_at"] is None, (
            "no logical instant is stamped by a refused submission, got "
            f"{application['submitted_at']!r}"
        )

    def test_resubmitting_a_submitted_application_does_not_restamp_it(self, api):
        """PRD §3.2: "Submitting the application advances it `DRAFT → SUBMITTED`. The
        application must currently be in `DRAFT`, or the attempt is refused with
        `ERR_INVALID_STATE_TRANSITION`"

        Design: Corner/state_machines/resubmitting_a_submitted_application_returns_invalid_state
        """
        env = setup_submitted_application(
            application_overrides={"claimed_category_flags": ["DISABILITY_IEP"]}
        )
        set_clock("2026-09-05T00:00:00Z")

        response = api.submit_application(env.application_id, env.guardian)
        validate_error(response, ApiErrorId.INVALID_STATE_TRANSITION.value, 409)

        application = read_application(env.application_id)
        assert application["status"] == "SUBMITTED", (
            f"the application stays in SUBMITTED, got {application['status']!r}"
        )
        assert_instant_equals(
            application["submitted_at"],
            "2026-09-01T00:00:00Z",
            "application.submitted_at not re-stamped by the refused resubmission",
        )
        assert application["provisional_award_cents"] == AWARD_BAND_B_IEP, (
            "BAND_B with DISABILITY_IEP alone yields 932663 cents and the rejected "
            f"call leaves it unchanged, got {application['provisional_award_cents']}"
        )

    def test_withdrawing_a_draft_application_is_refused_and_opens_no_account(self, api):
        """PRD §3.5: "Withdrawal is the mirror image and is likewise a `Guardian` action
        on an application in `ACCEPTED`; a wrong state is
        `ERR_INVALID_STATE_TRANSITION` and a mismatched `X-User-ID` against
        `student_id` is `ERR_NOT_ACCOUNT_HOLDER`."

        Design: Corner/state_machines/withdrawing_a_draft_application_returns_invalid_state
        """
        env = setup_draft_application()

        response = api.withdraw_application(env.application_id, env.guardian)
        validate_error(response, ApiErrorId.INVALID_STATE_TRANSITION.value, 409)

        assert read_application(env.application_id)["status"] == "DRAFT", (
            "the refused withdrawal leaves the application in DRAFT"
        )
        _, meta = validate_paginated(
            api.list_accounts(PA, params={"application_id": env.application_id})
        )
        assert meta["total_count"] == 0, (
            "acceptance is the only way an account ever comes into existence, so the "
            f"refused withdrawal must have touched none, got {meta['total_count']}"
        )
        year = read_program_year(env.program_year_id)
        assert year["seats_committed"] == 0 and year["seats_available"] == 2, (
            "no seat moves, got committed "
            f"{year['seats_committed']} / available {year['seats_available']}"
        )


class TestApplicationListing:
    """The canonical reverse lookup for the application's own foreign keys."""

    def test_listing_is_filtered_by_student_and_paginated(self, api):
        """PRD §2.3: "List responses carry `limit`, `offset`, `total_count` and
        `has_more` inside the `meta` object of the envelope, where `total_count` is the
        size of the whole filtered result set rather than of the returned page, and
        `has_more` states whether records remain beyond the current page."

        Design: Corner/entities/application_listing_is_filtered_and_paginated
        """
        env = setup_open_year_and_student()
        second = create_student(
            household_id="HH-2",
            first_name="Luis",
            last_name="Ortega",
            date_of_birth="2013-06-15",
            prior_enrollment="PRIVATE_SCHOOL",
            category_flags=[],
        )
        third = create_student(
            household_id="HH-3",
            first_name="Mara",
            last_name="Silva",
            date_of_birth="2012-11-08",
            prior_enrollment="HOMESCHOOL",
            category_flags=[],
        )
        create_application(env.program_year_id, env.student_id)
        a2 = create_application(
            env.program_year_id, second["id"], claimed_category_flags=[]
        )
        create_application(env.program_year_id, third["id"], claimed_category_flags=[])

        page, meta = validate_paginated(
            api.list_applications(PA, params={"limit": 2, "offset": 0})
        )
        assert len(page) == 2, f"limit=2 caps the page at two records, got {len(page)}"
        assert meta["total_count"] == 3, (
            "total_count is the size of the whole filtered result set, got "
            f"{meta['total_count']}"
        )
        assert meta["has_more"] is True, (
            "records remain beyond the first page of two, got has_more "
            f"{meta['has_more']!r}"
        )
        assert meta["limit"] == 2 and meta["offset"] == 0, (
            f"the page window is echoed in meta, got {meta!r}"
        )

        filtered, filtered_meta = validate_paginated(
            api.list_applications(PA, params={"student_id": second["id"]})
        )
        assert filtered_meta["total_count"] == 1, (
            "filtering by student_id narrows the set to one row, got "
            f"{filtered_meta['total_count']}"
        )
        assert filtered_meta["has_more"] is False, (
            f"nothing remains beyond that single row, got {filtered_meta['has_more']!r}"
        )
        assert [row["id"] for row in filtered] == [a2["id"]], (
            f"the filtered row is the second student's application, got {filtered!r}"
        )

    @pytest.mark.parametrize(
        "params",
        [
            {"limit": 101},
            {"offset": -1},
        ],
    )
    def test_pagination_arguments_outside_their_range_are_malformed(self, api, params):
        """PRD §2.3: "A `limit` outside the inclusive range 1 through 100, or a negative
        `offset`, is a malformed request and is rejected with `ERR_INVALID_REQUEST`."

        Design: Corner/errors/pagination_limit_above_the_maximum_returns_invalid_request
        """
        setup_draft_application()

        response = api.list_applications(PA, params=params)
        validate_error(response, ApiErrorId.INVALID_REQUEST.value, 400)

    def test_the_maximum_accepted_limit_of_one_hundred_is_admitted(self, api):
        """PRD §2.3: "`limit` caps the number of records in the response; when omitted
        it defaults to 10, its minimum accepted value is 1 and its maximum accepted
        value is 100."

        Design: Corner/errors/pagination_limit_above_the_maximum_returns_invalid_request
        """
        setup_draft_application()

        rows, meta = validate_paginated(api.list_applications(PA, params={"limit": 100}))
        assert meta["limit"] == 100, (
            f"100 is the maximum accepted value and is admitted, got {meta['limit']}"
        )
        assert meta["total_count"] == 1, (
            f"exactly one application exists, got {meta['total_count']}"
        )
        assert len(rows) == 1, f"the single row is returned, got {len(rows)}"


class TestEnrollmentTermOverlap:
    """A student's held enrolment term is a closed interval on both ends."""

    def _accepted_award_in_first_year(self):
        first = create_program_year(
            label="2026-27", term_start_date="2026-08-01", term_end_date="2027-06-30"
        )
        open_window(first["id"])
        student = create_student()
        set_clock("2026-09-01T00:00:00Z")
        application = create_application(first["id"], student["id"])
        submit_application(application["id"], student["id"])
        record_determination(application["id"])
        run_awarding(first["id"])
        accept = accept_award(application["id"], student["id"])
        return first, student, application, accept

    def test_next_year_term_starting_on_the_held_last_day_still_collides(self, api):
        """PRD §3.2: "The student must not already hold an offered, accepted, or
        completed application in a *different* programme year whose instructional term
        intersects the requested year's term — both terms are treated as fully inclusive
        date intervals, and applications for the same `program_year_id` are excluded
        from the comparison — or the request fails
        `ERR_OVERLAPPING_ENROLLMENT_PERIOD`."

        Design: Difficulty/resource_temporal_overlap/enrollment_terms_touching_on_one_day_collide_across_program_years
        """
        first, student, application, _ = self._accepted_award_in_first_year()
        assert read_application(application["id"])["status"] == "ACCEPTED", (
            "the held award must be ACCEPTED in the year whose term ends 2027-06-30"
        )

        overlapping = create_program_year(
            label="2027-28-overlap",
            total_seats=5,
            window_open_at="2027-01-01T00:00:00Z",
            window_close_at="2027-03-01T00:00:00Z",
            term_start_date="2027-06-30",
            term_end_date="2028-06-29",
        )
        open_window(overlapping["id"])
        set_clock("2027-02-01T00:00:00Z")

        response = api.create_application(
            create_application_payload(
                overlapping["id"], student["id"], claimed_category_flags=["DISABILITY_IEP"]
            ),
            make_guardian_headers(student["id"]),
        )
        validate_error(response, ApiErrorId.OVERLAPPING_ENROLLMENT_PERIOD.value, 409)

        _, meta = validate_paginated(
            api.list_applications(PA, params={"program_year_id": overlapping["id"]})
        )
        assert meta["total_count"] == 0, (
            "2027-06-30 lies inside the inclusive held term, so no row is created, "
            f"got {meta['total_count']}"
        )
        assert first["term_end_date"] == "2027-06-30", (
            "the held term's inclusive end date is the day the new term starts on"
        )

    def test_next_year_term_starting_one_day_later_is_admitted(self, api):
        """PRD §3.2: "The student must not already hold an offered, accepted, or
        completed application in a *different* programme year whose instructional term
        intersects the requested year's term — both terms are treated as fully inclusive
        date intervals, and applications for the same `program_year_id` are excluded
        from the comparison — or the request fails
        `ERR_OVERLAPPING_ENROLLMENT_PERIOD`."

        Design: Difficulty/resource_temporal_overlap/enrollment_terms_touching_on_one_day_collide_across_program_years
        """
        _, student, _, _ = self._accepted_award_in_first_year()

        overlapping = create_program_year(
            label="2027-28-overlap",
            total_seats=5,
            window_open_at="2027-01-01T00:00:00Z",
            window_close_at="2027-03-01T00:00:00Z",
            term_start_date="2027-06-30",
            term_end_date="2028-06-29",
        )
        open_window(overlapping["id"])
        clean = create_program_year(
            label="2027-28-clean",
            total_seats=5,
            window_open_at="2027-01-01T00:00:00Z",
            window_close_at="2027-03-01T00:00:00Z",
            term_start_date="2027-07-01",
            term_end_date="2028-06-30",
        )
        open_window(clean["id"])
        set_clock("2027-02-01T00:00:00Z")

        refused = api.create_application(
            create_application_payload(
                overlapping["id"], student["id"], claimed_category_flags=["DISABILITY_IEP"]
            ),
            make_guardian_headers(student["id"]),
        )
        validate_error(refused, ApiErrorId.OVERLAPPING_ENROLLMENT_PERIOD.value, 409)

        admitted = validate_success(
            api.create_application(
                create_application_payload(
                    clean["id"], student["id"], claimed_category_flags=["DISABILITY_IEP"]
                ),
                make_guardian_headers(student["id"]),
            ),
            expected_status=201,
        )
        assert admitted["status"] == "DRAFT", (
            "a term starting one day past the held term clears it, so the filing lands "
            f"in DRAFT, got {admitted['status']!r}"
        )
        assert admitted["program_year_id"] == clean["id"], (
            f"the admitted application belongs to the clean year, got {admitted!r}"
        )

        _, meta = validate_paginated(
            api.list_applications(PA, params={"student_id": student["id"]})
        )
        assert meta["total_count"] == 2, (
            "exactly two applications exist for the student, since no row was created "
            f"for the colliding year, got {meta['total_count']}"
        )
