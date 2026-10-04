"""Reward-point economics: the earning base, fair-overlap exclusion, and the
promotion combination rules (best multiplier plus stacking title incentives).
"""

from prd_bench_local_runner.testing import validate_error, validate_paginated, validate_success

from test_helpers import (
    add_line,
    add_offering,
    create_book_fair,
    create_cycle,
    create_order,
    create_promotion,
    create_school,
    create_teacher,
    create_title,
    enroll_school,
    make_teacher_headers,
    publish_cycle,
    read_order,
    read_teacher,
    set_clock,
    submit_order,
    TEST_USERS,
)

CLUB_ADMIN = TEST_USERS["club_admin_headers"]
SCHOOL_ADMIN = TEST_USERS["school_admin_headers"]


def _school_with_teacher(api, name):
    school = create_school(api, name=name, low_income_program=False)
    enroll_school(api, school["id"])
    teacher = create_teacher(api, school["id"], grade_band="G3_5", full_name=f"{name} Teacher")
    return school, teacher


def test_fair_overlap_lines_are_excluded_from_the_earning_base(api):
    """A line whose offering overlaps a school book fair earns nothing.

    PRD: "The `rewardable_subtotal_cents` is the same sum but restricted to
    lines whose `fair_overlap` is false and whose `donation_funded` is false —
    it is the earning base for reward points."
    PRD: "Step one derives base points from the earning base: the base is the
    `rewardable_subtotal_cents` divided by 100 cents per point and floored to
    an integer — 100 cents of rewardable spend earns one point."

    Design: Difficulty/dual_variant_calc/reward_points_award_excludes_fair_overlap_lines
    """
    school, teacher = _school_with_teacher(api, "Overlap School")
    bt1 = create_title(api, name="Fair Free Book", base_price_cents=1500, points_cost=15)
    bt2 = create_title(api, name="Fair Featured Book", base_price_cents=2000, points_cost=20)

    fair = create_book_fair(api, school["id"], start_date="2026-10-05", end_date="2026-10-09")
    api.add_fair_title(fair["id"], {"title_id": bt2["id"]}, SCHOOL_ADMIN)

    cycle = create_cycle(api, school["id"], month="2026-10", grade_band="G3_5")
    o1 = add_offering(api, cycle["id"], bt1["id"])
    o2 = add_offering(api, cycle["id"], bt2["id"])
    publish_cycle(api, cycle["id"])

    offering2 = validate_success(api.get_offering(o2["id"], CLUB_ADMIN))
    assert offering2["fair_overlap"] is True, (
        "offering of the fair-featured title must recompute to fair_overlap true at publication"
    )

    order = create_order(api, cycle["id"], teacher["id"])
    add_line(api, order["id"], o1["id"], qty=1, teacher_id=teacher["id"])
    add_line(api, order["id"], o2["id"], qty=1, teacher_id=teacher["id"])

    submitted = submit_order(api, order["id"], teacher["id"])
    assert submitted["status"] == "SUBMITTED"
    assert submitted["subtotal_cents"] == 3500
    assert submitted["rewardable_subtotal_cents"] == 1500, (
        "the fair-overlap line must be excluded from the earning base"
    )
    assert submitted["awarded_base_points"] == 15
    assert submitted["awarded_bonus_points"] == 0
    assert submitted["awarded_total_points"] == 15

    teacher_after = read_teacher(api, teacher["id"])
    assert teacher_after["points_balance"] == 15, (
        "the teacher earns 15 points, not 35 — the fair-overlap line earns nothing"
    )
    assert teacher_after["points_earned_total"] == 15


def test_line_level_attribution_assigns_points_only_to_qualifying_lines(api):
    """Each line's points_earned attribution excludes fair-overlap lines.

    PRD: "Each line also carries its own `points_earned` attribution: the
    line's rewardable value (its `qty` times `unit_price_cents`, for qualifying
    lines) divided by 100 cents per point and floored, with the order-level
    remainder — the difference between the floored order base and the sum of
    floored line attributions — given to the earliest-created qualifying line,
    ties broken by `student_name` in ascending order."
    PRD: "The `rewardable_subtotal_cents` is the same sum but restricted to
    lines whose `fair_overlap` is false and whose `donation_funded` is false —
    it is the earning base for reward points."

    Design: Difficulty/dual_variant_calc/reward_points_award_excludes_fair_overlap_lines
    """
    school, teacher = _school_with_teacher(api, "Attribution School")
    bt1 = create_title(api, name="Rewardable Book", base_price_cents=1500, points_cost=15)
    bt2 = create_title(api, name="Fair Only Book", base_price_cents=2000, points_cost=20)

    fair = create_book_fair(api, school["id"], start_date="2026-10-05", end_date="2026-10-09")
    api.add_fair_title(fair["id"], {"title_id": bt2["id"]}, SCHOOL_ADMIN)

    cycle = create_cycle(api, school["id"], month="2026-10", grade_band="G3_5")
    o1 = add_offering(api, cycle["id"], bt1["id"])
    o2 = add_offering(api, cycle["id"], bt2["id"])
    publish_cycle(api, cycle["id"])

    order = create_order(api, cycle["id"], teacher["id"])
    good_line = add_line(api, order["id"], o1["id"], qty=1, teacher_id=teacher["id"])
    fair_line = add_line(api, order["id"], o2["id"], qty=2, teacher_id=teacher["id"])

    submitted = submit_order(api, order["id"], teacher["id"])
    assert submitted["subtotal_cents"] == 5500
    assert submitted["rewardable_subtotal_cents"] == 1500
    # Whole-subtotal tier discount: 5500 * 500bp / 10000 = 275, rounded once.
    assert submitted["discount_cents"] == 275
    assert submitted["awarded_base_points"] == 15
    assert submitted["awarded_total_points"] == 15

    lines, _meta = validate_paginated(
        api.list_order_lines(order["id"], make_teacher_headers(teacher["id"]))
    )
    by_id = {line["id"]: line for line in lines}
    assert by_id[good_line["id"]]["points_earned"] == 15, (
        "the sole qualifying line carries the full base attribution"
    )
    assert by_id[fair_line["id"]]["points_earned"] == 0, (
        "a fair-overlap line is not qualifying and earns nothing"
    )


def _setup_promotion_order(api):
    """School, teacher, title, and an October-published cycle; returns the world."""
    school, teacher = _school_with_teacher(api, "Promo School")
    title = create_title(api, name="Incentive Title", base_price_cents=1500, points_cost=15)
    cycle = create_cycle(api, school["id"], month="2026-10", grade_band="G3_5")
    offering = add_offering(api, cycle["id"], title["id"])
    publish_cycle(api, cycle["id"])
    return {
        "school": school,
        "teacher": teacher,
        "title": title,
        "cycle": cycle,
        "offering": offering,
    }


def test_best_multiplier_stacks_with_two_title_incentives(api):
    """One best multiplier plus two stacking incentives on the same title.

    PRD: "the `BONUS_POINTS` promotions contribute a single best multiplier —
    the highest `multiplier_bp`, with ties broken by the earliest promotion
    `created_at` and then by `name` in ascending order. The multiplier bonus is
    the base multiplied by the best multiplier's excess over 100 basis points,
    divided by 100, and floored: at double earn (200 basis points), the
    multiplier bonus equals the base itself."
    PRD: "Independently, each `TITLE_INCENTIVE` promotion contributes its
    `bonus_points_per_unit` times the ordered quantity of its title across the
    order's qualifying lines — those not cancelled, not fair-overlapped, and
    not donation-funded — and multiple incentive promotions on the same title
    stack additively."

    Design: Difficulty/combinatorial_formula/reward_points_promo_multiplier_plus_stacked_incentives
    """
    world = _setup_promotion_order(api)
    create_promotion(api, name="Double October", kind="BONUS_POINTS", multiplier_bp=200)
    create_promotion(
        api,
        name="Incentive Plus Three",
        kind="TITLE_INCENTIVE",
        title_id=world["title"]["id"],
        bonus_points_per_unit=3,
    )
    create_promotion(
        api,
        name="Incentive Plus Two",
        kind="TITLE_INCENTIVE",
        title_id=world["title"]["id"],
        bonus_points_per_unit=2,
    )

    order = create_order(api, world["cycle"]["id"], world["teacher"]["id"])
    add_line(api, order["id"], world["offering"]["id"], qty=2, teacher_id=world["teacher"]["id"])
    set_clock(api, "2026-10-10T12:00:00Z")

    submitted = submit_order(api, order["id"], world["teacher"]["id"])
    assert submitted["awarded_base_points"] == 30, "base is floor(3000/100)"
    # Multiplier bonus floor(30 * (200-100)/100) = 30; incentives 2*(3+2) = 10.
    assert submitted["awarded_bonus_points"] == 40
    assert submitted["awarded_total_points"] == 70

    teacher_after = read_teacher(api, world["teacher"]["id"])
    assert teacher_after["points_balance"] == 70
    assert teacher_after["points_earned_total"] == 70


def test_highest_multiplier_wins_and_band_scoped_promotions_do_not_apply(api):
    """The single highest multiplier applies; other bands' promotions do not.

    PRD: "Step two scans promotions: among promotions that are `ACTIVE`, whose
    `[starts_on, ends_on)` window contains the logical clock date, and whose
    `grade_band` is either null or equal to the ordering teacher's band, the
    `BONUS_POINTS` promotions contribute a single best multiplier — the highest
    `multiplier_bp`, with ties broken by the earliest promotion `created_at`
    and then by `name` in ascending order."
    PRD: "An optional `grade_band` scopes the promotion to one band; a null
    `grade_band` means the promotion applies to all bands."

    Design: Difficulty/combinatorial_formula/reward_points_promo_multiplier_plus_stacked_incentives
    """
    world = _setup_promotion_order(api)
    # A larger multiplier scoped away to another band must not apply.
    create_promotion(
        api, name="Triple For G6_8", kind="BONUS_POINTS", multiplier_bp=300, grade_band="G6_8"
    )
    # The best applicable multiplier is 150 for this G3_5 teacher.
    create_promotion(api, name="Half Again", kind="BONUS_POINTS", multiplier_bp=150)

    order = create_order(api, world["cycle"]["id"], world["teacher"]["id"])
    add_line(api, order["id"], world["offering"]["id"], qty=2, teacher_id=world["teacher"]["id"])
    set_clock(api, "2026-10-10T12:00:00Z")

    submitted = submit_order(api, order["id"], world["teacher"]["id"])
    assert submitted["awarded_base_points"] == 30
    # Bonus uses the best APPLICABLE multiplier: floor(30 * (150-100)/100) = 15.
    assert submitted["awarded_bonus_points"] == 15
    assert submitted["awarded_total_points"] == 45

    teacher_after = read_teacher(api, world["teacher"]["id"])
    assert teacher_after["points_balance"] == 45
