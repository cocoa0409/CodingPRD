"""Customer onboarding (PRD 3.1)."""
from flask import Blueprint

from helpers import (authenticate, require_role, json_body, respond,
                     v_str, v_enum, validation)
from store import db, base_entity, pub, parse_dt, ApiError

bp = Blueprint("customers", __name__)

SEGMENTS = ("ELECTRONICS", "MEDICAL", "METALS", "CHEMICAL")
CREDIT_STANDINGS = ("PRIME", "STANDARD", "WATCH")


@bp.route("/gas-supply/customers", methods=["POST"])
def create_customer():
    _uid, role = authenticate()
    require_role(role, {"PlatformAdmin"})
    body = json_body()
    # Tier 9 structural (no path resources / state / business tiers here)
    name = v_str(body, "name")
    segment = v_enum(body, "segment", SEGMENTS)
    credit = v_enum(body, "credit_standing", CREDIT_STANDINGS, required=False)
    if credit is None:
        credit = "STANDARD"
    blackouts = body.get("blackout_windows")
    if blackouts is None:
        blackouts = []
    if not isinstance(blackouts, list):
        validation("blackout_windows must be a list")
    parsed = []
    for w in blackouts:
        if not isinstance(w, dict):
            validation("each blackout window must be an object")
        start = parse_dt(w.get("start_iso"))
        end = parse_dt(w.get("end_iso"))
        if start is None or end is None:
            validation("blackout windows require ISO start_iso and end_iso")
        parsed.append((start, end))
    ent = base_entity()
    ent.update({
        "name": name,
        "segment": segment,
        "credit_standing": credit,
        "blackout_windows": blackouts,
        "_blackouts": parsed,
    })
    db["customers"][ent["id"]] = ent
    return respond(pub(ent), "object", 201)


@bp.route("/gas-supply/customers/<customerId>", methods=["GET"])
def get_customer(customerId):
    authenticate()  # every declared role may call any GET endpoint
    ent = db["customers"].get(customerId)
    if ent is None:
        raise ApiError("ERR_CUSTOMER_NOT_FOUND", 404, "Customer not found")
    return respond(pub(ent))
