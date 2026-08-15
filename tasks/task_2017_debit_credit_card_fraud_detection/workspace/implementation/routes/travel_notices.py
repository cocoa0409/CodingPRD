"""TravelNotice endpoints."""

from flask import Blueprint, request

import db
import errors
import middleware
import response
from services import domain

bp = Blueprint("travel_notices", __name__)


def _overlap(a_start, a_end, b_start, b_end) -> bool:
    """Half-open [start, end) overlap test."""
    return a_start < b_end and b_start < a_end


@bp.route("/fraudops/travel-notices", methods=["POST"])
def create_notice():
    user_id, role = middleware.require_role("FraudAnalyst", "Cardholder")
    body = request.get_json(silent=True) or {}
    card_id = body.get("card_id")
    region_country = body.get("region_country")
    start_date = body.get("start_date")
    end_date = body.get("end_date")

    if not isinstance(card_id, str) or not card_id:
        raise errors.err_invalid_request("card_id is required")
    if not isinstance(region_country, str) or not region_country:
        raise errors.err_invalid_request("region_country is required")
    if not isinstance(start_date, str) or not isinstance(end_date, str):
        raise errors.err_invalid_request("start_date and end_date are required")

    card = db.cards.get(card_id)
    if not card:
        raise errors.err_not_found("Card not found")
    if role == "Cardholder" and user_id != card["account_id"]:
        raise errors.err_not_resource_owner()

    try:
        sd = domain._parse_date(start_date)
        ed = domain._parse_date(end_date)
    except Exception:
        raise errors.err_invalid_request("start_date/end_date must be YYYY-MM-DD")
    if ed <= sd:
        raise errors.err_invalid_window()

    acct = db.accounts[card["account_id"]]
    if acct["account_status"] != "ACTIVE":
        raise errors.err_account_not_active()

    # overlap check among ACTIVE notices for same card/region
    for n in db.travel_notices.values():
        if n["card_id"] != card_id:
            continue
        if n["region_country"] != region_country:
            continue
        if n["notice_status"] != "ACTIVE":
            continue
        if _overlap(sd, ed, domain._parse_date(n["start_date"]), domain._parse_date(n["end_date"])):
            raise errors.err_travel_notice_overlap()

    rec = middleware.stamp_new(
        {
            "card_id": card_id,
            "region_country": region_country,
            "start_date": start_date,
            "end_date": end_date,
            "notice_status": "ACTIVE",
        }
    )
    db.travel_notices[rec["id"]] = rec
    return response.success(domain.ser_notice(rec), status_code=201)


@bp.route("/fraudops/travel-notices/<nid>", methods=["GET"])
def get_notice(nid):
    user_id, role = middleware.require_role("FraudAnalyst", "FraudOpsManager", "Cardholder")
    n = db.travel_notices.get(nid)
    if not n:
        raise errors.err_not_found("TravelNotice not found")
    domain._apply_travel_notice_expiry(n)
    if role == "Cardholder":
        card = db.cards.get(n["card_id"])
        if not card or card["account_id"] != user_id:
            raise errors.err_not_resource_owner()
    return response.success(domain.ser_notice(n))


@bp.route("/fraudops/travel-notices/<nid>/cancel", methods=["POST"])
def cancel_notice(nid):
    user_id, role = middleware.require_role("FraudAnalyst", "Cardholder")
    n = db.travel_notices.get(nid)
    if not n:
        raise errors.err_not_found("TravelNotice not found")
    domain._apply_travel_notice_expiry(n)
    if role == "Cardholder":
        card = db.cards.get(n["card_id"])
        if not card or card["account_id"] != user_id:
            raise errors.err_not_resource_owner()
    if n["notice_status"] != "ACTIVE":
        raise errors.err_invalid_state("Notice is not ACTIVE")
    n["notice_status"] = "CANCELLED"
    middleware.touch(n)
    return response.success(domain.ser_notice(n))
