"""Routes: early alerts and retention outreach."""

from datetime import timedelta

from flask import Blueprint

from auth import require_roles
from domain import (
    MIN_DAYS_BETWEEN_OUTREACH,
    decimal_of,
    lazy_expire_outreach,
    ser_alert,
    ser_outreach,
)
from errors import raise_err
from response import ok_list, ok_object
from store import STORE, CLOCK, bump, new_entity, now_ts
from validate import get_body, is_int, is_num, paginate, req_enum, req_str

bp = Blueprint("advising", __name__)

LIST_ROLES = ("SystemAdmin", "RegistrarAdmin", "Advisor")
ALERT_STATUSES = ("OPEN", "ACKNOWLEDGED", "INTERVENTION", "RESOLVED", "ESCALATED")
OUTREACH_STATUSES = ("QUEUED", "SENT", "RESPONDED", "REENROLLED", "EXPIRED")


# ---------------------------------------------------------------------------
# Early alerts
# ---------------------------------------------------------------------------

@bp.post("/api/enrollments/<eid>/early-alerts")
def create_alert(eid):
    require_roles("SystemAdmin")
    enrollment = STORE.enrollments.get(eid)
    if enrollment is None:
        raise_err("ERR_NOT_FOUND", "enrollment not found")
    body = get_body()
    trigger = req_enum(body, "trigger_type", ("GRADE_THRESHOLD", "LATE_SUBMISSION"))
    grade = body.get("observed_grade_percent")
    days_late = body.get("days_late")
    if grade is not None and not is_num(grade):
        raise_err("ERR_INVALID_REQUEST", "observed_grade_percent must be a number")
    if days_late is not None and not is_int(days_late):
        raise_err("ERR_INVALID_REQUEST", "days_late must be an integer")

    if trigger == "GRADE_THRESHOLD":
        if grade is None or not decimal_of(grade) < decimal_of("70.00"):
            raise_err(
                "ERR_ALERT_THRESHOLD_NOT_MET",
                "GRADE_THRESHOLD requires observed_grade_percent < 70.00",
            )
    else:  # LATE_SUBMISSION
        if days_late is None or days_late < 3:
            raise_err(
                "ERR_ALERT_THRESHOLD_NOT_MET",
                "LATE_SUBMISSION requires days_late >= 3",
            )

    high = (grade is not None and decimal_of(grade) < decimal_of("60.00")) or (
        days_late is not None and days_late >= 7
    )
    alert = new_entity(
        {
            "enrollment_id": eid,
            "trigger_type": trigger,
            "observed_grade_percent": grade,
            "days_late": days_late,
            "severity": "HIGH" if high else "LOW",
            "status": "OPEN",
        }
    )
    STORE.alerts[alert["id"]] = alert
    return ok_object(ser_alert(alert), 201)


@bp.get("/api/enrollments/<eid>/early-alerts")
def list_alerts(eid):
    require_roles(*LIST_ROLES)
    enrollment = STORE.enrollments.get(eid)
    if enrollment is None:
        raise_err("ERR_NOT_FOUND", "enrollment not found")
    items = sorted(
        (a for a in STORE.alerts.values() if a["enrollment_id"] == eid),
        key=lambda a: a["_seq"],
    )
    page, limit, offset, total = paginate([ser_alert(a) for a in items])
    return ok_list(page, limit, offset, total)


@bp.post("/api/early-alerts/<aid>/advance")
def advance_alert(aid):
    uid, _role = require_roles("Advisor")
    body = get_body()
    to_state = req_enum(body, "to_state", ALERT_STATUSES)
    alert = STORE.alerts.get(aid)
    if alert is None:
        raise_err("ERR_NOT_FOUND", "early alert not found")
    enrollment = STORE.enrollments.get(alert["enrollment_id"])
    if enrollment is None or enrollment["advisor_id"] != uid:
        raise_err("ERR_FORBIDDEN", "only the enrollment's owning advisor may advance this alert")

    edges = {
        "OPEN": {"ACKNOWLEDGED"},
        "ACKNOWLEDGED": {"INTERVENTION"},
        "INTERVENTION": {"RESOLVED", "ESCALATED"},
        "ESCALATED": {"INTERVENTION"},
        "RESOLVED": set(),
    }
    if to_state not in edges.get(alert["status"], set()):
        raise_err(
            "ERR_INVALID_STATE",
            "cannot advance early alert from %s to %s" % (alert["status"], to_state),
        )
    alert["status"] = to_state
    bump(alert)
    return ok_object(ser_alert(alert))


# ---------------------------------------------------------------------------
# Retention outreach
# ---------------------------------------------------------------------------

@bp.post("/api/enrollments/<eid>/retention-outreaches")
def create_outreach(eid):
    uid, _role = require_roles("Advisor")
    enrollment = STORE.enrollments.get(eid)
    if enrollment is None:
        raise_err("ERR_NOT_FOUND", "enrollment not found")
    if enrollment["advisor_id"] != uid:
        raise_err("ERR_FORBIDDEN", "only the enrollment's owning advisor may queue outreach")
    if enrollment["status"] not in ("COMPLETED", "WITHDRAWN"):
        raise_err(
            "ERR_INVALID_STATE",
            "outreach may be queued only on COMPLETED or WITHDRAWN enrollments",
        )
    body = get_body()
    target_term_id = req_str(body, "target_term_id")

    application = STORE.applications.get(enrollment["application_id"])
    applicant_id = application["applicant_id"] if application else None

    # Cadence: most recent SENT/RESPONDED outreach for the same applicant;
    # a gap strictly shorter than 14 days rejects (exactly 14 days allowed).
    now = CLOCK.now()
    history = [
        o
        for o in STORE.outreaches.values()
        if o["applicant_id"] == applicant_id and o["status"] in ("SENT", "RESPONDED")
    ]
    if history:
        last = max(history, key=lambda o: o["_seq"])
        sent_dt = last.get("_sent_dt")
        if sent_dt is not None and (now - sent_dt) < timedelta(days=MIN_DAYS_BETWEEN_OUTREACH):
            raise_err(
                "ERR_OUTREACH_CADENCE",
                "less than 14 days since the last SENT/RESPONDED outreach for this applicant",
            )

    outreach = new_entity(
        {
            "enrollment_id": eid,
            "applicant_id": applicant_id,
            "target_term_id": target_term_id,
            "status": "QUEUED",
            "sent_at": None,
            "_sent_dt": None,
        }
    )
    STORE.outreaches[outreach["id"]] = outreach
    return ok_object(ser_outreach(outreach), 201)


@bp.get("/api/enrollments/<eid>/retention-outreaches")
def list_outreaches(eid):
    require_roles(*LIST_ROLES)
    enrollment = STORE.enrollments.get(eid)
    if enrollment is None:
        raise_err("ERR_NOT_FOUND", "enrollment not found")
    items = sorted(
        (o for o in STORE.outreaches.values() if o["enrollment_id"] == eid),
        key=lambda o: o["_seq"],
    )
    for o in items:
        lazy_expire_outreach(o)
    page, limit, offset, total = paginate([ser_outreach(o) for o in items])
    return ok_list(page, limit, offset, total)


@bp.post("/api/retention-outreaches/<oid>/advance")
def advance_outreach(oid):
    uid, _role = require_roles("Advisor")
    body = get_body()
    to_state = req_enum(body, "to_state", OUTREACH_STATUSES)
    outreach = STORE.outreaches.get(oid)
    if outreach is None:
        raise_err("ERR_NOT_FOUND", "retention outreach not found")
    enrollment = STORE.enrollments.get(outreach["enrollment_id"])
    if enrollment is None or enrollment["advisor_id"] != uid:
        raise_err("ERR_FORBIDDEN", "only the enrollment's owning advisor may advance this outreach")

    # Lazy expiry is evaluated on any advance attempt, before the requested
    # transition is checked.
    lazy_expire_outreach(outreach)

    cur = outreach["status"]
    if to_state == "SENT" and cur == "QUEUED":
        outreach["sent_at"] = now_ts()
        outreach["_sent_dt"] = CLOCK.now()
    elif to_state == "RESPONDED" and cur == "SENT":
        pass
    elif to_state == "REENROLLED" and cur == "RESPONDED":
        live = any(
            e["application_id"] != enrollment["application_id"]
            and _enrollment_applicant_id(e) == outreach["applicant_id"]
            and e["term_id"] == outreach["target_term_id"]
            and e["status"] in ("REGISTERED", "ACTIVE", "DEFERRED")
            for e in STORE.enrollments.values()
        )
        if not live:
            raise_err(
                "ERR_INVALID_STATE",
                "no live enrollment into the target term for this applicant",
            )
    else:
        raise_err(
            "ERR_INVALID_STATE",
            "cannot advance retention outreach from %s to %s" % (cur, to_state),
        )
    outreach["status"] = to_state
    bump(outreach)
    return ok_object(ser_outreach(outreach))


def _enrollment_applicant_id(enrollment):
    application = STORE.applications.get(enrollment["application_id"])
    return application["applicant_id"] if application else None
