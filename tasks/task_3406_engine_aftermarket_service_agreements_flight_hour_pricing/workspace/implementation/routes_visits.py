"""ShopVisit scheduling, induction (with daily capacity), completion (with the
pinned compliance gate), and visit reads / nested lists."""
from flask import Blueprint

from authz import check_operator_ownership, current_caller, require_roles
from calc import (
    SHOP_INDUCTION_DAILY_CAPACITY,
    directive_due,
    forecast_visit,
    recompute_engine_removal,
    visit_projected_cost,
)
from envelope import paginate, pagination_params, success
from errors import api_err
from routes_admin import get_engine_or_404
from serialize import lease_json, visit_json, workscope_json
from storage import DB, new_id, next_seq, now, touch
from validate import as_datetime, body, req_field

bp = Blueprint("visits", __name__)


def get_visit_or_404(visit_id):
    visit = DB["visits"].get(visit_id)
    if visit is None:
        raise api_err("ERR_SHOP_VISIT_NOT_FOUND", "shop visit does not exist")
    return visit


def visit_engine(visit):
    return DB["engines"][visit["engine_id"]]


@bp.route("/api/engines/<engine_id>/shop-visits", methods=["POST"])
def schedule_visit(engine_id):
    uid, role = require_roles("Operator")
    engine = get_engine_or_404(engine_id)
    check_operator_ownership(uid, role, engine["operator_id"])
    data = body()
    planned = as_datetime(req_field(data, "planned_induction_date"), "planned_induction_date")
    if engine["agreement_id"] is None:
        raise api_err("ERR_ENGINE_NOT_ENROLLED", "engine is not enrolled in an agreement")
    forecast, method = forecast_visit(engine)
    ts = now()
    visit = {
        "id": new_id(), "engine_id": engine_id,
        "planned_induction_date": planned,
        "forecast_induction_date": forecast, "forecast_method": method,
        "actual_induction_date": None, "completion_date": None,
        "status": "SCHEDULED", "projected_cost_usd": visit_projected_cost(engine),
        "created_at": ts, "updated_at": ts, "version": 1, "_seq": next_seq(),
    }
    DB["visits"][visit["id"]] = visit
    return success(visit_json(visit), 201)


@bp.route("/api/shop-visits/<visit_id>/induct", methods=["POST"])
def induct_visit(visit_id):
    require_roles("ShopPlanner")
    visit = get_visit_or_404(visit_id)
    if visit["status"] != "SCHEDULED":
        raise api_err("ERR_INVALID_STATE", "visit is not SCHEDULED")
    engine = visit_engine(visit)
    if engine["status"] != "IN_SERVICE":
        raise api_err("ERR_ENGINE_IN_SHOP", "engine is not IN_SERVICE")
    agreement = DB["agreements"].get(engine["agreement_id"])
    if agreement is None or agreement["status"] != "ACTIVE":
        raise api_err("ERR_AGREEMENT_NOT_ACTIVE", "enrolled agreement is not ACTIVE")
    clock = now()
    inducted_today = sum(
        1 for v in DB["visits"].values()
        if v["status"] == "INDUCTED"
        and v["actual_induction_date"] is not None
        and v["actual_induction_date"].date() == clock.date()
    )
    if inducted_today >= SHOP_INDUCTION_DAILY_CAPACITY:
        raise api_err("ERR_SHOP_CAPACITY_EXCEEDED",
                      "daily shop induction capacity reached")
    visit["actual_induction_date"] = clock
    visit["status"] = "INDUCTED"
    touch(visit)
    engine["status"] = "IN_SHOP"
    touch(engine)
    return success(visit_json(visit), 200)


def _due_mandatory_directives(engine):
    return [
        d for d in DB["directives"].values()
        if directive_due(d, engine)
    ]


def _approved_workscopes(visit_id):
    return [
        w for w in DB["workscopes"].values()
        if w["shop_visit_id"] == visit_id and w["status"] == "APPROVED"
    ]


@bp.route("/api/shop-visits/<visit_id>/complete", methods=["POST"])
def complete_visit(visit_id):
    require_roles("ShopPlanner")
    visit = get_visit_or_404(visit_id)
    if visit["status"] != "INDUCTED":
        raise api_err("ERR_INVALID_STATE", "visit is not INDUCTED")
    engine = visit_engine(visit)
    approved = _approved_workscopes(visit_id)
    # Compliance gate, pinned order: (a) due mandatory directives incorporated
    # into an APPROVED workscope; (b) an APPROVED workscope exists at all.
    for directive in _due_mandatory_directives(engine):
        incorporated = any(
            any(it.get("directive_ref") == directive["directive_ref"] for it in w["items"])
            for w in approved
        )
        if not incorporated:
            raise api_err(
                "ERR_MANDATORY_DIRECTIVE_OPEN",
                "due mandatory directive {} is not incorporated into an APPROVED workscope"
                .format(directive["directive_ref"]))
    if not approved:
        raise api_err("ERR_NO_APPROVED_WORKSCOPE", "no APPROVED workscope exists for the visit")
    for w in DB["workscopes"].values():
        if w["shop_visit_id"] != visit_id or w["status"] == "SUPERSEDED":
            continue
        for r in DB["requisitions"].values():
            if r["workscope_id"] == w["id"] and r["status"] in ("REQUESTED", "ESCALATED"):
                raise api_err("ERR_OPEN_REQUISITIONS",
                              "requisitions still REQUESTED or ESCALATED block completion")
    visit["completion_date"] = now()
    visit["status"] = "COMPLETED"
    touch(visit)
    engine["status"] = "IN_SERVICE"
    latest_approved = max(approved, key=lambda w: w["scope_version"])
    engine["llp_remaining_cycles"] = max(
        engine["llp_remaining_cycles"], latest_approved["restores_llp_cycles"])
    recompute_engine_removal(engine)
    touch(engine)
    return success(visit_json(visit), 200)


@bp.route("/api/shop-visits/<visit_id>", methods=["GET"])
def get_visit(visit_id):
    current_caller()
    return success(visit_json(get_visit_or_404(visit_id)), 200)


@bp.route("/api/shop-visits/<visit_id>/workscopes", methods=["GET"])
def list_visit_workscopes(visit_id):
    current_caller()
    get_visit_or_404(visit_id)
    limit, offset = pagination_params()
    workscopes = sorted(
        (w for w in DB["workscopes"].values() if w["shop_visit_id"] == visit_id),
        key=lambda w: (w["created_at"], w["_seq"]),
    )
    page, meta = paginate(workscopes, limit, offset)
    return success([workscope_json(w) for w in page], 200, meta)


@bp.route("/api/shop-visits/<visit_id>/leases", methods=["GET"])
def list_visit_leases(visit_id):
    current_caller()
    get_visit_or_404(visit_id)
    limit, offset = pagination_params()
    leases = sorted(
        (l for l in DB["leases"].values() if l["shop_visit_id"] == visit_id),
        key=lambda l: (l["created_at"], l["_seq"]),
    )
    page, meta = paginate(leases, limit, offset)
    return success([lease_json(l) for l in page], 200, meta)
