"""Business logic services: season counters, cascades, calculations."""
import math
from datetime import timedelta

import db
from errors import (
    err, ERR_NOT_FOUND, ERR_INVALID_REQUEST, ERR_INVALID_STATE,
    ERR_SEASON_NOT_LOCKED, ERR_SEASON_HAS_OPEN_TITLES, ERR_SLATE_FULL,
    ERR_BRAND_VIOLATION, ERR_DELIVERY_LATE, ERR_NO_WRAPPED_SHOOT,
    ERR_PRODUCTION_QUOTA_EXCEEDED, ERR_LOCATION_OVERLAP, ERR_LOCATION_BLACKOUT,
    ERR_TALENT_UNAVAILABLE, ERR_PREMIERE_CADENCE_VIOLATION, ERR_AIRSLOT_OVERLAP,
    ERR_ENCORE_CAP_EXCEEDED, ERR_AIRSLOT_TOO_EARLY, ERR_STREAMING_BEFORE_PREMIERE,
    ERR_INVALID_WINDOW, ERR_AD_BUDGET_EXCEEDED, ERR_STALE_VERSION,
)
from helpers import parse_dt, now_iso


# ---------- studio scope resolution ----------

def studio_of_season(season_id):
    season = db.seasons.get(season_id)
    return season["studio_id"] if season else None


def studio_of_title(title_id):
    title = db.titles.get(title_id)
    if not title:
        return None
    return studio_of_season(title["season_id"])


def studio_of_block(block_id):
    block = db.program_blocks.get(block_id)
    if not block:
        return None
    return studio_of_season(block["season_id"])


# ---------- common serialization ----------

def serialize(entity, extra_fields):
    """Common fields + extra fields. Datetime objects already stored as ISO strings."""
    out = {
        "id": entity["id"],
        "created_at": entity["created_at"],
        "updated_at": entity["updated_at"],
        "version": entity["version"],
    }
    for f in extra_fields:
        out[f] = entity.get(f)
    return out


def bump(entity):
    entity["version"] += 1
    entity["updated_at"] = now_iso()


# ---------- season derived counters ----------

def recompute_committed_title_count(season_id):
    season = db.seasons[season_id]
    count = sum(
        1 for t in db.titles.values()
        if t["season_id"] == season_id and t["status"] in ("APPROVED", "IN_PRODUCTION", "DELIVERED")
    )
    season["committed_title_count"] = count
    return count


def recompute_booked_shoot_days(season_id):
    season = db.seasons[season_id]
    total = sum(
        s["shoot_days"] for s in db.production_slots.values()
        if s["season_id"] == season_id and s["status"] == "BOOKED"
    )
    season["booked_shoot_days"] = total
    return total


def recompute_premiered_title_count(season_id):
    season = db.seasons[season_id]
    count = sum(
        1 for a in db.air_slots.values()
        if a["season_id"] == season_id and a["kind"] == "PREMIERE" and a["status"] == "AIRED"
    )
    season["premiered_title_count"] = count
    return count


def recompute_fulfilled_pictures(deal):
    talent_id = deal["talent_id"]
    season_id = deal["season_id"]
    distinct_titles = {
        c["title_id"]
        for c in db.castings.values()
        if c["talent_id"] == talent_id
        and c["status"] == "CONFIRMED"
        and db.titles.get(c["title_id"], {}).get("season_id") == season_id
    }
    deal["fulfilled_pictures"] = len(distinct_titles)
    return deal["fulfilled_pictures"]


# ---------- sponsorship calcs ----------

DECEMBER_SPIKE_NUM = 125
DECEMBER_SPIKE_DEN = 100
AUDIT_BONUS_THRESHOLD_CENTS = 1000000
AUDIT_BONUS_CENTS = 50000


def december_spike_applies(season):
    """Half-open intersection of [air_window_start, air_window_end) with
    [year-12-01T00:00:00Z, year-12-26T00:00:00Z). Touching boundary does not count."""
    year = season["year"]
    aws = parse_dt(season["air_window_start"])
    awe = parse_dt(season["air_window_end"])
    dec_start = parse_dt(f"{year}-12-01T00:00:00Z")
    dec_end = parse_dt(f"{year}-12-26T00:00:00Z")
    # half-open intersection: aws < dec_end AND dec_start < awe
    return aws < dec_end and dec_start < awe


def compute_projected_cost(sponsorship, season):
    base = sponsorship["season_cpm_cents"] * sponsorship["viewership_thousands"]
    if december_spike_applies(season):
        return (base * DECEMBER_SPIKE_NUM) // DECEMBER_SPIKE_DEN  # floor
    return base


def compute_actual_cost(sponsorship, season):
    actual_viewership = sponsorship["viewership_thousands"] + season["premiered_title_count"]
    return sponsorship["season_cpm_cents"] * actual_viewership


# ---------- royalty calcs ----------

def compute_provisional_royalty(reported_revenue_cents, royalty_rate):
    # floor(reported * rate) — single multiplication, single floor
    return math.floor(reported_revenue_cents * royalty_rate)


def compute_trued_royalty(reported_revenue_cents, royalty_rate, provisional):
    gross = reported_revenue_cents * royalty_rate
    if reported_revenue_cents >= AUDIT_BONUS_THRESHOLD_CENTS:
        gross += AUDIT_BONUS_CENTS
    return math.floor(gross) - provisional


# ---------- availability containment ----------

def availability_containment_ok(talent, title, season):
    """Per calc availability_containment_check."""
    booked_slots = [
        s for s in db.production_slots.values()
        if s["title_id"] == title["id"] and s["status"] == "BOOKED"
    ]
    windows = talent.get("availability_windows") or []
    parsed_windows = []
    for w in windows:
        try:
            parsed_windows.append((parse_dt(w["start"]), parse_dt(w["end"])))
        except Exception:
            continue
    if booked_slots:
        # earliest slot by shoot_start, tie-break created_at ASC
        booked_slots.sort(key=lambda s: (s["shoot_start"], s["created_at"]))
        earliest = booked_slots[0]
        ss = parse_dt(earliest["shoot_start"])
        se = parse_dt(earliest["shoot_end"])
        for ws, we in parsed_windows:
            if ws <= ss and se <= we:
                return True
        return False
    else:
        deadline = parse_dt(season["delivery_deadline"])
        horizon_open = deadline - timedelta(days=365)
        for ws, we in parsed_windows:
            # window qualifies when start < deadline AND (deadline - 365d) < end
            if ws < deadline and horizon_open < we:
                return True
        return False


# ---------- cascades ----------

def cascade_title_cancel(title):
    """Cancel cascades from Title cancel."""
    season_id = title["season_id"]
    season = db.seasons[season_id]

    # hop 2: every BOOKED ProductionSlot of the title -> CANCELLED; subtract shoot_days
    for slot in list(db.production_slots.values()):
        if slot["title_id"] == title["id"] and slot["status"] == "BOOKED":
            slot["status"] = "CANCELLED"
            bump(slot)

    recompute_booked_shoot_days(season_id)

    # hop 3: every CONFIRMED Casting of the title -> RELEASED; recompute deal
    affected_deals = set()
    for casting in list(db.castings.values()):
        if casting["title_id"] == title["id"] and casting["status"] == "CONFIRMED":
            casting["status"] = "RELEASED"
            bump(casting)
            for deal in db.deals.values():
                if deal["talent_id"] == casting["talent_id"] and deal["season_id"] == season_id:
                    affected_deals.add(deal["id"])
    for deal_id in affected_deals:
        deal = db.deals[deal_id]
        recompute_fulfilled_pictures(deal)
        if deal["status"] == "FULFILLED" and deal["fulfilled_pictures"] < deal["picture_commitment"]:
            deal["status"] = "ACTIVE"
        bump(deal)

    # hop 2 (parallel): every PLANNED AirSlot of the title -> CANCELLED
    for air in list(db.air_slots.values()):
        if air["title_id"] == title["id"] and air["status"] == "PLANNED":
            air["status"] = "CANCELLED"
            bump(air)

    # hop 1: recompute committed count (quota frees)
    recompute_committed_title_count(season_id)
    bump(season)


def cascade_season_archive(season):
    """Season archive cascades."""
    season_id = season["id"]

    # hop 1: every PUBLISHED ProgramBlock -> CLOSED; cancels its PLANNED AirSlots
    for block in list(db.program_blocks.values()):
        if block["season_id"] == season_id and block["status"] == "PUBLISHED":
            block["status"] = "CLOSED"
            bump(block)
            for air in list(db.air_slots.values()):
                if air["block_id"] == block["id"] and air["status"] == "PLANNED":
                    air["status"] = "CANCELLED"
                    bump(air)

    # hop 1: every SCHEDULED StreamingWindow -> CLOSED
    for sw in list(db.streaming_windows.values()):
        if sw["season_id"] == season_id and sw["status"] == "SCHEDULED":
            sw["status"] = "CLOSED"
            bump(sw)

    # hop 2: every ACTIVE TalentDeal under-fulfilled -> BREACHED
    for deal in list(db.deals.values()):
        if deal["season_id"] == season_id and deal["status"] == "ACTIVE":
            recompute_fulfilled_pictures(deal)
            if deal["fulfilled_pictures"] < deal["picture_commitment"]:
                deal["status"] = "BREACHED"
                bump(deal)
