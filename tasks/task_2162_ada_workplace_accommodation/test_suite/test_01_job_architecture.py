"""Job profiles, their duties, publication, and the workforce register."""

from test_helpers import (
    TEST_USERS,
    UNKNOWN_IDS,
    ApiErrorId,
    assert_employee,
    assert_essential_function,
    assert_job_profile,
    assert_three_fraction_digits,
    create_employee_payload,
    create_essential_function_payload,
    create_job_profile_payload,
    create_profile,
    is_valid_uuid,
    set_clock,
    validate_error,
    validate_paginated,
    validate_success,
)

COORD = TEST_USERS["coordinator_headers"]
AUDITOR = TEST_USERS["auditor_headers"]


def test_registering_an_employee_returns_the_three_base_roll_ups(api):
    """PRD §3.2: "Three roll-ups start at their base values: `employment_status`
    at `ACTIVE`, `open_case_count` at zero and `lifetime_denial_count` at zero."
    PRD §2.4: "Every resource this API mints carries a server-generated `id`. It
    is a UUID string with no type prefix — no `emp_`, no `req_`, nothing but the
    UUID itself."
    PRD §2.4: "Most resources additionally carry `updated_at` — same format,
    refreshed on every mutation of that row — and `version`, an integer that
    begins at 1 when the row is created and increases by exactly 1 on every
    mutation of that row."

    Design: Corner/entities/corner_employee_creation_returns_defaults_and_system_fields
    """
    profile = create_profile(job_code="C-JP-01", department_code="CN1")

    response = api.create_employee(
        create_employee_payload(
            profile["id"],
            employee_number="C-E-01",
            full_name="Corner One",
            department_code="CN1",
            job_title="Operator",
            hire_date="2024-03-01",
            annual_salary_cents=4_000_000,
        ),
        COORD,
    )
    data = validate_success(response, 201)

    assert_employee(data)
    assert response.json()["response_type"] == "object"
    assert data["employment_status"] == "ACTIVE"
    assert data["open_case_count"] == 0
    assert data["lifetime_denial_count"] == 0
    assert data["version"] == 1, "a freshly created row begins at version 1"
    assert is_valid_uuid(data["id"]) and "_" not in data["id"]
    assert_three_fraction_digits(data["created_at"], "Employee.created_at")

    meta = response.json()["meta"]
    assert meta["api_request_id"].startswith("req_")


def test_reading_an_employee_returns_the_row_that_was_registered(api):
    """PRD §3.2: "An employee is registered by an `AccommodationCoordinator` or a
    `ComplianceAuditor` with `employee_number` (a payroll identifier unique
    across all employees, between 1 and 32 characters), `full_name`,
    `department_code`, `job_title`, `hire_date` as an ISO 8601 calendar date in
    `YYYY-MM-DD` form, `job_profile_id` naming the profile whose duties will
    govern this person's analyses, an optional `is_people_manager` flag
    defaulting to false, and `annual_salary_cents`, a whole-cent figure that may
    not be negative."
    PRD §2.2: "The `data` field contains the resource object or an array of
    resource objects."

    Design: Corner/entities/corner_employee_retrieval_returns_stored_row
    """
    profile = create_profile(job_code="C-JP-02", department_code="CN2")
    created = validate_success(
        api.create_employee(
            create_employee_payload(
                profile["id"],
                employee_number="C-E-02",
                full_name="Corner Two",
                department_code="CN2",
                job_title="Operator",
                hire_date="2024-03-02",
                annual_salary_cents=4_100_000,
            ),
            COORD,
        ),
        201,
    )

    response = api.get_employee(created["id"], AUDITOR)
    data = validate_success(response, 200)

    assert response.json()["response_type"] == "object"
    assert data["id"] == created["id"]
    assert data["employee_number"] == "C-E-02"
    assert data["job_profile_id"] == profile["id"]
    assert data["annual_salary_cents"] == 4_100_000
    assert data["is_people_manager"] is False


def test_employee_listing_pages_and_reports_the_filtered_population(api):
    """PRD §3.2: "Employees can be listed with filters on `job_profile_id`,
    `department_code` and `employment_status`."
    PRD §2.3: "All four pagination fields — `limit`, `offset`, `total_count` and
    `has_more` — appear in the `meta` object of every list response.
    `total_count` reports the number of rows matching the filters before the page
    window is applied, and `has_more` is true exactly when rows remain beyond the
    current window."

    Design: Corner/entities/corner_employee_list_paginates_with_total_count_and_has_more
    """
    profile = create_profile(job_code="C-JP-03", department_code="CN3")
    for suffix, hire_date in (("A", "2024-03-03"), ("B", "2024-03-04"), ("C", "2024-03-05")):
        validate_success(
            api.create_employee(
                create_employee_payload(
                    profile["id"],
                    employee_number=f"C-E-03{suffix}",
                    full_name=f"Corner 3{suffix}",
                    department_code="CN3",
                    hire_date=hire_date,
                ),
                COORD,
            ),
            201,
        )

    first_page = api.list_employees(
        COORD, {"job_profile_id": profile["id"], "limit": 2, "offset": 0}
    )
    rows, meta = validate_paginated(first_page)
    assert len(rows) == 2, "limit 2 caps the page at two rows"
    assert meta["total_count"] == 3, "total_count counts the filtered population"
    assert meta["has_more"] is True
    assert meta["limit"] == 2 and meta["offset"] == 0

    second_page = api.list_employees(
        COORD, {"job_profile_id": profile["id"], "limit": 2, "offset": 2}
    )
    rows2, meta2 = validate_paginated(second_page)
    assert len(rows2) == 1
    assert meta2["total_count"] == 3
    assert meta2["has_more"] is False


def test_job_profile_without_the_employer_budget_is_a_malformed_body(api):
    """PRD §2.6: "**Body well-formed** — the request body must parse, must carry
    every required field, and every supplied value must satisfy its declared
    type, its enum membership and its numeric range; otherwise
    `ERR_INVALID_REQUEST`."
    PRD §3.1: "An `AccommodationCoordinator` creates a **job profile** by
    supplying its business key `job_code`, a human-readable `title`, the owning
    `department_code`, and two budget figures in whole cents:
    `department_annual_budget_cents`, the owning department's annual
    accommodation budget, and `employer_annual_budget_cents`, the employer-wide
    annual accommodation budget."

    Design: Corner/entities/corner_job_profile_missing_required_field_returns_invalid_request
    """
    set_clock()

    payload = create_job_profile_payload(job_code="C-JP-04", department_code="CN4")
    payload.pop("employer_annual_budget_cents")

    response = api.create_job_profile(payload, COORD)
    validate_error(response, ApiErrorId.ERR_INVALID_REQUEST)

    # Nothing was persisted: the same job_code is still free.
    complete = validate_success(
        api.create_job_profile(
            create_job_profile_payload(job_code="C-JP-04", department_code="CN4"), COORD
        ),
        201,
    )
    assert complete["job_code"] == "C-JP-04"
    assert complete["status"] == "DRAFT"


def test_duty_flags_default_to_essential_and_not_reassignable(api):
    """PRD §3.1: "Two optional flags round it out: `is_essential`, which defaults
    to true, and `marginal_reassignable`, which defaults to false and is
    meaningful only for duties that are *not* essential — it marks a marginal
    duty as one a coworker may absorb."
    PRD §3.1: "The duty's owning `job_profile_id` is taken from the address,
    never from the body, and the duty is born with `status` `ACTIVE`."
    PRD §3.1: "`essential_function_count` is the number of duties on the profile
    whose `status` is `ACTIVE`, regardless of whether they are essential or
    marginal."

    Design: Corner/entities/corner_essential_function_defaults_applied_when_omitted
    """
    profile = create_profile(job_code="C-JP-05", department_code="CN5")

    payload = create_essential_function_payload(
        function_code="C-EF-05",
        description="Default probe duty",
        criticality_weight=7,
        frequency_per_week=10,
    )
    payload.pop("is_essential")
    payload.pop("marginal_reassignable")

    response = api.create_essential_function(profile["id"], payload, COORD)
    data = validate_success(response, 201)

    assert_essential_function(data)
    assert data["is_essential"] is True
    assert data["marginal_reassignable"] is False
    assert data["status"] == "ACTIVE"
    assert data["job_profile_id"] == profile["id"]

    refreshed = validate_success(api.get_job_profile(profile["id"], COORD), 200)
    assert refreshed["essential_function_count"] == 1
    assert refreshed["total_essential_weight"] == 7


def test_criticality_weight_above_ten_is_rejected_and_writes_nothing(api):
    """PRD §3.1: "a `criticality_weight` between 1 and 10 inclusive that
    expresses how important the duty is relative to its siblings, and a
    `frequency_per_week` between 0 and 40 inclusive."
    PRD §2.6: "**Body well-formed** — the request body must parse, must carry
    every required field, and every supplied value must satisfy its declared
    type, its enum membership and its numeric range; otherwise
    `ERR_INVALID_REQUEST`."

    Design: Corner/entities/corner_essential_function_weight_out_of_range_rejected
    """
    profile = create_profile(job_code="C-JP-08", department_code="CN8")

    response = api.create_essential_function(
        profile["id"],
        create_essential_function_payload(
            function_code="C-EF-08",
            description="Out of range duty",
            criticality_weight=11,
            frequency_per_week=10,
        ),
        COORD,
    )
    validate_error(response, ApiErrorId.ERR_INVALID_REQUEST)

    rows, meta = validate_paginated(api.list_essential_functions(profile["id"], COORD))
    assert rows == [] and meta["total_count"] == 0

    refreshed = validate_success(api.get_job_profile(profile["id"], COORD), 200)
    assert refreshed["total_essential_weight"] == 0


def test_authoring_a_duty_under_an_unknown_profile_is_a_domain_specific_404(api):
    """PRD §2.6: "**Path identifiers resolve** — every id templated into the URL
    must name an existing row, checked strictly left to right, each yielding the
    not-found code for its own resource type."
    PRD §2.8: "The eleven not-found codes map one-to-one onto resource types:
    `ERR_EMPLOYEE_NOT_FOUND`, `ERR_JOB_PROFILE_NOT_FOUND`,
    `ERR_ESSENTIAL_FUNCTION_NOT_FOUND`, `ERR_REQUEST_NOT_FOUND`,
    `ERR_DOC_REQUEST_NOT_FOUND`, `ERR_FUNCTION_ANALYSIS_NOT_FOUND`,
    `ERR_OPTION_NOT_FOUND`, `ERR_TRIAL_NOT_FOUND`, `ERR_DENIAL_NOT_FOUND`,
    `ERR_APPEAL_NOT_FOUND` and `ERR_ABSENCE_RECORD_NOT_FOUND`, all HTTP 404."

    Design: Corner/entities/corner_essential_function_requires_existing_parent_profile
    """
    set_clock()

    response = api.create_essential_function(
        UNKNOWN_IDS["job_profile"],
        create_essential_function_payload(
            function_code="C-EF-10", description="Orphan duty"
        ),
        COORD,
    )
    validate_error(response, ApiErrorId.ERR_JOB_PROFILE_NOT_FOUND)


def test_publication_freezes_the_architecture_and_the_job_code_stays_unique(api):
    """PRD §3.3: "The pin is only legal against a profile that is `PUBLISHED` at
    that moment; a case opened for an employee whose profile is still `DRAFT` is
    refused with `ERR_PROFILE_NOT_PUBLISHED`."
    PRD §3.1: "An `AccommodationCoordinator` publishes a `DRAFT` profile by
    supplying `profile_version_label`, a label stamped onto the profile at that
    moment; the profile's `status` becomes `PUBLISHED`."
    PRD §3.1: "Authoring a duty onto a profile that has already left `DRAFT` is
    refused with `ERR_PROFILE_NOT_DRAFT`."
    PRD §3.1: "The `job_code` must be unique across all profiles; a collision is
    rejected with `ERR_DUPLICATE_RESOURCE_KEY`."

    Design: Corner/validations/corner_profile_lifecycle_gates_authoring_intake_and_uniqueness
    """
    set_clock()
    profile = create_profile(job_code="C-JP-28", department_code="CNS")
    validate_success(
        api.create_essential_function(
            profile["id"],
            create_essential_function_payload(
                function_code="C-EF-28A", description="Early duty"
            ),
            COORD,
        ),
        201,
    )
    employee = validate_success(
        api.create_employee(
            create_employee_payload(
                profile["id"], employee_number="C-E-28", department_code="CNS"
            ),
            COORD,
        ),
        201,
    )

    intake = api.create_accommodation_request(
        {
            "employee_id": employee["id"],
            "request_channel": "WRITTEN",
            "requested_accommodation_text": "Intake against a draft profile",
            "disability_obvious": True,
        },
        COORD,
    )
    validate_error(intake, ApiErrorId.ERR_PROFILE_NOT_PUBLISHED)
    assert validate_success(api.get_employee(employee["id"], COORD))["open_case_count"] == 0

    published = validate_success(
        api.publish_job_profile(
            profile["id"], {"profile_version_label": "2026.9"}, COORD
        ),
        200,
    )
    assert_job_profile(published)
    assert published["status"] == "PUBLISHED"
    assert published["profile_version_label"] == "2026.9"

    late_duty = api.create_essential_function(
        profile["id"],
        create_essential_function_payload(
            function_code="C-EF-28B",
            description="Late duty",
            criticality_weight=3,
            frequency_per_week=5,
        ),
        COORD,
    )
    validate_error(late_duty, ApiErrorId.ERR_PROFILE_NOT_DRAFT)
    assert (
        validate_success(api.get_job_profile(profile["id"], COORD))[
            "essential_function_count"
        ]
        == 1
    )

    duplicate = api.create_job_profile(
        create_job_profile_payload(
            job_code="C-JP-28",
            title="Duplicate Corner Profile",
            department_code="CNS",
        ),
        COORD,
    )
    validate_error(duplicate, ApiErrorId.ERR_DUPLICATE_RESOURCE_KEY)


def test_each_resource_family_answers_an_unknown_path_id_with_its_own_code(api):
    """PRD §2.8: "The eleven not-found codes map one-to-one onto resource types:
    `ERR_EMPLOYEE_NOT_FOUND`, `ERR_JOB_PROFILE_NOT_FOUND`,
    `ERR_ESSENTIAL_FUNCTION_NOT_FOUND`, `ERR_REQUEST_NOT_FOUND`,
    `ERR_DOC_REQUEST_NOT_FOUND`, `ERR_FUNCTION_ANALYSIS_NOT_FOUND`,
    `ERR_OPTION_NOT_FOUND`, `ERR_TRIAL_NOT_FOUND`, `ERR_DENIAL_NOT_FOUND`,
    `ERR_APPEAL_NOT_FOUND` and `ERR_ABSENCE_RECORD_NOT_FOUND`, all HTTP 404."

    Design: Corner/errors/corner_every_path_id_not_found_returns_domain_specific_404
    """
    probes = [
        (api.get_employee(UNKNOWN_IDS["employee"], AUDITOR), ApiErrorId.ERR_EMPLOYEE_NOT_FOUND),
        (
            api.update_essential_function(
                UNKNOWN_IDS["essential_function"], {"status": "RETIRED"}, COORD
            ),
            ApiErrorId.ERR_ESSENTIAL_FUNCTION_NOT_FOUND,
        ),
        (
            api.get_accommodation_request(UNKNOWN_IDS["request"], AUDITOR),
            ApiErrorId.ERR_REQUEST_NOT_FOUND,
        ),
        (
            api.withdraw_medical_doc_request(UNKNOWN_IDS["doc_request"], COORD),
            ApiErrorId.ERR_DOC_REQUEST_NOT_FOUND,
        ),
        (
            api.get_function_analysis(UNKNOWN_IDS["function_analysis"], AUDITOR),
            ApiErrorId.ERR_FUNCTION_ANALYSIS_NOT_FOUND,
        ),
        (
            api.get_accommodation_option(UNKNOWN_IDS["option"], AUDITOR),
            ApiErrorId.ERR_OPTION_NOT_FOUND,
        ),
        (api.get_trial_period(UNKNOWN_IDS["trial"], AUDITOR), ApiErrorId.ERR_TRIAL_NOT_FOUND),
        (api.get_denial_record(UNKNOWN_IDS["denial"], AUDITOR), ApiErrorId.ERR_DENIAL_NOT_FOUND),
        (api.get_appeal(UNKNOWN_IDS["appeal"], AUDITOR), ApiErrorId.ERR_APPEAL_NOT_FOUND),
        (
            api.get_absence_record(UNKNOWN_IDS["absence"], AUDITOR),
            ApiErrorId.ERR_ABSENCE_RECORD_NOT_FOUND,
        ),
    ]
    for response, expected in probes:
        assert response.status_code == 404, (
            f"expected 404 for {expected}, got {response.status_code}"
        )
        assert response.json()["response_type"] == "error"
        validate_error(response, expected)
