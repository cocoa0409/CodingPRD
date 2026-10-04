"""Jurisdiction clearances: submission, resubmission upsert, and regulatory
decisions with the disclosure-sufficiency guard and the formulation bubble-up
(PRD §3.1-3.2)."""

from flask import Blueprint, request

import auth
import calcs
import envelope
import serialization as ser
import store
import validation
from errors import api_err, invalid_state, not_found

bp = Blueprint("clearances", __name__)

DISCLOSURE_LEVELS = {"EXEMPT", "DECLARATION", "FULL_DISCLOSURE"}
DECISIONS = {"CLEARED", "CHANGES_REQUESTED", "REJECTED"}


def _get_clearance(cid):
    row = store.STORE["clearances"].get(cid)
    if row is None:
        raise not_found("JurisdictionClearance not found")
    return row


@bp.post("/stewardship/clearances")
def submit_clearance():
    _uid, role = auth.authenticate()
    auth.require_role(role, ["ProductManager"])
    payload = validation.get_payload()
    formulation_id = validation.req_str(payload, "formulation_id")
    jurisdiction_id = validation.req_str(payload, "jurisdiction_id")
    package_level = validation.req_enum(
        payload, "disclosure_package_level", DISCLOSURE_LEVELS)
    formulation = store.STORE["formulations"].get(formulation_id)
    if formulation is None:
        raise not_found("Formulation not found")
    jurisdiction = store.STORE["jurisdictions"].get(jurisdiction_id)
    if jurisdiction is None:
        raise not_found("Jurisdiction not found")
    # Priority 9: prohibited-substance screen runs before the duplicate check.
    if calcs.formulation_has_prohibited_component(formulation_id):
        raise api_err("ERR_SUBSTANCE_PROHIBITED",
                      "Formulation contains a PROHIBITED substance at > 0 ppm")
    existing = [c for c in store.STORE["clearances"].values()
                if c["formulation_id"] == formulation_id
                and c["jurisdiction_id"] == jurisdiction_id]
    # Priority 22: a live (SUBMITTED or CLEARED) clearance blocks duplicates.
    for clearance in existing:
        if clearance["status"] in ("SUBMITTED", "CLEARED"):
            raise api_err(
                "ERR_DUPLICATE_CLEARANCE",
                "A live clearance already exists for this "
                "(formulation, jurisdiction) pair")
    required_level = calcs.required_disclosure_level(formulation_id, jurisdiction)
    # Resubmission upsert: a pair sitting in CHANGES_REQUESTED or SUSPENDED is
    # resubmitted in place (HTTP 200); anything else is a first submission
    # (HTTP 201) — including pairs whose prior clearance is terminally
    # REJECTED.
    resubmission = None
    for clearance in sorted(existing, key=store.sort_key):
        if clearance["status"] in ("CHANGES_REQUESTED", "SUSPENDED"):
            resubmission = clearance
    if resubmission is not None:
        resubmission["disclosure_package_level"] = package_level
        resubmission["required_disclosure_level"] = required_level
        resubmission["submission_count"] += 1
        resubmission["status"] = "SUBMITTED"
        resubmission["decided_by"] = None
        resubmission["decided_at"] = None
        store.touch(resubmission)
        return envelope.success_object(ser.clearance(resubmission), 200)
    row = store.stamp_new({
        "formulation_id": formulation_id,
        "jurisdiction_id": jurisdiction_id,
        "disclosure_package_level": package_level,
        "required_disclosure_level": required_level,
        "status": "SUBMITTED",
        "submission_count": 1,
        "decided_by": None,
        "decided_at": None,
    })
    store.STORE["clearances"][row["id"]] = row
    return envelope.success_object(ser.clearance(row), 201)


@bp.get("/stewardship/clearances/<cid>")
def get_clearance(cid):
    _uid, role = auth.authenticate()
    auth.require_role(role, auth.ANY_ROLE)
    return envelope.success_object(ser.clearance(_get_clearance(cid)), 200)


@bp.get("/stewardship/clearances")
def list_clearances():
    _uid, role = auth.authenticate()
    auth.require_role(role, auth.ANY_ROLE)
    limit, offset = validation.parse_pagination()
    rows = validation.apply_filters(
        store.STORE["clearances"].values(), request.args,
        ["formulation_id", "jurisdiction_id", "status"])
    rows = sorted(rows, key=store.sort_key)
    page = rows[offset:offset + limit]
    return envelope.success_list(
        [ser.clearance(r) for r in page], len(rows), limit, offset)


@bp.post("/stewardship/clearances/<cid>/decision")
def decide_clearance(cid):
    uid, role = auth.authenticate()
    auth.require_role(role, ["RegulatoryManager"])
    payload = validation.get_payload()
    decision = validation.req_enum(payload, "decision", DECISIONS)
    clearance = _get_clearance(cid)
    if clearance["status"] != "SUBMITTED":
        raise invalid_state(
            "Only a SUBMITTED clearance can be decided")
    if decision == "CLEARED":
        # Priority 10: the submitted package must rank at least as high as the
        # required disclosure level (EXEMPT < DECLARATION < FULL_DISCLOSURE).
        if (calcs.DISCLOSURE_RANK[clearance["disclosure_package_level"]]
                < calcs.DISCLOSURE_RANK[clearance["required_disclosure_level"]]):
            raise api_err(
                "ERR_DISCLOSURE_INSUFFICIENT",
                "disclosure_package_level ranks below required_disclosure_level")
        clearance["status"] = "CLEARED"
        clearance["decided_by"] = uid
        clearance["decided_at"] = store.now()
        store.touch(clearance)
        formulation = store.STORE["formulations"][clearance["formulation_id"]]
        formulation["active_clearance_count"] += 1
        # Bubble-up: the first CLEARED clearance activates the formulation.
        if formulation["status"] == "DRAFT":
            formulation["status"] = "ACTIVE"
        store.touch(formulation)
    else:
        clearance["status"] = decision
        clearance["decided_by"] = uid
        clearance["decided_at"] = store.now()
        store.touch(clearance)
    return envelope.success_object(ser.clearance(clearance), 200)
