"""Listing behaviour, streaked-read sweep guard, retention floor and OCC."""
from datetime import datetime, timedelta, timezone

from test_helpers import (
    api_client, append_lesson_node, create_course_unit, fire_event,
    get_streak, get_success_data, make_learner_headers, placement_test_payload,
    practice_ok, read_node, register_learner, review, set_clock, validate_error,
    validate_paginated,
)


def test_lesson_node_listing_carries_the_full_pagination_envelope(api, admin_headers):
    """PRD §2.3: "List responses carry four pagination fields inside the `meta`
    object of the envelope: `limit`, `offset`, `total_count`, and `has_more`."
    PRD §2.3: "`total_count` reports the size of the full result set rather than the
    size of the returned page, and `has_more` is true exactly when further items
    remain beyond the returned page."

    Design: Corner/endpoints/list_pagination_envelope_on_lesson_node_listing
    """
    unit = create_course_unit(total_nodes=2)
    root = append_lesson_node(unit["id"], 1)
    append_lesson_node(unit["id"], 2, root["id"])

    response = api_client.list_lesson_nodes(
        admin_headers, {"unit_id": unit["id"], "limit": 1, "offset": 0}
    )
    data, meta = validate_paginated(response)

    assert meta["total_count"] == 2, (
        f"the full result set holds both nodes, got {meta['total_count']}"
    )
    assert meta["has_more"] is True, "an item remains beyond the returned page"
    assert meta["limit"] == 1
    assert meta["offset"] == 0
    assert data[0]["id"] == root["id"], (
        "the listing is ordered by node index, so the first row is the unit root"
    )


def test_firing_the_day_close_sweep_twice_without_advancing_the_clock_changes_nothing(api):
    """PRD §3.3: "If the closed day saw no accepted attempt, the streak is defended
    or lost. A learner holding at least one `freeze_token` spends one: `freeze_tokens`
    decreases by one, `current_length` is preserved untouched, and `focus_date`
    advances by one local day"
    PRD §3.3: "A learner with no tokens left has their streak broken:
    `current_length` drops to zero, the next repair price is computed for the
    learner, `focus_date` advances by one local day, and if that learner's
    `hearts_available` is zero a conversion offer with `milestone_code`
    `HEART_DEPLETION` is issued to soften the loss."

    Design: Corner/cross_cutting_layers/idempotent_day_close_sweep_is_guarded_by_focus_date
    """
    learner = register_learner(display_name="Ada", local_date_offset_days=0,
                               program_tier="FREE")
    streak = get_streak(learner["id"])
    assert streak["freeze_tokens"] == 0, (
        "a fresh streak row holds no defensive capacity until an operator equips "
        f"a token, got {streak['freeze_tokens']}"
    )

    set_clock("2026-09-02T00:00:00Z")
    fire_event("STREAK_DAY_CLOSE")

    after_first = get_streak(learner["id"])
    assert after_first["status"] in ("BROKEN", "FROZEN"), (
        f"the missed day resolves the streak, got {after_first['status']}"
    )

    fire_event("STREAK_DAY_CLOSE")
    after_second = get_streak(learner["id"])

    assert after_second["current_length"] == after_first["current_length"], (
        "the second sweep finds focus_date already level with the local date and "
        f"does nothing, got {after_second['current_length']} from "
        f"{after_first['current_length']}"
    )
    assert after_second["freeze_tokens"] == after_first["freeze_tokens"]


def test_day_close_sweep_does_nothing_while_the_local_date_has_not_moved(api):
    """PRD §3.3: "Day close is an operator-fired sweep that advances each learner
    whose local date has moved past their `focus_date`."
    PRD §2.11: "`STREAK_DAY_CLOSE` runs the streak freeze sweep once for every
    learner whose local date has advanced past their `focus_date`, advancing
    `focus_date` by one day"

    Design: Corner/cross_cutting_layers/idempotent_day_close_sweep_is_guarded_by_focus_date
    """
    learner = register_learner(display_name="Ada", local_date_offset_days=0,
                               program_tier="FREE")
    unit = create_course_unit(total_nodes=1)
    node = append_lesson_node(unit["id"], 1)

    practice_ok(node["id"], learner["id"], "2026-09-01T00:00:00Z",
                response_ms=5000, correct=True)
    qualified = get_streak(learner["id"])
    assert qualified["current_length"] == 1

    # The clock has not moved past focus_date, so the sweep has no learner to
    # advance.
    fire_event("STREAK_DAY_CLOSE")
    still = get_streak(learner["id"])

    assert still["status"] in ("QUALIFIED", "EVALUATING"), (
        "a day that has not moved past focus_date is never closed, so the row "
        f"keeps its qualifying posture, got {still['status']}"
    )
    assert still["current_length"] == 1, (
        f"the untouched sweep preserves the length, got {still['current_length']}"
    )


def test_reviewing_a_node_at_the_retention_floor_is_refused_but_one_below_succeeds(api):
    """PRD §3.2: "Attempting a review against a node already at the floor is refused
    outright with `ERR_DECAY_RETENTION_FLOOR` at HTTP 409, and the review counts as a
    mutation of the node: its `version` increments by one."
    PRD §3.2: "A node whose `decay_level` is still below the retention floor is
    restored `DECAYED → UNLOCKED`, its `decay_meter` resets to zero"

    Design: Corner/errors/error_decay_retention_floor_on_fourth_decay
    """
    learner = register_learner(display_name="Ada", local_date_offset_days=0,
                               program_tier="FREE")
    unit = create_course_unit(total_nodes=1)
    node = append_lesson_node(unit["id"], 1)
    practice_ok(node["id"], learner["id"], "2026-09-01T00:00:00Z",
                response_ms=5000, correct=True)

    # Three decay-and-restore cycles walk decay_level up to three: each cycle
    # lets ten days elapse (the meter reaches its five-point ceiling), demotes the
    # node to DECAYED, then restores it with a spaced review.
    for cycle in range(3):
        sweep_day = datetime(2026, 9, 1, tzinfo=timezone.utc) + timedelta(
            days=10 * (cycle + 1)
        )
        set_clock(sweep_day.strftime("%Y-%m-%dT%H:%M:%SZ"))
        fire_event("SKILL_DECAY")
        decayed = read_node(node["id"], learner["id"])
        assert decayed["state"] == "DECAYED", (
            f"cycle {cycle} demotes the crowned node, got {decayed['state']}"
        )
        assert decayed["decay_level"] == cycle + 1, (
            f"cycle {cycle} lands decay_level at {cycle + 1}, got "
            f"{decayed['decay_level']}"
        )
        restored = get_success_data(review(node["id"], learner["id"],
                                           decayed["version"]))
        assert restored["state"] == "UNLOCKED"
        assert restored["decay_level"] == cycle + 1

    # One further cycle drives decay_level to the floor of four while DECAYED.
    floor_day = datetime(2026, 9, 1, tzinfo=timezone.utc) + timedelta(days=40)
    set_clock(floor_day.strftime("%Y-%m-%dT%H:%M:%SZ"))
    fire_event("SKILL_DECAY")
    at_floor = read_node(node["id"], learner["id"])
    assert at_floor["state"] == "DECAYED"
    assert at_floor["decay_level"] == 4, (
        f"the fourth demotion leaves decay_level at the retention floor, got "
        f"{at_floor['decay_level']}"
    )

    # A review against a node already at the floor is refused outright.
    validate_error(
        review(node["id"], learner["id"], at_floor["version"]),
        "ERR_DECAY_RETENTION_FLOOR",
    )


def test_proctor_role_identifier_is_not_a_learner(api, admin_headers, proctor_headers):
    """PRD §2.1: "When `X-User-Role` is `CertificationProctor`, `X-User-ID` is an
    opaque operator identifier not tied to any persisted entity"
    PRD §2.1: "a request whose role is not permitted, or in which one learner
    acts on another learner's resource, is refused with `ERR_UNAUTHORIZED` at
    HTTP 403."

    Design: Corner/rbac/proctor_role_is_opaque_and_cannot_join_league
    """
    learner = register_learner(display_name="Ada", local_date_offset_days=0,
                               program_tier="PLUS_FAMILY")
    league = get_success_data(api_client.create_league(
        {"tier": "BRONZE", "week_start": "2026-09-21T00:00:00Z"},
        admin_headers,
    ))

    validate_error(
        api_client.update_league(
            league["id"], {"action": "JOIN", "learner_id": learner["id"]},
            proctor_headers,
        ),
        "ERR_UNAUTHORIZED",
    )

    refreshed = get_success_data(api_client.get_league(
        league["id"], admin_headers
    ))
    assert refreshed["member_count"] == 0, (
        "the opaque operator id is not a learner, so no standing was minted"
    )


def test_placement_create_with_a_stale_learner_version_is_refused(api):
    """PRD §2.7: "Opening a `PlacementTest` requires `expected_learner_version`
    matching the target learner's current `version`; if the learner's version has
    moved on since the client last read it, the create is refused with
    `ERR_STALE_VERSION` at HTTP 412."
    PRD §2.7: "a second attempt made against a freshly read version is legitimate
    and succeeds"

    Design: Corner/cross_cutting_layers/occ_stale_learner_version_on_second_placement_create
    """
    learner = register_learner(display_name="Ada", local_date_offset_days=0,
                               program_tier="FREE")
    headers = make_learner_headers(learner["id"])
    unit = create_course_unit(total_nodes=1)
    append_lesson_node(unit["id"], 1)

    first = get_success_data(api_client.create_placement_test(
        placement_test_payload(
            learner_id=learner["id"], course_id=unit["id"],
            administered_at="2026-09-01T02:00:00Z", total_items=20,
            expected_learner_version=learner["version"],
        ),
        headers,
    ))

    stale = api_client.create_placement_test(
        placement_test_payload(
            learner_id=learner["id"], course_id=unit["id"],
            administered_at="2026-09-01T03:00:00Z", total_items=20,
            expected_learner_version=learner["version"],
        ),
        headers,
    )
    validate_error(stale, "ERR_STALE_VERSION")

    sessions = get_success_data(api_client.list_placement_tests(
        headers, {"learner_id": learner["id"]}
    ))
    assert [session["id"] for session in sessions] == [first["id"]], (
        "the stale write is refused and leaves the session already minted intact"
    )


def test_learner_cannot_calibrate_another_learners_placement_session(api):
    """PRD §2.1: "in which one learner acts on another learner's resource, is
    refused with `ERR_UNAUTHORIZED` at HTTP 403"
    PRD §2.1: "ownership checks on any resource that references a `Learner` — a
    streak row's `learner_id`, a standing's `learner_id`, an offer's
    `learner_id`, a placement session's `learner_id`, an exam's `learner_id` —
    compare that foreign-key field to `X-User-ID`."

    Design: Corner/endpoints/unauthorized_anonymous_placement_calibrate_denied
    """
    from test_helpers import placement_action_payload

    owner = register_learner(display_name="Ada", local_date_offset_days=0,
                             program_tier="FREE")
    intruder = register_learner(display_name="Bea", local_date_offset_days=0,
                                program_tier="FREE")
    unit = create_course_unit(total_nodes=1)
    node = append_lesson_node(unit["id"], 1)

    placement = get_success_data(api_client.create_placement_test(
        placement_test_payload(
            learner_id=owner["id"], course_id=unit["id"],
            administered_at="2026-09-01T02:00:00Z", total_items=5,
            expected_learner_version=owner["version"],
        ),
        make_learner_headers(owner["id"]),
    ))
    # PRD §3.6: the sub-score submission is admitted only once the recorded
    # placement attempts reach the session's total_items, so five items are
    # presented before the session can be scored.
    for _ in range(5):
        get_success_data(api_client.update_placement_test(
            placement["id"],
            placement_action_payload(
                "PRESENT_ITEM", lesson_node_id=node["id"],
                recorded_at="2026-09-01T02:30:00Z", response_ms=4000,
                correct=True,
            ),
            make_learner_headers(owner["id"]),
        ))
    get_success_data(api_client.update_placement_test(
        placement["id"],
        placement_action_payload("SUBMIT_SCORES", comprehension_score=120,
                                 accuracy_score=80),
        make_learner_headers(owner["id"]),
    ))

    validate_error(
        api_client.update_placement_test(
            placement["id"], placement_action_payload("CALIBRATE"),
            make_learner_headers(intruder["id"]),
        ),
        "ERR_UNAUTHORIZED",
    )

    after = get_success_data(api_client.get_placement_test(
        placement["id"], make_learner_headers(owner["id"])
    ))
    assert after["status"] == "SCORED"