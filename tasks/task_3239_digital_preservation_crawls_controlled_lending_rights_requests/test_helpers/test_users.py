"""Pre-built role headers for every role in the PRD."""
from prd_bench_local_runner.testing import build_user_headers

# Shared constants — safe for opaque roles, and for tests that don't exercise ownership.
TEST_USERS = {
    # entity_backed role: shared constant is a fallback for non-ownership tests only.
    "patron_headers": build_user_headers("test-patron-shared", "Patron"),
    # opaque roles: shared constant is the canonical form.
    # Anonymous carries X-User-Role: Anonymous and NO X-User-ID (PRD 2.1).
    "anonymous_headers": {"X-User-Role": "Anonymous", "Content-Type": "application/json"},
    "admin_headers": build_user_headers("test-admin-1", "Admin"),
    "accessibility_officer_headers": build_user_headers("officer-1", "AccessibilityOfficer"),
    "library_admin_headers": build_user_headers("libadmin-1", "LibraryAdmin"),
    "scan_operator_headers": build_user_headers("scanop-1", "ScanOperator"),
    "crawl_operator_headers": build_user_headers("crawlop-1", "CrawlOperator"),
    "legal_reviewer_headers": build_user_headers("legal-a", "LegalReviewer"),
    "legal_reviewer_b_headers": build_user_headers("legal-b", "LegalReviewer"),
    "legal_reviewer_c_headers": build_user_headers("legal-c", "LegalReviewer"),
    "finance_admin_headers": build_user_headers("finance-1", "FinanceAdmin"),
}


# Per-instance builders — required for every entity_backed role.
def make_patron_headers(user_id: str) -> dict:
    """For Patron (entity_backed:Patron). Pass the actual Patron.id as user_id
    whenever the call is ownership-gated."""
    return build_user_headers(user_id, "Patron")


def make_legal_reviewer_headers(user_id: str) -> dict:
    """LegalReviewer with a specific opaque operator id (used for SoD scenarios)."""
    return build_user_headers(user_id, "LegalReviewer")


def make_accessibility_officer_headers(user_id: str) -> dict:
    """AccessibilityOfficer with a specific opaque operator id."""
    return build_user_headers(user_id, "AccessibilityOfficer")
