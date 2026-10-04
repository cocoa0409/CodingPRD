"""Pre-built request headers for the four roles in the PRD (§2.1).

Role names are spelled exactly as the PRD declares them: `StateAdmin`,
`CardholderServices`, `Cardholder`, `RetailerSystem`.

Identity model:
- `StateAdmin` and `CardholderServices` carry opaque operator identifiers that
  the server never compares to an entity `id` — shared constants are canonical.
  Segregation of duties (PRD §3.8) compares one CSR identifier against another,
  so two distinct named CSR operators are published: CSR_USER_A and CSR_USER_B.
- `Cardholder` acts with X-User-ID == the CaseAccount.id, and `RetailerSystem`
  with X-User-ID == the Retailer.id. Ownership-gated calls MUST use
  `make_cardholder_headers(case["id"])` / `make_retailer_system_headers(retailer["id"])`.
  The shared constants for these two roles are fallbacks for tests that never
  exercise ownership (unauthenticated / forbidden-role / not-found cases).
"""
from typing import Dict

from prd_bench_local_runner.testing import build_user_headers

# --- Named opaque operator identities ----------------------------------------
STATE_ADMIN_USER_ID = "state-admin-1"
CSR_USER_A = "csr-a"
CSR_USER_B = "csr-b"

TEST_USERS: Dict[str, Dict[str, str]] = {
    # Opaque roles — canonical shared form.
    "state_admin_headers": build_user_headers(STATE_ADMIN_USER_ID, "StateAdmin"),
    "csr_headers": build_user_headers(CSR_USER_A, "CardholderServices"),
    "csr_alt_headers": build_user_headers(CSR_USER_B, "CardholderServices"),
    # Entity-backed roles — fallbacks for non-ownership tests only.
    "cardholder_headers": build_user_headers("test-cardholder-1", "Cardholder"),
    "retailer_system_headers": build_user_headers("test-retailer-1", "RetailerSystem"),
}

ALL_ROLE_HEADER_KEYS = [
    "state_admin_headers",
    "csr_headers",
    "cardholder_headers",
    "retailer_system_headers",
]


def make_state_admin_headers(user_id: str = STATE_ADMIN_USER_ID) -> Dict[str, str]:
    """Headers for a named StateAdmin operator (opaque identity, PRD §2.1)."""
    return build_user_headers(user_id, "StateAdmin")


def make_cardholder_services_headers(user_id: str) -> Dict[str, str]:
    """Headers for a named CardholderServices operator. Pass CSR_USER_A or
    CSR_USER_B deliberately wherever segregation of duties is in play (PRD §3.8)."""
    return build_user_headers(user_id, "CardholderServices")


def make_cardholder_headers(case_account_id: str) -> Dict[str, str]:
    """Headers for the acting Cardholder; pass the real CaseAccount.id (PRD §2.1)."""
    return build_user_headers(case_account_id, "Cardholder")


def make_retailer_system_headers(retailer_id: str) -> Dict[str, str]:
    """Headers for the acting RetailerSystem; pass the real Retailer.id (PRD §2.1)."""
    return build_user_headers(retailer_id, "RetailerSystem")


def headers_without_role(user_id: str = "anonymous-1") -> Dict[str, str]:
    """Headers omitting X-User-Role entirely (PRD §2.1 expects ERR_UNAUTHENTICATED)."""
    return {"X-User-ID": user_id, "Content-Type": "application/json"}


def headers_without_user_id(role: str = "StateAdmin") -> Dict[str, str]:
    """Headers omitting X-User-ID entirely (PRD §2.1 expects ERR_UNAUTHENTICATED)."""
    return {"X-User-Role": role, "Content-Type": "application/json"}


def headers_with_unknown_role(user_id: str = "anonymous-1") -> Dict[str, str]:
    """Headers naming a role outside the four recognised names (PRD §2.1 expects
    ERR_UNAUTHENTICATED)."""
    return build_user_headers(user_id, "StoreGreeter")
