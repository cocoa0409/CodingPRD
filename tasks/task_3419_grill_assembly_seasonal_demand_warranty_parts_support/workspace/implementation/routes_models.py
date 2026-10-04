"""GrillModel CRUD and lifecycle (PRD §3.2)."""

from flask import Blueprint

import clock
from auth import authenticate, require_role
from constants import (
    BURNER_COVERAGE_YEARS,
    ELECTRONICS_COVERAGE_YEARS,
    GRATE_COVERAGE_YEARS,
    MODEL_PARTS_SUPPORT_YEARS,
    OTHER_COVERAGE_YEARS,
)
from errors import api_error, not_found, validation
from serialize import model_out
from store import db, new_entity, touch
from util import get_body, ok, opt_int, req_int, req_str, require

bp = Blueprint("models", __name__, url_prefix="/grillops")

READ_ROLES = ("PlannerAdmin", "ChannelRep", "ServiceAgent")

LIFECYCLE_VALID_FROM = {
    "MARK_CLEARANCE_ELIGIBLE": ("ACTIVE",),
    "DISCONTINUE": ("ACTIVE", "CLEARANCE_ELIGIBLE"),
    "MARK_PARTS_ONLY": ("DISCONTINUED",),
    "RETIRE": ("PARTS_ONLY",),
}


@bp.post("/models")
def create_model():
    _, role = authenticate()
    require_role(role, ("PlannerAdmin",))
    data = get_body()
    model_code = req_str(data, "model_code")
    model_family = req_str(data, "model_family")
    model_year = req_int(data, "model_year")
    base_price_cents = req_int(data, "base_price_cents")
    if base_price_cents < 0:
        raise validation("base_price_cents must be >= 0")
    demand_share_bp = req_int(data, "demand_share_bp")
    if not (0 <= demand_share_bp <= 10000):
        raise validation("demand_share_bp must be between 0 and 10000")
    burner_years = opt_int(data, "burner_coverage_years", BURNER_COVERAGE_YEARS)
    grate_years = opt_int(data, "grate_coverage_years", GRATE_COVERAGE_YEARS)
    electronics_years = opt_int(data, "electronics_coverage_years", ELECTRONICS_COVERAGE_YEARS)
    other_years = opt_int(data, "other_coverage_years", OTHER_COVERAGE_YEARS)
    parts_support_years = opt_int(data, "parts_support_years", MODEL_PARTS_SUPPORT_YEARS)
    firmware = data.get("current_firmware_version")
    if firmware is None:
        firmware = "1.0.0"
    elif not isinstance(firmware, str) or not firmware:
        raise validation("current_firmware_version must be a non-empty string")
    # model_code uniqueness (no dedicated code -> ERR_VALIDATION)
    for other in db.models.values():
        if other["model_code"] == model_code:
            raise validation("model_code must be unique")
    model = new_entity({
        "model_code": model_code,
        "model_family": model_family,
        "model_year": model_year,
        "base_price_cents": base_price_cents,
        "demand_share_bp": demand_share_bp,
        "burner_coverage_years": burner_years,
        "grate_coverage_years": grate_years,
        "electronics_coverage_years": electronics_years,
        "other_coverage_years": other_years,
        "parts_support_years": parts_support_years,
        "current_firmware_version": firmware,
        "status": "ACTIVE",
        "discontinued_at": None,
        "support_obligation_until": None,
    })
    db.models[model["id"]] = model
    return ok(model_out(model), status=201)


@bp.get("/models/<model_id>")
def get_model(model_id):
    _, role = authenticate()
    require_role(role, READ_ROLES)
    model = db.models.get(model_id)
    if model is None:
        raise not_found("MODEL")
    return ok(model_out(model))


@bp.post("/models/<model_id>/lifecycle")
def model_lifecycle(model_id):
    _, role = authenticate()
    require_role(role, ("PlannerAdmin",))
    model = db.models.get(model_id)
    if model is None:
        raise not_found("MODEL")
    # rung 5: terminal lockdown precedes body validation
    if model["status"] == "RETIRED":
        raise api_error("ERR_INVALID_STATE", "a RETIRED model has no further lifecycle transitions")
    data = get_body()
    action = require(data, "action")
    if action not in LIFECYCLE_VALID_FROM:
        raise validation("action must be one of MARK_CLEARANCE_ELIGIBLE, DISCONTINUE, MARK_PARTS_ONLY, RETIRE")
    if model["status"] not in LIFECYCLE_VALID_FROM[action]:
        raise api_error(
            "ERR_INVALID_STATE",
            "action %s is not available from status %s" % (action, model["status"]),
        )
    now = clock.now()
    if action == "MARK_CLEARANCE_ELIGIBLE":
        model["status"] = "CLEARANCE_ELIGIBLE"
    elif action == "DISCONTINUE":
        model["status"] = "DISCONTINUED"
        model["discontinued_at"] = clock.iso_z(now)
        model["support_obligation_until"] = clock.iso_z(
            clock.add_years(now, model["parts_support_years"])
        )
    elif action == "MARK_PARTS_ONLY":
        # obligation must have fully expired: strictly later than the window end
        obligation = clock.parse_iso(model["support_obligation_until"])
        if not now > obligation:
            raise api_error("ERR_INVALID_STATE", "parts-support obligation has not yet expired")
        model["status"] = "PARTS_ONLY"
    elif action == "RETIRE":
        model["status"] = "RETIRED"
    touch(model)
    return ok(model_out(model))
