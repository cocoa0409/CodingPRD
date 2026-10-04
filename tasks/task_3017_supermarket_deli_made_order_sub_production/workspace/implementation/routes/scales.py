"""ScalePriceFile and Label groups (PRD 3.6)."""
from errors import fail, invalid
from http_support import (
    Endpoint, as_int, as_number, as_string, body, envelope_array, opt, query,
    req,
)
from response import ok_object
from util import norm_dt, parse_dt, to_dec
import calc
import services as svc
import views

READ_ROLES = ["PlatformAdmin", "DeliManager", "DeliClerk", "BakeryCoordinator",
              "ScaleOperator"]
SCALE_ROLES = ["ScaleOperator", "DeliManager"]
LABEL_ROLES = ["ScaleOperator", "DeliClerk", "DeliManager"]

MAX_LABEL_WEIGHT_LBS = 10
SUBJECT_TYPES = ("SUB_TICKET", "PRODUCTION_BATCH", "CATERING_PLATTER")


def register(app):
    Endpoint(app, "POST", "/deli/price-files", SCALE_ROLES, create_file)
    Endpoint(app, "GET", "/deli/price-files/<id>", READ_ROLES, get_file)
    Endpoint(app, "GET", "/deli/price-files", READ_ROLES, list_files)
    Endpoint(app, "POST", "/deli/price-files/<id>/activate", SCALE_ROLES, activate)
    Endpoint(app, "POST", "/deli/price-files/<id>/retract", SCALE_ROLES, retract)
    Endpoint(app, "POST", "/deli/price-files/<id>/reactivate", SCALE_ROLES, reactivate)
    Endpoint(app, "GET", "/deli/active-price-file", READ_ROLES, active_file)

    Endpoint(app, "POST", "/deli/labels", LABEL_ROLES, create_label)
    Endpoint(app, "GET", "/deli/labels/<id>", READ_ROLES, get_label)
    Endpoint(app, "GET", "/deli/labels", READ_ROLES, list_labels)


def create_file(store, actor, view_args):
    payload = body()
    store_id = as_string(req(payload, "store_id"), "store_id")
    svc.get_store(store, store_id)
    file_label = as_string(req(payload, "file_label"), "file_label")
    if any(f["store_id"] == store_id and f["file_label"] == file_label
           for f in store.price_files.values()):
        invalid("file_label must be unique within the store.")
    effective_from = _instant(req(payload, "effective_from"), "effective_from")
    effective_to = _instant(req(payload, "effective_to"), "effective_to")
    if parse_dt(effective_to) <= parse_dt(effective_from):
        invalid("effective_to must be strictly after effective_from.")
    count = as_int(req(payload, "item_price_count"), "item_price_count")
    if count < 0:
        invalid("item_price_count must not be negative.")
    row = svc.create(store, "price_files", {
        "store_id": store_id,
        "file_label": file_label,
        "effective_from": effective_from,
        "effective_to": effective_to,
        "item_price_count": count,
        "status": "PENDING",
        "activated_at": None,
        "synced_scale_count": 0,
    })
    svc.recompute_store(store, store_id)
    return ok_object(store, views.price_file(row), 201)


def get_file(store, actor, view_args):
    row = svc.get_plain(store, "price_files", view_args["id"])
    return ok_object(store, views.price_file(row))


def list_files(store, actor, view_args):
    rows = svc.all_rows(store, "price_files")
    store_id = query("store_id")
    status = query("status")
    if store_id:
        rows = [r for r in rows if r["store_id"] == store_id]
    if status:
        rows = [r for r in rows if r["status"] == status]
    return envelope_array(store, rows, views.price_file)


def activate(store, actor, view_args):
    row = svc.get_plain(store, "price_files", view_args["id"])
    store_id = row["store_id"]
    svc.get_store(store, store_id)
    if row["status"] != "PENDING":
        fail("ERR_INVALID_STATE")

    incumbent = None
    for other in svc.all_rows(store, "price_files"):
        if other["id"] == row["id"] or other["store_id"] != store_id:
            continue
        if other["status"] != "ACTIVE":
            continue
        if not calc.price_files_overlap(row, other):
            continue
        re_price = (parse_dt(row["effective_from"]) > parse_dt(other["effective_from"])
                    and row["effective_to"] == other["effective_to"])
        if not re_price:
            fail("ERR_PRICE_FILE_OVERLAP")
        incumbent = other

    row["status"] = "ACTIVE"
    row["activated_at"] = store.now()
    svc.touch(store, row)

    if incumbent is not None:
        incumbent["status"] = "SUPERSEDED"
        svc.touch(store, incumbent)
        # Superseding voids the incumbent's ISSUED labels and forces remakes.
        svc.supersede_price_file_cascade(store, store_id, incumbent)

    svc.recompute_label_counts(store, row["id"])
    svc.recompute_store(store, store_id)
    return ok_object(store, views.price_file(row))


def retract(store, actor, view_args):
    row = svc.get_plain(store, "price_files", view_args["id"])
    store_id = row["store_id"]
    svc.get_store(store, store_id)
    if row["status"] != "ACTIVE":
        fail("ERR_INVALID_STATE")
    # Priority 27: a file with ISSUED labels cannot be withdrawn.
    if any(l["price_file_id"] == row["id"] and l["status"] == "ISSUED"
           for l in svc.all_rows(store, "labels")):
        fail("ERR_PRICE_FILE_IN_USE")
    # Priority 28: the associated promotion must first be CANCELLED.  A
    # promotion that has already settled is a closed week and does not block
    # the withdrawal; only a live or scheduled one does.
    for promo in svc.all_rows(store, "promotions"):
        if promo["status"] in ("CANCELLED", "SETTLED"):
            continue
        if promo["status"] == "DEGRADED":
            fail("ERR_PROMO_STATE_BLOCKS_FILE_WITHDRAWAL")
        if promo["status"] == "ACTIVE":
            fail("ERR_PROMO_STATE_BLOCKS_FILE_WITHDRAWAL")
        if promo["status"] == "SCHEDULED":
            now = parse_dt(store.now())
            if (parse_dt(promo["week_start_date"]) <= now
                    < parse_dt(promo["week_end_date"])):
                fail("ERR_PROMO_STATE_BLOCKS_FILE_WITHDRAWAL")
    row["status"] = "PENDING"
    svc.touch(store, row)
    svc.recompute_store(store, store_id)
    return ok_object(store, views.price_file(row))


def reactivate(store, actor, view_args):
    row = svc.get_plain(store, "price_files", view_args["id"])
    store_id = row["store_id"]
    svc.get_store(store, store_id)
    if row["status"] != "SUPERSEDED":
        fail("ERR_INVALID_STATE")
    now = parse_dt(store.now())
    # The currently ACTIVE file must be expired relative to the logical clock.
    current = calc.resolve_active_price_file(
        svc.all_rows(store, "price_files"), store_id, store.now())
    if current is not None:
        fail("ERR_INVALID_STATE")
    if not (parse_dt(row["effective_from"]) <= now < parse_dt(row["effective_to"])):
        fail("ERR_INVALID_STATE")
    # Through PENDING, then immediately ACTIVE via the ordinary edge. That edge
    # supersedes the incumbent exactly as a fresh activation would (PRD §3.6:
    # reactivation "is permitted only when the currently ACTIVE file is expired
    # relative to the logical clock and the returning file's effective interval
    # contains the clock" — the superseded incumbent is thereby retired).
    row["status"] = "PENDING"
    row["status"] = "ACTIVE"
    row["activated_at"] = store.now()
    svc.touch(store, row)

    for other in svc.all_rows(store, "price_files"):
        if other["id"] == row["id"] or other["store_id"] != store_id:
            continue
        if other["status"] != "ACTIVE":
            continue
        other["status"] = "SUPERSEDED"
        svc.touch(store, other)
        svc.supersede_price_file_cascade(store, store_id, other)

    svc.recompute_label_counts(store, row["id"])
    svc.recompute_store(store, store_id)
    return ok_object(store, views.price_file(row))


def active_file(store, actor, view_args):
    store_id = query("store_id")
    if store_id is None:
        invalid("store_id is required.")
    svc.get_store(store, store_id)
    row = calc.resolve_active_price_file(
        svc.all_rows(store, "price_files"), store_id, store.now())
    if row is None:
        fail("ERR_PRICE_FILE_STALE")
    return ok_object(store, views.price_file(row))


def create_label(store, actor, view_args):
    payload = body()
    store_id = as_string(req(payload, "store_id"), "store_id")
    svc.get_store(store, store_id)
    subject_type = req(payload, "subject_type")
    if subject_type not in SUBJECT_TYPES:
        invalid("subject_type must be one of %s." % ", ".join(SUBJECT_TYPES))
    subject_ref_id = as_string(req(payload, "subject_ref_id"), "subject_ref_id")
    net_weight = as_number(req(payload, "net_weight_lbs"), "net_weight_lbs")
    # Priority 36: the scale-lock bound.
    if net_weight <= 0 or net_weight > MAX_LABEL_WEIGHT_LBS:
        fail("ERR_LABEL_WEIGHT_EXCEEDED", )
    unit_price = as_int(req(payload, "unit_price_cents"), "unit_price_cents")
    if unit_price < 0:
        invalid("unit_price_cents must not be negative.")
    active = calc.resolve_active_price_file(
        svc.all_rows(store, "price_files"), store_id, store.now())
    if active is None:
        fail("ERR_PRICE_FILE_STALE")
    label = svc.synthesize_label(store, store_id, subject_type, subject_ref_id,
                                 net_weight, unit_price)
    svc.recompute_store(store, store_id)
    return ok_object(store, views.label(label), 201)


def get_label(store, actor, view_args):
    row = svc.get_plain(store, "labels", view_args["id"])
    return ok_object(store, views.label(row))


def list_labels(store, actor, view_args):
    rows = svc.all_rows(store, "labels")
    for name, key in (("store_id", "store_id"), ("sub_ticket_id", "sub_ticket_id"),
                      ("price_file_id", "price_file_id"),
                      ("subject_type", "subject_type"), ("status", "status")):
        value = query(name)
        if value:
            rows = [r for r in rows if r[key] == value]
    return envelope_array(store, rows, views.label)


def _instant(raw, field):
    try:
        return norm_dt(raw)
    except (TypeError, ValueError):
        invalid("%s must be an ISO 8601 instant." % field)