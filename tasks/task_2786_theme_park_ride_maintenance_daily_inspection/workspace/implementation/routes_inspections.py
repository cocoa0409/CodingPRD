"""Daily inspections, checklist results and the four-hop failure cascade."""

from flask import Blueprint, g

import derive
import fetch
import store
import validate
from auth import ALL_ROLES, require_roles
from envelope import list_response
from errors import (
    fail,
    invalid,
    ERR_DUPLICATE_INSPECTION,
    ERR_ESSENTIAL_FAIL_NOTE_REQUIRED,
    ERR_INSPECTION_STATE_INVALID,
    ERR_ITEM_RESULTS_PENDING,
    ERR_NDT_OVERDUE_SAFETY_CRITICAL,
    ERR_NO_ACTIVE_TEMPLATE,
    ERR_REGULATORY_HOLD_ACTIVE,
    ERR_SAFETY_CRITICAL_ITEM_FAILED,
    ERR_SEGREGATION_OF_DUTIES,
)
from reply import computed, made, saved

bp = Blueprint("inspections", __name__)

OUTCOMES = ("PASS", "FAIL", "NA")
RECORDING_STATES = ("IN_PROGRESS", "BLOCKED")


@bp.post("/park-ops/daily-inspections")
@require_roles("MaintenanceTechnician")
def open_inspection():
    data = validate.body()
    attraction = fetch.fk("attractions", data.get("attraction_id"))
    validate.id_field(data, "attraction_id")
    service_date = validate.date_field(data, "service_date")
    template = derive.active_template(attraction)
    if template is None:
        fail(ERR_NO_ACTIVE_TEMPLATE,
             "The attraction has no ACTIVE checklist revision.")
    effective_from = store.date_of(template["effective_from_date"])
    if effective_from is not None and service_date < effective_from:
        invalid("service_date must be the same as or later than the "
                "template revision's effective_from_date.")
    service_date_str = service_date.isoformat()
    for existing in store.rows("inspections"):
        if (existing["attraction_id"] == attraction["id"]
                and existing["service_date"] == service_date_str):
            fail(ERR_DUPLICATE_INSPECTION,
                 "An inspection already exists for this attraction and "
                 "service date.")
    inspection = store.create(
        "inspections",
        attraction_id=attraction["id"],
        template_id=template["id"],
        template_revision=template["revision"],
        service_date=service_date_str,
        status="IN_PROGRESS",
        opened_by_user_id=g.user_id,
        recorded_by_user_ids=[],
        signed_off_by_user_id=None,
        signed_off_at=None,
        rejection_reason=None,
        rework_round=0,
    )
    for item in derive.checklist_items_of(template["id"]):
        store.create(
            "item_results",
            inspection_id=inspection["id"],
            checklist_item_id=item["id"],
            severity_class=item["severity_class"],
            requires_photo=item["requires_photo"],
            outcome="PENDING",
            note=None,
            recorded_by_user_id=None,
            recorded_at=None,
        )
    return made(derive.ser_inspection, inspection)


@bp.get("/park-ops/daily-inspections/<inspection_id>")
@require_roles(*ALL_ROLES)
def read_inspection(inspection_id):
    return computed(derive.ser_inspection(fetch.inspection(inspection_id)))


@bp.get("/park-ops/daily-inspections")
@require_roles(*ALL_ROLES)
def list_inspections():
    return list_response(
        store.rows("inspections"),
        derive.ser_inspection,
        filters=(("attraction_id", "str"), ("template_id", "str"),
                 ("service_date", "str"), ("status", "str")),
        order=("service_date", "created_at"),
    )


@bp.post("/park-ops/daily-inspections/<inspection_id>/submit")
@require_roles("MaintenanceTechnician")
def submit_inspection(inspection_id):
    inspection = fetch.inspection(inspection_id)
    validate.body()
    if inspection["status"] != "IN_PROGRESS":
        fail(ERR_INSPECTION_STATE_INVALID,
             "Only an IN_PROGRESS inspection may be submitted.")
    if derive.pending_item_count(inspection) > 0:
        fail(ERR_ITEM_RESULTS_PENDING,
             "Every checklist line must be answered before submission.")
    inspection["status"] = "PENDING_SIGN_OFF"
    return saved(derive.ser_inspection, inspection)


@bp.post("/park-ops/daily-inspections/<inspection_id>/sign-off")
@require_roles("QualifiedInspector")
def sign_off_inspection(inspection_id):
    inspection = fetch.inspection(inspection_id)
    validate.body()
    if inspection["status"] != "PENDING_SIGN_OFF":
        fail(ERR_INSPECTION_STATE_INVALID,
             "Only a PENDING_SIGN_OFF inspection may be signed off.")
    attraction = store.db.attractions.get(inspection["attraction_id"])
    if derive.blocking_item_count(inspection) > 0:
        fail(ERR_SAFETY_CRITICAL_ITEM_FAILED,
             "A live safety-critical failure blocks sign-off.")
    if derive.has_overdue_safety_critical(attraction):
        fail(ERR_NDT_OVERDUE_SAFETY_CRITICAL,
             "A safety-critical component is overdue for nondestructive "
             "testing.")
    if derive.regulatory_hold(attraction):
        fail(ERR_REGULATORY_HOLD_ACTIVE,
             "A regulatory hold is active on this attraction.")
    if g.user_id in inspection["recorded_by_user_ids"]:
        fail(ERR_SEGREGATION_OF_DUTIES,
             "A technician who recorded a result may not sign this "
             "inspection off.")
    inspection["status"] = "SIGNED_OFF"
    inspection["signed_off_by_user_id"] = g.user_id
    inspection["signed_off_at"] = store.now_iso()
    return saved(derive.ser_inspection, inspection)


@bp.post("/park-ops/daily-inspections/<inspection_id>/reject")
@require_roles("QualifiedInspector")
def reject_inspection(inspection_id):
    inspection = fetch.inspection(inspection_id)
    data = validate.body()
    reason = validate.str_field(data, "rejection_reason", allow_empty=True)
    if inspection["status"] != "PENDING_SIGN_OFF":
        fail(ERR_INSPECTION_STATE_INVALID,
             "Only a PENDING_SIGN_OFF inspection may be rejected.")
    inspection["status"] = "REJECTED"
    inspection["rejection_reason"] = reason
    return saved(derive.ser_inspection, inspection)


@bp.post("/park-ops/daily-inspections/<inspection_id>/reopen")
@require_roles("MaintenanceTechnician")
def reopen_inspection(inspection_id):
    inspection = fetch.inspection(inspection_id)
    validate.body()
    if inspection["status"] != "REJECTED":
        fail(ERR_INSPECTION_STATE_INVALID,
             "Only a REJECTED inspection may be reopened.")
    inspection["status"] = "IN_PROGRESS"
    inspection["rework_round"] += 1
    for result in derive.results_of(inspection):
        if result["outcome"] == "FAIL":
            result["outcome"] = "PENDING"
            result["recorded_by_user_id"] = None
            result["recorded_at"] = None
    return saved(derive.ser_inspection, inspection)


# ---------------------------------------------------------------------------
# checklist result rows
# ---------------------------------------------------------------------------

def _sequence_of(result):
    item = store.db.checklist_items.get(result["checklist_item_id"])
    return item["sequence_no"] if item else 0


@bp.get("/park-ops/inspection-item-results/<result_id>")
@require_roles(*ALL_ROLES)
def read_item_result(result_id):
    return computed(derive.ser_item_result(fetch.item_result(result_id)))


@bp.get("/park-ops/inspection-item-results")
@require_roles(*ALL_ROLES)
def list_item_results():
    return list_response(
        store.rows("item_results"),
        derive.ser_item_result,
        filters=(("inspection_id", "str"), ("checklist_item_id", "str"),
                 ("outcome", "str"), ("severity_class", "str")),
        order=(lambda row, view: _sequence_of(row),),
    )


def _other_failures_reference(component_id, excluding_result_id):
    for other in store.rows("item_results"):
        if other["id"] == excluding_result_id or other["outcome"] != "FAIL":
            continue
        item = store.db.checklist_items.get(other["checklist_item_id"])
        if item is not None and item.get("component_id") == component_id:
            return True
    return False


def _open_auto_downtime(attraction):
    """Hop four of the inspection-failure cascade (PRD 3.2)."""
    for event in store.rows("downtime_events"):
        if (event["attraction_id"] == attraction["id"]
                and event["status"] in derive.LIVE_DOWNTIME):
            return None
    started = store.now()
    return store.create(
        "downtime_events",
        attraction_id=attraction["id"],
        failed_component_id=None,
        started_at=store.iso(started),
        ended_at=None,
        service_date=started.date().isoformat(),
        cause_category="INSPECTION_FAIL",
        root_cause_code=None,
        status="OPEN",
        duration_minutes=None,
        peak_minutes=None,
        off_peak_minutes=None,
        _settled_hundredths=None,
        void_reason=None,
        auto_opened=True,
    )


@bp.post("/park-ops/inspection-item-results/<result_id>/record")
@require_roles("MaintenanceTechnician")
def record_item_result(result_id):
    result = fetch.item_result(result_id)
    data = validate.body()
    outcome = validate.enum_field(data, "outcome", OUTCOMES)
    note = validate.str_field(data, "note", required=False, allow_empty=True)
    if outcome == "NA" and result["severity_class"] == "SAFETY_CRITICAL":
        invalid("A SAFETY_CRITICAL checklist line may never be waived as NA.")

    inspection = store.db.inspections.get(result["inspection_id"])
    previous = result["outcome"]
    status = inspection["status"]
    if previous == "PENDING":
        allowed = status in RECORDING_STATES
    elif previous == "FAIL" and outcome == "PASS":
        allowed = status in RECORDING_STATES
    elif previous == "PASS" and outcome == "FAIL":
        allowed = status in ("IN_PROGRESS", "BLOCKED", "PENDING_SIGN_OFF")
    else:
        allowed = False
    if not allowed:
        fail(ERR_INSPECTION_STATE_INVALID,
             "This outcome may not be recorded against the inspection in its "
             "current state.")

    if (outcome == "FAIL" and result["severity_class"] == "ESSENTIAL"
            and not (note or "").strip()):
        fail(ERR_ESSENTIAL_FAIL_NOTE_REQUIRED,
             "A FAIL on an ESSENTIAL line requires a non-empty note.")

    item = store.db.checklist_items.get(result["checklist_item_id"])
    component = None
    if item is not None and item.get("component_id"):
        component = store.db.components.get(item["component_id"])
    attraction = store.db.attractions.get(inspection["attraction_id"])

    result["outcome"] = outcome
    result["note"] = note
    result["recorded_by_user_id"] = g.user_id
    result["recorded_at"] = store.now_iso()
    if g.user_id not in inspection["recorded_by_user_ids"]:
        inspection["recorded_by_user_ids"].append(g.user_id)

    if outcome == "FAIL":
        # Hop one: any FAIL on a component-bound line flags that component.
        if component is not None:
            component["condition_flag"] = "SUSPECT"
        if (result["severity_class"] == "SAFETY_CRITICAL"
                and inspection["status"] == "IN_PROGRESS"):
            # Hops two, three and four.
            inspection["status"] = "BLOCKED"
            _open_auto_downtime(attraction)
    elif (outcome == "PASS" and previous == "FAIL"
          and result["severity_class"] == "SAFETY_CRITICAL"
          and inspection["status"] == "BLOCKED"
          and derive.blocking_item_count(inspection) == 0):
        # The compensating leg: the last blocking line has been cleared.
        inspection["status"] = "IN_PROGRESS"
        if component is not None and not _other_failures_reference(
                component["id"], result["id"]):
            component["condition_flag"] = "OK"

    return saved(derive.ser_item_result, result)
