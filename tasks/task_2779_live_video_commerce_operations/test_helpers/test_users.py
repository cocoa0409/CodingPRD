"""Pre-built role headers for the seven roles the PRD declares.

Two roles are entity-backed: a Host's X-User-ID is the id of the acting Host row
and a Viewer's X-User-ID is the id of the acting Viewer row. Every
ownership-gated call for those two roles MUST go through make_host_headers() /
make_viewer_headers() with the real entity id. The other five roles carry opaque
identity, so their shared constants are the canonical form — except where a
segregation-of-duties comparison needs two distinct compliance officers, which is
what the two ComplianceOfficer entries below provide.
"""

from prd_bench_local_runner.testing import build_user_headers

CLAIMS_OFFICER_ID = "co-claims-1"
CERT_OFFICER_ID = "co-cert-1"
SIGNOFF_OFFICER_ID = "co-signoff-1"
MODERATOR_ID = "mod-1"
PRODUCER_ID = "prod-1"
MERCHANDISER_ID = "merch-1"
ADMIN_ID = "admin-1"

TEST_USERS = {
    "show_producer_headers": build_user_headers(PRODUCER_ID, "ShowProducer"),
    "merchandising_manager_headers": build_user_headers(
        MERCHANDISER_ID, "MerchandisingManager"
    ),
    "compliance_officer_headers": build_user_headers(
        CLAIMS_OFFICER_ID, "ComplianceOfficer"
    ),
    "compliance_officer_cert_headers": build_user_headers(
        CERT_OFFICER_ID, "ComplianceOfficer"
    ),
    "compliance_officer_signoff_headers": build_user_headers(
        SIGNOFF_OFFICER_ID, "ComplianceOfficer"
    ),
    "moderator_headers": build_user_headers(MODERATOR_ID, "Moderator"),
    "platform_admin_headers": build_user_headers(ADMIN_ID, "PlatformAdmin"),
    # Entity-backed roles: these shared constants are only safe for requests that
    # never reach an ownership comparison (unknown-role checks, 404 probes).
    "host_headers": build_user_headers("test-host-1", "Host"),
    "viewer_headers": build_user_headers("test-viewer-1", "Viewer"),
}


def make_show_producer_headers(user_id: str = PRODUCER_ID) -> dict:
    """For ShowProducer (opaque identity)."""
    return build_user_headers(user_id, "ShowProducer")


def make_merchandising_manager_headers(user_id: str = MERCHANDISER_ID) -> dict:
    """For MerchandisingManager (opaque identity)."""
    return build_user_headers(user_id, "MerchandisingManager")


def make_compliance_officer_headers(user_id: str = CLAIMS_OFFICER_ID) -> dict:
    """For ComplianceOfficer (opaque identity). Distinct identifiers matter because
    sign-off compares the acting officer against the officer recorded on the
    products the show merchandised."""
    return build_user_headers(user_id, "ComplianceOfficer")


def make_moderator_headers(user_id: str = MODERATOR_ID) -> dict:
    """For Moderator (opaque identity)."""
    return build_user_headers(user_id, "Moderator")


def make_platform_admin_headers(user_id: str = ADMIN_ID) -> dict:
    """For PlatformAdmin (opaque identity)."""
    return build_user_headers(user_id, "PlatformAdmin")


def make_host_headers(host_id: str) -> dict:
    """For Host. Pass the acting Host row's id as X-User-ID."""
    return build_user_headers(host_id, "Host")


def make_viewer_headers(viewer_id: str) -> dict:
    """For Viewer. Pass the acting Viewer row's id as X-User-ID."""
    return build_user_headers(viewer_id, "Viewer")


ALL_ROLE_NAMES = [
    "ShowProducer",
    "MerchandisingManager",
    "ComplianceOfficer",
    "Moderator",
    "Host",
    "Viewer",
    "PlatformAdmin",
]
