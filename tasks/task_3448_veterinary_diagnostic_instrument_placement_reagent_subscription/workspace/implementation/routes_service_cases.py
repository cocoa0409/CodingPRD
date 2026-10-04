"""Service cases: open (REPAIR / PREVENTIVE_CALIBRATION), DISPATCH, RESOLVE,
CANCEL — with analyzer/loaner compensation, uptime recompute, and the
service-credit cascade."""
from datetime import timedelta
from decimal import Decimal

from flask import Blueprint

import db
import ser
import services
import util
from constants import RESPONSE_SLA_HOURS
from errors import err

bp = Blueprint("service_cases", __name__)


@bp.post("/api/service-cases")
def create_case():
    _, role = util.auth()
    util.require(role, ["FieldServiceEngineer"])
    b = util.body()

    analyzer_id = b.get("analyzer_id")
    if analyzer_id is None:
        raise err("ERR_INVALID_REQUEST", "analyzer_id is required")
    an = db.analyzers.get(analyzer_id)
    if an is None:
        raise err("ERR_ANALYZER_NOT_FOUND", "analyzer_id does not exist")
    loaner_id = b.get("loaner_analyzer_id")
    loaner = None
    if loaner_id is not None:
        loaner = db.analyzers.get(loaner_id)
        if loaner is None:
            raise err("ERR_ANALYZER_NOT_FOUND", "loaner_analyzer_id does not exist")

    case_type = b.get("case_type")
    if case_type not in ("REPAIR", "PREVENTIVE_CALIBRATION"):
        # PROFICIENCY_REMEDIATION is system-created only; anything else is not
        # a valid case_type either.
        raise err("ERR_INVALID_REQUEST",
                  "case_type must be REPAIR or PREVENTIVE_CALIBRATION")

    if an["operational_status"] != "IN_SERVICE":
        raise err("ERR_ANALYZER_INVALID_STATE",
                  "the serviced analyzer must be IN_SERVICE")
    if loaner is not None:
        if not loaner["is_loaner_unit"]:
            raise err("ERR_ANALYZER_INVALID_STATE",
                      "the loaner unit must be flagged is_loaner_unit")
        if loaner["operational_status"] != "IN_SERVICE":
            raise err("ERR_ANALYZER_INVALID_STATE",
                      "the loaner unit must be IN_SERVICE")

    now = db.now()
    c = services.stamp({
        "analyzer_id": analyzer_id,
        "case_type": case_type,
        "loaner_analyzer_id": loaner_id,
        "status": "OPEN",
        "opened_at": util.iso_z(now),
        "_opened_at": now,
        "response_due_at": util.iso_ms(now + timedelta(hours=RESPONSE_SLA_HOURS)),
        "_response_due_at": now + timedelta(hours=RESPONSE_SLA_HOURS),
        "_resolved_at": None,
        "downtime_hours": None,
        "sla_met": None,
        "resolution_note": None,
    })
    db.cases[c["id"]] = c
    an["operational_status"] = "UNDER_SERVICE"
    services.bump(an)
    if loaner is not None:
        loaner["operational_status"] = "ON_LOAN"
        services.bump(loaner)
    return util.ok(ser.case(c), code=201)


@bp.patch("/api/service-cases/<cid>")
def patch_case(cid):
    _, role = util.auth()
    util.require(role, ["FieldServiceEngineer"])
    c = db.cases.get(cid)
    if c is None:
        raise err("ERR_SERVICE_CASE_NOT_FOUND", "service case does not exist")
    b = util.body()
    action = b.get("action")
    if action not in ("DISPATCH", "RESOLVE", "CANCEL"):
        raise err("ERR_INVALID_REQUEST",
                  "action must be DISPATCH, RESOLVE or CANCEL")

    an = db.analyzers.get(c["analyzer_id"])

    if action == "DISPATCH":
        if c["status"] != "OPEN":
            raise err("ERR_SERVICE_CASE_INVALID_STATE",
                      "DISPATCH requires status OPEN")
        c["status"] = "DISPATCHED"
        services.bump(c)
        return util.ok(ser.case(c))

    if action == "RESOLVE":
        if c["status"] != "DISPATCHED":
            raise err("ERR_SERVICE_CASE_INVALID_STATE",
                      "RESOLVE requires status DISPATCHED")
        if b.get("resolution_note") is not None and not isinstance(
                b["resolution_note"], str):
            raise err("ERR_INVALID_REQUEST", "resolution_note must be a string")
        now = db.now()
        c["status"] = "RESOLVED"
        c["_resolved_at"] = now
        elapsed_hours = Decimal(
            str((now - c["_opened_at"]).total_seconds())) / Decimal(3600)
        c["downtime_hours"] = util.round_cents(elapsed_hours)
        c["sla_met"] = now <= c["_response_due_at"]
        if b.get("resolution_note") is not None:
            c["resolution_note"] = b["resolution_note"]
        services.bump(c)
        # Return units to service; accrue downtime; recompute uptime.
        if an is not None:
            if an["operational_status"] == "UNDER_SERVICE":
                an["operational_status"] = "IN_SERVICE"
            an["total_downtime_hours"] += c["downtime_hours"]
            breach = services.recompute_uptime(an, now)
            services.bump(an)
            services.maybe_credit(an, breach)
        loaner_id = c.get("loaner_analyzer_id")
        if loaner_id:
            loaner = db.analyzers.get(loaner_id)
            if loaner is not None and loaner["operational_status"] == "ON_LOAN":
                loaner["operational_status"] = "IN_SERVICE"
                services.bump(loaner)
        return util.ok(ser.case(c))

    # CANCEL from OPEN or DISPATCHED with unit-return compensation, no downtime.
    if c["status"] not in ("OPEN", "DISPATCHED"):
        raise err("ERR_SERVICE_CASE_INVALID_STATE",
                  "CANCEL requires status OPEN or DISPATCHED")
    c["status"] = "CANCELLED"
    services.bump(c)
    if an is not None and an["operational_status"] == "UNDER_SERVICE":
        an["operational_status"] = "IN_SERVICE"
        services.bump(an)
    loaner_id = c.get("loaner_analyzer_id")
    if loaner_id:
        loaner = db.analyzers.get(loaner_id)
        if loaner is not None and loaner["operational_status"] == "ON_LOAN":
            loaner["operational_status"] = "IN_SERVICE"
            services.bump(loaner)
    return util.ok(ser.case(c))
