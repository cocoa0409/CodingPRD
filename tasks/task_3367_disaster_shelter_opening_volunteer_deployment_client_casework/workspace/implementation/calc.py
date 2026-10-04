"""Derived-field and calculation rules (scaffold Table 3 / PRD section 3).

Every derived value is recomputed from current child data; recomputing a value
that changes the stored field is itself a mutation (updated_at + version).
"""

import math
from datetime import timedelta
from decimal import Decimal

import core
from core import (apply, clock, find, format_instant, now_iso, parse_instant,
                  round_half_up, rows, touch)

# --- pinned constants ------------------------------------------------------
OVERHEAD_RATE_BPS = 750
MIN_OVERHEAD_CENTS = 2500
SUPPLY_SURCHARGE_BPS = 625
PER_PERSON_CENTS = 30000
HOUSEHOLD_CAP_CENTS = 120000
EXPEDITED_FLAT_CENTS = 20000
EXPEDITED_MULTIPLIER_BPS = 5000
EXPEDITED_CAP_CENTS = 150000
MIN_ASSISTANCE_CENTS = 5000
CLIENTS_PER_VOLUNTEER = 20
MIN_REQUIRED_VOLUNTEERS = 1
RESTRICTED_THRESHOLD = 0.60
BED_TURNOVER_BUFFER_MINUTES = 120
STANDARD_WINDOW_DAYS = 90
RESTRICTED_WINDOW_DAYS = 45
CLOSURE_HOLD_DAYS = 14
CREDENTIAL_VALIDITY_DAYS = 30
NO_SHOW_GRACE_MINUTES = 240
CHECKIN_LEAD_MINUTES = 60
INSPECTION_VALIDITY_DAYS = 365
TRAVEL_CROSS_REGION_MILES = 400
TRAVEL_SAME_REGION_MILES = 120
AIR_BASE_CENTS = 45000
AIR_DAY_SURCHARGE_CENTS = 2500
AIR_SURCHARGE_FREE_DAYS = 14
GROUND_RATE_CENTS_PER_MILE = 55
GROUND_LODGING_PER_DAY_CENTS = 12000
GROUND_LODGING_FREE_DAYS = 7
BASE_SCORE = 100
RECENCY_WINDOW_DAYS = 30
RECENCY_MAX_BONUS = 30
SCORE_CROSS_REGION_MILES = 400
SCORE_SAME_REGION_MILES = 0
MILES_PER_PENALTY_UNIT = 50
DISTANCE_MAX_PENALTY = 25
ROTATION_PENALTY_PER_DAY = 2
ROTATION_MAX_PENALTY = 40
ROLE_MATCH_BONUS = 20
WINDOW_DAYS = 42
BASELINE_TARGET_UNITS = 600
STRAINED_THRESHOLD = 0.80
CRITICAL_THRESHOLD = 0.50
DEFERRAL_LOSS_BPS = 700

AIR_LEAD_DAYS = 1
GROUND_LEAD_DAYS = 2
SELF_LEAD_DAYS = 0

TERMINAL_DEPLOYMENT = ("ROTATION_ENDED", "RECALLED", "CANCELLED")
TERMINAL_REGISTRATION = ("CHECKED_OUT", "TRANSFERRED", "REUNIFIED")


def ceil_div(numerator, denominator):
    return -(-int(numerator) // int(denominator))


def lead_days(travel_mode):
    if travel_mode == "AIR":
        return AIR_LEAD_DAYS
    if travel_mode == "GROUND":
        return GROUND_LEAD_DAYS
    return SELF_LEAD_DAYS


# --------------------------------------------------------------------------
# Region aggregates
# --------------------------------------------------------------------------


def region_volunteer_counts(region):
    volunteers = [v for v in rows("volunteers") if v["home_region_id"] == region["id"]]
    available = sum(1 for v in volunteers
                    if v["credential_status"] == "ACTIVE"
                    and v["deployment_availability"] == "AVAILABLE")
    deployed = sum(1 for v in volunteers
                   if v["deployment_availability"] == "DEPLOYED")
    return available, deployed


def blood_continuity(region, mode="TRAILING"):
    drives = [d for d in rows("blood_drives") if d["region_id"] == region["id"]]
    denominator = BASELINE_TARGET_UNITS + sum(
        d["target_units"] for d in drives if d["status"] in ("PLANNED", "ACTIVE"))
    window_start = clock.now - timedelta(days=WINDOW_DAYS)
    numerator = 0
    for drive in drives:
        if drive["status"] != "COMPLETED":
            continue
        ended = parse_instant(drive["scheduled_end_at"])
        if ended is not None and window_start <= ended <= clock.now:
            numerator += drive["usable_units"]
    if mode == "FORWARD_LOOKING":
        numerator += sum(d["target_units"] for d in drives if d["status"] == "PLANNED")
    if denominator <= 0:
        index = 0.0
    else:
        index = float(round_half_up(Decimal(numerator) / Decimal(denominator), 4))
    if index < CRITICAL_THRESHOLD:
        status = "CRITICAL"
    elif index < STRAINED_THRESHOLD:
        status = "STRAINED"
    else:
        status = "NORMAL"
    return index, status


def refresh_region(region, mode="TRAILING"):
    available, deployed = region_volunteer_counts(region)
    index, status = blood_continuity(region, mode)
    apply(region, {
        "available_volunteer_count": available,
        "deployed_volunteer_count": deployed,
        "blood_continuity_index": index,
        "blood_continuity_status": status,
    })
    return region


# --------------------------------------------------------------------------
# Shelter operation aggregates
# --------------------------------------------------------------------------


def shelter_registrations(shelter_id):
    return [r for r in rows("shelter_registrations")
            if r["shelter_operation_id"] == shelter_id]


def shelter_deployments(shelter_id):
    return [d for d in rows("volunteer_deployments")
            if d.get("shelter_operation_id") == shelter_id]


def shelter_derived(shelter):
    registrations = shelter_registrations(shelter["id"])
    occupied = sum(1 for r in registrations
                   if r["status"] == "REGISTERED" and r["dormitory_bed_code"])
    registered = sum(1 for r in registrations
                     if r["status"] in ("REGISTERED", "REUNIFIED"))
    reunification_pending = sum(1 for r in registrations
                                if r["reunification_status"] in ("PENDING", "VERIFIED"))
    staffed = sum(1 for d in shelter_deployments(shelter["id"])
                  if d["status"] in ("ARRIVED", "ON_SHIFT"))
    required = max(MIN_REQUIRED_VOLUNTEERS, ceil_div(registered, CLIENTS_PER_VOLUNTEER))
    ratio = Decimal(staffed) / Decimal(required)
    if ratio > 1:
        ratio = Decimal(1)
    sufficiency = float(round_half_up(ratio, 4))
    return {
        "occupied_beds": occupied,
        "registered_client_count": registered,
        "reunification_pending_count": reunification_pending,
        "staffed_volunteer_count": staffed,
        "staffing_sufficiency": sufficiency,
    }


def refresh_shelter(shelter):
    """Recompute the shelter aggregates; returns True when staffing changed."""
    before = shelter.get("staffing_sufficiency")
    values = shelter_derived(shelter)
    apply(shelter, values)
    return before != values["staffing_sufficiency"]


def apply_posture_gate(shelter):
    """OPEN <-> RESTRICTED moves automatically and only on staffing."""
    posture = shelter["posture"]
    if posture not in ("OPEN", "RESTRICTED"):
        return False
    sufficiency = shelter["staffing_sufficiency"]
    if sufficiency < RESTRICTED_THRESHOLD and posture == "OPEN":
        shelter["posture"] = "RESTRICTED"
        touch(shelter)
    elif sufficiency >= RESTRICTED_THRESHOLD and posture == "RESTRICTED":
        shelter["posture"] = "OPEN"
        touch(shelter)
    else:
        return False
    operation = find("disaster_relief_operations", shelter["disaster_relief_operation_id"])
    if operation is not None:
        refresh_operation(operation)
    return True


def refresh_shelter_and_posture(shelter):
    staffing_changed = refresh_shelter(shelter)
    if staffing_changed:
        apply_posture_gate(shelter)
    return shelter


def feeding_line_cost(meals_served, unit_cost_cents):
    raw = (Decimal(int(meals_served)) * Decimal(int(unit_cost_cents))
           * Decimal(10000 + SUPPLY_SURCHARGE_BPS) / Decimal(10000))
    return int(round_half_up(raw, 0))


def shelter_feeding_events(shelter_id):
    return core.feeding_events.get(shelter_id, [])


def operational_cost(shelter, mode="PROVISIONAL"):
    if mode == "FINAL":
        direct = int(shelter.get("feeding_cost_cents", 0))
        for deployment in shelter_deployments(shelter["id"]):
            if deployment["status"] == "ROTATION_ENDED":
                direct += int(deployment.get("travel_cost_cents", 0))
        for request_row in _shelter_assistance_requests(shelter["id"]):
            if request_row["status"] == "DISBURSED":
                direct += int(request_row.get("approved_amount_cents", 0))
    else:
        direct = 0
        for event in shelter_feeding_events(shelter["id"]):
            raw = (Decimal(int(event["meals_planned"])) * Decimal(int(event["unit_cost_cents"]))
                   * Decimal(10000 + SUPPLY_SURCHARGE_BPS) / Decimal(10000))
            direct += int(round_half_up(raw, 0))
        for deployment in shelter_deployments(shelter["id"]):
            if deployment["status"] in ("APPROVED", "IN_TRANSIT", "ARRIVED", "ON_SHIFT"):
                direct += int(deployment.get("travel_cost_cents", 0))
        for request_row in _shelter_assistance_requests(shelter["id"]):
            if request_row["status"] in ("APPROVED", "CARD_ISSUED"):
                direct += int(request_row.get("requested_amount_cents", 0))
    overhead = max(int(round_half_up(Decimal(direct) * Decimal(OVERHEAD_RATE_BPS) / Decimal(10000), 0)),
                   MIN_OVERHEAD_CENTS)
    return direct + overhead


def _shelter_assistance_requests(shelter_id):
    client_ids = {r["client_id"] for r in shelter_registrations(shelter_id)}
    if not client_ids:
        return []
    case_ids = {c["id"] for c in rows("client_cases") if c["client_id"] in client_ids}
    return [a for a in rows("assistance_requests") if a["client_case_id"] in case_ids]


def refresh_operation(operation):
    count = sum(1 for s in rows("shelter_operations")
                if s["disaster_relief_operation_id"] == operation["id"]
                and s["posture"] in ("OPEN", "RESTRICTED"))
    balance = restricted_fund_balance(operation["id"])
    apply(operation, {
        "open_shelter_count": count,
        "restricted_fund_balance_cents": balance,
    })
    return operation


def restricted_fund_balance(operation_id):
    pool_ids = {e["fund_pool_id"] for e in rows("cost_ledger_entries")
                if e["disaster_relief_operation_id"] == operation_id}
    total = 0
    for pool_id in pool_ids:
        pool = find("fund_pools", pool_id)
        if pool is None or pool["restriction_type"] == "UNRESTRICTED":
            continue
        total += pool_remaining(pool)
    return total


# --------------------------------------------------------------------------
# Money
# --------------------------------------------------------------------------


def pool_remaining(pool):
    requests = [a for a in rows("assistance_requests") if a["fund_pool_id"] == pool["id"]]
    committed = sum(int(a["approved_amount_cents"]) for a in requests
                    if a["status"] in ("APPROVED", "CARD_ISSUED"))
    disbursed = sum(int(a["approved_amount_cents"]) for a in requests
                    if a["status"] == "DISBURSED")
    return int(pool["total_received_cents"]) - committed - disbursed


def refresh_pool(pool):
    requests = [a for a in rows("assistance_requests") if a["fund_pool_id"] == pool["id"]]
    committed = sum(int(a["approved_amount_cents"]) for a in requests
                    if a["status"] in ("APPROVED", "CARD_ISSUED"))
    disbursed = sum(int(a["approved_amount_cents"]) for a in requests
                    if a["status"] == "DISBURSED")
    apply(pool, {
        "committed_cents": committed,
        "disbursed_cents": disbursed,
        "remaining_cents": int(pool["total_received_cents"]) - committed - disbursed,
    })
    return pool


def duplication_offset(case_id, assistance_type):
    return sum(int(r["estimated_value_cents"]) for r in rows("referrals")
               if r["client_case_id"] == case_id
               and r["assistance_type"] == assistance_type
               and r["status"] in ("SUBMITTED", "ACCEPTED", "COMPLETED"))


def assistance_award(requested_amount_cents, offset_cents):
    """STEP 2 only: the award is floored at zero; the MIN test is a later step."""
    return max(0, int(requested_amount_cents) - int(offset_cents))


def restriction_compatible(pool, assistance_type, client_region_id):
    restriction = pool["restriction_type"]
    if restriction == "UNRESTRICTED":
        return True
    if restriction == "DONOR_RESTRICTED_DISASTER":
        return True
    if restriction == "DONOR_RESTRICTED_BLOOD":
        return False
    if restriction == "DONOR_RESTRICTED_LOCAL":
        return pool.get("region_id") is not None and pool["region_id"] == client_region_id
    return False


def redemption_window_days(case):
    registrations = [r for r in rows("shelter_registrations") if r["client_id"] == case["client_id"]]
    for registration in registrations:
        shelter = find("shelter_operations", registration["shelter_operation_id"])
        if shelter is not None and shelter["posture"] == "RESTRICTED":
            return RESTRICTED_WINDOW_DAYS
    return STANDARD_WINDOW_DAYS


def client_entitlement(case):
    client = find("clients", case["client_id"])
    household_size = int(client["household_size"]) if client else 1
    base = min(HOUSEHOLD_CAP_CENTS, household_size * PER_PERSON_CENTS)
    functional = any(r["client_id"] == case["client_id"] and r["functional_needs_flag"]
                     for r in rows("shelter_registrations"))
    if functional or case["status"] == "REOPENED":
        extra = int(round_half_up(Decimal(base) * Decimal(EXPEDITED_MULTIPLIER_BPS) / Decimal(10000), 0))
        return min(EXPEDITED_CAP_CENTS, EXPEDITED_FLAT_CENTS + extra)
    return base


def refresh_case_entitlement(case):
    apply(case, {"entitlement_cents": client_entitlement(case)})
    return case


def case_closure_eligible_at(case):
    stamps = []
    for referral in rows("referrals"):
        if referral["client_case_id"] != case["id"]:
            continue
        if referral["status"] in ("COMPLETED", "DECLINED", "CANCELLED") and referral.get("_resolved_at"):
            stamps.append(parse_instant(referral["_resolved_at"]))
    for request_row in rows("assistance_requests"):
        if request_row["client_case_id"] != case["id"]:
            continue
        if request_row["status"] == "DISBURSED":
            stamps.append(parse_instant(request_row["updated_at"]))
    stamps = [s for s in stamps if s is not None]
    if not stamps:
        return None
    return format_instant(max(stamps) + timedelta(days=CLOSURE_HOLD_DAYS))


def refresh_case_closure(case):
    eligible = case_closure_eligible_at(case)
    apply(case, {"case_closure_eligible_at": eligible})
    return eligible


def case_status_after_referrals(case):
    """REFERRED -> MONITORING once no referral is still live."""
    if case["status"] != "REFERRED":
        return case["status"]
    live = any(r["client_case_id"] == case["id"] and r["status"] in ("SUBMITTED", "ACCEPTED")
               for r in rows("referrals"))
    return "REFERRED" if live else "MONITORING"


# --------------------------------------------------------------------------
# Volunteer deployment pricing and candidate scoring
# --------------------------------------------------------------------------


def travel_cost(volunteer, operation, travel_mode, rotation_days):
    if volunteer["home_region_id"] == operation["region_id"]:
        miles = TRAVEL_SAME_REGION_MILES
    else:
        miles = TRAVEL_CROSS_REGION_MILES
    days = int(rotation_days)
    if travel_mode == "AIR":
        return AIR_BASE_CENTS + max(0, days - AIR_SURCHARGE_FREE_DAYS) * AIR_DAY_SURCHARGE_CENTS
    if travel_mode == "GROUND":
        return (miles * GROUND_RATE_CENTS_PER_MILE
                + max(0, days - GROUND_LODGING_FREE_DAYS) * GROUND_LODGING_PER_DAY_CENTS)
    return 0


def priority_score(volunteer, operation, role_code):
    refreshed = volunteer.get("credential_refreshed_at")
    if refreshed:
        seconds = (clock.now - parse_instant(refreshed)).total_seconds()
        whole_days = int(math.floor(max(0.0, seconds) / 86400.0))
        quotient = whole_days // RECENCY_WINDOW_DAYS
        recency_bonus = max(0, RECENCY_MAX_BONUS - quotient)
    else:
        recency_bonus = 0
    if volunteer["home_region_id"] == operation["region_id"]:
        miles = SCORE_SAME_REGION_MILES
    else:
        miles = SCORE_CROSS_REGION_MILES
    distance_penalty = min(DISTANCE_MAX_PENALTY, miles // MILES_PER_PENALTY_UNIT)
    rotation_penalty = min(ROTATION_MAX_PENALTY,
                           int(volunteer["rotation_days_used_ytd"]) * ROTATION_PENALTY_PER_DAY)
    role_bonus = ROLE_MATCH_BONUS if role_code in (volunteer.get("qualified_role_codes") or []) else 0
    return max(0, BASE_SCORE + recency_bonus - distance_penalty - rotation_penalty + role_bonus)


def usable_units(collected_units):
    lost = (int(collected_units) * DEFERRAL_LOSS_BPS) // 10000
    return int(collected_units) - lost


def refresh_drive(drive):
    apply(drive, {"usable_units": usable_units(drive["collected_units"])})
    return drive
