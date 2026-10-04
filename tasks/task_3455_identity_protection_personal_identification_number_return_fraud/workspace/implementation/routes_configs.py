"""FilterModelConfig routes: create (DRAFT), read, activate (retires the
previously ACTIVE config so exactly one is ACTIVE at any moment)."""
from flask import Blueprint

from auth import require_roles
from domain import get_config, new_record, pub, touch
from envelope import created, ok
from errors import err
from store import DB
from validate import body, invalid, is_int, req_int, req_str

bp = Blueprint("configs", __name__)

WEIGHT_FIELDS = (
    "w_victim_flagged",
    "w_refund_delta",
    "w_bank_product",
    "w_preparer_flagged",
    "w_dependent_conflict",
    "interaction_bonus",
    "gray_zone_threshold",
    "hold_threshold",
)


@bp.post("/identity-protection/filter-model-configs")
def create_config():
    require_roles(["SystemAdmin"])
    b = body()
    # Priority 8: model_version uniqueness (ERR_INVALID_REQUEST per catalog).
    mv = b.get("model_version")
    if isinstance(mv, str):
        for c in DB.configs.values():
            if c["model_version"] == mv:
                invalid("model_version must be unique")
    # Priority 13: threshold coherence (checked before payload shape; only
    # when both thresholds are present and integral).
    gray = b.get("gray_zone_threshold")
    hold = b.get("hold_threshold")
    if is_int(gray) and is_int(hold) and gray >= hold:
        err("ERR_THRESHOLD_ORDER_INVALID")
    # Priority 14: payload shape.
    mv = req_str(b, "model_version")
    fields = {}
    for name in WEIGHT_FIELDS:
        fields[name] = req_int(b, name)
    rec = new_record(DB.configs, {
        "model_version": mv,
        "status": "DRAFT",
        **fields,
    })
    return created(pub(rec))


@bp.get("/identity-protection/filter-model-configs/<string:config_id>")
def read_config(config_id):
    require_roles(["SystemAdmin", "FraudAnalyst"])
    return ok(pub(get_config(config_id)))


@bp.post("/identity-protection/filter-model-configs/<string:config_id>/activate")
def activate_config(config_id):
    require_roles(["SystemAdmin"])
    cfg = get_config(config_id)
    if cfg["status"] == "RETIRED":
        err("ERR_ALREADY_TERMINAL")
    if cfg["status"] != "DRAFT":
        err("ERR_CONFIG_NOT_DRAFT")
    # Priority 13: threshold coherence re-checked at activation.
    if cfg["gray_zone_threshold"] >= cfg["hold_threshold"]:
        err("ERR_THRESHOLD_ORDER_INVALID")
    for c in DB.configs.values():
        if c["status"] == "ACTIVE":
            c["status"] = "RETIRED"
            touch(c)
    cfg["status"] = "ACTIVE"
    touch(cfg)
    return ok(pub(cfg))
