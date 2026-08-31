"""Shared domain services: record bookkeeping, caseload ledger, cadence,
care-plan posture, and the cross-entity cascades."""
from decimal import Decimal

import core
from core import (CADENCE_INTERVAL_DAYS, CADENCE_MULTIPLIER, TIER_POINTS,
                  add_days, clock, db, new_id, next_seq, rhu)
from errors import ApiError


# --------------------------------------------------------------------------
# Record bookkeeping
# --------------------------------------------------------------------------
def base_record(versioned=True):
    now = clock.now()
    rec = {
        "id": new_id(),
        "created_at": now,
        "_seq": next_seq(),
    }
    if versioned:
        rec["updated_at"] = now
        rec["version"] = 1
    return rec


def touch_record(rec):
    """Refresh updated_at and bump version (PRD 2.10)."""
    if "version" in rec:
        rec["updated_at"] = clock.now()
        rec["version"] += 1


def sort_key(rec):
    return (rec["created_at"], rec["_seq"])


def sorted_rows(rows):
    return sorted(rows, key=sort_key)


def sorted_rows_desc(rows):
    return sorted(rows, key=sort_key, reverse=True)


# --------------------------------------------------------------------------
# Lookup helpers (ladder steps 5 and 6)
# --------------------------------------------------------------------------
def _lookup(table, ident, error_id):
    if not isinstance(ident, str):
        raise ApiError(error_id)
    rec = table.get(ident)
    if rec is None:
        raise ApiError(error_id)
    return rec


def get_member(ident):
    return _lookup(db.members, ident, "ERR_MEMBER_NOT_FOUND")


def get_program(ident):
    return _lookup(db.programs, ident, "ERR_PROGRAM_NOT_FOUND")


def get_care_manager(ident):
    return _lookup(db.care_managers, ident, "ERR_CARE_MANAGER_NOT_FOUND")


def get_enrollment(ident):
    return _lookup(db.enrollments, ident, "ERR_ENROLLMENT_NOT_FOUND")


def get_care_plan(ident):
    return _lookup(db.care_plans, ident, "ERR_CARE_PLAN_NOT_FOUND")


def get_goal(ident):
    return _lookup(db.goals, ident, "ERR_GOAL_NOT_FOUND")


def get_intervention(ident):
    return _lookup(db.interventions, ident, "ERR_INTERVENTION_NOT_FOUND")


def get_touch(ident):
    return _lookup(db.touches, ident, "ERR_TOUCH_NOT_FOUND")


def get_social_need(ident):
    return _lookup(db.social_needs, ident, "ERR_SOCIAL_NEED_NOT_FOUND")


def get_community_resource(ident):
    return _lookup(db.community_resources, ident, "ERR_COMMUNITY_RESOURCE_NOT_FOUND")


def get_referral(ident):
    return _lookup(db.referrals, ident, "ERR_REFERRAL_NOT_FOUND")


def get_transition_event(ident):
    return _lookup(db.transition_events, ident, "ERR_TRANSITION_EVENT_NOT_FOUND")


# --------------------------------------------------------------------------
# Graph navigation
# --------------------------------------------------------------------------
def enrollment_plans(enrollment_id):
    return sorted_rows([p for p in db.care_plans.values()
                        if p["enrollment_id"] == enrollment_id])


def active_plan(enrollment_id):
    for plan in enrollment_plans(enrollment_id):
        if plan["status"] == "ACTIVE":
            return plan
    return None


def plan_in_statuses(enrollment_id, statuses):
    for plan in enrollment_plans(enrollment_id):
        if plan["status"] in statuses:
            return plan
    return None


def plan_goals(care_plan_id):
    return sorted_rows([g for g in db.goals.values()
                        if g["care_plan_id"] == care_plan_id])


def goal_interventions(goal_id):
    return sorted_rows([i for i in db.interventions.values()
                        if i["goal_id"] == goal_id])


def plan_of_goal(goal):
    return db.care_plans.get(goal["care_plan_id"])


def enrollment_of_goal(goal):
    plan = plan_of_goal(goal)
    if plan is None:
        return None
    return db.enrollments.get(plan["enrollment_id"])


def program_of_enrollment(enrollment):
    return db.programs.get(enrollment["program_id"])


def program_of_goal(goal):
    enrollment = enrollment_of_goal(goal)
    if enrollment is None:
        return None
    return program_of_enrollment(enrollment)


def enrollment_social_needs(enrollment_id):
    return sorted_rows([n for n in db.social_needs.values()
                        if n["enrollment_id"] == enrollment_id])


def enrollment_touches(enrollment_id):
    return sorted_rows([t for t in db.touches.values()
                        if t["enrollment_id"] == enrollment_id])


def member_events(member_id):
    return sorted_rows([e for e in db.transition_events.values()
                        if e["member_id"] == member_id])


def member_enrollments(member_id):
    return sorted_rows([e for e in db.enrollments.values()
                        if e["member_id"] == member_id])


# --------------------------------------------------------------------------
# Caseload ledger (PRD 2.9)
# --------------------------------------------------------------------------
def acuity_weight(enrollment):
    tier = enrollment.get("risk_tier_at_enrollment")
    cadence = enrollment.get("cadence_tier") or "STANDARD"
    points = TIER_POINTS.get(tier, Decimal("0"))
    return rhu(points * CADENCE_MULTIPLIER[cadence], 1)


def recompute_acuity(enrollment):
    new_weight = acuity_weight(enrollment)
    enrollment["acuity_weight_points"] = new_weight
    return new_weight


def sync_manager(manager):
    """Recompute assigned_caseload_points / capacity_status / active count
    from scratch; bump the manager record when anything actually moved."""
    if manager is None:
        return
    total = Decimal("0")
    active = 0
    for enrollment in db.enrollments.values():
        if enrollment.get("care_manager_id") != manager["id"]:
            continue
        if enrollment["enrollment_status"] in ("PENDING", "ACTIVE"):
            total += enrollment["acuity_weight_points"]
        if enrollment["enrollment_status"] == "ACTIVE":
            active += 1
    total = rhu(total, 1)
    status = "OVER_CAPACITY" if total > manager["capacity_points"] else "OPEN"
    changed = (manager["assigned_caseload_points"] != total
               or manager["capacity_status"] != status
               or manager["active_enrollment_count"] != active)
    manager["assigned_caseload_points"] = total
    manager["capacity_status"] = status
    manager["active_enrollment_count"] = active
    if changed:
        touch_record(manager)


def sync_manager_by_id(manager_id):
    if manager_id:
        sync_manager(db.care_managers.get(manager_id))


# --------------------------------------------------------------------------
# Cadence (touch_cadence_tier_assignment) and next-touch projection
# --------------------------------------------------------------------------
def cadence_tier_for(enrollment):
    if enrollment.get("toc_due_at") is not None:
        return "TOC_INTENSIVE"
    if enrollment.get("engagement_status") == "DISENGAGED":
        return "INTENSIVE"
    if enrollment.get("risk_tier_at_enrollment") == "HIGH":
        return "INTENSIVE"
    return "STANDARD"


def project_next_touch_due_at(enrollment):
    base = enrollment.get("last_reached_touch_at") or enrollment.get("activated_at")
    if base is None:
        return None
    interval = CADENCE_INTERVAL_DAYS[enrollment["cadence_tier"]]
    adj = interval
    if enrollment["consecutive_failed_outreach_count"] >= core.ESCALATION_FAILED_TOUCH_MIN:
        adj = max(core.MIN_INTERVAL_DAYS, interval // 2)
    if (enrollment["engagement_status"] == "ENGAGED"
            and enrollment["consecutive_failed_outreach_count"] == 0):
        adj = min(interval + core.ENGAGED_RELAXATION_DAYS, core.MAX_INTERVAL_DAYS)
    toc_due = enrollment.get("toc_due_at")
    if toc_due is not None and clock.now() < toc_due:
        adj = min(adj, core.TOC_CONTACT_INTERVAL_DAYS)
    return add_days(base, adj)


def apply_cadence_change(enrollment, new_tier):
    """Set the cadence tier; when it moves, resync weight and the owning ledger."""
    if enrollment["cadence_tier"] == new_tier:
        return False
    enrollment["cadence_tier"] = new_tier
    recompute_acuity(enrollment)
    sync_manager_by_id(enrollment.get("care_manager_id"))
    return True


# --------------------------------------------------------------------------
# Care plan compliance posture (PRD 3.5)
# --------------------------------------------------------------------------
def posture_for(plan):
    if plan["status"] == "SUSPENDED":
        return "DEFICIENT"
    if plan["at_risk_goal_count"] >= 1:
        return "AT_RISK"
    return "COMPLIANT"


def refresh_posture(plan):
    plan["compliance_posture"] = posture_for(plan)


# --------------------------------------------------------------------------
# Cascades
# --------------------------------------------------------------------------
def cancel_scheduled_touches(enrollment_id, reason, only_manager_id=None):
    for touch in enrollment_touches(enrollment_id):
        if touch["status"] != "SCHEDULED":
            continue
        if only_manager_id is not None and touch["care_manager_id"] != only_manager_id:
            continue
        touch["status"] = "CANCELLED"
        touch["cancel_reason"] = reason
        touch_record(touch)


def close_plan_cascade(plan):
    """Plan -> CLOSED, goals OPEN/AT_RISK -> CLOSED_UNMET, their PLANNED
    interventions -> VOIDED with void_reason PLAN_CLOSED."""
    now = clock.now()
    plan["status"] = "CLOSED"
    plan["closed_at"] = now
    program = None
    enrollment = db.enrollments.get(plan["enrollment_id"])
    if enrollment is not None:
        program = program_of_enrollment(enrollment)
    for goal in plan_goals(plan["id"]):
        if goal["status"] not in ("OPEN", "AT_RISK"):
            continue
        was_at_risk = goal["status"] == "AT_RISK"
        goal["status"] = "CLOSED_UNMET"
        if was_at_risk:
            goal["barrier_flag"] = False
            plan["at_risk_goal_count"] = max(0, plan["at_risk_goal_count"] - 1)
        for intervention in goal_interventions(goal["id"]):
            if intervention["status"] != "PLANNED":
                continue
            intervention["status"] = "VOIDED"
            intervention["void_reason"] = "PLAN_CLOSED"
            touch_record(intervention)
            goal["planned_intervention_count"] = max(
                0, goal["planned_intervention_count"] - 1)
            if program is not None:
                program["committed_staff_minutes"] -= intervention["staff_minutes"]
                touch_record(program)
        touch_record(goal)
    refresh_posture(plan)
    touch_record(plan)


def suspend_plan(enrollment_id):
    plan = active_plan(enrollment_id)
    if plan is None:
        return
    plan["status"] = "SUSPENDED"
    refresh_posture(plan)
    touch_record(plan)


def resume_plan(enrollment_id):
    for plan in enrollment_plans(enrollment_id):
        if plan["status"] == "SUSPENDED":
            plan["status"] = "ACTIVE"
            refresh_posture(plan)
            touch_record(plan)
            return


def toc_escalate(enrollment, event):
    """Transitions-of-care escalation cascade (PRD 3.7)."""
    program = program_of_enrollment(enrollment)
    hours = program["toc_outreach_hours"] if program else 48
    enrollment["toc_due_at"] = core.add_hours(event["occurred_at"], hours)
    enrollment["pre_toc_cadence_tier"] = enrollment["cadence_tier"]
    enrollment["cadence_tier"] = "TOC_INTENSIVE"
    enrollment["cadence_tier_snapshot"] = "TOC_INTENSIVE"
    recompute_acuity(enrollment)
    sync_manager_by_id(enrollment.get("care_manager_id"))
    enrollment["next_touch_due_at"] = project_next_touch_due_at(enrollment)
    touch_record(enrollment)


def toc_satisfy(enrollment):
    """Clear an open transitions-of-care obligation and restore the cadence."""
    restored = enrollment.get("pre_toc_cadence_tier")
    enrollment["toc_due_at"] = None
    if restored is None:
        restored = cadence_tier_for(enrollment)
    enrollment["cadence_tier"] = restored
    enrollment["cadence_tier_snapshot"] = restored
    enrollment["pre_toc_cadence_tier"] = None
    recompute_acuity(enrollment)
    sync_manager_by_id(enrollment.get("care_manager_id"))


def escalate_social_need(need):
    """Need -> UNMET_ESCALATED plus the goal-barrier cascade (PRD 3.8)."""
    need["status"] = "UNMET_ESCALATED"
    need["escalation_count"] += 1
    touch_record(need)
    plan = active_plan(need["enrollment_id"])
    if plan is None:
        return
    changed = False
    for goal in plan_goals(plan["id"]):
        if goal["domain"] != need["domain"] or goal["status"] != "OPEN":
            continue
        goal["status"] = "AT_RISK"
        goal["barrier_flag"] = True
        touch_record(goal)
        plan["at_risk_goal_count"] += 1
        changed = True
    if changed:
        refresh_posture(plan)
        touch_record(plan)


def resolve_social_need(need):
    """Need -> RESOLVED plus the reverse barrier cascade (PRD 3.8)."""
    need["status"] = "RESOLVED"
    need["resolved_at"] = clock.now()
    touch_record(need)
    still_escalated = any(
        other["id"] != need["id"]
        and other["domain"] == need["domain"]
        and other["status"] == "UNMET_ESCALATED"
        for other in enrollment_social_needs(need["enrollment_id"]))
    if still_escalated:
        return
    for plan in enrollment_plans(need["enrollment_id"]):
        changed = False
        for goal in plan_goals(plan["id"]):
            if goal["domain"] != need["domain"] or goal["status"] != "AT_RISK":
                continue
            goal["status"] = "OPEN"
            goal["barrier_flag"] = False
            touch_record(goal)
            plan["at_risk_goal_count"] = max(0, plan["at_risk_goal_count"] - 1)
            changed = True
        if changed:
            refresh_posture(plan)
            touch_record(plan)


def maybe_complete_goal(goal):
    """Derived goal completion after an intervention completion (PRD 3.5)."""
    if goal["planned_intervention_count"] != 0:
        return
    if goal["completed_intervention_count"] < 1:
        return
    if goal["status"] == "OPEN":
        goal["status"] = "MET"
    elif goal["status"] == "AT_RISK":
        goal["status"] = "MET"
        goal["barrier_flag"] = False
        plan = plan_of_goal(goal)
        if plan is not None:
            plan["at_risk_goal_count"] = max(0, plan["at_risk_goal_count"] - 1)
            refresh_posture(plan)
            touch_record(plan)


def end_enrollment(enrollment, reason, graduate):
    """Shared ending path for graduation and disenrollment (PRD 3.4)."""
    now = clock.now()
    was_active = enrollment["enrollment_status"] == "ACTIVE"
    enrollment["enrollment_status"] = "GRADUATED" if graduate else "DISENROLLED"
    enrollment["disenrolled_at"] = now
    enrollment["disenrollment_reason"] = reason
    if was_active:
        cancel_scheduled_touches(enrollment["id"], "ENROLLMENT_ENDED")
        wanted = ("ACTIVE",) if graduate else ("ACTIVE", "SUSPENDED")
        plan = plan_in_statuses(enrollment["id"], wanted)
        if plan is not None:
            close_plan_cascade(plan)
    enrollment["next_touch_due_at"] = None
    enrollment["toc_due_at"] = None
    touch_record(enrollment)
    sync_manager_by_id(enrollment.get("care_manager_id"))
