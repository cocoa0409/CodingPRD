"""Existence, ownership and list-ordering helpers (SCAFFOLD §1.4 priorities 3-5,
PRD §2.3 and §2.9)."""

from core.context import state_of
from core.errors import fail
from core.store import STORE
from domain.model import serialize


def firm_or_404(firm_id):
    firm = STORE.get("AdvisorFirm", firm_id)
    if firm is None:
        fail("ERR_FIRM_NOT_FOUND")
    return firm


def row_or_404(entity, row_id):
    row = STORE.get(entity, row_id)
    if row is None:
        fail("ERR_RESOURCE_NOT_FOUND")
    return row


def child_of(entity, row_id, parent_field, parent_id):
    """Resolve a nested child, reporting ownership ahead of a missing row."""
    row = STORE.get(entity, row_id)
    if row is None:
        fail("ERR_RESOURCE_NOT_FOUND")
    if parent_id is not None and row.get(parent_field) != parent_id:
        fail("ERR_PARENT_CHILD_MISMATCH")
    return row


def firm_of_entity(entity, row):
    """Walk a row's firm_id, following the parent chain where denormalized."""
    firm_id = row.get("firm_id")
    if firm_id:
        return firm_id
    kind = entity
    for _ in range(4):
        if kind == "Household":
            return row.get("firm_id")
        parent = PARENT_LINKS.get(kind)
        if parent is None:
            break
        parent_entity, field = parent
        parent_row = STORE.get(parent_entity, row.get(field))
        if parent_row is None:
            return None
        if parent_row.get("firm_id"):
            return parent_row.get("firm_id")
        row, kind = parent_row, parent_entity
    return None


PARENT_LINKS = {
    "CustodyAgreement": ("AdvisorFirm", "firm_id"),
    "AdvisorFirmEntitlement": ("AdvisorFirm", "firm_id"),
    "Household": ("AdvisorFirm", "firm_id"),
    "HouseholdAccount": ("Household", "household_id"),
    "AssetTransfer": ("HouseholdAccount", "receiving_account_id"),
    "TransferLot": ("AssetTransfer", "transfer_id"),
    "ModelPortfolio": ("AdvisorFirm", "firm_id"),
    "ModelTarget": ("ModelPortfolio", "model_id"),
    "BlockOrder": ("AdvisorFirm", "firm_id"),
    "BlockAllocation": ("BlockOrder", "block_order_id"),
    "FeeBillingRun": ("AdvisorFirm", "firm_id"),
    "FeeCredit": ("Household", "household_id"),
    "AlternativeAssetHolding": ("HouseholdAccount", "account_id"),
    "MoneyMovementInstruction": ("HouseholdAccount", "account_id"),
    "StandingInstruction": ("HouseholdAccount", "account_id"),
    "CustodyRulesEvidence": ("AdvisorFirm", "firm_id"),
    "DataFeedProvision": ("AdvisorFirm", "firm_id"),
    "OnboardingBatch": ("AdvisorFirm", "firm_id"),
    "AdminActionLog": ("AdvisorFirm", "firm_id"),
    "DatabaseInvariant": ("AdvisorFirm", "firm_id"),
    "ExaminationBundle": ("AdvisorFirm", "firm_id"),
}


def require_same_firm(firm_id, entity, row):
    """Priority 45: a body FK pointing at another firm's row."""
    owner = firm_of_entity(entity, row)
    if owner is not None and firm_id is not None and owner != firm_id:
        fail("ERR_REFERENCE_MISMATCH")
    return row


def household_of_account(account):
    return STORE.get("Household", account.get("household_id"))


def firm_of_account(account):
    return STORE.get("AdvisorFirm", account.get("firm_id"))


def client_guard(identity, account_id):
    """PRD §2.1: a Client may only touch rows whose account belongs to the
    household named by X-User-ID; anything else resolves to not-found."""
    if not identity.is_client:
        return
    account = STORE.get("HouseholdAccount", account_id)
    if account is None or account.get("household_id") != identity.user_id:
        fail("ERR_RESOURCE_NOT_FOUND")


def account_context(identity, entity, row):
    """Apply the Client ownership guard to any account-scoped row."""
    if not identity.is_client:
        return row
    account_id = row.get("account_id")
    if account_id is None and entity == "HouseholdAccount":
        account_id = row.get("id")
    if account_id is None:
        fail("ERR_RESOURCE_NOT_FOUND")
    client_guard(identity, account_id)
    return row


def sorted_rows(entity, filters=None, query=None):
    """List rows ordered by created_at ascending (oldest first), filterable."""
    rows = STORE.all(entity)
    if filters:
        for key, value in filters.items():
            if value is None:
                continue
            rows = [r for r in rows if r.get(key) == value]
    if query is not None:
        rows = [r for r in rows if query(r)]
    rows.sort(key=lambda r: (r.get("created_at") or "", r.get("_seq") or 0))
    return rows


def serialize_page(rows):
    return [serialize(r) for r in rows]


def state(row):
    return state_of(row)