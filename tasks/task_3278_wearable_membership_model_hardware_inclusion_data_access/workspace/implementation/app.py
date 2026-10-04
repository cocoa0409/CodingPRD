#!/usr/bin/env python3
"""Wearable Membership API — task 3278 implementation (Flask, in-memory)."""

import os
import re
import secrets
import string
import uuid
from datetime import date, datetime, timezone

from dateutil.relativedelta import relativedelta
from decimal import Decimal, ROUND_HALF_UP

from flask import Flask, request, jsonify

app = Flask(__name__)

# ----------------------------------------------------------------------------
# In-memory store + logical clock
# ----------------------------------------------------------------------------

DEFAULT_CLOCK = datetime(2026, 9, 1, 0, 0, 0, tzinfo=timezone.utc)

STORE = {
    "members": {},
    "terms": {},
    "devices": {},
    "metric_sets": {},
    "releases": {},
    "teams": {},
    "team_memberships": {},
    "studies": {},
    "enrollments": {},
    "replacement_requests": {},
    "merch_orders": {},
}
CLOCK = {"now": DEFAULT_CLOCK}

ROLES = {"Anonymous", "Member", "Coach", "Support", "PlatformAdmin"}
HARDWARE_TIERS = {"BAND_STD", "BAND_PRO"}
CANCEL_FEE_POLICIES = {"REMAINING_MONTHS", "PAID_MONTHS_FLOOR"}
REPLACEMENT_REASONS = {"HARDWARE_FAILURE", "BATTERY_DRAIN", "SENSOR_DRIFT"}
TEAM_TYPES = {"SPORTS", "CORPORATE_WELLNESS"}
CONSENT_SCOPES = {"STRAIN", "RECOVERY", "SLEEP"}
CONSENT_ACTIONS = {"GRANT", "REVOKE"}
MERCH_CATEGORIES = {"BAND_ACCESSORY", "APPAREL", "RECOVERY_GEAR"}
REJECT_DIAGNOSES = {"NO_FAULT", "USER_DAMAGE"}

# ----------------------------------------------------------------------------
# Helpers
# ----------------------------------------------------------------------------


def now():
    return CLOCK["now"]


def today():
    return CLOCK["now"].date()


def iso_now():
    return CLOCK["now"].strftime("%Y-%m-%dT%H:%M:%S.%f")[:-3] + "Z"


def new_id():
    return str(uuid.uuid4())


def round_half_up(value, places):
    q = Decimal(1).scaleb(-places)
    return Decimal(value).quantize(q, rounding=ROUND_HALF_UP)


def parse_iso_datetime(s):
    if not isinstance(s, str):
        return None
    try:
        t = s.strip()
        if t.endswith("Z"):
            t = t[:-1] + "+00:00"
        dt = datetime.fromisoformat(t)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt.astimezone(timezone.utc)
    except (ValueError, TypeError):
        return None


def parse_iso_date(s):
    if not isinstance(s, str):
        return None
    if not re.fullmatch(r"\d{4}-\d{2}-\d{2}", s):
        return None
    try:
        return date.fromisoformat(s)
    except ValueError:
        return None


def is_int(v):
    return isinstance(v, int) and not isinstance(v, bool)


def is_num(v):
    return isinstance(v, (int, float)) and not isinstance(v, bool)


class ApiError(Exception):
    def __init__(self, error_id, http_status, message):
        super().__init__(message)
        self.error_id = error_id
        self.http_status = http_status
        self.message = message


def err_missing_ctx(msg="Missing or invalid context headers"):
    return ApiError("ERR_MISSING_OR_INVALID_CONTEXT_HEADER", 400, msg)


def err_forbidden_role(msg="Role not allowed for this endpoint"):
    return ApiError("ERR_FORBIDDEN_ROLE", 403, msg)


def err_not_owner(msg="Actor does not own the target resource"):
    return ApiError("ERR_NOT_RESOURCE_OWNER", 403, msg)


def err_not_found(msg="Resource not found"):
    return ApiError("ERR_NOT_FOUND", 404, msg)


def err_invalid(msg="Invalid request"):
    return ApiError("ERR_INVALID_REQUEST", 400, msg)


def err_state(msg="Invalid state transition"):
    return ApiError("ERR_INVALID_STATE_TRANSITION", 409, msg)


def err_stale(msg="Stale version"):
    return ApiError("ERR_STALE_VERSION", 412, msg)


def err_suspended(msg="Member is suspended"):
    return ApiError("ERR_MEMBER_SUSPENDED", 409, msg)


def meta():
    return {
        "api_request_id": "req_" + "".join(
            secrets.choice(string.ascii_letters + string.digits) for _ in range(20)
        ),
        "api_request_timestamp": iso_now(),
    }


def success(data, code=200, pag=None):
    body = {
        "meta": meta(),
        "response_type": "array" if isinstance(data, list) else "object",
        "data": data,
    }
    if pag is not None:
        body["meta"].update(pag)
    return jsonify(body), code


@app.errorhandler(ApiError)
def handle_api_error(e):
    body = {
        "meta": meta(),
        "response_type": "error",
        "data": {"error_id": e.error_id, "message": e.message},
    }
    return jsonify(body), e.http_status


@app.errorhandler(404)
def handle_404(e):
    return handle_api_error(err_not_found("Route not found"))


@app.errorhandler(405)
def handle_405(e):
    return handle_api_error(err_not_found("Route not found"))


@app.errorhandler(Exception)
def handle_unexpected(e):
    app.logger.exception("unexpected error")
    return handle_api_error(ApiError("ERR_INTERNAL", 500, str(e)))


# ----------------------------------------------------------------------------
# Validation plumbing
# ----------------------------------------------------------------------------


def current_role():
    uid = request.headers.get("X-User-ID")
    role = request.headers.get("X-User-Role")
    if not uid or not role or role not in ROLES:
        raise err_missing_ctx()
    return uid, role


def require_role(role, allowed):
    if role not in allowed:
        raise err_forbidden_role()


def parse_pagination():
    limit_s = request.args.get("limit")
    offset_s = request.args.get("offset")
    if limit_s is None:
        limit = 10
    else:
        try:
            limit = int(limit_s, 10)
        except (ValueError, TypeError):
            raise err_invalid("limit must be an integer")
        if limit < 1 or limit > 100:
            raise err_invalid("limit out of range")
    if offset_s is None:
        offset = 0
    else:
        try:
            offset = int(offset_s, 10)
        except (ValueError, TypeError):
            raise err_invalid("offset must be an integer")
        if offset < 0:
            raise err_invalid("offset out of range")
    return limit, offset


def paginate(items):
    items = sorted(items, key=lambda r: (r["created_at"], r["id"]))
    limit, offset = parse_pagination()
    page = items[offset:offset + limit]
    return page, {
        "limit": limit,
        "offset": offset,
        "total_count": len(items),
        "has_more": offset + limit < len(items),
    }


def json_body():
    if not request.data:
        return {}
    try:
        body = request.get_json(force=True, silent=False)
    except Exception:
        raise err_invalid("Malformed JSON body")
    if body is None:
        return {}
    if not isinstance(body, dict):
        raise err_invalid("Body must be a JSON object")
    return body


def require_fields(body, names):
    for n in names:
        if n not in body:
            raise err_invalid("Missing required field: %s" % n)


# ----------------------------------------------------------------------------
# Business helpers
# ----------------------------------------------------------------------------


def latest_term(member_id):
    terms = [t for t in STORE["terms"].values() if t["member_id"] == member_id]
    if not terms:
        return None
    terms.sort(key=lambda t: (t["created_at"], t["id"]))
    return terms[-1]


def current_term(member_id):
    terms = [
        t
        for t in STORE["terms"].values()
        if t["member_id"] == member_id and t["term_status"] in ("ACTIVE", "PAUSED")
    ]
    if not terms:
        return None
    terms.sort(key=lambda t: (t["created_at"], t["id"]))
    return terms[-1]


def add_months(d, months):
    return d + relativedelta(months=months)


def full_months_between(anchor, day):
    months = (day.year - anchor.year) * 12 + (day.month - anchor.month)
    if day.day < anchor.day:
        months -= 1
    return months


def current_published_version():
    pubs = [r for r in STORE["releases"].values() if r["release_status"] == "PUBLISHED"]
    if not pubs:
        return 1
    return max(r["version"] for r in pubs)


def compute_scores(avg_hr, hrv_ms, resting_hr, sleep_minutes, version):
    a = Decimal(str(avg_hr))
    h = Decimal(str(hrv_ms))
    r = Decimal(str(resting_hr))
    s = Decimal(str(sleep_minutes))
    if version >= 2:
        strain = min(Decimal(21), a / Decimal("9.0"))
        if h + r == 0:
            rec = Decimal(0)
        else:
            rec = (h * Decimal(100) / (h + r)) * Decimal("0.9") + Decimal(5)
        rec = min(Decimal(100), rec)
        sleep = min(Decimal(100), s * Decimal(100) / Decimal(450))
    else:
        strain = min(Decimal(21), a / Decimal("10.0"))
        if h + r == 0:
            rec = Decimal(0)
        else:
            rec = h * Decimal(100) / (h + r)
        rec = min(Decimal(100), rec)
        sleep = min(Decimal(100), s * Decimal(100) / Decimal(480))
    strain = round_half_up(strain, 1)
    rec = round_half_up(rec, 0)
    sleep = round_half_up(sleep, 0)
    return float(strain), int(rec), int(sleep)


def touch(ent):
    ent["updated_at"] = iso_now()
    ent["version"] += 1


def member_suspension_recompute(member):
    has_past_due = any(
        t["term_status"] == "PAST_DUE"
        for t in STORE["terms"].values()
        if t["member_id"] == member["id"]
    )
    if has_past_due and member["member_status"] != "SUSPENDED":
        member["member_status"] = "SUSPENDED"
        touch(member)
    elif not has_past_due and member["member_status"] == "SUSPENDED":
        member["member_status"] = "ACTIVE"
        touch(member)


def apply_clock_transitions():
    tday = today()
    # open SCHEDULED pause windows whose start has been reached
    for term in STORE["terms"].values():
        if term["term_status"] != "ACTIVE":
            continue
        for w in term["pause_windows"]:
            if w["window_status"] == "SCHEDULED" and parse_iso_date(w["start_on"]) <= tday:
                w["window_status"] = "OPEN"
                term["open_pause_end_on"] = w["end_on"]
                term["term_status"] = "PAUSED"
                touch(term)
                break
    # close OPEN pause windows whose scheduled end has been reached
    for term in STORE["terms"].values():
        if term["term_status"] != "PAUSED":
            continue
        for w in term["pause_windows"]:
            if w["window_status"] == "OPEN" and parse_iso_date(w["end_on"]) <= tday:
                w["window_status"] = "CLOSED"
                term["pause_days_used"] += (
                    parse_iso_date(w["end_on"]) - parse_iso_date(w["start_on"])
                ).days
                term["open_pause_end_on"] = None
                term["term_status"] = "ACTIVE"
                touch(term)
                break
    # consent expiry
    for m in STORE["team_memberships"].values():
        changed = False
        for e in m["consent_scopes"]:
            if (
                e["status"] == "GRANTED"
                and e.get("expires_on") is not None
                and parse_iso_date(e["expires_on"]) < tday
            ):
                e["status"] = "EXPIRED"
                changed = True
        if changed:
            touch(m)
    # term completion
    for term in STORE["terms"].values():
        if (
            term["term_status"] == "ACTIVE"
            and tday >= parse_iso_date(term["commitment_end_on"])
            and term["months_paid"] >= term["commitment_months"]
        ):
            term["term_status"] = "COMPLETED"
            touch(term)


def study_status(study):
    tday = today()
    start = parse_iso_date(study["enrollment_window_start_on"])
    end = parse_iso_date(study["enrollment_window_end_on"])
    return "RECRUITING" if start <= tday <= end else "CLOSED"


def latest_metric(member_id):
    sets = [x for x in STORE["metric_sets"].values() if x["member_id"] == member_id]
    if not sets:
        return None
    sets.sort(key=lambda x: (x["day_on"], x["created_at"], x["id"]))
    return sets[-1]


# ----------------------------------------------------------------------------
# Serializers
# ----------------------------------------------------------------------------


def member_out(m):
    return {
        "id": m["id"],
        "email": m["email"],
        "full_name": m["full_name"],
        "member_status": m["member_status"],
        "wallet_credit_cents": m["wallet_credit_cents"],
        "data_sharing_posture": m["data_sharing_posture"],
        "algorithm_ack_release_id": m["algorithm_ack_release_id"],
        "created_at": m["created_at"],
        "updated_at": m["updated_at"],
        "version": m["version"],
    }


def term_out(t):
    return {
        "id": t["id"],
        "member_id": t["member_id"],
        "plan_name": t["plan_name"],
        "monthly_fee_cents": t["monthly_fee_cents"],
        "commitment_months": t["commitment_months"],
        "hardware_tier": t["hardware_tier"],
        "upgrade_eligibility_months": t["upgrade_eligibility_months"],
        "pause_days_per_term": t["pause_days_per_term"],
        "cancel_fee_policy": t["cancel_fee_policy"],
        "early_cancel_fee_floor_cents": t["early_cancel_fee_floor_cents"],
        "term_status": t["term_status"],
        "started_on": t["started_on"],
        "commitment_end_on": t["commitment_end_on"],
        "months_paid": t["months_paid"],
        "pause_days_used": t["pause_days_used"],
        "pause_windows": [dict(w) for w in t["pause_windows"]],
        "open_pause_end_on": t["open_pause_end_on"],
        "cancel_fee_charged_cents": t["cancel_fee_charged_cents"],
        "last_upgrade_on": t["last_upgrade_on"],
        "created_at": t["created_at"],
        "updated_at": t["updated_at"],
        "version": t["version"],
    }


def device_out(d):
    return {
        "id": d["id"],
        "member_id": d["member_id"],
        "term_id": d["term_id"],
        "serial_number": d["serial_number"],
        "hardware_tier": d["hardware_tier"],
        "device_status": d["device_status"],
        "activated_on": d["activated_on"],
        "continuity_start_on": d["continuity_start_on"],
        "continuity_end_on": d["continuity_end_on"],
        "diagnosis": d["diagnosis"],
        "created_at": d["created_at"],
        "updated_at": d["updated_at"],
        "version": d["version"],
    }


def metric_out(m):
    return {
        "id": m["id"],
        "member_id": m["member_id"],
        "day_on": m["day_on"],
        "avg_hr": m["avg_hr"],
        "hrv_ms": m["hrv_ms"],
        "resting_hr": m["resting_hr"],
        "sleep_minutes": m["sleep_minutes"],
        "algorithm_version": m["algorithm_version"],
        "strain_score": m["strain_score"],
        "recovery_score": m["recovery_score"],
        "sleep_performance_pct": m["sleep_performance_pct"],
        "interpretation_status": m["interpretation_status"],
        "created_at": m["created_at"],
        "updated_at": m["updated_at"],
        "version": m["version"],
    }


def algo_release_out(r):
    return {
        "id": r["id"],
        "version": r["version"],
        "requires_member_ack": r["requires_member_ack"],
        "release_notes": r["release_notes"],
        "release_status": r["release_status"],
        "published_on": r["published_on"],
        "created_at": r["created_at"],
        "updated_at": r["updated_at"],
        "entity_version": r["entity_version"],
    }


def team_out(t):
    return {
        "id": t["id"],
        "name": t["name"],
        "team_type": t["team_type"],
        "coach_user_id": t["coach_user_id"],
        "created_at": t["created_at"],
        "updated_at": t["updated_at"],
        "version": t["version"],
    }


def membership_out(m):
    return {
        "id": m["id"],
        "team_id": m["team_id"],
        "member_id": m["member_id"],
        "membership_status": m["membership_status"],
        "consent_scopes": [dict(e) for e in m["consent_scopes"]],
        "created_at": m["created_at"],
        "updated_at": m["updated_at"],
        "version": m["version"],
    }


def study_out(s):
    return {
        "id": s["id"],
        "code": s["code"],
        "title": s["title"],
        "min_paid_months": s["min_paid_months"],
        "enrollment_window_start_on": s["enrollment_window_start_on"],
        "enrollment_window_end_on": s["enrollment_window_end_on"],
        "study_status": study_status(s),
        "created_at": s["created_at"],
        "updated_at": s["updated_at"],
        "version": s["version"],
    }


def enrollment_out(e):
    return {
        "id": e["id"],
        "study_id": e["study_id"],
        "member_id": e["member_id"],
        "enrollment_status": e["enrollment_status"],
        "enrolled_on": e["enrolled_on"],
        "member_seq": e["member_seq"],
        "created_at": e["created_at"],
        "updated_at": e["updated_at"],
        "version": e["version"],
    }


def replacement_out(r):
    return {
        "id": r["id"],
        "device_id": r["device_id"],
        "reason": r["reason"],
        "request_status": r["request_status"],
        "diagnosis": r["diagnosis"],
        "replacement_device_id": r["replacement_device_id"],
        "created_at": r["created_at"],
        "updated_at": r["updated_at"],
        "version": r["version"],
    }


def merch_out(o):
    return {
        "id": o["id"],
        "member_id": o["member_id"],
        "lines": [dict(l) for l in o["lines"]],
        "order_status": o["order_status"],
        "subtotal_cents": o["subtotal_cents"],
        "member_discount_cents": o["member_discount_cents"],
        "bundle_discount_cents": o["bundle_discount_cents"],
        "discount_cents": o["discount_cents"],
        "total_cents": o["total_cents"],
        "created_at": o["created_at"],
        "updated_at": o["updated_at"],
        "version": o["version"],
    }


def base_entity():
    ts = iso_now()
    return {"id": new_id(), "created_at": ts, "updated_at": ts, "version": 1}


# ----------------------------------------------------------------------------
# Loaders
# ----------------------------------------------------------------------------


def load_member(member_id):
    m = STORE["members"].get(member_id)
    if m is None:
        raise err_not_found("member not found")
    return m


def load_term(term_id):
    t = STORE["terms"].get(term_id)
    if t is None:
        raise err_not_found("term not found")
    return t


def load_device(device_id):
    d = STORE["devices"].get(device_id)
    if d is None:
        raise err_not_found("device not found")
    return d


def load_release(rid):
    r = STORE["releases"].get(rid)
    if r is None:
        raise err_not_found("release not found")
    return r


def load_team(tid):
    t = STORE["teams"].get(tid)
    if t is None:
        raise err_not_found("team not found")
    return t


def load_membership(mid):
    m = STORE["team_memberships"].get(mid)
    if m is None:
        raise err_not_found("team membership not found")
    return m


def load_study(sid):
    s = STORE["studies"].get(sid)
    if s is None:
        raise err_not_found("study not found")
    return s


def load_enrollment(eid):
    e = STORE["enrollments"].get(eid)
    if e is None:
        raise err_not_found("enrollment not found")
    return e


def load_replacement(rid):
    r = STORE["replacement_requests"].get(rid)
    if r is None:
        raise err_not_found("replacement request not found")
    return r


def load_merch_order(oid):
    o = STORE["merch_orders"].get(oid)
    if o is None:
        raise err_not_found("merch order not found")
    return o


# ----------------------------------------------------------------------------
# Clock endpoint
# ----------------------------------------------------------------------------


@app.route("/_clock/set_current_utc", methods=["POST"])
def set_clock():
    uid, role = current_role()
    require_role(role, {"PlatformAdmin"})
    body = json_body()
    require_fields(body, ["to_iso8601"])
    dt = parse_iso_datetime(body["to_iso8601"])
    if dt is None:
        raise err_invalid("to_iso8601 is not a valid ISO 8601 timestamp")
    CLOCK["now"] = dt
    apply_clock_transitions()
    return success({"current_utc": dt.strftime("%Y-%m-%dT%H:%M:%S.%f")[:-3] + "Z"}, 200)


# ----------------------------------------------------------------------------
# Members
# ----------------------------------------------------------------------------


@app.route("/members", methods=["POST"])
def create_member():
    uid, role = current_role()
    require_role(role, {"Anonymous"})
    body = json_body()
    require_fields(body, ["email", "full_name"])
    if not isinstance(body["email"], str) or not body["email"]:
        raise err_invalid("email must be a non-empty string")
    if not isinstance(body["full_name"], str) or not body["full_name"]:
        raise err_invalid("full_name must be a non-empty string")
    for m in STORE["members"].values():
        if m["email"] == body["email"]:
            raise err_invalid("email already registered")
    ent = base_entity()
    ent.update(
        {
            "email": body["email"],
            "full_name": body["full_name"],
            "member_status": "ACTIVE",
            "wallet_credit_cents": 0,
            "data_sharing_posture": "NORMAL",
            "algorithm_ack_release_id": None,
        }
    )
    STORE["members"][ent["id"]] = ent
    return success(member_out(ent), 201)


def check_member_ownership(member, uid, role):
    if role == "Member" and uid != member["id"]:
        raise err_not_owner("member id mismatch")


@app.route("/members/<mid>", methods=["GET"])
def get_member(mid):
    uid, role = current_role()
    require_role(role, {"Member", "Coach", "Support", "PlatformAdmin"})
    m = load_member(mid)
    check_member_ownership(m, uid, role)
    return success(member_out(m), 200)


@app.route("/members/<mid>/acknowledge-algorithm", methods=["POST"])
def acknowledge_algorithm(mid):
    uid, role = current_role()
    require_role(role, {"Member"})
    m = load_member(mid)
    check_member_ownership(m, uid, role)
    body = json_body()
    require_fields(body, ["release_id"])
    if not isinstance(body["release_id"], str):
        raise err_invalid("release_id must be a string")
    rel = STORE["releases"].get(body["release_id"])
    if rel is None:
        raise err_not_found("release not found")
    pubs = [r for r in STORE["releases"].values() if r["release_status"] == "PUBLISHED"]
    latest_pub = max(pubs, key=lambda r: r["version"]) if pubs else None
    m["algorithm_ack_release_id"] = body["release_id"]
    if latest_pub is not None and latest_pub["id"] == body["release_id"]:
        m["data_sharing_posture"] = "NORMAL"
    touch(m)
    return success(member_out(m), 200)


@app.route("/members/<mid>/terms", methods=["GET"])
def list_member_terms(mid):
    uid, role = current_role()
    require_role(role, {"Member", "Coach", "Support", "PlatformAdmin"})
    m = load_member(mid)
    check_member_ownership(m, uid, role)
    items = [t for t in STORE["terms"].values() if t["member_id"] == mid]
    page, pag = paginate(items)
    return success([term_out(t) for t in page], 200, pag)


@app.route("/members/<mid>/metric-sets", methods=["GET"])
def list_member_metric_sets(mid):
    uid, role = current_role()
    require_role(role, {"Member", "Coach", "Support", "PlatformAdmin"})
    m = load_member(mid)
    check_member_ownership(m, uid, role)
    items = [x for x in STORE["metric_sets"].values() if x["member_id"] == mid]
    day_on = request.args.get("day_on")
    if day_on is not None:
        if parse_iso_date(day_on) is None:
            raise err_invalid("day_on is not a valid date")
        items = [x for x in items if x["day_on"] == day_on]
    av = request.args.get("algorithm_version")
    if av is not None:
        try:
            av_i = int(av, 10)
        except (ValueError, TypeError):
            raise err_invalid("algorithm_version must be an integer")
        items = [x for x in items if x["algorithm_version"] == av_i]
    page, pag = paginate(items)
    return success([metric_out(x) for x in page], 200, pag)


@app.route("/members/<mid>/merch-orders", methods=["GET"])
def list_member_merch_orders(mid):
    uid, role = current_role()
    require_role(role, {"Member", "Support", "PlatformAdmin"})
    m = load_member(mid)
    check_member_ownership(m, uid, role)
    items = [o for o in STORE["merch_orders"].values() if o["member_id"] == mid]
    page, pag = paginate(items)
    return success([merch_out(o) for o in page], 200, pag)


@app.route("/members/<mid>/research-enrollments", methods=["GET"])
def list_member_enrollments(mid):
    uid, role = current_role()
    require_role(role, {"Member", "Support", "PlatformAdmin"})
    m = load_member(mid)
    check_member_ownership(m, uid, role)
    items = [e for e in STORE["enrollments"].values() if e["member_id"] == mid]
    page, pag = paginate(items)
    return success([enrollment_out(e) for e in page], 200, pag)


@app.route("/members/<mid>/terms", methods=["POST"])
def create_term(mid):
    uid, role = current_role()
    require_role(role, {"Member", "PlatformAdmin"})
    m = load_member(mid)
    check_member_ownership(m, uid, role)
    body = json_body()
    require_fields(
        body,
        [
            "plan_name",
            "monthly_fee_cents",
            "commitment_months",
            "hardware_tier",
            "upgrade_eligibility_months",
            "pause_days_per_term",
            "cancel_fee_policy",
            "early_cancel_fee_floor_cents",
        ],
    )
    if not isinstance(body["plan_name"], str) or not body["plan_name"]:
        raise err_invalid("plan_name must be a non-empty string")
    for fld in (
        "monthly_fee_cents",
        "commitment_months",
        "upgrade_eligibility_months",
        "pause_days_per_term",
        "early_cancel_fee_floor_cents",
    ):
        if not is_int(body[fld]) or body[fld] < 0:
            raise err_invalid("%s must be a non-negative integer" % fld)
    if body["commitment_months"] < 1:
        raise err_invalid("commitment_months must be at least 1")
    if body["hardware_tier"] not in HARDWARE_TIERS:
        raise err_invalid("hardware_tier must be BAND_STD or BAND_PRO")
    if body["cancel_fee_policy"] not in CANCEL_FEE_POLICIES:
        raise err_invalid("invalid cancel_fee_policy")
    if role == "Member" and m["member_status"] == "SUSPENDED":
        raise err_suspended()
    for t in STORE["terms"].values():
        if t["member_id"] == mid and t["term_status"] in ("ACTIVE", "PAUSED", "PAST_DUE"):
            raise ApiError("ERR_ACTIVE_TERM_EXISTS", 422, "member already has an open term")
    tday = today()
    ent = base_entity()
    ent.update(
        {
            "member_id": mid,
            "plan_name": body["plan_name"],
            "monthly_fee_cents": body["monthly_fee_cents"],
            "commitment_months": body["commitment_months"],
            "hardware_tier": body["hardware_tier"],
            "upgrade_eligibility_months": body["upgrade_eligibility_months"],
            "pause_days_per_term": body["pause_days_per_term"],
            "cancel_fee_policy": body["cancel_fee_policy"],
            "early_cancel_fee_floor_cents": body["early_cancel_fee_floor_cents"],
            "term_status": "ACTIVE",
            "started_on": tday.isoformat(),
            "commitment_end_on": add_months(tday, body["commitment_months"]).isoformat(),
            "months_paid": 0,
            "pause_days_used": 0,
            "pause_windows": [],
            "open_pause_end_on": None,
            "cancel_fee_charged_cents": None,
            "last_upgrade_on": None,
        }
    )
    STORE["terms"][ent["id"]] = ent
    return success(term_out(ent), 201)


# ----------------------------------------------------------------------------
# Merch orders
# ----------------------------------------------------------------------------


@app.route("/members/<mid>/merch-orders", methods=["POST"])
def create_merch_order(mid):
    uid, role = current_role()
    require_role(role, {"Member"})
    m = load_member(mid)
    check_member_ownership(m, uid, role)
    body = json_body()
    require_fields(body, ["lines"])
    lines = body["lines"]
    if not isinstance(lines, list) or not lines:
        raise err_invalid("lines must be a non-empty array")
    for ln in lines:
        if not isinstance(ln, dict):
            raise err_invalid("each line must be an object")
        require_fields(ln, ["sku", "category", "unit_price_cents", "qty"])
        if not isinstance(ln["sku"], str) or not ln["sku"]:
            raise err_invalid("line sku must be a non-empty string")
        if ln["category"] not in MERCH_CATEGORIES:
            raise err_invalid("invalid line category")
        if not is_int(ln["unit_price_cents"]) or ln["unit_price_cents"] < 0:
            raise err_invalid("unit_price_cents must be a non-negative integer")
        if not is_int(ln["qty"]) or ln["qty"] < 1:
            raise err_invalid("qty must be a positive integer")
    # state: suspended member gate
    if m["member_status"] == "SUSPENDED":
        raise err_suspended()
    # pricing
    subtotal = sum(ln["qty"] * ln["unit_price_cents"] for ln in lines)
    term = current_term(mid)
    member_pct = 10 if (term is not None and term["hardware_tier"] == "BAND_PRO") else 0
    member_discount = int(
        round_half_up(Decimal(subtotal) * Decimal(member_pct) / Decimal(100), 0)
    )
    apparel_lines = [ln for ln in lines if ln["category"] == "APPAREL"]
    apparel_qty = sum(ln["qty"] for ln in apparel_lines)
    apparel_subtotal = sum(ln["qty"] * ln["unit_price_cents"] for ln in apparel_lines)
    bundle_discount = (
        int(round_half_up(Decimal(apparel_subtotal) * Decimal(5) / Decimal(100), 0))
        if apparel_qty >= 3
        else 0
    )
    cap = int(round_half_up(Decimal(subtotal) * Decimal(30) / Decimal(100), 0))
    discount = min(member_discount + bundle_discount, cap)
    total = subtotal - discount
    # fiscal check
    if m["wallet_credit_cents"] < total:
        raise ApiError("ERR_INSUFFICIENT_WALLET_CREDIT", 422, "wallet balance insufficient")
    ent = base_entity()
    ent.update(
        {
            "member_id": mid,
            "lines": [
                {
                    "sku": ln["sku"],
                    "category": ln["category"],
                    "unit_price_cents": ln["unit_price_cents"],
                    "qty": ln["qty"],
                }
                for ln in lines
            ],
            "order_status": "PAID",
            "subtotal_cents": subtotal,
            "member_discount_cents": member_discount,
            "bundle_discount_cents": bundle_discount,
            "discount_cents": discount,
            "total_cents": total,
        }
    )
    STORE["merch_orders"][ent["id"]] = ent
    m["wallet_credit_cents"] -= total
    touch(m)
    return success(merch_out(ent), 201)


@app.route("/merch-orders/<oid>/cancel", methods=["POST"])
def cancel_merch_order(oid):
    uid, role = current_role()
    require_role(role, {"Member", "Support"})
    order = load_merch_order(oid)
    if role == "Member" and uid != order["member_id"]:
        raise err_not_owner("member id mismatch")
    if order["order_status"] != "PAID":
        raise err_state("order is not PAID")
    order["order_status"] = "CANCELLED"
    touch(order)
    member = load_member(order["member_id"])
    member["wallet_credit_cents"] += order["total_cents"]
    touch(member)
    return success(merch_out(order), 200)


# ----------------------------------------------------------------------------
# Term actions
# ----------------------------------------------------------------------------


def check_term_member_owner(term, uid, role):
    if role == "Member" and uid != term["member_id"]:
        raise err_not_owner("member id mismatch")


@app.route("/terms/<tid>/pause", methods=["POST"])
def pause_term(tid):
    uid, role = current_role()
    require_role(role, {"Member"})
    term = load_term(tid)
    check_term_member_owner(term, uid, role)
    body = json_body()
    require_fields(body, ["start_on", "days"])
    start = parse_iso_date(body["start_on"])
    if start is None:
        raise err_invalid("start_on is not a valid date")
    if not is_int(body["days"]) or body["days"] < 1:
        raise err_invalid("days must be a positive integer")
    days = body["days"]
    tday = today()
    if start < tday:
        raise err_invalid("start_on may not be in the past")
    # state
    if term["term_status"] != "ACTIVE":
        raise err_state("term is not ACTIVE")
    end = start + relativedelta(days=days)
    # temporal: half-open overlap vs SCHEDULED/OPEN windows
    for w in term["pause_windows"]:
        if w["window_status"] in ("SCHEDULED", "OPEN"):
            ws = parse_iso_date(w["start_on"])
            we = parse_iso_date(w["end_on"])
            if start < we and end > ws:
                raise ApiError(
                    "ERR_PAUSE_WINDOW_OVERLAP", 409, "pause window overlaps an existing window"
                )
    # business: budget
    committed = 0
    for w in term["pause_windows"]:
        if w["window_status"] in ("SCHEDULED", "OPEN"):
            committed += (parse_iso_date(w["end_on"]) - parse_iso_date(w["start_on"])).days
        elif w["window_status"] == "CLOSED":
            committed += (parse_iso_date(w["end_on"]) - parse_iso_date(w["start_on"])).days
    if committed + days > term["pause_days_per_term"]:
        raise ApiError("ERR_PAUSE_BUDGET_EXCEEDED", 422, "pause budget exceeded")
    window = {
        "start_on": start.isoformat(),
        "end_on": end.isoformat(),
        "window_status": "SCHEDULED",
    }
    if start == tday:
        window["window_status"] = "OPEN"
        term["term_status"] = "PAUSED"
        term["open_pause_end_on"] = end.isoformat()
    term["pause_windows"].append(window)
    touch(term)
    return success(term_out(term), 200)


@app.route("/terms/<tid>/resume", methods=["POST"])
def resume_term(tid):
    uid, role = current_role()
    require_role(role, {"Member"})
    term = load_term(tid)
    check_term_member_owner(term, uid, role)
    if term["term_status"] != "PAUSED":
        raise ApiError("ERR_TERM_NOT_PAUSED", 409, "term is not PAUSED")
    tday = today()
    open_window = None
    for w in term["pause_windows"]:
        if w["window_status"] == "OPEN":
            open_window = w
            break
    if open_window is None:
        raise ApiError("ERR_TERM_NOT_PAUSED", 409, "no open pause window")
    scheduled_end = parse_iso_date(open_window["end_on"])
    # early resume: close at today; if the clock reached the scheduled end the
    # clock sweep would already have closed it, so resume is always early here.
    unused_days = (scheduled_end - tday).days
    open_window["window_status"] = "CLOSED"
    open_window["end_on"] = tday.isoformat()
    term["pause_days_used"] += (tday - parse_iso_date(open_window["start_on"])).days
    term["open_pause_end_on"] = None
    term["term_status"] = "ACTIVE"
    touch(term)
    if unused_days > 0:
        credit = int(
            round_half_up(
                Decimal(term["monthly_fee_cents"]) * Decimal(unused_days) / Decimal(30), 0
            )
        )
        member = load_member(term["member_id"])
        member["wallet_credit_cents"] += credit
        touch(member)
    return success(term_out(term), 200)


@app.route("/terms/<tid>/record-payment", methods=["POST"])
def record_payment(tid):
    uid, role = current_role()
    require_role(role, {"Support", "PlatformAdmin"})
    term = load_term(tid)
    body = json_body()
    require_fields(body, ["outcome"])
    outcome = body["outcome"]
    if outcome not in ("SUCCEEDED", "FAILED"):
        raise err_invalid("outcome must be SUCCEEDED or FAILED")
    member = load_member(term["member_id"])
    if outcome == "SUCCEEDED":
        if term["term_status"] == "ACTIVE":
            term["months_paid"] += 1
            touch(term)
        elif term["term_status"] == "PAST_DUE":
            term["term_status"] = "ACTIVE"
            term["months_paid"] += 1
            touch(term)
            member_suspension_recompute(member)
        else:
            raise err_state("term does not accept a payment in its current state")
    else:  # FAILED
        if term["term_status"] != "ACTIVE":
            raise err_state("term is not ACTIVE")
        term["term_status"] = "PAST_DUE"
        touch(term)
        member_suspension_recompute(member)
    return success(term_out(term), 200)


@app.route("/terms/<tid>/cancel", methods=["POST"])
def cancel_term(tid):
    uid, role = current_role()
    require_role(role, {"Member", "Support"})
    term = load_term(tid)
    check_term_member_owner(term, uid, role)
    if term["term_status"] not in ("ACTIVE", "PAST_DUE"):
        raise ApiError("ERR_TERM_NOT_CANCELLABLE", 409, "term is not cancellable")
    if term["months_paid"] >= term["commitment_months"]:
        # commitment fulfilled: the term completes rather than cancelling
        term["term_status"] = "COMPLETED"
        touch(term)
        return success(term_out(term), 200)
    months_remaining = term["commitment_months"] - term["months_paid"]
    if term["cancel_fee_policy"] == "REMAINING_MONTHS":
        raw = Decimal(term["monthly_fee_cents"]) * Decimal(months_remaining) * Decimal("0.50")
    else:  # PAID_MONTHS_FLOOR
        raw = Decimal(term["monthly_fee_cents"]) * Decimal(term["months_paid"]) * Decimal("0.25")
    fee = max(term["early_cancel_fee_floor_cents"], int(round_half_up(raw, 0)))
    term["cancel_fee_charged_cents"] = fee
    term["term_status"] = "CANCELLED_EARLY"
    term["open_pause_end_on"] = None
    tday = today()
    for d in STORE["devices"].values():
        if d["member_id"] == term["member_id"] and d["device_status"] in (
            "PROVISIONED",
            "ACTIVE",
            "SUSPECT_FAULT",
        ):
            if d["device_status"] == "ACTIVE":
                d["continuity_end_on"] = tday.isoformat()
            d["device_status"] = "RETIRED"
            touch(d)
    touch(term)
    member = load_member(term["member_id"])
    member_suspension_recompute(member)
    return success(term_out(term), 200)


@app.route("/terms/<tid>/upgrade", methods=["POST"])
def upgrade_term(tid):
    uid, role = current_role()
    require_role(role, {"Member"})
    term = load_term(tid)
    check_term_member_owner(term, uid, role)
    body = json_body()
    require_fields(body, ["expected_term_version"])
    if not is_int(body["expected_term_version"]):
        raise err_invalid("expected_term_version must be an integer")
    # OCC
    if body["expected_term_version"] != term["version"]:
        raise err_stale("expected_term_version does not match current term version")
    # state gates
    member = load_member(term["member_id"])
    if member["member_status"] == "SUSPENDED":
        raise err_suspended()
    if term["term_status"] not in ("ACTIVE", "PAUSED", "PAST_DUE"):
        raise ApiError("ERR_NO_ACTIVE_TERM", 409, "no open term")
    # eligibility
    anchor = parse_iso_date(term["last_upgrade_on"] or term["started_on"])
    months_elapsed = full_months_between(anchor, today())
    if months_elapsed < term["upgrade_eligibility_months"]:
        raise ApiError("ERR_UPGRADE_NOT_ELIGIBLE", 422, "upgrade not yet eligible")
    term["last_upgrade_on"] = today().isoformat()
    touch(term)
    ent = base_entity()
    ent.update(
        {
            "member_id": term["member_id"],
            "term_id": term["id"],
            "serial_number": "UPG-" + uuid.uuid4().hex[:12].upper(),
            "hardware_tier": "BAND_PRO",
            "device_status": "PROVISIONED",
            "activated_on": None,
            "continuity_start_on": None,
            "continuity_end_on": None,
            "diagnosis": None,
        }
    )
    STORE["devices"][ent["id"]] = ent
    out = term_out(term)
    out["upgrade_device"] = device_out(ent)
    return success(out, 200)


# ----------------------------------------------------------------------------
# Devices
# ----------------------------------------------------------------------------


@app.route("/devices", methods=["POST"])
def create_device():
    uid, role = current_role()
    require_role(role, {"PlatformAdmin"})
    body = json_body()
    require_fields(body, ["member_id", "term_id", "serial_number", "hardware_tier"])
    if not isinstance(body["member_id"], str):
        raise err_invalid("member_id must be a string")
    if not isinstance(body["term_id"], str):
        raise err_invalid("term_id must be a string")
    if not isinstance(body["serial_number"], str) or not body["serial_number"]:
        raise err_invalid("serial_number must be a non-empty string")
    if body["hardware_tier"] not in HARDWARE_TIERS:
        raise err_invalid("hardware_tier must be BAND_STD or BAND_PRO")
    member = STORE["members"].get(body["member_id"])
    if member is None:
        raise err_not_found("member not found")
    term = STORE["terms"].get(body["term_id"])
    if term is None:
        raise err_not_found("term not found")
    if term["member_id"] != body["member_id"]:
        raise err_invalid("term does not belong to member")
    for d in STORE["devices"].values():
        if d["serial_number"] == body["serial_number"]:
            raise ApiError("ERR_SERIAL_NUMBER_TAKEN", 409, "serial number already registered")
    ent = base_entity()
    ent.update(
        {
            "member_id": body["member_id"],
            "term_id": body["term_id"],
            "serial_number": body["serial_number"],
            "hardware_tier": body["hardware_tier"],
            "device_status": "PROVISIONED",
            "activated_on": None,
            "continuity_start_on": None,
            "continuity_end_on": None,
            "diagnosis": None,
        }
    )
    STORE["devices"][ent["id"]] = ent
    return success(device_out(ent), 201)


@app.route("/devices/<did>", methods=["GET"])
def get_device(did):
    uid, role = current_role()
    require_role(role, {"Member", "Support", "PlatformAdmin"})
    d = load_device(did)
    if role == "Member" and uid != d["member_id"]:
        raise err_not_owner("member id mismatch")
    return success(device_out(d), 200)


@app.route("/devices", methods=["GET"])
def list_devices():
    uid, role = current_role()
    require_role(role, {"Member", "Support", "PlatformAdmin"})
    items = list(STORE["devices"].values())
    member_id = request.args.get("member_id")
    term_id = request.args.get("term_id")
    if role == "Member":
        if member_id is not None and member_id != uid:
            raise err_not_owner("member id mismatch")
        if member_id is None:
            items = [d for d in items if d["member_id"] == uid]
    if member_id is not None:
        items = [d for d in items if d["member_id"] == member_id]
    if term_id is not None:
        items = [d for d in items if d["term_id"] == term_id]
    page, pag = paginate(items)
    return success([device_out(d) for d in page], 200, pag)


@app.route("/devices/<did>/activate", methods=["POST"])
def activate_device(did):
    uid, role = current_role()
    require_role(role, {"Member"})
    d = load_device(did)
    if uid != d["member_id"]:
        raise err_not_owner("member id mismatch")
    member = load_member(d["member_id"])
    # state preconditions
    if d["device_status"] != "PROVISIONED":
        raise ApiError("ERR_DEVICE_NOT_ACTIVE", 409, "device is not PROVISIONED")
    if member["member_status"] != "ACTIVE":
        raise err_suspended()
    tday = today()
    # replacement stitch path
    parent_req = None
    for r in STORE["replacement_requests"].values():
        if r["replacement_device_id"] == did:
            parent_req = r
            break
    if parent_req is not None:
        faulty = load_device(parent_req["device_id"])
        if faulty["device_status"] != "RETIRED":
            raise ApiError(
                "ERR_REPLACEMENT_DEVICE_NOT_RETIRED",
                409,
                "faulty device must be RETIRED before activating the replacement",
            )
        start = parse_iso_date(faulty["continuity_end_on"]) + relativedelta(days=1)
        d["continuity_start_on"] = start.isoformat()
    else:
        # continuity overlap check: no other device of the member may cover today
        for other in STORE["devices"].values():
            if other["id"] == did or other["member_id"] != d["member_id"]:
                continue
            cs = other["continuity_start_on"]
            if cs is None:
                continue
            cs_d = parse_iso_date(cs)
            ce = other["continuity_end_on"]
            covers = cs_d <= tday and (ce is None or parse_iso_date(ce) >= tday)
            if covers:
                raise ApiError(
                    "ERR_CONTINUITY_WINDOW_OVERLAP",
                    409,
                    "another device already covers today",
                )
        d["continuity_start_on"] = tday.isoformat()
    d["device_status"] = "ACTIVE"
    d["activated_on"] = tday.isoformat()
    d["continuity_end_on"] = None
    touch(d)
    return success(device_out(d), 200)


@app.route("/devices/<did>/ingest", methods=["POST"])
def ingest_metric(did):
    uid, role = current_role()
    require_role(role, {"Member"})
    d = load_device(did)
    if uid != d["member_id"]:
        raise err_not_owner("member id mismatch")
    body = json_body()
    require_fields(body, ["day_on", "avg_hr", "hrv_ms", "resting_hr", "sleep_minutes"])
    day = parse_iso_date(body["day_on"])
    if day is None:
        raise err_invalid("day_on is not a valid date")
    if not is_num(body["avg_hr"]):
        raise err_invalid("avg_hr must be a number")
    if not is_num(body["hrv_ms"]):
        raise err_invalid("hrv_ms must be a number")
    if not is_num(body["resting_hr"]):
        raise err_invalid("resting_hr must be a number")
    if not is_int(body["sleep_minutes"]) or body["sleep_minutes"] < 0:
        raise err_invalid("sleep_minutes must be a non-negative integer")
    if d["device_status"] != "ACTIVE":
        raise ApiError("ERR_DEVICE_NOT_ACTIVE", 409, "device is not ACTIVE")
    tday = today()
    if day > tday:
        raise err_invalid("day_on may not be in the future")
    if d["continuity_start_on"] is not None and day < parse_iso_date(d["continuity_start_on"]):
        raise err_invalid("day_on precedes the device continuity start")
    for x in STORE["metric_sets"].values():
        if x["member_id"] == d["member_id"] and x["day_on"] == day.isoformat():
            raise ApiError(
                "ERR_DUPLICATE_METRIC_DAY", 409, "metric set already exists for this day"
            )
    version = current_published_version()
    strain, recovery, sleep = compute_scores(
        body["avg_hr"], body["hrv_ms"], body["resting_hr"], body["sleep_minutes"], version
    )
    ent = base_entity()
    ent.update(
        {
            "member_id": d["member_id"],
            "day_on": day.isoformat(),
            "avg_hr": body["avg_hr"],
            "hrv_ms": body["hrv_ms"],
            "resting_hr": body["resting_hr"],
            "sleep_minutes": body["sleep_minutes"],
            "algorithm_version": version,
            "strain_score": strain,
            "recovery_score": recovery,
            "sleep_performance_pct": sleep,
            "interpretation_status": "CURRENT",
        }
    )
    STORE["metric_sets"][ent["id"]] = ent
    return success(metric_out(ent), 201)


@app.route("/devices/<did>/replacement-requests", methods=["POST"])
def open_replacement_request(did):
    uid, role = current_role()
    require_role(role, {"Member"})
    d = load_device(did)
    if uid != d["member_id"]:
        raise err_not_owner("member id mismatch")
    body = json_body()
    require_fields(body, ["reason"])
    if body["reason"] not in REPLACEMENT_REASONS:
        raise err_invalid("invalid reason")
    for r in STORE["replacement_requests"].values():
        if r["device_id"] == did and r["request_status"] == "OPEN":
            raise ApiError(
                "ERR_REPLACEMENT_ALREADY_OPEN", 422, "device already has an OPEN request"
            )
    if d["device_status"] != "ACTIVE":
        raise ApiError("ERR_DEVICE_NOT_ACTIVE", 409, "device is not ACTIVE")
    ent = base_entity()
    ent.update(
        {
            "device_id": did,
            "reason": body["reason"],
            "request_status": "OPEN",
            "diagnosis": None,
            "replacement_device_id": None,
        }
    )
    STORE["replacement_requests"][ent["id"]] = ent
    d["device_status"] = "SUSPECT_FAULT"
    touch(d)
    return success(replacement_out(ent), 201)


@app.route("/devices/<did>/replacement-requests", methods=["GET"])
def list_replacement_requests(did):
    uid, role = current_role()
    require_role(role, {"Member", "Support", "PlatformAdmin"})
    d = load_device(did)
    if role == "Member" and uid != d["member_id"]:
        raise err_not_owner("member id mismatch")
    items = [r for r in STORE["replacement_requests"].values() if r["device_id"] == did]
    page, pag = paginate(items)
    return success([replacement_out(r) for r in page], 200, pag)


# ----------------------------------------------------------------------------
# Replacement request decisions
# ----------------------------------------------------------------------------


@app.route("/replacement-requests/<rid>/decide", methods=["POST"])
def decide_replacement(rid):
    uid, role = current_role()
    require_role(role, {"Support"})
    req = load_replacement(rid)
    body = json_body()
    require_fields(body, ["decision"])
    decision = body["decision"]
    if decision not in ("APPROVE", "REJECT"):
        raise err_invalid("decision must be APPROVE or REJECT")
    diagnosis = body.get("diagnosis")
    if decision == "REJECT":
        if diagnosis is None:
            raise err_invalid("diagnosis is required for REJECT")
        if diagnosis not in REJECT_DIAGNOSES:
            raise err_invalid("diagnosis must be NO_FAULT or USER_DAMAGE")
    if req["request_status"] != "OPEN":
        raise err_state("request is not OPEN")
    faulty = load_device(req["device_id"])
    if faulty["device_status"] != "SUSPECT_FAULT":
        raise ApiError("ERR_DEVICE_NOT_FAULTY", 409, "device is not SUSPECT_FAULT")
    if decision == "APPROVE":
        term = load_term(faulty["term_id"])
        if term["term_status"] not in ("ACTIVE", "PAUSED", "PAST_DUE"):
            raise err_state("the device's term is no longer open")
        req["request_status"] = "APPROVED"
        req["diagnosis"] = "CONFIRMED_FAILURE"
        faulty["device_status"] = "RMA_INBOUND"
        touch(faulty)
        ent = base_entity()
        ent.update(
            {
                "member_id": faulty["member_id"],
                "term_id": faulty["term_id"],
                "serial_number": "RMA-" + uuid.uuid4().hex[:12].upper(),
                "hardware_tier": faulty["hardware_tier"],
                "device_status": "PROVISIONED",
                "activated_on": None,
                "continuity_start_on": None,
                "continuity_end_on": None,
                "diagnosis": None,
            }
        )
        STORE["devices"][ent["id"]] = ent
        req["replacement_device_id"] = ent["id"]
        touch(req)
    else:  # REJECT
        req["request_status"] = "REJECTED"
        req["diagnosis"] = diagnosis
        if diagnosis == "NO_FAULT":
            faulty["device_status"] = "ACTIVE"
            faulty["diagnosis"] = "NO_FAULT"
        else:
            faulty["diagnosis"] = "USER_DAMAGE"
        touch(faulty)
        touch(req)
    return success(replacement_out(req), 200)


@app.route("/replacement-requests/<rid>/receive-return", methods=["POST"])
def receive_return(rid):
    uid, role = current_role()
    require_role(role, {"Support"})
    req = load_replacement(rid)
    if req["request_status"] != "APPROVED":
        raise err_state("request is not APPROVED")
    faulty = load_device(req["device_id"])
    faulty["device_status"] = "RETIRED"
    faulty["continuity_end_on"] = today().isoformat()
    touch(faulty)
    req["request_status"] = "COMPLETED"
    touch(req)
    return success(replacement_out(req), 200)


# ----------------------------------------------------------------------------
# Algorithm releases
# ----------------------------------------------------------------------------


@app.route("/algorithm-releases", methods=["POST"])
def create_release():
    uid, role = current_role()
    require_role(role, {"PlatformAdmin"})
    body = json_body()
    require_fields(body, ["version", "release_notes"])
    if not is_int(body["version"]) or body["version"] < 1:
        raise err_invalid("version must be a positive integer")
    if not isinstance(body["release_notes"], str):
        raise err_invalid("release_notes must be a string")
    requires_ack = body.get("requires_member_ack", True)
    if not isinstance(requires_ack, bool):
        raise err_invalid("requires_member_ack must be a boolean")
    for r in STORE["releases"].values():
        if body["version"] <= r["version"]:
            raise err_invalid("version must be greater than any existing version")
    ent = base_entity()
    ent.update(
        {
            "version": body["version"],
            "requires_member_ack": requires_ack,
            "release_notes": body["release_notes"],
            "release_status": "DRAFT",
            "published_on": None,
            "entity_version": 1,
        }
    )
    STORE["releases"][ent["id"]] = ent
    return success(algo_release_out(ent), 201)


@app.route("/algorithm-releases/<rid>/publish", methods=["POST"])
def publish_release(rid):
    uid, role = current_role()
    require_role(role, {"PlatformAdmin"})
    rel = load_release(rid)
    if rel["release_status"] != "DRAFT":
        raise err_state("release is not DRAFT")
    for r in STORE["releases"].values():
        if r["id"] != rid and rel["version"] <= r["version"]:
            raise err_invalid("version must be greater than any existing version")
    rel["release_status"] = "PUBLISHED"
    rel["published_on"] = today().isoformat()
    rel["entity_version"] += 1
    rel["updated_at"] = iso_now()
    for r in STORE["releases"].values():
        if r["id"] != rid and r["release_status"] == "PUBLISHED":
            r["release_status"] = "SUPERSEDED"
            r["entity_version"] += 1
            r["updated_at"] = iso_now()
    # cascade: recompute older metric sets, chronological by day_on, tie created_at
    affected = [
        x
        for x in STORE["metric_sets"].values()
        if x["algorithm_version"] < rel["version"]
    ]
    affected.sort(key=lambda x: (x["day_on"], x["created_at"], x["id"]))
    changed_members = set()
    for x in affected:
        old_recovery = x["recovery_score"]
        x["interpretation_status"] = "STALE"
        strain, recovery, sleep = compute_scores(
            x["avg_hr"], x["hrv_ms"], x["resting_hr"], x["sleep_minutes"], rel["version"]
        )
        x["strain_score"] = strain
        x["recovery_score"] = recovery
        x["sleep_performance_pct"] = sleep
        x["algorithm_version"] = rel["version"]
        x["interpretation_status"] = "RECOMPUTED"
        touch(x)
        if recovery != old_recovery:
            changed_members.add(x["member_id"])
    if rel["requires_member_ack"]:
        for mid in changed_members:
            member = STORE["members"].get(mid)
            if member is not None and member["data_sharing_posture"] != "SUPPRESSED":
                member["data_sharing_posture"] = "SUPPRESSED"
                touch(member)
    return success(algo_release_out(rel), 200)


# ----------------------------------------------------------------------------
# Teams and memberships
# ----------------------------------------------------------------------------


@app.route("/teams", methods=["POST"])
def create_team():
    uid, role = current_role()
    require_role(role, {"Coach"})
    body = json_body()
    require_fields(body, ["name", "team_type", "coach_user_id"])
    if not isinstance(body["name"], str) or not body["name"]:
        raise err_invalid("name must be a non-empty string")
    if body["team_type"] not in TEAM_TYPES:
        raise err_invalid("team_type must be SPORTS or CORPORATE_WELLNESS")
    if not isinstance(body["coach_user_id"], str) or not body["coach_user_id"]:
        raise err_invalid("coach_user_id must be a non-empty string")
    if body["coach_user_id"] != uid:
        raise err_not_owner("coach_user_id must equal the caller's X-User-ID")
    ent = base_entity()
    ent.update(
        {
            "name": body["name"],
            "team_type": body["team_type"],
            "coach_user_id": body["coach_user_id"],
        }
    )
    STORE["teams"][ent["id"]] = ent
    return success(team_out(ent), 201)


@app.route("/teams/<tid>/memberships", methods=["POST"])
def add_team_membership(tid):
    uid, role = current_role()
    require_role(role, {"Coach"})
    team = load_team(tid)
    if team["coach_user_id"] != uid:
        raise err_not_owner("coach does not own this team")
    body = json_body()
    require_fields(body, ["member_id"])
    if not isinstance(body["member_id"], str):
        raise err_invalid("member_id must be a string")
    member = STORE["members"].get(body["member_id"])
    if member is None:
        raise err_not_found("member not found")
    for m in STORE["team_memberships"].values():
        if (
            m["team_id"] == tid
            and m["member_id"] == body["member_id"]
            and m["membership_status"] == "ACTIVE"
        ):
            raise ApiError(
                "ERR_DUPLICATE_MEMBERSHIP", 409, "member already has an ACTIVE membership"
            )
    ent = base_entity()
    ent.update(
        {
            "team_id": tid,
            "member_id": body["member_id"],
            "membership_status": "ACTIVE",
            "consent_scopes": [],
        }
    )
    STORE["team_memberships"][ent["id"]] = ent
    return success(membership_out(ent), 201)


@app.route("/teams/<tid>/dashboard", methods=["GET"])
def team_dashboard(tid):
    uid, role = current_role()
    require_role(role, {"Coach"})
    team = load_team(tid)
    if team["coach_user_id"] != uid:
        raise err_not_owner("coach does not own this team")
    tday = today()
    memberships = [
        m
        for m in STORE["team_memberships"].values()
        if m["team_id"] == tid and m["membership_status"] == "ACTIVE"
    ]
    memberships.sort(key=lambda m: (m["created_at"], m["id"]))
    rows = []
    for ms in memberships:
        member = STORE["members"].get(ms["member_id"])
        if member is None:
            continue
        lt = latest_term(member["id"])
        if lt is None or lt["term_status"] in ("CANCELLED_EARLY", "COMPLETED"):
            continue
        if member["data_sharing_posture"] == "SUPPRESSED":
            rows.append(
                {
                    "membership_id": ms["id"],
                    "member_id": member["id"],
                    "suppressed": True,
                    "strain_score": None,
                    "recovery_score": None,
                    "sleep_performance_pct": None,
                }
            )
            continue
        latest = latest_metric(member["id"])
        scope_map = {"STRAIN": "strain_score", "RECOVERY": "recovery_score", "SLEEP": "sleep_performance_pct"}
        row = {
            "membership_id": ms["id"],
            "member_id": member["id"],
            "suppressed": False,
            "strain_score": None,
            "recovery_score": None,
            "sleep_performance_pct": None,
        }
        for scope, field in scope_map.items():
            entry = None
            for e in ms["consent_scopes"]:
                if e["scope"] == scope:
                    entry = e
                    break
            if (
                entry is not None
                and entry["status"] == "GRANTED"
                and (entry.get("expires_on") is None or parse_iso_date(entry["expires_on"]) >= tday)
                and latest is not None
            ):
                row[field] = latest[field]
        rows.append(row)
    return success({"rows": rows}, 200)


@app.route("/team-memberships/<mid>", methods=["GET"])
def get_team_membership(mid):
    uid, role = current_role()
    require_role(role, {"Member", "Coach", "Support", "PlatformAdmin"})
    ms = load_membership(mid)
    if role == "Member" and uid != ms["member_id"]:
        raise err_not_owner("member id mismatch")
    if role == "Coach":
        team = STORE["teams"].get(ms["team_id"])
        if team is None or team["coach_user_id"] != uid:
            raise err_not_owner("coach does not own this team")
    return success(membership_out(ms), 200)


@app.route("/team-memberships", methods=["GET"])
def list_team_memberships():
    uid, role = current_role()
    require_role(role, {"Member", "Coach", "Support", "PlatformAdmin"})
    items = list(STORE["team_memberships"].values())
    team_id = request.args.get("team_id")
    member_id = request.args.get("member_id")
    if role == "Member":
        if member_id is not None and member_id != uid:
            raise err_not_owner("member id mismatch")
        items = [m for m in items if m["member_id"] == uid]
    if team_id is not None:
        items = [m for m in items if m["team_id"] == team_id]
    if member_id is not None:
        items = [m for m in items if m["member_id"] == member_id]
    page, pag = paginate(items)
    return success([membership_out(m) for m in page], 200, pag)


@app.route("/team-memberships/<mid>/consents", methods=["POST"])
def update_consent(mid):
    uid, role = current_role()
    require_role(role, {"Member"})
    ms = load_membership(mid)
    if uid != ms["member_id"]:
        raise err_not_owner("member id mismatch")
    body = json_body()
    require_fields(body, ["scope", "action", "expected_team_membership_version"])
    scope = body["scope"]
    action = body["action"]
    if scope not in CONSENT_SCOPES:
        raise err_invalid("scope must be STRAIN, RECOVERY, or SLEEP")
    if action not in CONSENT_ACTIONS:
        raise err_invalid("action must be GRANT or REVOKE")
    if not is_int(body["expected_team_membership_version"]):
        raise err_invalid("expected_team_membership_version must be an integer")
    expires_on = body.get("expires_on")
    if action == "GRANT" and expires_on is not None:
        if parse_iso_date(expires_on) is None:
            raise err_invalid("expires_on is not a valid date")
    # OCC
    if body["expected_team_membership_version"] != ms["version"]:
        raise err_stale("expected_team_membership_version does not match current version")
    # state
    if ms["membership_status"] != "ACTIVE":
        raise err_state("membership is not ACTIVE")
    member = load_member(ms["member_id"])
    if action == "GRANT" and member["member_status"] == "SUSPENDED":
        raise err_suspended()
    # suppression boundary
    if action == "GRANT" and member["data_sharing_posture"] == "SUPPRESSED":
        raise ApiError(
            "ERR_DATA_SHARING_SUPPRESSED",
            403,
            "data sharing is suppressed until the latest release is acknowledged",
        )
    # temporal window
    tday = today()
    if action == "GRANT" and expires_on is not None and parse_iso_date(expires_on) < tday:
        raise ApiError("ERR_GRANT_WINDOW_INVALID", 400, "expires_on is in the past")
    entry = None
    for e in ms["consent_scopes"]:
        if e["scope"] == scope:
            entry = e
            break
    if action == "GRANT":
        if entry is None:
            entry = {"scope": scope}
            ms["consent_scopes"].append(entry)
        entry["status"] = "GRANTED"
        entry["granted_on"] = tday.isoformat()
        entry["expires_on"] = expires_on
    else:  # REVOKE
        if entry is None or entry["status"] != "GRANTED":
            raise err_state("no GRANTED entry for this scope")
        entry["status"] = "REVOKED"
    touch(ms)
    return success(membership_out(ms), 200)


@app.route("/team-memberships/<mid>/remove", methods=["POST"])
def remove_team_membership(mid):
    uid, role = current_role()
    require_role(role, {"Coach", "Member"})
    ms = load_membership(mid)
    if role == "Member" and uid != ms["member_id"]:
        raise err_not_owner("member id mismatch")
    if role == "Coach":
        team = STORE["teams"].get(ms["team_id"])
        if team is None or team["coach_user_id"] != uid:
            raise err_not_owner("coach does not own this team")
    if ms["membership_status"] != "ACTIVE":
        raise err_state("membership is not ACTIVE")
    ms["membership_status"] = "REMOVED"
    for e in ms["consent_scopes"]:
        if e["status"] == "GRANTED":
            e["status"] = "REVOKED"
    touch(ms)
    return success(membership_out(ms), 200)


# ----------------------------------------------------------------------------
# Research studies
# ----------------------------------------------------------------------------


@app.route("/research-studies", methods=["POST"])
def create_study():
    uid, role = current_role()
    require_role(role, {"PlatformAdmin"})
    body = json_body()
    require_fields(
        body,
        [
            "code",
            "title",
            "min_paid_months",
            "enrollment_window_start_on",
            "enrollment_window_end_on",
        ],
    )
    if not isinstance(body["code"], str) or not body["code"]:
        raise err_invalid("code must be a non-empty string")
    if not isinstance(body["title"], str) or not body["title"]:
        raise err_invalid("title must be a non-empty string")
    if not is_int(body["min_paid_months"]) or body["min_paid_months"] < 0:
        raise err_invalid("min_paid_months must be a non-negative integer")
    if parse_iso_date(body["enrollment_window_start_on"]) is None:
        raise err_invalid("enrollment_window_start_on is not a valid date")
    if parse_iso_date(body["enrollment_window_end_on"]) is None:
        raise err_invalid("enrollment_window_end_on is not a valid date")
    for s in STORE["studies"].values():
        if s["code"] == body["code"]:
            raise err_invalid("study code must be unique")
    ent = base_entity()
    ent.update(
        {
            "code": body["code"],
            "title": body["title"],
            "min_paid_months": body["min_paid_months"],
            "enrollment_window_start_on": body["enrollment_window_start_on"],
            "enrollment_window_end_on": body["enrollment_window_end_on"],
        }
    )
    STORE["studies"][ent["id"]] = ent
    return success(study_out(ent), 201)


@app.route("/research-studies/<sid>", methods=["GET"])
def get_study(sid):
    uid, role = current_role()
    require_role(role, {"Member", "Support", "PlatformAdmin"})
    s = load_study(sid)
    return success(study_out(s), 200)


@app.route("/research-studies/<sid>/enroll", methods=["POST"])
def enroll_study(sid):
    uid, role = current_role()
    require_role(role, {"Member"})
    study = load_study(sid)
    body = json_body()
    require_fields(body, ["member_id"])
    if not isinstance(body["member_id"], str):
        raise err_invalid("member_id must be a string")
    member = STORE["members"].get(body["member_id"])
    if member is None:
        raise err_not_found("member not found")
    if uid != body["member_id"]:
        raise err_not_owner("member id mismatch")
    # state gates
    if member["member_status"] == "SUSPENDED":
        raise err_suspended()
    # temporal window
    if study_status(study) != "RECRUITING":
        raise ApiError("ERR_ENROLLMENT_WINDOW_CLOSED", 422, "study is not recruiting")
    # business constraints
    term = current_term(member["id"])
    if term is None:
        raise ApiError("ERR_NO_ACTIVE_TERM", 409, "no open term")
    if term["months_paid"] < study["min_paid_months"]:
        raise err_invalid("member has not paid enough months for this study")
    for e in STORE["enrollments"].values():
        if (
            e["study_id"] == sid
            and e["member_id"] == member["id"]
            and e["enrollment_status"] == "ENROLLED"
        ):
            raise ApiError("ERR_ALREADY_ENROLLED", 409, "member is already enrolled")
    seq = sum(1 for e in STORE["enrollments"].values() if e["study_id"] == sid) + 1
    ent = base_entity()
    ent.update(
        {
            "study_id": sid,
            "member_id": member["id"],
            "enrollment_status": "ENROLLED",
            "enrolled_on": today().isoformat(),
            "member_seq": seq,
        }
    )
    STORE["enrollments"][ent["id"]] = ent
    return success(enrollment_out(ent), 201)


@app.route("/research-studies/<sid>/enrollments", methods=["GET"])
def list_study_enrollments(sid):
    uid, role = current_role()
    require_role(role, {"Member", "Support", "PlatformAdmin"})
    study = load_study(sid)
    items = [e for e in STORE["enrollments"].values() if e["study_id"] == sid]
    if role == "Member":
        items = [e for e in items if e["member_id"] == uid]
    page, pag = paginate(items)
    return success([enrollment_out(e) for e in page], 200, pag)


@app.route("/research-studies/<sid>/contribution-dataset", methods=["GET"])
def contribution_dataset(sid):
    uid, role = current_role()
    require_role(role, {"PlatformAdmin"})
    study = load_study(sid)
    rows = []
    enrollments = [
        e
        for e in STORE["enrollments"].values()
        if e["study_id"] == sid and e["enrollment_status"] == "ENROLLED"
    ]
    for e in enrollments:
        sets = [
            x
            for x in STORE["metric_sets"].values()
            if x["member_id"] == e["member_id"] and x["day_on"] >= e["enrolled_on"]
        ]
        for x in sets:
            rows.append(
                {
                    "member_seq": e["member_seq"],
                    "day_on": x["day_on"],
                    "strain_score": x["strain_score"],
                    "recovery_score": x["recovery_score"],
                    "sleep_performance_pct": x["sleep_performance_pct"],
                }
            )
    rows.sort(key=lambda r: (r["member_seq"], r["day_on"]))
    return success({"rows": rows}, 200)


@app.route("/research-enrollments/<eid>/withdraw", methods=["POST"])
def withdraw_enrollment(eid):
    uid, role = current_role()
    require_role(role, {"Member"})
    e = load_enrollment(eid)
    if uid != e["member_id"]:
        raise err_not_owner("member id mismatch")
    if e["enrollment_status"] != "ENROLLED":
        raise err_state("enrollment is not ENROLLED")
    e["enrollment_status"] = "WITHDRAWN"
    touch(e)
    return success(enrollment_out(e), 200)


# ----------------------------------------------------------------------------
# Entry point
# ----------------------------------------------------------------------------

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", "10000")))
