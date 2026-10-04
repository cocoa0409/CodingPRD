"""Retailer onboarding, status, item-file upload, item listing."""
import re

from flask import Blueprint

from errors import ApiError
from state import DB
from domain import new_entity, touch, ser_retailer, ser_item
from util import (
    authed, body, req_str, opt_bool, ok_object, list_response, sort_created,
    parse_iso_date, query_filter, retailer_self,
)

bp = Blueprint("retailers", __name__, url_prefix="/ebt")

UPC_RE = re.compile(r"^[0-9]{12}$")


def get_retailer(rid):
    r = DB.retailers.get(rid)
    if r is None:
        raise ApiError("ERR_NOT_FOUND", "retailer not found")
    return r


@bp.post("/retailers")
def create_retailer():
    authed(["StateAdmin"])
    b = body()
    contract_id = req_str(b, "contract_id")
    retailer_name = req_str(b, "retailer_name")
    acquirer_reference = req_str(b, "acquirer_reference")
    contract = DB.contracts.get(contract_id)
    if contract is None:
        raise ApiError("ERR_REFERENCE_NOT_FOUND", "contract_id does not exist")
    if contract["contract_status"] != "ACTIVE":
        raise ApiError("ERR_CONTRACT_NOT_ACTIVE", "retailer onboarding requires contract ACTIVE")
    r = new_entity()
    r.update({
        "contract_id": contract_id,
        "retailer_name": retailer_name,
        "acquirer_reference": acquirer_reference,
        "retailer_status": "APPROVED",
        "skimming_incident_count": 0,
        "_suspended_at": None,
    })
    DB.retailers[r["id"]] = r
    return ok_object(ser_retailer(r), 201)


@bp.get("/retailers/<rid>")
def read_retailer(rid):
    role, uid = authed(["StateAdmin", "CardholderServices", "RetailerSystem"])
    r = get_retailer(rid)
    retailer_self(role, uid, r["id"])
    return ok_object(ser_retailer(r))


@bp.post("/retailers/<rid>/status")
def retailer_status(rid):
    authed(["StateAdmin"])
    r = get_retailer(rid)
    b = body()
    to = req_str(b, "to")
    if to not in ("APPROVED", "SUSPENDED"):
        raise ApiError("ERR_INVALID_REQUEST", "unknown target status")
    cur = r["retailer_status"]
    if (cur, to) not in (("APPROVED", "SUSPENDED"), ("SUSPENDED", "APPROVED")):
        raise ApiError("ERR_INVALID_STATE", f"cannot transition retailer {cur} -> {to}")
    import util
    r["retailer_status"] = to
    if to == "SUSPENDED":
        r["_suspended_at"] = util.now_dt()
    touch(r)
    return ok_object(ser_retailer(r))


@bp.post("/retailers/<rid>/item-files")
def upload_item_file(rid):
    role, uid = authed(["RetailerSystem"])
    r = get_retailer(rid)
    retailer_self(role, uid, r["id"])
    contract = DB.contracts[r["contract_id"]]
    if contract["contract_status"] != "ACTIVE":
        raise ApiError("ERR_CONTRACT_NOT_ACTIVE", "item-file upload requires contract ACTIVE")
    if r["retailer_status"] != "APPROVED":
        raise ApiError("ERR_RETAILER_NOT_ACTIVE", "retailer is not APPROVED")
    b = body()
    items = b.get("items")
    if not isinstance(items, list):
        raise ApiError("ERR_INVALID_REQUEST", "items must be a list")
    # Validate every entry; any failure rejects the whole file.
    staged = []
    for entry in items:
        if not isinstance(entry, dict):
            raise ApiError("ERR_INVALID_REQUEST", "each item must be an object")
        upc = entry.get("upc")
        if not isinstance(upc, str) or not UPC_RE.match(upc):
            raise ApiError("ERR_UPC_INVALID", "upc must be exactly 12 decimal digits")
        food_eligible = entry.get("food_eligible")
        if not isinstance(food_eligible, bool):
            raise ApiError("ERR_INVALID_REQUEST", "food_eligible must be a boolean")
        eff_from = parse_iso_date(entry.get("effective_from"))
        if eff_from is None:
            raise ApiError("ERR_INVALID_REQUEST", "effective_from must be an ISO date")
        eff_to_raw = entry.get("effective_to")
        eff_to = None
        if eff_to_raw is not None:
            eff_to = parse_iso_date(eff_to_raw)
            if eff_to is None:
                raise ApiError("ERR_INVALID_REQUEST", "effective_to must be an ISO date")
            if eff_to <= eff_from:
                raise ApiError("ERR_INVALID_REQUEST",
                               "effective_to must be after effective_from")
        staged.append({"upc": upc, "food_eligible": food_eligible,
                       "effective_from": eff_from, "effective_to": eff_to})
    # Half-open [from, to) overlap per (retailer_id, upc); adjacency allowed.
    existing = [it for it in DB.items.values() if it["retailer_id"] == r["id"]]
    far = __import__("domain").FAR_FUTURE_DATE

    def overlaps(f1, t1, f2, t2):
        t1 = t1 if t1 is not None else far
        t2 = t2 if t2 is not None else far
        return f1 < t2 and f2 < t1

    for new_it in staged:
        for old in existing:
            if old["upc"] != new_it["upc"]:
                continue
            if overlaps(old["effective_from"], old["effective_to"],
                        new_it["effective_from"], new_it["effective_to"]):
                raise ApiError("ERR_ITEM_WINDOW_OVERLAP",
                               "item window overlaps an existing record")
    # also check within the file itself
    for i in range(len(staged)):
        for j in range(i + 1, len(staged)):
            a, c = staged[i], staged[j]
            if a["upc"] == c["upc"] and overlaps(
                    a["effective_from"], a["effective_to"],
                    c["effective_from"], c["effective_to"]):
                raise ApiError("ERR_ITEM_WINDOW_OVERLAP",
                               "item window overlaps another entry in the file")
    created = 0
    for s in staged:
        it = new_entity()
        it.update({
            "retailer_id": r["id"],
            "upc": s["upc"],
            "food_eligible": s["food_eligible"],
            "effective_from": s["effective_from"],
            "effective_to": s["effective_to"],
        })
        DB.items[it["id"]] = it
        created += 1
    return ok_object({"created_count": created}, 201)


@bp.get("/retailers/<rid>/items")
def list_items(rid):
    role, uid = authed(["StateAdmin", "CardholderServices", "RetailerSystem"])
    r = get_retailer(rid)
    retailer_self(role, uid, r["id"])
    rows = [it for it in DB.items.values() if it["retailer_id"] == r["id"]]
    upc = query_filter("upc")
    if upc is not None:
        rows = [it for it in rows if it["upc"] == upc]
    return list_response(sort_created(rows), ser_item)
