"""Derived fields, calculations and ordered cascades (PRD sections 2.8, 2.9,
3.1-3.9).  Nothing derived is cached: every read recomputes from live inputs."""
from datetime import timedelta
from decimal import Decimal, ROUND_HALF_UP

import clock
from store import db, ordered, touch

# --- constants pinned by the scaffold -------------------------------------
CRISIS_MULTIPLIER = Decimal("1.5")
AFTER_HOURS_FACTOR = Decimal("1.20")
PLAIN_FACTOR = Decimal("1.00")
AFTER_HOURS_START_UTC_HOUR = 18
AFTER_HOURS_END_UTC_HOUR = 8
DAILY_BILLABLE_CAP_MINUTES = 600
TRAVEL_BUFFER_MINUTES = 30
ADMIN_FEE_PCT = 7
TIER_1_CEILING_CENTS = 200000
TIER_2_CEILING_CENTS = 500000
TIER_1_PCT = 8
TIER_2_PCT = 6
TIER_3_PCT = 4
ACUITY_ELEVATED_THRESHOLD = 70
GRACE_DAYS = 7

ACCRUAL_STATUSES = ("DRAFT", "SUBMITTED", "APPROVED")
LIVE_ENTRY_STATUSES = ("DRAFT", "SUBMITTED", "APPROVED", "INVOICED")
AUTHORIZED_SET = ("AUTHORIZED", "ACTIVE")
LIVE_AUTH_STATUSES = ("PROPOSED", "AUTHORIZED", "ACTIVE", "SUSPENDED")
ESCALATION_TYPES = ("ESCALATE_GUARDIANSHIP_PETITION", "ESCALATE_APS_REPORT")

DOMAIN_WEIGHTS = {
    "safety": Decimal("0.30"),
    "cognition": Decimal("0.25"),
    "adl": Decimal("0.20"),
    "medical_complexity": Decimal("0.15"),
    "social_support": Decimal("0.05"),
    "finances": Decimal("0.05"),
}
DOMAIN_SCALE = 20


def round_half_up(value):
    """Resolve a fractional value by rounding half up, away from zero."""
    return int(Decimal(value).quantize(Decimal("1"), rounding=ROUND_HALF_UP))


# --- collection helpers ---------------------------------------------------

def by_client(collection, client_id):
    return [r for r in collection.values() if r.get("client_id") == client_id]


def plan_authorizations(care_plan_id):
    return [a for a in db.authorizations.values()
            if a["care_plan_id"] == care_plan_id]


def rank_top(records, key):
    """Rank by `key` descending, ties broken by created_at ascending."""
    if not records:
        return None
    items = sorted(records, key=lambda r: (r["created_at"], r["_seq"]))
    items = sorted(items, key=lambda r: r[key], reverse=True)
    return items[0]


# --- assessment acuity ---------------------------------------------------

def screening_acuity(domain_scores):
    total = sum(Decimal(domain_scores[k]) for k in domain_scores)
    return round_half_up(total / Decimal(6) * Decimal(DOMAIN_SCALE))


def comprehensive_acuity(domain_scores):
    weighted = Decimal(0)
    for name, weight in DOMAIN_WEIGHTS.items():
        weighted += Decimal(domain_scores[name]) * weight
    return round_half_up(weighted * Decimal(DOMAIN_SCALE))


def acuity_score(client_id):
    candidates = [a for a in db.assessments.values()
                  if a["client_id"] == client_id and a["status"] == "ACCEPTED"]
    top = rank_top(candidates, "accepted_at")
    if top is None or top.get("comprehensive_acuity") is None:
        return 0
    return top["comprehensive_acuity"]


# --- client ledger -------------------------------------------------------

def retainer_deposits_total(client_id):
    return sum(d["amount_cents"] for d in db.deposits
               if d["client_id"] == client_id)


def retainer_drawn(client_id):
    return sum(i["retainer_applied_cents"] for i in db.invoices.values()
               if i["client_id"] == client_id
               and i["status"] in ("ISSUED", "PAID"))


def retainer_balance(client_id):
    return retainer_deposits_total(client_id) - retainer_drawn(client_id)


def unbilled_accrual(client_id):
    return sum(e["billable_amount_cents"] for e in db.time_entries.values()
               if e["client_id"] == client_id
               and e["status"] in ACCRUAL_STATUSES)


def authorized_coverage_hours(client_id):
    return sum(a["coverage_hours"] for a in db.authorizations.values()
               if a["client_id"] == client_id
               and a["auth_status"] in AUTHORIZED_SET)


def protective_escalation_status(client_id):
    candidates = []
    for decision in db.decisions.values():
        conference = db.conferences.get(decision["family_conference_id"])
        if conference is None or conference["client_id"] != client_id:
            continue
        if decision["decision_type"] not in ESCALATION_TYPES:
            continue
        if decision["status"] not in ("ESCALATED", "ESCALATION_ACCEPTED",
                                      "ESCALATION_DECLINED"):
            continue
        candidates.append(decision)
    top = rank_top(candidates, "escalated_at")
    if top is None:
        return "NONE"
    if top["status"] == "ESCALATED":
        return "PENDING"
    if top["status"] == "ESCALATION_ACCEPTED":
        return "ACCEPTED"
    return "DECLINED"


# --- care plan and risk posture ------------------------------------------

def coverage_gap_flag(care_plan):
    """True while the plan has no authorization in the AUTHORIZED/ACTIVE set."""
    for auth in db.authorizations.values():
        if auth["care_plan_id"] == care_plan["id"] and \
                auth["auth_status"] in AUTHORIZED_SET:
            return False
    return True


def risk_posture(client):
    client_id = client["id"]
    for episode in db.episodes.values():
        if episode["client_id"] == client_id and \
                episode["status"] in ("OPEN", "TRANSITION_OVERSIGHT"):
            return "CRISIS"
    if acuity_score(client_id) >= ACUITY_ELEVATED_THRESHOLD:
        return "ELEVATED"
    if client["capacity_status"] == "ADJUDICATED_INCAPACITATED":
        return "ELEVATED"
    for auth in db.authorizations.values():
        if auth["client_id"] == client_id and \
                auth["coi_status"] in ("PENDING_DISCLOSURE", "DISCLOSED"):
            return "ELEVATED"
    for plan in db.care_plans.values():
        if plan["client_id"] == client_id and plan["status"] == "ACTIVE" \
                and coverage_gap_flag(plan):
            return "ELEVATED"
    return "ROUTINE"


# --- family report cadence ----------------------------------------------

def report_cadence(contact):
    if not contact["is_long_distance"]:
        return "NOT_APPLICABLE", 0
    anchor = contact["last_report_sent_at"] or contact["created_at"]
    due_at = anchor + timedelta(days=contact["reporting_cadence_days"])
    grace_at = due_at + timedelta(days=GRACE_DAYS)
    now = clock.now()
    if now < due_at:
        return "CURRENT", 0
    if now < grace_at:
        return "DUE", 0
    return "OVERDUE", int((now - grace_at).total_seconds() // 86400)


# --- service authorization costing ---------------------------------------

def whole_hours(start_at, end_at):
    return int((end_at - start_at).total_seconds() // 3600)


def coverage_hours_of(start_at, end_at, concurrent_caregivers):
    return whole_hours(start_at, end_at) * concurrent_caregivers


def coordination_costs(coverage_hours, hourly_cost_cents):
    """Pinned evaluation order: hours -> base -> tier -> fee -> total."""
    base_cost_cents = coverage_hours * hourly_cost_cents
    if base_cost_cents < TIER_1_CEILING_CENTS:
        pct = TIER_1_PCT
    elif base_cost_cents < TIER_2_CEILING_CENTS:
        pct = TIER_2_PCT
    else:
        pct = TIER_3_PCT
    fee = round_half_up(Decimal(base_cost_cents) * Decimal(pct) / Decimal(100))
    return {
        "base_cost_cents": base_cost_cents,
        "coordination_fee_cents": fee,
        "total_projected_cost_cents": base_cost_cents + fee,
    }


def closed_intervals_intersect(a_start, a_end, b_start, b_end):
    """Coverage windows are closed: touching endpoints count as intersecting."""
    return a_start <= b_end and b_start <= a_end


def coverage_capacity_holds(client, candidate):
    total = candidate["concurrent_caregivers"]
    for auth in db.authorizations.values():
        if auth["id"] == candidate["id"]:
            continue
        if auth["client_id"] != client["id"]:
            continue
        if auth["auth_status"] not in AUTHORIZED_SET:
            continue
        if closed_intervals_intersect(auth["coverage_start"], auth["coverage_end"],
                                      candidate["coverage_start"],
                                      candidate["coverage_end"]):
            total += auth["concurrent_caregivers"]
    return total <= client["authorized_concurrent_caregivers"]


# --- conference quorum ---------------------------------------------------

def quorum_evaluation(conference, attended_ids, client):
    invited = len(set(conference["invited_contact_ids"]))
    attended = len(set(attended_ids))
    half_met = attended * 2 >= invited
    contacts = [db.contacts[c] for c in set(attended_ids) if c in db.contacts]
    surrogate_present = any(c["is_surrogate_decision_maker"] for c in contacts)
    quorum_met = half_met and surrogate_present
    if client["capacity_status"] in ("DIMINISHED_DOCUMENTED",
                                    "ADJUDICATED_INCAPACITATED"):
        quorum_met = quorum_met and any(
            c["contact_role"] in ("POA_HEALTHCARE", "GUARDIAN") for c in contacts)
    return quorum_met, surrogate_present


def surrogate_present_of(conference):
    contacts = [db.contacts[c] for c in set(conference["attended_contact_ids"])
                if c in db.contacts]
    return any(c["is_surrogate_decision_maker"] for c in contacts)


# --- time entry rating ---------------------------------------------------

def rate_time_entry(client, care_manager, service_type, start_at, end_at,
                    episode):
    raw_minutes = int((end_at - start_at).total_seconds() // 60)
    increment = client["billing_increment_min"]
    rounded_minutes = -(-raw_minutes // increment) * increment
    if service_type == "TRAVEL":
        rate_multiplier = Decimal(client["travel_billing_pct"]) / Decimal(100)
    elif service_type == "CRISIS_RESPONSE" and episode is not None and \
            episode["status"] in ("OPEN", "TRANSITION_OVERSIGHT"):
        rate_multiplier = CRISIS_MULTIPLIER
    else:
        rate_multiplier = Decimal("1.0")
    hour = start_at.hour
    if hour < AFTER_HOURS_END_UTC_HOUR or hour >= AFTER_HOURS_START_UTC_HOUR:
        after_hours_factor = AFTER_HOURS_FACTOR
    else:
        after_hours_factor = PLAIN_FACTOR
    amount = (Decimal(rounded_minutes) * Decimal(care_manager["hourly_rate_cents"])
              * rate_multiplier * after_hours_factor / Decimal(60))
    return {
        "service_date": "%04d-%02d-%02d" % (start_at.year, start_at.month,
                                            start_at.day),
        "raw_minutes": raw_minutes,
        "rounded_minutes": rounded_minutes,
        "rate_multiplier": rate_multiplier,
        "after_hours_factor": after_hours_factor,
        "billable_amount_cents": round_half_up(amount),
    }


def care_manager_entries(care_manager_id, statuses=LIVE_ENTRY_STATUSES):
    return [e for e in db.time_entries.values()
            if e["care_manager_id"] == care_manager_id
            and e["status"] in statuses]


def half_open_overlaps(a_start, a_end, b_start, b_end):
    """TimeEntry intervals are half-open: touching endpoints do not overlap."""
    return a_start < b_end and b_start < a_end


# --- invoice arithmetic --------------------------------------------------

def invoice_line_statuses(variant):
    if variant == "PROVISIONAL":
        return ("SUBMITTED", "APPROVED")
    return ("APPROVED",)


def invoice_candidates(invoice, variant):
    statuses = invoice_line_statuses(variant)
    rows = []
    for entry in db.time_entries.values():
        if entry["client_id"] != invoice["client_id"]:
            continue
        if entry["invoice_id"] is not None:
            continue
        if entry["status"] not in statuses:
            continue
        if not (invoice["period_start"] <= entry["service_date"]
                <= invoice["period_end"]):
            continue
        rows.append(entry)
    rows.sort(key=lambda e: (e["start_at"], e["created_at"], e["_seq"]))
    return rows


def invoice_totals(invoice, variant, retainer_available=None):
    lines = invoice_candidates(invoice, variant)
    subtotal = sum(e["billable_amount_cents"] for e in lines)
    admin_fee = round_half_up(
        Decimal(subtotal) * Decimal(ADMIN_FEE_PCT) / Decimal(100))
    total_due = subtotal + admin_fee
    if retainer_available is None:
        retainer_available = retainer_balance(invoice["client_id"])
    applied = min(retainer_available, total_due)
    if applied < 0:
        applied = 0
    return {
        "variant": variant,
        "line_entry_ids": [e["id"] for e in lines],
        "line_subtotal_cents": subtotal,
        "admin_fee_cents": admin_fee,
        "total_due_cents": total_due,
        "retainer_applied_cents": applied,
        "balance_due_cents": total_due - applied,
    }


# --- ordered cascades ----------------------------------------------------

def client_authorizations(client_id):
    return ordered(by_client(db.authorizations, client_id))


def client_plans(client_id):
    return ordered(by_client(db.care_plans, client_id))


def terminate_authorization(auth, reason):
    auth["auth_status"] = "TERMINATED"
    auth["termination_reason"] = reason
    touch(auth)


def suspend_authorization(auth, reason):
    auth["auth_status"] = "SUSPENDED"
    auth["suspension_reason"] = reason
    touch(auth)


def reactivate_authorization(auth):
    auth["auth_status"] = "ACTIVE"
    auth["suspension_reason"] = "NONE"
    touch(auth)


def discharge_cascade(client):
    """Authorizations terminate, then plans withdraw (PRD 3.1)."""
    for auth in client_authorizations(client["id"]):
        if auth["auth_status"] in LIVE_AUTH_STATUSES:
            terminate_authorization(auth, "CLIENT_DISCHARGED")
    for plan in client_plans(client["id"]):
        if plan["status"] in ("DRAFT", "PENDING_FAMILY_APPROVAL", "ACTIVE"):
            plan["status"] = "WITHDRAWN"
            touch(plan)


def vendor_barred_cascade(vendor):
    for auth in ordered([a for a in db.authorizations.values()
                         if a["vendor_id"] == vendor["id"]]):
        if auth["auth_status"] == "ACTIVE":
            suspend_authorization(auth, "VENDOR_STANDING")
        elif auth["auth_status"] in ("PROPOSED", "AUTHORIZED"):
            terminate_authorization(auth, "VENDOR_STANDING")


def supersede_plan(plan):
    """A predecessor plan is superseded, then its authorizations terminate."""
    plan["status"] = "SUPERSEDED"
    touch(plan)
    for auth in ordered(plan_authorizations(plan["id"])):
        if auth["auth_status"] in LIVE_AUTH_STATUSES:
            terminate_authorization(auth, "PLAN_SUPERSEDED")


def decision_rescinded_cascade(decision):
    for auth in ordered([a for a in db.authorizations.values()
                         if a.get("authorizing_decision_id") == decision["id"]]):
        if auth["auth_status"] in LIVE_AUTH_STATUSES:
            terminate_authorization(auth, "DECISION_RESCINDED")


def guardianship_adjudication_cascade(client, decision):
    """Capacity is adjudicated, so pending approvals fall back to DRAFT."""
    client["capacity_status"] = "ADJUDICATED_INCAPACITATED"
    client["capacity_basis"] = "Guardianship petition granted; decision " + \
        decision["id"]
    for plan in client_plans(client["id"]):
        if plan["status"] == "PENDING_FAMILY_APPROVAL":
            plan["status"] = "DRAFT"
            touch(plan)


def suspend_client_for_nonpayment(client):
    client["status"] = "SUSPENDED_NONPAYMENT"
    for auth in client_authorizations(client["id"]):
        if auth["auth_status"] == "ACTIVE":
            suspend_authorization(auth, "NONPAYMENT")


def restore_client_from_nonpayment(client):
    """Return the client to care once the recomputed balance reaches the floor."""
    if client["status"] != "SUSPENDED_NONPAYMENT":
        return False
    if retainer_balance(client["id"]) < client["retainer_floor_cents"]:
        return False
    client["status"] = "ACTIVE_CARE"
    for auth in client_authorizations(client["id"]):
        if auth["auth_status"] != "SUSPENDED" or \
                auth["suspension_reason"] != "NONPAYMENT":
            continue
        vendor = db.vendors.get(auth["vendor_id"])
        if vendor is not None and vendor["standing"] == "BARRED":
            continue
        if not coverage_capacity_holds(client, auth):
            continue
        reactivate_authorization(auth)
    return True


def release_invoice_entries(invoice):
    for entry in ordered([e for e in db.time_entries.values()
                          if e["invoice_id"] == invoice["id"]]):
        entry["status"] = "APPROVED"
        entry["invoice_id"] = None
        touch(entry)
