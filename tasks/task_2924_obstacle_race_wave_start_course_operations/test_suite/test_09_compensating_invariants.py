"""Two conserved quantities and the compensations that must preserve them.

The bond ledger conserves money: a failed re-inspection is a true reversal that
subtracts exactly the cents that task had released, and the pass that follows
re-releases exactly the same amount, so a full round trip is bit-identical while
`inspection_rounds` keeps climbing. A course roster conserves a headcount: a
reassignment must drop one head from the source at the same instant it adds one
to the target, and every refusal must leave both counters untouched.
"""

from prd_bench_local_runner.testing import validate_error, validate_success

from test_helpers import factories as f
from test_helpers import fixtures as fx
from test_helpers import test_users as users
from test_helpers.api_errors import ApiErrorId
from test_helpers.assertions import (
    assert_bond_ledger_conserved,
    assert_course_capacities,
    assert_entry_state,
    assert_whole_cents,
)
from test_helpers.constants import (
    BYPASS_MODE_MANDATORY,
    BYPASS_MODE_NONE,
    BYPASS_MODE_TIMED_PENALTY,
    BYPASS_POLICY_ALLOWED_WITH_PENALTY,
    BYPASS_POLICY_DQ_ON_BYPASS,
    DIVISION_COMPETITIVE,
    DIVISION_OPEN,
    INSPECTION_REMEDIATION_REQUIRED,
    INSPECTION_VERIFIED,
    PROGRESS_REGISTERED,
    SCORING_CHIP_TIME,
    SCORING_GUN_TIME,
    SERVICE_BAG_CHECK,
    SETTLEMENT_FINAL,
    SITE_POSTURE_OPEN,
    TASK_REMEDIATION_REQUIRED,
    TASK_TYPE_DECOMPACT,
    TASK_TYPE_RESEED,
    TASK_TYPE_SILT_REMOVAL,
    TASK_VERIFIED,
)

# ─── The conserved bond ledger ───────────────────────────────────────────

#: The posted bond, and the ground disturbance it is split across.
_BOND_CENTS = 1000000
_DISTURBED_SQM = 4500

#: 1200 + 1500 + 1000 of obstacle footprint, plus an 800 sqm bag-check tent.
_FESTIVAL_FOOTPRINT_SQM = 800

#: Each of the three equal tasks remediates a third of the disturbed ground.
_TASK_AREA_SQM = 1500

#: round_half_up(1000000 * 1500 / 4500) — computed and rounded per task.
_TASK_SHARE_CENTS = 333333

#: Three independently rounded shares sum to one cent short of the bond, and
#: that missing cent stays held until the final settlement reconciles it.
_RELEASED_ALL_VERIFIED = 999999
_HELD_ALL_VERIFIED = 1

#: With one task clawed back, exactly one share moves from released to held.
_RELEASED_AFTER_CLAWBACK = 666666
_HELD_AFTER_CLAWBACK = 333334

_COURSE_KWARGS = {
    "name": "Quarry Gauntlet",
    "total_distance_m": 10000,
    "corral_release_rate_per_min": 12.00,
    "corral_throughput_capacity": 200,
}

#: The three canonical stations, whose footprints supply 3700 of the 4500.
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
        "penalty_seconds": 0,
    },
    {
        "name": "Pond Crossing",
        "difficulty_rating": 5,
        "lane_count": 3,
        "service_rate_per_min": 2.50,
        "marshals_required": 2,
        "footprint_sqm": 1500,
        "water_contact": True,
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

_TASK_TYPES = (TASK_TYPE_RESEED, TASK_TYPE_DECOMPACT, TASK_TYPE_SILT_REMOVAL)
_FINDINGS = ("Seed established", "Compaction relieved", "Silt cleared")


def _three_verified_tasks(api):
    """A permitted parcel disturbed to exactly 4500 sqm, carrying three equal
    remediation tasks T1, T2 and T3 that have all passed their first inspection.

    Returns (parcel, [T1, T2, T3]) with the parcel re-read after the third pass,
    so its ledger already reads released 999999 / held 1.
    """
    parcel, _permit = fx.permitted_venue(
        api,
        venue_kwargs={
            "protected_acreage_sqm": 2000,
            "restoration_bond_cents": _BOND_CENTS,
        },
        max_disturbed_area_sqm=5000,
    )
    fx.three_station_course(
        api, parcel["id"], course_kwargs=_COURSE_KWARGS, station_kwargs=_STATIONS
    )
    fx.festival_service(
        api,
        parcel["id"],
        service_type=SERVICE_BAG_CHECK,
        footprint_sqm=_FESTIVAL_FOOTPRINT_SQM,
        capacity=500,
        water_draw_lpm=0,
    )
    tasks = [
        fx.restoration_task(api, parcel["id"], _TASK_AREA_SQM, task_type=task_type)
        for task_type in _TASK_TYPES
    ]
    passed = [
        fx.inspect(api, task["id"], INSPECTION_VERIFIED, findings_note=note)
        for task, note in zip(tasks, _FINDINGS)
    ]
    return fx.read_venue(api, parcel["id"]), passed


def _assert_ledger(api, venue_id: str, released: int, held: int) -> dict:
    """Read the parcel and pin all three cent columns plus the sum invariant."""
    parcel = fx.read_venue(api, venue_id)
    assert parcel["restoration_bond_cents"] == _BOND_CENTS
    assert parcel["bond_released_cents"] == released, (
        f"bond_released_cents: expected {released}, "
        f"got {parcel['bond_released_cents']}"
    )
    assert parcel["bond_held_cents"] == held, (
        f"bond_held_cents: expected {held}, got {parcel['bond_held_cents']}"
    )
    assert parcel["bond_forfeited_cents"] == 0
    assert_bond_ledger_conserved(parcel)
    return parcel


def test_a_failed_reinspection_reverses_exactly_the_cents_it_had_released(api):
    """PRD §3.9: "A fail on a task that had passed moves it `VERIFIED → REMEDIATION_REQUIRED` and reverses the ledger exactly: the task's current `bond_release_cents` is subtracted from the parcel's `bond_released_cents` and added back to `bond_held_cents`, after which the task's `bond_release_cents` resets to 0; both `version` values increment."

    Design: Difficulty/compensating_invariant/failed_reinspection_claws_the_bond_share_back_and_the_three_cent_fields_still_sum
    """
    parcel, tasks = _three_verified_tasks(api)
    reseed, decompact, silt = tasks

    assert parcel["disturbed_area_sqm"] == _DISTURBED_SQM
    for task in tasks:
        assert task["status"] == TASK_VERIFIED
        assert task["inspection_rounds"] == 1
        assert_whole_cents(task["bond_release_cents"], "bond_release_cents")
        assert task["bond_release_cents"] == _TASK_SHARE_CENTS
    _assert_ledger(api, parcel["id"], _RELEASED_ALL_VERIFIED, _HELD_ALL_VERIFIED)

    clawed = fx.inspect(
        api,
        silt["id"],
        INSPECTION_REMEDIATION_REQUIRED,
        findings_note="Silt curtain failed after rain",
    )
    assert clawed["status"] == TASK_REMEDIATION_REQUIRED
    assert clawed["bond_release_cents"] == 0
    assert clawed["inspection_rounds"] == 2
    assert clawed["version"] == silt["version"] + 1

    after = _assert_ledger(
        api, parcel["id"], _RELEASED_AFTER_CLAWBACK, _HELD_AFTER_CLAWBACK
    )
    assert after["version"] == parcel["version"] + 1

    # The compensation is confined to the failing task: its two siblings keep
    # the shares they were attributed.
    for sibling in (reseed, decompact):
        assert (
            fx.read_task(api, sibling["id"])["bond_release_cents"] == _TASK_SHARE_CENTS
        )
        assert fx.read_task(api, sibling["id"])["status"] == TASK_VERIFIED


def test_a_final_settlement_mid_cycle_is_refused_and_moves_no_cents(api):
    """PRD §3.9: "It first demands that every remediation task on the parcel reads `VERIFIED` and that at least one such task exists; a parcel with an unverified task, or with no task at all, is refused with `ERR_RESTORATION_INCOMPLETE`."

    Design: Difficulty/compensating_invariant/failed_reinspection_claws_the_bond_share_back_and_the_three_cent_fields_still_sum
    """
    parcel, tasks = _three_verified_tasks(api)
    fx.inspect(
        api,
        tasks[2]["id"],
        INSPECTION_REMEDIATION_REQUIRED,
        findings_note="Silt curtain failed after rain",
    )
    mid_cycle = _assert_ledger(
        api, parcel["id"], _RELEASED_AFTER_CLAWBACK, _HELD_AFTER_CLAWBACK
    )
    assert mid_cycle["site_posture"] == SITE_POSTURE_OPEN

    refused = api.create_bond_release(
        parcel["id"],
        f.bond_release_payload(mid_cycle["version"], SETTLEMENT_FINAL),
        users.OFFICER,
    )
    validate_error(
        refused, ApiErrorId.ERR_RESTORATION_INCOMPLETE.value, expected_status=409
    )

    # The refusal is total: not one cent moved, the parcel stayed open, and its
    # version did not advance.
    unmoved = _assert_ledger(
        api, parcel["id"], _RELEASED_AFTER_CLAWBACK, _HELD_AFTER_CLAWBACK
    )
    assert unmoved["site_posture"] == SITE_POSTURE_OPEN
    assert unmoved["version"] == mid_cycle["version"]
    assert fx.read_task(api, tasks[2]["id"])["bond_release_cents"] == 0


def test_the_remediation_round_trip_leaves_the_ledger_bit_identical(api):
    """PRD §3.9: "A re-inspection that passes moves it `REMEDIATION_REQUIRED → VERIFIED` and applies precisely the same share computation and ledger sync as the first pass."

    Design: Difficulty/compensating_invariant/failed_reinspection_claws_the_bond_share_back_and_the_three_cent_fields_still_sum
    """
    parcel, tasks = _three_verified_tasks(api)
    silt = tasks[2]

    fx.inspect(
        api,
        silt["id"],
        INSPECTION_REMEDIATION_REQUIRED,
        findings_note="Silt curtain failed after rain",
    )
    _assert_ledger(api, parcel["id"], _RELEASED_AFTER_CLAWBACK, _HELD_AFTER_CLAWBACK)

    repassed = fx.inspect(
        api,
        silt["id"],
        INSPECTION_VERIFIED,
        findings_note="Curtain rebuilt and holding",
    )
    assert repassed["status"] == TASK_VERIFIED
    assert repassed["bond_release_cents"] == _TASK_SHARE_CENTS
    # Only the visit counter records that the cycle ever happened.
    assert repassed["inspection_rounds"] == 3

    _assert_ledger(api, parcel["id"], _RELEASED_ALL_VERIFIED, _HELD_ALL_VERIFIED)
    for task in tasks:
        reread = fx.read_task(api, task["id"])
        assert reread["status"] == TASK_VERIFIED
        assert reread["bond_release_cents"] == _TASK_SHARE_CENTS


# ─── The conserved course roster ─────────────────────────────────────────

_W1_START = "2026-09-12T08:00:00.000Z"
_W2_START = "2026-09-12T08:02:00.000Z"
_W3_START = "2026-09-12T08:04:00.000Z"

#: W1 5 + W2 2 + W3 5 — the sum of *declared* capacities, which no roster move
#: can ever touch.
_SCHEDULED_CAPACITY_TOTAL = 12

_RUNNERS = (
    ("Ada Rock", "ada@example.com", "CHIP-001"),
    ("Bo Stone", "bo@example.com", "CHIP-002"),
    ("Cy Fern", "cy@example.com", "CHIP-003"),
    ("Di Marsh", "di@example.com", "CHIP-004"),
)


def _reassignment_world(api) -> dict:
    """One course carrying three heats and four registered runners.

    W1 (capacity 5, OPEN division) holds three entries; W2 (capacity 2, the same
    OPEN division) holds one; W3 (capacity 5) carries the COMPETITIVE division
    and is empty. Every roster is still OPEN and every runner is CLEARED and old
    enough for either division, so only the two gates under test can bite.
    """
    parcel = fx.venue(api, protected_acreage_sqm=2000, restoration_bond_cents=500000)
    course, _stations = fx.three_station_course(
        api, parcel["id"], course_kwargs=_COURSE_KWARGS, station_kwargs=_STATIONS
    )
    open_division = fx.division(
        api,
        name="Open Wave",
        division_type=DIVISION_OPEN,
        bypass_policy=BYPASS_POLICY_ALLOWED_WITH_PENALTY,
        scoring_mode=SCORING_GUN_TIME,
        min_age=16,
    )
    elite_division = fx.division(
        api,
        name="Elite",
        division_type=DIVISION_COMPETITIVE,
        bypass_policy=BYPASS_POLICY_DQ_ON_BYPASS,
        scoring_mode=SCORING_CHIP_TIME,
        min_age=18,
    )
    w1 = fx.wave(
        api,
        course["id"],
        open_division["id"],
        wave_code="W1",
        scheduled_start_utc=_W1_START,
        capacity=5,
    )
    w2 = fx.wave(
        api,
        course["id"],
        open_division["id"],
        wave_code="W2",
        scheduled_start_utc=_W2_START,
        capacity=2,
    )
    w3 = fx.wave(
        api,
        course["id"],
        elite_division["id"],
        wave_code="W3",
        scheduled_start_utc=_W3_START,
        capacity=5,
    )
    humans = [
        fx.cleared_participant(
            api, full_name=name, birth_year=2000, email=email, chip_id=chip
        )
        for name, email, chip in _RUNNERS
    ]
    entries = [
        fx.entry(api, w1["id"], humans[index]["id"], bib_number=index + 1)
        for index in range(3)
    ]
    entries.append(fx.entry(api, w2["id"], humans[3]["id"], bib_number=4))
    return {
        "course": course,
        "w1": w1,
        "w2": w2,
        "w3": w3,
        "entries": entries,
    }


def _assigned_counts(api, world: dict):
    return tuple(
        fx.read_wave(api, world[code]["id"])["assigned_count"]
        for code in ("w1", "w2", "w3")
    )


def test_a_reassignment_moves_one_head_and_conserves_the_course_total(api):
    """PRD §3.5: "On success the entry's `wave_id` becomes the `target_wave_id` and `assigned_count` is recomputed on both heats, so the total roster across the course is conserved."

    Design: Difficulty/compensating_invariant/reassigning_an_entry_conserves_the_total_roster_count_across_both_heats
    """
    world = _reassignment_world(api)
    first, second = world["entries"][0], world["entries"][1]
    assert _assigned_counts(api, world) == (3, 1, 0)

    moved = validate_success(
        api.reassign_entry(
            first["id"], f.reassign_payload(world["w2"]["id"]), users.DIRECTOR
        )
    )
    assert moved["wave_id"] == world["w2"]["id"]
    assert_entry_state(moved, progress_status=PROGRESS_REGISTERED)
    # The source fell by exactly one at the moment the target rose by one.
    counts = _assigned_counts(api, world)
    assert counts == (2, 2, 0)
    assert sum(counts) == 4

    # W2 is now full, and W3 carries a different division: both refusals leave
    # the two counters exactly where the successful move left them.
    validate_error(
        api.reassign_entry(
            second["id"], f.reassign_payload(world["w2"]["id"]), users.DIRECTOR
        ),
        ApiErrorId.ERR_WAVE_CAPACITY_EXCEEDED.value,
        expected_status=409,
    )
    validate_error(
        api.reassign_entry(
            second["id"], f.reassign_payload(world["w3"]["id"]), users.DIRECTOR
        ),
        ApiErrorId.ERR_WAVE_COURSE_MISMATCH.value,
        expected_status=409,
    )
    assert fx.read_entry(api, second["id"])["wave_id"] == world["w1"]["id"]
    assert _assigned_counts(api, world) == (2, 2, 0)


def test_a_target_at_capacity_refuses_the_move_and_touches_no_counter(api):
    """PRD §3.5: "The target heat must have room by the same rule as registration — its `assigned_count` plus one at most its `capacity` — or the move is refused with `ERR_WAVE_CAPACITY_EXCEEDED`."

    Design: Difficulty/compensating_invariant/reassigning_an_entry_conserves_the_total_roster_count_across_both_heats
    """
    world = _reassignment_world(api)
    candidate = world["entries"][0]

    # Fill W2 to its declared capacity of 2 by registration rather than by a
    # move, so the counter — not the path that raised it — is what refuses.
    fx.registered_entry(api, world["w2"]["id"], bib_number=5)
    assert _assigned_counts(api, world) == (3, 2, 0)

    refused = api.reassign_entry(
        candidate["id"], f.reassign_payload(world["w2"]["id"]), users.DIRECTOR
    )
    validate_error(
        refused, ApiErrorId.ERR_WAVE_CAPACITY_EXCEEDED.value, expected_status=409
    )

    # No half-applied move: the entry never left, and no orphan row appeared.
    unmoved = fx.read_entry(api, candidate["id"])
    assert unmoved["wave_id"] == world["w1"]["id"]
    assert_entry_state(unmoved, progress_status=PROGRESS_REGISTERED)
    assert _assigned_counts(api, world) == (3, 2, 0)


def test_a_target_carrying_another_division_refuses_the_move(api):
    """PRD §3.5: "The target heat must belong to the same course *and* carry the same division as the entry's current heat, or the move is refused with `ERR_WAVE_COURSE_MISMATCH`."

    Design: Difficulty/compensating_invariant/reassigning_an_entry_conserves_the_total_roster_count_across_both_heats
    """
    world = _reassignment_world(api)
    candidate = world["entries"][0]

    # W3 sits on the very same course and has four seats free, and the runner is
    # old enough for the COMPETITIVE division — only the division differs.
    assert world["w3"]["course_id"] == world["course"]["id"]
    assert world["w3"]["capacity"] == 5
    refused = api.reassign_entry(
        candidate["id"], f.reassign_payload(world["w3"]["id"]), users.DIRECTOR
    )
    validate_error(
        refused, ApiErrorId.ERR_WAVE_COURSE_MISMATCH.value, expected_status=409
    )

    assert fx.read_entry(api, candidate["id"])["wave_id"] == world["w1"]["id"]
    assert _assigned_counts(api, world) == (3, 1, 0)


def test_the_declared_capacity_total_is_untouched_by_every_roster_move(api):
    """PRD §3.4: "Creating a heat recomputes the course's `scheduled_capacity_total` — the sum of `capacity` over the heats of that course whose `release_status` is `SCHEDULED`, `HELD`, `RELEASED` or `STARTED` — and therefore also recomputes the course's `readiness_posture`, because the medic requirement scales with that total."

    Design: Difficulty/compensating_invariant/reassigning_an_entry_conserves_the_total_roster_count_across_both_heats
    """
    world = _reassignment_world(api)
    course_id = world["course"]["id"]
    first, second = world["entries"][0], world["entries"][1]

    def declared_total():
        course = fx.read_course(api, course_id)
        assert_course_capacities(
            course, scheduled_capacity_total=_SCHEDULED_CAPACITY_TOTAL
        )
        return course["scheduled_capacity_total"]

    assert declared_total() == _SCHEDULED_CAPACITY_TOTAL

    validate_success(
        api.reassign_entry(
            first["id"], f.reassign_payload(world["w2"]["id"]), users.DIRECTOR
        )
    )
    assert declared_total() == _SCHEDULED_CAPACITY_TOTAL

    validate_error(
        api.reassign_entry(
            second["id"], f.reassign_payload(world["w2"]["id"]), users.DIRECTOR
        ),
        ApiErrorId.ERR_WAVE_CAPACITY_EXCEEDED.value,
        expected_status=409,
    )
    assert declared_total() == _SCHEDULED_CAPACITY_TOTAL

    validate_error(
        api.reassign_entry(
            second["id"], f.reassign_payload(world["w3"]["id"]), users.DIRECTOR
        ),
        ApiErrorId.ERR_WAVE_COURSE_MISMATCH.value,
        expected_status=409,
    )
    assert declared_total() == _SCHEDULED_CAPACITY_TOTAL
    assert _assigned_counts(api, world) == (2, 2, 0)
