"""Payer plans (PRD 3.1) and the patient chart (PRD 3.1), plus the clock."""
from flask import Blueprint

import calc
import common
import envelope
import shape
import store
from errors import ApiError

bp = Blueprint("registry", __name__)

PLAN_CODE_RE = r"^[A-Z0-9-]{3,20}$"
MRN_RE = r"^MRN-[0-9]{5}$"

POLICY_TERMS = [
    ("requires_prior_auth", shape.v_bool(), True),
    ("min_medical_management_days", shape.v_int(0, 180), 28),
    ("requires_ct_within_months", shape.v_int(1, 60), 12),
    ("min_documented_criteria", shape.v_int(1, 6), 3),
    ("max_balloon_devices", shape.v_int(1, 6), 2),
    ("covered_pct_bps", shape.v_int(0, 10000), 8000),
    ("allergy_serum_covered", shape.v_bool(), True),
    ("observation_floor_minutes", shape.v_int(0, 120), 20),
    ("device_trial_days", shape.v_int(1, 120), 30),
    ("restock_fee_bps", shape.v_int(0, 10000), 1500),
    ("restock_fee_floor_cents", shape.v_int(0, 500000), 12500),
    ("auth_validity_days", shape.v_int(1, 365), 90),
    ("appliance_covered", shape.v_bool(), True),
]


# --- payer plans -------------------------------------------------------------
@bp.post("/payer-policies")
def create_policy():
    common.begin(["PracticeAdmin"])
    spec = [
        ("payer_name", True, shape.v_string(1, 120), False),
        ("plan_code", True, shape.v_string(3, 20, PLAN_CODE_RE), False),
    ]
    for name, check, _default in POLICY_TERMS:
        spec.append((name, False, check, False))
    values, _provided = shape.read_body(spec)

    for row in store.rows("payer_policies"):
        if row["plan_code"] == values["plan_code"]:
            raise ApiError("ERR_DUPLICATE_PLAN_CODE")

    fields = {
        "payer_name": values["payer_name"],
        "plan_code": values["plan_code"],
    }
    for name, _check, default in POLICY_TERMS:
        fields[name] = values.get(name, default)
    row = common.new_row("payer_policies", fields)
    return envelope.created(common.public("payer_policies", row))


@bp.get("/payer-policies/<policy_id>")
def read_policy(policy_id):
    common.begin(shape.ALL_ROLES)
    shape.read_query({})
    shape.no_body()
    row = common.find("payer_policies", policy_id)
    return envelope.ok(common.public("payer_policies", row))


@bp.patch("/payer-policies/<policy_id>")
def amend_policy(policy_id):
    common.begin(["PracticeAdmin"])
    spec = [(name, False, check, False) for name, check, _d in POLICY_TERMS]
    values, provided = shape.read_body(spec)
    row = common.find("payer_policies", policy_id)
    for name in provided:
        row[name] = values[name]
    common.touch(row)
    return envelope.ok(common.public("payer_policies", row))


# --- patients ---------------------------------------------------------------
@bp.post("/patients")
def create_patient():
    common.begin(["PracticeAdmin"])
    values, provided = shape.read_body([
        ("payer_policy_id", True, shape.v_ref(), False),
        ("mrn", True, shape.v_string(9, 9, MRN_RE), False),
        ("full_name", True, shape.v_string(1, 120), False),
        ("date_of_birth", True, shape.v_date(), False),
        ("antihistamine_last_dose_at", False, shape.v_instant(), True),
        ("epinephrine_on_file", False, shape.v_bool(), False),
        ("prior_systemic_reaction_count", False, shape.v_int(0, 10), False),
    ])
    dob = store.parse_date(values["date_of_birth"])
    if dob > store.today():
        shape.bad("date_of_birth may not fall after the current logical clock date")

    common.find_ref("payer_policies", values["payer_policy_id"])

    for row in store.rows("patients"):
        if row["mrn"] == values["mrn"]:
            raise ApiError("ERR_DUPLICATE_MRN")

    row = common.new_row("patients", {
        "payer_policy_id": values["payer_policy_id"],
        "mrn": values["mrn"],
        "full_name": values["full_name"],
        "date_of_birth": values["date_of_birth"],
        "age_months": 0,
        "antihistamine_last_dose_at": values.get("antihistamine_last_dose_at"),
        "epinephrine_on_file": values.get("epinephrine_on_file", False),
        "dermatographism": False,
        "prior_systemic_reaction_count": values.get("prior_systemic_reaction_count", 0),
        "sensitized_antigen_count": 0,
        "risk_score": 0,
        "risk_score_variant": "PROVISIONAL",
        "supervision_tier": "STANDARD",
        "immunotherapy_escalation_step": 1,
        "immunotherapy_status": "NONE",
        "last_dose_administered_at": None,
    })
    row["age_months"] = calc.age_months(row)
    calc.rescore_patient(row)
    return envelope.created(common.public("patients", row))


@bp.get("/patients/<patient_id>")
def read_patient(patient_id):
    common.begin(shape.ALL_ROLES)
    shape.read_query({})
    shape.no_body()
    row = common.find("patients", patient_id)
    return envelope.ok(common.public("patients", row))


@bp.get("/patients")
def list_patients():
    common.begin(shape.ALL_ROLES)
    filters = shape.read_query({
        "payer_policy_id": shape.q_string(),
        "immunotherapy_status": shape.q_enum(calc.IMMUNO_STATUSES),
        "supervision_tier": shape.q_enum(calc.SUPERVISION_TIERS),
    })
    limit, offset = shape.pagination()
    shape.no_body()
    items = common.sorted_rows("patients", lambda r: common.matches(r, filters))
    page = common.paginate(items, limit, offset)
    return envelope.listing(
        [common.public("patients", r) for r in page], limit, offset, len(items)
    )


@bp.patch("/patients/<patient_id>")
def update_patient(patient_id):
    common.begin(["PracticeAdmin", "AllergyNurse"])
    values, provided = shape.read_body([
        ("antihistamine_last_dose_at", False, shape.v_instant(), True),
        ("epinephrine_on_file", False, shape.v_bool(), False),
        ("prior_systemic_reaction_count", False, shape.v_int(0, 10), False),
    ])
    row = common.find("patients", patient_id)
    for name in provided:
        row[name] = values[name]
    row["age_months"] = calc.age_months(row)
    calc.rescore_patient(row)
    common.touch(row)
    return envelope.ok(common.public("patients", row))


# --- the logical clock ------------------------------------------------------
@bp.post("/_clock/set_current_utc")
def set_clock():
    common.begin(["PracticeAdmin"])
    values, _provided = shape.read_body([
        ("current_utc", True, shape.v_instant(), False),
    ])
    store.set_clock(store.parse_instant(values["current_utc"]))
    return envelope.ok({"current_utc": values["current_utc"]})
