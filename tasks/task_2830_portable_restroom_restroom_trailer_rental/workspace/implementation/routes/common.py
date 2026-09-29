"""Shared helpers for the route modules."""
import db as dbmod
from errors import fail
from responses import ok_list
import validation as V

NOT_FOUND = {
    "rental_accounts": "ERR_ACCOUNT_NOT_FOUND",
    "service_sites": "ERR_SITE_NOT_FOUND",
    "placement_permits": "ERR_PERMIT_NOT_FOUND",
    "asset_units": "ERR_ASSET_UNIT_NOT_FOUND",
    "disposal_sites": "ERR_DISPOSAL_SITE_NOT_FOUND",
    "routes": "ERR_ROUTE_NOT_FOUND",
    "rental_contracts": "ERR_CONTRACT_NOT_FOUND",
    "unit_deployments": "ERR_DEPLOYMENT_NOT_FOUND",
    "service_schedules": "ERR_SCHEDULE_NOT_FOUND",
    "service_visits": "ERR_VISIT_NOT_FOUND",
    "waste_manifests": "ERR_MANIFEST_NOT_FOUND",
    "charge_events": "ERR_CHARGE_NOT_FOUND",
}


def resolve(collection, row_id):
    row = dbmod.get(collection, row_id)
    if row is None:
        fail(NOT_FOUND[collection])
    return row


def list_response(rows, limit, offset, serializer=dbmod.serialize):
    window, total = V.paginate(rows, limit, offset)
    return ok_list([serializer(r) for r in window], total, limit, offset)
