"""All read endpoints (PRD section 4). List order is created_at ascending."""
from __future__ import annotations

from flask import Blueprint, request

import repo
import serializers
from db import ordered, store
from errors import ApiError
from middleware import ALL_OPERATOR_ROLES, acting_role, acting_user_id, endpoint
from response import listing, ok, ok_data, page_params
from services import valuation as valuation_service
from validation import body

bp = Blueprint("reads", __name__)

READ_ANY_OPERATOR = ALL_OPERATOR_ROLES
LEASING_READ_ROLES = ("DeveloperPrincipal", "LeasingAgent", "AssetManager", "PropertyManager")
INVENTORY_READ_ROLES = ("DeveloperPrincipal", "ConstructionManager", "LeasingAgent",
                        "AssetManager", "PropertyManager")
TURN_READ_ROLES = ("DeveloperPrincipal", "ConstructionManager", "AssetManager",
                   "PropertyManager")


def _filtered(records, spec):
    """spec maps a query parameter name to the record field it filters on."""
    result = list(records)
    for parameter, field in spec.items():
        wanted = request.args.get(parameter)
        if wanted is None:
            continue
        result = [r for r in result if r.get(field) == wanted]
    return result


def _collection(table):
    return ordered(list(table.values()))


# ---------------------------------------------------------------- communities
@bp.get("/communities")
@endpoint(*READ_ANY_OPERATOR)
def list_communities():
    limit, offset = page_params(request.args)
    records = _filtered(_collection(store.communities),
                        {"lifecycle_status": "lifecycle_status", "posture": "posture"})
    return listing(serializers.community, records, limit, offset)


@bp.get("/communities/<identifier>")
@endpoint(*READ_ANY_OPERATOR)
def get_community(identifier):
    return ok(serializers.community, repo.get_community(identifier))


@bp.get("/communities/<identifier>/valuation")
@endpoint("DeveloperPrincipal", "AssetManager")
def get_valuation(identifier):
    community = repo.get_community(identifier)
    basis = request.args.get("basis")
    if basis is None:
        basis = body().get("basis")
    if basis is None or basis not in valuation_service.BASES:
        raise ApiError("ERR_INVALID_REQUEST",
                       "basis must be TRAILING_ACTUAL or FORWARD_STABILIZED")
    return ok_data(valuation_service.valuation(community, basis))


# ---------------------------------------------------------------- phases and homesites
@bp.get("/phases")
@endpoint(*READ_ANY_OPERATOR)
def list_phases():
    limit, offset = page_params(request.args)
    records = _filtered(_collection(store.phases), {
        "community_id": "community_id",
        "predecessor_phase_id": "predecessor_phase_id",
        "status": "status",
        "kind": "kind",
    })
    return listing(serializers.phase, records, limit, offset)


@bp.get("/phases/<identifier>")
@endpoint(*READ_ANY_OPERATOR)
def get_phase(identifier):
    return ok(serializers.phase, repo.get_phase(identifier))


@bp.get("/homesites")
@endpoint(*INVENTORY_READ_ROLES)
def list_homesites():
    limit, offset = page_params(request.args)
    records = _filtered(_collection(store.homesites), {
        "phase_id": "phase_id",
        "product_type": "product_type",
        "status": "status",
    })
    return listing(serializers.homesite, records, limit, offset)


@bp.get("/homesites/<identifier>")
@endpoint(*INVENTORY_READ_ROLES)
def get_homesite(identifier):
    return ok(serializers.homesite, repo.get_homesite(identifier))


# ---------------------------------------------------------------- pricing and concessions
@bp.get("/market-rent-schedules")
@endpoint(*LEASING_READ_ROLES)
def list_schedules():
    limit, offset = page_params(request.args)
    records = _filtered(_collection(store.schedules), {
        "community_id": "community_id",
        "product_type": "product_type",
        "status": "status",
    })
    return listing(serializers.schedule, records, limit, offset)


@bp.get("/market-rent-schedules/<identifier>")
@endpoint(*LEASING_READ_ROLES)
def get_schedule(identifier):
    return ok(serializers.schedule, repo.get_schedule(identifier))


@bp.get("/concession-programs")
@endpoint(*LEASING_READ_ROLES)
def list_programs():
    limit, offset = page_params(request.args)
    records = _filtered(_collection(store.programs),
                        {"community_id": "community_id", "status": "status"})
    return listing(serializers.program, records, limit, offset)


@bp.get("/concession-programs/<identifier>")
@endpoint(*LEASING_READ_ROLES)
def get_program(identifier):
    return ok(serializers.program, repo.get_program(identifier))


# ---------------------------------------------------------------- households and leases
@bp.get("/households")
@endpoint(*LEASING_READ_ROLES)
def list_households():
    limit, offset = page_params(request.args)
    return listing(serializers.household, _collection(store.households), limit, offset)


@bp.get("/households/<identifier>")
@endpoint(*(LEASING_READ_ROLES + ("Household",)))
def get_household(identifier):
    return ok(serializers.household, repo.get_household(identifier))


@bp.get("/leases")
@endpoint(*LEASING_READ_ROLES)
def list_leases():
    limit, offset = page_params(request.args)
    records = _filtered(_collection(store.leases), {
        "homesite_id": "homesite_id",
        "household_id": "household_id",
        "concession_program_id": "concession_program_id",
        "priced_by_schedule_id": "priced_by_schedule_id",
        "lease_status": "lease_status",
        "concession_status": "concession_status",
    })
    return listing(serializers.lease, records, limit, offset)


@bp.get("/leases/<identifier>")
@endpoint(*(LEASING_READ_ROLES + ("Household",)))
def get_lease(identifier):
    lease = repo.get_lease(identifier)
    # One of exactly three operations guarded by the ownership check (PRD 2.1).
    if acting_role() == "Household" and lease["household_id"] != acting_user_id():
        raise ApiError("ERR_OWNERSHIP_VIOLATION")
    return ok(serializers.lease, lease)


# ---------------------------------------------------------------- turns and reviews
@bp.get("/turn-work-orders")
@endpoint(*TURN_READ_ROLES)
def list_turn_orders():
    limit, offset = page_params(request.args)
    records = _filtered(_collection(store.turn_orders), {
        "homesite_id": "homesite_id",
        "scope": "scope",
        "status": "status",
    })
    return listing(serializers.turn_order, records, limit, offset)


@bp.get("/turn-work-orders/<identifier>")
@endpoint(*TURN_READ_ROLES)
def get_turn_order(identifier):
    return ok(serializers.turn_order, repo.get_turn_order(identifier))


@bp.get("/absorption-reviews")
@endpoint(*LEASING_READ_ROLES)
def list_reviews():
    limit, offset = page_params(request.args)
    records = _filtered(_collection(store.reviews),
                        {"community_id": "community_id", "product_type": "product_type"})
    return listing(serializers.review, records, limit, offset)


@bp.get("/absorption-reviews/<identifier>")
@endpoint(*LEASING_READ_ROLES)
def get_review(identifier):
    return ok(serializers.review, repo.get_review(identifier))
