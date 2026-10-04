"""Validation rules: format and grade-band gates, promotion windows and
shapes, enrollment exclusivity, and submit non-emptiness.
"""

from prd_bench_local_runner.testing import validate_error, validate_success

from test_helpers import (
    add_offering,
    create_cycle,
    create_school,
    create_teacher,
    create_title,
    enroll_school,
    make_teacher_headers,
    publish_cycle,
    TEST_USERS,
)

CLUB_ADMIN = TEST_USERS["club_admin_headers"]


def _school(api, name, enroll=True):
    school = create_school(api, name=name, low_income_program=False)
    if enroll:
        enroll_school(api, school["id"])
    return school


def test_hardcover_titles_cannot_appear_on_club_flyers(api):
    """Only PAPERBACK and CLUB_PAPERBACK may be offered.

    PRD: "only `PAPERBACK` and `CLUB_PAPERBACK` titles may appear on club
    flyers, so a `HARDCOVER` title is rejected with `ERR_FORMAT_NOT_ALLOWED`
    (HTTP 422)"

    Design: Corner/validations/offering_rejects_hardcover_format
    """
    school = _school(api, "Format School")
    hardcover = create_title(api, name="Hardcover Title", format="HARDCOVER",
                             base_price_cents=2500, points_cost=25)
    cycle = create_cycle(api, school["id"], month="2026-10", grade_band="G3_5")

    rejected = api.add_offering(cycle["id"], {"title_id": hardcover["id"]}, CLUB_ADMIN)
    validate_error(rejected, "ERR_FORMAT_NOT_ALLOWED", 422)

    paperback = create_title(api, name="Paperback Title", format="PAPERBACK")
    accepted = validate_success(api.add_offering(cycle["id"], {"title_id": paperback["id"]}, CLUB_ADMIN), 201)
    assert accepted["cycle_id"] == cycle["id"]


def test_offering_rejects_a_title_of_the_wrong_grade_band(api):
    """A K_2 title cannot be offered on a G3_5 cycle.

    PRD: "the title's `grade_band` must equal the cycle's `grade_band`
    (otherwise `ERR_GRADE_BAND_MISMATCH`, HTTP 422)"

    Design: Corner/validations/offering_rejects_grade_band_mismatch
    """
    school = _school(api, "Band School")
    k2_title = create_title(api, name="K2 Title", grade_band="K_2", base_price_cents=800,
                            points_cost=8)
    cycle = create_cycle(api, school["id"], month="2026-10", grade_band="G3_5")

    rejected = api.add_offering(cycle["id"], {"title_id": k2_title["id"]}, CLUB_ADMIN)
    validate_error(rejected, "ERR_GRADE_BAND_MISMATCH", 422)


def test_class_order_rejects_a_teacher_of_the_wrong_grade_band(api):
    """A G6_8 teacher cannot open an order on a K_2 cycle.

    PRD: "The order's teacher must teach at the cycle's school and their
    `grade_band` must equal the cycle's `grade_band`, else the creation is
    rejected with `ERR_GRADE_BAND_MISMATCH`"

    Design: Corner/validations/class_order_rejects_teacher_band_mismatch
    """
    school = _school(api, "Teacher Band School")
    teacher = create_teacher(api, school["id"], grade_band="G6_8", full_name="G6_8 Teacher")
    k2_title = create_title(api, name="K2 Order Title", grade_band="K_2", base_price_cents=800,
                            points_cost=8)
    cycle = create_cycle(api, school["id"], month="2026-10", grade_band="K_2")
    add_offering(api, cycle["id"], k2_title["id"])
    publish_cycle(api, cycle["id"])

    rejected = api.create_class_order(
        {"cycle_id": cycle["id"], "teacher_id": teacher["id"]},
        make_teacher_headers(teacher["id"]),
    )
    validate_error(rejected, "ERR_GRADE_BAND_MISMATCH", 422)


def test_promotion_window_must_extend_forward(api):
    """ends_on at or before starts_on is rejected.

    PRD: "The `ends_on` must be strictly after `starts_on`, and creating a
    promotion whose window already lies wholly in the past — `ends_on` on or
    before the current logical clock date — is rejected with
    `ERR_PROMO_WINDOW_INVALID` (HTTP 422)."

    Design: Corner/validations/promo_window_inverted_rejected
    """
    inverted = api.create_promotion(
        {
            "name": "Inverted Window",
            "kind": "BONUS_POINTS",
            "multiplier_bp": 200,
            "starts_on": "2026-11-01",
            "ends_on": "2026-10-01",
        },
        CLUB_ADMIN,
    )
    validate_error(inverted, "ERR_PROMO_WINDOW_INVALID", 422)

    # At the startup clock of 2026-09-01 a window that already ended is past.
    past = api.create_promotion(
        {
            "name": "Wholly Past",
            "kind": "BONUS_POINTS",
            "multiplier_bp": 200,
            "starts_on": "2026-07-01",
            "ends_on": "2026-08-01",
        },
        CLUB_ADMIN,
    )
    validate_error(past, "ERR_PROMO_WINDOW_INVALID", 422)


def test_promotion_shape_pairs_kind_with_its_fields(api):
    """BONUS_POINTS forbids title_id; TITLE_INCENTIVE requires one.

    PRD: "A `BONUS_POINTS` promotion applies a class-value multiplier and
    requires `multiplier_bp`, the bonus multiplier in basis points, which must
    be at least 100 (100 basis points is the neutral base; 200 means double
    earn) — and its `title_id` must be null. A `TITLE_INCENTIVE` promotion
    applies a flat per-unit bonus to one title and requires a non-null
    `title_id` and a `bonus_points_per_unit` value of at least zero. A
    promotion whose kind-field combination violates these shapes is rejected
    with `ERR_PROMO_SHAPE_INVALID` (HTTP 422)."

    Design: Corner/validations/promo_shape_multiplier_requires_no_title
    """
    title = create_title(api, name="Shape Title")

    bonus_with_title = api.create_promotion(
        {
            "name": "Bad Bonus Shape",
            "kind": "BONUS_POINTS",
            "title_id": title["id"],
            "multiplier_bp": 200,
            "starts_on": "2026-10-01",
            "ends_on": "2026-11-01",
        },
        CLUB_ADMIN,
    )
    validate_error(bonus_with_title, "ERR_PROMO_SHAPE_INVALID", 422)

    incentive_without_title = api.create_promotion(
        {
            "name": "Bad Incentive Shape",
            "kind": "TITLE_INCENTIVE",
            "bonus_points_per_unit": 3,
            "starts_on": "2026-10-01",
            "ends_on": "2026-11-01",
        },
        CLUB_ADMIN,
    )
    validate_error(incentive_without_title, "ERR_PROMO_SHAPE_INVALID", 422)

    bonus_below_base = api.create_promotion(
        {
            "name": "Below Neutral",
            "kind": "BONUS_POINTS",
            "multiplier_bp": 50,
            "starts_on": "2026-10-01",
            "ends_on": "2026-11-01",
        },
        CLUB_ADMIN,
    )
    validate_error(bonus_below_base, "ERR_PROMO_SHAPE_INVALID", 422)


def test_submitting_an_empty_order_is_rejected(api):
    """At least one non-CANCELLED line is required to submit.

    PRD: "and at least one line must exist with a status other than
    `CANCELLED` (else `ERR_ORDER_EMPTY`, HTTP 422)."

    Design: Corner/validations/submit_empty_order_rejected
    """
    school = _school(api, "Empty Order School")
    teacher = create_teacher(api, school["id"], grade_band="G3_5", full_name="Empty Teacher")
    title = create_title(api, name="Empty Order Title")
    cycle = create_cycle(api, school["id"], month="2026-10", grade_band="G3_5")
    add_offering(api, cycle["id"], title["id"])
    publish_cycle(api, cycle["id"])

    headers = make_teacher_headers(teacher["id"])
    order = validate_success(
        api.create_class_order({"cycle_id": cycle["id"], "teacher_id": teacher["id"]}, headers),
        201,
    )
    rejected = api.submit_class_order(
        order["id"], {"expected_class_order_version": order["version"]}, headers
    )
    validate_error(rejected, "ERR_ORDER_EMPTY", 422)


def test_a_school_holds_at_most_one_active_enrollment(api):
    """A second ACTIVE enrollment is rejected.

    PRD: "a school may hold at most one `ACTIVE` enrollment at a time, and an
    attempt to enroll a school that already has one is rejected with
    `ERR_ENROLLMENT_EXISTS` (HTTP 409)."

    Design: Corner/validations/enroll_second_active_enrollment_rejected
    """
    school = _school(api, "Double Enroll School")
    rejected = api.enroll_program(school["id"], {"enrolled_on": "2026-09-01"}, CLUB_ADMIN)
    validate_error(rejected, "ERR_ENROLLMENT_EXISTS", 409)
