"""Transaction batch + correction endpoints."""
from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal

from flask import Blueprint, request

from db import DB, CLOCK
from errors import (
    not_found, invalid_input, invalid_state, duplicate_key, region_archived,
)
from middleware import require_roles
from response import success
from services.calculations import (
    parse_iso8601, compute_confidence, compute_reference_price,
    compute_tier_values, round_half_up_int, CONFIDENCE_GATE,
)
from services.entity import stamp_new, stamp_new_log, touch


bp = Blueprint("batches", __name__)


def _batch_view(b):
    return {
        "id": b["id"],
        "source_id": b["source_id"],
        "submission_ref": b["submission_ref"],
        "items": b["items"],
        "status": b["status"],
        "accepted_count": b["accepted_count"],
        "created_at": b["created_at"],
        "updated_at": b["updated_at"],
        "version": b["version"],
    }


def _correction_view(c):
    return {
        "id": c["id"],
        "created_at": c["created_at"],
        "batch_id": c["batch_id"],
        "corrected_price_cents": c["corrected_price_cents"],
        "delta_applied": c["delta_applied"],
    }


def _validate_batch_item(item):
    if not isinstance(item, dict):
        raise invalid_input("batch item must be object")
    cid = item.get("configuration_id")
    rid = item.get("region_id")
    price = item.get("sold_price_cents")
    sale_date = item.get("sale_date")
    mileage = item.get("mileage")
    if not isinstance(cid, str) or not cid:
        raise invalid_input("configuration_id required")
    if not isinstance(rid, str) or not rid:
        raise invalid_input("region_id required")
    if not isinstance(price, int) or isinstance(price, bool):
        raise invalid_input("sold_price_cents must be integer")
    if price < 100 or price > 100000000:
        raise invalid_input("sold_price_cents out of range [100, 100000000]")
    if not isinstance(sale_date, str) or not sale_date:
        raise invalid_input("sale_date required")
    try:
        parse_iso8601(sale_date)
    except Exception:
        raise invalid_input("sale_date must be ISO 8601")
    if not isinstance(mileage, int) or isinstance(mileage, bool) or mileage < 0:
        raise invalid_input("mileage must be a non-negative integer")


@bp.route("/batches", methods=["POST"])
def create_batch():
    require_roles("DataOps")
    body = request.get_json(silent=True) or {}
    source_id = body.get("source_id")
    submission_ref = body.get("submission_ref")
    items = body.get("items")

    # Priority 3: existence
    source = DB.sources.get(source_id) if isinstance(source_id, str) else None
    if source is None:
        raise not_found("source not found")

    # Priority 4: idempotent replay on submission_ref
    if isinstance(submission_ref, str) and submission_ref in DB._batch_submission_refs:
        existing = DB.batches[DB._batch_submission_refs[submission_ref]]
        if (existing["source_id"] == source_id
                and existing["items"] == items):
            return success(_batch_view(existing), 201)
        raise duplicate_key("submission_ref reused with different body")

    # Priority 5: source must not be SUSPENDED
    if source["status"] == "SUSPENDED":
        raise invalid_state("source is SUSPENDED")

    # Priority 13: region must be ACTIVE for every item region
    if isinstance(items, list):
        for item in items:
            if isinstance(item, dict):
                rid = item.get("region_id")
                region = DB.regions.get(rid) if isinstance(rid, str) else None
                if region is not None and region["status"] != "ACTIVE":
                    raise region_archived("region archived")

    # Priority 14: input shape
    if not isinstance(items, list) or not (1 <= len(items) <= 500):
        raise invalid_input("items must be a list of size 1..500")
    if not isinstance(submission_ref, str) or not submission_ref:
        raise invalid_input("submission_ref is required")
    for item in items:
        _validate_batch_item(item)
        # Existence of item FKs
        if DB.configurations.get(item["configuration_id"]) is None:
            raise not_found("configuration not found for batch item")
        if DB.regions.get(item["region_id"]) is None:
            raise not_found("region not found for batch item")

    b = stamp_new({
        "source_id": source_id,
        "submission_ref": submission_ref,
        "items": items,
        "status": "RECEIVED",
        "accepted_count": 0,
    })
    DB.batches[b["id"]] = b
    DB._batch_submission_refs[submission_ref] = b["id"]
    return success(_batch_view(b), 201)


@bp.route("/batches", methods=["GET"])
def list_batches():
    require_roles("DataOps", "ValuationAdmin")
    items = list(DB.batches.values())
    source_id = request.args.get("source_id")
    status_filter = request.args.get("status")
    if source_id:
        items = [b for b in items if b["source_id"] == source_id]
    if status_filter:
        items = [b for b in items if b["status"] == status_filter]
    try:
        limit = int(request.args.get("limit", "10"))
        offset = int(request.args.get("offset", "0"))
    except (TypeError, ValueError):
        raise invalid_input("limit/offset must be integers")
    if limit < 1 or limit > 100 or offset < 0:
        raise invalid_input("pagination out of range")
    items.sort(key=lambda b: b["created_at"])
    total = len(items)
    page = items[offset:offset + limit]
    return success([_batch_view(b) for b in page], 200,
                   response_type="array",
                   limit=limit, offset=offset, total_count=total,
                   has_more=(offset + limit) < total)


@bp.route("/batches/<batch_id>", methods=["GET"])
def get_batch(batch_id):
    require_roles("DataOps", "ValuationAdmin")
    b = DB.batches.get(batch_id)
    if b is None:
        raise not_found("batch not found")
    return success(_batch_view(b), 200)


def _recompute_series_for_items(items):
    """After acceptance/correction: recompute confidence for matching ACTIVE/DRAFT
    series; auto-suspend below 0.25, auto-reactivate at >= 0.25."""
    now = CLOCK.now()
    affected = set()
    for item in items:
        affected.add((item["configuration_id"], item["region_id"]))
    for series in DB.series.values():
        key = (series["configuration_id"], series["region_id"])
        if key not in affected:
            continue
        if series["status"] not in ("ACTIVE", "DRAFT", "SUSPENDED"):
            continue
        new_score = compute_confidence(series["configuration_id"],
                                       series["region_id"], now)
        series["confidence_score"] = new_score
        if series["status"] in ("ACTIVE", "DRAFT") and new_score < float(CONFIDENCE_GATE):
            if series["status"] == "ACTIVE":
                series["status"] = "SUSPENDED"
        elif series["status"] == "SUSPENDED" and new_score >= float(CONFIDENCE_GATE):
            series["status"] = "ACTIVE"
        touch(series)


@bp.route("/batches/<batch_id>/validate", methods=["POST"])
def validate_batch(batch_id):
    require_roles("DataOps")
    b = DB.batches.get(batch_id)
    if b is None:
        raise not_found("batch not found")
    if b["status"] != "RECEIVED":
        raise invalid_state("batch not in RECEIVED")
    b["status"] = "VALIDATED"
    touch(b)
    return success(_batch_view(b), 200)


@bp.route("/batches/<batch_id>/accept", methods=["POST"])
def accept_batch(batch_id):
    require_roles("DataOps")
    b = DB.batches.get(batch_id)
    if b is None:
        raise not_found("batch not found")
    if b["status"] != "VALIDATED":
        raise invalid_state("batch not in VALIDATED")
    b["status"] = "ACCEPTED"
    b["accepted_count"] = len(b["items"])
    touch(b)
    source = DB.sources.get(b["source_id"])
    if source is not None:
        source["consecutive_rejections"] = 0
        touch(source)
    _recompute_series_for_items(b["items"])
    return success(_batch_view(b), 200)


@bp.route("/batches/<batch_id>/reject", methods=["POST"])
def reject_batch(batch_id):
    require_roles("DataOps")
    b = DB.batches.get(batch_id)
    if b is None:
        raise not_found("batch not found")
    if b["status"] != "RECEIVED":
        raise invalid_state("batch not in RECEIVED")
    b["status"] = "REJECTED"
    touch(b)
    source = DB.sources.get(b["source_id"])
    if source is not None:
        source["consecutive_rejections"] = source.get("consecutive_rejections", 0) + 1
        if source["consecutive_rejections"] >= 5 and source["status"] in ("PROBATION", "ACTIVE"):
            source["status"] = "SUSPENDED"
        touch(source)
    return success(_batch_view(b), 200)


@bp.route("/batches/<batch_id>/corrections", methods=["GET"])
def list_batch_corrections(batch_id):
    require_roles("DataOps", "ValuationAdmin")
    b = DB.batches.get(batch_id)
    if b is None:
        raise not_found("batch not found")
    items = [c for c in DB.corrections.values() if c["batch_id"] == batch_id]
    try:
        limit = int(request.args.get("limit", "10"))
        offset = int(request.args.get("offset", "0"))
    except (TypeError, ValueError):
        raise invalid_input("limit/offset must be integers")
    if limit < 1 or limit > 100 or offset < 0:
        raise invalid_input("pagination out of range")
    items.sort(key=lambda c: c["created_at"])
    total = len(items)
    page = items[offset:offset + limit]
    return success([_correction_view(c) for c in page], 200,
                   response_type="array",
                   limit=limit, offset=offset, total_count=total,
                   has_more=(offset + limit) < total)


@bp.route("/corrections", methods=["POST"])
def create_correction():
    require_roles("DataOps")
    body = request.get_json(silent=True) or {}
    batch_id = body.get("batch_id")
    corrected_price = body.get("corrected_price_cents")

    batch = DB.batches.get(batch_id) if isinstance(batch_id, str) else None
    if batch is None:
        raise not_found("batch not found")

    if batch["status"] != "ACCEPTED":
        raise invalid_state("batch must be ACCEPTED")

    if not isinstance(corrected_price, int) or isinstance(corrected_price, bool):
        raise invalid_input("corrected_price_cents must be integer")
    if corrected_price < 100 or corrected_price > 100000000:
        raise invalid_input("corrected_price_cents out of range")

    # Apply the correction to the batch's items in place
    for item in batch["items"]:
        item["sold_price_cents"] = corrected_price

    # Recompute latest PUBLISHED edition for each affected series
    affected_pairs = {(item["configuration_id"], item["region_id"])
                      for item in batch["items"]}
    now = CLOCK.now()
    for series in DB.series.values():
        key = (series["configuration_id"], series["region_id"])
        if key not in affected_pairs:
            continue
        # Latest PUBLISHED edition of this series (by effective_at, then created_at)
        published = [e for e in DB.editions.values()
                     if e["series_id"] == series["id"] and e["status"] == "PUBLISHED"]
        if not published:
            continue
        published.sort(key=lambda e: (e["effective_at_dt"], e["created_at"]))
        latest = published[-1]
        new_ref = compute_reference_price(series["configuration_id"],
                                          series["region_id"],
                                          latest["effective_at_dt"], now)
        if new_ref is not None:
            latest["reference_price_cents"] = new_ref
            ti, pp, rt = compute_tier_values(new_ref)
            latest["trade_in_cents"] = ti
            latest["private_party_cents"] = pp
            latest["retail_cents"] = rt
            touch(latest)

    # Recompute confidence for affected series (ACTIVE/DRAFT/SUSPENDED)
    _recompute_series_for_items(batch["items"])

    c = stamp_new_log({
        "batch_id": batch_id,
        "corrected_price_cents": corrected_price,
        "delta_applied": True,
    })
    DB.corrections[c["id"]] = c
    return success(_correction_view(c), 201)
