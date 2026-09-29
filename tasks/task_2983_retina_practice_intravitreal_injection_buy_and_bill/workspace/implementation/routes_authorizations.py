"""Prior authorizations: step therapy, decisions and appeals. PRD 3.4."""
from flask import Blueprint

import core
from core import (
    DB,
    Field,
    READ_ROLES,
    ROLE_BILLING,
    add_days,
    base_row,
    created,
    fail,
    get_authorization,
    get_body,
    get_plan,
    listing,
    ok,
    pagination,
    query_filters,
    touch,
    validate,
)
from domain import ENCOUNTER_COUNTED, policy_for

bp = Blueprint("authorizations", __name__)

AUTH_STATUSES = [
    "DRAFT",
    "SUBMITTED",
    "INFO_REQUESTED",
    "APPROVED",
    "DENIED",
    "APPEALED",
    "EXHAUSTED",
    "EXPIRED",
]
DECISIONS = ["APPROVED", "DENIED", "INFO_REQUESTED"]
DENIAL_REASONS = [
    "STEP_THERAPY",
    "NOT_MEDICALLY_NECESSARY",
    "NON_FORMULARY",
    "INCOMPLETE_DOCUMENTATION",
]


def occ_guard(plan, expected):
    """Validation 12: the stale-plan-version guard of PRD 2.6."""
    if int(expected) != int(plan["version"]):
        fail(
            "ERR_STALE_PLAN_VERSION",
            "expected_treatment_plan_version %s does not match %s"
            % (expected, plan["version"]),
        )


def count_step_therapy_failures(patient_id, prerequisite_drug_id):
    count = 0
    for enc in DB.encounters.values():
        if enc["patient_id"] != patient_id:
            continue
        if enc["status"] not in ENCOUNTER_COUNTED:
            continue
        if enc["effective_drug_id"] != prerequisite_drug_id:
            continue
        study = DB.imaging_studies.get(enc["imaging_study_id"])
        if study is None or study["disease_activity"] != "ACTIVE":
            continue
        count += 1
    return count


@bp.post("/prior-authorizations")
@core.api([ROLE_BILLING])
def create_authorization():
    body = get_body()
    values = validate(
        body,
        [
            Field("treatment_plan_id", "id", required=True),
            Field("expected_treatment_plan_version", "integer", required=True, minimum=1),
        ],
    )
    plan = get_plan(values["treatment_plan_id"])
    occ_guard(plan, values["expected_treatment_plan_version"])

    patient = DB.patients[plan["patient_id"]]
    row = base_row()
    row.update(
        {
            "treatment_plan_id": plan["id"],
            "patient_id": plan["patient_id"],
            "drug_id": plan["drug_id"],
            "payer_id": patient["payer_id"],
            "auth_number": None,
            "status": "DRAFT",
            "approved_injections": None,
            "injections_used": 0,
            "effective_date": None,
            "expiration_date": None,
            "clinical_justification": None,
            "information_requested": None,
            "denial_reason": None,
            "appeal_basis": None,
            "submission_count": 0,
            "step_therapy_failures_documented": 0,
        }
    )
    DB.authorizations[row["id"]] = row
    touch(plan)
    return created(row)


@bp.get("/prior-authorizations/<aid>")
@core.api(READ_ROLES)
def read_authorization(aid):
    return ok(get_authorization(aid))


@bp.get("/prior-authorizations")
@core.api(READ_ROLES)
def list_authorizations():
    limit, offset = pagination()
    filters = query_filters(
        {
            "treatment_plan_id": ("treatment_plan_id", "string"),
            "patient_id": ("patient_id", "string"),
            "payer_id": ("payer_id", "string"),
            "drug_id": ("drug_id", "string"),
            "status": ("status", "enum", AUTH_STATUSES),
        }
    )
    return listing(DB.authorizations.values(), filters, limit, offset)


@bp.post("/prior-authorizations/<aid>/submit")
@core.api([ROLE_BILLING])
def submit_authorization(aid):
    body = get_body()
    values = validate(body, [Field("clinical_justification", "string", required=True, minlen=1)])
    pa = get_authorization(aid)
    if pa["status"] not in ("DRAFT", "INFO_REQUESTED"):
        fail("ERR_AUTHORIZATION_STATE_INVALID", "cannot submit from %s" % pa["status"])

    policy = policy_for(pa["payer_id"], pa["drug_id"])
    if policy is None:
        fail("ERR_PAYER_POLICY_MISSING", "no coverage policy for this payer and drug")
    if policy["coverage_tier"] == "EXCLUDED":
        fail("ERR_DRUG_EXCLUDED_BY_PAYER", "the payer excludes this product")

    prerequisite = policy["step_therapy_prerequisite_drug_id"]
    if prerequisite is None:
        failures = 0
    else:
        failures = count_step_therapy_failures(pa["patient_id"], prerequisite)
        if failures < int(policy["required_prior_failures"]):
            fail("ERR_STEP_THERAPY_NOT_SATISFIED", "documented failures are insufficient")

    pa["clinical_justification"] = values["clinical_justification"]
    pa["step_therapy_failures_documented"] = failures
    pa["submission_count"] = int(pa["submission_count"]) + 1
    if pa["status"] == "INFO_REQUESTED":
        pa["information_requested"] = None
    pa["status"] = "SUBMITTED"
    touch(pa)
    return ok(pa)


@bp.post("/prior-authorizations/<aid>/decision")
@core.api([ROLE_BILLING])
def decide_authorization(aid):
    body = get_body()
    values = validate(
        body,
        [
            Field("decision", "enum", required=True, values=DECISIONS),
            Field("information_requested", "string", minlen=1),
            Field("denial_reason", "enum", values=DENIAL_REASONS),
            Field("auth_number", "string", minlen=1),
            Field("approved_injections", "integer", minimum=1),
            Field("effective_date", "datetime"),
        ],
    )
    decision = values["decision"]
    if decision == "INFO_REQUESTED" and values["information_requested"] is None:
        fail("ERR_INVALID_REQUEST", "information_requested is required for INFO_REQUESTED")
    if decision == "DENIED" and values["denial_reason"] is None:
        fail("ERR_INVALID_REQUEST", "denial_reason is required for DENIED")
    if decision == "APPROVED":
        for name in ("auth_number", "approved_injections", "effective_date"):
            if values[name] is None:
                fail("ERR_INVALID_REQUEST", "%s is required for APPROVED" % name)

    pa = get_authorization(aid)
    if pa["status"] not in ("SUBMITTED", "APPEALED"):
        fail("ERR_AUTHORIZATION_STATE_INVALID", "no decision is accepted from %s" % pa["status"])

    if decision == "INFO_REQUESTED":
        pa["information_requested"] = values["information_requested"]
        pa["status"] = "INFO_REQUESTED"
        touch(pa)
        return ok(pa)

    if decision == "DENIED":
        pa["denial_reason"] = values["denial_reason"]
        pa["status"] = "DENIED"
        touch(pa)
        return ok(pa)

    policy = policy_for(pa["payer_id"], pa["drug_id"])
    if policy is None:
        fail("ERR_PAYER_POLICY_MISSING", "no coverage policy for this payer and drug")
    if values["approved_injections"] > int(policy["pa_max_injections"]):
        fail(
            "ERR_APPROVED_INJECTIONS_EXCEED_POLICY",
            "approved_injections exceeds the policy maximum",
        )

    start = values["effective_date"]
    end = add_days(start, policy["pa_validity_days"])
    for other in DB.authorizations.values():
        if other["id"] == pa["id"]:
            continue
        if other["treatment_plan_id"] != pa["treatment_plan_id"]:
            continue
        if other["status"] not in ("APPROVED", "EXHAUSTED"):
            continue
        if other["effective_date"] is None or other["expiration_date"] is None:
            continue
        if start <= other["expiration_date"] and other["effective_date"] <= end:
            fail("ERR_AUTHORIZATION_WINDOW_OVERLAP", "coverage window overlaps another")

    pa["auth_number"] = values["auth_number"]
    pa["approved_injections"] = values["approved_injections"]
    pa["effective_date"] = start
    pa["expiration_date"] = end
    pa["denial_reason"] = None
    pa["status"] = "APPROVED"
    touch(pa)
    return ok(pa)


@bp.post("/prior-authorizations/<aid>/appeal")
@core.api([ROLE_BILLING])
def appeal_authorization(aid):
    body = get_body()
    values = validate(body, [Field("appeal_basis", "string", required=True, minlen=1)])
    pa = get_authorization(aid)
    if pa["status"] != "DENIED":
        fail("ERR_AUTHORIZATION_STATE_INVALID", "only a DENIED authorization may be appealed")
    payer = DB.payers[pa["payer_id"]]
    deadline = add_days(pa["updated_at"], payer["appeal_window_days"])
    if DB.clock > deadline:
        fail("ERR_APPEAL_WINDOW_CLOSED", "the payer's appeal window has closed")
    pa["appeal_basis"] = values["appeal_basis"]
    pa["status"] = "APPEALED"
    touch(pa)
    return ok(pa)
