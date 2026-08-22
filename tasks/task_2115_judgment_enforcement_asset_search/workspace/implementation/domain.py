"""Domain constants, calculations, cascades and the docket sweep."""

from datetime import date, timedelta

from errors import ApiError
from store import store, touch, bump, by_seq

# --- constants (scaffold section 1.3 / PRD sections 2.6 and 3) --------------
INTEREST_DAY_BASIS = 365
RENEWAL_FEE_CENTS = 5000
SHERIFF_FEE_CENTS = 12500
RENEWAL_TERM_YEARS = 10
JUDGMENT_TERM_YEARS = 10
RENEWAL_WINDOW_DAYS = 180
MAX_RENEWALS = 2

TARGET_ASSET_VALUE_CENTS = 5000000

FED_MIN_WAGE_CENTS = 725
GARNISH_FLOOR_MULTIPLIER = 30
DEFAULT_GARNISH_CAP_BPS = 2500
HOH_FL_GARNISH_CAP_BPS = 1000

BANK_AUTO_EXEMPT_CENTS = 175000
LEVY_TERM_DAYS = 120

TIER_1_MAX_CENTS = 1000000
TIER_2_MAX_CENTS = 5000000
TIER_1_BPS = 4000
TIER_2_BPS = 3300
TIER_3_BPS = 2500

MIN_SETTLEMENT_PCT_BPS = 6000
INSTALLMENT_FIRST_DUE_DAYS = 30
MAX_NEGOTIATION_ROUNDS = 4
MAX_MISSES = 3
MAX_REINSTATEMENTS = 1

EXEMPTION_RESPONSE_DAYS = 20
OPPOSITION_RESPONSE_DAYS = 10
EXAM_COOLING_DAYS = 120
EXAM_COOLING_HOURS = EXAM_COOLING_DAYS * 24
SUBPOENA_LEAD_DAYS = 10
MAX_CONTINUANCES = 2
EXAM_SERVICE_LOOKBACK_DAYS = 30

ACTIVE_ENFORCEMENT_STATES = ("WRIT_REQUESTED", "SERVED", "SUSPENDED")
LIVE_FILING_STATES = ("DRAFT", "SUBMITTED", "RECORDED")


# --- date helpers -----------------------------------------------------------
def to_date(value):
    if value is None:
        return None
    if isinstance(value, date):
        return value
    return date.fromisoformat(value)


def add_years(d, years):
    """Same month and day n years later; 02-29 maps to 02-28."""
    try:
        return d.replace(year=d.year + years)
    except ValueError:
        return d.replace(year=d.year + years, month=2, day=28)


def add_days(d, days):
    return d + timedelta(days=days)


def round_half_up(numerator, denominator):
    """Exact ROUND_HALF_UP on a non-negative integer ratio."""
    if numerator < 0:
        q, r = divmod(-numerator, denominator)
        return -(q + 1) if 2 * r >= denominator else -q
    q, r = divmod(numerator, denominator)
    if 2 * r >= denominator:
        q += 1
    return q


# --- lookups ----------------------------------------------------------------
def _get(collection, oid, error_id):
    row = collection.get(oid) if isinstance(oid, str) else None
    if row is None:
        raise ApiError(error_id)
    return row


def get_creditor(oid):
    return _get(store.creditors, oid, "ERR_CREDITOR_NOT_FOUND")


def get_debtor(oid):
    return _get(store.debtors, oid, "ERR_DEBTOR_NOT_FOUND")


def get_judgment(oid):
    return _get(store.judgments, oid, "ERR_JUDGMENT_NOT_FOUND")


def get_filing(oid):
    return _get(store.county_filings, oid, "ERR_COUNTY_FILING_NOT_FOUND")


def get_finding(oid):
    return _get(store.asset_findings, oid, "ERR_ASSET_FINDING_NOT_FOUND")


def get_action(oid):
    return _get(store.enforcement_actions, oid, "ERR_ENFORCEMENT_ACTION_NOT_FOUND")


def get_claim(oid):
    return _get(store.exemption_claims, oid, "ERR_EXEMPTION_CLAIM_NOT_FOUND")


def get_exam(oid):
    return _get(store.debtor_examinations, oid, "ERR_EXAMINATION_NOT_FOUND")


def get_offer(oid):
    return _get(store.settlement_offers, oid, "ERR_SETTLEMENT_OFFER_NOT_FOUND")


def get_agreement(oid):
    return _get(store.installment_agreements, oid, "ERR_INSTALLMENT_AGREEMENT_NOT_FOUND")


def get_payment(oid):
    return _get(store.payments, oid, "ERR_PAYMENT_NOT_FOUND")


def judgment_of(row):
    return store.judgments.get(row.get("judgment_id"))


def judgment_of_action(action):
    return store.judgments.get(action.get("judgment_id"))


def judgment_of_claim(claim):
    action = store.enforcement_actions.get(claim.get("enforcement_action_id"))
    return store.judgments.get(action["judgment_id"]) if action else None


def debtor_of_judgment(j):
    return store.debtors.get(j.get("debtor_id"))


def children(collection, field, value):
    return by_seq([r for r in collection.values() if r.get(field) == value])


# --- lifecycle guards -------------------------------------------------------
def guard_judgment_alive(j):
    """Rungs 15 and 16 of the screening order."""
    if j["status"] == "EXPIRED":
        raise ApiError("ERR_JUDGMENT_EXPIRED")
    if j["status"] == "SATISFIED":
        raise ApiError("ERR_JUDGMENT_SATISFIED")


def guard_not_stayed(j):
    """Rung 19 - guards drafting, writ request and service only."""
    if j["enforcement_posture"] == "STAYED":
        raise ApiError("ERR_ENFORCEMENT_STAYED")


def invalid_state(message="The resource is not in a state that permits this transition."):
    raise ApiError("ERR_INVALID_STATE", message)


# --- derived counters -------------------------------------------------------
def recount_judgment(j):
    jid = j["id"]
    j["active_enforcement_count"] = len(
        [a for a in store.enforcement_actions.values()
         if a["judgment_id"] == jid and a["status"] in ACTIVE_ENFORCEMENT_STATES]
    )
    j["open_offer_count"] = len(
        [o for o in store.settlement_offers.values()
         if o["judgment_id"] == jid and o["status"] == "OPEN"]
    )
    j["perfected_county_count"] = len(
        [f for f in store.county_filings.values()
         if f["judgment_id"] == jid and f["status"] == "RECORDED"]
    )


def recount_creditor(creditor):
    cid = creditor["id"]
    creditor["active_judgment_count"] = len(
        [j for j in store.judgments.values()
         if j["creditor_id"] == cid and j["status"] == "ACTIVE"]
    )


# --- calculation: chronological payoff replay (PRD 3.8) ---------------------
def replay(j, ref_date, order):
    principal = j["original_principal_cents"]
    costs = j["filing_costs_cents"] + j["_recorded_fees"] + j["_sheriff_fees"]
    interest = 0
    cursor = to_date(j["entered_on"])
    rate = j["interest_rate_bps"]
    denominator = 10000 * INTEREST_DAY_BASIS

    events = []
    for p in store.payments.values():
        if p["judgment_id"] == j["id"] and p["status"] == "APPLIED":
            events.append((to_date(p["received_on"]), 0, p["_seq"], p))
    for idx, ds in enumerate(j["renewal_dates"]):
        events.append((to_date(ds), 1, idx, None))
    events = [e for e in events if e[0] <= ref_date]
    events.sort(key=lambda e: (e[0], e[1], e[2]))

    segments = 0
    splits = {}
    for event_date, kind, _tie, row in events:
        days = (event_date - cursor).days
        if days > 0:
            interest += round_half_up(principal * rate * days, denominator)
            cursor = event_date
            segments += 1
        if kind == 0:
            remaining = row["amount_cents"]
            balances = {"costs": costs, "interest": interest, "principal": principal}
            allocation = {"costs": 0, "interest": 0, "principal": 0}
            buckets = ("costs", "interest", "principal") if order == "STATUTORY_ORDER" \
                else ("principal", "interest", "costs")
            for bucket in buckets:
                take = min(remaining, balances[bucket])
                if take > 0:
                    balances[bucket] -= take
                    remaining -= take
                    allocation[bucket] += take
            costs = balances["costs"]
            interest = balances["interest"]
            principal = balances["principal"]
            splits[row["id"]] = allocation
        else:
            principal += interest
            interest = 0
            costs += RENEWAL_FEE_CENTS

    days = (ref_date - cursor).days
    if days > 0:
        interest += round_half_up(principal * rate * days, denominator)
        segments += 1

    return {
        "principal": principal,
        "interest": interest,
        "costs": costs,
        "total": principal + interest + costs,
        "segments": segments,
        "splits": splits,
    }


def collected_total(j):
    return sum(p["amount_cents"] for p in store.payments.values()
               if p["judgment_id"] == j["id"] and p["status"] == "APPLIED")


def payoff_now(j, order=None):
    """Live total_payoff_cents as of the current logical-clock date."""
    return replay(j, store.clock_date(), order or j["application_order"])["total"]


def recompute_balances(j, order=None):
    """Persisting recompute: replays from entered_on to the current clock date."""
    ref = store.clock_date()
    result = replay(j, ref, order or j["application_order"])
    j["collected_to_date_cents"] = collected_total(j)
    j["principal_balance_cents"] = result["principal"]
    j["accrued_interest_cents"] = result["interest"]
    j["costs_balance_cents"] = result["costs"]
    j["total_payoff_cents"] = result["total"]
    j["accrued_through_on"] = ref.isoformat()
    j["gross_exposure_cents"] = result["total"] + j["collected_to_date_cents"]
    for payment_id, allocation in result["splits"].items():
        payment = store.payments.get(payment_id)
        if payment is not None:
            payment["applied_to_costs_cents"] = allocation["costs"]
            payment["applied_to_interest_cents"] = allocation["interest"]
            payment["applied_to_principal_cents"] = allocation["principal"]
    return result


def refresh_totals(j):
    """Recompute total_payoff/gross_exposure from the stored balance fields."""
    j["total_payoff_cents"] = (
        j["principal_balance_cents"] + j["accrued_interest_cents"] + j["costs_balance_cents"]
    )
    j["gross_exposure_cents"] = j["total_payoff_cents"] + j["collected_to_date_cents"]


# --- calculation: contingency accounting (PRD 3.8) --------------------------
def recompute_collections(j):
    applied = [p for p in store.payments.values()
               if p["judgment_id"] == j["id"] and p["status"] == "APPLIED"]
    applied.sort(key=lambda p: (to_date(p["received_on"]), p["_seq"]))
    gross = sum(p["amount_cents"] for p in applied)
    if gross < TIER_1_MAX_CENTS:
        tier_bps = TIER_1_BPS
    elif gross < TIER_2_MAX_CENTS:
        tier_bps = TIER_2_BPS
    else:
        tier_bps = TIER_3_BPS
    fee_total = 0
    for p in applied:
        slice_cents = round_half_up(p["amount_cents"] * tier_bps, 10000)
        p["contingency_fee_cents"] = slice_cents
        fee_total += slice_cents
    j["collected_to_date_cents"] = gross
    j["contingency_fee_cents"] = fee_total
    j["net_to_creditor_cents"] = gross - fee_total - j["filing_costs_cents"]


# --- calculation: recoverability score (PRD 3.3) ----------------------------
def findings_for_debtor(debtor_id):
    judgment_ids = set(j["id"] for j in store.judgments.values() if j["debtor_id"] == debtor_id)
    return [f for f in store.asset_findings.values() if f["judgment_id"] in judgment_ids]


def _asset_component(weighted_x100):
    # 60 * weighted / TARGET, floored, capped at 60.  weighted is carried x100.
    component = (60 * weighted_x100) // (100 * TARGET_ASSET_VALUE_CENTS)
    return min(60, component)


def preliminary_score(debtor):
    weighted_x100 = 0
    for f in findings_for_debtor(debtor["id"]):
        if f["status"] == "VERIFIED":
            weighted_x100 += f["estimated_value_cents"] * 100
        elif f["status"] == "OPEN":
            weighted_x100 += f["estimated_value_cents"] * 60
    asset = _asset_component(weighted_x100)
    locate = 20 if debtor["locate_status"] == "LOCATED" else 0
    cooperation = 20 - 10 * min(2, debtor["no_show_count"])
    return max(0, min(100, asset + locate + cooperation))


def certified_score(debtor):
    weighted_x100 = 0
    for f in findings_for_debtor(debtor["id"]):
        if f["status"] == "VERIFIED":
            weighted_x100 += f["estimated_value_cents"] * 100
    asset = _asset_component(weighted_x100)
    locate = 20 if debtor["locate_status"] == "LOCATED" else 0
    cooperation = 20 - 20 * min(1, debtor["no_show_count"])
    return max(0, min(100, asset + locate + cooperation))


def refresh_preliminary(debtor):
    if debtor is None:
        return
    debtor["recoverability_score"] = preliminary_score(debtor)


# --- calculation: wage garnishment / bank levy ------------------------------
def wage_garnishment_withholding(action):
    j = judgment_of_action(action)
    d = debtor_of_judgment(j)
    disposable = d["weekly_disposable_earnings_cents"]
    cap_bps = HOH_FL_GARNISH_CAP_BPS if (d["head_of_household"] and d["state_code"] == "FL") \
        else DEFAULT_GARNISH_CAP_BPS
    cap_a = (disposable * cap_bps) // 10000
    cap_b = max(0, disposable - FED_MIN_WAGE_CENTS * GARNISH_FLOOR_MULTIPLIER)
    cap_c = payoff_now(j)
    return min(cap_a, cap_b, cap_c)


def bank_levy_hold(action):
    j = judgment_of_action(action)
    finding = store.asset_findings.get(action["asset_finding_id"])
    remaining = payoff_now(j)
    return max(0, min(finding["available_cents"] - BANK_AUTO_EXEMPT_CENTS, remaining))


# --- calculation: lien priority (PRD 3.2) -----------------------------------
def renumber_priority(filing):
    cohort = [f for f in store.county_filings.values()
              if f["county_code"] == filing["county_code"]
              and f["state_code"] == filing["state_code"]
              and f["status"] == "RECORDED"]
    cohort.sort(key=lambda f: (to_date(f["recorded_on"]), f["_seq"]))
    for position, member in enumerate(cohort, start=1):
        if member["priority_rank"] != position:
            member["priority_rank"] = position
            if member["id"] != filing["id"]:
                bump(member)


# --- custody / enforcement cascades -----------------------------------------
def return_levy_hold(action):
    """Move a served writ's hold back from frozen_cents to available_cents."""
    hold = action.get("levy_hold_cents") or 0
    if hold:
        finding = store.asset_findings.get(action["asset_finding_id"])
        if finding is not None:
            finding["frozen_cents"] -= hold
            finding["available_cents"] += hold
            bump(finding)
    action["levy_hold_cents"] = 0


def step_back_posture(j):
    """ENFORCING -> LIEN_PERFECTED once the last live writ has gone."""
    recount_judgment(j)
    if (j["enforcement_posture"] == "ENFORCING"
            and j["active_enforcement_count"] == 0
            and j["perfected_county_count"] >= 1):
        j["enforcement_posture"] = "LIEN_PERFECTED"
        bump(j)
    else:
        touch(j)


def suspend_served_actions(j):
    for action in children(store.enforcement_actions, "judgment_id", j["id"]):
        if action["status"] == "SERVED":
            action["status"] = "SUSPENDED"
            bump(action)


def resume_suspended_actions(j):
    for action in children(store.enforcement_actions, "judgment_id", j["id"]):
        if action["status"] == "SUSPENDED":
            action["status"] = "SERVED"
            bump(action)


def quash_action(action, claim):
    """Shared cascade for a SUSTAINED ruling and for an unopposed DEFAULTED claim."""
    if action["status"] not in ("SERVED", "SUSPENDED"):
        return
    return_levy_hold(action)
    action["weekly_withholding_cents"] = 0
    action["status"] = "QUASHED"
    bump(action)
    finding = store.asset_findings.get(action["asset_finding_id"])
    if claim["claim_type"] in ("HEAD_OF_HOUSEHOLD", "HOMESTEAD") and finding is not None:
        if finding["status"] == "VERIFIED":
            finding["status"] = "EXHAUSTED"
            bump(finding)
    j = judgment_of_action(action)
    debtor = debtor_of_judgment(j)
    if debtor is not None:
        refresh_preliminary(debtor)
        touch(debtor)
    step_back_posture(j)


# --- judgment terminal cascades (PRD 3.9) -----------------------------------
def satisfy_judgment(j):
    j["status"] = "SATISFIED"
    j["enforcement_posture"] = "NONE"
    for filing in children(store.county_filings, "judgment_id", j["id"]):
        if filing["status"] == "RECORDED":
            filing["status"] = "RELEASED"
            bump(filing)
    for action in children(store.enforcement_actions, "judgment_id", j["id"]):
        if action["status"] in ACTIVE_ENFORCEMENT_STATES:
            return_levy_hold(action)
            action["status"] = "RELEASED"
            bump(action)
    for agreement in children(store.installment_agreements, "judgment_id", j["id"]):
        if agreement["status"] == "ACTIVE":
            agreement["status"] = "COMPLETED"
            bump(agreement)
    recount_judgment(j)
    creditor = store.creditors.get(j["creditor_id"])
    if creditor is not None:
        recount_creditor(creditor)
        bump(creditor)
    bump(j)


def expire_judgment(j):
    """Sweep step 1.  Returns the number of installment agreements terminated."""
    j["status"] = "EXPIRED"
    j["enforcement_posture"] = "NONE"
    for filing in children(store.county_filings, "judgment_id", j["id"]):
        if filing["status"] == "RECORDED":
            filing["status"] = "LAPSED"
            bump(filing)
    for action in children(store.enforcement_actions, "judgment_id", j["id"]):
        if action["status"] in ACTIVE_ENFORCEMENT_STATES:
            return_levy_hold(action)
            action["status"] = "RELEASED"
            bump(action)
    terminated = 0
    for agreement in children(store.installment_agreements, "judgment_id", j["id"]):
        if agreement["status"] == "ACTIVE":
            agreement["status"] = "TERMINATED"
            bump(agreement)
            terminated += 1
    recount_judgment(j)
    creditor = store.creditors.get(j["creditor_id"])
    if creditor is not None:
        recount_creditor(creditor)
        bump(creditor)
    bump(j)
    return terminated


# --- the docket sweep (PRD 2.5) ---------------------------------------------
def run_sweep(new_clock):
    new_date = new_clock.date()
    counts = {
        "expired_judgment_count": 0,
        "defaulted_claim_count": 0,
        "expired_offer_count": 0,
        "expired_subpoena_count": 0,
        "terminated_agreement_count": 0,
    }

    # step 1 - expiry
    for j in by_seq(list(store.judgments.values())):
        if j["status"] == "ACTIVE" and to_date(j["expires_on"]) <= new_date:
            counts["terminated_agreement_count"] += expire_judgment(j)
            counts["expired_judgment_count"] += 1

    # step 2 - unopposed exemption claims
    for claim in by_seq(list(store.exemption_claims.values())):
        if claim["status"] == "FILED" and to_date(claim["opposition_deadline_on"]) < new_date:
            claim["status"] = "DEFAULTED"
            bump(claim)
            action = store.enforcement_actions.get(claim["enforcement_action_id"])
            if action is not None:
                quash_action(action, claim)
            counts["defaulted_claim_count"] += 1

    # step 3 - stale offers
    for offer in by_seq(list(store.settlement_offers.values())):
        if offer["status"] == "OPEN" and to_date_instant(offer["_expires_at"]) <= new_clock:
            offer["status"] = "EXPIRED"
            offer["decided_at"] = instant_string(new_clock)
            bump(offer)
            j = store.judgments.get(offer["judgment_id"])
            if j is not None:
                recount_judgment(j)
                touch(j)
            counts["expired_offer_count"] += 1

    # step 4 - lapsed subpoenas
    for exam in by_seq(list(store.debtor_examinations.values())):
        if (exam["subpoena_status"] == "ISSUED"
                and exam["status"] == "SCHEDULED"
                and to_date(exam["subpoena_service_deadline_on"]) < new_date):
            exam["subpoena_status"] = "EXPIRED"
            bump(exam)
            counts["expired_subpoena_count"] += 1

    return counts


def to_date_instant(dt):
    return dt


def instant_string(dt):
    from store import fmt_instant
    return fmt_instant(dt)


def clock_instant_string():
    return instant_string(store.clock)
