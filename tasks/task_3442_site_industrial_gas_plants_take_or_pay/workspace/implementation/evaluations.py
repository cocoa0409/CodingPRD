"""Supply-mode evaluations (PRD 3.1): create/evaluate, accept, list."""
from decimal import Decimal

from flask import Blueprint

from helpers import (authenticate, require_role, forbidden, json_body, respond,
                     v_str, v_num, v_bool, v_enum, validation, by_created,
                     paginate, PRODUCTS)
from store import db, base_entity, pub, touch, ApiError
from domain import recommend_mode

bp = Blueprint("evaluations", __name__)


@bp.route("/gas-supply/supply-mode-evaluations", methods=["POST"])
def create_evaluation():
    _uid, role = authenticate()
    require_role(role, {"SupplyPlanner"})
    body = json_body()
    # Tier 3: body-referenced customer must exist
    cid = body.get("customer_id")
    if isinstance(cid, str) and cid not in db["customers"]:
        raise ApiError("ERR_CUSTOMER_NOT_FOUND", 404, "Customer not found")
    # Tier 9 structural
    customer_id = v_str(body, "customer_id")
    site_label = v_str(body, "site_label")
    avg = v_num(body, "demand_avg_nm3h", min_value=0)
    peak = v_num(body, "demand_peak_nm3h", min_value=0)
    purity = v_num(body, "required_purity_percent")
    product = v_enum(body, "required_product", PRODUCTS)
    pipe = v_bool(body, "pipeline_available")
    if Decimal(str(peak)) < Decimal(str(avg)):
        validation("demand_peak_nm3h must be >= demand_avg_nm3h")
    mode = recommend_mode(Decimal(str(avg)), pipe)
    # Creation supersedes siblings still in EVALUATED (same customer + site)
    for e in db["evaluations"].values():
        if (e["customer_id"] == customer_id and e["site_label"] == site_label
                and e["status"] == "EVALUATED"):
            e["status"] = "SUPERSEDED"
            touch(e)
    ent = base_entity()
    ent.update({
        "customer_id": customer_id,
        "site_label": site_label,
        "demand_avg_nm3h": avg,
        "demand_peak_nm3h": peak,
        "required_purity_percent": purity,
        "required_product": product,
        "pipeline_available": pipe,
        "recommended_mode": mode,
        "status": "EVALUATED",
    })
    db["evaluations"][ent["id"]] = ent
    return respond(pub(ent), "object", 201)


@bp.route("/gas-supply/customers/<customerId>/supply-mode-evaluations",
          methods=["GET"])
def list_customer_evaluations(customerId):
    authenticate()
    if customerId not in db["customers"]:
        raise ApiError("ERR_CUSTOMER_NOT_FOUND", 404, "Customer not found")
    items = by_created([e for e in db["evaluations"].values()
                        if e["customer_id"] == customerId])
    page, meta = paginate(items)
    return respond([pub(e) for e in page], "array", 200, meta)


@bp.route("/gas-supply/supply-mode-evaluations/<evaluationId>/accept",
          methods=["POST"])
def accept_evaluation(evaluationId):
    uid, role = authenticate()
    require_role(role, {"CustomerOps"})
    ent = db["evaluations"].get(evaluationId)
    if ent is None:
        raise ApiError("ERR_EVALUATION_NOT_FOUND", 404, "Evaluation not found")
    # CustomerOps ownership: caller must be the evaluated customer
    if uid != ent["customer_id"]:
        forbidden("CustomerOps caller does not own this evaluation")
    if ent["status"] != "EVALUATED":
        raise ApiError("ERR_INVALID_STATE_TRANSITION", 409,
                       "Only an EVALUATED evaluation can be accepted")
    ent["status"] = "ACCEPTED"
    touch(ent)
    # Acceptance supersedes every sibling in EVALUATED or ACCEPTED
    for e in db["evaluations"].values():
        if (e["id"] != ent["id"] and e["customer_id"] == ent["customer_id"]
                and e["site_label"] == ent["site_label"]
                and e["status"] in ("EVALUATED", "ACCEPTED")):
            e["status"] = "SUPERSEDED"
            touch(e)
    return respond(pub(ent))
