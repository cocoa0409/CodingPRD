"""Declared transitions, their side effects, and the calls a state machine
refuses: auto-activation on a passed exam, the end-of-play sweep, terminal-state
lockdown, the remediation loop, and the publication that retires its predecessor.
"""
import pytest
from prd_bench_local_runner.testing import validate_error

from test_helpers import factories as f
from test_helpers import fixtures as fx
from test_helpers.api_client import api_client
from test_helpers.assertions import assert_instant_equals
from test_helpers.constants import (
    INSTANT_G1_POSTGAME,
    INSTANT_G1_REPLAY_OPEN,
    INSTANT_NEXT_DAY_PUBLISH,
    INSTANT_REPLAY_DECIDE_AT_60S,
    INSTANT_REPLAY_RETRY_AT_90S,
    INSTANT_SEASON_START,
)


# ─── Roster membership versus field readiness ──────────

@pytest.fixture
def candidate_with_no_training_history():
    """Dan Ruiz newly registered into an open program, holding no records."""
    program = fx.create_open_program()
    official = fx.register_umpire(program["id"], cleared=False)
    return {"program": program, "official": official}


def test_a_passed_rules_exam_activates_the_candidate_without_clearing_him(
    candidate_with_no_training_history,
):
    """He starts as a CANDIDATE and the 84.00 exam carries him to ACTIVE, but with
    no physical test on file he is still not field-ready.

    PRD §3.2: "Storing a passed rules exam for an official whose `status` is
    `CANDIDATE` transitions that official `CANDIDATE → ACTIVE` and bumps the
    official's `version` — passing the rulebook exam is what makes someone a member
    of the officiating department."

    Design: Corner/state_machines/official_activates_on_passed_rules_exam_but_stays_uncleared
    """
    official_id = candidate_with_no_training_history["official"]["id"]

    assert candidate_with_no_training_history["official"]["status"] == "CANDIDATE"
    assert candidate_with_no_training_history["official"]["preseason_cleared"] is False

    exam = fx.add_training_record(
        official_id, f.rules_exam_payload(84.00, "EX-D1")
    )
    official = fx.read_official(official_id)

    assert exam["passed"] is True
    assert official["status"] == "ACTIVE"
    assert official["preseason_cleared"] is False


def test_the_passed_physical_test_completes_the_clearance_derivation(
    candidate_with_no_training_history,
):
    """Only once both a passed exam and a passed physical exist does
    `preseason_cleared` flip, and the official's status stays ACTIVE.

    PRD §3.2: "Field readiness is a separate derivation: `preseason_cleared` becomes
    true only when the official holds both a passed `PHYSICAL_TEST` record and a
    passed `RULES_EXAM` record."

    Design: Corner/state_machines/official_activates_on_passed_rules_exam_but_stays_uncleared
    """
    official_id = candidate_with_no_training_history["official"]["id"]
    fx.add_training_record(official_id, f.rules_exam_payload(84.00, "EX-D1"))

    physical = fx.add_training_record(
        official_id, f.physical_test_payload(79.00, "PT-D1")
    )
    official = fx.read_official(official_id)

    assert physical["passed"] is True
    assert official["preseason_cleared"] is True
    assert official["status"] == "ACTIVE"


# ─── The end-of-play sweep ─────────────────────────────

@pytest.fixture
def live_game_with_one_open_review():
    """An IN_PROGRESS game with Dan's CONFIRMED assignment and one review opened on
    BOOTH-1 at 18:00:00."""
    ctx = fx.in_progress_game_with_station(station_code="BOOTH-1")
    fx.pin_clock(INSTANT_G1_REPLAY_OPEN)
    ctx["review"] = fx.open_review(
        ctx["game"]["id"],
        ctx["station"]["id"],
        play_ref="Q1-P12",
        category="SCORING_PLAY",
    )
    return ctx


def test_ending_play_completes_the_confirmed_crew_in_the_same_call(
    live_game_with_one_open_review,
):
    """The transition sweeps the crew itself: the confirmed assignment reaches
    COMPLETED, the official's open counter falls to zero, and posture stays LOCKED.

    PRD §3.5: "Every `CONFIRMED` assignment on the game moves `CONFIRMED →
    COMPLETED` in `created_at` ascending order, and each affected official's
    `open_assignment_count` decrements by 1."

    Design: Corner/state_machines/mark_played_completes_crew_and_expires_open_replay_reviews
    """
    fx.pin_clock(INSTANT_G1_POSTGAME)

    played = fx.mark_played(live_game_with_one_open_review["game"]["id"])
    assignment = fx.read_assignment(
        live_game_with_one_open_review["assignment"]["id"]
    )
    official = fx.read_official(live_game_with_one_open_review["official"]["id"])

    assert played["status"] == "PLAYED"
    assert played["crew_posture"] == "LOCKED"
    assert assignment["status"] == "COMPLETED"
    assert official["open_assignment_count"] == 0


def test_ending_play_expires_the_open_review_and_releases_the_booth(
    live_game_with_one_open_review,
):
    """The window that opened at 18:00:00 expires with a null decision and 12600
    elapsed seconds measured to the 21:30:00 clock, freeing the booth.

    PRD §3.5: "Every review of that game still in `INITIATED` status moves
    `INITIATED → EXPIRED` with `decision` set to null and `elapsed_seconds` set to
    the whole seconds from that review's `window_open_utc` to the current logical
    clock, and each such booth's `active_review_count` decrements by 1 while its
    `version` bumps."

    Design: Corner/state_machines/mark_played_completes_crew_and_expires_open_replay_reviews
    """
    assert_instant_equals(
        live_game_with_one_open_review["review"]["window_open_utc"],
        INSTANT_G1_REPLAY_OPEN,
        "window_open_utc",
    )

    fx.pin_clock(INSTANT_G1_POSTGAME)
    fx.mark_played(live_game_with_one_open_review["game"]["id"])

    review = fx.read_review(live_game_with_one_open_review["review"]["id"])
    station = fx.read_station(live_game_with_one_open_review["station"]["id"])

    assert review["status"] == "EXPIRED"
    assert review["decision"] is None
    assert review["elapsed_seconds"] == 12600
    assert station["active_review_count"] == 0


# ─── Transitions the pipeline does not declare ─────────

def test_a_scheduled_game_cannot_skip_straight_to_played():
    """mark-played is declared only out of IN_PROGRESS, so the call is refused and
    the game keeps both its state and its version.

    PRD §3.5: "Ending play is an `OfficiatingDirector` action legal only from
    `IN_PROGRESS`, and it moves the game `IN_PROGRESS → PLAYED` while sweeping two
    collections."

    Design: Corner/state_machines/mark_played_from_scheduled_returns_game_state_invalid
    """
    program = fx.solo_program()
    game = fx.schedule_game(program["id"])

    response = api_client.mark_game_played(game["id"], fx.DIRECTOR)
    validate_error(response, "ERR_GAME_STATE_INVALID", 409)

    after = fx.read_game(game["id"])

    assert after["status"] == "SCHEDULED"
    assert after["version"] == game["version"]


# ─── The terminal game ─────────────────────────────────

@pytest.fixture
def finalized_solo_game():
    """Dan's one-official game taken all the way to FINALIZED."""
    ctx = fx.played_solo_game()
    ctx["finalized"] = fx.finalize_game(ctx["game"]["id"])
    return ctx


def test_finalization_realizes_the_crew_strength_over_completed_assignments(
    finalized_solo_game,
):
    """The stored index is recomputed from Dan's single COMPLETED assignment — 6
    times 0.80 over a required crew of one — and marked REALIZED.

    PRD §3.9: "The game's `crew_strength_index` is recomputed with the `REALIZED`
    variant over its `COMPLETED` assignments only, and `crew_strength_variant` is
    written as `REALIZED` — which is where a crew that lost a member to a suspension
    realizes a strictly lower index than it projected."

    Design: Corner/state_machines/finalized_game_rejects_every_further_transition
    """
    finalized = finalized_solo_game["finalized"]

    assert finalized["status"] == "FINALIZED"
    assert finalized["crew_strength_variant"] == "REALIZED"
    assert finalized["crew_strength_index"] == 4.80


def test_no_transition_escapes_the_finalized_game(finalized_solo_game):
    """Kickoff, mark-played and a second finalize are all refused with the same
    state error, and the game stays FINALIZED.

    PRD §3.4: "Its lifecycle is a strict linear pipeline: `SCHEDULED → IN_PROGRESS →
    PLAYED → FINALIZED`, with `FINALIZED` terminal."

    Design: Corner/state_machines/finalized_game_rejects_every_further_transition
    """
    game_id = finalized_solo_game["game"]["id"]

    validate_error(
        api_client.kickoff_game(game_id, fx.DIRECTOR), "ERR_GAME_STATE_INVALID", 409
    )
    validate_error(
        api_client.mark_game_played(game_id, fx.DIRECTOR),
        "ERR_GAME_STATE_INVALID",
        409,
    )
    validate_error(
        api_client.finalize_game(game_id, fx.DIRECTOR), "ERR_GAME_STATE_INVALID", 409
    )

    assert fx.read_game(game_id)["status"] == "FINALIZED"


# ─── Posting a grade exactly once ──────────────────────

@pytest.fixture
def posted_missed_call():
    """One POSTED missed call worth 0.75 on Dan, posted at the 21:30 clock."""
    return fx.posted_grade_for_appeal()


def test_a_second_post_is_refused_and_keeps_the_first_stamp(posted_missed_call):
    """Posting is declared only out of DRAFT, so the repeat is refused and
    `posted_at` still reads the instant of the first post.

    PRD §3.6: "Posting is legal only from `grade_status` `DRAFT`, only while the
    program is `OPEN`, and only once the game has reached `PLAYED` or `FINALIZED` —
    a grade cannot be posted on a game still in progress."

    Design: Corner/state_machines/post_play_grade_twice_returns_grade_state_invalid
    """
    grade = posted_missed_call["grade"]

    assert grade["error_points"] == 0.75
    assert grade["grade_status"] == "POSTED"
    assert_instant_equals(grade["posted_at"], INSTANT_G1_POSTGAME, "posted_at")

    response = api_client.post_play_grade(grade["id"], fx.GRADER)
    validate_error(response, "ERR_GRADE_STATE_INVALID", 409)

    after = fx.read_grade(grade["id"])

    assert after["grade_status"] == "POSTED"
    assert_instant_equals(after["posted_at"], grade["posted_at"], "posted_at")


def test_the_refused_repost_does_not_double_count_the_play(posted_missed_call):
    """The season aggregate counts the play once, at 0.75 weighted error points over
    one graded play.

    PRD §3.6: "`graded_play_count` is the number of grades in that set."

    Design: Corner/state_machines/post_play_grade_twice_returns_grade_state_invalid
    """
    api_client.post_play_grade(posted_missed_call["grade"]["id"], fx.GRADER)

    record = fx.season_record_for(posted_missed_call["official"]["id"])

    assert record["graded_play_count"] == 1
    assert record["weighted_error_points"] == 0.75


# ─── The settled replay review ─────────────────────────

def test_a_decided_review_refuses_a_second_decision():
    """A review decided STANDS at 60 elapsed seconds is terminal: the later REVERSED
    is refused and neither the decision nor the elapsed count is rewritten.

    PRD §3.5: "Both `DECIDED` and `EXPIRED` are terminal; a second attempt on an
    already-settled review is refused with `ERR_REVIEW_STATE_INVALID`."

    Design: Corner/state_machines/replay_decide_twice_returns_review_state_invalid
    """
    ctx = fx.in_progress_game_with_station(station_code="BOOTH-1")
    fx.pin_clock(INSTANT_G1_REPLAY_OPEN)
    review = fx.open_review(
        ctx["game"]["id"], ctx["station"]["id"], play_ref="Q1-P12"
    )
    fx.pin_clock(INSTANT_REPLAY_DECIDE_AT_60S)
    decided = fx.decide_review(review["id"], "STANDS")

    assert decided["status"] == "DECIDED"
    assert decided["decision"] == "STANDS"
    assert decided["elapsed_seconds"] == 60

    fx.pin_clock(INSTANT_REPLAY_RETRY_AT_90S)
    response = api_client.decide_replay_review(
        review["id"], f.replay_decision_payload("REVERSED"), fx.REPLAY
    )
    validate_error(response, "ERR_REVIEW_STATE_INVALID", 409)

    after = fx.read_review(review["id"])

    assert after["status"] == "DECIDED"
    assert after["decision"] == "STANDS"
    assert after["elapsed_seconds"] == 60


# ─── An appeal decision needs its review opened first ───

def test_deciding_an_appeal_that_was_never_taken_under_review_is_refused():
    """The decision transition is declared only out of UNDER_REVIEW, so a decision
    on a merely SUBMITTED appeal is refused and nothing about it is recorded.

    PRD §3.7: "The decision is legal only from `UNDER_REVIEW` and carries a required
    `outcome` of `UPHELD`, `OVERTURNED` or `MODIFIED`, an optional `decision_note`,
    and — for a `MODIFIED` outcome — a `revised_grade_code`."

    Design: Corner/state_machines/appeal_decide_without_start_review_returns_appeal_state_invalid
    """
    ctx = fx.posted_grade_for_appeal()
    appeal = fx.file_appeal(
        ctx["grade"]["id"], ctx["official"]["id"], "the hold was on the other guard"
    )

    assert appeal["status"] == "SUBMITTED"

    response = api_client.decide_grade_appeal(
        appeal["id"],
        f.appeal_decision_payload("UPHELD", "reviewed the sideline angle"),
        fx.APPEAL_REVIEWER,
    )
    validate_error(response, "ERR_APPEAL_STATE_INVALID", 409)

    after = fx.read_appeal(appeal["id"], fx.APPEAL_REVIEWER)
    grade = fx.read_grade(ctx["grade"]["id"])
    official = fx.read_official(ctx["official"]["id"])

    assert after["status"] == "SUBMITTED"
    assert after["decided_by_user_id"] is None
    assert grade["appeal_state"] == "APPEAL_PENDING"
    assert grade["grade_status"] == "POSTED"
    assert official["appeal_credits_remaining"] == 2


# ─── Screening happens once ─────────────────────────────

def test_a_screened_application_cannot_be_screened_again():
    """Lee Park's TIER_2 application is screened at the season-start clock; a second
    evaluator's screen is refused and the original stamp survives.

    PRD §3.3: "Screening is a `FieldEvaluator`'s job and moves the application
    `SUBMITTED → SCREENED`, stamping `screened_at` with the logical clock."

    Design: Corner/state_machines/screen_application_twice_returns_application_state_invalid
    """
    program = fx.create_open_program()
    lee = fx.register_official(
        program["id"],
        full_name="Lee Park",
        position="DOWN_JUDGE",
        seasons_experience=7,
        home_market_code="SEA",
    )
    fx.clear_official(
        lee["id"], exam_score=88.00, exam_code="EX-L1",
        physical_score=82.00, physical_code="PT-L1",
    )
    application = fx.create_application(lee["id"], "TIER_2")

    screened = fx.screen_application(application["id"], fx.EVALUATOR)

    assert screened["status"] == "SCREENED"
    assert_instant_equals(
        screened["screened_at"], INSTANT_SEASON_START, "screened_at"
    )

    response = api_client.screen_application(application["id"], fx.EVALUATOR_2)
    validate_error(response, "ERR_APPLICATION_STATE_INVALID", 409)

    after = fx.read_application(application["id"], fx.EVALUATOR)

    assert after["status"] == "SCREENED"
    assert_instant_equals(
        after["screened_at"], screened["screened_at"], "screened_at"
    )


# ─── An incoming proposal displaces a merely proposed one ──

@pytest.fixture
def one_proposed_umpire_slot():
    """A one-slot program whose UMPIRE position is held by Dan's PROPOSED
    assignment, with Rita registered and idle."""
    program = fx.solo_program()
    dan = fx.register_umpire(program["id"])
    rita = fx.register_referee(program["id"])
    game = fx.schedule_game(program["id"])
    dan_assignment = fx.propose_assignment(
        game["id"], dan["id"], "UMPIRE", expected_game_version=game["version"]
    )
    return {
        "program": program,
        "dan": dan,
        "rita": rita,
        "game": fx.read_game(game["id"]),
        "dan_assignment": dan_assignment,
    }


def test_the_incoming_proposal_supersedes_the_row_it_displaces(
    one_proposed_umpire_slot,
):
    """Rita's proposal for the same slot wins: Dan's row moves to SUPERSEDED with a
    stamped release instant and his open counter falls to zero.

    PRD §3.4: "If a merely `PROPOSED` assignment occupies it, the incoming proposal
    wins: the existing assignment moves `PROPOSED → SUPERSEDED`, has its
    `released_at` stamped with the logical clock, and decrements its official's
    `open_assignment_count` by 1."

    Design: Corner/state_machines/new_assignment_supersedes_earlier_proposed_same_position
    """
    game_id = one_proposed_umpire_slot["game"]["id"]

    incoming = fx.propose_assignment(
        game_id, one_proposed_umpire_slot["rita"]["id"], "UMPIRE"
    )
    displaced = fx.read_assignment(one_proposed_umpire_slot["dan_assignment"]["id"])
    dan = fx.read_official(one_proposed_umpire_slot["dan"]["id"])
    rita = fx.read_official(one_proposed_umpire_slot["rita"]["id"])

    assert incoming["status"] == "PROPOSED"
    assert displaced["status"] == "SUPERSEDED"
    assert_instant_equals(
        displaced["released_at"], INSTANT_SEASON_START, "released_at"
    )
    assert dan["open_assignment_count"] == 0
    assert rita["open_assignment_count"] == 1


def test_the_displacement_reprices_the_projected_crew_strength(
    one_proposed_umpire_slot,
):
    """The index is recomputed off the surviving row alone — Rita's capped twelve
    seasons at tier weight 0.80 and the umpire slot's weight 1.00, or 9.60.

    PRD §3.4: "Each counted assignment contributes the product of three factors: the
    official's `seasons_experience` capped at 12, the tier weight of the official's
    `tier` — 1.00 for `TIER_1`, 0.80 for `TIER_2`, 0.60 for `TIER_3` — and the
    position weight of the assignment's `position`, which is 1.30 for `REFEREE`, 1.00
    for `UMPIRE` and 0.85 for `DOWN_JUDGE`."

    Design: Corner/state_machines/new_assignment_supersedes_earlier_proposed_same_position
    """
    game_id = one_proposed_umpire_slot["game"]["id"]

    assert one_proposed_umpire_slot["game"]["crew_strength_index"] == 4.80

    fx.propose_assignment(game_id, one_proposed_umpire_slot["rita"]["id"], "UMPIRE")
    game = fx.read_game(game_id)

    assert game["crew_strength_index"] == 9.60
    assert game["confirmed_crew_count"] == 0
    assert game["crew_posture"] == "UNDERSTAFFED"


# ─── The remediation loop and its cap ──────────────────

@pytest.fixture
def remediation_action_on_a_probation_official():
    """Dan carries an OPENED PERFORMANCE remediation, which put him on
    PROBATION."""
    program = fx.create_open_program()
    dan = fx.register_umpire(program["id"], cleared=False)
    fx.add_training_record(dan["id"], f.rules_exam_payload(84.00, "EX-D1"))
    action = fx.open_discipline(dan["id"], "PERFORMANCE", "REMEDIATION")
    return {"program": program, "official": dan, "action": action}


def test_the_loop_runs_assign_reassess_assign_over_two_cycles(
    remediation_action_on_a_probation_official,
):
    """Two assignments and one reassessment in between carry the cycle count from
    zero to two while the official stays on PROBATION.

    PRD §3.8: "A permitted assignment moves the action to `REMEDIATION_ASSIGNED`,
    sets `remediation_plan` from the supplied text, increments
    `remediation_cycle_count` by 1, and bumps the action's `version` by 1."

    Design: Corner/state_machines/discipline_remediation_loop_reassigns_then_hits_cycle_limit
    """
    action_id = remediation_action_on_a_probation_official["action"]["id"]
    official_id = remediation_action_on_a_probation_official["official"]["id"]

    assert remediation_action_on_a_probation_official["action"]["status"] == "OPENED"
    assert remediation_action_on_a_probation_official["action"][
        "remediation_cycle_count"
    ] == 0
    assert fx.read_official(official_id)["status"] == "PROBATION"

    first = fx.assign_remediation(action_id, "Cycle 1: rules clinic and film review")
    reassessed = fx.resolve_discipline(action_id, "REASSESSED")
    second = fx.assign_remediation(action_id, "Cycle 2: field mentoring")

    assert first["status"] == "REMEDIATION_ASSIGNED"
    assert first["remediation_cycle_count"] == 1
    assert reassessed["status"] == "REASSESSED"
    assert reassessed["remediation_cycle_count"] == 1
    assert second["status"] == "REMEDIATION_ASSIGNED"
    assert second["remediation_cycle_count"] == 2
    assert second["remediation_plan"] == "Cycle 2: field mentoring"
    assert fx.read_official(official_id)["status"] == "PROBATION"


def test_the_third_cycle_is_refused_and_leaves_the_second_plan_standing(
    remediation_action_on_a_probation_official,
):
    """After two cycles the loop is exhausted: the third assignment is refused and
    the action keeps its cycle count of two and its second plan.

    PRD §3.8: "It is legal from `OPENED` or from `REASSESSED`, and it is capped: an
    action whose `remediation_cycle_count` has already reached 2 is refused a further
    cycle with `ERR_REMEDIATION_CYCLE_LIMIT`."

    Design: Corner/state_machines/discipline_remediation_loop_reassigns_then_hits_cycle_limit
    """
    action_id = remediation_action_on_a_probation_official["action"]["id"]
    fx.assign_remediation(action_id, "Cycle 1: rules clinic and film review")
    fx.resolve_discipline(action_id, "REASSESSED")
    fx.assign_remediation(action_id, "Cycle 2: field mentoring")
    fx.resolve_discipline(action_id, "REASSESSED")

    response = api_client.assign_remediation(
        action_id, f.remediation_payload("Cycle 3: another clinic"), fx.DIRECTOR
    )
    validate_error(response, "ERR_REMEDIATION_CYCLE_LIMIT", 409)

    after = fx.read_discipline(action_id)
    official = fx.read_official(
        remediation_action_on_a_probation_official["official"]["id"]
    )

    assert after["status"] == "REASSESSED"
    assert after["remediation_cycle_count"] == 2
    assert after["remediation_plan"] == "Cycle 2: field mentoring"
    assert official["status"] == "PROBATION"


# ─── Clearing the action restores the official ─────────

@pytest.fixture
def performance_warning_on_an_active_official():
    """Dan carries an OPENED PERFORMANCE warning — the one warning category that
    moves an official onto PROBATION."""
    program = fx.create_open_program()
    dan = fx.register_umpire(program["id"])
    action = fx.open_discipline(dan["id"], "PERFORMANCE", "WARNING")
    return {"program": program, "official": dan, "action": action}


def test_a_performance_warning_puts_the_active_official_on_probation(
    performance_warning_on_an_active_official,
):
    """The warning opens with no suspension count and moves Dan from ACTIVE to
    PROBATION.

    PRD §3.8: "A `WARNING` moves an `ACTIVE` official to `PROBATION` **only when its
    `reason_category` is `PERFORMANCE`**; a warning for `CONDUCT` or `ATTENDANCE`
    leaves the official's `status` alone."

    Design: Corner/state_machines/discipline_resolve_cleared_returns_official_to_active
    """
    action = performance_warning_on_an_active_official["action"]
    official = fx.read_official(
        performance_warning_on_an_active_official["official"]["id"]
    )

    assert action["status"] == "OPENED"
    assert action["suspension_games"] is None
    assert action["resolution_note"] is None
    assert official["status"] == "PROBATION"


def test_clearing_the_only_open_action_returns_him_to_active(
    performance_warning_on_an_active_official,
):
    """With nothing else outstanding, a CLEARED resolution records the note and
    carries Dan back from PROBATION to ACTIVE.

    PRD §3.8: "`CLEARED` is legal from `OPENED`, `REMEDIATION_ASSIGNED` or
    `REASSESSED`, and it moves the action to the terminal `CLEARED` state."

    Design: Corner/state_machines/discipline_resolve_cleared_returns_official_to_active
    """
    resolved = fx.resolve_discipline(
        performance_warning_on_an_active_official["action"]["id"],
        "CLEARED",
        note="attended the clinic and graded clean since",
    )
    official = fx.read_official(
        performance_warning_on_an_active_official["official"]["id"]
    )

    assert resolved["status"] == "CLEARED"
    assert resolved["resolution_note"] == "attended the clinic and graded clean since"
    assert official["status"] == "ACTIVE"


# ─── Publication retires the report it names ───────────

@pytest.fixture
def published_pool_report_and_its_replacement():
    """A finalized game with one FINAL grade, a PUBLISHED pool report on it, and a
    drafted clarification that names the first report as superseded."""
    ctx = fx.posted_grade_for_appeal()
    ctx["game"] = fx.finalize_game(ctx["game"]["id"])
    first = fx.draft_pool_report(
        ctx["game"]["id"], ctx["grade"]["id"], report_type="POOL_REPORT"
    )
    ctx["first"] = fx.publish_pool_report(first["id"])
    ctx["second"] = fx.draft_pool_report(
        ctx["game"]["id"],
        ctx["grade"]["id"],
        report_type="RULES_CLARIFICATION",
        supersedes_id=first["id"],
    )
    return ctx


def test_the_replacement_publishes_at_the_clock_it_goes_out_on(
    published_pool_report_and_its_replacement,
):
    """The first statement went out at the postgame instant; the clarification is
    drafted with a null stamp and publishes at the next day's clock.

    PRD §3.9: "Publication moves the report `DRAFT → PUBLISHED` and stamps
    `published_at` from the logical clock."

    Design: Corner/state_machines/pool_report_publication_supersedes_named_earlier_report
    """
    assert published_pool_report_and_its_replacement["first"]["status"] == "PUBLISHED"
    assert_instant_equals(
        published_pool_report_and_its_replacement["first"]["published_at"],
        INSTANT_G1_POSTGAME,
        "published_at",
    )
    assert published_pool_report_and_its_replacement["second"]["status"] == "DRAFT"
    assert published_pool_report_and_its_replacement["second"]["published_at"] is None

    fx.pin_clock(INSTANT_NEXT_DAY_PUBLISH)
    published = fx.publish_pool_report(
        published_pool_report_and_its_replacement["second"]["id"]
    )

    assert published["status"] == "PUBLISHED"
    assert_instant_equals(
        published["published_at"], INSTANT_NEXT_DAY_PUBLISH, "published_at"
    )


def test_the_named_predecessor_is_retired_with_its_own_stamp_intact(
    published_pool_report_and_its_replacement,
):
    """Publishing the clarification moves the report it names from PUBLISHED to the
    terminal SUPERSEDED, and does not rewrite that report's publication instant.

    PRD §3.9: "When `supersedes_id` is set, the report it names is retired: a target
    in `DRAFT` moves `DRAFT → SUPERSEDED` and a target in `PUBLISHED` moves
    `PUBLISHED → SUPERSEDED`, and either way that target's `version` bumps by 1."

    Design: Corner/state_machines/pool_report_publication_supersedes_named_earlier_report
    """
    first = published_pool_report_and_its_replacement["first"]

    fx.pin_clock(INSTANT_NEXT_DAY_PUBLISH)
    fx.publish_pool_report(published_pool_report_and_its_replacement["second"]["id"])

    retired = fx.read_pool_report(first["id"])

    assert retired["status"] == "SUPERSEDED"
    assert_instant_equals(
        retired["published_at"], INSTANT_G1_POSTGAME, "published_at"
    )
    assert retired["version"] > first["version"]
