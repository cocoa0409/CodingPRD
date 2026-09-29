"""Pre-built request headers for every role the PRD declares.

Six of the seven roles are opaque: the acting user identifier is an arbitrary
string that is never compared against a stored row, so a shared constant per
role is the canonical form.  ``Guest`` is the sole entity-backed role - the PRD
says the acting user identifier is the id of the acting guest account - so a
Guest header must always be built from a real account id with
``make_guest_headers``.

Segregation-of-duties rules compare user identifiers rather than roles, so this
module also provides a second distinct identity for the three roles whose rules
need two different people (safety officers, experience producers, licensor
representatives).
"""

from typing import Dict

from prd_bench_local_runner.testing import build_user_headers

# ── Canonical actor identifiers ────────────────────────────────────────────
VENUE_OPS_MANAGER_ID = "vom-1"
LICENSING_MANAGER_ID = "lm-1"
LICENSOR_REP_ID = "rep-1"
OTHER_LICENSOR_REP_ID = "rep-2"
EXPERIENCE_PRODUCER_ID = "producer-1"
OTHER_EXPERIENCE_PRODUCER_ID = "producer-2"
SAFETY_OFFICER_ID = "officer-1"
OTHER_SAFETY_OFFICER_ID = "officer-2"
GUEST_SERVICES_AGENT_ID = "gsa-1"


TEST_USERS: Dict[str, Dict[str, str]] = {
    "venue_ops_manager_headers": build_user_headers(
        VENUE_OPS_MANAGER_ID, "VenueOpsManager"
    ),
    "licensing_manager_headers": build_user_headers(
        LICENSING_MANAGER_ID, "LicensingManager"
    ),
    "licensor_rep_headers": build_user_headers(LICENSOR_REP_ID, "LicensorRep"),
    "other_licensor_rep_headers": build_user_headers(
        OTHER_LICENSOR_REP_ID, "LicensorRep"
    ),
    "experience_producer_headers": build_user_headers(
        EXPERIENCE_PRODUCER_ID, "ExperienceProducer"
    ),
    "other_experience_producer_headers": build_user_headers(
        OTHER_EXPERIENCE_PRODUCER_ID, "ExperienceProducer"
    ),
    "safety_officer_headers": build_user_headers(SAFETY_OFFICER_ID, "SafetyOfficer"),
    "other_safety_officer_headers": build_user_headers(
        OTHER_SAFETY_OFFICER_ID, "SafetyOfficer"
    ),
    "guest_services_agent_headers": build_user_headers(
        GUEST_SERVICES_AGENT_ID, "GuestServicesAgent"
    ),
}


def make_guest_headers(guest_account_id: str) -> Dict[str, str]:
    """Headers for the Guest role.

    Guest is entity-backed: pass the guest account's own id so that every
    ownership check on an order resolves to this caller.
    """
    return build_user_headers(guest_account_id, "Guest")


def make_headers(user_id: str, role: str) -> Dict[str, str]:
    """Headers for an arbitrary user/role pair.

    Used where one person wears two hats - for example a licensor
    representative who also files submissions as an experience producer.
    """
    return build_user_headers(user_id, role)


# ── Malformed credentials used by the authentication tests ─────────────────
# A blank value is the empty string, never whitespace, so that the header is
# genuinely present and genuinely blank.
BLANK_USER_ID_HEADERS: Dict[str, str] = build_user_headers("", "VenueOpsManager")
BLANK_ROLE_HEADERS: Dict[str, str] = build_user_headers(VENUE_OPS_MANAGER_ID, "")
UNDECLARED_ROLE_HEADERS: Dict[str, str] = build_user_headers(
    "merch-1", "MerchandisingLead"
)
