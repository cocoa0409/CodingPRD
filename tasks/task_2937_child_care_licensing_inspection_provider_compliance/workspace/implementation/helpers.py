"""Shared route helpers: path resolution, list paging."""

import envelope
import store
from errors import ApiError

_NOT_FOUND = {
    "provider": "ERR_PROVIDER_NOT_FOUND",
    "inspector": "ERR_INSPECTOR_NOT_FOUND",
    "checklist_item": "ERR_CHECKLIST_ITEM_NOT_FOUND",
    "staff_member": "ERR_STAFF_MEMBER_NOT_FOUND",
    "background_check": "ERR_BACKGROUND_CHECK_NOT_FOUND",
    "roster": "ERR_ROSTER_NOT_FOUND",
    "inspection": "ERR_INSPECTION_NOT_FOUND",
    "violation": "ERR_VIOLATION_NOT_FOUND",
    "complaint": "ERR_COMPLAINT_NOT_FOUND",
    "cap": "ERR_CAP_NOT_FOUND",
    "action": "ERR_ENFORCEMENT_ACTION_NOT_FOUND",
    "amendment": "ERR_AMENDMENT_NOT_FOUND",
    "report": "ERR_INCIDENT_REPORT_NOT_FOUND",
    "posting": "ERR_POSTING_NOT_FOUND",
}

_COLLECTIONS = {
    "provider": lambda: store.providers,
    "inspector": lambda: store.inspectors,
    "checklist_item": lambda: store.checklist_items,
    "staff_member": lambda: store.staff_members,
    "background_check": lambda: store.background_checks,
    "roster": lambda: store.rosters,
    "inspection": lambda: store.inspections,
    "violation": lambda: store.violations,
    "complaint": lambda: store.complaints,
    "cap": lambda: store.caps,
    "action": lambda: store.actions,
    "amendment": lambda: store.amendments,
    "report": lambda: store.reports,
    "posting": lambda: store.postings,
}


def need(kind, identifier):
    collection = _COLLECTIONS[kind]()
    record = collection.get(identifier) if isinstance(identifier, str) else None
    if record is None:
        raise ApiError(_NOT_FOUND[kind], "No %s matches the supplied identifier." % kind)
    return record


def listing(rows, serializer, limit, offset):
    total = len(rows)
    page = rows[offset : offset + limit]
    return envelope.ok_list([serializer(r) for r in page], limit, offset, total)
