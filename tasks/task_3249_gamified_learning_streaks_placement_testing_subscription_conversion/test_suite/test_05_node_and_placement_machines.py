"""Forking and cyclic state machines: node recovery, re-locking and re-scoring."""
from test_helpers import (
    api_client, append_lesson_node, create_course_unit, fire_event,
    get_success_data, list_unit_nodes, placement_action_payload, practice_ok,
    read_node, register_learner, review, scene_placement_ready, set_clock,
)


def test_review_of_decayed_node_below_the_floor_restores_it_and_reopens_dependents(api):
    """PRD §3.2: "A node whose `decay_level` is still below the retention floor is
    restored `DECAYED → UNLOCKED`, its `decay_meter` resets to zero, and any
    dependent node that is `LOCKED` but whose other prerequisites are satisfied is
    re-opened in turn"

    Design: Difficulty/non_linear_state_machine/lesson_node_decay_and_prerequisite_fork
    """
    learner = register_learner(display_name="Ada", local_date_offset_days=0,
                               program_tier="FREE")
    unit = create_course_unit(cefr_band="B1", total_nodes=2)
    root = append_lesson_node(unit["id"], 1)
    dependent = append_lesson_node(unit["id"], 2, root["id"])

    # Only the root is practised, so the dependent is left UNLOCKED — the posture
    # PRD §3.2's relocking rule targets ("every lesson node that names it as
    # `prerequisite_node_id` and that is currently `UNLOCKED`").  The sweep uses
    # 2026-09-11: the root (reviewed 09-01, due 09-02) has crossed its five-point
    # ceiling and is demoted, while the dependent — never practised and so never
    # reviewed — stays UNLOCKED and is pushed back to LOCKED by that demotion.
    practice_ok(root["id"], learner["id"], "2026-09-01T00:00:00Z",
                response_ms=5000, correct=True)
    set_clock("2026-09-11T00:00:00Z")
    fire_event("SKILL_DECAY")

    decayed = read_node(root["id"], learner["id"])
    assert decayed["state"] == "DECAYED"
    locked = read_node(dependent["id"], learner["id"])
    assert locked["state"] == "LOCKED", (
        "the demoted root pushes its UNLOCKED dependent back to LOCKED, got "
        f"{locked['state']}"
    )

    reviewed = get_success_data(review(
        root["id"], learner["id"], decayed["version"]
    ))
    assert reviewed["state"] == "UNLOCKED", (
        f"decay_level 1 sits below the floor of four, got {reviewed['state']}"
    )
    assert reviewed["decay_meter"] == 0

    reopened = read_node(dependent["id"], learner["id"])
    assert reopened["state"] == "UNLOCKED", (
        "the dependent's only prerequisite is satisfied again, so it is "
        f"re-opened in turn, got {reopened['state']}"
    )


def test_review_of_decayed_node_pulls_its_completed_unit_back_to_in_progress(api):
    """PRD §3.2: "A review is attempted against a node whose `state` is `DECAYED`"
    PRD §3.1: "a review that restores a decayed node pulls its completed unit back
    to `IN_PROGRESS` until the node is restored"

    Design: Difficulty/non_linear_state_machine/lesson_node_decay_and_prerequisite_fork
    """
    learner = register_learner(display_name="Ada", local_date_offset_days=0,
                               program_tier="FREE")
    unit = create_course_unit(cefr_band="B1", total_nodes=2)
    root = append_lesson_node(unit["id"], 1)
    dependent = append_lesson_node(unit["id"], 2, root["id"])

    practice_ok(root["id"], learner["id"], "2026-09-01T00:00:00Z",
                response_ms=5000, correct=True)
    set_clock("2026-09-02T00:00:00Z")
    practice_ok(dependent["id"], learner["id"], "2026-09-02T01:00:00Z",
                response_ms=5000, correct=True)

    nodes = list_unit_nodes(unit["id"], learner["id"])
    assert [node["state"] for node in nodes] == ["BRONZE", "BRONZE"], (
        "after the second practice the unit is IN_PROGRESS with both children "
        f"crowned, got {[n['state'] for n in nodes]}"
    )

    set_clock("2026-09-12T00:00:00Z")
    fire_event("SKILL_DECAY")
    decayed = read_node(root["id"], learner["id"])
    assert decayed["state"] == "DECAYED"
    reviewed = get_success_data(review(root["id"], learner["id"], decayed["version"]))
    assert reviewed["state"] == "UNLOCKED"

    # The dependent was crowned at BRONZE when the root decayed, so §3.2's
    # relocking rule — which applies only to dependents "currently `UNLOCKED`" —
    # never touched it, and the review restores only the decayed node.  Its crown
    # survives the cycle untouched; the completed unit is left IN_PROGRESS until
    # the restored node earns a crown again.
    refreshed = read_node(dependent["id"], learner["id"])
    assert refreshed["state"] == "BRONZE", (
        "a crowned dependent is never relocked by a prerequisite's decay, got "
        f"{refreshed['state']}"
    )


def test_placement_rescore_returns_session_to_scored_without_a_band(api):
    """PRD §3.6: "A calibrated session can be reopened for rescoring, which clears
    `calibrated_cefr_band` and re-evaluates the band from the stored sub-scores"
    PRD §3.6: "a recalibration takes the larger of the index already assigned and
    the newly computed one, so a learner never loses ground they have already been
    credited"

    Design: Difficulty/non_linear_state_machine/placement_scored_calibrated_cycle_with_certified_branch
    """
    scene = scene_placement_ready(
        unit1_band="A1", unit1_nodes=1, unit2_band="B1", total_items=20,
        complete_unit1=True, progress_unit2=True, complete_unit2=True,
        scored=True, calibrated=True, proctor_user_id="proctor-1",
        comprehension_score=200, accuracy_score=0,
    )
    placement_id = scene["placement"]["id"]
    headers = scene["headers"]

    calibrated = get_success_data(api_client.get_placement_test(
        placement_id, headers
    ))
    assert calibrated["status"] == "CALIBRATED"
    assert calibrated["placed_unit_index"] == 2

    rescored = get_success_data(api_client.update_placement_test(
        placement_id,
        placement_action_payload("SUBMIT_SCORES", comprehension_score=200,
                                 accuracy_score=0),
        headers,
    ))

    assert rescored["status"] == "SCORED", (
        f"a resubmission drives CALIBRATED -> SCORED, got {rescored['status']}"
    )
    assert rescored["calibrated_cefr_band"] is None, (
        "the resubmission clears the calibrated band, got "
        f"{rescored['calibrated_cefr_band']}"
    )
    assert rescored["placed_unit_index"] == 2, (
        "placed_unit_index is monotonic non-decreasing across the loop, got "
        f"{rescored['placed_unit_index']}"
    )


def test_placement_recalibration_is_monotonic_and_reapplies_the_band(api):
    """PRD §3.6: "Across those loops the learner's `placed_unit_index` is monotonic:
    a recalibration takes the larger of the index already assigned and the newly
    computed one"
    PRD §3.6: "when the resulting `placed_unit_index` is at least 5, a conversion
    offer with `milestone_code` `PLACEMENT_SKIP` is issued for the learner"

    Design: Difficulty/non_linear_state_machine/placement_scored_calibrated_cycle_with_certified_branch
    """
    scene = scene_placement_ready(
        unit1_band="A1", unit1_nodes=1, unit2_band="B1", total_items=20,
        complete_unit1=True, progress_unit2=True, complete_unit2=True,
        scored=True, calibrated=True, proctor_user_id="proctor-1",
        comprehension_score=200, accuracy_score=0,
    )
    placement_id = scene["placement"]["id"]
    headers = scene["headers"]

    get_success_data(api_client.update_placement_test(
        placement_id,
        placement_action_payload("SUBMIT_SCORES", comprehension_score=200,
                                 accuracy_score=0),
        headers,
    ))
    recalibrated = get_success_data(api_client.update_placement_test(
        placement_id, placement_action_payload("CALIBRATE"), headers,
    ))

    assert recalibrated["status"] == "CALIBRATED"
    assert recalibrated["placed_unit_index"] == 2, (
        "the second calibration credits the same two units and never drops the "
        f"learner below their earlier placement, got "
        f"{recalibrated['placed_unit_index']}"
    )
    assert recalibrated["calibrated_cefr_band"] == "B1"