"""Derived-field recomputation, the compliance posture aggregate and its cascades.

Everything here is recomputed from standing state on every mutation; nothing is
accumulated incrementally.
"""

from datetime import timedelta
from decimal import Decimal

import db
import calculations as calc
from errors import ApiError


# ---------------------------------------------------------------------------
# Ordered collections
# ---------------------------------------------------------------------------

def _ordered(collection):
    return sorted(collection.values(), key=lambda row: row["_seq"])


def agent_licenses(agent_id):
    return [row for row in _ordered(db.state_licenses) if row["agent_id"] == agent_id]


def agent_appointments(agent_id):
    return [row for row in _ordered(db.appointments) if row["agent_id"] == agent_id]


def agent_certifications(agent_id):
    return [row for row in _ordered(db.certifications) if row["agent_id"] == agent_id]


def agent_sessions(agent_id):
    return [row for row in _ordered(db.call_sessions) if row["agent_id"] == agent_id]


def agent_enrollments(agent_id):
    return [row for row in _ordered(db.enrollments) if row["agent_id"] == agent_id]


def agent_complaints(agent_id):
    return [row for row in _ordered(db.complaints) if row["agent_id"] == agent_id]


def agent_coaching(agent_id):
    return [row for row in _ordered(db.coaching) if row["agent_id"] == agent_id]


def agency_agents(agency_id):
    return [row for row in _ordered(db.agents) if row["agency_id"] == agency_id]


def agency_enrollments(agency_id):
    return [row for row in _ordered(db.enrollments) if row["agency_id"] == agency_id]


def agency_sessions(agency_id):
    agent_ids = {a["id"] for a in agency_agents(agency_id)}
    return [row for row in _ordered(db.call_sessions) if row["agent_id"] in agent_ids]


def agency_complaints(agency_id):
    agent_ids = {a["id"] for a in agency_agents(agency_id)}
    return [row for row in _ordered(db.complaints) if row["agent_id"] in agent_ids]


def agency_coaching(agency_id):
    agent_ids = {a["id"] for a in agency_agents(agency_id)}
    return [row for row in _ordered(db.coaching) if row["agent_id"] in agent_ids]


def enrollment_ledger(enrollment_id):
    return [row for row in _ordered(db.ledger_entries) if row["enrollment_id"] == enrollment_id]


def lock_entries_for(rec):
    """Ledger entries presented in a reconciliation's carrier and period."""
    return [
        row for row in _ordered(db.ledger_entries)
        if row["carrier_id"] == rec["carrier_id"] and row["period_month"] == rec["period_month"]
    ]


def touch(entity):
    entity["updated_at"] = db.now()
    entity["version"] = entity.get("version", 0) + 1


# ---------------------------------------------------------------------------
# Derived single-entity fields
# ---------------------------------------------------------------------------

def license_status(license_row):
    return "VALID" if license_row["expires_on"] >= db.now() else "LAPSED"


def scope_expires_on(scope):
    agency = db.agencies.get(scope["agency_id"])
    return scope["captured_on"] + timedelta(days=agency["soa_max_age_days"])


def scope_retained_until(scope):
    agency = db.agencies.get(scope["agency_id"])
    return scope["captured_on"] + timedelta(days=agency["soa_retention_days"])


def recording_retained_until(session):
    agency = db.agencies.get(session["agency_id"])
    return session["started_at"] + timedelta(days=agency["recording_retention_days"])


def recording_status(session):
    if session.get("recording_id") in (None, ""):
        return "MISSING"
    if db.now() > recording_retained_until(session):
        return "EXPIRED"
    return "RECORDED"


def is_usable_scope(scope):
    if scope is None:
        return False
    if scope["status"] != "CAPTURED":
        return False
    clock = db.now()
    if clock < scope["captured_on"]:
        return False
    return clock <= scope_expires_on(scope)


def coaching_overdue_days(assignment):
    due_on = assignment["due_on"]
    clock = db.now()
    if clock <= due_on:
        return 0
    return db.whole_days(due_on, clock)


def disenrolled_day_number(enrollment):
    if enrollment.get("disenrollment_date") is None:
        return None
    return db.whole_days(enrollment["effective_date"], enrollment["disenrollment_date"])


def is_rapid(enrollment, agency):
    day = disenrolled_day_number(enrollment)
    if day is None:
        return None
    return day <= agency["rapid_disenrollment_day_limit"]


# ---------------------------------------------------------------------------
# Agent counts and risk score
# ---------------------------------------------------------------------------

def recompute_agent_counts(agent):
    valid_licenses = [row for row in agent_licenses(agent["id"]) if license_status(row) == "VALID"]
    certified = [row for row in agent_certifications(agent["id"]) if row["status"] == "CERTIFIED"]
    appointed = [row for row in agent_appointments(agent["id"]) if row["status"] == "APPOINTED"]
    live = [row for row in agent_sessions(agent["id"]) if row["status"] == "IN_PROGRESS"]
    active = [row for row in agent_enrollments(agent["id"]) if row["disenrollment_status"] == "ENROLLED"]
    open_coaching = [
        row for row in agent_coaching(agent["id"])
        if row["status"] in ("ASSIGNED", "IN_PROGRESS", "OVERDUE")
    ]
    agent["licensed_state_count"] = len(valid_licenses)
    agent["certified_carrier_count"] = len(certified)
    agent["appointed_carrier_count"] = len(appointed)
    agent["live_call_count"] = len(live)
    agent["active_enrollment_count"] = len(active)
    agent["open_coaching_count"] = len(open_coaching)
    agent["coaching_flag"] = len(open_coaching) > 0


def recompute_risk_score(agent):
    session_penalty = Decimal("0.00")
    for session in agent_sessions(agent["id"]):
        if session["status"] not in ("COMPLETED", "DROPPED"):
            continue
        points = Decimal("0.0")
        if session.get("recording_id") in (None, "") or recording_status(session) == "MISSING":
            points += calc.SESSION_RECORDING_PENALTY
        if session.get("disclaimer_delivered") is not True:
            points += calc.SESSION_DISCLAIMER_PENALTY
        scope = db.scopes.get(session.get("scope_of_appointment_id"))
        if session.get("scope_of_appointment_id") is None or scope is None \
                or not scope.get("plan_types_authorized"):
            points += calc.SESSION_SCOPE_PENALTY
        session_penalty += calc.r2(points)

    enrollment_penalty = calc.RAPID_DISENROLLMENT_PENALTY * Decimal(
        len([row for row in agent_enrollments(agent["id"])
             if row["disenrollment_status"] == "RAPID_DISENROLLED"]))

    window_start = db.now() - timedelta(days=calc.RISK_WINDOW_DAYS)
    complaint_penalty = Decimal("0.00")
    for complaint in agent_complaints(agent["id"]):
        if complaint["status"] not in ("SUBSTANTIATED", "APPEALED"):
            continue
        substantiated_on = complaint.get("substantiated_on")
        if substantiated_on is None or substantiated_on < window_start:
            continue
        complaint_penalty += calc.COMPLAINT_SEVERITY_POINTS[complaint["severity"]]

    coaching_penalty = calc.COACHING_ASSIGNMENT_POINTS * Decimal(
        len([row for row in agent_coaching(agent["id"])
             if row["status"] in ("ASSIGNED", "IN_PROGRESS", "OVERDUE")]))

    overdue_penalty = Decimal("0.00")
    for row in agent_coaching(agent["id"]):
        if row["status"] == "OVERDUE":
            overdue_penalty += calc.OVERDUE_DAY_POINTS * Decimal(max(0, coaching_overdue_days(row)))

    agent["compliance_risk_score"] = calc.r2(
        session_penalty + enrollment_penalty + complaint_penalty + coaching_penalty + overdue_penalty
    )


def recompute_agent(agent):
    recompute_agent_counts(agent)
    recompute_risk_score(agent)


# ---------------------------------------------------------------------------
# Overdue coaching sweep
# ---------------------------------------------------------------------------

def sweep_overdue(agent_ids=None):
    """Move any ASSIGNED / IN_PROGRESS assignment with overdue_days >= 1 into
    OVERDUE. Returns the set of affected agent ids."""
    affected = set()
    for row in _ordered(db.coaching):
        if agent_ids is not None and row["agent_id"] not in agent_ids:
            continue
        if row["status"] in ("ASSIGNED", "IN_PROGRESS") and coaching_overdue_days(row) >= 1:
            row["status"] = "OVERDUE"
            touch(row)
            affected.add(row["agent_id"])
    for agent_id in affected:
        agent = db.agents.get(agent_id)
        if agent is not None:
            recompute_agent(agent)
    return affected


# ---------------------------------------------------------------------------
# Aggregate counts
# ---------------------------------------------------------------------------

def recompute_open_complaint_count(agency):
    open_rows = [
        row for row in agency_complaints(agency["id"])
        if row["status"] in ("OPEN", "UNDER_REVIEW")
    ]
    agency["open_complaint_count"] = len(open_rows)


def recompute_substantiated_rate(agency):
    numerator = len([
        row for row in agency_complaints(agency["id"])
        if row["status"] in ("SUBSTANTIATED", "APPEALED")
    ])
    denominator = len([
        row for row in agency_sessions(agency["id"])
        if row["status"] in ("COMPLETED", "AMENDED")
    ])
    agency["substantiated_complaint_rate"] = calc.r6(
        Decimal(numerator) / Decimal(max(1, denominator))
    )


def recompute_balance(agency):
    total = Decimal("0.00")
    for row in _ordered(db.ledger_entries):
        enrollment = db.enrollments.get(row["enrollment_id"])
        if enrollment is None or enrollment["agency_id"] != agency["id"]:
            continue
        if row["status"] in ("PROVISIONAL", "FINALIZED"):
            total += calc.dec(row["amount_cents"])
    agency["commission_balance_cents"] = calc.r2(total)


def recompute_loss_ratio(agency):
    numerator = 0
    for row in _ordered(db.ledger_entries):
        enrollment = db.enrollments.get(row["enrollment_id"])
        if enrollment is None or enrollment["agency_id"] != agency["id"]:
            continue
        if row["entry_type"] == "CHARGEBACK" and row["status"] == "FINALIZED" \
                and calc.dec(row["amount_cents"]) < 0:
            numerator += 1
    live_book = len([
        row for row in db.enrollments.values()
        if row["agency_id"] == agency["id"] and row["disenrollment_status"] == "ENROLLED"
    ])
    agency["loss_ratio"] = calc.r6(Decimal(numerator) / Decimal(max(1, live_book)))


def recompute_plan_enrolled_count(plan):
    plan["enrolled_member_count"] = len([
        row for row in db.enrollments.values()
        if row["plan_id"] == plan["id"] and row["disenrollment_status"] == "ENROLLED"
    ])


def recompute_member_enrollment_count(member):
    member["enrollment_count"] = len([
        row for row in db.enrollments.values() if row["member_id"] == member["id"]
    ])


def recompute_reconciliation(rec):
    variant = rec.get("internal_total_variant", "PROVISIONAL")
    total = Decimal("0.00")
    for row in lock_entries_for(rec):
        if row["status"] == "REVERSED":
            continue
        if variant == "FINAL" and row["status"] != "FINALIZED":
            continue
        total += calc.dec(row["amount_cents"])
    rec["internal_total_cents"] = calc.r2(total)
    reported = rec.get("carrier_reported_total_cents")
    if reported is None:
        rec["variance_cents"] = None
    else:
        rec["variance_cents"] = calc.r2(calc.dec(reported) - rec["internal_total_cents"])
    rec["variance_variant"] = variant


def refresh_period(carrier_id, period_month):
    for rec in _ordered(db.reconciliations):
        if rec["carrier_id"] == carrier_id and rec["period_month"] == period_month:
            recompute_reconciliation(rec)


# ---------------------------------------------------------------------------
# Posture aggregate and cascades
# ---------------------------------------------------------------------------

_LEVEL = {"OPEN": 0, "RESTRICTED": 1, "FROZEN": 2}


def recomputed_posture(agency):
    strike_window_start = db.now() - timedelta(days=calc.POSTURE_STRIKE_WINDOW_DAYS)
    strike_count = len([
        row for row in agency_complaints(agency["id"])
        if row["status"] in ("SUBSTANTIATED", "APPEALED")
        and row.get("substantiated_on") is not None
        and row["substantiated_on"] >= strike_window_start
    ])
    loss_ratio = calc.dec(agency["loss_ratio"])
    rate = calc.dec(agency["substantiated_complaint_rate"])
    if strike_count >= calc.POSTURE_FREEZE_STRIKES:
        return "FROZEN"
    if loss_ratio >= calc.POSTURE_FREEZE_LOSS_RATIO:
        return "FROZEN"
    if rate >= calc.POSTURE_RESTRICT_THRESHOLD:
        return "RESTRICTED"
    overdue = any(
        coaching_overdue_days(row) >= calc.POSTURE_OVERDUE_COACHING_DAYS
        for row in agency_coaching(agency["id"])
    )
    if overdue:
        return "RESTRICTED"
    return "OPEN"


def _posture_refresh_rates(agency):
    recompute_substantiated_rate(agency)
    recompute_loss_ratio(agency)


def _cascade_open_to_restricted(agency):
    for agent in agency_agents(agency["id"]):
        if agent["status"] == "ACTIVE":
            agent["status"] = "SUSPENDED"
            touch(agent)
    dropped_agents = set()
    for session in agency_sessions(agency["id"]):
        if session["status"] in ("RINGING", "IN_PROGRESS"):
            session["status"] = "DROPPED"
            session["actual_end_at"] = db.now()
            touch(session)
            dropped_agents.add(session["agent_id"])
    for agent_id in dropped_agents:
        agent = db.agents.get(agent_id)
        if agent is not None:
            recompute_agent_counts(agent)
    _posture_refresh_rates(agency)
    if calc.dec(agency["substantiated_complaint_rate"]) >= calc.POSTURE_RESTRICT_THRESHOLD:
        recompute_loss_ratio(agency)


def _withdraw_for_freeze(agency):
    for enrollment in agency_enrollments(agency["id"]):
        if enrollment["submission_status"] not in ("SUBMITTED", "ACKNOWLEDGED"):
            continue
        enrollment["submission_status"] = "WITHDRAWN"
        touch(enrollment)
        non_reversed = [row for row in enrollment_ledger(enrollment["id"]) if row["status"] != "REVERSED"]
        if non_reversed:
            total = Decimal("0.00")
            for row in non_reversed:
                total += calc.dec(row["amount_cents"])
            post_entry(enrollment, entry_type="REVERSAL", amount_cents=-calc.r2(total))
    recompute_balance(agency)
    _posture_refresh_rates(agency)


def _cascade_open_to_frozen(agency):
    for agent in agency_agents(agency["id"]):
        if agent["status"] == "ACTIVE":
            agent["status"] = "SUSPENDED"
            touch(agent)
    for session in agency_sessions(agency["id"]):
        if session["status"] in ("RINGING", "IN_PROGRESS"):
            session["status"] = "DROPPED"
            session["actual_end_at"] = db.now()
            touch(session)
    _withdraw_for_freeze(agency)
    for agent in agency_agents(agency["id"]):
        recompute_agent(agent)


def _cascade_restricted_to_frozen(agency):
    _withdraw_for_freeze(agency)
    carrier_ids = {
        plan["carrier_id"] for plan in db.plans.values()
        if plan.get("carrier_id")
    }
    for rec in _ordered(db.reconciliations):
        if rec["carrier_id"] in carrier_ids and rec["status"] == "DISPUTED":
            rec["status"] = "OPEN"
            touch(rec)
            recompute_reconciliation(rec)
    recompute_loss_ratio(agency)
    for agent in agency_agents(agency["id"]):
        recompute_agent(agent)


def apply_posture(agency, new_posture):
    """Run the cascade for the posture change, if the transition is declared."""
    old = agency["compliance_posture"]
    if new_posture == old:
        return
    if _LEVEL.get(new_posture, 0) < _LEVEL.get(old, 0):
        # Recovery is the compliance officer's posture-reset, never automatic.
        return
    agency["compliance_posture"] = new_posture
    agency["posture_since"] = db.now()
    touch(agency)
    if old == "OPEN" and new_posture == "RESTRICTED":
        _cascade_open_to_restricted(agency)
    elif old == "OPEN" and new_posture == "FROZEN":
        _cascade_open_to_frozen(agency)
    elif old == "RESTRICTED" and new_posture == "FROZEN":
        _cascade_restricted_to_frozen(agency)


def recompute_posture(agency):
    """Recompute rates, sweep overdue coaching and run any due cascade."""
    if agency is None:
        return
    sweep_overdue({agent["id"] for agent in agency_agents(agency["id"])})
    recompute_substantiated_rate(agency)
    recompute_loss_ratio(agency)
    target = recomputed_posture(agency)
    apply_posture(agency, target)


# ---------------------------------------------------------------------------
# Ledger posting
# ---------------------------------------------------------------------------

def post_entry(enrollment, entry_type, amount_cents=None, period_month=None,
               memo=None, reconciliation_id=None, clawback_pct=None, status="PROVISIONAL"):
    plan = db.plans.get(enrollment["plan_id"])
    carrier = db.carriers.get(enrollment["carrier_id"])
    if amount_cents is None:
        if entry_type == "INITIAL":
            amount_cents = calc.annual_initial(plan, carrier)
        elif entry_type == "RENEWAL":
            amount_cents = calc.annual_renewal(plan, carrier)
        elif entry_type == "ADJUSTMENT":
            amount_cents = calc.default_adjustment_amount(plan, carrier)
        else:
            amount_cents = Decimal("0.00")
    if period_month is None:
        # Every entry accrues against the enrollment it is posted for, so the
        # period it is presented in follows that enrollment's submission month
        # rather than the wall clock the later request happened to arrive on.
        period_month = enrollment["submitted_on"].strftime("%Y-%m")
    row = {
        "id": db.new_id(),
        "_seq": db.next_seq(),
        "created_at": db.now(),
        "updated_at": db.now(),
        "version": 1,
        "enrollment_id": enrollment["id"],
        "carrier_id": enrollment["carrier_id"],
        "carrier_reconciliation_id": reconciliation_id,
        "entry_type": entry_type,
        "amount_cents": calc.r2(amount_cents),
        "period_month": period_month,
        "posted_on": db.now(),
        "status": status,
        "clawback_pct_applied": clawback_pct,
        "memo": memo,
    }
    db.ledger_entries[row["id"]] = row
    return row


def reversal_base(enrollment_id):
    total = Decimal("0.00")
    for row in enrollment_ledger(enrollment_id):
        if row["status"] != "REVERSED":
            total += calc.dec(row["amount_cents"])
    return total


def reopen_open_reconciliation(carrier_id, period_month):
    rec = active_reconciliation(carrier_id, period_month)
    if rec is not None:
        recompute_reconciliation(rec)


def stabilize_period(carrier_id, period_month):
    """Recompute the month's standing reconciliation period.

    Called *after* a new entry has been inserted, so the period the entry is
    presented in is recomputed with the entry already in place.
    """
    rec = standing_reconciliation(carrier_id, period_month)
    if rec is None:
        return None
    recompute_reconciliation(rec)
    return rec["id"]


def present_entry(row, carrier_id=None, period_month=None):
    """Attach a freshly posted entry to its month's standing period and recompute.

    PRD §2.8 gives every entry the `carrier_reconciliation_id` of "the
    reconciliation period it is presented in", and a posting recomputes both the
    agency balance and the named period's `internal_total_cents`.
    """
    carrier_id = carrier_id or row["carrier_id"]
    period_month = period_month or row["period_month"]
    rec_id = stabilize_period(carrier_id, period_month)
    if rec_id is not None:
        row["carrier_reconciliation_id"] = rec_id
    return row


def standing_reconciliation(carrier_id, period_month):
    """The reconciliation period a ledger entry for that carrier and month is
    presented in: the OPEN one if the month is still open, else the most recently
    created period for it. Returns None when no period has been opened."""
    candidates = [
        rec for rec in _ordered(db.reconciliations)
        if rec["carrier_id"] == carrier_id and rec["period_month"] == period_month
    ]
    if not candidates:
        return None
    for rec in candidates:
        if rec["status"] == "OPEN":
            return rec
    return candidates[-1]


def active_reconciliation(carrier_id, period_month):
    for rec in _ordered(db.reconciliations):
        if rec["carrier_id"] == carrier_id and rec["period_month"] == period_month \
                and rec["status"] == "OPEN":
            return rec
    return None


# ---------------------------------------------------------------------------
# Commissioner projections
# ---------------------------------------------------------------------------

def qualifying_enrollments(agency_id, window_start, window_end):
    rows = []
    for enrollment in agency_enrollments(agency_id):
        if enrollment["submission_status"] not in ("SUBMITTED", "ACKNOWLEDGED", "EFFECTUATED"):
            continue
        if enrollment["effective_date"] >= window_start and enrollment["effective_date"] < window_end:
            rows.append(enrollment)
    return rows


def provisional_book_commission(agency_id, window_days=calc.FORWARD_WINDOW_DAYS):
    window_start = db.now()
    window_end = window_start + timedelta(days=window_days)
    total = Decimal("0.00")
    rows = qualifying_enrollments(agency_id, window_start, window_end)
    for enrollment in rows:
        plan = db.plans.get(enrollment["plan_id"])
        carrier = db.carriers.get(enrollment["carrier_id"])
        initial_term, renewal_term = calc.provisional_terms(plan, carrier, enrollment["effective_date"])
        total += initial_term
        total += renewal_term
    return calc.r2(total), len(rows), window_start, window_end


def earned_pass(agency_id):
    """Chronological as-earned pass; also attributes each enrollment's own
    contribution. Returns (agency_total, {enrollment_id: contribution})."""
    enrollments = [
        row for row in agency_enrollments(agency_id)
        if row["submission_status"] == "EFFECTUATED"
    ]
    enrollments.sort(key=lambda row: (row["effective_date"], row["created_at"]))
    contributions = {}
    running_effective_date = None
    earned = Decimal("0.00")
    clock = db.now()
    for enrollment in enrollments:
        carrier = db.carriers.get(enrollment["carrier_id"])
        plan = db.plans.get(enrollment["plan_id"])
        effective_date = enrollment["effective_date"]
        if running_effective_date is None or \
                (effective_date - running_effective_date).days > calc.LAPSE_GAP_DAYS:
            rate = calc.dec(carrier["initial_commission_rate_pct"])
        else:
            rate = calc.dec(carrier["renewal_commission_rate_pct"])
        running_effective_date = effective_date
        if enrollment.get("disenrollment_date") is not None:
            cutoff = min(clock, enrollment["disenrollment_date"])
        else:
            cutoff = clock
        if enrollment["disenrollment_status"] != "ENROLLED":
            billed_months = 1
        else:
            billed_months = max(1, db.whole_months(effective_date, cutoff))
        contribution = calc.r2(calc.dec(plan["monthly_premium_cents"]) * billed_months * rate)
        contributions[enrollment["id"]] = contribution
        earned += contribution
    return earned, contributions


def earned_commission_cents(agency_id):
    return earned_pass(agency_id)[0]


def refresh_earned_for_agency(agency_id):
    earned, contributions = earned_pass(agency_id)
    for enrollment in agency_enrollments(agency_id):
        enrollment["final_commission_cents"] = contributions.get(enrollment["id"], Decimal("0.00"))
    return earned


def provisional_for_enrollment(enrollment):
    plan = db.plans.get(enrollment["plan_id"])
    carrier = db.carriers.get(enrollment["carrier_id"])
    return calc.provisional_commission_cents(plan, carrier, enrollment["effective_date"])


# ---------------------------------------------------------------------------
# Requirement helpers shared by routes
# ---------------------------------------------------------------------------

def require_scope_usable(scope, agent_id, plan_type=None):
    """PRD §2.13's scope gate, in the order the precedence chain fixes:
    ERR_SCOPE_OF_APPOINTMENT_MISSING -> ERR_SCOPE_AGENT_MISMATCH ->
    ERR_PLAN_TYPE_NOT_AUTHORIZED.

    §2.13 states the gate as "a usable, unconsumed `CAPTURED` scope must exist
    with a non-empty authorization list, else `ERR_SCOPE_OF_APPOINTMENT_MISSING`",
    so every way a scope can fail to be a usable CAPTURED scope — absent, empty
    authorization, captured in the future, past `expires_on`, or already moved
    off `CAPTURED` — reports the missing-scope identifier.
    """
    if scope is None or not scope.get("plan_types_authorized") or db.now() < scope["captured_on"]:
        raise ApiError("ERR_SCOPE_OF_APPOINTMENT_MISSING",
                       "No usable captured scope of appointment exists for this member.")
    if scope["agent_id"] != agent_id:
        raise ApiError("ERR_SCOPE_AGENT_MISMATCH",
                       "The scope of appointment was captured by a different agent.")
    if scope["status"] != "CAPTURED" or db.now() > scope_expires_on(scope):
        raise ApiError("ERR_SCOPE_OF_APPOINTMENT_MISSING",
                       "The scope of appointment is not a usable CAPTURED scope.")
    if plan_type is not None and plan_type not in scope["plan_types_authorized"]:
        raise ApiError("ERR_PLAN_TYPE_NOT_AUTHORIZED",
                       "The plan type under discussion is not authorized by the scope.")


def require_staffing_authority(agent, plan):
    """APPOINTED appointment with the carrier, VALID license for the plan's
    state, CERTIFIED certification spanning the plan's product type."""
    has_appointment = any(
        row["status"] == "APPOINTED" and row["carrier_id"] == plan["carrier_id"]
        and row["state_code"] == plan["state_code"]
        for row in agent_appointments(agent["id"])
    )
    has_certification = any(
        row["status"] == "CERTIFIED" and row["carrier_id"] == plan["carrier_id"]
        and row["product_type"] == plan["plan_type"]
        for row in agent_certifications(agent["id"])
    )
    has_license = any(
        row["state_code"] == plan["state_code"] and license_status(row) == "VALID"
        for row in agent_licenses(agent["id"])
    )
    if not (has_appointment and has_certification and has_license):
        raise ApiError("ERR_AGENT_NOT_APPOINTED",
                       "The agent lacks the appointment, license or certification required.")