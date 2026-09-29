"""Endpoint behaviour: what the sweep reports about its own work, what a clock
move deliberately does not do, what a plain read already carries, and which
action endpoints refuse or mint a second row.
"""

from test_helpers import (
    ADMIN_HEADERS,
    assert_decimal_equals,
    assert_instant_equals,
    assert_integer_equals,
    factories as fac,
    fixtures as fx,
    validate_error,
    validate_paginated,
    validate_success,
)
from test_helpers.api_errors import ERR_APPLICATION_STATE_INVALID
from test_helpers.constants import (
    ACCESSIBILITY_NONE,
    ACCESSIBILITY_WCAG21_A,
    ACCESSIBILITY_WCAG21_AA,
    ANONYMIZE,
    APPLICATION_BLOCKED,
    APPLICATION_IN_REVIEW,
    CATEGORY_ASSESSMENT,
    CATEGORY_INSTRUCTIONAL_CONTENT,
    CLASSIFICATION_UNAUTHORIZED,
    CLOCK_DEFAULT,
    CLOCK_DEFAULT_RENDERED,
    CREDENTIAL_LEAD,
    CREDENTIAL_SENIOR,
    DECISION_BLOCK,
    DETECTION_ESCALATED,
    DISPOSITION_ACCEPT,
    ELEMENT_GEOLOCATION,
    ELEMENT_STUDENT_ID,
    ELEMENT_STUDENT_NAME,
    ENTRY_EXPIRED,
    ENTRY_EXPIRING_SOON,
    HARD_DELETE,
    INCIDENT_BREACH,
    INCIDENT_REPORTED,
    INCIDENT_UNAUTHORIZED_DISCLOSURE,
    NOTIFICATION_OVERDUE,
    NOTIFICATION_PENDING,
    POSTURE_CLEAR,
    POSTURE_FROZEN,
    POSTURE_RESTRICTED,
    PURPOSE_61,
    REQUEST_CLOSED_BLOCKED,
    REVIEW_BLOCKED,
    SEVERITY_MODERATE,
    SOURCE_NETWORK_DNS,
    SSO_LTI13,
    SSO_NONE,
    SSO_SAML2,
    TRIAGE_ESCALATE,
    VISIBILITY_HIDDEN,
    VISIBILITY_VISIBLE,
)

CLOCK_INSIDE_THE_REAUTHORIZATION_WINDOW = "2027-07-15T00:00:00Z"
CLOCK_AT_THE_EXPIRY = "2027-08-01T00:00:00Z"
CLOCK_TWO_DAYS_PAST_THE_DEADLINE = "2026-08-04T00:00:00Z"
CLOCK_FOUR_DAYS_ON = "2026-08-05T00:00:00Z"
PURPOSE_MAPPING = (
    "Campus-level session mapping for proctored assessment integrity checks."
)


def _reading_product_chain(api, **overrides):
    """Grade 3-5 instructional content on a fully attested product."""
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


def _reported_incident_on_a_lakeside_vendor(api):
    """A MODERATE breach whose 48-hour promise falls due on 2026-08-02."""
    fx.set_clock(api)
    vendor = fx.register_vendor(
        api, legal_name="Lakeside Analytics", breach_notification_hours=48
    )
    incident = fx.report_incident(
        api,
        vendor["id"],
        "2026-07-31T00:00:00Z",
        incident_type=INCIDENT_BREACH,
        affected_student_count=50,
        max_data_tier=2,
    )
    assert incident["severity"] == SEVERITY_MODERATE, (
        f"50 students at tier 2 is MODERATE, got {incident['severity']}"
    )
    assert_instant_equals(
        incident["notification_due_at"],
        "2026-08-02T00:00:00.000Z",
        "notification_due_at",
    )
    assert incident["notification_status"] == NOTIFICATION_PENDING, (
        f"No notification has gone out, got {incident['notification_status']}"
    )
    assert fx.read_vendor(api, vendor["id"])["privacy_posture"] == POSTURE_RESTRICTED, (
        "A reported incident that is not yet overdue only restricts the vendor"
    )
    return vendor, incident


# ---------------------------------------------------------------------------
# The sweep reports its own work
# ---------------------------------------------------------------------------


def test_the_sweep_walks_the_window_and_counts_only_what_it_moved(api):
    """One entry, three sweeps: EXPIRING_SOON, then nothing, then EXPIRED.

    PRD: "It takes no payload, reads the logical clock, and is idempotent for a
    fixed clock — running it twice without moving the clock changes nothing the
    second time."

    Design: Corner/endpoints/sweep_moves_the_window_and_reports_its_own_counts
    """
    chain = fx.published_entry_chain(
        api,
        CLOCK_DEFAULT,
        CLOCK_AT_THE_EXPIRY,
        authorized_grade_band_low=3,
        authorized_grade_band_high=5,
        **_reading_product_chain(api),
    )
    assert_instant_equals(
        fx.read_entry(api, chain.entry_id)["reauthorization_due_at"],
        "2027-07-02T00:00:00.000Z",
        "reauthorization_due_at",
    )
    fx.set_clock(api, CLOCK_INSIDE_THE_REAUTHORIZATION_WINDOW)

    first = fx.run_sweep(api)

    assert_integer_equals(first["expiring_soon_count"], 1, "expiring_soon_count")
    assert_integer_equals(first["expired_count"], 0, "expired_count")
    assert_integer_equals(
        first["overdue_notification_count"], 0, "overdue_notification_count"
    )
    assert_integer_equals(first["evaluated_entry_count"], 1, "evaluated_entry_count")
    assert_integer_equals(
        first["recomputed_vendor_count"], 1, "recomputed_vendor_count"
    )
    assert fx.read_entry(api, chain.entry_id)["status"] == ENTRY_EXPIRING_SOON, (
        "The entry has entered its reauthorization window"
    )
    assert (
        fx.read_application(api, chain.application_id)["catalog_visibility"]
        == VISIBILITY_VISIBLE
    ), "An EXPIRING_SOON entry is still visible to teachers"

    second = fx.run_sweep(api)

    assert_integer_equals(
        second["expiring_soon_count"], 0, "expiring_soon_count on a repeat sweep"
    )
    assert_integer_equals(
        second["expired_count"], 0, "expired_count on a repeat sweep"
    )
    fx.set_clock(api, CLOCK_AT_THE_EXPIRY)

    third = fx.run_sweep(api)

    assert_integer_equals(third["expired_count"], 1, "expired_count")
    assert_integer_equals(third["expiring_soon_count"], 0, "expiring_soon_count")
    assert fx.read_entry(api, chain.entry_id)["status"] == ENTRY_EXPIRED, (
        "The upper bound is exclusive, so the entry expires at its own instant"
    )
    assert (
        fx.read_application(api, chain.application_id)["catalog_visibility"]
        == VISIBILITY_HIDDEN
    ), "Nothing visible is left, so the product drops out of the catalog"


def test_the_sweep_marks_the_notification_overdue_and_freezes_the_vendor(api):
    """One sweep flips the notification and then re-reads the posture.

    PRD: "Afterwards the sweep recomputes `catalog_visibility` on every touched
    application, and `risk_score` followed by `privacy_posture` on every touched
    vendor — which is how an overdue notification silently freezes a vendor
    overnight."

    Design: Corner/endpoints/sweep_marks_the_notification_overdue_and_freezes_the_vendor
    """
    vendor, incident = _reported_incident_on_a_lakeside_vendor(api)
    fx.set_clock(api, CLOCK_TWO_DAYS_PAST_THE_DEADLINE)

    sweep = fx.run_sweep(api)

    assert_integer_equals(
        sweep["overdue_notification_count"], 1, "overdue_notification_count"
    )
    assert_integer_equals(sweep["evaluated_entry_count"], 0, "evaluated_entry_count")
    assert_integer_equals(sweep["expiring_soon_count"], 0, "expiring_soon_count")
    assert_integer_equals(sweep["expired_count"], 0, "expired_count")
    assert_integer_equals(
        sweep["recomputed_vendor_count"], 1, "recomputed_vendor_count"
    )
    swept = fx.read_incident(api, incident["id"])
    assert swept["notification_status"] == NOTIFICATION_OVERDUE, (
        f"Expected OVERDUE, got {swept['notification_status']}"
    )
    assert swept["response_status"] == INCIDENT_REPORTED, (
        f"The response axis is untouched, got {swept['response_status']}"
    )
    frozen = fx.read_vendor(api, vendor["id"])
    assert_decimal_equals(frozen["risk_score"], "8.00", "risk_score")
    assert frozen["privacy_posture"] == POSTURE_FROZEN, (
        f"An overdue notification is the top rung, got {frozen['privacy_posture']}"
    )


def test_moving_the_clock_writes_no_row_and_runs_no_sweep(api):
    """Time passes the deadline and the notification is still PENDING.

    PRD: "An administrative test-driving capability sets the clock to a supplied
    `current_utc` instant and echoes it back; setting the clock modifies no stored
    row and implies no sweep — the nightly compliance sweep must always be invoked
    explicitly."

    Design: Corner/endpoints/clock_endpoint_moves_time_without_touching_any_row
    """
    vendor, incident = _reported_incident_on_a_lakeside_vendor(api)

    echoed = fx.set_clock(api, CLOCK_FOUR_DAYS_ON)

    assert_instant_equals(echoed["current_utc"], "2026-08-05T00:00:00.000Z", "current_utc")
    unswept = fx.read_incident(api, incident["id"])
    assert unswept["notification_status"] == NOTIFICATION_PENDING, (
        f"No sweep has run, got {unswept['notification_status']}"
    )
    assert_instant_equals(
        unswept["notification_due_at"],
        "2026-08-02T00:00:00.000Z",
        "notification_due_at",
    )
    assert fx.read_vendor(api, vendor["id"])["privacy_posture"] == POSTURE_RESTRICTED, (
        "Without an explicit sweep the vendor never reaches FROZEN"
    )


# ---------------------------------------------------------------------------
# What a plain read already carries
# ---------------------------------------------------------------------------


def test_a_plain_application_read_already_carries_the_derived_numbers(api):
    """Two accepted rows of 2.50 and 8.63 read back as 11.13 on the product.

    PRD: "and an application's `exposed_sensitivity_points` is re-summed from
    scratch. Full recomputation is what makes the compensating actions of §3
    exact: rejecting a previously accepted commitment returns the application's
    exposure total to precisely the value it held before that commitment was
    accepted, with no drift."

    Design: Corner/endpoints/computed_read_of_an_application_matches_its_accepted_commitments
    """
    chain = fx.screening_review_chain(
        api,
        vendor={"legal_name": "Meridian Practice Labs"},
        application={
            "name": "Meridian Practice",
            "category": CATEGORY_ASSESSMENT,
            "grade_band_low": 6,
            "grade_band_high": 8,
            "sso_protocol": SSO_SAML2,
            "accessibility_conformance_level": ACCESSIBILITY_WCAG21_AA,
            "vpat_on_file": True,
        },
        teacher={"school_code": "MS-04", "grade_bands_taught": [6, 7, 8]},
        request={
            "requested_data_elements": [ELEMENT_STUDENT_ID, ELEMENT_GEOLOCATION],
            "grade_band_low": 6,
            "grade_band_high": 8,
            "student_count_estimate": 300,
        },
        review={"estimated_minutes": 180},
        assignee_level=CREDENTIAL_SENIOR,
        assignee_capacity=2400,
        decider_level=CREDENTIAL_LEAD,
        attest=False,
    )
    tier_two = fx.propose_commitment(
        api,
        chain.review_id,
        ELEMENT_STUDENT_ID,
        chain.liaison_headers,
        justified_purpose=PURPOSE_61,
        retention_days=90,
        deletion_method=HARD_DELETE,
    )
    tier_two = fx.decide_commitment(
        api, tier_two["id"], DISPOSITION_ACCEPT, chain.decider_headers
    )
    tier_three = fx.propose_commitment(
        api,
        chain.review_id,
        ELEMENT_GEOLOCATION,
        chain.liaison_headers,
        justified_purpose=PURPOSE_MAPPING,
        retention_days=365,
        deletion_method=ANONYMIZE,
    )
    tier_three = fx.decide_commitment(
        api, tier_three["id"], DISPOSITION_ACCEPT, chain.decider_headers
    )

    app = validate_success(api.get_application(chain.application_id, ADMIN_HEADERS), 200)

    assert_decimal_equals(
        app["exposed_sensitivity_points"], "11.13", "exposed_sensitivity_points"
    )
    assert_integer_equals(app["max_permitted_tier"], 4, "max_permitted_tier")
    assert app["category"] == CATEGORY_ASSESSMENT, (
        f"Expected ASSESSMENT, got {app['category']}"
    )
    assert app["status"] == APPLICATION_IN_REVIEW, (
        f"The review is still open, got {app['status']}"
    )
    assert app["catalog_visibility"] == VISIBILITY_HIDDEN, (
        f"Nothing is published, got {app['catalog_visibility']}"
    )
    assert app["sso_verified"] is False, (
        f"The district never attested, got {app['sso_verified']!r}"
    )
    assert_decimal_equals(tier_two["element_points"], "2.50", "element_points")
    assert_decimal_equals(tier_three["element_points"], "8.63", "element_points")
    vendor = validate_success(api.get_vendor(chain.vendor_id, ADMIN_HEADERS), 200)
    assert_decimal_equals(vendor["risk_score"], "5.57", "risk_score")
    assert vendor["privacy_posture"] == POSTURE_CLEAR, (
        f"Expected CLEAR, got {vendor['privacy_posture']}"
    )


# ---------------------------------------------------------------------------
# Action endpoints: one refusal and one cross-reference
# ---------------------------------------------------------------------------


def test_attestation_is_accepted_until_the_decision_blocks_the_product(api):
    """The same call that worked while IN_REVIEW is refused once BLOCKED.

    PRD: "Attestation is permitted from `CANDIDATE`, `IN_REVIEW`, `APPROVED` and
    `APPROVED_WITH_CONDITIONS`, because both facts are gated at publication time
    — that is, after the review has already been decided — and an approved
    application must still be able to finish its attestation. Only a `BLOCKED`
    application refuses to re-attest, with `ERR_APPLICATION_STATE_INVALID`."

    Design: Corner/endpoints/attest_integration_is_refused_once_the_application_is_blocked
    """
    chain = fx.screening_review_chain(
        api,
        **_reading_product_chain(
            api,
            application={
                "name": "Brightpath Readers",
                "category": CATEGORY_INSTRUCTIONAL_CONTENT,
                "grade_band_low": 3,
                "grade_band_high": 5,
                "sso_protocol": SSO_LTI13,
                "accessibility_conformance_level": ACCESSIBILITY_WCAG21_A,
                "vpat_on_file": False,
            },
            attest=False,
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
        api,
        chain.review_id,
        2,
        chain.assignee_headers,
        decision_note="Retention terms unacceptable.",
    )

    attested = fx.attest_integration(
        api,
        chain.application_id,
        sso_verified=True,
        accessibility_conformance_level=ACCESSIBILITY_WCAG21_AA,
        vpat_on_file=True,
    )

    assert attested["sso_verified"] is True, (
        f"The district recorded a passing integration test, got "
        f"{attested['sso_verified']!r}"
    )
    assert attested["accessibility_conformance_level"] == ACCESSIBILITY_WCAG21_AA, (
        f"Expected WCAG21_AA, got {attested['accessibility_conformance_level']}"
    )
    assert attested["vpat_on_file"] is True, (
        f"Expected the VPAT on file, got {attested['vpat_on_file']!r}"
    )
    blocked = fx.decide_review(
        api,
        chain.review_id,
        DECISION_BLOCK,
        chain.decider_headers,
        decision_note="Blocked on unresolved retention findings.",
    )
    assert blocked["status"] == REVIEW_BLOCKED, (
        f"Expected BLOCKED, got {blocked['status']}"
    )
    assert fx.read_application(api, chain.application_id)["status"] == APPLICATION_BLOCKED, (
        "The second hop of the cascade blocks the product"
    )
    assert fx.read_request(api, chain.request_id)["status"] == REQUEST_CLOSED_BLOCKED, (
        "The third hop closes the request as blocked"
    )

    refused = api.attest_integration(
        chain.application_id, fac.attestation_payload(sso_verified=False), ADMIN_HEADERS
    )

    validate_error(refused, ERR_APPLICATION_STATE_INVALID, 409)
    assert fx.read_application(api, chain.application_id)["sso_verified"] is True, (
        "The refused attestation wrote nothing"
    )


def test_escalating_a_detection_mints_the_incident_it_links_to(api):
    """The incident is stamped from `observed_at`, not from the clock.

    PRD: "Because the detection became `ESCALATED`, a `VendorIncident` is minted
    for the vendor of the matched application, with `incident_type` fixed at
    `UNAUTHORIZED_DISCLOSURE`, `detected_at` copied from the detection's
    `observed_at`, `affected_student_count` taken from the triage payload when
    supplied and otherwise defaulted to the detection's `distinct_user_count`,
    `max_data_tier` taken from the payload when supplied and otherwise defaulted
    to 3, and `response_status` `REPORTED`; the new incident's `severity` and
    `notification_due_at` are computed exactly as in §3.9, and the detection's
    `linked_incident_id` is set to the new row."

    Design: Corner/endpoints/escalating_a_detection_links_it_to_a_newly_minted_incident
    """
    fx.set_clock(api)
    vendor = fx.register_vendor(
        api, legal_name="Shadow Quiz Tools", breach_notification_hours=48
    )
    app = fx.register_application(
        api,
        vendor["id"],
        name="Shadow Quiz",
        category=CATEGORY_ASSESSMENT,
        grade_band_low=6,
        grade_band_high=8,
        sso_protocol=SSO_NONE,
        accessibility_conformance_level=ACCESSIBILITY_NONE,
        vpat_on_file=False,
    )
    detection = fx.observe_detection(
        api,
        "quiz.shadow.example",
        "2026-07-31T12:00:00Z",
        application_id=app["id"],
        school_code="MS-04",
        source=SOURCE_NETWORK_DNS,
        distinct_user_count=30,
        session_count=120,
    )

    escalated = fx.triage_detection(
        api,
        detection["id"],
        TRIAGE_ESCALATE,
        ADMIN_HEADERS,
        note="Unauthorized use at MS-04.",
    )

    assert escalated["status"] == DETECTION_ESCALATED, (
        f"Expected ESCALATED, got {escalated['status']}"
    )
    assert escalated["classification"] == CLASSIFICATION_UNAUTHORIZED, (
        f"Expected UNAUTHORIZED, got {escalated['classification']}"
    )
    assert_decimal_equals(escalated["exposure_score"], "63.00", "exposure_score")
    assert escalated["triaged_by_user_id"] is not None, (
        "The escalation stamps the acting operator"
    )
    incident_id = escalated["linked_incident_id"]
    assert incident_id is not None, (
        "ESCALATE is the disposition that creates a second entity"
    )

    minted = validate_success(api.get_incident(incident_id, ADMIN_HEADERS), 200)

    assert minted["vendor_id"] == vendor["id"], (
        "The escalation lands on the vendor of the matched application"
    )
    assert minted["incident_type"] == INCIDENT_UNAUTHORIZED_DISCLOSURE, (
        f"The type is fixed, got {minted['incident_type']}"
    )
    assert_instant_equals(
        minted["detected_at"], "2026-07-31T12:00:00.000Z", "detected_at"
    )
    assert_integer_equals(
        minted["affected_student_count"], 30, "affected_student_count"
    )
    assert_integer_equals(minted["max_data_tier"], 3, "max_data_tier")
    assert minted["severity"] == SEVERITY_MODERATE, (
        f"30 students at tier 3 is MODERATE, got {minted['severity']}"
    )
    assert_instant_equals(
        minted["notification_due_at"],
        "2026-08-02T12:00:00.000Z",
        "notification_due_at",
    )
    assert minted["response_status"] == INCIDENT_REPORTED, (
        f"Expected REPORTED, got {minted['response_status']}"
    )
    assert minted["notification_status"] == NOTIFICATION_PENDING, (
        f"Expected PENDING, got {minted['notification_status']}"
    )
    assert_instant_equals(minted["reported_at"], CLOCK_DEFAULT_RENDERED, "reported_at")
    owner = fx.read_vendor(api, vendor["id"])
    assert_integer_equals(owner["open_incident_count"], 1, "open_incident_count")
    assert_decimal_equals(owner["risk_score"], "8.00", "risk_score")
    assert owner["privacy_posture"] == POSTURE_RESTRICTED, (
        f"Expected RESTRICTED, got {owner['privacy_posture']}"
    )
    _rows, meta = validate_paginated(
        api.list_detections(ADMIN_HEADERS, linked_incident_id=incident_id)
    )
    assert_integer_equals(meta["total_count"], 1, "total_count")
