"""Contract routes: create (atomic with payloads), list, read, sign, rebook,
payload listing."""
import math
from datetime import datetime, timezone
from decimal import Decimal

from flask import Blueprint, g, request

from calc import quote_price_cents
from envelope import success, success_list
from errors import (
    ERR_CONTRACT_NOT_FOUND,
    ERR_CUSTOMER_NOT_FOUND,
    ERR_INVALID_STATE,
    ERR_MISSION_NOT_FOUND,
    ERR_REBOOKING_NOT_ELIGIBLE,
    ERR_STALE_CONTRACT_VERSION,
    ERR_WINDOW_INCOMPATIBLE,
    bad_request,
    conflict,
    not_found,
    stale,
    unprocessable,
)
from middleware import require_roles
from serialize import ser_contract, ser_payload
from store import bump, db, new_entity, now, touch
from util import round_half_up_int
from validate import (
    as_dt,
    as_enum,
    as_int,
    as_positive_number,
    as_str,
    body_json,
    check_window,
    opt_enum_filter,
    opt_field,
    paginate,
    parse_pagination,
    req_field,
)

bp = Blueprint("contracts", __name__)

PRICING_MODES = {"MARGINAL", "FLAT"}
INTERFACE_CLASSES = {"RING_15", "RING_24", "CUBESAT"}
ORBITS = {"SSO", "LEO", "GTO"}
CONTRACT_STATUSES = {"DRAFT", "SIGNED", "MANIFESTED", "FULFILLED", "EXPIRED"}
PAYLOAD_STATUSES = {"REGISTERED", "MANIFESTED", "DEPLOYED"}

FEE_PCT_FAR = Decimal("0.10")
FEE_PCT_MID = Decimal("0.25")
FEE_PCT_NEAR = Decimal("0.50")
FAR_MIN_DAYS = 61
MID_MIN_DAYS = 31


def _load_contract_scoped(cid):
    """Customer scoping (stage 3): a Customer caller may only touch its own
    contracts; violations surface as ERR_CONTRACT_NOT_FOUND."""
    c = db["contracts"].get(cid)
    if g.user_role == "Customer" and (c is None or c["customer_id"] != g.user_id):
        raise not_found(ERR_CONTRACT_NOT_FOUND, f"contract {cid} not found")
    return c


def _load_contract(cid):
    c = db["contracts"].get(cid)
    if c is None:
        raise not_found(ERR_CONTRACT_NOT_FOUND, f"contract {cid} not found")
    return c


@bp.post("/rideshare/contracts")
@require_roles("ContractManager")
def create_contract():
    body = body_json()
    customer_id = as_str(req_field(body, "customer_id"), "customer_id")
    pricing_mode = as_enum(req_field(body, "pricing_mode"), "pricing_mode", PRICING_MODES)
    wopen = as_dt(req_field(body, "window_open_utc"), "window_open_utc")
    wclose = as_dt(req_field(body, "window_close_utc"), "window_close_utc")
    check_window(wopen, wclose)
    payloads_in = req_field(body, "payloads")
    if not isinstance(payloads_in, list):
        raise bad_request("field payloads must be an array")
    # Validate every payload entry first — the create is atomic across the array.
    parsed = []
    for i, entry in enumerate(payloads_in):
        if not isinstance(entry, dict):
            raise bad_request(f"payloads[{i}] must be an object")
        parsed.append(
            {
                "payload_name": as_str(
                    req_field(entry, "payload_name"), f"payloads[{i}].payload_name"
                ),
                "mass_kg": as_positive_number(
                    req_field(entry, "mass_kg"), f"payloads[{i}].mass_kg"
                ),
                "volume_m3": as_positive_number(
                    req_field(entry, "volume_m3"), f"payloads[{i}].volume_m3"
                ),
                "interface_class": as_enum(
                    req_field(entry, "interface_class"),
                    f"payloads[{i}].interface_class",
                    INTERFACE_CLASSES,
                ),
                "required_orbit": as_enum(
                    req_field(entry, "required_orbit"),
                    f"payloads[{i}].required_orbit",
                    ORBITS,
                ),
            }
        )
    target_mission_id = opt_field(body, "target_mission_id", None)
    if target_mission_id is not None:
        target_mission_id = as_str(target_mission_id, "target_mission_id")
    rebookings_in = opt_field(body, "rebookings_remaining", None)
    if rebookings_in is not None:
        rebookings_in = as_int(rebookings_in, "rebookings_remaining")

    # existence, body fields in declared input order: customer_id, then target_mission_id
    customer = db["customers"].get(customer_id)
    if customer is None:
        raise not_found(ERR_CUSTOMER_NOT_FOUND, f"customer {customer_id} not found")
    if target_mission_id is not None and target_mission_id not in db["missions"]:
        raise not_found(
            ERR_MISSION_NOT_FOUND, f"mission {target_mission_id} not found"
        )

    if rebookings_in is None or rebookings_in == -1:
        rebookings = customer["default_rebookings"]
    else:
        rebookings = rebookings_in

    c = new_entity()
    c.update(
        {
            "customer_id": customer_id,
            "target_mission_id": target_mission_id,
            "pricing_mode": pricing_mode,
            "window_open_utc": wopen,
            "window_close_utc": wclose,
            "rebookings_remaining": rebookings,
            "quoted_price_cents": 0,
            "total_rebooking_fees_cents": 0,
            "rebook_eligible": False,
            "status": "DRAFT",
        }
    )
    db["contracts"][c["id"]] = c
    for entry in parsed:
        p = new_entity()
        p.update(
            {
                "contract_id": c["id"],
                "payload_name": entry["payload_name"],
                "mass_kg": entry["mass_kg"],
                "volume_m3": entry["volume_m3"],
                "interface_class": entry["interface_class"],
                "required_orbit": entry["required_orbit"],
                "status": "REGISTERED",
            }
        )
        db["payloads"][p["id"]] = p
    return success(ser_contract(c), 201)


@bp.get("/rideshare/contracts")
@require_roles("ContractManager", "Customer", "MissionOps")
def list_contracts():
    status = opt_enum_filter(request.args, "status", CONTRACT_STATUSES)
    customer_id = request.args.get("customer_id")
    target_mission_id = request.args.get("target_mission_id")
    limit, offset = parse_pagination(request.args)

    if g.user_role == "Customer":
        customer_id = g.user_id  # auto-filter to the caller's own customer_id
    rows = list(db["contracts"].values())
    if customer_id is not None:
        rows = [c for c in rows if c["customer_id"] == customer_id]
    if target_mission_id is not None:
        rows = [c for c in rows if c["target_mission_id"] == target_mission_id]
    if status is not None:
        rows = [c for c in rows if c["status"] == status]
    rows.sort(key=lambda c: (c["created_at"], c["_seq"]))
    page, total = paginate(rows, limit, offset)
    return success_list([ser_contract(c) for c in page], limit, offset, total)


@bp.get("/rideshare/contracts/<cid>")
@require_roles("ContractManager", "Customer", "MissionOps")
def get_contract(cid):
    c = _load_contract_scoped(cid)
    if c is None:
        raise not_found(ERR_CONTRACT_NOT_FOUND, f"contract {cid} not found")
    return success(ser_contract(c))


@bp.post("/rideshare/contracts/<cid>/sign")
@require_roles("Customer")
def sign_contract(cid):
    c = _load_contract_scoped(cid)
    if c is None:
        raise not_found(ERR_CONTRACT_NOT_FOUND, f"contract {cid} not found")
    if c["status"] != "DRAFT":
        raise conflict(
            ERR_INVALID_STATE, f"contract is {c['status']}, expected DRAFT"
        )
    payloads = [p for p in db["payloads"].values() if p["contract_id"] == c["id"]]
    c["quoted_price_cents"] = quote_price_cents(c["pricing_mode"], payloads)
    c["status"] = "SIGNED"
    bump(c)
    return success(ser_contract(c))


@bp.post("/rideshare/contracts/<cid>/rebook")
@require_roles("Customer", "ContractManager")
def rebook_contract(cid):
    c = _load_contract_scoped(cid)
    body = body_json()
    to_mission_id = as_str(req_field(body, "to_mission_id"), "to_mission_id")
    expected_version = as_int(
        req_field(body, "expected_contract_version"), "expected_contract_version"
    )
    if c is None:
        raise not_found(ERR_CONTRACT_NOT_FOUND, f"contract {cid} not found")
    mission = db["missions"].get(to_mission_id)
    if mission is None:
        raise not_found(ERR_MISSION_NOT_FOUND, f"mission {to_mission_id} not found")
    if expected_version != c["version"]:
        raise stale(
            ERR_STALE_CONTRACT_VERSION,
            f"expected_contract_version {expected_version} != current {c['version']}",
        )
    if c["status"] != "SIGNED":
        raise conflict(
            ERR_REBOOKING_NOT_ELIGIBLE,
            f"contract is {c['status']}, expected SIGNED",
        )
    if mission["status"] != "MANIFEST_OPEN":
        raise conflict(
            ERR_REBOOKING_NOT_ELIGIBLE,
            f"target mission is {mission['status']}, expected MANIFEST_OPEN",
        )
    if not (
        c["window_open_utc"] <= mission["window_open_utc"]
        and c["window_close_utc"] >= mission["window_close_utc"]
    ):
        raise unprocessable(
            ERR_WINDOW_INCOMPATIBLE,
            "contract window does not cover the target mission window",
        )

    if c["rebook_eligible"]:
        fee = 0
        c["rebook_eligible"] = False
    elif c["rebookings_remaining"] > 0:
        fee = 0
        c["rebookings_remaining"] -= 1
    else:
        gap_seconds = (mission["window_open_utc"] - now()).total_seconds()
        days = math.floor(gap_seconds / 86400)
        if days >= FAR_MIN_DAYS:
            pct = FEE_PCT_FAR
        elif days >= MID_MIN_DAYS:
            pct = FEE_PCT_MID
        else:
            pct = FEE_PCT_NEAR
        fee = round_half_up_int(Decimal(c["quoted_price_cents"]) * pct)
    c["total_rebooking_fees_cents"] += fee
    c["target_mission_id"] = to_mission_id
    bump(c)
    return success(ser_contract(c))


@bp.get("/rideshare/contracts/<cid>/payloads")
@require_roles("ContractManager", "Customer", "MissionOps", "IntegrationEngineer")
def list_contract_payloads(cid):
    c = _load_contract_scoped(cid)
    if c is None:
        raise not_found(ERR_CONTRACT_NOT_FOUND, f"contract {cid} not found")
    status = opt_enum_filter(request.args, "status", PAYLOAD_STATUSES)
    limit, offset = parse_pagination(request.args)
    rows = [p for p in db["payloads"].values() if p["contract_id"] == c["id"]]
    if status is not None:
        rows = [p for p in rows if p["status"] == status]
    # declared order in the create payloads array == creation order
    rows.sort(key=lambda p: (p["created_at"], p["_seq"]))
    page, total = paginate(rows, limit, offset)
    return success_list([ser_payload(p) for p in page], limit, offset, total)
