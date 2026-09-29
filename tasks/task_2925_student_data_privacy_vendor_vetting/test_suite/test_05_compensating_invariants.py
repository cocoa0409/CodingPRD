"""Quantities the service must conserve: workload minutes across a reassignment
and exposure points across an undone acceptance.
"""

from test_helpers import (
    assert_decimal_equals,
    assert_integer_equals,
    fixtures as fx,
    make_analyst_headers,
    make_teacher_headers,
    validate_error,
)
from test_helpers.api_errors import ERR_COMMITMENT_ALREADY_DECIDED
from test_helpers.constants import (
    ACCESSIBILITY_WCAG21_AA,
    ANONYMIZE,
    CATEGORY_ASSESSMENT,
    CATEGORY_INSTRUCTIONAL_CONTENT,
    COMMITMENT_ACCEPTED,
    COMMITMENT_REJECTED,
    CREDENTIAL_LEAD,
    CREDENTIAL_SENIOR,
    DISPOSITION_ACCEPT,
    DISPOSITION_REJECT,
    ELEMENT_GRADE_LEVEL,
    ELEMENT_STUDENT_NAME,
    FRAMEWORK_COPPA,
    FRAMEWORK_FERPA,
    JUST_240,
    POSTURE_CLEAR,
    PURPOSE_61,
    REVIEW_SCREENING,
    SSO_LTI13,
    SSO_SAML2,
    TRIAGE_ACCEPT_FOR_REVIEW,
)

DISTRICT_WIDE_MINUTES = 540


def _two_screening_reviews_on_two_analysts(api):
    """240 minutes held by one analyst and 300 by another, 540 district-wide."""
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
    teacher = fx.enroll_teacher(api, full_name="Dana Reyes", employee_number="EMP-7040")
    teacher_headers = make_teacher_headers(teacher["id"])
    first_analyst = fx.enroll_analyst(
        api, CREDENTIAL_SENIOR, review_capacity_minutes=2400
    )
    second_analyst = fx.enroll_analyst(
        api, CREDENTIAL_LEAD, review_capacity_minutes=2400
    )
    first_headers = make_analyst_headers(first_analyst["id"])

    requests = []
    for element_code in (ELEMENT_STUDENT_NAME, ELEMENT_GRADE_LEVEL):
        request = fx.draft_request(
            api,
            app["id"],
            teacher["id"],
            teacher_headers,
            instructional_justification=JUST_240,
            requested_data_elements=[element_code],
            student_count_estimate=700,
            grade_band_low=7,
            grade_band_high=8,
        )
        fx.submit_request(api, request["id"], teacher_headers)
        fx.triage_request(api, request["id"], TRIAGE_ACCEPT_FOR_REVIEW, first_headers)
        requests.append(request["id"])

    first_review = fx.open_review(
        api,
        requests[0],
        first_analyst["id"],
        first_headers,
        framework_set=[FRAMEWORK_FERPA, FRAMEWORK_COPPA],
        estimated_minutes=240,
    )
    second_review = fx.open_review(
        api,
        requests[1],
        second_analyst["id"],
        first_headers,
        framework_set=[FRAMEWORK_FERPA, FRAMEWORK_COPPA],
        estimated_minutes=300,
    )
    return {
        "first_analyst_id": first_analyst["id"],
        "second_analyst_id": second_analyst["id"],
        "first_review_id": first_review["id"],
        "second_review_id": second_review["id"],
    }


def _two_accepted_tier_one_commitments(api):
    """Two rows of 1.44 accepted, so the application total sits at 2.88."""
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
        employee_number="EMP-7041",
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
        requested_data_elements=[ELEMENT_STUDENT_NAME, ELEMENT_GRADE_LEVEL],
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
        framework_set=[FRAMEWORK_FERPA, FRAMEWORK_COPPA],
        estimated_minutes=180,
    )
    survivor = fx.propose_commitment(
        api,
        review["id"],
        ELEMENT_STUDENT_NAME,
        assignee_headers,
        justified_purpose=PURPOSE_61,
        retention_days=365,
        deletion_method=ANONYMIZE,
    )
    undone = fx.propose_commitment(
        api,
        review["id"],
        ELEMENT_GRADE_LEVEL,
        assignee_headers,
        justified_purpose=PURPOSE_61,
        retention_days=365,
        deletion_method=ANONYMIZE,
    )
    fx.decide_commitment(api, survivor["id"], DISPOSITION_ACCEPT, decider_headers)
    fx.decide_commitment(api, undone["id"], DISPOSITION_ACCEPT, decider_headers)
    return {
        "vendor_id": vendor["id"],
        "application_id": app["id"],
        "survivor_id": survivor["id"],
        "undone_id": undone["id"],
        "decider_headers": decider_headers,
    }


# ---------------------------------------------------------------------------
# Workload minutes are conserved across a reassignment
# ---------------------------------------------------------------------------


def test_reassignment_moves_the_minutes_off_the_outgoing_analyst(api):
    """Both analysts are recomputed, so the district-wide sum is unchanged at 540.

    PRD: "A successful move recomputes `allocated_review_minutes` on **both** the
    outgoing and the incoming analyst, which leaves the district-wide sum of
    allocated minutes unchanged, and it advances the review's `version`."

    Design: Difficulty/compensating_invariant/reassign_conserves_district_wide_allocated_minutes
    """
    ctx = _two_screening_reviews_on_two_analysts(api)

    fx.reassign_review(api, ctx["first_review_id"], ctx["second_analyst_id"])

    outgoing = fx.read_analyst(api, ctx["first_analyst_id"])
    incoming = fx.read_analyst(api, ctx["second_analyst_id"])
    assert_integer_equals(
        outgoing["allocated_review_minutes"], 0, "outgoing allocated_review_minutes"
    )
    assert_integer_equals(
        incoming["allocated_review_minutes"], 540, "incoming allocated_review_minutes"
    )
    total = outgoing["allocated_review_minutes"] + incoming["allocated_review_minutes"]
    assert_integer_equals(total, DISTRICT_WIDE_MINUTES, "district-wide allocated minutes")


def test_reassignment_leaves_the_review_screening_and_its_estimate_intact(api):
    """Only the assignee changes; the estimate and the state stay put.

    PRD: "Reassignment moves a non-terminal review to a different analyst, and
    only a `PrivacyOfficeAdmin` may do it. The payload carries the incoming
    `assigned_analyst_id`."

    Design: Difficulty/compensating_invariant/reassign_conserves_district_wide_allocated_minutes
    """
    ctx = _two_screening_reviews_on_two_analysts(api)

    moved = fx.reassign_review(api, ctx["first_review_id"], ctx["second_analyst_id"])

    assert moved["assigned_analyst_id"] == ctx["second_analyst_id"], (
        "The review must now name the incoming analyst"
    )
    assert moved["status"] == REVIEW_SCREENING, (
        f"Reassignment does not advance the review, got {moved['status']}"
    )
    assert_integer_equals(moved["estimated_minutes"], 240, "estimated_minutes")
    untouched = fx.read_review(api, ctx["second_review_id"])
    assert untouched["assigned_analyst_id"] == ctx["second_analyst_id"], (
        "The sibling review keeps its own assignee"
    )


# ---------------------------------------------------------------------------
# Exposure points are restored exactly
# ---------------------------------------------------------------------------


def test_rejecting_an_accepted_commitment_restores_the_exact_prior_total(api):
    """The application returns to 1.44, not to a delta-drifted 1.4425.

    PRD: "Full recomputation is what makes the compensating actions of §3 exact:
    rejecting a previously accepted commitment returns the application's
    exposure total to precisely the value it held before that commitment was
    accepted, with no drift."

    Design: Difficulty/compensating_invariant/reject_accepted_commitment_restores_exposed_points_exactly
    """
    ctx = _two_accepted_tier_one_commitments(api)
    before = fx.read_application(api, ctx["application_id"])
    assert_decimal_equals(
        before["exposed_sensitivity_points"], "2.88", "exposed_sensitivity_points"
    )

    rejected = fx.decide_commitment(
        api, ctx["undone_id"], DISPOSITION_REJECT, ctx["decider_headers"]
    )

    assert rejected["status"] == COMMITMENT_REJECTED, (
        f"Expected REJECTED, got {rejected['status']}"
    )
    survivor = fx.read_commitment(api, ctx["survivor_id"])
    assert survivor["status"] == COMMITMENT_ACCEPTED, (
        f"The sibling is untouched, got {survivor['status']}"
    )
    assert_decimal_equals(survivor["element_points"], "1.44", "element_points")
    app = fx.read_application(api, ctx["application_id"])
    assert_decimal_equals(
        app["exposed_sensitivity_points"], "1.44", "exposed_sensitivity_points"
    )
    vendor = fx.read_vendor(api, ctx["vendor_id"])
    assert_decimal_equals(vendor["risk_score"], "0.72", "risk_score")
    assert vendor["privacy_posture"] == POSTURE_CLEAR, (
        f"Expected CLEAR, got {vendor['privacy_posture']}"
    )


def test_the_compensation_cannot_be_replayed_on_a_rejected_row(api):
    """REJECTED is terminal, so a second reject is refused.

    PRD: "The commitment itself must still be dispositionable — `PROPOSED` or
    `ACCEPTED` — because `REJECTED` and `SUPERSEDED` are terminal and yield
    `ERR_COMMITMENT_ALREADY_DECIDED`."

    Design: Difficulty/compensating_invariant/reject_accepted_commitment_restores_exposed_points_exactly
    """
    ctx = _two_accepted_tier_one_commitments(api)
    fx.decide_commitment(api, ctx["undone_id"], DISPOSITION_REJECT, ctx["decider_headers"])

    response = api.decide_commitment(
        ctx["undone_id"], {"disposition": DISPOSITION_REJECT}, ctx["decider_headers"]
    )

    validate_error(response, ERR_COMMITMENT_ALREADY_DECIDED, 409)
    app = fx.read_application(api, ctx["application_id"])
    assert_decimal_equals(
        app["exposed_sensitivity_points"], "1.44", "exposed_sensitivity_points"
    )
