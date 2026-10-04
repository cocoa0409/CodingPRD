"""Cascading side effects (PRD 3.5/3.6/3.7) and the logical-clock time sweep
(PRD 2.5). The sweep is the only writer of Credential LAPSED/EXPIRED,
ImprovementPlan OVERDUE and PDEvent COMPLETED transitions."""

from datetime import timedelta

from store import (
    db,
    new_id,
    now_date,
    now_dt,
    now_iso,
    stamp_new,
    touch,
    active_catalog,
    parse_date,
    parse_datetime,
    add_months,
)

IN_FLIGHT_APPLICATION_STATES = ("DRAFT", "UNDER_REVIEW", "RETURNED", "SUSPENDED")
OPEN_PLAN_STATES = ("OPEN", "OVERDUE", "SUBMITTED")


def apply_standing_transition(school, to_standing):
    """Execute a school standing transition's side effects (PRD 3.7):
    suspend/resume/deny applications, recompute directory visibility (derived
    on read), and increment School.version. The caller has already validated
    that the transition is permitted."""
    old = school["standing"]
    school["standing"] = to_standing
    touch(school)
    apps = [a for a in db.applications.values() if a["school_id"] == school["id"]]
    if to_standing in ("PROBATION", "SUSPENDED") and old == "GOOD_STANDING":
        # Leaving GOOD_STANDING suspends each UNDER_REVIEW application.
        for a in apps:
            if a["status"] == "UNDER_REVIEW":
                a["status"] = "SUSPENDED"
                touch(a)
    elif to_standing in ("PROBATION", "SUSPENDED"):
        # Idempotent suspension (already-suspended applications stay).
        for a in apps:
            if a["status"] == "UNDER_REVIEW":
                a["status"] = "SUSPENDED"
                touch(a)
    if to_standing == "GOOD_STANDING":
        # Returning to GOOD_STANDING resumes SUSPENDED applications.
        for a in apps:
            if a["status"] == "SUSPENDED":
                a["status"] = "UNDER_REVIEW"
                touch(a)
    if to_standing == "REVOKED":
        # Revocation denies every still-actionable application.
        for a in apps:
            if a["status"] in IN_FLIGHT_APPLICATION_STATES:
                a["status"] = "DENIED"
                a["decided_at"] = now_iso()
                touch(a)


def auto_create_plan(school_id, visit_id, required_actions):
    """Auto-create an ImprovementPlan (PRD 3.5 revocation cascade and PRD 3.6
    visit-report path). due_date = current logical date + ACTIVE catalog's
    plan_response_days. Plan auto-creation never bumps School.version."""
    cat = active_catalog()
    days = int(cat["plan_response_days"]) if cat is not None else 0
    plan = {
        "id": new_id(),
        "school_id": school_id,
        "visit_id": visit_id,
        "required_actions": list(required_actions),
        "due_date": (now_date() + timedelta(days=days)).isoformat(),
        "status": "OPEN",
        "response_notes": None,
        "submitted_at": None,
        "verified_at": None,
    }
    stamp_new(plan)
    db.plans[plan["id"]] = plan
    return plan


def run_time_sweep():
    """PRD 2.5: run on every clock advance, in the documented family order."""
    today = now_date()
    now = now_dt()
    cat = active_catalog()

    # Credentials: ACTIVE -> LAPSED past the expiry date; LAPSED -> EXPIRED
    # past the expiry date extended by the ACTIVE catalog's grace months.
    for cred in list(db.credentials.values()):
        if cred["status"] == "ACTIVE":
            exp = parse_datetime(cred["expires_at"])
            if exp is not None and today > exp.date():
                cred["status"] = "LAPSED"
                touch(cred)
    for cred in list(db.credentials.values()):
        if cred["status"] == "LAPSED" and cat is not None:
            exp = parse_datetime(cred["expires_at"])
            if exp is None:
                continue
            grace_end = add_months(exp.date(), int(cat["renewal_grace_months"]))
            if today > grace_end:
                cred["status"] = "EXPIRED"
                touch(cred)

    # Improvement plans: OPEN -> OVERDUE past due_date, firing the standing
    # cascade on the owning school.
    for plan in list(db.plans.values()):
        if plan["status"] == "OPEN":
            due = parse_date(plan["due_date"])
            if due is not None and today > due:
                plan["status"] = "OVERDUE"
                touch(plan)
                school = db.schools.get(plan["school_id"])
                if school is not None:
                    if school["standing"] == "GOOD_STANDING":
                        apply_standing_transition(school, "PROBATION")
                    elif school["standing"] == "PROBATION":
                        apply_standing_transition(school, "SUSPENDED")
                    # SUSPENDED or REVOKED schools do not move further.

    # PD events: SCHEDULED -> COMPLETED once now is strictly past end_at.
    for ev in list(db.pd_events.values()):
        if ev["status"] == "SCHEDULED":
            end = parse_datetime(ev["end_at"])
            if end is not None and now > end:
                ev["status"] = "COMPLETED"
                touch(ev)
