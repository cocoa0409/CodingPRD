"""Metric snapshots and health evaluations (PRD 3.3, 3.4)."""

from datetime import timedelta

from flask import Blueprint, request

import clock
import constants as C
import db
import guards
import middleware as mw
import response
import serializers as ser
import validators as v
from errors import ApiError
from services import calc, notify, posture

bp = Blueprint("metrics", __name__)


def _filter(rows, field):
    if field not in request.args:
        return rows
    wanted = request.args.get(field)
    return [r for r in rows if r.get(field) == wanted]


def _snapshot_sort_key(row):
    return (-row["window_end"].timestamp(), row["created_at"], row["_seq"])


@bp.post("/metric-snapshots")
@mw.require(C.ROLE_OFFICER)
def file_snapshot():
    data = v.body()
    seller_id = v.req_str(data, "seller_id", 1, None)
    window_start = v.req_datetime(data, "window_start")
    window_end = v.req_datetime(data, "window_end")
    if window_end <= window_start:
        v.bad("'window_end' must be strictly later than 'window_start'.")
    counters = {}
    for field in ("order_volume", "delivered_or_refunded_volume", "defect_claims_pending",
                  "defect_claims_substantiated", "late_shipments",
                  "pre_fulfillment_cancellations", "shipments_total",
                  "shipments_with_valid_tracking"):
        counters[field] = v.req_int(data, field, minimum=0)
    if counters["shipments_with_valid_tracking"] > counters["shipments_total"]:
        v.bad("'shipments_with_valid_tracking' may not exceed 'shipments_total'.")
    source = v.opt_enum(data, "source", C.SNAPSHOT_SOURCES, default="PLATFORM_PIPELINE")

    seller = guards.seller(seller_id)
    guards.ensure_not_banned(seller)

    for existing in db.snapshots_of(seller["id"]):
        if existing["source"] != source:
            continue
        # Half-open intervals: touching endpoints do not overlap.
        if window_start < existing["window_end"] and existing["window_start"] < window_end:
            raise ApiError("ERR_SNAPSHOT_WINDOW_OVERLAP")

    row = db.new_row(
        "snapshot",
        versioned=False,
        seller_id=seller["id"],
        window_start=window_start,
        window_end=window_end,
        source=source,
        **counters
    )
    db.METRIC_SNAPSHOTS[row["id"]] = row

    latest = sorted(db.snapshots_of(seller["id"]), key=_snapshot_sort_key)
    db.set_field(seller, "open_defect_claim_units",
                 latest[0]["defect_claims_pending"] if latest else 0)
    db.mark_dirty(seller)
    return response.one(row, ser.snapshot, 201)


@bp.post("/sellers/<seller_id>/health-evaluations")
@mw.require(C.ROLE_INVESTIGATOR, C.ROLE_OFFICER)
def file_evaluation(seller_id):
    seller = guards.seller(seller_id)
    guards.ensure_not_banned(seller)

    now = clock.now()
    horizon = now - timedelta(days=C.EVAL_LOOKBACK_DAYS)
    candidates = [
        s for s in db.snapshots_of(seller["id"])
        if s["window_end"] <= now and s["window_end"] > horizon
    ]
    candidates.sort(key=_snapshot_sort_key)
    input_set = candidates[:C.EVAL_MAX_SNAPSHOTS]
    if not input_set:
        raise ApiError("ERR_NO_SNAPSHOTS_IN_WINDOW")

    computed = calc.evaluate(input_set)
    evaluation = db.new_row(
        "evaluation",
        versioned=False,
        seller_id=seller["id"],
        auto_violation_id=None,
        evaluated_at=now,
        **computed
    )
    db.HEALTH_EVALUATIONS[evaluation["id"]] = evaluation

    db.set_field(seller, "health_score", computed["health_score"])
    db.set_field(seller, "metric_tier", computed["metric_tier"])
    db.mark_dirty(seller)

    if computed["metric_tier"] == "BREACHING":
        pool = [
            r for r in db.sorted_rows(db.POLICY_RULES)
            if r["category"] == "SHIPPING_PERFORMANCE" and r["removal_scope"] == "ACCOUNT"
        ]
        pool.sort(key=lambda r: (-r["base_severity_weight"], r["created_at"], r["_seq"]))
        if pool:
            rule = pool[0]
            violation = db.new_row(
                "violation",
                seller_id=seller["id"],
                policy_rule_id=rule["id"],
                listing_id=None,
                reporter_type="PLATFORM_AUTOMATION",
                evidence_reference="HEALTH-EVAL-" + evaluation["id"],
                state="UNDER_INVESTIGATION",
                auto_generated=True,
                detected_at=now,
                adjudicated_at=None,
                decision_note=None,
            )
            db.VIOLATIONS[violation["id"]] = violation
            evaluation["auto_violation_id"] = violation["id"]
            posture.recompute(seller)
            notify.emit(seller["id"], "HEALTH_BREACH", "HEALTH_EVALUATION",
                        evaluation["id"])

    return response.one(evaluation, ser.evaluation, 201)


@bp.get("/health-evaluations")
@mw.require(C.ROLE_INVESTIGATOR, C.ROLE_REVIEWER, C.ROLE_OFFICER)
def list_evaluations():
    limit, offset = v.pagination()
    rows = db.sorted_rows(db.HEALTH_EVALUATIONS)
    rows = _filter(rows, "seller_id")
    rows = _filter(rows, "auto_violation_id")
    rows = _filter(rows, "metric_tier")
    page, total = response.paginate(rows, limit, offset)
    return response.many(page, ser.evaluation, limit, offset, total)


@bp.get("/health-evaluations/<evaluation_id>")
@mw.require(C.ROLE_INVESTIGATOR, C.ROLE_REVIEWER, C.ROLE_OFFICER)
def read_evaluation(evaluation_id):
    row = guards.evaluation(evaluation_id)
    return response.one(row, ser.evaluation, 200)
