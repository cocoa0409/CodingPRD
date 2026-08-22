"""Booking the hearing, the independent case-file dimension and the two cost variants."""

from test_helpers import (
    DIRECTOR,
    ApiErrorId,
    add_employee,
    add_witness_employee,
    api_client,
    assert_arbitration_demand,
    assert_instant,
    call_witness,
    create_three_aaa_arbitrators,
    file_grievance,
    file_prep,
    get_success_data,
    grievance_version,
    hold_step,
    post_cost_entry,
    read_grievance,
    request_panel,
    respond_step,
    schedule_hearing,
    schedule_step,
    set_clock,
    setup_base,
    setup_selected_arbitrator_case,
    take_strike,
    validate_error,
    validate_success,
)


def test_prep_filing_advances_only_the_preparation_dimension(api, analyst_headers):
    """PRD §3.7: "An arbitration demand carries **two independent state dimensions on the
    same record**. Its procedural `status` walks the track described in §3.6 and §3.8; its
    `prep_status` walks a separate track measuring how ready the case file is."
    PRD §3.7: "The demand's `readiness_score` is derived from those two dimensions together,
    as a sum of four independent contributions: 40 points once the preparation dimension is
    `EXHIBITS_FILED`, `BRIEFS_FILED` or `PREP_READY`; a further 30 points once it is
    `BRIEFS_FILED` or `PREP_READY`; a further 20 points when at least one witness assignment
    on the demand stands at `CONFIRMED`; and a further 10 points when the procedural status
    is `HEARING_SCHEDULED`, `HEARD` or `AWARDED`."

    Design: Difficulty/non_linear_state_machine/arbitration_demand_independent_state_dimensions
    """
    ctx = setup_selected_arbitrator_case()

    after_exhibits = file_prep(ctx["demand"]["id"], "EXHIBIT_LIST", exhibit_count=12)
    assert_arbitration_demand(after_exhibits)
    assert after_exhibits["prep_status"] == "EXHIBITS_FILED"
    assert after_exhibits["status"] == "ARBITRATOR_SELECTED", "the procedural track is untouched"
    assert after_exhibits["readiness_score"] == 40
    assert after_exhibits["exhibit_count"] == 12

    after_scheduling = schedule_hearing(ctx["demand"]["id"])
    assert after_scheduling["status"] == "HEARING_SCHEDULED"
    assert after_scheduling["prep_status"] == "EXHIBITS_FILED", "the prep track is untouched"
    assert after_scheduling["readiness_score"] == 50


def test_award_is_blocked_while_the_case_file_is_short_of_briefs(api, administrator_headers):
    """PRD §3.8: "The case file must stand at `BRIEFS_FILED` or `PREP_READY`, or the request
    is rejected with `ERR_PREP_INCOMPLETE`."
    PRD §3.7: "A `BRIEF` filing moves `EXHIBITS_FILED` to `BRIEFS_FILED`, and this is the
    rung that unblocks award recording."

    Design: Difficulty/non_linear_state_machine/arbitration_demand_independent_state_dimensions
    """
    ctx = setup_selected_arbitrator_case()
    file_prep(ctx["demand"]["id"], "EXHIBIT_LIST", exhibit_count=12)
    schedule_hearing(ctx["demand"]["id"])
    set_clock("2026-10-07T00:00:00Z")

    blocked = api.create_award(
        ctx["demand"]["id"], {"outcome": "DENIED", "sustained_fraction_bps": 0},
        administrator_headers,
    )
    validate_error(blocked, ApiErrorId.ERR_PREP_INCOMPLETE.value)

    after_brief = file_prep(ctx["demand"]["id"], "BRIEF")
    assert after_brief["prep_status"] == "BRIEFS_FILED"
    assert after_brief["readiness_score"] == 80


def test_zero_remedy_award_is_implemented_on_issue_and_closes_the_case(api, administrator_headers):
    """PRD §3.8: "When `net_remedy_cents` is exactly 0 **and** `reinstatement_ordered` is
    false, there is nothing to implement: the award goes straight from `ISSUED` to
    `IMPLEMENTED` and the grievance is moved to `CLOSED` within that same request."

    Design: Difficulty/non_linear_state_machine/arbitration_demand_independent_state_dimensions
    """
    ctx = setup_selected_arbitrator_case()
    file_prep(ctx["demand"]["id"], "EXHIBIT_LIST", exhibit_count=12)
    schedule_hearing(ctx["demand"]["id"])
    set_clock("2026-10-07T00:00:00Z")
    file_prep(ctx["demand"]["id"], "BRIEF")

    award = validate_success(
        api.create_award(
            ctx["demand"]["id"], {"outcome": "DENIED", "sustained_fraction_bps": 0},
            administrator_headers,
        ),
        201,
    )

    assert award["outcome"] == "DENIED"
    assert award["gross_remedy_cents"] == 0
    assert award["net_remedy_cents"] == 0
    assert award["status"] == "IMPLEMENTED"

    demand = validate_success(
        api.get_arbitration_demand(ctx["demand"]["id"], administrator_headers), 200
    )
    assert demand["status"] == "AWARDED"
    assert read_grievance(ctx["grievance"]["id"])["status"] == "CLOSED"


def test_hearing_is_refused_while_the_selected_arbitrator_is_off_the_roster(
    api, administrator_headers
):
    """PRD §3.8: "The selected arbitrator must not derive to `INACTIVE`, or the request is
    rejected with `ERR_ARBITRATOR_INACTIVE`."
    PRD §3.1: "The system maintains `active_case_count` itself, starting at 0 and counting
    the arbitration demands currently engaging that arbitrator, and derives `status` from the
    other three: `INACTIVE` whenever `is_active` is false; otherwise `FULL` once
    `active_case_count` has reached `max_concurrent_cases`; otherwise `AVAILABLE`."

    Design: Difficulty/cross_entity_state_dependency/hearing_blocked_by_inactive_arbitrator
    """
    ctx = setup_selected_arbitrator_case()

    off_roster = validate_success(
        api.update_arbitrator(ctx["chan"]["id"], {"is_active": False}, administrator_headers), 200
    )
    assert off_roster["status"] == "INACTIVE"
    assert off_roster["active_case_count"] == 1

    refused = api.schedule_hearing(
        ctx["demand"]["id"],
        {"hearing_start_at": "2026-10-05T09:00:00Z", "hearing_end_at": "2026-10-06T17:00:00Z"},
        administrator_headers,
    )
    validate_error(refused, ApiErrorId.ERR_ARBITRATOR_INACTIVE.value)

    demand = validate_success(
        api.get_arbitration_demand(ctx["demand"]["id"], administrator_headers), 200
    )
    assert demand["status"] == "ARBITRATOR_SELECTED"
    assert demand["hearing_start_at"] is None


def test_restoring_the_arbitrator_lets_the_identical_hearing_through(api, administrator_headers):
    """PRD §3.1: "Roster maintenance by the administrator can take an arbitrator off the
    roster or put them back, move `earliest_available_at`, adjust `max_concurrent_cases` or
    revise `per_diem_cents`, and re-derives `status` immediately — but it never disturbs a
    hearing that is already booked."
    PRD §3.8: "A successful booking moves the demand to `HEARING_SCHEDULED`, stores both
    instants, sets `brief_due_at` to thirty days after `hearing_end_at`, marks a
    not-yet-started case file `PREP_DEFICIENT` if the runway is under twenty-one days as
    described in §3.7, and writes `estimated_cost_cents` from the **forward-looking** cost
    variant."

    Design: Difficulty/cross_entity_state_dependency/hearing_blocked_by_inactive_arbitrator
    """
    ctx = setup_selected_arbitrator_case()
    validate_success(
        api.update_arbitrator(ctx["chan"]["id"], {"is_active": False}, administrator_headers), 200
    )
    validate_error(
        api.schedule_hearing(
            ctx["demand"]["id"],
            {"hearing_start_at": "2026-10-05T09:00:00Z", "hearing_end_at": "2026-10-06T17:00:00Z"},
            administrator_headers,
        ),
        ApiErrorId.ERR_ARBITRATOR_INACTIVE.value,
    )

    back_on = validate_success(
        api.update_arbitrator(ctx["chan"]["id"], {"is_active": True}, administrator_headers), 200
    )
    assert back_on["status"] == "AVAILABLE"

    booked = validate_success(
        api.schedule_hearing(
            ctx["demand"]["id"],
            {"hearing_start_at": "2026-10-05T09:00:00Z", "hearing_end_at": "2026-10-06T17:00:00Z"},
            administrator_headers,
        ),
        200,
    )
    assert booked["status"] == "HEARING_SCHEDULED"
    assert_instant(booked["hearing_start_at"], "2026-10-05T09:00:00Z", "hearing_start_at")
    assert_instant(booked["brief_due_at"], "2026-11-05T17:00:00Z", "brief_due_at")
    assert booked["estimated_cost_cents"] == 840_000, (
        "two hearing days plus a study day at 200000, plus 120000 per hearing day, no witnesses"
    )


def _two_demands_sharing_one_arbitrator():
    """Two grievances driven through the ladder in lockstep, both selecting Ben Chan."""
    ctx = setup_base()
    second_grievant = add_employee(
        ctx, "second_grievant",
        full_name="Lena Park",
        employee_number="EMP-3",
        hire_date="2017-04-03T00:00:00Z",
        seniority_date="2017-04-03T00:00:00Z",
        hourly_rate_cents=6_000,
        classification="MAINTENANCE",
        supervisor_id=ctx["supervisor"]["id"],
    )
    alvarez, chan, dowd = create_three_aaa_arbitrators()
    ctx["alvarez"], ctx["chan"], ctx["dowd"] = alvarez, chan, dowd

    first = file_grievance(ctx, statement="Discharge of Ortiz")
    second = file_grievance(
        ctx, grievant_id=second_grievant["id"], statement="Discharge of Park"
    )

    schedule = (
        ("2026-08-05T00:00:00Z", "Appealed to step 2"),
        ("2026-08-10T00:00:00Z", "Appealed to step 3"),
        ("2026-08-14T00:00:00Z", None),
    )
    for meeting_at, appeal_statement in schedule:
        steps = [schedule_step(first["id"], meeting_at), schedule_step(second["id"], meeting_at)]
        set_clock(meeting_at)
        for step in steps:
            hold_step(step["id"])
            respond_step(step["id"], "DENIED", response_summary="Upheld")
        if appeal_statement:
            for grievance in (first, second):
                get_success_data(
                    api_client.appeal_grievance(
                        grievance["id"],
                        {"appeal_statement": appeal_statement},
                        ctx["steward_headers"],
                    )
                )

    demands = []
    for grievance in (first, second):
        demands.append(
            get_success_data(
                api_client.create_arbitration_demand(
                    grievance["id"],
                    {
                        "panel_source": "AAA",
                        "panel_size": 3,
                        "expected_grievance_version": grievance_version(grievance["id"]),
                    },
                    ctx["steward_headers"],
                )
            )
        )
    ctx["first"], ctx["second"] = first, second
    ctx["demand_one"], ctx["demand_two"] = demands
    return ctx


def test_buffered_hearing_windows_treat_a_touching_endpoint_as_a_conflict(
    api, administrator_headers
):
    """PRD §3.8: "Then the **buffered calendar-conflict test** runs, and it is deliberately
    conservative in the arbitrator's favour: every hearing that arbitrator already has booked
    is expanded by their `travel_buffer_hours` on **both** sides, and the request is rejected
    with `ERR_ARBITRATOR_UNAVAILABLE` when that expanded interval intersects the requested
    window at any point, endpoints included. These are closed intervals, so a requested
    hearing that begins at the exact instant an expanded existing hearing ends is a
    conflict."

    Design: Difficulty/resource_temporal_overlap/arbitrator_buffered_closed_interval_conflict
    """
    ctx = _two_demands_sharing_one_arbitrator()
    for demand, first_strike, second_strike in (
        (ctx["demand_one"], ctx["alvarez"], ctx["dowd"]),
        (ctx["demand_two"], ctx["dowd"], ctx["alvarez"]),
    ):
        request_panel(demand["id"])
        take_strike(demand["id"], first_strike["id"], ctx["steward_headers"])
        take_strike(demand["id"], second_strike["id"], DIRECTOR)

    booked = schedule_hearing(ctx["demand_one"]["id"])
    assert booked["selected_arbitrator_id"] == ctx["chan"]["id"]

    engaged = validate_success(api.get_arbitrator(ctx["chan"]["id"], administrator_headers), 200)
    assert engaged["active_case_count"] == 2
    assert engaged["status"] == "AVAILABLE", "the ceiling of three is not reached yet"

    touching = api.schedule_hearing(
        ctx["demand_two"]["id"],
        {"hearing_start_at": "2026-10-07T17:00:00Z", "hearing_end_at": "2026-10-08T17:00:00Z"},
        administrator_headers,
    )
    validate_error(touching, ApiErrorId.ERR_ARBITRATOR_UNAVAILABLE.value)

    unchanged = validate_success(
        api.get_arbitration_demand(ctx["demand_two"]["id"], administrator_headers), 200
    )
    assert unchanged["status"] == "ARBITRATOR_SELECTED"


def test_a_window_one_hour_clear_of_the_buffer_is_accepted(api, administrator_headers):
    """PRD §3.8: "The existing hearings that count are those on other demands sharing the
    same `selected_arbitrator_id` whose status is `HEARING_SCHEDULED`, `HEARD` or `AWARDED`."
    PRD §3.8: "A successful booking moves the demand to `HEARING_SCHEDULED`, stores both
    instants, sets `brief_due_at` to thirty days after `hearing_end_at`, marks a
    not-yet-started case file `PREP_DEFICIENT` if the runway is under twenty-one days as
    described in §3.7, and writes `estimated_cost_cents` from the **forward-looking** cost
    variant."

    Design: Difficulty/resource_temporal_overlap/arbitrator_buffered_closed_interval_conflict
    """
    ctx = _two_demands_sharing_one_arbitrator()
    for demand, first_strike, second_strike in (
        (ctx["demand_one"], ctx["alvarez"], ctx["dowd"]),
        (ctx["demand_two"], ctx["dowd"], ctx["alvarez"]),
    ):
        request_panel(demand["id"])
        take_strike(demand["id"], first_strike["id"], ctx["steward_headers"])
        take_strike(demand["id"], second_strike["id"], DIRECTOR)
    schedule_hearing(ctx["demand_one"]["id"])

    validate_error(
        api.schedule_hearing(
            ctx["demand_two"]["id"],
            {"hearing_start_at": "2026-10-07T17:00:00Z", "hearing_end_at": "2026-10-08T17:00:00Z"},
            administrator_headers,
        ),
        ApiErrorId.ERR_ARBITRATOR_UNAVAILABLE.value,
    )

    cleared = validate_success(
        api.schedule_hearing(
            ctx["demand_two"]["id"],
            {"hearing_start_at": "2026-10-07T18:00:00Z", "hearing_end_at": "2026-10-08T18:00:00Z"},
            administrator_headers,
        ),
        200,
    )
    assert cleared["status"] == "HEARING_SCHEDULED"
    assert_instant(cleared["hearing_start_at"], "2026-10-07T18:00:00Z", "hearing_start_at")
    assert_instant(cleared["brief_due_at"], "2026-11-07T18:00:00Z", "brief_due_at")


def _case_with_two_invited_witness_slots():
    ctx = setup_selected_arbitrator_case(
        unit_overrides={"tolling_enabled": True},
        grievance_overrides={
            "statement": "Three-day suspension without just cause",
            "remedy_requested_cents": 200_000,
            "back_pay_hours_claimed": 24,
        },
    )
    add_witness_employee(ctx)
    post_cost_entry(ctx["grievance"]["id"], "COUNSEL", 900_000, "EMPLOYER")
    ctx["slot_one"] = call_witness(
        ctx["demand"]["id"], ctx["witness"]["id"],
        "2026-10-05T09:00:00Z", "2026-10-05T12:20:00Z",
        headers=ctx["steward_headers"],
    )
    ctx["slot_two"] = call_witness(
        ctx["demand"]["id"], ctx["witness"]["id"],
        "2026-10-05T13:00:00Z", "2026-10-05T14:10:00Z",
        headers=ctx["steward_headers"],
    )
    return ctx


def test_forward_looking_estimate_prices_a_study_day_and_every_invited_witness(api):
    """PRD §3.8: "That variant works as follows: the hearing spans a number of days computed
    as the hours between `hearing_start_at` and `hearing_end_at` divided by 24 and rounded
    **up**, so any partial day counts as a whole day; the arbitrator fee estimate is
    `per_diem_cents` multiplied by the hearing days plus one study day; the release estimate
    is the sum of `release_cost_cents` over every witness assignment on the demand standing
    at `INVITED` or `CONFIRMED`; the transcript estimate is 120,000 cents per hearing day;
    and `estimated_cost_cents` is the sum of those three."

    Design: Difficulty/dual_variant_calc/arbitration_estimated_vs_actual_cost_diverge
    """
    ctx = _case_with_two_invited_witness_slots()

    booked = schedule_hearing(ctx["demand"]["id"])

    assert booked["status"] == "HEARING_SCHEDULED"
    assert booked["estimated_cost_cents"] == 863_250, (
        "600000 arbitrator fee + 23250 invited release time + 240000 transcripts"
    )
    assert_instant(booked["brief_due_at"], "2026-11-05T17:00:00Z", "brief_due_at")


def test_chronological_actual_cost_reads_only_the_posted_arbitration_categories(api, analyst_headers):
    """PRD §3.8: "It reads only the posted cost ledger of the demand's grievance: entries
    whose `status` is `POSTED`, whose `category` is one of `ARBITRATOR_FEE`, `TRANSCRIPT`,
    `RELEASE_TIME` or `TRAVEL`, and whose `incurred_at` is at or before the clock's current
    instant."
    PRD §3.8: "The two variants read different inputs and are expected to disagree for the
    same case: the estimate prices a study day, every merely-invited witness and a transcript
    for every scheduled day whether or not one has been charged, while the actual counts only
    money genuinely posted and not voided, ignoring study days, unconfirmed witnesses and
    not-yet-incurred charges, and excluding the `COUNSEL` and `FILING` categories entirely."

    Design: Difficulty/dual_variant_calc/arbitration_estimated_vs_actual_cost_diverge
    """
    ctx = _case_with_two_invited_witness_slots()
    schedule_hearing(ctx["demand"]["id"])

    demand = validate_success(
        api.get_arbitration_demand(ctx["demand"]["id"], analyst_headers), 200
    )

    assert demand["actual_cost_cents"] == 400_000, (
        "only the SYSTEM ARBITRATOR_FEE entry qualifies; the 900000 counsel charge does not"
    )
    assert demand["estimated_cost_cents"] == 863_250
    assert demand["estimated_cost_cents"] != demand["actual_cost_cents"]


def test_the_estimate_prices_witnesses_that_are_still_only_invited(api, analyst_headers):
    """PRD §3.7: "The **release time** an assignment consumes is computed per assignment, and
    the order of the arithmetic is normative. First take the exact hours between
    `slot_start_at` and `slot_end_at`. Then add a prep allowance of one and a half hours — an
    hour and a half of preparation is granted to every witness regardless of how long they
    are on the stand. Then round that sum **up to the next quarter of an hour** and store it
    as `release_hours`. Then multiply `release_hours` by the called employee's
    `hourly_rate_cents` and round half up to whole cents, storing the result as
    `release_cost_cents`."
    PRD §3.7: "A new assignment is written at `INVITED` with a null `confirmed_by_user_id`
    and a null `release_cost_entry_id`."

    Design: Difficulty/dual_variant_calc/arbitration_estimated_vs_actual_cost_diverge
    """
    ctx = _case_with_two_invited_witness_slots()

    assert ctx["slot_one"]["release_cost_cents"] == 15_000
    assert ctx["slot_two"]["release_cost_cents"] == 8_250
    assert ctx["slot_one"]["status"] == "INVITED"
    assert ctx["slot_two"]["status"] == "INVITED"
    assert ctx["slot_one"]["release_cost_entry_id"] is None

    booked = schedule_hearing(ctx["demand"]["id"])
    assert booked["estimated_cost_cents"] == 863_250, (
        "23250 of that estimate comes from two witnesses who have not been confirmed"
    )


def test_a_tight_hearing_runway_marks_an_untouched_case_file_deficient(api, analyst_headers):
    """PRD §3.7: "It may fall to `PREP_DEFICIENT` without anybody asking: when a hearing is
    booked, a demand whose preparation has still not started and whose hearing begins less
    than twenty-one days from the clock's current instant is marked deficient on the spot."

    Design: Corner/state_machines/tight_hearing_runway_marks_the_case_file_prep_deficient
    """
    ctx = setup_selected_arbitrator_case()

    booked = schedule_hearing(
        ctx["demand"]["id"], "2026-08-30T09:00:00Z", "2026-08-31T17:00:00Z"
    )

    assert booked["prep_status"] == "PREP_DEFICIENT"
    assert booked["status"] == "HEARING_SCHEDULED"
    assert booked["readiness_score"] == 10
    assert booked["estimated_cost_cents"] == 840_000
    assert_instant(booked["brief_due_at"], "2026-09-30T17:00:00Z", "brief_due_at")


def test_an_exhibit_filing_lifts_the_case_file_out_of_deficiency(api):
    """PRD §3.7: "`PREP_DEFICIENT` is not a dead end — it is a flag, and the same filings
    that advance an untouched case file advance a deficient one — but it leaves
    `readiness_score` at its pre-filing value and award recording still blocked."
    PRD §3.7: "An `EXHIBIT_LIST` filing carries an `exhibit_count` that must be at least 1,
    records that count on the demand, and moves the preparation dimension from either
    `PREP_NOT_STARTED` or `PREP_DEFICIENT` to `EXHIBITS_FILED`; it is permitted only while
    the demand's procedural status is `ARBITRATOR_SELECTED`, `HEARING_SCHEDULED` or `HEARD`."

    Design: Corner/state_machines/tight_hearing_runway_marks_the_case_file_prep_deficient
    """
    ctx = setup_selected_arbitrator_case()
    schedule_hearing(ctx["demand"]["id"], "2026-08-30T09:00:00Z", "2026-08-31T17:00:00Z")

    filed = file_prep(ctx["demand"]["id"], "EXHIBIT_LIST", exhibit_count=8)

    assert filed["prep_status"] == "EXHIBITS_FILED"
    assert filed["exhibit_count"] == 8
    assert filed["readiness_score"] == 50
    assert filed["status"] == "HEARING_SCHEDULED"
