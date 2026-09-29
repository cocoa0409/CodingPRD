"""Error identities: each entity family owns its own 404, a fresh authorization
is not renewable, and a terminal subprocessor earns a state error rather than an
applicability error.
"""

from test_helpers import (
    ADMIN_HEADERS,
    assert_instant_equals,
    assert_integer_equals,
    assert_decimal_equals,
    factories as fac,
    fixtures as fx,
    get_success_data,
    make_analyst_headers,
    validate_error,
    validate_paginated,
)
from test_helpers.api_errors import (
    ERR_ANALYST_NOT_FOUND,
    ERR_APPLICATION_NOT_FOUND,
    ERR_CATALOG_ENTRY_NOT_FOUND,
    ERR_CATALOG_ENTRY_NOT_RENEWABLE,
    ERR_COMMITMENT_NOT_FOUND,
    ERR_DETECTION_NOT_FOUND,
    ERR_INCIDENT_NOT_FOUND,
    ERR_REQUEST_NOT_FOUND,
    ERR_REVIEW_NOT_FOUND,
    ERR_SUBPROCESSOR_NOT_FOUND,
    ERR_SUBPROCESSOR_STATE_INVALID,
    ERR_TEACHER_NOT_FOUND,
    ERR_VENDOR_NOT_FOUND,
)
from test_helpers.constants import (
    ACCESSIBILITY_WCAG21_AA,
    CATEGORY_INSTRUCTIONAL_CONTENT,
    CLOCK_DEFAULT,
    CREDENTIAL_SENIOR,
    DISPOSITION_REMOVE,
    DISPOSITION_VERIFY,
    ELEMENT_STUDENT_NAME,
    ENTRY_EXPIRING_SOON,
    ENTRY_PUBLISHED,
    ENTRY_SUPERSEDED,
    POSTURE_CLEAR,
    SSO_LTI13,
    SUBPROCESSOR_REMOVED,
    UNKNOWN_UUID,
)

CLOCK_INSIDE_THE_REAUTHORIZATION_WINDOW = "2027-07-15T00:00:00Z"
FIRST_EXPIRY = "2027-08-01T00:00:00Z"
SECOND_EXPIRY = "2028-08-01T00:00:00Z"
HOSTING_PURPOSE = (
    "Primary application hosting and nightly encrypted backup storage."
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


# ---------------------------------------------------------------------------
# One 404 identity per entity family
# ---------------------------------------------------------------------------


def test_every_entity_family_owns_its_own_not_found_id(api):
    """The same unknown UUID names eleven different missing things.

    PRD: "The path variables in play are `vendorId`, `subprocessorId`,
    `applicationId`, `teacherId`, `analystId`, `requestId`, `reviewId`,
    `commitmentId`, `entryId`, `detectionId` and `incidentId`, and each resolves
    to its own 404: `ERR_VENDOR_NOT_FOUND`, `ERR_SUBPROCESSOR_NOT_FOUND`,
    `ERR_APPLICATION_NOT_FOUND`, `ERR_TEACHER_NOT_FOUND`,
    `ERR_ANALYST_NOT_FOUND`, `ERR_REQUEST_NOT_FOUND`, `ERR_REVIEW_NOT_FOUND`,
    `ERR_COMMITMENT_NOT_FOUND`, `ERR_CATALOG_ENTRY_NOT_FOUND`,
    `ERR_DETECTION_NOT_FOUND` and `ERR_INCIDENT_NOT_FOUND`."

    Design: Corner/errors/every_not_found_error_id_is_individually_triggerable
    """
    fx.set_clock(api)
    probes = (
        (api.get_vendor, ERR_VENDOR_NOT_FOUND),
        (api.get_subprocessor, ERR_SUBPROCESSOR_NOT_FOUND),
        (api.get_application, ERR_APPLICATION_NOT_FOUND),
        (api.get_teacher, ERR_TEACHER_NOT_FOUND),
        (api.get_analyst, ERR_ANALYST_NOT_FOUND),
        (api.get_request, ERR_REQUEST_NOT_FOUND),
        (api.get_review, ERR_REVIEW_NOT_FOUND),
        (api.get_commitment, ERR_COMMITMENT_NOT_FOUND),
        (api.get_catalog_entry, ERR_CATALOG_ENTRY_NOT_FOUND),
        (api.get_detection, ERR_DETECTION_NOT_FOUND),
        (api.get_incident, ERR_INCIDENT_NOT_FOUND),
    )

    observed = []
    for read, expected_error_id in probes:
        response = read(UNKNOWN_UUID, ADMIN_HEADERS)
        body = validate_error(response, expected_error_id, 404)
        assert body["message"].strip(), (
            f"The 404 for {expected_error_id} must carry a message"
        )
        observed.append(body["error_id"])

    assert observed == [expected for _read, expected in probes], (
        f"Each family must answer with its own id, got {observed}"
    )
    assert len(set(observed)) == 11, (
        f"The eleven ids must be distinct, got {sorted(set(observed))}"
    )


# ---------------------------------------------------------------------------
# Renewal is gated on the sweep
# ---------------------------------------------------------------------------


def test_a_fresh_published_entry_is_not_renewable_until_the_sweep_moves_it(api):
    """The identical reauthorization is 409 before the sweep and 201 after it.

    PRD: "Only an entry in `EXPIRING_SOON` or `EXPIRED` may be reauthorized; a
    still-fresh `PUBLISHED` entry is not renewable and is refused with
    `ERR_CATALOG_ENTRY_NOT_RENEWABLE`, so the sweep must first walk the entry
    into its reauthorization window."

    Design: Corner/errors/fresh_published_entry_is_not_renewable_until_the_sweep_moves_it
    """
    fx.set_clock(api)
    chain = fx.published_entry_chain(
        api,
        CLOCK_DEFAULT,
        FIRST_EXPIRY,
        authorized_grade_band_low=3,
        authorized_grade_band_high=5,
        **_reading_product_chain(api),
    )
    fresh = fx.read_entry(api, chain.entry_id)
    assert fresh["status"] == ENTRY_PUBLISHED, (
        f"The new window opens PUBLISHED, got {fresh['status']}"
    )

    too_early = api.reauthorize_catalog_entry(
        chain.entry_id,
        fac.reauthorize_payload(
            SECOND_EXPIRY, fx.application_version(api, chain.application_id)
        ),
        ADMIN_HEADERS,
    )

    validate_error(too_early, ERR_CATALOG_ENTRY_NOT_RENEWABLE, 409)
    assert fx.read_entry(api, chain.entry_id)["status"] == ENTRY_PUBLISHED, (
        "The refusal must leave the predecessor PUBLISHED"
    )
    successors, meta = validate_paginated(
        api.list_catalog_entries(ADMIN_HEADERS, predecessor_entry_id=chain.entry_id)
    )
    assert_integer_equals(meta["total_count"], 0, "successor total_count before the sweep")
    assert successors == [], f"No successor may exist yet, got {successors}"

    fx.set_clock(api, CLOCK_INSIDE_THE_REAUTHORIZATION_WINDOW)
    sweep = fx.run_sweep(api)

    assert_integer_equals(sweep["expiring_soon_count"], 1, "expiring_soon_count")
    assert fx.read_entry(api, chain.entry_id)["status"] == ENTRY_EXPIRING_SOON, (
        "The sweep must walk the entry into its reauthorization window"
    )

    successor = fx.reauthorize_entry(
        api, chain.entry_id, SECOND_EXPIRY, chain.application_id
    )

    predecessor = fx.read_entry(api, chain.entry_id)
    assert predecessor["status"] == ENTRY_SUPERSEDED, (
        f"Expected SUPERSEDED, got {predecessor['status']}"
    )
    assert successor["predecessor_entry_id"] == chain.entry_id, (
        f"Expected {chain.entry_id}, got {successor['predecessor_entry_id']!r}"
    )
    assert_instant_equals(
        successor["effective_from"], "2027-08-01T00:00:00.000Z", "effective_from"
    )
    assert_instant_equals(
        successor["expires_at"], "2028-08-01T00:00:00.000Z", "expires_at"
    )
    assert successor["status"] == ENTRY_PUBLISHED, (
        f"Expected PUBLISHED, got {successor['status']}"
    )
    assert_integer_equals(
        successor["authorized_grade_band_low"], 3, "inherited authorized_grade_band_low"
    )
    assert_integer_equals(
        successor["authorized_grade_band_high"], 5, "inherited authorized_grade_band_high"
    )
    assert_instant_equals(
        successor["reauthorization_due_at"],
        "2028-07-02T00:00:00.000Z",
        "reauthorization_due_at",
    )


# ---------------------------------------------------------------------------
# A terminal subprocessor answers with a state error
# ---------------------------------------------------------------------------


def test_reviewing_a_removed_subprocessor_is_a_state_error_not_an_applicability_error(
    api,
):
    """REMOVED is terminal, so the refusal is state-flavoured, not disposition-flavoured.

    PRD: "Two refusals guard those dispositions and their relative order matters.
    A subprocessor already in `REMOVED` refuses any further review with
    `ERR_SUBPROCESSOR_STATE_INVALID`."

    Design: Corner/errors/reviewing_a_removed_subprocessor_is_a_terminal_state_error
    """
    fx.set_clock(api)
    vendor = fx.register_vendor(
        api, legal_name="Brightpath Reading Co", breach_notification_hours=48
    )
    analyst = fx.enroll_analyst(
        api,
        full_name="Ana Lopez",
        credential_level=CREDENTIAL_SENIOR,
        review_capacity_minutes=2400,
    )
    analyst_headers = make_analyst_headers(analyst["id"])
    subprocessor = fx.disclose_subprocessor(
        api,
        vendor["id"],
        name="Cloudhost US East",
        country_code="US",
        data_categories=[ELEMENT_STUDENT_NAME],
        purpose=HOSTING_PURPOSE,
        sub_breach_notification_hours=24,
    )
    fx.review_subprocessor(
        api,
        subprocessor["id"],
        DISPOSITION_VERIFY,
        analyst_headers,
        reviewed_note="Terms are at least as strict as the vendor's.",
    )
    fx.review_subprocessor(
        api,
        subprocessor["id"],
        DISPOSITION_REMOVE,
        analyst_headers,
        reviewed_note="Contract terminated.",
    )

    resurrect = api.review_subprocessor(
        subprocessor["id"],
        fac.subprocessor_review_payload(
            DISPOSITION_VERIFY,
            reviewed_note="Attempt to resurrect a removed subprocessor.",
        ),
        analyst_headers,
    )

    validate_error(resurrect, ERR_SUBPROCESSOR_STATE_INVALID, 409)
    after = get_success_data(api.get_subprocessor(subprocessor["id"], ADMIN_HEADERS))
    assert after["status"] == SUBPROCESSOR_REMOVED, (
        f"The terminal state is unchanged, got {after['status']}"
    )
    owner = fx.read_vendor(api, vendor["id"])
    assert_integer_equals(
        owner["flagged_subprocessor_count"], 0, "flagged_subprocessor_count"
    )
    assert_decimal_equals(owner["risk_score"], "0.00", "risk_score")
    assert owner["privacy_posture"] == POSTURE_CLEAR, (
        f"Expected CLEAR, got {owner['privacy_posture']}"
    )
