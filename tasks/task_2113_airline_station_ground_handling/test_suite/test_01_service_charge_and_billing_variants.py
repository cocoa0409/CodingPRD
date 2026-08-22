"""Service-level pricing: the provisional and final charge variants, the
four-input excess/season/subcontract formula, the pinned penalty rounding
order and the volume-rebate allocation."""
from test_helpers import (
    add_agent_occupation,
    add_billing_line,
    add_gse_occupation,
    assert_line_net_identity,
    assert_period_ledger_identity,
    assert_pct,
    complete_turn,
    create_approved_subcontractor,
    create_billing_period,
    create_certified_agent,
    create_flight_bank,
    create_gse_unit,
    create_open_station,
    create_turn,
    finalize_period,
    get_billing_line,
    get_billing_period,
    get_station,
    get_turn,
    publish_and_approve_staffing,
    start_turn,
)


# ---------------------------------------------------------------------------
# Queue A: dual_variant_calc / billing_line_provisional_vs_final_charge_diverges
# ---------------------------------------------------------------------------

def _setup_line_accrued_then_turn_run():
    """ZRH (SUMMER, tolerance 15) with TOWING_ONLY LX318 scheduled 06:00-06:20.
    A provisional line is accrued while the turn is still SCHEDULED, then the
    turn runs 06:00-06:38 with delay_code GH_EQUIPMENT."""
    station = create_open_station(
        clock="2026-04-01T00:00:00Z", iata_code="ZRH", name="Zurich",
        handler_code="SWP", season_code="SUMMER", otp_target_pct=85.00,
        otp_tolerance_minutes=15, gse_reposition_buffer_minutes=20,
        penalty_cap_cents=5000000, damage_penalty_multiplier=1.00)
    bank = create_flight_bank(station["id"], bank_code="AM1", planned_headcount=1)
    turn = create_turn(station["id"], bank["id"], flight_number="LX318",
                       turn_type="TOWING_ONLY")
    agent = create_certified_agent(station["id"])
    gse = create_gse_unit(station["id"], condition_score=95,
                          service_interval_cycles=25, cycles_since_service=0)
    publish_and_approve_staffing(bank["id"])
    period = create_billing_period(station["id"], period_code="2026-04")
    line = add_billing_line(period["id"], turn["id"])
    add_agent_occupation(turn["id"], agent["id"],
                         window_start="2026-04-10T05:50:00Z",
                         window_end="2026-04-10T06:30:00Z")
    add_gse_occupation(turn["id"], gse_unit_id=gse["id"],
                       window_start="2026-04-10T05:55:00Z",
                       window_end="2026-04-10T06:25:00Z")
    start_turn(turn["id"], actual_in="2026-04-10T06:00:00Z")
    complete_turn(turn["id"], actual_out="2026-04-10T06:38:00Z",
                  delay_code="GH_EQUIPMENT")
    return station, turn, period, line


def test_provisional_line_charges_scheduled_ground_time_with_no_penalties(api):
    """PRD §3.9: "While the line is `PROVISIONAL`, `charged_ground_minutes` is
    the turnaround's `scheduled_ground_minutes`."
    PRD §3.9: "While a line is `PROVISIONAL`, both `otp_penalty_cents` and
    `damage_penalty_cents` are exactly 0, and its `rebate_alloc_cents` is 0 as
    well."
    PRD §3.4: "A towing-only movement needs 1 agent and 1 piece of equipment,
    bills at 18000 cents, and has a standard ground time of 20 minutes."

    Design: Difficulty/dual_variant_calc/billing_line_provisional_vs_final_charge_diverges
    """
    _station, _turn, _period, line = _setup_line_accrued_then_turn_run()
    line = get_billing_line(line["id"])
    assert line["status"] == "PROVISIONAL"
    assert line["charged_ground_minutes"] == 20, (
        "the provisional variant reads scheduled_ground_minutes, not the "
        f"38 actual minutes; got {line['charged_ground_minutes']}")
    assert line["base_rate_cents"] == 18000
    assert line["excess_minutes"] == 0
    assert line["gross_amount_cents"] == 18000
    assert line["otp_penalty_cents"] == 0
    assert line["damage_penalty_cents"] == 0
    assert line["rebate_alloc_cents"] == 0
    assert line["net_amount_cents"] == 18000
    assert_line_net_identity(line)


def test_finalized_line_recharges_actual_ground_time_and_takes_otp_penalty(api):
    """PRD §3.9: "Once the line is `FINAL`, `charged_ground_minutes` is the
    turnaround's `actual_ground_minutes` when that turnaround is `COMPLETED`,
    and falls back to `scheduled_ground_minutes` when the turnaround is
    `CANCELLED`, since a cancelled turnaround has no actuals."
    PRD §3.9: "Once a line is `FINAL`, its `otp_penalty_cents` is 12 percent of
    its own `gross_amount_cents`, rounded half up to a whole cent, but only
    when the charged turnaround's `otp_result` is `DELAYED` **and** its
    `delay_code` is one of the handler-attributable codes `GH_STAFFING`,
    `GH_EQUIPMENT` or `GH_LOADING`; in every other case it is 0."
    PRD §3.9: "On success every non-void line moves `PROVISIONAL → FINAL` and
    is recomputed under the final variant of both the charge and the penalty
    rules, the eight-step rollup runs, and `finalized_by_user_id` is stamped
    with the acting `X-User-ID`."

    Design: Difficulty/dual_variant_calc/billing_line_provisional_vs_final_charge_diverges
    """
    _station, turn, period, line = _setup_line_accrued_then_turn_run()
    finalize_period(period["id"], user_id="bc-01")

    line = get_billing_line(line["id"])
    assert line["status"] == "FINAL"
    assert line["charged_ground_minutes"] == 38
    assert line["excess_minutes"] == 18
    assert line["ground_time_tier"] == "TIER_2"
    # 18000 base + 900*15 + 1400*3 = 35700, no multipliers at SUMMER/DIRECT.
    assert line["gross_amount_cents"] == 35700
    assert line["otp_penalty_cents"] == 4284, (
        "12 percent of 35700 rounds half up to 4284; got "
        f"{line['otp_penalty_cents']}")
    assert line["damage_penalty_cents"] == 0
    assert line["rebate_alloc_cents"] == 0
    assert line["net_amount_cents"] == 31416
    assert_line_net_identity(line)

    turn = get_turn(turn["id"])
    assert turn["otp_result"] == "DELAYED"

    period = get_billing_period(period["id"])
    assert period["status"] == "PENDING_APPROVAL"
    assert period["gross_total_cents"] == 35700
    assert period["rebate_tier"] == "NONE"
    assert period["accrued_cents"] == 31416
    assert period["net_total_cents"] == 31416
    assert_period_ledger_identity(period)


# ---------------------------------------------------------------------------
# Queue A: combinatorial_formula / turn_service_charge_four_input_nonlinear_mode_a
# ---------------------------------------------------------------------------

def _setup_winter_subcontracted_charge():
    """GVA (WINTER) TOWING_ONLY LX999 scheduled 06:00-06:20, run 06:00-06:42
    by a subcontracted agent, with delay_code WEATHER so no penalty applies."""
    station = create_open_station(
        clock="2026-04-01T00:00:00Z", iata_code="GVA", name="Geneva",
        handler_code="MNZ", season_code="WINTER", otp_target_pct=85.00,
        otp_tolerance_minutes=15, gse_reposition_buffer_minutes=20,
        penalty_cap_cents=5000000, damage_penalty_multiplier=1.00)
    subcontractor = create_approved_subcontractor(
        station["id"], legal_name="Jet Handling Sarl")
    bank = create_flight_bank(station["id"], bank_code="W1",
                              season_code="WINTER", planned_headcount=1)
    turn = create_turn(station["id"], bank["id"], flight_number="LX999",
                       turn_type="TOWING_ONLY")
    agent = create_certified_agent(
        station["id"], employee_code="E010", full_name="Cleo Marin",
        subcontractor_id=subcontractor["id"])
    gse = create_gse_unit(station["id"], condition_score=90,
                          service_interval_cycles=25, cycles_since_service=0)
    publish_and_approve_staffing(bank["id"])
    add_agent_occupation(turn["id"], agent["id"],
                         window_start="2026-04-10T05:50:00Z",
                         window_end="2026-04-10T06:50:00Z")
    add_gse_occupation(turn["id"], gse_unit_id=gse["id"],
                       window_start="2026-04-10T05:55:00Z",
                       window_end="2026-04-10T06:45:00Z")
    start_turn(turn["id"], actual_in="2026-04-10T06:00:00Z")
    complete_turn(turn["id"], actual_out="2026-04-10T06:42:00Z",
                  delay_code="WEATHER")
    period = create_billing_period(station["id"], period_code="2026-04")
    line = add_billing_line(period["id"], turn["id"])
    finalize_period(period["id"], user_id="bc-01")
    return station, turn, period, line


def test_winter_subcontracted_excess_charge_combines_all_four_inputs(api):
    """PRD §3.9: "The excess is charged at three marginal rates: 900 cents for
    each of the first 15 excess minutes, 1400 cents for each of the next 30
    excess minutes — that is, minutes 16 through 45 — and 2100 cents for every
    excess minute beyond the 45th."
    PRD §3.9: "The seasonal multiplier reflects winter-operations and de-icing
    cost across the whole station: it is 1.15 when the station's `season_code`
    is `WINTER` and 1.00 when it is `SUMMER`."
    PRD §3.9: "The base rate plus the excess charge, multiplied by the seasonal
    multiplier and then by the subcontract factor, is rounded half up to a
    whole cent exactly once — after both multiplications, in exact decimal
    arithmetic."

    Design: Difficulty/combinatorial_formula/turn_service_charge_four_input_nonlinear_mode_a
    """
    _station, turn, _period, line = _setup_winter_subcontracted_charge()
    turn = get_turn(turn["id"])
    assert turn["actual_ground_minutes"] == 42
    assert turn["delay_minutes"] == 22

    line = get_billing_line(line["id"])
    assert line["base_rate_cents"] == 18000
    assert line["excess_minutes"] == 22
    assert line["ground_time_tier"] == "TIER_2"
    # (18000 + 900*15 + 1400*7) * 1.15 * 0.965 = 45832.675 -> 45833
    assert line["gross_amount_cents"] == 45833, (
        "exact decimal arithmetic rounded half up exactly once; got "
        f"{line['gross_amount_cents']}")


def test_weather_delay_is_excluded_so_the_gross_charge_stands_alone(api):
    """PRD §3.4: "Otherwise, if `delay_code` is `CARRIER`, `ATC` or `WEATHER`,
    the `otp_result` is `EXCLUDED`: the delay was not the handler's to
    prevent."
    PRD §3.4: "`EXCLUDED` and `PENDING` turnarounds appear in neither the
    numerator nor the denominator."
    PRD §3.9: "Step eight sets the period's `accrued_cents` to the sum of
    `net_amount_cents` over its lines at `PROVISIONAL` or `FINAL`, and its
    `net_total_cents` to `gross_total_cents` less `otp_penalty_cents`, less
    `damage_penalty_cents`, plus `rebate_cents`."

    Design: Difficulty/combinatorial_formula/turn_service_charge_four_input_nonlinear_mode_a
    """
    station, turn, period, line = _setup_winter_subcontracted_charge()
    turn = get_turn(turn["id"])
    assert turn["otp_result"] == "EXCLUDED"

    line = get_billing_line(line["id"])
    assert line["otp_penalty_cents"] == 0
    assert line["net_amount_cents"] == 45833
    assert_line_net_identity(line)

    period = get_billing_period(period["id"])
    assert period["gross_total_cents"] == 45833
    assert period["rebate_tier"] == "NONE"
    assert period["net_total_cents"] == 45833
    assert_period_ledger_identity(period)

    station = get_station(station["id"])
    assert station["completed_turn_count"] == 0
    assert_pct(station["otp_rolling_pct"], 100.00, "otp_rolling_pct")


# ---------------------------------------------------------------------------
# Queue A: combinatorial_formula / otp_penalty_round_per_line_then_sum_mode_b
# ---------------------------------------------------------------------------

def _setup_two_delayed_subcontracted_lines():
    """Two delayed TOWING_ONLY turns handled by the same subcontracted agent:
    LX111 grosses 18239 and LX222 grosses 39855, together 58094."""
    station = create_open_station(
        clock="2026-04-01T00:00:00Z", iata_code="ZRH", name="Zurich",
        handler_code="SWP", season_code="SUMMER", otp_target_pct=85.00,
        otp_tolerance_minutes=15, gse_reposition_buffer_minutes=20,
        penalty_cap_cents=5000000, damage_penalty_multiplier=1.00)
    subcontractor = create_approved_subcontractor(
        station["id"], legal_name="Alpine Ramp AG")
    bank = create_flight_bank(station["id"], bank_code="AM1", planned_headcount=2)
    turn_b = create_turn(station["id"], bank["id"], flight_number="LX111",
                         turn_type="TOWING_ONLY",
                         scheduled_in="2026-04-10T06:00:00Z",
                         scheduled_out="2026-04-10T06:20:00Z")
    turn_a = create_turn(station["id"], bank["id"], flight_number="LX222",
                         turn_type="TOWING_ONLY",
                         scheduled_in="2026-04-10T07:00:00Z",
                         scheduled_out="2026-04-10T07:20:00Z")
    agent = create_certified_agent(
        station["id"], employee_code="E010", full_name="Cleo Marin",
        subcontractor_id=subcontractor["id"])
    gse = create_gse_unit(station["id"], condition_score=95,
                          service_interval_cycles=25, cycles_since_service=0)
    publish_and_approve_staffing(bank["id"])

    add_agent_occupation(turn_b["id"], agent["id"],
                         window_start="2026-04-10T05:55:00Z",
                         window_end="2026-04-10T06:45:00Z")
    add_gse_occupation(turn_b["id"], gse_unit_id=gse["id"],
                       window_start="2026-04-10T05:58:00Z",
                       window_end="2026-04-10T06:45:00Z")
    start_turn(turn_b["id"], actual_in="2026-04-10T06:19:00Z")
    complete_turn(turn_b["id"], actual_out="2026-04-10T06:40:00Z",
                  delay_code="GH_STAFFING")

    add_agent_occupation(turn_a["id"], agent["id"],
                         window_start="2026-04-10T06:55:00Z",
                         window_end="2026-04-10T07:50:00Z")
    add_gse_occupation(turn_a["id"], gse_unit_id=gse["id"],
                       window_start="2026-04-10T06:55:00Z",
                       window_end="2026-04-10T07:50:00Z")
    start_turn(turn_a["id"], actual_in="2026-04-10T07:00:00Z")
    complete_turn(turn_a["id"], actual_out="2026-04-10T07:42:00Z",
                  delay_code="GH_EQUIPMENT")

    period = create_billing_period(station["id"], period_code="2026-04")
    line_b = add_billing_line(period["id"], turn_b["id"])
    line_a = add_billing_line(period["id"], turn_a["id"])
    finalize_period(period["id"], user_id="bc-01")
    return period, line_b, line_a


def test_otp_penalty_is_rounded_on_each_line_before_any_summation(api):
    """PRD §3.9: "The 12 percent on-time penalty is rounded per line, and the
    already-rounded per-line figures are then added into the period's
    `otp_penalty_cents`."
    PRD §2.9: "Where an amount is derived per billing line and then aggregated
    into a period, each line's amount is rounded first and the already-rounded
    line amounts are then added together."

    Design: Difficulty/combinatorial_formula/otp_penalty_round_per_line_then_sum_mode_b
    """
    _period, line_b, line_a = _setup_two_delayed_subcontracted_lines()
    line_b = get_billing_line(line_b["id"])
    line_a = get_billing_line(line_a["id"])
    # (18000 + 900*1) * 0.965 = 18238.5 -> 18239; (18000 + 23300) * 0.965 -> 39855
    assert line_b["gross_amount_cents"] == 18239
    assert line_a["gross_amount_cents"] == 39855
    assert line_b["otp_penalty_cents"] == 2189, (
        "12 percent of 18239 rounds half up to 2189; got "
        f"{line_b['otp_penalty_cents']}")
    assert line_a["otp_penalty_cents"] == 4783, (
        "12 percent of 39855 rounds half up to 4783; got "
        f"{line_a['otp_penalty_cents']}")


def test_period_otp_penalty_is_the_sum_of_rounded_line_penalties(api):
    """PRD §3.9: "Adding the gross amounts together first and taking 12 percent
    of that sum is forbidden and gives a different answer: two delayed lines of
    39855 and 18239 cents produce 4783 plus 2189, that is 6972 cents, under the
    pinned order, where 12 percent of their combined 58094 cents rounds to
    6971."
    PRD §3.9: "Step six takes each line's `otp_penalty_cents` and
    `damage_penalty_cents` from the penalty rules above, and sets the period's
    `otp_penalty_cents` and `damage_penalty_cents` to the sums of those
    per-line figures."

    Design: Difficulty/combinatorial_formula/otp_penalty_round_per_line_then_sum_mode_b
    """
    period, line_b, line_a = _setup_two_delayed_subcontracted_lines()
    period = get_billing_period(period["id"])
    assert period["gross_total_cents"] == 58094
    assert period["otp_penalty_cents"] == 6972, (
        "round-per-line-then-sum yields 6972; sum-then-round would yield 6971, "
        f"got {period['otp_penalty_cents']}")
    assert period["otp_penalty_cents"] != 6971
    assert period["rebate_tier"] == "NONE"

    assert get_billing_line(line_b["id"])["net_amount_cents"] == 16050
    assert get_billing_line(line_a["id"])["net_amount_cents"] == 35072
    assert period["accrued_cents"] == 51122
    assert period["net_total_cents"] == 51122
    assert_period_ledger_identity(period)


# ---------------------------------------------------------------------------
# Queue A: combinatorial_formula / period_rebate_circular_evaluation_order_mode_c
# ---------------------------------------------------------------------------

def _setup_two_on_time_lines_at_the_tier_a_threshold():
    """Two on-time TOWING_ONLY turns grossing 35700 and 24300, i.e. a period
    gross of exactly 60000 cents — the inclusive TIER_A threshold."""
    station = create_open_station(
        clock="2026-04-01T00:00:00Z", iata_code="ZRH", name="Zurich",
        handler_code="SWP", season_code="SUMMER", otp_target_pct=85.00,
        otp_tolerance_minutes=15, gse_reposition_buffer_minutes=20,
        penalty_cap_cents=5000000, damage_penalty_multiplier=1.00)
    bank = create_flight_bank(station["id"], bank_code="AM1", planned_headcount=2)
    turn_p = create_turn(station["id"], bank["id"], flight_number="LX101",
                         turn_type="TOWING_ONLY",
                         scheduled_in="2026-04-10T06:00:00Z",
                         scheduled_out="2026-04-10T06:20:00Z")
    turn_q = create_turn(station["id"], bank["id"], flight_number="LX202",
                         turn_type="TOWING_ONLY",
                         scheduled_in="2026-04-10T08:00:00Z",
                         scheduled_out="2026-04-10T08:20:00Z")
    agent = create_certified_agent(station["id"])
    gse = create_gse_unit(station["id"], condition_score=95,
                          service_interval_cycles=25, cycles_since_service=0)
    publish_and_approve_staffing(bank["id"])

    add_agent_occupation(turn_p["id"], agent["id"],
                         window_start="2026-04-10T05:40:00Z",
                         window_end="2026-04-10T06:25:00Z")
    add_gse_occupation(turn_p["id"], gse_unit_id=gse["id"],
                       window_start="2026-04-10T05:45:00Z",
                       window_end="2026-04-10T06:25:00Z")
    start_turn(turn_p["id"], actual_in="2026-04-10T05:42:00Z")
    complete_turn(turn_p["id"], actual_out="2026-04-10T06:20:00Z",
                  delay_code="NONE")

    add_agent_occupation(turn_q["id"], agent["id"],
                         window_start="2026-04-10T07:50:00Z",
                         window_end="2026-04-10T08:25:00Z")
    add_gse_occupation(turn_q["id"], gse_unit_id=gse["id"],
                       window_start="2026-04-10T07:50:00Z",
                       window_end="2026-04-10T08:25:00Z")
    start_turn(turn_q["id"], actual_in="2026-04-10T07:53:00Z")
    complete_turn(turn_q["id"], actual_out="2026-04-10T08:20:00Z",
                  delay_code="NONE")

    period = create_billing_period(station["id"], period_code="2026-04")
    line_p = add_billing_line(period["id"], turn_p["id"])
    line_q = add_billing_line(period["id"], turn_q["id"])
    finalize_period(period["id"], user_id="bc-01")
    return period, turn_p, turn_q, line_p, line_q


def test_rebate_tier_and_allocation_resolve_the_circular_dependency(api):
    """PRD §3.9: "Step three selects `rebate_tier` from that total: `TIER_B`
    when `gross_total_cents` is at least 150000, `TIER_A` when it is at least
    60000 but below that, and `NONE` otherwise; because the rebate exists only
    in the final variant, the tier is `NONE` while any line in the period is
    still `PROVISIONAL`, so a period that has never been finalized reports
    `NONE` and a `rebate_cents` of 0 no matter how large it is."
    PRD §3.9: "Step four sets `rebate_cents` to `gross_total_cents` multiplied
    by the tier's rebate rate — 0.00 for `NONE`, 0.03 for `TIER_A`, 0.06 for
    `TIER_B` — rounded half up to a whole cent."
    PRD §3.9: "Each line's exact share is `rebate_cents` multiplied by that
    line's `gross_amount_cents` and divided by `gross_total_cents`, held as an
    exact rational value and deliberately not rounded."

    Design: Difficulty/combinatorial_formula/period_rebate_circular_evaluation_order_mode_c
    """
    period, _turn_p, _turn_q, line_p, line_q = (
        _setup_two_on_time_lines_at_the_tier_a_threshold())
    line_p = get_billing_line(line_p["id"])
    line_q = get_billing_line(line_q["id"])
    assert line_p["gross_amount_cents"] == 35700
    assert line_q["gross_amount_cents"] == 24300

    period = get_billing_period(period["id"])
    assert period["gross_total_cents"] == 60000, (
        "round each line then sum: 35700 + 24300 lands exactly on the "
        f"inclusive TIER_A threshold; got {period['gross_total_cents']}")
    assert period["rebate_tier"] == "TIER_A"
    assert period["rebate_cents"] == 1800
    assert line_p["rebate_alloc_cents"] == 1071
    assert line_q["rebate_alloc_cents"] == 729
    assert (line_p["rebate_alloc_cents"] + line_q["rebate_alloc_cents"]
            == period["rebate_cents"])


def test_rebate_allocation_keeps_accrued_and_net_total_equal(api):
    """PRD §3.9: "Step seven sets each line's `net_amount_cents` to its
    `gross_amount_cents`, less its `otp_penalty_cents`, less its
    `damage_penalty_cents`, plus its `rebate_alloc_cents`."
    PRD §3.9: "Those two figures must always be equal, and it is precisely the
    largest-remainder allocation in step five that guarantees they are."
    PRD §3.4: "First, if `delay_minutes` is less than or equal to the station's
    `otp_tolerance_minutes`, the `otp_result` is `ON_TIME` — the boundary is
    inclusive, and because this test runs first, a turnaround inside tolerance
    is `ON_TIME` even when its `delay_code` is `WEATHER`."

    Design: Difficulty/combinatorial_formula/period_rebate_circular_evaluation_order_mode_c
    """
    period, turn_p, turn_q, line_p, line_q = (
        _setup_two_on_time_lines_at_the_tier_a_threshold())
    assert get_turn(turn_p["id"])["otp_result"] == "ON_TIME"
    assert get_turn(turn_q["id"])["otp_result"] == "ON_TIME"

    line_p = get_billing_line(line_p["id"])
    line_q = get_billing_line(line_q["id"])
    assert line_p["net_amount_cents"] == 36771
    assert line_q["net_amount_cents"] == 25029
    assert_line_net_identity(line_p)
    assert_line_net_identity(line_q)

    period = get_billing_period(period["id"])
    assert period["otp_penalty_cents"] == 0
    assert period["accrued_cents"] == 61800
    assert period["net_total_cents"] == 61800
    assert_period_ledger_identity(period)
