"""Analyzers: install, read, drive operational/connectivity dimensions,
and the per-analyzer service-case discovery channel."""
from flask import Blueprint, request

import db
import ser
import services
import util
from errors import err

bp = Blueprint("analyzers", __name__)

OPERATIONAL_ENUM = ("INSTALLED", "IN_SERVICE", "UNDER_SERVICE", "ON_LOAN",
                    "DECOMMISSIONED")
CONNECTIVITY_ENUM = ("NOT_CONFIGURED", "ACTIVE", "DEGRADED")


def _load_analyzer(aid):
    an = db.analyzers.get(aid)
    if an is None:
        raise err("ERR_ANALYZER_NOT_FOUND", "analyzer does not exist")
    return an


@bp.post("/api/analyzers")
def create_analyzer():
    _, role = util.auth()
    util.require(role, ["FieldServiceEngineer"])
    b = util.body()

    clinic_id = b.get("clinic_id")
    agreement_id = b.get("agreement_id")
    if clinic_id is None:
        raise err("ERR_INVALID_REQUEST", "clinic_id is required")
    clinic = db.clinics.get(clinic_id)
    if clinic is None:
        raise err("ERR_CLINIC_NOT_FOUND", "clinic_id does not exist")
    if agreement_id is None:
        raise err("ERR_INVALID_REQUEST", "agreement_id is required")
    ag = db.agreements.get(agreement_id)
    if ag is None:
        raise err("ERR_AGREEMENT_NOT_FOUND", "agreement_id does not exist")

    serial = b.get("serial_number")
    if not isinstance(serial, str) or not serial:
        raise err("ERR_INVALID_REQUEST", "serial_number is required")
    for other in db.analyzers.values():
        if other["serial_number"] == serial:
            raise err("ERR_INVALID_REQUEST",
                      "serial_number must be unique across all analyzers")
    loaner = b.get("is_loaner_unit", False)
    if not isinstance(loaner, bool):
        raise err("ERR_INVALID_REQUEST", "is_loaner_unit must be boolean")

    if ag["status"] not in ("ACTIVE", "RENEGOTIATION", "BREACHED"):
        raise err("ERR_AGREEMENT_INVALID_STATE",
                  "installation requires the agreement to be ACTIVE, "
                  "RENEGOTIATION or BREACHED")

    an = services.stamp({
        "clinic_id": clinic_id,
        "agreement_id": agreement_id,
        "model": ag["model"],
        "serial_number": serial,
        "is_loaner_unit": loaner,
        "operational_status": "INSTALLED",
        "connectivity_status": "NOT_CONFIGURED",
        "proficiency_standing": "LAPSED",
        "_qc_valid_until": None,
        "total_downtime_hours": 0,
        "reported_uptime_pct": 1.0,
        "breach_uptime_pct": 1.0,
    })
    db.analyzers[an["id"]] = an
    return util.ok(ser.analyzer(an), code=201)


@bp.get("/api/analyzers/<aid>")
def get_analyzer(aid):
    util.auth()
    return util.ok(ser.analyzer(_load_analyzer(aid)))


@bp.get("/api/analyzers")
def list_analyzers():
    util.auth()
    items = util.sorted_items(db.analyzers.values())
    cid = request.args.get("clinic_id")
    if cid is not None:
        items = [a for a in items if a["clinic_id"] == cid]
    gid = request.args.get("agreement_id")
    if gid is not None:
        items = [a for a in items if a["agreement_id"] == gid]
    ops = request.args.get("operational_status")
    if ops is not None:
        items = [a for a in items if a["operational_status"] == ops]
    return util.paginate([ser.analyzer(a) for a in items])


@bp.patch("/api/analyzers/<aid>")
def patch_analyzer(aid):
    _, role = util.auth()
    util.require(role, ["FieldServiceEngineer"])
    an = _load_analyzer(aid)
    b = util.body()

    ops = b.get("operational_status")
    con = b.get("connectivity_status")
    if ops is not None and ops not in OPERATIONAL_ENUM:
        raise err("ERR_INVALID_REQUEST", "invalid operational_status")
    if con is not None and con not in CONNECTIVITY_ENUM:
        raise err("ERR_INVALID_REQUEST", "invalid connectivity_status")
    # UNDER_SERVICE / ON_LOAN are system-driven only, never accepted from clients.
    if ops in ("UNDER_SERVICE", "ON_LOAN"):
        raise err("ERR_INVALID_REQUEST",
                  "UNDER_SERVICE and ON_LOAN are system-driven states")

    # Validate the operational transition.
    if ops is not None:
        cur = an["operational_status"]
        if ops == "IN_SERVICE":
            if cur != "INSTALLED":
                raise err("ERR_ANALYZER_INVALID_STATE",
                          "entering service requires operational_status INSTALLED")
            ag = db.agreements.get(an["agreement_id"])
            if ag is None or ag["status"] not in ("ACTIVE", "RENEGOTIATION",
                                                  "BREACHED"):
                raise err("ERR_AGREEMENT_INVALID_STATE",
                          "the agreement must be ACTIVE, RENEGOTIATION or BREACHED")
        elif ops == "DECOMMISSIONED":
            if cur not in ("INSTALLED", "IN_SERVICE"):
                raise err("ERR_ANALYZER_INVALID_STATE",
                          "decommission requires INSTALLED or IN_SERVICE")
            for c in db.cases.values():
                if (c["analyzer_id"] == an["id"]
                        and c["status"] in ("OPEN", "DISPATCHED")):
                    raise err("ERR_SERVICE_CASE_INVALID_STATE",
                              "decommission is blocked by an OPEN or DISPATCHED "
                              "service case")
        else:
            raise err("ERR_ANALYZER_INVALID_STATE",
                      f"operational transition to {ops} is not allowed")

    # Validate the connectivity transition (frozen while DECOMMISSIONED,
    # including when this same request decommissions the unit).
    if con is not None:
        effective_ops = ops if ops is not None else an["operational_status"]
        if (an["operational_status"] == "DECOMMISSIONED"
                or effective_ops == "DECOMMISSIONED"):
            raise err("ERR_ANALYZER_INVALID_STATE",
                      "connectivity is frozen while DECOMMISSIONED")
        curc = an["connectivity_status"]
        if con == "ACTIVE":
            if curc not in ("NOT_CONFIGURED", "DEGRADED"):
                raise err("ERR_ANALYZER_INVALID_STATE",
                          "connectivity ACTIVE requires NOT_CONFIGURED or DEGRADED")
        elif con == "DEGRADED":
            if curc != "ACTIVE":
                raise err("ERR_ANALYZER_INVALID_STATE",
                          "connectivity DEGRADED requires ACTIVE")
        else:
            raise err("ERR_ANALYZER_INVALID_STATE",
                      f"connectivity transition to {con} is not allowed")

    if ops is not None:
        an["operational_status"] = ops
        services.bump(an)
    if con is not None:
        an["connectivity_status"] = con
        services.bump(an)
    return util.ok(ser.analyzer(an))


@bp.get("/api/analyzers/<aid>/service-cases")
def list_analyzer_cases(aid):
    util.auth()
    _load_analyzer(aid)
    items = [c for c in util.sorted_items(db.cases.values())
             if c["analyzer_id"] == aid or c["loaner_analyzer_id"] == aid]
    st = request.args.get("status")
    if st is not None:
        items = [c for c in items if c["status"] == st]
    return util.paginate([ser.case(c) for c in items])
