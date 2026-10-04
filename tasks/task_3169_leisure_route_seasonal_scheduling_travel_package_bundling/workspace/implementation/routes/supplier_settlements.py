"""Supplier settlements: create (provisional), list, get, finalize."""

from flask import Blueprint, request

import db
from common import (
    new_entity,
    get_or_404,
    body,
    require_field,
    require_date,
    touch,
    parse_date,
    logical_clock_date,
)
from errors import ApiError
from middleware import require_role, require_any_authenticated
from response import ok, paginate

bp = Blueprint("supplier_settlements", __name__)


def _get_settlement_or_404(settlement_id):
    return get_or_404(
        db.supplier_settlements,
        settlement_id,
        "ERR_SETTLEMENT_NOT_FOUND",
        "SupplierSettlement",
    )


def _compute_gross_payable(supplier_code, period_start, period_end, variant):
    """Sum net_cost_cents of supplier's offers for qualifying bundles.

    variant == "provisional": bundle_status in {ACTIVE, CANCELLED}
    variant == "final": bundle_status == ACTIVE only
    Bundle qualifies when its booking's flight_date is in [start, end].
    """
    if variant == "provisional":
        allowed = {"ACTIVE", "CANCELLED"}
    else:
        allowed = {"ACTIVE"}

    total = 0
    counted_bundles = []
    for bundle in db.package_bundles.values():
        if bundle["bundle_status"] not in allowed:
            continue
        booking = db.bookings.get(bundle["booking_id"])
        if booking is None:
            continue
        flight = db.flight_instances.get(booking["flight_instance_id"])
        if flight is None:
            continue
        if not (period_start <= flight["flight_date"] <= period_end):
            continue
        # Sum net cost for every offer of this supplier consumed by the bundle
        bundle_total = 0
        for field in ("hotel_offer_id", "rental_car_offer_id", "attraction_offer_id"):
            offer_id = bundle.get(field)
            if not offer_id:
                continue
            offer = db.supplier_offers.get(offer_id)
            if offer is None:
                continue
            if offer["supplier_code"] != supplier_code:
                continue
            bundle_total += offer["net_cost_cents"]
        if bundle_total > 0:
            total += bundle_total
            counted_bundles.append(bundle)
    return total, counted_bundles


@bp.route("/supplier-settlements", methods=["POST"])
def create_settlement():
    require_role("FinanceAnalyst")
    data = body()
    supplier_code = require_field(data, "supplier_code", str)
    start = require_date(data, "period_start_date")
    end = require_date(data, "period_end_date")
    if parse_date(end) < parse_date(start):
        raise ApiError(
            "ERR_VALIDATION",
            "period_end_date must be on or after period_start_date",
            422,
        )
    gross, _ = _compute_gross_payable(supplier_code, start, end, "provisional")
    ent = new_entity(
        {
            "supplier_code": supplier_code,
            "period_start_date": start,
            "period_end_date": end,
            "gross_payable_cents": gross,
            "clawback_cents": 0,
            "settlement_status": "PROVISIONAL",
        }
    )
    db.supplier_settlements[ent["id"]] = ent
    return ok(ent, 201)


@bp.route("/supplier-settlements", methods=["GET"])
def list_settlements():
    require_any_authenticated()
    items = list(db.supplier_settlements.values())
    sc = request.args.get("supplier_code")
    if sc:
        items = [s for s in items if s["supplier_code"] == sc]
    status = request.args.get("settlement_status")
    if status:
        items = [s for s in items if s["settlement_status"] == status]
    items.sort(key=lambda s: (s["created_at"], s["id"]))
    page, meta = paginate(items)
    return ok(page, 200, pagination=meta)


@bp.route("/supplier-settlements/<settlement_id>", methods=["GET"])
def get_settlement(settlement_id):
    require_any_authenticated()
    ent = _get_settlement_or_404(settlement_id)
    return ok(ent)


@bp.route("/supplier-settlements/<settlement_id>/finalize", methods=["POST"])
def finalize_settlement(settlement_id):
    require_role("FinanceAnalyst")
    settlement = _get_settlement_or_404(settlement_id)
    if settlement["settlement_status"] != "PROVISIONAL":
        raise ApiError(
            "ERR_SETTLEMENT_NOT_PROVISIONAL",
            "Finalize requires PROVISIONAL settlement",
            409,
        )
    clock_date = logical_clock_date()
    if clock_date <= parse_date(settlement["period_end_date"]):
        raise ApiError(
            "ERR_SETTLEMENT_PERIOD_OPEN",
            "Finalize before period_end_date has passed",
            422,
        )
    gross, counted = _compute_gross_payable(
        settlement["supplier_code"],
        settlement["period_start_date"],
        settlement["period_end_date"],
        "final",
    )
    settlement["gross_payable_cents"] = gross
    settlement["settlement_status"] = "FINALIZED"
    touch(settlement)
    for bundle in counted:
        bundle["bundle_status"] = "SETTLED"
        touch(bundle)
    return ok(settlement)
