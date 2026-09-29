"""Early intervention: the sweep, alerts, plans and monitoring check-ins."""
from decimal import Decimal

from flask import Blueprint, g

import calc
import svc
from core import (
    ApiError,
    add_days,
    body,
    db,
    dump,
    endpoint,
    f_enum,
    f_enum_list,
    f_int,
    f_str,
    new_row,
    paginate,
    q_enum,
    q_str,
    respond_object,
    sort_created,
    touch,
)

bp = Blueprint("eis", __name__)


# ---------------------------------------------------------------------------
# The sweep
# ---------------------------------------------------------------------------
@bp.post("/eis-runs")
@endpoint("IACommander", "SystemAdmin")
def run_sweep():
    payload = body()
    officer_id = f_str(payload, "officer_id", required=False)
    # tier 5 -- body reference existence
    target = svc.need_officer(officer_id) if officer_id is not None else None
    # tier 10 -- referential business rules
    if target is not None:
        escalated = any(
            a["officer_id"] == target["id"] and a["status"] == "ESCALATED"
            for a in db.alerts.values()
        )
        if escalated:
            raise ApiError("ERR_ALERT_ALREADY_OPEN")

    db.run_sequence += 1
    run_sequence = db.run_sequence
    if target is not None:
        officers = [target]
    else:
        officers = [
            o
            for o in sort_created(list(db.officers.values()))
            if o["employment_status"] == "ACTIVE"
        ]

    alerts_created = 0
    alerts_promoted = 0
    for officer in officers:
        profile = svc.recompute_officer_eis(officer)
        alert = svc.open_alert_for(officer["id"])
        if alert is None:
            if profile["alert_level"] != "NONE":
                svc.create_alert(officer, profile, "EIS_RUN", run_sequence=run_sequence)
                alerts_created += 1
            continue
        alert["composite_score"] = profile["composite_score"]
        alert["score_variant"] = profile["variant"]
        alert["alert_level"] = profile["alert_level"]
        alert["breached_indicators"] = list(profile["breached_indicators"])
        alert["run_sequence"] = run_sequence
        if alert["status"] == "OPEN" and profile["alert_level"] in ("ALERT", "CRITICAL"):
            alert["status"] = "PLAN_REQUIRED"
            alert["review_due_at"] = add_days(db.clock, calc.ALERT_REVIEW_DAYS)
            alerts_promoted += 1
        touch(alert)

    checkins_missed = 0
    for checkin in sort_created(list(db.checkins.values())):
        if checkin["status"] != "PENDING":
            continue
        plan = db.plans.get(checkin["plan_id"])
        if plan is None or plan["status"] != "ACTIVE":
            continue
        if checkin["due_at"] < db.clock:
            checkin["status"] = "MISSED"
            touch(checkin)
            checkins_missed += 1

    disclosures_expired = 0
    for disclosure in sort_created(list(db.disclosures.values())):
        if disclosure["status"] != "ACTIVE" or disclosure["permanent_retention"]:
            continue
        if db.clock >= disclosure["retention_until"]:
            disclosure["status"] = "EXPIRED"
            touch(disclosure)
            disclosures_expired += 1
            officer = db.officers.get(disclosure["officer_id"])
            if officer is not None:
                svc.recompute_credibility_flag(officer)

    return respond_object(
        {
            "run_sequence": run_sequence,
            "evaluated_officer_count": len(officers),
            "alerts_created": alerts_created,
            "alerts_promoted": alerts_promoted,
            "checkins_missed": checkins_missed,
            "disclosures_expired": disclosures_expired,
        }
    )


# ---------------------------------------------------------------------------
# Alerts
# ---------------------------------------------------------------------------
@bp.get("/eis-alerts/<alert_id>")
@endpoint("IACommander", "Supervisor", "SystemAdmin", "RecordsCustodian")
def read_alert(alert_id):
    return respond_object(dump(svc.need_alert(alert_id)))


@bp.get("/eis-alerts")
@endpoint("IACommander", "Supervisor", "SystemAdmin", "RecordsCustodian")
def list_alerts():
    officer_id = q_str("officer_id")
    status = q_enum("status", calc.ALERT_STATUSES)
    alert_level = q_enum("alert_level", calc.OFFICER_ALERT_LEVELS)
    score_variant = q_enum("score_variant", calc.SCORE_VARIANTS)
    rows = sort_created(list(db.alerts.values()))
    if officer_id is not None:
        rows = [r for r in rows if r["officer_id"] == officer_id]
    if status is not None:
        rows = [r for r in rows if r["status"] == status]
    if alert_level is not None:
        rows = [r for r in rows if r["alert_level"] == alert_level]
    if score_variant is not None:
        rows = [r for r in rows if r["score_variant"] == score_variant]
    return paginate(rows)


@bp.post("/eis-alerts/<alert_id>/dismiss")
@endpoint("IACommander")
def dismiss_alert(alert_id):
    alert = svc.need_alert(alert_id)
    payload = body()
    dismissal_reason = f_str(payload, "dismissal_reason")
    # tier 8 -- state legality
    if alert["status"] not in ("OPEN", "PLAN_REQUIRED"):
        raise ApiError("ERR_ALERT_STATE_INVALID")
    # tier 10 -- referential business rules
    if alert["plan_count"] != 0:
        raise ApiError("ERR_PLAN_EXISTS")

    alert["status"] = "DISMISSED"
    alert["dismissal_reason"] = dismissal_reason
    touch(alert)
    officer = db.officers.get(alert["officer_id"])
    if officer is not None:
        officer["open_alert_count"] = max(0, officer["open_alert_count"] - 1)
        touch(officer)
    return respond_object(dump(alert))


# ---------------------------------------------------------------------------
# Intervention plans
# ---------------------------------------------------------------------------
@bp.post("/eis-alerts/<alert_id>/intervention-plans")
@endpoint("Supervisor", "IACommander")
def create_plan(alert_id):
    alert = svc.need_alert(alert_id)
    payload = body()
    # tier 4 -- schema
    expected_version = f_int(payload, "expected_alert_version")
    supervisor_officer_id = f_str(payload, "supervisor_officer_id")
    required_checkin_count = f_int(
        payload, "required_checkin_count", minimum=2, maximum=6
    )
    duration_days = f_int(
        payload, "duration_days", choices=calc.DURATION_DAYS_CHOICES
    )
    interventions = f_enum_list(payload, "interventions", calc.INTERVENTION_TYPES)
    # tier 5 -- body reference existence
    svc.need_officer(supervisor_officer_id)
    # tier 7 -- version pinning
    if expected_version != alert["version"]:
        raise ApiError("ERR_STALE_ALERT_VERSION")
    # tier 8 -- state legality
    if alert["status"] not in ("PLAN_REQUIRED", "ESCALATED"):
        raise ApiError("ERR_ALERT_STATE_INVALID")

    plan = new_row(
        "InterventionPlan",
        alert_id=alert["id"],
        officer_id=alert["officer_id"],
        supervisor_officer_id=supervisor_officer_id,
        required_checkin_count=required_checkin_count,
        duration_days=duration_days,
        interventions=list(interventions),
        status="DRAFT",
        activated_at=None,
        end_date=None,
        completed_checkin_count=0,
        on_time_checkin_count=0,
        concern_count=0,
        compliance_score=None,
        closed_at=None,
    )
    db.plans[plan["id"]] = plan
    alert["plan_count"] += 1
    if alert["status"] == "ESCALATED":
        alert["status"] = "PLAN_REQUIRED"
    touch(alert)
    return respond_object(dump(plan), 201)


@bp.get("/intervention-plans/<plan_id>")
@endpoint("IACommander", "Supervisor", "SystemAdmin", "RecordsCustodian")
def read_plan(plan_id):
    return respond_object(dump(svc.need_plan(plan_id)))


@bp.get("/intervention-plans")
@endpoint("IACommander", "Supervisor", "SystemAdmin", "RecordsCustodian")
def list_plans():
    alert_id = q_str("alert_id")
    officer_id = q_str("officer_id")
    supervisor_officer_id = q_str("supervisor_officer_id")
    status = q_enum("status", calc.PLAN_STATUSES)
    rows = sort_created(list(db.plans.values()))
    if alert_id is not None:
        rows = [r for r in rows if r["alert_id"] == alert_id]
    if officer_id is not None:
        rows = [r for r in rows if r["officer_id"] == officer_id]
    if supervisor_officer_id is not None:
        rows = [
            r for r in rows if r["supervisor_officer_id"] == supervisor_officer_id
        ]
    if status is not None:
        rows = [r for r in rows if r["status"] == status]
    return paginate(rows)


@bp.post("/intervention-plans/<plan_id>/activate")
@endpoint("Supervisor")
def activate_plan(plan_id):
    plan = svc.need_plan(plan_id)
    payload = body()
    f_str(payload, "activation_note", required=False)
    # tier 6 -- resource-level ownership
    if g.role == "Supervisor" and g.user_id != plan["supervisor_officer_id"]:
        raise ApiError("ERR_NOT_PLAN_SUPERVISOR")
    # tier 8 -- state legality
    if plan["status"] != "DRAFT":
        raise ApiError("ERR_PLAN_STATE_INVALID")
    alert = svc.need_alert(plan["alert_id"])
    if alert["status"] != "PLAN_REQUIRED":
        raise ApiError("ERR_ALERT_STATE_INVALID")

    plan["status"] = "ACTIVE"
    plan["activated_at"] = db.clock
    plan["end_date"] = add_days(db.clock, plan["duration_days"])
    touch(plan)
    due_dates = calc.checkin_due_dates(
        plan["activated_at"], plan["duration_days"], plan["required_checkin_count"]
    )
    for index, due_at in enumerate(due_dates, start=1):
        checkin = new_row(
            "MonitoringCheckIn",
            plan_id=plan["id"],
            sequence_index=index,
            due_at=due_at,
            completed_at=None,
            outcome="PENDING",
            status="PENDING",
            on_time=None,
            notes=None,
        )
        db.checkins[checkin["id"]] = checkin
    alert["status"] = "PLAN_ACTIVE"
    touch(alert)
    return respond_object(dump(plan))


# ---------------------------------------------------------------------------
# Monitoring check-ins
# ---------------------------------------------------------------------------
@bp.get("/intervention-plans/<plan_id>/check-ins")
@endpoint("IACommander", "Supervisor", "SystemAdmin", "RecordsCustodian")
def list_checkins(plan_id):
    svc.need_plan(plan_id)
    status = q_enum("status", calc.CHECKIN_STATUSES)
    outcome = q_enum("outcome", calc.CHECKIN_OUTCOMES)
    rows = svc.checkins_of(plan_id)
    if status is not None:
        rows = [r for r in rows if r["status"] == status]
    if outcome is not None:
        rows = [r for r in rows if r["outcome"] == outcome]
    return paginate(rows)


@bp.post("/check-ins/<checkin_id>/complete")
@endpoint("Supervisor")
def complete_checkin(checkin_id):
    checkin = svc.need_checkin(checkin_id)
    payload = body()
    outcome = f_enum(payload, "outcome", calc.CHECKIN_COMPLETE_OUTCOMES)
    notes = f_str(payload, "notes", required=False)
    plan = svc.need_plan(checkin["plan_id"])
    # tier 6 -- resource-level ownership
    if g.role == "Supervisor" and g.user_id != plan["supervisor_officer_id"]:
        raise ApiError("ERR_NOT_PLAN_SUPERVISOR")
    # tier 8 -- state legality
    if checkin["status"] != "PENDING" or plan["status"] != "ACTIVE":
        raise ApiError("ERR_CHECKIN_NOT_PENDING")

    on_time = db.clock <= checkin["due_at"]
    checkin["status"] = "COMPLETED"
    checkin["outcome"] = outcome
    checkin["completed_at"] = db.clock
    checkin["on_time"] = on_time
    if notes is not None:
        checkin["notes"] = notes
    touch(checkin)
    plan["completed_checkin_count"] += 1
    if on_time:
        plan["on_time_checkin_count"] += 1
    if outcome == "CONCERN":
        plan["concern_count"] += 1
    plan["compliance_score"] = calc.compliance_score(
        plan["on_time_checkin_count"],
        plan["required_checkin_count"],
        plan["concern_count"],
    )
    touch(plan)
    return respond_object(dump(checkin))


@bp.post("/intervention-plans/<plan_id>/close")
@endpoint("Supervisor", "IACommander")
def close_plan(plan_id):
    plan = svc.need_plan(plan_id)
    payload = body()
    f_str(payload, "closing_note", required=False)
    # tier 6 -- resource-level ownership
    if g.role == "Supervisor" and g.user_id != plan["supervisor_officer_id"]:
        raise ApiError("ERR_NOT_PLAN_SUPERVISOR")
    # tier 8 -- state legality
    if plan["status"] != "ACTIVE":
        raise ApiError("ERR_PLAN_STATE_INVALID")
    # tier 10 -- referential business rules
    if any(c["status"] == "PENDING" for c in svc.checkins_of(plan["id"])):
        raise ApiError("ERR_PENDING_CHECKINS")

    score = calc.compliance_score(
        plan["on_time_checkin_count"],
        plan["required_checkin_count"],
        plan["concern_count"],
    )
    plan["compliance_score"] = score
    plan["closed_at"] = db.clock
    activated_at = plan["activated_at"]
    other_alert = any(
        a["officer_id"] == plan["officer_id"]
        and a["id"] != plan["alert_id"]
        and activated_at is not None
        and activated_at <= a["created_at"] <= db.clock
        for a in db.alerts.values()
    )
    success = score >= calc.PLAN_SUCCESS_SCORE and not other_alert
    alert = db.alerts.get(plan["alert_id"])
    officer = db.officers.get(plan["officer_id"])
    if success:
        plan["status"] = "CLOSED_SUCCESS"
        touch(plan)
        if alert is not None:
            alert["status"] = "CLOSED_SUCCESS"
            touch(alert)
        if officer is not None:
            officer["open_alert_count"] = max(0, officer["open_alert_count"] - 1)
            touch(officer)
        return respond_object(dump(plan))

    plan["status"] = "ESCALATED"
    touch(plan)
    if alert is not None:
        alert["status"] = "ESCALATED"
        touch(alert)
    if officer is not None:
        officer["intervention_escalation_count"] += 1
        officer["eis_alert_level"] = calc.raise_band(officer["eis_alert_level"])
        touch(officer)
    return respond_object(dump(plan))
