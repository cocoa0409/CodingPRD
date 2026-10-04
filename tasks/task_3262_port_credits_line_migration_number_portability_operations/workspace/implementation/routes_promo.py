"""Routes: promotional switch-credit schedules -- projection, vesting, clawback."""

from flask import Blueprint

import calculations
import clock
import errors
import lookups
import middleware
import models
import response
import services
import storage

bp = Blueprint("promo", __name__, url_prefix="/portability")

WRITERS = ("CustomerService", "PlatformAdmin")
BUFFERING_STATES = ("PROVISIONAL", "ACTIVE")


def _window_overlaps(line_id, new_start):
    """New window must start at or after every live window_end plus the buffer."""
    cfg = storage.init_system_config()
    buffer_days = cfg["promo_window_buffer_days"]
    for existing in storage.db.all("promo_credit_schedules"):
        if existing["subscriber_line_id"] != line_id:
            continue
        if existing["schedule_state"] not in BUFFERING_STATES:
            continue
        end = clock.parse_instant(existing["window_end"])
        if end is None:
            continue
        if new_start < clock.add_days(end, buffer_days):
            return True
    return False


@bp.post("/promo-credit-schedules")
@middleware.require_roles(*WRITERS)
def create_schedule(caller):
    data = middleware.body()
    line_id = middleware.required_str(data, "subscriber_line_id")
    line = lookups.line(line_id)

    promo_code = middleware.required_str(data, "promo_code")
    monthly_credit = middleware.required_int(data, "monthly_credit_cents")
    installment_months = middleware.required_int(data, "installment_months")
    if installment_months <= 0:
        errors.fail("ERR_INVALID_REQUEST", "installment_months must be at least 1.")
    retention_cycles = middleware.optional_int(data, "retention_requirement_cycles", 12)

    window_start = middleware.optional_instant(data, "window_start")
    if window_start is None:
        errors.fail("ERR_INVALID_REQUEST", "Field 'window_start' is required.")

    # The client's observed line version is validated before the window-overlap test
    # so a stale create surfaces as ERR_STALE_SUBSCRIBER_LINE_VERSION (412) rather
    # than as the overlap error; the version gate is a precondition of the create
    # itself, whereas the buffer test only becomes meaningful once the client is
    # known to hold a current view of the line.
    middleware.require_expected_line_version(data, line)

    if _window_overlaps(line_id, window_start):
        errors.fail("ERR_PROMO_WINDOW_OVERLAP",
                    "The requested window starts inside another schedule's window plus buffer.")

    window_end = calculations.promo_window_end(window_start, installment_months)
    provisional = calculations.promo_provisional_total(installment_months, retention_cycles)

    record = {
        "id": storage.new_id(),
        "created_at": clock.fmt_now(),
        "updated_at": clock.fmt_now(),
        "version": 1,
        "subscriber_line_id": line_id,
        "promo_code": promo_code,
        "monthly_credit_cents": monthly_credit,
        "installment_months": installment_months,
        "retention_requirement_cycles": retention_cycles,
        "schedule_state": "PROVISIONAL",
        "window_start": clock.fmt(window_start),
        "window_end": clock.fmt(window_end),
        "provisional_total_cents": provisional,
        "vested_total_cents": 0,
        "cycles_elapsed": calculations.promo_cycles_elapsed(window_start, clock.now()),
    }
    storage.db.add("promo_credit_schedules", record)

    line["promo_eligibility_state"] = "PROVISIONAL_ELIGIBLE"
    models.touch(line)

    account = storage.db.get("accounts", line["account_id"])
    if account is not None:
        account["promo_credited_cents"] += provisional
        models.recompute_promo_ledger(account["id"])

    return response.ok(models.promo_out(record), 201)


@bp.get("/promo-credit-schedules/<schedule_id>")
@middleware.require_roles("PlatformAdmin", "CustomerService", "Customer")
def get_schedule(caller, schedule_id):
    record = lookups.fetch("promo_credit_schedules", schedule_id)
    line = lookups.line(record["subscriber_line_id"])
    middleware.enforce_ownership(caller, line["account_id"])
    return response.ok(models.promo_out(record))


@bp.post("/promo-credit-schedules/<schedule_id>/activate")
@middleware.require_roles(*WRITERS)
def activate_schedule(caller, schedule_id):
    record = lookups.fetch("promo_credit_schedules", schedule_id)

    if record["schedule_state"] != "PROVISIONAL":
        errors.fail("ERR_INVALID_STATE", "Only a PROVISIONAL schedule can be activated.")

    start = clock.parse_instant(record["window_start"])
    if start is None or clock.now() < start:
        errors.fail("ERR_INVALID_STATE",
                    "The current logical clock instant is before window_start.")

    record["schedule_state"] = "ACTIVE"
    models.touch(record)

    line = lookups.line(record["subscriber_line_id"])
    account = storage.db.get("accounts", line["account_id"])
    if account is not None:
        models.recompute_promo_ledger(account["id"])
    return response.ok(models.promo_out(record))


@bp.post("/promo-credit-schedules/<schedule_id>/claw-back")
@middleware.require_roles("PlatformAdmin")
def claw_back_schedule(caller, schedule_id):
    record = lookups.fetch("promo_credit_schedules", schedule_id)

    if record["schedule_state"] != "ACTIVE":
        errors.fail("ERR_INVALID_STATE", "Only an ACTIVE schedule can be clawed back.")

    line = lookups.line(record["subscriber_line_id"])
    if line["service_status"] != "ACTIVE":
        errors.fail("ERR_LINE_NOT_ACTIVE",
                    "The attached line is not ACTIVE; the credit cannot be reversed.")

    # hop 1
    record["schedule_state"] = "CLAWED_BACK"
    record["vested_total_cents"] = 0
    models.touch(record)
    line["promo_eligibility_state"] = "CLAWED_BACK"
    models.touch(line)

    # hop 2: the credited amount is pushed back onto the device balance owed
    plan = _clawback_plan(line["id"])
    if plan is not None:
        plan["remaining_balance_cents"] += record["provisional_total_cents"]
        # hop 3
        services.recompute_plan(plan)

    # the reversal amount is exactly the schedule's own provisional total
    reversal = calculations.promo_clawback_reversal(record)
    account = storage.db.get("accounts", line["account_id"])
    if account is not None:
        account["promo_clawed_back_cents"] += reversal
        models.recompute_promo_ledger(account["id"])

    return response.ok(models.promo_out(record))


def _clawback_plan(line_id):
    candidates = [
        p for p in storage.db.all("device_installment_plans")
        if p["subscriber_line_id"] == line_id
    ]
    if not candidates:
        return None
    for plan in candidates:
        if plan["plan_state"] == "ACTIVE":
            return plan
    live = [p for p in candidates if p["plan_state"] != "CONVERTED"]
    pool = live or candidates
    pool.sort(key=lambda p: (p["created_at"], p["id"]))
    return pool[-1]