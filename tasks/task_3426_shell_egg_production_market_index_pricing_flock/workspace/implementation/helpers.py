"""Path-parameter resolution (priority 4, left-to-right) and shared list
rendering. Each missing resource raises its own 404 error id."""

from db import STORE
from errors import (
    ApiError,
    ERR_CAPITAL_PROJECT_NOT_FOUND,
    ERR_CERTIFICATION_NOT_FOUND,
    ERR_COMMITMENT_NOT_FOUND,
    ERR_COMPLEX_NOT_FOUND,
    ERR_CUSTOMER_NOT_FOUND,
    ERR_DEPOPULATION_ORDER_NOT_FOUND,
    ERR_DISEASE_EVENT_NOT_FOUND,
    ERR_FEED_CONTRACT_NOT_FOUND,
    ERR_FLOCK_NOT_FOUND,
    ERR_HOUSE_NOT_FOUND,
    ERR_ORDER_NOT_FOUND,
    ERR_PACKING_RUN_NOT_FOUND,
    ERR_SETTLEMENT_NOT_FOUND,
)
from util import pagination_args, success_list


def _get(table, key, error_id, label):
    ent = table.get(key)
    if ent is None:
        raise ApiError(error_id, 404, "%s not found: %s" % (label, key))
    return ent


def get_complex(cid):
    return _get(STORE.complexes, cid, ERR_COMPLEX_NOT_FOUND, "complex")


def get_house(hid):
    return _get(STORE.houses, hid, ERR_HOUSE_NOT_FOUND, "house")


def get_certification(cid):
    return _get(STORE.certifications, cid, ERR_CERTIFICATION_NOT_FOUND, "certification")


def get_flock(fid):
    return _get(STORE.flocks, fid, ERR_FLOCK_NOT_FOUND, "flock")


def get_disease_event(eid):
    return _get(STORE.disease_events, eid, ERR_DISEASE_EVENT_NOT_FOUND, "disease event")


def get_depop_order(oid):
    return _get(STORE.depopulation_orders, oid, ERR_DEPOPULATION_ORDER_NOT_FOUND, "depopulation order")


def get_customer(cid):
    return _get(STORE.customers, cid, ERR_CUSTOMER_NOT_FOUND, "customer")


def get_commitment(cid):
    return _get(STORE.commitments, cid, ERR_COMMITMENT_NOT_FOUND, "commitment")


def get_order(oid):
    return _get(STORE.orders, oid, ERR_ORDER_NOT_FOUND, "order")


def get_settlement(sid):
    return _get(STORE.settlements, sid, ERR_SETTLEMENT_NOT_FOUND, "settlement")


def get_feed_contract(fid):
    return _get(STORE.feed_contracts, fid, ERR_FEED_CONTRACT_NOT_FOUND, "feed contract")


def get_packing_run(pid):
    return _get(STORE.packing_runs, pid, ERR_PACKING_RUN_NOT_FOUND, "packing run")


def get_capital_project(pid):
    return _get(STORE.capital_projects, pid, ERR_CAPITAL_PROJECT_NOT_FOUND, "capital project")


def list_response(items, serializer):
    """Sort by creation order (created_at ASC; the logical clock ties break by
    insertion sequence), then paginate."""
    limit, offset = pagination_args()
    ordered = sorted(items, key=lambda e: e["_seq"])
    total = len(ordered)
    page = ordered[offset : offset + limit]
    return success_list([serializer(e) for e in page], total, limit, offset)
