"""Emergency events and performance assessments routes."""
from flask import Blueprint, request

from db import db
from middleware import require_roles, require_any
from response import success_object, success_list
from util import (base_entity, base_ledger_entity, touch, dec, require_fields,
                  is_number, get_body, strip_internal, paginate, sort_created,
                  parse_dt)
from errors import (err_not_found, err_invalid_request, err_invalid_state,
                    err_invalid_time_range, err_event_overlap)
from services.calcs import (performance_ratio, nonperformance_charge,
                            recompute_commitment_score, post_settlement_entry)

bp = Blueprint("events", __name__)

EVENT_TYPES = ("EMERGENCY_ACTION", "DR_TEST")


def _serialize_event(e):
    return strip_internal(e)


def _serialize_assessment(a):
    return strip_internal(a)


@bp.route("/capacity-market/emergency-events", methods=["POST"])
def create_event():
    require_roles("MarketAdmin")
    body = get_body()
    require_fields(body, ["delivery_year_id", "event_start", "event_end", "event_type"])
    dy = db.delivery_years.get(body["delivery_year_id"])
    if dy is None:
        raise err_not_found("delivery year not found")
    start = parse_dt(body["event_start"], "event_start")
    end = parse_dt(body["event_end"], "event_end")
    if end <= start:
        raise err_invalid_time_range("event_end must be strictly after event_start")
    if start < dy["_start_dt"] or end > dy["_end_dt"]:
        raise err_invalid_time_range("event window must be within the delivery year's planning period")
    etype = body["event_type"]
    if etype not in EVENT_TYPES:
        raise err_invalid_request("event_type must be EMERGENCY_ACTION or DR_TEST")
    e = base_entity()
    e.update({
        "delivery_year_id": dy["id"],
        "event_start": body["event_start"],
        "event_end": body["event_end"],
        "event_type": etype,
        "status": "DECLARED",
        "_start_dt": start,
        "_end_dt": end,
    })
    db.emergency_events[e["id"]] = e
    return success_object(_serialize_event(e), 201)


@bp.route("/capacity-market/emergency-events", methods=["GET"])
def list_events():
    require_any()
    items = list(db.emergency_events.values())
    for key in ("delivery_year_id", "status"):
        v = request.args.get(key)
        if v:
            items = [e for e in items if e.get(key) == v]
    items = sort_created(items)
    page, limit, offset, total = paginate(items, request.args)
    return success_list([_serialize_event(e) for e in page], limit, offset, total)


@bp.route("/capacity-market/emergency-events/<eid>", methods=["GET"])
def get_event(eid):
    require_any()
    e = db.emergency_events.get(eid)
    if e is None:
        raise err_not_found("emergency event not found")
    return success_object(_serialize_event(e))


@bp.route("/capacity-market/emergency-events/<eid>/begin-assessment", methods=["POST"])
def begin_assessment(eid):
    require_roles("MarketAdmin")
    e = db.emergency_events.get(eid)
    if e is None:
        raise err_not_found("emergency event not found")
    dy = db.delivery_years.get(e["delivery_year_id"])
    if dy is None:
        raise err_not_found("delivery year not found")
    if e["status"] != "DECLARED":
        raise err_invalid_state("event is not DECLARED")
    if dy["status"] != "CLEARED":
        raise err_invalid_state("delivery year is not CLEARED")
    # overlap check: no other event in same DY in {DECLARED, ASSESSING, ASSESSED} overlaps [start, end)
    for other in db.emergency_events.values():
        if other["id"] == eid or other["delivery_year_id"] != e["delivery_year_id"]:
            continue
        if other["status"] not in ("DECLARED", "ASSESSING", "ASSESSED"):
            continue
        # half-open overlap: start < other.end and other.start < end
        if e["_start_dt"] < other["_end_dt"] and other["_start_dt"] < e["_end_dt"]:
            raise err_event_overlap()

    e["status"] = "ASSESSING"
    touch(e)
    # spawn DRAFT assessments for in-scope commitments
    for c in db.commitments.values():
        if c["delivery_year_id"] != e["delivery_year_id"]:
            continue
        if c["status"] not in ("ACTIVE", "SETTLED"):
            continue
        resource = db.resources.get(c["resource_id"])
        if resource is None:
            continue
        if e["event_type"] == "DR_TEST" and resource["resource_type"] != "DR":
            continue
        a = base_ledger_entity()
        a.update({
            "emergency_event_id": e["id"],
            "commitment_id": c["id"],
            "expected_mw": None,
            "actual_mw": None,
            "performance_ratio": None,
            "charge_or_credit_dollars": None,
            "assessed_mwh": None,
            "status": "DRAFT",
            "_event_start": e["_start_dt"],
            "_event_end": e["_end_dt"],
        })
        db.assessments[a["id"]] = a
    return success_object(_serialize_event(e))


@bp.route("/capacity-market/emergency-events/<eid>/assessments", methods=["GET"])
def list_event_assessments(eid):
    require_any()
    e = db.emergency_events.get(eid)
    if e is None:
        raise err_not_found("emergency event not found")
    items = sort_created([a for a in db.assessments.values() if a["emergency_event_id"] == eid])
    page, limit, offset, total = paginate(items, request.args)
    return success_list([_serialize_assessment(a) for a in page], limit, offset, total)


@bp.route("/capacity-market/emergency-events/<eid>/finalize-assessments", methods=["POST"])
def finalize_assessments(eid):
    require_roles("MarketAdmin")
    e = db.emergency_events.get(eid)
    if e is None:
        raise err_not_found("emergency event not found")
    if e["status"] != "ASSESSING":
        raise err_invalid_state("event is not ASSESSING")
    event_assessments = [a for a in db.assessments.values() if a["emergency_event_id"] == eid]
    for a in event_assessments:
        if a["status"] != "DRAFT":
            raise err_invalid_state("all assessments must be DRAFT to finalize")
        if a["actual_mw"] is None or a["expected_mw"] is None:
            raise err_invalid_state("all assessments must have actual_mw recorded")

    affected_commitments = set()
    for a in event_assessments:
        a["performance_ratio"] = performance_ratio(a)
        commitment = db.commitments.get(a["commitment_id"])
        amt = nonperformance_charge(a, commitment, e)
        a["charge_or_credit_dollars"] = amt
        # assessed_mwh = expected_mw * H
        H = dec(str((e["_end_dt"] - e["_start_dt"]).total_seconds())) / dec(3600)
        a["assessed_mwh"] = dec(a["expected_mw"]) * H
        a["status"] = "FINALIZED"
        etype = "CHARGE" if amt < 0 else "BONUS"
        post_settlement_entry(e["delivery_year_id"], a["commitment_id"], e["id"], etype, amt)
        affected_commitments.add(a["commitment_id"])

    for cid in affected_commitments:
        c = db.commitments.get(cid)
        if c:
            recompute_commitment_score(c)
            touch(c)

    e["status"] = "ASSESSED"
    touch(e)
    return success_object(_serialize_event(e))


# ------------- Assessments -------------

@bp.route("/capacity-market/assessments", methods=["GET"])
def list_assessments():
    require_any()
    items = list(db.assessments.values())
    for key in ("commitment_id", "emergency_event_id", "status"):
        v = request.args.get(key)
        if v:
            items = [a for a in items if a.get(key) == v]
    items = sort_created(items)
    page, limit, offset, total = paginate(items, request.args)
    return success_list([_serialize_assessment(a) for a in page], limit, offset, total)


@bp.route("/capacity-market/assessments/<aid>", methods=["GET"])
def get_assessment(aid):
    require_any()
    a = db.assessments.get(aid)
    if a is None:
        raise err_not_found("assessment not found")
    return success_object(_serialize_assessment(a))


@bp.route("/capacity-market/assessments/<aid>/record-actual", methods=["POST"])
def record_actual(aid):
    require_roles("MarketAdmin")
    a = db.assessments.get(aid)
    if a is None:
        raise err_not_found("assessment not found")
    body = get_body()
    require_fields(body, ["expected_mw", "actual_mw"])
    if a["status"] != "DRAFT":
        raise err_invalid_state("assessment is not DRAFT")
    expected = body["expected_mw"]
    actual = body["actual_mw"]
    if not is_number(expected) or dec(expected) < 0:
        raise err_invalid_request("expected_mw must be >= 0")
    if not is_number(actual) or dec(actual) < 0:
        raise err_invalid_request("actual_mw must be >= 0")
    # PRD §3.6 describes expected_mw as "no more than the commitment's
    # committed_mw at assessment time" but names no error and no §2.6 gate
    # for exceeding it, so it is recorded as given.
    a["expected_mw"] = dec(expected)
    a["actual_mw"] = dec(actual)
    return success_object(_serialize_assessment(a))
