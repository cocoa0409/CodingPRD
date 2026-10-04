"""Syllabus versions and exams (PRD §2.10, §3.2): creation, the four-link
activation cascade (retire previous version -> retire/activate exams -> cancel
windows -> cancel registrations with full refund, no waitlist promotion), and
credit_map validation at activation time.
"""

from flask import Blueprint, request

import serialize as SZ
import services as S
from auth import require
from errors import ApiError, bad_request
from helpers import (body, ok_object, list_response, req_str, req_int,
                     opt_bool)
from store import db, new_record, touch

bp = Blueprint("syllabus", __name__)


@bp.post("/syllabus-versions")
def create_syllabus_version():
    require("Registrar")
    b = body()
    version_code = req_str(b, "version_code")
    credit_map = b.get("credit_map", {})
    if credit_map is None:
        credit_map = {}
    if (not isinstance(credit_map, dict)
            or any(not isinstance(k, str) or not isinstance(v, str)
                   for k, v in credit_map.items())):
        bad_request("credit_map must be an object mapping exam codes to exam codes")
    if any(v["version_code"] == version_code for v in db.syllabus_versions.values()):
        bad_request("version_code already exists")
    rec = new_record()
    rec.update({
        "version_code": version_code,
        "status": "DRAFT",
        "credit_map": dict(credit_map),
        "activated_at": None,
    })
    db.syllabus_versions[rec["id"]] = rec
    return ok_object(SZ.syllabus(rec), 201)


@bp.get("/syllabus-versions/<sid>")
def get_syllabus_version(sid):
    require("Registrar", "ExamCommittee")
    sv = db.syllabus_versions.get(sid)
    if sv is None:
        raise ApiError("ERR_SYLLABUS_VERSION_NOT_FOUND", 404,
                       "syllabus version not found")
    return ok_object(SZ.syllabus(sv), 200)


@bp.post("/syllabus-versions/<sid>/activate")
def activate_syllabus_version(sid):
    require("Registrar")
    sv = db.syllabus_versions.get(sid)
    if sv is None:
        raise ApiError("ERR_SYLLABUS_VERSION_NOT_FOUND", 404,
                       "syllabus version not found")
    if sv["status"] != "DRAFT":
        raise ApiError("ERR_SYLLABUS_ACTIVATION_INVALID", 422,
                       "only a DRAFT syllabus version can be activated")
    # credit_map validation at activation time (PRD §3.2)
    cmap = sv["credit_map"] or {}
    active = None
    for v in db.syllabus_versions.values():
        if v["status"] == "ACTIVE":
            active = v
            break
    if active is None:
        if cmap:
            bad_request("credit_map keys must be exam codes of the currently "
                        "ACTIVE version; no version is ACTIVE")
    else:
        outgoing_codes = {e["exam_code"] for e in db.exams.values()
                          if e["syllabus_version_id"] == active["id"]}
        for key in cmap:
            if key not in outgoing_codes:
                bad_request("credit_map key %r is not an exam code of the "
                            "currently ACTIVE version" % key)
    incoming_codes = {e["exam_code"] for e in db.exams.values()
                      if e["syllabus_version_id"] == sv["id"]}
    for value in cmap.values():
        if value not in incoming_codes:
            bad_request("credit_map value %r is not an exam code of the version "
                        "being activated" % value)
    # Cascade link 0: stamp activation.
    now = db.clock
    sv["activated_at"] = now
    sv["status"] = "ACTIVE"
    touch(sv)
    if active is not None:
        # Link 1: previously ACTIVE version retires.
        active["status"] = "RETIRED"
        touch(active)
        retired_exam_ids = []
        # Link 2a: every exam of the retired version retires.
        for e in sorted(db.exams.values(), key=lambda x: x["_seq"]):
            if e["syllabus_version_id"] == active["id"]:
                e["status"] = "RETIRED"
                touch(e)
                retired_exam_ids.append(e["id"])
        # Link 3: windows of retired exams in the three pre-testing states cancel.
        for w in sorted(db.exam_windows.values(), key=lambda x: x["_seq"]):
            if (w["exam_id"] in retired_exam_ids
                    and w["status"] in ("SCHEDULED", "REGISTRATION_OPEN",
                                        "REGISTRATION_CLOSED")):
                w["status"] = "CANCELLED"
                touch(w)
                # Link 4: their REGISTERED/WAITLISTED registrations cancel with a
                # full refund; NO waitlist promotion fires from a cancelled window.
                for r in sorted((r for r in db.exam_registrations.values()
                                 if r["exam_window_id"] == w["id"]
                                 and r["logistics_status"] in ("REGISTERED",
                                                               "WAITLISTED")),
                                key=lambda x: x["_seq"]):
                    S.cancel_registration(r, w, "SYLLABUS_RETIREMENT", now,
                                          allow_promotion=False)
    # Link 2b: every exam of the newly activated version becomes ACTIVE.
    for e in sorted(db.exams.values(), key=lambda x: x["_seq"]):
        if e["syllabus_version_id"] == sv["id"]:
            e["status"] = "ACTIVE"
            touch(e)
    return ok_object(SZ.syllabus(sv), 200)


@bp.post("/exams")
def create_exam():
    require("Registrar")
    b = body()
    exam_code = req_str(b, "exam_code")
    title = req_str(b, "title")
    credit_hours = req_int(b, "credit_hours", lo=1)
    syllabus_version_id = req_str(b, "syllabus_version_id")
    is_prelim = opt_bool(b, "is_prelim", True)
    prereq_id = None
    if "prerequisite_exam_id" in b and b["prerequisite_exam_id"] is not None:
        prereq_id = b["prerequisite_exam_id"]
        if not isinstance(prereq_id, str):
            bad_request("prerequisite_exam_id must be a string or null")
    if any(e["exam_code"] == exam_code for e in db.exams.values()):
        bad_request("exam_code already exists")
    sv = db.syllabus_versions.get(syllabus_version_id)
    if sv is None:
        raise ApiError("ERR_SYLLABUS_VERSION_NOT_FOUND", 404,
                       "syllabus version not found")
    if prereq_id is not None:
        prereq = db.exams.get(prereq_id)
        if prereq is None:
            raise ApiError("ERR_EXAM_NOT_FOUND", 404, "prerequisite exam not found")
        if prereq["syllabus_version_id"] != sv["id"]:
            bad_request("prerequisite exam must belong to the same syllabus version")
        # Acyclic guard: walk the prerequisite chain of the target.
        seen = set()
        cursor = prereq
        while cursor is not None:
            if cursor["id"] in seen:
                bad_request("prerequisite graph must remain acyclic")
            seen.add(cursor["id"])
            nxt = cursor["prerequisite_exam_id"]
            cursor = db.exams.get(nxt) if nxt else None
    rec = new_record()
    rec.update({
        "exam_code": exam_code,
        "title": title,
        "credit_hours": credit_hours,
        "is_prelim": is_prelim,
        "prerequisite_exam_id": prereq_id,
        "syllabus_version_id": sv["id"],
        "status": "DRAFT",
    })
    db.exams[rec["id"]] = rec
    return ok_object(SZ.exam(rec), 201)


@bp.get("/exams/<eid>")
def get_exam(eid):
    require("Registrar", "Candidate", "ExamCommittee")
    exam = db.exams.get(eid)
    if exam is None:
        raise ApiError("ERR_EXAM_NOT_FOUND", 404, "exam not found")
    return ok_object(SZ.exam(exam), 200)


@bp.get("/exams")
def list_exams():
    require("Registrar", "Candidate", "ExamCommittee")
    items = sorted(db.exams.values(), key=lambda e: e["_seq"])
    f_sv = request.args.get("syllabus_version_id")
    f_pre = request.args.get("prerequisite_exam_id")
    f_status = request.args.get("status")
    if f_sv is not None:
        items = [e for e in items if e["syllabus_version_id"] == f_sv]
    if f_pre is not None:
        items = [e for e in items if e["prerequisite_exam_id"] == f_pre]
    if f_status is not None:
        items = [e for e in items if e["status"] == f_status]
    return list_response([SZ.exam(e) for e in items])
