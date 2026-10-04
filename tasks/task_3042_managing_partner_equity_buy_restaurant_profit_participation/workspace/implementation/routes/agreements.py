"""Market partner agreement routes (PRD §3.2)."""

from flask import Blueprint, request

import db
from errors import conflict, invalid_request, unprocessable
from errors import (
    ERR_INVALID_STATE,
    ERR_MARKET_GROUP_NOT_ACTIVE,
    ERR_OVERRIDE_COVERAGE_OVERLAP,
)
from middleware import require_roles
from response import success_list, success_object
from services import domain
from util import (
    base_entity,
    get_json_body,
    paginate,
    req_date,
    req_field,
    req_number,
    req_string,
    touch,
)

bp = Blueprint("agreements", __name__)

AGREEMENT_READ_ROLES = ("PlatformAdmin", "CorporateController", "OperationsAuditor", "MarketPartner")


@bp.route("/market-partner-agreements", methods=["POST"])
def create_agreement():
    require_roles("CorporateController")
    body = get_json_body()
    partner_id = req_field(body, "partner_id")
    market_group_id = req_field(body, "market_group_id")
    # Body FK existence (tier 4).
    domain.ref_partner(partner_id)
    domain.ref_market_group(market_group_id)
    basis = req_string(body, "basis")
    if basis not in ("NET_GROUP_BASIS", "PER_RESTAURANT_POSITIVE"):
        raise invalid_request("basis must be NET_GROUP_BASIS or PER_RESTAURANT_POSITIVE")
    # Structural constraints (tier 8).
    coverage_start = req_date(body, "coverage_start_date")
    coverage_end = req_date(body, "coverage_end_date")
    if coverage_end < coverage_start:
        raise invalid_request("coverage_end_date must be on or after coverage_start_date")
    override_pct = req_number(body, "override_pct")
    if not (0 < override_pct <= 10):
        raise invalid_request("override_pct must be greater than 0 and at most 10")
    a = base_entity()
    a.update({
        "partner_id": partner_id,
        "market_group_id": market_group_id,
        "coverage_start_date": coverage_start.isoformat(),
        "coverage_end_date": coverage_end.isoformat(),
        "override_pct": override_pct,
        "basis": basis,
        "status": "DRAFT",
    })
    db.agreements[a["id"]] = a
    return success_object(domain.ser_agreement(a), 201)


@bp.route("/market-partner-agreements", methods=["GET"])
def list_agreements():
    require_roles(*AGREEMENT_READ_ROLES)
    items = list(db.agreements.values())
    partner_id = request.args.get("partner_id")
    if partner_id is not None:
        items = [a for a in items if a["partner_id"] == partner_id]
    mg = request.args.get("market_group_id")
    if mg is not None:
        items = [a for a in items if a["market_group_id"] == mg]
    status = request.args.get("status")
    if status is not None:
        items = [a for a in items if a["status"] == status]
    page, limit, offset, total = paginate(items)
    return success_list([domain.ser_agreement(a) for a in page], limit, offset, total)


@bp.route("/market-partner-agreements/<aid>", methods=["GET"])
def get_agreement(aid):
    require_roles(*AGREEMENT_READ_ROLES)
    return success_object(domain.ser_agreement(domain.get_agreement(aid)))


@bp.route("/market-partner-agreements/<aid>/activate", methods=["POST"])
def activate_agreement(aid):
    require_roles("CorporateController")
    a = domain.get_agreement(aid)
    if a["status"] != "DRAFT":
        raise conflict(ERR_INVALID_STATE, "Agreement must be DRAFT to activate")
    group = db.market_groups.get(a["market_group_id"])
    if group is None or group["status"] != "ACTIVE":
        raise unprocessable(ERR_MARKET_GROUP_NOT_ACTIVE, "Market group must be ACTIVE")
    # Coverage uniqueness over CLOSED intervals (inclusive both ends).
    for other in db.agreements.values():
        if other["id"] == a["id"]:
            continue
        if other["market_group_id"] != a["market_group_id"]:
            continue
        if other["status"] not in ("DRAFT", "ACTIVE"):
            continue
        if other["coverage_start_date"] <= a["coverage_end_date"] and a["coverage_start_date"] <= other["coverage_end_date"]:
            raise unprocessable(
                ERR_OVERRIDE_COVERAGE_OVERLAP,
                "Coverage interval intersects another DRAFT/ACTIVE agreement on the group",
            )
    a["status"] = "ACTIVE"
    touch(a)
    return success_object(domain.ser_agreement(a))


@bp.route("/market-partner-agreements/<aid>/terminate", methods=["POST"])
def terminate_agreement(aid):
    require_roles("CorporateController")
    a = domain.get_agreement(aid)
    if a["status"] not in ("DRAFT", "ACTIVE"):
        raise conflict(ERR_INVALID_STATE, "Agreement must be DRAFT or ACTIVE to terminate")
    a["status"] = "TERMINATED"
    touch(a)
    return success_object(domain.ser_agreement(a))
