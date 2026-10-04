"""Calculation rules (SCAFFOLD §1.3 / PRD §2.9, §2.10, §3).

Every formula here is pinned by the PRD: rounding modes, evaluation order,
boundary inclusivity, and variant input sets are implemented literally.
"""
from datetime import timedelta
from decimal import Decimal, ROUND_HALF_UP
from fractions import Fraction

import store

# --- Constants (SCAFFOLD §1.3 / §1.4) ---------------------------------------
FAMILY_WEIGHT = {"SANITATION": 2, "HACCP": 3, "HUMANE": 5, "LABELING": 1, "OTHER": 1}
ROLLING_WINDOW_DAYS = 90
RECENCY_BAND_1_DAYS = 30
RECENCY_BAND_2_DAYS = 60

SAMPLING_WINDOW_DAYS = 90
MIN_SAMPLES_FOR_CATEGORIZATION = 10
STANDARD_RATE = {"SALMONELLA": Fraction(10, 100), "CAMPYLOBACTER": Fraction(15, 100)}

NR_PENALTY_NUMERATOR = 10
NR_PENALTY_DENOMINATOR = 3

OPEN_NR_POINTS = 10
SUSPENSION_POINTS = 25
TIER_HIGH_MIN = 100
TIER_MEDIUM_MIN = 50
BONUS_HIGH = 15
BONUS_MEDIUM = 10
BONUS_LOW = 5

NR_ESCALATION_THRESHOLD = 3
NR_ESCALATION_WINDOW_DAYS = 90

RECALL_CLASS_REQUIREMENTS = {
    "CLASS_I": (10, Decimal("0.95")),
    "CLASS_II": (5, Decimal("0.80")),
    "CLASS_III": (4, Decimal("0.75")),
}

LABEL_DOCUMENTATION_MINIMUM = {
    "GRASS_FED": 2,
    "NO_ANTIBIOTICS": 2,
    "ORGANIC": 3,
    "BREED_SPECIFIC": 1,
}

WITHDRAWAL_ABATEMENT_DAYS = 30
WITHDRAWAL_SUSPENSION_COUNT = 2
WITHDRAWAL_SUSPENSION_WINDOW_DAYS = 365

TRAVEL_BUFFER_MINUTES = 30

OPEN_NR_STATUSES = ("OPEN", "RESPONSE_SUBMITTED", "ESCALATED", "APPEALED")
QUALIFYING_NR_STATUSES = ("OPEN", "RESPONSE_SUBMITTED", "ESCALATED")
CATEGORY_RANK = {None: 0, "CAT_1": 1, "CAT_2": 2, "CAT_3": 3}


def _within_trailing(moment, days):
    """True when `moment` lies within the trailing `days` of the logical clock
    (inclusive of the boundary day)."""
    if moment is None:
        return False
    age = (store.clock_now() - moment).total_seconds()
    return age <= days * 86400


# --- §3.2 shift coverage gap -------------------------------------------------

def coverage_gap_minutes(window, statuses):
    """Interval-merge gap per line, summed (SCAFFOLD shift_coverage_gap).

    Half-open [start, end) intervals; adjacency (end == next start) leaves zero
    uncovered minutes. `statuses` selects the variant input set.
    """
    total_seconds = int((window["end_utc"] - window["start_utc"]).total_seconds())
    gap_seconds = 0
    for line in range(1, int(window["planned_line_count"]) + 1):
        intervals = []
        for a in store.all_of("shift_assignments"):
            if (
                a["shift_window_id"] == window["id"]
                and a["line_index"] == line
                and a["status"] in statuses
            ):
                s = max(a["start_utc"], window["start_utc"])
                e = min(a["end_utc"], window["end_utc"])
                if s < e:
                    intervals.append((s, e))
        intervals.sort()
        covered = 0
        cur_s = cur_e = None
        for s, e in intervals:
            if cur_s is None:
                cur_s, cur_e = s, e
            elif s <= cur_e:  # overlaps or is adjacent (half-open continuity)
                cur_e = max(cur_e, e)
            else:
                covered += int((cur_e - cur_s).total_seconds())
                cur_s, cur_e = s, e
        if cur_s is not None:
            covered += int((cur_e - cur_s).total_seconds())
        gap_seconds += max(0, total_seconds - covered)
    return gap_seconds // 60


# --- §2.10 derived establishment scores --------------------------------------

def open_nr_count(establishment_id):
    return sum(
        1
        for nr in store.all_of("noncompliance_records")
        if nr["establishment_id"] == establishment_id and nr["status"] in OPEN_NR_STATUSES
    )


def suspension_count(establishment_id):
    """Lifetime count of SUSPENSION actions that reached IN_EFFECT."""
    return sum(
        1
        for a in store.all_of("enforcement_actions")
        if a["establishment_id"] == establishment_id
        and a["action_type"] == "SUSPENSION"
        and a["status"] in ("IN_EFFECT", "LIFTED")
    )


def compliance_score(establishment_id):
    """Pinned nested rounding: round each family penalty to 0.1 FIRST, then
    subtract the sum of the ROUNDED penalties from 100 (exact, unrounded)."""
    total = Decimal("0.0")
    for family in ("SANITATION", "HACCP", "HUMANE"):
        open_f = sum(
            1
            for nr in store.all_of("noncompliance_records")
            if nr["establishment_id"] == establishment_id
            and nr["regulation_family"] == family
            and nr["status"] in OPEN_NR_STATUSES
        )
        raw = (
            Decimal(open_f)
            * Decimal(NR_PENALTY_NUMERATOR)
            / Decimal(NR_PENALTY_DENOMINATOR)
        )
        total += raw.quantize(Decimal("0.1"), rounding=ROUND_HALF_UP)
    score = Decimal(100) - total
    return float(score)


def enforcement_priority_score(establishment_id):
    """Pinned order: base from CURRENT fields; tier from base ALONE; then add."""
    base = (
        OPEN_NR_POINTS * open_nr_count(establishment_id)
        + SUSPENSION_POINTS * suspension_count(establishment_id)
    )
    if base >= TIER_HIGH_MIN:
        bonus = BONUS_HIGH
    elif base >= TIER_MEDIUM_MIN:
        bonus = BONUS_MEDIUM
    else:
        bonus = BONUS_LOW
    return base + bonus


def rolling_risk_score(establishment_id):
    total = 0
    for nr in store.all_of("noncompliance_records"):
        if nr["establishment_id"] != establishment_id or nr["status"] not in OPEN_NR_STATUSES:
            continue
        if not _within_trailing(nr["issued_at"], ROLLING_WINDOW_DAYS):
            continue
        age_days = (store.clock_now() - nr["issued_at"]).total_seconds() / 86400.0
        if age_days <= RECENCY_BAND_1_DAYS:
            factor = 3
        elif age_days <= RECENCY_BAND_2_DAYS:
            factor = 2
        else:
            factor = 1
        total += FAMILY_WEIGHT[nr["regulation_family"]] * factor
    return total


def lifetime_risk_score(establishment_id):
    return sum(
        FAMILY_WEIGHT[nr["regulation_family"]]
        for nr in store.all_of("noncompliance_records")
        if nr["establishment_id"] == establishment_id and nr["status"] != "VACATED"
    )


# --- §3.6 pathogen categorization --------------------------------------------

def pathogen_category_map(establishment_id):
    """Per-pathogen category over resulted samples in the trailing window.

    Rates are exact rationals; boundaries are pinned: rate == standard is
    CAT_2 (<=), rate == half the standard is CAT_1 (<=).
    """
    result = {}
    for pathogen in ("SALMONELLA", "CAMPYLOBACTER"):
        resulted = [
            s
            for s in store.all_of("pathogen_samples")
            if s["establishment_id"] == establishment_id
            and s["pathogen"] == pathogen
            and s["result"] in ("POSITIVE", "NEGATIVE")
            and _within_trailing(s["resulted_at"], SAMPLING_WINDOW_DAYS)
        ]
        if len(resulted) < MIN_SAMPLES_FOR_CATEGORIZATION:
            result[pathogen] = None
            continue
        positives = sum(1 for s in resulted if s["result"] == "POSITIVE")
        rate = Fraction(positives, len(resulted))
        standard = STANDARD_RATE[pathogen]
        if rate <= standard / 2:
            result[pathogen] = "CAT_1"
        elif rate <= standard:
            result[pathogen] = "CAT_2"
        else:
            result[pathogen] = "CAT_3"
    return result


def worst_category(category_map):
    worst = None
    for cat in category_map.values():
        if CATEGORY_RANK[cat] > CATEGORY_RANK[worst]:
            worst = cat
    return worst


# --- §3.3 / §3.4 enforcement gates -------------------------------------------

def qualifying_nr_count(establishment_id, family):
    """NRs of the establishment in one family, status OPEN/RESPONSE_SUBMITTED/
    ESCALATED (APPEALED and VACATED excluded), issued within the trailing
    NR_ESCALATION_WINDOW_DAYS inclusive of the boundary day."""
    if family is None:
        return 0
    return sum(
        1
        for nr in store.all_of("noncompliance_records")
        if nr["establishment_id"] == establishment_id
        and nr["regulation_family"] == family
        and nr["status"] in QUALIFYING_NR_STATUSES
        and _within_trailing(nr["issued_at"], NR_ESCALATION_WINDOW_DAYS)
    )


def has_confirmed_egregious(establishment_id):
    return any(
        e["establishment_id"] == establishment_id
        and e["severity"] == "EGREGIOUS"
        and e["status"] == "CONFIRMED"
        for e in store.all_of("humane_events")
    )


def enforcement_eligible(action_type, basis, regulation_family, establishment_id, establishment):
    """Basis eligibility per PRD §3.4, evaluated at create AND re-evaluated at
    activate. Returns (ok, error_pair)."""
    from errors import ERR_ESCALATION_THRESHOLD_NOT_MET, ERR_WITHDRAWAL_CONDITIONS_NOT_MET

    if action_type == "NOTICE_OF_INTENDED_ENFORCEMENT":
        return True, None

    if action_type == "WITHHOLD_MARKS":
        ok = (
            basis == "ADMINISTRATIVE"
            or qualifying_nr_count(establishment_id, regulation_family) >= 1
            or has_confirmed_egregious(establishment_id)
            or establishment.get("pathogen_category") == "CAT_3"
        )
        return (True, None) if ok else (False, ERR_ESCALATION_THRESHOLD_NOT_MET)

    if action_type == "SUSPENSION":
        if basis == "NR_LINKAGE":
            ok = (
                qualifying_nr_count(establishment_id, regulation_family)
                >= NR_ESCALATION_THRESHOLD
            )
        elif basis == "EGREGIOUS_HUMANE":
            ok = has_confirmed_egregious(establishment_id)
        elif basis == "CATEGORY_3_PATHOGEN":
            ok = establishment.get("pathogen_category") == "CAT_3"
        else:  # ADMINISTRATIVE is never an eligible basis for suspension
            ok = False
        return (True, None) if ok else (False, ERR_ESCALATION_THRESHOLD_NOT_MET)

    if action_type == "WITHDRAWAL":
        now = store.clock_now()
        abatement_ok = any(
            a["establishment_id"] == establishment_id
            and a["action_type"] == "SUSPENSION"
            and a["status"] == "IN_EFFECT"
            and a.get("effective_at") is not None
            and a["effective_at"] <= now - timedelta(days=WITHDRAWAL_ABATEMENT_DAYS)
            for a in store.all_of("enforcement_actions")
        )
        recent_suspensions = sum(
            1
            for a in store.all_of("enforcement_actions")
            if a["establishment_id"] == establishment_id
            and a["action_type"] == "SUSPENSION"
            and a["status"] in ("IN_EFFECT", "LIFTED")
            and _within_trailing(a["created_at"], WITHDRAWAL_SUSPENSION_WINDOW_DAYS)
        )
        ok = abatement_ok or recent_suspensions >= WITHDRAWAL_SUSPENSION_COUNT
        return (True, None) if ok else (False, ERR_WITHDRAWAL_CONDITIONS_NOT_MET)

    return False, ERR_ESCALATION_THRESHOLD_NOT_MET


# --- §3.7 / §3.8 small thresholds ---------------------------------------------

def effectiveness_ratio(checks_effective, checks_performed):
    """round_half_up(effective / performed, 2); None when no checks recorded."""
    if not checks_performed:
        return None
    ratio = (Decimal(checks_effective) / Decimal(checks_performed)).quantize(
        Decimal("0.01"), rounding=ROUND_HALF_UP
    )
    return ratio
