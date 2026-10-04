import os
from flask import Flask, request

import errors as E
from errors import ApiError
from db import db, get_clock, set_clock, parse_iso
from response import success, error_response, new_id, paginate
from middleware import require_roles
from helpers import (
    touch, system_fields, append_only_fields, now_iso,
    provisional_price, final_price, compute_invoice_total, compute_valuation,
    price_band_ok, compute_penalty, clock_date, refresh_fountain_overdue,
    reevaluate_time_gated, decimal_to_json,
)

app = Flask(__name__)


@app.errorhandler(ApiError)
def handle_api_error(err):
    return error_response(err)


@app.errorhandler(404)
def handle_404(err):
    return error_response(E.err_not_found("Unknown route"))


@app.errorhandler(405)
def handle_405(err):
    return error_response(E.err_not_found("Unknown route"))


def body():
    b = request.get_json(silent=True)
    if b is None:
        return {}
    if not isinstance(b, dict):
        raise E.err_validation("JSON body must be an object")
    return b


def require_fields(b, *names):
    for n in names:
        if n not in b or b[n] is None:
            raise E.err_validation(f"Missing required field: {n}")


def sorted_by_created(items):
    return sorted(items, key=lambda x: (x["created_at"], x["id"]))


# ================= clock =================

@app.post("/bottler/_clock/set_current_utc")
def clock_set():
    require_roles("PlatformAdmin")
    b = body()
    require_fields(b, "to_iso8601")
    try:
        parse_iso(b["to_iso8601"])
    except Exception:
        raise E.err_validation("to_iso8601 must be a valid ISO 8601 timestamp")
    set_clock(b["to_iso8601"])
    reevaluate_time_gated()
    return success({"current_utc": get_clock()})


# ================= brand owners =================

@app.post("/bottler/brand-owners")
def create_brand_owner():
    require_roles("PlatformAdmin")
    b = body()
    require_fields(b, "name", "home_country")
    if not isinstance(b["name"], str) or not isinstance(b["home_country"], str):
        raise E.err_validation("name and home_country must be strings")
    bo = system_fields()
    bo.update({"id": new_id(), "name": b["name"], "home_country": b["home_country"],
               "status": "ACTIVE"})
    db.brand_owners[bo["id"]] = bo
    return success(bo, 201)


@app.get("/bottler/brand-owners/<bid>")
def get_brand_owner(bid):
    require_roles("PlatformAdmin", "BrandOwnerAdmin", "BottlerOps")
    bo = db.brand_owners.get(bid)
    if not bo:
        raise E.err_not_found()
    return success(bo)


@app.get("/bottler/brand-owners")
def list_brand_owners():
    require_roles("PlatformAdmin", "BrandOwnerAdmin", "BottlerOps")
    items = sorted_by_created(db.brand_owners.values())
    page, meta = paginate(items, request.args)
    return success(page, 200, meta)


# ================= territories =================

@app.post("/bottler/territories")
def create_territory():
    require_roles("PlatformAdmin")
    b = body()
    require_fields(b, "brand_owner_id", "code", "region_label")
    if b["brand_owner_id"] not in db.brand_owners:
        raise E.err_not_found("brand_owner_id not found")
    if not isinstance(b["code"], str) or not isinstance(b["region_label"], str):
        raise E.err_validation("code and region_label must be strings")
    if any(t["code"] == b["code"] for t in db.territories.values()):
        raise E.err_validation("Territory code must be unique")
    t = system_fields()
    t.update({"id": new_id(), "brand_owner_id": b["brand_owner_id"],
              "code": b["code"], "region_label": b["region_label"], "status": "OPEN"})
    db.territories[t["id"]] = t
    return success(t, 201)


@app.get("/bottler/territories/<tid>")
def get_territory(tid):
    require_roles("PlatformAdmin", "BrandOwnerAdmin", "BottlerOps")
    t = db.territories.get(tid)
    if not t:
        raise E.err_not_found()
    return success(t)


@app.get("/bottler/territories")
def list_territories():
    require_roles("PlatformAdmin", "BrandOwnerAdmin", "BottlerOps")
    items = list(db.territories.values())
    if "brand_owner_id" in request.args:
        items = [t for t in items if t["brand_owner_id"] == request.args["brand_owner_id"]]
    page, meta = paginate(sorted_by_created(items), request.args)
    return success(page, 200, meta)


# ================= bottler agreements =================

@app.post("/bottler/territories/<tid>/agreements")
def create_agreement(tid):
    require_roles("PlatformAdmin")
    t = db.territories.get(tid)
    if not t:
        raise E.err_not_found("territory not found")
    b = body()
    require_fields(b, "bottler_name", "concentrate_base_index", "marketing_accrual_basis",
                   "service_budget_cents")
    if b["marketing_accrual_basis"] not in ("CASE_VOLUME", "NET_REVENUE"):
        raise E.err_validation("marketing_accrual_basis must be CASE_VOLUME or NET_REVENUE")
    if not isinstance(b["service_budget_cents"], int) or isinstance(b["service_budget_cents"], bool):
        raise E.err_validation("service_budget_cents must be an integer")
    a = system_fields()
    a.update({
        "id": new_id(),
        "territory_id": tid,
        "bottler_name": b["bottler_name"],
        "concentrate_base_index": b["concentrate_base_index"],
        "marketing_accrual_basis": b["marketing_accrual_basis"],
        "status": "DRAFT",
        "marketing_fund_balance_cents": 0,
        "service_budget_cents": b["service_budget_cents"],
        "service_spent_cents": 0,
        "margin_ledger_cents": 0,
    })
    db.agreements[a["id"]] = a
    return success(a, 201)


@app.get("/bottler/territories/<tid>/agreements")
def list_agreements_of_territory(tid):
    require_roles("PlatformAdmin", "BrandOwnerAdmin", "BottlerOps")
    if tid not in db.territories:
        raise E.err_not_found("territory not found")
    items = [a for a in db.agreements.values() if a["territory_id"] == tid]
    page, meta = paginate(sorted_by_created(items), request.args)
    return success(page, 200, meta)


def _get_agreement_or_404(aid):
    a = db.agreements.get(aid)
    if not a:
        raise E.err_not_found("agreement not found")
    return a


@app.get("/bottler/bottler-agreements/<aid>")
def get_agreement(aid):
    require_roles("PlatformAdmin", "BrandOwnerAdmin", "BottlerOps")
    return success(_get_agreement_or_404(aid))


@app.post("/bottler/bottler-agreements/<aid>/activate")
def activate_agreement(aid):
    require_roles("PlatformAdmin")
    a = _get_agreement_or_404(aid)
    if a["status"] != "DRAFT":
        raise E.err_agreement_already_active()
    t = db.territories[a["territory_id"]]
    if any(o["territory_id"] == t["id"] and o["status"] == "ACTIVE" and o["id"] != aid
           for o in db.agreements.values()):
        raise E.err_territory_has_active()
    mandatory = [pl for pl in db.product_lines.values()
                 if pl["brand_owner_id"] == t["brand_owner_id"]
                 and pl["is_mandatory"] and pl["status"] == "ACTIVE"]
    if mandatory:
        has_index = any(i["brand_owner_id"] == t["brand_owner_id"]
                        for i in db.price_indices.values())
        if not has_index:
            raise E.err_line_obligation()
    a["status"] = "ACTIVE"
    touch(a)
    if t["status"] == "OPEN":
        t["status"] = "FRANCHISED"
        touch(t)
    return success(a)


@app.post("/bottler/bottler-agreements/<aid>/suspend")
def suspend_agreement(aid):
    require_roles("BrandOwnerAdmin")
    a = _get_agreement_or_404(aid)
    if a["status"] in ("TERMINATED", "REFRANCHISED"):
        raise E.err_already_terminal()
    if a["status"] != "ACTIVE":
        raise E.err_invalid_state("Agreement is not ACTIVE")
    a["status"] = "SUSPENDED"
    touch(a)
    return success(a)


@app.post("/bottler/bottler-agreements/<aid>/reinstate")
def reinstate_agreement(aid):
    require_roles("BrandOwnerAdmin")
    a = _get_agreement_or_404(aid)
    if a["status"] in ("TERMINATED", "REFRANCHISED"):
        raise E.err_already_terminal()
    if a["status"] != "SUSPENDED":
        raise E.err_invalid_state("Agreement is not SUSPENDED")
    a["status"] = "ACTIVE"
    touch(a)
    return success(a)


@app.post("/bottler/bottler-agreements/<aid>/terminate")
def terminate_agreement(aid):
    require_roles("BrandOwnerAdmin")
    a = _get_agreement_or_404(aid)
    if a["status"] in ("TERMINATED", "REFRANCHISED"):
        raise E.err_already_terminal()
    if a["status"] != "ACTIVE":
        raise E.err_invalid_state("Agreement is not ACTIVE")
    if any(c["agreement_id"] == aid and c["fulfillment_status"] == "PLACED"
           for c in db.cpos.values()):
        raise E.err_invalid_state("Agreement has open purchase orders")
    a["status"] = "TERMINATED"
    touch(a)
    t = db.territories[a["territory_id"]]
    t["status"] = "OPEN"
    touch(t)
    return success(a)


# ================= product lines =================

@app.post("/bottler/product-lines")
def create_product_line():
    require_roles("BrandOwnerAdmin")
    b = body()
    require_fields(b, "brand_owner_id", "line_code", "concentrate_base_price_per_gallon",
                   "is_mandatory")
    if b["brand_owner_id"] not in db.brand_owners:
        raise E.err_not_found("brand_owner_id not found")
    if not isinstance(b["is_mandatory"], bool):
        raise E.err_validation("is_mandatory must be a boolean")
    price = b["concentrate_base_price_per_gallon"]
    if isinstance(price, bool) or not isinstance(price, (int, float)):
        raise E.err_validation("concentrate_base_price_per_gallon must be a number")
    if price <= 0:
        raise E.err_validation("concentrate_base_price_per_gallon must be > 0")
    if any(pl["brand_owner_id"] == b["brand_owner_id"] and pl["line_code"] == b["line_code"]
           for pl in db.product_lines.values()):
        raise E.err_validation("line_code must be unique per brand owner")
    pl = system_fields()
    pl.update({
        "id": new_id(),
        "brand_owner_id": b["brand_owner_id"],
        "line_code": b["line_code"],
        "concentrate_base_price_per_gallon": price,
        "is_mandatory": b["is_mandatory"],
        "status": "ACTIVE",
    })
    db.product_lines[pl["id"]] = pl
    return success(pl, 201)


def _get_pl_or_404(pid):
    pl = db.product_lines.get(pid)
    if not pl:
        raise E.err_not_found("product line not found")
    return pl


@app.get("/bottler/product-lines/<pid>")
def get_product_line(pid):
    require_roles("PlatformAdmin", "BrandOwnerAdmin", "BottlerOps")
    return success(_get_pl_or_404(pid))


@app.get("/bottler/product-lines")
def list_product_lines():
    require_roles("PlatformAdmin", "BrandOwnerAdmin", "BottlerOps")
    items = list(db.product_lines.values())
    if "brand_owner_id" in request.args:
        items = [p for p in items if p["brand_owner_id"] == request.args["brand_owner_id"]]
    page, meta = paginate(sorted_by_created(items), request.args)
    return success(page, 200, meta)


@app.post("/bottler/product-lines/<pid>/retire")
def retire_product_line(pid):
    require_roles("BrandOwnerAdmin")
    pl = _get_pl_or_404(pid)
    if pl["status"] != "ACTIVE":
        raise E.err_invalid_state("Product line is not ACTIVE")
    pl["status"] = "RETIRED"
    touch(pl)
    return success(pl)


# ================= concentrate price indices =================

@app.post("/bottler/concentrate-price-indices")
def create_price_index():
    require_roles("BrandOwnerAdmin")
    b = body()
    require_fields(b, "brand_owner_id", "quarter", "index_value")
    if b["brand_owner_id"] not in db.brand_owners:
        raise E.err_not_found("brand_owner_id not found")
    val = b["index_value"]
    if isinstance(val, bool) or not isinstance(val, (int, float)):
        raise E.err_validation("index_value must be a number")
    if val <= 0:
        raise E.err_validation("index_value must be > 0")
    if any(i["brand_owner_id"] == b["brand_owner_id"] and i["quarter"] == b["quarter"]
           for i in db.price_indices.values()):
        raise E.err_index_duplicate()
    idx = append_only_fields()
    idx.update({
        "id": new_id(),
        "brand_owner_id": b["brand_owner_id"],
        "quarter": b["quarter"],
        "index_value": val,
    })
    db.price_indices[idx["id"]] = idx
    return success(idx, 201)


@app.get("/bottler/concentrate-price-indices/<iid>")
def get_price_index(iid):
    require_roles("PlatformAdmin", "BrandOwnerAdmin", "BottlerOps")
    idx = db.price_indices.get(iid)
    if not idx:
        raise E.err_not_found()
    return success(idx)


@app.get("/bottler/concentrate-price-indices")
def list_price_indices():
    require_roles("PlatformAdmin", "BrandOwnerAdmin", "BottlerOps")
    items = list(db.price_indices.values())
    if "brand_owner_id" in request.args:
        items = [i for i in items if i["brand_owner_id"] == request.args["brand_owner_id"]]
    if "quarter" in request.args:
        items = [i for i in items if i["quarter"] == request.args["quarter"]]
    page, meta = paginate(sorted_by_created(items), request.args)
    return success(page, 200, meta)


# ================= concentrate purchase orders =================

def _serialize_cpo(c):
    out = dict(c)
    for f in ("provisional_unit_price", "final_unit_price"):
        if out.get(f) is not None:
            out[f] = float(out[f])
    return out


@app.post("/bottler/concentrate-purchase-orders")
def create_cpo():
    role, uid = require_roles("BottlerOps")
    b = body()
    require_fields(b, "agreement_id", "product_line_id", "quantity_gallons",
                   "delivery_quarter")
    a = db.agreements.get(b["agreement_id"])
    if not a:
        raise E.err_not_found("agreement_id not found")
    if a["id"] != uid:
        raise E.err_unauthorized_role("BottlerOps identity does not match agreement")
    pl = db.product_lines.get(b["product_line_id"])
    if not pl:
        raise E.err_not_found("product_line_id not found")
    if a["status"] != "ACTIVE":
        raise E.err_agreement_not_active()
    if "expected_agreement_version" in b and b["expected_agreement_version"] is not None:
        if b["expected_agreement_version"] != a["version"]:
            raise E.err_stale_version()
    t = db.territories[a["territory_id"]]
    if pl["brand_owner_id"] != t["brand_owner_id"]:
        raise E.err_referential("Product line belongs to a different brand")
    qg = b["quantity_gallons"]
    if isinstance(qg, bool) or not isinstance(qg, int):
        raise E.err_validation("quantity_gallons must be an integer")
    if qg < 1000:
        raise E.err_min_order()
    unit, amount = provisional_price(pl, a, qg, b["delivery_quarter"])
    cpo = system_fields()
    cpo.update({
        "id": new_id(),
        "agreement_id": a["id"],
        "product_line_id": pl["id"],
        "quantity_gallons": qg,
        "delivery_quarter": b["delivery_quarter"],
        "fulfillment_status": "PLACED",
        "pricing_status": "PROVISIONAL",
        "provisional_unit_price": unit,
        "provisional_amount_cents": amount,
        "final_unit_price": None,
        "final_amount_cents": None,
        "price_delta_cents": None,
    })
    db.cpos[cpo["id"]] = cpo
    touch(a)  # placing a CPO increments the agreement version
    return success(_serialize_cpo(cpo), 201)


def _get_cpo_or_404(cid):
    c = db.cpos.get(cid)
    if not c:
        raise E.err_not_found("CPO not found")
    return c


@app.get("/bottler/concentrate-purchase-orders/<cid>")
def get_cpo(cid):
    require_roles("PlatformAdmin", "BrandOwnerAdmin", "BottlerOps")
    return success(_serialize_cpo(_get_cpo_or_404(cid)))


@app.get("/bottler/concentrate-purchase-orders")
def list_cpos():
    require_roles("PlatformAdmin", "BrandOwnerAdmin", "BottlerOps")
    items = list(db.cpos.values())
    if "agreement_id" in request.args:
        items = [c for c in items if c["agreement_id"] == request.args["agreement_id"]]
    if "product_line_id" in request.args:
        items = [c for c in items if c["product_line_id"] == request.args["product_line_id"]]
    page, meta = paginate(sorted_by_created(items), request.args)
    return success([_serialize_cpo(c) for c in page], 200, meta)


@app.post("/bottler/concentrate-purchase-orders/<cid>/receive")
def receive_cpo(cid):
    require_roles("BottlerOps")
    c = _get_cpo_or_404(cid)
    if c["fulfillment_status"] != "PLACED":
        raise E.err_invalid_state("CPO is not PLACED")
    c["fulfillment_status"] = "RECEIVED"
    touch(c)
    return success(_serialize_cpo(c))


@app.post("/bottler/concentrate-purchase-orders/<cid>/finalize")
def finalize_cpo(cid):
    require_roles("BottlerOps")
    c = _get_cpo_or_404(cid)
    if c["pricing_status"] == "FINALIZED":
        raise E.err_cpo_finalized()
    if c["fulfillment_status"] != "RECEIVED":
        raise E.err_invalid_state("CPO must be RECEIVED before finalize")
    a = db.agreements[c["agreement_id"]]
    pl = db.product_lines[c["product_line_id"]]
    unit, amount = final_price(pl, a, c["quantity_gallons"])
    c["final_unit_price"] = unit
    c["final_amount_cents"] = amount
    c["price_delta_cents"] = amount - c["provisional_amount_cents"]
    c["pricing_status"] = "FINALIZED"
    touch(c)
    return success(_serialize_cpo(c))


@app.post("/bottler/concentrate-purchase-orders/<cid>/cancel")
def cancel_cpo(cid):
    require_roles("BottlerOps")
    c = _get_cpo_or_404(cid)
    if c["pricing_status"] == "FINALIZED":
        raise E.err_cpo_finalized()
    if c["fulfillment_status"] != "PLACED":
        raise E.err_invalid_state("CPO is not PLACED")
    c["fulfillment_status"] = "CANCELLED"
    touch(c)
    return success(_serialize_cpo(c))


# ================= national customer agreements =================

def _windows_overlap(s1, e1, s2, e2):
    """Closed-interval overlap."""
    return s1 <= e2 and s2 <= e1


@app.post("/bottler/national-customer-agreements")
def create_nca():
    require_roles("BrandOwnerAdmin")
    b = body()
    require_fields(b, "brand_owner_id", "nca_code", "national_price_cents",
                   "effective_start", "effective_end")
    if b["brand_owner_id"] not in db.brand_owners:
        raise E.err_not_found("brand_owner_id not found")
    if isinstance(b["national_price_cents"], bool) or not isinstance(b["national_price_cents"], int):
        raise E.err_validation("national_price_cents must be an integer")
    if any(n["nca_code"] == b["nca_code"] for n in db.ncas.values()):
        raise E.err_validation("nca_code must be unique")
    n = system_fields()
    n.update({
        "id": new_id(),
        "brand_owner_id": b["brand_owner_id"],
        "nca_code": b["nca_code"],
        "national_price_cents": b["national_price_cents"],
        "effective_start": b["effective_start"],
        "effective_end": b["effective_end"],
        "status": "DRAFT",
    })
    db.ncas[n["id"]] = n
    return success(n, 201)


def _get_nca_or_404(nid):
    n = db.ncas.get(nid)
    if not n:
        raise E.err_not_found("NCA not found")
    return n


@app.get("/bottler/national-customer-agreements/<nid>")
def get_nca(nid):
    require_roles("PlatformAdmin", "BrandOwnerAdmin", "BottlerOps")
    return success(_get_nca_or_404(nid))


@app.get("/bottler/national-customer-agreements")
def list_ncas():
    require_roles("PlatformAdmin", "BrandOwnerAdmin", "BottlerOps")
    items = list(db.ncas.values())
    if "brand_owner_id" in request.args:
        items = [n for n in items if n["brand_owner_id"] == request.args["brand_owner_id"]]
    page, meta = paginate(sorted_by_created(items), request.args)
    return success(page, 200, meta)


@app.post("/bottler/national-customer-agreements/<nid>/publish")
def publish_nca(nid):
    require_roles("BrandOwnerAdmin")
    n = _get_nca_or_404(nid)
    if n["status"] not in ("DRAFT", "SUSPENDED"):
        if n["status"] == "EXPIRED":
            raise E.err_already_terminal()
        raise E.err_invalid_state("NCA cannot be published from its current state")
    for o in db.ncas.values():
        if o["id"] == nid:
            continue
        if o["brand_owner_id"] == n["brand_owner_id"] and o["status"] == "PUBLISHED":
            if _windows_overlap(n["effective_start"], n["effective_end"],
                                o["effective_start"], o["effective_end"]):
                raise E.err_nca_overlap()
    n["status"] = "PUBLISHED"
    touch(n)
    return success(n)


@app.post("/bottler/national-customer-agreements/<nid>/suspend")
def suspend_nca(nid):
    require_roles("BrandOwnerAdmin")
    n = _get_nca_or_404(nid)
    if n["status"] != "PUBLISHED":
        raise E.err_invalid_state("NCA is not PUBLISHED")
    n["status"] = "SUSPENDED"
    touch(n)
    return success(n)


@app.post("/bottler/national-customer-agreements/<nid>/expire")
def expire_nca(nid):
    require_roles("BrandOwnerAdmin")
    n = _get_nca_or_404(nid)
    if n["status"] == "EXPIRED":
        raise E.err_already_terminal()
    if n["status"] not in ("PUBLISHED", "SUSPENDED"):
        raise E.err_invalid_state("NCA cannot be expired from its current state")
    if clock_date() <= n["effective_end"]:
        raise E.err_invalid_state("Clock has not passed effective_end")
    n["status"] = "EXPIRED"
    touch(n)
    for c in db.customers.values():
        if c.get("nca_id") == nid:
            c["bound_price_cents"] = c["local_price_cents"]
            touch(c)
    return success(n)


# ================= customers =================

@app.post("/bottler/customers")
def create_customer():
    role, uid = require_roles("BottlerOps")
    b = body()
    require_fields(b, "agreement_id", "name", "channel", "local_price_cents")
    a = db.agreements.get(b["agreement_id"])
    if not a:
        raise E.err_not_found("agreement_id not found")
    if a["id"] != uid:
        raise E.err_unauthorized_role("BottlerOps identity does not match agreement")
    if b["channel"] not in ("RETAIL", "FOUNTAIN"):
        raise E.err_validation("channel must be RETAIL or FOUNTAIN")
    if isinstance(b["local_price_cents"], bool) or not isinstance(b["local_price_cents"], int):
        raise E.err_validation("local_price_cents must be an integer")
    c = system_fields()
    c.update({
        "id": new_id(),
        "agreement_id": a["id"],
        "nca_id": None,
        "name": b["name"],
        "channel": b["channel"],
        "local_price_cents": b["local_price_cents"],
        "bound_price_cents": b["local_price_cents"],
        "status": "ACTIVE",
    })
    db.customers[c["id"]] = c
    return success(c, 201)


def _get_customer_or_404(cid):
    c = db.customers.get(cid)
    if not c:
        raise E.err_not_found("Customer not found")
    return c


@app.get("/bottler/customers/<cid>")
def get_customer(cid):
    require_roles("PlatformAdmin", "BrandOwnerAdmin", "BottlerOps", "CustomerManager")
    return success(_get_customer_or_404(cid))


@app.get("/bottler/customers")
def list_customers():
    require_roles("PlatformAdmin", "BrandOwnerAdmin", "BottlerOps")
    items = list(db.customers.values())
    if "agreement_id" in request.args:
        items = [c for c in items if c["agreement_id"] == request.args["agreement_id"]]
    if "nca_id" in request.args:
        items = [c for c in items if c.get("nca_id") == request.args["nca_id"]]
    if "status" in request.args:
        items = [c for c in items if c["status"] == request.args["status"]]
    page, meta = paginate(sorted_by_created(items), request.args)
    return success(page, 200, meta)


@app.post("/bottler/customers/<cid>/enroll-nca")
def enroll_nca(cid):
    require_roles("BrandOwnerAdmin")
    c = _get_customer_or_404(cid)
    b = body()
    require_fields(b, "nca_id")
    n = db.ncas.get(b["nca_id"])
    if not n:
        raise E.err_not_found("nca_id not found")
    if n["status"] != "PUBLISHED":
        raise E.err_nca_not_published()
    if not price_band_ok(c["local_price_cents"], n["national_price_cents"]):
        raise E.err_price_band()
    c["nca_id"] = n["id"]
    c["bound_price_cents"] = n["national_price_cents"]
    touch(c)
    a = db.agreements[c["agreement_id"]]
    for o in db.dsd_orders.values():
        if o["customer_id"] == c["id"] and o["fulfillment_status"] == "BOOKED":
            old = o["invoice_total_cents"]
            new = compute_invoice_total(c, o["lines"])
            if new != old:
                o["invoice_total_cents"] = new
                touch(o)
                a["margin_ledger_cents"] += new - old
    return success(c)


@app.post("/bottler/customers/<cid>/dispute")
def dispute_customer(cid):
    role, uid = require_roles("CustomerManager")
    c = _get_customer_or_404(cid)
    if c["id"] != uid:
        raise E.err_unauthorized_role("CustomerManager identity does not match customer")
    if c["status"] != "ACTIVE":
        raise E.err_invalid_state("Customer is not ACTIVE")
    c["status"] = "DISPUTED"
    touch(c)
    return success(c)


@app.post("/bottler/customers/<cid>/resolve-dispute")
def resolve_dispute(cid):
    role, uid = require_roles("CustomerManager")
    c = _get_customer_or_404(cid)
    if c["id"] != uid:
        raise E.err_unauthorized_role("CustomerManager identity does not match customer")
    if c["status"] != "DISPUTED":
        raise E.err_invalid_state("Customer is not DISPUTED")
    c["status"] = "ACTIVE"
    touch(c)
    return success(c)


# ================= dsd orders =================

@app.post("/bottler/dsd-orders")
def create_dsd_order():
    role, uid = require_roles("CustomerManager", "BottlerOps")
    b = body()
    require_fields(b, "customer_id", "lines")
    c = db.customers.get(b["customer_id"])
    if not c:
        raise E.err_not_found("customer_id not found")
    if role == "CustomerManager":
        if c["id"] != uid:
            raise E.err_unauthorized_role("CustomerManager identity does not match customer")
    else:  # BottlerOps
        if c["agreement_id"] != uid:
            raise E.err_referential("Customer does not belong to the acting agreement")
    lines = b["lines"]
    if not isinstance(lines, list) or not lines:
        raise E.err_validation("lines must be a non-empty array")
    for line in lines:
        if not isinstance(line, dict):
            raise E.err_validation("each line must be an object")
        require_fields(line, "product_line_id", "quantity_cases", "discount_pct")
        if line["product_line_id"] not in db.product_lines:
            raise E.err_not_found("product_line_id not found")
        qc = line["quantity_cases"]
        if isinstance(qc, bool) or not isinstance(qc, int) or qc < 1:
            raise E.err_validation("quantity_cases must be an integer >= 1")
        dp = line["discount_pct"]
        if isinstance(dp, bool) or not isinstance(dp, (int, float)):
            raise E.err_validation("discount_pct must be a number")
        if dp < 0 or dp > 0.30:
            raise E.err_validation("discount_pct must be within [0, 0.30]")
    o = system_fields()
    o.update({
        "id": new_id(),
        "customer_id": c["id"],
        "lines": lines,
        "fulfillment_status": "BOOKED",
        "payment_status": "UNPAID",
        "invoice_total_cents": compute_invoice_total(c, lines),
    })
    db.dsd_orders[o["id"]] = o
    return success(o, 201)


def _get_order_or_404(oid):
    o = db.dsd_orders.get(oid)
    if not o:
        raise E.err_not_found("DSD order not found")
    return o


@app.get("/bottler/dsd-orders/<oid>")
def get_dsd_order(oid):
    require_roles("PlatformAdmin", "BrandOwnerAdmin", "BottlerOps", "CustomerManager")
    return success(_get_order_or_404(oid))


@app.get("/bottler/dsd-orders")
def list_dsd_orders():
    require_roles("PlatformAdmin", "BrandOwnerAdmin", "BottlerOps", "CustomerManager")
    items = list(db.dsd_orders.values())
    if "customer_id" in request.args:
        items = [o for o in items if o["customer_id"] == request.args["customer_id"]]
    page, meta = paginate(sorted_by_created(items), request.args)
    return success(page, 200, meta)


@app.post("/bottler/dsd-orders/<oid>/deliver")
def deliver_dsd_order(oid):
    require_roles("BottlerOps")
    o = _get_order_or_404(oid)
    if o["fulfillment_status"] != "BOOKED":
        raise E.err_invalid_state("Order is not BOOKED")
    c = db.customers[o["customer_id"]]
    if c["status"] == "DISPUTED":
        raise E.err_customer_disputed()
    o["fulfillment_status"] = "DELIVERED"
    touch(o)
    return success(o)


@app.post("/bottler/dsd-orders/<oid>/pay")
def pay_dsd_order(oid):
    require_roles("CustomerManager")
    o = _get_order_or_404(oid)
    if o["payment_status"] != "UNPAID":
        raise E.err_invalid_state("Order already PAID")
    if o["fulfillment_status"] != "DELIVERED":
        raise E.err_order_not_delivered()
    o["payment_status"] = "PAID"
    touch(o)
    return success(o)


@app.post("/bottler/dsd-orders/<oid>/void")
def void_dsd_order(oid):
    require_roles("BottlerOps")
    o = _get_order_or_404(oid)
    if o["fulfillment_status"] != "BOOKED":
        raise E.err_invalid_state("Order is not BOOKED")
    o["fulfillment_status"] = "VOIDED"
    touch(o)
    return success(o)


# ================= cold drink equipment + service windows =================

@app.post("/bottler/cold-drink-equipment")
def create_equipment():
    role, uid = require_roles("BottlerOps")
    b = body()
    require_fields(b, "agreement_id", "asset_tag")
    a = db.agreements.get(b["agreement_id"])
    if not a:
        raise E.err_not_found("agreement_id not found")
    if a["id"] != uid:
        raise E.err_unauthorized_role("BottlerOps identity does not match agreement")
    if any(e["asset_tag"] == b["asset_tag"] for e in db.equipment.values()):
        raise E.err_validation("asset_tag must be unique")
    eq = system_fields()
    eq.update({
        "id": new_id(),
        "agreement_id": a["id"],
        "asset_tag": b["asset_tag"],
        "customer_id": None,
        "placed_from": None,
        "placed_until": None,
        "status": "IN_WAREHOUSE",
        "placement_history": [],
    })
    db.equipment[eq["id"]] = eq
    return success(_serialize_equipment(eq), 201)


def _serialize_equipment(eq):
    out = {k: v for k, v in eq.items() if k != "placement_history"}
    return out


def _get_equipment_or_404(eid):
    eq = db.equipment.get(eid)
    if not eq:
        raise E.err_not_found("Equipment not found")
    return eq


@app.get("/bottler/cold-drink-equipment/<eid>")
def get_equipment(eid):
    require_roles("PlatformAdmin", "BrandOwnerAdmin", "BottlerOps", "FieldTechnician")
    return success(_serialize_equipment(_get_equipment_or_404(eid)))


@app.get("/bottler/cold-drink-equipment")
def list_equipment():
    require_roles("PlatformAdmin", "BrandOwnerAdmin", "BottlerOps", "FieldTechnician")
    items = list(db.equipment.values())
    if "agreement_id" in request.args:
        items = [e for e in items if e["agreement_id"] == request.args["agreement_id"]]
    if "customer_id" in request.args:
        items = [e for e in items if e.get("customer_id") == request.args["customer_id"]]
    page, meta = paginate(sorted_by_created(items), request.args)
    return success([_serialize_equipment(e) for e in page], 200, meta)


@app.post("/bottler/cold-drink-equipment/<eid>/place")
def place_equipment(eid):
    require_roles("BottlerOps")
    eq = _get_equipment_or_404(eid)
    b = body()
    require_fields(b, "customer_id", "placed_from", "placed_until")
    cust = db.customers.get(b["customer_id"])
    if not cust:
        raise E.err_not_found("customer_id not found")
    if eq["status"] != "IN_WAREHOUSE":
        raise E.err_equipment_not_in_warehouse()
    if cust["status"] != "ACTIVE":
        raise E.err_invalid_state("Customer is not ACTIVE")
    for hist in eq["placement_history"]:
        if _windows_overlap(b["placed_from"], b["placed_until"], hist[0], hist[1]):
            raise E.err_placement_overlap()
    eq["customer_id"] = b["customer_id"]
    eq["placed_from"] = b["placed_from"]
    eq["placed_until"] = b["placed_until"]
    eq["status"] = "PLACED"
    eq["placement_history"].append((b["placed_from"], b["placed_until"]))
    touch(eq)
    return success(_serialize_equipment(eq))


@app.post("/bottler/cold-drink-equipment/<eid>/uninstall")
def uninstall_equipment(eid):
    require_roles("BottlerOps")
    eq = _get_equipment_or_404(eid)
    if eq["status"] != "PLACED":
        raise E.err_invalid_state("Equipment is not PLACED")
    eq["customer_id"] = None
    eq["placed_from"] = None
    eq["placed_until"] = None
    eq["status"] = "IN_WAREHOUSE"
    touch(eq)
    return success(_serialize_equipment(eq))


@app.post("/bottler/cold-drink-equipment/<eid>/service-windows")
def create_service_window(eid):
    require_roles("FieldTechnician")
    eq = _get_equipment_or_404(eid)
    b = body()
    require_fields(b, "technician_label", "window_start", "window_end", "cost_cents")
    if eq["status"] not in ("PLACED", "UNDER_SERVICE"):
        raise E.err_invalid_state("Equipment is not PLACED")
    cost = b["cost_cents"]
    if isinstance(cost, bool) or not isinstance(cost, int) or cost < 0:
        raise E.err_validation("cost_cents must be an integer >= 0")
    ws = parse_iso(b["window_start"])
    we = parse_iso(b["window_end"])
    for w in db.service_windows.values():
        if w["technician_label"] == b["technician_label"]:
            ows = parse_iso(w["window_start"])
            owe = parse_iso(w["window_end"])
            if ws < owe and ows < we:  # half-open overlap; adjacency allowed
                raise E.err_window_overlap()
    a = db.agreements[eq["agreement_id"]]
    if a["service_spent_cents"] + cost > a["service_budget_cents"]:
        raise E.err_service_budget()
    w = append_only_fields()
    w.update({
        "id": new_id(),
        "equipment_id": eid,
        "technician_label": b["technician_label"],
        "window_start": b["window_start"],
        "window_end": b["window_end"],
        "cost_cents": cost,
    })
    db.service_windows[w["id"]] = w
    a["service_spent_cents"] += cost
    touch(a)
    if eq["status"] == "PLACED":
        eq["status"] = "UNDER_SERVICE"
        touch(eq)
    return success(w, 201)


@app.get("/bottler/cold-drink-equipment/<eid>/service-windows")
def list_service_windows(eid):
    require_roles("PlatformAdmin", "BrandOwnerAdmin", "BottlerOps", "FieldTechnician")
    _get_equipment_or_404(eid)
    items = [w for w in db.service_windows.values() if w["equipment_id"] == eid]
    page, meta = paginate(sorted_by_created(items), request.args)
    return success(page, 200, meta)


# ================= fountain accounts + syrup deliveries =================

@app.post("/bottler/fountain-accounts")
def create_fountain_account():
    require_roles("BottlerOps")
    b = body()
    require_fields(b, "customer_id")
    c = db.customers.get(b["customer_id"])
    if not c:
        raise E.err_not_found("customer_id not found")
    if c["channel"] != "FOUNTAIN":
        raise E.err_referential("Customer channel must be FOUNTAIN")
    fa = system_fields()
    fa.update({
        "id": new_id(),
        "customer_id": c["id"],
        "syrup_on_hand_gallons": 0,
        "maintenance_overdue": True,
        "last_maintenance_at": None,
    })
    db.fountain_accounts[fa["id"]] = fa
    return success(_serialize_fa(fa), 201)


def _serialize_fa(fa):
    return {k: v for k, v in fa.items() if k != "last_maintenance_at"}


def _get_fa_or_404(fid):
    fa = db.fountain_accounts.get(fid)
    if not fa:
        raise E.err_not_found("Fountain account not found")
    return fa


@app.get("/bottler/fountain-accounts/<fid>")
def get_fountain_account(fid):
    require_roles("PlatformAdmin", "BrandOwnerAdmin", "BottlerOps")
    fa = _get_fa_or_404(fid)
    refresh_fountain_overdue(fa)
    return success(_serialize_fa(fa))


@app.get("/bottler/fountain-accounts")
def list_fountain_accounts():
    require_roles("PlatformAdmin", "BrandOwnerAdmin", "BottlerOps")
    items = list(db.fountain_accounts.values())
    if "customer_id" in request.args:
        items = [f for f in items if f["customer_id"] == request.args["customer_id"]]
    for fa in items:
        refresh_fountain_overdue(fa)
    page, meta = paginate(sorted_by_created(items), request.args)
    return success([_serialize_fa(f) for f in page], 200, meta)


@app.post("/bottler/fountain-accounts/<fid>/syrup-deliveries")
def create_syrup_delivery(fid):
    require_roles("BottlerOps")
    fa = _get_fa_or_404(fid)
    b = body()
    require_fields(b, "gallons")
    g = b["gallons"]
    if isinstance(g, bool) or not isinstance(g, (int, float)):
        raise E.err_validation("gallons must be a number")
    if g <= 0:
        raise E.err_zero_quantity()
    refresh_fountain_overdue(fa)
    if fa["maintenance_overdue"]:
        raise E.err_maintenance_overdue()
    d = append_only_fields()
    d.update({
        "id": new_id(),
        "fountain_account_id": fid,
        "gallons": g,
        "delivered_at": get_clock(),
    })
    db.syrup_deliveries[d["id"]] = d
    fa["syrup_on_hand_gallons"] += g
    touch(fa)
    return success(d, 201)


@app.get("/bottler/fountain-accounts/<fid>/syrup-deliveries")
def list_syrup_deliveries(fid):
    require_roles("PlatformAdmin", "BrandOwnerAdmin", "BottlerOps")
    _get_fa_or_404(fid)
    items = [d for d in db.syrup_deliveries.values() if d["fountain_account_id"] == fid]
    page, meta = paginate(sorted_by_created(items), request.args)
    return success(page, 200, meta)


@app.post("/bottler/fountain-accounts/<fid>/maintenance")
def fountain_maintenance(fid):
    require_roles("FieldTechnician")
    fa = _get_fa_or_404(fid)
    fa["last_maintenance_at"] = get_clock()
    fa["maintenance_overdue"] = False
    touch(fa)
    return success(_serialize_fa(fa))


# ================= territory transfers =================

@app.post("/bottler/territory-transfers")
def create_transfer():
    require_roles("PlatformAdmin")
    b = body()
    require_fields(b, "territory_id", "buyer_name", "reported_ebitda_cents")
    if b["territory_id"] not in db.territories:
        raise E.err_not_found("territory_id not found")
    ebitda = b["reported_ebitda_cents"]
    if isinstance(ebitda, bool) or not isinstance(ebitda, int) or ebitda <= 0:
        raise E.err_validation("reported_ebitda_cents must be an integer > 0")
    tr = system_fields()
    tr.update({
        "id": new_id(),
        "territory_id": b["territory_id"],
        "buyer_name": b["buyer_name"],
        "reported_ebitda_cents": ebitda,
        "valuation_cents": None,
        "valuation_round": 0,
        "status": "PROPOSED",
    })
    db.transfers[tr["id"]] = tr
    return success(tr, 201)


def _get_transfer_or_404(tid):
    tr = db.transfers.get(tid)
    if not tr:
        raise E.err_not_found("Transfer not found")
    return tr


@app.get("/bottler/territory-transfers/<tid>")
def get_transfer(tid):
    require_roles("PlatformAdmin", "BrandOwnerAdmin")
    return success(_get_transfer_or_404(tid))


@app.get("/bottler/territory-transfers")
def list_transfers():
    require_roles("PlatformAdmin", "BrandOwnerAdmin")
    items = list(db.transfers.values())
    if "territory_id" in request.args:
        items = [t for t in items if t["territory_id"] == request.args["territory_id"]]
    page, meta = paginate(sorted_by_created(items), request.args)
    return success(page, 200, meta)


@app.post("/bottler/territory-transfers/<tid>/valuate")
def valuate_transfer(tid):
    require_roles("BrandOwnerAdmin")
    tr = _get_transfer_or_404(tid)
    b = body()
    if "expected_transfer_version" in b and b["expected_transfer_version"] is not None:
        if b["expected_transfer_version"] != tr["version"]:
            raise E.err_stale_version()
    if tr["status"] in ("EXECUTED", "REJECTED"):
        raise E.err_already_terminal()
    if tr["status"] not in ("PROPOSED", "NEGOTIATING"):
        raise E.err_invalid_state("Transfer cannot be valuated from its current state")
    tr["valuation_cents"] = compute_valuation(tr["reported_ebitda_cents"])
    tr["valuation_round"] += 1
    tr["status"] = "VALUED"
    touch(tr)
    return success(tr)


@app.post("/bottler/territory-transfers/<tid>/counter")
def counter_transfer(tid):
    require_roles("PlatformAdmin")
    tr = _get_transfer_or_404(tid)
    if tr["status"] != "VALUED":
        raise E.err_invalid_state("Transfer is not VALUED")
    tr["status"] = "NEGOTIATING"
    touch(tr)
    return success(tr)


@app.post("/bottler/territory-transfers/<tid>/approve")
def approve_transfer(tid):
    require_roles("BrandOwnerAdmin")
    tr = _get_transfer_or_404(tid)
    if tr["status"] != "VALUED":
        raise E.err_invalid_state("Transfer is not VALUED")
    current = [a for a in db.agreements.values()
               if a["territory_id"] == tr["territory_id"] and a["status"] == "ACTIVE"]
    if current:
        aid = current[0]["id"]
        if any(c["agreement_id"] == aid and c["status"] == "DISPUTED"
               for c in db.customers.values()):
            raise E.err_transfer_disputed()
    tr["status"] = "APPROVED"
    touch(tr)
    return success(tr)


@app.post("/bottler/territory-transfers/<tid>/execute")
def execute_transfer(tid):
    require_roles("PlatformAdmin")
    tr = _get_transfer_or_404(tid)
    if tr["status"] != "APPROVED":
        raise E.err_invalid_state("Transfer is not APPROVED")
    territory = db.territories[tr["territory_id"]]
    prior = None
    for a in db.agreements.values():
        if a["territory_id"] == tr["territory_id"] and a["status"] == "ACTIVE":
            prior = a
            break
    successor = system_fields()
    successor.update({
        "id": new_id(),
        "territory_id": tr["territory_id"],
        "bottler_name": tr["buyer_name"],
        "concentrate_base_index": prior["concentrate_base_index"] if prior else None,
        "marketing_accrual_basis": prior["marketing_accrual_basis"] if prior else "CASE_VOLUME",
        "status": "ACTIVE",
        "marketing_fund_balance_cents": 0,
        "service_budget_cents": prior["service_budget_cents"] if prior else 0,
        "service_spent_cents": 0,
        "margin_ledger_cents": 0,
    })
    db.agreements[successor["id"]] = successor
    if prior:
        prior["status"] = "REFRANCHISED"
        touch(prior)
        for c in db.customers.values():
            if c["agreement_id"] == prior["id"]:
                c["agreement_id"] = successor["id"]
                touch(c)
        for eq in db.equipment.values():
            if eq["agreement_id"] == prior["id"]:
                eq["agreement_id"] = successor["id"]
                touch(eq)
    territory["status"] = "REFRANCHISED"
    touch(territory)
    tr["status"] = "EXECUTED"
    touch(tr)
    return success(tr)


@app.post("/bottler/territory-transfers/<tid>/reject")
def reject_transfer(tid):
    require_roles("BrandOwnerAdmin")
    tr = _get_transfer_or_404(tid)
    if tr["status"] in ("EXECUTED", "REJECTED"):
        raise E.err_already_terminal()
    tr["status"] = "REJECTED"
    touch(tr)
    return success(tr)


# ================= innovation launches =================

@app.post("/bottler/innovation-launches")
def create_launch():
    require_roles("BrandOwnerAdmin")
    b = body()
    require_fields(b, "agreement_id", "product_line_id", "committed_cases",
                   "launch_start", "launch_end")
    a = db.agreements.get(b["agreement_id"])
    if not a:
        raise E.err_not_found("agreement_id not found")
    pl = db.product_lines.get(b["product_line_id"])
    if not pl:
        raise E.err_not_found("product_line_id not found")
    t = db.territories[a["territory_id"]]
    if pl["brand_owner_id"] != t["brand_owner_id"]:
        raise E.err_referential("Product line belongs to a different brand")
    cc = b["committed_cases"]
    if isinstance(cc, bool) or not isinstance(cc, int) or cc <= 0:
        raise E.err_validation("committed_cases must be an integer > 0")
    l = system_fields()
    l.update({
        "id": new_id(),
        "agreement_id": a["id"],
        "product_line_id": pl["id"],
        "committed_cases": cc,
        "launch_start": b["launch_start"],
        "launch_end": b["launch_end"],
        "cases_sold": 0,
        "changeover_completed": False,
        "penalty_cents": None,
        "status": "PLANNED",
    })
    db.launches[l["id"]] = l
    return success(l, 201)


def _get_launch_or_404(lid):
    l = db.launches.get(lid)
    if not l:
        raise E.err_not_found("Launch not found")
    return l


@app.get("/bottler/innovation-launches/<lid>")
def get_launch(lid):
    require_roles("PlatformAdmin", "BrandOwnerAdmin", "BottlerOps")
    return success(_get_launch_or_404(lid))


@app.get("/bottler/innovation-launches")
def list_launches():
    require_roles("PlatformAdmin", "BrandOwnerAdmin", "BottlerOps")
    items = list(db.launches.values())
    if "agreement_id" in request.args:
        items = [l for l in items if l["agreement_id"] == request.args["agreement_id"]]
    if "product_line_id" in request.args:
        items = [l for l in items if l["product_line_id"] == request.args["product_line_id"]]
    page, meta = paginate(sorted_by_created(items), request.args)
    return success(page, 200, meta)


@app.post("/bottler/innovation-launches/<lid>/schedule-changeover")
def schedule_changeover(lid):
    require_roles("BottlerOps")
    l = _get_launch_or_404(lid)
    if l["status"] != "PLANNED":
        raise E.err_invalid_state("Launch is not PLANNED")
    pl = db.product_lines[l["product_line_id"]]
    if pl["status"] != "ACTIVE":
        raise E.err_launch_product_inactive()
    a = db.agreements[l["agreement_id"]]
    if a["status"] != "ACTIVE":
        raise E.err_agreement_not_active()
    l["status"] = "CHANGEOVER_SCHEDULED"
    touch(l)
    return success(l)


@app.post("/bottler/innovation-launches/<lid>/complete-changeover")
def complete_changeover(lid):
    require_roles("BottlerOps")
    l = _get_launch_or_404(lid)
    if l["status"] != "CHANGEOVER_SCHEDULED":
        raise E.err_invalid_state("Launch is not CHANGEOVER_SCHEDULED")
    l["changeover_completed"] = True
    l["status"] = "IN_PRODUCTION"
    touch(l)
    return success(l)


@app.post("/bottler/innovation-launches/<lid>/record-sales")
def record_sales(lid):
    require_roles("BottlerOps")
    l = _get_launch_or_404(lid)
    b = body()
    require_fields(b, "cases")
    cases = b["cases"]
    if isinstance(cases, bool) or not isinstance(cases, int):
        raise E.err_validation("cases must be an integer")
    if cases <= 0:
        raise E.err_zero_quantity()
    l["cases_sold"] += cases
    touch(l)
    return success(l)


@app.post("/bottler/innovation-launches/<lid>/review-commitment")
def review_commitment(lid):
    require_roles("BrandOwnerAdmin")
    l = _get_launch_or_404(lid)
    if l["status"] in ("MET", "PENALIZED"):
        raise E.err_already_terminal()
    if l["status"] not in ("IN_PRODUCTION", "EXTENDED"):
        raise E.err_invalid_state("Launch cannot be reviewed from its current state")
    if clock_date() <= l["launch_end"]:
        raise E.err_commitment_window_open()
    a = db.agreements[l["agreement_id"]]
    if l["cases_sold"] >= l["committed_cases"]:
        l["penalty_cents"] = 0
        l["status"] = "MET"
    else:
        penalty = compute_penalty(l["committed_cases"], l["cases_sold"])
        l["penalty_cents"] = penalty
        l["status"] = "PENALIZED"
        a["margin_ledger_cents"] -= penalty
        touch(a)
    touch(l)
    return success(l)


# ================= marketing fund ledger =================

from decimal import Decimal, ROUND_HALF_UP

PER_CASE_RATE = 40
REVENUE_PCT = Decimal("0.025")


@app.post("/bottler/marketing-fund-ledger")
def create_fund_entry():
    role, uid = require_roles("BottlerOps", "BrandOwnerAdmin")
    b = body()
    require_fields(b, "agreement_id", "entry_type", "period")
    a = db.agreements.get(b["agreement_id"])
    if not a:
        raise E.err_not_found("agreement_id not found")
    if role == "BottlerOps" and a["id"] != uid:
        raise E.err_unauthorized_role("BottlerOps identity does not match agreement")
    et = b["entry_type"]
    if et not in ("ACCRUAL", "DISBURSEMENT", "CLAWBACK"):
        raise E.err_validation("entry_type must be ACCRUAL, DISBURSEMENT, or CLAWBACK")
    entry = append_only_fields()
    entry.update({
        "id": new_id(),
        "agreement_id": a["id"],
        "entry_type": et,
        "period": b["period"],
        "cases_sold": b.get("cases_sold"),
        "net_revenue_cents": b.get("net_revenue_cents"),
        "requested_amount_cents": b.get("requested_amount_cents"),
        "reference_entry_id": b.get("reference_entry_id"),
    })
    if et == "ACCRUAL":
        if a["marketing_accrual_basis"] == "CASE_VOLUME":
            cs = b.get("cases_sold")
            if not isinstance(cs, int) or isinstance(cs, bool):
                raise E.err_validation("cases_sold is required for CASE_VOLUME accrual")
            amount = cs * PER_CASE_RATE
        else:
            nr = b.get("net_revenue_cents")
            if not isinstance(nr, int) or isinstance(nr, bool):
                raise E.err_validation("net_revenue_cents is required for NET_REVENUE accrual")
            amount = int((Decimal(nr) * REVENUE_PCT).quantize(Decimal("1"), rounding=ROUND_HALF_UP))
        a["marketing_fund_balance_cents"] += amount
    elif et == "DISBURSEMENT":
        ra = b.get("requested_amount_cents")
        if not isinstance(ra, int) or isinstance(ra, bool) or ra <= 0:
            raise E.err_validation("requested_amount_cents must be an integer > 0")
        if ra > a["marketing_fund_balance_cents"]:
            raise E.err_fund_insufficient()
        amount = ra
        a["marketing_fund_balance_cents"] -= amount
    else:  # CLAWBACK
        ra = b.get("requested_amount_cents")
        if not isinstance(ra, int) or isinstance(ra, bool) or ra <= 0:
            raise E.err_validation("requested_amount_cents must be an integer > 0")
        ref_id = b.get("reference_entry_id")
        if not ref_id:
            raise E.err_validation("reference_entry_id is required for CLAWBACK")
        ref = db.fund_entries.get(ref_id)
        if not ref or ref["agreement_id"] != a["id"] or ref["entry_type"] != "ACCRUAL":
            raise E.err_referential("reference_entry_id must reference an ACCRUAL of the same agreement")
        if ra > ref["amount_cents"]:
            raise E.err_clawback_exceeds()
        amount = ra
        a["marketing_fund_balance_cents"] -= amount
    entry["amount_cents"] = amount
    db.fund_entries[entry["id"]] = entry
    touch(a)
    return success(entry, 201)


@app.get("/bottler/marketing-fund-ledger/<eid>")
def get_fund_entry(eid):
    require_roles("PlatformAdmin", "BrandOwnerAdmin", "BottlerOps")
    e = db.fund_entries.get(eid)
    if not e:
        raise E.err_not_found("Fund entry not found")
    return success(e)


@app.get("/bottler/marketing-fund-ledger")
def list_fund_entries():
    require_roles("PlatformAdmin", "BrandOwnerAdmin", "BottlerOps")
    items = list(db.fund_entries.values())
    if "agreement_id" in request.args:
        items = [e for e in items if e["agreement_id"] == request.args["agreement_id"]]
    if "reference_entry_id" in request.args:
        items = [e for e in items if e.get("reference_entry_id") == request.args["reference_entry_id"]]
    page, meta = paginate(sorted_by_created(items), request.args)
    return success(page, 200, meta)


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", "10000")))
