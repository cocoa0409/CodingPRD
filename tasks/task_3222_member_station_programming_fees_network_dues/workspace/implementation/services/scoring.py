"""station_operations_score, membership_class_assignment, standings, ack rule."""
import re

from core import config as C

WEIGHT_COVERAGE = C.d("0.40")
WEIGHT_STAFFING = C.d("0.35")
WEIGHT_NEWSROOM = C.d("0.25")
COVERAGE_STEP = 100000
COVERAGE_PER_STEP = 9
STAFFING_PER_FTE = 5
NEWSROOM_PER_FTE = 10
INDEX_CAP = 100

HOUSEHOLD_STEP = 50000
HOUSEHOLD_PER_STEP = 5

CLASS_A_SCORE_MIN = C.d("75.00")
CLASS_A_HOUSEHOLD_MIN = 45
CLASS_B_SCORE_MIN = C.d("60.00")
CLASS_B_HOUSEHOLD_MIN = 30
CLASS_C_SCORE_MIN = C.d("45.00")
CLASS_C_HOUSEHOLD_MIN = 15

CLASS_ORDER = ["CLASS_A", "CLASS_B", "CLASS_C", "CLASS_D"]

MATCH_BUDGET_PER_STATION_CENTS = 450000
EFFICIENCY_FLOOR_BPS = 8000


def coverage_index(coverage_population):
    """Nine points per whole one-hundred-thousand-person step begun, capped."""
    steps = int(C.d(coverage_population or 0) // COVERAGE_STEP)
    return min(INDEX_CAP, steps * COVERAGE_PER_STEP)


def staffing_index(full_time_staff_count):
    return min(INDEX_CAP, int(full_time_staff_count or 0) * STAFFING_PER_FTE)


def newsroom_index(newsroom_staff_count):
    return min(INDEX_CAP, int(newsroom_staff_count or 0) * NEWSROOM_PER_FTE)


def households_index(dma_households):
    """Five points per whole fifty-thousand-household step begun, capped."""
    steps = int(C.d(dma_households or 0) // HOUSEHOLD_STEP)
    return min(INDEX_CAP, steps * HOUSEHOLD_PER_STEP)


def operations_score(station):
    """Weighted score; each index is capped BEFORE the weights are applied."""
    ci = coverage_index(station.get("coverage_population"))
    si = staffing_index(station.get("full_time_staff_count"))
    ni = newsroom_index(station.get("newsroom_staff_count"))
    raw = WEIGHT_COVERAGE * ci + WEIGHT_STAFFING * si + WEIGHT_NEWSROOM * ni
    return C.round2(raw)


def membership_class(station, score=None):
    """The gate ladder is evaluated in order; the first passing gate wins."""
    if score is None:
        score = operations_score(station)
    score = C.round2(score)
    hi = households_index(station.get("dma_households"))
    if score >= CLASS_A_SCORE_MIN and hi >= CLASS_A_HOUSEHOLD_MIN:
        return "CLASS_A"
    if score >= CLASS_B_SCORE_MIN and hi >= CLASS_B_HOUSEHOLD_MIN:
        return "CLASS_B"
    if score >= CLASS_C_SCORE_MIN and hi >= CLASS_C_HOUSEHOLD_MIN:
        return "CLASS_C"
    return "CLASS_D"


def recompute_station_derived(station):
    """Re-derive operations_score and membership_class in place."""
    score = operations_score(station)
    station["operations_score"] = float(score)
    station["_operations_score_exact"] = str(score)
    station["membership_class"] = membership_class(station, score)
    return station


# --- member_station_standings -------------------------------------------------
def ranking_key(station):
    """(arrears DESC, score DESC, class ASC, created_at ASC) as a sortable tuple."""
    cls = station.get("membership_class") or "CLASS_D"
    try:
        cls_rank = CLASS_ORDER.index(cls)
    except ValueError:
        cls_rank = len(CLASS_ORDER)
    return (
        -int(station.get("dues_arrears_cents") or 0),
        -float(station.get("operations_score") or 0),
        cls_rank,
        station.get("created_at") or "",
    )


def standings(store):
    """Dense-ranked standings of stations that are ELIGIBLE and vote-eligible."""
    from core.store import projection_eligible
    rows = []
    for st in store.member_stations.values():
        if st.get("eligibility_status") != "ELIGIBLE":
            continue
        if not projection_eligible(st):
            continue
        rows.append(st)
    rows.sort(key=ranking_key)
    keys = [ranking_key(r) for r in rows]
    out = []
    for idx, rec in enumerate(rows):
        key = keys[idx]
        rank = len({k for k in keys if k < key}) + 1
        out.append((rec, rank))
    return out


# --- underwriting_acknowledgment_check ---------------------------------------
FORBIDDEN_PHRASES = [
    "best", "cheapest", "lowest price", "guarantee", "free", "sale",
    "bestseller", "recommend",
]
COMPARATIVE_TOKENS = ["better than", "outperforms", "cheaper than"]
CALL_TO_ACTION_TOKENS = ["call now", "visit today", "buy"]
MAX_ACK_WORDS = 30
VIOLATION_ORDER = [
    "SUPERLATIVE", "COMPARATIVE", "PRICE_INVITATION", "CALL_TO_ACTION", "LENGTH",
]


def _has_phrase(text_lower, phrase):
    pattern = r"(?<![A-Za-z0-9])" + re.escape(phrase) + r"(?![A-Za-z0-9])"
    return re.search(pattern, text_lower) is not None


def acknowledgment_violation(script):
    """The FIRST violation in VIOLATION_ORDER, or None when the script passes."""
    text = script if isinstance(script, str) else ""
    low = text.lower()
    for phrase in FORBIDDEN_PHRASES:
        if _has_phrase(low, phrase):
            return "SUPERLATIVE"
    for token in COMPARATIVE_TOKENS:
        if _has_phrase(low, token):
            return "COMPARATIVE"
    if _has_phrase(low, "price") or "$" in text:
        return "PRICE_INVITATION"
    for token in CALL_TO_ACTION_TOKENS:
        if _has_phrase(low, token):
            return "CALL_TO_ACTION"
    if len(text.split()) > MAX_ACK_WORDS:
        return "LENGTH"
    return None


def acknowledgment_passes(script):
    return acknowledgment_violation(script) is None