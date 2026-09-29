"""Identity header builders.

PRD §2.1 pins how `X-User-ID` is interpreted per role:

* `Teacher`      -> the acting Teacher's own `id`
* `PrivacyAnalyst` -> the acting PrivacyAnalyst's own `id`
* `VendorLiaison`  -> the acting **Vendor's** `id`; the liaison is not a
  separate person record, it *is* the vendor
* `PrivacyOfficeAdmin` and `TelemetryAgent` -> opaque operator identifiers that
  are never resolved against a stored row

Every distinct actor therefore gets a distinct `X-User-ID`, which is what the
ownership and segregation-of-duties rungs read.
"""

from typing import Dict

from prd_bench_local_runner.testing import build_user_headers

from .constants import (
    ROLE_PRIVACY_ANALYST,
    ROLE_PRIVACY_OFFICE_ADMIN,
    ROLE_TEACHER,
    ROLE_TELEMETRY_AGENT,
    ROLE_VENDOR_LIAISON,
)

# Opaque operator identifiers.  Distinct per operator so a test can tell two
# privacy-office operators apart in `triaged_by_user_id`.
ADMIN_USER_ID = "privacy-office-admin-001"
ADMIN_USER_ID_ALT = "privacy-office-admin-002"
TELEMETRY_USER_ID = "telemetry-collector-001"
TELEMETRY_USER_ID_ALT = "telemetry-collector-002"

Headers = Dict[str, str]


def make_admin_headers(user_id: str = ADMIN_USER_ID) -> Headers:
    """Headers for a PrivacyOfficeAdmin, whose identifier is opaque."""
    return build_user_headers(user_id, ROLE_PRIVACY_OFFICE_ADMIN)


def make_telemetry_headers(user_id: str = TELEMETRY_USER_ID) -> Headers:
    """Headers for a TelemetryAgent, whose identifier is opaque."""
    return build_user_headers(user_id, ROLE_TELEMETRY_AGENT)


def make_teacher_headers(teacher_id: str) -> Headers:
    """Headers for a Teacher, identified by that Teacher's own row id."""
    return build_user_headers(teacher_id, ROLE_TEACHER)


def make_analyst_headers(analyst_id: str) -> Headers:
    """Headers for a PrivacyAnalyst, identified by that analyst's row id."""
    return build_user_headers(analyst_id, ROLE_PRIVACY_ANALYST)


def make_vendor_liaison_headers(vendor_id: str) -> Headers:
    """Headers for a VendorLiaison, identified by the **vendor's** row id."""
    return build_user_headers(vendor_id, ROLE_VENDOR_LIAISON)


def make_role_headers(role: str, user_id: str) -> Headers:
    """Headers for an arbitrary role/identifier pair."""
    return build_user_headers(user_id, role)


def make_blank_identity_headers() -> Headers:
    """Both identity headers present but empty strings.

    PRD §2.1 treats an absent, empty or whitespace-only header the same way, so
    this models the empty-string case exactly: the header is sent, its value is
    the empty string, and no whitespace is substituted.
    """
    return {"X-User-ID": "", "X-User-Role": "", "Content-Type": "application/json"}


def make_missing_identity_headers() -> Headers:
    """Neither identity header sent at all."""
    return {"Content-Type": "application/json"}


ADMIN_HEADERS = make_admin_headers()
TELEMETRY_HEADERS = make_telemetry_headers()

TEST_USERS = {
    ROLE_PRIVACY_OFFICE_ADMIN: ADMIN_HEADERS,
    ROLE_TELEMETRY_AGENT: TELEMETRY_HEADERS,
}
