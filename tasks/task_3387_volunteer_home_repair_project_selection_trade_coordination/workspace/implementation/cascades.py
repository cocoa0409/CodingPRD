"""Compensating cascades (PRD 3.1, 3.2, 3.6, 3.7, 3.9).

Every cascaded child resource is updated independently: it gets its own
updated_at refresh and version increment.
"""
from db import STORES, get_clock
from logic import (
    bump, cycle_ledger, cycle_projects, project_events, project_work_orders,
    project_material_orders, event_enrollments, compute_posture, sync_posture,
    get_project, get_application, ACTIVE_ENROLLMENT_STATES,
    CANCELLABLE_PROJECT_STATES, SUSPENSION_CANCELLABLE_WO,
)


def cancel_event_internal(event, move_project_to_ready=True):
    """Event cancellation: withdraws live enrollments; a cancelled LOCKED
    event returns the host project EVENT_SCHEDULED -> READY when its posture
    is still READY."""
    if event["status"] in ("EXECUTED", "CANCELLED"):
        return
    was_locked = event["status"] == "LOCKED"
    event["status"] = "CANCELLED"
    bump(event)
    for en in event_enrollments(event["id"]):
        if en["status"] in ACTIVE_ENROLLMENT_STATES:
            en["status"] = "WITHDRAWN"
            bump(en)
    if was_locked and move_project_to_ready:
        project = get_project(event["project_id"])
        if (project is not None and project["status"] == "EVENT_SCHEDULED"
                and compute_posture(project) == "READY"):
            project["status"] = "READY"
            bump(project)


def cancel_project(project, reason):
    """Full project-cancellation cascade (PRD 3.9). reason is one of
    FUNDING_WITHDRAWN | STAFF_DECISION | HOMEOWNER_WITHDRAWN."""
    project["status"] = "CANCELLED"
    project["cancellation_reason"] = reason
    project["reserved_balance_cents"] = 0
    bump(project)
    # Non-terminal events cancelled; their live enrollments withdrawn.
    for ev in project_events(project["id"]):
        if ev["status"] in ("DRAFT", "PUBLISHED", "LOCKED"):
            ev["status"] = "CANCELLED"
            bump(ev)
            for en in event_enrollments(ev["id"]):
                if en["status"] in ACTIVE_ENROLLMENT_STATES:
                    en["status"] = "WITHDRAWN"
                    bump(en)
    # Non-terminal work orders cancelled.
    for w in project_work_orders(project["id"]):
        if w["status"] not in ("PAID", "CANCELLED"):
            w["status"] = "CANCELLED"
            w["cancellation_reason"] = "PROJECT_CANCELLED"
            bump(w)
    # In-flight material orders returned (DELIVERED orders stay delivered).
    for m in project_material_orders(project["id"]):
        if m["status"] in ("ORDERED", "STAGED"):
            m["status"] = "RETURNED"
            bump(m)
    # Application outcome.
    app = get_application(project["application_id"])
    if app is not None:
        if reason == "HOMEOWNER_WITHDRAWN":
            app["status"] = "WITHDRAWN"
        else:
            app["status"] = "DEFERRED"
            app["decision_reason"] = reason
        bump(app)


def funding_withdrawal_cascade(cycle_id):
    """PRD 3.1: while reserved_cents > pool_cents - spent_cents, cancel the
    lowest-priority cancellable project (priority_score_snapshot ascending,
    ties broken by created_at descending) until the invariant holds."""
    while True:
        cycle = STORES["funding_cycles"].get(cycle_id)
        if cycle is None:
            return
        led = cycle_ledger(cycle)
        if led["reserved_cents"] <= led["pool_cents"] - led["spent_cents"]:
            return
        candidates = [p for p in cycle_projects(cycle_id)
                      if p["status"] in CANCELLABLE_PROJECT_STATES]
        if not candidates:
            return
        victim = min(candidates,
                     key=lambda p: (p["priority_score_snapshot"], -p["_seq"]))
        cancel_project(victim, "FUNDING_WITHDRAWN")


def cancel_work_orders_for_contractor(contractor_id, reason):
    """Cancels the contractor's early-stage work orders and recomputes the
    posture of each affected project (READY demotes to PLANNING when the
    posture drops; EVENT_SCHEDULED projects stay)."""
    affected = set()
    for w in STORES["work_orders"].values():
        if (w["contractor_id"] == contractor_id
                and w["status"] in SUSPENSION_CANCELLABLE_WO):
            w["status"] = "CANCELLED"
            w["cancellation_reason"] = reason
            bump(w)
            affected.add(w["project_id"])
    for pid in affected:
        project = get_project(pid)
        if project is not None:
            sync_posture(project)


def suspend_contractor(contractor):
    """Manual or automatic (3 strikes) suspension with the 3-link cascade."""
    contractor["status"] = "SUSPENDED"
    bump(contractor)
    cancel_work_orders_for_contractor(contractor["id"], "CONTRACTOR_SUSPENDED")


def terminate_contractor(contractor):
    contractor["status"] = "TERMINATED"
    bump(contractor)
    cancel_work_orders_for_contractor(contractor["id"], "CONTRACTOR_SUSPENDED")


def deactivate_volunteer_cascade(volunteer_id):
    """Withdraws the volunteer's ENROLLED/CONFIRMED enrollments on events in
    PUBLISHED or LOCKED."""
    for en in STORES["enrollments"].values():
        if (en["volunteer_id"] == volunteer_id
                and en["status"] in ("ENROLLED", "CONFIRMED")):
            ev = STORES["events"].get(en["event_id"])
            if ev is not None and ev["status"] in ("PUBLISHED", "LOCKED"):
                en["status"] = "WITHDRAWN"
                bump(en)
