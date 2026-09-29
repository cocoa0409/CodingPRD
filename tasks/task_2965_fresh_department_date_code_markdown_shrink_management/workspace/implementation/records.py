"""Common-field bookkeeping (PRD 2.4) and id lookups (PRD 2.5)."""
from flask import g

from db import db, new_id
from errors import ApiError
from util import fmt_instant


def _touched_set():
    marks = g.get("_touched")
    if marks is None:
        marks = set()
        g._touched = marks
    return marks


def new_record(collection, fields, common=True):
    """Create a row.  `version` starts at 1; created_at/updated_at read the
    logical clock, never the host wall clock."""
    stamp = fmt_instant(db.now())
    record = {"id": new_id()}
    record.update(fields)
    record["created_at"] = stamp
    if common:
        record["updated_at"] = stamp
        record["version"] = 1
    record["_seq"] = db.next_seq()
    collection[record["id"]] = record
    _touched_set().add(record["id"])
    return record


def touch(record):
    """Refresh updated_at and bump version once per request for this row."""
    if record is None or "version" not in record:
        return record
    marks = _touched_set()
    if record["id"] in marks:
        record["updated_at"] = fmt_instant(db.now())
        return record
    marks.add(record["id"])
    record["version"] = record["version"] + 1
    record["updated_at"] = fmt_instant(db.now())
    return record


def lookup(collection, record_id, error_id):
    if not isinstance(record_id, str) or record_id == "":
        raise ApiError(error_id, "%s does not exist" % record_id)
    record = collection.get(record_id)
    if record is None:
        raise ApiError(error_id, "No such resource: %s" % record_id)
    return record


def store_by_id(sid):
    return lookup(db.stores, sid, "ERR_STORE_NOT_FOUND")


def partner_by_id(pid):
    return lookup(db.partners, pid, "ERR_PARTNER_NOT_FOUND")


def ladder_by_id(lid):
    return lookup(db.ladders, lid, "ERR_LADDER_NOT_FOUND")


def department_by_id(did):
    return lookup(db.departments, did, "ERR_DEPARTMENT_NOT_FOUND")


def item_by_id(iid):
    return lookup(db.items, iid, "ERR_ITEM_NOT_FOUND")


def lot_by_id(lid):
    return lookup(db.lots, lid, "ERR_LOT_NOT_FOUND")


def label_by_id(lid):
    return lookup(db.labels, lid, "ERR_LABEL_NOT_FOUND")


def check_by_id(cid):
    return lookup(db.checks, cid, "ERR_CHECK_NOT_FOUND")


def pickup_by_id(pid):
    return lookup(db.pickups, pid, "ERR_PICKUP_NOT_FOUND")


def assignment_by_id(aid):
    return lookup(db.assignments, aid, "ERR_ASSIGNMENT_NOT_FOUND")


def shrink_event_by_id(sid):
    return lookup(db.shrink_events, sid, "ERR_SHRINK_EVENT_NOT_FOUND")


def audit_by_id(aid):
    return lookup(db.audits, aid, "ERR_AUDIT_NOT_FOUND")


def finding_by_id(fid):
    return lookup(db.findings, fid, "ERR_FINDING_NOT_FOUND")


def recommendation_by_id(rid):
    return lookup(db.recommendations, rid, "ERR_RECOMMENDATION_NOT_FOUND")


# --- graph walks -----------------------------------------------------------
def item_of_lot(lot):
    return db.items[lot["item_id"]]


def department_of_item(item):
    return db.departments[item["department_id"]]


def department_of_lot(lot):
    return department_of_item(item_of_lot(lot))


def ladder_of_department(department):
    return db.ladders.get(department["markdown_ladder_id"])


def lots_of_item(item_id):
    return [l for l in db.lots.values() if l["item_id"] == item_id]


def items_of_department(department_id):
    return [i for i in db.items.values() if i["department_id"] == department_id]


def lots_of_department(department_id):
    ids = set(i["id"] for i in items_of_department(department_id))
    return [l for l in db.lots.values() if l["item_id"] in ids]


def labels_of_lot(lot_id):
    return [l for l in db.labels.values() if l["lot_id"] == lot_id]


def assignments_of_pickup(pickup_id):
    return [a for a in db.assignments.values() if a["pickup_id"] == pickup_id]


def assignments_of_lot(lot_id):
    return [a for a in db.assignments.values() if a["lot_id"] == lot_id]


def shrink_events_of_lot(lot_id):
    return [e for e in db.shrink_events.values() if e["lot_id"] == lot_id]


def audits_of_department(department_id):
    return [a for a in db.audits.values() if a["department_id"] == department_id]


def findings_of_audit(audit_id):
    return [f for f in db.findings.values() if f["audit_id"] == audit_id]
