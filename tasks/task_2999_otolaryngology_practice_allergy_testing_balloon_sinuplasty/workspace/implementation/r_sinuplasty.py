"""Balloon sinuplasty candidacy, authorization and the two revision loops (PRD 3.6)."""
from flask import Blueprint

import calc
import common
import envelope
import shape
import store
from errors import ApiError

bp = Blueprint("sinuplasty", __name__)

THERAPY_ITEM = shape.v_object({
    "therapy_code": (True, shape.v_enum(calc.THERAPY_CODES)),
    "start_date": (True, shape.v_date()),
    "end_date": (True, shape.v_date()),
})


def _check_therapies(name, value):
    items = shape.v_array(THERAPY_ITEM, non_empty=True)(name, value)
    for idx, item in enumerate(items):
        start = store.parse_date(item["start_date"])
        end = store.parse_date(item["end_date"])
        if start > end:
            shape.bad("%s[%d].start_date may not fall after its end_date" % (name, idx))
    return items


@bp.post("/sinuplasty-cases")
def create_case():
    common.begin(["Otolaryngologist"])
    values, _provided = shape.read_body([
        ("patient_id", True, shape.v_ref(), False),
        ("laterality", True, shape.v_enum(calc.LATERALITIES), False),
        ("sinuses", True,
         shape.v_array(shape.v_enum(calc.SINUSES), non_empty=True, distinct=True),
         False),
    ])
    patient = common.find_ref("patients", values["patient_id"])
    policy = common.policy_of_patient(patient)
    multiplier = 2 if values["laterality"] == "BILATERAL" else 1
    row = common.new_row("sinuplasty_cases", {
        "patient_id": patient["id"],
        "laterality": values["laterality"],
        "sinuses": values["sinuses"],
        "planned_device_count": len(values["sinuses"]) * multiplier,
        "ct_study_date": None,
        "documented_therapies": [],
        "documented_criteria_codes": [],
        "evaluation_variant": ("POLICY_STRICT" if policy["requires_prior_auth"]
                               else "CLINICAL_BROAD"),
        "criteria_met_count": 0,
        "contiguous_management_days": 0,
        "cumulative_management_days": 0,
        "candidacy_status": "UNDETERMINED",
        "status": "DRAFT",
        "revision_round": 0,
        "submitted_by_user_id": None,
        "pinned_policy_version": None,
        "authorized_device_count": 0,
        "auth_expires_at": None,
        "payer_reference": None,
        "documented_by_user_id": None,
    })
    return envelope.created(common.public("sinuplasty_cases", row))


@bp.get("/sinuplasty-cases/<case_id>")
def read_case(case_id):
    common.begin(shape.ALL_ROLES)
    shape.read_query({})
    shape.no_body()
    row = common.find("sinuplasty_cases", case_id)
    return envelope.ok(common.public("sinuplasty_cases", row))


@bp.get("/sinuplasty-cases")
def list_cases():
    common.begin(shape.ALL_ROLES)
    filters = shape.read_query({
        "patient_id": shape.q_string(),
        "status": shape.q_enum(calc.CASE_STATUSES),
        "candidacy_status": shape.q_enum(calc.CANDIDACY_STATUSES),
    })
    limit, offset = shape.pagination()
    shape.no_body()
    items = common.sorted_rows("sinuplasty_cases",
                               lambda r: common.matches(r, filters))
    page = common.paginate(items, limit, offset)
    return envelope.listing(
        [common.public("sinuplasty_cases", r) for r in page],
        limit, offset, len(items),
    )


@bp.post("/sinuplasty-cases/<case_id>/documentation")
def document_case(case_id):
    ctx = common.begin(["Otolaryngologist"])
    values, _provided = shape.read_body([
        ("ct_study_date", True, shape.v_date(), True),
        ("documented_therapies", True, _check_therapies, False),
        ("documented_criteria_codes", True,
         shape.v_array(shape.v_enum(calc.CRITERIA_CODES), non_empty=False), False),
    ])
    case = common.find("sinuplasty_cases", case_id)
    if case["status"] != "DRAFT":
        raise ApiError("ERR_CASE_STATE_INVALID")

    patient = store.db["patients"][case["patient_id"]]
    policy = common.policy_of_patient(patient)
    case["ct_study_date"] = values["ct_study_date"]
    case["documented_therapies"] = values["documented_therapies"]
    case["documented_criteria_codes"] = values["documented_criteria_codes"]
    case["status"] = "DOCUMENTED"
    case["documented_by_user_id"] = ctx.user_id
    result = calc.candidacy_evaluation(case, policy)
    case["criteria_met_count"] = result["criteria_met_count"]
    case["contiguous_management_days"] = result["contiguous_management_days"]
    case["cumulative_management_days"] = result["cumulative_management_days"]
    case["candidacy_status"] = result["candidacy_status"]
    common.touch(case)
    return envelope.ok(common.public("sinuplasty_cases", case))


@bp.get("/sinuplasty-cases/<case_id>/candidacy-evaluation")
def read_candidacy(case_id):
    common.begin(["PracticeAdmin", "Otolaryngologist", "PayerLiaison"])
    shape.read_query({})
    shape.no_body()
    case = common.find("sinuplasty_cases", case_id)
    patient = store.db["patients"][case["patient_id"]]
    policy = common.policy_of_patient(patient)
    result = calc.candidacy_evaluation(case, policy)
    if case["status"] == "DRAFT":
        result["candidacy_status"] = "UNDETERMINED"
    return envelope.ok({
        "evaluation_variant": result["evaluation_variant"],
        "criteria_met_count": result["criteria_met_count"],
        "admissible_criteria_codes": result["admissible_criteria_codes"],
        "contiguous_management_days": result["contiguous_management_days"],
        "cumulative_management_days": result["cumulative_management_days"],
        "management_days_metric": result["management_days_metric"],
        "min_documented_criteria_required": result["min_documented_criteria_required"],
        "min_medical_management_days_required":
            result["min_medical_management_days_required"],
        "candidacy_status": result["candidacy_status"],
    })


@bp.post("/sinuplasty-cases/<case_id>/authorization-submissions")
def submit_authorization(case_id):
    ctx = common.begin(["PayerLiaison"])
    shape.no_body()
    case = common.find("sinuplasty_cases", case_id)
    patient = store.db["patients"][case["patient_id"]]
    policy = common.policy_of_patient(patient)
    origin = case["status"]
    if origin == "DOCUMENTED":
        if not policy["requires_prior_auth"]:
            raise ApiError("ERR_CASE_STATE_INVALID")
        if case["candidacy_status"] != "ELIGIBLE":
            raise ApiError("ERR_CANDIDACY_NOT_ELIGIBLE")
    elif origin == "INFO_REQUESTED":
        if case["revision_round"] >= 2:
            raise ApiError("ERR_REVISION_LIMIT_REACHED")
        case["revision_round"] = case["revision_round"] + 1
    elif origin == "AUTH_EXPIRED":
        case["revision_round"] = 0
        case["authorized_device_count"] = 0
        case["auth_expires_at"] = None
    else:
        raise ApiError("ERR_CASE_STATE_INVALID")

    case["status"] = "AUTH_SUBMITTED"
    case["submitted_by_user_id"] = ctx.user_id
    case["pinned_policy_version"] = policy["version"]
    common.touch(case)
    return envelope.ok(common.public("sinuplasty_cases", case))


@bp.post("/sinuplasty-cases/<case_id>/payer-decisions")
def record_decision(case_id):
    ctx = common.begin(["PayerLiaison"])
    values, _provided = shape.read_body([
        ("decision", True, shape.v_enum(calc.DECISIONS), False),
        ("payer_reference", True, shape.v_string(1, 60), False),
    ])
    case = common.find("sinuplasty_cases", case_id)
    if case["status"] != "AUTH_SUBMITTED":
        raise ApiError("ERR_CASE_STATE_INVALID")
    if ctx.user_id == case["submitted_by_user_id"]:
        raise ApiError("ERR_SELF_DECISION_FORBIDDEN")

    patient = store.db["patients"][case["patient_id"]]
    policy = common.policy_of_patient(patient)
    case["payer_reference"] = values["payer_reference"]
    decision = values["decision"]
    if decision == "APPROVED":
        case["status"] = "AUTHORIZED"
        case["authorized_device_count"] = min(
            case["planned_device_count"], policy["max_balloon_devices"]
        )
        case["auth_expires_at"] = store.iso(
            store.plus_days(store.now(), policy["auth_validity_days"])
        )
    elif decision == "DENIED":
        case["status"] = "DENIED"
        case["authorized_device_count"] = 0
    else:
        case["status"] = "INFO_REQUESTED"
    common.touch(case)
    return envelope.ok(common.public("sinuplasty_cases", case))
