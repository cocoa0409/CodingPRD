"""Identifier resolution with the four-way not-found split (PRD 2.9)."""
from db import db
from errors import ApiError


def project(pid):
    row = db.projects.get(pid)
    if row is None:
        raise ApiError("ERR_PROJECT_NOT_FOUND", "project '%s' does not exist" % pid)
    return row


def work_package(wid):
    row = db.work_packages.get(wid)
    if row is None:
        raise ApiError(
            "ERR_WORK_PACKAGE_NOT_FOUND", "work package '%s' does not exist" % wid
        )
    return row


def subcontract(sid):
    row = db.subcontracts.get(sid)
    if row is None:
        raise ApiError(
            "ERR_SUBCONTRACT_NOT_FOUND", "subcontract '%s' does not exist" % sid
        )
    return row


def change_event(cid):
    row = db.change_events.get(cid)
    if row is None:
        raise ApiError(
            "ERR_CHANGE_EVENT_NOT_FOUND", "change event '%s' does not exist" % cid
        )
    return row


def resource(collection, rid, label="resource"):
    row = collection.get(rid)
    if row is None:
        raise ApiError("ERR_RESOURCE_NOT_FOUND", "%s '%s' does not exist" % (label, rid))
    return row


def estimate(eid):
    return resource(db.estimates, eid, "estimate")


def proposal(pid):
    return resource(db.proposals, pid, "gmp proposal")


def qualification_item(qid):
    return resource(db.qualification_items, qid, "qualification item")


def bid(bid_id):
    return resource(db.bids, bid_id, "self perform bid")


def draw(did):
    return resource(db.draws, did, "contingency draw")


def cost_report(rid):
    return resource(db.cost_reports, rid, "cost report")


# ------------------------------------------------------------ child helpers

def project_of_work_package(wp):
    return db.projects.get(wp["project_id"])


def project_of_subcontract(sub):
    wp = db.work_packages.get(sub["work_package_id"])
    if wp is None:
        return None
    return db.projects.get(wp["project_id"])


def project_of_proposal(prop):
    return db.projects.get(prop["project_id"])


def project_of_qualification_item(item):
    prop = db.proposals.get(item["gmp_proposal_id"])
    if prop is None:
        return None
    return db.projects.get(prop["project_id"])


def rows_of(collection, predicate):
    from db import sorted_rows

    return sorted_rows([r for r in collection.values() if predicate(r)])
