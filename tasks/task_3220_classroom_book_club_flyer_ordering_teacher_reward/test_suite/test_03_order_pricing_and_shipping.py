"""Order economics: the whole-subtotal tier discount rounded once, the
shipping fee resolution with its inclusive waiver boundary, and the low-income
school waiver.
"""

from prd_bench_local_runner.testing import validate_success

from test_helpers import (
    add_line,
    add_offering,
    create_cycle,
    create_order,
    create_school,
    create_teacher,
    create_title,
    enroll_school,
    publish_cycle,
    read_order,
    setup_open_order,
    TEST_USERS,
)

CLUB_ADMIN = TEST_USERS["club_admin_headers"]


def _school_with_teacher(api, name, low_income=False):
    school = create_school(api, name=name, low_income_program=low_income)
    enroll_school(api, school["id"])
    teacher = create_teacher(api, school["id"], grade_band="G3_5", full_name=f"{name} Teacher")
    return school, teacher


def test_whole_subtotal_discount_rounded_once_and_club_price_floor(api):
    """The discount applies to the aggregate, rounded once half-up.

    PRD: "The tier discount is computed on the whole subtotal, never per line.
    Four tiers apply, each with an inclusive lower bound on the subtotal: below
    5000 cents the discount rate is zero basis points; at or above 5000 cents
    the rate is 500 basis points (5.00%); at or above 15000 cents it is 1000
    basis points (10.00%); and at or above 40000 cents it is 1500 basis points
    (15.00%). The applicable tier is the highest tier whose inclusive minimum
    the subtotal has reached. The `discount_cents` is the subtotal multiplied
    by the applicable tier's basis points, divided by 10000, and rounded once,
    half-up, to whole cents. Computing per-line discounts, rounding each, and
    summing is expressly forbidden — it produces different cents at tier
    boundaries."
    PRD: "For a `CLUB_PAPERBACK` title the pinned price is the title's
    `base_price_cents` multiplied by 70 and divided by 100, floored to whole
    cents — the club edition is priced at 70% of list. For `PAPERBACK` (and any
    other offered format) the pinned price is simply the title's
    `base_price_cents`."

    Design: Difficulty/combinatorial_formula/tier_discount_whole_subtotal_single_rounding
    """
    school, teacher = _school_with_teacher(api, "Tier School")
    club_title = create_title(
        api, name="Club Edition", format="CLUB_PAPERBACK", base_price_cents=1000, points_cost=7
    )
    plain_title = create_title(api, name="Plain Paperback", base_price_cents=2100, points_cost=21)
    cycle = create_cycle(api, school["id"], month="2026-10", grade_band="G3_5")
    o1 = add_offering(api, cycle["id"], club_title["id"])
    o2 = add_offering(api, cycle["id"], plain_title["id"])
    publish_cycle(api, cycle["id"])

    assert validate_success(api.get_offering(o1["id"], CLUB_ADMIN))["flyer_price_cents"] == 700
    assert validate_success(api.get_offering(o2["id"], CLUB_ADMIN))["flyer_price_cents"] == 2100

    order = create_order(api, cycle["id"], teacher["id"])
    add_line(api, order["id"], o1["id"], qty=3, teacher_id=teacher["id"])
    add_line(api, order["id"], o2["id"], qty=2, teacher_id=teacher["id"])

    priced = read_order(api, order["id"], teacher["id"])
    assert priced["subtotal_cents"] == 6300, "3x700 + 2x2100"
    # Tier 1 applies (5000 <= 6300 < 15000): round_half_up(6300 * 500 / 10000) = 315.
    assert priced["discount_cents"] == 315
    assert priced["net_total_cents"] == 5985
    # Rewardable 6300 >= 2500, so the order-level waiver zeroes the fee.
    assert priced["shipping_fee_cents"] == 0


def test_highest_reached_tier_applies_at_the_inclusive_40000_boundary(api):
    """Tier 3 applies at exactly 40000 cents of subtotal.

    PRD: "at or above 40000 cents it is 1500 basis points (15.00%). The
    applicable tier is the highest tier whose inclusive minimum the subtotal
    has reached."
    PRD: "The tier discount is computed on the whole subtotal, never per line."

    Design: Difficulty/combinatorial_formula/tier_discount_whole_subtotal_single_rounding
    """
    school, teacher = _school_with_teacher(api, "Top Tier School")
    title = create_title(api, name="Bulk Title", base_price_cents=10000, points_cost=100)
    cycle = create_cycle(api, school["id"], month="2026-10", grade_band="G3_5")
    offering = add_offering(api, cycle["id"], title["id"])
    publish_cycle(api, cycle["id"])

    order = create_order(api, cycle["id"], teacher["id"])
    add_line(api, order["id"], offering["id"], qty=4, teacher_id=teacher["id"])

    priced = read_order(api, order["id"], teacher["id"])
    assert priced["subtotal_cents"] == 40000
    # Tier 3: round_half_up(40000 * 1500 / 10000) = 6000.
    assert priced["discount_cents"] == 6000
    assert priced["net_total_cents"] == 34000
    assert priced["shipping_fee_cents"] == 0


def test_free_shipping_boundary_below_threshold_charges_flat_fee(api):
    """A rewardable subtotal just below 2500 cents pays the 750-cent fee.

    PRD: "Shipping resolves to a flat 750 cents, with two independent waivers,
    each yielding a fee of zero. The school-level waiver applies whenever the
    school's `low_income_program` flag is true. The order-level waiver applies
    whenever the order's `rewardable_subtotal_cents` is at least 2500 cents —
    the boundary is inclusive, so a rewardable subtotal of exactly 2500 cents
    ships free. If neither waiver applies, `shipping_fee_cents` is the 750-cent
    flat fee."

    Design: Difficulty/boundary_precision_check/free_shipping_threshold_inclusive_at_2500
    """
    school, teacher = _school_with_teacher(api, "Below Threshold School")
    t1 = create_title(api, name="Priced 1249", base_price_cents=1249, points_cost=12)
    cycle = create_cycle(api, school["id"], month="2026-10", grade_band="G3_5")
    offering = add_offering(api, cycle["id"], t1["id"])
    publish_cycle(api, cycle["id"])

    order = create_order(api, cycle["id"], teacher["id"])
    add_line(api, order["id"], offering["id"], qty=2, teacher_id=teacher["id"])

    priced = read_order(api, order["id"], teacher["id"])
    assert priced["rewardable_subtotal_cents"] == 2498
    assert priced["shipping_fee_cents"] == 750, "2498 is below the inclusive 2500 threshold"


def test_free_shipping_boundary_at_exactly_2500_ships_free(api):
    """A rewardable subtotal of exactly 2500 cents ships free.

    PRD: "The order-level waiver applies whenever the order's
    `rewardable_subtotal_cents` is at least 2500 cents — the boundary is
    inclusive, so a rewardable subtotal of exactly 2500 cents ships free."
    PRD: "Shipping resolves to a flat 750 cents, with two independent waivers,
    each yielding a fee of zero."

    Design: Difficulty/boundary_precision_check/free_shipping_threshold_inclusive_at_2500
    """
    school, teacher = _school_with_teacher(api, "At Threshold School")
    t1 = create_title(api, name="Priced 1249", base_price_cents=1249, points_cost=12)
    t2 = create_title(api, name="Priced 1251", base_price_cents=1251, points_cost=12)
    cycle = create_cycle(api, school["id"], month="2026-10", grade_band="G3_5")
    o1 = add_offering(api, cycle["id"], t1["id"])
    o2 = add_offering(api, cycle["id"], t2["id"])
    publish_cycle(api, cycle["id"])

    order = create_order(api, cycle["id"], teacher["id"])
    add_line(api, order["id"], o1["id"], qty=1, teacher_id=teacher["id"])
    add_line(api, order["id"], o2["id"], qty=1, teacher_id=teacher["id"])

    priced = read_order(api, order["id"], teacher["id"])
    assert priced["rewardable_subtotal_cents"] == 2500
    assert priced["shipping_fee_cents"] == 0, "exactly 2500 meets the inclusive threshold"


def test_tier_two_applies_at_exactly_15000(api):
    """A subtotal of exactly 15000 takes tier 2's 1000 basis points.

    PRD: "at or above 15000 cents it is 1000 basis points (10.00%); and at or
    above 40000 cents it is 1500 basis points (15.00%). The applicable tier is
    the highest tier whose inclusive minimum the subtotal has reached."
    PRD: "The `net_total_cents` charged to families is the `subtotal_cents`
    minus the `discount_cents`."

    Design: Corner/calculations/tier_boundary_at_15000_applies_1000bp
    """
    school, teacher = _school_with_teacher(api, "Tier Two School")
    title = create_title(api, name="Priced 5000", base_price_cents=5000, points_cost=50)
    cycle = create_cycle(api, school["id"], month="2026-10", grade_band="G3_5")
    offering = add_offering(api, cycle["id"], title["id"])
    publish_cycle(api, cycle["id"])

    order = create_order(api, cycle["id"], teacher["id"])
    add_line(api, order["id"], offering["id"], qty=3, teacher_id=teacher["id"])

    priced = read_order(api, order["id"], teacher["id"])
    assert priced["subtotal_cents"] == 15000
    assert priced["discount_cents"] == 1500, "tier 2 at exactly 15000, inclusive"
    assert priced["net_total_cents"] == 13500


def test_low_income_school_waives_shipping_regardless_of_subtotal(api):
    """A low-income school's small order ships free under the 2500 threshold.

    PRD: "Shipping resolves to a flat 750 cents, with two independent waivers,
    each yielding a fee of zero. The school-level waiver applies whenever the
    school's `low_income_program` flag is true."

    Design: Corner/cross_cutting_layers/low_income_school_waives_shipping_regardless_of_subtotal
    """
    school, teacher = _school_with_teacher(api, "Low Income School", low_income=True)
    title = create_title(api, name="Small Book", base_price_cents=500, points_cost=5)
    cycle = create_cycle(api, school["id"], month="2026-10", grade_band="G3_5")
    offering = add_offering(api, cycle["id"], title["id"])
    publish_cycle(api, cycle["id"])

    order = create_order(api, cycle["id"], teacher["id"])
    add_line(api, order["id"], offering["id"], qty=1, teacher_id=teacher["id"])

    priced = read_order(api, order["id"], teacher["id"])
    assert priced["rewardable_subtotal_cents"] == 500
    assert priced["shipping_fee_cents"] == 0, (
        "the school-level waiver zeroes the fee even below the order-level threshold"
    )


def test_deleting_the_only_line_zeroes_aggregates_and_restores_flat_fee(api):
    """Line cancellation recomputes every order aggregate back to zero.

    PRD: "Every line creation, quantity change, or cancellation recomputes all
    of the parent order's aggregates — `subtotal_cents`,
    `rewardable_subtotal_cents`, `discount_cents`, `net_total_cents`,
    `shipping_fee_cents`, and the awarded-points previews — refreshes the
    order's `updated_at`, and increments the order's `version`."
    PRD: "If neither waiver applies, `shipping_fee_cents` is the 750-cent flat
    fee."

    Design: Corner/cross_cutting_layers/cascading_aggregates_recompute_on_line_delete
    """
    world = setup_open_order(
        api,
        line_specs=[{"offering_index": 0, "qty": 1}],
        school_name="Recompute School",
        title_overrides=[{"base_price_cents": 3000, "points_cost": 30}],
    )
    order = world["order"]
    line = world["lines"][0]

    before = read_order(api, order["id"], world["teacher"]["id"])
    assert before["subtotal_cents"] == 3000
    assert before["shipping_fee_cents"] == 0, "rewardable 3000 meets the waiver threshold"

    deleted = validate_success(
        api.delete_order_line(line["id"], world["teacher_headers"])
    )
    assert deleted["status"] == "CANCELLED"

    after = read_order(api, order["id"], world["teacher"]["id"])
    assert after["subtotal_cents"] == 0
    assert after["rewardable_subtotal_cents"] == 0
    assert after["discount_cents"] == 0
    assert after["net_total_cents"] == 0
    assert after["shipping_fee_cents"] == 750, "the flat fee returns once no waiver applies"
    assert after["awarded_base_points"] == 0
    assert after["awarded_total_points"] == 0
    assert after["version"] > before["version"], "the cancellation bumps the order's version"
