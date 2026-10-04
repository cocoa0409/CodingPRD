"""RegulatoryCap endpoints: create/get/list and OCC-guarded in-place amend."""

from flask import Blueprint

from core import (ALL_ROLES, DB, auth, body, err, list_response, new_entity,
                  ok_obj, pub, req_enum, req_int, req_num, req_str, touch,
                  apply_filters)

bp = Blueprint("caps", __name__)

REFUND_METHODS = ("SIMPLE_BALANCE", "LIFO_NET")

_INT_FIELDS = (
    "max_per_minute_cents",
    "max_connection_fee_cents",
    "max_ancillary_fee_cents",
    "max_deposit_fee_cents",
    "dormancy_days",
    "claim_window_days",
)


def cap_or_404(cap_id):
    cap = DB.caps.get(cap_id)
    if cap is None:
        err("ERR_REGULATORY_CAP_NOT_FOUND", 404,
            "RegulatoryCap %s does not exist" % cap_id)
    return cap


@bp.post("/comm-services/regulatory-caps")
def create_cap():
    auth(["StateRegulator"])
    data = body()
    state_code = req_str(data, "state_code")
    entity = new_entity()
    entity.update({
        "state_code": state_code,
        "max_per_minute_cents": req_int(data, "max_per_minute_cents"),
        "max_connection_fee_cents": req_int(data, "max_connection_fee_cents"),
        "max_ancillary_fee_cents": req_int(data, "max_ancillary_fee_cents"),
        "max_deposit_fee_cents": req_int(data, "max_deposit_fee_cents"),
        "max_commission_pct": req_num(data, "max_commission_pct"),
        "refund_method": req_enum(data, "refund_method", REFUND_METHODS),
        "dormancy_days": req_int(data, "dormancy_days"),
        "claim_window_days": req_int(data, "claim_window_days"),
    })
    for other in DB.caps.values():
        if other["state_code"] == state_code:
            err("ERR_DUPLICATE_CAP_FOR_STATE", 409,
                "A RegulatoryCap row already exists for state_code %s" % state_code)
    DB.caps[entity["id"]] = entity
    return ok_obj(pub(entity), 201)


@bp.get("/comm-services/regulatory-caps/<cap_id>")
def get_cap(cap_id):
    auth(ALL_ROLES)
    return ok_obj(pub(cap_or_404(cap_id)))


@bp.get("/comm-services/regulatory-caps")
def list_caps():
    auth(ALL_ROLES)
    items = apply_filters(DB.caps.values(), ["state_code"])
    return list_response(items, pub)


@bp.put("/comm-services/regulatory-caps/<cap_id>")
def amend_cap(cap_id):
    auth(["StateRegulator"])
    data = body()
    expected = req_int(data, "expected_regulatory_cap_version")
    cap = cap_or_404(cap_id)
    # OCC: stale view of the cap row -> 412 (PRD section 2.7).
    if expected != cap["version"]:
        err("ERR_STALE_VERSION", 412,
            "expected_regulatory_cap_version %s does not match current "
            "version %s" % (expected, cap["version"]))
    for name in _INT_FIELDS:
        if data.get(name) is not None:
            value = data[name]
            if isinstance(value, bool) or not isinstance(value, int):
                err("ERR_INVALID_REQUEST", 400,
                    "Field %s must be an integer" % name)
            cap[name] = value
    if data.get("max_commission_pct") is not None:
        value = data["max_commission_pct"]
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            err("ERR_INVALID_REQUEST", 400,
                "Field max_commission_pct must be a number")
        cap["max_commission_pct"] = value
    if data.get("refund_method") is not None:
        if data["refund_method"] not in REFUND_METHODS:
            err("ERR_INVALID_REQUEST", 400,
                "Field refund_method must be one of SIMPLE_BALANCE, LIFO_NET")
        cap["refund_method"] = data["refund_method"]
    touch(cap)
    return ok_obj(pub(cap))
