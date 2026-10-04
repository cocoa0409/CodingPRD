"""Customer chain endpoints: register, get, and set-credit-status with the
four-level credit cascade (chain -> agreements -> runs -> lots)."""

import domain
from db import store
from errors import ApiError
from flask import Blueprint
from middleware import ANY_ROLES, require_roles
from response import success_object
from util import body_json, req_enum, req_str
from constants import CREDIT_STATUSES, PRIORITY_TIERS

bp = Blueprint("chains", __name__)


@bp.route("/potato-ops/customer-chains", methods=["POST"])
@require_roles("AccountManager")
def create_chain():
    body = body_json()
    chain_code = req_str(body, "chain_code")
    legal_name = req_str(body, "legal_name")
    tier = req_enum(body, "priority_tier", PRIORITY_TIERS)
    c = domain.new_entity()
    c.update({
        "chain_code": chain_code,
        "legal_name": legal_name,
        "priority_tier": tier,
        "credit_status": "GOOD_STANDING",
    })
    store.chains[c["id"]] = c
    return success_object(domain.chain_view(c), 201)


@bp.route("/potato-ops/customer-chains/<cid>", methods=["GET"])
@require_roles(*ANY_ROLES)
def get_chain(cid):
    return success_object(domain.chain_view(domain.get_chain_or_404(cid)), 200)


@bp.route("/potato-ops/customer-chains/<cid>/set-credit-status", methods=["POST"])
@require_roles("AccountManager")
def set_credit_status(cid):
    body = body_json()
    new_status = req_enum(body, "credit_status", CREDIT_STATUSES)
    chain = domain.get_chain_or_404(cid)
    if chain["credit_status"] == new_status:
        raise ApiError(
            "ERR_INVALID_STATE",
            "credit_status must differ from the current value",
            409,
        )
    if new_status == "ON_HOLD":
        domain.cascade_credit_hold(chain)
    else:
        # GOOD_STANDING resume: re-reservation is atomic across the whole set —
        # if the pool cannot refit every SUSPENDED agreement, nothing changes.
        suspended = [
            a
            for a in store.agreements.values()
            if a["customer_id"] == chain["id"] and a["status"] == "SUSPENDED"
        ]
        needed = sum(a["weekly_contracted_cases"] for a in suspended)
        if domain.pool_remaining() < needed:
            raise ApiError(
                "ERR_WEEK_CAPACITY_EXCEEDED",
                "Plant weekly pool cannot refit the agreements being resumed",
                422,
            )
        domain.cascade_credit_resume(chain)
    return success_object(domain.chain_view(chain), 200)
