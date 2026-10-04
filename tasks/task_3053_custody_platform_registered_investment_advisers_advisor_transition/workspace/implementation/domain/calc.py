"""Business calculations C1-C12 from SCAFFOLD §1.3 and PRD §3.

All money is an integer number of cents.  Rounding is round-half-up, applied
only where the rule is specified to round; intermediate steps that are floored
are floored explicitly (PRD §2.7).
"""

from decimal import Decimal, ROUND_HALF_UP

from core import constants as C
from core.store import STORE

TEN_BILLION = Decimal(C.MICROS_TO_CENTS_DIVISOR)


def rhu_cents(numerator, denominator=1):
    """Round-half-up to whole cents."""
    value = Decimal(numerator) / Decimal(denominator)
    return int(value.quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def floor_div(numerator, denominator):
    if denominator == 0:
        return 0
    return numerator // denominator


# ---------------------------------------------------------------- positions --

def account_positions(account):
    """TransferLot rows that have been applied to this account."""
    out = []
    for lot in STORE.all("TransferLot"):
        if lot.get("lot_status") != "APPLIED":
            continue
        transfer = STORE.get("AssetTransfer", lot.get("transfer_id"))
        if transfer is None:
            continue
        if transfer.get("receiving_account_id") != account.get("id"):
            continue
        out.append(lot)
    return out


def position_market_value_cents(lot):
    return rhu_cents(int(lot.get("quantity_micros") or 0) * int(lot.get("valuation_price_micros") or 0),
                     C.MICROS_TO_CENTS_DIVISOR)


def position_cost_basis_cents(lot):
    appraisal = lot.get("basis_appraisal_cents")
    if appraisal is not None:
        return int(appraisal)
    sent = lot.get("sent_cost_basis_cents")
    return int(sent) if sent is not None else 0


def accepted_alternative_rows(account):
    rows = STORE.find("AlternativeAssetHolding", account_id=account.get("id"))
    return [r for r in rows
            if r.get("asset_acceptance_status") == "ACCEPTED" and not r.get("stale_valuation")]


# ---------------------------------------------------------------------- C1 --

def account_is_included(account, firm):
    if account.get("account_status") not in ("OPEN", "FROZEN"):
        return False
    if not account.get("billable"):
        return False
    if firm is None or firm.get("firm_posture") not in ("OPEN", "LIMITED"):
        return False
    return True


def compute_account_basis(account, firm):
    """C1 per-account: traditional basis + accepted alternative sleeve."""
    positions = account_positions(account)
    traditional = 0
    for lot in positions:
        market = position_market_value_cents(lot)
        cost = position_cost_basis_cents(lot)
        traditional += max(market, cost)
    alt = sum(int(r.get("accepted_value_cents") or 0) for r in accepted_alternative_rows(account))
    return traditional + alt


def compute_account_market_value(account):
    return sum(position_market_value_cents(lot) for lot in account_positions(account))


def recompute_firm_basis_total(firm):
    if firm is None:
        return 0
    total = sum(int(h.get("household_fee_basis_cents") or 0)
                for h in STORE.find("Household", firm_id=firm.get("id")))
    firm["household_fee_basis_total_cents"] = total
    return total


def recompute_household_basis(household, stamp=True):
    """C1: rebuild the household fee basis from its included accounts."""
    if household is None:
        return 0
    firm = STORE.get("AdvisorFirm", household.get("firm_id"))
    total = 0
    for account in STORE.find("HouseholdAccount", household_id=household.get("id")):
        if account_is_included(account, firm):
            account["account_fee_basis_cents"] = compute_account_basis(account, firm)
        else:
            account["account_fee_basis_cents"] = 0
        total += int(account.get("account_fee_basis_cents") or 0)
    household["household_fee_basis_cents"] = total
    from domain.model import touch
    touch(household, stamp=stamp)
    recompute_firm_basis_total(firm)
    return total


def recompute_account(account, stamp=True):
    """Recompute the account's market value, then the owning household."""
    from domain.model import touch
    account["market_value_cents"] = compute_account_market_value(account)
    touch(account, stamp=stamp)
    household = STORE.get("Household", account.get("household_id"))
    if household is not None:
        recompute_household_basis(household, stamp=stamp)
        recompute_household_annual_fee(household, stamp=stamp)
    return account


# ---------------------------------------------------------------------- C2 --

def _tier_amount(basis, lower, upper):
    if upper is None:
        return basis - lower
    return min(basis, upper) - lower


def attributable_annual_cents(basis):
    total = 0
    for lower, upper, rate in C.ATTRIBUTABLE_TIERS:
        amount = _tier_amount(basis, lower, upper)
        if amount > 0:
            total += floor_div(amount * rate, 10000)
    return total


def platform_rate_bps(basis):
    for lower, upper, rate in C.PLATFORM_TIERS:
        if basis >= lower and (upper is None or basis <= upper):
            return rate
    return C.PLATFORM_TIERS[-1][2]


def platform_fee_enabled():
    config = STORE.find_one("SystemConfig", config_key=C.CONFIG_KEY)
    if config is None:
        return True
    enabled = config.get("platform_fee_enabled")
    return True if enabled is None else bool(enabled)


def annual_fee_for_basis(basis):
    total = attributable_annual_cents(basis)
    if platform_fee_enabled():
        total += floor_div(basis * platform_rate_bps(basis), 10000)
    return total


def household_fee_variant(household):
    """PRD §3.6: OP_OUT on every account selects the per-account ladder."""
    accounts = STORE.find("HouseholdAccount", household_id=household.get("id"))
    accounts = [a for a in accounts if a.get("account_status") not in ("PENDING", "CLOSED")]
    if not accounts:
        accounts = STORE.find("HouseholdAccount", household_id=household.get("id"))
    if not accounts:
        return "HOUSEHOLD_AGGREGATED", 0
    if all(a.get("householding_consent") == "OP_OUT" for a in accounts):
        firm = STORE.get("AdvisorFirm", household.get("firm_id"))
        total = 0
        for account in accounts:
            basis = compute_account_basis(account, firm)
            total += annual_fee_for_basis(basis)
        return "PER_ACCOUNT", total
    return "HOUSEHOLD_AGGREGATED", annual_fee_for_basis(int(household.get("household_fee_basis_cents") or 0))


def recompute_household_annual_fee(household, stamp=True):
    from domain.model import touch
    variant, annual = household_fee_variant(household)
    household["household_annual_fee_cents"] = annual
    if stamp:
        touch(household)
    return annual


def prorate_gross_fee(annual_cents, period_days):
    return rhu_cents(annual_cents * period_days, C.DAYS_PER_YEAR)


def select_credits(household, gross_fee_cents):
    """Pinned credit selector: (earned_on_date ASC, created_at ASC).  The credit
    identifier is never consulted as a tie-break."""
    rows = [r for r in STORE.find("FeeCredit", household_id=household.get("id"))
            if r.get("credit_status") in ("AVAILABLE", "PARTIALLY_APPLIED")]
    rows.sort(key=lambda r: (r.get("earned_on_date") or "", r.get("created_at") or ""))
    applied = 0
    consumption = []
    for credit in rows:
        headroom = gross_fee_cents - applied
        if headroom <= 0:
            break
        available = int(credit.get("credit_cents") or 0)
        if available <= 0:
            continue
        take = min(available, headroom)
        applied += take
        consumption.append((credit, take, available))
    return applied, consumption


def apply_credit_consumption(consumption, run):
    from domain.model import touch
    for credit, take, available in consumption:
        if take >= available:
            credit["credit_status"] = "APPLIED"
        else:
            credit["credit_status"] = "PARTIALLY_APPLIED"
            credit["credit_cents"] = available - take
        credit["applied_to_billing_run_id"] = run.get("id")
        touch(credit)


def release_credits_for_run(run):
    from domain.model import touch
    released = []
    for credit in STORE.find("FeeCredit", applied_to_billing_run_id=run.get("id")):
        credit["credit_status"] = "AVAILABLE"
        credit["applied_to_billing_run_id"] = None
        touch(credit)
        released.append(credit)
    return released


# ---------------------------------------------------------------------- C3 --

def allocate_block(block, allocations, executed, price):
    """C3 pinned production order.  Returns the list of filled allocations."""
    eligible = [a for a in allocations
                if (STORE.get("HouseholdAccount", a.get("account_id")) or {}).get("account_status") == "OPEN"]
    total_requested = sum(int(a.get("requested_share_micros") or 0) for a in eligible)
    filled = []
    if total_requested <= 0 or executed <= 0:
        return filled, 0
    bases = {}
    remainders = {}
    for alloc in eligible:
        requested = int(alloc.get("requested_share_micros") or 0)
        exact_num = requested * executed
        base = exact_num // total_requested
        bases[alloc["id"]] = base
        remainders[alloc["id"]] = exact_num - base * total_requested
    residual = executed - sum(bases.values())
    ordered = sorted(eligible, key=lambda a: (-remainders[a["id"]], int(a.get("allocation_rank") or 0)))
    winners = []
    for index in range(max(0, residual)):
        # PRD §3.4: the residual is handed out one micro-share at a time, so a
        # micro-share never lands on the same allocation twice.
        winners.append(ordered[index % len(ordered)]["id"])
    assigned = 0
    for alloc in eligible:
        share = bases[alloc["id"]] + winners.count(alloc["id"])
        alloc["share_micros"] = share
        alloc["allocated_cost_cents"] = rhu_cents(share * price, C.MICROS_TO_CENTS_DIVISOR)
        alloc["average_price_micros"] = (rhu_cents(alloc["allocated_cost_cents"] * C.MICROS_TO_CENTS_DIVISOR, share)
                                         if share else 0)
        alloc["allocation_status"] = "ALLOCATED"
        filled.append(alloc)
        assigned += share
    return filled, executed - assigned


def block_notional_cents(executed, price):
    return rhu_cents(executed * price, C.MICROS_TO_CENTS_DIVISOR)


def distribute_over_allocation(block):
    """C4 compensating invariant: drift is credited back one cent at a time."""
    allocations = STORE.find("BlockAllocation", block_order_id=block.get("id"))
    notional = block_notional_cents(int(block.get("executed_share_micros") or 0),
                                    int(block.get("execution_price_micros") or 0))
    allocated_total = sum(int(a.get("allocated_cost_cents") or 0) for a in allocations)
    drift = allocated_total - notional
    if drift <= 0:
        return 0
    ordered = sorted(allocations,
                     key=lambda a: (-int(a.get("allocated_cost_cents") or 0), int(a.get("allocation_rank") or 0)))
    for index in range(drift):
        if not ordered:
            break
        alloc = ordered[index % len(ordered)]
        alloc["fee_rebate_cents"] = int(alloc.get("fee_rebate_cents") or 0) + 1
        alloc["allocation_status"] = "REBATED"
        share = int(alloc.get("share_micros") or 0)
        if share:
            alloc["average_price_micros"] = rhu_cents(
                (int(alloc.get("allocated_cost_cents") or 0) - int(alloc["fee_rebate_cents"]))
                * C.MICROS_TO_CENTS_DIVISOR, share)
    return drift


def reset_block_rebates(block):
    for alloc in STORE.find("BlockAllocation", block_order_id=block.get("id")):
        alloc["fee_rebate_cents"] = 0
        if alloc.get("allocation_status") == "REBATED":
            alloc["allocation_status"] = "ALLOCATED"


# ---------------------------------------------------------------------- C5 --

def valuation_haircut(stated_value_cents, floor_cents, age_days):
    """C5.  Returns (accepted_value_cents, haircut_bps).  Stale valuations are
    refused by the caller before this runs."""
    bps = C.HAIRCUT_BPS_AGED if age_days <= C.AGE_THRESHOLD_DAYS else C.HAIRCUT_BPS_YOUNG
    base = rhu_cents(int(stated_value_cents) * (10000 - bps), 10000)
    accepted = min(max(base, int(floor_cents)), int(stated_value_cents))
    return accepted, bps


# ---------------------------------------------------------------------- C6 --

def grade_lots(transfer, lots, submission_instant):
    """C6 chronological grading.  Returns (grades, carryover_cents)."""
    ordered = sorted(lots, key=lambda l: (l.get("lot_inventory_date") or "", l.get("symbol") or ""))
    suspected = suspected_double_basis(transfer)
    grades = {}
    carryover = 0
    for lot in ordered:
        sent = lot.get("sent_cost_basis_cents")
        if sent is None:
            grade = "NONE"
        elif suspected:
            grade = "LOW"
        elif submission_instant and (lot.get("lot_inventory_date") or "") < submission_instant:
            grade = "HIGH"
        else:
            grade = "MEDIUM"
        grades[lot["id"]] = grade
        if transfer.get("method") == "DIRECT_ROLLOVER":
            if sent is not None:
                carryover += int(sent)
        elif grade == "HIGH":
            carryover += int(sent)
    return grades, carryover


def suspected_double_basis(transfer):
    if transfer.get("method") != "ACAT":
        return False
    symbols = {l.get("symbol") for l in STORE.find("TransferLot", transfer_id=transfer.get("id"))}
    if not symbols:
        return False
    for other in STORE.all("AssetTransfer"):
        if other.get("id") == transfer.get("id"):
            continue
        if other.get("receiving_account_id") != transfer.get("receiving_account_id"):
            continue
        if other.get("transfer_status") != "CREDITED":
            continue
        if other.get("_seq", 0) >= transfer.get("_seq", 0):
            continue
        other_symbols = {l.get("symbol") for l in STORE.find("TransferLot", transfer_id=other.get("id"))}
        if symbols & other_symbols:
            return True
    return False


# ---------------------------------------------------------------------- C7 --

def money_movement_decision(movement, instruction, account):
    """C7 pinned sequential order — the first rule that fires wins."""
    note = movement.get("authorization_note")
    if note is None or str(note).strip() == "":
        return "ERR_AUTHORIZATION_NOTE_REQUIRED", None
    amount = int(movement.get("amount_cents") or 0)
    headroom = int(instruction.get("periodic_limit_cents") or 0) - int(instruction.get("consumed_period_cents") or 0)
    if amount > headroom:
        return "ERR_STANDING_LIMIT_EXCEEDED", None
    if instruction.get("verification_status") != "VERIFIED":
        return "ERR_STANDING_INSTRUCTION_NOT_VERIFIED", None
    if int(instruction.get("round_trip_days") or 0) >= C.STANDING_ROUND_TRIP_CEILING_DAYS:
        return "ERR_STANDING_INSTRUCTION_EXPIRED", None
    if (account or {}).get("account_type") in C.JURISDICTION_WITHHOLDING_TYPES:
        withheld = min(floor_div(amount * C.WITHHOLDING_RATE_BPS, 10000), amount)
        return None, (True, withheld)
    return None, (False, 0)


def dominant_rule_probe(movement, instruction, account):
    """C7 DOMINANT_RULE: the largest withdrawal any single restriction demands."""
    amount = int(movement.get("amount_cents") or 0)
    demands = {"jurisdiction": 0, "entitlement": 0, "limit": 0}
    if (account or {}).get("account_type") in C.JURISDICTION_WITHHOLDING_TYPES:
        demands["jurisdiction"] = min(floor_div(amount * C.WITHHOLDING_RATE_BPS, 10000), amount)
    consumed = int((instruction or {}).get("consumed_period_cents") or 0)
    limit = int((instruction or {}).get("periodic_limit_cents") or 0)
    if amount > limit - consumed:
        demands["limit"] = amount
    return demands


# ---------------------------------------------------------------------- C9 --

def listing_snapshot(account):
    """C9: the traditional sleeve, rounded half up at the position level."""
    traditional = sum(position_market_value_cents(lot) for lot in account_positions(account))
    alt = sum(int(r.get("accepted_value_cents") or 0) for r in accepted_alternative_rows(account))
    return traditional, traditional + alt


# --------------------------------------------------------------------- C10 --

POSTURE_LIMITS = ("OPEN", "LIMITED")


def derive_posture(firm):
    """C10 pinned first-match derivation.  `supervision_evidence_status` is the
    complementary rollup."""
    if firm is None:
        return "OPEN", None
    firm_id = firm.get("id")
    admin_actions = STORE.find("AdminActionLog", firm_id=firm_id)
    agreements = STORE.find("CustodyAgreement", firm_id=firm_id)
    entitlements = STORE.find("AdvisorFirmEntitlement", firm_id=firm_id)
    evidence = STORE.find("CustodyRulesEvidence", firm_id=firm_id)

    critical_rows = [e for e in evidence if e.get("critical")]
    if not critical_rows:
        rollup = "UNKNOWN"
    elif any(e.get("requirement_status") == "DEFICIENT" for e in critical_rows):
        rollup = "DEFICIENT"
    elif all(e.get("requirement_status") in ("ACCEPTED", "WAIVED") for e in critical_rows):
        rollup = "CLEAR"
    else:
        rollup = "UNKNOWN"
    firm["supervision_evidence_status"] = rollup

    if any(a.get("admin_action_kind") == "REGULATORY_FREEZE" and a.get("admin_action_status") == "ACTIVE"
           for a in admin_actions):
        return "FROZEN", "REGULATORY_FREEZE"
    if not any(a.get("agreement_status") == "EXECUTED" for a in agreements):
        return "SUSPENDED", "CUSTODY_AGREEMENT_NOT_EXECUTED"
    if any(e.get("requirement_status") == "DEFICIENT" and e.get("critical") for e in evidence):
        return "LIMITED", "CUSTODY_EVIDENCE_DEFICIENT"
    if any(e.get("entitlement_status") == "REVOKED" for e in entitlements):
        return "LIMITED", "ENTITLEMENT_REVOKED"
    if any(a.get("admin_action_status") == "UNACKNOWLEDGED" for a in admin_actions):
        return "LIMITED", "ADMIN_ACTION_UNACKNOWLEDGED"
    if any(a.get("agreement_status") == "TERMINATED" for a in agreements):
        return "SUSPENDED", "CUSTODY_AGREEMENT_TERMINATED"
    return "OPEN", None


def recompute_posture(firm, stamp=True):
    from domain.model import touch
    posture, reason = derive_posture(firm)
    firm["firm_posture"] = posture
    firm["posture_reason_code"] = reason
    firm["entitlement_count"] = sum(
        1 for e in STORE.find("AdvisorFirmEntitlement", firm_id=firm.get("id"))
        if e.get("entitlement_status") == "GRANTED")
    if stamp:
        touch(firm)
    return posture


# --------------------------------------------------------------------- C11 --

def reconciliation_totals(firm):
    basis_1 = int(firm.get("household_fee_basis_total_cents") or 0)
    basis_2 = sum(int(h.get("household_fee_basis_cents") or 0)
                  for h in STORE.find("Household", firm_id=firm.get("id")))
    basis_3 = 0
    for account in STORE.find("HouseholdAccount", firm_id=firm.get("id")):
        if account_is_included(account, firm):
            basis_3 += int(account.get("account_fee_basis_cents") or 0)
    return basis_1, basis_2, basis_3


# --------------------------------------------------------------------- C12 --

def examination_missing_codes(firm, period_start, period_end):
    evidence = STORE.find("CustodyRulesEvidence", firm_id=firm.get("id"))
    missing = []
    for code in C.EXAMINATION_REQUIRED_CODES:
        found = False
        for row in evidence:
            if row.get("requirement_code") != code:
                continue
            if row.get("requirement_status") not in ("ACCEPTED", "WAIVED"):
                continue
            submitted = row.get("submitted_at")
            if submitted is None:
                continue
            if period_start <= submitted < period_end:
                found = True
                break
        if not found:
            missing.append(code)
    return sorted(missing)