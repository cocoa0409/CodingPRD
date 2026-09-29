"""Entity lookups and the traversal chain lease -> homesite -> phase -> community."""
from __future__ import annotations

from db import ordered, store
from errors import ApiError


def _fetch(table, identifier, error_id):
    record = table.get(identifier) if isinstance(identifier, str) else None
    if record is None:
        raise ApiError(error_id)
    return record


def get_community(identifier):
    return _fetch(store.communities, identifier, "ERR_COMMUNITY_NOT_FOUND")


def get_phase(identifier):
    return _fetch(store.phases, identifier, "ERR_PHASE_NOT_FOUND")


def get_homesite(identifier):
    return _fetch(store.homesites, identifier, "ERR_HOMESITE_NOT_FOUND")


def get_schedule(identifier):
    return _fetch(store.schedules, identifier, "ERR_RENT_SCHEDULE_NOT_FOUND")


def get_program(identifier):
    return _fetch(store.programs, identifier, "ERR_CONCESSION_PROGRAM_NOT_FOUND")


def get_household(identifier):
    return _fetch(store.households, identifier, "ERR_HOUSEHOLD_NOT_FOUND")


def get_lease(identifier):
    return _fetch(store.leases, identifier, "ERR_LEASE_NOT_FOUND")


def get_turn_order(identifier):
    return _fetch(store.turn_orders, identifier, "ERR_TURN_WORK_ORDER_NOT_FOUND")


def get_review(identifier):
    return _fetch(store.reviews, identifier, "ERR_ABSORPTION_REVIEW_NOT_FOUND")


# ---------------------------------------------------------------- traversals
def community_of_phase(phase):
    return store.communities[phase["community_id"]]


def community_of_homesite(homesite):
    return community_of_phase(store.phases[homesite["phase_id"]])


def phase_of_homesite(homesite):
    return store.phases[homesite["phase_id"]]


def homesite_of_lease(lease):
    return store.homesites[lease["homesite_id"]]


def community_of_lease(lease):
    return community_of_homesite(homesite_of_lease(lease))


# ---------------------------------------------------------------- collections
def phases_of_community(community):
    return ordered([p for p in store.phases.values() if p["community_id"] == community["id"]])


def homesites_of_phase(phase):
    return ordered([h for h in store.homesites.values() if h["phase_id"] == phase["id"]])


def homesites_of_community(community):
    phase_ids = {p["id"] for p in store.phases.values() if p["community_id"] == community["id"]}
    return ordered([h for h in store.homesites.values() if h["phase_id"] in phase_ids])


def leases_of_homesite(homesite):
    return ordered([l for l in store.leases.values() if l["homesite_id"] == homesite["id"]])


def leases_of_community(community):
    homesite_ids = {h["id"] for h in homesites_of_community(community)}
    return ordered([l for l in store.leases.values() if l["homesite_id"] in homesite_ids])


def leases_of_household(household):
    return ordered([l for l in store.leases.values() if l["household_id"] == household["id"]])


def schedules_of_community(community):
    return ordered([s for s in store.schedules.values()
                    if s["community_id"] == community["id"]])


def programs_of_community(community):
    return ordered([p for p in store.programs.values()
                    if p["community_id"] == community["id"]])


def reviews_of_community(community):
    return ordered([r for r in store.reviews.values()
                    if r["community_id"] == community["id"]])


def turn_orders_of_homesite(homesite):
    return ordered([t for t in store.turn_orders.values()
                    if t["homesite_id"] == homesite["id"]])


def turn_orders_of_community(community):
    homesite_ids = {h["id"] for h in homesites_of_community(community)}
    return ordered([t for t in store.turn_orders.values()
                    if t["homesite_id"] in homesite_ids])
