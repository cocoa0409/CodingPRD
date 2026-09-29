"""Shared route helpers: rank 3 existence, rank 4 ownership, rank 6 body
foreign keys, rank 7 version echoes, rank 9 segregation of duties."""

import db
from errors import ApiError

LABEL_ADMIN = "LabelAdmin"
DISTRIBUTION_PARTNER = "DistributionPartner"
ROYALTY_ANALYST = "RoyaltyAnalyst"
BUSINESS_AFFAIRS = "BusinessAffairs"
ARTIST = "Artist"

ENTITY_BACKED_ROLES = (DISTRIBUTION_PARTNER, ARTIST)


def _find(collection, record_id, error_id):
    record = collection.get(record_id)
    if record is None:
        raise ApiError(error_id)
    return record


def find_distributor(record_id):
    return _find(db.store.distributors, record_id, "ERR_DISTRIBUTOR_NOT_FOUND")


def find_artist(record_id):
    return _find(db.store.artists, record_id, "ERR_ARTIST_NOT_FOUND")


def find_deal(record_id):
    return _find(db.store.deals, record_id, "ERR_DEAL_NOT_FOUND")


def find_release(record_id):
    return _find(db.store.releases, record_id, "ERR_RELEASE_NOT_FOUND")


def find_agreement(record_id):
    return _find(db.store.agreements, record_id, "ERR_AGREEMENT_NOT_FOUND")


def find_spend(record_id):
    return _find(db.store.spends, record_id, "ERR_MARKETING_SPEND_NOT_FOUND")


def find_report(record_id):
    return _find(db.store.reports, record_id, "ERR_REVENUE_REPORT_NOT_FOUND")


def find_run(record_id):
    return _find(db.store.runs, record_id, "ERR_PHYSICAL_RUN_NOT_FOUND")


def find_statement(record_id):
    return _find(db.store.statements, record_id, "ERR_STATEMENT_NOT_FOUND")


def require_owner(caller, owner_id):
    """Rank 4.  Only the two entity-backed roles carry an ownership identity."""
    if caller.role not in ENTITY_BACKED_ROLES:
        return
    if owner_id is None or caller.user_id != owner_id:
        raise ApiError("ERR_NOT_RESOURCE_OWNER")


def require_separation(caller, other_actor_id):
    """Rank 9.  The same human may not perform both halves of the control."""
    if other_actor_id is not None and caller.user_id == other_actor_id:
        raise ApiError("ERR_SEGREGATION_OF_DUTIES")


def check_deal_version(deal, expected):
    if deal["version"] != expected:
        raise ApiError("ERR_STALE_DEAL_VERSION")


def check_run_version(run, expected):
    if run["version"] != expected:
        raise ApiError("ERR_STALE_RUN_VERSION")
