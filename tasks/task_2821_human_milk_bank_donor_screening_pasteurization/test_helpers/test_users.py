"""Operator identities and the header pairs that carry them.

Seven of the eight roles carry an opaque `X-User-ID` that the server never
resolves to a row, so those identifiers are plain literals. The `Donor` role is
the one exception: its `X-User-ID` is the `id` of the acting donor row, so donor
headers can only be built once the donor exists, which is what
`make_donor_headers` is for.

The two segregation-of-duties rules force distinct identifiers within a role:
`QA_OFFICER_ID` records the culture, `QA_RELEASER_ID` performs the release, and
`PHARMACIST_ID` is never the same person as `PRESCRIBER_ID`.
"""

from typing import Dict

from prd_bench_local_runner.testing import build_user_headers

from .types import Role

# ---------------------------------------------------------------------------
# Opaque operator identifiers
# ---------------------------------------------------------------------------
ADMIN_ID = "u-admin-1"
INTAKE_ID = "u-intake-1"
INTAKE_ALT_ID = "u-intake-2"
MEDICAL_DIRECTOR_ID = "u-md-1"
MEDICAL_DIRECTOR_ALT_ID = "u-md-2"
TECHNICIAN_ID = "u-tech-1"
TECHNICIAN_ALT_ID = "u-tech-2"
QA_OFFICER_ID = "u-qa-1"          # records the post-pasteurization culture
QA_RELEASER_ID = "u-qa-2"         # releases the lot; must differ from the above
PHARMACIST_ID = "u-pharm-1"
PHARMACIST_ALT_ID = "u-pharm-2"
PRESCRIBER_ID = "u-presc-1"
PRESCRIBER_ALT_ID = "u-presc-2"

# ---------------------------------------------------------------------------
# Ready-made header pairs for the seven opaque roles
# ---------------------------------------------------------------------------
ADMIN_HEADERS = build_user_headers(ADMIN_ID, Role.MILK_BANK_ADMIN)
INTAKE_HEADERS = build_user_headers(INTAKE_ID, Role.INTAKE_COORDINATOR)
INTAKE_ALT_HEADERS = build_user_headers(INTAKE_ALT_ID, Role.INTAKE_COORDINATOR)
MEDICAL_DIRECTOR_HEADERS = build_user_headers(MEDICAL_DIRECTOR_ID, Role.MEDICAL_DIRECTOR)
MEDICAL_DIRECTOR_ALT_HEADERS = build_user_headers(
    MEDICAL_DIRECTOR_ALT_ID, Role.MEDICAL_DIRECTOR
)
TECHNICIAN_HEADERS = build_user_headers(TECHNICIAN_ID, Role.PROCESSING_TECHNICIAN)
TECHNICIAN_ALT_HEADERS = build_user_headers(TECHNICIAN_ALT_ID, Role.PROCESSING_TECHNICIAN)
QA_OFFICER_HEADERS = build_user_headers(QA_OFFICER_ID, Role.QUALITY_ASSURANCE_OFFICER)
QA_RELEASER_HEADERS = build_user_headers(QA_RELEASER_ID, Role.QUALITY_ASSURANCE_OFFICER)
PHARMACIST_HEADERS = build_user_headers(PHARMACIST_ID, Role.DISPENSING_PHARMACIST)
PHARMACIST_ALT_HEADERS = build_user_headers(PHARMACIST_ALT_ID, Role.DISPENSING_PHARMACIST)
PRESCRIBER_HEADERS = build_user_headers(PRESCRIBER_ID, Role.PRESCRIBER)
PRESCRIBER_ALT_HEADERS = build_user_headers(PRESCRIBER_ALT_ID, Role.PRESCRIBER)

TEST_USERS: Dict[str, Dict[str, str]] = {
    "admin": ADMIN_HEADERS,
    "intake": INTAKE_HEADERS,
    "intake_alt": INTAKE_ALT_HEADERS,
    "medical_director": MEDICAL_DIRECTOR_HEADERS,
    "medical_director_alt": MEDICAL_DIRECTOR_ALT_HEADERS,
    "technician": TECHNICIAN_HEADERS,
    "technician_alt": TECHNICIAN_ALT_HEADERS,
    "qa_officer": QA_OFFICER_HEADERS,
    "qa_releaser": QA_RELEASER_HEADERS,
    "pharmacist": PHARMACIST_HEADERS,
    "pharmacist_alt": PHARMACIST_ALT_HEADERS,
    "prescriber": PRESCRIBER_HEADERS,
    "prescriber_alt": PRESCRIBER_ALT_HEADERS,
}


# ---------------------------------------------------------------------------
# Entity-backed role: the acting donor
# ---------------------------------------------------------------------------
def make_donor_headers(donor_id: str) -> Dict[str, str]:
    """Headers for a donor acting on her own record.

    `X-User-ID` must be the `id` of the Donor row itself, because ownership
    checks compare the addressed resource's donor reference against it.
    """
    return build_user_headers(donor_id, Role.DONOR)


def headers_for(role: str, user_id: str) -> Dict[str, str]:
    """An arbitrary role/identifier pair, for access-control probes."""
    return build_user_headers(user_id, role)


def headers_missing_user_id(role: str) -> Dict[str, str]:
    """A header pair whose `X-User-ID` is present but empty."""
    return {"X-User-ID": "", "X-User-Role": role, "Content-Type": "application/json"}


def headers_missing_role(user_id: str) -> Dict[str, str]:
    """A header pair whose `X-User-Role` is present but empty."""
    return {"X-User-ID": user_id, "X-User-Role": "", "Content-Type": "application/json"}


NO_HEADERS: Dict[str, str] = {"Content-Type": "application/json"}

UNKNOWN_ROLE_HEADERS = {
    "X-User-ID": "u-super-1",
    "X-User-Role": "MilkBankSuperuser",
    "Content-Type": "application/json",
}
