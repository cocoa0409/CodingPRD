"""Violation reports, investigation and adjudication (PRD 3.5)."""

from flask import Blueprint, request

import clock
import constants as C
import db
import guards
import middleware as mw
import response
import serializers as ser
import validators as v
from errors import ApiError
from services import posture

bp = Blueprint("violations", __name__)


@bp.post("/violations")
@mw.require(C.ROLE_INVESTIGATOR, C.ROLE_OFFICER)
def file_violation():
    data = v.body()
    seller = guards.body_fk(db.SELLERS, data.get("seller_id"), "ERR_SELLER_NOT_FOUND")
    rule = guards.body_fk(db.POLICY_RULES, data.get("policy_rule_id"),
                          "ERR_POLICY_RULE_NOT_FOUND")
    listing = guards.body_fk(db.LISTINGS, data.get("listing_id"), "ERR_LISTING_NOT_FOUND")

    v.req_str(data, "seller_id", 1, None)
    v.req_str(data, "policy_rule_id", 1, None)
    if v.present(data, "listing_id"):
        v.req_str(data, "listing_id", 1, None)
    reporter_type = v.req_enum(data, "reporter_type", C.REPORTER_TYPES)
    evidence_reference = v.req_str(data, "evidence_reference", 3, 64)
    if seller is None:
        raise ApiError("ERR_SELLER_NOT_FOUND")
    if rule is None:
        raise ApiError("ERR_POLICY_RULE_NOT_FOUND")

    guards.ensure_not_banned(seller)

    if rule["removal_scope"] == "LISTING" and listing is None:
        raise ApiError("ERR_LISTING_REQUIRED_FOR_SCOPE")
    if listing is not None and listing["seller_id"] != seller["id"]:
        raise ApiError("ERR_LISTING_SELLER_MISMATCH")
    if rule["category"] == "INTELLECTUAL_PROPERTY" and reporter_type != "RIGHTS_OWNER":
        raise ApiError("ERR_REPORTER_NOT_ELIGIBLE")

    row = db.new_row(
        "violation",
        seller_id=seller["id"],
        policy_rule_id=rule["id"],
        listing_id=listing["id"] if listing is not None else None,
        reporter_type=reporter_type,
        evidence_reference=evidence_reference,
        state="REPORTED",
        auto_generated=False,
        detected_at=clock.now(),
        adjudicated_at=None,
        decision_note=None,
    )
    db.VIOLATIONS[row["id"]] = row
    return response.one(row, ser.violation, 201)


@bp.get("/violations")
@mw.require(C.ROLE_INVESTIGATOR, C.ROLE_REVIEWER, C.ROLE_OFFICER)
def list_violations():
    limit, offset = v.pagination()
    rows = db.sorted_rows(db.VIOLATIONS)
    for field in ("seller_id", "policy_rule_id", "listing_id", "state"):
        if field in request.args:
            wanted = request.args.get(field)
            rows = [r for r in rows if r.get(field) == wanted]
    page, total = response.paginate(rows, limit, offset)
    return response.many(page, ser.violation, limit, offset, total)


@bp.get("/violations/<violation_id>")
@mw.require(C.ROLE_INVESTIGATOR, C.ROLE_REVIEWER, C.ROLE_OFFICER)
def read_violation(violation_id):
    row = guards.violation(violation_id)
    return response.one(row, ser.violation, 200)


@bp.post("/violations/<violation_id>/open-investigation")
@mw.require(C.ROLE_INVESTIGATOR)
def open_investigation(violation_id):
    row = guards.violation(violation_id)
    seller = db.SELLERS[row["seller_id"]]
    guards.ensure_not_banned(seller)
    if row["state"] != "REPORTED":
        raise ApiError("ERR_INVALID_STATE")

    db.set_field(row, "state", "UNDER_INVESTIGATION")
    posture.recompute(seller)
    db.mark_dirty(seller)
    return response.one(row, ser.violation, 200)


@bp.post("/violations/<violation_id>/adjudicate")
@mw.require(C.ROLE_INVESTIGATOR)
def adjudicate_violation(violation_id):
    row = guards.violation(violation_id)
    data = v.body()
    outcome = v.req_enum(data, "outcome", C.VIOLATION_OUTCOMES)
    decision_note = v.opt_str(data, "decision_note")
    seller = db.SELLERS[row["seller_id"]]
    guards.ensure_not_banned(seller)
    if row["state"] != "UNDER_INVESTIGATION":
        raise ApiError("ERR_INVALID_STATE")

    db.set_field(row, "state", outcome)
    db.set_field(row, "adjudicated_at", clock.now())
    db.set_field(row, "decision_note", decision_note)
    posture.recompute(seller)
    return response.one(row, ser.violation, 200)
