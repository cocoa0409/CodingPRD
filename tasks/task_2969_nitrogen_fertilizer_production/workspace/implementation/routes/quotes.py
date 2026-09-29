"""Customer quoting on a hedged or spot basis (PRD 3.8)."""
from flask import Blueprint, request

import calc
import serialize
import validate as v
from auth import ALL_ROLES, COMMERCIAL_MANAGER, actor
from envelope import list_response, object_response, paging
from guards import duplicate, filtered, load, not_frozen, state
from mutate import touch
from store import db, stamp_new

bp = Blueprint("quotes", __name__)
PREFIX = "/nitrogen-ops/price-quotes"
BASES = ("HEDGED_BLEND", "SPOT_INDEX")
QUOTE_STATUSES = ("DRAFT", "ISSUED", "WITHDRAWN", "EXPIRED")


@bp.post(PREFIX)
def create_quote():
    actor([COMMERCIAL_MANAGER])
    body = v.get_body()
    plant_id = v.s_id(body, "plant_id")
    line_id = v.s_id(body, "product_line_id")
    quote_code = v.s_code(body, "quote_code", 2, 16)
    tons = v.s_num(body, "tons", 3, gt=0)
    basis = v.s_enum(body, "pass_through_basis", BASES)
    expires_at = v.s_dt(body, "expires_at")
    if expires_at <= db.clock:
        v.bad("expires_at must be after the quote's created_at.")
    plant = load("plants", plant_id)
    line = load("lines", line_id)
    duplicate("quotes", "quote_code", quote_code)
    state(line["plant_id"] == plant["id"], "ERR_PRODUCT_MISMATCH",
          "The product line does not belong to this plant's slate.")
    row = {
        "plant_id": plant_id,
        "product_line_id": line_id,
        "quote_code": quote_code,
        "tons": tons,
        "pass_through_basis": basis,
        "expires_at": expires_at,
        "gas_basis_usd_per_mmbtu": None,
        "quoted_price_usd_per_ton": None,
        "issued_at": None,
        "status": "DRAFT",
        "withdraw_reason": None,
    }
    stamp_new(row)
    db.quotes[row["id"]] = row
    return object_response(serialize.quote_json(row), 201)


@bp.get(PREFIX + "/<id>")
def get_quote(id):
    actor(ALL_ROLES)
    return object_response(serialize.quote_json(load("quotes", id)))


@bp.get(PREFIX)
def list_quotes():
    actor(ALL_ROLES)
    limit, offset = paging(request.args)
    rows = filtered("quotes", [
        ("plant_id", v.query_str("plant_id")),
        ("product_line_id", v.query_str("product_line_id")),
        ("status", v.query_enum("status", QUOTE_STATUSES)),
    ])
    return list_response(serialize.dump("quotes", rows), limit, offset)


@bp.post(PREFIX + "/expire-due")
def expire_due():
    """The ops checkpoint: expiry is never automatic."""
    actor([COMMERCIAL_MANAGER])
    v.get_body()
    due = [q for q in db.quotes.values()
           if q["status"] in ("DRAFT", "ISSUED") and q["expires_at"] <= db.clock]
    due.sort(key=lambda q: (q["expires_at"], q["_seq"]))
    ids = []
    for quote in due:
        quote["status"] = "EXPIRED"
        touch(quote)
        ids.append(quote["id"])
    return object_response({"expired_count": len(ids), "expired_quote_ids": ids})


@bp.post(PREFIX + "/<id>/issue")
def issue_quote(id):
    actor([COMMERCIAL_MANAGER])
    v.get_body()
    quote = load("quotes", id)
    state(quote["status"] == "DRAFT")
    state(db.clock < quote["expires_at"], "ERR_QUOTE_EXPIRED")
    plant = db.plants[quote["plant_id"]]
    not_frozen(plant)
    line = db.lines[quote["product_line_id"]]
    basis = calc.quote_gas_basis(quote, plant)
    posture = calc.operating_posture(plant)
    quote["gas_basis_usd_per_mmbtu"] = basis
    quote["quoted_price_usd_per_ton"] = calc.quote_price(quote, plant, line,
                                                         posture, basis)
    quote["issued_at"] = db.clock
    quote["status"] = "ISSUED"
    touch(quote)
    return object_response(serialize.quote_json(quote))


@bp.post(PREFIX + "/<id>/withdraw")
def withdraw_quote(id):
    actor([COMMERCIAL_MANAGER])
    body = v.get_body()
    reason = v.s_str(body, "withdraw_reason", min_len=1)
    quote = load("quotes", id)
    state(quote["status"] == "ISSUED")
    quote["status"] = "WITHDRAWN"
    quote["withdraw_reason"] = reason
    touch(quote)
    return object_response(serialize.quote_json(quote))


@bp.post(PREFIX + "/<id>/revise")
def revise_quote(id):
    actor([COMMERCIAL_MANAGER])
    body = v.get_body()
    tons = v.s_num(body, "tons", 3, required=False, gt=0)
    basis = v.s_enum(body, "pass_through_basis", BASES, required=False)
    expires_at = v.s_dt(body, "expires_at", required=False)
    quote = load("quotes", id)
    if expires_at is not None and expires_at <= quote["created_at"]:
        v.bad("expires_at must be after the quote's created_at.")
    state(quote["status"] == "WITHDRAWN")
    if tons is not None:
        quote["tons"] = tons
    if basis is not None:
        quote["pass_through_basis"] = basis
    if expires_at is not None:
        quote["expires_at"] = expires_at
    quote["quoted_price_usd_per_ton"] = None
    quote["gas_basis_usd_per_mmbtu"] = None
    quote["issued_at"] = None
    quote["withdraw_reason"] = None
    quote["status"] = "DRAFT"
    touch(quote)
    return object_response(serialize.quote_json(quote))
