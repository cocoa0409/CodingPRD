"""Offeror register and debarment — PRD 3.3."""
from auth import ALL_ROLES, fetch, guard
from envelope import created, listing, ok
from errors import ApiError
from logic import ordered
from router import route
from shape import body, req_int, req_str
from store import db, insert, touch

DEBAR_CASCADE_STATES = ("SUBMITTED", "UNDER_REVIEW", "REVISION_REQUESTED", "SCORED")


@route("/offerors", methods=["POST"])
def offerors_create():
    guard("ProgramAdministrator")
    data = body()
    row = {
        "legal_name": req_str(data, "legal_name"),
        "contact_email": req_str(data, "contact_email"),
        "bond_capacity_cents": req_int(data, "bond_capacity_cents", minimum=1),
        "status": "ELIGIBLE",
    }
    return created(insert(db.offerors, row))


@route("/offerors/<offeror_id>/debar", methods=["POST"])
def offerors_debar(offeror_id):
    guard("ProgramAdministrator")
    offeror = fetch(db.offerors, offeror_id, "ERR_OFFEROR_NOT_FOUND")
    if offeror["status"] != "ELIGIBLE":
        raise ApiError("ERR_OFFEROR_STATUS_INVALID",
                       "Offeror status %s cannot be debarred" % offeror["status"])
    offeror["status"] = "DEBARRED"
    touch(offeror)
    for proposal in ordered([p for p in db.proposals.values()
                             if p["offeror_id"] == offeror_id]):
        if proposal["status"] in DEBAR_CASCADE_STATES:
            proposal["status"] = "WITHDRAWN"
            touch(proposal)
    return ok(offeror)


@route("/offerors", methods=["GET"])
def offerors_list():
    guard(*ALL_ROLES)
    return listing(db.offerors, ("status",))


@route("/offerors/<offeror_id>", methods=["GET"])
def offerors_read(offeror_id):
    guard(*ALL_ROLES)
    return ok(fetch(db.offerors, offeror_id, "ERR_OFFEROR_NOT_FOUND"))
