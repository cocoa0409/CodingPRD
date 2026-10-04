import uuid
from datetime import datetime, timezone, date, time, timedelta
from functools import wraps

from flask import Flask, request, jsonify

app = Flask(__name__)

# =============================================================================
# In-memory store (fresh per process)
# =============================================================================
DB = {
    "talents": {},
    "agreements": {},
    "arenas": {},
    "anchors": {},
    "events": {},
    "bookings": {},
    "storylines": {},
    "chapters": {},
    "partners": {},
    "territory_rights": {},
    "distribution_windows": {},
    "merch_sales": {},
    "statements": {},
    "medical_cases": {},
    "evaluations": {},
    "clearances": {},
    "visa_cases": {},
    "callups": {},
}

CLOCK = {"current": datetime(2026, 9, 1, 0, 0, 0, tzinfo=timezone.utc)}

ROLES = {
    "ContractAdmin", "TourPlanner", "TalentRelations", "StorylineEditor",
    "DistributionManager", "MerchOps", "Medic", "LogisticsCoordinator",
}
ALL_ROLES = sorted(ROLES)


# =============================================================================
# Errors
# =============================================================================
class ApiError(Exception):
    def __init__(self, error_id, message, http_status):
        super().__init__(message)
        self.error_id = error_id
        self.message = message
        self.http_status = http_status


def err_unauthenticated(msg="Missing or malformed X-User-Role / X-User-ID headers"):
    return ApiError("ERR_UNAUTHENTICATED", msg, 401)


def err_forbidden(msg="Role not permitted for the endpoint"):
    return ApiError("ERR_FORBIDDEN", msg, 403)


def err_not_found(msg="Resource not found"):
    return ApiError("ERR_NOT_FOUND", msg, 404)


def err_ref_not_found(msg="Referenced resource not found"):
    return ApiError("ERR_REFERENCE_NOT_FOUND", msg, 404)


def err_invalid_request(msg="Invalid request"):
    return ApiError("ERR_INVALID_REQUEST", msg, 400)


def err_invalid_state(msg="Transition not permitted from current state"):
    return ApiError("ERR_INVALID_STATE", msg, 409)


def err_stale(msg="Stale version"):
    return ApiError("ERR_STALE_VERSION", msg, 412)


def err_event_not_mutable(msg="Event not in a state permitting this operation"):
    return ApiError("ERR_EVENT_NOT_MUTABLE", msg, 409)


def biz(error_id, msg):
    return ApiError(error_id, msg, 422)


# =============================================================================
# Envelope helpers
# =============================================================================
def _wall_ts():
    now = datetime.now(timezone.utc)
    ms = now.microsecond // 1000
    return now.strftime("%Y-%m-%dT%H:%M:%S.") + f"{ms:03d}Z"


def envelope(data, response_type="object", status=200, pagination=None):
    meta = {
        "api_request_id": "req_" + uuid.uuid4().hex[:20],
        "api_request_timestamp": _wall_ts(),
    }
    if pagination is not None:
        meta.update(pagination)
    body = {"meta": meta, "response_type": response_type, "data": data}
    return jsonify(body), status


@app.errorhandler(ApiError)
def handle_api_error(e):
    meta = {
        "api_request_id": "req_" + uuid.uuid4().hex[:20],
        "api_request_timestamp": _wall_ts(),
    }
    body = {
        "meta": meta,
        "response_type": "error",
        "data": {"error_id": e.error_id, "message": e.message},
    }
    return jsonify(body), e.http_status


@app.errorhandler(404)
def handle_404(e):
    return handle_api_error(err_not_found("Resource not found"))


@app.errorhandler(405)
def handle_405(e):
    return handle_api_error(err_not_found("Resource not found"))


@app.errorhandler(Exception)
def handle_exc(e):
    if isinstance(e, ApiError):
        return handle_api_error(e)
    return handle_api_error(err_invalid_request(str(e)))


# =============================================================================
# Auth + role guard
# =============================================================================
def role_required(allowed):
    def decorator(fn):
        @wraps(fn)
        def wrapper(*args, **kwargs):
            uid = request.headers.get("X-User-ID")
            role = request.headers.get("X-User-Role")
            if not uid or not isinstance(uid, str) or not uid.strip():
                raise err_unauthenticated()
            if not role or role not in ROLES:
                raise err_unauthenticated()
            if role not in allowed:
                raise err_forbidden()
            request.user_id = uid
            request.user_role = role
            return fn(*args, **kwargs)
        return wrapper
    return decorator


# =============================================================================
# Parsing / validation helpers
# =============================================================================
def get_body():
    if not request.data:
        return {}
    try:
        body = request.get_json(force=True, silent=False)
    except Exception:
        raise err_invalid_request("Malformed JSON body")
    if body is None:
        return {}
    if not isinstance(body, dict):
        raise err_invalid_request("Request body must be a JSON object")
    return body


def parse_date(s, field):
    if not isinstance(s, str):
        raise err_invalid_request(f"{field} must be a YYYY-MM-DD string")
    try:
        return datetime.strptime(s, "%Y-%m-%d").date()
    except (ValueError, TypeError):
        raise err_invalid_request(f"{field} must be a valid YYYY-MM-DD date")


def parse_time_hm(s, field):
    if not isinstance(s, str):
        raise err_invalid_request(f"{field} must be an HH:MM string")
    try:
        parts = s.split(":")
        if len(parts) != 2:
            raise ValueError
        h, m = int(parts[0]), int(parts[1])
        if not (0 <= h <= 23 and 0 <= m <= 59):
            raise ValueError
        return h * 60 + m
    except (ValueError, TypeError):
        raise err_invalid_request(f"{field} must be a valid HH:MM time")


def parse_dt(s, field):
    if not isinstance(s, str):
        raise err_invalid_request(f"{field} must be an ISO8601 UTC datetime")
    try:
        v = s
        if v.endswith("Z"):
            v = v[:-1] + "+00:00"
        dt = datetime.fromisoformat(v)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt.astimezone(timezone.utc)
    except (ValueError, TypeError):
        raise err_invalid_request(f"{field} must be a valid ISO8601 datetime")


def require_fields(body, fields):
    for f in fields:
        if f not in body or body[f] is None:
            raise err_invalid_request(f"Missing required field: {f}")


def req_int(body, field, minimum=None, maximum=None):
    v = body.get(field)
    if isinstance(v, bool) or not isinstance(v, int):
        raise err_invalid_request(f"{field} must be an integer")
    if minimum is not None and v < minimum:
        raise err_invalid_request(f"{field} must be >= {minimum}")
    if maximum is not None and v > maximum:
        raise err_invalid_request(f"{field} must be <= {maximum}")
    return v


def opt_enum(body, field, allowed, required=True):
    v = body.get(field)
    if v is None:
        if required:
            raise err_invalid_request(f"Missing required field: {field}")
        return None
    if v not in allowed:
        raise err_invalid_request(f"{field} must be one of {sorted(allowed)}")
    return v


def new_id():
    return str(uuid.uuid4())


def now_wall_iso():
    return _wall_ts()


def clock_now():
    return CLOCK["current"]


def clock_date():
    return CLOCK["current"].date()


def touch(res):
    res["updated_at"] = now_wall_iso()
    res["version"] = res.get("version", 1) + 1


def create_resource(table, fields):
    rid = new_id()
    ts = now_wall_iso()
    rec = {"id": rid, "created_at": ts, "updated_at": ts, "version": 1}
    rec.update(fields)
    DB[table][rid] = rec
    return rec


def get_or_404(table, rid):
    rec = DB[table].get(rid)
    if rec is None:
        raise err_not_found(f"Resource {rid} not found")
    return rec


def body_fk_or_404(table, rid, field):
    if not isinstance(rid, str):
        raise err_invalid_request(f"{field} must be a string id")
    rec = DB[table].get(rid)
    if rec is None:
        raise err_ref_not_found(f"{field} does not resolve to an existing resource")
    return rec


def paginate(items):
    try:
        limit = request.args.get("limit", "10")
        offset = request.args.get("offset", "0")
        limit = int(limit)
        offset = int(offset)
    except (ValueError, TypeError):
        raise err_invalid_request("limit/offset must be integers")
    if limit < 1 or limit > 100:
        raise err_invalid_request("limit must be between 1 and 100")
    if offset < 0:
        raise err_invalid_request("offset must be >= 0")
    total = len(items)
    page = items[offset:offset + limit]
    pagination = {
        "limit": limit,
        "offset": offset,
        "total_count": total,
        "has_more": (offset + limit) < total,
    }
    return page, pagination


def list_response(items):
    items = sorted(items, key=lambda r: (r.get("created_at", ""), r.get("id", "")))
    page, pagination = paginate(items)
    return envelope(page, "array", 200, pagination)


# =============================================================================
# Derived computations
# =============================================================================
def recompute_likeness(talent_id):
    talent = DB["talents"].get(talent_id)
    if talent is None:
        return
    new_val = any(
        a["talent_id"] == talent_id and a["status"] == "ACTIVE" and a.get("likeness_rights_granted")
        for a in DB["agreements"].values()
    )
    if talent.get("likeness_granted") != new_val:
        talent["likeness_granted"] = new_val
        touch(talent)


def derive_booking_mode(talent):
    if talent["availability_status"] == "SUSPENDED":
        return "UNBOOKABLE"
    if talent["availability_status"] == "INJURED":
        return "UNBOOKABLE"
    if any(mc["talent_id"] == talent["id"] and mc["status"] == "OPEN"
           for mc in DB["medical_cases"].values()):
        return "UNBOOKABLE"
    if talent["wellness_score"] >= 70.0:
        return "BOOKABLE"
    if talent["wellness_score"] >= 40.0:
        return "LIMITED"
    return "UNBOOKABLE"


def rederive_booking_mode(talent):
    new_val = derive_booking_mode(talent)
    if talent.get("booking_mode") != new_val:
        talent["booking_mode"] = new_val
        touch(talent)


def clamp_wellness(v):
    return max(0.0, min(100.0, round(v + 1e-9, 2)))


def apply_wellness(talent, delta):
    talent["wellness_score"] = clamp_wellness(talent["wellness_score"] + delta)
    touch(talent)
    rederive_booking_mode(talent)


def storyline_booked_count(storyline_id):
    return sum(
        1 for b in DB["bookings"].values()
        if b.get("storyline_id") == storyline_id and b["status"] == "BOOKED"
    )


def shelf_storyline(storyline):
    """ACTIVE -> SHELVED; flip remaining PLANNED chapters to MISSED (no increment)."""
    if storyline["status"] != "ACTIVE":
        return
    storyline["status"] = "SHELVED"
    touch(storyline)
    for ch in DB["chapters"].values():
        if ch["storyline_id"] == storyline["id"] and ch["status"] == "PLANNED":
            ch["status"] = "MISSED"
            touch(ch)


def gap_increment(storyline_id):
    storyline = DB["storylines"].get(storyline_id)
    if storyline is None:
        return
    storyline["gap_count"] = storyline.get("gap_count", 0) + 1
    touch(storyline)
    if storyline["status"] == "ACTIVE" and storyline["gap_count"] >= 3:
        shelf_storyline(storyline)


def scratch_booking(booking):
    if booking["status"] != "BOOKED":
        return
    booking["status"] = "SCRATCHED"
    touch(booking)


def recompute_chapter_indexes(storyline_id):
    chapters = [c for c in DB["chapters"].values() if c["storyline_id"] == storyline_id]

    def key(ch):
        ev = DB["events"].get(ch["event_id"])
        ev_date = ev["event_date"] if ev else ""
        ev_created = ev["created_at"] if ev else ""
        return (ev_date, ev_created, ch["created_at"], ch["id"])

    chapters.sort(key=key)
    for i, ch in enumerate(chapters, start=1):
        if ch.get("chapter_index") != i:
            ch["chapter_index"] = i
            touch(ch)


# =============================================================================
# Clock endpoint + sweeps
# =============================================================================
@app.route("/touring/_clock/set_current_utc", methods=["POST"])
@role_required(["ContractAdmin"])
def set_clock():
    body = get_body()
    require_fields(body, ["to_iso8601"])
    new_dt = parse_dt(body["to_iso8601"], "to_iso8601")
    old_dt = clock_now()
    CLOCK["current"] = new_dt

    # Weekly decay: each Monday 00:00Z boundary crossed in (old, new]
    def monday_boundaries(start, end):
        out = []
        d = start.date()
        d = d - timedelta(days=d.weekday())  # Monday of start's week
        first = datetime.combine(d, time(0, 0), tzinfo=timezone.utc)
        if first <= start:
            first += timedelta(days=7)
        cur = first
        while cur <= end:
            out.append(cur)
            cur += timedelta(days=7)
        return out

    crossings = monday_boundaries(old_dt, new_dt)
    if crossings:
        for talent in DB["talents"].values():
            if talent.get("roster_tier") == "MAIN_ROSTER":
                talent["wellness_score"] = clamp_wellness(
                    talent["wellness_score"] - 1.0 * len(crossings))
                touch(talent)
                rederive_booking_mode(talent)

    # Agreement expiry sweep
    new_date = new_dt.date()
    for ag in DB["agreements"].values():
        if ag["status"] == "ACTIVE":
            try:
                end = datetime.strptime(ag["end_date"], "%Y-%m-%d").date()
            except Exception:
                continue
            if new_date >= end:
                ag["status"] = "EXPIRED"
                touch(ag)
                recompute_likeness(ag["talent_id"])

    return envelope({"current_utc": _fmt_instant(new_dt)}, "object", 200)


def _fmt_instant(dt):
    dt = dt.astimezone(timezone.utc)
    if dt.microsecond:
        s = dt.strftime("%Y-%m-%dT%H:%M:%S.%f")
        return s.rstrip("0").rstrip(".") + "Z"
    return dt.strftime("%Y-%m-%dT%H:%M:%SZ")


# =============================================================================
# Talents
# =============================================================================
@app.route("/touring/talents", methods=["POST"])
@role_required(["TalentRelations"])
def create_talent():
    body = get_body()
    require_fields(body, ["ring_name", "legal_name", "contractor_status"])
    if body["contractor_status"] != "INDEPENDENT_CONTRACTOR":
        raise err_invalid_request("contractor_status must be INDEPENDENT_CONTRACTOR")
    if not isinstance(body["ring_name"], str) or not isinstance(body["legal_name"], str):
        raise err_invalid_request("ring_name and legal_name must be strings")
    rec = create_resource("talents", {
        "ring_name": body["ring_name"],
        "legal_name": body["legal_name"],
        "contractor_status": "INDEPENDENT_CONTRACTOR",
        "roster_tier": "DEVELOPMENTAL",
        "availability_status": "ACTIVE",
        "wellness_score": 0.0,
        "booking_mode": "UNBOOKABLE",
        "likeness_granted": False,
    })
    return envelope(rec, "object", 201)


@app.route("/touring/talents", methods=["GET"])
@role_required(ALL_ROLES)
def list_talents():
    items = list(DB["talents"].values())
    for f in ("roster_tier", "availability_status", "booking_mode"):
        v = request.args.get(f)
        if v is not None:
            items = [t for t in items if t.get(f) == v]
    return list_response(items)


@app.route("/touring/talents/<tid>", methods=["GET"])
@role_required(ALL_ROLES)
def get_talent(tid):
    return envelope(get_or_404("talents", tid), "object", 200)


@app.route("/touring/talents/<tid>/suspend", methods=["POST"])
@role_required(["TalentRelations"])
def suspend_talent(tid):
    talent = get_or_404("talents", tid)
    if talent["availability_status"] == "SUSPENDED":
        raise err_invalid_state("Talent already SUSPENDED")
    talent["availability_status"] = "SUSPENDED"
    touch(talent)
    rederive_booking_mode(talent)
    return envelope(talent, "object", 200)


@app.route("/touring/talents/<tid>/reinstate", methods=["POST"])
@role_required(["TalentRelations"])
def reinstate_talent(tid):
    talent = get_or_404("talents", tid)
    if talent["availability_status"] != "SUSPENDED":
        raise err_invalid_state("Talent is not SUSPENDED")
    has_open_case = any(
        mc["talent_id"] == tid and mc["status"] == "OPEN"
        for mc in DB["medical_cases"].values()
    )
    talent["availability_status"] = "INJURED" if has_open_case else "ACTIVE"
    touch(talent)
    rederive_booking_mode(talent)
    return envelope(talent, "object", 200)


@app.route("/touring/talents/<tid>/call-up", methods=["POST"])
@role_required(["TalentRelations"])
def call_up(tid):
    talent = get_or_404("talents", tid)
    body = get_body()
    require_fields(body, ["decision"])
    decision = body["decision"]
    if decision not in ("PROMOTE", "DEFER"):
        raise err_invalid_request("decision must be PROMOTE or DEFER")

    now = clock_now()
    window_start = (now - timedelta(days=90)).date()
    today = now.date()
    fulfilled = 0
    no_shows = 0
    for b in DB["bookings"].values():
        if b["talent_id"] != tid:
            continue
        ev = DB["events"].get(b["event_id"])
        if ev is None:
            continue
        try:
            ev_date = datetime.strptime(ev["event_date"], "%Y-%m-%d").date()
        except Exception:
            continue
        if not (window_start <= ev_date <= today):
            continue
        if b["status"] == "FULFILLED" and ev["event_type"] == "HOUSE_SHOW":
            fulfilled += 1
        elif b["status"] == "NO_SHOW":
            no_shows += 1
    import math
    wellness_term = int(math.floor(talent["wellness_score"] * 0.5 + 0.5))
    score = fulfilled * 4 - no_shows * 10 + wellness_term
    score = max(0, min(100, score))

    if decision == "PROMOTE":
        has_open = any(mc["talent_id"] == tid and mc["status"] == "OPEN"
                       for mc in DB["medical_cases"].values())
        if score < 60 or has_open:
            raise biz("ERR_READINESS_THRESHOLD_UNMET",
                      "PROMOTE requires readiness_score >= 60 and no OPEN medical case")

    rec = create_resource("callups", {
        "talent_id": tid,
        "readiness_score": score,
        "decision": decision,
        "decided_by": request.user_id,
    })
    if decision == "PROMOTE":
        talent["roster_tier"] = "MAIN_ROSTER"
        touch(talent)
        rederive_booking_mode(talent)
    return envelope(rec, "object", 201)


@app.route("/touring/talents/<tid>/call-up-decisions", methods=["GET"])
@role_required(["TalentRelations"])
def list_callups(tid):
    get_or_404("talents", tid)
    items = [c for c in DB["callups"].values() if c["talent_id"] == tid]
    return list_response(items)


@app.route("/touring/talents/<tid>/appearance-compliance", methods=["GET"])
@role_required(["TalentRelations", "ContractAdmin"])
def appearance_compliance(tid):
    get_or_404("talents", tid)
    today = clock_date()
    q = (today.month - 1) // 3
    q_start = date(today.year, q * 3 + 1, 1)
    if q == 3:
        q_end_excl = date(today.year + 1, 1, 1)
    else:
        q_end_excl = date(today.year, q * 3 + 4, 1)
    q_last = q_end_excl - timedelta(days=1)
    quarter_label = f"{today.year}-Q{q + 1}"

    # Agreement ACTIVE on last day of quarter
    floor_val = 0
    for ag in DB["agreements"].values():
        if ag["talent_id"] != tid or ag["status"] != "ACTIVE":
            continue
        try:
            s = datetime.strptime(ag["start_date"], "%Y-%m-%d").date()
            e = datetime.strptime(ag["end_date"], "%Y-%m-%d").date()
        except Exception:
            continue
        if s <= q_last < e:
            floor_val = ag.get("min_appearances_per_quarter", 0)
            break

    committed = 0
    projected = 0
    for b in DB["bookings"].values():
        if b["talent_id"] != tid:
            continue
        ev = DB["events"].get(b["event_id"])
        if ev is None:
            continue
        try:
            ev_date = datetime.strptime(ev["event_date"], "%Y-%m-%d").date()
        except Exception:
            continue
        if not (q_start <= ev_date < q_end_excl):
            continue
        if b["status"] == "FULFILLED":
            committed += 1
        elif b["status"] == "BOOKED" and ev["status"] in ("SCHEDULED", "LOCKED") and ev_date > today:
            projected += 1

    shortfall = max(0, floor_val - committed - projected)
    return envelope({
        "quarter": quarter_label,
        "committed": committed,
        "projected": projected,
        "shortfall": shortfall,
    }, "object", 200)


@app.route("/touring/talents/<tid>/medical-cases", methods=["GET"])
@role_required(["Medic", "TalentRelations"])
def talent_medical_cases(tid):
    get_or_404("talents", tid)
    items = [m for m in DB["medical_cases"].values() if m["talent_id"] == tid]
    return list_response(items)


@app.route("/touring/talents/<tid>/visa-cases", methods=["GET"])
@role_required(["LogisticsCoordinator", "TalentRelations"])
def talent_visa_cases(tid):
    get_or_404("talents", tid)
    items = [v for v in DB["visa_cases"].values() if v["talent_id"] == tid]
    return list_response(items)


@app.route("/touring/talents/<tid>/agreements", methods=["GET"])
@role_required(["ContractAdmin", "TalentRelations"])
def talent_agreements(tid):
    get_or_404("talents", tid)
    items = [a for a in DB["agreements"].values() if a["talent_id"] == tid]
    return list_response(items)


# =============================================================================
# Agreements
# =============================================================================
def _windows_overlap(s1, e1, s2, e2):
    return s1 < e2 and s2 < e1


def _check_agreement_overlap(talent_id, start, end, exclude_id=None, include_draft=True):
    for ag in DB["agreements"].values():
        if ag["talent_id"] != talent_id:
            continue
        if exclude_id and ag["id"] == exclude_id:
            continue
        if ag["status"] in ("EXPIRED", "TERMINATED"):
            continue
        if not include_draft and ag["status"] == "DRAFT":
            continue
        try:
            s2 = datetime.strptime(ag["start_date"], "%Y-%m-%d").date()
            e2 = datetime.strptime(ag["end_date"], "%Y-%m-%d").date()
        except Exception:
            continue
        if _windows_overlap(start, end, s2, e2):
            raise biz("ERR_AGREEMENT_OVERLAP",
                      "Agreement window overlaps another agreement for this talent")


@app.route("/touring/agreements", methods=["POST"])
@role_required(["ContractAdmin"])
def create_agreement():
    body = get_body()
    require_fields(body, ["talent_id", "start_date", "end_date",
                          "downside_guarantee_cents", "royalty_rate_bp",
                          "likeness_rights_granted", "min_appearances_per_quarter"])
    talent = body_fk_or_404("talents", body["talent_id"], "talent_id")
    start = parse_date(body["start_date"], "start_date")
    end = parse_date(body["end_date"], "end_date")

    # Domain-specific business rule (agreement overlap) precedes the generic
    # shape checks per the PRD §2.7 validation cascade ordering.
    _check_agreement_overlap(talent["id"], start, end)

    if end <= start:
        raise err_invalid_request("end_date must be after start_date")
    downside = req_int(body, "downside_guarantee_cents", minimum=0)
    rate = req_int(body, "royalty_rate_bp", minimum=0, maximum=5000)
    if not isinstance(body["likeness_rights_granted"], bool):
        raise err_invalid_request("likeness_rights_granted must be a boolean")
    min_app = req_int(body, "min_appearances_per_quarter", minimum=0)

    rec = create_resource("agreements", {
        "talent_id": talent["id"],
        "start_date": body["start_date"],
        "end_date": body["end_date"],
        "downside_guarantee_cents": downside,
        "royalty_rate_bp": rate,
        "likeness_rights_granted": body["likeness_rights_granted"],
        "min_appearances_per_quarter": min_app,
        "status": "DRAFT",
    })
    return envelope(rec, "object", 201)


@app.route("/touring/agreements", methods=["GET"])
@role_required(["ContractAdmin", "TalentRelations"])
def list_agreements():
    items = list(DB["agreements"].values())
    tv = request.args.get("talent_id")
    if tv is not None:
        items = [a for a in items if a["talent_id"] == tv]
    sv = request.args.get("status")
    if sv is not None:
        items = [a for a in items if a["status"] == sv]
    return list_response(items)


@app.route("/touring/agreements/<aid>", methods=["GET"])
@role_required(["ContractAdmin", "TalentRelations"])
def get_agreement(aid):
    return envelope(get_or_404("agreements", aid), "object", 200)


@app.route("/touring/agreements/<aid>", methods=["PATCH"])
@role_required(["ContractAdmin"])
def patch_agreement(aid):
    ag = get_or_404("agreements", aid)
    body = get_body()
    if ag["status"] != "DRAFT":
        raise err_invalid_state("Only DRAFT agreements may be edited")

    new_start_s = body.get("start_date", ag["start_date"])
    new_end_s = body.get("end_date", ag["end_date"])
    new_start = parse_date(new_start_s, "start_date")
    new_end = parse_date(new_end_s, "end_date")
    if new_end <= new_start:
        raise err_invalid_request("end_date must be after start_date")

    updates = {"start_date": new_start_s, "end_date": new_end_s}
    if "downside_guarantee_cents" in body:
        updates["downside_guarantee_cents"] = req_int(body, "downside_guarantee_cents", minimum=0)
    if "royalty_rate_bp" in body:
        updates["royalty_rate_bp"] = req_int(body, "royalty_rate_bp", minimum=0, maximum=5000)
    if "likeness_rights_granted" in body:
        if not isinstance(body["likeness_rights_granted"], bool):
            raise err_invalid_request("likeness_rights_granted must be a boolean")
        updates["likeness_rights_granted"] = body["likeness_rights_granted"]
    if "min_appearances_per_quarter" in body:
        updates["min_appearances_per_quarter"] = req_int(body, "min_appearances_per_quarter", minimum=0)

    _check_agreement_overlap(ag["talent_id"], new_start, new_end, exclude_id=aid)

    ag.update(updates)
    touch(ag)
    return envelope(ag, "object", 200)


@app.route("/touring/agreements/<aid>/activate", methods=["POST"])
@role_required(["ContractAdmin"])
def activate_agreement(aid):
    ag = get_or_404("agreements", aid)
    if ag["status"] != "DRAFT":
        raise err_invalid_state("Agreement is not DRAFT")
    body = get_body()
    if "expected_agreement_version" in body and body["expected_agreement_version"] is not None:
        ev = body["expected_agreement_version"]
        if isinstance(ev, bool) or not isinstance(ev, int):
            raise err_invalid_request("expected_agreement_version must be an integer")
        if ev != ag["version"]:
            raise err_stale("Agreement version has advanced; re-read before activating")
    start = datetime.strptime(ag["start_date"], "%Y-%m-%d").date()
    end = datetime.strptime(ag["end_date"], "%Y-%m-%d").date()
    _check_agreement_overlap(ag["talent_id"], start, end, exclude_id=aid)
    ag["status"] = "ACTIVE"
    touch(ag)
    recompute_likeness(ag["talent_id"])
    return envelope(ag, "object", 200)


@app.route("/touring/agreements/<aid>/terminate", methods=["POST"])
@role_required(["ContractAdmin"])
def terminate_agreement(aid):
    ag = get_or_404("agreements", aid)
    if ag["status"] != "ACTIVE":
        raise err_invalid_state("Agreement is not ACTIVE")
    ag["status"] = "TERMINATED"
    touch(ag)
    recompute_likeness(ag["talent_id"])

    today = clock_date()
    affected_storylines = set()
    for b in DB["bookings"].values():
        if b["talent_id"] != ag["talent_id"] or b["status"] != "BOOKED":
            continue
        ev = DB["events"].get(b["event_id"])
        if ev is None or ev["status"] != "SCHEDULED":
            continue
        try:
            ev_date = datetime.strptime(ev["event_date"], "%Y-%m-%d").date()
        except Exception:
            continue
        if ev_date >= today:
            scratch_booking(b)
            if b.get("storyline_id"):
                affected_storylines.add(b["storyline_id"])

    for sid in affected_storylines:
        sl = DB["storylines"].get(sid)
        if sl is not None and sl["status"] == "ACTIVE" and storyline_booked_count(sid) == 0:
            sl["status"] = "CONCLUDED"
            touch(sl)

    return envelope(ag, "object", 200)


# =============================================================================
# Arenas & anchors
# =============================================================================
@app.route("/touring/arenas", methods=["POST"])
@role_required(["TourPlanner"])
def create_arena():
    body = get_body()
    require_fields(body, ["name", "city", "country_code", "capacity", "merch_booths", "timezone"])
    capacity = req_int(body, "capacity", minimum=1)
    booths = req_int(body, "merch_booths", minimum=0)
    for f in ("name", "city", "country_code", "timezone"):
        if not isinstance(body[f], str):
            raise err_invalid_request(f"{f} must be a string")
    rec = create_resource("arenas", {
        "name": body["name"],
        "city": body["city"],
        "country_code": body["country_code"],
        "capacity": capacity,
        "merch_booths": booths,
        "timezone": body["timezone"],
    })
    return envelope(rec, "object", 201)


@app.route("/touring/arenas/<aid>", methods=["GET"])
@role_required(["TourPlanner", "LogisticsCoordinator", "MerchOps"])
def get_arena(aid):
    return envelope(get_or_404("arenas", aid), "object", 200)


@app.route("/touring/broadcast-anchors", methods=["POST"])
@role_required(["TourPlanner"])
def create_anchor():
    body = get_body()
    require_fields(body, ["name", "weekly_day_of_week", "territory_code", "must_have_event_each_week"])
    dow = req_int(body, "weekly_day_of_week", minimum=1, maximum=7)
    if not isinstance(body["name"], str) or not isinstance(body["territory_code"], str):
        raise err_invalid_request("name and territory_code must be strings")
    if not isinstance(body["must_have_event_each_week"], bool):
        raise err_invalid_request("must_have_event_each_week must be a boolean")
    rec = create_resource("anchors", {
        "name": body["name"],
        "weekly_day_of_week": dow,
        "territory_code": body["territory_code"],
        "must_have_event_each_week": body["must_have_event_each_week"],
    })
    return envelope(rec, "object", 201)


@app.route("/touring/broadcast-anchors/<aid>", methods=["GET"])
@role_required(["TourPlanner"])
def get_anchor(aid):
    return envelope(get_or_404("anchors", aid), "object", 200)


# =============================================================================
# Events
# =============================================================================
EVENT_ROLES_READ = ["TourPlanner", "StorylineEditor", "MerchOps",
                    "DistributionManager", "LogisticsCoordinator", "TalentRelations"]


@app.route("/touring/events", methods=["POST"])
@role_required(["TourPlanner"])
def create_event():
    body = get_body()
    require_fields(body, ["name", "event_type", "arena_id", "event_date",
                          "start_time", "end_time", "tour_country_code",
                          "roster_min_main", "roster_min_total"])
    event_type = body["event_type"]
    if event_type not in ("TELEVISION", "PREMIUM", "HOUSE_SHOW"):
        raise err_invalid_request("event_type must be TELEVISION, PREMIUM or HOUSE_SHOW")
    arena = body_fk_or_404("arenas", body["arena_id"], "arena_id")

    anchor_id = body.get("anchor_id")
    anchor = None
    if anchor_id is not None:
        anchor = body_fk_or_404("anchors", anchor_id, "anchor_id")

    if event_type == "TELEVISION":
        if anchor is None:
            raise biz("ERR_ANCHOR_DATE_MISMATCH", "TELEVISION event requires an anchor")
        ev_date = parse_date(body["event_date"], "event_date")
        if (ev_date.weekday() + 1) != anchor["weekly_day_of_week"]:
            raise biz("ERR_ANCHOR_DATE_MISMATCH",
                      "TELEVISION event date does not fall on the anchor's weekly day")
    else:
        ev_date = parse_date(body["event_date"], "event_date")

    start_min = parse_time_hm(body["start_time"], "start_time")
    end_min = parse_time_hm(body["end_time"], "end_time")
    if end_min <= start_min:
        raise err_invalid_request("end_time must be later than start_time")

    rmin = req_int(body, "roster_min_main", minimum=0)
    rtot = req_int(body, "roster_min_total", minimum=0)
    if rtot < rmin:
        raise err_invalid_request("roster_min_total must be >= roster_min_main")
    if not isinstance(body["name"], str) or not isinstance(body["tour_country_code"], str):
        raise err_invalid_request("name and tour_country_code must be strings")

    for ev in DB["events"].values():
        if ev["arena_id"] == arena["id"] and ev["event_date"] == body["event_date"]:
            raise biz("ERR_ARENA_DATE_CONFLICT",
                      "Arena already hosts an event on this date")

    rec = create_resource("events", {
        "name": body["name"],
        "event_type": event_type,
        "arena_id": arena["id"],
        "anchor_id": anchor_id,
        "event_date": body["event_date"],
        "start_time": body["start_time"],
        "end_time": body["end_time"],
        "tour_country_code": body["tour_country_code"],
        "status": "SCHEDULED",
        "roster_min_main": rmin,
        "roster_min_total": rtot,
    })
    return envelope(rec, "object", 201)


@app.route("/touring/events", methods=["GET"])
@role_required(EVENT_ROLES_READ)
def list_events():
    items = list(DB["events"].values())
    for f in ("status", "event_type", "arena_id", "anchor_id"):
        v = request.args.get(f)
        if v is not None:
            items = [e for e in items if str(e.get(f)) == v]
    return list_response(items)


@app.route("/touring/events/<eid>", methods=["GET"])
@role_required(EVENT_ROLES_READ)
def get_event(eid):
    return envelope(get_or_404("events", eid), "object", 200)


@app.route("/touring/events/<eid>/lock", methods=["POST"])
@role_required(["TourPlanner"])
def lock_event(eid):
    ev = get_or_404("events", eid)
    if ev["status"] != "SCHEDULED":
        raise err_invalid_state("Event is not SCHEDULED")
    body = get_body()
    if "expected_event_version" in body and body["expected_event_version"] is not None:
        v = body["expected_event_version"]
        if isinstance(v, bool) or not isinstance(v, int):
            raise err_invalid_request("expected_event_version must be an integer")
        if v != ev["version"]:
            raise err_stale("Event version has advanced; re-read before locking")
    booked = [b for b in DB["bookings"].values()
              if b["event_id"] == eid and b["status"] == "BOOKED"]
    total = len(booked)
    main_count = sum(
        1 for b in booked
        if DB["talents"].get(b["talent_id"], {}).get("roster_tier") == "MAIN_ROSTER"
    )
    if total < ev["roster_min_total"] or main_count < ev["roster_min_main"]:
        raise biz("ERR_ROSTER_MINIMUM_UNMET", "Roster minimums not met")
    ev["status"] = "LOCKED"
    touch(ev)
    return envelope(ev, "object", 200)


@app.route("/touring/events/<eid>/complete", methods=["POST"])
@role_required(["TourPlanner"])
def complete_event(eid):
    ev = get_or_404("events", eid)
    if ev["status"] != "LOCKED":
        raise err_invalid_state("Event is not LOCKED")
    ev["status"] = "COMPLETED"
    touch(ev)

    for b in DB["bookings"].values():
        if b["event_id"] == eid and b["status"] == "BOOKED":
            b["status"] = "FULFILLED"
            touch(b)
            talent = DB["talents"].get(b["talent_id"])
            if talent is not None:
                apply_wellness(talent, 3.0)

    for ch in DB["chapters"].values():
        if ch["event_id"] == eid and ch["status"] == "PLANNED":
            ch["status"] = "COMPLETED"
            touch(ch)
            sl = DB["storylines"].get(ch["storyline_id"])
            if sl is not None and sl.get("gap_count", 0) != 0:
                sl["gap_count"] = 0
                touch(sl)

    return envelope(ev, "object", 200)


@app.route("/touring/events/<eid>/cancel", methods=["POST"])
@role_required(["TourPlanner"])
def cancel_event(eid):
    ev = get_or_404("events", eid)
    if ev["status"] != "SCHEDULED":
        raise err_invalid_state("Event is not SCHEDULED")
    ev["status"] = "CANCELLED"
    touch(ev)

    for b in DB["bookings"].values():
        if b["event_id"] == eid and b["status"] == "BOOKED":
            scratch_booking(b)

    for ch in DB["chapters"].values():
        if ch["event_id"] == eid and ch["status"] == "PLANNED":
            ch["status"] = "MISSED"
            touch(ch)
            gap_increment(ch["storyline_id"])

    for w in DB["distribution_windows"].values():
        if w["event_id"] == eid and w["status"] in ("PROVISIONAL", "PUBLISHED"):
            w["status"] = "REVOKED"
            touch(w)

    return envelope(ev, "object", 200)


# =============================================================================
# Bookings
# =============================================================================
BOOKING_READ = ["TourPlanner", "TalentRelations", "StorylineEditor", "MerchOps"]


@app.route("/touring/bookings", methods=["POST"])
@role_required(["TourPlanner"])
def create_booking():
    body = get_body()
    require_fields(body, ["event_id", "talent_id", "segment_label"])
    ev = body_fk_or_404("events", body["event_id"], "event_id")
    talent = body_fk_or_404("talents", body["talent_id"], "talent_id")
    storyline_id = body.get("storyline_id")
    if storyline_id is not None:
        body_fk_or_404("storylines", storyline_id, "storyline_id")

    if ev["status"] != "SCHEDULED":
        raise err_event_not_mutable("Event is not SCHEDULED")

    mode = talent.get("booking_mode", "UNBOOKABLE")
    if mode == "UNBOOKABLE" or (mode == "LIMITED" and ev["event_type"] != "HOUSE_SHOW"):
        raise biz("ERR_TALENT_UNBOOKABLE", "Talent booking_mode does not permit this booking")

    if ev["tour_country_code"] != "US":
        try:
            ev_date = datetime.strptime(ev["event_date"], "%Y-%m-%d").date()
        except Exception:
            ev_date = None
        ok = False
        for vc in DB["visa_cases"].values():
            if (vc["talent_id"] == talent["id"] and vc["status"] == "GRANTED"
                    and vc["country_code"] == ev["tour_country_code"]):
                try:
                    rbd = datetime.strptime(vc["required_by_date"], "%Y-%m-%d").date()
                except Exception:
                    continue
                if ev_date is not None and rbd >= ev_date:
                    ok = True
                    break
        if not ok:
            raise biz("ERR_VISA_REQUIRED", "International booking requires a GRANTED visa covering the event date")

    if not isinstance(body["segment_label"], str):
        raise err_invalid_request("segment_label must be a string")

    ev_start = parse_time_hm(ev["start_time"], "start_time")
    ev_end = parse_time_hm(ev["end_time"], "end_time")
    for b in DB["bookings"].values():
        if b["talent_id"] != talent["id"] or b["status"] != "BOOKED":
            continue
        other = DB["events"].get(b["event_id"])
        if other is None or other["status"] not in ("SCHEDULED", "LOCKED"):
            continue
        if other["event_date"] != ev["event_date"]:
            continue
        o_start = parse_time_hm(other["start_time"], "start_time")
        o_end = parse_time_hm(other["end_time"], "end_time")
        if ev_start < o_end and o_start < ev_end:
            raise biz("ERR_TALENT_DOUBLE_BOOKED",
                      "Talent already booked on an overlapping event the same date")

    rec = create_resource("bookings", {
        "event_id": ev["id"],
        "talent_id": talent["id"],
        "storyline_id": storyline_id,
        "segment_label": body["segment_label"],
        "status": "BOOKED",
    })
    return envelope(rec, "object", 201)


@app.route("/touring/bookings", methods=["GET"])
@role_required(BOOKING_READ)
def list_bookings():
    items = list(DB["bookings"].values())
    for f in ("event_id", "talent_id", "storyline_id", "status"):
        v = request.args.get(f)
        if v is not None:
            items = [b for b in items if str(b.get(f)) == v]
    return list_response(items)


@app.route("/touring/bookings/<bid>", methods=["GET"])
@role_required(BOOKING_READ)
def get_booking(bid):
    return envelope(get_or_404("bookings", bid), "object", 200)


@app.route("/touring/bookings/<bid>/scratch", methods=["POST"])
@role_required(["TourPlanner"])
def scratch_booking_endpoint(bid):
    b = get_or_404("bookings", bid)
    if b["status"] != "BOOKED":
        raise err_invalid_state("Booking is not BOOKED")
    ev = DB["events"].get(b["event_id"])
    if ev is None or ev["status"] != "SCHEDULED":
        raise err_event_not_mutable("Owning event is not SCHEDULED")
    scratch_booking(b)
    return envelope(b, "object", 200)


@app.route("/touring/events/<eid>/bookings/<bid>/no-show", methods=["POST"])
@role_required(["TourPlanner"])
def no_show(eid, bid):
    ev = get_or_404("events", eid)
    b = get_or_404("bookings", bid)
    if b["status"] != "FULFILLED":
        raise err_invalid_state("Booking is not FULFILLED")
    if ev["status"] != "COMPLETED":
        raise err_invalid_state("Owning event is not COMPLETED")
    try:
        ev_date = datetime.strptime(ev["event_date"], "%Y-%m-%d").date()
    except Exception:
        ev_date = None
    if clock_date() != ev_date:
        raise err_invalid_state("No-show correction is same-day only")
    b["status"] = "NO_SHOW"
    touch(b)
    talent = DB["talents"].get(b["talent_id"])
    if talent is not None:
        apply_wellness(talent, -11.0)
    return envelope(b, "object", 200)


# =============================================================================
# Storylines & chapters
# =============================================================================
@app.route("/touring/storylines", methods=["POST"])
@role_required(["StorylineEditor"])
def create_storyline():
    body = get_body()
    require_fields(body, ["title"])
    if not isinstance(body["title"], str):
        raise err_invalid_request("title must be a string")
    rec = create_resource("storylines", {
        "title": body["title"],
        "status": "PLANNED",
        "gap_count": 0,
    })
    return envelope(rec, "object", 201)


@app.route("/touring/storylines/<sid>", methods=["GET"])
@role_required(["StorylineEditor", "TourPlanner"])
def get_storyline(sid):
    return envelope(get_or_404("storylines", sid), "object", 200)


@app.route("/touring/storylines/<sid>/chapters", methods=["GET"])
@role_required(["StorylineEditor", "TourPlanner"])
def storyline_chapters(sid):
    get_or_404("storylines", sid)
    items = [c for c in DB["chapters"].values() if c["storyline_id"] == sid]
    return list_response(items)


@app.route("/touring/storylines/<sid>/activate", methods=["POST"])
@role_required(["StorylineEditor"])
def activate_storyline(sid):
    sl = get_or_404("storylines", sid)
    if sl["status"] != "PLANNED":
        raise err_invalid_state("Storyline is not PLANNED")
    has_planned = any(c["storyline_id"] == sid and c["status"] == "PLANNED"
                      for c in DB["chapters"].values())
    if not has_planned:
        raise err_invalid_state("Storyline has no PLANNED chapter")
    sl["status"] = "ACTIVE"
    touch(sl)
    return envelope(sl, "object", 200)


@app.route("/touring/storylines/<sid>/conclude", methods=["POST"])
@role_required(["StorylineEditor"])
def conclude_storyline(sid):
    sl = get_or_404("storylines", sid)
    if sl["status"] != "ACTIVE":
        raise err_invalid_state("Storyline is not ACTIVE")
    for ch in DB["chapters"].values():
        if ch["storyline_id"] == sid and ch["status"] == "PLANNED":
            raise err_invalid_state("Storyline has non-terminal chapters")
    sl["status"] = "CONCLUDED"
    touch(sl)
    return envelope(sl, "object", 200)


@app.route("/touring/storylines/<sid>/revive", methods=["POST"])
@role_required(["StorylineEditor"])
def revive_storyline(sid):
    sl = get_or_404("storylines", sid)
    if sl["status"] != "SHELVED":
        raise err_invalid_state("Storyline is not SHELVED")
    sl["status"] = "ACTIVE"
    sl["gap_count"] = 0
    touch(sl)
    return envelope(sl, "object", 200)


@app.route("/touring/chapters", methods=["POST"])
@role_required(["StorylineEditor"])
def create_chapter():
    body = get_body()
    require_fields(body, ["storyline_id", "event_id"])
    sl = body_fk_or_404("storylines", body["storyline_id"], "storyline_id")
    ev = body_fk_or_404("events", body["event_id"], "event_id")
    rec = create_resource("chapters", {
        "storyline_id": sl["id"],
        "event_id": ev["id"],
        "chapter_index": 0,
        "status": "PLANNED",
    })
    recompute_chapter_indexes(sl["id"])
    rec = DB["chapters"][rec["id"]]
    return envelope(rec, "object", 201)


@app.route("/touring/chapters", methods=["GET"])
@role_required(["StorylineEditor", "TourPlanner"])
def list_chapters():
    items = list(DB["chapters"].values())
    for f in ("storyline_id", "event_id", "status"):
        v = request.args.get(f)
        if v is not None:
            items = [c for c in items if str(c.get(f)) == v]
    return list_response(items)


@app.route("/touring/events/<eid>/chapters", methods=["GET"])
@role_required(["StorylineEditor", "TourPlanner"])
def event_chapters(eid):
    get_or_404("events", eid)
    items = [c for c in DB["chapters"].values() if c["event_id"] == eid]
    return list_response(items)


# =============================================================================
# Distribution: partners, territory rights, windows
# =============================================================================
@app.route("/touring/streaming-partners", methods=["POST"])
@role_required(["DistributionManager"])
def create_partner():
    body = get_body()
    require_fields(body, ["name", "partner_code"])
    if not isinstance(body["name"], str) or not isinstance(body["partner_code"], str):
        raise err_invalid_request("name and partner_code must be strings")
    rec = create_resource("partners", {
        "name": body["name"],
        "partner_code": body["partner_code"],
        "status": "ACTIVE",
    })
    return envelope(rec, "object", 201)


@app.route("/touring/streaming-partners", methods=["GET"])
@role_required(["DistributionManager"])
def list_partners():
    items = list(DB["partners"].values())
    sv = request.args.get("status")
    if sv is not None:
        items = [p for p in items if p["status"] == sv]
    return list_response(items)


@app.route("/touring/streaming-partners/<pid>", methods=["GET"])
@role_required(["DistributionManager"])
def get_partner(pid):
    return envelope(get_or_404("partners", pid), "object", 200)


@app.route("/touring/territory-rights", methods=["POST"])
@role_required(["DistributionManager"])
def create_territory_right():
    body = get_body()
    require_fields(body, ["partner_id", "territory_code", "window_start_date",
                          "window_end_date", "exclusive"])
    partner = body_fk_or_404("partners", body["partner_id"], "partner_id")
    start = parse_date(body["window_start_date"], "window_start_date")
    end = parse_date(body["window_end_date"], "window_end_date")
    if end <= start:
        raise err_invalid_request("window_end_date must be after window_start_date")
    if not isinstance(body["exclusive"], bool):
        raise err_invalid_request("exclusive must be a boolean")
    if not isinstance(body["territory_code"], str):
        raise err_invalid_request("territory_code must be a string")

    for r in DB["territory_rights"].values():
        if r["territory_code"] != body["territory_code"]:
            continue
        try:
            s2 = datetime.strptime(r["window_start_date"], "%Y-%m-%d").date()
            e2 = datetime.strptime(r["window_end_date"], "%Y-%m-%d").date()
        except Exception:
            continue
        if not _windows_overlap(start, end, s2, e2):
            continue
        if body["exclusive"] or r["exclusive"]:
            raise biz("ERR_TERRITORY_RIGHT_CONFLICT",
                      "Right overlaps an exclusive right on the same territory")
        if r["partner_id"] == partner["id"]:
            raise biz("ERR_TERRITORY_RIGHT_CONFLICT",
                      "Same-partner same-territory rights may not overlap")

    rec = create_resource("territory_rights", {
        "partner_id": partner["id"],
        "territory_code": body["territory_code"],
        "window_start_date": body["window_start_date"],
        "window_end_date": body["window_end_date"],
        "exclusive": body["exclusive"],
    })
    return envelope(rec, "object", 201)


@app.route("/touring/territory-rights", methods=["GET"])
@role_required(["DistributionManager"])
def list_territory_rights():
    items = list(DB["territory_rights"].values())
    for f in ("partner_id", "territory_code"):
        v = request.args.get(f)
        if v is not None:
            items = [r for r in items if str(r.get(f)) == v]
    return list_response(items)


@app.route("/touring/territory-rights/<rid>", methods=["GET"])
@role_required(["DistributionManager"])
def get_territory_right(rid):
    return envelope(get_or_404("territory_rights", rid), "object", 200)


def _event_start_end_utc(ev):
    # Event date/times are in the host arena's local calendar (PRD §3.3);
    # the event's start/end instants in UTC are derived through the arena's
    # IANA timezone.
    from zoneinfo import ZoneInfo
    arena = DB["arenas"].get(ev.get("arena_id")) or {}
    try:
        tz = ZoneInfo(arena.get("timezone", "UTC"))
    except Exception:
        tz = timezone.utc
    ev_date = datetime.strptime(ev["event_date"], "%Y-%m-%d").date()
    sh, sm = map(int, ev["start_time"].split(":"))
    eh, em = map(int, ev["end_time"].split(":"))
    start = datetime.combine(ev_date, time(sh, sm), tzinfo=tz).astimezone(timezone.utc)
    end = datetime.combine(ev_date, time(eh, em), tzinfo=tz).astimezone(timezone.utc)
    return start, end


def _check_window_timing(ev, window_type, opens_at, exclude_id=None, partner_id=None,
                         territory_code=None, closes_at=None):
    start_utc, end_utc = _event_start_end_utc(ev)
    if window_type == "LIVE":
        earliest = start_utc - timedelta(minutes=30)
    else:
        earliest = end_utc + timedelta(hours=24)
    if opens_at < earliest:
        raise biz("ERR_WINDOW_OVERLAP", "Window opens earlier than permitted")
    if partner_id is not None and territory_code is not None and closes_at is not None:
        for w in DB["distribution_windows"].values():
            if w["event_id"] != ev["id"]:
                continue
            if w["partner_id"] != partner_id or w["territory_code"] != territory_code:
                continue
            if exclude_id and w["id"] == exclude_id:
                continue
            if w["status"] == "REVOKED":
                continue
            o2 = parse_dt(w["opens_at"], "opens_at")
            c2 = parse_dt(w["closes_at"], "closes_at")
            if opens_at < c2 and o2 < closes_at:
                raise biz("ERR_WINDOW_OVERLAP",
                          "Window overlaps another window for the same partner+territory")


@app.route("/touring/distribution-windows", methods=["POST"])
@role_required(["DistributionManager"])
def create_distribution_window():
    body = get_body()
    require_fields(body, ["event_id", "partner_id", "territory_code", "window_type",
                          "opens_at", "closes_at"])
    ev = body_fk_or_404("events", body["event_id"], "event_id")
    partner = body_fk_or_404("partners", body["partner_id"], "partner_id")

    if ev["event_type"] != "PREMIUM":
        raise biz("ERR_EVENT_NOT_PREMIUM", "Distribution windows require a PREMIUM event")

    window_type = body["window_type"]
    if window_type not in ("LIVE", "REPLAY"):
        raise err_invalid_request("window_type must be LIVE or REPLAY")
    opens_at = parse_dt(body["opens_at"], "opens_at")
    closes_at = parse_dt(body["closes_at"], "closes_at")
    if closes_at <= opens_at:
        raise err_invalid_request("closes_at must be after opens_at")
    if not isinstance(body["territory_code"], str):
        raise err_invalid_request("territory_code must be a string")

    # Licensing (pinned at creation)
    licensed = False
    if partner["status"] == "ACTIVE":
        for r in DB["territory_rights"].values():
            if r["partner_id"] != partner["id"] or r["territory_code"] != body["territory_code"]:
                continue
            try:
                rs = datetime.strptime(r["window_start_date"], "%Y-%m-%d").date()
                re_ = datetime.strptime(r["window_end_date"], "%Y-%m-%d").date()
            except Exception:
                continue
            if rs <= opens_at.date() and closes_at.date() < re_:
                licensed = True
                break
    if not licensed:
        raise biz("ERR_TERRITORY_NOT_LICENSED",
                  "No ACTIVE partner TerritoryRight covers the window's territory and dates")

    _check_window_timing(ev, window_type, opens_at,
                         partner_id=partner["id"],
                         territory_code=body["territory_code"],
                         closes_at=closes_at)

    rec = create_resource("distribution_windows", {
        "event_id": ev["id"],
        "partner_id": partner["id"],
        "territory_code": body["territory_code"],
        "window_type": window_type,
        "opens_at": body["opens_at"],
        "closes_at": body["closes_at"],
        "status": "PROVISIONAL",
    })
    return envelope(rec, "object", 201)


@app.route("/touring/distribution-windows", methods=["GET"])
@role_required(["DistributionManager"])
def list_distribution_windows():
    items = list(DB["distribution_windows"].values())
    for f in ("event_id", "partner_id", "status"):
        v = request.args.get(f)
        if v is not None:
            items = [w for w in items if str(w.get(f)) == v]
    return list_response(items)


@app.route("/touring/distribution-windows/<wid>", methods=["GET"])
@role_required(["DistributionManager"])
def get_distribution_window(wid):
    return envelope(get_or_404("distribution_windows", wid), "object", 200)


@app.route("/touring/distribution-windows/<wid>/publish", methods=["POST"])
@role_required(["DistributionManager"])
def publish_window(wid):
    w = get_or_404("distribution_windows", wid)
    if w["status"] != "PROVISIONAL":
        raise err_invalid_state("Window is not PROVISIONAL")
    ev = DB["events"].get(w["event_id"])
    if ev is None or ev["status"] not in ("SCHEDULED", "LOCKED"):
        raise err_invalid_state("Owning event is not SCHEDULED or LOCKED")
    opens_at = parse_dt(w["opens_at"], "opens_at")
    closes_at = parse_dt(w["closes_at"], "closes_at")
    _check_window_timing(ev, w["window_type"], opens_at, exclude_id=wid,
                         partner_id=w["partner_id"],
                         territory_code=w["territory_code"],
                         closes_at=closes_at)
    w["status"] = "PUBLISHED"
    touch(w)
    return envelope(w, "object", 200)


@app.route("/touring/distribution-windows/<wid>/revoke", methods=["POST"])
@role_required(["DistributionManager"])
def revoke_window(wid):
    w = get_or_404("distribution_windows", wid)
    if w["status"] not in ("PROVISIONAL", "PUBLISHED"):
        raise err_invalid_state("Window is not PROVISIONAL or PUBLISHED")
    w["status"] = "REVOKED"
    touch(w)
    return envelope(w, "object", 200)


# =============================================================================
# Merch sales & royalty statements
# =============================================================================
def _round_half_up_int(numer, denom):
    return (2 * numer + denom) // (2 * denom)


def _active_agreement_for(talent_id):
    for ag in DB["agreements"].values():
        if ag["talent_id"] == talent_id and ag["status"] == "ACTIVE":
            return ag
    return None


def _line_royalty(sale):
    ag = _active_agreement_for(sale["talent_id"])
    if ag is None:
        return 0
    base_rate = ag["royalty_rate_bp"]
    try:
        sale_date = parse_dt(sale["sold_at"], "sold_at").date()
    except Exception:
        sale_date = None
    day_gross = 0
    for s in DB["merch_sales"].values():
        if s["talent_id"] != sale["talent_id"] or s["event_id"] != sale["event_id"]:
            continue
        try:
            sd = parse_dt(s["sold_at"], "sold_at").date()
        except Exception:
            continue
        if sd == sale_date:
            day_gross += s["quantity"] * s["unit_price_cents"]
    if day_gross > 250000:
        rate = base_rate + 200
    elif day_gross >= 100000:
        rate = base_rate
    else:
        rate = base_rate - 100
    line_gross = sale["quantity"] * sale["unit_price_cents"]
    return _round_half_up_int(line_gross * rate, 10000)


@app.route("/touring/merch-sales", methods=["POST"])
@role_required(["MerchOps"])
def create_merch_sale():
    body = get_body()
    require_fields(body, ["event_id", "talent_id", "quantity", "unit_price_cents", "sold_at"])
    ev = body_fk_or_404("events", body["event_id"], "event_id")
    talent = body_fk_or_404("talents", body["talent_id"], "talent_id")

    if not talent.get("likeness_granted") or _active_agreement_for(talent["id"]) is None:
        raise biz("ERR_LIKENESS_NOT_GRANTED",
                  "Talent lacks an ACTIVE agreement with likeness rights granted")

    if ev["status"] in ("COMPLETED", "CANCELLED"):
        raise biz("ERR_MERCH_WINDOW_CLOSED", "Event merch window is closed")

    qty = req_int(body, "quantity")
    if qty <= 0:
        raise err_invalid_request("quantity must be positive")
    price = req_int(body, "unit_price_cents", minimum=0)
    parse_dt(body["sold_at"], "sold_at")

    ts = now_wall_iso()
    rec = {
        "id": new_id(),
        "created_at": ts,
        "event_id": ev["id"],
        "talent_id": talent["id"],
        "quantity": qty,
        "unit_price_cents": price,
        "sold_at": body["sold_at"],
        "royalty_cents": 0,
    }
    DB["merch_sales"][rec["id"]] = rec
    rec["royalty_cents"] = _line_royalty(rec)
    return envelope(rec, "object", 201)


@app.route("/touring/merch-sales", methods=["GET"])
@role_required(["MerchOps", "ContractAdmin"])
def list_merch_sales():
    items = list(DB["merch_sales"].values())
    for f in ("event_id", "talent_id"):
        v = request.args.get(f)
        if v is not None:
            items = [s for s in items if str(s.get(f)) == v]
    return list_response(items)


@app.route("/touring/merch-sales/<sid>", methods=["GET"])
@role_required(["MerchOps", "ContractAdmin"])
def get_merch_sale(sid):
    return envelope(get_or_404("merch_sales", sid), "object", 200)


@app.route("/touring/events/<eid>/merch-sales", methods=["GET"])
@role_required(["MerchOps", "ContractAdmin"])
def event_merch_sales(eid):
    get_or_404("events", eid)
    items = [s for s in DB["merch_sales"].values() if s["event_id"] == eid]
    return list_response(items)


def _statement_lines(stmt):
    start = datetime.strptime(stmt["period_start_date"], "%Y-%m-%d").date()
    end = datetime.strptime(stmt["period_end_date"], "%Y-%m-%d").date()
    out = []
    for s in DB["merch_sales"].values():
        if s["talent_id"] != stmt["talent_id"]:
            continue
        try:
            sd = parse_dt(s["sold_at"], "sold_at").date()
        except Exception:
            continue
        if not (start <= sd < end):
            continue
        ev = DB["events"].get(s["event_id"])
        if ev is None:
            continue
        if stmt["basis_mode"] == "PROVISIONAL":
            if ev["status"] not in ("LOCKED", "COMPLETED"):
                continue
        else:
            if ev["status"] != "COMPLETED":
                continue
        out.append(s)
    return out


def _recompute_statement(stmt):
    lines = _statement_lines(stmt)
    total_sales = sum(s["quantity"] * s["unit_price_cents"] for s in lines)
    total_royalty = sum(s.get("royalty_cents", 0) for s in lines)
    stmt["total_sales_cents"] = total_sales
    stmt["total_royalty_cents"] = total_royalty
    event_ids = {s["event_id"] for s in lines}
    stmt["event_id"] = next(iter(event_ids)) if len(event_ids) == 1 else None


@app.route("/touring/royalty-statements", methods=["POST"])
@role_required(["ContractAdmin"])
def create_statement():
    body = get_body()
    require_fields(body, ["talent_id", "period_start_date", "period_end_date", "basis_mode"])
    talent = body_fk_or_404("talents", body["talent_id"], "talent_id")
    start = parse_date(body["period_start_date"], "period_start_date")
    end = parse_date(body["period_end_date"], "period_end_date")
    if end <= start:
        raise err_invalid_request("period_end_date must be after period_start_date")
    basis = body["basis_mode"]
    if basis not in ("PROVISIONAL", "FINAL"):
        raise err_invalid_request("basis_mode must be PROVISIONAL or FINAL")
    rec = create_resource("statements", {
        "talent_id": talent["id"],
        "period_start_date": body["period_start_date"],
        "period_end_date": body["period_end_date"],
        "basis_mode": basis,
        "status": "OPEN",
        "event_id": None,
        "total_sales_cents": 0,
        "total_royalty_cents": 0,
    })
    _recompute_statement(rec)
    return envelope(rec, "object", 201)


@app.route("/touring/royalty-statements", methods=["GET"])
@role_required(["ContractAdmin"])
def list_statements():
    items = list(DB["statements"].values())
    for f in ("talent_id", "event_id", "status"):
        v = request.args.get(f)
        if v is not None:
            items = [s for s in items if str(s.get(f)) == v]
    return list_response(items)


@app.route("/touring/royalty-statements/<sid>", methods=["GET"])
@role_required(["ContractAdmin"])
def get_statement(sid):
    return envelope(get_or_404("statements", sid), "object", 200)


@app.route("/touring/royalty-statements/<sid>/recompute", methods=["POST"])
@role_required(["ContractAdmin"])
def recompute_statement(sid):
    stmt = get_or_404("statements", sid)
    if stmt["status"] != "OPEN":
        raise err_invalid_state("Statement is not OPEN")
    _recompute_statement(stmt)
    touch(stmt)
    return envelope(stmt, "object", 200)


@app.route("/touring/royalty-statements/<sid>/finalize", methods=["POST"])
@role_required(["ContractAdmin"])
def finalize_statement(sid):
    stmt = get_or_404("statements", sid)
    if stmt["status"] != "OPEN":
        raise err_invalid_state("Statement is not OPEN")
    if stmt["basis_mode"] != "FINAL":
        raise biz("ERR_STATEMENT_NOT_FINALIZABLE",
                  "Only FINAL-basis statements may be finalized")
    stmt["status"] = "FINALIZED"
    touch(stmt)
    return envelope(stmt, "object", 200)


# =============================================================================
# Medical
# =============================================================================
INJURY_SCRATCH_HORIZON_DAYS = 30


@app.route("/touring/medical-cases", methods=["POST"])
@role_required(["Medic"])
def create_medical_case():
    body = get_body()
    require_fields(body, ["talent_id", "severity"])
    talent = body_fk_or_404("talents", body["talent_id"], "talent_id")
    severity = body["severity"]
    if severity not in ("MINOR", "MAJOR"):
        raise err_invalid_request("severity must be MINOR or MAJOR")

    rec = create_resource("medical_cases", {
        "talent_id": talent["id"],
        "severity": severity,
        "evaluation_ids": [],
        "clearance_id": None,
        "status": "OPEN",
    })

    if talent["availability_status"] == "ACTIVE":
        talent["availability_status"] = "INJURED"
        touch(talent)
    rederive_booking_mode(talent)

    today = clock_date()
    horizon_end = today + timedelta(days=INJURY_SCRATCH_HORIZON_DAYS)
    for b in DB["bookings"].values():
        if b["talent_id"] != talent["id"] or b["status"] != "BOOKED":
            continue
        ev = DB["events"].get(b["event_id"])
        if ev is None or ev["status"] != "SCHEDULED":
            continue
        try:
            ev_date = datetime.strptime(ev["event_date"], "%Y-%m-%d").date()
        except Exception:
            continue
        if today <= ev_date <= horizon_end:
            scratch_booking(b)

    return envelope(rec, "object", 201)


@app.route("/touring/medical-cases/<mid>", methods=["GET"])
@role_required(["Medic"])
def get_medical_case(mid):
    return envelope(get_or_404("medical_cases", mid), "object", 200)


@app.route("/touring/medical-cases/<mid>/evaluations", methods=["GET"])
@role_required(["Medic"])
def list_evaluations(mid):
    get_or_404("medical_cases", mid)
    items = [e for e in DB["evaluations"].values() if e["medical_case_id"] == mid]
    return list_response(items)


@app.route("/touring/medical-cases/<mid>/evaluations", methods=["POST"])
@role_required(["Medic"])
def create_evaluation(mid):
    case = get_or_404("medical_cases", mid)
    body = get_body()
    if case["status"] != "OPEN":
        raise err_invalid_state("Medical case is not OPEN")
    require_fields(body, ["evaluator_id", "findings", "recommends_clearance"])
    if not isinstance(body["evaluator_id"], str) or not isinstance(body["findings"], str):
        raise err_invalid_request("evaluator_id and findings must be strings")
    if not isinstance(body["recommends_clearance"], bool):
        raise err_invalid_request("recommends_clearance must be a boolean")
    rec = create_resource("evaluations", {
        "medical_case_id": mid,
        "evaluator_id": body["evaluator_id"],
        "findings": body["findings"],
        "recommends_clearance": body["recommends_clearance"],
    })
    case["evaluation_ids"].append(rec["id"])
    touch(case)
    return envelope(rec, "object", 201)


@app.route("/touring/medical-cases/<mid>/clearances", methods=["POST"])
@role_required(["Medic"])
def create_clearance(mid):
    case = get_or_404("medical_cases", mid)
    body = get_body()
    if case["status"] != "OPEN":
        raise err_invalid_state("Medical case is not OPEN")
    require_fields(body, ["cleared_by"])
    cleared_by = body["cleared_by"]
    if not isinstance(cleared_by, str):
        raise err_invalid_request("cleared_by must be a string")

    evals = [DB["evaluations"][eid] for eid in case["evaluation_ids"]
             if eid in DB["evaluations"]]
    recommending = {e["evaluator_id"] for e in evals if e["recommends_clearance"]}
    all_evaluators = {e["evaluator_id"] for e in evals}
    if len(recommending) < 2 or cleared_by in all_evaluators:
        raise biz("ERR_CLEARANCE_PROTOCOL_VIOLATION",
                  "Clearance requires >= 2 recommending evaluations from distinct evaluators "
                  "and a clearing medic who did not evaluate the case")

    rec = create_resource("clearances", {
        "medical_case_id": mid,
        "cleared_by": cleared_by,
        "cleared_at": _fmt_instant(clock_now()),
    })
    case["status"] = "CLEARED"
    case["clearance_id"] = rec["id"]
    touch(case)
    talent = DB["talents"].get(case["talent_id"])
    if talent is not None and talent["availability_status"] == "INJURED":
        talent["availability_status"] = "ACTIVE"
        touch(talent)
        rederive_booking_mode(talent)
    return envelope(rec, "object", 201)


@app.route("/touring/medical-cases/<mid>/clearances", methods=["GET"])
@role_required(["Medic"])
def list_clearances(mid):
    get_or_404("medical_cases", mid)
    items = [c for c in DB["clearances"].values() if c["medical_case_id"] == mid]
    return list_response(items)


# =============================================================================
# Visas
# =============================================================================
@app.route("/touring/visa-cases", methods=["POST"])
@role_required(["LogisticsCoordinator"])
def create_visa_case():
    body = get_body()
    require_fields(body, ["talent_id", "country_code", "required_by_date"])
    talent = body_fk_or_404("talents", body["talent_id"], "talent_id")
    parse_date(body["required_by_date"], "required_by_date")
    if not isinstance(body["country_code"], str):
        raise err_invalid_request("country_code must be a string")
    rec = create_resource("visa_cases", {
        "talent_id": talent["id"],
        "country_code": body["country_code"],
        "required_by_date": body["required_by_date"],
        "status": "DRAFT",
    })
    return envelope(rec, "object", 201)


@app.route("/touring/visa-cases/<vid>", methods=["GET"])
@role_required(["LogisticsCoordinator"])
def get_visa_case(vid):
    return envelope(get_or_404("visa_cases", vid), "object", 200)


@app.route("/touring/visa-cases/<vid>/submit", methods=["POST"])
@role_required(["LogisticsCoordinator"])
def submit_visa(vid):
    vc = get_or_404("visa_cases", vid)
    if vc["status"] != "DRAFT":
        raise err_invalid_state("Visa case is not DRAFT")
    rbd = datetime.strptime(vc["required_by_date"], "%Y-%m-%d").date()
    if not (rbd > clock_date()):
        raise biz("ERR_VISA_WINDOW_PASSED", "required_by_date has been reached or passed")
    vc["status"] = "SUBMITTED"
    touch(vc)
    return envelope(vc, "object", 200)


@app.route("/touring/visa-cases/<vid>/grant", methods=["POST"])
@role_required(["LogisticsCoordinator"])
def grant_visa(vid):
    vc = get_or_404("visa_cases", vid)
    if vc["status"] != "SUBMITTED":
        raise err_invalid_state("Visa case is not SUBMITTED")
    rbd = datetime.strptime(vc["required_by_date"], "%Y-%m-%d").date()
    if clock_date() > rbd:
        raise biz("ERR_VISA_WINDOW_PASSED", "Grant after required_by_date is rejected")
    vc["status"] = "GRANTED"
    touch(vc)
    return envelope(vc, "object", 200)


@app.route("/touring/visa-cases/<vid>/deny", methods=["POST"])
@role_required(["LogisticsCoordinator"])
def deny_visa(vid):
    vc = get_or_404("visa_cases", vid)
    if vc["status"] != "SUBMITTED":
        raise err_invalid_state("Visa case is not SUBMITTED")
    vc["status"] = "DENIED"
    touch(vc)
    rbd = datetime.strptime(vc["required_by_date"], "%Y-%m-%d").date()
    for b in DB["bookings"].values():
        if b["talent_id"] != vc["talent_id"] or b["status"] != "BOOKED":
            continue
        ev = DB["events"].get(b["event_id"])
        if ev is None or ev["status"] != "SCHEDULED":
            continue
        if ev["tour_country_code"] != vc["country_code"]:
            continue
        try:
            ev_date = datetime.strptime(ev["event_date"], "%Y-%m-%d").date()
        except Exception:
            continue
        if ev_date <= rbd:
            scratch_booking(b)
    return envelope(vc, "object", 200)


# =============================================================================
# Entrypoint
# =============================================================================
if __name__ == "__main__":
    import os
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", "10000")))
