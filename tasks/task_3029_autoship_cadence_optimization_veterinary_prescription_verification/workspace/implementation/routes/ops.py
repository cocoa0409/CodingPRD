"""Test-driving capabilities: the logical clock and the read-only site selector."""

from flask import request

import clock
import db
import serializers
from errors import fail
from middleware import body
from routing import Arr, Obj, endpoint
from services import calculations, plans as plan_svc


@endpoint("/v1/_clock/set_current_utc", ["POST"], ["PlatformAdmin"])
def set_clock(caller, ):
    payload = body()
    value = payload.get("current_utc")
    if not value:
        fail("ERR_INVALID_REQUEST", "Field 'current_utc' is required.")
    try:
        instant = clock.parse(value)
    except (ValueError, TypeError):
        fail("ERR_INVALID_REQUEST", "current_utc must be an ISO 8601 instant.")
    clock.set_current(instant)

    # automatic VERIFIED -> EXPIRED sweep for every prescription
    plan_svc.expiry_sweep()

    # every plan's cadence prompt date is recomputed and every shipment's
    # transit window re-evaluated against the new clock
    for plan in db.AUTOSHIP_PLANS.values():
        plan_svc.recompute_plan_aggregates(plan)
    for item in db.AUTOSHIP_ITEMS.values():
        plan_svc.recompute_item_projections(item)

    return Obj({}, 200)


@endpoint(
    "/v1/_sites/find-eligible", ["GET"], ["PlatformAdmin", "ComplianceOfficer"]
)
def find_eligible(caller, ):
    destination_state = request.args.get("destination_state")
    if not destination_state:
        fail("ERR_INVALID_REQUEST", "Query parameter 'destination_state' is required.")
    raw_units = request.args.get("cold_pack_units")
    try:
        cold_pack_units = int(raw_units) if raw_units not in (None, "") else 0
    except (TypeError, ValueError):
        fail("ERR_INVALID_REQUEST", "cold_pack_units must be an integer.")
    ranked = calculations.eligible_sites(destination_state, cold_pack_units)
    return Arr([serializers.pharmacy_site(s) for s in ranked])