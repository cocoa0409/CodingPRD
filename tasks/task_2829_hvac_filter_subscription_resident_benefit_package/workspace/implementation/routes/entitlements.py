"""GET /benefit-entitlements/{id}."""
from flask import Blueprint

import envelope
import guards
import views

bp = Blueprint("entitlements", __name__)


@bp.get("/benefit-entitlements/<entitlement_id>")
def read_entitlement(entitlement_id):
    uid, role = guards.auth(["ProgramOperator", "PropertyManager", "Resident"])
    rec = guards.get_entitlement(entitlement_id)
    sub = guards.get_subscription(rec["subscription_id"])
    guards.own_subscription(uid, role, sub)
    return envelope.object_response(views.entitlement_view(rec))
