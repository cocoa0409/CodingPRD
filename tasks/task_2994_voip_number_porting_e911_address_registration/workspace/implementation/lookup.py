"""Reference resolution with the not-found error each family owns (ladder 6-9)."""
import store
from errors import ApiError


def account(account_id):
    row = store.accounts.get(account_id)
    if row is None:
        raise ApiError("ERR_ACCOUNT_NOT_FOUND", "No account with that id exists.")
    return row


def device(device_id):
    row = store.devices.get(device_id)
    if row is None:
        raise ApiError("ERR_DEVICE_NOT_FOUND", "No device with that id exists.")
    return row


def port_request(port_request_id):
    row = store.port_requests.get(port_request_id)
    if row is None:
        raise ApiError("ERR_PORT_REQUEST_NOT_FOUND", "No port request with that id exists.")
    return row


def resource(collection, resource_id, label="resource"):
    row = collection.get(resource_id)
    if row is None:
        raise ApiError("ERR_RESOURCE_NOT_FOUND", "No %s with that id exists." % label)
    return row


def carrier(carrier_id):
    return resource(store.carriers, carrier_id, "carrier")


def jurisdiction(jurisdiction_id):
    return resource(store.jurisdictions, jurisdiction_id, "jurisdiction")


def number_block(block_id):
    return resource(store.number_blocks, block_id, "number block")


def phone_number(number_id):
    return resource(store.phone_numbers, number_id, "phone number")


def reservation(reservation_id):
    return resource(store.number_reservations, reservation_id, "number reservation")


def cutover_slot(slot_id):
    return resource(store.cutover_slots, slot_id, "cutover slot")


def temporary_bridge(bridge_id):
    return resource(store.temporary_bridges, bridge_id, "temporary bridge")


def registration(registration_id):
    return resource(store.e911_registrations, registration_id, "e911 registration")


def assessment(assessment_id):
    return resource(store.fee_assessments, assessment_id, "fee assessment")


def require_active(account_row):
    if account_row["status"] != "ACTIVE":
        raise ApiError("ERR_ACCOUNT_NOT_ACTIVE", "The owning account is not ACTIVE.")
    return account_row
