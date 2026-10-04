"""Calculation rules (SCAFFOLD section 1.3).  Decimal arithmetic only."""
from decimal import Decimal, ROUND_DOWN

from core.db import DB, dec, rhu, rhu_int

TIER_RATE_LOW = 145
TIER_RATE_MID = 118
TIER_RATE_HIGH = 96
TIER_LOW_MAX_SQFT = 250000
TIER_MID_MAX_SQFT = 750000
COMMISSION_CREDIT_FLOOR_CENTS = 10000

MARKET_BENCHMARK_CENTS_PER_SQFT = 1750
SERVICE_LEVEL_SHORTFALL_BASE_CENTS = 3000000
SAVINGS_SHORTFALL_BASE_CENTS = 2000000
GAINSHARE_RATE_BPS = 2500
W_QUALITY_COMPLETE = 6000
W_RESPONSE_COMPLETE = 4000
W_QUALITY_BASIC = 5000
W_RESPONSE_BASIC = 5000
COST_INFLATION_CAP = Decimal("1.10")
SENIOR_BROKER_SHARE_BPS = 6000
STANDARD_BROKER_SHARE_BPS = 4500
PRIOR_BASE_LIMIT_BPS = 300
LEVEL_MANAGER_MAX_CENTS = 25000000
LEVEL_DIRECTOR_MAX_CENTS = 75000000

LEVEL_ORDER = {"MANAGER": 0, "DIRECTOR": 1, "ACCOUNT_EXECUTIVE": 2}


def tier_rate(portfolio_sqft):
    if portfolio_sqft <= TIER_LOW_MAX_SQFT:
        return TIER_RATE_LOW
    if portfolio_sqft <= TIER_MID_MAX_SQFT:
        return TIER_RATE_MID
    return TIER_RATE_HIGH


def record_due_cents(record):
    raw = dec(record.get("base_rent_cents", 0)) * dec(record.get("commission_pct", 0))
    return max(rhu(raw, 2), dec(COMMISSION_CREDIT_FLOOR_CENTS))


def ordered_records(account_id):
    recs = DB.children("commission_records", account_id)
    return sorted(recs, key=lambda r: (r.get("accrual_date"), r.get("_seq", 0)))


def commission_credit_nets_fee(account):
    """Gross fee tiered on portfolio_sqft; credits rounded per record then summed."""
    sqft = int(account.get("portfolio_sqft") or 0)
    rate = tier_rate(sqft)
    gross_fee = dec(rate) * dec(sqft)
    total = Decimal(0)
    self_perform = Decimal(0)
    third_party = Decimal(0)
    for r in ordered_records(account["id"]):
        due = record_due_cents(r)
        total += due
        if r.get("commission_source") == "SELF_PERFORM":
            self_perform += due
        else:
            third_party += due
    applied_credit = min(total, gross_fee + self_perform)
    annual_net_fee = gross_fee - third_party
    return {
        "gross_fee_cents": gross_fee,
        "total_credit_cents": total,
        "self_perform_credit_cents": self_perform,
        "third_party_credit_cents": third_party,
        "applied_credit_cents": applied_credit,
        "annual_net_fee_cents": annual_net_fee,
    }


def fee_ledger_credit_cents(account_id):
    total = Decimal(0)
    for r in ordered_records(account_id):
        total += record_due_cents(r)
    return total


def savings_realization_score(treq, variant):
    lease = DB.get("leases", treq.get("lease_id")) or {}
    sqft = int(lease.get("leased_sqft") or 0)
    term = int(treq.get("requested_term_months") or 0)
    prior = dec(treq.get("prior_rent_cents_per_year") or 0)
    benchmark_annual = dec(MARKET_BENCHMARK_CENTS_PER_SQFT) * dec(sqft)
    if variant == "final":
        proposed = dec(treq.get("proposed_rent_cents_per_year") or 0)
        savings = (prior - proposed) * dec(term) / dec(12)
    else:
        savings = max(Decimal(0), prior - benchmark_annual) * dec(term) / dec(12)
    return rhu_int(savings)


def kpi_net_adjustment(kpi):
    """Composite rule; both legs compare >= against the same threshold."""
    family = kpi.get("kpi_family")
    base = (SERVICE_LEVEL_SHORTFALL_BASE_CENTS if family == "SERVICE_LEVEL"
            else SAVINGS_SHORTFALL_BASE_CENTS)
    target = dec(kpi.get("target_value") or 0)
    actual = dec(kpi.get("actual_value") or 0)
    if actual >= target:
        shortfall = Decimal(0)
        gainshare = rhu((actual - target) * dec(GAINSHARE_RATE_BPS) / dec(10000), 2)
    else:
        shortfall = rhu(dec(base) * (target - actual) / dec(10000), 2)
        gainshare = Decimal(0)
    penalty = shortfall
    net = gainshare - penalty
    return {
        "gainshare_cents": gainshare,
        "penalty_cents": penalty,
        "net_adjustment_cents": net,
        "shortfall_component": shortfall,
    }


def weighted_scorecard_composite(scorecard, account):
    tier = (account or {}).get("platform_tier")
    if tier in ("COMPLETE", "ENTERPRISE"):
        wq, wr = W_QUALITY_COMPLETE, W_RESPONSE_COMPLETE
    else:
        wq, wr = W_QUALITY_BASIC, W_RESPONSE_BASIC
    weighted_numerator = (dec(scorecard.get("quality_bps") or 0) * dec(wq)
                          + dec(scorecard.get("response_bps") or 0) * dec(wr))
    raw = weighted_numerator / dec(10000)
    composite_raw = rhu(raw, 2)
    composite = min(Decimal(10000), max(Decimal(0), composite_raw))
    return int(composite.to_integral_value(rounding=ROUND_DOWN))


def _project_sites(project_id):
    sites = DB.rows("facility_sites")
    sel = [s for s in sites if s.get("consolidation_project_id") == project_id]
    return sorted(sel, key=lambda s: (s.get("created_at"), s.get("site_name") or ""))


def consolidation_savings_estimate(project, variant):
    sites = _project_sites(project["id"])
    rates = project.get("per_site_rates") or []
    reds = project.get("per_site_sqft_reductions") or []
    round_then_sum = Decimal(0)
    raw_sum = Decimal(0)
    for i, _site in enumerate(sites):
        rate = dec(rates[i]) if i < len(rates) else Decimal(0)
        area = dec(reds[i]) if i < len(reds) else Decimal(0)
        raw_i = area * rate
        round_then_sum += rhu(raw_i, 2)
        raw_sum += raw_i
    sum_then_round = rhu(raw_sum, 2)
    factor = dec(project.get("cost_inflation_factor") or 1)
    if factor > COST_INFLATION_CAP:
        factor = COST_INFLATION_CAP
    # PRD §3.6 pins the final step of both variants to "rounded half-up to 2
    # decimal places", so the stored figure keeps its 2-decimal precision.
    if variant == "final":
        return rhu(sum_then_round * factor, 2)
    return rhu(round_then_sum * factor, 2)


def broker_commission_split(engagement, treq):
    prior = dec(treq.get("prior_rent_cents_per_year") or 0)
    limit = (dec(PRIOR_BASE_LIMIT_BPS) * prior / dec(10000)).to_integral_value(rounding=ROUND_DOWN)
    supplied = dec(treq.get("third_party_commission_cents") or 0)
    deal = int(min(supplied, limit))
    bps = (SENIOR_BROKER_SHARE_BPS if engagement.get("broker_class") == "SENIOR"
           else STANDARD_BROKER_SHARE_BPS)
    broker_raw = dec(bps) * dec(deal) / dec(10000)
    broker_share = int(broker_raw.to_integral_value(rounding=ROUND_DOWN))
    account_share = deal - broker_share
    return {"deal_commission_cents": deal, "broker_share_cents": broker_share,
            "account_share_cents": account_share}


def broker_pool_allocated_cents(account_id):
    total = 0
    for e in DB.children("broker_engagements", account_id):
        if e.get("engagement_state") == "EXECUTED":
            total += int(e.get("broker_share_cents") or 0) + int(e.get("account_share_cents") or 0)
    return total


def approval_level_band(prior_rent_cents_per_year):
    prior = int(prior_rent_cents_per_year or 0)
    if prior < LEVEL_MANAGER_MAX_CENTS:
        return "MANAGER"
    if prior < LEVEL_DIRECTOR_MAX_CENTS:
        return "DIRECTOR"
    return "ACCOUNT_EXECUTIVE"


def governance_posture_rollup(account_id):
    failed = [a for a in DB.children("discipline_audits", account_id)
              if a.get("audit_state") == "FAILED" and a.get("remediation_required") is True]
    open_esc = [k for k in DB.children("service_level_kpis", account_id)
                if k.get("escalation_status") == "OPEN"]
    n_failed = len(failed)
    n_open = len(open_esc)
    if n_failed >= 2:
        posture = "RESTRICTED"
    elif n_failed == 1 or n_open >= 1:
        posture = "ON_WATCH"
    else:
        posture = "NORMAL"
    return posture, n_open


def transition_completion_score(account_id):
    tasks = DB.children("transition_tasks", account_id)
    eligible = len(tasks)
    progressed = len([t for t in tasks if t.get("task_state") in ("DONE", "FAILED")])
    if eligible == 0:
        return 0
    return (progressed * 10000) // eligible


def client_data_rights_for(platform_tier):
    return {
        "BASIC": "BROKER_OWNED",
        "COMPLETE": "CLIENT_OWNED_SHARED",
        "ENTERPRISE": "CLIENT_OWNED_EXCLUSIVE",
    }.get(platform_tier, "BROKER_OWNED")


def data_license_consent_required(license_row, account):
    rights = (account or {}).get("client_data_rights")
    return bool(rights == "CLIENT_OWNED_EXCLUSIVE" and license_row.get("data_scope") == "LINE_ITEM")


def level_for_vendor(vendor):
    base = "LEVEL_A" if vendor.get("delivery_model") == "SELF_PERFORM" else "LEVEL_B"
    if vendor.get("sourcing_program") == "DIVERSITY":
        occupied = [s for s in DB.children("facility_sites", vendor.get("account_id"))
                    if s.get("vendor_id") == vendor.get("id")
                    and s.get("vacancy_state") == "OCCUPIED"]
        if len(occupied) >= 1:
            base = "LEVEL_C"
    return base


def escalation_threshold_check(kpi):
    unit = kpi.get("measurement_unit")
    actual = int(kpi.get("actual_value") or 0)
    target = int(kpi.get("target_value") or 0)
    if unit == "BPS" and actual < target - 500:
        return "OPEN"
    if unit == "CENTS" and actual < target - 500000:
        return "OPEN"
    return "NONE"


def portfolio_leased_sqft(account_id):
    total = 0
    for s in DB.children("facility_sites", account_id):
        if s.get("vacancy_state") in ("OCCUPIED", "CONSOLIDATING"):
            total += int(s.get("sqft") or 0)
    return total


def expiration_bucket_for(lease, clock):
    end = lease.get("lease_end_date")
    if end is None:
        return "UNASSIGNED"
    if end <= clock:
        return "NEAR_TERM"
    days = (end - clock).days
    if days <= 365:
        return "NEAR_TERM"
    if days <= 1095:
        return "MID_TERM"
    return "LONG_TERM"


def expiration_bucket(lease, clock):
    return expiration_bucket_for(lease, clock)