"""The adjudication pipeline (PRD 3.5 - 3.8).

A pass proceeds in a strictly fixed order: line pricing, then the case-rate
allocation where applicable, then the member cost share, then the out-of-pocket
cap reconciliation, then the coordination-of-benefits offset, and finally the
claim-level outcome resolution.
"""

from decimal import Decimal

from store import db
from services.accumulators import snapshot
from services.authorizations import consume, release
from services.events import append_event
from services.lookup import (
    authorization_candidates,
    applicable_rules,
    line_is_covered,
    lines_of,
    match_coverage_segment,
    member_of,
    plan_of_member,
    provider_of,
    select_authorization,
    select_contract,
    select_fee_rate,
)
from services.money import dec, multiply_cents, round_half_up

COPAY_PROCEDURE_CODES = ("99213", "99214")
HARD_DENY_RANK_MAX = 10

MONEY_FIELDS = (
    "allowed_amount_cents",
    "deductible_applied_cents",
    "copay_cents",
    "coinsurance_cents",
    "member_liability_cents",
    "plan_paid_cents",
)

CLAIM_TOTAL_FIELDS = (
    "total_allowed_cents",
    "total_deductible_applied_cents",
    "total_member_liability_cents",
    "total_plan_paid_cents",
)


# --------------------------------------------------------------------------
# line resets
# --------------------------------------------------------------------------
def zero_line_money(line):
    for field in MONEY_FIELDS:
        line[field] = 0


def release_line_units(line):
    """A line that was holding units gives them back and the grant re-derives."""
    if line.get("authorization_id"):
        auth = db.authorizations.get(line["authorization_id"])
        if auth is not None:
            release(auth, line["units"])


def reset_lines(lines):
    """Wipe the slate before a pass: every line returns to PENDING."""
    for line in lines:
        if line["line_status"] == "PRICED":
            release_line_units(line)
        line["line_status"] = "PENDING"
        zero_line_money(line)
        line["authorization_id"] = None
        line["bundled_into_line_number"] = None
        line["edit_reason_code"] = None
        line["_rule"] = None
        db.touch(line)


def zero_claim_totals(claim):
    for field in CLAIM_TOTAL_FIELDS:
        claim[field] = 0


# --------------------------------------------------------------------------
# coverage matching (re-done on every pass)
# --------------------------------------------------------------------------
def apply_coverage_match(claim, lines):
    earliest = min(line["service_date"] for line in lines)
    matched = match_coverage_segment(claim["member_id"], earliest)
    claim["coverage_id"] = matched["id"] if matched else None
    if matched is None or matched["cob_order"] == "PRIMARY":
        claim["cob_role"] = "PRIMARY"
    else:
        claim["cob_role"] = "SECONDARY"
    return matched


def earliest_service_year(lines):
    return int(min(line["service_date"] for line in lines)[:4])


# --------------------------------------------------------------------------
# edit pass
# --------------------------------------------------------------------------
def _deny_line(line, reason_code, rule):
    line["line_status"] = "DENIED"
    line["allowed_amount_cents"] = 0
    line["edit_reason_code"] = reason_code
    line["bundled_into_line_number"] = None
    line["_rule"] = rule


def _pend_line(line, reason_code, rule):
    line["line_status"] = "PENDED"
    line["allowed_amount_cents"] = 0
    line["edit_reason_code"] = reason_code
    line["authorization_id"] = None
    line["_rule"] = rule


def _bundle_line(line, into_line_number, rule):
    line["line_status"] = "BUNDLED"
    line["allowed_amount_cents"] = 0
    line["member_liability_cents"] = 0
    line["plan_paid_cents"] = 0
    line["bundled_into_line_number"] = into_line_number
    line["edit_reason_code"] = rule["reason_code"]
    line["_rule"] = rule


def _rule_fires(rule, line, lines):
    """Returns (fired, surviving_line_number)."""
    kind = rule["edit_type"]
    if kind == "BUNDLING":
        survivors = [
            other
            for other in lines
            if other["id"] != line["id"]
            and other["service_date"] == line["service_date"]
            and other["procedure_code"] == rule["primary_code"]
        ]
        if survivors:
            return True, min(other["line_number"] for other in survivors)
        return False, None
    if kind == "MUTUALLY_EXCLUSIVE":
        survivors = [
            other
            for other in lines
            if other["id"] != line["id"] and other["procedure_code"] == rule["primary_code"]
        ]
        return (bool(survivors), None)
    if kind == "UNITS_LIMIT":
        return (line["units"] > rule["max_units"], None)
    # AUTH_REQUIRED keys on primary_code, which already matched.
    return True, None


def _match_authorization(claim, line, rule):
    auth = select_authorization(claim, line)
    if auth is None:
        _pend_line(line, "PEND_AUTH_MISSING", rule)
        return
    if auth["status"] == "REVOKED":
        _pend_line(line, "PEND_AUTH_REVOKED", rule)
        return
    if auth["authorized_units"] - auth["units_consumed"] < line["units"]:
        _pend_line(line, "PEND_AUTH_UNITS_EXCEEDED", rule)
        return
    line["line_status"] = "PRICED"
    line["authorization_id"] = auth["id"]
    consume(auth, line["units"])


def _apply_edits(claim, line, lines):
    for rule in applicable_rules(line):
        fired, into_line_number = _rule_fires(rule, line, lines)
        if not fired:
            continue
        if rule["severity"] == "INFORM":
            # Purely advisory: the line keeps the outcome it would otherwise
            # have reached and only its edit_reason_code is stamped.
            line["edit_reason_code"] = rule["reason_code"]
            continue
        if rule["edit_type"] == "BUNDLING":
            _bundle_line(line, into_line_number, rule)
            return
        if rule["edit_type"] in ("MUTUALLY_EXCLUSIVE", "UNITS_LIMIT"):
            if rule["severity"] == "DENY":
                _deny_line(line, rule["reason_code"], rule)
            else:
                _pend_line(line, rule["reason_code"], rule)
            return
        if rule["edit_type"] == "AUTH_REQUIRED":
            _match_authorization(claim, line, rule)
            return


# --------------------------------------------------------------------------
# pricing
# --------------------------------------------------------------------------
def _price_lines(claim, plan, provider, pricing_lines, rates):
    """Per-line allowed amounts; returns the claim-level pricing variant."""
    variant = "UNPRICED"
    case_contract = None
    for line in pricing_lines:
        rate = rates.get(line["id"])
        if rate is None:
            continue
        base = rate["allowed_amount_cents"] * line["units"]
        contract = select_contract(claim["provider_id"], plan["id"], line["service_date"])
        if contract is not None and contract["pricing_method"] == "PCT_OF_FEE_SCHEDULE":
            variant = "CONTRACT_PRICED"
            # A negotiated contract supersedes network status: the
            # out-of-network penalty is never applied under this variant.
            allowed = multiply_cents(base, contract["contract_pct"])
            line["allowed_amount_cents"] = min(allowed, line["billed_amount_cents"])
        elif contract is not None and contract["pricing_method"] == "CASE_RATE":
            variant = "CASE_RATE_PRICED"
            if case_contract is None:
                case_contract = contract
        else:
            variant = "FEE_SCHEDULE_PRICED"
            if provider["network_status"] == "OUT_OF_NETWORK":
                allowed = round_half_up(
                    dec(base) * (Decimal(1) - dec(plan["out_of_network_penalty_pct"]))
                )
            else:
                allowed = base
            line["allowed_amount_cents"] = min(allowed, line["billed_amount_cents"])
    if case_contract is not None:
        _allocate_case_rate(case_contract, pricing_lines)
    return variant


def _allocate_case_rate(contract, pricing_lines):
    """Largest-remainder pro-rata allocation of the case-rate pool (PRD 3.5)."""
    total_billed = sum(line["billed_amount_cents"] for line in pricing_lines)
    if total_billed <= 0:
        for line in pricing_lines:
            line["allowed_amount_cents"] = 0
        return
    pool = min(contract["case_rate_cents"], total_billed)
    remainders = []
    for line in pricing_lines:
        numerator = pool * line["billed_amount_cents"]
        whole, remainder = divmod(numerator, total_billed)
        line["allowed_amount_cents"] = whole
        remainders.append((remainder, line))
    leftover = pool - sum(line["allowed_amount_cents"] for line in pricing_lines)
    remainders.sort(key=lambda item: (-item[0], item[1]["line_number"]))
    for index in range(leftover):
        remainders[index][1]["allowed_amount_cents"] += 1
    for line in pricing_lines:
        line["allowed_amount_cents"] = min(
            line["allowed_amount_cents"], line["billed_amount_cents"]
        )


# --------------------------------------------------------------------------
# cost share, out-of-pocket cap, coordination of benefits
# --------------------------------------------------------------------------
def _cost_share(plan, pricing_lines, snap):
    ded_remaining = max(
        0, plan["deductible_individual_cents"] - snap["deductible_applied_cents"]
    )
    ordered = sorted(pricing_lines, key=lambda l: (l["service_date"], l["line_number"]))
    for line in ordered:
        if line["procedure_code"] in COPAY_PROCEDURE_CODES:
            line["copay_cents"] = min(
                plan["copay_office_visit_cents"], line["allowed_amount_cents"]
            )
            line["deductible_applied_cents"] = 0
            base_after = line["allowed_amount_cents"] - line["copay_cents"]
        else:
            line["copay_cents"] = 0
            line["deductible_applied_cents"] = min(
                ded_remaining, line["allowed_amount_cents"]
            )
            ded_remaining -= line["deductible_applied_cents"]
            base_after = line["allowed_amount_cents"] - line["deductible_applied_cents"]
        line["coinsurance_cents"] = multiply_cents(
            base_after, plan["coinsurance_member_pct"]
        )
        line["member_liability_cents"] = (
            line["copay_cents"] + line["deductible_applied_cents"] + line["coinsurance_cents"]
        )
        line["plan_paid_cents"] = line["allowed_amount_cents"] - line["member_liability_cents"]


def _oop_cap(plan, pricing_lines, snap):
    oop_room = max(0, plan["oop_max_individual_cents"] - snap["oop_applied_cents"])
    provisional_total = sum(line["member_liability_cents"] for line in pricing_lines)
    excess = max(0, provisional_total - oop_room)
    for line in sorted(pricing_lines, key=lambda l: l["line_number"], reverse=True):
        if excess <= 0:
            break
        give_back = min(line["member_liability_cents"], excess)
        line["member_liability_cents"] -= give_back
        line["plan_paid_cents"] += give_back
        excess -= give_back


def _totals(pricing_lines):
    return {
        "total_allowed_cents": sum(l["allowed_amount_cents"] for l in pricing_lines),
        "total_deductible_applied_cents": sum(
            l["deductible_applied_cents"] for l in pricing_lines
        ),
        "total_member_liability_cents": sum(
            l["member_liability_cents"] for l in pricing_lines
        ),
        "total_plan_paid_cents": sum(l["plan_paid_cents"] for l in pricing_lines),
    }


def _cob_offset(claim, plan, totals):
    """The last money step; only SECONDARY claims are touched."""
    if claim["cob_role"] != "SECONDARY":
        return totals
    other = claim["other_payer_paid_cents"]
    if other is None:
        return totals
    would_pay_as_primary = totals["total_plan_paid_cents"]
    if plan["cob_method"] == "COME_OUT_WHOLE":
        plan_pays = min(
            would_pay_as_primary, max(0, totals["total_allowed_cents"] - other)
        )
    else:  # NON_DUPLICATION
        plan_pays = max(0, would_pay_as_primary - other)
    totals["total_plan_paid_cents"] = plan_pays
    totals["total_member_liability_cents"] = max(
        0, totals["total_allowed_cents"] - other - plan_pays
    )
    return totals


# --------------------------------------------------------------------------
# claim-level outcome resolution
# --------------------------------------------------------------------------
def _resolve_outcome(claim, lines):
    """The six tests of PRD 3.8, evaluated strictly top to bottom."""
    # STEP 1 -- hard denials outrank every pend on the claim.
    hard = [
        line
        for line in lines
        if line.get("_rule")
        and line["_rule"]["severity"] == "DENY"
        and line["_rule"]["precedence_rank"] <= HARD_DENY_RANK_MAX
    ]
    if hard:
        winner = min(
            hard, key=lambda l: (l["_rule"]["precedence_rank"], l["line_number"])
        )
        return "DENIED", None, winner["_rule"]["reason_code"]

    # STEP 2 -- every line must be covered by some segment of the member.
    if not all(line_is_covered(claim["member_id"], l["service_date"]) for l in lines):
        return "DENIED", None, "DENY_NO_COVERAGE"

    # STEP 3 -- secondary claim with no reported other-payer amount.
    if claim["cob_role"] == "SECONDARY" and claim["other_payer_paid_cents"] is None:
        return "PENDED", "PEND_COB_OTHER_PAYER_MISSING", None

    # STEP 4 -- pended lines; deliberately ahead of STEP 5 so a soft deny
    # never masks a pend.
    pended = [line for line in lines if line["line_status"] == "PENDED"]
    if pended:
        winner = min(
            pended,
            key=lambda l: (
                l["_rule"]["precedence_rank"] if l.get("_rule") else 0,
                l["line_number"],
            ),
        )
        return "PENDED", winner["edit_reason_code"], None

    # STEP 5 -- everything knocked out.
    if all(line["line_status"] in ("DENIED", "BUNDLED") for line in lines):
        denied = [line for line in lines if line["line_status"] == "DENIED"]
        if denied:
            winner = min(denied, key=lambda l: l["line_number"])
            return "DENIED", None, winner["edit_reason_code"]
        return "DENIED", None, "DENY_BUNDLED_ALL"

    # STEP 6
    return "ADJUDICATED", None, None


# --------------------------------------------------------------------------
# the pass
# --------------------------------------------------------------------------
def run_pass(claim, actor_role, actor_user_id):
    from_status = claim["status"]
    lines = lines_of(claim)
    plan = plan_of_member(member_of(claim))
    provider = provider_of(claim)

    reset_lines(lines)
    apply_coverage_match(claim, lines)
    zero_claim_totals(claim)
    claim["pricing_variant"] = "UNPRICED"
    claim["pend_reason_code"] = None
    claim["deny_reason_code"] = None

    rates = {}
    for line in lines:
        rate = select_fee_rate(plan["id"], line["procedure_code"], line["service_date"])
        if rate is None:
            _deny_line(line, "DENY_NON_COVERED_SERVICE", None)
        else:
            rates[line["id"]] = rate

    for line in lines:
        if line["line_status"] != "PENDING":
            continue
        _apply_edits(claim, line, lines)
        if line["line_status"] == "PENDING":
            line["line_status"] = "PRICED"

    pricing_lines = [line for line in lines if line["line_status"] == "PRICED"]
    variant = _price_lines(claim, plan, provider, pricing_lines, rates)

    snap = snapshot(claim["member_id"], earliest_service_year(lines))
    _cost_share(plan, pricing_lines, snap)
    _oop_cap(plan, pricing_lines, snap)
    totals = _cob_offset(claim, plan, _totals(pricing_lines))

    status, pend_reason, deny_reason = _resolve_outcome(claim, lines)

    claim["adjudication_pass"] = claim["adjudication_pass"] + 1
    claim["last_adjudicated_by_user_id"] = actor_user_id
    claim["status"] = status
    claim["pend_reason_code"] = pend_reason
    claim["deny_reason_code"] = deny_reason
    if status == "ADJUDICATED":
        # Only a pass that adjudicates writes the claim totals and the variant.
        for field, value in totals.items():
            claim[field] = value
        claim["pricing_variant"] = variant
    db.touch(claim)
    append_event(
        claim,
        "ADJUDICATE",
        from_status,
        status,
        pend_reason or deny_reason,
        actor_role,
        actor_user_id,
    )
    return claim


# --------------------------------------------------------------------------
# medical-director override
# --------------------------------------------------------------------------
def override_approve(claim, actor_role, actor_user_id):
    from_status = claim["status"]
    lines = lines_of(claim)
    plan = plan_of_member(member_of(claim))
    provider = provider_of(claim)

    forced = [line for line in lines if line["line_status"] == "PENDED"]
    for line in forced:
        line["line_status"] = "PRICED"
        line["edit_reason_code"] = None
        line["_rule"] = None
        # The authorization selector is re-run with the REVOKED status
        # exclusion and the remaining-units test switched off.
        candidates = authorization_candidates(claim, line)
        if candidates:
            auth = candidates[0]
            line["authorization_id"] = auth["id"]
            consume(auth, line["units"])
        db.touch(line)

    pricing_lines = [line for line in lines if line["line_status"] == "PRICED"]
    rates = {}
    for line in pricing_lines:
        rate = select_fee_rate(plan["id"], line["procedure_code"], line["service_date"])
        if rate is not None:
            rates[line["id"]] = rate
    variant = _price_lines(claim, plan, provider, pricing_lines, rates)

    snap = snapshot(claim["member_id"], earliest_service_year(lines))
    _cost_share(plan, pricing_lines, snap)
    _oop_cap(plan, pricing_lines, snap)
    totals = _cob_offset(claim, plan, _totals(pricing_lines))
    for line in pricing_lines:
        db.touch(line)

    claim["status"] = "ADJUDICATED"
    claim["pend_reason_code"] = None
    claim["deny_reason_code"] = None
    for field, value in totals.items():
        claim[field] = value
    claim["pricing_variant"] = variant
    db.touch(claim)
    append_event(claim, "OVERRIDE", from_status, "ADJUDICATED", None, actor_role, actor_user_id)
    return claim


def override_deny(claim, reason_code, actor_role, actor_user_id):
    from_status = claim["status"]
    lines = lines_of(claim)
    for line in lines:
        if line["line_status"] == "PENDED":
            line["line_status"] = "DENIED"
            line["edit_reason_code"] = reason_code
            db.touch(line)
    claim["status"] = "DENIED"
    claim["deny_reason_code"] = reason_code
    claim["pend_reason_code"] = None
    claim["total_allowed_cents"] = 0
    claim["total_member_liability_cents"] = 0
    claim["total_plan_paid_cents"] = 0
    db.touch(claim)
    append_event(claim, "OVERRIDE", from_status, "DENIED", reason_code, actor_role, actor_user_id)
    return claim
