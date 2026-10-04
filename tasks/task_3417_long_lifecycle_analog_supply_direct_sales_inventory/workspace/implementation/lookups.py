# Existence lookups (validation priority row 3, PRD 2.8): entity-specific 404s.
from errors import (
    ApiError,
    ERR_ALLOCATION_RUN_NOT_FOUND,
    ERR_CAPACITY_POOL_NOT_FOUND,
    ERR_CUSTOMER_NOT_FOUND,
    ERR_DESIGN_WIN_NOT_FOUND,
    ERR_EOL_NOTICE_NOT_FOUND,
    ERR_LIFETIME_BUY_NOT_FOUND,
    ERR_ORDER_LINE_NOT_FOUND,
    ERR_ORDER_NOT_FOUND,
    ERR_PART_NOT_FOUND,
    ERR_REFERENCE_DESIGN_NOT_FOUND,
    ERR_SITE_QUALIFICATION_NOT_FOUND,
)
from store import store


def _get(table, entity_id, error_id, label):
    entity = table.get(entity_id) if isinstance(entity_id, str) else None
    if entity is None:
        raise ApiError(error_id, 404, "%s not found: %s" % (label, entity_id))
    return entity


def get_part(entity_id):
    return _get(store.parts, entity_id, ERR_PART_NOT_FOUND, "Part")


def get_customer(entity_id):
    return _get(store.customers, entity_id, ERR_CUSTOMER_NOT_FOUND, "Customer")


def get_order(entity_id):
    return _get(store.orders, entity_id, ERR_ORDER_NOT_FOUND, "SalesOrder")


def get_order_line(entity_id):
    return _get(store.order_lines, entity_id, ERR_ORDER_LINE_NOT_FOUND, "OrderLine")


def get_capacity_pool(entity_id):
    return _get(store.capacity_pools, entity_id, ERR_CAPACITY_POOL_NOT_FOUND, "CapacityPool")


def get_allocation_run(entity_id):
    return _get(store.allocation_runs, entity_id, ERR_ALLOCATION_RUN_NOT_FOUND, "AllocationRun")


def get_eol_notice(entity_id):
    return _get(store.eol_notices, entity_id, ERR_EOL_NOTICE_NOT_FOUND, "EolNotice")


def get_lifetime_buy(entity_id):
    return _get(store.lifetime_buys, entity_id, ERR_LIFETIME_BUY_NOT_FOUND, "LifetimeBuy")


def get_site_qualification(entity_id):
    return _get(store.site_qualifications, entity_id, ERR_SITE_QUALIFICATION_NOT_FOUND, "SiteQualification")


def get_reference_design(entity_id):
    return _get(store.reference_designs, entity_id, ERR_REFERENCE_DESIGN_NOT_FOUND, "ReferenceDesign")


def get_design_win(entity_id):
    return _get(store.design_wins, entity_id, ERR_DESIGN_WIN_NOT_FOUND, "DesignWin")
