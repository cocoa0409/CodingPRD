"""Announcement construction: body-shape rules, natural-key uniqueness,
authority/method coherence, position posture, the open transition, sibling
period overlap (half-open semantics), and the fixed startup clock.
"""
from test_helpers import (
    ADMIN, HR, HM, ApiErrorId,
    assert_announcement,
    create_announcement, create_announcement_payload, create_applicant_payload,
    create_classified_position, create_draft_position, create_series,
    create_series_payload, api_client, make_applicant_headers,
    open_announcement, register_applicant, validate_error, validate_success,
)


def test_invalid_request_shapes_rejected(api):
    """PRD §2.7: "then request-body shape — required fields present, types
    correct, enum values in range, numeric ranges honored, such as ratings
    between 1 and 5, `close_at` strictly later than `open_at`,
    `certificate_validity_days` between 30 and 90, and `wq_cut` below `bq_cut` —
    rejected as `ERR_INVALID_REQUEST` (3)".

    Design: Corner/validations/invalid_request_shapes_rejected
    """
    _series, position = create_classified_position()

    missing_field = create_series_payload(series_code="0399")
    missing_field.pop("min_grade")
    resp = api_client.create_series(missing_field, HR)
    validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST)

    bad_enum = create_announcement_payload(area_of_consideration="EVERYONE")
    resp = api_client.create_announcement(position["id"], bad_enum, HM)
    validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST)

    inverted_period = create_announcement_payload(
        open_at="2026-09-20T00:00:00Z", close_at="2026-09-05T00:00:00Z")
    resp = api_client.create_announcement(position["id"], inverted_period, HM)
    validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST)


def test_duplicate_natural_keys_rejected(api):
    """PRD §3.1: "Registering a series whose `series_code` is already taken fails
    with `ERR_DUPLICATE_KEY` (HTTP 409)."
    PRD §3.2: "The announcement carries a unique `announcement_number` (a
    collision meets `ERR_DUPLICATE_KEY`)".
    PRD §3.3: "a unique `email` (collisions fail with `ERR_DUPLICATE_KEY`)".

    Design: Corner/entities/duplicate_natural_keys_rejected
    """
    create_series(series_code="0343")
    resp = api_client.create_series(create_series_payload(series_code="0343"), HR)
    validate_error(resp, ApiErrorId.ERR_DUPLICATE_KEY)

    _series, position = create_classified_position()
    create_announcement(position["id"], announcement_number="OPM-26-401")
    # A disjoint period isolates the natural-key rule from the overlap rule.
    resp = api_client.create_announcement(
        position["id"],
        create_announcement_payload(
            announcement_number="OPM-26-401",
            open_at="2026-10-01T00:00:00Z", close_at="2026-10-10T00:00:00Z"),
        HM)
    validate_error(resp, ApiErrorId.ERR_DUPLICATE_KEY)

    register_applicant(email="ann@x.com")
    resp = api_client.create_applicant(
        create_applicant_payload(email="ann@x.com"),
        # HR-brokered registration keeps this a pure key-collision probe.
        HR)
    validate_error(resp, ApiErrorId.ERR_DUPLICATE_KEY)


def test_authority_method_mismatch_rejected(api):
    """PRD §3.2: "Authority and method must cohere: `COMPETITIVE` requires
    `CATEGORY_RATING`, `DIRECT_HIRE` requires `UNRANKED`, while `VEOA`,
    `SCHEDULE_A`, and `NONCOMPETITIVE_SPOUSE` accept either, and an incoherent
    pairing fails with `ERR_AUTHORITY_METHOD_MISMATCH` (HTTP 422)."

    Design: Corner/validations/authority_method_mismatch_rejected
    """
    _series, position = create_classified_position()

    resp = api_client.create_announcement(
        position["id"],
        create_announcement_payload(
            hiring_authority="DIRECT_HIRE", assessment_method="CATEGORY_RATING"),
        HM)
    validate_error(resp, ApiErrorId.ERR_AUTHORITY_METHOD_MISMATCH)

    resp = api_client.create_announcement(
        position["id"],
        create_announcement_payload(
            hiring_authority="COMPETITIVE", assessment_method="UNRANKED"),
        HM)
    validate_error(resp, ApiErrorId.ERR_AUTHORITY_METHOD_MISMATCH)


def test_announcement_on_draft_position_rejected(api):
    """PRD §3.2: "Creating an announcement against a position still in `DRAFT`
    is rejected with `ERR_POSITION_NOT_CLASSIFIED` (HTTP 422)."

    Design: Corner/validations/announcement_on_draft_position_rejected
    """
    series = create_series()
    position = create_draft_position(series["id"])
    assert position["status"] == "DRAFT"

    resp = api_client.create_announcement(
        position["id"], create_announcement_payload(), HM)
    validate_error(resp, ApiErrorId.ERR_POSITION_NOT_CLASSIFIED)


def test_announcement_double_open_rejected(api):
    """PRD §3.2: "The announcement opens when the `HiringManager` moves it from
    `DRAFT` to `OPEN`, which is permitted only while the logical clock is still
    earlier than `close_at`; a request whose transition preconditions fail is
    rejected with `ERR_INVALID_STATE` (HTTP 409)."

    Design: Corner/state_machines/announcement_double_open_rejected
    """
    _series, position = create_classified_position()
    announcement = create_announcement(position["id"])
    opened = open_announcement(announcement["id"])
    assert opened["status"] == "OPEN"

    resp = api_client.open_announcement(announcement["id"], HM)
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE)

    reread = api_client.get_announcement(announcement["id"], HM)
    assert reread.json()["data"]["status"] == "OPEN"


def test_announcement_period_half_open_adjacency(api):
    """PRD §2.9: "Sibling announcements of the same position follow half-open
    overlap semantics: their periods must not intersect, but adjacency is
    allowed — a new announcement whose `open_at` equals an existing sibling's
    `close_at` is not a conflict, while a genuine intersection is rejected with
    `ERR_ANNOUNCEMENT_PERIOD_OVERLAP` (HTTP 409)."

    Design: Difficulty/resource_temporal_overlap/announcement_period_half_open_adjacency
    """
    _series, position = create_classified_position()
    create_announcement(
        position["id"],
        announcement_number="OPM-26-201",
        open_at="2026-09-05T00:00:00Z", close_at="2026-09-20T00:00:00Z")

    # Adjacent: open_at == existing close_at is legal under half-open semantics.
    resp = api_client.create_announcement(
        position["id"],
        create_announcement_payload(
            announcement_number="OPM-26-202",
            open_at="2026-09-20T00:00:00Z", close_at="2026-09-25T00:00:00Z"),
        HM)
    adjacent = validate_success(resp, 201)
    assert_announcement(adjacent)

    # One day of genuine intersection is a conflict.
    resp = api_client.create_announcement(
        position["id"],
        create_announcement_payload(
            announcement_number="OPM-26-203",
            open_at="2026-09-19T00:00:00Z", close_at="2026-09-26T00:00:00Z"),
        HM)
    validate_error(resp, ApiErrorId.ERR_ANNOUNCEMENT_PERIOD_OVERLAP)


def test_clock_default_fixed_at_startup(api):
    """PRD §2.5: "Before any operator intervention the clock reads exactly
    2026-09-01T00:00:00Z, and it never falls back to wall-clock time thereafter."
    PRD §2.9: "applications are accepted while the logical clock is at or after
    `open_at` and strictly before `close_at`".

    Design: Corner/cross_cutting_layers/clock_default_fixed_at_startup
    """
    _series, position = create_classified_position()
    announcement = create_announcement(position["id"])
    # No clock call anywhere in this test: the startup default (2026-09-01)
    # is earlier than close_at, so the open transition itself is legal.
    opened = open_announcement(announcement["id"])
    assert opened["status"] == "OPEN"

    applicant = register_applicant()
    # The untouched clock reads 2026-09-01, which precedes open_at 2026-09-05.
    resp = api_client.submit_application(
        announcement["id"],
        {
            "applicant_id": applicant["id"],
            "claimed_experience_months": 30,
            "claimed_education_months": 0,
            "self_rating_knowledge": 3,
            "self_rating_skill": 3,
            "self_rating_ability": 3,
        },
        # Entity-backed role: identity is the applicant's own id.
        make_applicant_headers(applicant["id"]))
    validate_error(resp, ApiErrorId.ERR_OUTSIDE_OPEN_PERIOD)
