"""The validation ladder: precedence between categories, and role/ownership gates."""
from test_helpers import (
    ApiErrorId,
    MISSING_LISTING_ID,
    MISSING_LISTING_ID_FOR_ANON,
    MISSING_SECTION_ID,
    confirm_seat,
    create_learner,
    create_listing,
    create_section,
    get_listing,
    get_section,
    get_success_data,
    make_parent_headers,
    make_platform_admin_headers,
    make_teacher_headers,
    onboard_active_teacher,
    reserve_seat,
    setup_listing,
    validate_error,
)


def test_age_band_check_outranks_the_seat_capacity_check(api):
    """PRD §2.6: "The rules below are numbered in evaluation order — the lowest number is
    evaluated first — and as soon as one rule fails, the request is rejected with that
    rule's error and no later rule is consulted."
    PRD §2.6: "The learner's age at the section's start instant falls inside the listing's
    `min_age` to `max_age` band, inclusive, and the learner's `birth_date` is not in the
    future. Any failure here is `ERR_LEARNER_AGE_OUT_OF_RANGE` (HTTP 409), and it applies to
    seat reservation."
    PRD §2.6: "The section has a remaining seat: `seats_remaining` must be greater than
    zero, counting `CONFIRMED` and `RESERVED` enrollments against `capacity`. Any failure
    here is `ERR_SECTION_FULL` (HTTP 409), and it applies to seat reservation."

    Design: Difficulty/priority_pair_validation_conflict/age_band_check_precedes_seat_capacity_check
    """
    teacher = onboard_active_teacher()
    listing = setup_listing(teacher, min_age=8, max_age=12, list_price_cents=2000)
    section = create_section(
        listing, teacher, start_utc="2026-11-05T14:00:00Z", end_utc="2026-11-05T16:00:00Z",
        min_learners=1, capacity=1,
    )

    older = create_learner(display_name="Older Learner", birth_date="2016-05-01T00:00:00Z", tier="FAMILY")
    younger = create_learner(display_name="Younger Learner", birth_date="2020-05-01T00:00:00Z")

    seat = reserve_seat(listing, section, older)
    confirm_seat(seat["id"])

    saturated = get_section(listing["id"], section["id"])
    assert saturated["capacity"] == 1
    assert saturated["enrolled_count"] == 1
    assert saturated["seats_remaining"] == 0

    response = api.create_enrollment(
        listing["id"], section["id"], {"learner_id": younger["id"]}, make_parent_headers()
    )
    validate_error(response, ApiErrorId.ERR_LEARNER_AGE_OUT_OF_RANGE)


def test_age_band_check_outranks_capacity_even_with_only_a_reserved_seat(api):
    """PRD §2.6: "The rules below are numbered in evaluation order — the lowest number is
    evaluated first — and as soon as one rule fails, the request is rejected with that
    rule's error and no later rule is consulted."
    PRD §2.6: "The learner's age at the section's start instant falls inside the listing's
    `min_age` to `max_age` band, inclusive, and the learner's `birth_date` is not in the
    future. Any failure here is `ERR_LEARNER_AGE_OUT_OF_RANGE` (HTTP 409), and it applies to
    seat reservation."

    Design: Difficulty/priority_pair_validation_conflict/age_band_check_precedes_seat_capacity_check
    """
    teacher = onboard_active_teacher()
    listing = setup_listing(teacher, min_age=8, max_age=12, list_price_cents=2000)
    section = create_section(
        listing, teacher, start_utc="2026-11-05T14:00:00Z", end_utc="2026-11-05T16:00:00Z",
        min_learners=1, capacity=1,
    )

    older = create_learner(display_name="Older Learner", birth_date="2016-05-01T00:00:00Z")
    too_old = create_learner(display_name="Too Old Learner", birth_date="2012-05-01T00:00:00Z")

    held = reserve_seat(listing, section, older)
    assert held["status"] == "RESERVED"
    assert get_section(listing["id"], section["id"])["seats_remaining"] == 0

    response = api.create_enrollment(
        listing["id"], section["id"], {"learner_id": too_old["id"]}, make_parent_headers()
    )
    validate_error(response, ApiErrorId.ERR_LEARNER_AGE_OUT_OF_RANGE)


def test_missing_section_id_outranks_the_state_of_the_real_section(api):
    """PRD §2.6: "Every resource identifier appearing in the request path resolves to an
    existing resource, validated from left to right along the path. Any failure here is
    `ERR_NOT_FOUND` (HTTP 404). This applies to every endpoint that carries a resource
    identifier."
    PRD §2.6: "The target resource is in a state from which the requested transition is
    declared. Any failure here is `ERR_INVALID_STATE` (HTTP 409). This applies to every
    state-transition endpoint."

    Design: Difficulty/priority_pair_validation_conflict/existence_check_precedes_state_check
    """
    teacher = onboard_active_teacher()
    listing = setup_listing(teacher)
    section = create_section(listing, teacher)
    assert section["status"] == "OPEN_FOR_ENROLLMENT", (
        "opening the real section again would itself be rejected as ERR_INVALID_STATE"
    )

    response = api.open_section(listing["id"], MISSING_SECTION_ID, make_teacher_headers(teacher["id"]))
    validate_error(response, ApiErrorId.ERR_NOT_FOUND)

    assert get_section(listing["id"], section["id"])["status"] == "OPEN_FOR_ENROLLMENT"


def test_missing_parent_listing_outranks_the_deeper_section_lookup(api):
    """PRD §2.7: "A request naming a section under a listing that does not exist is
    therefore answered as a missing listing, never as a missing section."
    PRD §2.6: "Every resource identifier appearing in the request path resolves to an
    existing resource, validated from left to right along the path. Any failure here is
    `ERR_NOT_FOUND` (HTTP 404)."

    Design: Difficulty/priority_pair_validation_conflict/existence_check_precedes_state_check
    """
    teacher = onboard_active_teacher()
    listing = setup_listing(teacher)
    section = create_section(listing, teacher)

    response = api.open_section(MISSING_LISTING_ID, section["id"], make_teacher_headers(teacher["id"]))
    validate_error(response, ApiErrorId.ERR_NOT_FOUND)

    assert get_section(listing["id"], section["id"])["status"] == "OPEN_FOR_ENROLLMENT"


def test_get_unknown_listing_returns_not_found(api):
    """PRD §2.6: "Every resource identifier appearing in the request path resolves to an
    existing resource, validated from left to right along the path. Any failure here is
    `ERR_NOT_FOUND` (HTTP 404). This applies to every endpoint that carries a resource
    identifier."

    Design: Corner/entities/get_unknown_listing_returns_not_found
    """
    response = api.get_class_listing(MISSING_LISTING_ID, make_platform_admin_headers())
    validate_error(response, ApiErrorId.ERR_NOT_FOUND)


def test_parent_role_cannot_run_a_policy_review(api):
    """PRD §2.1: "A request whose declared role is recognised but is not permitted for the
    targeted operation is rejected with `ERR_FORBIDDEN` (HTTP 403)."

    Design: Corner/rbac/parent_cannot_policy_review_listing
    """
    teacher = onboard_active_teacher()
    listing = create_listing(teacher)
    assert listing["content_review_state"] == "PENDING_REVIEW"

    response = api.policy_review_listing(
        listing["id"], {"decision": "APPROVE"}, make_parent_headers()
    )
    validate_error(response, ApiErrorId.ERR_FORBIDDEN)

    assert get_listing(listing["id"])["content_review_state"] == "PENDING_REVIEW"


def test_missing_role_header_outranks_existence(api):
    """PRD §2.1: "A request that omits either header, or that declares an `X-User-Role`
    value outside the recognised set, is rejected with `ERR_UNAUTHENTICATED` (HTTP 401)."
    PRD §2.6: "A request that is missing a header and also names a resource that does not
    exist is answered with the authentication error, not the not-found error, because
    authentication is evaluated first."

    Design: Corner/rbac/missing_role_header_returns_unauthenticated
    """
    response = api.get_without_auth_headers(f"/outschool/class-listings/{MISSING_LISTING_ID_FOR_ANON}")
    validate_error(response, ApiErrorId.ERR_UNAUTHENTICATED)
