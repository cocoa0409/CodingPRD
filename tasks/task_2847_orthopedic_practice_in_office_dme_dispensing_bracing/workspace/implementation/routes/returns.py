"""Returns, inspection, refunds and refit encounters."""
from flask import Blueprint

from calc import refresh_shelf, restock_refund
from common import (authorize, body_json, fail, need_enum, now, opt_str,
                    paginate, respond_list, respond_object, whole_days)
from store import (RETURN_CONDITIONS, RETURN_REASONS, db, encounter_json,
                   encounter_returns, find_par_level, insert, lookup,
                   product_return_json, stamp, touch)
from routes.encounters import new_encounter_row

bp = Blueprint("returns", __name__)

RETURN_READ_ROLES = ["PracticeAdmin", "ComplianceOfficer", "InventoryManager",
                     "DmeFitter"]

RETURN_WINDOW_DAYS = {
    "POOR_FIT": 30,
    "PATIENT_REFUSED": 30,
    "DEFECT": 90,
    "WRONG_ITEM": 90,
}

REFIT_ELIGIBLE_REASONS = ("POOR_FIT", "WRONG_ITEM")
INSPECTED_STATUSES = ("RESTOCKED", "DESTROYED")


@bp.post("/dme/encounters/<encounter_id>/returns")
def create_return(encounter_id):
    authorize(["DmeFitter"])
    body = body_json()
    reason = need_enum(body, "reason", RETURN_REASONS)
    return_note = opt_str(body, "return_note")
    encounter = lookup("encounters", encounter_id, "ERR_ENCOUNTER_NOT_FOUND")
    existing = encounter_returns(encounter["id"])
    # Pinned carve-out 2: the clinical-state check runs only while the encounter
    # has no return yet, so a second request is diagnosed as a duplicate.
    if not existing and encounter["clinical_status"] != "DELIVERED":
        fail("ERR_INVALID_CLINICAL_STATE")
    days = whole_days(encounter["delivered_at"], now())
    if days > RETURN_WINDOW_DAYS[reason]:
        fail("ERR_RETURN_WINDOW_EXPIRED")
    if existing:
        fail("ERR_RETURN_ALREADY_EXISTS")
    row = stamp({
        "encounter_id": encounter["id"],
        "reason": reason,
        "return_note": return_note,
        "status": "REQUESTED",
        "quantity_returned": encounter["quantity"],
        "condition": None,
        "days_since_delivery": days,
        "restock_eligible": None,
        "restock_fee_pct": None,
        "device_component_cents": None,
        "fitting_component_cents": None,
        "device_refund_cents": None,
        "fitting_refund_cents": None,
        "refund_cents": None,
        "restock_fee_cents": None,
        "inspected_at": None,
        "refit_encounter_id": None,
    })
    insert("returns", row)
    encounter["clinical_status"] = "RETURN_PENDING"
    touch(encounter)
    return respond_object(product_return_json(row), 201)


@bp.get("/dme/encounters/<encounter_id>/returns")
def list_returns(encounter_id):
    authorize(RETURN_READ_ROLES)
    encounter = lookup("encounters", encounter_id, "ERR_ENCOUNTER_NOT_FOUND")
    rows = encounter_returns(encounter["id"])
    page, pagination = paginate(rows)
    return respond_list([product_return_json(r) for r in page], pagination, 200)


@bp.post("/dme/returns/<return_id>/inspection")
def inspect_return(return_id):
    authorize(["InventoryManager"])
    body = body_json()
    condition = need_enum(body, "condition", RETURN_CONDITIONS)
    row = lookup("returns", return_id, "ERR_RETURN_NOT_FOUND")
    if row["status"] != "REQUESTED":
        fail("ERR_INVALID_RETURN_STATE")
    encounter = db["encounters"].get(row["encounter_id"])
    product = db["products"].get(encounter["product_id"]) if encounter else None

    row["condition"] = condition
    row["inspected_at"] = now()
    money = restock_refund(row, encounter, product)
    row.update(money)
    row["status"] = "RESTOCKED" if money["restock_eligible"] else "DESTROYED"
    touch(row)

    if row["status"] == "RESTOCKED":
        shelf = find_par_level(encounter["clinic_id"], encounter["product_id"])
        if shelf is not None:
            shelf["on_hand_qty"] += row["quantity_returned"]
            touch(shelf)
            refresh_shelf(shelf)
    if encounter is not None:
        encounter["clinical_status"] = "RETURNED"
        encounter["financial_status"] = "REFUNDED"
        # patient_responsibility_cents is deliberately preserved
        encounter["billable_amount_cents"] = 0
        touch(encounter)
    return respond_object(product_return_json(row), 201)


@bp.post("/dme/returns/<return_id>/refit")
def issue_refit(return_id):
    # Carve-out: an unknown DmeFitter actor here is ERR_FITTER_NOT_FOUND (11).
    user_id, _ = authorize(["DmeFitter"], actor_check=False)
    fitter = lookup("fitters", user_id, "ERR_FITTER_NOT_FOUND")
    row = lookup("returns", return_id, "ERR_RETURN_NOT_FOUND")
    encounter = db["encounters"].get(row["encounter_id"])
    if encounter is not None and fitter["clinic_id"] != encounter["clinic_id"]:
        fail("ERR_CLINIC_SCOPE_MISMATCH")
    if row["status"] not in INSPECTED_STATUSES:
        fail("ERR_INVALID_RETURN_STATE")
    if encounter is not None and encounter["fitter_id"] == fitter["id"]:
        fail("ERR_REFIT_SAME_FITTER")
    if row["reason"] not in REFIT_ELIGIBLE_REASONS:
        fail("ERR_REFIT_REASON_NOT_ELIGIBLE")

    refit = new_encounter_row(encounter["clinic_id"], encounter["patient_id"],
                              encounter["product_id"],
                              encounter["ordering_physician_id"],
                              encounter["quantity"], encounter["service_date"])
    refit["refit_of_encounter_id"] = encounter["id"]
    refit["mn_diagnosis_code"] = encounter["mn_diagnosis_code"]
    refit["mn_functional_deficit"] = encounter["mn_functional_deficit"]
    refit["mn_expected_duration_months"] = encounter["mn_expected_duration_months"]
    refit["mn_signed_at"] = encounter["mn_signed_at"]
    refit["mn_physician_id"] = encounter["mn_physician_id"]
    refit["clinical_status"] = "DOCUMENTED"
    refit["financial_status"] = "UNVERIFIED"
    insert("encounters", refit)

    row["refit_encounter_id"] = refit["id"]
    row["status"] = "REFIT_ISSUED"
    touch(row)
    return respond_object(encounter_json(refit), 201)
