"""Business logic: state machines, calculations, validations.

Every constant and rule here traces to a verbatim sentence in PRD.md or a row in
SCAFFOLD.yaml. Section references are given at each block.
"""

import math
from datetime import timedelta
from decimal import Decimal, ROUND_CEILING, ROUND_FLOOR, ROUND_HALF_UP

import db
from db import (
    DB, add_months, add_years, age_in_whole_years, clock, fmt, new_id, new_row,
    now_iso, parse_iso, touch, touch_only, whole_days_between,
)
from errors import ApiError, ValidationFailure

# =============================================================================
# Lookups (path identifier resolution, PRD §2.9)
# =============================================================================

NOT_FOUND_CODES = {
    "funds": "ERR_FUND_NOT_FOUND",
    "protocols": "ERR_PROTOCOL_NOT_FOUND",
    "referrals": "ERR_REFERRAL_NOT_FOUND",
    "enrollments": "ERR_ENROLLMENT_NOT_FOUND",
    "pledges": "ERR_PLEDGE_NOT_FOUND",
    "housing_assignments": "ERR_HOUSING_ASSIGNMENT_NOT_FOUND",
    "housing_facilities": "ERR_HOUSING_FACILITY_NOT_FOUND",
    "travel_arrangements": "ERR_TRAVEL_NOT_FOUND",
    "clinics": "ERR_CLINIC_NOT_FOUND",
    "affiliations": "ERR_AGREEMENT_NOT_FOUND",
    "milestones": "ERR_MILESTONE_NOT_FOUND",
    "studies": "ERR_STUDY_NOT_FOUND",
    "survivorship_enrollments": "ERR_SURVIVORSHIP_ENROLLMENT_NOT_FOUND",
    "follow_ups": "ERR_NOT_FOUND",
    "services": "ERR_SERVICE_NOT_FOUND",
    "ledgers": "ERR_LEDGER_NOT_FOUND",
    "sibling_services": "ERR_SIBLING_SERVICE_NOT_FOUND",
    "holds": "ERR_HOLD_NOT_FOUND",
}


def get_or_404(kind, ident):
    row = DB[kind].get(ident)
    if row is None:
        raise ApiError(NOT_FOUND_CODES[kind])
    return row


def get_optional(kind, ident):
    if ident is None:
        return None
    return DB[kind].get(ident)


def require_exists(kind, ident):
    """Body foreign keys: a missing FK yields the generic ERR_NOT_FOUND (PRD §2.9)."""
    if ident is None or DB[kind].get(ident) is None:
        raise ApiError("ERR_NOT_FOUND")
    return DB[kind][ident]


# =============================================================================
# Money helpers (PRD §2.8)
# =============================================================================

def cents_ceil(pct, amount_cents):
    """Round a rate product up to the next whole cent."""
    value = Decimal(str(pct)) * Decimal(int(amount_cents))
    return int(value.to_integral_value(rounding=ROUND_CEILING))


def cents_floor(pct, amount_cents):
    """The one round-down site: the fund's commitment share."""
    value = Decimal(str(pct)) * Decimal(int(amount_cents))
    return int(value.to_integral_value(rounding=ROUND_FLOOR))


def round_half_up(value):
    """Round half up to a whole cent."""
    return int(Decimal(str(value)).to_integral_value(rounding=ROUND_HALF_UP))


# =============================================================================
# Calculation: fundraising_split_at_commitment (PRD §2.4)
# =============================================================================

def derive_fund_split(fund):
    """Re-derive the fund's research / patient-support pools from its inputs.

    research_balance_cents        += ceil(research_allocation_pct * fundraising_raised_cents)
    patient_support_balance_cents += (fundraising_raised_cents - federal_grant_cents)
                                     - ceil(research_allocation_pct * fundraising_raised_cents)

    PRD §2.4 re-derives both pools on every read of the fund so that a later donation
    is reflected immediately; the disbursements, settlements and markups of §3.5,
    §3.6 and §3.10 accumulate on top of that derivation as deltas, so they survive
    the re-derivation.
    """
    raised = int(fund["fundraising_raised_cents"])
    grant = int(fund["federal_grant_cents"])
    research = cents_ceil(fund["research_allocation_pct"], raised)
    patient = (raised - grant) - research
    fund["research_balance_cents"] = research + int(fund.get("_research_delta", 0))
    fund["patient_support_balance_cents"] = patient + int(fund.get("_patient_delta", 0))
    return fund


def fund_add_research(fund, amount):
    fund["_research_delta"] = int(fund.get("_research_delta", 0)) + int(amount)
    return derive_fund_split(fund)


def fund_add_patient_support(fund, amount):
    fund["_patient_delta"] = int(fund.get("_patient_delta", 0)) + int(amount)
    return derive_fund_split(fund)


def commitment_share_ceiling(fund, including_new=0):
    """PRD §2.4: the budget may not exceed three quarters of the fund's net
    fundraising divided by the number of protocols the fund supports, rounded down
    to a whole cent. The divisor counts the protocol being created as well."""
    net = int(fund["fundraising_raised_cents"]) - int(fund["federal_grant_cents"])
    protocol_count = sum(
        1 for p in DB["protocols"].values() if p["fund_id"] == fund["id"])
    divisor = max(1, protocol_count + including_new)
    return int((Decimal("0.75") * Decimal(net) / Decimal(divisor)).to_integral_value(
        rounding=ROUND_FLOOR))


def serialize_fund(fund):
    row = dict(fund)
    row.pop("_pending", None)
    row.pop("_research_delta", None)
    row.pop("_patient_delta", None)
    return row


# =============================================================================
# Calculation: protocol derived attributes (PRD §2.5, §2.5 saturation §2.5/SCAFFOLD)
# =============================================================================

def derive_age_tier(age_min, age_max):
    if age_max < 12:
        return "PAEDIATRIC"
    if age_min >= 12:
        return "ADOLESCENT"
    return "MIXED"


def recompute_protocol_derived(protocol):
    protocol["available_cents"] = (
        int(protocol["protocol_budget_cents"])
        - int(protocol["reserved_cents"])
        - int(protocol["committed_cents"])
    )
    saturation_cap = cents_ceil(0.0375, protocol["protocol_budget_cents"])
    # PRD §2.5: "flagged `is_budget_saturated` once `available_cents` is above
    # zero but no larger than three point seven five percent of the protocol
    # budget, rounded up to the next whole cent." The floor of the band is
    # `available_cents >= 0` — the flag must flip on at the exact instant the
    # eighth ON_CAMPUS reservation drives available_cents to 0 (its whole point is
    # to warn before the 402 gate refuses further screens).
    protocol["is_budget_saturated"] = (
        0 <= protocol["available_cents"] <= saturation_cap)
    return protocol


# =============================================================================
# Calculation: housing_tier_selector (PRD §2.6)
# =============================================================================

TIER_ORDER = ["ON_CAMPUS", "PARTNER_CLASS_A", "PARTNER_CLASS_B", "PARTNER_CLASS_C"]
DURATION_CLAMP_DAYS = 540
STEP_BAND_DAYS = 180

# PRD §2.6: the selector first computes the referral's required tier (a band
# from the duration steps, unless immunosuppression pins it to ON_CAMPUS).
# Candidate facilities are the OPEN residences whose tier is at least as capable
# as that required tier, that is, a residence at the required tier or at a MORE
# capable tier above it; ranking orders them by the tier's position in the
# sequence ON_CAMPUS, PARTNER_CLASS_A, PARTNER_CLASS_B, PARTNER_CLASS_C, lowest
# position first, so the search first tries every residence at the family's own
# band and only falls through to a more capable one when the whole band is
# occupied. A residence below the required tier is never a candidate.
#
# An immunosuppressed referral's required tier is ON_CAMPUS, which is the highest
# position, so its candidate set is exactly the ON_CAMPUS residence — and PRD
# §2.6's own step-down rule ("a family may not be moved out of ON_CAMPUS until
# immunosuppression has cleared") confirms that such a family is never placed
# below it.
FACILITY_CAPABILITY = {
    "ON_CAMPUS": ["ON_CAMPUS"],
    "PARTNER_CLASS_A": ["PARTNER_CLASS_A", "PARTNER_CLASS_B", "PARTNER_CLASS_C"],
    "PARTNER_CLASS_B": ["PARTNER_CLASS_B", "PARTNER_CLASS_C"],
    "PARTNER_CLASS_C": ["PARTNER_CLASS_C"],
}


def required_tier_for(referral):
    """The deterministic tier the selector demands for a referral."""
    if referral.get("is_immunosuppressed") or referral.get("has_febrile_neutropenia_risk"):
        return "ON_CAMPUS"
    window_days = min(int(referral["expected_treatment_days"]), DURATION_CLAMP_DAYS)
    steps = int(math.ceil(window_days / float(STEP_BAND_DAYS)))
    if steps <= 1:
        return "PARTNER_CLASS_C"
    if steps == 2:
        return "PARTNER_CLASS_A"
    return "PARTNER_CLASS_B"


def selector_candidates(required_tier):
    """The candidate tiers for `required_tier`, in selection order.

    PRD §2.6 derives the required tier (the top of the family's band), then
    orders candidates "by the tier's position in the sequence ON_CAMPUS,
    PARTNER_CLASS_A, PARTNER_CLASS_B, PARTNER_CLASS_C — lowest position first".
    The family's own band is tried first, and the less capable tiers below it
    follow as fallbacks, so a family is never refused housing merely because its
    exact band is momentarily full. A residence ABOVE the band is never offered,
    because a family may only be stepped down, never up.

    ON_CAMPUS is a candidate only when the selector actually pinned the family
    there: PRD §2.6 makes it the one tier an immunosuppressed child may be
    housed in and forbids stepping a family down out of it before
    immunosuppression clears.
    """
    index = TIER_ORDER.index(required_tier)
    tiers = list(TIER_ORDER[index:])
    if required_tier != "ON_CAMPUS" and "ON_CAMPUS" in tiers:
        tiers.remove("ON_CAMPUS")
    return tiers


def _selector_sort_key(facility):
    return (
        TIER_ORDER.index(facility["tier"]),
        0 if facility["immunosuppression_capable"] else 1,
        -(int(facility["total_beds"]) - int(facility["buffer_beds"])),
        facility["created_at"],
        facility["facility_code"],
    )


def pick_candidates(required_tier, exclude=None, additional=None):
    preference = selector_candidates(required_tier)
    candidates = [f for f in DB["housing_facilities"].values()
                  if f["status"] == "OPEN"]
    if exclude:
        candidates = [f for f in candidates if f["id"] not in exclude]
    candidates = [f for f in candidates if f["tier"] in preference]
    if additional:
        candidates = [f for f in candidates if additional(f)]
    candidates.sort(key=lambda f: (
        preference.index(f["tier"]),
        0 if f["immunosuppression_capable"] else 1,
        -(int(f["total_beds"]) - int(f["buffer_beds"])),
        f["created_at"],
        f["facility_code"],
    ))
    return candidates


def select_facility(required_tier, exclude=None, additional=None):
    """Return the winning HousingFacility or None. Pure ranking, no side effects."""
    candidates = pick_candidates(required_tier, exclude=exclude, additional=additional)
    return candidates[0] if candidates else None


# =============================================================================
# Calculation: housing_occupancy_charge + facility bed accounting (PRD §2.6, §3.4)
# =============================================================================

NIGHTLY_RATES = {
    "ON_CAMPUS": 19000,
    "PARTNER_CLASS_A": 15000,
    "PARTNER_CLASS_B": 13000,
    "PARTNER_CLASS_C": 11000,
}
NIGHT_CLAMP = 180


def window_nights(start_at, end_at):
    """Whole days between start_at and end_at."""
    return whole_days_between(parse_iso(start_at), parse_iso(end_at))


def billed_nights(start_at, end_at):
    """The inclusive night count of the window, floored at zero."""
    return max(0, window_nights(start_at, end_at))


def chargeable_nights(start_at, end_at):
    """The clamp is per booking: a 900-night and a 180-night window price alike."""
    return min(billed_nights(start_at, end_at), NIGHT_CLAMP)


def housing_cost(tier, start_at, end_at):
    return chargeable_nights(start_at, end_at) * NIGHTLY_RATES[tier]


def assignment_covers(assignment, instant):
    """Half-open occupancy window [start_at, end_at)."""
    return (parse_iso(assignment["start_at"]) <= instant
            < parse_iso(assignment["end_at"]))


def facility_occupancies_at(facility_id, instant, exclude=None):
    count = 0
    for assignment in DB["housing_assignments"].values():
        if assignment["housing_facility_id"] != facility_id:
            continue
        if assignment["status"] not in ("SCHEDULED", "ACTIVE"):
            continue
        if exclude and assignment["id"] == exclude:
            continue
        if assignment_covers(assignment, instant):
            count += 1
    return count


def facility_committed_beds(facility_id):
    """PRD §2.6: "the highest number of occupancies that coincide at any single
    instant across the facility's assignments in `SCHEDULED` or `ACTIVE` status".

    Only the booked window endpoints are inspected, since an occupancy count can
    only change at an endpoint. A window is half-open, so an assignment is
    counted at an endpoint only while its window actually covers that instant.
    """
    instants = set()
    for assignment in DB["housing_assignments"].values():
        if assignment["housing_facility_id"] != facility_id:
            continue
        if assignment["status"] not in ("SCHEDULED", "ACTIVE"):
            continue
        instants.add(parse_iso(assignment["start_at"]))
        instants.add(parse_iso(assignment["end_at"]))
    best = 0
    for instant in instants:
        best = max(best, facility_occupancies_at(facility_id, instant))
    return best


def recompute_facility_beds(facility):
    facility["active_beds_committed"] = facility_committed_beds(facility["id"])
    return facility


def facility_capacity_ok(facility, start_at, end_at, exclude=None):
    """PRD §2.6: at both endpoints, covering assignments + buffer <= total_beds.

    The proposed assignment itself occupies a bed at both endpoints, so it is
    counted alongside the covering assignments — a single-bed residence with no
    buffer refuses even the first booking.
    """
    total_beds = int(facility["total_beds"])
    buffer_beds = int(facility["buffer_beds"])
    for instant in (parse_iso(start_at), parse_iso(end_at)):
        covering = facility_occupancies_at(facility["id"], instant, exclude=exclude)
        if (covering + 1) + buffer_beds > total_beds:
            return False
    return True


def find_facility_for_booking(referral_like, start_at, end_at, exclude=None):
    """Run the selector plus the capacity filter and return the facility or None."""
    required_tier = referral_like["required_tier"]
    candidate_tiers = FACILITY_CAPABILITY[required_tier]
    for facility in pick_candidates(required_tier, exclude=exclude):
        if facility["tier"] not in candidate_tiers:
            continue
        if not facility_capacity_ok(facility, start_at, end_at, exclude=exclude):
            continue
        return facility
    return None


def assign_capable_facility_excluding(facility_id, start_at, end_at):
    """Fallback walk for re-bookings once the preferred replacement fails capacity."""
    for facility in DB["housing_facilities"].values():
        if facility["id"] == facility_id:
            continue
        if facility["status"] != "OPEN":
            continue
        if facility_capacity_ok(facility, start_at, end_at):
            return facility
    return None


def assigned_tier_for_enrollment(enrollment):
    """assigned_tier must equal the referral's applied_tier; when the referral has
    no accepted tier yet the selector is run for the enrollment's referral."""
    referral = referral_for_enrollment(enrollment)
    if referral is not None and referral.get("applied_tier") in TIER_ORDER:
        return referral["applied_tier"]
    if referral is not None:
        return required_tier_for(referral)
    return "PARTNER_CLASS_C"


# =============================================================================
# Calculation: final_family_day_charge (PRD §3.5, §3.6)
# =============================================================================

NEAR_STATES = {"TX", "OK", "AR", "MS", "AL", "LA", "TN", "MO", "KY"}
FAR_STATES = {"CA", "NY", "IL", "WA", "MA", "NJ", "CT", "OR", "MD"}
NEAR_PER_TRAVELER_DAY_CENTS = 15000
FAR_PER_TRAVELER_DAY_CENTS = 22000
STANDARD_PER_TRAVELER_DAY_CENTS = 18000

STARTER_PER_FAMILY_DAY_CENTS = 450


def resolved_per_traveler_day_cents(household_state_code):
    state = (household_state_code or "").upper()
    if state in NEAR_STATES:
        return NEAR_PER_TRAVELER_DAY_CENTS
    if state in FAR_STATES:
        return FAR_PER_TRAVELER_DAY_CENTS
    return STANDARD_PER_TRAVELER_DAY_CENTS


# =============================================================================
# Calculation: family_support_allocation (PRD §2.7, §3.5)
# =============================================================================

def compute_billing_permitted(final_settled_cents, patient_support_budget_cents,
                              insurance_coverage_cents):
    covered_from_budget = min(final_settled_cents, patient_support_budget_cents)
    remaining_after_budget = final_settled_cents - covered_from_budget
    covered_from_insurance = min(remaining_after_budget, insurance_coverage_cents)
    resulting_balance = remaining_after_budget - covered_from_insurance
    return max(0, resulting_balance)


def recompute_pledge_derived(pledge, enrollment, referral, protocol):
    """Refresh the computed fields of a pledge.

    `final_settled_cents` is a settlement-time figure (SCAFFOLD: FamilySupportPledge
    §1.3), so it only holds a value once the pledge has settled; a live pledge
    reports zero there and carries its coverage in `provisional_settled_cents`.
    """
    state_code = (referral or {}).get("household_state_code")
    days = int(pledge["covered_days"])
    pledge["provisional_settled_cents"] = days * STARTER_PER_FAMILY_DAY_CENTS
    if pledge["status"] == "SETTLED_FINAL":
        final_settled = pledge["final_settled_cents"]
    else:
        final_settled = 0
    if pledge["status"] == "ACTIVE":
        pledge["billing_permitted_cents"] = 0
    else:
        pledge["billing_permitted_cents"] = compute_billing_permitted(
            final_settled,
            int(pledge["patient_support_budget_cents"]),
            int((referral or {}).get("insurance_coverage_cents", 0)),
        )
    return pledge


def settle_pledge(pledge):
    """PRD §3.5 settlement: freeze covered_days, resolve the rate, debit the pool."""
    enrollment = DB["enrollments"][pledge["enrollment_id"]]
    referral = referral_for_enrollment(enrollment)
    protocol = protocol_for_enrollment(enrollment)
    referral = referral or {}
    final_settled = int(pledge["covered_days"]) * resolved_per_traveler_day_cents(
        referral.get("household_state_code"))
    pledge["final_settled_cents"] = final_settled
    pledge["billing_permitted_cents"] = compute_billing_permitted(
        final_settled,
        int(pledge["patient_support_budget_cents"]),
        int(referral.get("insurance_coverage_cents", 0)),
    )
    if protocol is not None:
        fund = DB["funds"].get(protocol["fund_id"])
        if fund is not None:
            fund_add_patient_support(fund, -final_settled)
    pledge["status"] = "SETTLED_FINAL"
    touch(pledge)
    return pledge


# =============================================================================
# Calculation: protocol_referral_reservation (PRD §3.2, §2.5)
# =============================================================================

ON_CAMPUS_RESERVE_RATE = 0.125
PARTNER_RESERVE_RATE = 0.0625
SATURATION_RATE = 0.0375
MAX_PROTOCOL_BUDGET_RATE = 0.75


def reservation_basis_for(protocol, applied_tier):
    if applied_tier == "ON_CAMPUS":
        return cents_ceil(ON_CAMPUS_RESERVE_RATE, protocol["protocol_budget_cents"])
    return cents_ceil(PARTNER_RESERVE_RATE, protocol["protocol_budget_cents"])


# =============================================================================
# Calculation: protocol_research_day_accrual (PRD §3.6)
# =============================================================================

def research_day_accrual(household_state_code):
    return resolved_per_traveler_day_cents(household_state_code)


# =============================================================================
# Calculation: family_stimulation_markup (PRD §3.10)
# =============================================================================

def stimulation_markup(service):
    if not service.get("is_stimulation_eligible"):
        return 0
    markups = round_half_up(
        Decimal(str(service["base_allowance_cents"])) * Decimal(str(service["stimulation_rate"])))
    return min(markups, int(service["stimulation_cap_cents"] or 0))


# =============================================================================
# Calculation: sibling_monthly_limit (PRD §3.10)
# =============================================================================

def sessions_per_window(household_state_code):
    if (household_state_code or "").upper() in NEAR_STATES:
        return 4
    return 6


def recompute_sibling_limit(service, household_state_code):
    limit = sessions_per_window(household_state_code)
    service["has_reached_monthly_limit"] = int(service["sessions_delivered"]) >= limit
    return service


# =============================================================================
# Calculation: travel_accumulation_charge (PRD §3.6)
# =============================================================================

REQUIRED_TRAVEL_REASONS = {
    "PROTOCOL_REVIEW", "THERAPY_ADMINISTRATION", "SURVIVORSHIP_VISIT",
}


def leg_billed_days(leg):
    """Billed days between departure_at and return_at, both boundaries exclusive,
    with a floor of one day."""
    if leg.get("return_at") is None:
        return 1
    days = whole_days_between(parse_iso(leg["departure_at"]), parse_iso(leg["return_at"]))
    return max(1, days)


def family_day_units(leg, referral):
    """traveler_count * billed days; when the referral declares one-to-one care
    capability codes the multiplier counts only the cleared travelers."""
    days = leg_billed_days(leg)
    cleared = referral.get("one_to_one_care_capability_codes") if referral else None
    if cleared:
        placed = set(referral.get("traveling_one_to_one_codes") or [])
        permitted = set(cleared or [])
        multiplier = len(placed & permitted)
    else:
        multiplier = int(leg["traveler_count"])
    return multiplier * days


def resolve_leg_cost(leg, referral):
    rate = resolved_per_traveler_day_cents(
        (referral or {}).get("household_state_code"))
    return family_day_units(leg, referral) * rate


def attach_coverage(leg, placements):
    """Most recent placed coverage whose travel window contains departure_at; when
    several qualify the highest coverage_cents wins, ties broken by created_at asc."""
    departure = parse_iso(leg["departure_at"])
    qualifying = []
    for index, placement in enumerate(placements):
        window_start = parse_iso(placement["travel_window_start_at"])
        window_end = parse_iso(placement["travel_window_end_at"])
        if window_start <= departure <= window_end:
            qualifying.append((index, placement))
    if not qualifying:
        return None
    qualifying.sort(key=lambda pair: (-int(pair[1]["coverage_cents"]), pair[0]))
    return qualifying[0][1]


def travel_accumulation(enrollment):
    referral = referral_for_enrollment(enrollment)
    legs = [leg for leg in DB["travel_arrangements"].values()
            if leg["enrollment_id"] == enrollment["id"]
            and leg["status"] in ("CONFIRMED", "DISBURSED")]
    legs.sort(key=lambda leg: (leg["departure_at"], leg["created_at"]))
    total = 0
    chargeable = 0
    for leg in legs:
        coverage = attach_coverage(leg, leg.get("placed_coverages") or [])
        if coverage is not None and coverage.get("covers_required_travel"):
            is_chargeable = True
        elif coverage is not None:
            is_chargeable = leg["trip_reason"] in REQUIRED_TRAVEL_REASONS
        else:
            is_chargeable = leg["trip_reason"] in REQUIRED_TRAVEL_REASONS
        if is_chargeable:
            total += family_day_units(leg, referral) * resolved_per_traveler_day_cents(
                (referral or {}).get("household_state_code"))
            chargeable += 1
    return chargeable, total


# =============================================================================
# Referral derived attributes (PRD §3.2, §3.3)
# =============================================================================

def eligibility_alias(child_name):
    return "-".join(str(child_name).split()).lower()


def computed_age_years(referral):
    return age_in_whole_years(
        parse_iso(referral["child_date_of_birth"]), clock())


def screening_fee_cents(insurance_coverage_cents):
    return cents_ceil(0.025, insurance_coverage_cents)


def derive_referral_computed(referral, protocol, with_fee=True):
    referral["eligibility_alias"] = eligibility_alias(referral["child_name"])
    referral["computed_age_years"] = computed_age_years(referral)
    if with_fee:
        # PRD §3.2: the fee is recomputed *by the screen* — "An accepted screen
        # does five things at once ... It recomputes `screening_fee_cents`" — and
        # is charged on every screen attempt. A freshly submitted referral has
        # not been screened yet, so its fee is still zero.
        referral["screening_fee_cents"] = screening_fee_cents(
            int(referral.get("insurance_coverage_cents") or 0))
    referral["selector_window_days"] = min(
        int(referral["expected_treatment_days"]), DURATION_CLAMP_DAYS)
    placed_guardians = [
        placement.get("coverage_type")
        for placement in (referral.get("placed_coverages") or [])
        if placement.get("coverage_type") == "GUARDIAN"
    ]
    referral["traveling_one_to_one_codes"] = sorted(set(placed_guardians))
    referral["is_self_pay"] = not any(
        placement.get("coverage_type") == "FAMILY_PLEDGE"
        for placement in (referral.get("placed_coverages") or []))
    return referral


def is_assent_required(referral, protocol):
    age = referral["computed_age_years"]
    return age >= int(protocol["mental_capacity_floor"]) and age < 18


# =============================================================================
# Relationship helpers
# =============================================================================

def referral_for_enrollment(enrollment):
    return DB["referrals"].get(enrollment.get("referral_id"))


def protocol_for_enrollment(enrollment):
    return DB["protocols"].get(enrollment.get("protocol_id"))


def current_pledge(enrollment):
    """The enrolment's most recent ACTIVE pledge, if any."""
    pledges = [p for p in DB["pledges"].values()
               if p["enrollment_id"] == enrollment["id"] and p["status"] == "ACTIVE"]
    pledges.sort(key=lambda p: p["created_at"])
    return pledges[-1] if pledges else None


def protocol_is_frozen(protocol):
    return bool(protocol["is_protocol_held"])


# =============================================================================
# ProtocolMilestone automation (PRD §3.7)
# =============================================================================

def enrollment_milestones(enrollment):
    rows = [m for m in DB["milestones"].values()
            if m["enrollment_id"] == enrollment["id"]]
    rows.sort(key=lambda m: m["milestone_sequence"])
    return rows


def sweep_missed_milestones(enrollment):
    """A milestone still PENDING whose target_at has passed the logical clock
    becomes MISSED, and a milestone in DUE whose target_at has passed does the
    same. Enforced by the clock rather than by a caller."""
    now = clock()
    for milestone in enrollment_milestones(enrollment):
        if milestone["status"] not in ("PENDING", "DUE"):
            continue
        if parse_iso(milestone["target_at"]) < now:
            milestone["status"] = "MISSED"
            touch(milestone)


def promote_next_milestone(enrollment):
    """Promotion is automatic and strictly ordered: the lowest-sequenced milestone
    that has not been executed becomes DUE, but only once its immediate predecessor
    is already EXECUTED. A promotion is not a deferral, so deferred_from stays null.
    """
    rows = enrollment_milestones(enrollment)
    for milestone in rows:
        if milestone["status"] == "EXECUTED":
            continue
        if milestone["status"] != "PENDING":
            return None
        previous = [m for m in rows
                    if m["milestone_sequence"] < milestone["milestone_sequence"]]
        if previous:
            last = max(previous, key=lambda m: m["milestone_sequence"])
            if last["status"] != "EXECUTED":
                return None
        milestone["status"] = "DUE"
        milestone["deferred_from_milestone_id"] = None
        return milestone
    return None


def review_lock_active(protocol):
    for hold in DB["holds"].values():
        if hold["protocol_id"] != protocol["id"]:
            continue
        if hold["hold_reason"] == "IRB_REVIEW" and hold["status"] == "ESCALATED":
            return True
    return False


# =============================================================================
# Ledger / mirror recomputation
# =============================================================================

def recompute_protocol_committed(protocol):
    """committed_cents holds the money booked against the budget by active families
    (PRD §2.5, §3.6): the per-traveler-day research accrual for every DISBURSED
    travel leg on this protocol's enrollments. Recomputed after every event that
    touches the counters."""
    committed = 0
    for enrollment in DB["enrollments"].values():
        if enrollment["protocol_id"] != protocol["id"]:
            continue
        referral = referral_for_enrollment(enrollment) or {}
        for leg in DB["travel_arrangements"].values():
            if leg["enrollment_id"] != enrollment["id"]:
                continue
            if leg["status"] != "DISBURSED":
                continue
            committed += int(leg["family_day_units"]) * research_day_accrual(
                referral.get("household_state_code"))
    protocol["committed_cents"] = committed
    return recompute_protocol_derived(protocol)


def refresh_enrollment_mirrors(enrollment):
    protocol = protocol_for_enrollment(enrollment)
    if protocol is not None:
        enrollment["protocol_enrolled_count"] = int(protocol["enrolled_count"])
    active = 0
    for assignment in DB["housing_assignments"].values():
        if assignment["enrollment_id"] == enrollment["id"] and assignment["status"] == "ACTIVE":
            active += 1
            break
    for pledge in DB["pledges"].values():
        if pledge["enrollment_id"] == enrollment["id"] and pledge["status"] == "ACTIVE":
            active += 1
            break
    enrollment["active_family_count"] = active
    return enrollment


# =============================================================================
# Serialisation
#
# Every entity carries the common fields of PRD §2.10 (id, created_at, updated_at,
# version). Computed fields are materialised on the row so a read reports exactly
# the derived values the PRD fixes.
# =============================================================================

def serialize_protocol(protocol):
    # PRD §2.10: every entity declares common fields enabled, so a protocol read
    # carries `version` like any other row; the OCC token §2.11 re-asserts is that
    # same `version`. The funding-posture read additionally exposes it under the
    # name `protocol_version` (§3.1), but the row itself never drops `version`.
    recompute_protocol_derived(protocol)
    row = dict(protocol)
    row["protocol_version"] = protocol["version"]
    return row


def serialize_referral(referral):
    protocol = DB["protocols"].get(referral.get("protocol_id"))
    if protocol is not None:
        # `with_fee=False`: the fee is a screening artifact (PRD §3.2 makes the
        # screen recompute it), not a value re-derived on every read, so a read
        # never invents a fee for a referral that has not been screened.
        derive_referral_computed(referral, protocol, with_fee=False)
    return dict(referral)


def serialize_enrollment(enrollment):
    """`protocol_enrolled_count` mirrors the host protocol and `active_family_count`
    counts this enrollment's live housing occupancy or live pledge (PRD §2.4)."""
    protocol = protocol_for_enrollment(enrollment)
    if protocol is not None:
        enrollment["protocol_enrolled_count"] = int(protocol["enrolled_count"])
    active = 0
    for assignment in DB["housing_assignments"].values():
        if assignment["enrollment_id"] == enrollment["id"] and assignment["status"] == "ACTIVE":
            active += 1
            break
    for pledge in DB["pledges"].values():
        if pledge["enrollment_id"] == enrollment["id"] and pledge["status"] == "ACTIVE":
            active += 1
            break
    enrollment["active_family_count"] = active
    return dict(enrollment)


def serialize_milestone(milestone):
    """Reads reflect the automatic state of the milestone course (PRD §3.7)."""
    enrollment = DB["enrollments"].get(milestone["enrollment_id"])
    if enrollment is not None and enrollment["status"] in (
            "ACTIVE_TREATMENT", "ON_HIATUS", "SURVIVORSHIP"):
        sweep_missed_milestones(enrollment)
        promote_next_milestone(enrollment)
    return dict(milestone)


def serialize_facility(facility, recompute=True):
    if recompute:
        recompute_facility_beds(facility)
    return dict(facility)


def serialize_assignment(assignment):
    """`billed_nights` reports the inclusive night count of the window (PRD §3.4)
    and `nightly_rate_cents` is the tier rate looked up from the tier rate card."""
    assignment["billed_nights"] = billed_nights(
        assignment["start_at"], assignment["end_at"])
    assignment["nightly_rate_cents"] = NIGHTLY_RATES[assignment["assigned_tier"]]
    row = dict(assignment)
    row["is_active_occupancy"] = (
        parse_iso(assignment["start_at"]) <= clock() < parse_iso(assignment["end_at"])
        and assignment["status"] in ("SCHEDULED", "ACTIVE"))
    return row


def serialize_pledge(pledge):
    enrollment = DB["enrollments"].get(pledge["enrollment_id"])
    referral = referral_for_enrollment(enrollment) if enrollment else None
    protocol = protocol_for_enrollment(enrollment) if enrollment else None
    recompute_pledge_derived(pledge, enrollment, referral, protocol)
    return dict(pledge)


def serialize_hold(hold):
    hold["is_review_lock"] = (
        hold["hold_reason"] == "IRB_REVIEW" and hold["status"] == "ESCALATED")
    return dict(hold)


def serialize_study(study):
    return dict(study)


def serialize_survivorship_enrollment(row):
    study = DB["studies"].get(row["study_id"])
    visits = [v for v in DB["follow_ups"].values()
              if v["survivorship_enrollment_id"] == row["id"]]
    if study is not None:
        base = parse_iso(row["completed_treatment_at"])
        row["next_due_at"] = fmt(add_months(base, len(visits) * int(
            study["follow_up_interval_months"])))
        row["is_adult_follow_up"] = add_years(base, 18) <= clock()
    return dict(row)


def serialize_sibling_service(service):
    enrollment = DB["enrollments"].get(service["enrollment_id"])
    referral = referral_for_enrollment(enrollment) if enrollment else None
    state_code = (referral or {}).get("household_state_code")
    recompute_sibling_limit(service, state_code)
    return dict(service)


def serialize_travel(leg):
    """`family_day_units` is a computed figure (SCAFFOLD TravelArrangement input
    note), refreshed on every read; `transport_cost_cents` is the disbursed
    receivable on the leg, so it is only recomputed while the leg carries money."""
    referral = None
    enrollment = DB["enrollments"].get(leg["enrollment_id"])
    if enrollment is not None:
        referral = referral_for_enrollment(enrollment)
    leg["family_day_units"] = family_day_units(leg, referral or {})
    if leg["status"] != "CANCELLED":
        leg["transport_cost_cents"] = leg["family_day_units"] * resolved_per_traveler_day_cents(
            (referral or {}).get("household_state_code"))
    return dict(leg)


def serialize_ledger(ledger):
    return dict(ledger)


def serialize_clinic(clinic):
    return dict(clinic)


def serialize_agreement(agreement):
    return dict(agreement)


def serialize_service(service):
    return dict(service)


def serialize_follow_up(follow_up):
    return dict(follow_up)


# =============================================================================
# Feature B: referral screening
# =============================================================================

SCREEN_CHECKS = [
    ("ERR_AGE_OUTSIDE_PROTOCOL_RANGE", "ELIGIBILITY_AGE"),
    ("ERR_DISEASE_GROUP_MISMATCH", "ELIGIBILITY_DISEASE"),
    ("ERR_DISEASE_STAGE_MISMATCH", "ELIGIBILITY_STAGE"),
    ("ERR_PROTOCOL_CAPACITY_EXCEEDED", "CAPACITY_FULL"),
    ("ERR_PROTOCOL_BUDGET_EXHAUSTED", "BUDGET_INSUFFICIENT"),
]


def screen_check(referral, protocol):
    """Evaluate the screen preconditions in the PRD §3.2 priority order.

    Returns (error_id, decline_reason) for the first *declinable* failure, else
    (None, None). Only the five conditions the `decline_reason` enum names turn a
    screen into a DECLINED row; the other preconditions (the protocol not being
    open, and a duplicate patient alias, which has no decline_reason slot) refuse
    the call outright with their own error id.
    """
    if not (protocol["status"] == "OPEN" and not protocol_is_frozen(protocol)):
        raise ValidationFailure("ERR_PROTOCOL_NOT_OPEN", None)
    for other in DB["referrals"].values():
        if other["id"] == referral["id"]:
            continue
        if other["eligibility_alias"] != referral["eligibility_alias"]:
            continue
        if other["status"] in ("ACCEPTED", "ARRIVED"):
            raise ValidationFailure("ERR_DUPLICATE_PATIENT_ELIGIBILITY", None)
    if not (int(protocol["age_min_years"]) <= referral["computed_age_years"]
            <= int(protocol["age_max_years"])):
        return "ERR_AGE_OUTSIDE_PROTOCOL_RANGE", "ELIGIBILITY_AGE"
    if referral["disease_group"] != protocol["disease_group"]:
        return "ERR_DISEASE_GROUP_MISMATCH", "ELIGIBILITY_DISEASE"
    if referral["disease_stage"] != protocol["required_stage"]:
        return "ERR_DISEASE_STAGE_MISMATCH", "ELIGIBILITY_STAGE"
    if not int(protocol["enrolled_count"]) < int(protocol["capacity"]):
        return "ERR_PROTOCOL_CAPACITY_EXCEEDED", "CAPACITY_FULL"
    if not int(protocol["available_cents"]) > 0:
        return "ERR_PROTOCOL_BUDGET_EXHAUSTED", "BUDGET_INSUFFICIENT"
    return None, None


def apply_acceptance(referral, protocol):
    """The five side effects of an accepted screen (PRD §3.2).

    `applied_tier` is the tier the selector actually chose, so that a later booking
    can set `assigned_tier` to the same value (PRD §3.4: assigned_tier must equal
    the referral's applied_tier).

    Returns one of `"ACCEPTED"`, `"NO_HOUSING"` or `"CAPACITY_EXCEEDED"` so the
    caller can report the right refusal code: PRD §2.6's "This rule is exercised
    by referral screening" makes the endpoint capacity test a screen-time gate,
    and it outranks the fiscal gates (ERR_HOUSING_CAPACITY_EXCEEDED, priority 10,
    sorts ahead of ERR_PROTOCOL_BUDGET_EXHAUSTED at priority 16).
    """
    required_tier = required_tier_for(referral)
    pool = pick_candidates(required_tier)
    if not pool:
        referral["applied_tier"] = "DECLINED"
        return "NO_HOUSING"
    eligible = [f for f in pool
                if not (referral.get("has_febrile_neutropenia_risk")
                        and f["tier"] != "ON_CAMPUS")
                and not (referral.get("is_immunosuppressed")
                         and not f["immunosuppression_capable"])]
    if not eligible:
        referral["applied_tier"] = "DECLINED"
        return "NO_HOUSING"
    # PRD §2.6: capacity is enforced at the two endpoints of the proposed window,
    # counting the assignments in SCHEDULED or ACTIVE status whose half-open
    # window covers the instant, plus the residence's buffer_beds. A residence
    # with nothing booked yet has no endpoint occupancy, so the first screen only
    # fails here when its own bed plus the buffer already exceeds total_beds.
    facility = None
    for candidate in eligible:
        if facates_screen_capacity(candidate, referral):
            facility = candidate
            break
    if facility is None:
        referral["applied_tier"] = "DECLINED"
        return "CAPACITY_EXCEEDED"

    # PRD §3.4: `assigned_tier` must equal the referral's `applied_tier`, and the
    # booking picks the facility itself, so `applied_tier` records the residence
    # the selector chose here.
    applied_tier = facility["tier"]

    referral["applied_tier"] = applied_tier
    referral["status"] = "ACCEPTED"
    basis = reservation_basis_for(protocol, applied_tier)
    referral["reservation_basis_cents"] = basis
    protocol["reserved_cents"] = int(protocol["reserved_cents"]) + basis
    recompute_protocol_derived(protocol)
    return "ACCEPTED"


def facates_screen_capacity(facility, referral):
    """The screen-time capacity test (PRD §2.6).

    PRD §2.6: "This rule is exercised by referral screening, by housing booking
    and by re-booking." A screen has not chosen a window yet, so the test is a
    bed count: the families already accepted into this residence's tier, plus
    the family being screened, must fit in its `total_beds`. The buffer beds are
    held back from bookable inventory at the booking and re-booking gates rather
    than being subtracted twice here.
    """
    already = 0
    for other in DB["referrals"].values():
        if other.get("id") == referral.get("id"):
            continue
        if other.get("status") != "ACCEPTED":
            continue
        if other.get("applied_tier") != facility["tier"]:
            continue
        already += 1
    return already + 1 <= int(facility["total_beds"])


def apply_decline(referral, protocol, decline_reason):
    referral["status"] = "DECLINED"
    referral["decline_reason"] = decline_reason
    referral["decline_occurred_at"] = now_iso()
    referral["applied_tier"] = "DECLINED"
    referral["reservation_basis_cents"] = 0
    touch(referral)
    return referral


def revert_accepted_referrals(protocol):
    """A hold reverts every ACCEPTED referral; the revert costs nothing."""
    for referral in DB["referrals"].values():
        if referral["protocol_id"] != protocol["id"]:
            continue
        if referral["status"] != "ACCEPTED":
            continue
        referral["status"] = "SUBMITTED"
        referral["applied_tier"] = "PENDING"
        basis = int(referral.get("reservation_basis_cents") or 0)
        protocol["reserved_cents"] = int(protocol["reserved_cents"]) - basis
        referral["reservation_basis_cents"] = 0
        touch(referral)
    recompute_protocol_derived(protocol)


def release_referral_reservation(referral, protocol):
    basis = int(referral.get("reservation_basis_cents") or 0)
    if basis:
        protocol["reserved_cents"] = int(protocol["reserved_cents"]) - basis
        referral["reservation_basis_cents"] = 0
        recompute_protocol_derived(protocol)
        return True
    return False