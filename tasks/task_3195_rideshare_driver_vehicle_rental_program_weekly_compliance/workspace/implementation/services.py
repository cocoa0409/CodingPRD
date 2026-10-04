"""Calculation rules, state machines and cross-cutting effects."""

from decimal import Decimal, ROUND_HALF_UP

import db
from errors import (E_DRIVER_NOT_ELIGIBLE, E_ENROLLMENT_NOT_ACTIVE,
                    E_MAINTENANCE_WINDOW_CONFLICT, E_MODEL_NOT_QUALIFIED, E_NOT_FOUND,
                    E_STALE_AGREEMENT_VERSION, E_STALE_VEHICLE_VERSION,
                    E_VEHICLE_NOT_AVAILABLE, E_WEEK_OVERLAP, ApiError, raise_error)

# --- Constants (PRD 3 and SCAFFOLD calculations) ------------------------------
MILEAGE_OVERAGE_RATE_CENTS_PER_MILE = 25
PLATFORM_CREDIT_CAP_CENTS = 600
PLATFORM_CREDIT_PER_ACTIVITY_POINT_CENTS = 10
PROGRAM_ACTIVITY_FLOOR = 50
TIER_3_CREDIT_MULTIPLIER_NUM = 3
TIER_3_CREDIT_MULTIPLIER_DEN = 2
TIER_3_MULTIPLIER_NUM = 5
TIER_3_MULTIPLIER_DEN = 4
BONUS_REQUIRES_SCORE_AT_OR_BELOW = 40
BONUS_REQUIRES_ACTIVITY_AT_OR_ABOVE = 90
BONUS_POINTS = 15
APPROVE_SCORE_AT_OR_ABOVE = 60
APPROVE_ACTIVITY_AT_OR_ABOVE = 70
DAMAGE_ALLOWANCE_CENTS_PER_MILE = 2
DRIVER_DAMAGE_CAP_CENTS = 50000
EQUITY_SHARE_NUM = 1
EQUITY_SHARE_DEN = 10
EQUITY_CENTS_DIVISOR = 100

RIDE_CLASSES = {"STANDARD", "XL", "LUXURY"}
DELIVERY_CLASSES = {"STANDARD", "XL", "DELIVERY_VAN"}
VEHICLE_CLASSES = ("STANDARD", "XL", "LUXURY", "DELIVERY_VAN")
ACTIVITY_CLASSES = {"RIDE", "DELIVERY"}

OCCUPANCY_HOLDING = {"ACTIVE", "RENEWAL_DUE", "DELINQUENT", "RECOVERY_PENDING",
                     "PURCHASE_PENDING"}
WEEK_TERMINAL = {"PAID", "RECOVERED", "WAIVED"}
DELINQUENT_BLOCKING = {"DUE", "GRACE", "DELINQUENT"}


def round_half_up(value):
    return int(Decimal(value).quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def all_of(collection, predicate=lambda row: True):
    return [row for row in collection.values() if predicate(row)]


def by_created(rows):
    if isinstance(rows, dict):
        rows = rows.values()
    return sorted(rows, key=lambda row: row["created_at"])


def paginate(rows):
    """PRD 2.3: limit defaults to 10 with a floor of 1 and a ceiling of 100."""
    from flask import request
    from errors import E_INVALID_REQUEST
    try:
        limit = int(request.args.get("limit", 10))
    except (TypeError, ValueError):
        raise_error(E_INVALID_REQUEST, "limit must be an integer.")
    try:
        offset = int(request.args.get("offset", 0))
    except (TypeError, ValueError):
        raise_error(E_INVALID_REQUEST, "offset must be an integer.")
    limit = max(1, min(100, limit))
    offset = max(0, offset)
    total = len(rows)
    return rows[offset:offset + limit], limit, offset, total


# --- Lookups ------------------------------------------------------------------

def get_driver(driver_id):
    row = db.DRIVERS.get(driver_id)
    if row is None:
        raise_error(E_NOT_FOUND, "No driver exists with id %s." % driver_id)
    return row


def get_enrollment(enrollment_id):
    row = db.ENROLLMENTS.get(enrollment_id)
    if row is None:
        raise_error(E_NOT_FOUND, "No enrolment exists with id %s." % enrollment_id)
    return row


def get_vehicle(vehicle_id):
    row = db.VEHICLES.get(vehicle_id)
    if row is None:
        raise_error(E_NOT_FOUND, "No program vehicle exists with id %s." % vehicle_id)
    return row


def get_agreement(agreement_id):
    row = db.AGREEMENTS.get(agreement_id)
    if row is None:
        raise_error(E_NOT_FOUND, "No rental agreement exists with id %s." % agreement_id)
    return row


def get_week(week_id):
    row = db.WEEKS.get(week_id)
    if row is None:
        raise_error(E_NOT_FOUND, "No rental week exists with id %s." % week_id)
    return row


def get_event(event_id):
    row = db.MAINTENANCE_EVENTS.get(event_id)
    if row is None:
        raise_error(E_NOT_FOUND, "No maintenance event exists with id %s." % event_id)
    return row


def get_option(option_id):
    row = db.PURCHASE_OPTIONS.get(option_id)
    if row is None:
        raise_error(E_NOT_FOUND, "No purchase option exists with id %s." % option_id)
    return row


def get_check(check_id):
    row = db.PLATFORM_CHECKS.get(check_id)
    if row is None:
        raise_error(E_NOT_FOUND, "No platform check exists with id %s." % check_id)
    return row


def get_fact(fact_id):
    row = db.FLEET_FACTS.get(fact_id)
    if row is None:
        raise_error(E_NOT_FOUND, "No fleet fact exists with id %s." % fact_id)
    return row


def weeks_of(agreement_id):
    return all_of(db.WEEKS, lambda w: w["agreement_id"] == agreement_id)


def open_week_of(agreement_id):
    for week in by_created(weeks_of(agreement_id)):
        if week["week_status"] == "OPEN":
            return week
    return None


def refresh_agreement_status(agreement):
    """The lifecycle follows the agreement's delinquent count only: a week going
    delinquent makes it DELINQUENT, and a count that falls back to zero returns
    it to ACTIVE (PRD 3.4, 3.8). An agreement holding an unsettled period keeps
    the RENEWAL_DUE it took when that period was opened."""
    if agreement["agreement_status"] not in ("ACTIVE", "RENEWAL_DUE", "DELINQUENT"):
        return
    weeks = weeks_of(agreement["id"])
    if any(w["week_status"] == "DELINQUENT" for w in weeks):
        target = "DELINQUENT"
    elif agreement["agreement_status"] == "DELINQUENT":
        target = "ACTIVE"
    else:
        return
    if agreement["agreement_status"] != target:
        agreement["agreement_status"] = target
        db.touch(agreement)


def equity_credit_for(agreement):
    """The purchase equity credit read off the agreement's settled weeks."""
    weeks = weeks_of(agreement["id"])
    sum_paid = sum(w["amount_due_cents"] for w in weeks if w["week_status"] == "PAID")
    sum_waived = sum(w["amount_due_cents"] for w in weeks if w["week_status"] == "WAIVED")
    untaxed_subtotal = sum_paid - sum_waived
    gross = untaxed_subtotal * EQUITY_SHARE_NUM // EQUITY_SHARE_DEN
    credit = round_half_up(gross * 100 / EQUITY_CENTS_DIVISOR) * (EQUITY_CENTS_DIVISOR // 100)
    return max(0, credit)


OCCUPANCY_HOLDING_STATES = ("ACTIVE", "RENEWAL_DUE", "DELINQUENT",
                             "RECOVERY_PENDING", "PURCHASE_PENDING")


def outstanding_delinquent_weeks(agreement_id):
    """Weeks whose delinquency still bears on the posture. A recovered agreement
    stops holding occupancy, and the weeks closed by its recovery set are no
    longer outstanding, so the reading is taken from the live agreement set
    (PRD 3.8: the posture is a live reading, not a one-way ratchet)."""
    agreement = db.AGREEMENTS.get(agreement_id)
    if agreement is not None and agreement["agreement_status"] not in OCCUPANCY_HOLDING_STATES:
        return 0
    return len([w for w in weeks_of(agreement_id) if w["week_status"] == "DELINQUENT"])


# --- Eligibility scoring ------------------------------------------------------

def eligibility_score(driver):
    score = 100
    pts = driver["driving_record_points"]
    if pts <= 3:
        # 5 points per point on the record
        score -= pts * 5
    elif pts <= 6:
        # a flat 15 for the first band plus 10 for each point above 3
        score -= 3 * 5
        score -= (pts - 3) * 10
    else:
        # a flat 15, a flat 30 for the second band, plus 20 for each point above 6
        score -= 3 * 5
        score -= 3 * 10
        score -= (pts - 6) * 20
    if score < 0:
        score = 0
    activity = driver["platform_activity_score"]
    if score <= BONUS_REQUIRES_SCORE_AT_OR_BELOW and activity >= BONUS_REQUIRES_ACTIVITY_AT_OR_ABOVE:
        score += BONUS_POINTS
    if score > 100:
        score = 100
    return score


def eligibility_decision(score, activity):
    """The decision is applied after the score is final (PRD 3.1)."""
    if score < APPROVE_SCORE_AT_OR_ABOVE:
        return "DENIED"
    if activity < APPROVE_ACTIVITY_AT_OR_ABOVE:
        return "DEFERRED"
    return "APPROVED"


def platform_credit_for(driver, tier):
    points = driver["platform_activity_score"]
    if points < PROGRAM_ACTIVITY_FLOOR:
        credit = 0
    elif points < 75:
        credit = (points - 50 + 1) * PLATFORM_CREDIT_PER_ACTIVITY_POINT_CENTS
    else:
        credit = (75 - 50) * PLATFORM_CREDIT_PER_ACTIVITY_POINT_CENTS
        credit += ((points - 75 + 1) * PLATFORM_CREDIT_PER_ACTIVITY_POINT_CENTS
                   * TIER_3_CREDIT_MULTIPLIER_NUM) // TIER_3_CREDIT_MULTIPLIER_DEN
    if tier == "TIER_3":
        credit = credit * TIER_3_MULTIPLIER_NUM // TIER_3_MULTIPLIER_DEN
    if credit > PLATFORM_CREDIT_CAP_CENTS:
        credit = PLATFORM_CREDIT_CAP_CENTS
    return credit


def credit_for_agreement(agreement):
    driver = db.DRIVERS.get(agreement["driver_id"])
    enrollment = db.ENROLLMENTS.get(agreement["enrollment_id"])
    if driver is None:
        return 0
    tier = enrollment["program_tier"] if enrollment else None
    return platform_credit_for(driver, tier)


def refresh_driver_posture(driver):
    """Re-derive Driver.eligibility_status from the driver's live situation."""
    enrollments = all_of(db.ENROLLMENTS, lambda e: e["driver_id"] == driver["id"])
    if any(e["enrollment_status"] == "SUSPENDED" for e in enrollments):
        driver["eligibility_status"] = "SUSPENDED"
    elif any(e["enrollment_status"] == "ACTIVE" for e in enrollments):
        driver["eligibility_status"] = "ELIGIBLE"
    elif enrollments and all(e["enrollment_status"] == "WITHDRAWN" for e in enrollments):
        driver["eligibility_status"] = "INELIGIBLE"
    elif any(e["enrollment_status"] == "REJECTED" for e in enrollments):
        driver["eligibility_status"] = "INELIGIBLE"
    else:
        driver["eligibility_status"] = "PENDING"


def evaluate_enrollment(enrollment):
    driver = db.DRIVERS[enrollment["driver_id"]]
    enrollment["activity_snapshot"] = driver["platform_activity_score"]
    enrollment["record_snapshot"] = driver["driving_record_points"]
    score = eligibility_score(driver)
    enrollment["eligibility_score"] = score
    enrollment["eligibility_decision"] = eligibility_decision(
        score, driver["platform_activity_score"])


# --- Weekly renewable charge --------------------------------------------------

def compute_weekly_charge(week, agreement, final):
    """weekly_renewal_charge; both variants share the pinned evaluation order."""
    week["base_charge_cents"] = agreement["weekly_rate_cents"]
    week["insurance_charge_cents"] = agreement["insurance_premium_cents"]
    if final and not agreement["unlimited_mileage"]:
        cap = agreement["mileage_cap_miles"] or 0
        over = max(0, week["miles_driven"] - cap)
        week["mileage_overage_cents"] = round_half_up(
            over * MILEAGE_OVERAGE_RATE_CENTS_PER_MILE)
    else:
        week["mileage_overage_cents"] = 0
    if not final:
        week["damage_charge_cents"] = 0
        week["platform_credit_cents"] = credit_for_agreement(agreement)
    week["amount_due_cents"] = (week["base_charge_cents"] + week["insurance_charge_cents"]
                                + week["mileage_overage_cents"] + week["damage_charge_cents"]
                                - week["platform_credit_cents"])
    return week


def refresh_open_week_charge(agreement):
    """Recompute the provisional variant for the agreement's open week, if any."""
    week = open_week_of(agreement["id"])
    if week is None:
        return None
    compute_weekly_charge(week, agreement, final=False)
    db.touch(week)
    return week


def damage_settlement_split(agreement):
    """Apportion completed DAMAGE_REPAIR events onto the agreement's open week."""
    week = open_week_of(agreement["id"])
    if week is None:
        return
    total = 0
    for event in all_of(db.MAINTENANCE_EVENTS,
                        lambda e: e["agreement_id"] == agreement["id"]):
        if event["event_type"] != "DAMAGE_REPAIR" or event["event_status"] != "COMPLETED":
            continue
        if event.get("_open_week_id") != week["id"]:
            continue
        remaining = event["damage_liability_cents"]
        allowance_applied = min(
            remaining,
            agreement["maintenance_allowance_miles"] * DAMAGE_ALLOWANCE_CENTS_PER_MILE)
        remaining -= allowance_applied
        total += min(remaining, DRIVER_DAMAGE_CAP_CENTS)
    week["damage_charge_cents"] = total


# --- Equity credit and escrow schedule ---------------------------------------

def recompute_equity_credit(agreement):
    credit = equity_credit_for(agreement)
    for option in all_of(db.PURCHASE_OPTIONS, lambda o: o["agreement_id"] == agreement["id"]):
        option["equity_credit_cents"] = credit
        recompute_escrow_schedule(option)
        db.touch(option)


def recompute_escrow_schedule(option):
    remaining = option["purchase_price_cents"] - option["equity_credit_cents"]
    option["escrow_required_cents"] = round_half_up(remaining / option["escrow_weeks_required"])


# --- Compliance posture -------------------------------------------------------

def apply_posture(agreement):
    """The posture is an absolute reading of the delinquent count (PRD 3.8):
    a count of 0 yields OPEN, exactly 1 yields RESTRICTED, 2 or more FROZEN."""
    count = outstanding_delinquent_weeks(agreement["id"])
    if count == 0:
        target = "OPEN"
    elif count == 1:
        target = "RESTRICTED"
    else:
        target = "FROZEN"

    current = agreement["compliance_posture"]
    if current == target:
        return
    was_frozen = current == "FROZEN"
    agreement["compliance_posture"] = target
    db.touch(agreement)
    if target == "FROZEN":
        on_posture_frozen(agreement)
    if target == "OPEN":
        # the freeze's co-effects are unwound once the count reaches zero:
        # the unit returns to the road and the driver's standing is restored
        on_freeze_lifted(agreement)
    elif was_frozen:
        # a count still outstanding is a partial cure: the unit comes back out
        # of the recovery pool and the driver's standing is restored, though
        # the posture stays RESTRICTED until the last week is settled
        on_freeze_lifted(agreement)


def on_posture_frozen(agreement):
    """The co-effects of a freeze: driver suspension and unit recovery."""
    driver = db.DRIVERS.get(agreement["driver_id"])
    if driver is not None and driver["eligibility_status"] == "ELIGIBLE":
        driver["eligibility_status"] = "SUSPENDED"
        db.touch(driver)
    enrollment = db.ENROLLMENTS.get(agreement["enrollment_id"])
    if enrollment is not None and enrollment["enrollment_status"] == "ACTIVE":
        enrollment["enrollment_status"] = "SUSPENDED"
        db.touch(enrollment)
    vehicle = db.VEHICLES.get(agreement["vehicle_id"])
    if vehicle is not None and vehicle["vehicle_status"] == "ASSIGNED":
        vehicle["vehicle_status"] = "RECOVERY"
        # the recovery interval opens at the instant the unit enters the pool
        # and runs until 24 hours after it last returns to AVAILABLE (PRD 3.8)
        vehicle["recovery_entered_at"] = db.now()
        vehicle["returned_to_available_at"] = None
        db.touch(vehicle)


def restore_driver_standing(agreement):
    """Lift a freeze-induced suspension once no agreement of the driver is
    frozen any more (PRD 3.8)."""
    others = [a for a in all_of(db.AGREEMENTS,
                                lambda a: a["driver_id"] == agreement["driver_id"])
              if a["compliance_posture"] == "FROZEN"]
    if others:
        return
    driver = db.DRIVERS.get(agreement["driver_id"])
    if driver is not None and driver["eligibility_status"] == "SUSPENDED":
        driver["eligibility_status"] = "ELIGIBLE"
        db.touch(driver)
    for enrollment in all_of(db.ENROLLMENTS, lambda e: e["driver_id"] == agreement["driver_id"]):
        if enrollment["enrollment_status"] == "SUSPENDED":
            enrollment["enrollment_status"] = "ACTIVE"
            db.touch(enrollment)


def on_freeze_lifted(agreement):
    """The inverse of a freeze: the unit comes back out of the recovery pool and
    the driver's standing is restored."""
    vehicle = db.VEHICLES.get(agreement["vehicle_id"])
    if vehicle is not None and vehicle["vehicle_status"] == "RECOVERY":
        vehicle["vehicle_status"] = "ASSIGNED"
        vehicle["assigned_driver_id"] = agreement["driver_id"]
        db.touch(vehicle)
    restore_driver_standing(agreement)


def recompute_posture(agreement, was_frozen=None):
    apply_posture(agreement)


# --- Time-gated transitions ---------------------------------------------------

def advance_time_gates():
    """Apply every deadline the logical clock has reached (PRD 2.9)."""
    for week in by_created(db.WEEKS.values()):
        if week["week_status"] != "DUE":
            continue
        if week["payment_status"] == "SETTLED":
            continue
        deadline = db.parse_iso(week["payment_deadline"])
        if deadline is not None and db.now() >= deadline:
            week["week_status"] = "GRACE"
            db.touch(week)


# --- Vehicle / interval helpers ----------------------------------------------

def vehicle_ride_class(vehicle):
    return vehicle["vehicle_class"] in RIDE_CLASSES


def vehicle_delivery_class(vehicle):
    return vehicle["vehicle_class"] in DELIVERY_CLASSES


def interval_collides(vehicle_id, start, end, ignore_agreement_id=None):
    # An agreement that has reached a terminal state no longer occupies the
    # unit, so its historical interval does not block a re-let.
    terminal = {"COMPLETED", "RECOVERED", "PURCHASED"}
    for agreement in all_of(db.AGREEMENTS,
                            lambda a: a["vehicle_id"] == vehicle_id
                            and a["agreement_status"] not in terminal):
        if ignore_agreement_id is not None and agreement["id"] == ignore_agreement_id:
            continue
        existing_start = db.parse_iso(agreement["period_start"])
        existing_end = db.parse_iso(agreement["period_end"])
        if existing_start is None or existing_end is None:
            continue
        if start < existing_end and existing_start < end:
            return True
    return False


def driver_holds_vehicle(driver_id):
    # a loaner substitutes for the unit under repair and so carries the same
    # driver; the holding that blocks a second assignment is any assigned unit
    # that is not itself a loaner (PRD 2.8)
    loaner_ids = {e["loaner_vehicle_id"] for e in db.MAINTENANCE_EVENTS.values()
                  if e["event_status"] == "LOANER_ISSUED" and e["loaner_vehicle_id"]}
    return any(v["vehicle_status"] == "ASSIGNED" and v["assigned_driver_id"] == driver_id
               and v["id"] not in loaner_ids for v in db.VEHICLES.values())


def ensure_driver_licence(driver):
    if driver["license_class"] not in ("FOR_HIRE", "COMMERCIAL"):
        raise_error(E_DRIVER_NOT_ELIGIBLE,
                    "The driver's licence class does not permit a program unit.")


def ensure_driver_eligible(driver):
    if driver["eligibility_status"] != "ELIGIBLE":
        raise_error(E_DRIVER_NOT_ELIGIBLE, "The driver is not in ELIGIBLE standing.")


def ensure_enrollment_active(agreement):
    enrollment = db.ENROLLMENTS.get(agreement["enrollment_id"])
    if enrollment is None or enrollment["enrollment_status"] != "ACTIVE":
        raise_error(E_ENROLLMENT_NOT_ACTIVE, "The authorising enrolment is not ACTIVE.")


def ensure_vehicle_available(vehicle):
    if vehicle["vehicle_status"] != "AVAILABLE":
        raise_error(E_VEHICLE_NOT_AVAILABLE, "The program vehicle is not AVAILABLE.")


def ensure_model_qualified(vehicle, activity):
    if activity == "RIDE" and not vehicle_ride_class(vehicle):
        raise_error(E_MODEL_NOT_QUALIFIED,
                    "The unit's class is not permitted for ride activity.")
    if activity == "DELIVERY" and not vehicle_delivery_class(vehicle):
        raise_error(E_MODEL_NOT_QUALIFIED,
                    "The unit's class is not permitted for delivery activity.")


def ensure_activity_permitted(vehicle):
    """Guard 17 for the assignment path: a unit that qualifies for neither
    activity may not be assigned to an agreement at all (PRD 2.7)."""
    if not vehicle_ride_class(vehicle) and not vehicle_delivery_class(vehicle):
        raise_error(E_MODEL_NOT_QUALIFIED,
                    "The unit's class is permitted for neither platform activity.")


def ensure_no_week_overlap(agreement, extra_week_number=None):
    numbers = [w["week_number"] for w in weeks_of(agreement["id"])]
    if extra_week_number is not None:
        numbers.append(extra_week_number)
    if len(numbers) != len(set(numbers)):
        raise_error(E_WEEK_OVERLAP, "Two weekly periods would share one week number.")


def check_agreement_version(agreement, supplied):
    if supplied is None:
        raise_error(E_STALE_AGREEMENT_VERSION, "expected_agreement_version is required.")
    if int(supplied) != agreement["version"]:
        raise_error(E_STALE_AGREEMENT_VERSION,
                    "expected_agreement_version does not match the agreement's version.")


def check_vehicle_version(vehicle, supplied):
    if supplied is None:
        raise_error(E_STALE_VEHICLE_VERSION, "expected_vehicle_version is required.")
    if int(supplied) != vehicle["version"]:
        raise_error(E_STALE_VEHICLE_VERSION,
                    "expected_vehicle_version does not match the vehicle's version.")


def check_recovery_quiet_period(vehicle):
    """Guard 21: the unit must be outside its recovery interval."""
    entered = db.parse_iso(vehicle.get("recovery_entered_at"))
    returned = db.parse_iso(vehicle.get("returned_to_available_at"))
    if entered is None:
        return
    if returned is None or db.now() < returned + db.hours(24):
        raise_error(E_MAINTENANCE_WINDOW_CONFLICT,
                    "The unit's recovery interval is still open.")


# --- Fleet sizing -------------------------------------------------------------

def compute_fleet_fact(fact):
    region = fact["region_code"]
    assigned_units = len(all_of(db.VEHICLES, lambda v: v["region_code"] == region
                                and v["vehicle_status"] == "ASSIGNED"))
    fact["active_agreements_count"] = assigned_units
    fact["available_fleet_count"] = len(
        all_of(db.VEHICLES, lambda v: v["region_code"] == region
               and v["vehicle_status"] in ("AVAILABLE", "RECOVERY")))
    denominator = assigned_units + fact["available_fleet_count"]
    fact["utilization_bps"] = 0 if denominator == 0 else (assigned_units * 10000) // denominator
    fact["sizing_deficit_units"] = fact["demand_units"] - denominator
    if fact["sizing_deficit_units"] > 0:
        fact["fleet_fact_status"] = "UNDER_SUPPLIED"
    elif fact["sizing_deficit_units"] < 0:
        fact["fleet_fact_status"] = "OVER_SUPPLIED"
    else:
        fact["fleet_fact_status"] = "BALANCED"


# --- Serialisation ------------------------------------------------------------

def driver_out(driver):
    return {
        "id": driver["id"],
        "created_at": db.fmt(driver["created_at"]),
        "updated_at": db.fmt(driver["updated_at"]),
        "version": driver["version"],
        "full_name": driver["full_name"],
        "email": driver["email"],
        "platform_driver_id": driver["platform_driver_id"],
        "platform_activity_score": driver["platform_activity_score"],
        "driving_record_points": driver["driving_record_points"],
        "license_class": driver["license_class"],
        "program_driver_tier": driver["program_driver_tier"],
        "eligibility_status": driver["eligibility_status"],
    }


def enrollment_out(enrollment):
    return {
        "id": enrollment["id"],
        "created_at": db.fmt(enrollment["created_at"]),
        "updated_at": db.fmt(enrollment["updated_at"]),
        "version": enrollment["version"],
        "driver_id": enrollment["driver_id"],
        "program_tier": enrollment["program_tier"],
        "activity_snapshot": enrollment["activity_snapshot"],
        "record_snapshot": enrollment["record_snapshot"],
        "eligibility_score": enrollment["eligibility_score"],
        "eligibility_decision": enrollment["eligibility_decision"],
        "enrollment_status": enrollment["enrollment_status"],
        "verified_at": db.fmt(enrollment["verified_at"]),
    }


def vehicle_out(vehicle):
    return {
        "id": vehicle["id"],
        "created_at": db.fmt(vehicle["created_at"]),
        "updated_at": db.fmt(vehicle["updated_at"]),
        "version": vehicle["version"],
        "vin": vehicle["vin"],
        "model_name": vehicle["model_name"],
        "model_year": vehicle["model_year"],
        "vehicle_class": vehicle["vehicle_class"],
        "qualifies_ride": vehicle_ride_class(vehicle),
        "qualifies_delivery": vehicle_delivery_class(vehicle),
        "odometer_miles": vehicle["odometer_miles"],
        "baseline_odometer_miles": vehicle["baseline_odometer_miles"],
        "vehicle_status": vehicle["vehicle_status"],
        "assigned_driver_id": vehicle["assigned_driver_id"],
        "region_code": vehicle["region_code"],
    }


def agreement_out(agreement):
    return {
        "id": agreement["id"],
        "created_at": db.fmt(agreement["created_at"]),
        "updated_at": db.fmt(agreement["updated_at"]),
        "version": agreement["version"],
        "enrollment_id": agreement["enrollment_id"],
        "driver_id": agreement["driver_id"],
        "vehicle_id": agreement["vehicle_id"],
        "weekly_rate_cents": agreement["weekly_rate_cents"],
        "insurance_premium_cents": agreement["insurance_premium_cents"],
        "unlimited_mileage": agreement["unlimited_mileage"],
        "mileage_cap_miles": agreement["mileage_cap_miles"],
        "maintenance_allowance_miles": agreement["maintenance_allowance_miles"],
        "compliance_posture": agreement["compliance_posture"],
        "agreement_status": agreement["agreement_status"],
        "current_week_number": agreement["current_week_number"],
        "total_billed_cents": agreement["total_billed_cents"],
        "total_waived_cents": agreement["total_waived_cents"],
        "period_start": db.fmt(agreement["period_start"]),
        "period_end": db.fmt(agreement["period_end"]),
    }


def week_out(week):
    return {
        "id": week["id"],
        "created_at": db.fmt(week["created_at"]),
        "updated_at": db.fmt(week["updated_at"]),
        "version": week["version"],
        "agreement_id": week["agreement_id"],
        "vehicle_id": week["vehicle_id"],
        "week_number": week["week_number"],
        "period_start": db.fmt(week["period_start"]),
        "period_end": db.fmt(week["period_end"]),
        "miles_driven": week["miles_driven"],
        "base_charge_cents": week["base_charge_cents"],
        "insurance_charge_cents": week["insurance_charge_cents"],
        "mileage_overage_cents": week["mileage_overage_cents"],
        "damage_charge_cents": week["damage_charge_cents"],
        "platform_credit_cents": week["platform_credit_cents"],
        "amount_due_cents": week["amount_due_cents"],
        "week_status": week["week_status"],
        "payment_status": week["payment_status"],
        "payment_deadline": db.fmt(week["payment_deadline"]),
        "grace_deadline": db.fmt(week["grace_deadline"]),
    }


def event_out(event):
    return {
        "id": event["id"],
        "created_at": db.fmt(event["created_at"]),
        "updated_at": db.fmt(event["updated_at"]),
        "version": event["version"],
        "agreement_id": event["agreement_id"],
        "vehicle_id": event["vehicle_id"],
        "event_type": event["event_type"],
        "odometer_at_service": event["odometer_at_service"],
        "downtime_hours": event["downtime_hours"],
        "loaner_vehicle_id": event["loaner_vehicle_id"],
        "loaner_deadline": db.fmt(event["loaner_deadline"]),
        "event_status": event["event_status"],
        "damage_liability_cents": event["damage_liability_cents"],
        "maintenance_allowance_applied_miles": event["maintenance_allowance_applied_miles"],
        "earnings_interruption_hours": event["earnings_interruption_hours"],
    }


def payment_out(payment):
    return {
        "id": payment["id"],
        "created_at": db.fmt(payment["created_at"]),
        "updated_at": db.fmt(payment["updated_at"]),
        "version": payment["version"],
        "agreement_id": payment["agreement_id"],
        "week_id": payment["week_id"],
        "amount_cents": payment["amount_cents"],
        "coverage_cents": payment["coverage_cents"],
        "platform_credit_cents": payment["platform_credit_cents"],
        "payment_outcome": payment["payment_outcome"],
        "collected_at": db.fmt(payment["collected_at"]),
    }


def option_out(option):
    return {
        "id": option["id"],
        "created_at": db.fmt(option["created_at"]),
        "updated_at": db.fmt(option["updated_at"]),
        "version": option["version"],
        "agreement_id": option["agreement_id"],
        "driver_id": option["driver_id"],
        "option_status": option["option_status"],
        "purchase_price_cents": option["purchase_price_cents"],
        "equity_credit_cents": option["equity_credit_cents"],
        "escrow_required_cents": option["escrow_required_cents"],
        "escrow_balance_cents": option["escrow_balance_cents"],
        "escrow_weeks_required": option["escrow_weeks_required"],
        "escrow_weeks_funded": option["escrow_weeks_funded"],
        "elected_at": db.fmt(option["elected_at"]),
    }


def check_out(check):
    return {
        "id": check["id"],
        "created_at": db.fmt(check["created_at"]),
        "updated_at": db.fmt(check["updated_at"]),
        "version": check["version"],
        "agreement_id": check["agreement_id"],
        "vehicle_id": check["vehicle_id"],
        "integration_result": check["integration_result"],
        "ride_qualified": check["ride_qualified"],
        "delivery_qualified": check["delivery_qualified"],
        "model_restriction_hit": check["model_restriction_hit"],
        "checked_at": db.fmt(check["checked_at"]),
    }


def fact_out(fact):
    return {
        "id": fact["id"],
        "created_at": db.fmt(fact["created_at"]),
        "updated_at": db.fmt(fact["updated_at"]),
        "version": fact["version"],
        "region_code": fact["region_code"],
        "demand_units": fact["demand_units"],
        "active_agreements_count": fact["active_agreements_count"],
        "available_fleet_count": fact["available_fleet_count"],
        "utilization_bps": fact["utilization_bps"],
        "sizing_deficit_units": fact["sizing_deficit_units"],
        "fleet_fact_status": fact["fleet_fact_status"],
    }