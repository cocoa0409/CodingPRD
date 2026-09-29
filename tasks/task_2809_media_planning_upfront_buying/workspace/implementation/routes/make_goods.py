"""The make-good remedy cycle (PRD 3.8)."""

from flask import Blueprint

from auth import require_roles, require_seller_owner
from constants import MAX_MAKE_GOOD_OFFERS
from errors import ApiError
from lookup import get
from response import ok
from routes.common import listing, read_one
from serializers import serialize
from services import cascades, derive
from store import store
from validation import body, require_window

bp = Blueprint("make_goods", __name__)

TERMINAL = ("SCHEDULED", "WAIVED")


def _guard_terminal(make_good):
    if make_good["status"] in TERMINAL:
        raise ApiError("ERR_ALREADY_TERMINAL")


@bp.post("/make-goods/<make_good_id>/offer")
@require_roles("SellerRep")
def offer_make_good(make_good_id):
    data = body()
    offered_forecast_id = data.string("offered_forecast_id")
    offered_impressions = data.integer("offered_impressions", minimum=1)
    offered_window_start = data.timestamp("offered_window_start")
    offered_window_end = data.timestamp("offered_window_end")
    require_window(offered_window_start, offered_window_end, "offered_window")

    make_good = get("make_goods", make_good_id)
    forecast = get("forecasts", offered_forecast_id)
    buy = store.buys.get(make_good["buy_id"])

    if buy is not None:
        require_seller_owner(buy["seller_id"])
    require_seller_owner(forecast["seller_id"])

    _guard_terminal(make_good)
    if make_good["status"] != "OPEN":
        raise ApiError("ERR_MAKE_GOOD_NOT_IN_EXPECTED_STATE")
    if forecast["status"] != "PUBLISHED":
        raise ApiError("ERR_FORECAST_NOT_PUBLISHED")
    if (
        offered_window_start < forecast["window_start"]
        or offered_window_end > forecast["window_end"]
        or offered_window_start < store.now()
    ):
        raise ApiError("ERR_MAKE_GOOD_WINDOW_INVALID")
    if make_good["offer_round"] + 1 > MAX_MAKE_GOOD_OFFERS:
        raise ApiError("ERR_MAKE_GOOD_OFFER_CAP_REACHED")
    # The permission rule sits above both the shortfall and the capacity rule.
    if buy is not None and buy["make_good_provision"] == "NONE":
        raise ApiError("ERR_MAKE_GOOD_NOT_PERMITTED")
    if offered_impressions < make_good["shortfall_impressions"]:
        raise ApiError("ERR_MAKE_GOOD_OFFER_INSUFFICIENT")
    seller = store.sellers.get(buy["seller_id"]) if buy is not None else None
    if seller is not None:
        exposure = derive.seller_exposure(seller)
        headroom = (
            seller["make_good_capacity_impressions"]
            - exposure["scheduled_make_good_impressions"]
        )
        if offered_impressions > headroom:
            raise ApiError("ERR_MAKE_GOOD_CAPACITY_EXCEEDED")

    make_good["offered_forecast_id"] = forecast["id"]
    make_good["offered_impressions"] = offered_impressions
    make_good["offered_window_start"] = offered_window_start
    make_good["offered_window_end"] = offered_window_end
    make_good["offer_round"] += 1
    make_good["status"] = "OFFERED"
    store.touch(make_good)
    return ok(serialize("make_goods", make_good))


@bp.post("/make-goods/<make_good_id>/accept")
@require_roles("AgencyBuyer")
def accept_make_good(make_good_id):
    make_good = get("make_goods", make_good_id)
    _guard_terminal(make_good)
    if make_good["status"] != "OFFERED":
        raise ApiError("ERR_MAKE_GOOD_NOT_IN_EXPECTED_STATE")
    forecast = store.forecasts.get(make_good["offered_forecast_id"])
    if forecast is None or forecast["status"] != "PUBLISHED":
        raise ApiError("ERR_FORECAST_NOT_PUBLISHED")
    if make_good["offered_impressions"] > derive.available_impressions(forecast):
        raise ApiError("ERR_FORECAST_AVAIL_EXCEEDED")

    buy = store.buys.get(make_good["buy_id"])
    make_good["status"] = "SCHEDULED"
    store.touch(make_good)

    # A make-good is compensation, not a new sale: the rate is zero.
    store.new(
        "units",
        {
            "buy_id": make_good["buy_id"],
            "forecast_id": forecast["id"],
            "make_good_id": make_good["id"],
            "daypart": forecast["daypart"],
            "program": forecast["program"],
            "platform": forecast["platform"],
            "units": 1,
            "unit_rate_cents": 0,
            "projected_impressions": make_good["offered_impressions"],
            "actual_impressions": 0,
            "air_window_start": make_good["offered_window_start"],
            "air_window_end": make_good["offered_window_end"],
            "exclusive": False,
            "line_net_cents": 0,
            "line_commission_cents": 0,
            "line_gross_cents": 0,
            "status": "MAKE_GOOD_SCHEDULED",
        },
    )
    cascades.sync_forecast(forecast)

    if buy is not None:
        buy["made_good_impressions"] += make_good["offered_impressions"]
        cascades.settle_open_shortfall(buy)
        seller = store.sellers.get(buy["seller_id"])
        if seller is not None:
            store.touch(seller)
    return ok(serialize("make_goods", make_good))


@bp.post("/make-goods/<make_good_id>/reject")
@require_roles("AgencyBuyer")
def reject_make_good(make_good_id):
    data = body()
    rejection_reason = data.string("rejection_reason")

    make_good = get("make_goods", make_good_id)
    _guard_terminal(make_good)
    if make_good["status"] != "OFFERED":
        raise ApiError("ERR_MAKE_GOOD_NOT_IN_EXPECTED_STATE")

    # The offered fields are deliberately retained for audit.
    make_good["rejection_reason"] = rejection_reason
    make_good["status"] = "OPEN"
    store.touch(make_good)
    return ok(serialize("make_goods", make_good))


@bp.post("/make-goods/<make_good_id>/waive")
@require_roles("AgencyController")
def waive_make_good(make_good_id):
    data = body(required=False)
    credit_cents = data.integer("credit_cents", required=False, minimum=1)

    make_good = get("make_goods", make_good_id)
    _guard_terminal(make_good)
    if make_good["status"] not in ("OPEN", "OFFERED"):
        raise ApiError("ERR_MAKE_GOOD_NOT_IN_EXPECTED_STATE")
    buy = store.buys.get(make_good["buy_id"])
    if buy is not None and buy["make_good_provision"] == "NONE":
        raise ApiError("ERR_MAKE_GOOD_NOT_PERMITTED")

    make_good["waived_credit_cents"] = (
        credit_cents if credit_cents is not None else make_good["shortfall_value_cents"]
    )
    make_good["status"] = "WAIVED"
    store.touch(make_good)

    if buy is not None:
        buy["waived_impressions"] += make_good["shortfall_impressions"]
        cascades.settle_open_shortfall(buy)
        seller = store.sellers.get(buy["seller_id"])
        if seller is not None:
            store.touch(seller)
        _recredit_draft_invoices(buy)
    return ok(serialize("make_goods", make_good))


def _recredit_draft_invoices(buy):
    """The credit reaches back into billing; issued invoices are untouched."""
    advertiser = derive.advertiser_of_buy(buy)
    credit = derive.make_good_credit_cents(buy)
    for invoice in derive.invoices_of_buy(buy["id"]):
        if invoice["client_status"] != "DRAFT":
            continue
        invoice["make_good_credit_cents"] = credit
        invoice["net_payable_cents"] = derive.net_payable_cents(
            invoice["gross_billable_cents"], credit
        )
        invoice["max_remittable_cents"] = derive.max_remittable_cents(
            invoice, advertiser
        )
        store.touch(invoice)


@bp.get("/make-goods/<make_good_id>")
def get_make_good(make_good_id):
    return read_one("make_goods", make_good_id)


@bp.get("/make-goods")
def list_make_goods():
    return listing(
        "make_goods",
        {
            "buy_id": "buy_id",
            "offered_forecast_id": "offered_forecast_id",
            "status": "status",
        },
    )
