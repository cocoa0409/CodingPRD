"""RightsProperty lifecycle."""
import clock
import util
from db import db
from errors import raise_err, ERR_INVALID_STATE, ERR_INVALID_REQUEST
from services import calc

SPORTS = {"NFL", "NBA", "MLB", "SOCCER", "GOLF", "RACING", "TENNIS"}
AMORT = {"STRAIGHT_LINE", "EVENT_WEIGHTED"}


def serialize(prop):
    from serialize import serialize as _s
    out = _s(prop)
    # counters recomputed from windows
    sim = sum(1 for w in db.windows.values()
              if w["property_id"] == prop["id"] and w["rights_mode"] == "SIMULCAST"
              and w["status"] not in ("CANCELLED", "REPLACED"))
    exc = sum(1 for w in db.windows.values()
              if w["property_id"] == prop["id"] and w["rights_mode"] == "EXCLUSIVE"
              and w["status"] not in ("CANCELLED", "REPLACED"))
    out["simulcast_windows_consumed"] = sim
    out["exclusive_windows_consumed"] = exc
    out["amortized_fee_cents"] = calc.amortized_fee_cents(prop)
    return out


def create_property(body):
    util.require_fields(body, [
        "property_code", "display_name", "sport", "rights_fee_cents",
        "term_start", "term_end", "amortization_method",
        "simulcast_windows_count", "exclusive_windows_count",
        "minimum_exclusive_ratio_pct", "required_local_breaks_per_event",
    ])
    util.req_str(body["property_code"], "property_code")
    util.req_str(body["display_name"], "display_name")
    util.req_enum(body["sport"], "sport", SPORTS)
    fee = util.req_int(body["rights_fee_cents"], "rights_fee_cents", minimum=0)
    term_start = util.req_dt(body["term_start"], "term_start")
    term_end = util.req_dt(body["term_end"], "term_end")
    if not term_end > term_start:
        raise_err(ERR_INVALID_REQUEST, "term_end must be strictly after term_start")
    util.req_enum(body["amortization_method"], "amortization_method", AMORT)
    sim_count = util.req_int(body["simulcast_windows_count"], "simulcast_windows_count", minimum=0)
    exc_count = util.req_int(body["exclusive_windows_count"], "exclusive_windows_count", minimum=0)
    ratio = util.req_int(body["minimum_exclusive_ratio_pct"], "minimum_exclusive_ratio_pct", minimum=0, maximum=100)
    local_breaks = util.req_int(body["required_local_breaks_per_event"], "required_local_breaks_per_event", minimum=0)
    for p in db.properties.values():
        if p["property_code"] == body["property_code"]:
            raise_err(ERR_INVALID_REQUEST, "property_code must be unique")
    now_iso = clock.now_iso()
    prop = {
        "id": util.new_id(),
        "property_code": body["property_code"],
        "display_name": body["display_name"],
        "sport": body["sport"],
        "status": "NEGOTIATION",
        "rights_fee_cents": fee,
        "term_start": term_start,
        "term_end": term_end,
        "amortization_method": body["amortization_method"],
        "simulcast_windows_count": sim_count,
        "exclusive_windows_count": exc_count,
        "minimum_exclusive_ratio_pct": ratio,
        "required_local_breaks_per_event": local_breaks,
        "created_at": now_iso,
        "updated_at": now_iso,
        "version": 1,
    }
    db.properties[prop["id"]] = prop
    return prop


def activate(prop):
    if prop["status"] != "NEGOTIATION":
        raise_err(ERR_INVALID_STATE, "property not in NEGOTIATION")
    now = clock.now()
    if not (prop["term_start"] <= now < prop["term_end"]):
        raise_err(ERR_INVALID_STATE, "current time outside property term")
    if not prop["rights_fee_cents"] > 0:
        raise_err(ERR_INVALID_STATE, "rights_fee_cents must be > 0")
    prop["status"] = "ACTIVE"
    util.touch(prop)
    calc.recompute_amortization(prop)
    return prop


def suspend(prop):
    if prop["status"] != "ACTIVE":
        raise_err(ERR_INVALID_STATE, "property not ACTIVE")
    has_active_window = any(
        w["property_id"] == prop["id"] and w["status"] in ("SCHEDULED", "LIVE")
        for w in db.windows.values()
    )
    if not has_active_window:
        raise_err(ERR_INVALID_STATE, "no SCHEDULED or LIVE window to suspend")
    prop["status"] = "SUSPENDED"
    util.touch(prop)
    from services.window import cancel_window
    for win in list(db.windows.values()):
        if win["property_id"] == prop["id"] and win["status"] == "SCHEDULED":
            cancel_window(win)
    return prop


def unsuspend(prop):
    if prop["status"] != "SUSPENDED":
        raise_err(ERR_INVALID_STATE, "property not SUSPENDED")
    now = clock.now()
    for rule in db.territory_rules.values():
        if rule["rule_status"] != "ACTIVE" or rule["rule_kind"] != "BLACKOUT":
            continue
        win = db.windows.get(rule["window_id"])
        if win is None or win["property_id"] != prop["id"]:
            continue
        if rule["effective_start"] <= now < rule["effective_end"]:
            raise_err(ERR_INVALID_STATE, "active blackout covers current time")
    prop["status"] = "ACTIVE"
    util.touch(prop)
    return prop


def terminate(prop):
    if prop["status"] not in ("NEGOTIATION", "ACTIVE"):
        raise_err(ERR_INVALID_STATE, "property cannot be terminated from current state")
    if prop["status"] == "ACTIVE":
        if any(w["property_id"] == prop["id"] and w["status"] == "LIVE"
               for w in db.windows.values()):
            raise_err(ERR_INVALID_STATE, "a window of this property is LIVE")
    prop["status"] = "TERMINATED"
    util.touch(prop)
    from services.window import cancel_window
    for win in list(db.windows.values()):
        if win["property_id"] == prop["id"] and win["status"] == "SCHEDULED":
            cancel_window(win)
    return prop
