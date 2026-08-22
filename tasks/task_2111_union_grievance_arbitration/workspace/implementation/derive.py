"""Derived fields, calculation rules and resource serializers.

Every rule here traces to a numbered section of the PRD; the section is named
in the docstring or the comment above the rule.
"""

from decimal import Decimal, ROUND_CEILING

from core import (
    db, now, to_dec, round_half_up, bps_rate, fmt_dt, num_out,
    add_days, floor_days, ceil_half, order_by,
)

# --------------------------------------------------------------------------
# Named constants (SCAFFOLD 1.3 `constants` blocks)
# --------------------------------------------------------------------------
ANALYST_AUTHORITY_CENTS = 50000
PRECEDENT_SETTING_MULTIPLIER = Decimal("1.25")
REINSTATEMENT_FLOOR_CENTS = 200000
REINSTATEMENT_HOURS = 40
TERM_LOADING = {
    "NONE": 0,
    "RECORD_EXPUNGEMENT": 25000,
    "SENIORITY_RESTORATION": 75000,
    "POLICY_CHANGE": 150000,
}
SCOPE_FACTOR = {
    "UNIT_WIDE": Decimal("1.00"),
    "DEPARTMENT": Decimal("0.75"),
    "INDIVIDUAL": Decimal("0.50"),
}
OFFER_VALIDITY_DAYS = 10

SHARE_TIER_1_CENTS = 500000
SHARE_TIER_2_CENTS = 2000000
ADMIN_FEE_BPS = 800
COST_OK_CEILING_CENTS = 1000000
COST_WATCH_CEILING_CENTS = 5000000

PREP_ALLOWANCE_HOURS = Decimal("1.5")
QUARTER_HOUR = Decimal("0.25")
MAX_DAILY_RELEASE_HOURS = Decimal("10.0")

STUDY_DAYS = 1
TRANSCRIPT_PER_DAY_CENTS = 120000
RETAINER_DAYS = 2

DAYS_PER_YEAR = 365
ENFORCEMENT_COUNSEL_CENTS = 150000

PANEL_HORIZON_DAYS = 90
BRIEF_DAYS_AFTER_HEARING = 30
PREP_RUNWAY_DAYS = 21

AUTHORITY_LADDER = ["ANALYST", "DIRECTOR", "NEGOTIATOR", "BOARD"]

# --------------------------------------------------------------------------
# Enumerations
# --------------------------------------------------------------------------
CLAUSE_CATEGORIES = {"DISCIPLINE", "PAY", "SENIORITY", "SAFETY", "LEAVE", "SUBCONTRACTING"}
CLASSIFICATIONS = {"PRODUCTION", "MAINTENANCE", "CLERICAL", "SUPERVISOR"}
EMPLOYMENT_STATUSES = {"ACTIVE", "SUSPENDED", "TERMINATED", "REINSTATED"}
PRECEDENT_OUTCOMES = {"SUSTAINED", "DENIED", "SPLIT"}
BINDING_SCOPES = {"UNIT_WIDE", "DEPARTMENT", "INDIVIDUAL"}
PANEL_SOURCES = {"AAA", "FMCS", "PERMANENT_UMPIRE"}
GRIEVANCE_STATUSES = {
    "FILED", "STEP_MEETING_SCHEDULED", "AWAITING_RESPONSE", "ANSWERED", "APPEALED",
    "ARBITRATION_DEMANDED", "AWARDED", "SETTLED", "WITHDRAWN", "CONSOLIDATED", "CLOSED",
}
TIMELINESS_STATES = {"TIMELY", "TOLLED", "EMPLOYER_DEFAULT", "UNION_DEFAULT", "BARRED"}
STEP_STATUSES = {"SCHEDULED", "HELD", "ANSWERED", "DEEMED_DENIED", "CANCELLED"}
DISPOSITIONS = {"GRANTED", "PARTIAL", "DENIED"}
OFFER_PARTIES = {"UNION", "EMPLOYER"}
REMEDY_TERMS = {"NONE", "RECORD_EXPUNGEMENT", "SENIORITY_RESTORATION", "POLICY_CHANGE", "REINSTATEMENT"}
OFFER_STATUSES = {"DRAFT", "AUTHORIZED", "COUNTERED", "ACCEPTED", "REJECTED", "LAPSED", "VOIDED"}
DECISIONS = {"ACCEPT", "REJECT", "COUNTER"}
DEMAND_STATUSES = {
    "DEMANDED", "PANEL_ISSUED", "STRIKING", "ARBITRATOR_SELECTED",
    "HEARING_SCHEDULED", "HEARD", "AWARDED", "WITHDRAWN", "SETTLED_PRE_HEARING",
}
PREP_STATUSES = {"PREP_NOT_STARTED", "PREP_DEFICIENT", "EXHIBITS_FILED", "BRIEFS_FILED", "PREP_READY"}
FILING_TYPES = {"EXHIBIT_LIST", "BRIEF", "STIPULATION"}
WITNESS_TYPES = {"FACT", "EXPERT", "CHARACTER"}
WITNESS_STATUSES = {"INVITED", "CONFIRMED", "TESTIFIED", "EXCUSED", "NO_SHOW"}
AWARD_OUTCOMES = {"SUSTAINED", "DENIED", "SPLIT"}
AWARD_STATUSES = {
    "ISSUED", "IMPLEMENTATION_PENDING", "PARTIALLY_IMPLEMENTED",
    "IMPLEMENTED", "COMPLIANCE_DISPUTED",
}
COST_CATEGORIES = {"ARBITRATOR_FEE", "TRANSCRIPT", "COUNSEL", "RELEASE_TIME", "TRAVEL", "FILING"}
BEARING_PARTIES = {"UNION", "EMPLOYER", "SPLIT"}
COST_STATUSES = {"POSTED", "VOIDED"}

GRIEVANCE_TERMINAL = {"SETTLED", "WITHDRAWN", "CONSOLIDATED", "CLOSED"}
DEMAND_LIVE_FOR_CASCADE = {
    "DEMANDED", "PANEL_ISSUED", "STRIKING", "ARBITRATOR_SELECTED", "HEARING_SCHEDULED",
}
ARBITRATION_COST_CATEGORIES = {"ARBITRATOR_FEE", "TRANSCRIPT", "RELEASE_TIME", "TRAVEL"}


# --------------------------------------------------------------------------
# Collection helpers
# --------------------------------------------------------------------------
def steps_of(grievance_id):
    return [s for s in db.grievance_steps.values() if s["grievance_id"] == grievance_id]


def offers_of(grievance_id):
    return [o for o in db.settlement_offers.values() if o["grievance_id"] == grievance_id]


def demands_of(grievance_id):
    return [d for d in db.arbitration_demands.values() if d["grievance_id"] == grievance_id]


def cost_entries_of(grievance_id):
    return [c for c in db.cost_entries.values() if c["grievance_id"] == grievance_id]


def strikes_of(demand_id):
    return [s for s in db.panel_strikes.values() if s["arbitration_demand_id"] == demand_id]


def assignments_of(demand_id):
    return [w for w in db.witness_assignments.values() if w["arbitration_demand_id"] == demand_id]


def award_of(demand_id):
    for a in db.awards.values():
        if a["arbitration_demand_id"] == demand_id:
            return a
    return None


def clauses_of(unit_id):
    return [c for c in db.contract_clauses.values() if c["bargaining_unit_id"] == unit_id]


# --------------------------------------------------------------------------
# BargainingUnit derivations (PRD 3.1)
# --------------------------------------------------------------------------
def unit_status(unit):
    """ACTIVE while the clock is before contract_expiry_date, EXPIRED from that
    instant onward."""
    return "ACTIVE" if now() < unit["contract_expiry_date"] else "EXPIRED"


def unit_open_grievance_count(unit):
    return sum(
        1 for g in db.grievances.values()
        if g["bargaining_unit_id"] == unit["id"] and g["status"] not in GRIEVANCE_TERMINAL
    )


# --------------------------------------------------------------------------
# Trend analysis (PRD 3.9 / calculations.supervisor_clause_trend_metrics)
# --------------------------------------------------------------------------
def adverse_outcome(grievance):
    """True when the grievance ended adversely for the employer; counted once."""
    for demand in demands_of(grievance["id"]):
        award = award_of(demand["id"])
        if award is not None and award["outcome"] in ("SUSTAINED", "SPLIT"):
            return True
    if grievance["status"] in ("SETTLED", "CLOSED") and grievance["settled_amount_cents"] > 0:
        return True
    for step in steps_of(grievance["id"]):
        if step["disposition"] in ("GRANTED", "PARTIAL"):
            return True
    return False


def supervisor_scorecard(employee):
    rows = [g for g in db.grievances.values() if g["respondent_supervisor_id"] == employee["id"]]
    open_count = sum(1 for g in rows if g["status"] not in GRIEVANCE_TERMINAL)
    closed_rows = [g for g in rows if g["status"] in ("SETTLED", "WITHDRAWN", "CLOSED")]
    closed_count = len(closed_rows)
    sustained_against = sum(1 for g in closed_rows if adverse_outcome(g))
    return {
        "open_grievance_count": open_count,
        "closed_grievance_count": closed_count,
        "sustained_against_count": sustained_against,
        "adverse_rate_bps": bps_rate(sustained_against, closed_count),
    }


def clause_scorecard(clause):
    rows = [g for g in db.grievances.values() if g["clause_id"] == clause["id"]]
    non_consolidated = [g for g in rows if g["status"] != "CONSOLIDATED"]
    filed_count = len(non_consolidated)
    sustained_count = sum(1 for g in non_consolidated if adverse_outcome(g))
    denied_count = sum(
        1 for g in rows
        if g["status"] in ("SETTLED", "WITHDRAWN", "CLOSED") and not adverse_outcome(g)
    )
    return {
        "filed_count": filed_count,
        "sustained_count": sustained_count,
        "denied_count": denied_count,
        "sustain_rate_bps": bps_rate(sustained_count, filed_count),
    }


def witness_release_hours_ytd(employee):
    total = Decimal(0)
    for w in db.witness_assignments.values():
        if w["employee_id"] == employee["id"] and w["status"] in ("CONFIRMED", "TESTIFIED"):
            total += w["release_hours"]
    return total


# --------------------------------------------------------------------------
# Grievance timeliness posture (PRD 3.3 / calculations.grievance_timeliness_posture)
# --------------------------------------------------------------------------
def active_steps(grievance_id):
    return [s for s in steps_of(grievance_id) if s["status"] != "CANCELLED"]


def latest_step(grievance_id):
    """Greatest step_number; where two share it, the greater created_at wins."""
    candidates = active_steps(grievance_id)
    if not candidates:
        return None
    ordered = order_by(candidates, "step_number", "created_at")
    return ordered[-1]


def step_at_number(grievance_id, number):
    candidates = [s for s in active_steps(grievance_id) if s["step_number"] == number]
    if not candidates:
        return None
    return order_by(candidates, "created_at")[-1]


def resolution_at(step):
    if step is None:
        return None
    if step["status"] == "ANSWERED":
        return step["responded_at"]
    if step["status"] == "DEEMED_DENIED":
        return step["response_due_at"]
    return None


def appeal_deadline_at(grievance):
    unit = db.bargaining_units.get(grievance["bargaining_unit_id"])
    resolved = resolution_at(latest_step(grievance["id"]))
    if resolved is None or unit is None:
        return None
    return add_days(resolved, unit["appeal_window_days"])


def arbitration_deadline_at(grievance):
    unit = db.bargaining_units.get(grievance["bargaining_unit_id"])
    if unit is None or grievance["current_step"] != 3:
        return None
    resolved = resolution_at(step_at_number(grievance["id"], 3))
    if resolved is None:
        return None
    return add_days(resolved, unit["arbitration_demand_days"])


def compute_posture(grievance):
    """The seven ordered branches of PRD 3.3; the first match wins."""
    if grievance["status"] in GRIEVANCE_TERMINAL:
        return grievance["timeliness_state"]

    step = latest_step(grievance["id"])
    if step is None:
        return "TIMELY"

    resolved = resolution_at(step)
    instant = now()

    arb_deadline = arbitration_deadline_at(grievance)
    if (grievance["current_step"] == 3
            and resolved is not None
            and not demands_of(grievance["id"])
            and arb_deadline is not None
            and instant > arb_deadline):
        return "BARRED"

    app_deadline = appeal_deadline_at(grievance)
    if (resolved is not None
            and grievance["status"] == "ANSWERED"
            and app_deadline is not None
            and instant > app_deadline):
        return "UNION_DEFAULT"

    if step["status"] == "DEEMED_DENIED" or (
            step["status"] == "ANSWERED" and step["late_by_days"] > 0):
        return "EMPLOYER_DEFAULT"

    if step["status"] == "SCHEDULED" and step["extension_days"] > 0:
        return "TOLLED"

    return "TIMELY"


def refresh_timeliness(grievance):
    """Re-derive the posture unless the grievance has become terminal, in which
    case it stays frozen at the value it held at that instant."""
    if grievance["status"] not in GRIEVANCE_TERMINAL:
        grievance["timeliness_state"] = compute_posture(grievance)
    return grievance["timeliness_state"]


# --------------------------------------------------------------------------
# Step response deadline (PRD 3.3 / calculations.step_response_deadline)
# --------------------------------------------------------------------------
def step_response_deadline(step, grievance, unit, clause):
    base_days = {
        1: unit["step1_response_days"],
        2: unit["step2_response_days"],
        3: unit["step3_response_days"],
    }[step["step_number"]]
    if clause["expedited"]:
        base_days = ceil_half(base_days)
    total_days = base_days + step["extension_days"]
    return add_days(step["meeting_held_at"], total_days)


# --------------------------------------------------------------------------
# Filing window (PRD 3.2 / calculations.grievance_filing_timeliness)
# --------------------------------------------------------------------------
def filing_window_days(unit, clause):
    window = unit["filing_window_days"]
    if clause["expedited"]:
        window = ceil_half(window)
    return window


# --------------------------------------------------------------------------
# Settlement exposure & authority tier
# (PRD 3.4 / calculations.settlement_exposure_authority_tier)
# --------------------------------------------------------------------------
def settlement_exposure(offer_terms, grievant, clause, unit, precedent):
    """Four normative stages: price, multiply-then-cap, tier, precedent review."""
    # stage 1 — raw exposure
    back_pay_cents = round_half_up(
        to_dec(offer_terms["back_pay_hours"]) * to_dec(grievant["hourly_rate_cents"]))
    terms = offer_terms["remedy_terms"]
    if terms == "REINSTATEMENT":
        term_loading = max(
            REINSTATEMENT_FLOOR_CENTS,
            grievant["hourly_rate_cents"] * REINSTATEMENT_HOURS,
        )
    else:
        term_loading = TERM_LOADING[terms]
    raw_exposure = offer_terms["monetary_cents"] + back_pay_cents + term_loading

    # stage 2 — precedent-setting multiplier BEFORE the clause cap
    multiplier = PRECEDENT_SETTING_MULTIPLIER if offer_terms["precedent_setting"] else Decimal("1.00")
    exposure_cents = round_half_up(to_dec(raw_exposure) * multiplier)
    if clause["monetary_cap_cents"] is not None:
        exposure_cents = min(exposure_cents, clause["monetary_cap_cents"])

    # stage 3 — base tier from the CAPPED exposure, every comparison inclusive
    if exposure_cents <= ANALYST_AUTHORITY_CENTS:
        base_tier = "ANALYST"
    elif exposure_cents <= unit["director_authority_cents"]:
        base_tier = "DIRECTOR"
    elif exposure_cents <= unit["negotiator_authority_cents"]:
        base_tier = "NEGOTIATOR"
    else:
        base_tier = "BOARD"

    # stage 4 — precedent review escalates by exactly one level, never more
    if precedent is None:
        deviation_bps = None
        authority_tier = base_tier
    else:
        adjusted = round_half_up(
            to_dec(precedent["monetary_value_cents"]) * SCOPE_FACTOR[precedent["binding_scope"]])
        denominator = adjusted if adjusted != 0 else 1
        deviation_bps = round_half_up(
            to_dec(abs(exposure_cents - adjusted)) * 10000 / to_dec(denominator))
        if deviation_bps > unit["precedent_deviation_tolerance_bps"]:
            index = AUTHORITY_LADDER.index(base_tier)
            authority_tier = AUTHORITY_LADDER[min(index + 1, len(AUTHORITY_LADDER) - 1)]
        else:
            authority_tier = base_tier

    return {
        "exposure_cents": exposure_cents,
        "base_tier": base_tier,
        "authority_tier": authority_tier,
        "precedent_deviation_bps": deviation_bps,
    }


# --------------------------------------------------------------------------
# Case cost allocation (PRD 3.9 / calculations.case_cost_allocation)
# --------------------------------------------------------------------------
def case_cost_allocation(grievance_id):
    posted = [c for c in cost_entries_of(grievance_id) if c["status"] == "POSTED"]

    base_total = sum(c["amount_cents"] for c in posted)

    if base_total <= SHARE_TIER_1_CENTS:
        union_split_bps = 5000
    elif base_total <= SHARE_TIER_2_CENTS:
        union_split_bps = 6000
    else:
        union_split_bps = 7000

    union_share = 0
    for entry in posted:
        if entry["bearing_party"] == "UNION":
            union_share += entry["amount_cents"]
        elif entry["bearing_party"] == "SPLIT":
            union_share += round_half_up(
                to_dec(entry["amount_cents"]) * to_dec(union_split_bps) / 10000)

    employer_base = base_total - union_share
    admin_fee = round_half_up(to_dec(employer_base) * to_dec(ADMIN_FEE_BPS) / 10000)
    employer_share = employer_base + admin_fee
    total_cost = union_share + employer_share

    if total_cost <= COST_OK_CEILING_CENTS:
        posture = "COST_OK"
    elif total_cost <= COST_WATCH_CEILING_CENTS:
        posture = "COST_WATCH"
    else:
        posture = "COST_BREACH"

    return {
        "total_cost_cents": total_cost,
        "union_cost_share_cents": union_share,
        "employer_cost_share_cents": employer_share,
        "cost_posture": posture,
    }


# --------------------------------------------------------------------------
# Witness release cost (PRD 3.7 / calculations.witness_release_cost)
# --------------------------------------------------------------------------
def witness_release(slot_start, slot_end, employee):
    raw_hours = to_dec(Decimal((slot_end - slot_start).total_seconds()) / Decimal(3600))
    billable = raw_hours + PREP_ALLOWANCE_HOURS
    quarters = (billable / QUARTER_HOUR).quantize(Decimal("1"), rounding=ROUND_CEILING)
    release_hours = quarters * QUARTER_HOUR
    release_cost = round_half_up(release_hours * to_dec(employee["hourly_rate_cents"]))
    return release_hours, release_cost


def daily_release_hours(employee_id, utc_date, exclude_id=None):
    total = Decimal(0)
    for w in db.witness_assignments.values():
        if w["employee_id"] != employee_id:
            continue
        if exclude_id is not None and w["id"] == exclude_id:
            continue
        if w["status"] not in ("INVITED", "CONFIRMED", "TESTIFIED"):
            continue
        if w["slot_start_at"].date() != utc_date:
            continue
        total += w["release_hours"]
    return total


# --------------------------------------------------------------------------
# Arbitration case cost (PRD 3.8 / calculations.arbitration_case_cost)
# --------------------------------------------------------------------------
def hearing_days(start, end):
    hours = Decimal((end - start).total_seconds()) / Decimal(3600)
    return int((hours / Decimal(24)).quantize(Decimal("1"), rounding=ROUND_CEILING))


def estimated_case_cost(demand, arbitrator):
    days = hearing_days(demand["hearing_start_at"], demand["hearing_end_at"])
    arbitrator_fee = arbitrator["per_diem_cents"] * (days + STUDY_DAYS)
    release_estimate = sum(
        w["release_cost_cents"] for w in assignments_of(demand["id"])
        if w["status"] in ("INVITED", "CONFIRMED")
    )
    transcript_estimate = TRANSCRIPT_PER_DAY_CENTS * days
    return arbitrator_fee + release_estimate + transcript_estimate


def actual_case_cost(demand):
    instant = now()
    candidates = [
        c for c in cost_entries_of(demand["grievance_id"])
        if c["status"] == "POSTED"
        and c["category"] in ARBITRATION_COST_CATEGORIES
        and c["incurred_at"] <= instant
    ]
    running = 0
    for entry in order_by(candidates, "incurred_at", "created_at"):
        running += entry["amount_cents"]
    return running


def readiness_score(demand):
    score = 0
    if demand["prep_status"] in ("EXHIBITS_FILED", "BRIEFS_FILED", "PREP_READY"):
        score += 40
    if demand["prep_status"] in ("BRIEFS_FILED", "PREP_READY"):
        score += 30
    if any(w["status"] == "CONFIRMED" for w in assignments_of(demand["id"])):
        score += 20
    if demand["status"] in ("HEARING_SCHEDULED", "HEARD", "AWARDED"):
        score += 10
    return score


# --------------------------------------------------------------------------
# Award remedy (PRD 3.8 / calculations.award_remedy)
# --------------------------------------------------------------------------
def award_remedy(award, grievant, grievance):
    base_back_pay = round_half_up(
        to_dec(award["back_pay_hours_ordered"]) * to_dec(grievant["hourly_rate_cents"]))
    sustained_portion = round_half_up(
        to_dec(base_back_pay) * to_dec(award["sustained_fraction_bps"]) / 10000)
    if award["interest_rate_bps"] == 0 or award["interest_accrual_start"] is None:
        interest_days = 0
    else:
        interest_days = floor_days(award["interest_accrual_start"], award["issued_at"])
    interest_cents = round_half_up(
        to_dec(sustained_portion) * to_dec(award["interest_rate_bps"]) * to_dec(interest_days)
        / (Decimal(10000) * Decimal(DAYS_PER_YEAR)))
    gross = sustained_portion + interest_cents
    net = max(0, gross - award["mitigation_offset_cents"] - grievance["settled_amount_cents"])
    return gross, net


# --------------------------------------------------------------------------
# Arbitrator derivations (PRD 3.1)
# --------------------------------------------------------------------------
def arbitrator_status(arbitrator):
    if not arbitrator["is_active"]:
        return "INACTIVE"
    if arbitrator["active_case_count"] >= arbitrator["max_concurrent_cases"]:
        return "FULL"
    return "AVAILABLE"


def panel_candidates(demand):
    """calculations.panel_candidate_selection — eligibility then total ranking."""
    grievance_id = demand["grievance_id"]
    struck_ever = set()
    for other in demands_of(grievance_id):
        for strike in strikes_of(other["id"]):
            struck_ever.add(strike["arbitrator_id"])

    horizon = add_days(demand["demanded_at"], PANEL_HORIZON_DAYS)
    eligible = []
    for a in db.arbitrators.values():
        if not a["is_active"]:
            continue
        if a["active_case_count"] >= a["max_concurrent_cases"]:
            continue
        if demand["panel_source"] not in a["panel_memberships"]:
            continue
        if a["earliest_available_at"] > horizon:
            continue
        if a["id"] in struck_ever:
            continue
        eligible.append(a)

    return order_by(eligible, "active_case_count", "per_diem_cents", "created_at")


# --------------------------------------------------------------------------
# Serializers
# --------------------------------------------------------------------------
def _common(rec, out, versioned=True):
    out["id"] = rec["id"]
    out["created_at"] = fmt_dt(rec["created_at"])
    if versioned:
        out["updated_at"] = fmt_dt(rec["updated_at"])
        out["version"] = rec["version"]
    return out


def ser_unit(unit):
    out = {
        "name": unit["name"],
        "local_number": unit["local_number"],
        "contract_effective_date": fmt_dt(unit["contract_effective_date"]),
        "contract_expiry_date": fmt_dt(unit["contract_expiry_date"]),
        "step1_response_days": unit["step1_response_days"],
        "step2_response_days": unit["step2_response_days"],
        "step3_response_days": unit["step3_response_days"],
        "appeal_window_days": unit["appeal_window_days"],
        "filing_window_days": unit["filing_window_days"],
        "arbitration_demand_days": unit["arbitration_demand_days"],
        "tolling_enabled": unit["tolling_enabled"],
        "director_authority_cents": unit["director_authority_cents"],
        "negotiator_authority_cents": unit["negotiator_authority_cents"],
        "precedent_deviation_tolerance_bps": unit["precedent_deviation_tolerance_bps"],
        "status": unit_status(unit),
        "open_grievance_count": unit_open_grievance_count(unit),
    }
    return _common(unit, out)


def ser_clause(clause):
    out = {
        "bargaining_unit_id": clause["bargaining_unit_id"],
        "clause_number": clause["clause_number"],
        "title": clause["title"],
        "category": clause["category"],
        "is_arbitrable": clause["is_arbitrable"],
        "monetary_cap_cents": clause["monetary_cap_cents"],
        "expedited": clause["expedited"],
    }
    out.update(clause_scorecard(clause))
    return _common(clause, out)


def ser_employee(employee):
    out = {
        "bargaining_unit_id": employee["bargaining_unit_id"],
        "supervisor_id": employee["supervisor_id"],
        "full_name": employee["full_name"],
        "employee_number": employee["employee_number"],
        "hire_date": fmt_dt(employee["hire_date"]),
        "seniority_date": fmt_dt(employee["seniority_date"]),
        "hourly_rate_cents": employee["hourly_rate_cents"],
        "classification": employee["classification"],
        "employment_status": employee["employment_status"],
    }
    out.update(supervisor_scorecard(employee))
    out["witness_release_hours_ytd"] = num_out(witness_release_hours_ytd(employee))
    return _common(employee, out)


def ser_grievance(grievance):
    refresh_timeliness(grievance)
    allocation = case_cost_allocation(grievance["id"])
    out = {
        "bargaining_unit_id": grievance["bargaining_unit_id"],
        "grievant_id": grievance["grievant_id"],
        "respondent_supervisor_id": grievance["respondent_supervisor_id"],
        "clause_id": grievance["clause_id"],
        "consolidated_into_id": grievance["consolidated_into_id"],
        "case_number": grievance["case_number"],
        "statement": grievance["statement"],
        "incident_date": fmt_dt(grievance["incident_date"]),
        "discovery_date": fmt_dt(grievance["discovery_date"]),
        "filed_at": fmt_dt(grievance["filed_at"]),
        "filed_by_steward_employee_id": grievance["filed_by_steward_employee_id"],
        "current_step": grievance["current_step"],
        "status": grievance["status"],
        "timeliness_state": grievance["timeliness_state"],
        "remedy_requested_cents": grievance["remedy_requested_cents"],
        "back_pay_hours_claimed": num_out(grievance["back_pay_hours_claimed"]),
        "settled_amount_cents": grievance["settled_amount_cents"],
        "appeal_deadline_at": fmt_dt(appeal_deadline_at(grievance)),
        "arbitration_deadline_at": fmt_dt(arbitration_deadline_at(grievance)),
    }
    out.update(allocation)
    return _common(grievance, out)


def ser_step(step):
    out = {
        "grievance_id": step["grievance_id"],
        "step_number": step["step_number"],
        "status": step["status"],
        "meeting_scheduled_at": fmt_dt(step["meeting_scheduled_at"]),
        "extension_days": step["extension_days"],
        "meeting_held_at": fmt_dt(step["meeting_held_at"]),
        "response_due_at": fmt_dt(step["response_due_at"]),
        "responded_at": fmt_dt(step["responded_at"]),
        "disposition": step["disposition"],
        "response_summary": step["response_summary"],
        "granted_amount_cents": step["granted_amount_cents"],
        "responded_by_user_id": step["responded_by_user_id"],
        "late_by_days": step["late_by_days"],
    }
    return _common(step, out)


def ser_offer(offer):
    out = {
        "grievance_id": offer["grievance_id"],
        "precedent_case_id": offer["precedent_case_id"],
        "offering_party": offer["offering_party"],
        "monetary_cents": offer["monetary_cents"],
        "back_pay_hours": num_out(offer["back_pay_hours"]),
        "remedy_terms": offer["remedy_terms"],
        "precedent_setting": offer["precedent_setting"],
        "round_number": offer["round_number"],
        "exposure_cents": offer["exposure_cents"],
        "authority_tier": offer["authority_tier"],
        "precedent_deviation_bps": offer["precedent_deviation_bps"],
        "status": offer["status"],
        "prepared_by_user_id": offer["prepared_by_user_id"],
        "authorized_by_user_id": offer["authorized_by_user_id"],
        "authorized_at": fmt_dt(offer["authorized_at"]),
        "expires_at": fmt_dt(offer["expires_at"]),
    }
    return _common(offer, out)


def ser_precedent(precedent):
    cited = sum(
        1 for o in db.settlement_offers.values()
        if o["precedent_case_id"] == precedent["id"] and o["status"] != "VOIDED"
    )
    out = {
        "clause_id": precedent["clause_id"],
        "citation": precedent["citation"],
        "decided_on": fmt_dt(precedent["decided_on"]),
        "outcome": precedent["outcome"],
        "monetary_value_cents": precedent["monetary_value_cents"],
        "binding_scope": precedent["binding_scope"],
        "arbitrator_name": precedent["arbitrator_name"],
        "cited_count": cited,
    }
    return _common(precedent, out, versioned=False)


def ser_arbitrator(arbitrator):
    out = {
        "full_name": arbitrator["full_name"],
        "panel_memberships": list(arbitrator["panel_memberships"]),
        "per_diem_cents": arbitrator["per_diem_cents"],
        "cancellation_fee_cents": arbitrator["cancellation_fee_cents"],
        "travel_buffer_hours": arbitrator["travel_buffer_hours"],
        "earliest_available_at": fmt_dt(arbitrator["earliest_available_at"]),
        "max_concurrent_cases": arbitrator["max_concurrent_cases"],
        "is_active": arbitrator["is_active"],
        "active_case_count": arbitrator["active_case_count"],
        "status": arbitrator_status(arbitrator),
    }
    return _common(arbitrator, out)


def ser_demand(demand):
    out = {
        "grievance_id": demand["grievance_id"],
        "selected_arbitrator_id": demand["selected_arbitrator_id"],
        "demanded_at": fmt_dt(demand["demanded_at"]),
        "demand_deadline_at": fmt_dt(demand["demand_deadline_at"]),
        "panel_source": demand["panel_source"],
        "panel_size": demand["panel_size"],
        "panel_arbitrator_ids": list(demand["panel_arbitrator_ids"]),
        "strike_turn": demand["strike_turn"],
        "strikes_taken": demand["strikes_taken"],
        "status": demand["status"],
        "prep_status": demand["prep_status"],
        "exhibit_count": demand["exhibit_count"],
        "hearing_start_at": fmt_dt(demand["hearing_start_at"]),
        "hearing_end_at": fmt_dt(demand["hearing_end_at"]),
        "brief_due_at": fmt_dt(demand["brief_due_at"]),
        "readiness_score": readiness_score(demand),
        "estimated_cost_cents": demand["estimated_cost_cents"],
        "actual_cost_cents": actual_case_cost(demand),
    }
    return _common(demand, out)


def ser_strike(strike):
    out = {
        "arbitration_demand_id": strike["arbitration_demand_id"],
        "arbitrator_id": strike["arbitrator_id"],
        "struck_by": strike["struck_by"],
        "strike_order": strike["strike_order"],
        "struck_by_user_id": strike["struck_by_user_id"],
    }
    return _common(strike, out, versioned=False)


def ser_assignment(assignment):
    out = {
        "arbitration_demand_id": assignment["arbitration_demand_id"],
        "employee_id": assignment["employee_id"],
        "witness_type": assignment["witness_type"],
        "called_by": assignment["called_by"],
        "slot_start_at": fmt_dt(assignment["slot_start_at"]),
        "slot_end_at": fmt_dt(assignment["slot_end_at"]),
        "release_hours": num_out(assignment["release_hours"]),
        "release_cost_cents": assignment["release_cost_cents"],
        "status": assignment["status"],
        "confirmed_by_user_id": assignment["confirmed_by_user_id"],
        "release_cost_entry_id": assignment["release_cost_entry_id"],
    }
    return _common(assignment, out)


def ser_award(award):
    out = {
        "arbitration_demand_id": award["arbitration_demand_id"],
        "issued_at": fmt_dt(award["issued_at"]),
        "outcome": award["outcome"],
        "sustained_fraction_bps": award["sustained_fraction_bps"],
        "back_pay_hours_ordered": num_out(award["back_pay_hours_ordered"]),
        "mitigation_offset_cents": award["mitigation_offset_cents"],
        "interest_rate_bps": award["interest_rate_bps"],
        "interest_accrual_start": fmt_dt(award["interest_accrual_start"]),
        "reinstatement_ordered": award["reinstatement_ordered"],
        "remedy_deadline_days": award["remedy_deadline_days"],
        "gross_remedy_cents": award["gross_remedy_cents"],
        "net_remedy_cents": award["net_remedy_cents"],
        "implemented_cents": award["implemented_cents"],
        "implementation_deadline_at": fmt_dt(award["implementation_deadline_at"]),
        "status": award["status"],
    }
    return _common(award, out)


def ser_cost_entry(entry):
    out = {
        "grievance_id": entry["grievance_id"],
        "category": entry["category"],
        "amount_cents": entry["amount_cents"],
        "bearing_party": entry["bearing_party"],
        "incurred_at": fmt_dt(entry["incurred_at"]),
        "origin": entry["origin"],
        "status": entry["status"],
        "void_reason": entry["void_reason"],
        "voided_by_user_id": entry["voided_by_user_id"],
    }
    return _common(entry, out)
