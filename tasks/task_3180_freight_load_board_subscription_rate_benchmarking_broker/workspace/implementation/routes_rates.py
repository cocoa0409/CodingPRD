import math
from datetime import timedelta
from decimal import ROUND_HALF_UP, Decimal

from flask import Blueprint, request

from db import db
from middleware import get_context, require_role
from response import APIError, success
from services import (
    check_org_active,
    find_active_subscription,
    get_broker,
    get_carrier,
    get_txn,
    new_resource,
    paginate,
    parse_limit_offset,
    recompute_contribution_flag,
    require_active_subscription,
    require_enum,
    require_fields,
    require_positive_int,
    sorted_by_created,
    touch,
)
from util import (
    BASE_FUEL_CENTS,
    BENCHMARK_MIN_SAMPLE,
    CONTRIBUTION_WINDOW_DAYS,
    EQUIPMENT_TYPES,
    MAX_FSC_PCT,
    RATE_KINDS,
    STEP_CENTS,
    STEP_PCT,
    VARIANTS,
    iso_ms,
    parse_dt,
)

bp = Blueprint("rates", __name__)

READ_ROLES = ("PlatformAdmin", "ComplianceAnalyst", "DataOps", "BrokerAdmin", "CarrierAdmin")


def fsc_pct(fuel_price_cents):
    if fuel_price_cents is None:
        fuel_price_cents = BASE_FUEL_CENTS
    steps = max(0, math.floor((fuel_price_cents - BASE_FUEL_CENTS) / STEP_CENTS))
    return min(steps * STEP_PCT, MAX_FSC_PCT)


def _round_half_up_cents(x):
    return int(Decimal(str(x)).quantize(Decimal("1"), rounding=ROUND_HALF_UP))


@bp.post("/rate-transactions")
def create_rate_transaction():
    user_id, role = get_context()
    require_role(role, ("BrokerAdmin", "CarrierAdmin"))
    body = request.get_json(silent=True) or {}
    require_fields(body, ["origin", "destination", "equipment_type", "rate_kind",
                          "rate_cents", "fuel_price_cents", "transaction_date"])
    require_enum(body["equipment_type"], EQUIPMENT_TYPES, "equipment_type")
    require_enum(body["rate_kind"], RATE_KINDS, "rate_kind")
    require_positive_int(body["rate_cents"], "rate_cents")
    require_positive_int(body["fuel_price_cents"], "fuel_price_cents")
    td = parse_dt(body["transaction_date"])
    if td is None:
        raise APIError("ERR_INVALID_REQUEST", 400, "transaction_date must be a valid datetime")
    if role == "BrokerAdmin":
        org = get_broker(db, user_id)
        reporter = {"reporter_broker_org_id": org["id"], "reporter_carrier_org_id": None}
        is_broker = True
    else:
        org = get_carrier(db, user_id)
        reporter = {"reporter_broker_org_id": None, "reporter_carrier_org_id": org["id"]}
        is_broker = False
    check_org_active(org)
    txn = new_resource(db, {
        "source": "CONTRIBUTED",
        "booking_id": None,
        **reporter,
        "origin": body["origin"],
        "destination": body["destination"],
        "equipment_type": body["equipment_type"],
        "rate_kind": body["rate_kind"],
        "rate_cents": body["rate_cents"],
        "fuel_price_cents": body["fuel_price_cents"],
        "transaction_date": body["transaction_date"],
        "status": "ACCEPTED",
    })
    db.rate_transactions[txn["id"]] = txn
    recompute_contribution_flag(db, org, is_broker=is_broker)
    return success(txn, 201)


@bp.get("/rate-transactions")
def list_rate_transactions():
    _, role = get_context()
    require_role(role, READ_ROLES)
    limit, offset = parse_limit_offset()
    items = list(db.rate_transactions.values())
    for f in ("booking_id", "reporter_broker_org_id", "reporter_carrier_org_id",
              "origin", "destination", "equipment_type", "rate_kind", "status"):
        v = request.args.get(f)
        if v is not None:
            items = [t for t in items if t.get(f) == v]
    items = sorted_by_created(items)
    page, meta = paginate(items, limit, offset)
    return success(page, 200, meta)


@bp.get("/rate-transactions/<txn_id>")
def get_rate_transaction(txn_id):
    _, role = get_context()
    require_role(role, READ_ROLES)
    return success(get_txn(db, txn_id))


@bp.post("/rate-transactions/<txn_id>/exclude")
def exclude_rate_transaction(txn_id):
    _, role = get_context()
    require_role(role, ("DataOps",))
    txn = get_txn(db, txn_id)
    if txn["status"] != "ACCEPTED":
        raise APIError("ERR_RATE_TRANSACTION_IMMUTABLE", 409, "Transaction is already EXCLUDED")
    txn["status"] = "EXCLUDED"
    touch(db, txn)
    if txn.get("reporter_broker_org_id"):
        org = db.broker_orgs.get(txn["reporter_broker_org_id"])
        if org is not None:
            recompute_contribution_flag(db, org, is_broker=True)
    if txn.get("reporter_carrier_org_id"):
        org = db.carrier_orgs.get(txn["reporter_carrier_org_id"])
        if org is not None:
            recompute_contribution_flag(db, org, is_broker=False)
    return success(txn)


@bp.get("/lane-rate-benchmarks")
def lane_rate_benchmark():
    user_id, role = get_context()
    require_role(role, ("BrokerAdmin", "CarrierAdmin"))
    origin = request.args.get("origin")
    destination = request.args.get("destination")
    equipment_type = request.args.get("equipment_type")
    variant = request.args.get("variant")
    if not origin or not destination or not equipment_type or not variant:
        raise APIError("ERR_INVALID_REQUEST", 400, "origin, destination, equipment_type and variant are required")
    if variant not in VARIANTS:
        raise APIError("ERR_INVALID_REQUEST", 400, "variant must be SPOT_ONLY or BLENDED")
    if equipment_type not in EQUIPMENT_TYPES:
        raise APIError("ERR_INVALID_REQUEST", 400, "Invalid equipment_type")
    if role == "BrokerAdmin":
        org = get_broker(db, user_id)
        is_broker = True
    else:
        org = get_carrier(db, user_id)
        is_broker = False
    check_org_active(org)
    sub = require_active_subscription(
        db, broker_org_id=org["id"] if is_broker else None,
        carrier_org_id=None if is_broker else org["id"])
    plan = db.subscription_plans[sub["plan_id"]]
    depth = plan["analytics_depth"]
    if variant == "SPOT_ONLY" and depth not in ("LANE_LEVEL", "FULL"):
        raise APIError("ERR_ANALYTICS_DEPTH_FORBIDDEN", 403, "SPOT_ONLY requires LANE_LEVEL analytics depth")
    if variant == "BLENDED":
        if depth != "FULL":
            raise APIError("ERR_ANALYTICS_DEPTH_FORBIDDEN", 403, "BLENDED requires FULL analytics depth")
        if plan["requires_data_contribution"]:
            recompute_contribution_flag(db, org, is_broker=is_broker)
            if not org["data_contribution_flag"]:
                raise APIError("ERR_DATA_CONTRIBUTION_REQUIRED", 403,
                               "Caller org's data_contribution_flag is false on a plan requiring contribution")
    now = db.clock
    window_start = now - timedelta(days=CONTRIBUTION_WINDOW_DAYS)
    candidates = []
    for t in db.rate_transactions.values():
        if t["status"] != "ACCEPTED":
            continue
        if t["origin"] != origin or t["destination"] != destination or t["equipment_type"] != equipment_type:
            continue
        td = parse_dt(t["transaction_date"])
        if td is None or not (window_start <= td <= now):
            continue
        if variant == "SPOT_ONLY" and t["rate_kind"] != "SPOT":
            continue
        candidates.append(t)
    if len(candidates) < BENCHMARK_MIN_SAMPLE:
        raise APIError("ERR_INSUFFICIENT_BENCHMARK_DATA", 422, "Fewer than 5 candidate transactions for the lane")

    # Pinned rounding order:
    # 1. per-transaction surcharge and linehaul
    linehauls = []
    fuels = []
    for t in candidates:
        if variant == "BLENDED" and t["rate_kind"] == "CONTRACT":
            effective = _round_half_up_cents(Decimal(t["rate_cents"]) * Decimal("0.95"))
        else:
            effective = t["rate_cents"]
        pct = fsc_pct(t.get("fuel_price_cents"))
        surcharge = _round_half_up_cents(Decimal(effective) * Decimal(str(pct)))
        linehauls.append(effective - surcharge)
        fuels.append(t.get("fuel_price_cents") if t.get("fuel_price_cents") is not None else BASE_FUEL_CENTS)
    # 2. sort linehaul ASC; nearest-rank percentiles
    linehauls.sort()
    n = len(linehauls)

    def pct_rank(k):
        idx = max(1, math.ceil(k / 100 * n)) - 1
        return linehauls[idx]

    p25 = pct_rank(25)
    p50 = pct_rank(50)
    p75 = pct_rank(75)
    # 3. fuel-adjusted p50 using median fuel price
    fuels.sort()
    median_fuel = fuels[max(1, math.ceil(n / 2)) - 1]
    fuel_adjusted_p50 = p50 + _round_half_up_cents(Decimal(p50) * Decimal(str(fsc_pct(median_fuel))))
    return success({
        "lane_key": f"{origin}:{destination}:{equipment_type}",
        "sample_count": n,
        "p25_linehaul_cents": p25,
        "p50_linehaul_cents": p50,
        "p75_linehaul_cents": p75,
        "fuel_adjusted_p50_cents": fuel_adjusted_p50,
        "variant": variant,
    })
