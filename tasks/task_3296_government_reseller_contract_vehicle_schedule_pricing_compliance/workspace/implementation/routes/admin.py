"""PlatformAdmin surface: logical clock + manufacturer lifecycle."""
from flask import request

import db
from server_core import app
from errors import err, not_found, invalid_state, ERR_UNIQUENESS_VIOLATION, ERR_INVALID_PRICE_PERIOD
from util import envelope, respond_list, body_arg, new_entity, parse_iso, fmt_iso, DUNS_RE


def manufacturer_view(m):
    return {k: m[k] for k in ("id", "legal_name", "duns", "manufacturer_type",
                              "headquarters_country", "designated_countries",
                              "status", "created_at", "updated_at", "version")}


@app.post("/_clock/set_current_utc")
def clock_set():
    to_iso8601 = body_arg("to_iso8601")
    dt = parse_iso(to_iso8601)
    if dt is None:
        raise err(ERR_INVALID_PRICE_PERIOD, "to_iso8601 must be a valid ISO-8601 timestamp", 422)
    db.set_logical_clock(fmt_iso(dt))
    return envelope({"current_utc": db.logical_clock}, 200)


@app.post("/manufacturers")
def manufacturers_create():
    duns = body_arg("duns")
    if not isinstance(duns, str) or not DUNS_RE.match(duns):
        raise err(ERR_UNIQUENESS_VIOLATION, "duns must be exactly 9 digits", 409)
    for m in db.manufacturers.values():
        if m["duns"] == duns:
            raise err(ERR_UNIQUENESS_VIOLATION, "duns must be unique across manufacturers", 409)
    designated = body_arg("designated_countries", [])
    if not isinstance(designated, list):
        designated = []
    m = new_entity(db, db.manufacturers, {},
                   legal_name=body_arg("legal_name"),
                   duns=duns,
                   manufacturer_type=body_arg("manufacturer_type"),
                   headquarters_country=body_arg("headquarters_country"),
                   designated_countries=designated,
                   status="ACTIVE")
    return envelope(manufacturer_view(m), 201)


@app.get("/manufacturers")
def manufacturers_list():
    items = list(db.manufacturers.values())
    status = request.args.get("status")
    if status is not None:
        items = [m for m in items if m["status"] == status]
    return respond_list([manufacturer_view(m) for m in items])


@app.get("/manufacturers/<mid>")
def manufacturers_get(mid):
    m = db.manufacturers.get(mid)
    if m is None:
        raise not_found("manufacturer not found")
    return envelope(manufacturer_view(m), 200)


@app.post("/manufacturers/<mid>/suspend")
def manufacturers_suspend(mid):
    m = db.manufacturers.get(mid)
    if m is None:
        raise not_found("manufacturer not found")
    if m["status"] != "ACTIVE":
        raise invalid_state("manufacturer is not ACTIVE")
    m["status"] = "SUSPENDED"
    from util import bump
    bump(m)
    return envelope(manufacturer_view(m), 200)
