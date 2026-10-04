"""Loan agreements (PRD 3.4/3.5): propose, counter rounds with OCC, accept
with terms validation + window overlap + FINAL premium, activate, close."""

from flask import Blueprint

import calc
import constants
import db
import serializers
import util
from envelope import listing, success
from errors import fail
from middleware import auth, get_or_404, require_role

bp = Blueprint("loan_agreements", __name__)

LOAN_READ_ROLES = ["PlatformAdmin", "Registrar", "LoansOfficer", "CommitteeChair", "BorrowerRep"]
NEGOTIATE_ROLES = ["LoansOfficer", "BorrowerRep"]


@bp.post("/campus/collection-objects/<oid>/loan-agreements")
def create_loan(oid):
    _uid, role = auth()
    require_role(role, ["LoansOfficer"])
    obj = get_or_404("collection_objects", oid, "CollectionObject")  # (3)
    b = util.body()
    # (9) request shape
    borrower_institution = util.req_str(b, "borrower_institution")
    loan_start_date = util.req_date(b, "loan_start_date")
    loan_end_date = util.req_date(b, "loan_end_date")
    if util.parse_date(loan_end_date) <= util.parse_date(loan_start_date):
        fail("ERR_INVALID_REQUEST", "loan_end_date must be strictly after loan_start_date")
    declared_value_cents = util.req_int(b, "declared_value_cents", minimum=0)
    coverage_type = util.req_enum(b, "coverage_type", constants.COVERAGE_TYPES)
    courier_required = util.req_bool(b, "courier_required")
    # (17) the object must stand IN_COLLECTION; overlap is NOT checked at
    # proposal time (only at acceptance).
    if obj["status"] != "IN_COLLECTION":
        fail("ERR_OBJECT_NOT_IN_COLLECTION", "The object is not IN_COLLECTION")
    l = db.new_entity(
        {
            "object_id": obj["id"],
            "borrower_institution": borrower_institution,
            "loan_start_date": loan_start_date,
            "loan_end_date": loan_end_date,
            "declared_value_cents": declared_value_cents,
            "coverage_type": coverage_type,
            "courier_required": courier_required,
            "status": "PROPOSED",
            "negotiated_round": 1,
            "premium_cents": None,  # locked at accept (FINAL variant)
        }
    )
    db.STORE["loan_agreements"][l["id"]] = l
    return success(serializers.loan_agreement(l), 201)


@bp.get("/campus/loan-agreements")
def list_loans():
    _uid, role = auth()
    require_role(role, LOAN_READ_ROLES)
    limit, offset = util.pagination()
    f_object = util.request.args.get("object_id")
    rows = []
    for l in db.all_sorted("loan_agreements"):
        if f_object is not None and l["object_id"] != f_object:
            continue
        rows.append(l)
    page = rows[offset : offset + limit]
    return listing([serializers.loan_agreement(l) for l in page], limit, offset, len(rows))


@bp.get("/campus/loan-agreements/<lid>")
def get_loan(lid):
    _uid, role = auth()
    require_role(role, LOAN_READ_ROLES)
    l = get_or_404("loan_agreements", lid, "LoanAgreement")
    return success(serializers.loan_agreement(l))


def _expected_version(b, field, current_version, stale_error):
    """OCC check: a present, well-formed expected version must equal the
    current one (else 412); presence/type problems surface at the shape stage."""
    ev = b.get(field)
    if util.is_int(ev) and ev != current_version:
        fail(stale_error, "The resource version has advanced; re-read and retry")


def _require_expected_version(b, field):
    if not util.is_int(b.get(field)):
        fail("ERR_INVALID_REQUEST", f"Field {field} is required and must be an integer")


@bp.post("/campus/loan-agreements/<lid>/counter")
def counter_loan(lid):
    _uid, role = auth()
    require_role(role, NEGOTIATE_ROLES)
    l = get_or_404("loan_agreements", lid, "LoanAgreement")
    b = util.body()
    # (5) transition legality is role-shaped: BorrowerRep counters PROPOSED
    # (-> COUNTERED); LoansOfficer counters COUNTERED (-> PROPOSED).
    if role == "BorrowerRep":
        if l["status"] != "PROPOSED":
            fail("ERR_INVALID_STATE", "The borrower may counter only a PROPOSED agreement")
        new_status = "COUNTERED"
    else:
        if l["status"] != "COUNTERED":
            fail("ERR_INVALID_STATE", "The loans officer may counter only a COUNTERED agreement")
        new_status = "PROPOSED"
    # OCC
    _expected_version(b, "expected_loan_version", l["version"], "ERR_STALE_LOAN_VERSION")
    # (9) request shape: expected_loan_version plus any provided term fields
    _require_expected_version(b, "expected_loan_version")
    new_start = l["loan_start_date"]
    new_end = l["loan_end_date"]
    if b.get("loan_start_date") is not None:
        new_start = util.req_date(b, "loan_start_date")
    if b.get("loan_end_date") is not None:
        new_end = util.req_date(b, "loan_end_date")
    if util.parse_date(new_end) <= util.parse_date(new_start):
        fail("ERR_INVALID_REQUEST", "loan_end_date must be strictly after loan_start_date")
    if b.get("declared_value_cents") is not None:
        util.req_int(b, "declared_value_cents", minimum=0)
    if b.get("coverage_type") is not None:
        util.req_enum(b, "coverage_type", constants.COVERAGE_TYPES)
    if b.get("courier_required") is not None:
        util.req_bool(b, "courier_required")
    # Provided term fields replace the current terms
    if b.get("loan_start_date") is not None:
        l["loan_start_date"] = new_start
    if b.get("loan_end_date") is not None:
        l["loan_end_date"] = new_end
    if b.get("declared_value_cents") is not None:
        l["declared_value_cents"] = b["declared_value_cents"]
    if b.get("coverage_type") is not None:
        l["coverage_type"] = b["coverage_type"]
    if b.get("courier_required") is not None:
        l["courier_required"] = b["courier_required"]
    l["status"] = new_status
    l["negotiated_round"] += 1
    db.touch(l)
    return success(serializers.loan_agreement(l))


@bp.post("/campus/loan-agreements/<lid>/accept")
def accept_loan(lid):
    _uid, role = auth()
    require_role(role, NEGOTIATE_ROLES)
    l = get_or_404("loan_agreements", lid, "LoanAgreement")
    b = util.body()
    # (5) transition legality: BorrowerRep accepts from PROPOSED; LoansOfficer
    # accepts from COUNTERED.
    if role == "BorrowerRep":
        if l["status"] != "PROPOSED":
            fail("ERR_INVALID_STATE", "The borrower may accept only a PROPOSED agreement")
    else:
        if l["status"] != "COUNTERED":
            fail("ERR_INVALID_STATE", "The loans officer may accept only a COUNTERED agreement")
    # OCC
    _expected_version(b, "expected_loan_version", l["version"], "ERR_STALE_LOAN_VERSION")
    _require_expected_version(b, "expected_loan_version")
    # (17) terms validation, pinned order (PRD 3.4: terms first, then overlap)
    if not l["courier_required"] and l["declared_value_cents"] >= constants.COURIER_MIN_DECLARED_VALUE_CENTS:
        fail("ERR_COURIER_REQUIRED", "A courier is required at this declared value")
    if l["coverage_type"] == "INDEMNITY":
        if l["declared_value_cents"] < constants.INDEMNITY_MIN_DECLARED_VALUE_CENTS:
            fail("ERR_INDEMNITY_MINIMUM_NOT_MET", "Indemnity coverage requires a higher declared value")
        if not l["courier_required"]:
            fail("ERR_INDEMNITY_REQUIRES_COURIER", "Indemnity coverage requires a courier")
    # (17) half-open window overlap against other AGREED/ACTIVE loans of the
    # same object; adjacency is allowed.
    s = util.parse_date(l["loan_start_date"])
    e = util.parse_date(l["loan_end_date"])
    for o in db.STORE["loan_agreements"].values():
        if o["id"] == l["id"] or o["object_id"] != l["object_id"]:
            continue
        if o["status"] not in ("AGREED", "ACTIVE"):
            continue
        if calc.half_open_overlap(
            s, e, util.parse_date(o["loan_start_date"]), util.parse_date(o["loan_end_date"])
        ):
            fail("ERR_LOAN_PERIOD_CONFLICT", "The loan window overlaps another agreed or active loan")
    # Premium: FINAL variant, locked at accept
    l["premium_cents"] = calc.loan_premium_final(
        l["declared_value_cents"], l["courier_required"], l["coverage_type"]
    )
    l["status"] = "AGREED"
    db.touch(l)
    return success(serializers.loan_agreement(l))


@bp.post("/campus/loan-agreements/<lid>/activate")
def activate_loan(lid):
    _uid, role = auth()
    require_role(role, ["LoansOfficer"])
    l = get_or_404("loan_agreements", lid, "LoanAgreement")
    if l["status"] != "AGREED":
        fail("ERR_INVALID_STATE", "Only an AGREED loan can be activated")
    # (17) an ACCEPTED OUTBOUND condition report is required to ship
    has_outbound = any(
        r["loan_id"] == l["id"] and r["report_kind"] == "OUTBOUND" and r["status"] == "ACCEPTED"
        for r in db.STORE["condition_reports"].values()
    )
    if not has_outbound:
        fail("ERR_CONDITION_REPORT_REQUIRED", "An ACCEPTED OUTBOUND condition report is required")
    obj = db.STORE["collection_objects"].get(l["object_id"])
    if obj is None or obj["status"] != "IN_COLLECTION":
        fail("ERR_OBJECT_NOT_IN_COLLECTION", "The object is not IN_COLLECTION")
    l["status"] = "ACTIVE"
    db.touch(l)
    obj["status"] = "OUT_ON_LOAN"
    db.touch(obj)
    return success(serializers.loan_agreement(l))


@bp.post("/campus/loan-agreements/<lid>/close")
def close_loan(lid):
    _uid, role = auth()
    require_role(role, ["LoansOfficer"])
    l = get_or_404("loan_agreements", lid, "LoanAgreement")
    if l["status"] != "ACTIVE":
        fail("ERR_INVALID_STATE", "Only an ACTIVE loan can be closed")
    # (17) an ACCEPTED RETURN condition report is required to register return
    accepted_returns = [
        r
        for r in db.STORE["condition_reports"].values()
        if r["loan_id"] == l["id"] and r["report_kind"] == "RETURN" and r["status"] == "ACCEPTED"
    ]
    if not accepted_returns:
        fail("ERR_CONDITION_REPORT_REQUIRED", "An ACCEPTED RETURN condition report is required")
    accepted_returns.sort(key=lambda r: r["_seq"])
    accepted = accepted_returns[-1]  # most recent ACCEPTED RETURN report governs
    l["status"] = "CLOSED"
    db.touch(l)
    obj = db.STORE["collection_objects"].get(l["object_id"])
    if obj is not None:
        obj["status"] = "UNDER_CONSERVATION" if accepted["damage_noted"] else "IN_COLLECTION"
        db.touch(obj)
    return success(serializers.loan_agreement(l))
