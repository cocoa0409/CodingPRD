"""Baseline periods and reduction targets."""
from flask import Blueprint

from db import base_row, db, sort_rows, touch
from errors import fail
from middleware import (ALL_READERS, CORPORATE_LEAD, SITE_MANAGER, authenticate,
                        require_site_scope)
from response import object_response, row_response
from routes.common import filtered, must_exist, respond_list
from services import derive
from services.calc import num
from validation import (bad, body_json, field_date, field_decimal, field_enum,
                       field_int, field_str, query_enum, query_str)

bp = Blueprint("baseline", __name__)

BASELINE_STATUSES = ("OPEN", "SUBMITTED", "CERTIFIED")
TARGET_STATUSES = ("PROPOSED", "ACTIVE", "ACHIEVED", "MISSED", "SUPERSEDED")
BASES = ("ABSOLUTE", "INTENSITY")
ATTAINMENT_STATES = ("BEHIND", "ACHIEVED_PENDING")


# ------------------------------------------------------- baseline periods
@bp.route("/baseline-periods", methods=["POST"])
def create_baseline():
    caller = authenticate((SITE_MANAGER,))
    body = body_json()
    site_id = field_str(body, "site_id")
    start_date = field_date(body, "start_date")
    end_date = field_date(body, "end_date")
    if end_date < start_date:
        bad("end_date may not be earlier than start_date.")
    must_exist(db.sites, site_id, "ERR_SITE_NOT_FOUND")
    require_site_scope(caller, site_id)
    for row in db.baselines.values():
        if row["site_id"] != site_id:
            continue
        if start_date <= row["end_date"] and row["start_date"] <= end_date:
            fail("ERR_BASELINE_WINDOW_OVERLAP",
                 "The window intersects an existing baseline period of this site.")
    period = base_row(
        site_id=site_id,
        start_date=start_date,
        end_date=end_date,
        status="OPEN",
        rejection_note=None,
        rejection_count=0,
        submitted_at=None,
        certified_at=None,
        baseline_entry_count=0,
        baseline_waste_grams=0,
        baseline_waste_kg=0.0,
        baseline_meals_served=0,
        baseline_intensity_kg_per_1k_meals=None,
        baseline_cost_cents=0,
    )
    db.baselines[period["id"]] = period
    return row_response(period, 201)


@bp.route("/baseline-periods/<period_id>/submit", methods=["POST"])
def submit_baseline(period_id):
    caller = authenticate((SITE_MANAGER,))
    body_json()
    period = must_exist(db.baselines, period_id, "ERR_BASELINE_NOT_FOUND")
    require_site_scope(caller, period["site_id"])
    if period["status"] != "OPEN":
        fail("ERR_INVALID_BASELINE_STATE", "Only an OPEN period may be submitted.")
    counted = derive.counted_entries_in_window(
        period["site_id"], period["start_date"], period["end_date"])
    if not counted:
        fail("ERR_BASELINE_NO_DATA", "The window holds no qualifying capture.")
    derive.freeze_baseline_metrics(period)
    period["status"] = "SUBMITTED"
    period["submitted_at"] = db.now_iso()
    touch(period)
    return row_response(period)


@bp.route("/baseline-periods/<period_id>/certify", methods=["POST"])
def certify_baseline(period_id):
    authenticate((CORPORATE_LEAD,))
    body_json()
    period = must_exist(db.baselines, period_id, "ERR_BASELINE_NOT_FOUND")
    if period["status"] != "SUBMITTED":
        fail("ERR_INVALID_BASELINE_STATE",
             "Only a SUBMITTED period may be certified.")
    if not period["baseline_meals_served"]:
        fail("ERR_BASELINE_NO_DATA",
             "A window with frozen meals of zero may not be certified.")
    period["status"] = "CERTIFIED"
    period["certified_at"] = db.now_iso()
    touch(period)
    return row_response(period)


@bp.route("/baseline-periods/<period_id>/reject", methods=["POST"])
def reject_baseline(period_id):
    authenticate((CORPORATE_LEAD,))
    body = body_json()
    rejection_note = field_str(body, "rejection_note")
    period = must_exist(db.baselines, period_id, "ERR_BASELINE_NOT_FOUND")
    if period["status"] != "SUBMITTED":
        fail("ERR_INVALID_BASELINE_STATE",
             "Only a SUBMITTED period may be rejected.")
    period["status"] = "OPEN"
    period["rejection_note"] = rejection_note
    period["rejection_count"] = period["rejection_count"] + 1
    derive.clear_baseline_metrics(period)
    touch(period)
    return row_response(period)


@bp.route("/baseline-periods/<period_id>", methods=["GET"])
def get_baseline(period_id):
    authenticate(ALL_READERS)
    return row_response(must_exist(db.baselines, period_id,
                                   "ERR_BASELINE_NOT_FOUND"))


@bp.route("/baseline-periods", methods=["GET"])
def list_baselines():
    authenticate(ALL_READERS)
    rows = filtered(list(db.baselines.values()),
                    site_id=query_str("site_id"),
                    status=query_enum("status", BASELINE_STATUSES))
    return respond_list(rows)


# ------------------------------------------------------- reduction targets
@bp.route("/reduction-targets", methods=["POST"])
def create_target():
    authenticate((CORPORATE_LEAD,))
    body = body_json()
    site_id = field_str(body, "site_id")
    baseline_period_id = field_str(body, "baseline_period_id")
    basis = field_enum(body, "basis", BASES)
    target_pct = field_decimal(body, "target_reduction_pct", exclusive_min=0,
                               maximum=100, scale=2)
    window_start = field_date(body, "window_start")
    window_end = field_date(body, "window_end")
    if window_end < window_start:
        bad("window_end may not be earlier than window_start.")
    expected_site_version = field_int(body, "expected_site_version")
    min_diversion = field_decimal(body, "min_diversion_rate_pct", required=False,
                                  minimum=0, maximum=100, scale=2,
                                  default=None)
    site = must_exist(db.sites, site_id, "ERR_SITE_NOT_FOUND")
    period = must_exist(db.baselines, baseline_period_id, "ERR_BASELINE_NOT_FOUND")
    if expected_site_version != site["version"]:
        fail("ERR_STALE_SITE_VERSION",
             "expected_site_version does not match the site's version.")
    if not window_start > period["end_date"]:
        fail("ERR_TARGET_WINDOW_BEFORE_BASELINE",
             "window_start must be strictly later than the baseline end_date.")

    superseded = [t for t in db.targets.values()
                  if t["site_id"] == site_id
                  and t["window_start"] == window_start
                  and t["window_end"] == window_end
                  and t["status"] in ("PROPOSED", "ACTIVE")]
    for row in sort_rows(superseded):
        row["status"] = "SUPERSEDED"
        row["resolved_at"] = db.now_iso()
        touch(row)

    target = base_row(
        site_id=site_id,
        baseline_period_id=baseline_period_id,
        basis=basis,
        target_reduction_pct=num(target_pct),
        min_diversion_rate_pct=(0.0 if min_diversion is None else num(min_diversion)),
        window_start=window_start,
        window_end=window_end,
        status="PROPOSED",
        performance_waste_grams=0,
        performance_meals_served=0,
        performance_intensity_kg_per_1k_meals=None,
        absolute_reduction_pct=None,
        intensity_reduction_pct=None,
        effective_reduction_pct=None,
        attainment_state="BEHIND",
        activated_at=None,
        resolved_at=None,
    )
    db.targets[target["id"]] = target
    return row_response(target, 201)


@bp.route("/reduction-targets/<target_id>/activate", methods=["POST"])
def activate_target(target_id):
    authenticate((CORPORATE_LEAD,))
    body_json()
    target = must_exist(db.targets, target_id, "ERR_TARGET_NOT_FOUND")
    if target["status"] != "PROPOSED":
        fail("ERR_INVALID_TARGET_STATE", "Only a PROPOSED target may be activated.")
    period = db.baselines.get(target["baseline_period_id"])
    if period is None or period["status"] != "CERTIFIED":
        fail("ERR_BASELINE_NOT_CERTIFIED",
             "The bound baseline period must be CERTIFIED.")
    target["status"] = "ACTIVE"
    target["activated_at"] = db.now_iso()
    derive.apply_attainment(target)
    touch(target)
    return row_response(target)


@bp.route("/reduction-targets/<target_id>/attainment", methods=["GET"])
def read_attainment(target_id):
    authenticate(ALL_READERS)
    target = must_exist(db.targets, target_id, "ERR_TARGET_NOT_FOUND")
    figures = derive.compute_attainment(target)
    data = {
        "target_id": target["id"],
        "basis": target["basis"],
        "baseline_waste_grams": figures["baseline_waste_grams"],
        "baseline_intensity_kg_per_1k_meals":
            figures["baseline_intensity_kg_per_1k_meals"],
        "performance_waste_grams": figures["performance_waste_grams"],
        "performance_meals_served": figures["performance_meals_served"],
        "performance_intensity_kg_per_1k_meals":
            figures["performance_intensity_kg_per_1k_meals"],
        "absolute_reduction_pct": figures["absolute_reduction_pct"],
        "intensity_reduction_pct": figures["intensity_reduction_pct"],
        "effective_reduction_pct": figures["effective_reduction_pct"],
        "target_reduction_pct": target["target_reduction_pct"],
        "min_diversion_rate_pct": target["min_diversion_rate_pct"],
        "site_diversion_rate_pct": figures["site_diversion_rate_pct"],
        "attainment_state": figures["attainment_state"],
    }
    return object_response(data)


@bp.route("/reduction-targets/<target_id>", methods=["GET"])
def get_target(target_id):
    authenticate(ALL_READERS)
    return row_response(must_exist(db.targets, target_id, "ERR_TARGET_NOT_FOUND"))


@bp.route("/reduction-targets", methods=["GET"])
def list_targets():
    authenticate(ALL_READERS)
    rows = filtered(list(db.targets.values()),
                    site_id=query_str("site_id"),
                    baseline_period_id=query_str("baseline_period_id"),
                    status=query_enum("status", TARGET_STATUSES),
                    basis=query_enum("basis", BASES),
                    attainment_state=query_enum("attainment_state",
                                                ATTAINMENT_STATES))
    return respond_list(rows)
