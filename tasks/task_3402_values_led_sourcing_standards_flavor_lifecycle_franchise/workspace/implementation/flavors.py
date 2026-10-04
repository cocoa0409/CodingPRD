"""Flavor lifecycle (PRD section 3.4).

Promotion walks DEVELOPMENT -> TEST_BATCH -> LIMITED_RUN -> CORE_LINE, one
named target_state at a time; no other promotion pairs exist. Retirement is
operational control (ParentOpsController) from LIMITED_RUN, CORE_LINE or
REVIVED and cascades to orders, slots and published claims. A REVIVED flavor
returns to CORE_LINE, closing the cycle.
"""
from flask import Blueprint

import cascades
from auth import authenticate, authorize
from db import LOGICAL_CLOCK, STORE, new_resource, public, touch
from envelope import ok
from errors import fail
from timeutil import fmt_dt
from validate import (BASE_TYPES, PROMOTE_TARGETS, get_body, req_enum,
                      req_int, req_num, req_str)

bp = Blueprint("flavors", __name__)

READ_ROLES = ("FlavorManager", "PlantScheduler", "ParentOpsController",
              "IndependentBoardMember", "FranchiseAdmin", "ShopOperator",
              "Fan", "SourcingManager")

_PROMOTE_PAIRS = {
    ("DEVELOPMENT", "TEST_BATCH"),
    ("TEST_BATCH", "LIMITED_RUN"),
    ("LIMITED_RUN", "CORE_LINE"),
}


def get_flavor(fid):
    f = STORE["flavors"].get(fid)
    if f is None:
        fail("ERR_FLAVOR_NOT_FOUND", "Flavor id does not exist")
    return f


@bp.post("/flavors")
def create_flavor():
    _, role = authenticate()
    authorize(role, ("FlavorManager",))
    body = get_body()
    name = req_str(body, "name")
    base_type = req_enum(body, "base_type", BASE_TYPES)
    chunk = req_num(body, "chunk_load_pct", 0, 100)
    swirl = req_num(body, "swirl_load_pct", 0, 100)
    price = req_int(body, "pint_price_cents", 0)
    r = new_resource()
    r.update({
        "name": name,
        "base_type": base_type,
        "chunk_load_pct": chunk,
        "swirl_load_pct": swirl,
        "pint_price_cents": price,
        "status": "DEVELOPMENT",
        "retired_at": None,
        "claim_type": "NONE",
        "claim_status": "UNCLAIMED",
        "claim_certification_ids": [],
        "claim_coverage_declared_pct": None,
        "claim_coverage_verified_pct": None,
    })
    STORE["flavors"][r["id"]] = r
    return ok(public(r), 201)


@bp.get("/flavors/<fid>")
def read_flavor(fid):
    _, role = authenticate()
    authorize(role, READ_ROLES)
    return ok(public(get_flavor(fid)))


@bp.post("/flavors/<fid>/promote")
def promote_flavor(fid):
    _, role = authenticate()
    authorize(role, ("FlavorManager",))
    f = get_flavor(fid)
    body = get_body()
    target = req_enum(body, "target_state", PROMOTE_TARGETS)
    if (f["status"], target) not in _PROMOTE_PAIRS:
        fail("ERR_INVALID_STATE",
             "Flavor in %s cannot be promoted to %s" % (f["status"], target))
    f["status"] = target
    touch(f)
    return ok(public(f))


@bp.post("/flavors/<fid>/retire")
def retire_flavor(fid):
    _, role = authenticate()
    authorize(role, ("ParentOpsController",))
    f = get_flavor(fid)
    if f["status"] not in ("LIMITED_RUN", "CORE_LINE", "REVIVED"):
        fail("ERR_INVALID_STATE",
             "Flavor in %s cannot be retired" % f["status"])
    f["retired_at"] = fmt_dt(LOGICAL_CLOCK["now"])
    cascades.retire_cascade(f)
    f["status"] = "RETIRED"
    touch(f)
    return ok(public(f))


@bp.post("/flavors/<fid>/return-to-line")
def return_to_line(fid):
    _, role = authenticate()
    authorize(role, ("FlavorManager",))
    f = get_flavor(fid)
    if f["status"] != "REVIVED":
        fail("ERR_INVALID_STATE",
             "Only a REVIVED flavor can return to the line")
    f["status"] = "CORE_LINE"
    touch(f)
    return ok(public(f))
