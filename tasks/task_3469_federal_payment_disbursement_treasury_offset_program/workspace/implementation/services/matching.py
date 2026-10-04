"""Matching, pool sizing, waterfall allocation, selectors, and overlap rules.

Implements SCAFFOLD §1.3: offset_pool_determination (INTAKE_ESTIMATE and
EXECUTION_FINAL variants), waterfall_allocation, reverse_match_waterfall,
the cross-servicing agency selector, and the reciprocal-agreement window
overlap rule (PRD §2.10).
"""
from constants import CHILD_SUPPORT_PCT
from db import STORE, clock_now
from util import pct_of_cents


def active_policy_for(payment_type):
    """The currently ACTIVE ExemptionPolicy for a payment_type, if any."""
    for p in STORE["policies"].values():
        if p["payment_type"] == payment_type and p["status"] == "ACTIVE":
            return p
    return None


def agreement_covers(state_code, directions, now=None):
    """An ACTIVE agreement for state_code whose direction is in `directions`
    and whose half-open window contains the clock: effective_from <= clock <
    effective_until (PRD §2.10)."""
    now = now if now is not None else clock_now()
    for a in STORE["agreements"].values():
        if (
            a["status"] == "ACTIVE"
            and a["state_code"] == state_code
            and a["direction"] in directions
            and a["effective_from"] <= now < a["effective_until"]
        ):
            return True
    return False


def _waterfall_order(debts):
    """(priority_rank ASC, delinquent_since ASC, created_at ASC) — never the
    server-minted id. _seq is the deterministic tie-break when created_at
    ties under the logical clock."""
    return sorted(
        debts,
        key=lambda d: (d["priority_rank"], d["delinquent_since"], d["created_at"], d["_seq"]),
    )


def eligible_debts_for_payment(payment):
    """ACTIVE debts whose debtor_tin matches the payment's payee_tin; state
    debts additionally require a covering FED_TO_STATE/BIDIRECTIONAL agreement
    at the evaluation clock (PRD §3.4)."""
    now = clock_now()
    out = []
    for d in STORE["debts"].values():
        if d["status"] != "ACTIVE":
            continue
        if d["debtor_tin"] != payment["payee_tin"]:
            continue
        creditor = STORE["creditors"].get(d["creditor_agency_id"])
        if creditor is not None and creditor["creditor_type"] == "STATE":
            if not agreement_covers(creditor["state_code"], ("FED_TO_STATE", "BIDIRECTIONAL"), now):
                continue
        out.append(d)
    return _waterfall_order(out)


def intake_projection(policy, amount_cents):
    """INTAKE_ESTIMATE variant: EXEMPT -> 0, FULL -> amount, PARTIAL ->
    max(0, amount - protected_minimum_cents). The percentage cap and the
    child-support branch are NOT applied at intake (PRD §3.4)."""
    if policy["exemption_class"] == "EXEMPT":
        return 0
    if policy["exemption_class"] == "FULL":
        return amount_cents
    return max(0, amount_cents - policy["protected_minimum_cents"])


def execution_pool(payment, eligible_debts):
    """EXECUTION_FINAL variant (PRD §3.4): EXEMPT -> 0; FULL -> amount;
    PARTIAL -> min(base, round_half_up(amount * pct)) where pct is 0.65 when
    any eligible matched debt is CHILD_SUPPORT, else the policy's
    max_offset_pct."""
    policy = active_policy_for(payment["payment_type"])
    amount = payment["amount_cents"]
    if policy["exemption_class"] == "EXEMPT":
        return 0
    if policy["exemption_class"] == "FULL":
        return amount
    base = max(0, amount - policy["protected_minimum_cents"])
    if any(d["debt_type"] == "CHILD_SUPPORT" for d in eligible_debts):
        pct = CHILD_SUPPORT_PCT
    else:
        pct = policy["max_offset_pct"]
    cap = pct_of_cents(amount, pct)
    return min(base, cap)


def reverse_match(payee_tin, requested_amount_cents):
    """Mirror-image waterfall over ACTIVE debts of FEDERAL creditors whose
    debtor_tin matches (PRD §3.8). Returns the matches array."""
    eligible = []
    for d in STORE["debts"].values():
        if d["status"] != "ACTIVE" or d["debtor_tin"] != payee_tin:
            continue
        creditor = STORE["creditors"].get(d["creditor_agency_id"])
        if creditor is not None and creditor["creditor_type"] == "FEDERAL":
            eligible.append(d)
    ordered = _waterfall_order(eligible)
    remaining = requested_amount_cents
    matches = []
    for d in ordered:
        if remaining <= 0:
            break
        take = min(remaining, d["current_balance_cents"])
        if take > 0:
            matches.append({"debt_id": d["id"], "matched_amount_cents": take})
            remaining -= take
    return matches


def pick_collection_agency():
    """Cross-servicing selector: the eligible pool is agencies whose count of
    concurrently open (INITIATED or ACTIVE) cross-servicing actions is below
    capacity_max_active; the pool is ranked by registration order
    (created_at ASC). Returns None when the pool is empty."""
    eligible = []
    for a in STORE["agencies"].values():
        open_count = sum(
            1
            for act in STORE["actions"].values()
            if act["collection_agency_id"] == a["id"]
            and act["status"] in ("INITIATED", "ACTIVE")
        )
        if open_count < a["capacity_max_active"]:
            eligible.append(a)
    if not eligible:
        return None
    eligible.sort(key=lambda a: (a["created_at"], a["_seq"]))
    return eligible[0]


def _directions_conflict(d1, d2):
    """BIDIRECTIONAL conflicts with every scope; otherwise a scope conflicts
    only with itself (PRD §2.10)."""
    if d1 == "BIDIRECTIONAL" or d2 == "BIDIRECTIONAL":
        return True
    return d1 == d2


def has_active_agreement_overlap(state_code, direction, effective_from, effective_until, exclude_id=None):
    """Half-open overlap against ACTIVE agreements of the same state with a
    conflicting direction scope."""
    for a in STORE["agreements"].values():
        if exclude_id is not None and a["id"] == exclude_id:
            continue
        if a["status"] != "ACTIVE" or a["state_code"] != state_code:
            continue
        if not _directions_conflict(direction, a["direction"]):
            continue
        if effective_from < a["effective_until"] and a["effective_from"] < effective_until:
            return True
    return False
