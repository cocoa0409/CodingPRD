"""Jurisdiction endpoints."""

from flask import Blueprint, request

import errors
from db import store
from middleware import authenticate, require_roles
from response import success_object, success_list
from services_common import new_entity, paginate, public

bp = Blueprint("jurisdictions", __name__)

ALL_ROLES = {"BureauCompliance", "BureauOnboarder", "BureauTaxFiler", "BureauTreasury", "ClientPayrollAdmin"}
FREQUENCIES = {"SEMIWEEKLY", "MONTHLY", "QUARTERLY"}


def jurisdiction_view(j):
    return public(j)


@bp.route("/jurisdictions", methods=["POST"])
def create_jurisdiction():
    auth = authenticate()
    require_roles(auth, {"BureauCompliance"})
    body = request.get_json(silent=True) or {}

    for field in ("code", "name", "deposit_frequency",
                  "penalty_tier1_rate", "penalty_tier2_rate", "penalty_tier3_rate",
                  "underpayment_threshold_cents"):
        if body.get(field) is None:
            raise errors.invalid_request(f"{field} is required")

    if body["deposit_frequency"] not in FREQUENCIES:
        raise errors.invalid_request("deposit_frequency out of domain")

    for rate in ("penalty_tier1_rate", "penalty_tier2_rate", "penalty_tier3_rate"):
        if not isinstance(body[rate], (int, float)) or isinstance(body[rate], bool):
            raise errors.invalid_request(f"{rate} must be a number")

    if not isinstance(body["underpayment_threshold_cents"], int) or isinstance(body["underpayment_threshold_cents"], bool):
        raise errors.invalid_request("underpayment_threshold_cents must be an integer")
    if body["underpayment_threshold_cents"] < 0:
        raise errors.invalid_request("underpayment_threshold_cents must be >= 0")

    active = body.get("active", True)
    if not isinstance(active, bool):
        raise errors.invalid_request("active must be a boolean")

    # Bureau-scoped unique code
    for j in store.jurisdictions.values():
        if j["code"] == body["code"]:
            raise errors.invalid_request("code must be unique")

    j = new_entity({
        "code": body["code"],
        "name": body["name"],
        "deposit_frequency": body["deposit_frequency"],
        "penalty_tier1_rate": body["penalty_tier1_rate"],
        "penalty_tier2_rate": body["penalty_tier2_rate"],
        "penalty_tier3_rate": body["penalty_tier3_rate"],
        "underpayment_threshold_cents": body["underpayment_threshold_cents"],
        "active": active,
    })
    store.jurisdictions[j["id"]] = j
    return success_object(jurisdiction_view(j), status=201)


@bp.route("/jurisdictions", methods=["GET"])
def list_jurisdictions():
    auth = authenticate()
    require_roles(auth, ALL_ROLES)
    items = list(store.jurisdictions.values())
    freq = request.args.get("deposit_frequency")
    if freq is not None:
        items = [j for j in items if j["deposit_frequency"] == freq]
    active = request.args.get("active")
    if active is not None:
        val = active.lower() == "true"
        items = [j for j in items if j["active"] == val]
    page, limit, offset, total = paginate(items)
    return success_list([jurisdiction_view(j) for j in page], limit, offset, total)


@bp.route("/jurisdictions/<jurisdictionId>", methods=["GET"])
def get_jurisdiction(jurisdictionId):
    auth = authenticate()
    require_roles(auth, ALL_ROLES)
    j = store.jurisdictions.get(jurisdictionId)
    if not j:
        raise errors.not_found("Jurisdiction not found")
    return success_object(jurisdiction_view(j))
