"""Per-request identity, body parsing, pagination and the guard helpers."""

from flask import request

from core import constants as C
from core.errors import fail

# Populated by core.router.api() at import time: (METHOD, rule) -> role tuple
ROLE_MAP = {}
# (METHOD, rule) -> whether the endpoint expects the If-Match contract
IF_MATCH_MAP = {}


class Params:
    """Query-string pagination honouring the scaffold's limit/offset defaults."""

    def __init__(self, args):
        raw_limit = args.get("limit")
        raw_offset = args.get("offset")
        self.limit = _int_or(raw_limit, 10)
        if self.limit < 1:
            self.limit = 1
        if self.limit > 100:
            self.limit = 100
        self.offset = max(0, _int_or(raw_offset, 0))

    def has(self, name):
        return request.args.get(name) is not None

    def get(self, name):
        return request.args.get(name)


def _int_or(value, default):
    if value is None or value == "":
        return default
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


class Identity:
    def __init__(self, user_id, role):
        self.user_id = user_id
        self.role = role

    @property
    def is_client(self):
        return self.role == "Client"

    def owns_household(self, household_id):
        return self.is_client and self.user_id == household_id


def parse_identity():
    """Priority 1: both headers present and the role is one of the seven."""
    user_id = request.headers.get("X-User-ID")
    role = request.headers.get("X-User-Role")
    if not user_id or not role:
        fail("ERR_AUTHENTICATION_REQUIRED")
    if role not in C.ROLES:
        fail("ERR_AUTHENTICATION_REQUIRED")
    return Identity(user_id, role)


def check_authorized(identity, rule, method):
    """Priority 2: the caller's role is listed among the endpoint's roles."""
    roles = ROLE_MAP.get((method, rule))
    if roles is None:
        return
    if identity.role not in roles:
        fail("ERR_UNAUTHORIZED_ROLE")


def body():
    data = request.get_json(silent=True)
    return data if isinstance(data, dict) else {}


def need(data, field):
    value = data.get(field)
    if value is None or (isinstance(value, str) and value.strip() == ""):
        fail("ERR_RESOURCE_NOT_FOUND", "Missing required field: %s" % field)
    return value


def check_if_match(row, data, required=True):
    """Priority 13: the generic conditional-request contract.

    The endpoint's declared If-Match token may travel in the `If-Match`
    header or, equivalently, as an `if_match` body field.
    """
    provided = request.headers.get("If-Match")
    if provided is None:
        provided = data.get("if_match")
    if provided is None or provided == "":
        if required:
            fail("ERR_IF_MATCH_REQUIRED")
        return
    token = str(provided).strip().strip('"')
    if token != str(row.get("version")):
        fail("ERR_INVALID_IF_MATCH")


def check_occ(row, data, field, error_id):
    """Priority 12: the three explicit optimistic-concurrency contracts."""
    if field not in data or data.get(field) is None:
        fail(error_id, "%s is required" % field)
    if int(data[field]) != int(row.get("version")):
        fail(error_id)


def check_state(row, from_states, terminal=()):
    """Priorities 6/7.  Terminal is reported ahead of a from-state mismatch."""
    state = state_of(row)
    if terminal and state in terminal:
        fail("ERR_ALREADY_TERMINAL")
    if state not in from_states:
        fail("ERR_INVALID_STATE")


STATE_FIELDS = {
    "CustodyAgreement": "agreement_status",
    "AdvisorFirmEntitlement": "entitlement_status",
    "HouseholdAccount": "account_status",
    "AssetTransfer": "transfer_status",
    "TransferLot": "lot_status",
    "ModelPortfolio": "model_status",
    "BlockOrder": "block_status",
    "BlockAllocation": "allocation_status",
    "FeeBillingRun": "billing_run_status",
    "FeeCredit": "credit_status",
    "AlternativeAssetHolding": "asset_acceptance_status",
    "MoneyMovementInstruction": "movement_status",
    "StandingInstruction": "verification_status",
    "CustodyRulesEvidence": "requirement_status",
    "DataFeedProvision": "provision_status",
    "OnboardingBatch": "batch_status",
    "AdminActionLog": "admin_action_status",
    "ExaminationBundle": "bundle_status",
    "DatabaseInvariant": "invariant_status",
    "Household": "household_status",
    "AdvisorFirm": "firm_posture",
}


def state_of(row):
    field = STATE_FIELDS.get(row.get("_entity"))
    return row.get(field) if field else None