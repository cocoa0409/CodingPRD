"""Derived-value calculations (PRD 3.2, 3.3, 3.6, 3.8, 3.9, 3.10, 3.11)."""

from decimal import Decimal

from store import db, sort_rows
from validation import round_cents, round_half_up

# ------------------------------------------------------------------ constants
DEFAULT_AVERAGE_TICKET_CENTS = 5000
NETWORK_MAX_SURCHARGE_PCT = Decimal("3.0")
CASH_DISCOUNT_MAX_PCT = Decimal("10.0")
RATE_CHANGE_BUFFER_DAYS = Decimal(30)
NOTICE_PERIOD_DAYS = 30
RESPONSE_WINDOW_DAYS = {"NETWORK": 10, "ATTORNEY_GENERAL": 20, "CARDHOLDER": 30}
SUBSTANTIATED_BASE_POINTS = Decimal(20)
OPEN_CASE_POINTS = Decimal(8)
SCORE_CEILING = Decimal(100)
REMEDIATION_EXPOSURE_THRESHOLD = Decimal(30)
SOURCE_MULTIPLIER = {
    "NETWORK": Decimal("1.5"),
    "ATTORNEY_GENERAL": Decimal("2.0"),
    "CARDHOLDER": Decimal("1.0"),
}
POSTURE_MULTIPLIER = {
    "PERMISSIVE": Decimal("0.5"),
    "MONITORED": Decimal("1.0"),
    "RESTRICTIVE": Decimal("2.0"),
}

APPROVED_OUTCOMES = ("APPROVED_WITH_SURCHARGE", "APPROVED_NO_SURCHARGE", "APPROVED_CASH_DISCOUNT")


# ------------------------------------------------------------------ selectors
def merchant_terminals(merchant_id):
    return [t for t in db.terminals.values() if t["merchant_id"] == merchant_id]


def merchant_transactions(merchant_id):
    out = []
    for tx in db.transactions.values():
        term = db.terminals.get(tx["terminal_id"])
        if term is not None and term["merchant_id"] == merchant_id:
            out.append(tx)
    return out


def program_transactions(program_id):
    return [tx for tx in db.transactions.values() if tx["program_id"] == program_id]


def program_rate_rules(program_id):
    return sort_rows([r for r in db.rate_rules.values() if r["program_id"] == program_id])


def program_registrations(program_id):
    return sort_rows([r for r in db.registrations.values() if r["program_id"] == program_id])


def program_artifacts(program_id):
    return sort_rows([a for a in db.artifacts.values() if a["program_id"] == program_id])


def program_terminals(program_id):
    return sort_rows([t for t in db.terminals.values() if t.get("program_id") == program_id])


def program_cases(program_id):
    return sort_rows([c for c in db.complaint_cases.values() if c["program_id"] == program_id])


def case_refunds(case_id):
    return sort_rows([r for r in db.refunds.values() if r["complaint_case_id"] == case_id])


def transaction_refunds(transaction_id):
    return [r for r in db.refunds.values() if r["transaction_id"] == transaction_id]


# ------------------------------------------------- average_ticket_snapshot
def average_ticket_snapshot(merchant_id):
    clock = db.now()
    rows = [tx for tx in merchant_transactions(merchant_id)
            if tx["outcome"] in APPROVED_OUTCOMES and tx["occurred_at"] <= clock]
    if not rows:
        return DEFAULT_AVERAGE_TICKET_CENTS
    total = sum(tx["base_amount_cents"] for tx in rows)
    return round_cents(Decimal(total) / Decimal(len(rows)))


# ------------------------------------------- cost_documentation_evaluation
def documented_cost_pct(base_mdr_pct, assessment_pct, per_item_fee_cents, average_ticket_cents):
    per_item_component = round_half_up(
        Decimal(per_item_fee_cents) / Decimal(average_ticket_cents) * Decimal(100), 4)
    return round_half_up(Decimal(base_mdr_pct) + Decimal(assessment_pct) + per_item_component, 4)


# ---------------------------------------------------- effective_surcharge_cap
def effective_surcharge_cap(program):
    if program["program_type"] == "CASH_DISCOUNT":
        return CASH_DISCOUNT_MAX_PCT
    candidates = [NETWORK_MAX_SURCHARGE_PCT]
    doc = db.cost_documentations.get(program.get("cost_documentation_id"))
    if doc is not None and doc.get("documented_cost_pct") is not None:
        candidates.append(Decimal(doc["documented_cost_pct"]))
    jur = db.jurisdictions.get(program.get("jurisdiction_id"))
    if jur is not None and jur.get("surcharge_cap_pct") is not None:
        candidates.append(Decimal(jur["surcharge_cap_pct"]))
    return min(candidates)


def recompute_cap(program):
    program["effective_cap_pct"] = effective_surcharge_cap(program)
    return program["effective_cap_pct"]


# ------------------------------------------------------- disclosure_readiness
def required_artifact_types(program):
    jur = db.jurisdictions.get(program["jurisdiction_id"])
    required = set()
    if jur is None:
        return required
    if program["program_type"] == "SURCHARGE":
        if jur["disclosure_signage_required"]:
            required.add("ENTRY_SIGNAGE")
            required.add("POS_SIGNAGE")
        if jur["receipt_line_item_required"]:
            required.add("RECEIPT_TEMPLATE")
    else:
        if jur["disclosure_signage_required"]:
            required.add("POS_SIGNAGE")
    return required


def satisfied_artifact_types(program):
    clock = db.now()
    satisfied = set()
    for art in program_artifacts(program["id"]):
        if art["state"] != "ATTESTED":
            continue
        eff = art.get("effective_from")
        exp = art.get("expires_at")
        if eff is None or exp is None:
            continue
        if eff <= clock < exp:
            satisfied.add(art["artifact_type"])
    return satisfied


def disclosure_readiness(program):
    return required_artifact_types(program).issubset(satisfied_artifact_types(program))


def recompute_disclosure_ready(program):
    program["disclosure_ready"] = disclosure_readiness(program)
    return program["disclosure_ready"]


def price_list_posting_in_window(program):
    return "PRICE_LIST_POSTING" in satisfied_artifact_types(program)


# ---------------------------------------------------- compliance_exposure_score
def exposure_scores(program):
    cases = program_cases(program["id"])
    network_sum = Decimal(0)
    for case in cases:
        if case["investigation_state"] == "SUBSTANTIATED":
            network_sum += SUBSTANTIATED_BASE_POINTS * SOURCE_MULTIPLIER[case["source"]]
    network_score = min(SCORE_CEILING, round_half_up(network_sum, 2))

    jur = db.jurisdictions.get(program["jurisdiction_id"])
    posture = POSTURE_MULTIPLIER.get(jur["ag_enforcement_posture"], Decimal(1)) if jur else Decimal(1)
    ag_sum = Decimal(0)
    for case in cases:
        state = case["investigation_state"]
        if state == "SUBSTANTIATED":
            ag_sum += SUBSTANTIATED_BASE_POINTS
        elif state in ("OPEN", "UNDER_REVIEW"):
            ag_sum += OPEN_CASE_POINTS
    ag_score = min(SCORE_CEILING, round_half_up(posture * ag_sum, 2))
    return network_score, ag_score


def recompute_exposure(program, network=True, ag=True):
    network_score, ag_score = exposure_scores(program)
    if network:
        program["network_exposure_score"] = network_score
    if ag:
        program["ag_exposure_score"] = ag_score
    return network_score, ag_score


# ------------------------------------------------------ merchant ledger/census
def issued_refund_total_for_merchant(merchant_id):
    total = 0
    for refund in db.refunds.values():
        if refund["state"] != "ISSUED":
            continue
        tx = db.transactions.get(refund["transaction_id"])
        if tx is None:
            continue
        term = db.terminals.get(tx["terminal_id"])
        if term is not None and term["merchant_id"] == merchant_id:
            total += refund["refund_amount_cents"]
    return total


def gross_surcharge_collected(merchant_id):
    return sum(tx["surcharge_amount_cents"] for tx in merchant_transactions(merchant_id)
               if tx["outcome"] == "APPROVED_WITH_SURCHARGE")


def enforcing_terminal_count(merchant_id):
    return sum(1 for t in merchant_terminals(merchant_id) if t["state"] == "ENFORCING")


def active_cost_documentation_id(merchant_id):
    for doc in sort_rows([d for d in db.cost_documentations.values()
                          if d["merchant_id"] == merchant_id]):
        if doc["state"] == "ACTIVE":
            return doc["id"]
    return None


def refunded_surcharge_cents(transaction_id):
    return sum(r["refund_amount_cents"] for r in transaction_refunds(transaction_id)
               if r["state"] == "ISSUED")


def case_refund_total(case_id):
    return sum(r["refund_amount_cents"] for r in case_refunds(case_id)
               if r["state"] == "ISSUED")
