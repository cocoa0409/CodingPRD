"""Pre-built role headers for the five roles the platform recognises.

``MemberLibrarian`` identifies a member library and ``VendorRep`` identifies a
vendor, so calls made in either role MUST thread the real entity id through the
``make_*`` builders below.  The remaining three roles are opaque and the shared
constants are the canonical form for them.
"""

from typing import Dict

from prd_bench_local_runner.testing import build_user_headers

# ─── Shared constants ─────────────────────────────────────────────────────────
# Safe for the three opaque roles, and for tests that never exercise ownership.
TEST_USERS: Dict[str, Dict[str, str]] = {
    "admin_headers": build_user_headers("admin-1", "ConsortiumAdmin"),
    "second_admin_headers": build_user_headers("admin-2", "ConsortiumAdmin"),
    "negotiator_headers": build_user_headers("neg-1", "LicenseNegotiator"),
    "second_negotiator_headers": build_user_headers("neg-2", "LicenseNegotiator"),
    "engineer_headers": build_user_headers("eng-1", "AccessEngineer"),
    # Fallbacks for the two entity-backed roles: use ONLY where no ownership
    # check applies (missing-resource lookups, shape rejections, role rejections).
    "librarian_headers": build_user_headers("lib-1", "MemberLibrarian"),
    "vendor_rep_headers": build_user_headers("vend-1", "VendorRep"),
}


# ─── Per-instance builders ────────────────────────────────────────────────────

def make_admin_headers(user_id: str = "admin-1") -> Dict[str, str]:
    """ConsortiumAdmin. The identity is opaque; only the user id is recorded."""
    return build_user_headers(user_id, "ConsortiumAdmin")


def make_negotiator_headers(user_id: str = "neg-1") -> Dict[str, str]:
    """LicenseNegotiator. Opaque identity; the submitting user id is stamped on
    the negotiation for the segregation-of-duties check at signing."""
    return build_user_headers(user_id, "LicenseNegotiator")


def make_engineer_headers(user_id: str = "eng-1") -> Dict[str, str]:
    """AccessEngineer. Opaque identity."""
    return build_user_headers(user_id, "AccessEngineer")


def make_librarian_headers(member_id: str) -> Dict[str, str]:
    """MemberLibrarian. Pass the real member id — the header identifies the
    member library the caller speaks for, and any mismatch is rejected."""
    return build_user_headers(member_id, "MemberLibrarian")


def make_vendor_rep_headers(vendor_id: str) -> Dict[str, str]:
    """VendorRep. Pass the real vendor id — the header identifies the vendor the
    caller speaks for, and any mismatch is rejected."""
    return build_user_headers(vendor_id, "VendorRep")


def make_headers(user_id: str, role: str) -> Dict[str, str]:
    """Arbitrary user id / role pair, for authentication-surface tests."""
    return build_user_headers(user_id, role)


def blank_user_id_headers(role: str = "ConsortiumAdmin") -> Dict[str, str]:
    """Headers whose ``X-User-ID`` is present but genuinely empty."""
    return {"X-User-ID": "", "X-User-Role": role, "Content-Type": "application/json"}


def blank_role_headers(user_id: str = "admin-1") -> Dict[str, str]:
    """Headers whose ``X-User-Role`` is present but genuinely empty."""
    return {"X-User-ID": user_id, "X-User-Role": "", "Content-Type": "application/json"}


def missing_user_id_headers(role: str = "ConsortiumAdmin") -> Dict[str, str]:
    """Headers with no ``X-User-ID`` at all."""
    return {"X-User-Role": role, "Content-Type": "application/json"}


def missing_role_headers(user_id: str = "admin-1") -> Dict[str, str]:
    """Headers with no ``X-User-Role`` at all."""
    return {"X-User-ID": user_id, "Content-Type": "application/json"}
