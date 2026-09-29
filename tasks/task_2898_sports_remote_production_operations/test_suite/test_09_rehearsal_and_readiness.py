"""Rehearsal, camera blocking and the two readiness figures.

Every test builds its own preconditions from an empty database with the logical
clock at its startup value, through the shared helpers in ``test_helpers``.
"""

from test_helpers import (
    assert_readiness,
    assert_status,
    validate_error,
    validate_paginated,
    validate_success,
)
from test_helpers.constants import REHEARSAL_START
from test_helpers.factories import (
    create_rehearsal_payload,
    rehearsal_outcome_payload,
    survey_review_payload,
)
from test_helpers.fixtures import (
    accept_call,
    book_path,
    create_approved_survey,
    create_prep,
    new_crew_member,
    new_data_feed,
    new_fiber_path,
    new_production,
    new_survey,
    offer_call,
    schedule_rehearsal,
    schedule_test,
    setup_provisioned_production,
    submit_survey,
)
from test_helpers.test_users import LEAGUE_OPERATIONS_ID

#: Two positions at 150 ft and 250 ft: 2.03 dB + 3.38 dB == 5.41 dB, 40 amps.
DIVERGENCE_PLOT = [
    {
        "label": "HIGH_HOME",
        "position_type": "HARD",
        "cable_run_feet": 150,
        "power_draw_amps": 20,
    },
    {
        "label": "LOW_FIRST",
        "position_type": "HANDHELD",
        "cable_run_feet": 250,
        "power_draw_amps": 20,
    },
]

#: Two positions at 150 ft and 600 ft: 2.03 dB + 8.10 dB == 10.13 dB exactly.
BUDGET_EDGE_PLOT = [
    {
        "label": "CAM-1",
        "position_type": "HARD",
        "cable_run_feet": 150,
        "power_draw_amps": 30,
    },
    {
        "label": "CAM-2",
        "position_type": "HANDHELD",
        "cable_run_feet": 600,
        "power_draw_amps": 30,
    },
]


def _setup_divergent_evidence(api):
    """An approved plot, a RESERVED primary booking, a PENDING prep and two
    calls of which exactly one has been accepted. No truck is assigned."""
    production = new_production(api)
    production_id = production["id"]
    survey = create_approved_survey(api, production_id, DIVERGENCE_PLOT)
    path = new_fiber_path(api)
    booking = book_path(api, production_id, path["id"])
    feed = new_data_feed(api)
    prep = create_prep(api, production_id, feed["id"])
    member_one = new_crew_member(api, full_name="Dana Reyes", position="TD")
    member_two = new_crew_member(api, full_name="Ellis Park", position="EIC")
    accepted = offer_call(api, production_id, member_one["id"])
    accepted = accept_call(api, accepted["id"], member_one["id"])
    offered = offer_call(api, production_id, member_two["id"])
    return {
        "production_id": production_id,
        "survey": survey,
        "booking": booking,
        "prep": prep,
        "accepted_call": accepted,
        "offered_call": offered,
    }


def test_preflight_reads_100_while_certified_reads_47_50_on_the_same_row(
    api, pm_headers
):
    """The two readiness variants disagree on one production in one response.

    PRD: "The two figures diverge widely on the same data, which is the whole point: for a production with an approved survey, one `RESERVED` primary booking, one `PENDING` preparation, and one `OFFERED` plus one `ACCEPTED` call against a `required_crew_positions` of 2, the preflight projection reads 100.00 while the certified figure reads 47.50."
    PRD: "The score is the sum of the four components, rounded half up to two decimal places."
    Design: Difficulty/dual_variant_calc/production_readiness_preflight_versus_certified_diverge
    """
    context = _setup_divergent_evidence(api)

    production = validate_success(api.get_production(context["production_id"], pm_headers))

    assert_readiness(production, preflight=100.00, certified=47.50)
    assert_status(production, "SURVEYED", "production stage")
    assert_status(context["booking"], "RESERVED", "booking status")
    assert_status(context["prep"], "PENDING", "prep status")
    assert_status(context["offered_call"], "OFFERED", "crew-call status")
    assert_status(context["accepted_call"], "ACCEPTED", "crew-call status")
    assert production["required_crew_positions"] == 2, (
        "a TIER_3 event demands 2 accepted crew calls"
    )
    assert float(context["survey"]["total_signal_loss_db"]) == 5.41, (
        "2.03 dB + 3.38 dB is the survey's loss budget"
    )


def test_test_scheduled_primary_and_pending_prep_credit_preflight_only(api, pm_headers):
    """A scheduled-but-unproven primary and an unvalidated prep score 85.00 forward
    and 40.00 chronologically.

    PRD: "Its transmission predicate holds when the production has a booking whose `booking_role` is `PRIMARY` and whose status is any of `RESERVED`, `TEST_SCHEDULED`, `CONFIRMED` or `PROMOTED`."
    PRD: "Its transmission predicate holds when the production has a `PRIMARY` booking in `CONFIRMED` or `PROMOTED` status."
    Design: Difficulty/dual_variant_calc/production_readiness_preflight_versus_certified_diverge
    """
    production = new_production(api)
    production_id = production["id"]
    create_approved_survey(api, production_id, DIVERGENCE_PLOT)
    path = new_fiber_path(api)
    booking = book_path(api, production_id, path["id"])
    booking = schedule_test(api, booking["id"])
    feed = new_data_feed(api)
    prep = create_prep(api, production_id, feed["id"])

    production = validate_success(api.get_production(production_id, pm_headers))

    assert_status(booking, "TEST_SCHEDULED", "booking status")
    assert_status(prep, "PENDING", "prep status")
    assert_readiness(production, preflight=85.00, certified=40.00)
    assert_status(production, "SURVEYED", "production stage")


def test_rehearsal_completion_refused_when_cleared_positions_fall_short(
    api, td_headers, pm_headers
):
    """Clearing fewer positions than the approved plot holds is refused even with
    both signoffs true.

    PRD: "Then all three observations must be affirmative together: `camera_blocking_positions_cleared` must equal the `camera_position_count` of the production's `APPROVED` survey exactly — not merely reach it — and both `venue_signoff` and `league_ops_signoff` must be true."
    PRD: "Any shortfall in any of the three is refused with `ERR_REHEARSAL_SIGNOFF_INCOMPLETE`."
    Design: Difficulty/cross_entity_state_dependency/rehearsal_completion_depends_on_approved_survey_position_count
    """
    context = setup_provisioned_production(api)
    production_id = context["production"]["id"]
    assert context["survey"]["camera_position_count"] == 2, (
        "the approved plot carries two camera positions"
    )
    rehearsal = schedule_rehearsal(api, production_id)

    response = api.record_rehearsal_outcome(
        rehearsal["id"],
        rehearsal_outcome_payload(
            "COMPLETED",
            camera_blocking_positions_cleared=1,
            venue_signoff=True,
            league_ops_signoff=True,
        ),
        td_headers,
    )

    validate_error(response, "ERR_REHEARSAL_SIGNOFF_INCOMPLETE")
    refused = validate_success(api.get_rehearsal(rehearsal["id"], td_headers))
    assert_status(refused, "SCHEDULED", "rehearsal status")
    production = validate_success(api.get_production(production_id, pm_headers))
    assert_status(production, "PROVISIONED", "production stage")
    assert_readiness(production, certified=85.00)


def test_rehearsal_completion_accepted_when_cleared_positions_equal_the_plot(
    api, td_headers, pm_headers
):
    """Clearing exactly the approved plot's position count promotes the production.

    PRD: "Then all three observations must be affirmative together: `camera_blocking_positions_cleared` must equal the `camera_position_count` of the production's `APPROVED` survey exactly — not merely reach it — and both `venue_signoff` and `league_ops_signoff` must be true."
    PRD: "On success the session moves `SCHEDULED → COMPLETED`, `readiness_hold` is cleared to false on every show execution of that production still in `PRE_SHOW`, and the production is promoted `PROVISIONED → REHEARSED` — specifically, the derivation of §2.9 is run first and the promotion to `REHEARSED` is applied when that derivation leaves the production at `PROVISIONED`, so a production whose provisioning conditions broke in the meantime is not promoted onto evidence it no longer has."
    Design: Difficulty/cross_entity_state_dependency/rehearsal_completion_depends_on_approved_survey_position_count
    """
    context = setup_provisioned_production(api)
    production_id = context["production"]["id"]
    cleared = context["survey"]["camera_position_count"]
    rehearsal = schedule_rehearsal(api, production_id)

    response = api.record_rehearsal_outcome(
        rehearsal["id"],
        rehearsal_outcome_payload(
            "COMPLETED",
            camera_blocking_positions_cleared=cleared,
            venue_signoff=True,
            league_ops_signoff=True,
        ),
        td_headers,
    )

    completed = validate_success(response)
    assert_status(completed, "COMPLETED", "rehearsal status")
    assert completed["camera_blocking_positions_cleared"] == cleared, (
        "the cleared count is recorded on the session"
    )
    production = validate_success(api.get_production(production_id, pm_headers))
    assert_status(production, "REHEARSED", "production stage")
    assert_readiness(production, certified=85.00)


def test_aborted_outcome_records_the_session_and_moves_nothing_else(
    api, td_headers, pm_headers
):
    """An abort writes the session's terminal state and leaves the production alone.

    PRD: "On success the session moves `SCHEDULED → ABORTED` and the observations supplied with it are recorded — and nothing else happens: the production's stage is left exactly where it stood, and `readiness_hold` is neither set nor cleared on any show execution."
    PRD: "There is no signoff gate on an abort, because an aborted session is precisely the case where signoff could not be obtained."
    Design: Corner/state_machines/rehearsal_aborted_outcome_leaves_production_stage_untouched
    """
    context = setup_provisioned_production(api)
    production_id = context["production"]["id"]
    rehearsal = schedule_rehearsal(api, production_id)
    assert_status(rehearsal, "SCHEDULED", "rehearsal status")

    response = api.record_rehearsal_outcome(
        rehearsal["id"],
        rehearsal_outcome_payload(
            "ABORTED",
            camera_blocking_positions_cleared=0,
            venue_signoff=False,
            league_ops_signoff=False,
            outcome_notes="venue lost the compound power feed",
        ),
        td_headers,
    )

    aborted = validate_success(response)
    assert_status(aborted, "ABORTED", "rehearsal status")
    assert aborted["outcome_notes"] == "venue lost the compound power feed", (
        "the observations supplied with the abort are recorded"
    )
    production = validate_success(api.get_production(production_id, pm_headers))
    assert_status(production, "PROVISIONED", "production stage")
    assert_readiness(production, certified=85.00)


def test_aborted_session_is_terminal_and_listed_under_its_status(
    api, td_headers, pm_headers
):
    """An aborted session cannot be re-outcomed and shows up under the status filter.

    PRD: "The session must still be `SCHEDULED`, or `ERR_REHEARSAL_STATE_INVALID`."
    PRD: "A production's sessions can be listed with an optional `status` filter, which is how a crew sees the ones a readiness cascade abandoned."
    Design: Corner/state_machines/rehearsal_aborted_outcome_leaves_production_stage_untouched
    """
    context = setup_provisioned_production(api)
    production_id = context["production"]["id"]
    rehearsal = schedule_rehearsal(api, production_id)
    validate_success(
        api.record_rehearsal_outcome(
            rehearsal["id"],
            rehearsal_outcome_payload(
                "ABORTED",
                camera_blocking_positions_cleared=0,
                venue_signoff=False,
                league_ops_signoff=False,
            ),
            td_headers,
        )
    )

    response = api.record_rehearsal_outcome(
        rehearsal["id"],
        rehearsal_outcome_payload(
            "ABORTED",
            camera_blocking_positions_cleared=0,
            venue_signoff=False,
            league_ops_signoff=False,
        ),
        td_headers,
    )

    validate_error(response, "ERR_REHEARSAL_STATE_INVALID")
    rows, meta = validate_paginated(
        api.list_production_rehearsals(
            production_id, pm_headers, params={"status": "ABORTED"}
        )
    )
    assert meta["total_count"] == 1, "the aborted session is listed under its status"
    assert rows[0]["id"] == rehearsal["id"]
    production = validate_success(api.get_production(production_id, pm_headers))
    assert_status(production, "PROVISIONED", "production stage")


def test_rehearsal_window_rung_answers_before_the_production_stage_rung(
    api, td_headers, pm_headers
):
    """On one PLANNED production two starts pick two different rungs of the ladder.

    PRD: "A `TechnicalDirector` schedules the session against a `production_id` with a `scheduled_start_utc`, and two things must be true for the session to be booked at all: the production must already stand at `PROVISIONED` or `REHEARSED`, or the request is refused with `ERR_PRODUCTION_STATE_INVALID`, and the rehearsal must be scheduled strictly **before** the production's own `scheduled_start_utc` — a rehearsal at or after air time is refused with `ERR_INVALID_TIME_WINDOW`."
    PRD: "Evaluation proceeds strictly down the ladder and stops at the first violation, so a request that breaks several rules is always reported at its earliest rung."
    Design: Corner/validations/rehearsal_window_check_precedes_the_production_stage_check
    """
    production = new_production(api)
    production_id = production["id"]
    assert_status(production, "PLANNED", "production stage")

    at_air_time = api.create_rehearsal(
        create_rehearsal_payload(
            production_id, scheduled_start_utc=production["scheduled_start_utc"]
        ),
        td_headers,
    )
    before_air_time = api.create_rehearsal(
        create_rehearsal_payload(production_id, scheduled_start_utc=REHEARSAL_START),
        td_headers,
    )

    validate_error(at_air_time, "ERR_INVALID_TIME_WINDOW")
    validate_error(before_air_time, "ERR_PRODUCTION_STATE_INVALID")
    _rows, meta = validate_paginated(
        api.list_production_rehearsals(production_id, pm_headers)
    )
    assert meta["total_count"] == 0, "neither refused request created a session"


def test_survey_approval_exposes_its_production_cascade_in_the_same_cycle(
    api, td_headers, lo_headers
):
    """The review response is already APPROVED and the very next production read
    already shows the derived stage and both readiness figures.

    PRD: "An approval moves the survey `SUBMITTED → APPROVED` and drives the production `PLANNED → SURVEYED` through the derivation, which — if a truck, a confirmed primary transport and enough validated preps are already in place — can carry the production straight on to `PROVISIONED` in the same request."
    PRD: "It is **derived**, synchronously, at the end of every request that changed any of a production's gates — a truck assignment, a primary booking's status, a prep's status, a crew call's status, a survey's status, or a rehearsal outcome."
    Design: Corner/consistency_model/gating_writes_expose_their_cascade_in_the_same_response_cycle
    """
    production = new_production(api)
    production_id = production["id"]
    version_before = production["version"]
    survey = new_survey(api, production_id, BUDGET_EDGE_PLOT, headers=td_headers)
    submit_survey(api, survey["id"], td_headers)

    reviewed = validate_success(
        api.review_venue_survey(
            survey["id"], survey_review_payload("APPROVE"), lo_headers
        )
    )
    after = validate_success(api.get_production(production_id, lo_headers))

    assert_status(reviewed, "APPROVED", "survey status")
    assert reviewed["reviewed_by_user_id"] == LEAGUE_OPERATIONS_ID, (
        "the review response already carries the reviewer's operator identifier"
    )
    assert_status(after, "SURVEYED", "production stage")
    assert_readiness(after, preflight=40.00, certified=40.00)
    assert after["version"] > version_before, (
        "the cascade that changed the production was committed with the review"
    )
    rows, meta = validate_paginated(
        api.list_production_venue_surveys(production_id, lo_headers)
    )
    assert meta["total_count"] == 1
    assert_status(rows[0], "APPROVED", "survey status")
    assert rows[0]["camera_position_count"] == 2
    assert float(rows[0]["total_signal_loss_db"]) == 10.13, (
        "2.03 dB + 8.10 dB sits exactly on the 10.13 dB budget"
    )
