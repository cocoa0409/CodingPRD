"""Authentication, RBAC, scope checks and segregation of duties (PRD 2.1)."""

from flask import request

import store
from errors import fail

ROLE_DEAN_OFFICE = "DeanOffice"
ROLE_DEPARTMENT_CHAIR = "DepartmentChair"
ROLE_DEAN = "Dean"
ROLE_FACILITIES = "FacilitiesManager"
ROLE_FACULTY = "Faculty"

ROLES = (
    ROLE_DEAN_OFFICE,
    ROLE_DEPARTMENT_CHAIR,
    ROLE_DEAN,
    ROLE_FACILITIES,
    ROLE_FACULTY,
)

USER_ID_HEADER = "X-User-ID"
USER_ROLE_HEADER = "X-User-Role"


class Actor(object):
    __slots__ = ("user_id", "role")

    def __init__(self, user_id, role):
        self.user_id = user_id
        self.role = role


def actor(allowed_roles):
    """Priority 1 then priority 2 of the global ladder (PRD 2.13)."""
    user_id = request.headers.get(USER_ID_HEADER)
    role = request.headers.get(USER_ROLE_HEADER)
    if user_id is None or user_id == "" or role is None or role == "":
        fail("ERR_UNAUTHENTICATED", "both X-User-ID and X-User-Role are required")
    if role not in ROLES:
        fail("ERR_UNAUTHENTICATED", "X-User-Role is not a declared role")
    if allowed_roles is not None and role not in allowed_roles:
        fail("ERR_UNAUTHORIZED", "role %s may not call this endpoint" % role)
    return Actor(user_id, role)


# ---------------------------------------------------------------------------
# Priority 12: unit scope
# ---------------------------------------------------------------------------


def _is_self_or_descendant(target_unit_id, ancestor_unit_id):
    seen = set()
    current = target_unit_id
    while current is not None and current not in seen:
        if current == ancestor_unit_id:
            return True
        seen.add(current)
        unit = store.db.funding_units.get(current)
        if unit is None:
            return False
        current = unit.get("parent_unit_id")
    return False


def unit_scope_on_unit(act, unit_id):
    """Funding-unit-scoped reads: the unit itself or one of its descendants."""
    if act.role not in (ROLE_DEPARTMENT_CHAIR, ROLE_DEAN):
        return
    if not _is_self_or_descendant(unit_id, act.user_id):
        fail("ERR_UNIT_SCOPE_VIOLATION", "acting unit is not in scope for this unit")


def unit_scope_on_package(act, package):
    """A DepartmentChair is scoped to department_unit_id, a Dean to college_unit_id."""
    if act.role == ROLE_DEPARTMENT_CHAIR:
        if act.user_id != package.get("department_unit_id"):
            fail("ERR_UNIT_SCOPE_VIOLATION", "acting chair does not fund this package")
    elif act.role == ROLE_DEAN:
        if act.user_id != package.get("college_unit_id"):
            fail("ERR_UNIT_SCOPE_VIOLATION", "acting dean does not fund this package")


# ---------------------------------------------------------------------------
# Priority 13: faculty scope
# ---------------------------------------------------------------------------


def faculty_scope(act, faculty_id):
    if act.role != ROLE_FACULTY:
        return
    if faculty_id is None or act.user_id != faculty_id:
        fail("ERR_FACULTY_SCOPE_VIOLATION", "faculty actors may only address their own records")


# ---------------------------------------------------------------------------
# Priority 14: segregation of duties
# ---------------------------------------------------------------------------


def segregation(act, *other_user_ids):
    for other in other_user_ids:
        if other is not None and act.user_id == other:
            fail(
                "ERR_SEGREGATION_OF_DUTIES",
                "the three negotiation signatures must be three distinct users",
            )
