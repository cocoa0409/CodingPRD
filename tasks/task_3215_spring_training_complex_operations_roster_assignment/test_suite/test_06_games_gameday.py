"""Exhibition games: publish gates, interval collisions and gameday packaging."""
from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    add_participation,
    api_client,
    cleared_player,
    confirm_participation,
    create_complex,
    create_game,
    create_workout_group,
    field_maintenance,
    fresh_game_version,
    get_complex,
    get_game,
    get_participation,
    publish_game,
    set_test_clock,
    validate_error,
    validate_success,
)


def _session(complex_id, session_date, session_end, **overrides):
    group = create_workout_group(complex_id)
    return validate_success(api_client.create_workout_session(
        group["id"],
        {
            "workout_group_id": group["id"],
            "session_date": session_date,
            "session_end_datetime": session_end,
            "session_kind": "BULLPEN",
            "field_units": 1,
            **overrides,
        },
        TEST_USERS["field_coordinator_headers"],
    ), 201)


def test_away_game_publishes_while_the_complex_posture_is_normal():
    """PRD 3.8: "Second, the owning complex's `facility_posture` must not be
    `CLOSED`, since a closed complex cannot host or dispatch a game."

    Design: Difficulty/cross_entity_state_dependency/away_game_publish_gate_depends_on_the_complex_posture
    """
    set_test_clock()
    complex_ = create_complex(facility_capacity_units=100)
    game = create_game(
        complex_["id"], opponent_name="Colorado Rockies", home_away="AWAY",
        game_datetime="2026-02-12T19:00:00Z", travel_radius_miles=180, duration_units=3)

    published = publish_game(game["id"])
    assert published["game_schedule_status"] == "PUBLISHED"


def test_away_game_publish_is_refused_once_the_complex_is_closed():
    """PRD 3.8: "Second, the owning complex's `facility_posture` must not be
    `CLOSED`, since a closed complex cannot host or dispatch a game."
    PRD 3.9: "every away game on the complex that is still `DRAFT` is driven to
    `CANCELLED`"

    Design: Difficulty/cross_entity_state_dependency/away_game_publish_gate_depends_on_the_complex_posture
    """
    set_test_clock()
    complex_ = create_complex(facility_capacity_units=100)
    first = create_game(
        complex_["id"], opponent_name="Colorado Rockies", home_away="AWAY",
        game_datetime="2026-02-12T19:00:00Z", travel_radius_miles=180, duration_units=3)
    second = create_game(
        complex_["id"], opponent_name="San Diego Padres", home_away="AWAY",
        game_datetime="2026-02-14T19:00:00Z", travel_radius_miles=180, duration_units=3)

    assert publish_game(first["id"])["game_schedule_status"] == "PUBLISHED"
    validate_success(field_maintenance(complex_["id"], "CLOSED"))
    assert get_complex(complex_["id"])["facility_posture"] == "CLOSED"

    validate_error(
        api_client.publish_game(
            second["id"], fresh_game_version(second["id"]),
            TEST_USERS["complex_director_headers"]),
        ApiErrorId.ERR_INVALID_STATE,
    )


def test_a_session_ending_at_the_game_interval_start_still_conflicts():
    """PRD 2.7: "Because both intervals are half-open after truncation, a session
    that ends at exactly the instant the game interval begins still conflicts"
    PRD 2.5: "`game_interval_start` is the first-pitch instant minus the game's
    duration units, and `game_interval_end` is the first-pitch instant plus the
    same duration units."

    Design: Difficulty/resource_temporal_overlap/workout_session_collides_with_a_candidate_game_interval
    """
    set_test_clock()
    complex_ = create_complex(facility_capacity_units=100)
    _session(complex_["id"], "2026-02-12T06:00:00Z", "2026-02-12T07:00:00Z")
    game = create_game(
        complex_["id"], opponent_name="Colorado Rockies", home_away="HOME",
        game_datetime="2026-02-12T10:00:00Z", travel_radius_miles=0, duration_units=3)

    validate_error(
        api_client.publish_game(
            game["id"], fresh_game_version(game["id"]),
            TEST_USERS["complex_director_headers"]),
        ApiErrorId.ERR_TEMPORAL_OVERLAP,
    )
    unchanged = get_game(game["id"])
    assert unchanged["game_schedule_status"] == "DRAFT"
    assert unchanged["game_interval_start"] == "2026-02-12T07:00:00.000Z"
    assert unchanged["game_interval_end"] == "2026-02-12T13:00:00.000Z"


def test_a_session_well_before_the_game_interval_publishes_cleanly():
    """PRD 2.7: "A candidate game whose interval touches any scheduled session
    interval on the same complex — including at a single shared minute boundary —
    may not be published"

    Design: Difficulty/resource_temporal_overlap/workout_session_collides_with_a_candidate_game_interval
    """
    set_test_clock()
    complex_ = create_complex(facility_capacity_units=100)
    _session(complex_["id"], "2026-02-12T04:00:00Z", "2026-02-12T06:00:00Z")
    game = create_game(
        complex_["id"], opponent_name="San Diego Padres", home_away="HOME",
        game_datetime="2026-02-12T10:00:00Z", travel_radius_miles=0, duration_units=3)

    published = publish_game(game["id"])
    assert published["game_schedule_status"] == "PUBLISHED"


def test_an_away_game_beyond_the_travel_radius_cannot_even_be_created():
    """PRD 3.8: "an away game may be published only if its `travel_radius_miles`
    is at most 250; a home game carries no radius restriction. A distance of
    exactly 250 is inside the limit and 250.01 is outside it ... note that this
    same limit is checked when the game is created, so an away game beyond the
    radius cannot even be recorded."

    Design: Corner/validations/away_game_beyond_the_travel_radius_is_rejected_at_create
    """
    set_test_clock()
    complex_ = create_complex()
    validate_error(
        api_client.create_game(
            complex_["id"],
            {"complex_id": complex_["id"], "opponent_name": "Too Far", "home_away": "AWAY",
             "travel_radius_miles": 260, "game_datetime": "2026-02-12T19:00:00Z",
             "duration_units": 3, "split_squad": False},
            TEST_USERS["complex_director_headers"]),
        ApiErrorId.ERR_TRAVEL_RADIUS_EXCEEDED,
    )
    at_limit = api_client.create_game(
        complex_["id"],
        {"complex_id": complex_["id"], "opponent_name": "At The Limit", "home_away": "AWAY",
         "game_datetime": "2026-02-12T19:00:00Z", "travel_radius_miles": 250,
         "duration_units": 3, "split_squad": False},
        TEST_USERS["complex_director_headers"])
    body = validate_success(at_limit, 201)
    assert body["game_schedule_status"] == "DRAFT"
    assert body["game_interval_start"] == "2026-02-12T16:00:00.000Z"
    assert body["game_interval_end"] == "2026-02-12T22:00:00.000Z"


def test_confirming_a_participation_moves_it_and_bumps_the_game_version():
    """PRD 3.8: "On success the participation moves to `CONFIRMED` and the
    player's requirement score is recomputed"
    PRD 2.4: "`version` is an integer that begins at its initial value and
    increments by one on each mutation of that row."

    Design: Corner/state_machines/confirming_a_scheduled_participation_executes_the_declared_side_effects
    """
    set_test_clock()
    complex_ = create_complex()
    onboarded = cleared_player(complex_["id"])
    game = create_game(
        complex_["id"], opponent_name="Colorado Rockies", home_away="HOME",
        game_datetime="2026-02-12T19:00:00Z", duration_units=3)
    publish_game(game["id"])
    participation = add_participation(game["id"], onboarded["player"]["id"])
    version_before = fresh_game_version(game["id"])

    validate_success(confirm_participation(game["id"], participation["id"]))

    assert get_participation(participation["id"])["participation_status"] == "CONFIRMED"
    game_after = get_game(game["id"])
    assert game_after["version"] == version_before + 1
    assert game_after["game_schedule_status"] == "PUBLISHED"


def test_a_second_participation_confirm_with_a_stale_game_version_is_refused():
    """PRD 2.8: "Confirming a game participation must carry
    `expected_game_version` matching the game's current `version`. If the game
    has advanced since the client last read it — for instance because another
    participation on the same game was just confirmed — the confirmation is
    refused with `ERR_STALE_VERSION` at HTTP 412."

    Design: Corner/errors/stale_game_version_on_participation_confirm_returns_precondition_failed
    """
    set_test_clock()
    complex_ = create_complex()
    first = cleared_player(complex_["id"])
    second = cleared_player(complex_["id"])
    game = create_game(
        complex_["id"], opponent_name="Colorado Rockies", home_away="HOME",
        game_datetime="2026-02-12T19:00:00Z", duration_units=3)
    publish_game(game["id"])
    part_one = add_participation(game["id"], first["player"]["id"])
    part_two = add_participation(game["id"], second["player"]["id"])
    observed = fresh_game_version(game["id"])

    validate_success(confirm_participation(game["id"], part_one["id"], observed))
    validate_error(
        api_client.confirm_participation(
            game["id"], part_two["id"], observed, TEST_USERS["field_coordinator_headers"]),
        ApiErrorId.ERR_STALE_VERSION,
    )
    assert get_participation(part_two["id"])["participation_status"] == "SCHEDULED"


def test_a_cancelled_game_cannot_be_published():
    """PRD 3.8: "It may be cancelled from either `DRAFT` or `PUBLISHED` ...
    `CANCELLED` is terminal"

    Design: Corner/state_machines/closed_away_game_is_terminal_for_further_field_actions
    """
    set_test_clock()
    complex_ = create_complex()
    game = create_game(
        complex_["id"], opponent_name="Colorado Rockies", home_away="AWAY",
        game_datetime="2026-02-12T19:00:00Z", travel_radius_miles=180, duration_units=3)
    validate_success(api_client.cancel_game(game["id"], TEST_USERS["complex_director_headers"]))

    validate_error(
        api_client.publish_game(
            game["id"], fresh_game_version(game["id"]),
            TEST_USERS["complex_director_headers"]),
        ApiErrorId.ERR_INVALID_STATE,
    )
    assert get_game(game["id"])["game_schedule_status"] == "CANCELLED"


def test_gameday_packaging_is_refused_outside_the_six_hour_window():
    """PRD 3.8: "a `ComplexDirector` packages the roster only while the logical
    clock sits within the closed window from six hours before `game_datetime` to
    `game_datetime` itself ... A packaging attempt outside that window is refused
    with `ERR_OUTSIDE_WINDOW` (HTTP 422)."

    Design: Corner/endpoints/gameday_roster_packaging_only_works_inside_the_six_hour_window
    """
    set_test_clock()
    complex_ = create_complex()
    onboarded = cleared_player(complex_["id"])
    game = create_game(
        complex_["id"], opponent_name="Colorado Rockies", home_away="HOME",
        game_datetime="2026-02-12T19:00:00Z", duration_units=3)
    publish_game(game["id"])
    participation = add_participation(game["id"], onboarded["player"]["id"])
    validate_success(confirm_participation(game["id"], participation["id"]))

    validate_error(
        api_client.package_roster(game["id"], TEST_USERS["complex_director_headers"]),
        ApiErrorId.ERR_OUTSIDE_WINDOW,
    )
    assert get_participation(participation["id"])["participation_status"] == "CONFIRMED"


def test_gameday_packaging_inside_the_window_locks_confirmed_participations():
    """PRD 3.8: "Packaging drives every confirmed participation on the game to
    `LOCKED` and reports the count locked alongside the game's `gameday_status`."

    Design: Corner/endpoints/gameday_roster_packaging_only_works_inside_the_six_hour_window
    """
    set_test_clock()
    complex_ = create_complex()
    onboarded = cleared_player(complex_["id"])
    game = create_game(
        complex_["id"], opponent_name="Colorado Rockies", home_away="HOME",
        game_datetime="2026-02-12T19:00:00Z", duration_units=3)
    publish_game(game["id"])
    participation = add_participation(game["id"], onboarded["player"]["id"])
    validate_success(confirm_participation(game["id"], participation["id"]))

    set_test_clock("2026-02-12T14:00:00Z")
    payload = validate_success(api_client.package_roster(
        game["id"], TEST_USERS["complex_director_headers"]))
    assert payload["locked_count"] == 1
    assert get_participation(participation["id"])["participation_status"] == "LOCKED"