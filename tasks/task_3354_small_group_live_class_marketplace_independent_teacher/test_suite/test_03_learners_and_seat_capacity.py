"""Learner accounts, seat occupancy and the seat-capacity boundary."""
from test_helpers import (
    ApiErrorId,
    confirm_seat,
    create_learner,
    create_section,
    get_enrollment,
    get_learner,
    get_section,
    get_success_data,
    make_parent_headers,
    make_teacher_headers,
    onboard_active_teacher,
    reserve_seat,
    setup_listing,
    subscribe_learner,
    validate_error,
    validate_paginated,
)


def test_full_section_reports_zero_seats_and_rejects_the_next_learner(api):
    """PRD §2.6: "The section has a remaining seat: `seats_remaining` must be greater
    than zero, counting `CONFIRMED` and `RESERVED` enrollments against `capacity`. Any
    failure here is `ERR_SECTION_FULL` (HTTP 409), and it applies to seat reservation."
    PRD §3.4: "`enrollment_min_met` is true when `enrolled_count` has reached
    `min_learners`."

    Design: Difficulty/boundary_precision_check/seat_capacity_zero_at_exactly_full_section
    """
    teacher = onboard_active_teacher()
    listing = setup_listing(teacher)
    section = create_section(listing, teacher, min_learners=2, capacity=2)

    learners = [
        create_learner(display_name=f"Learner {i}", birth_date=f"2016-0{i}-01T00:00:00Z", tier="FAMILY")
        for i in (1, 2, 3)
    ]
    first = reserve_seat(listing, section, learners[0])
    second = reserve_seat(listing, section, learners[1])
    confirm_seat(first["id"])
    confirm_seat(second["id"])

    full = get_section(listing["id"], section["id"])
    assert full["capacity"] == 2
    assert full["enrolled_count"] == 2
    assert full["reserved_count"] == 0
    assert full["seats_remaining"] == 0, "exactly two confirmed seats leave zero remaining"
    assert full["enrollment_min_met"] is True

    blocked = api.create_enrollment(
        listing["id"], section["id"], {"learner_id": learners[2]["id"]}, make_parent_headers()
    )
    validate_error(blocked, ApiErrorId.ERR_SECTION_FULL)
    assert get_section(listing["id"], section["id"])["seats_remaining"] == 0


def test_single_seat_section_is_full_after_one_confirmed_enrollment(api):
    """PRD §2.6: "The section has a remaining seat: `seats_remaining` must be greater
    than zero, counting `CONFIRMED` and `RESERVED` enrollments against `capacity`. Any
    failure here is `ERR_SECTION_FULL` (HTTP 409), and it applies to seat reservation."

    Design: Difficulty/boundary_precision_check/seat_capacity_zero_at_exactly_full_section
    """
    teacher = onboard_active_teacher()
    listing = setup_listing(teacher)
    section = create_section(listing, teacher, min_learners=1, capacity=1)

    holder = create_learner(display_name="Learner One", tier="FAMILY")
    blocked_learner = create_learner(
        display_name="Learner Two", birth_date="2016-06-01T00:00:00Z", tier="FAMILY"
    )
    enrollment = reserve_seat(listing, section, holder)
    confirm_seat(enrollment["id"])

    full = get_section(listing["id"], section["id"])
    assert full["enrolled_count"] == 1
    assert full["seats_remaining"] == 0
    assert full["enrollment_min_met"] is True

    blocked = api.create_enrollment(
        listing["id"], section["id"], {"learner_id": blocked_learner["id"]}, make_parent_headers()
    )
    validate_error(blocked, ApiErrorId.ERR_SECTION_FULL)


def test_reserved_seat_blocks_a_second_learner_until_it_is_cancelled(api):
    """PRD §2.6: "The section has a remaining seat: `seats_remaining` must be greater
    than zero, counting `CONFIRMED` and `RESERVED` enrollments against `capacity`. Any
    failure here is `ERR_SECTION_FULL` (HTTP 409), and it applies to seat reservation."
    PRD §3.4: "`enrolled_count` counts enrollments in `CONFIRMED` status,
    `reserved_count` counts those in `RESERVED` status, and `seats_remaining` is
    `capacity` less both counts, never allowed to go negative."

    Design: Difficulty/resource_temporal_overlap/enrollment_seat_occupation_uses_aggregate_capacity
    """
    teacher = onboard_active_teacher()
    listing = setup_listing(teacher)
    section = create_section(listing, teacher, min_learners=1, capacity=1)

    first = create_learner(display_name="Learner One")
    second = create_learner(display_name="Learner Two", birth_date="2016-06-01T00:00:00Z")

    held = reserve_seat(listing, section, first)
    assert held["status"] == "RESERVED"

    blocked = api.create_enrollment(
        listing["id"], section["id"], {"learner_id": second["id"]}, make_parent_headers()
    )
    validate_error(blocked, ApiErrorId.ERR_SECTION_FULL)

    released = get_success_data(api.cancel_enrollment(held["id"], make_parent_headers()))
    assert released["status"] == "CANCELLED_BY_TEACHER"

    admitted = get_success_data(
        api.create_enrollment(
            listing["id"], section["id"], {"learner_id": second["id"]}, make_parent_headers()
        )
    )
    assert admitted["status"] == "RESERVED", "the freed seat was immediately available"

    after = get_section(listing["id"], section["id"])
    assert after["capacity"] == 1
    assert after["reserved_count"] == 1
    assert after["seats_remaining"] == 0


def test_cancelling_one_of_two_reservations_frees_exactly_one_seat(api):
    """PRD §3.4: "`enrolled_count` counts enrollments in `CONFIRMED` status,
    `reserved_count` counts those in `RESERVED` status, and `seats_remaining` is
    `capacity` less both counts, never allowed to go negative."

    Design: Difficulty/resource_temporal_overlap/enrollment_seat_occupation_uses_aggregate_capacity
    """
    teacher = onboard_active_teacher()
    listing = setup_listing(teacher)
    section = create_section(listing, teacher, min_learners=1, capacity=2)

    learners = [
        create_learner(display_name=f"Learner {i}", birth_date=f"2016-0{i}-01T00:00:00Z")
        for i in (1, 2, 3)
    ]
    first = reserve_seat(listing, section, learners[0])
    reserve_seat(listing, section, learners[1])

    saturated = get_section(listing["id"], section["id"])
    assert saturated["reserved_count"] == 2
    assert saturated["seats_remaining"] == 0

    blocked = api.create_enrollment(
        listing["id"], section["id"], {"learner_id": learners[2]["id"]}, make_parent_headers()
    )
    validate_error(blocked, ApiErrorId.ERR_SECTION_FULL)

    get_success_data(api.cancel_enrollment(first["id"], make_parent_headers()))
    freed = get_section(listing["id"], section["id"])
    assert freed["reserved_count"] == 1
    assert freed["seats_remaining"] == 1

    admitted = get_success_data(
        api.create_enrollment(
            listing["id"], section["id"], {"learner_id": learners[2]["id"]}, make_parent_headers()
        )
    )
    assert admitted["status"] == "RESERVED"


def test_confirming_before_the_minimum_is_met_is_rejected(api):
    """PRD §3.6: "Confirmation moves an enrollment from `RESERVED` to `CONFIRMED` and
    requires four things: the section has reached `MIN_ENROLLMENT_MET`, the acting parent
    operator owns the learner, the learner's `confirmation_credit_cents` is at least the
    enrollment's `discounted_price_cents` (otherwise `ERR_CREDIT_INSUFFICIENT`, 409), and
    the enrollment itself is still `RESERVED` (a transition attempted from any other
    state is `ERR_INVALID_STATE`, 409)."
    PRD §3.6: "The confirmation draws the price down from the learner's allowance,
    reducing `confirmation_credit_cents` by exactly the enrollment's
    `discounted_price_cents`."

    Design: Corner/state_machines/confirm_enrollment_before_min_enrollment_met_rejected
    """
    teacher = onboard_active_teacher()
    listing = setup_listing(teacher)
    section = create_section(listing, teacher, min_learners=2, capacity=6)

    learner = create_learner(tier="FAMILY")
    assert learner["confirmation_credit_cents"] == 12000

    enrollment = reserve_seat(listing, section, learner)
    assert enrollment["status"] == "RESERVED"

    response = api.confirm_enrollment(enrollment["id"], make_parent_headers())
    validate_error(response, ApiErrorId.ERR_INVALID_STATE)

    current = get_section(listing["id"], section["id"])
    assert current["status"] == "OPEN_FOR_ENROLLMENT"
    assert current["enrollment_min_met"] is False

    still_reserved = get_enrollment(enrollment["id"])
    assert still_reserved["status"] == "RESERVED"
    assert get_learner(learner["id"])["confirmation_credit_cents"] == 12000, (
        "the rejected confirmation drew down no credit"
    )


def test_cancelled_enrollments_are_excluded_from_seat_counts(api):
    """PRD §3.4: "Enrollments in `PENDING_CONFIRMATION`, `RELEASED` or
    `CANCELLED_BY_TEACHER` hold no seat and are excluded from both counts;
    `PENDING_CONFIRMATION` is a legacy status that this API never produces but must
    still exclude."

    Design: Corner/calculations/section_seat_occupancy_excludes_cancelled_enrollments
    """
    teacher = onboard_active_teacher()
    listing = setup_listing(teacher)
    section = create_section(listing, teacher, min_learners=1, capacity=2)

    keeper = create_learner(display_name="Learner One", tier="FAMILY")
    leaver = create_learner(display_name="Learner Two", birth_date="2016-06-01T00:00:00Z")

    confirmed = reserve_seat(listing, section, keeper)
    confirm_seat(confirmed["id"])
    cancelled = reserve_seat(listing, section, leaver)
    cancelled = get_success_data(api.cancel_enrollment(cancelled["id"], make_parent_headers()))

    assert cancelled["status"] == "CANCELLED_BY_TEACHER"
    current = get_section(listing["id"], section["id"])
    assert current["enrolled_count"] == 1
    assert current["reserved_count"] == 0
    assert current["seats_remaining"] == 1, (
        "the cancelled enrollment released its seat rather than holding it"
    )


def test_duplicate_enrollment_on_the_same_section_is_rejected(api):
    """PRD §2.6: "The learner does not already hold an enrollment on this section in
    `RESERVED`, `PENDING_CONFIRMATION` or `CONFIRMED` status. Any failure here is
    `ERR_DUPLICATE_ENROLLMENT` (HTTP 409), and it applies to seat reservation."

    Design: Corner/validations/duplicate_enrollment_on_same_section_rejected
    """
    teacher = onboard_active_teacher()
    listing = setup_listing(teacher)
    section = create_section(listing, teacher, min_learners=1, capacity=6)

    learner = create_learner()
    first = reserve_seat(listing, section, learner)
    assert first["status"] == "RESERVED"

    response = api.create_enrollment(
        listing["id"], section["id"], {"learner_id": learner["id"]}, make_parent_headers()
    )
    validate_error(response, ApiErrorId.ERR_DUPLICATE_ENROLLMENT)

    assert get_enrollment(first["id"])["status"] == "RESERVED"
    assert get_section(listing["id"], section["id"])["reserved_count"] == 1, (
        "the duplicate attempt created no second reservation"
    )


def test_missing_required_field_on_learner_creation_is_rejected(api):
    """PRD §2.6: "Every required input field for the endpoint is present and non-blank.
    Any failure here is `ERR_MISSING_REQUIRED_FIELD` (HTTP 400), and it applies to every
    endpoint that declares required input."
    PRD §3.5: "Creating one requires a `display_name`, a `birth_date` and the
    `parent_user_id` of the owning parent operator; a birth date that lies after
    `CURRENT_DEFAULT_UTC` is not accepted."

    Design: Corner/entities/create_learner_missing_display_name_rejected
    """
    response = api.create_learner(
        {"birth_date": "2016-05-01T00:00:00Z", "parent_user_id": "p_1"},
        make_parent_headers(),
    )
    validate_error(response, ApiErrorId.ERR_MISSING_REQUIRED_FIELD)


def test_fresh_learner_carries_the_declared_defaults(api):
    """PRD §3.5: "A fresh learner starts with `subscription_tier` `NONE`,
    `subscription_discount_pct` of 0.00, `confirmation_credit_cents` of zero,
    `abuse_strike_count` of zero, and `enrollment_sequence` at zero."

    Design: Corner/entities/learner_defaults_applied_on_creation
    """
    learner = create_learner()
    assert learner["subscription_tier"] == "NONE"
    assert learner["subscription_discount_pct"] == 0.00
    assert learner["confirmation_credit_cents"] == 0
    assert learner["enrollment_sequence"] == 0
    assert learner["abuse_strike_count"] == 0


def test_a_new_reservation_is_visible_in_the_next_section_read(api):
    """PRD §3.4: "Occupancy is recomputed on every status change of any enrollment
    carrying that section's `section_id`."

    Design: Corner/cross_cutting_complexity_layers/enrollment_write_visible_in_the_same_read
    """
    teacher = onboard_active_teacher()
    listing = setup_listing(teacher)
    section = create_section(listing, teacher, min_learners=1, capacity=6)

    before = get_section(listing["id"], section["id"])
    assert before["seats_remaining"] == 6

    learner = create_learner()
    enrollment = reserve_seat(listing, section, learner)
    assert enrollment["status"] == "RESERVED"

    listing_sections = api.list_sections(listing["id"], make_teacher_headers(teacher["id"]))
    data, _meta = validate_paginated(listing_sections)
    reported = next(item for item in data if item["id"] == section["id"])
    assert reported["seats_remaining"] == 5, (
        "the very next read already reflects the reservation, with no reconciliation lag"
    )
    assert reported["reserved_count"] == 1
