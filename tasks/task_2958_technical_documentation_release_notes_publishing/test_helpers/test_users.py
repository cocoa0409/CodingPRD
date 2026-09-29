"""Header builders for the six roles of §2.1.

Two roles are backed by persisted records: a ``Writer``'s ``X-User-ID`` is the
``id`` of the acting ``Writer`` row and a ``Reviewer``'s ``X-User-ID`` is the
``id`` of the acting ``Reviewer`` row.  For those two, always thread the real
entity id through ``make_writer_headers`` / ``make_reviewer_headers``; the
placeholder entries in ``TEST_USERS`` resolve to nothing and are only useful
for probing ``ERR_ROLE_IDENTITY_MISMATCH``.

The other four roles carry opaque identities that the server never resolves,
so their shared header constants in ``TEST_USERS`` are safe to reuse.
"""
from prd_bench_local_runner.testing import build_user_headers

from .constants import TEST_DEFAULTS
from .types import UserRole

# ---------------------------------------------------------------------------
# Opaque operator identities (§2.1)
# ---------------------------------------------------------------------------

DOCS_LEAD_USER_ID = TEST_DEFAULTS["docs_lead_user_id"]
DOCS_LEAD_ALT_USER_ID = TEST_DEFAULTS["docs_lead_alt_user_id"]
LOCALIZATION_COORDINATOR_USER_ID = TEST_DEFAULTS["localization_coordinator_user_id"]
SUPPORT_ANALYST_USER_ID = TEST_DEFAULTS["support_analyst_user_id"]
READER_USER_ID = TEST_DEFAULTS["reader_user_id"]

#: An id of the right shape that resolves to no Writer/Reviewer row.
UNRESOLVABLE_ENTITY_USER_ID = "00000000-0000-0000-0000-0000000000ff"


# ---------------------------------------------------------------------------
# Per-role header builders
# ---------------------------------------------------------------------------

def make_docs_lead_headers(user_id: str = DOCS_LEAD_USER_ID) -> dict[str, str]:
    """Headers for a ``DocsLead``; ``user_id`` is an opaque operator identifier."""
    return build_user_headers(user_id, UserRole.DOCS_LEAD.value)


def make_writer_headers(user_id: str) -> dict[str, str]:
    """Headers for a ``Writer``; ``user_id`` MUST be an existing ``Writer.id``."""
    return build_user_headers(user_id, UserRole.WRITER.value)


def make_reviewer_headers(user_id: str) -> dict[str, str]:
    """Headers for a ``Reviewer``; ``user_id`` MUST be an existing ``Reviewer.id``."""
    return build_user_headers(user_id, UserRole.REVIEWER.value)


def make_localization_coordinator_headers(
    user_id: str = LOCALIZATION_COORDINATOR_USER_ID,
) -> dict[str, str]:
    """Headers for a ``LocalizationCoordinator``; the id is opaque."""
    return build_user_headers(user_id, UserRole.LOCALIZATION_COORDINATOR.value)


def make_support_analyst_headers(
    user_id: str = SUPPORT_ANALYST_USER_ID,
) -> dict[str, str]:
    """Headers for a ``SupportAnalyst``; the id is opaque."""
    return build_user_headers(user_id, UserRole.SUPPORT_ANALYST.value)


def make_reader_headers(user_id: str = READER_USER_ID) -> dict[str, str]:
    """Headers for a ``Reader``; the id is an opaque anonymous reader identifier."""
    return build_user_headers(user_id, UserRole.READER.value)


def make_headers(user_id: str, role: str) -> dict[str, str]:
    """Headers for an arbitrary role string, including unrecognized ones."""
    return build_user_headers(user_id, role)


# ---------------------------------------------------------------------------
# Malformed-header variants (§2.1)
# ---------------------------------------------------------------------------

def make_headers_missing_user_id(role: str = UserRole.DOCS_LEAD.value) -> dict[str, str]:
    """Headers with ``X-User-ID`` absent entirely."""
    return {"X-User-Role": role, "Content-Type": "application/json"}


def make_headers_missing_role(user_id: str = DOCS_LEAD_USER_ID) -> dict[str, str]:
    """Headers with ``X-User-Role`` absent entirely."""
    return {"X-User-ID": user_id, "Content-Type": "application/json"}


def make_headers_empty_user_id(role: str = UserRole.DOCS_LEAD.value) -> dict[str, str]:
    """Headers with ``X-User-ID`` present but sent as an empty string."""
    return {"X-User-ID": "", "X-User-Role": role, "Content-Type": "application/json"}


def make_headers_empty_role(user_id: str = DOCS_LEAD_USER_ID) -> dict[str, str]:
    """Headers with ``X-User-Role`` present but sent as an empty string."""
    return {"X-User-ID": user_id, "X-User-Role": "", "Content-Type": "application/json"}


# ---------------------------------------------------------------------------
# Shared header constants
# ---------------------------------------------------------------------------

TEST_USERS: dict[str, object] = {
    # Opaque roles — safe to share across a whole test.
    "docs_lead_headers": make_docs_lead_headers(),
    "docs_lead_alt_headers": make_docs_lead_headers(DOCS_LEAD_ALT_USER_ID),
    "localization_coordinator_headers": make_localization_coordinator_headers(),
    "support_analyst_headers": make_support_analyst_headers(),
    "reader_headers": make_reader_headers(),

    # Entity-backed roles — these do NOT resolve to a row; use the builders.
    "unresolvable_writer_headers": make_writer_headers(UNRESOLVABLE_ENTITY_USER_ID),
    "unresolvable_reviewer_headers": make_reviewer_headers(UNRESOLVABLE_ENTITY_USER_ID),

    # Raw identifiers, for asserting persisted accountability fields.
    "docs_lead_user_id": DOCS_LEAD_USER_ID,
    "docs_lead_alt_user_id": DOCS_LEAD_ALT_USER_ID,
    "localization_coordinator_user_id": LOCALIZATION_COORDINATOR_USER_ID,
    "support_analyst_user_id": SUPPORT_ANALYST_USER_ID,
    "reader_user_id": READER_USER_ID,
}
