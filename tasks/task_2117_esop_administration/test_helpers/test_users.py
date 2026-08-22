"""Pre-built role headers for every role in the PRD.

Four roles carry opaque operator identifiers that the server never compares to
any entity id, so their shared constants are always safe. `Participant` is the
one entity-backed role: its `X-User-ID` must be the acting participant's own
`id`, so ownership-gated calls MUST use `make_participant_headers(participant_id)`.
"""
from prd_bench_local_runner.testing import build_user_headers

# Opaque operator identifiers. Two distinct administrator identities and two
# distinct trustee identities exist so segregation-of-duties scenarios can be
# built (proposer and blesser must differ).
SPONSOR_USER_ID = "sponsor-01"
APPRAISER_USER_ID = "appraiser-01"
APPRAISER_ALT_USER_ID = "appraiser-02"
TRUSTEE_USER_ID = "trustee-01"
TRUSTEE_ALT_USER_ID = "trustee-02"
ADMIN_USER_ID = "tpa-01"
ADMIN_ALT_USER_ID = "tpa-02"

TEST_USERS = {
    # Opaque roles: the shared constant is the canonical form.
    "sponsor_headers": build_user_headers(SPONSOR_USER_ID, "PlanSponsor"),
    "appraiser_headers": build_user_headers(APPRAISER_USER_ID, "Appraiser"),
    "appraiser_alt_headers": build_user_headers(APPRAISER_ALT_USER_ID, "Appraiser"),
    "trustee_headers": build_user_headers(TRUSTEE_USER_ID, "Trustee"),
    "trustee_alt_headers": build_user_headers(TRUSTEE_ALT_USER_ID, "Trustee"),
    "admin_headers": build_user_headers(ADMIN_USER_ID, "PlanAdministrator"),
    "admin_alt_headers": build_user_headers(ADMIN_ALT_USER_ID, "PlanAdministrator"),
    # Entity-backed role: this shared constant is only valid for reads and for
    # calls that do not exercise ownership.
    "participant_headers": build_user_headers("test-participant-1", "Participant"),
}


def make_sponsor_headers(user_id: str) -> dict:
    """PlanSponsor acting under a specific opaque operator id."""
    return build_user_headers(user_id, "PlanSponsor")


def make_appraiser_headers(user_id: str) -> dict:
    """Appraiser acting under a specific opaque operator id. The id is stamped
    onto the valuation's appraiser_user_id at submission."""
    return build_user_headers(user_id, "Appraiser")


def make_trustee_headers(user_id: str) -> dict:
    """Trustee acting under a specific opaque operator id."""
    return build_user_headers(user_id, "Trustee")


def make_admin_headers(user_id: str) -> dict:
    """PlanAdministrator acting under a specific opaque operator id. The id is
    stamped onto an allocation run's created_by_user_id at creation."""
    return build_user_headers(user_id, "PlanAdministrator")


def make_participant_headers(participant_id: str) -> dict:
    """Participant acting on their own account. `participant_id` MUST be the
    real Participant record's id — ownership checks compare a resource's
    participant foreign key against this header value."""
    return build_user_headers(participant_id, "Participant")
