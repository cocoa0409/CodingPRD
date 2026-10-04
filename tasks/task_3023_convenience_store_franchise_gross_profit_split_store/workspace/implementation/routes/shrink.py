"""ShrinkAudit routes — counting is a separated duty from finalization."""

from datetime import timedelta
from decimal import Decimal

from flask import Blueprint

import db
import middleware
import schemas
import services
import timeutil
from errors import fail
from response import ok
from routes.common import SHARED, list_records

bp = Blueprint("shrink_audits", __name__)

CADENCE_DAYS = 31


@bp.post("/shrink-audits")
@middleware.auth(("FranchisorAdmin",))
def create_audit():
    payload = middleware.body(
        required=("store_id", "period_start", "period_end", "book_inventory_cents"),
    )
    store = services.require_store(payload["store_id"])
    period_start = timeutil.required_utc(payload["period_start"])
    period_end = timeutil.required_utc(payload["period_end"])
    if period_end <= period_start:
        fail("ERR_INVALID_REQUEST")
    book = middleware.non_negative_int(payload["book_inventory_cents"], "book_inventory_cents")

    for existing in db.all_of("shrink_audits"):
        if existing["store_id"] != store["id"]:
            continue
        if timeutil.overlaps(existing["period_start"], existing["period_end"],
                             period_start, period_end):
            fail("ERR_AUDIT_PERIOD_OVERLAP")

    record = db.insert("shrink_audits", {
        "store_id": store["id"],
        "period_start": period_start,
        "period_end": period_end,
        "book_inventory_cents": book,
        "physical_inventory_cents": None,
        "shrink_cents": None,
        "shrink_charge_cents": Decimal("0.00"),
        "status": "SCHEDULED",
        "recovered_in_settlement": False,
    })
    return ok(schemas.dump("shrink_audits", record), 201)


@bp.get("/shrink-audits")
@middleware.auth(SHARED)
def list_audits():
    return list_records("shrink_audits", ("store_id", "status"))


@bp.get("/shrink-audits/<audit_id>")
@middleware.auth(SHARED)
def get_audit(audit_id):
    audit = services.require("shrink_audits", audit_id)
    return ok(schemas.dump("shrink_audits", audit))


@bp.post("/shrink-audits/<audit_id>/count")
@middleware.auth(("FieldAuditor",))
def count_audit(audit_id):
    audit = services.require("shrink_audits", audit_id)
    payload = middleware.body(optional=("physical_inventory_cents", "recount"),
                              defaults={"recount": False})
    recount = payload["recount"]
    if not isinstance(recount, bool):
        fail("ERR_INVALID_REQUEST")

    if recount:
        services.require_state(audit, "COUNTED")
        audit["status"] = "SCHEDULED"
        audit["physical_inventory_cents"] = None
        audit["shrink_cents"] = None
        audit["shrink_charge_cents"] = Decimal("0.00")
        db.touch(audit)
        return ok(schemas.dump("shrink_audits", audit))

    services.require_state(audit, "SCHEDULED")
    if "physical_inventory_cents" not in payload:
        fail("ERR_INVALID_REQUEST")
    physical = payload["physical_inventory_cents"]
    if isinstance(physical, bool) or not isinstance(physical, int):
        fail("ERR_INVALID_REQUEST")
    if physical < 0:
        fail("ERR_INVALID_REQUEST")

    audit["physical_inventory_cents"] = physical
    audit["shrink_cents"] = audit["book_inventory_cents"] - physical
    percentage = services.agreement_responsibility_pct(audit["store_id"], "shrink_responsibility_pct")
    audit["shrink_charge_cents"] = services.shrink_charge(audit, percentage)
    audit["counted_pct"] = str(percentage)
    audit["status"] = "COUNTED"
    db.touch(audit)
    return ok(schemas.dump("shrink_audits", audit))


@bp.post("/shrink-audits/<audit_id>/finalize")
@middleware.auth(("FranchisorAdmin",))
def finalize_audit(audit_id):
    audit = services.require("shrink_audits", audit_id)
    services.require_state(audit, "COUNTED")
    if db.clock() < audit["period_end"]:
        fail("ERR_AUDIT_PERIOD_NOT_CLOSED")

    previous = None
    for other in db.all_of("shrink_audits"):
        if other["id"] == audit["id"] or other["store_id"] != audit["store_id"]:
            continue
        if other["status"] != "FINALIZED":
            continue
        if previous is None or other["period_end"] > previous["period_end"]:
            previous = other
    if previous is not None:
        if audit["period_start"] > previous["period_end"] + timedelta(days=CADENCE_DAYS):
            fail("ERR_AUDIT_CADENCE_REQUIRED")

    percentage = services.agreement_responsibility_pct(audit["store_id"], "shrink_responsibility_pct")
    audit["status"] = "FINALIZED"
    audit["shrink_charge_cents"] = services.shrink_charge(audit, percentage)
    audit["recovered_in_settlement"] = False
    db.touch(audit)

    franchisee = db.get("franchisees", services._store_owner(audit["store_id"]))
    if franchisee is not None:
        services.recalculate_franchisee(franchisee)
    return ok(schemas.dump("shrink_audits", audit))