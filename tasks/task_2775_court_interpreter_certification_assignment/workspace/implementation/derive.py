"""Program constants, computed fields and resource resolution."""
from decimal import Decimal

from errors import ApiError
from store import db, now, sort_created, today
from util import add_days, day_start, dec, parse_date, parse_dt, round_half_up_2

TIER_RANK = {"MASTER": 3, "CERTIFIED": 2, "REGISTERED": 1, "PROVISIONAL": 0}
TIERS = ("MASTER", "CERTIFIED", "REGISTERED", "PROVISIONAL")
CYCLE_DAYS = {"MASTER": 730, "CERTIFIED": 730, "REGISTERED": 730, "PROVISIONAL": 365}
GRACE_DAYS = 90

WRITTEN_FLOOR = {"MASTER": 90, "CERTIFIED": 80, "REGISTERED": 80, "PROVISIONAL": 80}
ORAL_FLOOR = {"MASTER": 85, "CERTIFIED": 70, "REGISTERED": 70, "PROVISIONAL": 70}
MAX_ATTEMPTS_PER_EXAM = 3
RETAKE_WAIT_DAYS = 90
MIN_RENEWAL_CREDIT_HOURS = 16

TYPE_WEIGHTS = {
    "ARRAIGNMENT": 50,
    "DETENTION_REVIEW": 45,
    "TRIAL": 40,
    "PLEA": 30,
    "SENTENCING": 30,
    "MOTION": 20,
    "CIVIL_MOTION": 10,
}
CUSTODY_BONUS = 25
RARITY_BONUS = {"RARE": 15, "NON_DESIGNATED": 5, "DESIGNATED": 0}
URGENCY_BASE = 20
URGENCY_PER_DAY = 2
CLASS_A_FLOOR = 80
CLASS_B_FLOOR = 55

SANCTION_POINTS = {"LETTER": 5, "PROBATION": 10, "SUSPENSION": 12, "REVOCATION": 20}
SANCTION_WINDOW = {
    "MINOR": ("LETTER", "PROBATION"),
    "MAJOR": ("PROBATION", "SUSPENSION"),
    "SEVERE": ("SUSPENSION", "REVOCATION"),
}
SANCTION_DAYS = {"LETTER": 365, "PROBATION": 180}
RECENT_WEIGHT = 4
OLDER_WEIGHT = 2
LOOKBACK_DAYS = 365
QUALITY_FLOOR = 60
APPEAL_WINDOW_DAYS = 30

TRAVEL_BUFFER_MINUTES = 60
MAX_OVERRUN_HOURS = 6
MAX_REPORT_SPAN_DAYS = 400
COMPLIANT_FLOOR = Decimal("95.00")
CORRECTIVE_FLOOR = Decimal("85.00")

LIVE_CREDENTIAL_STATUSES = (
    "ACTIVE",
    "LAPSED",
    "PENDING_WRITTEN",
    "PENDING_ORAL",
    "PENDING_ETHICS",
)
LIVE_SERVICE_STATUSES = ("PROPOSED", "CONFIRMED", "CHECKED_IN")
CANCELLABLE_SERVICE_STATUSES = ("PROPOSED", "CONFIRMED")
OBLIGATED_CLAIM_STATUSES = ("FINALIZED", "SUBMITTED", "APPROVED", "PAID")
PENDING_CLAIM_STATUSES = ("FINALIZED", "SUBMITTED", "APPROVED")


# --------------------------------------------------------------------------
# resolution
# --------------------------------------------------------------------------
def resolve(collection, row_id, error_id):
    row = getattr(db, collection).get(row_id) if isinstance(row_id, str) else None
    if row is None:
        raise ApiError(error_id, "The requested resource does not exist.")
    return row


def get_language(language_id):
    return resolve("languages", language_id, "ERR_CONFIG_RESOURCE_NOT_FOUND")


def get_courthouse(courthouse_id):
    return resolve("courthouses", courthouse_id, "ERR_CONFIG_RESOURCE_NOT_FOUND")


def get_rate_schedule(rate_schedule_id):
    return resolve("rate_schedules", rate_schedule_id, "ERR_CONFIG_RESOURCE_NOT_FOUND")


def get_interpreter(interpreter_id):
    return resolve("interpreters", interpreter_id, "ERR_INTERPRETER_NOT_FOUND")


def get_credential(credential_id):
    return resolve("credentials", credential_id, "ERR_CREDENTIAL_NOT_FOUND")


def get_hearing(hearing_id):
    return resolve("hearings", hearing_id, "ERR_HEARING_NOT_FOUND")


def get_assignment(assignment_id):
    return resolve("assignments", assignment_id, "ERR_ASSIGNMENT_NOT_FOUND")


def get_pay_claim(pay_claim_id):
    return resolve("pay_claims", pay_claim_id, "ERR_PAY_CLAIM_NOT_FOUND")


def get_complaint(complaint_id):
    return resolve("complaints", complaint_id, "ERR_COMPLAINT_NOT_FOUND")


def get_disciplinary_action(action_id):
    return resolve(
        "disciplinary_actions", action_id, "ERR_DISCIPLINARY_ACTION_NOT_FOUND"
    )


# --------------------------------------------------------------------------
# credentials and the roster
# --------------------------------------------------------------------------
def credentials_of(interpreter_id):
    return sort_created(
        [c for c in db.credentials.values() if c["interpreter_id"] == interpreter_id]
    )


def active_credentials_of(interpreter_id):
    return [c for c in credentials_of(interpreter_id) if c["status"] == "ACTIVE"]


def language_active_count(language_id):
    return len(
        [
            c
            for c in db.credentials.values()
            if c["language_id"] == language_id and c["status"] == "ACTIVE"
        ]
    )


def credential_tier(interpreter_id):
    """Highest tier among the holder's ACTIVE credentials, else NONE."""
    best = "NONE"
    best_rank = -1
    for c in active_credentials_of(interpreter_id):
        rank = TIER_RANK.get(c["tier"], -1)
        if rank > best_rank:
            best_rank = rank
            best = c["tier"]
    return best


def credentialed_language_ids(interpreter_id):
    return [c["language_id"] for c in active_credentials_of(interpreter_id)]


def best_active_credential(interpreter_id, language_id):
    """The holder's highest-ranked ACTIVE credential in one language."""
    best = None
    for c in active_credentials_of(interpreter_id):
        if c["language_id"] != language_id:
            continue
        if best is None or TIER_RANK.get(c["tier"], -1) > TIER_RANK.get(best["tier"], -1):
            best = c
    return best


def actions_of(interpreter_id, statuses=("IN_EFFECT", "EXPIRED")):
    return [
        a
        for a in db.disciplinary_actions.values()
        if a["interpreter_id"] == interpreter_id and a["status"] in statuses
    ]


def quality_points(interpreter_id):
    """(recent_points, older_points) split on the 365-day cutoff."""
    cutoff = add_days(today(), -LOOKBACK_DAYS)
    recent = 0
    older = 0
    for action in actions_of(interpreter_id):
        effective_from = parse_date(action["effective_from"])
        if effective_from >= cutoff:
            recent += action["points"]
        else:
            older += action["points"]
    return recent, older


def quality_scores(interpreter_id):
    recent, older = quality_points(interpreter_id)
    rolling = max(0, 100 - RECENT_WEIGHT * recent)
    lifetime = max(0, 100 - RECENT_WEIGHT * recent - OLDER_WEIGHT * older)
    return rolling, lifetime


def complaint_points(interpreter_id):
    return sum(a["points"] for a in actions_of(interpreter_id))


def claims_of_interpreter(interpreter_id):
    result = []
    for claim in db.pay_claims.values():
        assignment = db.assignments.get(claim["assignment_id"])
        if assignment and assignment["interpreter_id"] == interpreter_id:
            result.append(claim)
    return result


def interpreter_pay(interpreter_id):
    pending = 0
    paid = 0
    for claim in claims_of_interpreter(interpreter_id):
        amount = claim.get("final_total_cents") or 0
        if claim["status"] in PENDING_CLAIM_STATUSES:
            pending += amount
        elif claim["status"] == "PAID":
            paid += amount
    return pending, paid


# --------------------------------------------------------------------------
# courthouse ledger
# --------------------------------------------------------------------------
def claim_courthouse_id(claim):
    assignment = db.assignments.get(claim["assignment_id"])
    if assignment is None:
        return None
    hearing = db.hearings.get(assignment["hearing_id"])
    return hearing["courthouse_id"] if hearing else None


def ledger(courthouse):
    encumbered = 0
    obligated = 0
    for claim in db.pay_claims.values():
        if claim_courthouse_id(claim) != courthouse["id"]:
            continue
        if claim["status"] == "ENCUMBERED":
            encumbered += claim.get("provisional_total_cents") or 0
        elif claim["status"] in OBLIGATED_CLAIM_STATUSES:
            obligated += claim.get("final_total_cents") or 0
    available = courthouse["pay_budget_cents"] - encumbered - obligated
    return encumbered, obligated, available


def available_pay_cents(courthouse):
    return ledger(courthouse)[2]


# --------------------------------------------------------------------------
# hearings and matching
# --------------------------------------------------------------------------
def required_min_tier(hearing):
    language = db.languages[hearing["language_id"]]
    if language["tier_class"] == "RARE":
        return "PROVISIONAL"
    if hearing["priority_class"] == "A":
        return "CERTIFIED"
    if hearing["priority_class"] == "B":
        return "REGISTERED"
    return "PROVISIONAL"


def hearing_priority(hearing_type, in_custody, tier_class, scheduled_start):
    """lead_time_days, priority_score and priority_class, frozen at creation."""
    delta = (scheduled_start - now()).total_seconds()
    lead_time_days = max(0, int(delta // 86400)) if delta > 0 else 0
    urgency = max(0, URGENCY_BASE - URGENCY_PER_DAY * lead_time_days)
    score = TYPE_WEIGHTS[hearing_type]
    if in_custody:
        score += CUSTODY_BONUS
    score += RARITY_BONUS[tier_class]
    score += urgency
    score = min(100, score)
    if score >= CLASS_A_FLOOR:
        priority_class = "A"
    elif score >= CLASS_B_FLOOR:
        priority_class = "B"
    else:
        priority_class = "C"
    return lead_time_days, score, priority_class


def assignments_of_hearing(hearing_id):
    return sort_created(
        [a for a in db.assignments.values() if a["hearing_id"] == hearing_id]
    )


def assignments_of_interpreter(interpreter_id):
    return sort_created(
        [
            a
            for a in db.assignments.values()
            if a["interpreter_id"] == interpreter_id
        ]
    )


def live_assignments_of_interpreter(interpreter_id):
    """Live rows ordered by hearing start, then the assignment's own created_at."""
    rows = [
        a
        for a in db.assignments.values()
        if a["interpreter_id"] == interpreter_id
        and a["service_status"] in LIVE_SERVICE_STATUSES
    ]

    def key(a):
        hearing = db.hearings[a["hearing_id"]]
        return (hearing["scheduled_start"], a["created_at"], a["_seq"])

    return sorted(rows, key=key)


def claim_for_assignment(assignment_id):
    matches = sort_created(
        [c for c in db.pay_claims.values() if c["assignment_id"] == assignment_id]
    )
    return matches[-1] if matches else None


def interval_conflict(interpreter_id, hearing, delivery_mode, ignore_assignment_ids=()):
    """Return an error id when the interpreter is unavailable, else None."""
    new_start = parse_dt(hearing["scheduled_start"])
    new_end = parse_dt(hearing["scheduled_end"])
    for other in live_assignments_of_interpreter(interpreter_id):
        if other["id"] in ignore_assignment_ids:
            continue
        other_hearing = db.hearings[other["hearing_id"]]
        old_start = parse_dt(other_hearing["scheduled_start"])
        old_end = parse_dt(other_hearing["scheduled_end"])
        if old_start < new_end and new_start < old_end:
            return "ERR_INTERPRETER_DOUBLE_BOOKED"
        if (
            other["delivery_mode"] == "IN_PERSON"
            and delivery_mode == "IN_PERSON"
            and other_hearing["courthouse_id"] != hearing["courthouse_id"]
        ):
            gap = (max(old_start, new_start) - min(old_end, new_end)).total_seconds() / 60.0
            if gap < TRAVEL_BUFFER_MINUTES:
                return "ERR_TRAVEL_BUFFER_VIOLATION"
    return None


def vri_occupancy_exceeded(hearing, courthouse):
    """Closed-interval VRI occupancy at the courthouse, including the new row."""
    new_start = parse_dt(hearing["scheduled_start"])
    new_end = parse_dt(hearing["scheduled_end"])
    occupants = 0
    for other in db.assignments.values():
        if other["delivery_mode"] != "VRI":
            continue
        if other["service_status"] not in LIVE_SERVICE_STATUSES:
            continue
        other_hearing = db.hearings.get(other["hearing_id"])
        if other_hearing is None or other_hearing["courthouse_id"] != courthouse["id"]:
            continue
        old_start = parse_dt(other_hearing["scheduled_start"])
        old_end = parse_dt(other_hearing["scheduled_end"])
        if old_start <= new_end and new_start <= old_end:
            occupants += 1
    return occupants + 1 > courthouse["vri_concurrent_capacity"]


def effective_rate_schedule(on_date):
    """The schedule governing one calendar date, or None."""
    for schedule in db.rate_schedules.values():
        start = parse_date(schedule["effective_from"])
        through = (
            parse_date(schedule["effective_through"])
            if schedule["effective_through"]
            else None
        )
        if start <= on_date and (through is None or on_date <= through):
            return schedule
    return None


def schedule_for_hearing(hearing):
    return effective_rate_schedule(parse_dt(hearing["scheduled_start"]).date())


def eligible_interpreters(hearing):
    """The ranked eligible pool for one hearing (PRD 3.6)."""
    courthouse = db.courthouses[hearing["courthouse_id"]]
    required = required_min_tier(hearing)
    required_rank = TIER_RANK[required]
    mode = hearing["requested_delivery_mode"]
    ranked = []
    for interpreter in db.interpreters.values():
        if interpreter["roster_status"] != "ACTIVE":
            continue
        best = best_active_credential(interpreter["id"], hearing["language_id"])
        if best is None or TIER_RANK.get(best["tier"], -1) < required_rank:
            continue
        if interpreter["ethics_training_status"] != "COMPLETED":
            continue
        rolling = quality_scores(interpreter["id"])[0]
        if hearing["priority_class"] == "A" and rolling < QUALITY_FLOOR:
            continue
        if mode == "IN_PERSON":
            if not interpreter["accepts_in_person"]:
                continue
        elif not interpreter["accepts_remote"]:
            continue
        if interval_conflict(interpreter["id"], hearing, mode) is not None:
            continue
        same_county = 0 if interpreter["home_county_code"] == courthouse["county_code"] else 1
        ranked.append(
            (
                -TIER_RANK[best["tier"]],
                same_county,
                -rolling,
                interpreter["created_at"],
                interpreter["_seq"],
                interpreter,
            )
        )
    ranked.sort(key=lambda item: item[:5])
    return [item[5] for item in ranked]


# --------------------------------------------------------------------------
# language-access coverage
# --------------------------------------------------------------------------
def coverage_snapshot(courthouse_id, period_start, period_end):
    window_start = day_start(period_start)
    window_end = day_start(period_end)
    pool = []
    for hearing in db.hearings.values():
        if hearing["courthouse_id"] != courthouse_id:
            continue
        if hearing["status"] not in ("SERVED", "UNMET"):
            continue
        start = parse_dt(hearing["scheduled_start"])
        if window_start <= start < window_end:
            pool.append(hearing)
    resolved = len(pool)
    served = len([h for h in pool if h["status"] == "SERVED"])
    unmet = len([h for h in pool if h["status"] == "UNMET"])
    rare_unmet = len(
        [
            h
            for h in pool
            if h["status"] == "UNMET"
            and db.languages[h["language_id"]]["tier_class"] == "RARE"
        ]
    )
    if resolved == 0:
        coverage = Decimal("100.00")
    else:
        coverage = dec(round_half_up_2(dec(100 * served) / dec(resolved)))
    if coverage < CORRECTIVE_FLOOR:
        status = "NON_COMPLIANT"
    elif coverage < COMPLIANT_FLOOR or rare_unmet > 0:
        status = "CORRECTIVE_ACTION_REQUIRED"
    else:
        status = "COMPLIANT"
    by_language = {}
    for hearing in pool:
        code = db.languages[hearing["language_id"]]["code"]
        entry = by_language.setdefault(code, {"resolved": 0, "served": 0, "unmet": 0})
        entry["resolved"] += 1
        if hearing["status"] == "SERVED":
            entry["served"] += 1
        else:
            entry["unmet"] += 1
    ordered = {}
    for code in sorted(by_language):
        ordered[code] = by_language[code]
    return {
        "resolved_hearing_count": resolved,
        "served_hearing_count": served,
        "unmet_hearing_count": unmet,
        "rare_language_unmet_count": rare_unmet,
        "coverage_rate_pct": float(coverage),
        "compliance_status": status,
        "by_language": ordered,
    }
