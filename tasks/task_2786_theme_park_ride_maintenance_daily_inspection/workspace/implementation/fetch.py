"""Row lookups for path identifiers (ladder priority 3) and body foreign keys
(ladder priority 4)."""

import store
from errors import (
    fail,
    ERR_ATTRACTION_NOT_FOUND,
    ERR_COMPONENT_NOT_FOUND,
    ERR_TEMPLATE_NOT_FOUND,
    ERR_CHECKLIST_ITEM_NOT_FOUND,
    ERR_INSPECTION_NOT_FOUND,
    ERR_ITEM_RESULT_NOT_FOUND,
    ERR_BULLETIN_NOT_FOUND,
    ERR_BULLETIN_ACTION_NOT_FOUND,
    ERR_DOWNTIME_EVENT_NOT_FOUND,
    ERR_REQUISITION_NOT_FOUND,
    ERR_CERTIFICATION_NOT_FOUND,
    ERR_INCIDENT_NOT_FOUND,
    ERR_SHOP_BAY_NOT_FOUND,
    ERR_WORK_ORDER_NOT_FOUND,
)

ERROR_FOR = {
    "attractions": ERR_ATTRACTION_NOT_FOUND,
    "components": ERR_COMPONENT_NOT_FOUND,
    "templates": ERR_TEMPLATE_NOT_FOUND,
    "checklist_items": ERR_CHECKLIST_ITEM_NOT_FOUND,
    "inspections": ERR_INSPECTION_NOT_FOUND,
    "item_results": ERR_ITEM_RESULT_NOT_FOUND,
    "bulletins": ERR_BULLETIN_NOT_FOUND,
    "bulletin_actions": ERR_BULLETIN_ACTION_NOT_FOUND,
    "downtime_events": ERR_DOWNTIME_EVENT_NOT_FOUND,
    "requisitions": ERR_REQUISITION_NOT_FOUND,
    "certifications": ERR_CERTIFICATION_NOT_FOUND,
    "incidents": ERR_INCIDENT_NOT_FOUND,
    "shop_bays": ERR_SHOP_BAY_NOT_FOUND,
    "work_orders": ERR_WORK_ORDER_NOT_FOUND,
}


def maybe(collection, ident):
    if not isinstance(ident, str):
        return None
    return getattr(store.db, collection).get(ident)


def must(collection, ident):
    """Resolve an identifier or raise the collection's 404."""
    row = maybe(collection, ident)
    if row is None:
        fail(ERROR_FOR[collection], "No such resource: %s." % (ident,))
    return row


def fk(collection, ident):
    """Resolve an optional body foreign key. A null/absent value is left for
    the request-shape rung to complain about."""
    if ident is None:
        return None
    return must(collection, ident)


def attraction(ident):
    return must("attractions", ident)


def component(ident):
    return must("components", ident)


def template(ident):
    return must("templates", ident)


def checklist_item(ident):
    return must("checklist_items", ident)


def inspection(ident):
    return must("inspections", ident)


def item_result(ident):
    return must("item_results", ident)


def bulletin(ident):
    return must("bulletins", ident)


def bulletin_action(ident):
    return must("bulletin_actions", ident)


def downtime_event(ident):
    return must("downtime_events", ident)


def requisition(ident):
    return must("requisitions", ident)


def certification(ident):
    return must("certifications", ident)


def incident(ident):
    return must("incidents", ident)


def shop_bay(ident):
    return must("shop_bays", ident)


def work_order(ident):
    return must("work_orders", ident)


def children(collection, field, value):
    return [r for r in store.rows(collection) if r.get(field) == value]
