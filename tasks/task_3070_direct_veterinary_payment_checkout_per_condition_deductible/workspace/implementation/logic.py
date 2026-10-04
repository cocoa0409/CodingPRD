"""System logic: lazy sweeps, premium math, adjudication, payment, cascades."""
from datetime import date, timedelta
from decimal import Decimal

import core
from core import store, fail, new_entity, touch, now_iso, midnight, round_cents, to_decimal

INJURY_WAITING_DAYS = 5
ILLNESS_WAITING_DAYS = 14
RECORDS_WINDOW_DAYS = 14
SETTLE_DELAY_DAYS = 3

PREEXISTING_RECORD_TYPES = {"EXAM", "PROCEDURE", "LAB"}
CLAIM_OPEN_STATES = {"SUBMITTED", "PREEXISTING_REVIEW", "ADJUDICATED", "REOPENED"}


def _days_in_month(year, month):
    if month == 12:
        return 31
    return (date(year, month + 1, 1) - date(year, month, 1)).days


def add_years(d, years):
    try:
        return d.replace(year=d.year + years)
    except ValueError:
        # Feb 29 -> Feb 28 in non-leap year
        return date(d.year + years, 2, 28)


def age_band(dob, ref):
    y = ref.year - dob.year
    try:
        bday = date(ref.year, dob.month, dob.day)
    except ValueError:
        bday = date(ref.year, 2, 28)
    if ref < bday:
        y -= 1
    return max(y, 0)


def compute_next_birthday(dob, ref):
    """Smallest DOB-anniversary date at-or-after ref (the next sweep point;
    the sweep fires when the current date reaches it)."""
    for add in range(0, 202):
        try:
            cand = date(dob.year + add, dob.month, dob.day)
        except ValueError:
            cand = date(dob.year + add, 2, 28)
        if cand >= ref:
            return cand
    return ref


# ---------------------------------------------------------------------------
# Lazy sweeps (evaluated on reads and on clock advance)
# ---------------------------------------------------------------------------


def sweep_policy(policy):
    if policy["lifecycle_status"] != "ACTIVE":
        return
    clk = store.clock
    if policy["enrollment_status"] == "INJURY_WAITING" and clk >= policy["_inj_end"]:
        policy["enrollment_status"] = "ILLNESS_WAITING"
        touch(policy)
    if policy["enrollment_status"] == "ILLNESS_WAITING" and clk >= policy["_ill_end"]:
        policy["enrollment_status"] = "FULLY_ACTIVE"
        touch(policy)


def sweep_claim(claim):
    if claim["status"] == "PAID" and store.clock >= claim["paid_at"] + timedelta(days=SETTLE_DELAY_DAYS):
        claim["status"] = "SETTLED"
        touch(claim)


def sweep_filing(filing):
    if filing["status"] != "FILED":
        return
    eff = filing["_eff_date"]
    if store.clock.date() >= eff:
        filing["status"] = "EFFECTIVE"
        filing["effective_at"] = now_iso()
        touch(filing)
        # Supersede any other EFFECTIVE filing for the same (territory, species)
        for other in store.filings.values():
            if (
                other is not filing
                and other["status"] == "EFFECTIVE"
                and other["territory_code"] == filing["territory_code"]
                and other["species"] == filing["species"]
            ):
                other["status"] = "SUPERSEDED"
                touch(other)


def sweep_premium_recalc():
    today = store.clock.date()
    for policy in store.policies.values():
        if policy["lifecycle_status"] == "ACTIVE" and today >= policy["_next_bday"]:
            do_premium_recalc(policy)


def run_clock_sweep():
    for policy in store.policies.values():
        sweep_policy(policy)
    for filing in store.filings.values():
        sweep_filing(filing)
    for claim in store.claims.values():
        sweep_claim(claim)
    sweep_premium_recalc()


# ---------------------------------------------------------------------------
# Filing selection + premium math
# ---------------------------------------------------------------------------


def select_filing(territory_code, species, as_of_date):
    """Newest EFFECTIVE filing with filing_effective_date <= as_of_date.
    Tie-break: latest effective_at then latest created_at."""
    best = None
    best_key = None
    for f in store.filings.values():
        if f["status"] != "EFFECTIVE":
            continue
        if f["territory_code"] != territory_code or f["species"] != species:
            continue
        if f["_eff_date"] > as_of_date:
            continue
        key = (f["_eff_date"].isoformat(), f.get("effective_at") or "", f["created_at"])
        if best is None or key > best_key:
            best, best_key = f, key
    return best


def band_multiplier(filing, band):
    mults = filing["age_band_multipliers"]
    keys = []
    for k in mults.keys():
        try:
            keys.append(int(k))
        except (TypeError, ValueError):
            continue
    le = [k for k in keys if k <= band]
    if not le:
        return Decimal("1")
    chosen = max(le)
    m = to_decimal(mults.get(str(chosen), mults.get(chosen)))
    if m is None:
        return Decimal("1")
    return m


def compute_premium(filing, dob, ref_date):
    band = age_band(dob, ref_date)
    mult = band_multiplier(filing, band)
    return round_cents(Decimal(filing["base_monthly_premium_cents"]) * mult)


def do_premium_recalc(policy):
    today = store.clock.date()
    filing = select_filing(policy["territory_code"], policy["species"], today)
    if filing is None:
        fail("ERR_RATE_NOT_FILED", 422,
             "No EFFECTIVE rate filing for this territory and species")
    policy["applied_filing_id"] = filing["id"]
    policy["current_monthly_premium_cents"] = compute_premium(filing, policy["_dob"], today)
    policy["_next_bday"] = add_years(policy["_next_bday"], 1)
    policy["next_birthday"] = policy["_next_bday"].isoformat()
    touch(policy)


# ---------------------------------------------------------------------------
# Condition / adjudication
# ---------------------------------------------------------------------------


def is_preexisting(policy, condition_code):
    cs_midnight = midnight(policy["_coverage_start"])
    for r in store.records.values():
        if r["policy_id"] != policy["id"]:
            continue
        if r["record_type"] not in PREEXISTING_RECORD_TYPES:
            continue
        if r["diagnosis_code"] != condition_code:
            continue
        if r["_recorded_dt"] < cs_midnight:
            return True
    return False


def find_condition(policy_id, condition_code):
    for c in store.conditions.values():
        if c["policy_id"] == policy_id and c["condition_code"] == condition_code:
            return c
    return None


def find_or_mint_condition(policy, condition_code):
    cond = find_condition(policy["id"], condition_code)
    if cond is None:
        cond = new_entity()
        cond.update({
            "policy_id": policy["id"],
            "condition_code": condition_code,
            "preexisting": is_preexisting(policy, condition_code),
            "deductible_target_cents": policy["per_condition_deductible_cents"],
            "deductible_accumulated_cents": 0,
            "lifetime_reimbursed_cents": 0,
        })
        store.conditions[cond["id"]] = cond
    return cond


def run_adjudication(claim, policy):
    """Line categorization + deductible waterfall. Validates the pre-existing
    safety gate and computes everything into scratch first, mutating store
    state only when the whole adjudication succeeds (atomic)."""
    rate = to_decimal(policy["reimbursement_rate"])
    lines = claim_lines_sorted(claim["id"])
    # Scratch state: existing conditions' accumulations, plus new conditions.
    new_conditions = {}  # condition_code -> draft dict
    accum_delta = {}     # condition_id -> extra deductible applied this pass
    results = []         # (line, cond_or_draft, applied, reimb)

    def accum_for(cond):
        if cond["id"] is None:
            return cond["deductible_accumulated_cents"]
        return cond["deductible_accumulated_cents"] + accum_delta.get(cond["id"], 0)

    # Pass 1: categorization + validation (no mutations)
    for line in lines:
        if line["category"] == "TREATMENT":
            cond = find_condition(policy["id"], line["condition_code"])
            if cond is None:
                cond = new_conditions.get(line["condition_code"])
            if cond is None:
                cond = {
                    "id": None,
                    "policy_id": policy["id"],
                    "condition_code": line["condition_code"],
                    "preexisting": is_preexisting(policy, line["condition_code"]),
                    "deductible_target_cents": policy["per_condition_deductible_cents"],
                    "deductible_accumulated_cents": 0,
                    "lifetime_reimbursed_cents": 0,
                }
                new_conditions[line["condition_code"]] = cond
            if cond["preexisting"]:
                fail("ERR_PREEXISTING_CONDITION", 422,
                     "A treatment line maps to a pre-existing condition")
            results.append((line, cond, None, None))
        else:
            results.append((line, None, 0, 0))

    # Pass 2: waterfall into scratch
    final = []
    for line, cond, applied, reimb in results:
        if cond is not None:
            cur = accum_for(cond)
            remaining = cond["deductible_target_cents"] - cur
            applied = min(remaining, line["amount_cents"])
            base = line["amount_cents"] - applied
            reimb = round_cents(Decimal(base) * rate)
            if cond["id"] is None:
                cond["deductible_accumulated_cents"] += applied
            else:
                accum_delta[cond["id"]] = accum_delta.get(cond["id"], 0) + applied
        final.append((line, cond, applied, reimb))

    # Commit: mint new conditions, apply accumulation deltas, write lines+totals
    total_invoice = 0
    eligible_sum = 0
    ded_sum = 0
    reimb_sum = 0
    for line, cond, applied, reimb in final:
        total_invoice += line["amount_cents"]
        if cond is not None:
            if cond["id"] is None:
                ent = new_entity()
                cond_copy = dict(cond)
                cond_copy.pop("id", None)
                ent.update(cond_copy)
                store.conditions[ent["id"]] = ent
                cond["id"] = ent["id"]  # later lines of the same condition reuse it
                cond = ent
            else:
                if cond["id"] in accum_delta:
                    cond["deductible_accumulated_cents"] += accum_delta[cond["id"]]
                    accum_delta.pop(cond["id"])
                    touch(cond)
            line["eligible_amount_cents"] = line["amount_cents"]
            line["policy_condition_id"] = cond["id"]
            line["deductible_applied_cents"] = applied
            line["reimbursement_cents"] = reimb
            line["reversed"] = False
        else:
            line["eligible_amount_cents"] = 0
            line["policy_condition_id"] = None
            line["deductible_applied_cents"] = 0
            line["reimbursement_cents"] = 0
            line["reversed"] = False
        eligible_sum += line["eligible_amount_cents"]
        ded_sum += line["deductible_applied_cents"]
        reimb_sum += line["reimbursement_cents"]
    claim["total_invoice_cents"] = total_invoice
    claim["eligible_cents"] = eligible_sum
    claim["deductible_applied_cents"] = ded_sum
    claim["reimbursement_cents"] = reimb_sum
    claim["member_responsibility_cents"] = total_invoice - reimb_sum
    claim["adjudicated_at"] = now_iso()


def claim_lines_sorted(claim_id):
    lines = [l for l in store.lines.values() if l["claim_id"] == claim_id]
    return sorted(lines, key=lambda l: l["seq"])


def recompute_conditions(policy_id, exclude_reversed=True):
    """Zero all accumulations for a policy, then replay non-reversed lines
    (ordered by claim created_at then line seq) restoring deductibles and
    lifetime reimbursements."""
    for cond in store.conditions.values():
        if cond["policy_id"] != policy_id:
            continue
        cond["deductible_accumulated_cents"] = 0
        cond["lifetime_reimbursed_cents"] = 0
        touch(cond)
    claims = sorted(
        (c for c in store.claims.values() if c["policy_id"] == policy_id),
        key=lambda c: (c["created_at"], c["_seq"]),
    )
    for claim in claims:
        for line in claim_lines_sorted(claim["id"]):
            if exclude_reversed and line.get("reversed"):
                continue
            if line["category"] != "TREATMENT" or not line.get("policy_condition_id"):
                continue
            cond = store.conditions.get(line["policy_condition_id"])
            if cond is None:
                continue
            remaining = cond["deductible_target_cents"] - cond["deductible_accumulated_cents"]
            applied = min(remaining, line["eligible_amount_cents"])
            cond["deductible_accumulated_cents"] += applied
            cond["lifetime_reimbursed_cents"] += line["reimbursement_cents"]
            touch(cond)


# ---------------------------------------------------------------------------
# Cascades
# ---------------------------------------------------------------------------


def suspend_cascade(hospital):
    for claim in store.claims.values():
        if claim["hospital_id"] != hospital["id"]:
            continue
        if claim["status"] not in CLAIM_OPEN_STATES:
            continue
        for line in claim_lines_sorted(claim["id"]):
            line["eligible_amount_cents"] = 0
            line["deductible_applied_cents"] = 0
            line["reimbursement_cents"] = 0
            line["policy_condition_id"] = None
            line["reversed"] = True
        claim["status"] = "DENIED"
        claim["denial_reason"] = "HOSPITAL_SUSPENDED"
        claim["total_invoice_cents"] = sum(l["amount_cents"] for l in claim_lines_sorted(claim["id"]))
        claim["eligible_cents"] = 0
        claim["deductible_applied_cents"] = 0
        claim["reimbursement_cents"] = 0
        claim["member_responsibility_cents"] = claim["total_invoice_cents"]
        touch(claim)
        recompute_conditions(claim["policy_id"])


def overturn_cascade(claim):
    """SETTLED/DENIED -> REOPENED with payment reversal + clawback + replay."""
    hospital = store.hospitals.get(claim["hospital_id"])
    # Reverse the claim's original DIRECT_PAY payment (the one it points at)
    pay = store.payments.get(claim.get("payment_id") or "")
    if pay is not None and pay["kind"] == "DIRECT_PAY" and pay["status"] != "REVERSED":
        pay["status"] = "REVERSED"  # ledger_status stays POSTED
        touch(pay)
        claw = new_entity()
        claw.update({
            "claim_id": claim["id"],
            "hospital_id": claim["hospital_id"],
            "amount_cents": -pay["amount_cents"],
            "kind": "CLAWBACK",
            "status": "SETTLED",
            "ledger_status": "POSTED",
            "idempotency_key": None,
            "reverses_payment_id": pay["id"],
        })
        store.payments[claw["id"]] = claw
        if hospital is not None:
            hospital["running_ledger_balance_cents"] -= pay["amount_cents"]
    # Mark this claim's lines reversed and replay conditions
    for line in claim_lines_sorted(claim["id"]):
        line["reversed"] = True
    recompute_conditions(claim["policy_id"])
    claim["status"] = "REOPENED"
    touch(claim)
    if hospital is not None:
        touch(hospital)
