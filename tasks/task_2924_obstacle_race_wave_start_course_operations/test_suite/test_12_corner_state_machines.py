"""Corner-case compliance: state machines (breadth index).

Every test below translates exactly one live instance of the
`section: state_machines` block of the corner design index, and each docstring
closes with the `Design:` line naming that instance verbatim.

The runner relaunches the server before every individual test, so each test
builds its own world from an empty database whose logical clock reads
`2026-08-01T00:00:00Z`.
"""

from prd_bench_local_runner.testing import validate_error, validate_success

from test_helpers import constants as c
from test_helpers import factories as f
from test_helpers import fixtures as fx
from test_helpers import test_users as users
from test_helpers.api_errors import ApiErrorId
from test_helpers.assertions import (
    assert_course_capacities,
    assert_entry_state,
    assert_instant_equals,
    assert_obstacle_staffing,
    assert_timing,
    assert_version,
    assert_wave_state,
)

# ─── Race-day instants this file pins beyond the ones factories names ────

#: The second heat of the grid, one 15-minute slot after `f.GUN_UTC`, so the
#: two 6-minute corral windows are disjoint.
_SECOND_GUN_UTC = "2026-09-12T08:15:00.000Z"
_ATTEMPT_UTC = "2026-09-12T08:30:00.000Z"
_FINISH_UTC = "2026-09-12T08:40:00.000Z"
_CLOSE_UTC = "2026-09-12T08:45:00.000Z"

#: Free-text hold reasons supplied by the operator holding a heat.
_HOLD_REASON_OPS_PAUSE = "OPS_PAUSE"
_HOLD_REASON_WEATHER = "WEATHER_CELL"

#: The canonical published course: three dry stations rated 3 / 5 / 7 whose
#: design rates are 12.00, 7.50 and 12.00 against a corral rate of 12.00, so
#: `design_capacity_pph` and `bottleneck_capacity_pph` both read 450.
_CORRAL_RELEASE_RATE_PER_MIN = 12.00
_COURSE_CAPACITY_PPH = 450
_MAX_DISTURBED_AREA_SQM = 5000

_STATION_KWARGS = [
    {
        "name": "Cargo Net",
        "difficulty_rating": 3,
        "lane_count": 4,
        "service_rate_per_min": 3.00,
        "marshals_required": 1,
        "footprint_sqm": 1200,
        "water_contact": False,
        "bypass_mode": c.BYPASS_MODE_NONE,
        "penalty_seconds": 0,
    },
    {
        "name": "Mud Trench",
        "difficulty_rating": 5,
        "lane_count": 3,
        "service_rate_per_min": 2.50,
        "marshals_required": 1,
        "footprint_sqm": 1500,
        "water_contact": False,
        "bypass_mode": c.BYPASS_MODE_MANDATORY,
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
        "bypass_mode": c.BYPASS_MODE_TIMED_PENALTY,
        "penalty_seconds": 90,
    },
]

#: Ada's card on the canonical course: a clean first station, a failed second
#: station charging its 120 penalty seconds, and a clean third station.
_STATION_2_PENALTY_SECONDS = 120
#: 08:00:00 gun to an 08:40:00 finish.
_GUN_BASE_SECONDS = 2400
_ELAPSED_WITH_PENALTY_SECONDS = 2520


# ─── Private world builders ─────────────────────────────────────────────


def _one_station_draft_course(api):
    """An unpermitted DRAFT course carrying a single two-marshal station.

    With no application reading `APPROVED` on the parcel, heat scheduling skips
    the quiet-hours gate entirely. The station's four lanes at 3.00 give a
    design rate of 12.00, so `design_capacity_pph` is 720 and a single heat may
    carry up to 180.
    """
    parcel = fx.venue(api, water_access=c.WATER_ACCESS_POND)
    laid = fx.course(
        api,
        parcel["id"],
        total_distance_m=10000,
        corral_release_rate_per_min=_CORRAL_RELEASE_RATE_PER_MIN,
    )
    station = fx.obstacle(
        api,
        laid["id"],
        1,
        name="Cargo Net",
        difficulty_rating=3,
        lane_count=4,
        service_rate_per_min=3.00,
        marshals_required=2,
        footprint_sqm=1200,
        water_contact=False,
        bypass_mode=c.BYPASS_MODE_NONE,
        penalty_seconds=0,
    )
    return parcel, laid, station


def _one_station_scheduled_heat(api, capacity=10):
    """The unpermitted DRAFT course above plus one SCHEDULED / OPEN heat."""
    parcel, laid, station = _one_station_draft_course(api)
    div = fx.division(api)
    heat = fx.wave(
        api,
        laid["id"],
        div["id"],
        wave_code="S1",
        scheduled_start_utc=f.GUN_UTC,
        capacity=capacity,
    )
    return {
        "venue": parcel,
        "course": laid,
        "station": station,
        "division": div,
        "wave": heat,
    }


def _published_course(api):
    """The canonical published course: three dry stations, one marshal each
    plus one medic, on a parcel whose only application reads `APPROVED`.

    Readiness therefore reads `OPEN` and `bottleneck_capacity_pph` reads 450.
    """
    parcel = fx.venue(api, water_access=c.WATER_ACCESS_NONE)
    permit = fx.approved_permit(
        api,
        parcel["id"],
        water_use_allowed=False,
        max_disturbed_area_sqm=_MAX_DISTURBED_AREA_SQM,
    )
    laid, stations = fx.three_station_course(
        api,
        parcel["id"],
        course_kwargs={
            "total_distance_m": 10000,
            "corral_release_rate_per_min": _CORRAL_RELEASE_RATE_PER_MIN,
        },
        station_kwargs=_STATION_KWARGS,
    )
    fx.published_course(api, laid["id"])
    for station in stations:
        fx.marshal_shift(
            api,
            laid["id"],
            station["id"],
            staff_person_id=f"marshal-person-{station['station_index']}",
        )
    fx.medic_shift(api, laid["id"])
    return parcel, permit, laid, stations


def _published_course_with_heats(api, capacities=(10,)):
    """The canonical published course carrying one or two heats of an OPEN,
    GUN_TIME division on the 15-minute grid."""
    parcel, permit, laid, stations = _published_course(api)
    div = fx.division(api)
    starts = [f.GUN_UTC, _SECOND_GUN_UTC]
    codes = ["S1", "S2"]
    heats = [
        fx.wave(
            api,
            laid["id"],
            div["id"],
            wave_code=codes[index],
            scheduled_start_utc=starts[index],
            capacity=capacity,
        )
        for index, capacity in enumerate(capacities)
    ]
    return {
        "venue": parcel,
        "permit": permit,
        "course": laid,
        "stations": stations,
        "division": div,
        "waves": heats,
    }


# ─── every_new_row_lands_in_its_declared_initial_state ───────────────────


def test_a_freshly_registered_parcel_opens_with_its_whole_bond_held(api):
    """PRD §3.1: "A freshly registered parcel reads `site_posture` of `OPEN`, `disturbed_area_sqm` of 0, `bond_released_cents` and `bond_forfeited_cents` of 0, and `bond_held_cents` equal to the whole `restoration_bond_cents`."

    Design: Corner/state_machines/every_new_row_lands_in_its_declared_initial_state
    """
    response = api.create_venue(
        f.venue_payload(protected_acreage_sqm=2000, restoration_bond_cents=1000000),
        users.OFFICER,
    )
    parcel = validate_success(response, expected_status=201)

    assert parcel["site_posture"] == c.SITE_POSTURE_OPEN
    assert parcel["disturbed_area_sqm"] == 0
    assert parcel["bond_released_cents"] == 0
    assert parcel["bond_forfeited_cents"] == 0
    assert parcel["bond_held_cents"] == parcel["restoration_bond_cents"] == 1000000


def test_a_new_land_use_application_lands_in_draft_with_no_operators_stamped(api):
    """PRD §3.1: "A new application reads `status` of `DRAFT` with `revision_rounds` of 0, `submitted_by_user_id` and `decided_by_user_id` both null, and `decision_note` null."

    Design: Corner/state_machines/every_new_row_lands_in_its_declared_initial_state
    """
    parcel = fx.venue(api)

    response = api.create_permit(parcel["id"], f.permit_payload(), users.DESIGNER)
    application = validate_success(response, expected_status=201)

    assert application["status"] == c.PERMIT_DRAFT
    assert application["revision_rounds"] == 0
    assert application["submitted_by_user_id"] is None
    assert application["decided_by_user_id"] is None
    assert application["decision_note"] is None


def test_a_new_course_lands_in_draft_and_restricted_with_every_derived_number_zero(api):
    """PRD §3.2: "A new course reads `status` of `DRAFT` and `readiness_posture` of `RESTRICTED`, with `obstacle_count`, `difficulty_progression_score`, `design_capacity_pph`, `bottleneck_capacity_pph`, `medic_headcount`, `water_safety_headcount` and `scheduled_capacity_total` all at 0."

    Design: Corner/state_machines/every_new_row_lands_in_its_declared_initial_state
    """
    parcel = fx.venue(api)

    response = api.create_course(
        parcel["id"],
        f.course_payload(
            total_distance_m=10000,
            corral_release_rate_per_min=_CORRAL_RELEASE_RATE_PER_MIN,
        ),
        users.DESIGNER,
    )
    laid = validate_success(response, expected_status=201)

    assert_course_capacities(
        laid,
        design_capacity_pph=0,
        bottleneck_capacity_pph=0,
        scheduled_capacity_total=0,
        readiness_posture=c.READINESS_RESTRICTED,
        status=c.COURSE_DRAFT,
    )
    assert laid["obstacle_count"] == 0
    assert float(laid["difficulty_progression_score"]) == 0.0
    assert laid["medic_headcount"] == 0
    assert laid["water_safety_headcount"] == 0


def test_a_newly_scheduled_heat_lands_in_scheduled_on_one_axis_and_open_on_the_other(api):
    """PRD §3.4: "A newly scheduled heat reads `release_status` of `SCHEDULED`, `roster_status` of `OPEN`, `assigned_count` of 0, and `hold_reason`, `actual_start_utc` and `closed_at_utc` all null."

    Design: Corner/state_machines/every_new_row_lands_in_its_declared_initial_state
    """
    _, laid, _ = _one_station_draft_course(api)
    div = fx.division(api)

    response = api.create_wave(
        laid["id"],
        f.wave_payload(
            div["id"], wave_code="S1", scheduled_start_utc=f.GUN_UTC, capacity=10
        ),
        users.DIRECTOR,
    )
    heat = validate_success(response, expected_status=201)

    assert_wave_state(
        heat,
        release_status=c.RELEASE_SCHEDULED,
        roster_status=c.ROSTER_OPEN,
        hold_reason=None,
    )
    assert heat["assigned_count"] == 0
    assert heat["actual_start_utc"] is None
    assert heat["closed_at_utc"] is None


def test_a_new_entry_lands_in_registered_on_one_axis_and_pending_on_the_other(api):
    """PRD §3.5: "A new entry reads `progress_status` of `REGISTERED` and `result_status` of `PENDING`, with `bag_tag_code` null, `chip_start_offset_seconds` of 0, `chip_start_utc` and `finish_recorded_utc` null, `provisional_penalty_seconds` and `official_penalty_seconds` of 0, `provisional_elapsed_seconds` and `official_elapsed_seconds` null, `disputed_attempt_id` null, `protest_rounds` of 0, an empty `voided_attempt_ids` array and `dq_reason` null."

    Design: Corner/state_machines/every_new_row_lands_in_its_declared_initial_state
    """
    world = _one_station_scheduled_heat(api)
    human = fx.cleared_participant(api)

    response = api.create_entry(
        world["wave"]["id"], f.entry_payload(human["id"], bib_number=1), users.OPS
    )
    card = validate_success(response, expected_status=201)

    assert_entry_state(
        card,
        progress_status=c.PROGRESS_REGISTERED,
        result_status=c.RESULT_PENDING,
    )
    assert card["bag_tag_code"] is None
    assert card["chip_start_offset_seconds"] == 0
    assert card["chip_start_utc"] is None
    assert card["finish_recorded_utc"] is None
    assert_timing(card, provisional_penalty_seconds=0, official_penalty_seconds=0)
    assert card["provisional_elapsed_seconds"] is None
    assert card["official_elapsed_seconds"] is None
    assert card["disputed_attempt_id"] is None
    assert card["protest_rounds"] == 0
    assert card["voided_attempt_ids"] == []
    assert card["dq_reason"] is None


def test_a_newly_enrolled_human_is_unsigned_and_pending_clearance(api):
    """PRD §3.5: "Enrolment deliberately does not sign the waiver: a new participant reads `waiver_signed` of false, `clearance_status` of `PENDING` and an empty `medical_flags` array."

    Design: Corner/state_machines/every_new_row_lands_in_its_declared_initial_state
    """
    response = api.create_participant(
        f.participant_payload(full_name="Ben Stone", birth_year=1995), users.OPS
    )
    human = validate_success(response, expected_status=201)

    assert human["waiver_signed"] is False
    assert human["clearance_status"] == c.CLEARANCE_PENDING
    assert human["medical_flags"] == []


def test_one_marshal_against_two_required_lands_on_partial_never_marshaled(api):
    """PRD §3.3: "Confirming a `MARSHAL` shift raises the station's `confirmed_marshal_count`, which is the number of shifts reading `CONFIRMED` with `staff_role` of `MARSHAL` at that obstacle, and recomputes the station's `staffing_state`: `UNSTAFFED` when the confirmed marshal count is zero, `PARTIAL` when it is greater than zero but still below `marshals_required`, and `MARSHALED` when it is `marshals_required` or more."

    Design: Corner/state_machines/every_new_row_lands_in_its_declared_initial_state
    """
    _, laid, station = _one_station_draft_course(api)
    assert station["marshals_required"] == 2
    assert_obstacle_staffing(
        station, staffing_state=c.STAFFING_UNSTAFFED, confirmed_marshal_count=0
    )

    fx.marshal_shift(
        api, laid["id"], station["id"], staff_person_id=c.STAFF_PERSON_1
    )

    reread = fx.read_obstacle(api, station["id"])
    assert_obstacle_staffing(
        reread, staffing_state=c.STAFFING_PARTIAL, confirmed_marshal_count=1
    )


# ─── permit_moves_draft_to_submitted_to_approved_and_stamps_both_operators ─


def test_submission_stamps_the_acting_designer_into_submitted_by_user_id(api):
    """PRD §3.1: "A `DRAFT` application advances `DRAFT → SUBMITTED`, and an application that came back for rework advances `REVISION_REQUESTED → SUBMITTED`; in both directions the parcel must read `site_posture` of `OPEN`, and in both directions the acting `X-User-ID` is written into `submitted_by_user_id`, overwriting whatever was there from an earlier round."

    Design: Corner/state_machines/permit_moves_draft_to_submitted_to_approved_and_stamps_both_operators
    """
    parcel = fx.venue(api)
    application = fx.draft_permit(api, parcel["id"])

    response = api.submit_permit(application["id"], users.DESIGNER)
    submitted = validate_success(response, expected_status=200)

    assert submitted["status"] == c.PERMIT_SUBMITTED
    assert submitted["submitted_by_user_id"] == c.USER_DESIGNER_1


def test_the_decision_stamps_the_deciding_officer_and_stores_its_note(api):
    """PRD §3.1: "Every decision writes the acting `X-User-ID` into `decided_by_user_id`, and every decision is blocked when that identifier equals `submitted_by_user_id`."

    Design: Corner/state_machines/permit_moves_draft_to_submitted_to_approved_and_stamps_both_operators
    """
    parcel = fx.venue(api)
    application = fx.submitted_permit(api, parcel["id"])

    response = api.decide_permit(
        application["id"],
        f.decision_payload(c.DECISION_APPROVED, decision_note="Approved as filed"),
        users.OFFICER,
    )
    decided = validate_success(response, expected_status=200)

    assert decided["status"] == c.PERMIT_APPROVED
    assert decided["decided_by_user_id"] == c.USER_OFFICER_1
    assert decided["submitted_by_user_id"] == c.USER_DESIGNER_1
    assert decided["decision_note"] == "Approved as filed"
    assert decided["revision_rounds"] == 0


def test_the_two_step_approval_walk_bumps_the_permit_version_once_per_step(api):
    """PRD §2.4: "Most resources additionally carry an `updated_at` timestamp in the same ISO 8601 UTC format with three fractional digits, and a `version` integer that begins at 1 when the row is created and increases by exactly 1 on every mutation of that row — including mutations caused by a cascade from another entity rather than by a request addressed to the row directly."

    Design: Corner/state_machines/permit_moves_draft_to_submitted_to_approved_and_stamps_both_operators
    """
    parcel = fx.venue(api)
    application = fx.draft_permit(api, parcel["id"])
    assert_version(application, 1, "drafted application")

    submitted = validate_success(
        api.submit_permit(application["id"], users.DESIGNER), expected_status=200
    )
    assert_version(submitted, 2, "submitted application")

    decided = validate_success(
        api.decide_permit(
            application["id"],
            f.decision_payload(c.DECISION_APPROVED, decision_note="Approved as filed"),
            users.OFFICER,
        ),
        expected_status=200,
    )
    assert_version(decided, 3, "approved application")


# ─── a_blocking_medical_flag_routes_the_waiver_to_medically_held ──────────


def test_a_cardiac_flag_routes_the_waiver_to_medically_held(api):
    """PRD §3.5: "When at least one of those three appears, the participant advances `PENDING → MEDICALLY_HELD` instead."

    Design: Corner/state_machines/a_blocking_medical_flag_routes_the_waiver_to_medically_held
    """
    human = fx.participant(api, full_name="Cara Vale", birth_year=1990)

    response = api.sign_waiver(
        human["id"],
        f.waiver_payload(
            signature_name="Cara Vale", medical_flags=[c.MEDICAL_FLAG_CARDIAC]
        ),
        users.participant_headers(human["id"]),
    )
    signed = validate_success(response, expected_status=200)

    assert signed["clearance_status"] == c.CLEARANCE_MEDICALLY_HELD


def test_the_held_branch_still_signs_the_waiver_and_stores_the_declared_flags(api):
    """PRD §3.5: "Signing always sets `waiver_signed` to true and always stores the declared `medical_flags`, but it resolves `clearance_status` in one of two directions from `PENDING`."

    Design: Corner/state_machines/a_blocking_medical_flag_routes_the_waiver_to_medically_held
    """
    human = fx.participant(api, full_name="Cara Vale", birth_year=1990)

    signed = validate_success(
        api.sign_waiver(
            human["id"],
            f.waiver_payload(
                signature_name="Cara Vale", medical_flags=[c.MEDICAL_FLAG_CARDIAC]
            ),
            users.participant_headers(human["id"]),
        ),
        expected_status=200,
    )

    assert signed["waiver_signed"] is True
    assert signed["medical_flags"] == [c.MEDICAL_FLAG_CARDIAC]
    assert signed["clearance_status"] != c.CLEARANCE_PENDING


def test_a_medically_held_human_may_register_but_is_refused_at_bag_check(api):
    """PRD §3.5: "The participant's `clearance_status` must read `CLEARED` — a `PENDING` or `MEDICALLY_HELD` human is refused with `ERR_PARTICIPANT_NOT_CLEARED`."

    Design: Corner/state_machines/a_blocking_medical_flag_routes_the_waiver_to_medically_held
    """
    world = _one_station_scheduled_heat(api)
    held = fx.held_participant(
        api, [c.MEDICAL_FLAG_CARDIAC], full_name="Cara Vale", birth_year=1990
    )
    assert held["clearance_status"] == c.CLEARANCE_MEDICALLY_HELD

    card = validate_success(
        api.create_entry(
            world["wave"]["id"], f.entry_payload(held["id"], bib_number=7), users.OPS
        ),
        expected_status=201,
    )

    refusal = api.check_in_entry(
        card["id"],
        f.check_in_payload(15, bag_tag_code="BAG-007"),
        users.OPS,
    )
    validate_error(
        refusal, ApiErrorId.ERR_PARTICIPANT_NOT_CLEARED.value, expected_status=409
    )

    assert_entry_state(
        fx.read_entry(api, card["id"]), progress_status=c.PROGRESS_REGISTERED
    )


# ─── release_refuses_an_open_roster_and_then_refuses_an_empty_locked_roster ─


def test_release_refuses_a_heat_whose_roster_is_still_open(api):
    """PRD §3.6: "Its `roster_status` must be `LOCKED` or `SEALED`; a still-`OPEN` roster is refused with `ERR_WAVE_ROSTER_NOT_LOCKED`."

    Design: Corner/state_machines/release_refuses_an_open_roster_and_then_refuses_an_empty_locked_roster
    """
    world = _published_course_with_heats(api, capacities=(10, 10))
    first_heat = world["waves"][0]
    fx.checked_in_entry(
        api, first_heat["id"], bib_number=1, chip_start_offset_seconds=20
    )

    refusal = api.release_wave(first_heat["id"], users.DIRECTOR)
    validate_error(
        refusal, ApiErrorId.ERR_WAVE_ROSTER_NOT_LOCKED.value, expected_status=409
    )

    assert_wave_state(
        fx.read_wave(api, first_heat["id"]),
        release_status=c.RELEASE_SCHEDULED,
        roster_status=c.ROSTER_OPEN,
    )
    assert_course_capacities(
        fx.read_course(api, world["course"]["id"]),
        bottleneck_capacity_pph=_COURSE_CAPACITY_PPH,
        readiness_posture=c.READINESS_OPEN,
    )


def test_release_refuses_a_locked_but_empty_roster(api):
    """PRD §3.6: "The heat must have at least one entry assigned — an `assigned_count` of 0 is refused with `ERR_WAVE_ROSTER_EMPTY`."

    Design: Corner/state_machines/release_refuses_an_open_roster_and_then_refuses_an_empty_locked_roster
    """
    world = _published_course_with_heats(api, capacities=(10, 10))
    second_heat = world["waves"][1]
    fx.checked_in_entry(
        api, world["waves"][0]["id"], bib_number=1, chip_start_offset_seconds=20
    )
    locked = fx.lock_roster(api, second_heat["id"])
    assert locked["assigned_count"] == 0

    refusal = api.release_wave(second_heat["id"], users.DIRECTOR)
    validate_error(
        refusal, ApiErrorId.ERR_WAVE_ROSTER_EMPTY.value, expected_status=409
    )

    reread = fx.read_wave(api, second_heat["id"])
    assert_wave_state(
        reread,
        release_status=c.RELEASE_SCHEDULED,
        roster_status=c.ROSTER_LOCKED,
    )
    assert reread["assigned_count"] == 0
    assert_course_capacities(
        fx.read_course(api, world["course"]["id"]),
        bottleneck_capacity_pph=_COURSE_CAPACITY_PPH,
        readiness_posture=c.READINESS_OPEN,
    )


# ─── start_and_close_are_not_reachable_triggers_from_the_scheduled_state ──


def test_the_gun_is_not_a_reachable_trigger_from_the_scheduled_state(api):
    """PRD §3.6: "Starting from any `release_status` other than `RELEASED` is refused with `ERR_WAVE_STATE_INVALID`."

    Design: Corner/state_machines/start_and_close_are_not_reachable_triggers_from_the_scheduled_state
    """
    world = _one_station_scheduled_heat(api)

    refusal = api.start_wave(world["wave"]["id"], users.DIRECTOR)
    validate_error(
        refusal, ApiErrorId.ERR_WAVE_STATE_INVALID.value, expected_status=409
    )

    reread = fx.read_wave(api, world["wave"]["id"])
    assert_wave_state(reread, release_status=c.RELEASE_SCHEDULED)
    assert reread["actual_start_utc"] is None


def test_the_close_is_not_a_reachable_trigger_from_the_scheduled_state(api):
    """PRD §3.6: "Closing the heat advances `STARTED → CLOSED` under a `RaceDirector` and is refused from any other `release_status` with `ERR_WAVE_STATE_INVALID`."

    Design: Corner/state_machines/start_and_close_are_not_reachable_triggers_from_the_scheduled_state
    """
    world = _one_station_scheduled_heat(api)

    refusal = api.close_wave(world["wave"]["id"], users.DIRECTOR)
    validate_error(
        refusal, ApiErrorId.ERR_WAVE_STATE_INVALID.value, expected_status=409
    )

    reread = fx.read_wave(api, world["wave"]["id"])
    assert_wave_state(reread, release_status=c.RELEASE_SCHEDULED)
    assert reread["closed_at_utc"] is None
    assert_course_capacities(
        fx.read_course(api, world["course"]["id"]), status=c.COURSE_DRAFT
    )


# ─── an_approved_permit_is_terminal_and_blocks_a_second_approval_on_the_parcel ─


def test_resubmitting_an_approved_application_is_refused(api):
    """PRD §3.1: "Submission from any other state is refused with `ERR_PERMIT_STATE_INVALID`, and submission against a frozen or closed-out parcel is refused with `ERR_VENUE_FROZEN`."

    Design: Corner/state_machines/an_approved_permit_is_terminal_and_blocks_a_second_approval_on_the_parcel
    """
    parcel = fx.venue(api)
    governing = fx.approved_permit(api, parcel["id"])
    assert governing["status"] == c.PERMIT_APPROVED

    refusal = api.submit_permit(governing["id"], users.DESIGNER)
    validate_error(
        refusal, ApiErrorId.ERR_PERMIT_STATE_INVALID.value, expected_status=409
    )

    assert fx.read_permit(api, governing["id"])["status"] == c.PERMIT_APPROVED


def test_redeciding_an_approved_application_is_refused(api):
    """PRD §3.1: "A decision on an application that is not `SUBMITTED` is refused with `ERR_PERMIT_STATE_INVALID`."

    Design: Corner/state_machines/an_approved_permit_is_terminal_and_blocks_a_second_approval_on_the_parcel
    """
    parcel = fx.venue(api)
    governing = fx.approved_permit(api, parcel["id"])

    refusal = api.decide_permit(
        governing["id"],
        f.decision_payload(c.DECISION_DENIED, decision_note="Late objection"),
        users.OFFICER,
    )
    validate_error(
        refusal, ApiErrorId.ERR_PERMIT_STATE_INVALID.value, expected_status=409
    )

    assert fx.read_permit(api, governing["id"])["status"] == c.PERMIT_APPROVED
    assert fx.read_venue(api, parcel["id"])["site_posture"] == c.SITE_POSTURE_OPEN


def test_a_second_approval_on_the_same_parcel_is_refused(api):
    """PRD §3.1: "A decision of `APPROVED` moves `SUBMITTED → APPROVED` but only when no *other* application on the same parcel already reads `APPROVED`; if one does, the approval is refused with `ERR_PERMIT_ALREADY_APPROVED`."

    Design: Corner/state_machines/an_approved_permit_is_terminal_and_blocks_a_second_approval_on_the_parcel
    """
    parcel = fx.venue(api)
    fx.approved_permit(api, parcel["id"])
    contender = fx.submitted_permit(
        api, parcel["id"], max_disturbed_area_sqm=9000
    )
    assert contender["status"] == c.PERMIT_SUBMITTED

    refusal = api.decide_permit(
        contender["id"],
        f.decision_payload(
            c.DECISION_APPROVED, decision_note="Second approval attempt"
        ),
        users.OFFICER,
    )
    validate_error(
        refusal, ApiErrorId.ERR_PERMIT_ALREADY_APPROVED.value, expected_status=409
    )

    assert fx.read_permit(api, contender["id"])["status"] == c.PERMIT_SUBMITTED


# ─── repeating_lock_roster_and_vacate_is_refused_with_the_state_specific_code ─


def test_a_second_lock_roster_is_refused_with_the_wave_state_code(api):
    """PRD §3.6: "Locking an already locked or sealed roster is refused with `ERR_WAVE_STATE_INVALID`."

    Design: Corner/state_machines/repeating_lock_roster_and_vacate_is_refused_with_the_state_specific_code
    """
    world = _one_station_scheduled_heat(api)
    locked = fx.lock_roster(api, world["wave"]["id"])
    assert_wave_state(locked, roster_status=c.ROSTER_LOCKED)

    refusal = api.lock_roster(world["wave"]["id"], users.DIRECTOR)
    validate_error(
        refusal, ApiErrorId.ERR_WAVE_STATE_INVALID.value, expected_status=409
    )

    assert_wave_state(
        fx.read_wave(api, world["wave"]["id"]),
        release_status=c.RELEASE_SCHEDULED,
        roster_status=c.ROSTER_LOCKED,
    )


def test_a_second_vacate_is_refused_with_the_assignment_code_and_decrements_nothing(api):
    """PRD §3.3: "The shift must read `CONFIRMED`; vacating an already-vacated shift is refused with `ERR_ASSIGNMENT_NOT_ACTIVE`."

    Design: Corner/state_machines/repeating_lock_roster_and_vacate_is_refused_with_the_state_specific_code
    """
    _, laid, station = _one_station_draft_course(api)
    first_shift = fx.marshal_shift(
        api, laid["id"], station["id"], staff_person_id=c.STAFF_PERSON_1
    )
    second_shift = fx.marshal_shift(
        api, laid["id"], station["id"], staff_person_id=c.STAFF_PERSON_2
    )

    vacated = fx.vacate(api, first_shift["id"], reason="No-show")
    assert vacated["status"] == c.ASSIGNMENT_VACATED

    refusal = api.vacate_staff_assignment(
        first_shift["id"], f.vacate_payload("No-show again"), users.SAFETY
    )
    validate_error(
        refusal, ApiErrorId.ERR_ASSIGNMENT_NOT_ACTIVE.value, expected_status=409
    )

    assert_obstacle_staffing(
        fx.read_obstacle(api, station["id"]),
        staffing_state=c.STAFFING_PARTIAL,
        confirmed_marshal_count=1,
    )
    still_rostered = validate_success(
        api.get_staff_assignment(second_shift["id"], users.SAFETY),
        expected_status=200,
    )
    assert still_rostered["status"] == c.ASSIGNMENT_CONFIRMED


# ─── closing_the_heat_fans_out_dnf_official_readings_and_completes_the_course ─


def _heat_ready_to_close(api, capacities=(10,)):
    """Run one heat of the canonical course up to the instant before the close.

    Ada checks in, starts, clears station 1, fails station 2 for its 120
    penalty seconds, clears station 3 and finishes at 08:40 — a gun base of
    2400 seconds and a provisional elapsed reading of 2520. Bo checks in and
    starts but never finishes, so the close still finds him out on the course.
    The clock is left at `_CLOSE_UTC`.
    """
    world = _published_course_with_heats(api, capacities=capacities)
    heat = world["waves"][0]
    ada = fx.checked_in_entry(
        api, heat["id"], bib_number=1, chip_start_offset_seconds=20
    )
    bo = fx.checked_in_entry(api, heat["id"], bib_number=2, chip_start_offset_seconds=30)

    fx.lock_roster(api, heat["id"])
    fx.release(api, heat["id"])
    fx.set_clock(api, f.GUN_UTC)
    fx.start(api, heat["id"])

    fx.set_clock(api, _ATTEMPT_UTC)
    card = [c.OUTCOME_COMPLETED, c.OUTCOME_FAILED_PENALTY, c.OUTCOME_COMPLETED]
    for station, outcome in zip(world["stations"], card):
        fx.attempt(api, ada["id"], station["id"], outcome)

    fx.set_clock(api, _FINISH_UTC)
    finished = fx.finish(api, ada["id"])
    assert_entry_state(
        finished, progress_status=c.PROGRESS_FINISHED, result_status=c.RESULT_PROVISIONAL
    )

    fx.set_clock(api, _CLOSE_UTC)
    world["ada"] = ada
    world["bo"] = bo
    return world


def test_the_close_stamps_closed_at_utc_from_the_logical_clock(api):
    """PRD §3.6: "The close stamps `closed_at_utc` from the logical clock."

    Design: Corner/state_machines/closing_the_heat_fans_out_dnf_official_readings_and_completes_the_course
    """
    world = _heat_ready_to_close(api)

    closed = fx.close(api, world["waves"][0]["id"])

    assert_wave_state(closed, release_status=c.RELEASE_CLOSED)
    assert_instant_equals(closed["closed_at_utc"], _CLOSE_UTC, "closed_at_utc")


def test_a_runner_still_out_on_the_course_is_swept_to_dnf_and_not_classified(api):
    """PRD §3.6: "Every entry still reading `progress_status` of `STARTED` — still out on the course when the heat closed — advances to `DNF` with `result_status` set to `NOT_CLASSIFIED`."

    Design: Corner/state_machines/closing_the_heat_fans_out_dnf_official_readings_and_completes_the_course
    """
    world = _heat_ready_to_close(api)
    still_running = fx.read_entry(api, world["bo"]["id"])
    assert_entry_state(still_running, progress_status=c.PROGRESS_STARTED)

    fx.close(api, world["waves"][0]["id"])

    swept = fx.read_entry(api, world["bo"]["id"])
    assert_entry_state(
        swept,
        progress_status=c.PROGRESS_DNF,
        result_status=c.RESULT_NOT_CLASSIFIED,
    )


def test_the_close_takes_a_provisional_finisher_official_with_its_own_reading(api):
    """PRD §3.6: "Every entry reading `result_status` of `PROVISIONAL` advances `PROVISIONAL → OFFICIAL`, with `official_penalty_seconds` and `official_elapsed_seconds` computed by the official reading described in §3.8."

    Design: Corner/state_machines/closing_the_heat_fans_out_dnf_official_readings_and_completes_the_course
    """
    world = _heat_ready_to_close(api)

    fx.close(api, world["waves"][0]["id"])

    official = fx.read_entry(api, world["ada"]["id"])
    assert_entry_state(
        official,
        progress_status=c.PROGRESS_FINISHED,
        result_status=c.RESULT_OFFICIAL,
    )
    assert_timing(
        official,
        official_penalty_seconds=_STATION_2_PENALTY_SECONDS,
        official_elapsed_seconds=_ELAPSED_WITH_PENALTY_SECONDS,
    )


def test_closing_the_only_heat_completes_the_course_and_zeroes_its_scheduled_total(api):
    """PRD §3.6: "When the heat that just closed leaves no heat of that course outside `CLOSED`, and the course has at least one heat, the course advances `PUBLISHED → COMPLETED` automatically, and its `scheduled_capacity_total` recomputes to 0 because no heat remains in `SCHEDULED`, `HELD`, `RELEASED` or `STARTED`."

    Design: Corner/state_machines/closing_the_heat_fans_out_dnf_official_readings_and_completes_the_course
    """
    world = _heat_ready_to_close(api)
    assert_course_capacities(
        fx.read_course(api, world["course"]["id"]),
        status=c.COURSE_PUBLISHED,
        scheduled_capacity_total=10,
    )

    fx.close(api, world["waves"][0]["id"])

    assert_course_capacities(
        fx.read_course(api, world["course"]["id"]),
        status=c.COURSE_COMPLETED,
        scheduled_capacity_total=0,
    )


# ─── the_course_stays_published_until_the_last_heat_closes ────────────────


def test_closing_one_of_two_heats_leaves_the_course_published(api):
    """PRD §3.6: "When the heat that just closed leaves no heat of that course outside `CLOSED`, and the course has at least one heat, the course advances `PUBLISHED → COMPLETED` automatically, and its `scheduled_capacity_total` recomputes to 0 because no heat remains in `SCHEDULED`, `HELD`, `RELEASED` or `STARTED`."

    Design: Corner/state_machines/the_course_stays_published_until_the_last_heat_closes
    """
    world = _heat_ready_to_close(api, capacities=(10, 20))
    second_heat = world["waves"][1]

    fx.close(api, world["waves"][0]["id"])

    assert_course_capacities(
        fx.read_course(api, world["course"]["id"]), status=c.COURSE_PUBLISHED
    )
    assert_wave_state(
        fx.read_wave(api, second_heat["id"]), release_status=c.RELEASE_SCHEDULED
    )


def test_the_course_completes_only_once_the_second_heat_closes_too(api):
    """PRD §3.6: "When the heat that just closed leaves no heat of that course outside `CLOSED`, and the course has at least one heat, the course advances `PUBLISHED → COMPLETED` automatically, and its `scheduled_capacity_total` recomputes to 0 because no heat remains in `SCHEDULED`, `HELD`, `RELEASED` or `STARTED`."

    Design: Corner/state_machines/the_course_stays_published_until_the_last_heat_closes
    """
    world = _heat_ready_to_close(api, capacities=(10, 20))
    second_heat = world["waves"][1]
    fx.close(api, world["waves"][0]["id"])
    assert_course_capacities(
        fx.read_course(api, world["course"]["id"]), status=c.COURSE_PUBLISHED
    )

    fx.checked_in_entry(api, second_heat["id"], bib_number=11)
    fx.lock_roster(api, second_heat["id"])
    fx.release(api, second_heat["id"])
    fx.start(api, second_heat["id"])
    fx.close(api, second_heat["id"])

    assert_course_capacities(
        fx.read_course(api, world["course"]["id"]),
        status=c.COURSE_COMPLETED,
        scheduled_capacity_total=0,
    )


# ─── parent_scheduled_capacity_is_rederived_as_heats_are_added_and_held ───


def test_the_scheduled_total_sums_the_heats_and_keeps_counting_a_held_heat(api):
    """PRD §3.4: "Creating a heat recomputes the course's `scheduled_capacity_total` — the sum of `capacity` over the heats of that course whose `release_status` is `SCHEDULED`, `HELD`, `RELEASED` or `STARTED` — and therefore also recomputes the course's `readiness_posture`, because the medic requirement scales with that total."

    Design: Corner/state_machines/parent_scheduled_capacity_is_rederived_as_heats_are_added_and_held
    """
    _, laid, _station = _one_station_draft_course(api)
    div = fx.division(api)

    fx.wave(
        api,
        laid["id"],
        div["id"],
        wave_code="S1",
        scheduled_start_utc=f.GUN_UTC,
        capacity=10,
    )
    assert_course_capacities(
        fx.read_course(api, laid["id"]), scheduled_capacity_total=10
    )

    second_heat = fx.wave(
        api,
        laid["id"],
        div["id"],
        wave_code="S2",
        scheduled_start_utc=_SECOND_GUN_UTC,
        capacity=20,
    )
    assert_course_capacities(
        fx.read_course(api, laid["id"]), scheduled_capacity_total=30
    )

    held = fx.hold(api, second_heat["id"], reason=_HOLD_REASON_OPS_PAUSE)
    assert_wave_state(held, release_status=c.RELEASE_HELD)
    assert_course_capacities(
        fx.read_course(api, laid["id"]), scheduled_capacity_total=30
    )


# ─── the_release_and_roster_dimensions_move_without_disturbing_each_other ──


def test_locking_the_roster_leaves_the_start_line_dimension_untouched(api):
    """PRD §3.6: "Locking the roster is a `RaceDirector` move that advances `OPEN → LOCKED` and leaves `release_status` completely untouched."

    Design: Corner/state_machines/the_release_and_roster_dimensions_move_without_disturbing_each_other
    """
    world = _one_station_scheduled_heat(api)
    assert_wave_state(
        world["wave"],
        release_status=c.RELEASE_SCHEDULED,
        roster_status=c.ROSTER_OPEN,
    )

    locked = fx.lock_roster(api, world["wave"]["id"])

    assert_wave_state(
        locked, release_status=c.RELEASE_SCHEDULED, roster_status=c.ROSTER_LOCKED
    )
    assert_wave_state(
        fx.read_wave(api, world["wave"]["id"]),
        release_status=c.RELEASE_SCHEDULED,
        roster_status=c.ROSTER_LOCKED,
    )


def test_the_hold_loop_runs_both_ways_without_disturbing_the_locked_roster(api):
    """PRD §3.6: "`SCHEDULED` and `HELD` form a two-state loop that may be traversed any number of times, and `roster_status` is untouched in both directions."

    Design: Corner/state_machines/the_release_and_roster_dimensions_move_without_disturbing_each_other
    """
    world = _published_course_with_heats(api)
    heat_id = world["waves"][0]["id"]
    fx.lock_roster(api, heat_id)

    held = fx.hold(api, heat_id, reason=_HOLD_REASON_WEATHER)
    assert_wave_state(
        held,
        release_status=c.RELEASE_HELD,
        roster_status=c.ROSTER_LOCKED,
        hold_reason=_HOLD_REASON_WEATHER,
    )

    resumed = fx.unhold(api, heat_id)
    assert_wave_state(
        resumed,
        release_status=c.RELEASE_SCHEDULED,
        roster_status=c.ROSTER_LOCKED,
        hold_reason=None,
    )

    held_again = fx.hold(api, heat_id, reason=_HOLD_REASON_OPS_PAUSE)
    assert_wave_state(
        held_again,
        release_status=c.RELEASE_HELD,
        roster_status=c.ROSTER_LOCKED,
        hold_reason=_HOLD_REASON_OPS_PAUSE,
    )


def test_each_move_on_either_dimension_bumps_the_heats_version_once(api):
    """PRD §2.4: "Most resources additionally carry an `updated_at` timestamp in the same ISO 8601 UTC format with three fractional digits, and a `version` integer that begins at 1 when the row is created and increases by exactly 1 on every mutation of that row — including mutations caused by a cascade from another entity rather than by a request addressed to the row directly."

    Design: Corner/state_machines/the_release_and_roster_dimensions_move_without_disturbing_each_other
    """
    world = _published_course_with_heats(api)
    heat = world["waves"][0]
    assert_version(heat, 1, "wave on creation")

    locked = fx.lock_roster(api, heat["id"])
    assert_version(locked, 2, "wave after the roster lock")

    held = fx.hold(api, heat["id"], reason=_HOLD_REASON_WEATHER)
    assert_version(held, 3, "wave after the hold")


# ─── one_submitted_permit_forks_three_ways_and_only_denial_freezes_its_parcel ─


def test_a_revision_request_sends_the_application_back_and_counts_the_round(api):
    """PRD §3.1: "A decision of `REVISION_REQUESTED` moves `SUBMITTED → REVISION_REQUESTED` and increments `revision_rounds` by 1; the loop `SUBMITTED → REVISION_REQUESTED → SUBMITTED` may run any number of times and `revision_rounds` simply records how many times it has, with no ceiling."

    Design: Corner/state_machines/one_submitted_permit_forks_three_ways_and_only_denial_freezes_its_parcel
    """
    parcel = fx.venue(api)
    application = fx.submitted_permit(api, parcel["id"])
    assert application["revision_rounds"] == 0

    first_round = validate_success(
        api.decide_permit(
            application["id"],
            f.decision_payload(
                c.DECISION_REVISION_REQUESTED, decision_note="Redraw the water crossing"
            ),
            users.OFFICER,
        ),
        expected_status=200,
    )
    assert first_round["status"] == c.PERMIT_REVISION_REQUESTED
    assert first_round["revision_rounds"] == 1


def test_a_denial_freezes_the_parcel_it_was_filed_against(api):
    """PRD §3.1: "A decision of `DENIED` moves `SUBMITTED → DENIED` and is the head of the four-link freeze chain of §2.10: the parcel goes `OPEN → FROZEN`, its `DRAFT`, `VALIDATED` and `PUBLISHED` courses go to `SUSPENDED` with `readiness_posture` forced to `FROZEN`, the `SCHEDULED` and `HELD` heats on those courses go to `HELD` with `hold_reason` of `VENUE_FROZEN`, and every `OPEN` festival installation on the parcel goes to `CLOSED`."

    Design: Corner/state_machines/one_submitted_permit_forks_three_ways_and_only_denial_freezes_its_parcel
    """
    parcel = fx.venue(api)
    application = fx.submitted_permit(api, parcel["id"])

    denied = validate_success(
        api.decide_permit(
            application["id"],
            f.decision_payload(c.DECISION_DENIED, decision_note="Zoning objection upheld"),
            users.OFFICER,
        ),
        expected_status=200,
    )

    assert denied["status"] == c.PERMIT_DENIED
    assert (
        fx.read_venue(api, parcel["id"])["site_posture"] == c.SITE_POSTURE_FROZEN
    )


def test_an_approval_takes_the_third_fork_and_leaves_the_parcel_open(api):
    """PRD §3.1: "A decision of `APPROVED` moves `SUBMITTED → APPROVED` but only when no *other* application on the same parcel already reads `APPROVED`; if one does, the approval is refused with `ERR_PERMIT_ALREADY_APPROVED`."

    Design: Corner/state_machines/one_submitted_permit_forks_three_ways_and_only_denial_freezes_its_parcel
    """
    parcel = fx.venue(api)
    application = fx.submitted_permit(api, parcel["id"])

    approved = validate_success(
        api.decide_permit(
            application["id"],
            f.decision_payload(c.DECISION_APPROVED, decision_note="Cleared as drawn"),
            users.OFFICER,
        ),
        expected_status=200,
    )

    assert approved["status"] == c.PERMIT_APPROVED
    assert approved["revision_rounds"] == 0
    assert fx.read_venue(api, parcel["id"])["site_posture"] == c.SITE_POSTURE_OPEN


# ─── approving_the_permit_reopens_readiness_on_every_course_of_the_parcel ──


def _fully_staffed_course_awaiting_a_decision(api):
    """A DRAFT course with every station marshaled, on a parcel whose only
    application is still `SUBMITTED`.

    Every staffing input to the posture is satisfied — no station is
    `UNSTAFFED`, no obstacle touches water, and with no heat scheduled the
    required medic count is ceil(0 / 250) = 0 — so the missing governing
    application is the only thing left holding the posture down.
    """
    parcel = fx.venue(api, water_access=c.WATER_ACCESS_NONE)
    application = fx.submitted_permit(
        api,
        parcel["id"],
        water_use_allowed=False,
        max_disturbed_area_sqm=_MAX_DISTURBED_AREA_SQM,
    )
    laid, stations = fx.three_station_course(
        api,
        parcel["id"],
        course_kwargs={
            "total_distance_m": 10000,
            "corral_release_rate_per_min": _CORRAL_RELEASE_RATE_PER_MIN,
        },
        station_kwargs=_STATION_KWARGS,
    )
    for station in stations:
        fx.marshal_shift(
            api,
            laid["id"],
            station["id"],
            staff_person_id=f"marshal-person-{station['station_index']}",
        )
    return parcel, application, laid, stations


def test_a_course_with_no_governing_application_reads_frozen(api):
    """PRD §3.3: "It reads `FROZEN` when the parcel's `site_posture` is anything other than `OPEN`, or when the parcel has no governing permit reading `APPROVED`."

    Design: Corner/state_machines/approving_the_permit_reopens_readiness_on_every_course_of_the_parcel
    """
    parcel, application, laid, stations = _fully_staffed_course_awaiting_a_decision(api)
    assert application["status"] == c.PERMIT_SUBMITTED
    assert fx.read_venue(api, parcel["id"])["site_posture"] == c.SITE_POSTURE_OPEN
    for station in stations:
        assert_obstacle_staffing(
            fx.read_obstacle(api, station["id"]),
            staffing_state=c.STAFFING_MARSHALED,
        )

    assert_course_capacities(
        fx.read_course(api, laid["id"]),
        readiness_posture=c.READINESS_FROZEN,
        status=c.COURSE_DRAFT,
    )


def test_the_approval_reopens_readiness_on_the_parcels_draft_course(api):
    """PRD §3.1: "A successful approval also recomputes `readiness_posture` on every course of that parcel, because the presence of a governing application is one of the inputs to that posture."

    Design: Corner/state_machines/approving_the_permit_reopens_readiness_on_every_course_of_the_parcel
    """
    _parcel, application, laid, _stations = _fully_staffed_course_awaiting_a_decision(api)
    assert_course_capacities(
        fx.read_course(api, laid["id"]), readiness_posture=c.READINESS_FROZEN
    )

    approved = validate_success(
        api.decide_permit(
            application["id"],
            f.decision_payload(c.DECISION_APPROVED),
            users.OFFICER,
        ),
        expected_status=200,
    )
    assert approved["status"] == c.PERMIT_APPROVED

    assert_course_capacities(
        fx.read_course(api, laid["id"]),
        readiness_posture=c.READINESS_OPEN,
        status=c.COURSE_DRAFT,
    )
