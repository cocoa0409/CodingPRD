"""The eight pinned calculations of PRD section 3, with the rounding order fixed."""
import math
from decimal import Decimal, ROUND_HALF_UP

import store

# --- project_labor_charge ----------------------------------------------------
TIER_A_WIDTH = Decimal("200.00")
TIER_B_WIDTH = Decimal("300.00")
TIER_B_FACTOR = Decimal("0.92")
TIER_C_FACTOR = Decimal("0.85")
SUBFLOOR_MINOR_PCT = Decimal("0.04")
SUBFLOOR_MAJOR_PCT = Decimal("0.09")
OBSTRUCTION_CENTS = 1850
STAIR_FLIGHT_CENTS = 4200
MIN_LABOR_CHARGE_CENTS = 15000

# --- change_order_upcharge ---------------------------------------------------
TRIM_RATE_CENTS = 296
FIXTURE_RATE_CENTS = 7350
CHANGE_ORDER_ADMIN_FACTOR = Decimal("1.06")
CREDIT_CAP_PCT = Decimal("0.50")

# --- installer_scorecard ------------------------------------------------------
BASE_SCORE = Decimal("85.00")
ROLLING_WINDOW_DAYS = 90
CSAT_POINT_STEP = Decimal("5.00")
WEIGHT_QUALITY = Decimal("0.45")
WEIGHT_TIMELINESS = Decimal("0.30")
WEIGHT_SATISFACTION = Decimal("0.25")
PROBATION_COMPOSITE_MAX = Decimal("78.00")
REMOVAL_COMPOSITE_MAX = Decimal("70.00")
MIN_EVENTS_FOR_ACTION = 3
REMOVAL_NO_SHOW_COUNT = 3
REMOVAL_SAFETY_COUNT = 2

# --- cancellation_settlement --------------------------------------------------
FORFEIT_PCT_MEASURED = Decimal("0.10")
FORFEIT_PCT_SCHEDULED = Decimal("0.25")
FORFEIT_PCT_IN_PROGRESS = Decimal("0.50")
RESTOCK_PCT_IN_TRANSIT = Decimal("0.06")
RESTOCK_PCT_DELIVERED = Decimal("0.12")
COOLING_OFF_HOURS = 72
GOODWILL_PROJECT_COUNT = 3
GOODWILL_PCT = Decimal("0.50")
REINSTATE_WINDOW_HOURS = 72

# --- delivery / capacity ------------------------------------------------------
MIN_DELIVERY_SLACK_HOURS = 24
TRAVEL_BUFFER_MINUTES = 90
MAX_COMMITTED_MINUTES = 4800
WARRANTY_LABOR_DAYS = 365

ONE = Decimal("1")
CENTI = Decimal("0.01")


def rhu(value):
    """round_half_up to a whole integer, ties away from zero."""
    return int(Decimal(value).quantize(ONE, rounding=ROUND_HALF_UP))


def rhu2(value):
    """round_half_up to exactly two decimal places."""
    return Decimal(value).quantize(CENTI, rounding=ROUND_HALF_UP)


def dec(value):
    if isinstance(value, Decimal):
        return value
    return Decimal(str(value))


# =============================================================================
# 1. project_labor_charge
# =============================================================================
def labor_charge(project, category, jurisdiction, variant, measurement=None):
    if variant == "PROVISIONAL":
        units = dec(project["estimated_units"])
    else:
        if measurement is not None and measurement.get("measured_units") is not None:
            units = dec(measurement["measured_units"])
        else:
            units = dec(project["estimated_units"])

    billable = max(units, dec(category["minimum_billable_units"]))

    rate = dec(category["base_labor_rate_cents_per_unit"])
    rate_band_b = Decimal(rhu(rate * TIER_B_FACTOR))
    rate_band_c = Decimal(rhu(rate * TIER_C_FACTOR))

    units_a = min(billable, TIER_A_WIDTH)
    units_b = min(max(billable - TIER_A_WIDTH, Decimal("0")), TIER_B_WIDTH)
    units_c = max(billable - TIER_A_WIDTH - TIER_B_WIDTH, Decimal("0"))

    # pinned: round each band to whole cents, then sum
    base_cents = rhu(units_a * rate) + rhu(units_b * rate_band_b) + rhu(units_c * rate_band_c)

    surcharge_cents = 0
    if variant == "FINAL" and measurement is not None and measurement.get("measured_units") is not None:
        condition = measurement.get("subfloor_condition") or "NONE"
        if condition == "MINOR":
            subfloor = rhu(Decimal(base_cents) * SUBFLOOR_MINOR_PCT)
        elif condition == "MAJOR":
            subfloor = rhu(Decimal(base_cents) * SUBFLOOR_MAJOR_PCT)
        else:
            subfloor = 0
        obstructions = int(measurement.get("obstruction_count") or 0) * OBSTRUCTION_CENTS
        stairs = int(measurement.get("stair_flight_count") or 0) * STAIR_FLIGHT_CENTS
        surcharge_cents = subfloor + obstructions + stairs

    # pinned: add, multiply once, round once
    multiplied = rhu(Decimal(base_cents + surcharge_cents) * dec(jurisdiction["labor_complexity_multiplier"]))
    return max(multiplied, MIN_LABOR_CHARGE_CENTS)


def latest_completed_measurement(project_id):
    rows = [
        m for m in store.all_rows("measurements")
        if m["project_id"] == project_id and m["status"] == "COMPLETED"
    ]
    if not rows:
        return None
    rows.sort(key=lambda m: (m["completed_at"], -m["_seq"]), reverse=True)
    return rows[0]


# =============================================================================
# 2. change_order_upcharge
# =============================================================================
def line_rate(unit_kind, category):
    if unit_kind == "PRIMARY_UNITS":
        return dec(category["base_labor_rate_cents_per_unit"])
    if unit_kind == "TRIM_LINEAR_FT":
        return Decimal(TRIM_RATE_CENTS)
    return Decimal(FIXTURE_RATE_CENTS)


def line_itemized_upcharge(lines, category, jurisdiction):
    multiplier = dec(jurisdiction["labor_complexity_multiplier"])
    total = 0
    for line in lines:
        rate = line_rate(line["unit_kind"], category)
        raw = dec(line["units_delta"]) * rate * multiplier * CHANGE_ORDER_ADMIN_FACTOR
        # pinned: round every line before adding any of them
        total += rhu(raw)
    return total


def net_primary_units_delta(lines):
    total = Decimal("0")
    for line in lines:
        if line["unit_kind"] == "PRIMARY_UNITS":
            total += dec(line["units_delta"])
    return total


def variance_disclosure_upcharge(project, category, jurisdiction, measurement):
    return labor_charge(project, category, jurisdiction, "FINAL", measurement) - project["quoted_labor_cents"]


def credit_floor(project):
    return -rhu(Decimal(project["quoted_labor_cents"]) * CREDIT_CAP_PCT)


# =============================================================================
# 3. installer_scorecard
# =============================================================================
POINTS = {
    "ON_TIME_COMPLETION": (Decimal("2.00"), Decimal("6.00"), Decimal("1.00")),
    "LATE_COMPLETION": (Decimal("0.00"), Decimal("-8.00"), Decimal("-3.00")),
    "NO_SHOW": (Decimal("-4.00"), Decimal("-20.00"), Decimal("-10.00")),
    "PUNCH_MINOR": (Decimal("-3.00"), Decimal("0.00"), Decimal("-1.00")),
    "PUNCH_MAJOR": (Decimal("-8.00"), Decimal("-2.00"), Decimal("-4.00")),
    "PUNCH_SAFETY": (Decimal("-15.00"), Decimal("-3.00"), Decimal("-8.00")),
    "WARRANTY_UPHELD": (Decimal("-10.00"), Decimal("0.00"), Decimal("-6.00")),
    "CSAT_SURVEY": (Decimal("0.00"), Decimal("0.00"), None),
}


def event_deltas(event_type, csat_score):
    quality, timeliness, satisfaction = POINTS[event_type]
    if event_type == "CSAT_SURVEY":
        satisfaction = (Decimal(int(csat_score)) - Decimal("3")) * CSAT_POINT_STEP
    return rhu2(quality), rhu2(timeliness), rhu2(satisfaction)


def decay_weight(age_days):
    if age_days <= 90:
        return Decimal("1.00")
    if age_days <= 270:
        return Decimal("0.60")
    if age_days <= 540:
        return Decimal("0.30")
    return Decimal("0.10")


def _clamp_score(raw):
    return min(Decimal("100.00"), max(Decimal("0.00"), rhu2(raw)))


def _composite(quality, timeliness, satisfaction):
    return rhu2(quality * WEIGHT_QUALITY + timeliness * WEIGHT_TIMELINESS
                + satisfaction * WEIGHT_SATISFACTION)


def installer_events(installer_id):
    rows = [e for e in store.all_rows("scorecard_events") if e["installer_id"] == installer_id]
    return rows


def compute_scores(installer_id):
    """Both variants over the same ledger, computed without writing anything."""
    clock_now = store.now()
    window_open = clock_now - store.timedelta(days=ROLLING_WINDOW_DAYS)
    events = installer_events(installer_id)

    rolling = [e for e in events if e["occurred_at"] >= window_open]
    r_quality = BASE_SCORE
    r_timeliness = BASE_SCORE
    r_satisfaction = BASE_SCORE
    for event in rolling:
        r_quality += dec(event["quality_delta"])
        r_timeliness += dec(event["timeliness_delta"])
        r_satisfaction += dec(event["satisfaction_delta"])

    l_quality = BASE_SCORE
    l_timeliness = BASE_SCORE
    l_satisfaction = BASE_SCORE
    for event in events:
        age_days = store.whole_days_between(event["occurred_at"], clock_now)
        weight = decay_weight(age_days)
        l_quality += dec(event["quality_delta"]) * weight
        l_timeliness += dec(event["timeliness_delta"]) * weight
        l_satisfaction += dec(event["satisfaction_delta"]) * weight

    report = {
        "rolling_quality_score": _clamp_score(r_quality),
        "rolling_timeliness_score": _clamp_score(r_timeliness),
        "rolling_satisfaction_score": _clamp_score(r_satisfaction),
        "rolling_event_count": len(rolling),
        "rolling_no_show_count": len([e for e in rolling if e["event_type"] == "NO_SHOW"]),
        "rolling_safety_count": len([e for e in rolling if e["event_type"] == "PUNCH_SAFETY"]),
        "lifetime_quality_score": _clamp_score(l_quality),
        "lifetime_timeliness_score": _clamp_score(l_timeliness),
        "lifetime_satisfaction_score": _clamp_score(l_satisfaction),
        "lifetime_event_count": len(events),
    }
    report["rolling_composite_score"] = _composite(
        report["rolling_quality_score"], report["rolling_timeliness_score"],
        report["rolling_satisfaction_score"])
    report["lifetime_composite_score"] = _composite(
        report["lifetime_quality_score"], report["lifetime_timeliness_score"],
        report["lifetime_satisfaction_score"])
    report["removal_eligible"] = bool(
        (report["rolling_composite_score"] <= REMOVAL_COMPOSITE_MAX
         and report["rolling_event_count"] >= MIN_EVENTS_FOR_ACTION)
        or report["rolling_no_show_count"] >= REMOVAL_NO_SHOW_COUNT
        or report["rolling_safety_count"] >= REMOVAL_SAFETY_COUNT)
    return report


def rescore(installer):
    """Recompute both scorecard variants plus the derived counters onto the row."""
    report = compute_scores(installer["id"])
    installer["quality_score"] = report["rolling_quality_score"]
    installer["timeliness_score"] = report["rolling_timeliness_score"]
    installer["satisfaction_score"] = report["rolling_satisfaction_score"]
    installer["composite_score"] = report["rolling_composite_score"]
    installer["lifetime_composite_score"] = report["lifetime_composite_score"]
    installer["rolling_event_count"] = report["rolling_event_count"]
    installer["rolling_no_show_count"] = report["rolling_no_show_count"]
    installer["removal_eligible"] = report["removal_eligible"]
    return installer


def probation_transition(installer):
    """ACTIVE <-> PROBATION driven by the freshly recomputed rolling composite."""
    if installer["status"] == "ACTIVE":
        if (installer["composite_score"] <= PROBATION_COMPOSITE_MAX
                and installer["rolling_event_count"] >= MIN_EVENTS_FOR_ACTION):
            installer["status"] = "PROBATION"
            installer["probation_started_at"] = store.now()
    elif installer["status"] == "PROBATION":
        if installer["composite_score"] > PROBATION_COMPOSITE_MAX:
            installer["status"] = "ACTIVE"
            installer["probation_started_at"] = None


# =============================================================================
# 4. cancellation_settlement
# =============================================================================
FORFEIT_PCT = {
    "DRAFT": Decimal("0.00"),
    "MEASURE_PENDING": Decimal("0.00"),
    "MEASURED": FORFEIT_PCT_MEASURED,
    "CHANGE_PENDING": FORFEIT_PCT_MEASURED,
    "SCHEDULED": FORFEIT_PCT_SCHEDULED,
    "IN_PROGRESS": FORFEIT_PCT_IN_PROGRESS,
}


def project_delivery(project_id):
    """The project's material delivery: the most recently created row."""
    rows = [d for d in store.all_rows("material_deliveries") if d["project_id"] == project_id]
    if not rows:
        return None
    rows.sort(key=lambda d: (d["created_at"], d["_seq"]))
    return rows[-1]


def settlement(project, pre_fulfillment, delivery, pre_delivery_status, actor_role, customer):
    held = int(project["deposit_held_cents"])
    labor_forfeit_pct = FORFEIT_PCT.get(pre_fulfillment, Decimal("0.00"))
    labor_forfeit_cents = rhu(Decimal(held) * labor_forfeit_pct)

    if delivery is None or pre_delivery_status in ("PLANNED", "RETURNED"):
        restocking_fee_cents = 0
    elif pre_delivery_status in ("IN_TRANSIT", "DELAYED"):
        restocking_fee_cents = rhu(Decimal(delivery["material_cost_cents"]) * RESTOCK_PCT_IN_TRANSIT)
    elif pre_delivery_status == "DELIVERED":
        restocking_fee_cents = rhu(Decimal(delivery["material_cost_cents"]) * RESTOCK_PCT_DELIVERED)
    else:
        restocking_fee_cents = 0

    gross = labor_forfeit_cents + restocking_fee_cents

    # WAIVER LADDER — top to bottom, first match wins, no later tier consulted.
    if actor_role in ("ProgramAdmin", "ServiceManager"):
        tier = "RETAILER_FAULT"
        tier_retained = 0
    elif (store.now() - project["created_at"]).total_seconds() <= COOLING_OFF_HOURS * 3600:
        tier = "COOLING_OFF"
        tier_retained = 0
    elif (project["permit_status"] == "PENDING_APPLICATION"
          and project["permit_responsibility"] == "RETAILER"):
        tier = "PERMIT_BLOCKED"
        tier_retained = restocking_fee_cents
    elif customer is not None and int(customer["project_count"]) >= GOODWILL_PROJECT_COUNT:
        tier = "GOODWILL"
        tier_retained = rhu(Decimal(gross) * GOODWILL_PCT)
    else:
        tier = "NONE"
        tier_retained = gross

    retained = min(tier_retained, held)
    refund = held - retained

    if retained == 0:
        status = "REFUNDED"
    elif refund == 0:
        status = "FORFEITED"
    else:
        status = "PARTIALLY_REFUNDED"

    return {
        "deposit_held_cents": held,
        "labor_forfeit_pct": rhu2(labor_forfeit_pct),
        "labor_forfeit_cents": labor_forfeit_cents,
        "restocking_fee_cents": restocking_fee_cents,
        "gross_retained_cents": gross,
        "matched_waiver_tier": tier,
        "retained_cents": retained,
        "refund_cents": refund,
        "resulting_financial_status": status,
    }


# =============================================================================
# 5. permit_responsibility_determination
# =============================================================================
def determine_permit(project, category, jurisdiction):
    policy = category["permit_policy"]
    if policy == "NEVER":
        needed = False
    elif policy == "ALWAYS":
        needed = True
    else:
        needed = (category["trade_code"] in (jurisdiction["permit_required_trades"] or [])
                  and dec(project["effective_units"]) >= dec(jurisdiction["permit_unit_threshold"]))

    if not needed:
        return "NOT_REQUIRED", "NOT_REQUIRED"

    candidate = jurisdiction["permit_responsible_party"]
    if candidate == "INSTALLER":
        authorized = [
            c for c in store.all_rows("installer_credentials")
            if c["jurisdiction_id"] == project["jurisdiction_id"]
            and c["trade_code"] == category["trade_code"]
            and c["verification_status"] == "VERIFIED"
            and c["permit_pulling_authorized"] is True
        ]
        if not authorized:
            candidate = "RETAILER"
    return candidate, "PENDING_APPLICATION"


def apply_permit_determination(project, category, jurisdiction):
    responsibility, status = determine_permit(project, category, jurisdiction)
    project["permit_responsibility"] = responsibility
    if project.get("permit_status") in (None, "NOT_REQUIRED", "PENDING_APPLICATION"):
        project["permit_status"] = status


# =============================================================================
# 6. delivery_sync_slack
# =============================================================================
def delivery_slack_hours(window_start, promised_window_end):
    return int(math.floor((window_start - promised_window_end).total_seconds() / 3600.0))


def delay_days(actual_delivered_at, promised_window_end):
    seconds = (actual_delivered_at - promised_window_end).total_seconds()
    if seconds <= 0:
        return 0
    return int(math.ceil(seconds / 86400.0))


def lateness_excused(project_id):
    return any(int(d.get("delay_days") or 0) >= 1
               for d in store.all_rows("material_deliveries")
               if d["project_id"] == project_id)


# =============================================================================
# 7. installer_capacity_and_overlap
# =============================================================================
LIVE_ASSIGNMENT_STATUSES = ("HELD", "CONFIRMED", "IN_PROGRESS")
COMMITTED_STATUSES = ("HELD", "CONFIRMED", "IN_PROGRESS", "COMPLETED")


def duration_minutes(window_start, window_end):
    return int(math.floor((window_end - window_start).total_seconds() / 60.0))


def installer_assignments(installer_id):
    return [a for a in store.all_rows("installer_assignments") if a["installer_id"] == installer_id]


def window_conflict(installer_id, window_start, window_end):
    buffer_delta = store.timedelta(minutes=TRAVEL_BUFFER_MINUTES)
    for existing in installer_assignments(installer_id):
        if existing["status"] not in LIVE_ASSIGNMENT_STATUSES:
            continue
        if (window_start < existing["window_end"] + buffer_delta
                and existing["window_start"] < window_end + buffer_delta):
            return True
    return False


def recompute_committed_minutes(installer):
    total = 0
    for assignment in installer_assignments(installer["id"]):
        if assignment["status"] in COMMITTED_STATUSES:
            total += int(assignment["duration_minutes"])
    installer["committed_minutes"] = total
    return total


# =============================================================================
# 8. project_total_due
# =============================================================================
def accepted_upcharge_total(project_id):
    total = 0
    for order in store.all_rows("change_orders"):
        if (order["project_id"] == project_id and order["status"] == "ACCEPTED"
                and order["origin"] in ("CUSTOMER_REQUEST", "SITE_CONDITION")):
            total += int(order["upcharge_cents"])
    return total


def recompute_money(project):
    """change_order_upcharge_cents, total_due_cents and balance_due_cents."""
    project["change_order_upcharge_cents"] = accepted_upcharge_total(project["id"])
    if project["final_labor_cents"] is None:
        project["total_due_cents"] = 0
    else:
        project["total_due_cents"] = (int(project["final_labor_cents"])
                                      + int(project["change_order_upcharge_cents"])
                                      + int(project["permit_fee_cents_billed"]))
    if project["financial_status"] == "SETTLED":
        # PRD 3.6: once SETTLED the balance stays at zero and never reopens.
        project["balance_due_cents"] = 0
    else:
        project["balance_due_cents"] = max(
            0, int(project["total_due_cents"]) - int(project["deposit_applied_cents"]))
    return project


def deposit_waterfall(project):
    """Run once, when final_labor_cents is first written."""
    applied = min(int(project["deposit_held_cents"]), int(project["total_due_cents"]))
    project["deposit_applied_cents"] = int(project["deposit_applied_cents"]) + applied
    project["deposit_held_cents"] = int(project["deposit_held_cents"]) - applied
    surplus = int(project["deposit_held_cents"])
    project["deposit_refunded_cents"] = int(project["deposit_refunded_cents"]) + surplus
    project["deposit_held_cents"] = 0
    project["balance_due_cents"] = max(
        0, int(project["total_due_cents"]) - int(project["deposit_applied_cents"]))
    return project


def customer_project_count(customer_id):
    return len([p for p in store.all_rows("projects") if p["customer_id"] == customer_id])
