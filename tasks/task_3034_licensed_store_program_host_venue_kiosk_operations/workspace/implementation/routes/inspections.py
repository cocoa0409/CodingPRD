"""Inspections and corrective actions."""
from datetime import timedelta
from flask import request

import errors as E
import middleware as mw
from db import db
from response import success_list, success_object
from services import calculations as calc
from services import cascades
from routes.agreements import bp, get_store


def pub_inspection(i):
    return {
        "id": i["id"], "store_id": i["store_id"], "inspector_id": i["inspector_id"],
        "scheduled_start_utc": i["scheduled_start_utc"],
        "scheduled_end_utc": i["scheduled_end_utc"],
        "status": i["status"], "result": i["result"], "total_score": i["total_score"],
        "critical_fail": i["critical_fail"],
        "created_at": i["created_at"], "updated_at": i["updated_at"], "version": i["version"],
    }


def pub_corrective(c):
    return {
        "id": c["id"], "inspection_id": c["inspection_id"], "finding_code": c["finding_code"],
        "due_at": c["due_at"], "status": c["status"], "evidence_note": c["evidence_note"],
        "reopen_count": c["reopen_count"], "verified_by": c["verified_by"],
        "created_at": c["created_at"], "updated_at": c["updated_at"], "version": c["version"],
    }


def get_inspection(iid):
    i = db.inspections.get(iid)
    if i is None:
        raise E.err_not_found("inspection not found")
    return i


def get_corrective(cid):
    c = db.corrective_actions.get(cid)
    if c is None:
        raise E.err_not_found("corrective action not found")
    return c


def _store_licensee(store_id):
    return mw.licensee_of_store(db.stores[store_id])


def _inspection_scope(uid, role, insp):
    if role == "LicenseeManager" and uid != _store_licensee(insp["store_id"]):
        raise E.err_forbidden()


def _corrective_scope(uid, role, ca):
    insp = db.inspections[ca["inspection_id"]]
    _inspection_scope(uid, role, insp)


def _time_of_day_minutes(dt):
    return dt.hour * 60 + dt.minute


# ---------------------------------------------------------------------------
# Inspections
# ---------------------------------------------------------------------------

@bp.post("/licensing/stores/<sid>/inspections")
def schedule_inspection(sid):
    uid, role = mw.auth()
    mw.require_role(role, ("BrandInspector",))
    store = get_store(sid)
    if store["operating_status"] != "OPERATING":
        raise E.err_store_not_operating()
    b = mw.body()
    start = mw.req_datetime(b, "scheduled_start_utc")
    end = mw.req_datetime(b, "scheduled_end_utc")
    agreement = db.license_agreements[store["agreement_id"]]
    venue = db.host_venues[agreement["venue_id"]]
    open_min = _time_str_minutes(venue["open_time_utc"])
    close_min = _time_str_minutes(venue["close_time_utc"])
    if (
        start >= end
        or _time_of_day_minutes(start) < open_min
        or _time_of_day_minutes(end) > close_min
    ):
        raise E.err_outside_venue_hours()
    for other in db.inspections.values():
        if other["inspector_id"] != uid or other["status"] != "SCHEDULED":
            continue
        os_ = mw.parse_iso8601(other["scheduled_start_utc"])
        oe = mw.parse_iso8601(other["scheduled_end_utc"])
        if os_ < end and start < oe:
            raise E.err_inspector_conflict()
    rec = mw.make_resource({
        "store_id": sid, "inspector_id": uid,
        "scheduled_start_utc": mw.fmt_clock(start), "scheduled_end_utc": mw.fmt_clock(end),
        "status": "SCHEDULED", "result": "NONE", "total_score": None, "critical_fail": False,
    })
    db.inspections[rec["id"]] = rec
    return success_object(pub_inspection(rec), 201)


def _time_str_minutes(s):
    hh, mm = s.split(":")
    return int(hh) * 60 + int(mm)


@bp.get("/licensing/inspections/<iid>")
def get_inspection_route(iid):
    uid, role = mw.auth()
    mw.require_role(role, ("BrandProgramAdmin", "BrandInspector", "LicenseeManager"))
    insp = get_inspection(iid)
    _inspection_scope(uid, role, insp)
    return success_object(pub_inspection(insp))


@bp.get("/licensing/inspections")
def list_inspections():
    uid, role = mw.auth()
    mw.require_role(role, ("BrandProgramAdmin", "BrandInspector", "LicenseeManager"))
    items = list(db.inspections.values())
    if role == "LicenseeManager":
        items = [i for i in items if _store_licensee(i["store_id"]) == uid]
    sid = request.args.get("store_id")
    if sid is not None:
        items = [i for i in items if i["store_id"] == sid]
    iid = request.args.get("inspector_id")
    if iid is not None:
        items = [i for i in items if i["inspector_id"] == iid]
    st = request.args.get("status")
    if st is not None:
        items = [i for i in items if i["status"] == st]
    page, limit, offset, total = mw.paginate(items)
    return success_list([pub_inspection(x) for x in page], limit, offset, total)


@bp.post("/licensing/inspections/<iid>/complete")
def complete_inspection(iid):
    uid, role = mw.auth()
    mw.require_role(role, ("BrandInspector",))
    insp = get_inspection(iid)
    if insp["status"] != "SCHEDULED":
        raise E.err_invalid_inspection_state()
    b = mw.body()
    scores = b.get("category_scores")
    if not isinstance(scores, dict):
        raise E.err_invalid_request("category_scores must be an object")
    if set(scores.keys()) != set(calc.INSPECTION_CATEGORIES):
        raise E.err_invalid_request(
            "category_scores must cover exactly the four weighted categories"
        )
    for cat, v in scores.items():
        if isinstance(v, bool) or not isinstance(v, int) or not (0 <= v <= 100):
            raise E.err_invalid_request("category scores must be integers in 0..100")
    critical_fail = mw.req_bool(b, "critical_fail")
    total_score = calc.inspection_composite(scores)
    if critical_fail:
        result = "FAILED"
    elif total_score >= calc.INSPECTION_PASS_SCORE:
        result = "PASSED"
    else:
        result = "FAILED"
    insp["total_score"] = total_score
    insp["critical_fail"] = critical_fail
    insp["result"] = result
    insp["status"] = "COMPLETED"
    mw.touch(insp)
    if result == "FAILED":
        store = db.stores[insp["store_id"]]
        due_at = mw.fmt_clock(db.clock + timedelta(days=calc.CORRECTIVE_DUE_DAYS))
        if critical_fail:
            findings = ["CRITICAL"]
        else:
            findings = [c for c in calc.INSPECTION_CATEGORIES
                        if scores[c] < calc.CATEGORY_FAIL_SCORE]
        for f in findings:
            ca = mw.make_resource({
                "inspection_id": insp["id"], "finding_code": f, "due_at": due_at,
                "status": "OPEN", "evidence_note": None, "reopen_count": 0,
                "verified_by": None,
            })
            db.corrective_actions[ca["id"]] = ca
        calc.recompute_posture(store)
        mw.touch(store)
    return success_object(pub_inspection(insp))


@bp.post("/licensing/inspections/<iid>/cancel")
def cancel_inspection(iid):
    uid, role = mw.auth()
    mw.require_role(role, ("BrandInspector",))
    insp = get_inspection(iid)
    if insp["status"] != "SCHEDULED":
        raise E.err_invalid_inspection_state()
    insp["status"] = "CANCELLED"
    mw.touch(insp)
    return success_object(pub_inspection(insp))


# ---------------------------------------------------------------------------
# Corrective actions
# ---------------------------------------------------------------------------

@bp.get("/licensing/corrective-actions/<cid>")
def get_corrective_route(cid):
    uid, role = mw.auth()
    mw.require_role(role, ("BrandProgramAdmin", "BrandInspector", "LicenseeManager"))
    ca = get_corrective(cid)
    _corrective_scope(uid, role, ca)
    return success_object(pub_corrective(ca))


@bp.get("/licensing/corrective-actions")
def list_corrective_actions():
    uid, role = mw.auth()
    mw.require_role(role, ("BrandProgramAdmin", "BrandInspector", "LicenseeManager"))
    items = list(db.corrective_actions.values())
    if role == "LicenseeManager":
        items = [
            c for c in items
            if _store_licensee(db.inspections[c["inspection_id"]]["store_id"]) == uid
        ]
    iid = request.args.get("inspection_id")
    if iid is not None:
        items = [c for c in items if c["inspection_id"] == iid]
    st = request.args.get("status")
    if st is not None:
        items = [c for c in items if c["status"] == st]
    page, limit, offset, total = mw.paginate(
        items, extra_sort=lambda c: (c["created_at"], c["finding_code"], c["id"])
    )
    return success_list([pub_corrective(x) for x in page], limit, offset, total)


@bp.post("/licensing/corrective-actions/<cid>/submit-evidence")
def submit_evidence(cid):
    uid, role = mw.auth()
    mw.require_role(role, ("LicenseeManager",))
    ca = get_corrective(cid)
    _corrective_scope(uid, role, ca)
    if ca["status"] not in ("OPEN", "REOPENED"):
        raise E.err_invalid_corrective_state()
    b = mw.body()
    ca["evidence_note"] = mw.req_str(b, "evidence_note")
    ca["status"] = "SUBMITTED"
    mw.touch(ca)
    return success_object(pub_corrective(ca))


@bp.post("/licensing/corrective-actions/<cid>/verify")
def verify_corrective(cid):
    uid, role = mw.auth()
    mw.require_role(role, ("BrandInspector",))
    ca = get_corrective(cid)
    if ca["status"] != "SUBMITTED":
        raise E.err_invalid_corrective_state()
    insp = db.inspections[ca["inspection_id"]]
    if uid == insp["inspector_id"]:
        raise E.err_sod("the verifying inspector must differ from the completing inspector")
    ca["status"] = "VERIFIED"
    ca["verified_by"] = uid
    mw.touch(ca)
    calc.recompute_posture(db.stores[insp["store_id"]])
    return success_object(pub_corrective(ca))


@bp.post("/licensing/corrective-actions/<cid>/reopen")
def reopen_corrective(cid):
    uid, role = mw.auth()
    mw.require_role(role, ("BrandInspector",))
    ca = get_corrective(cid)
    if ca["status"] != "SUBMITTED":
        raise E.err_invalid_corrective_state()
    if ca["reopen_count"] >= calc.MAX_REOPENS:
        raise E.err_max_reopens()
    b = mw.body()
    ca["reopen_reason"] = mw.opt_str(b, "reason")
    ca["reopen_count"] += 1
    ca["status"] = "REOPENED"
    mw.touch(ca)
    insp = db.inspections[ca["inspection_id"]]
    calc.recompute_posture(db.stores[insp["store_id"]])
    return success_object(pub_corrective(ca))


@bp.post("/licensing/corrective-actions/sweep-overdue")
def sweep_overdue_correctives():
    uid, role = mw.auth()
    mw.require_role(role, ("BrandProgramAdmin",))
    due = [
        c for c in db.corrective_actions.values()
        if c["status"] in ("OPEN", "REOPENED")
        and mw.parse_iso8601(c["due_at"]) < db.clock
    ]
    due.sort(key=lambda c: (c["created_at"], c["finding_code"], c["id"]))
    escalated = []
    for ca in due:
        ca["status"] = "ESCALATED"
        mw.touch(ca)
        escalated.append(ca)
        insp = db.inspections[ca["inspection_id"]]
        store = db.stores[insp["store_id"]]
        agreement = db.license_agreements[store["agreement_id"]]
        agreement["breach_strikes"] += 1
        mw.touch(agreement)
        if (
            agreement["breach_strikes"] >= calc.BREACH_SUSPEND_THRESHOLD
            and agreement["status"] == "ACTIVE"
        ):
            cascades.suspend_agreement(agreement)
    page, limit, offset, total = mw.paginate(
        escalated, extra_sort=lambda c: (c["created_at"], c["finding_code"], c["id"])
    )
    return success_list([pub_corrective(x) for x in page], limit, offset, total)
