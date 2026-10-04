"""Install registrations and warranty activation."""
from datetime import date
from flask import Blueprint, request, g

import db as dbmod
from errors import (raise_err, ERR_INVALID_STATE, ERR_NOT_OWNER,
                    ERR_CONTRACTOR_NOT_CERTIFIED, ERR_REGISTRATION_WINDOW,
                    ERR_ALREADY_ENHANCED)
from middleware import require_roles
from services import calcs
from services.lookup import get_path, get_body_ref
from util import (body, ok_object, ok_list, req_str, parse_date,
                  new_resource, touch, logical_now_iso)

bp = Blueprint("registrations", __name__)


@bp.post("/decking/install-registrations")
@require_roles("Contractor")
def create_registration():
    data = body()
    contractor = get_body_ref("contractors", data.get("contractor_id"), "contractor_id")
    if g.user_id != contractor["id"]:
        raise_err(ERR_NOT_OWNER, "contractor acting on another contractor's registration")
    dealer = get_body_ref("dealers", data.get("dealer_id"), "dealer_id")
    line = get_body_ref("product_lines", data.get("product_line_id"), "product_line_id")
    lot = get_body_ref("board_lots", data.get("board_lot_id"), "board_lot_id")
    install_date = req_str(data, "install_date")
    parse_date(install_date, "install_date")
    registered_date = data.get("registered_date")
    if registered_date is not None:
        parse_date(registered_date, "registered_date")
    reg = new_resource({
        "contractor_id": contractor["id"],
        "dealer_id": dealer["id"],
        "product_line_id": line["id"],
        "install_date": install_date,
        "registered_at": logical_now_iso(),
        "registered_date": registered_date,
        "completion_date": None,
        "enhanced_warranty": False,
        "enhanced_activated_at": None,
        "warranty_years": 5,
        "board_lot_id": lot["id"],
        "status": "PENDING",
    })
    dbmod.db.install_registrations[reg["id"]] = reg
    return ok_object(dict(reg), status=201)


@bp.get("/decking/install-registrations/<rid>")
@require_roles("Contractor", "ProgramAdmin", "ClaimsAdjuster", "Dealer")
def get_registration(rid):
    return ok_object(dict(get_path("install_registrations", rid)))


@bp.get("/decking/install-registrations")
@require_roles("Contractor", "ProgramAdmin", "ClaimsAdjuster")
def list_registrations():
    items = list(dbmod.db.install_registrations.values())
    for f in ("dealer_id", "product_line_id", "board_lot_id", "contractor_id"):
        v = request.args.get(f)
        if v:
            items = [r for r in items if str(r.get(f)) == v]
    return ok_list([dict(r) for r in items])


def _own(reg):
    if g.user_id != reg["contractor_id"]:
        raise_err(ERR_NOT_OWNER, "contractor acting on another contractor's registration")


@bp.post("/decking/install-registrations/<rid>/mark-installed")
@require_roles("Contractor")
def mark_installed(rid):
    reg = get_path("install_registrations", rid)
    if reg["status"] != "PENDING":
        raise_err(ERR_INVALID_STATE, f"registration is {reg['status']}")
    _own(reg)
    reg["status"] = "INSTALLED"
    reg["completion_date"] = dbmod.clock_date().isoformat()
    touch(reg)
    c = dbmod.db.contractors[reg["contractor_id"]]
    calcs.recompute_contractor_counts(c)
    touch(c)
    return ok_object(dict(reg))


@bp.post("/decking/install-registrations/<rid>/activate-warranty")
@require_roles("Contractor")
def activate_warranty(rid):
    reg = get_path("install_registrations", rid)
    if reg["status"] != "INSTALLED":
        raise_err(ERR_INVALID_STATE, f"registration is {reg['status']}")
    _own(reg)
    c = dbmod.db.contractors[reg["contractor_id"]]
    if c["status"] != "CERTIFIED":
        raise_err(ERR_CONTRACTOR_NOT_CERTIFIED, "enhanced warranty requires CERTIFIED contractor")
    reg_date = date.fromisoformat(reg.get("registered_date") or reg["registered_at"][:10])
    install_date = date.fromisoformat(reg["install_date"])
    if (reg_date - install_date).days > 60:
        raise_err(ERR_REGISTRATION_WINDOW, "registration more than 60 days after install")
    if reg["enhanced_warranty"]:
        raise_err(ERR_ALREADY_ENHANCED, "enhanced warranty already active")
    reg["enhanced_warranty"] = True
    reg["warranty_years"] = calcs.TIER_WARRANTY_YEARS[c["tier"]]
    reg["enhanced_activated_at"] = logical_now_iso()
    touch(reg)
    calcs.recompute_contractor_counts(c)
    touch(c)
    return ok_object(dict(reg))


@bp.post("/decking/install-registrations/<rid>/cancel")
@require_roles("Contractor")
def cancel_registration(rid):
    reg = get_path("install_registrations", rid)
    if reg["status"] != "PENDING":
        raise_err(ERR_INVALID_STATE, f"registration is {reg['status']}")
    _own(reg)
    reg["status"] = "CANCELLED"
    touch(reg)
    return ok_object(dict(reg))
