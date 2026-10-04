"""ServiceVisit and Slicer endpoints (PRD SS3.6)."""
from datetime import timedelta

from flask import Blueprint, request

import store
from domain import VISIT_SPACING_MINUTES, touch
from errors import fail
from serializers import ser_slicer, ser_visit
from store import db
from util import (auth, body, list_response, new_id, ok, opt_array, opt_enum,
                  req_bool, req_dt, req_enum, req_int, req_str, sort_std)

bp = Blueprint("field", __name__)

VISIT_READERS = ("BrandAdmin", "DistributorRep", "RetailManager", "SafetyOfficer")
ALLERGEN_VALUES = {"NONE", "MILK", "EGG", "WHEAT", "SOY", "PEANUT", "TREE_NUT", "SESAME"}


def _get_visit(vid):
    v = db["visits"].get(vid)
    if v is None:
        fail("ERR_NOT_FOUND", 404, "service visit not found")
    return v


def _get_slicer(sid):
    s = db["slicers"].get(sid)
    if s is None:
        fail("ERR_NOT_FOUND", 404, "slicer not found")
    return s


# ---------------------------------------------------------------------------
# service visits
# ---------------------------------------------------------------------------

@bp.post("/api/service-visits")
def create_visit():
    _, uid = auth("DistributorRep")
    b = body()
    account_id = req_str(b, "account_id")
    window_start = req_dt(b, "window_start")
    window_end = req_dt(b, "window_end")
    if not window_start < window_end:
        fail("ERR_VALIDATION", 400, "window_start must be strictly before window_end")
    account = db["accounts"].get(account_id)
    if account is None:
        fail("ERR_NOT_FOUND", 404, "account not found")
    # temporal spacing (tier 9): no overlap, and a gap strictly under 30 minutes
    # is rejected; exactly 30 minutes is allowed. CANCELLED visits are ignored.
    gap = timedelta(minutes=VISIT_SPACING_MINUTES)
    for v in db["visits"].values():
        if v["account_id"] != account_id or v["status"] == "CANCELLED":
            continue
        if not (window_start >= v["window_end"] + gap
                or window_end + gap <= v["window_start"]):
            fail("ERR_VISIT_TOO_CLOSE", 409,
                 "visit overlaps or sits under 30 minutes from another visit at the account")
    # standing activity gates (tier 10)
    dist = db["distributors"].get(uid)
    if dist is None:
        fail("ERR_NOT_FOUND", 404, "distributor not found")
    if dist["status"] != "ACTIVE":
        fail("ERR_DISTRIBUTOR_NOT_ACTIVE", 409, "distributor is not ACTIVE")
    if account["approval_status"] != "APPROVED":
        fail("ERR_ACCOUNT_NOT_APPROVED", 409, "account is not APPROVED")
    now = store.now()
    v = {
        "id": new_id(), "_seq": store.next_seq(), "account_id": account_id,
        "distributor_id": uid, "window_start": window_start, "window_end": window_end,
        "status": "SCHEDULED", "score": None, "rotation_compliant": None,
        "slicer_presentation_ok": None, "submitted_at": None,
        "created_at": now, "updated_at": now, "version": 1,
    }
    db["visits"][v["id"]] = v
    return ok(ser_visit(v), 201)


@bp.get("/api/service-visits")
def list_visits():
    auth(*VISIT_READERS)
    items = sort_std(db["visits"].values())
    account_id = request.args.get("account_id")
    distributor_id = request.args.get("distributor_id")
    status = request.args.get("status")
    if account_id is not None:
        items = [v for v in items if v["account_id"] == account_id]
    if distributor_id is not None:
        items = [v for v in items if v["distributor_id"] == distributor_id]
    if status is not None:
        items = [v for v in items if v["status"] == status]
    return list_response([ser_visit(v) for v in items])


@bp.get("/api/service-visits/<vid>")
def get_visit(vid):
    auth(*VISIT_READERS)
    return ok(ser_visit(_get_visit(vid)))


@bp.post("/api/service-visits/<vid>/submit")
def submit_visit(vid):
    _, uid = auth("DistributorRep")
    b = body()
    score = req_int(b, "score")
    if not 0 <= score <= 100:
        fail("ERR_VALIDATION", 400, "score must be between 0 and 100 inclusive")
    rotation_compliant = req_bool(b, "rotation_compliant")
    slicer_presentation_ok = req_bool(b, "slicer_presentation_ok")
    cleaned = opt_array(b, "cleaned_slicer_ids")
    if cleaned is None:
        cleaned = []
    for sid in cleaned:
        if not isinstance(sid, str):
            fail("ERR_VALIDATION", 400, "cleaned_slicer_ids must contain only strings")
    v = _get_visit(vid)
    # entity-backed ownership: only the visit's own representative submits
    if v["distributor_id"] != uid:
        fail("ERR_FORBIDDEN", 403, "X-User-ID must equal the visit's distributor_id")
    if v["status"] in ("VERIFIED", "CANCELLED"):
        fail("ERR_ALREADY_TERMINAL", 409, "service visit is " + v["status"])
    if v["status"] not in ("SCHEDULED", "REWORK"):
        fail("ERR_INVALID_STATE", 409, "service visit is " + v["status"])
    # every referenced slicer id must resolve
    slicers = []
    for sid in cleaned:
        s = db["slicers"].get(sid)
        if s is None:
            fail("ERR_NOT_FOUND", 404, "slicer not found")
        slicers.append(s)
    now = store.now()
    v["status"] = "SUBMITTED"
    v["score"] = score
    v["rotation_compliant"] = rotation_compliant
    v["slicer_presentation_ok"] = slicer_presentation_ok
    v["submitted_at"] = now
    touch(v)
    for s in slicers:
        s["cleaning_verified_at"] = now
        touch(s)
    return ok(ser_visit(v))


@bp.post("/api/service-visits/<vid>/review")
def review_visit(vid):
    auth("SafetyOfficer")
    b = body()
    verdict = req_enum(b, "verdict", {"VERIFY", "REWORK"})
    v = _get_visit(vid)
    if v["status"] in ("VERIFIED", "CANCELLED"):
        fail("ERR_ALREADY_TERMINAL", 409, "service visit is " + v["status"])
    if v["status"] != "SUBMITTED":
        fail("ERR_INVALID_STATE", 409, "service visit is " + v["status"])
    v["status"] = "VERIFIED" if verdict == "VERIFY" else "REWORK"
    touch(v)
    return ok(ser_visit(v))


# ---------------------------------------------------------------------------
# slicers
# ---------------------------------------------------------------------------

@bp.post("/api/slicers")
def create_slicer():
    _, uid = auth("RetailManager")
    b = body()
    account_id = b.get("account_id")
    if not isinstance(account_id, str):
        fail("ERR_VALIDATION", 400, "account_id is required and must be a string")
    # entity-backed ownership: a RetailManager registers slicers at their account
    if account_id != uid:
        fail("ERR_FORBIDDEN", 403, "X-User-ID must equal the slicer's account_id")
    label = req_str(b, "label")
    dedicated = opt_enum(b, "dedicated_allergen", ALLERGEN_VALUES, "NONE")
    if db["accounts"].get(account_id) is None:
        fail("ERR_NOT_FOUND", 404, "account not found")
    now = store.now()
    s = {
        "id": new_id(), "_seq": store.next_seq(), "account_id": account_id,
        "label": label, "dedicated_allergen": dedicated,
        "cleaning_verified_at": None, "status": "ACTIVE",
        "created_at": now, "updated_at": now, "version": 1,
    }
    db["slicers"][s["id"]] = s
    return ok(ser_slicer(s), 201)


@bp.get("/api/slicers")
def list_slicers():
    auth(*VISIT_READERS)
    items = sort_std(db["slicers"].values())
    account_id = request.args.get("account_id")
    status = request.args.get("status")
    if account_id is not None:
        items = [s for s in items if s["account_id"] == account_id]
    if status is not None:
        items = [s for s in items if s["status"] == status]
    return list_response([ser_slicer(s) for s in items])


@bp.get("/api/slicers/<sid>")
def get_slicer(sid):
    auth(*VISIT_READERS)
    return ok(ser_slicer(_get_slicer(sid)))


@bp.post("/api/slicers/<sid>/decommission")
def decommission_slicer(sid):
    _, uid = auth("RetailManager")
    s = _get_slicer(sid)
    if s["account_id"] != uid:
        fail("ERR_FORBIDDEN", 403, "X-User-ID must equal the slicer's account_id")
    if s["status"] == "DECOMMISSIONED":
        fail("ERR_ALREADY_TERMINAL", 409, "slicer is DECOMMISSIONED")
    s["status"] = "DECOMMISSIONED"
    touch(s)
    return ok(ser_slicer(s))
