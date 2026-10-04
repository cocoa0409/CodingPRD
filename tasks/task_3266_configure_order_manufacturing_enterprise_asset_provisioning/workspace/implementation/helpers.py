from datetime import datetime, timezone
from flask import request
from errors import ApiError, ERR_INVALID_REQUEST, ERR_NOT_FOUND, err_not_found, err_invalid_request
from db import STORE


def get_json_body():
    if not request.is_json:
        raise err_invalid_request("Request body must be JSON")
    try:
        body = request.get_json(force=False, silent=False)
    except Exception:
        raise err_invalid_request("Malformed JSON body")
    if body is None:
        body = {}
    if not isinstance(body, dict):
        raise err_invalid_request("Request body must be a JSON object")
    return body


def require_field(body, name, types, enum=None, allow_none=False):
    if name not in body:
        raise err_invalid_request(f"Missing required field: {name}")
    val = body[name]
    if val is None:
        if allow_none:
            return None
        raise err_invalid_request(f"Field {name} must not be null")
    if not isinstance(val, types) or (isinstance(val, bool) and bool not in (types if isinstance(types, tuple) else (types,))):
        raise err_invalid_request(f"Field {name} has wrong type")
    if enum is not None and val not in enum:
        raise err_invalid_request(f"Field {name} must be one of {sorted(enum)}")
    return val


def optional_field(body, name, types, enum=None, default=None):
    if name not in body or body[name] is None:
        return default
    return require_field(body, name, types, enum=enum)


def parse_iso8601(val, field_name="timestamp"):
    if not isinstance(val, str):
        raise err_invalid_request(f"Field {field_name} must be an ISO8601 string")
    s = val.strip()
    if s.endswith("Z"):
        s = s[:-1] + "+00:00"
    try:
        dt = datetime.fromisoformat(s)
    except ValueError:
        raise err_invalid_request(f"Field {field_name} is not a valid ISO8601 timestamp")
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def iso_z(dt):
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + f"{dt.microsecond // 1000:03d}Z"


def iso_z_logical(dt):
    """Format for values derived from the logical clock (PRD §2.7). The clock
    is pinned to whole-second instants (e.g. `2026-09-01T00:00:00Z`), so a
    logical-clock value with zero microseconds serializes without fractional
    digits, matching the PRD's canonical clock representation."""
    if dt.microsecond == 0:
        return dt.strftime("%Y-%m-%dT%H:%M:%SZ")
    return iso_z(dt)


def get_pagination():
    raw_limit = request.args.get("limit")
    raw_offset = request.args.get("offset")
    if raw_limit is None:
        limit = 10
    else:
        try:
            limit = int(raw_limit)
        except (TypeError, ValueError):
            raise err_invalid_request("limit must be an integer")
        if limit < 1 or limit > 100:
            raise err_invalid_request("limit must be between 1 and 100")
    if raw_offset is None:
        offset = 0
    else:
        try:
            offset = int(raw_offset)
        except (TypeError, ValueError):
            raise err_invalid_request("offset must be an integer")
        if offset < 0:
            raise err_invalid_request("offset must be >= 0")
    return limit, offset


def sorted_by_created(items):
    return sorted(items, key=lambda e: (e["created_at"], e["id"]))


def paginate(items, limit, offset):
    items = sorted_by_created(items)
    total = len(items)
    return items[offset:offset + limit], total


def lookup(table, key, label="Resource"):
    ent = STORE[table].get(key) if isinstance(STORE, dict) else None
    raise RuntimeError("use store_lookup")


def store_lookup(name, key):
    ent = getattr(STORE, name).get(key)
    if ent is None:
        raise err_not_found(f"{name} {key} not found")
    return ent


# ---------- serializers (available_units derived at serialization) ----------

def ser_account(a):
    return {k: a[k] for k in ("id", "company_name", "account_tier", "credit_limit_cents",
                              "outstanding_cents", "recovery_credit_cents", "status",
                              "created_at", "updated_at", "version")}


def ser_program(p):
    return {k: p[k] for k in ("id", "account_id", "name", "locked", "asset_tag_prefix",
                              "custom_image_ref", "status", "created_at", "updated_at", "version")}


def ser_chassis(c):
    return {k: c[k] for k in ("id", "model_code", "category", "base_price_cents",
                              "build_duration_hours", "status", "created_at", "updated_at", "version")}


def ser_component(c):
    return {"id": c["id"], "sku": c["sku"], "kind": c["kind"], "price_cents": c["price_cents"],
            "lead_time_days": c["lead_time_days"], "stock_on_hand": c["stock_on_hand"],
            "reserved_units": c["reserved_units"],
            "available_units": c["stock_on_hand"] - c["reserved_units"],
            "revision": c["revision"], "status": c["status"],
            "created_at": c["created_at"], "updated_at": c["updated_at"], "version": c["version"]}


def ser_rule(r):
    return {"id": r["id"], "chassis_model_id": r["chassis_model_id"],
            "component_id": r["component_id"], "rule_type": r["rule_type"],
            "other_component_id": r["other_component_id"], "min_qty": r["min_qty"],
            "created_at": r["created_at"]}


def ser_template(t):
    return {k: t[k] for k in ("id", "program_id", "name", "chassis_model_id",
                              "pinned_components", "pinned_image_ref", "status",
                              "created_at", "updated_at", "version")}


def ser_configuration(c):
    return {k: c[k] for k in ("id", "account_id", "template_id", "chassis_model_id",
                              "component_selections", "compatibility_ok",
                              "lead_time_estimate_days", "committed_lead_time_days",
                              "status", "created_at", "updated_at", "version")}


def ser_order(o):
    return {k: o[k] for k in ("id", "account_id", "po_number", "build_status",
                              "ship_status", "promised_ship_date", "total_cents",
                              "discount_cents", "submitted_at",
                              "created_at", "updated_at", "version")}


def ser_order_line(l):
    return {k: l[k] for k in ("id", "order_id", "configuration_id", "qty",
                              "line_total_cents", "ship_to_mode", "status",
                              "created_at", "updated_at", "version")}


def ser_build_job(j):
    return {k: j[k] for k in ("id", "order_id", "order_line_id", "sequence_rank",
                              "qty", "shortage_component_id", "status",
                              "created_at", "updated_at", "version")}


def ser_sub_request(s):
    return {k: s[k] for k in ("id", "build_job_id", "original_component_id",
                              "proposed_component_id", "price_delta_cents", "round",
                              "status", "created_at", "updated_at", "version")}


def ser_wave(w):
    return {k: w[k] for k in ("id", "order_id", "wave_label", "ship_window_start",
                              "ship_window_end", "destinations", "status",
                              "created_at", "updated_at", "version")}


def ser_asset(a):
    return {k: a[k] for k in ("id", "order_line_id", "serial_number", "asset_tag",
                              "image_applied_ref", "destination_employee_ref", "status",
                              "created_at", "updated_at", "version")}


def ser_entitlement(e):
    return {k: e[k] for k in ("id", "order_line_id", "tier", "coverage_start",
                              "coverage_end", "parts_stocking_required",
                              "reserved_part_component_id", "status",
                              "created_at", "updated_at", "version")}


def ser_recovery(r):
    return {k: r[k] for k in ("id", "account_id", "asset_id", "program_kind",
                              "estimated_credit_cents", "final_credit_cents", "status",
                              "created_at", "updated_at", "version")}


# ---------- ownership chains ----------

def account_of_order(order):
    return order["account_id"]


def account_of_line(line):
    order = STORE.orders.get(line["order_id"])
    return order["account_id"] if order else None


def account_of_asset(asset):
    line = STORE.order_lines.get(asset["order_line_id"])
    return account_of_line(line) if line else None


def account_of_build_job(job):
    order = STORE.orders.get(job["order_id"])
    return order["account_id"] if order else None


def account_of_wave(wave):
    order = STORE.orders.get(wave["order_id"])
    return order["account_id"] if order else None


def account_of_sub_request(sr):
    job = STORE.build_jobs.get(sr["build_job_id"])
    return account_of_build_job(job) if job else None


def chassis_of_line(line):
    cfg = STORE.configurations.get(line["configuration_id"])
    if not cfg:
        return None
    return STORE.chassis_models.get(cfg["chassis_model_id"])
