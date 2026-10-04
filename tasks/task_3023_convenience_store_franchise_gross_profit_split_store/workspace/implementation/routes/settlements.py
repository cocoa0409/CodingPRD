"""Settlement and RevenueLine routes."""

from decimal import Decimal
from datetime import timedelta

from flask import Blueprint, request

import db
import middleware
import schemas
import services
import timeutil
from errors import fail
from response import ok
from routes.common import SHARED, list_records

bp = Blueprint("settlements", __name__)

CATEGORIES = ("MERCHANDISE", "FUEL", "SERVICES")


@bp.post("/settlements")
@middleware.auth(("FranchisorAdmin",))
def create_settlement():
    payload = middleware.body(
        required=("store_id", "franchisee_id", "period_start", "period_end",
                  "trailing_avg_gross_profit_cents", "expected_store_version"),
    )
    store = services.require_store(payload["store_id"])
    expected = payload["expected_store_version"]
    if isinstance(expected, bool) or not isinstance(expected, int):
        fail("ERR_INVALID_REQUEST")
    if expected != store["version"]:
        fail("ERR_STALE_VERSION")

    franchisee = services.require_franchisee(payload["franchisee_id"])
    period_start = timeutil.required_utc(payload["period_start"])
    period_end = timeutil.required_utc(payload["period_end"])
    if period_end <= period_start:
        fail("ERR_INVALID_REQUEST")
    trailing = middleware.non_negative_int(payload["trailing_avg_gross_profit_cents"],
                                          "trailing_avg_gross_profit_cents")

    if services.covering_agreement(store["id"]) is None:
        fail("ERR_NO_OPEN_AGREEMENT")

    record = db.insert("settlements", {
        "store_id": store["id"],
        "franchisee_id": franchisee["id"],
        "period_start": period_start,
        "period_end": period_end,
        "trailing_avg_gross_profit_cents": trailing,
        "gross_sales_cents": 0,
        "cost_of_goods_cents": 0,
        "rebate_credit_cents": Decimal("0.00"),
        "gross_profit_cents": Decimal("0.00"),
        "provisional_gross_profit_cents": Decimal("0.00"),
        "eligible_split_pct": Decimal("0.00"),
        "provisional_split_cents": Decimal("0.00"),
        "franchisee_split_cents": Decimal("0.00"),
        "franchisor_share_cents": Decimal("0.00"),
        "shrink_charge_cents": Decimal("0.00"),
        "waste_charge_cents": Decimal("0.00"),
        "draw_recovery_cents": Decimal("0.00"),
        "net_settlement_cents": Decimal("0.00"),
        "provisional": True,
        "status": "OPEN",
        "dispute_reason": None,
    })
    store["version"] = store["version"] + 1
    store["updated_at"] = db.now()
    return ok(schemas.dump("settlements", record), 201)


@bp.get("/settlements")
@middleware.auth(SHARED)
def list_settlements():
    if getattr(request, "acting_role", None) == "Franchisee":
        identity = getattr(request, "acting_identity", None)
        if request.args.get("franchisee_id") not in (None, identity):
            fail("ERR_NOT_RESOURCE_OWNER")
    return list_records("settlements", ("store_id", "franchisee_id", "status"))


@bp.get("/settlements/<settlement_id>")
@middleware.auth(SHARED)
def get_settlement(settlement_id):
    settlement = services.require("settlements", settlement_id)
    return ok(schemas.dump("settlements", settlement))


@bp.post("/settlements/<settlement_id>/revenue-lines")
@middleware.auth(("FranchisorAdmin",))
def create_revenue_line(settlement_id):
    settlement = services.require("settlements", settlement_id)
    payload = middleware.body(
        required=("category", "gross_sales_cents", "cost_of_goods_cents",
                  "expected_settlement_version"),
    )
    expected = payload["expected_settlement_version"]
    if isinstance(expected, bool) or not isinstance(expected, int):
        fail("ERR_INVALID_REQUEST")
    if expected != settlement["version"]:
        fail("ERR_STALE_VERSION")
    category = middleware.enum_value(payload["category"], CATEGORIES, "category")
    gross_sales = middleware.non_negative_int(payload["gross_sales_cents"], "gross_sales_cents")
    cost_of_goods = middleware.non_negative_int(payload["cost_of_goods_cents"], "cost_of_goods_cents")

    record = db.insert("revenue_lines", {
        "settlement_id": settlement["id"],
        "category": category,
        "gross_sales_cents": gross_sales,
        "cost_of_goods_cents": cost_of_goods,
        "line_gross_profit_cents": gross_sales - cost_of_goods,
    })
    services.recalculate_settlement_money(settlement)
    # The append advances the settlement's concurrency token; mirror it on the
    # returned row so the caller observes the settlement's new version.
    record["version"] = settlement["version"]
    return ok(schemas.dump("revenue_lines", record), 201)


def _non_recommended_in_scope(settlement):
    for rebate in db.all_of("rebates"):
        if rebate["store_id"] != settlement["store_id"]:
            continue
        if rebate["recommended_vendor"] or rebate["status"] == "RETRACTED":
            continue
        if timeutil.overlaps(rebate["period_start"], rebate["period_end"],
                             settlement["period_start"], settlement["period_end"]):
            return rebate
    return None


def _unfinalized_audit(settlement):
    for audit in db.all_of("shrink_audits"):
        if audit["store_id"] != settlement["store_id"]:
            continue
        if timeutil.overlaps(audit["period_start"], audit["period_end"],
                             settlement["period_start"], settlement["period_end"]):
            if audit["status"] != "FINALIZED":
                return audit
    return None


def _unreconciled_order(settlement):
    for order in db.all_of("fresh_orders"):
        if order["store_id"] != settlement["store_id"]:
            continue
        window = db.get("delivery_windows", order["delivery_window_id"])
        if window is None:
            continue
        if not timeutil.overlaps(window["window_start"], window["window_end"],
                                 settlement["period_start"], settlement["period_end"]):
            continue
        if order["status"] not in ("RECONCILED", "CANCELLED"):
            return order
    return None


@bp.post("/settlements/<settlement_id>/reconcile")
@middleware.auth(("FranchisorAdmin",))
def reconcile_settlement(settlement_id):
    settlement = services.require("settlements", settlement_id)

    if settlement["status"] not in ("OPEN", "DRAW_PAID"):
        fail("ERR_INVALID_STATE")

    store = services.require_store(settlement["store_id"])
    if store["status"] != "ACTIVE":
        fail("ERR_STORE_NOT_ACTIVE")

    if settlement["status"] == "OPEN":
        if not db.find("revenue_lines", settlement_id=settlement["id"]):
            fail("ERR_NO_REVENUE_LINES")
        if _non_recommended_in_scope(settlement) is not None:
            fail("ERR_VENDOR_NOT_RECOMMENDED")
        agreement = services.covering_agreement(settlement["store_id"])
        if agreement is None:
            fail("ERR_NO_OPEN_AGREEMENT")
        settlement["status"] = "DRAW_PAID"
        _apply_rebates(settlement, agreement)
        services.recalculate_settlement_money(settlement)
        return ok(schemas.dump("settlements", settlement))

    if services.covering_agreement(settlement["store_id"]) is None:
        fail("ERR_NO_OPEN_AGREEMENT")
    if _unfinalized_audit(settlement) is not None:
        fail("ERR_UNFINALIZED_SHRINK_AUDIT")
    if _unreconciled_order(settlement) is not None:
        fail("ERR_UNRECONCILED_FRESH_ORDER")

    agreement = services.covering_agreement(settlement["store_id"])
    waste_share_pct = services.dec(agreement["waste_share_pct"]) if agreement else Decimal(0)

    settlement["status"] = "RECONCILED"
    total_shrink = Decimal(0)
    for audit in db.all_of("shrink_audits"):
        if audit["status"] != "FINALIZED" or audit["store_id"] != settlement["store_id"]:
            continue
        if timeutil.overlaps(audit["period_start"], audit["period_end"],
                             settlement["period_start"], settlement["period_end"]):
            total_shrink += services.dec(audit["shrink_charge_cents"])
    settlement["shrink_charge_cents"] = total_shrink

    waste_total, _ = services.waste_share_allocation(
        settlement["store_id"], settlement["period_start"], settlement["period_end"],
        waste_share_pct)
    settlement["waste_charge_cents"] = waste_total
    settlement["provisional"] = False
    # The net settlement is frozen here; the draw recovery waterfall belongs to
    # the FINALIZED step, which is the only place the settlement's payout is
    # actually used to recover advances.
    services.recalculate_settlement_net(settlement)
    franchisee = db.get("franchisees", settlement["franchisee_id"])
    if franchisee is not None:
        services.recalculate_franchisee(franchisee)
    db.touch(settlement)
    return ok(schemas.dump("settlements", settlement))


def _apply_rebates(settlement, agreement):
    """Settlement OPEN -> DRAW_PAID: cascade hop 1 applies in-scope rebates."""
    lines = db.find("revenue_lines", settlement_id=settlement["id"])
    weights = [(line["category"], line["gross_sales_cents"]) for line in lines]
    pass_pct = services.dec(agreement["rebate_pass_pct"])

    for rebate in db.all_of("rebates"):
        if rebate["store_id"] != settlement["store_id"] or rebate["status"] != "POSTED":
            continue
        if not rebate["recommended_vendor"]:
            continue
        if not timeutil.overlaps(rebate["period_start"], rebate["period_end"],
                                 settlement["period_start"], settlement["period_end"]):
            continue
        rebate["status"] = "APPLIED"
        rebate["covering_settlement_id"] = settlement["id"]
        rebate["flowthrough_cents"] = services.rebate_flowthrough(
            rebate["rebate_cents"], pass_pct, weights)
        db.touch(rebate)


@bp.post("/settlements/<settlement_id>/disputes")
@middleware.auth(("Franchisee",))
def dispute_settlement(settlement_id):
    settlement = services.require("settlements", settlement_id)
    services.require_state(settlement, "RECONCILED")
    identity = getattr(request, "acting_identity", None)
    if identity != settlement["franchisee_id"]:
        fail("ERR_FORBIDDEN")
    payload = middleware.body(required=("dispute_reason",))
    reason = middleware.string_value(payload["dispute_reason"], "dispute_reason")
    if db.clock() > settlement["period_end"] + timedelta(days=14):
        fail("ERR_SETTLEMENT_COOLOFF_NOT_ELAPSED")
    settlement["status"] = "DISPUTED"
    settlement["dispute_reason"] = reason
    db.touch(settlement)
    return ok(schemas.dump("settlements", settlement), 201)


@bp.post("/settlements/<settlement_id>/resolve-dispute")
@middleware.auth(("FranchisorAdmin",))
def resolve_dispute(settlement_id):
    settlement = services.require("settlements", settlement_id)
    services.require_state(settlement, "DISPUTED")
    agreement = services.covering_agreement(settlement["store_id"])
    waste_share_pct = services.dec(agreement["waste_share_pct"]) if agreement else Decimal(0)

    settlement["status"] = "RECONCILED"
    settlement["dispute_reason"] = None
    waste_total, _ = services.waste_share_allocation(
        settlement["store_id"], settlement["period_start"], settlement["period_end"],
        waste_share_pct)
    settlement["waste_charge_cents"] = waste_total
    services.recalculate_settlement_net(settlement)
    db.touch(settlement)
    return ok(schemas.dump("settlements", settlement))


@bp.post("/settlements/<settlement_id>/finalize")
@middleware.auth(("FranchisorAdmin",))
def finalize_settlement(settlement_id):
    settlement = services.require("settlements", settlement_id)
    services.require_state(settlement, "RECONCILED")
    if db.clock() < settlement["period_end"] + timedelta(days=7):
        fail("ERR_SETTLEMENT_COOLOFF_NOT_ELAPSED")
    services.finalize_settlement(settlement)
    return ok(schemas.dump("settlements", settlement))


# ---------------------------------------------------------------------------
# RevenueLine reads
# ---------------------------------------------------------------------------

line_bp = Blueprint("revenue_lines", __name__)


@line_bp.get("/revenue-lines")
@middleware.auth(SHARED)
def list_revenue_lines():
    return list_records("revenue_lines", ("settlement_id", "category"))


@line_bp.get("/revenue-lines/<line_id>")
@middleware.auth(SHARED)
def get_revenue_line(line_id):
    line = services.require("revenue_lines", line_id)
    return ok(schemas.dump("revenue_lines", line))