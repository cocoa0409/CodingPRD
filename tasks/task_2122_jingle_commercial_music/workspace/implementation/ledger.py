"""The engagement budget ledger and its posture (PRD 2.7).

budget_cents == committed_cents + available_cents + spent_cents after every
single request, with no drift.
"""

import db

BUDGET_CONSTRAINED_PCT = 25


def project_calls(project_id):
    return [c for c in db.session_calls.values() if c["project_id"] == project_id]


def sweep_order(calls):
    """scheduled_start_utc ASC, tie-break created_at ASC (PRD 2.7)."""
    return sorted(calls, key=lambda c: (c["_start_dt"], c["created_at"], c["_seq"]))


def _suspend_sweep(project):
    for call in sweep_order(project_calls(project["id"])):
        if call["status"] == "SCHEDULED":
            call["status"] = "SUSPENDED_BUDGET"
            db.touch(call)


def _resume_sweep(project):
    for call in sweep_order(project_calls(project["id"])):
        if call["status"] == "SUSPENDED_BUDGET":
            call["status"] = "SCHEDULED"
            db.touch(call)


def derive_posture(project):
    if project["status"] == "ON_HOLD":
        return "FROZEN"
    if project["available_cents"] * 100 < BUDGET_CONSTRAINED_PCT * project["budget_cents"]:
        return "CONSTRAINED"
    return "HEALTHY"


def recompute_posture(project):
    """Recompute the posture and run the session-call sweep when it changes."""
    previous = project["budget_posture"]
    current = derive_posture(project)
    if current == previous:
        return False
    project["budget_posture"] = current
    if previous == "HEALTHY" and current in ("CONSTRAINED", "FROZEN"):
        _suspend_sweep(project)
    elif current == "HEALTHY" and previous in ("CONSTRAINED", "FROZEN"):
        _resume_sweep(project)
    return True


def apply_hold(project):
    """Freezing captures the status, forces FROZEN and suspends SCHEDULED calls."""
    project["status_before_hold"] = project["status"]
    project["status"] = "ON_HOLD"
    project["budget_posture"] = "FROZEN"
    _suspend_sweep(project)


def apply_resume(project):
    project["status"] = project["status_before_hold"]
    project["status_before_hold"] = None
    recompute_posture(project)


def reserve(project, amount):
    """available -> committed."""
    project["available_cents"] -= amount
    project["committed_cents"] += amount


def release(project, amount):
    """committed -> available."""
    project["committed_cents"] -= amount
    project["available_cents"] += amount


def settle(project, amount):
    """committed -> spent."""
    project["committed_cents"] -= amount
    project["spent_cents"] += amount


def settle_partial(project, committed_amount, spent_amount):
    """committed -> spent + available (the completion / inside-window split)."""
    project["committed_cents"] -= committed_amount
    project["spent_cents"] += spent_amount
    project["available_cents"] += committed_amount - spent_amount
