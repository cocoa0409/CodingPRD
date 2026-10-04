"""Resource resolution and not-found dispatch (PRD 2.6, PRD 2.11 priorites 6-11).

Nested paths are resolved left to right and resolution stops at the first
segment that does not name an existing resource.  A missing household yields
``ERR_HOMEOWNER_NOT_FOUND``, a missing property ``ERR_PROPERTY_NOT_FOUND``, a
missing qualification ``ERR_QUALIFICATION_NOT_FOUND``, a missing program
``ERR_BRIDGE_PROGRAM_NOT_FOUND`` and a missing interim loan
``ERR_LOAN_NOT_FOUND``.  Every other entity addressed by a path identifier --
a bridge advance, a carrying cost, a repair advance, a backup offer, a listing,
an agent, a referral, a coordination task or a disbursement -- yields
``ERR_RESOURCE_NOT_FOUND``.

The same discipline governs bodies that reference several resources at once:
body references are validated before any business rule on the payload, so a
request naming a household that does not exist is refused for the missing
household and never reaches the arithmetic.
"""

from errors import (
    ERR_BRIDGE_PROGRAM_NOT_FOUND,
    ERR_HOMEOWNER_NOT_FOUND,
    ERR_LOAN_NOT_FOUND,
    ERR_PROPERTY_NOT_FOUND,
    ERR_QUALIFICATION_NOT_FOUND,
    ERR_RESOURCE_NOT_FOUND,
    ApiError,
)
from store import db

# collection -> (not-found error id, human label)
_COLLECTION_ERRORS = {
    "homeowners": (ERR_HOMEOWNER_NOT_FOUND, "homeowner"),
    "properties": (ERR_PROPERTY_NOT_FOUND, "property"),
    "qualifications": (ERR_QUALIFICATION_NOT_FOUND, "qualification"),
    "bridge_programs": (ERR_BRIDGE_PROGRAM_NOT_FOUND, "bridge program"),
    "interim_loans": (ERR_LOAN_NOT_FOUND, "interim loan"),
    "bridge_advances": (ERR_RESOURCE_NOT_FOUND, "bridge advance"),
    "carrying_costs": (ERR_RESOURCE_NOT_FOUND, "carrying cost"),
    "repair_advances": (ERR_RESOURCE_NOT_FOUND, "repair advance"),
    "backup_offers": (ERR_RESOURCE_NOT_FOUND, "backup offer"),
    "listings": (ERR_RESOURCE_NOT_FOUND, "listing"),
    "agents": (ERR_RESOURCE_NOT_FOUND, "agent"),
    "referrals": (ERR_RESOURCE_NOT_FOUND, "referral"),
    "coordination_tasks": (ERR_RESOURCE_NOT_FOUND, "coordination task"),
    "disbursements": (ERR_RESOURCE_NOT_FOUND, "disbursement"),
}


def fetch(collection, entity_id):
    """Return the entity or raise the collection's not-found error."""
    record = db.get(collection, entity_id)
    if record is None:
        error_id, label = _COLLECTION_ERRORS[collection]
        raise ApiError(error_id, "No %s matches the referenced id." % label)
    return record


def lookup(collection, entity_id):
    """Return the entity or ``None``, without raising."""
    if entity_id is None:
        return None
    return db.get(collection, entity_id)


def get_homeowner(entity_id):
    return fetch("homeowners", entity_id)


def get_property(entity_id):
    return fetch("properties", entity_id)


def get_qualification(entity_id):
    return fetch("qualifications", entity_id)


def get_bridge_program(entity_id):
    return fetch("bridge_programs", entity_id)


def get_interim_loan(entity_id):
    return fetch("interim_loans", entity_id)


def get_bridge_advance(entity_id):
    return fetch("bridge_advances", entity_id)


def get_carrying_cost(entity_id):
    return fetch("carrying_costs", entity_id)


def get_repair_advance(entity_id):
    return fetch("repair_advances", entity_id)


def get_backup_offer(entity_id):
    return fetch("backup_offers", entity_id)


def get_listing(entity_id):
    return fetch("listings", entity_id)


def get_agent(entity_id):
    return fetch("agents", entity_id)


def get_referral(entity_id):
    return fetch("referrals", entity_id)


def get_coordination_task(entity_id):
    return fetch("coordination_tasks", entity_id)


def get_disbursement(entity_id):
    return fetch("disbursements", entity_id)


# ---------------------------------------------------------------------------
# Scoped existence helpers.  These raise 404 when the id is unknown, and return
# ``None`` when the id is simply absent from the payload (an optional FK).
# ---------------------------------------------------------------------------

def resolve_homeowner_id(entity_id):
    if entity_id is None:
        return None
    return get_homeowner(entity_id)["id"]


def resolve_property_id(entity_id):
    if entity_id is None:
        return None
    return get_property(entity_id)["id"]


def resolve_qualification_id(entity_id):
    if entity_id is None:
        return None
    return get_qualification(entity_id)["id"]


def resolve_bridge_program_id(entity_id):
    if entity_id is None:
        return None
    return get_bridge_program(entity_id)["id"]


def resolve_interim_loan_id(entity_id):
    if entity_id is None:
        return None
    return get_interim_loan(entity_id)["id"]


def resolve_referral_id(entity_id):
    if entity_id is None:
        return None
    return get_referral(entity_id)["id"]


def resolve_agent_id(entity_id):
    if entity_id is None:
        return None
    return get_agent(entity_id)["id"]