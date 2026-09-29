"""Batching cycles: creation, staging, need recomputation and the comparative decision."""

from flask import Blueprint

import auth
import calc
import cascades
import clock
import envelope
import services
import shape
import store
from errors import ApiError

bp = Blueprint("cycles", __name__)

CYCLE_STATUSES = ("OPEN_FOR_LOI", "OPEN_FOR_APPLICATIONS", "COMPLETENESS_WINDOW",
                  "COMPARATIVE_REVIEW", "DECIDED", "CLOSED")
NEXT_STAGE = {
    "OPEN_FOR_LOI": "OPEN_FOR_APPLICATIONS",
    "OPEN_FOR_APPLICATIONS": "COMPLETENESS_WINDOW",
    "COMPLETENESS_WINDOW": "COMPARATIVE_REVIEW",
    "DECIDED": "CLOSED",
}
WINDOW_FIELDS = ("loi_deadline_at", "application_deadline_at", "comment_period_closes_at",
                 "intervention_deadline_at", "completeness_deadline_at", "decision_deadline_at")


def _apply_need(cycle_row, area, formula_row):
    cycle_row["pinned_formula_version"] = formula_row["version"]
    result = calc.need_methodology(area, formula_row)
    cycle_row.update(result)


@bp.post("/batching-cycles")
def create_cycle():
    auth.identity(["ProgramAdmin"])
    body = shape.body()
    hsa_id = shape.string_field(body, "hsa_id")
    formula_id = shape.string_field(body, "formula_id")
    service_type = shape.enum_field(body, "service_type", shape.SERVICE_TYPES)
    raw = {}
    parsed = {}
    for field in WINDOW_FIELDS:
        raw[field], parsed[field] = shape.instant_field(body, field)

    area = services.hsa(hsa_id)
    formula_row = services.formula(formula_id)

    if service_type != formula_row["service_type"]:
        raise ApiError("ERR_SERVICE_TYPE_MISMATCH",
                       "The cycle's service_type must equal the pinned formula's service_type.")

    new_start = parsed["application_deadline_at"]
    new_end = parsed["decision_deadline_at"]
    for other in store.rows("batching_cycles"):
        if other["hsa_id"] != hsa_id or other["service_type"] != service_type:
            continue
        if other["status"] == "CLOSED":
            continue
        other_start = clock.parse_instant(other["application_deadline_at"])
        other_end = clock.parse_instant(other["decision_deadline_at"])
        if max(new_start, other_start) <= min(new_end, other_end):
            raise ApiError("ERR_CYCLE_WINDOW_OVERLAP",
                           "The cycle review window intersects an existing cycle's window.")

    if not (parsed["loi_deadline_at"] < parsed["application_deadline_at"]
            <= parsed["comment_period_closes_at"] <= parsed["intervention_deadline_at"]
            <= parsed["completeness_deadline_at"] <= parsed["decision_deadline_at"]):
        raise ApiError("ERR_INVALID_CYCLE_WINDOW", "The cycle calendar is out of order.")

    fields = {
        "hsa_id": hsa_id,
        "formula_id": formula_id,
        "pinned_formula_version": formula_row["version"],
        "service_type": service_type,
    }
    for field in WINDOW_FIELDS:
        fields[field] = raw[field]
    fields.update({
        "projected_patient_days": None,
        "provisional_required_beds": None,
        "selected_target_occupancy_rate": None,
        "required_beds_final": None,
        "inventory_beds_at_open": None,
        "unmet_bed_need_at_open": None,
        "unallocated_bed_need": None,
        "reopened_count": 0,
        "status": "OPEN_FOR_LOI",
    })
    record = store.create("batching_cycles", fields)
    _apply_need(record, area, formula_row)
    return envelope.ok(record, 201)


@bp.get("/batching-cycles/<record_id>")
def read_cycle(record_id):
    auth.identity(auth.STAFF_AND_PARTIES)
    return envelope.ok(services.cycle(record_id))


@bp.get("/batching-cycles")
def list_cycles():
    auth.identity(auth.STAFF_AND_PARTIES)
    limit, offset = shape.pagination()
    picked = shape.filters("hsa_id", "formula_id", "service_type", "status")
    rows = shape.apply_filters(store.sort_created(store.rows("batching_cycles")), picked)
    return envelope.ok_list(rows[offset:offset + limit], limit, offset, len(rows))


@bp.post("/batching-cycles/<record_id>/advance")
def advance_cycle(record_id):
    auth.identity(["IntakeAnalyst"])
    body = shape.body()
    to_status = shape.enum_field(body, "to_status", CYCLE_STATUSES)
    cycle_row = services.cycle(record_id)

    if NEXT_STAGE.get(cycle_row["status"]) != to_status:
        raise ApiError("ERR_INVALID_CYCLE_STATUS_TRANSITION",
                       "Only the immediate successor stage may be named.")

    if to_status == "CLOSED":
        if services.cycle_has_pending_appeal(cycle_row):
            raise ApiError("ERR_APPEAL_PENDING",
                           "An appeal on an application of this cycle is still pending.")
        now = clock.now()
        for app in services.applications_of_cycle(cycle_row):
            closes = app.get("appeal_window_closes_at")
            if closes is None:
                continue
            if not now > clock.parse_instant(closes):
                raise ApiError("ERR_APPEAL_WINDOW_OPEN",
                               "An appeal window of a decided application is still open.")

    if to_status == "COMPARATIVE_REVIEW":
        applications = services.applications_of_cycle(cycle_row)
        if any(a["status"] in ("SUBMITTED", "COMPLETENESS_REVIEW") for a in applications):
            raise ApiError("ERR_CYCLE_HAS_UNRESOLVED_APPLICATIONS",
                           "An application of this cycle is still mid-intake.")
        app_ids = {a["id"] for a in applications}
        mandatory = any(
            i["status"] == "GRANTED" and i["requested_hearing"]
            and i["application_id"] in app_ids
            for i in store.rows("interventions"))
        if mandatory:
            held = any(h["batching_cycle_id"] == cycle_row["id"] and h["status"] == "HELD"
                       for h in store.rows("public_hearings"))
            if not held:
                raise ApiError("ERR_MANDATORY_HEARING_NOT_HELD",
                               "A granted intervention demanded a hearing that has not been held.")

    if to_status == "COMPLETENESS_WINDOW":
        for letter in store.rows("letters_of_intent"):
            if letter["batching_cycle_id"] == cycle_row["id"] and letter["status"] == "FILED":
                letter["status"] = "EXPIRED"
                store.touch(letter)
        for app in services.applications_of_cycle(cycle_row):
            if app["status"] == "DRAFT":
                app["status"] = "WITHDRAWN"
                store.touch(app)

    if to_status == "COMPARATIVE_REVIEW":
        now = clock.now()
        applications = services.applications_of_cycle(cycle_row)
        app_ids = {a["id"] for a in applications}
        for review in store.rows("completeness_reviews"):
            if (review["application_id"] in app_ids
                    and review["status"] == "DEFICIENCY_NOTICE_ISSUED"
                    and clock.parse_instant(review["cure_deadline_at"]) < now):
                review["status"] = "EXPIRED"
                store.touch(review)
        for app in applications:
            if app["status"] == "DEEMED_COMPLETE":
                app["status"] = "COMPARATIVE_REVIEW"
                store.touch(app)

    cycle_row["status"] = to_status
    store.touch(cycle_row)
    return envelope.ok(cycle_row)


@bp.post("/batching-cycles/<record_id>/recompute-need")
def recompute_need(record_id):
    auth.identity(["ProgramAdmin"])
    cycle_row = services.cycle(record_id)
    area = services.hsa(cycle_row["hsa_id"])
    formula_row = services.formula(cycle_row["formula_id"])
    _apply_need(cycle_row, area, formula_row)
    store.touch(cycle_row)
    return envelope.ok(cycle_row)


@bp.get("/batching-cycles/<record_id>/need-analysis")
def need_analysis(record_id):
    auth.identity(["ProgramAdmin", "IntakeAnalyst", "DecisionOfficer", "Applicant"])
    cycle_row = services.cycle(record_id)
    formula_row = store.get("state_plan_formulas", cycle_row["formula_id"])
    current_version = formula_row["version"] if formula_row else None
    return envelope.ok({
        "projected_patient_days": cycle_row["projected_patient_days"],
        "provisional_required_beds": cycle_row["provisional_required_beds"],
        "selected_target_occupancy_rate": cycle_row["selected_target_occupancy_rate"],
        "required_beds_final": cycle_row["required_beds_final"],
        "inventory_beds": cycle_row["inventory_beds_at_open"],
        "unmet_bed_need": cycle_row["unmet_bed_need_at_open"],
        "unallocated_bed_need": cycle_row["unallocated_bed_need"],
        "pinned_formula_version": cycle_row["pinned_formula_version"],
        "formula_current_version": current_version,
        "formula_pin_stale": cycle_row["pinned_formula_version"] != current_version,
    })


@bp.post("/batching-cycles/<record_id>/comparative-decision")
def comparative_decision(record_id):
    user_id, _role = auth.identity(["DecisionOfficer"])
    body = shape.body()
    shape.string_field(body, "decision_note", required=False, default=None)
    cycle_row = services.cycle(record_id)

    if cycle_row["status"] != "COMPARATIVE_REVIEW":
        raise ApiError("ERR_INVALID_CYCLE_STATUS_TRANSITION",
                       "The cycle is not in COMPARATIVE_REVIEW.")

    candidates = [a for a in services.applications_of_cycle(cycle_row)
                  if a["status"] in ("COMPARATIVE_REVIEW", "REMANDED")]

    for app in candidates:
        for sheet in services.sheets_of_application(app["id"], "ACTIVE"):
            if sheet["reviewer_user_id"] == user_id:
                raise ApiError("ERR_SEGREGATION_OF_DUTIES",
                               "A reviewer of this batch may not decide it.")

    formula_row = store.get("state_plan_formulas", cycle_row["formula_id"])
    if formula_row is None or cycle_row["pinned_formula_version"] != formula_row["version"]:
        raise ApiError("ERR_FORMULA_VERSION_STALE",
                       "The cycle's formula pin is stale; recompute need first.")

    if not candidates:
        raise ApiError("ERR_NO_ELIGIBLE_APPLICATIONS", "The candidate set is empty.")
    for app in candidates:
        if app["score_sheet_count"] < calc.MIN_SHEETS_FOR_DECISION:
            raise ApiError("ERR_INSUFFICIENT_SCORE_SHEETS",
                           "Every candidate needs at least 2 ACTIVE score sheets.")

    cascades.run_comparative_decision(cycle_row, candidates)
    return envelope.ok(cycle_row)
