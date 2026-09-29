"""Calculation rules (SCAFFOLD s1.3 / PRD s3.5-s3.8).

Every rounding point below is pinned exactly where the specification puts it.
"""

from datetime import timedelta
from decimal import Decimal

from store import (
    AUTO_FINE_ORDINAL,
    CLASSIFICATION_W2_SCORE_THRESHOLD,
    CONTROL_WEIGHT_EQUIPMENT,
    CONTROL_WEIGHT_EXCLUSIVITY,
    CONTROL_WEIGHT_FIXED_SCHEDULE,
    CONTROL_WEIGHT_FULLTIME_HOURS,
    DELINQUENCY_THRESHOLD_CENTS,
    FINE_BASE_CENTS,
    FINE_ESCALATION_MULTIPLIER,
    FINE_FLOOR_CENTS,
    FINE_LOOKBACK_DAYS,
    LIVE_ROUTE_STATUSES,
    MONTHLY_FINE_CAP_CENTS,
    OBSERVED_EXCLUSIVITY_MIN_ROUTES,
    OBSERVED_FULLTIME_WEEKLY_HOURS,
    OBSERVED_WINDOW_DAYS,
    PARTIAL_NIGHT_WEIGHT,
    SEASONAL_PEAK_INDEX,
    SEASONAL_PEAK_MULTIPLIER,
    SLA_TIER1_CREDIT_BPS,
    SLA_TIER2_CREDIT_BPS,
    SLA_TIER2_ENTRY_BPS,
    VERIFICATION_COVERAGE_THRESHOLD_BPS,
    clock,
    db,
    days_in_month,
    parse_date,
    parse_instant,
    parse_period,
    period_bounds,
    rhu,
    rhu2,
    sort_rows,
)

TERMINAL_VERIFICATION = ("VERIFIED", "PARTIAL", "MISSED", "CANCELLED")


# ---------------------------------------------------------------------------
# Collection helpers
# ---------------------------------------------------------------------------
def residents_of_property(property_id):
    return sort_rows([r for r in db.residents.values() if r["property_id"] == property_id])


def contracts_of_property(property_id):
    return sort_rows([c for c in db.contracts.values() if c["property_id"] == property_id])


def nights_of_contract(contract_id):
    return sort_rows([n for n in db.nights.values() if n["contract_id"] == contract_id])


def routes_of_night(night_id):
    return sort_rows([r for r in db.routes.values() if r["service_night_id"] == night_id])


def routes_of_contractor(contractor_id):
    return sort_rows([r for r in db.routes.values() if r["contractor_id"] == contractor_id])


def scans_of_night(night_id):
    return sort_rows([s for s in db.scans.values() if s["service_night_id"] == night_id])


def scans_of_route(route_id):
    return sort_rows([s for s in db.scans.values() if s["route_assignment_id"] == route_id])


def fines_of_resident(resident_id):
    return sort_rows([f for f in db.fines.values() if f["resident_id"] == resident_id])


def fines_of_scan(scan_id):
    return sort_rows([f for f in db.fines.values() if f["scan_id"] == scan_id])


def incidents_of_property(property_id):
    return sort_rows([i for i in db.incidents.values() if i["property_id"] == property_id])


def statements_of_contract(contract_id):
    return sort_rows([s for s in db.statements.values() if s["contract_id"] == contract_id])


# ---------------------------------------------------------------------------
# Occupancy window (PRD s3.2): move_in inclusive, move_out EXCLUSIVE
# ---------------------------------------------------------------------------
def occupies_on(resident, on_date):
    move_in = parse_date(resident["move_in_date"])
    if move_in is None or on_date < move_in:
        return False
    move_out = parse_date(resident["move_out_date"]) if resident.get("move_out_date") else None
    if move_out is not None and not (on_date < move_out):
        return False
    return True


def billable_days_in_period(resident, first_date, last_date):
    move_in = parse_date(resident["move_in_date"])
    if move_in is None:
        return 0
    lo = move_in if move_in > first_date else first_date
    hi = last_date
    move_out = parse_date(resident["move_out_date"]) if resident.get("move_out_date") else None
    if move_out is not None:
        last_billed = move_out - timedelta(days=1)
        if last_billed < hi:
            hi = last_billed
    if hi < lo:
        return 0
    return (hi - lo).days + 1


# ---------------------------------------------------------------------------
# calculations.service_night_verification
# ---------------------------------------------------------------------------
def expected_door_count(night):
    from authz import property_of_night

    prop = property_of_night(night)
    if prop is None:
        return 0
    service_date = parse_date(night["service_date"])
    count = 0
    for resident in residents_of_property(prop["id"]):
        if not resident["fee_passthrough_enabled"]:
            continue
        if occupies_on(resident, service_date):
            count += 1
    return count


def scanned_door_count(night):
    total = 0
    for scan in scans_of_night(night["id"]):
        if scan["scan_result"] in ("SERVICED", "NO_SET_OUT"):
            total += 1
    return total


def coverage_bps(scanned, expected):
    if expected == 0:
        return 0
    return rhu(Decimal(10000) * Decimal(scanned) / Decimal(expected))


def recompute_night_counters(night):
    """Recompute expected_door_count, scanned_door_count and coverage_bps in place."""
    night["expected_door_count"] = expected_door_count(night)
    night["scanned_door_count"] = scanned_door_count(night)
    night["coverage_bps"] = coverage_bps(night["scanned_door_count"], night["expected_door_count"])
    return night


def select_verification_outcome(night):
    """Close-time selection, evaluated in the pinned order."""
    if night["scanned_door_count"] == 0:
        return "MISSED"
    if night["coverage_bps"] >= VERIFICATION_COVERAGE_THRESHOLD_BPS:
        return "VERIFIED"
    return "PARTIAL"


# ---------------------------------------------------------------------------
# calculations.route_unit_coverage  (conserved quantity, full re-aggregation)
# ---------------------------------------------------------------------------
def recompute_assigned_unit_coverage(night):
    total = 0
    for route in routes_of_night(night["id"]):
        if route["status"] in LIVE_ROUTE_STATUSES:
            total += route["unit_coverage_count"]
    night["assigned_unit_coverage_count"] = total
    return total


# ---------------------------------------------------------------------------
# calculations.resident_fine_amount  (round -> floor -> cap)
# ---------------------------------------------------------------------------
def compute_offense_ordinal(resident_id, non_compliance_type, exclude_scan_id=None):
    if not non_compliance_type:
        return 0
    now = clock.now()
    window_start = now - timedelta(days=FINE_LOOKBACK_DAYS)
    count = 0
    for scan in sort_rows(list(db.scans.values())):
        if exclude_scan_id is not None and scan["id"] == exclude_scan_id:
            continue
        if scan["resident_id"] != resident_id:
            continue
        if scan.get("non_compliance_type") != non_compliance_type:
            continue
        if scan.get("tag_status") not in ("OPEN", "FINED"):
            continue
        created = parse_instant(scan["created_at"])
        if created is None:
            continue
        if created < window_start or created > now:
            continue
        count += 1
    return 1 + count


def fines_assessed_this_period_cents(resident_id):
    """Running total of amount_cents for fines created inside the logical clock's month."""
    now = clock.now()
    total = 0
    for fine in fines_of_resident(resident_id):
        created = parse_instant(fine["created_at"])
        if created is None:
            continue
        if created.year == now.year and created.month == now.month:
            total += fine["amount_cents"]
    return total


def remaining_fine_cap_cents(resident_id):
    used = fines_assessed_this_period_cents(resident_id)
    remaining = MONTHLY_FINE_CAP_CENTS - used
    return remaining if remaining > 0 else 0


def compute_fine_amount(scan, night, resident):
    tag_type = scan["non_compliance_type"]
    ordinal = scan["offense_ordinal"] or 1
    base_cents = FINE_BASE_CENTS[tag_type]
    clamped = ordinal if ordinal <= 3 else 3
    if clamped < 1:
        clamped = 1
    multiplier = FINE_ESCALATION_MULTIPLIER[clamped]
    peak = night is not None and night.get("seasonal_volume_index", 100) >= SEASONAL_PEAK_INDEX
    seasonal_factor = SEASONAL_PEAK_MULTIPLIER if peak else Decimal("1.0")
    raw_exact = Decimal(base_cents) * multiplier * seasonal_factor
    rounded_cents = rhu(raw_exact)                                    # round ONCE
    floored_cents = rounded_cents if rounded_cents > FINE_FLOOR_CENTS else FINE_FLOOR_CENTS
    remaining_cap = remaining_fine_cap_cents(resident["id"])
    amount_cents = floored_cents if floored_cents < remaining_cap else remaining_cap
    return {
        "base_cents": base_cents,
        "escalation_multiplier": multiplier,
        "seasonal_uplift_applied": bool(peak),
        "uncapped_amount_cents": floored_cents,
        "amount_cents": amount_cents,
    }


def auto_fine_applies(scan):
    if not scan.get("non_compliance_type"):
        return False
    if scan["non_compliance_type"] == "RECYCLING_CONTAMINATION":
        return True
    return (scan.get("offense_ordinal") or 0) >= AUTO_FINE_ORDINAL


# ---------------------------------------------------------------------------
# calculations.resident_delinquency_rollup  (conserved quantities)
# ---------------------------------------------------------------------------
def outstanding_fines_cents(resident_id):
    total = 0
    for fine in fines_of_resident(resident_id):
        if fine["status"] in ("ASSESSED", "DISPUTED", "UPHELD"):
            total += fine["amount_cents"]
    return total


def derive_collections_status(outstanding):
    return "DELINQUENT" if outstanding >= DELINQUENCY_THRESHOLD_CENTS else "CURRENT"


# ---------------------------------------------------------------------------
# calculations.property_escalation_rollup
# ---------------------------------------------------------------------------
def escalated_incident_count(property_id):
    return len([i for i in incidents_of_property(property_id) if i["status"] == "ESCALATED"])


def has_escalated_jam(property_id):
    for incident in incidents_of_property(property_id):
        if incident["incident_type"] == "JAM" and incident["status"] == "ESCALATED":
            return True
    return False


# ---------------------------------------------------------------------------
# calculations.contractor_classification_score
# ---------------------------------------------------------------------------
def observed_audit_set(contractor_id):
    """COMPLETED routes whose night's service_date lies in the closed trailing window."""
    end_date = clock.now().date()
    start_date = end_date - timedelta(days=OBSERVED_WINDOW_DAYS - 1)
    audited = []
    for route in routes_of_contractor(contractor_id):
        if route["status"] != "COMPLETED":
            continue
        night = db.nights.get(route["service_night_id"])
        if night is None:
            continue
        service_date = parse_date(night["service_date"])
        if service_date is None or service_date < start_date or service_date > end_date:
            continue
        audited.append((service_date, route.get("created_at") or "", route.get("_seq", 0), route, night))
    audited.sort(key=lambda t: (t[0], t[1], t[2]))
    return [(t[3], t[4]) for t in audited]


def compute_classification(contractor, basis):
    equipment_factor = CONTROL_WEIGHT_EQUIPMENT if contractor["equipment_provided_by_company"] else 0
    fixed_schedule_factor = CONTROL_WEIGHT_FIXED_SCHEDULE if not contractor["sets_own_schedule"] else 0

    observed_hours = None
    if basis == "DECLARED":
        hours_factor = (
            CONTROL_WEIGHT_FULLTIME_HOURS
            if Decimal(contractor["weekly_committed_hours"]) >= OBSERVED_FULLTIME_WEEKLY_HOURS
            else 0
        )
        exclusivity_factor = CONTROL_WEIGHT_EXCLUSIVITY if contractor["works_exclusively"] else 0
    else:
        audited = observed_audit_set(contractor["id"])
        total_hours = Decimal(0)
        property_ids = set()
        from authz import property_of_night

        for route, night in audited:
            start = parse_instant(night["service_window_start"])
            end = parse_instant(night["service_window_end"])
            if start is not None and end is not None:
                seconds = Decimal((end - start).total_seconds())
                total_hours += seconds / Decimal(3600)
            prop = property_of_night(night)
            property_ids.add(prop["id"] if prop else None)
        observed_hours = rhu2(total_hours)
        hours_factor = CONTROL_WEIGHT_FULLTIME_HOURS if observed_hours >= OBSERVED_FULLTIME_WEEKLY_HOURS else 0
        exclusivity_factor = (
            CONTROL_WEIGHT_EXCLUSIVITY
            if len(audited) >= OBSERVED_EXCLUSIVITY_MIN_ROUTES and len(property_ids) == 1
            else 0
        )

    control_score = equipment_factor + fixed_schedule_factor + hours_factor + exclusivity_factor
    classification = (
        "EMPLOYEE_W2" if control_score >= CLASSIFICATION_W2_SCORE_THRESHOLD else "CONTRACTOR_1099"
    )
    return {
        "control_score": control_score,
        "classification": classification,
        "observed_weekly_hours": observed_hours,
    }


# ---------------------------------------------------------------------------
# calculations.resident_passthrough_line  +  calculations.statement_settlement
# ---------------------------------------------------------------------------
def passthrough_line_sum(contract, prop, billing_period):
    year, month = parse_period(billing_period)
    day_count = days_in_month(year, month)
    first_date, last_date = period_bounds(billing_period)
    daily_rate_exact = Decimal(contract["per_unit_monthly_fee_cents"]) / Decimal(day_count)
    total = 0
    for resident in residents_of_property(prop["id"]):
        if not resident["fee_passthrough_enabled"]:
            continue
        days = billable_days_in_period(resident, first_date, last_date)
        total += rhu(daily_rate_exact * Decimal(days))   # round per line, THEN sum
    return total


def nights_in_period(contract_id, billing_period):
    first_date, last_date = period_bounds(billing_period)
    result = []
    for night in nights_of_contract(contract_id):
        service_date = parse_date(night["service_date"])
        if service_date is not None and first_date <= service_date <= last_date:
            result.append(night)
    return result


def statement_settlement(contract, prop, billing_period, variant):
    # ---- S1: gross pass-through -----------------------------------------
    if variant == "PROVISIONAL":
        gross = contract["per_unit_monthly_fee_cents"] * prop["unit_count"]
    else:
        gross = passthrough_line_sum(contract, prop, billing_period)

    # ---- S1b: service shortfall ratio -----------------------------------
    in_period = nights_in_period(contract["id"], billing_period)
    scheduled_night_count = len([n for n in in_period if n["verification_status"] != "CANCELLED"])
    missed_count = 0
    partial_count = 0
    for night in in_period:
        status = night["verification_status"]
        if variant == "PROVISIONAL" and status not in ("VERIFIED", "PARTIAL", "MISSED"):
            continue
        if status == "MISSED":
            missed_count += 1
        elif status == "PARTIAL":
            partial_count += 1
    missed_equivalent = Decimal(missed_count) + PARTIAL_NIGHT_WEIGHT * Decimal(partial_count)
    if scheduled_night_count == 0:
        missed_service_bps = 0
    else:
        missed_service_bps = rhu(
            Decimal(10000) * missed_equivalent / Decimal(scheduled_night_count)
        )

    # ---- S2: SLA credit --------------------------------------------------
    threshold = contract["sla_missed_threshold_bps"]
    if missed_service_bps < threshold:
        rate = 0
    elif missed_service_bps < SLA_TIER2_ENTRY_BPS:
        rate = SLA_TIER1_CREDIT_BPS
    else:
        rate = SLA_TIER2_CREDIT_BPS
    credit = rhu(Decimal(gross) * Decimal(rate) / Decimal(10000))

    # ---- S3: owner revenue share (keyed on gross MINUS credit) -----------
    share = rhu(
        Decimal(gross - credit) * Decimal(contract["property_revenue_share_bps"]) / Decimal(10000)
    )

    # ---- S4: net due (exact integer subtraction) -------------------------
    net = gross - credit - share

    return {
        "gross_passthrough_cents": gross,
        "scheduled_night_count": scheduled_night_count,
        "missed_equivalent_nights": missed_equivalent,
        "missed_service_bps": missed_service_bps,
        "sla_credit_rate_bps": rate,
        "missed_service_credit_cents": credit,
        "property_revenue_share_cents": share,
        "net_due_from_property_cents": net,
    }
