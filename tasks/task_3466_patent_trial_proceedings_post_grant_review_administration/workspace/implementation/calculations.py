"""Calculation rules (SCAFFOLD.yaml Table 3 / PRD section 3).

Every constant is taken verbatim from the scaffold. Money uses Decimal with
ROUND_HALF_UP; scores are integer points.
"""

import calendar
from datetime import timedelta
from decimal import Decimal, ROUND_HALF_UP

from db import store

# --- merits_likelihood_evaluation ---
IPR_THRESHOLD = 40
PGR_THRESHOLD = 51
AGGREGATE_MAX_WEIGHT = Decimal("0.7")
AGGREGATE_MEAN_WEIGHT = Decimal("0.3")

# --- fintiv_discretionary_score ---
FINTIV_BASE = 20
FINTIV_PROXIMITY = 40
FINTIV_INVESTMENT = 20
FINTIV_STAY_CREDIT = -20
FINTIV_DENIAL_THRESHOLD = 70
INVESTMENT_DAYS = 180
PROJECTED_FWD_DAYS = 365

# --- fwd_deadline_computation ---
FWD_BASE_DAYS = 365
FWD_EXTENSION_DAYS = 183

# --- brief_window_deadlines ---
BRIEF_WINDOWS = {
    "PO_RESPONSE": 90,
    "PETITIONER_REPLY": 132,
    "PO_SUR_REPLY": 146,
}

# --- garmin_interest_score ---
GARMIN_GRANT_THRESHOLD = 6
GARMIN_EMPTY_FACTOR_CAP = 4
GARMIN_REPLY_BONUS = 1
GARMIN_MAX = 10

# --- brief_overage_fee ---
OVERAGE_RATE_CENTS_PER_PAGE = Decimal("316.25")
PAGE_LIMITS = {"PO_RESPONSE": 90, "PETITIONER_REPLY": 45, "PO_SUR_REPLY": 20}
PAGE_CAPS = {"PO_RESPONSE": 110, "PETITIONER_REPLY": 65, "PO_SUR_REPLY": 40}

# --- petition_required_fee ---
BASE_FEE_CENTS = 1_900_000
INCLUDED_CLAIMS = 20
EXCESS_CLAIM_FEE_CENTS = 15_000

# --- petition_time_bar ---
TIME_BAR_DAYS = 365

# --- institution_window ---
INSTITUTION_WINDOW_DAYS = 93

# --- hearing_room_conflict ---
TURNOVER_BUFFER_MINUTES = 30

# --- panel_capacity ---
PANEL_LEAD_CAPACITY = 2
PANEL_ACTIVE_PHASES = {
    "INSTITUTED", "REPLY_WINDOW", "SUR_REPLY_WINDOW",
    "HEARING_PHASE", "DECISION_PHASE", "REMANDED",
}


def round_half_up(value):
    return int(Decimal(value).quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def merits_evaluation(scores, review_type):
    """Returns (merits_max_score, threshold_used, advisory_aggregate_score,
    merits_met). Operative rule: per_ground_max >= threshold."""
    merits_max = max(scores)
    threshold = IPR_THRESHOLD if review_type == "IPR" else PGR_THRESHOLD
    mean = Decimal(sum(scores)) / Decimal(len(scores))
    advisory = int((AGGREGATE_MAX_WEIGHT * merits_max
                    + AGGREGATE_MEAN_WEIGHT * mean).quantize(
                        Decimal("1"), rounding=ROUND_HALF_UP))
    return merits_max, threshold, advisory, merits_max >= threshold


def _matter_fintiv_points(matter, petition, now):
    base = FINTIV_BASE
    projected_fwd = now + timedelta(days=PROJECTED_FWD_DAYS)
    proximity = 0
    if matter.get("trial_date") is not None:
        if matter["_trial_dt"] <= projected_fwd:
            proximity = FINTIV_PROXIMITY
    delta_days = (petition["_filing_dt"] - matter["_served_dt"]).days
    investment = FINTIV_INVESTMENT if delta_days > INVESTMENT_DAYS else 0
    stay = FINTIV_STAY_CREDIT if matter["status"] == "STAYED" else 0
    total = base + proximity + investment + stay
    return max(0, min(100, total))


def fintiv_score(petition):
    """Max over qualifying matters (same patent, petitioner is defendant,
    status ACTIVE or STAYED); zero when none qualify. The proximity factor
    always compares trial_date against now + 365 days (base statutory
    deadline), never against any extended fwd_due_date."""
    now = store.clock.now()
    best = 0
    found = False
    for matter in store.matters.values():
        if matter["patent_id"] != petition["patent_id"]:
            continue
        if matter["defendant_party_id"] != petition["petitioner_id"]:
            continue
        if matter["status"] not in ("ACTIVE", "STAYED"):
            continue
        found = True
        best = max(best, _matter_fintiv_points(matter, petition, now))
    return best if found else 0


def refresh_pending_petitions_for_patent(patent_id):
    """Refresh provisional fintiv_score on petitions of this patent still in
    FILED or NOTICE_ACCORDED (PRD 3.2). Bumps petition version only when the
    stored score actually changes."""
    for petition in store.petitions.values():
        if petition["patent_id"] != patent_id:
            continue
        if petition["status"] not in ("FILED", "NOTICE_ACCORDED"):
            continue
        new_score = fintiv_score(petition)
        if new_score != petition["fintiv_score"]:
            petition["fintiv_score"] = new_score
            store.touch(petition)


def add_months(dt, months):
    """Calendar-month addition with day clamping (anniversary variant)."""
    index = (dt.year * 12 + (dt.month - 1)) + months
    year, month = index // 12, index % 12 + 1
    day = min(dt.day, calendar.monthrange(year, month)[1])
    return dt.replace(year=year, month=month, day=day)


def fwd_dates(institution_dt, extended=False):
    """Returns (fwd_due_date, advisory_anniversary_date)."""
    due = institution_dt + timedelta(days=FWD_BASE_DAYS)
    anniversary = add_months(institution_dt, 12)
    if extended:
        due += timedelta(days=FWD_EXTENSION_DAYS)
        anniversary = add_months(anniversary, 6)
    return due, anniversary


def brief_window_deadline(cycle_anchor_dt, brief_type):
    return cycle_anchor_dt + timedelta(days=BRIEF_WINDOWS[brief_type])


def garmin_score(factors, phase_at_creation):
    raw = sum(factors)
    if min(factors) == 0:
        total = min(raw, GARMIN_EMPTY_FACTOR_CAP)
    else:
        total = raw
    if phase_at_creation == "REPLY_WINDOW":
        total += GARMIN_REPLY_BONUS
    return min(total, GARMIN_MAX)


def brief_overage_fee(brief_type, page_count):
    overage_pages = max(0, page_count - PAGE_LIMITS[brief_type])
    fee = (OVERAGE_RATE_CENTS_PER_PAGE * overage_pages).quantize(
        Decimal("1"), rounding=ROUND_HALF_UP)
    return int(fee)


def petition_required_fee(num_challenged_claims):
    extra = max(0, num_challenged_claims - INCLUDED_CLAIMS)
    return BASE_FEE_CENTS + extra * EXCESS_CLAIM_FEE_CENTS


def is_time_barred(patent_id, petitioner_id, filing_dt):
    """Barred iff any matter for the patent naming the petitioner as
    defendant served its complaint strictly more than 365 days before the
    filing date. Matter status does not lift the bar."""
    for matter in store.matters.values():
        if matter["patent_id"] != patent_id:
            continue
        if matter["defendant_party_id"] != petitioner_id:
            continue
        if (filing_dt - matter["_served_dt"]).days > TIME_BAR_DAYS:
            return True
    return False


def hearing_conflicts(room_id, start_dt, end_dt, exclude_hearing_id=None):
    """Half-open [start, end) against every other SCHEDULED hearing in the
    room extended by a trailing 30-minute turnover buffer."""
    for other in store.hearings.values():
        if other["hearing_room_id"] != room_id:
            continue
        if other["status"] != "SCHEDULED":
            continue
        if exclude_hearing_id is not None and other["id"] == exclude_hearing_id:
            continue
        occ_start = other["_start_dt"]
        occ_end = other["_end_dt"] + timedelta(minutes=TURNOVER_BUFFER_MINUTES)
        if start_dt < occ_end and end_dt > occ_start:
            return True
    return False


def panel_active_load(lead_judge_user_id):
    return sum(
        1 for p in store.proceedings.values()
        if p["lead_judge_user_id"] == lead_judge_user_id
        and p["phase"] in PANEL_ACTIVE_PHASES
    )
