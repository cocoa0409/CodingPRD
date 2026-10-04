"""Batch lot endpoints (PRD 3.4, 3.5): create/list/get/advance/review/disposition."""
from flask import Blueprint

import calc_quality
import clock
import envelope
import serialize
import store
from auth import require_auth
from constants import BATCH_ADVANCE_TARGETS, DISPOSITION_DECISIONS, MIN_REMAINING_SHELF_LIFE_HOURS
from errors import err
from validate import action_value, body, must_get, paginate, req_enum, req_str

bp = Blueprint("batches", __name__)


def _campaign_of(batch):
    return store.get("campaigns", batch["campaign_id"])


def _complete_parent_campaign(batch):
    campaign = _campaign_of(batch)
    if campaign["status"] == "PRODUCTION_IN_PROGRESS":
        campaign["status"] = "COMPLETED"  # automatic system transition (PRD 3.4)
        store.touch(campaign)


@bp.route("/campaigns/<cid>/batches", methods=["POST"])
def create_batch(cid):
    user = require_auth(("ManufacturingOperator",))
    campaign = must_get("campaign", cid)
    d = body()
    lot_number = req_str(d, "lot_number")
    if campaign["status"] != "PRODUCTION_IN_PROGRESS":
        err("ERR_INVALID_CAMPAIGN_STATE", "Batch creation requires PRODUCTION_IN_PROGRESS")
    if any(b["campaign_id"] == cid for b in store.all_recs("batches")):
        err("ERR_BATCH_ALREADY_EXISTS", "The campaign already has a batch lot")
    train = store.get("trains", campaign["train_id"])
    prov = calc_quality.provisional_yield(train["capacity_liters"])
    rec = store.create_rec("batches", {
        "campaign_id": campaign["id"],
        "lot_number": lot_number,
        "product_id": campaign["product_id"],  # denormalized copy, frozen here
        "process_status": "UPSTREAM",
        "quality_status": "IN_TESTING",
        "quality_hold_return_status": None,
        "manufactured_by_user_id": user,
        "quantity_units": prov,
        "provisional_yield_units": prov,
        "final_yield_units": None,
        "process_completed_at": None,
        "expiry_utc": None,
    })
    return envelope.ok(serialize.batch(rec), 201)


@bp.route("/campaigns/<cid>/batches", methods=["GET"])
def list_batches(cid):
    require_auth(("Any",))
    must_get("campaign", cid)
    recs = [b for b in store.all_recs("batches") if b["campaign_id"] == cid]
    page, total, limit, offset = paginate(recs)
    return envelope.ok_list([serialize.batch(b) for b in page], total, limit, offset)


@bp.route("/batches/<bid>", methods=["GET"])
def get_batch(bid):
    require_auth(("Any",))
    return envelope.ok(serialize.batch(must_get("batch", bid)), 200)


def _tests_of(batch_id, phase=None):
    return [t for t in store.all_recs("tests")
            if t["batch_lot_id"] == batch_id and (phase is None or t["phase"] == phase)]


def _to_downstream(rec):
    if rec["process_status"] != "UPSTREAM":
        err("ERR_INVALID_BATCH_STATE", "DOWNSTREAM requires process_status UPSTREAM")
    up = _tests_of(rec["id"], "UPSTREAM")
    if not any(t["status"] == "VERIFIED" for t in up) \
            or any(t["status"] not in ("VERIFIED", "INVALIDATED") for t in up):
        err("ERR_UNRESOLVED_TESTS", "Upstream evidence incomplete")
    rec["process_status"] = "DOWNSTREAM"


def _to_process_complete(rec):
    if rec["process_status"] != "DOWNSTREAM":
        err("ERR_INVALID_BATCH_STATE", "PROCESS_COMPLETE requires process_status DOWNSTREAM")
    down = _tests_of(rec["id"], "DOWNSTREAM")
    all_t = _tests_of(rec["id"])
    if not any(t["status"] == "VERIFIED" for t in down) \
            or any(t["status"] not in ("VERIFIED", "INVALIDATED") for t in all_t):
        err("ERR_UNRESOLVED_TESTS", "Batch evidence incomplete")
    final = calc_quality.final_yield(rec)
    rec["final_yield_units"] = final
    rec["quantity_units"] = final
    rec["process_status"] = "PROCESS_COMPLETE"
    rec["process_completed_at"] = clock.now()
    product = store.get("products", rec["product_id"])
    rec["expiry_utc"] = clock.add_hours(rec["process_completed_at"], product["shelf_life_hours"])
    rec["quality_status"] = "READY_FOR_REVIEW"
    _complete_parent_campaign(rec)


def _to_terminated(rec):
    if rec["process_status"] not in ("UPSTREAM", "DOWNSTREAM"):
        err("ERR_INVALID_BATCH_STATE", "TERMINATED requires UPSTREAM or DOWNSTREAM")
    rec["process_status"] = "TERMINATED"
    rec["quality_status"] = "REJECTED"
    _complete_parent_campaign(rec)


@bp.route("/batches/<bid>/advance", methods=["POST"])
def advance_batch(bid):
    require_auth(("ManufacturingOperator",))
    rec = must_get("batch", bid)
    d = body()
    target = action_value(d, "to_status", BATCH_ADVANCE_TARGETS)
    if target == "DOWNSTREAM":
        _to_downstream(rec)
    elif target == "PROCESS_COMPLETE":
        _to_process_complete(rec)
    else:
        _to_terminated(rec)
    store.touch(rec)
    return envelope.ok(serialize.batch(rec), 200)


@bp.route("/batches/<bid>/submit-for-review", methods=["POST"])
def submit_for_review(bid):
    require_auth(("QualityAssuranceReviewer",))
    rec = must_get("batch", bid)
    if rec["quality_status"] != "READY_FOR_REVIEW":
        err("ERR_INVALID_BATCH_STATE", "submit-for-review requires READY_FOR_REVIEW")
    rec["quality_status"] = "PENDING_DISPOSITION"
    store.touch(rec)
    return envelope.ok(serialize.batch(rec), 200)


def _segregation_check(rec, user):
    if user == rec["manufactured_by_user_id"]:
        err("ERR_SEGREGATION_OF_DUTIES", "Disposition user manufactured this batch")
    verifiers = {t["verified_by_user_id"] for t in _tests_of(rec["id"])
                 if t["status"] == "VERIFIED"}
    if user in verifiers:
        err("ERR_SEGREGATION_OF_DUTIES", "Disposition user verified a test on this batch")


def _release_gates(rec):
    campaign = _campaign_of(rec)
    if campaign["demand_type"] != "COMMERCIAL":
        return  # CLINICAL batches skip posture, shelf-life and comparability gates
    train = store.get("trains", campaign["train_id"])
    site = store.get("sites", train["site_id"])
    if site["release_posture"] == "FROZEN":
        err("ERR_SITE_RELEASE_FROZEN", "Site release_posture is FROZEN")
    remaining = clock.hours_between(clock.now(), rec["expiry_utc"])
    if remaining < MIN_REMAINING_SHELF_LIFE_HOURS:
        err("ERR_INSUFFICIENT_REMAINING_SHELF_LIFE", "Fewer than 720 hours remain")
    studies = [s for s in store.all_recs("studies") if s["product_id"] == rec["product_id"]]
    if studies:
        latest = max(studies, key=lambda s: (s["created_at"], s["_seq"]))
        if latest["status"] != "FILED":
            err("ERR_COMPARABILITY_NOT_ESTABLISHED",
                "The product's most recent ComparabilityStudy is not FILED")


@bp.route("/batches/<bid>/disposition", methods=["POST"])
def disposition(bid):
    user = require_auth(("QualityAssuranceReviewer",))
    rec = must_get("batch", bid)
    d = body()
    decision = req_enum(d, "decision", DISPOSITION_DECISIONS)
    req_str(d, "rationale")
    if rec["quality_status"] != "PENDING_DISPOSITION":
        err("ERR_INVALID_BATCH_STATE", "disposition requires PENDING_DISPOSITION")
    _segregation_check(rec, user)  # first business rule for both decisions
    if decision == "RELEASED":
        _release_gates(rec)
        rec["quality_status"] = "RELEASED"
    else:
        rec["quality_status"] = "REJECTED"
        for s in store.all_recs("shipments"):
            if s["batch_lot_id"] == rec["id"] and s["status"] == "PLANNED":
                s["status"] = "CANCELLED"  # cold-storage occupancy released
                store.touch(s)
    store.touch(rec)
    return envelope.ok(serialize.batch(rec), 200)
