"""Trade report intake (timeliness + dissemination banding) and cancellation."""
from flask import Blueprint, request

import serializers
import services
import store
from errors import (
    ApiError,
    ERR_INVALID_STATE,
    ERR_ORG_NOT_FOUND,
    ERR_ORG_SUSPENDED,
    ERR_ORG_TYPE_NOT_PERMITTED,
    ERR_TRADE_NOT_FOUND,
    ERR_TRADE_TIME_INVALID,
    ERR_UNAUTHORIZED,
)
from respond import ok, ok_list
from validators import (
    forbid_cross_org,
    get_body,
    paginate,
    req_datetime,
    req_enum,
    req_int,
    req_number,
    req_str,
    require_auth,
    require_role,
    _bad,
)

bp = Blueprint("trades", __name__)

TRADE_TYPES = ("INTER_DEALER", "CUSTOMER_BUY", "CUSTOMER_SELL")
TRADE_READ_ROLES = ("DealerRep", "PortalOperator", "PublicReader", "ComplianceOfficer")


def _visible(trade, uid, role):
    if role == "DealerRep":
        return trade["dealer_org_id"] == uid
    if role == "PublicReader":
        return trade["status"] == "DISSEMINATED"
    return True


@bp.route("/msrb/trade-reports", methods=["POST"])
def create_trade_report():
    uid, role = require_auth()
    require_role(role, ("DealerRep",))
    body = get_body()
    # Priority 2 ownership: DealerRep's X-User-ID must equal dealer_org_id.
    forbid_cross_org(uid, body.get("dealer_org_id"))
    # Priority 3 schema checks.
    cusip = req_str(body, "cusip")
    if len(cusip) != 9:
        raise _bad("cusip must be exactly 9 characters.")
    trade_type = req_enum(body, "trade_type", TRADE_TYPES)
    par_amount = req_int(body, "par_amount")
    if par_amount <= 0:
        raise _bad("par_amount must be > 0.")
    price = req_number(body, "price")
    if price <= 0:
        raise _bad("price must be > 0.")
    executed_at = req_datetime(body, "executed_at")
    dealer_org_id = req_str(body, "dealer_org_id")
    # Priority 5: referenced organization must exist.
    org = store.organizations.get(dealer_org_id)
    if org is None:
        raise ApiError(ERR_ORG_NOT_FOUND, "dealer_org_id does not exist.", 404)
    # Priority 10: organization must be ACTIVE.
    if org["status"] != "ACTIVE":
        raise ApiError(ERR_ORG_SUSPENDED, "The reporting dealer is SUSPENDED.", 409)
    # Priority 17: trade time check.
    now = store.now()
    if executed_at > now:
        raise ApiError(
            ERR_TRADE_TIME_INVALID,
            "executed_at must not be after the current logical time.",
            422,
        )
    # Priority 19: dealer type gate.
    if org["org_type"] != "BROKER_DEALER":
        raise ApiError(
            ERR_ORG_TYPE_NOT_PERMITTED,
            "Trade reporting dealer must be a BROKER_DEALER.",
            422,
        )
    # calculations.trade_timeliness + disseminated_par_publication.
    delta_seconds = int((now - executed_at).total_seconds())
    late_flag = delta_seconds > services.REPORT_LIMIT_SECONDS
    seconds_late = max(0, delta_seconds - services.REPORT_LIMIT_SECONDS)
    published_par = min(par_amount, services.LARGE_TRADE_PAR_CAP)
    capped_flag = par_amount > services.LARGE_TRADE_PAR_CAP
    trade = {
        "id": store.new_id(),
        "dealer_org_id": dealer_org_id,
        "cusip": cusip,
        "trade_type": trade_type,
        "par_amount": par_amount,
        "price": price,
        "executed_at": executed_at,
        "reported_at": now,
        "late_flag": late_flag,
        "seconds_late": seconds_late,
        "published_par": published_par,
        "capped_flag": capped_flag,
        "status": "DISSEMINATED",
        "created_at": now,
        "updated_at": now,
        "version": 1,
    }
    store.trade_reports[trade["id"]] = trade
    org["published_par_total"] += published_par
    services.recompute_posture(org)
    return ok(serializers.trade_report(trade), 201)


@bp.route("/msrb/trade-reports", methods=["GET"])
def list_trade_reports():
    uid, role = require_auth()
    require_role(role, TRADE_READ_ROLES)
    items = [t for t in store.trade_reports.values() if _visible(t, uid, role)]
    dealer_filter = request.args.get("dealer_org_id")
    if dealer_filter is not None:
        items = [t for t in items if t["dealer_org_id"] == dealer_filter]
    status_filter = request.args.get("status")
    if status_filter is not None:
        items = [t for t in items if t["status"] == status_filter]
    cusip_filter = request.args.get("cusip")
    if cusip_filter is not None:
        items = [t for t in items if t["cusip"] == cusip_filter]
    items.sort(key=lambda t: t["created_at"])
    page, limit, offset, total = paginate(items)
    return ok_list([serializers.trade_report(t) for t in page], limit, offset, total)


@bp.route("/msrb/trade-reports/<trade_id>", methods=["GET"])
def get_trade_report(trade_id):
    uid, role = require_auth()
    require_role(role, TRADE_READ_ROLES)
    trade = store.trade_reports.get(trade_id)
    if trade is None or not _visible(trade, uid, role):
        # Scoped reads outside the caller's visibility report not-found.
        raise ApiError(ERR_TRADE_NOT_FOUND, "Trade report not found.", 404)
    return ok(serializers.trade_report(trade), 200)


@bp.route("/msrb/trade-reports/<trade_id>/cancel", methods=["POST"])
def cancel_trade_report(trade_id):
    uid, role = require_auth()
    require_role(role, ("DealerRep",))
    get_body()
    trade = store.trade_reports.get(trade_id)
    if trade is None:
        raise ApiError(ERR_TRADE_NOT_FOUND, "Trade report not found.", 404)
    # Ownership: only the reporting dealer itself may cancel.
    if trade["dealer_org_id"] != uid:
        raise ApiError(
            ERR_UNAUTHORIZED,
            "A trade can be cancelled only by its reporting dealer.",
            403,
        )
    if trade["status"] != "DISSEMINATED":
        raise ApiError(
            ERR_INVALID_STATE, "Only a DISSEMINATED trade can be cancelled.", 409
        )
    trade["status"] = "CANCELLED"
    services.bump(trade)
    org = store.organizations.get(trade["dealer_org_id"])
    if org is not None:
        org["published_par_total"] -= trade["published_par"]
        services.recompute_posture(org)
    return ok(serializers.trade_report(trade), 200)
