"""EnforcementProceeding: open, list, get, determine (civil penalty +
compliance-score cascade) — PRD §3.9."""
from flask import Blueprint

import store
from auth import require_roles, any_role
from clock import CLOCK
from envelope import ok_object, ok_list, paginate
from errors import (
    fail,
    ERR_CARRIER_NOT_FOUND,
    ERR_PROCEEDING_NOT_FOUND,
    ERR_INVALID_REQUEST,
    ERR_PROCEEDING_NOT_NOTICE_ISSUED,
)
from serialization import ser_proceeding
from services import calc, cascades
from store import touch
from util import body, req_str, req_enum, is_int

bp = Blueprint("enforcement", __name__)

BASES = (
    "UNREASONABLE_PRACTICE",
    "TARIFF_VIOLATION",
    "UNLICENSED_ACTIVITY",
    "AGREEMENT_VIOLATION",
)


@bp.post("/fmc/enforcement-proceedings")
def open_proceeding():
    uid, _role = require_roles("EnforcementCounsel")
    b = body()
    tcid = b.get("target_carrier_id")
    if isinstance(tcid, str) and tcid not in store.carriers:
        fail(ERR_CARRIER_NOT_FOUND, "carrier organization not found: %s" % tcid)
    target_carrier_id = req_str(b, "target_carrier_id")
    basis = req_enum(b, "basis", BASES)
    rec = store.base_record()
    rec.update(
        target_carrier_id=target_carrier_id,
        basis=basis,
        opened_by_counsel_id=uid,
        proceeding_status="NOTICE_ISSUED",
        determination=None,
        violation_count=None,
        willful=None,
        repeat_offender=None,
        penalty_cents=None,
        score_delta=None,
        determined_at=None,
    )
    store.proceedings[rec["id"]] = rec
    return ok_object(ser_proceeding(rec), 201)


@bp.get("/fmc/carriers/<carrierId>/enforcement-proceedings")
def list_proceedings(carrierId):
    any_role()
    if carrierId not in store.carriers:
        fail(ERR_CARRIER_NOT_FOUND, "carrier organization not found: %s" % carrierId)
    recs = [
        p for p in store.proceedings.values()
        if p["target_carrier_id"] == carrierId
    ]
    page, limit, offset, total = paginate(recs)
    return ok_list([ser_proceeding(p) for p in page], limit, offset, total)


@bp.get("/fmc/enforcement-proceedings/<proceedingId>")
def get_proceeding(proceedingId):
    any_role()
    p = store.proceedings.get(proceedingId)
    if p is None:
        fail(ERR_PROCEEDING_NOT_FOUND,
             "enforcement proceeding not found: %s" % proceedingId)
    return ok_object(ser_proceeding(p))


@bp.post("/fmc/enforcement-proceedings/<proceedingId>/determine")
def determine(proceedingId):
    require_roles("AdministrativeLawJudge")
    p = store.proceedings.get(proceedingId)
    if p is None:
        fail(ERR_PROCEEDING_NOT_FOUND,
             "enforcement proceeding not found: %s" % proceedingId)
    b = body()
    determination = req_enum(b, "determination", ("VIOLATION_FOUND", "NO_VIOLATION"))
    violation_count = b.get("violation_count")
    willful = b.get("willful", False)
    if determination == "VIOLATION_FOUND":
        if violation_count is None or not is_int(violation_count) or violation_count < 1:
            fail(ERR_INVALID_REQUEST,
                 "a VIOLATION_FOUND determination requires a violation_count "
                 "of at least one")
        if not isinstance(willful, bool):
            fail(ERR_INVALID_REQUEST, "willful must be a boolean")
    if p["proceeding_status"] != "NOTICE_ISSUED":
        fail(ERR_PROCEEDING_NOT_NOTICE_ISSUED,
             "determine requires proceeding status NOTICE_ISSUED")

    now = CLOCK.now()
    if determination == "NO_VIOLATION":
        p["determination"] = "NO_VIOLATION"
        p["proceeding_status"] = "DISMISSED"
        p["determined_at"] = now
        touch(p)
        return ok_object(ser_proceeding(p))

    carrier = store.carriers[p["target_carrier_id"]]
    repeat_offender = any(
        q is not p
        and q["target_carrier_id"] == carrier["id"]
        and q["proceeding_status"] == "DETERMINED"
        and q["determination"] == "VIOLATION_FOUND"
        for q in store.proceedings.values()
    )
    penalty_cents = calc.civil_penalty_assessment(
        violation_count, willful, repeat_offender
    )
    score_delta = calc.violation_score_delta(p["basis"], violation_count)
    p.update(
        determination="VIOLATION_FOUND",
        violation_count=violation_count,
        willful=willful,
        repeat_offender=repeat_offender,
        penalty_cents=penalty_cents,
        score_delta=score_delta,
        determined_at=now,
        proceeding_status="DETERMINED",
    )
    cascades.apply_score_event(carrier, score_delta, penalty_cents=penalty_cents)
    touch(p)
    return ok_object(ser_proceeding(p))
