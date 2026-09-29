"""Customs entries: marking review, penalty assessment and mitigation (PRD 3.8)."""
from flask import Blueprint, request

import calc
import services
from auth import require_roles, scope_brand
from envelope import created, listing, ok
from errors import fail
from serializers import shipment_json
from store import create_row, db, ordered, touch
from util import dec, plus_days
from validate import (body, find_brand, find_label_spec, find_market, find_shipment,
                      find_style, market_of, present, req_enum, req_int, req_number,
                      req_string)

bp = Blueprint("shipments", __name__)

OUTCOMES = ("COMPLIANT", "DEFICIENT")
DEFICIENCY_CODES = ("MISSING_ORIGIN", "WRONG_ORIGIN", "MISSING_IDENTITY",
                    "NON_PERMANENT_PLACEMENT", "LANGUAGE_DEFICIENT")
READ_ROLES = ("ComplianceAdmin", "BrandAdmin", "CustomsOfficer", "Auditor")


@bp.post("/labeling/import-shipments")
def file_entry():
    require_roles("BrandAdmin", "ComplianceAdmin")
    payload = body()
    scope_brand(payload.get("importer_brand_id"))                  # ladder 4
    if present(payload, "importer_brand_id"):                      # ladder 5
        find_brand(payload["importer_brand_id"])
    if present(payload, "style_id"):
        find_style(payload["style_id"])
    if present(payload, "entry_market_code"):
        find_market(payload["entry_market_code"])
    importer_id = req_string(payload, "importer_brand_id")          # ladder 6
    style_id = req_string(payload, "style_id")
    entry_number = req_string(payload, "entry_number", min_len=1, max_len=24)
    quantity = req_int(payload, "quantity_units", minimum=1)
    value = req_number(payload, "declared_value_usd", 2, exclusive_min="0.00")
    market_code = req_string(payload, "entry_market_code")
    for other in db.import_shipments.values():                      # ladder 26
        if other["entry_number"] == entry_number:
            fail("ERR_DUPLICATE_ENTRY_NUMBER",
                 "That customs entry number has already been filed.")
    row = create_row(db.import_shipments, {
        "importer_brand_id": importer_id,
        "style_id": style_id,
        "corrective_label_spec_id": None,
        "entry_number": entry_number,
        "quantity_units": quantity,
        "declared_value_usd": value,
        "entry_market_code": market_code,
        "marking_state": "ENTRY_FILED",
        "deficiency_code": None,
        "review_decided_at": None,
        "redelivery_deadline_at": None,
        "posture_at_review": None,
        "assessment_basis": None,
        "penalty_ad_valorem_usd": dec("0.00"),
        "penalty_statutory_usd": dec("0.00"),
        "penalty_assessed_usd": dec("0.00"),
        "penalty_mitigated_usd": dec("0.00"),
        "corrected_units": 0,
    })
    return created(shipment_json(row))


@bp.post("/labeling/import-shipments/<sid>/marking-review")
def marking_review(sid):
    require_roles("CustomsOfficer")
    shipment = find_shipment(sid)                                   # ladder 3
    payload = body()
    outcome = req_enum(payload, "outcome", OUTCOMES)                 # ladder 6
    deficiency = None
    if outcome == "DEFICIENT":
        deficiency = req_enum(payload, "deficiency_code", DEFICIENCY_CODES)
    elif present(payload, "deficiency_code"):
        fail("ERR_INVALID_REQUEST",
             "deficiency_code must be absent on a compliant outcome.")
    if shipment["marking_state"] != "ENTRY_FILED":                  # ladder 9
        fail("ERR_SHIPMENT_STATE_INVALID",
             "Only a filed entry may take a marking review.")
    decided_at = db.now()
    shipment["review_decided_at"] = decided_at
    if outcome == "COMPLIANT":
        shipment["marking_state"] = "MARKING_COMPLIANT"
        touch(shipment)
        return ok(shipment_json(shipment))
    # PRD 3.8: the order of the assessment steps is normative.
    of_record = services.brand_of_record_row(shipment["importer_brand_id"])
    posture = calc.brand_posture(of_record["id"] if of_record else None,
                                 exclude_shipment_id=shipment["id"])
    regime = market_of(shipment["entry_market_code"])
    ad_valorem, statutory, basis, assessed = calc.marking_penalty_assessment(
        shipment, regime, posture)
    shipment["deficiency_code"] = deficiency
    shipment["posture_at_review"] = posture
    shipment["penalty_ad_valorem_usd"] = ad_valorem
    shipment["penalty_statutory_usd"] = statutory
    shipment["assessment_basis"] = basis
    shipment["penalty_assessed_usd"] = assessed
    shipment["penalty_mitigated_usd"] = dec("0.00")
    shipment["redelivery_deadline_at"] = plus_days(decided_at, calc.REDELIVERY_WINDOW_DAYS)
    shipment["marking_state"] = "REDELIVERY_ORDERED"
    touch(shipment)
    if of_record is not None:
        touch(of_record)
    return ok(shipment_json(shipment))


@bp.post("/labeling/import-shipments/<sid>/correct")
def correct_entry(sid):
    require_roles("BrandAdmin", "ComplianceAdmin")
    shipment = find_shipment(sid)                                   # ladder 3
    scope_brand(shipment["importer_brand_id"])                      # ladder 4
    payload = body()
    spec = None                                                     # ladder 5
    if present(payload, "corrective_label_spec_id"):
        spec = find_label_spec(payload["corrective_label_spec_id"])
    req_string(payload, "corrective_label_spec_id")                  # ladder 6
    corrected_units = req_int(payload, "corrected_units")
    if shipment["marking_state"] != "REDELIVERY_ORDERED":           # ladder 9
        fail("ERR_SHIPMENT_STATE_INVALID",
             "Only an entry under a redelivery order may be corrected.")
    if (spec["artifact_type"] != "PERMANENT_LABEL"                  # ladder 16
            or spec["style_id"] != shipment["style_id"]
            or spec["state"] != "PUBLISHED"):
        fail("ERR_REFERENCE_NOT_ELIGIBLE",
             "The corrective label must be a published permanent label of the same style.")
    if db.now() > shipment["redelivery_deadline_at"]:               # ladder 19
        fail("ERR_REDELIVERY_WINDOW_EXPIRED", "The redelivery window has closed.")
    if corrected_units <= 0 or corrected_units > shipment["quantity_units"]:  # ladder 31
        fail("ERR_INVALID_REQUEST",
             "corrected_units must be greater than zero and at most quantity_units.")
    shipment["penalty_mitigated_usd"] = calc.penalty_mitigation(
        shipment, corrected_units, db.now())
    shipment["corrective_label_spec_id"] = spec["id"]
    shipment["corrected_units"] = corrected_units
    shipment["marking_state"] = "MARKING_CORRECTED"
    touch(shipment)
    of_record = services.brand_of_record_row(shipment["importer_brand_id"])
    if of_record is not None:
        touch(of_record)
    return ok(shipment_json(shipment))


@bp.get("/labeling/import-shipments/<sid>")
def read_shipment(sid):
    require_roles(*READ_ROLES)
    return ok(shipment_json(find_shipment(sid)))


@bp.get("/labeling/import-shipments")
def list_shipments():
    require_roles(*READ_ROLES)
    rows = ordered(list(db.import_shipments.values()))
    args = request.args
    for field in ("importer_brand_id", "style_id", "corrective_label_spec_id",
                  "marking_state", "entry_market_code"):
        if args.get(field) is not None:
            rows = [r for r in rows if r[field] == args.get(field)]
    return listing(rows, shipment_json)
