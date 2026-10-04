"""Pre-built role headers for every role in the PRD (§2.1).

Opaque roles (PlatformAdmin, ContentIngester, CitatorAnalyst, AttorneyEditor,
LicensingManager, BillingAdmin, ComplianceOfficer) use shared constants: their
X-User-ID is never compared to an entity id, though AttorneyEditor calls carry
the editor's identity, so a per-editor builder is provided too.

Entity-backed roles (FirmAdmin -> SubscriberAccount.id, Researcher ->
SubscriberUser.id) MUST use the per-instance builders with the real entity id
whenever the call is ownership-gated (seat management, metered usage).
"""
from prd_bench_local_runner.testing import build_user_headers

TEST_USERS = {
    "platform_admin_headers": build_user_headers("test-platform-admin-1", "PlatformAdmin"),
    "content_ingester_headers": build_user_headers("test-content-ingester-1", "ContentIngester"),
    "citator_analyst_headers": build_user_headers("test-citator-analyst-1", "CitatorAnalyst"),
    "attorney_editor_headers": build_user_headers("ed-author-1", "AttorneyEditor"),
    "licensing_manager_headers": build_user_headers("test-licensing-manager-1", "LicensingManager"),
    "billing_admin_headers": build_user_headers("test-billing-admin-1", "BillingAdmin"),
    "compliance_officer_headers": build_user_headers("test-compliance-officer-1", "ComplianceOfficer"),
    # Fallbacks for non-ownership calls only; never use for seat/usage calls.
    "firm_admin_headers": build_user_headers("test-firm-admin-1", "FirmAdmin"),
    "researcher_headers": build_user_headers("test-researcher-1", "Researcher"),
}


def make_attorney_editor_headers(editor_id: str) -> dict:
    """AttorneyEditor is opaque, but headnote authorship/review compares
    X-User-ID to author_editor_id / reviewer_editor_id, so pass the editor's
    identity explicitly."""
    return build_user_headers(editor_id, "AttorneyEditor")


def make_firm_admin_headers(account_id: str) -> dict:
    """FirmAdmin is entity-backed: X-User-ID must equal the SubscriberAccount id
    owning the target subscription (PRD §2.1)."""
    return build_user_headers(account_id, "FirmAdmin")


def make_researcher_headers(user_id: str) -> dict:
    """Researcher is entity-backed: X-User-ID must equal the SubscriberUser id
    whose ACTIVE seat derives the usage event's subscription (PRD §2.1/§3.5)."""
    return build_user_headers(user_id, "Researcher")


# Common editor identities used by the editorial workflow tests.
EDITOR_AUTHOR = "ed-author-1"
EDITOR_REVIEWER = "ed-reviewer-1"
EDITOR_REVIEWER_2 = "ed-reviewer-2"
EDITOR_REVIEWER_9 = "ed-reviewer-9"
