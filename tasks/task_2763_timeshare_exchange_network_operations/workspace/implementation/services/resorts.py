"""Resort derived state: quality ladder, inventory counters, obligation shortfall."""

import calc
from store import (db, touch, parse_date, add_days, format_date,
                   OCCUPANCY_NIGHTS_PER_DEPOSIT, COUNTED_DEPOSIT_STATUSES,
                   AFFILIATION_YEAR_DAYS)


def reviews_of(resort_id):
    rows = [r for r in db.resort_quality_reviews.values() if r["resort_id"] == resort_id]
    return sorted(rows, key=lambda r: (r["created_at"], r["_seq"]))


def review_window(resort_id):
    """Reviews ordered created_at DESC, first eight, plus every row tied at the eighth."""
    rows = sorted(reviews_of(resort_id), key=lambda r: (r["created_at"], r["_seq"]), reverse=True)
    if len(rows) <= calc.REVIEW_WINDOW_SIZE:
        return rows
    cutoff = rows[calc.REVIEW_WINDOW_SIZE - 1]["created_at"]
    return [row for row in rows if row["created_at"] >= cutoff]


def recompute_quality(resort):
    """quality_score, review_count and the notch-shifted effective quality_rating."""
    rows = reviews_of(resort["id"])
    resort["review_count"] = len(rows)
    if len(rows) < calc.MIN_REVIEWS_FOR_SCORE:
        resort["quality_score"] = None
        scored_rating = resort["initial_quality_rating"]
    else:
        window = review_window(resort["id"])
        score = calc.mean_composite([row["composite_score"] for row in window])
        resort["quality_score"] = float(score)
        scored_rating = calc.score_band(score)
    resort["quality_rating"] = calc.shift_ladder(scored_rating, resort["downgrade_notches"])


def deposits_of(resort_id):
    return [d for d in db.deposits.values() if d["resort_id"] == resort_id]


def sync_inventory(resort):
    """deposits_committed_count and committed_nights (invariant INV_NIGHTS)."""
    count = 0
    for deposit in deposits_of(resort["id"]):
        if deposit["deposit_status"] in COUNTED_DEPOSIT_STATUSES:
            count += 1
    changed = (resort["deposits_committed_count"] != count
               or resort["committed_nights"] != count * OCCUPANCY_NIGHTS_PER_DEPOSIT)
    resort["deposits_committed_count"] = count
    resort["committed_nights"] = count * OCCUPANCY_NIGHTS_PER_DEPOSIT
    if changed:
        touch(resort)
    return changed


def affiliation_year(resort):
    if not resort.get("affiliated_on"):
        return None, None
    start = parse_date(resort["affiliated_on"][:10])
    return start, add_days(start, AFFILIATION_YEAR_DAYS)


def compliance_report(resort):
    start, end = affiliation_year(resort)
    obligation = resort["required_annual_deposit_units"]
    counted_stay = 0
    counted_filed = 0
    if start is not None:
        for deposit in deposits_of(resort["id"]):
            if deposit["deposit_status"] not in COUNTED_DEPOSIT_STATUSES:
                continue
            stay_day = parse_date(deposit["check_in_date"])
            filed_day = parse_date(deposit["created_at"][:10])
            if stay_day is not None and start <= stay_day < end:
                counted_stay += 1
            if filed_day is not None and start <= filed_day < end:
                counted_filed += 1
    return {
        "resort_id": resort["id"],
        "affiliation_year_start": format_date(start),
        "affiliation_year_end": format_date(end),
        "obligation_units": obligation,
        "deposits_committed_count": resort["deposits_committed_count"],
        "committed_nights": resort["committed_nights"],
        "counted_by_stay_year": counted_stay,
        "counted_by_deposit_date": counted_filed,
        "shortfall_by_stay_year": max(0, obligation - counted_stay),
        "shortfall_by_deposit_date": max(0, obligation - counted_filed),
    }


def shortfall_by_stay_year(resort):
    """The authoritative variant -- the only one that may drive a state change."""
    return compliance_report(resort)["shortfall_by_stay_year"]


def apply_complaint_strike(resort):
    """An upheld RESORT_QUALITY dispute: strike, and on the second one downgrade."""
    resort["complaint_strikes"] = resort["complaint_strikes"] + 1
    downgraded = False
    if resort["complaint_strikes"] >= calc.COMPLAINT_STRIKE_THRESHOLD:
        resort["complaint_strikes"] = 0
        resort["downgrade_notches"] = min(3, resort["downgrade_notches"] + 1)
        recompute_quality(resort)
        downgraded = True
        if resort["affiliation_status"] == "ACTIVE":
            resort["affiliation_status"] = "PROBATION"
    touch(resort)
    return downgraded
