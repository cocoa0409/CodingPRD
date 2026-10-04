"""Brewer models: registration with the pinned subsidy snapshot."""
from flask import Blueprint

from store import db
from helpers import body, created, init_common, require_roles, v_enum, v_int, v_str
from calc import subsidy_snapshot
from serializers import model_out

bp = Blueprint("models", __name__)

FIRMWARE = ("OPEN", "RESTRICTIVE")


@bp.post("/brewer-models")
@require_roles("PlatformAdmin")
def create_model():
    b = body()
    model_code = v_str(b, "model_code")
    firmware = v_enum(b, "firmware_compat", FIRMWARE)
    warranty_months = v_int(b, "warranty_months")
    descale_interval_brews = v_int(b, "descale_interval_brews")
    msrp = v_int(b, "msrp_cents")
    unit_cost = v_int(b, "unit_cost_cents")
    subsidy = subsidy_snapshot()
    model = init_common({
        "model_code": model_code,
        "firmware_compat": firmware,
        "warranty_months": warranty_months,
        "descale_interval_brews": descale_interval_brews,
        "msrp_cents": msrp,
        "unit_cost_cents": unit_cost,
        "subsidy_cents": subsidy,
        "margin_cents": msrp - unit_cost - subsidy,
    })
    db["models"][model["id"]] = model
    return created(model_out(model))
