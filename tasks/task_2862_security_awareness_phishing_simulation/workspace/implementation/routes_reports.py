"""Incidents, communication windows, the effectiveness report and the clock."""
from decimal import Decimal

from flask import Blueprint, request

import calc
import derive
import guards
import lookups
from envelope import created, ok, ok_list, paginate
from errors import fail
from store import fmt, new_row, now, ordered, parse_instant, rate, round_half_up, store

bp = Blueprint("reports", __name__)

VARIANTS = ("CONCURRENT", "LAGGED")
MAX_BUCKETS = 24


# ------------------------------------------------------------------- incidents
@bp.post("/awareness/incidents")
def create_incident():
    guards.authorize("SecurityAnalyst")
    data = guards.body()
    incident_type = guards.req_enum(data, "incident_type", calc.INCIDENT_TYPES)
    severity = guards.req_enum(data, "severity", calc.SEVERITIES)
    department = guards.req_enum(data, "department", calc.DEPARTMENTS)
    occurred_at = guards.req_instant(data, "occurred_at")
    summary = guards.req_str(data, "summary")
    root_cause_employee_id = guards.opt_id(data, "root_cause_employee_id")

    if root_cause_employee_id is not None:
        lookups.get_employee(root_cause_employee_id)

    row = new_row(False)
    row.update({
        "incident_type": incident_type,
        "severity": severity,
        "department": department,
        "occurred_at": occurred_at,
        "root_cause_employee_id": root_cause_employee_id,
        "summary": summary,
        "phish_related": incident_type in calc.PHISH_RELATED_TYPES,
    })
    store.incidents[row["id"]] = row
    return created(derive.incident_json(row))


@bp.get("/awareness/incidents/<incident_id>")
def read_incident(incident_id):
    guards.authorize("SecurityAnalyst", "ProgramAdmin")
    return ok(derive.incident_json(lookups.get_incident(incident_id)))


@bp.get("/awareness/incidents")
def list_incidents():
    guards.authorize("SecurityAnalyst", "ProgramAdmin")
    limit, offset = guards.pagination()
    department = guards.query_enum("department", calc.DEPARTMENTS)
    incident_type = guards.query_enum("incident_type", calc.INCIDENT_TYPES)
    root_cause = guards.query_str("root_cause_employee_id")
    occurred_from = guards.query_instant("occurred_from")
    occurred_to = guards.query_instant("occurred_to")

    rows = []
    for row in ordered(list(store.incidents.values())):
        if department is not None and row["department"] != department:
            continue
        if incident_type is not None and row["incident_type"] != incident_type:
            continue
        if root_cause is not None and row["root_cause_employee_id"] != root_cause:
            continue
        if occurred_from is not None and row["occurred_at"] < occurred_from:
            continue
        if occurred_to is not None and row["occurred_at"] > occurred_to:
            continue
        rows.append(row)
    page, total = paginate(rows, limit, offset)
    return ok_list([derive.incident_json(r) for r in page], limit, offset, total)


# --------------------------------------------------------- communication windows
@bp.post("/awareness/communication-windows")
def create_window():
    guards.authorize("ProgramAdmin")
    data = guards.body()
    window_type = guards.req_enum(data, "window_type", calc.WINDOW_TYPES)
    start_at = guards.req_instant(data, "start_at")
    end_at = guards.req_instant(data, "end_at")
    reason = guards.req_str(data, "reason")
    scope_department = guards.opt_enum(data, "scope_department", calc.DEPARTMENTS)

    if end_at <= start_at:
        fail("ERR_INVALID_REQUEST", "end_at must be strictly after start_at")

    row = new_row(False)
    row.update({
        "window_type": window_type,
        "start_at": start_at,
        "end_at": end_at,
        "scope_department": scope_department,
        "reason": reason,
    })
    store.windows[row["id"]] = row
    return created(derive.window_json(row))


@bp.get("/awareness/communication-windows")
def list_windows():
    guards.authorize("ProgramAdmin", "CampaignAuthor")
    limit, offset = guards.pagination()
    window_type = guards.query_enum("window_type", calc.WINDOW_TYPES)
    scope_department = guards.query_enum("scope_department", calc.DEPARTMENTS)

    rows = []
    for row in ordered(list(store.windows.values())):
        if window_type is not None and row["window_type"] != window_type:
            continue
        if scope_department is not None and row["scope_department"] != scope_department:
            continue
        rows.append(row)
    page, total = paginate(rows, limit, offset)
    return ok_list([derive.window_json(r) for r in page], limit, offset, total)


# ------------------------------------------------------------ the logical clock
@bp.post("/awareness/_clock/set_current_utc")
def set_clock():
    guards.authorize("ProgramAdmin")
    data = guards.body()
    target = guards.req_instant(data, "to_iso8601")
    previous = store.clock
    store.clock = target
    return ok({"current_utc": fmt(target), "previous_utc": fmt(previous)})


# ------------------------------------------------------- program effectiveness
def _month_floor(dt):
    return dt.replace(day=1, hour=0, minute=0, second=0, microsecond=0)


def _next_month(dt):
    if dt.month == 12:
        return dt.replace(year=dt.year + 1, month=1)
    return dt.replace(month=dt.month + 1)


def _merged_params():
    """The report is a GET; accept its inputs from the query string or a body."""
    params = {}
    payload = guards.body()
    if isinstance(payload, dict):
        params.update(payload)
    for key in request.args.keys():
        params[key] = request.args.get(key)
    return params


def _bucket_deliveries(bucket_start, bucket_end, department):
    rows = []
    for delivery in ordered(list(store.deliveries.values())):
        if delivery["state"] == "EXCLUDED":
            continue
        campaign = store.campaigns.get(delivery["campaign_id"])
        if campaign is None or campaign["state"] != "CLOSED":
            continue
        closed_at = campaign["closed_at"]
        if closed_at is None or closed_at < bucket_start or closed_at >= bucket_end:
            continue
        if department is not None:
            emp = store.employees.get(delivery["employee_id"])
            if emp is None or emp["department"] != department:
                continue
        rows.append(delivery)
    return rows


def _bucket_incidents(bucket_start, bucket_end, department):
    count = 0
    for row in store.incidents.values():
        if not row["phish_related"]:
            continue
        if row["occurred_at"] < bucket_start or row["occurred_at"] >= bucket_end:
            continue
        if department is not None and row["department"] != department:
            continue
        count += 1
    return count


@bp.get("/awareness/effectiveness-report")
def effectiveness_report():
    guards.authorize("SecurityAnalyst", "ProgramAdmin")
    params = _merged_params()
    period_start = guards.req_instant(params, "period_start")
    period_end = guards.req_instant(params, "period_end")
    variant = guards.req_enum(params, "variant", VARIANTS)
    department = guards.opt_enum(params, "department", calc.DEPARTMENTS)

    if period_end <= period_start:
        fail("ERR_INVALID_REQUEST", "period_end must be strictly later than period_start")

    buckets = []
    cursor = _month_floor(period_start)
    while cursor < period_end:
        following = _next_month(cursor)
        buckets.append((cursor, following))
        cursor = following
        if len(buckets) > MAX_BUCKETS:
            fail("ERR_REPORT_PERIOD_INVALID", "the requested span exceeds 24 calendar months")

    rows = []
    for bucket_start, bucket_end in buckets:
        deliveries = _bucket_deliveries(bucket_start, bucket_end, department)
        reported = len([d for d in deliveries if d["first_report_at"] is not None])
        rows.append({
            "month": bucket_start.strftime("%Y-%m"),
            "bucket_start": fmt(bucket_start),
            "bucket_end": fmt(bucket_end),
            "report_rate": rate(reported, len(deliveries)),
            "incident_count": _bucket_incidents(bucket_start, bucket_end, department),
        })

    # Pair formation: CONCURRENT keeps every bucket, LAGGED drops the last one.
    pairs = []
    for index, row in enumerate(rows):
        if variant == "LAGGED":
            if index + 1 >= len(rows):
                continue
            partner = rows[index + 1]["incident_count"]
        else:
            partner = row["incident_count"]
        if row["report_rate"] is None:
            continue                      # a null rate drops with its partner
        pairs.append((row["report_rate"], partner))

    pair_count = len(pairs)
    correlation = None
    reason_code = None
    if pair_count < 2:
        reason_code = "INSUFFICIENT_PAIRS"
    else:
        xs = [Decimal(str(x)) for x, _ in pairs]
        ys = [Decimal(y) for _, y in pairs]
        raw = calc.pearson(xs, ys)
        if raw is None:
            reason_code = "ZERO_VARIANCE"
        else:
            correlation = float(round_half_up(raw, 4))

    observed = [row["report_rate"] for row in rows if row["report_rate"] is not None]
    if observed:
        mean_report_rate = float(round_half_up(
            sum(Decimal(str(v)) for v in observed) / Decimal(len(observed)), 4))
    else:
        mean_report_rate = None

    return ok({
        "variant": variant,
        "buckets": rows,
        "pair_count": pair_count,
        "mean_report_rate": mean_report_rate,
        "total_incidents": sum(row["incident_count"] for row in rows),
        "correlation": correlation,
        "correlation_reason_code": reason_code,
    })
