"""Throwing programs: phase-allowance bands and the cyclic phase machine."""
from test_helpers import (
    TEST_USERS,
    advance_phase,
    api_client,
    create_complex,
    get_throw_program,
    log_bullpen,
    log_catch_play,
    set_test_clock,
    setup_pitcher_program,
    validate_success,
)


def _pitcher_at_phase_three(complex_id, target_throws=200):
    """Program at PHASE_3 with `target_throws` accumulated catch-play throws and
    its bullpen target satisfied, so the phase-allowance band is observable."""
    _player, _roster, _profile, _group, _assignment, program = setup_pitcher_program(
        complex_id, target_catch_play_throws=target_throws, target_bullpen_sessions=2)
    log_catch_play(program["id"], target_throws)
    # a second logged catch-play session accumulating the workload to the band
    # the design index asserts (200 throws then 50 more)
    log_catch_play(program["id"], 50)
    log_bullpen(program["id"])
    log_bullpen(program["id"])
    validate_success(advance_phase(program["id"], "ADVANCE"))
    validate_success(advance_phase(program["id"], "ADVANCE"))
    return program


def test_accumulated_throws_inside_the_phase_allowance_band_reads_met():
    """PRD 3.6: "The program's programmed maximum is `target_catch_play_throws`
    multiplied by a per-mille allowance that varies by phase, floor-divided by
    one hundred: the allowance is 100 per-mille at `PHASE_1`, 105 at `PHASE_2`,
    125 at `PHASE_3`, 150 at `PHASE_4`"
    PRD 3.6: "`schedule_requirement_throws` is the accumulated throws plus
    `age_factor` plus that bump."

    Design: Difficulty/combinatorial_formula/throwing_requirement_band_uses_phase_allowance_and_day_of_game_bump
    """
    set_test_clock()
    complex_ = create_complex()
    program = _pitcher_at_phase_three(complex_["id"], target_throws=200)

    row = get_throw_program(program["id"])
    assert row["program_phase"] == "PHASE_3"
    assert row["cumulative_throws"] == 250
    assert row["schedule_requirement_throws"] == 250
    assert row["requirement_status"] == "MET"


def test_the_same_workload_falls_outside_the_band_one_phase_later():
    """PRD 3.6: "Because the band moves with the phase, the same accumulated
    workload can read `UNMET` at `PHASE_4` and `MET` the instant the program
    reaches `PHASE_LIVE`, with no new session logged."

    Design: Difficulty/combinatorial_formula/throwing_requirement_band_uses_phase_allowance_and_day_of_game_bump
    """
    set_test_clock()
    complex_ = create_complex()
    program = _pitcher_at_phase_three(complex_["id"], target_throws=200)

    validate_success(advance_phase(program["id"], "ADVANCE"))

    row = get_throw_program(program["id"])
    assert row["program_phase"] == "PHASE_4"
    assert row["cumulative_throws"] == 250
    assert row["requirement_status"] == "UNMET", (
        "250 throws lands below the PHASE_4 band's 300-throw floor"
    )


def _program_targeting(complex_id, target_throws=40):
    _player, _roster, _profile, _group, _assignment, program = setup_pitcher_program(
        complex_id, target_catch_play_throws=target_throws, target_bullpen_sessions=2)
    return program


def test_under_target_workload_leaves_the_program_in_its_first_phase():
    """PRD 3.6: "From `PHASE_1`, an advance requires `cumulative_throws` to have
    reached `target_catch_play_throws`"

    Design: Difficulty/non_linear_state_machine/throwing_program_cycle_between_phase_two_and_phase_one
    """
    set_test_clock()
    complex_ = create_complex()
    program = _program_targeting(complex_["id"], target_throws=40)
    log_catch_play(program["id"], 35)

    advance = api_client.advance_phase(
        program["id"], "ADVANCE", TEST_USERS["pitching_coordinator_headers"])
    assert advance.json()["response_type"] == "error"

    # a regression is not a declared edge out of PHASE_1 either
    regress = api_client.advance_phase(
        program["id"], "REGRESS", TEST_USERS["pitching_coordinator_headers"])
    assert regress.json()["response_type"] == "error"

    assert get_throw_program(program["id"])["program_phase"] == "PHASE_1"


def test_program_reaches_phase_three_once_both_targets_are_satisfied():
    """PRD 3.6: "From `PHASE_2`, an advance requires `cumulative_bullpen_sessions`
    to have reached `target_bullpen_sessions`; it moves to `PHASE_3`, recomputes
    the score, and mirrors `PHASE_3` onto the profile."

    Design: Difficulty/non_linear_state_machine/throwing_program_cycle_between_phase_two_and_phase_one
    """
    set_test_clock()
    complex_ = create_complex()
    program = _program_targeting(complex_["id"], target_throws=40)
    log_catch_play(program["id"], 40)
    validate_success(advance_phase(program["id"], "ADVANCE"))
    log_bullpen(program["id"])
    log_bullpen(program["id"])
    validate_success(advance_phase(program["id"], "ADVANCE"))

    row = get_throw_program(program["id"])
    assert row["program_phase"] == "PHASE_3"
    assert row["cumulative_bullpen_sessions"] == 2