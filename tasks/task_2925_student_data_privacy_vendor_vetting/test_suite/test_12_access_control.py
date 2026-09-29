"""Access control: which role may reach which endpoint, which row an
entity-backed caller owns, and the three separate segregation-of-duties limbs
that guard a decision, a disposition and a publication.
"""

from test_helpers import (
    ADMIN_HEADERS,
    TELEMETRY_HEADERS,
    assert_decimal_equals,
    assert_instant_equals,
    assert_integer_equals,
    assert_pagination_meta,
    factories as fac,
    fixtures as fx,
    make_blank_identity_headers,
    make_teacher_headers,
    make_vendor_liaison_headers,
    validate_error,
    validate_paginated,
    validate_success,
)
from test_helpers.api_errors import (
    ERR_NOT_RESOURCE_OWNER,
    ERR_SEGREGATION_OF_DUTIES,
    ERR_UNAUTHENTICATED,
    ERR_UNAUTHORIZED,
    ERR_VENDOR_NOT_FOUND,
)
from test_helpers.constants import (
    ACCESSIBILITY_WCAG21_AA,
    ANONYMIZE,
    APPLICATION_APPROVED,
    CATEGORY_ASSESSMENT,
    CATEGORY_INSTRUCTIONAL_CONTENT,
    COMMITMENT_ACCEPTED,
    COMMITMENT_PROPOSED,
    CREDENTIAL_LEAD,
    CREDENTIAL_SENIOR,
    DECISION_CLEAR,
    DISPOSITION_ACCEPT,
    ELEMENT_STUDENT_NAME,
    ENTRY_PUBLISHED,
    POSTURE_CLEAR,
    PURPOSE_61,
    REQUEST_CLOSED_APPROVED,
    REQUEST_DRAFT,
    REQUEST_SUBMITTED,
    REVIEW_CLEARED,
    REVIEW_FINDINGS_ISSUED,
    REVIEW_SCREENING,
    SOURCE_NETWORK_DNS,
    SSO_LTI13,
    UNKNOWN_UUID,
    VENDOR_UNDER_REVIEW,
    VISIBILITY_HIDDEN,
    VISIBILITY_VISIBLE,
)

FIRST_EFFECTIVE_FROM = "2026-08-01T00:00:00Z"
FIRST_EXPIRY = "2027-08-01T00:00:00Z"
WAREHOUSE_PURPOSE = (
    "Cross-vendor analytics warehouse attached by the wrong liaison."
)


def _reading_product_chain(**overrides):
    """Keyword arguments for a grade 3-5 instructional-content chain."""
    kwargs = dict(
        vendor={"legal_name": "Brightpath Reading Co"},
        application={
            "name": "Brightpath Readers",
            "category": CATEGORY_INSTRUCTIONAL_CONTENT,
            "grade_band_low": 3,
            "grade_band_high": 5,
            "sso_protocol": SSO_LTI13,
            "accessibility_conformance_level": ACCESSIBILITY_WCAG21_AA,
            "vpat_on_file": True,
        },
        teacher={"school_code": "ES-11", "grade_bands_taught": [3, 4, 5]},
        request={
            "requested_data_elements": [ELEMENT_STUDENT_NAME],
            "grade_band_low": 3,
            "grade_band_high": 5,
            "student_count_estimate": 300,
        },
        review={"estimated_minutes": 180},
        assignee_capacity=2400,
    )
    kwargs.update(overrides)
    return kwargs


def _decidable_review(api, **overrides):
    """A review sitting in `FINDINGS_ISSUED` with one still-proposed commitment.

    A findings round needs at least one commitment on the table, and leaving that
    commitment `PROPOSED` keeps the accepted set empty, so the final score stays
    at the bare framework, subprocessor and accessibility total.
    """
    chain = fx.screening_review_chain(api, **_reading_product_chain(**overrides))
    fx.propose_commitment(
        api,
        chain.review_id,
        ELEMENT_STUDENT_NAME,
        chain.assignee_headers,
        justified_purpose=PURPOSE_61,
        retention_days=365,
        deletion_method=ANONYMIZE,
    )
    fx.issue_findings(
        api, chain.review_id, 0, chain.assignee_headers,
        decision_note="Nothing outstanding.",
    )
    return chain


# ---------------------------------------------------------------------------
# Endpoint role membership
# ---------------------------------------------------------------------------


def test_exclusive_operations_are_refused_to_every_other_role(api):
    """Four roles reach for four endpoints they are not listed on.

    PRD: "If `X-User-Role` is present but is not one of the five role names
    declared below, or is a valid role that the target endpoint does not list
    among its authorized roles, the request is rejected with `ERR_UNAUTHORIZED`
    (HTTP 403)."

    Design: Corner/rbac/exclusive_operations_are_refused_to_every_other_role
    """
    chain = fx.screening_review_chain(
        api, attest=False, **_reading_product_chain()
    )
    liaison_headers = make_vendor_liaison_headers(chain.vendor_id)

    admin_findings = api.issue_findings(
        chain.review_id,
        fac.findings_payload(1, decision_note="Admin has no findings authority."),
        ADMIN_HEADERS,
    )
    admin_telemetry = api.create_detection(
        fac.detection_payload(
            "readers.brightpath.example",
            "2026-07-31T12:00:00Z",
            application_id=chain.application_id,
            school_code="ES-11",
            source=SOURCE_NETWORK_DNS,
            distinct_user_count=30,
            session_count=120,
        ),
        ADMIN_HEADERS,
    )
    liaison_suspend = api.suspend_vendor(
        chain.vendor_id,
        fac.suspension_payload(reason="Liaison attempting to suspend its own vendor."),
        liaison_headers,
    )
    agent_read = api.list_detections(TELEMETRY_HEADERS)

    validate_error(admin_findings, ERR_UNAUTHORIZED, 403)
    review = fx.read_review(api, chain.review_id)
    assert review["status"] == REVIEW_SCREENING, (
        f"The review stays SCREENING, got {review['status']}"
    )
    assert_integer_equals(review["open_findings_count"], 0, "open_findings_count")

    validate_error(admin_telemetry, ERR_UNAUTHORIZED, 403)
    _rows, meta = validate_paginated(api.list_detections(ADMIN_HEADERS))
    assert_integer_equals(meta["total_count"], 0, "detection total_count")

    validate_error(liaison_suspend, ERR_UNAUTHORIZED, 403)
    vendor = fx.read_vendor(api, chain.vendor_id)
    assert vendor["status"] == VENDOR_UNDER_REVIEW, (
        f"Opening the review moved the vendor, got {vendor['status']}"
    )

    validate_error(agent_read, ERR_UNAUTHORIZED, 403)


def test_a_teacher_may_read_the_catalog_the_registry_and_its_own_row(api):
    """The role the catalog is published for is not locked out of reading it.

    PRD: "The `Authorized Roles` column is exhaustive: a valid role that is not
    listed for an endpoint receives `ERR_UNAUTHORIZED`."

    Design: Corner/rbac/shared_read_operations_work_for_the_teacher_role
    """
    fx.set_clock(api)
    vendor = fx.register_vendor(api, legal_name="Brightpath Reading Co")
    app = fx.register_application(
        api,
        vendor["id"],
        name="Brightpath Readers",
        category=CATEGORY_INSTRUCTIONAL_CONTENT,
        grade_band_low=3,
        grade_band_high=5,
        sso_protocol=SSO_LTI13,
        accessibility_conformance_level=ACCESSIBILITY_WCAG21_AA,
        vpat_on_file=True,
    )
    teacher = fx.enroll_teacher(
        api,
        full_name="Ivy Chen",
        employee_number="EMP-7128",
        school_code="ES-11",
        grade_bands_taught=[3, 4, 5],
    )
    teacher_headers = make_teacher_headers(teacher["id"])

    entries, entry_meta = validate_paginated(
        api.list_catalog_entries(teacher_headers)
    )
    applications, application_meta = validate_paginated(
        api.list_applications(teacher_headers)
    )
    one_application = validate_success(api.get_application(app["id"], teacher_headers))
    one_vendor = validate_success(api.get_vendor(vendor["id"], teacher_headers))
    own_row = validate_success(api.get_teacher(teacher["id"], teacher_headers))

    assert entries == [], f"No entry has been published yet, got {entries}"
    assert_pagination_meta(entry_meta, 10, 0, 0, False)
    assert_pagination_meta(application_meta, 10, 0, 1, False)
    assert len(applications) == 1, f"Expected one application, got {applications}"
    assert one_application["catalog_visibility"] == VISIBILITY_HIDDEN, (
        f"Nothing is published, got {one_application['catalog_visibility']}"
    )
    assert one_vendor["privacy_posture"] == POSTURE_CLEAR, (
        f"Expected CLEAR, got {one_vendor['privacy_posture']}"
    )
    assert own_row["employee_number"] == "EMP-7128", (
        f"Expected EMP-7128, got {own_row['employee_number']}"
    )
    assert_integer_equals(own_row["open_request_count"], 0, "open_request_count")


# ---------------------------------------------------------------------------
# Ownership and authentication
# ---------------------------------------------------------------------------


def test_ownership_is_enforced_for_teachers_and_vendor_liaisons(api):
    """A stranger can neither read nor act, and the rightful owner is unharmed.

    PRD: "`ERR_NOT_RESOURCE_OWNER` (HTTP 403) is raised when an entity-backed
    caller reaches for a row that is not theirs — an acting `Teacher` whose
    `X-User-ID` is not the request's `requester_teacher_id`, or an acting
    `VendorLiaison` whose `X-User-ID` is not the vendor reached from the target
    row."

    Design: Corner/rbac/ownership_is_enforced_for_teachers_and_vendor_liaisons
    """
    fx.set_clock(api)
    first_vendor = fx.register_vendor(api, legal_name="Brightpath Reading Co")
    second_vendor = fx.register_vendor(api, legal_name="Northgate Learning Systems")
    app = fx.register_application(
        api,
        first_vendor["id"],
        name="Brightpath Readers",
        category=CATEGORY_INSTRUCTIONAL_CONTENT,
        grade_band_low=3,
        grade_band_high=5,
        sso_protocol=SSO_LTI13,
        accessibility_conformance_level=ACCESSIBILITY_WCAG21_AA,
        vpat_on_file=True,
    )
    filer = fx.enroll_teacher(
        api,
        full_name="Ivy Chen",
        employee_number="EMP-7129",
        school_code="ES-11",
        grade_bands_taught=[3, 4, 5],
    )
    stranger = fx.enroll_teacher(
        api,
        full_name="Omar Diaz",
        employee_number="EMP-7130",
        school_code="ES-12",
        grade_bands_taught=[3, 4, 5],
    )
    filer_headers = make_teacher_headers(filer["id"])
    stranger_headers = make_teacher_headers(stranger["id"])
    request = fx.draft_request(
        api,
        app["id"],
        filer["id"],
        filer_headers,
        requested_data_elements=[ELEMENT_STUDENT_NAME],
        student_count_estimate=300,
        grade_band_low=3,
        grade_band_high=5,
    )

    stranger_read = api.get_request(request["id"], stranger_headers)
    stranger_submit = api.submit_request(
        request["id"], fac.submit_payload(), stranger_headers
    )
    wrong_liaison = api.create_subprocessor(
        fac.subprocessor_payload(
            first_vendor["id"],
            name="Northgate Data Warehouse",
            country_code="US",
            data_categories=[ELEMENT_STUDENT_NAME],
            purpose=WAREHOUSE_PURPOSE,
            sub_breach_notification_hours=24,
        ),
        make_vendor_liaison_headers(second_vendor["id"]),
    )

    validate_error(stranger_read, ERR_NOT_RESOURCE_OWNER, 403)
    validate_error(stranger_submit, ERR_NOT_RESOURCE_OWNER, 403)
    validate_error(wrong_liaison, ERR_NOT_RESOURCE_OWNER, 403)
    _rows, meta = validate_paginated(
        api.list_subprocessors(ADMIN_HEADERS, vendor_id=first_vendor["id"])
    )
    assert_integer_equals(meta["total_count"], 0, "subprocessor total_count")
    untouched = fx.read_request(api, request["id"], filer_headers)
    assert untouched["status"] == REQUEST_DRAFT, (
        f"The refusals must leave the draft alone, got {untouched['status']}"
    )
    assert untouched["submitted_at"] is None, (
        f"submitted_at must still be null, got {untouched['submitted_at']!r}"
    )

    owner_submit = fx.submit_request(api, request["id"], filer_headers)

    assert owner_submit["status"] == REQUEST_SUBMITTED, (
        f"The rightful owner is unaffected, got {owner_submit['status']}"
    )


def test_a_blank_identity_header_is_401_before_the_row_is_ever_looked_up(api):
    """The unknown id would be a 404, but authentication runs first.

    PRD: "If either header is absent, empty, or contains only whitespace, the
    request is rejected with `ERR_UNAUTHENTICATED` (HTTP 401) before any other
    processing occurs."

    Design: Corner/rbac/missing_identity_headers_are_401_before_any_row_lookup
    """
    fx.set_clock(api)

    unauthenticated = api.get_vendor(UNKNOWN_UUID, make_blank_identity_headers())
    authenticated = api.get_vendor(UNKNOWN_UUID, ADMIN_HEADERS)

    blank_body = validate_error(unauthenticated, ERR_UNAUTHENTICATED, 401)
    assert blank_body["message"].strip(), "The 401 must carry a message"
    known_body = validate_error(authenticated, ERR_VENDOR_NOT_FOUND, 404)
    assert known_body["message"].strip(), "The 404 must carry a message"
    for response in (unauthenticated, authenticated):
        assert response.json()["response_type"] == "error", (
            f"Expected the error envelope, got {response.json()['response_type']}"
        )


# ---------------------------------------------------------------------------
# The three segregation-of-duties limbs
# ---------------------------------------------------------------------------


def test_review_decide_needs_a_lead_who_is_not_the_assignee(api):
    """Both limbs are independently fatal, even for a LEAD assignee.

    PRD: "A review is closed by a `PrivacyAnalyst` whose stored
    `credential_level` is `LEAD` and who is **not** the review's
    `assigned_analyst_id`; a non-lead, or the assignee themself, is refused with
    `ERR_SEGREGATION_OF_DUTIES`."

    Design: Corner/rbac/review_decide_needs_a_lead_who_is_not_the_assignee
    """
    chain = _decidable_review(
        api,
        attest=False,
        assignee_level=CREDENTIAL_LEAD,
        decider_level=CREDENTIAL_LEAD,
        independent_level=CREDENTIAL_SENIOR,
    )

    lead_assignee = api.decide_review(
        chain.review_id,
        fac.decision_payload(
            DECISION_CLEAR, decision_note="Assignee deciding own review."
        ),
        chain.assignee_headers,
    )
    senior_outsider = api.decide_review(
        chain.review_id,
        fac.decision_payload(DECISION_CLEAR, decision_note="Senior analyst deciding."),
        chain.independent_headers,
    )

    validate_error(lead_assignee, ERR_SEGREGATION_OF_DUTIES, 403)
    validate_error(senior_outsider, ERR_SEGREGATION_OF_DUTIES, 403)
    undecided = fx.read_review(api, chain.review_id)
    assert undecided["status"] == REVIEW_FINDINGS_ISSUED, (
        f"Expected FINDINGS_ISSUED, got {undecided['status']}"
    )
    assert undecided["decided_by_analyst_id"] is None, (
        f"Nobody decided it, got {undecided['decided_by_analyst_id']!r}"
    )

    decided = fx.decide_review(
        api,
        chain.review_id,
        DECISION_CLEAR,
        chain.decider_headers,
        decision_note="Independent lead review sign-off.",
    )

    assert decided["status"] == REVIEW_CLEARED, (
        f"Expected CLEARED, got {decided['status']}"
    )
    assert decided["decided_by_analyst_id"] == chain.decider_id, (
        f"Expected {chain.decider_id}, got {decided['decided_by_analyst_id']!r}"
    )
    assert_decimal_equals(
        decided["final_compliance_score"], "55.00", "final_compliance_score"
    )
    app = fx.read_application(api, chain.application_id)
    assert app["status"] == APPLICATION_APPROVED, (
        f"Expected APPROVED, got {app['status']}"
    )
    request = fx.read_request(api, chain.request_id)
    assert request["status"] == REQUEST_CLOSED_APPROVED, (
        f"Expected CLOSED_APPROVED, got {request['status']}"
    )
    assignee = fx.read_analyst(api, chain.assignee_id)
    assert_integer_equals(
        assignee["allocated_review_minutes"], 0, "allocated_review_minutes"
    )


def test_commitment_decide_is_refused_to_the_reviews_own_analyst(api):
    """The weaker limb: a different analyst suffices, LEAD is not required.

    PRD: "Dispositioning a commitment is an analyst's act and is the
    segregation-of-duties boundary of this workflow: the analyst assigned to the
    review proposes and organizes the commitments, and a **different** analyst
    accepts or rejects them. An acting analyst whose identifier equals the
    review's `assigned_analyst_id` is refused with `ERR_SEGREGATION_OF_DUTIES`."

    Design: Corner/rbac/commitment_decide_is_refused_to_the_reviews_own_analyst
    """
    chain = fx.screening_review_chain(
        api,
        vendor={"legal_name": "Brightpath Reading Co"},
        application={
            "name": "Brightpath Readers",
            "category": CATEGORY_ASSESSMENT,
            "grade_band_low": 6,
            "grade_band_high": 8,
            "sso_protocol": SSO_LTI13,
            "accessibility_conformance_level": ACCESSIBILITY_WCAG21_AA,
            "vpat_on_file": True,
        },
        teacher={"school_code": "MS-04", "grade_bands_taught": [6, 7, 8]},
        request={
            "requested_data_elements": [ELEMENT_STUDENT_NAME],
            "grade_band_low": 6,
            "grade_band_high": 8,
            "student_count_estimate": 300,
        },
        review={"estimated_minutes": 180},
        assignee_level=CREDENTIAL_SENIOR,
        assignee_capacity=2400,
        independent_level=CREDENTIAL_SENIOR,
    )
    commitment = fx.propose_commitment(
        api,
        chain.review_id,
        ELEMENT_STUDENT_NAME,
        chain.liaison_headers,
        justified_purpose=PURPOSE_61,
        retention_days=365,
        deletion_method=ANONYMIZE,
    )

    own_analyst = api.decide_commitment(
        commitment["id"],
        fac.commitment_decision_payload(DISPOSITION_ACCEPT),
        chain.assignee_headers,
    )

    validate_error(own_analyst, ERR_SEGREGATION_OF_DUTIES, 403)
    still_proposed = fx.read_commitment(api, commitment["id"])
    assert still_proposed["status"] == COMMITMENT_PROPOSED, (
        f"Expected PROPOSED, got {still_proposed['status']}"
    )
    assert still_proposed["decided_by_analyst_id"] is None, (
        f"Nobody decided it, got {still_proposed['decided_by_analyst_id']!r}"
    )
    assert_decimal_equals(
        fx.read_application(api, chain.application_id)["exposed_sensitivity_points"],
        "0.00",
        "exposed_sensitivity_points before the accept",
    )

    accepted = fx.decide_commitment(
        api, commitment["id"], DISPOSITION_ACCEPT, chain.independent_headers
    )

    assert accepted["status"] == COMMITMENT_ACCEPTED, (
        f"A SENIOR credential is sufficient here, got {accepted['status']}"
    )
    assert accepted["decided_by_analyst_id"] == chain.independent_id, (
        f"Expected {chain.independent_id}, got {accepted['decided_by_analyst_id']!r}"
    )
    assert_decimal_equals(
        fx.read_application(api, chain.application_id)["exposed_sensitivity_points"],
        "1.44",
        "exposed_sensitivity_points",
    )
    assert_decimal_equals(
        fx.read_vendor(api, chain.vendor_id)["risk_score"], "0.72", "risk_score"
    )


def test_the_analyst_who_decided_the_review_may_not_publish_it(api):
    """The publication limb reads `decided_by_analyst_id`, not the assignment.

    PRD: "When a `PrivacyAnalyst` publishes, they must not be the analyst
    recorded as that review's `decided_by_analyst_id` — the analyst who decided a
    review does not also publish it — and a violation is
    `ERR_SEGREGATION_OF_DUTIES`."

    Design: Corner/rbac/publishing_analyst_must_not_be_the_analyst_who_decided_the_review
    """
    chain = _decidable_review(
        api, assignee_level=CREDENTIAL_SENIOR, decider_level=CREDENTIAL_LEAD
    )
    decided = fx.decide_review(
        api,
        chain.review_id,
        DECISION_CLEAR,
        chain.decider_headers,
        decision_note="Independent lead sign-off.",
    )
    assert decided["decided_by_analyst_id"] == chain.decider_id, (
        f"Expected {chain.decider_id}, got {decided['decided_by_analyst_id']!r}"
    )
    window = fac.catalog_entry_payload(
        chain.application_id,
        chain.review_id,
        FIRST_EFFECTIVE_FROM,
        FIRST_EXPIRY,
        authorized_grade_band_low=3,
        authorized_grade_band_high=5,
    )

    by_the_decider = api.create_catalog_entry(window, chain.decider_headers)

    validate_error(by_the_decider, ERR_SEGREGATION_OF_DUTIES, 403)
    _rows, meta = validate_paginated(
        api.list_catalog_entries(ADMIN_HEADERS, review_id=chain.review_id)
    )
    assert_integer_equals(meta["total_count"], 0, "catalog entry total_count")
    assert (
        fx.read_application(api, chain.application_id)["catalog_visibility"]
        == VISIBILITY_HIDDEN
    ), "The refused publication must leave the product hidden"

    entry = fx.publish_entry(
        api,
        chain.application_id,
        chain.review_id,
        FIRST_EFFECTIVE_FROM,
        FIRST_EXPIRY,
        headers=chain.assignee_headers,
        authorized_grade_band_low=3,
        authorized_grade_band_high=5,
    )

    assert entry["status"] == ENTRY_PUBLISHED, (
        f"Expected PUBLISHED, got {entry['status']}"
    )
    assert_decimal_equals(
        entry["published_review_score"], "60.00", "published_review_score"
    )
    assert_instant_equals(
        entry["reauthorization_due_at"],
        "2027-07-02T00:00:00.000Z",
        "reauthorization_due_at",
    )
    assert (
        fx.read_application(api, chain.application_id)["catalog_visibility"]
        == VISIBILITY_VISIBLE
    ), "The product must become visible once it is published"
