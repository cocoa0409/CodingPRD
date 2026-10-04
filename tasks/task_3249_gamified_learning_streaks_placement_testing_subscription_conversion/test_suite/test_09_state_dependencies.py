"""State dependencies: an operation refused because its subject is in the wrong
posture."""
from test_helpers import (
    api_client, append_lesson_node, create_course_unit, get_success_data,
    make_learner_headers, placement_action_payload, placement_test_payload,
    practice_ok, read_node, register_learner, review, validate_error,
)


def _locked_second_node(band="A1"):
    unit = create_course_unit(cefr_band=band, total_nodes=2)
    root = append_lesson_node(unit["id"], 1)
    second = append_lesson_node(unit["id"], 2, root["id"])
    return unit, root, second


def test_calibrating_a_just_opened_session_is_refused(api):
    """PRD §3.6: "A placement operation aimed at a session whose status is not one
    of `CREATED`, `IN_PROGRESS`, `SCORED` or `CALIBRATED` is refused with
    `ERR_PLACEMENT_NOT_ACTIVE` at HTTP 409."

    Design: Difficulty/cross_entity_state_dependency/placement_calibrate_requires_scored_session
    """
    learner = register_learner(display_name="Ada", local_date_offset_days=0,
                               program_tier="FREE")
    headers = make_learner_headers(learner["id"])
    unit = create_course_unit(total_nodes=1)
    append_lesson_node(unit["id"], 1)

    placement = get_success_data(api_client.create_placement_test(
        placement_test_payload(
            learner_id=learner["id"],
            course_id=unit["id"],
            administered_at="2026-09-01T02:00:00Z",
            total_items=10,
            expected_learner_version=learner["version"],
        ),
        headers,
    ))
    assert placement["status"] == "CREATED"

    refused = api_client.update_placement_test(
        placement["id"], placement_action_payload("CALIBRATE"), headers
    )
    validate_error(refused, "ERR_PLACEMENT_NOT_ACTIVE")


def test_an_unscored_session_cannot_be_calibrated_even_though_it_owns_the_probe(api):
    """PRD §3.6: "Calibration converts the raw sub-scores into a course position"
    PRD §3.6: "it is admitted only once the number of recorded placement attempts on
    nodes belonging to units up to the session's `placed_unit_index` has reached the
    session's `total_items`; it drives `IN_PROGRESS → SCORED`"

    Design: Difficulty/cross_entity_state_dependency/placement_calibrate_requires_scored_session
    """
    learner = register_learner(display_name="Ada", local_date_offset_days=0,
                               program_tier="FREE")
    headers = make_learner_headers(learner["id"])
    unit = create_course_unit(total_nodes=1)
    node = append_lesson_node(unit["id"], 1)

    placement = get_success_data(api_client.create_placement_test(
        placement_test_payload(
            learner_id=learner["id"],
            course_id=unit["id"],
            administered_at="2026-09-01T02:00:00Z",
            total_items=10,
            expected_learner_version=learner["version"],
        ),
        headers,
    ))

    # Present one item only, so the session is IN_PROGRESS but under-scored.
    get_success_data(api_client.update_placement_test(
        placement["id"],
        placement_action_payload(
            "PRESENT_ITEM", lesson_node_id=node["id"],
            recorded_at="2026-09-01T02:30:00Z", response_ms=4000, correct=True,
        ),
        headers,
    ))
    in_progress = get_success_data(api_client.get_placement_test(
        placement["id"], headers
    ))
    assert in_progress["status"] == "IN_PROGRESS"

    refused = api_client.update_placement_test(
        placement["id"], placement_action_payload("CALIBRATE"), headers
    )
    validate_error(refused, "ERR_PLACEMENT_NOT_ACTIVE")

    untouched = get_success_data(api_client.get_placement_test(
        placement["id"], headers
    ))
    assert untouched["status"] == "IN_PROGRESS"
    assert untouched["calibrated_cefr_band"] is None
    assert untouched["placed_unit_index"] is None


def test_reviewing_a_bronze_node_is_refused(api):
    """PRD §3.2: "A review is attempted against a node whose `state` is `DECAYED` —
    any other target is refused with `ERR_NODE_NOT_DECAYED` at HTTP 409"

    Design: Difficulty/cross_entity_state_dependency/review_requires_decayed_node_state
    """
    learner = register_learner(display_name="Ada", local_date_offset_days=0,
                               program_tier="FREE")
    unit = create_course_unit(total_nodes=1)
    node = append_lesson_node(unit["id"], 1)
    practice_ok(node["id"], learner["id"], "2026-09-01T00:00:00Z",
                response_ms=5000, correct=True)

    bronze = read_node(node["id"], learner["id"])
    assert bronze["state"] == "BRONZE"

    refused = review(node["id"], learner["id"], bronze["version"])
    validate_error(refused, "ERR_NODE_NOT_DECAYED")


def test_review_refusal_leaves_the_bronze_crown_intact(api):
    """PRD §3.2: "the review counts as a mutation of the node: its `version`
    increments by one"
    PRD §2.7: "The request is then refused with `ERR_STALE_VERSION` at HTTP 412 and
    no part of the write is applied."

    Design: Difficulty/cross_entity_state_dependency/review_requires_decayed_node_state
    """
    learner = register_learner(display_name="Ada", local_date_offset_days=0,
                               program_tier="FREE")
    unit = create_course_unit(total_nodes=1)
    node = append_lesson_node(unit["id"], 1)
    practice_ok(node["id"], learner["id"], "2026-09-01T00:00:00Z",
                response_ms=5000, correct=True)
    bronze = read_node(node["id"], learner["id"])

    refused = review(node["id"], learner["id"], bronze["version"])
    validate_error(refused, "ERR_NODE_NOT_DECAYED")

    after = read_node(node["id"], learner["id"])
    assert after["state"] == "BRONZE", (
        f"a refused review does not advance the crown, got {after['state']}"
    )
    assert after["version"] == bronze["version"], (
        f"a refused review is not applied at all, got version {after['version']} "
        f"from {bronze['version']}"
    )