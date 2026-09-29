"""Customer on-boarding, compliance holds and the regulatory filing cycle."""
from flask import Blueprint

import calc
from core import (
    body,
    endpoint,
    fail,
    listing,
    need,
    new_row,
    now_str,
    ok,
    opt_dt,
    opt_enum,
    opt_str,
    public,
    req_enum,
    req_str,
    store,
    touch,
)

bp = Blueprint("customers", __name__)

CUSTOMER_READERS = (
    "PlatformAdmin",
    "TreasuryOfficer",
    "BranchManager",
    "BranchTeller",
    "ComplianceOfficer",
)
REPORT_READERS = ("PlatformAdmin", "ComplianceOfficer", "TreasuryOfficer", "BranchManager")


# ==========================================================================
# Customers
# ==========================================================================
@bp.post("/customers")
@endpoint(["BranchTeller", "BranchManager"])
def create_customer():
    b = body()
    home_branch_id = opt_str(b, "home_branch_id")
    branch = need("Branch", home_branch_id) if home_branch_id is not None else None
    full_name = req_str(b, "full_name")
    nationality_code = req_str(b, "nationality_code")
    if len(nationality_code) != 2 or not nationality_code.isalpha() or not nationality_code.isupper():
        fail("ERR_INVALID_REQUEST", "nationality_code must be an ISO 3166-1 alpha-2 code.")
    id_document_type = opt_enum(
        b, "id_document_type", ("PASSPORT", "NATIONAL_ID", "DRIVING_LICENCE")
    )
    id_document_number = opt_str(b, "id_document_number")
    id_document_expiry = opt_dt(b, "id_document_expiry")
    travel_document_reference = opt_str(b, "travel_document_reference")
    bundle = (id_document_type, id_document_number, id_document_expiry)
    if id_document_type is not None and (id_document_number is None or id_document_expiry is None):
        fail(
            "ERR_INVALID_REQUEST",
            "id_document_number and id_document_expiry are required with id_document_type.",
        )
    if id_document_type is None and any(part is not None for part in bundle[1:]):
        fail(
            "ERR_INVALID_REQUEST",
            "id_document_type is required when any identification field is supplied.",
        )
    row = new_row("Customer")
    row["full_name"] = full_name
    row["nationality_code"] = nationality_code
    row["home_branch_id"] = branch["id"] if branch else None
    row["id_document_type"] = id_document_type
    row["id_document_number"] = id_document_number
    row["id_document_expiry"] = id_document_expiry
    row["travel_document_reference"] = travel_document_reference
    row["rolling_30d_settled_usd_cents"] = 0
    row["calendar_month_settled_usd_cents"] = 0
    row["near_threshold_txn_count"] = 0
    row["distinct_branch_count"] = 0
    row["structuring_risk_score"] = 0
    row["structuring_risk_tier"] = "NORMAL"
    row["compliance_hold_active"] = False
    store(row)
    return ok(public(row), 201)


@bp.post("/customers/<customer_id>/compliance-hold")
@endpoint(["ComplianceOfficer"])
def set_compliance_hold(customer_id):
    customer = need("Customer", customer_id)
    b = body()
    action = req_enum(b, "action", ("APPLY", "RELEASE"))
    opt_str(b, "reason")
    if action == "RELEASE":
        if calc.has_outstanding_structuring_report(customer["id"]):
            fail("ERR_STRUCTURING_REPORT_PENDING")
        customer["compliance_hold_active"] = False
    else:
        customer["compliance_hold_active"] = True
    touch(customer)
    return ok(public(customer))


@bp.get("/customers/<customer_id>")
@endpoint(CUSTOMER_READERS)
def read_customer(customer_id):
    return ok(public(need("Customer", customer_id)))


@bp.get("/customers")
@endpoint(CUSTOMER_READERS)
def list_customers():
    return listing(
        "Customer",
        {"home_branch_id": "home_branch_id", "structuring_risk_tier": "structuring_risk_tier"},
        {"compliance_hold_active": "compliance_hold_active"},
    )


# ==========================================================================
# Compliance reports (created only by cascades)
# ==========================================================================
@bp.post("/compliance-reports/<report_id>/file")
@endpoint(["ComplianceOfficer"])
def file_report(report_id):
    report = need("ComplianceReport", report_id)
    b = body()
    filing_reference = req_str(b, "filing_reference")
    if report["status"] not in ("DRAFT", "AMENDING"):
        fail("ERR_REPORT_INVALID_STATE")
    report["status"] = "FILED"
    report["filing_reference"] = filing_reference
    report["filed_at"] = now_str()
    touch(report)
    return ok(public(report))


@bp.post("/compliance-reports/<report_id>/amend")
@endpoint(["ComplianceOfficer"])
def amend_report(report_id):
    report = need("ComplianceReport", report_id)
    b = body()
    opt_str(b, "amendment_reason")
    if report["status"] != "FILED":
        fail("ERR_REPORT_INVALID_STATE")
    report["status"] = "AMENDING"
    report["amendment_count"] += 1
    touch(report)
    return ok(public(report))


@bp.get("/compliance-reports/<report_id>")
@endpoint(REPORT_READERS)
def read_report(report_id):
    return ok(public(need("ComplianceReport", report_id)))


@bp.get("/compliance-reports")
@endpoint(REPORT_READERS)
def list_reports():
    return listing(
        "ComplianceReport",
        {
            "customer_id": "customer_id",
            "branch_id": "branch_id",
            "triggering_transaction_id": "triggering_transaction_id",
            "note_assessment_id": "note_assessment_id",
            "report_type": "report_type",
            "status": "status",
        },
    )
