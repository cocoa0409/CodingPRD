"""Authentication, role authorisation and entity-backed actor resolution (PRD section 2.1)."""

from functools import wraps

from flask import g, request

from db import db
from errors import ApiError

ROLE_TALENT_BUYER = "TalentBuyer"
ROLE_TALENT_AGENT = "TalentAgent"
ROLE_FAIR_OPS = "FairOperationsDirector"
ROLE_PRODUCTION = "ProductionManager"
ROLE_BOX_OFFICE = "BoxOfficeManager"
ROLE_SPONSORSHIP = "SponsorshipDirector"
ROLE_SETTLEMENT = "SettlementController"

ALL_ROLES = (
    ROLE_TALENT_BUYER,
    ROLE_TALENT_AGENT,
    ROLE_FAIR_OPS,
    ROLE_PRODUCTION,
    ROLE_BOX_OFFICE,
    ROLE_SPONSORSHIP,
    ROLE_SETTLEMENT,
)


def roles(*allowed):
    """Decorator applying rejection steps 1 and 2 of PRD section 2.10.

    Step 3 (payload/query schema) and step 4 (actor identity resolution) are
    performed by the handler itself, in that order, because the PRD fixes the
    schema check ahead of the entity-backed identity lookup.
    """

    allowed_roles = tuple(allowed)

    def decorator(fn):
        @wraps(fn)
        def wrapper(*args, **kwargs):
            user_id = request.headers.get("X-User-ID")
            role = request.headers.get("X-User-Role")
            if user_id is None or role is None:
                raise ApiError("ERR_UNAUTHENTICATED")
            user_id = user_id.strip()
            role = role.strip()
            if user_id == "" or role == "" or role not in ALL_ROLES:
                raise ApiError("ERR_UNAUTHENTICATED")
            if role not in allowed_roles:
                raise ApiError("ERR_FORBIDDEN_ROLE")
            g.user_id = user_id
            g.role = role
            g.acting_agent = None
            g.agent_role_allowed = ROLE_TALENT_AGENT in allowed_roles
            return fn(*args, **kwargs)

        return wrapper

    return decorator


def resolve_actor():
    """Rejection step 4: the TalentAgent identity is entity-backed through user_id.

    Runs after schema validation and before any resource lookup.
    """
    if getattr(g, "role", None) != ROLE_TALENT_AGENT:
        return None
    for agent in db.agents.values():
        if agent.get("user_id") == g.user_id:
            g.acting_agent = agent
            return agent
    raise ApiError("ERR_UNKNOWN_ACTOR_IDENTITY")
