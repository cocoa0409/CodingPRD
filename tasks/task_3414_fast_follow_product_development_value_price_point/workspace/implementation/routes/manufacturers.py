"""Contract manufacturers (PRD 3.4): onboard, read, suspend/reactivate, and
revise quarterly slot capacity. Suspension blocks new formula projects, new
quotes, and quote acceptance (ERR_CM_SUSPENDED).
"""
from flask import Blueprint

from core.auth import authenticate, require_role
from core.constants import ROLE_SOURCING_LEAD
from core.envelope import pub, success_object
from core.errors import err, not_found
from core.store import new_record, store, touch
from core.validate import (
    get_body,
    opt_int,
    req_enum,
    req_int,
    req_str,
    req_str_list,
)

bp = Blueprint("manufacturers", __name__)

STATUSES = ("ACTIVE", "SUSPENDED")
QUALITY_TIERS = ("STANDARD", "PREMIUM")


@bp.post("/manufacturers")
def create_manufacturer():
    _, role = authenticate()
    require_role(role, ROLE_SOURCING_LEAD)
    body = get_body()
    rec = new_record(
        {
            "name": req_str(body, "name"),
            "capabilities": req_str_list(body, "capabilities"),
            "base_lead_time_weeks": req_int(body, "base_lead_time_weeks", minimum=1),
            "moq_units": req_int(body, "moq_units", minimum=1),
            "quality_tier": req_enum(body, "quality_tier", QUALITY_TIERS),
            "capacity_slots_per_quarter": req_int(
                body, "capacity_slots_per_quarter", minimum=0
            ),
            "status": "ACTIVE",
        }
    )
    store.manufacturers[rec["id"]] = rec
    return success_object(pub(rec), code=201)


@bp.get("/manufacturers/<rid>")
def get_manufacturer(rid):
    authenticate()
    rec = store.manufacturers.get(rid)
    if rec is None:
        raise not_found("ERR_MANUFACTURER_NOT_FOUND", "contract manufacturer not found")
    return success_object(pub(rec))


@bp.patch("/manufacturers/<rid>")
def patch_manufacturer(rid):
    _, role = authenticate()
    require_role(role, ROLE_SOURCING_LEAD)
    body = get_body()
    target = None
    if "status" in body and body["status"] is not None:
        target = req_enum(body, "status", STATUSES)
    new_capacity = None
    if "capacity_slots_per_quarter" in body and body["capacity_slots_per_quarter"] is not None:
        new_capacity = req_int(body, "capacity_slots_per_quarter", minimum=0)
    rec = store.manufacturers.get(rid)
    if rec is None:
        raise not_found("ERR_MANUFACTURER_NOT_FOUND", "contract manufacturer not found")
    changed = False
    if target is not None:
        current = rec["status"]
        if (current, target) in (("ACTIVE", "SUSPENDED"), ("SUSPENDED", "ACTIVE")):
            rec["status"] = target
            changed = True
        else:
            raise err(
                "ERR_INVALID_STATE",
                "cannot transition a manufacturer from %s to %s" % (current, target),
            )
    if new_capacity is not None:
        rec["capacity_slots_per_quarter"] = new_capacity
        changed = True
    if changed:
        touch(rec)
    return success_object(pub(rec))
