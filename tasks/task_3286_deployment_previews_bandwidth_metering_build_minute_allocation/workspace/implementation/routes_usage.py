"""Routes: usage periods, usage events, alert rules, spend caps, clock, summary."""

from flask import Blueprint, request

from db import db, new_id, now_iso, touch, parse_ts, format_ts
from errors import err
from middleware import (
    require_roles, parse_pagination, body, require_fields,
)
from response import ok_object, ok_list, ok_empty
from services import (
    usage_period_view, usage_event_view, alert_rule_view, spend_cap_view,
    get_team_or_404, open_period_for_team, recompute_projected_bill,
    stamp_effective_rates, evaluate_alerts, evaluate_spend_cap,
    active_spend_cap, alert_auto_reset_sweep, certificate_expiry_sweep,
)

bp = Blueprint("usage", __name__)

BILLING_READ = ("PlatformAdmin", "TeamOwner", "TeamBillingManager")
REGIONS = ("IAD", "SFO", "FRA", "SIN")
ALERT_METRICS = ("BANDWIDTH_BYTES", "INVOCATIONS", "BUILD_MINUTES", "SPEND_CENTS")
CAP_ACTIONS = ("ALERT_ONLY", "BLOCK_DEPLOYS_AND_SUSPEND")


def _paginate(items, view=None):
    limit, offset = parse_pagination()
    items = sorted(items, key=lambda x: (x["created_at_dt"], x["id"]))
    total = len(items)
    page = items[offset:offset + limit]
    if view:
        page = [view(x) for x in page]
    return ok_list(page, total, limit, offset)


def get_period_or_404(period_id):
    p = db.usage_periods.get(period_id)
    if not p:
        err("ERR_USAGE_PERIOD_NOT_FOUND", "UsagePeriod id does not exist")
    return p


def get_event_or_404(event_id):
    e = db.usage_events.get(event_id)
    if not e:
        err("ERR_USAGE_PERIOD_NOT_FOUND", "UsageEvent id does not exist")
    return e


def get_alert_or_404(alert_id):
    a = db.alert_rules.get(alert_id)
    if not a:
        err("ERR_ALERT_RULE_NOT_FOUND", "AlertRule id does not exist")
    return a


def get_cap_or_404(cap_id):
    c = db.spend_caps.get(cap_id)
    if not c:
        err("ERR_SPEND_CAP_NOT_FOUND", "SpendCap id does not exist")
    return c


# --- Usage periods -----------------------------------------------------------

@bp.post("/v1/teams/<team_id>/usage-periods")
@require_roles("TeamBillingManager", "PlatformAdmin")
def create_usage_period(team_id):
    get_team_or_404(team_id)
    data = body()
    require_fields(data, "period_start", "period_end")
    try:
        start = parse_ts(data["period_start"])
        end = parse_ts(data["period_end"])
    except (ValueError, TypeError):
        err("ERR_INVALID_REQUEST", "period_start/period_end must be ISO8601 strings")
    if end <= start:
        err("ERR_INVALID_PERIOD_RANGE", "period_end must be strictly after period_start")
    for p in db.usage_periods.values():
        if p["team_id"] != team_id:
            continue
        if p["status"] == "OPEN":
            err("ERR_USAGE_PERIOD_OVERLAP",
                "Opening a period while another period of the team is OPEN")
        if start < p["period_end_dt"] and end > p["period_start_dt"]:
            err("ERR_USAGE_PERIOD_OVERLAP",
                "the [start,end) interval overlaps an existing period")
    period = {
        "id": new_id(), "team_id": team_id,
        "period_start": format_ts(start), "period_end": format_ts(end),
        "period_start_dt": start, "period_end_dt": end,
        "status": "OPEN", "bandwidth_bytes": 0, "invocations": 0,
        "build_minutes_used": 0, "projected_bill_cents": 0,
        "final_bill_cents": None, "total_due_cents": None,
        "created_at": now_iso(), "updated_at": now_iso(), "version": 1,
        "created_at_dt": db.clock,
    }
    db.usage_periods[period["id"]] = period
    return ok_object(usage_period_view(period), 201)


@bp.get("/v1/teams/<team_id>/usage-periods")
@require_roles(*BILLING_READ)
def list_team_periods(team_id):
    get_team_or_404(team_id)
    status = request.args.get("status")
    items = [p for p in db.usage_periods.values() if p["team_id"] == team_id
             and (status is None or p["status"] == status)]
    return _paginate(items, view=usage_period_view)


@bp.get("/v1/usage-periods")
@require_roles(*BILLING_READ)
def list_periods():
    team_id = request.args.get("team_id")
    status = request.args.get("status")
    items = [p for p in db.usage_periods.values()
             if (team_id is None or p["team_id"] == team_id)
             and (status is None or p["status"] == status)]
    return _paginate(items, view=usage_period_view)


@bp.get("/v1/usage-periods/<period_id>")
@require_roles(*BILLING_READ)
def get_period(period_id):
    return ok_object(usage_period_view(get_period_or_404(period_id)))


@bp.post("/v1/usage-periods/<period_id>/close")
@require_roles("TeamBillingManager", "PlatformAdmin")
def close_period(period_id):
    period = get_period_or_404(period_id)
    if period["status"] != "OPEN":
        err("ERR_INVALID_STATE", "UsagePeriod.status == OPEN required")
    team = db.teams[period["team_id"]]
    for e in db.usage_events.values():
        if e["period_id"] == period_id and e["status"] == "ESTIMATED":
            e["status"] = "RECORDED"
    events = [e for e in db.usage_events.values()
              if e["period_id"] == period_id and e["status"] == "RECORDED"]
    from services import compute_charge
    period["final_bill_cents"] = compute_charge(period, team, events)
    stamp_effective_rates(period)
    period["total_due_cents"] = period["final_bill_cents"] + team["prorated_charges_cents"]
    period["status"] = "CLOSED"
    touch(period)
    return ok_object(usage_period_view(period))


@bp.post("/v1/usage-periods/<period_id>/invoice")
@require_roles("TeamBillingManager")
def invoice_period(period_id):
    period = get_period_or_404(period_id)
    if period["status"] != "CLOSED":
        err("ERR_INVALID_STATE", "UsagePeriod.status == CLOSED required")
    period["status"] = "INVOICED"
    touch(period)
    team = db.teams[period["team_id"]]
    team["prorated_charges_cents"] = 0
    touch(team)
    return ok_object(usage_period_view(period))


# --- Usage events ---------------------------------------------------------------

@bp.post("/v1/teams/<team_id>/usage-events")
@require_roles("SystemWebhook", "PlatformAdmin")
def ingest_usage_event(team_id):
    team = get_team_or_404(team_id)
    data = body()
    require_fields(data, "deployment_id", "event_type", "region")
    deployment_id = data["deployment_id"]
    event_type = data["event_type"]
    if event_type not in ("BANDWIDTH", "INVOCATION"):
        err("ERR_INVALID_REQUEST", "event_type must be BANDWIDTH or INVOCATION")
    region = data["region"]
    if region not in REGIONS:
        err("ERR_INVALID_REQUEST", "region must be one of IAD|SFO|FRA|SIN")
    bandwidth_bytes = data.get("bandwidth_bytes", 0)
    invocations = data.get("invocations", 0)
    edge_execution = data.get("edge_execution", False)
    status = data.get("status", "RECORDED")
    if not isinstance(bandwidth_bytes, int) or isinstance(bandwidth_bytes, bool):
        err("ERR_INVALID_REQUEST", "bandwidth_bytes must be an integer")
    if not isinstance(invocations, int) or isinstance(invocations, bool):
        err("ERR_INVALID_REQUEST", "invocations must be an integer")
    if not isinstance(edge_execution, bool):
        err("ERR_INVALID_REQUEST", "edge_execution must be a boolean")
    if status not in ("RECORDED", "ESTIMATED"):
        err("ERR_INVALID_REQUEST", "status must be RECORDED or ESTIMATED")
    # shape rules
    if event_type == "BANDWIDTH":
        if bandwidth_bytes < 1 or invocations != 0:
            err("ERR_USAGE_EVENT_SHAPE",
                "BANDWIDTH events require bandwidth_bytes>=1 and invocations==0")
    else:
        if invocations < 1 or bandwidth_bytes != 0:
            err("ERR_USAGE_EVENT_SHAPE",
                "INVOCATION events require invocations>=1 and bandwidth_bytes==0")

    period = open_period_for_team(team_id)
    if not period:
        err("ERR_USAGE_PERIOD_CLOSED",
            "Usage event ingested when no OPEN period exists for the team")
    if not (period["period_start_dt"] <= db.clock < period["period_end_dt"]):
        err("ERR_USAGE_PERIOD_CLOSED",
            "recorded_at must lie within [period_start, period_end) of the target OPEN period")

    event = {
        "id": new_id(), "period_id": period["id"], "team_id": team_id,
        "deployment_id": deployment_id, "event_type": event_type,
        "bandwidth_bytes": bandwidth_bytes, "invocations": invocations,
        "region": region, "edge_execution": edge_execution, "status": status,
        "recorded_at": now_iso(), "recorded_at_dt": db.clock,
        "effective_rate_cents": None,
        "created_at": now_iso(), "created_at_dt": db.clock,
    }
    db.usage_events[event["id"]] = event
    period["bandwidth_bytes"] += bandwidth_bytes
    period["invocations"] += invocations
    recompute_projected_bill(period)
    touch(period)
    evaluate_alerts(team_id)
    evaluate_spend_cap(team_id)
    return ok_object(usage_event_view(event), 201)


@bp.get("/v1/usage-periods/<period_id>/usage-events")
@require_roles(*BILLING_READ)
def list_period_events(period_id):
    get_period_or_404(period_id)
    event_type = request.args.get("event_type")
    deployment_id = request.args.get("deployment_id")
    status = request.args.get("status")
    items = [e for e in db.usage_events.values() if e["period_id"] == period_id
             and (event_type is None or e["event_type"] == event_type)
             and (deployment_id is None or e["deployment_id"] == deployment_id)
             and (status is None or e["status"] == status)]
    return _paginate(items, view=usage_event_view)


@bp.get("/v1/usage-events")
@require_roles(*BILLING_READ)
def list_usage_events():
    team_id = request.args.get("team_id")
    deployment_id = request.args.get("deployment_id")
    event_type = request.args.get("event_type")
    items = [e for e in db.usage_events.values()
             if (team_id is None or e["team_id"] == team_id)
             and (deployment_id is None or e["deployment_id"] == deployment_id)
             and (event_type is None or e["event_type"] == event_type)]
    return _paginate(items, view=usage_event_view)


@bp.get("/v1/usage-events/<event_id>")
@require_roles(*BILLING_READ)
def get_usage_event(event_id):
    return ok_object(usage_event_view(get_event_or_404(event_id)))


# --- Alert rules ------------------------------------------------------------------

@bp.post("/v1/teams/<team_id>/alert-rules")
@require_roles("TeamBillingManager")
def create_alert_rule(team_id):
    get_team_or_404(team_id)
    data = body()
    require_fields(data, "metric", "threshold_value")
    metric = data["metric"]
    if metric not in ALERT_METRICS:
        err("ERR_INVALID_REQUEST", "metric must be one of BANDWIDTH_BYTES|INVOCATIONS|BUILD_MINUTES|SPEND_CENTS")
    threshold = data["threshold_value"]
    if not isinstance(threshold, int) or isinstance(threshold, bool):
        err("ERR_INVALID_REQUEST", "threshold_value must be an integer")
    if threshold <= 0:
        err("ERR_INVALID_REQUEST", "threshold_value must be > 0")
    window = data.get("window_minutes", 60)
    if not isinstance(window, int) or isinstance(window, bool) or window <= 0:
        err("ERR_INVALID_REQUEST", "window_minutes must be a positive integer")
    rule = {
        "id": new_id(), "team_id": team_id, "metric": metric,
        "threshold_value": threshold, "window_minutes": window,
        "status": "ACTIVE", "last_fired_at": None, "last_fired_at_dt": None,
        "created_at": now_iso(), "updated_at": now_iso(), "version": 1,
        "created_at_dt": db.clock,
    }
    db.alert_rules[rule["id"]] = rule
    return ok_object(alert_rule_view(rule), 201)


@bp.get("/v1/teams/<team_id>/alert-rules")
@require_roles(*BILLING_READ)
def list_team_alert_rules(team_id):
    get_team_or_404(team_id)
    items = [a for a in db.alert_rules.values() if a["team_id"] == team_id]
    return _paginate(items, view=alert_rule_view)


@bp.get("/v1/alert-rules")
@require_roles(*BILLING_READ)
def list_alert_rules():
    team_id = request.args.get("team_id")
    items = [a for a in db.alert_rules.values()
             if team_id is None or a["team_id"] == team_id]
    return _paginate(items, view=alert_rule_view)


@bp.get("/v1/alert-rules/<alert_id>")
@require_roles(*BILLING_READ)
def get_alert_rule(alert_id):
    return ok_object(alert_rule_view(get_alert_or_404(alert_id)))


@bp.delete("/v1/alert-rules/<alert_id>")
@require_roles("TeamBillingManager")
def delete_alert_rule(alert_id):
    rule = get_alert_or_404(alert_id)
    rule["status"] = "DISABLED"
    touch(rule)
    return ok_empty(204)


# --- Spend caps ----------------------------------------------------------------------

@bp.post("/v1/teams/<team_id>/spend-caps")
@require_roles("TeamBillingManager")
def create_spend_cap(team_id):
    get_team_or_404(team_id)
    data = body()
    require_fields(data, "cap_cents", "action")
    cap_cents = data["cap_cents"]
    if not isinstance(cap_cents, int) or isinstance(cap_cents, bool):
        err("ERR_INVALID_REQUEST", "cap_cents must be an integer")
    if cap_cents <= 0:
        err("ERR_INVALID_REQUEST", "cap_cents must be > 0")
    action = data["action"]
    if action not in CAP_ACTIONS:
        err("ERR_INVALID_REQUEST", "action must be ALERT_ONLY or BLOCK_DEPLOYS_AND_SUSPEND")
    for c in db.spend_caps.values():
        if c["team_id"] == team_id and c["status"] != "DISABLED":
            err("ERR_SPEND_CAP_EXISTS", "Team already has a non-DISABLED spend cap")
    cap = {
        "id": new_id(), "team_id": team_id, "cap_cents": cap_cents,
        "action": action, "status": "ACTIVE", "tripped_at": None,
        "created_at": now_iso(), "updated_at": now_iso(), "version": 1,
        "created_at_dt": db.clock,
    }
    db.spend_caps[cap["id"]] = cap
    return ok_object(spend_cap_view(cap), 201)


@bp.get("/v1/teams/<team_id>/spend-caps")
@require_roles(*BILLING_READ)
def list_team_spend_caps(team_id):
    get_team_or_404(team_id)
    items = [c for c in db.spend_caps.values() if c["team_id"] == team_id]
    return _paginate(items, view=spend_cap_view)


@bp.get("/v1/spend-caps")
@require_roles(*BILLING_READ)
def list_spend_caps():
    team_id = request.args.get("team_id")
    items = [c for c in db.spend_caps.values()
             if team_id is None or c["team_id"] == team_id]
    return _paginate(items, view=spend_cap_view)


@bp.get("/v1/spend-caps/<cap_id>")
@require_roles(*BILLING_READ)
def get_spend_cap(cap_id):
    return ok_object(spend_cap_view(get_cap_or_404(cap_id)))


@bp.patch("/v1/spend-caps/<cap_id>")
@require_roles("TeamBillingManager")
def patch_spend_cap(cap_id):
    cap = get_cap_or_404(cap_id)
    data = body()
    expected = data.get("expected_spendcap_version")
    if expected is not None and expected != cap["version"]:
        err("ERR_STALE_VERSION", "expected_spendcap_version does not match current version")
    if "cap_cents" in data and data["cap_cents"] is not None:
        v = data["cap_cents"]
        if not isinstance(v, int) or isinstance(v, bool):
            err("ERR_INVALID_REQUEST", "cap_cents must be an integer")
        if v <= 0:
            err("ERR_INVALID_REQUEST", "cap_cents must be > 0")
        cap["cap_cents"] = v
    if "action" in data and data["action"] is not None:
        if data["action"] not in CAP_ACTIONS:
            err("ERR_INVALID_REQUEST", "action must be ALERT_ONLY or BLOCK_DEPLOYS_AND_SUSPEND")
        cap["action"] = data["action"]
    # TRIPPED -> ACTIVE reset when projected bill < new cap
    if cap["status"] == "TRIPPED":
        period = open_period_for_team(cap["team_id"])
        projected = period["projected_bill_cents"] if period else 0
        if projected < cap["cap_cents"]:
            cap["status"] = "ACTIVE"
            cap["tripped_at"] = None
    touch(cap)
    return ok_object(spend_cap_view(cap))


@bp.delete("/v1/spend-caps/<cap_id>")
@require_roles("TeamBillingManager")
def delete_spend_cap(cap_id):
    cap = get_cap_or_404(cap_id)
    cap["status"] = "DISABLED"
    touch(cap)
    return ok_empty(204)


# --- Logical clock -----------------------------------------------------------------------

@bp.post("/v1/_clock/set_current_utc")
@require_roles("PlatformAdmin")
def set_clock():
    data = body()
    require_fields(data, "to_iso8601")
    try:
        new_clock = parse_ts(data["to_iso8601"])
    except (ValueError, TypeError):
        err("ERR_INVALID_REQUEST", "to_iso8601 must be an ISO8601 string")
    db.clock = new_clock
    certificate_expiry_sweep()
    alert_auto_reset_sweep()
    return ok_object({"current_utc": format_ts(db.clock)})


# --- Usage summary --------------------------------------------------------------------------

@bp.get("/v1/teams/<team_id>/usage-summary")
@require_roles(*BILLING_READ)
def usage_summary(team_id):
    get_team_or_404(team_id)
    period = open_period_for_team(team_id)
    if not period:
        err("ERR_USAGE_PERIOD_NOT_FOUND", "No OPEN usage period exists for the team")
    return ok_object(usage_period_view(period))
