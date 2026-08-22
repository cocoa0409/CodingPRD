"""Shared route helpers."""
from db import sort_key, store
from errors import not_found
from respond import listing
from serialize import public_list


def get_or_404(collection, rec_id, error_id):
    rec = collection.get(rec_id)
    if rec is None:
        raise not_found(error_id)
    return rec


def producer_or_404(producer_id):
    return get_or_404(store.producers, producer_id, "ERR_PRODUCER_NOT_FOUND")


def premises_or_404(premises_id):
    return get_or_404(store.premises, premises_id, "ERR_PREMISES_NOT_FOUND")


def supplier_or_404(supplier_id):
    return get_or_404(store.suppliers, supplier_id, "ERR_SUPPLIER_NOT_FOUND")


def lot_or_404(lot_id):
    return get_or_404(store.tag_lots, lot_id, "ERR_TAG_LOT_NOT_FOUND")


def tag_or_404(tag_id):
    return get_or_404(store.tags, tag_id, "ERR_TAG_NOT_FOUND")


def animal_or_404(animal_id):
    return get_or_404(store.animals, animal_id, "ERR_ANIMAL_NOT_FOUND")


def movement_or_404(movement_id):
    return get_or_404(store.movements, movement_id, "ERR_MOVEMENT_NOT_FOUND")


def trace_or_404(trace_id):
    return get_or_404(store.trace_requests, trace_id, "ERR_TRACE_REQUEST_NOT_FOUND")


def hold_or_404(hold_id):
    return get_or_404(store.hold_orders, hold_id, "ERR_HOLD_ORDER_NOT_FOUND")


def run_or_404(run_id):
    return get_or_404(store.recon_runs, run_id, "ERR_RECONCILIATION_RUN_NOT_FOUND")


def award_or_404(award_id):
    return get_or_404(store.awards, award_id, "ERR_AWARD_NOT_FOUND")


def page(rows, limit, offset, key=None):
    rows = sorted(rows, key=key or sort_key)
    total = len(rows)
    window = rows[offset:offset + limit]
    return listing(public_list(window), limit, offset, total)
