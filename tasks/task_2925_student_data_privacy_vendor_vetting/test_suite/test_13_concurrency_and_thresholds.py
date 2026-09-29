"""Cross-cutting layers: the two optimistic-concurrency tokens, the inclusive
posture threshold, and the promise that a cascade is visible the moment it is
applied.
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
from test_helpers.api_errors import (
    ERR_STALE_APPLICATION_VERSION,
    ERR_STALE_REVIEW_VERSION,
)
from test_helpers.constants import (
    ACCESSIBILITY_WCAG21_AA,
    ACCESSIBILITY_WCAG21_AAA,
    ANONYMIZE,
    CATEGORY_ASSESSMENT,
    CATEGORY_INSTRUCTIONAL_CONTENT,
    CLOCK_DEFAULT,
    COMMITMENT_ACCEPTED,
    COMMITMENT_PROPOSED,
    COMMITMENT_REJECTED,
    CREDENTIAL_LEAD,
    CREDENTIAL_SENIOR,
    DECISION_CLEAR,
    DISPOSITION_ACCEPT,
    DISPOSITION_REJECT,
    ELEMENT_GEOLOCATION,
    ELEMENT_GRADE_LEVEL,
    ELEMENT_STUDENT_ID,
    ELEMENT_STUDENT_NAME,
    ENTRY_EXPIRING_SOON,
    ENTRY_PUBLISHED,
    ENTRY_SUPERSEDED,
    HARD_DELETE,
    POSTURE_CLEAR,
    POSTURE_WATCH,
    PURPOSE_61,
    SSO_LTI13,
    SSO_SAML2,
    VISIBILITY_VISIBLE,
)

FIRST_EFFECTIVE_FROM = "2026-08-01T00:00:00Z"
FIRST_EXPIRY = "2027-08-01T00:00:00Z"
SECOND_EXPIRY = "2028-08-01T00:00:00Z"
CLOCK_INSIDE_THE_REAUTHORIZATION_WINDOW = "2027-07-15T00:00:00Z"
PURPOSE_PLACEMENT = "Grade-level placement for adaptive item selection logic."
PURPOSE_MAPPING = (
    "Campus-level session mapping for proctored assessment integrity checks."
)
PURPOSE_HOSTING = "European hosting region for assessment delivery traffic."
PURPOSE_ANALYTICS = "Item response analytics and psychometric calibration runs."
PURPOSE_SUPPORT = "Follow-the-sun tier two teacher support desk coverage."
PURPOSE_MAIL = "Transactional mail relay for teacher notification digests."


def _practice_product_chain(api, **overrides):
    """A grade 6-8 assessment product whose tier ceiling permits every element."""
    kwargs = dict(
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
        teacher={
            "full_name": "Dana Reyes",
            "school_code": "MS-04",
            "grade_bands_taught": [6, 7, 8],
        },
        request={
            "requested_data_elements": [ELEMENT_STUDENT_ID, ELEMENT_GRADE_LEVEL],
            "grade_band_low": 6,
            "grade_band_high": 8,
            "student_count_estimate": 300,
        },
        review={"estimated_minutes": 180},
        assignee_level=CREDENTIAL_SENIOR,
        assignee_capacity=2400,
        decider_level=CREDENTIAL_LEAD,
    )
    kwargs.update(overrides)
    return fx.screening_review_chain(api, **kwargs)


def _reading_product_chain(api, **overrides):
    """A fully publishable grade 3-5 instructional-content product."""
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
    return fx.screening_review_chain(api, **kwargs)


# ---------------------------------------------------------------------------
# The review token
# ---------------------------------------------------------------------------


def test_a_stale_review_token_blocks_a_second_commitment_author(api):
    """Every create bumps the parent, so the second author must re-read it.

    PRD: "A `POST /data-element-commitments` request must carry
    `expected_review_version`, a non-optional integer field holding the client's
    last observed `version` of the `DataPracticeReview` named by `review_id`. If
    that value does not equal the review's current `version`, the create is
    rejected with `ERR_STALE_REVIEW_VERSION` (HTTP 412)."

    Design: Corner/cross_cutting_complexity_layers/stale_review_version_blocks_a_second_commitment_author
    """
    chain = _practice_product_chain(api)
    first_token = fx.review_version(api, chain.review_id, chain.liaison_headers)
    assert_integer_equals(first_token, 1, "review version after opening")

    first = fx.propose_commitment(
        api,
        chain.review_id,
        ELEMENT_STUDENT_ID,
        chain.liaison_headers,
        expected_review_version=first_token,
        justified_purpose=PURPOSE_61,
        retention_days=90,
        deletion_method=HARD_DELETE,
    )
    assert_integer_equals(
        fx.review_version(api, chain.review_id), 2, "review version after the create"
    )

    stale = api.create_commitment(
        fac.commitment_payload(
            chain.review_id,
            ELEMENT_GRADE_LEVEL,
            first_token,
            retention_days=90,
            deletion_method=HARD_DELETE,
            justified_purpose=PURPOSE_PLACEMENT,
        ),
        chain.liaison_headers,
    )

    validate_error(stale, ERR_STALE_REVIEW_VERSION, 412)
    assert_integer_equals(
        fx.review_version(api, chain.review_id), 2, "review version after the refusal"
    )
    _rows, meta = validate_paginated(
        api.list_commitments(ADMIN_HEADERS, review_id=chain.review_id)
    )
    assert_integer_equals(meta["total_count"], 1, "commitment total_count")

    second_token = fx.review_version(api, chain.review_id, chain.liaison_headers)
    assert_integer_equals(second_token, 2, "re-read review version")
    second = fx.propose_commitment(
        api,
        chain.review_id,
        ELEMENT_GRADE_LEVEL,
        chain.liaison_headers,
        expected_review_version=second_token,
        justified_purpose=PURPOSE_PLACEMENT,
        retention_days=90,
        deletion_method=HARD_DELETE,
    )

    assert_integer_equals(
        fx.review_version(api, chain.review_id), 3, "review version after the retry"
    )
    _retried, retried_meta = validate_paginated(
        api.list_commitments(ADMIN_HEADERS, review_id=chain.review_id)
    )
    assert_integer_equals(retried_meta["total_count"], 2, "commitment total_count")
    assert_decimal_equals(first["element_points"], "2.50", "STUDENT_ID element_points")
    assert_decimal_equals(second["element_points"], "1.00", "GRADE_LEVEL element_points")
    app = fx.read_application(api, chain.application_id)
    assert_decimal_equals(
        app["exposed_sensitivity_points"],
        "0.00",
        "exposed_sensitivity_points while both rows are proposed",
    )


def test_a_stale_application_token_blocks_a_reauthorization(api):
    """An attestation landing mid-flight invalidates the renewal, harmlessly.

    PRD: "A `POST /catalog-entries/{entryId}/reauthorize` request must carry
    `expected_application_version`, a non-optional integer field holding the
    client's last observed `version` of the parent `Application`. If that value
    does not equal the application's current `version`, the reauthorization is
    rejected with `ERR_STALE_APPLICATION_VERSION` (HTTP 412)."

    Design: Corner/cross_cutting_complexity_layers/stale_application_version_blocks_a_reauthorization
    """
    chain = _reading_product_chain(api)
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
        decision_note="No open findings.",
    )
    fx.decide_review(
        api,
        chain.review_id,
        DECISION_CLEAR,
        chain.decider_headers,
        decision_note="Cleared for publication.",
    )
    entry = fx.publish_entry(
        api,
        chain.application_id,
        chain.review_id,
        FIRST_EFFECTIVE_FROM,
        FIRST_EXPIRY,
        authorized_grade_band_low=3,
        authorized_grade_band_high=5,
    )
    fx.set_clock(api, CLOCK_INSIDE_THE_REAUTHORIZATION_WINDOW)
    fx.run_sweep(api)
    assert fx.read_entry(api, entry["id"])["status"] == ENTRY_EXPIRING_SOON, (
        "The sweep must make the entry renewable"
    )
    stale_token = fx.application_version(api, chain.application_id)

    attested = fx.attest_integration(
        api,
        chain.application_id,
        sso_verified=True,
        accessibility_conformance_level=ACCESSIBILITY_WCAG21_AAA,
        vpat_on_file=True,
    )
    stale = api.reauthorize_catalog_entry(
        entry["id"],
        fac.reauthorize_payload(SECOND_EXPIRY, stale_token),
        ADMIN_HEADERS,
    )

    assert attested["accessibility_conformance_level"] == ACCESSIBILITY_WCAG21_AAA, (
        f"Expected WCAG21_AAA, got {attested['accessibility_conformance_level']}"
    )
    validate_error(stale, ERR_STALE_APPLICATION_VERSION, 412)
    assert fx.read_entry(api, entry["id"])["status"] == ENTRY_EXPIRING_SOON, (
        "The failed attempt must not supersede the predecessor"
    )
    _rows, meta = validate_paginated(
        api.list_catalog_entries(ADMIN_HEADERS, predecessor_entry_id=entry["id"])
    )
    assert_integer_equals(meta["total_count"], 0, "successor total_count")
    fresh_token = fx.application_version(api, chain.application_id)
    assert_integer_equals(fresh_token, stale_token + 1, "application version")

    successor = fx.reauthorize_entry(
        api, entry["id"], SECOND_EXPIRY, chain.application_id, fresh_token
    )

    assert fx.read_entry(api, entry["id"])["status"] == ENTRY_SUPERSEDED, (
        "The retry must supersede the predecessor"
    )
    assert_instant_equals(
        successor["effective_from"], "2027-08-01T00:00:00.000Z", "effective_from"
    )
    assert successor["status"] == ENTRY_PUBLISHED, (
        f"Expected PUBLISHED, got {successor['status']}"
    )
    assert_instant_equals(
        successor["reauthorization_due_at"],
        "2028-07-02T00:00:00.000Z",
        "reauthorization_due_at",
    )
    assert (
        fx.read_application(api, chain.application_id)["catalog_visibility"]
        == VISIBILITY_VISIBLE
    ), "The successor keeps the product visible"


# ---------------------------------------------------------------------------
# The inclusive WATCH rung
# ---------------------------------------------------------------------------


def test_the_watch_rung_bites_at_exactly_forty_five_risk_points(api):
    """Forty foreign points plus a 10.00 load land the score on 45.00 exactly.

    PRD: "Otherwise the posture is `WATCH` if the vendor's `risk_score` is at
    least 45. The comparison is inclusive, so a `risk_score` of exactly 45.00 is
    `WATCH` while 44.99 falls through."

    Design: Corner/cross_cutting_complexity_layers/watch_threshold_bites_at_exactly_forty_five_risk_points
    """
    chain = _practice_product_chain(
        api,
        clock=CLOCK_DEFAULT,
        request={
            "requested_data_elements": [ELEMENT_GEOLOCATION, ELEMENT_STUDENT_ID],
            "grade_band_low": 6,
            "grade_band_high": 8,
            "student_count_estimate": 300,
        },
    )
    offshore = (
        ("Dublin Hosting Ltd", "IE", PURPOSE_HOSTING),
        ("Toronto Analytics Inc", "CA", PURPOSE_ANALYTICS),
        ("Sydney Support Group", "AU", PURPOSE_SUPPORT),
        ("Berlin Mail Relay GmbH", "DE", PURPOSE_MAIL),
    )
    for name, country_code, purpose in offshore:
        fx.disclose_subprocessor(
            api,
            chain.vendor_id,
            chain.liaison_headers,
            name=name,
            country_code=country_code,
            data_categories=[ELEMENT_STUDENT_ID],
            purpose=purpose,
            sub_breach_notification_hours=24,
        )
    geolocation = fx.propose_commitment(
        api,
        chain.review_id,
        ELEMENT_GEOLOCATION,
        chain.liaison_headers,
        justified_purpose=PURPOSE_MAPPING,
        retention_days=365,
        deletion_method=HARD_DELETE,
    )
    fx.decide_commitment(
        api, geolocation["id"], DISPOSITION_ACCEPT, chain.decider_headers
    )
    student_id = fx.propose_commitment(
        api,
        chain.review_id,
        ELEMENT_STUDENT_ID,
        chain.liaison_headers,
        justified_purpose=PURPOSE_61,
        retention_days=90,
        deletion_method=HARD_DELETE,
    )

    accepted = fx.decide_commitment(
        api, student_id["id"], DISPOSITION_ACCEPT, chain.decider_headers
    )
    on_the_boundary_app = fx.read_application(api, chain.application_id)
    on_the_boundary_vendor = fx.read_vendor(api, chain.vendor_id)
    rejected = fx.decide_commitment(
        api, student_id["id"], DISPOSITION_REJECT, chain.decider_headers
    )
    below_the_boundary_app = fx.read_application(api, chain.application_id)
    below_the_boundary_vendor = fx.read_vendor(api, chain.vendor_id)

    assert_decimal_equals(
        geolocation["element_points"], "7.50", "GEOLOCATION element_points"
    )
    assert_decimal_equals(
        student_id["element_points"], "2.50", "STUDENT_ID element_points"
    )
    assert accepted["status"] == COMMITMENT_ACCEPTED, (
        f"Expected ACCEPTED, got {accepted['status']}"
    )
    assert_decimal_equals(
        on_the_boundary_app["exposed_sensitivity_points"],
        "10.00",
        "exposed_sensitivity_points with both rows accepted",
    )
    assert_decimal_equals(
        on_the_boundary_vendor["risk_score"], "45.00", "risk_score on the boundary"
    )
    assert on_the_boundary_vendor["privacy_posture"] == POSTURE_WATCH, (
        "A score of exactly 45.00 is WATCH, got "
        f"{on_the_boundary_vendor['privacy_posture']}"
    )
    assert rejected["status"] == COMMITMENT_REJECTED, (
        f"Expected REJECTED, got {rejected['status']}"
    )
    assert_decimal_equals(
        below_the_boundary_app["exposed_sensitivity_points"],
        "7.50",
        "exposed_sensitivity_points after the rejection",
    )
    assert_decimal_equals(
        below_the_boundary_vendor["risk_score"], "43.75", "risk_score after the rejection"
    )
    assert below_the_boundary_vendor["privacy_posture"] == POSTURE_CLEAR, (
        "43.75 falls through the WATCH rung, got "
        f"{below_the_boundary_vendor['privacy_posture']}"
    )
    assert_integer_equals(
        below_the_boundary_vendor["flagged_subprocessor_count"],
        0,
        "flagged_subprocessor_count",
    )


# ---------------------------------------------------------------------------
# Nothing lags behind the write that caused it
# ---------------------------------------------------------------------------


def test_an_accepted_commitment_is_visible_in_the_response_that_accepted_it(api):
    """The ACCEPT body already carries the points, and so do the next two reads.

    PRD: "Third, **cascades are transactional and visible**. Either every hop of
    a cascade is applied or none is; a request that fails a validation leaves no
    partial cascade behind. Every row a cascade touches has its own `updated_at`
    refreshed and its own `version` incremented, including rows the caller never
    named."

    Design: Corner/consistency_model/accepted_commitment_is_visible_in_the_same_request_response
    """
    chain = _reading_product_chain(api, clock=CLOCK_DEFAULT)
    commitment = fx.propose_commitment(
        api,
        chain.review_id,
        ELEMENT_STUDENT_NAME,
        chain.liaison_headers,
        justified_purpose=PURPOSE_61,
        retention_days=365,
        deletion_method=ANONYMIZE,
    )
    assert commitment["status"] == COMMITMENT_PROPOSED, (
        f"Nothing is accepted yet, got {commitment['status']}"
    )
    assert_decimal_equals(
        fx.read_application(api, chain.application_id)["exposed_sensitivity_points"],
        "0.00",
        "exposed_sensitivity_points before the acceptance",
    )

    response = api.decide_commitment(
        commitment["id"],
        fac.commitment_decision_payload(DISPOSITION_ACCEPT),
        chain.decider_headers,
    )

    decided = validate_success(response, 200)
    assert decided["status"] == COMMITMENT_ACCEPTED, (
        f"The accepting response must already say ACCEPTED, got {decided['status']}"
    )
    assert decided["is_minimized"] is True, (
        f"Expected is_minimized true, got {decided['is_minimized']!r}"
    )
    assert_decimal_equals(
        decided["element_points"], "1.44", "element_points in the accepting response"
    )
    application = fx.read_application(api, chain.application_id)
    assert_decimal_equals(
        application["exposed_sensitivity_points"],
        "1.44",
        "exposed_sensitivity_points on the very next read",
    )
    vendor = fx.read_vendor(api, chain.vendor_id)
    assert_decimal_equals(vendor["risk_score"], "0.72", "risk_score on the next read")
    assert vendor["privacy_posture"] == POSTURE_CLEAR, (
        f"Expected CLEAR, got {vendor['privacy_posture']}"
    )
    rows, meta = validate_paginated(api.list_commitments(ADMIN_HEADERS))
    assert_integer_equals(meta["total_count"], 1, "commitment total_count")
    assert rows[0]["status"] == COMMITMENT_ACCEPTED, (
        f"The listed row must already be ACCEPTED, got {rows[0]['status']}"
    )
