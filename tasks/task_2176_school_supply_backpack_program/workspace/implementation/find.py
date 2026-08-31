"""Identifier resolution with the per-entity not-found code (PRD §2.6)."""
from db import db
from errors import ApiError


def _get(collection, key, error_id):
    if not isinstance(key, str):
        raise ApiError(error_id)
    rec = collection.get(key)
    if rec is None:
        raise ApiError(error_id)
    return rec


def school(key):
    return _get(db.schools, key, "ERR_SCHOOL_NOT_FOUND")


def supply_item(key):
    return _get(db.supply_items, key, "ERR_SUPPLY_ITEM_NOT_FOUND")


def spec(key):
    return _get(db.grade_kit_specs, key, "ERR_KIT_SPEC_NOT_FOUND")


def spec_line(key):
    return _get(db.kit_spec_lines, key, "ERR_KIT_SPEC_NOT_FOUND")


def cycle(key):
    return _get(db.drive_cycles, key, "ERR_DRIVE_CYCLE_NOT_FOUND")


def site(key):
    return _get(db.collection_sites, key, "ERR_COLLECTION_SITE_NOT_FOUND")


def batch(key):
    return _get(db.donation_batches, key, "ERR_DONATION_BATCH_NOT_FOUND")


def position(key):
    return _get(db.inventory_positions, key, "ERR_INVENTORY_POSITION_NOT_FOUND")


def donation(key):
    return _get(db.cash_donations, key, "ERR_CASH_DONATION_NOT_FOUND")


def order(key):
    return _get(db.purchase_orders, key, "ERR_PURCHASE_ORDER_NOT_FOUND")


def volunteer_event(key):
    return _get(db.volunteer_events, key, "ERR_VOLUNTEER_EVENT_NOT_FOUND")


def distribution_event(key):
    return _get(db.distribution_events, key, "ERR_DISTRIBUTION_EVENT_NOT_FOUND")


def registration(key):
    return _get(db.student_registrations, key, "ERR_REGISTRATION_NOT_FOUND")


def teacher_request(key):
    return _get(db.teacher_requests, key, "ERR_TEACHER_REQUEST_NOT_FOUND")
