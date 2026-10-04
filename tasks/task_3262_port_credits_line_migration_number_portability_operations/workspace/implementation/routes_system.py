"""Routes: logical clock, ops-run, system config, rejection code catalog."""

from flask import Blueprint

import clock
import errors
import lookups
import middleware
import models
import response
import scheduling
import storage

bp = Blueprint("system", __name__, url_prefix="/portability")

ADMIN = ("PlatformAdmin",)


@bp.post("/_clock/set_current_utc")
@middleware.require_roles(*ADMIN)
def set_current_utc(caller):
    data = middleware.body()
    supplied = data.get("to_iso8601")
    if supplied is None:
        errors.fail("ERR_INVALID_REQUEST", "Field 'to_iso8601' is required.")
    target = clock.to_iso(supplied)
    if target is None:
        errors.fail("ERR_INVALID_REQUEST", "Field 'to_iso8601' must be an ISO 8601 instant.")

    previous = clock.now()
    clock.set_now(target)
    scheduling.run_all()
    return response.ok({
        "current_utc": clock.fmt(clock.now()),
        "previous_utc": clock.fmt(previous),
    })


@bp.post("/system-config/ops-run")
@middleware.require_roles(*ADMIN)
def ops_run(caller):
    # Record the instant in the API's canonical three-fractional-digit form. The
    # operator's supplied reading is compared as an instant, but the stored audit
    # value follows the same millisecond convention as every other timestamp.
    cfg = storage.init_system_config()
    data = middleware.body()
    supplied = data.get("triggered_at")
    if supplied is None:
        errors.fail("ERR_INVALID_REQUEST", "Field 'triggered_at' is required.")
    triggered_at = clock.to_iso(supplied)
    if triggered_at is None:
        errors.fail("ERR_INVALID_REQUEST", "Field 'triggered_at' must be an ISO 8601 instant.")
    triggered_at = clock.parse_instant(clock.fmt(triggered_at))

    deadline = clock.parse_instant(cfg["last_line_cancellation_deadline"])
    cfg["last_ops_run_at"] = clock.fmt(triggered_at)

    # Idempotent per deadline: only a strictly-later run advances the epoch.
    if deadline is None or triggered_at > deadline:
        cfg["ops_run_epoch"] += 1
        for line in storage.db.all("subscriber_lines"):
            if line["service_status"] == "CANCELLED" and line["number_status"] == "ASSIGNED":
                line["number_status"] = "RECLAIMED"
                models.touch(line)

    models.touch(cfg)
    return response.ok(models.config_out(cfg))


@bp.get("/system-config")
@middleware.require_roles("PlatformAdmin", "CustomerService", "Customer")
def get_system_config(caller):
    cfg = storage.init_system_config()
    return response.ok(models.config_out(cfg))


@bp.post("/rejection-code-catalog")
@middleware.require_roles(*ADMIN)
def create_rejection_code(caller):
    data = middleware.body()
    code = middleware.required_str(data, "rejection_code")

    for existing in storage.db.all("rejection_code_catalog"):
        if existing["rejection_code"] == code:
            errors.fail("ERR_INVALID_REQUEST", "rejection_code must be unique across the catalog.")

    requires_action_by = middleware.required_str(data, "requires_action_by")
    if requires_action_by not in ("CUSTOMER", "LOSING_CARRIER", "GAINING_CARRIER"):
        errors.fail("ERR_INVALID_REQUEST", "requires_action_by is not a recognized value.")

    record = {
        "id": storage.new_id(),
        "created_at": clock.fmt_now(),
        "rejection_code": code,
        "description": middleware.required_str(data, "description"),
        "guidance_text": middleware.required_str(data, "guidance_text"),
        "resubmission_allowed": middleware.optional_bool(data, "resubmission_allowed", True),
        "retry_after_hours": middleware.optional_int(data, "retry_after_hours", 0),
        "requires_action_by": requires_action_by,
    }
    storage.db.add("rejection_code_catalog", record)
    return response.ok(models.catalog_out(record), 201)


def get_catalog(code):
    for row in storage.db.all("rejection_code_catalog"):
        if row["rejection_code"] == code:
            return row
    return None