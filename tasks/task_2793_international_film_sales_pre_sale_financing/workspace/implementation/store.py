"""In-memory store. Every dict starts empty on boot — nothing is ever seeded."""
from __future__ import annotations

from datetime import datetime

from errors import ApiError
from util import UTC, new_id

# The logical clock's fixed startup instant (PRD 2.4).
CLOCK_EPOCH = datetime(2026, 8, 1, 0, 0, 0, 0, tzinfo=UTC)


class Store:
    def __init__(self):
        self.films = {}
        self.agreements = {}
        self.territories = {}
        self.comparables = {}
        self.valuations = {}
        self.markets = {}
        self.slots = {}
        self.buyers = {}
        self.meetings = {}
        self.contracts = {}
        self.milestones = {}
        self.packages = {}
        self.facilities = {}
        self.accounts = {}
        self.tiers = {}
        self.runs = {}
        self.current_utc = CLOCK_EPOCH
        self._seq = 0

    def next_seq(self):
        self._seq += 1
        return self._seq


db = Store()


def now():
    """The logical present instant."""
    return db.current_utc


# ---------------------------------------------------------------- row helpers


def base_row(versioned=True):
    # PRD 2.4: "Time in this system is a logical clock, not wall-clock time."
    # Every field recording when something happened is stamped from current_utc,
    # the one exception being a milestone's client-supplied received_at.  The
    # audit columns are no exception, so created_at / updated_at read the
    # logical present instant and _seq preserves insertion order on ties.
    row = {
        "id": new_id(),
        "created_at": now(),
        "_seq": db.next_seq(),
    }
    if versioned:
        row["updated_at"] = row["created_at"]
        row["version"] = 1
    return row


def touch(row):
    """Refresh updated_at and bump version by one (PRD 2.8)."""
    if "version" in row:
        row["updated_at"] = now()
        row["version"] = row["version"] + 1
    return row


def creation_key(row):
    return (row["created_at"], row["_seq"])


def by_creation(rows):
    """created_at ASC — the only common-field fallback ordering (PRD 2.3)."""
    return sorted(rows, key=creation_key)


# ------------------------------------------------------------------- lookups


def _fetch(bucket, row_id, error_id):
    if not isinstance(row_id, str):
        raise ApiError(error_id)
    row = bucket.get(row_id)
    if row is None:
        raise ApiError(error_id)
    return row


def get_film(film_id):
    return _fetch(db.films, film_id, "ERR_FILM_NOT_FOUND")


def get_territory(territory_id):
    return _fetch(db.territories, territory_id, "ERR_TERRITORY_NOT_FOUND")


def get_market(market_id):
    return _fetch(db.markets, market_id, "ERR_MARKET_NOT_FOUND")


def get_buyer(buyer_id):
    return _fetch(db.buyers, buyer_id, "ERR_BUYER_NOT_FOUND")


def get_contract(contract_id):
    return _fetch(db.contracts, contract_id, "ERR_CONTRACT_NOT_FOUND")


def get_valuation(valuation_id):
    return _fetch(db.valuations, valuation_id, "ERR_VALUATION_NOT_FOUND")


def get_agreement(agreement_id):
    return _fetch(db.agreements, agreement_id, "ERR_AGREEMENT_NOT_FOUND")


def get_milestone(milestone_id):
    return _fetch(db.milestones, milestone_id, "ERR_MILESTONE_NOT_FOUND")


def get_package(package_id):
    return _fetch(db.packages, package_id, "ERR_PACKAGE_NOT_FOUND")


def get_facility(facility_id):
    return _fetch(db.facilities, facility_id, "ERR_FACILITY_NOT_FOUND")


def get_account(account_id):
    return _fetch(db.accounts, account_id, "ERR_ACCOUNT_NOT_FOUND")


def get_slot(slot_id):
    return _fetch(db.slots, slot_id, "ERR_MARKET_ITEM_NOT_FOUND")


def get_meeting(meeting_id):
    return _fetch(db.meetings, meeting_id, "ERR_MARKET_ITEM_NOT_FOUND")


# ------------------------------------------------------------- child queries


def agreements_of_film(film_id):
    return by_creation([r for r in db.agreements.values() if r["film_id"] == film_id])


def comparables_of_territory(territory_id):
    return by_creation(
        [r for r in db.comparables.values() if r["territory_id"] == territory_id]
    )


def buyers_of_territory(territory_id):
    return by_creation([r for r in db.buyers.values() if r["territory_id"] == territory_id])


def valuations_of_film(film_id):
    return by_creation([r for r in db.valuations.values() if r["film_id"] == film_id])


def contracts_of_film(film_id):
    return by_creation([r for r in db.contracts.values() if r["film_id"] == film_id])


def contracts_of_buyer(buyer_id):
    return by_creation([r for r in db.contracts.values() if r["buyer_id"] == buyer_id])


def milestones_of_contract(contract_id):
    return by_creation(
        [r for r in db.milestones.values() if r["contract_id"] == contract_id]
    )


def packages_of_contract(contract_id):
    return by_creation([r for r in db.packages.values() if r["contract_id"] == contract_id])


def facilities_of_film(film_id):
    return by_creation([r for r in db.facilities.values() if r["film_id"] == film_id])


def accounts_of_film(film_id):
    return by_creation([r for r in db.accounts.values() if r["film_id"] == film_id])


def open_accounts_of_film(film_id):
    return [r for r in accounts_of_film(film_id) if r["status"] == "OPEN"]


def tiers_of_account(account_id):
    return by_creation([r for r in db.tiers.values() if r["account_id"] == account_id])


def runs_of_account(account_id):
    return by_creation([r for r in db.runs.values() if r["account_id"] == account_id])


def slots_of_market(market_id):
    return by_creation([r for r in db.slots.values() if r["market_id"] == market_id])


def meetings_of_market(market_id):
    return by_creation([r for r in db.meetings.values() if r["market_id"] == market_id])
