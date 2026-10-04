"""Clock, stores, staff, stations, plush models, consumables, collection drops,
customers, and the consignment settlement."""
from flask import Blueprint

from core import (
    ROLE_ASSOCIATE,
    ROLE_CUSTOMER,
    ROLE_MANAGER,
    ROLE_PARTY_HOST,
    body,
    db,
    endpoint,
    err,
    fmt_dt,
    get_or_404,
    new_row,
    now,
    req_bool,
    req_datetime,
    req_enum,
    req_int,
    req_str,
    respond_list,
    respond_object,
    respond_raw,
    touch,
)
from domain import auto_confirm_parties, rhu_int, COMMISSION_PCT, WORKSHOP_TERMINAL

bp = Blueprint("admin", __name__)

ALL_ROLES = (ROLE_CUSTOMER, ROLE_ASSOCIATE, ROLE_PARTY_HOST, ROLE_MANAGER)
MANAGER = (ROLE_MANAGER,)
ASSOC_MGR = (ROLE_ASSOCIATE, ROLE_MANAGER)


# ---------------------------------------------------------------------------
# Logical clock (PRD section 2.4)
# ---------------------------------------------------------------------------
@bp.route("/_clock/set_current_utc", methods=["POST"])
@endpoint(*MANAGER)
def set_clock():
    data = body()
    target = req_datetime(data, "to_iso8601")
    if target < db.clock:
        err("ERR_OUTSIDE_TIME_WINDOW", "The logical clock cannot move backwards.")
    db.clock = target
    auto_confirm_parties()
    return respond_raw({"current_utc": fmt_dt(db.clock)})


# ---------------------------------------------------------------------------
# Stores
# ---------------------------------------------------------------------------
@bp.route("/stores", methods=["POST"])
@endpoint(*MANAGER)
def create_store():
    data = body()
    name = req_str(data, "name")
    rooms = req_int(data, "party_room_count", minimum=1)
    store = new_row(name=name, party_room_count=rooms)
    db.stores[store["id"]] = store
    return respond_object(store, status=201)


@bp.route("/stores/<store_id>", methods=["GET"])
@endpoint(*ALL_ROLES)
def get_store(store_id):
    return respond_object(get_or_404("stores", store_id, "store"))


@bp.route("/stores/<store_id>/staff", methods=["GET"])
@endpoint(*ASSOC_MGR)
def list_store_staff(store_id):
    get_or_404("stores", store_id, "store")
    return respond_list([s for s in db.staff.values() if s["store_id"] == store_id])


@bp.route("/stores/<store_id>/stations", methods=["GET"])
@endpoint(*ASSOC_MGR)
def list_store_stations(store_id):
    get_or_404("stores", store_id, "store")
    return respond_list([s for s in db.stations.values() if s["store_id"] == store_id])


@bp.route("/stores/<store_id>/workshops", methods=["GET"])
@endpoint(*ASSOC_MGR)
def list_store_workshops(store_id):
    get_or_404("stores", store_id, "store")
    rows = [w for w in db.workshops.values() if w["store_id"] == store_id]
    status = _status_filter()
    if status:
        rows = [w for w in rows if w["status"] == status]
    return respond_list(rows)


@bp.route("/stores/<store_id>/parties", methods=["GET"])
@endpoint(ROLE_PARTY_HOST, ROLE_MANAGER)
def list_store_parties(store_id):
    get_or_404("stores", store_id, "store")
    return respond_list([p for p in db.parties.values() if p["store_id"] == store_id])


@bp.route("/stores/<store_id>/appointment-blocks", methods=["GET"])
@endpoint(ROLE_PARTY_HOST, ROLE_MANAGER)
def list_store_appointment_blocks(store_id):
    get_or_404("stores", store_id, "store")
    return respond_list(
        [b for b in db.appointment_blocks.values() if b["store_id"] == store_id]
    )


@bp.route("/stores/<store_id>/consumables", methods=["GET"])
@endpoint(*ASSOC_MGR)
def list_store_consumables(store_id):
    get_or_404("stores", store_id, "store")
    return respond_list([c for c in db.consumables.values() if c["store_id"] == store_id])


@bp.route("/stores/<store_id>/build-ship-orders", methods=["GET"])
@endpoint(*ASSOC_MGR)
def list_store_build_ship_orders(store_id):
    get_or_404("stores", store_id, "store")
    rows = [o for o in db.build_ship_orders.values() if o["store_id"] == store_id]
    status = _status_filter()
    if status:
        rows = [o for o in rows if o["status"] == status]
    return respond_list(rows)


@bp.route("/stores/<store_id>/consignments/run", methods=["POST"])
@endpoint(*MANAGER)
def run_consignment_settlement(store_id):
    get_or_404("stores", store_id, "store")
    data = body()
    window_start = req_datetime(data, "window_start")
    window_end = req_datetime(data, "window_end")
    # consignment_settlement (PRD section 3.8): pinned order gmv -> commission
    # -> bonus over the half-open handoff window [window_start, window_end).
    eligible = []
    for order in db.build_ship_orders.values():
        if order["store_id"] != store_id or order["status"] != "HANDED_TO_CARRIER":
            continue
        handed = order["handed_over_at"]
        if handed is not None and window_start <= handed < window_end:
            eligible.append(order)
    gmv = 0
    for order in eligible:
        session = db.workshops.get(order["workshop_session_id"])
        if session is not None:
            gmv += session["total_price_cents"]
    commission = rhu_int(gmv * COMMISSION_PCT, 100)
    bonus = rhu_int(commission, max(len(eligible), 1))
    return respond_raw(
        {
            "gmv_cents": gmv,
            "commission_cents": commission,
            "store_bonus_cents": bonus,
            "eligible_order_count": len(eligible),
        }
    )


def _status_filter():
    from flask import request

    value = request.args.get("status")
    return value.strip() if isinstance(value, str) and value.strip() else None


# ---------------------------------------------------------------------------
# Staff
# ---------------------------------------------------------------------------
@bp.route("/staff", methods=["POST"])
@endpoint(*MANAGER)
def create_staff():
    data = body()
    store = get_or_404("stores", data.get("store_id"), "store")
    display_name = req_str(data, "display_name")
    role_title = req_enum(data, "role_title", ("ASSOCIATE", "PARTY_HOST", "MANAGER"))
    member = new_row(
        store_id=store["id"], display_name=display_name, role_title=role_title
    )
    db.staff[member["id"]] = member
    return respond_object(member, status=201)


@bp.route("/staff/<staff_id>", methods=["GET"])
@endpoint(ROLE_ASSOCIATE, ROLE_PARTY_HOST, ROLE_MANAGER)
def get_staff(staff_id):
    return respond_object(get_or_404("staff", staff_id, "staff member"))


@bp.route("/staff/<staff_id>/appointment-blocks", methods=["GET"])
@endpoint(*ASSOC_MGR)
def list_staff_appointment_blocks(staff_id):
    get_or_404("staff", staff_id, "staff member")
    return respond_list(
        [
            b
            for b in db.appointment_blocks.values()
            if b["reserved_host_id"] == staff_id
        ]
    )


# ---------------------------------------------------------------------------
# Stations
# ---------------------------------------------------------------------------
@bp.route("/stations", methods=["POST"])
@endpoint(*MANAGER)
def create_station():
    data = body()
    store = get_or_404("stores", data.get("store_id"), "store")
    station_type = req_enum(
        data, "station_type", ("SELECT", "STUFF", "SOUND", "BATHE", "DRESS")
    )
    capacity = req_int(data, "capacity", minimum=1)
    station = new_row(
        store_id=store["id"], station_type=station_type, capacity=capacity
    )
    db.stations[station["id"]] = station
    return respond_object(station, status=201)


@bp.route("/stations/<station_id>", methods=["GET"])
@endpoint(*ASSOC_MGR)
def get_station(station_id):
    return respond_object(get_or_404("stations", station_id, "station"))


@bp.route("/stations/<station_id>/workshops", methods=["GET"])
@endpoint(*ASSOC_MGR)
def list_station_workshops(station_id):
    get_or_404("stations", station_id, "station")
    return respond_list(
        [w for w in db.workshops.values() if w["assigned_station_id"] == station_id]
    )


# ---------------------------------------------------------------------------
# Plush models
# ---------------------------------------------------------------------------
@bp.route("/plush-models", methods=["POST"])
@endpoint(*MANAGER)
def create_plush_model():
    data = body()
    name = req_str(data, "name")
    sku = req_str(data, "sku")
    base_price = req_int(data, "base_price_cents", minimum=0)
    is_licensed = req_bool(data, "is_licensed")
    stuffing = req_int(data, "required_stuffing_grams", minimum=1)
    chip_ok = req_bool(data, "sound_chip_compatible")
    if any(m["sku"] == sku for m in db.plush_models.values()):
        err("ERR_VALIDATION", "A plush model with this sku already exists.")
    model = new_row(
        name=name,
        sku=sku,
        base_price_cents=base_price,
        is_licensed=is_licensed,
        required_stuffing_grams=stuffing,
        sound_chip_compatible=chip_ok,
    )
    db.plush_models[model["id"]] = model
    return respond_object(model, status=201)


@bp.route("/plush-models/<model_id>", methods=["GET"])
@endpoint(*ALL_ROLES)
def get_plush_model(model_id):
    return respond_object(get_or_404("plush_models", model_id, "plush model"))


@bp.route("/plush-models/<model_id>/workshops", methods=["GET"])
@endpoint(*ASSOC_MGR)
def list_plush_model_workshops(model_id):
    get_or_404("plush_models", model_id, "plush model")
    return respond_list(
        [w for w in db.workshops.values() if w["plush_model_id"] == model_id]
    )


@bp.route("/plush-models/<model_id>/collection-drops", methods=["GET"])
@endpoint(ROLE_CUSTOMER, ROLE_ASSOCIATE, ROLE_MANAGER)
def list_plush_model_collection_drops(model_id):
    get_or_404("plush_models", model_id, "plush model")
    return respond_list(
        [d for d in db.collection_drops.values() if d["plush_model_id"] == model_id]
    )


@bp.route("/plush-models/<model_id>/build-ship-orders", methods=["GET"])
@endpoint(*ASSOC_MGR)
def list_plush_model_build_ship_orders(model_id):
    get_or_404("plush_models", model_id, "plush model")
    return respond_list(
        [o for o in db.build_ship_orders.values() if o["plush_model_id"] == model_id]
    )


@bp.route("/plush-models/<model_id>/animals", methods=["GET"])
@endpoint(*ASSOC_MGR)
def list_plush_model_animals(model_id):
    get_or_404("plush_models", model_id, "plush model")
    return respond_list(
        [a for a in db.animals.values() if a["plush_model_id"] == model_id]
    )


# ---------------------------------------------------------------------------
# Consumables
# ---------------------------------------------------------------------------
@bp.route("/consumables", methods=["POST"])
@endpoint(*MANAGER)
def create_consumable():
    data = body()
    store = get_or_404("stores", data.get("store_id"), "store")
    consumable_type = req_enum(
        data, "consumable_type", ("STUFFING_FIBER", "SOUND_CHIP")
    )
    initial_qty = req_int(data, "initial_qty", minimum=0)
    row = new_row(
        store_id=store["id"],
        consumable_type=consumable_type,
        on_hand_qty=initial_qty,
        initial_qty=initial_qty,
    )
    db.consumables[row["id"]] = row
    return respond_object(row, status=201)


@bp.route("/consumables/<consumable_id>", methods=["GET"])
@endpoint(*ASSOC_MGR)
def get_consumable(consumable_id):
    return respond_object(get_or_404("consumables", consumable_id, "consumable"))


@bp.route("/consumables/<consumable_id>/restock", methods=["POST"])
@endpoint(*MANAGER)
def restock_consumable(consumable_id):
    row = get_or_404("consumables", consumable_id, "consumable")
    data = body()
    quantity = req_int(data, "quantity", minimum=0)
    row["on_hand_qty"] += quantity
    touch(row)
    return respond_object(row)


# ---------------------------------------------------------------------------
# Collection drops (PRD section 3.2)
# ---------------------------------------------------------------------------
@bp.route("/collection-drops", methods=["POST"])
@endpoint(*MANAGER)
def create_collection_drop():
    data = body()
    model = get_or_404("plush_models", data.get("plush_model_id"), "plush model")
    if not model["is_licensed"]:
        err(
            "ERR_REFERENTIAL_INTEGRITY",
            "A collection drop must reference a licensed plush model.",
        )
    name = req_str(data, "name")
    drop_start = req_datetime(data, "drop_start")
    drop_end = req_datetime(data, "drop_end")
    per_customer_limit = req_int(data, "per_customer_limit", minimum=1)
    total_units = req_int(data, "total_units", minimum=1)
    drop = new_row(
        name=name,
        plush_model_id=model["id"],
        drop_start=drop_start,
        drop_end=drop_end,
        per_customer_limit=per_customer_limit,
        total_units=total_units,
        units_claimed=0,
    )
    db.collection_drops[drop["id"]] = drop
    return respond_object(drop, status=201)


@bp.route("/collection-drops/<drop_id>", methods=["GET"])
@endpoint(ROLE_CUSTOMER, ROLE_ASSOCIATE, ROLE_MANAGER)
def get_collection_drop(drop_id):
    return respond_object(get_or_404("collection_drops", drop_id, "collection drop"))


@bp.route("/collection-drops/<drop_id>/workshops", methods=["GET"])
@endpoint(*ASSOC_MGR)
def list_collection_drop_workshops(drop_id):
    get_or_404("collection_drops", drop_id, "collection drop")
    return respond_list(
        [w for w in db.workshops.values() if w["collection_drop_id"] == drop_id]
    )


# ---------------------------------------------------------------------------
# Customers
# ---------------------------------------------------------------------------
@bp.route("/customers", methods=["POST"])
@endpoint(ROLE_CUSTOMER)
def create_customer():
    data = body()
    email = req_str(data, "email")
    full_name = req_str(data, "full_name")
    if any(c["email"] == email for c in db.customers.values()):
        err("ERR_VALIDATION", "A customer with this email already exists.")
    customer = new_row(email=email, full_name=full_name)
    db.customers[customer["id"]] = customer
    return respond_object(customer, status=201)


@bp.route("/customers/<customer_id>", methods=["GET"])
@endpoint(ROLE_CUSTOMER, ROLE_MANAGER)
def get_customer(customer_id):
    return respond_object(get_or_404("customers", customer_id, "customer"))


@bp.route("/customers/<customer_id>/workshops", methods=["GET"])
@endpoint(ROLE_CUSTOMER, ROLE_MANAGER)
def list_customer_workshops(customer_id):
    get_or_404("customers", customer_id, "customer")
    return respond_list(
        [w for w in db.workshops.values() if w["customer_id"] == customer_id]
    )


@bp.route("/customers/<customer_id>/animals", methods=["GET"])
@endpoint(ROLE_CUSTOMER, ROLE_MANAGER)
def list_customer_animals(customer_id):
    get_or_404("customers", customer_id, "customer")
    return respond_list(
        [a for a in db.animals.values() if a["customer_id"] == customer_id]
    )


@bp.route("/customers/<customer_id>/registries", methods=["GET"])
@endpoint(ROLE_CUSTOMER, ROLE_MANAGER)
def list_customer_registries(customer_id):
    get_or_404("customers", customer_id, "customer")
    return respond_list(
        [r for r in db.registries.values() if r["customer_id"] == customer_id]
    )


@bp.route("/customers/<customer_id>/parties", methods=["GET"])
@endpoint(ROLE_CUSTOMER, ROLE_MANAGER)
def list_customer_parties(customer_id):
    get_or_404("customers", customer_id, "customer")
    return respond_list(
        [p for p in db.parties.values() if p["customer_id"] == customer_id]
    )


@bp.route("/customers/<customer_id>/build-ship-orders", methods=["GET"])
@endpoint(ROLE_CUSTOMER, ROLE_MANAGER)
def list_customer_build_ship_orders(customer_id):
    get_or_404("customers", customer_id, "customer")
    return respond_list(
        [o for o in db.build_ship_orders.values() if o["customer_id"] == customer_id]
    )
