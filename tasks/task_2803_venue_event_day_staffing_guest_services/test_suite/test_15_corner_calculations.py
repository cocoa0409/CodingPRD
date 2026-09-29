"""Calculation breadth: tier floors, costing input sets, allocation remainders and clocks."""

from test_helpers import (
    COORDINATOR_HEADERS,
    DIRECTOR_HEADERS,
    ERR_ACCESSIBILITY_CAPACITY_EXCEEDED,
    ERR_HISTORICAL_ATTENDANCE_MISSING,
    ERR_PAYOUT_PHASE_INVALID,
    SUPERVISOR_HEADERS,
    activate_plan,
    advance_event,
    assert_absent,
    assert_average,
    assert_cents,
    assert_common_fields,
    assert_fields,
    assert_instant,
    assert_payout_totals,
    assert_slot_fill,
    attendance,
    assign_issue,
    create_assignment,
    create_certification,
    create_elevator_operator,
    create_event,
    create_guest_services_rep,
    create_issue,
    create_member,
    create_plan,
    create_resource,
    create_booking,
    create_satisfaction_response,
    create_slot,
    create_ticket_taker,
    create_usher,
    err,
    event_version,
    ok,
    page,
    patch_event,
    read_assignment,
    read_event,
    read_issue,
    read_member,
    read_plan,
    read_resource,
    read_slot,
    resolve_issue,
    run_payout,
    set_clock,
    transition_booking,
)
from test_helpers.factories import staffing_plan_payload

USHER = {
    "base_hourly_rate_cents": 2200,
    "attendance_ratio_per_1000": 1.5,
    "min_headcount": 4,
    "required_certifications": [],
}
TICKET_TAKER = {
    "base_hourly_rate_cents": 2000,
    "attendance_ratio_per_1000": 0.8,
    "min_headcount": 3,
    "required_certifications": [],
}


def _plan_aggregates(plan, *, headcount, base, surcharge, projected, label):
    assert_fields(plan, total_required_headcount=headcount)
    assert_cents(plan["base_labor_cost_cents"], base, f"{label} base_labor_cost_cents")
    assert_cents(
        plan["accessibility_surcharge_cents"], surcharge, f"{label} accessibility_surcharge_cents"
    )
    assert_cents(
        plan["projected_labor_cost_cents"], projected, f"{label} projected_labor_cost_cents"
    )


def _day_event(client, name, expected_attendance, **overrides):
    payload = {
        "name": name,
        "event_date": "2026-09-20T00:00:00Z",
        "doors_open_at": "2026-09-20T13:00:00Z",
        "doors_close_at": "2026-09-20T21:00:00Z",
        "expected_attendance": expected_attendance,
    }
    payload.update(overrides)
    return create_event(client, **payload)


def _worker(client, full_name, seniority_date, hourly_rate_cents, employment_type="CONTRACTED"):
    return create_member(
        client,
        full_name=full_name,
        employment_type=employment_type,
        seniority_date=seniority_date,
        hourly_rate_cents=hourly_rate_cents,
    )


def test_one_guest_across_the_top_tier_floor_moves_every_number_downstream(client):
    """39999 and 40000 differ by a guest and by twelve heads, 158400 cents and a tier.

    "Tiering is a floor comparison, inclusive at each floor: a forecast of 40000 or more
    is `TIER_4` and carries a staffing multiplier of 1.45; a forecast of at least 25000
    but below 40000 is `TIER_3` at 1.25; at least 12000 but below 25000 is `TIER_2` at
    1.10; anything lower is `TIER_1` at 1.00."

    "The order of quantize-then-ceiling matters: 46.87504 quantizes to 46.8750 and rises
    to 47, and 47.00004 quantizes to 47.0000 and stays at 47 rather than rising to 48."

    Design: Corner/calculations/attendance_tier_boundary_at_39999_and_40000
    """
    set_clock(client, "2026-09-01T09:00:00Z")
    usher = create_usher(client, **USHER)
    low = _day_event(client, "Tier Boundary Low", 39999)
    high = _day_event(client, "Tier Boundary High", 40000)
    assert_fields(low, attendance_tier="TIER_3")
    assert_fields(high, attendance_tier="TIER_4")

    plan_low = create_plan(client, low["id"], plan_variant="FORECAST_BASED")
    plan_high = create_plan(client, high["id"], plan_variant="FORECAST_BASED")
    slot_low = create_slot(
        client,
        plan_low["id"],
        usher["id"],
        zone_code="Z100",
        shift_start="2026-09-20T14:00:00Z",
        shift_end="2026-09-20T20:00:00Z",
    )
    slot_high = create_slot(
        client,
        plan_high["id"],
        usher["id"],
        zone_code="Z100",
        shift_start="2026-09-20T14:00:00Z",
        shift_end="2026-09-20T20:00:00Z",
    )

    assert_fields(
        slot_low, ratio_derived_headcount=75, required_headcount=75, shift_minutes=360
    )
    assert_cents(slot_low["slot_labor_cost_cents"], 990000, "low slot_labor_cost_cents")
    assert_fields(
        slot_high, ratio_derived_headcount=87, required_headcount=87, shift_minutes=360
    )
    assert_cents(slot_high["slot_labor_cost_cents"], 1148400, "high slot_labor_cost_cents")

    activated_low = activate_plan(client, plan_low["id"], low["id"], 1)
    activated_high = activate_plan(client, plan_high["id"], high["id"], 1)
    assert_fields(activated_low, basis_attendance=39999, basis_attendance_tier="TIER_3")
    assert_fields(activated_high, basis_attendance=40000, basis_attendance_tier="TIER_4")
    _plan_aggregates(
        activated_low, headcount=75, base=990000, surcharge=34650, projected=1024650, label="low plan"
    )
    _plan_aggregates(
        activated_high,
        headcount=87,
        base=1148400,
        surcharge=40194,
        projected=1188594,
        label="high plan",
    )


def test_the_family_floor_overwrites_the_ratio_result_itself(client):
    """A thousand guests want two ushers, and the family floor insists on four.

    "That four-decimal figure is then raised to the next whole number, and the whole
    number is what becomes `ratio_derived_headcount`, except that it is first lifted to
    the family's `min_headcount` if the ratio result falls below that floor."

    Design: Corner/calculations/slot_min_headcount_floor_beats_the_ratio_result
    """
    set_clock(client, "2026-09-01T09:00:00Z")
    usher = create_usher(client, **USHER)
    event = _day_event(client, "Small Crowd", 1000)
    assert_fields(event, attendance_tier="TIER_1")
    plan = create_plan(client, event["id"], plan_variant="FORECAST_BASED")

    slot = create_slot(
        client,
        plan["id"],
        usher["id"],
        zone_code="Z100",
        shift_start="2026-09-20T14:00:00Z",
        shift_end="2026-09-20T20:00:00Z",
    )

    assert_fields(slot, ratio_derived_headcount=4, required_headcount=4, shift_minutes=360)
    assert slot.get("required_headcount_override") is None, (
        "no override was supplied, so the field must not carry a value"
    )
    assert_cents(slot["slot_labor_cost_cents"], 52800, "slot_labor_cost_cents")

    activated = activate_plan(client, plan["id"], event["id"], 1)
    _plan_aggregates(
        activated, headcount=4, base=52800, surcharge=0, projected=52800, label="floored plan"
    )


def test_the_plan_aggregates_drop_the_closed_blocks_the_blocks_keep_their_price(client):
    """Supersession empties the incumbent's four aggregates without erasing block prices.

    "Step two sums those already-rounded per-block figures into `base_labor_cost_cents`;
    the exact products are never summed."

    "Because closed blocks drop out of all four aggregates, superseding a plan — which
    closes every block it owns — drives all four of them to zero."

    Design: Corner/calculations/plan_cost_excludes_closed_slots_from_the_input_set
    """
    set_clock(client, "2026-09-01T09:00:00Z")
    event = _day_event(
        client,
        "Supersede Cost Fixture",
        6000,
        doors_open_at="2026-09-20T17:00:00Z",
        doors_close_at="2026-09-20T23:00:00Z",
    )
    family = create_ticket_taker(client, **TICKET_TAKER)
    plan_a = create_plan(client, event["id"], plan_variant="FORECAST_BASED")
    slot_a1 = create_slot(
        client,
        plan_a["id"],
        family["id"],
        zone_code="Z100",
        shift_start="2026-09-20T18:00:00Z",
        shift_end="2026-09-20T22:05:00Z",
        required_headcount_override=5,
    )
    slot_a2 = create_slot(
        client,
        plan_a["id"],
        family["id"],
        zone_code="Z200",
        shift_start="2026-09-20T18:00:00Z",
        shift_end="2026-09-20T22:05:00Z",
        required_headcount_override=2,
    )
    assert_cents(slot_a1["slot_labor_cost_cents"], 40833, "slot A1 cost")
    assert_cents(slot_a2["slot_labor_cost_cents"], 16333, "slot A2 cost")

    active_a = activate_plan(client, plan_a["id"], event["id"], 1)
    _plan_aggregates(
        active_a, headcount=7, base=57166, surcharge=0, projected=57166, label="plan A"
    )

    plan_b = create_plan(client, event["id"], plan_variant="FORECAST_BASED")
    create_slot(
        client,
        plan_b["id"],
        family["id"],
        zone_code="Z100",
        shift_start="2026-09-20T18:00:00Z",
        shift_end="2026-09-20T22:05:00Z",
        required_headcount_override=1,
    )

    active_b = activate_plan(client, plan_b["id"], event["id"], event_version(client, event["id"]))

    assert_fields(read_plan(client, plan_a["id"]), status="SUPERSEDED")
    assert_fields(read_slot(client, slot_a1["id"]), status="CLOSED")
    assert_fields(read_slot(client, slot_a2["id"]), status="CLOSED")
    _plan_aggregates(
        read_plan(client, plan_a["id"]),
        headcount=0,
        base=0,
        surcharge=0,
        projected=0,
        label="superseded plan A",
    )
    assert_cents(
        read_slot(client, slot_a1["id"])["slot_labor_cost_cents"],
        40833,
        "closed block keeps its own price",
    )

    assert_fields(active_b, status="ACTIVE")
    _plan_aggregates(
        read_plan(client, plan_b["id"]),
        headcount=1,
        base=8167,
        surcharge=0,
        projected=8167,
        label="plan B",
    )
    assert_fields(read_event(client, event["id"]), status="PLANNED", version=3)


def _tip_pool_event(client, name, **overrides):
    payload = {
        "name": name,
        "event_date": "2026-09-12T00:00:00Z",
        "doors_open_at": "2026-09-12T17:00:00Z",
        "doors_close_at": "2026-09-12T23:30:00Z",
        "expected_attendance": 6000,
        "gratuity_pool_cents": 50000,
    }
    payload.update(overrides)
    return create_event(client, **payload)


def test_the_gratuity_remainder_falls_to_the_top_of_the_ranking(client):
    """Three equal shares of 50000 leave two cents, and seniority decides who gets them.

    "That remainder is handed out one cent at a time to the first rows **in ranking
    order** — deliberately not to the rows with the largest discarded fractions."

    "The `GRATUITY_ALLOCATION` phase distributes the event's tip pool; it demands that the
    event's `status` be `CLOSED` and that at least one gratuity-eligible assignment still
    sit at `payout_status` `ACCRUED`, failing which it is refused with
    `ERR_PAYOUT_PHASE_INVALID`."

    Design: Corner/calculations/gratuity_remainder_distributed_in_ranking_order
    """
    set_clock(client, "2026-09-12T18:00:00Z")
    event = _tip_pool_event(client, "Gratuity Remainder Fixture")
    family = create_elevator_operator(
        client,
        base_hourly_rate_cents=2400,
        attendance_ratio_per_1000=0.2,
        min_headcount=1,
        required_certifications=[],
        is_tip_eligible=True,
        is_contracted_position=True,
    )
    plan = create_plan(client, event["id"], plan_variant="FORECAST_BASED")
    slot = create_slot(
        client,
        plan["id"],
        family["id"],
        zone_code="Z100",
        shift_start="2026-09-12T18:00:00Z",
        shift_end="2026-09-12T23:05:00Z",
        required_headcount_override=3,
    )
    senior = _worker(client, "Ada Senior", "2020-01-01T00:00:00Z", 2400)
    middle = _worker(client, "Ben Middle", "2021-01-01T00:00:00Z", 2400)
    junior = _worker(client, "Cara Junior", "2022-01-01T00:00:00Z", 2400)
    activate_plan(client, plan["id"], event["id"], 1)
    rows = [
        create_assignment(client, slot["id"], member["id"])
        for member in (senior, middle, junior)
    ]
    advance_event(client, event["id"], "IN_PROGRESS")
    for row in rows:
        attendance(client, row["id"], "CHECK_IN")
    set_clock(client, "2026-09-12T23:00:00Z")
    for row in rows:
        settled = attendance(client, row["id"], "CHECK_OUT")
        assert_fields(settled, worked_minutes=300, payout_status="ACCRUED")
        assert_cents(settled["base_pay_cents"], 12000, "base_pay_cents")
    advance_event(client, event["id"], "CLOSED")

    run_payout(client, event["id"], "GRATUITY_ALLOCATION")

    senior_row = read_assignment(client, rows[0]["id"])
    middle_row = read_assignment(client, rows[1]["id"])
    junior_row = read_assignment(client, rows[2]["id"])
    assert_payout_totals(senior_row, base=12000, gratuity=16667, total=28667)
    assert_payout_totals(middle_row, base=12000, gratuity=16667, total=28667)
    assert_payout_totals(junior_row, base=12000, gratuity=16666, total=28666)
    for row in (senior_row, middle_row, junior_row):
        assert_fields(row, payout_status="GRATUITY_ALLOCATED")
    assert (
        senior_row["gratuity_cents"] + middle_row["gratuity_cents"] + junior_row["gratuity_cents"]
        == 50000
    ), "the cents allocated always add up to the pool to the cent"
    settled_event = read_event(client, event["id"])
    assert_cents(settled_event["gratuity_allocated_cents"], 50000, "gratuity_allocated_cents")
    assert_cents(settled_event["gratuity_pool_cents"], 50000, "gratuity_pool_cents")

    err(
        client.event_payout_run(
            event["id"], {"phase": "GRATUITY_ALLOCATION"}, DIRECTOR_HEADERS
        ),
        ERR_PAYOUT_PHASE_INVALID,
    )


def test_the_four_gratuity_conjuncts_each_exclude_a_row_on_their_own(client):
    """Four near-misses stand aside and one row takes the whole pool.

    "Gratuity eligibility is a conjunction of four conditions, and a row that misses any
    one of them is simply passed over rather than rejected."

    "The third and fourth conditions are separate on purpose: a part-time employee working
    a tip-eligible, contracted position is *not* eligible, keeps `gratuity_cents` at 0, and
    simply waits for the payroll phase."

    Design: Corner/calculations/gratuity_excludes_part_time_non_contracted_and_voided_rows
    """
    set_clock(client, "2026-09-12T18:00:00Z")
    event = _tip_pool_event(client, "Gratuity Filter Fixture")
    both = create_elevator_operator(
        client,
        base_hourly_rate_cents=2400,
        attendance_ratio_per_1000=0.2,
        min_headcount=1,
        required_certifications=[],
        is_tip_eligible=True,
        is_contracted_position=True,
    )
    neither = create_ticket_taker(client, **TICKET_TAKER)
    tip_only = create_guest_services_rep(
        client,
        base_hourly_rate_cents=2400,
        attendance_ratio_per_1000=0.3,
        min_headcount=1,
        required_certifications=[],
        is_tip_eligible=True,
        is_contracted_position=False,
    )
    plan = create_plan(client, event["id"], plan_variant="FORECAST_BASED")
    window = {
        "shift_start": "2026-09-12T18:00:00Z",
        "shift_end": "2026-09-12T23:05:00Z",
    }
    slot_both = create_slot(
        client, plan["id"], both["id"], zone_code="Z100", required_headcount_override=3, **window
    )
    slot_neither = create_slot(
        client, plan["id"], neither["id"], zone_code="Z200", required_headcount_override=1, **window
    )
    slot_tip_only = create_slot(
        client, plan["id"], tip_only["id"], zone_code="Z300", required_headcount_override=1, **window
    )
    eligible = _worker(client, "M1 Contracted", "2020-01-01T00:00:00Z", 2400)
    part_timer = _worker(
        client, "M2 Part Time", "2019-01-01T00:00:00Z", 2000, employment_type="PART_TIME_EMPLOYEE"
    )
    on_untipped_family = _worker(client, "M3 Contracted", "2018-01-01T00:00:00Z", 2000)
    on_uncontracted_family = _worker(client, "M4 Contracted", "2017-01-01T00:00:00Z", 2400)
    never_worked = _worker(client, "M5 Contracted", "2016-01-01T00:00:00Z", 2400)
    activate_plan(client, plan["id"], event["id"], 1)
    row_eligible = create_assignment(client, slot_both["id"], eligible["id"])
    row_part_time = create_assignment(client, slot_both["id"], part_timer["id"])
    row_untipped = create_assignment(client, slot_neither["id"], on_untipped_family["id"])
    row_uncontracted = create_assignment(client, slot_tip_only["id"], on_uncontracted_family["id"])
    row_voided = create_assignment(client, slot_both["id"], never_worked["id"])
    advance_event(client, event["id"], "IN_PROGRESS")
    worked_rows = (row_eligible, row_part_time, row_untipped, row_uncontracted)
    for row in worked_rows:
        attendance(client, row["id"], "CHECK_IN")
    set_clock(client, "2026-09-12T22:00:00Z")
    for row in worked_rows:
        attendance(client, row["id"], "CHECK_OUT")
    advance_event(client, event["id"], "CLOSED")
    assert_fields(
        read_assignment(client, row_voided["id"]),
        attendance_status="RELEASED",
        payout_status="VOIDED",
    )

    run_payout(client, event["id"], "GRATUITY_ALLOCATION")

    assert_payout_totals(
        read_assignment(client, row_eligible["id"]), base=9600, gratuity=50000, total=59600
    )
    assert_fields(read_assignment(client, row_eligible["id"]), payout_status="GRATUITY_ALLOCATED")
    for row, base, why in (
        (row_part_time, 8000, "excluded on employment_type"),
        (row_untipped, 8000, "excluded on is_tip_eligible"),
        (row_uncontracted, 9600, "excluded on is_contracted_position"),
    ):
        passed_over = read_assignment(client, row["id"])
        assert_fields(passed_over, payout_status="ACCRUED")
        assert_payout_totals(passed_over, base=base, gratuity=0, total=base)
        assert passed_over["gratuity_cents"] == 0, why
    voided = read_assignment(client, row_voided["id"])
    assert_cents(voided["gratuity_cents"], 0, "voided gratuity_cents")
    assert_cents(voided["total_payout_cents"], 0, "voided total_payout_cents")
    assert_cents(
        read_event(client, event["id"])["gratuity_allocated_cents"], 50000, "gratuity_allocated_cents"
    )


def test_five_no_shows_land_on_both_sides_of_the_reliability_clamp(client):
    """The rolling window sees three of them and the season figure sees all five.

    "For any set of rows the score starts at 100, subtracts 25 for each row in `NO_SHOW`,
    subtracts a further 8 for each row in `COMPLETED` whose `late_check_in` flag is set,
    adds 3 for each row in `COMPLETED`, and is then clamped into the range 0 through 100."

    "The clamp is observable: five no-shows produce a raw figure of minus 25 which is
    stored as 0."

    Design: Corner/calculations/reliability_score_clamped_at_the_floor_of_zero
    """
    set_clock(client, "2026-09-12T08:00:00Z")
    event = create_event(
        client,
        name="Reliability Clamp Fixture",
        event_date="2026-09-12T00:00:00Z",
        doors_open_at="2026-09-12T07:00:00Z",
        doors_close_at="2026-09-12T18:00:00Z",
        expected_attendance=6000,
    )
    family = create_ticket_taker(client, **TICKET_TAKER)
    plan = create_plan(client, event["id"], plan_variant="FORECAST_BASED")
    slots = [
        create_slot(
            client,
            plan["id"],
            family["id"],
            zone_code=f"Z{index}",
            shift_start=f"2026-09-12T{hour:02d}:00:00Z",
            shift_end=f"2026-09-12T{hour + 1:02d}:00:00Z",
            required_headcount_override=1,
        )
        for index, hour in enumerate((8, 10, 12, 14, 16), start=1)
    ]
    absentee = _worker(
        client, "Zoe Absent", "2020-01-01T00:00:00Z", 2000, employment_type="PART_TIME_EMPLOYEE"
    )
    activate_plan(client, plan["id"], event["id"], 1)
    rows = [create_assignment(client, slot["id"], absentee["id"]) for slot in slots]
    advance_event(client, event["id"], "IN_PROGRESS")

    for row in rows:
        attendance(client, row["id"], "NO_SHOW")

    worker = read_member(client, absentee["id"])
    assert_fields(
        worker,
        reliability_score=25,
        season_reliability_score=0,
        no_show_strikes=5,
        completed_assignment_count=0,
        status="PROBATION",
        in_backfill_pool=False,
        last_status_reason="AUTO_PROBATION_RELIABILITY",
    )
    for row in rows:
        struck = read_assignment(client, row["id"])
        assert_fields(struck, attendance_status="NO_SHOW", payout_status="VOIDED")
        assert_cents(struck["total_payout_cents"], 0, "total_payout_cents")
    for slot in slots:
        assert_slot_fill(read_slot(client, slot["id"]), filled=0, required=1, status="OPEN")
    _requests, meta = page(client.list_backfill_requests(COORDINATOR_HEADERS, {"status": "OPEN"}))
    assert meta["total_count"] == 5, "each no-show opens exactly one backfill request"


def _reported_absent(entity, *fields):
    """A figure the PRD reports as absent reads as missing or null, never as a zero."""
    for field in fields:
        assert entity.get(field) is None, (
            f"{field} must be reported as absent, got {entity.get(field)!r}"
        )


def test_two_categories_overwrite_the_severity_the_desk_typed_in(client):
    """LOST_CHILD and MEDICAL are forced critical; LOST_FOUND keeps the typed value.

    "When the `category` is `LOST_CHILD` or `MEDICAL`, or when the issue was created by an
    escalation and therefore carries an `escalated_from_issue_id`, the severity is forced to
    `CRITICAL` and whatever the client sent is discarded."

    "A `CRITICAL` issue is given 5 minutes, a `HIGH` issue 15 minutes, a `MEDIUM` issue 45
    minutes and a `LOW` issue 120 minutes, and that allowance is recorded in `sla_minutes`."

    Design: Corner/calculations/sla_minutes_forced_critical_for_lost_child_and_medical
    """
    set_clock(client, "2026-09-12T19:00:00Z")
    event = create_event(
        client,
        name="Severity Override Fixture",
        event_date="2026-09-12T00:00:00Z",
        doors_open_at="2026-09-12T17:00:00Z",
        doors_close_at="2026-09-12T23:00:00Z",
        expected_attendance=6000,
    )

    lost_child = create_issue(
        client,
        event["id"],
        channel="IN_PERSON",
        category="LOST_CHILD",
        severity="LOW",
        description="Child separated from their party at gate 4.",
    )
    medical = create_issue(
        client,
        event["id"],
        channel="IN_PERSON",
        category="MEDICAL",
        severity="LOW",
        description="Guest fainted in section 218.",
    )
    lost_found = create_issue(
        client,
        event["id"],
        channel="KIOSK",
        category="LOST_FOUND",
        severity="LOW",
        description="Phone left behind in section 118.",
    )

    for forced in (lost_child, medical):
        assert_fields(forced, severity="CRITICAL", sla_minutes=5, sla_breached=False)
        assert_instant(forced["sla_deadline"], "2026-09-12T19:05:00.000Z", "forced sla_deadline")
    assert_fields(lost_found, severity="LOW", sla_minutes=120, sla_breached=False)
    assert_instant(lost_found["sla_deadline"], "2026-09-12T21:00:00.000Z", "low sla_deadline")

    for issue in (lost_child, medical, lost_found):
        assert_instant(issue["sla_clock_started_at"], issue["created_at"], "sla clock is created_at")
        assert_instant(issue["created_at"], "2026-09-12T19:00:00.000Z", "created_at")

    _critical, meta = page(
        client.list_guest_issues(
            SUPERVISOR_HEADERS, {"event_id": event["id"], "severity": "CRITICAL"}
        )
    )
    assert meta["total_count"] == 2, "only the two forced rows are critical"


def test_the_breach_flag_is_strict_and_freezes_at_resolution(client):
    """Unbreached at the deadline instant, breached a minute later, frozen once resolved.

    "The `sla_breached` flag compares a reference instant against that deadline strictly:
    the reference is `resolved_at` once the issue has been resolved and the current logical
    clock while it is still unresolved."

    "Assignment deliberately does *not* restart the response clock: `sla_clock_started_at`
    and `sla_deadline` are left exactly as they were, and `sla_breached` is merely
    recomputed against that unchanged deadline."

    Design: Corner/calculations/sla_breach_is_strict_at_the_deadline_instant
    """
    set_clock(client, "2026-09-12T12:00:00Z")
    event = create_event(
        client,
        name="SLA Strictness Fixture",
        event_date="2026-09-12T00:00:00Z",
        doors_open_at="2026-09-12T11:00:00Z",
        doors_close_at="2026-09-12T23:00:00Z",
        expected_attendance=6000,
    )
    plan = create_plan(client, event["id"], plan_variant="FORECAST_BASED")
    activate_plan(client, plan["id"], event["id"], 1)
    advance_event(client, event["id"], "IN_PROGRESS")
    responder = _worker(
        client, "Ida Responder", "2020-01-01T00:00:00Z", 2000, employment_type="PART_TIME_EMPLOYEE"
    )
    credential = create_certification(
        client,
        responder["id"],
        "CODE_OF_CONDUCT",
        issued_on="2026-01-01T00:00:00Z",
        expires_on="2027-01-01T00:00:00Z",
    )
    assert_fields(credential, status="VALID")

    resolved_issue = create_issue(
        client,
        event["id"],
        channel="TEXT_LINE",
        category="CONDUCT_VIOLATION",
        severity="HIGH",
        description="Altercation in the aisle, report A.",
    )
    open_issue = create_issue(
        client,
        event["id"],
        channel="TEXT_LINE",
        category="CONDUCT_VIOLATION",
        severity="HIGH",
        description="Altercation in the aisle, report B.",
    )
    for issue in (resolved_issue, open_issue):
        assert_fields(issue, sla_minutes=15)
        assert_instant(issue["sla_deadline"], "2026-09-12T12:15:00.000Z", "sla_deadline")

    assigned = assign_issue(client, resolved_issue["id"], responder["id"])
    assert_fields(assigned, status="IN_PROGRESS", assigned_staff_member_id=responder["id"])
    assert_instant(
        assigned["sla_clock_started_at"], "2026-09-12T12:00:00.000Z", "clock after assignment"
    )
    assert_instant(assigned["sla_deadline"], "2026-09-12T12:15:00.000Z", "deadline after assignment")

    set_clock(client, "2026-09-12T12:10:00Z")
    resolved = resolve_issue(client, resolved_issue["id"], "EJECTION")
    assert_fields(resolved, status="RESOLVED", resolution_type="EJECTION", sla_breached=False)
    assert_instant(resolved["resolved_at"], "2026-09-12T12:10:00.000Z", "resolved_at")

    set_clock(client, "2026-09-12T12:15:00Z")
    assert_fields(read_issue(client, open_issue["id"]), sla_breached=False, status="OPEN")

    set_clock(client, "2026-09-12T12:16:00Z")
    assert_fields(read_issue(client, open_issue["id"]), sla_breached=True, status="OPEN")

    set_clock(client, "2026-09-12T13:00:00Z")
    frozen = read_issue(client, resolved_issue["id"])
    assert_fields(frozen, status="RESOLVED", sla_breached=False)
    assert_instant(frozen["resolved_at"], "2026-09-12T12:10:00.000Z", "resolved_at stays put")


def test_the_historical_variant_needs_its_turnstile_count_first(client):
    """Refused while the count is missing, and pinned to that count once it lands.

    "Under `HISTORICAL_ACTUAL`, `basis_attendance` is the event's
    `historical_actual_attendance`, and if that figure is absent the plan cannot be opened
    at all — the request is refused with `ERR_HISTORICAL_ATTENDANCE_MISSING`."

    Design: Corner/calculations/historical_variant_without_actual_attendance_rejected
    """
    set_clock(client, "2026-09-01T09:00:00Z")
    event = _day_event(client, "Variant Selection Fixture", 40000)
    _reported_absent(event, "historical_actual_attendance")
    usher = create_usher(client, **USHER)

    err(
        client.create_staffing_plan(
            staffing_plan_payload(event["id"], plan_variant="HISTORICAL_ACTUAL"), COORDINATOR_HEADERS
        ),
        ERR_HISTORICAL_ATTENDANCE_MISSING,
    )
    _plans, empty_meta = page(
        client.list_staffing_plans(COORDINATOR_HEADERS, {"event_id": event["id"]})
    )
    assert empty_meta["total_count"] == 0, "the refused filing must leave no plan behind"

    revised = patch_event(client, event["id"], historical_actual_attendance=25000)
    assert_fields(revised, attendance_tier="TIER_4", version=2, historical_actual_attendance=25000)

    historical = create_plan(client, event["id"], plan_variant="HISTORICAL_ACTUAL")
    forecast = create_plan(client, event["id"], plan_variant="FORECAST_BASED")
    assert_fields(
        historical, basis_attendance=25000, basis_attendance_tier="TIER_3", revision_number=1
    )
    assert_fields(forecast, basis_attendance=40000, basis_attendance_tier="TIER_4", revision_number=2)
    assert_fields(read_event(client, event["id"]), attendance_tier="TIER_4")

    slot = create_slot(
        client,
        historical["id"],
        usher["id"],
        zone_code="Z100",
        shift_start="2026-09-20T14:00:00Z",
        shift_end="2026-09-20T20:00:00Z",
    )
    assert_fields(slot, required_headcount=47, ratio_derived_headcount=47, shift_minutes=360)
    assert_cents(slot["slot_labor_cost_cents"], 620400, "historical slot_labor_cost_cents")


def test_peak_occupancy_is_a_slice_maximum_not_a_running_total(client):
    """Adjacent windows share no slice, a straddling one is refused, a disjoint one is free.

    "Windows are treated as half-open, so two bookings where one ends at exactly the instant
    the other begins are never concurrent and never compete for the same unit."

    "Cancellation from `CONFIRMED`, by contrast, releases capacity immediately: the pool's
    `peak_committed_units` over the affected window drops by the cancelled booking's
    `units_requested`."

    Design: Corner/calculations/peak_occupancy_adjacent_and_disjoint_windows_do_not_stack
    """
    set_clock(client, "2026-09-20T09:00:00Z")
    event = _day_event(
        client, "Peak Occupancy Fixture", 6000, doors_open_at="2026-09-20T09:30:00Z"
    )
    plan = create_plan(client, event["id"], plan_variant="FORECAST_BASED")
    activate_plan(client, plan["id"], event["id"], 1)
    pool = create_resource(
        client, event["id"], resource_type="WHEELCHAIR_ESCORT", zone_code="Z100", unit_count=3
    )
    early = create_booking(
        client,
        pool["id"],
        guest_reference="G-A",
        window_start="2026-09-20T10:00:00Z",
        window_end="2026-09-20T11:00:00Z",
        units_requested=3,
    )
    late = create_booking(
        client,
        pool["id"],
        guest_reference="G-B",
        window_start="2026-09-20T11:00:00Z",
        window_end="2026-09-20T12:00:00Z",
        units_requested=3,
    )
    straddler = create_booking(
        client,
        pool["id"],
        guest_reference="G-C",
        window_start="2026-09-20T10:30:00Z",
        window_end="2026-09-20T11:30:00Z",
        units_requested=1,
    )
    disjoint = create_booking(
        client,
        pool["id"],
        guest_reference="G-D",
        window_start="2026-09-20T15:00:00Z",
        window_end="2026-09-20T16:00:00Z",
        units_requested=2,
    )

    transition_booking(client, early["id"], "CONFIRMED")
    assert_fields(read_resource(client, pool["id"]), peak_committed_units=3)
    transition_booking(client, late["id"], "CONFIRMED")
    assert_fields(read_resource(client, pool["id"]), peak_committed_units=3)

    err(
        client.transition_accessibility_request(
            straddler["id"], {"target_status": "CONFIRMED"}, SUPERVISOR_HEADERS
        ),
        ERR_ACCESSIBILITY_CAPACITY_EXCEEDED,
    )
    refused = ok(client.get_accessibility_request(straddler["id"], SUPERVISOR_HEADERS))
    assert_fields(refused, status="REQUESTED")
    _reported_absent(refused, "confirmed_at")
    assert_fields(read_resource(client, pool["id"]), peak_committed_units=3)

    transition_booking(client, early["id"], "CANCELLED")
    transition_booking(client, late["id"], "CANCELLED")
    assert_fields(read_resource(client, pool["id"]), peak_committed_units=0)

    transition_booking(client, straddler["id"], "CONFIRMED")
    assert_fields(read_resource(client, pool["id"]), peak_committed_units=1)
    transition_booking(client, disjoint["id"], "CONFIRMED")
    assert_fields(read_resource(client, pool["id"]), peak_committed_units=2)

    _confirmed, meta = page(
        client.list_accessibility_requests(
            SUPERVISOR_HEADERS, {"resource_id": pool["id"], "status": "CONFIRMED"}
        )
    )
    assert meta["total_count"] == 2, "only the straddler and the disjoint booking are confirmed"


def test_an_unsurveyed_event_reports_absent_figures_not_zero_ones(client):
    """The empty summary is not the zero summary, and three responses fill it in.

    "When there are none, `average_score` and `promoter_share_bp` are both reported as
    absent rather than as zero, which distinguishes an unsurveyed event from a
    badly-reviewed one."

    "A `zone_breakdown` accompanies the headline figures, one entry per distinct
    `zone_code` carrying that zone's `zone_code`, its own `response_count` and its own
    `average_score`, ordered by `zone_code` ascending."

    Design: Corner/calculations/satisfaction_summary_with_zero_responses_returns_nulls
    """
    set_clock(client, "2026-09-20T22:00:00Z")
    event = _day_event(client, "Satisfaction Empty Fixture", 6000)

    empty = ok(client.get_satisfaction_summary(event["id"], DIRECTOR_HEADERS))
    assert_fields(
        empty, response_count=0, resolved_issue_count=0, sla_breached_issue_count=0
    )
    _reported_absent(empty, "average_score", "promoter_share_bp")
    assert empty["zone_breakdown"] == [], "an unsurveyed event breaks down into no zones"

    first = create_satisfaction_response(client, event["id"], "Z1", 5)
    create_satisfaction_response(client, event["id"], "Z1", 4, comment="Quick help at the elevator")
    create_satisfaction_response(client, event["id"], "Z2", 3)
    assert_common_fields(first, versioned=False)
    assert_absent(first, "updated_at", "version")

    summary = ok(client.get_satisfaction_summary(event["id"], DIRECTOR_HEADERS))
    assert_fields(summary, response_count=3, promoter_share_bp=6667)
    assert_average(summary["average_score"], 4.00, "average_score")
    breakdown = summary["zone_breakdown"]
    assert [entry["zone_code"] for entry in breakdown] == ["Z1", "Z2"], (
        "zone_breakdown is ordered by zone_code ascending"
    )
    assert_fields(breakdown[0], zone_code="Z1", response_count=2)
    assert_average(breakdown[0]["average_score"], 4.50, "Z1 average_score")
    assert_fields(breakdown[1], zone_code="Z2", response_count=1)
    assert_average(breakdown[1]["average_score"], 3.00, "Z2 average_score")

    _rows, meta = page(
        client.list_event_satisfaction_responses(
            event["id"], DIRECTOR_HEADERS, {"zone_code": "Z1"}
        )
    )
    assert meta["total_count"] == 2, "two of the three responses came from Z1"
