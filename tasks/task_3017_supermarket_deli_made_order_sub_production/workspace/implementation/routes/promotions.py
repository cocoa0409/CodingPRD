"""Promotion and BreadSupplyOrder groups (PRD 3.5)."""
from errors import fail, invalid
from http_support import (
    Endpoint, as_int, as_number, as_string, body, envelope_array, opt, query,
    req,
)
from response import ok_object
from util import dt_add_hours, norm_dt, to_dec
import calc
import services as svc
import views

READ_ROLES = ["PlatformAdmin", "DeliManager", "DeliClerk", "BakeryCoordinator",
              "ScaleOperator"]
MANAGER_ROLES = ["PlatformAdmin", "DeliManager"]
BREAD_ROLES = ["BakeryCoordinator", "DeliManager"]


def register(app):
    Endpoint(app, "POST", "/deli/promotions", MANAGER_ROLES, create_promo)
    Endpoint(app, "GET", "/deli/promotions/<id>", READ_ROLES, get_promo)
    Endpoint(app, "GET", "/deli/promotions", READ_ROLES, list_promos)
    Endpoint(app, "POST", "/deli/promotions/<id>/activate", MANAGER_ROLES, activate)
    Endpoint(app, "POST", "/deli/promotions/<id>/settle", MANAGER_ROLES, settle)
    Endpoint(app, "POST", "/deli/promotions/<id>/reopen", MANAGER_ROLES, reopen)
    Endpoint(app, "POST", "/deli/promotions/<id>/cancel", MANAGER_ROLES, cancel)

    Endpoint(app, "POST", "/deli/bread-supply-orders", BREAD_ROLES, create_order)
    Endpoint(app, "GET", "/deli/bread-supply-orders/<id>", READ_ROLES, get_order)
    Endpoint(app, "GET", "/deli/bread-supply-orders", READ_ROLES, list_orders)
    Endpoint(app, "POST", "/deli/bread-supply-orders/<id>/submit", BREAD_ROLES,
             submit_order)
    Endpoint(app, "POST", "/deli/bread-supply-orders/<id>/confirm", BREAD_ROLES,
             confirm_order)
    Endpoint(app, "POST", "/deli/bread-supply-orders/<id>/deliver", BREAD_ROLES,
             deliver_order)
    Endpoint(app, "POST", "/deli/bread-supply-orders/<id>/reopen", MANAGER_ROLES,
             reopen_order)


# ------------------------------------------------------------- promotions -----
def create_promo(store, actor, view_args):
    payload = body()
    promo_code = as_string(req(payload, "promo_code"), "promo_code")
    if any(p["promo_code"] == promo_code for p in store.promotions.values()):
        invalid("promo_code must be unique across the chain.")
    item_id = as_string(req(payload, "deli_item_id"), "deli_item_id")
    svc.get_plain(store, "items", item_id)
    week_start = _instant(req(payload, "week_start_date"), "week_start_date")
    week_end = _instant(req(payload, "week_end_date"), "week_end_date")
    from util import parse_dt
    if parse_dt(week_end) <= parse_dt(week_start):
        invalid("week_end_date must be strictly after week_start_date.")
    uplift = as_number(req(payload, "forecast_uplift_pct"), "forecast_uplift_pct")
    if uplift < 0 or uplift > 2:
        invalid("forecast_uplift_pct must be between 0 and 2 inclusive.")
    baseline = as_int(req(payload, "trailing_baseline_units"),
                      "trailing_baseline_units")
    if baseline < 0:
        invalid("trailing_baseline_units must not be negative.")
    row = svc.create(store, "promotions", {
        "promo_code": promo_code,
        "deli_item_id": item_id,
        "week_start_date": week_start,
        "week_end_date": week_end,
        "forecast_uplift_pct": uplift,
        "trailing_baseline_units": baseline,
        "required_bread_units": 0,
        "settled_bread_units": 0,
        "status": "SCHEDULED",
    })
    # required_bread_units is recomputed at creation (provisional variant).
    row["required_bread_units"] = calc.promo_bread_demand(row, settled=False)
    return ok_object(store, views.promotion(row), 201)


def get_promo(store, actor, view_args):
    row = svc.get_plain(store, "promotions", view_args["id"])
    return ok_object(store, views.promotion(row))


def list_promos(store, actor, view_args):
    rows = svc.all_rows(store, "promotions")
    item_id = query("deli_item_id")
    status = query("status")
    if item_id:
        rows = [r for r in rows if r["deli_item_id"] == item_id]
    if status:
        rows = [r for r in rows if r["status"] == status]
    return envelope_array(store, rows, views.promotion)


def activate(store, actor, view_args):
    row = svc.get_plain(store, "promotions", view_args["id"])
    if row["status"] != "SCHEDULED":
        fail("ERR_INVALID_STATE")
    from util import parse_dt
    now = parse_dt(store.now())
    if not (parse_dt(row["week_start_date"]) <= now < parse_dt(row["week_end_date"])):
        fail("ERR_INVALID_STATE")
    row["status"] = "ACTIVE"
    svc.touch(store, row)
    svc.recompute_promotion(store, row["id"], settled=False)
    for store_row in svc.all_rows(store, "stores"):
        svc.recompute_store(store, store_row["id"])
    return ok_object(store, views.promotion(row))


def settle(store, actor, view_args):
    row = svc.get_plain(store, "promotions", view_args["id"])
    if row["status"] not in ("ACTIVE", "DEGRADED"):
        fail("ERR_INVALID_STATE")
    from util import parse_dt
    if parse_dt(store.now()) < parse_dt(row["week_end_date"]):
        fail("ERR_INVALID_STATE")
    for order in svc.all_rows(store, "bread_orders"):
        if order["promotion_id"] == row["id"] and order["status"] in ("SUBMITTED",
                                                                     "CONFIRMED"):
            fail("ERR_INVALID_STATE")
    row["status"] = "SETTLED"
    svc.touch(store, row)
    svc.recompute_promotion(store, row["id"], settled=True)
    for store_row in svc.all_rows(store, "stores"):
        svc.recompute_store(store, store_row["id"])
    return ok_object(store, views.promotion(row))


def reopen(store, actor, view_args):
    row = svc.get_plain(store, "promotions", view_args["id"])
    if row["status"] != "SETTLED":
        fail("ERR_INVALID_STATE")
    row["status"] = "ACTIVE"
    row["settled_bread_units"] = 0
    svc.touch(store, row)
    svc.recompute_promotion(store, row["id"], settled=False)
    for store_row in svc.all_rows(store, "stores"):
        svc.recompute_store(store, store_row["id"])
    return ok_object(store, views.promotion(row))


def cancel(store, actor, view_args):
    row = svc.get_plain(store, "promotions", view_args["id"])
    if row["status"] not in ("ACTIVE", "DEGRADED", "SETTLED"):
        fail("ERR_INVALID_STATE")
    blockers = {"SUBMITTED", "CONFIRMED"}
    if row["status"] in ("ACTIVE", "DEGRADED"):
        blockers = blockers | {"DELIVERED"}
    for order in svc.all_rows(store, "bread_orders"):
        if order["promotion_id"] == row["id"] and order["status"] in blockers:
            fail("ERR_INVALID_STATE")
    row["status"] = "CANCELLED"
    svc.touch(store, row)
    for order in svc.all_rows(store, "bread_orders"):
        if order["promotion_id"] == row["id"] and order["status"] != "RECONCILED":
            order["status"] = "RECONCILED"
            svc.touch(store, order)
    for store_row in svc.all_rows(store, "stores"):
        svc.recompute_store(store, store_row["id"])
    return ok_object(store, views.promotion(row))


# ------------------------------------------------------- bread supply --------
def create_order(store, actor, view_args):
    payload = body()
    store_id = as_string(req(payload, "store_id"), "store_id")
    svc.get_store(store, store_id)
    bread_item_id = as_string(req(payload, "bread_deli_item_id"),
                              "bread_deli_item_id")
    svc.get_plain(store, "items", bread_item_id)
    promo_id = as_string(req(payload, "promotion_id"), "promotion_id")
    promo = svc.get_plain(store, "promotions", promo_id)
    committed = as_int(req(payload, "committed_units"), "committed_units")
    if committed < 0:
        invalid("committed_units must not be negative.")
    row = svc.create(store, "bread_orders", {
        "store_id": store_id,
        "bread_deli_item_id": bread_item_id,
        "promotion_id": promo_id,
        "committed_units": committed,
        "required_units": promo["required_bread_units"],
        "delivered_units": 0,
        "shortfall_units": 0,
        "reserved_units": 0,
        "unreserved_required_units": 0,
        "submit_by_at": dt_add_hours(promo["week_start_date"], -48),
        "status": "DRAFT",
    })
    row["shortfall_units"] = max(0, row["required_units"] - row["committed_units"])
    svc.recompute_bread(store, store_id)
    return ok_object(store, views.bread_order(row), 201)


def get_order(store, actor, view_args):
    row = svc.get_plain(store, "bread_orders", view_args["id"])
    return ok_object(store, views.bread_order(row))


def list_orders(store, actor, view_args):
    rows = svc.all_rows(store, "bread_orders")
    for name, key in (("store_id", "store_id"), ("promotion_id", "promotion_id"),
                      ("bread_deli_item_id", "bread_deli_item_id"),
                      ("status", "status")):
        value = query(name)
        if value:
            rows = [r for r in rows if r[key] == value]
    return envelope_array(store, rows, views.bread_order)


def submit_order(store, actor, view_args):
    row = svc.get_plain(store, "bread_orders", view_args["id"])
    if row["status"] != "DRAFT":
        fail("ERR_INVALID_STATE")
    from util import parse_dt
    # Priority 24: the 48-hour lead time is a hard wall.
    if parse_dt(store.now()) >= parse_dt(row["submit_by_at"]):
        fail("ERR_LEAD_TIME_VIOLATED")
    promo = store.promotions[row["promotion_id"]]
    row["required_units"] = promo["required_bread_units"]
    if row["required_units"] <= 0:
        fail("ERR_INVALID_STATE")
    row["status"] = "SUBMITTED"
    row["shortfall_units"] = max(0, row["required_units"] - row["committed_units"])
    svc.touch(store, row)
    svc.recompute_bread(store, row["store_id"])
    return ok_object(store, views.bread_order(row))


def confirm_order(store, actor, view_args):
    payload = body()
    row = svc.get_plain(store, "bread_orders", view_args["id"])
    if row["status"] != "SUBMITTED":
        fail("ERR_INVALID_STATE")
    promo = store.promotions[row["promotion_id"]]
    # Priority 38: OCC against the promotion.
    svc.check_occ(store, promo, opt(payload, "expected_promotion_version"),
                  "expected_promotion_version")
    if row["committed_units"] * 10 < row["required_units"] * 8:
        fail("ERR_INVALID_STATE")
    row["status"] = "CONFIRMED"
    row["shortfall_units"] = max(0, row["required_units"] - row["committed_units"])
    svc.touch(store, row)
    svc.touch(store, promo)
    if row["shortfall_units"] > 0:
        if promo["status"] == "ACTIVE":
            promo["status"] = "DEGRADED"
            svc.touch(store, promo)
    svc.recompute_bread(store, row["store_id"])
    return ok_object(store, views.bread_order(row))


def deliver_order(store, actor, view_args):
    payload = body()
    row = svc.get_plain(store, "bread_orders", view_args["id"])
    if row["status"] != "CONFIRMED":
        fail("ERR_INVALID_STATE")
    delivered = as_int(req(payload, "delivered_units"), "delivered_units")
    if delivered < 0:
        invalid("delivered_units must not be negative.")
    row["delivered_units"] = delivered
    if delivered * 10 < row["required_units"] * 9:
        row["status"] = "SHORT"
    else:
        row["status"] = "DELIVERED"
    svc.touch(store, row)
    # Delivery releases every BREAD_HOLD ticket for that bread item.
    svc.refresh_ticket_bread_status(store, row["store_id"], row["bread_deli_item_id"])
    if row["status"] == "SHORT":
        promo = store.promotions[row["promotion_id"]]
        if promo["status"] == "ACTIVE":
            promo["status"] = "DEGRADED"
            svc.touch(store, promo)
    svc.recompute_bread(store, row["store_id"])
    return ok_object(store, views.bread_order(row))


def reopen_order(store, actor, view_args):
    payload = body()
    row = svc.get_plain(store, "bread_orders", view_args["id"])
    if row["status"] not in ("DELIVERED", "SHORT"):
        fail("ERR_INVALID_STATE")
    req(payload, "reason")
    row["status"] = "SUBMITTED"
    row["delivered_units"] = 0
    svc.touch(store, row)
    svc.recompute_bread(store, row["store_id"])
    return ok_object(store, views.bread_order(row))


def _instant(raw, field):
    try:
        return norm_dt(raw)
    except (TypeError, ValueError):
        invalid("%s must be an ISO 8601 instant." % field)