"""Observability Billing API — Flask entry point.

Implements the PRD for the usage-based observability billing benchmark task.
Store starts empty on every boot; the logical clock defaults to
2026-09-01T00:00:00Z and is only moved by POST /_clock/set_current_utc.
"""

import os
from math import ceil

from flask import Flask, request

import db
from errors import (
    ApiError, invalid_request, forbidden, not_found, invalid_state,
    period_closed, stale_version, account_delinquent, commitment_window_overlap,
    tier_window_overlap, plan_limit, tag_policy_violation, duplicate_host_hour,
    no_active_commitment, open_incidents_block_close,
)
from helpers import (
    ROLES, PLAN_TIERS, METERS, MONITOR_KINDS, ENFORCEMENTS, SOFT_CAP,
    BP_BASE, EVENTS_PER_MILLION, BYTES_PER_GB,
    clock_utc, parse_dt, get_body,
    req_str, opt_str, req_int, opt_int, opt_bool, req_enum, req_dt,
    req_list_of_str, req_field, parse_pagination, parse_bool_param,
    check_auth, require_roles, new_record, touch, lookup,
    get_plan_for_account, get_or_create_accumulator, find_active_commitment,
    bump_meter, plan_overage_rate_cents, rate_usage_amount_cents,
    select_winning_filter, sample_admits,
)
from response import success_object, success_array, error_response

app = Flask(__name__)


@app.errorhandler(ApiError)
def handle_api_error(err):
    return error_response(err)


@app.errorhandler(404)
def handle_http_404(err):
    return error_response(not_found())


@app.errorhandler(405)
def handle_http_405(err):
    return error_response(not_found())


@app.errorhandler(Exception)
def handle_unexpected(err):
    if isinstance(err, ApiError):
        return error_response(err)
    return error_response(invalid_request(str(err)))


# ===========================================================================
# Shared pipeline pieces
# ===========================================================================

def _list(records, filters=None):
    """Filter (exact match on scalar fields), sort by created_at ASC, paginate."""
    items = list(records)
    if filters:
        for key, value in filters.items():
            if value is None:
                continue
            items = [r for r in items if r.get(key) == value]
    items.sort(key=lambda r: (r.get("created_at", ""), r["id"]))
    total = len(items)
    limit, offset = parse_pagination()
    page = items[offset:offset + limit]
    return success_array(page, total, limit, offset)


def _get_account(aid):
    return lookup(db.billing_accounts, aid)


def _get_period_under_account(aid, pid):
    account = _get_account(aid)
    period = lookup(db.billing_periods, pid)
    if period["billing_account_id"] != account["id"]:
        raise not_found()
    return account, period


def _require_period_open(period):
    if period["status"] != "OPEN":
        raise period_closed()


def _check_account_occ(account, body):
    expected = req_int(body, "expected_billing_account_version")
    if expected != account["version"]:
        raise stale_version()


def _sum_active_cardinality(account_id):
    total = 0
    for s in db.custom_metric_series.values():
        if s["billing_account_id"] == account_id and s["status"] == "ACTIVE":
            total += s["cardinality_estimate"]
    return total


# ===========================================================================
# Clock (test-driving; outside /api prefix)
# ===========================================================================

@app.route("/_clock/set_current_utc", methods=["POST"])
def set_clock():
    role = check_auth()
    require_roles(role, {"PlatformAdmin"})
    body = get_body()
    value = req_str(body, "current_utc")
    dt = parse_dt(value)
    if dt is None:
        raise invalid_request("current_utc must be an ISO 8601 datetime")
    db.logical_clock["current_utc"] = value
    return success_object({"current_utc": db.logical_clock["current_utc"]})


# ===========================================================================
# BillingAccount
# ===========================================================================

@app.route("/api/billing-accounts", methods=["POST"])
def create_billing_account():
    role = check_auth()
    require_roles(role, {"PlatformAdmin"})
    body = get_body()
    name = req_str(body, "name")
    plan_tier = req_enum(body, "plan_tier", PLAN_TIERS)
    anchor = req_int(body, "billing_cycle_anchor_day")
    if anchor < 1 or anchor > 28:
        raise invalid_request("billing_cycle_anchor_day must be between 1 and 28")
    rec = new_record({
        "name": name,
        "plan_tier": plan_tier,
        "billing_cycle_anchor_day": anchor,
        "standing": "GOOD",
    })
    db.billing_accounts[rec["id"]] = rec
    return success_object(rec, 201)


@app.route("/api/billing-accounts/<aid>", methods=["GET"])
def get_billing_account(aid):
    role = check_auth()
    require_roles(role, {"PlatformAdmin", "BillingAdmin", "FinanceReader", "TeamLead"})
    rec = lookup(db.billing_accounts, aid)
    return success_object(rec)


@app.route("/api/billing-accounts", methods=["GET"])
def list_billing_accounts():
    role = check_auth()
    require_roles(role, {"PlatformAdmin", "FinanceReader"})
    return _list(db.billing_accounts.values(), {
        "plan_tier": request.args.get("plan_tier"),
        "standing": request.args.get("standing"),
    })


# ===========================================================================
# PlanTierConfig
# ===========================================================================

@app.route("/api/plan-tier-configs", methods=["POST"])
def create_plan_tier_config():
    role = check_auth()
    require_roles(role, {"PlatformAdmin"})
    body = get_body()
    plan_tier = req_enum(body, "plan_tier", PLAN_TIERS)
    rec = new_record({
        "plan_tier": plan_tier,
        "max_monitors": req_int(body, "max_monitors"),
        "included_custom_metrics": req_int(body, "included_custom_metrics"),
        "host_overage_rate_cents": req_int(body, "host_overage_rate_cents"),
        "log_ingest_rate_cents_per_gb": req_int(body, "log_ingest_rate_cents_per_gb"),
        "log_index_rate_cents_per_million": req_int(body, "log_index_rate_cents_per_million"),
        "custom_metric_rate_cents_per_unit": req_int(body, "custom_metric_rate_cents_per_unit"),
    })
    db.plan_tier_configs[rec["id"]] = rec
    return success_object(rec, 201)


@app.route("/api/plan-tier-configs/<cid>", methods=["GET"])
def get_plan_tier_config(cid):
    role = check_auth()
    require_roles(role, {"PlatformAdmin", "BillingAdmin", "FinanceReader"})
    rec = lookup(db.plan_tier_configs, cid)
    return success_object(rec)


# ===========================================================================
# BillingPeriod
# ===========================================================================

@app.route("/api/billing-accounts/<aid>/billing-periods", methods=["POST"])
def create_billing_period(aid):
    role = check_auth()
    require_roles(role, {"BillingAdmin"})
    account = _get_account(aid)
    body = get_body()
    start = req_dt(body, "period_start_utc")
    end = req_dt(body, "period_end_utc")
    rec = new_record({
        "billing_account_id": account["id"],
        "period_start_utc": body["period_start_utc"],
        "period_end_utc": body["period_end_utc"],
        "status": "OPEN",
    })
    db.billing_periods[rec["id"]] = rec
    return success_object(rec, 201)


@app.route("/api/billing-accounts/<aid>/billing-periods", methods=["GET"])
def list_billing_periods(aid):
    role = check_auth()
    require_roles(role, {"BillingAdmin", "FinanceReader"})
    account = _get_account(aid)
    records = [p for p in db.billing_periods.values()
               if p["billing_account_id"] == account["id"]]
    return _list(records, {"status": request.args.get("status")})


@app.route("/api/billing-accounts/<aid>/billing-periods/<pid>", methods=["GET"])
def get_billing_period(aid, pid):
    role = check_auth()
    require_roles(role, {"BillingAdmin", "FinanceReader", "TeamLead"})
    account, period = _get_period_under_account(aid, pid)
    return success_object(period)


def _close_period(account, period):
    if period["status"] != "OPEN":
        raise invalid_state("BillingPeriod must be OPEN to close")
    now = parse_dt(clock_utc())
    period_end = parse_dt(period["period_end_utc"])
    if now < period_end:
        raise invalid_state("Logical clock has not reached period_end_utc")
    open_incidents = [
        i for i in db.cardinality_incidents.values()
        if i["status"] == "OPEN"
        and db.custom_metric_series[i["custom_metric_series_id"]]["billing_account_id"] == account["id"]
    ]
    if open_incidents:
        raise open_incidents_block_close()

    # Host billable counts (PRD §3.2)
    hours = [h for h in db.host_hour_records.values()
             if h["billing_period_id"] == period["id"]]
    footprints = sorted(h["infra_host_count"] + h["container_host_count"] for h in hours)
    if footprints:
        hwm = max(footprints)
        n = len(footprints)
        rank = ceil(0.99 * n)
        p99 = footprints[rank - 1]
    else:
        hwm = 0
        p99 = 0
    charged = min(hwm, p99)

    # Draft invoice: one line per meter with non-zero quantity
    invoice = new_record({
        "billing_period_id": period["id"],
        "total_amount_cents": 0,
        "status": "DRAFT",
    })
    db.invoices[invoice["id"]] = invoice

    accumulators = [a for a in db.meter_accumulators.values()
                    if a["billing_period_id"] == period["id"]]
    if charged > 0:
        host_acc = None
        for a in accumulators:
            if a["meter"] == "INFRA_HOST":
                host_acc = a
                break
        if host_acc is None:
            host_acc = get_or_create_accumulator(period, "INFRA_HOST")
            accumulators.append(host_acc)
        if host_acc["quantity"] < charged:
            bump_meter(period, account, "INFRA_HOST", charged - host_acc["quantity"])

    for a in sorted(accumulators, key=lambda x: (x.get("created_at", ""), x["id"])):
        if a["quantity"] == 0:
            continue
        if a["committed_consumed_quantity"] > 0:
            commitment = None
            for c in db.commitments.values():
                if (c["billing_account_id"] == account["id"]
                        and c["meter"] == a["meter"]
                        and c["status"] in ("ACTIVE", "EXHAUSTED", "SETTLED")
                        and c["consumed_quantity"] > 0):
                    commitment = c
                    break
            commit_rate = commitment["committed_unit_rate_cents"] if commitment else plan_overage_rate_cents(get_plan_for_account(account), a["meter"])
            over_rate = commitment["overage_unit_rate_cents"] if commitment else plan_overage_rate_cents(get_plan_for_account(account), a["meter"])
        else:
            commit_rate = plan_overage_rate_cents(get_plan_for_account(account), a["meter"])
            over_rate = commit_rate
        line = new_record({
            "invoice_id": invoice["id"],
            "meter": a["meter"],
            "rated_quantity": a["quantity"],
            "committed_quantity": a["committed_consumed_quantity"],
            "overage_quantity": a["on_demand_quantity"],
            "committed_unit_rate_cents": commit_rate,
            "overage_unit_rate_cents": over_rate,
            "amount_cents": 0,
        }, common=False, immutable=True)
        db.invoice_lines[line["id"]] = line

    # Settle elapsed commitments (PRD §3.4)
    for c in db.commitments.values():
        if c["billing_account_id"] != account["id"]:
            continue
        if c["status"] not in ("ACTIVE", "EXHAUSTED"):
            continue
        if parse_dt(c["window_end_utc"]) <= now:
            if c["status"] == "ACTIVE":
                c["expired_quantity"] = c["committed_quantity"] - c["consumed_quantity"]
            else:
                c["expired_quantity"] = 0
            c["status"] = "SETTLED"
            touch(c)

    period["status"] = "CLOSED"
    touch(period)
    return period


@app.route("/api/billing-accounts/<aid>/billing-periods/<pid>/close", methods=["POST"])
def close_billing_period(aid, pid):
    role = check_auth()
    require_roles(role, {"BillingAdmin"})
    account, period = _get_period_under_account(aid, pid)
    period = _close_period(account, period)
    return success_object(period)


@app.route("/api/billing-accounts/<aid>/billing-periods/<pid>/settle", methods=["POST"])
def settle_billing_period(aid, pid):
    role = check_auth()
    require_roles(role, {"BillingAdmin"})
    account, period = _get_period_under_account(aid, pid)
    if period["status"] != "CLOSED":
        raise invalid_state("BillingPeriod must be CLOSED to settle")
    invoices = [i for i in db.invoices.values() if i["billing_period_id"] == period["id"]]
    if not any(i["status"] in ("PAID", "VOID") for i in invoices):
        raise invalid_state("Period invoice must be PAID or VOID before settlement")
    period["status"] = "SETTLED"
    touch(period)
    return success_object(period)


@app.route("/api/billing-periods/<pid>", methods=["GET"])
def flat_get_billing_period(pid):
    role = check_auth()
    require_roles(role, {"BillingAdmin", "FinanceReader", "TeamLead"})
    rec = lookup(db.billing_periods, pid)
    return success_object(rec)


@app.route("/api/billing-periods", methods=["GET"])
def flat_list_billing_periods():
    role = check_auth()
    require_roles(role, {"BillingAdmin", "FinanceReader"})
    return _list(db.billing_periods.values(), {
        "billing_account_id": request.args.get("billing_account_id"),
        "status": request.args.get("status"),
    })


# ===========================================================================
# HostHourRecord
# ===========================================================================

@app.route("/api/billing-accounts/<aid>/billing-periods/<pid>/host-hour-records", methods=["POST"])
def create_host_hour_record(aid, pid):
    role = check_auth()
    require_roles(role, {"IngestionAgent"})
    account, period = _get_period_under_account(aid, pid)
    _require_period_open(period)
    body = get_body()
    bucket_raw = req_str(body, "hour_bucket_utc")
    bucket = parse_dt(bucket_raw)
    if bucket is None:
        raise invalid_request("hour_bucket_utc must be an ISO 8601 datetime")
    for h in db.host_hour_records.values():
        if (h["billing_period_id"] == period["id"]
                and parse_dt(h["hour_bucket_utc"]) == bucket):
            raise duplicate_host_hour()
    rec = new_record({
        "billing_period_id": period["id"],
        "hour_bucket_utc": bucket_raw,
        "infra_host_count": req_int(body, "infra_host_count"),
        "container_host_count": req_int(body, "container_host_count"),
        "serverless_invocation_count": req_int(body, "serverless_invocation_count"),
    })
    db.host_hour_records[rec["id"]] = rec
    return success_object(rec, 201)


@app.route("/api/billing-accounts/<aid>/billing-periods/<pid>/host-hour-records", methods=["GET"])
def list_host_hour_records(aid, pid):
    role = check_auth()
    require_roles(role, {"BillingAdmin", "FinanceReader"})
    account, period = _get_period_under_account(aid, pid)
    records = [h for h in db.host_hour_records.values()
               if h["billing_period_id"] == period["id"]]
    return _list(records)


@app.route("/api/host-hour-records/<hid>", methods=["GET"])
def flat_get_host_hour_record(hid):
    role = check_auth()
    require_roles(role, {"BillingAdmin", "FinanceReader"})
    rec = lookup(db.host_hour_records, hid)
    return success_object(rec)


@app.route("/api/host-hour-records", methods=["GET"])
def flat_list_host_hour_records():
    role = check_auth()
    require_roles(role, {"BillingAdmin", "FinanceReader"})
    return _list(db.host_hour_records.values(), {
        "billing_period_id": request.args.get("billing_period_id"),
    })


# ===========================================================================
# MeterAccumulator
# ===========================================================================

@app.route("/api/billing-accounts/<aid>/billing-periods/<pid>/meter-accumulators", methods=["GET"])
def list_meter_accumulators(aid, pid):
    role = check_auth()
    require_roles(role, {"BillingAdmin", "FinanceReader", "TeamLead"})
    account, period = _get_period_under_account(aid, pid)
    records = [a for a in db.meter_accumulators.values()
               if a["billing_period_id"] == period["id"]]
    return _list(records, {"meter": request.args.get("meter")})


@app.route("/api/meter-accumulators/<mid>", methods=["GET"])
def flat_get_meter_accumulator(mid):
    role = check_auth()
    require_roles(role, {"BillingAdmin", "FinanceReader", "TeamLead"})
    rec = lookup(db.meter_accumulators, mid)
    return success_object(rec)


@app.route("/api/meter-accumulators", methods=["GET"])
def flat_list_meter_accumulators():
    role = check_auth()
    require_roles(role, {"BillingAdmin", "FinanceReader", "TeamLead"})
    return _list(db.meter_accumulators.values(), {
        "billing_period_id": request.args.get("billing_period_id"),
        "meter": request.args.get("meter"),
    })


# ===========================================================================
# LogEvent
# ===========================================================================

def _resolve_exclusion(account, service_tag, retention_tier_id):
    """Evaluate filters synchronously at ingest (PRD §3.3). Returns
    (exclusion_state, effective_retention_tier_id)."""
    winner = select_winning_filter(account["id"], service_tag)
    if winner is None:
        return "INDEXED", retention_tier_id
    if winner["sample_rate_pct"] == 0:
        return "EXCLUDED", None
    if sample_admits(service_tag, winner["sample_rate_pct"]):
        return "INDEXED", retention_tier_id
    return "EXCLUDED", None


@app.route("/api/billing-accounts/<aid>/billing-periods/<pid>/log-events", methods=["POST"])
def create_log_event(aid, pid):
    role = check_auth()
    require_roles(role, {"IngestionAgent"})
    account, period = _get_period_under_account(aid, pid)
    _require_period_open(period)
    body = get_body()
    size_bytes = req_int(body, "size_bytes")
    service_tag = req_str(body, "service_tag")
    ingested_at = req_str(body, "ingested_at_utc")
    if parse_dt(ingested_at) is None:
        raise invalid_request("ingested_at_utc must be an ISO 8601 datetime")
    retention_tier_id = opt_str(body, "retention_tier_id")
    if retention_tier_id is not None:
        tier = lookup(db.retention_tiers, retention_tier_id)
        if tier["billing_account_id"] != account["id"]:
            raise not_found()
    exclusion_state, effective_tier = _resolve_exclusion(account, service_tag, retention_tier_id)
    rec = new_record({
        "billing_period_id": period["id"],
        "size_bytes": size_bytes,
        "service_tag": service_tag,
        "ingested_at_utc": ingested_at,
        "exclusion_state": exclusion_state,
        "retention_tier_id": effective_tier,
    })
    db.log_events[rec["id"]] = rec
    bump_meter(period, account, "LOG_INGEST", size_bytes)
    if exclusion_state == "INDEXED":
        bump_meter(period, account, "LOG_INDEX", 1)
    return success_object(rec, 201)


@app.route("/api/billing-accounts/<aid>/billing-periods/<pid>/log-events", methods=["GET"])
def list_log_events(aid, pid):
    role = check_auth()
    require_roles(role, {"BillingAdmin", "FinanceReader"})
    account, period = _get_period_under_account(aid, pid)
    records = [e for e in db.log_events.values()
               if e["billing_period_id"] == period["id"]]
    return _list(records, {
        "exclusion_state": request.args.get("exclusion_state"),
        "service_tag": request.args.get("service_tag"),
    })


@app.route("/api/billing-accounts/<aid>/log-events/<eid>/reindex", methods=["POST"])
def reindex_log_event(aid, eid):
    role = check_auth()
    require_roles(role, {"BillingAdmin"})
    account = _get_account(aid)
    event = lookup(db.log_events, eid)
    period = db.billing_periods.get(event["billing_period_id"])
    if period is None or period["billing_account_id"] != account["id"]:
        raise not_found()
    _require_period_open(period)
    if event["exclusion_state"] != "EXCLUDED":
        raise invalid_state("Only an EXCLUDED event can be reindexed")
    winner = select_winning_filter(account["id"], event["service_tag"])
    if winner is not None and winner["sample_rate_pct"] == 0:
        raise invalid_state("Event is under a hard exclusion (sample_rate_pct == 0)")
    commitment = find_active_commitment(account["id"], "LOG_INDEX")
    if commitment is None:
        raise no_active_commitment()
    event["exclusion_state"] = "INDEXED"
    touch(event)
    bump_meter(period, account, "LOG_INDEX", 1)
    return success_object(event)


@app.route("/api/log-events/<eid>", methods=["GET"])
def flat_get_log_event(eid):
    role = check_auth()
    require_roles(role, {"BillingAdmin", "FinanceReader"})
    rec = lookup(db.log_events, eid)
    return success_object(rec)


@app.route("/api/log-events", methods=["GET"])
def flat_list_log_events():
    role = check_auth()
    require_roles(role, {"BillingAdmin", "FinanceReader"})
    return _list(db.log_events.values(), {
        "billing_period_id": request.args.get("billing_period_id"),
        "retention_tier_id": request.args.get("retention_tier_id"),
        "exclusion_state": request.args.get("exclusion_state"),
        "service_tag": request.args.get("service_tag"),
    })


# ===========================================================================
# RetentionTier
# ===========================================================================

def _tier_windows_collide(account_id, from_dt, to_dt):
    """Half-open overlap + gap rule (PRD §2.9)."""
    tiers = [t for t in db.retention_tiers.values()
             if t["billing_account_id"] == account_id]
    for t in tiers:
        tf = parse_dt(t["effective_from_utc"])
        tt = parse_dt(t["effective_to_utc"])
        if from_dt < tt and tf < to_dt:
            return True
    predecessors = [t for t in tiers if parse_dt(t["effective_to_utc"]) <= from_dt]
    if predecessors:
        latest_end = max(parse_dt(t["effective_to_utc"]) for t in predecessors)
        if latest_end < from_dt:
            return True
    return False


@app.route("/api/billing-accounts/<aid>/retention-tiers", methods=["POST"])
def create_retention_tier(aid):
    role = check_auth()
    require_roles(role, {"BillingAdmin"})
    account = _get_account(aid)
    body = get_body()
    from_dt = req_dt(body, "effective_from_utc")
    to_dt = req_dt(body, "effective_to_utc")
    if _tier_windows_collide(account["id"], from_dt, to_dt):
        raise tier_window_overlap()
    _check_account_occ(account, body)
    rec = new_record({
        "billing_account_id": account["id"],
        "name": req_str(body, "name"),
        "retention_days": req_int(body, "retention_days"),
        "effective_from_utc": body["effective_from_utc"],
        "effective_to_utc": body["effective_to_utc"],
        "index_rate_multiplier_bp": req_int(body, "index_rate_multiplier_bp"),
    })
    db.retention_tiers[rec["id"]] = rec
    touch(account)
    return success_object(rec, 201)


@app.route("/api/billing-accounts/<aid>/retention-tiers", methods=["GET"])
def list_retention_tiers(aid):
    role = check_auth()
    require_roles(role, {"BillingAdmin", "FinanceReader"})
    account = _get_account(aid)
    records = [t for t in db.retention_tiers.values()
               if t["billing_account_id"] == account["id"]]
    return _list(records)


@app.route("/api/retention-tiers/<tid>", methods=["GET"])
def flat_get_retention_tier(tid):
    role = check_auth()
    require_roles(role, {"BillingAdmin", "FinanceReader"})
    rec = lookup(db.retention_tiers, tid)
    return success_object(rec)


@app.route("/api/retention-tiers", methods=["GET"])
def flat_list_retention_tiers():
    role = check_auth()
    require_roles(role, {"BillingAdmin", "FinanceReader"})
    return _list(db.retention_tiers.values(), {
        "billing_account_id": request.args.get("billing_account_id"),
    })


# ===========================================================================
# ExclusionFilter
# ===========================================================================

@app.route("/api/billing-accounts/<aid>/exclusion-filters", methods=["POST"])
def create_exclusion_filter(aid):
    role = check_auth()
    require_roles(role, {"BillingAdmin"})
    account = _get_account(aid)
    body = get_body()
    pattern = req_str(body, "service_tag_pattern")
    sample_rate = req_int(body, "sample_rate_pct")
    if sample_rate < 0 or sample_rate > 100:
        raise invalid_request("sample_rate_pct must be between 0 and 100")
    rec = new_record({
        "billing_account_id": account["id"],
        "service_tag_pattern": pattern,
        "sample_rate_pct": sample_rate,
        "priority": req_int(body, "priority"),
        "enabled": opt_bool(body, "enabled", True),
    })
    db.exclusion_filters[rec["id"]] = rec
    return success_object(rec, 201)


@app.route("/api/billing-accounts/<aid>/exclusion-filters", methods=["GET"])
def list_exclusion_filters(aid):
    role = check_auth()
    require_roles(role, {"BillingAdmin", "FinanceReader"})
    account = _get_account(aid)
    records = [f for f in db.exclusion_filters.values()
               if f["billing_account_id"] == account["id"]]
    return _list(records, {"enabled": parse_bool_param("enabled")})


@app.route("/api/billing-accounts/<aid>/exclusion-filters/<fid>/disable", methods=["POST"])
def disable_exclusion_filter(aid, fid):
    role = check_auth()
    require_roles(role, {"BillingAdmin"})
    account = _get_account(aid)
    filt = lookup(db.exclusion_filters, fid)
    if filt["billing_account_id"] != account["id"]:
        raise not_found()
    filt["enabled"] = False
    touch(filt)
    return success_object(filt)


@app.route("/api/exclusion-filters/<fid>", methods=["GET"])
def flat_get_exclusion_filter(fid):
    role = check_auth()
    require_roles(role, {"BillingAdmin", "FinanceReader"})
    rec = lookup(db.exclusion_filters, fid)
    return success_object(rec)


@app.route("/api/exclusion-filters", methods=["GET"])
def flat_list_exclusion_filters():
    role = check_auth()
    require_roles(role, {"BillingAdmin", "FinanceReader"})
    return _list(db.exclusion_filters.values(), {
        "billing_account_id": request.args.get("billing_account_id"),
        "enabled": parse_bool_param("enabled"),
    })


# ===========================================================================
# CustomMetricSeries + rollup snapshots + CardinalityIncident
# ===========================================================================

@app.route("/api/billing-accounts/<aid>/custom-metric-series", methods=["POST"])
def create_custom_metric_series(aid):
    role = check_auth()
    require_roles(role, {"BillingAdmin", "TeamLead"})
    account = _get_account(aid)
    body = get_body()
    metric_name = req_str(body, "metric_name")
    team_id = req_str(body, "team_id")
    team = lookup(db.teams, team_id)
    if team["billing_account_id"] != account["id"]:
        raise not_found()
    rec = new_record({
        "billing_account_id": account["id"],
        "metric_name": metric_name,
        "team_id": team_id,
        "cardinality_estimate": 0,
        "status": "ACTIVE",
    })
    db.custom_metric_series[rec["id"]] = rec
    return success_object(rec, 201)


@app.route("/api/billing-accounts/<aid>/custom-metric-series", methods=["GET"])
def list_custom_metric_series(aid):
    role = check_auth()
    require_roles(role, {"BillingAdmin", "FinanceReader", "TeamLead"})
    account = _get_account(aid)
    records = [s for s in db.custom_metric_series.values()
               if s["billing_account_id"] == account["id"]]
    return _list(records, {
        "status": request.args.get("status"),
        "team_id": request.args.get("team_id"),
    })


def _open_incident_for_series(series, account, estimate, threshold):
    for i in db.cardinality_incidents.values():
        if i["custom_metric_series_id"] == series["id"] and i["status"] == "OPEN":
            return
    incident = new_record({
        "custom_metric_series_id": series["id"],
        "opened_at_cardinality": estimate,
        "threshold_used": threshold,
        "status": "OPEN",
        "remediation_note": None,
    })
    db.cardinality_incidents[incident["id"]] = incident


@app.route("/api/billing-accounts/<aid>/custom-metric-series/<sid>/rollup", methods=["POST"])
def rollup_custom_metric_series(aid, sid):
    role = check_auth()
    require_roles(role, {"IngestionAgent"})
    account = _get_account(aid)
    series = lookup(db.custom_metric_series, sid)
    if series["billing_account_id"] != account["id"]:
        raise not_found()
    body = get_body()
    estimate = req_int(body, "cardinality_estimate")

    old_billable = series["cardinality_estimate"] if series["status"] == "ACTIVE" else 0
    series["cardinality_estimate"] = estimate
    touch(series)
    new_billable = estimate if series["status"] == "ACTIVE" else 0

    # Sync the CUSTOM_METRIC meter against the OPEN period, if any
    open_period = None
    for p in db.billing_periods.values():
        if p["billing_account_id"] == account["id"] and p["status"] == "OPEN":
            open_period = p
            break
    if open_period is not None:
        delta = new_billable - old_billable
        if delta != 0:
            bump_meter(open_period, account, "CUSTOM_METRIC", delta)

    plan = get_plan_for_account(account)
    included = plan["included_custom_metrics"] if plan else 0
    threshold = included + SOFT_CAP

    # Incident machinery (PRD §3.7)
    incidents = [i for i in db.cardinality_incidents.values()
                 if i["custom_metric_series_id"] == series["id"]]
    incidents.sort(key=lambda i: (i["created_at"], i["id"]))
    latest = incidents[-1] if incidents else None

    above = estimate > threshold
    if above:
        if latest is not None and latest["status"] == "VERIFIED":
            latest["status"] = "OPEN"
            touch(latest)
            series["status"] = "QUARANTINED"
            touch(series)
            if open_period is not None and estimate != 0:
                bump_meter(open_period, account, "CUSTOM_METRIC", -estimate)
        elif latest is None or latest["status"] == "CLOSED":
            _open_incident_for_series(series, account, estimate, threshold)
    else:
        if latest is not None and latest["status"] == "REMEDIATED":
            if latest.get("_below_count"):
                latest["status"] = "VERIFIED"
                latest.pop("_below_count", None)
            else:
                latest["_below_count"] = True
            touch(latest)

    return success_object(series)


@app.route("/api/custom-metric-series/<sid>", methods=["GET"])
def flat_get_custom_metric_series(sid):
    role = check_auth()
    require_roles(role, {"BillingAdmin", "FinanceReader", "TeamLead"})
    rec = lookup(db.custom_metric_series, sid)
    rec = {k: v for k, v in rec.items() if not k.startswith("_")}
    return success_object(rec)


@app.route("/api/custom-metric-series", methods=["GET"])
def flat_list_custom_metric_series():
    role = check_auth()
    require_roles(role, {"BillingAdmin", "FinanceReader", "TeamLead"})
    records = [{k: v for k, v in s.items() if not k.startswith("_")}
               for s in db.custom_metric_series.values()]
    return _list(records, {
        "billing_account_id": request.args.get("billing_account_id"),
        "team_id": request.args.get("team_id"),
        "status": request.args.get("status"),
    })


def _get_incident_under_account(aid, iid):
    account = _get_account(aid)
    incident = lookup(db.cardinality_incidents, iid)
    series = db.custom_metric_series.get(incident["custom_metric_series_id"])
    if series is None or series["billing_account_id"] != account["id"]:
        raise not_found()
    return account, incident, series


def _incident_public(incident):
    return {k: v for k, v in incident.items() if not k.startswith("_")}


@app.route("/api/billing-accounts/<aid>/cardinality-incidents", methods=["GET"])
def list_cardinality_incidents(aid):
    role = check_auth()
    require_roles(role, {"BillingAdmin", "FinanceReader"})
    account = _get_account(aid)
    series_ids = {s["id"] for s in db.custom_metric_series.values()
                  if s["billing_account_id"] == account["id"]}
    records = [_incident_public(i) for i in db.cardinality_incidents.values()
               if i["custom_metric_series_id"] in series_ids]
    return _list(records, {"status": request.args.get("status")})


@app.route("/api/billing-accounts/<aid>/cardinality-incidents/<iid>/triage", methods=["POST"])
def triage_incident(aid, iid):
    role = check_auth()
    require_roles(role, {"BillingAdmin"})
    account, incident, series = _get_incident_under_account(aid, iid)
    if incident["status"] != "OPEN":
        raise invalid_state("Incident must be OPEN to triage")
    incident["status"] = "TRIAGED"
    touch(incident)
    return success_object(_incident_public(incident))


@app.route("/api/billing-accounts/<aid>/cardinality-incidents/<iid>/remediate", methods=["POST"])
def remediate_incident(aid, iid):
    role = check_auth()
    require_roles(role, {"BillingAdmin"})
    account, incident, series = _get_incident_under_account(aid, iid)
    if incident["status"] != "TRIAGED":
        raise invalid_state("Incident must be TRIAGED to remediate")
    body = get_body()
    note = req_str(body, "remediation_note")
    if not note.strip():
        raise invalid_request("remediation_note must be non-empty")
    incident["remediation_note"] = note
    incident["status"] = "REMEDIATED"
    touch(incident)
    # Cascade: quarantine the series; stop contributing to billable cardinality
    was_active = series["status"] == "ACTIVE"
    series["status"] = "QUARANTINED"
    touch(series)
    if was_active and series["cardinality_estimate"] > 0:
        for p in db.billing_periods.values():
            if p["billing_account_id"] == account["id"] and p["status"] == "OPEN":
                bump_meter(p, account, "CUSTOM_METRIC", -series["cardinality_estimate"])
                break
    return success_object(_incident_public(incident))


@app.route("/api/billing-accounts/<aid>/cardinality-incidents/<iid>/close", methods=["POST"])
def close_incident(aid, iid):
    role = check_auth()
    require_roles(role, {"BillingAdmin"})
    account, incident, series = _get_incident_under_account(aid, iid)
    if incident["status"] != "VERIFIED":
        raise invalid_state("Incident must be VERIFIED to close")
    incident["status"] = "CLOSED"
    touch(incident)
    # Cascade: restore series to ACTIVE; resume contributing
    series["status"] = "ACTIVE"
    touch(series)
    if series["cardinality_estimate"] > 0:
        for p in db.billing_periods.values():
            if p["billing_account_id"] == account["id"] and p["status"] == "OPEN":
                bump_meter(p, account, "CUSTOM_METRIC", series["cardinality_estimate"])
                break
    return success_object(_incident_public(incident))


@app.route("/api/cardinality-incidents/<iid>", methods=["GET"])
def flat_get_cardinality_incident(iid):
    role = check_auth()
    require_roles(role, {"BillingAdmin", "FinanceReader"})
    rec = lookup(db.cardinality_incidents, iid)
    return success_object(_incident_public(rec))


@app.route("/api/cardinality-incidents", methods=["GET"])
def flat_list_cardinality_incidents():
    role = check_auth()
    require_roles(role, {"BillingAdmin", "FinanceReader"})
    records = [_incident_public(i) for i in db.cardinality_incidents.values()]
    return _list(records, {
        "custom_metric_series_id": request.args.get("custom_metric_series_id"),
        "status": request.args.get("status"),
    })


# ===========================================================================
# Commitment
# ===========================================================================

def _commitment_windows_collide(account_id, meter, start_dt, end_dt, exclude_id=None):
    """Closed-interval overlap for same account+meter (PRD §2.9)."""
    for c in db.commitments.values():
        if exclude_id is not None and c["id"] == exclude_id:
            continue
        if c["billing_account_id"] != account_id or c["meter"] != meter:
            continue
        cs = parse_dt(c["window_start_utc"])
        ce = parse_dt(c["window_end_utc"])
        if start_dt <= ce and cs <= end_dt:
            return True
    return False


@app.route("/api/billing-accounts/<aid>/commitments", methods=["POST"])
def create_commitment(aid):
    role = check_auth()
    require_roles(role, {"BillingAdmin"})
    account = _get_account(aid)
    body = get_body()
    meter = req_enum(body, "meter", METERS)
    start = req_dt(body, "window_start_utc")
    end = req_dt(body, "window_end_utc")
    if _commitment_windows_collide(account["id"], meter, start, end):
        raise commitment_window_overlap()
    if account["standing"] != "GOOD":
        raise account_delinquent()
    _check_account_occ(account, body)
    rec = new_record({
        "billing_account_id": account["id"],
        "meter": meter,
        "committed_quantity": req_int(body, "committed_quantity"),
        "consumed_quantity": 0,
        "expired_quantity": 0,
        "window_start_utc": body["window_start_utc"],
        "window_end_utc": body["window_end_utc"],
        "committed_unit_rate_cents": req_int(body, "committed_unit_rate_cents"),
        "overage_unit_rate_cents": req_int(body, "overage_unit_rate_cents"),
        "status": "DRAFT",
    })
    db.commitments[rec["id"]] = rec
    touch(account)
    return success_object(rec, 201)


@app.route("/api/billing-accounts/<aid>/commitments", methods=["GET"])
def list_commitments(aid):
    role = check_auth()
    require_roles(role, {"BillingAdmin", "FinanceReader"})
    account = _get_account(aid)
    records = [c for c in db.commitments.values()
               if c["billing_account_id"] == account["id"]]
    return _list(records, {
        "meter": request.args.get("meter"),
        "status": request.args.get("status"),
    })


def _get_commitment_under_account(aid, cid):
    account = _get_account(aid)
    commitment = lookup(db.commitments, cid)
    if commitment["billing_account_id"] != account["id"]:
        raise not_found()
    return account, commitment


@app.route("/api/billing-accounts/<aid>/commitments/<cid>/activate", methods=["POST"])
def activate_commitment(aid, cid):
    role = check_auth()
    require_roles(role, {"BillingAdmin"})
    account, commitment = _get_commitment_under_account(aid, cid)
    if commitment["status"] != "DRAFT":
        raise invalid_state("Commitment must be DRAFT to activate")
    start = parse_dt(commitment["window_start_utc"])
    end = parse_dt(commitment["window_end_utc"])
    if _commitment_windows_collide(account["id"], commitment["meter"], start, end,
                                   exclude_id=commitment["id"]):
        raise commitment_window_overlap()
    if account["standing"] != "GOOD":
        raise account_delinquent()
    commitment["status"] = "ACTIVE"
    touch(commitment)
    return success_object(commitment)


@app.route("/api/billing-accounts/<aid>/commitments/<cid>/top-up", methods=["POST"])
def top_up_commitment(aid, cid):
    role = check_auth()
    require_roles(role, {"BillingAdmin"})
    account, commitment = _get_commitment_under_account(aid, cid)
    if commitment["status"] != "EXHAUSTED":
        raise invalid_state("Commitment must be EXHAUSTED to top up")
    now = parse_dt(clock_utc())
    if now > parse_dt(commitment["window_end_utc"]):
        raise invalid_state("Logical clock has passed window_end_utc")
    body = get_body()
    top_up_quantity = req_int(body, "top_up_quantity")
    start = parse_dt(commitment["window_start_utc"])
    end = parse_dt(commitment["window_end_utc"])
    if _commitment_windows_collide(account["id"], commitment["meter"], start, end,
                                   exclude_id=commitment["id"]):
        raise commitment_window_overlap()
    commitment["committed_quantity"] += top_up_quantity
    commitment["status"] = "ACTIVE"
    touch(commitment)
    return success_object(commitment)


@app.route("/api/commitments/<cid>", methods=["GET"])
def flat_get_commitment(cid):
    role = check_auth()
    require_roles(role, {"BillingAdmin", "FinanceReader"})
    rec = lookup(db.commitments, cid)
    return success_object(rec)


@app.route("/api/commitments", methods=["GET"])
def flat_list_commitments():
    role = check_auth()
    require_roles(role, {"BillingAdmin", "FinanceReader"})
    return _list(db.commitments.values(), {
        "billing_account_id": request.args.get("billing_account_id"),
        "meter": request.args.get("meter"),
        "status": request.args.get("status"),
    })


# ===========================================================================
# Team
# ===========================================================================

@app.route("/api/billing-accounts/<aid>/teams", methods=["POST"])
def create_team(aid):
    role = check_auth()
    require_roles(role, {"BillingAdmin"})
    account = _get_account(aid)
    body = get_body()
    rec = new_record({
        "billing_account_id": account["id"],
        "name": req_str(body, "name"),
        "cost_center": req_str(body, "cost_center"),
    })
    db.teams[rec["id"]] = rec
    return success_object(rec, 201)


@app.route("/api/billing-accounts/<aid>/teams", methods=["GET"])
def list_teams(aid):
    role = check_auth()
    require_roles(role, {"BillingAdmin", "FinanceReader", "TeamLead"})
    account = _get_account(aid)
    records = [t for t in db.teams.values()
               if t["billing_account_id"] == account["id"]]
    return _list(records)


@app.route("/api/teams/<tid>", methods=["GET"])
def flat_get_team(tid):
    role = check_auth()
    require_roles(role, {"BillingAdmin", "FinanceReader", "TeamLead"})
    rec = lookup(db.teams, tid)
    return success_object(rec)


@app.route("/api/teams", methods=["GET"])
def flat_list_teams():
    role = check_auth()
    require_roles(role, {"BillingAdmin", "FinanceReader", "TeamLead"})
    return _list(db.teams.values(), {
        "billing_account_id": request.args.get("billing_account_id"),
    })


# ===========================================================================
# UsageRecord + TagPolicy governance
# ===========================================================================

@app.route("/api/billing-accounts/<aid>/billing-periods/<pid>/usage-records", methods=["POST"])
def create_usage_record(aid, pid):
    role = check_auth()
    require_roles(role, {"IngestionAgent", "BillingAdmin"})
    account, period = _get_period_under_account(aid, pid)
    _require_period_open(period)
    body = get_body()
    meter = req_enum(body, "meter", METERS)
    quantity = req_int(body, "quantity")
    team_id = opt_str(body, "team_id")
    if team_id is not None:
        team = lookup(db.teams, team_id)
        if team["billing_account_id"] != account["id"]:
            raise not_found()

    # Tag governance (PRD §3.6). The caller's identity supplies the tag value.
    user_id = request.headers.get("X-User-ID")
    policies = [p for p in db.tag_policies.values()
                if p["billing_account_id"] == account["id"]]
    has_block = any(p["enforcement"] == "BLOCK" for p in policies)
    has_warn = any(p["enforcement"] == "WARN" for p in policies)
    compliant = team_id is not None
    if policies:
        def policy_ok(pol):
            if team_id is None:
                return False
            team = db.teams.get(team_id)
            if team is None:
                return False
            if pol["required_tag_key"] == "team_id":
                value = team_id
            else:
                value = user_id
            return value in pol["allowed_values"]
        compliant = all(policy_ok(p) for p in policies)
    if has_block and not compliant:
        raise tag_policy_violation()
    if not has_block and has_warn and not compliant:
        compliant = False

    rec = new_record({
        "billing_period_id": period["id"],
        "team_id": team_id,
        "meter": meter,
        "quantity": quantity,
        "tag_compliant": compliant,
        "disputed": False,
    })
    db.usage_records[rec["id"]] = rec
    bump_meter(period, account, meter, quantity)
    return success_object(rec, 201)


@app.route("/api/billing-accounts/<aid>/billing-periods/<pid>/usage-records", methods=["GET"])
def list_usage_records(aid, pid):
    role = check_auth()
    require_roles(role, {"BillingAdmin", "FinanceReader", "TeamLead"})
    account, period = _get_period_under_account(aid, pid)
    records = [u for u in db.usage_records.values()
               if u["billing_period_id"] == period["id"]]
    return _list(records, {
        "team_id": request.args.get("team_id"),
        "tag_compliant": parse_bool_param("tag_compliant"),
        "meter": request.args.get("meter"),
    })


@app.route("/api/usage-records/<uid>", methods=["GET"])
def flat_get_usage_record(uid):
    role = check_auth()
    require_roles(role, {"BillingAdmin", "FinanceReader", "TeamLead"})
    rec = lookup(db.usage_records, uid)
    return success_object(rec)


@app.route("/api/usage-records", methods=["GET"])
def flat_list_usage_records():
    role = check_auth()
    require_roles(role, {"BillingAdmin", "FinanceReader", "TeamLead"})
    return _list(db.usage_records.values(), {
        "billing_period_id": request.args.get("billing_period_id"),
        "team_id": request.args.get("team_id"),
        "meter": request.args.get("meter"),
        "tag_compliant": parse_bool_param("tag_compliant"),
    })


# ===========================================================================
# AttributionDispute
# ===========================================================================

@app.route("/api/billing-accounts/<aid>/usage-records/<uid>/disputes", methods=["POST"])
def create_attribution_dispute(aid, uid):
    role = check_auth()
    require_roles(role, {"TeamLead"})
    account = _get_account(aid)
    usage = lookup(db.usage_records, uid)
    period = db.billing_periods.get(usage["billing_period_id"])
    if period is None or period["billing_account_id"] != account["id"]:
        raise not_found()
    body = get_body()
    raised_by = req_str(body, "raised_by_team_id")
    team = lookup(db.teams, raised_by)
    if team["billing_account_id"] != account["id"]:
        raise not_found()
    reason = req_str(body, "reason")
    rec = new_record({
        "usage_record_id": usage["id"],
        "raised_by_team_id": raised_by,
        "reason": reason,
        "status": "OPEN",
    })
    db.attribution_disputes[rec["id"]] = rec
    usage["disputed"] = True
    touch(usage)
    return success_object(rec, 201)


def _get_dispute_under_account(aid, did):
    account = _get_account(aid)
    dispute = lookup(db.attribution_disputes, did)
    usage = db.usage_records.get(dispute["usage_record_id"])
    if usage is None:
        raise not_found()
    period = db.billing_periods.get(usage["billing_period_id"])
    if period is None or period["billing_account_id"] != account["id"]:
        raise not_found()
    return account, dispute, usage, period


@app.route("/api/billing-accounts/<aid>/attribution-disputes/<did>/accept", methods=["POST"])
def accept_dispute(aid, did):
    role = check_auth()
    require_roles(role, {"BillingAdmin"})
    account, dispute, usage, period = _get_dispute_under_account(aid, did)
    if period["status"] != "OPEN":
        raise period_closed("Dispute acceptance requires the usage record's period to be OPEN")
    if dispute["status"] != "OPEN":
        raise invalid_state("Dispute must be OPEN to accept")
    dispute["status"] = "ACCEPTED"
    touch(dispute)
    usage["disputed"] = False
    usage["team_id"] = dispute["raised_by_team_id"]
    touch(usage)
    return success_object(dispute)


@app.route("/api/billing-accounts/<aid>/attribution-disputes/<did>/reject", methods=["POST"])
def reject_dispute(aid, did):
    role = check_auth()
    require_roles(role, {"BillingAdmin"})
    account, dispute, usage, period = _get_dispute_under_account(aid, did)
    if dispute["status"] != "OPEN":
        raise invalid_state("Dispute must be OPEN to reject")
    dispute["status"] = "REJECTED"
    touch(dispute)
    usage["disputed"] = False
    touch(usage)
    return success_object(dispute)


@app.route("/api/attribution-disputes/<did>", methods=["GET"])
def flat_get_attribution_dispute(did):
    role = check_auth()
    require_roles(role, {"BillingAdmin", "FinanceReader", "TeamLead"})
    rec = lookup(db.attribution_disputes, did)
    return success_object(rec)


@app.route("/api/attribution-disputes", methods=["GET"])
def flat_list_attribution_disputes():
    role = check_auth()
    require_roles(role, {"BillingAdmin", "FinanceReader", "TeamLead"})
    return _list(db.attribution_disputes.values(), {
        "usage_record_id": request.args.get("usage_record_id"),
        "raised_by_team_id": request.args.get("raised_by_team_id"),
        "status": request.args.get("status"),
    })


# ===========================================================================
# TagPolicy
# ===========================================================================

@app.route("/api/billing-accounts/<aid>/tag-policies", methods=["POST"])
def create_tag_policy(aid):
    role = check_auth()
    require_roles(role, {"BillingAdmin"})
    account = _get_account(aid)
    body = get_body()
    rec = new_record({
        "billing_account_id": account["id"],
        "required_tag_key": req_str(body, "required_tag_key"),
        "allowed_values": req_list_of_str(body, "allowed_values"),
        "enforcement": req_enum(body, "enforcement", ENFORCEMENTS),
    })
    db.tag_policies[rec["id"]] = rec
    return success_object(rec, 201)


@app.route("/api/billing-accounts/<aid>/tag-policies", methods=["GET"])
def list_tag_policies(aid):
    role = check_auth()
    require_roles(role, {"BillingAdmin", "FinanceReader"})
    account = _get_account(aid)
    records = [p for p in db.tag_policies.values()
               if p["billing_account_id"] == account["id"]]
    return _list(records)


@app.route("/api/tag-policies/<tid>", methods=["GET"])
def flat_get_tag_policy(tid):
    role = check_auth()
    require_roles(role, {"BillingAdmin", "FinanceReader"})
    rec = lookup(db.tag_policies, tid)
    return success_object(rec)


@app.route("/api/tag-policies", methods=["GET"])
def flat_list_tag_policies():
    role = check_auth()
    require_roles(role, {"BillingAdmin", "FinanceReader"})
    return _list(db.tag_policies.values(), {
        "billing_account_id": request.args.get("billing_account_id"),
    })


# ===========================================================================
# Monitor
# ===========================================================================

@app.route("/api/billing-accounts/<aid>/monitors", methods=["POST"])
def create_monitor(aid):
    role = check_auth()
    require_roles(role, {"BillingAdmin", "TeamLead"})
    account = _get_account(aid)
    body = get_body()
    name = req_str(body, "name")
    kind = req_enum(body, "monitor_kind", MONITOR_KINDS)
    plan = get_plan_for_account(account)
    if plan is not None:
        active_count = sum(
            1 for m in db.monitors.values()
            if m["billing_account_id"] == account["id"] and m["status"] == "ACTIVE"
        )
        if active_count >= plan["max_monitors"]:
            raise plan_limit()
    rec = new_record({
        "billing_account_id": account["id"],
        "name": name,
        "monitor_kind": kind,
        "status": "ACTIVE",
    })
    db.monitors[rec["id"]] = rec
    return success_object(rec, 201)


@app.route("/api/billing-accounts/<aid>/monitors", methods=["GET"])
def list_monitors(aid):
    role = check_auth()
    require_roles(role, {"BillingAdmin", "FinanceReader", "TeamLead"})
    account = _get_account(aid)
    records = [m for m in db.monitors.values()
               if m["billing_account_id"] == account["id"]]
    return _list(records, {
        "status": request.args.get("status"),
        "monitor_kind": request.args.get("monitor_kind"),
    })


def _get_monitor_under_account(aid, mid):
    account = _get_account(aid)
    monitor = lookup(db.monitors, mid)
    if monitor["billing_account_id"] != account["id"]:
        raise not_found()
    return account, monitor


@app.route("/api/billing-accounts/<aid>/monitors/<mid>/mute", methods=["POST"])
def mute_monitor(aid, mid):
    role = check_auth()
    require_roles(role, {"BillingAdmin", "TeamLead"})
    account, monitor = _get_monitor_under_account(aid, mid)
    if monitor["status"] != "ACTIVE":
        raise invalid_state("Only an ACTIVE monitor can be muted")
    monitor["status"] = "MUTED"
    touch(monitor)
    return success_object(monitor)


@app.route("/api/billing-accounts/<aid>/monitors/<mid>/delete", methods=["POST"])
def delete_monitor(aid, mid):
    role = check_auth()
    require_roles(role, {"BillingAdmin"})
    account, monitor = _get_monitor_under_account(aid, mid)
    if monitor["status"] == "DELETED":
        raise invalid_state("Monitor is already DELETED")
    monitor["status"] = "DELETED"
    touch(monitor)
    return success_object(monitor)


@app.route("/api/monitors/<mid>", methods=["GET"])
def flat_get_monitor(mid):
    role = check_auth()
    require_roles(role, {"BillingAdmin", "FinanceReader", "TeamLead"})
    rec = lookup(db.monitors, mid)
    return success_object(rec)


@app.route("/api/monitors", methods=["GET"])
def flat_list_monitors():
    role = check_auth()
    require_roles(role, {"BillingAdmin", "FinanceReader", "TeamLead"})
    return _list(db.monitors.values(), {
        "billing_account_id": request.args.get("billing_account_id"),
        "status": request.args.get("status"),
        "monitor_kind": request.args.get("monitor_kind"),
    })


# ===========================================================================
# Invoice / InvoiceLine
# ===========================================================================

def _get_invoice_under_account(aid, iid):
    account = _get_account(aid)
    invoice = lookup(db.invoices, iid)
    period = db.billing_periods.get(invoice["billing_period_id"])
    if period is None or period["billing_account_id"] != account["id"]:
        raise not_found()
    return account, invoice


@app.route("/api/billing-accounts/<aid>/invoices/<iid>", methods=["GET"])
def get_invoice(aid, iid):
    role = check_auth()
    require_roles(role, {"BillingAdmin", "FinanceReader"})
    account, invoice = _get_invoice_under_account(aid, iid)
    return success_object(invoice)


@app.route("/api/billing-accounts/<aid>/invoices/<iid>/lines", methods=["GET"])
def list_invoice_lines(aid, iid):
    role = check_auth()
    require_roles(role, {"BillingAdmin", "FinanceReader"})
    account, invoice = _get_invoice_under_account(aid, iid)
    lines = [l for l in db.invoice_lines.values() if l["invoice_id"] == invoice["id"]]
    lines.sort(key=lambda l: (l.get("created_at", ""), l["id"]))
    return success_array(lines, len(lines), len(lines) if lines else 10, 0)


@app.route("/api/billing-accounts/<aid>/invoices/<iid>/issue", methods=["POST"])
def issue_invoice(aid, iid):
    role = check_auth()
    require_roles(role, {"BillingAdmin"})
    account, invoice = _get_invoice_under_account(aid, iid)
    if invoice["status"] != "DRAFT":
        raise invalid_state("Invoice must be DRAFT to issue")
    total = 0
    for line in db.invoice_lines.values():
        if line["invoice_id"] != invoice["id"]:
            continue
        committed_amount = line["committed_quantity"] * line["committed_unit_rate_cents"]
        overage_amount = line["overage_quantity"] * line["overage_unit_rate_cents"]
        line["amount_cents"] = committed_amount + overage_amount
        total += line["amount_cents"]
    invoice["total_amount_cents"] = total
    invoice["status"] = "ISSUED"
    touch(invoice)
    return success_object(invoice)


@app.route("/api/billing-accounts/<aid>/invoices/<iid>/pay", methods=["POST"])
def pay_invoice(aid, iid):
    role = check_auth()
    require_roles(role, {"BillingAdmin"})
    account, invoice = _get_invoice_under_account(aid, iid)
    if invoice["status"] != "ISSUED":
        raise invalid_state("Invoice must be ISSUED to pay")
    invoice["status"] = "PAID"
    touch(invoice)
    return success_object(invoice)


@app.route("/api/billing-accounts/<aid>/invoices/<iid>/void", methods=["POST"])
def void_invoice(aid, iid):
    role = check_auth()
    require_roles(role, {"BillingAdmin"})
    account, invoice = _get_invoice_under_account(aid, iid)
    if invoice["status"] != "ISSUED":
        raise invalid_state("Invoice must be ISSUED to void")
    invoice["status"] = "VOID"
    touch(invoice)
    return success_object(invoice)


@app.route("/api/invoices/<iid>", methods=["GET"])
def flat_get_invoice(iid):
    role = check_auth()
    require_roles(role, {"BillingAdmin", "FinanceReader"})
    rec = lookup(db.invoices, iid)
    return success_object(rec)


@app.route("/api/invoices", methods=["GET"])
def flat_list_invoices():
    role = check_auth()
    require_roles(role, {"BillingAdmin", "FinanceReader"})
    return _list(db.invoices.values(), {
        "billing_period_id": request.args.get("billing_period_id"),
        "status": request.args.get("status"),
    })


@app.route("/api/invoice-lines/<lid>", methods=["GET"])
def flat_get_invoice_line(lid):
    role = check_auth()
    require_roles(role, {"BillingAdmin", "FinanceReader"})
    rec = lookup(db.invoice_lines, lid)
    return success_object(rec)


@app.route("/api/invoice-lines", methods=["GET"])
def flat_list_invoice_lines():
    role = check_auth()
    require_roles(role, {"BillingAdmin", "FinanceReader"})
    return _list(db.invoice_lines.values(), {
        "invoice_id": request.args.get("invoice_id"),
    })


# ===========================================================================
# Chargeback (PRD §3.9)
# ===========================================================================

@app.route("/api/billing-accounts/<aid>/billing-periods/<pid>/chargeback", methods=["GET"])
def chargeback(aid, pid):
    role = check_auth()
    require_roles(role, {"FinanceReader", "BillingAdmin"})
    account, period = _get_period_under_account(aid, pid)
    usage = [u for u in db.usage_records.values()
             if u["billing_period_id"] == period["id"]]
    by_team = {}
    team_names = {}
    for t in db.teams.values():
        if t["billing_account_id"] == account["id"]:
            team_names[t["id"]] = t["name"]
    unattributed = 0
    for u in usage:
        amount = rate_usage_amount_cents(account, u["meter"], u["quantity"])
        if u["tag_compliant"] and u["team_id"] and not u["disputed"]:
            by_team[u["team_id"]] = by_team.get(u["team_id"], 0) + amount
        elif (not u["tag_compliant"]) or u["team_id"] is None:
            if not u["disputed"]:
                unattributed += amount
        # disputed records sit out of the rollup entirely
    team_entries = []
    for tid in sorted(by_team.keys(), key=lambda t: team_names.get(t, t)):
        team_entries.append({
            "team_id": tid,
            "team_name": team_names.get(tid),
            "total_cents": by_team[tid],
        })
    return success_object({
        "by_team": team_entries,
        "unattributed_cents": unattributed,
    })


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "10000"))
    app.run(host="0.0.0.0", port=port)
