"""The daily NAV strike, finalization and repost (PRD 3.3)."""
from flask import Blueprint

import clock
import dates
import db
import response
import serializers
import validation
from errors import ApiError, invalid
from middleware import ALL_ROLES, ROLE_FA, authenticate
from routes import helpers
from services import navs as nav_service

bp = Blueprint("navs", __name__)


@bp.route("/nav-records", methods=["POST"])
def create_nav_record():
    authenticate((ROLE_FA,))
    body = validation.body()
    share_class_id = validation.get_id(body, "share_class_id", required=True)
    valuation_date = validation.get_date(body, "valuation_date", required=True)
    if not dates.is_business_day(valuation_date):
        raise invalid("valuation_date must fall Monday through Friday.")
    total_net_assets = validation.get_decimal(body, "total_net_assets", 2,
                                              required=True, non_negative=True)

    share_class = helpers.get_share_class(share_class_id)
    valuation_text = dates.fmt_date(valuation_date)

    if nav_service.find_for(share_class["id"], valuation_text) is not None:
        raise ApiError("ERR_NAV_DATE_DUPLICATE",
                       "A NAV record already exists for this class and valuation date.")

    snapshot, nav_per_share = nav_service.strike(share_class, total_net_assets)
    record = db.create(db.store.nav_records, {
        "share_class_id": share_class["id"],
        "valuation_date": valuation_text,
        "total_net_assets": total_net_assets,
        "shares_outstanding_snapshot": snapshot,
        "nav_per_share": nav_per_share,
        "original_nav_per_share": None,
        "status": "PRELIMINARY",
        "finalized_at": None,
    })
    return response.created(serializers.nav_record(record))


@bp.route("/nav-records/<nav_record_id>", methods=["GET"])
def read_nav_record(nav_record_id):
    authenticate(ALL_ROLES)
    record = helpers.get_nav_record(nav_record_id)
    return response.ok(serializers.nav_record(record))


@bp.route("/nav-records/<nav_record_id>/finalize", methods=["POST"])
def finalize_nav_record(nav_record_id):
    authenticate((ROLE_FA,))
    record = helpers.get_nav_record(nav_record_id)
    if record["status"] != "PRELIMINARY":
        raise ApiError("ERR_INVALID_NAV_STATE", "Only a PRELIMINARY record may be finalized.")
    record["status"] = "FINAL"
    record["finalized_at"] = clock.now_iso()
    db.touch(record)
    return response.ok(serializers.nav_record(record))


@bp.route("/nav-records/<nav_record_id>/repost", methods=["POST"])
def repost_nav_record(nav_record_id):
    authenticate((ROLE_FA,))
    body = validation.body()
    total_net_assets = validation.get_decimal(body, "total_net_assets", 2,
                                              required=True, non_negative=True)
    record = helpers.get_nav_record(nav_record_id)
    if record["status"] not in ("PRELIMINARY", "STALE_REPRICE_REQUIRED"):
        raise ApiError("ERR_INVALID_NAV_STATE",
                       "Only a PRELIMINARY or STALE_REPRICE_REQUIRED record may be re-struck.")

    share_class = db.store.share_classes[record["share_class_id"]]
    snapshot, nav_per_share = nav_service.strike(share_class, total_net_assets)
    record["total_net_assets"] = total_net_assets
    record["shares_outstanding_snapshot"] = snapshot
    record["nav_per_share"] = nav_per_share
    record["status"] = "PRELIMINARY"
    db.touch(record)
    return response.ok(serializers.nav_record(record))
