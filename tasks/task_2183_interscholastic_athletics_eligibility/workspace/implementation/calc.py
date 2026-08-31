"""All calculation rules from the PRD, implemented exactly as pinned."""
from datetime import timedelta, datetime, date
from decimal import Decimal

from core import (
    DB, UTC, dec, rhu, rhu_int, now, now_date, fail,
)

# ---- constants -------------------------------------------------------------
ACADEMIC_MIN_GPA = Decimal("2.000")
AGE_LIMIT_YEARS = 19
TRANSFER_SITOUT_DAYS = 365

SPORT_TIER_BASE_CENTS = {"TIER_A": 12345, "TIER_B": 8975, "TIER_C": 6499}
MULTI_SPORT_DISCOUNT_PCT = [Decimal("0.00"), Decimal("0.25"), Decimal("0.40")]
FRL_REDUCTION_PCT = Decimal("0.50")

POWER_OWN_WEIGHT = Decimal("0.65")
POWER_SOS_WEIGHT = Decimal("0.35")

ROLLING_WINDOW_DAYS = 7
MAX_CONTESTS_PER_WINDOW = 3

CERT_BASE_CENTS = {"LEVEL_1": 4000, "LEVEL_2": 6000, "LEVEL_3": 8500}
TIER_MULTIPLIER = {"TIER_A": Decimal("1.25"), "TIER_B": Decimal("1.00"), "TIER_C": Decimal("0.85")}
MILEAGE_CAP_MILES = Decimal("120")
MILEAGE_RATE_CENTS = Decimal("62")
NIGHT_HOUR_UTC = 23
NIGHT_SURCHARGE_CENTS = 1500
PLAYOFF_PCT = Decimal("0.20")
PLAYOFF_FLOOR_CENTS = 2500

RTP_INITIAL_REST_HOURS = 48
RTP_STAGE_MIN_HOURS = 24
RTP_MIN_TOTAL_HOURS = 144

PREGAME_BUFFER_MIN = 75
POSTGAME_BUFFER_MIN = 30

OFFICIAL_TRAVEL_BUFFER_MIN = 90
VENUE_TURNOVER_MIN = 60

MIN_BRACKET_SCHOOLS = 4
SANCTION_PROBATION_THRESHOLD = 2
SANCTION_SUSPENSION_THRESHOLD = 4
FORFEIT_WIN_SCORE = 1
FORFEIT_LOSS_SCORE = 0
MAX_APPEALS = 2

DOC_TYPES_REQUIRED = ["PHYSICAL", "PARENT_CONSENT", "CONCUSSION_ACK"]


# ---------------------------------------------------------------------------
# date helpers
# ---------------------------------------------------------------------------
def whole_years_between(birth, cutoff):
    years = cutoff.year - birth.year
    if (cutoff.month, cutoff.day) < (birth.month, birth.day):
        years -= 1
    return years


def whole_days_between(start, end):
    """Calendar-day difference over UTC dates: counts start, excludes end."""
    return (end - start).days


# ---------------------------------------------------------------------------
# academic_gpa_evaluation
# ---------------------------------------------------------------------------
def academic_gpa_evaluation(student, season):
    """Returns (variant, effective_gpa Decimal at 3dp)."""
    if now_date() < season["grading_lock_date"]:
        gpa = student["gpa_prior_period"]
        eff = rhu(dec(gpa if gpa is not None else 0), 3)
        return "PROVISIONAL", eff
    denom = int(student["credits_prior_period"] or 0) + int(student["credits_current_period"] or 0)
    if denom == 0:
        return "FINAL", rhu(Decimal("0"), 3)
    gp = dec(student["gpa_prior_period"] if student["gpa_prior_period"] is not None else 0)
    gc = dec(student["gpa_current_period"] if student["gpa_current_period"] is not None else 0)
    numer = (gp * Decimal(int(student["credits_prior_period"] or 0))) + \
            (gc * Decimal(int(student["credits_current_period"] or 0)))
    return "FINAL", rhu(numer / Decimal(denom), 3)


# ---------------------------------------------------------------------------
# eligibility_ladder_evaluation
# ---------------------------------------------------------------------------
def eligibility_ladder_evaluation(case, student, season, effective_gpa):
    """Strict precedence; returns the first failing rung or None."""
    # RUNG 1 - AGE
    if whole_years_between(student["birth_date"], season["age_cutoff_date"]) >= AGE_LIMIT_YEARS:
        return "AGE_LIMIT"
    # RUNG 2 - RESIDENCY
    if (not student["residency_verified"]) or (student["residency_verified_on"] is None) \
            or (student["residency_verified_on"] > season["residency_deadline"]):
        return "RESIDENCY_UNVERIFIED"
    # RUNG 3 - TRANSFER
    if student["previous_school_id"] is not None:
        if not student["hardship_waiver_granted"]:
            td = student["transfer_date"]
            if td is None:
                return "TRANSFER_SITOUT"
            if whole_days_between(td, season["first_contest_date"]) < TRANSFER_SITOUT_DAYS:
                return "TRANSFER_SITOUT"
    # RUNG 4 - DOCUMENTS
    today = now_date()
    docs = [d for d in DB.documents.values() if d["eligibility_case_id"] == case["id"]]
    for t in DOC_TYPES_REQUIRED:
        if not any(d["doc_type"] == t and d["expires_on"] >= today for d in docs):
            return "DOCS_INCOMPLETE"
    # RUNG 5 - ACADEMIC
    if effective_gpa < ACADEMIC_MIN_GPA:
        return "ACADEMIC_GPA"
    return None


# ---------------------------------------------------------------------------
# participation_fee_assessment
# ---------------------------------------------------------------------------
def participation_fee_assessment(student, season, school):
    """Returns fee_amount_cents (int)."""
    base = Decimal(SPORT_TIER_BASE_CENTS[season["sport_tier"]])
    priors = []
    for c in DB.cases.values():
        if c["student_id"] != student["id"]:
            continue
        s = DB.seasons.get(c["sport_season_id"])
        if s is None or s["school_year"] != season["school_year"]:
            continue
        if c["fee_status"] == "REFUNDED":
            continue
        priors.append(c)
    priors.sort(key=lambda r: (r["created_at"], r["_seq"]))
    prior_case_count = len(priors)
    discount = MULTI_SPORT_DISCOUNT_PCT[min(prior_case_count, 2)]
    line_cents = rhu_int(base * (Decimal(1) - discount))              # ROUND #1
    if student["free_reduced_lunch"]:
        line_cents = rhu_int(Decimal(line_cents) * (Decimal(1) - FRL_REDUCTION_PCT))  # ROUND #2
    family_prior_total = sum(c["fee_amount_cents"] for c in priors)
    headroom = int(school["fee_cap_cents"]) - int(family_prior_total)
    return max(0, min(int(line_cents), headroom))


# ---------------------------------------------------------------------------
# officials_travel_stipend
# ---------------------------------------------------------------------------
def officials_travel_stipend(official, contest, season):
    base = Decimal(CERT_BASE_CENTS[official["certification_level"]])
    tier_mult = TIER_MULTIPLIER[season["sport_tier"]]
    capped_miles = min(dec(contest["travel_miles"]), MILEAGE_CAP_MILES)
    mileage_cents = rhu_int(capped_miles * MILEAGE_RATE_CENTS)
    night_cents = NIGHT_SURCHARGE_CENTS if contest["starts_at"].astimezone(UTC).hour >= NIGHT_HOUR_UTC else 0
    playoff_cents = 0
    if contest["is_playoff"]:
        playoff_cents = max(PLAYOFF_FLOOR_CENTS, rhu_int(base * PLAYOFF_PCT))
    return rhu_int(base * tier_mult) + mileage_cents + night_cents + playoff_cents


# ---------------------------------------------------------------------------
# transport_release_window
# ---------------------------------------------------------------------------
def transport_release_window(contest, school, travel_minutes):
    depart_at = contest["starts_at"] - timedelta(minutes=travel_minutes + PREGAME_BUFFER_MIN)
    return_at = contest["ends_at"] + timedelta(minutes=travel_minutes + POSTGAME_BUFFER_MIN)
    hh, mm = school["school_day_end_utc_hhmm"].split(":")
    d = depart_at.astimezone(UTC).date()
    school_day_end = datetime(d.year, d.month, d.day, int(hh), int(mm), tzinfo=UTC)
    delta_min = int((school_day_end - depart_at).total_seconds() // 60) \
        if (school_day_end - depart_at).total_seconds() >= 0 \
        else -int((depart_at - school_day_end).total_seconds() // 60)
    release_minutes = max(0, delta_min)
    return depart_at, return_at, release_minutes


# ---------------------------------------------------------------------------
# fleet_capacity_overlap
# ---------------------------------------------------------------------------
def fleet_capacity_overlap(trip, school):
    committed = 0
    for t in DB.transports.values():
        if t["id"] == trip["id"]:
            continue
        if t["requesting_school_id"] != school["id"]:
            continue
        if t["status"] not in ("APPROVED", "COMPLETED"):
            continue
        if t["return_at"] < trip["depart_at"] or t["depart_at"] > trip["return_at"]:
            continue
        committed += t["bus_count"]
    return (committed + trip["bus_count"]) <= school["bus_fleet_size"]


# ---------------------------------------------------------------------------
# official_double_booking_overlap
# ---------------------------------------------------------------------------
def _buffered(contest):
    return (contest["starts_at"] - timedelta(minutes=OFFICIAL_TRAVEL_BUFFER_MIN),
            contest["ends_at"] + timedelta(minutes=OFFICIAL_TRAVEL_BUFFER_MIN))


def official_double_booking_overlap(official, contest):
    b_lo, b_hi = _buffered(contest)
    for a in DB.assignments.values():
        if a["official_id"] != official["id"]:
            continue
        if a["status"] not in ("OFFERED", "ACCEPTED"):
            continue
        held = DB.contests.get(a["contest_id"])
        if held is None:
            continue
        a_lo, a_hi = _buffered(held)
        if a_lo < b_hi and b_lo < a_hi:
            return False
    return True


# ---------------------------------------------------------------------------
# venue_turnover_overlap
# ---------------------------------------------------------------------------
def venue_turnover_overlap(home_school, starts_at, ends_at):
    overlapping = 0
    for c in DB.contests.values():
        if c["home_school_id"] != home_school["id"]:
            continue
        if starts_at < (c["ends_at"] + timedelta(minutes=VENUE_TURNOVER_MIN)) and c["starts_at"] < ends_at:
            overlapping += 1
    return (overlapping + 1) <= home_school["venue_concurrent_capacity"]


# ---------------------------------------------------------------------------
# contest_load_check
# ---------------------------------------------------------------------------
def contest_load_check(season, home_id, away_id, starts_at):
    """Runs home then away; raises the first failure."""
    for school_id in (home_id, away_id):
        rows = [c for c in DB.contests.values()
                if c["sport_season_id"] == season["id"]
                and (c["home_school_id"] == school_id or c["away_school_id"] == school_id)]
        if len(rows) + 1 > season["contest_limit"]:
            fail("ERR_SEASON_CONTEST_LIMIT",
                 "school %s would exceed the season contest limit" % school_id)
        lo = starts_at - timedelta(days=ROLLING_WINDOW_DAYS)
        hi = starts_at + timedelta(days=ROLLING_WINDOW_DAYS)
        window_count = sum(1 for c in rows if lo <= c["starts_at"] < hi)
        if window_count >= MAX_CONTESTS_PER_WINDOW:
            fail("ERR_CONTEST_WINDOW_DENSITY",
                 "school %s already holds %d contests in the rolling window" % (school_id, window_count))


# ---------------------------------------------------------------------------
# playoff_seed_assignment (pinned evaluation order, steps 1-8)
# ---------------------------------------------------------------------------
import functools


def _contest_outcome(c, school_id):
    """Returns 'W', 'L', 'F' (forfeit loss) or None for the given school."""
    if c["status"] == "FORFEITED":
        if c["forfeiting_school_id"] == school_id:
            return "F"
        return "W"
    hs, aws = c["home_score"], c["away_score"]
    if hs is None or aws is None or hs == aws:
        return None
    winner = c["home_school_id"] if hs > aws else c["away_school_id"]
    return "W" if winner == school_id else "L"


def _h2h_winner(c):
    if c["status"] == "FORFEITED":
        if c["forfeiting_school_id"] == c["home_school_id"]:
            return c["away_school_id"]
        if c["forfeiting_school_id"] == c["away_school_id"]:
            return c["home_school_id"]
        return None
    hs, aws = c["home_score"], c["away_score"]
    if hs is None or aws is None or hs == aws:
        return None
    return c["home_school_id"] if hs > aws else c["away_school_id"]


def playoff_seed_assignment(season):
    """Returns (list of seed dicts in bracket order, unseeded_school_count)."""
    # STEP 1 - freeze the snapshot
    snapshot = [c for c in DB.contests.values()
                if c["sport_season_id"] == season["id"] and c["status"] in ("PLAYED", "FORFEITED")]

    # STEP 2 - tally each school with >= 1 snapshot contest
    participants = []
    for c in snapshot:
        for sid in (c["home_school_id"], c["away_school_id"]):
            if sid not in participants:
                participants.append(sid)
    participants.sort(key=lambda sid: (DB.schools[sid]["created_at"], DB.schools[sid]["_seq"])
                      if sid in DB.schools else (now(), 0))

    tally = {}
    for sid in participants:
        wins = losses = forfeit_losses = 0
        for c in snapshot:
            if sid not in (c["home_school_id"], c["away_school_id"]):
                continue
            o = _contest_outcome(c, sid)
            if o == "W":
                wins += 1
            elif o == "L":
                losses += 1
            elif o == "F":
                losses += 1
                forfeit_losses += 1
        tally[sid] = {"wins": wins, "losses": losses, "forfeit_losses": forfeit_losses}

    # STEP 3 - raw_win_pct, FROZEN
    frozen_raw = {}
    for sid in participants:
        t = tally[sid]
        denom = t["wins"] + t["losses"]
        frozen_raw[sid] = rhu(Decimal(0), 4) if denom == 0 else \
            rhu(Decimal(t["wins"]) / Decimal(denom), 4)

    # STEP 4 - opponent_avg_win_pct, reading ONLY the frozen step-3 table
    opp_avg = {}
    for sid in participants:
        opps = []
        for c in snapshot:
            if c["home_school_id"] == sid:
                other = c["away_school_id"]
            elif c["away_school_id"] == sid:
                other = c["home_school_id"]
            else:
                continue
            if other == sid or other in opps:
                continue
            sch = DB.schools.get(other)
            if sch is not None and sch["sanction_status"] == "SUSPENDED":
                continue
            opps.append(other)
        if not opps:
            opp_avg[sid] = rhu(Decimal(0), 4)
        else:
            total = sum((frozen_raw.get(o, Decimal(0)) for o in opps), Decimal(0))
            opp_avg[sid] = rhu(total / Decimal(len(opps)), 4)

    # STEP 5 - blend
    power = {}
    for sid in participants:
        power[sid] = rhu(POWER_OWN_WEIGHT * frozen_raw[sid] + POWER_SOS_WEIGHT * opp_avg[sid], 4)

    # STEP 6 - order and break ties
    def h2h(a, b):
        """Return -1 if a ranks higher, 1 if b ranks higher, 0 if not separated."""
        meetings = [c for c in snapshot
                    if {c["home_school_id"], c["away_school_id"]} == {a, b}]
        if not meetings:
            return 0
        meetings.sort(key=lambda c: (c["starts_at"], c["_seq"]))
        w = _h2h_winner(meetings[-1])
        if w == a:
            return -1
        if w == b:
            return 1
        return 0

    def school_created(sid):
        s = DB.schools.get(sid)
        return (s["created_at"], s["_seq"]) if s else (now(), 0)

    def cmp_pair(a, b):
        if power[a] != power[b]:
            return -1 if power[a] > power[b] else 1
        if frozen_raw[a] != frozen_raw[b]:
            return -1 if frozen_raw[a] > frozen_raw[b] else 1
        r = h2h(a, b)
        if r != 0:
            return r
        if tally[a]["forfeit_losses"] != tally[b]["forfeit_losses"]:
            return -1 if tally[a]["forfeit_losses"] < tally[b]["forfeit_losses"] else 1
        if opp_avg[a] != opp_avg[b]:
            return -1 if opp_avg[a] > opp_avg[b] else 1
        ca, cb = school_created(a), school_created(b)
        if ca != cb:
            return -1 if ca < cb else 1
        return 0

    ordered = sorted(participants, key=functools.cmp_to_key(cmp_pair))

    def separator(prev, cur):
        if power[prev] != power[cur]:
            return "POWER_RATING"
        if frozen_raw[prev] != frozen_raw[cur]:
            return "RAW_WIN_PCT"
        if h2h(prev, cur) != 0:
            return "HEAD_TO_HEAD"
        if tally[prev]["forfeit_losses"] != tally[cur]["forfeit_losses"]:
            return "FORFEIT_LOSSES"
        if opp_avg[prev] != opp_avg[cur]:
            return "OPP_AVG_WIN_PCT"
        return "CREATED_AT"

    rows = []
    for idx, sid in enumerate(ordered):
        trace = "POWER_RATING" if idx == 0 else separator(ordered[idx - 1], sid)
        rows.append({
            "sport_season_id": season["id"],
            "school_id": sid,
            "wins": tally[sid]["wins"],
            "losses": tally[sid]["losses"],
            "forfeit_losses": tally[sid]["forfeit_losses"],
            "raw_win_pct": frozen_raw[sid],
            "opponent_avg_win_pct": opp_avg[sid],
            "power_rating": power[sid],
            "seed_number": idx + 1,
            "tiebreak_trace": trace,
        })

    seeded = set(ordered)
    unseeded = 0
    for s in DB.schools.values():
        if s["classification"] == season["classification"] and s["id"] not in seeded:
            unseeded += 1
    return rows, unseeded
