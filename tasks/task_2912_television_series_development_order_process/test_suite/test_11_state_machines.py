"""Transitions, self-loops, terminal states and the bubbling that follows them.

Each test drives one edge of one state machine and then reads back every row the
contract says that edge touches - the parent project, the funding slate, the writer's
desk - so a transition that fires without its side effects, or fires with too many,
is caught in the same test.
"""

from prd_bench_local_runner.testing import (
    validate_error,
    validate_paginated,
    validate_success,
)
from test_helpers import api_errors as e
from test_helpers import assertions as a
from test_helpers import factories as f
from test_helpers import fixtures as fx
from test_helpers.constants import (
    CLOCK_STARTUP_DEFAULT_STAMP,
    COLLAPSED_REASON_CASTING,
    COMMITTEE_FINANCE,
    CONTINGENCY_CASTING,
    CONTINGENCY_FAILED,
    CONTINGENCY_LOCATION,
    CONTINGENCY_PENDING,
    CONTINGENCY_SATISFIED,
    CONTINGENCY_WAIVED,
    DEAL_CUT_OFF,
    DEAL_EXECUTED,
    DECISION_APPROVED,
    DECISION_PENDING,
    DECISION_REJECTED,
    DEV_ACTIVE_DEVELOPMENT,
    DEV_PILOT_DELIVERED,
    DEV_PILOT_ORDERED,
    DEV_SCRIPT_COMPLETE,
    GL_OPEN,
    GL_REJECTED,
    GL_SUPERSEDED,
    PITCH_COVERED,
    PITCH_PASSED,
    PITCH_SUBMITTED,
    POSTURE_OPEN,
    PRODUCTION_COLLAPSED,
    PRODUCTION_GREEN_TO_SHOOT,
    RECOMMENDATION_ADVANCE,
    RECOMMENDATION_PASS,
    STEP_ACCEPTED,
    STEP_CUT_OFF,
    STEP_EXERCISED,
    STEP_PENDING,
    STEP_POLISH,
    STEP_REVISION,
    STEP_STORY,
    TIER_PROBATION,
)
from test_helpers.fixtures import build_scenario
from test_helpers.test_users import (
    USER_EXEC_CREATIVE_1,
    USER_FINANCE_1,
    agency_rep_headers,
    business_affairs_headers,
    development_exec_headers,
    finance_controller_headers,
    research_analyst_headers,
)

TWO_STEP_LADDER = {
    "steps": [f.step_spec(STEP_STORY, 3000000), f.step_spec(STEP_POLISH, 1000000)],
    "guaranteed_step_count": 1,
}
OPTIONAL_REVISION_LADDER = {
    "steps": [f.step_spec(STEP_STORY, 3000000), f.step_spec(STEP_REVISION, 2000000)],
    "guaranteed_step_count": 1,
}
DEEP_WATER = {
    "title": "Deep Water",
    "logline": "A salvage diver finds a submarine that should not exist.",
    "packaging_elements": [],
    "underlying_ip_key": "IP-DEEP-WATER",
}


def test_a_wrap_filed_before_the_shoot_window_closes_is_refused(api):
    """The clock still reads 2026-08-01 while the shoot runs to 2026-09-25.

    PRD 3.5: "It additionally requires that the logical clock's current date be on
    or after the pilot's `shoot_end_date` - a wrap filed while the shoot window is
    still running is refused with `ERR_SHOOT_WINDOW_NOT_ELAPSED`."

    Design: Corner/state_machines/pilot_order_wrap_before_the_shoot_end_date_returns_shoot_window_not_elapsed
    """
    ctx = build_scenario(api, "green_to_shoot")

    refused = api.wrap_pilot(ctx.pilot_order_id, development_exec_headers())
    validate_error(refused, e.ERR_SHOOT_WINDOW_NOT_ELAPSED, 422)

    pilot = validate_success(
        api.get_pilot_order(ctx.pilot_order_id, development_exec_headers())
    )
    assert pilot["production_status"] == PRODUCTION_GREEN_TO_SHOOT

    project = validate_success(api.get_project(ctx.project_id, business_affairs_headers()))
    assert project["dev_status"] == DEV_PILOT_ORDERED


def test_a_second_abandonment_is_refused_and_never_re_freezes_the_write_off(api):
    """ABANDONED is terminal, so the write-off is not doubled on the slate.

    PRD 3.9: "from `SERIES_ORDERED` or from `ABANDONED` it is refused with
    `ERR_INVALID_PROJECT_STATE`." and "`writeoff_cents` is never recomputed after
    this instant."

    Design: Corner/state_machines/abandoning_an_already_abandoned_project_returns_invalid_project_state
    """
    ctx = fx.abandoned_project(api, "deal")

    refused = api.abandon_project(
        ctx.project_id, f.abandon_payload("second attempt"), development_exec_headers()
    )
    validate_error(refused, e.ERR_INVALID_PROJECT_STATE, 409)

    project = validate_success(api.get_project(ctx.project_id, business_affairs_headers()))
    assert project["abandon_reason"] == "showrunner unavailable", (
        "the refused call must not overwrite the recorded reason"
    )
    a.assert_cents(project["writeoff_cents"], 4375000, "writeoff_cents")

    slate = validate_success(api.get_slate(ctx.slate_id, business_affairs_headers()))
    a.assert_slate_dollar_ledger(slate, writeoff=4375000, available=395625000)


def test_a_passed_pitch_can_never_be_advanced(api):
    """A CLEAR clearance on file does not rescue a pitch the network passed on.

    PRD 3.2: "A recommendation of `PASS` moves the pitch to `PASSED` from either
    `SUBMITTED` or `COVERED`, and `PASSED` is terminal: a passed pitch can never be
    re-covered and can never be advanced."

    Design: Corner/state_machines/a_passed_pitch_cannot_be_advanced_from_its_terminal_state
    """
    ctx = build_scenario(api, "pitch")
    fx.file_rights_check(api, ctx.pitch_id)
    fx.record_coverage(
        api, ctx.pitch_id, {"coverage_score": 41.0, "recommendation": RECOMMENDATION_PASS}
    )

    refused = api.advance_pitch(ctx.pitch_id, development_exec_headers())
    validate_error(refused, e.ERR_INVALID_PITCH_STATE, 409)

    pitch = validate_success(api.get_pitch(ctx.pitch_id, development_exec_headers()))
    assert pitch["status"] == PITCH_PASSED
    assert pitch["recommendation"] == RECOMMENDATION_PASS
    a.assert_score(pitch["coverage_score"], 41.0, "coverage_score")
    assert pitch["coverage_round"] == 1

    rows, meta = validate_paginated(
        api.list_projects(
            business_affairs_headers(),
            {"pitch_id": ctx.pitch_id, "limit": 10, "offset": 0},
        )
    )
    assert rows == [], "the refused advance created no development project"
    a.assert_pagination_meta(meta, total_count=0)


def test_a_pass_gives_a_probation_agency_its_single_slot_back(api):
    """The probation ceiling of 1 blocks the second pitch until the first is passed on.

    PRD 3.1: "An agency on `PROBATION` is cut to a single submission per season
    regardless of what its baseline says - the probation ceiling is 1." and "A
    pitch the network has passed on is forgiven: a `PASSED` pitch stops counting
    immediately, which frees a slot the moment coverage is recorded."

    Design: Corner/state_machines/coverage_pass_frees_the_probation_agencys_only_submission_slot
    """
    ctx = build_scenario(api, "pitch", agency={"relationship_tier": TIER_PROBATION})

    blocked = api.create_pitch(
        f.pitch_payload(ctx.agency_id, ctx.slate_id, dict(DEEP_WATER)),
        agency_rep_headers(ctx.agency_id),
    )
    validate_error(blocked, e.ERR_AGENCY_SUBMISSION_CAP_REACHED, 422)

    passed = validate_success(
        api.record_coverage(
            ctx.pitch_id,
            f.coverage_payload(38.0, RECOMMENDATION_PASS),
            development_exec_headers(),
        )
    )
    assert passed["status"] == PITCH_PASSED
    assert passed["recommendation"] == RECOMMENDATION_PASS

    accepted = validate_success(
        api.create_pitch(
            f.pitch_payload(ctx.agency_id, ctx.slate_id, dict(DEEP_WATER)),
            agency_rep_headers(ctx.agency_id),
        ),
        201,
    )
    assert accepted["title"] == "Deep Water"
    assert accepted["status"] == PITCH_SUBMITTED

    agency = validate_success(api.get_agency(ctx.agency_id, business_affairs_headers()))
    assert agency["effective_submission_cap"] == 1
    assert agency["submissions_used_count"] == 1, (
        "only the newly submitted pitch counts; the passed one is forgiven"
    )


def test_an_exercise_at_one_day_past_the_option_expiry_is_refused(api):
    """A 30-day option period anchored at execution puts step 1's expiry at 2026-08-31.

    PRD 3.4: "The logical clock's current instant must be strictly before the
    step's `option_expires_at`; an exercise at exactly `option_expires_at` is one
    instant too late and is refused with `ERR_OPTION_PERIOD_EXPIRED`."

    Design: Corner/state_machines/deal_step_exercise_after_the_option_period_expires_returns_option_period_expired
    """
    ctx = build_scenario(api, "deal", deal={"option_period_days": 30})
    fx.set_clock(api, "2026-09-01T00:00:00Z")

    refused = api.exercise_step(
        ctx.deal_id, ctx.step_ids[0], business_affairs_headers()
    )
    validate_error(refused, e.ERR_OPTION_PERIOD_EXPIRED, 422)

    steps = validate_success(api.list_deal_steps(ctx.deal_id, business_affairs_headers()))
    step_one = a.find_step(steps, 1)
    a.assert_step(
        step_one, status=STEP_PENDING, option_expires_at="2026-08-31T00:00:00.000Z"
    )
    assert step_one["exercised_at"] is None

    writer = validate_success(api.get_writer(ctx.writer_id, business_affairs_headers()))
    assert writer["open_step_count"] == 0


def test_a_cutoff_waits_for_the_guaranteed_step_and_then_releases_nothing(api):
    """The optional POLISH step was never exercised, so cutting it moves no money.

    PRD 3.4: "the whole operation is refused with `ERR_GUARANTEED_STEP_NOT_CUTTABLE`
    while any step at or below `guaranteed_step_count` is still `PENDING`." and
    "cutting an optional step that was still `PENDING` moves no money at all,
    because an unexercised option was never encumbered in the first place."

    Design: Corner/state_machines/cutoff_blocked_while_the_guaranteed_step_is_pending_then_releases_nothing_after_acceptance
    """
    ctx = build_scenario(api, "deal", deal=dict(TWO_STEP_LADDER))

    too_early = api.cutoff_deal(
        ctx.deal_id,
        f.cutoff_payload("creative direction changed"),
        business_affairs_headers(),
    )
    validate_error(too_early, e.ERR_GUARANTEED_STEP_NOT_CUTTABLE, 422)
    still_open = validate_success(
        api.get_script_deal(ctx.deal_id, business_affairs_headers())
    )
    assert still_open["deal_status"] == DEAL_EXECUTED

    fx.accept_step(api, ctx.deal_id, ctx.step_ids[0])

    cut = validate_success(
        api.cutoff_deal(
            ctx.deal_id,
            f.cutoff_payload("creative direction changed"),
            business_affairs_headers(),
        )
    )
    assert cut["deal_status"] == DEAL_CUT_OFF

    steps = validate_success(api.list_deal_steps(ctx.deal_id, business_affairs_headers()))
    a.assert_step(a.find_step(steps, 1), status=STEP_ACCEPTED)
    a.assert_step(a.find_step(steps, 2), status=STEP_CUT_OFF)

    deal = validate_success(api.get_script_deal(ctx.deal_id, business_affairs_headers()))
    a.assert_cents(deal["encumbered_cents"], 4375000, "encumbered_cents")

    slate = validate_success(api.get_slate(ctx.slate_id, business_affairs_headers()))
    a.assert_slate_dollar_ledger(slate, committed=4375000, available=395625000)


def test_re_covering_a_covered_pitch_only_moves_the_round_counter(api):
    """The COVERED self-loop overwrites the read without re-entering SUBMITTED.

    PRD 3.2: "on a pitch that is already `COVERED` it is a self-loop, leaving the
    pitch `COVERED` while overwriting the score and incrementing the round, and
    development may re-cover a pitch this way any number of times."

    Design: Corner/state_machines/re_covering_a_covered_pitch_increments_coverage_round_without_leaving_covered
    """
    ctx = build_scenario(api, "covered")

    recovered = validate_success(
        api.record_coverage(
            ctx.pitch_id,
            f.coverage_payload(88.0, RECOMMENDATION_ADVANCE),
            development_exec_headers(),
        )
    )
    assert recovered["status"] == PITCH_COVERED
    assert recovered["coverage_round"] == 2
    a.assert_score(recovered["coverage_score"], 88.0, "coverage_score")
    assert recovered["recommendation"] == RECOMMENDATION_ADVANCE

    rows, _meta = validate_paginated(
        api.list_projects(
            business_affairs_headers(),
            {"pitch_id": ctx.pitch_id, "limit": 10, "offset": 0},
        )
    )
    assert rows == [], "re-covering does not advance the pitch"


def test_accepting_the_only_guaranteed_step_bubbles_the_project_to_script_complete(api):
    """The acceptance frees the writer's desk and completes the script in one request.

    PRD 3.4: "when every step with a `step_index` at or below
    `guaranteed_step_count` has reached `ACCEPTED` and the project is still in
    `ACTIVE_DEVELOPMENT`, the project moves `ACTIVE_DEVELOPMENT → SCRIPT_COMPLETE`".

    Design: Corner/state_machines/accepting_the_last_guaranteed_step_bubbles_the_project_up_to_script_complete
    """
    ctx = build_scenario(api, "deal")
    step_one = ctx.step_ids[0]
    validate_success(api.exercise_step(ctx.deal_id, step_one, business_affairs_headers()))
    validate_success(api.deliver_step(ctx.deal_id, step_one, business_affairs_headers()))

    mid_flight = validate_success(
        api.get_writer(ctx.writer_id, business_affairs_headers())
    )
    assert mid_flight["open_step_count"] == 1

    validate_success(
        api.review_step(
            ctx.deal_id, step_one, f.review_payload(), development_exec_headers()
        )
    )

    steps = validate_success(api.list_deal_steps(ctx.deal_id, business_affairs_headers()))
    accepted = a.find_step(steps, 1)
    a.assert_step(accepted, status=STEP_ACCEPTED)
    a.assert_instant(
        accepted["accepted_at"], CLOCK_STARTUP_DEFAULT_STAMP, "accepted_at"
    )

    project = validate_success(api.get_project(ctx.project_id, business_affairs_headers()))
    assert project["dev_status"] == DEV_SCRIPT_COMPLETE

    writer = validate_success(api.get_writer(ctx.writer_id, business_affairs_headers()))
    assert writer["open_step_count"] == 0, "acceptance frees the writer's desk"

    deal = validate_success(api.get_script_deal(ctx.deal_id, business_affairs_headers()))
    assert deal["deal_status"] == DEAL_EXECUTED, "the deal itself does not complete"
    a.assert_cents(deal["encumbered_cents"], 4375000, "encumbered_cents")

    slate = validate_success(api.get_slate(ctx.slate_id, business_affairs_headers()))
    a.assert_slate_dollar_ledger(slate, committed=4375000, available=395625000)


def test_one_failed_casting_clearance_collapses_the_pilot_and_returns_its_budget(api):
    """The collapse reopens development and hands the whole budget back to the slate.

    PRD 3.5: "The named dimension is set to `FAILED`, `production_status` becomes
    `COLLAPSED`, and `collapsed_reason` records the kind of contingency that failed
    ... the project falls back `PILOT_ORDERED → ACTIVE_DEVELOPMENT` ... the pilot's
    `budget_cents` leaves the slate's `committed_dev_cents`".

    Design: Corner/state_machines/a_failed_casting_contingency_collapses_the_pilot_and_releases_its_budget
    """
    ctx = build_scenario(api, "pilot_ordered")

    failed = validate_success(
        api.clear_contingency(
            ctx.pilot_order_id,
            f.contingency_payload(
                CONTINGENCY_CASTING,
                CONTINGENCY_FAILED,
                overrides={"note": "lead offer withdrawn"},
            ),
            development_exec_headers(),
        )
    )
    # PRD 3.5 names `kind` and `resolution` only as inputs to the clearance, and
    # PRD 4 classes a contingency clearance as an operation that modifies an
    # existing resource, so the response body is the updated PilotOrder. The
    # collapse itself is asserted on that resource below.
    assert failed["production_status"] == PRODUCTION_COLLAPSED

    pilot = validate_success(
        api.get_pilot_order(ctx.pilot_order_id, development_exec_headers())
    )
    assert pilot["production_status"] == PRODUCTION_COLLAPSED
    assert pilot["casting_status"] == CONTINGENCY_FAILED
    assert pilot["location_status"] == CONTINGENCY_PENDING
    assert pilot["collapsed_reason"] == COLLAPSED_REASON_CASTING

    project = validate_success(api.get_project(ctx.project_id, business_affairs_headers()))
    assert project["dev_status"] == DEV_ACTIVE_DEVELOPMENT
    a.assert_cents(
        project["cumulative_dev_cost_cents"], 4375000, "cumulative_dev_cost_cents"
    )

    slate = validate_success(api.get_slate(ctx.slate_id, business_affairs_headers()))
    a.assert_slate_dollar_ledger(slate, committed=4375000, available=395625000)
    a.assert_slate_episode_ledger(slate, posture=POSTURE_OPEN)


def test_a_waived_location_is_as_green_as_a_satisfied_one(api):
    """BusinessAffairs waives the location dimension and the shoot goes green.

    PRD 3.5: "Resolving the last `PENDING` dimension such that `casting_status` is
    `SATISFIED` or `WAIVED` and `location_status` is likewise `SATISFIED` or
    `WAIVED` auto-advances the pilot `ORDERED → GREEN_TO_SHOOT` in the same
    request, and the pilot's `version` is incremented by 1."

    Design: Corner/state_machines/a_waived_location_contingency_from_business_affairs_greenlights_the_shoot
    """
    ctx = build_scenario(api, "pilot_ordered")
    fx.clear_contingency(
        api, ctx.pilot_order_id, CONTINGENCY_CASTING, CONTINGENCY_SATISFIED
    )

    waived = validate_success(
        api.clear_contingency(
            ctx.pilot_order_id,
            f.contingency_payload(
                CONTINGENCY_LOCATION,
                CONTINGENCY_WAIVED,
                overrides={"note": "standing backlot agreement covers the exteriors"},
            ),
            business_affairs_headers(),
        )
    )
    # The clearance response is the updated PilotOrder (PRD 2.2 / PRD 4): the
    # waiver is observable as location_status, not as an echoed `resolution`.
    assert waived["location_status"] == CONTINGENCY_WAIVED

    pilot = validate_success(
        api.get_pilot_order(ctx.pilot_order_id, development_exec_headers())
    )
    assert pilot["casting_status"] == CONTINGENCY_SATISFIED
    assert pilot["location_status"] == CONTINGENCY_WAIVED
    assert pilot["production_status"] == PRODUCTION_GREEN_TO_SHOOT
    assert pilot["collapsed_reason"] is None
    # Version 1 at the order, +1 for the casting clearance, +1 for this request.
    assert pilot["version"] == 3

    project = validate_success(api.get_project(ctx.project_id, business_affairs_headers()))
    assert project["dev_status"] == DEV_PILOT_ORDERED, (
        "clearing contingencies never moves the project"
    )


def test_research_cannot_be_fielded_on_a_pilot_that_has_not_wrapped(api):
    """The state gate is consulted ahead of the version guard, so a current version does not help.

    PRD 3.6: "Research is fielded only by a `ResearchAnalyst`, and only on a pilot
    whose `production_status` is `WRAPPED` - on any other production status the
    request is refused with `ERR_INVALID_PILOT_ORDER_STATE`."

    Design: Corner/state_machines/test_screening_on_an_unwrapped_pilot_returns_invalid_pilot_order_state
    """
    ctx = build_scenario(api, "pilot_ordered")
    observed = validate_success(
        api.get_pilot_order(ctx.pilot_order_id, development_exec_headers())
    )["version"]

    refused = api.field_screening(
        ctx.pilot_order_id, f.screening_payload(observed), research_analyst_headers()
    )
    validate_error(refused, e.ERR_INVALID_PILOT_ORDER_STATE, 409)

    screenings = validate_success(
        api.list_screenings(ctx.pilot_order_id, research_analyst_headers())
    )
    assert screenings == [], "the refused filing left no screening behind"

    pilot = validate_success(
        api.get_pilot_order(ctx.pilot_order_id, development_exec_headers())
    )
    assert pilot["version"] == observed, "a refused request mutates nothing"


def test_exercising_an_optional_step_pushes_a_complete_script_back_into_development(api):
    """The reversal is the one cyclic corner of the development lifecycle.

    PRD 3.4: "Exercising an optional step - one above the guarantee line - on a
    project that has already reached `SCRIPT_COMPLETE` pushes the project back
    `SCRIPT_COMPLETE → ACTIVE_DEVELOPMENT`, because there is live writing
    outstanding again."

    Design: Corner/state_machines/exercising_an_optional_step_after_script_completion_reopens_development
    """
    ctx = build_scenario(api, "script_complete", deal=dict(OPTIONAL_REVISION_LADDER))

    validate_success(
        api.exercise_step(ctx.deal_id, ctx.step_ids[1], business_affairs_headers())
    )

    steps = validate_success(api.list_deal_steps(ctx.deal_id, business_affairs_headers()))
    optional = a.find_step(steps, 2)
    # The REVISION base of 2500000 scaled by the HIGH tier factor is 3125000, which
    # lifts the submitted 2000000 fee.
    a.assert_step(optional, status=STEP_EXERCISED, effective_fee_cents=3125000)

    project = validate_success(api.get_project(ctx.project_id, business_affairs_headers()))
    assert project["dev_status"] == DEV_ACTIVE_DEVELOPMENT
    a.assert_cents(
        project["cumulative_dev_cost_cents"], 7500000, "cumulative_dev_cost_cents"
    )

    deal = validate_success(api.get_script_deal(ctx.deal_id, business_affairs_headers()))
    a.assert_cents(deal["encumbered_cents"], 7500000, "encumbered_cents")
    a.assert_cents(
        deal["guaranteed_commitment_cents"], 4375000, "guaranteed_commitment_cents"
    )
    a.assert_cents(
        deal["full_option_exposure_cents"], 7500000, "full_option_exposure_cents"
    )

    slate = validate_success(api.get_slate(ctx.slate_id, business_affairs_headers()))
    a.assert_slate_dollar_ledger(slate, committed=7500000, available=392500000)

    writer = validate_success(api.get_writer(ctx.writer_id, business_affairs_headers()))
    assert writer["open_step_count"] == 1


def test_a_single_finance_rejection_closes_the_join_and_fires_no_cascade(api):
    """The other two committees stay PENDING and the project is left where it stood.

    PRD 3.8: "The named committee's decision is set to `REJECTED`, the request moves
    `OPEN → REJECTED` and `decided_at` is stamped, and the committees that had not
    yet voted stay `PENDING` forever ... The project is deliberately left at
    `PILOT_DELIVERED`."

    Design: Corner/state_machines/a_rejected_finance_vote_short_circuits_the_join_and_leaves_the_project_pilot_delivered
    """
    ctx = build_scenario(api, "greenlight")

    rejected = validate_success(
        api.record_decision(
            ctx.greenlight_id,
            f.decision_payload(
                COMMITTEE_FINANCE,
                DECISION_REJECTED,
                note="deficit exposure outside plan",
            ),
            finance_controller_headers(USER_FINANCE_1),
        )
    )
    assert rejected["status"] == GL_REJECTED
    assert rejected["finance_decision"] == DECISION_REJECTED
    assert rejected["finance_decided_by_user_id"] == USER_FINANCE_1
    assert rejected["creative_decision"] == DECISION_PENDING
    assert rejected["business_decision"] == DECISION_PENDING

    project = validate_success(api.get_project(ctx.project_id, business_affairs_headers()))
    assert project["dev_status"] == DEV_PILOT_DELIVERED

    deal = validate_success(api.get_script_deal(ctx.deal_id, business_affairs_headers()))
    assert deal["deal_status"] == DEAL_EXECUTED, "no series-order cascade fired"
    a.assert_cents(deal["encumbered_cents"], 4375000, "encumbered_cents")

    slate = validate_success(api.get_slate(ctx.slate_id, business_affairs_headers()))
    a.assert_slate_dollar_ledger(slate, committed=37375000)
    a.assert_slate_episode_ledger(slate, committed=10, reserved=0)


def test_a_second_greenlight_request_supersedes_the_first_with_its_votes_intact(api):
    """The superseded request keeps the creative vote it already collected.

    PRD 3.8: "Every other greenlight request on the same project that was still
    `OPEN` becomes `SUPERSEDED`, with whatever committee decisions it had already
    collected frozen exactly as they stand".

    Design: Corner/state_machines/a_second_greenlight_request_supersedes_the_first_and_freezes_its_recorded_votes
    """
    ctx = build_scenario(api, "greenlight")
    fx.record_creative_decision(
        api, ctx.greenlight_id, DECISION_APPROVED, USER_EXEC_CREATIVE_1
    )

    reread_version = fx.project_version(api, ctx.project_id)
    replacement = validate_success(
        api.create_greenlight_request(
            f.greenlight_payload(ctx.project_id, ctx.negotiation_id, reread_version),
            business_affairs_headers(),
        ),
        201,
    )
    assert replacement["status"] == GL_OPEN
    assert replacement["creative_decision"] == DECISION_PENDING
    assert replacement["business_decision"] == DECISION_PENDING
    assert replacement["finance_decision"] == DECISION_PENDING
    assert replacement["project_version_at_request"] == reread_version

    superseded = validate_success(
        api.get_greenlight_request(ctx.greenlight_id, business_affairs_headers())
    )
    assert superseded["status"] == GL_SUPERSEDED
    assert superseded["creative_decision"] == DECISION_APPROVED, (
        "the collected vote is frozen, not reset"
    )
    assert superseded["creative_decided_by_user_id"] == USER_EXEC_CREATIVE_1

    rows, meta = validate_paginated(
        api.list_greenlight_requests(
            business_affairs_headers(),
            {"project_id": ctx.project_id, "limit": 10, "offset": 0},
        )
    )
    assert len(rows) == 2
    a.assert_pagination_meta(meta, total_count=2)
    assert len([row for row in rows if row["status"] == GL_OPEN]) == 1
