"""Benefit classifications, limitation levels and quantitative parity tests (PRD 3.2, 3.3)."""

from flask import Blueprint

import calc
import recompute
import serialize
import shape
from auth import guard
from enums import (ALL_ROLES, BENEFIT_SIDES, LIMITATION_TYPES, TEST_BASES)
from envelope import success
from helpers import list_response
from store import db, lookup_path, new_row, touch

bp = Blueprint("classifications", __name__)


@bp.route("/classifications/<classification_id>", methods=["GET"])
@guard(*ALL_ROLES)
def read_classification(classification_id):
    row = lookup_path(db.classifications, classification_id, "ERR_CLASSIFICATION_NOT_FOUND")
    return success(serialize.classification(row))


@bp.route("/classifications/<classification_id>/treatment-limitations", methods=["POST"])
@guard("PlanSponsor", "Administrator")
def create_treatment_limitation(classification_id):
    classification = lookup_path(db.classifications, classification_id,
                                 "ERR_CLASSIFICATION_NOT_FOUND")
    payload = shape.body()
    limitation_type = shape.req_enum(payload, "limitation_type", LIMITATION_TYPES)
    benefit_side = shape.req_enum(payload, "benefit_side", BENEFIT_SIDES)
    level_value = shape.req_decimal(payload, "level_value", 0, None)
    payments_cents = shape.req_int(payload, "projected_plan_payments_cents", 0, None)
    claims_count = shape.req_int(payload, "projected_claims_count", 0, None)

    plan_year = recompute.plan_year_of_classification(classification)
    recompute.gate_not_closed(plan_year)
    recompute.gate_open(plan_year)

    # Supersession, not editing: an identical ACTIVE row steps aside.
    for existing in db.treatment_limitations.values():
        if (existing["status"] == "ACTIVE"
                and existing["classification_id"] == classification_id
                and existing["limitation_type"] == limitation_type
                and existing["benefit_side"] == benefit_side
                and existing["level_value"] == level_value):
            existing["status"] = "SUPERSEDED"
            touch(existing)

    row = new_row({
        "classification_id": classification_id,
        "limitation_type": limitation_type,
        "benefit_side": benefit_side,
        "level_value": level_value,
        "projected_plan_payments_cents": payments_cents,
        "projected_claims_count": claims_count,
        "status": "ACTIVE",
    })
    db.treatment_limitations[row["id"]] = row
    return success(serialize.treatment_limitation(row), 201)


@bp.route("/classifications/<classification_id>/treatment-limitations", methods=["GET"])
@guard(*ALL_ROLES)
def list_treatment_limitations(classification_id):
    lookup_path(db.classifications, classification_id, "ERR_CLASSIFICATION_NOT_FOUND")
    rows = [r for r in db.treatment_limitations.values()
            if r["classification_id"] == classification_id]
    return list_response(rows, serialize.treatment_limitation,
                         ("limitation_type", "benefit_side", "status"))


@bp.route("/classifications/<classification_id>/parity-tests", methods=["POST"])
@guard("PlanSponsor", "ComplianceOfficer")
def create_parity_test(classification_id):
    classification = lookup_path(db.classifications, classification_id,
                                 "ERR_CLASSIFICATION_NOT_FOUND")
    payload = shape.body()
    limitation_type = shape.req_enum(payload, "limitation_type", LIMITATION_TYPES)
    basis = shape.req_enum(payload, "basis", TEST_BASES)

    plan_year = recompute.plan_year_of_classification(classification)
    recompute.gate_not_closed(plan_year)

    # Step 27: a zero denominator is refused rather than divided by.
    computed = calc.run_parity_test(classification_id, limitation_type, basis)

    for existing in db.parity_tests.values():
        if (existing["status"] == "COMPUTED"
                and existing["classification_id"] == classification_id
                and existing["limitation_type"] == limitation_type
                and existing["basis"] == basis):
            existing["status"] = "SUPERSEDED"
            touch(existing)

    row = new_row({
        "classification_id": classification_id,
        "limitation_type": limitation_type,
        "basis": basis,
        "advisory_only": basis == "CLAIMS_COUNT",
        "status": "COMPUTED",
    })
    row.update(computed)
    db.parity_tests[row["id"]] = row

    if plan_year is not None:
        recompute.recompute_plan_year(plan_year)
    return success(serialize.parity_test(row), 201)


@bp.route("/classifications/<classification_id>/parity-tests", methods=["GET"])
@guard(*ALL_ROLES)
def list_parity_tests(classification_id):
    lookup_path(db.classifications, classification_id, "ERR_CLASSIFICATION_NOT_FOUND")
    rows = [r for r in db.parity_tests.values()
            if r["classification_id"] == classification_id]
    return list_response(rows, serialize.parity_test,
                         ("limitation_type", "basis", "status"))
