"""Domain services: derived-field recomputation and cross-entity transitions.

Implements the calculation table (scaffold Table 3 / PRD 3.x) and the shared
side-effect machinery used by the route modules.
"""
from decimal import Decimal, ROUND_HALF_UP

from core import (
    ACTIVE_BANK_DISCLOSURE_VERSION,
    AMENDMENT_HOLD_HOURS,
    ApiError,
    CARRYFORWARD_FORM_MAP,
    CORRECTION_HINTS,
    FREE_FILE_AGI_LIMIT_CENTS,
    GUARANTEE_CAP_CENTS,
    RANK_TIER,
    REFUND_TRANSFER_FEE_CENTS,
    STATE_FLAT_RATE_NUMERATOR,
    STATE_FLAT_RATE_DENOMINATOR,
    TIER_RANK,
    db,
    new_row,
    now,
    touch,
)


# ---------------------------------------------------------------------------
# Lookups
# ---------------------------------------------------------------------------
def get_account(account_id):
    acct = db.accounts.get(account_id)
    if acct is None:
        raise ApiError("ERR_ACCOUNT_NOT_FOUND", "accountId does not exist.")
    return acct


def get_return(return_id):
    ret = db.returns.get(return_id)
    if ret is None:
        raise ApiError("ERR_RETURN_NOT_FOUND", "returnId does not exist.")
    return ret


def get_form_on_return(ret, form_id):
    form = db.forms.get(form_id)
    if form is None or form["return_id"] != ret["id"]:
        raise ApiError("ERR_FORM_NOT_FOUND", "formId does not exist on the return.")
    return form


def get_prompt_on_return(ret, prompt_id):
    prompt = db.prompts.get(prompt_id)
    if prompt is None or prompt["return_id"] != ret["id"]:
        raise ApiError("ERR_PROMPT_NOT_FOUND", "upgrade prompt id does not exist on the return.")
    return prompt


def get_state_return_on_return(ret, sr_id):
    sr = db.state_returns.get(sr_id)
    if sr is None or sr["return_id"] != ret["id"]:
        raise ApiError("ERR_STATE_RETURN_NOT_FOUND", "state return id does not exist on the return.")
    return sr


def get_snapshot_on_account(acct, snapshot_id):
    snap = db.snapshots.get(snapshot_id)
    if snap is None or snap["account_id"] != acct["id"]:
        raise ApiError("ERR_SNAPSHOT_NOT_FOUND", "snapshot id does not exist for the account.")
    return snap


def get_claim(claim_id):
    claim = db.claims.get(claim_id)
    if claim is None:
        raise ApiError("ERR_CLAIM_NOT_FOUND", "claim id does not exist.")
    return claim


def forms_of(ret):
    return [f for f in db.forms.values() if f["return_id"] == ret["id"]]


def active_forms_of(ret):
    return [f for f in forms_of(ret) if f["status"] == "ACTIVE"]


def state_returns_of(ret):
    return [s for s in db.state_returns.values() if s["return_id"] == ret["id"]]


def prompts_of(ret):
    return [p for p in db.prompts.values() if p["return_id"] == ret["id"]]


def attempts_of(ret):
    return [a for a in db.filing_attempts.values() if a["return_id"] == ret["id"]]


def agreements_of(ret):
    return [a for a in db.refund_transfers.values() if a["return_id"] == ret["id"]]


def claims_of(ret):
    return [c for c in db.claims.values() if c["return_id"] == ret["id"]]


# ---------------------------------------------------------------------------
# Guards
# ---------------------------------------------------------------------------
def require_account_active(acct):
    if acct["status"] != "ACTIVE":
        raise ApiError("ERR_ACCOUNT_SUSPENDED", "Account is SUSPENDED; return-graph mutations blocked.")


def require_return_editable(ret, error_id="ERR_RETURN_NOT_EDITABLE"):
    if ret["status"] not in ("DRAFT", "AMENDED"):
        raise ApiError(error_id, "Operation requires return status DRAFT or AMENDED.")


# ---------------------------------------------------------------------------
# Calculations (scaffold Table 3)
# ---------------------------------------------------------------------------
def recompute_classification(ret, acct):
    """minimum_required_tier + free_file_eligible (minimum_tier_classification /
    free_file_eligibility). Operates on ACTIVE forms only."""
    active = active_forms_of(ret)
    if not active:
        ret["minimum_required_tier"] = "FREE"
    else:
        rank = max(TIER_RANK[db.form_specs[f["form_code"]]["minimum_tier"]] for f in active)
        ret["minimum_required_tier"] = RANK_TIER[rank]
    disqualifying = any(
        db.form_specs[f["form_code"]]["disqualifies_free_file"] for f in active
    )
    income_ok = acct["agi_cents"] <= FREE_FILE_AGI_LIMIT_CENTS
    ret["free_file_eligible"] = (not disqualifying) and income_ok


def recompute_refund(ret):
    """federal_refund_cents: exact cent sum over ACTIVE forms whose spec counts."""
    total = 0
    for f in active_forms_of(ret):
        if db.form_specs[f["form_code"]].get("counts_toward_refund"):
            total += f["amount_cents"]
    ret["federal_refund_cents"] = total


def recompute_fees(ret):
    """total_fees_due_cents: tier price + non-REMOVED state add-ons + RT fee.

    The catalog row for the current tier may be absent (the PRD seeds tiers
    via an ops endpoint and does not require the FREE row to exist); missing
    rows price at zero."""
    tier = db.tiers.get(ret["current_tier"])
    price = tier["price_cents"] if tier else 0
    state_price = tier["state_addon_price_cents"] if tier else 0
    state_count = sum(1 for s in state_returns_of(ret) if s["status"] != "REMOVED")
    total = price + state_count * state_price
    if ret["refund_transfer_selected"]:
        total += REFUND_TRANSFER_FEE_CENTS
    ret["total_fees_due_cents"] = total


def recompute_prompt_flag(ret):
    ret["upgrade_prompt_pending"] = any(p["status"] == "PENDING" for p in prompts_of(ret))


def compute_allocated_tax(acct, state_code, numerator, denominator):
    """state_allocation_tax: resident full-AGI tax, else ratio-based; only the
    final product is rounded half-up to whole cents (ratio never pre-rounded)."""
    agi = acct["agi_cents"]
    if state_code == acct["resident_state_code"]:
        product = (Decimal(agi) * STATE_FLAT_RATE_NUMERATOR) / STATE_FLAT_RATE_DENOMINATOR
        return int(product.quantize(Decimal(1), rounding=ROUND_HALF_UP))
    if numerator == 0:
        return 0
    # exact rational: agi * (num / den) * 5%
    product = (Decimal(agi) * Decimal(numerator) * STATE_FLAT_RATE_NUMERATOR) / (
        Decimal(denominator) * STATE_FLAT_RATE_DENOMINATOR
    )
    return int(product.quantize(Decimal(1), rounding=ROUND_HALF_UP))


# ---------------------------------------------------------------------------
# Upgrade prompts
# ---------------------------------------------------------------------------
def maybe_raise_prompt(ret):
    """Reconcile the PENDING prompt against the provisional minimum.

    If the minimum outranks current_tier, open a PENDING prompt (superseding
    any existing PENDING one). If the minimum has collapsed back to or below
    current_tier, a previously raised PENDING prompt is stale and moves to
    SUPERSEDED (at most one prompt per return is ever PENDING).
    """
    if TIER_RANK[ret["minimum_required_tier"]] <= TIER_RANK[ret["current_tier"]]:
        for p in prompts_of(ret):
            if p["status"] == "PENDING":
                p["status"] = "SUPERSEDED"
                touch(p)
        ret["upgrade_prompt_pending"] = False
        return None
    for p in prompts_of(ret):
        if p["status"] == "PENDING":
            p["status"] = "SUPERSEDED"
            touch(p)
    from_tier = ret["current_tier"]
    to_tier = ret["minimum_required_tier"]
    from_price = db.tiers[from_tier]["price_cents"] if from_tier in db.tiers else 0
    to_price = db.tiers[to_tier]["price_cents"] if to_tier in db.tiers else 0
    prompt = new_row(
        "prompt",
        return_id=ret["id"],
        from_tier=from_tier,
        to_tier=to_tier,
        price_delta_cents=to_price - from_price,
        acknowledged=False,
        status="PENDING",
    )
    db.prompts[prompt["id"]] = prompt
    ret["upgrade_prompt_pending"] = True
    return prompt


# ---------------------------------------------------------------------------
# Filing / authority cascades
# ---------------------------------------------------------------------------
def pending_attempt(ret):
    for a in attempts_of(ret):
        if a["outcome"] == "PENDING":
            return a
    return None


def resolve_attempt(attempt, outcome, rejection_code=None):
    """Authority callback cascade (PRD 3.7)."""
    ret = db.returns[attempt["return_id"]]
    attempt["outcome"] = outcome
    attempt["resolved_at"] = now()
    if outcome == "ACCEPTED":
        attempt["rejection_code"] = None
        attempt["correction_hint"] = None
        ret["status"] = "ACCEPTED"
        # Settle any ACTIVE refund-transfer agreement.
        for ag in agreements_of(ret):
            if ag["status"] == "ACTIVE":
                ag["status"] = "SETTLED"
                touch(ag)
    else:  # REJECTED
        attempt["rejection_code"] = rejection_code
        attempt["correction_hint"] = CORRECTION_HINTS.get(rejection_code)
        ret["status"] = "REJECTED"
        # Roll every FILED state return back to READY.
        for sr in state_returns_of(ret):
            if sr["status"] == "FILED":
                sr["status"] = "READY"
                touch(sr)
    touch(attempt)
    # Note: the system-driven authority callback updates the return's status
    # but does not advance the return's OCC version (the PRD §2.4 increment
    # list covers filer-driven mutations; the callback is a system actor).


# ---------------------------------------------------------------------------
# Carryforward import
# ---------------------------------------------------------------------------
def import_snapshot(snap, ret, acct):
    for item in snap["carryforward_items"]:
        form = new_row(
            "form",
            return_id=ret["id"],
            form_code=CARRYFORWARD_FORM_MAP[item["item_type"]],
            source="IMPORTED",
            carryforward_item_type=item["item_type"],
            amount_cents=item["remaining_amount_cents"],
            status="ACTIVE",
        )
        db.forms[form["id"]] = form
    recompute_classification(ret, acct)
    recompute_refund(ret)
    maybe_raise_prompt(ret)
    snap["import_status"] = "IMPORTED"
    touch(snap)
    touch(ret)
