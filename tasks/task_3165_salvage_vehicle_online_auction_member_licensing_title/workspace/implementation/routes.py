"""All API routes. Mounted under /salvage-auction.

Validation priority (§2.7):
  1. auth (handled in app.py)
  2. role permission / entity-backed ownership (handled in app.py + handler)
  3. path-identifier existence, left-to-right
  4. body-referenced existence
  5. request shape (ERR_INVALID_REQUEST)
  6. uniqueness
  7. state preconditions
  8. license/title gating (bids/close)
  9. bid-amount rules
  10. clock-based gates
  11. export compliance
  12. slot capacity
  13. payment exactness
  14. reserve / no-bid handling
"""
from datetime import datetime, timedelta, timezone
from decimal import Decimal

from db import stores, get_clock, set_clock
from helpers import (
    ApiError, bad_request, err_forbidden, new_entity, new_id, touch, now_ts,
    get_body, require_fields, is_string, is_int, check_date_str,
    parse_iso8601_utc, get_entity, paginate, sort_created, round_half_up_int,
    current_date, clock_ts, _ts,
)

# --- Role names ---
ROLE_PLATFORM_ADMIN = "PlatformAdmin"
ROLE_SELLER_AGENT = "SellerAgent"
ROLE_YARD_OPERATOR = "YardOperator"
ROLE_AUCTIONEER = "Auctioneer"
ROLE_BUYER = "Buyer"
ROLE_TITLE_CLERK = "TitleClerk"

ALL_ROLES = [
    ROLE_PLATFORM_ADMIN, ROLE_SELLER_AGENT, ROLE_YARD_OPERATOR,
    ROLE_AUCTIONEER, ROLE_BUYER, ROLE_TITLE_CLERK,
]

# --- Enum sets (declared sets from §1.1) ---
SELLER_TYPES = {"INSURER", "DEALER", "FLEET"}
FEE_SCHEDULES = {"STANDARD", "VOLUME"}
MEMBER_TIERS = {"BASIC", "PREMIER", "BUSINESS"}
LICENSE_TYPES = {"DEALER", "DISMANTLER", "SALVAGE_BROKER"}
LOT_TYPES = {"STANDARD", "DEALER_ONLY", "DISMANTLER_ONLY", "EXPORT_ONLY"}
SALE_TYPES = {"PURE", "MINIMUM_BID", "ON_APPROVAL"}
PRIMARY_DAMAGES = {"FRONT", "REAR", "SIDE", "TOP", "MECHANICAL", "FLOOD", "FIRE"}
RUN_AND_DRIVE_STATUSES = {"RUN_AND_DRIVE", "STARTS", "STATIONARY"}
TITLE_TYPES = {"CLEAN", "SALVAGE", "REBUILT", "NON_REPAIRABLE", "PARTS_ONLY",
               "CERTIFICATE_OF_DESTRUCTION"}
EXPORT_DOC_TYPES = {"BILL_OF_LADING", "EXPORT_DECLARATION", "CUSTOMS_MANIFEST"}

# --- Calculation constants ---
MIN_INCREMENT_CENTS = 2500
TITLE_SLA_DAYS = 30
TITLE_LATE_PENALTY_CENTS = 15000
SELLER_FREE_STORAGE_DAYS = 7
TIER1_CAP = 500000
TIER2_CAP = 2000000
TIER1_RATE = Decimal("0.12")
TIER2_RATE = Decimal("0.09")
TIER3_RATE = Decimal("0.06")
STANDARD_RATE = Decimal("0.10")
STANDARD_FLOOR = 2500
VOLUME_RATE = Decimal("0.075")
VOLUME_FLOOR = 1500
TITLE_FEE_CENTS = 5000
GATE_PASS_EXPIRY_HOURS = 72
MAX_SLOT_DURATION_HOURS = 8
SLOT_CAPACITY = 4  # "fewer than 4 other passes" — the new one would make 5


# =====================================================================
# Utility: filters and lookups
# =====================================================================

def list_filter(items, filters):
    """filters: list of (query_arg_name, entity_field, parser-or-None)."""
    from flask import request
    out = list(items)
    for arg, field, parser in filters:
        raw = request.args.get(arg)
        if raw is None:
            continue
        if parser:
            try:
                raw = parser(raw)
            except (ValueError, TypeError):
                raise bad_request("%s has invalid value" % arg)
        out = [e for e in out if e.get(field) == raw]
    return out


def auction_items_for_auction(auction_id):
    return [it for it in stores["auction_items"].values() if it["auction_id"] == auction_id]


def auction_items_for_vehicle(vehicle_id):
    return [it for it in stores["auction_items"].values() if it["vehicle_id"] == vehicle_id]


def active_item_for_vehicle(vehicle_id):
    for it in auction_items_for_vehicle(vehicle_id):
        if it["status"] in ("QUEUED", "LIVE"):
            return it
    return None


def title_for_vehicle(vehicle_id):
    for t in stores["titles"].values():
        if t["vehicle_id"] == vehicle_id:
            return t
    return None


def sale_for_item(item_id):
    for s in stores["sales"].values():
        if s["auction_item_id"] == item_id:
            return s
    return None


def gate_passes_for_sale(sale_id):
    return [gp for gp in stores["gate_passes"].values() if gp["sale_id"] == sale_id]


def active_gate_pass_for_sale(sale_id):
    for gp in gate_passes_for_sale(sale_id):
        if gp["status"] in ("ISSUED", "CHECKED_IN"):
            return gp
    return None


def settlement_for_sale(sale_id):
    for st in stores["settlements"].values():
        if st["sale_id"] == sale_id:
            return st
    return None


def export_docs_for_sale(sale_id):
    return [d for d in stores["export_documents"].values() if d["sale_id"] == sale_id]


def winning_bid_for_item(item_id):
    for b in stores["bids"].values():
        if b["auction_item_id"] == item_id and b.get("is_winning"):
            return b
    return None


def bids_for_item(item_id):
    return [b for b in stores["bids"].values() if b["auction_item_id"] == item_id]


# =====================================================================
# Clock
# =====================================================================

def clock_set(user):
    body = get_body()
    require_fields(body, ["to_iso8601"])
    dt = parse_iso8601_utc(body["to_iso8601"])
    set_clock(dt)
    # Render the new clock value with three fractional digits
    ms = dt.microsecond // 1000
    stamp = dt.strftime("%Y-%m-%dT%H:%M:%S") + ".%03dZ" % ms
    return {"current_utc": stamp}, 200


# =====================================================================
# Yard
# =====================================================================

def create_yard(user):
    body = get_body()
    require_fields(body, ["name", "state_code", "daily_storage_rate_cents", "free_storage_days"])
    if not is_string(body["name"]) or not body["name"]:
        raise bad_request("name must be a non-empty string")
    if not is_string(body["state_code"]) or len(body["state_code"]) != 2:
        raise bad_request("state_code must be a two-letter string")
    if not is_int(body["daily_storage_rate_cents"]) or body["daily_storage_rate_cents"] <= 0:
        raise bad_request("daily_storage_rate_cents must be > 0")
    if not is_int(body["free_storage_days"]) or body["free_storage_days"] < 0:
        raise bad_request("free_storage_days must be >= 0")
    y = new_entity({
        "name": body["name"],
        "state_code": body["state_code"],
        "daily_storage_rate_cents": body["daily_storage_rate_cents"],
        "free_storage_days": body["free_storage_days"],
        "status": "ACTIVE",
    })
    stores["yards"][y["id"]] = y
    return y, 201


def list_yards(user):
    items = list_filter(stores["yards"].values(), [("state_code", "state_code", None)])
    items = sort_created(items)
    page, meta = paginate(items)
    return page, 200, meta


def get_yard(user, id):
    y = get_entity("yards", id, "ERR_YARD_NOT_FOUND", "Yard")
    return y, 200


# =====================================================================
# Seller
# =====================================================================

def create_seller(user):
    body = get_body()
    require_fields(body, ["name", "seller_type", "fee_schedule"])
    if not is_string(body["name"]) or not body["name"]:
        raise bad_request("name must be a non-empty string")
    if body["seller_type"] not in SELLER_TYPES:
        raise bad_request("seller_type must be INSURER | DEALER | FLEET")
    if body["fee_schedule"] not in FEE_SCHEDULES:
        raise bad_request("fee_schedule must be STANDARD | VOLUME")
    s = new_entity({
        "name": body["name"],
        "seller_type": body["seller_type"],
        "fee_schedule": body["fee_schedule"],
        "status": "ACTIVE",
    })
    stores["sellers"][s["id"]] = s
    return s, 201


def list_sellers(user):
    items = sort_created(list(stores["sellers"].values()))
    page, meta = paginate(items)
    return page, 200, meta


def get_seller(user, id):
    s = get_entity("sellers", id, "ERR_SELLER_NOT_FOUND", "Seller")
    return s, 200


# =====================================================================
# Member
# =====================================================================

def create_member(user):
    body = get_body()
    require_fields(body, ["email", "full_name", "home_state", "tier"])
    if not is_string(body["email"]) or not body["email"]:
        raise bad_request("email must be a non-empty string")
    if not is_string(body["full_name"]) or not body["full_name"]:
        raise bad_request("full_name must be a non-empty string")
    if not is_string(body["home_state"]) or len(body["home_state"]) != 2:
        raise bad_request("home_state must be a two-letter string")
    if body["tier"] not in MEMBER_TIERS:
        raise bad_request("tier must be BASIC | PREMIER | BUSINESS")
    cc = body.get("country_code", "US")
    if not is_string(cc) or not cc:
        raise bad_request("country_code must be a non-empty string")
    # uniqueness
    for m in stores["members"].values():
        if m["email"] == body["email"]:
            raise ApiError("ERR_EMAIL_TAKEN", 409, "member email already registered")
    m = new_entity({
        "email": body["email"],
        "full_name": body["full_name"],
        "home_state": body["home_state"],
        "tier": body["tier"],
        "country_code": cc,
        "status": "ACTIVE",
    })
    stores["members"][m["id"]] = m
    return m, 201


def list_members(user):
    items = list_filter(stores["members"].values(), [
        ("tier", "tier", None), ("home_state", "home_state", None),
    ])
    items = sort_created(items)
    page, meta = paginate(items)
    return page, 200, meta


def get_member(user, id):
    m = get_entity("members", id, "ERR_MEMBER_NOT_FOUND", "Member")
    return m, 200


# =====================================================================
# License
# =====================================================================

def create_license(user, id):
    m = get_entity("members", id, "ERR_MEMBER_NOT_FOUND", "Member")
    body = get_body()
    require_fields(body, ["state_code", "license_type", "expires_on"])
    if not is_string(body["state_code"]) or len(body["state_code"]) != 2:
        raise bad_request("state_code must be a two-letter string")
    if body["license_type"] not in LICENSE_TYPES:
        raise bad_request("license_type must be DEALER | DISMANTLER | SALVAGE_BROKER")
    check_date_str(body["expires_on"], "expires_on")
    lic = new_entity({
        "member_id": m["id"],
        "state_code": body["state_code"],
        "license_type": body["license_type"],
        "expires_on": body["expires_on"],
        "status": "ACTIVE",
    })
    stores["licenses"][lic["id"]] = lic
    return lic, 201


def list_member_licenses(user, id):
    m = get_entity("members", id, "ERR_MEMBER_NOT_FOUND", "Member")
    items = [l for l in stores["licenses"].values() if l["member_id"] == m["id"]]
    items = sort_created(items)
    page, meta = paginate(items)
    return page, 200, meta


def get_license(user, id):
    lic = get_entity("licenses", id, "ERR_LICENSE_NOT_FOUND", "License")
    return lic, 200


# =====================================================================
# Vehicle
# =====================================================================

def create_vehicle(user):
    body = get_body()
    # Path/role: SellerAgent only; X-User-ID is the seller id
    require_fields(body, ["seller_id", "yard_id", "vin", "year", "make", "model",
                          "lot_type", "reserve_price_cents", "sale_type", "odometer_reading"])
    # Body-referenced existence (priority 4)
    seller = stores["sellers"].get(body["seller_id"])
    if seller is None:
        raise ApiError("ERR_SELLER_NOT_FOUND", 404, "seller id does not exist")
    yard = stores["yards"].get(body["yard_id"])
    if yard is None:
        raise ApiError("ERR_YARD_NOT_FOUND", 404, "yard id does not exist")
    # Entity-backed ownership: SellerAgent X-User-ID must equal seller_id
    if user["role"] == ROLE_SELLER_AGENT and user["user_id"] != seller["id"]:
        raise err_forbidden("SellerAgent does not own this seller")
    # Shape (priority 5)
    if not is_string(body["vin"]) or len(body["vin"]) != 17:
        raise bad_request("vin must be a 17-character string")
    if not is_int(body["year"]):
        raise bad_request("year must be an integer")
    if not is_string(body["make"]) or not body["make"]:
        raise bad_request("make must be a non-empty string")
    if not is_string(body["model"]) or not body["model"]:
        raise bad_request("model must be a non-empty string")
    if body["lot_type"] not in LOT_TYPES:
        raise bad_request("lot_type must be STANDARD | DEALER_ONLY | DISMANTLER_ONLY | EXPORT_ONLY")
    if not is_int(body["reserve_price_cents"]) or body["reserve_price_cents"] < 0:
        raise bad_request("reserve_price_cents must be >= 0")
    if body["sale_type"] not in SALE_TYPES:
        raise bad_request("sale_type must be PURE | MINIMUM_BID | ON_APPROVAL")
    if not is_int(body["odometer_reading"]) or body["odometer_reading"] < 0:
        raise bad_request("odometer_reading must be >= 0")
    dc = body.get("damage_codes", [])
    if not isinstance(dc, list) or any(not is_string(x) for x in dc):
        raise bad_request("damage_codes must be a list of strings")
    # Uniqueness: VIN unique system-wide
    for v in stores["vehicles"].values():
        if v["vin"] == body["vin"]:
            raise ApiError("ERR_VIN_DUPLICATE", 409, "VIN already assigned to another vehicle")
    # State gates: seller/yard status
    if seller["status"] != "ACTIVE":
        raise ApiError("ERR_SELLER_SUSPENDED", 409, "SUSPENDED seller cannot assign new vehicles")
    if yard["status"] != "ACTIVE":
        raise ApiError("ERR_YARD_CLOSED", 409, "CLOSED yard cannot receive new assignments")
    v = new_entity({
        "seller_id": seller["id"],
        "yard_id": yard["id"],
        "vin": body["vin"],
        "year": body["year"],
        "make": body["make"],
        "model": body["model"],
        "lot_type": body["lot_type"],
        "reserve_price_cents": body["reserve_price_cents"],
        "sale_type": body["sale_type"],
        "damage_codes": list(dc),
        "primary_damage": "NONE",
        "run_and_drive_status": "UNKNOWN",
        "image_ids": [],
        "image_count": 0,
        "odometer_reading": body["odometer_reading"],
        "title_brand": "NONE",
        "assigned_at": clock_ts(),
        "received_at": None,
        "status": "ASSIGNED",
    })
    stores["vehicles"][v["id"]] = v
    return v, 201


def list_vehicles(user):
    items = list_filter(stores["vehicles"].values(), [
        ("status", "status", None), ("yard_id", "yard_id", None),
        ("seller_id", "seller_id", None), ("lot_type", "lot_type", None),
    ])
    items = sort_created(items)
    page, meta = paginate(items)
    return page, 200, meta


def get_vehicle(user, id):
    v = get_entity("vehicles", id, "ERR_VEHICLE_NOT_FOUND", "Vehicle")
    return v, 200


def vehicle_add_image(user, id):
    v = get_entity("vehicles", id, "ERR_VEHICLE_NOT_FOUND", "Vehicle")
    body = get_body()
    require_fields(body, ["image_url"])
    if not is_string(body["image_url"]) or not body["image_url"]:
        raise bad_request("image_url must be a non-empty string")
    # state: must be ASSIGNED or AWAITING_CONDITION (intake); not cancellable after
    if v["status"] not in ("ASSIGNED", "AWAITING_CONDITION"):
        raise ApiError("ERR_VEHICLE_INVALID_STATE", 409,
                       "vehicle not in a state that allows image upload")
    image_id = new_id()
    v["image_ids"].append(image_id)
    v["image_count"] += 1
    if v["status"] == "ASSIGNED" and v["image_count"] >= 5:
        v["status"] = "AWAITING_CONDITION"
    touch(v)
    return {"image_id": image_id, "image_count": v["image_count"]}, 201


def vehicle_condition(user, id):
    v = get_entity("vehicles", id, "ERR_VEHICLE_NOT_FOUND", "Vehicle")
    body = get_body()
    require_fields(body, ["primary_damage", "run_and_drive_status"])
    if body["primary_damage"] not in PRIMARY_DAMAGES:
        raise bad_request("primary_damage must be one of FRONT|REAR|SIDE|TOP|MECHANICAL|FLOOD|FIRE")
    if body["run_and_drive_status"] not in RUN_AND_DRIVE_STATUSES:
        raise bad_request("run_and_drive_status must be RUN_AND_DRIVE | STARTS | STATIONARY")
    if "damage_codes" in body and body["damage_codes"] is not None:
        if not isinstance(body["damage_codes"], list) or any(not is_string(x) for x in body["damage_codes"]):
            raise bad_request("damage_codes must be a list of strings")
    if v["status"] not in ("ASSIGNED", "AWAITING_CONDITION"):
        raise ApiError("ERR_VEHICLE_INVALID_STATE", 409,
                       "condition report requires ASSIGNED or AWAITING_CONDITION")
    v["primary_damage"] = body["primary_damage"]
    v["run_and_drive_status"] = body["run_and_drive_status"]
    dc = body.get("damage_codes")
    if isinstance(dc, list) and len(dc) > 0:
        v["damage_codes"] = list(dc)
    touch(v)
    return v, 200


def vehicle_mark_ready(user, id):
    v = get_entity("vehicles", id, "ERR_VEHICLE_NOT_FOUND", "Vehicle")
    body = get_body()
    require_fields(body, ["expected_vehicle_version"])
    if not is_int(body["expected_vehicle_version"]):
        raise bad_request("expected_vehicle_version must be an integer")
    # Image-readiness gate precedes the status gate: the resource named by the
    # endpoint (vehicle readiness) is not ready while image_count < 5 (PRD 3.1).
    if v["image_count"] < 5:
        raise ApiError("ERR_VEHICLE_NOT_IMAGE_READY", 409,
                       "mark-ready with image_count < 5")
    if v["status"] != "AWAITING_CONDITION":
        raise ApiError("ERR_VEHICLE_INVALID_STATE", 409,
                       "mark-ready requires AWAITING_CONDITION")
    if not v["damage_codes"] or v["primary_damage"] == "NONE" or v["run_and_drive_status"] == "UNKNOWN":
        raise ApiError("ERR_VEHICLE_INCOMPLETE_CONDITION", 409,
                       "mark-ready without a submitted condition report or with empty damage_codes")
    t = title_for_vehicle(v["id"])
    if t is None or t["status"] != "RECEIVED":
        raise ApiError("ERR_TITLE_NOT_RECEIVED", 409,
                       "mark-ready requires a RECEIVED title record")
    # OCC
    if body["expected_vehicle_version"] != v["version"]:
        raise ApiError("ERR_STALE_VERSION", 412,
                       "expected_vehicle_version does not match Vehicle.version")
    v["status"] = "SALE_READY"
    v["received_at"] = clock_ts()
    touch(v)
    return v, 200


def vehicle_cancel(user, id):
    v = get_entity("vehicles", id, "ERR_VEHICLE_NOT_FOUND", "Vehicle")
    # Seller ownership
    if user["role"] == ROLE_SELLER_AGENT and user["user_id"] != v["seller_id"]:
        raise ApiError("ERR_SELLER_MISMATCH", 403, "SellerAgent does not own this vehicle")
    if v["status"] not in ("ASSIGNED", "AWAITING_CONDITION", "SALE_READY", "LISTED", "LIVE"):
        raise ApiError("ERR_VEHICLE_NOT_CANCELLABLE", 409,
                       "cancel requires vehicle in ASSIGNED | AWAITING_CONDITION | SALE_READY | LISTED | LIVE")
    if v["status"] in ("LISTED", "LIVE"):
        item = active_item_for_vehicle(v["id"])
        if item is not None:
            item["status"] = "CANCELLED"
            touch(item)
            if v["status"] == "LIVE":
                for b in bids_for_item(item["id"]):
                    if b.get("is_winning"):
                        b["is_winning"] = False
            _maybe_complete_auction(item["auction_id"])
    v["status"] = "CANCELLED"
    touch(v)
    return v, 200


# =====================================================================
# Title
# =====================================================================

def derive_transferability(jurisdiction_state, title_type):
    if title_type in ("CLEAN", "SALVAGE", "REBUILT"):
        return "TRANSFERABLE"
    if title_type == "PARTS_ONLY":
        return "NON_TRANSFERABLE" if jurisdiction_state in ("CA", "TX") else "EXPORT_ONLY"
    if title_type == "NON_REPAIRABLE":
        return "NON_TRANSFERABLE" if jurisdiction_state in ("FL", "MI") else "EXPORT_ONLY"
    if title_type == "CERTIFICATE_OF_DESTRUCTION":
        return "NON_TRANSFERABLE"
    return "TRANSFERABLE"


def create_title(user, id):
    v = get_entity("vehicles", id, "ERR_VEHICLE_NOT_FOUND", "Vehicle")
    body = get_body()
    require_fields(body, ["title_type"])
    if body["title_type"] not in TITLE_TYPES:
        raise bad_request("title_type must be one of CLEAN|SALVAGE|REBUILT|NON_REPAIRABLE|PARTS_ONLY|CERTIFICATE_OF_DESTRUCTION")
    # Uniqueness
    if title_for_vehicle(v["id"]) is not None:
        raise ApiError("ERR_TITLE_ALREADY_EXISTS", 409, "vehicle already has a title record")
    # State: vehicle must not be CANCELLED
    if v["status"] == "CANCELLED":
        raise ApiError("ERR_VEHICLE_INVALID_STATE", 409,
                       "title recording on a CANCELLED vehicle is rejected")
    yard = stores["yards"].get(v["yard_id"])
    jurisdiction = yard["state_code"] if yard else None
    received = clock_ts()
    # late flag: elapsed between assigned_at and received_at > TITLE_SLA_DAYS (strict)
    assigned = parse_iso8601_utc(v["assigned_at"], "assigned_at")
    received_dt = parse_iso8601_utc(received, "received_at")
    elapsed_days = (received_dt.date() - assigned.date()).days
    late = elapsed_days > TITLE_SLA_DAYS
    t = new_entity({
        "vehicle_id": v["id"],
        "jurisdiction_state": jurisdiction,
        "title_type": body["title_type"],
        "received_at": received,
        "transferability": derive_transferability(jurisdiction, body["title_type"]),
        "late": late,
        "status": "RECEIVED",
    })
    stores["titles"][t["id"]] = t
    return t, 201


def list_vehicle_titles(user, id):
    v = get_entity("vehicles", id, "ERR_VEHICLE_NOT_FOUND", "Vehicle")
    t = title_for_vehicle(v["id"])
    items = [t] if t else []
    page, meta = paginate(items)
    return page, 200, meta


def get_title(user, id):
    t = get_entity("titles", id, "ERR_TITLE_NOT_FOUND", "TitleRecord")
    return t, 200


# =====================================================================
# Auction
# =====================================================================

def create_auction(user):
    body = get_body()
    require_fields(body, ["name", "scheduled_start"])
    if not is_string(body["name"]) or not body["name"]:
        raise bad_request("name must be a non-empty string")
    parse_iso8601_utc(body["scheduled_start"], "scheduled_start")
    a = new_entity({
        "name": body["name"],
        "scheduled_start": body["scheduled_start"],
        "status": "SCHEDULED",
        "current_sequence_number": 0,
    })
    stores["auctions"][a["id"]] = a
    return a, 201


def list_auctions(user):
    items = list_filter(stores["auctions"].values(), [("status", "status", None)])
    items = sort_created(items)
    page, meta = paginate(items)
    return page, 200, meta


def get_auction(user, id):
    a = get_entity("auctions", id, "ERR_AUCTION_NOT_FOUND", "Auction")
    return a, 200


def auction_start(user, id):
    a = get_entity("auctions", id, "ERR_AUCTION_NOT_FOUND", "Auction")
    if a["status"] != "SCHEDULED":
        raise ApiError("ERR_AUCTION_NOT_SCHEDULED", 409,
                       "operation requires auction in SCHEDULED")
    sched = parse_iso8601_utc(a["scheduled_start"], "scheduled_start")
    if get_clock() < sched:
        raise ApiError("ERR_AUCTION_NOT_YET_STARTED", 409,
                       "start before scheduled_start")
    queued = [it for it in auction_items_for_auction(a["id"]) if it["status"] == "QUEUED"]
    if not queued:
        raise ApiError("ERR_AUCTION_EMPTY", 409, "start with no QUEUED items")
    # sequence: created_at ASC; tie-break Vehicle.vin ASC
    def sort_key(it):
        veh = stores["vehicles"].get(it["vehicle_id"])
        vin = veh["vin"] if veh else ""
        return (it["created_at"], vin)
    queued.sort(key=sort_key)
    for idx, it in enumerate(queued, start=1):
        it["sequence_number"] = idx
        touch(it)
    a["status"] = "LIVE"
    touch(a)
    return a, 200


def _maybe_complete_auction(auction_id):
    a = stores["auctions"].get(auction_id)
    if a is None or a["status"] != "LIVE":
        return
    items = auction_items_for_auction(auction_id)
    if all(it["status"] in ("CLOSED", "CANCELLED") for it in items):
        a["status"] = "COMPLETED"
        touch(a)


# =====================================================================
# AuctionItem
# =====================================================================

def create_auction_item(user, id):
    a = get_entity("auctions", id, "ERR_AUCTION_NOT_FOUND", "Auction")
    body = get_body()
    require_fields(body, ["vehicle_id"])
    v = stores["vehicles"].get(body["vehicle_id"])
    if v is None:
        raise ApiError("ERR_VEHICLE_NOT_FOUND", 404, "vehicle id does not exist")
    # Uniqueness
    if active_item_for_vehicle(v["id"]) is not None:
        raise ApiError("ERR_VEHICLE_ALREADY_LISTED", 409,
                       "vehicle already has a QUEUED or LIVE auction item")
    # State
    if a["status"] != "SCHEDULED":
        raise ApiError("ERR_AUCTION_NOT_SCHEDULED", 409,
                       "listing requires auction SCHEDULED")
    if v["status"] != "SALE_READY":
        raise ApiError("ERR_VEHICLE_NOT_SALE_READY", 409,
                       "listing requires vehicle in SALE_READY")
    it = new_entity({
        "auction_id": a["id"],
        "vehicle_id": v["id"],
        "sequence_number": None,
        "prelim_high_bid_cents": 0,
        "prelim_high_bidder_id": None,
        "high_bid_cents": 0,
        "high_bidder_id": None,
        "reserve_met": False,
        "status": "QUEUED",
    })
    stores["auction_items"][it["id"]] = it
    v["status"] = "LISTED"
    touch(v)
    return it, 201


def list_auction_items(user, id):
    a = get_entity("auctions", id, "ERR_AUCTION_NOT_FOUND", "Auction")
    items = list_filter(auction_items_for_auction(a["id"]), [("status", "status", None)])
    items = sort_created(items)
    page, meta = paginate(items)
    return page, 200, meta


def list_vehicle_auction_items(user, id):
    v = get_entity("vehicles", id, "ERR_VEHICLE_NOT_FOUND", "Vehicle")
    items = sort_created(auction_items_for_vehicle(v["id"]))
    page, meta = paginate(items)
    return page, 200, meta


def get_auction_item(user, id):
    it = get_entity("auction_items", id, "ERR_AUCTION_ITEM_NOT_FOUND", "AuctionItem")
    return it, 200


def open_lot(user, id, itemId):
    a = get_entity("auctions", id, "ERR_AUCTION_NOT_FOUND", "Auction")
    it = get_entity("auction_items", itemId, "ERR_AUCTION_ITEM_NOT_FOUND", "AuctionItem")
    if it["auction_id"] != a["id"]:
        raise ApiError("ERR_AUCTION_ITEM_NOT_FOUND", 404,
                       "auction item does not belong to auction")
    v = stores["vehicles"].get(it["vehicle_id"])
    if a["status"] != "LIVE":
        raise ApiError("ERR_AUCTION_NOT_LIVE", 409, "open-lot requires auction LIVE")
    if it["sequence_number"] is None or it["sequence_number"] != a["current_sequence_number"] + 1:
        raise ApiError("ERR_AUCTION_ITEM_OUT_OF_ORDER", 409,
                       "open-lot skipped the running order")
    for other in auction_items_for_auction(a["id"]):
        if other["id"] != it["id"] and other["status"] == "LIVE":
            raise ApiError("ERR_AUCTION_ITEM_ALREADY_LIVE", 409,
                           "another lot is already LIVE in this auction")
    # Prelim snapshot: max of PRELIM bids (already captured in high_bid_cents from prelim acceptance)
    prelim_bids = [b for b in bids_for_item(it["id"]) if b["bid_type"] == "PRELIM"]
    if prelim_bids:
        max_amt = max(b["amount_cents"] for b in prelim_bids)
        # pick the earliest bid with that amount (first accepted wins ties)
        prelim_sorted = sorted(prelim_bids, key=lambda b: b["created_at"])
        chosen = next(b for b in prelim_sorted if b["amount_cents"] == max_amt)
        it["prelim_high_bid_cents"] = max_amt
        it["prelim_high_bidder_id"] = chosen["member_id"]
    else:
        it["prelim_high_bid_cents"] = 0
        it["prelim_high_bidder_id"] = None
    it["high_bid_cents"] = it["prelim_high_bid_cents"]
    it["high_bidder_id"] = it["prelim_high_bidder_id"]
    it["reserve_met"] = (it["prelim_high_bid_cents"] >= v["reserve_price_cents"]) if v else False
    it["status"] = "LIVE"
    a["current_sequence_number"] = it["sequence_number"]
    if v is not None:
        v["status"] = "LIVE"
        touch(v)
    touch(it)
    touch(a)
    return it, 200


def close_lot(user, id, itemId):
    a = get_entity("auctions", id, "ERR_AUCTION_NOT_FOUND", "Auction")
    it = get_entity("auction_items", itemId, "ERR_AUCTION_ITEM_NOT_FOUND", "AuctionItem")
    if it["auction_id"] != a["id"]:
        raise ApiError("ERR_AUCTION_ITEM_NOT_FOUND", 404,
                       "auction item does not belong to auction")
    v = stores["vehicles"].get(it["vehicle_id"])
    # state precondition
    if it["status"] != "LIVE":
        raise ApiError("ERR_AUCTION_ITEM_NOT_LIVE", 409, "close-lot requires item LIVE")
    # title transferability gate (priority 8 for close)
    t = title_for_vehicle(v["id"]) if v else None
    if t is not None and t["transferability"] == "NON_TRANSFERABLE":
        raise ApiError("ERR_TITLE_NON_TRANSFERABLE", 409,
                       "close-lot blocked: title transferability NON_TRANSFERABLE")
    # no-bids / reserve (priority 14)
    if it["high_bid_cents"] <= 0:
        raise ApiError("ERR_NO_BIDS", 409, "close-lot with no bids")
    if v["sale_type"] in ("PURE", "MINIMUM_BID") and not it["reserve_met"]:
        raise ApiError("ERR_RESERVE_NOT_MET", 409,
                       "close-lot on PURE / MINIMUM_BID vehicle with reserve_met == false")

    # Common close bookkeeping
    it["status"] = "CLOSED"
    touch(it)
    win_bid = winning_bid_for_item(it["id"])

    if v["sale_type"] == "ON_APPROVAL":
        # Sale PENDING_APPROVAL; buyer fee computed; no expiry stamped yet
        sale = _create_sale(v, it, pending=True)
        v["status"] = "ON_APPROVAL_PENDING"
        touch(v)
        _maybe_complete_auction(a["id"])
        return sale, 200
    else:
        # LIVE -> SOLD
        sale = _create_sale(v, it, pending=False)
        v["status"] = "SOLD"
        # Title transfer + brand stamping + settlement
        _perform_close_side_effects(v, sale, t)
        touch(v)
        _maybe_complete_auction(a["id"])
        return sale, 200


def cancel_auction_item(user, id, itemId):
    a = get_entity("auctions", id, "ERR_AUCTION_NOT_FOUND", "Auction")
    it = get_entity("auction_items", itemId, "ERR_AUCTION_ITEM_NOT_FOUND", "AuctionItem")
    if it["auction_id"] != a["id"]:
        raise ApiError("ERR_AUCTION_ITEM_NOT_FOUND", 404,
                       "auction item does not belong to auction")
    v = stores["vehicles"].get(it["vehicle_id"])
    if it["status"] != "QUEUED":
        raise ApiError("ERR_AUCTION_ITEM_NOT_QUEUED", 409, "cancel requires item QUEUED")
    it["status"] = "CANCELLED"
    touch(it)
    if v is not None and v["status"] == "LISTED":
        v["status"] = "SALE_READY"
        touch(v)
    return it, 200


def _create_sale(v, item, pending):
    buyer_fee = compute_buyer_premium(item["high_bid_cents"])
    sale = new_entity({
        "vehicle_id": v["id"],
        "auction_item_id": item["id"],
        "winner_member_id": item["high_bidder_id"],
        "winning_bid_cents": item["high_bid_cents"],
        "buyer_fee_cents": buyer_fee,
        "gate_pass_expires_at": None,
        "status": "PENDING_APPROVAL" if pending else "AWAITING_PAYMENT",
    })
    if not pending:
        sale["gate_pass_expires_at"] = _ts(get_clock() + timedelta(hours=GATE_PASS_EXPIRY_HOURS))
    stores["sales"][sale["id"]] = sale
    return sale


def compute_buyer_premium(hammer):
    """Marginal tiered premium; per-tier round-half-up then sum."""
    B = int(hammer)
    t1_portion = min(B, TIER1_CAP)
    t2_portion = max(0, min(B, TIER2_CAP) - TIER1_CAP)
    t3_portion = max(0, B - TIER2_CAP)
    t1 = round_half_up_int(Decimal(t1_portion) * TIER1_RATE)
    t2 = round_half_up_int(Decimal(t2_portion) * TIER2_RATE)
    t3 = round_half_up_int(Decimal(t3_portion) * TIER3_RATE)
    return t1 + t2 + t3


def compute_seller_settlement(sale, v, t):
    """Compute settlement fields per the pinned waterfall (§3.6)."""
    gross = sale["winning_bid_cents"]
    seller = stores["sellers"].get(v["seller_id"])
    yard = stores["yards"].get(v["yard_id"])
    # seller fee
    if seller is not None and seller["fee_schedule"] == "VOLUME":
        fee_pct = round_half_up_int(Decimal(gross) * VOLUME_RATE)
        seller_fee = max(VOLUME_FLOOR, fee_pct) + TITLE_FEE_CENTS
    else:
        fee_pct = round_half_up_int(Decimal(gross) * STANDARD_RATE)
        seller_fee = max(STANDARD_FLOOR, fee_pct) + TITLE_FEE_CENTS
    # storage recovery (seller side)
    rate = yard["daily_storage_rate_cents"] if yard else 0
    if v.get("received_at"):
        received_dt = parse_iso8601_utc(v["received_at"], "received_at")
        sale_day = get_clock().date()
        days = (sale_day - received_dt.date()).days
        chargeable = max(0, days - SELLER_FREE_STORAGE_DAYS)
        storage_recovery = chargeable * rate
    else:
        storage_recovery = 0
    # title late penalty
    late = t["late"] if t is not None else False
    title_late_penalty = TITLE_LATE_PENALTY_CENTS if late else 0
    net = gross - seller_fee - storage_recovery - title_late_penalty
    return {
        "sale_id": sale["id"],
        "seller_id": v["seller_id"],
        "gross_proceeds_cents": gross,
        "seller_fee_cents": seller_fee,
        "storage_recovery_cents": storage_recovery,
        "title_late_penalty_cents": title_late_penalty,
        "net_proceeds_cents": net,
    }


def _perform_close_side_effects(v, sale, t):
    """Create settlement, transfer title, stamp brand."""
    settlement = new_entity(compute_seller_settlement(sale, v, t))
    settlement["status"] = "DRAFT"
    stores["settlements"][settlement["id"]] = settlement
    # Title transfer + REBUILT stamping
    if t is not None:
        t["status"] = "TRANSFERRED"
        touch(t)
        if t["title_type"] in ("NON_REPAIRABLE", "PARTS_ONLY") and \
           t["jurisdiction_state"] in ("FL", "MI"):
            v["title_brand"] = "REBUILT"


# =====================================================================
# Bid
# =====================================================================

def effective_lot_coverage(member, yard_state):
    """Set of lot_types the member may bid on, per §3.7."""
    covered = {"STANDARD"}
    today = current_date()
    for lic in stores["licenses"].values():
        if lic["member_id"] != member["id"]:
            continue
        if lic["status"] != "ACTIVE":
            continue
        if lic["state_code"] != yard_state:
            continue
        try:
            exp = datetime.fromisoformat(lic["expires_on"]).date()
        except Exception:
            continue
        if exp < today:
            continue
        if lic["license_type"] == "DEALER":
            covered.add("DEALER_ONLY")
        elif lic["license_type"] == "DISMANTLER":
            covered.add("DISMANTLER_ONLY")
        elif lic["license_type"] == "SALVAGE_BROKER":
            covered.add("DEALER_ONLY")
            covered.add("DISMANTLER_ONLY")
    return covered


def place_bid(user):
    body = get_body()
    require_fields(body, ["auction_item_id", "amount_cents"])
    item = stores["auction_items"].get(body["auction_item_id"])
    if item is None:
        raise ApiError("ERR_AUCTION_ITEM_NOT_FOUND", 404, "auction item id does not exist")
    # Shape
    if not is_int(body["amount_cents"]) or body["amount_cents"] <= 0:
        raise bad_request("amount_cents must be > 0")
    # Buyer identity: X-User-ID is member id
    member = stores["members"].get(user["user_id"])
    if member is None:
        raise ApiError("ERR_MEMBER_NOT_FOUND", 404, "member id does not exist")
    v = stores["vehicles"].get(item["vehicle_id"])
    yard = stores["yards"].get(v["yard_id"]) if v else None
    # State: item must be QUEUED or LIVE
    if item["status"] not in ("QUEUED", "LIVE"):
        raise ApiError("ERR_AUCTION_ITEM_NOT_LIVE", 409,
                       "bid requires item QUEUED or LIVE")
    # License eligibility (priority 8) — before amount rules
    if member["status"] != "ACTIVE":
        raise ApiError("ERR_MEMBER_SUSPENDED", 403, "SUSPENDED member cannot bid")
    t = title_for_vehicle(v["id"]) if v else None
    # EXPORT_ONLY title blocks US winners
    if t is not None and t["transferability"] == "EXPORT_ONLY" and member["country_code"] == "US":
        raise ApiError("ERR_TITLE_EXPORT_ONLY", 403,
                       "bid by US member on EXPORT_ONLY title")
    # lot_type gating
    if v["lot_type"] == "EXPORT_ONLY":
        if member["country_code"] == "US":
            raise ApiError("ERR_LICENSE_REQUIRED", 403,
                           "EXPORT_ONLY lot requires non-US member")
    else:
        covered = effective_lot_coverage(member, yard["state_code"] if yard else None)
        if v["lot_type"] not in covered:
            raise ApiError("ERR_LICENSE_REQUIRED", 403,
                           "vehicle lot_type not covered by member's effective tier")
    # Amount rules (priority 9)
    bid_type = "PRELIM" if item["status"] == "QUEUED" else "LIVE"
    if item["high_bidder_id"] == member["id"] and item["high_bid_cents"] > 0:
        raise ApiError("ERR_BID_SELF_OUTBID", 422,
                       "member is already the high bidder on this item")
    if bid_type == "LIVE" and body["amount_cents"] < item["high_bid_cents"] + MIN_INCREMENT_CENTS:
        raise ApiError("ERR_BID_INCREMENT_TOO_SMALL", 422,
                       "live bid < high_bid_cents + 2500")
    # Anti-snipe / outbid cascade: flip previous winner
    prev_win = winning_bid_for_item(item["id"])
    if prev_win is not None:
        prev_win["is_winning"] = False
    ts = clock_ts()
    bid = {
        "id": new_id(),
        "created_at": ts,
        "auction_item_id": item["id"],
        "member_id": member["id"],
        "amount_cents": body["amount_cents"],
        "bid_type": bid_type,
        "is_winning": True,
        "placed_at": ts,
    }
    stores["bids"][bid["id"]] = bid
    item["high_bid_cents"] = body["amount_cents"]
    item["high_bidder_id"] = member["id"]
    if v is not None:
        item["reserve_met"] = item["high_bid_cents"] >= v["reserve_price_cents"]
    touch(item)
    return bid, 201


def list_bids(user):
    items = list_filter(stores["bids"].values(), [
        ("auction_item_id", "auction_item_id", None),
        ("member_id", "member_id", None),
    ])
    items = sort_created(items)
    page, meta = paginate(items)
    return page, 200, meta


def get_bid(user, id):
    b = stores["bids"].get(id)
    if b is None:
        raise ApiError("ERR_BID_NOT_FOUND", 404, "bid id does not exist")
    return b, 200


# =====================================================================
# Sale
# =====================================================================

def list_sales(user):
    items = list_filter(stores["sales"].values(), [
        ("status", "status", None),
        ("winner_member_id", "winner_member_id", None),
        ("vehicle_id", "vehicle_id", None),
        ("auction_item_id", "auction_item_id", None),
    ])
    items = sort_created(items)
    page, meta = paginate(items)
    return page, 200, meta


def get_sale(user, id):
    s = get_entity("sales", id, "ERR_SALE_NOT_FOUND", "Sale")
    return s, 200


def _seller_of_sale(sale):
    v = stores["vehicles"].get(sale["vehicle_id"])
    return v["seller_id"] if v else None


def sale_approve(user, id):
    s = get_entity("sales", id, "ERR_SALE_NOT_FOUND", "Sale")
    # ownership (priority 2)
    if user["role"] == ROLE_SELLER_AGENT and user["user_id"] != _seller_of_sale(s):
        raise ApiError("ERR_SELLER_MISMATCH", 403,
                       "SellerAgent does not own the seller of this sale")
    if s["status"] != "PENDING_APPROVAL":
        raise ApiError("ERR_SALE_NOT_PENDING_APPROVAL", 409,
                       "approve requires sale PENDING_APPROVAL")
    v = stores["vehicles"].get(s["vehicle_id"])
    if v is None or v["status"] != "ON_APPROVAL_PENDING":
        raise ApiError("ERR_VEHICLE_INVALID_STATE", 409,
                       "vehicle must be ON_APPROVAL_PENDING")
    s["status"] = "AWAITING_PAYMENT"
    s["gate_pass_expires_at"] = _ts(get_clock() + timedelta(hours=GATE_PASS_EXPIRY_HOURS))
    touch(s)
    v["status"] = "SOLD"
    t = title_for_vehicle(v["id"])
    _perform_close_side_effects(v, s, t)
    touch(v)
    return s, 200


def sale_reject(user, id):
    s = get_entity("sales", id, "ERR_SALE_NOT_FOUND", "Sale")
    if user["role"] == ROLE_SELLER_AGENT and user["user_id"] != _seller_of_sale(s):
        raise ApiError("ERR_SELLER_MISMATCH", 403,
                       "SellerAgent does not own the seller of this sale")
    if s["status"] != "PENDING_APPROVAL":
        raise ApiError("ERR_SALE_NOT_PENDING_APPROVAL", 409,
                       "reject-offer requires sale PENDING_APPROVAL")
    s["status"] = "CANCELLED"
    touch(s)
    # release winning bid
    wb = winning_bid_for_item(s["auction_item_id"])
    if wb is not None:
        wb["is_winning"] = False
    v = stores["vehicles"].get(s["vehicle_id"])
    if v is not None:
        v["status"] = "SALE_READY"
        touch(v)
    return s, 200


def sale_cancel(user, id):
    s = get_entity("sales", id, "ERR_SALE_NOT_FOUND", "Sale")
    if user["role"] == ROLE_SELLER_AGENT and user["user_id"] != _seller_of_sale(s):
        raise ApiError("ERR_SELLER_MISMATCH", 403,
                       "SellerAgent does not own the seller of this sale")
    if s["status"] not in ("PENDING_APPROVAL", "AWAITING_PAYMENT"):
        raise ApiError("ERR_SALE_NOT_CANCELLABLE", 409,
                       "sale cancel requires PENDING_APPROVAL or AWAITING_PAYMENT")
    s["status"] = "CANCELLED"
    touch(s)
    # Settlement zeroed, remains DRAFT
    st = settlement_for_sale(s["id"])
    if st is not None:
        st["gross_proceeds_cents"] = 0
        st["seller_fee_cents"] = 0
        st["storage_recovery_cents"] = 0
        st["title_late_penalty_cents"] = 0
        st["net_proceeds_cents"] = 0
        touch(st)
    # Title rolled back
    t = title_for_vehicle(s["vehicle_id"])
    v = stores["vehicles"].get(s["vehicle_id"])
    if t is not None and t["status"] == "TRANSFERRED":
        t["status"] = "RECEIVED"
        touch(t)
    if v is not None:
        # title_brand restored to prior value (NONE in practice — brand set only on close)
        v["title_brand"] = "NONE"
        v["status"] = "SALE_READY"
        touch(v)
    wb = winning_bid_for_item(s["auction_item_id"])
    if wb is not None:
        wb["is_winning"] = False
    return s, 200


def sale_pay(user, id):
    s = get_entity("sales", id, "ERR_SALE_NOT_FOUND", "Sale")
    body = get_body()
    require_fields(body, ["amount_cents"])
    if not is_int(body["amount_cents"]) or body["amount_cents"] <= 0:
        raise bad_request("amount_cents must be > 0")
    # Buyer ownership: X-User-ID == winner_member_id
    if user["role"] == ROLE_BUYER and user["user_id"] != s["winner_member_id"]:
        raise err_forbidden("Buyer acting on own Sale only")
    if s["status"] != "AWAITING_PAYMENT":
        raise ApiError("ERR_SALE_NOT_AWAITING_PAYMENT", 409,
                       "payment requires sale AWAITING_PAYMENT")
    # Outstanding winner storage: accrued on the sale's gate pass so far
    gp = active_gate_pass_for_sale(s["id"])
    accrued = gp["storage_fee_cents"] if gp is not None else 0
    expected = s["winning_bid_cents"] + s["buyer_fee_cents"] + accrued
    if body["amount_cents"] != expected:
        raise ApiError("ERR_PAYMENT_AMOUNT_MISMATCH", 422,
                       "payment != winning_bid_cents + buyer_fee_cents + outstanding winner storage")
    s["status"] = "PAID"
    touch(s)
    st = settlement_for_sale(s["id"])
    if st is not None:
        st["status"] = "FINALIZED"
        touch(st)
    v = stores["vehicles"].get(s["vehicle_id"])
    if v is not None:
        v["status"] = "RELEASED"
        touch(v)
    return s, 201


# =====================================================================
# GatePass
# =====================================================================

def _slot_overlap(a_start, a_end, b_start, b_end):
    """Half-open [start, end) overlap; touching boundaries do NOT overlap."""
    return a_start < b_end and b_start < a_end


def _slot_hour_window(dt):
    """1-hour window containing dt: [floor_hour, floor_hour+1h)."""
    base = dt.replace(minute=0, second=0, microsecond=0)
    return base, base + timedelta(hours=1)


def _check_slot_capacity(yard_id, slot_start_dt, slot_end_dt, exclude_pass_id=None):
    """Count other ISSUED/CHECKED_IN passes at this yard whose 1-hour window
    (containing slot_start) intersects the new slot (half-open)."""
    new_window_start, new_window_end = _slot_hour_window(slot_start_dt)
    count = 0
    for gp in stores["gate_passes"].values():
        if gp["id"] == exclude_pass_id:
            continue
        if gp["status"] not in ("ISSUED", "CHECKED_IN"):
            continue
        sale = stores["sales"].get(gp["sale_id"])
        if sale is None:
            continue
        veh = stores["vehicles"].get(sale["vehicle_id"])
        if veh is None or veh["yard_id"] != yard_id:
            continue
        other_start = parse_iso8601_utc(gp["slot_start"], "slot_start")
        other_end = parse_iso8601_utc(gp["slot_end"], "slot_end")
        # The other's 1-hour window containing its slot_start
        ows, owe = _slot_hour_window(other_start)
        # Must share the same 1-hour window AND have overlapping slots
        if not _slot_overlap(new_window_start, new_window_end, ows, owe):
            continue
        if not _slot_overlap(slot_start_dt, slot_end_dt, other_start, other_end):
            continue
        count += 1
    return count


def create_gate_pass(user, id):
    s = get_entity("sales", id, "ERR_SALE_NOT_FOUND", "Sale")
    # Buyer ownership on own sale only (YardOperator exempt)
    if user["role"] == ROLE_BUYER and user["user_id"] != s["winner_member_id"]:
        raise err_forbidden("Buyer may book only on own sale")
    body = get_body()
    require_fields(body, ["slot_start", "slot_end"])
    ss = parse_iso8601_utc(body["slot_start"], "slot_start")
    se = parse_iso8601_utc(body["slot_end"], "slot_end")
    # Shape: end > start and duration <= 8h
    if se <= ss:
        raise ApiError("ERR_SLOT_WINDOW_INVALID", 400,
                       "slot_end must be strictly after slot_start")
    if (se - ss) > timedelta(hours=MAX_SLOT_DURATION_HOURS):
        raise ApiError("ERR_SLOT_WINDOW_INVALID", 400,
                       "slot duration must not exceed 8 hours")
    # State: sale PAID
    if s["status"] != "PAID":
        raise ApiError("ERR_SALE_NOT_PAID", 409, "gate pass issuance requires sale PAID")
    # Uniqueness: one active pass per sale
    if active_gate_pass_for_sale(s["id"]) is not None:
        raise ApiError("ERR_GATE_PASS_ALREADY_ACTIVE", 409,
                       "sale already has an ISSUED or CHECKED_IN gate pass")
    # Capacity (creation-time overlap check)
    v = stores["vehicles"].get(s["vehicle_id"])
    if v is not None:
        existing = _check_slot_capacity(v["yard_id"], ss, se)
        if existing >= SLOT_CAPACITY:
            raise ApiError("ERR_SLOT_CAPACITY_EXCEEDED", 409,
                           "slot would exceed yard capacity")
    gp = new_entity({
        "sale_id": s["id"],
        "slot_start": body["slot_start"],
        "slot_end": body["slot_end"],
        "status": "ISSUED",
        "storage_fee_cents": 0,
    })
    stores["gate_passes"][gp["id"]] = gp
    return gp, 201


def list_gate_passes(user, id):
    s = get_entity("sales", id, "ERR_SALE_NOT_FOUND", "Sale")
    items = sort_created(gate_passes_for_sale(s["id"]))
    page, meta = paginate(items)
    return page, 200, meta


def get_gate_pass(user, id):
    gp = get_entity("gate_passes", id, "ERR_GATE_PASS_NOT_FOUND", "GatePass")
    return gp, 200


def gate_pass_check_in(user, id):
    gp = get_entity("gate_passes", id, "ERR_GATE_PASS_NOT_FOUND", "GatePass")
    s = stores["sales"].get(gp["sale_id"])
    if s is None:
        raise ApiError("ERR_SALE_NOT_FOUND", 404, "sale not found")
    v = stores["vehicles"].get(s["vehicle_id"])
    # State
    if gp["status"] != "ISSUED":
        raise ApiError("ERR_GATE_PASS_INVALID_STATE", 409,
                       "check-in requires ISSUED")
    # Expiry gate: logical clock <= gate_pass_expires_at (strict: expiry reached means expired)
    now = get_clock()
    if s["gate_pass_expires_at"]:
        exp = parse_iso8601_utc(s["gate_pass_expires_at"], "gate_pass_expires_at")
        if now >= exp:
            gp["status"] = "EXPIRED"
            touch(gp)
            raise ApiError("ERR_GATE_PASS_EXPIRED", 409,
                           "check-in after Sale.gate_pass_expires_at")
    # Slot window currently holds: slot_start <= now <= slot_end
    ss = parse_iso8601_utc(gp["slot_start"], "slot_start")
    se = parse_iso8601_utc(gp["slot_end"], "slot_end")
    if not (ss <= now <= se):
        raise ApiError("ERR_SLOT_WINDOW_INVALID", 400,
                       "logical clock must fall within the slot window")
    # Export compliance: non-US winner requires VERIFIED export document
    winner = stores["members"].get(s["winner_member_id"])
    if winner is not None and winner["country_code"] != "US":
        verified = any(
            d["status"] == "VERIFIED" and d["destination_country"] == winner["country_code"]
            for d in export_docs_for_sale(s["id"])
        )
        if not verified:
            raise ApiError("ERR_EXPORT_DOCUMENT_REQUIRED", 409,
                           "check-in for non-US winner without a VERIFIED export document")
    # Capacity re-check at check-in
    if v is not None:
        existing = _check_slot_capacity(v["yard_id"], ss, se, exclude_pass_id=gp["id"])
        if existing >= SLOT_CAPACITY:
            raise ApiError("ERR_SLOT_CAPACITY_EXCEEDED", 409,
                           "slot capacity exceeded at check-in")
    # Winner-side storage fee
    rate = v and stores["yards"].get(v["yard_id"])
    yard = stores["yards"].get(v["yard_id"]) if v else None
    free_days = yard["free_storage_days"] if yard else 0
    rate_cents = yard["daily_storage_rate_cents"] if yard else 0
    # Sale day = UTC date of close-lot / approve. We use the sale's updated_at
    # transition timestamp: specifically the moment the sale became AWAITING_PAYMENT.
    # Stored on the sale as part of the close/approve action — use sale's updated_at
    # at AWAITING_PAYMENT; simpler: derive from gate_pass_expires_at minus 72h.
    exp_dt = parse_iso8601_utc(s["gate_pass_expires_at"], "gate_pass_expires_at") \
        if s["gate_pass_expires_at"] else None
    sale_day = (exp_dt - timedelta(hours=GATE_PASS_EXPIRY_HOURS)).date() if exp_dt else now.date()
    days = (now.date() - sale_day).days
    chargeable = max(0, days - free_days)
    gp["storage_fee_cents"] = chargeable * rate_cents
    gp["status"] = "CHECKED_IN"
    touch(gp)
    return gp, 200


def gate_pass_complete(user, id):
    gp = get_entity("gate_passes", id, "ERR_GATE_PASS_NOT_FOUND", "GatePass")
    if gp["status"] != "CHECKED_IN":
        raise ApiError("ERR_GATE_PASS_INVALID_STATE", 409,
                       "complete requires CHECKED_IN")
    s = stores["sales"].get(gp["sale_id"])
    v = stores["vehicles"].get(s["vehicle_id"]) if s else None
    gp["status"] = "COMPLETED"
    touch(gp)
    if v is not None:
        v["status"] = "LOADED_OUT"
        touch(v)
    if s is not None:
        st = settlement_for_sale(s["id"])
        if st is not None:
            st["status"] = "PAID"
            touch(st)
    return gp, 200


# =====================================================================
# Settlement
# =====================================================================

def list_sale_settlements(user, id):
    s = get_entity("sales", id, "ERR_SALE_NOT_FOUND", "Sale")
    st = settlement_for_sale(s["id"])
    items = [st] if st else []
    page, meta = paginate(items)
    return page, 200, meta


def list_settlements(user):
    items = list_filter(stores["settlements"].values(), [
        ("seller_id", "seller_id", None),
        ("status", "status", None),
    ])
    items = sort_created(items)
    page, meta = paginate(items)
    return page, 200, meta


def get_settlement(user, id):
    st = stores["settlements"].get(id)
    if st is None:
        raise ApiError("ERR_NOT_FOUND", 404, "settlement id does not exist")
    return st, 200


# =====================================================================
# ExportDocument
# =====================================================================

def create_export_document(user, id):
    s = get_entity("sales", id, "ERR_SALE_NOT_FOUND", "Sale")
    if user["role"] == ROLE_BUYER and user["user_id"] != s["winner_member_id"]:
        raise err_forbidden("Buyer may submit only on own sale")
    body = get_body()
    require_fields(body, ["document_type", "destination_country"])
    if body["document_type"] not in EXPORT_DOC_TYPES:
        raise bad_request("document_type must be BILL_OF_LADING | EXPORT_DECLARATION | CUSTOMS_MANIFEST")
    if not is_string(body["destination_country"]) or not body["destination_country"]:
        raise bad_request("destination_country must be a non-empty string")
    winner = stores["members"].get(s["winner_member_id"])
    if winner is None or body["destination_country"] != winner["country_code"]:
        raise ApiError("ERR_EXPORT_DOC_COUNTRY_MISMATCH", 422,
                       "destination_country != winner Member.country_code")
    doc = new_entity({
        "sale_id": s["id"],
        "document_type": body["document_type"],
        "destination_country": body["destination_country"],
        "status": "SUBMITTED",
    })
    stores["export_documents"][doc["id"]] = doc
    return doc, 201


def list_export_documents(user, id):
    s = get_entity("sales", id, "ERR_SALE_NOT_FOUND", "Sale")
    items = sort_created(export_docs_for_sale(s["id"]))
    page, meta = paginate(items)
    return page, 200, meta


def get_export_document(user, id):
    d = get_entity("export_documents", id, "ERR_EXPORT_DOC_NOT_FOUND", "ExportDocument")
    return d, 200


def export_doc_verify(user, id):
    d = get_entity("export_documents", id, "ERR_EXPORT_DOC_NOT_FOUND", "ExportDocument")
    if d["status"] != "SUBMITTED":
        raise ApiError("ERR_EXPORT_DOC_INVALID_STATE", 409,
                       "verify requires export document SUBMITTED")
    d["status"] = "VERIFIED"
    touch(d)
    return d, 200


def export_doc_reject(user, id):
    d = get_entity("export_documents", id, "ERR_EXPORT_DOC_NOT_FOUND", "ExportDocument")
    if d["status"] != "SUBMITTED":
        raise ApiError("ERR_EXPORT_DOC_INVALID_STATE", 409,
                       "reject requires export document SUBMITTED")
    d["status"] = "REJECTED"
    touch(d)
    return d, 200


# =====================================================================
# Route table
# =====================================================================

P = "/salvage-auction"
ADM = ROLE_PLATFORM_ADMIN
SEL = ROLE_SELLER_AGENT
YRD = ROLE_YARD_OPERATOR
AUC = ROLE_AUCTIONEER
BUY = ROLE_BUYER
TCL = ROLE_TITLE_CLERK

ALL_GET = [ADM, SEL, YRD, AUC, BUY, TCL]

ROUTES = [
    ("POST", f"{P}/_clock/set_current_utc", clock_set, [ADM]),

    ("POST", f"{P}/yards", create_yard, [ADM]),
    ("GET", f"{P}/yards", list_yards, ALL_GET),
    ("GET", f"{P}/yards/<id>", get_yard, ALL_GET),

    ("POST", f"{P}/sellers", create_seller, [ADM]),
    ("GET", f"{P}/sellers", list_sellers, ALL_GET),
    ("GET", f"{P}/sellers/<id>", get_seller, ALL_GET),

    ("POST", f"{P}/members", create_member, [ADM]),
    ("GET", f"{P}/members", list_members, [ADM, AUC, TCL]),
    ("GET", f"{P}/members/<id>", get_member, [ADM, AUC, TCL, BUY]),

    ("POST", f"{P}/members/<id>/licenses", create_license, [ADM, TCL]),
    ("GET", f"{P}/members/<id>/licenses", list_member_licenses, [ADM, AUC, TCL, BUY]),
    ("GET", f"{P}/licenses/<id>", get_license, [ADM, AUC, TCL, BUY]),

    ("POST", f"{P}/vehicles", create_vehicle, [SEL]),
    ("GET", f"{P}/vehicles", list_vehicles, ALL_GET),
    ("GET", f"{P}/vehicles/<id>", get_vehicle, ALL_GET),
    ("POST", f"{P}/vehicles/<id>/images", vehicle_add_image, [YRD]),
    ("POST", f"{P}/vehicles/<id>/condition", vehicle_condition, [YRD]),
    ("POST", f"{P}/vehicles/<id>/mark-ready", vehicle_mark_ready, [YRD]),
    ("POST", f"{P}/vehicles/<id>/cancel", vehicle_cancel, [SEL]),
    ("POST", f"{P}/vehicles/<id>/title", create_title, [TCL]),
    ("GET", f"{P}/vehicles/<id>/title", list_vehicle_titles, ALL_GET),
    ("GET", f"{P}/titles/<id>", get_title, [ADM, YRD, AUC, SEL, TCL]),

    ("POST", f"{P}/auctions", create_auction, [AUC]),
    ("GET", f"{P}/auctions", list_auctions, ALL_GET),
    ("GET", f"{P}/auctions/<id>", get_auction, ALL_GET),
    ("POST", f"{P}/auctions/<id>/start", auction_start, [AUC]),

    ("POST", f"{P}/auctions/<id>/items", create_auction_item, [AUC]),
    ("GET", f"{P}/auctions/<id>/items", list_auction_items, ALL_GET),
    ("GET", f"{P}/vehicles/<id>/auction-items", list_vehicle_auction_items, ALL_GET),
    ("GET", f"{P}/auction-items/<id>", get_auction_item, ALL_GET),
    ("POST", f"{P}/auctions/<id>/items/<itemId>/open-lot", open_lot, [AUC]),
    ("POST", f"{P}/auctions/<id>/items/<itemId>/close-lot", close_lot, [AUC]),
    ("POST", f"{P}/auctions/<id>/items/<itemId>/cancel", cancel_auction_item, [AUC]),

    ("POST", f"{P}/bids", place_bid, [BUY]),
    ("GET", f"{P}/bids", list_bids, ALL_GET),
    ("GET", f"{P}/bids/<id>", get_bid, ALL_GET),

    ("GET", f"{P}/sales", list_sales, ALL_GET),
    ("GET", f"{P}/sales/<id>", get_sale, ALL_GET),
    ("POST", f"{P}/sales/<id>/approve", sale_approve, [SEL]),
    ("POST", f"{P}/sales/<id>/reject-offer", sale_reject, [SEL]),
    ("POST", f"{P}/sales/<id>/cancel", sale_cancel, [SEL]),
    ("POST", f"{P}/sales/<id>/payments", sale_pay, [BUY]),

    ("POST", f"{P}/sales/<id>/gate-passes", create_gate_pass, [BUY, YRD]),
    ("GET", f"{P}/sales/<id>/gate-passes", list_gate_passes, ALL_GET),
    ("GET", f"{P}/gate-passes/<id>", get_gate_pass, ALL_GET),
    ("POST", f"{P}/gate-passes/<id>/check-in", gate_pass_check_in, [YRD]),
    ("POST", f"{P}/gate-passes/<id>/complete", gate_pass_complete, [YRD]),

    ("GET", f"{P}/sales/<id>/settlement", list_sale_settlements, [ADM, AUC, SEL, TCL]),
    ("GET", f"{P}/settlements", list_settlements, [ADM, AUC, SEL, TCL]),
    ("GET", f"{P}/settlements/<id>", get_settlement, [ADM, AUC, SEL, TCL]),

    ("POST", f"{P}/sales/<id>/export-documents", create_export_document, [BUY, ADM]),
    ("GET", f"{P}/sales/<id>/export-documents", list_export_documents, ALL_GET),
    ("GET", f"{P}/export-documents/<id>", get_export_document, ALL_GET),
    ("POST", f"{P}/export-documents/<id>/verify", export_doc_verify, [ADM]),
    ("POST", f"{P}/export-documents/<id>/reject", export_doc_reject, [ADM]),
]
