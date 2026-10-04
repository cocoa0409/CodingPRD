"""Title licensing and royalty ledger: chronological accrual, the strict cap
boundary, license flips, and the cancellation reversal that flips them back.
"""

from prd_bench_local_runner.testing import validate_error, validate_paginated, validate_success

from test_helpers import (
    add_line,
    add_offering,
    create_cycle,
    create_order,
    create_redemption,
    create_school,
    create_teacher,
    create_title,
    enroll_school,
    make_teacher_headers,
    publish_cycle,
    read_teacher,
    read_title,
    submit_order,
    TEST_USERS,
)

CLUB_ADMIN = TEST_USERS["club_admin_headers"]


def _school_with_teacher(api, name):
    school = create_school(api, name=name, low_income_program=False)
    enroll_school(api, school["id"])
    teacher = create_teacher(api, school["id"], grade_band="G3_5", full_name=f"{name} Teacher")
    return school, teacher


def _published_cycle_with_offering(api, school_id, title_id):
    cycle = create_cycle(api, school_id, month="2026-10", grade_band="G3_5")
    offering = add_offering(api, cycle["id"], title_id)
    publish_cycle(api, cycle["id"])
    return cycle, offering


def test_submit_accrues_royalty_and_cancel_reverses_the_flip(api):
    """Submit accrues and flips the license; cancel reverses exactly.

    PRD: "Royalties accrue at a flat 90 cents per unit moved. Three events
    accrue royalty, each per unit: a class order submission accrues for every
    ordered line's quantity; a donation fulfillment accrues for the matched
    quantity; and confirming a book-kind redemption accrues for the redeemed
    quantity, since redemption copies are club editions."
    PRD: "The first unit that pushes the title's `royalty_accrued_cents`
    strictly above its `royalty_cap_cents` flips the title's `license_status`
    from `ACTIVE` to `SUSPENDED`; the comparison is strict — landing exactly on
    the cap leaves the license `ACTIVE`."
    PRD: "Cancellation of a submitted class order reverses accrual,
    decrementing `royalty_accrued_cents` by 90 cents times each line's
    quantity; if the running total falls back to at or below the cap, the
    license flips from `SUSPENDED` back to `ACTIVE`."

    Design: Difficulty/dual_variant_calc/royalty_chronological_accrual_vs_cancellation_reversal
    """
    school, teacher = _school_with_teacher(api, "Royalty School")
    title = create_title(api, name="Capped Title", base_price_cents=1000, points_cost=10,
                         royalty_cap_cents=180)
    cycle, offering = _published_cycle_with_offering(api, school["id"], title["id"])

    order = create_order(api, cycle["id"], teacher["id"])
    add_line(api, order["id"], offering["id"], qty=3, teacher_id=teacher["id"])

    submitted = submit_order(api, order["id"], teacher["id"])
    assert submitted["status"] == "SUBMITTED"
    assert submitted["points_status"] == "AWARDED"

    title_after_submit = read_title(api, title["id"])
    assert title_after_submit["royalty_accrued_cents"] == 270, "3 units at 90 cents each"
    assert title_after_submit["license_status"] == "SUSPENDED", "270 is strictly above the 180 cap"

    headers = make_teacher_headers(teacher["id"])
    cancelled = validate_success(api.cancel_class_order(order["id"], headers))
    assert cancelled["status"] == "CANCELLED"
    assert cancelled["points_status"] == "CLAWED_BACK"

    title_after_cancel = read_title(api, title["id"])
    assert title_after_cancel["royalty_accrued_cents"] == 0
    assert title_after_cancel["license_status"] == "ACTIVE", (
        "the reversal drops the total to at or below the cap, flipping the license back"
    )

    teacher_after = read_teacher(api, teacher["id"])
    assert teacher_after["points_balance"] == 0, "the clawback restores the zero balance"
    assert teacher_after["points_earned_total"] == 30, (
        "the earned total is unchanged — the clawback is tracked as a negative ledger entry"
    )


def test_cancel_reversal_flips_only_when_total_returns_to_cap_or_below(api):
    """A partial headroom reversal keeps the license suspended until at cap.

    PRD: "Cancellation of a submitted class order reverses accrual,
    decrementing `royalty_accrued_cents` by 90 cents times each line's
    quantity; if the running total falls back to at or below the cap, the
    license flips from `SUSPENDED` back to `ACTIVE`."
    PRD: "The first unit that pushes the title's `royalty_accrued_cents`
    strictly above its `royalty_cap_cents` flips the title's `license_status`
    from `ACTIVE` to `SUSPENDED`; the comparison is strict — landing exactly on
    the cap leaves the license `ACTIVE`."

    Design: Difficulty/dual_variant_calc/royalty_chronological_accrual_vs_cancellation_reversal
    """
    school, teacher = _school_with_teacher(api, "Headroom School")
    title = create_title(api, name="Headroom Title", base_price_cents=1000, points_cost=10,
                         royalty_cap_cents=180)
    cycle, offering = _published_cycle_with_offering(api, school["id"], title["id"])

    # First order: 3 units -> accrued 270 > 180 -> SUSPENDED at submit, and the
    # line backorders. Cancel returns accrued to 90 (<= cap) -> ACTIVE again.
    first = create_order(api, cycle["id"], teacher["id"])
    add_line(api, first["id"], offering["id"], qty=3, teacher_id=teacher["id"])
    submit_order(api, first["id"], teacher["id"])
    assert read_title(api, title["id"])["license_status"] == "SUSPENDED"

    validate_success(api.cancel_class_order(first["id"], make_teacher_headers(teacher["id"])))
    title_after = read_title(api, title["id"])
    assert title_after["royalty_accrued_cents"] == 0
    assert title_after["license_status"] == "ACTIVE"

    # Second order: exactly 2 units -> accrued 180 == cap -> stays ACTIVE.
    second = create_order(api, cycle["id"], teacher["id"])
    add_line(api, second["id"], offering["id"], qty=2, teacher_id=teacher["id"])
    submit_order(api, second["id"], teacher["id"])
    title_final = read_title(api, title["id"])
    assert title_final["royalty_accrued_cents"] == 180
    assert title_final["license_status"] == "ACTIVE", "landing exactly on the cap keeps ACTIVE"


def test_cap_equality_keeps_active_and_one_more_unit_suspends(api):
    """Exactly at the cap is ACTIVE; the next unit flips SUSPENDED.

    PRD: "The first unit that pushes the title's `royalty_accrued_cents`
    strictly above its `royalty_cap_cents` flips the title's `license_status`
    from `ACTIVE` to `SUSPENDED`; the comparison is strict — landing exactly on
    the cap leaves the license `ACTIVE`."

    Design: Difficulty/boundary_precision_check/royalty_cap_equality_keeps_active_excess_suspends
    """
    school, teacher = _school_with_teacher(api, "Cap School")
    title = create_title(api, name="Boundary Title", base_price_cents=1000, points_cost=10,
                         royalty_cap_cents=180)
    cycle, offering = _published_cycle_with_offering(api, school["id"], title["id"])

    order_a = create_order(api, cycle["id"], teacher["id"])
    add_line(api, order_a["id"], offering["id"], qty=2, teacher_id=teacher["id"])
    submit_order(api, order_a["id"], teacher["id"])

    title_mid = read_title(api, title["id"])
    assert title_mid["royalty_accrued_cents"] == 180, "2 units at 90 cents each"
    assert title_mid["license_status"] == "ACTIVE", "equality with the cap does not suspend"

    order_b = create_order(api, cycle["id"], teacher["id"])
    add_line(api, order_b["id"], offering["id"], qty=1, teacher_id=teacher["id"])
    submitted_b = submit_order(api, order_b["id"], teacher["id"])

    title_end = read_title(api, title["id"])
    assert title_end["royalty_accrued_cents"] == 270
    assert title_end["license_status"] == "SUSPENDED", "270 is strictly above the 180 cap"
    assert submitted_b["status"] == "SUBMITTED", "the in-flight submission completes"
    assert submitted_b["ship_status"] == "PENDING", (
        "the title suspended during its own submit, so its line backorders"
    )


def test_royalty_accrues_per_unit_before_the_cap_crossing(api):
    """Each unit accrues 90 cents; the crossing unit flips the license.

    PRD: "Royalties accrue at a flat 90 cents per unit moved."
    PRD: "Units are applied in chronological order of the triggering event's
    `created_at`, earliest first. The first unit that pushes the title's
    `royalty_accrued_cents` strictly above its `royalty_cap_cents` flips the
    title's `license_status` from `ACTIVE` to `SUSPENDED`; the comparison is
    strict — landing exactly on the cap leaves the license `ACTIVE`.
    Suspension never blocks the in-flight event: the whole submission,
    fulfillment, or confirmation completes first, and only then does the title
    flip."

    Design: Difficulty/boundary_precision_check/royalty_cap_equality_keeps_active_excess_suspends
    """
    school, teacher = _school_with_teacher(api, "Unit School")
    title = create_title(api, name="Per Unit Title", base_price_cents=1000, points_cost=10,
                         royalty_cap_cents=90)
    cycle, offering = _published_cycle_with_offering(api, school["id"], title["id"])

    # One unit lands exactly on the cap: ACTIVE.
    order_1 = create_order(api, cycle["id"], teacher["id"])
    add_line(api, order_1["id"], offering["id"], qty=1, teacher_id=teacher["id"])
    submit_order(api, order_1["id"], teacher["id"])
    assert read_title(api, title["id"])["license_status"] == "ACTIVE"
    assert read_title(api, title["id"])["royalty_accrued_cents"] == 90

    # The second unit pushes 180 > 90: SUSPENDED, and the whole submit completes.
    order_2 = create_order(api, cycle["id"], teacher["id"])
    add_line(api, order_2["id"], offering["id"], qty=1, teacher_id=teacher["id"])
    submitted_2 = submit_order(api, order_2["id"], teacher["id"])
    assert submitted_2["status"] == "SUBMITTED"
    title_end = read_title(api, title["id"])
    assert title_end["royalty_accrued_cents"] == 180
    assert title_end["license_status"] == "SUSPENDED"
