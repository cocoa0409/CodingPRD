"""Pre-built role headers for every role in the PRD (§2.1).

Two roles are entity-backed: an AccountHolder's X-User-ID IS the Account id,
and a RecipientParty's X-User-ID IS the RecipientNumber id. For any
ownership-gated call, build headers from the created entity via
make_account_holder_headers(account["id"]) /
make_recipient_party_headers(recipient["id"]) — the shared constants for
those two roles are fallbacks for tests that do not exercise ownership
(e.g., 400-shape or 404-existence cases).

The four opaque roles carry operator identifiers. Segregation-of-duties
checks compare these identifiers against each other (refund decider vs
payer, requester vs decider), so each opaque role also gets a builder, and
ComplianceOfficer/FacilityStaff ship a second distinct constant.
"""
from prd_bench_local_runner.testing import build_user_headers

from .types import UserRole

TEST_USERS = {
    # Opaque roles — canonical shared constants (distinct X-User-ID each).
    "platform_admin_headers": build_user_headers(
        "test-platform-admin-1", UserRole.PLATFORM_ADMIN.value
    ),
    "state_regulator_headers": build_user_headers(
        "test-state-regulator-1", UserRole.STATE_REGULATOR.value
    ),
    "facility_staff_headers": build_user_headers(
        "test-facility-staff-1", UserRole.FACILITY_STAFF.value
    ),
    "facility_staff_alt_headers": build_user_headers(
        "test-facility-staff-2", UserRole.FACILITY_STAFF.value
    ),
    "compliance_officer_headers": build_user_headers(
        "test-compliance-officer-1", UserRole.COMPLIANCE_OFFICER.value
    ),
    "compliance_officer_alt_headers": build_user_headers(
        "test-compliance-officer-2", UserRole.COMPLIANCE_OFFICER.value
    ),
    # Entity-backed roles — fallback constants ONLY for non-ownership tests.
    "account_holder_headers": build_user_headers(
        "test-account-holder-1", UserRole.ACCOUNT_HOLDER.value
    ),
    "recipient_party_headers": build_user_headers(
        "test-recipient-party-1", UserRole.RECIPIENT_PARTY.value
    ),
}


def make_platform_admin_headers(user_id="test-platform-admin-1") -> dict:
    """PlatformAdmin (opaque)."""
    return build_user_headers(user_id, UserRole.PLATFORM_ADMIN.value)


def make_state_regulator_headers(user_id="test-state-regulator-1") -> dict:
    """StateRegulator (opaque)."""
    return build_user_headers(user_id, UserRole.STATE_REGULATOR.value)


def make_facility_staff_headers(user_id="test-facility-staff-1") -> dict:
    """FacilityStaff (opaque). Pass a distinct id when a segregation-of-duties
    pairing must differ from another operator's id."""
    return build_user_headers(user_id, UserRole.FACILITY_STAFF.value)


def make_compliance_officer_headers(user_id="test-compliance-officer-1") -> dict:
    """ComplianceOfficer (opaque). Refund SoD requires the payer's id to differ
    from the decider's id, and a staff requester may not self-decide — pass
    explicit ids to build those pairings."""
    return build_user_headers(user_id, UserRole.COMPLIANCE_OFFICER.value)


def make_account_holder_headers(account_id: str) -> dict:
    """AccountHolder (entity-backed: Account). Pass the actual Account id
    whenever the call is ownership-gated (deposits, close, messages,
    recipient-numbers, video-session create/cancel, claim-unclaimed)."""
    return build_user_headers(account_id, UserRole.ACCOUNT_HOLDER.value)


def make_recipient_party_headers(recipient_number_id: str) -> dict:
    """RecipientParty (entity-backed: RecipientNumber). Pass the actual
    RecipientNumber id whenever the call is ownership-gated (verify,
    request-block)."""
    return build_user_headers(recipient_number_id, UserRole.RECIPIENT_PARTY.value)


__all__ = [
    "TEST_USERS",
    "make_platform_admin_headers",
    "make_state_regulator_headers",
    "make_facility_staff_headers",
    "make_compliance_officer_headers",
    "make_account_holder_headers",
    "make_recipient_party_headers",
]
