"""Pre-built role headers for every role declared in the PRD (PRD §2.1).

All six roles are opaque operator identifiers: ``X-User-ID`` is never compared
against the id of a persisted entity and no ownership check is performed
against it. The shared constants below are therefore the canonical form for
every role. The ``make_*_headers`` builders exist because two workflows compare
recorded operator identifiers against one another — the segregation-of-duties
checks on ``MetadataChangeSet.approved_by_user_id`` — so tests must be able to
present a specific ``X-User-ID`` value.
"""
from prd_bench_local_runner.testing import build_user_headers

# Shared constants — opaque identities, safe for every call.
TEST_USERS = {
    "platform_admin_headers": build_user_headers("test-platform-admin-1", "PlatformAdmin"),
    "release_manager_headers": build_user_headers("test-release-manager-1", "ReleaseManager"),
    "environment_admin_headers": build_user_headers("test-environment-admin-1", "EnvironmentAdmin"),
    "storage_archivist_headers": build_user_headers("test-storage-archivist-1", "StorageArchivist"),
    "security_auditor_headers": build_user_headers("test-security-auditor-1", "SecurityAuditor"),
    "app_developer_headers": build_user_headers("test-app-developer-1", "AppDeveloper"),
}


def make_platform_admin_headers(user_id: str = "test-platform-admin-2") -> dict:
    """PlatformAdmin headers carrying an explicit operator identifier.

    Used wherever the segregation-of-duties checks compare the approving
    ``X-User-ID`` against a previously recorded approval.  The default differs
    from the shared constant so that two successive approvals by ``ADMIN``
    present two distinct operators (PRD §3.5 requires them to differ).
    """
    return build_user_headers(user_id, "PlatformAdmin")


def make_release_manager_headers(user_id: str = "test-release-manager-2") -> dict:
    """ReleaseManager headers carrying an explicit operator identifier."""
    return build_user_headers(user_id, "ReleaseManager")


def make_environment_admin_headers(user_id: str = "test-environment-admin-2") -> dict:
    """EnvironmentAdmin headers carrying an explicit operator identifier."""
    return build_user_headers(user_id, "EnvironmentAdmin")


def make_storage_archivist_headers(user_id: str = "test-storage-archivist-2") -> dict:
    """StorageArchivist headers carrying an explicit operator identifier."""
    return build_user_headers(user_id, "StorageArchivist")


def make_security_auditor_headers(user_id: str = "test-security-auditor-2") -> dict:
    """SecurityAuditor headers carrying an explicit operator identifier."""
    return build_user_headers(user_id, "SecurityAuditor")


def make_app_developer_headers(user_id: str = "test-app-developer-2") -> dict:
    """AppDeveloper headers carrying an explicit operator identifier."""
    return build_user_headers(user_id, "AppDeveloper")