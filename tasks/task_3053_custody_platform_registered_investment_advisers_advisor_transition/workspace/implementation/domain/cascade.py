"""Cascading side effects that fire after a child mutation (SCAFFOLD §1.2,
PRD §2.4, §3.1, §3.2, §3.9)."""

from core.store import STORE
from domain.calc import recompute_household_annual_fee, recompute_household_basis, recompute_posture
from domain.model import touch

MODEL_ENTITLEMENT_CODES = ("MODEL_MANAGEMENT", "ALTERNATIVE_ASSETS")


# ------------------------------------------------------------ entitlements ---

def suspend_entitlements(firm, only_codes=None):
    """GRANTED -> SUSPENDED for the firm's entitlements."""
    changed = []
    for ent in STORE.find("AdvisorFirmEntitlement", firm_id=firm.get("id")):
        if ent.get("entitlement_status") != "GRANTED":
            continue
        if only_codes and ent.get("entitlement_code") not in only_codes:
            continue
        ent["entitlement_status"] = "SUSPENDED"
        ent["effective_from"] = None
        touch(ent)
        changed.append(ent)
    if changed:
        redrive_models(firm)
    return changed


def revoke_entitlements(firm, keep_agreement_id):
    """GRANTED -> REVOKED for entitlements claiming any other agreement."""
    changed = []
    for ent in STORE.find("AdvisorFirmEntitlement", firm_id=firm.get("id")):
        if ent.get("entitlement_status") != "GRANTED":
            continue
        if ent.get("requested_custody_agreement_id") == keep_agreement_id:
            continue
        ent["entitlement_status"] = "REVOKED"
        ent["effective_from"] = None
        touch(ent)
        changed.append(ent)
    if changed:
        redrive_models(firm)
    return changed


def redrive_models(firm):
    """Second hop: suspending or revoking MODEL_MANAGEMENT / ALTERNATIVE_ASSETS
    forces every non-ARCHIVED model out of ACTIVE."""
    live = [e for e in STORE.find("AdvisorFirmEntitlement", firm_id=firm.get("id"))
            if e.get("entitlement_code") in MODEL_ENTITLEMENT_CODES
            and e.get("entitlement_status") == "GRANTED"]
    if live:
        return []
    changed = []
    for model in STORE.find("ModelPortfolio", firm_id=firm.get("id")):
        if model.get("model_status") == "ARCHIVED":
            continue
        if model.get("model_status") in ("ACTIVE", "APPROVED", "REBALANCING"):
            # PRD §3.4: every non-ARCHIVED model "is driven out of ACTIVE" when the
            # model authority is suspended or revoked.
            if model.get("model_status") == "ACTIVE":
                model["model_status"] = "REBALANCING"
            model["_model_entitlement_blocked"] = True
            touch(model)
            changed.append(model)
    return changed


# ------------------------------------------------------------------- feeds ---

def throttle_feeds(firm, reason):
    changed = []
    for feed in STORE.find("DataFeedProvision", firm_id=firm.get("id")):
        if feed.get("provision_status") != "ACTIVE":
            continue
        feed["provision_status"] = "THROTTLED"
        feed["throttle_reason_code"] = reason
        touch(feed)
        changed.append(feed)
    return changed


def activate_feeds(firm):
    changed = []
    for feed in STORE.find("DataFeedProvision", firm_id=firm.get("id")):
        if feed.get("provision_status") != "THROTTLED":
            continue
        feed["provision_status"] = "ACTIVE"
        feed["throttle_reason_code"] = None
        touch(feed)
        changed.append(feed)
    return changed


# ------------------------------------------------------------------ blocks ---

def unallocate_submitted_blocks(firm):
    changed = []
    for block in STORE.find("BlockOrder", firm_id=firm.get("id"), block_status="SUBMITTED"):
        block["block_status"] = "UNALLOCATED"
        block["unallocated_share_micros"] = int(block.get("executed_share_micros") or 0)
        touch(block)
        changed.append(block)
    return changed


# ----------------------------------------------------------------- billing ---

def reopen_settled_runs(firm):
    changed = []
    for run in STORE.find("FeeBillingRun", firm_id=firm.get("id"), billing_run_status="SETTLED"):
        run["billing_run_status"] = "REOPENED"
        touch(run)
        changed.append(run)
    return changed


# --------------------------------------------------------------- movements ---

def cancel_open_movements(firm):
    changed = []
    for mov in STORE.find("MoneyMovementInstruction"):
        account = STORE.get("HouseholdAccount", mov.get("account_id"))
        if account is None or account.get("firm_id") != firm.get("id"):
            continue
        if mov.get("movement_status") in ("DRAFT", "PENDING_AUTHORIZATION"):
            mov["movement_status"] = "CANCELLED"
            touch(mov)
            changed.append(mov)
    return changed


def reject_movements_for_account(account, states=("DRAFT", "PENDING_AUTHORIZATION")):
    changed = []
    for mov in STORE.find("MoneyMovementInstruction", account_id=account.get("id")):
        if mov.get("movement_status") in states:
            mov["movement_status"] = "REJECTED"
            touch(mov)
            changed.append(mov)
    return changed


def revoke_standing_instructions(account):
    changed = []
    for instr in STORE.find("StandingInstruction", account_id=account.get("id")):
        if instr.get("verification_status") == "VERIFIED":
            instr["verification_status"] = "REVOKED"
            touch(instr)
            changed.append(instr)
    return changed


# -------------------------------------------------------------- households ---

def redrive_households_for_billing(firm):
    """Granting BILLING: a household consenting OP_OUT that holds more than one
    billable account moves ACTIVE -> BILLING_HELD."""
    changed = []
    for household in STORE.find("Household", firm_id=firm.get("id")):
        accounts = STORE.find("HouseholdAccount", household_id=household.get("id"))
        billable = [a for a in accounts if a.get("billable")]
        consent = {a.get("householding_consent") for a in accounts}
        if consent and consent == {"OP_OUT"} and len(billable) > 1:
            if household.get("household_status") == "ACTIVE":
                household["household_status"] = "BILLING_HELD"
                touch(household)
                changed.append(household)
    return changed


def hold_household(household):
    if household is None:
        return None
    if household.get("household_status") == "ACTIVE":
        household["household_status"] = "BILLING_HELD"
        touch(household)
    return household


def release_household(household):
    if household is None:
        return None
    if household.get("household_status") == "BILLING_HELD":
        household["household_status"] = "ACTIVE"
        touch(household)
    return household


# ------------------------------------------------------------- firm posture ---

def apply_posture(firm):
    """Re-derive the firm's posture and fan out the posture-driven cascades."""
    if firm is None:
        return None
    previous = firm.get("firm_posture")
    posture = recompute_posture(firm)
    if posture == "FROZEN":
        cancel_open_movements(firm)
        reopen_settled_runs(firm)
        suspend_entitlements(firm)
        throttle_feeds(firm, firm.get("posture_reason_code"))
    elif posture == "SUSPENDED":
        suspend_entitlements(firm)
        throttle_feeds(firm, firm.get("posture_reason_code"))
    elif posture == "LIMITED":
        if previous == "OPEN":
            suspend_entitlements(firm, only_codes=MODEL_ENTITLEMENT_CODES)
        throttle_feeds(firm, firm.get("posture_reason_code"))
    elif posture == "OPEN":
        activate_feeds(firm)
    return firm


def refresh_household(household):
    """Re-derive a household's basis and annual fee in one step."""
    if household is None:
        return None
    recompute_household_basis(household)
    recompute_household_annual_fee(household)
    return household