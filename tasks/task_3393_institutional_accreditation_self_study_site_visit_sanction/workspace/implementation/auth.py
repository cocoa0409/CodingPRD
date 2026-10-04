"""Auth header extraction, role checks, and entity-backed ownership (PRD §2.1).

Every request must carry X-User-ID and X-User-Role; a missing header or an
undeclared role fails with ERR_UNAUTHENTICATED (401). A role not authorized
for the endpoint, or a failed ownership binding, fails with
ERR_UNAUTHORIZED_ROLE (403).

InstitutionLiaison ownership: X-User-ID must equal the id of the Institution
at the root of the target resource's parent chain. PeerReviewer binding is
enforced per endpoint by the route handlers (ERR_REVIEWER_NOT_ASSIGNED for
respond/schedule/file/verify; ERR_UNAUTHORIZED_ROLE for cast-vote membership).
"""
from flask import request

from constants import ROLES
from db import STORE
from errors import ERR_UNAUTHENTICATED, ERR_UNAUTHORIZED_ROLE, raise_err


class Actor:
    def __init__(self, user_id, role):
        self.user_id = user_id
        self.role = role


def authenticate():
    user_id = request.headers.get("X-User-ID")
    role = request.headers.get("X-User-Role")
    if not user_id or not role or role not in ROLES:
        raise_err(ERR_UNAUTHENTICATED, "Missing or malformed X-User-ID / X-User-Role headers")
    return Actor(user_id, role)


def require_role(actor, roles):
    if actor.role not in roles:
        raise_err(ERR_UNAUTHORIZED_ROLE, "Role %s is not permitted on this endpoint" % actor.role)


def require_liaison_owns(actor, institution_id):
    """For InstitutionLiaison actors, X-User-ID must equal the institution id."""
    if actor.role == "InstitutionLiaison" and actor.user_id != institution_id:
        raise_err(ERR_UNAUTHORIZED_ROLE, "Liaison may act only on the institution it represents")


def check_liaison_chain(actor, institution_id):
    """Ownership check for resources resolved through a parent chain."""
    require_liaison_owns(actor, institution_id)


def institution_of_cycle(cycle):
    return cycle["institution_id"] if cycle else None


def institution_of_argument(argument):
    cycle = STORE.review_cycles.get(argument["review_cycle_id"])
    return cycle["institution_id"] if cycle else None


def institution_of_evidence(item):
    argument = STORE.assurance_arguments.get(item["assurance_argument_id"])
    return institution_of_argument(argument) if argument else None


def institution_of_team(team):
    cycle = STORE.review_cycles.get(team["review_cycle_id"])
    return cycle["institution_id"] if cycle else None


def institution_of_assignment(assignment):
    team = STORE.review_teams.get(assignment["review_team_id"])
    return institution_of_team(team) if team else None


def institution_of_panel(panel):
    cycle = STORE.review_cycles.get(panel["review_cycle_id"])
    return cycle["institution_id"] if cycle else None


def institution_of_outcome(outcome):
    if outcome["review_cycle_id"]:
        cycle = STORE.review_cycles.get(outcome["review_cycle_id"])
        return cycle["institution_id"] if cycle else None
    return outcome["indicator_origin_institution_id"]
