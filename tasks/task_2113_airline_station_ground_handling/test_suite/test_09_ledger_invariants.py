"""Conserved quantities and immediate visibility: minute ledgers, accrued
cents, the compensating void and reject, and the derived values a request
publishes on the way out."""
from test_helpers import (
    add_agent_occupation,
    add_billing_line,
    add_gse_occupation,
    assert_no_ledger_drift,
    assert_pct,
    assert_period_ledger_identity,
    close_out_incident,
    complete_turn,
    create_approved_subcontractor,
    create_billing_period,
    create_certified_agent,
    create_flight_bank,
    create_gse_unit,
    create_open_station,
    create_turn,
    decide_oversight,
    finalize_period,
    get_agent,
    get_billing_line,
    get_billing_period,
    get_flight_bank,
    get_gse_unit,
    get_incident,
    get_station,
    get_turn,
    get_turn_resource,
    publish_and_approve_staffing,
    reject_period,
    release_occupation,
    report_incident,
    start_turn,
    void_billing_line,
)


# ---------------------------------------------------------------------------
# Queue A: compensating_invariant /
#          gse_occupation_minutes_conserved_across_create_and_release
# ---------------------------------------------------------------------------

def _create_then_release_equipment_occupation():
    """A turn that already carries a 40-minute agent occupation takes a
    45-minute tug occupation and then releases it again."""
    station = create_open_station(gse_reposition_buffer_minutes=20)
    bank = create_flight_bank(station["id"], planned_headcount=1)
    turn = create_turn(station["id"], bank["id"])
    agent = create_certified_agent(station["id"])
    gse = create_gse_unit(station["id"], condition_score=95,
                          service_interval_cycles=25, cycles_since_service=0)
    publish_and_approve_staffing(bank["id"])
    agent_resource = add_agent_occupation(turn["id"], agent["id"])
    minutes_before = get_gse_unit(gse["id"])["committed_occupation_minutes"]

    gse_resource = add_gse_occupation(turn["id"], gse_unit_id=gse["id"],
                                      window_start="2026-04-10T05:45:00Z",
                                      window_end="2026-04-10T06:30:00Z")
    turn_after_create = get_turn(turn["id"])
    minutes_mid = get_gse_unit(gse["id"])["committed_occupation_minutes"]
    released = release_occupation(gse_resource["id"], reason="TUG_REALLOCATED")
    minutes_after = get_gse_unit(gse["id"])["committed_occupation_minutes"]
    return {"station": station, "bank": bank, "turn": turn, "agent": agent,
            "gse": gse, "agent_resource": agent_resource,
            "gse_resource": gse_resource, "released": released,
            "turn_after_create": turn_after_create,
            "minutes": (minutes_before, minutes_mid, minutes_after)}


def test_equipment_minutes_return_to_their_pre_create_value_on_release(api):
    """PRD §2.7: "The system guarantees three conserved quantities: creating an
    equipment occupation of a given number of minutes and then releasing or
    cancelling it returns that unit's `committed_occupation_minutes` to the
    value it had before the create; the same holds for an agent's
    `assigned_duty_minutes` on agent occupations; and creating a billing line
    and then voiding it returns the owning period's `accrued_cents` and
    `line_count` to their pre-create values."
    PRD §2.7: "Compensating movements are exact, not approximate."

    Design: Difficulty/compensating_invariant/gse_occupation_minutes_conserved_across_create_and_release
    """
    scenario = _create_then_release_equipment_occupation()
    before, mid, after = scenario["minutes"]
    assert before == 0
    assert scenario["gse_resource"]["occupied_minutes"] == 45
    assert mid == 45
    assert scenario["released"]["status"] == "RELEASED"
    assert after == 0
    assert_no_ledger_drift(before, after, "committed_occupation_minutes")


def test_releasing_the_equipment_demotes_the_turn_and_its_staffing_plan(api):
    """PRD §3.7: "The owning turnaround then recomputes its coverage counters
    and may demote `RESOURCED → SCHEDULED`, which in turn drops an `APPROVED`
    bank staffing plan to `REVISION_REQUIRED`."
    PRD §3.4: "Each equipment occupation released this way adds 1 to its unit's
    `cycles_since_service`, and any unit whose `cycles_since_service` has
    thereby reached or passed its `service_interval_cycles` moves `AVAILABLE →
    IN_MAINTENANCE` and receives a four-hour service hold running from the
    current logical clock."

    Design: Difficulty/compensating_invariant/gse_occupation_minutes_conserved_across_create_and_release
    """
    scenario = _create_then_release_equipment_occupation()
    assert scenario["turn_after_create"]["status"] == "RESOURCED"

    turn = get_turn(scenario["turn"]["id"])
    assert turn["status"] == "SCHEDULED"
    assert turn["assigned_gse_count"] == 0
    assert get_flight_bank(scenario["bank"]["id"])["staffing_status"] == \
        "REVISION_REQUIRED"

    assert get_agent(scenario["agent"]["id"])["assigned_duty_minutes"] == 40, (
        "the agent ledger is untouched by an equipment release")
    assert get_turn_resource(scenario["agent_resource"]["id"])["status"] == \
        "RESERVED"
    assert get_gse_unit(scenario["gse"]["id"])["cycles_since_service"] == 0, (
        "only a turn completion advances the service cycle counter")


# ---------------------------------------------------------------------------
# Queue A: compensating_invariant / billing_accrual_cents_conserved_across_create_and_void
# ---------------------------------------------------------------------------

def _accrue_then_void_a_line():
    """An OPEN period takes one 18000-cent line for a SCHEDULED turn and then
    voids it."""
    station = create_open_station()
    bank = create_flight_bank(station["id"], planned_headcount=1)
    turn = create_turn(station["id"], bank["id"])
    period = create_billing_period(station["id"], period_code="2026-04")
    before = get_billing_period(period["id"])

    line = add_billing_line(period["id"], turn["id"])
    mid = get_billing_period(period["id"])
    voided = void_billing_line(line["id"], reason="ACCRUED_TO_WRONG_PERIOD")
    after = get_billing_period(period["id"])
    return {"station": station, "turn": turn, "period": period, "line": line,
            "voided": voided, "before": before, "mid": mid, "after": after}


def test_accrued_cents_return_to_zero_when_the_line_is_voided(api):
    """PRD §2.7: "The system guarantees three conserved quantities: creating an
    equipment occupation of a given number of minutes and then releasing or
    cancelling it returns that unit's `committed_occupation_minutes` to the
    value it had before the create; the same holds for an agent's
    `assigned_duty_minutes` on agent occupations; and creating a billing line
    and then voiding it returns the owning period's `accrued_cents` and
    `line_count` to their pre-create values."
    PRD §3.9: "Voiding is the compensating action: a `BillingController` voids
    a line with a mandatory `reason`, which is stored as the line's
    `void_reason` and moves the line to `VOID`."

    Design: Difficulty/compensating_invariant/billing_accrual_cents_conserved_across_create_and_void
    """
    scenario = _accrue_then_void_a_line()
    assert scenario["before"]["accrued_cents"] == 0
    assert scenario["before"]["line_count"] == 0
    assert scenario["line"]["gross_amount_cents"] == 18000
    assert scenario["line"]["net_amount_cents"] == 18000
    assert scenario["mid"]["accrued_cents"] == 18000
    assert scenario["mid"]["gross_total_cents"] == 18000
    assert scenario["mid"]["line_count"] == 1
    assert scenario["voided"]["status"] == "VOID"
    assert scenario["after"]["accrued_cents"] == 0
    assert_no_ledger_drift(scenario["before"]["accrued_cents"],
                           scenario["after"]["accrued_cents"], "accrued_cents")


def test_voiding_restores_line_count_totals_and_the_turn_billed_flag(api):
    """PRD §3.9: "The period recomputes `line_count`, `gross_total_cents`,
    `accrued_cents`, `rebate_tier`, `rebate_cents` and `net_total_cents`
    without that line, and the turnaround's `billed` flag returns to false."
    PRD §3.9: "Void lines are excluded from every subsequent computation,
    including the rebate basis."

    Design: Difficulty/compensating_invariant/billing_accrual_cents_conserved_across_create_and_void
    """
    scenario = _accrue_then_void_a_line()
    after = scenario["after"]
    assert after["line_count"] == 0
    assert after["gross_total_cents"] == 0
    assert after["rebate_tier"] == "NONE"
    assert after["net_total_cents"] == 0
    assert_period_ledger_identity(after)

    line = get_billing_line(scenario["line"]["id"])
    assert line["void_reason"] == "ACCRUED_TO_WRONG_PERIOD"
    assert get_turn(scenario["turn"]["id"])["billed"] is False


# ---------------------------------------------------------------------------
# Queue B: consistency_model /
#          cascade_and_derived_fields_are_visible_immediately_after_the_request
# ---------------------------------------------------------------------------

def test_derived_values_are_visible_on_the_first_read_after_the_write(api):
    """PRD §2.7: "The cascades are applied immediately, inside the request that
    triggered them — there is no deferred reconciliation."
    PRD §3.7: "The turnaround then recomputes `assigned_agent_count` and
    `assigned_gse_count`, which count that turnaround's occupations by family
    among rows at `RESERVED` or `COMMITTED`, and a fully covered `SCHEDULED`
    turnaround promotes to `RESOURCED`."

    Design: Corner/consistency_model/cascade_and_derived_fields_are_visible_immediately_after_the_request
    """
    station = create_open_station()
    bank = create_flight_bank(station["id"], planned_headcount=1)
    turn = create_turn(station["id"], bank["id"])
    agent = create_certified_agent(station["id"])
    gse = create_gse_unit(station["id"])
    publish_and_approve_staffing(bank["id"])
    add_agent_occupation(turn["id"], agent["id"])
    assert get_turn(turn["id"])["status"] == "SCHEDULED"

    occupation = add_gse_occupation(turn["id"], gse_unit_id=gse["id"])
    assert occupation["occupied_minutes"] == 30, (
        "the creating response already carries the derived minute count")
    assert occupation["status"] == "RESERVED"

    turn = get_turn(turn["id"])
    assert turn["status"] == "RESOURCED"
    assert turn["assigned_gse_count"] == 1
    assert get_gse_unit(gse["id"])["committed_occupation_minutes"] == 30

    bank = get_flight_bank(bank["id"])
    assert_pct(bank["staffing_coverage_pct"], 100.00, "staffing_coverage_pct")
    assert bank["staffing_status"] == "APPROVED"


# ---------------------------------------------------------------------------
# Queue B: calculations / cancelled_agent_occupation_does_not_dilute_subcontract_factor
# ---------------------------------------------------------------------------

def test_a_cancelled_subcontracted_occupation_does_not_dilute_the_charge(api):
    """PRD §3.9: "The subcontract-dilution factor is 0.965 when at least one
    occupation on the charged turnaround has `resource_kind` `AGENT`, has
    `status` `RESERVED`, `COMMITTED` or `RELEASED`, and names an agent whose
    `employment_type` is `SUBCONTRACTED`; otherwise it is 1.00."
    PRD §3.9: "Cancelled occupations are ignored by that test, so a
    subcontracted agent whose assignment was cancelled does not dilute the
    charge."

    Design: Corner/calculations/cancelled_agent_occupation_does_not_dilute_subcontract_factor
    """
    station = create_open_station()
    firm = create_approved_subcontractor(station["id"],
                                         legal_name="Alpine Ramp AG")
    bank = create_flight_bank(station["id"], planned_headcount=1)
    turn = create_turn(station["id"], bank["id"])
    agent = create_certified_agent(station["id"], employee_code="E010",
                                   full_name="Cleo Marin",
                                   subcontractor_id=firm["id"])
    occupation = add_agent_occupation(turn["id"], agent["id"])
    decide_oversight(firm["id"], "SUSPEND")
    decide_oversight(firm["id"], "TERMINATE")

    occupation = get_turn_resource(occupation["id"])
    assert occupation["status"] == "CANCELLED"
    assert occupation["cancel_reason"] == "SUBCONTRACTOR_TERMINATED"

    period = create_billing_period(station["id"], period_code="2026-04")
    line = add_billing_line(period["id"], turn["id"])
    assert line["gross_amount_cents"] == 18000, (
        "the undiluted base rate, not the 17370 a 0.965 factor would give")
    assert line["gross_amount_cents"] != 17370
    assert line["net_amount_cents"] == 18000
    assert line["charged_ground_minutes"] == 20
    assert line["excess_minutes"] == 0
    assert line["ground_time_tier"] == "TIER_1"
    assert get_agent(agent["id"])["status"] == "TERMINATED"


# ---------------------------------------------------------------------------
# Queue B: calculations / provisional_line_uses_scheduled_ground_time_even_after_completion
# ---------------------------------------------------------------------------

def test_a_line_accrued_after_completion_is_still_priced_provisionally(api):
    """PRD §3.9: "Which ground time enters the charge depends on the line's own
    `status`, and this is the pivot the whole billing model turns on."
    PRD §3.9: "While the line is `PROVISIONAL`, `charged_ground_minutes` is the
    turnaround's `scheduled_ground_minutes`."
    PRD §3.9: "On success the line lands at `PROVISIONAL`, copies the
    turnaround's `turn_type` into its own `turn_type_snapshot` — every rate
    lookup thereafter reads the snapshot, never the live turnaround — sets the
    turnaround's `billed` flag to true, and increments the period's `version`
    by 1."

    Design: Corner/calculations/provisional_line_uses_scheduled_ground_time_even_after_completion
    """
    station = create_open_station(otp_tolerance_minutes=15)
    bank = create_flight_bank(station["id"], planned_headcount=1)
    turn = create_turn(station["id"], bank["id"])
    agent = create_certified_agent(station["id"])
    gse = create_gse_unit(station["id"])
    publish_and_approve_staffing(bank["id"])
    add_agent_occupation(turn["id"], agent["id"],
                         window_start="2026-04-10T05:50:00Z",
                         window_end="2026-04-10T06:45:00Z")
    add_gse_occupation(turn["id"], gse_unit_id=gse["id"],
                       window_start="2026-04-10T05:55:00Z",
                       window_end="2026-04-10T06:45:00Z")
    start_turn(turn["id"], actual_in="2026-04-10T06:00:00Z")
    completed = complete_turn(turn["id"], actual_out="2026-04-10T06:38:00Z",
                              delay_code="GH_EQUIPMENT")
    assert completed["actual_ground_minutes"] == 38
    assert completed["otp_result"] == "DELAYED"

    period = create_billing_period(station["id"], period_code="2026-04")
    line = add_billing_line(period["id"], turn["id"])
    assert line["status"] == "PROVISIONAL"
    assert line["charged_ground_minutes"] == 20
    assert line["gross_amount_cents"] == 18000
    assert line["otp_penalty_cents"] == 0
    assert line["net_amount_cents"] == 18000
    assert line["turn_type_snapshot"] == "TOWING_ONLY"
    assert get_turn(turn["id"])["billed"] is True


# ---------------------------------------------------------------------------
# Queue B: calculations / damage_penalty_applies_station_multiplier_to_severity_table
# ---------------------------------------------------------------------------

def test_damage_penalty_scales_the_severity_table_by_the_station_multiplier(api):
    """PRD §3.9: "Its `damage_penalty_cents` is the sum, over every incident
    whose `turn_id` is that turnaround, whose `status` is `CLOSED`, whose
    `liability_party` is `HANDLER` and whose `incident_type` is
    `AIRCRAFT_DAMAGE` or `GSE_DAMAGE`, of the severity's damage figure — 25000
    cents for `MINOR`, 250000 cents for `MAJOR`, 900000 cents for `CRITICAL` —
    multiplied by the station's `damage_penalty_multiplier` and rounded half up
    to a whole cent for each contributing incident before the incidents are
    added together."
    PRD §3.1: "`damage_penalty_multiplier` scales the severity-based damage
    penalty table for this station, defaults to 1.00, is carried to two decimal
    places, and must be strictly greater than zero."

    Design: Corner/calculations/damage_penalty_applies_station_multiplier_to_severity_table
    """
    station = create_open_station(clock="2026-04-10T08:00:00Z",
                                  otp_tolerance_minutes=15,
                                  penalty_cap_cents=5000000,
                                  damage_penalty_multiplier=2.00)
    bank = create_flight_bank(station["id"], planned_headcount=1)
    turn = create_turn(station["id"], bank["id"])
    agent = create_certified_agent(station["id"])
    gse = create_gse_unit(station["id"])
    publish_and_approve_staffing(bank["id"])
    add_agent_occupation(turn["id"], agent["id"],
                         window_start="2026-04-10T05:50:00Z",
                         window_end="2026-04-10T07:15:00Z")
    add_gse_occupation(turn["id"], gse_unit_id=gse["id"],
                       window_start="2026-04-10T05:55:00Z",
                       window_end="2026-04-10T07:10:00Z")
    start_turn(turn["id"], actual_in="2026-04-10T06:00:00Z")
    complete_turn(turn["id"], actual_out="2026-04-10T07:05:00Z",
                  delay_code="WEATHER")

    incident = report_incident(
        station["id"], user_id="duty-01", incident_type="AIRCRAFT_DAMAGE",
        severity="MINOR", occurred_at="2026-04-10T06:40:00Z",
        turn_id=turn["id"], description="Scuff to belly fairing")
    close_out_incident(incident["id"], liability_party="HANDLER",
                       root_cause_code="TUG_MISALIGNMENT",
                       assessed_damage_cents=480000)
    incident = get_incident(incident["id"])
    assert incident["status"] == "CLOSED"
    assert incident["assessed_damage_cents"] == 480000

    period = create_billing_period(station["id"], period_code="2026-04")
    line = add_billing_line(period["id"], turn["id"])
    finalized = finalize_period(period["id"], user_id="bc-01")

    line = get_billing_line(line["id"])
    assert line["gross_amount_cents"] == 54000
    assert line["damage_penalty_cents"] == 50000, (
        "25000 for MINOR scaled by the station's 2.00 multiplier")
    assert line["otp_penalty_cents"] == 0
    assert line["net_amount_cents"] == 4000
    assert finalized["damage_penalty_cents"] == 50000
    assert finalized["otp_penalty_cents"] == 0
    assert finalized["accrued_cents"] == 4000
    assert get_billing_period(period["id"])["net_total_cents"] == 4000


# ---------------------------------------------------------------------------
# Queue B: calculations / excluded_delay_code_keeps_turn_out_of_otp_denominator
# ---------------------------------------------------------------------------

def test_an_excluded_turn_enters_neither_side_of_the_otp_ratio(api):
    """PRD §3.4: "The station's `completed_turn_count` then counts its
    turnarounds whose `status` is `COMPLETED` and whose `otp_result` is
    `ON_TIME` or `DELAYED`; its `on_time_turn_count` counts those whose
    `status` is `COMPLETED` and whose `otp_result` is `ON_TIME`."
    PRD §3.4: "`EXCLUDED` and `PENDING` turnarounds appear in neither the
    numerator nor the denominator."

    Design: Corner/calculations/excluded_delay_code_keeps_turn_out_of_otp_denominator
    """
    station = create_open_station(otp_tolerance_minutes=15)
    assert_pct(get_station(station["id"])["otp_rolling_pct"], 100.00,
               "otp_rolling_pct")
    bank = create_flight_bank(station["id"], planned_headcount=1)
    turn = create_turn(station["id"], bank["id"])
    agent = create_certified_agent(station["id"])
    gse = create_gse_unit(station["id"])
    publish_and_approve_staffing(bank["id"])
    add_agent_occupation(turn["id"], agent["id"],
                         window_start="2026-04-10T05:50:00Z",
                         window_end="2026-04-10T07:10:00Z")
    add_gse_occupation(turn["id"], gse_unit_id=gse["id"],
                       window_start="2026-04-10T05:55:00Z",
                       window_end="2026-04-10T07:05:00Z")
    start_turn(turn["id"], actual_in="2026-04-10T06:00:00Z")

    completed = complete_turn(turn["id"], actual_out="2026-04-10T07:00:00Z",
                              delay_code="ATC")
    assert completed["delay_minutes"] == 40
    assert completed["otp_result"] == "EXCLUDED"

    station = get_station(station["id"])
    assert station["completed_turn_count"] == 0
    assert station["on_time_turn_count"] == 0
    assert_pct(station["otp_rolling_pct"], 100.00, "otp_rolling_pct")
    assert station["oversight_posture"] == "NORMAL"
    assert get_turn(turn["id"])["status"] == "COMPLETED"


# ---------------------------------------------------------------------------
# Queue B: state_machines / billing_period_reject_reverts_lines_to_provisional_variant
# ---------------------------------------------------------------------------

def test_rejecting_a_finalized_period_reverts_every_line_to_provisional(api):
    """PRD §3.9: "Rejecting with `REJECT` moves it `PENDING_APPROVAL → OPEN`
    and is a full compensating recomputation rather than a mere status change:
    every `FINAL` line returns to `PROVISIONAL` and is recomputed under the
    provisional variant, so each line's `otp_penalty_cents`,
    `damage_penalty_cents` and `rebate_alloc_cents` all return to 0 and each
    line's `charged_ground_minutes` reverts to the turnaround's scheduled
    figure."
    PRD §3.9: "The period's `gross_total_cents`, `otp_penalty_cents`,
    `damage_penalty_cents`, `rebate_tier`, `rebate_cents`, `accrued_cents` and
    `net_total_cents` are recomputed from the reverted lines,
    `finalized_by_user_id` is cleared back to null, and `reject_count` is
    increased by 1."

    Design: Corner/state_machines/billing_period_reject_reverts_lines_to_provisional_variant
    """
    station = create_open_station(otp_tolerance_minutes=15,
                                  penalty_cap_cents=5000000)
    bank = create_flight_bank(station["id"], planned_headcount=1)
    turn = create_turn(station["id"], bank["id"])
    agent = create_certified_agent(station["id"])
    gse = create_gse_unit(station["id"])
    publish_and_approve_staffing(bank["id"])
    add_agent_occupation(turn["id"], agent["id"])
    add_gse_occupation(turn["id"], gse_unit_id=gse["id"])
    start_turn(turn["id"], actual_in="2026-04-10T06:00:00Z")
    complete_turn(turn["id"], actual_out="2026-04-10T06:38:00Z",
                  delay_code="GH_EQUIPMENT")
    period = create_billing_period(station["id"], period_code="2026-04")
    line = add_billing_line(period["id"], turn["id"])
    pending = finalize_period(period["id"], user_id="bc-01")
    assert pending["status"] == "PENDING_APPROVAL"
    assert pending["accrued_cents"] == 31416
    assert pending["finalized_by_user_id"] == "bc-01"

    reopened = reject_period(period["id"], user_id="ca-01",
                             note="Delay code disputed by carrier")
    assert reopened["status"] == "OPEN"
    assert reopened["accrued_cents"] == 18000
    assert reopened["reject_count"] == 1
    assert reopened["finalized_by_user_id"] is None

    line = get_billing_line(line["id"])
    assert line["status"] == "PROVISIONAL"
    assert line["gross_amount_cents"] == 18000
    assert line["charged_ground_minutes"] == 20
    assert line["otp_penalty_cents"] == 0
    assert line["rebate_alloc_cents"] == 0
    assert line["net_amount_cents"] == 18000

    period = get_billing_period(period["id"])
    assert period["rebate_tier"] == "NONE"
    assert period["net_total_cents"] == 18000
    assert_period_ledger_identity(period)
