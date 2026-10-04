"""Pre-built role headers for the five declared roles (PRD §2.1)."""
from prd_bench_local_runner.testing import build_user_headers

# Shared constants. Safe for the four opaque roles and for calls that do not
# exercise ownership. For AccountOwner the shared constant is only a fallback:
# the role is backed by an Account entity, so ownership-gated calls must carry
# make_account_owner_headers(account["id"]).
TEST_USERS = {
    "account_owner_headers": build_user_headers("test-account-owner-1", "AccountOwner"),
    "backup_operator_headers": build_user_headers("test-backup-operator-1", "BackupOperator"),
    "retention_officer_headers": build_user_headers("test-retention-officer-1", "RetentionOfficer"),
    "compliance_officer_headers": build_user_headers("test-compliance-officer-1", "ComplianceOfficer"),
    "system_operator_headers": build_user_headers("test-system-operator-1", "SystemOperator"),
}


def make_account_owner_headers(account_id: str) -> dict:
    """For AccountOwner, whose identity is the acting Account's id. Pass the
    actual Account.id whenever the call is ownership-gated."""
    return build_user_headers(account_id, "AccountOwner")