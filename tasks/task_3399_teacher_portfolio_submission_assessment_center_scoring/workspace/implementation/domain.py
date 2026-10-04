"""Business logic: aggregations, cascades, selector policy, sweeps.

All monetary/score math uses Decimal with round-half-up (PRD section 2.6).
Computed fields (counted_score, superseded, budget_remaining_cents,
open_assignment_count, reliability rates, program status) are derived from
canonical state on demand so they can never go stale.
"""
from datetime import timedelta
from decimal import Decimal, ROUND_HALF_UP

import constants as C
import errors as E
from store import DB, now, new_id, stamp_new, touch


# ---------------------------------------------------------------------------
# Component triple derivations (PRD 3.3)
# ---------------------------------------------------------------------------

def triple_of(sub):
    return [x for x in DB.submissions.values()
            if x["candidate_id"] == sub["candidate_id"]
            and x["cycle_id"] == sub["cycle_id"]
            and x["component_code"] == sub["component_code"]]


def triple_for(candidate_id, cycle_id, component_code):
    return [x for x in DB.submissions.values()
            if x["candidate_id"] == candidate_id
            and x["cycle_id"] == cycle_id
            and x["component_code"] == component_code]


def counted_score_for(candidate_id, cycle_id, component_code):
    """max final_score over SCORED attempts of the triple; None until any SCORED."""
    scored = [x["final_score"] for x in triple_for(candidate_id, cycle_id, component_code)
              if x["status"] == "SCORED" and x["final_score"] is not None]
    return max(scored) if scored else None


def superseded_of(sub):
    """True on every attempt except the highest-attempt_number row of the triple."""
    top = max(x["attempt_number"] for x in triple_of(sub))
    return sub["attempt_number"] < top


def latest_attempt(candidate_id, cycle_id, component_code):
    attempts = triple_for(candidate_id, cycle_id, component_code)
    if not attempts:
        return None
    return max(attempts, key=lambda x: x["attempt_number"])


# ---------------------------------------------------------------------------
# Weighted certification score (PRD 2.6 / 3.7): pinned round-then-sum order
# ---------------------------------------------------------------------------

def weighted_total(components, score_for_code):
    """score_for_code(code) -> Decimal or None (None contributes 0)."""
    total = Decimal("0")
    for comp in components:
        score = score_for_code(comp["code"])
        if score is None:
            score = Decimal("0")
        contribution = (score * _dec(comp["weight"])).quantize(
            C.CONTRIBUTION_QUANT, rounding=ROUND_HALF_UP)
        total += contribution
    return total.quantize(C.TOTAL_QUANT, rounding=ROUND_HALF_UP)


def _dec(value):
    return Decimal(str(value))


def provisional_total(cert):
    """Latest-attempt variant: 0 for a component whose latest attempt is unscored."""
    cycle = DB.cycles[cert["cycle_id"]]

    def score_for(code):
        latest = latest_attempt(cert["candidate_id"], cert["cycle_id"], code)
        if latest is None:
            return None
        return latest["final_score"]

    return weighted_total(cycle["components"], score_for)


# ---------------------------------------------------------------------------
# Certifications (PRD 3.7)
# ---------------------------------------------------------------------------

def certification_for(candidate_id, cycle_id):
    for cert in DB.certifications.values():
        if cert["candidate_id"] == candidate_id and cert["cycle_id"] == cycle_id:
            return cert
    return None


def ensure_certification(candidate_id, cycle_id):
    cert = certification_for(candidate_id, cycle_id)
    if cert is None:
        cert = {
            "id": new_id(),
            "candidate_id": candidate_id,
            "cycle_id": cycle_id,
            "status": "PENDING",
            "weighted_total_final": None,
            "certified_at": None,
            "valid_until": None,
        }
        stamp_new(cert)
        DB.certifications[cert["id"]] = cert
    return cert


def decide_certification(cert):
    """Fires the PENDING -> CERTIFIED/DENIED decision the moment every cycle
    component holds a counted_score (PRD 3.7). Boundary: equality certifies."""
    if cert["status"] != "PENDING":
        return
    cycle = DB.cycles[cert["cycle_id"]]
    counted = {}
    for comp in cycle["components"]:
        cs = counted_score_for(cert["candidate_id"], cert["cycle_id"], comp["code"])
        if cs is None:
            return
        counted[comp["code"]] = cs
    total = weighted_total(cycle["components"], lambda code: counted.get(code))
    cert["weighted_total_final"] = total
    if total >= _dec(cycle["certification_threshold"]):
        cert["status"] = "CERTIFIED"
        cert["certified_at"] = now()
        cert["valid_until"] = now() + timedelta(days=C.VALIDITY_DAYS)
        touch(cert)
        auto_propose_stipends(cert)
    else:
        cert["status"] = "DENIED"
        touch(cert)


def on_submission_scored(sub):
    """Cascade after an attempt reaches SCORED: counted_score/superseded are
    derived (self-refreshing); certification aggregation re-runs."""
    cert = certification_for(sub["candidate_id"], sub["cycle_id"])
    if cert is not None:
        decide_certification(cert)


# ---------------------------------------------------------------------------
# Incentive programs and stipends (PRD 3.8)
# ---------------------------------------------------------------------------

def program_remaining(program_id):
    prog = DB.programs[program_id]
    committed = sum(s["amount_cents"] for s in DB.stipends.values()
                    if s["program_id"] == program_id and s["status"] in ("APPROVED", "PAID"))
    return prog["budget_total_cents"] - committed


def program_status(program_id):
    return "EXHAUSTED" if program_remaining(program_id) == 0 else "OPEN"


def stipend_amount_for(prog, cert, candidate):
    """Pinned evaluation order (PRD 3.8): multiplier, then tentative amount
    rounded half-up to integer cents, then cap at current budget_remaining."""
    deadline = prog["early_bird_deadline"]
    if deadline is not None and cert["certified_at"] is not None and cert["certified_at"] <= deadline:
        multiplier = _dec(prog["early_bird_multiplier"])
    else:
        multiplier = Decimal("1.0")
    tentative = (_dec(prog["base_stipend_cents"])
                 * _dec(candidate["fte_fraction"])
                 * multiplier).quantize(Decimal("1"), rounding=ROUND_HALF_UP)
    return min(int(tentative), program_remaining(prog["id"]))


def auto_propose_stipends(cert):
    """On CERTIFIED: one PROPOSED stipend per eligible OPEN program with
    remaining budget > 0; pairs already holding a stipend row are skipped."""
    candidate = DB.candidates[cert["candidate_id"]]
    for prog in DB.programs.values():
        if program_remaining(prog["id"]) <= 0:
            continue
        if prog["sponsor_district_code"] is not None:
            if candidate["district_code"] != prog["sponsor_district_code"]:
                continue
        else:
            if candidate["license_state"] != prog["sponsor_state"]:
                continue
        already = any(s for s in DB.stipends.values()
                      if s["program_id"] == prog["id"] and s["certification_id"] == cert["id"])
        if already:
            continue
        stipend = {
            "id": new_id(),
            "program_id": prog["id"],
            "certification_id": cert["id"],
            "amount_cents": stipend_amount_for(prog, cert, candidate),
            "status": "PROPOSED",
        }
        stamp_new(stipend)
        DB.stipends[stipend["id"]] = stipend


# ---------------------------------------------------------------------------
# Assessors: selector, suspension cascade, reliability (PRD 3.5 / 3.6)
# ---------------------------------------------------------------------------

def open_assignment_count(assessor_id):
    return sum(1 for x in DB.assignments.values()
               if x["assessor_id"] == assessor_id
               and x["status"] in ("ASSIGNED", "SCORE_SUBMITTED"))


def choose_assessor(sub):
    """Selector policy (PRD 3.6): ACTIVE, non-conflicted, no existing
    ASSIGNED/SCORE_SUBMITTED/FINALIZED assignment on this submission.
    Rank: open_assignment_count ASC, calibrated_at ASC, created_at ASC."""
    candidate = DB.candidates[sub["candidate_id"]]
    pool = []
    for a in DB.assessors.values():
        if a["status"] != "ACTIVE":
            continue
        if a["home_district_code"] == candidate["district_code"]:
            continue
        clash = any(x for x in DB.assignments.values()
                    if x["assessor_id"] == a["id"]
                    and x.get("submission_id") == sub["id"]
                    and x["status"] in ("ASSIGNED", "SCORE_SUBMITTED", "FINALIZED"))
        if clash:
            continue
        pool.append(a)
    if not pool:
        E.fail(E.ERR_NO_ELIGIBLE_ASSESSOR, 409,
               "No ACTIVE, non-conflicted, not-already-assigned assessor available")
    from datetime import datetime, timezone
    far = datetime.max.replace(tzinfo=timezone.utc)
    pool.sort(key=lambda a: (
        open_assignment_count(a["id"]),
        a["calibrated_at"] if a["calibrated_at"] is not None else far,
        a.get("_seq", 0),
    ))
    return pool[0]


def suspend_assessor(assessor):
    """Any suspension: every ASSIGNED assignment flips to REASSIGNED."""
    assessor["status"] = "SUSPENDED"
    touch(assessor)
    for asg in DB.assignments.values():
        if asg["assessor_id"] == assessor["id"] and asg["status"] == "ASSIGNED":
            asg["status"] = "REASSIGNED"
            touch(asg)


def finalized_live_reads(assessor_id):
    reads = [x for x in DB.assignments.values()
             if x["assessor_id"] == assessor_id
             and x.get("submission_id") is not None
             and x["status"] == "FINALIZED"]
    reads.sort(key=lambda x: (x["score_submitted_at"], x.get("_seq", 0)))
    return reads


def reliability_rates(assessor_id):
    """(scored_read_count, exact_rate, adjacent_rate); rates None until 10 reads."""
    reads = finalized_live_reads(assessor_id)
    count = len(reads)
    if count < C.IRR_WINDOW:
        return count, None, None
    window = reads[-C.IRR_WINDOW:]
    exact = 0
    adjacent = 0
    for read in window:
        sub = DB.submissions.get(read["submission_id"])
        if sub is None or sub["final_score"] is None:
            continue
        diff = abs(read["score"] - sub["final_score"])
        if diff == 0:
            exact += 1
        if diff <= C.ADJACENT_BAND:
            adjacent += 1
    exact_rate = (Decimal(exact) / Decimal(C.IRR_WINDOW)).quantize(
        C.SCORE_QUANT, rounding=ROUND_HALF_UP)
    adjacent_rate = (Decimal(adjacent) / Decimal(C.IRR_WINDOW)).quantize(
        C.SCORE_QUANT, rounding=ROUND_HALF_UP)
    return count, exact_rate, adjacent_rate


def irr_check_after_finalization(assessor_id):
    """Auto-suspend when a finalization makes scored_read_count >= 10 with
    exact_agreement_rate < 0.70. Boundary: exactly 0.70 does NOT suspend."""
    assessor = DB.assessors.get(assessor_id)
    if assessor is None or assessor["status"] != "ACTIVE":
        return
    count, exact_rate, _ = reliability_rates(assessor_id)
    if count >= C.IRR_WINDOW and exact_rate is not None and exact_rate < C.IRR_EXACT_FLOOR:
        suspend_assessor(assessor)


# ---------------------------------------------------------------------------
# Booking completion cascade (PRD 3.4)
# ---------------------------------------------------------------------------

def on_booking_completed(booking):
    """Hop 1: latest IN_PROGRESS/RETURNED ASSESSMENT attempt of this
    candidate+cycle -> SCORED with final_score := earned_score.
    Hop 2: certification aggregation recompute (decide when complete).
    Hop 3: CERTIFIED -> stipend auto-proposal (inside decide_certification)."""
    attempts = [s for s in DB.submissions.values()
                if s["candidate_id"] == booking["candidate_id"]
                and s["cycle_id"] == booking["cycle_id"]
                and s["kind"] == "ASSESSMENT"
                and s["status"] in ("IN_PROGRESS", "RETURNED")]
    if not attempts:
        return
    sub = max(attempts, key=lambda s: s["attempt_number"])
    sub["status"] = "SCORED"
    sub["final_score"] = booking["earned_score"]
    touch(sub)
    on_submission_scored(sub)


# ---------------------------------------------------------------------------
# Logical clock sweeps (PRD 2.4): exactly two sweeps, no submission expiry
# ---------------------------------------------------------------------------

def sweep_clock(new_clock):
    DB.clock = new_clock
    for b in DB.bookings.values():
        if b["status"] == "BOOKED" and b["slot_end_at"] < new_clock:
            b["status"] = "NO_SHOW"
            touch(b)
    for cert in DB.certifications.values():
        if (cert["status"] in ("CERTIFIED", "RENEWED")
                and cert["valid_until"] is not None
                and cert["valid_until"] < new_clock):
            cert["status"] = "EXPIRED"
            touch(cert)
