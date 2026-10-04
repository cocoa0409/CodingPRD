"""Exclusivity awards: read surface (PRD 3.8). Awards are system-created."""
from flask import Blueprint, request

from auth import ALL_ROLES, auth, require_role
from envelope import sort_default, success_list, success_object
from errors import fail
from serialize import award
from state import STORE, get

bp = Blueprint("awards", __name__)


@bp.get("/generic-drug-review/exclusivity-awards/<award_id>")
def get_award(award_id):
    _uid, role = auth()
    require_role(role, ALL_ROLES)
    ent = get("awards", award_id)
    if ent is None:
        fail("ERR_EXCLUSIVITY_AWARD_NOT_FOUND",
             "Exclusivity award id does not exist")
    return success_object(award(ent))


@bp.get("/generic-drug-review/exclusivity-awards")
def list_awards():
    _uid, role = auth()
    require_role(role, ALL_ROLES)
    items = list(STORE["awards"].values())
    f_rp = request.args.get("reference_product_id")
    f_app = request.args.get("application_id")
    f_status = request.args.get("status")
    if f_rp is not None:
        items = [a for a in items if a["reference_product_id"] == f_rp]
    if f_app is not None:
        items = [a for a in items if a["application_id"] == f_app]
    if f_status is not None:
        items = [a for a in items if a["status"] == f_status]
    return success_list([award(a) for a in sort_default(items)])
