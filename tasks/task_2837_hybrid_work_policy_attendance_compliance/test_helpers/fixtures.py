"""Composite setup helpers.

Every helper builds its preconditions from scratch through PRD-declared
endpoints only, because the database is empty at the start of every test.
Setup calls use the lenient `get_success_data` validator so a broken
precondition surfaces as a setup failure rather than an assertion failure.
"""
from datetime import date, timedelta

from prd_bench_local_runner.testing import get_success_data

from .api_client import api_client
from .constants import (
    ISO_WEEK_MONDAYS,
    PINNED_CLOCK_INSTANT,
    TEST_DEFAULTS,
)
from .factories import (
    adjudicate_payload,
    attendance_week_payload,
    auto_desk_payload,
    classification_decision_payload,
    classification_payload,
    desk_assignment_payload,
    employee_payload,
    employee_status_payload,
    exception_request_payload,
    hold_payload,
    neighborhood_payload,
    policy_cycle_payload,
    posture_payload,
    recalibration_review_payload,
    relocation_request_payload,
    request_info_payload,
    respond_info_payload,
    seat_allocation_payload,
    security_review_payload,
    signal_payload,
    tax_review_payload,
    team_payload,
)
from .test_users import (
    HRBP_USER_ID,
    MANAGER_USER_ID,
    TEST_USERS,
    make_employee_headers,
)

WPO = TEST_USERS["workplace_program_office_headers"]
HRBP = TEST_USERS["hr_business_partner_headers"]
MANAGER = TEST_USERS["people_manager_headers"]
SECOND_MANAGER = TEST_USERS["second_people_manager_headers"]
SECOND_HRBP = TEST_USERS["second_hr_business_partner_headers"]
ACCOMMODATION = TEST_USERS["accommodation_specialist_headers"]
AUDITOR = TEST_USERS["compliance_auditor_headers"]
SYSTEM = TEST_USERS["system_integration_headers"]


# --------------------------------------------------------------------------
# Calendar helpers
# --------------------------------------------------------------------------
def week_dates(iso_week: str):
    """The seven calendar dates an attendance week covers, Monday first."""
    monday = date.fromisoformat(ISO_WEEK_MONDAYS[iso_week])
    return [(monday + timedelta(days=offset)).isoformat() for offset in range(7)]


def week_monday(iso_week: str) -> str:
    return ISO_WEEK_MONDAYS[iso_week]


def shift_date(iso_date: str, days: int) -> str:
    return (date.fromisoformat(iso_date) + timedelta(days=days)).isoformat()


# --------------------------------------------------------------------------
# Tier 0: clock
# --------------------------------------------------------------------------
def pin_clock(instant: str = PINNED_CLOCK_INSTANT) -> dict:
    """Rebind the server's logical current UTC instant."""
    return get_success_data(api_client.set_clock(instant, {}))


# --------------------------------------------------------------------------
# Tier 1: single-entity creation
# --------------------------------------------------------------------------
def create_cycle(**overrides) -> dict:
    """Open a policy cycle in OPEN posture."""
    return get_success_data(
        api_client.create_policy_cycle(policy_cycle_payload(**overrides), WPO)
    )


def create_team(cycle_id: str, **overrides) -> dict:
    """Enroll one team in the cycle."""
    return get_success_data(
        api_client.create_team(team_payload(cycle_id, **overrides), WPO)
    )


def register_employee(team_id: str, **overrides) -> dict:
    """Register one employee owned by mgr-1 and partnered with hrbp-1.

    Either owner may be redirected by keyword; both are consumed here so they
    never collide with the positional parameters of ``employee_payload``.
    """
    manager_user_id = overrides.pop("manager_user_id", MANAGER_USER_ID)
    hr_partner_user_id = overrides.pop("hr_partner_user_id", HRBP_USER_ID)
    payload = employee_payload(team_id, manager_user_id, hr_partner_user_id, **overrides)
    return get_success_data(api_client.create_employee(payload, HRBP))


def read_employee(employee_id: str) -> dict:
    return get_success_data(api_client.get_employee(employee_id, HRBP))


def read_team(team_id: str) -> dict:
    return get_success_data(api_client.get_team(team_id, WPO))


def read_cycle(cycle_id: str) -> dict:
    return get_success_data(api_client.get_policy_cycle(cycle_id, WPO))


def read_week(week_id: str) -> dict:
    return get_success_data(api_client.get_attendance_week(week_id, HRBP))


def read_neighborhood(neighborhood_id: str) -> dict:
    return get_success_data(api_client.get_neighborhood(neighborhood_id, WPO))


def read_allocation(allocation_id: str) -> dict:
    return get_success_data(api_client.get_seat_allocation(allocation_id, WPO))


def read_case(case_id: str) -> dict:
    return get_success_data(api_client.get_escalation_case(case_id, HRBP))


def read_exception(request_id: str) -> dict:
    return get_success_data(api_client.get_exception_request(request_id, HRBP))


def read_relocation(request_id: str) -> dict:
    return get_success_data(api_client.get_relocation_request(request_id, WPO))


def read_review(review_id: str) -> dict:
    return get_success_data(api_client.get_recalibration_review(review_id, WPO))


# --------------------------------------------------------------------------
# Tier 2: cycle + team + employee setup
# --------------------------------------------------------------------------
def setup_cycle_team_employee(cycle_overrides=None, team_overrides=None,
                              employee_overrides=None, pin=True) -> dict:
    """Clock + cycle + one team + one employee. The most common preamble."""
    if pin:
        pin_clock()
    cycle = create_cycle(**(cycle_overrides or {}))
    team = create_team(cycle["id"], **(team_overrides or {}))
    employee = register_employee(team["id"], **(employee_overrides or {}))
    return {"cycle": cycle, "team": team, "employee": employee}


def setup_cycle_with_two_teams(cycle_overrides=None, team_a=None, team_b=None,
                               pin=True) -> dict:
    """Clock + cycle + two teams whose team_code ordering is deterministic."""
    if pin:
        pin_clock()
    cycle = create_cycle(**(cycle_overrides or {}))
    defaults_a = {"team_code": "T-A", "expected_days_in_office_per_week": 3,
                  "headcount_planned": 12}
    defaults_a.update(team_a or {})
    defaults_b = {"team_code": "T-B", "expected_days_in_office_per_week": 4,
                  "headcount_planned": 25}
    defaults_b.update(team_b or {})
    return {
        "cycle": cycle,
        "team_a": create_team(cycle["id"], **defaults_a),
        "team_b": create_team(cycle["id"], **defaults_b),
    }


# --------------------------------------------------------------------------
# Tier 3: eligibility classification lifecycle
# --------------------------------------------------------------------------
def draft_classification(employee: dict, **overrides) -> dict:
    """Draft a classification authored by hrbp-1 so mgr-1 may later decide it."""
    payload = classification_payload(employee["id"], employee["version"], **overrides)
    return get_success_data(api_client.create_classification(payload, HRBP))


def approve_classification_for(employee: dict, requested_class: str = "HYBRID",
                               effective_from: str = "2026-09-01",
                               justification_code: str = "ROLE_DESIGN") -> dict:
    """Walk DRAFT -> PENDING_MANAGER -> APPROVED for one employee.

    The draft is authored by hrbp-1 and decided by mgr-1, who is the employee's
    own manager_user_id and not the author, so neither the segregation-of-duties
    rule nor the manager-ownership rule blocks the decision.
    Returns {"classification": ..., "employee": <refreshed employee>}.
    """
    fresh = read_employee(employee["id"])
    classification = draft_classification(
        fresh,
        requested_class=requested_class,
        effective_from=effective_from,
        justification_code=justification_code,
    )
    get_success_data(api_client.submit_classification(classification["id"], HRBP))
    decided = get_success_data(
        api_client.decide_classification(
            classification["id"], classification_decision_payload("APPROVE"), MANAGER
        )
    )
    return {"classification": decided, "employee": read_employee(employee["id"])}


def setup_employee_with_class(eligibility_class: str, team_overrides=None,
                              cycle_overrides=None, employee_overrides=None) -> dict:
    """Cycle + team + employee holding an APPROVED classification of the named class."""
    base = setup_cycle_team_employee(
        cycle_overrides=cycle_overrides,
        team_overrides=team_overrides,
        employee_overrides=employee_overrides,
    )
    approved = approve_classification_for(base["employee"], eligibility_class)
    base["classification"] = approved["classification"]
    base["employee"] = approved["employee"]
    return base


# --------------------------------------------------------------------------
# Tier 4: attendance weeks, signals and settlement
# --------------------------------------------------------------------------
def open_week(employee_id: str, iso_week: str = "2026-W37", headers=None,
              **overrides) -> dict:
    payload = attendance_week_payload(employee_id, iso_week, **overrides)
    return get_success_data(
        api_client.create_attendance_week(payload, headers or SYSTEM)
    )


def add_signal(week_id: str, observed_date: str, signal_source: str = "BADGE",
               minutes_present: int = None, dedupe_key: str = None,
               headers=None) -> dict:
    overrides = {}
    if minutes_present is not None:
        overrides["minutes_present"] = minutes_present
    if dedupe_key is not None:
        overrides["dedupe_key"] = dedupe_key
    payload = signal_payload(observed_date, signal_source, **overrides)
    return get_success_data(
        api_client.append_signal(week_id, payload, headers or SYSTEM)
    )


def add_full_day_signals(week_id: str, dates, signal_source: str = "BADGE",
                         minutes_present: int = None):
    """Append one qualifying signal per date. Returns the created signals."""
    minutes = (
        minutes_present if minutes_present is not None
        else TEST_DEFAULTS["FULL_DAY_MINUTES"]
    )
    return [
        add_signal(week_id, observed, signal_source, minutes_present=minutes)
        for observed in dates
    ]


def finalize(week_id: str, headers=None) -> dict:
    return get_success_data(api_client.finalize_week(week_id, headers or SYSTEM))


def amend(week_id: str, amendment_reason: str = "Badge feed backfill") -> dict:
    return get_success_data(
        api_client.amend_week(week_id, {"amendment_reason": amendment_reason}, HRBP)
    )


def open_and_finalize_week(employee_id: str, iso_week: str, present_dates,
                           signal_source: str = "BADGE",
                           minutes_present: int = None) -> dict:
    """Open a week, append one qualifying signal per named date, settle it."""
    week = open_week(employee_id, iso_week)
    add_full_day_signals(week["id"], present_dates, signal_source, minutes_present)
    return finalize(week["id"])


def first_case_for(employee_id: str) -> dict:
    """The employee's escalation case, discovered through the case listing."""
    data, _ = _paginated(api_client.list_escalation_cases(HRBP, {"employee_id": employee_id}))
    assert data, f"expected an escalation case for employee {employee_id}"
    return data[0]


def cases_for(employee_id: str):
    data, _ = _paginated(api_client.list_escalation_cases(HRBP, {"employee_id": employee_id}))
    return data


def _paginated(response):
    body = response.json()
    assert 200 <= response.status_code < 300, (
        f"Setup listing failed with HTTP {response.status_code}: {response.text}"
    )
    return body["data"], body["meta"]


# --------------------------------------------------------------------------
# Tier 5: the standard breach scenario
# --------------------------------------------------------------------------
STANDARD_CYCLE = {
    "days_in_office_floor": 2,
    "badge_weight": 0.60,
    "network_weight": 0.40,
    "collaboration_target_score": 70.00,
    "equity_variance_threshold_pct": 20.00,
}

STANDARD_TEAM = {
    "team_code": "T-A",
    "expected_days_in_office_per_week": 3,
    "headcount_planned": 12,
    "signal_corroboration_required": False,
}

BREACH_PRESENT_DATES = ["2026-09-08", "2026-09-09", "2026-09-10"]


def setup_standard_breach(team_overrides=None, employee_overrides=None,
                          cycle_overrides=None, iso_week: str = "2026-W37") -> dict:
    """One unclassified employee settled at a two-day shortfall.

    Cycle with a two-day floor, team T-A expecting three days for twelve planned
    heads with corroboration off, one employee carrying the ONSITE_REQUIRED
    policy default, and a week credited with three qualifying badge days. The
    settlement leaves the employee in BREACH with a case in the formal-action
    band.

    Returns cycle, team, employee, week and case, all re-read after settlement.
    """
    cycle_kwargs = dict(STANDARD_CYCLE)
    cycle_kwargs.update(cycle_overrides or {})
    team_kwargs = dict(STANDARD_TEAM)
    team_kwargs.update(team_overrides or {})

    base = setup_cycle_team_employee(
        cycle_overrides=cycle_kwargs,
        team_overrides=team_kwargs,
        employee_overrides=dict(employee_overrides or {}),
    )
    week = open_and_finalize_week(
        base["employee"]["id"], iso_week, BREACH_PRESENT_DATES
    )
    return {
        "cycle": read_cycle(base["cycle"]["id"]),
        "team": read_team(base["team"]["id"]),
        "employee": read_employee(base["employee"]["id"]),
        "week": week,
        "case": first_case_for(base["employee"]["id"]),
    }


def setup_open_week(team_overrides=None, employee_overrides=None,
                    cycle_overrides=None, iso_week: str = "2026-W37") -> dict:
    """The standard setup with a week left OPEN and no signals yet."""
    cycle_kwargs = dict(STANDARD_CYCLE)
    cycle_kwargs.update(cycle_overrides or {})
    team_kwargs = dict(STANDARD_TEAM)
    team_kwargs.update(team_overrides or {})
    base = setup_cycle_team_employee(
        cycle_overrides=cycle_kwargs,
        team_overrides=team_kwargs,
        employee_overrides=dict(employee_overrides or {}),
    )
    base["week"] = open_week(base["employee"]["id"], iso_week)
    return base


def setup_case_at_stage(target_stage: str) -> dict:
    """Drive a case up to the named live stage using the manual escalation lever.

    The standard breach settlement lands the case at WRITTEN_WARNING; each
    further rung is one manual escalation by an HRBusinessPartner who is not the
    employee's manager.
    """
    scenario = setup_standard_breach()
    ladder = ["WRITTEN_WARNING", "PERFORMANCE_PLAN", "REFERRED"]
    assert target_stage in ladder, f"unsupported target stage {target_stage}"
    steps = ladder.index(target_stage)
    case = scenario["case"]
    for _ in range(steps):
        case = get_success_data(
            api_client.escalate_case(
                case["id"], {"action_note": "Formal action recorded."}, HRBP
            )
        )
    scenario["case"] = case
    scenario["employee"] = read_employee(scenario["employee"]["id"])
    scenario["team"] = read_team(scenario["team"]["id"])
    return scenario


def set_hold(case_id: str, value: bool) -> dict:
    return get_success_data(api_client.hold_case(case_id, hold_payload(value), HRBP))


# --------------------------------------------------------------------------
# Tier 6: exception requests
# --------------------------------------------------------------------------
def file_exception(employee_id: str, headers=None, **overrides) -> dict:
    payload = exception_request_payload(employee_id, **overrides)
    return get_success_data(
        api_client.create_exception_request(payload, headers or HRBP)
    )


def run_info_round(request_id: str, responder=None) -> dict:
    """One completed information round: request-info then respond.

    The round is opened by an AccommodationSpecialist, which is legal for every
    request including the accommodation-flagged ones, and answered by an
    HRBusinessPartner unless the caller supplies another permitted responder.
    """
    get_success_data(
        api_client.request_exception_info(
            request_id, request_info_payload(), ACCOMMODATION
        )
    )
    return get_success_data(
        api_client.respond_exception_info(
            request_id, respond_info_payload(), responder or HRBP
        )
    )


def approve_exception(request_id: str, granted_relief_days: int,
                      headers=None) -> dict:
    return get_success_data(
        api_client.adjudicate_exception(
            request_id,
            adjudicate_payload("APPROVE", granted_relief_days=granted_relief_days),
            headers or HRBP,
        )
    )


def setup_approved_exception(employee_id: str, requested_relief_days: int = 2,
                             granted_relief_days: int = None,
                             start_date: str = "2026-09-07",
                             end_date: str = "2026-09-11",
                             category: str = "CAREGIVING") -> dict:
    """File and approve one exception request.

    CAREGIVING on an employee with no accommodation on file leaves
    interactive_process_required false, so an HRBusinessPartner may approve it
    without an information round.
    """
    request = file_exception(
        employee_id,
        category=category,
        requested_relief_days=requested_relief_days,
        start_date=start_date,
        end_date=end_date,
    )
    if request["interactive_process_required"]:
        run_info_round(request["id"])
        approver = ACCOMMODATION
    else:
        approver = HRBP
    granted = (
        granted_relief_days if granted_relief_days is not None
        else requested_relief_days
    )
    return approve_exception(request["id"], granted, approver)


# --------------------------------------------------------------------------
# Tier 7: remote-location requests
# --------------------------------------------------------------------------
def setup_relocation_request(jurisdiction_code: str = "US_TX",
                             data_classification_tier: str = "PUBLIC",
                             eligibility_class: str = "HYBRID",
                             proposed_start_date: str = "2026-10-01",
                             cycle_overrides=None, team_overrides=None,
                             employee_overrides=None) -> dict:
    """Cycle + team + employee holding an APPROVED remote-eligible class, plus a
    freshly filed relocation request."""
    cycle_kwargs = dict(STANDARD_CYCLE)
    cycle_kwargs.update(cycle_overrides or {})
    team_kwargs = dict(STANDARD_TEAM)
    team_kwargs.update(team_overrides or {})
    base = setup_employee_with_class(
        eligibility_class,
        cycle_overrides=cycle_kwargs,
        team_overrides=team_kwargs,
        employee_overrides=dict(employee_overrides or {}),
    )
    payload = relocation_request_payload(
        base["employee"]["id"],
        jurisdiction_code=jurisdiction_code,
        data_classification_tier=data_classification_tier,
        proposed_start_date=proposed_start_date,
    )
    base["request"] = get_success_data(
        api_client.create_relocation_request(payload, HRBP)
    )
    return base


def record_tax(request_id: str, review_outcome: str = "CLEARED",
               licensing_gap_count: int = 0,
               tax_nexus_registration_cost_cents: int = 0) -> dict:
    return get_success_data(
        api_client.record_tax_review(
            request_id,
            tax_review_payload(
                review_outcome, licensing_gap_count,
                tax_nexus_registration_cost_cents,
            ),
            HRBP,
        )
    )


def record_security(request_id: str, review_outcome: str = "CLEARED",
                    control_gap_count: int = 0) -> dict:
    return get_success_data(
        api_client.record_security_review(
            request_id, security_review_payload(review_outcome, control_gap_count),
            AUDITOR,
        )
    )


def setup_relocation_joined(jurisdiction_code: str = "US_TX",
                            data_classification_tier: str = "PUBLIC",
                            tax_outcome: str = "CLEARED",
                            security_outcome: str = "CLEARED",
                            licensing_gap_count: int = 0,
                            control_gap_count: int = 0,
                            tax_nexus_registration_cost_cents: int = 0,
                            eligibility_class: str = "HYBRID",
                            tax_first: bool = True) -> dict:
    """A relocation request with both review dimensions recorded and no decision yet."""
    scenario = setup_relocation_request(
        jurisdiction_code=jurisdiction_code,
        data_classification_tier=data_classification_tier,
        eligibility_class=eligibility_class,
    )
    request_id = scenario["request"]["id"]
    if tax_first:
        scenario["after_tax"] = record_tax(
            request_id, tax_outcome, licensing_gap_count,
            tax_nexus_registration_cost_cents,
        )
        scenario["after_security"] = record_security(
            request_id, security_outcome, control_gap_count
        )
    else:
        scenario["after_security"] = record_security(
            request_id, security_outcome, control_gap_count
        )
        scenario["after_tax"] = record_tax(
            request_id, tax_outcome, licensing_gap_count,
            tax_nexus_registration_cost_cents,
        )
    scenario["request"] = read_relocation(request_id)
    return scenario


def decide_relocation(request_id: str, decision: str) -> dict:
    return get_success_data(
        api_client.decide_relocation(request_id, {"decision": decision}, WPO)
    )


# --------------------------------------------------------------------------
# Tier 8: space — neighborhoods, seat allocations, desks
# --------------------------------------------------------------------------
def create_neighborhood(cycle_id: str, anchor_team_id: str, **overrides) -> dict:
    payload = neighborhood_payload(cycle_id, anchor_team_id, **overrides)
    return get_success_data(api_client.create_neighborhood(payload, WPO))


def reserve_allocation(neighborhood_id: str, team_id: str, allocated_seats: int = 5,
                       window_start_week: str = "2026-W37",
                       window_end_week: str = "2026-W39",
                       expected_neighborhood_version: int = None) -> dict:
    """Reserve seats, reading the neighborhood's live version for the guard."""
    version = expected_neighborhood_version
    if version is None:
        version = read_neighborhood(neighborhood_id)["version"]
    payload = seat_allocation_payload(
        neighborhood_id, team_id, version,
        allocated_seats=allocated_seats,
        window_start_week=window_start_week,
        window_end_week=window_end_week,
    )
    return get_success_data(api_client.create_seat_allocation(payload, WPO))


def commit_allocation(allocation_id: str) -> dict:
    return get_success_data(api_client.commit_seat_allocation(allocation_id, WPO))


def release_allocation(allocation_id: str,
                       release_reason: str = "Zone reconfigured.") -> dict:
    return get_success_data(
        api_client.release_seat_allocation(
            allocation_id, {"release_reason": release_reason}, WPO
        )
    )


def setup_space(seat_count: int = 10, buffer_seats: int = 1,
                allocated_seats: int = 5,
                window_start_week: str = "2026-W37",
                window_end_week: str = "2026-W39",
                commit: bool = True, team_overrides=None,
                cycle_overrides=None, neighborhood_overrides=None) -> dict:
    """Cycle + team + employee + neighborhood + one seat allocation.

    The allocation is committed by default so it consumes capacity and carries a
    chargeback line.
    """
    cycle_kwargs = dict(STANDARD_CYCLE)
    cycle_kwargs.update(cycle_overrides or {})
    team_kwargs = dict(STANDARD_TEAM)
    team_kwargs.update(team_overrides or {})
    base = setup_cycle_team_employee(
        cycle_overrides=cycle_kwargs, team_overrides=team_kwargs
    )
    neighborhood = create_neighborhood(
        base["cycle"]["id"], base["team"]["id"],
        seat_count=seat_count, buffer_seats=buffer_seats,
        **(neighborhood_overrides or {}),
    )
    allocation = reserve_allocation(
        neighborhood["id"], base["team"]["id"], allocated_seats,
        window_start_week, window_end_week,
    )
    if commit:
        allocation = commit_allocation(allocation["id"])
    base["neighborhood"] = read_neighborhood(neighborhood["id"])
    base["allocation"] = allocation
    return base


def assign_desk(allocation_id: str, employee_id: str, desk_index: int = 1,
                start_date: str = "2026-09-07", end_date: str = "2026-09-11",
                headers=None) -> dict:
    payload = desk_assignment_payload(
        allocation_id, employee_id, desk_index,
        start_date=start_date, end_date=end_date,
    )
    return get_success_data(api_client.create_desk_assignment(payload, headers or WPO))


def auto_assign(employee_id: str, start_date: str = "2026-09-07",
                end_date: str = "2026-09-11", headers=None) -> dict:
    return get_success_data(
        api_client.auto_assign_desk(
            auto_desk_payload(employee_id, start_date, end_date), headers or WPO
        )
    )


def vacate_desk(assignment_id: str) -> dict:
    return get_success_data(api_client.vacate_desk_assignment(assignment_id, WPO))


def setup_desk_scenario(seat_count: int = 10, buffer_seats: int = 1,
                        allocated_seats: int = 5,
                        window_start_week: str = "2026-W37",
                        window_end_week: str = "2026-W41") -> dict:
    """A committed allocation plus one live desk assignment at index 1."""
    scenario = setup_space(
        seat_count=seat_count, buffer_seats=buffer_seats,
        allocated_seats=allocated_seats,
        window_start_week=window_start_week, window_end_week=window_end_week,
    )
    scenario["assignment"] = assign_desk(
        scenario["allocation"]["id"], scenario["employee"]["id"], 1
    )
    return scenario


# --------------------------------------------------------------------------
# Tier 9: posture, employment status and recalibration
# --------------------------------------------------------------------------
def set_posture(cycle_id: str, target_posture: str, note: str = None) -> dict:
    return get_success_data(
        api_client.set_cycle_posture(cycle_id, posture_payload(target_posture, note), WPO)
    )


def set_status(employee_id: str, target_status: str, note: str = None) -> dict:
    return get_success_data(
        api_client.set_employee_status(
            employee_id, employee_status_payload(target_status, note), HRBP
        )
    )


def separate_employee(employee_id: str) -> dict:
    return set_status(employee_id, "SEPARATED")


def draft_review(cycle_id: str, proposed_days_in_office_delta: int = 0,
                 review_label: str = None) -> dict:
    overrides = {"proposed_days_in_office_delta": proposed_days_in_office_delta}
    if review_label is not None:
        overrides["review_label"] = review_label
    payload = recalibration_review_payload(cycle_id, **overrides)
    return get_success_data(api_client.create_recalibration_review(payload, WPO))


def submit_review(review_id: str, headers=None) -> dict:
    return get_success_data(
        api_client.submit_recalibration_review(review_id, headers or WPO)
    )


def decide_review(review_id: str, decision: str, expected_policy_cycle_version: int,
                  headers=None, decision_reason: str = None) -> dict:
    payload = {
        "decision": decision,
        "expected_policy_cycle_version": expected_policy_cycle_version,
    }
    if decision_reason is not None:
        payload["decision_reason"] = decision_reason
    return get_success_data(
        api_client.decide_recalibration_review(review_id, payload, headers or AUDITOR)
    )


def setup_submitted_review(proposed_days_in_office_delta: int = 0,
                           scenario: dict = None,
                           cycle_overrides=None, team_overrides=None) -> dict:
    """A recalibration review submitted inside a RECALIBRATING cycle.

    When `scenario` is supplied its cycle is reused, so the measurement snapshot
    sees whatever attendance, chargeback and equity state that scenario built.
    """
    if scenario is None:
        cycle_kwargs = dict(STANDARD_CYCLE)
        cycle_kwargs.update(cycle_overrides or {})
        team_kwargs = dict(STANDARD_TEAM)
        team_kwargs.update(team_overrides or {})
        scenario = setup_cycle_team_employee(
            cycle_overrides=cycle_kwargs, team_overrides=team_kwargs
        )
    cycle_id = scenario["cycle"]["id"]
    review = draft_review(cycle_id, proposed_days_in_office_delta)
    set_posture(cycle_id, "RECALIBRATING")
    scenario["review"] = submit_review(review["id"])
    scenario["cycle"] = read_cycle(cycle_id)
    return scenario


# --------------------------------------------------------------------------
# Listing helper reused by pagination and ordering assertions
# --------------------------------------------------------------------------
def list_all(list_call, headers, params=None):
    """Call a listing endpoint and return (rows, meta)."""
    return _paginated(list_call(headers, params))


# --------------------------------------------------------------------------
# Tier 10: the deep-cascade scenario reused by settlement and separation tests
# --------------------------------------------------------------------------
DEEP_CASCADE_TEAM = {
    "team_code": "T1-CORE",
    "expected_days_in_office_per_week": 5,
    "headcount_planned": 25,
    "signal_corroboration_required": False,
}


def setup_deep_cascade_breach(cycle_label: str = "FY27-D6") -> dict:
    """Two unclassified employees on a five-day team, one settled at a shortfall.

    The first employee's week credits two qualifying badge days against five
    required days, so the settlement leaves a three-day shortfall, a one-week
    breach streak and a case in the formal-action band. The second employee is
    untouched and remains the compliant half of the cycle population.
    """
    pin_clock()
    cycle = create_cycle(
        cycle_label=cycle_label,
        days_in_office_floor=2,
        badge_weight=0.60,
        network_weight=0.40,
        collaboration_target_score=70.00,
        equity_variance_threshold_pct=20.00,
    )
    team = create_team(cycle["id"], **DEEP_CASCADE_TEAM)
    first = register_employee(
        team["id"], employee_number="E-1001", work_email="e1001@example.com"
    )
    second = register_employee(
        team["id"], employee_number="E-1002", work_email="e1002@example.com"
    )
    before = read_cycle(cycle["id"])
    week = open_and_finalize_week(
        first["id"], "2026-W37", ["2026-09-08", "2026-09-09"]
    )
    return {
        "cycle_before": before,
        "cycle": read_cycle(cycle["id"]),
        "team": read_team(team["id"]),
        "employee": read_employee(first["id"]),
        "second_employee": read_employee(second["id"]),
        "week": week,
        "case": first_case_for(first["id"]),
    }
