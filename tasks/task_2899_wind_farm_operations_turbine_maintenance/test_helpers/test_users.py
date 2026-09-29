"""Pre-built authentication headers for every declared role.

Every request carries ``X-User-ID`` and ``X-User-Role``.  The five non-crew
roles use opaque identifiers; a ``CrewLead`` request must carry the identifier
of the crew it acts for, which is why the crew-lead builder is parameterised.
"""

from typing import Dict, Optional

from prd_bench_local_runner.testing import build_user_headers

from .constants import (
    ROLE_COMMERCIAL_MANAGER,
    ROLE_CONTROL_ROOM_OPERATOR,
    ROLE_CREW_LEAD,
    ROLE_MAINTENANCE_PLANNER,
    ROLE_RELIABILITY_ENGINEER,
    ROLE_SITE_ADMIN,
    UNDECLARED_ROLE,
)

# --- Opaque user identifiers -------------------------------------------------
# Distinct values throughout: several rules compare the acting identifier with a
# recorded one, so no two actors may ever share an id.
SITE_ADMIN_USER_ID = "admin-1"
CONTROL_ROOM_USER_ID = "ops-1"
PLANNER_USER_ID = "planner-1"
PLANNER_2_USER_ID = "planner-2"
ENGINEER_USER_ID = "rel-1"
ENGINEER_2_USER_ID = "rel-2"
COMMERCIAL_USER_ID = "comm-1"
CREW_LEAD_USER_ID = "lead-1"


def make_site_admin_headers(user_id: str = SITE_ADMIN_USER_ID) -> Dict[str, str]:
    """Headers for a SiteAdmin actor."""
    return build_user_headers(user_id, ROLE_SITE_ADMIN)


def make_control_room_headers(user_id: str = CONTROL_ROOM_USER_ID) -> Dict[str, str]:
    """Headers for a ControlRoomOperator actor."""
    return build_user_headers(user_id, ROLE_CONTROL_ROOM_OPERATOR)


def make_planner_headers(user_id: str = PLANNER_USER_ID) -> Dict[str, str]:
    """Headers for a MaintenancePlanner actor."""
    return build_user_headers(user_id, ROLE_MAINTENANCE_PLANNER)


def make_engineer_headers(user_id: str = ENGINEER_USER_ID) -> Dict[str, str]:
    """Headers for a ReliabilityEngineer actor."""
    return build_user_headers(user_id, ROLE_RELIABILITY_ENGINEER)


def make_commercial_headers(user_id: str = COMMERCIAL_USER_ID) -> Dict[str, str]:
    """Headers for a CommercialManager actor."""
    return build_user_headers(user_id, ROLE_COMMERCIAL_MANAGER)


def make_crew_lead_headers(crew_id: str = CREW_LEAD_USER_ID) -> Dict[str, str]:
    """Headers for a CrewLead acting for ``crew_id``.

    Operations that check crew assignment compare the acting identifier with the
    work order's reserved crew, so callers pass the crew's own identifier.
    """
    return build_user_headers(crew_id, ROLE_CREW_LEAD)


def make_undeclared_role_headers(
    user_id: str = "stranger-1",
    role: str = UNDECLARED_ROLE,
) -> Dict[str, str]:
    """Headers whose role is not one of the declared roles."""
    return build_user_headers(user_id, role)


def make_headers_without_role(user_id: str = SITE_ADMIN_USER_ID) -> Dict[str, str]:
    """Headers with the role header entirely absent."""
    return {"X-User-ID": user_id, "Content-Type": "application/json"}


def make_headers_without_user_id(role: str = ROLE_SITE_ADMIN) -> Dict[str, str]:
    """Headers with the user identifier entirely absent."""
    return {"X-User-Role": role, "Content-Type": "application/json"}


def make_headers_with_blank_role(user_id: str = SITE_ADMIN_USER_ID) -> Dict[str, str]:
    """Headers whose role is present but empty.

    The value is the empty string, never whitespace: a whitespace-only header
    value is a different case from an empty one.
    """
    return {
        "X-User-ID": user_id,
        "X-User-Role": "",
        "Content-Type": "application/json",
    }


def make_headers_with_blank_user_id(role: str = ROLE_SITE_ADMIN) -> Dict[str, str]:
    """Headers whose user identifier is present but empty."""
    return {
        "X-User-ID": "",
        "X-User-Role": role,
        "Content-Type": "application/json",
    }


def make_headers(role: str, user_id: Optional[str] = None) -> Dict[str, str]:
    """Headers for an arbitrary declared role, used by parametrised role sweeps."""
    defaults = {
        ROLE_SITE_ADMIN: SITE_ADMIN_USER_ID,
        ROLE_CONTROL_ROOM_OPERATOR: CONTROL_ROOM_USER_ID,
        ROLE_MAINTENANCE_PLANNER: PLANNER_USER_ID,
        ROLE_RELIABILITY_ENGINEER: ENGINEER_USER_ID,
        ROLE_CREW_LEAD: CREW_LEAD_USER_ID,
        ROLE_COMMERCIAL_MANAGER: COMMERCIAL_USER_ID,
    }
    return build_user_headers(user_id or defaults.get(role, "user-1"), role)
