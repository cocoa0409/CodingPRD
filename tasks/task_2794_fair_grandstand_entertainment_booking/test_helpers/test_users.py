"""Header builders for the seven roles the PRD admits.

Six roles are opaque: the API only inspects ``X-User-Role`` for them, so any
stable ``X-User-ID`` works. ``TalentAgent`` is the one entity-backed role -- the
``X-User-ID`` it presents is matched against ``TalentAgent.user_id``, so agent
headers must be built from the ``user_id`` supplied when the agent record was
created (never from the record's ``id``).
"""

from prd_bench_local_runner.testing import build_user_headers

from .types import UserRole

# Opaque actor identifiers. Distinct per role so that audit stamps and the
# segregation-of-duties rule can be observed.
TEST_USERS = {
    "talent_buyer": {"user_id": "buyer-01", "role": UserRole.TALENT_BUYER.value},
    "talent_buyer_alt": {"user_id": "buyer-02", "role": UserRole.TALENT_BUYER.value},
    "fair_operations_director": {
        "user_id": "ops-director-01",
        "role": UserRole.FAIR_OPERATIONS_DIRECTOR.value,
    },
    "production_manager": {
        "user_id": "production-01",
        "role": UserRole.PRODUCTION_MANAGER.value,
    },
    "box_office_manager": {
        "user_id": "boxoffice-01",
        "role": UserRole.BOX_OFFICE_MANAGER.value,
    },
    "sponsorship_director": {
        "user_id": "sponsorship-01",
        "role": UserRole.SPONSORSHIP_DIRECTOR.value,
    },
    "settlement_controller": {
        "user_id": "controller-01",
        "role": UserRole.SETTLEMENT_CONTROLLER.value,
    },
    "settlement_controller_alt": {
        "user_id": "controller-02",
        "role": UserRole.SETTLEMENT_CONTROLLER.value,
    },
    "talent_agent": {"user_id": "agent-hollis", "role": UserRole.TALENT_AGENT.value},
}


def _headers(key):
    entry = TEST_USERS[key]
    return build_user_headers(entry["user_id"], entry["role"])


TALENT_BUYER_HEADERS = _headers("talent_buyer")
TALENT_BUYER_ALT_HEADERS = _headers("talent_buyer_alt")
FAIR_OPERATIONS_DIRECTOR_HEADERS = _headers("fair_operations_director")
PRODUCTION_MANAGER_HEADERS = _headers("production_manager")
BOX_OFFICE_MANAGER_HEADERS = _headers("box_office_manager")
SPONSORSHIP_DIRECTOR_HEADERS = _headers("sponsorship_director")
SETTLEMENT_CONTROLLER_HEADERS = _headers("settlement_controller")
SETTLEMENT_CONTROLLER_ALT_HEADERS = _headers("settlement_controller_alt")
TALENT_AGENT_HEADERS = _headers("talent_agent")


def make_talent_agent_headers(user_id):
    """Headers for the agent whose ``TalentAgent.user_id`` equals ``user_id``."""
    return build_user_headers(user_id, UserRole.TALENT_AGENT.value)


def make_headers(user_id, role):
    """Headers for an arbitrary identifier/role pair."""
    return build_user_headers(user_id, role)


ROLE_HEADERS = {
    UserRole.TALENT_BUYER.value: TALENT_BUYER_HEADERS,
    UserRole.TALENT_AGENT.value: TALENT_AGENT_HEADERS,
    UserRole.FAIR_OPERATIONS_DIRECTOR.value: FAIR_OPERATIONS_DIRECTOR_HEADERS,
    UserRole.PRODUCTION_MANAGER.value: PRODUCTION_MANAGER_HEADERS,
    UserRole.BOX_OFFICE_MANAGER.value: BOX_OFFICE_MANAGER_HEADERS,
    UserRole.SPONSORSHIP_DIRECTOR.value: SPONSORSHIP_DIRECTOR_HEADERS,
    UserRole.SETTLEMENT_CONTROLLER.value: SETTLEMENT_CONTROLLER_HEADERS,
}
