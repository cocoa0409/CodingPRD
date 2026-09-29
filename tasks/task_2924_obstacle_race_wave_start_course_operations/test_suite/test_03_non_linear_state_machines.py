"""Difficulty/non_linear_state_machine — lifecycles that go backwards.

Two instances live here, both cycles rather than ladders:

* `permit_revision_loop_reenters_submitted_and_counts_unbounded_rounds` — the
  land-use application walks `SUBMITTED → REVISION_REQUESTED → SUBMITTED` as
  often as the authority likes, counting rounds against no ceiling at all and
  rewriting `submitted_by_user_id` on every re-entry.
* `entry_result_cycle_provisional_under_protest_bounded_at_two_rounds` — the
  result row walks `PROVISIONAL → UNDER_PROTEST → PROVISIONAL`, but this cycle
  *is* bounded: a third protest is refused once two rounds are adjudicated.
"""

from prd_bench_local_runner.testing import get_success_data, validate_error

from test_helpers import factories as f
from test_helpers import fixtures as fx
from test_helpers import test_users as users
from test_helpers.api_errors import ApiErrorId
from test_helpers.assertions import (
    assert_entry_state,
    assert_instant_equals,
    assert_timing,
    assert_wave_state,
)
from test_helpers.constants import (
    BYPASS_MODE_MANDATORY,
    BYPASS_MODE_NONE,
    BYPASS_MODE_TIMED_PENALTY,
    BYPASS_POLICY_ALLOWED_WITH_PENALTY,
    DECISION_APPROVED,
    DECISION_REVISION_REQUESTED,
    DIVISION_OPEN,
    MAX_PROTEST_ROUNDS,
    OUTCOME_COMPLETED,
    OUTCOME_FAILED_PENALTY,
    PERMIT_APPROVED,
    PERMIT_DRAFT,
    PERMIT_REVISION_REQUESTED,
    PERMIT_SUBMITTED,
    PROGRESS_FINISHED,
    RELEASE_CLOSED,
    RESULT_OFFICIAL,
    RESULT_PROVISIONAL,
    RESULT_UNDER_PROTEST,
    ROLE_PERMIT_OFFICER,
    RULING_DENIED_OFFICIAL,
    RULING_UPHELD_ADJUSTED,
    SCORING_CHIP_TIME,
    SITE_POSTURE_OPEN,
    USER_DESIGNER_1,
    USER_DESIGNER_2,
    USER_OFFICER_1,
)

# ─── Private literals this file needs and constants.py does not name ─────

_VALID_UNTIL_UTC = "2026-12-31T00:00:00.000Z"
_RESTORATION_DEADLINE_UTC = "2026-09-20T00:00:00.000Z"
_GUN_UTC = "2026-09-12T08:00:00.000Z"
_CHIP_START_UTC = "2026-09-12T08:00:37.000Z"
_STATION_1_UTC = "2026-09-12T08:05:00.000Z"
_STATION_2_UTC = "2026-09-12T08:20:00.000Z"
_STATION_3_UTC = "2026-09-12T08:35:00.000Z"
_FINISH_UTC = "2026-09-12T08:40:00.000Z"

#: Two penalised dry stations, so two successive rulings each have something
#: real to suppress and no water-safety roster is needed to release the heat.
_STATIONS = [
    {
        "name": "Cargo Net",
        "difficulty_rating": 3,
        "lane_count": 4,
        "service_rate_per_min": 3.00,
        "marshals_required": 2,
        "footprint_sqm": 1200,
        "water_contact": False,
        "bypass_mode": BYPASS_MODE_NONE,
        "penalty_seconds": 60,
    },
    {
        "name": "Mud Pit",
        "difficulty_rating": 5,
        "lane_count": 3,
        "service_rate_per_min": 2.50,
        "marshals_required": 2,
        "footprint_sqm": 1500,
        "water_contact": False,
        "bypass_mode": BYPASS_MODE_MANDATORY,
        "penalty_seconds": 120,
    },
    {
        "name": "Wall Climb",
        "difficulty_rating": 7,
        "lane_count": 3,
        "service_rate_per_min": 3.00,
        "marshals_required": 1,
        "footprint_sqm": 1000,
        "water_contact": False,
        "bypass_mode": BYPASS_MODE_TIMED_PENALTY,
        "penalty_seconds": 90,
    },
]


def _submit(api, permit_id, headers):
    """Drive `POST /permits/{id}/submit` and return the application row."""
    return get_success_data(api.submit_permit(permit_id, headers))


def _decide(api, permit_id, decision, headers, **overrides):
    """Drive `POST /permits/{id}/decision` and return the application row."""
    return get_success_data(
        api.decide_permit(permit_id, f.decision_payload(decision, **overrides), headers)
    )


def _finished_entry(api):
    """One runner across three stations, finished, reading PROVISIONAL.

    Two of the three attempts carry a penalty, so a first ruling and a second
    ruling each have a distinct attempt to void. Returns
    (wave, entry, attempts) with `attempts` in station order.
    """
    venue, _permit = fx.permitted_venue(
        api,
        venue_kwargs={"protected_acreage_sqm": 2000, "restoration_bond_cents": 1000000},
        water_use_allowed=True,
        max_disturbed_area_sqm=5000,
        quiet_hours_start_hour_utc=22,
        quiet_hours_end_hour_utc=6,
        valid_until_utc=_VALID_UNTIL_UTC,
        restoration_deadline_utc=_RESTORATION_DEADLINE_UTC,
    )
    course, stations = fx.three_station_course(
        api,
        venue["id"],
        course_kwargs={
            "total_distance_m": 10000,
            "corral_release_rate_per_min": 12.00,
            "corral_throughput_capacity": 200,
        },
        station_kwargs=_STATIONS,
    )
    fx.published_course(api, course["id"])
    for station in stations:
        fx.fully_marshal(api, course["id"], station)
    fx.medic_shift(api, course["id"], "medic-a")

    division = fx.division(
        api,
        name="Open Chip",
        division_type=DIVISION_OPEN,
        bypass_policy=BYPASS_POLICY_ALLOWED_WITH_PENALTY,
        scoring_mode=SCORING_CHIP_TIME,
        min_age=18,
        team_size_min=1,
        team_size_max=1,
    )
    wave = fx.wave(
        api, course["id"], division["id"], scheduled_start_utc=_GUN_UTC, capacity=112
    )
    entry = fx.checked_in_entry(
        api, wave["id"], bib_number=101, chip_start_offset_seconds=37
    )
    fx.lock_roster(api, wave["id"])
    fx.release(api, wave["id"])
    fx.set_clock(api, _GUN_UTC)
    fx.start(api, wave["id"])

    entry_id = entry["id"]
    attempts = []
    for recorded_at, station, outcome in (
        (_STATION_1_UTC, stations[0], OUTCOME_COMPLETED),
        (_STATION_2_UTC, stations[1], OUTCOME_FAILED_PENALTY),
        (_STATION_3_UTC, stations[2], OUTCOME_FAILED_PENALTY),
    ):
        fx.set_clock(api, recorded_at)
        attempts.append(fx.attempt(api, entry_id, station["id"], outcome))

    fx.set_clock(api, _FINISH_UTC)
    return wave, fx.finish(api, entry_id), attempts


def _rule(api, entry, ruling, **overrides):
    """Adjudicate the open protest under the entry's current version."""
    current = fx.read_entry(api, entry["id"])
    return fx.adjudicate(api, entry["id"], ruling, current["version"], **overrides)


# ─── non_linear_state_machine / the permit revision loop ──────────────────


def test_permit_loop_reenters_submitted_and_counts_rounds_without_a_ceiling(api):
    """PRD §3.1: "A decision of `REVISION_REQUESTED` moves `SUBMITTED → REVISION_REQUESTED` and increments `revision_rounds` by 1; the loop `SUBMITTED → REVISION_REQUESTED → SUBMITTED` may run any number of times and `revision_rounds` simply records how many times it has, with no ceiling."

    Design: Difficulty/non_linear_state_machine/permit_revision_loop_reenters_submitted_and_counts_unbounded_rounds
    """
    venue = fx.venue(api)
    assert venue["site_posture"] == SITE_POSTURE_OPEN
    permit = fx.draft_permit(
        api,
        venue["id"],
        valid_until_utc=_VALID_UNTIL_UTC,
        restoration_deadline_utc=_RESTORATION_DEADLINE_UTC,
    )
    permit_id = permit["id"]
    assert permit["status"] == PERMIT_DRAFT
    assert permit["revision_rounds"] == 0
    assert permit["submitted_by_user_id"] is None
    assert permit["decided_by_user_id"] is None

    submitted = _submit(api, permit_id, users.DESIGNER)
    assert submitted["status"] == PERMIT_SUBMITTED
    assert submitted["submitted_by_user_id"] == USER_DESIGNER_1
    assert submitted["revision_rounds"] == 0, (
        "the first submission is not a revision round"
    )

    # Four full turns of the loop. Nothing anywhere refuses the fourth.
    for expected_round in (1, 2, 3, 4):
        note = f"Round {expected_round}: widen the access road."
        sent_back = _decide(
            api,
            permit_id,
            DECISION_REVISION_REQUESTED,
            users.OFFICER,
            decision_note=note,
        )
        assert sent_back["status"] == PERMIT_REVISION_REQUESTED
        assert sent_back["revision_rounds"] == expected_round
        assert sent_back["decided_by_user_id"] == USER_OFFICER_1
        assert sent_back["decision_note"] == note

        resubmitted = _submit(api, permit_id, users.DESIGNER)
        assert resubmitted["status"] == PERMIT_SUBMITTED
        assert resubmitted["submitted_by_user_id"] == USER_DESIGNER_1
        # Re-entry is not itself a round: only the decision increments the count.
        assert resubmitted["revision_rounds"] == expected_round

    approved = _decide(api, permit_id, DECISION_APPROVED, users.OFFICER)
    assert approved["status"] == PERMIT_APPROVED
    assert approved["decided_by_user_id"] == USER_OFFICER_1
    # The tally survives the exit from the loop as a permanent record.
    assert approved["revision_rounds"] == 4
    assert fx.read_permit(api, permit_id)["revision_rounds"] == 4


def test_a_decision_is_inadmissible_until_the_loop_reenters_submitted(api):
    """PRD §3.1: "A decision on an application that is not `SUBMITTED` is refused with `ERR_PERMIT_STATE_INVALID`."

    Design: Difficulty/non_linear_state_machine/permit_revision_loop_reenters_submitted_and_counts_unbounded_rounds
    """
    venue = fx.venue(api)
    permit = fx.draft_permit(
        api,
        venue["id"],
        valid_until_utc=_VALID_UNTIL_UTC,
        restoration_deadline_utc=_RESTORATION_DEADLINE_UTC,
    )
    permit_id = permit["id"]

    # DRAFT is one step short of the decision point.
    validate_error(
        api.decide_permit(
            permit_id,
            f.decision_payload(DECISION_REVISION_REQUESTED),
            users.OFFICER,
        ),
        ApiErrorId.ERR_PERMIT_STATE_INVALID.value,
        409,
    )

    _submit(api, permit_id, users.DESIGNER)
    sent_back = _decide(api, permit_id, DECISION_REVISION_REQUESTED, users.OFFICER)
    assert sent_back["status"] == PERMIT_REVISION_REQUESTED
    assert sent_back["revision_rounds"] == 1

    # REVISION_REQUESTED is one step *past* it: the same endpoint that just
    # worked is refused again until the designer walks the loop round.
    validate_error(
        api.decide_permit(
            permit_id, f.decision_payload(DECISION_APPROVED), users.OFFICER
        ),
        ApiErrorId.ERR_PERMIT_STATE_INVALID.value,
        409,
    )
    held = fx.read_permit(api, permit_id)
    assert held["status"] == PERMIT_REVISION_REQUESTED
    assert held["revision_rounds"] == 1, "a refused decision must count for nothing"

    # Re-entry into SUBMITTED makes the identical call admissible once more.
    _submit(api, permit_id, users.DESIGNER)
    second = _decide(api, permit_id, DECISION_REVISION_REQUESTED, users.OFFICER)
    assert second["status"] == PERMIT_REVISION_REQUESTED
    assert second["revision_rounds"] == 2


def test_each_reentry_rewrites_the_submitter_the_officer_may_not_be(api):
    """PRD §2.7: "The land authority's decision on a permit application may not be recorded by the operator identifier stored in that permit's `submitted_by_user_id`; a `PermitOfficer` whose `X-User-ID` matches the submitter is refused with `ERR_SEGREGATION_OF_DUTIES` (HTTP 403), which is what prevents one human wearing both the `CourseDesigner` and `PermitOfficer` hats from rubber-stamping their own application."

    Design: Difficulty/non_linear_state_machine/permit_revision_loop_reenters_submitted_and_counts_unbounded_rounds
    """
    venue = fx.venue(api)
    permit = fx.draft_permit(
        api,
        venue["id"],
        valid_until_utc=_VALID_UNTIL_UTC,
        restoration_deadline_utc=_RESTORATION_DEADLINE_UTC,
    )
    permit_id = permit["id"]

    first = _submit(api, permit_id, users.DESIGNER)
    assert first["submitted_by_user_id"] == USER_DESIGNER_1

    # On this round designer-1 is the disqualified identifier.
    validate_error(
        api.decide_permit(
            permit_id,
            f.decision_payload(DECISION_REVISION_REQUESTED),
            users.headers_for(USER_DESIGNER_1, ROLE_PERMIT_OFFICER),
        ),
        ApiErrorId.ERR_SEGREGATION_OF_DUTIES.value,
        403,
    )
    sent_back = _decide(api, permit_id, DECISION_REVISION_REQUESTED, users.OFFICER)
    assert sent_back["revision_rounds"] == 1

    # The loop re-enters under a second designer, overwriting the submitter.
    second = _submit(api, permit_id, users.DESIGNER_2)
    assert second["status"] == PERMIT_SUBMITTED
    assert second["submitted_by_user_id"] == USER_DESIGNER_2

    # designer-2 is now the blocked identifier ...
    validate_error(
        api.decide_permit(
            permit_id,
            f.decision_payload(DECISION_APPROVED),
            users.headers_for(USER_DESIGNER_2, ROLE_PERMIT_OFFICER),
        ),
        ApiErrorId.ERR_SEGREGATION_OF_DUTIES.value,
        403,
    )
    # ... and designer-1, displaced by the re-entry, is free to decide.
    approved = _decide(
        api,
        permit_id,
        DECISION_APPROVED,
        users.headers_for(USER_DESIGNER_1, ROLE_PERMIT_OFFICER),
    )
    assert approved["status"] == PERMIT_APPROVED
    assert approved["decided_by_user_id"] == USER_DESIGNER_1
    assert approved["revision_rounds"] == 1


# ─── non_linear_state_machine / the protest cycle ──────────────────────────


def _two_adjudicated_rounds(api):
    """Walk the cycle twice, upholding both times, and leave it at PROVISIONAL.

    Returns (wave, entry, attempts) with `protest_rounds` reading 2.
    """
    wave, entry, attempts = _finished_entry(api)
    for disputed in (attempts[1], attempts[2]):
        fx.protest(api, entry["id"], entry["participant_id"], disputed["id"])
        _rule(api, entry, RULING_UPHELD_ADJUSTED)
    return wave, entry, attempts


def test_upheld_rulings_return_the_entry_to_provisional_round_after_round(api):
    """PRD §3.8: "An `UPHELD_ADJUSTED` ruling agrees with the participant: the id held in `disputed_attempt_id` is appended to the entry's `voided_attempt_ids` array, the official reading is recomputed with that attempt's penalty suppressed, and the entry returns `UNDER_PROTEST → PROVISIONAL`, from which a second protest naming a different attempt may legitimately follow — the cycle `PROVISIONAL → UNDER_PROTEST → PROVISIONAL` is bounded only by the requirement that `protest_rounds` be strictly fewer than 2 when a protest is filed."

    Design: Difficulty/non_linear_state_machine/entry_result_cycle_provisional_under_protest_bounded_at_two_rounds
    """
    _wave, entry, attempts = _finished_entry(api)
    entry_id = entry["id"]
    participant_id = entry["participant_id"]

    # The provisional reading: gun base 2400s plus 0 + 120 + 90 seconds.
    assert_instant_equals(entry["chip_start_utc"], _CHIP_START_UTC, "chip_start_utc")
    assert_entry_state(
        entry, progress_status=PROGRESS_FINISHED, result_status=RESULT_PROVISIONAL
    )
    assert_timing(
        entry, provisional_penalty_seconds=210, provisional_elapsed_seconds=2610
    )
    assert entry["protest_rounds"] == 0
    assert entry["voided_attempt_ids"] == []

    # ─ Round one: the 120s Mud Pit call is challenged and upheld.
    protested = fx.protest(api, entry_id, participant_id, attempts[1]["id"])
    assert_entry_state(protested, result_status=RESULT_UNDER_PROTEST)
    assert protested["disputed_attempt_id"] == attempts[1]["id"]
    assert protested["protest_rounds"] == 0, "filing a protest is not yet a round"

    first_ruling = _rule(api, entry, RULING_UPHELD_ADJUSTED, note="Video shows a clean lap.")
    assert_entry_state(first_ruling, result_status=RESULT_PROVISIONAL)
    assert first_ruling["protest_rounds"] == 1
    assert first_ruling["voided_attempt_ids"] == [attempts[1]["id"]]
    # Official reading on the chip base of 2363s, now carrying only the 90s.
    assert_timing(
        first_ruling,
        provisional_penalty_seconds=210,
        provisional_elapsed_seconds=2610,
        official_penalty_seconds=90,
        official_elapsed_seconds=2453,
    )

    # ─ Round two: a *different* attempt, admissible because 1 is fewer than 2.
    reprotested = fx.protest(api, entry_id, participant_id, attempts[2]["id"])
    assert_entry_state(reprotested, result_status=RESULT_UNDER_PROTEST)
    assert reprotested["disputed_attempt_id"] == attempts[2]["id"]
    assert reprotested["protest_rounds"] == 1

    second_ruling = _rule(api, entry, RULING_UPHELD_ADJUSTED)
    assert_entry_state(second_ruling, result_status=RESULT_PROVISIONAL)
    assert second_ruling["protest_rounds"] == MAX_PROTEST_ROUNDS
    assert second_ruling["voided_attempt_ids"] == [attempts[1]["id"], attempts[2]["id"]]
    # Both penalties voided: the official reading is now the bare chip base.
    assert_timing(
        second_ruling,
        provisional_penalty_seconds=210,
        provisional_elapsed_seconds=2610,
        official_penalty_seconds=0,
        official_elapsed_seconds=2363,
    )


def test_a_third_protest_is_refused_once_two_rounds_are_adjudicated(api):
    """PRD §3.8: "The entry's `protest_rounds` must be strictly fewer than 2 — a third protest against an entry already carrying two adjudicated rounds is refused with `ERR_PROTEST_ROUNDS_EXHAUSTED`."

    Design: Difficulty/non_linear_state_machine/entry_result_cycle_provisional_under_protest_bounded_at_two_rounds
    """
    _wave, entry, attempts = _two_adjudicated_rounds(api)
    entry_id = entry["id"]
    participant_id = entry["participant_id"]

    at_the_bound = fx.read_entry(api, entry_id)
    # The row sits back at PROVISIONAL, so state alone would admit a protest.
    assert_entry_state(at_the_bound, result_status=RESULT_PROVISIONAL)
    assert at_the_bound["protest_rounds"] == MAX_PROTEST_ROUNDS

    # It is the round count, not the state, that closes the cycle.
    validate_error(
        api.create_protest(
            entry_id,
            f.protest_payload(attempts[0]["id"]),
            users.participant_headers(participant_id),
        ),
        ApiErrorId.ERR_PROTEST_ROUNDS_EXHAUSTED.value,
        409,
    )

    unmoved = fx.read_entry(api, entry_id)
    assert_entry_state(
        unmoved, progress_status=PROGRESS_FINISHED, result_status=RESULT_PROVISIONAL
    )
    assert unmoved["protest_rounds"] == MAX_PROTEST_ROUNDS
    assert unmoved["voided_attempt_ids"] == [attempts[1]["id"], attempts[2]["id"]]
    assert_timing(
        unmoved,
        provisional_penalty_seconds=210,
        provisional_elapsed_seconds=2610,
        official_penalty_seconds=0,
        official_elapsed_seconds=2363,
    )


def test_closing_the_heat_leaves_an_open_dispute_mid_cycle(api):
    """PRD §3.6: "Entries reading `UNDER_PROTEST` are deliberately left `UNDER_PROTEST` — closing a heat does not resolve an open dispute."

    Design: Difficulty/non_linear_state_machine/entry_result_cycle_provisional_under_protest_bounded_at_two_rounds
    """
    wave, entry, attempts = _finished_entry(api)
    entry_id = entry["id"]
    participant_id = entry["participant_id"]

    fx.protest(api, entry_id, participant_id, attempts[1]["id"])
    fx.close(api, wave["id"])
    assert_wave_state(fx.read_wave(api, wave["id"]), release_status=RELEASE_CLOSED)

    # The heat is over and the entry is still mid-cycle: no official reading has
    # been computed for it and no round has been counted.
    stranded = fx.read_entry(api, entry_id)
    assert_entry_state(
        stranded, progress_status=PROGRESS_FINISHED, result_status=RESULT_UNDER_PROTEST
    )
    assert stranded["protest_rounds"] == 0
    assert stranded["official_penalty_seconds"] == 0
    assert stranded["official_elapsed_seconds"] is None
    assert stranded["provisional_elapsed_seconds"] == 2610

    # The cycle resumes after the close and lands back on PROVISIONAL ...
    resumed = _rule(api, entry, RULING_UPHELD_ADJUSTED)
    assert_entry_state(resumed, result_status=RESULT_PROVISIONAL)
    assert resumed["protest_rounds"] == 1
    assert_timing(
        resumed,
        provisional_penalty_seconds=210,
        provisional_elapsed_seconds=2610,
        official_penalty_seconds=90,
        official_elapsed_seconds=2453,
    )

    # ... from which a second round is still admissible on a closed heat.
    again = fx.protest(api, entry_id, participant_id, attempts[2]["id"])
    assert_entry_state(again, result_status=RESULT_UNDER_PROTEST)
    assert again["protest_rounds"] == 1


def test_a_denied_ruling_exits_the_cycle_to_a_terminal_official_result(api):
    """PRD §3.8: "A `DENIED_OFFICIAL` ruling rejects the complaint and closes the matter: the official reading is computed and the entry advances `UNDER_PROTEST → OFFICIAL`, which is terminal."

    Design: Difficulty/non_linear_state_machine/entry_result_cycle_provisional_under_protest_bounded_at_two_rounds
    """
    _wave, entry, attempts = _finished_entry(api)
    entry_id = entry["id"]
    participant_id = entry["participant_id"]

    fx.protest(api, entry_id, participant_id, attempts[1]["id"])
    denied = _rule(api, entry, RULING_DENIED_OFFICIAL, note="The marshal's call stands.")

    # The ruling leaves the loop instead of re-entering it, and nothing is voided.
    assert_entry_state(denied, result_status=RESULT_OFFICIAL)
    assert denied["protest_rounds"] == 1
    assert denied["voided_attempt_ids"] == []
    # Chip base 2363s plus both surviving penalties, 120 + 90.
    assert_timing(
        denied,
        provisional_penalty_seconds=210,
        provisional_elapsed_seconds=2610,
        official_penalty_seconds=210,
        official_elapsed_seconds=2573,
    )

    # One round of two is spent, yet the terminal state — not the count — is
    # what refuses the next protest.
    validate_error(
        api.create_protest(
            entry_id,
            f.protest_payload(attempts[2]["id"]),
            users.participant_headers(participant_id),
        ),
        ApiErrorId.ERR_ENTRY_NOT_PROTESTABLE.value,
        409,
    )
    assert fx.read_entry(api, entry_id)["protest_rounds"] == 1
