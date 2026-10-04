"""CateringOrder group (PRD 3.7)."""
from decimal import Decimal

from errors import fail, invalid
from http_support import (
    Endpoint, as_int, as_string, body, envelope_array, opt, query, req,
)
from response import ok_object
from util import dt_add_hours, norm_dt, parse_dt, to_dec
import calc
import services as svc
import views

READ_ROLES = ["PlatformAdmin", "DeliManager", "DeliClerk", "BakeryCoordinator",
              "ScaleOperator"]
CLERK_ROLES = ["DeliClerk", "DeliManager"]

BUCKET_HEADCOUNT_LIMIT = 40
MAX_WINDOW_HOURS = 2
CANCEL_REASONS = ("CUSTOMER_REQUEST", "UNCLAIMED", "STORE_CLOSURE", "OTHER")


def register(app):
    Endpoint(app, "POST", "/deli/catering-orders", CLERK_ROLES, create_order)
    Endpoint(app, "GET", "/deli/catering-orders/<id>", READ_ROLES, get_order)
    Endpoint(app, "GET", "/deli/catering-orders", READ_ROLES, list_orders)
    Endpoint(app, "POST", "/deli/catering-orders/<id>/confirm", CLERK_ROLES, confirm)
    Endpoint(app, "POST", "/deli/catering-orders/<id>/revise", CLERK_ROLES, revise)
    Endpoint(app, "POST", "/deli/catering-orders/<id>/start-production", CLERK_ROLES,
             start_production)
    Endpoint(app, "POST", "/deli/catering-orders/<id>/mark-ready", CLERK_ROLES,
             mark_ready)
    Endpoint(app, "POST", "/deli/catering-orders/<id>/pickup", CLERK_ROLES, pickup)
    Endpoint(app, "POST", "/deli/catering-orders/<id>/cancel", CLERK_ROLES, cancel)


def create_order(store, actor, view_args):
    payload = body()
    store_id = as_string(req(payload, "store_id"), "store_id")
    svc.get_store(store, store_id)
    item = svc.get_item(store, as_string(req(payload, "platter_deli_item_id"),
                                         "platter_deli_item_id"))
    if item["category"] != "CATERING_PLATTER":
        invalid("platter_deli_item_id must be a CATERING_PLATTER item.")
    request_id = as_string(req(payload, "request_id"), "request_id")
    # Priority 37: the replay guard fires above every deeper state check.
    if (store_id, request_id) in store.requests:
        fail("ERR_DUPLICATE_REQUEST")

    platter_count = as_int(req(payload, "platter_count"), "platter_count")
    headcount = as_int(req(payload, "headcount"), "headcount")
    lead_time = as_int(req(payload, "lead_time_hours"), "lead_time_hours")
    if platter_count < 1:
        invalid("platter_count must be at least 1.")
    if headcount < 1:
        invalid("headcount must be at least 1.")
    if lead_time < 0:
        invalid("lead_time_hours must not be negative.")
    window_start = _instant(req(payload, "pickup_window_start"), "pickup_window_start")
    window_end = _instant(req(payload, "pickup_window_end"), "pickup_window_end")
    if parse_dt(window_end) <= parse_dt(window_start):
        invalid("pickup_window_end must be strictly after pickup_window_start.")
    if parse_dt(window_end) > parse_dt(dt_add_hours(window_start, MAX_WINDOW_HOURS)):
        invalid("pickup_window_end must be at most 2 hours after pickup_window_start.")
    deposit = as_int(req(payload, "deposit_cents"), "deposit_cents")
    if deposit < 0:
        invalid("deposit_cents must not be negative.")
    planner_id = as_string(req(payload, "certified_planner_associate_id"),
                           "certified_planner_associate_id")
    planner = svc.get_associate(store, planner_id)
    if planner["store_id"] != store_id:
        fail("ERR_NOT_FOUND")
    parent_id = opt(payload, "parent_order_id")
    if parent_id is not None:
        svc.get_scoped(store, "catering_orders", parent_id, store_id)

    row = svc.create(store, "catering_orders", {
        "store_id": store_id,
        "platter_deli_item_id": item["id"],
        "parent_order_id": parent_id,
        "certified_planner_associate_id": planner_id,
        "customer_name": as_string(req(payload, "customer_name"), "customer_name"),
        "platter_count": platter_count,
        "headcount": headcount,
        "lead_time_hours": lead_time,
        "pickup_window_start": window_start,
        "pickup_window_end": window_end,
        "deposit_cents": deposit,
        "quote_total_cents": 0,
        "pickup_bucket_key": None,
        "status": "INQUIRY",
    })
    store.requests.add((store_id, request_id))
    svc.recompute_catering_quote(store, row)
    svc.touch(store, row)
    return ok_object(store, views.catering(row), 201)


def get_order(store, actor, view_args):
    row = svc.get_plain(store, "catering_orders", view_args["id"])
    return ok_object(store, views.catering(row))


def list_orders(store, actor, view_args):
    rows = svc.all_rows(store, "catering_orders")
    for name, key in (("store_id", "store_id"), ("status", "status"),
                      ("parent_order_id", "parent_order_id"),
                      ("platter_deli_item_id", "platter_deli_item_id"),
                      ("certified_planner_associate_id",
                       "certified_planner_associate_id")):
        value = query(name)
        if value:
            rows = [r for r in rows if r[key] == value]
    return envelope_array(store, rows, views.catering)


def confirm(store, actor, view_args):
    row = svc.get_plain(store, "catering_orders", view_args["id"])
    store_id = row["store_id"]
    store_row = svc.get_store(store, store_id)
    svc.recompute_store(store, store_id)
    if row["status"] != "INQUIRY":
        fail("ERR_INVALID_STATE")

    planner_certified = svc.holds_cert(
        store, row["certified_planner_associate_id"], "FOOD_HANDLING")
    # Priority 11 / priority 24: certification first, then the lead-time rules.
    if not planner_certified:
        fail("ERR_ASSOCIATE_NOT_CERTIFIED")
    if row["lead_time_hours"] < 24 and not (actor.entity_backed and svc.holds_cert(
            store, actor.id, "FOOD_HANDLING")):
        fail("ERR_LEAD_TIME_VIOLATED")
    if parse_dt(dt_add_hours(store.now(), row["lead_time_hours"])) > \
            parse_dt(row["pickup_window_start"]):
        fail("ERR_LEAD_TIME_VIOLATED")

    key = calc.pickup_bucket_key(row["pickup_window_start"])
    # Priority 25: the bucket capacity rule is aggregate, not per-order.
    if calc.bucket_headcount(svc.all_rows(store, "catering_orders"), key,
                             exclude_id=row["id"]) + row["headcount"] > \
            BUCKET_HEADCOUNT_LIMIT:
        fail("ERR_PICKUP_CAPACITY_EXCEEDED")
    if store_row["posture"] != "OPEN":
        fail("ERR_POSTURE_RESTRICTED")

    row["pickup_bucket_key"] = key
    row["status"] = "CONFIRMED"
    svc.touch(store, row)
    svc.recompute_catering_quote(store, row)
    svc.touch(store, row)
    return ok_object(store, views.catering(row))


def revise(store, actor, view_args):
    payload = body()
    row = svc.get_plain(store, "catering_orders", view_args["id"])
    store_id = row["store_id"]
    svc.get_store(store, store_id)
    svc.recompute_store(store, store_id)
    if row["status"] != "CONFIRMED":
        fail("ERR_INVALID_STATE")

    if "platter_count" in payload:
        value = as_int(payload["platter_count"], "platter_count")
        if value < 1:
            invalid("platter_count must be at least 1.")
        row["platter_count"] = value
    if "headcount" in payload:
        value = as_int(payload["headcount"], "headcount")
        if value < 1:
            invalid("headcount must be at least 1.")
        row["headcount"] = value
    if "pickup_window_start" in payload:
        row["pickup_window_start"] = _instant(payload["pickup_window_start"],
                                              "pickup_window_start")
    if "pickup_window_end" in payload:
        row["pickup_window_end"] = _instant(payload["pickup_window_end"],
                                            "pickup_window_end")
    if parse_dt(row["pickup_window_end"]) <= parse_dt(row["pickup_window_start"]):
        invalid("pickup_window_end must be strictly after pickup_window_start.")
    if parse_dt(row["pickup_window_end"]) > \
            parse_dt(dt_add_hours(row["pickup_window_start"], MAX_WINDOW_HOURS)):
        invalid("pickup_window_end must be at most 2 hours after pickup_window_start.")

    key = calc.pickup_bucket_key(row["pickup_window_start"])
    if calc.bucket_headcount(svc.all_rows(store, "catering_orders"), key,
                             exclude_id=row["id"]) + row["headcount"] > \
            BUCKET_HEADCOUNT_LIMIT:
        fail("ERR_PICKUP_CAPACITY_EXCEEDED")

    row["pickup_bucket_key"] = key
    row["status"] = "INQUIRY"
    svc.touch(store, row)
    svc.recompute_catering_quote(store, row)
    svc.touch(store, row)
    return ok_object(store, views.catering(row))


def start_production(store, actor, view_args):
    row = svc.get_plain(store, "catering_orders", view_args["id"])
    svc.get_store(store, row["store_id"])
    if row["status"] != "CONFIRMED":
        fail("ERR_INVALID_STATE")
    row["status"] = "IN_PRODUCTION"
    svc.touch(store, row)
    return ok_object(store, views.catering(row))


def mark_ready(store, actor, view_args):
    row = svc.get_plain(store, "catering_orders", view_args["id"])
    store_id = row["store_id"]
    svc.get_store(store, store_id)
    svc.recompute_store(store, store_id)
    if row["status"] != "IN_PRODUCTION":
        fail("ERR_INVALID_STATE")
    # Priority 20: the price file must be current before a label can print.
    if store.stores[store_id]["active_price_file_id"] is None:
        fail("ERR_PRICE_FILE_STALE")
    # The store must be within two hours of the pickup window start.
    if parse_dt(store.now()) < parse_dt(dt_add_hours(row["pickup_window_start"], -2)):
        fail("ERR_INVALID_STATE")
    item = svc.get_item(store, row["platter_deli_item_id"])
    row["status"] = "READY"
    svc.touch(store, row)
    svc.synthesize_label(store, store_id, "CATERING_PLATTER", row["id"],
                         to_dec(item["servings_per_platter"]),
                         svc.unit_price_for(store, item))
    return ok_object(store, views.catering(row))


def pickup(store, actor, view_args):
    row = svc.get_plain(store, "catering_orders", view_args["id"])
    svc.get_store(store, row["store_id"])
    if row["status"] != "READY":
        fail("ERR_INVALID_STATE")
    now = parse_dt(store.now())
    # Priority 23: strictly inside the half-open pickup window.
    if not (parse_dt(row["pickup_window_start"]) <= now < parse_dt(row["pickup_window_end"])):
        fail("ERR_PICKUP_WINDOW_MISSED")
    row["status"] = "PICKED_UP"
    svc.touch(store, row)
    return ok_object(store, views.catering(row))


def cancel(store, actor, view_args):
    payload = body()
    row = svc.get_plain(store, "catering_orders", view_args["id"])
    store_id = row["store_id"]
    svc.get_store(store, store_id)
    # PRD §3.7 describes the cancellation path but never declares a `reason`
    # vocabulary for it, so the field is accepted as free text and only recorded.
    reason = opt(payload, "reason", default="CUSTOMER_REQUEST")
    if row["status"] in ("PICKED_UP", "CANCELLED"):
        fail("ERR_INVALID_STATE")
    if row["status"] in ("IN_PRODUCTION", "READY"):
        # Manager-level reversal only.
        if actor.role not in ("DeliManager", "PlatformAdmin"):
            fail("ERR_UNAUTHORIZED")
    was_ready = row["status"] == "READY"
    row["status"] = "CANCELLED"
    svc.touch(store, row)
    store.cancel_reason[row["id"]] = reason
    if was_ready:
        # Unclaimed-platter waste: excluded from deli liability by its reason.
        _synthesize_unclaimed_waste(store, row)
    return ok_object(store, views.catering(row))


def _synthesize_unclaimed_waste(store, order):
    batch = None
    for candidate in svc.all_rows(store, "batches"):
        if candidate["store_id"] == order["store_id"] \
                and candidate["deli_item_id"] == order["platter_deli_item_id"]:
            if candidate["hold_status"] in ("HOLDING", "MARKED_DOWN"):
                batch = candidate
                break
    if batch is None:
        return
    svc.create(store, "waste_records", {
        "store_id": order["store_id"],
        "production_batch_id": batch["id"],
        "markdown_by_associate_id": None,
        "verifier_associate_id": None,
        "verified_by_certification_id": None,
        "discard_lbs": Decimal(0),
        "reason": "UNCLAIMED_PLATTER",
        "markdown_sold_lbs": Decimal(0),
        "markdown_cents": 0,
        "markdown_recorded_at": None,
        "discarded_at": store.now(),
        "discard_value_cents": 0,
        "handling_fee_cents": 0,
        "total_liability_cents": 0,
        "status": "DISCARDED",
    })
    svc.recompute_store(store, order["store_id"])


def _instant(raw, field):
    try:
        return norm_dt(raw)
    except (TypeError, ValueError):
        invalid("%s must be an ISO 8601 instant." % field)