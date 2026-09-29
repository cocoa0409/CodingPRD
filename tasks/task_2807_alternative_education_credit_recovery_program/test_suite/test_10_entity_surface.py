"""The entity surface itself: what a create returns, what a read recomputes,
what a listing filters, and which body values the server refuses to take."""

from test_helpers import (
    NON_EXISTENT_UUID,
    ApiErrorId,
    CohortFlag,
    GradeCode,
    IntakePosture,
    Modality,
    Pathway,
    PriorOutcome,
    ReplacementStatus,
    SubjectArea,
    DISTRICT_ADMIN_HEADERS,
    REGISTRAR_HEADERS,
    assert_center,
    assert_close,
    assert_common_fields,
    assert_course,
    assert_home_school,
    assert_prior_course_record,
    assert_seat_picture,
    factories as f,
    fixtures as fx,
    make_home_school_counselor_headers,
    validate_error,
    validate_paginated,
    validate_success,
)


class TestCreateAndReadReturnEveryDeclaredField:
    """A create echoes its inputs and already carries its derivations."""

    def test_a_new_home_school_reports_the_empty_cohort_answer(self, api):
        """The three inputs come back with cohort counts of 0, a null adjusted rate
        and a NOT_RATED flag.

        PRD: "A school with an empty cohort is a special case with its own answer
        — when the cohort size is zero, the adjusted rate is null and the flag reads
        `NOT_RATED`, which is exactly what a freshly registered school reports:
        counts of 0, 0 and 0, a null rate, and `NOT_RATED`."

        Design: Corner/entities/create_home_school_returns_all_declared_fields
        """
        school = validate_success(
            api.create_home_school(
                f.home_school_payload(
                    name="North High",
                    district_code="NHS-01",
                    accountability_cohort_year=2026,
                ),
                DISTRICT_ADMIN_HEADERS,
            ),
            201,
        )
        assert_home_school(school)
        assert_common_fields(school, expected_version=1)
        assert school["name"] == "North High"
        assert school["district_code"] == "NHS-01"
        assert school["accountability_cohort_year"] == 2026
        assert school["cohort_size"] == 0
        assert school["graduates_count"] == 0
        assert school["alt_ed_placed_count"] == 0
        assert school["adjusted_grad_rate"] is None
        assert school["cohort_flag"] == CohortFlag.NOT_RATED.value

    def test_reading_a_center_recomputes_its_seat_and_staffing_ledger(self, api):
        """Twenty funded seats against 2.00 FTE at twelve students per teacher read
        back as 20 available and a headroom of 24, and the read never bumps the
        version.

        PRD: "`staffing_headroom` is the certified teacher FTE multiplied by the
        contractual students-per-teacher cap, rounded down to a whole number, minus
        the active student count."

        Design: Corner/entities/get_center_returns_stored_and_derived_seat_fields
        """
        created = fx.open_center(
            api,
            name="Cedar AEC",
            seat_capacity=20,
            certified_teacher_fte=2.00,
            support_staff_fte=1.50,
            max_students_per_teacher=12,
        )

        center = validate_success(api.get_center(created["id"], DISTRICT_ADMIN_HEADERS))
        assert_center(center)
        assert center["seat_capacity"] == 20
        assert_close(center["certified_teacher_fte"], 2.00, "certified teacher fte")
        assert_close(center["support_staff_fte"], 1.50, "support staff fte")
        assert center["max_students_per_teacher"] == 12
        assert_seat_picture(center, 0, 0, 20, IntakePosture.OPEN.value)
        assert_close(center["student_teacher_ratio"], 0.00, "student teacher ratio")
        assert center["staffing_headroom"] == 24
        assert center["version"] == 1

    def test_the_catalog_listing_filters_and_orders_by_creation(self, api):
        """Two published courses list in creation order, a subject filter narrows
        the window to one row and a modality filter that matches nothing returns an
        empty window.

        PRD: "Unless a specific endpoint says otherwise, every list endpoint returns
        its rows sorted by `created_at` in ascending order."

        Design: Corner/entities/list_courses_returns_filtered_collection
        """
        math_course = fx.publish_course(
            api,
            code="ALG1",
            title="Algebra I",
            subject_area=SubjectArea.MATH.value,
            modality=Modality.PACKET.value,
        )
        ela_course = fx.publish_course(
            api,
            code="ENG1",
            title="English I",
            subject_area=SubjectArea.ELA.value,
            modality=Modality.PACKET.value,
        )

        rows, meta = validate_paginated(api.list_courses(DISTRICT_ADMIN_HEADERS))
        assert [row["id"] for row in rows] == [math_course["id"], ela_course["id"]]
        assert meta["total_count"] == 2
        for row in rows:
            assert_course(row)

        math_rows, _meta = validate_paginated(
            api.list_courses(
                DISTRICT_ADMIN_HEADERS, {"subject_area": SubjectArea.MATH.value}
            )
        )
        assert [row["id"] for row in math_rows] == [math_course["id"]]

        online_rows, _meta = validate_paginated(
            api.list_courses(DISTRICT_ADMIN_HEADERS, {"modality": Modality.ONLINE.value})
        )
        assert online_rows == []

    def test_a_created_course_carries_only_server_minted_system_fields(self, api):
        """The catalogue row opens at version 1 with `created_at` equal to
        `updated_at`, and the same row comes back on a read.

        PRD: "`version` (integer): a system-managed counter that starts at 1 on
        creation and increments by exactly 1 on every mutation of the row. No entity
        in this system omits `updated_at` or `version`."

        Design: Corner/entities/create_course_system_fields_generated_input_ignored
        """
        course = validate_success(
            api.create_course(
                f.online_course_payload(
                    code="BIO1",
                    title="Biology I",
                    subject_area=SubjectArea.SCIENCE.value,
                    credit_value=1.00,
                    total_modules=10,
                    required_seat_hours=60.00,
                    pacing_days=40,
                    proctored_exam_weight=0.40,
                    ncaa_approved=True,
                    min_passing_percent=60.00,
                ),
                DISTRICT_ADMIN_HEADERS,
            ),
            201,
        )
        assert_common_fields(course, expected_version=1)
        assert course["created_at"] == course["updated_at"]
        assert course["proctoring_required"] is True
        assert_close(course["proctored_exam_weight"], 0.40, "proctored exam weight")

        fetched = validate_success(
            api.get_course(course["id"], DISTRICT_ADMIN_HEADERS)
        )
        assert fetched["id"] == course["id"]
        assert fetched["version"] == 1

    def test_the_historical_rows_letter_grade_is_derived_not_supplied(self, api):
        """A 59.50 percent attempt lands below the 60 D floor and reads F, the row
        opens NOT_REPLACED, and the failed row counts in the GPA denominator alone.

        PRD: "From the original percent the system derives `original_grade_code` by
        letter bands: `A` at 90 or above, `B` at 80 or above, `C` at 70 or above,
        `D` at 60 or above, and `F` below 60 — except that a row whose outcome is
        `INCOMPLETE` carries the literal code `I` regardless of percent."

        Design: Corner/entities/prior_record_grade_code_computed_client_value_ignored
        """
        school = fx.open_home_school(api)
        course = fx.publish_course(api, code="ALG1", title="Algebra I")
        student = fx.register_student(api, school["id"])

        record = validate_success(
            api.create_prior_course_record(
                f.prior_course_record_payload(
                    student["id"],
                    course["id"],
                    term_code="2025-S1",
                    original_percent=59.50,
                    credits_attempted=1.00,
                    outcome=PriorOutcome.FAILED.value,
                ),
                REGISTRAR_HEADERS,
            ),
            201,
        )
        assert_prior_course_record(record)
        assert record["original_grade_code"] == GradeCode.F.value
        assert record["replacement_status"] == ReplacementStatus.NOT_REPLACED.value

        owner = fx.read_student(api, student["id"])
        assert_close(owner["credits_earned_total"], 0.00, "credits earned total")
        assert_close(owner["gpa"], 0.00, "gpa from a single F row")


class TestTheServerRefusesMalformedAndDanglingBodies:
    """Rung 5 shape checks and rung 6 body-identifier resolution."""

    def test_a_center_without_its_funded_seat_capacity_is_refused(self, api):
        """Staffing alone does not imply a seat count, so the create is refused with
        ERR_INVALID_REQUEST and no centre is opened.

        PRD: "A center is opened with a `name`, a funded `seat_capacity` of at least
        1, a `certified_teacher_fte` greater than zero carried to 2 decimal places, a
        `support_staff_fte` of zero or more carried to 2 decimal places, and a
        contractual `max_students_per_teacher` of at least 1 expressing how many
        students one full teacher FTE may carry."

        Design: Corner/entities/create_center_missing_required_seat_capacity_rejected
        """
        response = api.create_center(
            f.center_payload(name="Cedar AEC", seat_capacity=f.OMIT),
            DISTRICT_ADMIN_HEADERS,
        )
        validate_error(response, ApiErrorId.INVALID_REQUEST.value, 422)

        rows, _meta = validate_paginated(api.list_centers(DISTRICT_ADMIN_HEADERS))
        assert rows == []

    def test_a_modality_outside_the_declared_domain_is_refused(self, api):
        """HYBRID is not one of the three published modalities, so the catalogue
        create is refused with ERR_INVALID_REQUEST rather than coerced.

        PRD: "The request body is well formed: required inputs are present, enum
        values fall inside their declared domain, numerics fall inside their declared
        range, dates are ISO 8601 and booleans are booleans."

        Design: Corner/entities/create_course_invalid_modality_enum_returns_422
        """
        response = api.create_course(
            f.course_payload(
                code="GEO1",
                title="Geometry",
                subject_area=SubjectArea.MATH.value,
                modality="HYBRID",
                proctoring_required=False,
            ),
            DISTRICT_ADMIN_HEADERS,
        )
        validate_error(response, ApiErrorId.INVALID_REQUEST.value, 422)

        rows, _meta = validate_paginated(api.list_courses(DISTRICT_ADMIN_HEADERS))
        assert rows == []

    def test_a_credit_value_off_the_quarter_grid_is_refused(self, api):
        """0.30 is not a multiple of 0.25, so the catalogue refuses it with
        ERR_INVALID_REQUEST and the quarter-credit grid stays intact.

        PRD: "Each course is published with a `code` of 2 to 16 characters that is
        unique across the catalog and doubles as the transcript course code, a `title`
        of 1 to 120 characters, a `subject_area` drawn from `ELA`, `MATH`, `SCIENCE`,
        `SOCIAL_STUDIES` and `ELECTIVE` that determines which graduation-plan subject
        bucket the credit lands in, a `credit_value` that is a multiple of 0.25
        between 0.25 and 2.00 representing full credit for complete mastery, and a
        `modality` of `ONLINE`, `PACKET` or `BLENDED`."

        Design: Corner/entities/create_course_credit_value_not_quarter_multiple_returns_422
        """
        response = api.create_course(
            f.course_payload(
                code="ART1",
                title="Art I",
                subject_area=SubjectArea.ELECTIVE.value,
                credit_value=0.30,
                total_modules=4,
                required_seat_hours=30.00,
                pacing_days=20,
            ),
            DISTRICT_ADMIN_HEADERS,
        )
        validate_error(response, ApiErrorId.INVALID_REQUEST.value, 422)

        rows, _meta = validate_paginated(api.list_courses(DISTRICT_ADMIN_HEADERS))
        assert rows == []

    def test_a_path_identifier_of_the_wrong_entity_type_still_reads_as_missing(
        self, api
    ):
        """A real home-school id offered where a student id belongs returns 404
        ERR_STUDENT_NOT_FOUND, and so does an id that was never minted.

        PRD: "Every identifier embedded in the request path exists, validated left to
        right."

        Design: Corner/entities/get_student_unknown_id_not_found
        """
        school = fx.open_home_school(api)

        confused = api.get_student(school["id"], REGISTRAR_HEADERS)
        body = validate_error(confused, ApiErrorId.STUDENT_NOT_FOUND.value, 404)
        assert "full_name" not in body
        assert "cohort_year" not in body

        unminted = api.get_student(NON_EXISTENT_UUID, REGISTRAR_HEADERS)
        validate_error(unminted, ApiErrorId.STUDENT_NOT_FOUND.value, 404)

    def test_a_body_identifier_that_resolves_to_nothing_is_a_not_found(self, api):
        """A `home_school_id` naming a catalogue course resolves to no school, so the
        student create returns 404 ERR_HOME_SCHOOL_NOT_FOUND.

        PRD: "Every identifier supplied inside the request body resolves to an
        existing row — `student_id`, `center_id`, `course_id`, `prior_course_record_id`,
        `placement_id`, `proctor_station_id`, `support_provider_id` and
        `prior_referral_id`."

        Design: Corner/entities/create_student_unknown_home_school_not_found
        """
        course = fx.publish_course(api, code="ALG1", title="Algebra I")

        response = api.create_student(
            f.student_payload(course["id"], full_name="Cyd Marek", grade_level=11),
            REGISTRAR_HEADERS,
        )
        validate_error(response, ApiErrorId.HOME_SCHOOL_NOT_FOUND.value, 404)

        rows, _meta = validate_paginated(api.list_students(REGISTRAR_HEADERS))
        assert rows == []

    def test_a_home_school_id_never_satisfies_the_referrals_center_reference(
        self, api
    ):
        """Parentage travels in body identifiers rather than in the URL, so a
        referral whose `center_id` is a home-school id fails with
        ERR_CENTER_NOT_FOUND even though its `student_id` resolves.

        PRD: "Failure is the matching 404 from the set `ERR_STUDENT_NOT_FOUND`,
        `ERR_CENTER_NOT_FOUND`, `ERR_COURSE_NOT_FOUND`, `ERR_PRIOR_RECORD_NOT_FOUND`,
        `ERR_PLACEMENT_NOT_FOUND`, `ERR_STATION_NOT_FOUND`, `ERR_PROVIDER_NOT_FOUND`
        or `ERR_REFERRAL_NOT_FOUND`."

        Design: Corner/entities/referral_center_fk_integrity_rejects_unknown_center
        """
        school = fx.open_home_school(api)
        student = fx.register_student(api, school["id"], full_name="Dov Klein")
        counselor = make_home_school_counselor_headers(school["id"])

        response = api.create_referral(
            f.referral_payload(
                student["id"],
                school["id"],
                pathway=Pathway.CREDIT_DEFICIENCY.value,
                deficiency_credits=4.00,
                behavior_incident_count=1,
                days_disengaged=6,
            ),
            counselor,
        )
        validate_error(response, ApiErrorId.CENTER_NOT_FOUND.value, 404)

        rows, _meta = validate_paginated(
            api.list_referrals(counselor, {"student_id": student["id"]})
        )
        assert rows == []
