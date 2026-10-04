"""Production routes."""

from flask import Blueprint, request

from db import DB
from common import base_resource, touch, paginate
from middleware import require_role
from errors import not_found, invalid_state, production_already_active
from response import success_object, success_list
import calc
import services

bp = Blueprint("productions", __name__)


def production_view(p):
    return dict(p)


@bp.post("/venue/productions")
def create_production():
    require_role("ProductionDirector")
    body = request.get_json(silent=True) or {}
    p = base_resource()
    p.update({
        "title": body.get("title"),
        "production_type": body.get("production_type"),
        "base_price_cents": body.get("base_price_cents"),
        "is_haptic_capable": bool(body.get("is_haptic_capable", False)),
        "status": "DRAFT",
        "gain_cents": 0,
    })
    DB.productions[p["id"]] = p
    return success_object(production_view(p), 201)


@bp.get("/venue/productions")
def list_productions():
    require_role("ProductionDirector", "ContentProducer", "VenueScheduler",
                 "VenueOpsEngineer", "SponsorshipManager", "BoxOfficeAgent")
    items = sorted(DB.productions.values(), key=lambda x: x["created_at"])
    status = request.args.get("status")
    if status:
        items = [p for p in items if p["status"] == status]
    page, limit, offset, total = paginate([production_view(p) for p in items], request.args)
    return success_list(page, limit, offset, total)


@bp.get("/venue/productions/<pid>")
def get_production(pid):
    require_role("ProductionDirector", "ContentProducer", "VenueScheduler",
                 "VenueOpsEngineer", "SponsorshipManager", "BoxOfficeAgent")
    p = DB.productions.get(pid)
    if not p:
        raise not_found()
    return success_object(production_view(p))


@bp.post("/venue/productions/<pid>/activate")
def activate_production(pid):
    require_role("ProductionDirector")
    p = DB.productions.get(pid)
    if not p:
        raise not_found()
    if p["status"] not in ("DRAFT", "DARK"):
        raise invalid_state()
    for other in DB.productions.values():
        if other["id"] != pid and other["status"] == "ACTIVE":
            raise production_already_active()
    p["status"] = "ACTIVE"
    touch(p)
    calc.recompute_gain()
    return success_object(production_view(p))


@bp.post("/venue/productions/<pid>/deactivate")
def deactivate_production(pid):
    require_role("ProductionDirector")
    p = DB.productions.get(pid)
    if not p:
        raise not_found()
    if p["status"] != "ACTIVE":
        raise invalid_state()
    for s in DB.shows.values():
        if s["production_id"] == pid and s["status"] == "CONFIRMED":
            raise invalid_state("Production has CONFIRMED shows")
    p["status"] = "DARK"
    touch(p)
    for s in DB.shows.values():
        if s["production_id"] == pid and s["status"] in ("TENTATIVE", "REHEARSAL"):
            services.cancel_show(s)
    calc.recompute_gain()
    return success_object(production_view(p))


@bp.post("/venue/productions/<pid>/retire")
def retire_production(pid):
    require_role("ProductionDirector")
    p = DB.productions.get(pid)
    if not p:
        raise not_found()
    if p["status"] not in ("DRAFT", "DARK"):
        raise invalid_state()
    p["status"] = "RETIRED"
    touch(p)
    calc.recompute_gain()
    return success_object(production_view(p))
