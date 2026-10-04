"""Conviction posting and disqualifications (PRD section 3.4)."""
from flask import Blueprint

import calc
import serialize
import state
import store
import validation as v
from errors import err
from response import ok

bp = Blueprint("convictions", __name__, url_prefix="/driver-exchange")

SEVERITIES = {"NON_CMV", "CMV_SERIOUS", "CMV_MAJOR"}


@bp.post("/convictions")
def post_conviction():
    """Post a conviction to a record held by the caller's jurisdiction. Late
    postings are accepted and flagged is_late; the posting recomputes both
    point totals, fires the disqualification evaluation (create or merge),
    suspends ACTIVE COMMERCIAL licenses when a disqualification is created,
    and recomputes the holding jurisdiction's timeliness score."""
    user_id, role = v.auth_context()
    v.require_role(role, {"JurisdictionRegistrar"})
    data = v.body()
    record_id = v.req_string(data, "record_id")
    offense_date = v.req_date(data, "offense_date")
    conviction_date = v.req_date(data, "conviction_date")
    severity = v.req_enum(data, "severity", SEVERITIES)
    points = v.req_int(data, "points", 1, 6)
    record = store.db.records.get(record_id)
    if record is None:
        raise err("ERR_RECORD_NOT_FOUND", "no driver record with id %s" % record_id)
    if record["holding_jurisdiction_id"] != user_id:
        raise err("ERR_JURISDICTION_OWNERSHIP_MISMATCH",
                  "convictions post only to records held by the caller's jurisdiction")
    jurisdiction = store.db.jurisdictions.get(record["holding_jurisdiction_id"])
    if jurisdiction is None or jurisdiction["membership_status"] != "ACTIVE":
        raise err("ERR_JURISDICTION_NOT_ACTIVE",
                  "posting requires an ACTIVE holding jurisdiction")
    if not state.has_certified_participation(record["holding_jurisdiction_id"],
                                             "COMMERCIAL_DRIVER_NETWORK"):
        raise err("ERR_PARTICIPATION_NOT_CERTIFIED",
                  "posting requires a CERTIFIED COMMERCIAL_DRIVER_NETWORK participation")
    if record["status"] != "ACTIVE":
        raise err("ERR_RECORD_NOT_ACTIVE",
                  "convictions may only post to ACTIVE records")
    posted_at = store.now()
    conviction = {
        "id": store.new_id(),
        "record_id": record_id,
        "offense_date": offense_date.isoformat(),
        "conviction_date": conviction_date.isoformat(),
        "severity": severity,
        "points": points,
        "posted_at": store.format_datetime(posted_at),
        "is_late": calc.compute_is_late(posted_at, conviction_date),
    }
    store.stamp_conviction(conviction)
    store.db.convictions[conviction["id"]] = conviction
    calc.recompute_points(record)
    store.touch(record)
    calc.evaluate_disqualification(record, conviction)
    calc.recompute_timeliness(jurisdiction)
    store.touch(jurisdiction)
    return ok(serialize.conviction(conviction), 201)


@bp.post("/disqualifications")
def create_disqualification():
    """Manually record a judicial disqualification (closed-interval dates);
    overlaps with a derived-ACTIVE disqualification on the same record are
    rejected under closed semantics -- shared boundary days collide."""
    _, role = v.auth_context()
    v.require_role(role, {"AuditAuthority"})
    data = v.body()
    record_id = v.req_string(data, "record_id")
    start_date = v.req_date(data, "start_date")
    end_date = v.req_date(data, "end_date")
    record = store.db.records.get(record_id)
    if record is None:
        raise err("ERR_RECORD_NOT_FOUND", "no driver record with id %s" % record_id)
    for existing in state.active_disqualifications(record_id):
        if state.closed_intervals_intersect(store.parse_date(existing["start_date"]),
                                            store.parse_date(existing["end_date"]),
                                            start_date, end_date):
            raise err("ERR_DISQUALIFICATION_OVERLAP",
                      "the interval overlaps an existing ACTIVE disqualification")
    dq = {
        "id": store.new_id(),
        "record_id": record_id,
        "basis": "MANUAL_JUDICIAL",
        "start_date": start_date.isoformat(),
        "end_date": end_date.isoformat(),
        "overturned_at": None,
    }
    store.stamp(dq)
    store.db.disqualifications[dq["id"]] = dq
    state.suspend_active_commercial_licenses(record_id)
    return ok(serialize.disqualification(dq), 201)


@bp.post("/disqualifications/<dqid>/overturn")
def overturn_disqualification(dqid):
    """The only direct disqualification mutation; valid only while the
    derived status is ACTIVE."""
    _, role = v.auth_context()
    v.require_role(role, {"AuditAuthority"})
    dq = store.db.disqualifications.get(dqid)
    if dq is None:
        raise err("ERR_DISQUALIFICATION_NOT_FOUND",
                  "no disqualification with id %s" % dqid)
    if state.dq_derived_status(dq) != "ACTIVE":
        raise err("ERR_INVALID_STATE",
                  "only an ACTIVE disqualification may be overturned")
    dq["overturned_at"] = store.now_iso()
    store.touch(dq)
    return ok(serialize.disqualification(dq))
