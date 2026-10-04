#!/usr/bin/env python3
"""Bowl Assembly Ops API — in-memory Flask implementation."""
import os
import re
import uuid
import random
import string
from datetime import datetime, timedelta, timezone
from decimal import Decimal, ROUND_HALF_UP

from flask import Flask, request, jsonify

app = Flask(__name__)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------
ROLES = {"OpsAdmin", "ShiftManager", "LineOperator", "PrepCook", "QualityLead", "Customer"}
SANITATION_INTERVAL_HOURS = 4
HOPPER_DEPLETION_THRESHOLD = 200.0
DRIFT_WINDOW_SIZE = 10
DRIFT_MIN_SAMPLES = 3
DRIFT_THRESHOLD_PCT = Decimal("3.0")
PORTION_TOLERANCE_PCT = Decimal("5.0")
EXTRA_MULTIPLIER = Decimal("1.5")
ROUTING_THRESHOLD = 8
QUEUE_TARGET_SECONDS = 300
DAILY_REFILL_BUDGET_GRAMS = Decimal("50000")
SAFETY_FACTOR = Decimal("0.8")
FORECAST_CAP_MINUTES = Decimal("240")
REMAKE_LIMIT = 3
STARTUP_CLOCK = datetime(2026, 9, 1, 0, 0, 0, tzinfo=timezone.utc)

STATION_SLOT_MAP = {0: "BASE", 1: "PROTEIN", 2: "TOPPING", 3: "TOPPING", 4: "TOPPING", 5: "TOPPING", 6: "DRESSING"}

# ---------------------------------------------------------------------------
# Logical clock
# ---------------------------------------------------------------------------
class Clock:
    def __init__(self):
        self._now = STARTUP_CLOCK

    def now(self):
        return self._now

    def set(self, dt):
        self._now = dt

CLOCK = Clock()

# ---------------------------------------------------------------------------
# In-memory store
# ---------------------------------------------------------------------------
db = {
    "restaurants": {},
    "assembly_lines": {},
    "ingredients": {},
    "recipes": {},
    "hoppers": {},
    "refill_tasks": {},
    "prep_batches": {},
    "orders": {},
    "portion_verifications": {},
    "calibration_adjustments": {},
    "substitution_rules": {},
    "sanitation_cycles": {},
    "labor_assignments": {},
}
seq_counter = [0]  # monotonic counter for stable tie-breaking within same timestamp


def next_seq():
    seq_counter[0] += 1
    return seq_counter[0]


# ---------------------------------------------------------------------------
# Errors
# ---------------------------------------------------------------------------
class ApiError(Exception):
    def __init__(self, error_id, http_status, message):
        super().__init__(message)
        self.error_id = error_id
        self.http_status = http_status
        self.message = message


def err_not_found(msg="resource not found"):
    return ApiError("ERR_NOT_FOUND", 404, msg)


def err_invalid_state(msg="invalid state"):
    return ApiError("ERR_INVALID_STATE", 409, msg)


def err_validation(msg="validation error"):
    return ApiError("ERR_VALIDATION", 400, msg)


# ---------------------------------------------------------------------------
# Response envelope
# ---------------------------------------------------------------------------
def _req_id():
    return "req_" + "".join(random.choices(string.ascii_uppercase + string.digits, k=20))


def _ts():
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.") + f"{datetime.now(timezone.utc).microsecond // 1000:03d}Z"


def make_meta(extra=None):
    m = {"api_request_id": _req_id(), "api_request_timestamp": _ts()}
    if extra:
        m.update(extra)
    return m


def ok_object(data, status=200):
    return jsonify({"meta": make_meta(), "response_type": "object", "data": data}), status


def ok_list(items, limit, offset, total_count, status=200):
    has_more = (offset + len(items)) < total_count
    meta = make_meta({"limit": limit, "offset": offset, "total_count": total_count, "has_more": has_more})
    return jsonify({"meta": meta, "response_type": "array", "data": items}), status


@app.errorhandler(ApiError)
def handle_api_error(e):
    body = {
        "meta": make_meta(),
        "response_type": "error",
        "data": {"error_id": e.error_id, "message": e.message},
    }
    return jsonify(body), e.http_status


@app.errorhandler(404)
def handle_404(e):
    return jsonify({
        "meta": make_meta(),
        "response_type": "error",
        "data": {"error_id": "ERR_NOT_FOUND", "message": "resource not found"},
    }), 404


@app.errorhandler(405)
def handle_405(e):
    return jsonify({
        "meta": make_meta(),
        "response_type": "error",
        "data": {"error_id": "ERR_NOT_FOUND", "message": "resource not found"},
    }), 404


@app.errorhandler(Exception)
def handle_exc(e):
    if isinstance(e, ApiError):
        return handle_api_error(e)
    import traceback
    traceback.print_exc()
    return jsonify({
        "meta": make_meta(),
        "response_type": "error",
        "data": {"error_id": "ERR_VALIDATION", "message": str(e)},
    }), 400


# ---------------------------------------------------------------------------
# Auth middleware
# ---------------------------------------------------------------------------
def get_auth():
    uid = request.headers.get("X-User-ID")
    role = request.headers.get("X-User-Role")
    if not uid or not role or role not in ROLES:
        raise ApiError("ERR_UNAUTHENTICATED", 401, "missing or unrecognized X-User-ID / X-User-Role")
    return uid, role


def require_roles(*roles):
    uid, role = get_auth()
    if role not in roles:
        raise ApiError("ERR_UNAUTHORIZED_ROLE", 403, "role not permitted for this endpoint")
    return uid, role


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
def iso(dt):
    if dt is None:
        return None
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + f"{dt.microsecond // 1000:03d}Z"


def parse_dt(value):
    if not isinstance(value, str):
        raise err_validation("expected ISO8601 datetime string")
    v = value.strip()
    if v.endswith("Z"):
        v = v[:-1] + "+00:00"
    try:
        dt = datetime.fromisoformat(v)
    except Exception:
        raise err_validation("invalid ISO8601 datetime")
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt


def parse_iso_relaxed(value):
    """Parse ISO8601 to datetime, or raise err_validation."""
    return parse_dt(value)


def new_id():
    return str(uuid.uuid4())


def now():
    return CLOCK.now()


def num(v):
    """Coerce to Decimal for gram math."""
    if isinstance(v, Decimal):
        return v
    return Decimal(str(v))


def round1(v):
    return Decimal(v).quantize(Decimal("0.1"), rounding=ROUND_HALF_UP)


def round2(v):
    return Decimal(v).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)


def dec_to_json(v):
    if v is None:
        return None
    d = Decimal(str(v))
    # normalize: emit as float if it has fractional part, int otherwise
    if d == d.to_integral_value():
        return int(d)
    return float(d)


def parse_limit_offset():
    try:
        limit = request.args.get("limit")
        offset = request.args.get("offset")
        limit = int(limit) if limit is not None else 10
        offset = int(offset) if offset is not None else 0
    except ValueError:
        raise err_validation("invalid limit/offset")
    if limit < 1 or limit > 100:
        raise err_validation("limit out of range")
    if offset < 0:
        raise err_validation("offset out of range")
    return limit, offset


def get_body():
    body = request.get_json(silent=True)
    if body is None:
        body = {}
    if not isinstance(body, dict):
        raise err_validation("request body must be a JSON object")
    return body


def required(body, field):
    if field not in body or body[field] is None:
        raise err_validation(f"missing required field: {field}")
    return body[field]


# ---------------------------------------------------------------------------
# Common fields plumbing
# ---------------------------------------------------------------------------
def stamp_new(rec):
    rec["id"] = new_id()
    rec["created_at"] = now()
    rec["updated_at"] = now()
    rec["version"] = 1
    rec["_seq"] = next_seq()


def touch(rec):
    rec["updated_at"] = now()
    rec["version"] = rec.get("version", 1) + 1


def serialize(rec):
    out = {}
    for k, v in rec.items():
        if k.startswith("_"):
            continue
        if isinstance(v, datetime):
            out[k] = iso(v)
        elif isinstance(v, Decimal):
            out[k] = dec_to_json(v)
        else:
            out[k] = v
    return out


# ---------------------------------------------------------------------------
# Derived computations
# ---------------------------------------------------------------------------
def compute_posture(line):
    if line["status"] != "ACTIVE":
        return "FROZEN"
    # sanitation overdue?
    nd = line.get("next_sanitation_due_at")
    if nd is not None and now() > nd:
        return "RESTRICTED"
    for h in db["hoppers"].values():
        if h["line_id"] == line["id"] and h["status"] in ("QUARANTINED", "DEPLETED", "REFILL_SCHEDULED", "REFILLING"):
            return "RESTRICTED"
    return "OPEN"


def active_substitution_for(restaurant_id, from_ingredient_id):
    """Return the ACTIVE substitution rule covering from_ingredient at restaurant now, or None."""
    t = now()
    for r in db["substitution_rules"].values():
        if (r["restaurant_id"] == restaurant_id and r["from_ingredient_id"] == from_ingredient_id
                and r["status"] == "ACTIVE"
                and r["effective_start"] <= t < r["effective_end"]):
            return r
    return None


def compute_is_available(recipe):
    for entry in recipe["portion_spec"]:
        ing = db["ingredients"].get(entry["ingredient_id"])
        if ing is None:
            return False
        if ing["status"] == "ACTIVE":
            continue
        if active_substitution_for(recipe["restaurant_id"], entry["ingredient_id"]) is not None:
            continue
        return False
    return True


def compute_drift_pct(hopper):
    anchor = hopper.get("drift_window_anchor")
    anchor_seq = hopper.get("_drift_window_anchor_seq")
    samples = []
    for pv in db["portion_verifications"].values():
        if pv["hopper_id"] != hopper["id"]:
            continue
        if anchor is None:
            samples.append(pv)
        elif pv["created_at"] > anchor:
            samples.append(pv)
        elif pv["created_at"] == anchor and anchor_seq is not None and pv["_seq"] > anchor_seq:
            # Same logical instant as the anchor but recorded after it.
            samples.append(pv)
    # most recent DRIFT_WINDOW_SIZE by created_at DESC, tie by insertion seq DESC
    samples.sort(key=lambda pv: (pv["created_at"], pv["_seq"]), reverse=True)
    samples = samples[:DRIFT_WINDOW_SIZE]
    if len(samples) < DRIFT_MIN_SAMPLES:
        return None
    total = sum(pv["variance_pct"] for pv in samples)
    mean = Decimal(total) / Decimal(len(samples))
    return round2(mean)


def hopper_serialize(h):
    out = serialize(h)
    out["drift_pct"] = dec_to_json(compute_drift_pct(h)) if compute_drift_pct(h) is not None else None
    return out


def line_serialize(line):
    out = serialize(line)
    out["posture"] = compute_posture(line)
    return out


def recipe_serialize(r):
    out = serialize(r)
    out["is_available"] = compute_is_available(r)
    return out


def batch_available(b):
    return num(b["quantity_grams"]) - num(b["allocated_grams"]) - num(b["consumed_grams"])


def batch_serialize(b):
    out = serialize(b)
    avail = batch_available(b)
    out["available_grams"] = dec_to_json(avail)
    q = num(b["quantity_grams"])
    consumed = num(b["consumed_grams"])
    allocated = num(b["allocated_grams"])
    if q > 0:
        utilized = round2(consumed / q * Decimal("100"))
        if b["status"] == "EXPIRED":
            waste = round2(avail / q * Decimal("100"))
        else:
            waste = round2((q - consumed - allocated - avail) / q * Decimal("100"))
    else:
        utilized = Decimal("0.00")
        waste = Decimal("0.00")
    out["utilized_pct"] = dec_to_json(utilized)
    out["waste_pct"] = dec_to_json(waste)
    if b["status"] == "EXPIRED":
        out["waste_pct_expired"] = dec_to_json(waste)
    return out


def labor_serialize(la):
    out = serialize(la)
    t = now()
    out["is_active"] = bool(la["window_start"] <= t <= la["window_end"])
    return out


def resolve_portions(recipe, customizations):
    """Return list of dicts: {ingredient_id, target_grams(Decimal), removed:bool}.
    Applies REMOVE (excluded), EXTRA (x1.5), SUBSTITUTE (resolve via active rule)."""
    cust_by_ing = {}
    for c in (customizations or []):
        cust_by_ing[c["ingredient_id"]] = c["action"]
    resolved = []
    for entry in recipe["portion_spec"]:
        iid = entry["ingredient_id"]
        action = cust_by_ing.get(iid)
        if action == "REMOVE":
            continue
        target = num(entry["target_grams"])
        if action == "EXTRA":
            target = target * EXTRA_MULTIPLIER
        eff_iid = iid
        if action == "SUBSTITUTE":
            rule = active_substitution_for(recipe["restaurant_id"], iid)
            if rule is not None:
                eff_iid = rule["to_ingredient_id"]
        resolved.append({"ingredient_id": eff_iid, "orig_ingredient_id": iid, "target_grams": target, "action": action})
    return resolved


def dispense_grams_for(target, coefficient):
    return round1(num(target) * num(coefficient))


def find_hopper_for_ingredient(line_id, ingredient_id):
    for h in db["hoppers"].values():
        if h["line_id"] == line_id and h["ingredient_id"] == ingredient_id:
            return h
    return None


def line_queue_count(line_id, before_dt=None, before_seq=None):
    cnt = 0
    for o in db["orders"].values():
        if o["assigned_line_id"] == line_id and o["status"] == "QUEUED":
            if before_dt is not None:
                if (o["queue_entered_at"], o["_seq"]) < (before_dt, before_seq):
                    cnt += 1
            else:
                cnt += 1
    return cnt


def compute_estimated_queue_seconds(order):
    line = db["assembly_lines"].get(order["assigned_line_id"])
    if line is None:
        return 0
    n = line_queue_count(order["assigned_line_id"], order["queue_entered_at"], order["_seq"])
    return int(n) * int(line["service_rate_seconds_per_bowl"])


def select_line(restaurant_id, route):
    candidates = []
    for line in db["assembly_lines"].values():
        if (line["restaurant_id"] == restaurant_id and line["line_type"] == route
                and line["status"] == "ACTIVE" and compute_posture(line) == "OPEN"):
            q = line_queue_count(line["id"])
            candidates.append((q, line["service_rate_seconds_per_bowl"], line["created_at"], line["_seq"], line))
    if not candidates:
        return None
    candidates.sort(key=lambda t: (t[0], t[1], t[2], t[3]))
    return candidates[0][4]


def depletion_forecast(hopper):
    """Return desired_ready_at datetime."""
    t = now()
    created = hopper["created_at"]
    minutes = Decimal(str(max((t - created).total_seconds(), 0))) / Decimal("60")
    if minutes < 1:
        minutes = Decimal("1")
    burn = num(hopper["cumulative_dispensed_grams"]) / minutes
    current = num(hopper["current_grams"])
    if burn == 0:
        minutes_to_empty = FORECAST_CAP_MINUTES
    else:
        minutes_to_empty = round2(current / burn)
        if minutes_to_empty == 0 and current > 0:
            minutes_to_empty = FORECAST_CAP_MINUTES
    wait = minutes_to_empty * SAFETY_FACTOR
    return t + timedelta(seconds=float(wait * 60))


def run_allocation_waterfall():
    pending = [t for t in db["refill_tasks"].values() if t["status"] == "SCHEDULED"]
    pending.sort(key=lambda t: (t.get("desired_ready_at") or t["created_at"], t["created_at"], t["_seq"]))
    for task in pending:
        hopper = db["hoppers"].get(task["hopper_id"])
        if hopper is None:
            continue
        restaurant_id = hopper_line_restaurant(hopper)
        cands = []
        for b in db["prep_batches"].values():
            if (b["restaurant_id"] == restaurant_id and b["ingredient_id"] == task["ingredient_id"]
                    and b["status"] == "READY" and b.get("expires_at") is not None
                    and b["expires_at"] > now() and batch_available(b) > 0):
                cands.append(b)
        if not cands:
            continue
        cands.sort(key=lambda b: (b["expires_at"], b["created_at"], b["_seq"]))
        batch = cands[0]
        alloc = min(num(task["requested_grams"]), batch_available(batch))
        alloc = round1(alloc)
        task["allocated_grams"] = alloc
        task["prep_batch_id"] = batch["id"]
        task["status"] = "READY"
        touch(task)
        batch["allocated_grams"] = num(batch["allocated_grams"]) + alloc
        touch(batch)
        if hopper["status"] == "DEPLETED":
            hopper["status"] = "REFILL_SCHEDULED"
            touch(hopper)


def hopper_line_restaurant(hopper):
    line = db["assembly_lines"].get(hopper["line_id"])
    return line["restaurant_id"] if line else None


def recompute_recipe_versions_for_ingredient(ingredient_id):
    """Bump version on recipes whose is_available changed. We recompute and bump if changed."""
    for r in db["recipes"].values():
        if any(e["ingredient_id"] == ingredient_id for e in r["portion_spec"]):
            prev = r.get("_last_is_available")
            cur = compute_is_available(r)
            if prev is None:
                r["_last_is_available"] = cur
            elif prev != cur:
                r["_last_is_available"] = cur
                touch(r)


def recompute_recipe_versions_for_restaurant(restaurant_id, ingredient_id=None):
    for r in db["recipes"].values():
        if r["restaurant_id"] != restaurant_id:
            continue
        if ingredient_id is not None and not any(e["ingredient_id"] == ingredient_id for e in r["portion_spec"]):
            continue
        prev = r.get("_last_is_available")
        cur = compute_is_available(r)
        if prev is None:
            r["_last_is_available"] = cur
        elif prev != cur:
            r["_last_is_available"] = cur
            touch(r)


def maybe_quarantine_hopper(hopper):
    """Recompute drift and fire quarantine cascade if needed."""
    d = compute_drift_pct(hopper)
    if d is None or abs(d) <= DRIFT_THRESHOLD_PCT:
        return
    if hopper["status"] != "IN_SERVICE":
        return
    hopper["status"] = "QUARANTINED"
    touch(hopper)
    line_id = hopper["line_id"]
    # force-reroute QUEUED AUTOMATED orders on this line whose recipe uses this ingredient
    for o in list(db["orders"].values()):
        if (o["assigned_line_id"] == line_id and o["route"] == "AUTOMATED" and o["status"] == "QUEUED"):
            recipe = db["recipes"].get(o["recipe_id"])
            if recipe is None:
                continue
            portions = resolve_portions(recipe, o.get("customizations") or [])
            if any(p["ingredient_id"] == hopper["ingredient_id"] for p in portions):
                o["route"] = "MANUAL"
                new_line = select_line(o["restaurant_id"], "MANUAL")
                if new_line is not None:
                    o["assigned_line_id"] = new_line["id"]
                o["estimated_queue_seconds"] = compute_estimated_queue_seconds(o)
                touch(o)


# ---------------------------------------------------------------------------
# Clock endpoint
# ---------------------------------------------------------------------------
@app.post("/api/_clock/set_current_utc")
def set_clock():
    uid, role = require_roles("OpsAdmin")
    body = get_body()
    dt = parse_dt(required(body, "to_iso8601"))
    CLOCK.set(dt)
    return ok_object({"current_utc": iso(CLOCK.now())})


# ---------------------------------------------------------------------------
# Restaurants
# ---------------------------------------------------------------------------
@app.post("/api/restaurants")
def create_restaurant():
    require_roles("OpsAdmin")
    body = get_body()
    name = required(body, "name")
    city = required(body, "city")
    if not isinstance(name, str) or not isinstance(city, str):
        raise err_validation("name and city must be strings")
    rec = {"name": name, "city": city}
    stamp_new(rec)
    db["restaurants"][rec["id"]] = rec
    return ok_object(serialize(rec), 201)


@app.get("/api/restaurants")
def list_restaurants():
    require_roles(*ROLES)
    limit, offset = parse_limit_offset()
    items = sorted(db["restaurants"].values(), key=lambda r: (r["created_at"], r["_seq"]))
    total = len(items)
    page = items[offset:offset + limit]
    return ok_list([serialize(x) for x in page], limit, offset, total)


@app.get("/api/restaurants/<rid>")
def get_restaurant(rid):
    require_roles(*ROLES)
    rec = db["restaurants"].get(rid)
    if rec is None:
        raise err_not_found()
    return ok_object(serialize(rec))


@app.get("/api/restaurants/<rid>/orders")
def list_restaurant_orders(rid):
    require_roles("OpsAdmin", "ShiftManager", "LineOperator", "QualityLead")
    rec = db["restaurants"].get(rid)
    if rec is None:
        raise err_not_found()
    limit, offset = parse_limit_offset()
    status = request.args.get("status")
    items = [o for o in db["orders"].values() if o["restaurant_id"] == rid]
    if status:
        items = [o for o in items if o["status"] == status]
    items.sort(key=lambda r: (r["created_at"], r["_seq"]))
    total = len(items)
    page = items[offset:offset + limit]
    return ok_list([serialize(x) for x in page], limit, offset, total)


@app.get("/api/restaurants/<rid>/throughput")
def restaurant_throughput(rid):
    require_roles("OpsAdmin", "ShiftManager")
    rec = db["restaurants"].get(rid)
    if rec is None:
        raise err_not_found()
    from_s = request.args.get("from_iso8601")
    to_s = request.args.get("to_iso8601")
    if from_s:
        w_start = parse_dt(from_s)
    else:
        w_start = STARTUP_CLOCK
    if to_s:
        w_end = parse_dt(to_s)
    else:
        w_end = now()
    window_seconds = (w_end - w_start).total_seconds()
    lines = [l for l in db["assembly_lines"].values() if l["restaurant_id"] == rid]
    lines.sort(key=lambda l: (l["created_at"], l["_seq"]))
    report = []
    for line in lines:
        completed = [o for o in db["orders"].values()
                     if o["assigned_line_id"] == line["id"] and o["status"] == "COMPLETED"
                     and o["completed_at"] is not None and w_start <= o["completed_at"] < w_end]
        completed.sort(key=lambda o: (o["completed_at"], o["created_at"], o["_seq"]))
        n = len(completed)
        if window_seconds > 0:
            bph = round2(Decimal(n) * Decimal("3600") / Decimal(str(window_seconds)))
        else:
            bph = Decimal("0.00")
        if n > 0:
            aq = [o["actual_queue_seconds"] for o in completed if o["actual_queue_seconds"] is not None]
            if aq:
                avg = round2(Decimal(sum(aq)) / Decimal(len(aq)))
                avg_int = int(avg.quantize(Decimal("1"), rounding=ROUND_HALF_UP))
            else:
                avg_int = None
        else:
            avg_int = None
        qtm = (avg_int is not None) and (avg_int <= QUEUE_TARGET_SECONDS)
        report.append({
            "line_id": line["id"],
            "bowls_per_hour": dec_to_json(bph),
            "avg_queue_seconds": avg_int,
            "queue_target_met": qtm,
            "orders_completed": n,
        })
    return ok_list(report, len(report), 0, len(report))


# ---------------------------------------------------------------------------
# Assembly lines
# ---------------------------------------------------------------------------
@app.post("/api/assembly-lines")
def create_line():
    require_roles("OpsAdmin")
    body = get_body()
    rid = required(body, "restaurant_id")
    name = required(body, "name")
    line_type = required(body, "line_type")
    if line_type not in ("AUTOMATED", "MANUAL"):
        raise err_validation("line_type must be AUTOMATED or MANUAL")
    rest = db["restaurants"].get(rid)
    if rest is None:
        raise err_not_found("restaurant not found")
    srate = body.get("service_rate_seconds_per_bowl")
    if srate is None:
        srate = 45 if line_type == "AUTOMATED" else 120
    if not isinstance(srate, int) or isinstance(srate, bool) or srate <= 0:
        raise err_validation("service_rate_seconds_per_bowl must be a positive integer")
    rec = {
        "restaurant_id": rid, "name": name, "line_type": line_type,
        "service_rate_seconds_per_bowl": srate,
        "status": "ACTIVE",
        "last_sanitation_completed_at": None,
        "next_sanitation_due_at": None,
    }
    stamp_new(rec)
    db["assembly_lines"][rec["id"]] = rec
    return ok_object(line_serialize(rec), 201)


@app.get("/api/assembly-lines")
def list_lines():
    require_roles("OpsAdmin", "ShiftManager", "LineOperator", "PrepCook", "QualityLead")
    limit, offset = parse_limit_offset()
    rid = request.args.get("restaurant_id")
    status = request.args.get("status")
    items = list(db["assembly_lines"].values())
    if rid:
        items = [l for l in items if l["restaurant_id"] == rid]
    if status:
        items = [l for l in items if l["status"] == status]
    items.sort(key=lambda r: (r["created_at"], r["_seq"]))
    total = len(items)
    page = items[offset:offset + limit]
    return ok_list([line_serialize(x) for x in page], limit, offset, total)


@app.get("/api/assembly-lines/<lid>")
def get_line(lid):
    require_roles("OpsAdmin", "ShiftManager", "LineOperator", "PrepCook", "QualityLead")
    rec = db["assembly_lines"].get(lid)
    if rec is None:
        raise err_not_found()
    return ok_object(line_serialize(rec))


@app.post("/api/assembly-lines/<lid>/pause")
def pause_line(lid):
    require_roles("ShiftManager")
    line = db["assembly_lines"].get(lid)
    if line is None:
        raise err_not_found()
    if line["status"] != "ACTIVE":
        raise err_invalid_state("line is not ACTIVE")
    # line-busy guard: no ASSEMBLING order
    for o in db["orders"].values():
        if o["assigned_line_id"] == lid and o["status"] == "ASSEMBLING":
            raise ApiError("ERR_LINE_BUSY", 409, "line hosts an in-flight order")
    for h in db["hoppers"].values():
        if h["line_id"] == lid and h["status"] == "REFILLING":
            raise ApiError("ERR_LINE_BUSY", 409, "line has a REFILLING hopper")
    line["status"] = "PAUSED"
    touch(line)
    return ok_object(line_serialize(line))


@app.post("/api/assembly-lines/<lid>/resume")
def resume_line(lid):
    require_roles("ShiftManager")
    line = db["assembly_lines"].get(lid)
    if line is None:
        raise err_not_found()
    if line["status"] != "PAUSED":
        raise err_invalid_state("line is not PAUSED")
    line["status"] = "ACTIVE"
    touch(line)
    return ok_object(line_serialize(line))


@app.get("/api/assembly-lines/<lid>/hoppers")
def list_line_hoppers(lid):
    require_roles("OpsAdmin", "ShiftManager", "LineOperator", "PrepCook", "QualityLead")
    line = db["assembly_lines"].get(lid)
    if line is None:
        raise err_not_found()
    limit, offset = parse_limit_offset()
    status = request.args.get("status")
    items = [h for h in db["hoppers"].values() if h["line_id"] == lid]
    if status:
        items = [h for h in items if h["status"] == status]
    items.sort(key=lambda r: (r["created_at"], r["_seq"]))
    total = len(items)
    page = items[offset:offset + limit]
    return ok_list([hopper_serialize(x) for x in page], limit, offset, total)


@app.get("/api/assembly-lines/<lid>/sanitation-cycles")
def list_line_cycles(lid):
    require_roles("OpsAdmin", "ShiftManager", "LineOperator", "QualityLead")
    line = db["assembly_lines"].get(lid)
    if line is None:
        raise err_not_found()
    limit, offset = parse_limit_offset()
    status = request.args.get("status")
    items = [c for c in db["sanitation_cycles"].values() if c["line_id"] == lid]
    if status:
        items = [c for c in items if c["status"] == status]
    items.sort(key=lambda r: (r["created_at"], r["_seq"]))
    total = len(items)
    page = items[offset:offset + limit]
    return ok_list([serialize(x) for x in page], limit, offset, total)


# ---------------------------------------------------------------------------
# Ingredients
# ---------------------------------------------------------------------------
@app.post("/api/ingredients")
def create_ingredient():
    require_roles("OpsAdmin")
    body = get_body()
    sku = required(body, "sku")
    name = required(body, "name")
    station_type = required(body, "station_type")
    shelf_life = required(body, "shelf_life_minutes")
    allergen = body.get("allergen_flag", False)
    if station_type not in ("BASE", "PROTEIN", "TOPPING", "DRESSING"):
        raise err_validation("invalid station_type")
    if not isinstance(shelf_life, int) or isinstance(shelf_life, bool) or shelf_life <= 0:
        raise err_validation("shelf_life_minutes must be a positive integer")
    if not isinstance(allergen, bool):
        raise err_validation("allergen_flag must be boolean")
    for ing in db["ingredients"].values():
        if ing["sku"] == sku:
            raise err_validation("sku must be unique")
    rec = {"sku": sku, "name": name, "station_type": station_type,
           "shelf_life_minutes": shelf_life, "allergen_flag": allergen, "status": "ACTIVE"}
    stamp_new(rec)
    db["ingredients"][rec["id"]] = rec
    return ok_object(serialize(rec), 201)


@app.get("/api/ingredients")
def list_ingredients():
    require_roles(*ROLES)
    limit, offset = parse_limit_offset()
    status = request.args.get("status")
    st = request.args.get("station_type")
    items = list(db["ingredients"].values())
    if status:
        items = [i for i in items if i["status"] == status]
    if st:
        items = [i for i in items if i["station_type"] == st]
    items.sort(key=lambda r: (r["created_at"], r["_seq"]))
    total = len(items)
    page = items[offset:offset + limit]
    return ok_list([serialize(x) for x in page], limit, offset, total)


@app.get("/api/ingredients/<iid>")
def get_ingredient(iid):
    require_roles(*ROLES)
    rec = db["ingredients"].get(iid)
    if rec is None:
        raise err_not_found()
    return ok_object(serialize(rec))


@app.post("/api/ingredients/<iid>/eighty-six")
def eighty_six(iid):
    require_roles("ShiftManager")
    rec = db["ingredients"].get(iid)
    if rec is None:
        raise err_not_found()
    if rec["status"] == "EIGHTY_SIXED":
        raise ApiError("ERR_ALREADY_EIGHTY_SIXED", 409, "ingredient already eighty-sixed")
    rec["status"] = "EIGHTY_SIXED"
    touch(rec)
    recompute_recipe_versions_for_ingredient(iid)
    return ok_object(serialize(rec))


@app.post("/api/ingredients/<iid>/restore")
def restore_ingredient(iid):
    require_roles("ShiftManager")
    rec = db["ingredients"].get(iid)
    if rec is None:
        raise err_not_found()
    if rec["status"] != "EIGHTY_SIXED":
        raise err_invalid_state("ingredient is not EIGHTY_SIXED")
    rec["status"] = "ACTIVE"
    touch(rec)
    recompute_recipe_versions_for_ingredient(iid)
    return ok_object(serialize(rec))


# ---------------------------------------------------------------------------
# Recipes
# ---------------------------------------------------------------------------
@app.post("/api/recipes")
def create_recipe():
    require_roles("OpsAdmin")
    body = get_body()
    rid = required(body, "restaurant_id")
    name = required(body, "name")
    base_complexity = body.get("base_complexity", 0)
    portion_spec = required(body, "portion_spec")
    rest = db["restaurants"].get(rid)
    if rest is None:
        raise err_not_found("restaurant not found")
    if not isinstance(base_complexity, int) or isinstance(base_complexity, bool) or base_complexity < 0:
        raise err_validation("base_complexity must be a non-negative integer")
    if not isinstance(portion_spec, list) or len(portion_spec) < 1:
        raise err_validation("portion_spec must contain at least 1 entry")
    seen = set()
    norm_spec = []
    for entry in portion_spec:
        if not isinstance(entry, dict) or "ingredient_id" not in entry or "target_grams" not in entry:
            raise err_validation("each portion_spec entry requires ingredient_id and target_grams")
        iid = entry["ingredient_id"]
        if iid in seen:
            raise err_validation("ingredient_ids in portion_spec must be distinct")
        seen.add(iid)
        if db["ingredients"].get(iid) is None:
            raise err_not_found("ingredient not found")
        tg = entry["target_grams"]
        if not isinstance(tg, (int, float)) or isinstance(tg, bool):
            raise err_validation("target_grams must be numeric")
        norm_spec.append({"ingredient_id": iid, "target_grams": tg})
    rec = {"restaurant_id": rid, "name": name, "base_complexity": base_complexity,
           "portion_spec": norm_spec}
    stamp_new(rec)
    rec["_last_is_available"] = compute_is_available(rec)
    db["recipes"][rec["id"]] = rec
    return ok_object(recipe_serialize(rec), 201)


@app.get("/api/recipes")
def list_recipes():
    require_roles(*ROLES)
    limit, offset = parse_limit_offset()
    rid = request.args.get("restaurant_id")
    avail = request.args.get("is_available")
    items = list(db["recipes"].values())
    if rid:
        items = [r for r in items if r["restaurant_id"] == rid]
    if avail is not None:
        want = avail.lower() == "true"
        items = [r for r in items if compute_is_available(r) == want]
    items.sort(key=lambda r: (r["created_at"], r["_seq"]))
    total = len(items)
    page = items[offset:offset + limit]
    return ok_list([recipe_serialize(x) for x in page], limit, offset, total)


@app.get("/api/recipes/<rid>")
def get_recipe(rid):
    require_roles(*ROLES)
    rec = db["recipes"].get(rid)
    if rec is None:
        raise err_not_found()
    return ok_object(recipe_serialize(rec))


@app.get("/api/recipes/<rid>/orders")
def list_recipe_orders(rid):
    require_roles("OpsAdmin", "ShiftManager", "LineOperator", "QualityLead")
    rec = db["recipes"].get(rid)
    if rec is None:
        raise err_not_found()
    limit, offset = parse_limit_offset()
    status = request.args.get("status")
    items = [o for o in db["orders"].values() if o["recipe_id"] == rid]
    if status:
        items = [o for o in items if o["status"] == status]
    items.sort(key=lambda r: (r["created_at"], r["_seq"]))
    total = len(items)
    page = items[offset:offset + limit]
    return ok_list([serialize(x) for x in page], limit, offset, total)


# ---------------------------------------------------------------------------
# Hoppers
# ---------------------------------------------------------------------------
@app.post("/api/hoppers")
def create_hopper():
    require_roles("OpsAdmin")
    body = get_body()
    line_id = required(body, "line_id")
    ingredient_id = required(body, "ingredient_id")
    capacity = required(body, "capacity_grams")
    station_slot = required(body, "station_slot")
    coefficient = body.get("calibration_coefficient", 1.0)
    line = db["assembly_lines"].get(line_id)
    if line is None:
        raise err_not_found("line not found")
    ing = db["ingredients"].get(ingredient_id)
    if ing is None:
        raise err_not_found("ingredient not found")
    if not isinstance(capacity, (int, float)) or isinstance(capacity, bool) or capacity <= 0:
        raise err_validation("capacity_grams must be > 0")
    if not isinstance(station_slot, int) or isinstance(station_slot, bool):
        raise err_validation("station_slot must be integer")
    if not isinstance(coefficient, (int, float)) or isinstance(coefficient, bool):
        raise err_validation("calibration_coefficient must be numeric")
    coef_d = Decimal(str(coefficient))
    if coef_d < Decimal("0.5") or coef_d > Decimal("2.0"):
        raise err_validation("calibration_coefficient out of range")
    if coef_d != coef_d.quantize(Decimal("0.001")):
        raise err_validation("calibration_coefficient must have at most 3 decimal places")
    # station slot map
    expected_station = STATION_SLOT_MAP.get(station_slot)
    if expected_station is None or expected_station != ing["station_type"]:
        raise ApiError("ERR_INGREDIENT_STATION_MISMATCH", 422, "station_slot inconsistent with ingredient station_type")
    # uniqueness of slot on line
    for h in db["hoppers"].values():
        if h["line_id"] == line_id and h["station_slot"] == station_slot:
            raise err_validation("station_slot must be unique per line")
    rec = {
        "line_id": line_id, "ingredient_id": ingredient_id,
        "capacity_grams": capacity, "station_slot": station_slot,
        "calibration_coefficient": coefficient,
        "status": "LOADING",
        "current_grams": Decimal("0"), "initial_load_grams": Decimal("0"),
        "cumulative_dispensed_grams": Decimal("0"),
        "cumulative_refilled_grams": Decimal("0"),
        "cumulative_waste_grams": Decimal("0"),
    }
    stamp_new(rec)
    rec["drift_window_anchor"] = rec["created_at"]
    rec["_drift_window_anchor_seq"] = rec["_seq"]
    db["hoppers"][rec["id"]] = rec
    return ok_object(hopper_serialize(rec), 201)


@app.get("/api/hoppers")
def list_hoppers():
    require_roles("OpsAdmin", "ShiftManager", "LineOperator", "PrepCook", "QualityLead")
    limit, offset = parse_limit_offset()
    line_id = request.args.get("line_id")
    ingredient_id = request.args.get("ingredient_id")
    status = request.args.get("status")
    items = list(db["hoppers"].values())
    if line_id:
        items = [h for h in items if h["line_id"] == line_id]
    if ingredient_id:
        items = [h for h in items if h["ingredient_id"] == ingredient_id]
    if status:
        items = [h for h in items if h["status"] == status]
    items.sort(key=lambda r: (r["created_at"], r["_seq"]))
    total = len(items)
    page = items[offset:offset + limit]
    return ok_list([hopper_serialize(x) for x in page], limit, offset, total)


@app.get("/api/hoppers/<hid>")
def get_hopper(hid):
    require_roles("OpsAdmin", "ShiftManager", "LineOperator", "PrepCook", "QualityLead")
    rec = db["hoppers"].get(hid)
    if rec is None:
        raise err_not_found()
    return ok_object(hopper_serialize(rec))


@app.post("/api/hoppers/<hid>/load")
def load_hopper(hid):
    require_roles("LineOperator")
    rec = db["hoppers"].get(hid)
    if rec is None:
        raise err_not_found()
    body = get_body()
    load_grams = required(body, "load_grams")
    if not isinstance(load_grams, (int, float)) or isinstance(load_grams, bool) or load_grams <= 0:
        raise err_validation("load_grams must be > 0")
    if rec["status"] not in ("LOADING", "DEPLETED"):
        raise err_invalid_state("hopper not in LOADING or DEPLETED")
    if num(rec["current_grams"]) + num(load_grams) > num(rec["capacity_grams"]):
        raise ApiError("ERR_HOPPER_CAPACITY_EXCEEDED", 422, "load would exceed capacity")
    ehv = body.get("expected_hopper_version")
    if ehv is not None and ehv != rec["version"]:
        raise ApiError("ERR_STALE_HOPPER_VERSION", 412, "stale hopper version")
    rec["current_grams"] = num(rec["current_grams"]) + num(load_grams)
    rec["initial_load_grams"] = rec["current_grams"]
    rec["status"] = "IN_SERVICE"
    touch(rec)
    return ok_object(hopper_serialize(rec))


@app.post("/api/hoppers/<hid>/sensor-reading")
def sensor_reading(hid):
    require_roles("LineOperator")
    rec = db["hoppers"].get(hid)
    if rec is None:
        raise err_not_found()
    body = get_body()
    reading = required(body, "grams_reading")
    if not isinstance(reading, (int, float)) or isinstance(reading, bool):
        raise err_validation("grams_reading must be numeric")
    if rec["status"] != "IN_SERVICE":
        raise err_invalid_state("hopper not IN_SERVICE")
    if num(reading) < 0 or num(reading) > num(rec["capacity_grams"]):
        raise ApiError("ERR_SENSOR_READING_OUT_OF_RANGE", 422, "grams_reading out of range")
    rec["current_grams"] = num(reading)
    touch(rec)
    if num(reading) <= Decimal(str(HOPPER_DEPLETION_THRESHOLD)):
        rec["status"] = "DEPLETED"
        # auto-create refill task if none active
        has_active = any(t for t in db["refill_tasks"].values()
                         if t["hopper_id"] == hid and t["status"] in ("SCHEDULED", "READY", "IN_PROGRESS"))
        if not has_active:
            # Auto-created refills always use FORECAST mode (PRD §3.4).
            requested = forecast_requested_grams(rec)
            task = {
                "hopper_id": hid,
                "ingredient_id": rec["ingredient_id"],
                "requested_grams": requested,
                "allocated_grams": Decimal("0"),
                "prep_batch_id": None,
                "desired_ready_at": depletion_forecast(rec),
                "auto_created": True,
                "status": "SCHEDULED",
            }
            stamp_new(task)
            db["refill_tasks"][task["id"]] = task
            run_allocation_waterfall()
    return ok_object(hopper_serialize(rec))


@app.post("/api/hoppers/<hid>/calibration-adjustments")
def create_calibration_adjustment(hid):
    uid, role = require_roles("QualityLead")
    rec = db["hoppers"].get(hid)
    if rec is None:
        raise err_not_found()
    if rec["status"] != "QUARANTINED":
        raise err_invalid_state("hopper not QUARANTINED")
    body = get_body()
    new_coef = required(body, "new_coefficient")
    if not isinstance(new_coef, (int, float)) or isinstance(new_coef, bool):
        raise err_validation("new_coefficient must be numeric")
    nc = Decimal(str(new_coef))
    if nc < Decimal("0.5") or nc > Decimal("2.0"):
        raise err_validation("new_coefficient out of range")
    if nc != nc.quantize(Decimal("0.001")):
        raise err_validation("new_coefficient must have at most 3 decimal places")
    # segregation of duties
    pvs = [pv for pv in db["portion_verifications"].values() if pv["hopper_id"] == hid]
    if pvs:
        pvs.sort(key=lambda pv: (pv["created_at"], pv["_seq"]))
        most_recent = pvs[-1]
        if most_recent["recorded_by_user_id"] == uid:
            raise ApiError("ERR_SEGREGATION_OF_DUTIES", 403, "approver cannot be the recording verifier")
    drift_obs = compute_drift_pct(rec)
    adj = {
        "hopper_id": hid,
        "old_coefficient": num(rec["calibration_coefficient"]),
        "new_coefficient": nc,
        "drift_pct_observed": drift_obs,
        "approved_by_user_id": uid,
        "adjusted_at": now(),
    }
    adj["id"] = new_id()
    adj["created_at"] = now()
    adj["_seq"] = next_seq()
    db["calibration_adjustments"][adj["id"]] = adj
    rec["calibration_coefficient"] = new_coef
    rec["drift_window_anchor"] = now()
    rec["_drift_window_anchor_seq"] = adj["_seq"]
    rec["status"] = "IN_SERVICE"
    touch(rec)
    return ok_object(serialize(adj), 201)


@app.get("/api/hoppers/<hid>/calibration-adjustments")
def list_calibration_adjustments(hid):
    require_roles("OpsAdmin", "ShiftManager", "LineOperator", "QualityLead")
    rec = db["hoppers"].get(hid)
    if rec is None:
        raise err_not_found()
    limit, offset = parse_limit_offset()
    items = [a for a in db["calibration_adjustments"].values() if a["hopper_id"] == hid]
    items.sort(key=lambda r: (r["created_at"], r["_seq"]))
    total = len(items)
    page = items[offset:offset + limit]
    return ok_list([serialize(x) for x in page], limit, offset, total)


@app.get("/api/hoppers/<hid>/portion-verifications")
def list_hopper_pvs(hid):
    require_roles("OpsAdmin", "ShiftManager", "LineOperator", "QualityLead")
    rec = db["hoppers"].get(hid)
    if rec is None:
        raise err_not_found()
    limit, offset = parse_limit_offset()
    items = [pv for pv in db["portion_verifications"].values() if pv["hopper_id"] == hid]
    items.sort(key=lambda r: (r["created_at"], r["_seq"]))
    total = len(items)
    page = items[offset:offset + limit]
    return ok_list([serialize(x) for x in page], limit, offset, total)


@app.get("/api/hoppers/<hid>/refill-tasks")
def list_hopper_refill_tasks(hid):
    require_roles("OpsAdmin", "ShiftManager", "LineOperator", "PrepCook", "QualityLead")
    rec = db["hoppers"].get(hid)
    if rec is None:
        raise err_not_found()
    limit, offset = parse_limit_offset()
    status = request.args.get("status")
    items = [t for t in db["refill_tasks"].values() if t["hopper_id"] == hid]
    if status:
        items = [t for t in items if t["status"] == status]
    items.sort(key=lambda r: (r["created_at"], r["_seq"]))
    total = len(items)
    page = items[offset:offset + limit]
    return ok_list([serialize(x) for x in page], limit, offset, total)


def forecast_requested_grams(hopper):
    """FORECAST mode: min(capacity - current, committed queued demand for the
    hopper's ingredient on its line), 1 decimal place round-half-up."""
    demand = Decimal("0")
    for o in db["orders"].values():
        if o["assigned_line_id"] == hopper["line_id"] and o["status"] == "QUEUED":
            recipe = db["recipes"].get(o["recipe_id"])
            if recipe is None:
                continue
            portions = resolve_portions(recipe, o.get("customizations") or [])
            for p in portions:
                if p["ingredient_id"] == hopper["ingredient_id"]:
                    demand += dispense_grams_for(p["target_grams"], hopper["calibration_coefficient"])
    return round1(min(num(hopper["capacity_grams"]) - num(hopper["current_grams"]), demand))


# ---------------------------------------------------------------------------
# Refill tasks
# ---------------------------------------------------------------------------
@app.post("/api/refill-tasks")
def create_refill_task():
    require_roles("LineOperator", "ShiftManager")
    body = get_body()
    hopper_id = required(body, "hopper_id")
    mode = required(body, "mode")
    if mode not in ("STANDARD", "FORECAST"):
        raise err_validation("mode must be STANDARD or FORECAST")
    hopper = db["hoppers"].get(hopper_id)
    if hopper is None:
        raise err_not_found("hopper not found")
    line = db["assembly_lines"].get(hopper["line_id"])
    if mode == "STANDARD":
        requested = round1(num(hopper["capacity_grams"]) - num(hopper["current_grams"]))
    else:
        requested = forecast_requested_grams(hopper)
    # daily refill budget
    rid = line["restaurant_id"]
    today = now().date()
    spent = Decimal("0")
    for t in db["refill_tasks"].values():
        h2 = db["hoppers"].get(t["hopper_id"])
        if h2 is None:
            continue
        l2 = db["assembly_lines"].get(h2["line_id"])
        if l2 is None or l2["restaurant_id"] != rid:
            continue
        if t["created_at"].date() == today:
            spent += num(t["allocated_grams"])
    if spent + requested > DAILY_REFILL_BUDGET_GRAMS:
        raise ApiError("ERR_REFILL_BUDGET_EXCEEDED", 402, "daily refill budget exceeded")
    task = {
        "hopper_id": hopper_id,
        "ingredient_id": hopper["ingredient_id"],
        "requested_grams": requested,
        "allocated_grams": Decimal("0"),
        "prep_batch_id": None,
        "desired_ready_at": depletion_forecast(hopper),
        "auto_created": False,
        "status": "SCHEDULED",
    }
    stamp_new(task)
    db["refill_tasks"][task["id"]] = task
    run_allocation_waterfall()
    return ok_object(serialize(task), 201)


@app.get("/api/refill-tasks")
def list_refill_tasks():
    require_roles("OpsAdmin", "ShiftManager", "LineOperator", "PrepCook", "QualityLead")
    limit, offset = parse_limit_offset()
    hopper_id = request.args.get("hopper_id")
    ingredient_id = request.args.get("ingredient_id")
    prep_batch_id = request.args.get("prep_batch_id")
    status = request.args.get("status")
    items = list(db["refill_tasks"].values())
    if hopper_id:
        items = [t for t in items if t["hopper_id"] == hopper_id]
    if ingredient_id:
        items = [t for t in items if t["ingredient_id"] == ingredient_id]
    if prep_batch_id:
        items = [t for t in items if t.get("prep_batch_id") == prep_batch_id]
    if status:
        items = [t for t in items if t["status"] == status]
    items.sort(key=lambda r: (r["created_at"], r["_seq"]))
    total = len(items)
    page = items[offset:offset + limit]
    return ok_list([serialize(x) for x in page], limit, offset, total)


@app.get("/api/refill-tasks/<tid>")
def get_refill_task(tid):
    require_roles("OpsAdmin", "ShiftManager", "LineOperator", "PrepCook", "QualityLead")
    rec = db["refill_tasks"].get(tid)
    if rec is None:
        raise err_not_found()
    return ok_object(serialize(rec))


@app.post("/api/refill-tasks/<tid>/start")
def start_refill_task(tid):
    require_roles("LineOperator")
    task = db["refill_tasks"].get(tid)
    if task is None:
        raise err_not_found()
    if task["status"] != "READY":
        raise err_invalid_state("task not READY")
    hopper = db["hoppers"].get(task["hopper_id"])
    batch = db["prep_batches"].get(task.get("prep_batch_id"))
    if batch is None or batch["status"] != "READY" or batch.get("expires_at") is None or batch["expires_at"] <= now():
        raise ApiError("ERR_PREP_BATCH_EXPIRED", 422, "allocated batch no longer usable")
    if hopper is None or hopper["status"] != "REFILL_SCHEDULED":
        raise err_invalid_state("hopper not REFILL_SCHEDULED")
    line = db["assembly_lines"].get(hopper["line_id"])
    if line is None or line["status"] != "ACTIVE":
        raise err_invalid_state("line not ACTIVE")
    task["status"] = "IN_PROGRESS"
    touch(task)
    hopper["status"] = "REFILLING"
    touch(hopper)
    return ok_object(serialize(task))


@app.post("/api/refill-tasks/<tid>/complete")
def complete_refill_task(tid):
    require_roles("LineOperator")
    task = db["refill_tasks"].get(tid)
    if task is None:
        raise err_not_found()
    if task["status"] != "IN_PROGRESS":
        raise err_invalid_state("task not IN_PROGRESS")
    hopper = db["hoppers"].get(task["hopper_id"])
    if hopper is None or hopper["status"] != "REFILLING":
        raise err_invalid_state("hopper not REFILLING")
    batch = db["prep_batches"].get(task.get("prep_batch_id"))
    alloc = num(task["allocated_grams"])
    hopper["current_grams"] = num(hopper["current_grams"]) + alloc
    hopper["cumulative_refilled_grams"] = num(hopper["cumulative_refilled_grams"]) + alloc
    hopper["status"] = "IN_SERVICE"
    touch(hopper)
    if batch is not None:
        batch["allocated_grams"] = num(batch["allocated_grams"]) - alloc
        batch["consumed_grams"] = num(batch["consumed_grams"]) + alloc
        if batch_available(batch) == 0 and num(batch["allocated_grams"]) == 0:
            if batch["status"] == "READY":
                batch["status"] = "CONSUMED"
        touch(batch)
    task["status"] = "COMPLETED"
    touch(task)
    return ok_object(serialize(task))


@app.post("/api/refill-tasks/<tid>/cancel")
def cancel_refill_task(tid):
    require_roles("ShiftManager")
    task = db["refill_tasks"].get(tid)
    if task is None:
        raise err_not_found()
    if task["status"] not in ("SCHEDULED", "READY"):
        raise err_invalid_state("task not SCHEDULED or READY")
    hopper = db["hoppers"].get(task["hopper_id"])
    if task.get("prep_batch_id"):
        batch = db["prep_batches"].get(task["prep_batch_id"])
        if batch is not None:
            batch["allocated_grams"] = num(batch["allocated_grams"]) - num(task["allocated_grams"])
            touch(batch)
    task["status"] = "CANCELLED"
    touch(task)
    if hopper is not None and hopper["status"] == "REFILL_SCHEDULED":
        hopper["status"] = "DEPLETED"
        touch(hopper)
    return ok_object(serialize(task))


# ---------------------------------------------------------------------------
# Prep batches
# ---------------------------------------------------------------------------
@app.post("/api/prep-batches")
def create_prep_batch():
    require_roles("PrepCook")
    body = get_body()
    rid = required(body, "restaurant_id")
    iid = required(body, "ingredient_id")
    qty = required(body, "quantity_grams")
    if db["restaurants"].get(rid) is None:
        raise err_not_found("restaurant not found")
    if db["ingredients"].get(iid) is None:
        raise err_not_found("ingredient not found")
    if not isinstance(qty, (int, float)) or isinstance(qty, bool) or qty <= 0:
        raise err_validation("quantity_grams must be > 0")
    rec = {
        "restaurant_id": rid, "ingredient_id": iid,
        "quantity_grams": qty,
        "allocated_grams": Decimal("0"), "consumed_grams": Decimal("0"),
        "status": "IN_PREP",
        "ready_at": None, "expires_at": None,
    }
    stamp_new(rec)
    db["prep_batches"][rec["id"]] = rec
    return ok_object(batch_serialize(rec), 201)


@app.get("/api/prep-batches")
def list_prep_batches():
    require_roles("OpsAdmin", "ShiftManager", "LineOperator", "PrepCook", "QualityLead")
    limit, offset = parse_limit_offset()
    rid = request.args.get("restaurant_id")
    iid = request.args.get("ingredient_id")
    status = request.args.get("status")
    items = list(db["prep_batches"].values())
    if rid:
        items = [b for b in items if b["restaurant_id"] == rid]
    if iid:
        items = [b for b in items if b["ingredient_id"] == iid]
    if status:
        items = [b for b in items if b["status"] == status]
    items.sort(key=lambda r: (r["created_at"], r["_seq"]))
    total = len(items)
    page = items[offset:offset + limit]
    return ok_list([batch_serialize(x) for x in page], limit, offset, total)


@app.get("/api/prep-batches/<bid>")
def get_prep_batch(bid):
    require_roles("OpsAdmin", "ShiftManager", "LineOperator", "PrepCook", "QualityLead")
    rec = db["prep_batches"].get(bid)
    if rec is None:
        raise err_not_found()
    return ok_object(batch_serialize(rec))


@app.post("/api/prep-batches/expire-sweep")
def expire_sweep():
    require_roles("ShiftManager")
    expired_ids = []
    t = now()
    for b in list(db["prep_batches"].values()):
        if b["status"] == "READY" and b.get("expires_at") is not None and b["expires_at"] <= t:
            # release READY tasks allocated from this batch
            for task in db["refill_tasks"].values():
                if task.get("prep_batch_id") == b["id"] and task["status"] == "READY":
                    b["allocated_grams"] = num(b["allocated_grams"]) - num(task["allocated_grams"])
                    task["allocated_grams"] = Decimal("0")
                    task["prep_batch_id"] = None
                    task["status"] = "SCHEDULED"
                    touch(task)
                    hopper = db["hoppers"].get(task["hopper_id"])
                    if hopper is not None and hopper["status"] == "REFILL_SCHEDULED":
                        hopper["status"] = "DEPLETED"
                        touch(hopper)
            b["status"] = "EXPIRED"
            touch(b)
            expired_ids.append(b["id"])
    if expired_ids:
        run_allocation_waterfall()
    return ok_object({"expired_count": len(expired_ids), "expired_batch_ids": expired_ids})


@app.post("/api/prep-batches/<bid>/mark-ready")
def mark_ready(bid):
    require_roles("PrepCook")
    rec = db["prep_batches"].get(bid)
    if rec is None:
        raise err_not_found()
    if rec["status"] != "IN_PREP":
        raise err_invalid_state("batch not IN_PREP")
    ing = db["ingredients"].get(rec["ingredient_id"])
    rec["ready_at"] = now()
    rec["expires_at"] = now() + timedelta(minutes=ing["shelf_life_minutes"])
    rec["status"] = "READY"
    touch(rec)
    run_allocation_waterfall()
    return ok_object(batch_serialize(rec))


# ---------------------------------------------------------------------------
# Orders
# ---------------------------------------------------------------------------
def order_serialize(o):
    return serialize(o)


@app.post("/api/orders")
def create_order():
    uid, role = require_roles("Customer")
    body = get_body()
    rid = required(body, "restaurant_id")
    recipe_id = required(body, "recipe_id")
    customizations = body.get("customizations", [])
    if db["restaurants"].get(rid) is None:
        raise err_not_found("restaurant not found")
    recipe = db["recipes"].get(recipe_id)
    if recipe is None:
        raise err_not_found("recipe not found")
    if not isinstance(customizations, list):
        raise err_validation("customizations must be an array")
    # validate customizations
    portion_ids = {e["ingredient_id"] for e in recipe["portion_spec"]}
    seen = set()
    for c in customizations:
        if not isinstance(c, dict) or "ingredient_id" not in c or "action" not in c:
            raise ApiError("ERR_INVALID_CUSTOMIZATION", 422, "invalid customization entry")
        iid = c["ingredient_id"]
        action = c["action"]
        if action not in ("EXTRA", "REMOVE", "SUBSTITUTE"):
            raise ApiError("ERR_INVALID_CUSTOMIZATION", 422, "invalid customization action")
        if iid in seen:
            raise ApiError("ERR_INVALID_CUSTOMIZATION", 422, "duplicate customization for ingredient")
        seen.add(iid)
        if db["ingredients"].get(iid) is None:
            raise err_not_found("ingredient not found")
        if action in ("EXTRA", "REMOVE"):
            if iid not in portion_ids:
                raise ApiError("ERR_INVALID_CUSTOMIZATION", 422, "customization ingredient not in portion_spec")
        else:  # SUBSTITUTE
            rule = active_substitution_for(recipe["restaurant_id"], iid)
            if rule is None:
                raise ApiError("ERR_INVALID_CUSTOMIZATION", 422, "no active substitution for ingredient")
    # complexity score
    score = recipe["base_complexity"]
    for c in customizations:
        if c["action"] == "EXTRA":
            score += 1
        elif c["action"] == "REMOVE":
            score += 2
        elif c["action"] == "SUBSTITUTE":
            score += 3
        ing = db["ingredients"].get(c["ingredient_id"])
        if ing is not None and ing.get("allergen_flag"):
            score += 2
    route = "AUTOMATED" if score <= ROUTING_THRESHOLD else "MANUAL"
    # eligible line
    line = select_line(rid, route)
    if line is None:
        raise ApiError("ERR_NO_LINE_AVAILABLE", 422, "no eligible line for route")
    # recipe availability
    if not compute_is_available(recipe):
        raise ApiError("ERR_RECIPE_UNAVAILABLE", 422, "recipe is not available")
    # OCC
    erv = body.get("expected_recipe_version")
    if erv is not None and erv != recipe["version"]:
        raise ApiError("ERR_STALE_RECIPE_VERSION", 412, "stale recipe version")
    rec = {
        "restaurant_id": rid, "recipe_id": recipe_id,
        "customizations": customizations,
        "complexity_score": score,
        "route": route,
        "assigned_line_id": line["id"],
        "status": "QUEUED",
        "queue_entered_at": now(),
        "started_at": None, "completed_at": None,
        "remake_count": 0,
        "expected_total_grams": Decimal("0"),
        "estimated_queue_seconds": 0,
        "actual_queue_seconds": None,
        "_dispense_snapshot": None,
        "_customer_user_id": uid,
    }
    stamp_new(rec)
    rec["estimated_queue_seconds"] = compute_estimated_queue_seconds(rec)
    db["orders"][rec["id"]] = rec
    return ok_object(order_serialize(rec), 201)


@app.get("/api/orders")
def list_orders():
    require_roles("OpsAdmin", "ShiftManager", "LineOperator", "QualityLead")
    limit, offset = parse_limit_offset()
    rid = request.args.get("restaurant_id")
    recipe_id = request.args.get("recipe_id")
    line_id = request.args.get("assigned_line_id")
    status = request.args.get("status")
    items = list(db["orders"].values())
    if rid:
        items = [o for o in items if o["restaurant_id"] == rid]
    if recipe_id:
        items = [o for o in items if o["recipe_id"] == recipe_id]
    if line_id:
        items = [o for o in items if o["assigned_line_id"] == line_id]
    if status:
        items = [o for o in items if o["status"] == status]
    items.sort(key=lambda r: (r["created_at"], r["_seq"]))
    total = len(items)
    page = items[offset:offset + limit]
    return ok_list([order_serialize(x) for x in page], limit, offset, total)


@app.get("/api/orders/<oid>")
def get_order(oid):
    require_roles(*ROLES)
    rec = db["orders"].get(oid)
    if rec is None:
        raise err_not_found()
    return ok_object(order_serialize(rec))


@app.post("/api/orders/<oid>/start-assembly")
def start_assembly(oid):
    require_roles("LineOperator")
    order = db["orders"].get(oid)
    if order is None:
        raise err_not_found()
    if order["status"] != "QUEUED":
        raise err_invalid_state("order not QUEUED")
    line = db["assembly_lines"].get(order["assigned_line_id"])
    if line is None:
        raise err_not_found("line not found")
    if compute_posture(line) != "OPEN":
        raise ApiError("ERR_LINE_NOT_OPEN", 409, "line posture is not OPEN")
    recipe = db["recipes"].get(order["recipe_id"])
    if recipe is None:
        raise err_not_found("recipe not found")
    portions = resolve_portions(recipe, order.get("customizations") or [])
    # check availability & compute dispenses
    dispenses = []  # list of (hopper or None, ingredient, dispense_grams)
    for p in portions:
        ing = db["ingredients"].get(p["ingredient_id"])
        if ing is None:
            raise err_not_found("ingredient not found")
        if ing["status"] == "EIGHTY_SIXED":
            raise ApiError("ERR_RECIPE_UNAVAILABLE", 422, "ingredient eighty-sixed")
        if order["route"] == "AUTOMATED":
            hopper = find_hopper_for_ingredient(line["id"], p["ingredient_id"])
            if hopper is None or hopper["status"] != "IN_SERVICE":
                raise err_invalid_state("no IN_SERVICE hopper for ingredient")
            dg = dispense_grams_for(p["target_grams"], hopper["calibration_coefficient"])
            if num(hopper["current_grams"]) < dg:
                raise err_invalid_state("insufficient hopper grams")
            dispenses.append((hopper, p["ingredient_id"], dg))
        else:
            dispenses.append((None, p["ingredient_id"], round1(num(p["target_grams"]))))
    # commit dispenses (AUTOMATED only)
    if order["route"] == "AUTOMATED":
        for hopper, iid, dg in dispenses:
            hopper["current_grams"] = num(hopper["current_grams"]) - dg
            hopper["cumulative_dispensed_grams"] = num(hopper["cumulative_dispensed_grams"]) + dg
            touch(hopper)
    t = now()
    order["started_at"] = t
    order["actual_queue_seconds"] = int(round((t - order["queue_entered_at"]).total_seconds()))
    order["status"] = "ASSEMBLING"
    order["_dispense_snapshot"] = [
        {"hopper_id": (h["id"] if h else None), "ingredient_id": iid, "dispense_grams": dg}
        for (h, iid, dg) in dispenses
    ]
    touch(order)
    return ok_object(order_serialize(order))


@app.post("/api/orders/<oid>/submit-verification")
def submit_verification(oid):
    uid, role = require_roles("LineOperator")
    order = db["orders"].get(oid)
    if order is None:
        raise err_not_found()
    if order["status"] != "ASSEMBLING":
        raise err_invalid_state("order not ASSEMBLING")
    body = get_body()
    measurements = required(body, "measurements")
    if not isinstance(measurements, list):
        raise ApiError("ERR_VERIFICATION_MISMATCH", 422, "measurements must be an array")
    snapshot = order.get("_dispense_snapshot") or []
    expected_hopper_ids = {s["hopper_id"] for s in snapshot if s["hopper_id"] is not None}
    got_hopper_ids = set()
    for m in measurements:
        if not isinstance(m, dict) or "hopper_id" not in m or "actual_grams" not in m:
            raise ApiError("ERR_VERIFICATION_MISMATCH", 422, "invalid measurement entry")
        got_hopper_ids.add(m["hopper_id"])
    if got_hopper_ids != expected_hopper_ids:
        raise ApiError("ERR_VERIFICATION_MISMATCH", 422, "measurements must exactly cover dispensed hopper set")
    # build verifications
    created_pvs = []
    total_expected = Decimal("0")
    for s in snapshot:
        total_expected += num(s["dispense_grams"])
    order["expected_total_grams"] = total_expected
    failed = []
    for s in snapshot:
        hid = s["hopper_id"]
        if hid is None:
            continue
        m = next(m for m in measurements if m["hopper_id"] == hid)
        actual = m["actual_grams"]
        if not isinstance(actual, (int, float)) or isinstance(actual, bool) or num(actual) < 0:
            raise ApiError("ERR_VERIFICATION_MISMATCH", 422, "actual_grams must be >= 0")
        expected = num(s["dispense_grams"])
        if expected == 0:
            raise ApiError("ERR_VERIFICATION_MISMATCH", 422, "expected_grams is zero")
        variance = round2((num(actual) - expected) / expected * Decimal("100"))
        result = "PASS" if abs(variance) <= PORTION_TOLERANCE_PCT else "FAIL"
        pv = {
            "order_id": oid,
            "hopper_id": hid,
            "ingredient_id": s["ingredient_id"],
            "expected_grams": expected,
            "actual_grams": num(actual),
            "variance_pct": variance,
            "result": result,
            "recorded_by_user_id": uid,
        }
        pv["id"] = new_id()
        pv["created_at"] = now()
        pv["_seq"] = next_seq()
        db["portion_verifications"][pv["id"]] = pv
        created_pvs.append(pv)
        if result == "FAIL":
            failed.append((s, pv))
    # transition
    order["status"] = "VERIFICATION"
    t = now()
    if not failed:
        order["status"] = "COMPLETED"
        order["completed_at"] = t
        touch(order)
    else:
        if order["remake_count"] < REMAKE_LIMIT:
            order["remake_count"] += 1
            order["queue_entered_at"] = t
            order["started_at"] = None
            order["actual_queue_seconds"] = None
            order["_seq"] = next_seq()  # re-queued at back
            order["status"] = "QUEUED"
            order["estimated_queue_seconds"] = compute_estimated_queue_seconds(order)
        else:
            order["status"] = "CANCELLED"
        # waste reclassification for each failed measurement
        for s, pv in failed:
            hopper = db["hoppers"].get(s["hopper_id"])
            if hopper is None:
                continue
            expected = num(s["dispense_grams"])
            hopper["cumulative_dispensed_grams"] = num(hopper["cumulative_dispensed_grams"]) - expected
            hopper["cumulative_waste_grams"] = num(hopper["cumulative_waste_grams"]) + expected
            touch(hopper)
        touch(order)
    # drift recompute + quarantine cascade per involved hopper
    involved = {s["hopper_id"] for s in snapshot if s["hopper_id"] is not None}
    for hid in involved:
        hopper = db["hoppers"].get(hid)
        if hopper is not None:
            maybe_quarantine_hopper(hopper)
    return ok_object(order_serialize(order))


@app.post("/api/orders/<oid>/cancel")
def cancel_order(oid):
    uid, role = require_roles("Customer")
    order = db["orders"].get(oid)
    if order is None:
        raise err_not_found()
    if order["status"] != "QUEUED":
        raise err_invalid_state("order not QUEUED")
    order["status"] = "CANCELLED"
    touch(order)
    # recompute estimates on the line
    for o in db["orders"].values():
        if o["assigned_line_id"] == order["assigned_line_id"] and o["status"] == "QUEUED":
            new_est = compute_estimated_queue_seconds(o)
            if new_est != o["estimated_queue_seconds"]:
                o["estimated_queue_seconds"] = new_est
    return ok_object(order_serialize(order))


@app.post("/api/orders/<oid>/reroute")
def reroute_order(oid):
    require_roles("ShiftManager")
    order = db["orders"].get(oid)
    if order is None:
        raise err_not_found()
    if order["status"] != "QUEUED":
        raise err_invalid_state("order not QUEUED")
    body = get_body()
    target_route = required(body, "target_route")
    target_line_id = body.get("target_line_id")
    if target_route not in ("AUTOMATED", "MANUAL"):
        raise err_validation("target_route must be AUTOMATED or MANUAL")
    if target_route == order["route"]:
        raise err_validation("target_route must differ from current route")
    if target_line_id is not None:
        line = db["assembly_lines"].get(target_line_id)
        if line is None:
            raise err_not_found("target line not found")
        if line["restaurant_id"] != order["restaurant_id"]:
            raise err_validation("target line not at order's restaurant")
        if line["line_type"] != target_route:
            raise err_validation("target line_type does not match target_route")
        if compute_posture(line) != "OPEN":
            raise ApiError("ERR_LINE_NOT_OPEN", 409, "target line posture not OPEN")
    else:
        line = select_line(order["restaurant_id"], target_route)
        if line is None:
            raise ApiError("ERR_NO_LINE_AVAILABLE", 422, "no eligible line for target route")
    order["route"] = target_route
    order["assigned_line_id"] = line["id"]
    order["queue_entered_at"] = now()
    order["_seq"] = next_seq()
    order["estimated_queue_seconds"] = compute_estimated_queue_seconds(order)
    touch(order)
    return ok_object(order_serialize(order))


@app.get("/api/orders/<oid>/portion-verifications")
def list_order_pvs(oid):
    require_roles("OpsAdmin", "ShiftManager", "LineOperator", "QualityLead")
    rec = db["orders"].get(oid)
    if rec is None:
        raise err_not_found()
    limit, offset = parse_limit_offset()
    items = [pv for pv in db["portion_verifications"].values() if pv["order_id"] == oid]
    items.sort(key=lambda r: (r["created_at"], r["_seq"]))
    total = len(items)
    page = items[offset:offset + limit]
    return ok_list([serialize(x) for x in page], limit, offset, total)


# ---------------------------------------------------------------------------
# Substitution rules
# ---------------------------------------------------------------------------
def window_overlap(a_start, a_end, b_start, b_end):
    return a_start < b_end and b_start < a_end


@app.post("/api/substitution-rules")
def create_substitution_rule():
    require_roles("OpsAdmin")
    body = get_body()
    rid = required(body, "restaurant_id")
    from_id = required(body, "from_ingredient_id")
    to_id = required(body, "to_ingredient_id")
    eff_start = parse_dt(required(body, "effective_start"))
    eff_end = parse_dt(required(body, "effective_end"))
    if db["restaurants"].get(rid) is None:
        raise err_not_found("restaurant not found")
    if db["ingredients"].get(from_id) is None:
        raise err_not_found("from_ingredient not found")
    if db["ingredients"].get(to_id) is None:
        raise err_not_found("to_ingredient not found")
    if from_id == to_id:
        raise ApiError("ERR_SUBSTITUTION_CONFLICT", 422, "from and to ingredients must differ")
    if eff_end <= eff_start:
        raise ApiError("ERR_SUBSTITUTION_CONFLICT", 422, "effective_end must be strictly after effective_start")
    to_ing = db["ingredients"][to_id]
    if to_ing["status"] != "ACTIVE":
        raise ApiError("ERR_SUBSTITUTION_CONFLICT", 422, "to_ingredient must be ACTIVE")
    for r in db["substitution_rules"].values():
        if (r["restaurant_id"] == rid and r["from_ingredient_id"] == from_id and r["status"] == "ACTIVE"
                and window_overlap(eff_start, eff_end, r["effective_start"], r["effective_end"])):
            raise ApiError("ERR_SUBSTITUTION_CONFLICT", 422, "overlapping ACTIVE rule for same from_ingredient")
    rec = {
        "restaurant_id": rid, "from_ingredient_id": from_id, "to_ingredient_id": to_id,
        "effective_start": eff_start, "effective_end": eff_end,
        "status": "PENDING",
    }
    stamp_new(rec)
    db["substitution_rules"][rec["id"]] = rec
    return ok_object(serialize(rec), 201)


@app.get("/api/substitution-rules")
def list_substitution_rules():
    require_roles("OpsAdmin", "ShiftManager", "LineOperator", "PrepCook", "QualityLead")
    limit, offset = parse_limit_offset()
    rid = request.args.get("restaurant_id")
    fid = request.args.get("from_ingredient_id")
    tid = request.args.get("to_ingredient_id")
    status = request.args.get("status")
    items = list(db["substitution_rules"].values())
    if rid:
        items = [r for r in items if r["restaurant_id"] == rid]
    if fid:
        items = [r for r in items if r["from_ingredient_id"] == fid]
    if tid:
        items = [r for r in items if r["to_ingredient_id"] == tid]
    if status:
        items = [r for r in items if r["status"] == status]
    items.sort(key=lambda r: (r["created_at"], r["_seq"]))
    total = len(items)
    page = items[offset:offset + limit]
    return ok_list([serialize(x) for x in page], limit, offset, total)


@app.get("/api/substitution-rules/<sid>")
def get_substitution_rule(sid):
    require_roles("OpsAdmin", "ShiftManager", "LineOperator", "PrepCook", "QualityLead")
    rec = db["substitution_rules"].get(sid)
    if rec is None:
        raise err_not_found()
    return ok_object(serialize(rec))


@app.post("/api/substitution-rules/<sid>/activate")
def activate_substitution(sid):
    require_roles("ShiftManager")
    rec = db["substitution_rules"].get(sid)
    if rec is None:
        raise err_not_found()
    if rec["status"] != "PENDING":
        raise err_invalid_state("rule not PENDING")
    to_ing = db["ingredients"].get(rec["to_ingredient_id"])
    if to_ing is None or to_ing["status"] != "ACTIVE":
        raise ApiError("ERR_SUBSTITUTION_CONFLICT", 422, "to_ingredient must be ACTIVE")
    for r in db["substitution_rules"].values():
        if (r["id"] != sid and r["restaurant_id"] == rec["restaurant_id"]
                and r["from_ingredient_id"] == rec["from_ingredient_id"] and r["status"] == "ACTIVE"
                and window_overlap(rec["effective_start"], rec["effective_end"], r["effective_start"], r["effective_end"])):
            raise ApiError("ERR_SUBSTITUTION_CONFLICT", 422, "overlapping ACTIVE rule")
    rec["status"] = "ACTIVE"
    touch(rec)
    recompute_recipe_versions_for_restaurant(rec["restaurant_id"], rec["from_ingredient_id"])
    return ok_object(serialize(rec))


@app.post("/api/substitution-rules/<sid>/reject")
def reject_substitution(sid):
    require_roles("ShiftManager")
    rec = db["substitution_rules"].get(sid)
    if rec is None:
        raise err_not_found()
    if rec["status"] != "PENDING":
        raise err_invalid_state("rule not PENDING")
    rec["status"] = "REJECTED"
    touch(rec)
    return ok_object(serialize(rec))


@app.post("/api/substitution-rules/<sid>/retire")
def retire_substitution(sid):
    require_roles("ShiftManager")
    rec = db["substitution_rules"].get(sid)
    if rec is None:
        raise err_not_found()
    if rec["status"] != "ACTIVE":
        raise err_invalid_state("rule not ACTIVE")
    rec["status"] = "RETIRED"
    touch(rec)
    recompute_recipe_versions_for_restaurant(rec["restaurant_id"], rec["from_ingredient_id"])
    return ok_object(serialize(rec))


# ---------------------------------------------------------------------------
# Sanitation cycles
# ---------------------------------------------------------------------------
@app.post("/api/sanitation-cycles")
def create_sanitation_cycle():
    require_roles("ShiftManager")
    body = get_body()
    line_id = required(body, "line_id")
    sched_start = parse_dt(required(body, "scheduled_start"))
    sched_end = parse_dt(required(body, "scheduled_end"))
    line = db["assembly_lines"].get(line_id)
    if line is None:
        raise err_not_found("line not found")
    if sched_end <= sched_start:
        raise ApiError("ERR_SANITATION_OVERLAP", 422, "scheduled_end must be strictly after scheduled_start")
    for c in db["sanitation_cycles"].values():
        if c["line_id"] == line_id and c["status"] in ("SCHEDULED", "IN_PROGRESS"):
            if sched_start < c["scheduled_end"] and c["scheduled_start"] < sched_end:
                raise ApiError("ERR_SANITATION_OVERLAP", 422, "overlapping non-terminal cycle on line")
    rec = {
        "line_id": line_id,
        "scheduled_start": sched_start, "scheduled_end": sched_end,
        "actual_started_at": None, "actual_completed_at": None,
        "status": "SCHEDULED",
    }
    stamp_new(rec)
    db["sanitation_cycles"][rec["id"]] = rec
    return ok_object(serialize(rec), 201)


@app.get("/api/sanitation-cycles")
def list_sanitation_cycles():
    require_roles("OpsAdmin", "ShiftManager", "LineOperator", "QualityLead")
    limit, offset = parse_limit_offset()
    line_id = request.args.get("line_id")
    status = request.args.get("status")
    items = list(db["sanitation_cycles"].values())
    if line_id:
        items = [c for c in items if c["line_id"] == line_id]
    if status:
        items = [c for c in items if c["status"] == status]
    items.sort(key=lambda r: (r["created_at"], r["_seq"]))
    total = len(items)
    page = items[offset:offset + limit]
    return ok_list([serialize(x) for x in page], limit, offset, total)


@app.get("/api/sanitation-cycles/<cid>")
def get_sanitation_cycle(cid):
    require_roles("OpsAdmin", "ShiftManager", "LineOperator", "QualityLead")
    rec = db["sanitation_cycles"].get(cid)
    if rec is None:
        raise err_not_found()
    return ok_object(serialize(rec))


@app.post("/api/sanitation-cycles/<cid>/start")
def start_sanitation(cid):
    require_roles("LineOperator")
    rec = db["sanitation_cycles"].get(cid)
    if rec is None:
        raise err_not_found()
    if rec["status"] != "SCHEDULED":
        raise err_invalid_state("cycle not SCHEDULED")
    line = db["assembly_lines"].get(rec["line_id"])
    if line is None:
        raise err_not_found("line not found")
    if line["status"] != "ACTIVE":
        raise err_invalid_state("line not ACTIVE")
    t = now()
    if not (rec["scheduled_start"] <= t < rec["scheduled_end"]):
        raise ApiError("ERR_SANITATION_OVERLAP", 422, "current time outside scheduled window")
    # line-busy guard
    for o in db["orders"].values():
        if o["assigned_line_id"] == line["id"] and o["status"] in ("QUEUED", "ASSEMBLING", "VERIFICATION"):
            raise ApiError("ERR_LINE_BUSY", 409, "line hosts in-flight orders")
    for h in db["hoppers"].values():
        if h["line_id"] == line["id"] and h["status"] == "REFILLING":
            raise ApiError("ERR_LINE_BUSY", 409, "line has a REFILLING hopper")
    rec["actual_started_at"] = t
    rec["status"] = "IN_PROGRESS"
    touch(rec)
    line["status"] = "CLEANING"
    touch(line)
    return ok_object(serialize(rec))


@app.post("/api/sanitation-cycles/<cid>/complete")
def complete_sanitation(cid):
    require_roles("LineOperator")
    rec = db["sanitation_cycles"].get(cid)
    if rec is None:
        raise err_not_found()
    if rec["status"] != "IN_PROGRESS":
        raise err_invalid_state("cycle not IN_PROGRESS")
    line = db["assembly_lines"].get(rec["line_id"])
    if line is None:
        raise err_not_found("line not found")
    if line["status"] != "CLEANING":
        raise err_invalid_state("line not CLEANING")
    t = now()
    rec["actual_completed_at"] = t
    rec["status"] = "COMPLETED"
    touch(rec)
    line["last_sanitation_completed_at"] = t
    line["next_sanitation_due_at"] = t + timedelta(hours=SANITATION_INTERVAL_HOURS)
    line["status"] = "ACTIVE"
    touch(line)
    # quarantined hoppers -> DEPLETED
    for h in db["hoppers"].values():
        if h["line_id"] == line["id"] and h["status"] == "QUARANTINED":
            h["status"] = "DEPLETED"
            touch(h)
    return ok_object(serialize(rec))


@app.post("/api/sanitation-cycles/<cid>/abort")
def abort_sanitation(cid):
    require_roles("ShiftManager")
    rec = db["sanitation_cycles"].get(cid)
    if rec is None:
        raise err_not_found()
    if rec["status"] != "IN_PROGRESS":
        raise err_invalid_state("cycle not IN_PROGRESS")
    line = db["assembly_lines"].get(rec["line_id"])
    if line is None:
        raise err_not_found("line not found")
    if line["status"] != "CLEANING":
        raise err_invalid_state("line not CLEANING")
    rec["status"] = "ABORTED"
    touch(rec)
    line["status"] = "ACTIVE"
    touch(line)
    return ok_object(serialize(rec))


# ---------------------------------------------------------------------------
# Labor assignments
# ---------------------------------------------------------------------------
@app.post("/api/labor-assignments")
def create_labor_assignment():
    require_roles("ShiftManager")
    body = get_body()
    rid = required(body, "restaurant_id")
    staff = required(body, "staff_user_id")
    from_role = required(body, "from_role")
    to_role = required(body, "to_role")
    ws = parse_dt(required(body, "window_start"))
    we = parse_dt(required(body, "window_end"))
    if db["restaurants"].get(rid) is None:
        raise err_not_found("restaurant not found")
    if from_role != "MAKE_LINE":
        raise err_validation("from_role must be MAKE_LINE")
    if to_role not in ("PREP", "HOSPITALITY"):
        raise err_validation("to_role must be PREP or HOSPITALITY")
    if we <= ws:
        raise err_validation("window_end must be strictly after window_start")
    # closed-interval overlap: touching endpoints conflict
    for la in db["labor_assignments"].values():
        if la["staff_user_id"] == staff:
            if ws <= la["window_end"] and la["window_start"] <= we:
                raise ApiError("ERR_LABOR_OVERLAP", 422, "labor window overlaps existing assignment")
    rec = {
        "restaurant_id": rid, "staff_user_id": staff,
        "from_role": from_role, "to_role": to_role,
        "window_start": ws, "window_end": we,
    }
    stamp_new(rec)
    db["labor_assignments"][rec["id"]] = rec
    return ok_object(labor_serialize(rec), 201)


@app.get("/api/labor-assignments")
def list_labor_assignments():
    require_roles("OpsAdmin", "ShiftManager")
    limit, offset = parse_limit_offset()
    rid = request.args.get("restaurant_id")
    staff = request.args.get("staff_user_id")
    items = list(db["labor_assignments"].values())
    if rid:
        items = [l for l in items if l["restaurant_id"] == rid]
    if staff:
        items = [l for l in items if l["staff_user_id"] == staff]
    items.sort(key=lambda r: (r["created_at"], r["_seq"]))
    total = len(items)
    page = items[offset:offset + limit]
    return ok_list([labor_serialize(x) for x in page], limit, offset, total)


@app.get("/api/labor-assignments/<lid>")
def get_labor_assignment(lid):
    require_roles("OpsAdmin", "ShiftManager")
    rec = db["labor_assignments"].get(lid)
    if rec is None:
        raise err_not_found()
    return ok_object(labor_serialize(rec))


# ---------------------------------------------------------------------------
# Portion verifications (analytics)
# ---------------------------------------------------------------------------
@app.get("/api/portion-verifications")
def list_pvs():
    require_roles("OpsAdmin", "ShiftManager", "LineOperator", "QualityLead")
    limit, offset = parse_limit_offset()
    oid = request.args.get("order_id")
    hid = request.args.get("hopper_id")
    iid = request.args.get("ingredient_id")
    result = request.args.get("result")
    items = list(db["portion_verifications"].values())
    if oid:
        items = [p for p in items if p["order_id"] == oid]
    if hid:
        items = [p for p in items if p["hopper_id"] == hid]
    if iid:
        items = [p for p in items if p["ingredient_id"] == iid]
    if result:
        items = [p for p in items if p["result"] == result]
    items.sort(key=lambda r: (r["created_at"], r["_seq"]))
    total = len(items)
    page = items[offset:offset + limit]
    return ok_list([serialize(x) for x in page], limit, offset, total)


@app.get("/api/portion-verifications/<pid>")
def get_pv(pid):
    require_roles("OpsAdmin", "ShiftManager", "LineOperator", "QualityLead")
    rec = db["portion_verifications"].get(pid)
    if rec is None:
        raise err_not_found()
    return ok_object(serialize(rec))


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    port = int(os.environ.get("PORT", "10000"))
    app.run(host="0.0.0.0", port=port)
