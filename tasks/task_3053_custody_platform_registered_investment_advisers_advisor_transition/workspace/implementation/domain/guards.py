"""Shared guard sequences, applied in the scaffold's pinned category order
(SCAFFOLD §1.4 / PRD §2.1: auth -> existence -> state -> business safety ->
business constraint -> temporal -> referential -> fiscal)."""

from core import constants as C
from core.errors import fail
from core.store import STORE


def firm_active_guard(firm):
    """Priority 14: FROZEN blocks every write except the two exempt endpoints."""
    if firm is not None and firm.get("firm_posture") == "FROZEN":
        fail("ERR_FIRM_FROZEN")


def trading_guard(firm):
    """Priority 17: trading-path actions require a posture of exactly OPEN."""
    if firm is not None and firm.get("firm_posture") != "OPEN":
        fail("ERR_FIRM_NOT_OPEN_FOR_TRADING")


def current_agreement(firm):
    """The firm's current EXECUTED agreement, or None."""
    if firm is None:
        return None
    executed = [a for a in STORE.find("CustodyAgreement", firm_id=firm.get("id"))
                if a.get("agreement_status") == "EXECUTED"]
    if executed:
        return executed[0]
    return None


def require_executed_agreement(firm):
    agreement = current_agreement(firm)
    if agreement is None:
        fail("ERR_CUSTODY_AGREEMENT_REQUIRED")
    return agreement


def granted_entitlements(firm):
    if firm is None:
        return []
    return [e for e in STORE.find("AdvisorFirmEntitlement", firm_id=firm.get("id"))
            if e.get("entitlement_status") == "GRANTED"]


def require_any_entitlement(firm, codes):
    """Priority 15: ERR_ENTITLEMENT_NOT_GRANTED when none of the codes is live."""
    granted = {e.get("entitlement_code") for e in granted_entitlements(firm)}
    if not (granted & set(codes)):
        fail("ERR_ENTITLEMENT_NOT_GRANTED")


def require_all_entitlements(firm, codes):
    granted = {e.get("entitlement_code") for e in granted_entitlements(firm)}
    for code in codes:
        if code not in granted:
            fail("ERR_ENTITLEMENT_NOT_GRANTED")


def require_model_management(firm):
    """Model writes: a suspension or revocation surfaces as the model-specific
    error rather than the generic entitlement error."""
    for ent in STORE.find("AdvisorFirmEntitlement", firm_id=firm.get("id")):
        if ent.get("entitlement_code") == "MODEL_MANAGEMENT" and ent.get("entitlement_status") == "GRANTED":
            return
    for model in STORE.find("ModelPortfolio", firm_id=firm.get("id")):
        if model.get("_model_entitlement_blocked"):
            fail("ERR_MODEL_MANAGEMENT_ENTITLEMENT_REQUIRED")
    fail("ERR_ENTITLEMENT_NOT_GRANTED")


def invariant_guard(firm):
    """Priority 26: under ENFORCED enforcement a BROKEN firm-scoped invariant
    rejects the guarded writes."""
    if firm is None:
        return
    config = STORE.find_one("SystemConfig", config_key=C.CONFIG_KEY)
    if config is None or config.get("database_invariant_enforcement") != "ENFORCED":
        return
    for inv in STORE.find("DatabaseInvariant", firm_id=firm.get("id")):
        if inv.get("invariant_status") == "BROKEN":
            fail("ERR_INVARIANT_CHAIN_BROKEN")


def enforcement_enforced():
    config = STORE.find_one("SystemConfig", config_key=C.CONFIG_KEY)
    return config is not None and config.get("database_invariant_enforcement") == "ENFORCED"


def no_outstanding_admin_action(firm):
    """Priority 22: an UNACKNOWLEDGED action blocks the two-party operations."""
    if firm is None:
        return
    for row in STORE.find("AdminActionLog", firm_id=firm.get("id")):
        if row.get("admin_action_status") == "UNACKNOWLEDGED":
            fail("ERR_ADMIN_ACTION_OUTSTANDING")


def sod_guard(identity, recorded_user_id):
    """Priority 18: the acting user must differ from the recorded drafter."""
    if recorded_user_id is not None and identity.user_id == recorded_user_id:
        fail("ERR_SOD_VIOLATION")