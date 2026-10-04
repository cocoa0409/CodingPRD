"""Pre-built role headers for every role in the PRD (§2.1).

Two roles are entity-backed: their ``X-User-ID`` is the ``id`` of a persisted
resource and ownership checks compare it against foreign keys on the target.

- ``LabAgent``        -> X-User-ID is the acting TestLaboratory's id
- ``ElectionOfficial`` -> X-User-ID is the acting ElectionOfficial's id

For those two roles the shared entries in TEST_USERS are fallbacks ONLY for
tests that never exercise an ownership check (bad payload, unknown resource,
role-denial probes). Any ownership-gated call MUST use the per-instance
builder with the real entity id — ``make_lab_agent_headers(lab["id"])`` /
``make_election_official_headers(official["id"])`` — and distinct owners get
distinct identities because each fixture creates its own laboratory/official
records. The remaining five roles are opaque: the server never compares their
X-User-ID to any resource id, so the shared constant is the canonical form.
"""
from prd_bench_local_runner.testing import build_user_headers

# Canonical opaque operator identifiers.
PLATFORM_ADMIN_ID = "test-platform-admin-1"
CERT_AUTHORITY_ID = "test-cert-authority-1"
VENDOR_REP_ID = "test-vendor-rep-1"
AUDITOR_ID = "test-auditor-1"
PUBLIC_REQUESTER_ID = "test-public-requester-1"

TEST_USERS = {
    # entity_backed fallbacks — non-ownership tests only, never ownership-gated
    # calls (the id will never equal a persisted laboratory/official id).
    "lab_agent_headers": build_user_headers("test-lab-1", "LabAgent"),
    "election_official_headers": build_user_headers("test-official-1", "ElectionOfficial"),
    # opaque roles — canonical form.
    "platform_admin_headers": build_user_headers(PLATFORM_ADMIN_ID, "PlatformAdmin"),
    "certification_authority_headers": build_user_headers(
        CERT_AUTHORITY_ID, "CertificationAuthority"
    ),
    "vendor_rep_headers": build_user_headers(VENDOR_REP_ID, "VendorRep"),
    "auditor_headers": build_user_headers(AUDITOR_ID, "Auditor"),
    "public_requester_headers": build_user_headers(PUBLIC_REQUESTER_ID, "PublicRequester"),
}


# --- Per-instance builders — mandatory for the entity-backed roles ----------
def make_lab_agent_headers(lab_id: str) -> dict:
    """For LabAgent: X-User-ID is the id of the acting TestLaboratory record."""
    return build_user_headers(lab_id, "LabAgent")


def make_election_official_headers(official_id: str) -> dict:
    """For ElectionOfficial: X-User-ID is the id of the acting ElectionOfficial."""
    return build_user_headers(official_id, "ElectionOfficial")


# --- Builders for the opaque roles (identity is a free operator handle) -----
def make_platform_admin_headers(user_id: str = PLATFORM_ADMIN_ID) -> dict:
    return build_user_headers(user_id, "PlatformAdmin")


def make_certification_authority_headers(user_id: str = CERT_AUTHORITY_ID) -> dict:
    return build_user_headers(user_id, "CertificationAuthority")


def make_vendor_rep_headers(user_id: str = VENDOR_REP_ID) -> dict:
    return build_user_headers(user_id, "VendorRep")


def make_auditor_headers(user_id: str = AUDITOR_ID) -> dict:
    return build_user_headers(user_id, "Auditor")


def make_public_requester_headers(user_id: str = PUBLIC_REQUESTER_ID) -> dict:
    return build_user_headers(user_id, "PublicRequester")
