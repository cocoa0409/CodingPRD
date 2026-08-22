"""Pre-built role headers for every role in the PRD.

PRD section 2.1: `Performer` is the only role whose `X-User-ID` is a persisted
row id — it is the `id` of the acting `Performer` row. Ownership-gated calls
MUST therefore use make_performer_headers(performer["id"]); the shared
TEST_USERS constant is only safe for tests whose outcome does not depend on
ownership. `PermitOfficer`, `AuditionPanelist`, `NoiseInspector` and `Resident`
carry opaque operator identifiers.
"""
from prd_bench_local_runner.testing import build_user_headers


TEST_USERS = {
    "permit_officer_headers": build_user_headers("officer-alpha", "PermitOfficer"),
    "second_officer_headers": build_user_headers("officer-beta", "PermitOfficer"),
    "audition_panelist_headers": build_user_headers("panelist-1", "AuditionPanelist"),
    "noise_inspector_headers": build_user_headers("inspector-1", "NoiseInspector"),
    "resident_headers": build_user_headers("resident-1", "Resident"),
    # Entity-backed role: fallback constant for non-ownership tests only.
    "performer_headers": build_user_headers("test-performer-1", "Performer"),
}

OFFICER_ALPHA = "officer-alpha"
OFFICER_BETA = "officer-beta"
OFFICER_GAMMA = "officer-gamma"


def make_officer_headers(user_id: str = OFFICER_ALPHA) -> dict:
    """PermitOfficer headers. The identifier is opaque, but officer ids are
    compared to each other for separation of duties, so pass distinct values
    for the triaging/adjudicating and finalizing/deciding officers."""
    return build_user_headers(user_id, "PermitOfficer")


def make_performer_headers(user_id: str) -> dict:
    """Performer headers. Pass the actual Performer row's id — every
    ownership check compares the target resource's performer reference to it."""
    return build_user_headers(user_id, "Performer")


def make_panelist_headers(user_id: str = "panelist-1") -> dict:
    return build_user_headers(user_id, "AuditionPanelist")


def make_inspector_headers(user_id: str = "inspector-1") -> dict:
    return build_user_headers(user_id, "NoiseInspector")


def make_resident_headers(user_id: str = "resident-1") -> dict:
    return build_user_headers(user_id, "Resident")
