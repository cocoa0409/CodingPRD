"""Calculation rules (SCAFFOLD §1.3) implemented with Decimal discipline.

- fund_period_accrual: per-period round-half-up BEFORE accumulation; the EVENT
  bucket takes the rounding remainder; the CASH_BASIS shadow applies the 0.92
  collection factor per bucket share in the same pass.
- event_cost_estimate: single round-half-up at the very end.
- distribution_projection: COMMITTED_ONLY and WEIGHTED_PIPELINE variants,
  stored at 2 decimals round-half-up.
- forecast_bias / friction / delisting_risk_score: post-launch review math.
"""

from decimal import ROUND_CEILING, ROUND_HALF_UP, Decimal

from constants import (
    CASH_COLLECTION_FACTOR,
    FORECAST_BIAS_CAP_PCT,
    FORECAST_BIAS_NORMALIZER,
    FRICTION_COUNT_CAP,
    FRICTION_UNIT_SCORE,
    PHASE_WEIGHT_GATE_FAILED,
    PHASE_WEIGHT_GATE_PASSED,
    PHASE_WEIGHT_PENDING,
    RISK_AT_RISK_MIN_SCORE,
    RISK_DELIST_MIN_SCORE,
    RISK_WATCH_MIN_SCORE,
    RISK_WEIGHT_DISTRIBUTION,
    RISK_WEIGHT_FORECAST,
    RISK_WEIGHT_FRICTION,
    RISK_WEIGHT_SALES,
)
from storage import STORE, touch


def D(x):
    """Exact Decimal from an int/float/str JSON number."""
    if isinstance(x, Decimal):
        return x
    if isinstance(x, int):
        return Decimal(x)
    return Decimal(str(x))


def rhu_int(x):
    """Round half-up to whole cents/units."""
    return int(D(x).quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def rhu_2dp(x):
    """Round half-up to exactly 2 decimal places."""
    return D(x).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)


def ceil_int(x):
    """Round UP to the next whole unit (price_per_unit_cents discipline)."""
    return int(D(x).quantize(Decimal("1"), rounding=ROUND_CEILING))


def clamp_dec(lo, hi, v):
    return max(D(lo), min(D(hi), D(v)))


def num_out(d):
    """Decimal -> JSON number (int when integral, else float)."""
    d = D(d)
    if d == d.to_integral_value():
        return int(d)
    return float(d)


# ---------------------------------------------------------------------------
# Fund helpers
# ---------------------------------------------------------------------------

def fund_of_plan(plan_id):
    for fund in STORE["funds"].values():
        if fund["plan_id"] == plan_id:
            return fund
    return None


def fund_out(fund):
    """Public fund view with the derived availabilities (PRD §2.11)."""
    out = {k: v for k, v in fund.items() if not k.startswith("_")}
    out["edlp_available_cents"] = fund["edlp_accrued_cents"] - fund["edlp_settled_cents"]
    out["event_available_cents"] = (
        fund["event_accrued_cents"]
        - fund["event_reserved_cents"]
        - fund["event_settled_cents"]
    )
    return out


def bucket_available(fund, bucket):
    if bucket == "EVENT":
        return (
            fund["event_accrued_cents"]
            - fund["event_reserved_cents"]
            - fund["event_settled_cents"]
        )
    return fund["edlp_accrued_cents"] - fund["edlp_settled_cents"]


def post_accrual(fund, period, invoiced_sales_cents):
    """fund_period_accrual: both bases computed per period, rounded per period
    per bucket share BEFORE accumulation; remainder routes to EVENT."""
    credit = rhu_int(D(invoiced_sales_cents) * D(fund["accrual_rate_pct"]) / 100)
    edlp_share = rhu_int(D(credit) * D(fund["edlp_split_pct"]) / 100)
    event_share = credit - edlp_share
    edlp_cash = rhu_int(D(edlp_share) * D(CASH_COLLECTION_FACTOR))
    event_cash = rhu_int(D(event_share) * D(CASH_COLLECTION_FACTOR))
    fund["edlp_accrued_cents"] += edlp_share
    fund["event_accrued_cents"] += event_share
    fund["edlp_cash_cents"] += edlp_cash
    fund["event_cash_cents"] += event_cash
    fund["total_invoiced_cents"] += invoiced_sales_cents
    fund["_periods"].add(period)
    touch(fund)


# ---------------------------------------------------------------------------
# Event cost estimate
# ---------------------------------------------------------------------------

def event_cost_estimate(event, plan):
    """Baseline selector (pinned): among the plan's PUBLISHED forecasts whose
    week bucket [week_start, week_start + 6 days] contains event.start_date,
    the latest week_start wins; fallback is plan.weekly_baseline_cases.
    One round-half-up at the very end."""
    start = event["_start_dt"]
    best = None
    for fc in STORE["forecasts"].values():
        if fc["plan_id"] != plan["id"] or fc["pub_status"] != "PUBLISHED":
            continue
        ws = fc["_week_start_dt"]
        if ws <= start and (start - ws).total_seconds() <= 6 * 86400:
            if best is None or ws > best:
                best = ws
    baseline = plan["weekly_baseline_cases"]
    if best is not None:
        for fc in STORE["forecasts"].values():
            if (
                fc["plan_id"] == plan["id"]
                and fc["pub_status"] == "PUBLISHED"
                and fc["_week_start_dt"] == best
            ):
                baseline = fc["baseline_cases"]
                break
    return rhu_int(
        D(baseline) * D(plan["avg_unit_net_price_cents"]) * D(event["discount_depth_pct"]) / 100
    )


# ---------------------------------------------------------------------------
# Launch projections
# ---------------------------------------------------------------------------

_PHASE_WEIGHTS = {
    "GATE_PASSED": D(PHASE_WEIGHT_GATE_PASSED),
    "PENDING": D(PHASE_WEIGHT_PENDING),
    "GATE_FAILED": D(PHASE_WEIGHT_GATE_FAILED),
}


def phases_of_launch(launch_id):
    return sorted(
        (p for p in STORE["phases"].values() if p["launch_id"] == launch_id),
        key=lambda p: p["phase_index"],
    )


def recompute_launch(launch):
    """Refresh budget_remaining_cents and both distribution projections from
    the launch's phases (no version bump here; the caller's mutation bumps)."""
    phases = phases_of_launch(launch["id"])
    spent = sum(p["trade_spend_cents"] for p in phases)
    launch["budget_remaining_cents"] = launch["total_trade_budget_cents"] - spent
    committed = sum(
        D(p["distribution_target_pct"]) * _PHASE_WEIGHTS["GATE_PASSED"]
        if p["status"] == "GATE_PASSED"
        else D(0)
        for p in phases
    )
    weighted = sum(
        D(p["distribution_target_pct"]) * _PHASE_WEIGHTS[p["status"]] for p in phases
    )
    launch["projected_distribution_committed_pct"] = num_out(rhu_2dp(committed))
    launch["projected_distribution_weighted_pct"] = num_out(rhu_2dp(weighted))


# ---------------------------------------------------------------------------
# Review math
# ---------------------------------------------------------------------------

def forecast_bias_pct(plan_id, period_start, period_end):
    """Mean of |committed - baseline| / baseline * 100 over the plan's
    PUBLISHED + COMMITTED forecasts whose week_start falls inside the closed
    review window; 0 when the qualifying set is empty. 2dp round-half-up."""
    total = D(0)
    n = 0
    for fc in STORE["forecasts"].values():
        if fc["plan_id"] != plan_id:
            continue
        if fc["pub_status"] != "PUBLISHED" or fc["commit_status"] != "COMMITTED":
            continue
        ws = fc["_week_start_dt"]
        if not (period_start <= ws <= period_end):
            continue
        total += D(abs(fc["committed_cases"] - fc["baseline_cases"])) / D(fc["baseline_cases"]) * 100
        n += 1
    if n == 0:
        return D(0)
    return rhu_2dp(total / n)


def friction_count(fund_id, period_start, period_end):
    """Deductions of the fund created (logical time) within the closed window
    whose status is DISPUTED or WRITTEN_OFF, plus SETTLED with short_paid."""
    count = 0
    for d in STORE["deductions"].values():
        if d["fund_id"] != fund_id:
            continue
        created = d["_created_logical"]
        if not (period_start <= created <= period_end):
            continue
        if d["status"] in ("DISPUTED", "WRITTEN_OFF"):
            count += 1
        elif d["status"] == "SETTLED" and d["short_paid"]:
            count += 1
    return count


def risk_score_posture(sales_attainment_pct, target_distribution_pct, distribution_achieved_pct, bias_pct, friction):
    """delisting_risk_score: components keep full precision until one final
    round-half-up to an integer clamped 0..100; posture reads off the score."""
    sales_c = clamp_dec(0, 100, D(100) - D(sales_attainment_pct))
    dist_c = clamp_dec(0, 100, D(target_distribution_pct) - D(distribution_achieved_pct))
    forecast_c = min(D(bias_pct), D(FORECAST_BIAS_CAP_PCT)) * D(FORECAST_BIAS_NORMALIZER)
    friction_c = min(D(friction), D(FRICTION_COUNT_CAP)) * D(FRICTION_UNIT_SCORE)
    raw = (
        D(RISK_WEIGHT_SALES) * sales_c
        + D(RISK_WEIGHT_DISTRIBUTION) * dist_c
        + D(RISK_WEIGHT_FORECAST) * forecast_c
        + D(RISK_WEIGHT_FRICTION) * friction_c
    )
    score = int(clamp_dec(0, 100, rhu_int(raw)))
    if score >= RISK_DELIST_MIN_SCORE:
        posture = "DELIST_RECOMMENDED"
    elif score >= RISK_AT_RISK_MIN_SCORE:
        posture = "AT_RISK"
    elif score >= RISK_WATCH_MIN_SCORE:
        posture = "WATCH"
    else:
        posture = "HEALTHY"
    return score, posture


def recompute_open_reviews(plan_id):
    """Deduction cascade hops 2-3 (PRD §3.6): every OPEN review whose launch
    belongs to this plan recomputes friction_count, risk_score, risk_posture;
    each touched review registers its own version increment."""
    fund = fund_of_plan(plan_id)
    if fund is None:
        return
    for rev in STORE["reviews"].values():
        if rev["status"] != "OPEN":
            continue
        launch = STORE["launches"].get(rev["launch_id"])
        if launch is None or launch["plan_id"] != plan_id:
            continue
        rev["friction_count"] = friction_count(
            fund["id"], rev["_period_start_dt"], rev["_period_end_dt"]
        )
        score, posture = risk_score_posture(
            rev["sales_attainment_pct"],
            rev["target_distribution_pct"],
            rev["distribution_achieved_pct"],
            rev["forecast_bias_pct"],
            rev["friction_count"],
        )
        rev["risk_score"] = score
        rev["risk_posture"] = posture
        touch(rev)
