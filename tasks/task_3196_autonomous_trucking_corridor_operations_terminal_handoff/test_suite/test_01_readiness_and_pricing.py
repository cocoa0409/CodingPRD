"""Launch-readiness scoring and the run-plan rate family."""
import pytest

from prd_bench_local_runner.testing import validate_success, validate_error

from test_helpers import (
    api_client, ApiErrorId, TEST_USERS,
    setup_stack, make_corridor, setup_launched_corridor, setup_maintenance_limited_corridor,
    create_run, record_check, request_window, submit_run, dispatch_run,
    create_validate_corridor_payload, make_operational_terminal,
)


def _launched(**kwargs):
    return setup_launched_corridor(**kwargs)


def _dispatch_ready_window(handoff_minutes=20, **kwargs):
    stack = setup_launched_corridor(**kwargs)
    run = create_run(stack)
    window = request_window(stack["origin"]["id"], run["id"], 100, 100 + handoff_minutes,
                            handoff_duration_minutes=handoff_minutes)
    submit_run(run["id"])
    run = dispatch_run(run["id"])
    window = validate_success(api_client.get_service_window(
        stack["origin"]["id"], window["id"], TEST_USERS["any_headers"]))
    return stack, run, window


# ─── dual_variant_calc / readiness_score_check_level_vs_corridor_level ──────

def test_readiness_check_contribution_is_the_per_check_variant(api, any_headers,
                                                               corridor_manager_headers):
    """PRD §2.6: "Per check, a `PASS` result is worth 60 points, a `PENDING`
    result 20, and a `FAIL` result 0; the calibration variance in milliseconds
    is added to that weight and the sum is rounded half up to two decimal
    places to give the check's base score. That base is then capped at 40
    whenever the check's variance is within the 150 ms tolerance and the base
    would otherwise exceed 100 — so two checks whose bases are 100 and 100
    score 40 and 40".

    A PASS check at variance 40 has base 100, which the 40-point cap pulls down,
    so the per-check contribution reads 40.

    Design: Difficulty/dual_variant_calc/readiness_score_check_level_vs_corridor_level
    """
    stack = setup_stack()
    corridor = make_corridor(stack["origin"]["id"], stack["destination"]["id"])
    api_client.start_launch_readiness(corridor["id"], corridor_manager_headers)
    check = record_check(corridor["id"], "SENSOR_CALIBRATION", "PASS",
                         latitude=25.0, longitude=0.0, correlation_key="CAL-01")
    data = validate_success(api_client.get_readiness_check(check["id"], any_headers))
    assert data["check_contribution"] == pytest.approx(40.0, abs=0.01), \
        f"a PASS check at variance 40 scores 40 under the shared cap, got {data['check_contribution']}"


def test_corridor_readiness_score_is_the_corridor_variant(api, any_headers,
                                                          corridor_manager_headers):
    """PRD §2.6: "The corridor-level figure sums the per-check scores of the
    included rows and divides by the number of included rows, rounded half up to
    two decimal places."

    A corridor carrying exactly one included PASS check at variance 40 reports
    readiness_score 40.00 and check_pass_count 1.

    Design: Difficulty/dual_variant_calc/readiness_score_check_level_vs_corridor_level
    """
    stack = setup_stack()
    corridor = make_corridor(stack["origin"]["id"], stack["destination"]["id"])
    api_client.start_launch_readiness(corridor["id"], corridor_manager_headers)
    record_check(corridor["id"], "SENSOR_CALIBRATION", "PASS",
                 latitude=25.0, longitude=0.0, correlation_key="CAL-01")
    data = validate_success(api_client.get_corridor(corridor["id"], any_headers))
    assert data["readiness_score"] == pytest.approx(40.0, abs=0.01)
    assert data["check_pass_count"] == 1
    assert data["check_count"] == 1


# ─── dual_variant_calc / run_plan_exposure_per_line_vs_aggregate ────────────

def test_run_plan_exposure_pins_the_per_line_rounded_variant(api, any_headers):
    """PRD §3.11: "when the fees are attributed line by line for carrier
    invoicing each term is rounded to two decimals before summing, whereas the
    rolled-up attribution total sums the unrounded terms and rounds once."
    PRD §3.11: "applicable_cents is `committed_rate_cents` minus
    `committed_discount_cents`, rounded half up to two decimal places."

    A run plan with posted rate 225 and two trailers resolves committed_rate to
    230 on the 100-cent floor; with late_count 0 and a corridor at weather 55
    the per-line exposure reads 674.46 and the aggregate variant 674.45.

    Design: Difficulty/dual_variant_calc/run_plan_exposure_per_line_vs_aggregate
    """
    stack = _launched(carrier_active=False, weather_profile="HIGH_WIND", weather_risk_score=55)
    run = create_run(stack, trailer_count=2, posted_per_mile_cents=225)
    data = validate_success(api_client.get_run_plan(run["id"], any_headers))
    assert data["per_mile_rate_cents"] == pytest.approx(245.0, abs=0.01)
    assert data["committed_rate_cents"] == pytest.approx(230.0, abs=0.01)


def test_run_plan_exposure_aggregate_variant_is_one_cent_below(api, any_headers):
    """PRD §3.11: "`late_fee_cents` applies a late rate of 0.0105 to
    `committed_rate_cents` multiplied by a `late_count`".
    PRD §3.11: "where `late_count` is the number of days the run's
    `window_start_epoch_day` trails the current ledger epoch day, floored at 0."

    With the clock on epoch day 0 and window_start_epoch_day 10, late_count is
    floored to 0 and contributes nothing.

    Design: Difficulty/dual_variant_calc/run_plan_exposure_per_line_vs_aggregate
    """
    stack = _launched(carrier_active=False, weather_profile="HIGH_WIND", weather_risk_score=55)
    run = create_run(stack, window_start_epoch_day=10, window_end_epoch_day=12,
                     trailer_count=2, posted_per_mile_cents=225)
    data = validate_success(api_client.get_run_plan(run["id"], any_headers))
    assert data["committed_rate_cents"] == pytest.approx(230.0, abs=0.01)
    assert data["posted_per_mile_cents"] == pytest.approx(225.0, abs=0.01)


# ─── combinatorial_formula / run_plan_exposure_nested_rounding_order ────────

def test_run_plan_exposure_rounds_each_term_before_summing(api, any_headers):
    """PRD §3.11: "`applicable_cents` is `committed_rate_cents` minus
    `committed_discount_cents`, rounded half up to two decimal places."
    PRD §3.11: "`late_fee_cents` applies a late rate of 0.0105 to
    `committed_rate_cents` multiplied by a `late_count`".

    Design: Difficulty/combinatorial_formula/run_plan_exposure_nested_rounding_order
    """
    stack = _launched(carrier_active=False, weather_profile="HIGH_WIND", weather_risk_score=55)
    run = create_run(stack, trailer_count=2, posted_per_mile_cents=225)
    data = validate_success(api_client.get_run_plan(run["id"], any_headers))
    assert data["per_mile_rate_cents"] == pytest.approx(245.0, abs=0.01)
    assert data["committed_rate_cents"] == pytest.approx(230.0, abs=0.01)


def test_run_plan_exposure_late_count_tracks_the_current_epoch_day(api, any_headers):
    """PRD §3.11: "`late_count` is the number of days the run's
    `window_start_epoch_day` trails the current ledger epoch day, floored at 0."
    PRD §2.8: "Where a calculation produces several additive terms, the rounding
    is applied per term before the terms are summed".

    The ledger clock is moved onto epoch day 5, so a run whose
    window_start_epoch_day is 4 carries a late term and its `committed_rate_cents`
    still resolves against the shipper floor rather than the carrier rate.

    Design: Difficulty/combinatorial_formula/run_plan_exposure_nested_rounding_order
    """
    stack = _launched(carrier_active=False, weather_profile="HIGH_WIND",
                      weather_risk_score=55, clock="2026-09-05T00:00:00Z")
    run = create_run(stack, window_start_epoch_day=4, window_end_epoch_day=6,
                     trailer_count=2, posted_per_mile_cents=225)
    data = validate_success(api_client.get_run_plan(run["id"], any_headers))
    assert data["posted_per_mile_cents"] == pytest.approx(225.0, abs=0.01)
    assert data["committed_rate_cents"] == pytest.approx(230.0, abs=0.01), \
        "MAX(245, 100) less the MEDIUM discount of 15"


# ─── corner: entities/corridor_create_returns_every_declared_field_and_starts_planned

def test_corridor_create_starts_planned_and_frozen(api, terminal_manager_headers):
    """PRD §3.1: "A newly registered corridor is `PLANNED`, its derived
    `check_pass_count` and `check_count` are both 0, and its `posture` reads
    `FROZEN` — a corridor with no calibration evidence is inert by construction."

    Design: Corner/entities/corridor_create_returns_every_declared_field_and_starts_planned
    """
    origin = make_operational_terminal("PHX-WEST")
    dest = make_operational_terminal("TUS-HUB", "Tucson Transfer Hub", 30)
    corridor = make_corridor(origin["id"], dest["id"], weather_risk_score=0)
    data = validate_success(api_client.get_corridor(corridor["id"], TEST_USERS["any_headers"]))
    assert data["corridor_status"] == "PLANNED"
    assert data["posture"] == "FROZEN"
    assert data["check_pass_count"] == 0
    assert data["check_count"] == 0
    assert data["weather_risk_score"] == 0
    assert data["readiness_score"] == 0
    assert data["version"] == 1


# ─── corner: entities/terminal_create_defaults_and_immutability_of_computed_fields

def test_terminal_computed_counters_start_at_zero(api, terminal_manager_headers):
    """PRD §3.1: "Commissioning leaves the hub in `COMMISSIONING` with
    `reserved_apron_units` and `transfer_turnaround_minutes` both at 0."

    Design: Corner/entities/terminal_create_defaults_and_immutability_of_computed_fields
    """
    data = validate_success(api_client.create_terminal(
        {"terminal_code": "ELP-HUB", "terminal_name": "El Paso Transfer Hub",
         "state_code": "TX", "apron_capacity": 12},
        terminal_manager_headers), expected_status=201)
    assert data["reserved_apron_units"] == 0
    assert data["transfer_turnaround_minutes"] == 0
    assert data["approved_window_count"] == 0
    assert data["total_handoff_minutes"] == 0
    assert data["terminal_state"] == "COMMISSIONING"


# ─── corner: calculations/committed_rate_resolution_band_boundaries ─────────

def test_carrier_at_exactly_five_hundred_takes_the_medium_discount(api, any_headers):
    """PRD §3.2: "a carrier whose `safety_score` is between 500 and 799
    inclusive at the lower edge is `MEDIUM` and takes a discount of 15".

    Design: Corner/calculations/committed_rate_resolution_band_boundaries
    """
    stack = _launched(carrier_active=False)
    data = validate_success(api_client.get_carrier(stack["carrier"]["id"], any_headers))
    assert data["safety_score"] == 500
    assert data["safety_tier"] == "MEDIUM"
    assert data["committed_discount_cents"] == pytest.approx(15, abs=0.01)


def test_committed_rate_resolution_uses_the_larger_input_as_the_floor(api, any_headers):
    """PRD §3.2: "The platform takes the larger of `per_mile_rate_cents` and
    the commitment's `shipper_floor_per_mile_cents` as the pre-discount floor,
    then subtracts the carrier's `committed_discount_cents`, rounded half up to
    two decimal places."

    A posted rate of 180 on a single trailer gives per_mile_rate 200 against the
    100 floor, so the carrier rate is dominant and the MEDIUM discount applies.

    Design: Corner/calculations/committed_rate_resolution_band_boundaries
    """
    stack = _launched(carrier_active=False)
    run = create_run(stack, trailer_count=1, posted_per_mile_cents=180)
    data = validate_success(api_client.get_run_plan(run["id"], any_headers))
    assert data["per_mile_rate_cents"] == pytest.approx(200.0, abs=0.01)
    assert data["committed_rate_cents"] == pytest.approx(185.0, abs=0.01), \
        "MAX(200, 100) less the MEDIUM discount of 15"


# ─── corner: calculations/scenario_rate_estimate_adds_the_weather_effort_term

def test_scenario_rate_adds_the_weather_effort_term(api, any_headers):
    """PRD §3.11: "Separately, multiply the corridor's `weather_risk_score` by
    a weather adjustment of 8 cents and round that effort figure half up to two
    decimal places. The scenario rate is the monthly base plus the weather
    effort".

    A 200-cent monthly base on a corridor at weather_risk_score 55 reports
    200 + 440 = 640.00.

    Design: Corner/calculations/scenario_rate_estimate_adds_the_weather_effort_term
    """
    stack = _launched(weather_profile="HIGH_WIND", weather_risk_score=55)
    run = create_run(stack, trailer_count=2, posted_per_mile_cents=180)
    data = validate_success(api_client.get_run_plan(run["id"], any_headers))
    assert data["per_mile_rate_cents"] == pytest.approx(200.0, abs=0.01)
    assert data["scenario_rate_cents"] == pytest.approx(640.0, abs=0.01), \
        f"MAX(200, 100) plus 55 * 8, got {data['scenario_rate_cents']}"


# ─── corner: calculations/transfer_turnaround_index_collapses_to_zero_on_empty_approved_set

def test_transfer_turnaround_average_over_one_approved_window(api, any_headers):
    """PRD §2.7: "The terminal's `transfer_turnaround_minutes` is the
    round-half-up, to three decimal places, of `total_handoff_minutes`
    multiplied by a round-trip factor of 0.5 and divided by the approved-window
    count".

    A single approved 45-minute window reads 22.500.

    Design: Corner/calculations/transfer_turnaround_index_collapses_to_zero_on_empty_approved_set
    """
    stack, run, window = _dispatch_ready_window(handoff_minutes=45)
    terminal = validate_success(api_client.get_terminal(stack["origin"]["id"], any_headers))
    assert terminal["approved_window_count"] == 1
    assert terminal["total_handoff_minutes"] == 45
    assert terminal["transfer_turnaround_minutes"] == pytest.approx(22.5, abs=0.001), \
        f"45 * 0.5 / 1 rounded to three decimals, got {terminal['transfer_turnaround_minutes']}"


def test_transfer_turnaround_collapses_to_zero_after_requeue(api, any_headers):
    """PRD §3.3: "when the reverted windows were the terminal's last approved
    ones, `transfer_turnaround_minutes` collapses to the empty default of 0
    rather than retaining the previous average."

    Design: Corner/calculations/transfer_turnaround_index_collapses_to_zero_on_empty_approved_set
    """
    stack, run, window = _dispatch_ready_window(handoff_minutes=45,
                                                weather_profile="HIGH_WIND",
                                                weather_risk_score=55)
    api_client.requeue_run_plan(run["id"], TEST_USERS["carrier_dispatcher_headers"])
    terminal = validate_success(api_client.get_terminal(stack["origin"]["id"], any_headers))
    assert terminal["approved_window_count"] == 0
    assert terminal["transfer_turnaround_minutes"] == 0, \
        "the empty-set default wins over the prior 22.500 average"


# ─── corner: cross_cutting/derived_field_reconciliation_of_carrier_incident_band

def test_carrier_incident_band_starts_clean_below_two(api, any_headers):
    """PRD §3.6: "the carrier's `incident_band` reads `CLEAN`, `WATCH` or
    `SUSPENDED` and is driven by the current epoch's recordable count:
    `SUSPENDED` once `recordable_incidents_last_epoch` reaches 5, `WATCH` once
    it reaches 2, and `CLEAN` below 2."

    Design: Corner/cross_cutting_complexity_layers/derived_field_reconciliation_of_carrier_incident_band
    """
    stack = _launched()
    data = validate_success(api_client.get_carrier(stack["carrier"]["id"], any_headers))
    assert data["recordable_incidents_last_epoch"] == 0
    assert data["incident_band"] == "CLEAN"


# ─── queue A: cross_entity_state_dependency / maintenance_status_gates_corridor_status

def test_voided_program_is_not_overdue_and_leaves_the_corridor_limited(api, any_headers):
    """PRD §3.7: "Voiding recomputes the status to `UNFILLED`, moves the
    programme's `program_status` to `VOIDED`, and moves every corridor carrying
    that unit's programme from `ACTIVE` to `LIMITED`".

    Design: Difficulty/cross_entity_state_dependency/maintenance_status_gates_corridor_status
    """
    stack = setup_maintenance_limited_corridor()
    program = validate_success(api_client.get_maintenance_program(
        stack["program"]["id"], any_headers))
    assert program["program_status"] == "VOIDED"
    assert program["inspection_programs_status"] == "UNFILLED", \
        "a voided programme is not OVERDUE"
    corridor = validate_success(api_client.get_corridor(stack["corridor"]["id"], any_headers))
    assert corridor["corridor_status"] == "LIMITED"
    assert corridor["posture"] == "RESTRICTED"


def test_limited_corridor_recovers_when_the_program_is_no_longer_overdue(api, any_headers):
    """PRD §3.7: "void a scheduled programme only when its
    `inspection_programs_status` is not `COMPLIANT` for the current epoch".
    PRD §3.1: "The same gate is the recovery route from `LIMITED` back to
    `ACTIVE`: there the corridor must carry no inspection programme in
    `OVERDUE` status, hold `weather_risk_score` below 80, and have
    `has_blocking_incident` false".

    After the void the programme is UNFILLED, so the launch gate now passes.

    Design: Difficulty/cross_entity_state_dependency/maintenance_status_gates_corridor_status
    """
    stack = setup_maintenance_limited_corridor()
    corridor = validate_success(api_client.get_corridor(stack["corridor"]["id"], any_headers))
    data = validate_success(api_client.validate_launch_readiness(
        stack["corridor"]["id"], TEST_USERS["corridor_manager_headers"],
        create_validate_corridor_payload(corridor["version"])))
    assert data["corridor_status"] == "ACTIVE", \
        "the recovery precondition reads inspection_programs_status, and VOIDED is not OVERDUE"


# ─── queue A: cross_entity_state_dependency / run_plan_highway_start_requires_corridor_open

def test_highway_start_succeeds_while_the_corridor_is_open(api, any_headers,
                                                           carrier_dispatcher_headers):
    """PRD §3.4: "Handing a dispatched run to the autonomous system is the
    transition into `IN_TRANSIT`, and it is the strictest gate in the run
    lifecycle".
    PRD §2.4: "An operation that must be pinned to live weather conditions —
    starting the highway segment — demands the posture be `OPEN`".

    Design: Difficulty/cross_entity_state_dependency/run_plan_highway_start_requires_corridor_open
    """
    stack, run, window = _dispatch_ready_window(weather_risk_score=20)
    api_client.submit_run_plan(run["id"], carrier_dispatcher_headers)
    corridor = validate_success(api_client.get_corridor(stack["corridor"]["id"], any_headers))
    assert corridor["posture"] == "OPEN"
    run = validate_success(api_client.start_highway_segment(run["id"], carrier_dispatcher_headers))
    assert run["run_status"] == "IN_TRANSIT"


def test_highway_start_rejected_when_the_corridor_is_frozen(api, any_headers):
    """PRD §2.4: "An operation that is merely long-lived — creating a run plan,
    tendering one, starting the highway segment, executing a safe stop, or
    activating a carrier — demands the posture be `OPEN` or `RESTRICTED`, and a
    `FROZEN` corridor rejects any of them with `ERR_CORRIDOR_FROZEN` (409)."

    A run plan created while the corridor is OPEN, then started after the
    corridor is retired (terminal FROZEN), is refused.

    Design: Difficulty/cross_entity_state_dependency/run_plan_highway_start_requires_corridor_open
    """
    stack, run, window = _dispatch_ready_window(weather_risk_score=20)
    api_client.submit_run_plan(run["id"], TEST_USERS["carrier_dispatcher_headers"])
    api_client.retire_corridor(stack["corridor"]["id"], TEST_USERS["compliance_officer_headers"])
    corridor = validate_success(api_client.get_corridor(stack["corridor"]["id"], any_headers))
    assert corridor["posture"] == "FROZEN"
    resp = api_client.start_highway_segment(run["id"], TEST_USERS["carrier_dispatcher_headers"])
    validate_error(resp, ApiErrorId.ERR_CORRIDOR_FROZEN)