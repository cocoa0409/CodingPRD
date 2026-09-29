"""Scores whose two variants read the same rows differently, and scores whose
factor tables must be combined in exactly one order.
"""

from test_helpers import (
    assert_decimal_equals,
    assert_instant_equals,
    assert_integer_equals,
    fixtures as fx,
    make_analyst_headers,
    make_teacher_headers,
)
from test_helpers.constants import (
    ACCESSIBILITY_WCAG21_AA,
    ANONYMIZE,
    ALL_FRAMEWORKS,
    APPLICATION_APPROVED_WITH_CONDITIONS,
    BAND_HIGH,
    BAND_STANDARD,
    CATEGORY_ASSESSMENT,
    CATEGORY_INSTRUCTIONAL_CONTENT,
    COMMITMENT_SUPERSEDED,
    CREDENTIAL_LEAD,
    CREDENTIAL_SENIOR,
    DECISION_CLEAR,
    DECISION_CONDITIONAL,
    DISPOSITION_ACCEPT,
    ELEMENT_EMAIL,
    ELEMENT_GRADE_LEVEL,
    ELEMENT_PARENT_CONTACT,
    ELEMENT_STUDENT_NAME,
    ENTRY_SUPERSEDED,
    FRAMEWORK_COPPA,
    FRAMEWORK_FERPA,
    HARD_DELETE,
    INCIDENT_BREACH,
    JUST_140,
    JUST_240,
    POSTURE_CLEAR,
    POSTURE_WATCH,
    PURPOSE_61,
    REQUEST_SUBMITTED,
    RESOLVE_REMEDIATE,
    REVIEW_CONDITIONAL,
    SSO_LTI13,
    SSO_OIDC,
    SSO_SAML2,
    TRIAGE_ACCEPT_FOR_REVIEW,
    VENDOR_CONDITIONAL,
)


# ---------------------------------------------------------------------------
# Shared chains
# ---------------------------------------------------------------------------


def _findings_issued_review_with_mixed_commitments(api):
    """A FINDINGS_ISSUED review whose PROPOSED and ACCEPTED sets differ.

    Two tier-1 rows at 365 days / ANONYMIZE are ACCEPTED; one tier-2 EMAIL row
    at 900 days / HARD_DELETE is left PROPOSED, so the optimistic and
    pessimistic input sets are genuinely different.  The vendor has not signed
    the state addendum.
    """
    fx.set_clock(api)
    vendor = fx.register_vendor(
        api,
        legal_name="Northbeam Learning Inc",
        breach_notification_hours=72,
        signed_state_addendum=False,
        subprocessor_disclosure_complete=True,
    )
    app = fx.register_application(
        api,
        vendor["id"],
        name="Northbeam Formative",
        category=CATEGORY_ASSESSMENT,
        grade_band_low=6,
        grade_band_high=8,
        sso_protocol=SSO_SAML2,
        accessibility_conformance_level=ACCESSIBILITY_WCAG21_AA,
        vpat_on_file=True,
    )
    fx.attest_integration(api, app["id"], sso_verified=True)
    teacher = fx.enroll_teacher(api, full_name="Dana Reyes", employee_number="EMP-7001")
    teacher_headers = make_teacher_headers(teacher["id"])
    assignee = fx.enroll_analyst(api, CREDENTIAL_SENIOR, review_capacity_minutes=2400)
    decider = fx.enroll_analyst(api, CREDENTIAL_LEAD, review_capacity_minutes=2400)

    req = fx.draft_request(
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
    fx.submit_request(api, req["id"], teacher_headers)
    fx.triage_request(api, req["id"], TRIAGE_ACCEPT_FOR_REVIEW)
    review = fx.open_review(
        api,
        req["id"],
        assignee["id"],
        framework_set=list(ALL_FRAMEWORKS),
        estimated_minutes=240,
    )

    assignee_headers = make_analyst_headers(assignee["id"])
    decider_headers = make_analyst_headers(decider["id"])

    cm1 = fx.propose_commitment(
        api,
        review["id"],
        ELEMENT_STUDENT_NAME,
        assignee_headers,
        justified_purpose=PURPOSE_61,
        retention_days=365,
        deletion_method=ANONYMIZE,
    )
    cm2 = fx.propose_commitment(
        api,
        review["id"],
        ELEMENT_GRADE_LEVEL,
        assignee_headers,
        justified_purpose=PURPOSE_61,
        retention_days=365,
        deletion_method=ANONYMIZE,
    )
    cm3 = fx.propose_commitment(
        api,
        review["id"],
        ELEMENT_EMAIL,
        assignee_headers,
        justified_purpose=PURPOSE_61,
        retention_days=900,
        deletion_method=HARD_DELETE,
    )
    fx.decide_commitment(api, cm1["id"], DISPOSITION_ACCEPT, decider_headers)
    fx.decide_commitment(api, cm2["id"], DISPOSITION_ACCEPT, decider_headers)
    fx.issue_findings(
        api,
        review["id"],
        2,
        assignee_headers,
        decision_note="Retention term on EMAIL exceeds district guidance.",
    )
    return {
        "vendor_id": vendor["id"],
        "application_id": app["id"],
        "review_id": review["id"],
        "commitment_ids": [cm1["id"], cm2["id"], cm3["id"]],
        "decider_headers": decider_headers,
        "assignee_headers": assignee_headers,
    }


def _remediated_critical_incident_with_expiring_entry(api):
    """A vendor carrying one REMEDIATED CRITICAL incident and a renewable entry.

    The incident is 47 days old at the reauthorization clock, so its decay
    multiplier is still 1.0 and the only thing separating the two risk variants
    is whether they count a remediated incident at all.
    """
    fx.set_clock(api, "2026-07-20T00:00:00Z")
    vendor = fx.register_vendor(
        api,
        legal_name="Coastline Analytics LLC",
        breach_notification_hours=100,
        data_deletion_days=45,
        signed_state_addendum=True,
        subprocessor_disclosure_complete=True,
    )
    fx.disclose_subprocessor(
        api,
        vendor["id"],
        name="Emerald Hosting Ltd",
        country_code="IE",
        data_categories=[ELEMENT_STUDENT_NAME],
        purpose="Managed database hosting for the analytics warehouse.",
        sub_breach_notification_hours=96,
    )
    incident = fx.report_incident(
        api,
        vendor["id"],
        "2026-07-20T00:00:00Z",
        incident_type=INCIDENT_BREACH,
        affected_student_count=1400,
        max_data_tier=3,
    )
    fx.send_notification(api, incident["id"], 1400)
    fx.set_clock(api, "2026-07-20T06:00:00Z")
    fx.contain_incident(api, incident["id"], "2026-07-20T06:00:00Z")
    fx.resolve_incident(
        api,
        incident["id"],
        RESOLVE_REMEDIATE,
        remediation_note="Root cause closed and audited.",
    )

    app = fx.register_application(
        api,
        vendor["id"],
        name="Coastline Insights",
        category=CATEGORY_ASSESSMENT,
        grade_band_low=6,
        grade_band_high=8,
        sso_protocol=SSO_OIDC,
        accessibility_conformance_level=ACCESSIBILITY_WCAG21_AA,
        vpat_on_file=True,
    )
    fx.attest_integration(api, app["id"], sso_verified=True)
    teacher = fx.enroll_teacher(api, full_name="Marta Vela", employee_number="EMP-7002")
    teacher_headers = make_teacher_headers(teacher["id"])
    assignee = fx.enroll_analyst(api, CREDENTIAL_SENIOR, review_capacity_minutes=2400)
    decider = fx.enroll_analyst(api, CREDENTIAL_LEAD, review_capacity_minutes=2400)

    req = fx.draft_request(
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
    fx.submit_request(api, req["id"], teacher_headers)
    fx.triage_request(api, req["id"], TRIAGE_ACCEPT_FOR_REVIEW)
    review = fx.open_review(
        api,
        req["id"],
        assignee["id"],
        framework_set=list(ALL_FRAMEWORKS),
        estimated_minutes=240,
    )
    assignee_headers = make_analyst_headers(assignee["id"])
    decider_headers = make_analyst_headers(decider["id"])
    commitment = fx.propose_commitment(
        api,
        review["id"],
        ELEMENT_STUDENT_NAME,
        assignee_headers,
        justified_purpose=PURPOSE_61,
        retention_days=90,
        deletion_method=HARD_DELETE,
    )
    fx.decide_commitment(api, commitment["id"], DISPOSITION_ACCEPT, decider_headers)
    fx.issue_findings(api, review["id"], 0, assignee_headers)
    fx.decide_review(api, review["id"], DECISION_CLEAR, decider_headers)

    fx.set_clock(api, "2026-08-01T00:00:00Z")
    entry = fx.publish_entry(
        api,
        app["id"],
        review["id"],
        "2026-08-01T00:00:00Z",
        "2026-10-01T00:00:00Z",
        authorized_grade_band_low=6,
        authorized_grade_band_high=8,
    )
    fx.set_clock(api, "2026-09-05T00:00:00Z")
    fx.run_sweep(api)
    return {
        "vendor_id": vendor["id"],
        "application_id": app["id"],
        "review_id": review["id"],
        "entry_id": entry["id"],
    }


def _three_identical_tier_one_commitments(api):
    """Three tier-1 / 365-day / ANONYMIZE rows on one INSTRUCTIONAL_CONTENT app.

    Each row's raw product is 1.4375, so the rounding order is the only thing
    that decides whether the application totals 4.32 or 4.31.
    """
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
        employee_number="EMP-7003",
        school_code="ES-11",
        grade_bands_taught=[3, 4, 5],
    )
    teacher_headers = make_teacher_headers(teacher["id"])
    assignee = fx.enroll_analyst(api, CREDENTIAL_SENIOR, review_capacity_minutes=2400)
    decider = fx.enroll_analyst(api, CREDENTIAL_LEAD, review_capacity_minutes=2400)

    req = fx.draft_request(
        api,
        app["id"],
        teacher["id"],
        teacher_headers,
        instructional_justification=JUST_240,
        requested_data_elements=[
            ELEMENT_STUDENT_NAME,
            ELEMENT_GRADE_LEVEL,
            ELEMENT_PARENT_CONTACT,
        ],
        student_count_estimate=300,
        grade_band_low=3,
        grade_band_high=5,
    )
    fx.submit_request(api, req["id"], teacher_headers)
    fx.triage_request(api, req["id"], TRIAGE_ACCEPT_FOR_REVIEW)
    review = fx.open_review(
        api,
        req["id"],
        assignee["id"],
        framework_set=[FRAMEWORK_FERPA, FRAMEWORK_COPPA],
        estimated_minutes=180,
    )
    assignee_headers = make_analyst_headers(assignee["id"])
    decider_headers = make_analyst_headers(decider["id"])

    rows = []
    for element_code in (
        ELEMENT_STUDENT_NAME,
        ELEMENT_GRADE_LEVEL,
        ELEMENT_PARENT_CONTACT,
    ):
        rows.append(
            fx.propose_commitment(
                api,
                review["id"],
                element_code,
                assignee_headers,
                justified_purpose=PURPOSE_61,
                retention_days=365,
                deletion_method=ANONYMIZE,
            )
        )
    fx.decide_commitment(api, rows[0]["id"], DISPOSITION_ACCEPT, decider_headers)
    fx.decide_commitment(api, rows[1]["id"], DISPOSITION_ACCEPT, decider_headers)
    return {
        "vendor_id": vendor["id"],
        "application_id": app["id"],
        "commitment_ids": [row["id"] for row in rows],
        "decider_headers": decider_headers,
    }


def _two_requests_straddling_the_band_boundary(api):
    """Two drafts whose raw priority scores land at 55.00 and 60.01."""
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
    teacher = fx.enroll_teacher(api, full_name="Dana Reyes", employee_number="EMP-7004")
    teacher_headers = make_teacher_headers(teacher["id"])
    request_a = fx.draft_request(
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
    request_b = fx.draft_request(
        api,
        app["id"],
        teacher["id"],
        teacher_headers,
        instructional_justification=JUST_140,
        requested_data_elements=[ELEMENT_STUDENT_NAME],
        student_count_estimate=1,
        grade_band_low=6,
        grade_band_high=8,
    )
    return {
        "teacher_id": teacher["id"],
        "teacher_headers": teacher_headers,
        "request_a_id": request_a["id"],
        "request_b_id": request_b["id"],
    }


# ---------------------------------------------------------------------------
# Review compliance: provisional versus final
# ---------------------------------------------------------------------------


def test_provisional_and_final_compliance_scores_diverge_on_identical_rows(api):
    """The two compliance variants disagree by exactly 3.33 on one database.

    PRD: "Because both the input-set filter and the penalty terms differ,
    identical stored rows produce a different number under the two variants —
    `provisional_compliance_score` and `final_compliance_score` are not expected
    to agree, and neither is recomputed after the fact."

    Design: Difficulty/dual_variant_calc/review_compliance_provisional_vs_final_diverge
    """
    ctx = _findings_issued_review_with_mixed_commitments(api)

    fx.decide_review(
        api,
        ctx["review_id"],
        DECISION_CONDITIONAL,
        ctx["decider_headers"],
        decision_note="Approved with conditions pending retention rewrite.",
    )

    review = fx.read_review(api, ctx["review_id"])
    assert_decimal_equals(
        review["provisional_compliance_score"], "60.67", "provisional_compliance_score"
    )
    assert_decimal_equals(
        review["final_compliance_score"], "64.00", "final_compliance_score"
    )
    delta = round(
        review["final_compliance_score"] - review["provisional_compliance_score"], 2
    )
    assert_decimal_equals(delta, "3.33", "final minus provisional")


def test_conditional_decision_cascades_through_application_and_vendor(api):
    """A CONDITIONAL decision supersedes the undecided row and moves both parents.

    PRD: "Every commitment of this review still sitting in `PROPOSED` is moved
    to `SUPERSEDED`, after which the owning application's
    `exposed_sensitivity_points` is recomputed over the accepted set."

    Design: Difficulty/dual_variant_calc/review_compliance_provisional_vs_final_diverge
    """
    ctx = _findings_issued_review_with_mixed_commitments(api)

    fx.decide_review(
        api,
        ctx["review_id"],
        DECISION_CONDITIONAL,
        ctx["decider_headers"],
        decision_note="Approved with conditions pending retention rewrite.",
    )

    review = fx.read_review(api, ctx["review_id"])
    assert review["status"] == REVIEW_CONDITIONAL, (
        f"Expected CONDITIONAL, got {review['status']}"
    )

    undecided = fx.read_commitment(api, ctx["commitment_ids"][2])
    assert undecided["status"] == COMMITMENT_SUPERSEDED, (
        f"Expected the still-PROPOSED row to be SUPERSEDED, got {undecided['status']}"
    )
    assert undecided["is_minimized"] is False, (
        "A 900-day retention term cannot be minimized"
    )

    app = fx.read_application(api, ctx["application_id"])
    assert app["status"] == APPLICATION_APPROVED_WITH_CONDITIONS, (
        f"Expected APPROVED_WITH_CONDITIONS, got {app['status']}"
    )
    vendor = fx.read_vendor(api, ctx["vendor_id"])
    assert vendor["status"] == VENDOR_CONDITIONAL, (
        f"Expected the vendor to land on CONDITIONAL, got {vendor['status']}"
    )


# ---------------------------------------------------------------------------
# Vendor risk: live versus reauthorization
# ---------------------------------------------------------------------------


def test_live_and_reauthorization_risk_diverge_by_the_remediated_incident(api):
    """A remediated CRITICAL incident is counted live and forgiven on renewal.

    PRD: "The two variants differ in exactly one respect — the live variant
    counts incidents whose `response_status` is `REPORTED`, `CONTAINED`,
    `ESCALATED` or `REMEDIATED`, while the reauthorization variant forgives
    remediated incidents and counts only `REPORTED`, `CONTAINED` and
    `ESCALATED`."

    Design: Difficulty/dual_variant_calc/vendor_risk_live_vs_reauthorization_diverge
    """
    ctx = _remediated_critical_incident_with_expiring_entry(api)

    fx.reauthorize_entry(
        api,
        ctx["entry_id"],
        "2027-10-01T00:00:00Z",
        ctx["application_id"],
    )

    vendor = fx.read_vendor(api, ctx["vendor_id"])
    assert_decimal_equals(vendor["risk_score"], "50.50", "risk_score")
    assert_decimal_equals(
        vendor["reauthorization_risk_score"], "20.50", "reauthorization_risk_score"
    )
    delta = round(vendor["risk_score"] - vendor["reauthorization_risk_score"], 2)
    assert_decimal_equals(delta, "30.00", "live minus reauthorization")
    assert vendor["privacy_posture"] == POSTURE_WATCH, (
        f"Expected WATCH at 50.50, got {vendor['privacy_posture']}"
    )


def test_reauthorization_chains_the_successor_onto_the_predecessor_expiry(api):
    """The successor starts exactly where the predecessor ended.

    PRD: "A successor entry is created in `PUBLISHED`, with `predecessor_entry_id`
    pointing at the predecessor, `effective_from` set to the predecessor's
    `expires_at` — exact adjacency, which is legal precisely because windows are
    half-open — `expires_at` set to the supplied instant, `reauthorization_due_at`
    recomputed as the new expiry minus 30 days, and `published_review_score` carried
    over from the predecessor."

    Design: Difficulty/dual_variant_calc/vendor_risk_live_vs_reauthorization_diverge
    """
    ctx = _remediated_critical_incident_with_expiring_entry(api)

    successor = fx.reauthorize_entry(
        api,
        ctx["entry_id"],
        "2027-10-01T00:00:00Z",
        ctx["application_id"],
    )

    predecessor = fx.read_entry(api, ctx["entry_id"])
    assert predecessor["status"] == ENTRY_SUPERSEDED, (
        f"Expected the predecessor to be SUPERSEDED, got {predecessor['status']}"
    )
    assert successor["predecessor_entry_id"] == ctx["entry_id"], (
        "The successor must point back at the entry it renewed"
    )
    assert_instant_equals(
        successor["effective_from"], "2026-10-01T00:00:00.000Z", "effective_from"
    )
    assert_instant_equals(
        successor["reauthorization_due_at"],
        "2027-09-01T00:00:00.000Z",
        "reauthorization_due_at",
    )
    app = fx.read_application(api, ctx["application_id"])
    assert_decimal_equals(
        app["exposed_sensitivity_points"], "1.00", "exposed_sensitivity_points"
    )


# ---------------------------------------------------------------------------
# Exposure: round each element, then sum
# ---------------------------------------------------------------------------


def test_element_points_are_rounded_before_the_application_total_is_summed(api):
    """Three rows of 1.4375 total 4.32, not the sum-then-round answer 4.31.

    PRD: "The three factors are multiplied together and the product is rounded
    half up to two decimals — and that per-element rounding happens **before**
    anything is added up."

    Design: Difficulty/combinatorial_formula/exposed_points_round_each_element_then_sum
    """
    ctx = _three_identical_tier_one_commitments(api)

    fx.decide_commitment(
        api, ctx["commitment_ids"][2], DISPOSITION_ACCEPT, ctx["decider_headers"]
    )

    for commitment_id in ctx["commitment_ids"]:
        row = fx.read_commitment(api, commitment_id)
        assert_decimal_equals(row["element_points"], "1.44", "element_points")

    app = fx.read_application(api, ctx["application_id"])
    assert_decimal_equals(
        app["exposed_sensitivity_points"], "4.32", "exposed_sensitivity_points"
    )


def test_accepting_the_third_element_carries_the_total_into_vendor_risk(api):
    """The application total feeds the vendor's sensitivity load at one half.

    PRD: "The **sensitivity load** takes every application of this vendor whose
    `status` is `IN_REVIEW`, `APPROVED` or `APPROVED_WITH_CONDITIONS`, adds up
    their `exposed_sensitivity_points`, multiplies that sum by one half, and
    rounds the result half up to two decimals before it enters the total."

    Design: Difficulty/combinatorial_formula/exposed_points_round_each_element_then_sum
    """
    ctx = _three_identical_tier_one_commitments(api)

    third = fx.decide_commitment(
        api, ctx["commitment_ids"][2], DISPOSITION_ACCEPT, ctx["decider_headers"]
    )

    assert_integer_equals(third["sensitivity_tier"], 1, "sensitivity_tier")
    assert third["is_minimized"] is True, (
        "A tier-1 row at 365 days with a named purpose is minimized"
    )
    vendor = fx.read_vendor(api, ctx["vendor_id"])
    assert_decimal_equals(vendor["risk_score"], "2.16", "risk_score")
    assert vendor["privacy_posture"] == POSTURE_CLEAR, (
        f"Expected CLEAR at 2.16, got {vendor['privacy_posture']}"
    )


# ---------------------------------------------------------------------------
# Priority: the band comes from the raw score
# ---------------------------------------------------------------------------


def test_priority_band_is_read_off_the_raw_score_not_the_final_score(api):
    """Raw 55.00 stays STANDARD and stores 60.50, never the re-derived 66.00.

    PRD: "The band is a function of the **raw** score only. It is pinned at step
    two and never re-derived from the final `priority_score`."

    Design: Difficulty/combinatorial_formula/request_priority_band_pinned_to_pre_multiplier_raw
    """
    ctx = _two_requests_straddling_the_band_boundary(api)

    submitted = fx.submit_request(
        api, ctx["request_a_id"], ctx["teacher_headers"]
    )

    assert submitted["priority_band"] == BAND_STANDARD, (
        f"Raw 55.00 is STANDARD, got {submitted['priority_band']}"
    )
    assert_decimal_equals(submitted["priority_score"], "60.50", "priority_score")
    assert submitted["status"] == REQUEST_SUBMITTED, (
        f"Expected SUBMITTED, got {submitted['status']}"
    )
    assert_integer_equals(submitted["revision_round"], 0, "revision_round")


def test_priority_band_high_floor_is_inclusive_on_the_raw_score(api):
    """Raw 60.01 clears the HIGH floor and stores 72.01.

    PRD: "`HIGH` when the raw score is at least 60, `STANDARD` when it is at
    least 30 but below 60, and `LOW` below 30."

    Design: Difficulty/combinatorial_formula/request_priority_band_pinned_to_pre_multiplier_raw
    """
    ctx = _two_requests_straddling_the_band_boundary(api)

    fx.submit_request(api, ctx["request_a_id"], ctx["teacher_headers"])
    submitted_b = fx.submit_request(api, ctx["request_b_id"], ctx["teacher_headers"])

    assert submitted_b["priority_band"] == BAND_HIGH, (
        f"Raw 60.01 is HIGH, got {submitted_b['priority_band']}"
    )
    assert_decimal_equals(submitted_b["priority_score"], "72.01", "priority_score")

    teacher = fx.read_teacher(api, ctx["teacher_id"])
    assert_integer_equals(teacher["open_request_count"], 2, "open_request_count")
