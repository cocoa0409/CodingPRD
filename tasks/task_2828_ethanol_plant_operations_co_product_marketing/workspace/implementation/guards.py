"""Lookups and shared preconditions, in PRD 2.9 rejection order."""
import calc
import derive
from errors import fail
from store import db, touch
from util import D, at_second


def get_plant_or_404(plant_id=None):
    plant = db.plant
    if plant is None:
        fail("ERR_PLANT_NOT_FOUND", "No plant has been registered")
    if plant_id is not None and plant_id != plant["id"]:
        fail("ERR_PLANT_NOT_FOUND", "Plant %s does not exist" % plant_id)
    return plant


def get_contract(contract_id):
    row = db.contracts.get(contract_id)
    if row is None:
        fail("ERR_CONTRACT_NOT_FOUND", "Contract %s does not exist" % contract_id)
    return row


def get_delivery(delivery_id):
    row = db.deliveries.get(delivery_id)
    if row is None:
        fail("ERR_DELIVERY_NOT_FOUND", "Delivery %s does not exist" % delivery_id)
    return row


def get_batch(batch_id):
    row = db.batches.get(batch_id)
    if row is None:
        fail("ERR_BATCH_NOT_FOUND", "Batch %s does not exist" % batch_id)
    return row


def get_tank(tank_id):
    row = db.tanks.get(tank_id)
    if row is None:
        fail("ERR_TANK_NOT_FOUND", "Tank %s does not exist" % tank_id)
    return row


def get_blend(blend_id):
    row = db.blends.get(blend_id)
    if row is None:
        fail("ERR_BLEND_NOT_FOUND", "Blend %s does not exist" % blend_id)
    return row


def get_track(track_id):
    row = db.tracks.get(track_id)
    if row is None:
        fail("ERR_TRACK_NOT_FOUND", "Track %s does not exist" % track_id)
    return row


def get_shipment(shipment_id):
    row = db.shipments.get(shipment_id)
    if row is None:
        fail("ERR_SHIPMENT_NOT_FOUND", "Shipment %s does not exist" % shipment_id)
    return row


def get_sale(sale_id):
    row = db.sales.get(sale_id)
    if row is None:
        fail("ERR_SALE_NOT_FOUND", "Sale %s does not exist" % sale_id)
    return row


def get_rin(rin_id):
    row = db.rins.get(rin_id)
    if row is None:
        fail("ERR_RIN_BATCH_NOT_FOUND", "RIN batch %s does not exist" % rin_id)
    return row


def get_project(project_id):
    row = db.projects.get(project_id)
    if row is None:
        fail("ERR_CARBON_PROJECT_NOT_FOUND",
             "Carbon project %s does not exist" % project_id)
    return row


def get_position(position_id):
    row = db.positions.get(position_id)
    if row is None:
        fail("ERR_HEDGE_POSITION_NOT_FOUND",
             "Hedge position %s does not exist" % position_id)
    return row


def get_condition(condition_id):
    row = db.conditions.get(condition_id)
    if row is None:
        fail("ERR_PERMIT_CONDITION_NOT_FOUND",
             "Permit condition %s does not exist" % condition_id)
    return row


def unique(collection, field, value):
    for row in collection.values():
        if row[field] == value:
            fail("ERR_DUPLICATE_CODE", "%s %s is already in use" % (field, value))


def require_not_suspended():
    if derive.compliance_posture() == "SUSPENDED":
        fail("ERR_PLANT_SUSPENDED",
             "The plant is SUSPENDED and may not run this operation")


def require_tank_in_service(tank):
    if tank["service_status"] != "IN_SERVICE":
        fail("ERR_TANK_NOT_IN_SERVICE",
             "Tank %s is %s" % (tank["tank_code"], tank["service_status"]))


def require_product_type(tank, expected):
    if tank["product_type"] != expected:
        fail("ERR_TANK_PRODUCT_TYPE_MISMATCH",
             "Tank %s holds %s, expected %s"
             % (tank["tank_code"], tank["product_type"], expected))


def blend_conflicts(destination_tank, window_start, occupancy_end, exclude_id=None):
    """Closed intervals with exclusive occupancy: touching endpoints conflict."""
    for blend in db.blends.values():
        if blend["destination_tank_id"] != destination_tank["id"]:
            continue
        if blend["status"] != "SCHEDULED":
            continue
        if exclude_id is not None and blend["id"] == exclude_id:
            continue
        if calc.closed_intervals_conflict(
                at_second(window_start), at_second(occupancy_end),
                at_second(blend["window_start"]), at_second(blend["occupancy_end"])):
            return blend
    return None
