"""Acting-user identities and the header builders the suite calls with.

The PRD names seven roles and draws one sharp distinction between them:
``Producer`` is the only entity-backed role, so a producer's ``X-User-ID`` must
be the ``id`` of the acting producer row, while the other six roles are opaque
operator identifiers that are never compared to any entity's ``id``.
"""

from typing import Dict

from prd_bench_local_runner.testing import build_user_headers

ROLE_CENTER_ADMIN = "CenterAdmin"
ROLE_TRAINING_COORDINATOR = "TrainingCoordinator"
ROLE_CONTENT_REVIEWER = "ContentReviewer"
ROLE_SCHEDULING_COORDINATOR = "SchedulingCoordinator"
ROLE_FACILITIES_MANAGER = "FacilitiesManager"
ROLE_FINANCE_OFFICER = "FinanceOfficer"
ROLE_PRODUCER = "Producer"

ALL_ROLES = [
    ROLE_CENTER_ADMIN,
    ROLE_TRAINING_COORDINATOR,
    ROLE_CONTENT_REVIEWER,
    ROLE_SCHEDULING_COORDINATOR,
    ROLE_FACILITIES_MANAGER,
    ROLE_FINANCE_OFFICER,
    ROLE_PRODUCER,
]

STAFF_ROLES = [
    ROLE_CENTER_ADMIN,
    ROLE_TRAINING_COORDINATOR,
    ROLE_CONTENT_REVIEWER,
    ROLE_SCHEDULING_COORDINATOR,
    ROLE_FACILITIES_MANAGER,
    ROLE_FINANCE_OFFICER,
]

# Opaque operator identifiers. Two content reviewers and two of the money roles
# exist so that claim-versus-decide and duty-segregation rules can be exercised
# with genuinely different acting users.
USER_ADMIN = "adm-1"
USER_ADMIN_2 = "adm-2"
USER_TRAINER = "trn-1"
USER_REVIEWER = "rev-1"
USER_REVIEWER_2 = "rev-2"
USER_SCHEDULER = "sch-1"
USER_FACILITIES = "fac-1"
USER_FACILITIES_2 = "fac-2"
USER_FINANCE = "fin-1"
USER_FINANCE_2 = "fin-2"

TEST_USERS = {
    "admin": {"user_id": USER_ADMIN, "role": ROLE_CENTER_ADMIN},
    "admin2": {"user_id": USER_ADMIN_2, "role": ROLE_CENTER_ADMIN},
    "trainer": {"user_id": USER_TRAINER, "role": ROLE_TRAINING_COORDINATOR},
    "reviewer": {"user_id": USER_REVIEWER, "role": ROLE_CONTENT_REVIEWER},
    "reviewer2": {"user_id": USER_REVIEWER_2, "role": ROLE_CONTENT_REVIEWER},
    "scheduler": {"user_id": USER_SCHEDULER, "role": ROLE_SCHEDULING_COORDINATOR},
    "facilities": {"user_id": USER_FACILITIES, "role": ROLE_FACILITIES_MANAGER},
    "facilities2": {"user_id": USER_FACILITIES_2, "role": ROLE_FACILITIES_MANAGER},
    "finance": {"user_id": USER_FINANCE, "role": ROLE_FINANCE_OFFICER},
    "finance2": {"user_id": USER_FINANCE_2, "role": ROLE_FINANCE_OFFICER},
}

# Ready-made staff header dictionaries.
ADMIN_HEADERS = build_user_headers(USER_ADMIN, ROLE_CENTER_ADMIN)
ADMIN2_HEADERS = build_user_headers(USER_ADMIN_2, ROLE_CENTER_ADMIN)
TRAINER_HEADERS = build_user_headers(USER_TRAINER, ROLE_TRAINING_COORDINATOR)
REVIEWER_HEADERS = build_user_headers(USER_REVIEWER, ROLE_CONTENT_REVIEWER)
REVIEWER2_HEADERS = build_user_headers(USER_REVIEWER_2, ROLE_CONTENT_REVIEWER)
SCHEDULER_HEADERS = build_user_headers(USER_SCHEDULER, ROLE_SCHEDULING_COORDINATOR)
FACILITIES_HEADERS = build_user_headers(USER_FACILITIES, ROLE_FACILITIES_MANAGER)
FACILITIES2_HEADERS = build_user_headers(USER_FACILITIES_2, ROLE_FACILITIES_MANAGER)
FINANCE_HEADERS = build_user_headers(USER_FINANCE, ROLE_FINANCE_OFFICER)
FINANCE2_HEADERS = build_user_headers(USER_FINANCE_2, ROLE_FINANCE_OFFICER)

HEADERS_BY_ROLE = {
    ROLE_CENTER_ADMIN: ADMIN_HEADERS,
    ROLE_TRAINING_COORDINATOR: TRAINER_HEADERS,
    ROLE_CONTENT_REVIEWER: REVIEWER_HEADERS,
    ROLE_SCHEDULING_COORDINATOR: SCHEDULER_HEADERS,
    ROLE_FACILITIES_MANAGER: FACILITIES_HEADERS,
    ROLE_FINANCE_OFFICER: FINANCE_HEADERS,
}


def make_producer_headers(producer_id: str) -> Dict[str, str]:
    """Headers for a producer acting on their own records.

    ``X-User-ID`` is the producer row's ``id``, which is what ownership checks
    compare the resource's foreign key against.
    """
    return build_user_headers(producer_id, ROLE_PRODUCER)


def make_staff_headers(user_id: str, role: str) -> Dict[str, str]:
    """Headers for an arbitrary opaque operator identity."""
    return build_user_headers(user_id, role)


def headers_for_role(role: str, producer_id: str = None) -> Dict[str, str]:
    """Headers for any role; ``producer_id`` is required for ``Producer``."""
    if role == ROLE_PRODUCER:
        if producer_id is None:
            raise ValueError("Producer headers require the acting producer's id")
        return make_producer_headers(producer_id)
    return HEADERS_BY_ROLE[role]
