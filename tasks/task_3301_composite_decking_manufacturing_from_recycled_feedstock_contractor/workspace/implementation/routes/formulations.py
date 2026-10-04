"""Formulations: create, activate, revise-in-place, retire."""
from flask import Blueprint

import db as dbmod
from errors import (raise_err, ERR_INVALID_REQUEST, ERR_INVALID_STATE,
                    ERR_FORMULA_UNBALANCED, ERR_REVISION_COLLISION,
                    ERR_FORMULATION_IN_USE)
from middleware import require_roles
from services import calcs
from services.lookup import get_path
from util import body, ok_object, ok_list, req_str, new_resource, touch

bp = Blueprint("formulations", __name__)

MATERIALS = ("VIRGIN_PE", "REPRO_PE", "PCR_FILM", "WOOD_FLOUR")


def _validate_lines(data):
    lines = data.get("lines")
    if not isinstance(lines, list) or not lines:
        raise_err(ERR_INVALID_REQUEST, "lines must be a non-empty array")
    for l in lines:
        if not isinstance(l, dict):
            raise_err(ERR_INVALID_REQUEST, "each formulation line must be an object")
        m = l.get("material")
        w = l.get("weight_fraction_bp")
        if m not in MATERIALS:
            raise_err(ERR_INVALID_REQUEST, f"line material must be one of {MATERIALS}")
        if isinstance(w, bool) or not isinstance(w, int) or w < 0:
            raise_err(ERR_INVALID_REQUEST, "weight_fraction_bp must be a non-negative integer")
    return lines


def formulation_view(f):
    rev = dbmod.db.formulation_revisions[f["id"]][f["active_revision"]]
    out = dict(f)
    out["lines"] = [dict(l) for l in rev["lines"]]
    return out


@bp.post("/decking/formulations")
@require_roles("ProcessEngineer")
def create_formulation():
    data = body()
    name = req_str(data, "name")
    lines = _validate_lines(data)
    f = new_resource({
        "name": name,
        "status": "DRAFT",
        "active_revision": 1,
        "current_revision_hash": None,
    })
    dbmod.db.formulations[f["id"]] = f
    dbmod.db.formulation_revisions[f["id"]] = {1: {"lines": lines, "hash": calcs.content_hash(lines)}}
    return ok_object(formulation_view(f), status=201)


@bp.get("/decking/formulations/<fid>")
@require_roles("ProcessEngineer", "OpsManager", "ProductManager")
def get_formulation(fid):
    return ok_object(formulation_view(get_path("formulations", fid)))


@bp.post("/decking/formulations/<fid>/activate")
@require_roles("ProcessEngineer")
def activate_formulation(fid):
    f = get_path("formulations", fid)
    if f["status"] != "DRAFT":
        raise_err(ERR_INVALID_STATE, f"formulation is {f['status']}")
    rev = dbmod.db.formulation_revisions[fid][1]
    total = sum(l["weight_fraction_bp"] for l in rev["lines"])
    if total != 10000:
        raise_err(ERR_FORMULA_UNBALANCED, "weight fractions do not sum to 10000 bp")
    f["status"] = "ACTIVE"
    f["active_revision"] = 1
    f["current_revision_hash"] = rev["hash"]
    touch(f)
    return ok_object(formulation_view(f))


@bp.post("/decking/formulations/<fid>/revisions")
@require_roles("ProcessEngineer")
def revise_formulation(fid):
    f = get_path("formulations", fid)
    if f["status"] != "ACTIVE":
        raise_err(ERR_INVALID_STATE, f"formulation is {f['status']}")
    data = body()
    lines = _validate_lines(data)
    total = sum(l["weight_fraction_bp"] for l in lines)
    if total != 10000:
        raise_err(ERR_FORMULA_UNBALANCED, "weight fractions do not sum to 10000 bp")
    h = calcs.content_hash(lines)
    for rev in dbmod.db.formulation_revisions[fid].values():
        if rev["hash"] == h:
            raise_err(ERR_REVISION_COLLISION, "revision content hash duplicates a prior revision")
    f["active_revision"] += 1
    f["current_revision_hash"] = h
    dbmod.db.formulation_revisions[fid][f["active_revision"]] = {"lines": lines, "hash": h}
    touch(f)
    return ok_object(formulation_view(f))


@bp.post("/decking/formulations/<fid>/retire")
@require_roles("ProcessEngineer")
def retire_formulation(fid):
    f = get_path("formulations", fid)
    if f["status"] != "ACTIVE":
        raise_err(ERR_INVALID_STATE, f"formulation is {f['status']}")
    for pl in dbmod.db.product_lines.values():
        if pl["formulation_id"] == fid and pl["status"] == "ACTIVE":
            raise_err(ERR_FORMULATION_IN_USE, "ACTIVE product line still references the formulation")
    f["status"] = "RETIRED"
    touch(f)
    return ok_object(formulation_view(f))


@bp.get("/decking/formulations/<fid>/product-lines")
@require_roles("ProcessEngineer", "ProductManager")
def formulation_product_lines(fid):
    get_path("formulations", fid)
    items = [dict(pl) for pl in dbmod.db.product_lines.values() if pl["formulation_id"] == fid]
    return ok_list(items)
