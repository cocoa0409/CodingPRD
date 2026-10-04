"""Placement calibration: the session-graded boundary anchor and its band."""
from test_helpers import (
    api_client, get_success_data, placement_action_payload,
    scene_placement_ready,
)


def test_self_serve_calibration_caps_at_completed_unit_and_follows_its_band(api):
    """PRD §3.6: "For a self-serve session the ceiling is the largest `unit_index`
    among units the learner has already `COMPLETED`"
    PRD §3.6: "when the ceiling falls short of the provisional index the learner is
    placed at the ceiling and the calibrated band becomes that ceiling unit's own
    `cefr_band` instead"
    PRD §3.6: "identical sub-scores of 200 with 20 items place a self-serve learner
    at unit 1"

    Design: Difficulty/dual_variant_calc/placement_hard_cap_anchor_by_session_grade
    """
    scene = scene_placement_ready(
        unit1_band="A1", unit1_nodes=1, unit2_band="B1", total_items=20,
        complete_unit1=True, progress_unit2=False, scored=True,
        comprehension_score=200, accuracy_score=0,
    )
    placement = get_success_data(api_client.update_placement_test(
        scene["placement"]["id"], placement_action_payload("CALIBRATE"),
        scene["headers"],
    ))

    assert placement["placed_unit_index"] == 1, (
        "only unit 1 is COMPLETED, so the self-serve ceiling is 1 and the "
        f"provisional index of 6 is clamped to it, got "
        f"{placement['placed_unit_index']}"
    )
    assert placement["calibrated_cefr_band"] == "A1", (
        "the calibrated band becomes the ceiling unit's own cefr_band, so unit "
        f"1's A1, got {placement['calibrated_cefr_band']}"
    )
    assert placement["status"] == "CALIBRATED"


def test_institution_graded_calibration_counts_in_progress_units(api):
    """PRD §3.6: "for an institution-graded session the ceiling is the largest
    `unit_index` among units in `COMPLETED` or `IN_PROGRESS`"
    PRD §3.6: "identical sub-scores of 200 with 20 items place a self-serve learner
    at unit 1 but an institution-graded learner at unit 2, with the band following
    the unit"

    Design: Difficulty/dual_variant_calc/placement_hard_cap_anchor_by_session_grade
    """
    scene = scene_placement_ready(
        unit1_band="A1", unit1_nodes=1, unit2_band="B1", total_items=20,
        complete_unit1=True, progress_unit2=True, scored=True,
        comprehension_score=200, accuracy_score=0,
    )
    placement = get_success_data(api_client.update_placement_test(
        scene["placement"]["id"],
        placement_action_payload("CALIBRATE", proctor_user_id="proctor-1"),
        scene["headers"],
    ))

    assert placement["placed_unit_index"] == 2, (
        "the institution-graded ceiling also counts unit 2's IN_PROGRESS "
        f"posture, got {placement['placed_unit_index']}"
    )
    assert placement["calibrated_cefr_band"] == "B1", (
        "the band follows the unit the learner is placed into, so unit 2's B1, "
        f"got {placement['calibrated_cefr_band']}"
    )
    assert placement["is_institution_graded"] is True


def test_self_serve_anchor_ignores_in_progress_units(api):
    """PRD §3.6: "The candidate position is then clamped against how far the
    learner's own course has actually advanced. For a self-serve session the
    ceiling is the largest `unit_index` among units the learner has already
    `COMPLETED`"
    PRD §3.6: "the flag is true exactly when `proctor_user_id` holds a
    non-empty operator identifier, and it selects which boundary anchor the
    calibration applies."

    Design: Difficulty/dual_variant_calc/placement_hard_cap_anchor_by_session_grade
    """
    scene = scene_placement_ready(
        unit1_band="A1", unit1_nodes=1, unit2_band="B1", total_items=20,
        complete_unit1=True, progress_unit2=True, extra_completed_units=1,
        extra_unit_band="A2", scored=True, comprehension_score=200,
        accuracy_score=0,
    )
    placement = get_success_data(api_client.update_placement_test(
        scene["placement"]["id"], placement_action_payload("CALIBRATE"),
        scene["headers"],
    ))

    assert placement["placed_unit_index"] == 3, (
        "a self-serve session skips unit 2's IN_PROGRESS posture and takes the "
        f"largest COMPLETED unit_index, got {placement['placed_unit_index']}"
    )
    assert placement["is_institution_graded"] is False