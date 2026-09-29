"""Shared repricing, scoring and cascade machinery (PRD 2.8, 3.2-3.9)."""
import calc
import clock
import db

LINE_PRICED_FIELDS = (
    "extended_list_cents",
    "extended_cost_cents",
    "volume_tier_level_applied",
    "bundle_discount_applied_pct",
    "effective_stack_discount_pct",
    "provisional_net_cents",
    "final_net_cents",
)


# ---- pricing ---------------------------------------------------------------

def compute_pricing(quote, policy=None, lines=None):
    """Both passes of C1-C4 plus C7 figures, without writing anything."""
    if policy is None:
        policy = db.policy(quote["desk_policy_id"])
    if lines is None:
        lines = db.lines_of_quote(quote["id"])

    priced = [calc.price_line(line, lines, quote, policy) for line in lines]

    list_total = sum(p["extended_list_cents"] for p in priced)
    cost_total = sum(p["extended_cost_cents"] for p in priced)
    provisional_subtotal = sum(p["provisional_net_cents"] for p in priced)
    final_subtotal = sum(p["final_net_cents"] for p in priced)

    provisional = calc.order_totals(policy, quote, provisional_subtotal)
    final = calc.order_totals(policy, quote, final_subtotal)

    provisional_blended = calc.blended_discount(
        list_total, provisional["net_subtotal_cents"], provisional["volume_rebate_cents"]
    )
    final_blended = calc.blended_discount(
        list_total, final["net_subtotal_cents"], final["volume_rebate_cents"]
    )
    provisional_margin = calc.margin_pct(provisional["net_total_cents"], cost_total)
    final_margin = calc.margin_pct(final["net_total_cents"], cost_total)

    has_accepted = any(
        e["status"] == "ACCEPTED" for e in db.exceptions_of_quote(quote["id"])
    )
    level = calc.required_level(policy["id"], final_blended, has_accepted)

    return {
        "policy": policy,
        "lines": lines,
        "priced": priced,
        "list_total_cents": list_total,
        "cost_total_cents": cost_total,
        "provisional_net_total_cents": provisional["net_total_cents"],
        "final_net_total_cents": final["net_total_cents"],
        "provisional_blended_discount_pct": provisional_blended,
        "final_blended_discount_pct": final_blended,
        "provisional_margin_pct": provisional_margin,
        "final_margin_pct": final_margin,
        "volume_rebate_cents": final["volume_rebate_cents"],
        "payment_terms_uplift_cents": final["payment_terms_uplift_cents"],
        "required_approval_level": level,
        "margin_give_up_cents": calc.margin_give_up_cents(
            policy, final_margin, final["net_total_cents"]
        ),
        "arrangement_type": calc.classify_arrangement(lines),
    }


def reprice(quote, policy=None):
    """Reprice every line and roll the quote header up (PRD 3.2, 3.3)."""
    result = compute_pricing(quote, policy=policy)
    by_id = {line["id"]: line for line in result["lines"]}
    for computed in result["priced"]:
        line = by_id[computed["id"]]
        changed = False
        for field in LINE_PRICED_FIELDS:
            if line.get(field) != computed[field]:
                line[field] = computed[field]
                changed = True
        if changed:
            db.touch(line)

    for field in (
        "list_total_cents",
        "cost_total_cents",
        "provisional_net_total_cents",
        "final_net_total_cents",
        "provisional_blended_discount_pct",
        "final_blended_discount_pct",
        "provisional_margin_pct",
        "final_margin_pct",
        "volume_rebate_cents",
        "payment_terms_uplift_cents",
        "required_approval_level",
        "arrangement_type",
    ):
        quote[field] = result[field]
    return result


def recompute_approval_level(quote, policy=None):
    """C3 level only, for exception accept and revoke (PRD 3.5)."""
    if policy is None:
        policy = db.policy(quote["desk_policy_id"])
    has_accepted = any(
        e["status"] == "ACCEPTED" for e in db.exceptions_of_quote(quote["id"])
    )
    quote["required_approval_level"] = calc.required_level(
        policy["id"], quote["final_blended_discount_pct"], has_accepted
    )
    return quote["required_approval_level"]


# ---- risk scoring ----------------------------------------------------------

def score_term(term):
    term["severity_factor"] = calc.severity_factor(
        term["term_category"], term["requested_numeric_value"]
    )
    term["risk_contribution"] = calc.risk_contribution(
        term["term_category"], term["severity_factor"]
    )
    return term


def rescore_quote_terms(quote, policy=None):
    """Recompute both quote scores and place requires_cfo_cosign (PRD 3.4)."""
    if policy is None:
        policy = db.policy(quote["desk_policy_id"])
    scored = calc.score_terms(quote["id"])
    quote["terms_risk_score_aggregate"] = scored["aggregate"]
    quote["terms_risk_score_dominant"] = scored["dominant"]

    cosign_required = scored["dominant"] >= calc.dec(policy["terms_cfo_risk_threshold"])
    dominant = scored["dominant_term"]
    for term in db.terms_of_quote(quote["id"]):
        wanted = bool(cosign_required and dominant is not None and term["id"] == dominant["id"])
        if term["requires_cfo_cosign"] != wanted:
            term["requires_cfo_cosign"] = wanted
            db.touch(term)
    return scored


# ---- assessments -----------------------------------------------------------

def stale_assessments(quote):
    """Version advance past the snapshot staleness rule (PRD 3.6)."""
    for row in db.assessments_of_quote(quote["id"]):
        if row["status"] not in ("ASSESSED", "CLEARED", "BLOCKED"):
            continue
        if quote["version"] <= row["snapshot_quote_version"]:
            continue
        row["status"] = "STALE"
        row["assessed_by_user_id"] = None
        row["assessed_at"] = None
        row["assessment_note"] = None
        db.touch(row)


def revrec_gate_satisfied(quote):
    if quote["arrangement_type"] == "SINGLE_ELEMENT":
        return True
    return any(
        a["status"] == "CLEARED" for a in db.assessments_of_quote(quote["id"])
    )


# ---- compensating moves ----------------------------------------------------

def release_accepted_exceptions(quote):
    """ACCEPTED -> RELEASED with the allowance returned (PRD 2.12)."""
    released = []
    account = db.account(quote["account_id"])
    for row in db.exceptions_of_quote(quote["id"]):
        if row["status"] != "ACCEPTED":
            continue
        row["status"] = "RELEASED"
        row["released_at"] = clock.now()
        db.touch(row)
        if account is not None:
            account["exception_allowance_used_cents"] -= int(row["allowance_consumed_cents"])
            db.touch(account)
        released.append(row["id"])
    return released


def withdraw_pending_terms(quote):
    withdrawn = []
    for term in db.terms_of_quote(quote["id"]):
        if term["review_state"] != "PENDING":
            continue
        term["review_state"] = "WITHDRAWN"
        db.touch(term)
        withdrawn.append(term["id"])
    return withdrawn


def void_pending_steps(request):
    voided = []
    for step in db.steps_of_request(request["id"]):
        if step["decision"] != "PENDING":
            continue
        step["decision"] = "VOIDED"
        step["decided_at"] = clock.now()
        db.touch(step)
        voided.append(step["id"])
    return voided


# ---- approval steps --------------------------------------------------------

def create_step(request, policy, level, escalated_from_step_level=None):
    """One approval step with its C5 turnaround fields (PRD 3.7, 3.8)."""
    band = db.tier_at_level(policy["id"], level)
    step = {
        "approval_request_id": request["id"],
        "level": level,
        "assigned_role": band["required_role"] if band else None,
        "decision": "PENDING",
        "acting_user_id": None,
        "delegation_grant_id": None,
        "decided_at": None,
        "turnaround_hours": None,
        "decision_note": None,
        "escalated_from_step_level": escalated_from_step_level,
    }
    db.insert("approval_steps", step)
    sla = calc.step_sla(policy, level, step["created_at"])
    step["in_surge_window"] = sla["in_surge_window"]
    step["sla_hours_effective"] = sla["sla_hours_effective"]
    step["sla_due_at"] = sla["sla_due_at"]
    return step


# ---- quote-level outcomes --------------------------------------------------

def quote_approved(quote, policy=None):
    """PENDING_APPROVAL -> APPROVED with the re-based validity (PRD 3.8)."""
    if policy is None:
        policy = db.policy(quote["desk_policy_id"])
    quote["status"] = "APPROVED"
    quote["approved_at"] = clock.now()
    quote["expires_at"] = calc.approval_expiry(policy, quote["approved_at"])
    db.touch(quote)


def quote_rejected(quote):
    """PENDING_APPROVAL -> REJECTED with its withdraw-and-release cascades."""
    quote["status"] = "REJECTED"
    db.touch(quote)
    withdraw_pending_terms(quote)
    release_accepted_exceptions(quote)


# ---- request join ----------------------------------------------------------

DISCOUNT_JOIN_OK = ("NOT_REQUIRED", "CLEARED")
TERMS_JOIN_OK = ("NOT_REQUIRED", "CLEARED")


def approve_request(request, quote, policy=None):
    request["status"] = "APPROVED"
    request["decided_at"] = clock.now()
    request["total_turnaround_hours"] = calc.turnaround_hours(
        request["submitted_at"], request["decided_at"]
    )
    request["sla_state"] = "MET" if request["escalation_count"] == 0 else "BREACHED"
    db.touch(request)
    quote_approved(quote, policy=policy)


def reject_request(request, quote):
    request["status"] = "REJECTED"
    request["decided_at"] = clock.now()
    request["total_turnaround_hours"] = calc.turnaround_hours(
        request["submitted_at"], request["decided_at"]
    )
    request["sla_state"] = "BREACHED" if request["escalation_count"] > 0 else "MET"
    db.touch(request)
    quote_rejected(quote)


def try_join(request, quote, policy=None):
    """OPEN -> APPROVED once both axes have joined (PRD 3.7)."""
    if request["status"] != "OPEN":
        return False
    if request["discount_track_state"] not in DISCOUNT_JOIN_OK:
        return False
    if request["terms_track_state"] not in TERMS_JOIN_OK:
        return False
    approve_request(request, quote, policy=policy)
    return True


def maybe_clear_terms_axis(request, quote, policy=None):
    """The three-part terms-axis clearing condition (PRD 3.7)."""
    if request["terms_track_state"] != "PENDING_LEGAL":
        return False
    terms = db.terms_of_quote(quote["id"])
    if any(t["review_state"] == "PENDING" for t in terms):
        return False
    if request["requires_cfo_cosign"]:
        cosigned = False
        for term in terms:
            if term["requires_cfo_cosign"] and term["cfo_cosigned_at"] is not None:
                cosigned = True
        if not cosigned:
            return False
    request["terms_track_state"] = "CLEARED"
    db.touch(request)
    try_join(request, quote, policy=policy)
    return True
