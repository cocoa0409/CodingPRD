"""Calculation rules (SCAFFOLD section 1.3 / PRD sections 3.5-3.9).

All money is integer cents. Rounding: ceil for call-minute rounding, floor for
affordability division, half-up applied once to the aggregate for commissions
and the average-revenue figure.
"""

from datetime import timedelta
from decimal import Decimal, ROUND_HALF_UP

from core import DB, balance_of, ledger_of


def ceil_minutes(seconds):
    return -(-int(seconds) // 60)


def round_half_up_int(frac):
    return int(Decimal(frac).quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def commission_for(pct, basis_total):
    """Percentage applied ONCE to the aggregate basis, then rounded half-up."""
    return int((Decimal(str(pct)) * Decimal(basis_total)).quantize(
        Decimal("1"), rounding=ROUND_HALF_UP))


# ------------------------------------------------------- lookup helpers -----
def active_contract(facility_id):
    for contract in DB.contracts.values():
        if contract["facility_id"] == facility_id and contract["status"] == "ACTIVE":
            return contract
    return None


def active_schedule(contract_id):
    for schedule in DB.schedules.values():
        if schedule["contract_id"] == contract_id and schedule["status"] == "ACTIVE":
            return schedule
    return None


def cap_for_state(state_code):
    for cap in DB.caps.values():
        if cap["state_code"] == state_code:
            return cap
    return None


def cap_for_facility(facility):
    if facility is None:
        return None
    return cap_for_state(facility["state_code"])


def can_cover(account, amount_cents):
    """Funding-model rule: PREPAID/DEBIT full balance; COLLECT credit headroom."""
    bal = balance_of(account["id"])
    if account["funding_model"] == "COLLECT":
        return bal - amount_cents >= -(account["collect_credit_limit_cents"] or 0)
    return bal >= amount_cents


# ----------------------------------------------------------- refund payout --
def refund_payout(method, entries, closure_balance, closure_fee):
    """refund_payout calc: SIMPLE_BALANCE vs fee-restoring LIFO_NET variants."""
    if method == "LIFO_NET":
        charges = sum(-e["amount_cents"] for e in entries
                      if e["type"] in ("CALL_CHARGE", "MESSAGE_CHARGE", "VIDEO_CHARGE"))
        refunds = sum(e["amount_cents"] for e in entries
                      if e["type"] in ("MESSAGE_REFUND", "VIDEO_REFUND"))
        remaining = max(0, charges - refunds)
        intact_groups = set()
        deposits = [e for e in entries if e["type"] == "DEPOSIT"]
        # Attribute charges against deposit PRINCIPAL, newest first (LIFO).
        for dep in sorted(deposits, key=lambda e: e["_seq"], reverse=True):
            attributed = min(remaining, dep["amount_cents"])
            remaining -= attributed
            if attributed <= 0:
                intact_groups.add(dep.get("_group"))
        fee_refund = sum(-e["amount_cents"] for e in entries
                         if e["type"] == "DEPOSIT_FEE"
                         and e.get("_group") in intact_groups)
        return max(0, closure_balance - closure_fee + fee_refund)
    # SIMPLE_BALANCE: deposit fees are never returned.
    return max(0, closure_balance - closure_fee)


# ------------------------------------------------------------- call charge --
def end_call_charges(call, account, duration_seconds):
    """call_charge calc. Returns (status, billable_minutes, total, cutoff)."""
    if duration_seconds == 0:
        return "NOT_CONNECTED", 0, 0, call["cutoff_reason"]
    fee = call["applied_connection_fee_cents"]
    rate = call["applied_per_minute_cents"]
    requested = ceil_minutes(duration_seconds)
    balance_at_connect = call["_balance_at_connect"]
    if account["funding_model"] == "COLLECT":
        headroom = balance_at_connect + (account["collect_credit_limit_cents"] or 0)
        available = headroom - fee
        cutoff = "CREDIT_LIMIT_REACHED"
    else:
        available = balance_at_connect - fee
        cutoff = "BALANCE_EXHAUSTED"
    if rate > 0:
        affordable = max(0, available // rate)
    else:
        affordable = requested  # zero rate: no affordability truncation
    if requested > affordable:
        return "COMPLETED", affordable, fee + affordable * rate, cutoff
    return "COMPLETED", requested, fee + requested * rate, "NONE"


# --------------------------------------------------------- video capacity ---
def inmate_session_overlap(inmate_id, new_start, new_end):
    """Unbuffered half-open overlap; adjacency is allowed."""
    for session in DB.sessions.values():
        if session["inmate_id"] != inmate_id or session["status"] != "CONFIRMED":
            continue
        if session["scheduled_start"] < new_end and new_start < session["scheduled_end"]:
            return True
    return False


def capacity_exceeded(facility, new_start, new_end):
    """Buffered sweep over half-open intervals; ends sort before starts at an
    instant so back-to-back buffered sessions do not double-count."""
    buffer = timedelta(minutes=facility["video_turnover_minutes"])
    events = []
    for session in DB.sessions.values():
        if session["facility_id"] == facility["id"] and session["status"] == "CONFIRMED":
            events.append((session["scheduled_start"] - buffer, 1))
            events.append((session["scheduled_end"] + buffer, -1))
    events.append((new_start - buffer, 1))
    events.append((new_end + buffer, -1))
    events.sort(key=lambda ev: (ev[0], ev[1]))
    current = 0
    peak = 0
    for _, delta in events:
        current += delta
        peak = max(peak, current)
    return peak > facility["video_booth_count"]


def daily_confirmed_count(inmate_id, day):
    return sum(
        1 for session in DB.sessions.values()
        if session["inmate_id"] == inmate_id
        and session["status"] == "CONFIRMED"
        and session["scheduled_start"].date() == day
    )


# ------------------------------------------------------ regulatory summary --
def regulatory_summary(facility, period_start, period_end):
    """regulatory_summary_aggregation + site_commission_accrual calcs over the
    half-open window [period_start, period_end)."""

    def in_window(dt):
        return dt is not None and period_start <= dt < period_end

    completed = [c for c in DB.calls.values()
                 if c["facility_id"] == facility["id"]
                 and c["status"] == "COMPLETED" and in_window(c["ended_at"])]
    total_call_seconds = sum(c["duration_seconds"] for c in completed)
    total_billable = sum(c["billable_minutes"] for c in completed)
    total_revenue = sum(c["total_charge_cents"] for c in completed)
    total_conn = sum(c["applied_connection_fee_cents"] for c in completed
                     if c["total_charge_cents"] > 0)
    if total_billable > 0:
        avg = int((Decimal(total_revenue) / Decimal(total_billable)).quantize(
            Decimal("1"), rounding=ROUND_HALF_UP))
    else:
        avg = 0
    cap = cap_for_facility(facility)
    breaches = 0
    if cap is not None:
        breaches = sum(1 for c in completed
                       if c["applied_per_minute_cents"] > cap["max_per_minute_cents"])

    account_ids = {a["id"] for a in DB.accounts.values()
                   if a["facility_id"] == facility["id"]}
    entries = [e for aid in account_ids for e in ledger_of(aid)
               if in_window(e["created_at"])]

    def mag(*types):
        return sum(abs(e["amount_cents"]) for e in entries if e["type"] in types)

    deposit_fees = mag("DEPOSIT_FEE")
    message_net = mag("MESSAGE_CHARGE") - mag("MESSAGE_REFUND")
    video_net = mag("VIDEO_CHARGE") - mag("VIDEO_REFUND")
    # Net signed total of CLOSURE_FEE entries, sign-flipped.
    closure_net = -sum(e["amount_cents"] for e in entries
                       if e["type"] == "CLOSURE_FEE")
    escheated = mag("ESCHEAT_REMITTANCE")

    gross_billed = mag("CALL_CHARGE", "MESSAGE_CHARGE", "VIDEO_CHARGE")
    service_refunds = mag("MESSAGE_REFUND", "VIDEO_REFUND")
    contract = active_contract(facility["id"])
    if contract is None:
        basis_name = None
        accrued = 0
    else:
        basis_name = contract["commission_basis"]
        if basis_name == "GROSS":
            basis = gross_billed
        else:  # NET excludes deposit fees and service refunds
            basis = gross_billed - deposit_fees - service_refunds
        accrued = commission_for(contract["commission_pct"], basis)

    complaints = [c for c in DB.complaints.values()
                  if c["facility_id"] == facility["id"]]
    return {
        "total_call_seconds": total_call_seconds,
        "total_billable_minutes": total_billable,
        "total_call_revenue_cents": total_revenue,
        "total_connection_fees_cents": total_conn,
        "avg_revenue_per_billable_minute_cents": avg,
        "total_deposit_fees_cents": deposit_fees,
        "total_message_fees_net_cents": message_net,
        "total_video_fees_net_cents": video_net,
        "total_closure_fees_cents": closure_net,
        "total_escheated_cents": escheated,
        "commission_basis": basis_name,
        "commission_accrued_cents": accrued,
        "complaints_filed": sum(1 for c in complaints if in_window(c["created_at"])),
        "complaints_resolved": sum(1 for c in complaints if in_window(c["resolved_at"])),
        "complaints_escalated": sum(1 for c in complaints if in_window(c["escalated_at"])),
        "cap_breach_count": breaches,
    }
