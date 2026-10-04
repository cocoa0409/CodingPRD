"""Applications: gate chain ordering, eligibility, deadlines, interviews, and
the active_application_count conserved quantity."""
from test_helpers import (
    ApiErrorId,
    apply_as_student,
    create_active_university,
    create_application_payload,
    create_approved_employer,
    create_document,
    create_interview_payload,
    create_published_posting,
    create_student,
    decide_approval,
    make_employer_recruiter_headers,
    make_student_headers,
    request_approval,
    schedule_interview,
    set_clock,
    setup_base_marketplace,
    setup_interviewing_application,
    transition_posting,
    validate_error,
    validate_paginated,
    validate_success,
)
from test_helpers.fixtures import PA


def _setup_employer_without_approval(api, pause_posting):
    """University ACTIVE with Sam ENROLLED; employer Globex APPROVED (ELEVATED)
    with NO EmployerApproval row at the university; Globex posting PUBLISHED,
    optionally then PAUSED."""
    set_clock()
    university = create_active_university(
        name="State University", primary_domain="stateu.edu",
        employer_daily_message_cap=10,
    )
    student = create_student(
        university["id"], email="sam@stateu.edu", full_name="Sam Lee",
        major="CS", graduation_year=2027, work_authorization="US_CITIZEN",
        profile_visibility="PUBLIC_TO_APPROVED_EMPLOYERS",
    )
    employer = create_approved_employer(
        analyst_signal_adjustment=1,
        company_name="Globex", website_domain="globex.com",
        contact_email="jobs@gmail.com",
    )
    posting = create_published_posting(
        employer["id"], title="Globex Intern", position_type="INTERNSHIP",
        required_majors=["CS"], min_graduation_year=2026, max_graduation_year=2028,
        required_documents=["RESUME"], application_deadline="2026-12-01T00:00:00Z",
    )
    if pause_posting:
        transition_posting(
            posting["id"], "PAUSED", make_employer_recruiter_headers(employer["id"])
        )
    return {"university": university, "student": student,
            "employer": employer, "posting": posting}


def _apply_raw(api, student_id, posting_id, file_uri="s3://docs/sam-resume.pdf"):
    return api.create_application(
        {
            "student_id": student_id,
            "job_posting_id": posting_id,
            "submitted_documents": [create_document("RESUME", file_uri)],
        },
        make_student_headers(student_id),
    )


class TestStateErrorBeatsSafetyError:
    def test_paused_posting_and_missing_approval_yields_state_error(self, api):
        """PRD §2.9: "When a request would fail more than one check, the first failure
        in the following fixed order wins; later checks are not evaluated once an
        earlier one has failed:"
        PRD §3.7: "the posting's stored status must be `PUBLISHED` — a posting in
        `DRAFT`, `SUBMITTED`, or `PAUSED` fails with `ERR_POSTING_NOT_PUBLISHED`
        (HTTP 409)."

        Design: Difficulty/priority_pair_validation_conflict/application_state_error_beats_safety_error
        """
        ctx = _setup_employer_without_approval(api, pause_posting=True)
        response = _apply_raw(api, ctx["student"]["id"], ctx["posting"]["id"])
        error = validate_error(response, ApiErrorId.ERR_POSTING_NOT_PUBLISHED, 409)
        # The safety violation (no approval row exists) is equally true, yet the
        # earlier state gate is the one reported.
        assert error["error_id"] != "ERR_EMPLOYER_NOT_APPROVED_FOR_UNIVERSITY"
        rows, _meta = validate_paginated(
            api.list_applications(PA, params={"job_posting_id": ctx["posting"]["id"]})
        )
        assert len(rows) == 0

    def test_missing_approval_alone_yields_safety_error(self, api):
        """PRD §3.7: "The safety gates follow: an `APPROVED` employer approval must
        exist for the pairing of the posting's employer and the student's university,
        otherwise `ERR_EMPLOYER_NOT_APPROVED_FOR_UNIVERSITY` (HTTP 403)"

        Design: Difficulty/priority_pair_validation_conflict/application_state_error_beats_safety_error
        """
        ctx = _setup_employer_without_approval(api, pause_posting=False)
        response = _apply_raw(api, ctx["student"]["id"], ctx["posting"]["id"])
        validate_error(response, ApiErrorId.ERR_EMPLOYER_NOT_APPROVED_FOR_UNIVERSITY, 403)


class TestDeadlineBoundary:
    def test_apply_at_exact_deadline_succeeds(self, api):
        """PRD §2.10: "The comparison is strict and the deadline is inclusive: at the
        exact instant the clock equals the deadline, the posting still reports
        `PUBLISHED` and still accepts applications."

        Design: Difficulty/boundary_precision_check/application_deadline_inclusive_boundary
        """
        ctx = setup_base_marketplace(
            posting_overrides={"application_deadline": "2026-10-01T12:00:00Z"}
        )
        set_clock("2026-10-01T12:00:00Z")
        application = apply_as_student(
            ctx["student"]["id"], ctx["posting"]["id"],
            submitted_documents=[create_document("RESUME", "s3://docs/sam-resume.pdf")],
        )
        assert application["status"] == "SUBMITTED", (
            "an apply at exactly the inclusive deadline must be accepted"
        )

    def test_apply_one_second_after_deadline_fails_and_projects_expired(self, api):
        """PRD §2.10: "An apply attempt against a projected-`EXPIRED` posting is
        rejected as a temporal violation with `ERR_APPLICATION_DEADLINE_PASSED`, never
        as a state-machine error."
        PRD §2.10: "A posting whose stored status is `PUBLISHED` is reported as
        `EXPIRED` on every read — single read or list — once the logical clock has
        moved strictly past its `application_deadline`."

        Design: Difficulty/boundary_precision_check/application_deadline_inclusive_boundary
        """
        ctx = setup_base_marketplace(
            posting_overrides={"application_deadline": "2026-10-01T12:00:00Z"}
        )
        sally = create_student(
            ctx["university"]["id"], email="sally@stateu.edu", full_name="Sally Kim",
            major="CS", graduation_year=2027, work_authorization="US_CITIZEN",
            profile_visibility="PUBLIC_TO_APPROVED_EMPLOYERS",
        )
        set_clock("2026-10-01T12:00:01Z")
        response = _apply_raw(api, sally["id"], ctx["posting"]["id"],
                              file_uri="s3://docs/sally-resume.pdf")
        error = validate_error(response, ApiErrorId.ERR_APPLICATION_DEADLINE_PASSED, 409)
        assert error["error_id"] != "ERR_POSTING_NOT_PUBLISHED"
        projected = validate_success(api.get_job_posting(ctx["posting"]["id"], PA), 200)
        assert projected["status"] == "EXPIRED"


class TestUniversityLevelApprovalGate:
    def test_apply_rejected_while_approval_pending(self, api):
        """PRD §3.7: "an `APPROVED` employer approval must exist for the pairing of the
        posting's employer and the student's university, otherwise
        `ERR_EMPLOYER_NOT_APPROVED_FOR_UNIVERSITY` (HTTP 403)"

        Design: Difficulty/cross_entity_state_dependency/application_requires_university_level_approval
        """
        set_clock()
        university = create_active_university(
            name="State University", primary_domain="stateu.edu",
            employer_daily_message_cap=10,
        )
        student = create_student(
            university["id"], email="sam@stateu.edu", full_name="Sam Lee",
            major="CS", graduation_year=2027, work_authorization="US_CITIZEN",
            profile_visibility="PUBLIC_TO_APPROVED_EMPLOYERS",
        )
        employer = create_approved_employer(
            company_name="Acme Corp", website_domain="acme.com",
            contact_email="hr@acme.com",
        )
        # The approval row exists but is never decided: it stays PENDING.
        request_approval(employer["id"], university["id"])
        posting = create_published_posting(
            employer["id"], title="SWE Intern", position_type="INTERNSHIP",
            required_majors=["CS"], min_graduation_year=2026, max_graduation_year=2028,
            accepted_work_authorizations=["US_CITIZEN", "PERMANENT_RESIDENT"],
            required_documents=["RESUME"], application_deadline="2026-12-01T00:00:00Z",
        )
        response = _apply_raw(api, student["id"], posting["id"])
        validate_error(response, ApiErrorId.ERR_EMPLOYER_NOT_APPROVED_FOR_UNIVERSITY, 403)

    def test_apply_succeeds_after_approval_approved(self, api):
        """PRD §3.7: "an `APPROVED` employer approval must exist for the pairing of the
        posting's employer and the student's university, otherwise
        `ERR_EMPLOYER_NOT_APPROVED_FOR_UNIVERSITY` (HTTP 403)"
        PRD §3.7: "A created application lands in `SUBMITTED` with `submitted_at`
        stamped from the logical clock, and the posting's `active_application_count`
        rises by 1."

        Design: Difficulty/cross_entity_state_dependency/application_requires_university_level_approval
        """
        set_clock()
        university = create_active_university(
            name="State University", primary_domain="stateu.edu",
            employer_daily_message_cap=10,
        )
        student = create_student(
            university["id"], email="sam@stateu.edu", full_name="Sam Lee",
            major="CS", graduation_year=2027, work_authorization="US_CITIZEN",
            profile_visibility="PUBLIC_TO_APPROVED_EMPLOYERS",
        )
        employer = create_approved_employer(
            company_name="Acme Corp", website_domain="acme.com",
            contact_email="hr@acme.com",
        )
        approval = request_approval(employer["id"], university["id"])
        posting = create_published_posting(
            employer["id"], title="SWE Intern", position_type="INTERNSHIP",
            required_majors=["CS"], min_graduation_year=2026, max_graduation_year=2028,
            accepted_work_authorizations=["US_CITIZEN", "PERMANENT_RESIDENT"],
            required_documents=["RESUME"], application_deadline="2026-12-01T00:00:00Z",
        )
        # Flipping the OTHER entity's row to APPROVED changes nothing about the
        # posting or the student, yet the identical request now succeeds.
        decide_approval(approval["id"], university["id"], "APPROVE",
                        employer_id=employer["id"])
        application = apply_as_student(
            student["id"], posting["id"],
            submitted_documents=[create_document("RESUME", "s3://docs/sam-resume.pdf")],
        )
        assert application["status"] == "SUBMITTED"
        posting_read = validate_success(api.get_job_posting(posting["id"], PA), 200)
        assert posting_read["active_application_count"] == 1


class TestInterviewBuffer:
    def test_exactly_fifteen_minute_gap_and_other_interviewer_pass(self, api):
        """PRD §3.7: "Unlike the room rule, exact adjacency is still a conflict: a gap
        of strictly less than fifteen minutes fails, while a gap of exactly fifteen
        minutes passes."
        PRD §3.7: "Conflict detection runs per interviewer across the whole
        marketplace — every `SCHEDULED` interview bearing the same `interviewer_email`,
        on any application of any employer, participates"

        Design: Difficulty/resource_temporal_overlap/interview_buffer_fifteen_minute_gap_semantics
        """
        ctx = setup_base_marketplace()
        application, _first = setup_interviewing_application(ctx)
        recruiter = make_employer_recruiter_headers(ctx["employer"]["id"])
        # Exactly a fifteen-minute gap after the 10:00-11:00 interview: passes.
        resp_i2 = api.create_interview(
            application["id"],
            create_interview_payload(
                interviewer_email="int@acme.com",
                starts_at="2026-10-05T11:15:00Z", ends_at="2026-10-05T12:00:00Z",
            ),
            recruiter,
        )
        interview2 = validate_success(resp_i2, 201)
        assert interview2["status"] == "SCHEDULED"
        # The buffer is scoped per interviewer_email: a different interviewer's
        # overlapping slot does not conflict.
        resp_i3 = api.create_interview(
            application["id"],
            create_interview_payload(
                interviewer_email="other@acme.com",
                starts_at="2026-10-05T10:30:00Z", ends_at="2026-10-05T11:30:00Z",
            ),
            recruiter,
        )
        interview3 = validate_success(resp_i3, 201)
        assert interview3["interviewer_email"] == "other@acme.com"

    def test_ten_minute_gap_conflicts(self, api):
        """PRD §3.7: "the new interview conflicts when its `starts_at` is strictly
        before an existing interview's `ends_at` plus fifteen minutes, and that
        existing interview's `starts_at` is strictly before the new interview's
        `ends_at` plus fifteen minutes."
        PRD §3.7: "A conflicting schedule is rejected with
        `ERR_INTERVIEW_SCHEDULE_CONFLICT` (HTTP 409)."

        Design: Difficulty/resource_temporal_overlap/interview_buffer_fifteen_minute_gap_semantics
        """
        ctx = setup_base_marketplace()
        application, _first = setup_interviewing_application(ctx)
        schedule_interview(
            application["id"], ctx["employer"]["id"],
            interviewer_email="int@acme.com",
            starts_at="2026-10-05T11:15:00Z", ends_at="2026-10-05T12:00:00Z",
        )
        schedule_interview(
            application["id"], ctx["employer"]["id"],
            interviewer_email="other@acme.com",
            starts_at="2026-10-05T10:30:00Z", ends_at="2026-10-05T11:30:00Z",
        )
        # 11:10 is strictly before 11:00 + 15 minutes: a ten-minute gap fails.
        response = api.create_interview(
            application["id"],
            create_interview_payload(
                interviewer_email="int@acme.com",
                starts_at="2026-10-05T11:10:00Z", ends_at="2026-10-05T12:30:00Z",
            ),
            make_employer_recruiter_headers(ctx["employer"]["id"]),
        )
        validate_error(response, ApiErrorId.ERR_INTERVIEW_SCHEDULE_CONFLICT, 409)
        interviews = validate_success(
            api.list_interviews(application["id"], PA), 200
        )
        assert len(interviews) == 3
        assert all(i["status"] == "SCHEDULED" for i in interviews)


class TestActiveApplicationCountConservation:
    def test_submit_increments_active_count_per_create(self, api):
        """PRD §3.4: "It is recomputed on every application creation and on every
        application terminal transition"
        PRD §3.7: "A created application lands in `SUBMITTED` with `submitted_at`
        stamped from the logical clock, and the posting's `active_application_count`
        rises by 1."

        Design: Difficulty/compensating_invariant/application_submit_withdraw_conserves_active_count
        """
        ctx = setup_base_marketplace()
        posting_id = ctx["posting"]["id"]
        initial = validate_success(api.get_job_posting(posting_id, PA), 200)
        assert initial["active_application_count"] == 0
        apply_as_student(
            ctx["student"]["id"], posting_id,
            submitted_documents=[create_document("RESUME", "s3://docs/sam-resume.pdf")],
        )
        after_one = validate_success(api.get_job_posting(posting_id, PA), 200)
        assert after_one["active_application_count"] == 1
        sally = create_student(
            ctx["university"]["id"], email="sally@stateu.edu", full_name="Sally Kim",
            major="CS", graduation_year=2027, work_authorization="US_CITIZEN",
            profile_visibility="PUBLIC_TO_APPROVED_EMPLOYERS",
        )
        apply_as_student(
            sally["id"], posting_id,
            submitted_documents=[create_document("RESUME", "s3://docs/sally-resume.pdf")],
        )
        after_two = validate_success(api.get_job_posting(posting_id, PA), 200)
        assert after_two["active_application_count"] == 2

    def test_withdraw_returns_count_to_prior_value(self, api):
        """PRD §3.4: "the bookkeeping is compensating: an application creation followed
        by that same application's withdrawal returns the count to exactly its prior
        value."
        PRD §3.4: "The `active_application_count` itself is a conserved quantity over
        the four active statuses — `SUBMITTED`, `UNDER_REVIEW`, `INTERVIEWING`, and
        `OFFER_EXTENDED`."

        Design: Difficulty/compensating_invariant/application_submit_withdraw_conserves_active_count
        """
        ctx = setup_base_marketplace()
        posting_id = ctx["posting"]["id"]
        app1 = apply_as_student(
            ctx["student"]["id"], posting_id,
            submitted_documents=[create_document("RESUME", "s3://docs/sam-resume.pdf")],
        )
        sally = create_student(
            ctx["university"]["id"], email="sally@stateu.edu", full_name="Sally Kim",
            major="CS", graduation_year=2027, work_authorization="US_CITIZEN",
            profile_visibility="PUBLIC_TO_APPROVED_EMPLOYERS",
        )
        app2 = apply_as_student(
            sally["id"], posting_id,
            submitted_documents=[create_document("RESUME", "s3://docs/sally-resume.pdf")],
        )
        withdrawn = validate_success(
            api.transition_application(
                app1["id"], {"to": "WITHDRAWN"},
                make_student_headers(ctx["student"]["id"]),
            ),
            200,
        )
        assert withdrawn["status"] == "WITHDRAWN"
        posting = validate_success(api.get_job_posting(posting_id, PA), 200)
        assert posting["active_application_count"] == 1, (
            "submit + withdraw on the same application must net zero"
        )
        rows, _meta = validate_paginated(
            api.list_applications(PA, params={"job_posting_id": posting_id})
        )
        assert len(rows) == 2
        active = [r for r in rows if r["status"] in (
            "SUBMITTED", "UNDER_REVIEW", "INTERVIEWING", "OFFER_EXTENDED"
        )]
        assert len(active) == 1
        assert active[0]["id"] == app2["id"]


class TestApplicationPipeline:
    def test_cannot_jump_submitted_to_offer_extended(self, api):
        """PRD §3.7: "`SUBMITTED` to `UNDER_REVIEW`, `UNDER_REVIEW` to `INTERVIEWING`,
        and `INTERVIEWING` to `OFFER_EXTENDED`, strictly in sequence — a jump that
        skips a stage, such as `SUBMITTED` directly to `OFFER_EXTENDED`, is rejected
        with `ERR_INVALID_APPLICATION_TRANSITION` (HTTP 409)."

        Design: Corner/state_machines/application_cannot_jump_submitted_to_offer
        """
        ctx = setup_base_marketplace()
        application = apply_as_student(
            ctx["student"]["id"], ctx["posting"]["id"],
            submitted_documents=[create_document("RESUME", "s3://docs/sam-resume.pdf")],
        )
        response = api.transition_application(
            application["id"], {"to": "OFFER_EXTENDED"},
            make_employer_recruiter_headers(ctx["employer"]["id"]),
        )
        validate_error(response, ApiErrorId.ERR_INVALID_APPLICATION_TRANSITION, 409)
        read = validate_success(api.get_application(application["id"], PA), 200)
        assert read["status"] == "SUBMITTED"


class TestApplicationExistenceOrder:
    def test_body_foreign_keys_checked_in_declared_input_order(self, api):
        """PRD §2.7: "After path identifiers, foreign keys in the request body are
        validated in the endpoint's declared input order — for example, on application
        creation `student_id` is resolved before `job_posting_id`, so a request in
        which both are bad surfaces `ERR_STUDENT_NOT_FOUND`"

        Design: Corner/validations/application_body_fks_checked_in_declared_input_order
        """
        set_clock()
        university = create_active_university(
            name="State University", primary_domain="stateu.edu",
            employer_daily_message_cap=10,
        )
        student = create_student(
            university["id"], email="sam@stateu.edu", full_name="Sam Lee",
            major="CS", graduation_year=2027, work_authorization="US_CITIZEN",
        )
        unknown_student = "00000000-0000-4000-8000-000000000001"
        unknown_posting = "00000000-0000-4000-8000-000000000002"
        # Both foreign keys unknown: student_id is declared first, so it answers.
        response = api.create_application(
            create_application_payload(unknown_student, unknown_posting,
                                       submitted_documents=[]),
            make_student_headers(unknown_student),
        )
        validate_error(response, ApiErrorId.ERR_STUDENT_NOT_FOUND, 404)
        # Only job_posting_id unknown: the student resolves, the posting answers.
        response = api.create_application(
            create_application_payload(student["id"], unknown_posting,
                                       submitted_documents=[]),
            make_student_headers(student["id"]),
        )
        validate_error(response, ApiErrorId.ERR_JOB_POSTING_NOT_FOUND, 404)
        rows, _meta = validate_paginated(
            api.list_applications(PA, params={"student_id": student["id"]})
        )
        assert len(rows) == 0


class TestDuplicateApplication:
    def test_duplicate_active_application_rejected(self, api):
        """PRD §3.7: "The duplicate check: no existing application for the same
        student-posting pair may sit in any of the four active statuses, else
        `ERR_DUPLICATE_APPLICATION` (HTTP 409)."

        Design: Corner/validations/duplicate_active_application_rejected
        """
        ctx = setup_base_marketplace()
        apply_as_student(
            ctx["student"]["id"], ctx["posting"]["id"],
            submitted_documents=[create_document("RESUME", "s3://docs/sam-resume.pdf")],
        )
        response = _apply_raw(api, ctx["student"]["id"], ctx["posting"]["id"],
                              file_uri="s3://docs/sam-resume-2.pdf")
        validate_error(response, ApiErrorId.ERR_DUPLICATE_APPLICATION, 409)
        posting = validate_success(api.get_job_posting(ctx["posting"]["id"], PA), 200)
        assert posting["active_application_count"] == 1


class TestGraduationYearBounds:
    def test_graduation_year_bounds_are_inclusive(self, api):
        """PRD §3.7: "The graduation-year check: the student's `graduation_year` is at
        least `min_graduation_year` and at most `max_graduation_year`, both bounds
        inclusive, else `ERR_GRAD_YEAR_NOT_ELIGIBLE` (HTTP 422)."
        PRD §3.4: "`required_majors` (an array defaulting to empty, where empty means
        every major is eligible and a non-empty list requires the student's `major` to
        be a member)"

        Design: Corner/calculations/eligibility_graduation_year_bounds_inclusive
        """
        set_clock()
        university = create_active_university(
            name="State University", primary_domain="stateu.edu",
            employer_daily_message_cap=10,
        )
        employer = create_approved_employer(
            company_name="Acme Corp", website_domain="acme.com",
            contact_email="hr@acme.com",
        )
        approval = request_approval(employer["id"], university["id"])
        decide_approval(approval["id"], university["id"], "APPROVE",
                        employer_id=employer["id"])
        # Unrestricted posting: empty majors/authorizations/documents, [2026, 2028].
        posting = create_published_posting(
            employer["id"], title="Open Role", position_type="FULL_TIME",
            min_graduation_year=2026, max_graduation_year=2028,
            application_deadline="2026-12-01T00:00:00Z",
        )
        students = {}
        for year in (2025, 2026, 2028, 2029):
            students[year] = create_student(
                university["id"], email=f"y{year}@stateu.edu", full_name=f"Y{year}",
                major="CS", graduation_year=year, work_authorization="US_CITIZEN",
            )
        for year in (2026, 2028):
            application = apply_as_student(
                students[year]["id"], posting["id"], submitted_documents=[]
            )
            assert application["status"] == "SUBMITTED", (
                f"boundary year {year} is inside the inclusive [2026, 2028] range"
            )
        for year in (2025, 2029):
            response = api.create_application(
                create_application_payload(students[year]["id"], posting["id"],
                                           submitted_documents=[]),
                make_student_headers(students[year]["id"]),
            )
            validate_error(response, ApiErrorId.ERR_GRAD_YEAR_NOT_ELIGIBLE, 422)
        posting_read = validate_success(api.get_job_posting(posting["id"], PA), 200)
        assert posting_read["active_application_count"] == 2
