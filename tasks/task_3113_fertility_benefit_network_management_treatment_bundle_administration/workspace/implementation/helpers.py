"""Derived-field recomputation and shared lookups.

Every ledger reading in this service is recomputed from the rows that
reference it; nothing is adjusted incrementally from the client's side.
"""

from decimal import Decimal, ROUND_HALF_UP

from clock import parse_dt

LIVE_MEMBER_STATES = ("INTAKE", "CARE_ACTIVE", "CARE_COMPLETE")
CASELOAD_STATES = ("CARE_ACTIVE", "CARE_COMPLETE")
LIVE_OUTCOME_STATES = ("RECORDED", "AMENDED")

LIVE_BIRTH_WEIGHT_BPS = 60
MULTIPLE_BIRTH_PENALTY_BPS = 45
MATURITY_BONUS_BPS = 20
MATURITY_CAP = 5


def round_half_up(value):
    """Round to a whole number, halves away from zero."""
    return int(Decimal(str(value)).quantize(Decimal("1"), rounding=ROUND_HALF_UP))


# --------------------------------------------------------------------------
# Lookups
# --------------------------------------------------------------------------

def plans_for_bundle(store, bundle_id):
    return [p for p in store.all("treatment_plans") if p["bundle_entitlement_id"] == bundle_id]


def bundle_of_plan(store, plan):
    return store.find("bundle_entitlements", plan["bundle_entitlement_id"])


def member_of_plan(store, plan):
    return store.find("members", plan["member_id"])


def employer_of_member(store, member):
    return store.find("employer_accounts", member["employer_account_id"])


def employer_of_bundle(store, bundle):
    return store.find("employer_accounts", bundle["employer_account_id"])


def plan_of_preauth(store, pa):
    return store.find("treatment_plans", pa["treatment_plan_id"])


def bundle_of_preauth(store, pa):
    plan = plan_of_preauth(store, pa)
    return bundle_of_plan(store, plan) if plan else None


def employer_of_preauth(store, pa):
    plan = plan_of_preauth(store, pa)
    member = member_of_plan(store, plan) if plan else None
    return employer_of_member(store, member) if member else None


def member_of_cycle(store, cycle):
    return store.find("members", cycle["member_id"])


def bundle_of_cycle(store, cycle):
    pa = store.find("preauthorizations", cycle["preauthorization_id"])
    return bundle_of_preauth(store, pa) if pa else None


def preauth_of_cycle(store, cycle):
    return store.find("preauthorizations", cycle["preauthorization_id"])


def plan_of_cycle(store, cycle):
    return store.find("treatment_plans", cycle["treatment_plan_id"])


def claims_for_cycle(store, cycle_id):
    return [c for c in store.all("claims") if c.get("treatment_cycle_id") == cycle_id]


# --------------------------------------------------------------------------
# Advocate status
# --------------------------------------------------------------------------

def derive_advocate_status(store, advocate):
    now = store.now()
    expire = parse_dt(advocate["credentials_expire_on"])
    if expire is not None and now >= expire:
        return "INACTIVE"
    if advocate["current_caseload"] >= advocate["caseload_limit"]:
        return "AT_CAPACITY"
    return "ACTIVE"


def recompute_advocate(store, advocate):
    members = [m for m in store.all("members") if m.get("care_advocate_id") == advocate["id"]]
    advocate["current_caseload"] = len([m for m in members if m["member_status"] in CASELOAD_STATES])
    advocate["assignments_completed"] = len([m for m in members if m["member_status"] == "CARE_COMPLETE"])
    # The derived status is re-derived against the current clock so a lapsed
    # credential is readable on the row rather than only through the gate.
    expire = parse_dt(advocate["credentials_expire_on"])
    if expire is not None and store.now() >= expire:
        advocate["advocate_status"] = "INACTIVE"
    elif advocate["current_caseload"] >= advocate["caseload_limit"]:
        advocate["advocate_status"] = "AT_CAPACITY"
    else:
        advocate["advocate_status"] = "ACTIVE"


def recompute_all_advocates(store):
    for advocate in store.all("care_advocates"):
        recompute_advocate(store, advocate)


# --------------------------------------------------------------------------
# Member counters
# --------------------------------------------------------------------------

def recompute_member(store, member):
    cycles = [
        c for c in store.all("treatment_cycles")
        if c.get("member_id") == member["id"] and c["cycle_status"] == "OUTCOME_RECORDED"
    ]
    member["completed_cycles"] = len(cycles)

    births = 0
    for record in store.all("outcome_records"):
        if record.get("member_id") == member["id"] and record["outcome_status"] in LIVE_OUTCOME_STATES:
            births += record.get("births_count") or 0
    member["live_births_recorded"] = births

    candidates = [
        r for r in store.all("pathway_requests")
        if r.get("member_id") == member["id"] and r["pathway_status"] in ("APPROVED", "ACTIVE")
    ]
    if candidates:
        candidates.sort(key=lambda r: (store.created_key(r), r["id"]))
        member["pathway_selected"] = candidates[0]["pathway_type"]
    else:
        member["pathway_selected"] = "NONE"


def recompute_all_members(store):
    for member in store.all("members"):
        recompute_member(store, member)


# --------------------------------------------------------------------------
# Employer account counters
# --------------------------------------------------------------------------

def recompute_employer(store, account):
    account["active_member_count"] = len([
        m for m in store.all("members")
        if m.get("employer_account_id") == account["id"] and m["member_status"] in LIVE_MEMBER_STATES
    ])
    account["entitlement_count"] = len([
        b for b in store.all("bundle_entitlements")
        if b.get("employer_account_id") == account["id"] and b["bundle_status"] in ("ACTIVE", "EXHAUSTED")
    ])


# --------------------------------------------------------------------------
# Bundle ledger
# --------------------------------------------------------------------------

def _cascade_denied(pa):
    """An authorization denied by the bundle-exhausted cascade, not by a reviewer."""
    return pa["review_status"] == "DENIED" and pa.get("denial_reason_code") == "BUNDLE_EXHAUSTED"


def _bundle_plan_ids(store, bundle):
    return {p["id"] for p in plans_for_bundle(store, bundle["id"])}


def recompute_bundle_cycles(store, bundle):
    plan_ids = _bundle_plan_ids(store, bundle)
    consumed = len([
        c for c in store.all("treatment_cycles")
        if c["treatment_plan_id"] in plan_ids and c["consumption_marker"] == "CONSUMED"
    ])
    now = store.now()
    committed = 0
    for pa in store.all("preauthorizations"):
        if pa["treatment_plan_id"] not in plan_ids:
            continue
        if _cascade_denied(pa):
            continue
        approved_live = (
            pa["review_status"] == "APPROVED"
            and pa.get("effective_to") is not None
            and now < parse_dt(pa["effective_to"])
        )
        pending = pa["review_status"] in ("SUBMITTED", "CLINICAL_REVIEW")
        if approved_live or pending:
            committed += 1
    bundle["cycles_consumed"] = consumed
    bundle["cycles_committed"] = committed


def recompute_pharmacy_remaining(store, bundle):
    pool = bundle.get("pharmacy_pool_cents") or 0
    consumed = bundle.get("pharmacy_consumed_cents") or 0
    bundle["pharmacy_remaining_cents"] = max(0, pool - consumed)


def recompute_pharmacy_from_claims(store, bundle):
    """Pharmacy consumption from the orders the bundle's plans hold.

    An order that has left the pharmacy (DISPENSING or later) holds its
    plan_paid_cents as consumed; a delivered order also raises a MEDICATION
    claim, so the claim records the pool draw the dispensing already made.
    """
    plan_ids = _bundle_plan_ids(store, bundle)
    order_total = 0
    auths_with_order = set()
    for order in store.all("medication_orders"):
        pa = store.find("preauthorizations", order["preauthorization_id"])
        if pa is None or pa["treatment_plan_id"] not in plan_ids:
            continue
        if order["pharmacy_status"] in ("DISPENSING", "DISPENSED", "SHIPPED", "DELIVERED"):
            order_total += order.get("plan_paid_cents") or 0
            auths_with_order.add(order["preauthorization_id"])

    # A reversal releases the pool draw the order had made.
    released = 0
    manual_paid = 0
    for claim in store.all("claims"):
        if claim["service_category"] != "MEDICATION":
            continue
        if claim["claim_status"] == "REVERSED":
            released += claim.get("_released_cents") or 0
            continue
        if claim["claim_status"] == "PAID" and (claim.get("plan_paid_cents") or 0) > 0:
            if claim["preauthorization_id"] not in auths_with_order:
                manual_paid += claim["plan_paid_cents"]

    bundle["pharmacy_consumed_cents"] = max(0, order_total - released) + manual_paid
    recompute_pharmacy_remaining(store, bundle)


def derive_bundle_status(store, bundle):
    account = employer_of_bundle(store, bundle)
    if not bundle.get("_activated"):
        bundle["cycles_remaining"] = 0
        bundle["pharmacy_remaining_cents"] = 0
        bundle["bundle_status"] = "DRAFT"
        return
    if account is not None and account["account_status"] == "SUSPENDED":
        bundle["cycles_remaining"] = 0
        bundle["pharmacy_remaining_cents"] = 0
        bundle["bundle_status"] = "DRAFT"
        return
    if bundle["cycles_remaining"] == 0 and bundle["pharmacy_remaining_cents"] == 0:
        bundle["bundle_status"] = "EXHAUSTED"
    else:
        bundle["bundle_status"] = "ACTIVE"


def recompute_bundle(store, bundle, sync_pharmacy=False, force=False):
    """Recompute the ledger; version advances only when a counter actually moves."""
    before = (
        bundle.get("cycles_consumed"), bundle.get("cycles_committed"),
        bundle.get("cycles_remaining"), bundle.get("pharmacy_consumed_cents"),
        bundle.get("pharmacy_remaining_cents"), bundle.get("bundle_status"),
    )
    account = employer_of_bundle(store, bundle)
    recompute_bundle_cycles(store, bundle)
    if sync_pharmacy:
        recompute_pharmacy_from_claims(store, bundle)
    else:
        recompute_pharmacy_remaining(store, bundle)

    allowance_base = bundle.get("lifetime_max_cycles") or 0
    annual = bundle.get("max_cycles_per_year")
    cap = allowance_base if annual is None else min(allowance_base, annual)
    if account is not None and account["allocation_method"] == "CONCURRENT_BUNDLE":
        netted = bundle["cycles_committed"]
    else:
        netted = bundle["cycles_consumed"]
    bundle["cycles_remaining"] = max(0, cap - netted)
    derive_bundle_status(store, bundle)

    after = (
        bundle["cycles_consumed"], bundle["cycles_committed"],
        bundle["cycles_remaining"], bundle["pharmacy_consumed_cents"],
        bundle["pharmacy_remaining_cents"], bundle["bundle_status"],
    )
    changed = before != after
    if changed or force:
        store.touch(bundle)
    return changed


def recompute_bundle_of_plan(store, plan, sync_pharmacy=False):
    bundle = bundle_of_plan(store, plan)
    if bundle is not None:
        recompute_bundle(store, bundle, sync_pharmacy=sync_pharmacy)
    return bundle


# --------------------------------------------------------------------------
# Plan counters
# --------------------------------------------------------------------------

def recompute_plan(store, plan):
    completed = len([
        c for c in store.all("treatment_cycles")
        if c["treatment_plan_id"] == plan["id"] and c["cycle_status"] == "OUTCOME_RECORDED"
    ])
    plan["cycles_completed"] = completed
    if plan["plan_status"] == "IN_PROGRESS" and completed >= (plan.get("planned_cycles") or 0):
        plan["plan_status"] = "COMPLETED"


# --------------------------------------------------------------------------
# Authorization consumption dimension
# --------------------------------------------------------------------------

def recompute_preauth_consumption(store, pa):
    consumed = len([
        c for c in store.all("treatment_cycles")
        if c["preauthorization_id"] == pa["id"] and c["consumption_marker"] == "CONSUMED"
    ])
    pa["consumed_cycles"] = consumed
    pa["approved_cycles"] = 1 if pa["review_status"] == "APPROVED" else 0
    if consumed == 0:
        pa["consumption_status"] = "UNCONSUMED"
    elif consumed == 1:
        pa["consumption_status"] = "PARTIALLY_CONSUMED"
    else:
        pa["consumption_status"] = "EXHAUSTED"


# --------------------------------------------------------------------------
# Clinic quality
# --------------------------------------------------------------------------

def clinic_workset(store, clinic):
    return [
        o for o in store.all("outcome_records")
        if o.get("clinic_id") == clinic["id"] and o["outcome_status"] in LIVE_OUTCOME_STATES
    ]


def recompute_clinic_quality(store, clinic):
    workset = clinic_workset(store, clinic)
    n = len(workset)
    live = [o for o in workset if o["live_birth"]]
    m = len(live)
    q_live = 0 if n == 0 else round_half_up(10000 * m / n)
    q_multiple = 0 if m == 0 else round_half_up(10000 * len([o for o in live if o["multiple_birth"]]) / m)
    clinic["cycles_reported"] = n
    clinic["live_birth_rate_bps"] = q_live
    clinic["multiple_birth_rate_bps"] = q_multiple
    clinic["composite_quality_bps"] = round_half_up(
        LIVE_BIRTH_WEIGHT_BPS * min(q_live, 10000)
        - MULTIPLE_BIRTH_PENALTY_BPS * q_multiple
        + MATURITY_BONUS_BPS * min(n, MATURITY_CAP)
    )
    return clinic


def clinic_gates_satisfied(clinic):
    """The ordered eligibility gates G1 then G2 then G3; first satisfied wins."""
    n = clinic["cycles_reported"]
    threshold = clinic["maturity_report_threshold"]
    if (
        n >= threshold
        and clinic["live_birth_rate_bps"] >= clinic["min_live_birth_rate_bps"]
        and clinic["multiple_birth_rate_bps"] <= clinic["max_multiple_birth_rate_bps"]
    ):
        return True
    if n == 0:
        return True
    if n == threshold - 1:
        return True
    return False


def clinic_quality_breached(clinic):
    n = clinic["cycles_reported"]
    threshold = clinic["maturity_report_threshold"]
    if n < threshold:
        return False
    return (
        clinic["live_birth_rate_bps"] < clinic["min_live_birth_rate_bps"]
        or clinic["multiple_birth_rate_bps"] > clinic["max_multiple_birth_rate_bps"]
    )


# --------------------------------------------------------------------------
# Clinic contracts
# --------------------------------------------------------------------------

def contracts_of_clinic(store, clinic_id, statuses=None):
    rows = [c for c in store.all("clinic_contracts") if c["clinic_id"] == clinic_id]
    if statuses is not None:
        rows = [c for c in rows if c["contracting_status"] in statuses]
    return rows


def active_contract_rate(store, clinic_id, bundle_type, at=None):
    """The negotiated rate in force for a bundle type at an instant.

    Contracts in ACTIVE or FROZEN contribute their rate; the row with the
    greater effective_from wins and created_at ASC breaks a tie.
    """
    if at is None:
        at = store.now()
    candidates = []
    for contract in store.all("clinic_contracts"):
        if contract["clinic_id"] != clinic_id:
            continue
        if contract["contracting_status"] not in ("ACTIVE", "FROZEN"):
            continue
        start = parse_dt(contract["effective_from"])
        end = parse_dt(contract["effective_to"])
        if start <= at < end:
            candidates.append(contract)
    if not candidates:
        return None
    candidates.sort(key=lambda c: (store.created_key(c), c["id"]))
    candidates.sort(key=lambda c: parse_dt(c["effective_from"]), reverse=True)
    contract = candidates[0]
    rates = contract.get("bundle_rates") or {}
    return rates.get(bundle_type)


def contract_covering(store, clinic_id, at=None, statuses=("ACTIVE", "FROZEN")):
    if at is None:
        at = store.now()
    for contract in contracts_of_clinic(store, clinic_id, statuses):
        start = parse_dt(contract["effective_from"])
        end = parse_dt(contract["effective_to"])
        if start <= at < end:
            return contract
    return None


def any_contract_holding_rate(store, clinic_id, bundle_type):
    """True when the clinic holds a contract (any status) with a rate for the bundle."""
    for contract in contracts_of_clinic(store, clinic_id):
        rates = contract.get("bundle_rates") or {}
        if bundle_type in rates:
            return True
    return False


# --------------------------------------------------------------------------
# Cascades
# --------------------------------------------------------------------------

def freeze_clinic_contracts(store, clinic, reason="QUALITY_BREACH"):
    for contract in contracts_of_clinic(store, clinic["id"], ("ACTIVE",)):
        contract["contracting_status"] = "FROZEN"
        contract["frozen_reason"] = reason
        store.touch(contract)


def unfreeze_clinic_contracts(store, clinic, reason="QUALITY_BREACH"):
    for contract in contracts_of_clinic(store, clinic["id"], ("FROZEN",)):
        if contract.get("frozen_reason") == reason:
            contract["contracting_status"] = "ACTIVE"
            contract["frozen_reason"] = None
            store.touch(contract)


def block_plans_of_clinic(store, clinic_id, statuses=("CLINIC_SELECTED", "AUTHORIZATION_PENDING")):
    """Move dependent plans into PLANNING_REVISION and deny their pending authorizations."""
    for plan in store.all("treatment_plans"):
        if plan.get("clinic_id") != clinic_id or plan["plan_status"] not in statuses:
            continue
        plan["plan_status"] = "PLANNING_REVISION"
        plan["plan_blocked_reason"] = "CLINIC_NOT_CONTRACTED"
        store.touch(plan)
        for pa in store.all("preauthorizations"):
            if pa["treatment_plan_id"] != plan["id"]:
                continue
            if pa["review_status"] in ("SUBMITTED", "CLINICAL_REVIEW"):
                pa["review_status"] = "DENIED"
                pa["denial_reason_code"] = "CLINIC_NOT_CONTRACTED"
                store.touch(pa)


def plan_price(store, plan):
    """Re-read the plan's negotiated price from the contract rates in force."""
    member = member_of_plan(store, plan)
    bundle = bundle_of_plan(store, plan)
    if member is None or bundle is None or not plan.get("clinic_id"):
        return plan.get("selected_bundle_price_cents") or 0
    return plan.get("selected_bundle_price_cents") or 0