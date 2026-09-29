"""Customer contracts and shipments in transit (PRD 3.9)."""

from flask import Blueprint

import clock
import domain
import helpers
import store
from errors import ApiError, invalid
from validation import COMMODITY_CLASSES, Body, authenticate

bp = Blueprint("commercial", __name__)

COMMERCIAL_READ_ROLES = ("CarrierRep", "ComplianceOfficer", "RegistryAdmin")
FREIGHT_CLASSES = ("GENERAL_FREIGHT", "HOUSEHOLD_GOODS", "HAZMAT_BULK", "HAZMAT_NONBULK")


@bp.post("/operating-authorities/<authority_id>/customer-contracts")
def create_contract(authority_id):
    uid, role = authenticate(("CarrierRep",))
    authority = helpers.need_authority(authority_id)
    helpers.require_carrier_owner(role, uid, authority["carrier_id"])

    body = Body()
    shipper_name = body.req_str("shipper_name", min_len=1, max_len=200)
    commodity_class = body.req_enum("commodity_class", COMMODITY_CLASSES)
    revenue = body.req_int("monthly_committed_revenue_cents", min_v=1)
    term_start_at = body.req_instant("term_start_at")
    term_end_at = body.req_instant("term_end_at")
    expected_version = body.req_int("expected_authority_version")
    if not term_start_at < term_end_at:
        raise invalid("Field 'term_start_at' must be strictly before 'term_end_at'.")

    # rung 8: the authority version guard
    if expected_version != authority["version"]:
        raise ApiError("ERR_STALE_AUTHORITY_VERSION")

    # rung 10: the authority must admit a new contract
    if authority["authority_status"] not in ("PENDING", "ACTIVE"):
        raise ApiError("ERR_AUTHORITY_INVALID_STATE")

    # rung 17: the passenger rule cuts both ways
    is_passenger_authority = authority["transportation_type"] == "PASSENGER"
    if commodity_class == "PASSENGERS":
        if not is_passenger_authority or not (authority["passenger_seating_capacity"] or 0) >= 1:
            raise ApiError("ERR_PASSENGER_AUTHORITY_REQUIRED")
    elif is_passenger_authority:
        raise ApiError("ERR_PASSENGER_AUTHORITY_REQUIRED")

    # rung 30: unified registration, uniquely strict on this operation
    carrier = store.CARRIERS[authority["carrier_id"]]
    if carrier["biennial_delinquent"] or carrier["unified_registration_status"] != "REGISTERED":
        raise ApiError("ERR_BIENNIAL_UPDATE_DELINQUENT")

    rec = store.base_record()
    rec.update({
        "authority_id": authority["id"],
        "shipper_name": shipper_name,
        "commodity_class": commodity_class,
        "monthly_committed_revenue_cents": revenue,
        "term_start_at": term_start_at,
        "term_end_at": term_end_at,
        "status": "ACTIVE",
        "suspended_at": None,
        "resumed_at": None,
        "terminated_at": None,
        "embargoed_shipment_count": 0,
        "disruption_liability_cents": 0,
        "disruption_liability_variant": "NONE",
    })
    store.insert(store.CONTRACTS, rec)

    authority["active_contract_count"] += 1
    domain.touch(authority)
    return helpers.one(rec, 201)


@bp.get("/operating-authorities/<authority_id>/customer-contracts")
def list_contracts(authority_id):
    authenticate(COMMERCIAL_READ_ROLES)
    helpers.need_authority(authority_id)
    return helpers.listing(store.contracts_of_authority(authority_id), {"status": "status"})


@bp.get("/customer-contracts/<contract_id>")
def read_contract(contract_id):
    authenticate(COMMERCIAL_READ_ROLES)
    return helpers.one(helpers.need_ref(store.CONTRACTS, contract_id))


@bp.post("/customer-contracts/<contract_id>/shipments")
def tender_shipment(contract_id):
    uid, role = authenticate(("CarrierRep",))
    contract = helpers.need_ref(store.CONTRACTS, contract_id)
    authority = store.AUTHORITIES.get(contract["authority_id"])
    helpers.require_carrier_owner(role, uid,
                                  None if authority is None else authority["carrier_id"])

    body = Body()
    origin_state = body.req_state("origin_state")
    destination_state = body.req_state("destination_state")
    tender_at = body.req_instant("tender_at")
    expected_delivery_at = body.req_instant("expected_delivery_at")
    declared_value = body.req_int("declared_value_cents", min_v=1)
    hazmat = body.opt_bool("hazmat", default=False)
    if not tender_at < expected_delivery_at:
        raise invalid("Field 'expected_delivery_at' must be strictly after 'tender_at'.")

    # rung 14: the contract must be ACTIVE
    if contract["status"] != "ACTIVE":
        raise ApiError("ERR_CONTRACT_NOT_ACTIVE")

    # rung 16: hazardous-materials authority
    commodity_class = contract["commodity_class"]
    if commodity_class == "HAZMAT_BULK":
        if not authority["hazmat_endorsed"] or not authority["hazmat_bulk_capable"]:
            raise ApiError("ERR_HAZMAT_AUTHORITY_REQUIRED")
    elif commodity_class == "HAZMAT_NONBULK" or hazmat:
        if not authority["hazmat_endorsed"]:
            raise ApiError("ERR_HAZMAT_AUTHORITY_REQUIRED")

    # rung 24: service of process arranged at both ends of the movement
    covered = domain.covered_states(authority)
    if origin_state not in covered or destination_state not in covered:
        raise ApiError("ERR_PROCESS_AGENT_NOT_DESIGNATED")

    rec = store.base_record()
    rec.update({
        "contract_id": contract["id"],
        "origin_state": origin_state,
        "destination_state": destination_state,
        "tender_at": tender_at,
        "expected_delivery_at": expected_delivery_at,
        "declared_value_cents": declared_value,
        "hazmat": hazmat,
        "status": "TENDERED",
        "pre_embargo_status": "NONE",
        "embargoed_at": None,
        "embargo_released_at": None,
        "embargo_days_accrued": 0,
        "delivered_at": None,
        "diverted_at": None,
    })
    store.insert(store.SHIPMENTS, rec)
    return helpers.one(rec, 201)


@bp.get("/shipments/<shipment_id>")
def read_shipment(shipment_id):
    authenticate(COMMERCIAL_READ_ROLES)
    return helpers.one(helpers.need_ref(store.SHIPMENTS, shipment_id))


@bp.get("/shipments")
def list_shipments():
    authenticate(COMMERCIAL_READ_ROLES)
    return helpers.listing(store.all_of(store.SHIPMENTS), {
        "contract_id": "contract_id",
        "status": "status",
    })


@bp.post("/shipments/<shipment_id>/depart")
def depart_shipment(shipment_id):
    uid, role = authenticate(("CarrierRep",))
    shipment = helpers.need_ref(store.SHIPMENTS, shipment_id)
    contract = store.CONTRACTS.get(shipment["contract_id"])
    authority = None if contract is None else store.AUTHORITIES.get(contract["authority_id"])
    helpers.require_carrier_owner(role, uid,
                                  None if authority is None else authority["carrier_id"])

    if shipment["status"] != "TENDERED":
        raise ApiError("ERR_SHIPMENT_INVALID_STATE")
    if contract["status"] != "ACTIVE":
        raise ApiError("ERR_CONTRACT_NOT_ACTIVE")
    if authority["authority_status"] != "ACTIVE":
        raise ApiError("ERR_AUTHORITY_INVALID_STATE")

    shipment["status"] = "IN_TRANSIT"
    domain.touch(shipment)
    return helpers.one(shipment)


@bp.post("/shipments/<shipment_id>/deliver")
def deliver_shipment(shipment_id):
    uid, role = authenticate(("CarrierRep",))
    shipment = helpers.need_ref(store.SHIPMENTS, shipment_id)
    contract = store.CONTRACTS.get(shipment["contract_id"])
    authority = None if contract is None else store.AUTHORITIES.get(contract["authority_id"])
    helpers.require_carrier_owner(role, uid,
                                  None if authority is None else authority["carrier_id"])

    if shipment["status"] != "IN_TRANSIT":
        raise ApiError("ERR_SHIPMENT_INVALID_STATE")

    shipment["status"] = "DELIVERED"
    shipment["delivered_at"] = clock.now()
    domain.touch(shipment)
    return helpers.one(shipment)
