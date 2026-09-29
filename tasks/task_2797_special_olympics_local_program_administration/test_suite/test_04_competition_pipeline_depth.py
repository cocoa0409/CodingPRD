"""Performance-ratio direction, the merge pass, and the divisioning gates."""

from test_helpers import (
    ApiErrorId,
    fixtures as fx,
    validate_error,
    validate_success,
)
from test_helpers import factories as f
from test_helpers.api_client import api_client
from test_helpers.fixtures import CD, PM

THREE_ATHLETES = [
    {"athlete": {"legal_name": "Maya Foster", "birth_date": "2004-03-09"}},
    {"athlete": {"legal_name": "Ivan Petrov", "birth_date": "2003-10-01"}},
    {"athlete": {"legal_name": "Grace Lin", "birth_date": "1998-05-20"}},
]


def _resulted_season_world(sport: str, season_name: str, event_code: str):
    """One locked season of three entries, ready for results on games day."""
    world = fx.setup_entry_ready_world(
        athlete_specs=THREE_ATHLETES,
        season_overrides={"sport": sport, "season_name": season_name})
    entries = fx.submit_entries(world["season"]["id"], [
        {"participant_id": world["athletes"][0]["id"], "event_code": event_code,
         "skill_score": 40.0},
        {"participant_id": world["athletes"][1]["id"], "event_code": event_code,
         "skill_score": 39.0},
        {"participant_id": world["athletes"][2]["id"], "event_code": event_code,
         "skill_score": 38.0},
    ])
    fx.set_clock("2026-09-02T00:00:00Z")
    validate_success(api_client.run_divisioning(world["season"]["id"], {}, CD))
    validate_success(api_client.lock_season_entries(world["season"]["id"], {}, CD))
    fx.set_clock("2026-09-20T09:00:00Z")
    world["entries"] = entries
    return world


def test_01_a_time_scored_season_divides_skill_by_result():
    """ATHLETICS is time-scored, so 40.0 against 44.0 gives 0.9091.

    PRD §3.7: "For `ATHLETICS` and `SWIMMING` the sport is time-scored and lower
    is better, so the ratio is the entry's `skill_score` divided by its
    `result_value`… a `skill_score` of 40 against a `result_value` of 44 yields
    `0.9091` in a time-scored season".

    Design: Difficulty/dual_variant_calc/entry_performance_ratio_direction_variants
    """
    world = _resulted_season_world("ATHLETICS", "Fall 2026 Athletics", "100M_DASH")
    entry = validate_success(api_client.post_entry_result(
        world["entries"][0]["id"], f.post_result_payload(44.0), CD))
    assert entry["skill_score"] == 40.0
    assert entry["result_value"] == 44.0
    assert entry["performance_ratio"] == 0.9091
    assert entry["advancement_status"] == "ADVANCED_STATE"
    assert entry["status"] == "ADVANCED"


def test_02_a_point_scored_season_divides_result_by_skill():
    """BOCCE is point-scored, so the identical inputs give 1.1000 instead.

    PRD §3.7: "For `BOCCE` and `BASKETBALL` the sport is point-scored and higher
    is better, so the ratio is the entry's `result_value` divided by its
    `skill_score`… and `1.1000` in a point-scored one — two different numbers
    from identical inputs".

    Design: Difficulty/dual_variant_calc/entry_performance_ratio_direction_variants
    """
    world = _resulted_season_world("BOCCE", "Fall 2026 Bocce", "BOCCE_SINGLES")
    entry = validate_success(api_client.post_entry_result(
        world["entries"][0]["id"], f.post_result_payload(44.0), CD))
    assert entry["skill_score"] == 40.0
    assert entry["result_value"] == 44.0
    assert entry["performance_ratio"] == 1.1
    assert entry["advancement_status"] == "ADVANCED_STATE"
    assert entry["status"] == "ADVANCED"


def _five_entry_merge_world():
    """Three undersized bands, one of which becomes another's merge target."""
    athlete_specs = [
        {"athlete": {"legal_name": "Kai Obi", "birth_date": "2012-05-10"}},
        {"athlete": {"legal_name": "Sara Nolan", "birth_date": "2011-08-02"}},
        {"athlete": {"legal_name": "Tomas Reyes", "birth_date": "2008-04-15"}},
        {"athlete": {"legal_name": "Elena Duarte", "birth_date": "2007-11-30"}},
        {"athlete": {"legal_name": "Marcus Webb", "birth_date": "1994-02-20"}},
    ]
    entry_specs = [
        {"athlete_index": 0, "skill_score": 20.0},
        {"athlete_index": 1, "skill_score": 19.8},
        {"athlete_index": 2, "skill_score": 20.4},
        {"athlete_index": 3, "skill_score": 20.1},
        {"athlete_index": 4, "skill_score": 8.0},
    ]
    return fx.setup_divisioned_season(athlete_specs, entry_specs,
                                      divisioning_clock="2026-09-02T00:00:00Z")


def _divisions_by_age_group(world):
    return {division["age_group"]: division for division in world["divisions"]}


def test_03_the_merge_pass_folds_the_younger_band_into_its_neighbour():
    """AGE_12_15 is processed first and finds AGE_16_21 within one position.

    PRD §3.6: the source list "is processed in ascending order of age band"; a
    merge "moves every live entry of the source over to the target … and then
    moves the source `UNDERSIZED → VOIDED` with its `merged_into_division_id`
    set to the target's id", while the target "increments `merged_source_count`
    by one, recomputes its `entry_count`, `ability_band_high`,
    `ability_band_low` and `ability_spread_ratio` from its live entries, and
    re-derives its own status".

    Design: Difficulty/combinatorial_formula/undersized_division_merge_order
    """
    world = _five_entry_merge_world()
    assert world["season"]["status"] == "DIVISIONED"
    assert world["season"]["divisioning_run_count"] == 1
    assert world["season"]["entry_count"] == 5
    assert world["season"]["divisioned_entry_count"] == 5
    assert len(world["divisions"]) == 3

    by_band = _divisions_by_age_group(world)
    target = by_band["AGE_16_21"]
    assert target["status"] == "VALID"
    assert target["entry_count"] == 4
    assert target["ability_band_high"] == 20.4
    assert target["ability_band_low"] == 19.8
    assert target["ability_spread_ratio"] == 1.0303
    assert target["merged_source_count"] == 1

    source = by_band["AGE_12_15"]
    assert source["status"] == "VOIDED"
    assert source["entry_count"] == 0
    assert source["merged_into_division_id"] == target["id"]

    entries = {entry["id"]: entry for entry in world["entries"]}
    moved = [entry for entry in entries.values() if entry["skill_score"] == 20.0][0]
    anchor = [entry for entry in entries.values() if entry["skill_score"] == 20.4][0]
    assert moved["division_id"] == anchor["division_id"] == target["id"]


def test_04_a_division_that_received_a_merge_is_never_used_as_a_source():
    """AGE_16_21 was UNDERSIZED in the snapshot yet is never folded away, and
    AGE_30_PLUS finds no adjacent target.

    PRD §3.6: "A division that has already received a merge in this run is
    skipped as a source, so no division is both a target and a source"; and "If
    no target qualifies, the source simply keeps its `UNDERSIZED` status and the
    run continues without error". Seeding then runs "across every live division: each
    entry's `seed_rank` is its rank within its division by `skill_score`
    descending".

    Design: Difficulty/combinatorial_formula/undersized_division_merge_order
    """
    world = _five_entry_merge_world()
    by_band = _divisions_by_age_group(world)
    lonely = by_band["AGE_30_PLUS"]
    assert lonely["status"] == "UNDERSIZED"
    assert lonely["entry_count"] == 1
    assert lonely["merged_source_count"] == 0
    assert lonely["merged_into_division_id"] is None
    assert by_band["AGE_16_21"]["merged_into_division_id"] is None

    seeds = {entry["skill_score"]: entry["seed_rank"] for entry in world["entries"]}
    assert seeds[20.4] == 1
    assert seeds[20.1] == 2
    assert seeds[20.0] == 3
    assert seeds[19.8] == 4
    assert seeds[8.0] == 1


def test_05_an_unmergeable_undersized_division_blocks_locking():
    """The deferred consequence of the merge pass surfaces at lock time.

    PRD §3.6: locking "requires that no division of the season is still
    `UNDERSIZED` — one that is yields `ERR_UNDERSIZED_DIVISION_PRESENT` (409),
    which is precisely how an unmergeable undersized division finally makes
    itself felt".

    Design: Difficulty/combinatorial_formula/undersized_division_merge_order
    """
    world = _five_entry_merge_world()
    validate_error(api_client.lock_season_entries(world["season"]["id"], {}, CD),
                   ApiErrorId.ERR_UNDERSIZED_DIVISION_PRESENT.value, 409)
    season = validate_success(api_client.get_season(world["season"]["id"], CD))
    assert season["status"] == "DIVISIONED"


def _restricted_and_undersized_world():
    """A RESTRICTED posture and a surviving UNDERSIZED division on one season."""
    world = fx.setup_divisioned_season(
        THREE_ATHLETES,
        [{"athlete_index": 0, "skill_score": 40.0},
         {"athlete_index": 1, "skill_score": 39.0},
         {"athlete_index": 2, "skill_score": 38.0}],
        divisioning_clock="2026-09-02T00:00:00Z")
    fx.record_screening_finding(
        world["athletes"][0]["id"], discipline="FUNFITNESS",
        screened_on="2026-09-02", finding_severity="URGENT",
        finding_note="Uncontrolled hypertension, immediate referral")
    return world


def test_06_the_posture_gate_is_reported_before_the_undersized_division():
    """Band 7 posture beats the band 11 composition constraint on one call.

    PRD §2.6: band 7 is "**Program compliance posture** —
    `ERR_PROGRAM_POSTURE_RESTRICTED` and `ERR_PROGRAM_POSTURE_FROZEN`, both HTTP
    409" while band 11 is "**Business constraint** — composition, ability spread,
    uniqueness"; PRD §2.7: "locking a season's entries" is among the operations
    "refused with `ERR_PROGRAM_POSTURE_RESTRICTED` (HTTP 409) while a program is
    `RESTRICTED`".

    Design: Difficulty/priority_pair_validation_conflict/posture_gate_precedes_undersized_division_check
    """
    world = _restricted_and_undersized_world()
    assert fx.get_program(world["program"]["id"])["compliance_posture"] == "RESTRICTED"
    division = validate_success(
        api_client.get_division(world["entries"][1]["division_id"], CD))
    assert division["status"] == "UNDERSIZED"
    assert division["entry_count"] == 2

    error = validate_error(
        api_client.lock_season_entries(world["season"]["id"], {}, CD),
        ApiErrorId.ERR_PROGRAM_POSTURE_RESTRICTED.value, 409)
    assert error["error_id"] != ApiErrorId.ERR_UNDERSIZED_DIVISION_PRESENT.value


def test_07_the_refused_lock_leaves_the_season_and_its_entries_alone():
    """No partial lock: the season and both live entries stay DIVISIONED.

    PRD §3.6: "The lock moves the season `DIVISIONED → ENTRIES_LOCKED`, moves
    every entry in `DIVISIONED` whose division is `VALID` to `LOCKED`, and
    increments the season's `version` by one."

    Design: Difficulty/priority_pair_validation_conflict/posture_gate_precedes_undersized_division_check
    """
    world = _restricted_and_undersized_world()
    before = validate_success(api_client.get_season(world["season"]["id"], CD))
    validate_error(api_client.lock_season_entries(world["season"]["id"], {}, CD),
                   ApiErrorId.ERR_PROGRAM_POSTURE_RESTRICTED.value, 409)

    after = validate_success(api_client.get_season(world["season"]["id"], CD))
    assert after["status"] == "DIVISIONED"
    assert after["version"] == before["version"]
    for entry in world["entries"][1:]:
        live = validate_success(api_client.get_competition_entry(entry["id"], CD))
        assert live["status"] == "DIVISIONED"
    division = validate_success(
        api_client.get_division(world["entries"][1]["division_id"], CD))
    assert division["status"] == "UNDERSIZED"
    assert division["entry_count"] == 2


def _empty_candidate_season():
    """An OPEN program whose PRACTICE_OPEN season holds no entries at all."""
    world = fx.setup_program_with_certified_coach()
    season = fx.create_practice_open_season(
        world["program"]["id"], sport="BOCCE", season_name="Fall 2026 Bocce",
        practice_minimum_sessions=0, practice_minimum_minutes=0)
    fx.set_clock("2026-09-02T00:00:00Z")
    world["season"] = season
    return world


def test_08_divisioning_an_empty_candidate_set_fails_closed():
    """Zero SUBMITTED entries is an error, not a run that yields no divisions.

    PRD §3.6: "at least one entry of the season must be sitting in `SUBMITTED`,
    or the run is refused with `ERR_NO_ELIGIBLE_ENTRIES` (422) rather than
    producing zero divisions."

    Design: Difficulty/boundary_precision_check/divisioning_with_empty_candidate_set_returns_no_eligible_entries
    """
    world = _empty_candidate_season()
    assert fx.get_program(world["program"]["id"])["compliance_posture"] == "OPEN"
    validate_error(api_client.run_divisioning(world["season"]["id"], {}, CD),
                   ApiErrorId.ERR_NO_ELIGIBLE_ENTRIES.value, 422)

    season = validate_success(api_client.get_season(world["season"]["id"], CD))
    assert season["status"] == "PRACTICE_OPEN"


def test_09_the_failed_divisioning_run_moves_no_counter():
    """Every divisioning counter stays at zero and no division row exists.

    PRD §3.6: on a successful run "the season's `divisioning_run_count` increments
    by one; `entry_count` and `divisioned_entry_count` … are recomputed".

    Design: Difficulty/boundary_precision_check/divisioning_with_empty_candidate_set_returns_no_eligible_entries
    """
    world = _empty_candidate_season()
    validate_error(api_client.run_divisioning(world["season"]["id"], {}, CD),
                   ApiErrorId.ERR_NO_ELIGIBLE_ENTRIES.value, 422)

    season = validate_success(api_client.get_season(world["season"]["id"], CD))
    assert season["divisioning_run_count"] == 0
    assert season["divisioned_entry_count"] == 0
    assert season["entry_count"] == 0

    listing = api_client.list_divisions(
        CD, params={"season_id": world["season"]["id"]})
    assert listing.status_code == 200
    assert listing.json()["meta"]["total_count"] == 0
