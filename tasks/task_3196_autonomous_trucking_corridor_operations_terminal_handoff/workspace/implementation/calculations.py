"""Calculations — SCAFFOLD.yaml §1.3 (Table 3) + PRD §2.6, §2.7, §3.2–§3.11.

Every derived figure produced here is rounded where the rule says so, using
Decimal arithmetic and round-half-up (§2.8: "every derived monetary field is
rounded half up to exactly 2 decimal places at the moment it is computed").

Constants the scaffold names only by symbol are declared once, here, with a
single numeric choice; see CALC_CONSTANTS.
"""

from decimal import Decimal

from core import D, rhu, floor_dec, ceil_dec, num
import db

# --- constants named by symbol in the scaffold ------------------------------
CALC_CONSTANTS = {
    # §3.2 "the heavy-trailer surcharge rate"
    "HEAVY_TRAILER_SURCHARGE_CENTS": Decimal("20"),
    # §3.11 "the larger of a minimum chassis rate and the run's per_mile_rate_cents"
    "MIN_CHASSIS_RATE_CENTS": Decimal("500"),
    # §3.11 "the maintenance unit rate"
    "MAINT_UNIT_RATE": Decimal("2.5"),
    # §3.10 "a slot base of 20000.00 dollars"
    "SLOT_BASE_CENTS": Decimal("20000.00"),
    # §3.10 "an override base amount"
    "OVERRIDE_BASE_CENTS": Decimal("250000.00"),
    # §3.2 "a per-verified-ride-along credit of 1200.00 dollars"
    "PER_VERIFIED_RIDE_ALONG_CENTS": Decimal("1200.00"),
    # §3.11 "a weather adjustment of 8 cents"
    "WEATHER_ADJUSTMENT_CENTS": Decimal("8"),
    # §3.11 route-driven hours quotas (per day / mileage / route load)
    "AUTO_HOURS_PER_DAY_QUOTA": Decimal("1.5"),
    "MILEAGE_HOURS_QUOTA": Decimal("4.25"),
    "ROUTE_LOAD_HOURS_QUOTA": Decimal("2.75"),
    # §3.12 platform commission expressed as basis points
    "COMMISSION_BPS": Decimal("125"),
    # §2.6 calibration variance tolerance / readiness variance cap
    "VARIANCE_TOLERANCE_MS": Decimal("150"),
    "VARIANCE_CAP": Decimal("40"),
    "PASS_WEIGHT": Decimal("60"),
    "PENDING_WEIGHT": Decimal("20"),
}

HTS = CALC_CONSTANTS["HEAVY_TRAILER_SURCHARGE_CENTS"]
MIN_CHASSIS = CALC_CONSTANTS["MIN_CHASSIS_RATE_CENTS"]
MAINT_UNIT_RATE = CALC_CONSTANTS["MAINT_UNIT_RATE"]
SLOT_BASE = CALC_CONSTANTS["SLOT_BASE_CENTS"]
OVERRIDE_BASE = CALC_CONSTANTS["OVERRIDE_BASE_CENTS"]
RIDE_ALONG_CREDIT = CALC_CONSTANTS["PER_VERIFIED_RIDE_ALONG_CENTS"]
WEATHER_ADJ = CALC_CONSTANTS["WEATHER_ADJUSTMENT_CENTS"]
COMMISSION_BPS = CALC_CONSTANTS["COMMISSION_BPS"]
VARIANCE_TOL = Decimal("150")
VARIANCE_CAP = Decimal("40")
PASS_WEIGHT = Decimal("60")
PENDING_WEIGHT = Decimal("20")
ROUNDTRIP_FACTOR = Decimal("0.5")
LATE_RATE = Decimal("0.0105")
WEATHER_ATTRIBUTION_CENTS = Decimal("8.037")


# ---------------------------------------------------------------------------
# §2.6 / §3.1 — corridor_readiness_score
# ---------------------------------------------------------------------------


def check_base_score(check):
    """Part A, pre-cap: weighted result points plus the calibration variance."""
    result = check.get("check_result")
    weighted = (PASS_WEIGHT if result == "PASS"
                else PENDING_WEIGHT if result == "PENDING"
                else Decimal(0))
    variance = D(check.get("calibration_variance_ms", 0))
    base = rhu(weighted + variance, 2)
    if variance <= VARIANCE_TOL and base > 100:
        return rhu(VARIANCE_CAP, 2)
    return base


def included_checks(corridor_id):
    """§2.6: a row is included only when check_status is CALIBRATION_PASSED or
    VALIDATED and its is_test_payload flag is false."""
    return [c for c in db.by("launch_readiness_checks", "corridor_id", corridor_id)
            if c.get("check_status") in ("CALIBRATION_PASSED", "VALIDATED")
            and not c.get("is_test_payload")]


def corridor_readiness_score(corridor_id):
    rows = included_checks(corridor_id)
    if not rows:
        return rhu(0, 2)
    total = sum((check_base_score(c) for c in rows), Decimal(0))
    return rhu(total / Decimal(len(rows)), 2)


def check_contribution(check):
    """The check_level variant surfaced as `check_contribution`."""
    return check_base_score(check)


# ---------------------------------------------------------------------------
# §3.2 / §3.11 — carrier_rate_reconciliation
# ---------------------------------------------------------------------------


def provisional_quote(posted_per_mile_cents, discount):
    """net_provisional_cents = ROUND_HALF_UP(posted - discount, 2)."""
    return rhu(D(posted_per_mile_cents) - D(discount), 2)


def settled_net(net_provisional_cents):
    """+= COMMISSION_BPS of the provisional quote (125 basis points)."""
    q = D(net_provisional_cents)
    return rhu(q + q * COMMISSION_BPS / Decimal(10000), 2)


def carrier_rate_reconciliation(run_plan, carrier):
    quote = provisional_quote(run_plan.get("posted_per_mile_cents", 0),
                              discount_for_tier(carrier.get("safety_tier")))
    return quote, settled_net(quote)


# ---------------------------------------------------------------------------
# §3.2 — committed_rate_resolution and the safety tiers
# ---------------------------------------------------------------------------


def safety_tier_for_score(score):
    """§3.6: HIGH at or above 800, MEDIUM from 500 through 799, LOW below 500."""
    score = D(score)
    if score >= 800:
        return "HIGH"
    if score >= 500:
        return "MEDIUM"
    return "LOW"


def discount_for_tier(tier):
    """committed_discount_cents is 0 at HIGH, 15 at MEDIUM, 40 at LOW."""
    return {"HIGH": Decimal("0"), "MEDIUM": Decimal("15"), "LOW": Decimal("40")}.get(
        tier, Decimal("0"))


def per_mile_rate(posted_per_mile_cents, trailer_count):
    """§3.2: posted plus ceil(trailer_count / 2) surcharge units for any count
    of at least 1 — a single-trailer run adds one unit and a two-trailer run adds
    one as well."""
    posted = D(posted_per_mile_cents)
    tc = int(trailer_count or 0)
    if tc < 1:
        return rhu(posted, 2)
    units = -((-tc) // 2)  # ceil(tc / 2) for positive ints
    return rhu(posted + Decimal(units) * HTS, 2)


def committed_rate(per_mile, shipper_floor, discount):
    """floor_rate = MAX(per_mile_rate_cents, shipper_floor_per_mile_cents);
    committed_rate_cents = ROUND_HALF_UP(floor_rate - discount, 2)."""
    floor_rate = max(D(per_mile), D(shipper_floor))
    return rhu(floor_rate - D(discount), 2)


# ---------------------------------------------------------------------------
# §3.11 — scenario_rate_estimate
# ---------------------------------------------------------------------------


def scenario_rate(per_mile, shipper_floor, weather_risk_score):
    """base * COVERAGE_MONTHS plus weather_risk_score * WEATHER_ADJUSTMENT_CENTS,
    each term rounded half up, then rounded once more."""
    base = max(D(per_mile), D(shipper_floor))
    working = rhu(base * Decimal(1), 2)
    effort = rhu(D(weather_risk_score) * WEATHER_ADJ, 2)
    return rhu(working + effort, 2)


def scenario_rate_one_month_only(per_mile, shipper_floor):
    """The near-variant drops the weather effort term entirely."""
    base = max(D(per_mile), D(shipper_floor))
    return rhu(base * Decimal(1), 2)


# ---------------------------------------------------------------------------
# §2.7 / §3.9 — transfer_turnaround_index and the apron buffer
# ---------------------------------------------------------------------------


def transfer_turnaround_minutes(terminal_id):
    approved = [w for w in db.by("terminal_service_windows", "terminal_id", terminal_id)
                if w.get("window_status") == "APPROVED"]
    count = len(approved)
    total = sum((int(w.get("handoff_duration_minutes") or 0) for w in approved), 0)
    if count == 0:
        return 0
    return rhu(Decimal(total) * ROUNDTRIP_FACTOR / Decimal(count), 3)


def total_handoff_minutes(terminal_id):
    approved = [w for w in db.by("terminal_service_windows", "terminal_id", terminal_id)
                if w.get("window_status") == "APPROVED"]
    return sum((int(w.get("handoff_duration_minutes") or 0) for w in approved), 0)


def approved_window_count(terminal_id):
    return len([w for w in db.by("terminal_service_windows", "terminal_id", terminal_id)
                if w.get("window_status") == "APPROVED"])


def window_length_minutes(window):
    return int(window.get("window_end_minute") or 0) - int(window.get("window_start_minute") or 0)


def reserved_apron_units(terminal_id):
    """§2.7: SUM over APPROVED windows of round_half_up(length / 60, 2)."""
    approved = [w for w in db.by("terminal_service_windows", "terminal_id", terminal_id)
                if w.get("window_status") == "APPROVED"]
    total = Decimal(0)
    for w in approved:
        total += rhu(Decimal(window_length_minutes(w)) / Decimal(60), 2)
    return rhu(total, 2)


def buffer_seconds(service_type, window_length):
    """§2.7: HANDOFF_INBOUND is floor(length + 0.49); every other service type is
    floor(length + 0.51), rendered as whole seconds."""
    length = D(window_length)
    if service_type == "HANDOFF_INBOUND":
        return int(floor_dec(length + Decimal("0.49"), 0))
    return int(floor_dec(length + Decimal("0.51"), 0))


def apron_effective_end(window):
    """effective_end = window_end_minute + buffer_minutes."""
    return int(window.get("window_end_minute") or 0) + int(window.get("buffer_minutes") or 0)


def apron_overlaps(terminal_id, start, end_with_buffer, exclude_id=None):
    """§2.7 adjacency rule: touching windows do not occupy.  A new window whose
    start equals an existing window's effective end — its end minute plus its
    buffer — is permitted, but any window that would share even a single minute
    with an existing approved or in-service window is rejected."""
    for w in db.by("terminal_service_windows", "terminal_id", terminal_id):
        if w["id"] == exclude_id:
            continue
        if w.get("window_status") not in ("APPROVED", "IN_SERVICE"):
            continue
        w_start = int(w.get("window_start_minute") or 0)
        w_end = apron_effective_end(w)
        if start < w_end and w_start < end_with_buffer:
            return w
    return None


def monitoring_expanded_interval(window):
    """§2.7: under GEOFENCE_PLUS_BUFFER the interval is expanded multiplicatively
    by 1.5 before screening; under GEOFENCE_ONLY the exact intervals are used."""
    from core import parse_iso
    start = parse_iso(window.get("monitoring_start_at"))
    end = parse_iso(window.get("monitoring_end_at"))
    if start is None or end is None:
        return (None, None)
    if window.get("geofence_type") == "GEOFENCE_PLUS_BUFFER":
        span = (end - start) * 1.5 / 2
        return (start - span, end + span)
    return (start, end)


def monitoring_overlaps(corridor_id, operator_ids, interval, exclude_id=None):
    """Same operator, same corridor, either seat, either direction."""
    start, end = interval
    if start is None or end is None:
        return None
    for w in db.by("remote_support_assignments", "corridor_id", corridor_id):
        if w["id"] == exclude_id:
            continue
        if w.get("assignment_status") not in ("SCHEDULED", "MONITORING"):
            continue
        if not ({w.get("remote_operator_id"), w.get("safety_support_operator_id")}
                & set(operator_ids)):
            continue
        w_start, w_end = monitoring_expanded_interval(w)
        if w_start is None or w_end is None:
            continue
        if start < w_end and w_start < end:
            return w
    return None


# ---------------------------------------------------------------------------
# §3.4 — safe_stop_fee
# ---------------------------------------------------------------------------


def safe_stop_fee(corridor, run_plan, carrier):
    band = carrier.get("incident_band")
    health = (Decimal("1.0") if band == "CLEAN"
              else Decimal("1.5") if band == "WATCH" else Decimal("2.0"))
    exposure = rhu(D(corridor.get("highway_segment_miles", 0))
                   * D(corridor.get("weather_risk_score", 0))
                   * D(run_plan.get("trailer_count", 0))
                   * health, 2)
    return _fee_for_exposure(exposure), exposure


def _fee_for_exposure(exposure):
    """Boundaries are exact: 1000 falls in the 25000 band, 999.99 stays at 0."""
    e = D(exposure)
    if e < 1000:
        return Decimal(0)
    if e < 5000:
        return Decimal(25000)
    return Decimal(60000)


def safe_stop_fee_transit_minutes(corridor):
    """The near-variant substitutes mileage-scaled transit minutes."""
    minutes = rhu(D(corridor.get("highway_segment_miles", 0)) * Decimal("1.6"), 2)
    return _fee_for_exposure(minutes)


# ---------------------------------------------------------------------------
# §3.8 — driver_reroute_risk
# ---------------------------------------------------------------------------


def driver_reroute_risk(corridor_id, hauler_team_id, credential_event_count=0):
    group = [r for r in db.by("run_plans", "corridor_id", corridor_id)
             if r.get("hauler_team_id") == hauler_team_id
             and r.get("run_status") in ("READINESS_PENDING", "IN_TRANSIT")]
    max_score = max((D(r.get("safety_score", 0)) for r in group), default=Decimal(0))
    weighted = max_score * Decimal("0.5")
    reduced = weighted - Decimal("50") * Decimal(1 if credential_event_count else 0)
    return rhu(max(reduced, Decimal(0)), 2)


def driver_reroute_risk_fleet_scoped(hauler_team_id, credential_event_count=0):
    """Fleet-scoped variant maximises across every non-terminal run plan."""
    live = [r for r in db.all_rows("run_plans")
            if r.get("run_status") not in ("COMPLETED", "ABORTED")]
    max_score = max((D(r.get("safety_score", 0)) for r in live), default=Decimal(0))
    weighted = max_score * Decimal("0.5")
    reduced = weighted - Decimal("50") * Decimal(1 if credential_event_count else 0)
    return rhu(max(reduced, Decimal(0)), 2)


# ---------------------------------------------------------------------------
# §2.5 / §3.12 — regulatory_charge_allocation
# ---------------------------------------------------------------------------


def _engagement_in_epoch(engagement, epoch_start, epoch_end):
    if epoch_start is None or epoch_end is None:
        return True
    from core import parse_iso
    at = parse_iso(engagement.get("engaged_at"))
    if at is None:
        return False
    return epoch_start <= at < epoch_end


def authority_hours_used(authority_id):
    """hours_used counts only engagements whose engagement_status is SUBMITTED
    within the current epoch window; DRAFT and REJECTED never debit."""
    from core import epoch_window
    epoch_start, epoch_end = epoch_window()
    total = 0
    for e in db.by("regulatory_engagements", "state_authority_id", authority_id):
        if e.get("engagement_status") != "SUBMITTED":
            continue
        if not _engagement_in_epoch(e, epoch_start, epoch_end):
            continue
        total += int(e.get("autonomous_hours_logged") or 0)
    return total


def remaining_autonomous_hours(authority):
    used = authority_hours_used(authority["id"])
    remaining = int(authority.get("autonomous_hours_allowed") or 0) - used
    return max(remaining, 0)


def prior_accepted_in_epoch(authority_id, exclude_id=None):
    from core import epoch_window
    epoch_start, epoch_end = epoch_window()
    for e in db.by("regulatory_engagements", "state_authority_id", authority_id):
        if e["id"] == exclude_id:
            continue
        if e.get("engagement_status") != "ACCEPTED":
            continue
        if _engagement_in_epoch(e, epoch_start, epoch_end):
            return e
    return None


def hours_charge_allowed(engagement):
    """True only when state_status is FORMAL or INFORMAL and an ACCEPTED prior
    engagement already exists in the same epoch."""
    if engagement.get("state_status") not in ("FORMAL", "INFORMAL"):
        return False
    return prior_accepted_in_epoch(engagement.get("state_authority_id"),
                                   exclude_id=engagement["id"]) is not None


def state_status_for(engagement_type, weather_profile):
    """§3.12: FORMAL for SAFETY_BRIEFING or INCIDENT_DISCLOSURE, INFORMAL for an
    OPERATIONAL_NOTICE when the corridor weather profile is CLEAR_DEFAULT, and
    EXEMPT in every other case."""
    if engagement_type in ("SAFETY_BRIEFING", "INCIDENT_DISCLOSURE"):
        return "FORMAL"
    if engagement_type == "OPERATIONAL_NOTICE" and weather_profile == "CLEAR_DEFAULT":
        return "INFORMAL"
    return "EXEMPT"


# ---------------------------------------------------------------------------
# §3.11 — run_plan_exposure
# ---------------------------------------------------------------------------


def run_plan_exposure(run_plan, corridor):
    """applicable + late fee + weather fee; per-term rounding is the variant the
    platform attributes line by line for carrier invoicing."""
    committed = D(run_plan.get("committed_rate_cents", 0))
    discount = D(run_plan.get("_committed_discount_cents",
                              run_plan.get("committed_discount_cents", 0)))
    applicable = rhu(committed - discount, 2)
    late_fee = rhu(LATE_RATE * committed * Decimal(late_count(run_plan)), 2)
    weather_fee = rhu(D(corridor.get("weather_risk_score", 0)) * WEATHER_ATTRIBUTION_CENTS, 2)
    return rhu(applicable + late_fee + weather_fee, 2)


def run_plan_exposure_aggregate(run_plan, corridor):
    """The rolled-up reading: unrounded terms summed and rounded once."""
    committed = D(run_plan.get("committed_rate_cents", 0))
    discount = D(run_plan.get("_committed_discount_cents",
                              run_plan.get("committed_discount_cents", 0)))
    applicable = committed - discount
    late_fee = LATE_RATE * committed * Decimal(late_count(run_plan))
    weather_fee = D(corridor.get("weather_risk_score", 0)) * WEATHER_ATTRIBUTION_CENTS
    return rhu(applicable + late_fee + weather_fee, 2)


def late_count(run_plan):
    """The number of days window_start_epoch_day trails the current ledger epoch
    day, floored at 0."""
    from core import epoch_day
    return max(int(run_plan.get("window_start_epoch_day") or 0) - epoch_day(), 0)


# ---------------------------------------------------------------------------
# §3.11 — fleet unit maintenance readings
# ---------------------------------------------------------------------------


def fleet_maint_charges(hours_posted_total):
    return floor_dec(D(hours_posted_total) * MAINT_UNIT_RATE, 2)


def fleet_maint_projection(maint_charges, weather_profile):
    """Evaluated second in the pinned order; 1.08 for HIGH_WIND or LOW_VISIBILITY."""
    disc = Decimal("1.08") if weather_profile in ("HIGH_WIND", "LOW_VISIBILITY") else Decimal("1.0")
    return floor_dec(D(maint_charges) * disc, 2)


def fleet_remain_hours(weather_clearance_hours, hours_posted_total):
    return max(int(weather_clearance_hours or 0) - int(hours_posted_total or 0), 0)


def route_driven_hours_cents(is_watch_squad):
    auto = CALC_CONSTANTS["AUTO_HOURS_PER_DAY_QUOTA"]
    mileage = CALC_CONSTANTS["MILEAGE_HOURS_QUOTA"]
    route_load = CALC_CONSTANTS["ROUTE_LOAD_HOURS_QUOTA"]
    if is_watch_squad:
        route_load = route_load * Decimal(2)
    return floor_dec((auto + mileage + route_load) * Decimal(100), 2)


def chassis_holding_rate(per_mile_rate_cents, coverage_days):
    return rhu(max(MIN_CHASSIS, D(per_mile_rate_cents)) * Decimal(int(coverage_days or 0)), 2)


# ---------------------------------------------------------------------------
# §3.10 — container booking readings
# ---------------------------------------------------------------------------


def container_unit_rate(length_feet):
    return floor_dec(SLOT_BASE * D(length_feet) / Decimal(40), 2)


def vgm_override_fee(booked_vgm_kg_sum):
    total = D(booked_vgm_kg_sum)
    if total <= 0:
        return rhu(0, 2)
    return rhu(ceil_dec(OVERRIDE_BASE / total, 2), 2)


def ride_along_credit(verified_count):
    return floor_dec(RIDE_ALONG_CREDIT * Decimal(int(verified_count or 0)) / Decimal(2), 2)


# ---------------------------------------------------------------------------
# §3.7 — residual risk
# ---------------------------------------------------------------------------


def residual_risk_score(hazard_count, highway_segment_miles):
    miles_factor = floor_dec(D(highway_segment_miles) / Decimal(100), 3)
    return floor_dec((Decimal(1) + D(hazard_count)) * (Decimal(1) + miles_factor), 2)


# ---------------------------------------------------------------------------
# §3.6 / §2.5 — carrier safety arithmetic
# ---------------------------------------------------------------------------


def carrier_safety_score(previous_epoch_incidents):
    return max(900 - 25 * int(previous_epoch_incidents or 0), 0)


def incident_band_for(recordable_incidents_last_epoch):
    n = int(recordable_incidents_last_epoch or 0)
    if n >= 5:
        return "SUSPENDED"
    if n >= 2:
        return "WATCH"
    return "CLEAN"


def commitment_consumed_slots(commitment_id):
    live = ("READINESS_PENDING", "DISPATCH_READY", "IN_TRANSIT", "COMPLETED")
    return len([r for r in db.by("run_plans", "shipper_commitment_id", commitment_id)
                if r.get("run_status") in live])


def verified_ride_along_count(commitment_id):
    """Counts the transition enrolments on the commitment's runs that reached
    RIDE_ALONG_VERIFIED."""
    run_ids = {r["id"] for r in db.by("run_plans", "shipper_commitment_id", commitment_id)}
    count = 0
    for rid, tids in db.sides["run_ride_along_transitions"].items():
        if rid not in run_ids:
            continue
        for tid in tids:
            t = db.get("driver_transitions", tid)
            if t and t.get("transition_status") == "RIDE_ALONG_VERIFIED":
                count += 1
    return count


# ---------------------------------------------------------------------------
# §3.10 — shipping instruction aggregates
# ---------------------------------------------------------------------------


def attached_units(instruction_id):
    ids = db.sides["instruction_units"].get(instruction_id, [])
    out = []
    for uid in ids:
        u = db.get("container_units", uid)
        if u is not None:
            out.append(u)
    return out


VGM_STATUSES = ("INGATED", "LOADED", "ON_VESSEL", "DISCHARGED")


def booked_vgm_kg_sum(instruction_id):
    """Sum of gross_weight_kg across attached units in INGATED, LOADED,
    ON_VESSEL or DISCHARGED."""
    total = Decimal(0)
    for u in attached_units(instruction_id):
        if u.get("unit_status") in VGM_STATUSES:
            total += D(u.get("gross_weight_kg", 0))
    return rhu(total, 2)


def highest_length_tier(instruction_id):
    lengths = [int(u.get("length_feet") or 0) for u in attached_units(instruction_id)]
    return max(lengths) if lengths else 0


def length_tier(length_feet):
    """The length tier of the highest attached container.  20 / 40 / 45 feet."""
    if length_feet >= 45:
        return "TIER_45"
    if length_feet >= 40:
        return "TIER_40"
    return "TIER_20"


TIER_FREIGHT_RATE = {
    "TIER_20": Decimal("1500.00"),
    "TIER_40": Decimal("2500.00"),
    "TIER_45": Decimal("2950.00"),
}

TIER_DISCOUNT = {
    "TIER_20": Decimal("0.00"),
    "TIER_40": Decimal("125.00"),
    "TIER_45": Decimal("175.00"),
}


def booked_line_total_cents(instruction_id, carried_only=False):
    """The per-row charge rounded per row and then summed, with a per-line
    freight rate and the length tier of the highest attached container."""
    units = attached_units(instruction_id)
    if carried_only:
        units = [u for u in units if u.get("unit_status") not in ("OFFLOADED", "PENDING")]
        units = [u for u in units if u.get("unit_status") != "GATED_OUT"]
    tier = length_tier(highest_length_tier(instruction_id))
    rows = [u for u in units if u.get("unit_status") != "PENDING"]
    total = Decimal(0)
    for _ in rows:
        total += rhu(TIER_FREIGHT_RATE[tier], 2)
    return rhu(total, 2)


def container_discount_cents(instruction_id):
    tier = length_tier(highest_length_tier(instruction_id))
    return rhu(TIER_DISCOUNT[tier], 2)