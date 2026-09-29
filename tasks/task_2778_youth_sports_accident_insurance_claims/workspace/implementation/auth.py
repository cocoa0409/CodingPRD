"""Authentication, role authorisation and the two entity-backed ownership models."""

from flask import request, g

import constants
import db
from errors import ApiError

ENTITY_BACKED_ROLES = ("LeagueAdministrator", "GuardianPortal")


def authenticate():
    user_id = request.headers.get("X-User-ID")
    role = request.headers.get("X-User-Role")
    if not user_id or not role or role not in constants.ROLES:
        raise ApiError("ERR_UNAUTHENTICATED")
    g.user_id = user_id
    g.user_role = role
    return user_id, role


def require_roles(allowed):
    user_id, role = authenticate()
    if role not in allowed:
        raise ApiError("ERR_ROLE_NOT_PERMITTED")
    return user_id, role


def ownership_sensitive(allowed):
    """Ladder priority 3 applies only where the role list admits an entity-backed role."""
    return any(r in allowed for r in ENTITY_BACKED_ROLES)


# ------------------------------------------------------------- graph resolvers

def league_id_of(row):
    store = row["_store"]
    if store == "leagues":
        return row["id"]
    if store in ("league_policies", "participants"):
        return row["league_id"]
    if store in ("enrollments", "sanctioned_activities"):
        policy = db.get("league_policies", row["league_policy_id"])
        return policy["league_id"] if policy else None
    if store == "injury_reports":
        enrollment = db.get("enrollments", row["enrollment_id"])
        if not enrollment:
            return None
        policy = db.get("league_policies", enrollment["league_policy_id"])
        return policy["league_id"] if policy else None
    if store == "claims":
        policy = db.get("league_policies", row["league_policy_id"])
        return policy["league_id"] if policy else None
    if store == "provider_bills":
        claim = db.get("claims", row["claim_id"])
        return league_id_of(claim) if claim else None
    if store in ("benefit_payments", "coordination_records"):
        claim = db.get("claims", row["claim_id"])
        return league_id_of(claim) if claim else None
    return None


def participant_id_of(row):
    store = row["_store"]
    if store == "participants":
        return row["id"]
    if store == "family_health_plans":
        return row["participant_id"]
    if store == "enrollments":
        return row["participant_id"]
    if store == "claims":
        enrollment = db.get("enrollments", row["enrollment_id"])
        return enrollment["participant_id"] if enrollment else None
    if store in ("provider_bills", "benefit_payments", "coordination_records"):
        claim = db.get("claims", row["claim_id"])
        return participant_id_of(claim) if claim else None
    return None


def check_ownership(row):
    """Compare X-User-ID against the League or Participant reached from `row`."""
    role = getattr(g, "user_role", None)
    user_id = getattr(g, "user_id", None)
    if row is None:
        return
    if role == "LeagueAdministrator":
        if league_id_of(row) != user_id:
            raise ApiError("ERR_OWNERSHIP_MISMATCH")
    elif role == "GuardianPortal":
        if participant_id_of(row) != user_id:
            raise ApiError("ERR_OWNERSHIP_MISMATCH")


def check_ownership_league(league_id):
    role = getattr(g, "user_role", None)
    if role == "LeagueAdministrator" and league_id != getattr(g, "user_id", None):
        raise ApiError("ERR_OWNERSHIP_MISMATCH")


def check_ownership_participant(participant_id):
    role = getattr(g, "user_role", None)
    if role == "GuardianPortal" and participant_id != getattr(g, "user_id", None):
        raise ApiError("ERR_OWNERSHIP_MISMATCH")


def early_ownership(entity, raw_id):
    """Priority-3 pre-check on a body foreign key, before request-shape validation."""
    import guards
    role = getattr(g, "user_role", None)
    if role not in ENTITY_BACKED_ROLES:
        return
    row = guards.maybe(entity, raw_id)
    if row is not None:
        check_ownership(row)
