"""Machines that loop, machines that run on two independent axes, and the
multi-row cascades one write is required to walk.
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
)
from test_helpers.api_errors import (
    ERR_NOTIFICATION_ALREADY_SENT,
    ERR_REVISION_LIMIT_EXCEEDED,
)
from test_helpers.constants import (
    ACCESSIBILITY_WCAG21_AA,
    ALL_FRAMEWORKS,
    ANONYMIZE,
    APPLICATION_APPROVED,
    BAND_STANDARD,
    CATEGORY_ADMINISTRATIVE,
    CATEGORY_ASSESSMENT,
    CATEGORY_INSTRUCTIONAL_CONTENT,
    COMMITMENT_ACCEPTED,
    CREDENTIAL_LEAD,
    CREDENTIAL_SENIOR,
    DECISION_CLEAR,
    DISPOSITION_ACCEPT,
    ELEMENT_GRADE_LEVEL,
    ELEMENT_IEP_STATUS,
    ELEMENT_STUDENT_NAME,
    HARD_DELETE,
    INCIDENT_CONTAINED,
    INCIDENT_RETENTION_VIOLATION,
    JUST_240,
    NOTIFICATION_SENT,
    POSTURE_CLEAR,
    POSTURE_WATCH,
    PURPOSE_61,
    REQUEST_CLOSED_APPROVED,
    REQUEST_RETURNED,
    REQUEST_SUBMITTED,
    REVIEW_CLEARED,
    SEVERITY_LOW,
    SSO_LTI13,
    SSO_SAML2,
    TRIAGE_ACCEPT_FOR_REVIEW,
    TRIAGE_RETURN,
    VENDOR_APPROVED,
    VISIBILITY_HIDDEN,
)


# ---------------------------------------------------------------------------
# Shared chains
# ---------------------------------------------------------------------------


def _request_parked_in_returned_at_revision_two(api):
    """Drive SUBMITTED -> RETURNED -> SUBMITTED twice, ending in RETURNED."""
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
    teacher = fx.enroll_teacher(api, full_name="Dana Reyes", employee_number="EMP-7005")
    teacher_headers = make_teacher_headers(teacher["id"])
    analyst = fx.enroll_analyst(api, CREDENTIAL_SENIOR, review_capacity_minutes=2400)
    analyst_headers = make_analyst_headers(analyst["id"])

    request = fx.draft_request(
        api,
        app["id"],
        teacher["id"],
        teacher_headers,
        instructional_justification=JUST_240,
        requested_data_elements=[ELEMENT_STUDENT_NAME, ELEMENT_GRADE_LEVEL],
        student_count_estimate=700,
        grade_band_low=7,
        grade_band_high=8,
    )
    rounds = [
        "Round 1: narrow the data elements.",
        "Round 2: justification still thin.",
        "Round 3: returned again.",
    ]
    for note in rounds:
        fx.submit_request(api, request["id"], teacher_headers)
        fx.triage_request(
            api, request["id"], TRIAGE_RETURN, analyst_headers, triage_note=note
        )
    return {
        "teacher_id": teacher["id"],
        "teacher_headers": teacher_headers,
        "request_id": request["id"],
    }


def _notified_then_contained_incident(api):
    """One LOW incident whose notification axis is SENT and response axis CONTAINED."""
    fx.set_clock(api)
    vendor = fx.register_vendor(
        api,
        legal_name="Harborlight Media Inc",
        breach_notification_hours=72,
        signed_state_addendum=True,
        subprocessor_disclosure_complete=True,
    )
    incident = fx.report_incident(
        api,
        vendor["id"],
        "2026-08-01T00:00:00Z",
        incident_type=INCIDENT_RETENTION_VIOLATION,
        affected_student_count=5,
        max_data_tier=1,
    )
    fx.send_notification(api, incident["id"], 5)
    fx.set_clock(api, "2026-08-01T12:00:00Z")
    fx.contain_incident(api, incident["id"], "2026-08-01T12:00:00Z")
    return {"vendor_id": vendor["id"], "incident_id": incident["id"]}


def _findings_issued_review_with_a_second_untriaged_request(api):
    """One teacher holds a triaged request under review and a second still SUBMITTED."""
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
        sso_protocol=SSO_LTI13,
        accessibility_conformance_level=ACCESSIBILITY_WCAG21_AA,
        vpat_on_file=True,
    )
    fx.attest_integration(api, app["id"], sso_verified=True)
    teacher = fx.enroll_teacher(
        api,
        full_name="Ivy Chen",
        employee_number="EMP-7010",
        school_code="ES-11",
        grade_bands_taught=[3, 4, 5],
    )
    teacher_headers = make_teacher_headers(teacher["id"])
    assignee = fx.enroll_analyst(api, CREDENTIAL_SENIOR, review_capacity_minutes=2400)
    decider = fx.enroll_analyst(api, CREDENTIAL_LEAD, review_capacity_minutes=2400)
    assignee_headers = make_analyst_headers(assignee["id"])
    decider_headers = make_analyst_headers(decider["id"])

    first = fx.draft_request(
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
    fx.submit_request(api, first["id"], teacher_headers)
    second = fx.draft_request(
        api,
        app["id"],
        teacher["id"],
        teacher_headers,
        instructional_justification=JUST_240,
        requested_data_elements=[ELEMENT_GRADE_LEVEL],
        student_count_estimate=300,
        grade_band_low=3,
        grade_band_high=5,
    )
    fx.submit_request(api, second["id"], teacher_headers)
    fx.triage_request(api, first["id"], TRIAGE_ACCEPT_FOR_REVIEW, assignee_headers)

    review = fx.open_review(
        api,
        first["id"],
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
    return {
        "vendor_id": vendor["id"],
        "application_id": app["id"],
        "teacher_id": teacher["id"],
        "assignee_id": assignee["id"],
        "decider_id": decider["id"],
        "decider_headers": decider_headers,
        "first_request_id": first["id"],
        "second_request_id": second["id"],
        "review_id": review["id"],
    }


def _proposed_tier_four_commitment_on_a_penalised_vendor(api):
    """A vendor already carrying 45 points of penalties, plus one PROPOSED tier-4 row."""
    fx.set_clock(api)
    vendor = fx.register_vendor(
        api,
        legal_name="Cascadia Student Systems",
        breach_notification_hours=200,
        data_deletion_days=45,
        signed_state_addendum=True,
        subprocessor_disclosure_complete=True,
    )
    fx.disclose_subprocessor(
        api,
        vendor["id"],
        name="Dublin Hosting Ltd",
        country_code="IE",
        data_categories=[ELEMENT_STUDENT_NAME],
        purpose="Primary application hosting for the district tenant.",
        sub_breach_notification_hours=24,
    )
    fx.disclose_subprocessor(
        api,
        vendor["id"],
        name="Pune Support Services",
        country_code="IN",
        data_categories=[ELEMENT_GRADE_LEVEL],
        purpose="Tier two support desk for district staff tickets.",
        sub_breach_notification_hours=48,
    )
    app = fx.register_application(
        api,
        vendor["id"],
        name="Cascadia SIS Companion",
        category=CATEGORY_ADMINISTRATIVE,
        grade_band_low=6,
        grade_band_high=8,
        sso_protocol=SSO_SAML2,
        accessibility_conformance_level=ACCESSIBILITY_WCAG21_AA,
        vpat_on_file=True,
    )
    fx.attest_integration(api, app["id"], sso_verified=True)
    teacher = fx.enroll_teacher(api, full_name="Dana Reyes", employee_number="EMP-7011")
    teacher_headers = make_teacher_headers(teacher["id"])
    assignee = fx.enroll_analyst(api, CREDENTIAL_SENIOR, review_capacity_minutes=2400)
    decider = fx.enroll_analyst(api, CREDENTIAL_LEAD, review_capacity_minutes=2400)
    assignee_headers = make_analyst_headers(assignee["id"])

    request = fx.draft_request(
        api,
        app["id"],
        teacher["id"],
        teacher_headers,
        instructional_justification=JUST_240,
        requested_data_elements=[ELEMENT_IEP_STATUS],
        student_count_estimate=300,
        grade_band_low=6,
        grade_band_high=8,
    )
    fx.submit_request(api, request["id"], teacher_headers)
    fx.triage_request(api, request["id"], TRIAGE_ACCEPT_FOR_REVIEW, assignee_headers)
    review = fx.open_review(
        api,
        request["id"],
        assignee["id"],
        assignee_headers,
        framework_set=list(ALL_FRAMEWORKS),
        estimated_minutes=240,
    )
    commitment = fx.propose_commitment(
        api,
        review["id"],
        ELEMENT_IEP_STATUS,
        assignee_headers,
        justified_purpose=PURPOSE_61,
        retention_days=365,
        deletion_method=HARD_DELETE,
    )
    return {
        "vendor_id": vendor["id"],
        "application_id": app["id"],
        "commitment_id": commitment["id"],
        "decider_headers": make_analyst_headers(decider["id"]),
    }


# ---------------------------------------------------------------------------
# The cyclic request machine
# ---------------------------------------------------------------------------


def test_third_resubmission_is_refused_once_the_revision_counter_reaches_two(api):
    """The loop is bounded by the counter, and the row stays parked in RETURNED.

    PRD: "a resubmission is permitted only while `revision_round` is still below
    2, so once the counter has reached 2 any further submission is refused with
    `ERR_REVISION_LIMIT_EXCEEDED`."

    Design: Difficulty/non_linear_state_machine/request_return_resubmit_cycle_then_revision_limit
    """
    ctx = _request_parked_in_returned_at_revision_two(api)

    response = api.submit_request(ctx["request_id"], {}, ctx["teacher_headers"])

    validate_error(response, ERR_REVISION_LIMIT_EXCEEDED, 409)
    request = fx.read_request(api, ctx["request_id"])
    assert_integer_equals(request["revision_round"], 2, "revision_round")
    assert request["status"] == REQUEST_RETURNED, (
        f"A refused resubmission leaves the row in RETURNED, got {request['status']}"
    )


def test_revision_counter_advances_only_on_the_returned_to_submitted_edge(api):
    """Three submissions but only two of them left RETURNED, so the counter reads 2.

    PRD: "A successful submission moves the request to `SUBMITTED`, stamps
    `submitted_at` with the current logical clock, and — when the prior status
    was `RETURNED` — increases `revision_round` by 1; the first submission out
    of `DRAFT` leaves the counter alone."

    Design: Difficulty/non_linear_state_machine/request_return_resubmit_cycle_then_revision_limit
    """
    ctx = _request_parked_in_returned_at_revision_two(api)

    request = fx.read_request(api, ctx["request_id"])
    assert_integer_equals(request["revision_round"], 2, "revision_round")
    assert_decimal_equals(request["priority_score"], "60.50", "priority_score")
    assert request["priority_band"] == BAND_STANDARD, (
        f"Expected STANDARD, got {request['priority_band']}"
    )
    teacher = fx.read_teacher(api, ctx["teacher_id"])
    assert_integer_equals(teacher["open_request_count"], 1, "open_request_count")


# ---------------------------------------------------------------------------
# The two-axis incident machine
# ---------------------------------------------------------------------------


def test_second_notification_is_refused_and_leaves_the_recorded_count_alone(api):
    """SENT is terminal on the notification axis even mid-flight on the other.

    PRD: "It requires `notification_status` to be `PENDING` or `OVERDUE`; `SENT`
    and `SENT_LATE` are terminal for this dimension and a repeat attempt is
    refused with `ERR_NOTIFICATION_ALREADY_SENT`."

    Design: Difficulty/non_linear_state_machine/incident_response_and_notification_dimensions_advance_independently
    """
    ctx = _notified_then_contained_incident(api)

    response = api.send_notification(
        ctx["incident_id"], {"notified_party_count": 9}, ADMIN_HEADERS
    )

    validate_error(response, ERR_NOTIFICATION_ALREADY_SENT, 409)
    incident = fx.read_incident(api, ctx["incident_id"])
    assert_integer_equals(incident["notified_party_count"], 5, "notified_party_count")


def test_response_and_notification_axes_never_write_each_other(api):
    """Notifying left the response axis alone; containing left the notification axis alone.

    PRD: "Neither axis constrains the other: an incident may be contained and remediated
    while its notification is still `PENDING`, and it may be notified while its
    response is still `REPORTED`. No transition on one axis ever writes the other,
    and the workflow narrative below should be read as two parallel tracks."

    Design: Difficulty/non_linear_state_machine/incident_response_and_notification_dimensions_advance_independently
    """
    ctx = _notified_then_contained_incident(api)

    incident = fx.read_incident(api, ctx["incident_id"])

    assert incident["severity"] == SEVERITY_LOW, (
        f"Five students at tier 1 is LOW, got {incident['severity']}"
    )
    assert_instant_equals(
        incident["notification_due_at"], "2026-08-04T00:00:00.000Z", "notification_due_at"
    )
    assert incident["notification_status"] == NOTIFICATION_SENT, (
        f"Expected SENT, got {incident['notification_status']}"
    )
    assert_instant_equals(
        incident["notification_sent_at"],
        "2026-08-01T00:00:00.000Z",
        "notification_sent_at",
    )
    assert incident["response_status"] == INCIDENT_CONTAINED, (
        f"Expected CONTAINED, got {incident['response_status']}"
    )
    assert_instant_equals(
        incident["contained_at"], "2026-08-01T12:00:00.000Z", "contained_at"
    )
    vendor = fx.read_vendor(api, ctx["vendor_id"])
    assert_integer_equals(vendor["open_incident_count"], 1, "open_incident_count")


# ---------------------------------------------------------------------------
# One decision, four hops
# ---------------------------------------------------------------------------


def test_clear_decision_closes_only_the_triaged_request_of_that_application(api):
    """Hop three touches exactly one request, so the teacher's count lands on 1.

    PRD: "The third hop follows the application: every request of that
    application still sitting in `TRIAGED_FOR_REVIEW` moves to `CLOSED_APPROVED`
    when the application was approved either way, and to `CLOSED_BLOCKED` when
    it was blocked."

    Design: Difficulty/transitive_cascade/review_clear_cascades_four_hops_to_teacher_open_request_count
    """
    ctx = _findings_issued_review_with_a_second_untriaged_request(api)

    fx.decide_review(
        api,
        ctx["review_id"],
        DECISION_CLEAR,
        ctx["decider_headers"],
        decision_note="Cleared for publication.",
    )

    app = fx.read_application(api, ctx["application_id"])
    assert app["status"] == APPLICATION_APPROVED, (
        f"Expected APPROVED, got {app['status']}"
    )
    assert app["catalog_visibility"] == VISIBILITY_HIDDEN, (
        "Approval alone does not publish the application"
    )
    first = fx.read_request(api, ctx["first_request_id"])
    assert first["status"] == REQUEST_CLOSED_APPROVED, (
        f"Expected CLOSED_APPROVED, got {first['status']}"
    )
    second = fx.read_request(api, ctx["second_request_id"])
    assert second["status"] == REQUEST_SUBMITTED, (
        f"An untriaged request is outside the cascade, got {second['status']}"
    )
    teacher = fx.read_teacher(api, ctx["teacher_id"])
    assert_integer_equals(teacher["open_request_count"], 1, "open_request_count")


def test_clear_decision_settles_review_vendor_and_analyst_workload(api):
    """The same call scores the review, promotes the vendor and frees the analyst.

    PRD: "A vendor that was still `REGISTERED` or `UNDER_REVIEW` moves to `APPROVED` on
    `CLEAR`, `CONDITIONAL` on `CONDITIONAL`, and the terminal `REJECTED` on `BLOCK`;
    a rejected vendor can never be reinstated and can only re-enter the district as
    a newly registered row."

    Design: Difficulty/transitive_cascade/review_clear_cascades_four_hops_to_teacher_open_request_count
    """
    ctx = _findings_issued_review_with_a_second_untriaged_request(api)

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
    assert review["decided_by_analyst_id"] == ctx["decider_id"], (
        "The deciding analyst must be stamped on the review"
    )
    vendor = fx.read_vendor(api, ctx["vendor_id"])
    assert vendor["status"] == VENDOR_APPROVED, (
        f"Expected APPROVED, got {vendor['status']}"
    )
    assert_decimal_equals(vendor["risk_score"], "0.72", "risk_score")
    assert vendor["privacy_posture"] == POSTURE_CLEAR, (
        f"Expected CLEAR, got {vendor['privacy_posture']}"
    )
    analyst = fx.read_analyst(api, ctx["assignee_id"])
    assert_integer_equals(
        analyst["allocated_review_minutes"], 0, "allocated_review_minutes"
    )


def test_accepting_one_commitment_walks_the_element_points_to_the_application(api):
    """Hop one and hop two: the row is scored and the application total follows.

    PRD: "The full dependency chain runs from a commitment decision to the
    owning application's `exposed_sensitivity_points`, from there to the
    vendor's `risk_score`, and from there to the vendor's `privacy_posture` —
    one analyst decision therefore walks four rows."

    Design: Difficulty/transitive_cascade/commitment_accept_cascades_four_hops_to_vendor_posture
    """
    ctx = _proposed_tier_four_commitment_on_a_penalised_vendor(api)

    decided = fx.decide_commitment(
        api, ctx["commitment_id"], DISPOSITION_ACCEPT, ctx["decider_headers"]
    )

    assert decided["status"] == COMMITMENT_ACCEPTED, (
        f"Expected ACCEPTED, got {decided['status']}"
    )
    assert_integer_equals(decided["sensitivity_tier"], 4, "sensitivity_tier")
    assert_decimal_equals(decided["element_points"], "16.25", "element_points")
    assert decided["is_minimized"] is True, (
        "A tier-4 row exactly at the 365-day ceiling on an ADMINISTRATIVE "
        "application is minimized"
    )
    app = fx.read_application(api, ctx["application_id"])
    assert_decimal_equals(
        app["exposed_sensitivity_points"], "16.25", "exposed_sensitivity_points"
    )


def test_posture_is_re_evaluated_from_the_refreshed_risk_score(api):
    """The vendor lands on WATCH at 53.13, which only a fresh score can produce.

    PRD: "First, **derived values are recomputed in dependency order**: a vendor's
    `risk_score` is always recomputed before its `privacy_posture` in any operation
    whose effects name both, so posture never reads a stale score."

    Design: Difficulty/transitive_cascade/commitment_accept_cascades_four_hops_to_vendor_posture
    """
    ctx = _proposed_tier_four_commitment_on_a_penalised_vendor(api)

    fx.decide_commitment(
        api, ctx["commitment_id"], DISPOSITION_ACCEPT, ctx["decider_headers"]
    )

    vendor = fx.read_vendor(api, ctx["vendor_id"])
    assert_decimal_equals(vendor["risk_score"], "53.13", "risk_score")
    assert vendor["privacy_posture"] == POSTURE_WATCH, (
        f"Expected WATCH above the threshold of 45, got {vendor['privacy_posture']}"
    )
    assert_integer_equals(
        vendor["flagged_subprocessor_count"], 0, "flagged_subprocessor_count"
    )
