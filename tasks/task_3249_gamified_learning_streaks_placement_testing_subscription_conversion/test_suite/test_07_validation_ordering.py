"""Validation ordering: the earlier check in the cascade decides the response."""
from test_helpers import (
    NON_EXISTENT_UUID, append_lesson_node, create_course_unit,
    make_learner_headers, practice, read_node, register_learner, validate_error,
)


def _locked_second_node(learner_id, band="A1"):
    """Unit 1 with a root node plus a second node chained behind it, so the
    second node is still LOCKED."""
    unit = create_course_unit(cefr_band=band, total_nodes=2)
    root = append_lesson_node(unit["id"], 1)
    second = append_lesson_node(unit["id"], 2, root["id"])
    return unit, root, second


def test_state_check_wins_over_unrecognised_payload_field(api):
    """PRD §3.1: "A practice attempt submitted against a node that has not opened,
    or whose prerequisite is still unmet, is refused — the first with
    `ERR_NODE_LOCKED` and the second with `ERR_PREREQUISITE_NOT_MET`, both at
    HTTP 409."
    PRD §2.10: "State-entry checks come next: the concurrency guard on a
    placement or exam create (`ERR_STALE_VERSION`, 412); the lesson node's
    `state` being one of `UNLOCKED`, `BRONZE`, `SILVER`, `GOLD` or `LEGENDARY`
    for a practice attempt (`ERR_NODE_LOCKED`, 409)"
    PRD §2.10: "and finally, the presence of every required input field and the
    membership of every enum field in its declared set (`ERR_INVALID_REQUEST`,
    400)"

    Design: Difficulty/priority_pair_validation_conflict/locked_node_outranks_unknown_payload_field
    """
    learner = register_learner(display_name="Ada", local_date_offset_days=0,
                               program_tier="FREE")
    _unit, _root, locked = _locked_second_node(learner["id"])

    response = practice(
        locked["id"],
        {
            "learner_id": learner["id"],
            "recorded_at": "2026-09-01T10:00:00Z",
            "response_ms": 9000,
            "correct": True,
            "heal_flag": True,
        },
        make_learner_headers(learner["id"]),
    )

    validate_error(response, "ERR_NODE_LOCKED")


def test_existence_check_wins_over_state_check(api):
    """PRD §2.5: "A practice or review submission that names a learner and a
    lesson node therefore reports `ERR_LEARNER_NOT_FOUND` when the learner is
    unknown and `ERR_LESSON_NODE_NOT_FOUND` only once the learner has been
    confirmed."
    PRD §2.10: "Existence checks follow, in the left-to-right order of §2.5: the
    learner named by `X-User-ID` or by a `learner_id` in the body or query must
    exist (`ERR_LEARNER_NOT_FOUND`, 404)"

    Design: Difficulty/priority_pair_validation_conflict/missing_learner_outranks_locked_node
    """
    learner = register_learner(display_name="Ada", local_date_offset_days=0,
                               program_tier="FREE")
    _unit, _root, locked = _locked_second_node(learner["id"])

    response = practice(
        locked["id"],
        {
            "learner_id": NON_EXISTENT_UUID,
            "recorded_at": "2026-09-01T10:00:00Z",
            "response_ms": 3000,
            "correct": True,
        },
        make_learner_headers(NON_EXISTENT_UUID),
    )

    validate_error(response, "ERR_LEARNER_NOT_FOUND")


def test_unknown_learner_refusal_leaves_the_locked_node_untouched(api):
    """PRD §2.10: "Because the ordering is normative, a request that would violate a
    later rule but trips an earlier one reports the earlier error. Implementers
    should not reorder these checks even where the underlying storage would allow a
    different sequence."
    PRD §3.1: "A practice attempt submitted against a node that has not opened, or
    whose prerequisite is still unmet, is refused"

    Design: Difficulty/priority_pair_validation_conflict/missing_learner_outranks_locked_node
    """
    learner = register_learner(display_name="Ada", local_date_offset_days=0,
                               program_tier="FREE")
    _unit, _root, locked = _locked_second_node(learner["id"])

    validate_error(
        practice(
            locked["id"],
            {
                "learner_id": NON_EXISTENT_UUID,
                "recorded_at": "2026-09-01T10:00:00Z",
                "response_ms": 3000,
                "correct": True,
            },
            make_learner_headers(NON_EXISTENT_UUID),
        ),
        "ERR_LEARNER_NOT_FOUND",
    )

    untouched = read_node(locked["id"], learner["id"])
    assert untouched["state"] == "LOCKED", (
        f"the earlier existence check short-circuits before any node work, got "
        f"{untouched['state']}"
    )

    # The same node, named by a real learner, still trips the state check.
    validate_error(
        practice(
            locked["id"],
            {
                "learner_id": learner["id"],
                "recorded_at": "2026-09-01T11:00:00Z",
                "response_ms": 3000,
                "correct": True,
            },
            make_learner_headers(learner["id"]),
        ),
        "ERR_NODE_LOCKED",
    )


def test_locked_node_rejection_leaves_the_node_untouched(api):
    """PRD §3.1: "A practice attempt submitted against a node that has not opened,
    or whose prerequisite is still unmet, is refused — the first with
    `ERR_NODE_LOCKED` and the second with `ERR_PREREQUISITE_NOT_MET`, both at
    HTTP 409."
    PRD §2.10: "Implementers should not reorder these checks even where the
    underlying storage would allow a different sequence."

    Design: Difficulty/priority_pair_validation_conflict/locked_node_outranks_unknown_payload_field
    """
    learner = register_learner(display_name="Ada", local_date_offset_days=0,
                               program_tier="FREE")
    _unit, _root, locked = _locked_second_node(learner["id"])

    response = practice(
        locked["id"],
        {
            "learner_id": learner["id"],
            "recorded_at": "2026-09-01T10:00:00Z",
            "response_ms": 9000,
            "correct": True,
        },
        make_learner_headers(learner["id"]),
    )
    validate_error(response, "ERR_NODE_LOCKED")

    after = read_node(locked["id"], learner["id"])
    assert after["state"] == "LOCKED", (
        f"a refused attempt leaves the node LOCKED, got {after['state']}"
    )
