"""The ten calculation rules of PRD section 3.4, 3.5, 3.9, 3.10 and 3.11."""
from datetime import timedelta

import core
import lookups

# ---------------------------------------------------------------------------
# weighted_completeness_score  (PRD 3.4)
# ---------------------------------------------------------------------------
def _scoring_attributes(property_id):
    return [a for a in lookups.attributes_of(property_id)
            if a["proposed_status"] in lookups.SCORING_STATUSES]


def _source_is_fresh(prop, source_id):
    if source_id is None:
        return False
    sd = core.source_documents.get(source_id)
    if sd is None or sd["property_id"] != prop["id"]:
        return False
    age = core.clock.now() - core.parse_dt(sd["obtained_at"])
    return age <= timedelta(days=core.SOURCE_FRESHNESS_DAYS)


def weighted_completeness_score(prop, variant="PROVISIONAL"):
    scoring = _scoring_attributes(prop["id"])
    denominator = len(scoring)
    if denominator == 0:
        return 0.0
    numerator = core.Decimal("0.0")
    for attr in scoring:
        if attr["proposed_status"] == "VERIFIED":
            if _source_is_fresh(prop, attr["source_document_id"]):
                numerator += core.WEIGHT_VERIFIED_SOURCED
            elif variant == "PROVISIONAL":
                numerator += core.WEIGHT_VERIFIED_UNSOURCED
            else:
                numerator += core.WEIGHT_UNVERIFIED
        else:
            numerator += core.WEIGHT_UNVERIFIED
    base = core.Decimal("100.0") * numerator / core.Decimal(denominator)
    stale = core.Decimal(0)
    for sd in lookups.sources_of(prop["id"]):
        age = core.clock.now() - core.parse_dt(sd["obtained_at"])
        if age > timedelta(days=core.SOURCE_FRESHNESS_DAYS):
            stale += 1
    penalty = core.WEIGHT_STALE_PENALTY * stale
    value = core.round_half_up(base - penalty, 2)
    if value < 0:
        value = core.Decimal("0.0")
    return float(value)


def refresh_property_state(prop, variant="PROVISIONAL", update_posture=False):
    """Recompute every derived property field, then mutate per PRD 3.4.

    ``land_posture`` is set by the market escalations of §3.7 and re-derived at
    the periodic staleness re-age of §3.11; an ordinary child recomputation
    leaves it where the escalation put it.
    """
    lookups.recompute_property_attributes(prop)
    lookups.recompute_verified_sale_value(prop)
    prop["completeness_pct"] = weighted_completeness_score(prop, variant)
    if update_posture:
        prop["land_posture"] = derive_land_posture(prop)
    core.touch(prop)
    return prop


def derive_land_posture(prop):
    """PRD 3.4: "It is `OPEN` when no unverified attribute burden and no
    stale-source burden is present, `RESTRICTED` when the property has been
    placed under a market escalation while it was still `DRAFT` or
    `RESEARCHING`."

    Applied on the periodic staleness re-age: a property already graded
    `RESTRICTED` or `FROZEN` by a market escalation keeps that grade, while a
    property carrying an unverified attribute or a stale source is re-graded
    `RESTRICTED`.
    """
    if prop["land_posture"] in ("RESTRICTED", "FROZEN"):
        return prop["land_posture"]
    unverified = any(a["proposed_status"] == "PENDING"
                     for a in lookups.attributes_of(prop["id"]))
    if unverified or prop["stale_source_count"] > 0:
        return "RESTRICTED"
    return "OPEN"


# ---------------------------------------------------------------------------
# property_stale_source_count  (PRD 3.5)
# ---------------------------------------------------------------------------
def property_stale_source_count(prop):
    stale = 0
    for sd in lookups.sources_of(prop["id"]):
        age = core.clock.now() - core.parse_dt(sd["obtained_at"])
        if age > timedelta(days=core.SOURCE_FRESHNESS_DAYS):
            stale += 1
    return stale


# ---------------------------------------------------------------------------
# seat_overage_fee  (PRD 3.10)
# ---------------------------------------------------------------------------
TIER_RATES = {
    "TIER_1": core.TIER_1_DAILY_RATE_CENTS,
    "TIER_2": core.TIER_2_DAILY_RATE_CENTS,
    "TIER_3": core.TIER_3_DAILY_RATE_CENTS,
}


def seat_overage_fee(seat, contract):
    over_days = max(0, seat["monthly_active_days"] - core.INCLUDED_ACTIVE_DAYS)
    if over_days == 0:
        return 0
    rate = TIER_RATES.get(seat["index_tier"], core.TIER_3_DAILY_RATE_CENTS)
    overage = over_days * rate
    violations = len(seat["monthly_unauthorized_markets"])
    if violations == 0:
        cap_bps = core.LICENSED_MARKET_USAGE_LIMIT_BPS
    elif violations == 1:
        cap_bps = 2 * core.LICENSED_MARKET_USAGE_LIMIT_BPS
    else:
        cap_bps = 3 * core.LICENSED_MARKET_USAGE_LIMIT_BPS
    cap = (contract["annual_fee_cents"] * cap_bps) // 10000
    return min(overage, cap)


# ---------------------------------------------------------------------------
# seat_owner_attribution  (PRD 3.9)
# ---------------------------------------------------------------------------
def _window_events(seat, days):
    start = core.parse_dt(seat["last_usage_cycle"])
    end = start + timedelta(days=days)
    rows = []
    for event in lookups.events_of(seat["id"]):
        occurred = core.parse_dt(event["occurred_at"])
        if start <= occurred < end:
            rows.append((event, occurred))
    return rows


def seat_owner_attribution(seat, variant="weekly_snapshot"):
    days = 7 if variant == "weekly_snapshot" else 30
    window = _window_events(seat, days)
    if not window:
        return None, 0.0
    ip_days = {}
    day_ips = {}
    for event, occurred in window:
        day = occurred.date()
        ip = event["distinguishing_ip"]
        ip_days.setdefault(ip, set()).add(day)
        day_ips.setdefault(day, set()).add(ip)
    party_days = sum(1 for day in day_ips if len(day_ips[day]) >= 2)
    p = core.Decimal(party_days) / core.Decimal(days)
    busiest_ip = None
    for ip in sorted(ip_days):
        if busiest_ip is None:
            busiest_ip = ip
        elif len(ip_days[ip]) > len(ip_days[busiest_ip]):
            busiest_ip = ip
    candidates = [(e, o) for (e, o) in window if e["distinguishing_ip"] == busiest_ip]
    candidates.sort(key=lambda pair: (pair[1], pair[0]["created_at"], pair[0]["distinguishing_ip"]))
    owner_user_id = candidates[0][0]["user_id"] if candidates else None
    owner_events = sum(1 for (e, _o) in window if e["user_id"] == owner_user_id)
    share = p * core.Decimal(owner_events) / core.Decimal(len(window))
    return owner_user_id, float(core.round_half_up(core.Decimal(100) * share, 2))


def refresh_seat_monitoring(seat):
    contract = core.contracts.get(seat["contract_id"])
    events = lookups.events_of(seat["id"])
    days = {core.parse_dt(e["occurred_at"]).date() for e in events}
    seat["monthly_active_days"] = len(days)
    unauthorized = set()
    ips = set()
    licensed = set(contract["licensed_markets"]) if contract else set()
    for event in events:
        if event["market"] not in licensed:
            unauthorized.add(event["market"])
        ips.add(event["distinguishing_ip"])
    seat["monthly_unauthorized_markets"] = sorted(unauthorized)
    seat["distinctive_ip_count"] = len(ips)
    threshold = core.SHARING_IP_THRESHOLD.get(seat["index_tier"], 5)
    seat["shared_flag"] = len(ips) > threshold
    seat["overage_fee_cents"] = seat_overage_fee(seat, contract) if contract else 0
    owner, share = seat_owner_attribution(seat, "weekly_snapshot")
    seat["owner_user_id"] = owner
    seat["owner_share_pct"] = share
    core.touch(seat)
    return seat


# ---------------------------------------------------------------------------
# market_index_value  (PRD 3.5)
# ---------------------------------------------------------------------------
def _refined_comparables(market, window_start, window_end, excluded_property_ids):
    excluded = set(excluded_property_ids or [])
    refined = []
    for comp in core.lease_comparables.values():
        prop = core.properties.get(comp["property_id"])
        if prop is None or prop["market"] != market:
            continue
        lease_start = core.parse_dt(comp["lease_start"])
        lease_end = core.parse_dt(comp["lease_end"])
        if not (lease_start <= window_end and lease_end > window_start):
            continue
        if prop["research_status"] != "VERIFIED":
            continue
        if comp["property_id"] in excluded:
            continue
        if prop["land_posture"] in ("FROZEN", "RESTRICTED"):
            continue
        refined.append(comp)
    return refined


def _modal_class(refined):
    counts = {}
    for comp in refined:
        prop = core.properties.get(comp["property_id"])
        if prop is not None:
            counts[prop["classification"]] = counts.get(prop["classification"], 0) + 1
    if not counts:
        return None
    return sorted(counts.items(), key=lambda pair: (-pair[1], pair[0]))[0][0]


def _hedonic_value(refined):
    modal = _modal_class(refined)
    adjusted = []
    group_counts = {}
    for comp in refined:
        group_counts[comp["property_id"]] = group_counts.get(comp["property_id"], 0) + 1
    for comp in refined:
        prop = core.properties.get(comp["property_id"])
        rent = core.dec(comp["effective_rent_psf"])
        if prop is not None and modal is not None and prop["classification"] != modal:
            rank = {"CLASS_A": 1, "CLASS_B": 0, "CLASS_C": -1}.get(prop["classification"], 0)
            factor = core.Decimal("1") + core.Decimal("0.04") * core.Decimal(rank)
            rent = rent * factor
        if group_counts.get(comp["property_id"], 1) > 1:
            rent = rent * core.Decimal("0.97")
        adjusted.append(rent)
    if not adjusted:
        return None
    return sum(adjusted) / core.Decimal(len(adjusted))


def market_index_value(market, window_start, window_end, adjustment_mode="UNADJUSTED",
                       excluded_property_ids=None):
    refined = _refined_comparables(market, window_start, window_end, excluded_property_ids)
    if not refined:
        return {
            "index_value": None,
            "comp_count": 0,
            "mean_effective_rent_psf": None,
            "median_effective_rent_psf": None,
        }
    rents = [core.dec(c["effective_rent_psf"]) for c in refined]
    mean = sum(rents) / core.Decimal(len(rents))
    ordered = sorted(rents)
    size = len(ordered)
    if size % 2 == 1:
        median = ordered[size // 2]
    else:
        median = (ordered[size // 2 - 1] + ordered[size // 2]) / core.Decimal(2)
    if adjustment_mode == "HEDONIC":
        hedonic = _hedonic_value(refined)
        if hedonic is not None:
            mean = hedonic
    return {
        "index_value": float(core.round_half_up(mean, 2)),
        "comp_count": size,
        "mean_effective_rent_psf": float(core.round_half_up(mean, 2)),
        "median_effective_rent_psf": float(core.round_half_up(median, 2)),
    }


# ---------------------------------------------------------------------------
# market_forecast  (PRD 3.5)
# ---------------------------------------------------------------------------
def select_base_run(market, selector, candidates=None):
    runs = candidates
    if runs is None:
        runs = [r for r in core.analytics_runs.values()
                if r["market"] == market and r["run_type"] == "INDEX" and r["index_value"] is not None]
    if not runs:
        return None, None
    ordered = sorted(runs, key=lambda r: (r["created_at"], r["id"]))
    if selector == "EARLIEST":
        return ordered[0], None
    if selector == "UPPER_BOUND":
        best = max(core.dec(r["index_value"]) for r in runs)
        tied = [r for r in runs if core.dec(r["index_value"]) == best]
        if len(tied) > 1:
            return None, "AMBIGUOUS_SELECTION"
        return tied[0], None
    return ordered[-1], None


def market_forecast(base_index_value, horizon_quarters=None):
    quarters = core.DEFAULT_HORIZON_QUARTERS if horizon_quarters is None else horizon_quarters
    growth = (core.Decimal("1") + core.BASE_GROWTH_RATE) ** core.Decimal(quarters)
    if growth < core.MIN_GROWTH_FACTOR:
        growth = core.MIN_GROWTH_FACTOR
    if growth > core.MAX_GROWTH_FACTOR:
        growth = core.MAX_GROWTH_FACTOR
    value = core.dec(base_index_value) * growth
    return float(core.round_half_up(value, 2))


# ---------------------------------------------------------------------------
# cap_rate_bps  (PRD 3.5)
# ---------------------------------------------------------------------------
def cap_rate_bps(prop, gross_sale_price_cents):
    income = 0
    for attr in lookups.attributes_of(prop["id"]):
        if attr["field_name"] == "in_place_income_annual_cents" and attr["proposed_status"] == "VERIFIED":
            try:
                income = int(core.dec(attr["value"]))
            except (ValueError, ArithmeticError):
                income = 0
    if income > core.SUBSTITUTE_INCOME_CENTS:
        source = "VERIFIED"
    else:
        income = core.SUBSTITUTE_INCOME_CENTS
        source = "SUBSTITUTE"
    raw = core.Decimal(10000) * core.Decimal(income) / core.Decimal(gross_sale_price_cents)
    return core.as_int(raw), source


# ---------------------------------------------------------------------------
# market_addition_fee  (PRD 3.10)
# ---------------------------------------------------------------------------
PRODUCT_FACTORS = {
    "GLOBAL_ALL": core.Decimal("0.50"),
    "ANALYTICS_INDEX": core.Decimal("1.00"),
    "LISTING_SERVICE": core.Decimal("0.75"),
    "CORE_MARKET_DATA": core.Decimal("1.25"),
}
TIER_FACTORS = {
    "ENTERPRISE": core.Decimal("0.80"),
    "MID_MARKET": core.Decimal("1.00"),
    "SMB": core.Decimal("1.15"),
}


def market_addition_fee(contract, organization):
    base = core.round_half_up(core.dec(contract["annual_fee_cents"]) * core.MARKET_ADD_BASE_PCT, 0)
    product_factor = PRODUCT_FACTORS.get(contract["product"], core.Decimal("1.25"))
    gross = core.round_half_up(base * product_factor, 0)
    tier_factor = TIER_FACTORS.get(organization["service_tier"], core.Decimal("1.15"))
    return core.as_int(core.round_half_up(gross * tier_factor, 0))


# ---------------------------------------------------------------------------
# enforcement_penalty  (PRD 3.7)
# ---------------------------------------------------------------------------
def enforcement_penalty(finding_cents, fee_rate_pct):
    raw = core.dec(finding_cents) * core.dec(fee_rate_pct)
    penalty = core.as_int(raw)
    return penalty, penalty >= core.LITIGATION_PENALTY_THRESHOLD_CENTS


# ---------------------------------------------------------------------------
# renewal_lapse_scan  (PRD 3.11)
# ---------------------------------------------------------------------------
def renewal_lapse_scan():
    contracts = [c for c in core.contracts.values() if c["status"] in ("ACTIVE", "GRACE")]
    contracts.sort(key=lambda c: (c["renewal_due_at"] or "", c["created_at"]))
    lapsed = 0
    for contract in contracts:
        if (contract["status"] == "ACTIVE" and contract["auto_renew"] is True
                and core.clock.now() >= core.parse_dt(contract["renewal_due_at"])
                and contract["renewal_decision"] == "NONE"):
            contract["status"] = "GRACE"
            core.touch(contract)
            org = core.organizations.get(contract["subscriber_organization_id"])
            if org is not None:
                lookups.recompute_organization_counters(org)
        if (contract["status"] == "GRACE"
                and core.clock.now() >= core.parse_dt(contract["term_end"])):
            contract["status"] = "LAPSED"
            contract["renewal_decision"] = "FAILED"
            core.touch(contract)
            for seat in lookups.seats_of(contract["id"]):
                seat["access_revoked"] = True
                seat["shared_flag"] = False
                core.touch(seat)
            org = core.organizations.get(contract["subscriber_organization_id"])
            if org is not None:
                lookups.recompute_organization_counters(org)
            lapsed += 1
    return lapsed