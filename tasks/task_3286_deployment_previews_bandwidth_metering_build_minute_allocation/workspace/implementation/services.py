"""Business logic: billing, slugs, alerts, spend caps, cascades, sweeps."""

import hashlib
import math
import re
from datetime import timedelta
from decimal import Decimal, ROUND_HALF_UP

from db import db, new_id, now_iso, touch
from errors import err

REGION_EDGE_MULTIPLIER = {"IAD": 1, "SFO": 1, "FRA": 2, "SIN": 3}
GB_BYTES = 1_000_000_000
DEFAULT_ESTIMATE_MINUTES = 2
CERT_VALIDITY_DAYS = 90


# ---------------------------------------------------------------------------
# Serializers
# ---------------------------------------------------------------------------

def plan_view(p):
    return {k: p[k] for k in (
        "id", "tier", "seat_limit", "included_build_minutes",
        "build_concurrency_limit", "included_bandwidth_gb",
        "included_invocations_millions", "bandwidth_tier1_rate_cents_per_gb",
        "bandwidth_tier2_rate_cents_per_gb", "bandwidth_tier2_threshold_gb",
        "invocation_rate_cents_per_million", "seat_price_cents_monthly",
        "overage_build_minute_rate_cents", "created_at", "updated_at",
        "version",
    )}


def team_view(t):
    return {k: t[k] for k in (
        "id", "name", "plan_tier", "seat_limit", "included_build_minutes",
        "build_concurrency_limit", "included_bandwidth_gb",
        "included_invocations_millions", "seats_used",
        "prorated_charges_cents", "created_at", "updated_at", "version",
    )}


def member_view(m):
    return {k: m[k] for k in (
        "id", "team_id", "user_email", "role", "created_at", "updated_at",
        "version",
    )}


def project_view(p):
    return {k: p[k] for k in (
        "id", "team_id", "name", "production_branch", "framework",
        "preview_protection", "status", "suspended_reason",
        "production_deployment_id", "created_at", "updated_at", "version",
    )}


def deployment_view(d):
    return {k: d[k] for k in (
        "id", "project_id", "branch", "git_ref", "commit_sha", "target",
        "region", "access_protection", "status", "url_slug", "url",
        "estimated_build_minutes", "billable_minutes",
        "build_duration_seconds", "completed_at",
        "previous_promoted_deployment_id", "created_at", "updated_at",
        "version",
    )}


def env_var_view(e):
    v = {k: e[k] for k in (
        "id", "project_id", "key", "scopes", "is_secret", "created_at",
        "updated_at", "version",
    )}
    v["value"] = None if e.get("is_secret") else e.get("value")
    return v


def domain_view(d):
    return {k: d[k] for k in (
        "id", "project_id", "name", "certificate_id",
        "verification_status", "status", "created_at", "updated_at",
        "version",
    )}


def certificate_view(c):
    return {k: c[k] for k in (
        "id", "domain_id", "issuer", "status", "not_before", "not_after",
        "auto_renewed_from_id", "created_at", "updated_at", "version",
    )}


def redirect_view(r):
    return {k: r[k] for k in (
        "id", "project_id", "source", "target", "status_code", "priority",
        "created_at", "updated_at", "version",
    )}


def usage_period_view(p):
    return {k: p[k] for k in (
        "id", "team_id", "period_start", "period_end", "status",
        "bandwidth_bytes", "invocations", "build_minutes_used",
        "projected_bill_cents", "final_bill_cents", "total_due_cents",
        "created_at", "updated_at", "version",
    )}


def usage_event_view(e):
    return {k: e[k] for k in (
        "id", "period_id", "team_id", "deployment_id", "event_type",
        "bandwidth_bytes", "invocations", "region", "edge_execution",
        "status", "recorded_at", "effective_rate_cents", "created_at",
    )}


def alert_rule_view(a):
    return {k: a[k] for k in (
        "id", "team_id", "metric", "threshold_value", "window_minutes",
        "status", "last_fired_at", "created_at", "updated_at", "version",
    )}


def spend_cap_view(s):
    return {k: s[k] for k in (
        "id", "team_id", "cap_cents", "action", "status", "tripped_at",
        "created_at", "updated_at", "version",
    )}


# ---------------------------------------------------------------------------
# Lookups
# ---------------------------------------------------------------------------

def get_team_or_404(team_id):
    t = db.teams.get(team_id)
    if not t:
        err("ERR_TEAM_NOT_FOUND", "Team id does not exist")
    return t


def get_project_or_404(project_id):
    p = db.projects.get(project_id)
    if not p:
        err("ERR_PROJECT_NOT_FOUND", "Project id does not exist")
    return p


def get_deployment_or_404(dep_id):
    d = db.deployments.get(dep_id)
    if not d:
        err("ERR_DEPLOYMENT_NOT_FOUND", "Deployment id does not exist")
    return d


def get_domain_or_404(domain_id):
    d = db.domains.get(domain_id)
    if not d:
        err("ERR_DOMAIN_NOT_FOUND", "Domain id does not exist")
    return d


def get_certificate_or_404(cert_id):
    c = db.certificates.get(cert_id)
    if not c:
        err("ERR_CERTIFICATE_NOT_FOUND", "Certificate id does not exist")
    return c


def get_member_or_404(member_id):
    m = db.members.get(member_id)
    if not m:
        err("ERR_MEMBER_NOT_FOUND", "Member id does not exist")
    return m


def open_period_for_team(team_id):
    for p in db.usage_periods.values():
        if p["team_id"] == team_id and p["status"] == "OPEN":
            return p
    return None


# ---------------------------------------------------------------------------
# Slug
# ---------------------------------------------------------------------------

def make_slug(project_id, branch, commit_sha):
    base = branch.lower()
    base = re.sub(r"[^a-z0-9-]", "-", base)
    base = re.sub(r"-+", "-", base)
    base = base.strip("-")
    base = base[:40]
    digest = hashlib.sha256(
        f"{project_id}|{branch}|{commit_sha}".encode("utf-8")
    ).hexdigest()[:8]
    return f"{base}-{digest}"


# ---------------------------------------------------------------------------
# Billing
# ---------------------------------------------------------------------------

def compute_charge(period, team, events):
    """usage_overage_charge over the given event set.

    Returns total cents; bandwidth/invocation/build derived from period
    aggregates and the given events (regional edge is per-event).
    """
    plan = db.plan_by_tier.get(team["plan_tier"])

    bw_bytes = sum(e["bandwidth_bytes"] for e in events)
    invocations = sum(e["invocations"] for e in events)

    total_gb_ceil = math.ceil(bw_bytes / GB_BYTES) if bw_bytes > 0 else 0
    overage_gb = max(0, total_gb_ceil - team["included_bandwidth_gb"])
    bandwidth_cents = (
        min(overage_gb, plan["bandwidth_tier2_threshold_gb"])
        * plan["bandwidth_tier1_rate_cents_per_gb"]
        + max(0, overage_gb - plan["bandwidth_tier2_threshold_gb"])
        * plan["bandwidth_tier2_rate_cents_per_gb"]
    )

    billable_millions_ceil = math.ceil(invocations / 1_000_000) if invocations > 0 else 0
    overage_millions = max(
        0, billable_millions_ceil - team["included_invocations_millions"]
    )
    invocation_cents = overage_millions * plan["invocation_rate_cents_per_million"]

    regional_edge_cents = 0
    for e in events:
        if e.get("edge_execution"):
            regional_edge_cents += (
                math.ceil(e["invocations"] / 1_000_000)
                * REGION_EDGE_MULTIPLIER[e["region"]]
            )

    build_overage = max(
        0, period["build_minutes_used"] - team["included_build_minutes"]
    )
    build_cents = build_overage * plan["overage_build_minute_rate_cents"]

    return bandwidth_cents + invocation_cents + regional_edge_cents + build_cents


def recompute_projected_bill(period):
    team = db.teams[period["team_id"]]
    events = [
        e for e in db.usage_events.values()
        if e["period_id"] == period["id"]
        and e["status"] in ("RECORDED", "ESTIMATED")
    ]
    period["projected_bill_cents"] = compute_charge(period, team, events)


def stamp_effective_rates(period):
    """Final-variant per-event effective_rate_cents, chronological order.

    Bandwidth events share the period marginal tier at their cumulative
    position; invocations likewise per cumulative million; edge fees are
    per-event additive; build minutes are not per-event (no event link).
    """
    team = db.teams[period["team_id"]]
    plan = db.plan_by_tier.get(team["plan_tier"])
    events = sorted(
        (e for e in db.usage_events.values() if e["period_id"] == period["id"]),
        key=lambda e: (e["recorded_at_dt"], e["created_at_dt"]),
    )

    included_bw_bytes = team["included_bandwidth_gb"] * GB_BYTES
    included_inv = team["included_invocations_millions"] * 1_000_000
    cum_bw = 0
    cum_inv = 0
    for e in events:
        rate = 0
        if e["event_type"] == "BANDWIDTH":
            prev_gb = math.ceil(cum_bw / GB_BYTES) if cum_bw > 0 else 0
            cum_bw += e["bandwidth_bytes"]
            new_gb = math.ceil(cum_bw / GB_BYTES) if cum_bw > 0 else 0
            prev_over = max(0, prev_gb - team["included_bandwidth_gb"])
            new_over = max(0, new_gb - team["included_bandwidth_gb"])
            # marginal cents for the delta in overage GB
            def tier_cents(over):
                return (
                    min(over, plan["bandwidth_tier2_threshold_gb"])
                    * plan["bandwidth_tier1_rate_cents_per_gb"]
                    + max(0, over - plan["bandwidth_tier2_threshold_gb"])
                    * plan["bandwidth_tier2_rate_cents_per_gb"]
                )
            rate = tier_cents(new_over) - tier_cents(prev_over)
            # suppress unused vars
            _ = included_bw_bytes
        else:
            prev_m = math.ceil(cum_inv / 1_000_000) if cum_inv > 0 else 0
            cum_inv += e["invocations"]
            new_m = math.ceil(cum_inv / 1_000_000) if cum_inv > 0 else 0
            prev_over = max(0, prev_m - team["included_invocations_millions"])
            new_over = max(0, new_m - team["included_invocations_millions"])
            rate = (new_over - prev_over) * plan["invocation_rate_cents_per_million"]
        if e.get("edge_execution"):
            rate += (
                math.ceil(e["invocations"] / 1_000_000)
                * REGION_EDGE_MULTIPLIER[e["region"]]
            )
        e["effective_rate_cents"] = rate


# ---------------------------------------------------------------------------
# Seat proration
# ---------------------------------------------------------------------------

def prorate_seat_charge(team):
    period = open_period_for_team(team["id"])
    if not period:
        return
    plan = db.plan_by_tier.get(team["plan_tier"])
    days_total = max(
        1, (period["period_end_dt"] - period["period_start_dt"]).days
    )
    days_remaining = max(0, (period["period_end_dt"] - db.clock).days)
    price = Decimal(plan["seat_price_cents_monthly"])
    charge = (price * days_remaining / days_total).quantize(
        Decimal("1"), rounding=ROUND_HALF_UP
    )
    team["prorated_charges_cents"] += int(charge)


# ---------------------------------------------------------------------------
# Alerts & spend cap
# ---------------------------------------------------------------------------

def windowed_metric(rule, period):
    from db import parse_ts  # local to avoid cycle at import time
    window_start = db.clock - timedelta(minutes=rule["window_minutes"])
    if rule["metric"] == "SPEND_CENTS":
        return period["projected_bill_cents"] if period else 0
    if rule["metric"] in ("BANDWIDTH_BYTES", "INVOCATIONS"):
        if not period:
            return 0
        total = 0
        for e in db.usage_events.values():
            if e["period_id"] != period["id"]:
                continue
            if e["recorded_at_dt"] < window_start:
                continue
            if rule["metric"] == "BANDWIDTH_BYTES":
                total += e["bandwidth_bytes"]
            else:
                total += e["invocations"]
        return total
    if rule["metric"] == "BUILD_MINUTES":
        total = 0
        for d in db.deployments.values():
            if d.get("completed_at_dt") is None:
                continue
            if d["completed_at_dt"] < window_start:
                continue
            proj = db.projects.get(d["project_id"])
            if not proj or proj["team_id"] != rule["team_id"]:
                continue
            total += d.get("billable_minutes") or 0
        return total
    return 0


def evaluate_alerts(team_id):
    period = open_period_for_team(team_id)
    for rule in db.alert_rules.values():
        if rule["team_id"] != team_id or rule["status"] != "ACTIVE":
            continue
        metric = windowed_metric(rule, period)
        if metric >= rule["threshold_value"]:
            rule["status"] = "FIRED"
            rule["last_fired_at"] = now_iso()
            rule["last_fired_at_dt"] = db.clock
            touch(rule)


def evaluate_spend_cap(team_id):
    period = open_period_for_team(team_id)
    if not period:
        return
    cap = active_spend_cap(team_id)
    if not cap:
        return
    if period["projected_bill_cents"] >= cap["cap_cents"]:
        cap["status"] = "TRIPPED"
        cap["tripped_at"] = now_iso()
        touch(cap)
        if cap["action"] == "BLOCK_DEPLOYS_AND_SUSPEND":
            for p in db.projects.values():
                if p["team_id"] == team_id and p["status"] == "ACTIVE":
                    p["status"] = "SUSPENDED"
                    p["suspended_reason"] = "SPEND_CAP_BREACHED"
                    touch(p)


def active_spend_cap(team_id):
    for c in db.spend_caps.values():
        if c["team_id"] == team_id and c["status"] == "ACTIVE":
            return c
    return None


def tripped_spend_cap(team_id):
    for c in db.spend_caps.values():
        if c["team_id"] == team_id and c["status"] == "TRIPPED":
            return c
    return None


def alert_auto_reset_sweep():
    for rule in db.alert_rules.values():
        if rule["status"] != "FIRED":
            continue
        last = rule.get("last_fired_at_dt")
        if last is None:
            continue
        if db.clock >= last + timedelta(minutes=rule["window_minutes"]):
            period = open_period_for_team(rule["team_id"])
            if windowed_metric(rule, period) < rule["threshold_value"]:
                rule["status"] = "ACTIVE"
                touch(rule)


# ---------------------------------------------------------------------------
# Certificate expiry sweep
# ---------------------------------------------------------------------------

def certificate_expiry_sweep():
    for cert in list(db.certificates.values()):
        if cert["status"] == "ACTIVE" and cert.get("not_after_dt") is not None \
                and db.clock >= cert["not_after_dt"]:
            cert["status"] = "EXPIRED"
            touch(cert)
            domain = db.domains.get(cert["domain_id"])
            if domain:
                if domain.get("certificate_id") == cert["id"]:
                    domain["certificate_id"] = None
                domain["status"] = "SUSPENDED"
                touch(domain)
                if domain["verification_status"] == "VERIFIED":
                    create_certificate(domain, auto_renewed_from_id=cert["id"])


# ---------------------------------------------------------------------------
# Certificates
# ---------------------------------------------------------------------------

def create_certificate(domain, auto_renewed_from_id=None):
    cert = {
        "id": new_id(),
        "domain_id": domain["id"],
        "issuer": "LETSENCRYPT",
        "status": "ISSUING",
        "not_before": None,
        "not_after": None,
        "not_after_dt": None,
        "auto_renewed_from_id": auto_renewed_from_id,
        "created_at": now_iso(),
        "updated_at": now_iso(),
        "version": 1,
        "created_at_dt": db.clock,
    }
    db.certificates[cert["id"]] = cert
    return cert
