"""Identity threading for the six roles of PRD section 2.1.

Five roles carry an opaque identifier that the server only ever records and
compares against other recorded identifiers, so their builders take a caller
supplied operator name. ``TerminalOperator`` is entity-backed: its
``X-User-ID`` must be the ``id`` of the acting ``StorageAsset``, so its builder
takes an asset id and there is deliberately no default.
"""

from prd_bench_local_runner.testing import build_user_headers

from .constants import (
    ROLE_COMMERCIAL_MANAGER,
    ROLE_LOGISTICS_COORDINATOR,
    ROLE_PROCESS_ENGINEER,
    ROLE_REGULATORY_ADMIN,
    ROLE_SAFETY_OFFICER,
    ROLE_TERMINAL_OPERATOR,
)

# --- Named opaque operators ----------------------------------------------
# Distinct identifiers matter wherever segregation of duties is enforced
# (PRD 2.9), so the suite uses one identifier per signature slot.
REG_ADMIN = "reg-admin"

ENG_AUTHOR = "eng-author"
ENG_APPROVER = "eng-approver"
ENG_OPERATOR = "eng-operator"

SO_REVIEWER = "so-reviewer"
SO_APPROVER = "so-approver"
SO_SCREENER = "so-screener"
SO_CLEARER = "so-clearer"
SO_OFFICER = "so-officer"

CM_AUTHOR = "cm-author"
CM_TRADER = "cm-trader"

LOGISTICS = "logistics-coordinator"

UNKNOWN_ROLE_NAME = "PlantJanitor"


def make_regulatory_admin_headers(user_id: str = REG_ADMIN):
    """Headers for a RegulatoryAdmin acting under an opaque identifier."""
    return build_user_headers(user_id, ROLE_REGULATORY_ADMIN)


def make_process_engineer_headers(user_id: str = ENG_AUTHOR):
    """Headers for a ProcessEngineer acting under an opaque identifier."""
    return build_user_headers(user_id, ROLE_PROCESS_ENGINEER)


def make_safety_officer_headers(user_id: str = SO_OFFICER):
    """Headers for a SafetyOfficer acting under an opaque identifier."""
    return build_user_headers(user_id, ROLE_SAFETY_OFFICER)


def make_commercial_manager_headers(user_id: str = CM_AUTHOR):
    """Headers for a CommercialManager acting under an opaque identifier."""
    return build_user_headers(user_id, ROLE_COMMERCIAL_MANAGER)


def make_logistics_coordinator_headers(user_id: str = LOGISTICS):
    """Headers for a LogisticsCoordinator acting under an opaque identifier."""
    return build_user_headers(user_id, ROLE_LOGISTICS_COORDINATOR)


def make_terminal_operator_headers(asset_id: str):
    """Headers for a TerminalOperator.

    ``asset_id`` must be the id of the StorageAsset the operator speaks for:
    PRD 2.1 makes this role entity-backed and compares the header against the
    movement's ``dest_asset_id``.
    """
    return build_user_headers(asset_id, ROLE_TERMINAL_OPERATOR)


def make_role_headers(role: str, user_id: str):
    """Headers for an arbitrary role/identifier pair."""
    return build_user_headers(user_id, role)


# --- Malformed identity envelopes ---------------------------------------
def headers_missing_user_id(role: str = ROLE_REGULATORY_ADMIN):
    """Headers that omit X-User-ID entirely."""
    return {"X-User-Role": role, "Content-Type": "application/json"}


def headers_missing_role(user_id: str = REG_ADMIN):
    """Headers that omit X-User-Role entirely."""
    return {"X-User-ID": user_id, "Content-Type": "application/json"}


def headers_with_empty_user_id(role: str = ROLE_REGULATORY_ADMIN):
    """Headers whose X-User-ID is present but the zero-length string.

    The value is exactly "" and never a run of spaces: PRD 2.1 rejects a
    present-but-empty header, and a whitespace value would be a different
    request altogether.
    """
    return {"X-User-ID": "", "X-User-Role": role, "Content-Type": "application/json"}


def headers_with_empty_role(user_id: str = REG_ADMIN):
    """Headers whose X-User-Role is present but the zero-length string."""
    return {
        "X-User-ID": user_id,
        "X-User-Role": "",
        "Content-Type": "application/json",
    }


def headers_with_unknown_role(user_id: str = REG_ADMIN, role: str = UNKNOWN_ROLE_NAME):
    """Headers naming a role outside the six declared role names."""
    return {"X-User-ID": user_id, "X-User-Role": role, "Content-Type": "application/json"}


# Convenience singletons for the common read paths.
ADMIN = make_regulatory_admin_headers()
ENGINEER = make_process_engineer_headers()
SAFETY = make_safety_officer_headers()
COMMERCIAL = make_commercial_manager_headers()
LOGISTICS_HEADERS = make_logistics_coordinator_headers()

READER_ROLE_HEADER_BUILDERS = {
    ROLE_REGULATORY_ADMIN: make_regulatory_admin_headers,
    ROLE_PROCESS_ENGINEER: make_process_engineer_headers,
    ROLE_SAFETY_OFFICER: make_safety_officer_headers,
    ROLE_COMMERCIAL_MANAGER: make_commercial_manager_headers,
    ROLE_LOGISTICS_COORDINATOR: make_logistics_coordinator_headers,
}
