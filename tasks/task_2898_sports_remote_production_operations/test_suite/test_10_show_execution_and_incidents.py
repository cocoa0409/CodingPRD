"""Show execution: the two state dimensions, the incident log and its thresholds.

Every test builds its own preconditions from an empty database with the logical
clock at its startup value, through the shared helpers in ``test_helpers``.
"""

from test_helpers import (
    assert_instant_equals,
    assert_path_ledger,
    assert_readiness,
    assert_show_execution,
    assert_status,
    validate_error,
    validate_paginated,
    validate_success,
)
from test_helpers.constants import AIR_CLOCK, UNKNOWN_UUIDS
from test_helpers.factories import (
    create_incident_payload,
    create_show_execution_payload,
)
from test_helpers.fixtures import (
    book_path,
    confirm_booking,
    create_approved_survey,
    log_incident,
    new_fiber_path,
    new_production,
    read_booking,
    read_path,
    set_air_status,
    set_clock,
    setup_provisioned_production,
    setup_show_on_air,
    setup_show_pre_show,
)


def _setup_show_on_air_with_proven_backup(api):
    """A live show whose production also holds a CONFIRMED BACKUP booking on a
    second fiber circuit, so a path loss has somewhere to fail over to."""
    context = setup_show_pre_show(api)
    production_id = context["production"]["id"]
    context["backup_path"] = new_fiber_path(
        api, path_code="FIB-B", carrier_code="CARR2"
    )
    backup = book_path(
        api,
        production_id,
        context["backup_path"]["id"],
        booking_role="BACKUP",
        requested_mbps=100,
    )
    context["backup"] = confirm_booking(api, backup["id"])
    set_clock(api, AIR_CLOCK)
    context["show"] = set_air_status(api, context["show"]["id"], "ON_AIR")
    return context


def test_extended_play_loop_requires_a_logged_extended_play_incident(api, td_headers):
    """The backward air edge is guarded by the accumulator, not by the air status alone.

    PRD: "Moving `ON_AIR → IN_EXTENDED_PLAY` requires that the show currently be `ON_AIR` **and** that `extended_play_minutes` already be at least 1, meaning at least one extended-play incident has been logged; entering extended play with no extended-play minutes on the record is refused with `ERR_SHOW_STATE_INVALID`."
    PRD: "Extended play can end and normal play resume: moving `IN_EXTENDED_PLAY → ON_AIR` requires only that the show currently be `IN_EXTENDED_PLAY`, and it explicitly does **not** re-stamp `on_air_at_utc`, so the show's total air time is measured from the original open of the microphone however many times the show swings in and out of extended play."
    Design: Difficulty/non_linear_state_machine/show_execution_air_and_signal_dimensions_advance_independently
    """
    context = setup_show_on_air(api)
    show_id = context["show"]["id"]
    assert context["show"]["extended_play_minutes"] == 0, (
        "the show opens with no extended-play minutes on the record"
    )

    too_early = api.set_air_status(show_id, "IN_EXTENDED_PLAY", td_headers)
    validate_error(too_early, "ERR_SHOW_STATE_INVALID")

    log_incident(
        api,
        show_id,
        kind="EXTENDED_PLAY",
        started_at_utc="2026-08-15T21:55:00Z",
        duration_minutes=5,
        severity="MINOR",
    )
    in_extended_play = validate_success(
        api.set_air_status(show_id, "IN_EXTENDED_PLAY", td_headers)
    )
    resumed = validate_success(api.set_air_status(show_id, "ON_AIR", td_headers))

    assert_status(in_extended_play, "IN_EXTENDED_PLAY", "air status", "air_status")
    assert_status(in_extended_play, "NOMINAL", "signal status", "signal_status")
    assert in_extended_play["extended_play_minutes"] == 5, (
        "the extended-play incident fed its own accumulator"
    )
    assert_status(resumed, "ON_AIR", "air status", "air_status")
    assert_instant_equals(resumed["on_air_at_utc"], AIR_CLOCK, "on_air_at_utc")
    assert resumed["off_air_at_utc"] is None, "resuming never stamps the off-air instant"


def test_path_loss_moves_the_signal_dimension_and_leaves_the_air_dimension(
    api, td_headers
):
    """A path loss swings the signal dimension to ON_BACKUP while the air dimension
    stays exactly where it stood, and returning to ON_AIR never resets it.

    PRD: "The record tracks **two independent state dimensions** simultaneously."
    PRD: "The show's `signal_status` moves `NOMINAL → ON_BACKUP` and the show stays on air."
    Design: Difficulty/non_linear_state_machine/show_execution_air_and_signal_dimensions_advance_independently
    """
    context = _setup_show_on_air_with_proven_backup(api)
    show_id = context["show"]["id"]
    log_incident(
        api,
        show_id,
        kind="EXTENDED_PLAY",
        started_at_utc="2026-08-15T21:55:00Z",
        duration_minutes=5,
        severity="MINOR",
    )
    set_air_status(api, show_id, "IN_EXTENDED_PLAY")

    log_incident(
        api,
        show_id,
        kind="PATH_LOSS",
        started_at_utc="2026-08-15T22:00:00Z",
        duration_minutes=6,
        severity="MAJOR",
    )

    after_loss = validate_success(api.get_show_execution(show_id, td_headers))
    assert_show_execution(after_loss)
    assert_status(after_loss, "IN_EXTENDED_PLAY", "air status", "air_status")
    assert_status(after_loss, "ON_BACKUP", "signal status", "signal_status")
    assert after_loss["technical_downtime_minutes"] == 6, (
        "a path loss is technical downtime"
    )
    assert_status(
        read_booking(api, context["booking"]["id"]), "FAILED_OVER", "booking status"
    )
    assert_status(read_booking(api, context["backup"]["id"]), "PROMOTED", "booking status")
    assert_path_ledger(read_path(api, context["path"]["id"]), 0, 0)
    assert_path_ledger(read_path(api, context["backup_path"]["id"]), 100, 1)

    resumed = validate_success(api.set_air_status(show_id, "ON_AIR", td_headers))
    assert_status(resumed, "ON_AIR", "air status", "air_status")
    assert_status(resumed, "ON_BACKUP", "signal status", "signal_status")
    production = validate_success(
        api.get_production(context["production"]["id"], td_headers)
    )
    assert_status(production, "ON_AIR", "production stage")


def test_show_creation_refused_while_the_production_is_planned_or_surveyed(
    api, pm_headers
):
    """The identical creation body is refused at PLANNED and again at SURVEYED.

    PRD: "The show record is opened by a `ProductionManager` against a `production_id`, and only while the production stands at `PROVISIONED` or `REHEARSED`; anything else is `ERR_PRODUCTION_STATE_INVALID`."
    Design: Difficulty/cross_entity_state_dependency/show_execution_creation_depends_on_production_stage
    """
    production = new_production(api)
    production_id = production["id"]
    payload = create_show_execution_payload(production_id)
    assert_status(production, "PLANNED", "production stage")

    at_planned = api.create_show_execution(payload, pm_headers)
    validate_error(at_planned, "ERR_PRODUCTION_STATE_INVALID")
    _rows, meta = validate_paginated(
        api.list_production_show_executions(production_id, pm_headers)
    )
    assert meta["total_count"] == 0, "the refusal at PLANNED created no show record"

    create_approved_survey(api, production_id)
    surveyed = validate_success(api.get_production(production_id, pm_headers))
    assert_status(surveyed, "SURVEYED", "production stage")

    at_surveyed = api.create_show_execution(payload, pm_headers)
    validate_error(at_surveyed, "ERR_PRODUCTION_STATE_INVALID")
    _rows, meta = validate_paginated(
        api.list_production_show_executions(production_id, pm_headers)
    )
    assert meta["total_count"] == 0, "the refusal at SURVEYED created no show record"


def test_show_creation_accepted_once_the_production_is_provisioned(api, pm_headers):
    """At PROVISIONED the same body is accepted and both dimensions open at their
    initial values.

    PRD: "The show record is opened by a `ProductionManager` against a `production_id`, and only while the production stands at `PROVISIONED` or `REHEARSED`; anything else is `ERR_PRODUCTION_STATE_INVALID`."
    PRD: "A new record opens at `PRE_SHOW` and `NOMINAL` with `readiness_hold` false, all three contingency accumulators (`weather_hold_minutes`, `extended_play_minutes` and `technical_downtime_minutes`) at 0, `air_minutes_total` at 0, and both `on_air_at_utc` and `off_air_at_utc` null."
    Design: Difficulty/cross_entity_state_dependency/show_execution_creation_depends_on_production_stage
    """
    context = setup_provisioned_production(api)
    production_id = context["production"]["id"]

    response = api.create_show_execution(
        create_show_execution_payload(production_id), pm_headers
    )

    show = validate_success(response, 201)
    assert_show_execution(show)
    assert show["production_id"] == production_id
    assert_status(show, "PRE_SHOW", "air status", "air_status")
    assert_status(show, "NOMINAL", "signal status", "signal_status")
    assert show["readiness_hold"] is False
    assert show["weather_hold_minutes"] == 0
    assert show["extended_play_minutes"] == 0
    assert show["technical_downtime_minutes"] == 0
    assert show["air_minutes_total"] == 0
    assert show["on_air_at_utc"] is None
    assert show["off_air_at_utc"] is None
    production = validate_success(api.get_production(production_id, pm_headers))
    assert_status(production, "PROVISIONED", "production stage")
    assert_readiness(production, certified=85.00)


def test_incident_under_an_unknown_show_reports_the_parent_not_found(api, td_headers):
    """The parent segment is resolved before anything about the incident is judged.

    PRD: "If the parent named by the first path segment does not exist, the response is that parent's not-found error — `ERR_PRODUCTION_NOT_FOUND`, `ERR_SURVEY_NOT_FOUND` or `ERR_SHOW_NOT_FOUND` as appropriate — and the child segment is never examined."
    PRD: "A `TECHNICAL_FAILURE`, an `EXTENDED_PLAY` or a `PATH_LOSS` may only be logged while the show is `ON_AIR` or `IN_EXTENDED_PLAY`; logging one against a `PRE_SHOW` or `OFF_AIR` show is refused with `ERR_SHOW_STATE_INVALID`."
    Design: Corner/entities/incident_creation_under_unknown_show_returns_not_found
    """
    payload = create_incident_payload(
        kind="TECHNICAL_FAILURE",
        started_at_utc=AIR_CLOCK,
        duration_minutes=4,
        severity="MAJOR",
    )

    unknown = api.create_incident(UNKNOWN_UUIDS["show"], payload, td_headers)

    validate_error(unknown, "ERR_SHOW_NOT_FOUND")
    context = setup_show_pre_show(api)
    existing = api.create_incident(context["show"]["id"], payload, td_headers)
    validate_error(existing, "ERR_SHOW_STATE_INVALID")


def test_going_on_air_exactly_at_the_venue_curfew_is_refused(api, td_headers, pm_headers):
    """The curfew rung uses a strictly-before comparison, so the curfew instant itself
    is already too late.

    PRD: "Finally the building's curfew is checked: the logical clock must stand strictly before the production's `venue_curfew_utc`, and a clock at or after curfew is refused with `ERR_VENUE_CURFEW_EXCEEDED`."
    PRD: "It stamps `off_air_at_utc` with the logical clock and recomputes `air_minutes_total`, which is the number of whole minutes between `on_air_at_utc` and `off_air_at_utc` and which reads 0 for as long as either instant is null."
    Design: Corner/validations/venue_curfew_blocks_going_on_air_at_the_curfew_instant
    """
    context = setup_show_pre_show(api)
    show_id = context["show"]["id"]
    curfew = context["production"]["venue_curfew_utc"]
    assert context["show"]["readiness_hold"] is False
    assert_readiness(context["production"], certified=100.00)
    set_clock(api, curfew)

    response = api.set_air_status(show_id, "ON_AIR", td_headers)

    validate_error(response, "ERR_VENUE_CURFEW_EXCEEDED")
    show = validate_success(api.get_show_execution(show_id, td_headers))
    assert_status(show, "PRE_SHOW", "air status", "air_status")
    assert_status(show, "NOMINAL", "signal status", "signal_status")
    assert show["on_air_at_utc"] is None, "a refused open never stamps the air instant"
    assert show["air_minutes_total"] == 0
    production = validate_success(api.get_production(context["production"]["id"], pm_headers))
    assert_status(production, "REHEARSED", "production stage")


def test_cumulative_technical_downtime_reaching_20_minutes_forces_the_show_off_air(
    api, td_headers, pm_headers
):
    """Weather minutes never count towards the downtime trigger, and the third
    technical incident crosses the threshold on the sum, not on its own length.

    PRD: "Each kind feeds a different accumulator by exactly its `duration_minutes`."
    PRD: "Once `technical_downtime_minutes` stands at or above **20 minutes**, and the show is currently `ON_AIR` or `IN_EXTENDED_PLAY`, the show is forced off air: `air_status` becomes `OFF_AIR`, `off_air_at_utc` is stamped with the logical clock, and `air_minutes_total` is recomputed."
    PRD: "The production's stage is deliberately left at `ON_AIR` so that the wrap remains available to the `ProductionManager`."
    Design: Corner/cross_cutting_complexity_layers/cumulative_technical_downtime_forces_the_show_off_air_at_the_threshold
    """
    context = setup_show_on_air(api)
    show_id = context["show"]["id"]
    forced_off_air_clock = "2026-08-15T20:00:00Z"

    log_incident(
        api,
        show_id,
        kind="WEATHER_HOLD",
        started_at_utc="2026-08-15T18:05:00Z",
        duration_minutes=5,
        severity="MINOR",
    )
    after_weather = validate_success(api.get_show_execution(show_id, td_headers))
    assert after_weather["weather_hold_minutes"] == 5
    assert after_weather["technical_downtime_minutes"] == 0, (
        "a rain delay is not technical downtime"
    )
    assert_status(after_weather, "ON_AIR", "air status", "air_status")

    log_incident(
        api,
        show_id,
        kind="TECHNICAL_FAILURE",
        started_at_utc="2026-08-15T18:30:00Z",
        duration_minutes=12,
        severity="MAJOR",
    )
    below = validate_success(api.get_show_execution(show_id, td_headers))
    assert below["technical_downtime_minutes"] == 12
    assert_status(below, "ON_AIR", "air status", "air_status")
    assert below["off_air_at_utc"] is None, "12 minutes is below the threshold"

    set_clock(api, forced_off_air_clock)
    log_incident(
        api,
        show_id,
        kind="TECHNICAL_FAILURE",
        started_at_utc="2026-08-15T19:50:00Z",
        duration_minutes=8,
        severity="CRITICAL",
    )

    forced = validate_success(api.get_show_execution(show_id, td_headers))
    assert forced["technical_downtime_minutes"] == 20, "12 plus 8 reaches the threshold"
    assert_status(forced, "OFF_AIR", "air status", "air_status")
    assert_instant_equals(forced["off_air_at_utc"], forced_off_air_clock, "off_air_at_utc")
    assert forced["air_minutes_total"] == 120, (
        "18:00 to 20:00 is 120 whole minutes on air"
    )
    production = validate_success(api.get_production(context["production"]["id"], pm_headers))
    assert_status(production, "ON_AIR", "production stage")

    further = api.create_incident(
        show_id,
        create_incident_payload(
            kind="TECHNICAL_FAILURE",
            started_at_utc=forced_off_air_clock,
            duration_minutes=3,
            severity="MAJOR",
        ),
        td_headers,
    )
    validate_error(further, "ERR_SHOW_STATE_INVALID")
    unchanged = validate_success(api.get_show_execution(show_id, td_headers))
    assert unchanged["technical_downtime_minutes"] == 20, (
        "the refused incident was never folded into the accumulator"
    )
    _rows, meta = validate_paginated(api.list_incidents(show_id, td_headers))
    assert meta["total_count"] == 3, "three incidents were accepted in all"
    _rows, technical_meta = validate_paginated(
        api.list_incidents(show_id, td_headers, params={"kind": "TECHNICAL_FAILURE"})
    )
    assert technical_meta["total_count"] == 2
