"""Computed reports: seigniorage per denomination and metal exposure per
commodity (PRD §2.9, §3.1, §3.2)."""
from flask import Blueprint, request

import serialize
import store
from helpers import auth, bad_request, envelope, not_found

bp = Blueprint("reports", __name__)

REPORT_TYPES = {"seigniorage", "metal-exposure"}
EXPOSURE_VARIANTS = {"mark_to_market", "budget_variance"}


@bp.route("/mint/reports/<report_type>", methods=["GET"])
def get_report(report_type):
    auth("FinanceOfficer", "ProductionPlanner", "ProgramManager",
         "MintDirector", "PlatformAdmin", "ProcurementOfficer")
    if report_type not in REPORT_TYPES:
        not_found("Unknown report_type: %s" % report_type)
    if report_type == "seigniorage":
        rows = _seigniorage_rows()
    else:
        rows = _metal_exposure_rows()
    return envelope({"report_type": report_type, "rows": rows},
                    response_type="object", status=200)


def _seigniorage_rows():
    fy_raw = request.args.get("fiscal_year")
    fiscal_year = None
    if fy_raw is not None:
        try:
            fiscal_year = int(fy_raw, 10)
        except (ValueError, TypeError):
            bad_request("fiscal_year must be an integer")
    code_filter = request.args.get("denomination_code")
    rows = []
    for code in sorted(store.db["denominations"].keys()):
        if code_filter is not None and code != code_filter:
            continue
        d = store.db["denominations"][code]
        orders = [o for o in store.db["fed_orders"].values()
                  if o["denomination_code"] == code]
        if fiscal_year is not None:
            orders = [o for o in orders if o["fiscal_year"] == fiscal_year]
        budgeted = sum(o["budgeted_seigniorage_cents"] for o in orders
                       if o["status"] != "CANCELLED")
        realized = sum(o["realized_seigniorage_cents"] for o in orders
                       if o["status"] == "FULFILLED")
        runs = [r for r in store.db["runs"].values()
                if r["denomination_code"] == code]
        rows.append({
            "denomination_code": code,
            "budgeted_seigniorage_cents": serialize.num_out(budgeted),
            "realized_seigniorage_cents": serialize.num_out(realized),
            "blanks_on_hand_pieces": d["blank_stock_pieces"],
            "blanks_reserved_pieces": sum(
                r["reserved_blanks"] for r in runs
                if r["status"] in ("STRIKING", "INSPECTION")),
            "blanks_produced_pieces": sum(r["produced_pieces"] for r in runs),
            "blanks_scrapped_pieces": sum(r["scrapped_pieces"] for r in runs),
            "blanks_delivered_pieces": sum(
                l["blanks_produced"] for l in store.db["lots"].values()
                if l["denomination_code"] == code and l["status"] == "DELIVERED"),
        })
    return rows


def _metal_exposure_rows():
    variant = request.args.get("variant", "mark_to_market")
    if variant not in EXPOSURE_VARIANTS:
        bad_request("variant must be mark_to_market or budget_variance")
    commodity_filter = request.args.get("commodity")
    by_commodity = {}
    for l in store.db["lots"].values():
        # Only unhedged lots in ORDERED or DELIVERED are exposed.
        if l["locked_unit_price_cents_per_tonne"] is not None:
            continue
        if l["status"] not in ("ORDERED", "DELIVERED"):
            continue
        c = l["commodity"]
        if commodity_filter is not None and c != commodity_filter:
            continue
        spot = store.db["spot_prices"].get(c)
        if spot is None:
            continue
        base = (l["order_spot_cents_per_tonne"] if variant == "mark_to_market"
                else l["budget_price_cents_per_tonne"])
        by_commodity[c] = by_commodity.get(c, 0) + l["quantity_tonnes"] * (spot - base)
    return [{"commodity": c, "exposure_cents": by_commodity[c]}
            for c in sorted(by_commodity.keys())]
