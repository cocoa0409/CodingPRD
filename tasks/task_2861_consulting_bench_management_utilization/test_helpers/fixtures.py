"""Composite setup helpers for the Consulting Bench Management API suite.

The harness relaunches the API server before every individual test, so every
test starts against an empty database. Every precondition below is therefore
built from scratch through PRD-declared endpoints only.

Tier 1  atoms — one endpoint call each, with the envelope already unwrapped
Tier 2  entity hierarchy — group / skill / consultant graphs
Tier 3  lifecycle shortcuts — qualified demand, confirmed assignment, ...
Tier 4  accumulation and threshold targeting — bench ladder, posture, coverage
Tier 5  finalization and terminal states — closed periods, separations
"""

from typing import Any, Dict, List, Optional

from prd_bench_local_runner.testing import get_success_data, validate_success

from . import factories
from .constants import (
    DATE_FRI_AUG_28,
    DATE_MON_AUG_03,
    DATE_SAT_AUG_29,
    INSTANT_AUG_03,
)
from .test_users import (
    FINANCE_CONTROLLER,
    PRACTICE_PARTNER,
    RESOURCE_MANAGER,
    SALES_LEAD,
)

# =============================================================================
# Tier 1 — atoms
# =============================================================================


def set_clock(api, current_utc: str, headers: Dict[str, str] = None) -> None:
    """PRD §2.5: move the logical clock. Returns nothing; the endpoint's data
    payload is empty."""
    response = api.set_clock(current_utc, headers or RESOURCE_MANAGER)
    validate_success(response, 200)


def bench_run(api, headers: Dict[str, str] = None) -> None:
    """PRD §3.10: the only operation that advances a state machine on the
    strength of the clock alone."""
    response = api.run_bench_run(headers or RESOURCE_MANAGER)
    validate_success(response, 200)


def create_group(api, headers: Dict[str, str] = None, **kwargs) -> Dict[str, Any]:
    response = api.create_practice_group(
        factories.practice_group_payload(**kwargs), headers or PRACTICE_PARTNER
    )
    return validate_success(response, 201)


def create_skill(api, headers: Dict[str, str] = None, **kwargs) -> Dict[str, Any]:
    response = api.create_skill(
        factories.skill_payload(**kwargs), headers or PRACTICE_PARTNER
    )
    return validate_success(response, 201)


def create_consultant(
    api, practice_group_id: str, headers: Dict[str, str] = None, **kwargs
) -> Dict[str, Any]:
    response = api.create_consultant(
        factories.consultant_payload(practice_group_id, **kwargs),
        headers or RESOURCE_MANAGER,
    )
    return validate_success(response, 201)


def create_assertion(
    api,
    consultant_id: str,
    skill_id: str,
    headers: Dict[str, str] = None,
    **kwargs,
) -> Dict[str, Any]:
    response = api.create_skill_assertion(
        factories.skill_assertion_payload(consultant_id, skill_id, **kwargs),
        headers or RESOURCE_MANAGER,
    )
    return validate_success(response, 201)


def create_demand(
    api,
    practice_group_id: str,
    required_skill_id: str,
    headers: Dict[str, str] = None,
    **kwargs,
) -> Dict[str, Any]:
    response = api.create_demand(
        factories.demand_payload(practice_group_id, required_skill_id, **kwargs),
        headers or SALES_LEAD,
    )
    return validate_success(response, 201)


def qualify(api, demand_id: str, headers: Dict[str, str] = None) -> Dict[str, Any]:
    response = api.qualify_demand(demand_id, headers or SALES_LEAD)
    return validate_success(response, 200)


def set_mode(
    api, demand_id: str, staffing_mode: str, headers: Dict[str, str] = None
) -> Dict[str, Any]:
    response = api.set_staffing_mode(
        demand_id, staffing_mode, headers or RESOURCE_MANAGER
    )
    return validate_success(response, 200)


def close_demand(
    api,
    demand_id: str,
    outcome: str,
    headers: Dict[str, str] = None,
    note: Optional[str] = None,
) -> Dict[str, Any]:
    response = api.close_demand(demand_id, outcome, headers or SALES_LEAD, note=note)
    return validate_success(response, 200)


def create_firm(api, headers: Dict[str, str] = None, **kwargs) -> Dict[str, Any]:
    response = api.create_firm(
        factories.firm_payload(**kwargs), headers or PRACTICE_PARTNER
    )
    return validate_success(response, 201)


def create_program(
    api, skill_id: str, headers: Dict[str, str] = None, **kwargs
) -> Dict[str, Any]:
    response = api.create_reskilling_program(
        factories.reskilling_program_payload(skill_id, **kwargs),
        headers or RESOURCE_MANAGER,
    )
    return validate_success(response, 201)


def enrol(
    api, program_id: str, consultant_id: str, headers: Dict[str, str] = None
) -> Dict[str, Any]:
    """PRD §4: enrolment returns 200 because it mutates an existing bench spell
    rather than creating a new resource."""
    response = api.enrol_in_program(
        program_id, consultant_id, headers or RESOURCE_MANAGER
    )
    return validate_success(response, 200)


def complete_program(
    api, program_id: str, headers: Dict[str, str] = None
) -> Dict[str, Any]:
    response = api.complete_program(program_id, headers or RESOURCE_MANAGER)
    return validate_success(response, 200)


# --- reads -------------------------------------------------------------------


def read_group(api, group_id: str, headers: Dict[str, str] = None) -> Dict[str, Any]:
    return validate_success(api.get_practice_group(group_id, headers or PRACTICE_PARTNER))


def read_skill(api, skill_id: str, headers: Dict[str, str] = None) -> Dict[str, Any]:
    return validate_success(api.get_skill(skill_id, headers or PRACTICE_PARTNER))


def read_consultant(api, consultant_id: str, headers: Dict[str, str] = None) -> Dict[str, Any]:
    return validate_success(api.get_consultant(consultant_id, headers or RESOURCE_MANAGER))


def read_demand(api, demand_id: str, headers: Dict[str, str] = None) -> Dict[str, Any]:
    return validate_success(api.get_demand(demand_id, headers or SALES_LEAD))


def read_assignment(api, assignment_id: str, headers: Dict[str, str] = None) -> Dict[str, Any]:
    return validate_success(api.get_assignment(assignment_id, headers or RESOURCE_MANAGER))


def read_spell(api, spell_id: str, headers: Dict[str, str] = None) -> Dict[str, Any]:
    return validate_success(api.get_bench_spell(spell_id, headers or RESOURCE_MANAGER))


def read_program(api, program_id: str, headers: Dict[str, str] = None) -> Dict[str, Any]:
    return validate_success(
        api.get_reskilling_program(program_id, headers or RESOURCE_MANAGER)
    )


def read_firm(api, firm_id: str, headers: Dict[str, str] = None) -> Dict[str, Any]:
    return validate_success(api.get_firm(firm_id, headers or PRACTICE_PARTNER))


def read_placement(api, placement_id: str, headers: Dict[str, str] = None) -> Dict[str, Any]:
    return validate_success(api.get_placement(placement_id, headers or PRACTICE_PARTNER))


def read_approval(api, approval_id: str, headers: Dict[str, str] = None) -> Dict[str, Any]:
    return validate_success(
        api.get_discount_approval(approval_id, headers or FINANCE_CONTROLLER)
    )


def read_period(
    api, consultant_id: str, period_id: str, headers: Dict[str, str] = None
) -> Dict[str, Any]:
    return validate_success(
        api.get_utilization_period(consultant_id, period_id, headers or FINANCE_CONTROLLER)
    )


def read_forecast(api, forecast_id: str, headers: Dict[str, str] = None) -> Dict[str, Any]:
    return validate_success(
        api.get_hiring_forecast(forecast_id, headers or FINANCE_CONTROLLER)
    )


def consultant_version(api, consultant_id: str) -> int:
    """PRD §2.8: POST /assignments carries expected_consultant_version, so the
    caller must re-read the consultant immediately before every proposal."""
    return read_consultant(api, consultant_id)["version"]


def demand_version(api, demand_id: str) -> int:
    """PRD §2.8: POST /discount-approvals carries expected_opportunity_version."""
    return read_demand(api, demand_id)["version"]


def spells_of(api, consultant_id: str, headers: Dict[str, str] = None) -> List[Dict[str, Any]]:
    response = api.list_bench_spells(
        headers or RESOURCE_MANAGER, {"consultant_id": consultant_id}
    )
    return validate_success(response)


def open_spell_of(api, consultant_id: str) -> Dict[str, Any]:
    """The bench spell that is currently open for this consultant."""
    rows = spells_of(api, consultant_id)
    open_rows = [row for row in rows if row["ended_on"] is None]
    assert open_rows, f"consultant {consultant_id} has no open bench spell"
    return open_rows[-1]


def assignments_of_demand(
    api, demand_id: str, headers: Dict[str, str] = None
) -> List[Dict[str, Any]]:
    response = api.list_assignments(
        headers or RESOURCE_MANAGER, {"demand_opportunity_id": demand_id}
    )
    return validate_success(response)


def assertions_of(
    api, consultant_id: str, headers: Dict[str, str] = None, **params
) -> List[Dict[str, Any]]:
    query = {"consultant_id": consultant_id}
    query.update(params)
    response = api.list_skill_assertions(headers or RESOURCE_MANAGER, query)
    return validate_success(response)


# =============================================================================
# Tier 2 — entity hierarchy
# =============================================================================


def base_world(
    api,
    clock: str = INSTANT_AUG_03,
    group_name: str = "Cloud NA",
    geography_code: str = "NA",
    skill_code: str = "CLOUD_ARCH",
    skill_name: str = "Cloud Architecture",
    skill_family: str = "CLOUD",
    **group_kwargs,
) -> Dict[str, Any]:
    """Clock, one practice group and one skill: the floor every other fixture
    stands on."""
    set_clock(api, clock)
    group = create_group(
        api, name=group_name, geography_code=geography_code, **group_kwargs
    )
    skill = create_skill(
        api, code=skill_code, name=skill_name, family=skill_family
    )
    return {"group": group, "skill": skill, "clock": clock}


def add_bench_group(
    api,
    world: Dict[str, Any],
    name: str = "Bench NA",
    geography_code: Optional[str] = None,
) -> Dict[str, Any]:
    """A second, unrelated practice group in the same geography, stored under the
    world key ``bench_group``.

    PRD §2.10: a group's `rollup_bench_ratio` is the summed `bench_headcount` of
    the group and its transitive descendants over the summed `total_headcount` of
    the same set, and the group is `FROZEN` at a ratio of 0.5000 or more. PRD
    §3.2: a hire lands on the bench, so it increments both `total_headcount` and
    `bench_headcount` of the group it is hired into. A group that owns nothing but
    freshly hired consultants therefore sits at a ratio of 1.0000 and is `FROZEN`,
    which PRD §3.5 and §3.6 make a hard refusal for an `INVESTMENT` confirmation
    and for every external-sourcing write.

    Tests whose subject is not posture therefore hire into this second group,
    leaving the demand's own group at a 0.0000 rollup ratio and an `OPEN` posture.
    Nothing in the PRD couples an assignment's consultant to the demand's practice
    group; only the auto-staff eligibility filter of §3.5 does, and callers of that
    filter keep hiring into the demand's group.
    """
    group = create_group(
        api,
        name=name,
        geography_code=geography_code or world["group"]["geography_code"],
    )
    world["bench_group"] = group
    return group


def parent_child_world(
    api,
    clock: str = INSTANT_AUG_03,
    parent_name: str = "Cloud Global",
    child_name: str = "Cloud NA",
    geography_code: str = "NA",
) -> Dict[str, Any]:
    """A two-level practice hierarchy so that rollup_bench_ratio and posture
    propagation have somewhere to propagate to."""
    set_clock(api, clock)
    parent = create_group(api, name=parent_name, geography_code=geography_code)
    child = create_group(
        api,
        name=child_name,
        geography_code=geography_code,
        parent_group_id=parent["id"],
    )
    skill = create_skill(api)
    return {"parent": parent, "child": child, "group": child, "skill": skill}


def hire(
    api,
    world: Dict[str, Any],
    full_name: str = "Ada Byron",
    proficiency_level: Optional[int] = 4,
    group_key: str = "group",
    assertion_kwargs: Optional[Dict[str, Any]] = None,
    **consultant_kwargs,
) -> Dict[str, Any]:
    """Hire a consultant into the world's group and, unless proficiency_level is
    None, record one skill assertion against the world's skill."""
    consultant = create_consultant(
        api,
        world[group_key]["id"],
        full_name=full_name,
        email=factories.unique_email(full_name.split()[0].lower()),
        **consultant_kwargs,
    )
    assertion = None
    if proficiency_level is not None:
        assertion = create_assertion(
            api,
            consultant["id"],
            world["skill"]["id"],
            proficiency_level=proficiency_level,
            **(assertion_kwargs or {}),
        )
    return {"consultant": consultant, "assertion": assertion}


# =============================================================================
# Tier 3 — lifecycle shortcuts
# =============================================================================


def qualified_demand(
    api,
    world: Dict[str, Any],
    staffing_mode: str = "INTERNAL",
    group_key: str = "group",
    **demand_kwargs,
) -> Dict[str, Any]:
    """A demand carried through QUALIFYING -> QUALIFIED and given its staffing
    branch, which PRD §2.9 rung 16 requires before any staffing write."""
    demand = create_demand(
        api, world[group_key]["id"], world["skill"]["id"], **demand_kwargs
    )
    qualify(api, demand["id"])
    if staffing_mode is not None:
        set_mode(api, demand["id"], staffing_mode)
    return read_demand(api, demand["id"])


def propose_assignment(
    api,
    consultant_id: str,
    demand_id: str,
    allocation_pct: float = 100.00,
    start_date: str = DATE_MON_AUG_03,
    end_date: str = DATE_SAT_AUG_29,
    category: str = "BILLABLE",
    expected_consultant_version: Optional[int] = None,
    headers: Dict[str, str] = None,
) -> Dict[str, Any]:
    """Propose one assignment, re-reading the consultant's version first so the
    OCC guard of PRD §2.8 is satisfied."""
    version = (
        expected_consultant_version
        if expected_consultant_version is not None
        else consultant_version(api, consultant_id)
    )
    response = api.create_assignment(
        factories.assignment_payload(
            consultant_id,
            demand_id,
            version,
            allocation_pct=allocation_pct,
            start_date=start_date,
            end_date=end_date,
            category=category,
        ),
        headers or RESOURCE_MANAGER,
    )
    return validate_success(response, 201)


def confirm(api, assignment_id: str, headers: Dict[str, str] = None) -> Dict[str, Any]:
    response = api.confirm_assignment(assignment_id, headers or RESOURCE_MANAGER)
    return validate_success(response, 200)


def release(
    api, assignment_id: str, headers: Dict[str, str] = None, reason: str = "released"
) -> Dict[str, Any]:
    response = api.release_assignment(assignment_id, headers or RESOURCE_MANAGER, reason=reason)
    return validate_success(response, 200)


def cancel(
    api, assignment_id: str, headers: Dict[str, str] = None, reason: str = "cancelled"
) -> Dict[str, Any]:
    response = api.cancel_assignment(assignment_id, headers or RESOURCE_MANAGER, reason=reason)
    return validate_success(response, 200)


def confirmed_assignment(
    api,
    consultant_id: str,
    demand_id: str,
    allocation_pct: float = 100.00,
    start_date: str = DATE_MON_AUG_03,
    end_date: str = DATE_SAT_AUG_29,
    category: str = "BILLABLE",
) -> Dict[str, Any]:
    """Propose then confirm in one step: the state at which an assignment starts
    moving coverage and hours."""
    assignment = propose_assignment(
        api,
        consultant_id,
        demand_id,
        allocation_pct=allocation_pct,
        start_date=start_date,
        end_date=end_date,
        category=category,
    )
    return confirm(api, assignment["id"])


def staffed_world(
    api,
    clock: str = INSTANT_AUG_03,
    allocation_pct: float = 100.00,
    assignment_start: str = DATE_MON_AUG_03,
    assignment_end: str = DATE_SAT_AUG_29,
    category: str = "BILLABLE",
    proficiency_level: int = 4,
    demand_kwargs: Optional[Dict[str, Any]] = None,
    consultant_kwargs: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """One group, one skill, one consultant, one QUALIFIED / INTERNAL demand and
    one CONFIRMED assignment — the recurring spine of the depth cases."""
    world = base_world(api, clock=clock)
    staff = hire(
        api,
        world,
        proficiency_level=proficiency_level,
        **(consultant_kwargs or {}),
    )
    demand = qualified_demand(api, world, **(demand_kwargs or {}))
    assignment = confirmed_assignment(
        api,
        staff["consultant"]["id"],
        demand["id"],
        allocation_pct=allocation_pct,
        start_date=assignment_start,
        end_date=assignment_end,
        category=category,
    )
    world.update(
        {
            "consultant": staff["consultant"],
            "assertion": staff["assertion"],
            "demand": demand,
            "assignment": assignment,
        }
    )
    return world


def create_period(
    api,
    consultant_id: str,
    period_start_on: str = DATE_MON_AUG_03,
    period_end_on: str = DATE_FRI_AUG_28,
    headers: Dict[str, str] = None,
    **kwargs,
) -> Dict[str, Any]:
    response = api.create_utilization_period(
        consultant_id,
        factories.utilization_period_payload(
            period_start_on=period_start_on, period_end_on=period_end_on, **kwargs
        ),
        headers or FINANCE_CONTROLLER,
    )
    return validate_success(response, 201)


def close_period(
    api, consultant_id: str, period_id: str, headers: Dict[str, str] = None
) -> Dict[str, Any]:
    response = api.close_utilization_period(
        consultant_id, period_id, headers or FINANCE_CONTROLLER
    )
    return validate_success(response, 200)


def create_placement(
    api,
    firm_id: str,
    demand_id: str,
    headers: Dict[str, str] = None,
    **kwargs,
) -> Dict[str, Any]:
    response = api.create_placement(
        factories.placement_payload(firm_id, demand_id, **kwargs),
        headers or RESOURCE_MANAGER,
    )
    return validate_success(response, 201)


def approve_placement(
    api, placement_id: str, headers: Dict[str, str] = None
) -> Dict[str, Any]:
    response = api.approve_placement(placement_id, headers or PRACTICE_PARTNER)
    return validate_success(response, 200)


def terminate_placement(
    api, placement_id: str, headers: Dict[str, str] = None, reason: str = "terminated"
) -> Dict[str, Any]:
    response = api.terminate_placement(
        placement_id, headers or PRACTICE_PARTNER, reason=reason
    )
    return validate_success(response, 200)


def approved_placement(
    api, firm_id: str, demand_id: str, **kwargs
) -> Dict[str, Any]:
    placement = create_placement(api, firm_id, demand_id, **kwargs)
    return approve_placement(api, placement["id"])


def request_discount(
    api,
    demand_id: str,
    requested_rate_usd_per_hour: float,
    expected_opportunity_version: Optional[int] = None,
    headers: Dict[str, str] = None,
    **kwargs,
) -> Dict[str, Any]:
    """Request a discount, re-reading the demand's version first so the OCC
    guard of PRD §2.8 is satisfied."""
    version = (
        expected_opportunity_version
        if expected_opportunity_version is not None
        else demand_version(api, demand_id)
    )
    response = api.create_discount_approval(
        factories.discount_approval_payload(
            demand_id, requested_rate_usd_per_hour, version, **kwargs
        ),
        headers or SALES_LEAD,
    )
    return validate_success(response, 201)


def decide_discount(
    api,
    approval_id: str,
    decision: str,
    headers: Dict[str, str] = None,
    decision_note: Optional[str] = None,
) -> Dict[str, Any]:
    response = api.decide_discount_approval(
        approval_id, decision, headers or FINANCE_CONTROLLER, decision_note=decision_note
    )
    return validate_success(response, 200)


def revise_discount(
    api,
    approval_id: str,
    requested_rate_usd_per_hour: float,
    headers: Dict[str, str] = None,
    decision_note: Optional[str] = None,
) -> Dict[str, Any]:
    response = api.revise_discount_approval(
        approval_id,
        requested_rate_usd_per_hour,
        headers or SALES_LEAD,
        decision_note=decision_note,
    )
    return validate_success(response, 200)


def create_forecast(api, headers: Dict[str, str] = None, **kwargs) -> Dict[str, Any]:
    response = api.create_hiring_forecast(
        factories.hiring_forecast_payload(**kwargs), headers or FINANCE_CONTROLLER
    )
    return validate_success(response, 201)


# =============================================================================
# Tier 4 — accumulation and threshold targeting
# =============================================================================


def advance_clock_and_run(api, instant: str) -> None:
    """PRD §2.5 and §3.10: move the clock, then let the checkpoint observe it.
    Moving the clock alone re-derives computed fields but never advances a state
    machine."""
    set_clock(api, instant)
    bench_run(api)


def bench_spell_at_l1(
    api,
    world: Dict[str, Any],
    consultant_id: str,
    escalation_instant: str = "2026-08-17T00:00:00Z",
) -> Dict[str, Any]:
    """Age a never-staffed CONSULTANT's spell past the 14-day L1 threshold of the
    firm-wide CONSULTANT level target."""
    advance_clock_and_run(api, escalation_instant)
    return open_spell_of(api, consultant_id)


def bench_spell_at_l2(
    api,
    world: Dict[str, Any],
    consultant_id: str,
    l1_instant: str = "2026-08-17T00:00:00Z",
    l2_instant: str = "2026-09-02T00:00:00Z",
) -> Dict[str, Any]:
    """Two checkpoints, 14 and 30 bench days in, climb the ladder to
    ESCALATED_L2 with escalation_count 2."""
    advance_clock_and_run(api, l1_instant)
    advance_clock_and_run(api, l2_instant)
    return open_spell_of(api, consultant_id)


def group_at_bench_ratio(
    api,
    total_headcount: int,
    bench_headcount: int,
    clock: str = INSTANT_AUG_03,
    required_fte: Optional[float] = None,
) -> Dict[str, Any]:
    """Build a group whose own_bench_ratio is bench_headcount/total_headcount by
    hiring `total_headcount` consultants and confirming assignments for the ones
    that must not be on the bench.

    Returns the world plus the consultant and assignment lists in creation
    order, so a caller can target CONSTRAINED (>= 0.3000) or FROZEN (>= 0.5000)
    exactly.
    """
    assert 0 <= bench_headcount <= total_headcount
    staffed = total_headcount - bench_headcount
    world = base_world(api, clock=clock)
    consultants = []
    for index in range(total_headcount):
        staff = hire(api, world, full_name=f"Consultant {index + 1}")
        consultants.append(staff["consultant"])
    assignments = []
    if staffed:
        demand = qualified_demand(
            api,
            world,
            required_fte=float(required_fte if required_fte is not None else staffed),
        )
        for consultant in consultants[:staffed]:
            assignments.append(
                confirmed_assignment(api, consultant["id"], demand["id"])
            )
        world["demand"] = demand
    world["consultants"] = consultants
    world["assignments"] = assignments
    world["group"] = read_group(api, world["group"]["id"])
    return world


def demand_with_external_branch(
    api,
    world: Dict[str, Any],
    firm_kwargs: Optional[Dict[str, Any]] = None,
    demand_kwargs: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """A QUALIFIED demand on the EXTERNAL branch plus an APPROVED partner firm."""
    firm = create_firm(api, **(firm_kwargs or {}))
    demand = qualified_demand(
        api, world, staffing_mode="EXTERNAL", **(demand_kwargs or {})
    )
    return {"firm": firm, "demand": demand}


def enrolled_in_cohort(
    api,
    world: Dict[str, Any],
    consultant_id: str,
    program_kwargs: Optional[Dict[str, Any]] = None,
    l1_instant: str = "2026-08-17T00:00:00Z",
) -> Dict[str, Any]:
    """PRD §3.8: a bench spell must already be escalated before it can be
    enrolled, so the ladder is climbed to ESCALATED_L1 first."""
    program = create_program(api, world["skill"]["id"], **(program_kwargs or {}))
    bench_spell_at_l1(api, world, consultant_id, escalation_instant=l1_instant)
    spell = enrol(api, program["id"], consultant_id)
    return {"program": read_program(api, program["id"]), "spell": spell}


# =============================================================================
# Tier 5 — finalization and terminal states
# =============================================================================


def separated_consultant(
    api,
    world: Dict[str, Any],
    consultant_id: str,
    proposer_headers: Dict[str, str] = None,
    decider_headers: Dict[str, str] = None,
    l1_instant: str = "2026-08-17T00:00:00Z",
    l2_instant: str = "2026-09-02T00:00:00Z",
) -> Dict[str, Any]:
    """Drive a spell all the way to the SEPARATED terminal state: ladder to
    ESCALATED_L2, propose, then decide APPROVED under a second X-User-ID as PRD
    §2.11 requires."""
    spell = bench_spell_at_l2(
        api, world, consultant_id, l1_instant=l1_instant, l2_instant=l2_instant
    )
    proposal = validate_success(
        api.propose_separation(
            spell["id"],
            proposer_headers or RESOURCE_MANAGER,
            rationale="no pipeline fit after 30 bench days",
        ),
        200,
    )
    decision = validate_success(
        api.decide_separation(
            spell["id"],
            "APPROVED",
            decider_headers or PRACTICE_PARTNER,
            note="approved at partner review",
        ),
        200,
    )
    return {"spell": decision, "proposal": proposal}


def closed_period(
    api,
    consultant_id: str,
    period_start_on: str = DATE_MON_AUG_03,
    period_end_on: str = DATE_FRI_AUG_28,
    close_instant: str = DATE_SAT_AUG_29 + "T00:00:00Z",
    **kwargs,
) -> Dict[str, Any]:
    """PRD §3.9: a period may only be closed once period_end_on is strictly
    earlier than the clock date, so the clock is advanced past the window."""
    period = create_period(
        api, consultant_id, period_start_on, period_end_on, **kwargs
    )
    set_clock(api, close_instant, FINANCE_CONTROLLER)
    return close_period(api, consultant_id, period["id"])


def auto_approved_discount(api, demand_id: str, requested_rate: float) -> Dict[str, Any]:
    """PRD §3.7 step S7: a NONE-tier request is created already APPROVED with
    decided_by_user_id 'SYSTEM_AUTO' and cascades the rate onto the demand."""
    return request_discount(api, demand_id, requested_rate)
