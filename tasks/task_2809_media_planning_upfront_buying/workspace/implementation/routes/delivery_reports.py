"""Measured delivery, post-buy analysis and make-good creation (PRD 3.8)."""

from flask import Blueprint

from auth import current_role, require_roles, require_seller_owner
from constants import MAKE_GOOD_TOLERANCE_PCT, MEASUREMENT_BASES
from errors import ApiError, bad_request
from lookup import get
from response import created, ok
from routes.common import listing, read_one
from serializers import serialize
from services import derive
from store import store
from validation import body

bp = Blueprint("delivery_reports", __name__)


@bp.post("/delivery-reports")
@require_roles("SellerRep", "MeasurementProvider")
def create_report():
    data = body()
    buy_id = data.string("buy_id")
    measurement_basis = data.enum("measurement_basis", MEASUREMENT_BASES)
    period_start = data.timestamp("period_start")
    period_end = data.timestamp("period_end")
    delivered_impressions = data.integer("delivered_impressions", minimum=0)
    delivered_demo_impressions = data.integer("delivered_demo_impressions", minimum=0)
    if delivered_demo_impressions > delivered_impressions:
        raise bad_request(
            "delivered_demo_impressions may not exceed delivered_impressions"
        )

    buy = get("buys", buy_id)
    if current_role() == "SellerRep":
        require_seller_owner(buy["seller_id"])

    # All three temporal failures report the same error (PRD 3.8).
    if (
        period_start > period_end
        or period_start < buy["flight_start"]
        or period_end > buy["flight_end"]
        or period_end > store.now()
    ):
        raise ApiError("ERR_REPORT_PERIOD_OUTSIDE_FLIGHT")

    record = store.new(
        "reports",
        {
            "buy_id": buy["id"],
            "measurement_basis": measurement_basis,
            "period_start": period_start,
            "period_end": period_end,
            "delivered_impressions": delivered_impressions,
            "delivered_demo_impressions": delivered_demo_impressions,
            "is_post_buy_final": period_end >= buy["flight_end"],
            "dispute_reason": None,
            "status": "SUBMITTED",
        },
    )
    # Filing refreshes the buy's provisional view.
    store.touch(buy)
    return created(serialize("reports", record))


@bp.post("/delivery-reports/<delivery_report_id>/accept")
@require_roles("AgencyBuyer")
def accept_report(delivery_report_id):
    report = get("reports", delivery_report_id)
    if report["status"] != "SUBMITTED":
        raise ApiError("ERR_REPORT_NOT_SUBMITTED")
    buy = store.buys.get(report["buy_id"])
    if buy is None or buy["buy_status"] not in ("PLACED", "IN_FLIGHT"):
        raise ApiError("ERR_BUY_NOT_IN_EXPECTED_STATE")

    report["status"] = "ACCEPTED"
    store.touch(report)

    # Link 1 - the final input set has changed.
    if buy["buy_status"] == "PLACED":
        buy["buy_status"] = "IN_FLIGHT"
    if not report["is_post_buy_final"]:
        if buy["stewardship_status"] == "NOT_STARTED":
            buy["stewardship_status"] = "ON_TRACK"
        store.touch(buy)
        return ok(serialize("reports", report))

    # Link 2 - the post-buy shortfall evaluation.
    _, shortfall_pct = derive.shortfall(buy)
    under_delivered = shortfall_pct >= MAKE_GOOD_TOLERANCE_PCT
    moved = False
    if buy["stewardship_status"] in ("NOT_STARTED", "ON_TRACK", "AT_RISK"):
        buy["stewardship_status"] = (
            "UNDER_DELIVERED" if under_delivered else "WITHIN_TOLERANCE"
        )
        moved = True
    store.touch(buy)

    if under_delivered and moved:
        # Link 3 - a make-good is opened against the buy.
        frozen = derive.open_shortfall_impressions(buy)
        store.new(
            "make_goods",
            {
                "buy_id": buy["id"],
                "offered_forecast_id": None,
                "shortfall_impressions": frozen,
                "shortfall_value_cents": derive.shortfall_value_cents(
                    frozen, buy["agreed_cpm_cents"]
                ),
                "offered_impressions": 0,
                "offered_window_start": None,
                "offered_window_end": None,
                "offer_round": 0,
                "rejection_reason": None,
                "waived_credit_cents": 0,
                "status": "OPEN",
            },
        )
        # Link 4 - the seller's open exposure grows by the frozen shortfall.
        seller = store.sellers.get(buy["seller_id"])
        if seller is not None:
            store.touch(seller)
    return ok(serialize("reports", report))


@bp.post("/delivery-reports/<delivery_report_id>/dispute")
@require_roles("AgencyBuyer")
def dispute_report(delivery_report_id):
    data = body()
    dispute_reason = data.string("dispute_reason")

    report = get("reports", delivery_report_id)
    if report["status"] != "SUBMITTED":
        raise ApiError("ERR_REPORT_NOT_SUBMITTED")

    report["status"] = "DISPUTED"
    report["dispute_reason"] = dispute_reason
    store.touch(report)
    buy = store.buys.get(report["buy_id"])
    if buy is not None:
        # The provisional pair falls; the final pair is untouched.
        store.touch(buy)
    return ok(serialize("reports", report))


@bp.get("/delivery-reports/<delivery_report_id>")
def get_report(delivery_report_id):
    return read_one("reports", delivery_report_id)


@bp.get("/delivery-reports")
def list_reports():
    return listing(
        "reports",
        {
            "buy_id": "buy_id",
            "status": "status",
            "measurement_basis": "measurement_basis",
        },
    )
