"""Every calculation rule of PRD section 3, implemented with Decimal + round-half-up."""
from datetime import timedelta
from decimal import Decimal

from core import dec, rh

# ------------------------------------------------------------------- constants
MAX_OFFSPRING_INBREEDING = Decimal("0.125")
MOLECULAR_WEIGHT = Decimal("0.40")

PROGRAM_WEIGHT = {
    "SSP_GREEN": Decimal("0.6"),
    "SSP_YELLOW": Decimal("0.8"),
    "SSP_RED": Decimal("1.0"),
    "STUDBOOK_ONLY": Decimal("0.3"),
}

GENETIC_RATE = Decimal("0.50")
HUSBANDRY_RATE = Decimal("1.125")
TRANSPORT_BASE_POINTS = Decimal("12.5")
OWNERSHIP_MULTIPLIER = {
    "OWNERSHIP_TRANSFER": Decimal("1.00"),
    "BREEDING_LOAN": Decimal("0.50"),
    "LOAN_WITH_RETAINED_OWNERSHIP": Decimal("0.65"),
}
THERMAL_PENALTY_PER_MINUTE = Decimal("0.05")

SAMPLE_INTERVAL_MINUTES = 30
MAX_EXCURSION_MINUTES = 90
QUARANTINE_MIN_DAYS_STANDARD = 30
QUARANTINE_MIN_DAYS_ENHANCED = 45

SANITATION_BUFFER_DAYS = 3
EXTENDED_SANITATION_DAYS = 14
CARRIER_OVERLAP_LIMIT = 2

MIN_CRATE_SESSIONS = 5
CRATE_RECENCY_DAYS = 14

CVI_VALIDITY_DAYS = 30
TEST_VALIDITY_DAYS = 60

SUBMISSION_GRACE_DAYS = 30
LATE_POINT_PER_DAY = Decimal("0.5")
LATE_POINT_CAP = Decimal("20")
ACCREDITATION_REVIEW_POINTS = Decimal("21.00")

AGGRESSION_POINTS = {"CALM": 0, "MINOR_AGGRESSION": 2, "SEVERE_AGGRESSION": 5}
AGGRESSION_REGRESSION_THRESHOLD = 6
MAX_REGRESSIONS = 2
MIN_SESSIONS_PER_STAGE = 3
CALM_ADVANCE_MAX = 2

MAX_NEGOTIATION_ROUNDS = 6

REQUIRED_DOCUMENTS = {
    "INTRA_JURISDICTION": [],
    "INTERSTATE": ["INTERSTATE_CVI", "STATE_IMPORT_PERMIT"],
    "INTERNATIONAL": ["INTERSTATE_CVI", "CITES_EXPORT_PERMIT", "CITES_IMPORT_PERMIT"],
}
REQUIRED_TEST_PANEL = {
    "INTRA_JURISDICTION": ["TB"],
    "INTERSTATE": ["TB", "BRUCELLA"],
    "INTERNATIONAL": ["TB", "BRUCELLA", "HERPESVIRUS", "FECAL_PARASITE"],
}

OCCUPIED_LOCATIONS = ("HELD", "IN_QUARANTINE", "AWAITING_INTRODUCTION", "INTRODUCING")
RESERVED_LOCATIONS = ("RESERVED", "IN_TRANSIT")
ACTIVE_AGREEMENT_STATUSES = ("DRAFT", "OFFERED", "COUNTERED", "ACCEPTED", "EXECUTED")
LIVE_ACCREDITATION = ("ACCREDITED", "PROVISIONAL")


def clamp(value, low, high):
    if value < low:
        return dec(low)
    if value > high:
        return dec(high)
    return value


def whole_years(birth, on_date):
    years = on_date.year - birth.year
    if (on_date.month, on_date.day) < (birth.month, birth.day):
        years -= 1
    return years


def whole_days(start, end):
    return (end - start).days


# ------------------------------------------------------------ pedigree kinship
def _parents(animal):
    return [animal.get("sire_id"), animal.get("dam_id")]


def _grandparents(animals, animal):
    out = []
    for p in _parents(animal):
        if p and p in animals:
            for gp in _parents(animals[p]):
                if gp:
                    out.append(gp)
    return out


def _siblings(animals, id_a, id_b):
    """True when a and b are full or half siblings (a null parent never matches)."""
    if not id_a or not id_b or id_a == id_b:
        return False
    a = animals.get(id_a)
    b = animals.get(id_b)
    if a is None or b is None:
        return False
    same_sire = a.get("sire_id") is not None and a.get("sire_id") == b.get("sire_id")
    same_dam = a.get("dam_id") is not None and a.get("dam_id") == b.get("dam_id")
    return bool(same_sire or same_dam)


def pedigree_kinship(animals, subject, paired):
    candidates = []
    same_sire = subject.get("sire_id") is not None and subject.get("sire_id") == paired.get("sire_id")
    same_dam = subject.get("dam_id") is not None and subject.get("dam_id") == paired.get("dam_id")
    if same_sire and same_dam:
        candidates.append(Decimal("0.2500"))
    elif same_sire != same_dam:
        candidates.append(Decimal("0.1250"))

    if paired["id"] in [p for p in _parents(subject) if p] or \
            subject["id"] in [p for p in _parents(paired) if p]:
        candidates.append(Decimal("0.2500"))

    if paired["id"] in _grandparents(animals, subject) or \
            subject["id"] in _grandparents(animals, paired):
        candidates.append(Decimal("0.1250"))

    aunt = False
    for p in _parents(subject):
        if p and _siblings(animals, paired["id"], p):
            aunt = True
    for p in _parents(paired):
        if p and _siblings(animals, subject["id"], p):
            aunt = True
    if aunt:
        candidates.append(Decimal("0.1250"))

    cousins = False
    for ps in _parents(subject):
        for pp in _parents(paired):
            if ps and pp and _siblings(animals, ps, pp):
                cousins = True
    if cousins:
        candidates.append(Decimal("0.0625"))

    return max(candidates) if candidates else Decimal("0.0000")


def projected_inbreeding(f_pedigree, analysis_mode, molecular_pct):
    if analysis_mode == "PEDIGREE_ONLY":
        return rh(f_pedigree, 4)
    pct = dec(molecular_pct if molecular_pct is not None else 0)
    blended = MOLECULAR_WEIGHT * (pct / Decimal(100)) + (Decimal(1) - MOLECULAR_WEIGHT) * f_pedigree
    return rh(blended, 4)


def pairing_verdict(recommendation_type, projected):
    if recommendation_type != "BREED_WITH":
        return "NOT_APPLICABLE"
    if projected >= MAX_OFFSPRING_INBREEDING:
        return "NOT_RECOMMENDED"
    if projected >= MAX_OFFSPRING_INBREEDING / Decimal(2):
        return "CONDITIONAL"
    return "RECOMMENDED"


# --------------------------------------------------------- demographic need index
def demographic_need(program_type, target, current_population, founder_pct, kinship):
    target_d = dec(target)
    gap_ratio = clamp(rh((target_d - dec(current_population)) / target_d, 6), 0, 1)
    founder_scarcity = rh(Decimal(1) - dec(founder_pct) / Decimal(100), 4)
    relief_kinship = dec(kinship) if kinship is not None else Decimal("0.0000")
    kinship_relief = clamp(rh(Decimal(1) - relief_kinship / MAX_OFFSPRING_INBREEDING, 4), 0, 1)
    composite = (Decimal("0.5") * gap_ratio + Decimal("0.3") * founder_scarcity
                 + Decimal("0.2") * kinship_relief)
    index = rh(PROGRAM_WEIGHT[program_type] * composite, 4)
    score = rh(index * Decimal(100), 2)
    return index, score


# ------------------------------------------------------------ credit valuation
def credit_points(genetic_value_score, age_years, transport_pct, ownership_disposition):
    genetic_component = rh(dec(genetic_value_score) * GENETIC_RATE, 2)
    husbandry_component = rh(dec(age_years) * HUSBANDRY_RATE, 2)
    transport_component = rh(TRANSPORT_BASE_POINTS * (dec(transport_pct) / Decimal(100)), 2)
    subtotal = genetic_component + husbandry_component + transport_component
    return rh(subtotal * OWNERSHIP_MULTIPLIER[ownership_disposition], 2)


def final_credit(credit, excursion_minutes):
    penalty = rh(dec(excursion_minutes) * THERMAL_PENALTY_PER_MINUTE, 2)
    value = rh(dec(credit) - penalty, 2)
    zero = Decimal("0.00")
    return value if value > zero else zero


def thermal_excursion(samples, temp_min, temp_max):
    if not samples:
        return 0
    lo = dec(temp_min)
    hi = dec(temp_max)
    out = 0
    for s in samples:
        v = dec(s)
        if v < lo or v > hi:
            out += 1
    return SAMPLE_INTERVAL_MINUTES * out


# ----------------------------------------------------------------- studbook late
def lateness(reporting_period_end, submitted_on):
    deadline = reporting_period_end + timedelta(days=SUBMISSION_GRACE_DAYS)
    days_late = whole_days(deadline, submitted_on)
    if days_late < 0:
        days_late = 0
    base = rh(dec(days_late) * LATE_POINT_PER_DAY, 2)
    if base > LATE_POINT_CAP:
        base = rh(LATE_POINT_CAP, 2)
    if base >= Decimal(15):
        multiplier = Decimal("0.40")
    elif base >= Decimal(8):
        multiplier = Decimal("0.25")
    elif base >= Decimal(3):
        multiplier = Decimal("0.10")
    else:
        multiplier = Decimal("0.00")
    surcharge = rh(base * multiplier, 2)
    total = rh(base + surcharge, 2)
    return days_late, rh(base, 2), multiplier, surcharge, total


# --------------------------------------------------------------- transfer scope
def transfer_scope(sending_code, receiving_code):
    if sending_code == receiving_code:
        return "INTRA_JURISDICTION"
    if sending_code[:2] != receiving_code[:2]:
        return "INTERNATIONAL"
    return "INTERSTATE"
