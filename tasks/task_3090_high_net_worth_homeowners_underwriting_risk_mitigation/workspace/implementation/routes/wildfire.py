"""Wildfire defense dispatch (PRD §3.6)."""

from datetime import timedelta

from flask import Blueprint

import calc
import db
import reqs
from clock import add_days, fmt_dt, parse_dt
from errors import err
from middleware import authorize
from response import array, ok, paginate
from serialize import render, render_list
from services import core

bp = Blueprint("wildfire", __name__)

DISPATCH_READERS = ("Underwriter", "AgencyProducer", "ClaimsAdjuster", "ComplianceReporter",
                    "PlatformAdmin")
ZONE_DISPATCH_READERS = ("Underwriter", "ComplianceReporter", "PlatformAdmin",
                         "AgencyProducer", "ClaimsAdjuster", "RiskConsultant")
EVENT_LEVELS = ("NONE", "WATCH", "ACTIVE")

OCCUPANCY_HOURS = 24
VENDOR_PREFIX = "vendor-"


def common_fields():
    now = fmt_dt(db.now())
    return {"id": db.new_id(), "created_at": now, "updated_at": now, "version": 1}


# --------------------------------------------------------------------------
# dispatch request
# --------------------------------------------------------------------------
@bp.route("/hnw/wildfire-events/properties/<property_id>/dispatch-request", methods=["POST"])
def dispatch_request(property_id):
    authorize(("AgencyProducer", "Underwriter"))
    prop = core.get(db.PROPERTIES, property_id, "Property")
    zone = db.ZONES.get(prop["risk_zone_id"])
    if zone is None or zone["state_event"] != "ACTIVE":
        raise err("ERR_ZONE_EVENT_INACTIVE",
                  "The zone's event is not ACTIVE.")
    record = common_fields()
    record.update({
        "property_id": prop["id"],
        "risk_zone_id": zone["id"],
        "vendor_ref": None,
        "state_event": zone["state_event"],
        "status": "REQUESTED",
        "priority_rank": calc.priority_rank(prop, db.now()),
        "assigned_at": None,
    })
    db.DISPATCHES[record["id"]] = record
    return ok(render(record), status=201)


# --------------------------------------------------------------------------
# vendor poll
# --------------------------------------------------------------------------
@bp.route("/hnw/wildfire-events/vendors/poll", methods=["POST"])
def vendor_poll():
    authorize(("Underwriter",))
    data = reqs.body()
    zone_id = reqs.string(data, "risk_zone_id", required=True)
    zone = core.get(db.ZONES, zone_id, "RiskZone")
    now = db.now()
    if _overlapping_assignments(zone_id, now) >= 2:
        raise err("ERR_ZONE_DISPATCH_CAPACITY",
                  "The zone already holds two overlapping dispatch assignments.")
    pool = []
    for dispatch in db.DISPATCHES.values():
        if dispatch["status"] != "REQUESTED" or dispatch["risk_zone_id"] != zone_id:
            continue
        property_zone = db.ZONES.get(dispatch["risk_zone_id"])
        # A zone event that has dropped below ACTIVE is no longer defending, so
        # a queued request is not eligible until the event returns (PRD §3.6).
        if property_zone is None or property_zone["state_event"] != "ACTIVE":
            continue
        prop = db.PROPERTIES.get(dispatch["property_id"])
        if prop is None:
            continue
        pool.append((dispatch, prop))
    if not pool:
        raise err("ERR_NO_ELIGIBLE_VENDOR",
                  "No REQUESTED dispatch with an ACTIVE zone event is eligible.")
    now = db.now()
    for dispatch, prop in pool:
        dispatch["priority_rank"] = calc.priority_rank(prop, now)
    age = {}
    for dispatch, prop in pool:
        from clock import whole_days_ago
        age[dispatch["id"]] = whole_days_ago(prop["created_at"], now)
    ordered = sorted(
        pool,
        key=lambda pair: (
            _zone_rank(pair[1]),
            _expiring_rank(pair[1], now),
            -age[pair[0]["id"]],
            pair[1]["created_at"],
        ),
    )
    chosen, chosen_prop = ordered[0]
    chosen["status"] = "VENDOR_ASSIGNED"
    chosen["vendor_ref"] = _vendor_ref(chosen)
    chosen["assigned_at"] = fmt_dt(now)
    core.touch(chosen)
    core.recompute_property(chosen_prop["id"])
    return ok(render(chosen))


def _zone_rank(prop):
    band = calc.mitigation_band(prop["id"])
    return 1 if band in ("PARTIAL", "UNVERIFIED") else 2


def _expiring_rank(prop, now):
    horizon = now + timedelta(days=14)
    for req in db.MITIGATION_REQUIREMENTS.values():
        if req["property_id"] != prop["id"] or req["status"] != "IMPOSED":
            continue
        if req["due_on"] is not None and req["due_on"] <= horizon:
            return 0
    return 1


def _vendor_ref(dispatch):
    return "%s%s" % (VENDOR_PREFIX, dispatch["id"][:8])


def _window(dispatch):
    start = parse_dt(dispatch["assigned_at"])
    if start is None:
        return None
    return start, start + timedelta(hours=OCCUPANCY_HOURS)


def _overlapping_assignments(zone_id, candidate_start):
    """Count occupied windows that overlap the candidate's 24-hour occupancy."""
    count = 0
    candidate_end = candidate_start + timedelta(hours=OCCUPANCY_HOURS)
    for dispatch in db.DISPATCHES.values():
        if dispatch["risk_zone_id"] != zone_id:
            continue
        if dispatch["status"] not in ("VENDOR_ASSIGNED", "ON_SITE"):
            continue
        window = _window(dispatch)
        if window is None:
            continue
        start, end = window
        if _overlaps(start, end, candidate_start, candidate_end):
            count += 1
    return count


def _overlaps(a_start, a_end, b_start, b_end):
    return a_start < b_end and b_start < a_end


# --------------------------------------------------------------------------
# acknowledge / release
# --------------------------------------------------------------------------
@bp.route("/hnw/wildfire-events/properties/<property_id>/dispatch-ack", methods=["POST"])
def dispatch_ack(property_id):
    authorize(("AgencyProducer",))
    prop = core.get(db.PROPERTIES, property_id, "Property")
    data = reqs.body()
    zone_id = reqs.string(data, "risk_zone_id", required=True)
    zone = core.get(db.ZONES, zone_id, "RiskZone")
    reqs.integer(data, "property_id", default=None)
    prop = core.get(db.PROPERTIES, property_id, "Property")
    if prop["risk_zone_id"] != zone_id:
        raise err("ERR_NOT_FOUND", "The property is not bound to this risk zone.")
    assigned = _assigned_dispatch(property_id)
    if assigned is None:
        raise err("ERR_INVALID_STATE",
                  "No dispatch of this property is in VENDOR_ASSIGNED.")
    supplied = data.get("vendor_ref")
    if supplied is not None and supplied != assigned["vendor_ref"]:
        raise err("ERR_INVALID_STATE",
                  "The supplied vendor_ref does not match the assigned vendor.")
    # The temporal gate is a precondition of the edge itself.
    if zone["state_event"] != "ACTIVE":
        raise err("ERR_ZONE_EVENT_INACTIVE", "The zone's event has dropped below ACTIVE.")
    # Supplying a reference that matches the property's assigned vendor
    # re-affirms the assignment (PRD §3.6) — no state write is required.
    if supplied is None:
        if zone["concentration_band"] == "CRITICAL":
            raise err("ERR_INVALID_STATE",
                      "The zone's concentration band is CRITICAL; release is refused.")
        assigned["status"] = "REQUESTED"
        assigned["vendor_ref"] = None
        assigned["assigned_at"] = None
        core.touch(assigned)
    core.recompute_property(property_id)
    return ok(render(assigned))


def _assigned_dispatch(property_id):
    rows = [d for d in db.DISPATCHES.values()
            if d["property_id"] == property_id and d["status"] == "VENDOR_ASSIGNED"]
    if not rows:
        return None
    rows.sort(key=lambda d: d["created_at"])
    return rows[-1]


# --------------------------------------------------------------------------
# advance
# --------------------------------------------------------------------------
@bp.route("/hnw/wildfire-events/dispatches/<dispatch_id>/advance", methods=["POST"])
def advance(dispatch_id):
    authorize(("Underwriter",))
    dispatch = core.get(db.DISPATCHES, dispatch_id, "WildfireDefenseDispatch")
    status = dispatch["status"]
    if status == "VENDOR_ASSIGNED":
        dispatch["status"] = "ON_SITE"
        core.touch(dispatch)
    elif status == "ON_SITE":
        dispatch["status"] = "COMPLETED"
        core.touch(dispatch)
        _on_completion(dispatch)
    elif status == "REQUESTED":
        raise err("ERR_INVALID_STATE",
                  "A REQUESTED dispatch must be assigned by a vendor poll first.")
    else:
        raise err("ERR_INVALID_STATE",
                  "Only a REQUESTED, VENDOR_ASSIGNED or ON_SITE dispatch may be advanced.")
    prop = db.PROPERTIES.get(dispatch["property_id"])
    if prop is not None:
        core.recompute_property(prop["id"])
    if dispatch["status"] == "COMPLETED" and prop is not None:
        # The dispatch has left VENDOR_ASSIGNED/ON_SITE, so the defence exemption
        # it conferred may lapse and the posture must be re-derived.
        core.stamp_posture_if_changed(prop)
    return ok(render(dispatch))


def _on_completion(dispatch):
    prop = db.PROPERTIES.get(dispatch["property_id"])
    if prop is None:
        return
    core.attach_requirement(prop, "DEFENSIBLE_SPACE", "CLEARED", "DEFENSE_FOLLOW_UP",
                            add_days(db.now(), 14))


# --------------------------------------------------------------------------
# reads
# --------------------------------------------------------------------------
@bp.route("/hnw/properties/<property_id>/wildfire-dispatches", methods=["GET"])
def list_property_dispatches(property_id):
    authorize(DISPATCH_READERS)
    core.get(db.PROPERTIES, property_id, "Property")
    limit, offset = reqs.pagination()
    rows = [d for d in db.DISPATCHES.values() if d["property_id"] == property_id]
    status = reqs.query("status")
    if status:
        rows = [d for d in rows if d["status"] == status]
    rows = reqs.sorted_by_created(rows)
    page, meta = paginate(rows, limit, offset)
    return array(render_list(page), meta)


@bp.route("/hnw/risk-zones/<zone_id>/wildfire-dispatches", methods=["GET"])
def list_zone_dispatches(zone_id):
    authorize(ZONE_DISPATCH_READERS)
    core.get(db.ZONES, zone_id, "RiskZone")
    limit, offset = reqs.pagination()
    rows = [d for d in db.DISPATCHES.values() if d["risk_zone_id"] == zone_id]
    status = reqs.query("status")
    if status:
        rows = [d for d in rows if d["status"] == status]
    rows = reqs.sorted_by_created(rows)
    page, meta = paginate(rows, limit, offset)
    return array(render_list(page), meta)