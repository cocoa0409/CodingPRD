"""Policy series + benefit schedule endpoints."""
from flask import Blueprint, request

import db
import errors as E
from middleware import require_role
from response import success_object
from serializers import benefit_schedule, policy as policy_ser, policy_series
from util import get_body, get_or_404, list_response, parse_iso

bp = Blueprint("policy_series", __name__)

SERIES = db.STORES["policy_series"]
SCHEDULES = db.STORES["benefit_schedules"]


# ---------------- PolicySeries ----------------

@bp.route("/policy-series", methods=["POST"])
def create_series(role, user_id):
    require_role(role, {"CarrierAdmin"})
    body = get_body(["series_code", "product_line"])
    if body["product_line"] not in ("ACCIDENT", "HOSPITAL", "CRITICAL_ILLNESS"):
        raise E.err(E.ERR_INVALID_REQUEST, "product_line must be ACCIDENT | HOSPITAL | CRITICAL_ILLNESS")
    for s in SERIES.values():
        if s["series_code"] == body["series_code"]:
            raise E.err(E.ERR_INVALID_REQUEST, "series_code must be unique")
    rec = db.stamp_created({
        "series_code": body["series_code"],
        "product_line": body["product_line"],
        "status": "DRAFT",
        "current_schedule_id": None,
    })
    SERIES[rec["id"]] = rec
    return success_object(policy_series(rec), status=201)


@bp.route("/policy-series/<rid>", methods=["GET"])
def get_series(role, user_id, rid):
    require_role(role, {"CarrierAdmin", "BenefitCounselor", "ClaimsAdjuster"})
    rec = get_or_404(SERIES, rid)
    return success_object(policy_series(rec))


@bp.route("/policy-series/<rid>/benefit-schedules", methods=["GET"])
def list_schedules(role, user_id, rid):
    require_role(role, {"CarrierAdmin", "BenefitCounselor", "ClaimsAdjuster"})
    get_or_404(SERIES, rid)
    filters = {
        "policy_series_id": rid,
        "status": request.args.get("status"),
    }
    return list_response(SCHEDULES, filters, benefit_schedule)


@bp.route("/policy-series/<rid>/activate", methods=["POST"])
def activate_series(role, user_id, rid):
    require_role(role, {"CarrierAdmin"})
    rec = get_or_404(SERIES, rid)
    if rec["status"] != "DRAFT":
        raise E.err(E.ERR_INVALID_STATE, f"Cannot activate from {rec['status']}")
    has_published = any(
        s["policy_series_id"] == rec["id"] and s["status"] == "PUBLISHED"
        for s in SCHEDULES.values()
    )
    if not has_published:
        raise E.err(E.ERR_SERIES_WITHOUT_SCHEDULE, "Series has no PUBLISHED schedule")
    rec["status"] = "ACTIVE"
    db.touch(rec)
    return success_object(policy_series(rec))


@bp.route("/policy-series/<rid>/retire", methods=["POST"])
def retire_series(role, user_id, rid):
    require_role(role, {"CarrierAdmin"})
    rec = get_or_404(SERIES, rid)
    if rec["status"] != "ACTIVE":
        raise E.err(E.ERR_INVALID_STATE, f"Cannot retire from {rec['status']}")
    rec["status"] = "RETIRED"
    db.touch(rec)
    return success_object(policy_series(rec))


@bp.route("/policy-series/<rid>/policies", methods=["GET"])
def list_series_policies(role, user_id, rid):
    require_role(role, {"CarrierAdmin", "ClaimsAdjuster"})
    get_or_404(SERIES, rid)
    filters = {
        "policy_series_id": rid,
        "status": request.args.get("status"),
    }
    return list_response(db.STORES["policies"], filters, policy_ser)


# ---------------- BenefitSchedule ----------------

@bp.route("/benefit-schedules", methods=["POST"])
def create_schedule(role, user_id):
    require_role(role, {"CarrierAdmin"})
    body = get_body([
        "policy_series_id", "schedule_version", "effective_date", "benefit_items",
        "monthly_premium_cents", "wellness_benefit_cents", "wellness_waiting_months",
        "preexisting_exclusion_months",
    ])
    series = SERIES.get(body["policy_series_id"])
    if series is None:
        raise E.err(E.ERR_REFERENTIAL_INTEGRITY, "policy_series_id does not exist")
    sv = body["schedule_version"]
    if not isinstance(sv, int) or isinstance(sv, bool):
        raise E.err(E.ERR_INVALID_REQUEST, "schedule_version must be an integer")
    ed = parse_iso(body["effective_date"], "effective_date")
    items = body["benefit_items"]
    if not isinstance(items, list):
        raise E.err(E.ERR_INVALID_REQUEST, "benefit_items must be an array")
    # the event_code values must be unique within the array
    codes = [i.get("event_code") for i in items if isinstance(i, dict)]
    if len(set(codes)) != len(codes):
        raise E.err(E.ERR_INVALID_REQUEST, "event_code values must be unique within benefit_items")
    # monotonicity within the series: schedule_version strictly greater, effective_date strictly later
    for s in SCHEDULES.values():
        if s["policy_series_id"] != series["id"]:
            continue
        if sv <= s["schedule_version"]:
            raise E.err(E.ERR_SCHEDULE_VERSION_CONFLICT, "schedule_version not strictly increasing")
        if ed <= parse_iso(s["effective_date"]):
            raise E.err(E.ERR_SCHEDULE_VERSION_CONFLICT, "effective_date not strictly increasing")
    rec = db.stamp_created({
        "policy_series_id": series["id"],
        "schedule_version": sv,
        "effective_date": db.format_ts(ed),
        "benefit_items": items,
        "monthly_premium_cents": body["monthly_premium_cents"],
        "wellness_benefit_cents": body["wellness_benefit_cents"],
        "wellness_waiting_months": body["wellness_waiting_months"],
        "preexisting_exclusion_months": body["preexisting_exclusion_months"],
        "status": "DRAFT",
    })
    SCHEDULES[rec["id"]] = rec
    return success_object(benefit_schedule(rec), status=201)


@bp.route("/benefit-schedules/<rid>", methods=["GET"])
def get_schedule(role, user_id, rid):
    require_role(role, {"CarrierAdmin", "BenefitCounselor", "ClaimsAdjuster"})
    rec = get_or_404(SCHEDULES, rid)
    return success_object(benefit_schedule(rec))


@bp.route("/benefit-schedules/<rid>/publish", methods=["POST"])
def publish_schedule(role, user_id, rid):
    require_role(role, {"CarrierAdmin"})
    rec = get_or_404(SCHEDULES, rid)
    if rec["status"] != "DRAFT":
        raise E.err(E.ERR_INVALID_STATE, f"Cannot publish from {rec['status']}")
    series = SERIES[rec["policy_series_id"]]
    if series["status"] not in ("DRAFT", "ACTIVE"):
        raise E.err(E.ERR_SERIES_RETIRED, "Series is RETIRED")
    items = rec["benefit_items"]
    if not items:
        raise E.err(E.ERR_INVALID_REQUEST, "benefit_items must be non-empty")
    codes = [i.get("event_code") for i in items]
    if len(set(codes)) != len(codes):
        raise E.err(E.ERR_INVALID_REQUEST, "event_code values must be unique within benefit_items")
    for i in items:
        amt = i.get("benefit_amount_cents")
        if not isinstance(amt, int) or isinstance(amt, bool) or amt < 0:
            raise E.err(E.ERR_INVALID_REQUEST, "benefit_amount_cents must be >= 0")
    # OCC on series
    body = request.get_json(silent=True) or {}
    expected = body.get("expected_series_version")
    if expected is not None and expected != series["version"]:
        raise E.err(E.ERR_STALE_VERSION, "expected_series_version does not match")
    # supersede prior PUBLISHED schedules of this series
    for s in SCHEDULES.values():
        if s["policy_series_id"] == series["id"] and s["status"] == "PUBLISHED":
            s["status"] = "SUPERSEDED"
            db.touch(s)
    rec["status"] = "PUBLISHED"
    db.touch(rec)
    series["current_schedule_id"] = rec["id"]
    db.touch(series)
    return success_object(benefit_schedule(rec))
