"""WasteRecord group: the mandated markdown-before-discard sequence (PRD 3.3)."""
from decimal import Decimal

from errors import fail, invalid
from http_support import (
    Endpoint, as_number, as_string, body, envelope_array, opt, query, req,
)
from response import ok_object
from util import parse_dt, rhu_int, to_dec
import calc
import services as svc
import views

READ_ROLES = ["PlatformAdmin", "DeliManager", "DeliClerk", "BakeryCoordinator",
              "ScaleOperator"]
CLERK_ROLES = ["DeliClerk", "DeliManager"]
MANAGER_ROLES = ["PlatformAdmin", "DeliManager"]

REASONS = ("HOLD_EXPIRED", "TEMPERATURE_BREACH", "ALLERGEN_CONTAMINATION",
           "QUALITY", "UNCLAIMED_PLATTER")


def register(app):
    Endpoint(app, "POST", "/deli/waste-records", CLERK_ROLES, create_record)
    Endpoint(app, "GET", "/deli/waste-records/<id>", READ_ROLES, get_record)
    Endpoint(app, "GET", "/deli/waste-records", READ_ROLES, list_records)
    Endpoint(app, "POST", "/deli/waste-records/<id>/mark-down", CLERK_ROLES,
             mark_down)
    Endpoint(app, "POST", "/deli/waste-records/<id>/discard", CLERK_ROLES, discard)
    Endpoint(app, "POST", "/deli/waste-records/<id>/verify", MANAGER_ROLES, verify)
    Endpoint(app, "POST", "/deli/waste-records/<id>/unverify", MANAGER_ROLES,
             unverify)
    Endpoint(app, "POST", "/deli/waste-records/<id>/void", MANAGER_ROLES, void)


def create_record(store, actor, view_args):
    payload = body()
    store_id = as_string(req(payload, "store_id"), "store_id")
    svc.get_store(store, store_id)
    batch_id = as_string(req(payload, "production_batch_id"), "production_batch_id")
    batch = svc.get_scoped(store, "batches", batch_id, store_id)
    markdown_by = as_string(req(payload, "markdown_by_associate_id"),
                            "markdown_by_associate_id")
    associate = svc.get_associate(store, markdown_by)
    if associate["store_id"] != store_id:
        fail("ERR_NOT_FOUND")
    reason = req(payload, "reason")
    if reason not in REASONS:
        invalid("reason must be one of %s." % ", ".join(REASONS))
    # Priority 29: a second concurrent record would fork the liability ledger.
    for other in svc.all_rows(store, "waste_records"):
        if other["production_batch_id"] == batch_id and other["status"] in ("DRAFT",
                                                                          "MARKED_DOWN"):
            fail("ERR_MARKDOWN_REQUIRED_BEFORE_DISCARD")
    row = svc.create(store, "waste_records", {
        "store_id": store_id,
        "production_batch_id": batch_id,
        "markdown_by_associate_id": markdown_by,
        "verifier_associate_id": None,
        "verified_by_certification_id": None,
        "discard_lbs": Decimal(0),
        "reason": reason,
        "markdown_sold_lbs": Decimal(0),
        "markdown_cents": 0,
        "markdown_recorded_at": None,
        "discarded_at": None,
        "discard_value_cents": 0,
        "handling_fee_cents": 0,
        "total_liability_cents": 0,
        "status": "DRAFT",
    })
    svc.recompute_store(store, store_id)
    return ok_object(store, views.waste(row), 201)


def get_record(store, actor, view_args):
    row = svc.get_plain(store, "waste_records", view_args["id"])
    return ok_object(store, views.waste(row))


def list_records(store, actor, view_args):
    rows = svc.all_rows(store, "waste_records")
    for name, key in (("store_id", "store_id"),
                      ("production_batch_id", "production_batch_id"),
                      ("verifier_associate_id", "verifier_associate_id"),
                      ("markdown_by_associate_id", "markdown_by_associate_id"),
                      ("status", "status"), ("reason", "reason")):
        value = query(name)
        if value:
            rows = [r for r in rows if r[key] == value]
    return envelope_array(store, rows, views.waste)


def mark_down(store, actor, view_args):
    payload = body()
    row = svc.get_plain(store, "waste_records", view_args["id"])
    store_id = row["store_id"]
    svc.get_store(store, store_id)
    svc.recompute_store(store, store_id)
    batch = svc.get_scoped(store, "batches", row["production_batch_id"], store_id)
    item = svc.get_item(store, batch["deli_item_id"])
    if row["status"] != "DRAFT":
        fail("ERR_INVALID_STATE")
    # The parent batch must already have been marked down.
    if batch["hold_status"] != "MARKED_DOWN":
        fail("ERR_MARKDOWN_REQUIRED_BEFORE_DISCARD")
    # Priority 30: the half-open markdown window decides legality.
    if not calc.markdown_window_open(batch, item, store.now()):
        fail("ERR_MARKDOWN_WINDOW_CLOSED")
    markdown_by = as_string(req(payload, "markdown_by_associate_id"),
                            "markdown_by_associate_id")
    associate = svc.get_associate(store, markdown_by)
    if associate["store_id"] != store_id:
        fail("ERR_NOT_FOUND")
    # Priority 31: the marker-down cannot be the producer.
    if markdown_by == batch["produced_by_associate_id"]:
        fail("ERR_SEGREGATION_OF_DUTIES")
    sold_lbs = as_number(req(payload, "markdown_sold_lbs"), "markdown_sold_lbs")
    if sold_lbs < 0:
        invalid("markdown_sold_lbs must not be negative.")

    row["markdown_by_associate_id"] = markdown_by
    row["markdown_sold_lbs"] = sold_lbs
    row["markdown_cents"] = rhu_int(sold_lbs * to_dec(item["retail_price_per_lb_cents"]))
    row["markdown_recorded_at"] = store.now()
    row["status"] = "MARKED_DOWN"
    svc.touch(store, row)
    _recompute_batch_markdown(store, batch, item)
    svc.recompute_store(store, store_id)
    return ok_object(store, views.waste(row))


def discard(store, actor, view_args):
    payload = body()
    row = svc.get_plain(store, "waste_records", view_args["id"])
    store_id = row["store_id"]
    svc.get_store(store, store_id)
    svc.recompute_store(store, store_id)
    batch = svc.get_scoped(store, "batches", row["production_batch_id"], store_id)
    item = svc.get_item(store, batch["deli_item_id"])
    if row["status"] not in ("DRAFT", "MARKED_DOWN"):
        fail("ERR_INVALID_STATE")

    if row["status"] == "DRAFT":
        # Direct discard is legal only when the markdown window is shut.
        if batch["hold_status"] != "HOLDING":
            fail("ERR_INVALID_STATE")
        # The discard is legal once the offer at markdown price has been made,
        # i.e. once the half-open markdown window has shut.
        state = calc.hold_window_state(batch, item, store.now())
        if item["markdown_window_minutes"] != 0 and state != "EXPIRED":
            fail("ERR_MARKDOWN_REQUIRED_BEFORE_DISCARD")
    else:
        if batch["hold_status"] not in ("HOLDING", "MARKED_DOWN"):
            fail("ERR_INVALID_STATE")

    discard_lbs = as_number(req(payload, "discard_lbs"), "discard_lbs")
    if discard_lbs <= 0:
        invalid("discard_lbs must be greater than zero.")

    row["discard_lbs"] = discard_lbs
    prior = _prior_liability(store, row)
    value_cents, fee_cents, total_cents = calc.waste_liability(row, item, prior)
    row["discard_value_cents"] = value_cents
    row["handling_fee_cents"] = fee_cents
    row["total_liability_cents"] = total_cents
    row["discarded_at"] = store.now()
    row["status"] = "DISCARDED"
    svc.touch(store, row)

    batch["hold_status"] = "DISCARDED"
    svc.touch(store, batch)
    svc.recompute_store(store, store_id)
    return ok_object(store, views.waste(row))


def verify(store, actor, view_args):
    payload = body()
    row = svc.get_plain(store, "waste_records", view_args["id"])
    store_id = row["store_id"]
    svc.get_store(store, store_id)
    svc.recompute_store(store, store_id)
    batch = svc.get_scoped(store, "batches", row["production_batch_id"], store_id)
    if row["status"] != "DISCARDED":
        fail("ERR_INVALID_STATE")

    verifier_id = as_string(req(payload, "verifier_associate_id"),
                            "verifier_associate_id")
    verifier = svc.get_associate(store, verifier_id)
    if verifier["store_id"] != store_id:
        fail("ERR_NOT_FOUND")
    cert_id = as_string(req(payload, "verified_by_certification_id"),
                        "verified_by_certification_id")
    cert = svc.get_plain(store, "certifications", cert_id)
    # Priority 11: the presented certification must be a live FOOD_HANDLING
    # credential belonging to the stated verifier.
    if cert["associate_id"] != verifier_id or cert["cert_type"] != "FOOD_HANDLING" \
            or not calc.cert_is_active(cert, store.now()):
        fail("ERR_ASSOCIATE_NOT_CERTIFIED")
    # Priority 31: three distinct people.
    if verifier_id == batch["produced_by_associate_id"]:
        fail("ERR_SEGREGATION_OF_DUTIES")
    if row["markdown_by_associate_id"] is not None \
            and verifier_id == row["markdown_by_associate_id"]:
        fail("ERR_SEGREGATION_OF_DUTIES")
    # Priority 38: OCC against the batch whose final cost this settles.
    svc.check_occ(store, batch, opt(payload, "expected_batch_version"),
                  "expected_batch_version")

    row["status"] = "VERIFIED"
    row["verifier_associate_id"] = verifier_id
    row["verified_by_certification_id"] = cert_id
    svc.touch(store, row)

    svc.recompute_batch_discard(store, batch)
    svc.settle_batch_costs(store, batch)
    svc.touch(store, batch)
    svc.recompute_store(store, store_id)
    return ok_object(store, views.waste(row))


def unverify(store, actor, view_args):
    payload = body()
    row = svc.get_plain(store, "waste_records", view_args["id"])
    store_id = row["store_id"]
    svc.get_store(store, store_id)
    svc.recompute_store(store, store_id)
    batch = svc.get_scoped(store, "batches", row["production_batch_id"], store_id)
    if row["status"] != "VERIFIED":
        fail("ERR_INVALID_STATE")
    req(payload, "reason")
    row["status"] = "DISCARDED"
    row["verifier_associate_id"] = None
    row["verified_by_certification_id"] = None
    svc.touch(store, row)
    svc.recompute_batch_discard(store, batch)
    svc.settle_batch_costs(store, batch)
    svc.touch(store, batch)
    svc.recompute_store(store, store_id)
    return ok_object(store, views.waste(row))


def void(store, actor, view_args):
    payload = body()
    row = svc.get_plain(store, "waste_records", view_args["id"])
    store_id = row["store_id"]
    svc.get_store(store, store_id)
    svc.recompute_store(store, store_id)
    req(payload, "reason")
    if row["status"] not in ("DRAFT", "MARKED_DOWN"):
        fail("ERR_INVALID_STATE")
    row["status"] = "VOIDED"
    svc.touch(store, row)
    svc.recompute_store(store, store_id)
    return ok_object(store, views.waste(row))


def _recompute_batch_markdown(store, batch, item):
    sold = Decimal(0)
    cents = 0
    for other in svc.all_rows(store, "waste_records"):
        if other["production_batch_id"] != batch["id"]:
            continue
        sold += to_dec(other["markdown_sold_lbs"])
        cents += other["markdown_cents"]
    batch["markdown_sold_lbs"] = sold
    batch["markdown_cents"] = cents
    svc.touch(store, batch)


def _prior_liability(store, row):
    """Sum over strictly-earlier non-platter rows in the same store."""
    cutoff = parse_dt(row["created_at"])
    total = 0
    for other in svc.all_rows(store, "waste_records"):
        if other["id"] == row["id"] or other["store_id"] != row["store_id"]:
            continue
        if other["reason"] == "UNCLAIMED_PLATTER":
            continue
        if other["status"] not in ("VERIFIED", "DISCARDED", "MARKED_DOWN"):
            continue
        if not (parse_dt(other["created_at"]) < cutoff):
            continue
        total += other["total_liability_cents"]
    return total