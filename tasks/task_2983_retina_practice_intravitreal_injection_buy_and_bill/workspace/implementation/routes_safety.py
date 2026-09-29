"""Adverse events, lot recalls and recall notifications. PRD 3.9."""
from flask import Blueprint, g

import core
from core import (
    DB,
    Field,
    READ_ROLES,
    ROLE_COMPLIANCE,
    ROLE_PATIENT,
    ROLE_RETINA,
    ROLE_TECH,
    ROLE_BILLING,
    ROLE_ADMIN,
    add_days,
    base_row,
    created,
    fail,
    get_adverse_event,
    get_body,
    get_encounter,
    get_lot,
    get_notification,
    get_recall,
    listing,
    ok,
    pagination,
    query_filters,
    touch,
    validate,
)
from domain import (
    LOT_CLUSTER_THRESHOLD,
    PLAN_TREATABLE,
    RECALL_CLASS_DAYS,
    apply_reportability,
    generate_recall_notifications,
    lot_vials,
    open_recall_for_lot,
    recompute_endophthalmitis_count,
    recompute_lot_counters,
    recount_notifications,
    suspend_plan,
    void_draft_encounters,
)

bp = Blueprint("safety", __name__)

EVENT_TYPES = ["ENDOPHTHALMITIS", "IOP_SPIKE", "RETINAL_DETACHMENT", "INTRAOCULAR_INFLAMMATION"]
SEVERITIES = ["MILD", "MODERATE", "SEVERE"]
CULTURE_RESULTS = ["PENDING", "POSITIVE", "NEGATIVE"]
EVENT_STATUSES = [
    "REPORTED",
    "UNDER_INVESTIGATION",
    "ADJUDICATED_RELATED",
    "ADJUDICATED_UNRELATED",
]
OUTCOMES = ["RELATED", "UNRELATED"]
RECALL_CLASSES = ["CLASS_I", "CLASS_II", "CLASS_III"]
RECALL_STATUSES = [
    "INITIATED",
    "PATIENTS_NOTIFIED",
    "RETURN_SHIPPED",
    "CREDIT_RECONCILED",
    "CLOSED",
]
NOTIFICATION_STATUSES = ["PENDING", "SENT", "ACKNOWLEDGED", "UNREACHABLE"]
NOTIFICATION_CHANNELS = ["SMS", "EMAIL", "PHONE"]
ALL_ROLES_READ = READ_ROLES + [ROLE_PATIENT]


# --------------------------------------------------------------- adverse events
@bp.post("/adverse-events")
@core.api([ROLE_RETINA])
def create_adverse_event():
    body = get_body()
    values = validate(
        body,
        [
            Field("injection_encounter_id", "id", required=True),
            Field("event_type", "enum", required=True, values=EVENT_TYPES),
            Field("onset_datetime", "datetime", required=True),
            Field("severity", "enum", required=True, values=SEVERITIES),
            Field("culture_result", "enum", values=CULTURE_RESULTS, default="PENDING"),
        ],
    )
    enc = get_encounter(values["injection_encounter_id"])
    vial = DB.vials.get(enc["vial_id"])
    lot_id = vial["drug_lot_id"] if vial is not None else None

    row = base_row()
    row.update(
        {
            "injection_encounter_id": enc["id"],
            "patient_id": enc["patient_id"],
            "reported_by_clinician_id": g.user_id,
            "adjudicated_by_clinician_id": None,
            "source_drug_lot_id": lot_id,
            "event_type": values["event_type"],
            "onset_datetime": values["onset_datetime"],
            "severity": values["severity"],
            "culture_result": values["culture_result"],
            "days_post_injection": 0,
            "reportable": False,
            "fda_report_due_date": None,
            "status": "REPORTED",
            "adjudication_note": None,
        }
    )
    apply_reportability(row, enc)
    DB.adverse_events[row["id"]] = row
    return created(row)


@bp.get("/adverse-events/<aid>")
@core.api(READ_ROLES)
def read_adverse_event(aid):
    return ok(get_adverse_event(aid))


@bp.get("/adverse-events")
@core.api(READ_ROLES)
def list_adverse_events():
    limit, offset = pagination()
    filters = query_filters(
        {
            "injection_encounter_id": ("injection_encounter_id", "string"),
            "patient_id": ("patient_id", "string"),
            "reported_by_clinician_id": ("reported_by_clinician_id", "string"),
            "adjudicated_by_clinician_id": ("adjudicated_by_clinician_id", "string"),
            "source_drug_lot_id": ("source_drug_lot_id", "string"),
            "event_type": ("event_type", "enum", EVENT_TYPES),
            "severity": ("severity", "enum", SEVERITIES),
            "status": ("status", "enum", EVENT_STATUSES),
        }
    )
    return listing(DB.adverse_events.values(), filters, limit, offset)


@bp.post("/adverse-events/<aid>/start-investigation")
@core.api([ROLE_COMPLIANCE])
def start_investigation(aid):
    get_body()
    event = get_adverse_event(aid)
    if event["status"] != "REPORTED":
        fail("ERR_ADVERSE_EVENT_STATE_INVALID", "only a REPORTED event may be investigated")
    event["status"] = "UNDER_INVESTIGATION"
    touch(event)
    return ok(event)


@bp.post("/adverse-events/<aid>/adjudicate")
@core.api([ROLE_RETINA])
def adjudicate_adverse_event(aid):
    body = get_body()
    values = validate(
        body,
        [
            Field("outcome", "enum", required=True, values=OUTCOMES),
            Field("adjudication_note", "string", required=True, minlen=1),
        ],
    )
    event = get_adverse_event(aid)
    encounter = DB.encounters[event["injection_encounter_id"]]
    if encounter["clinician_id"] == g.user_id:  # step 10
        fail("ERR_ADJUDICATOR_IS_INJECTOR", "the injector may not adjudicate their own event")
    if event["status"] != "UNDER_INVESTIGATION":  # step 13
        fail("ERR_ADVERSE_EVENT_STATE_INVALID", "only an event under investigation may be judged")

    event["adjudicated_by_clinician_id"] = g.user_id
    event["adjudication_note"] = values["adjudication_note"]
    apply_reportability(event, encounter)

    if values["outcome"] == "UNRELATED":
        event["status"] = "ADJUDICATED_UNRELATED"
        touch(event)
        return ok(event)

    event["status"] = "ADJUDICATED_RELATED"
    touch(event)

    plan = DB.plans.get(encounter["treatment_plan_id"])
    if plan is not None:
        if plan["status"] in PLAN_TREATABLE:
            suspend_plan(plan, "ADVERSE_EVENT")
        elif plan["status"] == "SUSPENDED":
            void_draft_encounters(plan, "PLAN_SUSPENDED")

    if event["event_type"] == "ENDOPHTHALMITIS" and event["source_drug_lot_id"]:
        lot = DB.lots.get(event["source_drug_lot_id"])
        if lot is not None:
            count = recompute_endophthalmitis_count(lot)
            if count >= LOT_CLUSTER_THRESHOLD and lot["status"] == "AVAILABLE":
                lot["status"] = "QUARANTINED"
                lot["quarantine_reason"] = "ENDOPHTHALMITIS_CLUSTER"
                touch(lot)
                for vial in lot_vials(lot["id"]):
                    if vial["status"] == "IN_STOCK":
                        vial["status"] = "QUARANTINED"
                        touch(vial)
                recompute_lot_counters(lot)
    return ok(event)


# ------------------------------------------------------------------- recalls
@bp.post("/lot-recalls")
@core.api([ROLE_COMPLIANCE])
def create_recall():
    body = get_body()
    values = validate(
        body,
        [
            Field("drug_lot_id", "id", required=True),
            Field("recall_class", "enum", required=True, values=RECALL_CLASSES),
            Field("reason", "string", required=True, minlen=1),
        ],
    )
    lot = get_lot(values["drug_lot_id"])
    if lot["status"] not in ("AVAILABLE", "QUARANTINED"):  # step 13
        fail("ERR_LOT_STATE_INVALID", "a %s lot cannot be recalled" % lot["status"])
    if open_recall_for_lot(lot["id"]) is not None:  # step 40
        fail("ERR_RECALL_ALREADY_OPEN", "an open recall already exists for this lot")

    recall = base_row()
    recall.update(
        {
            "drug_lot_id": lot["id"],
            "recall_class": values["recall_class"],
            "reason": values["reason"],
            "status": "INITIATED",
            "initiated_by_user_id": g.user_id,
            "notification_deadline_date": add_days(
                DB.clock, RECALL_CLASS_DAYS[values["recall_class"]]
            ),
            "notifications_required": 0,
            "notifications_acknowledged": 0,
            "notifications_unreachable": 0,
            "vials_returned_count": 0,
            "credit_expected_cents": 0,
            "credit_received_cents": None,
            "carrier_reference": None,
            "closed_by_user_id": None,
            "closure_note": None,
        }
    )
    DB.recalls[recall["id"]] = recall

    lot["status"] = "RECALLED"
    touch(lot)
    reserved_encounters = []
    for vial in lot_vials(lot["id"]):
        if vial["status"] in ("IN_STOCK", "RESERVED"):
            if vial["status"] == "RESERVED" and vial["reserved_for_encounter_id"]:
                reserved_encounters.append(vial["reserved_for_encounter_id"])
            # The reservation pointer is deliberately left in place: PRD 3.5
            # keeps a quarantined-but-reserved vial out of a later release.
            vial["status"] = "QUARANTINED"
            touch(vial)
    recompute_lot_counters(lot)

    from domain import recompute_authorization_usage, refresh_last_encounter

    touched_authorizations = []
    touched_plans = []
    for enc_id in reserved_encounters:
        enc = DB.encounters.get(enc_id)
        if enc is None or enc["status"] != "DRAFT":
            continue
        enc["status"] = "VOIDED"
        enc["void_reason"] = "LOT_RECALLED"
        touch(enc)
        pa = DB.authorizations.get(enc.get("prior_authorization_id"))
        if pa is not None and pa not in touched_authorizations:
            touched_authorizations.append(pa)
        plan = DB.plans.get(enc["treatment_plan_id"])
        if plan is not None and plan not in touched_plans:
            touched_plans.append(plan)
    for pa in touched_authorizations:
        recompute_authorization_usage(pa)
    for plan in touched_plans:
        # PRD 3.3: last_encounter_id is "always the plan's non-VOIDED encounter
        # with the greatest encounter_datetime".
        if refresh_last_encounter(plan):
            touch(plan)

    generate_recall_notifications(recall, lot)
    return created(recall)


@bp.get("/lot-recalls/<rid>")
@core.api(READ_ROLES)
def read_recall(rid):
    return ok(get_recall(rid))


@bp.get("/lot-recalls")
@core.api(READ_ROLES)
def list_recalls():
    limit, offset = pagination()
    filters = query_filters(
        {
            "drug_lot_id": ("drug_lot_id", "string"),
            "recall_class": ("recall_class", "enum", RECALL_CLASSES),
            "status": ("status", "enum", RECALL_STATUSES),
        }
    )
    return listing(DB.recalls.values(), filters, limit, offset)


@bp.post("/lot-recalls/<rid>/send-notifications")
@core.api([ROLE_COMPLIANCE])
def send_notifications(rid):
    get_body()
    recall = get_recall(rid)
    if recall["status"] != "INITIATED":
        fail("ERR_RECALL_STATE_INVALID", "notifications are sent only from INITIATED")
    for row in DB.notifications.values():
        if row["lot_recall_id"] == recall["id"] and row["status"] == "PENDING":
            row["status"] = "SENT"
            row["sent_at"] = DB.clock
            touch(row)
    recall["status"] = "PATIENTS_NOTIFIED"
    touch(recall)
    return ok(recall)


@bp.post("/lot-recalls/<rid>/ship-return")
@core.api([ROLE_TECH])
def ship_return(rid):
    body = get_body()
    values = validate(body, [Field("carrier_reference", "string", required=True, minlen=1)])
    recall = get_recall(rid)
    if recall["status"] != "PATIENTS_NOTIFIED":
        fail("ERR_RECALL_STATE_INVALID", "the return ships only from PATIENTS_NOTIFIED")
    lot = DB.lots[recall["drug_lot_id"]]
    quarantined = [v for v in lot_vials(lot["id"]) if v["status"] == "QUARANTINED"]
    if not quarantined:
        fail("ERR_NO_QUARANTINED_VIALS", "the lot holds no quarantined vial to return")
    for vial in quarantined:
        vial["status"] = "RETURNED"
        touch(vial)
    recompute_lot_counters(lot)
    recall["carrier_reference"] = values["carrier_reference"]
    recall["vials_returned_count"] = int(lot["vials_returned"])
    recall["credit_expected_cents"] = int(lot["vials_returned"]) * int(
        lot["unit_acquisition_cost_cents"]
    )
    recall["status"] = "RETURN_SHIPPED"
    touch(recall)
    return ok(recall)


@bp.post("/lot-recalls/<rid>/reconcile-credit")
@core.api([ROLE_BILLING])
def reconcile_credit(rid):
    body = get_body()
    values = validate(body, [Field("credit_received_cents", "integer", required=True, minimum=0)])
    recall = get_recall(rid)
    if recall["status"] != "RETURN_SHIPPED":
        fail("ERR_RECALL_STATE_INVALID", "credit is reconciled only from RETURN_SHIPPED")
    if values["credit_received_cents"] > int(recall["credit_expected_cents"]):
        fail("ERR_CREDIT_EXCEEDS_EXPECTED", "the credit received exceeds the expected credit")
    recall["credit_received_cents"] = values["credit_received_cents"]
    recall["status"] = "CREDIT_RECONCILED"
    touch(recall)
    return ok(recall)


@bp.post("/lot-recalls/<rid>/close")
@core.api([ROLE_COMPLIANCE])
def close_recall(rid):
    body = get_body()
    values = validate(body, [Field("closure_note", "string", required=True, minlen=1)])
    recall = get_recall(rid)
    if recall["initiated_by_user_id"] == g.user_id:  # step 11
        fail("ERR_RECALL_CLOSER_CONFLICT", "the initiator may not close the recall")
    if recall["status"] != "CREDIT_RECONCILED":  # step 13
        fail("ERR_RECALL_STATE_INVALID", "closure is reachable only from CREDIT_RECONCILED")
    if int(recall["notifications_acknowledged"]) + int(recall["notifications_unreachable"]) != int(
        recall["notifications_required"]
    ):  # step 43
        fail("ERR_PATIENT_NOTIFICATIONS_INCOMPLETE", "some notifications are unresolved")
    recall["closure_note"] = values["closure_note"]
    recall["closed_by_user_id"] = g.user_id
    recall["status"] = "CLOSED"
    touch(recall)
    return ok(recall)


# ------------------------------------------------------------- notifications
@bp.get("/recall-notifications/<nid>")
@core.api(ALL_ROLES_READ)
def read_notification(nid):
    row = get_notification(nid)
    if g.role == ROLE_PATIENT and row["patient_id"] != g.user_id:  # step 8
        fail("ERR_NOT_NOTIFICATION_OWNER", "a patient may read only their own notifications")
    return ok(row)


@bp.get("/recall-notifications")
@core.api(ALL_ROLES_READ)
def list_notifications():
    limit, offset = pagination()
    filters = query_filters(
        {
            "lot_recall_id": ("lot_recall_id", "string"),
            "patient_id": ("patient_id", "string"),
            "injection_encounter_id": ("injection_encounter_id", "string"),
            "status": ("status", "enum", NOTIFICATION_STATUSES),
        }
    )
    if g.role == ROLE_PATIENT:  # step 8
        if "patient_id" in filters and filters["patient_id"] != g.user_id:
            fail("ERR_NOT_NOTIFICATION_OWNER", "a patient may list only their own notifications")
        filters["patient_id"] = g.user_id
    return listing(DB.notifications.values(), filters, limit, offset)


@bp.post("/recall-notifications/<nid>/acknowledge")
@core.api([ROLE_PATIENT])
def acknowledge_notification(nid):
    get_body()
    row = get_notification(nid)
    if row["patient_id"] != g.user_id:  # step 8
        fail("ERR_NOT_NOTIFICATION_OWNER", "only the owning patient may acknowledge")
    if row["status"] != "SENT":  # step 13
        fail("ERR_NOTIFICATION_STATE_INVALID", "only a SENT notification may be acknowledged")
    row["status"] = "ACKNOWLEDGED"
    row["acknowledged_at"] = DB.clock
    touch(row)
    recall = DB.recalls[row["lot_recall_id"]]
    recount_notifications(recall)
    touch(recall)
    return ok(row)


@bp.post("/recall-notifications/<nid>/mark-unreachable")
@core.api([ROLE_COMPLIANCE])
def mark_unreachable(nid):
    body = get_body()
    values = validate(body, [Field("attempt_note", "string", required=True, minlen=1)])
    row = get_notification(nid)
    if row["status"] != "SENT":
        fail("ERR_NOTIFICATION_STATE_INVALID", "only a SENT notification may be marked unreachable")
    row["status"] = "UNREACHABLE"
    row["attempt_note"] = values["attempt_note"]
    touch(row)
    recall = DB.recalls[row["lot_recall_id"]]
    recount_notifications(recall)
    touch(recall)
    return ok(row)
