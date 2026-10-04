"""ProductionBatch group (PRD 3.1).

The start path carries the densest validation ordering in the API; the checks
below are written in the exact sequence the PRD's ordered list prescribes.
"""
from decimal import Decimal

from errors import fail, invalid
from http_support import (
    Endpoint, as_bool, as_number, as_string, body, envelope_array, opt, query,
    req,
)
from response import ok_object
from util import dt_add_minutes, parse_dt, to_dec
import calc
import services as svc
import views

READ_ROLES = ["PlatformAdmin", "DeliManager", "DeliClerk", "BakeryCoordinator",
              "ScaleOperator"]
CLERK_ROLES = ["DeliClerk", "DeliManager"]


def register(app):
    Endpoint(app, "POST", "/deli/production-batches", CLERK_ROLES, create_batch)
    Endpoint(app, "GET", "/deli/production-batches/<id>", READ_ROLES, get_batch)
    Endpoint(app, "GET", "/deli/production-batches", READ_ROLES, list_batches)
    Endpoint(app, "POST", "/deli/production-batches/<id>/start", CLERK_ROLES, start)
    Endpoint(app, "POST", "/deli/production-batches/<id>/complete", CLERK_ROLES,
             complete)
    Endpoint(app, "POST", "/deli/production-batches/<id>/rework", CLERK_ROLES,
             rework)
    Endpoint(app, "POST", "/deli/production-batches/<id>/mark-down", CLERK_ROLES,
             mark_down)


def create_batch(store, actor, view_args):
    payload = body()
    store_id = as_string(req(payload, "store_id"), "store_id")
    store_row = svc.get_store(store, store_id)
    svc.recompute_store(store, store_id)
    item_id = as_string(req(payload, "deli_item_id"), "deli_item_id")
    item = svc.get_item(store, item_id)

    # Priority 6: pickup-window lockout.
    if svc.pickup_window_lockout(store, store_id):
        fail("ERR_HACCP_WINDOW_FREEZE")
    # Priority 7: HACCP hold flag.
    if store_row["haccp_safety_flag"]:
        fail("ERR_HACCP_HOLD")
    # Priority 8: HALT posture.
    if store_row["posture"] == "HALT":
        fail("ERR_POSTURE_HALT")
    # Priority 9: unverified waste backlog.
    if store_row["pending_waste_verification_count"] >= 3:
        fail("ERR_UNVERIFIED_WASTE_BACKLOG")
    # Priority 10: RESTRICTED blocks batch creation only.
    if store_row["posture"] == "RESTRICTED":
        fail("ERR_POSTURE_RESTRICTED")

    batch_code = as_string(req(payload, "batch_code"), "batch_code")
    if any(b["store_id"] == store_id and b["batch_code"] == batch_code
           for b in store.batches.values()):
        invalid("batch_code must be unique within the store.")
    planned_lbs = as_number(req(payload, "planned_lbs"), "planned_lbs")
    if planned_lbs <= 0:
        invalid("planned_lbs must be greater than 0.")
    # ERR_BATCH_WINDOW_INVALID: the hold window must be well formed.
    if item["case_life_minutes"] <= item["markdown_window_minutes"]:
        fail("ERR_BATCH_WINDOW_INVALID", )

    producer_id = as_string(req(payload, "produced_by_associate_id"),
                            "produced_by_associate_id")
    producer = svc.get_associate(store, producer_id)
    if producer["store_id"] != store_id:
        fail("ERR_NOT_FOUND")

    slicer_id = opt(payload, "slicer_id")
    if slicer_id is not None:
        svc.get_scoped(store, "slicers", slicer_id, store_id)

    rework_of = opt(payload, "rework_of_batch_id")
    if rework_of is not None:
        svc.get_scoped(store, "batches", rework_of, store_id)

    row = svc.create(store, "batches", {
        "store_id": store_id,
        "deli_item_id": item_id,
        "slicer_id": slicer_id,
        "produced_by_associate_id": producer_id,
        "rework_of_batch_id": rework_of,
        "batch_code": batch_code,
        "planned_lbs": planned_lbs,
        "produced_lbs": Decimal(0),
        "produced_at": None,
        "hold_expires_at": None,
        "production_status": "PLANNED",
        "hold_status": "HOLDING",
        "markdown_sold_lbs": Decimal(0),
        "markdown_cents": 0,
        "discard_lbs": Decimal(0),
        "temperature_breach": as_bool(opt(payload, "temperature_breach", default=False),
                                      "temperature_breach"),
        "case_yield_cost_provisional_cents": 0,
        "case_yield_cost_final_cents": 0,
        "_verified_waste": [],
    })
    svc.recompute_store(store, store_id)
    return ok_object(store, views.batch(row), 201)


def get_batch(store, actor, view_args):
    row = svc.get_plain(store, "batches", view_args["id"])
    return ok_object(store, views.batch(row))


def list_batches(store, actor, view_args):
    rows = svc.all_rows(store, "batches")
    for name, key in (("store_id", "store_id"), ("deli_item_id", "deli_item_id"),
                      ("production_status", "production_status"),
                      ("hold_status", "hold_status"),
                      ("rework_of_batch_id", "rework_of_batch_id"),
                      ("slicer_id", "slicer_id"),
                      ("produced_by_associate_id", "produced_by_associate_id")):
        value = query(name)
        if value:
            rows = [r for r in rows if r[key] == value]
    return envelope_array(store, rows, views.batch)


def start(store, actor, view_args):
    payload = body()
    row = svc.get_plain(store, "batches", view_args["id"])
    store_id = row["store_id"]
    store_row = svc.get_store(store, store_id)
    svc.recompute_store(store, store_id)
    item = svc.get_item(store, row["deli_item_id"])

    # Priority 5: required state.
    if row["production_status"] != "PLANNED":
        fail("ERR_INVALID_STATE")

    # Priority 38 -- but the store posture gate is part of the transition
    # preconditions themselves (PRD 2.11), so RESTRICTED/HALT report first.
    if store_row["posture"] in ("RESTRICTED", "HALT"):
        fail("ERR_POSTURE_RESTRICTED")

    # Ordering note: the OCC gate is the transition's own precondition and must
    # be evaluated before the resource-level checks it accompanies.
    svc.check_occ(store, store_row, opt(payload, "expected_store_version"),
                  "expected_store_version")

    # Priority 6: pickup-window lockout.
    if svc.pickup_window_lockout(store, store_id):
        fail("ERR_HACCP_WINDOW_FREEZE")
    if store_row["haccp_safety_flag"]:
        fail("ERR_HACCP_HOLD")
    # Priority 9: the backlog fires above the safety-screened slicer checks.
    if store_row["pending_waste_verification_count"] >= 3:
        fail("ERR_UNVERIFIED_WASTE_BACKLOG")

    # Priority 15: slicer-required items must name a slicer.
    slicer = None
    if item["slicer_required"] and row["slicer_id"] is None:
        fail("ERR_SLICER_REQUIRED", )
    if row["slicer_id"] is not None:
        slicer = svc.get_scoped(store, "slicers", row["slicer_id"], store_id)

    # Priority 11: operator certification.
    if item["slicer_required"]:
        if not svc.holds_cert(store, row["produced_by_associate_id"],
                              "SLICER_OPERATION"):
            fail("ERR_ASSOCIATE_NOT_CERTIFIED")

    if slicer is not None:
        prev_item = store.items.get(slicer["last_sliced_deli_item_id"]) \
            if slicer["last_sliced_deli_item_id"] else None
        # Priority 12: allergen changeover. The slicer must not introduce any
        # allergen absent from the item's own declared set; the residue is
        # cleared by an ALLERGEN_CHANGEOVER cycle, not by completion.
        if prev_item is not None:
            introduced = set(prev_item["allergen_flags"]) - set(item["allergen_flags"])
            if introduced:
                fail("ERR_ALLERGEN_CHANGEOVER_REQUIRED")

        # Priority 13: the slicer must be free across [clock, clock + case life).
        window_end = dt_add_minutes(store.now(), item["case_life_minutes"])
        if _slicer_committed(store, slicer, store.now(), window_end):
            fail("ERR_SLICER_WINDOW_CONFLICT")

        # Priority 14: sanitation state.
        if slicer["sanitation_status"] == "SANITIZING":
            fail("ERR_SLICER_NOT_SANITIZED")
        if slicer["sanitation_status"] == "NEEDS_SANITATION":
            if not calc.sanitation_cycle_due(slicer, "ROUTINE") \
                    and not calc.sanitation_cycle_due(slicer, "TIMED"):
                fail("ERR_SLICER_NOT_SANITIZED")

    row["production_status"] = "IN_PRODUCTION"
    svc.touch(store, row)
    if slicer is not None:
        slicer["sanitation_status"] = "IN_USE"
        slicer["assigned_deli_item_id"] = row["deli_item_id"]
        svc.touch(store, slicer)
    svc.recompute_store(store, store_id)
    svc.bump_store(store, store_id)
    return ok_object(store, views.batch(row))


def _slicer_committed(store, slicer, start_iso, end_iso):
    """Half-open commitment test across sanitation cycles and in-flight batches."""
    start = parse_dt(start_iso)
    end = parse_dt(end_iso)
    for cycle in svc.all_rows(store, "sanitation_cycles"):
        if cycle["slicer_id"] != slicer["id"]:
            continue
        if cycle["status"] == "ABORTED":
            continue
        cycle_start = parse_dt(cycle["started_at"])
        cycle_end = parse_dt(dt_add_minutes(cycle["started_at"], cycle["cycle_minutes"]))
        if cycle["status"] == "OPEN":
            if cycle_start < end and start < cycle_end:
                return True
        elif cycle["status"] == "COMPLETE":
            if cycle_start < end and start < cycle_end:
                return True
    for batch in svc.all_rows(store, "batches"):
        if batch["slicer_id"] != slicer["id"] or batch["id"] == "":
            continue
        if batch["production_status"] != "IN_PRODUCTION":
            continue
        item = store.items.get(batch["deli_item_id"])
        if item is None:
            continue
        item_start = parse_dt(batch["updated_at"])
        item_end = parse_dt(dt_add_minutes(batch["updated_at"], item["case_life_minutes"]))
        if item_start < end and start < item_end:
            return True
    return False


def complete(store, actor, view_args):
    payload = body()
    row = svc.get_plain(store, "batches", view_args["id"])
    store_id = row["store_id"]
    store_row = svc.get_store(store, store_id)
    svc.recompute_store(store, store_id)
    item = svc.get_item(store, row["deli_item_id"])

    if row["production_status"] != "IN_PRODUCTION":
        fail("ERR_INVALID_STATE")
    # Priority 6: pickup-window lockout covers batch completion too.
    if svc.pickup_window_lockout(store, store_id):
        fail("ERR_HACCP_WINDOW_FREEZE")
    if store_row["haccp_safety_flag"]:
        fail("ERR_HACCP_HOLD")

    produced_lbs = as_number(req(payload, "produced_lbs"), "produced_lbs")
    if produced_lbs <= 0:
        invalid("produced_lbs must be greater than zero.")

    previous_sliced = None
    slicer = store.slicers.get(row["slicer_id"]) if row["slicer_id"] else None
    if slicer is not None and slicer["last_sliced_deli_item_id"]:
        previous_sliced = store.items.get(slicer["last_sliced_deli_item_id"])

    row["produced_lbs"] = produced_lbs
    row["production_status"] = "ON_LINE"
    row["produced_at"] = store.now()
    row["hold_expires_at"] = dt_add_minutes(store.now(), item["case_life_minutes"])
    svc.touch(store, row)

    # The cost variants are recomputed against the counters as they stand at
    # completion, before the slicer's cut counter advances for this batch.
    svc.settle_batch_costs(store, row, seal_provisional=True)
    svc.touch(store, row)

    if slicer is not None:
        slicer["sanitation_status"] = "NEEDS_SANITATION"
        slicer["cuts_since_sanitation"] = (
            slicer["cuts_since_sanitation"] + calc.cuts_for_weight(produced_lbs))
        slicer["assigned_deli_item_id"] = None
        slicer["last_sliced_deli_item_id"] = row["deli_item_id"]
        svc.touch(store, slicer)

    svc.recompute_store(store, store_id)
    svc.bump_store(store, store_id)

    # Allergen changeover cascade: a diverging sliced set makes queued tickets
    # in that allergen set un-buildable.
    if previous_sliced is not None and slicer is not None:
        if frozenset(previous_sliced["allergen_flags"]) != frozenset(item["allergen_flags"]):
            queued = [t for t in svc.all_rows(store, "sub_tickets")
                      if t["store_id"] == store_id]
            svc.allergen_changeover_cascade(store, store_id, item, queued)
    return ok_object(store, views.batch(row))


def rework(store, actor, view_args):
    payload = body()
    old = svc.get_plain(store, "batches", view_args["id"])
    store_id = old["store_id"]
    svc.get_store(store, store_id)
    if old["hold_status"] != "DISCARDED":
        fail("ERR_INVALID_STATE")
    item = svc.get_item(store, old["deli_item_id"])

    planned_lbs = as_number(req(payload, "planned_lbs"), "planned_lbs")
    if planned_lbs <= 0:
        invalid("planned_lbs must be greater than 0.")
    producer_id = as_string(req(payload, "produced_by_associate_id"),
                            "produced_by_associate_id")
    producer = svc.get_associate(store, producer_id)
    if producer["store_id"] != store_id:
        fail("ERR_NOT_FOUND")
    slicer_id = opt(payload, "slicer_id")
    if slicer_id is not None:
        svc.get_scoped(store, "slicers", slicer_id, store_id)
    batch_code = as_string(req(payload, "batch_code"), "batch_code")
    if any(b["store_id"] == store_id and b["batch_code"] == batch_code
           for b in store.batches.values()):
        invalid("batch_code must be unique within the store.")
    if item["case_life_minutes"] <= item["markdown_window_minutes"]:
        fail("ERR_BATCH_WINDOW_INVALID", )

    row = svc.create(store, "batches", {
        "store_id": store_id,
        "deli_item_id": old["deli_item_id"],
        "slicer_id": slicer_id,
        "produced_by_associate_id": producer_id,
        "rework_of_batch_id": old["id"],
        "batch_code": batch_code,
        "planned_lbs": planned_lbs,
        "produced_lbs": Decimal(0),
        "produced_at": None,
        "hold_expires_at": None,
        "production_status": "PLANNED",
        "hold_status": "HOLDING",
        "markdown_sold_lbs": Decimal(0),
        "markdown_cents": 0,
        "discard_lbs": Decimal(0),
        "temperature_breach": False,
        "case_yield_cost_provisional_cents": 0,
        "case_yield_cost_final_cents": 0,
        "_verified_waste": [],
    })
    svc.recompute_store(store, store_id)
    return ok_object(store, views.batch(row), 201)


def mark_down(store, actor, view_args):
    payload = body()
    row = svc.get_plain(store, "batches", view_args["id"])
    store_id = row["store_id"]
    svc.get_store(store, store_id)
    svc.recompute_store(store, store_id)
    item = svc.get_item(store, row["deli_item_id"])

    if row["production_status"] != "ON_LINE":
        fail("ERR_INVALID_STATE")
    # Priority 29: a second concurrent waste record would fork the ledger.
    for waste in svc.all_rows(store, "waste_records"):
        if waste["production_batch_id"] == row["id"] and waste["status"] in ("DRAFT",
                                                                            "MARKED_DOWN"):
            fail("ERR_WASTE_SEQUENCE_VIOLATION")
    # Priority 30: half-open markdown window.
    if not calc.markdown_window_open(row, item, store.now()):
        fail("ERR_MARKDOWN_WINDOW_CLOSED")

    recorded_by = opt(payload, "recorded_by_associate_id")
    if recorded_by is not None:
        if recorded_by == row["produced_by_associate_id"]:
            fail("ERR_SEGREGATION_OF_DUTIES")

    row["hold_status"] = "MARKED_DOWN"
    svc.touch(store, row)
    waste = svc.create(store, "waste_records", {
        "store_id": store_id,
        "production_batch_id": row["id"],
        "markdown_by_associate_id": recorded_by,
        "verifier_associate_id": None,
        "verified_by_certification_id": None,
        "discard_lbs": Decimal(0),
        "reason": "HOLD_EXPIRED",
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
    return ok_object(store, views.batch(row))