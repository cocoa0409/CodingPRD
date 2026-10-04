"""Calculation rules (SCAFFOLD §1.3). Money is integer cents, Decimal-only."""

from datetime import timedelta
from decimal import Decimal, ROUND_HALF_UP

from db import db

# --- gross_settlement_calculation constants ---
TIER_INCREMENT = 3
TIER_CEILING = 4000
DEDUCTION_CAP = 50000
LATE_ACCRUAL_DAYS = 3

# --- deduction_segment_cap constants ---
CAP_SEGMENTS_FORWARD = ["MAINTENANCE", "ACCESSORIAL"]
CAP_SEGMENTS_REVERSED = ["ACCESSORIAL", "MAINTENANCE"]

# --- chargeback_net_recovery constants ---
CHARGEBACK_ESCALATION_CENTS = 200000
CHARGEBACK_ESCALATION_PCT = 10

# --- provider_composite_score constants ---
PERF_WEIGHT = Decimal("0.5")
SAFETY_WEIGHT = Decimal("0.3")
CX_WEIGHT = Decimal("0.2")
DELIVERY_WEIGHTS = (Decimal("0.6"), Decimal("0.25"), Decimal("0.15"))
SAFETY_WEIGHTS = (Decimal("0.4"), Decimal("0.4"), Decimal("0.2"))
COMPOSITE_FLOOR = Decimal("0.00")
COMPOSITE_CEILING = Decimal("100.00")
MAX_SWING = Decimal("5.00")

# --- settlement_performance_multiplier constants ---
MULT_WEIGHTS = (Decimal("0.5"), Decimal("0.3"), Decimal("0.2"))
TIER_1_MIN = Decimal("60.00")
TIER_2_MIN = Decimal("75.00")
TIER_3_MIN = Decimal("85.00")
EXEMPT_MULTIPLIER = Decimal("1.00")

# --- provider_renewal_recommendation constants ---
SAFETY_MIN_RENEW = Decimal("80.00")
SAFETY_MIN_CONDITIONAL = Decimal("60.00")
SERVICE_MIN_RENEW = Decimal("75.00")
TRAILING_WINDOW = 4

# --- owned_vehicle_count_reconciliation / vehicle selector constants ---
BRAND_MIN_PCT = Decimal("100.00")
STEP_VAN_STOP_CEILING = 1500

# --- owned_driver_count_reconciliation constants ---
DRIVER_MIN_PCT = Decimal("100.00")

# --- driver duty guard buffer ---
DRIVER_GUARD_MINUTES = 1

TWO_PLACES = Decimal("0.01")
ONE_CENT = Decimal("1")
HUNDRED = Decimal("100")
WEEK = timedelta(days=7)


def to_decimal(value):
    if isinstance(value, Decimal):
        return value
    return Decimal(str(value))


def round_money(value):
    """Round half up to a whole cent."""
    return int(to_decimal(value).quantize(ONE_CENT, rounding=ROUND_HALF_UP))


def round_score(value):
    """Round half up to two decimal places."""
    return float(to_decimal(value).quantize(TWO_PLACES, rounding=ROUND_HALF_UP))


def median(values):
    ordered = sorted(values)
    n = len(ordered)
    if n == 0:
        return None
    middle = n // 2
    if n % 2 == 1:
        return ordered[middle]
    return (ordered[middle - 1] + ordered[middle]) / Decimal("2")


# ---------------------------------------------------------------------------
# Window helpers
# ---------------------------------------------------------------------------

def week_end(period):
    return period["week_start_at_dt"] + WEEK


def observations(period):
    return [o for o in db.all("StopObservation") if o["settlement_period_id"] == period["id"]]


def in_window(period, obs, use_observed_date=False):
    """Half-open [week_start_at, week_start_at + 7 days) membership."""
    start = period["week_start_at_dt"]
    end = start + WEEK
    key = obs["observed_date_dt"] if use_observed_date else obs["recorded_at_dt"]
    return start <= key < end


def window_observations(period, use_observed_date=False):
    """Observations in window, folded in the pinned order.

    Pinned: ascending recorded_at, ascending created_at as tie-break. The
    server-minted id never participates in this ordering.
    """
    rows = [o for o in observations(period) if in_window(period, o, use_observed_date)]
    rows.sort(key=lambda o: (o["recorded_at_dt"], o["created_at"], o.get("_seq", 0)))
    return rows


def period_deductions(period, deduction_type=None, eligible_only=False):
    rows = [d for d in db.all("SettlementDeduction") if d["settlement_period_id"] == period["id"]]
    if deduction_type is not None:
        if isinstance(deduction_type, (list, tuple, set)):
            rows = [d for d in rows if d["deduction_type"] in deduction_type]
        else:
            rows = [d for d in rows if d["deduction_type"] == deduction_type]
    if eligible_only:
        rows = [d for d in rows if d.get("performance_factor_eligible", True)]
    return rows


def sum_amounts(rows):
    return int(sum(int(r.get("amount_cents", 0)) for r in rows))


def governing_agreement_for_area(service_area_id):
    """The agreement governing a territory (latest by created_at)."""
    matches = [a for a in db.all("Agreement") if a["service_area_id"] == service_area_id]
    if not matches:
        return None
    matches.sort(key=lambda a: (a["created_at"], a.get("_seq", 0)))
    return matches[-1]


def governing_agreement(period):
    """The agreement whose service_area_id and provider_id both match the period."""
    matches = [
        a
        for a in db.all("Agreement")
        if a["service_area_id"] == period["service_area_id"]
        and a["provider_id"] == period["provider_id"]
    ]
    if not matches:
        return governing_agreement_for_area(period["service_area_id"])
    matches.sort(key=lambda a: (a["created_at"], a.get("_seq", 0)))
    return matches[-1]


def latest_metric(provider_id):
    rows = [m for m in db.all("PerformanceMetric") if m["provider_id"] == provider_id]
    if not rows:
        return None
    rows.sort(key=lambda m: (m["created_at"], m.get("_seq", 0)))
    return rows[-1]


def has_late_accrual(period):
    for o in observations(period):
        if (o["recorded_at_dt"] - o["observed_date_dt"]).total_seconds() > LATE_ACCRUAL_DAYS * 86400:
            return True
    return False


# ---------------------------------------------------------------------------
# gross_settlement_calculation
# ---------------------------------------------------------------------------

def resolve_multiplier(period):
    """The performance multiplier, resolved BEFORE the deduction segments are split.

    A no-stops week is exempt from the multiplier entirely; the zero-stops week
    that filed a nonzero miles_and_accessorial observation is forced to 1.00 and
    the tier table is skipped.
    """
    rows = observations(period)
    if not rows or all(int(o["stops_count"]) == 0 for o in rows):
        for o in rows:
            if int(o["miles_driven"]) != 0 and int(o["accessorial_cents"]) != 0:
                return EXEMPT_MULTIPLIER
        return EXEMPT_MULTIPLIER
    metric = latest_metric(period["provider_id"])
    if metric is None:
        return EXEMPT_MULTIPLIER
    agg = (MULT_WEIGHTS[0] * to_decimal(metric["service_score"])
           + MULT_WEIGHTS[1] * to_decimal(metric["safety_score"])
           + MULT_WEIGHTS[2] * to_decimal(metric["customer_experience_score"]))
    agg = to_decimal(round_score(agg))
    if agg > TIER_3_MIN:
        return Decimal("1.05")
    if agg >= TIER_2_MIN:
        return Decimal("1.00")
    return Decimal("0.90")


def _base_gross(period, use_observed_date):
    agreement = governing_agreement(period)
    rows = window_observations(period, use_observed_date)
    total_stops = sum(int(o["stops_count"]) for o in rows)
    total_packages = sum(int(o["packages_count"]) for o in rows)
    total_accessorial = sum(int(o["accessorial_cents"]) for o in rows)

    if agreement is None:
        base_rate = package_rate = peak_surcharge = 0
    else:
        base_rate = int(agreement["base_rate_cents_per_stop"])
        package_rate = int(agreement["package_rate_cents"])
        peak_surcharge = int(agreement["peak_surcharge_cents"])

    tier_stop_count = min(total_stops, TIER_CEILING)
    if tier_stop_count <= 1000:
        tier_rate = base_rate
    elif tier_stop_count <= 2500:
        tier_rate = base_rate + TIER_INCREMENT
    else:
        tier_rate = base_rate + 2 * TIER_INCREMENT

    stops_gross = tier_stop_count * tier_rate
    package_gross = total_packages * package_rate
    peak_gross = total_stops * peak_surcharge if period.get("is_peak_week") else 0
    base_gross = stops_gross + package_gross + peak_gross + total_accessorial
    return {
        "stops_gross_cents": stops_gross,
        "package_gross_cents": package_gross,
        "peak_gross_cents": peak_gross,
        "accessorial_gross_cents": total_accessorial,
        "base_gross_cents": base_gross,
    }


def deduction_bundles(period):
    """Pre-multiplier bundle (capped) and post-multiplier bundle (uncapped).

    FUEL and CHARGEBACK are post-multiplier and never capped. The pre-multiplier
    bundle is MAINTENANCE plus ACCESSORIAL over the performance-eligible rows,
    capped at DEDUCTION_CAP unless this reconcile bypassed the cap.
    """
    rows = period_deductions(period, ["MAINTENANCE", "ACCESSORIAL"], eligible_only=True)
    capped = sum_amounts(rows)
    fuel = sum_amounts(period_deductions(period, "FUEL"))
    chargeback = sum_amounts(period_deductions(period, "CHARGEBACK"))
    return capped, fuel + chargeback


def compute_gross_settlement(period, use_observed_date=False, resolve=True):
    """Write base_gross_cents and net_amount_cents; return the decomposed segments.

    `resolve=False` is the provisional close-accrual pass: it uses the week's
    stored performance_multiplier, which is still the declared default of 1.00
    because the metrics-driven tier table is resolved only at reconcile. That is
    what keeps the reconcile precondition — base_gross minus net equals the sum
    of the non-CHARGEBACK deduction segments — satisfiable.
    """
    breakdown = _base_gross(period, use_observed_date)
    if resolve:
        multiplier = resolve_multiplier(period)
    else:
        multiplier = to_decimal(period.get("performance_multiplier") or 1.0)
    period["performance_multiplier"] = float(multiplier)
    capped, post = deduction_bundles(period)
    gross_fee = round_money(to_decimal(capped) * multiplier)
    period["base_gross_cents"] = breakdown["base_gross_cents"]
    period["net_amount_cents"] = breakdown["base_gross_cents"] - gross_fee - post
    breakdown["performance_multiplier"] = float(multiplier)
    # PRD §3.7 exposes "its applied `performance_multiplier`, its
    # `capped_deduction_cents` ... and its `net_amount_cents`" so that a reader
    # can see which segment moved the payout. Net is base gross minus the scaled
    # capped bundle minus the post-multiplier bundle, so the reported capped
    # figure is the scaled bundle that actually moved the payout rather than the
    # pre-scaling segment total.
    breakdown["capped_deduction_cents"] = gross_fee
    breakdown["uncapped_deduction_cents"] = post
    breakdown["net_amount_cents"] = period["net_amount_cents"]
    return breakdown


def summary_breakdown(period):
    breakdown = _base_gross(period, use_observed_date=False)
    raw_capped, post = deduction_bundles(period)
    multiplier = to_decimal(period.get("performance_multiplier") or 1.0)
    return {
        "settlement_period_id": period["id"],
        "stops_gross_cents": breakdown["stops_gross_cents"],
        "package_gross_cents": breakdown["package_gross_cents"],
        "peak_gross_cents": breakdown["peak_gross_cents"],
        "accessorial_gross_cents": breakdown["accessorial_gross_cents"],
        "base_gross_cents": period.get("base_gross_cents", breakdown["base_gross_cents"]),
        "performance_multiplier": period.get("performance_multiplier", 1.0),
        "capped_deduction_cents": round_money(to_decimal(raw_capped) * multiplier),
        "uncapped_deduction_cents": post,
        "net_amount_cents": period.get("net_amount_cents", 0),
    }


# ---------------------------------------------------------------------------
# deduction_segment_cap
# ---------------------------------------------------------------------------

def segment_order(period, deduction_order):
    """Reversed order applies on a RE_NEGOTIATION agreement or a peak week.

    PRD §3.8 pins the two readings as the maintenance-first order and the order
    that fills ACCESSORIAL first, so a switch naming either reading selects it.
    """
    if deduction_order in ("reversed", "ACCESSORIAL_FIRST"):
        return CAP_SEGMENTS_REVERSED
    if deduction_order in ("forward", "MAINTENANCE_FIRST"):
        return CAP_SEGMENTS_FORWARD
    agreement = governing_agreement(period)
    if period.get("is_peak_week") or (agreement is not None and agreement["status"] == "RE_NEGOTIATION"):
        return CAP_SEGMENTS_REVERSED
    return CAP_SEGMENTS_FORWARD


def apply_deduction_segment_cap(period, allow_over_cap=False, deduction_order=None):
    """Waterfall-fill the capped segments and WRITE every row's amount_cents.

    `allow_over_cap` governs only the ERR_DEDUCTION_CAP_EXCEEDED gate in the
    reconcile operation; the waterfall below still fills the capped segments to
    DEDUCTION_CAP in the order in force, which is what makes the maintenance-first
    and maintenance-deferred readings produce different per-segment splits on the
    same rows.

    FUEL and CHARGEBACK rows, and rows whose performance_factor_eligible is
    false, are written through unchanged. A segment whose request exceeds what
    remains is filled to the remainder and later segments receive nothing;
    rounding remainders stay in the last eligible segment and are never re-split.
    """
    order = segment_order(period, deduction_order)
    rows = period_deductions(period, ["MAINTENANCE", "ACCESSORIAL", "FUEL", "CHARGEBACK"])
    untouched = [d for d in rows if d["deduction_type"] in ("FUEL", "CHARGEBACK")
                 or not d.get("performance_factor_eligible", True)]
    eligible = [d for d in rows if d["deduction_type"] in ("MAINTENANCE", "ACCESSORIAL")
                and d.get("performance_factor_eligible", True)]

    want_total = sum_amounts(eligible)
    # The waterfall is the cap's own mechanism and runs whenever the cap is in
    # force, including when the caller has waived the refusal. PRD §3.8 states
    # the cap is "filled as a waterfall", so the capped segments are filled to
    # DEDUCTION_CAP here; `allow_over_cap` governs only the ERROR gate.
    if want_total <= DEDUCTION_CAP:
        for row in eligible:
            row["amount_cents"] = int(row["amount_cents"])
    else:
        remaining = DEDUCTION_CAP
        for segment in order:
            segment_rows = [d for d in eligible if d["deduction_type"] == segment]
            if not segment_rows:
                continue
            want = sum_amounts(segment_rows)
            fill = min(want, remaining)
            remaining -= fill
            if want == 0:
                for row in segment_rows:
                    row["amount_cents"] = 0
                continue
            allocated = 0
            for index, row in enumerate(segment_rows):
                if index == len(segment_rows) - 1:
                    share = fill - allocated
                else:
                    share = int(to_decimal(int(row["amount_cents"])) * to_decimal(fill) / to_decimal(want))
                row["amount_cents"] = max(0, share)
                allocated += row["amount_cents"]
    for row in untouched:
        row["amount_cents"] = int(row["amount_cents"])


# ---------------------------------------------------------------------------
# chargeback_net_recovery
# ---------------------------------------------------------------------------

def compute_net_recovery(claim):
    """Salvage recovery, then a per-provider calendar-year escalation."""
    amount = int(claim["amount_cents"])
    rate = to_decimal(claim.get("recovery_rate_pct") or 0)
    base_recovery = round_money(to_decimal(amount) * rate / HUNDRED)
    net = amount - base_recovery

    claim_year = claim["created_at_dt"].year
    prior_total = 0
    for other in db.all("ChargebackClaim"):
        if other["id"] == claim["id"]:
            continue
        if other["provider_id"] != claim["provider_id"]:
            continue
        if other["status"] not in ("APPROVED", "SETTLED"):
            continue
        if other["created_at_dt"].year != claim_year:
            continue
        prior_total += int(other.get("net_of_recovery_cents") or 0)

    if prior_total >= CHARGEBACK_ESCALATION_CENTS:
        net = round_money(to_decimal(net) * (Decimal("1") + to_decimal(CHARGEBACK_ESCALATION_PCT) / HUNDRED))
    claim["net_of_recovery_cents"] = net
    return net


def recompute_period_chargebacks(period):
    """Reassessed at reconcile: the population includes claims settled in the pass."""
    for claim in db.all("ChargebackClaim"):
        if claim["settlement_period_id"] == period["id"]:
            compute_net_recovery(claim)


# ---------------------------------------------------------------------------
# provider_composite_score
# ---------------------------------------------------------------------------

def composite_weights(provider):
    if provider.get("status") in ("UNDER_REVIEW", "SUSPENDED"):
        return SAFETY_WEIGHTS
    active = [a for a in db.all("Agreement")
              if a["provider_id"] == provider["id"] and a["status"] == "ACTIVE"]
    if active:
        return DELIVERY_WEIGHTS
    return (PERF_WEIGHT, SAFETY_WEIGHT, CX_WEIGHT)


def compose_metric(metric):
    from errors import ApiError, ERR_PROVIDER_NOT_FOUND

    provider = db.get("ServiceProvider", metric["provider_id"])
    if provider is None:
        raise ApiError(ERR_PROVIDER_NOT_FOUND)
    w_service, w_safety, w_cx = composite_weights(provider)
    raw = (w_service * to_decimal(metric["service_score"])
           + w_safety * to_decimal(metric["safety_score"])
           + w_cx * to_decimal(metric["customer_experience_score"]))
    composite = to_decimal(round_score(raw))
    composite = min(composite, COMPOSITE_CEILING)
    composite = max(composite, COMPOSITE_FLOOR)

    earlier = [
        m
        for m in db.all("PerformanceMetric")
        if m["provider_id"] == metric["provider_id"]
        and (m["created_at"], m.get("_seq", 0)) < (metric["created_at"], metric.get("_seq", 0))
    ]
    if earlier:
        earlier.sort(key=lambda m: (m["created_at"], m.get("_seq", 0)))
        prior = earlier[-1].get("composite_score")
        if prior is not None:
            composite = max(composite, to_decimal(prior) - MAX_SWING)
    metric["composite_score"] = float(composite)
    return metric["composite_score"]


# ---------------------------------------------------------------------------
# provider_renewal_recommendation
# ---------------------------------------------------------------------------

def renewal_recommendation(agreement):
    """Terminal safety reading, or the worst-window reading inside 30 days."""
    provider_id = agreement["provider_id"]
    metrics = [m for m in db.all("PerformanceMetric") if m["provider_id"] == provider_id]
    metrics.sort(key=lambda m: (m["created_at"], m.get("_seq", 0)))

    terminal_safety = to_decimal(metrics[-1]["safety_score"]) if metrics else None
    window = metrics[-TRAILING_WINDOW:] if metrics else []
    med = None
    if window:
        med = to_decimal(round_score(median([to_decimal(m["service_score"]) for m in window])))

    within_window = False
    due = agreement.get("renewal_due_at_dt")
    if due is not None and (due - db.clock).total_seconds() <= 30 * 86400:
        within_window = True

    safety_reading = terminal_safety
    if within_window and window:
        safety_reading = min(to_decimal(m["safety_score"]) for m in window)

    if safety_reading is None:
        recommendation = "RENEW"
    elif safety_reading < SAFETY_MIN_CONDITIONAL:
        recommendation = "DO_NOT_RENEW"
    elif (med is not None and med < SERVICE_MIN_RENEW) or safety_reading < SAFETY_MIN_RENEW:
        recommendation = "CONDITIONAL"
    else:
        recommendation = "RENEW"

    return {
        "agreement_id": agreement["id"],
        "renewal_recommendation": recommendation,
        "terminal_safety_score": float(terminal_safety) if terminal_safety is not None else None,
        "median_service_score": float(med) if med is not None else None,
        "renewal_due_at": agreement.get("renewal_due_at"),
    }


# ---------------------------------------------------------------------------
# driver_qualification_compliance
# ---------------------------------------------------------------------------

def driver_roster(service_area_id, non_temporary_only=True):
    rows = [d for d in db.all("Driver") if d["service_area_id"] == service_area_id]
    if non_temporary_only:
        rows = [d for d in rows if not d.get("is_temporary")]
    return rows


def qualification_failures(service_area_id):
    roster = driver_roster(service_area_id)
    failures = 0
    for driver in roster:
        if (
            driver["qualification_status"] != "QUALIFIED"
            or driver["license_class"] == "CLASS_C"
            or driver["status"] in ("SUSPENDED", "TERMINATED")
        ):
            failures += 1
    return roster, failures


def driver_qualification_compliance(service_area_id):
    """(compliance_pct, failures). Empty roster records 100.00 with zero failures."""
    roster, failures = qualification_failures(service_area_id)
    if not roster:
        return 100.00, 0
    pct = round_score(to_decimal(len(roster) - failures) / to_decimal(len(roster)) * HUNDRED)
    return pct, failures


# ---------------------------------------------------------------------------
# owned_vehicle_count_reconciliation
# ---------------------------------------------------------------------------

def brand_compliance_pct(provider_id, include_pending=False):
    """Percentage over the ACTIVE non-temporary fleet; DECOMMISSIONED rows never
    enter the denominator. The transfer-approval variant widens the denominator
    to every owned non-temporary vehicle that is not DECOMMISSIONED."""
    fleet = [v for v in db.all("Vehicle")
             if v["provider_id"] == provider_id and not v.get("is_temporary")]
    if include_pending:
        denominator = [v for v in fleet if v["status"] != "DECOMMISSIONED"]
    else:
        denominator = [v for v in fleet if v["status"] == "ACTIVE"]
    if not denominator:
        return 0.00
    passed = len([v for v in denominator if v["branding_compliance"] == "PASSED"])
    return round_score(to_decimal(passed) / to_decimal(len(denominator)) * HUNDRED)


def recompute_brand_compliance(provider_id, include_pending=False):
    provider = db.get("ServiceProvider", provider_id)
    if provider is None:
        return None
    provider["brand_compliance_pct"] = brand_compliance_pct(provider_id, include_pending)
    return provider["brand_compliance_pct"]


# ---------------------------------------------------------------------------
# owned_driver_count_reconciliation
# ---------------------------------------------------------------------------

def recompute_qualification_pct(provider_id, include_suspended=False):
    """Denominator counts only ACTIVE drivers, or every non-terminal driver
    including SUSPENDED ones in the peak-season-end variant. Temporary drivers
    are excluded outright and the denominator is treated as at least one."""
    provider = db.get("ServiceProvider", provider_id)
    if provider is None:
        return None
    roster = [d for d in db.all("Driver")
              if d["provider_id"] == provider_id and not d.get("is_temporary")]
    if include_suspended:
        counted = [d for d in roster if d["status"] != "TERMINATED"]
    else:
        counted = [d for d in roster if d["status"] == "ACTIVE"]
    qualified = len([d for d in counted if d["qualification_status"] == "QUALIFIED"])
    provider["qualification_pct"] = round_score(
        to_decimal(qualified) / to_decimal(max(len(counted), 1)) * HUNDRED
    )
    return provider["qualification_pct"]


def recompute_chargeback_outstanding(provider_id):
    """Sum of CHARGEBACK deduction segments on the provider's RECONCILED and
    RELEASED weeks, not yet offset by a release reduction."""
    provider = db.get("ServiceProvider", provider_id)
    if provider is None:
        return None
    total = 0
    for period in db.all("SettlementPeriod"):
        if period["provider_id"] != provider_id:
            continue
        if period["status"] not in ("RECONCILED", "RELEASED"):
            continue
        total += sum_amounts(period_deductions(period, "CHARGEBACK"))
    provider["chargeback_outstanding_cents"] = total
    return total