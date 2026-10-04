"""Pre-built role headers for every role in PRD §2.1.

All seven roles carry an opaque identity: X-User-ID is an operator identifier
that is never equal to, and never compared against, any persisted entity's id
(PRD §2.1). Segregation of duties compares one operator's recorded X-User-ID
against another caller's (PRD §3.4 substantiation, PRD §3.8 settlement), so
the ClaimsScientist and LegalCounsel roles each ship TWO pre-built users with
distinct ids:

- SCI_ANNA conducts studies; SCI_BOB substantiates them.
- LC_JANE files patent cases; LC_JOHN settles them.
"""
from prd_bench_local_runner.testing import build_user_headers

from .types import UserRole

# Distinct operator ids for the segregation-of-duties pairs (PRD §3.4, §3.8).
SCI_ANNA_ID = "sci-anna"
SCI_BOB_ID = "sci-bob"
LC_JANE_ID = "lc-jane"
LC_JOHN_ID = "lc-john"

TEST_USERS = {
    "platform_admin_headers": build_user_headers("admin-op-1", UserRole.PLATFORM_ADMIN.value),
    "product_lead_headers": build_user_headers("pl-rhea-1", UserRole.PRODUCT_LEAD.value),
    "sourcing_manager_headers": build_user_headers("sm-omar-1", UserRole.SOURCING_MANAGER.value),
    "claims_scientist_headers": build_user_headers(SCI_ANNA_ID, UserRole.CLAIMS_SCIENTIST.value),
    "claims_scientist_alt_headers": build_user_headers(SCI_BOB_ID, UserRole.CLAIMS_SCIENTIST.value),
    "media_buyer_headers": build_user_headers("mb-cara-1", UserRole.MEDIA_BUYER.value),
    "retail_exec_headers": build_user_headers("re-vic-1", UserRole.RETAIL_EXEC.value),
    "legal_counsel_headers": build_user_headers(LC_JANE_ID, UserRole.LEGAL_COUNSEL.value),
    "legal_counsel_alt_headers": build_user_headers(LC_JOHN_ID, UserRole.LEGAL_COUNSEL.value),
}


def make_platform_admin_headers(user_id: str) -> dict:
    return build_user_headers(user_id, UserRole.PLATFORM_ADMIN.value)


def make_product_lead_headers(user_id: str) -> dict:
    return build_user_headers(user_id, UserRole.PRODUCT_LEAD.value)


def make_sourcing_manager_headers(user_id: str) -> dict:
    return build_user_headers(user_id, UserRole.SOURCING_MANAGER.value)


def make_claims_scientist_headers(user_id: str) -> dict:
    """Build headers for an additional ClaimsScientist operator.

    Use a user_id distinct from SCI_ANNA_ID / SCI_BOB_ID when a test needs a
    third scientist; substantiation is rejected when the caller's X-User-ID
    equals the study's conducted_by_user_id (PRD §3.4).
    """
    return build_user_headers(user_id, UserRole.CLAIMS_SCIENTIST.value)


def make_media_buyer_headers(user_id: str) -> dict:
    return build_user_headers(user_id, UserRole.MEDIA_BUYER.value)


def make_retail_exec_headers(user_id: str) -> dict:
    return build_user_headers(user_id, UserRole.RETAIL_EXEC.value)


def make_legal_counsel_headers(user_id: str) -> dict:
    """Build headers for an additional LegalCounsel operator.

    Use a user_id distinct from LC_JANE_ID / LC_JOHN_ID when a test needs a
    third counsel; settlement is rejected when the caller's X-User-ID equals
    the case's filed_by_user_id (PRD §3.8).
    """
    return build_user_headers(user_id, UserRole.LEGAL_COUNSEL.value)


__all__ = [
    "SCI_ANNA_ID",
    "SCI_BOB_ID",
    "LC_JANE_ID",
    "LC_JOHN_ID",
    "TEST_USERS",
    "make_platform_admin_headers",
    "make_product_lead_headers",
    "make_sourcing_manager_headers",
    "make_claims_scientist_headers",
    "make_media_buyer_headers",
    "make_retail_exec_headers",
    "make_legal_counsel_headers",
]
