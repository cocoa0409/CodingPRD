"""Cascading state consistency (PRD 2.9) and clock-driven auto-transitions
(PRD 2.5). Every cascade hop marks the affected resource (version +1,
updated_at refreshed, deduped per request)."""
import db
import calc
import timeutil
from constants import CYCLE_MAX_DURATION_DAYS


# --- lookups -------------------------------------------------------------------
def gb_of_athlete(athlete_id):
    athlete = db.get("athletes", athlete_id)
    if athlete is None:
        return None
    return db.get("governing_bodies", athlete["governing_body_id"])


def agreements_of_athlete(athlete_id):
    return [fa for fa in db.all_of("funding_agreements")
            if fa["athlete_id"] == athlete_id]


def athletes_of_gb(gb_id):
    return [a for a in db.all_of("athletes") if a["governing_body_id"] == gb_id]


def procedures_of_gb(gb_id):
    return [p for p in db.all_of("selection_procedures")
            if p["governing_body_id"] == gb_id]


def rosters_of_proc(proc_id):
    return [r for r in db.all_of("rosters")
            if r["selection_procedure_id"] == proc_id]


def appeals_of_roster(roster_id):
    return [a for a in db.all_of("appeals") if a["roster_id"] == roster_id]


def deals_of_athlete(athlete_id):
    return [d for d in db.all_of("commercial_deals")
            if d["athlete_id"] == athlete_id]


def unresolved_abuse(athlete_id):
    return any(r["athlete_id"] == athlete_id
               and r["status"] in ("REPORTED", "FORWARDED")
               for r in db.all_of("abuse_reports"))


# --- funding agreement primitive cascades --------------------------------------
def suspend_agreement(fa):
    """ACTIVE -> SUSPENDED: exact stipend reversal, insurance lapse, waterfall."""
    if fa["status"] != "ACTIVE":
        return
    fa["status"] = "SUSPENDED"
    if fa["insurance_status"] == "INS_ENROLLED":
        fa["insurance_status"] = "INS_LAPSED"
    db.mark("funding_agreements", fa)
    gb = gb_of_athlete(fa["athlete_id"])
    if gb is not None:
        gb["committed_monthly_stipend_cents"] -= fa["monthly_stipend_cents"]
        db.mark("governing_bodies", gb)
        calc.run_waterfall(gb)


def resume_agreement(fa):
    """SUSPENDED -> ACTIVE: restores exactly the stipend removed at suspension."""
    fa["status"] = "ACTIVE"
    db.mark("funding_agreements", fa)
    gb = gb_of_athlete(fa["athlete_id"])
    if gb is not None:
        gb["committed_monthly_stipend_cents"] += fa["monthly_stipend_cents"]
        db.mark("governing_bodies", gb)
        calc.run_waterfall(gb)


def terminate_agreement(fa):
    if fa["status"] == "TERMINATED":
        return
    prior = fa["status"]
    fa["status"] = "TERMINATED"
    if fa["insurance_status"] == "INS_ENROLLED":
        fa["insurance_status"] = "INS_LAPSED"
    db.mark("funding_agreements", fa)
    gb = gb_of_athlete(fa["athlete_id"])
    if gb is not None:
        if prior == "ACTIVE":
            gb["committed_monthly_stipend_cents"] -= fa["monthly_stipend_cents"]
            db.mark("governing_bodies", gb)
        calc.run_waterfall(gb)


# --- athlete cascades -----------------------------------------------------------
def athlete_suspend_cascade(athlete):
    for fa in agreements_of_athlete(athlete["id"]):
        if fa["status"] == "ACTIVE":
            suspend_agreement(fa)


def athlete_reinstate_cascade(athlete):
    """Every SUSPENDED agreement with tier != NONE returns to ACTIVE, provided
    the body is not DECERTIFIED."""
    gb = gb_of_athlete(athlete["id"])
    if gb is not None and gb["status"] == "DECERTIFIED":
        return
    for fa in agreements_of_athlete(athlete["id"]):
        if fa["status"] == "SUSPENDED" and fa["tier"] != "NONE":
            resume_agreement(fa)


def athlete_retire_cascade(athlete):
    for fa in agreements_of_athlete(athlete["id"]):
        if fa["status"] in ("OFFERED", "ACTIVE", "SUSPENDED"):
            terminate_agreement(fa)
    remove_athlete_slots(athlete["id"], promote=False)
    for deal in deals_of_athlete(athlete["id"]):
        if deal["status"] in ("PROPOSED", "CONSENT_GRANTED", "ACTIVE"):
            deal["status"] = "TERMINATED"
            db.mark("commercial_deals", deal)


def flag_athlete(athlete):
    """Screening -> SCREENING_FLAGGED; ELIGIBLE -> SUSPENDED (+funding halt)."""
    if athlete["eligibility_status"] == "RETIRED":
        return
    if athlete["screening_status"] != "SCREENING_FLAGGED":
        athlete["screening_status"] = "SCREENING_FLAGGED"
        db.mark("athletes", athlete)
    if athlete["eligibility_status"] == "ELIGIBLE":
        athlete["eligibility_status"] = "SUSPENDED"
        db.mark("athletes", athlete)
        athlete_suspend_cascade(athlete)


# --- roster slot cascades --------------------------------------------------------
def _next_alternate(roster):
    cands = [s for s in roster["slots"]
             if s["slot_type"] == "ALTERNATE" and s["slot_status"] == "NOMINATED"]
    if not cands:
        return None
    cands.sort(key=lambda s: s["rank"])
    return cands[0]


def promote_alternate(roster, rank):
    alt = _next_alternate(roster)
    if alt is None:
        return False
    alt["slot_type"] = "PRIMARY"
    alt["slot_status"] = "PROMOTED"
    alt["rank"] = rank
    return True


def remove_athlete_slots(athlete_id, promote):
    """Remove the athlete's non-terminal slots on non-terminal rosters."""
    for roster in db.all_of("rosters"):
        if roster["status"] not in ("NOMINATED", "SUBMITTED"):
            continue
        changed = False
        for slot in roster["slots"]:
            if slot["athlete_id"] != athlete_id:
                continue
            if slot["slot_status"] not in ("NOMINATED", "ACCEPTED", "PROMOTED"):
                continue
            was_primary = slot["slot_type"] == "PRIMARY"
            old_rank = slot["rank"]
            slot["slot_status"] = "REMOVED"
            changed = True
            if promote and was_primary:
                promote_alternate(roster, old_rank)
        if changed:
            db.mark("rosters", roster)


# --- abuse cascade -----------------------------------------------------------------
def abuse_substantiated_cascade(report):
    athlete = db.get("athletes", report["athlete_id"])
    if athlete is None:
        return
    flag_athlete(athlete)
    remove_athlete_slots(athlete["id"], promote=True)


# --- cycle close cascades ------------------------------------------------------------
def cascade_cycle_closed(cycle, passed):
    gb = db.get("governing_bodies", cycle["governing_body_id"])
    if gb is None:
        return
    if passed:
        if gb["status"] == "APPLIED":
            gb["status"] = "CERTIFIED"
            gb["certified_at"] = timeutil.now()
            db.mark("governing_bodies", gb)
        elif gb["status"] == "PROBATION":
            gb["status"] = "CERTIFIED"
            db.mark("governing_bodies", gb)
    else:
        if gb["status"] == "CERTIFIED":
            gb["status"] = "PROBATION"
            db.mark("governing_bodies", gb)


# --- complaint substantiation cascade ---------------------------------------------------
def cascade_complaint_substantiated(complaint):
    gb = db.get("governing_bodies", complaint["governing_body_id"])
    if gb is None:
        return
    now = timeutil.now()
    old_posture, new_posture = calc.recompute_posture(gb, now)
    if old_posture == "NORMAL" and new_posture == "ELEVATED" \
            and gb["status"] == "CERTIFIED":
        gb["status"] = "PROBATION"
        db.mark("governing_bodies", gb)
    if complaint["severity"] == "CRITICAL" \
            and gb["status"] in ("CERTIFIED", "PROBATION"):
        gb["status"] = "INTERIM_MANAGED"  # interim_manager_id stays null
        db.mark("governing_bodies", gb)


# --- decertification cascade --------------------------------------------------------------
def roster_cancel(roster):
    if roster["status"] not in ("DRAFT", "NOMINATED", "SUBMITTED"):
        return
    roster["status"] = "CANCELLED"
    db.mark("rosters", roster)
    for appeal in appeals_of_roster(roster["id"]):
        if appeal["status"] in ("FILED", "HEARING"):
            appeal["status"] = "WITHDRAWN"
            db.mark("appeals", appeal)


def procedure_supersede(proc):
    if proc["proc_status"] not in ("DRAFT", "PUBLISHED", "LOCKED"):
        return
    proc["proc_status"] = "SUPERSEDED"
    db.mark("selection_procedures", proc)
    for roster in rosters_of_proc(proc["id"]):
        roster_cancel(roster)


def decertify(gb):
    for proc in procedures_of_gb(gb["id"]):
        procedure_supersede(proc)
    for athlete in athletes_of_gb(gb["id"]):
        for fa in agreements_of_athlete(athlete["id"]):
            if fa["status"] in ("ACTIVE", "SUSPENDED"):
                suspend_agreement(fa)
        for deal in deals_of_athlete(athlete["id"]):
            if deal["status"] == "ACTIVE":
                deal["status"] = "TERMINATED"
                db.mark("commercial_deals", deal)


# --- clock-driven auto-transitions (PRD 2.5; on clock set and on read) --------------------
def due_athlete(athlete, now):
    if athlete["screening_status"] == "SCREENING_CLEARED" \
            and athlete.get("screening_expires_at") is not None \
            and now > athlete["screening_expires_at"]:
        athlete["screening_status"] = "SCREENING_EXPIRED"
        db.mark("athletes", athlete)


def due_deal(deal, now):
    if deal["status"] == "ACTIVE" and now > deal["exclusivity_end"]:
        deal["status"] = "EXPIRED"
        db.mark("commercial_deals", deal)


def due_cycle(cycle, now):
    if cycle["status"] == "REMEDIATION" and cycle.get("opened_at") is not None \
            and now > cycle["opened_at"] + timeutil.days(CYCLE_MAX_DURATION_DAYS):
        cycle["status"] = "CLOSED_FAILED"
        cycle["final_score"] = cycle["provisional_score"]
        cycle["remediation_applied"] = False
        cycle["closed_at"] = now
        db.mark("certification_cycles", cycle)
        cascade_cycle_closed(cycle, passed=False)


def due_body(gb, now):
    old_posture, new_posture = calc.recompute_posture(gb, now)
    if old_posture == "NORMAL" and new_posture == "ELEVATED" \
            and gb["status"] == "CERTIFIED":
        gb["status"] = "PROBATION"
        db.mark("governing_bodies", gb)


def sweep_all(now):
    for athlete in list(db.all_of("athletes")):
        due_athlete(athlete, now)
    for deal in list(db.all_of("commercial_deals")):
        due_deal(deal, now)
    for cycle in list(db.all_of("certification_cycles")):
        due_cycle(cycle, now)
    for gb in list(db.all_of("governing_bodies")):
        due_body(gb, now)
