"""Annual membership dues: the floor, the marginal per-student tier boundary,
the per-classroom surcharge, and the cap — three regimes of one formula.
"""

from test_helpers import (
    MAX_DUES_CENTS,
    MIN_DUES_CENTS,
    create_classroom,
    create_school,
    expected_annual_dues_cents,
    read_school,
    reset_clock,
    setup_member_school,
)


def test_dues_floor_and_marginal_tier_boundary(api):
    """PRD section 3.2: "an `AFFILIATE` school with zero students and one
    classroom raws to 48000 cents and pays the 60000-cent floor" and "an
    `AFFILIATE` with 100 students and one classroom pays 198000 cents, while a
    101st student — billed alone at the 1200-cent tier — brings the quote to
    199200 cents". PRD section 3.2: "The raw total is then floored at 60000
    cents before being capped at 1500000 cents; the floor applies before the
    cap."

    Design: Difficulty/combinatorial_formula/dues_marginal_tiers_floor_and_cap
    """
    reset_clock()
    # School F: APPLICANT (quotes the AFFILIATE schedule), 0 students, 1 room.
    floor_school = create_school(name="F School", display_name="F Schoolhouse")
    create_classroom(floor_school["id"], name="F1", enrolled_student_count=0)
    floor_dues = read_school(floor_school["id"])["annual_dues_cents"]
    assert floor_dues == MIN_DUES_CENTS, "raw 40000 + 0 + 8000 = 48000 lifted by the floor"
    assert floor_dues == expected_annual_dues_cents("APPLICANT", 0, 1)

    # School G: APPLICANT, 60 + 41 = 101 students across 2 rooms — the 101st
    # student bills marginally at 1200c, and both rooms surcharged.
    tier_school = create_school(name="G School", display_name="G Schoolhouse")
    create_classroom(tier_school["id"], name="G1", enrolled_student_count=60)
    create_classroom(tier_school["id"], name="G2", enrolled_student_count=41)
    tier_dues = read_school(tier_school["id"])["annual_dues_cents"]
    assert tier_dues == 207200, "40000 + 100x1500 + 1x1200 + 2x8000"
    assert tier_dues == expected_annual_dues_cents("APPLICANT", 101, 2)


def test_dues_cap_binds_for_large_member_school(api):
    """PRD section 3.2: "an `ACCREDITED` school with 1500 students and 20
    classrooms raws to 1780000 cents and pays the 1500000-cent cap" — the same
    cap binds this MEMBER school: raw 90000 + 1470000 + 8000 = 1568000 clipped
    to 1500000. PRD section 3.2: "90000 cents for `MEMBER`" base dues.

    Design: Difficulty/combinatorial_formula/dues_marginal_tiers_floor_and_cap
    """
    reset_clock()
    staged = setup_member_school(
        classroom_overrides={"enrolled_student_count": 1500, "assistant_count": 100}
    )
    school = read_school(staged.school["id"])
    assert school["membership_level"] == "MEMBER"
    assert school["total_enrollment"] == 1500
    assert school["annual_dues_cents"] == MAX_DUES_CENTS
    assert school["annual_dues_cents"] == expected_annual_dues_cents("MEMBER", 1500, 1)
