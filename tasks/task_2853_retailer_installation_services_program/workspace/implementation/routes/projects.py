"""Projects: the sale, the three status dimensions, the money and the permit."""
from decimal import Decimal

from flask import Blueprint

import envelope
import fields
import store
from errors import ApiError
from fields import A, B, E, I, M, N, S, T, auth, body, need, occ, pagination, validate
from routes.helpers import category_and_jurisdiction, owner_customer, project_not_cancelled
from services import calc, cascade

bp = Blueprint("projects", __name__)

PROJECT_READ = ["ProgramAdmin", "ProjectCoordinator", "ServiceManager", "NetworkManager", "Customer"]
PROJECT_READ_ONE = PROJECT_READ + ["Installer"]

PROJECT_CREATE = [
    S("customer_id"),
    S("service_category_id"),
    S("jurisdiction_id"),
    S("site_address", maxlen=200),
    N("estimated_units", gt=0),
    T("requested_install_date"),
]

AMOUNT = [M("amount_cents")]
CANCEL = [S("cancel_reason", maxlen=300)]
REINSTATE = [S("reinstate_note", required=False, maxlen=300)]

DEFECT = [
    E("severity", fields.PUNCH_SEVERITIES),
    S("description", maxlen=300),
    T("due_at"),
]

QUALITY_INSPECTION = [
    E("quality_result", fields.QUALITY_RESULTS),
    I("workmanship_score", minimum=0, maximum=100),
    A("defects", item_specs=DEFECT),
]

PERMIT_APPLY = [
    S("permit_application_reference", maxlen=64),
    B("resubmit", required=False),
]

PERMIT_ISSUE = [
    M("permit_fee_cents"),
    T("permit_issued_on"),
]

INSPECTION_SLOT = [
    T("inspection_slot_start"),
    T("inspection_slot_end"),
]

INSPECTION_RESULT = [
    E("result", fields.INSPECTION_RESULTS),
    S("inspector_note", required=False, maxlen=300),
]


def _not_closed(project):
    """Rank 13: CLOSED is terminal on the execution dimension."""
    if project["fulfillment_status"] == "CLOSED":
        raise ApiError("ERR_ALREADY_TERMINAL")


def _permit_not_closed(project):
    """Rank 13: CLOSED is the only terminal permit state."""
    if project["permit_status"] == "CLOSED":
        raise ApiError("ERR_ALREADY_TERMINAL")


@bp.post("/projects")
def create_project():
    auth(["ProgramAdmin", "ProjectCoordinator"])
    data = validate(body(), PROJECT_CREATE)
    customer = need("customers", data["customer_id"])
    category = need("service_categories", data["service_category_id"])
    jurisdiction = need("jurisdictions", data["jurisdiction_id"])
    if category["status"] != "ACTIVE" or jurisdiction["status"] != "ACTIVE":
        raise ApiError("ERR_REFERENCE_NOT_ELIGIBLE")

    row = {
        "customer_id": customer["id"],
        "service_category_id": category["id"],
        "jurisdiction_id": jurisdiction["id"],
        "site_address": data["site_address"],
        "estimated_units": data["estimated_units"],
        "requested_install_date": data["requested_install_date"],
        "fulfillment_status": "MEASURE_PENDING" if category["measurement_required"] else "MEASURED",
        "financial_status": "QUOTED",
        "permit_status": None,
        "permit_responsibility": None,
        "effective_units": data["estimated_units"],
        "quoted_labor_cents": 0,
        "deposit_required_cents": 0,
        "deposit_paid_cents": 0,
        "deposit_held_cents": 0,
        "deposit_applied_cents": 0,
        "deposit_refunded_cents": 0,
        "deposit_forfeited_cents": 0,
        "final_labor_cents": None,
        "change_order_upcharge_cents": 0,
        "permit_fee_cents_billed": 0,
        "total_due_cents": 0,
        "balance_due_cents": 0,
        "permit_application_reference": None,
        "permit_issued_on": None,
        "inspection_slot_start": None,
        "inspection_slot_end": None,
        "inspection_result": "NONE",
        "inspection_attempt_count": 0,
        "quality_result": "NONE",
        "workmanship_score": None,
        "escalated_punch_count": 0,
        "service_manager_review_required": False,
        "install_completed_at": None,
        "cancelled_at": None,
        "cancel_reason": None,
        "closed_at": None,
    }
    row["quoted_labor_cents"] = calc.labor_charge(row, category, jurisdiction, "PROVISIONAL")
    row["deposit_required_cents"] = calc.rhu(
        Decimal(row["quoted_labor_cents"]) * calc.dec(category["deposit_pct"]))
    calc.apply_permit_determination(row, category, jurisdiction)
    store.insert("projects", row)

    customer["project_count"] = calc.customer_project_count(customer["id"])
    store.touch(customer)
    return envelope.obj(row, 201)


@bp.get("/projects")
def list_projects():
    auth(PROJECT_READ)
    limit, offset = pagination()
    rows = store.all_rows("projects")
    for name in ("customer_id", "service_category_id", "jurisdiction_id",
                 "fulfillment_status", "financial_status", "permit_status"):
        rows = fields.filter_eq(rows, name, fields.arg(name))
    return envelope.collection(envelope.order_default(rows), limit, offset)


@bp.get("/projects/<row_id>")
def get_project(row_id):
    auth(PROJECT_READ_ONE)
    return envelope.obj(need("projects", row_id))


@bp.get("/projects/<row_id>/settlement-preview")
def settlement_preview(row_id):
    actor = auth(["ProgramAdmin", "ProjectCoordinator", "ServiceManager", "Customer"])
    project = need("projects", row_id)
    delivery = calc.project_delivery(project["id"])
    customer = store.get("customers", project["customer_id"])
    result = calc.settlement(
        project, project["fulfillment_status"], delivery,
        delivery["status"] if delivery is not None else None, actor.role, customer)
    return envelope.raw(result)


@bp.post("/projects/<row_id>/deposit")
def pay_deposit(row_id):
    actor = auth(["Customer"])
    data = validate(body(), AMOUNT)
    project = need("projects", row_id)
    _not_closed(project)
    if project["fulfillment_status"] == "CANCELLED" or project["financial_status"] != "QUOTED":
        raise ApiError("ERR_INVALID_STATE")
    owner_customer(project, actor)
    if data["amount_cents"] != int(project["deposit_required_cents"]):
        raise ApiError("ERR_DEPOSIT_AMOUNT_MISMATCH")
    project["deposit_paid_cents"] = data["amount_cents"]
    project["deposit_held_cents"] = data["amount_cents"]
    project["financial_status"] = "DEPOSIT_HELD"
    calc.recompute_money(project)
    store.touch(project)
    return envelope.obj(project)


@bp.post("/projects/<row_id>/pay-balance")
def pay_balance(row_id):
    actor = auth(["Customer"])
    data = validate(body(), AMOUNT)
    project = need("projects", row_id)
    _not_closed(project)
    owner_customer(project, actor)
    # PRD 3.6: the balance gate is stated purely as the amount and the balance, with
    # no separate financial-dimension state precondition: "which must equal
    # `balance_due_cents` **exactly** and which requires `balance_due_cents` to be
    # greater than zero; any other figure, or a payment against a zero balance, is
    # `ERR_BALANCE_AMOUNT_MISMATCH`". Rank 36 therefore owns every non-payable state:
    # SETTLED, QUOTED, DEPOSIT_HELD and the three post-cancellation statuses all carry
    # `balance_due_cents` of zero, so each answers ERR_BALANCE_AMOUNT_MISMATCH.
    balance = int(project["balance_due_cents"])
    if balance <= 0 or data["amount_cents"] != balance:
        raise ApiError("ERR_BALANCE_AMOUNT_MISMATCH")
    project["financial_status"] = "SETTLED"
    project["balance_due_cents"] = 0
    store.touch(project)
    return envelope.obj(project)


CANCELLABLE = ("DRAFT", "MEASURE_PENDING", "MEASURED", "CHANGE_PENDING", "SCHEDULED", "IN_PROGRESS")


@bp.post("/projects/<row_id>/cancel")
def cancel(row_id):
    actor = auth(["ProgramAdmin", "ProjectCoordinator", "ServiceManager", "Customer"])
    data = validate(body(), CANCEL)
    project = need("projects", row_id)
    _not_closed(project)
    owner_customer(project, actor)
    if project["fulfillment_status"] not in CANCELLABLE:
        raise ApiError("ERR_NOT_CANCELLABLE")
    cascade.cancel_project(project, data["cancel_reason"], actor.role)
    store.touch(project)
    return envelope.obj(project)


@bp.post("/projects/<row_id>/reinstate")
def reinstate(row_id):
    auth(["ProgramAdmin", "ProjectCoordinator"])
    payload = body()
    validate(payload, REINSTATE)
    project = need("projects", row_id)
    expected = occ(payload, "expected_project_version")
    if expected != project["version"]:
        raise ApiError("ERR_STALE_PROJECT_VERSION")
    _not_closed(project)
    if project["fulfillment_status"] != "CANCELLED":
        raise ApiError("ERR_INVALID_STATE")
    if project["financial_status"] not in ("PARTIALLY_REFUNDED", "REFUNDED", "FORFEITED"):
        raise ApiError("ERR_INVALID_STATE")
    elapsed = (store.now() - project["cancelled_at"]).total_seconds()
    if elapsed >= calc.REINSTATE_WINDOW_HOURS * 3600:
        raise ApiError("ERR_REINSTATE_WINDOW_CLOSED")

    project["deposit_held_cents"] = (int(project["deposit_held_cents"])
                                    + int(project["deposit_refunded_cents"])
                                    + int(project["deposit_forfeited_cents"]))
    project["deposit_refunded_cents"] = 0
    project["deposit_forfeited_cents"] = 0
    project["financial_status"] = "DEPOSIT_HELD"
    survivor = any(m["project_id"] == project["id"] and m["status"] == "COMPLETED"
                   for m in store.all_rows("measurements"))
    project["fulfillment_status"] = "MEASURED" if survivor else "MEASURE_PENDING"
    project["cancelled_at"] = None
    project["cancel_reason"] = None
    calc.recompute_money(project)
    store.touch(project)
    return envelope.obj(project)


@bp.post("/projects/<row_id>/quality-inspection")
def quality_inspection(row_id):
    auth(["ProjectCoordinator"])
    data = validate(body(), QUALITY_INSPECTION)
    project = need("projects", row_id)
    _not_closed(project)
    project_not_cancelled(project)
    if project["fulfillment_status"] != "INSTALL_COMPLETE" or project["quality_result"] != "NONE":
        raise ApiError("ERR_INVALID_STATE")

    defects = data["defects"]
    project["workmanship_score"] = data["workmanship_score"]
    if not defects:
        project["quality_result"] = data["quality_result"]
    else:
        project["quality_result"] = (
            "PASS_WITH_PUNCH" if data["workmanship_score"] >= 70 else "FAIL")
        installer_id = cascade.project_completed_installer_id(project["id"])
        installer = store.get("installers", installer_id) if installer_id else None
        for defect in defects:
            store.insert("punch_list_items", {
                "project_id": project["id"],
                "severity": defect["severity"],
                "description": defect["description"],
                "due_at": defect["due_at"],
                "status": "OPEN",
                "resolution_note": None,
                "resolved_at": None,
                "verified_at": None,
                "escalated_at": None,
                "escalation_reason": None,
                "escalated_to_user_id": None,
            })
            if installer is not None:
                cascade.append_event(
                    installer, "PUNCH_" + defect["severity"], store.now(), "SYSTEM",
                    project_id=project["id"])
        if installer is not None:
            cascade.rescore_and_touch(installer)
        project["fulfillment_status"] = "PUNCH_OPEN"
    store.touch(project)
    return envelope.obj(project)


@bp.post("/projects/<row_id>/close")
def close(row_id):
    auth(["ProjectCoordinator"])
    project = need("projects", row_id)
    _not_closed(project)
    blocking = [p for p in store.all_rows("punch_list_items")
                if p["project_id"] == project["id"]
                and p["status"] in ("OPEN", "RESOLVED", "ESCALATED")]
    if blocking:
        raise ApiError("ERR_PUNCH_LIST_NOT_CLEARED")
    category, jurisdiction = category_and_jurisdiction(project)
    if (jurisdiction is not None and jurisdiction["inspection_required"]
            and project["permit_responsibility"] != "NOT_REQUIRED"
            and project["permit_status"] != "CLOSED"):
        raise ApiError("ERR_INSPECTION_NOT_PASSED")
    if project["financial_status"] != "SETTLED":
        raise ApiError("ERR_NOT_CANCELLABLE")
    if project["fulfillment_status"] not in ("INSTALL_COMPLETE", "PUNCH_OPEN"):
        raise ApiError("ERR_INVALID_STATE")
    if (project["fulfillment_status"] == "INSTALL_COMPLETE"
            and project["quality_result"] != "PASS"):
        raise ApiError("ERR_INVALID_STATE")
    project["fulfillment_status"] = "CLOSED"
    project["closed_at"] = store.now()
    store.touch(project)
    return envelope.obj(project)


PERMIT_PARTY_ROLES = {
    "RETAILER": ("ProjectCoordinator", "ProgramAdmin"),
    "INSTALLER": ("Installer",),
    "CUSTOMER": ("Customer",),
}


@bp.post("/projects/<row_id>/permit/apply")
def permit_apply(row_id):
    actor = auth(["ProgramAdmin", "ProjectCoordinator", "Installer", "Customer"])
    data = validate(body(), PERMIT_APPLY)
    project = need("projects", row_id)
    _not_closed(project)
    _permit_not_closed(project)
    resubmit = bool(data.get("resubmit", False))
    if resubmit:
        if project["permit_status"] != "APPLIED":
            raise ApiError("ERR_INVALID_STATE")
    elif project["permit_status"] != "PENDING_APPLICATION":
        raise ApiError("ERR_INVALID_STATE")
    if actor.role not in PERMIT_PARTY_ROLES.get(project["permit_responsibility"], ()):
        raise ApiError("ERR_WRONG_PERMIT_PARTY")

    if resubmit:
        project["permit_status"] = "PENDING_APPLICATION"
        project["permit_application_reference"] = None
    else:
        project["permit_application_reference"] = data["permit_application_reference"]
        project["permit_status"] = "APPLIED"
    store.touch(project)
    return envelope.obj(project)


@bp.post("/projects/<row_id>/permit/issue")
def permit_issue(row_id):
    auth(["ProgramAdmin", "ProjectCoordinator"])
    data = validate(body(), PERMIT_ISSUE)
    project = need("projects", row_id)
    _not_closed(project)
    _permit_not_closed(project)
    if project["permit_status"] != "APPLIED":
        raise ApiError("ERR_INVALID_STATE")
    project["permit_fee_cents_billed"] = data["permit_fee_cents"]
    project["permit_issued_on"] = data["permit_issued_on"]
    project["permit_status"] = "ISSUED"
    calc.recompute_money(project)
    store.touch(project)
    return envelope.obj(project)


@bp.post("/projects/<row_id>/inspection-slot")
def inspection_slot(row_id):
    auth(["ProjectCoordinator"])
    data = validate(body(), INSPECTION_SLOT)
    project = need("projects", row_id)
    _not_closed(project)
    _permit_not_closed(project)
    category, jurisdiction = category_and_jurisdiction(project)
    if project["permit_status"] not in ("ISSUED", "INSPECTION_FAILED"):
        raise ApiError("ERR_INVALID_STATE")
    if jurisdiction is None or not jurisdiction["inspection_required"]:
        raise ApiError("ERR_INVALID_STATE")

    start = data["inspection_slot_start"]
    end = data["inspection_slot_end"]
    earliest = store.days_after(store.now(), int(jurisdiction["inspection_lead_days"]))
    if end <= start or start < earliest:
        raise ApiError("ERR_INSPECTION_LEAD_TIME")

    overlapping = 0
    for other in store.all_rows("projects"):
        if other["id"] == project["id"]:
            continue
        if other["jurisdiction_id"] != project["jurisdiction_id"]:
            continue
        if other["permit_status"] != "INSPECTION_SCHEDULED":
            continue
        if other["inspection_slot_start"] is None or other["inspection_slot_end"] is None:
            continue
        if start <= other["inspection_slot_end"] and other["inspection_slot_start"] <= end:
            overlapping += 1
    if overlapping >= int(jurisdiction["max_concurrent_inspections"]):
        raise ApiError("ERR_INSPECTION_CAPACITY_FULL")

    project["inspection_slot_start"] = start
    project["inspection_slot_end"] = end
    project["permit_status"] = "INSPECTION_SCHEDULED"
    store.touch(project)
    return envelope.obj(project)


@bp.post("/projects/<row_id>/inspection-result")
def inspection_result(row_id):
    auth(["ProgramAdmin", "ProjectCoordinator"])
    data = validate(body(), INSPECTION_RESULT)
    project = need("projects", row_id)
    _not_closed(project)
    _permit_not_closed(project)
    if project["permit_status"] != "INSPECTION_SCHEDULED":
        raise ApiError("ERR_INVALID_STATE")
    project["inspection_result"] = data["result"]
    project["inspection_attempt_count"] = int(project["inspection_attempt_count"]) + 1
    if data["result"] == "FAILED":
        project["permit_status"] = "INSPECTION_FAILED"
        project["inspection_slot_start"] = None
        project["inspection_slot_end"] = None
    else:
        # INSPECTION_PASSED is transient: the same request drives it on to CLOSED.
        project["permit_status"] = "INSPECTION_PASSED"
        project["permit_status"] = "CLOSED"
    store.touch(project)
    return envelope.obj(project)


@bp.get("/projects/<row_id>/scorecard-events")
def list_project_events(row_id):
    auth(["ProgramAdmin", "NetworkManager", "ProjectCoordinator", "ServiceManager"])
    limit, offset = pagination()
    project = need("projects", row_id)
    rows = [e for e in store.all_rows("scorecard_events") if e["project_id"] == project["id"]]
    rows = fields.filter_eq(rows, "event_type", fields.arg("event_type"))
    return envelope.collection(envelope.order_scorecard_events(rows), limit, offset)
