"""Shared lookups, ledger mechanics and the cross-aggregate cascades of PRD 2.8."""

import calc
import store
from errors import ApiError

FREEZE_STATUSES = ("SUBMITTED", "TEAM_ASSIGNED", "PLANNED", "IN_ASSESSMENT", "NC_OPEN")
APPLICATION_TERMINAL = ("GRANTED", "WITHDRAWN")
TEAM_BUILD_STATUSES = ("SUBMITTED", "TEAM_ASSIGNED")
PLANNING_STATUSES = ("SUBMITTED", "TEAM_ASSIGNED")
FINDING_STATUSES = ("SUBMITTED", "TEAM_ASSIGNED", "PLANNED", "IN_ASSESSMENT", "NC_OPEN")
RECUSAL_STATUSES = ("SUBMITTED", "TEAM_ASSIGNED", "PLANNED", "IN_ASSESSMENT", "NC_OPEN")

NOT_FOUND = {
    "schemes": "ERR_SCHEME_NOT_FOUND",
    "assessors": "ERR_ASSESSOR_NOT_FOUND",
    "qualifications": "ERR_QUALIFICATION_NOT_FOUND",
    "declarations": "ERR_DECLARATION_NOT_FOUND",
    "organizations": "ERR_ORGANIZATION_NOT_FOUND",
    "applications": "ERR_APPLICATION_NOT_FOUND",
    "assignments": "ERR_TEAM_ASSIGNMENT_NOT_FOUND",
    "plans": "ERR_PLAN_NOT_FOUND",
    "sessions": "ERR_WITNESS_SESSION_NOT_FOUND",
    "nonconformities": "ERR_NONCONFORMITY_NOT_FOUND",
    "decisions": "ERR_DECISION_NOT_FOUND",
    "scopes": "ERR_SCOPE_NOT_FOUND",
    "complaints": "ERR_COMPLAINT_NOT_FOUND",
}


def find(kind, row_id):
    record = store.get(kind, row_id)
    if record is None:
        raise ApiError(NOT_FOUND[kind])
    return record


def scheme_snapshot(scheme):
    """The rule values of the revision a cycle pins (PRD 2.5)."""
    return {
        "rule_revision": scheme["rule_revision"],
        "witness_min_count": scheme["witness_min_count"],
        "qualification_points_required": scheme["_points_required"],
        "complexity_multiplier": scheme["_complexity_multiplier"],
        "surveillance_interval_days": scheme["surveillance_interval_days"],
        "reassessment_interval_days": scheme["reassessment_interval_days"],
        "critical_nc_close_days": scheme["critical_nc_close_days"],
        "major_nc_close_days": scheme["major_nc_close_days"],
        "minor_nc_close_days": scheme["minor_nc_close_days"],
        "unannounced_authority": scheme["unannounced_authority"],
        "remote_assessment_allowed": scheme["remote_assessment_allowed"],
    }


def pinned(application):
    return application["_pinned"]


# ------------------------------------------------------------------ collections
def plans_of(application_id):
    return [p for p in store.rows("plans") if p["application_id"] == application_id]


def sessions_of_plan(plan_id):
    return [s for s in store.rows("sessions") if s["plan_id"] == plan_id]


def sessions_of_application(application_id):
    plan_ids = {p["id"] for p in plans_of(application_id)}
    return [s for s in store.rows("sessions") if s["plan_id"] in plan_ids]


def approved_plan(application_id):
    for plan in store.ordered(plans_of(application_id)):
        if plan["status"] == "APPROVED":
            return plan
    return None


def assignments_of(application_id):
    return [a for a in store.rows("assignments") if a["application_id"] == application_id]


def qualifications_of(assessor_id):
    return [q for q in store.rows("qualifications") if q["assessor_id"] == assessor_id]


def decisions_of(application_id):
    return [d for d in store.rows("decisions") if d["application_id"] == application_id]


def scopes_of(organization_id):
    return [s for s in store.rows("scopes") if s["organization_id"] == organization_id]


def application_of_plan(plan):
    return store.get("applications", plan["application_id"])


def application_of_session(session):
    plan = store.get("plans", session["plan_id"])
    return application_of_plan(plan) if plan else None


def organization_of_session(session):
    application = application_of_session(session)
    return application["organization_id"] if application else None


def confirmed_assignment(application_id, assessor_id, role_types=None):
    for assignment in assignments_of(application_id):
        if assignment["assessor_id"] != assessor_id:
            continue
        if assignment["status"] != "CONFIRMED":
            continue
        if role_types is not None and assignment["role_type"] not in role_types:
            continue
        return assignment
    return None


def any_assignment(application_id, assessor_id, statuses=None):
    for assignment in assignments_of(application_id):
        if assignment["assessor_id"] != assessor_id:
            continue
        if statuses is not None and assignment["status"] not in statuses:
            continue
        return assignment
    return None


def has_confirmed_lead(application_id, exclude_assignment_id=None):
    for assignment in assignments_of(application_id):
        if exclude_assignment_id is not None and assignment["id"] == exclude_assignment_id:
            continue
        if assignment["status"] == "CONFIRMED" and assignment["role_type"] == "LEAD_ASSESSOR":
            return True
    return False


def voted_on_application(application_id, assessor_id):
    for record in decisions_of(application_id):
        for ballot in record["votes"]:
            if ballot["voter_assessor_id"] == assessor_id:
                return True
    return False


def live_granted_qualification(assessor_id, scheme_id, role_type, expire_lazily=False):
    """Return a GRANTED, unexpired qualification, expiring stale ones when asked."""
    from validators import parse_date

    today = store.clock_date()
    for qualification in store.ordered(qualifications_of(assessor_id)):
        if qualification["scheme_id"] != scheme_id:
            continue
        if qualification["role_type"] != role_type:
            continue
        if qualification["status"] != "GRANTED":
            continue
        expires_on = qualification.get("expires_on")
        if expires_on and parse_date(expires_on, "expires_on") < today:
            if expire_lazily:
                qualification["status"] = "EXPIRED"
                store.touch(qualification)
                assessor = store.get("assessors", assessor_id)
                if assessor and assessor["granted_qualification_count"] > 0:
                    assessor["granted_qualification_count"] -= 1
                    store.touch(assessor)
            continue
        return qualification
    return None


# ------------------------------------------------------------- assessor ledger
def commit_witness_days(assessor, days):
    assessor["committed_witness_days"] += days
    assessor["available_witness_days"] = (
        assessor["annual_witness_capacity_days"] - assessor["committed_witness_days"]
    )
    store.touch(assessor)


def release_witness_days(assessor, days):
    assessor["committed_witness_days"] -= days
    if assessor["committed_witness_days"] < 0:
        assessor["committed_witness_days"] = 0
    assessor["available_witness_days"] = (
        assessor["annual_witness_capacity_days"] - assessor["committed_witness_days"]
    )
    store.touch(assessor)


def abort_session(session, note):
    session["status"] = "ABORTED"
    session["evidence_note"] = note
    store.touch(session)
    assessor = store.get("assessors", session["assessor_id"])
    if assessor is not None:
        release_witness_days(assessor, session["day_count"])


# ------------------------------------------------------------------- cascades
def recount_active_scopes(organization):
    active = sum(1 for s in scopes_of(organization["id"]) if s["status"] == "ACTIVE")
    if organization["active_scope_count"] != active:
        organization["active_scope_count"] = active
        store.touch(organization)
    return active


def recompute_risk_at_decision(organization, application_id):
    score = calc.risk_at_decision(application_id, organization["id"], store.clock_date())
    organization["risk_score"] = score
    store.touch(organization)
    return score


def recompute_risk_at_surveillance_planning(organization, granting_application_id,
                                            surveillance_application_id):
    """PRD 3.7/3.9: opening a follow-on cycle is one of the four moments the
    organization's risk score is recomputed, under the at-surveillance-planning
    variant."""
    score = calc.risk_at_surveillance_planning(
        granting_application_id, surveillance_application_id, organization,
        store.clock_date())
    organization["risk_score"] = score
    store.touch(organization)
    return score


def freeze_cycles(organization_id, exclude_application_id=None):
    """Scope-suspension collateral: freeze in-flight cycles, cancel drafts, abort slots."""
    for application in store.ordered(store.rows("applications")):
        if application["organization_id"] != organization_id:
            continue
        if exclude_application_id is not None and application["id"] == exclude_application_id:
            continue
        if application["status"] not in FREEZE_STATUSES:
            continue
        store.set_fields(application, suspension_blocked=True)
        for plan in store.ordered(plans_of(application["id"])):
            if plan["status"] == "DRAFT":
                plan["status"] = "CANCELLED"
                store.touch(plan)
            for session in store.ordered(sessions_of_plan(plan["id"])):
                if session["status"] == "SCHEDULED":
                    abort_session(session, "scope suspended")


def suspend_scope(scope, reason, exclude_application_id=None):
    scope["status"] = "SUSPENDED"
    scope["suspension_reason"] = reason
    scope["mra_notified"] = True
    store.touch(scope)
    organization = store.get("organizations", scope["organization_id"])
    if organization is not None:
        organization["status"] = "SUSPENDED"
        organization["suspension_reason"] = reason
        store.touch(organization)
        recount_active_scopes(organization)
        freeze_cycles(organization["id"], exclude_application_id)


def create_decision_record(application):
    """Create the VOTING record for the cycle's current round, once."""
    for record in decisions_of(application["id"]):
        if record["round"] == application["decision_round"] and record["status"] == "VOTING":
            return record
    record = store.insert("decisions", {
        "application_id": application["id"],
        "round": application["decision_round"],
        "status": "VOTING",
        "votes": [],
        "vote_count": 0,
        "outcome": None,
        "granted_scope_lines": None,
        "decided_on": None,
        "decided_by_user_id": None,
    })
    organization = store.get("organizations", application["organization_id"])
    if organization is not None:
        recompute_risk_at_decision(organization, application["id"])
    return record


def teardown_assessor(assessor, reason):
    """Suspension/withdrawal cascade over team assignments and witnessing slots."""
    recused_leads = []
    for assignment in store.ordered(store.rows("assignments")):
        if assignment["assessor_id"] != assessor["id"]:
            continue
        if assignment["status"] == "PROPOSED":
            assignment["status"] = "REJECTED"
            assignment["recusal_reason"] = reason
            store.touch(assignment)
        elif assignment["status"] == "CONFIRMED":
            assignment["status"] = "RECUSED"
            assignment["recusal_reason"] = reason
            store.touch(assignment)
            if assignment["role_type"] == "LEAD_ASSESSOR":
                recused_leads.append(assignment)
    for assignment in recused_leads:
        application = store.get("applications", assignment["application_id"])
        if application is None:
            continue
        if application["status"] == "TEAM_ASSIGNED" and not has_confirmed_lead(application["id"]):
            application["status"] = "SUBMITTED"
            store.touch(application)
    for session in store.ordered(store.rows("sessions")):
        if session["assessor_id"] != assessor["id"]:
            continue
        if session["status"] == "SCHEDULED":
            abort_session(session, reason)


def refresh_completed_witness_count(application):
    completed = sum(1 for s in sessions_of_application(application["id"])
                    if s["status"] == "COMPLETED")
    application["completed_witness_session_count"] = completed
    store.touch(application)
    return completed


def derive_scope_schedule(scope, risk_score, granting_pinned):
    from validators import parse_date

    schedule = calc.surveillance_schedule(
        risk_score,
        parse_date(scope["effective_from"], "effective_from"),
        granting_pinned["surveillance_interval_days"],
        granting_pinned["reassessment_interval_days"],
    )
    return schedule
