"""Subprocessor disclosure and analyst disposition (PRD 3.1)."""
from flask import Blueprint

from core import auth, envelope, logic, serialize, store, validate
from core.errors import ApiError
from core.validate import F

bp = Blueprint("subprocessors", __name__)


@bp.post("/subprocessors")
def disclose_subprocessor():
    user_id, role = auth.actor("VendorLiaison", "PrivacyOfficeAdmin")
    data = validate.body([
        F("vendor_id", "str"),
        F("name", "str", lo=1, hi=200, nonblank=True),
        F("country_code", "country"),
        F("data_categories", "enum_array", members=set(logic.ELEMENT_CODES), min_items=1),
        F("purpose", "str", lo=1, hi=500),
        F("sub_breach_notification_hours", "int", lo=1, hi=720),
        F("processor_vendor_id", "str", required=False),
    ])
    vendor = auth.need("vendor", data["vendor_id"])
    if "processor_vendor_id" in data:
        auth.need("vendor", data["processor_vendor_id"])
    if role == "VendorLiaison":
        auth.owner_or_403(user_id == vendor["id"])

    row = store.new_row({
        "vendor_id": vendor["id"],
        "processor_vendor_id": data.get("processor_vendor_id"),
        "name": data["name"],
        "country_code": data["country_code"],
        "data_categories": data["data_categories"],
        "purpose": data["purpose"],
        "sub_breach_notification_hours": data["sub_breach_notification_hours"],
        "status": "DISCLOSED",
        "reviewed_note": None,
    })
    store.subprocessors[row["id"]] = row
    logic.recompute_vendor(vendor)
    return envelope.created(serialize.subprocessor(row))


@bp.get("/subprocessors")
def list_subprocessors():
    auth.actor("PrivacyOfficeAdmin", "PrivacyAnalyst", "VendorLiaison")
    filters = envelope.query_filters({
        "vendor_id": None,
        "processor_vendor_id": None,
        "status": set(logic.SUBPROCESSOR_STATUSES),
        "country_code": None,
    })
    rows = list(store.subprocessors.values())
    for key in ("vendor_id", "processor_vendor_id", "status", "country_code"):
        if key in filters:
            rows = [r for r in rows if r[key] == filters[key]]
    return envelope.paged(store.ordered(rows), serialize.subprocessor)


@bp.get("/subprocessors/<subprocessor_id>")
def read_subprocessor(subprocessor_id):
    auth.actor("PrivacyOfficeAdmin", "PrivacyAnalyst", "VendorLiaison")
    return envelope.ok(serialize.subprocessor(auth.need("subprocessor", subprocessor_id)))


@bp.post("/subprocessors/<subprocessor_id>/review")
def review_subprocessor(subprocessor_id):
    auth.actor("PrivacyAnalyst")
    data = validate.body([
        F("disposition", "enum", members={"VERIFY", "FLAG", "REMOVE"}),
        F("reviewed_note", "str", required=False),
    ])
    row = auth.need("subprocessor", subprocessor_id)
    vendor = store.vendors[row["vendor_id"]]
    disposition = data["disposition"]

    # Rung 19: a removed disclosure refuses any further review.
    if row["status"] == "REMOVED":
        raise ApiError("ERR_SUBPROCESSOR_STATE_INVALID")

    # Rung 27 sits ABOVE applicability, so a VERIFY aimed at an already-flagged
    # row with weak terms reports the weaker terms (PRD 3.1).
    if disposition == "VERIFY":
        if row["sub_breach_notification_hours"] > vendor["breach_notification_hours"]:
            raise ApiError("ERR_SUBPROCESSOR_NOTIFICATION_TERMS_WEAKER")

    # Rung 41: applicability of the submitted disposition.
    if disposition == "VERIFY" and row["status"] != "DISCLOSED":
        raise ApiError("ERR_DISPOSITION_NOT_APPLICABLE")
    if disposition == "FLAG" and row["status"] != "DISCLOSED":
        raise ApiError("ERR_DISPOSITION_NOT_APPLICABLE")
    if disposition == "REMOVE" and row["status"] not in ("VERIFIED", "FLAGGED"):
        raise ApiError("ERR_DISPOSITION_NOT_APPLICABLE")

    row["status"] = {"VERIFY": "VERIFIED", "FLAG": "FLAGGED", "REMOVE": "REMOVED"}[disposition]
    if "reviewed_note" in data:
        row["reviewed_note"] = data["reviewed_note"]
    store.bump(row)

    logic.recompute_vendor(vendor, counts=True)
    return envelope.ok(serialize.subprocessor(row))
