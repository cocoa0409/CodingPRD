"""Business-rule gates: conditional ceilings, cross-entity comparisons, the
inclusive window boundary, the publication gate order and the capacity aggregate.
"""

from test_helpers import (
    ADMIN_HEADERS,
    assert_decimal_equals,
    assert_instant_equals,
    assert_integer_equals,
    factories as fac,
    fixtures as fx,
    make_analyst_headers,
    make_teacher_headers,
    validate_error,
    validate_paginated,
    validate_success,
)
from test_helpers.api_errors import (
    ERR_ACCESSIBILITY_CONFORMANCE_INSUFFICIENT,
    ERR_ANALYST_CAPACITY_EXCEEDED,
    ERR_DISPOSITION_NOT_APPLICABLE,
    ERR_ELEMENT_TIER_NOT_PERMITTED,
    ERR_GRADE_BAND_OUT_OF_SCOPE,
    ERR_JUSTIFICATION_TOO_SHORT,
    ERR_NO_DATA_ELEMENTS,
    ERR_REMEDIATION_WINDOW_CLOSED,
    ERR_RETENTION_EXCEEDS_STATUTORY_CAP,
    ERR_SSO_NOT_VERIFIED,
    ERR_SUBPROCESSOR_DISCLOSURE_INCOMPLETE,
    ERR_SUBPROCESSOR_NOTIFICATION_TERMS_WEAKER,
    ERR_WHITELIST_REQUIRES_ACTIVE_ENTRY,
)
from test_helpers.constants import (
    ACCESSIBILITY_WCAG21_A,
    ACCESSIBILITY_WCAG21_AA,
    ANONYMIZE,
    APPLICATION_APPROVED_WITH_CONDITIONS,
    BAND_HIGH,
    CATEGORY_ANALYTICS,
    CATEGORY_INSTRUCTIONAL_CONTENT,
    CLASSIFICATION_UNAUTHORIZED,
    CLOCK_DEFAULT,
    COMMITMENT_PROPOSED,
    COMMITMENT_REJECTED,
    CREDENTIAL_SENIOR,
    DECISION_CLEAR,
    DECISION_CONDITIONAL,
    DETECTION_BLOCKED,
    DETECTION_NEW,
    DISPOSITION_ACCEPT,
    DISPOSITION_FLAG,
    DISPOSITION_REJECT,
    DISPOSITION_VERIFY,
    ELEMENT_GEOLOCATION,
    ELEMENT_GRADE_LEVEL,
    ELEMENT_STUDENT_NAME,
    ENTRY_PUBLISHED,
    HARD_DELETE,
    JUST_115,
    JUST_240,
    POSTURE_RESTRICTED,
    PURPOSE_61,
    REQUEST_DRAFT,
    REQUEST_SUBMITTED,
    REQUEST_TRIAGED_FOR_REVIEW,
    REVIEW_CONDITIONAL,
    REVIEW_FINDINGS_ISSUED,
    REVIEW_REMEDIATION_SUBMITTED,
    SOURCE_MDM_INVENTORY,
    SSO_LTI13,
    SSO_SAML2,
    SUBPROCESSOR_DISCLOSED,
    SUBPROCESSOR_FLAGGED,
    SUBPROCESSOR_VERIFIED,
    TRIAGE_ACCEPT_FOR_REVIEW,
    TRIAGE_BLOCK,
    TRIAGE_CONFIRM_AUTHORIZED,
    TRIAGE_WHITELIST,
    VISIBILITY_HIDDEN,
    VISIBILITY_VISIBLE,
)

CLOCK_AT_THE_FIRST_DUE_INSTANT = "2026-08-15T00:00:00Z"
CLOCK_ONE_SECOND_LATE = "2026-08-29T00:00:01Z"


def _reading_product_chain(api, **overrides):
    """Grade 3-5 instructional content, capped at tier 2."""
    kwargs = dict(
        vendor={"legal_name": "Brightpath Reading Co"},
        application={
            "name": "Brightpath Readers",
            "category": CATEGORY_INSTRUCTIONAL_CONTENT,
            "grade_band_low": 3,
            "grade_band_high": 5,
            "sso_protocol": SSO_LTI13,
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


def _analytics_product_chain(api):
    """Grade 6-8 analytics, which the district caps at tier 3."""
    return fx.screening_review_chain(
        api,
        vendor={"legal_name": "Cascadia Student Systems", "data_deletion_days": 45},
        application={
            "name": "Cascadia Insights",
            "category": CATEGORY_ANALYTICS,
            "grade_band_low": 6,
            "grade_band_high": 8,
            "sso_protocol": "OIDC",
        },
        teacher={"school_code": "MS-04", "grade_bands_taught": [6, 7, 8]},
        request={
            "requested_data_elements": [ELEMENT_GEOLOCATION],
            "grade_band_low": 6,
            "grade_band_high": 8,
            "student_count_estimate": 700,
        },
        review={"estimated_minutes": 180},
        assignee_capacity=2400,
    )


# ---------------------------------------------------------------------------
# Conditional ceilings on the commitment register
# ---------------------------------------------------------------------------


def test_the_retention_ceiling_depends_on_the_element_tier(api):
    """731 days is refused for a tier-3 element and accepted for a tier-1 one.

    PRD: "Tiers 1 and 2 may be retained for up to 1825 days, tier 3 for up to 730 days,
    and tier 4 for no more than 365 days. A commitment breaching its tier's ceiling
    is refused with `ERR_RETENTION_EXCEEDS_STATUTORY_CAP`, so a `HEALTH_RECORD`
    commitment at 400 days never reaches the register even though 400 is inside the
    general 1 to 1825 range."

    Design: Corner/validations/retention_ceiling_is_conditional_on_the_element_tier
    """
    chain = _analytics_product_chain(api)
    token = fx.review_version(api, chain.review_id)

    over_the_tier_cap = api.create_commitment(
        fac.commitment_payload(
            chain.review_id,
            ELEMENT_GEOLOCATION,
            token,
            retention_days=731,
            deletion_method=HARD_DELETE,
            justified_purpose=PURPOSE_61,
        ),
        chain.assignee_headers,
    )

    validate_error(over_the_tier_cap, ERR_RETENTION_EXCEEDS_STATUTORY_CAP, 422)
    at_the_tier_cap = validate_success(
        api.create_commitment(
            fac.commitment_payload(
                chain.review_id,
                ELEMENT_GEOLOCATION,
                token,
                retention_days=730,
                deletion_method=HARD_DELETE,
                justified_purpose=PURPOSE_61,
            ),
            chain.assignee_headers,
        ),
        201,
    )
    assert_integer_equals(at_the_tier_cap["sensitivity_tier"], 3, "sensitivity_tier")
    assert_integer_equals(at_the_tier_cap["retention_days"], 730, "retention_days")
    assert at_the_tier_cap["is_minimized"] is False, (
        "730 days clears the statutory cap but not the 365-day soft cap, got "
        f"{at_the_tier_cap['is_minimized']!r}"
    )
    tier_one = validate_success(
        api.create_commitment(
            fac.commitment_payload(
                chain.review_id,
                ELEMENT_STUDENT_NAME,
                fx.review_version(api, chain.review_id),
                retention_days=731,
                deletion_method=HARD_DELETE,
                justified_purpose=PURPOSE_61,
            ),
            chain.assignee_headers,
        ),
        201,
    )
    assert_integer_equals(tier_one["sensitivity_tier"], 1, "sensitivity_tier")
    assert_integer_equals(tier_one["retention_days"], 731, "retention_days")


def test_an_over_tier_element_may_be_proposed_but_never_accepted(api):
    """The tier ceiling gates the acceptance, not the proposal.

    PRD: "An `ACCEPT` additionally requires the element's `sensitivity_tier` to
    be no greater than the application's `max_permitted_tier`, and an over-tier
    element is refused with `ERR_ELEMENT_TIER_NOT_PERMITTED` — such an element may
    be proposed and recorded, but it may never be accepted."

    Design: Corner/validations/element_tier_gate_bites_at_accept_not_at_propose
    """
    chain = fx.screening_review_chain(
        api,
        **_reading_product_chain(
            api, request={
                "requested_data_elements": [ELEMENT_GEOLOCATION],
                "grade_band_low": 3,
                "grade_band_high": 5,
                "student_count_estimate": 300,
            }
        ),
    )
    proposed = fx.propose_commitment(
        api,
        chain.review_id,
        ELEMENT_GEOLOCATION,
        chain.assignee_headers,
        justified_purpose=PURPOSE_61,
        retention_days=90,
        deletion_method=HARD_DELETE,
    )
    assert_integer_equals(proposed["sensitivity_tier"], 3, "sensitivity_tier")
    assert proposed["is_minimized"] is False, (
        f"A tier-3 element on a tier-2 product is not minimized, got "
        f"{proposed['is_minimized']!r}"
    )

    refused_acceptance = api.decide_commitment(
        proposed["id"], {"disposition": DISPOSITION_ACCEPT}, chain.decider_headers
    )

    validate_error(refused_acceptance, ERR_ELEMENT_TIER_NOT_PERMITTED, 422)
    assert fx.read_commitment(api, proposed["id"])["status"] == COMMITMENT_PROPOSED, (
        "The refused acceptance leaves the row PROPOSED"
    )
    rejected = fx.decide_commitment(
        api, proposed["id"], DISPOSITION_REJECT, chain.decider_headers
    )
    assert rejected["status"] == COMMITMENT_REJECTED, (
        f"An over-tier row is still rejectable, got {rejected['status']}"
    )
    app = fx.read_application(api, chain.application_id)
    assert_decimal_equals(
        app["exposed_sensitivity_points"], "0.00", "exposed_sensitivity_points"
    )
    vendor = fx.read_vendor(api, chain.vendor_id)
    assert_decimal_equals(vendor["risk_score"], "0.00", "risk_score")


# ---------------------------------------------------------------------------
# Cross-entity comparisons and the inclusive window boundary
# ---------------------------------------------------------------------------


def test_verifying_a_subprocessor_needs_terms_no_weaker_than_the_vendors(api):
    """72 against 48 is refused, and exactly 48 passes the comparison.

    PRD: "`VERIFY` moves `DISCLOSED` to `VERIFIED`, but only when the
    subprocessor's notification terms are at least as strict as the vendor's own:
    `sub_breach_notification_hours` must be less than or equal to the vendor's
    `breach_notification_hours`, and a weaker downstream term is refused with
    `ERR_SUBPROCESSOR_NOTIFICATION_TERMS_WEAKER`."

    Design: Corner/validations/subprocessor_verify_requires_terms_no_weaker_than_the_vendor
    """
    fx.set_clock(api)
    vendor = fx.register_vendor(
        api, legal_name="Brightpath Reading Co", breach_notification_hours=48
    )
    analyst = fx.enroll_analyst(
        api, CREDENTIAL_SENIOR, full_name="Ana Lopez", review_capacity_minutes=2400
    )
    analyst_headers = make_analyst_headers(analyst["id"])
    weak = fx.disclose_subprocessor(
        api,
        vendor["id"],
        name="Weak Terms Hosting",
        country_code="US",
        sub_breach_notification_hours=72,
    )
    equal = fx.disclose_subprocessor(
        api,
        vendor["id"],
        name="Equal Terms Hosting",
        country_code="US",
        sub_breach_notification_hours=48,
    )

    refused = api.review_subprocessor(
        weak["id"],
        fac.subprocessor_review_payload(
            DISPOSITION_VERIFY,
            reviewed_note="Terms are weaker than the prime contract.",
        ),
        analyst_headers,
    )

    validate_error(refused, ERR_SUBPROCESSOR_NOTIFICATION_TERMS_WEAKER, 422)
    still_disclosed = validate_success(api.get_subprocessor(weak["id"], ADMIN_HEADERS), 200)
    assert still_disclosed["status"] == SUBPROCESSOR_DISCLOSED, (
        f"Expected DISCLOSED, got {still_disclosed['status']}"
    )
    verified = fx.review_subprocessor(
        api,
        equal["id"],
        DISPOSITION_VERIFY,
        analyst_headers,
        reviewed_note="Terms match the prime contract exactly.",
    )
    assert verified["status"] == SUBPROCESSOR_VERIFIED, (
        f"Equality passes the comparison, got {verified['status']}"
    )
    flagged = fx.review_subprocessor(
        api,
        weak["id"],
        DISPOSITION_FLAG,
        analyst_headers,
        reviewed_note="Escalated to contract renegotiation.",
    )
    assert flagged["status"] == SUBPROCESSOR_FLAGGED, (
        f"FLAG carries no term condition, got {flagged['status']}"
    )
    owner = fx.read_vendor(api, vendor["id"])
    assert_integer_equals(
        owner["flagged_subprocessor_count"], 1, "flagged_subprocessor_count"
    )
    assert_decimal_equals(owner["risk_score"], "0.00", "risk_score")
    assert owner["privacy_posture"] == POSTURE_RESTRICTED, (
        f"A flagged subprocessor restricts the vendor, got {owner['privacy_posture']}"
    )


def test_a_remediation_at_the_exact_due_instant_is_inside_the_window(api):
    """The comparison is inclusive at the deadline and closed one second later.

    PRD: "The window is inclusive: a remediation arriving when the logical clock
    is exactly at `remediation_due_at` succeeds, and one arriving after it is
    refused with `ERR_REMEDIATION_WINDOW_CLOSED`."

    Design: Corner/validations/remediation_window_is_inclusive_at_the_due_instant
    """
    chain = fx.screening_review_chain(api, **_reading_product_chain(api))
    fx.propose_commitment(
        api,
        chain.review_id,
        ELEMENT_STUDENT_NAME,
        chain.assignee_headers,
        justified_purpose=PURPOSE_61,
        retention_days=365,
        deletion_method=ANONYMIZE,
    )
    first_round = fx.issue_findings(
        api, chain.review_id, 2, chain.assignee_headers, decision_note="Round 1 findings."
    )
    assert_instant_equals(
        first_round["remediation_due_at"],
        "2026-08-15T00:00:00.000Z",
        "remediation_due_at",
    )
    fx.set_clock(api, CLOCK_AT_THE_FIRST_DUE_INSTANT)

    on_time = fx.submit_remediation(
        api,
        chain.review_id,
        2,
        chain.liaison_headers,
        remediation_note="Submitted at the exact due instant.",
    )

    assert on_time["status"] == REVIEW_REMEDIATION_SUBMITTED, (
        f"The deadline instant is inside the window, got {on_time['status']}"
    )
    assert_integer_equals(
        on_time["unresolved_findings_count"], 0, "unresolved_findings_count"
    )
    second_round = fx.issue_findings(
        api, chain.review_id, 1, chain.assignee_headers, decision_note="Round 2 findings."
    )
    assert_integer_equals(second_round["round_number"], 2, "round_number")
    assert_instant_equals(
        second_round["remediation_due_at"],
        "2026-08-29T00:00:00.000Z",
        "remediation_due_at",
    )
    fx.set_clock(api, CLOCK_ONE_SECOND_LATE)

    late = api.submit_remediation(
        chain.review_id,
        fac.remediation_payload(1, remediation_note="One second late."),
        chain.liaison_headers,
    )

    validate_error(late, ERR_REMEDIATION_WINDOW_CLOSED, 409)
    after = fx.read_review(api, chain.review_id)
    assert after["status"] == REVIEW_FINDINGS_ISSUED, (
        f"The late submission changed nothing, got {after['status']}"
    )
    assert_integer_equals(
        after["unresolved_findings_count"], 1, "unresolved_findings_count"
    )


# ---------------------------------------------------------------------------
# Submit-time gates on a draft request
# ---------------------------------------------------------------------------


def _reading_product_registry(api):
    """Vendor, application and teacher for the grade 3-5 reading product."""
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
    )
    teacher = fx.enroll_teacher(
        api,
        full_name="Ivy Chen",
        school_code="ES-11",
        grade_bands_taught=[3, 4, 5],
    )
    return app, teacher, make_teacher_headers(teacher["id"])


def test_the_justification_floor_is_checked_at_submit_not_at_create(api):
    """115 characters drafts fine, fails submit, and the resubmit repairs it.

    PRD: "A teacher may supply `instructional_justification`,
    `requested_data_elements` or `student_count_estimate` again on submission; any
    supplied value overwrites the stored draft value **before** any check or
    calculation runs, so a teacher can fix a too-short justification in the same
    call that submits it."

    Design: Corner/validations/justification_floor_is_enforced_at_submit_not_at_create
    """
    app, teacher, teacher_headers = _reading_product_registry(api)
    drafted = fx.draft_request(
        api,
        app["id"],
        teacher["id"],
        teacher_headers,
        instructional_justification=JUST_115,
        requested_data_elements=[ELEMENT_STUDENT_NAME],
        student_count_estimate=300,
        grade_band_low=3,
        grade_band_high=5,
    )

    too_short = api.submit_request(drafted["id"], {}, teacher_headers)

    validate_error(too_short, ERR_JUSTIFICATION_TOO_SHORT, 422)
    unchanged = fx.read_request(api, drafted["id"])
    assert unchanged["status"] == REQUEST_DRAFT, (
        f"The refused submit leaves the row DRAFT, got {unchanged['status']}"
    )
    assert unchanged["submitted_at"] is None, (
        f"Nothing was submitted, got {unchanged['submitted_at']!r}"
    )
    assert_integer_equals(
        fx.read_teacher(api, teacher["id"])["open_request_count"],
        0,
        "open_request_count",
    )

    repaired = fx.submit_request(
        api, drafted["id"], teacher_headers, instructional_justification=JUST_240
    )

    assert repaired["status"] == REQUEST_SUBMITTED, (
        f"The longer justification overwrites the draft, got {repaired['status']}"
    )
    assert repaired["priority_band"] == BAND_HIGH, (
        f"Expected HIGH, got {repaired['priority_band']}"
    )
    assert_decimal_equals(repaired["priority_score"], "85.20", "priority_score")
    assert_integer_equals(
        fx.read_teacher(api, teacher["id"])["open_request_count"],
        1,
        "open_request_count",
    )


def test_an_empty_element_list_is_refused_at_submit_and_fixable_in_the_same_call(api):
    """An empty list drafts fine, and the submit body may supply the elements.

    PRD: "Four further conditions then apply in this order: the vendor behind the
    requested application must not be frozen, or the submission is refused with
    `ERR_VENDOR_POSTURE_FROZEN`; the effective `instructional_justification` must be
    at least 120 characters long, or `ERR_JUSTIFICATION_TOO_SHORT`; the effective
    `requested_data_elements` must contain at least one element code, or
    `ERR_NO_DATA_ELEMENTS`; and a resubmission is permitted only while
    `revision_round` is still below 2, so once the counter has reached 2 any further
    submission is refused with `ERR_REVISION_LIMIT_EXCEEDED`."

    Design: Corner/validations/empty_data_element_list_is_refused_at_submit
    """
    app, teacher, teacher_headers = _reading_product_registry(api)
    drafted = fx.draft_request(
        api,
        app["id"],
        teacher["id"],
        teacher_headers,
        instructional_justification=JUST_240,
        requested_data_elements=[],
        student_count_estimate=300,
        grade_band_low=3,
        grade_band_high=5,
    )

    no_elements = api.submit_request(drafted["id"], {}, teacher_headers)

    validate_error(no_elements, ERR_NO_DATA_ELEMENTS, 422)
    assert fx.read_request(api, drafted["id"])["status"] == REQUEST_DRAFT, (
        "The refused submit leaves the row DRAFT"
    )

    repaired = fx.submit_request(
        api,
        drafted["id"],
        teacher_headers,
        requested_data_elements=[ELEMENT_STUDENT_NAME, ELEMENT_GRADE_LEVEL],
    )

    assert repaired["requested_data_elements"] == [
        ELEMENT_STUDENT_NAME,
        ELEMENT_GRADE_LEVEL,
    ], f"The submit body's elements are stored, got {repaired['requested_data_elements']}"
    assert repaired["priority_band"] == BAND_HIGH, (
        f"Expected HIGH, got {repaired['priority_band']}"
    )
    assert_decimal_equals(repaired["priority_score"], "85.20", "priority_score")


# ---------------------------------------------------------------------------
# The publication ladder
# ---------------------------------------------------------------------------


def _cleared_review_ready_to_publish(api, **overrides):
    """A CLEARED review on the grade 3-5 product with one proposed commitment.

    The commitment is left `PROPOSED`, which is enough for the mandatory findings
    round and keeps the accepted set empty, so the published score stays at the
    bare framework-and-contract total.
    """
    chain = fx.screening_review_chain(api, **_reading_product_chain(api, **overrides))
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
        api, chain.review_id, 0, chain.assignee_headers, decision_note="No open findings."
    )
    fx.decide_review(
        api,
        chain.review_id,
        DECISION_CLEAR,
        chain.decider_headers,
        decision_note="Cleared for publication.",
    )
    return chain


def test_the_accessibility_gate_is_reported_before_the_sso_gate(api):
    """Both gates fail, and the ladder names accessibility first.

    PRD: "The application's `accessibility_conformance_level` must be `WCAG21_AA`
    or `WCAG21_AAA` and its `vpat_on_file` must be true, or
    `ERR_ACCESSIBILITY_CONFORMANCE_INSUFFICIENT`. Its `sso_protocol` must be
    something other than `NONE` and `sso_verified` must be true, or
    `ERR_SSO_NOT_VERIFIED`."

    Design: Corner/validations/publication_gate_order_accessibility_before_sso
    """
    chain = _cleared_review_ready_to_publish(
        api,
        application={
            "name": "Brightpath Readers",
            "category": CATEGORY_INSTRUCTIONAL_CONTENT,
            "grade_band_low": 3,
            "grade_band_high": 5,
            "sso_protocol": SSO_SAML2,
            "accessibility_conformance_level": ACCESSIBILITY_WCAG21_A,
            "vpat_on_file": False,
        },
        attest=False,
    )
    entry_body = fac.catalog_entry_payload(
        chain.application_id,
        chain.review_id,
        CLOCK_DEFAULT,
        "2027-08-01T00:00:00Z",
        authorized_grade_band_low=3,
        authorized_grade_band_high=5,
    )

    both_gates_failing = api.create_catalog_entry(entry_body, ADMIN_HEADERS)

    validate_error(
        both_gates_failing, ERR_ACCESSIBILITY_CONFORMANCE_INSUFFICIENT, 422
    )
    fx.attest_integration(
        api,
        chain.application_id,
        sso_verified=False,
        accessibility_conformance_level=ACCESSIBILITY_WCAG21_AA,
        vpat_on_file=True,
    )

    only_sso_failing = api.create_catalog_entry(entry_body, ADMIN_HEADERS)

    validate_error(only_sso_failing, ERR_SSO_NOT_VERIFIED, 422)
    fx.attest_integration(api, chain.application_id, sso_verified=True)

    published = validate_success(
        api.create_catalog_entry(entry_body, ADMIN_HEADERS), 201
    )

    assert published["status"] == ENTRY_PUBLISHED, (
        f"Expected PUBLISHED, got {published['status']}"
    )
    assert_instant_equals(
        published["reauthorization_due_at"],
        "2027-07-02T00:00:00.000Z",
        "reauthorization_due_at",
    )
    app = fx.read_application(api, chain.application_id)
    assert app["catalog_visibility"] == VISIBILITY_VISIBLE, (
        f"Expected VISIBLE, got {app['catalog_visibility']}"
    )
    _rows, meta = validate_paginated(
        api.list_catalog_entries(ADMIN_HEADERS, application_id=chain.application_id)
    )
    assert_integer_equals(meta["total_count"], 1, "total_count")


def test_the_published_band_must_sit_inside_the_application_band(api):
    """Grade 2 is outside a 3-5 product, and the strict subset 4-5 publishes.

    PRD: "Finally the published band must sit inside the product's own band:
    `authorized_grade_band_low` must be at least the application's
    `grade_band_low` and `authorized_grade_band_high` must be no more than the
    application's `grade_band_high`, or `ERR_GRADE_BAND_OUT_OF_SCOPE`."

    Design: Corner/validations/publication_band_must_sit_inside_the_application_band
    """
    chain = _cleared_review_ready_to_publish(api)

    below_the_product_band = api.create_catalog_entry(
        fac.catalog_entry_payload(
            chain.application_id,
            chain.review_id,
            CLOCK_DEFAULT,
            "2027-08-01T00:00:00Z",
            authorized_grade_band_low=2,
            authorized_grade_band_high=5,
        ),
        ADMIN_HEADERS,
    )

    validate_error(below_the_product_band, ERR_GRADE_BAND_OUT_OF_SCOPE, 422)

    inside_the_product_band = fx.publish_entry(
        api,
        chain.application_id,
        chain.review_id,
        CLOCK_DEFAULT,
        "2027-08-01T00:00:00Z",
        authorized_grade_band_low=4,
        authorized_grade_band_high=5,
    )

    assert_integer_equals(
        inside_the_product_band["authorized_grade_band_low"],
        4,
        "authorized_grade_band_low",
    )
    assert_integer_equals(
        inside_the_product_band["authorized_grade_band_high"],
        5,
        "authorized_grade_band_high",
    )
    assert_decimal_equals(
        inside_the_product_band["published_review_score"],
        "60.00",
        "published_review_score",
    )
    app = fx.read_application(api, chain.application_id)
    assert app["catalog_visibility"] == VISIBILITY_VISIBLE, (
        f"Expected VISIBLE, got {app['catalog_visibility']}"
    )


def test_publication_is_refused_while_the_subprocessor_chain_is_undisclosed(api):
    """A flag on the vendor blocks a write two hops away on the catalog entry.

    PRD: "The vendor must assert a complete subprocessor chain, or
    `ERR_SUBPROCESSOR_DISCLOSURE_INCOMPLETE`."

    Design: Corner/validations/publication_requires_complete_subprocessor_disclosure
    """
    chain = fx.screening_review_chain(
        api,
        **_reading_product_chain(
            api,
            vendor={
                "legal_name": "Undisclosed Chain Vendor",
                "signed_state_addendum": True,
                "subprocessor_disclosure_complete": False,
            },
            application={
                "name": "Undisclosed Reader",
                "category": CATEGORY_INSTRUCTIONAL_CONTENT,
                "grade_band_low": 3,
                "grade_band_high": 5,
                "sso_protocol": SSO_LTI13,
            },
        ),
    )
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
        api, chain.review_id, 1, chain.assignee_headers, decision_note="One finding open."
    )
    decided = fx.decide_review(
        api,
        chain.review_id,
        DECISION_CONDITIONAL,
        chain.decider_headers,
        decision_note="Approved with conditions; the chain is not fully disclosed.",
    )
    assert decided["status"] == REVIEW_CONDITIONAL, (
        f"An undisclosed chain cannot be fully cleared, got {decided['status']}"
    )

    refused = api.create_catalog_entry(
        fac.catalog_entry_payload(
            chain.application_id,
            chain.review_id,
            CLOCK_DEFAULT,
            "2027-08-01T00:00:00Z",
            authorized_grade_band_low=3,
            authorized_grade_band_high=5,
        ),
        ADMIN_HEADERS,
    )

    validate_error(refused, ERR_SUBPROCESSOR_DISCLOSURE_INCOMPLETE, 422)
    _rows, meta = validate_paginated(
        api.list_catalog_entries(ADMIN_HEADERS, application_id=chain.application_id)
    )
    assert_integer_equals(meta["total_count"], 0, "total_count")
    app = fx.read_application(api, chain.application_id)
    assert app["catalog_visibility"] == VISIBILITY_HIDDEN, (
        f"Expected HIDDEN, got {app['catalog_visibility']}"
    )
    assert app["status"] == APPLICATION_APPROVED_WITH_CONDITIONS, (
        f"A conditional decision approves with conditions, got {app['status']}"
    )
    assert fx.read_review(api, chain.review_id)["status"] == REVIEW_CONDITIONAL, (
        "The decided review is untouched by the refused publication"
    )


# ---------------------------------------------------------------------------
# The workload aggregate
# ---------------------------------------------------------------------------


def test_analyst_capacity_is_checked_against_the_aggregate(api):
    """Two 240-minute reviews overrun a 400-minute analyst; 160 lands exactly on it.

    PRD: "Capacity is then enforced as the very last rung of the ladder: the
    assignee's freshly recomputed `allocated_review_minutes` plus the new review's
    `estimated_minutes` must not exceed that analyst's `review_capacity_minutes`,
    and an overload is refused with `ERR_ANALYST_CAPACITY_EXCEEDED`."

    Design: Corner/validations/analyst_capacity_is_an_aggregate_over_open_reviews
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
    )
    teacher = fx.enroll_teacher(
        api, full_name="Ivy Chen", school_code="ES-11", grade_bands_taught=[3, 4, 5]
    )
    teacher_headers = make_teacher_headers(teacher["id"])
    analyst = fx.enroll_analyst(
        api, CREDENTIAL_SENIOR, full_name="Ana Lopez", review_capacity_minutes=400
    )
    analyst_headers = make_analyst_headers(analyst["id"])
    triaged = []
    for element_code in (ELEMENT_STUDENT_NAME, ELEMENT_GRADE_LEVEL):
        request = fx.draft_request(
            api,
            app["id"],
            teacher["id"],
            teacher_headers,
            instructional_justification=JUST_240,
            requested_data_elements=[element_code],
            student_count_estimate=300,
            grade_band_low=3,
            grade_band_high=5,
        )
        fx.submit_request(api, request["id"], teacher_headers)
        fx.triage_request(
            api, request["id"], TRIAGE_ACCEPT_FOR_REVIEW, analyst_headers
        )
        triaged.append(request["id"])
    fx.open_review(
        api, triaged[0], analyst["id"], analyst_headers, estimated_minutes=240
    )
    assert_integer_equals(
        fx.read_analyst(api, analyst["id"])["allocated_review_minutes"],
        240,
        "allocated_review_minutes",
    )

    over_capacity = api.create_review(
        fac.review_payload(triaged[1], analyst["id"], estimated_minutes=240),
        analyst_headers,
    )

    validate_error(over_capacity, ERR_ANALYST_CAPACITY_EXCEEDED, 409)
    assert_integer_equals(
        fx.read_analyst(api, analyst["id"])["allocated_review_minutes"],
        240,
        "allocated_review_minutes",
    )
    assert fx.read_request(api, triaged[1])["status"] == REQUEST_TRIAGED_FOR_REVIEW, (
        "The refused review leaves its source request triaged and unconsumed"
    )

    exactly_at_capacity = fx.open_review(
        api, triaged[1], analyst["id"], analyst_headers, estimated_minutes=160
    )

    assert_integer_equals(
        exactly_at_capacity["estimated_minutes"], 160, "estimated_minutes"
    )
    assert_integer_equals(
        fx.read_analyst(api, analyst["id"])["allocated_review_minutes"],
        400,
        "allocated_review_minutes",
    )


# ---------------------------------------------------------------------------
# Two refusals, two different reasons
# ---------------------------------------------------------------------------


def test_the_two_refused_detection_dispositions_fail_for_different_reasons(api):
    """WHITELIST wants an entry; CONFIRM_AUTHORIZED wants an authorized reading.

    PRD: "The critical subtlety is that this gate reads the entry's state at the
    **current logical clock**, not at `observed_at`: a detection classified
    `EXPIRED_AUTHORIZATION` last month becomes whitelistable once the product is
    reauthorized and the matched entry is live again, while a detection classified
    `UNAUTHORIZED` can never be whitelisted at all because it has no matched entry
    to point at."

    Design: Corner/validations/detection_dispositions_gated_by_classification_and_active_entry
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
    )
    detection = fx.observe_detection(
        api,
        "readers.brightpath.example",
        "2026-07-31T12:00:00Z",
        application_id=app["id"],
        school_code="ES-11",
        source=SOURCE_MDM_INVENTORY,
        distinct_user_count=30,
        session_count=120,
    )
    assert detection["classification"] == CLASSIFICATION_UNAUTHORIZED, (
        f"A registered product with no entry is UNAUTHORIZED, got "
        f"{detection['classification']}"
    )
    assert_decimal_equals(detection["exposure_score"], "63.00", "exposure_score")

    no_entry_to_whitelist = api.triage_detection(
        detection["id"],
        fac.detection_triage_payload(
            TRIAGE_WHITELIST, note="No entry to whitelist against."
        ),
        ADMIN_HEADERS,
    )

    validate_error(no_entry_to_whitelist, ERR_WHITELIST_REQUIRES_ACTIVE_ENTRY, 422)

    not_authorized = api.triage_detection(
        detection["id"],
        fac.detection_triage_payload(
            TRIAGE_CONFIRM_AUTHORIZED, note="Classification does not support this."
        ),
        ADMIN_HEADERS,
    )

    validate_error(not_authorized, ERR_DISPOSITION_NOT_APPLICABLE, 422)
    untouched = fx.read_detection(api, detection["id"])
    assert untouched["status"] == DETECTION_NEW, (
        f"Neither refusal triaged the row, got {untouched['status']}"
    )
    assert untouched["triaged_by_user_id"] is None, (
        f"No triager was stamped, got {untouched['triaged_by_user_id']!r}"
    )

    blocked = fx.triage_detection(
        api, detection["id"], TRIAGE_BLOCK, ADMIN_HEADERS, note="Blocked at the filter."
    )

    assert blocked["status"] == DETECTION_BLOCKED, (
        f"BLOCK is the applicable disposition, got {blocked['status']}"
    )
