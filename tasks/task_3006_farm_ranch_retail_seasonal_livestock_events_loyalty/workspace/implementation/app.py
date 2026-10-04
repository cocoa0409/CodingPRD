"""Farm & Ranch Retail API — Flask entry point and route table.

Implements PRD.md for task_3006. All temporal reasoning uses the logical
clock (db.now()); the store starts empty on every boot.
"""

import os
from datetime import datetime, timedelta, timezone
from decimal import Decimal

from flask import Flask, request

import db
import errors
import middleware as mw
import response as resp
import services as svc

app = Flask(__name__)

ALL_READ = ["RegionalAdmin", "StoreManager", "StoreAssociate", "Customer"]


@app.errorhandler(errors.ApiError)
def handle_api_error(err):
    return resp.error(err)


@app.errorhandler(404)
def handle_404(err):
    return resp.error(errors.ApiError("ERR_INVALID_REQUEST", "resource not found", 404))


@app.errorhandler(405)
def handle_405(err):
    return resp.error(errors.ApiError("ERR_INVALID_REQUEST", "method not allowed", 405))


@app.errorhandler(Exception)
def handle_unexpected(err):
    if isinstance(err, errors.ApiError):
        return resp.error(err)
    return resp.error(errors.ApiError("ERR_INVALID_REQUEST", str(err), 400))


def _list_response(records, filters, serializer):
    """filters: list of (query_param, record_field) exact-match filters."""
    for param, field in filters:
        raw = request.args.get(param)
        if raw is not None:
            records = [r for r in records if str(r.get(field)) == raw]
    limit, offset = mw.parse_pagination(request.args)
    page, total = mw.paginate(records, limit, offset)
    return resp.success_list([serializer(r) for r in page], limit, offset, total)


# ===========================================================================
# Logical clock
# ===========================================================================
@app.route("/_clock/set_current_utc", methods=["POST"])
def set_clock():
    uid, role = mw.user_context()
    mw.check_role(role, ["RegionalAdmin"])
    data = mw.get_json()
    to = svc.parse_iso(data.get("to_iso8601"), "to_iso8601")
    db.set_now(to)
    return resp.success({"current_utc": db.fmt_ts(db.now())})


# ===========================================================================
# Stores
# ===========================================================================
@app.route("/stores", methods=["POST"])
def create_store():
    uid, role = mw.user_context()
    mw.check_role(role, ["RegionalAdmin"])
    data = mw.get_json()
    name = svc.req_str(data, "store_name")
    region = svc.req_str(data, "region_code")
    store = db.new_common({
        "id": db.new_id(),
        "store_name": name,
        "region_code": region,
        "posture": "OFFSEASON",
        "active_campaign_id": None,
    })
    db.stores[store["id"]] = store
    return resp.success(svc.serialize_store(store), 201)


@app.route("/stores", methods=["GET"])
def list_stores():
    uid, role = mw.user_context()
    mw.check_role(role, ALL_READ)
    return _list_response(list(db.stores.values()), [], svc.serialize_store)


@app.route("/stores/<sid>", methods=["GET"])
def get_store(sid):
    uid, role = mw.user_context()
    mw.check_role(role, ALL_READ)
    return resp.success(svc.serialize_store(svc.get_store(sid)))


# ===========================================================================
# Season campaigns
# ===========================================================================
@app.route("/season-campaigns", methods=["POST"])
def create_campaign():
    uid, role = mw.user_context()
    mw.check_role(role, ["RegionalAdmin"])
    data = mw.get_json()
    store_id = svc.req_str(data, "store_id")
    season = svc.req_enum(data, "season", {"WINTER_HEATING", "SPRING_PLANTING", "FALL_FEED"})
    planogram = svc.req_str(data, "planogram_map")
    aisle_count = svc.req_int(data, "aisle_count", minimum=1)
    svc.get_store(store_id)
    campaign = db.new_common({
        "id": db.new_id(),
        "store_id": store_id,
        "season": season,
        "planogram_map": planogram,
        "aisle_count": aisle_count,
        "aisles_reset_count": 0,
        "activated_at": None,
        "status": "DRAFT",
    })
    db.campaigns[campaign["id"]] = campaign
    return resp.success(svc.serialize_campaign(campaign), 201)


@app.route("/season-campaigns", methods=["GET"])
def list_campaigns():
    uid, role = mw.user_context()
    mw.check_role(role, ALL_READ)
    return _list_response(
        list(db.campaigns.values()),
        [("store_id", "store_id"), ("status", "status")],
        svc.serialize_campaign)


@app.route("/season-campaigns/<cid>", methods=["GET"])
def get_campaign(cid):
    uid, role = mw.user_context()
    mw.check_role(role, ALL_READ)
    return resp.success(svc.serialize_campaign(svc.get_campaign(cid)))


@app.route("/season-campaigns/<cid>/begin-teardown", methods=["POST"])
def begin_teardown(cid):
    uid, role = mw.user_context()
    mw.check_role(role, ["StoreManager"])
    c = svc.get_campaign(cid)
    if c["status"] != "DRAFT":
        raise errors.err_campaign_not_in_draft()
    c["status"] = "TEARDOWN"
    db.touch(c)
    return resp.success(svc.serialize_campaign(c))


@app.route("/season-campaigns/<cid>/complete-reset", methods=["POST"])
def complete_reset(cid):
    uid, role = mw.user_context()
    mw.check_role(role, ["StoreManager"])
    data = mw.get_json()
    count = svc.req_int(data, "aisles_reset_count")
    c = svc.get_campaign(cid)
    if c["status"] != "TEARDOWN":
        raise errors.err_campaign_not_in_teardown()
    if count != c["aisle_count"]:
        raise errors.err_aisle_count_mismatch()
    c["aisles_reset_count"] = count
    c["status"] = "VERIFY_PENDING"
    db.touch(c)
    return resp.success(svc.serialize_campaign(c))


@app.route("/season-campaigns/<cid>/verify", methods=["POST"])
def verify_campaign(cid):
    uid, role = mw.user_context()
    mw.check_role(role, ["RegionalAdmin"])
    data = mw.get_json()
    audit_passed = svc.req_bool(data, "audit_passed")
    c = svc.get_campaign(cid)
    if c["status"] != "VERIFY_PENDING":
        raise errors.err_campaign_not_verify_pending()
    if audit_passed:
        c["status"] = "READY"
    else:
        c["status"] = "TEARDOWN"
        c["aisles_reset_count"] = 0
    db.touch(c)
    return resp.success(svc.serialize_campaign(c))


@app.route("/season-campaigns/<cid>/activate", methods=["POST"])
def activate_campaign(cid):
    uid, role = mw.user_context()
    mw.check_role(role, ["RegionalAdmin"])
    data = mw.get_json()
    expected = svc.req_int(data, "expected_store_version")
    c = svc.get_campaign(cid)
    store = svc.get_store(c["store_id"])
    # OCC (priority 5) before state preconditions (priority 7)
    if expected != store["version"]:
        raise errors.err_stale_store_version()
    if c["status"] != "READY":
        raise errors.err_campaign_not_ready()
    c["status"] = "ACTIVE"
    c["activated_at"] = db.now()
    db.touch(c)
    svc.posture_cascade_on_activation(store, c)
    return resp.success(svc.serialize_campaign(c))


@app.route("/season-campaigns/<cid>/cancel", methods=["POST"])
def cancel_campaign(cid):
    uid, role = mw.user_context()
    mw.check_role(role, ["RegionalAdmin"])
    c = svc.get_campaign(cid)
    if c["status"] not in ("DRAFT", "TEARDOWN", "VERIFY_PENDING"):
        raise errors.err_invalid_state_transition("campaign cannot be cancelled from its state")
    c["status"] = "CANCELLED"
    db.touch(c)
    return resp.success(svc.serialize_campaign(c))


# ===========================================================================
# Staging bays
# ===========================================================================
@app.route("/staging-bays", methods=["POST"])
def create_bay():
    uid, role = mw.user_context()
    mw.check_role(role, ["StoreManager"])
    data = mw.get_json()
    store_id = svc.req_str(data, "store_id")
    bay_no = svc.req_int(data, "bay_no", minimum=1)
    size_class = svc.req_enum(data, "size_class", {"M", "L", "XL"})
    svc.get_store(store_id)
    for b in db.bays.values():
        if b["store_id"] == store_id and b["bay_no"] == bay_no:
            raise errors.err_bay_no_taken()
    bay = db.new_common({
        "id": db.new_id(),
        "store_id": store_id,
        "bay_no": bay_no,
        "size_class": size_class,
        "status": "AVAILABLE",
    })
    db.bays[bay["id"]] = bay
    return resp.success(svc.serialize_bay(bay), 201)


@app.route("/staging-bays", methods=["GET"])
def list_bays():
    uid, role = mw.user_context()
    mw.check_role(role, ALL_READ)
    return _list_response(
        list(db.bays.values()),
        [("store_id", "store_id"), ("status", "status")],
        svc.serialize_bay)


@app.route("/staging-bays/<bid>", methods=["GET"])
def get_bay(bid):
    uid, role = mw.user_context()
    mw.check_role(role, ALL_READ)
    return resp.success(svc.serialize_bay(svc.get_bay(bid)))


@app.route("/staging-bays/<bid>/set-status", methods=["POST"])
def set_bay_status(bid):
    uid, role = mw.user_context()
    mw.check_role(role, ["StoreManager"])
    data = mw.get_json()
    status = svc.req_enum(data, "status", {"AVAILABLE", "OCCUPIED", "OUT_OF_SERVICE"})
    bay = svc.get_bay(bid)
    if status == "OCCUPIED":
        raise errors.err_invalid_request("OCCUPIED is managed by pickup staging")
    bay["status"] = status
    db.touch(bay)
    return resp.success(svc.serialize_bay(bay))


# ===========================================================================
# Hatchery schedules
# ===========================================================================
@app.route("/hatchery-schedules", methods=["POST"])
def create_schedule():
    uid, role = mw.user_context()
    mw.check_role(role, ["StoreManager"])
    data = mw.get_json()
    store_id = svc.req_str(data, "store_id")
    species = svc.req_str(data, "species")
    breed = svc.req_str(data, "breed")
    hatch_date = svc.parse_iso(data.get("hatch_date"), "hatch_date")
    sws = svc.parse_iso(data.get("sale_window_start"), "sale_window_start")
    swe = svc.parse_iso(data.get("sale_window_end"), "sale_window_end")
    daily_capacity = svc.req_int(data, "daily_capacity", minimum=1)
    min_purchase = svc.req_int(data, "min_purchase_qty", minimum=1)
    base_price = svc.req_int(data, "base_price_cents_per_bird", minimum=1)
    if not swe > sws:
        raise errors.err_invalid_request("sale_window_end must be > sale_window_start")
    if sws < hatch_date + timedelta(days=1):
        raise errors.err_invalid_request(
            "sale_window_start must be on or after hatch_date + 1 day")
    svc.get_store(store_id)
    sched = db.new_common({
        "id": db.new_id(),
        "store_id": store_id,
        "species": species,
        "breed": breed,
        "hatch_date": hatch_date,
        "sale_window_start": sws,
        "sale_window_end": swe,
        "daily_capacity": daily_capacity,
        "min_purchase_qty": min_purchase,
        "base_price_cents_per_bird": base_price,
        "status": "DRAFT",
    })
    db.schedules[sched["id"]] = sched
    return resp.success(svc.serialize_schedule(sched), 201)


@app.route("/hatchery-schedules", methods=["GET"])
def list_schedules():
    uid, role = mw.user_context()
    mw.check_role(role, ALL_READ)
    return _list_response(
        list(db.schedules.values()),
        [("store_id", "store_id"), ("species", "species"), ("status", "status")],
        svc.serialize_schedule)


@app.route("/hatchery-schedules/<sid>", methods=["GET"])
def get_schedule(sid):
    uid, role = mw.user_context()
    mw.check_role(role, ALL_READ)
    return resp.success(svc.serialize_schedule(svc.get_schedule(sid)))


@app.route("/hatchery-schedules/<sid>/publish", methods=["POST"])
def publish_schedule(sid):
    uid, role = mw.user_context()
    mw.check_role(role, ["StoreManager"])
    sched = svc.get_schedule(sid)
    if sched["status"] != "DRAFT":
        raise errors.err_schedule_not_draft()
    svc.schedule_window_gap_check(sched)
    sched["status"] = "PUBLISHED"
    db.touch(sched)
    return resp.success(svc.serialize_schedule(sched))


@app.route("/hatchery-schedules/<sid>/close", methods=["POST"])
def close_schedule(sid):
    uid, role = mw.user_context()
    mw.check_role(role, ["StoreManager"])
    data = mw.get_json()
    reason = svc.opt_str(data, "reason")
    sched = svc.get_schedule(sid)
    if reason == "CANCELLED":
        if sched["status"] != "DRAFT":
            raise errors.err_schedule_not_draft()
        sched["status"] = "CANCELLED"
        db.touch(sched)
        return resp.success(svc.serialize_schedule(sched))
    if sched["status"] != "PUBLISHED":
        raise errors.err_schedule_not_published()
    svc.close_schedule_cascade(sched)
    return resp.success(svc.serialize_schedule(sched))


# ===========================================================================
# Livestock lots and care logs
# ===========================================================================
@app.route("/livestock-lots", methods=["POST"])
def create_lot():
    uid, role = mw.user_context()
    mw.check_role(role, ["StoreManager"])
    data = mw.get_json()
    store_id = svc.req_str(data, "store_id")
    schedule_id = svc.req_str(data, "hatchery_schedule_id")
    qty = svc.req_int(data, "quantity_received", minimum=1)
    received_at = svc.parse_iso(data.get("received_at"), "received_at")
    svc.get_store(store_id)
    sched = svc.get_schedule(schedule_id)
    if sched["status"] != "PUBLISHED":
        raise errors.err_schedule_not_published()
    lot = db.new_common({
        "id": db.new_id(),
        "store_id": store_id,
        "hatchery_schedule_id": schedule_id,
        "quantity_received": qty,
        "received_at": received_at,
        "quantity_on_hand": qty,
        "quantity_sold": 0,
        "mortality_count": 0,
        "quantity_quarantined": 0,
        "mortality_rate": Decimal("0"),
        "health_flag": "NORMAL",
        "status": "RECEIVING",
    })
    db.lots[lot["id"]] = lot
    return resp.success(svc.serialize_lot(lot), 201)


@app.route("/livestock-lots", methods=["GET"])
def list_lots():
    uid, role = mw.user_context()
    mw.check_role(role, ALL_READ)
    return _list_response(
        list(db.lots.values()),
        [("store_id", "store_id"), ("hatchery_schedule_id", "hatchery_schedule_id"),
         ("status", "status")],
        svc.serialize_lot)


@app.route("/livestock-lots/<lid>", methods=["GET"])
def get_lot(lid):
    uid, role = mw.user_context()
    mw.check_role(role, ALL_READ)
    return resp.success(svc.serialize_lot(svc.get_lot(lid)))


@app.route("/livestock-lots/<lid>/open-sale", methods=["POST"])
def open_sale(lid):
    uid, role = mw.user_context()
    mw.check_role(role, ["StoreManager"])
    lot = svc.get_lot(lid)
    sched = svc.get_schedule(lot["hatchery_schedule_id"])
    if lot["status"] != "RECEIVING":
        raise errors.err_lot_not_receiving()
    if sched["status"] != "PUBLISHED":
        raise errors.err_schedule_not_published()
    now = db.now()
    if not (sched["sale_window_start"] <= now <= sched["sale_window_end"]):
        raise errors.err_outside_sale_window()
    lot["status"] = "ON_SALE"
    db.touch(lot)
    return resp.success(svc.serialize_lot(lot))


@app.route("/livestock-lots/<lid>/close-sale", methods=["POST"])
def close_sale(lid):
    uid, role = mw.user_context()
    mw.check_role(role, ["StoreManager"])
    data = mw.get_json()
    disposition = svc.opt_bool(data, "disposition", default=False)
    lot = svc.get_lot(lid)
    svc.close_lot_cascade(lot, disposition=bool(disposition))
    return resp.success(svc.serialize_lot(lot))


@app.route("/livestock-lots/<lid>/care-logs", methods=["POST"])
def create_care_log(lid):
    uid, role = mw.user_context()
    mw.check_role(role, ["StoreAssociate"])
    data = mw.get_json()
    entry_type = svc.req_enum(data, "entry_type", {"FEEDING", "WATER", "TEMPERATURE", "MORTALITY"})
    measured_temp_f = data.get("measured_temp_f")
    mortality_count = data.get("mortality_count")
    note = svc.opt_str(data, "note")
    if entry_type == "TEMPERATURE":
        if not (isinstance(measured_temp_f, (int, float)) and not isinstance(measured_temp_f, bool)):
            raise errors.err_invalid_request("measured_temp_f is required for TEMPERATURE")
    else:
        if measured_temp_f is not None and not (
                isinstance(measured_temp_f, (int, float)) and not isinstance(measured_temp_f, bool)):
            raise errors.err_invalid_request("measured_temp_f must be a number")
    if entry_type == "MORTALITY":
        if not (isinstance(mortality_count, int) and not isinstance(mortality_count, bool)
                and mortality_count >= 1):
            raise errors.err_invalid_request("mortality_count >= 1 is required for MORTALITY")
    else:
        if mortality_count is not None and not (
                isinstance(mortality_count, int) and not isinstance(mortality_count, bool)):
            raise errors.err_invalid_request("mortality_count must be an integer")
    lot = svc.get_lot(lid)
    entry = {
        "id": db.new_id(),
        "lot_id": lot["id"],
        "entry_type": entry_type,
        "measured_temp_f": measured_temp_f,
        "mortality_count": mortality_count,
        "note": note,
        "created_at": db.now(),
    }
    db.care_logs[entry["id"]] = entry
    if entry_type == "MORTALITY":
        lot["mortality_count"] += mortality_count
        # PRD §3.3: quantity_on_hand = received - sold - mortality - quarantined
        # - reserved; mortality losses therefore decrement on_hand.
        lot["quantity_on_hand"] -= mortality_count
        lot["mortality_rate"] = (
            Decimal(lot["mortality_count"]) / Decimal(lot["quantity_received"])
        ).quantize(Decimal("0.0001"), rounding="ROUND_HALF_UP")
        db.touch(lot)
        if lot["mortality_rate"] > svc.MORTALITY_QUARANTINE_RATE and lot["status"] == "ON_SALE":
            lot["status"] = "SUSPENDED"
            lot["health_flag"] = "QUARANTINED"
            for o in list(db.chick_orders.values()):
                if o["livestock_lot_id"] == lot["id"] and o["status"] in ("RESERVED", "BROODER_VERIFIED"):
                    svc._release_order_reservation(o, lot, cause="quarantine")
            db.touch(lot)
    return resp.success(svc.serialize_care_log(entry), 201)


@app.route("/livestock-lots/<lid>/care-logs", methods=["GET"])
def list_care_logs(lid):
    uid, role = mw.user_context()
    mw.check_role(role, ALL_READ)
    lot = svc.get_lot(lid)
    entries = [e for e in db.care_logs.values() if e["lot_id"] == lot["id"]]
    return _list_response(entries, [("entry_type", "entry_type")], svc.serialize_care_log)


# ===========================================================================
# Chick orders
# ===========================================================================
@app.route("/chick-orders", methods=["POST"])
def create_chick_order():
    uid, role = mw.user_context()
    mw.check_role(role, ["Customer"])
    data = mw.get_json()
    store_id = svc.req_str(data, "store_id")
    lot_id = svc.req_str(data, "livestock_lot_id")
    account_id = svc.req_str(data, "loyalty_account_id")
    quantity = svc.req_int(data, "quantity", minimum=1)
    pickup_date = svc.parse_iso(data.get("pickup_date"), "pickup_date")
    expected_lot_version = svc.req_int(data, "expected_livestock_lot_version")
    # entity-backed identity (priority 3)
    mw.check_identity(uid, role, account_id)
    # existence (priority 4)
    store = svc.get_store(store_id)
    lot = svc.get_lot(lot_id)
    account = svc.get_account(account_id)
    sched = svc.get_schedule(lot["hatchery_schedule_id"])
    # OCC (priority 5)
    if expected_lot_version != lot["version"]:
        raise errors.err_stale_lot_version()
    # posture gate (priority 6)
    if store["posture"] != "SPRING_PLANTING":
        raise errors.err_posture_not_spring()
    # state preconditions (priority 7)
    if lot["status"] != "ON_SALE":
        raise errors.err_lot_not_on_sale()
    # temporal window (priority 9): both the logical now and the requested
    # pickup_date must fall inside the schedule's closed sale window
    # (PRD §3.2: "sale_window_start is the first instant birds may be sold and
    # sale_window_end the last"; PRD §3.4 pickup_date rule).
    now = db.now()
    if not (sched["sale_window_start"] <= now <= sched["sale_window_end"]):
        raise errors.err_outside_sale_window()
    if not (sched["sale_window_start"] <= pickup_date <= sched["sale_window_end"]):
        raise errors.err_outside_sale_window()
    # constraints (priority 10): min purchase, daily capacity, lot availability
    if quantity < sched["min_purchase_qty"]:
        raise errors.err_min_purchase()
    today = db.now().date()
    reserved_today = 0
    for o in db.chick_orders.values():
        if (o["created_at"].date() == today and o["status"] in ("RESERVED", "BROODER_VERIFIED")):
            o_lot = db.lots.get(o["livestock_lot_id"])
            if o_lot is not None and o_lot["hatchery_schedule_id"] == sched["id"]:
                reserved_today += o["quantity"]
    if reserved_today + quantity > sched["daily_capacity"]:
        raise errors.err_daily_capacity()
    if quantity > lot["quantity_on_hand"]:
        raise errors.err_lot_capacity()
    discount, total = svc.chick_order_total(quantity, sched["base_price_cents_per_bird"])
    order = db.new_common({
        "id": db.new_id(),
        "store_id": store_id,
        "livestock_lot_id": lot_id,
        "loyalty_account_id": account_id,
        "quantity": quantity,
        "pickup_date": pickup_date,
        "unit_price_cents": sched["base_price_cents_per_bird"],
        "discount_pct": discount,
        "total_cents": total,
        "brooder_verified_at": None,
        "fulfilled_at": None,
        "claim_status": "NONE",
        "claimed_mortality_count": 0,
        "approved_claim_count": 0,
        "refund_cents": 0,
        "status": "RESERVED",
    })
    db.chick_orders[order["id"]] = order
    lot["quantity_on_hand"] -= quantity
    db.touch(lot)
    return resp.success(svc.serialize_chick_order(order), 201)


@app.route("/chick-orders", methods=["GET"])
def list_chick_orders():
    uid, role = mw.user_context()
    mw.check_role(role, ALL_READ)
    return _list_response(
        list(db.chick_orders.values()),
        [("store_id", "store_id"), ("livestock_lot_id", "livestock_lot_id"),
         ("loyalty_account_id", "loyalty_account_id"), ("status", "status")],
        svc.serialize_chick_order)


@app.route("/chick-orders/<oid>", methods=["GET"])
def get_chick_order(oid):
    uid, role = mw.user_context()
    mw.check_role(role, ALL_READ)
    return resp.success(svc.serialize_chick_order(svc.get_chick_order(oid)))


@app.route("/chick-orders/<oid>/verify-brooder", methods=["POST"])
def verify_brooder(oid):
    uid, role = mw.user_context()
    mw.check_role(role, ["StoreAssociate"])
    data = mw.get_json()
    heat = svc.req_bool(data, "heat_lamp_ok")
    thermo = svc.req_bool(data, "thermometer_ok")
    bedding = svc.req_bool(data, "bedding_ok")
    order = svc.get_chick_order(oid)
    if order["status"] != "RESERVED":
        raise errors.err_order_not_reserved()
    if not (heat and thermo and bedding):
        raise errors.err_brooder_check_failed()
    order["status"] = "BROODER_VERIFIED"
    order["brooder_verified_at"] = db.now()
    db.touch(order)
    return resp.success(svc.serialize_chick_order(order))


@app.route("/chick-orders/<oid>/fulfill", methods=["POST"])
def fulfill_chick_order(oid):
    uid, role = mw.user_context()
    mw.check_role(role, ["StoreAssociate"])
    order = svc.get_chick_order(oid)
    # state preconditions (priority 7)
    if order["status"] == "RESERVED":
        raise errors.err_order_not_verified()
    if order["status"] != "BROODER_VERIFIED":
        raise errors.err_invalid_state_transition("order is not fulfillable from its state")
    now = db.now()
    lot = svc.get_lot(order["livestock_lot_id"])
    sched = svc.get_schedule(lot["hatchery_schedule_id"])
    # safety (priority 8): brooder freshness, lot ON_SALE, care-log freshness
    if now > order["brooder_verified_at"] + timedelta(hours=72):
        order["status"] = "RESERVED"
        order["brooder_verified_at"] = None
        db.touch(order)
        raise errors.err_brooder_verification_expired()
    if lot["status"] != "ON_SALE":
        raise errors.err_lot_not_on_sale()
    fresh_cutoff = now - timedelta(hours=12)
    has_fresh = any(
        e["lot_id"] == lot["id"] and e["created_at"] >= fresh_cutoff
        for e in db.care_logs.values()
    )
    if not has_fresh:
        raise errors.err_care_log_stale()
    # temporal (priority 9): sale-window grace (expire on lapse)
    if now > sched["sale_window_end"] + timedelta(hours=48):
        order["status"] = "EXPIRED"
        lot["quantity_on_hand"] += order["quantity"]
        db.touch(order)
        db.touch(lot)
        raise errors.err_sale_window_closed()
    order["status"] = "FULFILLED"
    order["fulfilled_at"] = now
    db.touch(order)
    lot["quantity_sold"] += order["quantity"]
    db.touch(lot)
    return resp.success(svc.serialize_chick_order(order))


@app.route("/chick-orders/<oid>/cancel", methods=["POST"])
def cancel_chick_order(oid):
    uid, role = mw.user_context()
    mw.check_role(role, ["Customer", "StoreManager"])
    mw.get_json()  # optional reason
    order = svc.get_chick_order(oid)
    mw.check_identity(uid, role, order["loyalty_account_id"])
    if order["status"] not in ("RESERVED", "BROODER_VERIFIED"):
        raise errors.err_invalid_state_transition("order cannot be cancelled from its state")
    lot = svc.get_lot(order["livestock_lot_id"])
    order["status"] = "CANCELLED"
    db.touch(order)
    if lot["status"] == "SUSPENDED":
        lot["quantity_quarantined"] += order["quantity"]
    else:
        lot["quantity_on_hand"] += order["quantity"]
    db.touch(lot)
    return resp.success(svc.serialize_chick_order(order))


@app.route("/chick-orders/<oid>/mortality-claims", methods=["POST"])
def open_mortality_claim(oid):
    uid, role = mw.user_context()
    mw.check_role(role, ["Customer"])
    data = mw.get_json()
    mortality_count = svc.req_int(data, "mortality_count", minimum=1)
    order = svc.get_chick_order(oid)
    mw.check_identity(uid, role, order["loyalty_account_id"])
    if order["status"] != "FULFILLED":
        raise errors.err_invalid_state_transition("claims require a FULFILLED order")
    if db.now() > order["fulfilled_at"] + timedelta(hours=48):
        raise errors.err_claim_window_expired()
    if mortality_count > order["quantity"] - order["approved_claim_count"]:
        raise errors.err_claim_exceeds_remaining()
    order["claim_status"] = "CLAIMED"
    order["claimed_mortality_count"] = mortality_count
    db.touch(order)
    return resp.success(svc.serialize_chick_order(order), 201)


@app.route("/chick-orders/<oid>/review-mortality-claim", methods=["POST"])
def review_mortality_claim(oid):
    uid, role = mw.user_context()
    mw.check_role(role, ["StoreManager"])
    data = mw.get_json()
    decision = svc.req_enum(data, "decision", {"APPROVE", "REJECT"})
    order = svc.get_chick_order(oid)
    if order["claim_status"] != "CLAIMED":
        raise errors.err_invalid_state_transition("no open claim on this order")
    if decision == "REJECT":
        order["claim_status"] = "REJECTED"
        db.touch(order)
        return resp.success(svc.serialize_chick_order(order))
    # APPROVE: mortality_claim_refund
    refund = svc.round_half_up_int(
        Decimal(order["total_cents"]) * Decimal(order["claimed_mortality_count"])
        / Decimal(order["quantity"]))
    goodwill = refund // 100
    order["claim_status"] = "APPROVED"
    order["approved_claim_count"] += order["claimed_mortality_count"]
    order["refund_cents"] += refund
    db.touch(order)
    acct = db.loyalty_accounts.get(order["loyalty_account_id"])
    if acct is not None:
        svc.post_ledger_entry(account=acct, entry_type="ADJUSTMENT",
                              points_delta=goodwill, store_id=None)
    return resp.success(svc.serialize_chick_order(order))


# ===========================================================================
# Weighted sales
# ===========================================================================
@app.route("/weighted-sales", methods=["POST"])
def create_weighted_sale():
    uid, role = mw.user_context()
    mw.check_role(role, ["StoreAssociate"])
    data = mw.get_json()
    store_id = svc.req_str(data, "store_id")
    sale_kind = svc.req_enum(data, "sale_kind", {"FEED_BULK", "PROPANE_EXCHANGE"})
    container_class = svc.req_enum(data, "container_class", {"BAG_50", "DRUM", "TOTE", "CYLINDER_20"})
    gross = svc.req_num(data, "gross_weight_lbs", gt=0)
    account_id = svc.opt_str(data, "loyalty_account_id")
    if sale_kind == "PROPANE_EXCHANGE" and container_class != "CYLINDER_20":
        raise errors.err_invalid_request("PROPANE_EXCHANGE requires container_class CYLINDER_20")
    store = svc.get_store(store_id)
    if account_id is not None:
        svc.get_account(account_id)
    if store["posture"] == "OFFSEASON":
        raise errors.err_store_floor_closed()
    tare = svc.TARE_TABLE[container_class]
    price, gallons = svc.weighted_sale_price(sale_kind, gross, tare)
    sale = db.new_common({
        "id": db.new_id(),
        "store_id": store_id,
        "loyalty_account_id": account_id,
        "sale_kind": sale_kind,
        "container_class": container_class,
        "gross_weight_lbs": gross,
        "provisional_tare_lbs": tare,
        "measured_tare_lbs": None,
        "provisional_total_cents": price,
        "final_total_cents": None,
        "propane_gallons": gallons if sale_kind == "PROPANE_EXCHANGE" else Decimal("0"),
        "redeem_points": 0,
        "points_redeemed": 0,
        "finalized_at": None,
        "status": "PROVISIONAL",
    })
    db.weighted_sales[sale["id"]] = sale
    return resp.success(svc.serialize_weighted_sale(sale), 201)


@app.route("/weighted-sales", methods=["GET"])
def list_weighted_sales():
    uid, role = mw.user_context()
    mw.check_role(role, ALL_READ)
    return _list_response(
        list(db.weighted_sales.values()),
        [("store_id", "store_id"), ("loyalty_account_id", "loyalty_account_id"),
         ("sale_kind", "sale_kind"), ("status", "status")],
        svc.serialize_weighted_sale)


@app.route("/weighted-sales/<sid>", methods=["GET"])
def get_weighted_sale(sid):
    uid, role = mw.user_context()
    mw.check_role(role, ALL_READ)
    return resp.success(svc.serialize_weighted_sale(svc.get_sale(sid)))


@app.route("/weighted-sales/<sid>/finalize", methods=["POST"])
def finalize_weighted_sale(sid):
    uid, role = mw.user_context()
    mw.check_role(role, ["StoreAssociate"])
    data = mw.get_json()
    measured_tare = svc.req_num(data, "measured_tare_lbs")
    redeem = data.get("redeem_points", 0)
    if not (isinstance(redeem, int) and not isinstance(redeem, bool) and redeem >= 0):
        raise errors.err_invalid_request("redeem_points must be an integer >= 0")
    sale = svc.get_sale(sid)
    account = None
    if sale["loyalty_account_id"] is not None:
        account = svc.get_account(sale["loyalty_account_id"])
    # state (priority 7)
    if sale["status"] != "PROVISIONAL":
        raise errors.err_sale_not_provisional()
    # safety (priority 8): hazmat cap before tare feasibility
    if sale["sale_kind"] == "PROPANE_EXCHANGE":
        store = svc.get_store(sale["store_id"])
        used = Decimal(str(svc.hazmat_gallons_used_today(store)))
        if used + sale["propane_gallons"] > svc.HAZMAT_DAILY_CAP_GAL:
            raise errors.err_hazmat_cap()
    # redemption account state (priority 7 error surfaced at its pinned slot)
    if redeem > 0:
        if account is None or account["status"] != "ACTIVE":
            raise errors.err_account_suspended()
    # constraint (priority 10): tare feasibility
    if not (measured_tare > 0) or measured_tare > sale["gross_weight_lbs"]:
        raise errors.err_tare_exceeds_gross()
    # fiscal (priority 11)
    if redeem > 0 and redeem > account["points_balance"]:
        raise errors.err_insufficient_points()
    # pinned evaluation order: net -> price -> round -> redemption subtraction
    price, _ = svc.weighted_sale_price(sale["sale_kind"], sale["gross_weight_lbs"], measured_tare)
    final_total = max(price - redeem, 0)
    sale["measured_tare_lbs"] = measured_tare
    sale["redeem_points"] = redeem
    sale["final_total_cents"] = final_total
    sale["finalized_at"] = db.now()
    sale["status"] = "FINALIZED"
    if redeem > 0:
        sale["points_redeemed"] = redeem
        svc.post_ledger_entry(account=account, entry_type="REDEMPTION",
                              points_delta=-redeem, store_id=sale["store_id"])
    if account is not None:
        earn_context = "FEED" if sale["sale_kind"] == "FEED_BULK" else "FUEL"
        # PRD §3.6: accrual base is the net-of-redemption amount, which is the
        # already-floored final_total_cents (final_total_cents is itself the
        # price minus redeemed points); subtracting points_redeemed again
        # would double-count the redemption.
        svc.post_ledger_entry(account=account, entry_type="ACCRUAL",
                              base_amount_cents=final_total,
                              earn_context=earn_context, store_id=sale["store_id"])
    db.touch(sale)
    return resp.success(svc.serialize_weighted_sale(sale))


@app.route("/weighted-sales/<sid>/void", methods=["POST"])
def void_weighted_sale(sid):
    uid, role = mw.user_context()
    mw.check_role(role, ["StoreManager"])
    sale = svc.get_sale(sid)
    if sale["status"] != "PROVISIONAL":
        raise errors.err_sale_not_provisional()
    sale["status"] = "VOIDED"
    db.touch(sale)
    return resp.success(svc.serialize_weighted_sale(sale))


# ===========================================================================
# Loyalty accounts and ledger
# ===========================================================================
@app.route("/loyalty-accounts", methods=["POST"])
def create_account():
    uid, role = mw.user_context()
    mw.check_role(role, ["Anonymous"])
    data = mw.get_json()
    full_name = svc.req_str(data, "full_name")
    phone = svc.req_str(data, "phone")
    email = svc.opt_str(data, "email")
    for a in db.loyalty_accounts.values():
        if a["phone"] == phone:
            raise errors.err_phone_taken()
    account = db.new_common({
        "id": db.new_id(),
        "full_name": full_name,
        "phone": phone,
        "email": email,
        "status": "ACTIVE",
        "tier": "NEIGHBOR",
        "points_balance": 0,
        "tier_qualifying_points": 0,
    })
    db.loyalty_accounts[account["id"]] = account
    return resp.success(svc.serialize_account(account), 201)


@app.route("/loyalty-accounts", methods=["GET"])
def list_accounts():
    uid, role = mw.user_context()
    mw.check_role(role, ["RegionalAdmin", "StoreManager", "StoreAssociate"])
    return _list_response(
        list(db.loyalty_accounts.values()),
        [("phone", "phone"), ("status", "status")],
        svc.serialize_account)


@app.route("/loyalty-accounts/lookup", methods=["POST"])
def lookup_account():
    uid, role = mw.user_context()
    mw.check_role(role, ["StoreAssociate"])
    data = mw.get_json()
    phone = svc.req_str(data, "phone")
    for a in db.loyalty_accounts.values():
        if a["phone"] == phone:
            return resp.success(svc.serialize_account(a))
    raise errors.err_phone_not_found()


@app.route("/loyalty-accounts/<aid>", methods=["GET"])
def get_account(aid):
    uid, role = mw.user_context()
    mw.check_role(role, ALL_READ)
    mw.check_identity(uid, role, aid)
    return resp.success(svc.serialize_account(svc.get_account(aid)))


@app.route("/loyalty-accounts/<aid>/set-status", methods=["POST"])
def set_account_status(aid):
    uid, role = mw.user_context()
    mw.check_role(role, ["StoreManager"])
    data = mw.get_json()
    status = svc.req_enum(data, "status", {"ACTIVE", "SUSPENDED", "CLOSED"})
    account = svc.get_account(aid)
    allowed = {("ACTIVE", "SUSPENDED"), ("SUSPENDED", "ACTIVE"), ("ACTIVE", "CLOSED")}
    if (account["status"], status) not in allowed:
        raise errors.err_invalid_state_transition(
            f"account cannot move {account['status']} -> {status}")
    account["status"] = status
    db.touch(account)
    return resp.success(svc.serialize_account(account))


@app.route("/loyalty-accounts/<aid>/ledger-entries", methods=["POST"])
def create_ledger_entry(aid):
    uid, role = mw.user_context()
    mw.check_role(role, ["StoreAssociate"])
    data = mw.get_json()
    entry_type = svc.req_enum(data, "entry_type", {"ACCRUAL", "REDEMPTION", "ADJUSTMENT", "REVERSAL"})
    store_id = svc.opt_str(data, "store_id")
    base_amount_cents = data.get("base_amount_cents")
    earn_context = data.get("earn_context")
    points_delta = data.get("points_delta")
    related_entry_id = svc.opt_str(data, "related_entry_id")

    if entry_type == "ACCRUAL":
        if not isinstance(store_id, str):
            raise errors.err_invalid_request("store_id is required for ACCRUAL")
        if not (isinstance(base_amount_cents, int) and not isinstance(base_amount_cents, bool)
                and base_amount_cents > 0):
            raise errors.err_invalid_request("base_amount_cents > 0 is required for ACCRUAL")
        if not isinstance(earn_context, str) or earn_context not in ("FEED", "FUEL", "OTHER"):
            raise errors.err_invalid_request("earn_context is required for ACCRUAL")
    elif entry_type == "REDEMPTION":
        if not isinstance(store_id, str):
            raise errors.err_invalid_request("store_id is required for REDEMPTION")
        if not (isinstance(points_delta, int) and not isinstance(points_delta, bool)
                and points_delta < 0):
            raise errors.err_invalid_request("points_delta must be negative for REDEMPTION")
    elif entry_type == "ADJUSTMENT":
        if not (isinstance(points_delta, int) and not isinstance(points_delta, bool)):
            raise errors.err_invalid_request("points_delta is required for ADJUSTMENT")
    elif entry_type == "REVERSAL":
        if not isinstance(related_entry_id, str):
            raise errors.err_invalid_request("related_entry_id is required for REVERSAL")
        if not (isinstance(points_delta, int) and not isinstance(points_delta, bool)):
            raise errors.err_invalid_request("points_delta is required for REVERSAL")

    account = svc.get_account(aid)
    store = svc.get_store(store_id) if store_id is not None else None

    # state precondition (priority 7): posting point movement requires an
    # ACTIVE account; suspension gates ledger writes while leaving reads
    # (receipt-free lookup, GET) available.
    if account["status"] != "ACTIVE":
        raise errors.err_account_suspended()

    # referential integrity (priority 12)
    if entry_type == "REVERSAL":
        target = db.ledger_entries.get(related_entry_id)
        if target is None or target["account_id"] != account["id"]:
            raise errors.err_not_found("ERR_ENTRY_NOT_FOUND", "referenced ledger entry")
        # remaining unreversed magnitude of the target
        reversed_mag = sum(
            -e["points_delta"] for e in db.ledger_entries.values()
            if e["entry_type"] == "REVERSAL" and e["related_entry_id"] == target["id"]
        )
        remaining = abs(target["points_delta"]) - reversed_mag
        if points_delta == 0:
            raise errors.err_reversal_mismatch()
        if target["points_delta"] > 0 and not (points_delta < 0):
            raise errors.err_reversal_mismatch()
        if target["points_delta"] < 0 and not (points_delta > 0):
            raise errors.err_reversal_mismatch()
        if abs(points_delta) > remaining:
            raise errors.err_reversal_mismatch()

    # fiscal guard: redemption cannot drive balance negative
    if entry_type in ("REDEMPTION", "ADJUSTMENT", "REVERSAL") and points_delta is not None:
        if account["points_balance"] + points_delta < 0:
            raise errors.err_insufficient_points()

    entry = svc.post_ledger_entry(
        account=account,
        entry_type=entry_type,
        points_delta=points_delta,
        store_id=store_id if store else None,
        base_amount_cents=base_amount_cents,
        earn_context=earn_context,
        related_entry_id=related_entry_id,
    )
    return resp.success(svc.serialize_ledger_entry(entry), 201)


@app.route("/loyalty-accounts/<aid>/ledger-entries", methods=["GET"])
def list_account_ledger_entries(aid):
    uid, role = mw.user_context()
    mw.check_role(role, ALL_READ)
    account = svc.get_account(aid)
    entries = [e for e in db.ledger_entries.values() if e["account_id"] == account["id"]]
    return _list_response(entries, [("entry_type", "entry_type")], svc.serialize_ledger_entry)


@app.route("/loyalty-ledger-entries", methods=["GET"])
def list_ledger_entries():
    uid, role = mw.user_context()
    mw.check_role(role, ["RegionalAdmin", "StoreManager", "StoreAssociate"])
    return _list_response(
        list(db.ledger_entries.values()),
        [("account_id", "account_id"), ("store_id", "store_id"),
         ("related_entry_id", "related_entry_id")],
        svc.serialize_ledger_entry)


@app.route("/loyalty-ledger-entries/<eid>", methods=["GET"])
def get_ledger_entry(eid):
    uid, role = mw.user_context()
    mw.check_role(role, ALL_READ)
    return resp.success(svc.serialize_ledger_entry(svc.get_entry(eid)))


@app.route("/loyalty-accounts/<aid>/offers", methods=["GET"])
def get_offers(aid):
    uid, role = mw.user_context()
    mw.check_role(role, ["StoreAssociate", "StoreManager", "Customer"])
    mw.check_identity(uid, role, aid)
    store_id = request.args.get("store_id")
    if not isinstance(store_id, str) or store_id == "":
        raise errors.err_invalid_request("store_id query parameter is required")
    account = svc.get_account(aid)
    store = svc.get_store(store_id)
    season_points = sum(
        e["points_delta"] for e in db.ledger_entries.values()
        if e["account_id"] == account["id"]
        and e["entry_type"] == "ACCRUAL"
        and e["posture_at_entry"] == store["posture"]
    )
    fuel_discount = min(svc.FUEL_CENTS_PER_STEP * (season_points // svc.FUEL_POINTS_STEP),
                        svc.FUEL_MAX_CENTS_PER_GAL)
    feed_coupon = svc.FEED_COUPON_CENTS if (
        store["posture"] == "FALL_FEED" and account["tier"] in ("RANCH_HAND", "HOMESTEAD")) else 0
    return resp.success({
        "fuel_discount_cents_per_gal": fuel_discount,
        "feed_coupon_cents": feed_coupon,
        "season_qualifying_points": season_points,
        "eligible": (fuel_discount > 0) or (feed_coupon > 0),
    })


# ===========================================================================
# Pickup orders (BOPIS)
# ===========================================================================
@app.route("/pickup-orders", methods=["POST"])
def create_pickup_order():
    uid, role = mw.user_context()
    mw.check_role(role, ["Customer"])
    data = mw.get_json()
    store_id = svc.req_str(data, "store_id")
    account_id = svc.req_str(data, "loyalty_account_id")
    item_sku = svc.req_str(data, "item_sku")
    size_class = svc.req_enum(data, "item_size_class", {"M", "L", "XL"})
    requires_loadout = svc.req_bool(data, "requires_loadout_assistance")
    mw.check_identity(uid, role, account_id)
    svc.get_store(store_id)
    svc.get_account(account_id)
    order = db.new_common({
        "id": db.new_id(),
        "store_id": store_id,
        "loyalty_account_id": account_id,
        "item_sku": item_sku,
        "item_size_class": size_class,
        "requires_loadout_assistance": requires_loadout,
        "staging_bay_id": None,
        "ready_at": None,
        "pickup_deadline": None,
        "fulfillment_status": "PLACED",
        "loadout_status": "NOT_REQUIRED",
    })
    db.pickup_orders[order["id"]] = order
    return resp.success(svc.serialize_pickup_order(order), 201)


@app.route("/pickup-orders", methods=["GET"])
def list_pickup_orders():
    uid, role = mw.user_context()
    mw.check_role(role, ALL_READ)
    return _list_response(
        list(db.pickup_orders.values()),
        [("store_id", "store_id"), ("loyalty_account_id", "loyalty_account_id"),
         ("staging_bay_id", "staging_bay_id"), ("status", "fulfillment_status")],
        svc.serialize_pickup_order)


@app.route("/pickup-orders/<oid>", methods=["GET"])
def get_pickup_order(oid):
    uid, role = mw.user_context()
    mw.check_role(role, ALL_READ)
    return resp.success(svc.serialize_pickup_order(svc.get_pickup_order(oid)))


def _release_bay(order):
    if order["staging_bay_id"] is not None:
        bay = db.bays.get(order["staging_bay_id"])
        if bay is not None and bay["status"] == "OCCUPIED":
            bay["status"] = "AVAILABLE"
            db.touch(bay)


@app.route("/pickup-orders/<oid>/stage", methods=["POST"])
def stage_pickup_order(oid):
    uid, role = mw.user_context()
    mw.check_role(role, ["StoreAssociate"])
    order = svc.get_pickup_order(oid)
    if order["fulfillment_status"] != "PLACED":
        raise errors.err_invalid_state_transition("stage requires fulfillment PLACED")
    bay = svc.staging_bay_selection(order["store_id"], order["item_size_class"])
    order["staging_bay_id"] = bay["id"]
    order["fulfillment_status"] = "STAGED"
    db.touch(order)
    bay["status"] = "OCCUPIED"
    db.touch(bay)
    return resp.success(svc.serialize_pickup_order(order))


@app.route("/pickup-orders/<oid>/mark-ready", methods=["POST"])
def mark_ready(oid):
    uid, role = mw.user_context()
    mw.check_role(role, ["StoreAssociate"])
    order = svc.get_pickup_order(oid)
    if order["fulfillment_status"] != "STAGED":
        raise errors.err_invalid_state_transition("mark-ready requires fulfillment STAGED")
    now = db.now()
    order["ready_at"] = now
    order["pickup_deadline"] = now + timedelta(days=5)
    order["fulfillment_status"] = "READY_FOR_PICKUP"
    db.touch(order)
    return resp.success(svc.serialize_pickup_order(order))


@app.route("/pickup-orders/<oid>/request-loadout", methods=["POST"])
def request_loadout(oid):
    uid, role = mw.user_context()
    mw.check_role(role, ["Customer"])
    order = svc.get_pickup_order(oid)
    mw.check_identity(uid, role, order["loyalty_account_id"])
    if order["fulfillment_status"] != "READY_FOR_PICKUP":
        raise errors.err_invalid_state_transition("request-loadout requires READY_FOR_PICKUP")
    if not order["requires_loadout_assistance"]:
        raise errors.err_loadout_not_applicable()
    if order["loadout_status"] != "NOT_REQUIRED":
        raise errors.err_invalid_state_transition("loadout already requested")
    order["loadout_status"] = "ASSISTANCE_REQUESTED"
    db.touch(order)
    return resp.success(svc.serialize_pickup_order(order))


@app.route("/pickup-orders/<oid>/complete-loadout", methods=["POST"])
def complete_loadout(oid):
    uid, role = mw.user_context()
    mw.check_role(role, ["StoreAssociate"])
    order = svc.get_pickup_order(oid)
    if order["loadout_status"] != "ASSISTANCE_REQUESTED":
        raise errors.err_invalid_state_transition("complete-loadout requires ASSISTANCE_REQUESTED")
    if order["fulfillment_status"] != "READY_FOR_PICKUP":
        raise errors.err_invalid_state_transition("complete-loadout requires READY_FOR_PICKUP")
    order["loadout_status"] = "LOADOUT_DONE"
    db.touch(order)
    return resp.success(svc.serialize_pickup_order(order))


@app.route("/pickup-orders/<oid>/complete", methods=["POST"])
def complete_pickup_order(oid):
    uid, role = mw.user_context()
    mw.check_role(role, ["StoreAssociate"])
    order = svc.get_pickup_order(oid)
    if order["fulfillment_status"] != "READY_FOR_PICKUP":
        raise errors.err_invalid_state_transition("complete requires READY_FOR_PICKUP")
    if order["loadout_status"] == "ASSISTANCE_REQUESTED":
        raise errors.err_loadout_not_completed()
    if db.now() > order["pickup_deadline"]:
        order["fulfillment_status"] = "EXPIRED"
        db.touch(order)
        _release_bay(order)
        raise errors.err_pickup_window_expired()
    order["fulfillment_status"] = "COMPLETED"
    db.touch(order)
    _release_bay(order)
    return resp.success(svc.serialize_pickup_order(order))


@app.route("/pickup-orders/<oid>/cancel", methods=["POST"])
def cancel_pickup_order(oid):
    uid, role = mw.user_context()
    mw.check_role(role, ["Customer", "StoreManager"])
    order = svc.get_pickup_order(oid)
    mw.check_identity(uid, role, order["loyalty_account_id"])
    if order["fulfillment_status"] not in ("PLACED", "STAGED", "READY_FOR_PICKUP"):
        raise errors.err_invalid_state_transition("order cannot be cancelled from its state")
    order["fulfillment_status"] = "CANCELLED"
    db.touch(order)
    _release_bay(order)
    return resp.success(svc.serialize_pickup_order(order))


# ===========================================================================
# Service events and bookings
# ===========================================================================
@app.route("/service-events", methods=["POST"])
def create_event():
    uid, role = mw.user_context()
    mw.check_role(role, ["StoreManager"])
    data = mw.get_json()
    store_id = svc.req_str(data, "store_id")
    event_kind = svc.req_enum(data, "event_kind", {"PET_WASH", "VET_CLINIC"})
    resource_name = svc.req_str(data, "resource_name")
    event_date = svc.parse_iso(data.get("event_date"), "event_date")
    sws = svc.parse_iso(data.get("slot_window_start"), "slot_window_start")
    swe = svc.parse_iso(data.get("slot_window_end"), "slot_window_end")
    slot_len = svc.req_int(data, "slot_length_minutes", minimum=5)
    buffer_min = svc.req_int(data, "cleanup_buffer_minutes", minimum=0)
    capacity = svc.req_int(data, "capacity_per_slot", minimum=1)
    requires_vaccine = svc.req_bool(data, "requires_vaccine_record")
    if not swe > sws:
        raise errors.err_invalid_request("slot_window_end must be > slot_window_start")
    svc.get_store(store_id)
    event = db.new_common({
        "id": db.new_id(),
        "store_id": store_id,
        "event_kind": event_kind,
        "resource_name": resource_name,
        "event_date": event_date,
        "slot_window_start": sws,
        "slot_window_end": swe,
        "slot_length_minutes": slot_len,
        "cleanup_buffer_minutes": buffer_min,
        "capacity_per_slot": capacity,
        "requires_vaccine_record": requires_vaccine,
        "status": "DRAFT",
    })
    db.service_events[event["id"]] = event
    return resp.success(svc.serialize_event(event), 201)


@app.route("/service-events", methods=["GET"])
def list_events():
    uid, role = mw.user_context()
    mw.check_role(role, ALL_READ)
    return _list_response(
        list(db.service_events.values()),
        [("store_id", "store_id"), ("event_kind", "event_kind"), ("status", "status")],
        svc.serialize_event)


@app.route("/service-events/<eid>", methods=["GET"])
def get_event(eid):
    uid, role = mw.user_context()
    mw.check_role(role, ALL_READ)
    return resp.success(svc.serialize_event(svc.get_event(eid)))


@app.route("/service-events/<eid>/publish", methods=["POST"])
def publish_event(eid):
    uid, role = mw.user_context()
    mw.check_role(role, ["StoreManager"])
    event = svc.get_event(eid)
    if event["status"] != "DRAFT":
        raise errors.err_invalid_state_transition("publish requires DRAFT")
    event["status"] = "PUBLISHED"
    db.touch(event)
    return resp.success(svc.serialize_event(event))


@app.route("/service-events/<eid>/cancel", methods=["POST"])
def cancel_event(eid):
    uid, role = mw.user_context()
    mw.check_role(role, ["StoreManager"])
    event = svc.get_event(eid)
    if event["status"] not in ("DRAFT", "PUBLISHED"):
        raise errors.err_invalid_state_transition("event cannot be cancelled from its state")
    was_published = event["status"] == "PUBLISHED"
    event["status"] = "CANCELLED"
    db.touch(event)
    if was_published:
        for b in db.event_bookings.values():
            if b["service_event_id"] == event["id"] and b["status"] in ("BOOKED", "CHECKED_IN"):
                b["status"] = "CANCELLED"
                db.touch(b)
    return resp.success(svc.serialize_event(event))


@app.route("/event-bookings", methods=["POST"])
def create_booking():
    uid, role = mw.user_context()
    mw.check_role(role, ["Customer"])
    data = mw.get_json()
    event_id = svc.req_str(data, "service_event_id")
    account_id = svc.req_str(data, "loyalty_account_id")
    slot_start = svc.parse_iso(data.get("slot_start"), "slot_start")
    vaccine_confirmed = svc.opt_bool(data, "vaccine_record_confirmed", default=False)
    mw.check_identity(uid, role, account_id)
    event = svc.get_event(event_id)
    svc.get_account(account_id)
    slot_end = slot_start + timedelta(minutes=event["slot_length_minutes"])
    if (slot_start.date() != event["event_date"].date()
            or slot_start < event["slot_window_start"]
            or slot_end > event["slot_window_end"]):
        raise errors.err_invalid_request(
            "slot must fall on event_date within [slot_window_start, slot_window_end]")
    if event["status"] != "PUBLISHED":
        raise errors.err_event_not_published()
    if event["requires_vaccine_record"] and not vaccine_confirmed:
        raise errors.err_vaccine_record_required()
    svc.event_booking_overlap_check(event, slot_start, slot_end)
    booking = db.new_common({
        "id": db.new_id(),
        "service_event_id": event["id"],
        "loyalty_account_id": account_id,
        "slot_start": slot_start,
        "slot_end": slot_end,
        "vaccine_record_confirmed": bool(vaccine_confirmed),
        "status": "BOOKED",
    })
    db.event_bookings[booking["id"]] = booking
    return resp.success(svc.serialize_booking(booking), 201)


@app.route("/event-bookings", methods=["GET"])
def list_bookings():
    uid, role = mw.user_context()
    mw.check_role(role, ALL_READ)
    return _list_response(
        list(db.event_bookings.values()),
        [("service_event_id", "service_event_id"),
         ("loyalty_account_id", "loyalty_account_id"), ("status", "status")],
        svc.serialize_booking)


@app.route("/event-bookings/<bid>", methods=["GET"])
def get_booking(bid):
    uid, role = mw.user_context()
    mw.check_role(role, ALL_READ)
    return resp.success(svc.serialize_booking(svc.get_booking(bid)))


@app.route("/event-bookings/<bid>/check-in", methods=["POST"])
def check_in_booking(bid):
    uid, role = mw.user_context()
    mw.check_role(role, ["StoreAssociate"])
    booking = svc.get_booking(bid)
    if booking["status"] != "BOOKED":
        raise errors.err_invalid_state_transition("check-in requires BOOKED")
    now = db.now()
    if not (booking["slot_start"] - timedelta(minutes=15) <= now <= booking["slot_end"]):
        raise errors.err_outside_checkin_window()
    booking["status"] = "CHECKED_IN"
    db.touch(booking)
    return resp.success(svc.serialize_booking(booking))


@app.route("/event-bookings/<bid>/complete", methods=["POST"])
def complete_booking(bid):
    uid, role = mw.user_context()
    mw.check_role(role, ["StoreAssociate"])
    booking = svc.get_booking(bid)
    if booking["status"] != "CHECKED_IN":
        raise errors.err_invalid_state_transition("complete requires CHECKED_IN")
    booking["status"] = "COMPLETED"
    db.touch(booking)
    return resp.success(svc.serialize_booking(booking))


@app.route("/event-bookings/<bid>/mark-no-show", methods=["POST"])
def mark_no_show(bid):
    uid, role = mw.user_context()
    mw.check_role(role, ["StoreAssociate"])
    booking = svc.get_booking(bid)
    if booking["status"] != "BOOKED":
        raise errors.err_invalid_state_transition("mark-no-show requires BOOKED")
    if not db.now() > booking["slot_end"]:
        raise errors.err_booking_not_expired()
    booking["status"] = "NO_SHOW"
    db.touch(booking)
    return resp.success(svc.serialize_booking(booking))


@app.route("/event-bookings/<bid>/cancel", methods=["POST"])
def cancel_booking(bid):
    uid, role = mw.user_context()
    mw.check_role(role, ["Customer", "StoreManager"])
    booking = svc.get_booking(bid)
    mw.check_identity(uid, role, booking["loyalty_account_id"])
    if booking["status"] != "BOOKED":
        raise errors.err_invalid_state_transition("cancel requires BOOKED")
    booking["status"] = "CANCELLED"
    db.touch(booking)
    return resp.success(svc.serialize_booking(booking))


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", "10000")))
