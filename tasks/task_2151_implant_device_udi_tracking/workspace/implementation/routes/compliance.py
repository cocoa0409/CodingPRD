"""Registry reporting, field actions and recall outreach."""
from flask import Blueprint

import serialize
from auth import (
    ALL_ROLES,
    CIRC_CLINICIAN,
    COMPLIANCE_OFFICER,
    INVENTORY_LEAD,
    REVENUE_ANALYST,
    endpoint,
)
from calc import (
    CLASS_NOTICE_DAYS,
    REGISTRY_MIN_COMPLETENESS_SCORE,
    lot_in_action_scope,
    recall_exposure_cohort,
    registry_completeness_score,
    unit_in_action_scope,
)
from derive import (
    case_close_readiness,
    detach_reservation,
    lot_unit_conservation,
    recompute_catalog_available,
    recompute_notification_open_count,
    recompute_vendor_recall_open,
    set_custody,
)
from envelope import array_response, object_response
from errors import ApiError
from graph import (
    case_of_submission,
    catalog_of_lot,
    lots_of_catalog,
    notifications_of_action,
    units_of_lot,
)
from resolve import must
from store import (
    base_record,
    clock_dt,
    clock_iso,
    db,
    iso_like,
    ordered,
    parse_iso,
    plus_days,
    touch,
)
from validation import (
    apply_page,
    bad,
    body,
    filter_enum,
    filter_value,
    forbid,
    opt_str,
    pagination,
    req_dt,
    req_enum,
    req_str,
    req_str_array,
)

bp = Blueprint("compliance", __name__)

SUBMISSION_STATES = ("REQUIRED", "SUBMITTED", "ACCEPTED", "REJECTED", "EXEMPT")
ACTION_STATES = ("DRAFT", "PUBLISHED", "IN_REMEDIATION", "CLOSED")
NOTIFICATION_STATES = ("PENDING", "NOTIFIED", "ACKNOWLEDGED", "UNREACHABLE", "CLOSED")
SUBMISSION_READERS = [CIRC_CLINICIAN, COMPLIANCE_OFFICER, REVENUE_ANALYST]
RECALL_READERS = [COMPLIANCE_OFFICER, CIRC_CLINICIAN, INVENTORY_LEAD, REVENUE_ANALYST]


# ----------------------------------------------------- registry submissions
@bp.route("/udi/registry-submissions/<submission_id>", methods=["GET"])
@endpoint(SUBMISSION_READERS)
def get_submission(submission_id):
    return object_response(serialize.registry_submission(must("submission_id", submission_id)))


@bp.route("/udi/registry-submissions", methods=["GET"])
@endpoint(SUBMISSION_READERS)
def list_submissions():
    limit, offset = pagination()
    implant_record_id = filter_value("implant_record_id")
    status = filter_enum("status", SUBMISSION_STATES)
    rows = []
    for row in db.registry_submissions.values():
        if implant_record_id is not None and row["implant_record_id"] != implant_record_id:
            continue
        if status is not None and row["status"] != status:
            continue
        rows.append(row)
    page, total = apply_page(ordered(rows), limit, offset)
    return array_response([serialize.registry_submission(r) for r in page], limit, offset, total)


@bp.route("/udi/registry-submissions/<submission_id>/submit", methods=["POST"])
@endpoint([COMPLIANCE_OFFICER])
def submit_submission(submission_id):
    data = body()
    registry_code = req_str(data, "registry_code")

    submission = must("submission_id", submission_id)

    if submission["status"] not in ("REQUIRED", "REJECTED"):        # step 8
        raise ApiError("ERR_INVALID_LIFECYCLE_STATE", "The submission cannot be sent from here.")

    record = db.implant_records.get(submission["implant_record_id"])
    if record is None or record["status"] not in ("VERIFIED", "EXPLANTED"):
        raise ApiError("ERR_INVALID_RECORD_STATE", "The implant record cannot be reported.")

    if registry_completeness_score(submission) < REGISTRY_MIN_COMPLETENESS_SCORE:   # step 14
        raise ApiError("ERR_REGISTRY_SUBMISSION_INCOMPLETE", "completeness_score is below 80.")

    was_rejected = submission["status"] == "REJECTED"
    submission["status"] = "SUBMITTED"
    submission["submitted_at_utc"] = clock_iso()
    submission["registry_code"] = registry_code
    if was_rejected:
        submission["resubmission_count"] = submission.get("resubmission_count", 0) + 1
    touch(submission)
    case_close_readiness(case_of_submission(submission))
    return object_response(serialize.registry_submission(submission))


@bp.route("/udi/registry-submissions/<submission_id>/adjudicate", methods=["POST"])
@endpoint([COMPLIANCE_OFFICER])
def adjudicate_submission(submission_id):
    data = body()
    outcome = req_enum(data, "outcome", ("ACCEPTED", "REJECTED"))
    rejection_reason = opt_str(data, "rejection_reason")
    if outcome == "REJECTED" and rejection_reason is None:
        raise bad("rejection_reason is required for a REJECTED outcome.")

    submission = must("submission_id", submission_id)
    if submission["status"] != "SUBMITTED":                          # step 8
        raise ApiError("ERR_INVALID_LIFECYCLE_STATE", "Only a SUBMITTED submission adjudicates.")

    submission["status"] = outcome
    submission["adjudicated_at_utc"] = clock_iso()
    if outcome == "REJECTED":
        submission["rejection_reason"] = rejection_reason
    touch(submission)
    case_close_readiness(case_of_submission(submission))
    return object_response(serialize.registry_submission(submission))


# ------------------------------------------------------------ field actions
@bp.route("/udi/field-actions", methods=["POST"])
@endpoint([COMPLIANCE_OFFICER])
def create_field_action():
    data = body()
    vendor_id = req_str(data, "vendor_id")
    catalog_item_id = req_str(data, "catalog_item_id")
    action_code = req_str(data, "action_code")
    action_class = req_enum(data, "action_class", ("CLASS_I", "CLASS_II", "CLASS_III"))
    scope_type = req_enum(data, "scope_type", ("CATALOG", "LOT", "SERIAL_RANGE"))
    req_dt(data, "effective_from_utc")

    if scope_type == "LOT":
        lot_numbers = req_str_array(data, "lot_numbers")
        forbid(data, "serial_low", "unless scope_type is SERIAL_RANGE")
        forbid(data, "serial_high", "unless scope_type is SERIAL_RANGE")
        serial_low = serial_high = None
    elif scope_type == "SERIAL_RANGE":
        serial_low = req_str(data, "serial_low")
        serial_high = req_str(data, "serial_high")
        forbid(data, "lot_numbers", "unless scope_type is LOT")
        lot_numbers = None
    else:
        forbid(data, "lot_numbers", "unless scope_type is LOT")
        forbid(data, "serial_low", "unless scope_type is SERIAL_RANGE")
        forbid(data, "serial_high", "unless scope_type is SERIAL_RANGE")
        lot_numbers = None
        serial_low = serial_high = None

    vendor = must("vendor_id", vendor_id)
    item = must("catalog_item_id", catalog_item_id)

    for existing in db.field_actions.values():
        if existing["action_code"] == action_code:
            raise ApiError("ERR_DUPLICATE_IDENTIFIER", "action_code already exists.")

    record = base_record()
    record.update(
        {
            "vendor_id": vendor["id"],
            "catalog_item_id": item["id"],
            "action_code": action_code,
            "action_class": action_class,
            "scope_type": scope_type,
            "lot_numbers": list(lot_numbers) if lot_numbers else None,
            "serial_low": serial_low,
            "serial_high": serial_high,
            "status": "DRAFT",
            "effective_from_utc": data["effective_from_utc"],
            "published_at_utc": None,
            "implanted_cohort_size": 0,
            "on_hand_cohort_size": 0,
            "notification_open_count": 0,
        }
    )
    db.field_actions[record["id"]] = record
    return object_response(serialize.field_action(record), 201)


@bp.route("/udi/field-actions/<field_action_id>/publish", methods=["POST"])
@endpoint([COMPLIANCE_OFFICER])
def publish_field_action(field_action_id):
    action = must("field_action_id", field_action_id)
    if action["status"] != "DRAFT":                                  # step 8
        raise ApiError("ERR_INVALID_LIFECYCLE_STATE", "Only a DRAFT action can be published.")

    cohort = recall_exposure_cohort(action)

    action["status"] = "PUBLISHED"
    action["published_at_utc"] = clock_iso()
    action["implanted_cohort_size"] = cohort["implanted_cohort_size"]
    action["on_hand_cohort_size"] = cohort["on_hand_cohort_size"]
    touch(action)

    # four-hop cascade: lot -> unit -> reservation -> case readiness
    for lot in lots_of_catalog(action["catalog_item_id"]):
        if lot["status"] not in ("QUARANTINE", "AVAILABLE"):
            continue
        if not lot_in_action_scope(lot, action):
            continue
        lot["status"] = "RECALLED"
        touch(lot)
        for unit in units_of_lot(lot["id"]):
            if unit["custody_state"] not in ("QUARANTINED", "AVAILABLE", "RESERVED"):
                continue
            if unit["custody_state"] == "RESERVED":
                detach_reservation(unit, blocked=True)
            set_custody(unit, "RECALL_HOLD")
        lot_unit_conservation(lot)
        recompute_catalog_available(catalog_of_lot(lot))

    effective_from = parse_iso(action["effective_from_utc"])
    notice_days = CLASS_NOTICE_DAYS[action["action_class"]]
    for record in cohort["implanted_records"]:
        notification = base_record()
        notification.update(
            {
                "field_action_id": action["id"],
                "implant_record_id": record["id"],
                "patient_id": record["patient_id"],
                "status": "PENDING",
                "due_utc": iso_like(
                    plus_days(effective_from, notice_days), action["effective_from_utc"]
                ),
                "outcome_note": None,
                "escalation_level": 0,
            }
        )
        db.recall_notifications[notification["id"]] = notification

    vendor = db.vendors.get(action["vendor_id"])
    if action["action_class"] == "CLASS_I" and vendor is not None:
        vendor["standing"] = "HOLD"
        touch(vendor)
    recompute_notification_open_count(action)
    recompute_vendor_recall_open(vendor)
    return object_response(serialize.field_action(action))


@bp.route("/udi/field-actions/<field_action_id>/close", methods=["POST"])
@endpoint([COMPLIANCE_OFFICER])
def close_field_action(field_action_id):
    data = body()
    disposition = req_enum(data, "on_hand_disposition", ("RETURN_TO_VENDOR", "DISPOSE"))

    action = must("field_action_id", field_action_id)
    if action["status"] not in ("PUBLISHED", "IN_REMEDIATION"):      # step 8
        raise ApiError("ERR_INVALID_LIFECYCLE_STATE", "The action cannot be closed from here.")

    open_count = len([n for n in notifications_of_action(action["id"]) if n["status"] == "PENDING"])
    if open_count != 0:                                              # step 26
        raise ApiError("ERR_RECALL_REMEDIATION_INCOMPLETE", "Outreach is still open.")

    action["status"] = "CLOSED"
    touch(action)

    for notification in notifications_of_action(action["id"]):
        if notification["status"] in ("NOTIFIED", "ACKNOWLEDGED", "UNREACHABLE"):
            notification["status"] = "CLOSED"
            touch(notification)

    target = "RETURNED_TO_VENDOR" if disposition == "RETURN_TO_VENDOR" else "DISPOSED"
    for unit in ordered(db.device_units.values()):
        if unit["custody_state"] != "RECALL_HOLD":
            continue
        lot = db.lots.get(unit["lot_id"])
        if lot is None or not lot_in_action_scope(lot, action):
            continue
        set_custody(unit, target)

    vendor = db.vendors.get(action["vendor_id"])
    recompute_vendor_recall_open(vendor)
    if vendor is not None and vendor["recall_open_count"] == 0 and vendor["standing"] != "ACTIVE":
        vendor["standing"] = "ACTIVE"
        touch(vendor)
    return object_response(serialize.field_action(action))


@bp.route("/udi/field-actions/<field_action_id>", methods=["GET"])
@endpoint(ALL_ROLES)
def get_field_action(field_action_id):
    return object_response(serialize.field_action(must("field_action_id", field_action_id)))


@bp.route("/udi/field-actions", methods=["GET"])
@endpoint(ALL_ROLES)
def list_field_actions():
    limit, offset = pagination()
    vendor_id = filter_value("vendor_id")
    catalog_item_id = filter_value("catalog_item_id")
    status = filter_enum("status", ACTION_STATES)
    rows = []
    for row in db.field_actions.values():
        if vendor_id is not None and row["vendor_id"] != vendor_id:
            continue
        if catalog_item_id is not None and row["catalog_item_id"] != catalog_item_id:
            continue
        if status is not None and row["status"] != status:
            continue
        rows.append(row)
    page, total = apply_page(ordered(rows), limit, offset)
    return array_response([serialize.field_action(r) for r in page], limit, offset, total)


@bp.route("/udi/field-actions/<field_action_id>/exposure", methods=["GET"])
@endpoint(RECALL_READERS)
def field_action_exposure(field_action_id):
    action = must("field_action_id", field_action_id)
    cohort = recall_exposure_cohort(action)
    patient_ids = []
    for record in cohort["implanted_records"]:
        if record["patient_id"] not in patient_ids:
            patient_ids.append(record["patient_id"])
    return object_response(
        {
            "implanted_cohort_size": cohort["implanted_cohort_size"],
            "on_hand_cohort_size": cohort["on_hand_cohort_size"],
            "patient_ids": patient_ids,
            "implant_record_ids": [r["id"] for r in cohort["implanted_records"]],
            "notification_open_count": action.get("notification_open_count", 0),
        }
    )


# ------------------------------------------------------ recall notifications
@bp.route("/udi/recall-notifications/<notification_id>", methods=["GET"])
@endpoint(RECALL_READERS)
def get_notification(notification_id):
    return object_response(
        serialize.recall_notification(must("notification_id", notification_id))
    )


@bp.route("/udi/recall-notifications", methods=["GET"])
@endpoint(RECALL_READERS)
def list_notifications():
    limit, offset = pagination()
    field_action_id = filter_value("field_action_id")
    implant_record_id = filter_value("implant_record_id")
    patient_id = filter_value("patient_id")
    status = filter_enum("status", NOTIFICATION_STATES)
    rows = []
    for row in db.recall_notifications.values():
        if field_action_id is not None and row["field_action_id"] != field_action_id:
            continue
        if implant_record_id is not None and row["implant_record_id"] != implant_record_id:
            continue
        if patient_id is not None and row["patient_id"] != patient_id:
            continue
        if status is not None and row["status"] != status:
            continue
        rows.append(row)
    page, total = apply_page(ordered(rows), limit, offset)
    return array_response([serialize.recall_notification(r) for r in page], limit, offset, total)


@bp.route("/udi/recall-notifications/<notification_id>/resolve", methods=["POST"])
@endpoint([COMPLIANCE_OFFICER])
def resolve_notification(notification_id):
    data = body()
    outcome = req_enum(data, "outcome", ("NOTIFIED", "ACKNOWLEDGED", "UNREACHABLE"))
    outcome_note = opt_str(data, "outcome_note")

    notification = must("notification_id", notification_id)
    if notification["status"] != "PENDING":                          # step 8
        raise ApiError("ERR_INVALID_LIFECYCLE_STATE", "The notification is already resolved.")

    notification["status"] = outcome
    if outcome_note is not None:
        notification["outcome_note"] = outcome_note
    touch(notification)

    action = db.field_actions.get(notification["field_action_id"])
    recompute_notification_open_count(action)
    if action is not None and action["status"] == "PUBLISHED":
        action["status"] = "IN_REMEDIATION"
        touch(action)
    return object_response(serialize.recall_notification(notification))
