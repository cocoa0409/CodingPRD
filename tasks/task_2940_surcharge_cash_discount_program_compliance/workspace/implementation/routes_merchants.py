"""Merchants, the documented-cost chain and terminal provisioning."""

from decimal import Decimal

from flask import Blueprint

import auth
import calc
import listing
import serialize
import validation as v
from auth import authorize, check_merchant_ownership
from envelope import created, ok
from errors import ApiError
from store import db, base_row, touch
from validation import as_int, as_decimal, as_string, parse_body

bp = Blueprint("merchants", __name__)

DOC_STATES = ("ACTIVE", "SUPERSEDED")


@bp.post("/merchants")
def create_merchant():
    authorize(["PlatformAdmin"])
    body, malformed = parse_body()
    if malformed:
        raise v.bad("The request body must be a JSON object.")
    v.require_present(body, ["jurisdiction_id", "legal_name", "mcc"])
    jurisdiction_id = as_string(body["jurisdiction_id"], "jurisdiction_id", 1)
    legal_name = as_string(body["legal_name"], "legal_name", 1, 200)
    mcc = as_string(body["mcc"], "mcc", 4, 4)
    if not v.MCC.match(mcc):
        raise v.bad("mcc must be exactly four digits.")

    auth.get_jurisdiction(jurisdiction_id)

    row = base_row()
    row.update({
        "jurisdiction_id": jurisdiction_id,
        "legal_name": legal_name,
        "mcc": mcc,
    })
    db.merchants[row["id"]] = row
    return created(serialize.merchant(row))


@bp.get("/merchants/<merchant_id>")
def read_merchant(merchant_id):
    authorize(auth.READ_ROLES)
    return ok(serialize.merchant(auth.get_merchant(merchant_id)))


@bp.get("/merchants")
def list_merchants():
    authorize(auth.READ_ROLES)
    rows = listing.filtered(list(db.merchants.values()), [
        (listing.arg("jurisdiction_id"), "jurisdiction_id"),
        (listing.arg("mcc"), "mcc"),
    ])
    return listing.list_response(rows, serialize.merchant)


# --------------------------------------------------------- cost documentation
@bp.post("/merchants/<merchant_id>/cost-documentations")
def file_cost_documentation(merchant_id):
    actor = authorize(["ComplianceOfficer"])
    merchant = auth.get_merchant(merchant_id)
    body, malformed = parse_body()
    if malformed:
        raise v.bad("The request body must be a JSON object.")
    v.require_present(body, ["base_mdr_pct", "assessment_pct", "per_item_fee_cents",
                            "evidence_uri", "expected_merchant_version"])
    base_mdr_pct = as_decimal(body["base_mdr_pct"], "base_mdr_pct",
                              minimum=Decimal(0), maximum=Decimal(100), max_decimals=4)
    assessment_pct = as_decimal(body["assessment_pct"], "assessment_pct",
                                minimum=Decimal(0), maximum=Decimal(100), max_decimals=4)
    per_item_fee_cents = as_int(body["per_item_fee_cents"], "per_item_fee_cents", 0, 100000)
    evidence_uri = as_string(body["evidence_uri"], "evidence_uri", 1, 300)
    expected = as_int(body["expected_merchant_version"], "expected_merchant_version", 0)

    if expected != merchant["version"]:
        raise ApiError("ERR_STALE_MERCHANT_VERSION",
                       "expected_merchant_version %d does not match the merchant's current version %d."
                       % (expected, merchant["version"]))

    average_ticket_cents = calc.average_ticket_snapshot(merchant["id"])
    documented = calc.documented_cost_pct(base_mdr_pct, assessment_pct,
                                          per_item_fee_cents, average_ticket_cents)

    row = base_row()
    row.update({
        "merchant_id": merchant["id"],
        "base_mdr_pct": base_mdr_pct,
        "assessment_pct": assessment_pct,
        "per_item_fee_cents": per_item_fee_cents,
        "evidence_uri": evidence_uri,
        "average_ticket_cents": average_ticket_cents,
        "documented_cost_pct": documented,
        "attested_by_user_id": actor.user_id,
        "effective_from": db.now(),
        "state": "ACTIVE",
        "superseded_at": None,
    })

    for doc in sorted([d for d in db.cost_documentations.values()
                       if d["merchant_id"] == merchant["id"]],
                      key=lambda d: (d["created_at"], d["_seq"])):
        if doc["state"] == "ACTIVE":
            doc["state"] = "SUPERSEDED"
            doc["superseded_at"] = db.now()
            touch(doc)

    db.cost_documentations[row["id"]] = row
    touch(merchant)
    return created(serialize.cost_documentation(row))


@bp.get("/cost-documentations/<doc_id>")
def read_cost_documentation(doc_id):
    authorize(auth.READ_ROLES)
    return ok(serialize.cost_documentation(auth.get_cost_documentation(doc_id)))


@bp.get("/cost-documentations")
def list_cost_documentations():
    authorize(auth.READ_ROLES)
    rows = listing.filtered(list(db.cost_documentations.values()), [
        (listing.arg("merchant_id"), "merchant_id"),
        (listing.enum_arg("state", DOC_STATES), "state"),
    ])
    return listing.list_response(rows, serialize.cost_documentation)


# ------------------------------------------------------- terminal provisioning
@bp.post("/merchants/<merchant_id>/terminals")
def provision_terminal(merchant_id):
    actor = authorize(["MerchantOperator"])
    merchant = auth.get_merchant(merchant_id)
    check_merchant_ownership(actor, merchant["id"])
    body, malformed = parse_body()
    if malformed:
        raise v.bad("The request body must be a JSON object.")
    v.require_present(body, ["serial_number"])
    serial_number = as_string(body["serial_number"], "serial_number", 1, 40)

    for term in db.terminals.values():
        if term["merchant_id"] == merchant["id"] and term["serial_number"] == serial_number:
            raise ApiError("ERR_DUPLICATE_TERMINAL_SERIAL",
                           "This merchant already holds a terminal with serial_number %s." % serial_number)

    row = base_row()
    row.update({
        "merchant_id": merchant["id"],
        "program_id": None,
        "serial_number": serial_number,
        "debit_exclusion_enabled": False,
        "bin_table_version": None,
        "state": "PROVISIONED",
        "quarantine_reason": "NONE",
        "last_configured_at": None,
    })
    db.terminals[row["id"]] = row
    return created(serialize.terminal(row))
