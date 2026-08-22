"""Composite setup helpers.

Every helper builds its preconditions from scratch through PRD-declared
endpoints, because the API server is relaunched with an empty database before
each test. Setup calls use the lenient validator so a broken precondition
surfaces as a clear "Setup step failed" rather than as a confusing assertion
inside the test body.
"""

from prd_bench_local_runner.testing import get_success_data

from .api_client import api_client
from .constants import CLOCK_START, TEST_DEFAULTS
from .factories import (
    arbitration_demand_payload,
    arbitrator_payload,
    bargaining_unit_payload,
    contract_clause_payload,
    cost_entry_payload,
    employee_payload,
    grievance_payload,
    grievance_step_payload,
    hearing_payload,
    precedent_case_payload,
    prep_filing_payload,
    settlement_offer_payload,
    step_response_payload,
    witness_assignment_payload,
)
from .test_users import TEST_USERS, make_grievant_headers, make_steward_headers

DIRECTOR = TEST_USERS["director_headers"]
ANALYST = TEST_USERS["analyst_headers"]
ADMINISTRATOR = TEST_USERS["administrator_headers"]
NEGOTIATOR = TEST_USERS["negotiator_headers"]

# The canonical ladder calendar used across the suite: each rung is scheduled,
# the clock is moved onto the meeting date, the meeting is held and answered.
LADDER_MEETINGS = ("2026-08-05T00:00:00Z", "2026-08-10T00:00:00Z", "2026-08-14T00:00:00Z")
DEFAULT_HEARING_START = "2026-10-05T09:00:00Z"
DEFAULT_HEARING_END = "2026-10-06T17:00:00Z"


# --------------------------------------------------------------------------
# Tier 0: the logical clock and single-resource creation
# --------------------------------------------------------------------------

def set_clock(to_iso8601: str, headers=DIRECTOR) -> str:
    """Move the logical clock and return its new reading."""
    data = get_success_data(api_client.set_clock(to_iso8601, headers))
    return data.get("current_utc")


def create_bargaining_unit(**overrides) -> dict:
    return get_success_data(
        api_client.create_bargaining_unit(bargaining_unit_payload(**overrides), DIRECTOR)
    )


def create_contract_clause(unit_id: str, **overrides) -> dict:
    return get_success_data(
        api_client.create_contract_clause(
            unit_id, contract_clause_payload(**overrides), DIRECTOR
        )
    )


def create_employee(unit_id: str, **overrides) -> dict:
    return get_success_data(
        api_client.create_employee(employee_payload(unit_id, **overrides), DIRECTOR)
    )


def create_precedent_case(clause_id: str, **overrides) -> dict:
    return get_success_data(
        api_client.create_precedent_case(precedent_case_payload(clause_id, **overrides), DIRECTOR)
    )


def create_arbitrator(**overrides) -> dict:
    return get_success_data(
        api_client.create_arbitrator(arbitrator_payload(**overrides), ADMINISTRATOR)
    )


def create_three_aaa_arbitrators(**chan_overrides) -> tuple:
    """Alvarez (250000/day), Chan (200000/day) and Dowd (200000/day), in that order.

    Chan is created before Dowd so that the created_at tie-break decides between
    them when both carry the same per diem and the same engagement count.
    """
    alvarez = create_arbitrator(full_name="Ruth Alvarez", per_diem_cents=250_000)
    chan_kwargs = {"full_name": "Ben Chan", "per_diem_cents": 200_000}
    chan_kwargs.update(chan_overrides)
    chan = create_arbitrator(**chan_kwargs)
    dowd = create_arbitrator(full_name="Cara Dowd", per_diem_cents=200_000)
    return alvarez, chan, dowd


# --------------------------------------------------------------------------
# Tier 1: the base registry — agreement, clause and three people
# --------------------------------------------------------------------------

def setup_base(unit_overrides=None, clause_overrides=None, grievant_overrides=None) -> dict:
    """Agreement + one clause + supervisor, grievant and steward.

    Returns a context dict carrying every created row plus the entity-backed
    headers for the steward and the grievant.
    """
    unit = create_bargaining_unit(**(unit_overrides or {}))
    clause = create_contract_clause(unit["id"], **(clause_overrides or {}))
    supervisor = create_employee(
        unit["id"],
        full_name="Dana Fields",
        employee_number="SUP-1",
        hire_date="2015-03-01T00:00:00Z",
        seniority_date="2015-03-01T00:00:00Z",
        hourly_rate_cents=TEST_DEFAULTS["SUPERVISOR_RATE_CENTS"],
        classification="SUPERVISOR",
    )
    grievant_payload = {
        "full_name": "Ray Ortiz",
        "employee_number": "EMP-1",
        "hourly_rate_cents": TEST_DEFAULTS["GRIEVANT_RATE_CENTS"],
        "classification": "PRODUCTION",
        "supervisor_id": supervisor["id"],
    }
    grievant_payload.update(grievant_overrides or {})
    grievant = create_employee(unit["id"], **grievant_payload)
    steward = create_employee(
        unit["id"],
        full_name="Ivan Cruz",
        employee_number="STW-1",
        hire_date="2016-02-01T00:00:00Z",
        seniority_date="2016-02-01T00:00:00Z",
        hourly_rate_cents=TEST_DEFAULTS["STEWARD_RATE_CENTS"],
        classification="CLERICAL",
        supervisor_id=supervisor["id"],
    )
    return {
        "unit": unit,
        "clause": clause,
        "supervisor": supervisor,
        "grievant": grievant,
        "steward": steward,
        "steward_headers": make_steward_headers(steward["id"]),
        "grievant_headers": make_grievant_headers(grievant["id"]),
    }


def add_employee(ctx: dict, key: str, **overrides) -> dict:
    """Register one more person in the same unit and stash it on the context."""
    employee = create_employee(ctx["unit"]["id"], **overrides)
    ctx[key] = employee
    return employee


def add_witness_employee(ctx: dict, **overrides) -> dict:
    """Register EMP-2 at 3000 cents/hour as the standard testimony witness."""
    payload = {
        "full_name": "Nia Brooks",
        "employee_number": "EMP-2",
        "hire_date": "2019-05-06T00:00:00Z",
        "seniority_date": "2019-05-06T00:00:00Z",
        "hourly_rate_cents": TEST_DEFAULTS["WITNESS_RATE_CENTS"],
        "classification": "PRODUCTION",
        "supervisor_id": ctx["supervisor"]["id"],
    }
    payload.update(overrides)
    return add_employee(ctx, "witness", **payload)


# --------------------------------------------------------------------------
# Tier 2: grievances
# --------------------------------------------------------------------------

def file_grievance(ctx: dict, **overrides) -> dict:
    """File one grievance under the context's agreement, as its filing steward.

    The four foreign keys default to the context's own rows but may be overridden
    by keyword, which is how a case naming a different grievant, supervisor,
    clause or unit is filed against the same registry.
    """
    payload = grievance_payload(
        overrides.pop("bargaining_unit_id", ctx["unit"]["id"]),
        overrides.pop("grievant_id", ctx["grievant"]["id"]),
        overrides.pop("respondent_supervisor_id", ctx["supervisor"]["id"]),
        overrides.pop("clause_id", ctx["clause"]["id"]),
        **overrides,
    )
    return get_success_data(
        api_client.create_grievance(payload, ctx["steward_headers"])
    )


def setup_grievance(unit_overrides=None, clause_overrides=None, grievant_overrides=None,
                    **grievance_overrides) -> dict:
    """Base registry plus one grievance in FILED. Context carries `grievance`."""
    ctx = setup_base(unit_overrides, clause_overrides, grievant_overrides)
    ctx["grievance"] = file_grievance(ctx, **grievance_overrides)
    return ctx


def read_grievance(grievance_id: str, headers=ANALYST) -> dict:
    return get_success_data(api_client.get_grievance(grievance_id, headers))


def grievance_version(grievance_id: str, headers=ANALYST) -> int:
    return read_grievance(grievance_id, headers)["version"]


def refresh_grievance(ctx: dict, headers=ANALYST) -> dict:
    ctx["grievance"] = read_grievance(ctx["grievance"]["id"], headers)
    return ctx["grievance"]


# --------------------------------------------------------------------------
# Tier 3: the step ladder
# --------------------------------------------------------------------------

def schedule_step(grievance_id: str, meeting_scheduled_at: str, **overrides) -> dict:
    return get_success_data(
        api_client.create_grievance_step(
            grievance_id, grievance_step_payload(meeting_scheduled_at, **overrides), ANALYST
        )
    )


def hold_step(step_id: str, headers=ANALYST) -> dict:
    return get_success_data(api_client.hold_grievance_step(step_id, headers))


def respond_step(step_id: str, disposition: str = "DENIED", headers=ANALYST, **overrides) -> dict:
    return get_success_data(
        api_client.respond_grievance_step(
            step_id, step_response_payload(disposition, **overrides), headers
        )
    )


def appeal_grievance(ctx: dict, appeal_statement: str = "Appealed to the next step") -> dict:
    return get_success_data(
        api_client.appeal_grievance(
            ctx["grievance"]["id"],
            {"appeal_statement": appeal_statement},
            ctx["steward_headers"],
        )
    )


def run_step(ctx: dict, meeting_scheduled_at: str, disposition: str = "DENIED",
             responder_headers=ANALYST, response_overrides=None, **step_overrides) -> dict:
    """Schedule a rung, move the clock onto the meeting, hold it and answer it."""
    step = schedule_step(ctx["grievance"]["id"], meeting_scheduled_at, **step_overrides)
    set_clock(meeting_scheduled_at)
    hold_step(step["id"])
    return respond_step(
        step["id"], disposition, headers=responder_headers, **(response_overrides or {})
    )


def hold_open_step(ctx: dict, meeting_scheduled_at: str, **step_overrides) -> dict:
    """Schedule a rung, move the clock onto the meeting and hold it, leaving it open."""
    step = schedule_step(ctx["grievance"]["id"], meeting_scheduled_at, **step_overrides)
    set_clock(meeting_scheduled_at)
    return hold_step(step["id"])


def advance_to_step3_answered(ctx: dict, dispositions=("DENIED", "DENIED", "DENIED"),
                              meetings=LADDER_MEETINGS) -> list:
    """Drive one grievance through rungs 1, 2 and 3, answering each in turn.

    Leaves the grievance at ANSWERED with current_step 3, which is the state
    from which arbitration may be demanded. Returns the three step records as
    they read immediately after each answer.
    """
    steps = []
    for index, (meeting_at, disposition) in enumerate(zip(meetings, dispositions)):
        steps.append(run_step(ctx, meeting_at, disposition))
        if index < 2:
            appeal_grievance(ctx, f"Appealed to step {index + 2}")
    ctx["steps"] = steps
    refresh_grievance(ctx)
    return steps


# --------------------------------------------------------------------------
# Tier 4: settlement offers
# --------------------------------------------------------------------------

def draft_offer(grievance_id: str, headers=ANALYST, offering_party="EMPLOYER",
                monetary_cents=40_000, **overrides) -> dict:
    return get_success_data(
        api_client.create_settlement_offer(
            grievance_id,
            settlement_offer_payload(offering_party, monetary_cents, **overrides),
            headers,
        )
    )


def authorize_offer(offer_id: str, grievance_id: str, headers=DIRECTOR, **extra) -> dict:
    """Read the grievance version, then authorize the offer against it."""
    payload = {"expected_grievance_version": grievance_version(grievance_id)}
    payload.update(extra)
    return get_success_data(
        api_client.authorize_settlement_offer(offer_id, payload, headers)
    )


def setup_authorized_offer(monetary_cents=40_000, **grievance_overrides) -> dict:
    """One grievance carrying a single AUTHORIZED employer offer."""
    ctx = setup_grievance(**grievance_overrides)
    ctx["offer"] = draft_offer(ctx["grievance"]["id"], monetary_cents=monetary_cents)
    ctx["offer"] = authorize_offer(ctx["offer"]["id"], ctx["grievance"]["id"])
    return ctx


# --------------------------------------------------------------------------
# Tier 5: arbitration
# --------------------------------------------------------------------------

def demand_arbitration(ctx: dict, panel_size=3, panel_source="AAA", **overrides) -> dict:
    payload = arbitration_demand_payload(
        grievance_version(ctx["grievance"]["id"]), panel_source, panel_size, **overrides
    )
    demand = get_success_data(
        api_client.create_arbitration_demand(
            ctx["grievance"]["id"], payload, ctx["steward_headers"]
        )
    )
    ctx["demand"] = demand
    return demand


def setup_demanded_case(unit_overrides=None, clause_overrides=None, panel_size=3,
                        with_arbitrators=True, chan_overrides=None,
                        grievance_overrides=None, grievant_overrides=None) -> dict:
    """Full step ladder plus an arbitration demand in DEMANDED.

    Also registers the three AAA arbitrators the strike fixtures consume, unless
    the caller wants to build a different roster first.
    """
    ctx = setup_base(unit_overrides, clause_overrides, grievant_overrides)
    if with_arbitrators:
        alvarez, chan, dowd = create_three_aaa_arbitrators(**(chan_overrides or {}))
        ctx["alvarez"], ctx["chan"], ctx["dowd"] = alvarez, chan, dowd
    ctx["grievance"] = file_grievance(ctx, **(grievance_overrides or {}))
    advance_to_step3_answered(ctx)
    demand_arbitration(ctx, panel_size=panel_size)
    return ctx


def request_panel(demand_id: str) -> dict:
    return get_success_data(api_client.request_panel(demand_id, ADMINISTRATOR))


def take_strike(demand_id: str, arbitrator_id: str, headers) -> dict:
    return get_success_data(
        api_client.create_panel_strike(demand_id, {"arbitrator_id": arbitrator_id}, headers)
    )


def setup_selected_arbitrator_case(**kwargs) -> dict:
    """Demand driven to ARBITRATOR_SELECTED with Ben Chan as the survivor.

    The union strikes Alvarez and the employer strikes Dowd, so the panel of
    three resolves to Chan and the engagement cascade fires.
    """
    ctx = setup_demanded_case(**kwargs)
    request_panel(ctx["demand"]["id"])
    take_strike(ctx["demand"]["id"], ctx["alvarez"]["id"], ctx["steward_headers"])
    take_strike(ctx["demand"]["id"], ctx["dowd"]["id"], DIRECTOR)
    ctx["demand"] = get_success_data(
        api_client.get_arbitration_demand(ctx["demand"]["id"], ANALYST)
    )
    return ctx


def schedule_hearing(demand_id: str, hearing_start_at=DEFAULT_HEARING_START,
                     hearing_end_at=DEFAULT_HEARING_END) -> dict:
    return get_success_data(
        api_client.schedule_hearing(
            demand_id, hearing_payload(hearing_start_at, hearing_end_at), ADMINISTRATOR
        )
    )


def setup_hearing_scheduled_case(hearing_start_at=DEFAULT_HEARING_START,
                                 hearing_end_at=DEFAULT_HEARING_END, **kwargs) -> dict:
    ctx = setup_selected_arbitrator_case(**kwargs)
    ctx["demand"] = schedule_hearing(ctx["demand"]["id"], hearing_start_at, hearing_end_at)
    return ctx


def file_prep(demand_id: str, filing_type: str, **overrides) -> dict:
    return get_success_data(
        api_client.create_prep_filing(
            demand_id, prep_filing_payload(filing_type, **overrides), ANALYST
        )
    )


def file_prep_through_briefs(demand_id: str, exhibit_count: int = 6) -> dict:
    file_prep(demand_id, "EXHIBIT_LIST", exhibit_count=exhibit_count)
    return file_prep(demand_id, "BRIEF")


def setup_award_ready_case(hearing_start_at=DEFAULT_HEARING_START,
                           hearing_end_at=DEFAULT_HEARING_END,
                           clock_after_hearing="2026-10-07T00:00:00Z",
                           exhibit_count=6, **kwargs) -> dict:
    """Hearing booked, case file at BRIEFS_FILED and the clock past the hearing."""
    ctx = setup_hearing_scheduled_case(hearing_start_at, hearing_end_at, **kwargs)
    ctx["demand"] = file_prep_through_briefs(ctx["demand"]["id"], exhibit_count)
    set_clock(clock_after_hearing)
    return ctx


def record_award(demand_id: str, outcome="DENIED", **overrides) -> dict:
    payload = {"outcome": outcome}
    if outcome == "DENIED" and "sustained_fraction_bps" not in overrides:
        payload["sustained_fraction_bps"] = 0
    if outcome == "SUSTAINED" and "sustained_fraction_bps" not in overrides:
        payload["sustained_fraction_bps"] = 10_000
    payload.update(overrides)
    return get_success_data(api_client.create_award(demand_id, payload, ADMINISTRATOR))


def setup_split_award_case(clock_at_award="2026-11-14T00:00:00Z", **kwargs) -> dict:
    """The canonical SPLIT award: 120 ordered hours at 3500 cents against a
    60 percent sustained fraction, 5 percent interest from 2026-08-15 and a
    90000 cent mitigation offset."""
    kwargs.setdefault("grievance_overrides", {"back_pay_hours_claimed": 120})
    ctx = setup_award_ready_case(clock_after_hearing=clock_at_award, **kwargs)
    ctx["award"] = record_award(
        ctx["demand"]["id"],
        outcome="SPLIT",
        sustained_fraction_bps=6_000,
        back_pay_hours_ordered=120,
        mitigation_offset_cents=90_000,
        interest_rate_bps=500,
        interest_accrual_start="2026-08-15T00:00:00Z",
        remedy_deadline_days=30,
    )
    return ctx


# --------------------------------------------------------------------------
# Tier 6: witnesses and the case cost ledger
# --------------------------------------------------------------------------

def call_witness(demand_id: str, employee_id: str, slot_start_at: str, slot_end_at: str,
                 headers=ANALYST, **overrides) -> dict:
    return get_success_data(
        api_client.create_witness_assignment(
            demand_id,
            witness_assignment_payload(employee_id, slot_start_at, slot_end_at, **overrides),
            headers,
        )
    )


def confirm_witness(assignment_id: str, headers=DIRECTOR) -> dict:
    return get_success_data(api_client.confirm_witness_assignment(assignment_id, headers))


def post_cost_entry(grievance_id: str, category="FILING", amount_cents=12_500,
                    bearing_party="UNION", headers=ANALYST) -> dict:
    return get_success_data(
        api_client.create_cost_entry(
            grievance_id, cost_entry_payload(category, amount_cents, bearing_party), headers
        )
    )


def void_cost_entry(cost_entry_id: str, void_reason="Posted in error", headers=DIRECTOR) -> dict:
    return get_success_data(
        api_client.void_cost_entry(cost_entry_id, {"void_reason": void_reason}, headers)
    )


def setup_case_with_counsel_cost(amount_cents=900_000) -> dict:
    """One grievance carrying a single employer-borne COUNSEL charge.

    That single 900000 cent entry puts the case at 972000 cents in total, which
    is the pre-action baseline several cost tests measure against.
    """
    ctx = setup_grievance()
    ctx["counsel_entry"] = post_cost_entry(
        ctx["grievance"]["id"], "COUNSEL", amount_cents, "EMPLOYER"
    )
    return ctx


__all__ = [
    "ADMINISTRATOR",
    "ANALYST",
    "CLOCK_START",
    "DEFAULT_HEARING_END",
    "DEFAULT_HEARING_START",
    "DIRECTOR",
    "LADDER_MEETINGS",
    "NEGOTIATOR",
    "add_employee",
    "add_witness_employee",
    "advance_to_step3_answered",
    "appeal_grievance",
    "authorize_offer",
    "call_witness",
    "confirm_witness",
    "create_arbitrator",
    "create_bargaining_unit",
    "create_contract_clause",
    "create_employee",
    "create_precedent_case",
    "create_three_aaa_arbitrators",
    "demand_arbitration",
    "draft_offer",
    "file_grievance",
    "file_prep",
    "file_prep_through_briefs",
    "grievance_version",
    "hold_open_step",
    "hold_step",
    "post_cost_entry",
    "read_grievance",
    "record_award",
    "refresh_grievance",
    "request_panel",
    "respond_step",
    "run_step",
    "schedule_hearing",
    "schedule_step",
    "set_clock",
    "setup_authorized_offer",
    "setup_award_ready_case",
    "setup_base",
    "setup_case_with_counsel_cost",
    "setup_demanded_case",
    "setup_grievance",
    "setup_hearing_scheduled_case",
    "setup_selected_arbitrator_case",
    "setup_split_award_case",
    "take_strike",
    "void_cost_entry",
]
