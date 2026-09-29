"""Which of two simultaneously broken rules answers first, and what happens on
the exact instant or count where a threshold flips.
"""

from test_helpers import (
    ADMIN_HEADERS,
    assert_decimal_equals,
    assert_instant_equals,
    assert_integer_equals,
    fixtures as fx,
    make_analyst_headers,
    make_teacher_headers,
    validate_error,
    validate_paginated,
    validate_success,
)
from test_helpers.api_errors import (
    ERR_ANALYST_CAPACITY_EXCEEDED,
    ERR_AUTHORIZATION_WINDOW_OVERLAP,
    ERR_REQUEST_NOT_TRIAGED,
    ERR_VENDOR_POSTURE_BLOCKS_PUBLICATION,
)
from test_helpers.constants import (
    ACCESSIBILITY_WCAG21_AA,
    ALL_FRAMEWORKS,
    ANONYMIZE,
    CATEGORY_ASSESSMENT,
    CATEGORY_INSTRUCTIONAL_CONTENT,
    CLASSIFICATION_AUTHORIZED,
    CLASSIFICATION_EXPIRED_AUTHORIZATION,
    CREDENTIAL_LEAD,
    CREDENTIAL_SENIOR,
    DECISION_CLEAR,
    DETECTION_NEW,
    DISPOSITION_ACCEPT,
    DISPOSITION_FLAG,
    DISPOSITION_REMOVE,
    ELEMENT_STUDENT_NAME,
    ENTRY_PUBLISHED,
    FRAMEWORK_COPPA,
    FRAMEWORK_FERPA,
    INCIDENT_UNAUTHORIZED_DISCLOSURE,
    JUST_240,
    NOTIFICATION_PENDING,
    POSTURE_CLEAR,
    POSTURE_FROZEN,
    POSTURE_RESTRICTED,
    PURPOSE_61,
    REQUEST_TRIAGED_FOR_REVIEW,
    SEVERITY_CRITICAL,
    SEVERITY_HIGH,
    SOURCE_BROWSER_EXTENSION,
    SOURCE_NETWORK_DNS,
    SSO_SAML2,
    SUBPROCESSOR_REMOVED,
    TRIAGE_ACCEPT_FOR_REVIEW,
    VISIBILITY_VISIBLE,
)
from test_helpers.factories import review_payload

OVERSIZED_REVIEW_MINUTES = 600
TINY_ANALYST_CAPACITY = 100


# ---------------------------------------------------------------------------
# Shared chains
# ---------------------------------------------------------------------------


def _untriaged_request_and_a_tiny_capacity_analyst(api):
    """A SUBMITTED request plus an analyst too small for the review it will get."""
    fx.set_clock(api)
    vendor = fx.register_vendor(
        api,
        legal_name="Meridian Practice Labs",
        breach_notification_hours=48,
        signed_state_addendum=True,
        subprocessor_disclosure_complete=True,
    )
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
    teacher = fx.enroll_teacher(api, full_name="Dana Reyes", employee_number="EMP-7012")
    teacher_headers = make_teacher_headers(teacher["id"])
    analyst = fx.enroll_analyst(
        api, CREDENTIAL_SENIOR, review_capacity_minutes=TINY_ANALYST_CAPACITY
    )
    analyst_headers = make_analyst_headers(analyst["id"])
    request = fx.draft_request(
        api,
        app["id"],
        teacher["id"],
        teacher_headers,
        instructional_justification=JUST_240,
        requested_data_elements=[ELEMENT_STUDENT_NAME],
        student_count_estimate=700,
        grade_band_low=7,
        grade_band_high=8,
    )
    fx.submit_request(api, request["id"], teacher_headers)
    body = review_payload(
        request["id"],
        analyst["id"],
        framework_set=[FRAMEWORK_FERPA, FRAMEWORK_COPPA],
        estimated_minutes=OVERSIZED_REVIEW_MINUTES,
    )
    return {
        "analyst_id": analyst["id"],
        "analyst_headers": analyst_headers,
        "request_id": request["id"],
        "review_body": body,
    }


def _published_entry_on_a_vendor_with_a_flagged_subprocessor(api):
    """A live entry, a RESTRICTED posture, and an overlapping window ready to file."""
    fx.set_clock(api)
    vendor = fx.register_vendor(
        api,
        legal_name="Brightpath Reading Co",
        breach_notification_hours=48,
        signed_state_addendum=True,
        subprocessor_disclosure_complete=True,
    )
    subprocessor = fx.disclose_subprocessor(
        api,
        vendor["id"],
        name="Cedar Analytics LLC",
        country_code="US",
        data_categories=[ELEMENT_STUDENT_NAME],
        purpose="Product usage analytics for the district tenant only.",
        sub_breach_notification_hours=24,
    )
    app = fx.register_application(
        api,
        vendor["id"],
        name="Brightpath Readers",
        category=CATEGORY_INSTRUCTIONAL_CONTENT,
        grade_band_low=3,
        grade_band_high=5,
        sso_protocol=SSO_SAML2,
        accessibility_conformance_level=ACCESSIBILITY_WCAG21_AA,
        vpat_on_file=True,
    )
    fx.attest_integration(api, app["id"], sso_verified=True)
    teacher = fx.enroll_teacher(
        api,
        full_name="Ivy Chen",
        employee_number="EMP-7013",
        school_code="ES-11",
        grade_bands_taught=[3, 4, 5],
    )
    teacher_headers = make_teacher_headers(teacher["id"])
    assignee = fx.enroll_analyst(api, CREDENTIAL_SENIOR, review_capacity_minutes=2400)
    decider = fx.enroll_analyst(api, CREDENTIAL_LEAD, review_capacity_minutes=2400)
    assignee_headers = make_analyst_headers(assignee["id"])
    decider_headers = make_analyst_headers(decider["id"])

    request = fx.draft_request(
        api,
        app["id"],
        teacher["id"],
        teacher_headers,
        instructional_justification=JUST_240,
        requested_data_elements=[ELEMENT_STUDENT_NAME],
        student_count_estimate=300,
        grade_band_low=3,
        grade_band_high=5,
    )
    fx.submit_request(api, request["id"], teacher_headers)
    fx.triage_request(api, request["id"], TRIAGE_ACCEPT_FOR_REVIEW, assignee_headers)
    review = fx.open_review(
        api,
        request["id"],
        assignee["id"],
        assignee_headers,
        framework_set=list(ALL_FRAMEWORKS),
        estimated_minutes=180,
    )
    commitment = fx.propose_commitment(
        api,
        review["id"],
        ELEMENT_STUDENT_NAME,
        assignee_headers,
        justified_purpose=PURPOSE_61,
        retention_days=365,
        deletion_method=ANONYMIZE,
    )
    fx.decide_commitment(api, commitment["id"], DISPOSITION_ACCEPT, decider_headers)
    fx.issue_findings(
        api, review["id"], 0, assignee_headers, decision_note="No open findings."
    )
    fx.decide_review(
        api,
        review["id"],
        DECISION_CLEAR,
        decider_headers,
        decision_note="Cleared for publication.",
    )
    entry = fx.publish_entry(
        api,
        app["id"],
        review["id"],
        "2026-08-01T00:00:00Z",
        "2026-10-01T00:00:00Z",
        authorized_grade_band_low=3,
        authorized_grade_band_high=5,
    )
    fx.review_subprocessor(
        api,
        subprocessor["id"],
        DISPOSITION_FLAG,
        assignee_headers,
        reviewed_note="Undisclosed secondary use of telemetry.",
    )
    overlapping_body = {
        "application_id": app["id"],
        "review_id": review["id"],
        "effective_from": "2026-09-01T00:00:00Z",
        "expires_at": "2026-11-01T00:00:00Z",
        "authorized_grade_band_low": 3,
        "authorized_grade_band_high": 5,
    }
    return {
        "vendor_id": vendor["id"],
        "application_id": app["id"],
        "subprocessor_id": subprocessor["id"],
        "analyst_headers": assignee_headers,
        "entry_id": entry["id"],
        "overlapping_body": overlapping_body,
    }


def _three_vendors_awaiting_a_boundary_incident(api):
    """Three fresh vendors, so the incident buffer never sees a sibling row."""
    fx.set_clock(api)
    names = ("Boundary Vendor One", "Boundary Vendor Two", "Boundary Vendor Three")
    return [
        fx.register_vendor(
            api,
            legal_name=name,
            breach_notification_hours=48,
            signed_state_addendum=True,
            subprocessor_disclosure_complete=True,
        )["id"]
        for name in names
    ]


def _entry_published_over_august_then_clock_in_september(api):
    """A PUBLISHED window of [2026-08-01, 2026-09-01) observed from 2026-09-02."""
    fx.set_clock(api)
    vendor = fx.register_vendor(
        api,
        legal_name="Brightpath Reading Co",
        breach_notification_hours=48,
        signed_state_addendum=True,
        subprocessor_disclosure_complete=True,
    )
    app = fx.register_application(
        api,
        vendor["id"],
        name="Brightpath Readers",
        category=CATEGORY_INSTRUCTIONAL_CONTENT,
        grade_band_low=3,
        grade_band_high=5,
        sso_protocol=SSO_SAML2,
        accessibility_conformance_level=ACCESSIBILITY_WCAG21_AA,
        vpat_on_file=True,
    )
    fx.attest_integration(api, app["id"], sso_verified=True)
    teacher = fx.enroll_teacher(
        api,
        full_name="Ivy Chen",
        employee_number="EMP-7020",
        school_code="ES-11",
        grade_bands_taught=[3, 4, 5],
    )
    teacher_headers = make_teacher_headers(teacher["id"])
    assignee = fx.enroll_analyst(api, CREDENTIAL_SENIOR, review_capacity_minutes=2400)
    decider = fx.enroll_analyst(api, CREDENTIAL_LEAD, review_capacity_minutes=2400)
    assignee_headers = make_analyst_headers(assignee["id"])
    decider_headers = make_analyst_headers(decider["id"])

    request = fx.draft_request(
        api,
        app["id"],
        teacher["id"],
        teacher_headers,
        instructional_justification=JUST_240,
        requested_data_elements=[ELEMENT_STUDENT_NAME],
        student_count_estimate=300,
        grade_band_low=3,
        grade_band_high=5,
    )
    fx.submit_request(api, request["id"], teacher_headers)
    fx.triage_request(api, request["id"], TRIAGE_ACCEPT_FOR_REVIEW, assignee_headers)
    review = fx.open_review(
        api,
        request["id"],
        assignee["id"],
        assignee_headers,
        framework_set=list(ALL_FRAMEWORKS),
        estimated_minutes=180,
    )
    commitment = fx.propose_commitment(
        api,
        review["id"],
        ELEMENT_STUDENT_NAME,
        assignee_headers,
        justified_purpose=PURPOSE_61,
        retention_days=365,
        deletion_method=ANONYMIZE,
    )
    fx.decide_commitment(api, commitment["id"], DISPOSITION_ACCEPT, decider_headers)
    fx.issue_findings(
        api, review["id"], 0, assignee_headers, decision_note="No open findings."
    )
    fx.decide_review(
        api,
        review["id"],
        DECISION_CLEAR,
        decider_headers,
        decision_note="Cleared for publication.",
    )
    entry = fx.publish_entry(
        api,
        app["id"],
        review["id"],
        "2026-08-01T00:00:00Z",
        "2026-09-01T00:00:00Z",
        authorized_grade_band_low=3,
        authorized_grade_band_high=5,
    )
    fx.set_clock(api, "2026-09-02T00:00:00Z")
    return {"application_id": app["id"], "entry_id": entry["id"]}


# ---------------------------------------------------------------------------
# Ladder order: state gate before fiscal gate
# ---------------------------------------------------------------------------


def test_untriaged_source_request_answers_before_analyst_capacity(api):
    """Both rungs are broken; the earlier state rung must answer.

    PRD: "The request named as a review's source has been triaged for review —
    otherwise `ERR_REQUEST_NOT_TRIAGED`."

    Design: Difficulty/priority_pair_validation_conflict/review_open_state_gate_beats_analyst_capacity
    """
    ctx = _untriaged_request_and_a_tiny_capacity_analyst(api)

    response = api.create_review(ctx["review_body"], ctx["analyst_headers"])

    validate_error(response, ERR_REQUEST_NOT_TRIAGED, 409)
    rows, meta = validate_paginated(
        api.list_reviews(ADMIN_HEADERS, source_request_id=ctx["request_id"])
    )
    assert_integer_equals(meta["total_count"], 0, "total_count")
    assert rows == [], "A refused create must leave no review behind"


def test_capacity_gate_is_reached_once_the_state_gate_is_satisfied(api):
    """The identical body now reports the capacity refusal, proving the order.

    PRD: "Analyst capacity, checked last of all — otherwise
    `ERR_ANALYST_CAPACITY_EXCEEDED`."

    Design: Difficulty/priority_pair_validation_conflict/review_open_state_gate_beats_analyst_capacity
    """
    ctx = _untriaged_request_and_a_tiny_capacity_analyst(api)
    api.create_review(ctx["review_body"], ctx["analyst_headers"])

    fx.triage_request(
        api, ctx["request_id"], TRIAGE_ACCEPT_FOR_REVIEW, ctx["analyst_headers"]
    )
    response = api.create_review(ctx["review_body"], ctx["analyst_headers"])

    validate_error(response, ERR_ANALYST_CAPACITY_EXCEEDED, 409)
    request = fx.read_request(api, ctx["request_id"])
    assert request["status"] == REQUEST_TRIAGED_FOR_REVIEW, (
        f"Expected TRIAGED_FOR_REVIEW, got {request['status']}"
    )
    analyst = fx.read_analyst(api, ctx["analyst_id"])
    assert_integer_equals(
        analyst["allocated_review_minutes"], 0, "allocated_review_minutes"
    )


# ---------------------------------------------------------------------------
# Ladder order: posture safety before window overlap
# ---------------------------------------------------------------------------


def test_restricted_posture_answers_before_the_overlapping_window(api):
    """A flagged subprocessor blocks publication before the window is even compared.

    PRD: "Publication is gated more tightly still: it additionally requires the
    posture to be `CLEAR` or `WATCH`, so a `RESTRICTED` vendor is refused with
    `ERR_VENDOR_POSTURE_BLOCKS_PUBLICATION` even though it is not frozen."

    Design: Difficulty/priority_pair_validation_conflict/publication_posture_safety_beats_window_overlap
    """
    ctx = _published_entry_on_a_vendor_with_a_flagged_subprocessor(api)

    response = api.create_catalog_entry(ctx["overlapping_body"], ADMIN_HEADERS)

    validate_error(response, ERR_VENDOR_POSTURE_BLOCKS_PUBLICATION, 409)
    vendor = fx.read_vendor(api, ctx["vendor_id"])
    assert vendor["privacy_posture"] == POSTURE_RESTRICTED, (
        f"One flagged subprocessor is RESTRICTED, got {vendor['privacy_posture']}"
    )


def test_window_overlap_surfaces_once_the_posture_clears(api):
    """Removing the flagged subprocessor exposes the temporal rule underneath.

    PRD: "The vendor's posture permits publication — otherwise
    `ERR_VENDOR_POSTURE_BLOCKS_PUBLICATION`."

    Design: Difficulty/priority_pair_validation_conflict/publication_posture_safety_beats_window_overlap
    """
    ctx = _published_entry_on_a_vendor_with_a_flagged_subprocessor(api)
    api.create_catalog_entry(ctx["overlapping_body"], ADMIN_HEADERS)

    fx.review_subprocessor(
        api,
        ctx["subprocessor_id"],
        DISPOSITION_REMOVE,
        ctx["analyst_headers"],
        reviewed_note="Subprocessor contract terminated.",
    )
    response = api.create_catalog_entry(ctx["overlapping_body"], ADMIN_HEADERS)

    validate_error(response, ERR_AUTHORIZATION_WINDOW_OVERLAP, 409)
    subprocessor = validate_success(api.get_subprocessor(ctx["subprocessor_id"], ADMIN_HEADERS))
    assert subprocessor["status"] == SUBPROCESSOR_REMOVED, (
        f"Expected REMOVED, got {subprocessor['status']}"
    )
    vendor = fx.read_vendor(api, ctx["vendor_id"])
    assert_integer_equals(
        vendor["flagged_subprocessor_count"], 0, "flagged_subprocessor_count"
    )
    assert_decimal_equals(vendor["risk_score"], "0.72", "risk_score")
    assert vendor["privacy_posture"] == POSTURE_CLEAR, (
        f"Expected CLEAR, got {vendor['privacy_posture']}"
    )
    entry = fx.read_entry(api, ctx["entry_id"])
    assert entry["status"] == ENTRY_PUBLISHED, (
        f"The live entry is untouched by two refusals, got {entry['status']}"
    )
    _, meta = validate_paginated(
        api.list_catalog_entries(ADMIN_HEADERS, application_id=ctx["application_id"])
    )
    assert_integer_equals(meta["total_count"], 1, "total_count")
    app = fx.read_application(api, ctx["application_id"])
    assert app["catalog_visibility"] == VISIBILITY_VISIBLE, (
        f"Expected VISIBLE, got {app['catalog_visibility']}"
    )


# ---------------------------------------------------------------------------
# Boundary: the severity ladder at exactly 1000 students
# ---------------------------------------------------------------------------


def test_severity_count_door_is_inclusive_at_one_thousand_students(api):
    """1000 is CRITICAL and 999 at tier 2 is only HIGH.

    PRD: "Every comparison is inclusive, so exactly 1000 affected students is
    `CRITICAL` and 999 with a `max_data_tier` of 3 or less is `HIGH`."

    Design: Difficulty/boundary_precision_check/incident_severity_at_exactly_1000_affected_students
    """
    first, second, _third = _three_vendors_awaiting_a_boundary_incident(api)

    at_boundary = fx.report_incident(
        api,
        first,
        "2026-08-01T00:00:00Z",
        incident_type=INCIDENT_UNAUTHORIZED_DISCLOSURE,
        affected_student_count=1000,
        max_data_tier=2,
    )
    below_boundary = fx.report_incident(
        api,
        second,
        "2026-08-01T00:00:00Z",
        incident_type=INCIDENT_UNAUTHORIZED_DISCLOSURE,
        affected_student_count=999,
        max_data_tier=2,
    )

    assert at_boundary["severity"] == SEVERITY_CRITICAL, (
        f"Exactly 1000 is CRITICAL, got {at_boundary['severity']}"
    )
    assert below_boundary["severity"] == SEVERITY_HIGH, (
        f"999 at tier 2 is HIGH, got {below_boundary['severity']}"
    )
    assert_decimal_equals(
        fx.read_vendor(api, first)["risk_score"], "30.00", "risk_score"
    )
    assert fx.read_vendor(api, first)["privacy_posture"] == POSTURE_FROZEN, (
        "A CRITICAL incident still in REPORTED freezes the vendor"
    )
    assert_decimal_equals(
        fx.read_vendor(api, second)["risk_score"], "18.00", "risk_score"
    )
    assert fx.read_vendor(api, second)["privacy_posture"] == POSTURE_RESTRICTED, (
        "A HIGH incident in REPORTED only restricts the vendor"
    )


def test_severity_drives_the_statutory_ceiling_in_the_notification_deadline(api):
    """The same boundary is visible a second time in notification_due_at.

    PRD: "The effective allowance is the **minimum** of the vendor's contractual
    `breach_notification_hours` and that statutory ceiling — never the maximum —
    and `notification_due_at` is `detected_at` plus the effective allowance."

    Design: Difficulty/boundary_precision_check/incident_severity_at_exactly_1000_affected_students
    """
    first, second, third = _three_vendors_awaiting_a_boundary_incident(api)

    at_boundary = fx.report_incident(
        api,
        first,
        "2026-08-01T00:00:00Z",
        incident_type=INCIDENT_UNAUTHORIZED_DISCLOSURE,
        affected_student_count=1000,
        max_data_tier=2,
    )
    below_boundary = fx.report_incident(
        api,
        second,
        "2026-08-01T00:00:00Z",
        incident_type=INCIDENT_UNAUTHORIZED_DISCLOSURE,
        affected_student_count=999,
        max_data_tier=2,
    )
    by_tier = fx.report_incident(
        api,
        third,
        "2026-08-01T00:00:00Z",
        incident_type=INCIDENT_UNAUTHORIZED_DISCLOSURE,
        affected_student_count=999,
        max_data_tier=4,
    )

    assert_instant_equals(
        at_boundary["notification_due_at"],
        "2026-08-02T00:00:00.000Z",
        "notification_due_at",
    )
    assert_instant_equals(
        below_boundary["notification_due_at"],
        "2026-08-03T00:00:00.000Z",
        "notification_due_at",
    )
    assert by_tier["severity"] == SEVERITY_CRITICAL, (
        f"A tier-4 incident is CRITICAL regardless of volume, got {by_tier['severity']}"
    )
    assert_instant_equals(
        by_tier["notification_due_at"],
        "2026-08-02T00:00:00.000Z",
        "notification_due_at",
    )
    assert fx.read_vendor(api, third)["privacy_posture"] == POSTURE_FROZEN, (
        "The tier disjunct freezes the vendor just as the count disjunct does"
    )
    assert below_boundary["notification_status"] == NOTIFICATION_PENDING, (
        "Reporting an incident never sends its notification"
    )


# ---------------------------------------------------------------------------
# Boundary: the half-open catalog window at the expiry instant
# ---------------------------------------------------------------------------


def test_observation_one_second_before_expiry_is_still_authorized(api):
    """The last authorized instant is expires_at minus one second.

    PRD: "an observation landing exactly on an entry's `expires_at` is outside
    that window and falls through to branch 3, where that very same entry
    becomes the match — the boundary instant flips a detection from
    `AUTHORIZED` to `EXPIRED_AUTHORIZATION` while keeping the same
    `matched_catalog_entry_id`."

    Design: Difficulty/boundary_precision_check/detection_window_half_open_at_exact_expiry_instant
    """
    ctx = _entry_published_over_august_then_clock_in_september(api)

    inside = fx.observe_detection(
        api,
        "app.brightpathreaders.com",
        "2026-08-31T23:59:59Z",
        ctx["application_id"],
        school_code="ES-11",
        source=SOURCE_NETWORK_DNS,
        distinct_user_count=30,
        session_count=120,
    )
    on_expiry = fx.observe_detection(
        api,
        "app.brightpathreaders.com",
        "2026-09-01T00:00:00Z",
        ctx["application_id"],
        school_code="ES-11",
        source=SOURCE_NETWORK_DNS,
        distinct_user_count=30,
        session_count=120,
    )

    assert inside["classification"] == CLASSIFICATION_AUTHORIZED, (
        f"One second before expiry is AUTHORIZED, got {inside['classification']}"
    )
    assert inside["matched_catalog_entry_id"] == ctx["entry_id"], (
        "The matched entry must be the published window"
    )
    assert on_expiry["classification"] == CLASSIFICATION_EXPIRED_AUTHORIZATION, (
        f"The expiry instant is outside the window, got {on_expiry['classification']}"
    )
    assert on_expiry["matched_catalog_entry_id"] == ctx["entry_id"], (
        "The same entry is still the match on the far side of the boundary"
    )


def test_classification_base_shifts_the_exposure_score_by_twenty_five(api):
    """The boundary flip is visible as an 18.00 to 43.00 jump, and effective_from is inside.

    PRD: "plus a base that depends entirely on the classification just assigned
    — 0 for `AUTHORIZED`, 25 for `EXPIRED_AUTHORIZATION`, 45 for `UNAUTHORIZED`
    and 30 for `UNKNOWN_DOMAIN`."

    Design: Difficulty/boundary_precision_check/detection_window_half_open_at_exact_expiry_instant
    """
    ctx = _entry_published_over_august_then_clock_in_september(api)

    inside = fx.observe_detection(
        api,
        "app.brightpathreaders.com",
        "2026-08-31T23:59:59Z",
        ctx["application_id"],
        school_code="ES-11",
        source=SOURCE_NETWORK_DNS,
        distinct_user_count=30,
        session_count=120,
    )
    on_expiry = fx.observe_detection(
        api,
        "app.brightpathreaders.com",
        "2026-09-01T00:00:00Z",
        ctx["application_id"],
        school_code="ES-11",
        source=SOURCE_NETWORK_DNS,
        distinct_user_count=30,
        session_count=120,
    )
    on_effective_from = fx.observe_detection(
        api,
        "app.brightpathreaders.com",
        "2026-08-01T00:00:00Z",
        ctx["application_id"],
        school_code="ES-11",
        source=SOURCE_BROWSER_EXTENSION,
        distinct_user_count=30,
        session_count=120,
    )

    assert_decimal_equals(inside["exposure_score"], "18.00", "exposure_score")
    assert_decimal_equals(on_expiry["exposure_score"], "43.00", "exposure_score")
    assert on_effective_from["classification"] == CLASSIFICATION_AUTHORIZED, (
        "effective_from itself is inside the half-open window, got "
        f"{on_effective_from['classification']}"
    )
    assert_decimal_equals(
        on_effective_from["exposure_score"], "18.00", "exposure_score"
    )
    assert on_effective_from["status"] == DETECTION_NEW, (
        f"A fresh detection opens in NEW, got {on_effective_from['status']}"
    )
    entry = fx.read_entry(api, ctx["entry_id"])
    assert entry["status"] == ENTRY_PUBLISHED, (
        "No sweep was run, so the entry is still PUBLISHED"
    )
