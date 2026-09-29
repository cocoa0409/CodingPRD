"""Crediting approved relief into settled weeks, and taking it back again."""
from test_helpers import (
    ApiErrorId,
    add_signal,
    adjudicate_payload,
    api_client,
    approve_exception,
    cases_for,
    file_exception,
    finalize,
    first_case_for,
    list_all,
    open_week,
    read_cycle,
    read_employee,
    read_exception,
    read_team,
    read_week,
    request_info_payload,
    respond_info_payload,
    revoke_payload,
    setup_cycle_team_employee,
    validate_error,
    validate_success,
)
from test_helpers.fixtures import ACCOMMODATION, HRBP
from test_helpers.test_users import make_employee_headers

FULL_WEEK_TEAM = {
    "team_code": "T1-CORE",
    "expected_days_in_office_per_week": 5,
    "core_collaboration_days": ["MON", "TUE", "WED", "THU", "FRI"],
    "headcount_planned": 25,
    "signal_corroboration_required": False,
}


def _settled_week_with_a_live_request(cycle_label, extra_signals=()):
    """A finalized week two days short, a written warning, and one live request.

    The employee carries no approved classification, so five office days are
    demanded; three dates clear the minute floor and the relief request covers
    the whole working week without naming it.
    """
    base = setup_cycle_team_employee(
        cycle_overrides={"cycle_label": cycle_label, "days_in_office_floor": 2},
        team_overrides=dict(FULL_WEEK_TEAM),
        employee_overrides={"employee_number": "E-1001",
                            "disability_accommodation_on_file": False},
    )
    employee_id = base["employee"]["id"]
    base["week"] = open_week(employee_id, "2026-W37")
    signals = [
        ("2026-09-08", "BADGE", 480),
        ("2026-09-09", "BADGE", 480),
        ("2026-09-10", "NETWORK", 480),
    ] + list(extra_signals)
    for observed, source, minutes in signals:
        add_signal(base["week"]["id"], observed, source, minutes_present=minutes)
    base["week"] = finalize(base["week"]["id"])
    base["case"] = first_case_for(employee_id)
    base["headers"] = make_employee_headers(employee_id)
    base["request"] = file_exception(
        employee_id,
        headers=base["headers"],
        category="CAREGIVING",
        requested_relief_days=2,
        start_date="2026-09-07",
        end_date="2026-09-11",
        rationale="elder-care coverage two days a week for the stated window",
    )
    return base


def _depth_five_scenario():
    """The settled week above, plus a duplicate-date network read and a short day."""
    return _settled_week_with_a_live_request(
        "FY27-D5",
        extra_signals=[("2026-09-08", "NETWORK", 300), ("2026-09-11", "BADGE", 120)],
    )


def _approved_relief_scenario():
    """The same settled week with its relief request already approved."""
    base = _settled_week_with_a_live_request("FY27-CI1")
    base["request"] = approve_exception(base["request"]["id"], 2, HRBP)
    return base


def test_01_approving_a_relief_request_rewrites_a_week_it_never_names():
    """The request names an employee and a date range; the cascade finds the week.

    PRD 3.6: "**First**, `status` becomes `APPROVED`, `granted_relief_days` takes the
    supplied value, and `adjudicated_by_user_id` records the acting user."
    PRD 3.6: "**Second**, because the request is now approved, the employee's
    `approved_relief_days_total` — the sum of `granted_relief_days` across their
    `APPROVED` requests — is recomputed."
    PRD 3.6: "**Third**, because the employee's approved relief changed, every one of
    that employee's attendance weeks whose `status` is `FINALIZED` or `LOCKED` and
    whose seven-date window intersects the relief window recomputes its
    `relief_days_credited` and its `shortfall_days`, processed in `week_start_date`
    ascending order."
    PRD 3.5: "**First**, the week's own accounting is written: `status` becomes
    `FINALIZED`, `finalized_at` is stamped at the current logical instant,
    `required_days` is snapshotted, `variant_applied` records `SIGNAL_CORROBORATED`
    when the team requires corroboration and `SIGNAL_UNION` otherwise, `credited_days`
    is counted under that standard, `relief_days_credited` is applied from approved
    exceptions, and `shortfall_days` becomes the required days minus the credited days
    minus the credited relief, floored at zero so it never goes negative."

    Design: Difficulty/transitive_cascade/exception_approval_depth_five_relief_cascade
    """
    scenario = _depth_five_scenario()
    before = scenario["week"]
    assert before["credited_days"] == 3, (
        "two dates carry two sources apiece or a short read, and dates are counted once"
    )
    assert before["relief_days_credited"] == 0
    assert before["shortfall_days"] == 2
    assert read_employee(scenario["employee"]["id"])["non_compliance_pressure"] == 4.00
    assert scenario["case"]["stage"] == "WRITTEN_WARNING"
    assert scenario["request"]["status"] == "SUBMITTED"
    assert scenario["request"]["interactive_process_required"] is False

    approved = validate_success(
        api_client.adjudicate_exception(
            scenario["request"]["id"],
            adjudicate_payload("APPROVE", granted_relief_days=2),
            HRBP,
        )
    )
    assert approved["status"] == "APPROVED"
    assert approved["granted_relief_days"] == 2
    assert approved["adjudicated_by_user_id"] == "hrbp-1"
    assert approved["info_round_count"] == 0
    assert read_employee(scenario["employee"]["id"])["approved_relief_days_total"] == 2

    after = read_week(scenario["week"]["id"])
    assert after["relief_days_credited"] == 2, (
        "two granted days against five overlapping business days, under the week's demand"
    )
    assert after["shortfall_days"] == 0
    assert after["credited_days"] == 3, "the badge and network evidence was not touched"
    assert after["required_days"] == 5


def test_02_the_same_approval_runs_the_ladder_backwards_to_the_cycle_totals():
    """A relief grant cures a case and unwinds both counters without deleting anything.

    PRD 3.6: "**Fourth**, because those weeks' shortfalls changed, the employee's
    `cumulative_shortfall_days`, `consecutive_breach_weeks`, `non_compliance_pressure`
    and `compliance_state` are recomputed."
    PRD 3.6: "**Fifth**, because the pressure changed, the employee's open case —
    provided `discretionary_hold` is false — has its `stage` reset from the new
    pressure, and a case leaving the formal-action band decrements the team's
    `formal_action_count` and therefore the cycle's `formal_action_total`."
    PRD 3.5: "Reaching `CURED` from `COACHING` sets `escalation_stage` back to `NONE`,
    decrements `escalated_headcount` by one, and refreshes the cycle's
    `aggregate_compliance_rate`; reaching `CURED` from `WRITTEN_WARNING` does all of
    that **and** decrements `formal_action_count`, refreshing `formal_action_total` as
    well."
    PRD 3.2: "Registration also recomputes the parent cycle's
    `aggregate_compliance_rate`, which is the count of `ACTIVE` employees on teams of
    that cycle whose `compliance_state` is `COMPLIANT`, divided by the total count of
    `ACTIVE` employees on those teams, multiplied by 100 and rounded half up to two
    decimals; when no `ACTIVE` employee exists on the cycle's teams at all the rate is
    exactly 0.00 rather than an error."

    Design: Difficulty/transitive_cascade/exception_approval_depth_five_relief_cascade
    """
    scenario = _depth_five_scenario()
    employee_id = scenario["employee"]["id"]
    assert read_team(scenario["team"]["id"])["escalated_headcount"] == 1
    assert read_team(scenario["team"]["id"])["formal_action_count"] == 1
    assert read_cycle(scenario["cycle"]["id"])["formal_action_total"] == 1
    assert read_cycle(scenario["cycle"]["id"])["aggregate_compliance_rate"] == 0.00

    approve_exception(scenario["request"]["id"], 2, HRBP)

    employee = read_employee(employee_id)
    assert employee["cumulative_shortfall_days"] == 0
    assert employee["consecutive_breach_weeks"] == 0
    assert employee["non_compliance_pressure"] == 0.00
    assert employee["compliance_state"] == "COMPLIANT"
    assert employee["escalation_stage"] == "NONE"

    cured = read_exception(scenario["request"]["id"])
    assert cured["status"] == "APPROVED"
    case = first_case_for(employee_id)
    assert case["stage"] == "CURED", "the cascade drove the ladder down, not up"
    assert case["discretionary_hold"] is False

    team = read_team(scenario["team"]["id"])
    assert team["escalated_headcount"] == 0
    assert team["formal_action_count"] == 0
    cycle = read_cycle(scenario["cycle"]["id"])
    assert cycle["formal_action_total"] == 0
    assert cycle["aggregate_compliance_rate"] == 100.00, (
        "the only ACTIVE employee on the cycle's teams is now COMPLIANT"
    )

    rows, meta = list_all(
        api_client.list_escalation_cases, HRBP, {"employee_id": employee_id}
    )
    assert meta["total_count"] == 1, "curing a case does not delete it"
    assert rows[0]["id"] == scenario["case"]["id"]


def test_03_revocation_puts_the_relief_the_week_and_the_pressure_back():
    """Every conserved quantity returns to the value it held before the approval.

    PRD 3.6: "**Revocation** is the compensating action for an approval and reverses it
    exactly."
    PRD 3.6: "The request's `status` becomes `REVOKED` and its `granted_relief_days`
    returns to 0; the employee's `approved_relief_days_total` is recomputed, undoing the
    second link of the approval chain; the same set of `FINALIZED` and `LOCKED` weeks
    recomputes `relief_days_credited` and `shortfall_days` in `week_start_date`
    ascending order; the employee's `cumulative_shortfall_days`,
    `consecutive_breach_weeks`, `non_compliance_pressure` and `compliance_state` are
    recomputed; and the open case's `stage` — again only when `discretionary_hold` is
    false — is reset from the restored pressure, so a case re-entering the
    formal-action band re-increments `formal_action_count` and `formal_action_total`."
    PRD 3.6: "Every conserved quantity returns to its pre-approval value with no drift:
    that is the contract revocation is held to."
    PRD 3.6: "A request must be `APPROVED`, or the call is refused with
    `ERR_EXCEPTION_NOT_APPROVED` (409), which is also what a second revocation receives.
    The caller supplies a `closure_reason`."

    Design: Difficulty/compensating_invariant/exception_revoke_restores_pressure_stage_and_relief_total
    """
    scenario = _approved_relief_scenario()
    employee_id = scenario["employee"]["id"]
    assert scenario["request"]["status"] == "APPROVED"
    assert read_week(scenario["week"]["id"])["relief_days_credited"] == 2
    assert read_week(scenario["week"]["id"])["shortfall_days"] == 0
    assert read_employee(employee_id)["approved_relief_days_total"] == 2
    assert read_employee(employee_id)["non_compliance_pressure"] == 0.00

    revoked = validate_success(
        api_client.revoke_exception(
            scenario["request"]["id"],
            revoke_payload("caregiving arrangement ended early"),
            ACCOMMODATION,
        )
    )
    assert revoked["status"] == "REVOKED"
    assert revoked["granted_relief_days"] == 0
    assert revoked["closure_reason"] == "caregiving arrangement ended early"

    assert read_employee(employee_id)["approved_relief_days_total"] == 0, (
        "the total returns to the value it held before the approval, not below it"
    )

    week = read_week(scenario["week"]["id"])
    assert week["relief_days_credited"] == 0
    assert week["shortfall_days"] == 2
    assert week["credited_days"] == 3, (
        "the badge and network evidence was never part of the compensation"
    )

    employee = read_employee(employee_id)
    assert employee["cumulative_shortfall_days"] == 2
    assert employee["consecutive_breach_weeks"] == 1
    assert employee["non_compliance_pressure"] == 4.00, (
        "the pressure climbs back to exactly the figure it left"
    )
    assert employee["compliance_state"] == "BREACH"


def test_04_revocation_reopens_the_band_with_a_new_case_and_refuses_a_second_pass():
    """The counters are restored; the cured case is not, because terminal means terminal.

    PRD 3.6: "A request must be `APPROVED`, or the call is refused with
    `ERR_EXCEPTION_NOT_APPROVED` (409), which is also what a second revocation
    receives."
    PRD 3.5: "The **escalation ladder** has four live rungs, `COACHING`,
    `WRITTEN_WARNING`, `PERFORMANCE_PLAN` and `REFERRED`, and two terminal outcomes,
    `CURED` and `CLOSED_SEPARATION`."
    PRD 3.5: "A later breach opens a brand-new case whose `prior_case_id` points back
    at the cured one, which is how the self-referential case history is threaded."
    PRD 3.5: "`escalated_headcount` is the number of that team's employees holding a
    case whose `stage` is `COACHING`, `WRITTEN_WARNING`, `PERFORMANCE_PLAN` or
    `REFERRED`; `formal_action_count` is the number holding a case in the narrower
    formal-action band of `WRITTEN_WARNING`, `PERFORMANCE_PLAN` or `REFERRED`."

    Design: Difficulty/compensating_invariant/exception_revoke_restores_pressure_stage_and_relief_total
    """
    scenario = _approved_relief_scenario()
    employee_id = scenario["employee"]["id"]
    first_case_id = scenario["case"]["id"]
    assert read_team(scenario["team"]["id"])["formal_action_count"] == 0
    assert read_cycle(scenario["cycle"]["id"])["formal_action_total"] == 0

    validate_success(
        api_client.revoke_exception(
            scenario["request"]["id"],
            revoke_payload("caregiving arrangement ended early"),
            ACCOMMODATION,
        )
    )

    team = read_team(scenario["team"]["id"])
    assert team["escalated_headcount"] == 1
    assert team["formal_action_count"] == 1
    assert read_cycle(scenario["cycle"]["id"])["formal_action_total"] == 1, (
        "the cycle total is again the sum over the cycle's teams"
    )

    rows, meta = list_all(
        api_client.list_escalation_cases, HRBP, {"employee_id": employee_id}
    )
    assert meta["total_count"] == 2, "re-entry opens a second case rather than reviving one"
    older = [row for row in rows if row["id"] == first_case_id][0]
    newer = [row for row in rows if row["id"] != first_case_id][0]
    assert older["stage"] == "CURED", "a terminal stage is never reopened"
    assert newer["stage"] == "WRITTEN_WARNING"
    assert newer["opened_pressure"] == 4.00
    assert newer["prior_case_id"] == first_case_id
    assert read_employee(employee_id)["escalation_stage"] == "WRITTEN_WARNING"

    validate_error(
        api_client.revoke_exception(
            scenario["request"]["id"],
            revoke_payload("duplicate revocation attempt"),
            ACCOMMODATION,
        ),
        ApiErrorId.ERR_EXCEPTION_NOT_APPROVED.value,
        409,
    )
    assert read_employee(employee_id)["non_compliance_pressure"] == 4.00, (
        "the compensation is not applied twice"
    )
    assert read_team(scenario["team"]["id"])["formal_action_count"] == 1
    assert read_week(scenario["week"]["id"])["shortfall_days"] == 2
    assert len(cases_for(employee_id)) == 2


def test_05_two_grants_contribute_their_business_day_overlap_and_the_total_is_clamped():
    """Ten granted days over an empty five-day week credit five, and not a day more.

    PRD 3.6: "Granted relief may never exceed what the employee asked for: a
    `granted_relief_days` above the stored `requested_relief_days` is refused with
    `ERR_RELIEF_EXCEEDS_REQUEST` (409)."
    PRD 3.6: "For each request, count how many of the week's dates fall on a Monday
    through Friday **and** inside that request's inclusive window; that count is the
    request's business-day overlap for this week."
    PRD 3.6: "Add to the running total the smaller of the request's
    `granted_relief_days` and that business-day overlap."
    PRD 3.6: "When every request has been walked, the week's `relief_days_credited` is
    the smaller of the running total and the week's `required_days` — the system never
    credits more relief than the week actually demanded."
    PRD 3.6: "Collect the requests whose closed relief window intersects any of the
    week's seven dates, and order them by `created_at` ascending — that order is
    pinned, and it is why the exception collection is listed in the same order."

    Design: Corner/calculations/relief_waterfall_credits_business_day_overlap_in_creation_order
    """
    base = setup_cycle_team_employee(
        cycle_overrides={"cycle_label": "FY27-CRN42", "days_in_office_floor": 2},
        team_overrides={
            "team_code": "T-A",
            "expected_days_in_office_per_week": 3,
            "core_collaboration_days": ["TUE", "WED", "THU"],
            "headcount_planned": 12,
            "signal_corroboration_required": False,
        },
        employee_overrides={"employee_number": "E-1001",
                            "disability_accommodation_on_file": False},
    )
    employee_id = base["employee"]["id"]
    week = finalize(open_week(employee_id, "2026-W37")["id"])
    assert week["required_days"] == 5
    assert week["credited_days"] == 0
    assert week["shortfall_days"] == 5
    assert read_employee(employee_id)["non_compliance_pressure"] == 8.50
    assert first_case_for(employee_id)["stage"] == "PERFORMANCE_PLAN"

    two_day_window = file_exception(
        employee_id,
        category="CAREGIVING",
        requested_relief_days=5,
        start_date="2026-09-07",
        end_date="2026-09-08",
        rationale="eldercare Monday and Tuesday",
    )
    whole_week = file_exception(
        employee_id,
        category="MEDICAL",
        requested_relief_days=5,
        start_date="2026-09-07",
        end_date="2026-09-13",
        rationale="post-operative recovery, whole week",
    )

    validate_error(
        api_client.adjudicate_exception(
            two_day_window["id"],
            adjudicate_payload("APPROVE", granted_relief_days=6),
            HRBP,
        ),
        ApiErrorId.ERR_RELIEF_EXCEEDS_REQUEST.value,
        409,
    )
    assert read_exception(two_day_window["id"])["status"] == "SUBMITTED"
    assert read_week(week["id"])["relief_days_credited"] == 0

    approve_exception(two_day_window["id"], 5, HRBP)
    after_first = read_week(week["id"])
    assert after_first["relief_days_credited"] == 2, (
        "five granted days over two Monday-to-Friday dates contribute two"
    )
    assert after_first["shortfall_days"] == 3
    employee = read_employee(employee_id)
    assert employee["non_compliance_pressure"] == 5.50
    assert employee["approved_relief_days_total"] == 5, (
        "the employee counter holds granted days, which the credit calculation caps"
    )
    assert first_case_for(employee_id)["stage"] == "WRITTEN_WARNING"

    validate_success(
        api_client.request_exception_info(
            whole_week["id"], request_info_payload("expected return-to-office date"),
            ACCOMMODATION,
        )
    )
    validate_success(
        api_client.respond_exception_info(
            whole_week["id"], respond_info_payload("cleared to return from 2026-09-14"),
            HRBP,
        )
    )
    approve_exception(whole_week["id"], 5, ACCOMMODATION)

    after_second = read_week(week["id"])
    assert after_second["relief_days_credited"] == 5, (
        "a running total of seven is clamped to what the week demanded"
    )
    assert after_second["shortfall_days"] == 0
    assert after_second["required_days"] == 5
    assert after_second["credited_days"] == 0
    employee = read_employee(employee_id)
    assert employee["non_compliance_pressure"] == 0.00
    assert employee["compliance_state"] == "COMPLIANT"
    assert employee["approved_relief_days_total"] == 10, (
        "ten days were granted even though only five could ever be credited"
    )
    assert first_case_for(employee_id)["stage"] == "CURED"

    rows, meta = list_all(
        api_client.list_exception_requests, HRBP, {"employee_id": employee_id}
    )
    assert meta["total_count"] == 2
    assert [row["id"] for row in rows] == [two_day_window["id"], whole_week["id"]], (
        "the collection order is the pinned relief accumulation order"
    )
