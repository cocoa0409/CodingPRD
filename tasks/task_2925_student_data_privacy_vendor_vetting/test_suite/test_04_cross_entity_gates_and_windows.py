"""Writes whose legality is decided by a row several hops away, and the two
deliberately opposite interval conventions.
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
)
from test_helpers.api_errors import (
    ERR_AUTHORIZATION_WINDOW_OVERLAP,
    ERR_INCIDENT_WINDOW_BUFFER_CONFLICT,
    ERR_REVIEW_NOT_CLEARED,
    ERR_VENDOR_POSTURE_FROZEN,
)
from test_helpers.constants import (
    ACCESSIBILITY_WCAG21_AA,
    ALL_FRAMEWORKS,
    ANONYMIZE,
    APPLICATION_APPROVED,
    BAND_STANDARD,
    CATEGORY_ASSESSMENT,
    CATEGORY_INSTRUCTIONAL_CONTENT,
    CREDENTIAL_LEAD,
    CREDENTIAL_SENIOR,
    DECISION_CLEAR,
    DISPOSITION_ACCEPT,
    ELEMENT_STUDENT_NAME,
    ENTRY_PUBLISHED,
    INCIDENT_REMEDIATED,
    INCIDENT_REPORTED,
    INCIDENT_RETENTION_VIOLATION,
    INCIDENT_SUBPROCESSOR_CHANGE,
    INCIDENT_UNAUTHORIZED_DISCLOSURE,
    JUST_240,
    NOTIFICATION_PENDING,
    POSTURE_CLEAR,
    POSTURE_RESTRICTED,
    PURPOSE_61,
    REQUEST_DRAFT,
    REQUEST_SUBMITTED,
    RESOLVE_REMEDIATE,
    REVIEW_CLEARED,
    SEVERITY_CRITICAL,
    SEVERITY_LOW,
    SSO_SAML2,
    TRIAGE_ACCEPT_FOR_REVIEW,
    VISIBILITY_VISIBLE,
)


# ---------------------------------------------------------------------------
# Shared chains
# ---------------------------------------------------------------------------


def _draft_request_behind_a_frozen_vendor(api):
    """A DRAFT request whose vendor is frozen by an open CRITICAL incident."""
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
    teacher = fx.enroll_teacher(api, full_name="Dana Reyes", employee_number="EMP-7021")
    teacher_headers = make_teacher_headers(teacher["id"])
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
    incident = fx.report_incident(
        api,
        vendor["id"],
        "2026-08-01T00:00:00Z",
        incident_type=INCIDENT_UNAUTHORIZED_DISCLOSURE,
        affected_student_count=1500,
        max_data_tier=2,
    )
    return {
        "vendor_id": vendor["id"],
        "teacher_id": teacher["id"],
        "teacher_headers": teacher_headers,
        "request_id": request["id"],
        "incident_id": incident["id"],
    }


def _publishable_pair_with_a_review_in_findings_issued(api):
    """Everything a publication needs except a decided review."""
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
        employee_number="EMP-7022",
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
    publication_body = {
        "application_id": app["id"],
        "review_id": review["id"],
        "effective_from": "2026-08-01T00:00:00Z",
        "expires_at": "2026-10-01T00:00:00Z",
        "authorized_grade_band_low": 3,
        "authorized_grade_band_high": 5,
    }
    return {
        "application_id": app["id"],
        "review_id": review["id"],
        "decider_headers": decider_headers,
        "publication_body": publication_body,
    }


def _entry_published_over_august_and_september(api):
    """One PUBLISHED window of [2026-08-01, 2026-10-01) ready to be abutted."""
    ctx = _publishable_pair_with_a_review_in_findings_issued(api)
    fx.decide_review(
        api,
        ctx["review_id"],
        DECISION_CLEAR,
        ctx["decider_headers"],
        decision_note="Cleared for publication.",
    )
    entry = fx.publish_entry(
        api,
        ctx["application_id"],
        ctx["review_id"],
        "2026-08-01T00:00:00Z",
        "2026-10-01T00:00:00Z",
        authorized_grade_band_low=3,
        authorized_grade_band_high=5,
    )
    ctx["entry_id"] = entry["id"]
    return ctx


def _uncontained_incident_widened_to_august_eighth(api):
    """One uncontained LOW incident whose widened window ends at 2026-08-08T00:00:00Z."""
    fx.set_clock(api, "2026-08-02T00:00:00Z")
    vendor = fx.register_vendor(
        api,
        legal_name="Harborlight Media Inc",
        breach_notification_hours=48,
        signed_state_addendum=True,
        subprocessor_disclosure_complete=True,
    )
    incident = fx.report_incident(
        api,
        vendor["id"],
        "2026-08-02T00:00:00Z",
        incident_type=INCIDENT_RETENTION_VIOLATION,
        affected_student_count=5,
        max_data_tier=1,
    )
    fx.set_clock(api, "2026-08-09T00:00:00Z")
    return {"vendor_id": vendor["id"], "incident_id": incident["id"]}


# ---------------------------------------------------------------------------
# Frozen vendor, three hops away
# ---------------------------------------------------------------------------


def test_submission_is_refused_while_an_open_critical_incident_freezes_the_vendor(api):
    """The request itself is faultless; a row three hops away closes the door.

    PRD: "A frozen vendor is cut off from four operations, each rejected with
    `ERR_VENDOR_POSTURE_FROZEN`: submitting or resubmitting a teacher request
    for one of its applications, dispositioning one of its data-element
    commitments, publishing one of its applications to the catalog, and
    reauthorizing one of its catalog entries."

    Design: Difficulty/cross_entity_state_dependency/request_submit_blocked_by_frozen_vendor_posture
    """
    ctx = _draft_request_behind_a_frozen_vendor(api)

    response = api.submit_request(ctx["request_id"], {}, ctx["teacher_headers"])

    validate_error(response, ERR_VENDOR_POSTURE_FROZEN, 409)
    request = fx.read_request(api, ctx["request_id"])
    assert request["status"] == REQUEST_DRAFT, (
        f"A refused submission leaves the row in DRAFT, got {request['status']}"
    )
    assert request["submitted_at"] is None, (
        "A refused submission must not stamp submitted_at"
    )
    incident = fx.read_incident(api, ctx["incident_id"])
    assert incident["severity"] == SEVERITY_CRITICAL, (
        f"1500 affected students is CRITICAL, got {incident['severity']}"
    )


def test_remediating_the_incident_reopens_the_identical_submission(api):
    """Nothing about the request changed, yet the same call now succeeds.

    PRD: "`REMEDIATE` writes `response_status` `REMEDIATED` and then recomputes
    the vendor's `open_incident_count`, `risk_score` and `privacy_posture` in
    that order; because `REMEDIATED` leaves the open-incident set, this is the
    transition that can finally return a vendor's posture to `WATCH` or
    `CLEAR`."

    Design: Difficulty/cross_entity_state_dependency/request_submit_blocked_by_frozen_vendor_posture
    """
    ctx = _draft_request_behind_a_frozen_vendor(api)
    api.submit_request(ctx["request_id"], {}, ctx["teacher_headers"])

    fx.set_clock(api, "2026-08-01T06:00:00Z")
    fx.contain_incident(api, ctx["incident_id"], "2026-08-01T06:00:00Z")
    fx.resolve_incident(
        api,
        ctx["incident_id"],
        RESOLVE_REMEDIATE,
        remediation_note="Root cause fixed and records purged.",
    )
    submitted = fx.submit_request(api, ctx["request_id"], ctx["teacher_headers"])

    incident = fx.read_incident(api, ctx["incident_id"])
    assert incident["response_status"] == INCIDENT_REMEDIATED, (
        f"Expected REMEDIATED, got {incident['response_status']}"
    )
    assert incident["notification_status"] == NOTIFICATION_PENDING, (
        "The response axis never writes the notification axis"
    )
    vendor = fx.read_vendor(api, ctx["vendor_id"])
    assert_decimal_equals(vendor["risk_score"], "30.00", "risk_score")
    assert vendor["privacy_posture"] == POSTURE_CLEAR, (
        f"30.00 is below the WATCH threshold, got {vendor['privacy_posture']}"
    )
    assert submitted["status"] == REQUEST_SUBMITTED, (
        f"Expected SUBMITTED, got {submitted['status']}"
    )
    assert_decimal_equals(submitted["priority_score"], "60.50", "priority_score")
    assert submitted["priority_band"] == BAND_STANDARD, (
        f"Expected STANDARD, got {submitted['priority_band']}"
    )
    teacher = fx.read_teacher(api, ctx["teacher_id"])
    assert_integer_equals(teacher["open_request_count"], 1, "open_request_count")


# ---------------------------------------------------------------------------
# Publication waits on another entity's terminal state
# ---------------------------------------------------------------------------


def test_publication_is_refused_while_the_cited_review_is_undecided(api):
    """Every other publication gate passes; the review's state alone refuses.

    PRD: "The cited review must be in `CLEARED` or `CONDITIONAL` **and** its own
    `application_id` must equal the submitted `application_id`, or
    `ERR_REVIEW_NOT_CLEARED` — a decided review from a different product cannot
    be borrowed."

    Design: Difficulty/cross_entity_state_dependency/publication_blocked_until_review_reaches_cleared
    """
    ctx = _publishable_pair_with_a_review_in_findings_issued(api)

    response = api.create_catalog_entry(ctx["publication_body"], ADMIN_HEADERS)

    validate_error(response, ERR_REVIEW_NOT_CLEARED, 422)
    _, meta = validate_paginated(
        api.list_catalog_entries(ADMIN_HEADERS, application_id=ctx["application_id"])
    )
    assert_integer_equals(meta["total_count"], 0, "total_count")


def test_publication_snapshots_the_score_of_the_review_it_waited_for(api):
    """Once the LEAD decides, the same body publishes and freezes the score.

    PRD: "`published_review_score` is a snapshot of the cited review's
    `final_compliance_score` taken at publication and **never** refreshed
    afterwards, so a catalog entry keeps reporting the score the district saw when
    it authorized the product even if the review row were later re-read."

    Design: Difficulty/cross_entity_state_dependency/publication_blocked_until_review_reaches_cleared
    """
    ctx = _publishable_pair_with_a_review_in_findings_issued(api)
    api.create_catalog_entry(ctx["publication_body"], ADMIN_HEADERS)

    fx.decide_review(
        api,
        ctx["review_id"],
        DECISION_CLEAR,
        ctx["decider_headers"],
        decision_note="Cleared for publication.",
    )
    review = fx.read_review(api, ctx["review_id"])
    assert review["status"] == REVIEW_CLEARED, (
        f"Expected CLEARED, got {review['status']}"
    )
    assert_decimal_equals(
        review["final_compliance_score"], "100.00", "final_compliance_score"
    )

    entry = fx.publish_entry(
        api,
        ctx["application_id"],
        ctx["review_id"],
        "2026-08-01T00:00:00Z",
        "2026-10-01T00:00:00Z",
        authorized_grade_band_low=3,
        authorized_grade_band_high=5,
    )

    assert entry["status"] == ENTRY_PUBLISHED, (
        f"Expected PUBLISHED, got {entry['status']}"
    )
    assert_decimal_equals(
        entry["published_review_score"], "100.00", "published_review_score"
    )
    assert_instant_equals(
        entry["reauthorization_due_at"],
        "2026-09-01T00:00:00.000Z",
        "reauthorization_due_at",
    )
    assert entry["predecessor_entry_id"] is None, (
        "A first publication has no predecessor"
    )
    app = fx.read_application(api, ctx["application_id"])
    assert app["catalog_visibility"] == VISIBILITY_VISIBLE, (
        f"Expected VISIBLE, got {app['catalog_visibility']}"
    )
    assert app["status"] == APPLICATION_APPROVED, (
        f"Expected APPROVED, got {app['status']}"
    )


# ---------------------------------------------------------------------------
# Half-open catalog windows: adjacency is legal
# ---------------------------------------------------------------------------


def test_a_window_starting_exactly_where_the_last_one_ended_is_accepted(api):
    """Zero buffer plus a half-open interval makes exact adjacency legal.

    PRD: "Two windows of the same application conflict only if they genuinely
    overlap, so exact adjacency is legal — a new window whose `effective_from`
    equals an existing window's `expires_at` is accepted."

    Design: Difficulty/resource_temporal_overlap/catalog_window_adjacency_legal_one_second_overlap_rejected
    """
    ctx = _entry_published_over_august_and_september(api)

    successor = fx.publish_entry(
        api,
        ctx["application_id"],
        ctx["review_id"],
        "2026-10-01T00:00:00Z",
        "2026-12-01T00:00:00Z",
        authorized_grade_band_low=3,
        authorized_grade_band_high=5,
    )

    assert successor["status"] == ENTRY_PUBLISHED, (
        f"Expected PUBLISHED, got {successor['status']}"
    )
    assert_instant_equals(
        successor["effective_from"], "2026-10-01T00:00:00.000Z", "effective_from"
    )
    assert_instant_equals(
        successor["reauthorization_due_at"],
        "2026-11-01T00:00:00.000Z",
        "reauthorization_due_at",
    )


def test_backing_the_same_window_off_by_one_second_is_an_overlap(api):
    """One second of genuine intersection is refused, unlike the adjacent case.

    PRD: "Overlap is tested only against sibling entries of the same application
    in status `PUBLISHED`, `EXPIRING_SOON` or `SUSPENDED_HOLD`, and a conflict is
    reported as `ERR_AUTHORIZATION_WINDOW_OVERLAP`."

    Design: Difficulty/resource_temporal_overlap/catalog_window_adjacency_legal_one_second_overlap_rejected
    """
    ctx = _entry_published_over_august_and_september(api)
    fx.publish_entry(
        api,
        ctx["application_id"],
        ctx["review_id"],
        "2026-10-01T00:00:00Z",
        "2026-12-01T00:00:00Z",
        authorized_grade_band_low=3,
        authorized_grade_band_high=5,
    )

    response = api.create_catalog_entry(
        {
            "application_id": ctx["application_id"],
            "review_id": ctx["review_id"],
            "effective_from": "2026-09-30T23:59:59Z",
            "expires_at": "2026-12-01T00:00:00Z",
            "authorized_grade_band_low": 3,
            "authorized_grade_band_high": 5,
        },
        ADMIN_HEADERS,
    )

    validate_error(response, ERR_AUTHORIZATION_WINDOW_OVERLAP, 409)
    predecessor = fx.read_entry(api, ctx["entry_id"])
    assert predecessor["status"] == ENTRY_PUBLISHED, (
        f"The live entry is untouched, got {predecessor['status']}"
    )
    _, meta = validate_paginated(
        api.list_catalog_entries(ADMIN_HEADERS, application_id=ctx["application_id"])
    )
    assert_integer_equals(meta["total_count"], 2, "total_count")


# ---------------------------------------------------------------------------
# Closed incident windows: touching endpoints collide
# ---------------------------------------------------------------------------


def test_incident_touching_the_widened_buffer_end_exactly_is_refused(api):
    """The mirror image of the catalog rule: closed intervals make touching a collision.

    PRD: "The incoming window collides if it intersects any widened window as
    closed intervals — that is, if the incoming window's start is at or before
    the widened window's end **and** the incoming window's end is at or after
    the widened window's start."

    Design: Difficulty/resource_temporal_overlap/incident_buffer_window_touching_endpoints_collide
    """
    ctx = _uncontained_incident_widened_to_august_eighth(api)

    response = api.create_incident(
        {
            "vendor_id": ctx["vendor_id"],
            "incident_type": INCIDENT_SUBPROCESSOR_CHANGE,
            "detected_at": "2026-08-08T00:00:00Z",
            "affected_student_count": 5,
            "max_data_tier": 1,
        },
        ADMIN_HEADERS,
    )

    validate_error(response, ERR_INCIDENT_WINDOW_BUFFER_CONFLICT, 409)
    existing = fx.read_incident(api, ctx["incident_id"])
    assert existing["response_status"] == INCIDENT_REPORTED, (
        f"The existing row is untouched, got {existing['response_status']}"
    )
    assert existing["contained_at"] is None, (
        "An uncontained incident keeps a null contained_at"
    )
    assert existing["notification_status"] == NOTIFICATION_PENDING, (
        "Only the sweep promotes a missed notification to OVERDUE"
    )


def test_incident_one_second_past_the_widened_buffer_end_is_accepted(api):
    """A single second clears the closed interval and the report lands.

    PRD: "each existing incident of that vendor in `REPORTED`, `CONTAINED`,
    `ESCALATED` or `REMEDIATED` has its bare window widened by 72 hours at the
    start and 72 hours at the end; the incoming window is **not** widened."

    Design: Difficulty/resource_temporal_overlap/incident_buffer_window_touching_endpoints_collide
    """
    ctx = _uncontained_incident_widened_to_august_eighth(api)
    api.create_incident(
        {
            "vendor_id": ctx["vendor_id"],
            "incident_type": INCIDENT_SUBPROCESSOR_CHANGE,
            "detected_at": "2026-08-08T00:00:00Z",
            "affected_student_count": 5,
            "max_data_tier": 1,
        },
        ADMIN_HEADERS,
    )

    accepted = fx.report_incident(
        api,
        ctx["vendor_id"],
        "2026-08-08T00:00:01Z",
        incident_type=INCIDENT_SUBPROCESSOR_CHANGE,
        affected_student_count=5,
        max_data_tier=1,
    )

    assert_instant_equals(
        accepted["detected_at"], "2026-08-08T00:00:01.000Z", "detected_at"
    )
    assert accepted["severity"] == SEVERITY_LOW, (
        f"Five students at tier 1 is LOW, got {accepted['severity']}"
    )
    assert_instant_equals(
        accepted["notification_due_at"],
        "2026-08-10T00:00:01.000Z",
        "notification_due_at",
    )
    _, meta = validate_paginated(
        api.list_incidents(ADMIN_HEADERS, vendor_id=ctx["vendor_id"])
    )
    assert_integer_equals(meta["total_count"], 2, "total_count")
    vendor = fx.read_vendor(api, ctx["vendor_id"])
    assert_decimal_equals(vendor["risk_score"], "6.00", "risk_score")
    assert vendor["privacy_posture"] == POSTURE_RESTRICTED, (
        f"Two open incidents restrict the vendor, got {vendor['privacy_posture']}"
    )
