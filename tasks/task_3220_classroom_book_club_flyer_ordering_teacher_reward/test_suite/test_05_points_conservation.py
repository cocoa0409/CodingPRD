"""Points conservation: submit-then-cancel restores the exact prior balance,
and the acquire/cancel round-trip restores royalty headroom.
"""

from prd_bench_local_runner.testing import validate_error, validate_paginated, validate_success

from test_helpers import (
    add_line,
    add_offering,
    create_cycle,
    create_order,
    create_promotion,
    create_redemption,
    create_school,
    create_teacher,
    create_title,
    enroll_school,
    make_teacher_headers,
    publish_cycle,
    read_order,
    read_teacher,
    read_title,
    set_clock,
    setup_submitted_order,
    submit_order,
    TEST_USERS,
)

CLUB_ADMIN = TEST_USERS["club_admin_headers"]


def _school_with_teacher(api, name):
    school = create_school(api, name=name, low_income_program=False)
    enroll_school(api, school["id"])
    teacher = create_teacher(api, school["id"], grade_band="G3_5", full_name=f"{name} Teacher")
    return school, teacher


def test_cancel_after_promo_expiry_claws_back_the_pinned_amount(api):
    """The clawback reverses the pinned award, not a recomputation.

    PRD: "and the clawback runs — the original pinned `awarded_total_points`
    (never a recomputation, so later promotion expiries or price edits cannot
    change it) is subtracted from the teacher's `points_balance`, a
    points-ledger `CLAWBACK` entry is appended, and `points_status` moves from
    `AWARDED` to `CLAWED_BACK`."

    Design: Difficulty/compensating_invariant/submit_then_cancel_conserves_teacher_points
    """
    school, teacher = _school_with_teacher(api, "Pinned School")
    # The cap suspends the title at submission, backordering the line so
    # ship_status stays PENDING and the cancel-from-SUBMITTED path is legal.
    title = create_title(api, name="Pinned Title", base_price_cents=1500, points_cost=15,
                         royalty_cap_cents=89)
    create_promotion(api, name="Double October", kind="BONUS_POINTS", multiplier_bp=200)
    cycle = create_cycle(api, school["id"], month="2026-10", grade_band="G3_5")
    offering = add_offering(api, cycle["id"], title["id"])
    publish_cycle(api, cycle["id"])

    order = create_order(api, cycle["id"], teacher["id"])
    add_line(api, order["id"], offering["id"], qty=2, teacher_id=teacher["id"])

    set_clock(api, "2026-10-15T00:00:00Z")
    submitted = submit_order(api, order["id"], teacher["id"])
    # Base 30, double-earn multiplier bonus 30, total 60.
    assert submitted["awarded_total_points"] == 60
    assert read_teacher(api, teacher["id"])["points_balance"] == 60

    # The promotion expires before the cancel.
    set_clock(api, "2026-11-02T00:00:00Z")
    cancelled = validate_success(
        api.cancel_class_order(order["id"], make_teacher_headers(teacher["id"]))
    )
    assert cancelled["points_status"] == "CLAWED_BACK"
    teacher_after = read_teacher(api, teacher["id"])
    assert teacher_after["points_balance"] == 0, (
        "the pinned 60 is clawed back even though the promotion expired"
    )
    assert teacher_after["points_earned_total"] == 60, (
        "the earned total is left unchanged; the clawback is a negative ledger entry"
    )

    ledger, _ = validate_paginated(
        api.list_teacher_points_ledger(teacher["id"], make_teacher_headers(teacher["id"]))
    )
    kinds = [(entry["entry_type"], entry["points"]) for entry in ledger]
    assert ("EARN", 60) in kinds
    assert ("CLAWBACK", -60) in kinds


def test_submit_then_cancel_round_trip_restores_balance_and_reconciles(api):
    """Balance returns to zero while earned history is preserved.

    PRD: "The submitted-path cancel performs the full unwind: every
    non-cancelled line moves to `CANCELLED`; royalty accrual is reversed per
    §3.3, potentially flipping licenses back to `ACTIVE`; and the clawback runs
    — the original pinned `awarded_total_points` ... is subtracted from the
    teacher's `points_balance`..."
    PRD: "The teacher's `points_earned_total` is left unchanged — the clawback
    is tracked as a negative ledger entry and the balance is recomputed, not
    rewritten."

    Design: Difficulty/compensating_invariant/submit_then_cancel_conserves_teacher_points
    """
    # The cap suspends the title at submission, backordering the line so
    # ship_status stays PENDING and the cancel-from-SUBMITTED path is legal.
    world = setup_submitted_order(
        api,
        line_specs=[{"offering_index": 0, "qty": 2}],
        school_name="Round Trip School",
        title_overrides=[{"base_price_cents": 1500, "points_cost": 15,
                          "royalty_cap_cents": 89}],
    )
    order = world["order"]
    teacher = world["teacher"]
    assert order["awarded_total_points"] == 30
    assert teacher["points_balance"] == 30

    cancelled = validate_success(
        api.cancel_class_order(order["id"], make_teacher_headers(teacher["id"]))
    )
    assert cancelled["status"] == "CANCELLED"
    assert cancelled["points_status"] == "CLAWED_BACK"

    after = read_teacher(api, teacher["id"])
    assert after["points_balance"] == 0
    assert after["points_earned_total"] == 30
    assert after["points_redeemed_total"] == 0
    assert after["points_expired_total"] == 0

    lines, _ = validate_paginated(
        api.list_order_lines(order["id"], make_teacher_headers(teacher["id"]))
    )
    assert all(line["status"] == "CANCELLED" for line in lines)


def test_submit_then_cancel_restores_royalty_headroom_exactly(api):
    """Accrual plus reversal leaves the title's headroom bit-identical.

    PRD: "Cancellation of a submitted class order reverses accrual,
    decrementing `royalty_accrued_cents` by 90 cents times each line's
    quantity; if the running total falls back to at or below the cap, the
    license flips from `SUSPENDED` back to `ACTIVE`."
    PRD: "Royalties accrue at a flat 90 cents per unit moved."

    Design: Difficulty/compensating_invariant/acquire_renew_cycle_conserves_royalty_cap_headroom
    """
    school, teacher = _school_with_teacher(api, "Headroom Conserve School")
    title = create_title(
        api, name="Headroom Title", base_price_cents=1000, points_cost=10, royalty_cap_cents=500
    )
    # A decoy title whose cap trips at submission keeps one line BACKORDERED,
    # so ship_status stays PENDING and the cancel-from-SUBMITTED path is legal.
    decoy = create_title(
        api, name="Decoy Title", base_price_cents=1000, points_cost=10, royalty_cap_cents=89
    )
    cycle = create_cycle(api, school["id"], month="2026-10", grade_band="G3_5")
    offering = add_offering(api, cycle["id"], title["id"])
    decoy_offering = add_offering(api, cycle["id"], decoy["id"])
    publish_cycle(api, cycle["id"])

    order = create_order(api, cycle["id"], teacher["id"])
    add_line(api, order["id"], offering["id"], qty=3, teacher_id=teacher["id"])
    add_line(api, order["id"], decoy_offering["id"], qty=1, teacher_id=teacher["id"])
    submitted = submit_order(api, order["id"], teacher["id"])
    assert submitted["ship_status"] == "PENDING", "the decoy line is backordered"

    mid = read_title(api, title["id"])
    assert mid["royalty_accrued_cents"] == 270, "3 units at 90 cents each"
    assert mid["license_status"] == "ACTIVE", "270 <= 500"
    assert mid["royalty_cap_cents"] - mid["royalty_accrued_cents"] == 230

    validate_success(api.cancel_class_order(order["id"], make_teacher_headers(teacher["id"])))
    final = read_title(api, title["id"])
    assert final["royalty_accrued_cents"] == 0
    assert final["license_status"] == "ACTIVE"
    assert final["royalty_cap_cents"] - final["royalty_accrued_cents"] == 500, (
        "headroom restored to exactly the original 500"
    )
    assert read_teacher(api, teacher["id"])["points_balance"] == 0


def test_cancel_reversal_allows_later_submit_to_stay_under_cap(api):
    """After a full reversal, a later submit re-accrues from zero.

    PRD: "Cancellation of a submitted class order reverses accrual,
    decrementing `royalty_accrued_cents` by 90 cents times each line's
    quantity; if the running total falls back to at or below the cap, the
    license flips from `SUSPENDED` back to `ACTIVE`."
    PRD: "Royalties accrue at a flat 90 cents per unit moved. Three events
    accrue royalty, each per unit: a class order submission accrues for every
    ordered line's quantity; a donation fulfillment accrues for the matched
    quantity; and confirming a book-kind redemption accrues for the redeemed
    quantity, since redemption copies are club editions."

    Design: Difficulty/compensating_invariant/acquire_renew_cycle_conserves_royalty_cap_headroom
    """
    school, teacher = _school_with_teacher(api, "Reaccrue School")
    title = create_title(
        api, name="Reaccrue Title", base_price_cents=1000, points_cost=10, royalty_cap_cents=270
    )
    cycle = create_cycle(api, school["id"], month="2026-10", grade_band="G3_5")
    offering = add_offering(api, cycle["id"], title["id"])
    publish_cycle(api, cycle["id"])

    first = create_order(api, cycle["id"], teacher["id"])
    add_line(api, first["id"], offering["id"], qty=4, teacher_id=teacher["id"])
    submit_order(api, first["id"], teacher["id"])
    assert read_title(api, title["id"])["license_status"] == "SUSPENDED", "360 > 270"

    validate_success(api.cancel_class_order(first["id"], make_teacher_headers(teacher["id"])))
    restored = read_title(api, title["id"])
    assert restored["royalty_accrued_cents"] == 0
    assert restored["license_status"] == "ACTIVE"

    second = create_order(api, cycle["id"], teacher["id"])
    add_line(api, second["id"], offering["id"], qty=3, teacher_id=teacher["id"])
    submit_order(api, second["id"], teacher["id"])
    final = read_title(api, title["id"])
    assert final["royalty_accrued_cents"] == 270, "re-accrual starts from zero"
    assert final["license_status"] == "ACTIVE", "270 lands exactly on the cap"
