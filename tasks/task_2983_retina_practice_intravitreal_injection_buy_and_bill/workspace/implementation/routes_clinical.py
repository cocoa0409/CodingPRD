"""Imaging studies and treatment plans. PRD 3.2 and 3.3."""
from datetime import timedelta

from flask import Blueprint, g

import core
from core import (
    DB,
    Field,
    READ_ROLES,
    ROLE_RETINA,
    add_days,
    base_row,
    created,
    fail,
    get_body,
    get_drug,
    get_patient,
    get_plan,
    get_study,
    listing,
    ok,
    pagination,
    query_filters,
    touch,
    validate,
)
from domain import (
    CST_ACTIVE_THRESHOLD_UM,
    IMAGING_VALIDITY_DAYS,
    LOADING_INTERVAL_DAYS,
    PLAN_OPEN_STATUSES,
    plan_encounters,
    suspend_plan,
    void_draft_encounters,
)

bp = Blueprint("clinical", __name__)

EYES = ["OD", "OS"]
DISEASE_ACTIVITY = ["ACTIVE", "QUIESCENT"]
PLAN_STATUSES = ["DRAFT", "LOADING", "MAINTENANCE", "INTENSIFIED", "SUSPENDED", "DISCONTINUED"]
SUSPENSION_REASONS = ["ADVERSE_EVENT", "CLINICIAN_HOLD", "LOT_RECALL", "PATIENT_REQUEST"]


# ---------------------------------------------------------------- ImagingStudy
@bp.post("/imaging-studies")
@core.api([ROLE_RETINA])
def create_imaging_study():
    body = get_body()
    values = validate(
        body,
        [
            Field("patient_id", "id", required=True),
            Field("eye", "enum", required=True, values=EYES),
            Field("study_datetime", "datetime", required=True),
            Field(
                "central_subfield_thickness_um",
                "integer",
                required=True,
                minimum=100,
                maximum=900,
            ),
            Field("intraretinal_fluid", "boolean", required=True),
            Field("subretinal_fluid", "boolean", required=True),
            Field("new_hemorrhage", "boolean", required=True),
            Field("va_letter_score", "integer", required=True, minimum=0, maximum=100),
        ],
    )
    get_patient(values["patient_id"])

    active = (
        values["central_subfield_thickness_um"] >= CST_ACTIVE_THRESHOLD_UM
        or values["intraretinal_fluid"]
        or values["subretinal_fluid"]
        or values["new_hemorrhage"]
    )
    row = base_row(versioned=False)
    row.update(
        {
            "patient_id": values["patient_id"],
            "interpreted_by_clinician_id": g.user_id,
            "eye": values["eye"],
            "study_datetime": values["study_datetime"],
            "central_subfield_thickness_um": values["central_subfield_thickness_um"],
            "intraretinal_fluid": values["intraretinal_fluid"],
            "subretinal_fluid": values["subretinal_fluid"],
            "new_hemorrhage": values["new_hemorrhage"],
            "va_letter_score": values["va_letter_score"],
            "disease_activity": "ACTIVE" if active else "QUIESCENT",
        }
    )
    DB.imaging_studies[row["id"]] = row
    return created(row)


@bp.get("/imaging-studies/<sid>")
@core.api(READ_ROLES)
def read_imaging_study(sid):
    return ok(get_study(sid))


@bp.get("/imaging-studies")
@core.api(READ_ROLES)
def list_imaging_studies():
    limit, offset = pagination()
    filters = query_filters(
        {
            "patient_id": ("patient_id", "string"),
            "interpreted_by_clinician_id": ("interpreted_by_clinician_id", "string"),
            "interpreting_clinician_id": ("interpreted_by_clinician_id", "string"),
            "eye": ("eye", "enum", EYES),
            "disease_activity": ("disease_activity", "enum", DISEASE_ACTIVITY),
            "activity_classification": ("disease_activity", "enum", DISEASE_ACTIVITY),
        }
    )
    return listing(DB.imaging_studies.values(), filters, limit, offset)


# --------------------------------------------------------------- TreatmentPlan
@bp.post("/treatment-plans")
@core.api([ROLE_RETINA])
def create_treatment_plan():
    body = get_body()
    values = validate(
        body,
        [
            Field("patient_id", "id", required=True),
            Field("drug_id", "id", required=True),
            Field("eye", "enum", required=True, values=EYES),
            Field("loading_doses_required", "integer", minimum=1, maximum=6, default=3),
        ],
    )
    get_patient(values["patient_id"])
    get_drug(values["drug_id"])

    for row in DB.plans.values():
        if (
            row["patient_id"] == values["patient_id"]
            and row["eye"] == values["eye"]
            and row["status"] in PLAN_OPEN_STATUSES
        ):
            fail("ERR_DUPLICATE_ACTIVE_PLAN", "an open plan already exists for this eye")

    row = base_row()
    row.update(
        {
            "patient_id": values["patient_id"],
            "drug_id": values["drug_id"],
            "eye": values["eye"],
            "loading_doses_required": values["loading_doses_required"],
            "status": "DRAFT",
            "baseline_imaging_study_id": None,
            "current_interval_days": None,
            "next_due_date": None,
            "injections_administered": 0,
            "consecutive_quiescent_visits": 0,
            "last_encounter_id": None,
            "suspension_reason": None,
            "discontinuation_reason": None,
            "_activation_interval": None,
            "_activation_next_due": None,
        }
    )
    DB.plans[row["id"]] = row
    return created(row)


@bp.get("/treatment-plans/<pid>")
@core.api(READ_ROLES)
def read_treatment_plan(pid):
    return ok(get_plan(pid))


@bp.get("/treatment-plans")
@core.api(READ_ROLES)
def list_treatment_plans():
    limit, offset = pagination()
    filters = query_filters(
        {
            "patient_id": ("patient_id", "string"),
            "drug_id": ("drug_id", "string"),
            "baseline_imaging_study_id": ("baseline_imaging_study_id", "string"),
            "last_encounter_id": ("last_encounter_id", "string"),
            "status": ("status", "enum", PLAN_STATUSES),
            "eye": ("eye", "enum", EYES),
        }
    )
    return listing(DB.plans.values(), filters, limit, offset)


@bp.post("/treatment-plans/<pid>/activate")
@core.api([ROLE_RETINA])
def activate_treatment_plan(pid):
    body = get_body()
    values = validate(body, [Field("baseline_imaging_study_id", "id", required=True)])
    plan = get_plan(pid)
    study = get_study(values["baseline_imaging_study_id"])

    if plan["status"] != "DRAFT":
        fail("ERR_PLAN_STATE_INVALID", "only a DRAFT plan may be activated")
    patient = DB.patients[plan["patient_id"]]
    if patient["status"] != "ACTIVE":
        fail("ERR_PLAN_STATE_INVALID", "patient is not ACTIVE")
    drug = DB.drugs[plan["drug_id"]]
    if drug["status"] != "ACTIVE":
        fail("ERR_PLAN_STATE_INVALID", "drug is not ACTIVE")
    if study["disease_activity"] != "ACTIVE":
        fail("ERR_PLAN_STATE_INVALID", "baseline study is QUIESCENT")
    if study["patient_id"] != plan["patient_id"] or study["eye"] != plan["eye"]:
        fail("ERR_IMAGING_EYE_MISMATCH", "study patient or eye disagrees with the plan")
    delta = DB.clock - study["study_datetime"]
    if delta < timedelta(0) or delta > timedelta(days=IMAGING_VALIDITY_DAYS):
        fail("ERR_IMAGING_STUDY_STALE", "baseline study is outside its validity window")

    plan["status"] = "LOADING"
    plan["baseline_imaging_study_id"] = study["id"]
    plan["current_interval_days"] = LOADING_INTERVAL_DAYS
    plan["next_due_date"] = add_days(DB.clock, LOADING_INTERVAL_DAYS)
    plan["_activation_interval"] = LOADING_INTERVAL_DAYS
    plan["_activation_next_due"] = plan["next_due_date"]
    touch(plan)
    return ok(plan)


@bp.post("/treatment-plans/<pid>/suspend")
@core.api([ROLE_RETINA])
def suspend_treatment_plan(pid):
    body = get_body()
    values = validate(
        body, [Field("suspension_reason", "enum", required=True, values=SUSPENSION_REASONS)]
    )
    plan = get_plan(pid)
    if plan["status"] not in ("LOADING", "MAINTENANCE", "INTENSIFIED"):
        fail("ERR_PLAN_STATE_INVALID", "plan cannot be suspended from %s" % plan["status"])
    suspend_plan(plan, values["suspension_reason"])
    return ok(plan)


@bp.post("/treatment-plans/<pid>/resume")
@core.api([ROLE_RETINA])
def resume_treatment_plan(pid):
    get_body()
    plan = get_plan(pid)
    if plan["status"] != "SUSPENDED":
        fail("ERR_PLAN_STATE_INVALID", "only a SUSPENDED plan may be resumed")
    encounter_ids = {e["id"] for e in plan_encounters(plan["id"])}
    for event in DB.adverse_events.values():
        if event["injection_encounter_id"] in encounter_ids and event["status"] in (
            "REPORTED",
            "UNDER_INVESTIGATION",
        ):
            fail("ERR_OPEN_ADVERSE_EVENT", "an adverse event on this plan is still open")
    plan["status"] = "MAINTENANCE"
    plan["suspension_reason"] = None
    plan["next_due_date"] = add_days(DB.clock, plan["current_interval_days"])
    touch(plan)
    return ok(plan)


@bp.post("/treatment-plans/<pid>/discontinue")
@core.api([ROLE_RETINA])
def discontinue_treatment_plan(pid):
    body = get_body()
    values = validate(body, [Field("discontinuation_reason", "string", required=True, minlen=1)])
    plan = get_plan(pid)
    if plan["status"] not in PLAN_OPEN_STATUSES:
        fail("ERR_PLAN_STATE_INVALID", "plan is already DISCONTINUED")
    plan["status"] = "DISCONTINUED"
    plan["discontinuation_reason"] = values["discontinuation_reason"]
    plan["next_due_date"] = None
    touch(plan)
    void_draft_encounters(plan, "PLAN_DISCONTINUED")
    return ok(plan)
