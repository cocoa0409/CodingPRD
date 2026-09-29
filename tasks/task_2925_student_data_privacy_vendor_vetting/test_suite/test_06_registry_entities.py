"""Registry surface: creation defaults, reads, paging, shape refusals and the
reference-resolution behaviour of body foreign keys.
"""

from test_helpers import (
    ADMIN_HEADERS,
    assert_bare_uuid,
    assert_common_fields,
    assert_covers_exactly,
    assert_decimal_equals,
    assert_integer_equals,
    assert_pagination_meta,
    factories as fac,
    fixtures as fx,
    make_teacher_headers,
    validate_error,
    validate_paginated,
    validate_success,
)
from test_helpers.api_errors import (
    ERR_APPLICATION_NOT_FOUND,
    ERR_DUPLICATE_EMPLOYEE_NUMBER,
    ERR_INVALID_REQUEST,
    ERR_REVIEW_NOT_FOUND,
    ERR_VENDOR_NOT_FOUND,
)
from test_helpers.constants import (
    ACCESSIBILITY_WCAG21_AA,
    ANONYMIZE,
    APPLICATION_CANDIDATE,
    BAND_LOW,
    CATEGORY_ADMINISTRATIVE,
    CATEGORY_ASSESSMENT,
    CATEGORY_COMMUNICATION,
    CATEGORY_INSTRUCTIONAL_CONTENT,
    COMMITMENT_PROPOSED,
    ELEMENT_STUDENT_NAME,
    JUST_240,
    POSTURE_CLEAR,
    PURPOSE_61,
    REQUEST_DRAFT,
    SSO_LTI13,
    SSO_OIDC,
    SSO_SAML2,
    UNKNOWN_UUID,
    VENDOR_REGISTERED,
    VISIBILITY_HIDDEN,
)


# ---------------------------------------------------------------------------
# Vendor: creation, retrieval, listing
# ---------------------------------------------------------------------------


def test_registering_a_vendor_returns_the_full_computed_envelope(api):
    """Every computed column is populated by the create, none left null.

    PRD: "A freshly registered vendor lands in registry status `REGISTERED`
    with `open_incident_count` and `flagged_subprocessor_count` both zero,
    `reauthorization_risk_score` at 0.00, `suspended_at` null, and its
    `risk_score` and `privacy_posture` computed immediately — which for a
    vendor with no children means the contractual-term penalty is the only
    non-zero contribution to its score."

    Design: Corner/entities/vendor_creation_returns_full_envelope_with_computed_defaults
    """
    fx.set_clock(api)

    response = api.create_vendor(
        fac.vendor_payload(
            legal_name="Brightpath Reading Co",
            hq_country_code="US",
            breach_notification_hours=48,
            data_deletion_days=30,
            signed_state_addendum=True,
            subprocessor_disclosure_complete=True,
        ),
        ADMIN_HEADERS,
    )

    vendor = validate_success(response, 201)
    assert response.json()["response_type"] == "object", (
        "A single-resource write answers with response_type object"
    )
    assert vendor["status"] == VENDOR_REGISTERED, (
        f"Expected REGISTERED, got {vendor['status']}"
    )
    assert_decimal_equals(vendor["risk_score"], "0.00", "risk_score")
    assert vendor["privacy_posture"] == POSTURE_CLEAR, (
        f"Expected CLEAR, got {vendor['privacy_posture']}"
    )
    assert_integer_equals(vendor["open_incident_count"], 0, "open_incident_count")
    assert_integer_equals(
        vendor["flagged_subprocessor_count"], 0, "flagged_subprocessor_count"
    )
    assert_decimal_equals(
        vendor["reauthorization_risk_score"], "0.00", "reauthorization_risk_score"
    )
    assert vendor["suspended_at"] is None, (
        f"suspended_at must start null, got {vendor['suspended_at']!r}"
    )
    assert_common_fields(vendor, expected_version=1)
    assert_bare_uuid(vendor["id"], "vendor id")


def test_reading_a_vendor_back_echoes_the_stored_row(api):
    """A read is not a mutation, so the version counter stays at 1.

    PRD: "`version` is an integer that starts at 1 when the row is created and
    increases by exactly 1 on every mutation of that row."

    Design: Corner/entities/vendor_retrieval_returns_the_stored_row
    """
    fx.set_clock(api)
    created = fx.register_vendor(
        api,
        legal_name="Brightpath Reading Co",
        hq_country_code="US",
        breach_notification_hours=48,
        data_deletion_days=30,
        signed_state_addendum=True,
        subprocessor_disclosure_complete=True,
    )

    response = api.get_vendor(created["id"], ADMIN_HEADERS)

    vendor = validate_success(response, 200)
    assert vendor["legal_name"] == "Brightpath Reading Co", (
        f"legal_name must round-trip, got {vendor['legal_name']!r}"
    )
    assert_integer_equals(
        vendor["breach_notification_hours"], 48, "breach_notification_hours"
    )
    assert vendor["signed_state_addendum"] is True, (
        "signed_state_addendum must round-trip as a JSON boolean"
    )
    assert_integer_equals(vendor["version"], 1, "version")


def test_the_vendor_registry_pages_with_total_count_and_has_more(api):
    """total_count counts the whole matching set, not the returned page.

    PRD: "The `meta` block of a list response carries `limit` and `offset` as
    they were resolved for the query, `total_count` as the number of rows
    matching the filters before pagination, and `has_more` as true whenever
    rows remain beyond the returned page."

    Design: Corner/entities/vendor_listing_paginates_with_total_count_and_has_more
    """
    fx.set_clock(api)
    expected_ids = [
        fx.register_vendor(api, legal_name=name)["id"]
        for name in ("Vendor Alpha", "Vendor Bravo", "Vendor Charlie")
    ]

    first_page = api.list_vendors(ADMIN_HEADERS, limit=2, offset=0)
    second_page = api.list_vendors(ADMIN_HEADERS, limit=2, offset=2)

    first_rows, first_meta = validate_paginated(first_page)
    assert first_page.json()["response_type"] == "array", (
        "A collection read answers with response_type array"
    )
    assert len(first_rows) == 2, f"Expected a full page of 2, got {len(first_rows)}"
    assert_pagination_meta(first_meta, limit=2, offset=0, total_count=3, has_more=True)

    second_rows, second_meta = validate_paginated(second_page)
    assert len(second_rows) == 1, f"Expected a tail page of 1, got {len(second_rows)}"
    assert_pagination_meta(second_meta, limit=2, offset=2, total_count=3, has_more=False)
    assert_covers_exactly([first_rows, second_rows], expected_ids)


# ---------------------------------------------------------------------------
# Not found, required fields and declared type constraints
# ---------------------------------------------------------------------------


def test_an_unknown_application_id_is_a_typed_not_found(api):
    """A well-formed but unknown path id is a 404, never an empty 200.

    PRD: "Every path identifier resolves, left to right — otherwise the
    matching not-found code."

    Design: Corner/entities/application_not_found_for_unknown_uuid
    """
    fx.set_clock(api)

    response = api.get_application(UNKNOWN_UUID, ADMIN_HEADERS)

    body = validate_error(response, ERR_APPLICATION_NOT_FOUND, 404)
    assert response.json()["response_type"] == "error", (
        "A refusal answers with response_type error"
    )
    assert body["message"].strip(), "The error envelope carries a human-readable message"


def test_a_teacher_without_a_school_code_is_refused_at_the_shape_gate(api):
    """The rejected write persists nothing, so its employee number stays free.

    PRD: "A request that survives authentication and role authorization is next
    checked for shape, and any shape failure is reported as `ERR_INVALID_REQUEST`
    (HTTP 400)."

    Design: Corner/entities/teacher_creation_missing_school_code_is_invalid_request
    """
    fx.set_clock(api)

    refused = api.create_teacher(
        {
            "full_name": "Ivy Chen",
            "employee_number": "EMP-9001",
            "grade_bands_taught": [3, 4, 5],
        },
        ADMIN_HEADERS,
    )

    validate_error(refused, ERR_INVALID_REQUEST, 400)
    accepted = api.create_teacher(
        {
            "full_name": "Ivy Chen",
            "employee_number": "EMP-9001",
            "school_code": "ES-11",
            "grade_bands_taught": [3, 4, 5],
        },
        ADMIN_HEADERS,
    )
    teacher = validate_success(accepted, 201)
    assert teacher["school_code"] == "ES-11", (
        f"Expected ES-11, got {teacher['school_code']!r}"
    )


def test_a_drafted_request_carries_the_declared_creation_defaults(api):
    """A DRAFT row is not yet open work, so the teacher's counter stays at zero.

    PRD: "A drafted request sits in `DRAFT` with `revision_round` at zero,
    `submitted_at` null, `triage_note` null, `priority_score` at 0.00 and
    `priority_band` at `LOW`."

    Design: Corner/entities/application_request_defaults_to_draft_with_null_scores
    """
    fx.set_clock(api)
    vendor = fx.register_vendor(api, legal_name="Meridian Practice Labs")
    app = fx.register_application(
        api,
        vendor["id"],
        name="Meridian Practice",
        category=CATEGORY_ASSESSMENT,
        grade_band_low=6,
        grade_band_high=8,
        sso_protocol=SSO_SAML2,
        accessibility_conformance_level=ACCESSIBILITY_WCAG21_AA,
        vpat_on_file=True,
    )
    teacher = fx.enroll_teacher(
        api, full_name="Dana Reyes", employee_number="EMP-9002", school_code="MS-04"
    )
    teacher_headers = make_teacher_headers(teacher["id"])

    response = api.create_request(
        fac.request_payload(
            app["id"],
            teacher["id"],
            instructional_justification=JUST_240,
            requested_data_elements=[ELEMENT_STUDENT_NAME],
            student_count_estimate=700,
            grade_band_low=7,
            grade_band_high=8,
        ),
        teacher_headers,
    )

    request = validate_success(response, 201)
    assert request["status"] == REQUEST_DRAFT, (
        f"Expected DRAFT, got {request['status']}"
    )
    assert_integer_equals(request["revision_round"], 0, "revision_round")
    assert_decimal_equals(request["priority_score"], "0.00", "priority_score")
    assert request["priority_band"] == BAND_LOW, (
        f"A drafted request starts at LOW, got {request['priority_band']}"
    )
    assert request["submitted_at"] is None, (
        f"submitted_at must start null, got {request['submitted_at']!r}"
    )
    assert request["triage_note"] is None, (
        f"triage_note must start null, got {request['triage_note']!r}"
    )
    filer = fx.read_teacher(api, teacher["id"])
    assert_integer_equals(filer["open_request_count"], 0, "open_request_count")


def test_the_permitted_tier_and_visibility_are_derived_from_the_category(api):
    """The tier is looked up from the category, never taken from the payload.

    PRD: "The application's `max_permitted_tier` is looked up from its category
    at creation and never recomputed, because category is immutable:
    `INSTRUCTIONAL_CONTENT` permits tiers up to 2, `COMMUNICATION` and
    `ANALYTICS` up to 3, and `ASSESSMENT` and `ADMINISTRATIVE` up to 4."

    Design: Corner/entities/application_computed_tier_and_visibility_are_server_derived
    """
    fx.set_clock(api)
    vendor = fx.register_vendor(
        api, legal_name="Cascadia Student Systems", data_deletion_days=45
    )

    instructional = fx.register_application(
        api,
        vendor["id"],
        name="Cascadia Reader",
        category=CATEGORY_INSTRUCTIONAL_CONTENT,
        grade_band_low=3,
        grade_band_high=5,
        sso_protocol=SSO_LTI13,
        accessibility_conformance_level=ACCESSIBILITY_WCAG21_AA,
        vpat_on_file=True,
    )
    administrative = fx.register_application(
        api,
        vendor["id"],
        name="Cascadia SIS Companion",
        category=CATEGORY_ADMINISTRATIVE,
        sso_protocol=SSO_SAML2,
    )
    communication = fx.register_application(
        api,
        vendor["id"],
        name="Cascadia Messages",
        category=CATEGORY_COMMUNICATION,
        sso_protocol=SSO_OIDC,
    )

    assert_integer_equals(
        instructional["max_permitted_tier"], 2, "INSTRUCTIONAL_CONTENT tier ceiling"
    )
    assert_integer_equals(
        administrative["max_permitted_tier"], 4, "ADMINISTRATIVE tier ceiling"
    )
    assert_integer_equals(
        communication["max_permitted_tier"], 3, "COMMUNICATION tier ceiling"
    )
    assert instructional["catalog_visibility"] == VISIBILITY_HIDDEN, (
        f"A new product starts hidden, got {instructional['catalog_visibility']}"
    )
    assert_decimal_equals(
        instructional["exposed_sensitivity_points"], "0.00", "exposed_sensitivity_points"
    )
    assert instructional["status"] == APPLICATION_CANDIDATE, (
        f"Expected CANDIDATE, got {instructional['status']}"
    )
    assert instructional["sso_verified"] is False, (
        "An asserted protocol is unverified until the district attests it"
    )


def test_enum_inverted_band_and_out_of_range_hours_are_all_invalid_request(api):
    """Three different shape failures all land on the same 400, and none persists.

    PRD: "Shape validation covers: every required input field present; no
    unknown fields; each field of its declared JSON type; every enumerated value
    drawn from its declared set; every timestamp a valid ISO 8601 UTC instant;
    and every integer inside its declared range."

    Design: Corner/entities/application_enum_and_range_constraints_rejected_at_shape_gate
    """
    fx.set_clock(api)
    vendor = fx.register_vendor(api, legal_name="Brightpath Reading Co")

    bad_enum = api.create_application(
        fac.application_payload(
            vendor["id"],
            name="Bad Category App",
            category="GAMES",
            grade_band_low=3,
            grade_band_high=5,
            sso_protocol=SSO_LTI13,
        ),
        ADMIN_HEADERS,
    )
    inverted_band = api.create_application(
        fac.application_payload(
            vendor["id"],
            name="Inverted Band App",
            category=CATEGORY_ASSESSMENT,
            grade_band_low=8,
            grade_band_high=6,
        ),
        ADMIN_HEADERS,
    )
    hours_over_ceiling = api.create_vendor(
        fac.vendor_payload(
            legal_name="Out Of Range Vendor", breach_notification_hours=721
        ),
        ADMIN_HEADERS,
    )

    validate_error(bad_enum, ERR_INVALID_REQUEST, 400)
    validate_error(inverted_band, ERR_INVALID_REQUEST, 400)
    validate_error(hours_over_ceiling, ERR_INVALID_REQUEST, 400)
    survivors = api.list_applications(ADMIN_HEADERS, vendor_id=vendor["id"])
    rows, meta = validate_paginated(survivors)
    assert_integer_equals(meta["total_count"], 0, "surviving application total_count")
    assert rows == [], f"No rejected write may persist, got {len(rows)} rows"


def test_a_second_teacher_reusing_an_employee_number_is_a_conflict(api):
    """The duplicate is a 409 business conflict, not a 400 shape failure.

    PRD: "The employee number is the district's own key and must be unique
    across every teacher row; a second enrolment reusing one is refused with
    `ERR_DUPLICATE_EMPLOYEE_NUMBER`."

    Design: Corner/entities/duplicate_employee_number_rejected_across_teachers
    """
    fx.set_clock(api)
    incumbent = fx.enroll_teacher(
        api,
        full_name="Dana Reyes",
        employee_number="EMP-9003",
        school_code="MS-04",
        grade_bands_taught=[6, 7, 8],
    )

    response = api.create_teacher(
        fac.teacher_payload(
            full_name="Other Person",
            employee_number="EMP-9003",
            school_code="ES-11",
            grade_bands_taught=[3],
        ),
        ADMIN_HEADERS,
    )

    validate_error(response, ERR_DUPLICATE_EMPLOYEE_NUMBER, 409)
    stored = fx.read_teacher(api, incumbent["id"])
    assert stored["full_name"] == "Dana Reyes", (
        f"The incumbent row is untouched, got {stored['full_name']!r}"
    )
    assert_integer_equals(stored["version"], 1, "version")


# ---------------------------------------------------------------------------
# Body foreign keys resolve before any later rung
# ---------------------------------------------------------------------------


def test_a_commitment_naming_an_unknown_review_is_not_found_before_the_occ_check(api):
    """The concurrency token is genuinely current, so only the FK can fail.

    PRD: "Foreign keys carried in a request body are resolved after the path, in
    the order in which the endpoint declares its input fields, and they draw
    from the same catalogue of 404 codes selected by the referenced entity."

    Design: Corner/entities/commitment_body_fk_to_unknown_review_is_not_found
    """
    chain = fx.screening_review_chain(
        api,
        vendor={"legal_name": "Brightpath Reading Co"},
        application={"name": "Brightpath Readers", "sso_protocol": SSO_LTI13},
        review={"estimated_minutes": 180},
        assignee_capacity=2400,
    )
    current_version = fx.review_version(api, chain.review_id)

    orphan = api.create_commitment(
        fac.commitment_payload(
            UNKNOWN_UUID,
            ELEMENT_STUDENT_NAME,
            current_version,
            retention_days=365,
            deletion_method=ANONYMIZE,
            justified_purpose=PURPOSE_61,
        ),
        chain.assignee_headers,
    )

    validate_error(orphan, ERR_REVIEW_NOT_FOUND, 404)
    _, empty_meta = validate_paginated(
        api.list_commitments(chain.assignee_headers, review_id=chain.review_id)
    )
    assert_integer_equals(empty_meta["total_count"], 0, "commitment total_count")

    accepted = api.create_commitment(
        fac.commitment_payload(
            chain.review_id,
            ELEMENT_STUDENT_NAME,
            current_version,
            retention_days=365,
            deletion_method=ANONYMIZE,
            justified_purpose=PURPOSE_61,
        ),
        chain.assignee_headers,
    )
    commitment = validate_success(accepted, 201)
    assert commitment["review_id"] == chain.review_id, (
        f"Expected the real parent, got {commitment['review_id']}"
    )
    assert commitment["status"] == COMMITMENT_PROPOSED, (
        f"Expected PROPOSED, got {commitment['status']}"
    )
    assert_integer_equals(commitment["sensitivity_tier"], 1, "sensitivity_tier")
    assert_decimal_equals(commitment["element_points"], "1.44", "element_points")
    assert commitment["is_minimized"] is True, (
        "A tier-1 element kept 365 days and anonymized is minimized"
    )
    app = fx.read_application(api, chain.application_id)
    assert_decimal_equals(
        app["exposed_sensitivity_points"], "0.00", "exposed_sensitivity_points"
    )


def test_an_application_under_an_unknown_vendor_is_not_found(api):
    """The identical payload succeeds verbatim once the parent vendor exists.

    PRD: "A body `vendor_id` or `processor_vendor_id` that names no stored
    vendor yields `ERR_VENDOR_NOT_FOUND`; a body `review_id` that names no
    stored review yields `ERR_REVIEW_NOT_FOUND`; a body `application_id` yields
    `ERR_APPLICATION_NOT_FOUND`; a body `requester_teacher_id` yields
    `ERR_TEACHER_NOT_FOUND`; a body `assigned_analyst_id` yields
    `ERR_ANALYST_NOT_FOUND`; and a body `source_request_id` yields
    `ERR_REQUEST_NOT_FOUND`."

    Design: Corner/entities/flat_topology_cross_reference_integrity_on_application_create
    """
    fx.set_clock(api)

    orphan = api.create_application(
        fac.application_payload(
            UNKNOWN_UUID,
            name="Orphan App",
            category=CATEGORY_ASSESSMENT,
            grade_band_low=6,
            grade_band_high=8,
            sso_protocol=SSO_SAML2,
        ),
        ADMIN_HEADERS,
    )

    validate_error(orphan, ERR_VENDOR_NOT_FOUND, 404)
    vendor = fx.register_vendor(api, legal_name="Brightpath Reading Co")
    retried = api.create_application(
        fac.application_payload(
            vendor["id"],
            name="Orphan App",
            category=CATEGORY_ASSESSMENT,
            grade_band_low=6,
            grade_band_high=8,
            sso_protocol=SSO_SAML2,
        ),
        ADMIN_HEADERS,
    )
    app = validate_success(retried, 201)
    assert app["vendor_id"] == vendor["id"], (
        f"Expected {vendor['id']}, got {app['vendor_id']}"
    )
    assert_integer_equals(app["max_permitted_tier"], 4, "max_permitted_tier")
