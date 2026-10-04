"""Cookie Program API — Flask application."""
import os

from flask import Flask, request

import db
from clock import clock, parse_dt
from errors import ApiError, raise_err
from logic import (
    ALLERGEN_TAGS, account_json, account_uncollected, active_recall_covers,
    agreement_json, agreement_outstanding, check_auto_selling, digital_order_json,
    find_account, find_or_404, get_body, incentive_tier, line_json, location_json,
    new_record, opt_dt, opt_int, opt_str, order_json, po_json, product_json,
    recall_json, req_bool, req_dt, req_enum, req_int, req_str, request_json,
    season_avg_unit_price, season_counters, season_json, site_json, slot_json,
    touch, transfer_json, troop_json,
)
from response import err as err_response, ok, paginate

app = Flask(__name__)

ADMIN = "CouncilAdmin"
LEADER = "TroopLeader"
ROLES = {ADMIN, LEADER}

# ---------------------------------------------------------------------------
# auth + error handling
# ---------------------------------------------------------------------------


@app.before_request
def authenticate():
    if not request.path.startswith("/cookie-program"):
        return None
    role = request.headers.get("X-User-Role")
    uid = request.headers.get("X-User-ID")
    if role is None or role not in ROLES or uid is None or uid == "":
        return err_response("ERR_UNAUTHENTICATED",
                            "missing or invalid X-User-Role / X-User-ID headers",
                            401)
    request.user_role = role
    request.user_id = uid
    return None


@app.errorhandler(ApiError)
def handle_api_error(e):
    return err_response(e.error_id, e.message, e.http_status)


@app.errorhandler(404)
def handle_404(e):
    return err_response("ERR_NOT_FOUND", "resource not found", 404)


@app.errorhandler(405)
def handle_405(e):
    return err_response("ERR_NOT_FOUND", "resource not found", 404)


@app.errorhandler(Exception)
def handle_exception(e):
    import traceback
    traceback.print_exc()
    return err_response("ERR_INVALID_REQUEST", str(e), 400)


def require_roles(*roles):
    if request.user_role not in roles:
        raise_err("ERR_UNAUTHORIZED", "role not permitted for this endpoint")


def acting_troop():
    """The troop id of the acting TroopLeader, or None for CouncilAdmin."""
    if request.user_role == LEADER:
        return request.user_id
    return None


# ---------------------------------------------------------------------------
# clock
# ---------------------------------------------------------------------------


@app.post("/cookie-program/_clock/set_current_utc")
def set_clock():
    require_roles(ADMIN)
    body = get_body()
    to = req_str(body, "to_iso8601")
    try:
        clock.set(to)
    except Exception:
        raise_err("ERR_INVALID_REQUEST", "invalid to_iso8601")
    for season in db.all_recs("seasons"):
        check_auto_selling(season)
    return ok({"current_utc": clock.now_iso_seconds()})


# ---------------------------------------------------------------------------
# seasons
# ---------------------------------------------------------------------------


@app.post("/cookie-program/seasons")
def create_season():
    require_roles(ADMIN)
    body = get_body()
    code = req_str(body, "code")
    name = req_str(body, "name")
    opens = req_dt(body, "ordering_opens_at")
    closes = req_dt(body, "ordering_closes_at")
    for s in db.all_recs("seasons"):
        if s["code"] == code:
            raise_err("ERR_INVALID_REQUEST", f"duplicate season code: {code}")
    season = new_record("seasons", {
        "code": code,
        "name": name,
        "status": "DRAFT",
        "ordering_opens_at": opens,
        "ordering_closes_at": closes,
        "ordering_opens_at_raw": body["ordering_opens_at"],
        "ordering_closes_at_raw": body["ordering_closes_at"],
    })
    return ok(season_json(season), status=201)


@app.get("/cookie-program/seasons")
def list_seasons():
    require_roles(ADMIN, LEADER)
    items = db.all_recs("seasons")
    status = request.args.get("status")
    if status is not None:
        items = [s for s in items if s["status"] == status]
    page, pg = paginate(items)
    return ok([season_json(s) for s in page], response_type="array", pagination=pg)


@app.get("/cookie-program/seasons/<seasonId>")
def get_season(seasonId):
    require_roles(ADMIN, LEADER)
    season = find_or_404("seasons", seasonId, "season")
    return ok(season_json(season))


@app.post("/cookie-program/seasons/<seasonId>/open")
def open_season(seasonId):
    require_roles(ADMIN)
    season = find_or_404("seasons", seasonId, "season")
    if season["status"] != "DRAFT":
        raise_err("ERR_SEASON_INVALID_STATE", "season is not DRAFT")
    prods = [p for p in db.all_recs("products") if p["season_id"] == seasonId]
    if not prods:
        raise_err("ERR_PRODUCT_CATALOG_EMPTY", "season has no products")
    season["status"] = "OPEN"
    touch(season)
    check_auto_selling(season)
    return ok(season_json(season))


@app.post("/cookie-program/seasons/<seasonId>/cancel")
def cancel_season(seasonId):
    require_roles(ADMIN)
    season = find_or_404("seasons", seasonId, "season")
    if season["status"] != "DRAFT":
        raise_err("ERR_SEASON_INVALID_STATE", "season is not DRAFT")
    season["status"] = "CANCELLED"
    touch(season)
    return ok(season_json(season))


@app.post("/cookie-program/seasons/<seasonId>/begin-reconciliation")
def begin_reconciliation(seasonId):
    require_roles(ADMIN)
    season = find_or_404("seasons", seasonId, "season")
    if season["status"] != "SELLING":
        raise_err("ERR_SEASON_INVALID_STATE", "season is not SELLING")
    for t in db.all_recs("transfers"):
        if (t["season_id"] == seasonId and t["status"] in
                ("REQUESTED", "SHIPPER_SIGNED", "RECEIVER_SIGNED")):
            raise_err("ERR_TRANSFER_IN_FLIGHT",
                      "season has non-terminal transfers")
    for r in db.all_recs("requests"):
        slot = db.get("slots", r["slot_id"])
        if not slot:
            continue
        loc = db.get("locations", slot["location_id"])
        if loc and loc["season_id"] == seasonId and r["status"] == "PENDING":
            raise_err("ERR_BOOTH_REQUEST_PENDING",
                      "season has PENDING booth requests")
    season["status"] = "RECONCILIATION"
    touch(season)
    return ok(season_json(season))


@app.post("/cookie-program/seasons/<seasonId>/close-out")
def close_out_season(seasonId):
    require_roles(ADMIN)
    season = find_or_404("seasons", seasonId, "season")
    if season["status"] != "RECONCILIATION":
        raise_err("ERR_SEASON_INVALID_STATE", "season is not RECONCILIATION")
    # guard: uncollected amounts with non-forfeited agreements (PRD §3.9:
    # block when uncollected is non-zero AND any PENDING agreement is not
    # already FORFEITED; DISPUTED-only accounts pass and are swept below).
    for account in db.all_recs("accounts"):
        if account["season_id"] != seasonId:
            continue
        if account_uncollected(account) == 0:
            continue
        has_pending = any(
            ag["troop_id"] == account["troop_id"]
            and ag["season_id"] == account["season_id"]
            and ag["status"] == "PENDING"
            for ag in db.all_recs("agreements")
        )
        if has_pending:
            raise_err("ERR_UNRESOLVED_UNCOLLECTED",
                      "account has unresolved uncollected amounts")
    for r in db.all_recs("recalls"):
        if r["season_id"] == seasonId and r["status"] == "DRAFT":
            raise_err("ERR_RECALL_DRAFT_OPEN", "season has a DRAFT recall")

    # 1) forfeiture sweep
    forfeited = 0
    for ag in db.all_recs("agreements"):
        if ag["season_id"] != seasonId:
            continue
        if ag["status"] in ("PENDING", "DISPUTED"):
            account = find_account(ag["troop_id"], seasonId)
            if account is not None:
                account["balance_cents"] += ag["outstanding_cents"]
                touch(account)
            ag["status"] = "FORFEITED"
            touch(ag)
            forfeited += 1

    # 2) proceeds waterfall
    settled_accounts = 0
    total_offset = 0
    for account in db.all_recs("accounts"):
        if account["season_id"] != seasonId:
            continue
        gross = account["proceeds_accrued_cents"]
        balance_offset = min(gross, max(account["balance_cents"], 0))
        account["balance_cents"] -= balance_offset
        account["proceeds_payable_cents"] = gross - balance_offset
        total_offset += balance_offset
        settled_accounts += 1
        touch(account)

    # 3) unsold donation sweep (computed)
    donated = 0
    for p in db.all_recs("products"):
        if p["season_id"] != seasonId:
            continue
        purchased = sum(
            po["quantity"] for po in db.all_recs("pos")
            if po["season_id"] == seasonId and po["product_id"] == p["id"]
            and po["status"] in ("ORDERED", "PARTIALLY_DELIVERED", "DELIVERED"))
        committed = 0
        for o in db.all_recs("orders"):
            if o["season_id"] != seasonId or o["status"] not in (
                    "CONFIRMED", "FULFILLED"):
                continue
            for line in db.all_recs("lines"):
                if line["order_id"] == o["id"] and line["product_id"] == p["id"]:
                    committed += line["package_qty"]
        digital = 0
        for do in db.all_recs("digital_orders"):
            if do["season_id"] != seasonId:
                continue
            if do["fulfillment_status"] != "DELIVERED":
                continue
            for item in do["items"]:
                if item["product_id"] == p["id"]:
                    digital += item["package_qty"]
        unsold = purchased - committed - digital
        if unsold > 0:
            donated += unsold

    season["status"] = "CLOSED"
    touch(season)
    return ok({
        "settled_accounts": settled_accounts,
        "total_proceeds_offset_cents": total_offset,
        "donated_unsold_units": donated,
        "forfeited_agreements": forfeited,
    })


# ---------------------------------------------------------------------------
# products
# ---------------------------------------------------------------------------


@app.post("/cookie-program/seasons/<seasonId>/products")
def create_product(seasonId):
    require_roles(ADMIN)
    season = find_or_404("seasons", seasonId, "season")
    body = get_body()
    variety_code = req_str(body, "variety_code")
    name = req_str(body, "name")
    unit_price = req_int(body, "unit_price_cents")
    proceeds = req_int(body, "troop_proceeds_cents")
    tags = body.get("allergen_tags", [])
    if not isinstance(tags, list) or any(t not in ALLERGEN_TAGS for t in tags):
        raise_err("ERR_INVALID_REQUEST", "invalid allergen_tags")
    ppc = opt_int(body, "packages_per_case", 12)
    if ppc < 1:
        raise_err("ERR_INVALID_REQUEST", "packages_per_case must be >= 1")
    if unit_price < 1:
        raise_err("ERR_INVALID_REQUEST", "unit_price_cents must be >= 1")
    for p in db.all_recs("products"):
        if p["season_id"] == seasonId and p["variety_code"] == variety_code:
            raise_err("ERR_INVALID_REQUEST",
                      f"duplicate variety_code in season: {variety_code}")
    # fiscal guard (priority 12)
    if not (0 < proceeds < unit_price):
        raise_err("ERR_FISCAL_VIOLATION",
                  "troop_proceeds_cents must satisfy 0 < proceeds < unit_price")
    product = new_record("products", {
        "season_id": seasonId,
        "variety_code": variety_code,
        "name": name,
        "unit_price_cents": unit_price,
        "troop_proceeds_cents": proceeds,
        "allergen_tags": tags,
        "packages_per_case": ppc,
    })
    return ok(product_json(product), status=201)


@app.get("/cookie-program/seasons/<seasonId>/products")
def list_season_products(seasonId):
    require_roles(ADMIN, LEADER)
    find_or_404("seasons", seasonId, "season")
    items = [p for p in db.all_recs("products") if p["season_id"] == seasonId]
    page, pg = paginate(items)
    return ok([product_json(p) for p in page], response_type="array", pagination=pg)


@app.get("/cookie-program/products/<productId>")
def get_product(productId):
    require_roles(ADMIN, LEADER)
    p = find_or_404("products", productId, "product")
    return ok(product_json(p))


@app.get("/cookie-program/products")
def list_products():
    require_roles(ADMIN, LEADER)
    items = db.all_recs("products")
    sid = request.args.get("season_id")
    if sid is not None:
        items = [p for p in items if p["season_id"] == sid]
    page, pg = paginate(items)
    return ok([product_json(p) for p in page], response_type="array", pagination=pg)


# ---------------------------------------------------------------------------
# troops
# ---------------------------------------------------------------------------


@app.post("/cookie-program/troops")
def create_troop():
    require_roles(ADMIN)
    body = get_body()
    number = req_str(body, "troop_number")
    name = req_str(body, "name")
    su = req_str(body, "service_unit")
    for t in db.all_recs("troops"):
        if t["troop_number"] == number:
            raise_err("ERR_INVALID_REQUEST", f"duplicate troop_number: {number}")
    troop = new_record("troops", {
        "troop_number": number,
        "name": name,
        "status": "ACTIVE",
        "service_unit": su,
    })
    return ok(troop_json(troop), status=201)


@app.get("/cookie-program/troops/<troopId>")
def get_troop(troopId):
    require_roles(ADMIN, LEADER)
    t = find_or_404("troops", troopId, "troop")
    return ok(troop_json(t))


# ---------------------------------------------------------------------------
# accounts
# ---------------------------------------------------------------------------


@app.post("/cookie-program/seasons/<seasonId>/accounts")
def create_account(seasonId):
    require_roles(ADMIN)
    find_or_404("seasons", seasonId, "season")
    body = get_body()
    troop_id = req_str(body, "troop_id")
    find_or_404("troops", troop_id, "troop")
    if find_account(troop_id, seasonId) is not None:
        raise_err("ERR_INVALID_REQUEST", "account already exists for troop+season")
    account = new_record("accounts", {
        "troop_id": troop_id,
        "season_id": seasonId,
        "balance_cents": 0,
        "proceeds_accrued_cents": 0,
        "deposit_cents": 0,
    })
    return ok(account_json(account), status=201)


@app.get("/cookie-program/seasons/<seasonId>/accounts")
def list_season_accounts(seasonId):
    require_roles(ADMIN, LEADER)
    find_or_404("seasons", seasonId, "season")
    items = [a for a in db.all_recs("accounts") if a["season_id"] == seasonId]
    tid = request.args.get("troop_id")
    if tid is not None:
        items = [a for a in items if a["troop_id"] == tid]
    page, pg = paginate(items)
    return ok([account_json(a) for a in page], response_type="array", pagination=pg)


@app.get("/cookie-program/accounts")
def list_accounts():
    require_roles(ADMIN, LEADER)
    items = db.all_recs("accounts")
    tid = request.args.get("troop_id")
    sid = request.args.get("season_id")
    if tid is not None:
        items = [a for a in items if a["troop_id"] == tid]
    if sid is not None:
        items = [a for a in items if a["season_id"] == sid]
    page, pg = paginate(items)
    return ok([account_json(a) for a in page], response_type="array", pagination=pg)


@app.get("/cookie-program/accounts/<accountId>")
def get_account(accountId):
    require_roles(ADMIN, LEADER)
    a = find_or_404("accounts", accountId, "account")
    return ok(account_json(a))


@app.post("/cookie-program/accounts/<accountId>/deposits")
def record_deposit(accountId):
    require_roles(LEADER, ADMIN)
    account = find_or_404("accounts", accountId, "account")
    if request.user_role == LEADER and account["troop_id"] != request.user_id:
        raise_err("ERR_FORBIDDEN_OWNERSHIP", "account belongs to another troop")
    body = get_body()
    amount = req_int(body, "amount_cents")
    reference = req_str(body, "reference")
    if amount < 1:
        raise_err("ERR_INVALID_REQUEST", "amount_cents must be >= 1")
    account["deposit_cents"] += amount
    account["balance_cents"] -= amount
    touch(account)
    return ok(account_json(account), status=201)


# ---------------------------------------------------------------------------
# orders + lines
# ---------------------------------------------------------------------------


@app.post("/cookie-program/seasons/<seasonId>/orders")
def create_order(seasonId):
    require_roles(LEADER)
    find_or_404("seasons", seasonId, "season")
    body = get_body()
    troop_id = req_str(body, "troop_id")
    kind = req_enum(body, "kind", {"INITIAL", "REPLENISHMENT"})
    find_or_404("troops", troop_id, "troop")
    if troop_id != request.user_id:
        raise_err("ERR_FORBIDDEN_OWNERSHIP", "cannot order for another troop")
    order = new_record("orders", {
        "season_id": seasonId,
        "troop_id": troop_id,
        "kind": kind,
        "status": "DRAFT",
        "total_units": 0,
        "total_amount_cents": 0,
        "rejection_reason": None,
    })
    return ok(order_json(order), status=201)


@app.get("/cookie-program/seasons/<seasonId>/orders")
def list_season_orders(seasonId):
    require_roles(ADMIN, LEADER)
    find_or_404("seasons", seasonId, "season")
    items = [o for o in db.all_recs("orders") if o["season_id"] == seasonId]
    tid = request.args.get("troop_id")
    st = request.args.get("status")
    if tid is not None:
        items = [o for o in items if o["troop_id"] == tid]
    if st is not None:
        items = [o for o in items if o["status"] == st]
    page, pg = paginate(items)
    return ok([order_json(o) for o in page], response_type="array", pagination=pg)


@app.get("/cookie-program/orders/<orderId>")
def get_order(orderId):
    require_roles(ADMIN, LEADER)
    o = find_or_404("orders", orderId, "order")
    return ok(order_json(o))


@app.get("/cookie-program/orders")
def list_orders():
    require_roles(ADMIN, LEADER)
    items = db.all_recs("orders")
    sid = request.args.get("season_id")
    tid = request.args.get("troop_id")
    st = request.args.get("status")
    if sid is not None:
        items = [o for o in items if o["season_id"] == sid]
    if tid is not None:
        items = [o for o in items if o["troop_id"] == tid]
    if st is not None:
        items = [o for o in items if o["status"] == st]
    page, pg = paginate(items)
    return ok([order_json(o) for o in page], response_type="array", pagination=pg)


@app.post("/cookie-program/seasons/<seasonId>/orders/<orderId>/lines")
def add_order_line(seasonId, orderId):
    require_roles(LEADER)
    find_or_404("seasons", seasonId, "season")
    order = find_or_404("orders", orderId, "order")
    if order["season_id"] != seasonId:
        raise_err("ERR_NOT_FOUND", "order not in season")
    if order["status"] != "DRAFT":
        raise_err("ERR_ORDER_INVALID_STATE", "order is not DRAFT")
    if order["troop_id"] != request.user_id:
        raise_err("ERR_FORBIDDEN_OWNERSHIP", "order belongs to another troop")
    body = get_body()
    product_id = req_str(body, "product_id")
    qty = req_int(body, "package_qty")
    product = db.get("products", product_id)
    if product is None or product["season_id"] != seasonId:
        raise_err("ERR_NOT_FOUND", "product not found in season")
    if qty <= 0 or qty % product["packages_per_case"] != 0:
        raise_err("ERR_CASE_PACK_VIOLATION",
                  "package_qty must be a positive multiple of packages_per_case")
    line = new_record("lines", {
        "order_id": orderId,
        "product_id": product_id,
        "package_qty": qty,
    })
    order["total_units"] += qty
    touch(order)
    return ok(line_json(line), status=201)


@app.get("/cookie-program/orders/<orderId>/lines")
def list_order_lines(orderId):
    require_roles(ADMIN, LEADER)
    find_or_404("orders", orderId, "order")
    items = [l for l in db.all_recs("lines") if l["order_id"] == orderId]
    page, pg = paginate(items)
    return ok([line_json(l) for l in page], response_type="array", pagination=pg)


@app.get("/cookie-program/order-lines/<lineId>")
def get_line(lineId):
    require_roles(ADMIN, LEADER)
    line = find_or_404("lines", lineId, "order line")
    return ok(line_json(line))


@app.get("/cookie-program/order-lines")
def list_lines():
    require_roles(ADMIN, LEADER)
    items = db.all_recs("lines")
    oid = request.args.get("order_id")
    pid = request.args.get("product_id")
    if oid is not None:
        items = [l for l in items if l["order_id"] == oid]
    if pid is not None:
        items = [l for l in items if l["product_id"] == pid]
    page, pg = paginate(items)
    return ok([line_json(l) for l in page], response_type="array", pagination=pg)


@app.post("/cookie-program/seasons/<seasonId>/orders/<orderId>/submit")
def submit_order(seasonId, orderId):
    require_roles(LEADER)
    season = find_or_404("seasons", seasonId, "season")
    order = find_or_404("orders", orderId, "order")
    if order["season_id"] != seasonId:
        raise_err("ERR_NOT_FOUND", "order not in season")
    if order["status"] != "DRAFT":
        raise_err("ERR_ORDER_INVALID_STATE", "order is not DRAFT")
    if order["total_units"] == 0:
        raise_err("ERR_ORDER_EMPTY", "order has no lines")
    if order["troop_id"] != request.user_id:
        raise_err("ERR_FORBIDDEN_OWNERSHIP", "order belongs to another troop")
    if order["kind"] == "INITIAL":
        if season["status"] not in ("OPEN", "SELLING"):
            raise_err("ERR_SEASON_NOT_ACCEPTING",
                      "season not accepting INITIAL orders")
        now = clock.now()
        if now < season["ordering_opens_at"] or now > season["ordering_closes_at"]:
            raise_err("ERR_ORDER_WINDOW_CLOSED",
                      "outside the initial ordering window")
    else:  # REPLENISHMENT
        if season["status"] != "SELLING":
            raise_err("ERR_SEASON_NOT_ACCEPTING",
                      "season not accepting REPLENISHMENT orders")
    order["status"] = "SUBMITTED"
    touch(order)
    touch(season)
    return ok(order_json(order))


@app.post("/cookie-program/seasons/<seasonId>/orders/<orderId>/confirm")
def confirm_order(seasonId, orderId):
    require_roles(ADMIN)
    season = find_or_404("seasons", seasonId, "season")
    order = find_or_404("orders", orderId, "order")
    if order["season_id"] != seasonId:
        raise_err("ERR_NOT_FOUND", "order not in season")
    if order["status"] != "SUBMITTED":
        raise_err("ERR_ORDER_INVALID_STATE", "order is not SUBMITTED")
    # recall gate (priority 5)
    lines = [l for l in db.all_recs("lines") if l["order_id"] == orderId]
    for line in lines:
        if active_recall_covers(line["product_id"]):
            raise_err("ERR_RECALLED_PRODUCT",
                      "an ACTIVE recall covers a product on this order")
    # allocation gate (priority 11). The order's own units are already held in
    # pending_commit_units; the gate measures remaining supply excluding this
    # order's pending reservation, then requires it to cover the order.
    c = season_counters(seasonId)
    effective_remaining = c["remaining_units"] + order["total_units"]
    if effective_remaining < order["total_units"]:
        raise_err("ERR_SUPPLY_INSUFFICIENT",
                  "season remaining_units below order total")
    order["status"] = "CONFIRMED"
    total_amount = 0
    proceeds = 0
    for line in lines:
        product = db.get("products", line["product_id"])
        total_amount += product["unit_price_cents"] * line["package_qty"]
        proceeds += product["troop_proceeds_cents"] * line["package_qty"]
    order["total_amount_cents"] = total_amount
    touch(order)
    account = find_account(order["troop_id"], seasonId)
    if account is not None:
        account["balance_cents"] += total_amount
        account["proceeds_accrued_cents"] += proceeds
        touch(account)
    touch(season)
    check_auto_selling(season)
    return ok(order_json(order))


@app.post("/cookie-program/seasons/<seasonId>/orders/<orderId>/reject")
def reject_order(seasonId, orderId):
    require_roles(ADMIN)
    season = find_or_404("seasons", seasonId, "season")
    order = find_or_404("orders", orderId, "order")
    if order["season_id"] != seasonId:
        raise_err("ERR_NOT_FOUND", "order not in season")
    if order["status"] != "SUBMITTED":
        raise_err("ERR_ORDER_INVALID_STATE", "order is not SUBMITTED")
    body = get_body()
    order["status"] = "REJECTED"
    order["rejection_reason"] = opt_str(body, "reason")
    touch(order)
    touch(season)
    return ok(order_json(order))


@app.post("/cookie-program/seasons/<seasonId>/orders/<orderId>/fulfill")
def fulfill_order(seasonId, orderId):
    require_roles(ADMIN)
    season = find_or_404("seasons", seasonId, "season")
    order = find_or_404("orders", orderId, "order")
    if order["season_id"] != seasonId:
        raise_err("ERR_NOT_FOUND", "order not in season")
    if order["status"] != "CONFIRMED":
        raise_err("ERR_ORDER_INVALID_STATE", "order is not CONFIRMED")
    if season["status"] not in ("OPEN", "SELLING"):
        raise_err("ERR_SEASON_INVALID_STATE", "season not OPEN or SELLING")
    order["status"] = "FULFILLED"
    touch(order)
    return ok(order_json(order))


# ---------------------------------------------------------------------------
# sites
# ---------------------------------------------------------------------------


@app.post("/cookie-program/seasons/<seasonId>/sites")
def create_site(seasonId):
    require_roles(ADMIN)
    season = find_or_404("seasons", seasonId, "season")
    body = get_body()
    name = req_str(body, "name")
    address = req_str(body, "address")
    capacity = req_int(body, "capacity_units")
    if capacity < 1:
        raise_err("ERR_INVALID_REQUEST", "capacity_units must be >= 1")
    expected = req_int(body, "expected_season_version")
    if expected != season["version"]:
        raise_err("ERR_STALE_VERSION", "expected_season_version is stale")
    site = new_record("sites", {
        "season_id": seasonId,
        "name": name,
        "address": address,
        "capacity_units": capacity,
    })
    touch(season)
    return ok(site_json(site), status=201)


@app.get("/cookie-program/seasons/<seasonId>/sites")
def list_season_sites(seasonId):
    require_roles(ADMIN, LEADER)
    find_or_404("seasons", seasonId, "season")
    items = [s for s in db.all_recs("sites") if s["season_id"] == seasonId]
    page, pg = paginate(items)
    return ok([site_json(s) for s in page], response_type="array", pagination=pg)


@app.get("/cookie-program/sites/<siteId>")
def get_site(siteId):
    require_roles(ADMIN, LEADER)
    s = find_or_404("sites", siteId, "site")
    return ok(site_json(s))


@app.get("/cookie-program/sites")
def list_sites():
    require_roles(ADMIN, LEADER)
    items = db.all_recs("sites")
    sid = request.args.get("season_id")
    if sid is not None:
        items = [s for s in items if s["season_id"] == sid]
    page, pg = paginate(items)
    return ok([site_json(s) for s in page], response_type="array", pagination=pg)


# ---------------------------------------------------------------------------
# baker purchase orders
# ---------------------------------------------------------------------------


@app.post("/cookie-program/seasons/<seasonId>/baker-pos")
def create_po(seasonId):
    require_roles(ADMIN)
    find_or_404("seasons", seasonId, "season")
    body = get_body()
    baker = req_str(body, "baker_name")
    product_id = req_str(body, "product_id")
    quantity = req_int(body, "quantity")
    site_id = req_str(body, "delivery_site_id")
    product = db.get("products", product_id)
    if product is None or product["season_id"] != seasonId:
        raise_err("ERR_NOT_FOUND", "product not found in season")
    site = db.get("sites", site_id)
    if site is None or site["season_id"] != seasonId:
        raise_err("ERR_NOT_FOUND", "delivery site not found in season")
    if quantity < 1:
        raise_err("ERR_INVALID_REQUEST", "quantity must be >= 1")
    po = new_record("pos", {
        "season_id": seasonId,
        "baker_name": baker,
        "product_id": product_id,
        "quantity": quantity,
        "delivery_site_id": site_id,
        "status": "DRAFT",
        "delivered_qty": 0,
    })
    return ok(po_json(po), status=201)


@app.get("/cookie-program/seasons/<seasonId>/baker-pos")
def list_season_pos(seasonId):
    require_roles(ADMIN)
    find_or_404("seasons", seasonId, "season")
    items = [p for p in db.all_recs("pos") if p["season_id"] == seasonId]
    dsid = request.args.get("delivery_site_id")
    if dsid is not None:
        items = [p for p in items if p["delivery_site_id"] == dsid]
    page, pg = paginate(items)
    return ok([po_json(p) for p in page], response_type="array", pagination=pg)


@app.get("/cookie-program/baker-pos/<poId>")
def get_po(poId):
    require_roles(ADMIN)
    po = find_or_404("pos", poId, "purchase order")
    return ok(po_json(po))


@app.get("/cookie-program/baker-pos")
def list_pos():
    require_roles(ADMIN)
    items = db.all_recs("pos")
    sid = request.args.get("season_id")
    pid = request.args.get("product_id")
    dsid = request.args.get("delivery_site_id")
    if sid is not None:
        items = [p for p in items if p["season_id"] == sid]
    if pid is not None:
        items = [p for p in items if p["product_id"] == pid]
    if dsid is not None:
        items = [p for p in items if p["delivery_site_id"] == dsid]
    page, pg = paginate(items)
    return ok([po_json(p) for p in page], response_type="array", pagination=pg)


@app.post("/cookie-program/seasons/<seasonId>/baker-pos/<poId>/place")
def place_po(seasonId, poId):
    require_roles(ADMIN)
    season = find_or_404("seasons", seasonId, "season")
    po = find_or_404("pos", poId, "purchase order")
    if po["season_id"] != seasonId:
        raise_err("ERR_NOT_FOUND", "purchase order not in season")
    if po["status"] != "DRAFT":
        raise_err("ERR_PO_INVALID_STATE", "purchase order is not DRAFT")
    if season["status"] not in ("DRAFT", "OPEN"):
        raise_err("ERR_SEASON_INVALID_STATE", "season not DRAFT or OPEN")
    po["status"] = "ORDERED"
    touch(po)
    touch(season)
    check_auto_selling(season)
    return ok(po_json(po))


@app.post("/cookie-program/seasons/<seasonId>/baker-pos/<poId>/cancel")
def cancel_po(seasonId, poId):
    require_roles(ADMIN)
    find_or_404("seasons", seasonId, "season")
    po = find_or_404("pos", poId, "purchase order")
    if po["season_id"] != seasonId:
        raise_err("ERR_NOT_FOUND", "purchase order not in season")
    if po["status"] != "DRAFT":
        raise_err("ERR_PO_INVALID_STATE", "purchase order is not DRAFT")
    po["status"] = "CANCELLED"
    touch(po)
    return ok(po_json(po))


@app.post("/cookie-program/seasons/<seasonId>/baker-pos/<poId>/record-delivery")
def record_delivery(seasonId, poId):
    require_roles(ADMIN)
    find_or_404("seasons", seasonId, "season")
    po = find_or_404("pos", poId, "purchase order")
    if po["season_id"] != seasonId:
        raise_err("ERR_NOT_FOUND", "purchase order not in season")
    if po["status"] not in ("ORDERED", "PARTIALLY_DELIVERED"):
        raise_err("ERR_PO_INVALID_STATE",
                  "purchase order not ORDERED or PARTIALLY_DELIVERED")
    body = get_body()
    delivered_now = req_int(body, "delivered_now")
    if delivered_now < 1:
        raise_err("ERR_INVALID_REQUEST", "delivered_now must be >= 1")
    if po["delivered_qty"] + delivered_now > po["quantity"]:
        raise_err("ERR_OVERDELIVERY", "cumulative delivery exceeds quantity")
    site = find_or_404("sites", po["delivery_site_id"], "site")
    sj = site_json(site)
    if sj["posture"] != "RECEIVING" or \
            sj["received_units"] + delivered_now > site["capacity_units"]:
        raise_err("ERR_SITE_CAPACITY_EXCEEDED",
                  "site cannot receive this delivery")
    po["delivered_qty"] += delivered_now
    if po["delivered_qty"] == po["quantity"]:
        po["status"] = "DELIVERED"
    else:
        po["status"] = "PARTIALLY_DELIVERED"
    touch(po)
    return ok(po_json(po))


# ---------------------------------------------------------------------------
# transfers
# ---------------------------------------------------------------------------


@app.post("/cookie-program/transfers")
def create_transfer():
    require_roles(LEADER, ADMIN)
    body = get_body()
    season_id = req_str(body, "season_id")
    find_or_404("seasons", season_id, "season")
    product_id = req_str(body, "product_id")
    product = db.get("products", product_id)
    if product is None or product["season_id"] != season_id:
        raise_err("ERR_NOT_FOUND", "product not found in season")
    qty = req_int(body, "package_qty")
    source_troop_id = opt_str(body, "source_troop_id")
    dest_troop_id = opt_str(body, "dest_troop_id")
    site_id = opt_str(body, "site_id")
    counter_id = opt_str(body, "counter_transfer_id")

    if source_troop_id is None and dest_troop_id is None:
        raise_err("ERR_INVALID_REQUEST",
                  "at least one troop side must be set")
    if (source_troop_id is None or dest_troop_id is None) and site_id is None:
        raise_err("ERR_INVALID_REQUEST",
                  "site_id is required when a troop side is null")
    if source_troop_id is not None and dest_troop_id is not None and site_id is not None:
        raise_err("ERR_INVALID_REQUEST",
                  "site_id must be null for troop-to-troop transfers")
    if source_troop_id is not None:
        find_or_404("troops", source_troop_id, "troop")
    if dest_troop_id is not None:
        find_or_404("troops", dest_troop_id, "troop")
    if site_id is not None:
        site = db.get("sites", site_id)
        if site is None or site["season_id"] != season_id:
            raise_err("ERR_NOT_FOUND", "site not found in season")
    if counter_id is not None:
        find_or_404("transfers", counter_id, "transfer")
    if qty <= 0 or qty % product["packages_per_case"] != 0:
        raise_err("ERR_CASE_PACK_VIOLATION",
                  "package_qty must be a positive multiple of packages_per_case")
    if request.user_role == LEADER:
        uid = request.user_id
        if uid != source_troop_id and uid != dest_troop_id:
            raise_err("ERR_FORBIDDEN_OWNERSHIP",
                      "acting troop is not a party to the transfer")
    t = new_record("transfers", {
        "season_id": season_id,
        "source_troop_id": source_troop_id,
        "dest_troop_id": dest_troop_id,
        "site_id": site_id,
        "product_id": product_id,
        "package_qty": qty,
        "status": "REQUESTED",
        "shipper_signed_by_troop_id": None,
        "receiver_signed_by_troop_id": None,
        "counter_transfer_id": counter_id,
        "requested_by_troop_id": acting_troop(),
    })
    return ok(transfer_json(t), status=201)


@app.get("/cookie-program/transfers/<transferId>")
def get_transfer(transferId):
    require_roles(ADMIN, LEADER)
    t = find_or_404("transfers", transferId, "transfer")
    return ok(transfer_json(t))


@app.get("/cookie-program/transfers")
def list_transfers():
    require_roles(ADMIN, LEADER)
    items = db.all_recs("transfers")
    for f in ("season_id", "source_troop_id", "dest_troop_id", "site_id",
              "product_id", "shipper_signed_by_troop_id",
              "receiver_signed_by_troop_id", "counter_transfer_id", "status"):
        v = request.args.get(f)
        if v is not None:
            items = [t for t in items if t.get(f) == v]
    page, pg = paginate(items)
    return ok([transfer_json(t) for t in page], response_type="array", pagination=pg)


@app.post("/cookie-program/transfers/<transferId>/sign-ship")
def sign_ship(transferId):
    require_roles(LEADER, ADMIN)
    t = find_or_404("transfers", transferId, "transfer")
    if t["status"] != "REQUESTED":
        raise_err("ERR_TRANSFER_INVALID_STATE", "transfer is not REQUESTED")
    body = get_body()
    signing_troop_id = opt_str(body, "signing_troop_id")
    if request.user_role == ADMIN:
        if t["source_troop_id"] is not None:
            raise_err("ERR_UNAUTHORIZED",
                      "only the source troop may sign the ship side")
        signer = signing_troop_id
    else:
        uid = request.user_id
        if t["source_troop_id"] is None:
            raise_err("ERR_UNAUTHORIZED",
                      "cupboard-source ship side is signed by CouncilAdmin")
        if uid != t["source_troop_id"]:
            raise_err("ERR_FORBIDDEN_OWNERSHIP",
                      "acting troop is not the source troop")
        if signing_troop_id is not None and signing_troop_id != uid:
            raise_err("ERR_FORBIDDEN_OWNERSHIP",
                      "signing_troop_id does not match acting troop")
        signer = uid
    # segregation of duties
    if t.get("requested_by_troop_id") is not None and \
            signer == t["requested_by_troop_id"]:
        raise_err("ERR_SOD_SAME_TROOP",
                  "signing troop must differ from the requesting troop")
    # site availability gate
    if t["source_troop_id"] is None and t.get("site_id") is not None:
        site = find_or_404("sites", t["site_id"], "site")
        if site_json(site)["available_units"] < t["package_qty"]:
            raise_err("ERR_SUPPLY_INSUFFICIENT",
                      "site available_units below package_qty")
    t["shipper_signed_by_troop_id"] = signer
    t["status"] = "SHIPPER_SIGNED"
    t["hold_released"] = False
    touch(t)
    return ok(transfer_json(t))


@app.post("/cookie-program/transfers/<transferId>/sign-receive")
def sign_receive(transferId):
    require_roles(LEADER, ADMIN)
    t = find_or_404("transfers", transferId, "transfer")
    if t["status"] != "SHIPPER_SIGNED":
        raise_err("ERR_TRANSFER_INVALID_STATE", "transfer is not SHIPPER_SIGNED")
    body = get_body()
    signing_troop_id = opt_str(body, "signing_troop_id")
    if request.user_role == ADMIN:
        if t["dest_troop_id"] is not None:
            raise_err("ERR_UNAUTHORIZED",
                      "only the destination troop may sign the receive side")
        signer = signing_troop_id
    else:
        uid = request.user_id
        if t["dest_troop_id"] is None:
            raise_err("ERR_UNAUTHORIZED",
                      "cupboard-destination receive side is signed by CouncilAdmin")
        if uid != t["dest_troop_id"]:
            raise_err("ERR_FORBIDDEN_OWNERSHIP",
                      "acting troop is not the destination troop")
        if signing_troop_id is not None and signing_troop_id != uid:
            raise_err("ERR_FORBIDDEN_OWNERSHIP",
                      "signing_troop_id does not match acting troop")
        signer = uid
    if signer is not None and signer == t["shipper_signed_by_troop_id"]:
        raise_err("ERR_SOD_SAME_TROOP",
                  "receive signer must differ from ship signer")
    t["receiver_signed_by_troop_id"] = signer
    t["status"] = "RECEIVER_SIGNED"
    touch(t)
    return ok(transfer_json(t))


def _finalize_transfer(t):
    """Apply completion side effects for one transfer (no version bump here)."""
    t["status"] = "COMPLETED"
    touch(t)


@app.post("/cookie-program/transfers/<transferId>/complete")
def complete_transfer(transferId):
    require_roles(ADMIN)
    t = find_or_404("transfers", transferId, "transfer")
    if t["status"] != "RECEIVER_SIGNED":
        raise_err("ERR_TRANSFER_INVALID_STATE", "transfer is not RECEIVER_SIGNED")
    # recall gate (priority 5)
    if active_recall_covers(t["product_id"]):
        raise_err("ERR_RECALLED_PRODUCT",
                  "an ACTIVE recall covers the transfer product")
    body = get_body()
    expected = req_int(body, "expected_transfer_version")
    if expected != t["version"]:
        raise_err("ERR_STALE_VERSION", "expected_transfer_version is stale")
    _finalize_transfer(t)
    # swap symmetry
    cid = t.get("counter_transfer_id")
    if cid:
        counter = db.get("transfers", cid)
        if counter is not None and counter["status"] == "RECEIVER_SIGNED":
            _finalize_transfer(counter)
    return ok(transfer_json(t))


@app.post("/cookie-program/transfers/<transferId>/retract-ship-signature")
def retract_ship(transferId):
    require_roles(LEADER)
    t = find_or_404("transfers", transferId, "transfer")
    if t["status"] != "SHIPPER_SIGNED":
        raise_err("ERR_TRANSFER_INVALID_STATE", "transfer is not SHIPPER_SIGNED")
    if request.user_id != t["shipper_signed_by_troop_id"]:
        raise_err("ERR_FORBIDDEN_OWNERSHIP",
                  "only the ship signer may retract")
    t["shipper_signed_by_troop_id"] = None
    t["status"] = "REQUESTED"
    t["hold_released"] = True
    touch(t)
    return ok(transfer_json(t))


@app.post("/cookie-program/transfers/<transferId>/decline")
def decline_transfer(transferId):
    require_roles(LEADER, ADMIN)
    t = find_or_404("transfers", transferId, "transfer")
    if t["status"] != "REQUESTED":
        raise_err("ERR_TRANSFER_INVALID_STATE", "transfer is not REQUESTED")
    if request.user_role == LEADER:
        uid = request.user_id
        if uid != t["source_troop_id"] and uid != t["dest_troop_id"]:
            raise_err("ERR_FORBIDDEN_OWNERSHIP",
                      "acting troop is not a party to the transfer")
    t["status"] = "DECLINED"
    touch(t)
    return ok(transfer_json(t))


@app.post("/cookie-program/transfers/<transferId>/cancel")
def cancel_transfer(transferId):
    require_roles(LEADER, ADMIN)
    t = find_or_404("transfers", transferId, "transfer")
    if t["status"] != "REQUESTED":
        raise_err("ERR_TRANSFER_INVALID_STATE", "transfer is not REQUESTED")
    if request.user_role == LEADER:
        if request.user_id != t.get("requested_by_troop_id"):
            raise_err("ERR_FORBIDDEN_OWNERSHIP",
                      "only the requesting troop may cancel")
    t["status"] = "CANCELLED"
    touch(t)
    return ok(transfer_json(t))


# ---------------------------------------------------------------------------
# booth locations / slots / requests
# ---------------------------------------------------------------------------


@app.post("/cookie-program/seasons/<seasonId>/booth-locations")
def create_location(seasonId):
    require_roles(ADMIN)
    find_or_404("seasons", seasonId, "season")
    body = get_body()
    host = req_str(body, "host_business_name")
    address = req_str(body, "address")
    perm = body.get("host_permission_granted", False)
    if not isinstance(perm, bool):
        raise_err("ERR_INVALID_REQUEST", "host_permission_granted must be boolean")
    blackouts = body.get("blackout_dates", [])
    if not isinstance(blackouts, list) or any(not isinstance(d, str) for d in blackouts):
        raise_err("ERR_INVALID_REQUEST", "blackout_dates must be an array of dates")
    loc = new_record("locations", {
        "season_id": seasonId,
        "host_business_name": host,
        "address": address,
        "host_permission_granted": perm,
        "blackout_dates": blackouts,
    })
    return ok(location_json(loc), status=201)


@app.get("/cookie-program/seasons/<seasonId>/booth-locations")
def list_season_locations(seasonId):
    require_roles(ADMIN, LEADER)
    find_or_404("seasons", seasonId, "season")
    items = [l for l in db.all_recs("locations") if l["season_id"] == seasonId]
    page, pg = paginate(items)
    return ok([location_json(l) for l in page], response_type="array", pagination=pg)


@app.get("/cookie-program/booth-locations/<locationId>")
def get_location(locationId):
    require_roles(ADMIN, LEADER)
    loc = find_or_404("locations", locationId, "booth location")
    return ok(location_json(loc))


@app.get("/cookie-program/booth-locations")
def list_locations():
    require_roles(ADMIN, LEADER)
    items = db.all_recs("locations")
    sid = request.args.get("season_id")
    if sid is not None:
        items = [l for l in items if l["season_id"] == sid]
    page, pg = paginate(items)
    return ok([location_json(l) for l in page], response_type="array", pagination=pg)


@app.post("/cookie-program/booth-slots")
def create_slot():
    require_roles(ADMIN)
    body = get_body()
    location_id = req_str(body, "location_id")
    loc = find_or_404("locations", location_id, "booth location")
    start = req_dt(body, "start_at")
    end = req_dt(body, "end_at")
    capacity = opt_int(body, "capacity_troops", 1)
    if capacity < 1:
        raise_err("ERR_INVALID_REQUEST", "capacity_troops must be >= 1")
    if end <= start:
        raise_err("ERR_INVALID_REQUEST", "end_at must be strictly after start_at")
    # booth conflict checks (priority 8)
    if not loc["host_permission_granted"]:
        raise_err("ERR_BOOTH_CONFLICT", "host permission not granted")
    slot_date = start.date().isoformat()
    if slot_date in loc["blackout_dates"] or end.date().isoformat() in loc["blackout_dates"]:
        raise_err("ERR_BOOTH_CONFLICT", "slot date is blacked out")
    for s in db.all_recs("slots"):
        if s["location_id"] != location_id:
            continue
        # half-open overlap: start < existing.end AND end > existing.start
        if start < s["end_at"] and end > s["start_at"]:
            raise_err("ERR_BOOTH_CONFLICT", "slot overlaps an existing slot")
    slot = new_record("slots", {
        "location_id": location_id,
        "start_at": start,
        "end_at": end,
        "start_at_raw": body["start_at"],
        "end_at_raw": body["end_at"],
        "capacity_troops": capacity,
    })
    return ok(slot_json(slot), status=201)


@app.get("/cookie-program/booth-locations/<locationId>/slots")
def list_location_slots(locationId):
    require_roles(ADMIN, LEADER)
    find_or_404("locations", locationId, "booth location")
    items = [s for s in db.all_recs("slots") if s["location_id"] == locationId]
    page, pg = paginate(items)
    return ok([slot_json(s) for s in page], response_type="array", pagination=pg)


@app.get("/cookie-program/booth-slots/<slotId>")
def get_slot(slotId):
    require_roles(ADMIN, LEADER)
    s = find_or_404("slots", slotId, "booth slot")
    return ok(slot_json(s))


@app.get("/cookie-program/booth-slots")
def list_slots():
    require_roles(ADMIN, LEADER)
    items = db.all_recs("slots")
    lid = request.args.get("location_id")
    if lid is not None:
        items = [s for s in items if s["location_id"] == lid]
    page, pg = paginate(items)
    return ok([slot_json(s) for s in page], response_type="array", pagination=pg)


def _slot_approved_count(slot_id):
    return sum(1 for r in db.all_recs("requests")
               if r["slot_id"] == slot_id and r["status"] == "APPROVED")


@app.post("/cookie-program/booth-slots/<slotId>/requests")
def create_booth_request(slotId):
    require_roles(LEADER)
    slot = find_or_404("slots", slotId, "booth slot")
    body = get_body()
    troop_id = req_str(body, "troop_id")
    mode = req_enum(body, "mode", {"LOTTERY", "FIRST_COME"})
    rank = opt_int(body, "lottery_rank", None)
    find_or_404("troops", troop_id, "troop")
    if troop_id != request.user_id:
        raise_err("ERR_FORBIDDEN_OWNERSHIP",
                  "cannot request a booth for another troop")
    if mode == "LOTTERY":
        if rank is None or rank < 1:
            raise_err("ERR_INVALID_REQUEST",
                      "lottery_rank >= 1 is required for LOTTERY mode")
    loc = find_or_404("locations", slot["location_id"], "booth location")
    season = find_or_404("seasons", loc["season_id"], "season")
    # duplicate active request per troop per slot (priority 8)
    for r in db.all_recs("requests"):
        if (r["slot_id"] == slotId and r["troop_id"] == troop_id
                and r["status"] in ("PENDING", "APPROVED")):
            raise_err("ERR_BOOTH_CONFLICT",
                      "troop already holds a request on this slot")
    req = new_record("requests", {
        "slot_id": slotId,
        "troop_id": troop_id,
        "mode": mode,
        "lottery_rank": rank,
        "status": "PENDING",
        "decision_reason": None,
    })
    # FIRST_COME auto-approval when season SELLING and capacity remains
    if mode == "FIRST_COME" and season["status"] == "SELLING" \
            and loc["host_permission_granted"] \
            and _slot_approved_count(slotId) < slot["capacity_troops"]:
        req["status"] = "APPROVED"
    return ok(request_json(req), status=201)


@app.get("/cookie-program/booth-slots/<slotId>/requests")
def list_slot_requests(slotId):
    require_roles(ADMIN, LEADER)
    find_or_404("slots", slotId, "booth slot")
    items = [r for r in db.all_recs("requests") if r["slot_id"] == slotId]
    st = request.args.get("status")
    if st is not None:
        items = [r for r in items if r["status"] == st]
    page, pg = paginate(items)
    return ok([request_json(r) for r in page], response_type="array", pagination=pg)


@app.get("/cookie-program/booth-requests/<requestId>")
def get_booth_request(requestId):
    require_roles(ADMIN, LEADER)
    r = find_or_404("requests", requestId, "booth request")
    return ok(request_json(r))


@app.get("/cookie-program/booth-requests")
def list_booth_requests():
    require_roles(ADMIN, LEADER)
    items = db.all_recs("requests")
    sid = request.args.get("slot_id")
    tid = request.args.get("troop_id")
    st = request.args.get("status")
    if sid is not None:
        items = [r for r in items if r["slot_id"] == sid]
    if tid is not None:
        items = [r for r in items if r["troop_id"] == tid]
    if st is not None:
        items = [r for r in items if r["status"] == st]
    page, pg = paginate(items)
    return ok([request_json(r) for r in page], response_type="array", pagination=pg)


@app.post("/cookie-program/booth-slots/<slotId>/draw-lottery")
def draw_lottery(slotId):
    require_roles(ADMIN)
    slot = find_or_404("slots", slotId, "booth slot")
    loc = find_or_404("locations", slot["location_id"], "booth location")
    season = find_or_404("seasons", loc["season_id"], "season")
    if season["status"] != "SELLING":
        raise_err("ERR_SEASON_NOT_SELLING", "season is not SELLING")
    if not loc["host_permission_granted"]:
        raise_err("ERR_HOST_PERMISSION_MISSING", "host permission not granted")
    pending = [r for r in db.all_recs("requests")
               if r["slot_id"] == slotId and r["status"] == "PENDING"
               and r["mode"] == "LOTTERY"]
    eligible = sorted(
        [r for r in pending if r["lottery_rank"] is not None and r["lottery_rank"] <= 2],
        key=lambda r: (r["lottery_rank"], r["created_at"], r["created_seq"]))
    ineligible = [r for r in pending
                  if r["lottery_rank"] is not None and r["lottery_rank"] > 2]
    remaining = slot["capacity_troops"] - _slot_approved_count(slotId)
    if remaining < 0:
        remaining = 0
    approved_ids = []
    denied_ids = []
    for r in eligible[:remaining]:
        r["status"] = "APPROVED"
        touch(r)
        approved_ids.append(r["id"])
    for r in eligible[remaining:]:
        r["status"] = "DENIED"
        r["decision_reason"] = "LOTTERY_LOST"
        touch(r)
        denied_ids.append(r["id"])
    for r in ineligible:
        r["status"] = "DENIED"
        r["decision_reason"] = "RANK_GT_2"
        touch(r)
        denied_ids.append(r["id"])
    return ok({"approved_request_ids": approved_ids,
               "denied_request_ids": denied_ids})


@app.post("/cookie-program/booth-requests/<requestId>/approve")
def approve_booth_request(requestId):
    require_roles(ADMIN)
    r = find_or_404("requests", requestId, "booth request")
    if r["status"] != "PENDING":
        raise_err("ERR_REQUEST_INVALID_STATE", "request is not PENDING")
    slot = find_or_404("slots", r["slot_id"], "booth slot")
    loc = find_or_404("locations", slot["location_id"], "booth location")
    season = find_or_404("seasons", loc["season_id"], "season")
    if season["status"] != "SELLING":
        raise_err("ERR_SEASON_NOT_SELLING", "season is not SELLING")
    if not loc["host_permission_granted"]:
        raise_err("ERR_HOST_PERMISSION_MISSING", "host permission not granted")
    if _slot_approved_count(r["slot_id"]) >= slot["capacity_troops"]:
        raise_err("ERR_BOOTH_CAPACITY_FULL", "slot capacity reached")
    r["status"] = "APPROVED"
    touch(r)
    return ok(request_json(r))


@app.post("/cookie-program/booth-requests/<requestId>/cancel")
def cancel_booth_request(requestId):
    require_roles(LEADER)
    r = find_or_404("requests", requestId, "booth request")
    if r["status"] not in ("PENDING", "APPROVED"):
        raise_err("ERR_REQUEST_INVALID_STATE",
                  "request is not PENDING or APPROVED")
    if r["troop_id"] != request.user_id:
        raise_err("ERR_FORBIDDEN_OWNERSHIP",
                  "request belongs to another troop")
    r["status"] = "CANCELLED"
    touch(r)
    return ok(request_json(r))


# ---------------------------------------------------------------------------
# digital orders
# ---------------------------------------------------------------------------


@app.post("/cookie-program/seasons/<seasonId>/digital-orders")
def create_digital_order(seasonId):
    require_roles(LEADER)
    find_or_404("seasons", seasonId, "season")
    body = get_body()
    troop_id = req_str(body, "troop_id")
    email = req_str(body, "customer_email")
    ftype = req_enum(body, "fulfillment_type", {"SHIPPED", "IN_PERSON"})
    donation_units = opt_int(body, "donation_units", 0)
    if donation_units < 0:
        raise_err("ERR_INVALID_REQUEST", "donation_units must be >= 0")
    items = body.get("items")
    if not isinstance(items, list):
        raise_err("ERR_INVALID_REQUEST", "items must be an array")
    find_or_404("troops", troop_id, "troop")
    if troop_id != request.user_id:
        raise_err("ERR_FORBIDDEN_OWNERSHIP",
                  "cannot create a digital order for another troop")
    items_total = 0
    norm_items = []
    for item in items:
        if not isinstance(item, dict):
            raise_err("ERR_INVALID_REQUEST", "each item must be an object")
        pid = item.get("product_id")
        qty = item.get("package_qty")
        if not isinstance(pid, str):
            raise_err("ERR_INVALID_REQUEST", "item.product_id must be a string")
        if isinstance(qty, bool) or not isinstance(qty, int) or qty < 1:
            raise_err("ERR_INVALID_REQUEST", "item.package_qty must be >= 1")
        product = db.get("products", pid)
        if product is None or product["season_id"] != seasonId:
            raise_err("ERR_INVALID_REQUEST",
                      "item product must belong to the season")
        items_total += qty * product["unit_price_cents"]
        norm_items.append({"product_id": pid, "package_qty": qty})
    avg_price = season_avg_unit_price(seasonId)
    total = items_total + donation_units * avg_price
    order = new_record("digital_orders", {
        "season_id": seasonId,
        "troop_id": troop_id,
        "customer_email": email,
        "fulfillment_type": ftype,
        "donation_units": donation_units,
        "payment_status": "PENDING",
        "fulfillment_status": "OPEN",
        "total_amount_cents": total,
        "items": norm_items,
        "agreement_id": None,
    })
    return ok(digital_order_json(order), status=201)


@app.get("/cookie-program/digital-orders/<orderId>")
def get_digital_order(orderId):
    require_roles(ADMIN, LEADER)
    o = find_or_404("digital_orders", orderId, "digital order")
    return ok(digital_order_json(o))


@app.get("/cookie-program/digital-orders")
def list_digital_orders():
    require_roles(ADMIN, LEADER)
    items = db.all_recs("digital_orders")
    sid = request.args.get("season_id")
    tid = request.args.get("troop_id")
    ps = request.args.get("payment_status")
    if sid is not None:
        items = [o for o in items if o["season_id"] == sid]
    if tid is not None:
        items = [o for o in items if o["troop_id"] == tid]
    if ps is not None:
        items = [o for o in items if o["payment_status"] == ps]
    page, pg = paginate(items)
    return ok([digital_order_json(o) for o in page], response_type="array",
              pagination=pg)


def _digital_proceeds(order):
    total = 0
    for item in order["items"]:
        product = db.get("products", item["product_id"])
        if product:
            total += item["package_qty"] * product["troop_proceeds_cents"]
    return total


@app.post("/cookie-program/digital-orders/<orderId>/record-payment")
def record_payment(orderId):
    require_roles(LEADER)
    o = find_or_404("digital_orders", orderId, "digital order")
    if o["payment_status"] != "PENDING":
        raise_err("ERR_PAYMENT_INVALID_STATE", "payment is not PENDING")
    season = find_or_404("seasons", o["season_id"], "season")
    if season["status"] != "SELLING":
        raise_err("ERR_SEASON_NOT_SELLING", "season is not SELLING")
    o["payment_status"] = "PAID"
    touch(o)
    account = find_account(o["troop_id"], o["season_id"])
    if account is not None:
        account["balance_cents"] += o["total_amount_cents"]
        account["proceeds_accrued_cents"] += _digital_proceeds(o)
        touch(account)
    return ok(digital_order_json(o))


@app.post("/cookie-program/digital-orders/<orderId>/mark-uncollected")
def mark_uncollected(orderId):
    require_roles(LEADER)
    o = find_or_404("digital_orders", orderId, "digital order")
    if o["payment_status"] != "PENDING":
        raise_err("ERR_PAYMENT_INVALID_STATE", "payment is not PENDING")
    if o["fulfillment_type"] != "IN_PERSON":
        raise_err("ERR_FULFILLMENT_TYPE_MISMATCH",
                  "shipped orders cannot be uncollected")
    body = get_body()
    agreement_id = opt_str(body, "agreement_id")
    o["payment_status"] = "UNCOLLECTED"
    if agreement_id is not None:
        ag = find_or_404("agreements", agreement_id, "agreement")
        ag["outstanding_cents"] = agreement_outstanding(ag) + o["total_amount_cents"]
        ag["outstanding_override"] = ag["outstanding_cents"]
        touch(ag)
        o["agreement_id"] = agreement_id
    touch(o)
    return ok(digital_order_json(o))


@app.post("/cookie-program/digital-orders/<orderId>/mark-delivered")
def mark_delivered(orderId):
    require_roles(LEADER)
    o = find_or_404("digital_orders", orderId, "digital order")
    if o["fulfillment_status"] != "OPEN":
        raise_err("ERR_FULFILLMENT_INVALID_STATE", "fulfillment is not OPEN")
    if o["payment_status"] != "PAID":
        raise_err("ERR_UNPAID_DELIVERY", "payment is not PAID")
    for item in o["items"]:
        if active_recall_covers(item["product_id"]):
            raise_err("ERR_RECALLED_PRODUCT",
                      "an ACTIVE recall covers a product in this order")
    o["fulfillment_status"] = "DELIVERED"
    touch(o)
    return ok(digital_order_json(o))


@app.post("/cookie-program/digital-orders/<orderId>/refund")
def refund_digital_order(orderId):
    require_roles(ADMIN)
    o = find_or_404("digital_orders", orderId, "digital order")
    if o["payment_status"] != "PAID":
        raise_err("ERR_PAYMENT_INVALID_STATE", "payment is not PAID")
    if o["fulfillment_status"] == "DELIVERED":
        raise_err("ERR_ALREADY_DELIVERED", "order already delivered")
    o["payment_status"] = "REFUNDED"
    touch(o)
    account = find_account(o["troop_id"], o["season_id"])
    if account is not None:
        account["balance_cents"] -= o["total_amount_cents"]
        account["proceeds_accrued_cents"] -= _digital_proceeds(o)
        touch(account)
    return ok(digital_order_json(o))


@app.post("/cookie-program/digital-orders/<orderId>/cancel")
def cancel_digital_order(orderId):
    require_roles(LEADER)
    o = find_or_404("digital_orders", orderId, "digital order")
    if o["fulfillment_status"] != "OPEN":
        raise_err("ERR_FULFILLMENT_INVALID_STATE", "fulfillment is not OPEN")
    if o["payment_status"] == "PAID":
        raise_err("ERR_REFUND_REQUIRED", "refund required before cancelling")
    o["fulfillment_status"] = "CANCELLED"
    touch(o)
    return ok(digital_order_json(o))


# ---------------------------------------------------------------------------
# participant agreements
# ---------------------------------------------------------------------------


@app.post("/cookie-program/troops/<troopId>/agreements")
def create_agreement(troopId):
    require_roles(LEADER)
    find_or_404("troops", troopId, "troop")
    if troopId != request.user_id:
        raise_err("ERR_FORBIDDEN_OWNERSHIP",
                  "cannot manage agreements for another troop")
    body = get_body()
    season_id = req_str(body, "season_id")
    find_or_404("seasons", season_id, "season")
    participant = req_str(body, "participant_name")
    parent = req_str(body, "parent_name")
    signed = body.get("signed_responsibility", False)
    if not isinstance(signed, bool):
        raise_err("ERR_INVALID_REQUEST", "signed_responsibility must be boolean")
    assigned = opt_int(body, "assigned_packages", 0)
    paid = opt_int(body, "paid_amount_cents", 0)
    if assigned < 0 or paid < 0:
        raise_err("ERR_INVALID_REQUEST",
                  "assigned_packages and paid_amount_cents must be >= 0")
    avg = season_avg_unit_price(season_id)
    ag = new_record("agreements", {
        "troop_id": troopId,
        "season_id": season_id,
        "participant_name": participant,
        "parent_name": parent,
        "signed_responsibility": signed,
        "assigned_packages": assigned,
        "paid_amount_cents": paid,
        "unit_price_at_assignment_cents": avg,
        "outstanding_cents": 0,
        "status": "PENDING",
        "dispute_reason": None,
    })
    ag["outstanding_cents"] = agreement_outstanding(ag)
    return ok(agreement_json(ag), status=201)


@app.get("/cookie-program/troops/<troopId>/agreements")
def list_troop_agreements(troopId):
    require_roles(ADMIN, LEADER)
    find_or_404("troops", troopId, "troop")
    items = [a for a in db.all_recs("agreements") if a["troop_id"] == troopId]
    sid = request.args.get("season_id")
    st = request.args.get("status")
    if sid is not None:
        items = [a for a in items if a["season_id"] == sid]
    if st is not None:
        items = [a for a in items if a["status"] == st]
    page, pg = paginate(items)
    return ok([agreement_json(a) for a in page], response_type="array",
              pagination=pg)


@app.get("/cookie-program/agreements/<agreementId>")
def get_agreement(agreementId):
    require_roles(ADMIN, LEADER)
    ag = find_or_404("agreements", agreementId, "agreement")
    return ok(agreement_json(ag))


@app.get("/cookie-program/agreements")
def list_agreements():
    require_roles(ADMIN, LEADER)
    items = db.all_recs("agreements")
    tid = request.args.get("troop_id")
    sid = request.args.get("season_id")
    st = request.args.get("status")
    if tid is not None:
        items = [a for a in items if a["troop_id"] == tid]
    if sid is not None:
        items = [a for a in items if a["season_id"] == sid]
    if st is not None:
        items = [a for a in items if a["status"] == st]
    page, pg = paginate(items)
    return ok([agreement_json(a) for a in page], response_type="array",
              pagination=pg)


@app.post("/cookie-program/agreements/<agreementId>/settle")
def settle_agreement(agreementId):
    require_roles(LEADER)
    ag = find_or_404("agreements", agreementId, "agreement")
    if ag["status"] not in ("PENDING", "DISPUTED"):
        raise_err("ERR_AGREEMENT_INVALID_STATE",
                  "agreement is not PENDING or DISPUTED")
    if ag["troop_id"] != request.user_id:
        raise_err("ERR_FORBIDDEN_OWNERSHIP",
                  "agreement belongs to another troop")
    body = get_body()
    settle_amount = req_int(body, "settle_amount_cents")
    outstanding = agreement_outstanding(ag)
    if settle_amount < outstanding:
        raise_err("ERR_UNDERPAID", "settle amount does not cover outstanding")
    ag["paid_amount_cents"] += settle_amount
    ag["outstanding_cents"] = 0
    ag["status"] = "PAID"
    touch(ag)
    account = find_account(ag["troop_id"], ag["season_id"])
    if account is not None:
        account["balance_cents"] -= settle_amount
        touch(account)
    return ok(agreement_json(ag))


@app.post("/cookie-program/agreements/<agreementId>/dispute")
def dispute_agreement(agreementId):
    require_roles(LEADER)
    ag = find_or_404("agreements", agreementId, "agreement")
    if ag["status"] != "PENDING":
        raise_err("ERR_AGREEMENT_INVALID_STATE", "agreement is not PENDING")
    if ag["troop_id"] != request.user_id:
        raise_err("ERR_FORBIDDEN_OWNERSHIP",
                  "agreement belongs to another troop")
    body = get_body()
    ag["status"] = "DISPUTED"
    ag["dispute_reason"] = opt_str(body, "reason")
    touch(ag)
    return ok(agreement_json(ag))


@app.post("/cookie-program/agreements/<agreementId>/resolve-dispute")
def resolve_dispute(agreementId):
    require_roles(ADMIN)
    ag = find_or_404("agreements", agreementId, "agreement")
    if ag["status"] != "DISPUTED":
        raise_err("ERR_AGREEMENT_INVALID_STATE", "agreement is not DISPUTED")
    ag["status"] = "PENDING"
    touch(ag)
    return ok(agreement_json(ag))


@app.post("/cookie-program/agreements/<agreementId>/forfeit")
def forfeit_agreement(agreementId):
    require_roles(ADMIN)
    ag = find_or_404("agreements", agreementId, "agreement")
    if ag["status"] not in ("PENDING", "DISPUTED"):
        raise_err("ERR_AGREEMENT_INVALID_STATE",
                  "agreement is not PENDING or DISPUTED")
    outstanding = agreement_outstanding(ag)
    ag["status"] = "FORFEITED"
    touch(ag)
    account = find_account(ag["troop_id"], ag["season_id"])
    if account is not None:
        account["balance_cents"] += outstanding
        touch(account)
    return ok(agreement_json(ag))


# ---------------------------------------------------------------------------
# recalls
# ---------------------------------------------------------------------------


@app.post("/cookie-program/seasons/<seasonId>/recalls")
def create_recall(seasonId):
    require_roles(ADMIN)
    season = find_or_404("seasons", seasonId, "season")
    body = get_body()
    product_id = req_str(body, "product_id")
    reason = req_str(body, "reason")
    effective = req_dt(body, "effective_at")
    product = db.get("products", product_id)
    if product is None or product["season_id"] != seasonId:
        raise_err("ERR_NOT_FOUND", "product not found in season")
    if effective < parse_dt(season["created_at"]):
        raise_err("ERR_INVALID_REQUEST",
                  "effective_at must not precede season creation")
    recall = new_record("recalls", {
        "season_id": seasonId,
        "product_id": product_id,
        "reason": reason,
        "effective_at": effective,
        "effective_at_raw": body["effective_at"],
        "status": "DRAFT",
    })
    return ok(recall_json(recall), status=201)


@app.get("/cookie-program/seasons/<seasonId>/recalls")
def list_season_recalls(seasonId):
    require_roles(ADMIN, LEADER)
    find_or_404("seasons", seasonId, "season")
    items = [r for r in db.all_recs("recalls") if r["season_id"] == seasonId]
    pid = request.args.get("product_id")
    st = request.args.get("status")
    if pid is not None:
        items = [r for r in items if r["product_id"] == pid]
    if st is not None:
        items = [r for r in items if r["status"] == st]
    page, pg = paginate(items)
    return ok([recall_json(r) for r in page], response_type="array", pagination=pg)


@app.get("/cookie-program/recalls/<recallId>")
def get_recall(recallId):
    require_roles(ADMIN, LEADER)
    r = find_or_404("recalls", recallId, "recall")
    return ok(recall_json(r))


@app.get("/cookie-program/recalls")
def list_recalls():
    require_roles(ADMIN, LEADER)
    items = db.all_recs("recalls")
    sid = request.args.get("season_id")
    pid = request.args.get("product_id")
    st = request.args.get("status")
    if sid is not None:
        items = [r for r in items if r["season_id"] == sid]
    if pid is not None:
        items = [r for r in items if r["product_id"] == pid]
    if st is not None:
        items = [r for r in items if r["status"] == st]
    page, pg = paginate(items)
    return ok([recall_json(r) for r in page], response_type="array", pagination=pg)


@app.post("/cookie-program/seasons/<seasonId>/recalls/<recallId>/activate")
def activate_recall(seasonId, recallId):
    require_roles(ADMIN)
    season = find_or_404("seasons", seasonId, "season")
    recall = find_or_404("recalls", recallId, "recall")
    if recall["season_id"] != seasonId:
        raise_err("ERR_NOT_FOUND", "recall not in season")
    if recall["status"] != "DRAFT":
        raise_err("ERR_RECALL_INVALID_STATE", "recall is not DRAFT")
    if season["status"] not in ("OPEN", "SELLING"):
        raise_err("ERR_SEASON_INVALID_STATE", "season not OPEN or SELLING")
    recall["status"] = "ACTIVE"
    touch(recall)
    return ok(recall_json(recall))


@app.post("/cookie-program/seasons/<seasonId>/recalls/<recallId>/lift")
def lift_recall(seasonId, recallId):
    require_roles(ADMIN)
    find_or_404("seasons", seasonId, "season")
    recall = find_or_404("recalls", recallId, "recall")
    if recall["season_id"] != seasonId:
        raise_err("ERR_NOT_FOUND", "recall not in season")
    if recall["status"] != "ACTIVE":
        raise_err("ERR_RECALL_INVALID_STATE", "recall is not ACTIVE")
    recall["status"] = "LIFTED"
    touch(recall)
    return ok(recall_json(recall))


# ---------------------------------------------------------------------------

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", "10000")))
