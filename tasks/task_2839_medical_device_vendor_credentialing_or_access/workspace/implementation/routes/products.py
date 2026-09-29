"""Product introduction, approved products and loaner sets (PRD 3.6, 3.7)."""
from flask import Blueprint

import calc
import cascades
import db
from db import store
from errors import ApiError
from reqval import (
    authenticate,
    pagination_params,
    query_bool,
    query_enum,
    query_string,
    read_body,
)
from routes import common

bp = Blueprint("products", __name__, url_prefix="/vendor-access")

SCHEDULABLE = ("SCHEDULED", "RESCHEDULED")


def _decrement_open_pir_count(vendor):
    if vendor is None:
        return
    vendor["open_pir_count"] = max(0, vendor["open_pir_count"] - 1)
    cascades.mark_vendor(vendor)


# ----------------------------------------- ProductIntroductionRequest (PIR)
@bp.post("/product-introduction-requests")
def open_pir():
    user_id, role = authenticate(("VendorAdmin",))
    body = read_body()
    vendor_id = body.string("vendor_id")
    facility_id = body.string("facility_id")
    product_name = body.string("product_name")
    product_catalog_number = body.string("product_catalog_number")
    manufacturer = body.string("manufacturer")
    is_implant = body.boolean("is_implant")
    unit_cost_cents = body.integer("unit_cost_cents", minimum=0)
    expected_vendor_version = body.integer("expected_vendor_version")
    supersedes_request_id = body.string("supersedes_request_id", required=False)

    vendor = common.vendor(vendor_id)
    common.facility(facility_id)
    if supersedes_request_id is not None:
        common.pir(supersedes_request_id)

    common.require_vendor_scope(role, user_id, vendor["id"])
    if expected_vendor_version != vendor["version"]:
        raise ApiError("ERR_STALE_VENDOR_VERSION")

    row = db.stamp_common(
        {
            "vendor_id": vendor["id"],
            "facility_id": facility_id,
            "supersedes_request_id": supersedes_request_id,
            "product_name": product_name,
            "product_catalog_number": product_catalog_number,
            "manufacturer": manufacturer,
            "is_implant": is_implant,
            "unit_cost_cents": unit_cost_cents,
            "status": "DRAFT",
            "revision_round": 0,
            "clinical_sponsor_user_id": None,
            "clinical_reviewed_at_utc": None,
            "value_analysis_user_id": None,
            "decided_at_utc": None,
        }
    )
    store.pirs[row["id"]] = row
    # A successful create itself increments the vendor's version by one.
    cascades.mark_vendor(vendor)
    cascades.flush()
    return common.created(row)


@bp.get("/product-introduction-requests/<row_id>")
def read_pir(row_id):
    authenticate(common.ALL_ROLES)
    return common.ok(common.pir(row_id))


@bp.get("/product-introduction-requests")
def list_pirs():
    authenticate(common.ALL_ROLES)
    limit, offset = pagination_params()
    vendor_id = query_string("vendor_id")
    facility_id = query_string("facility_id")
    supersedes_request_id = query_string("supersedes_request_id")
    status = query_enum("status", db.PIR_STATUSES)
    is_implant = query_bool("is_implant")
    rows = [
        row
        for row in store.pirs.values()
        if common.matches(row, "vendor_id", vendor_id)
        and common.matches(row, "facility_id", facility_id)
        and common.matches(row, "supersedes_request_id", supersedes_request_id)
        and common.matches(row, "status", status)
        and common.matches(row, "is_implant", is_implant)
    ]
    return common.listing(rows, limit, offset)


@bp.post("/product-introduction-requests/<row_id>/submit")
def submit_pir(row_id):
    user_id, role = authenticate(("VendorAdmin",))
    read_body()
    pir = common.pir(row_id)
    common.require_vendor_scope(role, user_id, pir["vendor_id"])

    if pir["status"] not in ("DRAFT", "CHANGES_REQUESTED"):
        raise ApiError("ERR_PIR_INVALID_STATE")
    if pir["status"] == "CHANGES_REQUESTED" and pir["revision_round"] >= db.MAX_REVISION_ROUNDS:
        raise ApiError("ERR_PIR_REVISION_LIMIT")

    vendor = store.vendors.get(pir["vendor_id"])
    if pir["status"] == "DRAFT":
        vendor["open_pir_count"] = vendor["open_pir_count"] + 1
        cascades.mark_vendor(vendor)
    else:
        # A request in CHANGES_REQUESTED was already being counted as open.
        pir["revision_round"] = pir["revision_round"] + 1
    pir["status"] = "CLINICAL_REVIEW"
    cascades.mark(pir)
    cascades.flush()
    return common.ok(pir)


@bp.post("/product-introduction-requests/<row_id>/clinical-review")
def clinical_review(row_id):
    user_id, _role = authenticate(("ClinicalSponsor",))
    body = read_body()
    decision = body.enum("decision", ("ENDORSE", "REJECT"))
    body.string("review_note", required=False)

    pir = common.pir(row_id)
    if pir["status"] != "CLINICAL_REVIEW":
        raise ApiError("ERR_PIR_INVALID_STATE")

    moment = db.now_str()
    pir["clinical_sponsor_user_id"] = user_id
    pir["clinical_reviewed_at_utc"] = moment
    if decision == "ENDORSE":
        pir["status"] = "VALUE_ANALYSIS_REVIEW"
    else:
        pir["status"] = "REJECTED"
        pir["decided_at_utc"] = moment
        _decrement_open_pir_count(store.vendors.get(pir["vendor_id"]))
    cascades.mark(pir)
    cascades.flush()
    return common.ok(pir)


def _mint_approved_product(pir):
    """Exactly one ApprovedProduct, copying the request as it stands now."""
    moment = db.now_str()
    product = db.stamp_common(
        {
            "product_introduction_request_id": pir["id"],
            "product_name": pir["product_name"],
            "product_catalog_number": pir["product_catalog_number"],
            "manufacturer": pir["manufacturer"],
            "is_implant": pir["is_implant"],
            "unit_cost_cents": pir["unit_cost_cents"],
            "pinned_pir_version": pir["version"],
            "approved_at_utc": moment,
            "approval_expires_at_utc": calc.approval_expiry(moment),
            "status": "ACTIVE",
            "suspended_reason": "NONE",
        }
    )
    store.approved_products[product["id"]] = product
    return product


@bp.post("/product-introduction-requests/<row_id>/value-analysis-decision")
def value_analysis_decision(row_id):
    user_id, _role = authenticate(("ValueAnalysisApprover",))
    body = read_body()
    decision = body.enum("decision", ("APPROVE", "REJECT", "REQUEST_CHANGES"))
    body.string("decision_note", required=False)

    pir = common.pir(row_id)
    if pir["status"] != "VALUE_ANALYSIS_REVIEW":
        raise ApiError("ERR_PIR_INVALID_STATE")
    if user_id == pir["clinical_sponsor_user_id"]:
        raise ApiError("ERR_SEGREGATION_OF_DUTIES")
    if decision == "REQUEST_CHANGES" and pir["revision_round"] >= db.MAX_REVISION_ROUNDS:
        raise ApiError("ERR_PIR_REVISION_LIMIT")

    pir["value_analysis_user_id"] = user_id
    if decision == "REQUEST_CHANGES":
        pir["status"] = "CHANGES_REQUESTED"
        # The next round needs a fresh clinical endorsement.
        pir["clinical_sponsor_user_id"] = None
        pir["clinical_reviewed_at_utc"] = None
        cascades.mark(pir)
        cascades.flush()
        return common.ok(pir)

    pir["decided_at_utc"] = db.now_str()
    pir["status"] = "APPROVED" if decision == "APPROVE" else "REJECTED"
    _decrement_open_pir_count(store.vendors.get(pir["vendor_id"]))
    cascades.mark(pir)
    cascades.flush()

    if decision == "APPROVE":
        _mint_approved_product(pir)
        if pir["supersedes_request_id"]:
            for product in db.in_creation_order(list(store.approved_products.values())):
                if product["product_introduction_request_id"] != pir["supersedes_request_id"]:
                    continue
                cascades.suspend_product(product, "SUPERSEDED")
        cascades.flush()
    return common.ok(pir)


# ------------------------------------------------------- ApprovedProduct
@bp.get("/approved-products/<row_id>")
def read_approved_product(row_id):
    authenticate(common.ALL_ROLES)
    return common.ok(common.approved_product(row_id))


@bp.get("/approved-products")
def list_approved_products():
    authenticate(common.ALL_ROLES)
    limit, offset = pagination_params()
    request_id = query_string("product_introduction_request_id")
    vendor_id = query_string("vendor_id")
    facility_id = query_string("facility_id")
    status = query_enum("status", db.PRODUCT_STATUSES)
    is_implant = query_bool("is_implant")
    rows = []
    for row in store.approved_products.values():
        if not common.matches(row, "product_introduction_request_id", request_id):
            continue
        if not common.matches(row, "status", status):
            continue
        if not common.matches(row, "is_implant", is_implant):
            continue
        if vendor_id is not None and calc.product_vendor_id(row) != vendor_id:
            continue
        if facility_id is not None and calc.product_facility_id(row) != facility_id:
            continue
        rows.append(row)
    return common.listing(rows, limit, offset)


# ------------------------------------------------------------- LoanerSet
@bp.post("/loaner-sets")
def register_loaner_set():
    authenticate(("VendorAdmin", "SterileProcessingTech"))
    body = read_body()
    surgical_case_id = body.string("surgical_case_id")
    approved_product_id = body.string("approved_product_id")
    tray_count = body.integer("tray_count", minimum=0)
    complexity = body.enum("reprocessing_complexity", db.COMPLEXITIES)
    expected_case_version = body.integer("expected_case_version")

    case = common.surgical_case(surgical_case_id)
    product = common.approved_product(approved_product_id)

    if expected_case_version != case["version"]:
        raise ApiError("ERR_STALE_CASE_VERSION")
    if case["status"] not in SCHEDULABLE:
        raise ApiError("ERR_CASE_NOT_SCHEDULED")

    facility = calc.case_facility(case)
    pinned = calc.compute_deadline(
        case["original_scheduled_start_utc"], case, facility, complexity, tray_count
    )
    required = calc.compute_deadline(
        case["scheduled_start_utc"], case, facility, complexity, tray_count
    )
    occupation_start = required
    occupation_end = case["scheduled_start_utc"]

    collisions = calc.bay_collision_count(occupation_start, occupation_end, facility["id"])
    if collisions >= facility["spd_bay_count"]:
        raise ApiError("ERR_SPD_BAY_CAPACITY_EXCEEDED")
    if product["status"] != "ACTIVE":
        raise ApiError("ERR_PRODUCT_NOT_APPROVED")

    row = db.stamp_common(
        {
            "surgical_case_id": case["id"],
            "approved_product_id": product["id"],
            "tray_count": tray_count,
            "reprocessing_complexity": complexity,
            "pinned_deadline_utc": pinned,
            "required_delivery_deadline_utc": required,
            "delivered_at_utc": None,
            "late_minutes_pinned_basis": 0,
            "late_minutes_current_basis": 0,
            "assessed_late_fee_cents": 0,
            "fee_status": "NONE",
            "status": "EXPECTED",
            "spd_occupation_start_utc": occupation_start,
            "spd_occupation_end_utc": occupation_end,
        }
    )
    store.loaner_sets[row["id"]] = row
    # The registration increments the case's version by one and refreshes the
    # case's implant readiness posture.
    cascades.mark_case(case)
    cascades.flush()
    return common.created(row)


@bp.get("/loaner-sets/<row_id>")
def read_loaner_set(row_id):
    authenticate(common.ALL_ROLES)
    return common.ok(common.loaner_set(row_id))


@bp.get("/loaner-sets")
def list_loaner_sets():
    authenticate(common.ALL_ROLES)
    limit, offset = pagination_params()
    surgical_case_id = query_string("surgical_case_id")
    approved_product_id = query_string("approved_product_id")
    status = query_enum("status", db.LOANER_STATUSES)
    fee_status = query_enum("fee_status", db.FEE_STATUSES)
    rows = [
        row
        for row in store.loaner_sets.values()
        if common.matches(row, "surgical_case_id", surgical_case_id)
        and common.matches(row, "approved_product_id", approved_product_id)
        and common.matches(row, "status", status)
        and common.matches(row, "fee_status", fee_status)
    ]
    return common.listing(rows, limit, offset)


@bp.post("/loaner-sets/<row_id>/receive")
def receive_loaner_set(row_id):
    authenticate(("SterileProcessingTech",))
    body = read_body()
    delivered_raw, _delivered = body.instant("delivered_at_utc", required=False)

    loaner_set = common.loaner_set(row_id)
    case = store.surgical_cases.get(loaner_set["surgical_case_id"])
    if case is None or case["status"] not in SCHEDULABLE:
        raise ApiError("ERR_CASE_NOT_SCHEDULED")
    if loaner_set["status"] != "EXPECTED":
        raise ApiError("ERR_LOANER_SET_INVALID_STATE")

    # An omitted delivery instant means "now", on the logical clock.
    delivered_at = delivered_raw if delivered_raw is not None else db.now_str()
    loaner_set["delivered_at_utc"] = delivered_at
    loaner_set["late_minutes_pinned_basis"] = calc.compute_late_minutes(
        loaner_set["pinned_deadline_utc"], delivered_at
    )
    loaner_set["late_minutes_current_basis"] = calc.compute_late_minutes(
        loaner_set["required_delivery_deadline_utc"], delivered_at
    )

    # The fork is taken purely on the current-basis figure.
    loaner_set["status"] = calc.delivery_branch(loaner_set["late_minutes_current_basis"])
    if loaner_set["status"] == "DELIVERED_ON_TIME":
        loaner_set["assessed_late_fee_cents"] = 0
        loaner_set["fee_status"] = "NONE"
    else:
        loaner_set["assessed_late_fee_cents"] = calc.compute_late_fee(loaner_set)
        loaner_set["fee_status"] = calc.compute_fee_status(loaner_set)
    cascades.mark(loaner_set)
    cascades.mark_case(case)
    cascades.mark_vendor_id(calc.loaner_set_vendor_id(loaner_set))

    cascades.flush()
    return common.ok(loaner_set)


@bp.post("/loaner-sets/<row_id>/release")
def release_loaner_set(row_id):
    authenticate(("SterileProcessingTech",))
    read_body()

    loaner_set = common.loaner_set(row_id)
    if loaner_set["status"] not in ("DELIVERED_ON_TIME", "DELIVERED_LATE"):
        raise ApiError("ERR_LOANER_SET_INVALID_STATE")

    product = store.approved_products.get(loaner_set["approved_product_id"])
    if product is None or product["status"] != "ACTIVE":
        raise ApiError("ERR_PRODUCT_NOT_APPROVED")

    vendor_id = calc.loaner_set_vendor_id(loaner_set)
    vendor = store.vendors.get(vendor_id)
    if vendor is not None and vendor["late_fee_balance_cents"] >= db.FEE_HOLD_THRESHOLD_CENTS:
        raise ApiError("ERR_VENDOR_FEE_HOLD")

    loaner_set["status"] = "RELEASED_TO_OR"
    cascades.mark(loaner_set)
    # The released set leaves the bay, and the case's readiness is refreshed.
    cascades.mark_case_id(loaner_set["surgical_case_id"])

    cascades.flush()
    return common.ok(loaner_set)
