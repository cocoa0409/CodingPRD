"""Domain services: calculations, cascades, fatigue, completion evaluation.

All cross-entity business logic lives here so routes stay thin.
"""
from datetime import date, timedelta
from decimal import Decimal

from db import stores, get_clock
from helpers import (
    ApiError, now_ts, touch, new_entity, round_half_up_int, current_date_str,
)

# --- calculation constants (SCAFFOLD.yaml calculations table) ---------------
DISCOUNT_TIER_3 = Decimal("0.05")
DISCOUNT_TIER_4 = Decimal("0.10")
INTERNATIONAL_MULTIPLIER = Decimal("1.20")
DOMESTIC_MULTIPLIER = Decimal("1.00")

TIER_HIGH_FLOOR_CENTS = 500000
TIER_MID_FLOOR_CENTS = 100000
RATE_HIGH = Decimal("0.30")
RATE_MID = Decimal("0.20")
RATE_LOW = Decimal("0.10")
BASE_VISIT_CENTS = 150000

VERIFY_INCREMENT = 2
REMOTE_CONSULT_DECREMENT = 3
WITHDRAWAL_THRESHOLD = 10

MAX_WINDOW_DAYS = 5
DEPOSIT_DEADLINE_DAYS = 14
MAX_REVIEW_DAYS = 3

WITHDRAWABLE_CASE_STATES = {"INTAKE", "AWAITING_FINANCIAL", "FINANCIAL_CLEARED", "SCHEDULING"}
TERMINAL_CASE_STATES = {"COMPLETED", "WITHDRAWN", "DECLINED"}


# --- lookups ----------------------------------------------------------------

def case_clearance(case_id):
    for fc in stores["financial_clearances"].values():
        if fc["visit_case_id"] == case_id:
            return fc
    return None


def case_itinerary(case_id):
    for it in stores["itineraries"].values():
        if it["visit_case_id"] == case_id:
            return it
    return None


def case_patient(case):
    referral = stores["referrals"].get(case["referral_id"])
    if referral is None:
        return None
    return stores["patients"].get(referral.get("patient_id"))


def case_referral(case):
    return stores["referrals"].get(case["referral_id"])


def issued_letter(case_id):
    for letter in stores["estimate_letters"].values():
        if letter["visit_case_id"] == case_id and letter["status"] == "ISSUED":
            return letter
    return None


def case_visits(case_id):
    return [v for v in stores["visits"].values() if v["visit_case_id"] == case_id]


def itinerary_visits(itinerary_id):
    return [v for v in stores["visits"].values() if v["itinerary_id"] == itinerary_id]


def letter_view(letter):
    """Return a serialization of the letter with computed is_stale."""
    it = case_itinerary(letter["visit_case_id"])
    current_revision = it["revision"] if it else letter["itinerary_revision_at_issue"]
    out = dict(letter)
    out["is_stale"] = letter["itinerary_revision_at_issue"] < current_revision
    return out


# --- estimate engine (§3.5) --------------------------------------------------

def recompute_itinerary_totals(itinerary):
    """Recompute provisional/final totals over the active visit set and store."""
    case = stores["visit_cases"].get(itinerary["visit_case_id"])
    patient = case_patient(case) if case else None
    is_international = bool(patient and patient["is_international"])
    multiplier = INTERNATIONAL_MULTIPLIER if is_international else DOMESTIC_MULTIPLIER

    active = [
        v for v in itinerary_visits(itinerary["id"])
        if v["status"] in ("PENDING", "CONFIRMED", "COMPLETED")
    ]
    bundled_count = len(active)
    if bundled_count <= 2:
        discount = Decimal("0")
    elif bundled_count == 3:
        discount = DISCOUNT_TIER_3
    else:
        discount = DISCOUNT_TIER_4

    factor = (Decimal("1") - discount) * multiplier
    per_visit_raw = [Decimal(v["listed_price_cents"]) * factor for v in active]
    provisional = sum(round_half_up_int(p) for p in per_visit_raw)
    final = round_half_up_int(sum(per_visit_raw, Decimal("0")))

    itinerary["provisional_total_cents"] = provisional
    itinerary["final_total_cents"] = final


def compute_tiered_deposit(final_estimate_cents):
    if final_estimate_cents >= TIER_HIGH_FLOOR_CENTS:
        return round_half_up_int(Decimal(final_estimate_cents) * RATE_HIGH)
    if final_estimate_cents >= TIER_MID_FLOOR_CENTS:
        return round_half_up_int(Decimal(final_estimate_cents) * RATE_MID)
    return round_half_up_int(Decimal(final_estimate_cents) * RATE_LOW)


def approval_base_estimate(case):
    """Seed estimate used at review approval: care-team size * BASE_VISIT_CENTS,
    with the international multiplier applied on top for international patients."""
    base = len(case["care_team_specialty_ids"]) * BASE_VISIT_CENTS
    patient = case_patient(case)
    if patient and patient["is_international"]:
        base = round_half_up_int(Decimal(base) * INTERNATIONAL_MULTIPLIER)
    return base


# --- fatigue / auto-withdrawal (§3.3) ----------------------------------------

def bump_fatigue_on_verify(referral_id):
    """+2 fatigue on every non-terminal case under the referral, then threshold check."""
    for case in list(stores["visit_cases"].values()):
        if case["referral_id"] != referral_id:
            continue
        if case["status"] in TERMINAL_CASE_STATES:
            continue
        case["fatigue_score"] += VERIFY_INCREMENT
        touch(case)
        check_fatigue_withdrawal(case)


def check_fatigue_withdrawal(case):
    if case["fatigue_score"] >= WITHDRAWAL_THRESHOLD and case["status"] in WITHDRAWABLE_CASE_STATES:
        withdraw_case(case)


def decrement_fatigue_on_remote_consult(case):
    if case["status"] in TERMINAL_CASE_STATES:
        return
    if case["case_type"] != "REMOTE_CONSULT":
        return
    case["fatigue_score"] = max(0, case["fatigue_score"] - REMOTE_CONSULT_DECREMENT)
    touch(case)


# --- release cascade (§3.7) --------------------------------------------------

def release_cascade(case):
    """Release HELD slots, cancel PENDING visits, cancel DRAFT itinerary,
    cancel REQUESTED/BOOKED logistics arrangements. Each affected resource is a
    real mutation: updated_at refreshes and version increments."""
    it = case_itinerary(case["id"])

    for slot in stores["appointment_slots"].values():
        if slot.get("held_by_case_id") == case["id"] and slot["status"] == "HELD":
            slot["status"] = "RELEASED"
            slot["held_by_case_id"] = None
            touch(slot)

    for visit in case_visits(case["id"]):
        if visit["status"] == "PENDING":
            visit["status"] = "CANCELLED"
            touch(visit)

    if it and it["status"] == "DRAFT":
        it["status"] = "CANCELLED"
        touch(it)

    for arr in stores["logistics_arrangements"].values():
        if arr["visit_case_id"] == case["id"] and arr["status"] in ("REQUESTED", "BOOKED"):
            arr["status"] = "CANCELLED"
            touch(arr)


def decline_logistics_cascade(case):
    for arr in stores["logistics_arrangements"].values():
        if arr["visit_case_id"] == case["id"] and arr["status"] in ("REQUESTED", "BOOKED"):
            arr["status"] = "CANCELLED"
            touch(arr)


def withdraw_case(case):
    """Shared manual/auto withdrawal: status -> WITHDRAWN with release cascade."""
    release_cascade(case)
    case["status"] = "WITHDRAWN"
    touch(case)


# --- case completion / referral closure (§3.7, §3.8) -------------------------

def reevaluate_case_completion(case):
    """READY_TO_TRAVEL -> COMPLETED when every non-CANCELLED visit is COMPLETED
    or NO_SHOW and at least one visit is COMPLETED."""
    if case["status"] != "READY_TO_TRAVEL":
        return
    it = case_itinerary(case["id"])
    if it is None:
        return
    visits = itinerary_visits(it["id"])
    non_cancelled = [v for v in visits if v["status"] != "CANCELLED"]
    if not non_cancelled:
        return
    if all(v["status"] in ("COMPLETED", "NO_SHOW") for v in non_cancelled):
        if any(v["status"] == "COMPLETED" for v in non_cancelled):
            case["status"] = "COMPLETED"
            touch(case)
            reevaluate_referral_closure(case)


def reevaluate_referral_closure(case):
    """Referral REVIEWED -> CLOSED once the case is COMPLETED and both required
    communications exist."""
    if case["status"] != "COMPLETED":
        return
    referral = case_referral(case)
    if referral is None or referral["status"] != "REVIEWED":
        return
    comms = [c for c in stores["communications"].values() if c["visit_case_id"] == case["id"]]
    has_results = any(c["comm_type"] == "RESULTS_TO_REFERRER" for c in comms)
    has_plan = any(c["comm_type"] == "CONTINUITY_PLAN" for c in comms)
    if has_results and has_plan:
        referral["status"] = "CLOSED"
        touch(referral)


# --- financial clearance bubbling --------------------------------------------

def clearance_cleared(clearance):
    """PENDING -> CLEARED plus bubble the case AWAITING_FINANCIAL -> FINANCIAL_CLEARED."""
    clearance["status"] = "CLEARED"
    touch(clearance)
    case = stores["visit_cases"].get(clearance["visit_case_id"])
    if case and case["status"] == "AWAITING_FINANCIAL":
        case["status"] = "FINANCIAL_CLEARED"
        touch(case)


def maybe_clear_on_deposit(clearance):
    """After a DEPOSIT posts: clear when deposit_paid_cents >= required_deposit_cents
    (equality clears)."""
    if clearance["status"] != "PENDING":
        return
    if clearance["deposit_paid_cents"] >= clearance["required_deposit_cents"]:
        clearance_cleared(clearance)


# --- capacity / overlap (§3.1, §3.4) ------------------------------------------

def slots_overlap(a_start, a_end, b_start, b_end):
    return a_start < b_end and b_start < a_end


def used_capacity(service_id, slot_date):
    return sum(
        1 for s in stores["appointment_slots"].values()
        if s["specialty_service_id"] == service_id
        and s["slot_date"] == slot_date
        and s["status"] in ("HELD", "CONFIRMED")
    )


def earliest_held_slot_date(case_id):
    dates = [
        s["slot_date"] for s in stores["appointment_slots"].values()
        if s.get("held_by_case_id") == case_id and s["status"] == "HELD"
    ]
    return min(dates) if dates else None


def forfeit_deadline_breached(case_id):
    """True when the logical clock date is strictly later than the earliest HELD
    slot date minus DEPOSIT_DEADLINE_DAYS. No HELD slots -> no deadline anchor."""
    earliest = earliest_held_slot_date(case_id)
    if earliest is None:
        return False
    deadline = date.fromisoformat(earliest) - timedelta(days=DEPOSIT_DEADLINE_DAYS)
    return get_clock().date() > deadline


# --- sequencing (§3.7) --------------------------------------------------------

def sequencing_blocker(visit):
    """Return a blocking visit if a lower-priority same-day CONFIRMED visit exists."""
    this_slot = stores["appointment_slots"].get(visit["appointment_slot_id"])
    if this_slot is None:
        return None
    for other in itinerary_visits(visit["itinerary_id"]):
        if other["id"] == visit["id"] or other["status"] != "CONFIRMED":
            continue
        other_slot = stores["appointment_slots"].get(other["appointment_slot_id"])
        if other_slot is None or other_slot["slot_date"] != this_slot["slot_date"]:
            continue
        if other["sequencing_priority"] < visit["sequencing_priority"]:
            return other
        if other["sequencing_priority"] == visit["sequencing_priority"] and \
                other["created_at"] < visit["created_at"]:
            return other
    return None
