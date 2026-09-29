"""One stored profile scored by each of the two priority-for-services pathways."""

from prd_bench_local_runner.testing import validate_success

from test_helpers import fixtures
from test_helpers.assertions import (
    assert_assessment_components,
    assert_int_equals,
    assert_pfs_triple,
)
from test_helpers.constants import (
    PFS_VARIANT_INTERRUPTION_WEIGHTED,
    PFS_VARIANT_OSY_PATHWAY,
    SCHOOLING_OUT_OF_SCHOOL,
)
from test_helpers.test_users import make_coordinator_headers, make_recruiter_headers

STUDENT = {
    "full_name": "Luz Ibarra",
    "birth_date": "2009-04-12",
    "grade_level": 10,
    "school_days_interrupted": 10,
    "math_below_grade": True,
    "reading_below_grade": True,
    "credit_deficit": 2,
    "has_hs_credential": False,
    "primary_language_not_english": False,
}


def _scored_child(client):
    """A child with one VERIFIED move whose ENROLLED profile scores exactly 60."""
    base = fixtures.area_and_recruiter(
        client,
        area_overrides={"name": "Skagit Delta"},
        recruiter_overrides={"full_name": "Ana Delgado"},
    )
    recruiter_id = base.recruiter["id"]
    student = fixtures.create_student(client, recruiter_id, base.area["id"], **STUDENT)
    move = fixtures.verified_move(
        client,
        recruiter_id,
        student["id"],
        from_state_code="OR",
        distance_miles=310.00,
    )
    base.recruiter_id = recruiter_id
    base.student = student
    base.move = move
    return base


def test_enrolled_profile_scores_under_the_interruption_weighted_pathway(client):
    """The ENROLLED pathway consumes the placement flags and the credit deficit.

    "This pathway consults neither the high-school credential nor the home-language
    flag, so `credential_points` and `language_points` are both 0."

    Design: Difficulty/dual_variant_calc/pfs_score_diverges_between_interruption_weighted_and_osy_pathway
    """
    bundle = _scored_child(client)

    assessment = validate_success(
        client.get_pfs_assessment(bundle.student["id"], make_coordinator_headers()), 200
    )

    assert_assessment_components(
        assessment,
        pfs_variant=PFS_VARIANT_INTERRUPTION_WEIGHTED,
        recent_verified_moves=1,
        move_band_points=18,
        interruption_points=8,
        academic_points=28,
        credit_points=6,
        credential_points=0,
        language_points=0,
        raw_score=60,
        pfs_score=60,
        pfs_flag=True,
        floor_applied=False,
    )

    stored = fixtures.read_student(client, bundle.student["id"])
    assert_pfs_triple(stored, PFS_VARIANT_INTERRUPTION_WEIGHTED, 60, True)


def test_flipping_schooling_status_reweights_the_same_profile_and_drops_the_flag(client):
    """The OSY pathway re-weights the identical stored profile and lowers the flag.

    "The consequence is that one stored profile scores differently under the two
    pathways, and flipping `schooling_status` on an existing child can move `pfs_flag`
    in either direction."

    Design: Difficulty/dual_variant_calc/pfs_score_diverges_between_interruption_weighted_and_osy_pathway
    """
    bundle = _scored_child(client)

    amended = validate_success(
        client.patch_student(
            bundle.student["id"],
            {"schooling_status": SCHOOLING_OUT_OF_SCHOOL, "grade_level": None},
            make_recruiter_headers(bundle.recruiter_id),
        ),
        200,
    )

    assert_pfs_triple(amended, PFS_VARIANT_OSY_PATHWAY, 55, False)

    assessment = validate_success(
        client.get_pfs_assessment(bundle.student["id"], make_coordinator_headers()), 200
    )
    assert_assessment_components(
        assessment,
        pfs_variant=PFS_VARIANT_OSY_PATHWAY,
        recent_verified_moves=1,
        move_band_points=18,
        interruption_points=12,
        credential_points=20,
        language_points=0,
        academic_points=0,
        credit_points=0,
        raw_score=50,
        pfs_score=55,
        pfs_flag=False,
        floor_applied=True,
    )

    # The stored inputs the OSY pathway ignores are untouched by the re-scoring.
    assert_int_equals(amended["math_below_grade"], True, "student.math_below_grade")
    assert_int_equals(amended["reading_below_grade"], True, "student.reading_below_grade")
    assert_int_equals(amended["credit_deficit"], 2, "student.credit_deficit")
