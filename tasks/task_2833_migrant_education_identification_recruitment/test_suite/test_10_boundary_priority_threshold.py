"""The priority flag is tested one point below and exactly at its inclusive threshold."""

from prd_bench_local_runner.testing import validate_success

from test_helpers import fixtures
from test_helpers.assertions import (
    assert_assessment_components,
    assert_pfs_triple,
)
from test_helpers.constants import PFS_VARIANT_INTERRUPTION_WEIGHTED
from test_helpers.test_users import make_coordinator_headers

NEAR_THRESHOLD = {
    "school_days_interrupted": 5,
    "math_below_grade": True,
    "reading_below_grade": True,
    "credit_deficit": 3,
}


def _child_scoring_fifty_nine(client):
    """A child whose ENROLLED components add to exactly 59, one point below the threshold."""
    base = fixtures.area_and_recruiter(client)
    student = fixtures.create_student(
        client, base.recruiter["id"], base.area["id"], **NEAR_THRESHOLD
    )
    fixtures.verified_move(client, base.recruiter["id"], student["id"])
    base.student = student
    return base


def test_a_score_of_fifty_nine_leaves_the_priority_flag_down(client):
    """One point short of the threshold the flag must still read false.

    "Three fields hold it: `pfs_score`, a whole number from 0 through 100;
    `pfs_variant`, recording which of the two scoring pathways produced it, either
    `INTERRUPTION_WEIGHTED` or `OSY_PATHWAY`; and `pfs_flag`, true exactly when
    `pfs_score` is 60 or greater - the threshold is inclusive, so a score of exactly 60
    raises the flag."

    Design: Difficulty/boundary_precision_check/pfs_flag_is_inclusive_at_exactly_the_60_point_threshold
    """
    bundle = _child_scoring_fifty_nine(client)

    assessment = validate_success(
        client.get_pfs_assessment(bundle.student["id"], make_coordinator_headers()), 200
    )
    assert_assessment_components(
        assessment,
        pfs_variant=PFS_VARIANT_INTERRUPTION_WEIGHTED,
        recent_verified_moves=1,
        move_band_points=18,
        interruption_points=4,
        academic_points=28,
        credit_points=9,
        credential_points=0,
        language_points=0,
        raw_score=59,
        pfs_score=59,
        pfs_flag=False,
    )

    stored = fixtures.read_student(client, bundle.student["id"])
    assert_pfs_triple(stored, PFS_VARIANT_INTERRUPTION_WEIGHTED, 59, False)


def test_a_score_of_exactly_sixty_raises_the_priority_flag(client):
    """Amending the profile to land on exactly 60 raises the flag on the inclusive edge.

    "Every accepted amendment recomputes and persists `pfs_score`, `pfs_variant` and
    `pfs_flag`; when - and only when - `pfs_flag` actually changed value, the
    hour-allocation rule of 3.9 is re-run across the child's plans in `DRAFT` or `ACTIVE`
    status, because the budget those plans divide depends on the flag."

    Design: Difficulty/boundary_precision_check/pfs_flag_is_inclusive_at_exactly_the_60_point_threshold
    """
    bundle = _child_scoring_fifty_nine(client)

    amended = validate_success(
        client.patch_student(
            bundle.student["id"],
            {"school_days_interrupted": 10, "credit_deficit": 2},
            make_coordinator_headers(),
        ),
        200,
    )

    assert_pfs_triple(amended, PFS_VARIANT_INTERRUPTION_WEIGHTED, 60, True)

    assessment = validate_success(
        client.get_pfs_assessment(bundle.student["id"], make_coordinator_headers()), 200
    )
    assert_assessment_components(
        assessment,
        pfs_variant=PFS_VARIANT_INTERRUPTION_WEIGHTED,
        move_band_points=18,
        interruption_points=8,
        academic_points=28,
        credit_points=6,
        raw_score=60,
        pfs_score=60,
        pfs_flag=True,
        floor_applied=False,
    )
