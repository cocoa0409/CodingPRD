"""Counterfeit, damaged and obsolete notes: quarantine and assessment outcomes."""
from flask import Blueprint

import calc
from core import (
    S,
    actor,
    body,
    clock,
    endpoint,
    fail,
    listing,
    need,
    need_currency,
    new_row,
    now_str,
    ok,
    opt_str,
    public,
    req_enum,
    req_int,
    req_str,
    rhu,
    store,
    touch,
)

bp = Blueprint("notes", __name__)

READERS = ("PlatformAdmin", "TreasuryOfficer", "BranchManager", "BranchTeller", "ComplianceOfficer")

PERMITTED_OUTCOMES = {
    "SUSPECTED_COUNTERFEIT": ("CONFISCATED",),
    "DAMAGED": ("RETURNED", "EXCHANGED_AT_DISCOUNT"),
    "OBSOLETE_SERIES": ("RETURNED",),
}


@bp.post("/note-assessments")
@endpoint(["BranchTeller", "BranchManager"])
def create_assessment():
    b = body()
    branch = need("Branch", req_str(b, "branch_id"))
    position = need("InventoryPosition", req_str(b, "inventory_position_id"))
    transaction = need("ExchangeTransaction", req_str(b, "exchange_transaction_id"))
    denomination = req_int(b, "denomination_minor_units", minimum=1)
    note_count = req_int(b, "note_count", minimum=1)
    defect_type = req_enum(
        b, "defect_type", ("SUSPECTED_COUNTERFEIT", "DAMAGED", "OBSOLETE_SERIES")
    )
    serial_reference = opt_str(b, "serial_reference")
    if position["branch_id"] != branch["id"]:
        fail("ERR_INVALID_REQUEST", "The cited position belongs to another branch.")
    entry = calc.mix_entry(position, denomination)
    if entry is None:
        fail(
            "ERR_INVALID_REQUEST",
            "denomination_minor_units is not present on the position's denomination_mix.",
        )
    if entry["available_note_count"] < note_count:
        fail("ERR_INVALID_REQUEST", "The position does not hold that many available notes.")

    row = new_row("NoteAssessment")
    row["branch_id"] = branch["id"]
    row["inventory_position_id"] = position["id"]
    row["exchange_transaction_id"] = transaction["id"]
    row["currency_code"] = position["currency_code"]
    row["denomination_minor_units"] = denomination
    row["note_count"] = note_count
    row["defect_type"] = defect_type
    row["serial_reference"] = serial_reference
    row["face_fx_minor_units"] = denomination * note_count
    row["status"] = "SUBMITTED"
    row["outcome"] = None
    row["recovery_usd_cents"] = None
    row["assessed_by_user_id"] = None
    store(row)

    entry["available_note_count"] -= note_count
    entry["quarantined_note_count"] += note_count
    calc.inventory_cascade(position, branch)
    touch(branch)
    return ok(public(row), 201)


@bp.post("/note-assessments/<assessment_id>/assess")
@endpoint(["BranchManager"])
def assess(assessment_id):
    assessment = need("NoteAssessment", assessment_id)
    b = body()
    outcome = req_enum(b, "outcome", ("CONFISCATED", "RETURNED", "EXCHANGED_AT_DISCOUNT"))
    opt_str(b, "assessment_note")
    # rank 5
    if assessment["status"] != "SUBMITTED":
        fail("ERR_ASSESSMENT_ALREADY_ASSESSED")
    # rank 11
    if outcome not in PERMITTED_OUTCOMES[assessment["defect_type"]]:
        fail("ERR_OUTCOME_NOT_PERMITTED_FOR_DEFECT")
    branch = need("Branch", assessment["branch_id"])
    position = need("InventoryPosition", assessment["inventory_position_id"])
    profile = need_currency(assessment["currency_code"])
    note_count = assessment["note_count"]
    entry = calc.ensure_mix_entry(position, assessment["denomination_minor_units"])

    card = None
    if outcome == "EXCHANGED_AT_DISCOUNT":
        # rank 12
        card = calc.require_effective_card(branch["id"], assessment["currency_code"], clock())

    assessment["status"] = "ASSESSED"
    assessment["outcome"] = outcome
    assessment["assessed_by_user_id"] = actor()

    if outcome == "CONFISCATED":
        entry["quarantined_note_count"] -= note_count
        entry["written_off_note_count"] += note_count
    elif outcome == "RETURNED":
        entry["quarantined_note_count"] -= note_count
    else:
        entry["quarantined_note_count"] -= note_count
        entry["available_note_count"] += note_count
        assessment["recovery_usd_cents"] = calc.damaged_note_recovery(
            assessment["face_fx_minor_units"], card, profile
        )
    touch(assessment)
    calc.inventory_cascade(position, branch)

    if outcome == "CONFISCATED":
        mid = calc.wholesale_mid(assessment["currency_code"])
        stamp = now_str()
        origin = S["ExchangeTransaction"].get(assessment["exchange_transaction_id"])
        calc.create_report(
            origin["customer_id"] if origin is not None else None,
            branch["id"],
            "COUNTERFEIT_SEIZURE",
            stamp,
            stamp,
            rhu(assessment["face_fx_minor_units"] * 1000000, mid),
            0,
            note_assessment_id=assessment["id"],
        )
        transaction = S["ExchangeTransaction"].get(assessment["exchange_transaction_id"])
        if transaction is not None and transaction["compliance_status"] == "PENDING":
            transaction["compliance_status"] = "FLAGGED"
            touch(transaction)
    return ok(public(assessment))


@bp.get("/note-assessments/<assessment_id>")
@endpoint(READERS)
def read_assessment(assessment_id):
    return ok(public(need("NoteAssessment", assessment_id)))


@bp.get("/note-assessments")
@endpoint(READERS)
def list_assessments():
    return listing(
        "NoteAssessment",
        {
            "branch_id": "branch_id",
            "inventory_position_id": "inventory_position_id",
            "exchange_transaction_id": "exchange_transaction_id",
            "defect_type": "defect_type",
            "status": "status",
        },
    )
