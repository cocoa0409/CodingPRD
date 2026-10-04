"""Preventive maintenance schedule endpoints — PRD 3.6."""
from datetime import timedelta

import calc
import services
from core import (ApiError, DB, apply, arg, body, create, dec, endpoint, field,
                  get, iso, now, ordered, own, paginate, parse_dt, set_status,
                  str_field)

SCHEDULE_LIVE = ("ACTIVE", "DUE", "OVERDUE")
OPEN_WORK_ORDER_STATUSES = ("SCHEDULED", "IN_PROGRESS", "PAUSED", "AWAITING_PARTS")
HORIZON_DAYS = 30


def schedule_or_404(schedule_id):
    return get("pm_schedules", schedule_id, "ERR_PM_SCHEDULE_NOT_FOUND")


def _occupation_windows(asset_id, excluding=None):
    windows = []
    for schedule in services.schedules_of(asset_id=asset_id):
        if schedule is excluding:
            continue
        if schedule["status"] not in ("DRAFT", "ACTIVE", "DUE", "OVERDUE", "SUSPENDED"):
            continue
        start = parse_dt(schedule.get("next_due_at"))
        if start is None:
            continue
        windows.append((start, start + timedelta(hours=float(schedule["duration_hours"]))))
    for work_order in DB["work_orders"].values():
        if work_order["asset_id"] != asset_id or work_order["work_type"] != "PREVENTIVE":
            continue
        if work_order["status"] not in OPEN_WORK_ORDER_STATUSES:
            continue
        linked = DB["pm_schedules"].get(work_order.get("_pm_schedule_id"))
        hours = float(linked["duration_hours"]) if linked else 1.0
        start = parse_dt(work_order.get("created_at"))
        if start is None:
            continue
        windows.append((start, start + timedelta(hours=hours)))
    return windows


def _overlaps(start, end, asset_id, excluding=None):
    for other_start, other_end in _occupation_windows(asset_id, excluding):
        if start < other_end and other_start < end:
            return True
    return False


def _linked_work_order(schedule):
    occurrence = services.current_occurrence(schedule)
    if occurrence is None:
        return None
    return DB["work_orders"].get(occurrence["work_order_id"])


# --------------------------------------------------------------------------
# schedule endpoints
# --------------------------------------------------------------------------
@endpoint("/assets/<id>/pm-schedules", ["GET"],
          ["PlatformAdmin", "MunicipalityAdmin", "OperatorAdmin"])
def list_asset_schedules(id):
    asset = get("assets", id, "ERR_ASSET_NOT_FOUND")
    own(asset)
    status = arg("status")
    return paginate(ordered(services.schedules_of(asset_id=asset["id"], status=status)))


@endpoint("/assets/<id>/pm-schedules", ["POST"], ["OperatorAdmin"], status=201)
def create_schedule(id):
    asset = get("assets", id, "ERR_ASSET_NOT_FOUND")
    own(asset)
    data = body()
    try:
        frequency = int(field(data, "frequency_days"))
    except (TypeError, ValueError):
        raise ApiError("ERR_INVALID_DATE_WINDOW", "frequency_days must be an integer.")
    if frequency < 1:
        raise ApiError("ERR_INVALID_DATE_WINDOW", "frequency_days must be at least 1.")
    duration = dec(field(data, "duration_hours"))
    if duration <= 0:
        raise ApiError("ERR_INVALID_DATE_WINDOW", "duration_hours must be greater than 0.")
    first_due = parse_dt(field(data, "first_due_at"))
    total_hours = duration + sum(
        (dec(s["duration_hours"]) for s in services.schedules_of(asset_id=asset["id"])
         if s["status"] in ("DRAFT", "ACTIVE", "DUE", "OVERDUE")), dec(0))
    if first_due + timedelta(hours=float(total_hours)) > now() + timedelta(days=HORIZON_DAYS):
        raise ApiError("ERR_PM_WINDOW_TOO_FAR")
    if _overlaps(first_due, first_due + timedelta(hours=float(duration)), asset["id"]):
        raise ApiError("ERR_PM_OCCUPATION_OVERLAP")
    return create("pm_schedules",
                  asset_id=asset["id"],
                  contract_id=asset["contract_id"],
                  frequency_days=frequency,
                  duration_hours=float(duration),
                  next_due_at=iso(first_due),
                  compliance_rate_pct=0.0,
                  missed_occurrence_count=0,
                  status="DRAFT",
                  _occurrences=[])


@endpoint("/pm-schedules/<id>", ["GET"],
          ["PlatformAdmin", "MunicipalityAdmin", "OperatorAdmin"])
def read_schedule(id):
    schedule = schedule_or_404(id)
    own(schedule)
    return schedule


@endpoint("/pm-schedules/<id>/regenerate", ["POST"], ["OperatorAdmin"])
def regenerate_schedule(id):
    schedule = schedule_or_404(id)
    own(schedule)
    if schedule["status"] == "RETIRED":
        raise ApiError("ERR_ALREADY_TERMINAL")
    if schedule["status"] not in ("DUE", "OVERDUE"):
        raise ApiError("ERR_PM_SCHEDULE_INVALID_STATE")
    due = parse_dt(schedule.get("next_due_at"))
    work_order = _linked_work_order(schedule)
    if schedule["status"] == "DUE":
        if due is None or now() > due + timedelta(days=calc.PM_GRACE_DAYS):
            raise ApiError("ERR_PM_WINDOW_EXPIRED")
        if work_order is None or work_order["status"] != "CLOSED":
            raise ApiError("ERR_PM_WINDOW_EXPIRED")
        closed_at = parse_dt(work_order.get("status_changed_at"))
        if closed_at is None or closed_at > due + timedelta(days=calc.PM_GRACE_DAYS):
            raise ApiError("ERR_PM_WINDOW_EXPIRED")
    else:
        if work_order is None or work_order["status"] != "CLOSED":
            raise ApiError("ERR_PM_WINDOW_EXPIRED")
    new_due = (due or now()) + timedelta(days=int(schedule["frequency_days"]))
    if _overlaps(new_due, new_due + timedelta(hours=float(schedule["duration_hours"])),
                 schedule["asset_id"], excluding=schedule):
        raise ApiError("ERR_PM_OCCUPATION_OVERLAP")
    schedule["next_due_at"] = iso(new_due)
    set_status(schedule, "ACTIVE")
    apply(schedule, compliance_rate_pct=calc.pm_compliance_rate(schedule))
    return schedule


@endpoint("/pm-schedules/<id>/suspend", ["POST"], ["MunicipalityAdmin"])
def suspend_schedule(id):
    schedule = schedule_or_404(id)
    own(schedule)
    str_field(body(), "reason", required=False)
    if schedule["status"] == "RETIRED":
        raise ApiError("ERR_ALREADY_TERMINAL")
    if schedule["status"] not in SCHEDULE_LIVE:
        raise ApiError("ERR_PM_SCHEDULE_INVALID_STATE")
    contract = DB["contracts"][schedule["contract_id"]]
    if contract["status"] not in ("UNDER_REVIEW", "TERMINATED", "HANDING_BACK"):
        raise ApiError("ERR_PM_SCHEDULE_INVALID_STATE")
    set_status(schedule, "SUSPENDED")
    apply(schedule, compliance_rate_pct=calc.pm_compliance_rate(schedule))
    return schedule


@endpoint("/pm-schedules/<id>/reactivate", ["POST"], ["OperatorAdmin"])
def reactivate_schedule(id):
    schedule = schedule_or_404(id)
    own(schedule)
    if schedule["status"] != "SUSPENDED":
        raise ApiError("ERR_PM_SCHEDULE_INVALID_STATE")
    contract = DB["contracts"][schedule["contract_id"]]
    if contract["status"] not in ("OPERATING", "RENEWED"):
        raise ApiError("ERR_PM_SCHEDULE_INVALID_STATE")
    asset = DB["assets"].get(schedule["asset_id"])
    if asset is not None and asset["status"] == "OUT_OF_SERVICE":
        raise ApiError("ERR_PM_SCHEDULE_INVALID_STATE")
    set_status(schedule, "ACTIVE")
    schedule["next_due_at"] = iso(now() + timedelta(days=int(schedule["frequency_days"])))
    return schedule


@endpoint("/pm-schedules/<id>/close-out", ["POST"], ["MunicipalityAdmin"])
def close_out_schedule(id):
    schedule = schedule_or_404(id)
    own(schedule)
    if schedule["status"] == "RETIRED":
        raise ApiError("ERR_ALREADY_TERMINAL")
    if schedule["status"] != "ACTIVE":
        raise ApiError("ERR_PM_SCHEDULE_INVALID_STATE")
    contract = DB["contracts"][schedule["contract_id"]]
    if contract["status"] != "HANDING_BACK":
        raise ApiError("ERR_PM_SCHEDULE_INVALID_STATE")
    set_status(schedule, "COMPLETED")
    return schedule


@endpoint("/pm-schedules/<id>/retire", ["POST"], ["MunicipalityAdmin"])
def retire_schedule(id):
    schedule = schedule_or_404(id)
    own(schedule)
    if schedule["status"] == "RETIRED":
        raise ApiError("ERR_ALREADY_TERMINAL")
    if schedule["status"] != "COMPLETED":
        raise ApiError("ERR_PM_SCHEDULE_INVALID_STATE")
    contract = DB["contracts"][schedule["contract_id"]]
    if contract["status"] not in ("HANDING_BACK", "TRANSITIONED"):
        raise ApiError("ERR_PM_SCHEDULE_INVALID_STATE")
    set_status(schedule, "RETIRED")
    return schedule


@endpoint("/pm-schedules/<id>/evaluate", ["POST"], ["OperatorAdmin"])
def evaluate_schedule_endpoint(id):
    schedule = schedule_or_404(id)
    own(schedule)
    if schedule["status"] in ("SUSPENDED", "COMPLETED", "RETIRED"):
        raise ApiError("ERR_PM_SCHEDULE_INVALID_STATE")
    services.evaluate_schedule(schedule)
    return schedule
