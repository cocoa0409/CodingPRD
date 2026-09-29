"""
Caller identities.

Four of the five roles are opaque operator identities: any stable token works, so this
module hands out named constants and pre-built header dicts for them. Several duties are
segregated — the analyst who prices a determination may not finalize it, the analyst who
finalized it may not void it, and the nurse who issued a query may not close it — so each
of those roles gets more than one identity, and tests pick deliberately.

`AttendingPhysician` is entity-backed: its `X-User-ID` must be the `id` of a real
`Physician` row, which is also what gets stamped into `closed_by_physician_id` and
`answered_by_physician_id`. Its headers therefore cannot be a constant; they are built
per test from the physician id the fixture just created, via
`make_attending_physician_headers`. Reaching for a shared constant instead turns one
ownership check into a cascade of unexplained 404s.
"""

from typing import Dict

from prd_bench_local_runner.testing import build_user_headers

from .types import UserRole

Json = Dict[str, str]

# ── Opaque operator identities ───────────────────────
COMPLIANCE_OFFICER_ID = "officer-a"
COMPLIANCE_OFFICER_2_ID = "officer-b"
INTAKE_COORDINATOR_ID = "intake-a"
INTAKE_COORDINATOR_2_ID = "intake-b"
NURSE_ID = "nurse-a"
NURSE_2_ID = "nurse-b"
ANALYST_ID = "analyst-a"
ANALYST_2_ID = "analyst-b"
ANALYST_3_ID = "analyst-c"

# A syntactically valid physician id that no `Physician` row uses, for probes that need a
# physician caller who does not exist.
UNKNOWN_PHYSICIAN_ID = "11111111-1111-1111-1111-111111111111"

# A role name outside the declared five, for the unknown-role probe.
UNKNOWN_ROLE = "WardClerk"


TEST_USERS: Dict[str, Dict[str, str]] = {
    "compliance_officer": {
        "user_id": COMPLIANCE_OFFICER_ID,
        "role": UserRole.COMPLIANCE_OFFICER,
    },
    "compliance_officer_2": {
        "user_id": COMPLIANCE_OFFICER_2_ID,
        "role": UserRole.COMPLIANCE_OFFICER,
    },
    "intake_coordinator": {
        "user_id": INTAKE_COORDINATOR_ID,
        "role": UserRole.INTAKE_COORDINATOR,
    },
    "intake_coordinator_2": {
        "user_id": INTAKE_COORDINATOR_2_ID,
        "role": UserRole.INTAKE_COORDINATOR,
    },
    "nurse": {"user_id": NURSE_ID, "role": UserRole.UTILIZATION_REVIEW_NURSE},
    "nurse_2": {"user_id": NURSE_2_ID, "role": UserRole.UTILIZATION_REVIEW_NURSE},
    "analyst": {"user_id": ANALYST_ID, "role": UserRole.REVENUE_INTEGRITY_ANALYST},
    "analyst_2": {"user_id": ANALYST_2_ID, "role": UserRole.REVENUE_INTEGRITY_ANALYST},
    "analyst_3": {"user_id": ANALYST_3_ID, "role": UserRole.REVENUE_INTEGRITY_ANALYST},
}


# ── Pre-built headers for the opaque roles ───────────
OFFICER_HEADERS = build_user_headers(COMPLIANCE_OFFICER_ID, UserRole.COMPLIANCE_OFFICER)
OFFICER_2_HEADERS = build_user_headers(
    COMPLIANCE_OFFICER_2_ID, UserRole.COMPLIANCE_OFFICER
)
INTAKE_HEADERS = build_user_headers(INTAKE_COORDINATOR_ID, UserRole.INTAKE_COORDINATOR)
INTAKE_2_HEADERS = build_user_headers(
    INTAKE_COORDINATOR_2_ID, UserRole.INTAKE_COORDINATOR
)
NURSE_HEADERS = build_user_headers(NURSE_ID, UserRole.UTILIZATION_REVIEW_NURSE)
NURSE_2_HEADERS = build_user_headers(NURSE_2_ID, UserRole.UTILIZATION_REVIEW_NURSE)
ANALYST_HEADERS = build_user_headers(ANALYST_ID, UserRole.REVENUE_INTEGRITY_ANALYST)
ANALYST_2_HEADERS = build_user_headers(ANALYST_2_ID, UserRole.REVENUE_INTEGRITY_ANALYST)
ANALYST_3_HEADERS = build_user_headers(ANALYST_3_ID, UserRole.REVENUE_INTEGRITY_ANALYST)


def headers_for(user_key: str) -> Json:
    """Headers for one of the named opaque operators, by key of TEST_USERS."""
    user = TEST_USERS[user_key]
    return build_user_headers(user["user_id"], user["role"])


def make_attending_physician_headers(physician_id: str) -> Json:
    """Headers for the physician of record whose `Physician` id is given.

    The specification makes this role's `X-User-ID` the physician row's own id, so the
    caller identity and the clinical identity are the same value.
    """
    return build_user_headers(physician_id, UserRole.ATTENDING_PHYSICIAN)


def make_headers(user_id: str, role: str) -> Json:
    """Headers for an arbitrary caller, for probes that need an unusual pairing."""
    return build_user_headers(user_id, role)


# Headers for every opaque role, keyed by role name, for the role-sweep probes.
OPAQUE_ROLE_HEADERS: Dict[str, Json] = {
    UserRole.COMPLIANCE_OFFICER: OFFICER_HEADERS,
    UserRole.INTAKE_COORDINATOR: INTAKE_HEADERS,
    UserRole.UTILIZATION_REVIEW_NURSE: NURSE_HEADERS,
    UserRole.REVENUE_INTEGRITY_ANALYST: ANALYST_HEADERS,
}
