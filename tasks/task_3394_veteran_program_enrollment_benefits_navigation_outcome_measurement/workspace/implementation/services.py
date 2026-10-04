"""Business logic: entity stamping/serialization, calculations (acuity,
compensation, site selection, travel awards, survey windows, engagement
derivation, donor reporting), and the 7-step clock sweep."""
from datetime import datetime, timedelta
from decimal import Decimal, ROUND_HALF_UP
from fractions import Fraction

import db
from constants import (
    ACUITY_WEIGHTS_VETERAN, ACUITY_WEIGHTS_FAMILY_SUPPORT,
    ACUITY_TIER_ENHANCED_MIN, ACUITY_TIER_INTENSIVE_MIN,
    RATING_BASE_CENTS, DEPENDENT_RATING_FLOOR_PCT,
    DEPENDENT_ALLOWANCE_ONE_CENTS, DEPENDENT_ALLOWANCE_TWO_CENTS,
    DEPENDENT_ALLOWANCE_EXTRA_CENTS, COLA_RATE,
    PER_REGISTRATION_TRAVEL_CAP_CENTS, BASELINE_IMPUTE_SCORE,
    BASELINE_WINDOW_DAYS, EXIT_WINDOW_DAYS,
    FOLLOWUP_90_OFFSET_DAYS, FOLLOWUP_GRACE_DAYS,
    CLAIM_CLOSE_GRACE_DAYS, APPEAL_WINDOW_DAYS, RECOVERY_BUFFER_DAYS,
)
from errors import ApiError


# ---------------------------------------------------------------------------
# Stamping and serialization
# ---------------------------------------------------------------------------

def stamp_new(rec, lean=False):
    """Set created_at (and updated_at/version unless the entity is one of the
    two lean resources — Assessment and DonorReport carry only id+created_at)."""
    t = db.now()
    rec["created_at"] = t
    if not lean:
        rec["updated_at"] = t
        rec["version"] = 1


def bump(rec):
    """One version increment + updated_at refresh per mutation."""
    if "version" in rec:
        rec["version"] += 1
        rec["updated_at"] = db.now()


def serialize(rec):
    out = {}
    for key, value in rec.items():
        if key.startswith("_"):
            continue
        if isinstance(value, datetime):
            out[key] = db.iso(value)
        else:
            out[key] = value
    return out


# ---------------------------------------------------------------------------
# calculations.acuity_scoring
# ---------------------------------------------------------------------------

def compute_acuity(member_type, psych, phys, voc, soc):
    w = ACUITY_WEIGHTS_VETERAN if member_type == "VETERAN" else ACUITY_WEIGHTS_FAMILY_SUPPORT
    raw = w["PSYCH"] * psych + w["PHYS"] * phys + w["VOC"] * voc + w["SOC"] * soc
    score = int((raw * 10).quantize(Decimal("1"), rounding=ROUND_HALF_UP))
    if score >= ACUITY_TIER_INTENSIVE_MIN:
        return score, "INTENSIVE"
    if score >= ACUITY_TIER_ENHANCED_MIN:
        return score, "ENHANCED"
    return score, "STANDARD"


# ---------------------------------------------------------------------------
# calculations.compensation_monthly
# ---------------------------------------------------------------------------

def provisional_monthly_cents(claim_type, claimed_rating_pct):
    if claim_type != "DISABILITY_COMPENSATION":
        return None
    return RATING_BASE_CENTS[claimed_rating_pct]


def final_monthly_cents(outcome, decided_rating_pct, dependent_count):
    if outcome == "DENIED" or decided_rating_pct is None:
        return 0
    base = RATING_BASE_CENTS[decided_rating_pct]
    if decided_rating_pct < DEPENDENT_RATING_FLOOR_PCT or dependent_count == 0:
        dep = 0
    elif dependent_count == 1:
        dep = DEPENDENT_ALLOWANCE_ONE_CENTS
    else:
        dep = DEPENDENT_ALLOWANCE_TWO_CENTS + DEPENDENT_ALLOWANCE_EXTRA_CENTS * (dependent_count - 2)
    total = (Decimal(base) + Decimal(dep)) * (Decimal(1) + COLA_RATE)
    return int(total.quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def recompute_member_compensation(member_id):
    member = db.STORE["members"].get(member_id)
    if member is None:
        return
    total = 0
    for claim in db.STORE["claims"].values():
        if (claim["member_id"] == member_id
                and claim["status"] in ("DECIDED", "CLOSED")
                and claim["final_monthly_cents"] is not None):
            total += claim["final_monthly_cents"]
    member["total_monthly_compensation_cents"] = total


# ---------------------------------------------------------------------------
# calculations.engagement_status_derivation
# ---------------------------------------------------------------------------

def derive_engagement(member_id):
    active = 0
    completed = 0
    for e in db.STORE["enrollments"].values():
        if e["member_id"] != member_id:
            continue
        if e["status"] in ("INTAKE", "ACTIVE", "SUSPENDED"):
            active += 1
        elif e["status"] == "COMPLETED":
            completed += 1
    if active >= 1:
        return "ENGAGED"
    if completed >= 1:
        return "GRADUATED"
    return "INACTIVE"


def refresh_engagement(member_id, always_bump=False):
    member = db.STORE["members"][member_id]
    new_value = derive_engagement(member_id)
    changed = new_value != member["engagement_status"]
    member["engagement_status"] = new_value
    if changed or always_bump:
        bump(member)


# ---------------------------------------------------------------------------
# Duplication avoidance
# ---------------------------------------------------------------------------

def has_active_external_record(member_id, service_category):
    for x in db.STORE["external_service_records"].values():
        if (x["member_id"] == member_id and x["status"] == "ACTIVE"
                and x["service_category"] == service_category):
            return True
    return False


# ---------------------------------------------------------------------------
# Outcome surveys (calculations.survey_window_schedule)
# ---------------------------------------------------------------------------

def create_survey(enrollment_id, wave, window_open_at, window_close_at):
    rec = {
        "id": db.new_id(), "_seq": db.next_seq(),
        "enrollment_id": enrollment_id, "wave": wave, "status": "SCHEDULED",
        "window_open_at": window_open_at, "window_close_at": window_close_at,
        "q1": None, "q2": None, "q3": None, "q4": None, "q5": None,
        "wellbeing_score": None, "submitted_at": None,
    }
    stamp_new(rec)
    db.STORE["surveys"][rec["id"]] = rec
    return rec


def schedule_baseline_survey(enrollment):
    open_at = enrollment["created_at"]
    close_at = open_at + timedelta(days=BASELINE_WINDOW_DAYS)
    return create_survey(enrollment["id"], "BASELINE", open_at, close_at)


def schedule_exit_surveys(enrollment):
    exit_at = enrollment["exit_at"]
    create_survey(enrollment["id"], "EXIT", exit_at,
                  exit_at + timedelta(days=EXIT_WINDOW_DAYS))
    create_survey(enrollment["id"], "FOLLOWUP_90",
                  exit_at + timedelta(days=FOLLOWUP_90_OFFSET_DAYS - FOLLOWUP_GRACE_DAYS),
                  exit_at + timedelta(days=FOLLOWUP_90_OFFSET_DAYS + FOLLOWUP_GRACE_DAYS))


# ---------------------------------------------------------------------------
# calculations.clock_sweep_rules — runs in this fixed order on every clock set
# ---------------------------------------------------------------------------

def run_clock_sweep():
    now = db.now()
    # 1. OutcomeSurvey SCHEDULED -> OPEN where clock >= window_open_at
    for s in db.STORE["surveys"].values():
        if s["status"] == "SCHEDULED" and now >= s["window_open_at"]:
            s["status"] = "OPEN"
            bump(s)
    # 2. OutcomeSurvey OPEN -> EXPIRED where clock > window_close_at
    for s in db.STORE["surveys"].values():
        if s["status"] == "OPEN" and now > s["window_close_at"]:
            s["status"] = "EXPIRED"
            bump(s)
    # 3. BenefitsClaim DECIDED -> CLOSED where clock > decided_at + (90 + 7) days
    close_after = timedelta(days=APPEAL_WINDOW_DAYS + CLAIM_CLOSE_GRACE_DAYS)
    for c in db.STORE["claims"].values():
        if (c["status"] == "DECIDED" and c["decided_at"] is not None
                and now > c["decided_at"] + close_after):
            c["status"] = "CLOSED"
            bump(c)
    # 4. Referral PENDING_MATCH -> EXPIRED where clock > treatment_start
    for r in db.STORE["referrals"].values():
        if r["status"] == "PENDING_MATCH" and now > r["treatment_start"]:
            r["status"] = "EXPIRED"
            bump(r)
    # 5. EventRegistration CONFIRMED -> NO_SHOW where clock > event.ends_at
    for reg in db.STORE["event_registrations"].values():
        if reg["status"] == "CONFIRMED":
            ev = db.STORE["community_events"].get(reg["community_event_id"])
            if ev is not None and now > ev["ends_at"]:
                reg["status"] = "NO_SHOW"
                bump(reg)
    # 6. EventRegistration WAITLISTED -> EXPIRED where clock > event.starts_at
    for reg in db.STORE["event_registrations"].values():
        if reg["status"] == "WAITLISTED":
            ev = db.STORE["community_events"].get(reg["community_event_id"])
            if ev is not None and now > ev["starts_at"]:
                reg["status"] = "EXPIRED"
                bump(reg)
    # 7. ExternalServiceRecord ACTIVE -> CLOSED where end_date set and clock > end_date
    for x in db.STORE["external_service_records"].values():
        if (x["status"] == "ACTIVE" and x["end_date"] is not None
                and now > x["end_date"]):
            x["status"] = "CLOSED"
            bump(x)


# ---------------------------------------------------------------------------
# calculations.site_selection
# ---------------------------------------------------------------------------

def select_site(referral):
    candidates = []
    for s in db.STORE["partner_sites"].values():
        if s["region"] != referral["region"]:
            continue
        if referral["required_specialty"] not in s["specialties"]:
            continue
        if s["current_census"] >= s["capacity"]:
            continue
        candidates.append(s)
    if not candidates:
        return None
    candidates.sort(key=lambda s: (
        Fraction(s["current_census"], s["capacity"]),  # exact rational, no rounding
        s["created_at"],
        s["name"],
        s["_seq"],
    ))
    return candidates[0]


def apply_match(referral, site):
    referral["partner_site_id"] = site["id"]
    referral["matched_at"] = db.now()
    referral["status"] = "MATCHED"
    site["current_census"] += 1


# ---------------------------------------------------------------------------
# calculations.treatment_window_overlap (closed intervals, +7d buffers)
# ---------------------------------------------------------------------------

def treatment_window_conflict(member_id, new_start, new_end):
    buf = timedelta(days=RECOVERY_BUFFER_DAYS)
    n_start = new_start
    n_end = new_end + buf
    for r in db.STORE["referrals"].values():
        if r["member_id"] != member_id:
            continue
        if r["status"] not in ("PENDING_MATCH", "MATCHED", "IN_TREATMENT"):
            continue
        e_start = r["treatment_start"]
        e_end = r["treatment_end"] + buf
        if n_start <= e_end and e_start <= n_end:
            return True
    return False


# ---------------------------------------------------------------------------
# calculations.event_schedule_overlap (half-open intervals) + travel award
# ---------------------------------------------------------------------------

def event_schedule_conflict(member_id, new_event):
    for reg in db.STORE["event_registrations"].values():
        if reg["member_id"] != member_id:
            continue
        if reg["status"] not in ("CONFIRMED", "WAITLISTED"):
            continue
        ev = db.STORE["community_events"].get(reg["community_event_id"])
        if ev is None:
            continue
        if new_event["starts_at"] < ev["ends_at"] and ev["starts_at"] < new_event["ends_at"]:
            return True
    return False


def travel_award_amount(request_cents, event):
    return min(request_cents,
               PER_REGISTRATION_TRAVEL_CAP_CENTS,
               event["travel_budget_remaining_cents"])


# ---------------------------------------------------------------------------
# calculations.program_effect_reporting
# ---------------------------------------------------------------------------

def _submitted_score(enrollment_id, wave):
    for s in db.STORE["surveys"].values():
        if (s["enrollment_id"] == enrollment_id and s["wave"] == wave
                and s["status"] == "SUBMITTED"):
            return s["wellbeing_score"]
    return None


def build_donor_report(period_start, period_end, methodology, track_weights):
    entries = []
    total_counted = 0
    tracks = sorted(db.STORE["program_tracks"].values(),
                    key=lambda t: (t["track_code"], t["_seq"]))
    for track in tracks:
        deltas = []
        for e in db.STORE["enrollments"].values():
            if e["program_track_id"] != track["id"] or e["status"] != "COMPLETED":
                continue
            if not (period_start <= e["exit_at"] <= period_end):
                continue
            base = _submitted_score(e["id"], "BASELINE")
            exit_score = _submitted_score(e["id"], "EXIT")
            if methodology == "ITT":
                b = base if base is not None else BASELINE_IMPUTE_SCORE
                x = exit_score if exit_score is not None else b
                deltas.append(x - b)
            else:  # COMPLETER
                if base is not None and exit_score is not None:
                    deltas.append(exit_score - base)
        if not deltas:
            continue
        mean = Decimal(sum(deltas)) / Decimal(len(deltas))
        effect = mean.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
        entries.append({"track_code": track["track_code"],
                        "cohort_size": len(deltas), "effect": effect})
        total_counted += len(deltas)
    if not entries:
        raise ApiError("ERR_EMPTY_COHORT",
                       "the counted cohort is empty in every track", 422)
    if track_weights is not None:
        raw = {}
        for e in entries:
            raw[e["track_code"]] = Decimal(str(track_weights.get(e["track_code"], 0)))
        wsum = sum(raw.values(), Decimal(0))
        if wsum <= 0:
            raw = {e["track_code"]: Decimal(1) for e in entries}
            wsum = Decimal(len(entries))
        weights = {k: v / wsum for k, v in raw.items()}
    else:
        weights = {e["track_code"]: Decimal(e["cohort_size"]) / Decimal(total_counted)
                   for e in entries}
    overall = sum((weights[e["track_code"]] * e["effect"] for e in entries), Decimal(0))
    overall = overall.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
    for e in entries:
        e["effect"] = float(e["effect"])
    return entries, total_counted, float(overall)
