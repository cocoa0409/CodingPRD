"""The fourteen calculations of PRD Section 3."""
from datetime import timedelta
from decimal import Decimal

import store
from util import UTC, add_days, floor_bps, floor_mul, rhu, rhu_float, rhu_int

POSTURE_MULTIPLIER = {"OPEN": "1.00", "HEIGHTENED": "1.25", "RESTRICTED": "1.50",
                      "FROZEN": "2.00"}
ABSOLUTE_RESERVE_FLOOR_CENTS = 250000
TRAILING_VOLUME_BPS = 150
TRAILING_WINDOW_DAYS = 90
FEE_BASE_CENTS = 25000
VARIANCE_RESTRICT_CENTS = 5000000
COMPLAINT_RESTRICT_BPS = 250
COMPLAINT_HEIGHTEN_BPS = 120
GROWTH_ABSOLUTE_CAP_CENTS = 5000000
CALENDAR_DAY_CHANNELS = {"CFPB_PORTAL": 15, "BANK_CALL_CENTER": 30, "PARTNER_APP": 30,
                         "EMAIL": 30}
BUSINESS_DAY_CHANNELS = {"STATE_AG": 10, "SOCIAL": 5}
ALERT_SLA_HOURS = {"SANCTIONS_HIT": 24, "STRUCTURING": 72, "VELOCITY": 120,
                   "ACH_RETURN_RATE": 168}
COMPLAINT_RATE_STATUSES = ("RECEIVED", "ROOT_CAUSE_ASSIGNED", "ESCALATED", "RESOLVED")
CONTRACTUAL_STATUSES = ("CONTRACTED", "LIVE", "WIND_DOWN")


# --- diligence composite ----------------------------------------------------
def effective_complaint_history_score(review, partner):
    if review["review_type"] == "RENEWAL":
        return max(0, 100 - (int(partner["complaint_rate_bps"]) // 5))
    return int(review["complaint_history_score"])


def composite_score(review, effective):
    c1 = rhu(Decimal(int(review["business_model_score"])) * Decimal("0.20"), 2)
    c2 = rhu(Decimal(int(review["funding_score"])) * Decimal("0.25"), 2)
    c3 = rhu(Decimal(int(review["compliance_capability_score"])) * Decimal("0.35"), 2)
    c4 = rhu(Decimal(int(effective)) * Decimal("0.20"), 2)
    return rhu(c1 + c2 + c3 + c4, 1)


def tier_for(score):
    score = Decimal(str(score))
    if score >= Decimal("85.0"):
        return "TIER_1"
    if score >= Decimal("70.0"):
        return "TIER_2"
    if score >= Decimal("55.0"):
        return "TIER_3"
    return "UNRATED"


def score_diligence(review, partner):
    effective = effective_complaint_history_score(review, partner)
    score = composite_score(review, effective)
    review["effective_complaint_history_score"] = int(effective)
    review["composite_score"] = float(score)
    review["tier"] = tier_for(score)


# --- complaint rate ---------------------------------------------------------
def complaint_rate_bps(partner):
    now = store.clock()
    floor_at = now - timedelta(days=TRAILING_WINDOW_DAYS)
    numerator = 0
    for complaint in store.DB["complaints"].values():
        if complaint["partner_id"] != partner["id"]:
            continue
        if complaint["status"] not in COMPLAINT_RATE_STATUSES:
            continue
        received = complaint["received_at"]
        if received > floor_at and received <= now:
            numerator += 1
    denominator = max(1, int(partner["end_user_account_count"]))
    return rhu_int(Decimal(numerator * 10000) / Decimal(denominator))


# --- deadlines --------------------------------------------------------------
def alert_sla_due_at(alert_type, triggered_at):
    return triggered_at + timedelta(hours=ALERT_SLA_HOURS[alert_type])


def complaint_response_due_at(channel, received_at):
    if channel in CALENDAR_DAY_CHANNELS:
        return add_days(received_at, CALENDAR_DAY_CHANNELS[channel])
    needed = BUSINESS_DAY_CHANNELS[channel]
    weekday = received_at.weekday()          # Mon=0 .. Sun=6
    if weekday >= 5:
        anchor = received_at.replace(hour=0, minute=0, second=0, microsecond=0)
        anchor = anchor + timedelta(days=(7 - weekday))
    else:
        anchor = received_at.replace(hour=0, minute=0, second=0, microsecond=0)
    cursor = anchor
    counted = 0
    while counted < needed:
        cursor = cursor + timedelta(days=1)
        if cursor.weekday() < 5:
            counted += 1
    return cursor.replace(hour=23, minute=59, second=59, microsecond=999000)


# --- group / concentration --------------------------------------------------
def group_root(partner):
    seen = set()
    current = partner
    while current.get("parent_partner_id"):
        if current["id"] in seen:
            break
        seen.add(current["id"])
        parent = store.get("partners", current["parent_partner_id"])
        if parent is None:
            break
        current = parent
    return current


def group_members(partner):
    root = group_root(partner)
    members = [root]
    ids = {root["id"]}
    changed = True
    while changed:
        changed = False
        for candidate in store.rows("partners"):
            if candidate["id"] in ids:
                continue
            if candidate.get("parent_partner_id") in ids:
                members.append(candidate)
                ids.add(candidate["id"])
                changed = True
    members.sort(key=lambda r: (r["created_at"], r["_seq"]))
    return members


def fbo_sum(partner_ids=None):
    total = 0
    for account in store.DB["custody_accounts"].values():
        if account["account_type"] != "FBO_END_USER":
            continue
        if account["status"] not in ("ACTIVE", "FROZEN"):
            continue
        if partner_ids is not None and account["partner_id"] not in partner_ids:
            continue
        total += int(account["balance_cents"])
    return total


def concentration_parts(partner):
    members = group_members(partner)
    member_ids = set(m["id"] for m in members)
    numerator = fbo_sum(member_ids)
    denominator = fbo_sum(None)
    return numerator, denominator, members


def concentration_ratio(numerator, denominator):
    if denominator == 0:
        return 0.00
    return rhu_float(Decimal(numerator * 100) / Decimal(denominator), 2)


# --- reserve floor ----------------------------------------------------------
def governing_agreement(partner_id):
    for agreement in store.rows("agreements"):
        if agreement["partner_id"] == partner_id and agreement["status"] in (
                "EXECUTED", "TERMINATED"):
            return agreement
    return None


def account_of(partner_id, account_type):
    for account in store.rows("custody_accounts"):
        if account["partner_id"] == partner_id and account["account_type"] == account_type:
            return account
    return None


def account_balance(partner_id, account_type):
    account = account_of(partner_id, account_type)
    if account is None or account["status"] == "CLOSED":
        return 0
    return int(account["balance_cents"])


def trailing_gross(partner_id):
    now = store.clock()
    floor_at = now - timedelta(days=TRAILING_WINDOW_DAYS)
    total = 0
    for batch in store.DB["settlement_batches"].values():
        if batch["partner_id"] != partner_id:
            continue
        if batch["reconciliation_status"] not in ("MATCHED", "VARIANCE_CLEARED"):
            continue
        if batch["window_end"] > floor_at and batch["window_end"] <= now:
            total += int(batch["gross_settlement_cents"])
    return total


def required_reserve(partner):
    """Single pass with the posture pinned to its pre-pass persisted value."""
    posture_in = partner["oversight_posture"]
    agreement = governing_agreement(partner["id"])
    if agreement is None:
        return 0, 0
    fbo = account_balance(partner["id"], "FBO_END_USER")
    floor_one = floor_bps(fbo, int(agreement["reserve_requirement_bps"]))
    floor_two = floor_bps(trailing_gross(partner["id"]), TRAILING_VOLUME_BPS)
    base = max(floor_one, floor_two, ABSOLUTE_RESERVE_FLOOR_CENTS)
    scaled = floor_mul(base, POSTURE_MULTIPLIER[posture_in])
    required = min(scaled, int(agreement["max_end_user_balance_cents"]))
    reserve = account_balance(partner["id"], "RESERVE")
    shortfall = max(0, required - reserve)
    return required, shortfall


# --- posture ladder ---------------------------------------------------------
def posture_for(partner):
    if partner["status"] not in CONTRACTUAL_STATUSES:
        return "OPEN"
    if int(partner["open_sanctions_alert_count"]) >= 1 or \
            int(partner["consecutive_shortfall_cycles"]) >= 2:
        return "FROZEN"
    if int(partner["complaint_rate_bps"]) >= COMPLAINT_RESTRICT_BPS or \
            int(partner["unreconciled_variance_cents"]) >= VARIANCE_RESTRICT_CENTS or \
            int(partner["growth_breach_count"]) >= 2:
        return "RESTRICTED"
    if int(partner["complaint_rate_bps"]) >= COMPLAINT_HEIGHTEN_BPS or \
            int(partner["growth_breach_count"]) == 1 or \
            int(partner["reserve_shortfall_cents"]) > 0:
        return "HEIGHTENED"
    return "OPEN"


# --- settlement money -------------------------------------------------------
def fee_bps_for(gross):
    if gross < 10000000:
        return 45
    if gross < 100000000:
        return 32
    return 21


def settlement_money(batch, reserve_bps):
    gross = int(batch["gross_settlement_cents"])
    bps = fee_bps_for(gross)
    fee = FEE_BASE_CENTS + floor_bps(gross, bps)
    base = (gross + int(batch["interchange_cents"]) - int(batch["returns_cents"])
            + int(batch["variance_adjustment_cents"]))
    if batch["reconciliation_status"] == "VARIANCE_CLEARED":
        reserve_funding = floor_bps(base, reserve_bps)
    else:
        reserve_funding = floor_bps(gross, reserve_bps)
    raw_net = base - fee - reserve_funding
    net = raw_net if raw_net > 0 else 0
    carry = -raw_net if raw_net < 0 else 0
    return {
        "bank_fee_bps_applied": bps,
        "bank_fee_cents": fee,
        "settlement_base_cents": base,
        "reserve_funding_cents": reserve_funding,
        "net_to_partner_cents": net,
        "shortfall_carry_cents": carry,
    }


# --- growth -----------------------------------------------------------------
def end_user_credit_sum(partner_id, period_start, period_end):
    total = 0
    for entry in store.DB["ledger_entries"].values():
        if entry["partner_id"] != partner_id or entry["entry_type"] != "END_USER_CREDIT":
            continue
        if entry["effective_at"] >= period_start and entry["effective_at"] < period_end:
            total += int(entry["amount_cents"])
    return total


def monthly_growth(partner, cycle, cap_pct):
    current = end_user_credit_sum(partner["id"], cycle["period_start"], cycle["period_end"])
    prior_cycle = None
    for candidate in store.DB["cycles"].values():
        if candidate["cycle_index"] == int(cycle["cycle_index"]) - 1 and \
                candidate["status"] == "CLOSED":
            prior_cycle = candidate
            break
    prior = 0
    if prior_cycle is not None:
        prior = end_user_credit_sum(partner["id"], prior_cycle["period_start"],
                                    prior_cycle["period_end"])
    if prior == 0:
        return 0.00, current > GROWTH_ABSOLUTE_CAP_CENTS
    pct = rhu(Decimal((current - prior) * 100) / Decimal(prior), 2)
    breach = cap_pct is not None and pct > Decimal(str(cap_pct))
    return float(pct), breach


# --- marketing risk flags ---------------------------------------------------
def marketing_risk_flags(review, partner):
    elements = review.get("disclosure_elements") or []
    flags = []
    if partner["business_model"] == "LENDING" and (
            not review.get("apr_disclosed") or "APR" not in elements):
        flags.append("MISSING_APR")
    if partner["business_model"] == "DEPOSIT_WALLET" and (
            not review.get("fdic_signage_correct")
            or "FDIC_SIGNAGE" not in elements
            or "PASS_THROUGH_INSURANCE" not in elements):
        flags.append("MISSING_FDIC_SIGNAGE")
    if review["material_type"] == "DISCLOSURE" and "DISPUTE_RIGHTS" not in elements:
        flags.append("MISSING_DISPUTE_RIGHTS")
    return flags


# --- systemic root cause ----------------------------------------------------
def systemic_root_cause_code(partner_id, cycle):
    pool = []
    for complaint in store.rows("complaints"):
        if complaint["partner_id"] != partner_id:
            continue
        if complaint["status"] not in ("ROOT_CAUSE_ASSIGNED", "ESCALATED", "RESOLVED"):
            continue
        if not complaint.get("root_cause_code"):
            continue
        if complaint["received_at"] >= cycle["period_start"] and \
                complaint["received_at"] < cycle["period_end"]:
            pool.append(complaint)
    if not pool:
        return None
    counts = {}
    earliest = {}
    for complaint in pool:
        code = complaint["root_cause_code"]
        counts[code] = counts.get(code, 0) + 1
        if code not in earliest or complaint["created_at"] < earliest[code]:
            earliest[code] = complaint["created_at"]
    top = max(counts.values())
    candidates = [code for code, count in counts.items() if count == top]
    candidates.sort(key=lambda code: (earliest[code], code))
    return candidates[0]


# --- wind-down residual -----------------------------------------------------
def residual_balance(partner_id):
    total = 0
    for account in store.DB["custody_accounts"].values():
        if account["partner_id"] == partner_id and account["status"] in ("ACTIVE", "FROZEN"):
            total += int(account["balance_cents"])
    return total
