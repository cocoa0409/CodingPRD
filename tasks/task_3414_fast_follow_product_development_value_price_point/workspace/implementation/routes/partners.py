"""Retail partners (PRD 3.7): onboarded with a fixed category_capacities map
(the limited shelf footprint). committed_facings / available_facings are
recomputed on every read; a capacity reduction below committed facings fires
the atomic capacity-eviction cascade.
"""
from flask import Blueprint

from core.auth import authenticate, require_role
from core.constants import ROLE_RETAIL_PLANNER
from core.envelope import pub, success_object
from core.errors import not_found
from core.store import new_record, store, touch
from core.validate import get_body, req_capacity_map, req_str
from services import calc, cascade

bp = Blueprint("partners", __name__)


def _pub_partner(rec):
    data = pub(rec)
    committed, available = calc.facing_maps(
        rec["id"],
        rec["category_capacities"],
        store.line_reviews.values(),
        store.planogram_slots.values(),
    )
    data["committed_facings"] = committed
    data["available_facings"] = available
    return data


@bp.post("/retail-partners")
def create_partner():
    _, role = authenticate()
    require_role(role, ROLE_RETAIL_PLANNER)
    body = get_body()
    rec = new_record(
        {
            "name": req_str(body, "name"),
            "banner_code": req_str(body, "banner_code"),
            "category_capacities": req_capacity_map(body, "category_capacities"),
        }
    )
    store.retail_partners[rec["id"]] = rec
    return success_object(_pub_partner(rec), code=201)


@bp.get("/retail-partners/<rid>")
def get_partner(rid):
    authenticate()
    rec = store.retail_partners.get(rid)
    if rec is None:
        raise not_found("ERR_RETAIL_PARTNER_NOT_FOUND", "retail partner not found")
    return success_object(_pub_partner(rec))


@bp.patch("/retail-partners/<rid>")
def patch_partner(rid):
    _, role = authenticate()
    require_role(role, ROLE_RETAIL_PLANNER)
    body = get_body()
    new_caps = None
    if "category_capacities" in body and body["category_capacities"] is not None:
        new_caps = req_capacity_map(body, "category_capacities")
    rec = store.retail_partners.get(rid)
    if rec is None:
        raise not_found("ERR_RETAIL_PARTNER_NOT_FOUND", "retail partner not found")
    if new_caps is not None:
        # Atomic: either every category fits after evicting newest COMMITTED
        # slots, or the whole revision is rejected and nothing changes.
        cascade.apply_capacity_revision(rec, new_caps)
    return success_object(_pub_partner(rec))
