"""Reusable ladder guards (priorities 5-12) and reference resolution."""

import db
import util
from errors import ApiError, NOT_FOUND_BY_ENTITY


def resolve(entity, row_id):
    """Priority 5/6 existence check. `entity` is the db store's singular name."""
    store = _STORE_BY_ENTITY[entity]
    row = db.get(store, row_id)
    if row is None:
        raise ApiError(NOT_FOUND_BY_ENTITY[entity])
    return row


_STORE_BY_ENTITY = {
    "league": "leagues",
    "sport_classification": "sport_classifications",
    "league_policy": "league_policies",
    "participant": "participants",
    "enrollment": "enrollments",
    "family_health_plan": "family_health_plans",
    "sanctioned_activity": "sanctioned_activities",
    "injury_report": "injury_reports",
    "claim": "claims",
    "provider_bill": "provider_bills",
    "coordination_record": "coordination_records",
    "benefit_payment": "benefit_payments",
}


def maybe(entity, row_id):
    """Resolve without raising (used by the early ownership pre-check)."""
    if not isinstance(row_id, str):
        return None
    return db.get(_STORE_BY_ENTITY[entity], row_id)


# ------------------------------------------------------------ policy gates

def require_policy_in_force(policy, allowed):
    if policy["status"] not in allowed:
        raise ApiError("ERR_POLICY_NOT_IN_FORCE")


def require_league_sanctioned(policy_or_league):
    league = policy_or_league
    if league["_store"] != "leagues":
        league = db.get("leagues", policy_or_league["league_id"])
    if league["sanctioning_status"] != "SANCTIONED":
        raise ApiError("ERR_LEAGUE_NOT_SANCTIONED")


def require_not_frozen(policy):
    if policy["coverage_posture"] == "FROZEN":
        raise ApiError("ERR_POLICY_FROZEN")


def require_not_claims_review(policy):
    if policy["coverage_posture"] == "CLAIMS_REVIEW":
        raise ApiError("ERR_POLICY_UNDER_CLAIMS_REVIEW")


# --------------------------------------------------------------- term windows

def instant_in_term(policy, instant):
    """Half-open [term_effective_date, term_expiration_date)."""
    effective = util.parse_datetime(policy["term_effective_date"])
    expiration = util.parse_datetime(policy["term_expiration_date"])
    return effective <= instant < expiration


def policy_of_claim(claim):
    return db.get("league_policies", claim["league_policy_id"])


def report_of_claim(claim):
    return db.get("injury_reports", claim["injury_report_id"])


def sport_of_policy(policy):
    return db.get("sport_classifications", policy["sport_classification_id"])
