"""Quality certificates (PRD 3.6): record, list, certify under a two-person
rule; certification cascades to the delivery."""
from decimal import Decimal

from flask import Blueprint

from helpers import (authenticate, require_role, json_body, respond,
                     v_dt, v_num, v_int, v_enum, by_created, paginate)
from store import db, base_entity, pub, touch, now_iso, ApiError
from domain import create_delivery

bp = Blueprint("quality", __name__)


@bp.route("/gas-supply/deliveries/<deliveryId>/quality-certificates",
          methods=["POST"])
def create_certificate(deliveryId):
    uid, role = authenticate()
    require_role(role, {"QualityAnalyst"})
    delivery = db["deliveries"].get(deliveryId)
    if delivery is None:
        raise ApiError("ERR_DELIVERY_NOT_FOUND", 404, "Delivery not found")
    # Tier 4: delivery must be DELIVERED
    if delivery["transport_status"] != "DELIVERED":
        raise ApiError("ERR_DELIVERY_NOT_DELIVERED", 409,
                       "Certificate requires a DELIVERED delivery")
    # Tier 7: at most one certificate per delivery
    for cert in db["certificates"].values():
        if cert["delivery_id"] == deliveryId:
            raise ApiError("ERR_CERTIFICATE_EXISTS", 409,
                           "A certificate already exists for this delivery")
    # Tier 9 structural
    body = json_body()
    sampled_at = v_dt(body, "sampled_at")
    purity = v_num(body, "measured_purity_percent")
    impurity = v_int(body, "measured_impurity_ppm", min_value=0)
    ent = base_entity()
    ent.update({
        "delivery_id": deliveryId,
        "sampled_at": sampled_at,
        "measured_purity_percent": purity,
        "measured_impurity_ppm": impurity,
        "analyst_user_id": uid,
        "certifier_user_id": None,
        "result": "RECORDED",
        "decided_at": None,
    })
    db["certificates"][ent["id"]] = ent
    return respond(pub(ent), "object", 201)


@bp.route("/gas-supply/deliveries/<deliveryId>/quality-certificates",
          methods=["GET"])
def list_certificates(deliveryId):
    authenticate()
    if deliveryId not in db["deliveries"]:
        raise ApiError("ERR_DELIVERY_NOT_FOUND", 404, "Delivery not found")
    items = by_created([c for c in db["certificates"].values()
                        if c["delivery_id"] == deliveryId])
    page, meta = paginate(items)
    return respond([pub(c) for c in page], "array", 200, meta)


@bp.route("/gas-supply/quality-certificates/<certificateId>/certify",
          methods=["POST"])
def certify_certificate(certificateId):
    uid, role = authenticate()
    require_role(role, {"QualityCertifier"})
    cert = db["certificates"].get(certificateId)
    if cert is None:
        raise ApiError("ERR_CERTIFICATE_NOT_FOUND", 404,
                       "QualityCertificate not found")
    body = json_body()
    # Tier 4: only a RECORDED certificate can be decided
    if cert["result"] != "RECORDED":
        raise ApiError("ERR_INVALID_STATE_TRANSITION", 409,
                       "Certificate has already been decided")
    # Tier 5: segregation of duties, then (for CERTIFIED) result consistency
    if uid == cert["analyst_user_id"]:
        raise ApiError("ERR_SEGREGATION_OF_DUTIES", 422,
                       "Certifier must differ from the recording analyst")
    decision_raw = body.get("decision")
    if decision_raw == "CERTIFIED":
        delivery = db["deliveries"].get(cert["delivery_id"])
        purity_ok = (Decimal(str(cert["measured_purity_percent"]))
                     >= Decimal(str(delivery["required_purity_percent"])))
        impurity_ok = (cert["measured_impurity_ppm"]
                       <= delivery["max_impurity_ppm"])
        if not (purity_ok and impurity_ok):
            raise ApiError("ERR_RESULT_INCONSISTENT", 422,
                           "Measured values violate the delivery's "
                           "specification snapshot")
    # Tier 9 structural
    decision = v_enum(body, "decision", ("CERTIFIED", "FAILED"))
    # Effects
    cert["result"] = decision
    cert["certifier_user_id"] = uid
    cert["decided_at"] = now_iso()
    touch(cert)
    delivery = db["deliveries"].get(cert["delivery_id"])
    if delivery is not None:
        if decision == "CERTIFIED":
            delivery["transport_status"] = "COMPLETED"
            delivery["quality_status"] = "CERTIFIED"
            touch(delivery)
        else:
            delivery["transport_status"] = "REJECTED"
            delivery["quality_status"] = "FAILED"
            touch(delivery)
            tank = db["tanks"].get(delivery["tank_id"])
            if tank is not None:
                create_delivery(tank, "REDELIVERY")
    return respond(pub(cert))
