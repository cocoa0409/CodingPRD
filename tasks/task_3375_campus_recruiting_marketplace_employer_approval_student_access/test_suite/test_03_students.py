"""Student roster provisioning, field round-trip, defaults, and listing."""
from test_helpers import (
    ApiErrorId,
    NON_EXISTENT_UUID,
    assert_student,
    create_active_university,
    create_student,
    create_student_payload,
    make_career_center_admin_headers,
    make_student_headers,
    set_clock,
    validate_error,
    validate_paginated,
    validate_success,
)


class TestStudentFieldRoundTrip:
    def test_get_round_trips_all_stored_fields(self, api):
        """PRD §3.1: "The administrator creates a student with `university_id`, `email`,
        `full_name`, `major`, `graduation_year`, `work_authorization`, and optionally
        `profile_visibility`."
        PRD §3.1: "A new student starts with `status` `ENROLLED` and `outcome_status`
        `UNREPORTED`, and the university's `enrolled_student_count` rises by 1."
        PRD §3.1: "the first write that leaves `UNREPORTED` stamps `outcome_recorded_at`
        from the logical clock, later writes leave that stamp untouched"

        Design: Corner/entities/student_get_round_trips_all_stored_fields
        """
        set_clock()
        university = create_active_university(
            name="State University", primary_domain="stateu.edu",
            employer_daily_message_cap=10,
        )
        created = create_student(
            university["id"],
            email="sam@stateu.edu", full_name="Sam Lee", major="CS",
            graduation_year=2027, work_authorization="US_CITIZEN",
            profile_visibility="PUBLIC_TO_APPROVED_EMPLOYERS",
        )
        read = validate_success(
            api.get_student(
                created["id"], make_career_center_admin_headers(university["id"])
            ),
            200,
        )
        assert_student(read)
        assert read["email"] == "sam@stateu.edu"
        assert read["full_name"] == "Sam Lee"
        assert read["major"] == "CS"
        assert read["graduation_year"] == 2027
        assert read["work_authorization"] == "US_CITIZEN"
        assert read["profile_visibility"] == "PUBLIC_TO_APPROVED_EMPLOYERS"
        assert read["status"] == "ENROLLED"
        assert read["outcome_status"] == "UNREPORTED"
        assert read["outcome_recorded_at"] is None
        assert read["university_id"] == university["id"]


class TestStudentListing:
    def test_list_paginates_with_total_count_and_has_more(self, api):
        """PRD §2.3: "The `limit` parameter sets the maximum number of items returned:
        it defaults to 10 when omitted, accepts a minimum of 1, and is capped at a
        maximum of 100. The `offset` parameter sets how many items to skip and defaults
        to 0."
        PRD §2.3: "List responses carry the pagination fields `limit`, `offset`,
        `total_count`, and `has_more` inside the `meta` object of the response envelope."
        PRD §3.1: "The list accepts the filters `university_id`, `major`,
        `graduation_year`, `status`, and `visible_for_employer_id`, plus `limit` and
        `offset`."

        Design: Corner/entities/students_list_paginates_with_total_count_and_has_more
        """
        set_clock()
        university = create_active_university(
            name="State University", primary_domain="stateu.edu",
            employer_daily_message_cap=10,
        )
        headers = make_career_center_admin_headers(university["id"])
        create_student(university["id"], email="sam@stateu.edu", full_name="Sam Lee",
                       major="CS", graduation_year=2027, work_authorization="US_CITIZEN")
        create_student(university["id"], email="sally@stateu.edu", full_name="Sally Kim",
                       major="CS", graduation_year=2027, work_authorization="US_CITIZEN")
        create_student(university["id"], email="wei@stateu.edu", full_name="Wei Chen",
                       major="EE", graduation_year=2028, work_authorization="VISA_OPT_CPT")

        page1, meta1 = validate_paginated(
            api.list_students(headers, params={"university_id": university["id"],
                                               "limit": 2, "offset": 0})
        )
        assert len(page1) == 2
        assert meta1["total_count"] == 3
        assert meta1["has_more"] is True

        page2, meta2 = validate_paginated(
            api.list_students(headers, params={"university_id": university["id"],
                                               "limit": 2, "offset": 2})
        )
        assert len(page2) == 1
        assert meta2["total_count"] == 3
        assert meta2["has_more"] is False

        all_rows, meta3 = validate_paginated(
            api.list_students(headers, params={"university_id": university["id"]})
        )
        assert len(all_rows) == 3, "default limit 10 / offset 0 must return all 3 rows"

        ee_rows, meta4 = validate_paginated(
            api.list_students(headers, params={"university_id": university["id"],
                                               "major": "EE"})
        )
        assert len(ee_rows) == 1
        assert ee_rows[0]["email"] == "wei@stateu.edu"


class TestStudentProvisioningDefaults:
    def test_profile_visibility_defaults_to_university_only(self, api):
        """PRD §3.1: "`profile_visibility` is one of `PUBLIC_TO_APPROVED_EMPLOYERS`,
        `UNIVERSITY_ONLY`, or `HIDDEN`, defaulting to `UNIVERSITY_ONLY` when omitted."

        Design: Corner/entities/student_create_defaults_profile_visibility_to_university_only
        """
        set_clock()
        university = create_active_university(
            name="State University", primary_domain="stateu.edu",
            employer_daily_message_cap=10,
        )
        response = api.create_student(
            create_student_payload(
                university["id"], email="pat@stateu.edu", full_name="Pat Ng",
                major="BIO", graduation_year=2028,
                work_authorization="SPONSORSHIP_REQUIRED",
            ),
            make_career_center_admin_headers(university["id"]),
        )
        student = validate_success(response, 201)
        assert student["profile_visibility"] == "UNIVERSITY_ONLY"
        read = validate_success(
            api.get_student(student["id"], make_student_headers(student["id"])), 200
        )
        assert read["profile_visibility"] == "UNIVERSITY_ONLY"

    def test_invalid_work_authorization_enum_rejected(self, api):
        """PRD §3.1: "`work_authorization` is one of `US_CITIZEN`, `PERMANENT_RESIDENT`,
        `VISA_OPT_CPT`, or `SPONSORSHIP_REQUIRED`"
        PRD §2.9: "Malformed-body residual: a missing required field, a wrong-typed
        value, an out-of-enum member, a `min_graduation_year` greater than
        `max_graduation_year`, a `capacity` below 1, an in-person session without a
        room, or a virtual session carrying one — otherwise `ERR_INVALID_REQUEST`
        (400)."

        Design: Corner/entities/student_create_with_invalid_enum_work_authorization_returns_invalid_request
        """
        set_clock()
        university = create_active_university(
            name="State University", primary_domain="stateu.edu",
            employer_daily_message_cap=10,
        )
        headers = make_career_center_admin_headers(university["id"])
        response = api.create_student(
            create_student_payload(
                university["id"], email="kim@stateu.edu", full_name="Kim Lee",
                major="CS", graduation_year=2027, work_authorization="CITIZEN",
            ),
            headers,
        )
        validate_error(response, ApiErrorId.ERR_INVALID_REQUEST, 400)
        rows, _meta = validate_paginated(
            api.list_students(headers, params={"university_id": university["id"]})
        )
        assert len(rows) == 0, "the rejected provisioning must not persist a row"

    def test_unknown_university_returns_university_not_found(self, api):
        """PRD §2.7: "After path identifiers, foreign keys in the request body are
        validated in the endpoint's declared input order"
        PRD §2.7: "Each resource type has its own not-found error:
        `ERR_UNIVERSITY_NOT_FOUND`, `ERR_STUDENT_NOT_FOUND`, `ERR_EMPLOYER_NOT_FOUND`,
        `ERR_EMPLOYER_APPROVAL_NOT_FOUND`, `ERR_JOB_POSTING_NOT_FOUND`,
        `ERR_CAREER_EVENT_NOT_FOUND`, `ERR_EVENT_SESSION_NOT_FOUND`,
        `ERR_EVENT_SIGNUP_NOT_FOUND`, `ERR_APPLICATION_NOT_FOUND`, and
        `ERR_OUTREACH_MESSAGE_NOT_FOUND` — all HTTP 404."

        Design: Corner/entities/student_create_with_unknown_university_returns_university_not_found
        """
        set_clock()
        # Caller identity equals the (unknown) body university_id, so the ownership
        # comparison passes trivially and existence answers the 404.
        response = api.create_student(
            create_student_payload(
                NON_EXISTENT_UUID, email="ghost@stateu.edu", full_name="Ghost",
                major="CS", graduation_year=2027, work_authorization="US_CITIZEN",
            ),
            make_career_center_admin_headers(NON_EXISTENT_UUID),
        )
        validate_error(response, ApiErrorId.ERR_UNIVERSITY_NOT_FOUND, 404)
