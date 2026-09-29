"""Logical clock, payers, drugs, coverage policies, patients, clinicians.

PRD 2.5 and 3.1.
"""
from flask import Blueprint, g

import core
from core import (
    DB,
    Field,
    READ_ROLES,
    ROLE_ADMIN,
    base_row,
    created,
    fail,
    get_body,
    get_drug,
    get_patient,
    get_payer,
    get_clinician,
    get_policy,
    iso3,
    listing,
    ok,
    pagination,
    query_filters,
    touch,
    validate,
)
from domain import FEDERAL_PAYER_TYPES, policy_for

bp = Blueprint("reference", __name__)

PAYER_TYPES = ["COMMERCIAL", "MEDICARE_ADVANTAGE", "MEDICARE_PART_B", "MEDICAID"]
BIOSIMILAR_PREFERENCES = ["NONE", "PREFERRED", "MANDATORY"]
ACTIVE_INACTIVE = ["ACTIVE", "INACTIVE"]
VIAL_TYPES = ["SINGLE_DOSE", "MULTI_DOSE_COMPOUNDED"]
COVERAGE_TIERS = ["PREFERRED", "NON_PREFERRED", "EXCLUDED"]
CHANNELS = ["SMS", "EMAIL", "PHONE"]
CREDENTIALS = ["MD", "DO"]
CLINICIAN_STATUSES = ["ACTIVE", "SUSPENDED"]


# --------------------------------------------------------------- logical clock
@bp.post("/_clock/set_current_utc")
@core.api([ROLE_ADMIN])
def set_clock():
    body = get_body()
    values = validate(body, [Field("current_utc", "datetime", required=True)])
    DB.clock = values["current_utc"]
    return ok({"current_utc": iso3(DB.clock)})


# ----------------------------------------------------------------------- Payer
@bp.post("/payers")
@core.api([ROLE_ADMIN])
def create_payer():
    body = get_body()
    values = validate(
        body,
        [
            Field("name", "string", required=True, minlen=1, maxlen=120),
            Field("payer_type", "enum", required=True, values=PAYER_TYPES),
            Field("coinsurance_rate", "number", required=True, minimum=0, maximum=1, max_dp=4),
            Field("pa_required", "boolean", default=True),
            Field("biosimilar_preference", "enum", values=BIOSIMILAR_PREFERENCES, default="NONE"),
            Field("appeal_window_days", "integer", minimum=1, maximum=365, default=60),
        ],
    )
    for row in DB.payers.values():
        if row["name"] == values["name"]:
            fail("ERR_DUPLICATE_RESOURCE", "payer name already registered")
    row = base_row()
    row.update(
        {
            "name": values["name"],
            "payer_type": values["payer_type"],
            "federal_program": values["payer_type"] in FEDERAL_PAYER_TYPES,
            "coinsurance_rate": values["coinsurance_rate"],
            "pa_required": values["pa_required"],
            "biosimilar_preference": values["biosimilar_preference"],
            "appeal_window_days": values["appeal_window_days"],
            "status": "ACTIVE",
        }
    )
    DB.payers[row["id"]] = row
    return created(row)


@bp.get("/payers/<pid>")
@core.api(READ_ROLES)
def read_payer(pid):
    return ok(get_payer(pid))


@bp.get("/payers")
@core.api(READ_ROLES)
def list_payers():
    limit, offset = pagination()
    filters = query_filters(
        {
            "payer_type": ("payer_type", "enum", PAYER_TYPES),
            "status": ("status", "enum", ACTIVE_INACTIVE),
            "name": ("name", "string"),
            "federal_program": ("federal_program", "boolean"),
            "biosimilar_preference": ("biosimilar_preference", "enum", BIOSIMILAR_PREFERENCES),
        }
    )
    return listing(DB.payers.values(), filters, limit, offset)


# ------------------------------------------------------------------------ Drug
@bp.post("/drugs")
@core.api([ROLE_ADMIN])
def create_drug():
    body = get_body()
    values = validate(
        body,
        [
            Field("brand_name", "string", required=True, minlen=1, maxlen=120),
            Field("hcpcs_code", "string", required=True, minlen=5, maxlen=8),
            Field("vial_type", "enum", required=True, values=VIAL_TYPES),
            Field("vial_fill_ml", "number", required=True, gt=0, max_dp=3),
            Field("label_dose_ml", "number", required=True, gt=0, max_dp=3),
            Field("mg_per_ml", "number", required=True, gt=0),
            Field("billing_unit_mg", "number", required=True, gt=0),
            Field("asp_cents_per_billing_unit", "integer", required=True, minimum=0),
            Field("min_interval_days", "integer", required=True, minimum=1),
            Field("max_interval_days", "integer", required=True, minimum=1),
            Field("is_biosimilar", "boolean", default=False),
            Field("reference_drug_id", "id", default=None),
        ],
    )
    if values["label_dose_ml"] > values["vial_fill_ml"]:
        fail("ERR_INVALID_REQUEST", "label_dose_ml must not exceed vial_fill_ml")
    if values["max_interval_days"] < values["min_interval_days"]:
        fail("ERR_INVALID_REQUEST", "max_interval_days must be at least min_interval_days")

    reference = None
    if values["reference_drug_id"] is not None:
        reference = get_drug(values["reference_drug_id"])

    for row in DB.drugs.values():
        if row["hcpcs_code"] == values["hcpcs_code"]:
            fail("ERR_DUPLICATE_RESOURCE", "hcpcs_code already registered")

    if reference is not None and reference["is_biosimilar"]:
        fail("ERR_INVALID_REFERENCE_DRUG", "reference drug must not itself be a biosimilar")
    if values["is_biosimilar"] and values["reference_drug_id"] is None:
        fail("ERR_INVALID_REFERENCE_DRUG", "a biosimilar must name a reference drug")

    row = base_row()
    row.update(
        {
            "brand_name": values["brand_name"],
            "hcpcs_code": values["hcpcs_code"],
            "vial_type": values["vial_type"],
            "vial_fill_ml": values["vial_fill_ml"],
            "label_dose_ml": values["label_dose_ml"],
            "mg_per_ml": values["mg_per_ml"],
            "billing_unit_mg": values["billing_unit_mg"],
            "asp_cents_per_billing_unit": values["asp_cents_per_billing_unit"],
            "min_interval_days": values["min_interval_days"],
            "max_interval_days": values["max_interval_days"],
            "is_biosimilar": values["is_biosimilar"],
            "reference_drug_id": values["reference_drug_id"],
            "status": "ACTIVE",
        }
    )
    DB.drugs[row["id"]] = row
    return created(row)


@bp.get("/drugs/<did>")
@core.api(READ_ROLES)
def read_drug(did):
    return ok(get_drug(did))


@bp.get("/drugs")
@core.api(READ_ROLES)
def list_drugs():
    limit, offset = pagination()
    filters = query_filters(
        {
            "reference_drug_id": ("reference_drug_id", "string"),
            "is_biosimilar": ("is_biosimilar", "boolean"),
            "vial_type": ("vial_type", "enum", VIAL_TYPES),
            "status": ("status", "enum", ACTIVE_INACTIVE),
            "hcpcs_code": ("hcpcs_code", "string"),
        }
    )
    return listing(DB.drugs.values(), filters, limit, offset)


# -------------------------------------------------------------- coverage policy
@bp.post("/payer-drug-policies")
@core.api([ROLE_ADMIN])
def create_policy():
    body = get_body()
    values = validate(
        body,
        [
            Field("payer_id", "id", required=True),
            Field("drug_id", "id", required=True),
            Field("coverage_tier", "enum", required=True, values=COVERAGE_TIERS),
            Field(
                "drug_allowed_cents_per_billing_unit", "integer", required=True, minimum=0
            ),
            Field("admin_allowed_cents", "integer", required=True, minimum=0),
            Field("wastage_reimbursed", "boolean", default=False),
            Field("pa_required", "boolean", default=True),
            Field("pa_validity_days", "integer", minimum=1, maximum=730, default=180),
            Field("pa_max_injections", "integer", minimum=1, default=3),
            Field("step_therapy_prerequisite_drug_id", "id", default=None),
            Field("required_prior_failures", "integer", minimum=0, default=0),
        ],
    )
    get_payer(values["payer_id"])
    get_drug(values["drug_id"])
    if values["step_therapy_prerequisite_drug_id"] is not None:
        get_drug(values["step_therapy_prerequisite_drug_id"])

    if policy_for(values["payer_id"], values["drug_id"]) is not None:
        fail("ERR_DUPLICATE_RESOURCE", "a policy already exists for this payer and drug")

    row = base_row()
    row.update(
        {
            "payer_id": values["payer_id"],
            "drug_id": values["drug_id"],
            "coverage_tier": values["coverage_tier"],
            "drug_allowed_cents_per_billing_unit": values[
                "drug_allowed_cents_per_billing_unit"
            ],
            "admin_allowed_cents": values["admin_allowed_cents"],
            "wastage_reimbursed": values["wastage_reimbursed"],
            "pa_required": values["pa_required"],
            "pa_validity_days": values["pa_validity_days"],
            "pa_max_injections": values["pa_max_injections"],
            "step_therapy_prerequisite_drug_id": values["step_therapy_prerequisite_drug_id"],
            "required_prior_failures": values["required_prior_failures"],
        }
    )
    DB.policies[row["id"]] = row
    return created(row)


@bp.get("/payer-drug-policies/<pid>")
@core.api(READ_ROLES)
def read_policy(pid):
    return ok(get_policy(pid))


@bp.get("/payer-drug-policies")
@core.api(READ_ROLES)
def list_policies():
    limit, offset = pagination()
    filters = query_filters(
        {
            "payer_id": ("payer_id", "string"),
            "drug_id": ("drug_id", "string"),
            "step_therapy_prerequisite_drug_id": ("step_therapy_prerequisite_drug_id", "string"),
            "coverage_tier": ("coverage_tier", "enum", COVERAGE_TIERS),
            "pa_required": ("pa_required", "boolean"),
            "wastage_reimbursed": ("wastage_reimbursed", "boolean"),
        }
    )
    return listing(DB.policies.values(), filters, limit, offset)


# --------------------------------------------------------------------- Patient
@bp.post("/patients")
@core.api([ROLE_ADMIN])
def create_patient():
    body = get_body()
    values = validate(
        body,
        [
            Field("mrn", "string", required=True, minlen=4, maxlen=24),
            Field("full_name", "string", required=True, minlen=1),
            Field("payer_id", "id", required=True),
            Field("member_id", "string", required=True, minlen=1),
            Field("contact_point", "string", required=True, minlen=1),
            Field("notification_channel", "enum", values=CHANNELS, default="PHONE"),
        ],
    )
    get_payer(values["payer_id"])
    for row in DB.patients.values():
        if row["mrn"] == values["mrn"]:
            fail("ERR_DUPLICATE_RESOURCE", "mrn already registered")
    row = base_row()
    row.update(
        {
            "mrn": values["mrn"],
            "full_name": values["full_name"],
            "payer_id": values["payer_id"],
            "member_id": values["member_id"],
            "notification_channel": values["notification_channel"],
            "contact_point": values["contact_point"],
            "status": "ACTIVE",
        }
    )
    DB.patients[row["id"]] = row
    return created(row)


@bp.get("/patients/<pid>")
@core.api(READ_ROLES)
def read_patient(pid):
    return ok(get_patient(pid))


@bp.get("/patients")
@core.api(READ_ROLES)
def list_patients():
    limit, offset = pagination()
    filters = query_filters(
        {
            "payer_id": ("payer_id", "string"),
            "status": ("status", "enum", ACTIVE_INACTIVE),
            "mrn": ("mrn", "string"),
        }
    )
    return listing(DB.patients.values(), filters, limit, offset)


# ------------------------------------------------------------------- Clinician
@bp.post("/clinicians")
@core.api([ROLE_ADMIN])
def create_clinician():
    body = get_body()
    values = validate(
        body,
        [
            Field("full_name", "string", required=True, minlen=1),
            Field("npi", "string", required=True, digits=10),
            Field("credential", "enum", required=True, values=CREDENTIALS),
            Field("injection_privilege", "boolean", default=True),
            Field("max_injections_per_day", "integer", minimum=1, default=12),
        ],
    )
    for row in DB.clinicians.values():
        if row["npi"] == values["npi"]:
            fail("ERR_DUPLICATE_RESOURCE", "npi already registered")
    row = base_row()
    row.update(
        {
            "full_name": values["full_name"],
            "npi": values["npi"],
            "credential": values["credential"],
            "injection_privilege": values["injection_privilege"],
            "max_injections_per_day": values["max_injections_per_day"],
            "status": "ACTIVE",
            "suspension_reason": None,
        }
    )
    DB.clinicians[row["id"]] = row
    return created(row)


@bp.get("/clinicians/<cid>")
@core.api(READ_ROLES)
def read_clinician(cid):
    return ok(get_clinician(cid))


@bp.get("/clinicians")
@core.api(READ_ROLES)
def list_clinicians():
    limit, offset = pagination()
    filters = query_filters(
        {
            "status": ("status", "enum", CLINICIAN_STATUSES),
            "credential": ("credential", "enum", CREDENTIALS),
            "injection_privilege": ("injection_privilege", "boolean"),
            "npi": ("npi", "string"),
        }
    )
    return listing(DB.clinicians.values(), filters, limit, offset)


@bp.post("/clinicians/<cid>/suspend")
@core.api([ROLE_ADMIN])
def suspend_clinician(cid):
    body = get_body()
    values = validate(body, [Field("suspension_reason", "string", required=True, minlen=1)])
    clinician = get_clinician(cid)
    if clinician["status"] != "ACTIVE":
        fail("ERR_CLINICIAN_NOT_ELIGIBLE", "clinician is already suspended")
    clinician["status"] = "SUSPENDED"
    clinician["suspension_reason"] = values["suspension_reason"]
    touch(clinician)
    return ok(clinician)
