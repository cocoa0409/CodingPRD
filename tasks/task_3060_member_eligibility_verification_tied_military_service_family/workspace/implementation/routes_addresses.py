from flask import Blueprint, request

import auth
import store
from domain import ser_address
from envelope import success
from errors import err
from helpers import (
    new_row, touch, require_field, require_enum, require_date, optional_date,
    optional_bool, date_to_str, d_from_str,
)
from paginate import list_response

bp = Blueprint("addresses", __name__)

ADDR_TYPES = {"DOMESTIC_RESIDENCE", "MILITARY_APO_FPO_DPO", "OVERSEAS_FOREIGN"}


def _get_member(member_id):
    m = store.T["members"].get(member_id)
    if m is None:
        raise err("ERR_NOT_FOUND", 404, "member not found")
    return m


def _get_address(address_id):
    a = store.T["addresses"].get(address_id)
    if a is None:
        raise err("ERR_NOT_FOUND", 404, "address not found")
    return a


def _intervals_overlap(s1, e1, s2, e2):
    """Half-open [s, e) overlap; None end = infinity."""
    e1i = e1 if e1 is not None else None
    e2i = e2 if e2 is not None else None
    # [s1,e1) overlaps [s2,e2) iff s1 < e2 and s2 < e1 (open ends treated as +inf)
    left = True
    right = True
    if e2i is not None and not (s1 < e2i):
        left = False
    if e1i is not None and not (s2 < e1i):
        right = False
    return left and right


def _validate_no_overlap(member_id, addr_type, s, e, exclude_id=None):
    for a in store.T["addresses"].values():
        if a["member_id"] != member_id or a["addr_type"] != addr_type:
            continue
        if exclude_id and a["id"] == exclude_id:
            continue
        a_s = d_from_str(a["effective_from"])
        a_e = d_from_str(a["effective_to"]) if a["effective_to"] else None
        if _intervals_overlap(s, e, a_s, a_e):
            raise err("ERR_ADDRESS_OVERLAP", 409, "address interval overlap")


@bp.post("/membership/members/<member_id>/addresses")
def create_address(member_id):
    c = auth.ctx()
    auth.require_roles(c, ["Member", "VerificationOfficer"])
    auth.enforce_ownership(c, member_id)
    m = _get_member(member_id)
    body = request.get_json(silent=True)
    if not isinstance(body, dict):
        raise err("ERR_INVALID_REQUEST", 400, "malformed body")
    addr_type = require_enum(body, "addr_type", ADDR_TYPES)
    line1 = require_field(body, "line1")
    city = require_field(body, "city")
    region = require_field(body, "region_code")
    postal = require_field(body, "postal_code")
    country = require_field(body, "country_code")
    ef = require_date(body, "effective_from")
    et = optional_date(body, "effective_to")
    duty = optional_bool(body, "is_duty_station", False)

    if et is not None and not (et > ef):
        raise err("ERR_ADDRESS_OVERLAP", 409, "effective_to must be strictly greater than effective_from")

    # Priority 30: retroactive duty station conflict
    if duty:
        for a in store.T["addresses"].values():
            if (a["member_id"] == member_id and a["is_duty_station"]
                    and a["effective_to"] is None):
                a_from = d_from_str(a["effective_from"])
                if ef < a_from:
                    raise err("ERR_DUTY_STATION_CONFLICT", 409,
                              "retroactive duty-station change requires closing prior interval")

    # Priority 9: same-type overlap
    _validate_no_overlap(member_id, addr_type, ef, et)

    row = new_row()
    row.update({
        "member_id": member_id,
        "addr_type": addr_type,
        "line1": line1, "city": city,
        "region_code": region, "postal_code": postal,
        "country_code": country,
        "effective_from": date_to_str(ef),
        "effective_to": date_to_str(et) if et else None,
        "is_duty_station": duty,
    })
    store.insert_row("addresses", row)
    return success(201, ser_address(row), "object")


@bp.get("/membership/members/<member_id>/addresses")
def list_member_addresses(member_id):
    c = auth.ctx()
    auth.require_roles(c, ["Member", "VerificationOfficer", "PlatformAdmin"])
    auth.enforce_ownership(c, member_id)
    _get_member(member_id)
    rows = [a for a in store.T["addresses"].values() if a["member_id"] == member_id]
    rows.sort(key=lambda r: (r["created_at"], r["id"]))
    return list_response([ser_address(r) for r in rows], success)


@bp.get("/membership/addresses")
def list_addresses():
    c = auth.ctx()
    auth.require_roles(c, ["VerificationOfficer", "PlatformAdmin"])
    rows = list(store.T["addresses"].values())
    member_id = request.args.get("member_id")
    addr_type = request.args.get("addr_type")
    if member_id:
        rows = [a for a in rows if a["member_id"] == member_id]
    if addr_type:
        rows = [a for a in rows if a["addr_type"] == addr_type]
    rows.sort(key=lambda r: (r["created_at"], r["id"]))
    return list_response([ser_address(r) for r in rows], success)


@bp.get("/membership/addresses/<address_id>")
def get_address(address_id):
    c = auth.ctx()
    auth.require_roles(c, ["Member", "VerificationOfficer", "PlatformAdmin"])
    a = _get_address(address_id)
    if c["role"] == "Member" and c["uid"] != a["member_id"]:
        raise err("ERR_FORBIDDEN_ROLE", 403, "ownership mismatch")
    return success(200, ser_address(a), "object")


@bp.route("/membership/addresses/<address_id>", methods=["PATCH"])
def patch_address(address_id):
    c = auth.ctx()
    auth.require_roles(c, ["Member", "VerificationOfficer"])
    a = _get_address(address_id)
    if c["role"] == "Member" and c["uid"] != a["member_id"]:
        raise err("ERR_FORBIDDEN_ROLE", 403, "ownership mismatch")
    body = request.get_json(silent=True)
    if not isinstance(body, dict):
        raise err("ERR_INVALID_REQUEST", 400, "malformed body")

    ef = d_from_str(a["effective_from"])
    et = d_from_str(a["effective_to"]) if a["effective_to"] else None
    duty = a["is_duty_station"]

    if "effective_from" in body:
        if body["effective_from"] is None:
            raise err("ERR_INVALID_REQUEST", 400, "effective_from cannot be null")
        from helpers import _iso_to_date, _MONTH_RE
        v = body["effective_from"]
        if not isinstance(v, str) or not _MONTH_RE.match(v):
            raise err("ERR_INVALID_REQUEST", 400, "invalid effective_from")
        ef = _iso_to_date(v)
    if "effective_to" in body:
        if body["effective_to"] is None:
            et = None
        else:
            from helpers import _iso_to_date, _MONTH_RE
            v = body["effective_to"]
            if not isinstance(v, str) or not _MONTH_RE.match(v):
                raise err("ERR_INVALID_REQUEST", 400, "invalid effective_to")
            et = _iso_to_date(v)
    if "is_duty_station" in body:
        v = body["is_duty_station"]
        if not isinstance(v, bool):
            raise err("ERR_INVALID_REQUEST", 400, "invalid is_duty_station")
        duty = v

    if et is not None and not (et > ef):
        raise err("ERR_ADDRESS_OVERLAP", 409, "effective_to must be strictly greater than effective_from")

    _validate_no_overlap(a["member_id"], a["addr_type"], ef, et, exclude_id=a["id"])

    a["effective_from"] = date_to_str(ef)
    a["effective_to"] = date_to_str(et) if et else None
    a["is_duty_station"] = duty
    touch(a)
    return success(200, ser_address(a), "object")
