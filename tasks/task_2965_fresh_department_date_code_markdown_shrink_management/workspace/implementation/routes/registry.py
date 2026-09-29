"""Store, food-bank partner and markdown-ladder registry endpoints."""
from flask import Blueprint

from db import db
from errors import ApiError, bad_request
from middleware import (ROLE_ADMIN, ROLE_AUDITOR, ROLE_CLERK, ROLE_MANAGER,
                        ROLE_PARTNER, actor, authenticate)
from records import new_record, partner_by_id, ladder_by_id, store_by_id, touch
from response import created, ok, public
from routes.common import (ACTIVE_SUSPENDED, DEPARTMENT_CODES, LADDER_STATUSES,
                           REGION_CODE_RE, STORE_NUMBER_RE, listing, matches)
from util import D, fmt_instant, num
from validate import (MISSING, field_array, field_bool, field_enum, field_int,
                      field_number, field_string, json_body, query_bool,
                      query_enum, query_string)

bp = Blueprint("registry", __name__)

READ_ROLES = (ROLE_ADMIN, ROLE_MANAGER, ROLE_CLERK, ROLE_AUDITOR)


# --- dock door codes -------------------------------------------------------
def _dock_door_codes(body, required, default):
    codes = field_array(body, "dock_door_codes", required=required,
                        default=default, min_items=1, max_items=8)
    if codes is MISSING or codes is default:
        return codes
    for code in codes:
        if not isinstance(code, str) or not (1 <= len(code) <= 8):
            raise bad_request("dock_door_codes entries must be 1..8 chars")
    return list(codes)


# --- stores ----------------------------------------------------------------
@bp.get("/fresh/stores/<store_id>")
def get_store(store_id):
    authenticate(*READ_ROLES)
    return ok(public(store_by_id(store_id)))


@bp.get("/fresh/stores")
def list_stores():
    authenticate(*READ_ROLES)
    status = query_enum("status", ACTIVE_SUSPENDED)
    region_code = query_string("region_code")
    rows = [
        s for s in db.stores.values()
        if matches(s, "status", status)
        and matches(s, "region_code", region_code)
    ]
    return listing(rows)


@bp.post("/fresh/stores")
def create_store():
    authenticate(ROLE_ADMIN)
    body = json_body()
    store_number = field_string(body, "store_number", required=True,
                                min_len=4, max_len=4, pattern=STORE_NUMBER_RE)
    name = field_string(body, "name", required=True, min_len=1, max_len=120)
    region_code = field_string(body, "region_code", required=True, min_len=1,
                               max_len=24, pattern=REGION_CODE_RE)
    dock_door_codes = _dock_door_codes(body, False, ["D1", "D2", "D3"])
    donation_program_enabled = field_bool(
        body, "donation_program_enabled", default=True)
    status = field_enum(body, "status", ACTIVE_SUSPENDED, default="ACTIVE")
    for existing in db.stores.values():
        if existing["store_number"] == store_number:
            raise ApiError("ERR_STORE_NUMBER_DUPLICATE",
                           "store_number %s already exists" % store_number)
    record = new_record(db.stores, {
        "store_number": store_number,
        "name": name,
        "region_code": region_code,
        "dock_door_codes": list(dock_door_codes),
        "donation_program_enabled": donation_program_enabled,
        "status": status,
    })
    return created(public(record))


@bp.patch("/fresh/stores/<store_id>")
def patch_store(store_id):
    authenticate(ROLE_ADMIN)
    body = json_body()
    status = field_enum(body, "status", ACTIVE_SUSPENDED, default=MISSING)
    enabled = field_bool(body, "donation_program_enabled", default=MISSING)
    codes = _dock_door_codes(body, False, MISSING)
    name = field_string(body, "name", default=MISSING, min_len=1, max_len=120)
    store = store_by_id(store_id)
    if status is not MISSING:
        store["status"] = status
    if enabled is not MISSING:
        store["donation_program_enabled"] = enabled
    if codes is not MISSING:
        store["dock_door_codes"] = list(codes)
    if name is not MISSING:
        store["name"] = name
    touch(store)
    return ok(public(store))


# --- food-bank partners ----------------------------------------------------
def _accepted_department_codes(body, required, default):
    codes = field_array(body, "accepted_department_codes", required=required,
                        default=default, min_items=1, max_items=6)
    if codes is MISSING or codes is default:
        return codes
    seen = set()
    for code in codes:
        if code not in DEPARTMENT_CODES:
            raise bad_request(
                "accepted_department_codes entries must be department codes")
        if code in seen:
            raise bad_request("accepted_department_codes must not repeat")
        seen.add(code)
    return list(codes)


def _contact_email(body, required, default):
    email = field_string(body, "contact_email", required=required,
                         default=default, min_len=1, max_len=200)
    if email is MISSING or email is default:
        return email
    if email.count("@") != 1:
        raise bad_request("contact_email must contain exactly one '@'")
    return email


@bp.get("/fresh/food-bank-partners/<partner_id>")
def get_partner(partner_id):
    authenticate(ROLE_ADMIN, ROLE_MANAGER, ROLE_AUDITOR, ROLE_PARTNER)
    return ok(public(partner_by_id(partner_id)))


@bp.get("/fresh/food-bank-partners")
def list_partners():
    authenticate(ROLE_ADMIN, ROLE_MANAGER, ROLE_AUDITOR)
    status = query_enum("status", ACTIVE_SUSPENDED)
    region = query_string("service_region_code")
    certified = query_bool("cold_chain_certified")
    rows = [
        p for p in db.partners.values()
        if matches(p, "status", status)
        and matches(p, "service_region_code", region)
        and matches(p, "cold_chain_certified", certified)
    ]
    return listing(rows)


@bp.post("/fresh/food-bank-partners")
def create_partner():
    authenticate(ROLE_ADMIN)
    body = json_body()
    name = field_string(body, "name", required=True, min_len=1, max_len=120)
    email = _contact_email(body, True, None)
    region = field_string(body, "service_region_code", required=True,
                          min_len=1, max_len=24)
    codes = _accepted_department_codes(body, True, None)
    certified = field_bool(body, "cold_chain_certified", default=False)
    status = field_enum(body, "status", ACTIVE_SUSPENDED, default="ACTIVE")
    record = new_record(db.partners, {
        "name": name,
        "contact_email": email,
        "service_region_code": region,
        "accepted_department_codes": list(codes),
        "cold_chain_certified": certified,
        "status": status,
        "pickups_completed_count": 0,
        "units_received_total": 0,
    })
    return created(public(record))


@bp.patch("/fresh/food-bank-partners/<partner_id>")
def patch_partner(partner_id):
    authenticate(ROLE_ADMIN)
    body = json_body()
    status = field_enum(body, "status", ACTIVE_SUSPENDED, default=MISSING)
    certified = field_bool(body, "cold_chain_certified", default=MISSING)
    codes = _accepted_department_codes(body, False, MISSING)
    email = _contact_email(body, False, MISSING)
    partner = partner_by_id(partner_id)
    if status is not MISSING:
        partner["status"] = status
    if certified is not MISSING:
        partner["cold_chain_certified"] = certified
    if codes is not MISSING:
        partner["accepted_department_codes"] = list(codes)
    if email is not MISSING:
        partner["contact_email"] = email
    touch(partner)
    return ok(public(partner))


# --- markdown ladders ------------------------------------------------------
def _rungs(body):
    rungs = field_array(body, "rungs", required=True, min_items=2, max_items=6)
    parsed = []
    for entry in rungs:
        if not isinstance(entry, dict):
            raise bad_request("Each rung must be an object")
        days = entry.get("days_remaining_max")
        if isinstance(days, bool) or not isinstance(days, int):
            raise bad_request("rung days_remaining_max must be an integer")
        discount = entry.get("discount_pct")
        if isinstance(discount, bool) or not isinstance(discount, (int, float)):
            raise bad_request("rung discount_pct must be a number")
        discount = D(discount)
        if discount <= D(0) or discount >= D(100):
            raise bad_request("rung discount_pct must be in (0, 100)")
        approval = entry.get("requires_manager_approval", False)
        if not isinstance(approval, bool):
            raise bad_request("rung requires_manager_approval must be boolean")
        parsed.append({
            "days_remaining_max": days,
            "discount_pct": num(discount),
            "requires_manager_approval": approval,
        })
    for previous, following in zip(parsed, parsed[1:]):
        if not following["days_remaining_max"] < previous["days_remaining_max"]:
            raise bad_request(
                "rung days_remaining_max must be strictly decreasing")
        if not D(following["discount_pct"]) > D(previous["discount_pct"]):
            raise bad_request("rung discount_pct must be strictly increasing")
    return parsed


@bp.get("/fresh/markdown-ladders/<ladder_id>")
def get_ladder(ladder_id):
    authenticate(*READ_ROLES)
    return ok(public(ladder_by_id(ladder_id)))


@bp.get("/fresh/markdown-ladders")
def list_ladders():
    authenticate(*READ_ROLES)
    status = query_enum("status", LADDER_STATUSES)
    code = query_enum("department_code", DEPARTMENT_CODES)
    rows = [
        l for l in db.ladders.values()
        if matches(l, "status", status)
        and matches(l, "department_code", code)
    ]
    return listing(rows)


@bp.post("/fresh/markdown-ladders")
def create_ladder():
    authenticate(ROLE_ADMIN)
    body = json_body()
    name = field_string(body, "name", required=True, min_len=1, max_len=60)
    code = field_enum(body, "department_code", DEPARTMENT_CODES, required=True)
    rungs = _rungs(body)
    floor_pct = field_number(body, "sell_through_floor_pct", default=D("60"),
                             exclusive_min=0, maximum=100)
    max_discount = field_number(body, "max_total_discount_pct",
                                default=D("75"), exclusive_min=0, maximum=95)
    for existing in db.ladders.values():
        if existing["name"] == name:
            raise ApiError("ERR_LADDER_NAME_DUPLICATE",
                           "Ladder name %s already exists" % name)
    record = new_record(db.ladders, {
        "name": name,
        "department_code": code,
        "rungs": rungs,
        "sell_through_floor_pct": num(floor_pct),
        "max_total_discount_pct": num(max_discount),
        "status": "DRAFT",
        "activated_at": None,
    })
    return created(public(record))


@bp.post("/fresh/markdown-ladders/<ladder_id>/activate")
def activate_ladder(ladder_id):
    authenticate(ROLE_ADMIN)
    json_body()
    ladder = ladder_by_id(ladder_id)
    if ladder["status"] != "DRAFT":
        raise ApiError("ERR_LADDER_NOT_DRAFT",
                       "Only a DRAFT ladder may be activated")
    ladder["status"] = "ACTIVE"
    ladder["activated_at"] = fmt_instant(db.now())
    touch(ladder)
    return ok(public(ladder))


@bp.post("/fresh/markdown-ladders/<ladder_id>/retire")
def retire_ladder(ladder_id):
    authenticate(ROLE_ADMIN)
    json_body()
    ladder = ladder_by_id(ladder_id)
    if ladder["status"] != "ACTIVE":
        raise ApiError("ERR_LADDER_NOT_ACTIVE",
                       "Only an ACTIVE ladder may be retired")
    ladder["status"] = "RETIRED"
    touch(ladder)
    return ok(public(ladder))
