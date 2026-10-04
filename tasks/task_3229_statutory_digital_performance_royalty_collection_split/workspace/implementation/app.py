"""Flask app: routing, validation order, and endpoint handlers."""

import os

from flask import Flask, request

from db import store
from errors import (
    ApiError,
    err_invalid_request,
    err_invalid_state,
    err_not_found,
    err_stale_version,
)
from helpers import (
    base_entity,
    day_floor,
    fmt_ts,
    logical_now,
    paginate,
    parse_dt,
    require_enum,
    require_int,
    require_number,
    require_str,
    serialize,
    sort_created,
    touch,
)
from middleware import check_segregation, get_context, require_roles
from response import err_response, ok_array, ok_object
import services as svc

app = Flask(__name__)

ALL_READ = ["Admin", "RoyaltyOps", "RoyaltyAuditor", "Licensee", "PayeeAdmin", "MatchingAgent"]

SERVICE_CATEGORIES = {
    "PREEXISTING_SUBSCRIPTION",
    "NONSUBSCRIPTION_AD_SUPPORTED",
    "BUSINESS_ESTABLISHMENT",
}


@app.errorhandler(ApiError)
def handle_api_error(e):
    return err_response(e.error_id, e.http_status, e.message)


@app.errorhandler(404)
def handle_404(e):
    return err_response("ERR_NOT_FOUND", 404, "Route not found")


@app.errorhandler(405)
def handle_405(e):
    return err_response("ERR_NOT_FOUND", 404, "Route not found")


@app.errorhandler(Exception)
def handle_generic(e):
    if isinstance(e, ApiError):
        return handle_api_error(e)
    return err_response("ERR_INVALID_REQUEST", 400, str(e))


def body():
    if not request.data:
        return {}
    try:
        parsed = request.get_json(force=True, silent=False)
    except Exception:
        raise err_invalid_request("Request body must be valid JSON")
    if parsed is None:
        return {}
    if not isinstance(parsed, dict):
        raise err_invalid_request("Request body must be a JSON object")
    return parsed


def get_or_404(collection, rid):
    ent = collection.get(rid)
    if ent is None:
        raise err_not_found(f"Resource {rid} does not exist")
    return ent


# ---------------------------------------------------------------------------
# Clock
# ---------------------------------------------------------------------------

@app.route("/_clock/set_current_utc", methods=["POST"])
def set_clock():
    require_roles(["Admin"])
    b = body()
    to = parse_dt(b.get("to_iso8601"), "to_iso8601")
    store.clock = to
    return ok_object({"current_utc": fmt_ts(store.clock)})


# ---------------------------------------------------------------------------
# Licensees
# ---------------------------------------------------------------------------

def licensee_out(l):
    return serialize(l)


@app.route("/licensees", methods=["POST"])
def create_licensee():
    require_roles(["Admin"])
    b = body()
    legal_name = require_str(b, "legal_name")
    category = require_enum(b, "service_category", SERVICE_CATEGORIES)
    notice_date = parse_dt(b.get("notice_date"), "notice_date")
    l = base_entity()
    l.update({
        "legal_name": legal_name,
        "service_category": category,
        "license_status": "DRAFT",
        "notice_date": notice_date,
        "annual_minimum_fee_cents": 0,
        "suspended_reason": None,
    })
    store.licensees[l["id"]] = l
    return ok_object(licensee_out(l), 201)


@app.route("/licensees", methods=["GET"])
def list_licensees():
    require_roles(ALL_READ)
    items = list(store.licensees.values())
    st = request.args.get("license_status")
    if st is not None:
        items = [l for l in items if l["license_status"] == st]
    cat = request.args.get("service_category")
    if cat is not None:
        items = [l for l in items if l["service_category"] == cat]
    items = sort_created(items)
    page, limit, offset, total = paginate(items, request.args)
    return ok_array([licensee_out(l) for l in page], limit, offset, total)


@app.route("/licensees/<lid>", methods=["GET"])
def get_licensee(lid):
    require_roles(ALL_READ)
    l = get_or_404(store.licensees, lid)
    return ok_object(licensee_out(l))


@app.route("/licensees/<lid>/activate", methods=["POST"])
def activate_licensee(lid):
    require_roles(["Admin"])
    l = get_or_404(store.licensees, lid)
    if l["license_status"] != "DRAFT":
        raise err_invalid_state("Licensee is not DRAFT")
    l["license_status"] = "ACTIVE"
    touch(l)
    return ok_object(licensee_out(l))


@app.route("/licensees/<lid>/suspend", methods=["POST"])
def suspend_licensee(lid):
    require_roles(["Admin"])
    l = get_or_404(store.licensees, lid)
    b = body()
    reason = b.get("reason")
    if reason is not None and not isinstance(reason, str):
        raise err_invalid_request("reason must be a string")
    if l["license_status"] != "ACTIVE":
        raise err_invalid_state("Licensee is not ACTIVE")
    svc.suspend_licensee_cascade(l, reason)
    return ok_object(licensee_out(l))


@app.route("/licensees/<lid>/reinstate", methods=["POST"])
def reinstate_licensee(lid):
    require_roles(["Admin"])
    l = get_or_404(store.licensees, lid)
    if l["license_status"] != "SUSPENDED":
        raise err_invalid_state("Licensee is not SUSPENDED")
    l["license_status"] = "ACTIVE"
    l["suspended_reason"] = None
    touch(l)
    return ok_object(licensee_out(l))


@app.route("/licensees/<lid>/terminate", methods=["POST"])
def terminate_licensee(lid):
    require_roles(["Admin"])
    l = get_or_404(store.licensees, lid)
    if l["license_status"] == "TERMINATED":
        raise err_invalid_state("Licensee is already TERMINATED")
    blocked = False
    for rep in store.usage_reports.values():
        if rep["licensee_id"] != lid:
            continue
        if rep["report_status"] == "SUBMITTED":
            blocked = True
        for batch in store.distribution_batches.values():
            if batch["usage_report_id"] == rep["id"] and batch["batch_status"] == "PLANNED":
                blocked = True
    for audit in store.audit_cases.values():
        if audit["licensee_id"] == lid and audit["audit_status"] in ("OPENED", "FINDINGS_ISSUED"):
            blocked = True
    if blocked:
        raise ApiError("ERR_TERMINATION_BLOCKED", 409,
                       "In-flight reports, planned batches, or open audits block termination")
    l["license_status"] = "TERMINATED"
    touch(l)
    return ok_object(licensee_out(l))


@app.route("/licensees/<lid>/usage-reports", methods=["GET"])
def list_licensee_reports(lid):
    require_roles(["Admin", "RoyaltyOps", "RoyaltyAuditor", "Licensee"])
    get_or_404(store.licensees, lid)
    items = [r for r in store.usage_reports.values() if r["licensee_id"] == lid]
    st = request.args.get("report_status")
    if st is not None:
        items = [r for r in items if r["report_status"] == st]
    items = sort_created(items)
    page, limit, offset, total = paginate(items, request.args)
    return ok_array([report_out(r) for r in page], limit, offset, total)


@app.route("/licensees/<lid>/audit-cases", methods=["GET"])
def list_licensee_audits(lid):
    require_roles(["Admin", "RoyaltyOps", "RoyaltyAuditor"])
    get_or_404(store.licensees, lid)
    items = [a for a in store.audit_cases.values() if a["licensee_id"] == lid]
    st = request.args.get("audit_status")
    if st is not None:
        items = [a for a in items if a["audit_status"] == st]
    items = sort_created(items)
    page, limit, offset, total = paginate(items, request.args)
    return ok_array([audit_out(a) for a in page], limit, offset, total)


# ---------------------------------------------------------------------------
# Rate schedules
# ---------------------------------------------------------------------------

def schedule_out(s):
    return serialize(s)


@app.route("/rate-schedules", methods=["POST"])
def create_schedule():
    require_roles(["Admin"])
    b = body()
    proceeding_ref = require_str(b, "proceeding_ref")
    start = parse_dt(b.get("effective_start"), "effective_start")
    end = parse_dt(b.get("effective_end"), "effective_end")
    if not (end > start):
        raise err_invalid_request("effective_end must be > effective_start")
    rate = require_int(b, "rate_per_performance_microcents", min_val=0, exclusive_min=True)
    min_fee = require_int(b, "min_fee_cents", min_val=0, exclusive_min=True)
    category = require_enum(b, "category", SERVICE_CATEGORIES)
    if svc.schedule_overlap_exists(category, start, end):
        raise ApiError("ERR_RATE_SCHEDULE_OVERLAP", 409,
                       "Schedule window overlaps another DRAFT/EFFECTIVE schedule of the same category")
    s = base_entity()
    s.update({
        "proceeding_ref": proceeding_ref,
        "effective_start": start,
        "effective_end": end,
        "rate_per_performance_microcents": rate,
        "min_fee_cents": min_fee,
        "category": category,
        "schedule_status": "DRAFT",
    })
    store.rate_schedules[s["id"]] = s
    return ok_object(schedule_out(s), 201)


@app.route("/rate-schedules", methods=["GET"])
def list_schedules():
    require_roles(["Admin", "RoyaltyOps", "StatutoryBoard"])
    items = list(store.rate_schedules.values())
    cat = request.args.get("category")
    if cat is not None:
        items = [s for s in items if s["category"] == cat]
    st = request.args.get("schedule_status")
    if st is not None:
        items = [s for s in items if s["schedule_status"] == st]
    items = sort_created(items)
    page, limit, offset, total = paginate(items, request.args)
    return ok_array([schedule_out(s) for s in page], limit, offset, total)


@app.route("/rate-schedules/<sid>", methods=["GET"])
def get_schedule(sid):
    require_roles(["Admin", "RoyaltyOps", "StatutoryBoard"])
    s = get_or_404(store.rate_schedules, sid)
    return ok_object(schedule_out(s))


@app.route("/rate-schedules/<sid>/activate", methods=["POST"])
def activate_schedule(sid):
    require_roles(["Admin"])
    s = get_or_404(store.rate_schedules, sid)
    if s["schedule_status"] != "DRAFT":
        raise err_invalid_state("Schedule is not DRAFT")
    if svc.schedule_overlap_exists(s["category"], s["effective_start"], s["effective_end"],
                                   exclude_id=sid):
        raise ApiError("ERR_RATE_SCHEDULE_OVERLAP", 409,
                       "Schedule window overlaps another DRAFT/EFFECTIVE schedule of the same category")
    svc.supersede_prior_effective(s)
    s["schedule_status"] = "EFFECTIVE"
    touch(s)
    return ok_object(schedule_out(s))


# ---------------------------------------------------------------------------
# Rate proceedings
# ---------------------------------------------------------------------------

def proceeding_out(p):
    return serialize(p)


@app.route("/rate-proceedings", methods=["POST"])
def create_proceeding():
    require_roles(["StatutoryBoard"])
    b = body()
    docket_no = require_str(b, "docket_no")
    p = base_entity()
    p.update({
        "docket_no": docket_no,
        "proceeding_status": "OPEN",
        "decided_schedule_id": None,
    })
    store.rate_proceedings[p["id"]] = p
    return ok_object(proceeding_out(p), 201)


@app.route("/rate-proceedings", methods=["GET"])
def list_proceedings():
    require_roles(["Admin", "RoyaltyOps", "StatutoryBoard"])
    items = list(store.rate_proceedings.values())
    st = request.args.get("proceeding_status")
    if st is not None:
        items = [p for p in items if p["proceeding_status"] == st]
    ds = request.args.get("decided_schedule_id")
    if ds is not None:
        items = [p for p in items if p["decided_schedule_id"] == ds]
    items = sort_created(items)
    page, limit, offset, total = paginate(items, request.args)
    return ok_array([proceeding_out(p) for p in page], limit, offset, total)


@app.route("/rate-proceedings/<pid>", methods=["GET"])
def get_proceeding(pid):
    require_roles(["Admin", "RoyaltyOps", "StatutoryBoard"])
    p = get_or_404(store.rate_proceedings, pid)
    return ok_object(proceeding_out(p))


@app.route("/rate-proceedings/<pid>/decide", methods=["POST"])
def decide_proceeding(pid):
    require_roles(["StatutoryBoard"])
    p = get_or_404(store.rate_proceedings, pid)
    b = body()
    new_schedule_id = b.get("new_schedule_id")
    if not isinstance(new_schedule_id, str) or not new_schedule_id:
        raise err_invalid_request("new_schedule_id is required")
    sched = store.rate_schedules.get(new_schedule_id)
    if sched is None:
        raise err_not_found("new_schedule_id does not reference an existing schedule")
    if p["proceeding_status"] != "OPEN" or sched["schedule_status"] != "DRAFT":
        raise ApiError("ERR_RATE_PROCEEDING_INVALID", 409,
                       "decide requires OPEN proceeding and DRAFT schedule")
    p["proceeding_status"] = "DECIDED"
    p["decided_schedule_id"] = new_schedule_id
    touch(p)
    return ok_object(proceeding_out(p))


@app.route("/rate-proceedings/<pid>/publish", methods=["POST"])
def publish_proceeding(pid):
    require_roles(["StatutoryBoard"])
    p = get_or_404(store.rate_proceedings, pid)
    if p["proceeding_status"] != "DECIDED":
        raise ApiError("ERR_RATE_PROCEEDING_INVALID", 409, "publish requires DECIDED proceeding")
    sched = store.rate_schedules.get(p["decided_schedule_id"])
    if sched is None or sched["schedule_status"] != "DRAFT":
        raise ApiError("ERR_RATE_PROCEEDING_INVALID", 409, "decided schedule is not DRAFT")
    svc.supersede_prior_effective(sched)
    sched["schedule_status"] = "EFFECTIVE"
    touch(sched)
    p["proceeding_status"] = "PUBLISHED"
    touch(p)
    return ok_object(proceeding_out(p))


@app.route("/rate-proceedings/<pid>/close", methods=["POST"])
def close_proceeding(pid):
    require_roles(["StatutoryBoard"])
    p = get_or_404(store.rate_proceedings, pid)
    if p["proceeding_status"] != "PUBLISHED":
        raise ApiError("ERR_RATE_PROCEEDING_INVALID", 409, "close requires PUBLISHED proceeding")
    p["proceeding_status"] = "CLOSED"
    touch(p)
    return ok_object(proceeding_out(p))


# ---------------------------------------------------------------------------
# Usage reports
# ---------------------------------------------------------------------------

def report_out(r):
    out = serialize(r)
    out.pop("_snapshot_schedule_id", None)
    out.pop("_snapshot_rate_microcents", None)
    out.pop("_snapshot_min_fee_cents", None)
    return out


@app.route("/usage-reports", methods=["POST"])
def create_report():
    require_roles(["Licensee"])
    b = body()
    licensee_id = b.get("licensee_id")
    if not isinstance(licensee_id, str) or not licensee_id:
        raise err_invalid_request("licensee_id is required")
    licensee = store.licensees.get(licensee_id)
    if licensee is None:
        raise err_not_found("licensee_id does not reference an existing licensee")
    start = parse_dt(b.get("period_start"), "period_start")
    end = parse_dt(b.get("period_end"), "period_end")
    if not (end >= start):
        raise err_invalid_request("period_end must be >= period_start")
    if svc.report_overlap_exists(licensee_id, start, end):
        raise ApiError("ERR_USAGE_REPORT_OVERLAP", 409,
                       "Report window overlaps another non-terminal report of the same licensee")
    if licensee["license_status"] != "ACTIVE":
        raise ApiError("ERR_LICENSEE_NOT_ACTIVE", 409, "Licensee is not ACTIVE")
    r = base_entity()
    r.update({
        "licensee_id": licensee_id,
        "period_start": start,
        "period_end": end,
        "report_status": "DRAFT",
        "total_performances": 0,
        "matched_performances": 0,
        "unmatched_performances": 0,
        "_snapshot_schedule_id": None,
        "_snapshot_rate_microcents": None,
        "_snapshot_min_fee_cents": None,
    })
    store.usage_reports[r["id"]] = r
    return ok_object(report_out(r), 201)


@app.route("/usage-reports", methods=["GET"])
def list_reports():
    require_roles(["Admin", "RoyaltyOps", "RoyaltyAuditor", "Licensee"])
    items = list(store.usage_reports.values())
    lid = request.args.get("licensee_id")
    if lid is not None:
        items = [r for r in items if r["licensee_id"] == lid]
    st = request.args.get("report_status")
    if st is not None:
        items = [r for r in items if r["report_status"] == st]
    items = sort_created(items)
    page, limit, offset, total = paginate(items, request.args)
    return ok_array([report_out(r) for r in page], limit, offset, total)


@app.route("/usage-reports/<rid>", methods=["GET"])
def get_report(rid):
    require_roles(["Admin", "RoyaltyOps", "RoyaltyAuditor", "Licensee"])
    r = get_or_404(store.usage_reports, rid)
    return ok_object(report_out(r))


def _submit_prechecks(r):
    lines = [pl for pl in store.play_lines.values() if pl["usage_report_id"] == r["id"]]
    if not lines:
        raise ApiError("ERR_REPORT_NO_PLAY_LINES", 409,
                       "Submission requires at least one play line")
    licensee = store.licensees.get(r["licensee_id"])
    if licensee is None or licensee["license_status"] != "ACTIVE":
        raise ApiError("ERR_LICENSEE_NOT_ACTIVE", 409, "Licensee is not ACTIVE")
    if svc.report_overlap_exists(r["licensee_id"], r["period_start"], r["period_end"],
                                 exclude_id=r["id"]):
        raise ApiError("ERR_USAGE_REPORT_OVERLAP", 409,
                       "Report window overlaps another non-terminal report of the same licensee")
    if svc.resolve_effective_schedule(licensee["service_category"], r["period_start"]) is None:
        raise ApiError("ERR_NO_EFFECTIVE_RATE_SCHEDULE", 409,
                       "No EFFECTIVE schedule covers the report's period_start")
    return licensee


@app.route("/usage-reports/<rid>/submit", methods=["POST"])
def submit_report(rid):
    require_roles(["Licensee"])
    r = get_or_404(store.usage_reports, rid)
    if r["report_status"] not in ("DRAFT", "AMENDED"):
        raise err_invalid_state("Report is not DRAFT or AMENDED")
    licensee = _submit_prechecks(r)
    svc.snapshot_rate(r, licensee)
    r["report_status"] = "SUBMITTED"
    touch(r)
    return ok_object(report_out(r))


@app.route("/usage-reports/<rid>/accept", methods=["POST"])
def accept_report(rid):
    require_roles(["RoyaltyOps"])
    r = get_or_404(store.usage_reports, rid)
    if r["report_status"] != "SUBMITTED":
        raise err_invalid_state("Report is not SUBMITTED")
    r["report_status"] = "ACCEPTED"
    touch(r)
    return ok_object(report_out(r))


@app.route("/usage-reports/<rid>/reject", methods=["POST"])
def reject_report(rid):
    require_roles(["RoyaltyOps"])
    r = get_or_404(store.usage_reports, rid)
    b = body()
    reason = b.get("reason")
    if reason is not None and not isinstance(reason, str):
        raise err_invalid_request("reason must be a string")
    if r["report_status"] != "SUBMITTED":
        raise err_invalid_state("Report is not SUBMITTED")
    r["report_status"] = "REJECTED"
    touch(r)
    return ok_object(report_out(r))


@app.route("/usage-reports/<rid>/amend", methods=["POST"])
def amend_report(rid):
    require_roles(["Licensee"])
    r = get_or_404(store.usage_reports, rid)
    if r["report_status"] == "REJECTED":
        r["report_status"] = "DRAFT"
        touch(r)
        return ok_object(report_out(r))
    if r["report_status"] != "ACCEPTED":
        raise err_invalid_state("Report is not REJECTED or ACCEPTED")
    # ACCEPTED -> AMENDED path
    for batch in store.distribution_batches.values():
        if batch["usage_report_id"] == rid and batch["batch_status"] == "EXECUTED":
            raise err_invalid_state("An EXECUTED batch exists for this report")
    r["report_status"] = "AMENDED"
    touch(r)
    # recompute liability if present
    liab = svc._liability_for_report(rid)
    if liab is not None and liab["liability_status"] not in ("SETTLED", "WRITTEN_OFF"):
        licensee = store.licensees.get(r["licensee_id"])
        old_due = liab["amount_due_cents"]
        result = svc.compute_liability(r, licensee, force_mode="YTD_MINIMUM_FEE")
        liab["gross_performance_royalty_cents"] = result["gross"]
        liab["minimum_fee_cents"] = result["minimum_fee"]
        liab["amount_due_cents"] = result["amount_due"]
        liab["admin_fee_cents"] = result["admin_fee"]
        liab["distributable_pool_cents"] = result["pool"]
        liab["_mode"] = result["mode"]
        touch(liab)
        # reconcile paid-to-date when the amount changed and liability already PAID
        if liab["amount_due_cents"] != old_due and liab["liability_status"] in ("PAID", "SETTLED"):
            diff = liab["amount_due_cents"] - old_due
            svc.add_min_fee_paid(r["licensee_id"], r["period_start"].year, diff)
    # cancel PLANNED batch
    for batch in store.distribution_batches.values():
        if batch["usage_report_id"] == rid and batch["batch_status"] == "PLANNED":
            batch["batch_status"] = "REVERSED"
            touch(batch)
    return ok_object(report_out(r))


# ---------------------------------------------------------------------------
# Play lines
# ---------------------------------------------------------------------------

def playline_out(p):
    return serialize(p)


@app.route("/usage-reports/<rid>/play-lines", methods=["GET"])
def list_report_play_lines(rid):
    require_roles(["Admin", "RoyaltyOps", "RoyaltyAuditor", "Licensee", "MatchingAgent"])
    get_or_404(store.usage_reports, rid)
    items = [p for p in store.play_lines.values() if p["usage_report_id"] == rid]
    st = request.args.get("identification_status")
    if st is not None:
        items = [p for p in items if p["identification_status"] == st]
    items = sort_created(items)
    page, limit, offset, total = paginate(items, request.args)
    return ok_array([playline_out(p) for p in page], limit, offset, total)


@app.route("/usage-reports/<rid>/play-lines", methods=["POST"])
def add_play_line(rid):
    require_roles(["Licensee"])
    r = get_or_404(store.usage_reports, rid)
    b = body()
    isrc = require_str(b, "isrc")
    track_title = require_str(b, "track_title")
    artist_name = require_str(b, "artist_name")
    perf = require_int(b, "performance_count", min_val=0, exclusive_min=True)
    if r["report_status"] not in ("DRAFT", "AMENDED"):
        raise ApiError("ERR_PLAY_LINE_IMMUTABLE", 409,
                       "Play lines may only be added while the report is DRAFT or AMENDED")
    p = base_entity()
    p.update({
        "usage_report_id": rid,
        "isrc": isrc,
        "track_title": track_title,
        "artist_name": artist_name,
        "performance_count": perf,
        "identification_status": "UNMATCHED",
        "matched_recording_id": None,
        "match_attempt_count": 0,
    })
    svc.identify_play_line(p)
    store.play_lines[p["id"]] = p
    svc.recompute_report_counters(r)
    touch(r)
    return ok_object(playline_out(p), 201)


@app.route("/play-lines/<pid>", methods=["GET"])
def get_play_line(pid):
    require_roles(["Admin", "RoyaltyOps", "RoyaltyAuditor", "Licensee", "MatchingAgent"])
    p = get_or_404(store.play_lines, pid)
    return ok_object(playline_out(p))


@app.route("/play-lines", methods=["GET"])
def list_play_lines():
    require_roles(["Admin", "RoyaltyOps", "RoyaltyAuditor", "MatchingAgent"])
    items = list(store.play_lines.values())
    mrid = request.args.get("matched_recording_id")
    if mrid is not None:
        items = [p for p in items if p["matched_recording_id"] == mrid]
    st = request.args.get("identification_status")
    if st is not None:
        items = [p for p in items if p["identification_status"] == st]
    items = sort_created(items)
    page, limit, offset, total = paginate(items, request.args)
    return ok_array([playline_out(p) for p in page], limit, offset, total)


@app.route("/play-lines/<pid>", methods=["DELETE"])
def delete_play_line(pid):
    require_roles(["Licensee"])
    p = get_or_404(store.play_lines, pid)
    r = store.usage_reports.get(p["usage_report_id"])
    if r is None:
        raise err_not_found("Containing report not found")
    if r["report_status"] not in ("DRAFT", "AMENDED"):
        raise ApiError("ERR_PLAY_LINE_IMMUTABLE", 409,
                       "Play lines may only be removed while the report is DRAFT or AMENDED")
    del store.play_lines[pid]
    svc.recompute_report_counters(r)
    touch(r)
    return "", 204


# ---------------------------------------------------------------------------
# Royalty liabilities
# ---------------------------------------------------------------------------

def liability_out(l):
    out = serialize(l)
    out.pop("_mode", None)
    out.pop("_rate_microcents", None)
    out.pop("_schedule_min_fee_cents", None)
    return out


@app.route("/usage-reports/<rid>/compute-liability", methods=["POST"])
def compute_liability(rid):
    require_roles(["RoyaltyOps"])
    r = get_or_404(store.usage_reports, rid)
    b = body()
    expected = b.get("expected_usage_report_version")
    if isinstance(expected, bool) or not isinstance(expected, int):
        raise err_invalid_request("expected_usage_report_version is required and must be an integer")
    if r["report_status"] not in ("ACCEPTED", "AMENDED"):
        raise err_invalid_state("Report is not ACCEPTED or AMENDED")
    if expected != r["version"]:
        raise err_stale_version("expected_usage_report_version does not match report version")
    if svc._liability_for_report(rid) is not None:
        raise ApiError("ERR_ALREADY_EXISTS", 409,
                       "A RoyaltyLiability already exists for this report")
    licensee = store.licensees.get(r["licensee_id"])
    result = svc.compute_liability(r, licensee)
    l = base_entity()
    l.update({
        "usage_report_id": rid,
        "period_start": r["period_start"],
        "gross_performance_royalty_cents": result["gross"],
        "minimum_fee_cents": result["minimum_fee"],
        "amount_due_cents": result["amount_due"],
        "liability_status": "COMPUTED",
        "admin_fee_cents": result["admin_fee"],
        "distributable_pool_cents": result["pool"],
        "_mode": result["mode"],
        "_rate_microcents": result["rate_microcents"],
        "_schedule_min_fee_cents": result["schedule_min_fee_cents"],
    })
    store.royalty_liabilities[l["id"]] = l
    # licensee's annual minimum fee sourced from effective schedule at run time
    sch = svc.resolve_effective_schedule(licensee["service_category"], r["period_start"])
    if sch is not None:
        licensee["annual_minimum_fee_cents"] = sch["min_fee_cents"]
        touch(licensee)
    touch(r)
    return ok_object(liability_out(l), 201)


@app.route("/usage-reports/<rid>/royalty-liability", methods=["GET"])
def get_report_liability(rid):
    require_roles(["Admin", "RoyaltyOps", "RoyaltyAuditor", "Licensee"])
    get_or_404(store.usage_reports, rid)
    items = [l for l in store.royalty_liabilities.values() if l["usage_report_id"] == rid]
    items = sort_created(items)
    page, limit, offset, total = paginate(items, request.args)
    return ok_array([liability_out(l) for l in page], limit, offset, total)


@app.route("/royalty-liabilities/<lid>", methods=["GET"])
def get_liability(lid):
    require_roles(["Admin", "RoyaltyOps", "RoyaltyAuditor", "Licensee"])
    l = get_or_404(store.royalty_liabilities, lid)
    return ok_object(liability_out(l))


@app.route("/royalty-liabilities/<lid>/bill", methods=["POST"])
def bill_liability(lid):
    require_roles(["RoyaltyOps"])
    l = get_or_404(store.royalty_liabilities, lid)
    if l["liability_status"] != "COMPUTED":
        raise err_invalid_state("Liability is not COMPUTED")
    l["liability_status"] = "BILLED"
    touch(l)
    return ok_object(liability_out(l))


@app.route("/royalty-liabilities/<lid>/record_payment", methods=["POST"])
def pay_liability(lid):
    require_roles(["RoyaltyOps"])
    l = get_or_404(store.royalty_liabilities, lid)
    if l["liability_status"] != "BILLED":
        raise err_invalid_state("Liability is not BILLED")
    l["liability_status"] = "PAID"
    touch(l)
    rep = store.usage_reports.get(l["usage_report_id"])
    if rep is not None:
        svc.add_min_fee_paid(rep["licensee_id"], rep["period_start"].year,
                             l["amount_due_cents"])
    return ok_object(liability_out(l))


@app.route("/royalty-liabilities/<lid>/write_off", methods=["POST"])
def writeoff_liability(lid):
    require_roles(["Admin"])
    l = get_or_404(store.royalty_liabilities, lid)
    b = body()
    reason = b.get("reason")
    if reason is not None and not isinstance(reason, str):
        raise err_invalid_request("reason must be a string")
    if l["liability_status"] != "BILLED":
        raise err_invalid_state("Liability is not BILLED")
    l["liability_status"] = "WRITTEN_OFF"
    touch(l)
    return ok_object(liability_out(l))


# ---------------------------------------------------------------------------
# Distribution batches & lines
# ---------------------------------------------------------------------------

def batch_out(b):
    return serialize(b)


def line_out(l):
    return serialize(l)


@app.route("/usage-reports/<rid>/distribution-batches", methods=["POST"])
def create_batch(rid):
    require_roles(["RoyaltyOps"])
    get_or_404(store.usage_reports, rid)
    b = body()
    scheduled_for = parse_dt(b.get("scheduled_for"), "scheduled_for")
    if svc._liability_for_report(rid) is None:
        raise ApiError("ERR_LIABILITY_NOT_COMPUTED", 409,
                       "Batch planning requires an existing liability for the report")
    for existing in store.distribution_batches.values():
        if existing["usage_report_id"] == rid and existing["batch_status"] != "REVERSED":
            raise ApiError("ERR_ALREADY_EXISTS", 409,
                           "A DistributionBatch already exists for this report")
    if not (scheduled_for > logical_now()):
        raise ApiError("ERR_SCHEDULED_TIME_NOT_FUTURE", 400,
                       "scheduled_for must be strictly after the current logical clock time")
    batch = base_entity()
    batch.update({
        "usage_report_id": rid,
        "batch_status": "PLANNED",
        "scheduled_for": scheduled_for,
        "executed_at": None,
    })
    store.distribution_batches[batch["id"]] = batch
    return ok_object(batch_out(batch), 201)


@app.route("/usage-reports/<rid>/distribution-batches", methods=["GET"])
def list_report_batches(rid):
    require_roles(["Admin", "RoyaltyOps", "RoyaltyAuditor"])
    get_or_404(store.usage_reports, rid)
    items = [b for b in store.distribution_batches.values() if b["usage_report_id"] == rid]
    st = request.args.get("batch_status")
    if st is not None:
        items = [b for b in items if b["batch_status"] == st]
    items = sort_created(items)
    page, limit, offset, total = paginate(items, request.args)
    return ok_array([batch_out(b) for b in page], limit, offset, total)


@app.route("/distribution-batches/<bid>", methods=["GET"])
def get_batch(bid):
    require_roles(["Admin", "RoyaltyOps", "RoyaltyAuditor"])
    b = get_or_404(store.distribution_batches, bid)
    return ok_object(batch_out(b))


@app.route("/distribution-batches/<bid>/execute", methods=["POST"])
def execute_batch(bid):
    require_roles(["RoyaltyOps"])
    batch = get_or_404(store.distribution_batches, bid)
    b = body()
    expected = b.get("expected_distribution_batch_version")
    if isinstance(expected, bool) or not isinstance(expected, int):
        raise err_invalid_request(
            "expected_distribution_batch_version is required and must be an integer")
    if batch["batch_status"] != "PLANNED":
        raise err_invalid_state("Batch is not PLANNED")
    if expected != batch["version"]:
        raise err_stale_version(
            "expected_distribution_batch_version does not match batch version")
    liab = svc._liability_for_report(batch["usage_report_id"])
    if liab is None or liab["liability_status"] != "PAID":
        raise ApiError("ERR_LIABILITY_NOT_PAID", 409,
                       "Batch execution requires liability in PAID status")
    if batch["scheduled_for"] > logical_now():
        raise ApiError("ERR_BATCH_NOT_DUE", 409,
                       "scheduled_for is still in the future relative to the logical clock")
    report = store.usage_reports[batch["usage_report_id"]]
    svc.execute_distribution(batch, report, liab)
    return ok_object(batch_out(batch))


@app.route("/distribution-batches/<bid>/cancel", methods=["POST"])
def cancel_batch(bid):
    require_roles(["RoyaltyOps"])
    batch = get_or_404(store.distribution_batches, bid)
    if batch["batch_status"] != "PLANNED":
        raise ApiError("ERR_BATCH_NOT_CANCELLABLE", 409,
                       "Only PLANNED batches may be cancelled")
    batch["batch_status"] = "REVERSED"
    touch(batch)
    return ok_object(batch_out(batch))


@app.route("/distribution-batches/<bid>/lines", methods=["GET"])
def list_batch_lines(bid):
    require_roles(["Admin", "RoyaltyOps", "RoyaltyAuditor"])
    get_or_404(store.distribution_batches, bid)
    items = [l for l in store.distribution_lines.values()
             if l["distribution_batch_id"] == bid]
    pt = request.args.get("payee_type")
    if pt is not None:
        items = [l for l in items if l["payee_type"] == pt]
    items = sort_created(items)
    page, limit, offset, total = paginate(items, request.args)
    return ok_array([line_out(l) for l in page], limit, offset, total)


@app.route("/distribution-lines/<lid>", methods=["GET"])
def get_distribution_line(lid):
    require_roles(["Admin", "RoyaltyOps", "RoyaltyAuditor"])
    l = get_or_404(store.distribution_lines, lid)
    return ok_object(line_out(l))


@app.route("/distribution-lines", methods=["GET"])
def list_distribution_lines():
    require_roles(["Admin", "RoyaltyOps", "RoyaltyAuditor"])
    items = list(store.distribution_lines.values())
    paid = request.args.get("payee_artist_id")
    if paid is not None:
        items = [l for l in items if l["payee_artist_id"] == paid]
    proid = request.args.get("payee_rights_owner_id")
    if proid is not None:
        items = [l for l in items if l["payee_rights_owner_id"] == proid]
    pt = request.args.get("payee_type")
    if pt is not None:
        items = [l for l in items if l["payee_type"] == pt]
    items = sort_created(items)
    page, limit, offset, total = paginate(items, request.args)
    return ok_array([line_out(l) for l in page], limit, offset, total)


# ---------------------------------------------------------------------------
# Artists & rights owners
# ---------------------------------------------------------------------------

def artist_out(a):
    return serialize(a)


def rights_owner_out(o):
    return serialize(o)


def _register_payee(collection, b, name_field):
    name = require_str(b, name_field)
    email = require_str(b, "contact_email")
    e = base_entity()
    e.update({
        name_field: name,
        "contact_email": email,
        "registration_status": "PENDING_VERIFICATION",
        "payee_verified_at": None,
    })
    collection[e["id"]] = e
    return e


def _payee_transition(entity, action):
    if action == "verify":
        if entity["registration_status"] != "PENDING_VERIFICATION":
            raise err_invalid_state("Registration is not PENDING_VERIFICATION")
        entity["registration_status"] = "VERIFIED"
        entity["payee_verified_at"] = logical_now()
    elif action == "reject":
        if entity["registration_status"] != "PENDING_VERIFICATION":
            raise err_invalid_state("Registration is not PENDING_VERIFICATION")
        entity["registration_status"] = "REJECTED"
    elif action == "suspend":
        if entity["registration_status"] != "VERIFIED":
            raise err_invalid_state("Registration is not VERIFIED")
        entity["registration_status"] = "SUSPENDED"
    touch(entity)


@app.route("/artists", methods=["POST"])
def create_artist():
    require_roles(["Admin", "PayeeAdmin"])
    a = _register_payee(store.artists, body(), "stage_name")
    return ok_object(artist_out(a), 201)


@app.route("/artists", methods=["GET"])
def list_artists():
    require_roles(["Admin", "PayeeAdmin", "RoyaltyOps"])
    items = list(store.artists.values())
    st = request.args.get("registration_status")
    if st is not None:
        items = [a for a in items if a["registration_status"] == st]
    items = sort_created(items)
    page, limit, offset, total = paginate(items, request.args)
    return ok_array([artist_out(a) for a in page], limit, offset, total)


@app.route("/artists/<aid>", methods=["GET"])
def get_artist(aid):
    require_roles(["Admin", "PayeeAdmin", "RoyaltyOps"])
    a = get_or_404(store.artists, aid)
    return ok_object(artist_out(a))


@app.route("/artists/<aid>/verify", methods=["POST"])
def verify_artist(aid):
    require_roles(["PayeeAdmin"])
    a = get_or_404(store.artists, aid)
    _payee_transition(a, "verify")
    return ok_object(artist_out(a))


@app.route("/artists/<aid>/reject_registration", methods=["POST"])
def reject_artist(aid):
    require_roles(["PayeeAdmin"])
    a = get_or_404(store.artists, aid)
    b = body()
    if b.get("reason") is not None and not isinstance(b.get("reason"), str):
        raise err_invalid_request("reason must be a string")
    _payee_transition(a, "reject")
    return ok_object(artist_out(a))


@app.route("/artists/<aid>/suspend_registration", methods=["POST"])
def suspend_artist(aid):
    require_roles(["PayeeAdmin"])
    a = get_or_404(store.artists, aid)
    _payee_transition(a, "suspend")
    return ok_object(artist_out(a))


@app.route("/rights-owners", methods=["POST"])
def create_rights_owner():
    require_roles(["Admin", "PayeeAdmin"])
    o = _register_payee(store.rights_owners, body(), "legal_name")
    return ok_object(rights_owner_out(o), 201)


@app.route("/rights-owners", methods=["GET"])
def list_rights_owners():
    require_roles(["Admin", "PayeeAdmin", "RoyaltyOps"])
    items = list(store.rights_owners.values())
    st = request.args.get("registration_status")
    if st is not None:
        items = [o for o in items if o["registration_status"] == st]
    items = sort_created(items)
    page, limit, offset, total = paginate(items, request.args)
    return ok_array([rights_owner_out(o) for o in page], limit, offset, total)


@app.route("/rights-owners/<oid>", methods=["GET"])
def get_rights_owner(oid):
    require_roles(["Admin", "PayeeAdmin", "RoyaltyOps"])
    o = get_or_404(store.rights_owners, oid)
    return ok_object(rights_owner_out(o))


@app.route("/rights-owners/<oid>/verify", methods=["POST"])
def verify_rights_owner(oid):
    require_roles(["PayeeAdmin"])
    o = get_or_404(store.rights_owners, oid)
    _payee_transition(o, "verify")
    return ok_object(rights_owner_out(o))


@app.route("/rights-owners/<oid>/reject_registration", methods=["POST"])
def reject_rights_owner(oid):
    require_roles(["PayeeAdmin"])
    o = get_or_404(store.rights_owners, oid)
    b = body()
    if b.get("reason") is not None and not isinstance(b.get("reason"), str):
        raise err_invalid_request("reason must be a string")
    _payee_transition(o, "reject")
    return ok_object(rights_owner_out(o))


@app.route("/rights-owners/<oid>/suspend_registration", methods=["POST"])
def suspend_rights_owner(oid):
    require_roles(["PayeeAdmin"])
    o = get_or_404(store.rights_owners, oid)
    _payee_transition(o, "suspend")
    return ok_object(rights_owner_out(o))


# ---------------------------------------------------------------------------
# Recordings & ownership claims
# ---------------------------------------------------------------------------

def recording_out(r):
    return serialize(r)


def claim_out(c):
    return serialize(c)


@app.route("/recordings", methods=["POST"])
def create_recording():
    require_roles(["Admin"])
    b = body()
    isrc = require_str(b, "isrc")
    track_title = require_str(b, "track_title")
    roid = b.get("rights_owner_id")
    if not isinstance(roid, str) or not roid:
        raise err_invalid_request("rights_owner_id is required")
    faid = b.get("featured_artist_id")
    if not isinstance(faid, str) or not faid:
        raise err_invalid_request("featured_artist_id is required")
    if roid not in store.rights_owners:
        raise err_not_found("rights_owner_id does not reference an existing rights owner")
    if faid not in store.artists:
        raise err_not_found("featured_artist_id does not reference an existing artist")
    for rec in store.recordings.values():
        if rec["isrc"] == isrc:
            raise ApiError("ERR_DUPLICATE_ISRC", 409, "Recording ISRC already registered")
    r = base_entity()
    r.update({
        "isrc": isrc,
        "track_title": track_title,
        "rights_owner_id": roid,
        "featured_artist_id": faid,
        "catalog_status": "ACTIVE",
    })
    store.recordings[r["id"]] = r
    return ok_object(recording_out(r), 201)


@app.route("/recordings", methods=["GET"])
def list_recordings():
    require_roles(["Admin", "RoyaltyOps", "PayeeAdmin", "MatchingAgent"])
    items = list(store.recordings.values())
    isrc = request.args.get("isrc")
    if isrc is not None:
        items = [r for r in items if r["isrc"] == isrc]
    st = request.args.get("catalog_status")
    if st is not None:
        items = [r for r in items if r["catalog_status"] == st]
    roid = request.args.get("rights_owner_id")
    if roid is not None:
        items = [r for r in items if r["rights_owner_id"] == roid]
    faid = request.args.get("featured_artist_id")
    if faid is not None:
        items = [r for r in items if r["featured_artist_id"] == faid]
    items = sort_created(items)
    page, limit, offset, total = paginate(items, request.args)
    return ok_array([recording_out(r) for r in page], limit, offset, total)


@app.route("/recordings/<rid>", methods=["GET"])
def get_recording(rid):
    require_roles(["Admin", "RoyaltyOps", "PayeeAdmin", "MatchingAgent"])
    r = get_or_404(store.recordings, rid)
    return ok_object(recording_out(r))


@app.route("/recordings/<rid>/withdraw", methods=["POST"])
def withdraw_recording(rid):
    require_roles(["Admin"])
    r = get_or_404(store.recordings, rid)
    if r["catalog_status"] != "ACTIVE":
        raise err_invalid_state("Recording is not ACTIVE")
    for c in store.ownership_claims.values():
        if c["recording_id"] == rid and c["claim_status"] in ("OPEN", "UNDER_REVIEW"):
            raise ApiError("ERR_RECORDING_IN_DISPUTE", 409,
                           "Recording has an OPEN or UNDER_REVIEW ownership claim")
    r["catalog_status"] = "WITHDRAWN"
    touch(r)
    return ok_object(recording_out(r))


@app.route("/recordings/<rid>/ownership-claims", methods=["POST"])
def create_claim(rid):
    require_roles(["PayeeAdmin"])
    rec = get_or_404(store.recordings, rid)
    b = body()
    claimant_type = require_enum(b, "claimant_type", {"RIGHTS_OWNER", "FEATURED_ARTIST"})
    claimant_id = b.get("claimant_id")
    if not isinstance(claimant_id, str) or not claimant_id:
        raise err_invalid_request("claimant_id is required")
    share = require_number(b, "claimed_share_pct", min_exclusive=0, max_inclusive=100)
    claimant = (store.rights_owners.get(claimant_id) if claimant_type == "RIGHTS_OWNER"
                else store.artists.get(claimant_id))
    if claimant is None:
        raise err_not_found("claimant_id does not reference an existing payee")
    if rec["catalog_status"] == "WITHDRAWN":
        raise ApiError("ERR_RECORDING_WITHDRAWN", 409, "Claim target recording is WITHDRAWN")
    if claimant["registration_status"] != "VERIFIED":
        raise ApiError("ERR_PAYEE_NOT_VERIFIED", 409,
                       "Claimant registration is not VERIFIED")
    c = base_entity()
    c.update({
        "recording_id": rid,
        "claimant_type": claimant_type,
        "claimant_id": claimant_id,
        "claimed_share_pct": share,
        "claim_status": "OPEN",
        "resolution_note": None,
    })
    store.ownership_claims[c["id"]] = c
    return ok_object(claim_out(c), 201)


@app.route("/recordings/<rid>/ownership-claims", methods=["GET"])
def list_recording_claims(rid):
    require_roles(["Admin", "PayeeAdmin", "RoyaltyOps"])
    get_or_404(store.recordings, rid)
    items = [c for c in store.ownership_claims.values() if c["recording_id"] == rid]
    st = request.args.get("claim_status")
    if st is not None:
        items = [c for c in items if c["claim_status"] == st]
    items = sort_created(items)
    page, limit, offset, total = paginate(items, request.args)
    return ok_array([claim_out(c) for c in page], limit, offset, total)


@app.route("/ownership-claims/<cid>", methods=["GET"])
def get_claim(cid):
    require_roles(["Admin", "PayeeAdmin", "RoyaltyOps"])
    c = get_or_404(store.ownership_claims, cid)
    return ok_object(claim_out(c))


@app.route("/ownership-claims", methods=["GET"])
def list_claims():
    require_roles(["Admin", "PayeeAdmin", "RoyaltyOps"])
    items = list(store.ownership_claims.values())
    cid = request.args.get("claimant_id")
    if cid is not None:
        items = [c for c in items if c["claimant_id"] == cid]
    st = request.args.get("claim_status")
    if st is not None:
        items = [c for c in items if c["claim_status"] == st]
    items = sort_created(items)
    page, limit, offset, total = paginate(items, request.args)
    return ok_array([claim_out(c) for c in page], limit, offset, total)


@app.route("/ownership-claims/<cid>/start_review", methods=["POST"])
def start_review_claim(cid):
    require_roles(["PayeeAdmin"])
    c = get_or_404(store.ownership_claims, cid)
    if c["claim_status"] != "OPEN":
        raise err_invalid_state("Claim is not OPEN")
    c["claim_status"] = "UNDER_REVIEW"
    touch(c)
    return ok_object(claim_out(c))


@app.route("/ownership-claims/<cid>/reopen", methods=["POST"])
def reopen_claim(cid):
    require_roles(["PayeeAdmin"])
    c = get_or_404(store.ownership_claims, cid)
    if c["claim_status"] != "UNDER_REVIEW":
        raise err_invalid_state("Claim is not UNDER_REVIEW")
    c["claim_status"] = "OPEN"
    touch(c)
    return ok_object(claim_out(c))


@app.route("/ownership-claims/<cid>/resolve", methods=["POST"])
def resolve_claim(cid):
    require_roles(["PayeeAdmin"])
    c = get_or_404(store.ownership_claims, cid)
    b = body()
    outcome = require_enum(b, "outcome", {"UPHELD", "REJECTED"})
    note = b.get("resolution_note")
    if note is not None and not isinstance(note, str):
        raise err_invalid_request("resolution_note must be a string")
    if c["claim_status"] != "UNDER_REVIEW":
        raise err_invalid_state("Claim is not UNDER_REVIEW")
    c["claim_status"] = outcome
    c["resolution_note"] = note
    touch(c)
    if outcome == "UPHELD":
        rec = store.recordings.get(c["recording_id"])
        if rec is not None:
            if c["claimant_type"] == "RIGHTS_OWNER":
                rec["rights_owner_id"] = c["claimant_id"]
            else:
                rec["featured_artist_id"] = c["claimant_id"]
            touch(rec)
    return ok_object(claim_out(c))


@app.route("/ownership-claims/<cid>/withdraw", methods=["POST"])
def withdraw_claim(cid):
    require_roles(["PayeeAdmin"])
    c = get_or_404(store.ownership_claims, cid)
    if c["claim_status"] != "OPEN":
        raise err_invalid_state("Claim is not OPEN")
    c["claim_status"] = "WITHDRAWN"
    touch(c)
    return ok_object(claim_out(c))


# ---------------------------------------------------------------------------
# Unclaimed pools
# ---------------------------------------------------------------------------

def pool_out(p):
    return serialize(p)


@app.route("/unclaimed-pools", methods=["POST"])
def create_pool():
    require_roles(["Admin"])
    b = body()
    start = parse_dt(b.get("period_start"), "period_start")
    end = parse_dt(b.get("period_end"), "period_end")
    if not (end >= start):
        raise err_invalid_request("period_end must be >= period_start")
    p = base_entity()
    p.update({
        "period_start": start,
        "period_end": end,
        "accrued_unmatched_cents": 0,
        "pool_status": "ACCRUING",
        "distributed_cents": 0,
        "campaign_count": 0,
    })
    store.unclaimed_pools[p["id"]] = p
    return ok_object(pool_out(p), 201)


@app.route("/unclaimed-pools", methods=["GET"])
def list_pools():
    require_roles(["Admin", "RoyaltyOps", "MatchingAgent"])
    items = list(store.unclaimed_pools.values())
    st = request.args.get("pool_status")
    if st is not None:
        items = [p for p in items if p["pool_status"] == st]
    items = sort_created(items)
    page, limit, offset, total = paginate(items, request.args)
    return ok_array([pool_out(p) for p in page], limit, offset, total)


@app.route("/unclaimed-pools/<pid>", methods=["GET"])
def get_pool(pid):
    require_roles(["Admin", "RoyaltyOps", "MatchingAgent"])
    p = get_or_404(store.unclaimed_pools, pid)
    return ok_object(pool_out(p))


@app.route("/unclaimed-pools/<pid>/start_campaign", methods=["POST"])
def start_campaign(pid):
    require_roles(["MatchingAgent"])
    p = get_or_404(store.unclaimed_pools, pid)
    if p["pool_status"] != "ACCRUING":
        raise err_invalid_state("Pool is not ACCRUING")
    if p["accrued_unmatched_cents"] <= 0:
        raise err_invalid_state(
            "Starting a campaign requires a positive accrued unmatched balance")
    p["pool_status"] = "MATCHING_CAMPAIGN"
    touch(p)
    return ok_object(pool_out(p))


@app.route("/unclaimed-pools/<pid>/complete_campaign", methods=["POST"])
def complete_campaign(pid):
    require_roles(["MatchingAgent"])
    p = get_or_404(store.unclaimed_pools, pid)
    if p["pool_status"] != "MATCHING_CAMPAIGN":
        raise ApiError("ERR_CAMPAIGN_NOT_OPEN", 409,
                       "complete_campaign requires pool in MATCHING_CAMPAIGN")
    svc.run_matching_campaign(p)
    p["campaign_count"] += 1
    p["pool_status"] = "ACCRUING"
    if (p["campaign_count"] >= svc.CAMPAIGNS_BEFORE_DISTRIBUTION
            and p["accrued_unmatched_cents"] > 0):
        p["pool_status"] = "DISTRIBUTION_ELIGIBLE"
    touch(p)
    return ok_object(pool_out(p))


@app.route("/unclaimed-pools/<pid>/release", methods=["POST"])
def release_pool(pid):
    require_roles(["RoyaltyOps"])
    p = get_or_404(store.unclaimed_pools, pid)
    if p["pool_status"] != "DISTRIBUTION_ELIGIBLE":
        raise ApiError("ERR_POOL_NOT_DISTRIBUTABLE", 409,
                       "Pool not in DISTRIBUTION_ELIGIBLE")
    svc.release_pool(p)
    p["pool_status"] = "DISTRIBUTED"
    touch(p)
    return ok_object(pool_out(p))


@app.route("/unclaimed-pools/<pid>/expire", methods=["POST"])
def expire_pool(pid):
    require_roles(["Admin"])
    p = get_or_404(store.unclaimed_pools, pid)
    if p["pool_status"] != "ACCRUING":
        raise err_invalid_state("Pool is not ACCRUING")
    from datetime import timedelta as _td
    deadline = day_floor(p["period_end"]) + _td(days=svc.UNCLAIMED_EXPIRY_DAYS)
    if not (logical_now() > deadline):
        raise ApiError("ERR_POOL_NOT_EXPIRABLE", 409,
                       "Pool expiry window (period_end + 365 days) not yet passed")
    p["pool_status"] = "EXPIRED"
    touch(p)
    return ok_object(pool_out(p))


# ---------------------------------------------------------------------------
# Audit cases
# ---------------------------------------------------------------------------

def audit_out(a):
    return serialize(a)


@app.route("/licensees/<lid>/audit-cases", methods=["POST"])
def create_audit(lid):
    user_id, _ = require_roles(["RoyaltyAuditor"])
    get_or_404(store.licensees, lid)
    b = body()
    auditor_ref = require_str(b, "auditor_ref")
    start = parse_dt(b.get("period_start"), "period_start")
    end = parse_dt(b.get("period_end"), "period_end")
    if not (end >= start):
        raise err_invalid_request("period_end must be >= period_start")
    a = base_entity()
    a.update({
        "licensee_id": lid,
        "auditor_ref": auditor_ref,
        "period_start": start,
        "period_end": end,
        "audit_status": "OPENED",
        "assessed_underpayment_cents": 0,
        "recovered_cents": 0,
        "opened_by": user_id,
    })
    store.audit_cases[a["id"]] = a
    return ok_object(audit_out(a), 201)


@app.route("/audit-cases/<aid>", methods=["GET"])
def get_audit(aid):
    require_roles(["Admin", "RoyaltyOps", "RoyaltyAuditor"])
    a = get_or_404(store.audit_cases, aid)
    return ok_object(audit_out(a))


@app.route("/audit-cases/<aid>/issue_findings", methods=["POST"])
def issue_findings(aid):
    user_id, _ = require_roles(["RoyaltyAuditor"])
    a = get_or_404(store.audit_cases, aid)
    check_segregation(a, user_id)
    b = body()
    dtp = b.get("declared_true_performances")
    if isinstance(dtp, bool) or not isinstance(dtp, (int, dict)):
        raise err_invalid_request(
            "declared_true_performances is required (integer or object map)")
    if isinstance(dtp, dict):
        for k, v in dtp.items():
            if isinstance(v, bool) or not isinstance(v, int) or v < 0:
                raise err_invalid_request(
                    "declared_true_performances values must be non-negative integers")
    elif dtp < 0:
        raise err_invalid_request("declared_true_performances must be >= 0")
    if a["audit_status"] != "OPENED":
        raise err_invalid_state("Audit is not OPENED")
    if not svc.licensee_has_report_in_status_overlapping(
            a["licensee_id"], a["period_start"], a["period_end"],
            ("ACCEPTED", "AMENDED")):
        raise err_invalid_state(
            "No ACCEPTED/AMENDED report of the licensee overlaps the audit window")
    a["assessed_underpayment_cents"] = svc.issue_findings_calc(a, dtp)
    a["audit_status"] = "FINDINGS_ISSUED"
    touch(a)
    return ok_object(audit_out(a))


@app.route("/audit-cases/<aid>/record_recovery", methods=["POST"])
def record_recovery(aid):
    user_id, _ = require_roles(["RoyaltyAuditor"])
    a = get_or_404(store.audit_cases, aid)
    check_segregation(a, user_id)
    b = body()
    amount = require_int(b, "amount_cents", min_val=0)
    final = b.get("final")
    if not isinstance(final, bool):
        raise err_invalid_request("final is required and must be a boolean")
    if a["audit_status"] != "FINDINGS_ISSUED":
        raise err_invalid_state("Audit is not FINDINGS_ISSUED")
    if a["recovered_cents"] + amount > a["assessed_underpayment_cents"]:
        raise ApiError("ERR_RECOVERY_EXCEEDS_ASSESSMENT", 409,
                       "Cumulative recovery would exceed assessed underpayment")
    a["recovered_cents"] += amount
    svc.add_min_fee_paid(a["licensee_id"], a["period_start"].year, amount)
    if final:
        a["audit_status"] = "SETTLED"
        if a["recovered_cents"] < a["assessed_underpayment_cents"]:
            licensee = store.licensees.get(a["licensee_id"])
            if licensee is not None and licensee["license_status"] == "ACTIVE":
                svc.suspend_licensee_cascade(licensee, "UNDERPAYMENT_SHORTFALL")
    touch(a)
    return ok_object(audit_out(a))


@app.route("/audit-cases/<aid>/close", methods=["POST"])
def close_audit(aid):
    user_id, _ = require_roles(["RoyaltyAuditor"])
    a = get_or_404(store.audit_cases, aid)
    check_segregation(a, user_id)
    if a["audit_status"] != "FINDINGS_ISSUED":
        raise err_invalid_state("Audit is not FINDINGS_ISSUED")
    if not (a["assessed_underpayment_cents"] == 0
            or a["recovered_cents"] == a["assessed_underpayment_cents"]):
        raise ApiError("ERR_AUDIT_NOT_SETTLABLE", 409,
                       "Audit cannot close: assessment positive and not fully recovered")
    a["audit_status"] = "CLOSED"
    touch(a)
    return ok_object(audit_out(a))


@app.route("/audit-cases/<aid>/waive", methods=["POST"])
def waive_audit(aid):
    require_roles(["RoyaltyAuditor"])
    a = get_or_404(store.audit_cases, aid)
    b = body()
    if b.get("reason") is not None and not isinstance(b.get("reason"), str):
        raise err_invalid_request("reason must be a string")
    if a["audit_status"] != "OPENED":
        raise err_invalid_state("Audit is not OPENED")
    a["audit_status"] = "WAIVED"
    touch(a)
    return ok_object(audit_out(a))


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", "10000")))
