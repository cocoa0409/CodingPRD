"""Non-installation cases: notice, confirmation (cascade A), remediation and
unsubstantiated closure (PRD 3.6)."""
from flask import Blueprint

import calc
import clock
import envelope
import guards
import services
import validate
import views
from errors import fail
from store import db, touch

bp = Blueprint("cases", __name__)


def _case_subscription(uid, role, case):
    sub = db.subscriptions[case["subscription_id"]]
    guards.own_subscription(uid, role, sub)
    return sub


@bp.get("/non-install-cases/<case_id>")
def read_case(case_id):
    uid, role = guards.auth(["ProgramOperator", "PropertyManager"])
    rec = guards.get_case(case_id)
    _case_subscription(uid, role, rec)
    return envelope.object_response(views.case_view(rec))


@bp.post("/non-install-cases/<case_id>/send-notice")
def send_notice(case_id):
    guards.auth(["ProgramOperator"])
    rec = guards.get_case(case_id)
    if rec["status"] != "OPEN":
        fail("ERR_CASE_STATE_INVALID", "the case is not OPEN")

    notice_date = clock.today()
    rec["notice_sent_at"] = clock.now_iso()
    rec["remediation_deadline"] = clock.fmt_date(
        clock.plus_days(notice_date, calc.REMEDIATION_GRACE_DAYS))
    rec["status"] = "NOTICE_SENT"
    touch(rec)
    return envelope.object_response(views.case_view(rec))


@bp.post("/non-install-cases/<case_id>/confirm")
def confirm(case_id):
    guards.auth(["ProgramOperator"])
    rec = guards.get_case(case_id)
    if rec["status"] != "NOTICE_SENT":
        fail("ERR_CASE_STATE_INVALID", "the case is not NOTICE_SENT")
    # Rung 15 reads the thresholds frozen onto the case at creation, so a later
    # change to the program constants cannot make an old case confirmable.
    if rec["evidence_score"] < rec["confirm_threshold"]:
        fail("ERR_EVIDENCE_BELOW_CONFIRM_THRESHOLD",
             "the frozen evidence score does not reach the frozen threshold")

    sub = db.subscriptions[rec["subscription_id"]]
    rec["status"] = "ESCALATED_TO_PM"
    touch(rec)
    services.confirm_non_install_cascade(sub)
    return envelope.object_response(views.case_view(rec))


@bp.post("/non-install-cases/<case_id>/remediate")
def remediate(case_id):
    uid, role = guards.auth(["ProgramOperator", "PropertyManager"])
    rec = guards.get_case(case_id)
    sub = _case_subscription(uid, role, rec)
    body = validate.json_body()
    note = validate.req_text(body, "remediation_note")
    if rec["status"] != "ESCALATED_TO_PM":
        fail("ERR_CASE_STATE_INVALID", "the case is not ESCALATED_TO_PM")

    rec["remediation_note"] = note
    rec["status"] = "REMEDIATED"
    touch(rec)
    sub["installation_posture"] = "REMEDIATED"
    touch(sub)
    return envelope.object_response(views.case_view(rec))


@bp.post("/non-install-cases/<case_id>/close-unsubstantiated")
def close_unsubstantiated(case_id):
    guards.auth(["ProgramOperator"])
    rec = guards.get_case(case_id)
    if rec["status"] not in ("OPEN", "NOTICE_SENT"):
        fail("ERR_CASE_STATE_INVALID", "the case is neither OPEN nor NOTICE_SENT")

    sub = db.subscriptions[rec["subscription_id"]]
    rec["status"] = "CLOSED_UNSUBSTANTIATED"
    touch(rec)
    sub["installation_posture"] = "COMPLIANT"
    touch(sub)
    return envelope.object_response(views.case_view(rec))
