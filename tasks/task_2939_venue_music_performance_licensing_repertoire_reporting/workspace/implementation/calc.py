"""The calculations of PRD 3.

Every rounding step below sits exactly where the PRD puts it: three roundings
before the clamp and one after it in the annual fee (PRD 3.5), one rounding at
the very end of the rider fee and the true-up (PRD 3.2, 3.6), a per-month
instalment rounded before summing in the back-licence walk (PRD 3.9), and the
goodwill tier selected once from the pre-credit total (PRD 3.9).
"""

import db
from core import (
    FULL_COVERAGE_THRESHOLD_BP,
    LIVE_NIGHT_UPLIFT_BP,
    SEASONAL_PEAK_BP,
    SETTLEMENT_FLOOR_BP,
    TERM_DAYS,
    TIER_BASE_CENTS,
    TIER_COVER_RATE_BP,
    TIER_PER_OCCUPANT_CENTS,
    UNCOVERED_SOCIETY_PENALTY_H,
    USE_PROFILE_MULTIPLIER_BP,
    USE_TYPE_WEIGHT,
    DURATION_WEIGHT_CAP,
    FOOD_DRINK_SQFT_LIMIT,
    MAX_SPEAKERS_PER_ROOM,
    MAX_TOTAL_SPEAKERS,
    OTHER_ESTABLISHMENT_SQFT_LIMIT,
    rhu,
    whole_days,
)

# ---------------------------------------------------------------------------
# rate_schedule_selection (PRD 3.2)
# ---------------------------------------------------------------------------


def select_schedule(society_id, venue_category):
    """Top-ranked EFFECTIVE schedule for the pair, or None."""
    now = db.now()
    candidates = [
        row
        for row in db.ordered("rate_schedules")
        if row["society_id"] == society_id
        and row["venue_category"] == venue_category
        and row["status"] == "EFFECTIVE"
        and row["effective_from"] <= now
    ]
    if not candidates:
        return None
    candidates.sort(
        key=lambda row: (row["effective_from"], row["schedule_version"], row["created_at"], row["_seq"]),
        reverse=True,
    )
    return candidates[0]


def incumbent_effective(society_id, venue_category):
    """Link 1 of the publication cascade: the currently EFFECTIVE incumbent."""
    candidates = [
        row
        for row in db.ordered("rate_schedules")
        if row["society_id"] == society_id
        and row["venue_category"] == venue_category
        and row["status"] == "EFFECTIVE"
    ]
    if not candidates:
        return None
    candidates.sort(
        key=lambda row: (row["effective_from"], row["schedule_version"], row["created_at"], row["_seq"]),
        reverse=True,
    )
    return candidates[0]


# ---------------------------------------------------------------------------
# annual_license_fee (PRD 3.5)
# ---------------------------------------------------------------------------


def tier_for(occupancy):
    if occupancy <= 100:
        return 1
    if occupancy <= 300:
        return 2
    if occupancy <= 750:
        return 3
    return 4


def annual_fee(schedule, society, seating, standing, cover_revenue_cents, live_nights, use_profile):
    """The five-step derivation of PRD 3.5, shared by both variants."""
    occupancy = seating if seating >= standing else standing
    tier = tier_for(occupancy)
    adjustment_bp = schedule["adjustment_bp"]

    # Step 1 -- two schedule-adjusted components, each rounded on its own.
    base_component = rhu(TIER_BASE_CENTS[tier] * adjustment_bp, 10000)
    occupancy_component = rhu(TIER_PER_OCCUPANT_CENTS[tier] * occupancy * adjustment_bp, 10000)

    # Step 2 -- the cover component, outside the reach of adjustment_bp.
    cover_component = rhu(cover_revenue_cents * TIER_COVER_RATE_BP[tier], 10000)
    subtotal = base_component + occupancy_component + cover_component

    # Step 3 -- use profile and live-night uplift added in bp, applied once.
    nights = live_nights if live_nights <= 7 else 7
    combined_bp = USE_PROFILE_MULTIPLIER_BP[use_profile] + nights * LIVE_NIGHT_UPLIFT_BP
    scaled = rhu(subtotal * combined_bp, 10000)

    # Step 4 -- floor and ceiling, before apportionment.
    clamped = scaled
    if clamped < schedule["min_annual_fee_cents"]:
        clamped = schedule["min_annual_fee_cents"]
    if clamped > schedule["max_annual_fee_cents"]:
        clamped = schedule["max_annual_fee_cents"]

    # Step 5 -- the society's share.
    return rhu(clamped * society["repertoire_share_bp"], 10000)


def provisional_fee(schedule, society, application, license_type):
    """The provisional declared variant."""
    if license_type == "BGM_EXEMPT":
        return 0
    return annual_fee(
        schedule,
        society,
        application["declared_seating"],
        application["declared_standing"],
        application["declared_cover_revenue_cents"],
        application["declared_live_nights"],
        application["declared_music_use_profile"],
    )


def verified_fee(schedule, society, venue, license_type):
    """The final verified variant."""
    if license_type == "BGM_EXEMPT":
        return 0
    return annual_fee(
        schedule,
        society,
        venue["seating_capacity"],
        venue["standing_capacity"],
        venue["annual_cover_revenue_cents"],
        venue["weekly_live_performance_nights"],
        venue["music_use_profile"],
    )


# ---------------------------------------------------------------------------
# license_type_assignment (PRD 3.4)
# ---------------------------------------------------------------------------


def assign_license_type(venue, requested_license_type):
    if venue["bgm_exemption_status"] == "EXEMPT":
        return "BGM_EXEMPT"
    if venue["music_use_profile"] == "BACKGROUND_ONLY":
        return "BLANKET"
    if requested_license_type == "SEASONAL_EVENT" and venue["weekly_live_performance_nights"] <= 1:
        return "SEASONAL_EVENT"
    if (
        requested_license_type == "PER_PROGRAM"
        and venue["venue_category"] in ("CONCERT_HALL", "NIGHTCLUB")
        and venue["weekly_live_performance_nights"] <= 3
    ):
        return "PER_PROGRAM"
    return "BLANKET"


def reporting_required(license_type, venue):
    return license_type in ("BLANKET", "PER_PROGRAM") and venue["music_use_profile"] in (
        "LIVE_ONLY",
        "MIXED",
    )


# ---------------------------------------------------------------------------
# bgm_exemption_determination (PRD 3.3) -- first matching clause wins
# ---------------------------------------------------------------------------


def bgm_exemption(venue):
    if venue["music_use_profile"] != "BACKGROUND_ONLY":
        return "NOT_EXEMPT", "MUSIC_USE_PROFILE_INELIGIBLE"
    if venue["uses_licensed_bgm_service"]:
        return "EXEMPT", "LICENSED_SERVICE_PASSTHROUGH"
    if (
        venue["gross_square_feet"] is None
        or venue["speaker_count"] is None
        or venue["max_speakers_per_room"] is None
    ):
        return "INCONCLUSIVE", "DATA_INCOMPLETE"
    if venue["has_cover_charge"]:
        return "NOT_EXEMPT", "COVER_CHARGE_DISQUALIFIES"
    if not venue["retransmission_only"]:
        return "NOT_EXEMPT", "PERFORMANCE_NOT_RETRANSMISSION"
    limit = (
        FOOD_DRINK_SQFT_LIMIT
        if venue["venue_category"] in ("BAR_GRILL", "RESTAURANT")
        else OTHER_ESTABLISHMENT_SQFT_LIMIT
    )
    if venue["gross_square_feet"] > limit:
        return "NOT_EXEMPT", "SIZE_LIMIT_EXCEEDED"
    if (
        venue["speaker_count"] > MAX_TOTAL_SPEAKERS
        or venue["max_speakers_per_room"] > MAX_SPEAKERS_PER_ROOM
    ):
        return "NOT_EXEMPT", "SPEAKER_LIMIT_EXCEEDED"
    return "EXEMPT", "WITHIN_SIZE_AND_SPEAKER_LIMITS"


# ---------------------------------------------------------------------------
# venue_coverage_posture (PRD 2.10)
# ---------------------------------------------------------------------------


def window_contains(window, instant):
    return window["window_start"] <= instant < window["window_end"]


def license_covers_instant(license_row, instant):
    """An ACTIVE licence with at least one ACTIVE window spanning the instant."""
    if license_row["coverage_status"] != "ACTIVE":
        return False
    for window in db.windows_of_license(license_row["id"]):
        if window["status"] == "ACTIVE" and window_contains(window, instant):
            return True
    return False


def covered_share_bp(venue_id):
    now = db.now()
    society_ids = set()
    for lic in db.licenses_of_venue(venue_id):
        if license_covers_instant(lic, now):
            society_ids.add(lic["society_id"])
    total = 0
    for society_id in society_ids:
        society = db.society(society_id)
        if society is not None:
            total += society["repertoire_share_bp"]
    return total


def posture_for(share_bp):
    if share_bp >= FULL_COVERAGE_THRESHOLD_BP:
        return "FULLY_COVERED"
    if share_bp >= 1:
        return "PARTIALLY_COVERED"
    return "UNCOVERED"


# ---------------------------------------------------------------------------
# venue_ledger_balances (PRD 2.9)
# ---------------------------------------------------------------------------


def ledger_balances(venue_id):
    lifetime = 0
    outstanding = 0
    settled = 0
    voided = 0
    for row in db.assessments_of_venue(venue_id):
        amount = row["amount_cents"]
        paid = row["paid_amount_cents"]
        lifetime += amount
        settled += paid
        if row["status"] == "ISSUED":
            outstanding += amount - paid
        elif row["status"] in ("VOIDED", "SETTLED"):
            voided += amount - paid
    return {
        "lifetime_assessed_cents": lifetime,
        "outstanding_balance_cents": outstanding,
        "settled_amount_cents": settled,
        "voided_amount_cents": voided,
    }


# ---------------------------------------------------------------------------
# seasonal_rider_fee and rate_change_trueup (PRD 3.6, 3.2)
# ---------------------------------------------------------------------------


def rider_fee(annual_fee_cents, covered_day_count):
    """Single rounding at the very end (PRD 3.6)."""
    return rhu(annual_fee_cents * covered_day_count * SEASONAL_PEAK_BP, TERM_DAYS * 10000)


def trueup_amount(new_fee_cents, old_fee_cents, term_end):
    """Prorated true-up (PRD 3.2 link 3); one rounding at the end."""
    difference = new_fee_cents - old_fee_cents
    if difference <= 0:
        return 0
    days_remaining = whole_days(db.now(), term_end)
    if days_remaining <= 0:
        return 0
    return rhu(difference * days_remaining, TERM_DAYS)


# ---------------------------------------------------------------------------
# repertoire_match_selection and the two gap shares (PRD 3.8)
# ---------------------------------------------------------------------------


def _norm(text):
    return text.strip().lower()


def match_work(entry):
    """Exact title+writer equality once case and surrounding space are ignored."""
    title = _norm(entry["work_title"])
    writer = _norm(entry["writer_name"])
    candidates = [
        row
        for row in db.ordered("works")
        if _norm(row["title"]) == title and _norm(row["writer_name"]) == writer
    ]
    if not candidates:
        return None

    def rank(row):
        society = db.society(row["society_id"])
        share = society["repertoire_share_bp"] if society else 0
        code = society["society_code"] if society else ""
        # created_at ASC, then registering society's share DESC, then code ASC.
        # No insertion-order term: PRD 3.8 wants share/code to break a
        # created_at tie, and rows minted at the same logical instant tie.
        return (row["created_at"], -share, code)

    candidates.sort(key=rank)
    return candidates[0]


def entry_covered(entry, venue_id):
    affiliation = entry["society_affiliation"]
    if affiliation in ("UNAFFILIATED", "UNKNOWN"):
        return False
    instant = entry["performance_datetime"]
    for lic in db.licenses_of_venue(venue_id):
        if lic["coverage_status"] != "ACTIVE":
            continue
        society = db.society(lic["society_id"])
        if society is None or society["society_code"] != affiliation:
            continue
        for window in db.windows_of_license(lic["id"]):
            if window["status"] == "ACTIVE" and window_contains(window, instant):
                return True
    return False


def entry_weight(entry):
    seconds = entry["duration_seconds"]
    minutes = -(-seconds // 60)  # ceiling division: any part-minute counts fully
    if minutes > DURATION_WEIGHT_CAP:
        minutes = DURATION_WEIGHT_CAP
    return minutes * USE_TYPE_WEIGHT[entry["use_type"]]


def share_pct_h(flagged_weight, total_weight):
    """Weighted share as integer hundredths of a percent-point."""
    if total_weight == 0:
        return 0
    return rhu(flagged_weight * 10000, total_weight)


def gap_exposure(annual_fee_cents, uncovered_share_pct_h):
    return rhu(annual_fee_cents * uncovered_share_pct_h, 10000)


# ---------------------------------------------------------------------------
# repertoire_gap_risk_score (PRD 3.8 link 2)
# ---------------------------------------------------------------------------


def source_report_for_score(venue_id):
    """Single most recent reportable report of the venue, or None."""
    candidates = []
    for lic in db.licenses_of_venue(venue_id):
        for report in db.reports_of_license(lic["id"]):
            if report["status"] in ("SUBMITTED", "ACCEPTED"):
                candidates.append(report)
    if not candidates:
        return None
    candidates.sort(key=lambda row: (row["period_end"], row["created_at"], row["_seq"]), reverse=True)
    return candidates[0]


def gap_risk_score_h(venue_id):
    report = source_report_for_score(venue_id)
    if report is None:
        return 0
    affiliations = set()
    for entry in db.entries_of_report(report["id"]):
        if not entry["is_covered"]:
            affiliations.add(entry["society_affiliation"])
    scaled_tenths = report["uncovered_share_pct_h"] * 8 + len(affiliations) * UNCOVERED_SOCIETY_PENALTY_H * 10
    score_h = rhu(scaled_tenths, 10)
    return 10000 if score_h > 10000 else score_h


# ---------------------------------------------------------------------------
# back_license_exposure and settlement_target (PRD 3.9)
# ---------------------------------------------------------------------------


def whole_months(lookback_start, lookback_end):
    """Whole calendar months fully contained in the half-open lookback."""
    from datetime import datetime, timezone

    year, month = lookback_start.year, lookback_start.month
    first = datetime(year, month, 1, tzinfo=timezone.utc)
    if first < lookback_start:
        year, month = (year + 1, 1) if month == 12 else (year, month + 1)
    months = []
    while True:
        start = datetime(year, month, 1, tzinfo=timezone.utc)
        next_year, next_month = (year + 1, 1) if month == 12 else (year, month + 1)
        end = datetime(next_year, next_month, 1, tzinfo=timezone.utc)
        if end > lookback_end:
            break
        months.append(start)
        year, month = next_year, next_month
    return months


def month_covered(venue_id, society_id, month_start):
    """A month is covered when a non-pending licence's term contains its first instant."""
    for lic in db.licenses_of_venue(venue_id):
        if lic["society_id"] != society_id:
            continue
        if lic["coverage_status"] not in ("ACTIVE", "SUSPENDED", "EXPIRED", "TERMINATED"):
            continue
        if lic["term_start"] <= month_start < lic["term_end"]:
            return True
    return False


def penalty_rate_bp(unlicensed_month_count):
    if unlicensed_month_count <= 6:
        return 2500
    if unlicensed_month_count <= 18:
        return 5000
    return 10000


def goodwill_rate_bp(pre_credit_total_cents):
    if pre_credit_total_cents < 500000:
        return 0
    if pre_credit_total_cents < 2500000:
        return 500
    if pre_credit_total_cents < 10000000:
        return 1000
    return 1500


def settlement_waterfall(back_license_exposure_cents, unlicensed_month_count):
    penalty_cents = rhu(
        back_license_exposure_cents * penalty_rate_bp(unlicensed_month_count), 10000
    )
    pre_credit_total_cents = back_license_exposure_cents + penalty_cents
    goodwill_credit_cents = rhu(
        pre_credit_total_cents * goodwill_rate_bp(pre_credit_total_cents), 10000
    )
    settlement_total_cents = pre_credit_total_cents - goodwill_credit_cents
    settlement_floor_cents = rhu(settlement_total_cents * SETTLEMENT_FLOOR_BP, 10000)
    return {
        "penalty_cents": penalty_cents,
        "pre_credit_total_cents": pre_credit_total_cents,
        "goodwill_credit_cents": goodwill_credit_cents,
        "settlement_total_cents": settlement_total_cents,
        "settlement_floor_cents": settlement_floor_cents,
    }
