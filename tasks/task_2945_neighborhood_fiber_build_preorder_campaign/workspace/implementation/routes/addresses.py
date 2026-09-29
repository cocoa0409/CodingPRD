"""The address registry, serviceability, the exception path and fallback offers."""

from flask import Blueprint

import auth
import calc
import cascades
import envelope
import listing
import serialize
import shape
from errors import ApiError
from store import bump, db, insert, must_find, new_row, now, ordered, rows

bp = Blueprint("addresses", __name__)


def _zone_of(address):
    return db.build_zones.get(address["build_zone_id"])


def _campaign_id_of(address):
    zone = _zone_of(address)
    return zone["campaign_id"] if zone else None


@bp.post("/service-addresses")
def create_address():
    auth.gate(("ProgramManager",))
    data = shape.body()
    zone = listing.resolve(data, "build_zone_id", "build_zones")
    shape.req_id(data, "build_zone_id")
    street = shape.req_str(data, "street_address", 1, 160)
    dwelling = shape.req_enum(data, "dwelling_type", calc.DWELLING_TYPES)
    unit_count = shape.opt_int(data, "unit_count", 1, None, 1)
    if dwelling == "SINGLE_FAMILY" and unit_count != 1:
        shape.bad("unit_count", "must be exactly 1 for a single-family address")
    if dwelling == "MDU" and unit_count < 2:
        shape.bad("unit_count", "must be at least 2 for an MDU address")
    distance = shape.req_int(data, "distance_to_node_m", 0)
    for existing in calc.zone_addresses(zone["id"]):
        if existing["street_address"] == street:
            shape.bad("street_address", "is already registered in this zone")
    row = new_row(
        {
            "build_zone_id": zone["id"],
            "street_address": street,
            "dwelling_type": dwelling,
            "unit_count": unit_count,
            "distance_to_node_m": distance,
            "serviceability": "UNDETERMINED",
            "not_serviceable_reason": None,
            "serviceability_determined_at": None,
            "exception_status": "NONE",
            "exception_reason": None,
            "active_fallback_technology": None,
        }
    )
    insert("service_addresses", row)
    bump(zone)
    return envelope.created(serialize.service_address(row))


@bp.get("/service-addresses/<address_id>")
def read_address(address_id):
    auth.gate(auth.ALL_ROLES)
    address = must_find("service_addresses", address_id)
    cascades.touch_address(address)
    return envelope.ok(serialize.service_address(address))


@bp.get("/service-addresses")
def list_addresses():
    auth.gate(auth.ALL_ROLES)
    items = ordered(rows("service_addresses"))
    for address in items:
        cascades.touch_address(address)
    items = listing.apply_filters(
        items,
        (
            listing.fk("build_zone_id", "build_zone_id", "build_zones"),
            listing.enum("serviceability", "serviceability", calc.SERVICEABILITIES),
            listing.enum("exception_status", "exception_status", calc.EXCEPTION_STATUSES),
            listing.enum("dwelling_type", "dwelling_type", calc.DWELLING_TYPES),
        ),
    )
    return envelope.list_response(items, serialize.service_address)


@bp.post("/service-addresses/<address_id>/serviceability-determination")
def determination(address_id):
    auth.gate(("ProgramManager",))
    address = must_find("service_addresses", address_id)
    data = shape.body()
    target = shape.req_enum(data, "serviceability", calc.DETERMINATIONS)
    reason = shape.opt_enum(data, "not_serviceable_reason", calc.NOT_SERVICEABLE_REASONS)
    if target == "NOT_SERVICEABLE" and reason is None:
        shape.bad("not_serviceable_reason", "is required for a NOT_SERVICEABLE determination")
    current = address["serviceability"]
    if target == "SERVICEABLE":
        if current != "UNDETERMINED":
            raise ApiError(
                "ERR_SERVICE_ADDRESS_STATE_INVALID",
                "SERVICEABLE is only reachable from UNDETERMINED",
            )
        if address["dwelling_type"] == "MDU" and not calc.has_signed_agreement(address["id"]):
            raise ApiError(
                "ERR_SERVICE_ADDRESS_STATE_INVALID",
                "an MDU address needs a signed owner agreement to be serviceable",
            )
    elif target == "CONDITIONAL_MDU":
        if current != "UNDETERMINED":
            raise ApiError(
                "ERR_SERVICE_ADDRESS_STATE_INVALID",
                "CONDITIONAL_MDU is only reachable from UNDETERMINED",
            )
        if address["dwelling_type"] != "MDU":
            raise ApiError(
                "ERR_SERVICE_ADDRESS_STATE_INVALID",
                "only an MDU address can be conditional",
            )
    else:
        if current not in ("UNDETERMINED", "SERVICEABLE"):
            raise ApiError(
                "ERR_SERVICE_ADDRESS_STATE_INVALID",
                "NOT_SERVICEABLE is only reachable from UNDETERMINED or SERVICEABLE",
            )
    address["serviceability"] = target
    address["serviceability_determined_at"] = now()
    address["not_serviceable_reason"] = reason if target == "NOT_SERVICEABLE" else None
    bump(address)
    zone = _zone_of(address)
    if zone is not None:
        bump(zone)
    return envelope.ok(serialize.service_address(address))


@bp.post("/service-addresses/<address_id>/unserved-exception")
def unserved_exception(address_id):
    auth.gate(("ProgramManager",))
    address = must_find("service_addresses", address_id)
    data = shape.body()
    action = shape.req_enum(data, "action", calc.EXCEPTION_ACTIONS)
    reason = shape.opt_str(data, "exception_reason", 1, 240)
    status = address["exception_status"]
    if action == "REQUEST":
        if status != "NONE":
            raise ApiError(
                "ERR_SERVICE_ADDRESS_STATE_INVALID", "an exception is already on record"
            )
        if address["serviceability"] != "NOT_SERVICEABLE":
            raise ApiError(
                "ERR_SERVICE_ADDRESS_STATE_INVALID",
                "an exception may only be requested for a NOT_SERVICEABLE address",
            )
        address["exception_status"] = "REQUESTED"
        address["exception_reason"] = reason
    elif action == "GRANT":
        if status != "REQUESTED":
            raise ApiError(
                "ERR_SERVICE_ADDRESS_STATE_INVALID", "only a requested exception can be granted"
            )
        if address["serviceability"] != "NOT_SERVICEABLE":
            raise ApiError(
                "ERR_SERVICE_ADDRESS_STATE_INVALID",
                "an exception may only be granted for a NOT_SERVICEABLE address",
            )
        address["exception_status"] = "GRANTED"
    else:
        if status != "REQUESTED":
            raise ApiError(
                "ERR_SERVICE_ADDRESS_STATE_INVALID", "only a requested exception can be denied"
            )
        address["exception_status"] = "DENIED"
    bump(address)
    return envelope.ok(serialize.service_address(address))


@bp.post("/service-addresses/<address_id>/fallback-offers")
def create_fallback_offer(address_id):
    auth.gate(("ProgramManager",))
    address = must_find("service_addresses", address_id)
    data = shape.body()
    account = listing.resolve(data, "account_id", "accounts")
    shape.req_id(data, "account_id")
    expires_at = shape.req_dt(data, "expires_at")
    if expires_at <= now():
        shape.bad("expires_at", "must fall strictly after the logical clock")
    if address["exception_status"] != "GRANTED":
        raise ApiError(
            "ERR_SERVICE_ADDRESS_STATE_INVALID",
            "an alternative-technology offer requires a granted exception",
        )
    option = calc.select_fallback_option(address, _campaign_id_of(address))
    if option is None:
        raise ApiError(
            "ERR_NO_FALLBACK_OPTION_AVAILABLE",
            "no eligible alternative-technology option remains for this address",
        )
    row = new_row(
        {
            "service_address_id": address["id"],
            "fallback_option_id": option["id"],
            "account_id": account["id"],
            "status": "OFFERED",
            "technology": option["technology"],
            "min_downstream_mbps": option["min_downstream_mbps"],
            "monthly_price_cents": option["monthly_price_cents"],
            "offered_at": now(),
            "expires_at": expires_at,
            "responded_at": None,
        }
    )
    insert("fallback_offers", row)
    return envelope.created(serialize.fallback_offer(row))
