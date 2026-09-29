"""Composite setup builders for the awareness program API.

The server is relaunched against an empty database before every individual test,
so nothing here may assume pre-existing rows: each builder constructs its
preconditions from scratch through declared endpoints only.

Every builder uses the lenient ``get_success_data`` so a setup failure surfaces
as a readable AssertionError instead of a KeyError deep inside a test.
"""

from __future__ import annotations

from datetime import timedelta
from typing import Dict, List, Optional

from prd_bench_local_runner.testing import get_success_data

from . import factories
from .assertions import parse_instant
from .constants import (
    CLOCK_EPOCH,
    EVENT_CLICK,
    EVENT_REPORT,
    SOURCE_LANDING_PAGE,
    SOURCE_REPORT_BUTTON,
    TIER_1,
)
from .test_users import (
    ADMIN,
    ANALYST,
    APPROVER,
    AUTHOR,
    make_learner_headers,
    make_manager_headers,
)


# --------------------------------------------------------------------------- #
# Instant arithmetic                                                          #
# --------------------------------------------------------------------------- #


def instant(base: str, *, days: int = 0, hours: int = 0, minutes: int = 0,
            seconds: int = 0) -> str:
    """Shift an ISO-8601 instant by whole units and render it back in Z form."""
    moment = parse_instant(base) + timedelta(
        days=days, hours=hours, minutes=minutes, seconds=seconds
    )
    return moment.strftime("%Y-%m-%dT%H:%M:%SZ")


# --------------------------------------------------------------------------- #
# Clock                                                                       #
# --------------------------------------------------------------------------- #


def set_clock(api, to_iso8601: str, headers: Optional[dict] = None) -> dict:
    """Move the logical clock and return the clock payload."""
    return get_success_data(api.set_clock(to_iso8601, headers or ADMIN))


def reset_clock(api) -> dict:
    """Park the logical clock at the declared start instant."""
    return set_clock(api, CLOCK_EPOCH)


# --------------------------------------------------------------------------- #
# Employees                                                                   #
# --------------------------------------------------------------------------- #


def register_employee(api, **overrides) -> dict:
    """Register one employee and return the stored row."""
    return get_success_data(
        api.create_employee(factories.employee_payload(**overrides), ADMIN)
    )


def register_manager(api, **overrides) -> dict:
    """Register an employee whose role_code is MANAGER."""
    return get_success_data(
        api.create_employee(factories.manager_payload(**overrides), ADMIN)
    )


def register_manager_and_report(api, *, department: str = "IT",
                                report_role_code: str = "IT_ADMIN",
                                report_hire_date: str = "2019-01-01",
                                manager_hire_date: str = "2011-01-01") -> Dict[str, dict]:
    """Register a manager plus one direct report pointing at that manager."""
    manager = register_manager(api, department=department, hire_date=manager_hire_date)
    report = register_employee(
        api,
        full_name="Riley Report",
        department=department,
        role_code=report_role_code,
        hire_date=report_hire_date,
        manager_id=manager["id"],
    )
    return {"manager": manager, "report": report}


def read_employee(api, employee_id: str, headers: Optional[dict] = None) -> dict:
    return get_success_data(api.get_employee(employee_id, headers or ADMIN))


def offboard(api, employee_id: str) -> dict:
    return get_success_data(api.offboard_employee(employee_id, ADMIN))


# --------------------------------------------------------------------------- #
# Modules                                                                     #
# --------------------------------------------------------------------------- #


def create_module(api, **overrides) -> dict:
    """Create a DRAFT training module."""
    return get_success_data(api.create_module(factories.module_payload(**overrides), ADMIN))


def create_published_module(api, **overrides) -> dict:
    """Create a module and publish it, returning the PUBLISHED row."""
    module = create_module(api, **overrides)
    return get_success_data(api.publish_module(module["id"], ADMIN))


def create_retired_module(api, **overrides) -> dict:
    """Create, publish and then retire a module."""
    module = create_published_module(api, **overrides)
    return get_success_data(api.retire_module(module["id"], ADMIN))


# --------------------------------------------------------------------------- #
# Assignments                                                                 #
# --------------------------------------------------------------------------- #


def assign_module(api, employee: dict, module: dict, *,
                  assignment_reason: str = "ANNUAL", **overrides) -> dict:
    """Assign a published module to an employee using that employee's current version."""
    fresh = read_employee(api, employee["id"])
    payload = factories.assignment_payload(
        employee["id"], module["id"], fresh["version"],
        assignment_reason=assignment_reason, **overrides
    )
    return get_success_data(api.create_assignment(payload, ADMIN))


def read_assignment(api, assignment_id: str, headers: Optional[dict] = None) -> dict:
    return get_success_data(api.get_assignment(assignment_id, headers or ADMIN))


def assigned_employee_with_module(api, *, assignment_reason: str = "ANNUAL",
                                  module_overrides: Optional[dict] = None,
                                  employee_overrides: Optional[dict] = None) -> Dict[str, dict]:
    """One employee, one published module and one fresh assignment between them."""
    employee = register_employee(api, **(employee_overrides or {}))
    module = create_published_module(api, **(module_overrides or {}))
    assignment = assign_module(api, employee, module, assignment_reason=assignment_reason)
    return {"employee": employee, "module": module, "assignment": assignment}


def managed_assignment(api, *, assignment_reason: str = "REMEDIAL",
                       module_overrides: Optional[dict] = None) -> Dict[str, dict]:
    """A manager, a direct report, a published module and the report's assignment."""
    pair = register_manager_and_report(api)
    module = create_published_module(api, **(module_overrides or {}))
    assignment = assign_module(
        api, pair["report"], module, assignment_reason=assignment_reason
    )
    return {
        "manager": pair["manager"],
        "employee": pair["report"],
        "module": module,
        "assignment": assignment,
        "manager_headers": make_manager_headers(pair["manager"]["id"]),
        "learner_headers": make_learner_headers(pair["report"]["id"]),
    }


def complete_assignment(api, assignment: dict, employee: dict, *, score_pct: int = 100) -> dict:
    """Drive an assignment through start and a passing submit."""
    learner = make_learner_headers(employee["id"])
    get_success_data(api.start_assignment(assignment["id"], learner))
    return get_success_data(
        api.submit_assignment(assignment["id"], {"score_pct": score_pct}, learner)
    )


# --------------------------------------------------------------------------- #
# Sweeps                                                                      #
# --------------------------------------------------------------------------- #


def run_sweep(api) -> dict:
    """Run one compliance sweep at the current logical clock."""
    return get_success_data(api.run_compliance_sweep(ADMIN))


def sweep_at(api, clock_instant: str) -> dict:
    """Move the clock to an instant and run one sweep there."""
    set_clock(api, clock_instant)
    return run_sweep(api)


def escalated_to_rung(api, *, rung: int, assignment_reason: str = "REMEDIAL") -> Dict[str, object]:
    """A managed assignment driven by one sweep to the requested escalation rung.

    The REMEDIAL base window is seven whole days, so an assignment created at the
    clock epoch falls due on 2026-08-08T00:00:00Z; the sweep instant below is
    chosen so the floored overdue-day count lands on the requested rung.
    """
    days_overdue = {1: 1, 2: 7, 3: 14}[rung]
    ctx = managed_assignment(api, assignment_reason=assignment_reason)
    due_at = ctx["assignment"]["due_at"]
    sweep = sweep_at(api, instant(due_at, days=days_overdue))
    ctx["sweep"] = sweep
    ctx["assignment"] = read_assignment(api, ctx["assignment"]["id"])
    ctx["employee"] = read_employee(api, ctx["employee"]["id"])
    return ctx


def list_notices_for(api, assignment_id: str, **filters) -> List[dict]:
    params = {"assignment_id": assignment_id}
    params.update(filters)
    return get_success_data(api.list_notices(params, ADMIN))


def list_consequences_for(api, employee_id: str, **filters) -> List[dict]:
    params = {"employee_id": employee_id}
    params.update(filters)
    return get_success_data(api.list_access_consequences(params, ADMIN))


# --------------------------------------------------------------------------- #
# Templates and campaigns                                                     #
# --------------------------------------------------------------------------- #


def create_template(api, headers: Optional[dict] = None, **overrides) -> dict:
    """Create a DRAFT pretext template."""
    return get_success_data(
        api.create_template(factories.template_payload(**overrides), headers or AUTHOR)
    )


def approved_template(api, **overrides) -> dict:
    """Create a template and approve it for campaign use."""
    template = create_template(api, **overrides)
    return get_success_data(api.approve_template_for_use(template["id"], APPROVER))


def create_campaign(api, template_id: str, headers: Optional[dict] = None, **overrides) -> dict:
    """Create a DRAFT campaign owned by the acting author."""
    return get_success_data(
        api.create_campaign(
            factories.campaign_payload(template_id, **overrides), headers or AUTHOR
        )
    )


def approved_campaign(api, *, template: Optional[dict] = None,
                      author_headers: Optional[dict] = None,
                      approver_headers: Optional[dict] = None,
                      template_overrides: Optional[dict] = None,
                      **campaign_overrides) -> Dict[str, dict]:
    """A template approved for use plus a campaign carried to APPROVED."""
    author = author_headers or AUTHOR
    approver = approver_headers or APPROVER
    tpl = template or approved_template(api, **(template_overrides or {}))
    campaign = create_campaign(api, tpl["id"], author, **campaign_overrides)
    get_success_data(api.submit_campaign_for_review(campaign["id"], author))
    approved = get_success_data(api.approve_campaign(campaign["id"], approver))
    return {"template": tpl, "campaign": approved}


def scheduled_campaign(api, *, scheduled_send_at: str,
                       template: Optional[dict] = None,
                       author_headers: Optional[dict] = None,
                       template_overrides: Optional[dict] = None,
                       **campaign_overrides) -> Dict[str, dict]:
    """A campaign carried all the way to SCHEDULED at the requested instant."""
    author = author_headers or AUTHOR
    ctx = approved_campaign(
        api, template=template, author_headers=author,
        template_overrides=template_overrides, **campaign_overrides
    )
    scheduled = get_success_data(
        api.schedule_campaign(
            ctx["campaign"]["id"],
            factories.schedule_payload(scheduled_send_at, ctx["campaign"]["version"]),
            author,
        )
    )
    ctx["campaign"] = scheduled
    return ctx


def running_campaign(api, *, scheduled_send_at: str,
                     template: Optional[dict] = None,
                     author_headers: Optional[dict] = None,
                     template_overrides: Optional[dict] = None,
                     **campaign_overrides) -> Dict[str, object]:
    """A campaign scheduled, then launched once the clock reaches the send instant."""
    ctx = scheduled_campaign(
        api, scheduled_send_at=scheduled_send_at, template=template,
        author_headers=author_headers, template_overrides=template_overrides,
        **campaign_overrides
    )
    set_clock(api, scheduled_send_at)
    ctx["campaign"] = get_success_data(api.launch_campaign(ctx["campaign"]["id"], ADMIN))
    ctx["deliveries"] = list_deliveries(api, campaign_id=ctx["campaign"]["id"])
    return ctx


def list_deliveries(api, **filters) -> List[dict]:
    return get_success_data(api.list_deliveries(filters, ADMIN))


def delivery_for(api, campaign_id: str, employee_id: str) -> dict:
    rows = list_deliveries(api, campaign_id=campaign_id, employee_id=employee_id)
    assert rows, f"no delivery for employee {employee_id} in campaign {campaign_id}"
    return rows[0]


def delivered_simulation(api, *, employee: Optional[dict] = None,
                         department: str = "ENGINEERING",
                         hire_date: str = "2014-02-02",
                         difficulty_tier: str = TIER_1,
                         credential_capture_enabled: bool = False,
                         scheduled_send_at: str = "2026-08-02T09:00:00Z",
                         name: str = "Awareness Wave") -> Dict[str, object]:
    """One employee, one RUNNING single-member campaign, one DELIVERED delivery."""
    target = employee or register_employee(
        api, department=department, role_code="ENGINEER", hire_date=hire_date
    )
    ctx = running_campaign(
        api,
        scheduled_send_at=scheduled_send_at,
        name=name,
        difficulty_tier=difficulty_tier,
        target_departments=[target["department"]],
        template_overrides={
            "difficulty_tier": difficulty_tier,
            "credential_capture_enabled": credential_capture_enabled,
            "theme_tags": ["CURIOSITY"],
        },
    )
    ctx["employee"] = target
    ctx["delivery"] = delivery_for(api, ctx["campaign"]["id"], target["id"])
    return ctx


# --------------------------------------------------------------------------- #
# Interactions                                                                #
# --------------------------------------------------------------------------- #


def append_event(api, delivery_id: str, occurred_at: str, *, event_type: str = EVENT_CLICK,
                 source: str = SOURCE_LANDING_PAGE, advance_clock: bool = True) -> dict:
    """Append one interaction event, moving the clock forward to cover it first."""
    if advance_clock:
        set_clock(api, occurred_at)
    return get_success_data(
        api.append_interaction(
            delivery_id,
            factories.interaction_payload(occurred_at, event_type=event_type, source=source),
            ADMIN,
        )
    )


def click(api, delivery_id: str, occurred_at: str, **kwargs) -> dict:
    return append_event(api, delivery_id, occurred_at, event_type=EVENT_CLICK,
                        source=SOURCE_LANDING_PAGE, **kwargs)


def report(api, delivery_id: str, occurred_at: str, **kwargs) -> dict:
    return append_event(api, delivery_id, occurred_at, event_type=EVENT_REPORT,
                        source=SOURCE_REPORT_BUTTON, **kwargs)


def read_delivery(api, delivery_id: str) -> dict:
    return get_success_data(api.get_delivery(delivery_id, ADMIN))


def close_campaign(api, campaign_id: str, *, debrief_note: str = "Wave closed; debrief sent.") -> dict:
    return get_success_data(
        api.close_campaign(campaign_id, {"debrief_note": debrief_note}, ADMIN)
    )


def repeat_clicker_at_tier_two(api, *, department: str = "SALES",
                               hire_date: str = "2016-08-08") -> Dict[str, object]:
    """One employee failing two separate simulations, which opens an intervention.

    Two distinct failure deliveries put the employee on repeat_clicker_tier 2,
    the threshold at which the contract opens a repeat-clicker intervention.
    """
    employee = register_employee(
        api, department=department, role_code="IC", hire_date=hire_date
    )
    template = approved_template(
        api, name="Repeat Probe Template", theme_tags=["CURIOSITY"]
    )
    first = running_campaign(
        api, scheduled_send_at="2026-08-02T09:00:00Z", template=template,
        name="Repeat Wave 1", target_departments=[department],
    )
    d1 = delivery_for(api, first["campaign"]["id"], employee["id"])
    click(api, d1["id"], "2026-08-02T09:30:00Z")
    second = running_campaign(
        api, scheduled_send_at="2026-08-08T09:00:00Z", template=template,
        name="Repeat Wave 2", target_departments=[department],
    )
    d2 = delivery_for(api, second["campaign"]["id"], employee["id"])
    click(api, d2["id"], "2026-08-08T10:00:00Z")
    interventions = get_success_data(
        api.list_interventions({"employee_id": employee["id"]}, ADMIN)
    )
    return {
        "employee": read_employee(api, employee["id"]),
        "template": template,
        "first_campaign": first["campaign"],
        "second_campaign": second["campaign"],
        "first_delivery": d1,
        "second_delivery": d2,
        "interventions": interventions,
        "intervention": interventions[0] if interventions else None,
    }


# --------------------------------------------------------------------------- #
# Communication windows and incidents                                         #
# --------------------------------------------------------------------------- #


def declare_window(api, start_at: str, end_at: str, **overrides) -> dict:
    return get_success_data(
        api.create_communication_window(
            factories.communication_window_payload(start_at, end_at, **overrides), ADMIN
        )
    )


def record_incident(api, **overrides) -> dict:
    return get_success_data(
        api.create_incident(factories.incident_payload(**overrides), ANALYST)
    )
