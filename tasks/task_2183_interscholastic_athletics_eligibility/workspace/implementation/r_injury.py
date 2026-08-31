"""Injury reports and the graduated return-to-play protocol."""
from datetime import timedelta
from flask import Blueprint, request

from core import (
    DB, ALL_ROLES, INJURY_TYPES, auth, body, ok, ok_list, fail, req_str,
    req_enum, opt_str, opt_bool, new_record, touch, now, pagination, paginate,
    get_student, get_contest, get_injury, ser_injury,
)
import calc
import domain

bp = Blueprint("injuries", __name__)


@bp.post("/athletics/injury-reports")
def create_injury():
    p = auth(["MedicalOfficer"])
    b = body()
    if isinstance(b.get("student_id"), str):
        get_student(b["student_id"])
    if isinstance(b.get("contest_id"), str):
        get_contest(b["contest_id"])
    student_id = req_str(b, "student_id")
    injury_type = req_enum(b, "injury_type", INJURY_TYPES)
    contest_id = opt_str(b, "contest_id", None)
    opt_str(b, "injury_note", None)

    rec = new_record({
        "student_id": student_id,
        "contest_id": contest_id,
        "injury_type": injury_type,
        "reported_at": now(),
        "reported_by_user_id": p.user_id,
        "status": "REPORTED",
        "rtp_stage": 0,
        "last_stage_advanced_at": None,
        "recurrence_count": 0,
        "cleared_by_user_id": None,
        "cleared_at": None,
    })
    DB.injuries[rec["id"]] = rec
    for case in DB.cases.values():
        if case["student_id"] == student_id and case["status"] == "ELIGIBLE":
            case["status"] = "MEDICALLY_SUSPENDED"
            touch(case)
    return ok(ser_injury(rec), 201)


@bp.post("/athletics/injury-reports/<iid>/advance-stage")
def advance_stage(iid):
    auth(["MedicalOfficer"])
    report = get_injury(iid)
    b = body()
    recurrence = opt_bool(b, "symptom_recurrence", False)
    opt_str(b, "stage_note", None)
    clock = now()

    if report["status"] == "REPORTED" and not recurrence:
        floor = report["reported_at"] + timedelta(hours=calc.RTP_INITIAL_REST_HOURS)
        if clock < floor:
            fail("ERR_RTP_INTERVAL_NOT_ELAPSED",
                 "the 48-hour initial rest interval has not elapsed")
        report["status"] = "RTP_IN_PROGRESS"
        report["rtp_stage"] = 1
        report["last_stage_advanced_at"] = clock
        touch(report)
        return ok(ser_injury(report))

    if report["status"] == "RTP_IN_PROGRESS":
        if recurrence:
            report["rtp_stage"] = 1
            report["recurrence_count"] += 1
            report["last_stage_advanced_at"] = clock
            touch(report)
            return ok(ser_injury(report))
        if report["rtp_stage"] >= 5:
            fail("ERR_RTP_STAGE_CEILING", "the return-to-play protocol is already at stage 5")
        floor = report["last_stage_advanced_at"] + timedelta(hours=calc.RTP_STAGE_MIN_HOURS)
        if clock < floor:
            fail("ERR_RTP_INTERVAL_NOT_ELAPSED",
                 "the 24-hour inter-stage interval has not elapsed")
        report["rtp_stage"] += 1
        report["last_stage_advanced_at"] = clock
        touch(report)
        return ok(ser_injury(report))

    fail("ERR_INVALID_STATE",
         "a report in %s admits no stage advance" % report["status"])


@bp.post("/athletics/injury-reports/<iid>/clear")
def clear_injury(iid):
    p = auth(["MedicalOfficer"])
    report = get_injury(iid)
    b = body()
    disposition = req_enum(b, "disposition", ["RETURN_TO_PLAY", "SEASON_ENDED"])
    opt_str(b, "clearance_note", None)
    clock = now()

    if report["status"] not in ("REPORTED", "RTP_IN_PROGRESS"):
        fail("ERR_INVALID_STATE", "a report in %s is already closed" % report["status"])
    if disposition == "RETURN_TO_PLAY" and report["rtp_stage"] != 5:
        fail("ERR_RTP_STAGE_INCOMPLETE",
             "return-to-play clearance requires return-to-play stage 5")
    if p.user_id == report["reported_by_user_id"]:
        fail("ERR_SEGREGATION_OF_DUTIES",
             "the officer who filed this report may not clear it")
    if disposition == "RETURN_TO_PLAY":
        floor = report["reported_at"] + timedelta(hours=calc.RTP_MIN_TOTAL_HOURS)
        if clock < floor:
            fail("ERR_RTP_INTERVAL_NOT_ELAPSED",
                 "the 144-hour total return-to-play interval has not elapsed")

    report["status"] = "CLEARED" if disposition == "RETURN_TO_PLAY" else "SEASON_ENDED"
    report["cleared_by_user_id"] = p.user_id
    report["cleared_at"] = clock
    touch(report)

    if disposition == "RETURN_TO_PLAY":
        if not domain.student_has_live_injury(report["student_id"], exclude_id=report["id"]):
            for case in DB.cases.values():
                if case["student_id"] == report["student_id"] \
                        and case["status"] == "MEDICALLY_SUSPENDED":
                    case["status"] = "ELIGIBLE"
                    touch(case)
    return ok(ser_injury(report))


@bp.get("/athletics/injury-reports/<iid>")
def read_injury(iid):
    auth(ALL_ROLES)
    return ok(ser_injury(get_injury(iid)))


@bp.get("/athletics/injury-reports")
def list_injuries():
    auth(ALL_ROLES)
    limit, offset = pagination()
    rows = list(DB.injuries.values())
    for key in ("student_id", "contest_id", "status"):
        val = request.args.get(key)
        if val is not None:
            rows = [i for i in rows if i[key] == val]
    rows.sort(key=lambda i: (i["reported_at"], i["created_at"], i["_seq"]))
    page, total = paginate(rows, limit, offset)
    return ok_list([ser_injury(i) for i in page], limit, offset, total)
