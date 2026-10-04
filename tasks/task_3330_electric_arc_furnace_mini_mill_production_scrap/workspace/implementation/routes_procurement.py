"""Procurement contract and scrap lot routes."""
import uuid
from datetime import datetime, timedelta, timezone
from decimal import Decimal, ROUND_HALF_UP
from flask import Blueprint

import db
from errors import err
from response import (ok, list_response, require_role, require_auth, get_body,
                      req_str, req_enum, req_num, req_int, parse_date)
from services import (get_mill, get_contract, get_lot, new_common, bump,
                      require_index, month_last_day, SETTLEMENT_MIN_FILL_PCT,
                      round_cents)

bp = Blueprint("procurement", __name__)


@bp.route("/mills/<millId>/procurement-contracts", methods=["POST"])
def create_contract(millId):
    require_role("ProcurementOfficer")
    get_mill(millId)
    body = get_body()
    supplier = req_str(body, "supplier_name")
    cat = req_enum(body, "grade_category",
                   {"SHREDDED", "BUSHLING", "HMS", "DRI", "PIG_IRON"})
    ctype = req_enum(body, "contract_type", {"FIXED", "INDEXED"})
    committed = req_num(body, "committed_tons", gt=0)
    price = body.get("contract_price_cents")
    if ctype == "FIXED":
        if price is None:
            raise err("ERR_CONTRACT_PRICE_FORBIDDEN",
                      "FIXED contract requires contract_price_cents")
        if not isinstance(price, int) or isinstance(price, bool) or price < 0:
            raise err("ERR_INVALID_REQUEST", "contract_price_cents must be a non-negative integer")
    else:
        if price is not None:
            raise err("ERR_CONTRACT_PRICE_FORBIDDEN",
                      "INDEXED contract forbids contract_price_cents")
    contract = {
        "id": str(uuid.uuid4()),
        "mill_id": millId,
        "supplier_name": supplier,
        "grade_category": cat,
        "contract_type": ctype,
        "contract_price_cents": price if ctype == "FIXED" else None,
        "committed_tons": committed,
        "received_tons": 0,
        "settlement_tons": None,
        "settlement_amount_cents": None,
        "status": "OPEN",
        **new_common(),
    }
    db.contracts[contract["id"]] = contract
    return ok(contract, 201)


@bp.route("/mills/<millId>/procurement-contracts", methods=["GET"])
def list_contracts(millId):
    require_auth()
    get_mill(millId)
    rows = [c for c in db.contracts.values() if c["mill_id"] == millId]
    return list_response(rows, {"status": "status", "grade_category": "grade_category"})


@bp.route("/mills/<millId>/procurement-contracts/<contractId>", methods=["GET"])
def get_contract_route(millId, contractId):
    require_auth()
    get_mill(millId)
    return ok(get_contract(contractId, millId))


def _settlement(contract, settlement_tons):
    if contract["contract_type"] == "FIXED":
        return round_cents(Decimal(contract["contract_price_cents"]) * Decimal(str(settlement_tons)))
    lots = [l for l in db.scrap_lots.values()
            if l["contract_id"] == contract["id"]
            and l["status"] in ("RECEIVED", "PARTIALLY_CONSUMED", "CONSUMED")]
    lots.sort(key=lambda l: (l["received_on"], l["created_at"]))
    remaining = Decimal(str(settlement_tons))
    amount = 0
    for lot in lots:
        if remaining <= 0:
            break
        take = min(Decimal(str(lot["dry_tons"])), remaining)
        month = lot["received_on"][:7]
        idx = require_index(contract["mill_id"], contract["grade_category"], month)
        amount += round_cents(Decimal(idx["price_per_ton_cents"]) * take)
        remaining -= take
    return amount


@bp.route("/mills/<millId>/procurement-contracts/<contractId>/close", methods=["POST"])
def close_contract(millId, contractId):
    require_role("ProcurementOfficer")
    get_mill(millId)
    contract = get_contract(contractId, millId)
    if contract["status"] != "OPEN":
        raise err("ERR_INVALID_STATE", "contract is not OPEN")
    if Decimal(str(contract["received_tons"])) < SETTLEMENT_MIN_FILL_PCT * Decimal(str(contract["committed_tons"])):
        raise err("ERR_UNDER_DELIVERED", "received tonnage below 80% of commitment")
    settlement_tons = min(contract["received_tons"], contract["committed_tons"])
    amount = _settlement(contract, settlement_tons)
    contract["settlement_tons"] = settlement_tons
    contract["settlement_amount_cents"] = amount
    contract["status"] = "CLOSED"
    bump(contract)
    return ok(contract)


@bp.route("/mills/<millId>/procurement-contracts/<contractId>/default", methods=["POST"])
def default_contract(millId, contractId):
    require_role("ProcurementOfficer")
    get_mill(millId)
    contract = get_contract(contractId, millId)
    if contract["status"] != "OPEN":
        raise err("ERR_INVALID_STATE", "contract is not OPEN")
    lots = [l for l in db.scrap_lots.values() if l["contract_id"] == contract["id"]]
    if lots:
        latest_month = max(l["received_on"][:7] for l in lots)
    else:
        latest_month = db.get_clock().strftime("%Y-%m")
    y, m = int(latest_month[:4]), int(latest_month[5:7])
    last_day = month_last_day(latest_month)
    window_end = datetime(y, m, last_day, tzinfo=timezone.utc) + timedelta(days=7)
    if db.get_clock() < window_end:
        raise err("ERR_INVALID_REQUEST",
                  "settlement window not elapsed (need 7 days past receipt month end)")
    settlement_tons = contract["received_tons"]
    amount = _settlement(contract, settlement_tons)
    contract["settlement_tons"] = settlement_tons
    contract["settlement_amount_cents"] = amount
    contract["status"] = "DEFAULTED"
    bump(contract)
    return ok(contract)


# --- scrap lots -------------------------------------------------------------

@bp.route("/mills/<millId>/procurement-contracts/<contractId>/scrap-lots", methods=["POST"])
def create_lot(millId, contractId):
    require_role("ProcurementOfficer")
    get_mill(millId)
    contract = get_contract(contractId, millId)
    body = get_body()
    received_on = parse_date(req_str(body, "received_on"), "received_on")
    tons_received = req_num(body, "tons_received", gt=0)
    moisture = body.get("moisture_pct", 0.0)
    if not isinstance(moisture, (int, float)) or isinstance(moisture, bool) \
            or moisture < 0.0 or moisture > 0.30:
        raise err("ERR_INVALID_REQUEST", "moisture_pct out of range")
    cu = req_num(body, "cu_pct", ge=0.0, le=0.005)
    mn = req_num(body, "mn_pct", ge=0.0, le=0.02)
    if contract["status"] != "OPEN":
        raise err("ERR_INVALID_STATE", "contract is not OPEN")
    dry = float(Decimal(str(tons_received)) * (Decimal("1") - Decimal(str(moisture))))
    lot = {
        "id": str(uuid.uuid4()),
        "contract_id": contractId,
        "mill_id": millId,
        "received_on": received_on,
        "tons_received": tons_received,
        "moisture_pct": moisture,
        "dry_tons": dry,
        "cu_pct": cu,
        "mn_pct": mn,
        "remaining_tons": dry,
        "status": "RECEIVED",
        "created_at": db.ts_now(),
    }
    db.scrap_lots[lot["id"]] = lot
    contract["received_tons"] = float(Decimal(str(contract["received_tons"])) + Decimal(str(tons_received)))
    return ok(lot, 201)


@bp.route("/mills/<millId>/procurement-contracts/<contractId>/scrap-lots", methods=["GET"])
def list_lots(millId, contractId):
    require_auth()
    get_mill(millId)
    get_contract(contractId, millId)
    rows = [l for l in db.scrap_lots.values() if l["contract_id"] == contractId]
    return list_response(rows, {"status": "status"})


@bp.route("/mills/<millId>/scrap-lots", methods=["GET"])
def list_mill_lots(millId):
    require_auth()
    get_mill(millId)
    rows = [l for l in db.scrap_lots.values() if l["mill_id"] == millId]
    return list_response(rows, {"status": "status"})


@bp.route("/mills/<millId>/scrap-lots/by-id/<lotId>", methods=["GET"])
def get_lot_route(millId, lotId):
    require_auth()
    get_mill(millId)
    lot = get_lot(lotId)
    if lot["mill_id"] != millId:
        raise err("ERR_LOT_NOT_FOUND", "lot not found in mill")
    return ok(lot)


# --- flat reads -------------------------------------------------------------

@bp.route("/mills/procurement-contracts", methods=["GET"])
def flat_list_contracts():
    require_auth()
    return list_response(list(db.contracts.values()),
                         {"mill_id": "mill_id", "status": "status",
                          "grade_category": "grade_category"})


@bp.route("/mills/procurement-contracts/<contractId>", methods=["GET"])
def flat_get_contract(contractId):
    require_auth()
    return ok(get_contract(contractId))


@bp.route("/mills/scrap-lots", methods=["GET"])
def flat_list_lots():
    require_auth()
    return list_response(list(db.scrap_lots.values()),
                         {"mill_id": "mill_id", "contract_id": "contract_id",
                          "status": "status"})


@bp.route("/mills/scrap-lots/<lotId>", methods=["GET"])
def flat_get_lot(lotId):
    require_auth()
    return ok(get_lot(lotId))
