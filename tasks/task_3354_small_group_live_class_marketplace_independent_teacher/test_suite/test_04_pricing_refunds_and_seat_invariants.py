"""Discount stacking, refund tiers, coupon redemption and seat conservation."""
from test_helpers import (
    ApiErrorId,
    cancel_section,
    confirm_seat,
    create_learner,
    create_section,
    get_enrollment,
    get_payout,
    get_section,
    get_success_data,
    get_teacher,
    make_parent_headers,
    onboard_active_teacher,
    reserve_seat,
    set_clock,
    setup_compensating_refund_scenario,
    setup_listing,
    subscribe_learner,
    validate_error,
)


def test_multi_day_cancellation_far_out_refunds_nothing_under_the_timing_selector(api):
    """PRD §3.6: "The general rule selects the tier from the hours remaining and the
    listing's `format`. A full refund is granted when the whole hours remaining are at
    least the full-refund cutoff for that format: 168 hours for `ONE_TIME`, 336 hours for
    `MULTI_DAY`, and 336 hours for `ONGOING`. Failing that, a half refund is granted when
    the cancellation is a learner-fault cancellation and the whole hours remaining are at
    least the half-refund cutoff for that format: 24 hours for `ONE_TIME`, 72 hours for
    `MULTI_DAY`, and 168 hours for `ONGOING`. Otherwise the tier is `NONE`."
    PRD §3.6: "The rejected alternative reading — selecting the tier from the format
    alone, granting `FULL` to every `ONE_TIME` cancellation, `PARTIAL_HALF` to every
    `MULTI_DAY` cancellation and `NONE` to every `ONGOING` cancellation regardless of how
    far ahead the cancellation arrives — is never applied by the server; it is recorded
    here only because it disagrees with the timing rule on the same request."

    Design: Difficulty/dual_variant_calc/refund_tier_timing_vs_format_on_enrollment
    """
    teacher = onboard_active_teacher()
    listing = setup_listing(teacher, title="Algebra Club", format="MULTI_DAY", list_price_cents=2000)
    section = create_section(
        listing, teacher,
        start_utc="2026-10-15T14:00:00Z", end_utc="2026-10-15T16:00:00Z",
        min_learners=1, capacity=6,
    )
    learner = create_learner()
    enrollment = reserve_seat(listing, section, learner)
    assert enrollment["discounted_price_cents"] == 2000

    # 50 whole hours before the start: below the 72-hour half-refund cutoff for MULTI_DAY.
    set_clock("2026-10-13T12:00:00Z")
    cancelled = get_success_data(api.cancel_enrollment(enrollment["id"], make_parent_headers()))

    assert cancelled["status"] == "CANCELLED_BY_TEACHER"
    assert cancelled["refund_category"] == "NONE", (
        "the timing selector returns NONE; the rejected format selector would have said PARTIAL_HALF"
    )
    assert cancelled["refund_cents"] == 0
    assert cancelled["cash_refund_cents"] == 0


def test_multi_day_cancellation_inside_the_full_window_refunds_the_whole_price(api):
    """PRD §3.6: "A full refund is granted when the whole hours remaining are at least
    the full-refund cutoff for that format: 168 hours for `ONE_TIME`, 336 hours for
    `MULTI_DAY`, and 336 hours for `ONGOING`."
    PRD §3.6: "`refund_cents` is zero for `NONE`, the enrollment's `discounted_price_cents`
    multiplied by the partial-refund rate of 0.50 and floored to a whole cent for
    `PARTIAL_HALF`, and the full `discounted_price_cents` for `FULL`."

    Design: Difficulty/dual_variant_calc/refund_tier_timing_vs_format_on_enrollment
    """
    teacher = onboard_active_teacher()
    listing = setup_listing(teacher, title="Algebra Club", format="MULTI_DAY", list_price_cents=2000)
    section = create_section(
        listing, teacher,
        start_utc="2026-10-15T14:00:00Z", end_utc="2026-10-15T16:00:00Z",
        min_learners=1, capacity=6,
    )
    learner = create_learner()
    enrollment = reserve_seat(listing, section, learner)
    assert enrollment["discounted_price_cents"] == 2000

    # 400 whole hours before the start: past the 336-hour full-refund cutoff for MULTI_DAY.
    set_clock("2026-09-28T22:00:00Z")
    cancelled = get_success_data(api.cancel_enrollment(enrollment["id"], make_parent_headers()))

    assert cancelled["refund_category"] == "FULL", (
        "the timing selector promotes the tier with the remaining hours, so the tier is not format-keyed"
    )
    assert cancelled["refund_cents"] == 2000
    assert cancelled["cash_refund_cents"] == 2000


def test_discount_stack_applies_the_subscription_before_the_coupon(api):
    """PRD §3.5: "The subscription discount is always computed first, on the undiscounted
    list price, and the coupon always applies to what remains after it. The rejected
    alternative — applying the coupon to the list price first and the plan discount to the
    remainder — is never used by the server; it is documented only because it diverges on
    identical inputs. For a 3333-cent listing with a 10 percent plan and a 15 percent
    coupon, the applied order yields 2550 cents while the rejected order would yield 2551."

    Design: Difficulty/combinatorial_formula/discount_stacking_order_on_enrollment
    """
    teacher = onboard_active_teacher()
    listing = setup_listing(teacher, title="Geometry Lab", list_price_cents=3333)
    section = create_section(listing, teacher, min_learners=1, capacity=6)
    learner = create_learner(tier="PLUS")
    assert learner["subscription_discount_pct"] == 0.10

    enrollment = reserve_seat(listing, section, learner, coupon_code="SPRING15")
    assert enrollment["subscription_discount_cents"] == 333, (
        "the plan discount is floored on the undiscounted list price"
    )
    assert enrollment["coupon_discount_cents"] == 450, (
        "the coupon applies to the price that remains after the plan discount"
    )
    assert enrollment["discounted_price_cents"] == 2550, (
        "the rejected coupon-first order would have produced 2551"
    )


def test_discount_stack_floors_each_step_independently(api):
    """PRD §3.5: "Step one computes the subscription discount as the list price multiplied
    by the learner's `subscription_discount_pct`, floored to a whole cent, and records it in
    `subscription_discount_cents`. Step two subtracts that from the list price to obtain the
    price that remains. Step three computes the coupon discount on that remaining price —
    for a percent coupon, the remaining price multiplied by the coupon's value, floored to a
    whole cent; for an amount coupon, the coupon's face value in cents — and records it in
    `coupon_discount_cents`."
    PRD §3.5: "Every step floors independently and no step re-rounds a value an earlier step
    produced."

    Design: Difficulty/combinatorial_formula/discount_stacking_order_on_enrollment
    """
    teacher = onboard_active_teacher()
    listing = setup_listing(teacher, title="Geometry Lab", list_price_cents=3333)
    section = create_section(listing, teacher, min_learners=1, capacity=6)
    learner = create_learner(tier="FAMILY")
    assert learner["subscription_discount_pct"] == 0.20

    enrollment = reserve_seat(listing, section, learner, coupon_code="SIBLING10")
    assert enrollment["subscription_discount_cents"] == 666, "floor(3333 * 0.20) == 666"
    assert enrollment["coupon_discount_cents"] == 266, "floor(2667 * 0.10) == 266"
    assert enrollment["discounted_price_cents"] == 2401, (
        "3333 - 666 - 266; the rejected coupon-first order would have produced 2400"
    )


def test_partial_refund_floors_the_half_rate(api):
    """PRD §3.6: "`refund_cents` is zero for `NONE`, the enrollment's `discounted_price_cents`
    multiplied by the partial-refund rate of 0.50 and floored to a whole cent for
    `PARTIAL_HALF`, and the full `discounted_price_cents` for `FULL`."
    PRD §2.9: "Rounding is always floor truncation toward the lower integer. There is no
    round-half-up anywhere in this system, and no step is allowed to re-round a value that
    an earlier step already produced."

    Design: Corner/calculations/partial_refund_uses_floor_truncation
    """
    teacher = onboard_active_teacher()
    listing = setup_listing(teacher, list_price_cents=3333)
    section = create_section(
        listing, teacher,
        start_utc="2026-11-05T14:00:00Z", end_utc="2026-11-05T16:00:00Z",
        min_learners=1, capacity=6,
    )
    learner = create_learner()
    enrollment = reserve_seat(listing, section, learner)
    assert enrollment["discounted_price_cents"] == 3333

    # 100 whole hours before the start: inside the half-refund band for ONE_TIME.
    set_clock("2026-11-01T10:00:00Z")
    cancelled = get_success_data(api.cancel_enrollment(enrollment["id"], make_parent_headers()))

    assert cancelled["refund_category"] == "PARTIAL_HALF"
    assert cancelled["refund_cents"] == 1666, (
        "half of 3333 is 1666.5, so 1666 pins floor truncation rather than round-half-up"
    )


def test_coupon_cannot_be_redeemed_twice_by_the_same_learner(api):
    """PRD §3.5: "A coupon may be used once per learner in earnest: if the learner already
    holds a `CONFIRMED` enrollment that redeemed the same code, the new reservation is
    refused with `ERR_COUPON_ALREADY_REDEEMED` (409)."

    Design: Corner/validations/coupon_already_redeemed_rejected
    """
    teacher = onboard_active_teacher()
    listing = setup_listing(teacher)
    first_section = create_section(
        listing, teacher, start_utc="2026-11-05T14:00:00Z", end_utc="2026-11-05T16:00:00Z",
        min_learners=1, capacity=6,
    )
    second_section = create_section(
        listing, teacher, start_utc="2026-11-06T14:00:00Z", end_utc="2026-11-06T16:00:00Z",
        min_learners=1, capacity=6,
    )
    learner = create_learner(tier="FAMILY")

    first = reserve_seat(listing, first_section, learner, coupon_code="FLAT250")
    assert first["coupon_discount_cents"] == 250
    confirmed = confirm_seat(first["id"])
    assert confirmed["status"] == "CONFIRMED"

    response = api.create_enrollment(
        listing["id"], second_section["id"],
        {"learner_id": learner["id"], "coupon_code": "FLAT250"},
        make_parent_headers(),
    )
    validate_error(response, ApiErrorId.ERR_COUPON_ALREADY_REDEEMED)
    assert get_section(listing["id"], second_section["id"])["reserved_count"] == 0, (
        "the rejected attempt created no reservation"
    )


def test_teacher_fault_section_cancel_conserves_the_refunded_sections_net(api):
    """PRD §3.8: "`teacher_liability_cents` is written as the sum, over the refunded
    sections, of the section's original discounted total less the floored fee on it,
    multiplied by the teacher-liability rate of 0.50 and floored, so the teacher owes back
    half of what remains after the platform's reversed fee is deducted; `net_after_refunds_cents`
    is recomputed as gross less platform fee less the reversed fee; `refund_period_index` is
    stamped with the current period index; the payout's status becomes `FAILED`; and its
    `approval_status` becomes `pending_approval`."
    PRD §3.8: "a section cancelled before it starts drops out of the sum entirely because
    its `outcome` is no longer null or `HELD`; this is precisely why a teacher-fault refund
    moves a payout."

    Design: Difficulty/compensating_invariant/teacher_fault_refund_conserves_section_gross
    """
    scenario = setup_compensating_refund_scenario()
    teacher, listing = scenario["teacher"], scenario["listing"]
    keep, drop = scenario["sections"]
    payout = scenario["payout"]

    assert payout["gross_earnings_cents"] == 3200
    assert payout["platform_fee_cents"] == 800
    assert payout["net_payout_cents"] == 2400

    cancel_section(listing["id"], drop["id"], teacher["id"])

    after = get_payout(payout["id"])
    assert after["status"] == "FAILED", "the clawback moved the payout to FAILED"
    assert after["approval_status"] == "pending_approval"
    assert after["gross_earnings_cents"] == 1600, "the refunded section dropped out of the accrual set"
    assert after["platform_fee_cents"] == 400
    assert after["net_payout_cents"] == 1200
    assert after["platform_fee_reversed_cents"] == 400
    assert after["teacher_liability_cents"] == 600, (
        "the teacher owes back half of the refunded section's total after the reversed fee"
    )

    refunded = get_enrollment(scenario["enrollments"][1]["id"])
    assert refunded["refund_cents"] == 1600

    fresh_teacher = get_teacher(teacher["id"])
    assert fresh_teacher["lifetime_net_earnings_cents"] == 1200, (
        "lifetime earnings landed exactly on the surviving section's net"
    )
    assert fresh_teacher["lifetime_fee_reversed_cents"] == 400
    assert fresh_teacher["lifetime_teacher_liability_cents"] == 600
    assert get_section(listing["id"], keep["id"])["status"] == "MIN_ENROLLMENT_MET", (
        "the surviving section was not cancelled: its reservations filled its floor, so it "
        "rests in MIN_ENROLLMENT_MET rather than OPEN_FOR_ENROLLMENT"
    )


def test_teacher_fault_refund_returns_the_full_gross_while_clawing_back_the_fee(api):
    """PRD §3.8: "The first hop finds every payout of the owning teacher that is still in
    `REQUESTED` and whose period covers the refunded section's `start_utc` — that is,
    `start_utc` is at or after `period_start` and strictly before `period_end` — and
    recomputes it".
    PRD §3.6: "`refund_cents` is zero for `NONE`, the enrollment's `discounted_price_cents`
    multiplied by the partial-refund rate of 0.50 and floored to a whole cent for
    `PARTIAL_HALF`, and the full `discounted_price_cents` for `FULL`."

    Design: Difficulty/compensating_invariant/teacher_fault_refund_conserves_section_gross
    """
    scenario = setup_compensating_refund_scenario()
    teacher, listing = scenario["teacher"], scenario["listing"]
    drop = scenario["sections"][1]
    payout = scenario["payout"]

    cancel_section(listing["id"], drop["id"], teacher["id"])

    refunded = get_enrollment(scenario["enrollments"][1]["id"])
    after = get_payout(payout["id"])
    surviving_net = after["net_payout_cents"]

    assert refunded["refund_cents"] - after["platform_fee_reversed_cents"] == surviving_net, (
        "the refund less the reversed fee equals the surviving section's net, so no money drifted"
    )
    assert get_teacher(teacher["id"])["lifetime_net_earnings_cents"] == surviving_net


def test_reserving_and_cancelling_a_seat_leaves_the_seat_budget_intact(api):
    """PRD §3.4: "The invariant `seats_remaining` greater than or equal to zero must hold
    after every write."
    PRD §3.4: "`enrolled_count` counts enrollments in `CONFIRMED` status, `reserved_count`
    counts those in `RESERVED` status, and `seats_remaining` is `capacity` less both counts,
    never allowed to go negative."

    Design: Difficulty/compensating_invariant/seat_reserve_cancel_conserves_section_capacity
    """
    teacher = onboard_active_teacher()
    listing = setup_listing(teacher)
    section = create_section(listing, teacher, min_learners=1, capacity=3)

    holder = create_learner(display_name="Learner One", tier="FAMILY")
    round_tripper = create_learner(display_name="Learner Two", birth_date="2016-06-01T00:00:00Z")

    kept = reserve_seat(listing, section, holder)
    confirm_seat(kept["id"])

    reserved = reserve_seat(listing, section, round_tripper)
    mid = get_section(listing["id"], section["id"])
    assert mid["enrolled_count"] == 1
    assert mid["reserved_count"] == 1
    assert mid["seats_remaining"] == 1

    cancelled = get_success_data(api.cancel_enrollment(reserved["id"], make_parent_headers()))
    assert cancelled["status"] == "CANCELLED_BY_TEACHER"

    final = get_section(listing["id"], section["id"])
    assert final["capacity"] == 3
    assert final["enrolled_count"] == 1
    assert final["reserved_count"] == 0
    assert final["seats_remaining"] == 2, (
        "capacity == enrolled + reserved + remaining both before and after the round trip"
    )


def test_a_cancelled_reservation_returns_its_seat_to_the_pool(api):
    """PRD §3.4: "Enrollments in `PENDING_CONFIRMATION`, `RELEASED` or
    `CANCELLED_BY_TEACHER` hold no seat and are excluded from both counts;
    `PENDING_CONFIRMATION` is a legacy status that this API never produces but must still
    exclude."

    Design: Difficulty/compensating_invariant/seat_reserve_cancel_conserves_section_capacity
    """
    teacher = onboard_active_teacher()
    listing = setup_listing(teacher)
    section = create_section(listing, teacher, min_learners=1, capacity=2)

    first = create_learner(display_name="Learner One")
    second = create_learner(display_name="Learner Two", birth_date="2016-06-01T00:00:00Z")
    third = create_learner(display_name="Learner Three", birth_date="2016-07-01T00:00:00Z")

    reserved = reserve_seat(listing, section, first)
    get_success_data(api.cancel_enrollment(reserved["id"], make_parent_headers()))

    second_reservation = reserve_seat(listing, section, second)
    third_reservation = reserve_seat(listing, section, third)
    assert second_reservation["status"] == "RESERVED"
    assert third_reservation["status"] == "RESERVED"

    current = get_section(listing["id"], section["id"])
    assert current["reserved_count"] == 2
    assert current["seats_remaining"] == 0
    assert current["capacity"] == current["enrolled_count"] + current["reserved_count"] + current["seats_remaining"]
