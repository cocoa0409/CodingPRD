"""Corner index — `Cross-Cutting Complexity Layers` and `Consistency Model`.

Every test in this module translates exactly one live instance of those two
sections of SCAFFOLD_CORNER_DESIGN.yaml, and names that instance on the final
`Design:` line of its docstring.
"""

from prd_bench_local_runner.testing import (
    validate_error,
    validate_paginated,
    validate_success,
)

from test_helpers import constants
from test_helpers import factories as f
from test_helpers import fixtures as fx
from test_helpers import test_users as users
from test_helpers.api_errors import ApiErrorId
from test_helpers.assertions import (
    assert_bond_ledger_conserved,
    assert_course_capacities,
    assert_entry_state,
    assert_obstacle_staffing,
    assert_timing,
    assert_version,
    ids_of,
)

# ─── The race-day world both concurrency instances stand on ─────────────
#
# Corral rate 12.00 with stations of 4×3.00 (NONE), 3×2.50 (MANDATORY) and
# 3×3.00 (TIMED_PENALTY, relief min(4.50, 8.00) capped by the corral) gives
# design rates of 12.00, 7.50 and 12.00. The course bottleneck is therefore
# floor(60 × 7.50) = 450 per hour, whose 15-minute ceiling of 112 leaves room
# for a heat of 50; one paramedic covers ceil(50 / 250).

_COURSE_KWARGS = {
    "name": "Quarry Gauntlet",
    "total_distance_m": 10000,
    "corral_release_rate_per_min": 12.00,
    "corral_throughput_capacity": 200,
}

_STATION_KWARGS = [
    {
        "name": "Cargo Net",
        "difficulty_rating": 3,
        "lane_count": 4,
        "service_rate_per_min": 3.00,
        "marshals_required": 1,
        "footprint_sqm": 1200,
        "bypass_mode": constants.BYPASS_MODE_NONE,
        "penalty_seconds": 0,
    },
    {
        "name": "Mud Trench",
        "difficulty_rating": 5,
        "lane_count": 3,
        "service_rate_per_min": 2.50,
        "marshals_required": 1,
        "footprint_sqm": 1500,
        "bypass_mode": constants.BYPASS_MODE_MANDATORY,
        "penalty_seconds": 120,
    },
    {
        "name": "Wall Climb",
        "difficulty_rating": 7,
        "lane_count": 3,
        "service_rate_per_min": 3.00,
        "marshals_required": 1,
        "footprint_sqm": 1000,
        "bypass_mode": constants.BYPASS_MODE_TIMED_PENALTY,
        "penalty_seconds": 90,
    },
]

#: 1200 + 1500 + 1000 square metres of station footprint.
_DISTURBED_SQM = 3700
_BOND_CENTS = 1000000
_SHARE_DECOMPACT_CENTS = 540541  # 1000000 × 2000 / 3700, half up
_SHARE_RESEED_CENTS = 459459  # 1000000 × 1700 / 3700, half up


def _entry_under_protest(api):
    """A finished, protested entry carrying a 120-second provisional penalty.

    Returns `(entry_id, disputed_attempt_id, version_before_protest)`, where the
    version was read after the finish and before the protest, so it is stale by
    exactly one write by the time it is handed back.
    """
    parcel, _permit = fx.permitted_venue(api)
    course, stations = fx.three_station_course(
        api,
        parcel["id"],
        course_kwargs=_COURSE_KWARGS,
        station_kwargs=_STATION_KWARGS,
    )
    for station in stations:
        fx.fully_marshal(api, course["id"], station)
    fx.medic_shift(api, course["id"])
    fx.published_course(api, course["id"])

    division = fx.division(api)
    heat = fx.wave(api, course["id"], division["id"], wave_code="S1", capacity=50)
    runner = fx.cleared_participant(api, full_name="Runner One")
    entry = fx.entry(api, heat["id"], runner["id"], 1)
    fx.check_in(api, entry["id"])
    fx.lock_roster(api, heat["id"])
    fx.release(api, heat["id"])
    fx.start(api, heat["id"])

    fx.attempt(api, entry["id"], stations[0]["id"], constants.OUTCOME_COMPLETED)
    disputed = fx.attempt(
        api, entry["id"], stations[1]["id"], constants.OUTCOME_FAILED_PENALTY
    )
    fx.attempt(api, entry["id"], stations[2]["id"], constants.OUTCOME_COMPLETED)
    finished = fx.finish(api, entry["id"])
    assert_entry_state(
        finished,
        progress_status=constants.PROGRESS_FINISHED,
        result_status=constants.RESULT_PROVISIONAL,
    )
    assert_timing(finished, provisional_penalty_seconds=120)

    version_before_protest = fx.read_entry(api, entry["id"])["version"]
    protested = fx.protest(api, entry["id"], runner["id"], disputed["id"])
    assert_entry_state(protested, result_status=constants.RESULT_UNDER_PROTEST)
    return entry["id"], disputed["id"], version_before_protest


def _two_verified_tasks(api):
    """A parcel whose two remediation tasks are both VERIFIED.

    The shares 540541 and 459459 have already been booked task by task, so the
    ledger reads fully released before any settlement is attempted. Returns
    `(parcel_id, version_before_second_inspection)`.
    """
    parcel, _permit = fx.permitted_venue(
        api, venue_kwargs={"restoration_bond_cents": _BOND_CENTS}
    )
    fx.three_station_course(
        api,
        parcel["id"],
        course_kwargs=_COURSE_KWARGS,
        station_kwargs=_STATION_KWARGS,
    )
    task_a = fx.restoration_task(
        api, parcel["id"], 2000, task_type=constants.TASK_TYPE_DECOMPACT
    )
    task_b = fx.restoration_task(
        api, parcel["id"], 1700, task_type=constants.TASK_TYPE_RESEED
    )
    verified_a = fx.inspect(
        api,
        task_a["id"],
        constants.INSPECTION_VERIFIED,
        findings_note="Subsoil ripped to 300mm",
    )
    assert verified_a["bond_release_cents"] == _SHARE_DECOMPACT_CENTS

    stale_version = fx.read_venue(api, parcel["id"])["version"]

    verified_b = fx.inspect(
        api,
        task_b["id"],
        constants.INSPECTION_VERIFIED,
        findings_note="Native mix established",
    )
    assert verified_b["bond_release_cents"] == _SHARE_RESEED_CENTS
    return parcel["id"], stale_version


# ─── cross-cutting / the entry version guard ────────────────────────────


def test_a_pre_protest_version_token_is_refused_and_changes_nothing(api):
    """PRD §2.8: "If `expected_entry_version` does not equal the entry's current `version` — because another writer advanced the entry since the client read it — the adjudication is rejected with `ERR_STALE_ENTRY_VERSION` (HTTP 412), which stops the client from ruling on a results card it has not seen."

    Design: Corner/Cross-Cutting Complexity Layers/a_stale_entry_version_is_refused_before_the_state_check
    """
    entry_id, _disputed_id, version_before_protest = _entry_under_protest(api)

    refused = api.create_adjudication(
        entry_id,
        f.adjudication_payload(
            constants.RULING_UPHELD_ADJUSTED,
            version_before_protest,
            note="Working from the pre-protest reading",
        ),
        users.DIRECTOR,
    )
    validate_error(
        refused, ApiErrorId.ERR_STALE_ENTRY_VERSION.value, expected_status=412
    )

    # The refusal is completely inert.
    after = fx.read_entry(api, entry_id)
    assert_entry_state(after, result_status=constants.RESULT_UNDER_PROTEST)
    assert after["protest_rounds"] == 0
    assert after["voided_attempt_ids"] == []
    assert_timing(after, provisional_penalty_seconds=120)
    # The protest itself counted as exactly one write, and the 412 as none.
    assert_version(after, version_before_protest + 1, "entry")


def test_the_fresh_token_rules_and_its_replay_is_stale_not_a_state_error(api):
    """PRD §2.6: "The supplied `expected_entry_version` or `expected_venue_version` equals the parent row's current `version` — otherwise `ERR_STALE_ENTRY_VERSION` or `ERR_STALE_VENUE_VERSION` (412)."

    Design: Corner/Cross-Cutting Complexity Layers/a_stale_entry_version_is_refused_before_the_state_check
    """
    entry_id, disputed_id, version_before_protest = _entry_under_protest(api)
    fresh_version = fx.read_entry(api, entry_id)["version"]
    assert fresh_version == version_before_protest + 1

    ruled = validate_success(
        api.create_adjudication(
            entry_id,
            f.adjudication_payload(
                constants.RULING_UPHELD_ADJUSTED,
                fresh_version,
                note="Rope failure confirmed",
            ),
            users.DIRECTOR,
        )
    )
    assert_entry_state(ruled, result_status=constants.RESULT_PROVISIONAL)
    assert ruled["protest_rounds"] == 1
    assert ruled["voided_attempt_ids"] == [disputed_id]
    # The official reading drops the voided penalty; the provisional keeps it.
    assert_timing(
        ruled, provisional_penalty_seconds=120, official_penalty_seconds=0
    )
    assert_version(ruled, fresh_version + 1, "entry")

    # Replaying the very token that just worked is stale, not a state error,
    # even though the entry has left UNDER_PROTEST.
    replay = api.create_adjudication(
        entry_id,
        f.adjudication_payload(
            constants.RULING_UPHELD_ADJUSTED,
            fresh_version,
            note="Replay of the same decision",
        ),
        users.DIRECTOR,
    )
    validate_error(
        replay, ApiErrorId.ERR_STALE_ENTRY_VERSION.value, expected_status=412
    )
    after = fx.read_entry(api, entry_id)
    assert after["protest_rounds"] == 1
    assert after["voided_attempt_ids"] == [disputed_id]
    assert_version(after, fresh_version + 1, "entry")


# ─── cross-cutting / the venue version guard on settlement ──────────────


def test_a_token_read_before_the_second_verification_is_refused(api):
    """PRD §2.8: "If `expected_venue_version` does not equal the venue's current `version` — because task verifications or clawbacks have moved the ledger since the client read it — the settlement is rejected with `ERR_STALE_VENUE_VERSION` (HTTP 412)."

    Design: Corner/Cross-Cutting Complexity Layers/a_stale_venue_version_is_refused_on_bond_settlement
    """
    parcel_id, stale_version = _two_verified_tasks(api)
    before = fx.read_venue(api, parcel_id)

    refused = api.create_bond_release(
        parcel_id,
        f.bond_release_payload(stale_version, constants.SETTLEMENT_PROGRESSIVE),
        users.OFFICER,
    )
    validate_error(
        refused, ApiErrorId.ERR_STALE_VENUE_VERSION.value, expected_status=412
    )

    # The refusal moves no money and does not advance the parcel.
    after = fx.read_venue(api, parcel_id)
    assert after["bond_released_cents"] == before["bond_released_cents"]
    assert after["bond_held_cents"] == before["bond_held_cents"]
    assert after["bond_forfeited_cents"] == before["bond_forfeited_cents"]
    assert after["site_posture"] == constants.SITE_POSTURE_OPEN
    assert_version(after, before["version"], "venue")
    assert_bond_ledger_conserved(after)


def test_an_accepted_settlement_token_cannot_be_replayed(api):
    """PRD §2.6: "The supplied `expected_entry_version` or `expected_venue_version` equals the parent row's current `version` — otherwise `ERR_STALE_ENTRY_VERSION` or `ERR_STALE_VENUE_VERSION` (412)."

    Design: Corner/Cross-Cutting Complexity Layers/a_stale_venue_version_is_refused_on_bond_settlement
    """
    parcel_id, _stale_version = _two_verified_tasks(api)
    fresh_version = fx.read_venue(api, parcel_id)["version"]

    settled = validate_success(
        api.create_bond_release(
            parcel_id,
            f.bond_release_payload(
                fresh_version, constants.SETTLEMENT_PROGRESSIVE
            ),
            users.OFFICER,
        )
    )
    # The two independently rounded shares sum to the posted bond exactly.
    assert settled["bond_released_cents"] == (
        _SHARE_DECOMPACT_CENTS + _SHARE_RESEED_CENTS
    )
    assert settled["bond_released_cents"] == _BOND_CENTS
    assert settled["bond_held_cents"] == 0
    assert settled["bond_forfeited_cents"] == 0
    assert settled["site_posture"] == constants.SITE_POSTURE_OPEN
    assert_bond_ledger_conserved(settled)

    replay = api.create_bond_release(
        parcel_id,
        f.bond_release_payload(fresh_version, constants.SETTLEMENT_PROGRESSIVE),
        users.OFFICER,
    )
    validate_error(
        replay, ApiErrorId.ERR_STALE_VENUE_VERSION.value, expected_status=412
    )

    # No share was booked twice by the replay.
    after = fx.read_venue(api, parcel_id)
    assert after["bond_released_cents"] == _BOND_CENTS
    assert after["bond_held_cents"] == 0
    assert_version(after, fresh_version + 1, "venue")
    assert_bond_ledger_conserved(after)


# ─── consistency model / immediate, two hops from the write ─────────────


def test_one_vacate_is_already_visible_two_hops_out_on_the_first_read(api):
    """PRD §3.3: "The same operation also recomputes the affected obstacle's `effective_clearance_rate_per_min` and the course's `bottleneck_capacity_pph`, and increments the `version` of every row it touched."

    Design: Corner/Consistency Model/every_cascade_effect_is_visible_on_the_first_read_after_the_write
    """
    parcel, _permit = fx.permitted_venue(api)
    doubled_station = dict(_STATION_KWARGS[0], marshals_required=2)
    course, stations = fx.three_station_course(
        api,
        parcel["id"],
        course_kwargs=_COURSE_KWARGS,
        station_kwargs=[doubled_station, _STATION_KWARGS[1], _STATION_KWARGS[2]],
    )
    first_station_shifts = fx.fully_marshal(api, course["id"], stations[0])
    for station in stations[1:]:
        fx.fully_marshal(api, course["id"], station)
    assert len(first_station_shifts) == 2

    # Fully staffed: 12.00 / 7.50 / 12.00, so the bottleneck is floor(60 × 7.50).
    assert_obstacle_staffing(
        fx.read_obstacle(api, stations[0]["id"]),
        staffing_state=constants.STAFFING_MARSHALED,
        confirmed_marshal_count=2,
        effective_rate=12.00,
        design_rate=12.00,
    )
    assert_course_capacities(
        fx.read_course(api, course["id"]),
        design_capacity_pph=450,
        bottleneck_capacity_pph=450,
        readiness_posture=constants.READINESS_OPEN,
    )

    vacated_shift = first_station_shifts[1]
    vacated = fx.vacate(
        api, vacated_shift["id"], reason="Reassigned to the festival gate"
    )
    # The write's own response already reports the shift released.
    assert vacated["status"] == constants.ASSIGNMENT_VACATED
    assert vacated["vacate_reason"] == "Reassigned to the festival gate"

    # First read, one hop out: 4 lanes × 3.00 × the 0.60 partial factor.
    assert_obstacle_staffing(
        fx.read_obstacle(api, stations[0]["id"]),
        staffing_state=constants.STAFFING_PARTIAL,
        confirmed_marshal_count=1,
        effective_rate=7.20,
        design_rate=12.00,
    )
    # First read, two hops out: floor(60 × 7.20), with the design rate untouched.
    assert_course_capacities(
        fx.read_course(api, course["id"]),
        design_capacity_pph=450,
        bottleneck_capacity_pph=432,
        readiness_posture=constants.READINESS_OPEN,
    )
    # First read of the filtered shift list already excludes the vacated row.
    rows, meta = validate_paginated(
        api.list_staff_assignments(
            users.SAFETY,
            params={
                "obstacle_id": stations[0]["id"],
                "status": constants.ASSIGNMENT_CONFIRMED,
            },
        )
    )
    assert meta["total_count"] == 1
    assert ids_of(rows) == [first_station_shifts[0]["id"]]
    assert vacated_shift["id"] not in ids_of(rows)
