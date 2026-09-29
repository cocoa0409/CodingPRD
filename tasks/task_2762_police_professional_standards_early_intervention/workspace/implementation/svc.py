"""Domain services: lookups, ledgers, cascades, serializers."""
from decimal import Decimal

import calc
from core import (
    ApiError,
    add_days,
    db,
    dump,
    fmt_dt,
    new_row,
    sort_created,
    touch,
)


# ---------------------------------------------------------------------------
# Lookups (tier 3 path existence / tier 5 body reference existence)
# ---------------------------------------------------------------------------
def need(collection, row_id, error_id):
    row = collection.get(row_id)
    if row is None:
        raise ApiError(error_id)
    return row


def need_unit(unit_id):
    return need(db.units, unit_id, "ERR_UNIT_NOT_FOUND")


def need_room(room_id):
    return need(db.rooms, room_id, "ERR_ROOM_NOT_FOUND")


def need_officer(officer_id):
    return need(db.officers, officer_id, "ERR_OFFICER_NOT_FOUND")


def need_complaint(complaint_id):
    return need(db.complaints, complaint_id, "ERR_COMPLAINT_NOT_FOUND")


def need_allegation(allegation_id):
    return need(db.allegations, allegation_id, "ERR_ALLEGATION_NOT_FOUND")


def need_investigation(investigation_id):
    return need(db.investigations, investigation_id, "ERR_INVESTIGATION_NOT_FOUND")


def need_session(session_id):
    return need(db.sessions, session_id, "ERR_SESSION_NOT_FOUND")


def need_discipline(discipline_id):
    return need(db.disciplines, discipline_id, "ERR_DISCIPLINE_NOT_FOUND")


def need_appeal(appeal_id):
    return need(db.appeals, appeal_id, "ERR_APPEAL_NOT_FOUND")


def need_reinstatement(reinstatement_id):
    return need(db.reinstatements, reinstatement_id, "ERR_REINSTATEMENT_NOT_FOUND")


def need_alert(alert_id):
    return need(db.alerts, alert_id, "ERR_ALERT_NOT_FOUND")


def need_plan(plan_id):
    return need(db.plans, plan_id, "ERR_PLAN_NOT_FOUND")


def need_checkin(checkin_id):
    return need(db.checkins, checkin_id, "ERR_CHECKIN_NOT_FOUND")


def need_disclosure(disclosure_id):
    return need(db.disclosures, disclosure_id, "ERR_DISCLOSURE_NOT_FOUND")


# ---------------------------------------------------------------------------
# Relationship helpers
# ---------------------------------------------------------------------------
def allegations_of(complaint_id):
    return sort_created(
        [a for a in db.allegations.values() if a["complaint_id"] == complaint_id]
    )


def investigation_of(complaint_id):
    rows = [
        i for i in db.investigations.values() if i["complaint_id"] == complaint_id
    ]
    return sort_created(rows)[0] if rows else None


def sessions_of(investigation_id):
    return sort_created(
        [s for s in db.sessions.values() if s["investigation_id"] == investigation_id]
    )


def checkins_of(plan_id):
    rows = [c for c in db.checkins.values() if c["plan_id"] == plan_id]
    rows.sort(key=lambda c: (c["sequence_index"], c["_seq"]))
    return rows


def plans_of(alert_id):
    return sort_created([p for p in db.plans.values() if p["alert_id"] == alert_id])


def appeals_of(discipline_id):
    return sort_created(
        [a for a in db.appeals.values() if a["discipline_id"] == discipline_id]
    )


def reinstatements_of(appeal_id):
    return sort_created(
        [r for r in db.reinstatements.values() if r["appeal_id"] == appeal_id]
    )


def disclosures_of_allegation(allegation_id):
    return sort_created(
        [
            d
            for d in db.disclosures.values()
            if d["source_allegation_id"] == allegation_id
        ]
    )


def open_alert_for(officer_id):
    rows = [
        a
        for a in db.alerts.values()
        if a["officer_id"] == officer_id and a["status"] in calc.ALERT_OPEN_STATUSES
    ]
    return sort_created(rows)[0] if rows else None


# ---------------------------------------------------------------------------
# Ledgers and cascades
# ---------------------------------------------------------------------------
def recompute_officer_eis(officer):
    """Rescores the officer under the rolling variant and records the result."""
    profile = calc.rolling_profile(officer)
    officer["eis_score"] = profile["composite_score"]
    officer["eis_alert_level"] = profile["alert_level"]
    touch(officer)
    return profile


def recompute_credibility_flag(officer):
    active = any(
        d["officer_id"] == officer["id"] and d["status"] == "ACTIVE"
        for d in db.disclosures.values()
    )
    officer["credibility_disclosure_active"] = active
    touch(officer)
    return active


def append_activity_event(officer_id, event_type, severity_code, occurred_at,
                          source_reference=None, system_generated=False):
    event = new_row(
        "OfficerActivityEvent",
        audited=False,
        officer_id=officer_id,
        event_type=event_type,
        severity_code=severity_code,
        occurred_at=occurred_at,
        source_reference=source_reference,
        base_weight=calc.EVENT_BASE_WEIGHTS[event_type]
        * calc.SEVERITY_MULTIPLIERS[severity_code],
        weekday_index=occurred_at.weekday(),
        system_generated=system_generated,
    )
    db.events[event["id"]] = event
    return event


def create_alert(officer, profile, trigger_source, run_sequence=None):
    level = profile["alert_level"]
    status = "PLAN_REQUIRED" if level in ("ALERT", "CRITICAL") else "OPEN"
    alert = new_row(
        "EarlyInterventionAlert",
        officer_id=officer["id"],
        trigger_source=trigger_source,
        composite_score=profile["composite_score"],
        score_variant=profile["variant"],
        alert_level=level,
        breached_indicators=list(profile["breached_indicators"]),
        status=status,
        review_due_at=add_days(db.clock, calc.ALERT_REVIEW_DAYS),
        dismissal_reason=None,
        run_sequence=run_sequence,
        plan_count=0,
    )
    db.alerts[alert["id"]] = alert
    officer["open_alert_count"] += 1
    touch(officer)
    return alert


def release_investigator(investigation):
    """Drops the caseload the investigation currently occupies."""
    assignee_id = investigation.get("assigned_investigator_officer_id")
    if not assignee_id:
        return None
    assignee = db.officers.get(assignee_id)
    if assignee is None:
        return None
    assignee["open_case_load"] = max(0, assignee["open_case_load"] - 1)
    touch(assignee)
    return assignee


def void_investigation(investigation, cancel_sessions):
    was_open = investigation["status"] in calc.INVESTIGATION_OPEN_STATUSES
    investigation["status"] = "VOIDED"
    investigation["closed_at"] = db.clock
    touch(investigation)
    if cancel_sessions:
        for session in sessions_of(investigation["id"]):
            if session["status"] in ("SCHEDULED", "POSTPONED"):
                session["status"] = "CANCELLED"
                touch(session)
    if was_open:
        release_investigator(investigation)


def recompute_sustained_count(complaint):
    count = sum(
        1
        for a in allegations_of(complaint["id"])
        if a["disposition"] == "SUSTAINED"
    )
    complaint["sustained_allegation_count"] = count
    return count


def refresh_investigation_window(investigation, complaint):
    statutory_days, required_cert, due_at = calc.investigation_window(
        complaint["classification"], complaint["received_at"], investigation["tolled_days"]
    )
    investigation["statutory_days"] = statutory_days
    investigation["required_certification_level"] = required_cert
    investigation["due_at"] = due_at
    investigation["overdue"] = calc.is_overdue(investigation)


# ---------------------------------------------------------------------------
# Serializers
# ---------------------------------------------------------------------------
def dump_investigation(investigation):
    return dump(investigation, {"overdue": calc.is_overdue(investigation)})


def dump_profile(officer, profile):
    return {
        "officer_id": officer["id"],
        "variant": profile["variant"],
        "window_start": fmt_dt(profile["window_start"]),
        "window_end": fmt_dt(profile["window_end"]),
        "event_count": profile["event_count"],
        "weighted_total": float(calc.rhu(profile["weighted_total"], 2)),
        "composite_score": float(profile["composite_score"]),
        "alert_level": profile["alert_level"],
        "breached_indicators": list(profile["breached_indicators"]),
        "peer_pool_size": profile["peer_pool_size"],
        "peer_mean": float(calc.rhu(profile["peer_mean"], 2)),
    }
