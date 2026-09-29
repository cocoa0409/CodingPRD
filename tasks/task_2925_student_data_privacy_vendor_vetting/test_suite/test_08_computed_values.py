"""Derived numbers: which rows feed a total, which constants are pinned in the
lookups, and how the age decay and the statutory ceilings bite.
"""

from test_helpers import (
    assert_decimal_equals,
    assert_instant_equals,
    assert_integer_equals,
    fixtures as fx,
    make_teacher_headers,
)
from test_helpers.constants import (
    ANONYMIZE,
    BAND_HIGH,
    BAND_STANDARD,
    CATEGORY_ASSESSMENT,
    CATEGORY_INSTRUCTIONAL_CONTENT,
    CLASSIFICATION_UNKNOWN_DOMAIN,
    CLOCK_DEFAULT_RENDERED,
    COMMITMENT_ACCEPTED,
    COMMITMENT_PROPOSED,
    COMMITMENT_REJECTED,
    CREDENTIAL_LEAD,
    CREDENTIAL_SENIOR,
    DETECTION_NEW,
    DISPOSITION_ACCEPT,
    DISPOSITION_REJECT,
    ELEMENT_GRADE_LEVEL,
    ELEMENT_PARENT_CONTACT,
    ELEMENT_STUDENT_NAME,
    HARD_DELETE,
    INCIDENT_SUBPROCESSOR_CHANGE,
    INCIDENT_UNAUTHORIZED_DISCLOSURE,
    JUST_122,
    JUST_240,
    JUST_426,
    NOTIFICATION_SENT,
    POSTURE_CLEAR,
    POSTURE_FROZEN,
    POSTURE_RESTRICTED,
    PURPOSE_35,
    PURPOSE_61,
    REQUEST_SUBMITTED,
    SEVERITY_CRITICAL,
    SEVERITY_HIGH,
    SOURCE_BROWSER_EXTENSION,
    SSO_LTI13,
    SSO_SAML2,
)

CLOCK_FOUR_MONTHS_EARLIER = "2026-04-01T00:00:00Z"


def _reading_product_chain(api):
    """A SCREENING review on a tier-2-capped instructional product."""
    return fx.screening_review_chain(
        api,
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
            "requested_data_elements": [
                ELEMENT_STUDENT_NAME,
                ELEMENT_GRADE_LEVEL,
                ELEMENT_PARENT_CONTACT,
            ],
            "grade_band_low": 3,
            "grade_band_high": 5,
            "student_count_estimate": 300,
        },
        review={"estimated_minutes": 180},
        assignee_level=CREDENTIAL_SENIOR,
        assignee_capacity=2400,
        decider_level=CREDENTIAL_LEAD,
    )


# ---------------------------------------------------------------------------
# Selector branches and input sets
# ---------------------------------------------------------------------------


def test_a_domain_that_matches_no_application_is_an_unknown_domain(api):
    """The unmatched branch short-circuits and uses the 30-point base.

    PRD: "If `application_id` is null, the `classification` is `UNKNOWN_DOMAIN`
    and `matched_catalog_entry_id` is null. Nothing else is examined: an
    unmatched domain is never compared to any window."

    Design: Corner/calculations/detection_with_no_matched_application_is_unknown_domain
    """
    fx.set_clock(api)

    detection = fx.observe_detection(
        api,
        "quizmaster.example.net",
        "2026-07-30T09:15:00Z",
        school_code="MS-04",
        source=SOURCE_BROWSER_EXTENSION,
        distinct_user_count=30,
        session_count=120,
    )

    assert detection["application_id"] is None, (
        f"No application was ever registered, got {detection['application_id']!r}"
    )
    assert detection["classification"] == CLASSIFICATION_UNKNOWN_DOMAIN, (
        f"Expected UNKNOWN_DOMAIN, got {detection['classification']}"
    )
    assert detection["matched_catalog_entry_id"] is None, (
        f"Nothing else is examined, got {detection['matched_catalog_entry_id']!r}"
    )
    assert_decimal_equals(detection["exposure_score"], "48.00", "exposure_score")
    assert detection["status"] == DETECTION_NEW, (
        f"Expected NEW, got {detection['status']}"
    )
    assert detection["triaged_by_user_id"] is None, (
        f"No triage has happened, got {detection['triaged_by_user_id']!r}"
    )


def test_only_accepted_commitments_feed_the_exposure_total(api):
    """A proposed row and a rejected row are both worth nothing.

    PRD: "An application's `exposed_sensitivity_points` is then the sum of the
    already-rounded `element_points` of every commitment that is currently
    `ACCEPTED` and belongs to any review of that application, with the sum itself
    rounded half up to two decimals. Commitments in `PROPOSED`, `REJECTED` or
    `SUPERSEDED` contribute nothing."

    Design: Corner/calculations/exposed_points_input_set_excludes_proposed_and_rejected_rows
    """
    chain = _reading_product_chain(api)
    accepted = fx.propose_commitment(
        api,
        chain.review_id,
        ELEMENT_STUDENT_NAME,
        chain.assignee_headers,
        justified_purpose=PURPOSE_61,
        retention_days=365,
        deletion_method=ANONYMIZE,
    )
    left_proposed = fx.propose_commitment(
        api,
        chain.review_id,
        ELEMENT_GRADE_LEVEL,
        chain.assignee_headers,
        justified_purpose=PURPOSE_61,
        retention_days=90,
        deletion_method=HARD_DELETE,
    )
    rejected = fx.propose_commitment(
        api,
        chain.review_id,
        ELEMENT_PARENT_CONTACT,
        chain.assignee_headers,
        justified_purpose=PURPOSE_61,
        retention_days=90,
        deletion_method=HARD_DELETE,
    )
    fx.decide_commitment(api, rejected["id"], DISPOSITION_REJECT, chain.decider_headers)

    decided = fx.decide_commitment(
        api, accepted["id"], DISPOSITION_ACCEPT, chain.decider_headers
    )

    assert decided["status"] == COMMITMENT_ACCEPTED, (
        f"Expected ACCEPTED, got {decided['status']}"
    )
    assert_decimal_equals(decided["element_points"], "1.44", "element_points")
    assert fx.read_commitment(api, left_proposed["id"])["status"] == COMMITMENT_PROPOSED, (
        "The undecided row must stay PROPOSED"
    )
    assert fx.read_commitment(api, rejected["id"])["status"] == COMMITMENT_REJECTED, (
        "The rejected row must stay REJECTED"
    )
    app = fx.read_application(api, chain.application_id)
    assert_decimal_equals(
        app["exposed_sensitivity_points"], "1.44", "exposed_sensitivity_points"
    )
    vendor = fx.read_vendor(api, chain.vendor_id)
    assert_decimal_equals(vendor["risk_score"], "0.72", "risk_score")
    assert vendor["privacy_posture"] == POSTURE_CLEAR, (
        f"Expected CLEAR, got {vendor['privacy_posture']}"
    )


# ---------------------------------------------------------------------------
# The age decay step and the statutory ceiling
# ---------------------------------------------------------------------------


def test_an_incident_weighs_half_once_it_is_older_than_ninety_days(api):
    """At 122 whole days the HIGH weight drops from 18.00 to 9.00.

    PRD: "An incident aged 90 days or fewer carries its full weight; one aged
    more than 90 but no more than 365 days carries half its weight; one older
    than 365 days contributes nothing at all."

    Design: Corner/calculations/incident_weight_halves_once_past_the_ninety_day_shelf
    """
    fx.set_clock(api, CLOCK_FOUR_MONTHS_EARLIER)
    vendor = fx.register_vendor(api, legal_name="Brightpath Reading Co")
    incident = fx.report_incident(
        api,
        vendor["id"],
        CLOCK_FOUR_MONTHS_EARLIER,
        incident_type=INCIDENT_UNAUTHORIZED_DISCLOSURE,
        affected_student_count=500,
        max_data_tier=2,
    )
    fx.send_notification(api, incident["id"], 500)
    before = fx.read_vendor(api, vendor["id"])
    assert_decimal_equals(before["risk_score"], "18.00", "risk_score at full weight")
    fx.set_clock(api)

    sweep = fx.run_sweep(api)

    assert_integer_equals(
        sweep["overdue_notification_count"], 0, "overdue_notification_count"
    )
    assert_integer_equals(sweep["evaluated_entry_count"], 0, "evaluated_entry_count")
    aged = fx.read_incident(api, incident["id"])
    assert aged["severity"] == SEVERITY_HIGH, (
        f"500 students at tier 2 is HIGH, got {aged['severity']}"
    )
    assert_instant_equals(
        aged["notification_due_at"], "2026-04-03T00:00:00.000Z", "notification_due_at"
    )
    assert aged["notification_status"] == NOTIFICATION_SENT, (
        f"The notification went out inside the window, got {aged['notification_status']}"
    )
    fx.contain_incident(api, incident["id"])
    after = fx.read_vendor(api, vendor["id"])
    assert_decimal_equals(after["risk_score"], "9.00", "risk_score at half weight")
    assert after["privacy_posture"] == POSTURE_RESTRICTED, (
        f"The incident is still open, got {after['privacy_posture']}"
    )


def test_the_notification_deadline_takes_the_stricter_of_contract_and_statute(api):
    """A 12-hour promise binds, and a 96-hour promise is pulled to 24.

    PRD: "The effective allowance is the **minimum** of the vendor's contractual
    `breach_notification_hours` and that statutory ceiling — never the maximum —
    and `notification_due_at` is `detected_at` plus the effective allowance."

    Design: Corner/calculations/notification_due_takes_the_stricter_of_contract_and_statute
    """
    fx.set_clock(api)
    strict = fx.register_vendor(
        api, legal_name="Strict Terms Vendor", breach_notification_hours=12
    )
    lax = fx.register_vendor(
        api, legal_name="Lax Terms Vendor", breach_notification_hours=96
    )

    strict_incident = fx.report_incident(
        api,
        strict["id"],
        "2026-08-01T00:00:00Z",
        incident_type=INCIDENT_SUBPROCESSOR_CHANGE,
        affected_student_count=5,
        max_data_tier=4,
    )
    lax_incident = fx.report_incident(
        api,
        lax["id"],
        "2026-08-01T00:00:00Z",
        incident_type=INCIDENT_SUBPROCESSOR_CHANGE,
        affected_student_count=5,
        max_data_tier=4,
    )

    assert strict_incident["severity"] == SEVERITY_CRITICAL, (
        f"Tier 4 forces CRITICAL, got {strict_incident['severity']}"
    )
    assert_instant_equals(
        strict_incident["notification_due_at"],
        "2026-08-01T12:00:00.000Z",
        "notification_due_at of the tighter promise",
    )
    assert lax_incident["severity"] == SEVERITY_CRITICAL, (
        f"Tier 4 forces CRITICAL, got {lax_incident['severity']}"
    )
    assert_instant_equals(
        lax_incident["notification_due_at"],
        "2026-08-02T00:00:00.000Z",
        "notification_due_at pulled down to the statute",
    )
    strict_after = fx.read_vendor(api, strict["id"])
    lax_after = fx.read_vendor(api, lax["id"])
    assert_decimal_equals(strict_after["risk_score"], "30.00", "strict risk_score")
    assert_decimal_equals(lax_after["risk_score"], "40.00", "lax risk_score")
    assert strict_after["privacy_posture"] == POSTURE_FROZEN, (
        f"Expected FROZEN, got {strict_after['privacy_posture']}"
    )
    assert lax_after["privacy_posture"] == POSTURE_FROZEN, (
        f"Expected FROZEN, got {lax_after['privacy_posture']}"
    )
    assert_integer_equals(strict_after["open_incident_count"], 1, "open_incident_count")
    assert_integer_equals(lax_after["open_incident_count"], 1, "open_incident_count")


# ---------------------------------------------------------------------------
# Pinned lookup constants
# ---------------------------------------------------------------------------


def test_the_justification_bonus_is_a_three_step_length_lookup(api):
    """The bonus alone tips the longest request across the HIGH boundary.

    PRD: "a justification bonus is added, worth 15 points when the effective
    `instructional_justification` is at least 400 characters, 8 points when it is
    at least 240 but under 400, and nothing below that."

    Design: Corner/calculations/justification_bonus_uses_three_pinned_length_tiers
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
    )
    teacher = fx.enroll_teacher(
        api,
        full_name="Dana Reyes",
        employee_number="EMP-7111",
        school_code="MS-04",
        grade_bands_taught=[6, 7, 8],
    )
    teacher_headers = make_teacher_headers(teacher["id"])
    expectations = (
        (JUST_122, "51.70", BAND_STANDARD),
        (JUST_240, "60.50", BAND_STANDARD),
        (JUST_426, "74.40", BAND_HIGH),
    )
    drafted = [
        fx.draft_request(
            api,
            app["id"],
            teacher["id"],
            teacher_headers,
            instructional_justification=justification,
            requested_data_elements=[ELEMENT_STUDENT_NAME],
            student_count_estimate=700,
            grade_band_low=7,
            grade_band_high=8,
        )
        for justification, _score, _band in expectations
    ]

    submitted = [
        fx.submit_request(api, request["id"], teacher_headers) for request in drafted
    ]

    for row, (_justification, expected_score, expected_band) in zip(
        submitted, expectations
    ):
        assert_decimal_equals(row["priority_score"], expected_score, "priority_score")
        assert row["priority_band"] == expected_band, (
            f"Expected {expected_band}, got {row['priority_band']}"
        )
        assert row["status"] == REQUEST_SUBMITTED, (
            f"Expected SUBMITTED, got {row['status']}"
        )
        assert_instant_equals(
            row["submitted_at"], CLOCK_DEFAULT_RENDERED, "submitted_at"
        )
    filer = fx.read_teacher(api, teacher["id"])
    assert_integer_equals(filer["open_request_count"], 3, "open_request_count")


def test_minimization_turns_on_the_purpose_floor_and_the_retention_soft_cap(api):
    """A 35-character purpose fails, 365 days passes and 366 fails.

    PRD: "all four of its conditions must hold: the element's `sensitivity_tier`
    is no greater than the owning application's `max_permitted_tier`;
    `retention_days` is no more than 365, so exactly 365 days is minimized and
    366 is not; `deletion_method` is anything other than `AGGREGATE_ONLY`; and
    `justified_purpose` runs to at least 40 characters."

    Design: Corner/calculations/is_minimized_flips_on_the_purpose_length_and_retention_soft_cap
    """
    chain = _reading_product_chain(api)

    short_purpose = fx.propose_commitment(
        api,
        chain.review_id,
        ELEMENT_STUDENT_NAME,
        chain.assignee_headers,
        justified_purpose=PURPOSE_35,
        retention_days=90,
        deletion_method=HARD_DELETE,
    )
    at_the_cap = fx.propose_commitment(
        api,
        chain.review_id,
        ELEMENT_GRADE_LEVEL,
        chain.assignee_headers,
        justified_purpose=PURPOSE_61,
        retention_days=365,
        deletion_method=HARD_DELETE,
    )
    over_the_cap = fx.propose_commitment(
        api,
        chain.review_id,
        ELEMENT_PARENT_CONTACT,
        chain.assignee_headers,
        justified_purpose=PURPOSE_61,
        retention_days=366,
        deletion_method=HARD_DELETE,
    )

    assert short_purpose["is_minimized"] is False, (
        "A 35-character purpose is below the floor, got "
        f"{short_purpose['is_minimized']!r}"
    )
    assert at_the_cap["is_minimized"] is True, (
        f"Exactly 365 days is minimized, got {at_the_cap['is_minimized']!r}"
    )
    assert over_the_cap["is_minimized"] is False, (
        f"366 days is not minimized, got {over_the_cap['is_minimized']!r}"
    )
    for row in (short_purpose, at_the_cap, over_the_cap):
        assert row["status"] == COMMITMENT_PROPOSED, (
            f"The soft cap never rejects the write, got {row['status']}"
        )
        assert_integer_equals(row["sensitivity_tier"], 1, "sensitivity_tier")
    app = fx.read_application(api, chain.application_id)
    assert_decimal_equals(
        app["exposed_sensitivity_points"], "0.00", "exposed_sensitivity_points"
    )
