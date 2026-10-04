"""Formula projects (PRD 3.4): compressed six-week development loop
IN_DEVELOPMENT <-> SAMPLE_REVIEW with a three-round budget; rejection at the
cap auto-abandons. The reformulation cascade reopens APPROVED projects.
"""
from datetime import timedelta

from flask import Blueprint

from core import clock
from core.auth import authenticate, forbid, require_role
from core.constants import (
    COMPRESSED_FORMULA_WEEKS,
    MAX_FORMULA_ROUNDS,
    ROLE_MANUFACTURER_REP,
    ROLE_SOURCING_LEAD,
)
from core.envelope import pub, success_object
from core.errors import err, not_found
from core.pagination import list_response
from core.store import new_record, store, touch
from core.validate import get_body, req_enum, req_str

bp = Blueprint("formulas", __name__)

STATUSES = ("IN_DEVELOPMENT", "SAMPLE_REVIEW", "APPROVED", "ABANDONED")


@bp.post("/formula-projects")
def create_formula_project():
    _, role = authenticate()
    require_role(role, ROLE_SOURCING_LEAD)
    body = get_body()
    product_id = req_str(body, "product_id")
    cm_id = req_str(body, "contract_manufacturer_id")
    brief = req_str(body, "brief")
    product = store.products.get(product_id)
    if product is None:
        raise not_found("ERR_PRODUCT_NOT_FOUND", "product not found")
    cm = store.manufacturers.get(cm_id)
    if cm is None:
        raise not_found("ERR_MANUFACTURER_NOT_FOUND", "contract manufacturer not found")
    if cm["status"] != "ACTIVE":
        raise err("ERR_CM_SUSPENDED", "the contract manufacturer is suspended")
    rec = new_record(
        {
            "product_id": product_id,
            "contract_manufacturer_id": cm_id,
            "brief": brief,
            "status": "IN_DEVELOPMENT",
            "round_count": 1,
            "due_at": None,  # set below from the record's created_at
            "submitted_at": None,
            "is_late": False,
            "formula_version": None,
        }
    )
    rec["due_at"] = rec["created_at"] + timedelta(weeks=COMPRESSED_FORMULA_WEEKS)
    store.formula_projects[rec["id"]] = rec
    return success_object(pub(rec), code=201)


@bp.get("/formula-projects")
def list_formula_projects():
    authenticate()
    return list_response(
        store.formula_projects.values(),
        {
            "product_id": "product_id",
            "contract_manufacturer_id": "contract_manufacturer_id",
            "status": "status",
        },
        pub,
    )


@bp.get("/formula-projects/<rid>")
def get_formula_project(rid):
    authenticate()
    rec = store.formula_projects.get(rid)
    if rec is None:
        raise not_found("ERR_FORMULA_PROJECT_NOT_FOUND", "formula project not found")
    return success_object(pub(rec))


@bp.patch("/formula-projects/<rid>")
def patch_formula_project(rid):
    user_id, role = authenticate()
    require_role(role, ROLE_SOURCING_LEAD, ROLE_MANUFACTURER_REP)
    body = get_body()
    raw_target = body.get("status")
    # Field-level authorization (priority 2): a sample submission may be made
    # by SourcingLead or by the project's own ManufacturerRep; every other
    # status target requires SourcingLead. The role class is decided on the raw
    # value so it precedes shape validation (priority 3) and path resolution
    # (priority 4); the ownership half of the split needs the record, so it is
    # checked right after resolution.
    if raw_target is not None and raw_target != "SAMPLE_REVIEW":
        require_role(role, ROLE_SOURCING_LEAD)
    target = None
    if raw_target is not None:
        target = req_enum(body, "status", STATUSES)
    rec = store.formula_projects.get(rid)
    if rec is None:
        raise not_found("ERR_FORMULA_PROJECT_NOT_FOUND", "formula project not found")
    if (
        target == "SAMPLE_REVIEW"
        and role == ROLE_MANUFACTURER_REP
        and user_id != rec["contract_manufacturer_id"]
    ):
        forbid("a ManufacturerRep may only submit its own manufacturer's samples")
    if target is None:
        return success_object(pub(rec))

    current = rec["status"]
    if target == "SAMPLE_REVIEW" and current == "IN_DEVELOPMENT":
        rec["submitted_at"] = clock.now()
        rec["is_late"] = rec["submitted_at"] > rec["due_at"]
        rec["status"] = "SAMPLE_REVIEW"
    elif target == "APPROVED" and current == "SAMPLE_REVIEW":
        rec["formula_version"] = rec["round_count"]
        rec["status"] = "APPROVED"
    elif target == "IN_DEVELOPMENT" and current == "SAMPLE_REVIEW":
        # Sample rejection: at the round cap the project auto-abandons instead.
        if rec["round_count"] >= MAX_FORMULA_ROUNDS:
            rec["status"] = "ABANDONED"
        else:
            rec["round_count"] += 1
            rec["status"] = "IN_DEVELOPMENT"
    elif target == "ABANDONED" and current == "IN_DEVELOPMENT":
        rec["status"] = "ABANDONED"
    else:
        raise err(
            "ERR_INVALID_STATE",
            "cannot transition a formula project from %s to %s" % (current, target),
        )
    touch(rec)
    return success_object(pub(rec))
