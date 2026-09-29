"""Domain enumerations and the pure calculation rules (PRD 3.x)."""
from decimal import Decimal

from store import (add_days, floor_days, floor_minutes, money2, now, ordered,
                   rate, round_half_up, store)

# ------------------------------------------------------------------- constants
DEPARTMENTS = ("ENGINEERING", "FINANCE", "SALES", "HR", "IT", "EXECUTIVE")
ROLE_CODES = ("IC", "ENGINEER", "FINANCE_APPROVER", "IT_ADMIN", "EXECUTIVE", "MANAGER")
EMPLOYMENT_STATUSES = ("ACTIVE", "OFFBOARDED")
TENURE_BANDS = ("NEW_HIRE", "EARLY", "ESTABLISHED", "VETERAN")
COMPLIANCE_STATES = ("COMPLIANT", "AT_RISK", "DELINQUENT")
ACCESS_POSTURES = ("NONE", "WARNED", "ELEVATED_REVIEW", "SUSPENDED")

MODULE_TYPES = ("NEW_HIRE", "ANNUAL", "ROLE_SPECIFIC", "REMEDIAL")
CRITICALITIES = ("STANDARD", "HIGH")
MODULE_STATUSES = ("DRAFT", "PUBLISHED", "RETIRED")

ASSIGNMENT_REASONS = ("NEW_HIRE", "ANNUAL", "ROLE_CHANGE", "REMEDIAL")
ASSIGNMENT_STATES = ("ASSIGNED", "IN_PROGRESS", "FAILED_ATTEMPT", "COMPLETED",
                     "OVERDUE", "ESCALATED", "VOIDED")
ASSIGNMENT_NON_TERMINAL = ("ASSIGNED", "IN_PROGRESS", "FAILED_ATTEMPT", "OVERDUE", "ESCALATED")

NOTICE_STATES = ("SENT", "ACKNOWLEDGED", "EXPIRED")

CONSEQUENCE_TYPES = ("WARNING", "MFA_REVIEW", "SYSTEM_ACCESS_SUSPENSION")
CONSEQUENCE_STATES = ("ACTIVE", "LIFTED", "VOIDED")
RANK_BY_TYPE = {"WARNING": 1, "MFA_REVIEW": 2, "SYSTEM_ACCESS_SUSPENSION": 3}
TYPE_BY_RANK = {1: "WARNING", 2: "MFA_REVIEW", 3: "SYSTEM_ACCESS_SUSPENSION"}
POSTURE_BY_RANK = {0: "NONE", 1: "WARNED", 2: "ELEVATED_REVIEW", 3: "SUSPENDED"}

PRETEXT_CATEGORIES = ("PACKAGE_DELIVERY", "IT_PASSWORD_RESET", "SHARED_DOCUMENT",
                      "INVOICE_APPROVAL", "HR_BENEFITS_ENROLLMENT", "EXEC_URGENT_REQUEST")
DIFFICULTY_TIERS = ("TIER_1_BASIC", "TIER_2_TARGETED", "TIER_3_SPEAR")
TIER_RANK = {"TIER_1_BASIC": 1, "TIER_2_TARGETED": 2, "TIER_3_SPEAR": 3}
TIER_BY_RANK = {1: "TIER_1_BASIC", 2: "TIER_2_TARGETED", 3: "TIER_3_SPEAR"}
THEME_TAGS = ("URGENCY", "AUTHORITY", "CURIOSITY", "REWARD", "BONUS_COMPENSATION",
              "LAYOFF_NOTICE", "MEDICAL_RESULT", "CHARITY_APPEAL", "FAMILY_EMERGENCY")
PROHIBITED_THEME_TAGS = ("BONUS_COMPENSATION", "LAYOFF_NOTICE", "MEDICAL_RESULT",
                         "CHARITY_APPEAL", "FAMILY_EMERGENCY")
TEMPLATE_REVIEW_STATES = ("DRAFT", "APPROVED_FOR_USE", "BLOCKED")

CAMPAIGN_STATES = ("DRAFT", "IN_REVIEW", "APPROVED", "REJECTED", "SCHEDULED",
                   "RUNNING", "CLOSED", "CANCELLED")

DELIVERY_STATES = ("QUEUED", "DELIVERED", "REPORTED", "CLICKED",
                   "CREDENTIAL_SUBMITTED", "NO_INTERACTION", "EXCLUDED")
OUTCOME_CLASSES = ("PENDING", "NO_INTERACTION", "REPORTED_ONLY", "CLICKED_NO_REPORT",
                   "CLICKED_THEN_REPORTED", "CREDENTIAL_SUBMITTED", "EXCLUDED")
EXCLUDED_REASONS = ("CAMPAIGN_CANCELLED", "CAMPAIGN_RESCHEDULED",
                    "EMPLOYEE_OFFBOARDED", "ACCESS_SUSPENDED")

EVENT_TYPES = ("OPEN", "CLICK", "REPORT", "CREDENTIAL_SUBMIT")
EVENT_SOURCES = ("MAIL_GATEWAY", "REPORT_BUTTON", "LANDING_PAGE")

INTERVENTION_STATES = ("OPEN", "ESCALATED_TO_MANAGER", "COACHING_ASSIGNED",
                       "COACHING_COMPLETED", "CLOSED_RESOLVED")
INTERVENTION_ACTIVE_STATES = ("OPEN", "ESCALATED_TO_MANAGER", "COACHING_ASSIGNED",
                              "COACHING_COMPLETED")

INCIDENT_TYPES = ("CREDENTIAL_PHISH", "BEC", "MALWARE_DELIVERY", "DATA_LOSS")
PHISH_RELATED_TYPES = ("CREDENTIAL_PHISH", "BEC")
SEVERITIES = ("LOW", "MEDIUM", "HIGH", "CRITICAL")
WINDOW_TYPES = ("SIMULATION_BLACKOUT", "ANNOUNCEMENT_MORATORIUM")

BASE_DAYS = {"NEW_HIRE": 14, "ANNUAL": 30, "ROLE_CHANGE": 21, "REMEDIAL": 7}
HIGH_CRITICALITY_FLOOR_DAYS = 3
DEFAULT_REMINDER_OFFSETS_DAYS = [7, 3, 1, -2]
QUIET_PERIOD_DAYS = 5
REPEAT_WINDOW_DAYS = 180
CLEAN_STREAK_FOR_DECAY = 3
ESCALATION_L1_DAYS = 1
ESCALATION_L2_DAYS = 7
ESCALATION_L3_DAYS = 14

CREDENTIAL_WEIGHT = 18
CLICK_WEIGHT = 10
OVERDUE_WEIGHT = 8
REPORT_CREDIT = 6
NEW_HIRE_RELIEF = 5
NO_INTERACTION_CREDIT = 2
TIER_MULTIPLIER_STEP = Decimal("0.10")

FAILURE_STATES = ("CLICKED", "CREDENTIAL_SUBMITTED")


# ------------------------------------------------------------ tenure / harmful
def tenure_band(employee, clock=None):
    clock = clock or now()
    days = floor_days(clock, employee["_hire_dt"])
    if days < 90:
        return "NEW_HIRE"
    if days < 365:
        return "EARLY"
    if days < 1095:
        return "ESTABLISHED"
    return "VETERAN"


def harmful_flag_hits(theme_tags):
    tags = set(theme_tags or [])
    return [t for t in PROHIBITED_THEME_TAGS if t in tags]


# --------------------------------------------------------------- assignment due
def due_window_days(assignment_reason, criticality):
    base = BASE_DAYS[assignment_reason]
    if criticality == "HIGH":
        return max(HIGH_CRITICALITY_FLOOR_DAYS, base // 2)
    return base


def effective_due_at(assignment):
    return add_days(assignment["due_at"], assignment["granted_extension_days"])


def next_reminder_due_at(assignment, module):
    if assignment["state"] in ("COMPLETED", "VOIDED"):
        return None
    offsets = module["reminder_offsets_days"]
    sent = assignment["reminders_sent"]
    if sent >= len(offsets):
        return None
    return add_days(effective_due_at(assignment), -offsets[sent])


def days_overdue(assignment, clock=None):
    clock = clock or now()
    return max(0, floor_days(clock, effective_due_at(assignment)))


def escalation_target_level(days):
    if days >= ESCALATION_L3_DAYS:
        return 3
    if days >= ESCALATION_L2_DAYS:
        return 2
    if days >= ESCALATION_L1_DAYS:
        return 1
    return 0


# -------------------------------------------------------------- collection views
def assignments_of(employee_id):
    return ordered([a for a in store.assignments.values() if a["employee_id"] == employee_id])


def consequences_of(employee_id):
    return ordered([c for c in store.consequences.values() if c["employee_id"] == employee_id])


def active_consequences(employee_id):
    return [c for c in consequences_of(employee_id) if c["state"] == "ACTIVE"]


def deliveries_of_employee(employee_id):
    return ordered([d for d in store.deliveries.values() if d["employee_id"] == employee_id])


def deliveries_of_campaign(campaign_id):
    return ordered([d for d in store.deliveries.values() if d["campaign_id"] == campaign_id])


def events_of_delivery(delivery_id):
    rows = [e for e in store.events.values() if e["delivery_id"] == delivery_id]
    return sorted(rows, key=lambda e: e["sequence_index"])


def notices_of_assignment(assignment_id):
    return ordered([n for n in store.notices.values() if n["assignment_id"] == assignment_id])


def consequences_of_assignment(assignment_id):
    return ordered([c for c in store.consequences.values()
                    if c.get("source_assignment_id") == assignment_id])


# ------------------------------------------------------- employee derived state
def compliance_state(employee_id):
    rows = assignments_of(employee_id)
    if any(a["state"] == "ESCALATED" for a in rows):
        return "DELINQUENT"
    if any(a["state"] == "OVERDUE" for a in rows):
        return "AT_RISK"
    return "COMPLIANT"


def max_active_rank(employee_id):
    ranks = [c["severity_rank"] for c in active_consequences(employee_id)]
    return max(ranks) if ranks else 0


def access_posture(employee_id):
    return POSTURE_BY_RANK[max_active_rank(employee_id)]


def active_suspension_count(employee_id):
    return len([c for c in active_consequences(employee_id)
                if c["consequence_type"] == "SYSTEM_ACCESS_SUSPENSION"])


def reserved_simulation_slots(employee_id):
    return len([d for d in store.deliveries.values()
                if d["employee_id"] == employee_id and d["state"] == "QUEUED"])


def failure_deliveries(employee_id, clock=None):
    """Rolling-window failure deliveries (PRD 3.10)."""
    clock = clock or now()
    window_start = add_days(clock, -REPEAT_WINDOW_DAYS)
    out = []
    for d in deliveries_of_employee(employee_id):
        if d["state"] not in FAILURE_STATES:
            continue
        campaign = store.campaigns.get(d["campaign_id"])
        if campaign is None or campaign["state"] not in ("RUNNING", "CLOSED"):
            continue
        if d["delivered_at"] is None or d["delivered_at"] < window_start:
            continue
        out.append(d)
    return out


def repeat_clicker_tier(employee, clock=None):
    f = len(failure_deliveries(employee["id"], clock))
    if f == 0:
        tier = 0
    elif f == 1:
        tier = 1
    elif f <= 3:
        tier = 2
    else:
        tier = 3
    return max(0, tier - employee.get("_tier_decay_total", 0))


def consecutive_clean_simulations(employee_id):
    """Trailing clean deliveries after the most recent failure delivery."""
    rows = [d for d in deliveries_of_employee(employee_id)
            if d["state"] != "EXCLUDED" and d["delivered_at"] is not None]
    rows.sort(key=lambda d: (d["delivered_at"], d["_seq"]))
    streak = 0
    for d in rows:
        if d["state"] in FAILURE_STATES:
            streak = 0
            continue
        if d["state"] == "NO_INTERACTION":
            streak += 1
            continue
        if d["state"] == "REPORTED":
            campaign = store.campaigns.get(d["campaign_id"])
            if campaign is not None and campaign["state"] == "CLOSED":
                streak += 1
    return streak


# ------------------------------------------------------------------- risk score
def _risk(employee, variant, clock=None):
    clock = clock or now()
    if variant == "PROVISIONAL":
        allowed = ("RUNNING", "CLOSED")
    else:
        allowed = ("CLOSED",)
    in_scope = []
    for d in deliveries_of_employee(employee["id"]):
        campaign = store.campaigns.get(d["campaign_id"])
        if campaign is not None and campaign["state"] in allowed:
            in_scope.append(d)
    credential_failures = len([d for d in in_scope if d["credential_submitted_at"] is not None])
    click_failures = len([d for d in in_scope
                          if d["first_click_at"] is not None
                          and d["credential_submitted_at"] is None])
    report_deliveries = len([d for d in in_scope if d["first_report_at"] is not None])
    delinquent = len([a for a in assignments_of(employee["id"])
                      if a["state"] in ("OVERDUE", "ESCALATED")])
    tier = repeat_clicker_tier(employee, clock)
    if variant == "SETTLED":
        settled_clean = len([d for d in in_scope if d["state"] == "NO_INTERACTION"])
    else:
        settled_clean = 0

    penalty_units = (Decimal(CREDENTIAL_WEIGHT) * credential_failures
                     + Decimal(CLICK_WEIGHT) * click_failures
                     + Decimal(OVERDUE_WEIGHT) * delinquent)
    weighted_penalty = penalty_units * (Decimal(1) + TIER_MULTIPLIER_STEP * Decimal(tier))
    credit_units = (Decimal(REPORT_CREDIT) * report_deliveries
                    + (Decimal(NEW_HIRE_RELIEF) if tenure_band(employee, clock) == "NEW_HIRE"
                       else Decimal(0))
                    + Decimal(NO_INTERACTION_CREDIT) * settled_clean)
    raw = weighted_penalty - credit_units
    rounded = round_half_up(raw, 2)
    if rounded < 0:
        rounded = Decimal("0.00")
    if rounded > 100:
        rounded = Decimal("100.00")
    return float(rounded)


def risk_score_provisional(employee, clock=None):
    return _risk(employee, "PROVISIONAL", clock)


def risk_score_settled(employee, clock=None):
    return _risk(employee, "SETTLED", clock)


# ---------------------------------------------------------------- delivery view
def outcome_class(delivery):
    if delivery["state"] == "EXCLUDED":
        return "EXCLUDED"
    if delivery["credential_submitted_at"] is not None:
        return "CREDENTIAL_SUBMITTED"
    if delivery["first_click_at"] is not None and delivery["first_report_at"] is not None:
        return "CLICKED_THEN_REPORTED"
    if delivery["first_click_at"] is not None:
        return "CLICKED_NO_REPORT"
    if delivery["first_report_at"] is not None:
        return "REPORTED_ONLY"
    if delivery["state"] == "DELIVERED":
        return "PENDING"
    return "NO_INTERACTION"


def time_to_report_minutes(delivery):
    if delivery["first_report_at"] is None or delivery["delivered_at"] is None:
        return None
    return floor_minutes(delivery["first_report_at"], delivery["delivered_at"])


def quiet_reference_instant(delivery):
    if delivery["delivered_at"] is not None:
        return delivery["delivered_at"]
    campaign = store.campaigns.get(delivery["campaign_id"])
    if campaign is None:
        return None
    return campaign.get("scheduled_send_at")


def quiet_period_until(delivery):
    ref = quiet_reference_instant(delivery)
    if ref is None:
        return None
    return add_days(ref, QUIET_PERIOD_DAYS)


def effective_tier_for(campaign, employee, clock=None):
    """Per-employee difficulty escalation (PRD 3.8)."""
    clock = clock or now()
    base_rank = TIER_RANK[campaign["difficulty_tier"]]
    streak_relief = 1 if consecutive_clean_simulations(employee["id"]) >= CLEAN_STREAK_FOR_DECAY else 0
    tier = repeat_clicker_tier(employee, clock)
    raw_rank = max(base_rank, base_rank + tier - streak_relief)
    capped_rank = min(3, raw_rank)
    if tenure_band(employee, clock) == "NEW_HIRE":
        effective_rank = min(capped_rank, 2)
    else:
        effective_rank = capped_rank
    return TIER_BY_RANK[effective_rank]


def simulation_frequency_days(current_tier):
    if current_tier == 3:
        return 14
    if current_tier == 2:
        return 30
    return 45


# ------------------------------------------------------------- scorecard rates
def rate_bundle(deliveries):
    evaluable = [d for d in deliveries if d["state"] != "EXCLUDED"]
    n = len(evaluable)
    clicked_n = len([d for d in evaluable if d["first_click_at"] is not None])
    reported_n = len([d for d in evaluable if d["first_report_at"] is not None])
    credential_n = len([d for d in evaluable if d["credential_submitted_at"] is not None])
    if n == 0:
        return {
            "evaluable_count": 0,
            "click_rate": None,
            "report_rate": None,
            "credential_rate": None,
            "resilience_ratio": None,
        }
    return {
        "evaluable_count": n,
        "click_rate": rate(clicked_n, n),
        "report_rate": rate(reported_n, n),
        "credential_rate": rate(credential_n, n),
        "resilience_ratio": rate(reported_n, max(1, clicked_n)),
    }


def campaign_rates(campaign_id):
    return rate_bundle(deliveries_of_campaign(campaign_id))


def pearson(xs, ys):
    n = len(xs)
    if n < 2:
        return None
    mx = sum(xs) / Decimal(n)
    my = sum(ys) / Decimal(n)
    sxy = sum((x - mx) * (y - my) for x, y in zip(xs, ys))
    sxx = sum((x - mx) * (x - mx) for x in xs)
    syy = sum((y - my) * (y - my) for y in ys)
    if sxx == 0 or syy == 0:
        return None
    import math
    denom = Decimal(math.sqrt(float(sxx))) * Decimal(math.sqrt(float(syy)))
    if denom == 0:
        return None
    return sxy / denom
