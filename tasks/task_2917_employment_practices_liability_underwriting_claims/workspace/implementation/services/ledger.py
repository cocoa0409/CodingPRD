"""Derived ledgers, recomputations and the four cascade chains (PRD 2.11)."""

from decimal import Decimal

import calc
import store


# --------------------------------------------------------------------------
# claim-level ledgers
# --------------------------------------------------------------------------
def claim_retention_satisfied(claim):
    return sum(p["retention_portion_cents"]
               for p in store.payments_of_claim(claim["id"])
               if p["status"] == "APPROVED")


def claim_indemnity_paid(claim):
    return sum(p["insurer_portion_cents"]
               for p in store.payments_of_claim(claim["id"])
               if p["status"] == "APPROVED")


def claim_defense_paid(claim):
    total = 0
    for assignment in store.assignments_of_claim(claim["id"]):
        for invoice in store.invoices_of_assignment(assignment["id"]):
            if invoice["status"] == "APPROVED":
                total += invoice["allowed_amount_cents"]
    return total


def claim_retention_basis(claim):
    return ("GROUP_AGGREGATED" if claim.get("related_claim_group_id")
            else "PER_CLAIM")


def claim_applied_retention(claim):
    if claim.get("related_claim_group_id"):
        return 0
    per_claim = claim.get("per_claim_retention_cents")
    if per_claim is None:
        return None
    applied = per_claim - claim.get("pre_suit_credit_cents", 0)
    return applied if applied > 0 else 0


# --------------------------------------------------------------------------
# group-level ledgers
# --------------------------------------------------------------------------
def group_members(group):
    return sorted(store.members_of_group(group["id"]),
                  key=store.sort_key_created)


def group_shared_retention(group):
    best = 0
    for claim in group_members(group):
        value = claim.get("per_claim_retention_cents") or 0
        if value > best:
            best = value
    return best


def group_retention_basis_claim_id(group):
    best_id = None
    best_value = None
    for claim in group_members(group):
        value = claim.get("per_claim_retention_cents") or 0
        if best_value is None or value > best_value:
            best_value = value
            best_id = claim["id"]
    return best_id


def group_retention_paid(group):
    total = 0
    for claim in group_members(group):
        total += claim_retention_satisfied(claim)
    return total


def group_of_claim(claim):
    group_id = claim.get("related_claim_group_id")
    if not group_id:
        return None
    return store.GROUPS.get(group_id)


# --------------------------------------------------------------------------
# policy-level ledgers
# --------------------------------------------------------------------------
def policy_indemnity_paid(policy):
    total = 0
    for claim in store.claims_of_policy(policy["id"]):
        total += claim_indemnity_paid(claim)
    return total


def policy_defense_spend(policy):
    total = 0
    for claim in store.claims_of_policy(policy["id"]):
        total += claim_defense_paid(claim)
    return total


def policy_remaining(policy):
    return (policy["aggregate_limit_cents"] - policy_indemnity_paid(policy)
            - policy_defense_spend(policy))


def _sublimit_consumed(policy, bucket):
    total = 0
    for claim in store.claims_of_policy(policy["id"]):
        for payment in store.payments_of_claim(claim["id"]):
            if (payment["status"] == "APPROVED"
                    and payment["sublimit_bucket"] == bucket):
                total += payment["insurer_portion_cents"]
    return total


def policy_wage_hour_remaining(policy):
    return (policy["wage_hour_sublimit_cents"]
            - _sublimit_consumed(policy, "WAGE_HOUR"))


def policy_third_party_remaining(policy):
    return (policy["third_party_sublimit_cents"]
            - _sublimit_consumed(policy, "THIRD_PARTY"))


def policy_limit_posture(policy):
    remaining = policy_remaining(policy)
    if remaining <= 0:
        return "EXHAUSTED"
    if remaining < policy["aggregate_limit_cents"]:
        return "ERODED"
    return "OPEN"


def limit_ledger(policy):
    return {
        "policy_id": policy["id"],
        "aggregate_limit_cents": policy["aggregate_limit_cents"],
        "indemnity_paid_cents": policy_indemnity_paid(policy),
        "defense_spend_cents": policy_defense_spend(policy),
        "aggregate_limit_remaining_cents": policy_remaining(policy),
        "wage_hour_sublimit_cents": policy["wage_hour_sublimit_cents"],
        "wage_hour_sublimit_remaining_cents": policy_wage_hour_remaining(policy),
        "third_party_sublimit_cents": policy["third_party_sublimit_cents"],
        "third_party_sublimit_remaining_cents":
            policy_third_party_remaining(policy),
        "limit_posture": policy_limit_posture(policy),
    }


# --------------------------------------------------------------------------
# defense ledgers
# --------------------------------------------------------------------------
def assignment_budget_spent(assignment):
    return sum(i["allowed_amount_cents"]
               for i in store.invoices_of_assignment(assignment["id"])
               if i["status"] == "APPROVED")


def assignment_budget_remaining(assignment):
    return assignment["budget_cap_cents"] - assignment_budget_spent(assignment)


def firm_open_matter_count(firm):
    return len([a for a in store.ASSIGNMENTS.values()
                if a["panel_firm_id"] == firm["id"]
                and a["status"] in ("ACTIVE", "SUSPENDED_FUNDING")])


def firm_window_matter_count(firm, window_from, window_to):
    """Window-scoped capacity count under the half-open overlap rule."""
    count = 0
    for assignment in store.ASSIGNMENTS.values():
        if assignment["panel_firm_id"] != firm["id"]:
            continue
        if assignment["status"] not in ("ACTIVE", "SUSPENDED_FUNDING"):
            continue
        if (assignment["engagement_from"] < window_to
                and window_from < assignment["engagement_to"]):
            count += 1
    return count


# --------------------------------------------------------------------------
# applicant recomputation and the service -> applicant -> assessment cascade
# --------------------------------------------------------------------------
def recompute_applicant(applicant, bump=True):
    services = store.services_of_applicant(applicant["id"])
    applicant["turnover_pct"] = calc.turnover_pct(
        applicant["prior_year_separations"], applicant["total_headcount"])
    applicant["hazard_load_pct"] = calc.hazard_load_pct(applicant)
    applicant["risk_credit_pct"] = calc.risk_credit_pct(services)
    applicant["exposure_score"] = calc.exposure_score(applicant, services)
    if bump:
        store.touch(applicant)
    return applicant


def stale_priced_assessments(applicant_id):
    """Second hop: PRICED -> REFERRED, and REFERRED rows are marked stale too."""
    touched = []
    for assessment in store.assessments_of_applicant(applicant_id):
        if assessment["status"] == "PRICED":
            assessment["status"] = "REFERRED"
            assessment["credit_basis_stale"] = True
            store.touch(assessment)
            touched.append(assessment)
        elif assessment["status"] == "REFERRED":
            assessment["credit_basis_stale"] = True
            store.touch(assessment)
            touched.append(assessment)
    return touched


def service_change_cascade(service):
    """Hop 1: applicant credit basis. Hop 2: that applicant's assessments."""
    applicant = store.APPLICANTS.get(service["applicant_id"])
    if applicant is None:
        return
    recompute_applicant(applicant)
    stale_priced_assessments(applicant["id"])


# --------------------------------------------------------------------------
# policy suspension / reinstatement cascade (depth 3)
# --------------------------------------------------------------------------
GATED_CLAIM_STATUSES = ("UNDER_REVIEW", "COVERAGE_ACCEPTED", "DEFENSE_OPEN")
HELD_INVOICE_STATUSES = ("SUBMITTED", "UNDER_AUDIT", "ADJUSTED")


def suspend_cascade(policy):
    for claim in sorted(store.claims_of_policy(policy["id"]),
                        key=store.sort_key_created):
        if claim["status"] not in GATED_CLAIM_STATUSES:
            continue
        claim["coverage_gated"] = True
        store.touch(claim)
        for assignment in sorted(store.assignments_of_claim(claim["id"]),
                                 key=store.sort_key_created):
            if assignment["status"] != "ACTIVE":
                continue
            assignment["status"] = "SUSPENDED_FUNDING"
            assignment["hold_reason"] = "POLICY_SUSPENDED"
            store.touch(assignment)
            for invoice in sorted(store.invoices_of_assignment(assignment["id"]),
                                  key=store.sort_key_created):
                if invoice["status"] not in HELD_INVOICE_STATUSES:
                    continue
                invoice["hold_reason"] = "POLICY_SUSPENDED"
                store.touch(invoice)


def reinstate_cascade(policy):
    for claim in sorted(store.claims_of_policy(policy["id"]),
                        key=store.sort_key_created):
        if not claim.get("coverage_gated"):
            continue
        claim["coverage_gated"] = False
        store.touch(claim)
        for assignment in sorted(store.assignments_of_claim(claim["id"]),
                                 key=store.sort_key_created):
            if (assignment["status"] != "SUSPENDED_FUNDING"
                    or assignment.get("hold_reason") != "POLICY_SUSPENDED"):
                continue
            assignment["status"] = "ACTIVE"
            assignment["hold_reason"] = None
            store.touch(assignment)
            for invoice in sorted(store.invoices_of_assignment(assignment["id"]),
                                  key=store.sort_key_created):
                if invoice.get("hold_reason") != "POLICY_SUSPENDED":
                    continue
                invoice["hold_reason"] = None
                store.touch(invoice)


# --------------------------------------------------------------------------
# claim closure cascade (depth 2)
# --------------------------------------------------------------------------
def close_claim_assignments(claim):
    firms = []
    for assignment in sorted(store.assignments_of_claim(claim["id"]),
                             key=store.sort_key_created):
        if assignment["status"] not in ("ACTIVE", "SUSPENDED_FUNDING"):
            continue
        assignment["status"] = "CLOSED"
        store.touch(assignment)
        firm = store.FIRMS.get(assignment["panel_firm_id"])
        if firm is not None and firm["id"] not in [f["id"] for f in firms]:
            firms.append(firm)
    for firm in firms:
        store.touch(firm)


# --------------------------------------------------------------------------
# limit-exhaustion cascade (hops 3 and 4 of the payment approval chain)
# --------------------------------------------------------------------------
def exhaustion_cascade(policy, instant):
    firms = []
    for claim in sorted(store.claims_of_policy(policy["id"]),
                        key=store.sort_key_created):
        for assignment in sorted(store.assignments_of_claim(claim["id"]),
                                 key=store.sort_key_created):
            if assignment["status"] not in ("ACTIVE", "SUSPENDED_FUNDING"):
                continue
            assignment["status"] = "CLOSED"
            assignment["funding_ceased_at"] = instant
            store.touch(assignment)
            firm = store.FIRMS.get(assignment["panel_firm_id"])
            if firm is not None and firm["id"] not in [f["id"] for f in firms]:
                firms.append(firm)
            for invoice in sorted(store.invoices_of_assignment(assignment["id"]),
                                  key=store.sort_key_created):
                if invoice["status"] not in HELD_INVOICE_STATUSES:
                    continue
                invoice["status"] = "REJECTED"
                invoice["hold_reason"] = "LIMIT_EXHAUSTED"
                store.touch(invoice)
    for firm in firms:
        store.touch(firm)


# --------------------------------------------------------------------------
# group locking
# --------------------------------------------------------------------------
def refresh_group_lock(group):
    shared = group_shared_retention(group)
    paid = group_retention_paid(group)
    if group["status"] == "OPEN" and paid >= shared:
        group["status"] = "LOCKED"
    elif group["status"] == "LOCKED" and paid < shared:
        group["status"] = "OPEN"
    store.touch(group)
    return group


# --------------------------------------------------------------------------
# outstanding retention for the settlement waterfall
# --------------------------------------------------------------------------
def outstanding_retention(claim):
    group = group_of_claim(claim)
    if group is not None:
        outstanding = (group_shared_retention(group)
                       - group_retention_paid(group))
    else:
        applied = claim_applied_retention(claim) or 0
        outstanding = applied - claim_retention_satisfied(claim)
    return outstanding if outstanding > 0 else 0
