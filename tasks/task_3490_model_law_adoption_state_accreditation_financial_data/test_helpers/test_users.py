"""Caller identities for the six declared roles.

Three roles carry an opaque operator identifier the server never compares to a
persisted entity id — ``AssociationStaff``, ``Actuary`` and ``ReviewTeamLead``
— so shared constants are safe for them (``ReviewTeamLead`` headers must still
match the ``team_lead_id`` a review was scheduled with; the default constant
uses the same ``lead-1`` the review factory defaults to).

The other three roles are entity-backed: the ``X-User-ID`` of a
``StateRegulator`` must be the ``id`` of a registered State, of an
``InsurerUser`` the ``id`` of a registered Insurer, and of a ``ProducerUser``
the ``id`` of a registered Producer. Authentication rejects an unresolvable id
outright, so these roles expose ONLY per-instance builders — fixtures must call
them with the live entity's ``id``.
"""

from prd_bench_local_runner.testing import build_user_headers

from .constants import (
    ACTIVATOR_ACTUARY_USER_ID,
    ASSOCIATION_STAFF_USER_ID,
    AUTHOR_ACTUARY_USER_ID,
    REVIEW_LEAD_USER_ID,
    ROLE_ACTUARY,
    ROLE_ASSOCIATION_STAFF,
    ROLE_INSURER_USER,
    ROLE_PRODUCER_USER,
    ROLE_REVIEW_TEAM_LEAD,
    ROLE_STATE_REGULATOR,
    SECOND_REVIEW_LEAD_USER_ID,
    THIRD_REVIEW_LEAD_USER_ID,
)
from .types import Headers, ResourceId

# Shared constants for the opaque roles — safe on any endpoint, including calls
# whose success does not depend on owning the subject resource.
TEST_USERS = {
    "association_staff_headers": build_user_headers(
        ASSOCIATION_STAFF_USER_ID, ROLE_ASSOCIATION_STAFF
    ),
    "actuary_author_headers": build_user_headers(AUTHOR_ACTUARY_USER_ID, ROLE_ACTUARY),
    "actuary_activator_headers": build_user_headers(
        ACTIVATOR_ACTUARY_USER_ID, ROLE_ACTUARY
    ),
    "review_team_lead_headers": build_user_headers(
        REVIEW_LEAD_USER_ID, ROLE_REVIEW_TEAM_LEAD
    ),
}


def make_association_staff_headers(user_id: str = ASSOCIATION_STAFF_USER_ID) -> Headers:
    """AssociationStaff is opaque; any identifier authenticates."""
    return build_user_headers(user_id, ROLE_ASSOCIATION_STAFF)


def make_actuary_headers(user_id: str) -> Headers:
    """Actuary is opaque. The author id of a standard may not activate it, so
    activation calls must be built with a different id (segregation of duties)."""
    return build_user_headers(user_id, ROLE_ACTUARY)


def make_review_team_lead_headers(user_id: str = REVIEW_LEAD_USER_ID) -> Headers:
    """ReviewTeamLead is opaque, but issue-findings compares the header to the
    review's stored team_lead_id — pass the same id used at scheduling."""
    return build_user_headers(user_id, ROLE_REVIEW_TEAM_LEAD)


def make_state_regulator_headers(state_id: ResourceId) -> Headers:
    """StateRegulator is entity-backed: X-User-ID must be the live State.id the
    regulator acts for. Ownership compares the resource's state_code (or
    lead_state_code on call close) to that State's code."""
    return build_user_headers(str(state_id), ROLE_STATE_REGULATOR)


def make_insurer_user_headers(insurer_id: ResourceId) -> Headers:
    """InsurerUser is entity-backed: X-User-ID must be the live Insurer.id; it
    must equal the insurer_id on filing create/submit and determines which
    insurer a market conduct response is filed for."""
    return build_user_headers(str(insurer_id), ROLE_INSURER_USER)


def make_producer_user_headers(producer_id: ResourceId) -> Headers:
    """ProducerUser is entity-backed: X-User-ID must be the live Producer.id and
    equal the producer_id on license applications."""
    return build_user_headers(str(producer_id), ROLE_PRODUCER_USER)


def headers_for_role(role: str, entity_id: ResourceId = None) -> Headers:
    """Build headers for any of the six roles.

    ``entity_id`` is required for the three entity-backed roles and ignored for
    the opaque ones (which fall back to their default operator ids).
    """
    if role == ROLE_STATE_REGULATOR:
        assert entity_id is not None, "StateRegulator headers need a live State.id"
        return make_state_regulator_headers(entity_id)
    if role == ROLE_INSURER_USER:
        assert entity_id is not None, "InsurerUser headers need a live Insurer.id"
        return make_insurer_user_headers(entity_id)
    if role == ROLE_PRODUCER_USER:
        assert entity_id is not None, "ProducerUser headers need a live Producer.id"
        return make_producer_user_headers(entity_id)
    if role == ROLE_ASSOCIATION_STAFF:
        return make_association_staff_headers()
    if role == ROLE_ACTUARY:
        return make_actuary_headers(AUTHOR_ACTUARY_USER_ID)
    if role == ROLE_REVIEW_TEAM_LEAD:
        return make_review_team_lead_headers()
    raise AssertionError("unknown role: %s" % role)


# --- Negative-authentication helpers ------------------------------------------
def headers_without_identity() -> Headers:
    """No identity headers at all (401 territory)."""
    return {"Content-Type": "application/json"}


def headers_with_unknown_role(user_id: str = ASSOCIATION_STAFF_USER_ID) -> Headers:
    """An undeclared role name (401 territory)."""
    return {"X-User-ID": user_id, "X-User-Role": "NotARealRole",
            "Content-Type": "application/json"}


# Second and third leads for reviewer-rotation scenarios.
SECOND_LEAD_HEADERS = build_user_headers(SECOND_REVIEW_LEAD_USER_ID, ROLE_REVIEW_TEAM_LEAD)
THIRD_LEAD_HEADERS = build_user_headers(THIRD_REVIEW_LEAD_USER_ID, ROLE_REVIEW_TEAM_LEAD)
