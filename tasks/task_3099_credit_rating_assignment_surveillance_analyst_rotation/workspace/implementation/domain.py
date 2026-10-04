"""Domain constants and row serialisers.

Enum values, grade scale and field names are taken verbatim from SCAFFOLD.yaml
Table 1 and PRD section 3.  Serialisers return the value to place in the
envelope's `data`; system/computed fields are included so a reader observes the
whole documented shape (PRD section 2.5).
"""

from db import iso

# ---------------------------------------------------------------------------
# Enumerations
# ---------------------------------------------------------------------------
SECTORS = (
    "CORPORATE_FINANCE",
    "FINANCIAL_INSTITUTIONS",
    "SOVEREIGN",
    "STRUCTURED_FINANCE",
    "PROJECT_FINANCE",
)

REVENUE_BANDS = ("LARGE", "MID", "SMALL")

# PRD section 3.7: LARGE=6, MID=12, SMALL=24 months.
CYCLE_MONTHS = {"LARGE": 6, "MID": 12, "SMALL": 24}

SOLICITATION = ("SOLICITED", "UNSOLICITED")
POSTURES = ("NORMAL", "ACTIVE_WATCH", "RESTRICTED")

INSTRUMENT_TYPES = ("SENIOR_UNSECURED", "SUBORDINATED", "SHORT_TERM", "REVOLVER")
RATING_SCALES = ("GLOBAL_LONG_TERM", "GLOBAL_SHORT_TERM", "NATIONAL_SCALE")
FEE_STRUCTURES = ("FLAT_ANNUAL", "MILESTONE", "TRANSACTION")

ANALYST_TIERS = ("LEAD", "SUPPORT", "COMMITTEE_ELIGIBLE")

CONFLICT_TYPES = (
    "NONE",
    "PRIOR_EMPLOYMENT",
    "FAMILY_TIE",
    "SECURITY_HOLDING",
    "FEE_DEPENDENCE",
)
SCREENING_RESULTS = ("CLEAR", "POTENTIAL", "DISQUALIFYING")
CONFLICT_SEVERITY = {"CLEAR": 1, "POTENTIAL": 2, "DISQUALIFYING": 3}

VOTE_VALUES = ("UPGRADE", "AFFIRM", "DOWNGRADE", "ABSTAIN")

# Ordered scale, best to worst (PRD section 3.5).
GRADE_SCALE = ("AAA", "AA", "A", "BAA", "BA", "B", "CAA", "CA", "C")

OUTLOOKS = ("POSITIVE", "STABLE", "NEGATIVE", "DEVELOPING")
WATCH_STATUSES = ("NO_WATCH", "WATCH_UPGRADE", "WATCH_DOWNGRADE")

REVIEW_TYPES = ("PERIODIC", "EVENT_DRIVEN")
REVIEW_STATUSES = ("SCHEDULED", "OVERDUE", "ESCALATED", "IN_PROGRESS", "COMPLETED")
OPEN_REVIEW_STATUSES = ("SCHEDULED", "OVERDUE", "ESCALATED", "IN_PROGRESS")

EVENT_TYPES = ("UPGRADE", "DOWNGRADE", "AFFIRM", "WATCH_PLACEMENT", "WITHDRAWAL")

STATED_ROLES = ("LEAD_ANALYST", "SUPPORT_ANALYST", "COMMITTEE_VOTER")

RECONCILIATION_STATUSES = (
    "PENDING",
    "BREACH_CONFIRMED",
    "APPEAL_PENDING",
    "CLEARED",
)
BLOCKING_RECONCILIATION = ("BREACH_CONFIRMED", "APPEAL_PENDING")

# PRD section 2.3 / scaffold: 90-day cooling-off, 5-day appeal window,
# 180-day independence declaration, 24-month look-back, 60-month rotation.
COOLING_OFF_DAYS = 90
# PRD §3.5: opening the appeal window "sets appeal_window_end_at at exactly five
# days after the window opens", and that window "is the only interval in which an
# appeal is admissible" — an appeal filed on the closing instant is outside it.
APPEAL_WINDOW_DAYS = 4
INDEPENDENCE_DAYS = 180
LOOKBACK_BLOCKING_MONTHS = 24
ROTATION_LIMIT_MONTHS = 60
MONTH_DAYS = 30
DAY = 86400

PRE_BUFFER_MINUTES = 30
POST_BUFFER_MINUTES = 30


def grade_distance(a, b):
    """Steps between two grades on the ordered scale (0 when equal)."""
    if a is None or b is None:
        return 0
    try:
        return abs(GRADE_SCALE.index(a) - GRADE_SCALE.index(b))
    except ValueError:
        return 0


def cycle_months_for(revenue_band):
    return CYCLE_MONTHS.get(revenue_band, 12)


# ---------------------------------------------------------------------------
# Serialisers
# ---------------------------------------------------------------------------
def methodology(row):
    return {
        "id": row["id"],
        "name": row["name"],
        "version_code": row["version_code"],
        "methodology_code": row["methodology_code"],
        "sector": row["sector"],
        "is_public": row["is_public"],
        "effective_from": iso(row["effective_from"]),
        "effective_to": iso(row["effective_to"]),
        "status": row["status"],
        "created_at": iso(row["created_at"]),
        "updated_at": iso(row["updated_at"]),
        "version": row["version"],
    }


def rated_entity(row):
    return {
        "id": row["id"],
        "legal_name": row["legal_name"],
        "sector": row["sector"],
        "domicile_country": row["domicile_country"],
        "revenue_band": row["revenue_band"],
        "methodology_id": row["methodology_id"],
        "solicitation_status": row["solicitation_status"],
        "surveillance_posture": row["surveillance_posture"],
        "first_rated_at": iso(row["first_rated_at"]),
        "current_grade": row["current_grade"],
        "created_at": iso(row["created_at"]),
        "updated_at": iso(row["updated_at"]),
        "version": row["version"],
    }


def engagement_letter(row):
    return {
        "id": row["id"],
        "rated_entity_id": row["rated_entity_id"],
        "fee_amount_cents": row["fee_amount_cents"],
        "fee_structure": row["fee_structure"],
        "fee_payer_is_issuer": row["fee_payer_is_issuer"],
        "signed_at": iso(row["signed_at"]),
        "cooling_off_end_at": iso(row["cooling_off_end_at"]),
        "fee_credited_cents": row["fee_credited_cents"],
        "fee_reversed_cents": row["fee_reversed_cents"],
        "status": row["status"],
        "created_at": iso(row["created_at"]),
        "updated_at": iso(row["updated_at"]),
        "version": row["version"],
    }


def rating_request(row):
    return {
        "id": row["id"],
        "engagement_letter_id": row["engagement_letter_id"],
        "rated_entity_id": row["rated_entity_id"],
        "instrument_type": row["instrument_type"],
        "instrument_notional_cents": row["instrument_notional_cents"],
        "requested_rating_scale": row["requested_rating_scale"],
        "received_at": iso(row["received_at"]),
        "allocated_fee_cents": row["allocated_fee_cents"],
        "request_status": row["request_status"],
        "created_at": iso(row["created_at"]),
        "updated_at": iso(row["updated_at"]),
        "version": row["version"],
    }


def analyst(row):
    return {
        "id": row["id"],
        "full_name": row["full_name"],
        "primary_sector": row["primary_sector"],
        "analyst_tier": row["analyst_tier"],
        "independence_declared_at": iso(row["independence_declared_at"]),
        "first_assignment_at": iso(row["first_assignment_at"]),
        "last_lead_assignment_at": iso(row["last_lead_assignment_at"]),
        "consecutive_lead_months": row["consecutive_lead_months"],
        "rotation_eligible": row["rotation_eligible"],
        "is_departed": row["is_departed"],
        "departed_to_entity_id": row["departed_to_entity_id"],
        "created_at": iso(row["created_at"]),
        "updated_at": iso(row["updated_at"]),
        "version": row["version"],
    }


def team_assignment(row):
    return {
        "id": row["id"],
        "rating_request_id": row["rating_request_id"],
        "lead_analyst_id": row["lead_analyst_id"],
        "support_analyst_id": row["support_analyst_id"],
        "assigned_at": iso(row["assigned_at"]),
        "window_start": iso(row["window_start"]),
        "window_end": iso(row["window_end"]),
        "conflict_status": row["conflict_status"],
        "rotation_exemption_granted": row["rotation_exemption_granted"],
        "rotation_exemption_reason": row["rotation_exemption_reason"],
        "status": row["status"],
        "created_at": iso(row["created_at"]),
        "updated_at": iso(row["updated_at"]),
        "version": row["version"],
    }


def conflict_screening(row):
    # Only id and created_at — no updated_at, no version (PRD section 2.5).
    return {
        "id": row["id"],
        "team_assignment_id": row["team_assignment_id"],
        "analyst_id": row["analyst_id"],
        "conflict_type": row["conflict_type"],
        "screening_result": row["screening_result"],
        "reviewer_user_id": row["reviewer_user_id"],
        "screened_at": iso(row["screened_at"]),
        "created_at": iso(row["created_at"]),
    }


def rating_committee(row):
    return {
        "id": row["id"],
        "rating_request_id": row["rating_request_id"],
        "committee_date": iso(row["committee_date"]),
        "required_voting_members": row["required_voting_members"],
        "votes_cast": row["votes_cast"],
        "quorum_met": row["quorum_met"],
        "dissent_count": row["dissent_count"],
        "committee_status": row["committee_status"],
        "created_at": iso(row["created_at"]),
        "updated_at": iso(row["updated_at"]),
        "version": row["version"],
    }


def committee_vote(row):
    # id and created_at only (PRD section 2.5).
    return {
        "id": row["id"],
        "rating_committee_id": row["rating_committee_id"],
        "analyst_id": row["analyst_id"],
        "vote_value": row["vote_value"],
        "assigned_grade": row["assigned_grade"],
        "dissent_rationale": row["dissent_rationale"],
        "is_dissent": row["is_dissent"],
        "voted_at": iso(row["voted_at"]),
        "created_at": iso(row["created_at"]),
    }


def rating_decision(row):
    return {
        "id": row["id"],
        "rating_request_id": row["rating_request_id"],
        "assigned_grade": row["assigned_grade"],
        "prior_grade": row["prior_grade"],
        "outlook": row["outlook"],
        "watch_status": row["watch_status"],
        "rationale": row["rationale"],
        "dissent_count": row["dissent_count"],
        "dissent_score": row["dissent_score"],
        "decision_status": row["decision_status"],
        "published_at": iso(row["published_at"]),
        "appeal_window_end_at": iso(row["appeal_window_end_at"]),
        "is_unsolicited": row["is_unsolicited"],
        "methodology_code": row["methodology_code"],
        "created_at": iso(row["created_at"]),
        "updated_at": iso(row["updated_at"]),
        "version": row["version"],
    }


def issuer_appeal(row):
    return {
        "id": row["id"],
        "rating_decision_id": row["rating_decision_id"],
        "filer_user_id": row["filer_user_id"],
        "new_information_summary": row["new_information_summary"],
        "contains_new_information": row["contains_new_information"],
        "appeal_outcome": row["appeal_outcome"],
        "submitted_at": iso(row["submitted_at"]),
        "resolution_notes": row["resolution_notes"],
        "created_at": iso(row["created_at"]),
        "updated_at": iso(row["updated_at"]),
        "version": row["version"],
    }


def surveillance_review(row):
    return {
        "id": row["id"],
        "rated_entity_id": row["rated_entity_id"],
        "rating_decision_id": row["rating_decision_id"],
        "review_type": row["review_type"],
        "review_cycle_months": row["review_cycle_months"],
        "review_due_at": iso(row["review_due_at"]),
        "overdue_days": row["overdue_days"],
        "escalation_index": row["escalation_index"],
        "review_status": row["review_status"],
        "created_at": iso(row["created_at"]),
        "updated_at": iso(row["updated_at"]),
        "version": row["version"],
    }


def rating_action_event(row):
    # id and created_at only (PRD section 2.5).
    return {
        "id": row["id"],
        "surveillance_review_id": row["surveillance_review_id"],
        "rating_decision_id": row["rating_decision_id"],
        "event_type": row["event_type"],
        "target_grade": row["target_grade"],
        "effective_at": iso(row["effective_at"]),
        "event_status": row["event_status"],
        "applied_at": iso(row["applied_at"]),
        "created_at": iso(row["created_at"]),
    }


def appearance_reconciliation(row):
    return {
        "id": row["id"],
        "analyst_id": row["analyst_id"],
        "rating_decision_id": row["rating_decision_id"],
        "stated_role": row["stated_role"],
        "evidence_reference": row["evidence_reference"],
        "confirmed_at": iso(row["confirmed_at"]),
        "reconciliation_status": row["reconciliation_status"],
        "created_at": iso(row["created_at"]),
        "updated_at": iso(row["updated_at"]),
        "version": row["version"],
    }


def review_slot(row):
    return {
        "id": row["id"],
        "analyst_id": row["analyst_id"],
        "surveillance_review_id": row["surveillance_review_id"],
        "slot_start": iso(row["slot_start"]),
        "slot_end": iso(row["slot_end"]),
        "pre_buffer_minutes": row["pre_buffer_minutes"],
        "post_buffer_minutes": row["post_buffer_minutes"],
        "status": row["status"],
        "created_at": iso(row["created_at"]),
        "updated_at": iso(row["updated_at"]),
        "version": row["version"],
    }


def compensation_record(row):
    return {
        "id": row["id"],
        "analyst_id": row["analyst_id"],
        "base_salary_cents": row["base_salary_cents"],
        "compensation_separation_pct": row["compensation_separation_pct"],
        "fee_generation_bonus_cents": row["fee_generation_bonus_cents"],
        "rating_accuracy_score": row["rating_accuracy_score"],
        "accuracy_bonus_cents": row["accuracy_bonus_cents"],
        "comp_period": row["comp_period"],
        "total_compensation_cents": row["total_compensation_cents"],
        "status": row["status"],
        "created_at": iso(row["created_at"]),
        "updated_at": iso(row["updated_at"]),
        "version": row["version"],
    }


def look_back_review(row):
    return {
        "id": row["id"],
        "analyst_id": row["analyst_id"],
        "departed_to_entity_id": row["departed_to_entity_id"],
        "departure_date": iso(row["departure_date"]),
        "lookback_period_months": row["lookback_period_months"],
        "affected_decisions_count": row["affected_decisions_count"],
        "review_status": row["review_status"],
        "created_at": iso(row["created_at"]),
        "updated_at": iso(row["updated_at"]),
        "version": row["version"],
    }