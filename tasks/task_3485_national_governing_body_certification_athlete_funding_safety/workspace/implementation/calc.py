"""Calculation rules (SCAFFOLD 1.3 / PRD 3)."""
from datetime import datetime
from decimal import Decimal, ROUND_HALF_UP

import db
import timeutil
from constants import (
    AGENCY_FEE_PCT, ALTERNATE_COUNT, COMMITTEE_SHARE_PCT,
    COMPLAINT_POSTURE_THRESHOLD, COMPLAINT_POSTURE_WINDOW_DAYS,
    COMPOSITE_SEASON_WEIGHT, COMPOSITE_TRIALS_WEIGHT, EVENT_MULTIPLIER,
    INSURANCE_MIN_POINTS, INSURANCE_WAIT_DAYS, NGB_SHARE_PCT, PLACING_POINTS,
    QUOTA_BONUS_SLOTS, QUOTA_BONUS_THRESHOLD, RECENCY_FULL_DAYS,
    RECENCY_HALF_WEIGHT, REMEDIATION_BONUS_CAP, SCIENCE_HOURS_CAP,
    SCORE_WEIGHT_ATHLETE_REP, SCORE_WEIGHT_FINANCIAL, SCORE_WEIGHT_GOVERNANCE,
    STIPEND_BY_TIER, TIER_A_MIN_POINTS, TIER_B_MIN_POINTS, TIER_C_MIN_POINTS,
    TRAILING_WINDOW_DAYS, TRAINING_VALIDITY_DAYS,
)

TWO_PLACES = Decimal("0.01")


def round2(value):
    return Decimal(value).quantize(TWO_PLACES, rounding=ROUND_HALF_UP)


def round_cents(value):
    return int(Decimal(value).quantize(Decimal("1"), rounding=ROUND_HALF_UP))


# --- compliance_score ---------------------------------------------------------
def provisional_score(governance, athlete_rep, financial):
    return round2(SCORE_WEIGHT_GOVERNANCE * governance
                  + SCORE_WEIGHT_ATHLETE_REP * athlete_rep
                  + SCORE_WEIGHT_FINANCIAL * financial)


def final_score_after_remediation(governance, athlete_rep, financial):
    """Lowest component +REMEDIATION_BONUS_CAP (cap 100); ties: financial
    first, then athlete_rep, then governance."""
    components = {"governance": governance, "athlete_rep": athlete_rep,
                  "financial": financial}
    lowest_value = min(components.values())
    for name in ("financial", "athlete_rep", "governance"):
        if components[name] == lowest_value:
            components[name] = min(lowest_value + REMEDIATION_BONUS_CAP,
                                   Decimal("100"))
            break
    return provisional_score(components["governance"], components["athlete_rep"],
                             components["financial"])


# --- funding_points -----------------------------------------------------------
def base_points(placing, event_grade):
    return round2(Decimal(PLACING_POINTS[placing]) * EVENT_MULTIPLIER[event_grade])


def verified_results(athlete_id):
    return [r for r in db.all_of("results")
            if r["athlete_id"] == athlete_id and r["status"] == "VERIFIED"]


def trailing_points(athlete_id, now):
    total = Decimal("0")
    for r in verified_results(athlete_id):
        age = now - r["event_date"]
        if age < timeutil.days(0) or age > timeutil.days(TRAILING_WINDOW_DAYS):
            continue
        weight = Decimal("1") if age <= timeutil.days(RECENCY_FULL_DAYS) \
            else RECENCY_HALF_WEIGHT
        total += Decimal(str(r["base_points"])) * weight
    return round2(total)


def season_points_for_year(athlete_id, year, now):
    """CALENDAR_SEASON over [Jan 1 of `year`, now]; no recency decay."""
    start = datetime(year, 1, 1, tzinfo=timeutil.UTC)
    total = Decimal("0")
    for r in verified_results(athlete_id):
        if start <= r["event_date"] <= now:
            total += Decimal(str(r["base_points"]))
    return round2(total)


def season_points(athlete_id, now):
    return season_points_for_year(athlete_id, now.year, now)


def funding_points(athlete_id, now):
    return trailing_points(athlete_id, now), season_points(athlete_id, now)


# --- tier_assignment ----------------------------------------------------------
def tier_for(points):
    if points >= TIER_A_MIN_POINTS:
        return "TIER_A"
    if points >= TIER_B_MIN_POINTS:
        return "TIER_B"
    if points >= TIER_C_MIN_POINTS:
        return "TIER_C"
    return "NONE"


def stipend_for(tier):
    return STIPEND_BY_TIER[tier]


def operative_points(agreement):
    if agreement["points_method"] == "TRAILING_365":
        return Decimal(str(agreement["trailing_points"]))
    return Decimal(str(agreement["season_points"]))


def recompute_agreement_points(agreement, now):
    """Recompute both points variants + tier + stipend (funding_points then
    tier_assignment). Marks the agreement dirty when any field moved."""
    trailing, season = funding_points(agreement["athlete_id"], now)
    tier = tier_for(operative_points(
        {**agreement, "trailing_points": trailing, "season_points": season}))
    stipend = stipend_for(tier)
    if (agreement["trailing_points"] != trailing
            or agreement["season_points"] != season
            or agreement["tier"] != tier
            or agreement["monthly_stipend_cents"] != stipend):
        agreement["trailing_points"] = trailing
        agreement["season_points"] = season
        agreement["tier"] = tier
        agreement["monthly_stipend_cents"] = stipend
        db.mark("funding_agreements", agreement)
    return agreement


# --- insurance_eligibility ----------------------------------------------------
def insurance_eligible(agreement, now):
    if operative_points(agreement) < INSURANCE_MIN_POINTS:
        return False
    activated_at = agreement.get("activated_at")
    if activated_at is None:
        return False
    return now >= activated_at + timeutil.days(INSURANCE_WAIT_DAYS)


# --- complaint_posture --------------------------------------------------------
def recompute_posture(gb, now):
    """Recount substantiated complaints in the trailing window; returns
    (old_posture, new_posture). Updates the body's computed fields."""
    count = 0
    window = timeutil.days(COMPLAINT_POSTURE_WINDOW_DAYS)
    for c in db.all_of("complaints"):
        if c["governing_body_id"] != gb["id"] or c["status"] != "SUBSTANTIATED":
            continue
        resolved_at = c.get("resolved_at")
        if resolved_at is not None and now - resolved_at <= window \
                and resolved_at <= now:
            count += 1
    posture = "ELEVATED" if count >= COMPLAINT_POSTURE_THRESHOLD else "NORMAL"
    old = gb["complaint_posture"]
    if gb["substantiated_complaint_count"] != count or old != posture:
        gb["substantiated_complaint_count"] = count
        gb["complaint_posture"] = posture
        db.mark("governing_bodies", gb)
    return old, posture


# --- science_hours_waterfall --------------------------------------------------
def run_waterfall(gb):
    pool = gb["sport_science_pool_hours"]
    athlete_gb = {a["id"]: a["governing_body_id"] for a in db.all_of("athletes")}
    agreements = [fa for fa in db.all_of("funding_agreements")
                  if athlete_gb.get(fa["athlete_id"]) == gb["id"]]
    tier_rank = {"TIER_A": 0, "TIER_B": 1, "TIER_C": 2}
    active = [fa for fa in agreements if fa["status"] == "ACTIVE"]
    epoch = datetime.min.replace(tzinfo=timeutil.UTC)
    active.sort(key=lambda fa: (tier_rank.get(fa["tier"], 3),
                                fa.get("activated_at") or epoch,
                                fa["created_at"], fa["_seq"]))
    remaining = pool
    total = 0
    for fa in active:
        cap = SCIENCE_HOURS_CAP.get(fa["tier"], 0)
        alloc = min(remaining, cap)
        if alloc < 0:
            alloc = 0
        remaining -= alloc
        total += alloc
        if fa["science_hours_allocated"] != alloc:
            fa["science_hours_allocated"] = alloc
            db.mark("funding_agreements", fa)
    for fa in agreements:
        if fa["status"] != "ACTIVE" and fa["science_hours_allocated"] != 0:
            fa["science_hours_allocated"] = 0
            db.mark("funding_agreements", fa)
    if gb["allocated_science_hours"] != total:
        gb["allocated_science_hours"] = total
        db.mark("governing_bodies", gb)


# --- quota_bonus + roster_composite_ranking -----------------------------------
def _season_points_map(proc, now):
    """Season points (calendar year of trials_end) for every athlete with a
    QUALIFIED entry on the procedure."""
    year = proc["trials_end"].year
    out = {}
    for entry in proc["entries"]:
        if entry["entry_status"] != "QUALIFIED":
            continue
        aid = entry["athlete_id"]
        out[aid] = season_points_for_year(aid, year, now)
    return out


def quota_bonus(proc, now):
    season_map = _season_points_map(proc, now)
    top3 = sorted(season_map.values(), reverse=True)[:3]
    top3_sum = sum(top3, Decimal("0"))
    applied = top3_sum >= QUOTA_BONUS_THRESHOLD
    quota_effective = proc["quota_slots"] + (QUOTA_BONUS_SLOTS if applied else 0)
    return applied, quota_effective, season_map


def training_current(athlete, now):
    completed = athlete.get("training_completed_at")
    return completed is not None and \
        now <= completed + timeutil.days(TRAINING_VALIDITY_DAYS)


def screening_clear(athlete, now):
    return athlete["screening_status"] == "SCREENING_CLEARED" \
        and athlete.get("screening_expires_at") is not None \
        and now <= athlete["screening_expires_at"]


def composite_ranking(proc, roster, now, season_map):
    """Returns ranked candidate dicts for the eligible QUALIFIED entrants."""
    candidates = []
    declined = set(roster["declined_athlete_ids"])
    for entry in proc["entries"]:
        if entry["entry_status"] != "QUALIFIED":
            continue
        aid = entry["athlete_id"]
        if aid in declined:
            continue
        athlete = db.get("athletes", aid)
        if athlete is None:
            continue
        if athlete["eligibility_status"] != "ELIGIBLE":
            continue
        if not screening_clear(athlete, now):
            continue
        if not training_current(athlete, now):
            continue
        trials_score = Decimal(str(entry["score"]))
        s_points = season_map.get(aid, Decimal("0"))
        composite = round2(COMPOSITE_TRIALS_WEIGHT * trials_score
                           + COMPOSITE_SEASON_WEIGHT * s_points)
        candidates.append({
            "athlete_id": aid,
            "composite_score": composite,
            "trials_score": entry["score"],
            "season_points": s_points,
            "_recorded": entry.get("result_recorded_at"),
            "_created": (athlete["created_at"], athlete["_seq"]),
        })
    candidates.sort(key=lambda c: (
        -c["composite_score"],
        -Decimal(str(c["trials_score"])),
        c["_recorded"] or datetime.max.replace(tzinfo=timeutil.UTC),
        c["_created"],
    ))
    return candidates


def build_slots(proc, roster, now):
    """Full selector: season points -> quota bonus -> composite ranking."""
    applied, quota_effective, season_map = quota_bonus(proc, now)
    candidates = composite_ranking(proc, roster, now, season_map)
    slots = []
    rank = 1
    for cand in candidates[:quota_effective]:
        slots.append({
            "athlete_id": cand["athlete_id"],
            "slot_type": "PRIMARY",
            "slot_status": "NOMINATED",
            "rank": rank,
            "composite_score": cand["composite_score"],
            "trials_score": cand["trials_score"],
            "season_points": cand["season_points"],
        })
        rank += 1
    for cand in candidates[quota_effective:quota_effective + ALTERNATE_COUNT]:
        slots.append({
            "athlete_id": cand["athlete_id"],
            "slot_type": "ALTERNATE",
            "slot_status": "NOMINATED",
            "rank": rank,
            "composite_score": cand["composite_score"],
            "trials_score": cand["trials_score"],
            "season_points": cand["season_points"],
        })
        rank += 1
    return applied, quota_effective, slots


# --- revenue_split -------------------------------------------------------------
def revenue_split(gross_value_cents, basis):
    gross = Decimal(gross_value_cents)
    if basis == "NET_BASIS":
        fee = round_cents(gross * AGENCY_FEE_PCT)
        base = gross - fee
    else:
        base = gross
    committee = round_cents(base * COMMITTEE_SHARE_PCT)
    ngb = round_cents(base * NGB_SHARE_PCT)
    athlete = int(base) - committee - ngb
    return committee, ngb, athlete
