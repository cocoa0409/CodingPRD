"""PortCongestionReport: append-only weekly per-terminal intake (PRD §3.9).
No updated_at / version on this resource family (PRD §2.5)."""
from flask import Blueprint

import store
from auth import require_roles
from envelope import ok_object
from errors import (
    fail,
    ERR_INVALID_REQUEST,
    ERR_DUPLICATE_CONGESTION_REPORT,
    ERR_PORT_CAPACITY_EXCEEDED,
)
from serialization import ser_congestion
from util import body, req_str, req_int, req_dt, is_num
from constants import PORT_WEEKLY_BERTH_CAPACITY_HOURS

bp = Blueprint("congestion", __name__)


@bp.post("/fmc/port-congestion-reports")
def ingest_report():
    require_roles("CommissionDocket")
    b = body()
    port_code = req_str(b, "port_code")
    terminal_code = req_str(b, "terminal_code")
    week_start = req_dt(b, "week_start")
    if (
        week_start.weekday() != 0
        or (week_start.hour, week_start.minute, week_start.second,
            week_start.microsecond) != (0, 0, 0, 0)
    ):
        fail(ERR_INVALID_REQUEST,
             "week_start must be the Monday of the reported week at 00:00:00Z")
    berth = req_int(b, "berth_occupancy_hours", lo=0, hi=168)
    gate = req_int(b, "gate_closures_hours", lo=0, hi=168)
    dwell = b.get("vessel_dwell_hours_avg")
    if dwell is None or not is_num(dwell) or dwell < 0:
        fail(ERR_INVALID_REQUEST,
             "vessel_dwell_hours_avg must be a non-negative number")
    for r in store.congestion_reports.values():
        if (
            r["port_code"] == port_code
            and r["terminal_code"] == terminal_code
            and r["week_start"] == week_start
        ):
            fail(ERR_DUPLICATE_CONGESTION_REPORT,
                 "a report with this (port_code, terminal_code, week_start) "
                 "already exists")
    port_week_total = sum(
        r["berth_occupancy_hours"]
        for r in store.congestion_reports.values()
        if r["port_code"] == port_code and r["week_start"] == week_start
    )
    if port_week_total + berth > PORT_WEEKLY_BERTH_CAPACITY_HOURS:
        fail(ERR_PORT_CAPACITY_EXCEEDED,
             "the port's weekly berth capacity of 672 hours would be exceeded")
    rec = store.base_record(versioned=False)
    rec.update(
        port_code=port_code,
        terminal_code=terminal_code,
        week_start=week_start,
        berth_occupancy_hours=berth,
        gate_closures_hours=gate,
        vessel_dwell_hours_avg=dwell,
    )
    store.congestion_reports[rec["id"]] = rec
    return ok_object(ser_congestion(rec), 201)
